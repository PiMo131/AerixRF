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
    exceptions are captured in ``error``. Candidates are tried strongest-first;
    once `budget_s` of wall time has been spent no further candidate is started
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
        cands = [(0, n, float(env.max()) if env.size else 0.0)]
    else:
        cands = _segment_envelope(env, block, sample_rate, max_bursts=max_bursts,
                                  min_len_s=DEFAULT_MIN_BURST_S,
                                  max_len_s=DEFAULT_MAX_BURST_S,
                                  threshold_db=threshold_db)

    attempts: list[DecodeAttempt] = []
    for ci, (start, end, peak) in enumerate(cands):
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
        )
        try:
            demod, info = _demodulate(iq[lo:hi], sample_rate, correlation_threshold,
                                      max_integer_cfo_bins, region=(start - lo, end - lo))
            attempt.zc_score = float(info["zc_score"])
            attempt.cfo_hz = float(info["cfo_hz"])
            attempt.integer_cfo_bins = int(info["integer_cfo_bins"])
            attempt.zc6_score = float(info.get("zc6_score", 0.0))
            attempt.demod = demod
            attempt.level = _grade(demod, info, correlation_threshold)
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


def decode_frame(demod: DroneIdDemod, iterations: int = 8) -> DroneIdResult | None:
    """Back end: de-rate-match + Turbo decode + CRC + field parse of a demod result.

    Returns a populated :class:`DroneIdResult` when CRC24A validates, else None.
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
    )


def available() -> bool:
    """Whether the demod front end is wired in (True once sync+OFDM demod exist)."""
    return True
