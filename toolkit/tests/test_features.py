"""Tests for antsdr_toolkit.dsp.features (burst-set statistics), hand-built and synthetic."""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.dsp import bursts as bu
from antsdr_toolkit.dsp import features as ft
from antsdr_toolkit.dsp import spectrum as sp

FC = 2.44e9


def _b(t0: float, t1: float, f0: float, f1: float, snr: float = 20.0) -> bu.Burst:
    return bu.Burst(t0, t1, f0, f1, peak_db=-50.0, mean_db=-55.0, snr_db=snr)


# --------------------------------------------------------------------------- unit level


def test_empty_and_single_burst_features():
    empty = ft.burst_features([], window_s=1.0)
    assert empty.n_bursts == 0 and empty.window_s == 1.0
    assert all(v == 0 for k, v in empty.to_dict().items() if k != "window_s")
    assert empty.to_dict()["duty_cycle"] == 0.0
    assert empty.n_distinct_centers == 0

    one = ft.burst_features([_b(0.1, 0.3, 1e9, 1.002e9, snr=12.5)], window_s=1.0)
    assert one.n_bursts == 1
    assert one.duty_cycle == pytest.approx(0.2)
    assert one.bandwidth_median_hz == one.bandwidth_p10_hz == one.bandwidth_p90_hz == 2e6
    assert one.duration_median_s == pytest.approx(0.2)
    assert one.interval_median_s == 0.0 and one.interval_cv == 0.0  # undefined -> 0
    assert one.n_distinct_centers == 1 and one.center_spacing_median_hz == 0.0
    assert one.hop_rate_hz == 0.0
    assert one.occupied_span_hz == pytest.approx(2e6)
    assert one.snr_median_db == 12.5
    d = one.to_dict()
    assert set(d) == {
        "n_bursts", "window_s", "duty_cycle", "bandwidth_median_hz", "bandwidth_p10_hz",
        "bandwidth_p90_hz", "duration_median_s", "duration_p10_s", "duration_p90_s",
        "interval_median_s", "interval_cv", "n_distinct_centers", "center_spacing_median_hz",
        "hop_rate_hz", "occupied_span_hz", "snr_median_db",
    }
    assert all(np.isfinite(v) for v in d.values())


def test_periodic_bursts_intervals_duty_cycle_and_percentiles():
    # 10 bursts every 10 ms, 2 ms long, one centre, bandwidths 1..10 MHz
    bursts = [_b(k * 10e-3, k * 10e-3 + 2e-3, 1e9 - (k + 1) * 0.5e6, 1e9 + (k + 1) * 0.5e6)
              for k in range(10)]
    f = ft.burst_features(bursts[::-1], window_s=0.1)  # order must not matter
    assert f.n_bursts == 10
    assert f.duty_cycle == pytest.approx(0.2)
    assert f.interval_median_s == pytest.approx(10e-3)
    assert f.interval_cv == pytest.approx(0.0, abs=1e-9)
    assert f.duration_median_s == pytest.approx(2e-3)
    assert f.duration_p10_s == pytest.approx(2e-3) and f.duration_p90_s == pytest.approx(2e-3)
    bw = np.arange(1, 11) * 1e6
    assert f.bandwidth_median_hz == pytest.approx(np.median(bw))
    assert f.bandwidth_p10_hz == pytest.approx(np.percentile(bw, 10))
    assert f.bandwidth_p90_hz == pytest.approx(np.percentile(bw, 90))
    assert f.n_distinct_centers == 1 and f.hop_rate_hz == 0.0
    assert f.occupied_span_hz == pytest.approx(10e6)

    # jittered intervals give a positive CV; overlapping bursts count once in the duty cycle
    jitter = [_b(t, t + 1e-3, 1e9, 1.001e9) for t in (0.0, 0.010, 0.025, 0.030, 0.050)]
    fj = ft.burst_features(jitter, window_s=0.1)
    iv = np.diff([0.0, 0.010, 0.025, 0.030, 0.050])
    assert fj.interval_cv == pytest.approx(np.std(iv) / np.mean(iv))
    assert fj.interval_median_s == pytest.approx(np.median(iv))
    overlapping = [_b(0.0, 0.5, 1e9, 1.1e9), _b(0.25, 0.75, 1.2e9, 1.3e9), _b(0.9, 1.5, 1e9, 1.1e9)]
    assert ft.occupied_fraction(overlapping, 1.0) == pytest.approx(0.85)  # 0..0.75 + 0.9..1.0
    assert ft.burst_features(overlapping, window_s=1.0).duty_cycle == pytest.approx(0.85)
    assert ft.occupied_fraction(overlapping, 0.0) == 0.0
    assert ft.occupied_fraction([], 1.0) == 0.0


def test_cluster_centers_greedy_tolerance():
    centers = [1.0e6, 1.1e6, 1.2e6, 1.3e6, 5.0e6, 0.9e6]
    labels, means = ft.cluster_centers(centers, 250e3)
    # sorted: 0.9, 1.0, 1.1 | 1.2, 1.3 | 5.0  (each cluster spans at most the tolerance)
    assert labels.tolist() == [0, 0, 1, 1, 2, 0]
    assert means.tolist() == pytest.approx([1.0e6, 1.25e6, 5.0e6])
    assert np.all(np.diff(means) > 0)
    labels0, means0 = ft.cluster_centers(centers, 0.0)
    assert len(means0) == 6 and sorted(labels0.tolist()) == list(range(6))
    labels_big, means_big = ft.cluster_centers(centers, 10e6)
    assert np.all(labels_big == 0) and means_big.shape == (1,)
    labels_e, means_e = ft.cluster_centers([], 1.0)
    assert labels_e.shape == (0,) and means_e.shape == (0,)


def test_hop_rate_counts_distinct_center_changes_over_the_span():
    # alternate between two channels every 4 ms: 9 bursts, 8 changes over 32 ms -> 250 /s
    two = [_b(k * 4e-3, k * 4e-3 + 2e-3, 1e9 + (k % 2) * 2e6, 1e9 + (k % 2) * 2e6 + 1e6)
           for k in range(9)]
    f = ft.burst_features(two, window_s=1.0)  # independent of the window length
    assert f.n_distinct_centers == 2
    assert f.hop_rate_hz == pytest.approx(250.0)
    assert f.center_spacing_median_hz == pytest.approx(2e6)
    # small centre jitter within the tolerance is the same channel
    jittered = [bu.Burst(b.t_start_s, b.t_end_s, b.f_low_hz + (k % 3) * 40e3,
                         b.f_high_hz + (k % 3) * 40e3, -50.0, -55.0, 20.0)
                for k, b in enumerate(two)]
    assert ft.burst_features(jittered, window_s=1.0).n_distinct_centers == 2
    tight = ft.burst_features(jittered, window_s=1.0, center_tolerance_hz=10e3)
    assert tight.n_distinct_centers > 2
    # a repeat on the same channel is not a hop
    same = two[:1] + [bu.Burst(4e-3, 6e-3, two[0].f_low_hz, two[0].f_high_hz, -50.0, -55.0, 20.0)]
    assert ft.burst_features(same, window_s=1.0).hop_rate_hz == 0.0


def test_bursts_to_table():
    bursts = [_b(0.0, 1e-3, 1e9, 1.001e9), _b(2e-3, 3e-3, 1.1e9, 1.102e9, snr=5.0)]
    table = ft.bursts_to_table(bursts)
    assert len(table) == 2 and table[0] == bursts[0].to_dict()
    assert table[1]["bandwidth_hz"] == pytest.approx(2e6) and table[1]["snr_db"] == 5.0
    assert ft.bursts_to_table([]) == []


# --------------------------------------------------------------------------- scenes


@pytest.mark.parametrize("order", ["sequential", "random"])
def test_fhss_scene_features(order: str):
    """(2) 8 channels, 250 hops/s for 100 ms -> ~25 bursts on 8 distinct centres."""
    fs = 20e6
    rng = np.random.default_rng(2)
    channels = [-7e6, -5e6, -3e6, -1e6, 1e6, 3e6, 5e6, 7e6]
    scene = syn.Scene(fs, FC, 100e-3, rng, noise_power_db=-60.0)
    emissions = scene.fhss(
        lambda d: syn.bandlimited_noise_burst(fs, 1e6, d, rng),
        channels_hz=channels, hop_rate_hz=250.0, burst_duration_s=2e-3,
        t_start_s=1e-3, t_end_s=100e-3, snr_db=15.0, label="fhss", order=order,
    )
    assert len(emissions) == 25
    found = bu.detect_bursts_from_iq(
        scene.render(), fs, FC, fft_size=1024, threshold_db=10.0,
        min_duration_s=100e-6, min_bandwidth_hz=200e3,
    )
    assert 23 <= len(found) <= 27
    f = ft.burst_features(found, window_s=scene.duration_s, center_tolerance_hz=250e3)
    assert f.n_bursts == len(found)
    assert f.n_distinct_centers == 8
    assert f.center_spacing_median_hz == pytest.approx(2e6, rel=0.10)
    assert f.occupied_span_hz == pytest.approx(15e6, rel=0.05)
    assert f.bandwidth_median_hz == pytest.approx(1e6, rel=0.15)
    assert f.duration_median_s == pytest.approx(2e-3, rel=0.10)
    assert f.interval_median_s == pytest.approx(4e-3, rel=0.05)
    assert f.interval_cv < 0.05
    assert f.duty_cycle == pytest.approx(0.5, abs=0.05)
    if order == "sequential":
        # every hop changes channel: the rate of distinct-centre changes is the hop rate
        assert abs(f.hop_rate_hz - 250.0) <= 0.2 * 250.0
    else:
        # random draws repeat a channel 1/8 of the time, so fewer *changes* than hops
        assert 0.7 * 250.0 <= f.hop_rate_hz <= 250.0
    assert 10.0 < f.snr_median_db < 30.0


def test_fm_video_like_carrier_is_one_continuous_burst():
    """(3) a continuous wideband FM carrier: duty cycle ~1, bandwidth close to Carson's rule."""
    fs = 30.72e6
    rng = np.random.default_rng(3)
    dev, bb = 4e6, 2e6
    carson = 2 * (dev + bb)
    scene = syn.Scene(fs, FC, 20e-3, rng, noise_power_db=-60.0)
    fm = syn.fm_video_like(fs, 22e-3, rng, deviation_hz=dev, baseband_bw_hz=bb)
    scene.add(fm, t_start_s=-1e-3, freq_offset_hz=1e6, snr_db=20.0, label="fpv")
    x = scene.render()
    power_db, freqs_hz, times_s = sp.stft_power_db(x, fs, FC, fft_size=1024)

    # the spectral skirts flicker in and out of the mask as short fragments; a
    # min duration keeps only the carrier body
    found = bu.detect_bursts(power_db, freqs_hz, times_s, threshold_db=10.0,
                             min_duration_s=1e-3)
    assert len(found) == 1
    body = found[0]
    f = ft.burst_features(found, window_s=scene.duration_s)
    assert f.duty_cycle > 0.99
    assert body.t_start_s < 0.1e-3 and body.t_end_s > scene.duration_s - 0.1e-3
    assert 0.8 * carson <= f.bandwidth_median_hz <= 1.1 * carson
    assert f.occupied_span_hz == f.bandwidth_median_hz
    assert abs(body.center_freq_hz - (FC + 1e6)) < 200e3
    assert f.n_distinct_centers == 1 and f.hop_rate_hz == 0.0
    assert body.snr_db > 20.0

    # documented weakness: a pure per-bin temporal floor tracks a carrier present in
    # every frame, making it invisible
    assert bu.detect_bursts(power_db, freqs_hz, times_s, threshold_db=10.0,
                            min_duration_s=1e-3, floor_ripple_db=None) == []

    # a default 24 MHz FPV-like carrier filling 78 % of the dwell is still one burst
    wide_scene = syn.Scene(fs, FC, 10e-3, np.random.default_rng(31), noise_power_db=-60.0)
    wide = syn.fm_video_like(fs, 11e-3, np.random.default_rng(32))
    wide_scene.add(wide, t_start_s=-0.5e-3, freq_offset_hz=0.0, snr_db=20.0, label="fpv24")
    found_wide = bu.detect_bursts_from_iq(wide_scene.render(), fs, FC, fft_size=1024,
                                          threshold_db=10.0, min_duration_s=1e-3)
    assert len(found_wide) == 1
    assert 0.7 * 24e6 <= found_wide[0].bandwidth_hz <= 1.05 * 24e6
    assert ft.burst_features(found_wide, window_s=wide_scene.duration_s).duty_cycle > 0.99
