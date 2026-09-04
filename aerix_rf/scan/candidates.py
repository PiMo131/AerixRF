"""Rank "newly hot" regions of a swept band into lock candidates.

Input is the per-sweep matrix from :func:`aerix_rf.scan.sweep.parse_sweep_csv_multi`
(``[n_sweeps, n_bins]`` dB) plus, ideally, a :class:`~aerix_rf.scan.sweep.Baseline`
recorded with the test drones off (spec 1.3: ``current - baseline``).

Pipeline
--------
1. **Frames.** Single hackrf_sweep passes are ~6 dB noisy per bin, so consecutive
   sweeps are averaged (in linear power) into frames of ``frame_sweeps`` sweeps
   (auto: about :data:`TARGET_FRAMES` frames per pass). Frames are the time unit
   for persistence / burstiness / hopping. With ~100 sweeps/s a 2 s pass gives
   ~50 frames of ~40 ms -- fast enough to see burst structure, too slow to see
   millisecond-scale DJI intra-channel hopping (that just looks persistent).
2. **Differential.** ``delta = frame - reference`` where reference is the
   baseline resampled onto the live grid, or -- with no baseline -- the per-bin
   median across frames (self-baseline). Self-baseline only finds things that
   are hot in < 50 % of the frames; a signal that is on all the time becomes its
   own reference and disappears. Delta is smoothed along frequency
   (``smooth_bins``) before thresholding.
3. **Hot regions per frame.** Contiguous runs of ``delta > min_delta_db`` at least
   ``min_width_mhz`` wide.
4. **Clusters.** Regions are merged across frames when their centres are within
   ``cluster_mhz`` or their spans overlap by more than half of the narrower one.
5. **Hop groups.** Clusters that look like the same transmitter dwelling on
   different channels -- similar width, similar peak rise, rarely hot in the
   same frame, and at least two frame-to-frame hand-overs between them -- are
   merged into ONE candidate with ``hopping=True``, ``hop_channels_mhz`` listing
   the dwell channels and ``center_mhz`` at the most-used channel (the one to
   lock on first). ``lo/hi`` then span the whole hop set while ``width_mhz`` is
   the per-dwell width.
6. **Score** (0..1) -- weighted mean of four 0..1 factors, :data:`DEFAULT_WEIGHTS`::

       rise        = clip((delta_db - min_delta_db) / 20, 0, 1)   # +26 dB -> 1
       width       = interp(width_mhz, [0,1,5,20,40], [0,.2,1,1,.3])  # 5-20 MHz best
       persistence = fraction of frames in which the region was hot
       dynamics    = max(clip(burstiness_db / 6, 0, 1), hop_score)
       score       = 0.35*rise + 0.20*width + 0.20*persistence + 0.25*dynamics

   Rationale: drone control/video links are 5-20 MHz wide, bursty (duty-cycled
   telemetry, video GOP bursts) and often hop; a Wi-Fi AP on a fixed channel is
   persistent but not dynamic. Persistence alone therefore cannot lift a
   candidate to the top: a +20 dB, 20 MHz, always-on AP scores ~0.65, a +20 dB,
   10 MHz link on 40 % of the time with 8 dB burst std scores ~0.78 and a slow
   hopper ~0.9. Everything is exposed on the :class:`Candidate` so a CLI can
   re-sort by any single factor; ``weights`` can be overridden per call.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np
from scipy.ndimage import uniform_filter1d

from aerix_rf.scan.sweep import Baseline, average_db

__all__ = [
    "Candidate", "DEFAULT_WEIGHTS", "TARGET_FRAMES",
    "rank_candidates", "summarize", "to_dict",
]

#: default score weights (normalised at use, so they need not sum to 1)
DEFAULT_WEIGHTS: dict[str, float] = {
    "rise": 0.35, "width": 0.20, "persistence": 0.20, "dynamics": 0.25,
}
#: auto ``frame_sweeps`` targets roughly this many frames per pass
TARGET_FRAMES = 50
#: dB rise scale for the ``rise`` factor (min_delta_db + RISE_SCALE_DB -> 1.0)
RISE_SCALE_DB = 20.0
#: burst std (dB) that counts as "fully bursty"
BURST_SCALE_DB = 6.0


@dataclass
class Candidate:
    center_mhz: float          # for hoppers: the most-used dwell channel
    lo_mhz: float              # occupied span (hoppers: whole hop set)
    hi_mhz: float
    width_mhz: float           # typical occupied width per dwell
    delta_db: float            # max rise over reference
    mean_delta_db: float       # mean rise over the region while hot
    power_db: float            # absolute mean region power while hot (dB, hackrf_sweep scale)
    persistence: float         # fraction of frames in which the region was hot
    burstiness: float          # std across ALL frames of the region's power (dB)
    hopping: bool              # part of a multi-channel hop group
    hop_score: float           # 0..1: fraction of active frame pairs where the channel changed
    hop_channels_mhz: tuple[float, ...]   # dwell channels (single-channel: (center,))
    score: float               # 0..1 ranking score
    rank: int                  # 1 = best
    n_frames: int = 0          # frames the statistics were computed over

    def to_dict(self) -> dict:
        d = asdict(self)
        d["hop_channels_mhz"] = list(self.hop_channels_mhz)
        return d


def to_dict(obj: Candidate | Sequence[Candidate]) -> dict | list[dict]:
    """JSON-ready form of one Candidate or a list of them."""
    if isinstance(obj, Candidate):
        return obj.to_dict()
    return [c.to_dict() for c in obj]


# --------------------------------------------------------------------------- #
# internals
# --------------------------------------------------------------------------- #

def _to_frames(pm: np.ndarray, frame_sweeps: int) -> np.ndarray:
    """Average consecutive sweeps (linear) into frames; drops a short tail."""
    n = pm.shape[0]
    if frame_sweeps <= 1:
        return pm
    n_frames = n // frame_sweeps
    if n_frames == 0:
        return average_db(pm)[None, :]
    body = pm[: n_frames * frame_sweeps].reshape(n_frames, frame_sweeps, pm.shape[1])
    lin = np.power(10.0, body / 10.0)
    with np.errstate(divide="ignore"):
        return 10.0 * np.log10(np.nanmean(lin, axis=1))


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs of True runs."""
    if not mask.any():
        return []
    m = np.concatenate(([0], mask.astype(np.int8), [0]))
    d = np.diff(m)
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1) - 1
    return list(zip(starts.tolist(), ends.tolist()))


@dataclass
class _Region:
    frame: int
    i: int
    j: int
    center: float
    peak: float
    mean: float


class _Cluster:
    def __init__(self, r: _Region):
        self.regions: list[_Region] = [r]
        self.sum_center = r.center

    @property
    def center(self) -> float:
        return self.sum_center / len(self.regions)

    def add(self, r: _Region) -> None:
        self.regions.append(r)
        self.sum_center += r.center

    def finalize(self, freqs: np.ndarray, bin_mhz: float, frames: np.ndarray) -> None:
        # Extent: 10th/90th percentile of the per-frame edges. For a stable
        # region this is ~the typical edge; for a channel seen as several
        # fragments (sweep-timing artefact of hackrf_sweep) it is the union
        # without the occasional stray bin.
        self.i = int(np.floor(np.percentile([r.i for r in self.regions], 10)))
        self.j = int(np.ceil(np.percentile([r.j for r in self.regions], 90)))
        self.lo = float(freqs[self.i] - bin_mhz / 2)
        self.hi = float(freqs[self.j] + bin_mhz / 2)
        self.width = self.hi - self.lo
        self.centre = float(np.median([r.center for r in self.regions]))
        self.peak = float(max(r.peak for r in self.regions))
        self.mean_delta = float(np.mean([r.mean for r in self.regions]))
        self.frames: dict[int, float] = {}          # frame -> strongest peak in it
        for r in self.regions:
            self.frames[r.frame] = max(self.frames.get(r.frame, -np.inf), r.peak)
        lin = np.power(10.0, frames[:, self.i:self.j + 1] / 10.0)
        with np.errstate(divide="ignore"):
            self.power_series = 10.0 * np.log10(np.nanmean(lin, axis=1))   # per frame, all frames


def _cluster(regions: list[_Region], cluster_mhz: float, freqs: np.ndarray,
             bin_mhz: float, frames: np.ndarray) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    for r in sorted(regions, key=lambda r: r.center):
        if clusters and abs(r.center - clusters[-1].center) <= cluster_mhz:
            clusters[-1].add(r)
        else:
            clusters.append(_Cluster(r))
    for c in clusters:
        c.finalize(freqs, bin_mhz, frames)
    # Second pass: merge clusters whose spans overlap or touch (gap <= cluster_mhz).
    # A transmitter's hot region is contiguous; hackrf_sweep only illuminates
    # the FFT segment it is on during a short burst, so one 20 MHz Wi-Fi
    # channel is often seen as several touching fragments. Two different
    # transmitters with touching spans cannot be separated by a sweep anyway.
    merged: list[_Cluster] = []
    for c in clusters:
        if merged:
            p = merged[-1]
            gap = max(p.lo, c.lo) - min(p.hi, c.hi)      # negative = overlap
            if gap <= cluster_mhz:
                for r in c.regions:
                    p.add(r)
                p.finalize(freqs, bin_mhz, frames)
                continue
        merged.append(c)
    return merged


def _hop_groups(clusters: list[_Cluster]) -> list[list[int]]:
    """Connected components of clusters that hand over to each other frame-to-frame."""
    n = len(clusters)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(n):
        A = clusters[a]
        fa = set(A.frames)
        for b in range(a + 1, n):
            B = clusters[b]
            fb = set(B.frames)
            wr = A.width / B.width if B.width > 0 else math.inf
            if not (0.5 <= wr <= 2.0):
                continue
            if abs(A.peak - B.peak) > 10.0:
                continue
            smaller = min(len(fa), len(fb))
            if smaller == 0 or len(fa & fb) / smaller >= 0.3:
                continue
            handovers = sum(1 for f in fa if (f + 1) in fb and (f + 1) not in fa)
            handovers += sum(1 for f in fb if (f + 1) in fa and (f + 1) not in fb)
            if handovers < 2:
                continue
            parent[find(a)] = find(b)

    groups: dict[int, list[int]] = {}
    for a in range(n):
        groups.setdefault(find(a), []).append(a)
    return list(groups.values())


def _width_factor(width_mhz: float) -> float:
    return float(np.interp(width_mhz, [0.0, 1.0, 5.0, 20.0, 40.0], [0.0, 0.2, 1.0, 1.0, 0.3]))


def _score(delta_db: float, width_mhz: float, persistence: float, burstiness: float,
           hop_score: float, min_delta_db: float, weights: dict[str, float]) -> float:
    f = {
        "rise": float(np.clip((delta_db - min_delta_db) / RISE_SCALE_DB, 0.0, 1.0)),
        "width": _width_factor(width_mhz),
        "persistence": float(np.clip(persistence, 0.0, 1.0)),
        "dynamics": float(max(np.clip(burstiness / BURST_SCALE_DB, 0.0, 1.0), hop_score)),
    }
    total = sum(weights.get(k, 0.0) for k in f)
    if total <= 0:
        return 0.0
    return float(sum(weights.get(k, 0.0) * v for k, v in f.items()) / total)


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #

def rank_candidates(freqs: np.ndarray, power_matrix: np.ndarray,
                    baseline: Baseline | tuple[np.ndarray, np.ndarray] | None = None, *,
                    min_delta_db: float = 6.0, min_width_mhz: float = 1.0,
                    max_candidates: int = 8, frame_sweeps: int | None = None,
                    smooth_bins: int = 3, cluster_mhz: float = 2.0,
                    weights: dict[str, float] | None = None) -> list[Candidate]:
    """Rank newly-hot regions of ``power_matrix`` (``[n_sweeps, n_bins]`` dB).

    ``baseline`` is a :class:`Baseline` (or a ``(freqs_mhz, power_db)`` tuple)
    recorded with the drones off; ``None`` uses the per-bin median across frames
    (self-baseline, weaker -- see module docstring). Returns up to
    ``max_candidates`` candidates, best first, ``rank`` starting at 1; an empty
    list when nothing rises by ``min_delta_db`` over ``min_width_mhz``.
    """
    freqs = np.asarray(freqs, dtype=float)
    pm = np.atleast_2d(np.asarray(power_matrix, dtype=float))
    if pm.shape[0] == 0 or pm.shape[1] != freqs.size or freqs.size < 2:
        return []
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)
    bin_mhz = float(np.median(np.diff(freqs)))
    n_sweeps = pm.shape[0]
    if frame_sweeps is None:
        frame_sweeps = max(1, n_sweeps // TARGET_FRAMES)
    frames = _to_frames(pm, int(frame_sweeps))
    n_frames = frames.shape[0]

    if baseline is None:
        ref = np.nanmedian(frames, axis=0)
    elif isinstance(baseline, Baseline):
        ref = baseline.interp(freqs)
    else:
        bf, bp = baseline
        ref = np.interp(freqs, np.asarray(bf, dtype=float), np.asarray(bp, dtype=float))
    raw = np.nan_to_num(frames - ref[None, :], nan=-200.0)
    delta = raw
    if smooth_bins and smooth_bins > 1:
        delta = uniform_filter1d(raw, int(smooth_bins), axis=1, mode="nearest")

    min_bins = max(1, int(math.ceil(min_width_mhz / bin_mhz - 1e-9)))
    regions: list[_Region] = []
    for fi in range(n_frames):
        row = delta[fi]
        rrow = raw[fi]
        for i, j in _runs(row > min_delta_db):
            # smoothing widens a run by ~smooth_bins/2 per side; trim the
            # edges back to where the unsmoothed rise clears the threshold
            while i < j and rrow[i] <= min_delta_db:
                i += 1
            while j > i and rrow[j] <= min_delta_db:
                j -= 1
            if (j - i + 1) < min_bins:
                continue
            seg = row[i:j + 1]
            wl = np.power(10.0, seg / 10.0)
            centre = float(np.sum(freqs[i:j + 1] * wl) / np.sum(wl))
            regions.append(_Region(fi, i, j, centre, float(seg.max()), float(seg.mean())))
    if not regions:
        return []

    clusters = _cluster(regions, cluster_mhz, freqs, bin_mhz, frames)
    cands: list[Candidate] = []
    for group in _hop_groups(clusters):
        members = sorted((clusters[g] for g in group), key=lambda c: c.centre)
        hopping = len(members) > 1
        # active member per frame = strongest hot member in that frame
        active: dict[int, int] = {}
        for k, m in enumerate(members):
            for f, pk in m.frames.items():
                if f not in active or pk > members[active[f]].frames[f]:
                    active[f] = k
        hot_frames = sorted(active)
        persistence = len(hot_frames) / n_frames
        if hopping:
            pairs = [(f, f + 1) for f in hot_frames if (f + 1) in active]
            changes = sum(1 for a, b in pairs if active[a] != active[b])
            hop_score = changes / len(pairs) if pairs else 0.0
            best = max(members, key=lambda m: len(m.frames))
            centre = best.centre
            lo = min(m.lo for m in members)
            hi = max(m.hi for m in members)
            width = float(np.median([m.width for m in members]))
            series = np.max(np.vstack([m.power_series for m in members]), axis=0)
        else:
            hop_score = 0.0
            best = members[0]
            centre, lo, hi, width = best.centre, best.lo, best.hi, best.width
            series = best.power_series
        delta_db = max(m.peak for m in members)
        mean_delta = float(np.average([m.mean_delta for m in members],
                                      weights=[len(m.frames) for m in members]))
        power_hot = float(np.mean(series[hot_frames])) if hot_frames else float("nan")
        burst = float(np.std(series)) if series.size > 1 else 0.0
        score = _score(delta_db, width, persistence, burst, hop_score, min_delta_db, w)
        cands.append(Candidate(
            center_mhz=round(centre, 3), lo_mhz=round(lo, 3), hi_mhz=round(hi, 3),
            width_mhz=round(width, 3), delta_db=round(delta_db, 2),
            mean_delta_db=round(mean_delta, 2), power_db=round(power_hot, 2),
            persistence=round(persistence, 3), burstiness=round(burst, 2),
            hopping=hopping, hop_score=round(hop_score, 3),
            hop_channels_mhz=tuple(round(m.centre, 1) for m in members),
            score=round(score, 4), rank=0, n_frames=n_frames,
        ))

    cands.sort(key=lambda c: (-c.score, -c.delta_db))
    cands = cands[:max(0, int(max_candidates))]
    for k, c in enumerate(cands, start=1):
        c.rank = k
    return cands


def summarize(cands: Sequence[Candidate]) -> str:
    """Fixed-width table for the terminal."""
    if not cands:
        return "(no candidates: nothing rose above the reference)"
    hdr = (f"{'#':>2} {'centre':>8} {'span (MHz)':>17} {'width':>6} {'dMax':>6} "
           f"{'dMean':>6} {'pers':>5} {'burst':>5} {'hop':>5} {'score':>5}")
    lines = [hdr, "-" * len(hdr)]
    for c in cands:
        hop = f"{c.hop_score:.2f}" if c.hopping else "-"
        lines.append(
            f"{c.rank:>2} {c.center_mhz:>8.1f} {c.lo_mhz:>8.1f}-{c.hi_mhz:<8.1f} "
            f"{c.width_mhz:>6.1f} {c.delta_db:>+6.1f} {c.mean_delta_db:>+6.1f} "
            f"{c.persistence:>5.2f} {c.burstiness:>5.1f} {hop:>5} {c.score:>5.2f}"
        )
        if c.hopping:
            chans = ", ".join(f"{f:.1f}" for f in c.hop_channels_mhz)
            lines.append(f"   hops over: {chans}")
    lines.append("dMax/dMean = rise over reference (dB); pers = fraction of frames hot; "
                 "burst = std of region power (dB); hop = channel-change rate")
    return "\n".join(lines)
