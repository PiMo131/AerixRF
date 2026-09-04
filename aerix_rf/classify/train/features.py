"""Spectrogram / IQ -> fixed-length feature vectors.

The single source of truth for how a 1-second RF frame becomes a model input.
Both training (``train.py``) and inference (``classify.model``) call these, so
live features are produced by the exact same code as the training features --
the hard requirement for the model to transfer from the bench to the box.

Two feature families, mirroring IQTLabs/RFClassification:

  * ``psd``  -- time-averaged power spectral density, resampled to a fixed
               number of bins. Compact, robust, the default.
  * ``spec`` -- the whole spectrogram downsampled to a small grid and flattened
               (an "RF thumbnail"), the input a CNN would also take.

Two normalisations make the vector independent of the front-end:

  * subtract the per-frame noise floor (a low percentile of the dB matrix) so
    absolute gain / RSSI drops out -- a bench synth at -30 dB and a HackRF at
    +10 dB look the same. A *low percentile* (not the per-bin median) is used on
    purpose: the median sits on the signal plateau for a wideband/continuous
    emitter and would erase exactly the occupancy the classifier needs, whereas
    the 10th percentile tracks the quietest bins/slices = the true noise floor.
  * resample along frequency to a fixed length so the vector's dimension does
    not depend on ``fft_size`` (live default 1024, training can differ).

Note the frequency axis is a *fraction of the captured band*, not MHz, so a
model is only valid at the ``sample_rate`` it was trained at. The trained bundle
records that rate; ``classify.model`` warns on a mismatch.
"""

from __future__ import annotations

import numpy as np

from ...dsp.spectrogram import Spectrogram, compute

# Defaults chosen small: light sklearn models, fast tests, still separable.
PSD_BINS = 256                 # length of the resampled PSD feature vector
SPEC_SHAPE = (32, 32)          # (freq, time) grid of the downsampled-spectrogram feature
FEATURE_KINDS = ("psd", "spec")
FLOOR_PCT = 10.0               # noise-floor percentile subtracted for gain-invariance


def _noise_floor(power_db: np.ndarray) -> float:
    """Scalar noise floor: a low percentile over the whole [T,F] dB matrix."""
    return float(np.percentile(power_db, FLOOR_PCT))


def _resample_1d(x: np.ndarray, n: int) -> np.ndarray:
    """Linear-resample a 1-D array to length ``n`` (freq-axis rescale)."""
    if x.size == n:
        return x.astype(np.float32)
    src = np.linspace(0.0, 1.0, num=x.size, dtype=np.float64)
    dst = np.linspace(0.0, 1.0, num=n, dtype=np.float64)
    return np.interp(dst, src, x).astype(np.float32)


def _resample_2d(m: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Linear-resample a 2-D array to ``shape`` (separable, axis by axis)."""
    fr, ft = shape
    # along axis 0 (rows), then axis 1 (cols)
    tmp = np.stack([_resample_1d(m[:, j], fr) for j in range(m.shape[1])], axis=1)
    out = np.stack([_resample_1d(tmp[i, :], ft) for i in range(tmp.shape[0])], axis=0)
    return out.astype(np.float32)


def psd_feature(spec: Spectrogram, n_bins: int = PSD_BINS) -> np.ndarray:
    """Time-averaged PSD (dB), noise-floor-subtracted, resampled to ``n_bins``."""
    p = np.asarray(spec.power_db, dtype=np.float64)          # [T, F]
    psd = p.mean(axis=0) - _noise_floor(p)                   # kill absolute gain
    return _resample_1d(psd, n_bins)


def spectrogram_feature(spec: Spectrogram,
                        shape: tuple[int, int] = SPEC_SHAPE) -> np.ndarray:
    """Whole spectrogram (dB) -> small [freq,time] grid, floor-subtracted, flat."""
    p = np.asarray(spec.power_db, dtype=np.float64)          # [T, F]
    p = (p - _noise_floor(p)).T                              # [F, T], floor-subtracted
    grid = _resample_2d(p, shape)
    return grid.reshape(-1).astype(np.float32)


def extract(spec: Spectrogram, kind: str = "psd", *,
            psd_bins: int = PSD_BINS,
            spec_shape: tuple[int, int] = SPEC_SHAPE) -> np.ndarray:
    """Spectrogram -> feature vector for the given ``kind`` ('psd' | 'spec')."""
    if kind == "psd":
        return psd_feature(spec, psd_bins)
    if kind == "spec":
        return spectrogram_feature(spec, spec_shape)
    raise ValueError(f"unknown feature kind {kind!r}; expected one of {FEATURE_KINDS}")


def extract_from_iq(iq: np.ndarray, sample_rate: float, kind: str = "psd", *,
                    fft_size: int = 1024,
                    psd_bins: int = PSD_BINS,
                    spec_shape: tuple[int, int] = SPEC_SHAPE) -> np.ndarray:
    """Raw complex IQ -> feature vector, via the box's own ``spectrogram.compute``."""
    spec = compute(iq, sample_rate, fft_size=fft_size)
    return extract(spec, kind, psd_bins=psd_bins, spec_shape=spec_shape)


def feature_dim(kind: str = "psd", *, psd_bins: int = PSD_BINS,
                spec_shape: tuple[int, int] = SPEC_SHAPE) -> int:
    return psd_bins if kind == "psd" else spec_shape[0] * spec_shape[1]
