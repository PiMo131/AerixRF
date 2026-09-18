"""Tests for aerix_rf.datasets.resample (Workstream D, T2)."""

from __future__ import annotations

import numpy as np
import pytest

from aerix_rf.datasets.resample import (
    CANONICAL_RATE_HZ,
    apply_chain,
    chain_to_json,
    plan_chain,
    usable_bandwidth,
)


def _tone(rate_hz: float, freq_hz: float, n: int) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / rate_hz
    return np.exp(2j * np.pi * freq_hz * t).astype(np.complex128)


def _peak_bin_hz(x: np.ndarray, rate_hz: float) -> float:
    n = x.shape[-1]
    spec = np.fft.fftshift(np.fft.fft(x * np.hanning(n)))
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / rate_hz))
    return float(freqs[np.argmax(np.abs(spec))])


def _tone_power_ratio_db(x: np.ndarray, rate_hz: float, freq_hz: float) -> float:
    """dB level of the strongest bin near freq_hz relative to a full-scale tone's peak bin."""
    n = x.shape[-1]
    win = np.hanning(n)
    spec = np.fft.fftshift(np.fft.fft(x * win))
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / rate_hz))
    idx = np.argmin(np.abs(freqs - freq_hz))
    lo, hi = max(0, idx - 3), min(n, idx + 4)
    mag = np.max(np.abs(spec[lo:hi]))
    ref = np.sum(win)  # coherent gain of a full-scale unit tone
    return 20 * np.log10(max(mag, 1e-300) / ref)


def test_20msps_direct_single_stage():
    chain = plan_chain(20_000_000)
    assert len(chain) == 1
    assert chain[0].op == "rational"
    assert (chain[0].up, chain[0].down) == (96, 125)


def test_40msps_tone_within_one_bin_and_18mhz_suppressed():
    in_rate = 40_000_000.0
    n = 40_000_000  # 1.0 s
    tone3 = _tone(in_rate, 3_000_000.0, n)
    chain = plan_chain(in_rate)
    out = apply_chain(tone3, chain, in_rate)
    out_rate = CANONICAL_RATE_HZ
    bin_hz = out_rate / out.shape[-1]
    peak = _peak_bin_hz(out, out_rate)
    assert abs(peak - 3_000_000.0) <= bin_hz

    tone18 = _tone(in_rate, 18_000_000.0, n)
    out18 = apply_chain(tone18, chain, in_rate)
    # A full-scale in-band tone through the same chain is the 0 dB reference.
    ref = apply_chain(tone3, chain, in_rate)
    ref_db = _tone_power_ratio_db(ref, out_rate, 3_000_000.0)
    blocker_db = _tone_power_ratio_db(out18, out_rate, 18_000_000.0 - in_rate)  # aliased image search fallback
    # Search the whole output spectrum for the strongest residual bin instead
    # of a specific alias frequency: the 18 MHz tone must not survive at
    # anywhere near full strength.
    n_out = out18.shape[-1]
    spec = np.fft.fft(out18 * np.hanning(n_out))
    peak_mag = np.max(np.abs(spec))
    ref_spec = np.fft.fft(ref * np.hanning(n_out))
    ref_mag = np.max(np.abs(ref_spec))
    down_db = 20 * np.log10(max(peak_mag, 1e-300) / ref_mag)
    assert down_db <= -60.0


def test_apply_chain_deterministic_byte_identical():
    in_rate = 40_000_000.0
    n = 400_000
    rng = np.random.default_rng(0)
    iq = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex128)
    chain = plan_chain(in_rate)
    out1 = apply_chain(iq, chain, in_rate)
    out2 = apply_chain(iq, chain, in_rate)
    assert out1.dtype == np.complex64
    assert np.array_equal(out1.view(np.uint8), out2.view(np.uint8))


def test_canonical_to_canonical_is_recorded_noop():
    chain = plan_chain(CANONICAL_RATE_HZ)
    assert len(chain) >= 1
    assert all(s.op == "identity" for s in chain)
    iq = np.zeros(1000, dtype=np.complex128)
    iq[0] = 1.0
    out = apply_chain(iq, chain, CANONICAL_RATE_HZ)
    assert out.dtype == np.complex64
    assert np.array_equal(out, iq.astype(np.complex64))


def test_20msps_chain_single_9625_stage():
    chain = plan_chain(20_000_000)
    assert len(chain) == 1
    assert chain[0].up == 96 and chain[0].down == 125


@pytest.mark.parametrize(
    "in_rate,expected_decim,expected_frac",
    [
        (40_000_000, 2, (96, 125)),
        (50_000_000, 2, (384, 625)),
        (56_000_000, 2, (96, 175)),
        # Amendment (2026-09-18): the 60 MS/s override is removed; the
        # general "largest divisor keeping >=19.2 MS/s" rule now applies
        # uniformly, giving /3 -> 20 MS/s -> 96/125 (not the previous
        # /2 -> 64/125).
        (60_000_000, 3, (96, 125)),
        (61_440_000, 3, (3, 4)),
        (100_000_000, 5, (96, 125)),
        # Zenodo 4264467 (2020): 1.0 s @ 120 MS/s (2.4 GHz) and 0.5 s @
        # 200 MS/s (5.8 GHz), both int16 interleaved. Neither needs a new
        # special case -- the general rule already lands both on the same
        # 20 MS/s -> 96/125 finishing stage as 40/60/100 MS/s.
        (120_000_000, 6, (96, 125)),
        (200_000_000, 10, (96, 125)),
    ],
)
def test_known_rate_chains(in_rate, expected_decim, expected_frac):
    chain = plan_chain(float(in_rate))
    assert len(chain) == 2
    decim_stage, rational_stage = chain
    assert decim_stage.op == "decimate"
    assert decim_stage.down == expected_decim
    assert rational_stage.op == "rational"
    assert (rational_stage.up, rational_stage.down) == expected_frac


def test_band_deficit_flags_10msps_not_20msps():
    usable, deficit = usable_bandwidth(10_000_000.0)
    assert usable == 10_000_000.0
    assert deficit is True

    usable2, deficit2 = usable_bandwidth(20_000_000.0)
    assert usable2 == 12_000_000.0
    assert deficit2 is False


def test_1_second_at_40msps_yields_exact_canonical_sample_count():
    in_rate = 40_000_000.0
    n = 40_000_000  # exactly 1.000 s at 40 MS/s
    iq = _tone(in_rate, 1_000_000.0, n)
    chain = plan_chain(in_rate)
    out = apply_chain(iq, chain, in_rate)
    # Edge-sample convention: resample_poly's exact output length for
    # up/down resampling of an N-sample input is ceil(N * up / down); for
    # the two-stage 40 MS/s chain (decimate 2 -> 20e6, then 96/125) applied
    # to an exact 1.000 s input this lands exactly on the canonical count.
    assert out.shape[-1] == 15_360_000


def test_chain_to_json_round_trips_design_params():
    chain = plan_chain(50_000_000.0)
    dumped = chain_to_json(chain)
    assert isinstance(dumped, list)
    assert dumped[0]["op"] == "decimate"
    assert "numtaps" in dumped[0]
    assert "window" in dumped[0] and "kaiser" in dumped[0]["window"]
    assert dumped[1]["op"] == "rational"
    assert dumped[1]["up"] == 384 and dumped[1]["down"] == 625


def test_complex64_dtype_out():
    in_rate = 60_000_000.0
    iq = _tone(in_rate, 1_000_000.0, 60_000)
    chain = plan_chain(in_rate)
    out = apply_chain(iq, chain, in_rate)
    assert out.dtype == np.complex64


def test_live_grade_recorded_and_differs_from_dataset_grade():
    """F5 live-latency task: grade='live' plans a distinct (50 dB stopband,
    1.0 MHz transition) chain, with 'grade' recorded per stage; grade
    defaults to 'dataset' and that default chain is completely unchanged
    (numtaps/window/cutoff/stopband_db all identical to before this field
    existed)."""
    chain_dataset = plan_chain(20_000_000.0)
    assert all(s.grade in (None, "dataset") for s in chain_dataset)
    assert chain_dataset[0].stopband_db == 60.0

    chain_live = plan_chain(20_000_000.0, grade="live")
    assert chain_live[0].grade == "live"
    assert chain_live[0].stopband_db == 50.0
    # Recorded distinctly -- may have more or fewer taps than dataset grade
    # depending on the up-factor (see F5 result packet); just must not be
    # silently identical.
    assert chain_live[0].numtaps != chain_dataset[0].numtaps


def test_live_grade_invalid_value_rejected():
    with pytest.raises(ValueError):
        plan_chain(20_000_000.0, grade="bogus")
