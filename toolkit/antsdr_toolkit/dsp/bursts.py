"""Time-frequency burst detection on STFT power maps.

What the detector is
--------------------
:func:`detect_bursts` is a deliberately simple, explainable energy detector
working on a spectrogram ``power_db[frames, bins]`` as produced by
:func:`antsdr_toolkit.dsp.spectrum.stft_power_db`:

1. **Robust per-bin noise floor** (:func:`robust_noise_floor_db`).  For every
   frequency bin a low percentile (default 20th) of the power over all frames
   estimates that bin's noise level: short bursts cannot lift a low
   percentile, and persistent receiver artefacts (DC/LO spur, anti-alias
   roll-off) are absorbed into their own bin's floor.  The percentile is
   bias-corrected to the *mean* noise power (+6.5 dB for the 20th percentile
   of exponentially distributed cell powers) so ``threshold_db`` reads as
   "dB above the mean noise", i.e. an in-cell SNR.  Bins whose floor sits
   more than ``floor_ripple_db`` above the band-wide reference (a low
   percentile across bins) are treated as *persistently occupied* - e.g. a
   continuous analog-FPV carrier - and fall back to the reference floor so
   such carriers remain detectable.
2. **Fixed threshold**: ``mask = power_db > floor + threshold_db``.
3. **Morphological closing** (optional, :mod:`scipy.ndimage`) with a
   rectangular structuring element sized from ``close_time_s`` /
   ``close_freq_hz`` bridges small gaps, so a burst fragmented by fading,
   OFDM guard nulls or frame quantisation is reported once, not in pieces.
4. **Connected components** (8-connectivity) of the mask; each component's
   bounding box becomes a :class:`Burst` with peak/mean power and SNR.
   Components smaller than ``min_duration_s`` / ``min_bandwidth_hz`` are
   dropped - the main protection against isolated false-alarm cells.

Box convention: cell *edges*, i.e. ``t_start_s = frame_centre - hop/2`` and
``f_low_hz = bin_centre - bin_width/2`` (and symmetrically for the end/high
edges), so a single cell has duration ``hop / fs`` and bandwidth
``fs / fft_size``, never zero.

Threshold trade-off (sensitivity versus false alarms)
-----------------------------------------------------
Noise cell powers are exponentially distributed, so the per-cell false-alarm
probability ``threshold_db`` above the mean noise is
``exp(-10**(threshold_db / 10))``: 4.5e-5 at 10 dB, 2e-2 at 6 dB, but 0.2 at
2 dB.  A burst of in-band SNR ``s`` (linear) exceeds a threshold ``T``
(linear) with probability ``exp(-T / (1 + s))`` per cell: a 3 dB burst is
only 3.6 % "visible" at 10 dB - a few isolated cells that the size filters
discard, i.e. it is *missed* - but 59 % visible at 2 dB, above the
8-connected site-percolation density (~0.41) so its mask joins into one
ragged component.  Finding weak bursts therefore means lowering the
threshold, accepting that a fifth of all noise cells light up, and relying on
``min_duration_s`` / ``min_bandwidth_hz`` (set *looser* than the true
extent, because weak bursts fragment and shrink) plus closing to reject the
clutter.  Boxes of weak bursts are also inflated by noise cells that happen
to touch them.

Known weaknesses (the research phase may replace this detector)
---------------------------------------------------------------
* No CFAR adaptivity across time: one floor per bin for the whole map.  A
  floor that drifts (AGC steps, gain changes between sweep dwells) or a
  signal present in more than ``100 - floor_percentile`` percent of the
  frames biases the floor; the band-wide clamp rescues only carriers that
  occupy less than ``100 - band_percentile`` percent of the bins.
* Sensitive to ``fft_size``: for wideband signals the cell SNR falls with
  narrower bins (less signal energy per bin, same noise per bin), for tones
  it rises with longer frames, so one threshold behaves differently at
  different resolutions; edges are quantised to one cell either way.
* Bounding boxes, not shapes: chirps, overlapping emitters and hops within
  one frame are boxed together when their masks touch.
* No signal modelling: window sidelobes and PA ramp splatter of a strong
  burst pass the threshold and widen its box.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

import numpy as np
from scipy import ndimage

from .spectrum import db, estimate_noise_floor_db, stft_power_db

__all__ = [
    "Burst",
    "closing_structure",
    "detect_bursts",
    "detect_bursts_from_iq",
    "match_bursts",
    "robust_noise_floor_db",
    "time_freq_iou",
]

_EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)


@dataclass(frozen=True)
class Burst:
    """A detected time-frequency box; times in s, frequencies in absolute Hz, powers in dB."""

    t_start_s: float
    t_end_s: float
    f_low_hz: float
    f_high_hz: float
    peak_db: float
    mean_db: float
    snr_db: float

    @property
    def duration_s(self) -> float:
        return self.t_end_s - self.t_start_s

    @property
    def bandwidth_hz(self) -> float:
        return self.f_high_hz - self.f_low_hz

    @property
    def center_freq_hz(self) -> float:
        return 0.5 * (self.f_low_hz + self.f_high_hz)

    def to_dict(self) -> dict[str, float]:
        """Plain dict of the fields plus the derived duration, bandwidth and centre."""
        out = asdict(self)
        out["duration_s"] = self.duration_s
        out["bandwidth_hz"] = self.bandwidth_hz
        out["center_freq_hz"] = self.center_freq_hz
        return out


def robust_noise_floor_db(
    power_db: np.ndarray,
    *,
    percentile: float = 20.0,
    smooth_bins: int = 0,
    band_percentile: float = 10.0,
    ripple_db: float | None = 6.0,
) -> np.ndarray:
    """Per-bin *mean* noise power (dB) of a ``(frames, bins)`` map, shape ``(bins,)``.

    Wraps :func:`~antsdr_toolkit.dsp.spectrum.estimate_noise_floor_db` with
    ``bias_correct=True`` (percentile -> mean noise) and then clamps
    persistently occupied bins: where the per-bin floor exceeds the
    band-wide reference (the ``band_percentile``-th percentile across bins)
    by more than ``ripple_db`` the reference is used instead, because such
    a bin is far more likely to hold a continuous signal than a receiver
    floor that is 6 dB higher than its neighbours.  ``ripple_db=None``
    disables the clamp (pure per-bin semantics).  Bins with a *lower* floor
    (e.g. under the anti-alias roll-off) always keep their own estimate.
    """
    p = np.asarray(power_db)
    if p.ndim != 2:
        raise ValueError(f"power_db must be 2-D (frames, bins), got shape {p.shape}")
    floor = estimate_noise_floor_db(
        p, axis=0, percentile=percentile, smooth_bins=smooth_bins, bias_correct=True
    )
    if ripple_db is not None and floor.size:
        ref = np.percentile(floor, float(band_percentile))
        floor = np.where(floor > ref + float(ripple_db), floor.dtype.type(ref), floor)
    return floor


def closing_structure(
    close_time_s: float, close_freq_hz: float, time_step_s: float, freq_step_hz: float
) -> np.ndarray | None:
    """Odd-sized rectangular structuring element that bridges gaps up to the given widths.

    A closing with an element of ``2n + 1`` cells bridges gaps of at most
    ``2n`` cells, so ``n = ceil(close / (2 * step))`` guarantees that any gap
    no wider than ``close_time_s`` (frames axis) or ``close_freq_hz`` (bins
    axis) is filled.  Returns ``None`` when no closing is requested.
    """

    def half(close: float, step: float) -> int:
        if close <= 0.0 or step <= 0.0:
            return 0
        return math.ceil(close / (2.0 * step) - 1e-9)

    n_t, n_f = half(float(close_time_s), float(time_step_s)), half(
        float(close_freq_hz), float(freq_step_hz)
    )
    if n_t == 0 and n_f == 0:
        return None
    return np.ones((2 * n_t + 1, 2 * n_f + 1), dtype=bool)


def _close_mask(mask: np.ndarray, structure: np.ndarray) -> np.ndarray:
    """Binary closing without border artefacts (pad with False, close, crop)."""
    pt, pf = structure.shape[0] // 2, structure.shape[1] // 2
    padded = np.pad(mask, ((pt, pt), (pf, pf)), mode="constant", constant_values=False)
    closed = ndimage.binary_closing(padded, structure=structure)
    return closed[pt : pt + mask.shape[0], pf : pf + mask.shape[1]]


def _axis_step(axis: np.ndarray) -> float:
    """Median spacing of a 1-D axis; 0.0 for a single element."""
    return float(np.median(np.diff(axis))) if axis.size > 1 else 0.0


def _component_peaks(
    p: np.ndarray, labels: np.ndarray, wanted: np.ndarray
) -> list[tuple[int, int]]:
    """``(frame, bin)`` of the maximum cell of each label in ``wanted`` (same order).

    Only the cells of the wanted components are gathered and sorted, which is
    far cheaper than :func:`scipy.ndimage.maximum_position` (that sorts the
    whole map) when most components were discarded by the size filters.
    """
    keep_lut = np.zeros(int(labels.max()) + 1, dtype=bool)
    keep_lut[wanted] = True
    cell = np.flatnonzero(keep_lut[labels])
    cell_lab = labels.ravel()[cell]
    order = np.lexsort((p.ravel()[cell], cell_lab))  # by label, then ascending value
    lab_sorted = cell_lab[order]
    last = np.flatnonzero(np.diff(lab_sorted, append=-1) != 0)  # last (= max) cell per label
    peak_of_label = dict(zip(lab_sorted[last].tolist(), cell[order][last].tolist()))
    n_bins = p.shape[1]
    return [divmod(peak_of_label[int(lab)], n_bins) for lab in wanted]


def detect_bursts(
    power_db: np.ndarray,
    freqs_hz: np.ndarray,
    times_s: np.ndarray,
    *,
    threshold_db: float = 10.0,
    noise_floor_db: np.ndarray | float | None = None,
    min_duration_s: float = 0.0,
    min_bandwidth_hz: float = 0.0,
    close_time_s: float = 0.0,
    close_freq_hz: float = 0.0,
    floor_percentile: float = 20.0,
    floor_ripple_db: float | None = 6.0,
    floor_smooth_bins: int = 0,
) -> list[Burst]:
    """Detect energy bursts in an STFT power map; see the module docstring.

    Parameters
    ----------
    power_db, freqs_hz, times_s
        Output of :func:`~antsdr_toolkit.dsp.spectrum.stft_power_db`:
        ``(frames, bins)`` dB map, ascending absolute bin centres (Hz) and
        frame centres (s).
    threshold_db
        Detection threshold in dB above the noise floor (mean noise power).
    noise_floor_db
        Explicit floor: scalar, ``(bins,)`` or ``(frames, bins)``, in dB of
        *mean* noise power.  ``None`` estimates it with
        :func:`robust_noise_floor_db` using ``floor_percentile``,
        ``floor_ripple_db`` and ``floor_smooth_bins``.
    min_duration_s, min_bandwidth_hz
        Components with a smaller bounding box (cell-edge convention) are
        dropped.  One cell is ``hop / fs`` long and ``fs / fft_size`` wide.
    close_time_s, close_freq_hz
        Gaps up to this size are bridged by a binary closing before
        labelling (see :func:`closing_structure`).

    Returns bursts sorted by start time, then by lower frequency.
    ``snr_db`` is the peak cell minus the floor at the peak bin (the peak of
    many exponential cells is biased a few dB above the mean SNR);
    ``mean_db`` is the mean linear power over the whole bounding box.
    """
    p = np.asarray(power_db)
    freqs = np.asarray(freqs_hz, dtype=np.float64).ravel()
    times = np.asarray(times_s, dtype=np.float64).ravel()
    if p.ndim != 2:
        raise ValueError(f"power_db must be 2-D (frames, bins), got shape {p.shape}")
    if p.shape != (times.size, freqs.size):
        raise ValueError(
            f"power_db shape {p.shape} does not match (len(times_s), len(freqs_hz)) = "
            f"({times.size}, {freqs.size})"
        )
    if not np.issubdtype(p.dtype, np.floating):
        p = p.astype(np.float32)
    if p.size == 0:
        return []

    if noise_floor_db is None:
        floor = robust_noise_floor_db(
            p,
            percentile=floor_percentile,
            smooth_bins=floor_smooth_bins,
            ripple_db=floor_ripple_db,
        )
    else:
        floor = np.asarray(noise_floor_db, dtype=p.dtype)
        if floor.ndim not in (0, 1, 2):
            raise ValueError("noise_floor_db must be a scalar, (bins,) or (frames, bins)")
    floor_map = np.broadcast_to(floor, p.shape)  # scalar, (bins,) or (frames, bins)

    dt, df = _axis_step(times), _axis_step(freqs)
    mask = p > floor_map + p.dtype.type(threshold_db)
    structure = closing_structure(close_time_s, close_freq_hz, dt, df)
    if structure is not None:
        mask = _close_mask(mask, structure)

    labels, n_labels = ndimage.label(mask, structure=_EIGHT_CONNECTED)
    if n_labels == 0:
        return []
    slices = ndimage.find_objects(labels)
    t_lo = np.array([s[0].start for s in slices])
    t_hi = np.array([s[0].stop for s in slices])
    f_lo = np.array([s[1].start for s in slices])
    f_hi = np.array([s[1].stop for s in slices])
    t_start = times[t_lo] - dt / 2.0
    t_end = times[t_hi - 1] + dt / 2.0
    f_low = freqs[f_lo] - df / 2.0
    f_high = freqs[f_hi - 1] + df / 2.0
    # tiny tolerance so "min size = k cells" accepts exactly k cells despite rounding
    long_enough = t_end - t_start >= float(min_duration_s) * (1.0 - 1e-9)
    wide_enough = f_high - f_low >= float(min_bandwidth_hz) * (1.0 - 1e-9)
    idx = np.flatnonzero(long_enough & wide_enough)
    if idx.size == 0:
        return []

    peaks = _component_peaks(p, labels, idx + 1)
    bursts: list[Burst] = []
    for k, (pt, pf) in zip(idx, peaks):
        box = p[t_lo[k] : t_hi[k], f_lo[k] : f_hi[k]].astype(np.float64)
        mean_db = float(db(np.mean(10.0 ** (box / 10.0))))
        peak_db = float(p[pt, pf])
        bursts.append(
            Burst(
                t_start_s=float(t_start[k]),
                t_end_s=float(t_end[k]),
                f_low_hz=float(f_low[k]),
                f_high_hz=float(f_high[k]),
                peak_db=peak_db,
                mean_db=mean_db,
                snr_db=peak_db - float(floor_map[pt, pf]),
            )
        )
    bursts.sort(key=lambda b: (b.t_start_s, b.f_low_hz))
    return bursts


def detect_bursts_from_iq(
    x: np.ndarray,
    sample_rate_hz: float,
    center_freq_hz: float,
    *,
    fft_size: int = 1024,
    hop: int | None = None,
    window: str | tuple | np.ndarray = "hann",
    **kwargs,
) -> list[Burst]:
    """Convenience: :func:`~antsdr_toolkit.dsp.spectrum.stft_power_db` then :func:`detect_bursts`.

    ``kwargs`` are passed to :func:`detect_bursts` (``threshold_db``,
    ``min_duration_s`` ...).
    """
    power_db, freqs_hz, times_s = stft_power_db(
        x, sample_rate_hz, center_freq_hz, fft_size=fft_size, hop=hop, window=window
    )
    return detect_bursts(power_db, freqs_hz, times_s, **kwargs)


def _box(b: Burst | Mapping[str, float]) -> tuple[float, ...]:
    if isinstance(b, Burst):
        return b.t_start_s, b.t_end_s, b.f_low_hz, b.f_high_hz
    return tuple(float(b[k]) for k in ("t_start_s", "t_end_s", "f_low_hz", "f_high_hz"))


def time_freq_iou(a: Burst | Mapping[str, float], b: Burst | Mapping[str, float]) -> float:
    """Intersection-over-union of two time-frequency boxes (:class:`Burst` or truth dicts).

    Useful for scoring detections against :meth:`Scene.truth_bursts`
    (keys ``t_start_s, t_end_s, f_low_hz, f_high_hz``).  Degenerate boxes
    (zero area) give 0.0.
    """
    t0a, t1a, f0a, f1a = _box(a)
    t0b, t1b, f0b, f1b = _box(b)
    inter = max(0.0, min(t1a, t1b) - max(t0a, t0b)) * max(0.0, min(f1a, f1b) - max(f0a, f0b))
    union = (t1a - t0a) * (f1a - f0a) + (t1b - t0b) * (f1b - f0b) - inter
    return inter / union if union > 0.0 else 0.0


def match_bursts(
    detected: Sequence[Burst],
    truth: Sequence[Burst | Mapping[str, float]],
    *,
    min_iou: float = 0.5,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Greedy one-to-one matching by IoU; returns ``(pairs, unmatched_detected, unmatched_truth)``.

    ``pairs`` holds ``(detected_index, truth_index)`` tuples, best IoU
    first.  Intended for precision/recall bookkeeping in tests and the
    research phase, not for real-time use.
    """
    if not detected or not truth:
        return [], list(range(len(detected))), list(range(len(truth)))
    iou = np.array([[time_freq_iou(d, t) for t in truth] for d in detected])
    pairs: list[tuple[int, int]] = []
    free_d, free_t = set(range(len(detected))), set(range(len(truth)))
    for flat in np.argsort(iou, axis=None)[::-1]:
        i, j = divmod(int(flat), len(truth))
        if iou[i, j] < min_iou:
            break
        if i in free_d and j in free_t:
            pairs.append((i, j))
            free_d.discard(i)
            free_t.discard(j)
    return pairs, sorted(free_d), sorted(free_t)
