"""Zadoff-Chu sequence generation and correlation-based synchronization.

Ported from proto17/dji_droneid (MATLAB `create_zc.m`, `find_zc_indices_by_file.m`,
`normalized_xcorr_fast.m`). DJI DroneID (OcuSync <= 2.0) places two ZC sequences in
OFDM symbols 4 and 6 (1-based) of a 9-symbol burst; these are used as pilots for
time/frequency synchronization and channel estimation.

Exact parameters (LTE-like, nominal 15.36 MHz sample rate):
    fft_size        = sample_rate / 15_000            (1024 @ 15.36 MHz)
    data_carriers   = 600 (DC excluded)
    ZC roots        = 600 (symbol 4), 147 (symbol 6)
    ZC seq length   = 601 -> middle sample dropped (would land on DC) -> 600 values

Source: https://github.com/proto17/dji_droneid  (matlab/updated_scripts/create_zc.m)
"""

from __future__ import annotations

import numpy as np

# ZC roots keyed by 1-based OFDM symbol index, matching create_zc.m.
_ZC_ROOTS = {4: 600, 6: 147}
_ZC_SEQ_LEN = 601


def zc_data_values(symbol_index: int) -> np.ndarray:
    """The 600 frequency-domain ZC values that land on the data carriers.

    Reproduces `zc = exp(-1j*pi*root*(0:600).*(1:601)/601)` then drops the middle
    (index 300, 0-based) sample that would otherwise fall on the DC carrier.
    """
    if symbol_index not in _ZC_ROOTS:
        raise ValueError(f"ZC symbol index must be 4 or 6, got {symbol_index}")
    root = _ZC_ROOTS[symbol_index]
    k = np.arange(_ZC_SEQ_LEN)                      # 0..600
    zc = np.exp(-1j * np.pi * root * k * (k + 1) / _ZC_SEQ_LEN)
    return np.delete(zc, _ZC_SEQ_LEN // 2)          # drop index 300 -> 600 values


def zc_time_domain(fft_size: int, symbol_index: int) -> np.ndarray:
    """Time-domain ZC OFDM symbol (fft_size samples, no cyclic prefix).

    Equivalent to MATLAB `create_zc(fft_size, symbol_index)`: place the 600 ZC
    values on the data-carrier FFT bins, then `ifft(fftshift(freq))`.
    """
    from .ofdm import data_carrier_indices

    freq = np.zeros(fft_size, dtype=np.complex128)
    freq[data_carrier_indices(fft_size)] = zc_data_values(symbol_index)
    # MATLAB: ifft(fftshift(...)). fft_size is even so fftshift == ifftshift; we
    # mirror the reference literally.
    return np.fft.ifft(np.fft.fftshift(freq))


def zc_taps_bank(fft_size: int, symbol_index: int, shifts) -> np.ndarray:
    """Golden ZC taps pre-shifted by integer subcarrier offsets.

    Row ``i`` holds ``zc[n] * exp(+j 2 pi shifts[i] n / fft_size)``, i.e. the
    time-domain ZC symbol as it would be received with a carrier offset of
    ``shifts[i]`` whole subcarriers. Correlating the received signal against row
    ``i`` is (up to a per-lag unit phase) identical to correcting the signal by
    ``-shifts[i]`` bins and correlating against the unshifted taps -- so one
    correlation bank evaluates every integer-CFO hypothesis at once.
    """
    taps = zc_time_domain(fft_size, symbol_index)
    n = np.arange(fft_size)
    shifts = np.asarray(list(shifts), dtype=np.int64)
    return taps[None, :] * np.exp(1j * 2 * np.pi * shifts[:, None] * n[None, :] / fft_size)


def normalized_xcorr_bank(samples: np.ndarray, taps_bank: np.ndarray) -> np.ndarray:
    """Normalized cross-correlation of `samples` against every row of `taps_bank`.

    Returns ``[rows, len(samples) - taps_len]`` scores in [0, 1]. The numerator
    is computed with one FFT of the samples shared by all rows; the sliding-window
    energy (denominator) is computed once with cumulative sums.
    """
    from scipy import fft as sfft

    samples = np.asarray(samples, dtype=np.complex128)
    taps_bank = np.atleast_2d(np.asarray(taps_bank, dtype=np.complex128))
    rows, n = taps_bank.shape
    m = samples.size - n
    if m <= 0:
        return np.zeros((rows, 0))

    t0 = taps_bank - taps_bank.mean(axis=1, keepdims=True)
    t_norm = np.sqrt(np.sum(np.abs(t0) ** 2, axis=1))          # [rows]
    t_norm = np.where(t_norm == 0, np.inf, t_norm)

    # Linear correlation via FFT: lags 0..m never wrap when L >= len(samples).
    L = sfft.next_fast_len(samples.size)
    S = sfft.fft(samples, L)
    T = sfft.fft(t0, L, axis=1)
    num = sfft.ifft(S[None, :] * np.conj(T), axis=1)[:, :m]

    # Sliding-window energy: ||w0||^2 = sum|w|^2 - n*|mean(w)|^2.
    cs = np.concatenate(([0.0], np.cumsum(np.abs(samples) ** 2)))
    csum = np.concatenate(([0.0 + 0j], np.cumsum(samples)))
    win_e = cs[n : n + m] - cs[:m]                          # sum|w|^2 per window
    win_s = csum[n : n + m] - csum[:m]                      # sum(w) per window
    win_var_e = win_e - (np.abs(win_s) ** 2) / n            # = ||w0||^2
    win_norm = np.sqrt(np.maximum(win_var_e, 1e-12))

    return np.abs(num) / (win_norm[None, :] * t_norm[:, None])


def normalized_xcorr(samples: np.ndarray, taps: np.ndarray) -> np.ndarray:
    """Normalized cross-correlation; peaks point to the START of `taps` in `samples`.

    Returns an array of length ``len(samples) - len(taps)`` of values in [0, 1],
    where 1.0 is a perfect match. This is the clean normalized form
    ``|<w0, t0>| / (||w0|| ||t0||)`` (w0/t0 zero-mean). Because the taps are made
    zero-mean, the sliding-window mean cancels out of the numerator, so the
    numerator is a plain correlation computed by FFT; the denominator's sliding
    energy is computed with cumulative sums.
    """
    return normalized_xcorr_bank(samples, np.asarray(taps)[None, :])[0]


def find_zc_symbol_start(iq: np.ndarray, fft_size: int, symbol_index: int = 4,
                         ) -> tuple[int, float]:
    """Locate the start of the ZC OFDM symbol (its data, after the CP).

    Correlates `iq` against the golden time-domain ZC for `symbol_index`.
    Returns ``(offset, score)`` where `offset` is the sample index of the peak
    (start of the ZC symbol's fft_size data samples) and `score` in [0, 1].
    """
    peak, score, _k, _scores, _peaks = find_zc_symbol_start_int_cfo(
        iq, fft_size, symbol_index, shifts=(0,))
    return peak, score


def find_zc_symbol_start_int_cfo(iq: np.ndarray, fft_size: int, symbol_index: int = 4,
                                 shifts=range(-4, 5),
                                 ) -> tuple[int, float, int, np.ndarray, np.ndarray]:
    """ZC symbol search over time for each integer-subcarrier CFO hypothesis.

    Returns ``(offset, score, best_shift, per_shift_scores, per_shift_peaks)``:
    the correlation peak position/score for the highest-scoring hypothesis, the
    integer CFO (in subcarriers) that produced it, and the peak score / peak
    position for every hypothesis in `shifts`. The received signal is assumed to
    be *fractionally* CFO-corrected already.

    CAUTION -- the per-shift scores alone do NOT identify the integer CFO: a
    Zadoff-Chu sequence shifted by k subcarriers is (nearly) a time-shifted copy
    of itself, so every hypothesis peaks at ~0.9-1.0 a few samples apart. Callers
    must disambiguate with the second pilot (root 147 in symbol 6), whose
    time-shift-per-bin differs -- see ``droneid._select_integer_cfo``.
    """
    shifts = list(shifts)
    bank = zc_taps_bank(fft_size, symbol_index, shifts)
    scores = normalized_xcorr_bank(iq, bank)
    if scores.shape[1] == 0:
        z = np.zeros(len(shifts))
        return 0, 0.0, 0, z, z.astype(np.int64)
    per_shift_peaks = scores.argmax(axis=1)
    per_shift = scores[np.arange(len(shifts)), per_shift_peaks]
    best = int(np.argmax(per_shift))
    return (int(per_shift_peaks[best]), float(per_shift[best]), int(shifts[best]),
            per_shift, per_shift_peaks.astype(np.int64))
