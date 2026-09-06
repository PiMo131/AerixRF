"""Stepped-frequency sweep: tune, settle, capture, analyse, rank, aggregate.

What a sweep does
-----------------
The E200 streams at most ~20 MSPS to the host, so a band wider than the
usable span of one tuning (see :mod:`antsdr_toolkit.scan.planner`) must be
visited one :class:`~.planner.Dwell` at a time.  :class:`Sweeper` walks a
plan and, per dwell:

1. **retune, settle, discard** - after ``source.retune`` the AD9361 PLL and
   the libiio buffer pipeline still hold stale samples; fpv-sdr sleeps
   0.08 s and RF-Vision-UAV-Tracker sleeps 40-50 ms *and* throws away 1-2
   buffers after every retune.  ``settle_s`` / ``discard_buffers`` reproduce
   both.  Sources that cannot retune (SigMF replay, synthetic scenes) are
   treated as a single dwell at their own centre and skip this step.
2. **capture** ``dwell_s`` of IQ (fpv-sdr scanner default 0.06 s; the
   RF-Vision-UAV-Tracker uses 13 ms for its fast ranking scan and 65 ms for
   the follow-up dwell).
3. **analyse** (:func:`analyse_dwell`):

   * Welch PSD over the usable span (``fft_size`` bins, "spectrum" scaling:
     a full-scale tone reads ~0 dB) and a robust noise floor = 20th
     percentile of the bins outside a small DC notch (the AD9361 LO leak
     sits in the centre bins; fpv-sdr skips ``|k - N/2| <= 2``).
   * **occupancy**: contiguous runs of bins more than
     ``occupancy_threshold_db`` above the floor (gaps up to ``max_gap_hz``
     bridged, runs shorter than ``min_occupied_bins`` dropped) become
     :class:`OccupiedSegment` ``(f_low_hz, f_high_hz, peak_db, snr_db)``.
     Because the PSD is averaged over hundreds of segments its per-bin
     noise variance is tiny (~0.2 dB for 60 ms at 20 MSPS), so the 6 dB
     default threshold is about ignoring receiver artefacts and weak
     emitters, not about false alarms on white noise; raise it towards
     fpv-sdr's 12 dB on hardware with spurs or filter ripple.
   * **kurtosis** ``kappa = E|x|^4 / (E|x|^2)^2`` of the de-meaned samples,
     capped at 20: 2.0 for circular complex Gaussian noise (RF-Vision-UAV-
     Tracker uses 3.0, the real-valued figure - wrong for complex baseband),
     1.0 for a constant-envelope carrier, roughly ``2 / duty`` for a burst
     train, so it flags bursty dwells that a mean-power RSSI scan misses.
   * **bursts** via :func:`~antsdr_toolkit.dsp.bursts.detect_bursts_from_iq`
     (STFT energy detector) and their :class:`~antsdr_toolkit.dsp.features.BurstFeatures`.

4. **rank** the results by :func:`activity_score` - the dwell's mean power
   above its floor plus half the strongest segment's SNR, multiplied by the
   RF-Vision-UAV-Tracker kurtosis bonus ``1 + 0.4 * max(0, kappa - 2) / 2``
   - and optionally **revisit** the top ``revisit_top`` dwells with a longer
   ``revisit_dwell_s`` (the tracker's "fast scan all sectors, then dwell on
   the best one" pattern).

:class:`OccupancyMap` accumulates repeated runs into a per-bin max-hold and
occupancy fraction (share of runs in which a bin exceeded its run's floor by
the threshold), keyed by dwell centre, and serialises to JSON.

Sources (algorithms re-implemented from the research digest; no code
copied): https://github.com/lukeswitz/fpv-sdr (settle 0.08 s, dwell 0.06 s,
usable 0.8, 4096-bin PSD, 20th-percentile floor, DC-bin skip; GPL-headed
Python), https://github.com/ALPssdz/RF-Vision-UAV-Tracker (discard 1-2
buffers after retune, kurtosis sector ranking with beta 0.40 and cap 20,
fast-scan-then-dwell pattern; MIT).  Verified constants: all the timing and
threshold numbers above; inferred: the 6 dB occupancy threshold, the
activity-score weighting and the 100 kHz gap-bridging default.

Units: Hz, seconds, dB relative to full scale 1.0; IQ ``complex64``;
frequency axes absolute Hz ascending.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np
from scipy import ndimage

from ..device.base import SampleSource, StreamInfo
from ..dsp.bursts import Burst, detect_bursts_from_iq
from ..dsp.features import BurstFeatures, burst_features
from ..dsp.spectrum import welch_psd_db
from .planner import DEFAULT_USABLE_FRACTION, Dwell, usable_span_hz

__all__ = [
    "KAPPA_GAUSSIAN",
    "KURTOSIS_BETA",
    "KURTOSIS_CAP",
    "DwellResult",
    "OccupancyMap",
    "OccupiedSegment",
    "Sweeper",
    "activity_score",
    "analyse_dwell",
    "is_fixed_tuning",
    "kurtosis",
    "occupancy_from_psd",
]

log = logging.getLogger(__name__)

KAPPA_GAUSSIAN = 2.0
"""``E|x|^4 / (E|x|^2)^2`` of circularly symmetric complex Gaussian noise."""
KURTOSIS_CAP = 20.0
"""Upper clamp on the reported kurtosis (RF-Vision-UAV-Tracker KURTOSIS_CAP)."""
KURTOSIS_BETA = 0.40
"""Weight of the kurtosis excess in :func:`activity_score` (tracker KURTOSIS_BETA)."""
DEFAULT_OCCUPANCY_THRESHOLD_DB = 6.0
_LIN_FLOOR = 1e-20
OCCUPANCY_MAP_SCHEMA = "antsdr-toolkit/occupancy-map/0.1"


# --------------------------------------------------------------------------- primitives
class OccupiedSegment(NamedTuple):
    """A contiguous run of PSD bins above the occupancy threshold.

    Frequencies are absolute Hz (bin edges), ``peak_db`` the strongest bin
    and ``snr_db`` that peak minus the dwell's noise floor.  Being a tuple it
    unpacks as ``f_low, f_high, peak_db, snr_db``.
    """

    f_low_hz: float
    f_high_hz: float
    peak_db: float
    snr_db: float

    @property
    def bandwidth_hz(self) -> float:
        return self.f_high_hz - self.f_low_hz

    @property
    def center_freq_hz(self) -> float:
        return 0.5 * (self.f_low_hz + self.f_high_hz)

    def to_dict(self) -> dict[str, float]:
        out = dict(self._asdict())
        out["bandwidth_hz"] = self.bandwidth_hz
        out["center_freq_hz"] = self.center_freq_hz
        return out


def kurtosis(x: np.ndarray, *, cap: float = KURTOSIS_CAP) -> float:
    """``E|x|^4 / (E|x|^2)^2`` of the de-meaned IQ, clamped to ``cap``.

    Multi-channel ``(channels, n)`` input is averaged over channels.  Returns
    ``cap`` for an all-zero input (undefined ratio) so silence never ranks
    as noise.  Reference values: 2.0 complex Gaussian, 1.0 constant envelope,
    ~``2 / duty`` for a strong gated burst train.
    """
    xc = np.asarray(x)
    if xc.ndim == 1:
        xc = xc[np.newaxis, :]
    if xc.ndim != 2 or xc.shape[-1] == 0:
        raise ValueError("kurtosis needs (n,) or (channels, n) samples with n > 0")
    values = []
    for ch in xc:
        z = ch.astype(np.complex128)
        z -= z.mean()
        p2 = z.real * z.real + z.imag * z.imag
        m2 = float(p2.mean())
        if m2 <= 0.0:
            values.append(float(cap))
            continue
        m4 = float((p2 * p2).mean())
        values.append(min(m4 / (m2 * m2), float(cap)))
    return float(np.mean(values))


def _close_runs(mask: np.ndarray, gap_bins: int) -> np.ndarray:
    """Bridge gaps of at most ``gap_bins`` in a 1-D boolean mask (padded closing)."""
    half = math.ceil(gap_bins / 2.0)
    if half <= 0 or mask.size == 0:
        return mask
    padded = np.pad(mask, half, mode="constant", constant_values=False)
    closed = ndimage.binary_closing(padded, structure=np.ones(2 * half + 1, dtype=bool))
    return closed[half : half + mask.size]


def occupancy_from_psd(
    freqs_hz: np.ndarray,
    psd_db: np.ndarray,
    *,
    threshold_db: float = DEFAULT_OCCUPANCY_THRESHOLD_DB,
    floor_percentile: float = 20.0,
    center_freq_hz: float | None = None,
    dc_notch_bins: int = 5,
    max_gap_hz: float = 100e3,
    min_bins: int = 3,
) -> tuple[float, list[OccupiedSegment], np.ndarray]:
    """Noise floor, occupied segments and the per-bin mask of one PSD.

    ``center_freq_hz`` locates the DC bin; the ``dc_notch_bins`` bins around
    it are excluded from the floor estimate and from the mask (LO leakage).
    Gaps narrower than ``max_gap_hz`` - never less than the notch itself,
    so a wide signal straddling DC stays one segment - are bridged before
    runs shorter than ``min_bins`` are discarded.

    Returns ``(noise_floor_db, segments, mask)`` where ``mask`` is the
    boolean per-bin union of the returned segments (``False`` in the notch
    unless a signal bridges it, ``False`` for runs shorter than ``min_bins``).
    """
    f = np.asarray(freqs_hz, dtype=np.float64).ravel()
    p = np.asarray(psd_db, dtype=np.float64).ravel()
    if f.shape != p.shape:
        raise ValueError("freqs_hz and psd_db must have the same length")
    n = p.size
    if n == 0:
        return math.nan, [], np.zeros(0, dtype=bool)
    valid = np.ones(n, dtype=bool)
    notch = np.zeros(n, dtype=bool)
    if center_freq_hz is not None and dc_notch_bins > 0:
        k0 = int(np.argmin(np.abs(f - float(center_freq_hz))))
        half = int(dc_notch_bins) // 2
        notch[max(k0 - half, 0) : k0 + half + 1] = True
        valid &= ~notch
    if not valid.any():
        valid[:] = True
        notch[:] = False
    floor = float(np.percentile(p[valid], float(floor_percentile)))
    mask = valid & (p > floor + float(threshold_db))
    df = float(np.median(np.diff(f))) if n > 1 else 0.0
    gap_bins = math.ceil(float(max_gap_hz) / df) if df > 0.0 else 0
    mask = _close_runs(mask, gap_bins)
    # A signal wide enough to straddle the LO leak keeps its notched bins, so
    # it stays one segment; the notch width is deliberately NOT a global
    # minimum gap, which would also bridge unrelated nulls (an OFDM guard,
    # a hop boundary) elsewhere in the spectrum.
    if notch.any():
        bridged = _close_runs(mask | notch, 0) & notch
        edges = np.flatnonzero(notch)
        lo, hi = int(edges[0]), int(edges[-1])
        occupied_both_sides = bool(mask[max(lo - 1, 0)]) and bool(mask[min(hi + 1, n - 1)])
        if occupied_both_sides:
            mask |= bridged

    edges = np.diff(mask.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    segments: list[OccupiedSegment] = []
    for s, e in zip(starts, stops):
        if e - s < int(min_bins):
            mask[s:e] = False
            continue
        run = p[s:e]
        peak = float(run.max())
        segments.append(
            OccupiedSegment(float(f[s] - df / 2.0), float(f[e - 1] + df / 2.0), peak, peak - floor)
        )
    return floor, segments, mask


def activity_score(
    mean_excess_db: float,
    peak_snr_db: float,
    kappa: float,
    *,
    beta: float = KURTOSIS_BETA,
    kappa_ref: float = KAPPA_GAUSSIAN,
) -> float:
    """Rank a dwell: power above the floor with a burstiness bonus (heuristic).

    ``(max(mean_excess_db, 0) + 0.5 * max(peak_snr_db, 0)) * (1 + beta *
    max(0, kappa - kappa_ref) / kappa_ref)``.  The first factor is the
    RSSI-style term of the RF-Vision-UAV-Tracker stage 1 made gain-
    independent (power relative to the dwell's own floor, plus the strongest
    occupied segment so one short strong burst outranks a weak broad rise);
    the second is its kurtosis weighting with the complex-Gaussian reference.
    Noise-only dwells score ~0.
    """
    excess = max(float(mean_excess_db), 0.0)
    peak = max(float(peak_snr_db), 0.0)
    bonus = 1.0 + float(beta) * max(0.0, float(kappa) - float(kappa_ref)) / float(kappa_ref)
    return (excess + 0.5 * peak) * bonus


# --------------------------------------------------------------------------- results
@dataclass(eq=False)
class DwellResult:
    """Analysis of one dwell (see the module docstring for how each field is made).

    ``freqs_hz`` / ``psd_db`` cover only the usable span (``span_hz`` around
    ``center_freq_hz``), ascending absolute Hz.  ``occupancy`` lists the
    segments above the threshold, ``occupied_fraction`` the share of usable
    bins in them, ``mean_excess_db`` the mean linear PSD over the usable
    bins relative to the noise floor.  ``t_wall_s`` is the wall-clock time
    (``time.time()`` style) at which the capture started; burst times are
    seconds from that start.
    """

    center_freq_hz: float
    span_hz: float
    sample_rate_hz: float
    n_samples: int
    t_wall_s: float
    freqs_hz: np.ndarray
    psd_db: np.ndarray
    noise_floor_db: float
    occupancy: list[OccupiedSegment]
    occupied_fraction: float
    mean_excess_db: float
    kurtosis: float
    bursts: list[Burst]
    features: BurstFeatures
    targets: tuple[float, ...] = ()

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sample_rate_hz

    @property
    def f_low_hz(self) -> float:
        return self.center_freq_hz - self.span_hz / 2.0

    @property
    def f_high_hz(self) -> float:
        return self.center_freq_hz + self.span_hz / 2.0

    @property
    def peak_snr_db(self) -> float:
        """SNR of the strongest occupied segment; 0.0 when nothing is occupied."""
        return max((s.snr_db for s in self.occupancy), default=0.0)

    @property
    def activity_score(self) -> float:
        return activity_score(self.mean_excess_db, self.peak_snr_db, self.kurtosis)

    def to_dict(self, *, include_psd: bool = False) -> dict[str, Any]:
        """JSON-serialisable summary; ``include_psd`` adds the frequency axis and PSD."""
        out: dict[str, Any] = {
            "center_freq_hz": self.center_freq_hz,
            "span_hz": self.span_hz,
            "f_low_hz": self.f_low_hz,
            "f_high_hz": self.f_high_hz,
            "sample_rate_hz": self.sample_rate_hz,
            "n_samples": int(self.n_samples),
            "duration_s": self.duration_s,
            "t_wall_s": self.t_wall_s,
            "noise_floor_db": self.noise_floor_db,
            "occupied_fraction": self.occupied_fraction,
            "mean_excess_db": self.mean_excess_db,
            "peak_snr_db": self.peak_snr_db,
            "kurtosis": self.kurtosis,
            "activity_score": self.activity_score,
            "n_bursts": len(self.bursts),
            "targets": list(self.targets),
            "occupancy": [s.to_dict() for s in self.occupancy],
            "bursts": [b.to_dict() for b in self.bursts],
            "features": self.features.to_dict(),
        }
        if include_psd:
            out["freqs_hz"] = [float(v) for v in self.freqs_hz]
            out["psd_db"] = [float(v) for v in self.psd_db]
        return out


def analyse_dwell(
    x: np.ndarray,
    sample_rate_hz: float,
    center_freq_hz: float,
    span_hz: float | None = None,
    *,
    t_wall_s: float = 0.0,
    targets: Sequence[float] = (),
    fft_size: int = 4096,
    occupancy_threshold_db: float = DEFAULT_OCCUPANCY_THRESHOLD_DB,
    floor_percentile: float = 20.0,
    dc_notch_bins: int = 5,
    max_gap_hz: float = 100e3,
    min_occupied_bins: int = 3,
    burst_fft_size: int = 1024,
    burst_threshold_db: float = 10.0,
    burst_min_frames: int = 3,
    burst_min_bins: int = 3,
    burst_close_frames: int = 1,
    burst_close_bins: int = 2,
    burst_kwargs: dict[str, Any] | None = None,
    center_tolerance_hz: float = 250e3,
) -> DwellResult:
    """Analyse one captured dwell (``(n,)`` or ``(channels, n)`` complex IQ).

    ``span_hz`` defaults to the whole sample rate.  Burst-detector sizes are
    given in STFT cells (frames of ``burst_fft_size // 2`` hop, bins of
    ``fs / burst_fft_size``): the minimum box is ``burst_min_frames`` x
    ``burst_min_bins`` and gaps up to ``burst_close_frames`` /
    ``burst_close_bins`` are closed; ``burst_kwargs`` are passed through to
    :func:`~antsdr_toolkit.dsp.bursts.detect_bursts` and override these.
    """
    fs = float(sample_rate_hz)
    fc = float(center_freq_hz)
    xc = np.asarray(x)
    if xc.ndim not in (1, 2) or xc.shape[-1] == 0:
        raise ValueError("x must be non-empty (n,) or (channels, n) IQ")
    if not np.iscomplexobj(xc):
        xc = xc.astype(np.complex64)
    n = int(xc.shape[-1])
    span = fs if span_hz is None else float(span_hz)
    if not 0.0 < span <= fs * (1.0 + 1e-9):
        raise ValueError(f"span_hz must lie in (0, sample_rate_hz], got {span}")

    freqs, psd = welch_psd_db(xc, fs, fc, nfft=int(fft_size))
    keep = np.abs(freqs - fc) <= span / 2.0 + 1e-6
    freqs, psd = freqs[keep], psd[keep]
    floor, segments, mask = occupancy_from_psd(
        freqs, psd, threshold_db=occupancy_threshold_db, floor_percentile=floor_percentile,
        center_freq_hz=fc, dc_notch_bins=dc_notch_bins, max_gap_hz=max_gap_hz,
        min_bins=min_occupied_bins,
    )
    lin = 10.0 ** (psd.astype(np.float64) / 10.0)
    floor_lin = 10.0 ** (floor / 10.0) if math.isfinite(floor) else _LIN_FLOOR
    mean_excess = 10.0 * math.log10(max(float(lin.mean()) / max(floor_lin, _LIN_FLOOR), _LIN_FLOOR))
    occupied_fraction = float(mask.mean()) if mask.size else 0.0

    hop = max(int(burst_fft_size) // 2, 1)
    dt, df = hop / fs, fs / int(burst_fft_size)
    kwargs: dict[str, Any] = {
        "threshold_db": float(burst_threshold_db),
        "min_duration_s": int(burst_min_frames) * dt,
        "min_bandwidth_hz": int(burst_min_bins) * df,
        "close_time_s": int(burst_close_frames) * dt,
        "close_freq_hz": int(burst_close_bins) * df,
    }
    if burst_kwargs:
        kwargs.update(burst_kwargs)
    bursts = detect_bursts_from_iq(xc, fs, fc, fft_size=int(burst_fft_size), hop=hop, **kwargs)
    feats = burst_features(bursts, window_s=n / fs, center_tolerance_hz=center_tolerance_hz)

    return DwellResult(
        center_freq_hz=fc,
        span_hz=span,
        sample_rate_hz=fs,
        n_samples=n,
        t_wall_s=float(t_wall_s),
        freqs_hz=freqs,
        psd_db=psd,
        noise_floor_db=floor,
        occupancy=segments,
        occupied_fraction=occupied_fraction,
        mean_excess_db=mean_excess,
        kurtosis=kurtosis(xc),
        bursts=bursts,
        features=feats,
        targets=tuple(float(t) for t in targets),
    )


# --------------------------------------------------------------------------- sweeper
def is_fixed_tuning(source: SampleSource) -> bool:
    """``True`` when ``source`` inherits the base ``retune`` (cannot move its LO)."""
    return getattr(type(source), "retune", None) is SampleSource.retune


def _rank_key(result: DwellResult) -> tuple[float, float]:
    return (-result.activity_score, result.center_freq_hz)


class Sweeper:
    """Drive a :class:`~antsdr_toolkit.device.base.SampleSource` through a dwell plan.

    Parameters
    ----------
    source
        Any sample source.  Tunable sources (they override ``retune``) are
        stepped through ``plan``; fixed sources (SigMF replay, synthetic)
        are analysed as one dwell at their own centre with span
        ``min(bandwidth, usable_fraction * fs)`` and ``plan`` only
        contributes the targets that fall inside that span.
    plan
        Dwells from :func:`~.planner.plan_dwells`; required for tunable
        sources.  Every dwell's span must fit the source's sample rate.
    dwell_s, settle_s, discard_buffers
        Capture length, post-retune settling sleep and the number of
        ``dwell_s``-long reads thrown away after each retune.  These are in
        addition to whatever the driver does inside ``retune`` itself (the
        E200 driver already flushes its own ``discard_buffers``); set
        ``settle_s=0, discard_buffers=0`` to rely on the driver alone.
    fft_size
        Welch PSD size for the occupancy analysis.
    rng
        Generator used when ``order="random"`` (a fresh permutation of the
        plan on every run, so a periodic emitter is not systematically
        missed by a periodic sweep); ``None`` creates an unseeded one.
    order
        ``"sequential"`` (plan order) or ``"random"``.
    revisit_top, revisit_dwell_s
        After a run, re-capture the ``revisit_top`` best-ranked dwells for
        ``revisit_dwell_s`` (default ``dwell_s``) and replace their results.
    sleep, clock
        Injectable ``time.sleep`` / ``time.time`` (tests pass fakes).
    Remaining keyword arguments are forwarded to :func:`analyse_dwell`.
    """

    def __init__(
        self,
        source: SampleSource,
        plan: Sequence[Dwell] | None = None,
        *,
        dwell_s: float = 0.06,
        settle_s: float = 0.08,
        discard_buffers: int = 2,
        fft_size: int = 4096,
        rng: np.random.Generator | None = None,
        usable_fraction: float = DEFAULT_USABLE_FRACTION,
        order: str = "sequential",
        revisit_top: int = 0,
        revisit_dwell_s: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        **analysis_kwargs: Any,
    ) -> None:
        if float(dwell_s) <= 0.0:
            raise ValueError("dwell_s must be positive")
        if float(settle_s) < 0.0 or int(discard_buffers) < 0:
            raise ValueError("settle_s and discard_buffers must be >= 0")
        if order not in ("sequential", "random"):
            raise ValueError("order must be 'sequential' or 'random'")
        if int(revisit_top) < 0:
            raise ValueError("revisit_top must be >= 0")
        self.source = source
        self.dwell_s = float(dwell_s)
        self.settle_s = float(settle_s)
        self.discard_buffers = int(discard_buffers)
        self.fft_size = int(fft_size)
        self.order = order
        self.revisit_top = int(revisit_top)
        self.revisit_dwell_s = self.dwell_s if revisit_dwell_s is None else float(revisit_dwell_s)
        self._rng = rng
        self._sleep = sleep
        self._clock = clock
        self._analysis = dict(analysis_kwargs)
        self.n_runs = 0

        info = source.info
        fs = info.sample_rate_hz
        self.fixed_tuning = is_fixed_tuning(source)
        given = list(plan or [])
        if self.fixed_tuning:
            span = min(info.bandwidth_hz, usable_span_hz(fs, usable_fraction))
            fixed = Dwell(info.center_freq_hz, span)
            targets = tuple(t for d in given for t in d.targets if fixed.covers(t))
            if given and (len(given) != 1 or abs(given[0].center_freq_hz - fixed.center_freq_hz) > 1.0):
                log.info("%s cannot retune: using one dwell at %.6f MHz instead of the %d-dwell plan",
                         type(source).__name__, fixed.center_freq_hz / 1e6, len(given))
            self.plan: list[Dwell] = [Dwell(fixed.center_freq_hz, fixed.span_hz, targets)]
        else:
            if not given:
                raise ValueError("a tunable source needs a non-empty plan")
            for d in given:
                if d.span_hz > fs * (1.0 + 1e-9):
                    raise ValueError(
                        f"dwell span {d.span_hz:.0f} Hz exceeds the source sample rate {fs:.0f} Hz"
                    )
            self.plan = given

    @property
    def info(self) -> StreamInfo:
        return self.source.info

    def _ordered_plan(self) -> list[Dwell]:
        if self.order == "sequential" or len(self.plan) < 2:
            return list(self.plan)
        if self._rng is None:
            self._rng = np.random.default_rng()
        perm = self._rng.permutation(len(self.plan))
        return [self.plan[int(i)] for i in perm]

    def _capture(self, dwell: Dwell, dwell_s: float) -> DwellResult | None:
        fs = self.source.info.sample_rate_hz
        n = max(1, round(dwell_s * fs))
        if not self.fixed_tuning:
            self.source.retune(dwell.center_freq_hz)
            if self.settle_s > 0.0:
                self._sleep(self.settle_s)
            for _ in range(self.discard_buffers):
                self.source.read(n)
        t0 = float(self._clock())
        x = self.source.read(n)
        if x.shape[-1] == 0:
            return None
        return analyse_dwell(
            x, fs, dwell.center_freq_hz, dwell.span_hz, t_wall_s=t0, targets=dwell.targets,
            fft_size=self.fft_size, **self._analysis,
        )

    def run_once(self) -> list[DwellResult]:
        """Visit every dwell once; results sorted by activity (most active first).

        A finite fixed source that is exhausted yields an empty list.
        """
        results: list[DwellResult] = []
        for dwell in self._ordered_plan():
            result = self._capture(dwell, self.dwell_s)
            if result is None:
                break
            results.append(result)
        if self.revisit_top and results and not self.fixed_tuning:
            results.sort(key=_rank_key)
            for k in range(min(self.revisit_top, len(results))):
                r = results[k]
                again = self._capture(Dwell(r.center_freq_hz, r.span_hz, r.targets),
                                      self.revisit_dwell_s)
                if again is not None:
                    results[k] = again
        results.sort(key=_rank_key)
        self.n_runs += 1
        return results

    def iter_runs(self, n_runs: int | None = None) -> Iterator[list[DwellResult]]:
        """Yield :meth:`run_once` results ``n_runs`` times (forever when ``None``).

        Stops early when a run returns no results (finite source exhausted).
        """
        done = 0
        while n_runs is None or done < n_runs:
            results = self.run_once()
            if not results:
                return
            yield results
            done += 1


# --------------------------------------------------------------------------- aggregation
@dataclass(eq=False)
class OccupancyEntry:
    """Accumulated statistics of one dwell centre across runs."""

    center_freq_hz: float
    span_hz: float
    freqs_hz: np.ndarray
    max_hold_db: np.ndarray
    above_count: np.ndarray
    n_runs: int = 0
    n_bursts: int = 0
    kurtosis_max: float = 0.0
    noise_floors_db: list[float] = field(default_factory=list)

    @property
    def occupancy(self) -> np.ndarray:
        """Fraction of runs (0..1) in which each bin exceeded floor + threshold."""
        if self.n_runs == 0:
            return np.zeros_like(self.max_hold_db)
        return self.above_count / float(self.n_runs)

    def to_dict(self, *, decimals: int = 1) -> dict[str, Any]:
        floors = self.noise_floors_db
        return {
            "center_freq_hz": self.center_freq_hz,
            "span_hz": self.span_hz,
            "n_runs": int(self.n_runs),
            "n_bins": int(self.freqs_hz.size),
            "bin_hz": float(np.median(np.diff(self.freqs_hz))) if self.freqs_hz.size > 1 else 0.0,
            "freqs_hz": [float(v) for v in self.freqs_hz],
            "max_hold_db": [round(float(v), decimals) for v in self.max_hold_db],
            "occupancy": [round(float(v), 4) for v in self.occupancy],
            "noise_floor_db": {
                "median": float(np.median(floors)) if floors else None,
                "min": float(min(floors)) if floors else None,
                "max": float(max(floors)) if floors else None,
            },
            "n_bursts": int(self.n_bursts),
            "kurtosis_max": float(self.kurtosis_max),
        }


class OccupancyMap:
    """Max-hold and occupancy fraction per PSD bin, accumulated over sweep runs.

    Results are grouped by dwell centre (rounded to ``key_hz``); a dwell
    whose frequency axis differs from the stored one for that centre (other
    sample rate / FFT size) raises ``ValueError``.  A bin counts as occupied
    in a run when its PSD exceeds that run's noise floor by ``threshold_db``
    (the raw per-bin test, without the notch/closing of the segment
    extraction).
    """

    def __init__(self, *, threshold_db: float = DEFAULT_OCCUPANCY_THRESHOLD_DB,
                 key_hz: float = 1.0) -> None:
        self.threshold_db = float(threshold_db)
        self.key_hz = float(key_hz)
        self._entries: dict[float, OccupancyEntry] = {}
        self.n_runs = 0

    def _key(self, center_freq_hz: float) -> float:
        return round(float(center_freq_hz) / self.key_hz) * self.key_hz

    def update(self, results: Sequence[DwellResult]) -> None:
        """Fold one run's results into the map."""
        for r in results:
            key = self._key(r.center_freq_hz)
            entry = self._entries.get(key)
            if entry is None:
                entry = OccupancyEntry(
                    center_freq_hz=r.center_freq_hz,
                    span_hz=r.span_hz,
                    freqs_hz=np.array(r.freqs_hz, dtype=np.float64),
                    max_hold_db=np.full(r.freqs_hz.size, -np.inf),
                    above_count=np.zeros(r.freqs_hz.size, dtype=np.int64),
                )
                self._entries[key] = entry
            elif entry.freqs_hz.size != r.freqs_hz.size or not np.allclose(
                entry.freqs_hz, r.freqs_hz, rtol=0.0, atol=1e-3
            ):
                raise ValueError(
                    f"frequency axis of dwell {r.center_freq_hz:.0f} Hz does not match the map"
                )
            psd = np.asarray(r.psd_db, dtype=np.float64)
            entry.max_hold_db = np.maximum(entry.max_hold_db, psd)
            entry.above_count += (psd > r.noise_floor_db + self.threshold_db)
            entry.n_runs += 1
            entry.n_bursts += len(r.bursts)
            entry.kurtosis_max = max(entry.kurtosis_max, float(r.kurtosis))
            entry.noise_floors_db.append(float(r.noise_floor_db))
        self.n_runs += 1

    def entries(self) -> list[OccupancyEntry]:
        """Entries in ascending centre-frequency order."""
        return [self._entries[k] for k in sorted(self._entries)]

    def entry(self, center_freq_hz: float) -> OccupancyEntry:
        return self._entries[self._key(center_freq_hz)]

    def __len__(self) -> int:
        return len(self._entries)

    def segments(self, *, min_fraction: float = 0.5) -> list[dict[str, float]]:
        """Frequency ranges occupied in at least ``min_fraction`` of their dwell's runs.

        Each row: ``center_freq_hz`` (dwell), ``f_low_hz``, ``f_high_hz``,
        ``occupancy`` (max fraction inside the run) and ``max_hold_db``.
        """
        rows: list[dict[str, float]] = []
        for e in self.entries():
            occ = e.occupancy
            mask = occ >= float(min_fraction)
            if not mask.any():
                continue
            df = float(np.median(np.diff(e.freqs_hz))) if e.freqs_hz.size > 1 else 0.0
            edges = np.diff(mask.astype(np.int8), prepend=0, append=0)
            for s, t in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
                rows.append({
                    "center_freq_hz": e.center_freq_hz,
                    "f_low_hz": float(e.freqs_hz[s] - df / 2.0),
                    "f_high_hz": float(e.freqs_hz[t - 1] + df / 2.0),
                    "occupancy": float(occ[s:t].max()),
                    "max_hold_db": float(e.max_hold_db[s:t].max()),
                })
        return rows

    def to_dict(self, *, decimals: int = 1) -> dict[str, Any]:
        return {
            "schema": OCCUPANCY_MAP_SCHEMA,
            "n_runs": int(self.n_runs),
            "threshold_db": self.threshold_db,
            "dwells": [e.to_dict(decimals=decimals) for e in self.entries()],
        }

    def to_json(self, *, indent: int | None = None, decimals: int = 1) -> str:
        return json.dumps(self.to_dict(decimals=decimals), indent=indent)
