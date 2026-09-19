"""T5: backend-neutral sweep (``aerix_rf.sdr.sweep``).

Synthetic-only (no hardware): a retunable multi-tone fake ``IQSource`` drives
``RetuneWelchSweep`` and checks the stitched output against the SAME
``(freqs_mhz, power_matrix, n_rows)`` contract ``hackrf_sweep``-backed code
already relies on (``scan.candidates.rank_candidates``, ``scan.sweep.Baseline``).
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from aerix_rf.sdr.capture import IQSource, IQWindow, ReceiverCapabilities
from aerix_rf.sdr.sweep import HackrfSweepSource, RetuneWelchSweep
from aerix_rf.scan.sweep import Baseline, average_db
from aerix_rf.scan.candidates import rank_candidates


class _MultiToneSource(IQSource):
    """Retunable synthetic IQSource: fixed-frequency tones + noise, no hardware."""

    receiver_type = "faketone"

    def __init__(self, tones_mhz: list[float], amps: list[float] | None = None,
                 sample_rate: float = 20e6, window_s: float = 0.02,
                 noise_std: float = 0.01, bw_hz: float = 20e6, seed: int = 0) -> None:
        self.tones_hz = [float(t) * 1e6 for t in tones_mhz]
        self.amps = list(amps) if amps is not None else [1.0] * len(self.tones_hz)
        self.sample_rate = float(sample_rate)
        self.window_s = float(window_s)
        self.noise_std = float(noise_std)
        self.bw_hz = float(bw_hz)
        self._rng = np.random.default_rng(seed)
        self._center_hz = 0.0

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return ReceiverCapabilities(
            receiver_type="faketone", backend="fake",
            tuning_range_hz=(0.0, 6e9),
            sample_rates_hz=(self.sample_rate, self.sample_rate),
            sample_rate_is_range=False, max_instantaneous_bw_hz=self.bw_hz,
            channel_count=1, native_iq_format="complex64", native_full_scale=1.0,
            supports_sweep=False,
        )

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)

    def windows(self):
        n = max(1, int(self.sample_rate * self.window_s))
        t = np.arange(n) / self.sample_rate
        while True:
            iq = (self._rng.normal(0, self.noise_std, n)
                  + 1j * self._rng.normal(0, self.noise_std, n)).astype(np.complex64)
            for f_hz, amp in zip(self.tones_hz, self.amps):
                bb = f_hz - self._center_hz
                if abs(bb) <= self.sample_rate / 2:
                    iq += (amp * np.exp(2j * np.pi * bb * t)).astype(np.complex64)
            yield IQWindow(iq=iq, captured_at=time.time(), sample_rate=self.sample_rate,
                           center_freq_hz=self._center_hz, receiver_type="faketone",
                           expected_samples=n)


class _RolledOffNoiseSource(IQSource):
    """Retunable synthetic IQSource: flat-floor coloured noise whose per-dwell
    passband has a realistic analog roll-off (fixed relative to the CURRENT
    tuned centre, as a real front-end's would be) plus a DC/LO-leak spur at
    each dwell's own centre. Used to reproduce/verify the seam-comb defect
    (``base_58.npz``) with a controlled, backend-neutral fake -- no hardware.
    """

    receiver_type = "fakerolloff"

    def __init__(self, sample_rate: float = 20e6, window_s: float = 0.05,
                 floor_lin: float = 1.0, rolloff_db_at_0_45fs: float = -6.0,
                 dc_lin: float = 0.0, seed: int = 0) -> None:
        self.sample_rate = float(sample_rate)
        self.window_s = float(window_s)
        self.floor_lin = float(floor_lin)
        self.rolloff_db_at_0_45fs = float(rolloff_db_at_0_45fs)
        self.dc_lin = float(dc_lin)
        self._rng = np.random.default_rng(seed)
        self._center_hz = 0.0
        self._n = max(8, int(round(self.sample_rate * self.window_s)))
        freqs = np.fft.fftfreq(self._n, d=1.0 / self.sample_rate)
        nyq = self.sample_rate / 2.0
        x = np.abs(freqs) / nyq                      # 0..1, fraction of Nyquist
        # Flat (0 dB) passband out to 0.85*Nyquist, then a linear roll-off
        # through `rolloff_db_at_0_45fs` at exactly |f| = 0.45*Fs (0.9*Nyquist)
        # -- same relative shape every dwell, independent of where it is
        # tuned (a real front end's response is fixed relative to its own LO,
        # not to absolute frequency). Flat well past the default
        # `usable_frac` (0.82) interior boundary so the TRIMMED region is
        # actually flat; only the discarded outer edge rolls off.
        x0 = 0.85
        resp_db = np.where(x <= x0, 0.0,
                           self.rolloff_db_at_0_45fs * (x - x0) / (0.90 - x0))
        self._mag = np.sqrt(self.floor_lin) * np.power(10.0, resp_db / 20.0)

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return ReceiverCapabilities(
            receiver_type="fakerolloff", backend="fake",
            tuning_range_hz=(0.0, 6e9),
            sample_rates_hz=(self.sample_rate, self.sample_rate),
            sample_rate_is_range=False, max_instantaneous_bw_hz=self.sample_rate,
            channel_count=1, native_iq_format="complex64", native_full_scale=1.0,
            supports_sweep=False,
        )

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)

    def windows(self):
        n = self._n
        while True:
            spec = (self._rng.normal(0.0, 1.0, n) + 1j * self._rng.normal(0.0, 1.0, n))
            spec *= self._mag
            iq = np.fft.ifft(spec) * n
            if self.dc_lin:
                iq = iq + self.dc_lin   # constant offset -> delta exactly at this dwell's DC
            yield IQWindow(iq=iq.astype(np.complex64), captured_at=time.time(),
                           sample_rate=self.sample_rate, center_freq_hz=self._center_hz,
                           receiver_type="fakerolloff", expected_samples=n)


def _flat_region_stats(freqs: np.ndarray, row: np.ndarray, lo_mhz: float, hi_mhz: float) -> tuple[float, float]:
    """(median_db, max_abs_deviation_db) over bins covered inside [lo, hi]."""
    mask = (freqs >= lo_mhz) & (freqs <= hi_mhz) & np.isfinite(row)
    vals = row[mask]
    med = float(np.median(vals))
    dev = float(np.max(np.abs(vals - med)))
    return med, dev


def test_seam_comb_fixed_by_inner_trim_and_overlap():
    """Regression for the measured base_58.npz defect: a +7 dB, 4-bin-wide
    comb at every step SEAM. Reproduced here with OLD stitcher parameters
    (usable_frac=1.0, no DC guard) on a synthetic flat-floor source with a
    realistic per-dwell roll-off + DC spur; fixed with the NEW defaults."""
    src = _RolledOffNoiseSource(sample_rate=20e6, window_s=0.05,
                                rolloff_db_at_0_45fs=-6.0, dc_lin=0.02, seed=7)
    bin_hz = 500_000

    # OLD behaviour: no inner trim, no overlap, no extra DC guard -- reproduces
    # the seam pattern (edges of each 20 MHz dwell abut with zero overlap).
    old = RetuneWelchSweep(src, step_hz=20e6, dwells_per_step=1, settle_s=0.0,
                           fft_size=1024, usable_frac=1.0, dc_blank_bins=0)
    freqs_old, mat_old, _ = old.sweep(LO, HI, seconds=0.0, bin_hz=bin_hz)
    _, dev_old = _flat_region_stats(freqs_old, mat_old[0], LO + 1.0, HI - 1.0)
    assert dev_old > 1.5, f"expected the OLD stitcher to show a seam artifact, got dev={dev_old:.2f} dB"

    # NEW behaviour: inner-trim + overlap-safe stepping + DC guard -> flat.
    new = RetuneWelchSweep(src, step_hz=20e6, dwells_per_step=1, settle_s=0.0,
                           fft_size=1024)
    freqs_new, mat_new, _ = new.sweep(LO, HI, seconds=0.0, bin_hz=bin_hz)
    _, dev_new = _flat_region_stats(freqs_new, mat_new[0], LO + 1.0, HI - 1.0)
    assert dev_new <= 0.5, f"expected a flat stitched floor, got max deviation {dev_new:.2f} dB"


def test_step_centers_use_trimmed_interior_stride():
    """Retune spacing is `usable_frac * step_hz`, not the full `step_hz` --
    the mechanism that removes the seam gap (see module docstring)."""
    src = _RolledOffNoiseSource(sample_rate=20e6, window_s=0.01)
    sweep = RetuneWelchSweep(src, step_hz=20e6, usable_frac=0.8)
    assert sweep.overlap_hz == pytest.approx(20e6 * 0.2)
    centers = sweep._step_centers(0.0, 80e6)
    spacing = np.diff(centers)
    assert np.allclose(spacing, 20e6 * 0.8)


LO, HI = 2400.0, 2480.0


def test_stitched_sweep_peaks_within_one_bin_and_ordered_by_amplitude():
    # Offset from the step centres (2410/2430/2450/2470 MHz for a 20 MHz step
    # starting at 2400 MHz) so none land exactly on DC, which spectrogram.compute
    # blanks (receiver DC-spike removal) -- see aerix_rf.dsp.spectrogram.compute.
    tones = [2405.0, 2427.0, 2453.0, 2475.0]
    amps = [1.0, 0.6, 0.35, 0.15]           # strictly decreasing -> strictly decreasing dB
    src = _MultiToneSource(tones, amps=amps, window_s=0.02, noise_std=0.005)
    sweep = RetuneWelchSweep(src, step_hz=20e6, dwells_per_step=1, settle_s=0.0, fft_size=1024)
    bin_hz = 250_000
    freqs, matrix, n = sweep.sweep(LO, HI, seconds=0.0, bin_hz=bin_hz)

    assert n == 1
    assert freqs.size == matrix.shape[1]
    row = matrix[0]
    assert not np.isnan(row).all()

    peak_freqs = []
    peak_dbs = []
    for tone in tones:
        window = (freqs >= tone - 1.0) & (freqs <= tone + 1.0)
        assert window.any(), f"grid has no bins near {tone} MHz"
        sub = row[window]
        sub_freqs = freqs[window]
        i = int(np.nanargmax(sub))
        peak_freqs.append(sub_freqs[i])
        peak_dbs.append(sub[i])
        # peak within one bin of the true tone frequency
        assert abs(sub_freqs[i] - tone) <= bin_hz / 1e6 * 1.5

    # dB ordering follows amplitude ordering (strongest tone first)
    assert peak_dbs == sorted(peak_dbs, reverse=True)


def test_baseline_differencing_ranks_new_tone_top():
    baseline_src = _MultiToneSource([], window_s=0.02, noise_std=0.01, seed=1)
    live_src = _MultiToneSource([2452.0], amps=[1.0], window_s=0.02, noise_std=0.01, seed=2)

    bin_hz = 200_000
    base_sweep = RetuneWelchSweep(baseline_src, step_hz=20e6, dwells_per_step=1,
                                  settle_s=0.0, fft_size=512)
    freqs_b, mat_b, _ = base_sweep.sweep(LO, HI, seconds=0.0, bin_hz=bin_hz)
    baseline = Baseline(lo_mhz=LO, hi_mhz=HI, bin_hz=float(bin_hz),
                        freqs_mhz=freqs_b, power_db=average_db(mat_b),
                        n_sweeps=1, dwell_s=0.02)

    live_sweep = RetuneWelchSweep(live_src, step_hz=20e6, dwells_per_step=1,
                                  settle_s=0.0, fft_size=512)
    freqs_l, mat_l, _ = live_sweep.sweep(LO, HI, seconds=0.0, bin_hz=bin_hz)

    cands = rank_candidates(freqs_l, mat_l, baseline, min_delta_db=6.0, min_width_mhz=0.05)
    assert cands, "expected at least one candidate"
    assert abs(cands[0].center_mhz - 2452.0) <= 1.0


def test_retune_welch_sweep_step_hz_derives_from_actual_sample_rate():
    """No explicit step_hz, no rf_bandwidth/bandwidth_hz attribute: derive from the
    source's ACTUAL live sample_rate (20 MHz default) * DEFAULT_USABLE_FRACTION
    (0.6) -> 12 MHz, NOT the capabilities ceiling directly."""
    src = _MultiToneSource([2440.0], window_s=0.01, bw_hz=20e6)  # ceiling well above 12 MHz
    sweep = RetuneWelchSweep(src)
    assert sweep.step_hz == pytest.approx(12e6)


def test_retune_welch_sweep_step_hz_capped_by_capabilities():
    """Fraction-derived step_hz (12 MHz) must never exceed the backend's own
    advertised capabilities.max_instantaneous_bw_hz ceiling (here 10 MHz)."""
    src = _MultiToneSource([2440.0], window_s=0.01, bw_hz=10e6)
    sweep = RetuneWelchSweep(src)
    assert sweep.step_hz == pytest.approx(10e6)


def test_retune_welch_sweep_step_hz_not_capability_ceiling_alone():
    """Regression: a source whose capabilities advertise a big ceiling (e.g. sim's
    100 MHz) must not become one oversized step when the source's actual live
    sample rate is much smaller -- that left most of the grid NaN."""
    src = _MultiToneSource([2440.0], window_s=0.01, bw_hz=100e6)
    sweep = RetuneWelchSweep(src)
    assert sweep.step_hz == pytest.approx(12e6)
    assert sweep.step_hz != pytest.approx(100e6)


def test_hackrf_sweep_source_is_a_thin_wrapper(monkeypatch):
    """HackrfSweepSource forwards unchanged to scan.sweep.sweep_once (no behaviour added)."""
    import aerix_rf.scan.sweep as scan_sweep

    calls = {}

    def fake_sweep_once(lo, hi, seconds, **kwargs):
        calls["args"] = (lo, hi, seconds, kwargs)
        return np.array([2440.0]), np.zeros((1, 1)), 1

    monkeypatch.setattr(scan_sweep, "sweep_once", fake_sweep_once)
    src = HackrfSweepSource()
    freqs, matrix, n = src.sweep(2400.0, 2480.0, 2.0, bin_hz=500_000, lna=16, vga=24)
    assert calls["args"] == (2400.0, 2480.0, 2.0, {"bin_hz": 500_000, "lna": 16, "vga": 24})
    assert n == 1
    src.close()  # no-op, must not raise
