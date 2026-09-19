"""SiK-style 2-GFSK burst demodulator: rate estimate, channelise, FM
discriminate, post-detection matched filter, timing recovery, bit slice,
sync search.

**Evidence level 1 (synthetic).** Validated only against ``synth.py``'s
generator, which shares this module's model assumptions (Gaussian pulse
shaping, the inferred 0x2DD4 sync word). A pass here is "decoder
self-consistency verified" only -- it does NOT demonstrate decoding a real
SiK radio. See ``docs/design/sik-mavlink-passive-decode.md`` (T1) and
``synth.py``'s module docstring for the shared model.

Pipeline (``demod_gfsk``)
------------------------
0. **Pre-decimate** (polyphase) from the capture rate to an intermediate
   rate wide enough to hold the whole CFO search range plus the occupied
   bandwidth (``_CFO_SEARCH_HZ`` +/- OBW/2), and at least the working
   oversample ``_WORK_OSF * rate_bps``. At 15.36 MS/s and 64 kbps this is a
   x20 reduction *before* any FFT, and is what keeps the per-burst cost in
   the millisecond range.
1. **One FFT does both coarse CFO and channelisation.** The periodogram is
   smoothed over ~rate/8, thresholded a few dB above its median (noise
   floor), and the power centroid of what survives is the coarse CFO. A
   2-GFSK power spectrum is symmetric about the carrier, so the centroid is
   an unbiased carrier estimate and -- unlike two-peak picking -- it does
   not fail when the two tones merge (small h, or h*rate comparable to the
   analysis resolution). The same FFT is then rolled so the CFO lands at
   bin 0 and sliced to ``_WORK_OSF*rate_bps`` of bandwidth; the inverse FFT
   of that slice is the derotated, decimated channel signal.
2. **Channel filter.** Short Kaiser FIR at the working rate, one-sided
   cutoff ``deviation + 0.6*rate_bps`` (i.e. just outside the upper tone
   plus its Gaussian skirt). This sets the pre-detection noise bandwidth,
   which is what the "in-band SNR" of ``synth.py`` refers to.
3. **FM discriminate** (angle of the conjugate product, scaled to Hz).
4. **Residual CFO removal**: the midpoint of the 10th and 90th percentiles
   of the post-detection eye. The instantaneous-frequency distribution of
   2-GFSK is bimodal at +/-deviation, so the two percentiles land one in
   each mode and their midpoint is the carrier. The obvious alternatives --
   the mean or the median of the discriminator output -- are both biased by
   mark/space imbalance over a short burst: for a bimodal density the
   median moves across the (sparse) middle region as soon as the two masses
   differ, which was measured at ~8.6% of the deviation (5.5 kHz at 64 kbps)
   on 592-bit bursts. The percentile midpoint only fails beyond roughly a
   90/10 imbalance.
5. **Post-detection matched filter**: average the discriminator output over
   one symbol period. This is the step whose absence cost the previous
   implementation several dB: slicing a single discriminator sample per
   symbol keeps the full pre-detection noise bandwidth (~2 x rate) in every
   decision, while the symbol-rate average keeps only ~rate/2 of it.
6. **Symbol timing**: the matched-filter output is interpolated to a fixed
   ``_OSF`` grid and the sub-symbol phase maximising the mean |eye opening|
   is chosen (single best-phase search, no tracking loop -- adequate for
   single static bursts with no sample-clock drift; a real capture with
   clock error will need a loop, see the design doc's open items).
7. **Hard-slice** at the chosen phase.

``estimate_rate`` measures the 98% occupied bandwidth (noise-floor
subtracted) and compares it against the *modelled* OBW of each of the 13
legal SiK air rates, choosing the closest in log-bandwidth. The per-rate
constant ``_OBW98_OVER_RATE`` is the measured OBW98/rate of the BT=0.5
Gaussian model in ``synth.py``; Carson's rule (``(2+h)*rate``) over-states
it by ~1.6x because Gaussian shaping suppresses the outer sidebands. This
constant is therefore calibrated *to the model*, not to hardware -- see
"Open evidence gaps" below.

Open evidence gaps
------------------
* ``_OBW98_OVER_RATE`` and the timing/CFO tolerances are calibrated against
  the synthetic model only. Real Si4432 spectra (PA shaping, LO phase
  noise, non-ideal Gaussian filter) may move OBW98/rate by several percent;
  the rate decision boundaries have ~15% margin at the worst adjacent pair
  (128k vs 192k), so this is tolerable but unverified.
* The sync word 0x2DD4 is an inferred Si4432 power-on default.
* No sample-clock-error (resampling) handling: bursts are assumed short
  enough that ppm-level clock error does not walk the symbol phase.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import firwin, fftconvolve, resample_poly

from .synth import SIK_AIR_RATES_BPS, nominal_h

_OSF = 16             # samples-per-symbol of the post-detection timing grid
_WORK_OSF = 6.0       # samples-per-symbol of the channelised complex signal
_CFO_SEARCH_HZ = 25e3  # half-width of the CFO range the front end must pass
_CHAN_EXCESS_BW = 0.6  # channel filter cutoff = deviation + this * rate_bps

# Measured 98% occupied bandwidth / rate_bps of the synth.py BT=0.5 Gaussian
# GFSK model at 20 dB in-band SNR (see module docstring). Keyed by nominal h.
_OBW98_OVER_RATE: Dict[float, float] = {
    1.875: 2.25,
    2.0: 2.49,
    1.65: 2.01,
    1.27: 1.78,
}


def _smooth_box(x: np.ndarray, w: int) -> np.ndarray:
    """O(N) moving average of width ``w`` (odd), edge-padded."""
    if w <= 1:
        return x
    w |= 1
    pad = w // 2
    xp = np.concatenate([np.full(pad, x[0]), x, np.full(pad, x[-1])])
    c = np.cumsum(np.concatenate([[0.0], xp]))
    return (c[w:] - c[:-w]) / w


def _occupied_bandwidth(burst: np.ndarray, fs: float, res_hz: float,
                        frac: float = 0.98, thr_db: float = 6.0) -> Tuple[float, float]:
    """(centroid_hz, occupied_bw_hz) of the noise-floor-subtracted spectrum.

    Averaged periodogram with resolution ~``res_hz``; bins below
    ``median + thr_db`` are zeroed so that wideband noise outside the signal
    does not inflate the bandwidth (at the low air rates the *wideband* SNR
    over a 15.36 MHz capture is strongly negative even when the in-band SNR
    is 20 dB).
    """
    n = len(burst)
    nseg = int(2 ** np.ceil(np.log2(max(fs / max(res_hz, 1.0), 64.0))))
    nseg = int(min(nseg, max(n, 64)))
    nsegs = max(n // nseg, 1)
    win = np.hanning(nseg)
    acc = np.zeros(nseg)
    for i in range(nsegs):
        seg = burst[i * nseg:(i + 1) * nseg]
        if len(seg) < nseg:
            break
        acc += np.abs(np.fft.fft(seg * win)) ** 2
    acc = np.fft.fftshift(acc / max(nsegs, 1))
    freqs = np.fft.fftshift(np.fft.fftfreq(nseg, d=1.0 / fs))
    floor = float(np.median(acc))
    q = np.where(acc > floor * 10.0 ** (thr_db / 10.0), acc - floor, 0.0)
    total = q.sum()
    if total <= 0:
        return 0.0, 0.0
    centroid = float(np.sum(freqs * q) / total)
    order = np.argsort(np.abs(freqs - centroid))
    cum = np.cumsum(q[order])
    k = min(int(np.searchsorted(cum, frac * total)), nseg - 1)
    return centroid, float(2.0 * abs(freqs[order[k]] - centroid))


def estimate_rate(burst: np.ndarray, fs: float) -> float:
    """Estimate the SiK air rate (bits/s) from occupied bandwidth.

    Evidence level 1 (synthetic). Two passes: a coarse OBW measurement sets
    the spectral resolution for a refined one, then the refined OBW is
    matched (in log bandwidth) against the modelled OBW of each of the 13
    legal SiK air rates. Returns bits/second (float).
    """
    burst = np.asarray(burst)
    # Pass 1: coarse, resolution-agnostic.
    _, obw0 = _occupied_bandwidth(burst, fs, res_hz=fs / 16384.0)
    rate0 = max(obw0 / 2.5, 1.0)
    # Pass 2: resolution ~ rate/16 of the coarse estimate.
    _, obw = _occupied_bandwidth(burst, fs, res_hz=max(rate0 / 16.0, fs / len(burst)))
    if obw <= 0:
        obw = obw0
    rates = np.asarray(SIK_AIR_RATES_BPS, dtype=float)
    modelled = np.array([r * _OBW98_OVER_RATE[nominal_h(r)] for r in rates])
    idx = int(np.argmin(np.abs(np.log(modelled) - np.log(max(obw, 1.0)))))
    return float(rates[idx])


def _front_end(burst: np.ndarray, fs: float, rate_bps: float, h: float
               ) -> Tuple[np.ndarray, float, float]:
    """Pre-decimate, estimate coarse CFO, and return the derotated channel.

    Returns ``(channel_iq, fs_work, cfo_hz)``. See module docstring steps 0-2.
    """
    obw = rate_bps * (2.0 + h)
    keep_hz = _CFO_SEARCH_HZ + obw / 2.0          # one-sided band that must survive
    fs_need = max(_WORK_OSF * rate_bps, 2.5 * 2.0 * keep_hz)
    decim = max(int(fs // fs_need), 1)
    if decim > 1:
        # Design the decimation filter from the transition width actually
        # required (passband edge keep_hz, stopband edge fs_w - keep_hz)
        # rather than taking resample_poly's default 10*decim+1 taps: the
        # required transition here is wide (>=3*keep_hz), and the polyphase
        # cost is linear in the tap count, so this is ~3x faster at 64 kbps
        # for the same alias rejection.
        fs_w = fs / decim
        trans = max(fs_w - 2.0 * keep_hz, fs_w * 0.05)
        atten_db = 65.0
        beta = 0.1102 * (atten_db - 8.7)
        ntaps = int(np.ceil((atten_db - 8.0) / (2.285 * 2.0 * np.pi * trans / fs)))
        ntaps = int(np.clip(ntaps, 15, 10 * decim + 1)) | 1
        taps = firwin(ntaps, fs_w / 2.0, fs=fs, window=("kaiser", beta))
        burst = resample_poly(burst, 1, decim, window=taps)
        fs = fs_w

    n = len(burst)
    spec = np.fft.fft(burst)
    power = np.abs(spec) ** 2
    bin_hz = fs / n
    w = int(round((rate_bps / 8.0) / bin_hz))
    power_s = _smooth_box(np.fft.fftshift(power), w)
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / fs))
    floor = float(np.median(power_s))
    q = np.where(power_s > floor * 4.0, power_s - floor, 0.0)
    cfo_hz = float(np.sum(freqs * q) / q.sum()) if q.sum() > 0 else 0.0

    # Slice the spectrum: roll the CFO bin to 0, keep +/- fs_work/2.
    k0 = int(round(cfo_hz / bin_hz))
    m = int(round(_WORK_OSF * rate_bps / bin_hz))
    m = max(min(m, n), 16)
    m += m % 2
    rolled = np.roll(spec, -k0)
    sliced = np.concatenate([rolled[: m // 2], rolled[n - m // 2:]])
    chan = np.fft.ifft(sliced) * (m / n)
    fs_work = fs * m / n
    cfo_hz = k0 * bin_hz

    cutoff = min(h * rate_bps / 2.0 + _CHAN_EXCESS_BW * rate_bps, 0.45 * fs_work)
    taps = firwin(65, cutoff, fs=fs_work, window=("kaiser", 8.0))
    chan = fftconvolve(chan, taps, mode="same")
    return chan, fs_work, cfo_hz


def demod_gfsk(burst: np.ndarray, fs: float, rate_bps: float, h: float
               ) -> Tuple[np.ndarray, dict]:
    """Demodulate a 2-GFSK burst to hard bit decisions.

    Evidence level 1 (synthetic) -- see module docstring. Returns
    ``(bits, timing_info)``: ``bits`` is a ``uint8`` array of hard 0/1
    decisions, one per symbol; ``timing_info`` carries the estimated CFO
    (Hz, coarse + residual), the channelised sample rate, the chosen
    sub-symbol sampling phase and the number of symbols recovered.
    """
    burst = np.asarray(burst)
    deviation_hz = h * rate_bps / 2.0

    chan, fs_work, cfo_coarse = _front_end(burst, fs, rate_bps, h)
    if len(chan) < 4:
        return np.zeros(0, dtype=np.uint8), {"cfo_hz": cfo_coarse}

    disc = np.angle(chan[1:] * np.conj(chan[:-1])) * fs_work / (2.0 * np.pi)

    # Post-detection matched filter (one-symbol average) on the _OSF grid.
    fs3 = rate_bps * _OSF
    n_out = int(len(disc) / fs_work * fs3)
    if n_out < 2 * _OSF:
        return np.zeros(0, dtype=np.uint8), {"cfo_hz": cfo_coarse}
    t_in = np.arange(len(disc)) / fs_work
    y = np.interp(np.arange(n_out) / fs3, t_in, disc, left=disc[0], right=disc[-1])
    mf = np.ones(_OSF) / _OSF
    eye = np.convolve(y, mf, mode="valid")  # eye[k] averages [k, k+_OSF)

    # Residual CFO = midpoint of the two eye modes (see docstring step 4).
    lo, hi = np.percentile(eye, [10.0, 90.0])
    cfo_res = float((lo + hi) / 2.0)
    eye = eye - cfo_res

    best_phase, best_score = 0, -np.inf
    for phase in range(_OSF):
        score = float(np.mean(np.abs(eye[phase::_OSF])))
        if score > best_score:
            best_score, best_phase = score, phase

    symbol_samples = eye[best_phase::_OSF]
    bits = (symbol_samples > 0).astype(np.uint8)

    timing_info = {
        "cfo_hz": cfo_coarse + cfo_res,
        "cfo_coarse_hz": cfo_coarse,
        "cfo_residual_hz": cfo_res,
        "fs_channelized": fs_work,
        "best_phase": best_phase,
        "osf": _OSF,
        "n_symbols": len(symbol_samples),
        "deviation_hz": deviation_hz,
        "eye_open_hz": best_score,
    }
    return bits, timing_info


def _alternating_errors(windows: np.ndarray) -> np.ndarray:
    """Per-window Hamming distance to the nearer of the two 1010/0101 patterns."""
    width = windows.shape[1]
    patt = np.arange(width) % 2
    d = np.sum(windows != patt, axis=1)
    return np.minimum(d, width - d)


def find_sync(
    bits: np.ndarray,
    sync_word: int,
    both_polarities: bool = True,
    both_bit_orders: bool = True,
    *,
    max_bit_errors: int = 2,
    preamble_bits: int = 32,
    preamble_max_errors: int = 3,
    require_preamble: bool = True,
) -> List[Tuple[int, bool, str]]:
    """Search a hard-bit stream for a 16-bit sync word.

    Evidence level 1 (synthetic) -- the sync word value (0x2DD4 default) is
    an inferred Si4432 power-on default, not a firmware-confirmed constant
    (design doc S1/S4). Returns a list of ``(offset, inverted, bit_order)``
    for every match, where ``offset`` is the index of the first bit of the
    sync word, ``inverted`` is whether the bit stream had to be
    polarity-flipped and ``bit_order`` is ``"msb"``/``"lsb"``.

    Error tolerance and the preamble gate go together and must not be
    separated: allowing ``max_bit_errors`` (default 2) expands the accepted
    set to sum(C(16,k), k<=2) = 137 of 65536 patterns, i.e. a 2.1e-3 chance
    per bit position per (polarity, bit-order) hypothesis -- on a 2000-bit
    noise stream with 4 hypotheses that is ~17 false syncs *per burst*. The
    gate therefore additionally requires the ``preamble_bits`` bits
    immediately before the candidate to be alternating (1010.../0101...)
    within ``preamble_max_errors``, which for random bits costs another
    ~2.8e-4 and brings the expected false-sync rate back to ~5e-3 per
    2000-bit burst. The gate is polarity-agnostic (an inverted alternating
    preamble is still alternating). Set ``require_preamble=False`` only for
    unit tests of the matcher itself, or when the preamble is known to be
    truncated by the capture.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    width = 16
    n = len(bits)
    if n < width:
        return []

    windows = np.lib.stride_tricks.sliding_window_view(bits, width)  # [n-15, 16]
    sync_msb = np.array([(sync_word >> (width - 1 - i)) & 1 for i in range(width)], dtype=np.uint8)
    patterns = {"msb": sync_msb, "lsb": sync_msb[::-1]}

    ok_preamble: Optional[np.ndarray] = None
    if require_preamble and preamble_bits > 0:
        ok_preamble = np.zeros(len(windows), dtype=bool)
        if n >= width + preamble_bits:
            pre_windows = np.lib.stride_tricks.sliding_window_view(bits, preamble_bits)
            errs = _alternating_errors(pre_windows)
            # candidate at offset o needs pre-window starting at o-preamble_bits
            ok = errs <= preamble_max_errors
            ok_preamble[preamble_bits:preamble_bits + len(ok)] = ok[: len(ok_preamble) - preamble_bits]

    orders = ["msb", "lsb"] if both_bit_orders else ["msb"]
    polarities = [False, True] if both_polarities else [False]

    hits: List[Tuple[int, bool, str]] = []
    for inverted in polarities:
        w = 1 - windows if inverted else windows
        for order in orders:
            dist = np.sum(w != patterns[order], axis=1)
            good = dist <= max_bit_errors
            if ok_preamble is not None:
                good &= ok_preamble
            hits.extend((int(o), inverted, order) for o in np.nonzero(good)[0])
    hits.sort(key=lambda x: (x[0], x[1], x[2]))
    return hits
