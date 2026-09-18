"""Stage-3 DJI DroneID decode (best-effort, OcuSync <= 2.0).

Ported from proto17/dji_droneid and anarkiwi/samples2djidroneid. Pipeline:

    1-second IQ window (e.g. 20 MS/s from a HackRF)
      -> :func:`find_burst_candidates`   cheap |x|^2 envelope segmentation
      -> per candidate (with margin):    resample to 15.36 MHz
           :func:`demodulate`            blind fractional CFO (CP self-similarity)
                                         ZC sym-4 correlation bank over integer-CFO
                                           hypotheses (+/-K subcarriers) -> timing + k
                                         CP-based STO refine, fine CFO, OFDM demod,
                                         ZC channel equalization, sym-6 ZC confirm,
                                         QPSK hard decisions, LTE descramble
           :func:`decode_frame`          de-rate-match + Turbo + CRC24A + parse
      -> :class:`DecodeAttempt` per candidate, graded A/B/C (see Milestone 1.5).

Never resample or ZC-correlate the whole window: :func:`decode_all` only touches
the short high-energy segments, so a burst-free window costs one envelope pass.

Only OcuSync <= 2.0 is decodable; O3/O4 are encrypted. Decoded operator location is
personal data -> retention-gated server-side.

Source: https://github.com/proto17/dji_droneid
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from scipy.signal import filtfilt, firwin

from . import ofdm
from .zc import find_zc_symbol_start_int_cfo

# LTE scrambler second-LFSR init: the 31-bit literal 0x12345678 pattern from
# process_file.m, bit-reversed (fliplr). Kept verbatim from the reference.
_X2_INIT = np.array(list(reversed([
    0, 0, 1,   0, 0, 1, 0,   0, 0, 1, 1,   0, 1, 0, 0,
    0, 1, 0, 1,   0, 1, 1, 0,   0, 1, 1, 1,   1, 0, 0, 0,
])), dtype=np.int8)

# ZC correlation score below which we declare "no decodable burst present".
DEFAULT_CORRELATION_THRESHOLD = 0.5
# Equalized sym-6 ZC match below which the OFDM structure is not confirmed
# (level stays "A"; noise scores ~0.04, a real burst well above 0.5).
ZC6_CONFIRM_THRESHOLD = 0.3
# Integer-CFO search half-width in subcarriers (4 -> +/-60 kHz, covers a HackRF's
# +/-20 ppm at 2.4 GHz plus a few kHz of drone-side error).
DEFAULT_MAX_INTEGER_CFO_BINS = 4
# The single unshifted sym-4 correlation used as a pre-bank gate scores a little
# lower than the best hypothesis when |k| > 0 (ZC shift ambiguity, ~0.85-1.0 of
# it), so the gate sits at this fraction of the correlation threshold.
ZC_GATE_FRACTION = 0.8
# Envelope segmentation: block length and threshold above the window's median.
ENVELOPE_BLOCK_S = 20e-6
DEFAULT_ENVELOPE_THRESHOLD_DB = 3.0
# Accepted candidate duration (a 9-symbol burst is 0.643 ms; margin for envelope
# edge blocks and a possible 8-symbol variant / trailing energy).
DEFAULT_MIN_BURST_S = 0.4e-3
DEFAULT_MAX_BURST_S = 1.5e-3
# Margin (in burst lengths) cut around an envelope candidate before resampling.
# The envelope bounds are good to ~1 block (20 us); a quarter burst (~160 us)
# covers that plus the STO search while keeping the slice (and its FFTs) small.
CANDIDATE_MARGIN_BURSTS = 0.25
# decode_all stops starting new candidates once this much wall time was spent.
DEFAULT_BUDGET_S = 0.25

# Centre-hypothesis scorer (docs/design/decoder-blocker-robustness.md, "Scorer
# design"): accept a hypothesis immediately once the equalized sym-6 ZC
# confirm score reaches this (a real burst at the true centre is ~0.9); below
# CENTRE_REFINE_ZC6 the best hypothesis is treated as mis-centred (not just
# noisy) and a fine grid around it is tried, +/-CENTRE_REFINE_SPAN_HZ in
# CENTRE_REFINE_STEP_HZ steps (closes the integer-CFO capture range gap,
# 2*K*15 kHz = 120 kHz < 100 kHz step... i.e. do not raise the step above that).
CENTRE_ACCEPT_ZC6 = 0.75
CENTRE_REFINE_ZC6 = 0.35
CENTRE_REFINE_SPAN_HZ = 4e5
CENTRE_REFINE_STEP_HZ = 1e5

# Per-candidate spectral shape (field lesson, Mini 3 2026-09-04): the window's
# strongest bursts are Wi-Fi beacons (~18 MHz) and the RC uplink hops (~2 MHz),
# both 20 dB above the DroneID burst, which sits anywhere inside the window --
# e.g. 2429.5 MHz in a 2437 MHz window. So each candidate's coarse centre and
# occupied bandwidth are measured from its own PSD; DroneID-shaped candidates
# (~9 MHz occupied, less when clipped by the window edge) are tried first and
# each is mixed to DC by its own centre before the front end.
BURST_SPECTRUM_FFT = 1024             # 19.5 kHz bins at 20 MS/s: band edges to ~1 bin
BURST_SPECTRUM_SMOOTH_BINS = 3
BURST_SPECTRUM_FLOOR_DB = -10.0       # occupied band = contiguous bins within this of the peak
BURST_SPECTRUM_EDGE_BINS = 2          # band reaching this close to the window edge = clipped
DRONEID_MIN_OCCUPIED_HZ = 4.0e6
# Tightened from 14.0e6 (2026-09-18, decoder-blocker-robustness.md): the old
# _grow_band could grow *through* a stronger adjacent blocker's edge and land
# on a ~12 MHz band that was never DroneID; 11 MHz still comfortably covers
# the ~9 MHz nominal occupied width plus edge-clip slop.
DRONEID_MAX_OCCUPIED_HZ = 11.0e6
CANDIDATE_POOL_FACTOR = 32            # envelope candidates spectrally screened per attempted burst

# Channel-select filter applied (after mixing a hypothesis centre to DC, before
# _demodulate/ZC correlation) so a strong out-of-band emitter sharing the slice
# cannot dominate the ZC correlator's normalisation (root cause in
# docs/design/decoder-blocker-robustness.md). Zero-phase (filtfilt) so it adds
# no group delay that would shift the burst's timing/CFO estimate. The cutoff
# is deliberately just outside the ~9.0 MHz nominal DroneID occupied width
# (+/-4.5 MHz): a brick wall at 4.60 MHz starves the outer carriers to 0/8 CRC
# on the wideband-blocker bench arm, while 4.51 MHz recovers full sensitivity.
CHANNEL_FILTER_CUTOFF_HZ = 4.51e6
CHANNEL_FILTER_TAPS = 129
CHANNEL_FILTER_BETA = 10.0            # Kaiser window beta

# Band-peel centre-hypothesis search (per candidate slice): repeatedly take the
# PSD's remaining argmax, grow its occupied band (_grow_band), zero those bins,
# and repeat -- a stronger blocker is peeled away first, exposing the real
# DroneID band underneath on a later round. Bounds and caps per
# docs/design/decoder-blocker-robustness.md.
PEEL_ROUNDS = 8
PEEL_BW_MIN_HZ = DRONEID_MIN_OCCUPIED_HZ
PEEL_BW_MAX_HZ = DRONEID_MAX_OCCUPIED_HZ
PEEL_DEDUP_HZ = 0.5e6
MAX_CENTRE_HYPOTHESES = 4

# A continuous stronger emitter elsewhere in the window (CW spur or a
# band-limited noise-like blocker) can dominate a single burst slice's PSD and
# pull the old single-argmax band search onto the wrong signal. burst_spectrum
# now scores several candidate bands per slice instead of just the global
# peak; these bound that search (field lesson, 2026-09-18 bench sweep).
BURST_SPECTRUM_MAX_PEAKS = 4          # local maxima considered per slice
BURST_SPECTRUM_PEAK_SEP_HZ = 2.0e6    # minimum spacing enforced between them
BURST_SPECTRUM_SPUR_DB = 20.0         # narrowband spur excised before a retry
BURST_SPECTRUM_SPUR_MAX_HZ = 0.5e6    # ... if narrower than this


@dataclass
class DroneIdResult:
    serial: str | None
    drone_lat: float | None
    drone_lon: float | None
    operator_lat: float | None
    operator_lon: float | None
    protocol: str        # e.g. "ocusync2"
    # Extended fields populated once the Turbo/CRC back end validates a frame.
    # Kept at the end with None defaults so existing constructors/consumers are
    # unaffected (main.py filters None out of res.__dict__).
    drone_height: float | None = None
    drone_altitude: float | None = None
    home_lat: float | None = None
    home_lon: float | None = None
    sequence: int | None = None
    decode_iterations: int | None = None
    # Additive (2026-09-18): the rest of frame.DroneIdFrame that parse_frame already
    # extracts but this result did not previously expose. version/msg_type and the
    # state0/state1 bits are NOT threaded through: frame.parse_frame/DroneIdFrame do
    # not currently carry them (only validates msg_type==16/version==2 and discards),
    # and extending that parse is out of this change's scope.
    product_type: int | None = None
    uuid: str | None = None
    gps_time_ms: int | None = None
    # Evidence-quality labels (rf-protocol-analyst design, see
    # .claude/agent-memory/rf-protocol-analyst/protocol_droneid_evidence_gating.md):
    # post-CRC semantic sanity checks. These NEVER gate/drop a CRC24A-valid frame;
    # they only annotate it. `sequence_non_monotonic` is the one flag that needs
    # more than a single frame -- it is filled in by decode_all across the
    # CRC-valid results of one call, comparing each frame's sequence number to the
    # previous CRC-valid frame in time order (delta != 1 -> flagged; covers both
    # duplicates, delta 0, and gaps, delta > 1). A fresh decode_frame() call in
    # isolation (e.g. in a unit test) never has a prior frame to compare against,
    # so that flag is only ever added by decode_all.
    semantic_flags: list[str] = field(default_factory=list)
    evidence_quality: str = "clean"          # "clean" | "flagged" (derived from semantic_flags)


@dataclass
class DroneIdDemod:
    """Recoverable front-end products of a DroneID burst (pre-Turbo-decode)."""
    sync_offset: int                 # burst start sample index (in 15.36 MHz stream)
    zc_score: float                  # peak ZC correlation, 0..1
    cfo_hz: float                    # estimated & corrected carrier freq offset
    sample_rate: float               # working rate (15.36 MHz)
    fft_size: int
    freq_symbols: np.ndarray         # [9, fft_size] fftshift(fft(symbol))
    data_carriers: np.ndarray        # [9, 600] equalized data-carrier symbols
    qpsk_bits: np.ndarray            # [9, 1200] hard-decision bits per symbol
    descrambled_bits: np.ndarray     # [7200] descrambled payload bits
    resampled: bool = False
    integer_cfo_bins: int = 0        # whole-subcarrier part of the CFO (15 kHz units)
    zc6_score: float = 0.0           # equalized sym-6 ZC match, 0..1 (OFDM confirm)


@dataclass
class DecodeAttempt:
    """Outcome of trying to decode one candidate burst inside a window.

    ``level`` follows the Milestone 1.5 validation hierarchy:
      "none" -- no ZC sync candidate above threshold
      "A"    -- ZC sync candidate found
      "B"    -- OFDM demod + descramble done and the sym-6 ZC pilot confirms the
                OFDM structure (equalized match >= ZC6_CONFIRM_THRESHOLD)
      "C"    -- Turbo decode + CRC24A valid (``result`` populated)
    Sample indices are in the *input* stream's units (not the 15.36 MHz working rate).
    """
    start_sample: int
    end_sample: int
    duration_ms: float
    peak_power_db: float             # 10 log10 of the strongest 20 us block (linear |x|^2)
    level: str
    zc_score: float
    cfo_hz: float
    integer_cfo_bins: int
    crc_ok: bool
    result: DroneIdResult | None
    error: str | None
    snr_db: float | None = None      # peak block power over the window's median floor
    zc6_score: float = 0.0
    demod: DroneIdDemod | None = field(default=None, repr=False)
    center_offset_hz: float = 0.0    # burst centre relative to the window centre (PSD centroid)
    occupied_bw_hz: float = 0.0      # contiguous band within BURST_SPECTRUM_FLOOR_DB of the peak
    droneid_shaped: bool = False     # occupied_bw within the DroneID range -> tried first
    alt_centers_hz: tuple[float, ...] = ()  # other DroneID-shaped bands in this slice (reporting only)
    hypotheses_tried: int = 0        # centre hypotheses (band-peel) actually mixed+filtered+demodulated
    chosen_center_offset_mhz: float = 0.0  # centre hypothesis (MHz) that produced the reported level


def generate_scrambler_seq(num_bits: int, x2_init: np.ndarray = _X2_INIT) -> np.ndarray:
    """LTE pseudo-random (Gold) sequence generator (generate_scrambler_seq.m).

    x1 fixed init [1,0,...,0]; Nc=1600 offset; c(n) = x1(n+Nc) ^ x2(n+Nc).
    The default-init sequence is cached (the Python LFSR loop costs ~13 ms per
    call, which was a visible per-burst cost); callers get a fresh copy.
    """
    if x2_init is _X2_INIT:
        return _default_scrambler_seq(int(num_bits)).copy()
    return _generate_scrambler_seq(num_bits, x2_init)


@lru_cache(maxsize=4)
def _default_scrambler_seq(num_bits: int) -> np.ndarray:
    return _generate_scrambler_seq(num_bits, _X2_INIT)


def _generate_scrambler_seq(num_bits: int, x2_init: np.ndarray) -> np.ndarray:
    nc = 1600
    total = num_bits + nc
    x1 = np.zeros(total + 31, dtype=np.int8)
    x2 = np.zeros(total + 31, dtype=np.int8)
    x1[0] = 1                                        # x1_init = [1,0,...,0]
    x2[:31] = x2_init
    for n in range(total):
        x1[n + 31] = (x1[n + 3] + x1[n]) & 1
        x2[n + 31] = (x2[n + 3] + x2[n + 2] + x2[n + 1] + x2[n]) & 1
    return (x1[nc:nc + num_bits] ^ x2[nc:nc + num_bits]).astype(np.int8)


def descramble_payload(qpsk_bits: np.ndarray) -> np.ndarray:
    """Descramble the 6 payload OFDM symbols (process_file.m).

    Selects 1-based symbols [2,3,5,7,8,9] (ZC symbols 4/6 and the leading symbol 1
    are excluded), row-major flattens to 7200 bits, and XORs with the scrambler.
    """
    data_rows = [s - 1 for s in ofdm.DATA_SYMBOLS_1B]     # -> [1,2,4,6,7,8]
    payload = qpsk_bits[data_rows, :].reshape(-1).astype(np.int8)
    seq = generate_scrambler_seq(payload.size)
    return (payload ^ seq).astype(np.int8)


def _select_integer_cfo(work: np.ndarray, fft_size: int, shifts: list[int],
                        peaks: np.ndarray, scores: np.ndarray, threshold: float,
                        ) -> tuple[int, int, float]:
    """Pick the integer-CFO hypothesis using the second ZC pilot.

    For every hypothesis ``k`` whose sym-4 correlation is above `threshold`, take
    its own timing ``peaks[i]``, de-rotate the sym-4 and sym-6 windows by ``k``
    bins, equalize sym 6 with the sym-4 zero-forcing channel and match it against
    the root-147 ZC. Sym 4 alone cannot tell k apart (a ZC frequency shift looks
    like a time shift), but sym 6 has a different root and therefore a different
    time-shift-per-bin, so only the true k equalizes cleanly (~1 vs ~0.05).
    Returns ``(k_bins, zc_peak, zc_score)``; ties resolve towards the smallest |k|.
    """
    _long_cp, short_cp = ofdm.cyclic_prefix_lengths(ofdm.NOMINAL_SAMPLE_RATE)
    sym6_rel = 2 * (fft_size + short_cp)              # sym-6 data start - sym-4 data start
    n = np.arange(fft_size)
    dci = ofdm.data_carrier_indices(fft_size)
    order = sorted(range(len(shifts)), key=lambda i: (abs(shifts[i]), shifts[i]))
    best = (0, int(peaks[order[0]]), float(scores[order[0]]), -1.0)
    for i in order:
        k, s4, sc = int(shifts[i]), int(peaks[i]), float(scores[i])
        if sc < threshold or s4 < 0 or s4 + sym6_rel + fft_size > work.size:
            continue
        rot = np.exp(-1j * 2 * np.pi * k * n / fft_size) if k else 1.0
        f4 = np.fft.fftshift(np.fft.fft(work[s4:s4 + fft_size] * rot))
        f6 = np.fft.fftshift(np.fft.fft(work[s4 + sym6_rel:s4 + sym6_rel + fft_size] * rot))
        conf = ofdm.zc_confirm_score(f6, ofdm.zc_channel(f4, fft_size, 4)[dci], fft_size, 6)
        if conf > best[3]:
            best = (k, s4, sc, conf)
    return best[0], best[1], best[2]


def _demodulate(iq: np.ndarray, sample_rate: float,
                correlation_threshold: float,
                max_integer_cfo_bins: int,
                region: tuple[int, int] | None,
                ) -> tuple[DroneIdDemod | None, dict]:
    """Front end; returns ``(demod_or_None, info)``.

    `info` always carries ``zc_score``, ``cfo_hz`` and ``integer_cfo_bins`` so a
    caller can grade a failed attempt. `region` is an optional ``(lo, hi)`` sample
    span *in the input rate* where the burst energy sits (from the envelope
    stage); it focuses the blind CFO estimate. It is scaled to the working rate.
    """
    iq = np.asarray(iq, dtype=np.complex128)
    fs = ofdm.NOMINAL_SAMPLE_RATE
    fft_size = ofdm.fft_size_for(fs)
    info: dict = {"zc_score": 0.0, "cfo_hz": 0.0, "integer_cfo_bins": 0, "zc6_score": 0.0}

    # (1) Resample to the nominal 15.36 MHz if the input differs; kill DC.
    resampled = abs(sample_rate - fs) >= 1.0
    work = ofdm.resample_to(iq, sample_rate, fs)
    if work.size < ofdm.burst_length(fs):
        return None, info
    work = work - work.mean()

    ratio = fs / sample_rate
    work_region = None
    if region is not None:
        work_region = (int(region[0] * ratio), int(np.ceil(region[1] * ratio)))

    # (2) Blind fractional CFO (no timing needed) so the ZC correlation is sharp.
    cfo_frac = ofdm.estimate_cfo_blind(work, fs, work_region)
    work = ofdm.apply_cfo(work, fs, cfo_frac)
    info["cfo_hz"] = cfo_frac

    # (3a) Cheap gate: ONE unshifted sym-4 correlation. Thanks to the ZC shift
    #      ambiguity (a k-bin frequency shift looks like a small time shift) it
    #      peaks >= ~0.85 for any |k| <= K, so it rejects non-DroneID candidates
    #      (ambient Wi-Fi/BT) at ~1/6 the cost of the full hypothesis bank.
    K = int(max_integer_cfo_bins)
    _pk0, gate_score, _k0, _s0, _p0 = find_zc_symbol_start_int_cfo(
        work, fft_size, symbol_index=4, shifts=(0,))
    info["zc_score"] = float(gate_score)
    if gate_score < correlation_threshold * ZC_GATE_FRACTION:
        return None, info

    # (3b) Coarse time sync per integer-subcarrier CFO hypothesis: correlate for
    #      the first ZC sequence (symbol 4) against +/-K bin-shifted replicas, then
    #      let the second pilot (symbol 6) pick the hypothesis (ZC shift ambiguity).
    shifts = list(range(-K, K + 1))
    _pk, zc_score_max, _kb, per_scores, per_peaks = find_zc_symbol_start_int_cfo(
        work, fft_size, symbol_index=4, shifts=shifts)
    info["zc_score"] = float(zc_score_max)
    if zc_score_max < correlation_threshold:
        return None, info
    k_bins, zc_peak, zc_score = _select_integer_cfo(
        work, fft_size, shifts, per_peaks, per_scores, correlation_threshold)
    info["zc_score"] = float(zc_score)
    info["integer_cfo_bins"] = int(k_bins)
    info["cfo_hz"] = cfo_frac + k_bins * ofdm.CARRIER_SPACING_HZ
    if k_bins:
        work = ofdm.apply_cfo(work, fs, k_bins * ofdm.CARRIER_SPACING_HZ)

    # ZC symbol 4's data starts `sum(cp[0:4]) + 3*fft` after the burst start.
    schedule = ofdm.cp_schedule(fs)
    pre_zc4 = sum(schedule[:4]) + fft_size * 3
    coarse_start = zc_peak - pre_zc4

    # (3b) Refine with cyclic-prefix STO around the coarse estimate.
    burst_start = ofdm.find_sto_cp(work, fs, coarse_start)
    if burst_start < 0 or burst_start + ofdm.burst_length(fs) > work.size:
        burst_start = max(0, min(coarse_start, work.size - ofdm.burst_length(fs)))

    # (3c) Fine CFO from a short-CP symbol at the known timing and correct it.
    cfo_fine = ofdm.estimate_cfo(work, fs, burst_start)
    work = ofdm.apply_cfo(work, fs, cfo_fine)
    cfo_hz = cfo_frac + k_bins * ofdm.CARRIER_SPACING_HZ + cfo_fine
    info["cfo_hz"] = cfo_hz

    # (4) OFDM demod: strip CPs, FFT each symbol.
    _time_syms, freq_syms = ofdm.extract_ofdm_symbols(work, fs, burst_start)

    # ZC channel estimate (symbol 4) -> zero-forcing equalizer on data carriers.
    dci = ofdm.data_carrier_indices(fft_size)
    channel = ofdm.zc_channel(freq_syms[3], fft_size, 4)[dci]

    # Confirm the OFDM structure with the second pilot (symbol 6, root 147).
    zc6_score = ofdm.zc_confirm_score(freq_syms[5], channel, fft_size, 6)
    info["zc6_score"] = zc6_score

    data_carriers = np.zeros((ofdm.NUM_OFDM_SYMBOLS, dci.size), dtype=np.complex128)
    qpsk_bits = np.zeros((ofdm.NUM_OFDM_SYMBOLS, dci.size * 2), dtype=np.int8)
    for idx in range(ofdm.NUM_OFDM_SYMBOLS):
        eq = freq_syms[idx, dci] * channel
        data_carriers[idx] = eq
        qpsk_bits[idx] = ofdm.quantize_qpsk(eq)

    # (5) Descramble the payload symbols.
    descrambled = descramble_payload(qpsk_bits)

    demod = DroneIdDemod(
        sync_offset=int(burst_start),
        zc_score=float(zc_score),
        cfo_hz=float(cfo_hz),
        sample_rate=fs,
        fft_size=fft_size,
        freq_symbols=freq_syms,
        data_carriers=data_carriers,
        qpsk_bits=qpsk_bits,
        descrambled_bits=descrambled,
        resampled=resampled,
        integer_cfo_bins=int(k_bins),
        zc6_score=float(zc6_score),
    )
    return demod, info


def demodulate(iq: np.ndarray, sample_rate: float,
               correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
               *, max_integer_cfo_bins: int = DEFAULT_MAX_INTEGER_CFO_BINS,
               region: tuple[int, int] | None = None,
               ) -> DroneIdDemod | None:
    """Run the DroneID front end on a *short* slice; return intermediates or None.

    None is returned when no burst correlates above `correlation_threshold` for any
    integer-CFO hypothesis in ``[-max_integer_cfo_bins, +max_integer_cfo_bins]``.
    For long windows use :func:`decode_all`, which segments first.
    """
    demod, _info = _demodulate(iq, sample_rate, correlation_threshold,
                               max_integer_cfo_bins, region)
    return demod


# ---------------------------------------------------------------------------
# Window-level: envelope segmentation + burst-by-burst decoding
# ---------------------------------------------------------------------------

def _block_envelope(iq: np.ndarray, block: int) -> np.ndarray:
    """Mean power per `block` samples with the window's static DC removed.

    Two cheap passes over the interleaved (re, im) view -- an einsum for the
    per-block energy and a column sum for the global mean -- ~25 ms for 20 M
    samples, no BLAS (whose thread pool is erratic under load). Subtracting the
    global |DC|^2 keeps a HackRF DC spike from lifting the noise floor; a
    DroneID burst's own mean is ~0 so its blocks are unaffected.
    """
    nblocks = iq.size // block
    if nblocks == 0:
        return np.zeros(0)
    if iq.dtype not in (np.complex64, np.complex128):
        iq = iq.astype(np.complex64)
    iq = np.ascontiguousarray(iq[:nblocks * block])
    ftype = np.float32 if iq.dtype == np.complex64 else np.float64
    v = iq.view(ftype).reshape(nblocks, block * 2)
    power = np.einsum("ij,ij->i", v, v) / block                     # E|x|^2 per block
    col = v.sum(axis=0, dtype=np.float64)                           # 2*block column sums
    total = nblocks * block
    dc_power = (col[0::2].sum() / total) ** 2 + (col[1::2].sum() / total) ** 2
    return np.maximum(power.astype(np.float64) - dc_power, 0.0)


def find_burst_candidates(iq: np.ndarray, sample_rate: float, *,
                          max_bursts: int = 8,
                          min_len_s: float = DEFAULT_MIN_BURST_S,
                          max_len_s: float = DEFAULT_MAX_BURST_S,
                          threshold_db: float = DEFAULT_ENVELOPE_THRESHOLD_DB,
                          ) -> list[tuple[int, int, float]]:
    """Cheap envelope segmentation: short high-energy segments of DroneID-like length.

    Computes a decimated |x|^2 envelope (20 us blocks), thresholds it at
    `threshold_db` above the window's median (the noise floor, as bursts occupy
    a tiny fraction of a 1 s window), closes gaps < 0.1 ms, keeps runs whose
    duration lies in ``[min_len_s, max_len_s]`` (a DroneID burst is ~0.64 ms) and
    returns up to `max_bursts` of them, strongest first, as
    ``(start_sample, end_sample, peak_power)`` with `peak_power` the linear mean
    |x|^2 of the strongest block. One pass over the data; ~15 ms for 20 M samples.
    """
    block = _envelope_block(sample_rate)
    env = _block_envelope(np.asarray(iq), block)
    return _segment_envelope(env, block, sample_rate, max_bursts=max_bursts,
                             min_len_s=min_len_s, max_len_s=max_len_s,
                             threshold_db=threshold_db)


def _envelope_block(sample_rate: float) -> int:
    return max(1, int(round(sample_rate * ENVELOPE_BLOCK_S)))


def _segment_envelope(env: np.ndarray, block: int, sample_rate: float, *,
                      max_bursts: int, min_len_s: float, max_len_s: float,
                      threshold_db: float) -> list[tuple[int, int, float]]:
    """Segmentation half of :func:`find_burst_candidates` on a precomputed envelope."""
    if env.size == 0:
        return []
    floor = float(np.median(env))
    thr = max(floor, 1e-30) * 10.0 ** (threshold_db / 10.0)
    mask = env > thr
    if not mask.any():
        return []

    # Runs of True in `mask`.
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)                 # exclusive block index

    # Close short gaps (< 0.1 ms) so a fading burst is not split in two.
    gap_blocks = max(1, int(round(0.1e-3 / ENVELOPE_BLOCK_S)))
    merged: list[list[int]] = []
    for s, e in zip(starts, ends):
        if merged and s - merged[-1][1] <= gap_blocks:
            merged[-1][1] = int(e)
        else:
            merged.append([int(s), int(e)])

    min_blocks = min_len_s * sample_rate / block
    max_blocks = max_len_s * sample_rate / block
    cands = []
    for s, e in merged:
        if not (min_blocks <= (e - s) <= max_blocks):
            continue
        cands.append((s * block, e * block, float(env[s:e].max())))
    cands.sort(key=lambda c: c[2], reverse=True)
    return cands[:max_bursts]


def _burst_psd(iq: np.ndarray, sample_rate: float) -> np.ndarray | None:
    """Averaged Hann-windowed |FFT|^2 of a burst slice, smoothed and DC-clipped."""
    n = BURST_SPECTRUM_FFT
    x = np.asarray(iq)
    frames = x.size // n
    if frames == 0:
        return None
    x = np.asarray(x[:frames * n], dtype=np.complex64).reshape(frames, n)
    x = x * np.hanning(n).astype(np.float32)
    psd = np.fft.fftshift(np.mean(np.abs(np.fft.fft(x, axis=1)) ** 2, axis=0))
    mid = n // 2
    psd[mid - 1:mid + 2] = np.minimum(psd[mid - 1:mid + 2], max(psd[mid - 2], psd[mid + 2]))
    k = BURST_SPECTRUM_SMOOTH_BINS
    if k > 1:
        psd = np.convolve(psd, np.ones(k) / k, mode="same")
    return psd


def _grow_band_bins(psd: np.ndarray, imax: int) -> tuple[int, int]:
    """Inclusive bin span ``(lo, hi)`` of the occupied band grown from ``imax``.

    Shared by :func:`_grow_band` (public behaviour unchanged) and
    :func:`_centre_hypotheses`, which needs the raw span to zero those bins
    before peeling the next round.
    """
    n = psd.size
    peak = float(psd[imax])
    above = psd > peak * 10.0 ** (BURST_SPECTRUM_FLOOR_DB / 10.0)
    gap = 2
    lo = imax
    while lo > 0 and above[max(0, lo - gap):lo].any():
        lo -= 1
    hi = imax
    while hi < n - 1 and above[hi + 1:hi + 1 + gap].any():
        hi += 1
    return lo, hi


def _grow_band(psd: np.ndarray, sample_rate: float, imax: int) -> tuple[float, float]:
    """Grow the occupied band outward from bin ``imax`` (existing FLOOR_DB rule).

    Returns ``(center_hz, bw_hz)``; the edge-clip centring rule from the
    original :func:`burst_spectrum` is preserved.
    """
    n = psd.size
    mid = n // 2
    lo, hi = _grow_band_bins(psd, imax)
    df = sample_rate / n
    f_lo = (lo - mid) * df
    f_hi = (hi + 1 - mid) * df
    bw = f_hi - f_lo
    clipped_lo = lo <= BURST_SPECTRUM_EDGE_BINS
    clipped_hi = hi >= n - 1 - BURST_SPECTRUM_EDGE_BINS
    fft_size = ofdm.fft_size_for(ofdm.NOMINAL_SAMPLE_RATE)
    nominal = ofdm.data_carrier_indices(fft_size).size * ofdm.CARRIER_SPACING_HZ
    if clipped_lo and not clipped_hi and bw < nominal:
        center = f_hi - nominal / 2.0
    elif clipped_hi and not clipped_lo and bw < nominal:
        center = f_lo + nominal / 2.0
    else:
        center = (f_lo + f_hi) / 2.0
    return float(center), float(bw)


@lru_cache(maxsize=8)
def _channel_filter_taps(sample_rate: float) -> np.ndarray:
    """Kaiser-windowed lowpass FIR taps for :func:`_channel_filter`, cached per fs."""
    return firwin(CHANNEL_FILTER_TAPS, CHANNEL_FILTER_CUTOFF_HZ, fs=sample_rate,
                 window=("kaiser", CHANNEL_FILTER_BETA))


def _channel_filter(iq: np.ndarray, sample_rate: float) -> np.ndarray:
    """Zero-phase channel-select FIR, applied after mixing a hypothesis centre to
    DC and before :func:`_demodulate`/ZC correlation.

    Without this, a strong out-of-band continuous emitter (CW spur or
    band-limited blocker) dominates the ZC correlator's own-energy
    normalisation and collapses its score below threshold even with a
    perfectly correct centre (see docs/design/decoder-blocker-robustness.md).
    ``filtfilt`` (zero group delay) so burst timing/CFO estimates downstream
    are unaffected. Skipped for slices shorter than ``3 * CHANNEL_FILTER_TAPS``
    (filtfilt's default edge padding would fail or badly distort a short
    slice); such slices are left unfiltered rather than raising.
    """
    iq = np.asarray(iq)
    taps = _channel_filter_taps(float(sample_rate))
    if iq.size < 3 * taps.size:
        return iq
    return filtfilt(taps, [1.0], iq)


def _centre_hypotheses(iq: np.ndarray, sample_rate: float) -> list[float]:
    """Ordered centre-frequency (Hz) hypotheses for one candidate slice.

    Band-peel: repeatedly take the slice PSD's remaining argmax, grow its
    occupied band (:func:`_grow_band`), zero those bins, and repeat up to
    ``PEEL_ROUNDS`` times. A stronger blocker's band is peeled away first
    (zeroed), so the real DroneID band's edges are clean on a later round --
    this is what makes the wideband-blocker bench arm resolve to the true
    centre instead of the blocker's. Only bands shaped like DroneID
    (``PEEL_BW_MIN_HZ..PEEL_BW_MAX_HZ`` occupied, ``|centre| < fs/2 - 1 MHz``)
    are kept, in peel (power) order, deduped within ``PEEL_DEDUP_HZ`` of an
    already-kept centre. Centre 0.0 (no mix) is always appended as a final
    fallback -- a mis-shaped or fully-excised peel must never leave the caller
    with zero hypotheses -- unless a kept centre is already that close to DC.
    Capped at ``MAX_CENTRE_HYPOTHESES`` entries total.
    """
    psd = _burst_psd(iq, sample_rate)
    if psd is None:
        return [0.0]
    n = psd.size
    mid = n // 2
    df = sample_rate / n
    limit_hz = sample_rate / 2.0 - 1.0e6
    work = psd.astype(np.float64).copy()
    out: list[float] = []
    for _ in range(PEEL_ROUNDS):
        if work.max() <= 0.0:
            break
        imax = int(np.argmax(work))
        centre, bw = _grow_band(work, sample_rate, imax)
        lo, hi = _grow_band_bins(work, imax)
        work[lo:hi + 1] = 0.0
        if abs(centre) < limit_hz and PEEL_BW_MIN_HZ <= bw <= PEEL_BW_MAX_HZ:
            if not any(abs(centre - c) < PEEL_DEDUP_HZ for c in out):
                out.append(centre)
    out = out[:max(0, MAX_CENTRE_HYPOTHESES - 1)]
    if not any(abs(c) < PEEL_DEDUP_HZ for c in out):
        out.append(0.0)
    return out[:MAX_CENTRE_HYPOTHESES]


_EMPTY_DEMOD_INFO = {"zc_score": 0.0, "cfo_hz": 0.0, "integer_cfo_bins": 0, "zc6_score": 0.0}


def _score_centre(slice_iq: np.ndarray, sample_rate: float, centre_hz: float, *,
                  correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
                  max_integer_cfo_bins: int = DEFAULT_MAX_INTEGER_CFO_BINS,
                  region: tuple[int, int] | None = None,
                  deadline: float | None,
                  cache: dict,
                  ) -> tuple[tuple["DroneIdDemod | None", dict] | None, float, float]:
    """Mix ``slice_iq`` to ``centre_hz``, channel-filter, and score it via
    :func:`_demodulate`.

    Returns ``(demod_result, zc4, zc6)`` where ``demod_result`` is the
    ``(demod, info)`` pair :func:`_demodulate` produces. ``demod_result`` is
    ``None`` (with ``zc4 = zc6 = 0.0``) when ``deadline`` (a
    ``time.perf_counter()`` deadline, or ``None`` to disable it) had already
    passed and nothing new was evaluated.

    Cached by ``round(centre_hz / 1e3)`` (1 kHz buckets) keyed into the
    caller-owned ``cache`` dict, so a centre already scored -- in particular
    the eventual winner -- is never re-demodulated; a cache hit is returned
    even past ``deadline`` since it costs nothing new.
    """
    import time

    key = round(centre_hz / 1e3)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if deadline is not None and time.perf_counter() >= deadline:
        return None, 0.0, 0.0
    mix_hz = centre_hz if abs(centre_hz) > max_integer_cfo_bins * ofdm.CARRIER_SPACING_HZ else 0.0
    h_slice = _mix(slice_iq, sample_rate, mix_hz)
    h_slice = _channel_filter(h_slice, sample_rate)
    demod, info = _demodulate(h_slice, sample_rate, correlation_threshold,
                              max_integer_cfo_bins, region)
    zc4 = float(info.get("zc_score", 0.0))
    zc6 = float(info.get("zc6_score", 0.0))
    result = ((demod, info), zc4, zc6)
    cache[key] = result
    return result


def _select_centre(slice_iq: np.ndarray, sample_rate: float,
                   hypotheses_hz: list[float] | tuple[float, ...], *,
                   correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
                   max_integer_cfo_bins: int = DEFAULT_MAX_INTEGER_CFO_BINS,
                   region: tuple[int, int] | None = None,
                   deadline: float | None = None,
                   allow_refine: bool = True,
                   ) -> tuple[float, tuple, int, tuple[float, ...]]:
    """Pick the best centre-frequency hypothesis for one candidate slice.

    Evaluates ``hypotheses_hz`` (:func:`_centre_hypotheses`' order) via
    :func:`_score_centre`, accepting immediately at
    ``zc6 >= CENTRE_ACCEPT_ZC6`` -- this keeps the clean/RUB path identical to
    before the scorer existed: one hypothesis, one demod. Otherwise ranks
    every hypothesis evaluated so far by ``(zc6, zc4)``; if the best is
    DroneID-shaped but not selective (``zc6 < CENTRE_REFINE_ZC6`` and
    ``zc4 >= correlation_threshold * ZC_GATE_FRACTION``), a
    +/-CENTRE_REFINE_STEP_HZ..CENTRE_REFINE_SPAN_HZ grid around it is scored
    too and the overall argmax taken (see
    docs/design/decoder-blocker-robustness.md, "Scorer design"). Never accepts
    a final result below ``ZC6_CONFIRM_THRESHOLD``: a noise-driven grid point
    cannot win outright, so the first hypothesis (peel order) is returned
    instead, unevaluated hypotheses included in ``alt_centers_hz``.

    Returns ``(centre_hz, (demod, info), hypotheses_tried, alt_centers_hz)``.
    ``hypotheses_tried`` counts distinct centres actually
    mixed/filtered/demodulated (cache hits and deadline-skipped hypotheses do
    not add to it). ``deadline`` is checked before every evaluation.
    """
    hyps = list(hypotheses_hz)
    if not hyps:
        return 0.0, (None, dict(_EMPTY_DEMOD_INFO)), 0, ()

    cache: dict = {}

    def score(h: float, dl: float | None):
        return _score_centre(
            slice_iq, sample_rate, h, correlation_threshold=correlation_threshold,
            max_integer_cfo_bins=max_integer_cfo_bins, region=region,
            deadline=dl, cache=cache)

    scored: list[tuple[float, float, float, tuple]] = []  # (zc6, zc4, centre_hz, demod_result)
    accepted: tuple[float, tuple] | None = None
    for h in hyps:
        demod_result, zc4, zc6 = score(h, deadline)
        if demod_result is None:
            break  # deadline passed before this hypothesis could be evaluated
        scored.append((zc6, zc4, h, demod_result))
        if zc6 >= CENTRE_ACCEPT_ZC6:
            accepted = (h, demod_result)
            break

    if accepted is None and scored:
        best_zc6, best_zc4, best_h, best_result = max(scored, key=lambda t: (t[0], t[1]))
        if (allow_refine and best_zc6 < CENTRE_REFINE_ZC6
                and best_zc4 >= correlation_threshold * ZC_GATE_FRACTION):
            offsets = []
            step = CENTRE_REFINE_STEP_HZ
            while step <= CENTRE_REFINE_SPAN_HZ + 1.0:
                offsets.extend((-step, step))
                step += CENTRE_REFINE_STEP_HZ
            for off in offsets:
                demod_result, zc4, zc6 = score(best_h + off, deadline)
                if demod_result is None:
                    break  # deadline passed mid-refinement
                scored.append((zc6, zc4, best_h + off, demod_result))
            best_zc6, best_zc4, best_h, best_result = max(scored, key=lambda t: (t[0], t[1]))
        if best_zc6 < ZC6_CONFIRM_THRESHOLD:
            first_h = hyps[0]
            demod_result, _zc4, _zc6 = score(first_h, deadline)  # cache hit -> free
            accepted = (first_h, demod_result if demod_result is not None
                       else (None, dict(_EMPTY_DEMOD_INFO)))
        else:
            accepted = (best_h, best_result)

    if accepted is None:
        accepted = (hyps[0], (None, dict(_EMPTY_DEMOD_INFO)))

    centre_hz, demod_result = accepted
    alt_centers_hz = tuple(h for h in hyps if h != centre_hz)
    return centre_hz, demod_result, len(cache), alt_centers_hz


BURST_SPECTRUM_ALT_MIN_DB = -30.0     # local maxima below this (rel. to the slice peak) are noise, not candidates


def _local_peak_bins(psd: np.ndarray, sample_rate: float, *, k: int, min_sep_hz: float,
                     min_rel_db: float = BURST_SPECTRUM_ALT_MIN_DB) -> list[int]:
    """Up to ``k`` local maxima of ``psd``, tallest first, >= ``min_sep_hz`` apart.

    Iteratively takes the remaining argmax and masks its neighbourhood; the
    first bin returned is always the single global argmax bin (bit-identical
    to the pre-fix :func:`burst_spectrum` candidate). Peaks more than
    ``min_rel_db`` below the slice's own peak are dropped -- residual
    floating-point noise in an otherwise-empty band (e.g. a synthetic
    band-limited signal's zeroed-out FFT bins) must not masquerade as a
    plausible second band.
    """
    n = psd.size
    df = sample_rate / n
    sep_bins = max(1, int(round(min_sep_hz / df)))
    work = psd.astype(np.float64).copy()
    top = float(work.max())
    floor = top * 10.0 ** (min_rel_db / 10.0) if top > 0.0 else 0.0
    peaks: list[int] = []
    for _ in range(max(1, k)):
        i = int(np.argmax(work))
        if work[i] <= 0.0 or (peaks and work[i] < floor):
            break
        peaks.append(i)
        work[max(0, i - sep_bins):min(n, i + sep_bins + 1)] = -1.0
    return peaks


def _burst_spectrum_candidates(iq: np.ndarray, sample_rate: float,
                               ) -> list[tuple[float, float, bool]]:
    """``[(center_offset_hz, occupied_bw_hz, droneid_shaped), ...]`` bands in one slice.

    Entry 0 is always the band grown from the slice's single strongest bin --
    bit-identical to the pre-fix :func:`burst_spectrum` (a window with only
    one real band therefore behaves exactly as before). When a second,
    stronger, continuous emitter (CW spur or band-limited noise) shares the
    slice, its band dominates entry 0, so up to BURST_SPECTRUM_MAX_PEAKS - 1
    further local maxima (>= BURST_SPECTRUM_PEAK_SEP_HZ apart, within
    BURST_SPECTRUM_ALT_MIN_DB of the slice peak) are also scored and appended,
    DroneID-shaped ones (occupied width in [DRONEID_MIN_OCCUPIED_HZ,
    DRONEID_MAX_OCCUPIED_HZ]) first, closest to the nominal ~9 MHz occupied
    width and flattest (lowest in-band dB spread) first among those -- so the
    real DroneID band is not silently discarded, only demoted to an
    alternate. A narrowband spur (>= BURST_SPECTRUM_SPUR_DB above the slice
    median, narrower than BURST_SPECTRUM_SPUR_MAX_HZ -- e.g. a CW blocker) is
    additionally excised and the alternate search retried on the residual
    PSD, in case it was masking a real band's edge.
    """
    psd = _burst_psd(iq, sample_rate)
    if psd is None:
        return []
    n = psd.size
    df = sample_rate / n
    peak = float(psd.max())
    if peak <= 0.0:
        return []

    fft_size = ofdm.fft_size_for(ofdm.NOMINAL_SAMPLE_RATE)
    nominal = ofdm.data_carrier_indices(fft_size).size * ofdm.CARRIER_SPACING_HZ

    def score(imax: int, psd_src: np.ndarray) -> tuple[float, float, bool, float]:
        center, bw = _grow_band(psd_src, sample_rate, imax)
        shaped = DRONEID_MIN_OCCUPIED_HZ <= bw <= DRONEID_MAX_OCCUPIED_HZ
        band = psd_src[max(0, imax - 1):imax + 2]
        band_db = 10.0 * np.log10(np.maximum(band, 1e-30) / max(float(psd_src[imax]), 1e-30))
        flatness = float(np.std(band_db))
        return center, bw, shaped, flatness

    peak_bins = _local_peak_bins(psd, sample_rate, k=BURST_SPECTRUM_MAX_PEAKS,
                                 min_sep_hz=BURST_SPECTRUM_PEAK_SEP_HZ)
    if not peak_bins:
        return []
    primary = score(peak_bins[0], psd)                   # == old single-argmax burst_spectrum result
    alt_results: list[tuple[float, float, bool, float]] = [score(i, psd) for i in peak_bins[1:]]

    # Excise a strong narrowband spur (CW blocker) and retry once: replace it
    # with its immediate neighbours' level (same trick as the DC-spike clip)
    # so a band edge that was hiding under/behind it can be recovered.
    med = float(np.median(psd[psd > 0])) if np.any(psd > 0) else 0.0
    if med > 0.0:
        spur_bins = max(1, int(round(BURST_SPECTRUM_SPUR_MAX_HZ / df)))
        is_spur = psd > med * 10.0 ** (BURST_SPECTRUM_SPUR_DB / 10.0)
        if is_spur.any():
            # Keep only spur runs narrower than spur_bins.
            edges = np.diff(np.concatenate(([0], is_spur.astype(np.int8), [0])))
            starts = np.flatnonzero(edges == 1)
            ends = np.flatnonzero(edges == -1)
            excise = np.zeros(n, dtype=bool)
            for s, e in zip(starts, ends):
                if e - s <= spur_bins:
                    excise[s:e] = True
            if excise.any():
                psd2 = psd.copy()
                lo_fill = np.roll(psd2, 1)
                hi_fill = np.roll(psd2, -1)
                psd2[excise] = np.minimum(lo_fill[excise], hi_fill[excise])
                for _ in range(3):                       # a wide spur needs a few passes
                    lo_fill = np.roll(psd2, 1)
                    hi_fill = np.roll(psd2, -1)
                    still = excise & (psd2 >= med * 10.0 ** (BURST_SPECTRUM_SPUR_DB / 10.0))
                    if not still.any():
                        break
                    psd2[still] = np.minimum(lo_fill[still], hi_fill[still])
                for imax in _local_peak_bins(psd2, sample_rate, k=BURST_SPECTRUM_MAX_PEAKS,
                                             min_sep_hz=BURST_SPECTRUM_PEAK_SEP_HZ):
                    alt_results.append(score(imax, psd2))

    # Rank the alternates only: DroneID-shaped first, then closest to the
    # nominal occupied width, then flattest; dedup near-identical centres
    # (within one peak spacing) against each other and against the primary.
    alt_results.sort(key=lambda r: (not r[2], abs(r[1] - nominal), r[3]))
    ranked: list[tuple[float, float, bool]] = [(primary[0], primary[1], primary[2])]
    for center, bw, shaped, _flat in alt_results:
        if any(abs(center - c) < BURST_SPECTRUM_PEAK_SEP_HZ for c, _b, _s in ranked):
            continue
        ranked.append((center, bw, shaped))
    return ranked


def burst_spectrum(iq: np.ndarray, sample_rate: float) -> tuple[float, float]:
    """Coarse ``(center_offset_hz, occupied_bw_hz)`` of one burst slice: top candidate.

    Averaged Hann-windowed |FFT|^2 over the slice, smoothed over a few bins; the
    occupied band is the contiguous run of bins within BURST_SPECTRUM_FLOOR_DB of
    a candidate peak (2-bin gaps bridged so the DroneID DC null does not split
    it) and the centre is the midpoint of its edges -- an OFDM spectrum's edges
    are sharp, so this holds to ~20 kHz at 5 dB SNR where a power centroid
    wanders by +/-70 kHz with the data. A band that reaches the window edge is
    clipped, so its centre is placed half the nominal DroneID occupied width in
    from the visible edge (a 2429.5 MHz channel in a 2437 MHz window: visible
    -10..-3 MHz, centre -7.5 MHz). A HackRF DC spike is clipped to its
    neighbours first.

    With only one strong band in the slice this is identical to before. When a
    second, stronger, continuous emitter shares the slice, several candidate
    bands are scored (see :func:`_burst_spectrum_candidates`) and the best one
    is returned; :func:`_rank_candidates` exposes the rest as alternates.
    """
    cands = _burst_spectrum_candidates(iq, sample_rate)
    if not cands:
        return 0.0, 0.0
    center, bw, _shaped = cands[0]
    return center, bw


def _rank_candidates(iq: np.ndarray, sample_rate: float,
                     cands: list[tuple[int, int, float]], max_bursts: int,
                     ) -> list[tuple[int, int, float, float, float, bool, tuple[float, ...]]]:
    """Measure each envelope candidate's spectrum and order DroneID-shaped first.

    Returns ``(start, end, peak, center_offset_hz, occupied_bw_hz, shaped,
    alt_centers_hz)`` for the `max_bursts` best: shaped candidates by power,
    then the rest by power. ``alt_centers_hz`` holds other DroneID-shaped
    bands found in the same slice (e.g. the real burst when a stronger
    continuous emitter also occupies a plausible-width band there), ranked,
    excluding the primary centre.
    """
    measured = []
    for start, end, peak in cands:
        bands = _burst_spectrum_candidates(iq[start:end], sample_rate)
        if not bands:
            measured.append((start, end, peak, 0.0, 0.0, False, ()))
            continue
        center, bw, shaped = bands[0]
        alts = tuple(c for c, _b, s in bands[1:] if s)
        measured.append((start, end, peak, center, bw, shaped, alts))
    measured.sort(key=lambda c: (not c[5], -c[2]))
    return measured[:max_bursts]


def _mix(iq: np.ndarray, sample_rate: float, offset_hz: float) -> np.ndarray:
    """Shift a slice by ``-offset_hz`` (complex128: a float32 phase ramp drifts)."""
    if abs(offset_hz) < 1.0:
        return iq
    t = np.arange(iq.size, dtype=np.float64) / sample_rate
    return np.asarray(iq, dtype=np.complex128) * np.exp(-2j * np.pi * offset_hz * t)


def _grade(demod: DroneIdDemod | None, info: dict, threshold: float) -> str:
    if info.get("zc_score", 0.0) < threshold:
        return "none"
    if demod is None or demod.zc6_score < ZC6_CONFIRM_THRESHOLD:
        return "A"
    return "B"


def decode_all(iq: np.ndarray, sample_rate: float, *, max_bursts: int = 8,
               correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
               max_integer_cfo_bins: int = DEFAULT_MAX_INTEGER_CFO_BINS,
               threshold_db: float = DEFAULT_ENVELOPE_THRESHOLD_DB,
               budget_s: float | None = DEFAULT_BUDGET_S,
               ) -> list[DecodeAttempt]:
    """Decode every DroneID-like burst in a window, one :class:`DecodeAttempt` each.

    Long windows are segmented by :func:`find_burst_candidates`; each candidate is
    cut out with a quarter burst of margin on both sides and resampled/decoded on
    its own, so cost scales with the number of bursts, not the window length.
    Short inputs (<= 4 burst lengths, e.g. a pre-cut burst) are treated as a single
    candidate without segmentation. A failing candidate never stops the others:
    exceptions are captured in ``error``.

    The burst need not sit at the window centre: up to ``CANDIDATE_POOL_FACTOR *
    max_bursts`` envelope candidates get a PSD measurement (:func:`burst_spectrum`),
    DroneID-shaped ones (occupied bandwidth in the DroneID range) are tried first,
    and each candidate is mixed to DC by its own centre before the front end, so
    a DroneID channel anywhere inside the window decodes even when ambient Wi-Fi
    or the RC link is 20 dB stronger. ``cfo_hz`` is the total offset from the
    window centre (mix + front-end residual); ``center_offset_hz`` is the PSD
    centroid alone.

    Once `budget_s` of wall time has been spent no further candidate is started
    (the weakest are skipped) and the last attempt's ``error`` says how many were
    skipped. ``budget_s=None`` disables the cap. Attempts are returned in time order.
    """
    import time

    t_start = time.perf_counter()
    iq = np.asarray(iq)
    in_burst = int(round(ofdm.burst_length(ofdm.NOMINAL_SAMPLE_RATE)
                         * sample_rate / ofdm.NOMINAL_SAMPLE_RATE))
    margin = int(round(in_burst * CANDIDATE_MARGIN_BURSTS))
    n = iq.size

    block = _envelope_block(sample_rate)
    env = _block_envelope(iq, block)                    # one pass over the window
    floor = float(np.median(env)) if env.size else 0.0
    if n <= 4 * in_burst:
        pool = [(0, n, float(env.max()) if env.size else 0.0)]
    else:
        pool = _segment_envelope(env, block, sample_rate,
                                 max_bursts=max_bursts * CANDIDATE_POOL_FACTOR,
                                 min_len_s=DEFAULT_MIN_BURST_S,
                                 max_len_s=DEFAULT_MAX_BURST_S,
                                 threshold_db=threshold_db)
    cands = _rank_candidates(iq, sample_rate, pool, max_bursts)

    attempts: list[DecodeAttempt] = []
    for ci, (start, end, peak, center_hz, bw_hz, shaped, alt_centers_hz) in enumerate(cands):
        elapsed = time.perf_counter() - t_start
        if budget_s is not None and ci > 0 and elapsed >= budget_s:
            skipped = len(cands) - ci
            note = (f"budget_s={budget_s:g} exceeded after {elapsed:.2f}s; "
                    f"{skipped} weaker candidate(s) not attempted")
            last = attempts[-1]
            last.error = note if last.error is None else f"{last.error}; {note}"
            break
        lo = max(0, start - margin)
        hi = min(n, end + margin)
        peak_db = 10.0 * np.log10(peak) if peak > 0 else -np.inf
        snr_db = 10.0 * np.log10(peak / floor) if (peak > 0 and floor > 0) else None
        attempt = DecodeAttempt(
            start_sample=int(start), end_sample=int(end),
            duration_ms=(end - start) / sample_rate * 1e3,
            peak_power_db=float(peak_db), level="none", zc_score=0.0, cfo_hz=0.0,
            integer_cfo_bins=0, crc_ok=False, result=None, error=None, snr_db=snr_db,
            center_offset_hz=float(center_hz), occupied_bw_hz=float(bw_hz),
            droneid_shaped=bool(shaped), alt_centers_hz=tuple(alt_centers_hz),
        )
        # Ordered centre-frequency hypotheses from a band peel of this slice's
        # own PSD (a stronger blocker's band is peeled away first, exposing the
        # real one underneath): mix each to DC, apply the channel-select filter,
        # demodulate, stop at the first that finds ZC sync. budget_s is
        # rechecked before every hypothesis (not just every candidate) so a
        # single slice with several plausible bands cannot itself blow the
        # wall-clock budget; the first hypothesis of a candidate that already
        # passed the outer gate is always attempted.
        try:
            hyps = _centre_hypotheses(iq[lo:hi], sample_rate)
            deadline = (t_start + budget_s) if budget_s is not None else None
            h_hz, (demod, info), tried, _alt_hyps = _select_centre(
                iq[lo:hi], sample_rate, hyps,
                correlation_threshold=correlation_threshold,
                max_integer_cfo_bins=max_integer_cfo_bins,
                region=(start - lo, end - lo), deadline=deadline)
            if tried == 0:
                # A candidate that already passed the outer per-candidate
                # budget gate always gets its first centre hypothesis
                # evaluated, deadline notwithstanding (pre-scorer contract).
                # allow_refine=False keeps this to exactly that one
                # evaluation: with only one hypothesis in play, a
                # DroneID-shaped-but-not-selective result would otherwise
                # enter the +/-100..400 kHz refinement grid (extra
                # _demodulate calls the single-evaluation contract forbids).
                h_hz, (demod, info), tried, _alt_hyps = _select_centre(
                    iq[lo:hi], sample_rate, hyps[:1],
                    correlation_threshold=correlation_threshold,
                    max_integer_cfo_bins=max_integer_cfo_bins,
                    region=(start - lo, end - lo), deadline=None,
                    allow_refine=False)
            attempt.hypotheses_tried = int(tried)
            mix_hz = h_hz if abs(h_hz) > max_integer_cfo_bins * ofdm.CARRIER_SPACING_HZ else 0.0
            attempt.level = _grade(demod, info, correlation_threshold)
            attempt.chosen_center_offset_mhz = float(h_hz) / 1e6
            if budget_s is not None and time.perf_counter() - t_start >= budget_s and tried < len(hyps):
                note = (f"budget_s={budget_s:g} exceeded after "
                        f"{time.perf_counter() - t_start:.2f}s; "
                        f"{len(hyps) - tried} weaker centre hypothes(es) not attempted")
                attempt.error = note if attempt.error is None else f"{attempt.error}; {note}"
            if info is not None:
                attempt.zc_score = float(info["zc_score"])
                attempt.cfo_hz = float(mix_hz + info["cfo_hz"])
                attempt.integer_cfo_bins = int(info["integer_cfo_bins"])
                attempt.zc6_score = float(info.get("zc6_score", 0.0))
                attempt.demod = demod
            if demod is not None:
                # Refine the reported span to the synchronized burst (input units).
                ratio = sample_rate / demod.sample_rate
                attempt.start_sample = int(lo + round(demod.sync_offset * ratio))
                attempt.end_sample = int(attempt.start_sample + in_burst)
                attempt.duration_ms = in_burst / sample_rate * 1e3
            if attempt.level == "B":
                result = decode_frame(demod)
                if result is not None:
                    attempt.result = result
                    attempt.crc_ok = True
                    attempt.level = "C"
        except Exception as exc:  # noqa: BLE001 - one bad burst must not stop the rest
            attempt.error = f"{type(exc).__name__}: {exc}"
        attempts.append(attempt)

    attempts.sort(key=lambda a: a.start_sample)

    # Cross-frame evidence-quality check: sequence continuity across the CRC-valid
    # results of *this* decode_all call, in time order. Only computable here (a
    # lone decode_frame() call has no prior frame to compare against). A delta
    # other than +1 -- a duplicate (0) or a gap (>1) -- flags the later frame;
    # never the first CRC-valid frame in the window, and never drops anything.
    prev_seq = None
    for attempt in attempts:
        res = attempt.result
        if res is None or res.sequence is None:
            continue
        if prev_seq is not None and res.sequence - prev_seq != 1:
            res.semantic_flags.append("sequence_non_monotonic")
            res.evidence_quality = "flagged"
        prev_seq = res.sequence

    return attempts


def decode(iq: np.ndarray, sample_rate: float) -> DroneIdResult | None:
    """Attempt to decode a DJI DroneID burst from an IQ window.

    Thin wrapper over :func:`decode_all`: returns the first CRC-valid
    :class:`DroneIdResult` (in time order) or None when no decodable
    (OcuSync <= 2.0) burst is present -- noise, an encrypted O3/O4 burst, or a
    non-DroneID signal. Per-burst diagnostics are available from
    :func:`decode_all`.

    TODO(stage-3): handle the 8-symbol drone variant (leading symbol absent).
        find_sto_cp already ignores symbol 1 and the ZC-anchored timing does not
        depend on it, but extract_ofdm_symbols / descramble_payload assume 9
        symbols; a variant would need a second CP schedule (8 entries, first
        long-CP symbol dropped) and pre_zc4 recomputed. Not built until observed
        on a real capture.
    """
    for attempt in decode_all(iq, sample_rate):
        if attempt.result is not None:
            return attempt.result
    return None


# --- Post-CRC evidence-quality labels ---------------------------------------
# Never gate/drop a CRC24A-valid frame on these (rf-protocol-analyst design,
# protocol_droneid_evidence_gating.md): they annotate telemetry plausibility only.
#
# GPS_TIME plausibility window: OFF_GPS_TIME is a ms-epoch u64; [2015-01-01,
# 2035-01-01) brackets DJI DroneID's real deployment era with margin. Exact 0 is
# also implausible (no fix) and is covered by the same bound check.
GPS_TIME_MS_MIN = 1420070400000     # 2015-01-01T00:00:00Z
GPS_TIME_MS_MAX = 2051222400000     # 2035-01-01T00:00:00Z

# Known DJI product_type codes. proto17/dji_droneid (create_frame_bytes.m) documents
# the *field* (u8, 0-255) but ships no name table. No broader DJI product-type
# reference was available inside this task's packet/repo (open item for
# rf-protocol-analyst / a device specialist to source a fuller table -- see the
# unresolved-issues note in this change's handback). The two entries below are
# the codes actually observed on the two real-hardware RUB-SysSec DroneID
# captures used as this decoder's golden fixture (tests/test_droneid_rub_golden.py):
# evidence level 5 (operator-provided test truth) for those two codes only.
# Absence from this table is NOT evidence of an invalid/spoofed frame -- it only
# means the code is not yet catalogued here (see `product_type_unknown` below).
KNOWN_PRODUCT_TYPES: dict[int, str] = {
    58: "mavic_air_2 (RUB-SysSec golden capture)",
    63: "mini2_sm (RUB-SysSec golden capture; researcher-instrumented serial)",
}


def _coord_flags(name: str, lat: float, lon: float) -> list[str]:
    if lat == 0.0 and lon == 0.0:
        return [f"{name}_coords_zero"]
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return [f"{name}_coords_out_of_range"]
    return []


def _semantic_flags(parsed) -> list[str]:
    """Post-CRC evidence-quality labels for one already-CRC-valid parsed frame.

    Per-frame only; does not include `sequence_non_monotonic` (cross-frame,
    added by :func:`decode_all`).
    """
    flags: list[str] = []
    flags += _coord_flags("drone", parsed.drone_lat, parsed.drone_lon)
    flags += _coord_flags("operator", parsed.operator_lat, parsed.operator_lon)
    flags += _coord_flags("home", parsed.home_lat, parsed.home_lon)
    if not (GPS_TIME_MS_MIN <= parsed.gps_time_ms < GPS_TIME_MS_MAX):
        flags.append("gps_time_implausible")
    if parsed.product_type not in KNOWN_PRODUCT_TYPES:
        flags.append("product_type_unknown")
    return flags


def decode_frame(demod: DroneIdDemod, iterations: int = 8) -> DroneIdResult | None:
    """Back end: de-rate-match + Turbo decode + CRC + field parse of a demod result.

    Returns a populated :class:`DroneIdResult` when CRC24A validates, else None.
    CRC24A validity alone determines whether a result is returned; the semantic
    checks below only set ``semantic_flags``/``evidence_quality`` on it.
    """
    from . import turbo
    from . import frame as _frame

    decoded = turbo.decode_frame_bits(demod.descrambled_bits, iterations=iterations)
    if decoded is None:
        return None
    frame_bytes, meta = decoded
    parsed = _frame.parse_frame(frame_bytes)
    if parsed is None:
        return None
    flags = _semantic_flags(parsed)
    return DroneIdResult(
        serial=parsed.serial,
        drone_lat=parsed.drone_lat,
        drone_lon=parsed.drone_lon,
        operator_lat=parsed.operator_lat,
        operator_lon=parsed.operator_lon,
        protocol="ocusync2",
        drone_height=parsed.drone_height,
        drone_altitude=parsed.drone_altitude,
        home_lat=parsed.home_lat,
        home_lon=parsed.home_lon,
        sequence=parsed.sequence,
        decode_iterations=meta["iterations"],
        product_type=parsed.product_type,
        uuid=parsed.uuid,
        gps_time_ms=parsed.gps_time_ms,
        semantic_flags=flags,
        evidence_quality="flagged" if flags else "clean",
    )


def available() -> bool:
    """Whether the demod front end is wired in (True once sync+OFDM demod exist)."""
    return True
