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
