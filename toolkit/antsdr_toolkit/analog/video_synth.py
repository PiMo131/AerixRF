"""Synthetic composite video, so the analog chain can be tested.

Builds an NTSC or PAL field at the levels the reference decoder expects
(sync tip -0.04, blanking -0.015, black -0.02, peak white +0.06) and
frequency-modulates it, giving a signal whose line rate, envelope and
occupied bandwidth are all known.  Test material only; never transmitted.
"""

from __future__ import annotations

import numpy as np

from .fpv import QUAD_DEMOD_DIVISOR_HZ, SYNC_LEVEL, WHITE_LEVEL

__all__ = ["composite_video", "fm_modulate", "video_carrier"]

#: Line timing of each standard: (line, sync, back porch, active, front porch)
#: in seconds, and the number of active lines per field.
STANDARDS = {
    "ntsc": (63.5e-6, 4.7e-6, 4.7e-6, 52.6e-6, 1.5e-6, 240),
    "pal": (64.0e-6, 4.7e-6, 5.7e-6, 51.95e-6, 1.65e-6, 288),
}
BLANK_LEVEL = -0.015


def composite_video(sample_rate_hz: float, duration_s: float, *,
                    standard: str = "ntsc",
                    rng: np.random.Generator | None = None) -> np.ndarray:
    """A composite video waveform of the requested length.

    The active line is filled with a smooth ramp plus a little noise, which is
    enough to give the modulated carrier a realistic bandwidth without
    pretending to be a picture.
    """
    if standard not in STANDARDS:
        raise ValueError(f"standard must be one of {tuple(STANDARDS)}, got {standard!r}")
    rng = np.random.default_rng(0) if rng is None else rng
    fs = float(sample_rate_hz)
    line_s, sync_s, back_s, _active_s, front_s, _lines = STANDARDS[standard]
    n_line = round(line_s * fs)
    n_sync = round(sync_s * fs)
    n_back = round(back_s * fs)
    n_front = round(front_s * fs)
    n_active = max(n_line - n_sync - n_back - n_front, 1)

    line = np.empty(n_line, dtype=np.float64)
    line[:n_sync] = SYNC_LEVEL
    line[n_sync:n_sync + n_back] = BLANK_LEVEL
    # The picture starts at blanking rather than at the decoder's nominal
    # black level, which sits *below* the sync threshold: starting there would
    # put a second threshold crossing in every line and halve the lock score.
    ramp = np.linspace(BLANK_LEVEL, WHITE_LEVEL, n_active)
    line[n_sync + n_back:n_sync + n_back + n_active] = ramp
    line[n_sync + n_back + n_active:] = BLANK_LEVEL

    n_total = round(float(duration_s) * fs)
    repeats = int(np.ceil(n_total / n_line)) + 1
    field = np.tile(line, repeats)[:n_total]
    return field + 0.002 * rng.standard_normal(n_total)


def fm_modulate(baseband: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    """Frequency-modulate at the scaling :func:`..fpv.fm_demod` inverts."""
    x = np.asarray(baseband, dtype=np.float64).ravel()
    fs = float(sample_rate_hz)
    gain = 2.0 * np.pi * QUAD_DEMOD_DIVISOR_HZ / fs
    phase = np.cumsum(x * gain)
    return np.exp(1j * phase).astype(np.complex64)


def video_carrier(sample_rate_hz: float, duration_s: float, *,
                  standard: str = "ntsc",
                  rng: np.random.Generator | None = None) -> np.ndarray:
    """A ready-made analog FPV carrier: composite video, frequency-modulated."""
    baseband = composite_video(sample_rate_hz, duration_s, standard=standard, rng=rng)
    return fm_modulate(baseband, sample_rate_hz)
