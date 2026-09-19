"""Tests for aerix_rf.dsp.ofdm_sim (synthetic Wi-Fi-like OFDM / BLE-like GFSK).

Evidence level 1 (synthetic): these check the generator's own internal
consistency (spectral occupancy, preamble periodicity, scene truth-record
bookkeeping, determinism, GFSK deviation) -- they are ground-truth checks
on the model, not validation against a real Wi-Fi or BLE radio. See
``aerix_rf/dsp/ofdm_sim.py`` module docstring for the preamble-sequence
provenance caveats (STF/LTF transcribed from memory, high-confidence but
not independently verified against the primary standard in this task).
"""

from __future__ import annotations

import numpy as np
import pytest

from aerix_rf.dsp.ofdm_sim import make_ble_like_scene, make_ofdm_burst, make_wifi_like_scene


def _psd(iq: np.ndarray, fs: float):
    n = len(iq)
    spec = np.abs(np.fft.fftshift(np.fft.fft(iq))) ** 2
    freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / fs))
    return freqs, spec


def test_ofdm_burst_spectral_mask_at_40msps():
    # 20 MHz Wi-Fi-like channel observed at 40 MS/s (2x oversampled at the
    # capture rate) so the full occupied band is unaliased.
    fs = 40e6
    iq = make_ofdm_burst(fs, 50e-6, bw_hz=20e6, seed=1)
    assert iq.dtype == np.complex64
    freqs, spec = _psd(iq, fs)
    total = float(spec.sum())

    # >=90% of power inside +-(bw/2 * n_used/n_fft + 1 MHz).
    bw_half = 20e6 / 2.0 * 52.0 / 64.0 + 1e6
    inband = float(spec[np.abs(freqs) <= bw_half].sum())
    assert inband / total >= 0.90

    # <=-20 dB average outside +-bw/2 (10 MHz).
    outband_mean = float(spec[np.abs(freqs) > 10e6].mean())
    overall_mean = float(spec.mean())
    assert 10.0 * np.log10(outband_mean / overall_mean) <= -20.0


def test_ofdm_burst_runs_at_canonical_undersampled_rate():
    # NOTE: 15.36 MS/s is well below the 20 MHz Wi-Fi channel bandwidth, so
    # this is an intentionally undersampled/aliased capture -- only checked
    # for a finite, well-typed result, not a spectral mask. A 20 MHz-wide
    # OFDM channel is not fully representable at this canonical AERIX rate;
    # only the portion that survives aliasing into the passband is usable
    # by any detector running at this rate.
    iq = make_ofdm_burst(15.36e6, 20e-6, bw_hz=20e6, seed=2)
    assert iq.dtype == np.complex64
    assert len(iq) > 0
    assert np.all(np.isfinite(iq))


def test_preamble_autocorrelation_peak_at_short_training_period():
    # At the native 20 MS/s rate (no resampling), the short training field
    # is periodic with a 16-sample (0.8 us) period; lag-16 autocorrelation
    # over the STF should show a clear peak (normalised magnitude near 1).
    iq = make_ofdm_burst(20e6, 16e-6, bw_hz=20e6, preamble=True, seed=3)
    stf = iq[:160].astype(np.complex128)  # 8 us STF region, see module docstring
    denom = float(np.mean(np.abs(stf) ** 2)) * len(stf)

    def norm_ac(lag: int) -> float:
        return abs(np.vdot(stf[:-lag], stf[lag:])) / denom

    ac16 = norm_ac(16)
    others = [norm_ac(lag) for lag in range(1, 40) if lag != 16]
    assert ac16 > 0.5
    assert ac16 >= max(others) - 1e-9  # lag 16 is the (tied-)largest peak in range


def test_wifi_scene_beacon_count_matches_period():
    window_s = 2.0
    beacon_period_s = 0.1024
    _, events = make_wifi_like_scene(
        20e6, window_s, beacon_period_s=beacon_period_s, beacon_len_s=200e-6,
        duty=0.0, seed=4,
    )
    beacons = [e for e in events if e[3] == "beacon"]
    expected = window_s / beacon_period_s
    assert abs(len(beacons) - expected) <= 2


def test_wifi_scene_deterministic_with_seed():
    iq_a, ev_a = make_wifi_like_scene(20e6, 0.5, seed=42)
    iq_b, ev_b = make_wifi_like_scene(20e6, 0.5, seed=42)
    assert np.array_equal(iq_a, iq_b)
    assert ev_a == ev_b


def test_ofdm_burst_deterministic_with_seed():
    a = make_ofdm_burst(20e6, 30e-6, seed=7)
    b = make_ofdm_burst(20e6, 30e-6, seed=7)
    c = make_ofdm_burst(20e6, 30e-6, seed=8)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_ble_scene_packet_deviation_near_250khz():
    fs = 20e6
    iq, events = make_ble_like_scene(fs, 0.02, seed=6)
    assert events, "expected at least one BLE-like packet in a 20 ms window"
    t_start, t_end, offset_hz, kind = events[0]
    assert kind == "ble_packet"
    i0, i1 = int(round(t_start * fs)), int(round(t_end * fs))
    seg = iq[i0:i1].astype(np.complex128) * np.exp(
        -1j * 2.0 * np.pi * offset_hz * np.arange(i1 - i0) / fs
    )
    inst_hz = np.diff(np.unwrap(np.angle(seg))) * fs / (2.0 * np.pi)
    # Symbol-period (1 Mb/s -> 20 samples/symbol at 20 MS/s) moving-average
    # matched filter, as in aerix_rf.decode.sik.gfsk's post-detection step,
    # to see the settled +-deviation modes rather than raw discriminator noise.
    w = int(round(fs / 1e6))
    smoothed = np.convolve(inst_hz, np.ones(w) / w, mode="valid")
    lo, hi = np.percentile(smoothed, [5, 95])
    assert 200e3 <= hi <= 300e3
    assert -300e3 <= lo <= -200e3


def test_ble_scene_runs_with_default_channel_count():
    iq, events = make_ble_like_scene(20e6, 0.01, seed=9)
    assert iq.dtype == np.complex64
    assert np.all(np.isfinite(iq))
    assert all(e[3] == "ble_packet" for e in events)
