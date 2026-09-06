"""Spectral estimation helpers: STFT power maps, Welch spectra and noise floors.

Conventions used throughout this module
---------------------------------------
* IQ input is complex baseband, shape ``(n,)`` for one channel or
  ``(channels, n)`` for several.  Multi-channel input is combined by
  averaging the *linear* power of the channels (incoherent combining), so
  the output always has a single frequency axis.
* Powers are in dB relative to full scale: ``10*log10(|X|^2)`` where a
  complex tone of amplitude 1.0 reads ~0 dB at its bin.  This "spectrum"
  scaling divides the windowed FFT by the coherent gain ``sum(w)`` so that
  tone levels are independent of ``fft_size`` and window; noise, on the
  other hand, spreads over the bins and reads
  ``P_noise * ENBW_bins / fft_size`` per bin (for a Hann window
  ``ENBW_bins = 1.5``, i.e. -28.3 dB below the total for 1024 bins).
* Frequency axes are absolute Hz (baseband offset + centre frequency),
  fft-shifted so they are monotonically increasing.  Times are seconds.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy import ndimage, signal

__all__ = [
    "db",
    "db_amplitude",
    "estimate_noise_floor_db",
    "fft_freqs_hz",
    "percentile_bias_db",
    "stft_power_db",
    "welch_psd_db",
]

# Largest number of samples per STFT chunk; bounds the transient memory of the
# framed FFT (frames x fft_size complex values) to a few tens of MB.
_STFT_CHUNK_SAMPLES = 1 << 22


def db(x_power: np.ndarray | float, floor: float = 1e-20) -> np.ndarray:
    """Convert linear power to dB with a floor that avoids ``log10(0)``.

    ``floor`` is a linear power (default 1e-20 -> -200 dB).  Floating-point
    dtypes are preserved (float32 in, float32 out); integer input becomes
    float64.
    """
    x = np.asarray(x_power)
    if not np.issubdtype(x.dtype, np.floating):
        x = x.astype(np.float64)
    return 10.0 * np.log10(np.maximum(x, floor))


def db_amplitude(x: np.ndarray | complex, floor: float = 1e-10) -> np.ndarray:
    """Convert an amplitude (possibly complex) to dB: ``20*log10(|x|)`` with a floor."""
    mag = np.abs(np.asarray(x))
    if not np.issubdtype(mag.dtype, np.floating):
        mag = mag.astype(np.float64)
    return 20.0 * np.log10(np.maximum(mag, floor))


def fft_freqs_hz(fft_size: int, sample_rate_hz: float, center_freq_hz: float) -> np.ndarray:
    """Absolute, ascending frequency axis of an fft-shifted ``fft_size``-point spectrum."""
    return np.fft.fftshift(np.fft.fftfreq(int(fft_size), d=1.0 / float(sample_rate_hz))) + float(
        center_freq_hz
    )


def _window(window: str | tuple | np.ndarray, n: int) -> np.ndarray:
    """Return a periodic (DFT-even) analysis window of length ``n`` as float64."""
    if isinstance(window, np.ndarray):
        if window.shape != (n,):
            raise ValueError(f"window array must have shape ({n},), got {window.shape}")
        return window.astype(np.float64)
    return signal.get_window(window, n, fftbins=True).astype(np.float64)


def _as_channels(x: np.ndarray) -> np.ndarray:
    """Coerce IQ to shape (channels, n) without copying when possible."""
    x = np.asarray(x)
    if x.ndim == 1:
        return x[np.newaxis, :]
    if x.ndim == 2:
        return x
    raise ValueError(f"IQ must be 1-D or 2-D (channels, n), got shape {x.shape}")


def stft_power_db(
    x: np.ndarray,
    sample_rate_hz: float,
    center_freq_hz: float,
    *,
    fft_size: int = 1024,
    hop: int | None = None,
    window: str | tuple | np.ndarray = "hann",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Short-time power spectrum (spectrogram) in dB.

    Parameters
    ----------
    x
        Complex IQ, shape ``(n,)`` or ``(channels, n)``.  Channels are
        combined by averaging their linear power.
    sample_rate_hz, center_freq_hz
        Sample rate and RF centre frequency, Hz.
    fft_size
        Frame length and FFT size (no zero padding).
    hop
        Frame advance in samples; defaults to ``fft_size // 2``.
    window
        Window name / tuple for :func:`scipy.signal.get_window`, or an
        explicit array of length ``fft_size``.

    Returns
    -------
    power_db : float32, shape ``(frames, bins)``
        FFT-shifted power in dB; a unit-amplitude tone on a bin reads ~0 dB.
    freqs_hz : float64, shape ``(bins,)``
        Absolute, ascending bin centre frequencies.
    times_s : float64, shape ``(frames,)``
        Frame centre times in seconds from the first sample.

    Input shorter than ``fft_size`` is zero-padded to a single frame; trailing
    samples that do not fill a whole frame are dropped.
    """
    fft_size = int(fft_size)
    if fft_size < 2:
        raise ValueError("fft_size must be >= 2")
    hop = fft_size // 2 if hop is None else int(hop)
    if hop < 1:
        raise ValueError("hop must be >= 1")
    fs = float(sample_rate_hz)

    xc = _as_channels(x)
    if not np.iscomplexobj(xc):
        xc = xc.astype(np.complex64)
    n_ch, n = xc.shape
    if n < fft_size:
        pad = np.zeros((n_ch, fft_size - n), dtype=xc.dtype)
        xc = np.concatenate([xc, pad], axis=1)
        n = fft_size
    n_frames = 1 + (n - fft_size) // hop

    w = _window(window, fft_size)
    gain = float(w.sum())
    w_typed = w.astype(np.float32 if xc.dtype == np.complex64 else np.float64)

    # (channels, n_frames, fft_size) strided view: no copy until multiplied by w.
    frames = sliding_window_view(xc, fft_size, axis=1)[:, ::hop, :][:, :n_frames, :]
    power = np.empty((n_frames, fft_size), dtype=np.float32)
    chunk = max(1, _STFT_CHUNK_SAMPLES // (fft_size * n_ch))
    for start in range(0, n_frames, chunk):
        seg = frames[:, start : start + chunk, :] * w_typed
        spec = np.fft.fft(seg, axis=-1)
        p = (spec.real * spec.real + spec.imag * spec.imag).mean(axis=0)
        power[start : start + chunk] = np.fft.fftshift(p, axes=-1)
    power /= np.float32(gain * gain)

    freqs_hz = fft_freqs_hz(fft_size, fs, center_freq_hz)
    times_s = (np.arange(n_frames, dtype=np.float64) * hop + fft_size / 2.0) / fs
    return db(power), freqs_hz, times_s


def welch_psd_db(
    x: np.ndarray,
    sample_rate_hz: float,
    center_freq_hz: float,
    *,
    nfft: int = 4096,
    window: str | tuple | np.ndarray = "hann",
    scaling: str = "spectrum",
) -> tuple[np.ndarray, np.ndarray]:
    """Welch-averaged two-sided spectrum in dB on an absolute frequency axis.

    Segments of ``nfft`` samples with 50 % overlap are windowed, transformed
    and averaged.  With ``scaling="spectrum"`` (default) a unit-amplitude tone
    reads ~0 dB, consistent with :func:`stft_power_db`; with
    ``scaling="density"`` the result is a power spectral density in dB/Hz.
    Multi-channel input is averaged in linear power.

    Returns ``(freqs_hz ascending, psd_db)`` each of length ``nfft``.
    """
    nfft = int(nfft)
    if nfft < 2:
        raise ValueError("nfft must be >= 2")
    fs = float(sample_rate_hz)
    xc = _as_channels(x)
    if not np.iscomplexobj(xc):
        xc = xc.astype(np.complex64)
    nperseg = min(nfft, xc.shape[-1])
    win = _window(window, nperseg) if not isinstance(window, np.ndarray) else window
    freqs, pxx = signal.welch(
        xc,
        fs=fs,
        window=win,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        nfft=nfft,
        detrend=False,
        return_onesided=False,
        scaling=scaling,
        axis=-1,
    )
    pxx = np.asarray(pxx, dtype=np.float64).mean(axis=0)
    freqs_hz = np.fft.fftshift(freqs) + float(center_freq_hz)
    return freqs_hz, db(np.fft.fftshift(pxx))


def percentile_bias_db(percentile: float) -> float:
    """Offset (dB) from a low percentile of noise power to its mean.

    Bin powers of complex Gaussian noise are exponentially distributed, so
    the ``q``-quantile equals ``-ln(1 - q)`` times the mean.  Adding the
    returned value to a percentile-based floor estimates the *mean* noise
    power (e.g. +6.5 dB for the 20th percentile, +1.6 dB for the median).
    """
    q = float(percentile) / 100.0
    if not 0.0 < q < 1.0:
        raise ValueError("percentile must be in (0, 100)")
    return -10.0 * math.log10(-math.log(1.0 - q))


def estimate_noise_floor_db(
    power_db: np.ndarray,
    *,
    axis: int = 0,
    percentile: float = 20.0,
    smooth_bins: int = 0,
    bias_correct: bool = False,
) -> np.ndarray:
    """Robust per-bin noise floor of a dB power map.

    Takes a low percentile along the time ``axis`` (frames), so short bursts
    that occupy less than ``100 - percentile`` percent of the frames do not
    lift the estimate.  ``smooth_bins > 1`` applies a median filter of that
    width across the remaining (frequency) axis to suppress bin-to-bin
    variance.  ``bias_correct=True`` adds :func:`percentile_bias_db` so the
    result estimates the mean noise power rather than its ``percentile``-th
    quantile.

    Returns an array with ``axis`` removed (shape ``(bins,)`` for the usual
    ``(frames, bins)`` input).
    """
    p = np.asarray(power_db)
    if p.ndim < 1:
        raise ValueError("power_db must be at least 1-D")
    if not np.issubdtype(p.dtype, np.floating):
        p = p.astype(np.float64)
    floor = np.percentile(p, float(percentile), axis=axis)
    floor = np.asarray(floor, dtype=p.dtype)
    if smooth_bins and int(smooth_bins) > 1 and floor.ndim >= 1:
        floor = ndimage.median_filter(floor, size=int(smooth_bins), mode="nearest")
    if bias_correct:
        floor = floor + p.dtype.type(percentile_bias_db(percentile))
    return floor
