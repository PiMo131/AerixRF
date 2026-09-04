"""OFDM demodulation helpers for DJI DroneID (OcuSync <= 2.0).

Ported from proto17/dji_droneid (MATLAB `get_fft_size.m`, `get_cyclic_prefix_lengths.m`,
`get_data_carrier_indices.m`, `extract_ofdm_symbol_samples.m`, `find_sto_cp.m`,
`quantize_qpsk.m`, and the CFO estimate in `process_file.m`).

Burst layout (nominal 15.36 MHz):
    9 OFDM symbols, cyclic-prefix schedule (samples) = [80, 72, 72, 72, 72, 72, 72, 72, 80]
    fft_size = sample_rate / 15_000 = 1024 @ 15.36 MHz
    full burst = 9*1024 + 2*80 + 7*72 = 9880 samples (~643 us)
    symbols 4 and 6 (1-based) carry ZC pilots; the rest carry QPSK.

Source: https://github.com/proto17/dji_droneid
"""

from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly
from fractions import Fraction

CARRIER_SPACING_HZ = 15_000.0
DATA_CARRIER_COUNT = 600
NOMINAL_SAMPLE_RATE = 15.36e6
NUM_OFDM_SYMBOLS = 9
# 1-based ZC symbol positions and the 1-based data symbols used for the payload
# (symbols 1, 4, 6 are excluded from descrambling per process_file.m: 4 & 6 are ZC,
# symbol 1 is the sometimes-absent leading symbol).
ZC_SYMBOLS_1B = (4, 6)
DATA_SYMBOLS_1B = (2, 3, 5, 7, 8, 9)


def fft_size_for(sample_rate: float) -> int:
    """FFT size for a given sample rate (carrier spacing is 15 kHz, LTE-like)."""
    return int(round(sample_rate / CARRIER_SPACING_HZ))


def cyclic_prefix_lengths(sample_rate: float) -> tuple[int, int]:
    """(long_cp_len, short_cp_len) in samples. 80/72 @ 15.36 MHz."""
    long_cp = int(round(sample_rate / 192_000.0))
    short_cp = int(round(0.0000046875 * sample_rate))
    return long_cp, short_cp


def cp_schedule(sample_rate: float) -> list[int]:
    """Per-symbol cyclic-prefix lengths for the 9-symbol burst."""
    long_cp, short_cp = cyclic_prefix_lengths(sample_rate)
    return [long_cp, short_cp, short_cp, short_cp, short_cp,
            short_cp, short_cp, short_cp, long_cp]


def burst_length(sample_rate: float) -> int:
    """Total samples in a full 9-symbol burst (CPs + FFT windows)."""
    fft_size = fft_size_for(sample_rate)
    return sum(cp_schedule(sample_rate)) + fft_size * NUM_OFDM_SYMBOLS


def data_carrier_indices(fft_size: int) -> np.ndarray:
    """Indices into an ``fftshift(fft(x))`` array holding the 600 data carriers.

    DC is at ``fft_size/2`` (0-based); carriers are the 300 bins on either side,
    excluding DC. @1024: [212..511] and [513..812].
    """
    dc = fft_size // 2
    half = DATA_CARRIER_COUNT // 2
    left = np.arange(dc - half, dc)
    right = np.arange(dc + 1, dc + 1 + half)
    return np.concatenate([left, right])


def resample_to(iq: np.ndarray, in_rate: float, out_rate: float = NOMINAL_SAMPLE_RATE,
                ) -> np.ndarray:
    """Polyphase-resample `iq` from `in_rate` to `out_rate` (no-op if equal)."""
    if abs(in_rate - out_rate) < 1.0:
        return np.asarray(iq, dtype=np.complex128)
    frac = Fraction(out_rate / in_rate).limit_denominator(10_000)
    up, down = frac.numerator, frac.denominator
    iq = np.asarray(iq, dtype=np.complex128)
    # resample_poly handles complex by processing real/imag together.
    return resample_poly(iq, up, down)


def find_sto_cp(iq: np.ndarray, sample_rate: float, coarse_start: int,
                search: int = 60) -> int:
    """Refine burst start using cyclic-prefix self-correlation (find_sto_cp.m).

    Brute-forcing every offset (as the reference does over a whole file) is slow in
    Python, so we only search a +/- `search` window around `coarse_start` (which
    comes from ZC correlation). Score each candidate by correlating each symbol's CP
    against the symbol tail, averaging over symbols 2..9 (symbol 1 may be absent).
    Returns the absolute sample index of the first CP sample of the burst.
    """
    fft_size = fft_size_for(sample_rate)
    schedule = cp_schedule(sample_rate)
    full_len = burst_length(sample_rate)
    iq = np.asarray(iq, dtype=np.complex128)

    lo = max(0, coarse_start - search)
    hi = min(len(iq) - full_len, coarse_start + search)
    if hi <= lo:
        return max(0, min(coarse_start, len(iq) - full_len))

    best_score = -np.inf
    best_off = coarse_start
    for offset in range(lo, hi + 1):
        pos = offset
        acc = 0.0
        for si, cp_len in enumerate(schedule):
            window = iq[pos:pos + fft_size + cp_len]
            left = window[:cp_len]
            right = window[-cp_len:]
            if si >= 1:                              # skip symbol 1 (may be absent)
                acc += np.abs(np.vdot(right, left))  # <left, right> magnitude
            pos += cp_len + fft_size
        score = acc / (len(schedule) - 1)
        if score > best_score:
            best_score = score
            best_off = offset
    return best_off


def estimate_cfo(iq: np.ndarray, sample_rate: float, burst_start: int) -> float:
    """Coarse carrier-frequency offset (Hz) from a short-CP symbol's CP vs tail.

    Uses OFDM symbol 2 (short CP, index 2 in process_file.m's cfo logic). The CP is
    a copy of the symbol tail delayed by fft_size samples, so the phase of their
    correlation over fft_size samples gives the CFO.
    """
    fft_size = fft_size_for(sample_rate)
    long_cp, short_cp = cyclic_prefix_lengths(sample_rate)
    # Start of symbol 2's CP: after symbol 1 (long CP + fft).
    sym2_cp_start = burst_start + long_cp + fft_size
    cp = iq[sym2_cp_start:sym2_cp_start + short_cp]
    # The CP replicates the LAST short_cp samples of the symbol body (fft_size ahead).
    tail = iq[sym2_cp_start + fft_size:sym2_cp_start + fft_size + short_cp]
    if cp.size == 0 or tail.size != cp.size:
        return 0.0
    # np.vdot(cp, tail) conjugates cp (matches MATLAB dot(cp, tail)).
    offset_radians = np.angle(np.vdot(cp, tail)) / fft_size
    return float(offset_radians * sample_rate / (2 * np.pi))


def estimate_cfo_blind(iq: np.ndarray, sample_rate: float,
                       region: tuple[int, int] | None = None) -> float:
    """Timing-free *fractional* CFO estimate (Hz) from CP self-similarity.

    Sums ``conj(x[n]) * x[n + fft_size]`` over the whole `region` (default: all of
    `iq`). Only cyclic-prefix/tail pairs add coherently; every other product has a
    random phase and averages out, so the phase of the sum is ``2 pi f N / fs``
    without knowing where the symbols start. Unambiguous range is +/- half a
    subcarrier (+/-7.5 kHz @ 15 kHz spacing); the integer part is found separately
    by the ZC correlation bank (see :func:`zc.find_zc_symbol_start_int_cfo`).
    Accuracy is a few hundred Hz -- enough to make the ZC search reliable; the
    residual is cleaned up afterwards by :func:`estimate_cfo` on a known CP.
    """
    fft_size = fft_size_for(sample_rate)
    lo, hi = (0, iq.size) if region is None else region
    seg = np.asarray(iq[max(0, lo):min(iq.size, hi)], dtype=np.complex128)
    if seg.size <= fft_size + 1:
        return 0.0
    # einsum rather than np.vdot: a ~10k-element BLAS zdotc costs 1-5 ms per call
    # while OpenBLAS's thread pool warms up under load (first ~100 calls of a
    # process), which dominated the reject path; einsum is a flat ~30 us.
    c = np.einsum("i,i->", np.conj(seg[:-fft_size]), seg[fft_size:])
    if c == 0:
        return 0.0
    return float(np.angle(c) / fft_size * sample_rate / (2 * np.pi))


def zc_confirm_score(freq_symbol: np.ndarray, channel_taps: np.ndarray,
                     fft_size: int, symbol_index: int) -> float:
    """Normalized match of an equalized received symbol against a golden ZC (0..1).

    Applies the zero-forcing taps (from the *other* ZC symbol) to the data
    carriers of `freq_symbol` and correlates with the expected ZC values. A
    real DroneID burst gives ~1 (both pilots see the same channel); noise gives
    ~1/sqrt(600). Used to confirm that the OFDM structure is really present.
    """
    from .zc import zc_data_values

    dci = data_carrier_indices(fft_size)
    eq = freq_symbol[dci] * channel_taps
    gold = zc_data_values(symbol_index)
    denom = np.linalg.norm(eq) * np.linalg.norm(gold)
    if denom == 0:
        return 0.0
    return float(np.abs(np.vdot(gold, eq)) / denom)


def apply_cfo(iq: np.ndarray, sample_rate: float, cfo_hz: float) -> np.ndarray:
    """Remove a carrier-frequency offset of `cfo_hz` from `iq`."""
    iq = np.asarray(iq, dtype=np.complex128)
    n = np.arange(iq.size)
    return iq * np.exp(-1j * 2 * np.pi * cfo_hz / sample_rate * n)


def extract_ofdm_symbols(iq: np.ndarray, sample_rate: float, burst_start: int,
                         ) -> tuple[np.ndarray, np.ndarray]:
    """Extract the 9 OFDM symbols (CP removed) as time- and freq-domain arrays.

    Returns ``(time_domain[9, fft_size], freq_domain[9, fft_size])`` where the
    frequency domain is ``fftshift(fft(symbol))``. `burst_start` is the first CP
    sample of the burst.
    """
    fft_size = fft_size_for(sample_rate)
    schedule = cp_schedule(sample_rate)
    iq = np.asarray(iq, dtype=np.complex128)

    time_domain = np.zeros((NUM_OFDM_SYMBOLS, fft_size), dtype=np.complex128)
    freq_domain = np.zeros((NUM_OFDM_SYMBOLS, fft_size), dtype=np.complex128)
    pos = burst_start
    for idx, cp_len in enumerate(schedule):
        sym = iq[pos + cp_len:pos + cp_len + fft_size]
        if sym.size < fft_size:                      # ran off the end; leave zeros
            break
        time_domain[idx] = sym
        freq_domain[idx] = np.fft.fftshift(np.fft.fft(sym))
        pos += cp_len + fft_size
    return time_domain, freq_domain


def zc_channel(freq_symbol: np.ndarray, fft_size: int, symbol_index: int) -> np.ndarray:
    """Zero-forcing channel estimate from a received ZC symbol (calculate_channel.m).

    ``taps = gold / received`` over all FFT bins; multiplying received data carriers
    by these taps equalizes them. The division is guarded against near-zero bins.
    """
    from .zc import zc_time_domain

    gold = np.fft.fftshift(np.fft.fft(zc_time_domain(fft_size, symbol_index)))
    denom = np.where(np.abs(freq_symbol) < 1e-9, 1e-9, freq_symbol)
    return gold / denom


def quantize_qpsk(carriers: np.ndarray) -> np.ndarray:
    """Hard-decision QPSK demod (quantize_qpsk.m mapping).

    1+j -> 00, 1-j -> 01, -1+j -> 10, -1-j -> 11. Returns a flat bit array of
    length ``2 * len(carriers)``.
    """
    carriers = np.asarray(carriers)
    b0 = (carriers.real < 0).astype(np.int8)         # sign of I -> first bit
    b1 = (carriers.imag < 0).astype(np.int8)         # sign of Q -> second bit
    bits = np.empty(carriers.size * 2, dtype=np.int8)
    bits[0::2] = b0
    bits[1::2] = b1
    return bits
