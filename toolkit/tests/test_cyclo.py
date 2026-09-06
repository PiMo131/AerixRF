"""Cyclostationary numerology tests, on OFDM signals built to order."""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.dsp import cyclo


def ofdm(fs: float, spacing_hz: float, cp_fraction: float, n_symbols: int,
         rng: np.random.Generator, *, occupied: float = 0.9) -> np.ndarray:
    """A generic OFDM signal: random QPSK on ``occupied`` of the carriers."""
    n_fft = round(fs / spacing_hz)
    n_cp = round(n_fft * cp_fraction)
    n_used = int(n_fft * occupied) // 2 * 2
    out = np.empty(n_symbols * (n_fft + n_cp), dtype=np.complex128)
    idx = np.concatenate([np.arange(n_fft // 2 - n_used // 2, n_fft // 2),
                          np.arange(n_fft // 2 + 1, n_fft // 2 + 1 + n_used // 2)])
    pos = 0
    for _ in range(n_symbols):
        spectrum = np.zeros(n_fft, dtype=np.complex128)
        bits = rng.integers(0, 2, (idx.size, 2))
        spectrum[idx] = ((1 - 2 * bits[:, 0]) + 1j * (1 - 2 * bits[:, 1])) / np.sqrt(2)
        body = np.fft.ifft(np.fft.ifftshift(spectrum)) * np.sqrt(n_fft)
        out[pos:pos + n_cp] = body[-n_cp:]
        out[pos + n_cp:pos + n_cp + n_fft] = body
        pos += n_cp + n_fft
    return (out / np.sqrt(np.mean(np.abs(out) ** 2))).astype(np.complex64)


def noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return ((rng.standard_normal(n) + 1j * rng.standard_normal(n))
            / np.sqrt(2)).astype(np.complex64)


FS = 20e6


def test_lag_and_alpha_of_each_numerology():
    assert cyclo.NUMEROLOGIES["ocusync_15k"].lag_samples(FS) == 1333
    assert cyclo.NUMEROLOGIES["ocusync_30k"].lag_samples(FS) == 667
    assert cyclo.NUMEROLOGIES["wifi"].lag_samples(FS) == 64
    # the 30 kHz numerology is a hypothesis, and says so
    assert not cyclo.NUMEROLOGIES["ocusync_30k"].verified
    assert cyclo.NUMEROLOGIES["wifi"].verified


def test_an_lte_numerology_signal_lights_the_15_khz_window_only():
    rng = np.random.default_rng(0)
    # 15 kHz spacing with a 1/14 prefix puts the line at 15e3 / (1 + 1/14) = 14 kHz
    x = ofdm(FS, 15e3, 1 / 14, 60, rng)
    profile = cyclo.cyclic_profile(x, FS, chunk_s=8e-3)
    lte = profile["ocusync_15k"]
    assert lte.alpha_hz == pytest.approx(14e3, rel=0.05)
    assert lte.contrast > 3.0
    assert lte.cp_fraction == pytest.approx(1 / 14, rel=0.1)
    assert profile["wifi"].contrast < lte.contrast


def test_a_wifi_numerology_signal_lights_the_250_khz_window():
    rng = np.random.default_rng(1)
    # 312.5 kHz spacing with a 1/4 prefix is 802.11a/g: 3.2 us plus 0.8 us
    x = ofdm(FS, 312.5e3, 0.25, 2000, rng)
    profile = cyclo.cyclic_profile(x, FS, chunk_s=4e-3)
    wifi = profile["wifi"]
    assert wifi.alpha_hz == pytest.approx(250e3, rel=0.05)
    assert wifi.contrast > 3.0
    assert profile["ocusync_15k"].contrast < wifi.contrast
    assert profile["ocusync_30k"].contrast < wifi.contrast


def test_the_30_khz_numerology_is_separable_from_the_15_khz_one():
    rng = np.random.default_rng(2)
    x30 = ofdm(FS, 30e3, 1 / 14, 120, rng)
    profile = cyclo.cyclic_profile(x30, FS, chunk_s=8e-3)
    assert profile["ocusync_30k"].alpha_hz == pytest.approx(28e3, rel=0.05)
    assert profile["ocusync_30k"].contrast > 3.0
    assert profile["ocusync_30k"].peak > profile["ocusync_15k"].peak


def test_noise_produces_no_line_anywhere():
    rng = np.random.default_rng(3)
    x = noise(400_000, rng)
    profile = cyclo.cyclic_profile(x, FS, chunk_s=8e-3)
    for result in profile.values():
        assert result.contrast < 3.0, result
        assert result.peak < 20 * cyclo.noise_floor_ncc(int(8e-3 * FS))


def test_the_noise_floor_formula_matches_measurement():
    rng = np.random.default_rng(4)
    n = 100_000
    ncc = cyclo.caf_ncc(noise(n, rng), 1333)
    assert float(np.mean(ncc[1:])) == pytest.approx(cyclo.noise_floor_ncc(n), rel=0.15)


def test_the_line_survives_a_low_duty_cycle_because_the_peak_is_weighted():
    rng = np.random.default_rng(5)
    burst = ofdm(FS, 15e3, 1 / 14, 30, rng)
    x = noise(500_000, rng)
    x[50_000:50_000 + burst.size] += burst * 3.0  # about 8 % duty cycle
    weighted = cyclo.cyclic_profile(x, FS, chunk_s=4e-3)["ocusync_15k"]
    averaged = cyclo.cyclic_profile(x, FS, chunk_s=4e-3, peak_weight=0.0)["ocusync_15k"]
    # Averaging dilutes the line across the chunks that hold only noise; the
    # peak weighting roughly doubles the statistic. Both find the same alpha,
    # so the difference is sensitivity, not correctness.
    assert weighted.peak > 1.8 * averaged.peak
    assert weighted.alpha_hz == pytest.approx(14e3, rel=0.05)
    assert weighted.alpha_hz == averaged.alpha_hz


def test_kurtosis_reference_values():
    rng = np.random.default_rng(6)
    assert cyclo.kurtosis(noise(200_000, rng)) == pytest.approx(cyclo.KAPPA_GAUSSIAN, abs=0.05)
    gated = noise(200_000, rng)
    gated[60_000:] = 0.0  # 30 % duty
    assert cyclo.kurtosis(gated) == pytest.approx(2.0 / 0.3, rel=0.05)
    tone = np.exp(2j * np.pi * 0.01 * np.arange(10_000)).astype(np.complex64)
    assert cyclo.kurtosis(tone) == pytest.approx(1.0, abs=1e-3)
    assert cyclo.kurtosis(np.zeros(100, np.complex64)) == 20.0
    with pytest.raises(ValueError):
        cyclo.kurtosis(np.zeros(0, np.complex64))


def test_result_serialises_and_reports_the_prefix_fraction():
    import json

    rng = np.random.default_rng(7)
    x = ofdm(FS, 15e3, 0.25, 60, rng)
    result = cyclo.cyclic_profile(x, FS, chunk_s=8e-3)["ocusync_15k"]
    assert result.cp_fraction == pytest.approx(0.25, rel=0.15)
    doc = json.loads(json.dumps(result.to_dict()))
    assert doc["name"] == "ocusync_15k" and doc["verified_numerology"] is True


def test_degenerate_inputs():
    assert cyclo.caf_ncc(np.zeros(10, np.complex64), 100).size == 0
    assert cyclo.caf_ncc(np.zeros(1000, np.complex64), 10).size == 0  # zero power
    with pytest.raises(ValueError):
        cyclo.caf_ncc(np.ones(100, np.complex64), 0)
    assert cyclo.peak_in_window(np.zeros(0), FS, (1e3, 2e3)) == (0.0, 0.0, 0.0)
    empty = cyclo.cyclic_profile(np.zeros(10, np.complex64), FS)
    assert all(r.peak == 0.0 for r in empty.values())
    with pytest.raises(ValueError):
        cyclo.cyclic_profile(np.ones(1000, np.complex64), FS, overlap=1.0)
