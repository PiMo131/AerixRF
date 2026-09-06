"""Turn target frequencies or a band into the fewest receiver dwells.

A *dwell* is one receiver tuning: ``center_freq_hz`` plus the ``span_hz`` of
baseband that is trusted after discarding the anti-alias roll-off at the
edges of the sample rate.  The AD9361 applies a ~0.8-1.0 x Fs analog filter,
so following lukeswitz/fpv-sdr only ``usable_fraction`` (default 0.8) of the
sample rate is used: 32 MHz at 40 MSPS, 16 MHz at the E200's realistic
20 MSPS host rate.

Two planning modes:

* **Target list** (:func:`plan_dwells` with a sequence of frequencies, Hz):
  the greedy chunk plan of fpv-sdr, re-implemented from its description -
  sort the unique targets, open a group at the lowest unassigned target and
  keep adding targets while ``f - lowest <= width``, centre the dwell on
  ``(lowest + highest) / 2``.  Every target therefore lies inside its dwell's
  usable span by construction.  With the 53 unique fpv-sdr channel
  frequencies this yields 16 dwells at 40 MSPS, 24 at 20 and 16 MSPS and 28
  at 12 MSPS (fpv-sdr's own numbers; unit-tested).
* **Band tiling** (:func:`plan_dwells` with a :class:`~.bands.Band` or a
  band name): ``n = ceil((span - usable) / step) + 1`` tiles whose centres
  are spread evenly from ``f_low + usable / 2`` to ``f_high - usable / 2``,
  so the first and last tiles end exactly on the band edges and any surplus
  is shared as equal overlap between neighbours.

``overlap`` (0 <= overlap < 1) is a fraction of the usable span: for a band
it is the minimum share two neighbouring tiles have in common (``step =
usable * (1 - overlap)``); for a target list the grouping width shrinks to
``usable * (1 - overlap)`` so every target keeps a guard of
``overlap * usable / 2`` to the dwell edge (room for the target's own
bandwidth - e.g. +-4.5 MHz of an analog FPV carrier).  ``overlap = 0``
reproduces fpv-sdr exactly.

Sources: https://github.com/lukeswitz/fpv-sdr (chunk_plan description, 0.8
usable fraction, 40/20 MSPS rate choices - algorithm re-implemented, no code
copied because the Python files carry GPL-3.0 headers);
https://github.com/ALPssdz/RF-Vision-UAV-Tracker (fixed 40 MHz sectors at
5745/5785/5825 MHz, the band-tiling special case).  Units: Hz throughout.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .bands import Band, get_band

__all__ = ["Dwell", "plan_dwells", "plan_summary", "usable_span_hz"]

DEFAULT_USABLE_FRACTION = 0.8
"""Fraction of the sample rate trusted per dwell (fpv-sdr ``--usable-frac``)."""


@dataclass(frozen=True)
class Dwell:
    """One receiver tuning of a sweep plan.

    Attributes:
        center_freq_hz: LO / centre frequency to tune to, Hz.
        span_hz: Usable baseband span around the centre, Hz (``<=`` sample rate).
        targets: Requested frequencies (Hz, ascending) this dwell was built to
            cover; empty for tiles of a band.
    """

    center_freq_hz: float
    span_hz: float
    targets: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "center_freq_hz", float(self.center_freq_hz))
        object.__setattr__(self, "span_hz", float(self.span_hz))
        object.__setattr__(self, "targets", tuple(sorted(float(t) for t in self.targets)))
        if not self.span_hz > 0.0:
            raise ValueError(f"span_hz must be positive, got {self.span_hz}")

    @property
    def f_low_hz(self) -> float:
        return self.center_freq_hz - self.span_hz / 2.0

    @property
    def f_high_hz(self) -> float:
        return self.center_freq_hz + self.span_hz / 2.0

    def covers(self, freq_hz: float) -> bool:
        """``True`` when ``freq_hz`` lies inside the usable span (edges inclusive)."""
        return self.f_low_hz <= float(freq_hz) <= self.f_high_hz

    def to_dict(self) -> dict[str, Any]:
        return {
            "center_freq_hz": self.center_freq_hz,
            "span_hz": self.span_hz,
            "f_low_hz": self.f_low_hz,
            "f_high_hz": self.f_high_hz,
            "targets": list(self.targets),
        }


def usable_span_hz(sample_rate_hz: float, usable_fraction: float = DEFAULT_USABLE_FRACTION) -> float:
    """Trusted baseband span for a sample rate: ``usable_fraction * sample_rate_hz``."""
    fs = float(sample_rate_hz)
    frac = float(usable_fraction)
    if not fs > 0.0:
        raise ValueError(f"sample_rate_hz must be positive, got {fs}")
    if not 0.0 < frac <= 1.0:
        raise ValueError(f"usable_fraction must be in (0, 1], got {frac}")
    return fs * frac


def _check_overlap(overlap: float) -> float:
    ov = float(overlap)
    if not 0.0 <= ov < 1.0:
        raise ValueError(f"overlap must be in [0, 1), got {ov}")
    return ov


def _plan_targets(freqs_hz: Iterable[float], usable: float, overlap: float) -> list[Dwell]:
    """Greedy chunk plan over unique ascending targets (fpv-sdr algorithm)."""
    targets = np.unique(np.asarray(list(freqs_hz), dtype=np.float64))
    if targets.size == 0:
        return []
    if not np.all(np.isfinite(targets)) or np.any(targets <= 0.0):
        raise ValueError("target frequencies must be finite and positive (Hz)")
    width = usable * (1.0 - overlap)
    plan: list[Dwell] = []
    i, n = 0, targets.size
    while i < n:
        lo = targets[i]
        j = i
        while j < n and targets[j] - lo <= width:
            j += 1
        group = targets[i:j]
        plan.append(Dwell(0.5 * (group[0] + group[-1]), usable, tuple(group.tolist())))
        i = j
    return plan


def _plan_band(band: Band, usable: float, overlap: float) -> list[Dwell]:
    """Evenly spread contiguous tiles covering ``[f_low, f_high]`` exactly."""
    span = band.span_hz
    if span <= usable:
        return [Dwell(band.center_freq_hz, usable)]
    step = usable * (1.0 - overlap)
    n_tiles = math.ceil((span - usable) / step - 1e-9) + 1
    centers = np.linspace(band.f_low_hz + usable / 2.0, band.f_high_hz - usable / 2.0, n_tiles)
    return [Dwell(float(c), usable) for c in centers]


def plan_dwells(
    freqs_or_band: Band | str | Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    *,
    usable_fraction: float = DEFAULT_USABLE_FRACTION,
    overlap: float = 0.0,
) -> list[Dwell]:
    """Plan the dwells that cover a target list or a band at ``sample_rate_hz``.

    Parameters
    ----------
    freqs_or_band
        A :class:`~.bands.Band`, a band name from :data:`~.bands.BAND_PLANS`,
        or a sequence of absolute target frequencies in Hz (duplicates and
        order do not matter).
    sample_rate_hz
        Complex sample rate the receiver will run at, Hz.
    usable_fraction
        Trusted fraction of the sample rate per dwell (0 < f <= 1).
    overlap
        Fraction of the usable span used as inter-tile overlap (band) or as
        edge guard around targets (list); see the module docstring.

    Returns dwells in ascending centre-frequency order.  An empty target list
    gives an empty plan.
    """
    usable = usable_span_hz(sample_rate_hz, usable_fraction)
    ov = _check_overlap(overlap)
    if isinstance(freqs_or_band, (Band, str)):
        return _plan_band(get_band(freqs_or_band), usable, ov)
    return _plan_targets(freqs_or_band, usable, ov)


def plan_summary(plan: Sequence[Dwell]) -> dict[str, Any]:
    """Aggregate facts about a plan: count, covered extent and target count."""
    if not plan:
        return {"n_dwells": 0, "f_low_hz": None, "f_high_hz": None, "n_targets": 0,
                "total_span_hz": 0.0}
    return {
        "n_dwells": len(plan),
        "f_low_hz": min(d.f_low_hz for d in plan),
        "f_high_hz": max(d.f_high_hz for d in plan),
        "n_targets": sum(len(d.targets) for d in plan),
        "total_span_hz": float(sum(d.span_hz for d in plan)),
    }
