"""Fixed 1 ms-grid windowing for canonical dataset normalisation (Workstream D, T3).

Implements stage S3 of ``docs/design/dataset-normalization.md``: tile a
(post-S2, canonical-rate) IQ stream into non-overlapping windows on an
integer-millisecond grid, target duration 1.000 s. The one hard rule from the
memo ("Zero-padding to 1000 frames is forbidden -- a constant silent tail is
a perfect dataset label a CNN finds in one epoch") governs this module:
a source shorter than ``window_s`` (or with a short remainder after full
windows are taken) yields a genuinely short window -- flagged, never padded
to nominal length. Any leftover strictly shorter than one grid step
(``grid_ms``) is dropped entirely: it cannot form even one output ms-frame in
``tensor.py`` and there is nothing meaningful to pad it with.
"""

from __future__ import annotations

from typing import Iterator

import numpy as np


def _grid_step_samples(sample_rate_hz: float, grid_ms: int) -> int:
    """Samples per ``grid_ms`` millisecond step, rounded to the nearest
    integer. Exact (no rounding) for the canonical rate (15.36 MS/s -> 15360
    samples/ms) and for any other integer-MS/s rate."""

    return int(round(float(sample_rate_hz) * grid_ms / 1000.0))


def _window_len_samples(sample_rate_hz: float, window_s: float, grid_ms: int) -> int:
    grid_step = _grid_step_samples(sample_rate_hz, grid_ms)
    steps = int(round(window_s * 1000.0 / grid_ms))
    return steps * grid_step


def iter_windows(
    iq: np.ndarray,
    sample_rate_hz: float,
    window_s: float = 1.0,
    grid_ms: int = 1,
) -> Iterator[tuple[int, np.ndarray, bool]]:
    """Tile ``iq`` into non-overlapping windows of ``window_s`` seconds on a
    ``grid_ms``-millisecond sample grid.

    Yields ``(start_sample, iq_window, short)`` in order. ``short`` is True
    iff ``iq_window`` is shorter than the nominal ``window_s`` (only possible
    for the last window of a source, or the whole source if it is itself
    shorter than ``window_s``). Windows are never padded -- ``iq_window``'s
    true length is the true number of grid-aligned samples available.
    A trailing remainder shorter than one ``grid_ms`` step is dropped (it
    cannot form a single output ms-frame downstream).
    """

    grid_step = _grid_step_samples(sample_rate_hz, grid_ms)
    if grid_step <= 0:
        raise ValueError(f"sample_rate_hz={sample_rate_hz!r} / grid_ms={grid_ms!r} gives a non-positive grid step")
    window_len = _window_len_samples(sample_rate_hz, window_s, grid_ms)

    n = iq.shape[-1]
    start = 0
    while start < n:
        remaining = n - start
        n_steps = remaining // grid_step
        if n_steps == 0:
            break  # < 1 grid step left: dropped, not fabricated into a window
        this_len = min(window_len, n_steps * grid_step)
        short = this_len < window_len
        yield start, iq[..., start:start + this_len], short
        start += this_len


def n_expected_windows(
    n_samples: int,
    sample_rate_hz: float,
    window_s: float = 1.0,
    grid_ms: int = 1,
) -> int:
    """Number of windows :func:`iter_windows` would yield for a source of
    ``n_samples``, without materialising any IQ data."""

    grid_step = _grid_step_samples(sample_rate_hz, grid_ms)
    if grid_step <= 0:
        raise ValueError(f"sample_rate_hz={sample_rate_hz!r} / grid_ms={grid_ms!r} gives a non-positive grid step")
    window_len = _window_len_samples(sample_rate_hz, window_s, grid_ms)

    count = 0
    start = 0
    n_samples = int(n_samples)
    while start < n_samples:
        remaining = n_samples - start
        n_steps = remaining // grid_step
        if n_steps == 0:
            break
        this_len = min(window_len, n_steps * grid_step)
        count += 1
        start += this_len
    return count
