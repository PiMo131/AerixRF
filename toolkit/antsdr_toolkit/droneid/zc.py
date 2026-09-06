"""Zadoff-Chu pilot symbols: the thing that makes a DroneID burst findable.

Symbols 4 and 6 of every burst carry a Zadoff-Chu sequence of length 601 with
roots 600 and 147.  Zadoff-Chu sequences have constant amplitude in both
domains and an almost ideal autocorrelation, so correlating a capture against
the root-600 waveform finds the burst even at a frequency offset of more than
a megahertz, which is what a first-stage detector needs.

Construction (identical in both reference projects):

1. ``z[n] = exp(-j * pi * root * n * (n + 1) / 601)`` for ``n = 0 .. 600``.
2. Delete element 300, which lands on the null DC carrier, leaving 600 values.
3. Place them on the 600 data carriers of an ``N``-point spectrum, DC null.
4. Inverse-FFT to get the time-domain symbol (no cyclic prefix).

The root-600 time-domain symbol is *approximately* mirror-symmetric: its
first half correlates with its reversed second half at about 0.85, against
about 0.52 for root 147 (measured on this implementation at 15.36 MSPS).  The
reference C++ uses that as a reference-free burst detector.  It is a weak
discriminator on its own - :func:`half_symmetry` returns the coherence so a
caller can decide - and the reason it is not 1.0 is the deleted DC carrier and
the guard bins between the 601 occupied carriers and the FFT size.
"""

from __future__ import annotations

import functools

import numpy as np

from .constants import N_CARRIERS, N_DATA_CARRIERS, ZC_ROOTS, fft_size

__all__ = ["carrier_indices", "half_symmetry", "zc_frequency", "zc_sequence", "zc_time"]


def zc_sequence(root: int, length: int = N_CARRIERS) -> np.ndarray:
    """The raw length-601 Zadoff-Chu sequence for ``root`` (DC element kept)."""
    if length <= 0:
        raise ValueError(f"length must be positive, got {length}")
    n = np.arange(length, dtype=np.float64)
    return np.exp(-1j * np.pi * float(root) * n * (n + 1.0) / float(length))


def carrier_indices(n_fft: int) -> np.ndarray:
    """Indices of the 600 data carriers in an fft-shifted ``n_fft`` spectrum.

    The occupied band is the 601 bins centred on DC; the DC bin itself is
    dropped, leaving 300 bins below and 300 above.
    """
    if n_fft < N_CARRIERS:
        raise ValueError(f"n_fft {n_fft} is smaller than the {N_CARRIERS} occupied carriers")
    dc = n_fft // 2
    half = N_DATA_CARRIERS // 2
    return np.concatenate([np.arange(dc - half, dc), np.arange(dc + 1, dc + 1 + half)])


def zc_frequency(root: int, n_fft: int) -> np.ndarray:
    """The Zadoff-Chu symbol as an fft-shifted spectrum of ``n_fft`` bins."""
    seq = zc_sequence(root)
    values = np.delete(seq, N_CARRIERS // 2)  # drop the DC element
    spectrum = np.zeros(int(n_fft), dtype=np.complex128)
    spectrum[carrier_indices(int(n_fft))] = values
    return spectrum


@functools.lru_cache(maxsize=32)
def _zc_time_cached(root: int, n_fft: int) -> np.ndarray:
    spectrum = zc_frequency(root, n_fft)
    time = np.fft.ifft(np.fft.ifftshift(spectrum))
    return np.ascontiguousarray(time.astype(np.complex64))


def zc_time(root: int, sample_rate_hz: float | None = None, *,
            n_fft: int | None = None) -> np.ndarray:
    """Time-domain Zadoff-Chu symbol, one FFT long, no cyclic prefix.

    Give either a sample rate (the FFT size follows from the 15 kHz spacing)
    or an explicit ``n_fft``.  Results are cached: the same root and size are
    wanted for every correlation.
    """
    if n_fft is None:
        if sample_rate_hz is None:
            raise ValueError("give either sample_rate_hz or n_fft")
        n_fft = fft_size(sample_rate_hz)
    return _zc_time_cached(int(root), int(n_fft)).copy()


def half_symmetry(symbol: np.ndarray) -> float:
    """Coherence in ``[0, 1]`` between the first half and the reversed second.

    About 0.85 for the root-600 pilot and 0.52 for root 147 at any supported
    sample rate, because root 600 is congruent to -1 modulo the sequence
    length 601 and is therefore close to its own time reversal.  Phase-blind
    (the magnitude of the normalised inner product), so a frequency offset
    does not destroy it, which is what makes it usable before synchronisation.
    """
    x = np.asarray(symbol, dtype=np.complex128).ravel()
    n = x.size // 2
    if n == 0:
        return 0.0
    first, second = x[:n], x[n:2 * n][::-1]
    denom = np.linalg.norm(first) * np.linalg.norm(second)
    if denom <= 0.0:
        return 0.0
    return float(abs(np.vdot(second, first)) / denom)


def roots_for(sample_rate_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """The two pilot symbols (roots 600 and 147) at this sample rate."""
    return tuple(zc_time(root, sample_rate_hz) for root in ZC_ROOTS)  # type: ignore[return-value]
