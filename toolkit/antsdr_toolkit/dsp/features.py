"""Burst-set features: what a *collection* of detected bursts says about an emitter.

Given the :class:`~antsdr_toolkit.dsp.bursts.Burst` boxes found in one
observation window, :func:`burst_features` summarises the timing, bandwidth
and frequency-agility statistics that separate the waveform families seen in
drone links (before any classifier is trained):

* OFDM video/control links (OcuSync, Wi-Fi): wide (10-40 MHz), periodic
  bursts at one or two centres, high duty cycle.
* FHSS control links (Lightbridge, ELRS, FrSky, SiK): narrow bursts, many
  distinct centres on a regular grid, hundreds of hops per second.
* Analog FPV video: one continuous carrier, duty cycle ~1, Carson-rule
  bandwidth.
* LoRa telemetry: narrow, long, sparse bursts at a fixed centre.

Units: seconds, Hz, dB.  Statistics that are undefined for the number of
bursts at hand (e.g. intervals with fewer than two bursts) are reported as
``0.0`` rather than NaN so the feature vector stays JSON- and
classifier-friendly; ``n_bursts`` tells the consumer how much to trust them.

Frequency-agility definitions
-----------------------------
*Distinct centres* are found by 1-D greedy clustering of the sorted burst
centre frequencies: a burst joins the current cluster while it lies within
``center_tolerance_hz`` of the cluster's lowest member, otherwise it starts
a new one, so every cluster spans at most the tolerance.  ``hop_rate_hz``
counts how often consecutive bursts (in start-time order) change cluster,
divided by the span from the first to the last burst start - the rate of an
emitter that hops on every burst, independent of how much of the window it
was active in.  Two emitters transmitting alternately at different
frequencies are indistinguishable from one hopper at this level.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

from .bursts import Burst

__all__ = [
    "BurstFeatures",
    "burst_features",
    "bursts_to_table",
    "cluster_centers",
    "occupied_fraction",
]


@dataclass(frozen=True)
class BurstFeatures:
    """Summary statistics of the bursts detected in one observation window."""

    n_bursts: int
    window_s: float
    duty_cycle: float
    bandwidth_median_hz: float
    bandwidth_p10_hz: float
    bandwidth_p90_hz: float
    duration_median_s: float
    duration_p10_s: float
    duration_p90_s: float
    interval_median_s: float
    interval_cv: float
    n_distinct_centers: int
    center_spacing_median_hz: float
    hop_rate_hz: float
    occupied_span_hz: float
    snr_median_db: float

    def to_dict(self) -> dict[str, float | int]:
        """Plain dict of all fields (JSON-serialisable, no NaN)."""
        return asdict(self)


def cluster_centers(
    centers_hz: Sequence[float] | np.ndarray, tolerance_hz: float
) -> tuple[np.ndarray, np.ndarray]:
    """Greedy 1-D clustering of frequencies; returns ``(labels, cluster_means_hz)``.

    ``labels[i]`` is the cluster index (ascending in frequency) of
    ``centers_hz[i]``; ``cluster_means_hz`` are the sorted cluster mean
    frequencies.  A value joins the current cluster while it lies within
    ``tolerance_hz`` of the cluster's lowest member (so each cluster spans at
    most ``tolerance_hz``); ``tolerance_hz <= 0`` clusters exact matches only.
    """
    c = np.asarray(centers_hz, dtype=np.float64).ravel()
    if c.size == 0:
        return np.zeros(0, dtype=np.intp), np.zeros(0, dtype=np.float64)
    order = np.argsort(c, kind="stable")
    sorted_c = c[order]
    # a new cluster starts wherever the value exceeds the running cluster origin + tolerance
    labels_sorted = np.empty(c.size, dtype=np.intp)
    origin = sorted_c[0]
    label = 0
    for i, value in enumerate(sorted_c):
        if value - origin > float(tolerance_hz):
            label += 1
            origin = value
        labels_sorted[i] = label
    labels = np.empty(c.size, dtype=np.intp)
    labels[order] = labels_sorted
    means = np.array(
        [sorted_c[labels_sorted == k].mean() for k in range(label + 1)], dtype=np.float64
    )
    return labels, means


def occupied_fraction(bursts: Sequence[Burst], window_s: float) -> float:
    """Fraction of ``[0, window_s]`` during which at least one burst is active.

    Union of the burst time intervals (overlaps counted once), clipped to
    the window, divided by ``window_s``.
    """
    w = float(window_s)
    if w <= 0.0 or not bursts:
        return 0.0
    ivals = sorted((max(b.t_start_s, 0.0), min(b.t_end_s, w)) for b in bursts)
    total, cur_start, cur_end = 0.0, None, None
    for start, end in ivals:
        if end <= start:
            continue
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        elif end > cur_end:
            cur_end = end
    if cur_end is not None:
        total += cur_end - cur_start
    return min(total / w, 1.0)


def burst_features(
    bursts: Sequence[Burst], *, window_s: float, center_tolerance_hz: float = 250e3
) -> BurstFeatures:
    """Compute :class:`BurstFeatures` for the bursts of one observation window.

    ``window_s`` is the observed duration (used for ``duty_cycle``).
    ``center_tolerance_hz`` sets how far apart two burst centres may be and
    still count as the same channel - a few STFT bins plus the expected
    centre jitter of the waveform (default 250 kHz suits 1-2 MHz FHSS
    channels; use ~1 MHz for 10-20 MHz OFDM channels).
    """
    n = len(bursts)
    w = float(window_s)
    if n == 0:
        return BurstFeatures(0, w, 0.0, *([0.0] * 8), 0, 0.0, 0.0, 0.0, 0.0)

    bw = np.array([b.bandwidth_hz for b in bursts], dtype=np.float64)
    dur = np.array([b.duration_s for b in bursts], dtype=np.float64)
    snr = np.array([b.snr_db for b in bursts], dtype=np.float64)
    centers = np.array([b.center_freq_hz for b in bursts], dtype=np.float64)
    starts = np.array([b.t_start_s for b in bursts], dtype=np.float64)
    order = np.argsort(starts, kind="stable")

    intervals = np.diff(starts[order])
    if intervals.size:
        interval_median = float(np.median(intervals))
        mean_iv = float(np.mean(intervals))
        interval_cv = float(np.std(intervals) / mean_iv) if mean_iv > 0.0 else 0.0
    else:
        interval_median = interval_cv = 0.0

    labels, means = cluster_centers(centers, center_tolerance_hz)
    spacing_median = float(np.median(np.diff(means))) if means.size > 1 else 0.0
    seq = labels[order]
    changes = int(np.count_nonzero(seq[1:] != seq[:-1]))
    span = float(starts[order][-1] - starts[order][0])
    hop_rate = changes / span if span > 0.0 else 0.0

    return BurstFeatures(
        n_bursts=n,
        window_s=w,
        duty_cycle=occupied_fraction(bursts, w),
        bandwidth_median_hz=float(np.median(bw)),
        bandwidth_p10_hz=float(np.percentile(bw, 10)),
        bandwidth_p90_hz=float(np.percentile(bw, 90)),
        duration_median_s=float(np.median(dur)),
        duration_p10_s=float(np.percentile(dur, 10)),
        duration_p90_s=float(np.percentile(dur, 90)),
        interval_median_s=interval_median,
        interval_cv=interval_cv,
        n_distinct_centers=int(means.size),
        center_spacing_median_hz=spacing_median,
        hop_rate_hz=float(hop_rate),
        occupied_span_hz=float(max(b.f_high_hz for b in bursts) - min(b.f_low_hz for b in bursts)),
        snr_median_db=float(np.median(snr)),
    )


def bursts_to_table(bursts: Sequence[Burst]) -> list[dict[str, float]]:
    """List of :meth:`Burst.to_dict` rows (e.g. for CSV/JSON export or a DataFrame)."""
    return [b.to_dict() for b in bursts]
