"""Backend-neutral spectrum sweep: the :class:`SweepSource` contract.

Two implementations, both producing the SAME ``(freqs_mhz, power_matrix, n_rows)``
shape that :mod:`aerix_rf.scan.candidates` / :mod:`aerix_rf.scan.sweep`'s
``Baseline`` already consume -- ``freqs_mhz`` a sorted grid of bin centres
(MHz), ``power_matrix`` ``[n_rows, n_bins]`` dB, one row per completed sweep
of the requested band:

  * :class:`HackrfSweepSource` -- the existing ``hackrf_sweep`` subprocess
    path (:mod:`aerix_rf.scan.sweep`), UNCHANGED behaviour. Selected when the
    backend's :class:`~aerix_rf.sdr.capture.ReceiverCapabilities.supports_sweep`
    is true (today: only HackRF).
  * :class:`RetuneWelchSweep` -- generic: works over any
    :class:`~aerix_rf.sdr.capture.IQSource` that implements ``tune()`` /
    ``windows()`` (ANTSDR, sim, file, ...). Steps the LO across the requested
    range in ``step_hz`` increments (default: the source's usable analog
    bandwidth -- ``getattr(source, "rf_bandwidth", None)`` if the backend sets
    one, e.g. 10 MHz for the ANTSDR default profile, else
    ``capabilities.max_instantaneous_bw_hz``), dwells ``dwells_per_step``
    ``windows()``-sized reads per step (default 2), discards the first
    ``settle_s`` (default 50 ms) of the FIRST post-retune window to let the LO
    settle, computes a Welch-style PSD per dwell with the canonical STFT
    (:func:`aerix_rf.dsp.spectrogram.compute` -- same Hanning window / DC
    handling as everywhere else in the pipeline), and stitches the per-step
    PSDs onto one frequency grid by linear-power-averaging overlapping bins.

Sweeping by retune is much slower than ``hackrf_sweep`` (docs/design/antsdr-
backend.md risk #13): one row costs ``n_steps * dwells_per_step`` whole
``windows()`` reads, which is seconds, not milliseconds. ``sweep()`` always
completes the row in progress before checking the ``seconds`` dwell budget,
so it always returns >= 1 row (never an empty/partial one), matching
``hackrf_sweep``'s contract -- but for a live receiver a caller should not
assume a fast return for ``seconds`` less than one row's cost.

HackRF-specific control (gain args, hackrf_sweep CSV parsing) stays in
:mod:`aerix_rf.scan.sweep`; this module only holds the generic contract that
does not need to know it exists.

ANTSDR E200 (``antsdr_iio``) via :class:`RetuneWelchSweep`, NOT hardware-
validated yet (no E200 access during this change; see the CLI wiring in
:mod:`aerix_rf.cli`'s ``_sweep_source_for``, which picks this path whenever
``supports_sweep`` is false):
  * ``step_hz`` defaults to the backend's advertised ``rf_bandwidth`` --
    10 MHz for the ANTSDR default profile (the AD9361's *usable* analog
    front-end bandwidth at that profile's sample rate, per
    ``antsdr-specialist``; NOT the full ``max_instantaneous_bw_hz`` the
    capabilities object may otherwise report -- see the sim-backend caveat
    below for why that distinction matters).
  * ``dwells_per_step=2`` whole ``windows()`` reads per retune (default
    ``window_s`` dwell length is whatever the backend's own ``Config``
    configured, unchanged by this module).
  * ``settle_s=0.05`` (50 ms) of the first post-retune window is discarded
    for AD9361 LO-settle time; unvalidated on real hardware -- this number
    came from the general PLL-lock-time guidance in
    ``docs/design/antsdr-backend.md``, not a measurement.
  * Try on real hardware with (E200 was busy during this change):
    ``LD_LIBRARY_PATH=/home/jarvis/aerix-rf/.antsdr-tools/mamba/envs/antsdr/lib
    AERIX_RF_ANTSDR_URI=ip:192.168.1.10 uv run aerix-rf baseline
    --backend antsdr_iio --band 2.4 --seconds 30 --out <dir>``

FIXED (2026-09-18, architect decision): ``step_hz``'s fallback previously
trusted ``capabilities.max_instantaneous_bw_hz`` (a backend's advertised
theoretical range ceiling) over the ACTUAL sample rate ``windows()``
delivers when a backend's real-time rate is fixed by ``Config`` rather than
by capability (true for ``SimSource``: ``max_instantaneous_bw_hz=100e6`` but
``windows()`` actually runs at ``cfg.sample_rate``, e.g. 20 MHz). Trusting
the ceiling alone produced a single oversized step whose dwell only covered
a fraction of the requested grid, leaving the rest NaN. ``step_hz`` now
derives from the source's own usable-bandwidth attribute
(``rf_bandwidth``/``bandwidth_hz``, e.g. ANTSDR's 10 MHz) or, failing that,
``DEFAULT_USABLE_FRACTION`` (0.6) of the source's ACTUAL live sample rate,
then is always capped by ``capabilities.max_instantaneous_bw_hz`` -- see
``RetuneWelchSweep.__init__``.
"""

from __future__ import annotations

import time
from typing import Any, Iterator, Protocol, runtime_checkable

import numpy as np

from ..dsp import spectrogram
from .capture import IQSource

__all__ = [
    "SweepSource",
    "HackrfSweepSource",
    "RetuneWelchSweep",
    "DEFAULT_BIN_HZ",
    "DEFAULT_DWELLS_PER_STEP",
    "DEFAULT_SETTLE_S",
    "DEFAULT_FFT_SIZE",
    "DEFAULT_INNER_USABLE_FRAC",
    "DEFAULT_DC_BLANK_BINS",
]

DEFAULT_BIN_HZ = 500_000
DEFAULT_DWELLS_PER_STEP = 2
DEFAULT_SETTLE_S = 0.05
DEFAULT_FFT_SIZE = 1024
# Conservative default usable fraction of a source's ACTUAL live sample rate,
# used only when the backend does not already advertise its own usable analog
# bandwidth (``rf_bandwidth``/``bandwidth_hz``, e.g. ANTSDR's 10 MHz at
# 12.288 MS/s). Matches the sim backend's default 20 MS/s -> 12 MHz.
DEFAULT_USABLE_FRACTION = 0.6
# FIXED (2026-09-19, seam-comb defect): a dwell's FULL analog bandwidth
# (``step_hz``) includes its own edge roll-off / anti-alias transition band
# (and, at zero-IF, a DC/LO-leak spike at its own centre). Measured on real
# ANTSDR hardware (``base_58.npz``, 5.8 GHz baseline): a +7 dB, 4-bin-wide
# (500 kHz bins) comb sat exactly at every 10 MHz step SEAM -- the edges of
# each dwell's usable band -- because the OLD stitcher (a) fed a dwell's full
# ``step_hz``-wide span, edges included, straight into the stitched grid, and
# (b) stepped centres exactly ``step_hz`` apart with ZERO overlap, so each
# edge region was covered by only one (contaminated) dwell instead of an
# interior region of a neighbour. Only the CENTRAL ``DEFAULT_INNER_USABLE_FRAC``
# of each dwell's own bandwidth is trusted; retune centres are then spaced by
# that trimmed (interior) width instead of the full bandwidth, so consecutive
# dwells' interiors exactly tile (no-gap) the requested band -- see
# ``RetuneWelchSweep.__init__``/``_step_centers``/``_dwell_psd``.
DEFAULT_INNER_USABLE_FRAC = 0.82
# Fine (per-dwell PSD resolution, i.e. ``sample_rate / fft_size``) bins blanked
# by interpolation around each dwell's OWN tuned centre (DC/LO-leak spike),
# wider than :data:`aerix_rf.dsp.spectrogram._DC_BLANK_BINS`'s +-1 bin (which
# already runs unconditionally inside ``spectrogram.compute``) as a second,
# stitcher-level guard band -- LO leakage on real zero-IF hardware is not
# always a single-bin Dirac.
DEFAULT_DC_BLANK_BINS = 3


@runtime_checkable
class SweepSource(Protocol):
    """``sweep()`` -> ``(freqs_mhz, power_matrix [n_rows, n_bins] dB, n_rows)``,
    the exact tuple shape :func:`aerix_rf.scan.sweep.sweep_once` returns today."""

    def sweep(self, lo_mhz: float, hi_mhz: float, seconds: float,
              **kwargs: Any) -> tuple[np.ndarray, np.ndarray, int]: ...

    def close(self) -> None: ...


class HackrfSweepSource:
    """Wraps the existing ``hackrf_sweep`` subprocess path unchanged.

    ``kwargs`` passed to :meth:`sweep` are forwarded verbatim to
    :func:`aerix_rf.scan.sweep.sweep_once` (``bin_hz``, ``lna``, ``vga``,
    ``amp``, ``retries``, ``keep_csv``).
    """

    def sweep(self, lo_mhz: float, hi_mhz: float, seconds: float,
              **kwargs: Any) -> tuple[np.ndarray, np.ndarray, int]:
        from ..scan.sweep import sweep_once  # lazy: scan.sweep imports this module too
        return sweep_once(lo_mhz, hi_mhz, seconds, **kwargs)

    def close(self) -> None:
        pass  # no persistent resource: sweep_once owns its own subprocess


class RetuneWelchSweep:
    """Generic retune+Welch sweep over any live :class:`IQSource`.

    Does NOT open/close ``source`` itself on construction (the caller already
    built it, e.g. via ``aerix_rf.sdr.capture.make_source``); :meth:`close`
    forwards to ``source.close()`` so callers can treat every
    :class:`SweepSource` the same way.
    """

    def __init__(self, source: IQSource, *, step_hz: float | None = None,
                 dwells_per_step: int = DEFAULT_DWELLS_PER_STEP,
                 settle_s: float = DEFAULT_SETTLE_S,
                 fft_size: int = DEFAULT_FFT_SIZE,
                 usable_frac: float = DEFAULT_INNER_USABLE_FRAC,
                 dc_blank_bins: int = DEFAULT_DC_BLANK_BINS) -> None:
        self.source = source
        caps = source.capabilities
        if not step_hz:
            # Prefer a backend's own advertised usable analog bandwidth
            # (ANTSDR: rf_bandwidth, 10 MHz at the default 12.288 MS/s profile).
            step_hz = getattr(source, "rf_bandwidth", None) or getattr(source, "bandwidth_hz", None)
        if not step_hz:
            # No explicit usable-bandwidth attribute: derive from the source's
            # ACTUAL live sample rate (never from capabilities alone -- a
            # backend's capabilities ceiling is a theoretical range, not what
            # windows() is actually delivering, e.g. sim advertises 100 MHz but
            # runs at cfg.sample_rate=20 MHz; trusting the ceiling produced a
            # single oversized step whose dwell only covered a fraction of the
            # grid, leaving the rest NaN).
            actual_sample_rate = (getattr(source, "sample_rate", None)
                                   or getattr(getattr(source, "cfg", None), "sample_rate", None))
            if actual_sample_rate:
                step_hz = float(actual_sample_rate) * DEFAULT_USABLE_FRACTION
        if not step_hz:
            step_hz = caps.max_instantaneous_bw_hz or None
        if not step_hz:
            # last resort: the top of the source's own sample-rate range
            step_hz = caps.sample_rates_hz[-1] if caps.sample_rates_hz else 10e6
        # Never exceed the backend's own advertised ceiling, whichever path produced step_hz.
        if caps.max_instantaneous_bw_hz:
            step_hz = min(float(step_hz), float(caps.max_instantaneous_bw_hz))
        self.step_hz = float(step_hz)
        self.dwells_per_step = max(1, int(dwells_per_step))
        self.settle_s = float(settle_s)
        self.fft_size = int(fft_size)
        # (a)/(b) seam-comb fix: only the central `usable_frac` of a dwell's own
        # `step_hz`-wide span is trusted (edge roll-off trimmed); consecutive
        # dwell centres are then spaced by that trimmed (interior) width --
        # `usable_frac * step_hz` -- instead of the full `step_hz`, so
        # interiors exactly tile the requested band with no gap left uncovered
        # by any dwell's interior. `overlap_hz` (recorded for callers' meta,
        # e.g. `aerix_rf.scan.sweep.save_baseline`) is the resulting overlap
        # between consecutive dwells' FULL (untrimmed) spans -- exactly the
        # total width trimmed off one dwell's two edges, i.e. the minimum
        # overlap that guarantees full interior coverage; see module docstring.
        self.usable_frac = float(usable_frac)
        if not (0.0 < self.usable_frac <= 1.0):
            raise ValueError(f"usable_frac must be in (0, 1], got {self.usable_frac!r}")
        self.overlap_hz = self.step_hz * (1.0 - self.usable_frac)
        self._retune_stride_hz = self.step_hz - self.overlap_hz  # == usable_frac * step_hz
        self.dc_blank_bins = max(0, int(dc_blank_bins))
        self._windows: Iterator | None = None
        self.row_started_at: list[float] = []   # monotonic wall-clock per emitted row

    def close(self) -> None:
        self.source.close()

    # -- internals ---------------------------------------------------------

    def _next_window(self):
        if self._windows is None:
            self._windows = self.source.windows()
        win = next(self._windows, None)
        if win is None:
            raise RuntimeError("IQSource stopped producing windows during a sweep")
        return win

    def _step_centers(self, lo_hz: float, hi_hz: float) -> np.ndarray:
        # Spaced by the TRIMMED interior width (`_retune_stride_hz`), not the
        # full dwell bandwidth (`step_hz`) -- see __init__ / module docstring.
        stride = self._retune_stride_hz
        span = max(hi_hz - lo_hz, stride)
        n = max(1, int(np.ceil(span / stride - 1e-9)))
        centers = lo_hz + stride * (np.arange(n) + 0.5)
        if n > 1:
            # last step ends exactly at hi_hz instead of overshooting by < stride
            centers[-1] = hi_hz - stride / 2
        return centers

    def _build_grid(self, lo_hz: float, hi_hz: float, bin_hz: float) -> np.ndarray:
        n = max(1, int(round((hi_hz - lo_hz) / bin_hz)))
        return lo_hz + bin_hz * (np.arange(n) + 0.5)

    def _dwell_psd(self, center_hz: float) -> tuple[np.ndarray, np.ndarray]:
        """Retune, settle, Welch-average ``dwells_per_step`` windows -> (freqs_hz, power_db)."""
        self.source.tune(center_hz)
        chunks = []
        sample_rate = None
        for i in range(self.dwells_per_step):
            win = self._next_window()
            sample_rate = win.sample_rate
            iq = win.iq
            if i == 0 and self.settle_s > 0:
                n_discard = min(iq.size, int(round(self.settle_s * sample_rate)))
                iq = iq[n_discard:]
            if iq.size:
                chunks.append(iq)
        if not chunks:
            # settle_s ate the entire first dwell (very short windows): take one
            # more, undiscarded, rather than feed the STFT an empty array.
            win = self._next_window()
            sample_rate = win.sample_rate
            chunks = [win.iq]
        iq = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
        spec = spectrogram.compute(iq, sample_rate, fft_size=self.fft_size)
        lin = np.power(10.0, spec.power_db.astype(np.float64) / 10.0)
        with np.errstate(divide="ignore"):
            psd_db = 10.0 * np.log10(np.mean(lin, axis=0) + 1e-30)
        freqs_hz = spec.freqs_hz + center_hz

        # (c) DC/LO-leak guard: blank +-dc_blank_bins fine bins around this
        # dwell's OWN tuned centre (index len//2, since freqs_hz is spec's
        # fftshifted, zero-centred grid offset by center_hz) by interpolating
        # from the immediate neighbours -- same style as, but wider than,
        # spectrogram.compute's own unconditional +-1 bin DC blank.
        k = self.dc_blank_bins
        c = psd_db.size // 2
        if k > 0 and psd_db.size >= 2 * k + 4:
            left = psd_db[max(0, c - k - 3):c - k]
            right = psd_db[c + k + 1:c + k + 4]
            fill = 0.5 * (left.mean() + right.mean()) if left.size and right.size else np.nan
            if np.isfinite(fill):
                psd_db = psd_db.copy()
                psd_db[c - k:c + k + 1] = fill

        # (a) trim to this dwell's inner usable band only -- the outer edges
        # (analog roll-off / anti-alias transition) are discarded rather than
        # stitched in; retune centres are already spaced (see _step_centers)
        # so every requested frequency falls inside the interior of >= 1 dwell.
        half_width_hz = self.step_hz * self.usable_frac / 2.0
        interior = np.abs(freqs_hz - center_hz) <= half_width_hz
        return freqs_hz[interior], psd_db[interior]

    def _bin_row(self, grid: np.ndarray, contribs: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
        """Stitch per-step PSDs onto ``grid`` (linear-power average where steps
        overlap -- see module docstring).

        A per-step PSD's own frequency resolution (``sample_rate / fft_size``,
        e.g. ~20 kHz at the defaults) is normally much FINER than the output
        ``grid`` (``bin_hz``, default 500 kHz): plain ``np.interp`` only
        samples the two fine bins nearest each coarse grid point and silently
        drops a narrowband peak that happens to sit between grid points
        (observed: a synthetic tone with an exact-bin peak in the per-step PSD
        vanished into the noise floor after stitching -- T5 test
        ``test_stitched_sweep_peaks_within_one_bin_and_ordered_by_amplitude``).
        When the step is denser than the grid we instead average, in linear
        power, every fine bin whose centre falls inside each grid cell -- the
        correct "wider resolution bandwidth" downsample, and consistent with
        every other linear-power average in this codebase
        (:func:`aerix_rf.scan.sweep.average_db`, the dwell-PSD time-average
        above). ``np.interp`` is kept as a fallback for grid cells no fine
        bin lands in (grid finer than the step's own resolution).
        """
        bin_hz = float(np.median(np.diff(grid))) if grid.size > 1 else 1.0
        grid_edge0 = grid[0] - bin_hz / 2.0
        acc_lin = np.zeros_like(grid)
        acc_n = np.zeros(grid.shape, dtype=np.int32)
        for freqs_hz, psd_db in contribs:
            lo, hi = freqs_hz[0], freqs_hz[-1]
            mask = (grid >= lo) & (grid <= hi)
            if not mask.any():
                continue
            lin = np.power(10.0, psd_db / 10.0)
            contrib_vals = np.interp(grid[mask], freqs_hz, lin)  # sparse-grid fallback
            src_res = float(np.median(np.diff(freqs_hz))) if freqs_hz.size > 1 else bin_hz
            if src_res < bin_hz * 0.9:
                idx = np.floor((freqs_hz - grid_edge0) / bin_hz).astype(np.int64)
                valid = (idx >= 0) & (idx < grid.size)
                sums = np.bincount(idx[valid], weights=lin[valid], minlength=grid.size)
                counts = np.bincount(idx[valid], minlength=grid.size)
                covered_idx = np.nonzero(mask)[0]
                has_fine = counts[covered_idx] > 0
                contrib_vals[has_fine] = (sums[covered_idx] / np.maximum(counts[covered_idx], 1))[has_fine]
            acc_lin[mask] += contrib_vals
            acc_n[mask] += 1
        row = np.full(grid.shape, np.nan)
        covered = acc_n > 0
        with np.errstate(divide="ignore", invalid="ignore"):
            row[covered] = 10.0 * np.log10(acc_lin[covered] / acc_n[covered])
        return row

    # -- public --------------------------------------------------------------

    def sweep(self, lo_mhz: float, hi_mhz: float, seconds: float, *,
              bin_hz: float = DEFAULT_BIN_HZ,
              **_ignored: Any) -> tuple[np.ndarray, np.ndarray, int]:
        """One or more full lo->hi passes; always >= 1 row (see module docstring).

        ``_ignored`` swallows HackRF-only kwargs (``lna``/``vga``/``amp``/...)
        so callers can pass the same kwargs dict to either :class:`SweepSource`
        without branching -- see ``aerix_rf.cli``.
        """
        lo_hz, hi_hz = float(lo_mhz) * 1e6, float(hi_mhz) * 1e6
        centers = self._step_centers(lo_hz, hi_hz)
        grid = self._build_grid(lo_hz, hi_hz, float(bin_hz))
        rows: list[np.ndarray] = []
        self.row_started_at = []
        t_start = time.time()
        while True:
            t_row = time.time()
            contribs = [self._dwell_psd(c) for c in centers]
            rows.append(self._bin_row(grid, contribs))
            self.row_started_at.append(t_row)
            if time.time() - t_start >= seconds:
                break
        matrix = np.vstack(rows)
        return grid / 1e6, matrix, matrix.shape[0]
