"""End-to-end synthetic SiK/MAVLink passive-decode pipeline over one sub-GHz
dwell window (T4).

``decode_sik_window`` wires together, in order: burst detection (T1's
:func:`aerix_rf.detect.bursts.detect_bursts`, over an STFT built here) ->
per-burst rate/GFSK demod (:mod:`aerix_rf.decode.sik.gfsk`, T1) -> sync
search -> hardware-frame deframe (:mod:`aerix_rf.decode.sik.frame`, T2) ->
hop-raster/NETID evidence (:mod:`aerix_rf.decode.sik.raster`, T4) ->
MAVLink parse, gated (:mod:`aerix_rf.decode.sik.mavlink`, T3).

**Evidence level 1 (synthetic).** Every stage below is validated only
against this project's own synthetic generator (:mod:`aerix_rf.decode.sik.synth`
plus the MAVLink test encoder). This module does NOT demonstrate decoding a
real SiK radio -- see each stage's own module docstring for its specific
inferred/unverified assumptions (sync word value, CRC coverage/byte order,
tdm_trailer endianness). A result from this pipeline must never be reported
as hardware-proven.

**Evidence mapping** (design doc S2, "Evidence mapping"):
  * level 1 ``sub_ghz_burst_candidate`` -- >=1 burst detected in the dwell.
  * level 2 ``sik_like_hopper_candidate`` -- raster evidence is
    ``consistent`` (S1 legal (spacing, N) pair, within tolerance) AND
    ``n_bursts >= 5``.
  * level 3 ``sik_netid_confirmed`` -- the *same* NETID recovered (from
    CRC-valid frame headers, not the brute-force NETID search -- S2: "Do not
    brute-force NETID ... it is in the header in clear") on
    ``>= SIK_NETID_MIN_FRAMES`` CRC-valid frames across
    ``>= SIK_NETID_MIN_CHANNELS`` distinct channels.
  * level 4 ``sik_mavlink_confirmed`` -- only on a MAVLink CRC + CRC_EXTRA
    pass (:class:`aerix_rf.decode.sik.mavlink.MavlinkMessage.crc_ok`), and
    only when ``flag_third_party_mavlink`` is True (mirrors
    ``decode.third_party_mavlink``, default off -- design doc S3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import scipy.fft as sfft
from scipy.signal import firwin, upfirdn

from aerix_rf.detect.bursts import BurstEvent, detect_bursts

from . import raster as sik_raster
from .frame import SikFrame, deframe
from .gfsk import demod_gfsk, estimate_rate, find_sync
from .mavlink import MavlinkMessage, SikMavlinkDecoder
from .synth import SIK_AIR_RATES_BPS, _DEFAULT_SYNC_WORD, nominal_h

DEFAULT_SYNC_WORD = _DEFAULT_SYNC_WORD  # 0x2DD4, INFERRED (see synth.py docstring)

SIK_NETID_MIN_FRAMES = 5     # level-3 gate (design doc S2 "Evidence mapping")
SIK_NETID_MIN_CHANNELS = 3
SIK_HOPPER_MIN_BURSTS = 5    # level-2 gate

_FFT_SIZE = 1024
_N_AVG = 6                   # power-averaged FFT frames per detector frame (see below)
_BURST_GUARD_S = 100e-6      # padding added each side of a detected burst before demod
_BURST_GUARD_MAX_S = 500e-6  # cap on that padding (>= one detector frame)
_MAX_RATE_HYPOTHESES = 3     # estimated air rate + its two legal neighbours
_MAX_BURSTS = 128            # per-window event cap (detect_bursts' own default is 64,
                             # which a 40-hop dwell can legitimately exceed)

# detect_bursts()'s GATE_DB/HYST_DB defaults (6/3 dB over the per-bin floor,
# aerix_rf/detect/bursts.py) are calibrated for D8's *block-averaged* 200 us
# detector frames (aerix_rf.datasets.tensor.detector_frames, factor 6), whose
# per-bin power is Erlang-6 rather than exponential. A single-look periodogram
# (factor 1) has a 5.6 dB power standard deviation, for which those same dB
# thresholds give a per-pixel arm false-alarm rate of ~1.9%
# (``exp(-10**(6/10))``) -- enough to flood a multi-second dwell with pure-noise
# "bursts" (observed: the 64-event cap reached on a 0.2 s noise-only capture),
# and raising the thresholds far enough to suppress that (13/9 dB) eats most of
# the margin a real burst has over the floor. This pipeline therefore averages
# ``_N_AVG`` FFT frames into one detector frame (matching D8's factor 6), which
# both restores the intended statistics and improves the -6 dB edge/centre
# estimate; the gates are then set from the Erlang-6 tail rather than inherited:
# with a median-based floor (median/mean = 0.955 at 6 looks), an arm gate of
# 9 dB gives P(false arm) ~ 2e-14/pixel (<1e-8 expected over a 1 s dwell) and a
# 6 dB hold gives ~8e-6/pixel -- and a hold pixel only becomes an event if its
# component also contains an arm pixel. A synthetic SiK burst at 20 dB in-band
# SNR peaks ~24 dB over the floor in these frames, so the 9 dB arm keeps ~15 dB
# of margin. Both remain arguments to :func:`decode_sik_window` for retuning
# against real captures.
_GATE_DB = 9.0
_HYST_DB = 6.0

# Centre refinement (see _refine_centre_hz): half-width of the search window
# around the detector's centre, and the resolution of the burst periodogram.
_CENTRE_WIN_HZ = 250e3
_CENTRE_RES_HZ = 6e3
_CENTRE_MAX_SEGMENTS = 16    # bounded per-burst cost for the centroid periodogram

# Per-burst channel rate after the down-conversion in _ddc_burst(). The widest
# SiK air rate (250 kbps, h~1.27) has an OBW98 of ~0.82 MHz, so a 2 MHz channel
# keeps every legal rate with margin for the centre-estimate error, while
# cutting the per-burst rate-estimation/demod cost by the decimation factor
# (7x at 15.36 MS/s). demod_gfsk decimates again internally, per rate.
_CHANNEL_FS_MIN_HZ = 2.0e6
_DDC_TAPS_PER_DECIM = 6

# ---------------------------------------------------------------------------
# STFT framing (D8-style: linear power [n_frames, n_bins], explicit floor)
# ---------------------------------------------------------------------------

def _stft_power_lin(iq: np.ndarray, fs: float, fft_size: int = _FFT_SIZE,
                    n_avg: int = _N_AVG):
    """Non-overlapping STFT, power-averaged ``n_avg`` frames at a time ->
    ``(power_lin [T,F], freqs_hz [F] baseband, frame_dt_s)``. Deliberately
    simple (no target-frame-count adaptation like
    :mod:`aerix_rf.dsp.spectrogram`) -- this pipeline needs a fixed, known
    frame cadence to feed :func:`detect_bursts`, not a display image.

    The ``n_avg`` block average is what makes the detector-frame statistics
    match the gating thresholds (see ``_GATE_DB``/``_HYST_DB`` above): it is
    the same factor-6 incoherent average as D8's 200 us detector frames. The
    resulting frame period (``n_avg*fft_size/fs``, 400 us at 15.36 MS/s) must
    stay well under the shortest SiK burst of interest -- a 64 kbps SiK frame
    is milliseconds long, so this is not the binding constraint.
    """
    iq = np.asarray(iq, dtype=np.complex64)
    n = iq.size
    need = fft_size * n_avg
    if n < need:
        iq = np.pad(iq, (0, need - n))
    win = np.hanning(fft_size).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(iq, fft_size)[::fft_size]
    n_blocks = len(frames) // n_avg
    frames = frames[: n_blocks * n_avg]
    # scipy.fft (not np.fft) so a complex64 input stays single-precision:
    # numpy always promotes to complex128, which doubles both the FFT cost and
    # the memory traffic of the largest array this pipeline touches.
    spec = sfft.fftshift(sfft.fft(frames * win, axis=1, workers=-1), axes=1)
    power = (spec.real ** 2 + spec.imag ** 2).astype(np.float64) / (fft_size ** 2)
    power = power.reshape(n_blocks, n_avg, fft_size).mean(axis=1)
    freqs_hz = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / fs))
    frame_dt_s = n_avg * fft_size / fs
    return power, freqs_hz.astype(np.float64), frame_dt_s


def _refine_centre_hz(iq: np.ndarray, fs: float, centre_hz: float, event: BurstEvent,
                      *, win_hz: float = _CENTRE_WIN_HZ, res_hz: float = _CENTRE_RES_HZ,
                      n_iter: int = 3) -> float:
    """Re-estimate a burst's centre frequency as the noise-subtracted spectral
    centroid of its own samples, iterated so the search window ends up
    centred on the estimate.

    Why this is needed: :func:`detect_bursts` reports a **-6 dB edge-midpoint**
    centre, which is the right estimator for a single-lobe burst but not for
    wide-deviation 2-FSK. A SiK burst at h~2 has a *bimodal* spectrum with
    tones at +/-h*rate/2 (+/-64 kHz at 64 kbps); whichever tone is stronger in
    a given frame's data wins the peak search and the -6 dB walk terminates in
    the dip between the tones, so the reported centre collapses onto one tone
    (measured here: -54 kHz +/- 2 kHz systematic on the synthetic 64 kbps
    fixture, i.e. ~0.2 of the 250 kHz channel spacing). A power centroid over
    the burst's whole occupied band is symmetric in the tones and does not
    have that failure mode.

    The centroid is taken over bins within ``win_hz`` of the current centre
    estimate that exceed 4x the burst-slice noise floor (median of the whole
    slice spectrum), so out-of-channel noise does not pull it toward the dwell
    centre. ``win_hz`` must stay below the narrowest expected channel spacing:
    a *simultaneous* neighbouring emitter inside the window would bias this
    estimate (a real, unmodelled risk in crowded spectrum -- one SiK link
    transmits alone, a second link in the same dwell does not).
    """
    i0 = max(0, int(round(event.t_start * fs)))
    i1 = min(len(iq), int(round(event.t_end * fs)))
    seg = iq[i0:i1]
    nfft = int(2 ** np.ceil(np.log2(max(fs / res_hz, 16.0))))
    if len(seg) < nfft:
        return float(event.centre_hz)
    hop = nfft // 2
    n_seg = (len(seg) - nfft) // hop + 1
    if n_seg > _CENTRE_MAX_SEGMENTS:   # bounded cost: a longer burst is
        hop = (len(seg) - nfft) // (_CENTRE_MAX_SEGMENTS - 1)   # sub-sampled,
        n_seg = _CENTRE_MAX_SEGMENTS                            # not averaged in full
    win = np.hanning(nfft).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(seg, nfft)[::hop][:n_seg]
    spec = sfft.fft(frames * win, axis=1, workers=-1)
    power = sfft.fftshift((spec.real ** 2 + spec.imag ** 2).astype(np.float64).mean(axis=0))
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / fs)) + centre_hz
    floor = float(np.median(power))
    above = power > 4.0 * floor
    est = float(event.centre_hz)
    for _ in range(max(1, n_iter)):
        mask = above & (np.abs(freqs - est) <= win_hz)
        q = np.where(mask, power - floor, 0.0)
        total = q.sum()
        if total <= 0:
            return est
        new = float((freqs * q).sum() / total)
        if abs(new - est) < 100.0:
            est = new
            break
        est = new
    return est


# ---------------------------------------------------------------------------
# Per-burst demod + deframe
# ---------------------------------------------------------------------------

@dataclass
class BurstDecodeResult:
    event: BurstEvent
    centre_hz: Optional[float] = None   # refined FSK-aware centre (see _refine_centre_hz);
                                        # event.centre_hz keeps the detector's -6 dB midpoint
    rate_bps: Optional[float] = None
    frame: Optional[SikFrame] = None
    sync_hit: Optional[tuple] = None
    error: Optional[str] = None


def _normalize_payload_bits(bits: np.ndarray, inverted: bool, bit_order: str) -> np.ndarray:
    b = (1 - bits) if inverted else bits
    if bit_order == "lsb":
        n = len(b) - (len(b) % 8)
        b = b[:n].reshape(-1, 8)[:, ::-1].reshape(-1)
    return b


def _ddc_burst(seg: np.ndarray, fs: float, rel_hz: float):
    """Digital down-conversion of one burst: shift ``rel_hz`` to DC and
    decimate to >= ``_CHANNEL_FS_MIN_HZ``. Returns ``(channel_iq, fs_channel)``.

    The mixing is folded into the anti-alias filter (bandpass decimation:
    ``h[n] = lowpass[n] * exp(+j2*pi*rel*n/fs)``, decimate, then one residual
    ``exp(-j2*pi*rel*m/fs_channel)`` at the *decimated* rate), so no
    full-rate complex exponential or full-rate temporary is ever formed --
    the only full-rate work is the polyphase FIR, which computes taps only at
    the kept output samples. Everything downstream (rate estimation, the GFSK
    front end's own per-rate decimation) then runs at the channel rate.
    """
    decim = int(fs // _CHANNEL_FS_MIN_HZ)
    if decim < 2 or len(seg) < 4 * decim:
        t = np.arange(len(seg), dtype=np.float64) / fs
        return (seg * np.exp(-1j * 2.0 * np.pi * rel_hz * t)).astype(np.complex64), fs
    fs_ch = fs / decim
    ntaps = (_DDC_TAPS_PER_DECIM * decim) | 1
    # Cutoff at fs_ch/2: the band that must survive is the widest SiK OBW
    # (+/-0.45 MHz) and the first alias folds in from fs_ch - 0.45 MHz, so the
    # transition may be ~1.1 MHz wide -- hence the short tap count.
    lp = firwin(ntaps, 0.5 * fs_ch, fs=fs, window=("kaiser", 7.0))
    n = np.arange(ntaps) - (ntaps - 1) // 2
    bp = lp * np.exp(1j * 2.0 * np.pi * rel_hz * n / fs)
    y = upfirdn(bp, np.asarray(seg, dtype=np.complex64), 1, decim)
    m = np.arange(len(y), dtype=np.float64)
    y = y * np.exp(-1j * 2.0 * np.pi * rel_hz * m / fs_ch)
    return y.astype(np.complex64), fs_ch


def _decode_one_burst(iq: np.ndarray, fs: float, centre_hz: float,
                       event: BurstEvent, sync_word: int,
                       burst_centre_hz: Optional[float] = None) -> BurstDecodeResult:
    if burst_centre_hz is None:
        burst_centre_hz = float(event.centre_hz)
    # The detector's frame span already brackets the burst (t_start is the
    # start of the first armed frame, t_end the end of the last), so the guard
    # only has to cover the frame quantisation plus filter transients; a
    # duration-proportional guard just pays full-rate DDC cost for noise.
    guard = min(max(_BURST_GUARD_S, 0.25 * event.duration_s), _BURST_GUARD_MAX_S)
    i0 = max(0, int(round((event.t_start - guard) * fs)))
    i1 = min(len(iq), int(round((event.t_end + guard) * fs)))
    if i1 - i0 < 64:
        return BurstDecodeResult(event=event, centre_hz=burst_centre_hz, error="segment too short")
    seg = iq[i0:i1]

    # Bring the burst's estimated (absolute) centre to ~baseband and down to a
    # channel rate: demod_gfsk's internal CFO search is only +/-25 kHz
    # (gfsk.py docstring), far narrower than a hop set's channel spacing.
    rel_hz = burst_centre_hz - centre_hz
    seg_bb, fs_ch = _ddc_burst(seg, fs, rel_hz)

    try:
        rate_bps = estimate_rate(seg_bb, fs_ch)
    except Exception as exc:  # keep one bad burst from aborting the window
        return BurstDecodeResult(event=event, centre_hz=burst_centre_hz,
                                  error=f"rate estimation failed: {exc}")

    # estimate_rate matches the measured OBW against the 13 legal air rates in
    # log bandwidth; adjacent legal rates are only a factor 1.5 apart (64 vs
    # 96 kbps), so a noisy burst occasionally lands one step off (observed:
    # 1 burst in 40 at 20 dB in-band SNR on the synthetic fixture). The
    # receiver does not know the link's rate a priori, so retry the immediate
    # neighbours before declaring the burst undecodable -- a CRC-valid frame
    # at a neighbouring rate is self-validating, and each retry only costs a
    # demod on an already-channelised few-ms segment.
    rates = list(SIK_AIR_RATES_BPS)
    i = rates.index(rate_bps) if rate_bps in rates else -1
    candidates = [rate_bps] + ([rates[j] for j in (i - 1, i + 1) if 0 <= j < len(rates)]
                               if i >= 0 else [])
    last_error = "no sync"
    for rate in candidates[:_MAX_RATE_HYPOTHESES]:
        try:
            bits, _info = demod_gfsk(seg_bb, fs_ch, rate, nominal_h(rate))
        except Exception as exc:  # keep one bad burst from aborting the window
            last_error = f"demod failed: {exc}"
            continue
        if len(bits) < 48:
            last_error = "too few symbols"
            continue
        hits = find_sync(bits, sync_word)
        if not hits:
            continue
        last_error = "no CRC-valid frame"
        for off, inverted, order in hits:
            payload_start = off + 16
            if payload_start >= len(bits):
                continue
            norm = _normalize_payload_bits(bits[payload_start:], inverted, order)
            frame = deframe(norm, sync_offset=0)
            if frame is not None and frame.crc_ok:
                return BurstDecodeResult(event=event, centre_hz=burst_centre_hz, rate_bps=rate,
                                          frame=frame, sync_hit=(off, inverted, order))
    return BurstDecodeResult(event=event, centre_hz=burst_centre_hz, rate_bps=rate_bps,
                              error=last_error)


# ---------------------------------------------------------------------------
# Window-level pipeline
# ---------------------------------------------------------------------------

def decode_sik_window(
    iq: np.ndarray,
    fs: float,
    centre_hz: float,
    band: str,
    flag_third_party_mavlink: bool = False,
    *,
    sync_word: int = DEFAULT_SYNC_WORD,
    fft_size: int = _FFT_SIZE,
    n_avg: int = _N_AVG,
    gate_db: float = _GATE_DB,
    hysteresis_db: float = _HYST_DB,
    max_events: int = _MAX_BURSTS,
) -> Dict[str, Any]:
    """Run the full T1-T4 chain over one dwell's raw IQ. Evidence level 1
    (synthetic) -- see module docstring. ``iq`` is complex baseband sampled
    at ``fs`` around RF ``centre_hz``; ``band`` selects the legal-raster
    table (``"sik915"``/``"sik868"``/``"sik433"``, see
    :mod:`aerix_rf.decode.sik.raster`).
    """
    iq = np.asarray(iq, dtype=np.complex64)
    power_lin, freqs_bb_hz, frame_dt_s = _stft_power_lin(iq, fs, fft_size, n_avg)
    freqs_abs_hz = freqs_bb_hz + centre_hz
    # Explicit per-bin noise floor (median over time): with a sparse hop set
    # (a handful of ms-scale bursts in a multi-second dwell) almost every
    # frame is pure noise, so the median is robust and does not need
    # detect_bursts' internal 5th-percentile fallback.
    floor_lin = np.median(power_lin, axis=0)

    events = detect_bursts(
        power_lin, fs=fs, frame_dt_s=frame_dt_s, freqs_hz=freqs_abs_hz,
        noise_floor_lin=floor_lin, iq=iq, iq_fs=fs,
        gate_db=gate_db, hysteresis_db=hysteresis_db, max_events=max_events,
    )

    # FSK-aware centre re-estimate per burst (the detector's -6 dB edge
    # midpoint is biased onto one tone for h~2 2-FSK -- see _refine_centre_hz).
    # Everything downstream that needs a frequency (mixing to baseband, the
    # hop raster, the distinct-channel count) uses this, not event.centre_hz.
    centres_hz = [_refine_centre_hz(iq, fs, centre_hz, ev) for ev in events]

    n_bursts = len(events)
    labels = {
        "sub_ghz_burst_candidate": n_bursts > 0,
        "sik_like_hopper_candidate": False,
        "sik_netid_confirmed": False,
        "sik_mavlink_confirmed": False,
    }
    notes: List[str] = []

    burst_results: List[BurstDecodeResult] = [
        _decode_one_burst(iq, fs, centre_hz, ev, sync_word, burst_centre_hz=c)
        for ev, c in zip(events, centres_hz)
    ]
    valid_frames = [r for r in burst_results if r.frame is not None]

    raster_ev = sik_raster.estimate_sik_raster(
        centres_hz, band
    ) if events else sik_raster.SikRasterEvidence(
        band=band, spacing_hz=None, offset_hz=None, n_channels=None,
        n_channel_clusters=0, rayleigh_r=0.0, p_false=1.0,
        consistent=False, insufficient=True, notes=["no bursts detected"],
    )

    if raster_ev.consistent and n_bursts >= SIK_HOPPER_MIN_BURSTS:
        labels["sik_like_hopper_candidate"] = True

    # NETID confirmation: from CRC-valid frame *headers* (in clear), not the
    # raster/brute-force NETID search (S2).
    by_netid: Dict[int, List[BurstDecodeResult]] = {}
    for r in valid_frames:
        by_netid.setdefault(r.frame.netid, []).append(r)

    confirmed_netid: Optional[int] = None
    for netid, results in by_netid.items():
        n_channels = len({round((r.centre_hz or r.event.centre_hz) / 1e3) for r in results})  # ~1 kHz dedupe
        if len(results) >= SIK_NETID_MIN_FRAMES and n_channels >= SIK_NETID_MIN_CHANNELS:
            labels["sik_netid_confirmed"] = True
            confirmed_netid = netid
            break

    mavlink_messages: List[MavlinkMessage] = []
    if flag_third_party_mavlink and confirmed_netid is not None:
        decoder = SikMavlinkDecoder(enabled=True)
        for r in sorted(by_netid[confirmed_netid], key=lambda r: r.event.t_start):
            mavlink_messages.extend(decoder.feed(r.frame))
        if any(getattr(m, "crc_ok", False) for m in mavlink_messages):
            labels["sik_mavlink_confirmed"] = True

    if labels["sik_mavlink_confirmed"]:
        evidence_level = 4
    elif labels["sik_netid_confirmed"]:
        evidence_level = 3
    elif labels["sik_like_hopper_candidate"]:
        evidence_level = 2
    elif labels["sub_ghz_burst_candidate"]:
        evidence_level = 1
    else:
        evidence_level = 0

    if raster_ev.insufficient:
        notes.append("raster: " + "; ".join(raster_ev.notes))
    elif not raster_ev.consistent:
        notes.extend(raster_ev.notes)

    return {
        "evidence_level": evidence_level,
        "labels": labels,
        "n_bursts": n_bursts,
        "n_crc_valid_frames": len(valid_frames),
        "netid": confirmed_netid,
        "netid_frame_counts": {k: len(v) for k, v in by_netid.items()},
        "raster": raster_ev,
        "mavlink_messages": mavlink_messages,
        "flag_third_party_mavlink": flag_third_party_mavlink,
        "burst_results": burst_results,
        "notes": notes,
    }
