"""Tests for antsdr_toolkit.dsp.bursts: the STFT energy burst detector on synthetic ground truth."""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.dsp import bursts as bu
from antsdr_toolkit.dsp import spectrum as sp

FC = 2.44e9


def _noise_map(rng: np.random.Generator, frames: int, bins: int, mean_db: float) -> np.ndarray:
    """dB map of complex-Gaussian noise: per-cell linear power is exponential."""
    return sp.db(rng.exponential(10 ** (mean_db / 10), size=(frames, bins))).astype(np.float32)


def _errors_in_cells(burst: bu.Burst, truth: dict, dt: float, df: float) -> np.ndarray:
    """Signed edge errors (start, end, low, high) in units of one STFT cell."""
    return np.array(
        [
            (burst.t_start_s - truth["t_start_s"]) / dt,
            (burst.t_end_s - truth["t_end_s"]) / dt,
            (burst.f_low_hz - truth["f_low_hz"]) / df,
            (burst.f_high_hz - truth["f_high_hz"]) / df,
        ]
    )


# --------------------------------------------------------------------------- unit level


def test_burst_dataclass_properties_and_dict():
    b = bu.Burst(1.0, 1.5, 2.4e9, 2.41e9, peak_db=-40.0, mean_db=-50.0, snr_db=25.0)
    assert b.duration_s == pytest.approx(0.5)
    assert b.bandwidth_hz == pytest.approx(10e6)
    assert b.center_freq_hz == pytest.approx(2.405e9)
    d = b.to_dict()
    assert d["t_start_s"] == 1.0 and d["snr_db"] == 25.0
    assert d["duration_s"] == pytest.approx(0.5) and d["center_freq_hz"] == pytest.approx(2.405e9)
    with pytest.raises(AttributeError):
        b.t_start_s = 0.0  # frozen


def test_closing_structure_bridges_requested_gaps():
    dt, df = 25.6e-6, 19531.25
    assert bu.closing_structure(0.0, 0.0, dt, df) is None
    s = bu.closing_structure(150e-6, 0.0, dt, df)
    assert s.shape == (7, 1) and s.dtype == bool  # bridges 6 frames = 154 us >= 150 us
    s = bu.closing_structure(0.0, 500e3, dt, df)
    assert s.shape == (1, 27)  # bridges 26 bins = 508 kHz >= 500 kHz
    assert bu.closing_structure(2 * dt, 2 * df, dt, df).shape == (3, 3)
    # an axis without spacing (single frame) cannot be closed
    assert bu.closing_structure(1e-3, 0.0, 0.0, df) is None


def test_detect_bursts_on_synthetic_map_exact_box_and_floor_variants():
    rng = np.random.default_rng(10)
    frames, bins = 200, 128
    p = _noise_map(rng, frames, bins, -70.0)
    p[50:80, 30:60] += 20.0  # a 30-frame x 30-bin block at 20 dB SNR
    times = np.arange(frames) * 1e-3 + 0.5e-3  # dt = 1 ms
    freqs = FC + (np.arange(bins) - 64) * 1e4  # df = 10 kHz

    for floor in (None, -70.0, np.full(bins, -70.0), np.full((frames, bins), -70.0)):
        found = bu.detect_bursts(
            p, freqs, times, threshold_db=10.0, noise_floor_db=floor,
            min_duration_s=2e-3, min_bandwidth_hz=2e4,
        )
        assert len(found) == 1
        b = found[0]
        # cell-edge convention: frame centre -/+ dt/2, bin centre -/+ df/2
        assert b.t_start_s == pytest.approx(50e-3) and b.t_end_s == pytest.approx(80e-3)
        assert b.f_low_hz == pytest.approx(FC - 34 * 1e4 - 0.5e4)
        assert b.f_high_hz == pytest.approx(FC - 5 * 1e4 + 0.5e4)
        assert b.duration_s == pytest.approx(30e-3) and b.bandwidth_hz == pytest.approx(30e4)
        # the box mean is the signal level; the peak SNR is biased above 20 dB by the
        # maximum over 900 exponential cells (~+7 dB), never below the true SNR
        assert b.mean_db == pytest.approx(-50.0, abs=1.0)
        assert 20.0 <= b.snr_db <= 32.0
        assert b.peak_db > b.mean_db

    # the block is missed when it fills the map in time (floor tracks it) ...
    full = _noise_map(rng, frames, bins, -70.0)
    full[:, 30:60] += 20.0
    assert bu.detect_bursts(full, freqs, times, floor_ripple_db=None) == []
    # ... but the band-wide clamp of the default floor rescues the continuous carrier
    carrier = bu.detect_bursts(full, freqs, times, min_duration_s=10e-3, min_bandwidth_hz=1e5)
    assert len(carrier) == 1 and carrier[0].bandwidth_hz == pytest.approx(30e4)
    assert carrier[0].duration_s == pytest.approx(frames * 1e-3)

    # validation and degenerate input
    assert bu.detect_bursts(np.zeros((0, 4), np.float32), np.arange(4.0), np.zeros(0)) == []
    with pytest.raises(ValueError):
        bu.detect_bursts(p[:, :100], freqs, times)
    with pytest.raises(ValueError):
        bu.detect_bursts(p[0], freqs, times)
    with pytest.raises(ValueError):
        bu.detect_bursts(p, freqs, times, noise_floor_db=np.zeros((1, 1, 1)))
    one_frame = bu.detect_bursts(p[60:61], freqs, times[60:61], noise_floor_db=-70.0)
    assert len(one_frame) >= 1 and all(b.duration_s == 0.0 for b in one_frame)


def test_robust_noise_floor_clamps_persistently_occupied_bins():
    rng = np.random.default_rng(11)
    frames, bins = 1000, 256  # enough frames for the percentile estimate to settle within ~1 dB
    p = _noise_map(rng, frames, bins, -70.0)
    p[:, 100:176] += 20.0  # continuous carrier over 30 % of the band
    p[:, 200] += 4.0  # a weak persistent spur, within the allowed ripple

    floor = bu.robust_noise_floor_db(p)
    assert floor.shape == (bins,)
    assert np.abs(floor[:100] - (-70.0)).max() < 1.5  # bias-corrected to the mean noise
    assert np.abs(floor[100:176] - (-70.0)).max() < 1.5  # carrier bins fall back to the band
    assert floor[200] == pytest.approx(-66.0, abs=1.5)  # the spur keeps its own floor

    raw = bu.robust_noise_floor_db(p, ripple_db=None)
    assert np.abs(raw[100:176] - (-50.0)).max() < 1.5  # pure per-bin semantics
    assert np.array_equal(raw[:100], floor[:100])
    with pytest.raises(ValueError):
        bu.robust_noise_floor_db(p[0])


# --------------------------------------------------------------------------- scenes


def test_three_ofdm_bursts_are_boxed_within_one_cell_and_no_false_alarms():
    """(1) 3 x 10 MHz / 600 us OFDM-like bursts at 20 dB in a 30.72 MHz scene."""
    fs = 30.72e6
    rng = np.random.default_rng(1)
    scene = syn.Scene(fs, FC, 10e-3, rng, noise_power_db=-60.0)
    plan = [(1e-3, -8e6), (4e-3, 0.0), (7e-3, 8e6)]
    for t0, off in plan:
        burst = syn.bandlimited_noise_burst(fs, 10e6, 600e-6, rng)
        scene.add(burst, t_start_s=t0, freq_offset_hz=off, snr_db=20.0, label="ofdm",
                  bandwidth_hz=10e6)
    x = scene.render()
    truth = scene.truth_bursts()

    # 120 kHz bins / 4.2 us hops: coarser than the burst's own 4 % spectral roll-off and
    # PA ramps, so every edge is resolvable to one cell
    power_db, freqs_hz, times_s = sp.stft_power_db(x, fs, FC, fft_size=256)
    dt, df = times_s[1] - times_s[0], freqs_hz[1] - freqs_hz[0]
    found = bu.detect_bursts(
        power_db, freqs_hz, times_s, threshold_db=10.0,
        min_duration_s=3 * dt, min_bandwidth_hz=3 * df,
    )
    assert len(found) == 3
    assert [b.t_start_s for b in found] == sorted(b.t_start_s for b in found)
    for b, tr in zip(found, truth):
        err = _errors_in_cells(b, tr, dt, df)
        assert np.all(np.abs(err) <= 1.0), err
        assert bu.time_freq_iou(b, tr) > 0.8
        assert b.snr_db > 20.0
    # nothing in the empty region (after the last burst, and between bursts)
    assert all(b.t_end_s < 7.8e-3 for b in found)
    assert not any(2e-3 < b.t_start_s < 3.9e-3 for b in found)

    # without the size filters the only extras are isolated false-alarm cells at the
    # rate predicted for exponential noise: exp(-10) ~ 4.5e-5 per cell
    unfiltered = bu.detect_bursts(power_db, freqs_hz, times_s, threshold_db=10.0)
    extras = [b for b in unfiltered if max(bu.time_freq_iou(b, tr) for tr in truth) < 0.5]
    assert len(unfiltered) == 3 + len(extras)
    expected = power_db.size * np.exp(-10.0)
    assert 0.2 * expected < len(extras) < 4 * expected + 5
    assert all(b.duration_s <= 2 * dt and b.bandwidth_hz <= 2 * df for b in extras)

    # finer bins resolve the burst's roll-off instead: boxes shrink by a few bins (well
    # inside the 400 kHz transition) and wide bursts trigger a frame early - the
    # documented fft_size sensitivity
    p2, f2, t2 = sp.stft_power_db(x, fs, FC, fft_size=1024)
    dt2, df2 = t2[1] - t2[0], f2[1] - f2[0]
    fine = bu.detect_bursts(p2, f2, t2, threshold_db=10.0, min_duration_s=3 * dt2,
                            min_bandwidth_hz=3 * df2)
    assert len(fine) == 3
    for b, tr in zip(fine, truth):
        err = _errors_in_cells(b, tr, dt2, df2)
        assert np.all(np.abs(err[:2]) <= 2.0), err
        assert err[2] >= -1.0 and err[3] <= 1.0  # never wider than the truth + 1 cell
        assert abs(err[2]) * df2 < 400e3 and abs(err[3]) * df2 < 400e3
        assert bu.time_freq_iou(b, tr) > 0.9


def test_low_snr_bursts_missed_at_10_db_found_at_2_db():
    """(4) 3 dB bursts: the threshold / min-size trade-off described in the module docstring."""
    fs = 20e6
    rng = np.random.default_rng(4)
    scene = syn.Scene(fs, FC, 12e-3, rng, noise_power_db=-60.0)
    for t0, off in [(2e-3, -4e6), (8e-3, 5e6)]:
        weak = syn.bandlimited_noise_burst(fs, 5e6, 1e-3, rng)
        scene.add(weak, t_start_s=t0, freq_offset_hz=off, snr_db=3.0, label="weak",
                  bandwidth_hz=5e6)
    x = scene.render()
    truth = scene.truth_bursts()
    power_db, freqs_hz, times_s = sp.stft_power_db(x, fs, FC, fft_size=1024)

    # at 10 dB a 3 dB burst lights up only exp(-10/3) = 3.6 % of its cells: isolated
    # specks that the size filters discard -> missed
    strict = bu.detect_bursts(power_db, freqs_hz, times_s, threshold_db=10.0,
                              min_duration_s=300e-6, min_bandwidth_hz=2e6)
    assert strict == []
    specks = bu.detect_bursts(power_db, freqs_hz, times_s, threshold_db=10.0)
    assert all(max(bu.time_freq_iou(b, tr) for tr in truth) < 0.1 for b in specks)

    # at 2 dB 59 % of the burst cells exceed (above the 8-connected percolation density)
    # so the mask joins into one ragged component per burst; the min sizes are set looser
    # than the true 5 MHz x 1 ms extent because weak bursts fragment and shrink
    loose = bu.detect_bursts(power_db, freqs_hz, times_s, threshold_db=2.0,
                             min_duration_s=300e-6, min_bandwidth_hz=2e6)
    pairs, false_alarms, missed = bu.match_bursts(loose, truth, min_iou=0.5)
    assert len(pairs) == 2 and missed == [] and false_alarms == []
    for i, j in pairs:
        assert 0.6 * 5e6 < loose[i].bandwidth_hz < 1.3 * 5e6
        assert 0.6e-3 < loose[i].duration_s < 1.6e-3
        true_center = 0.5 * (truth[j]["f_low_hz"] + truth[j]["f_high_hz"])
        assert abs(loose[i].center_freq_hz - true_center) < 500e3

    # the price: without size filters a 2 dB threshold makes ~20 % of all noise cells
    # light up, i.e. thousands of clutter components
    clutter = bu.detect_bursts(power_db, freqs_hz, times_s, threshold_db=2.0)
    assert len(clutter) > 1000


def test_closing_merges_bursts_fragmented_in_time_and_frequency():
    """(5) close_time_s / close_freq_hz bridge gaps the STFT mask leaves inside one burst."""
    fs = 20e6
    rng = np.random.default_rng(5)
    scene = syn.Scene(fs, FC, 8e-3, rng, noise_power_db=-60.0)
    # a burst with a 100 us dropout in the middle (two 300 us halves)
    for t0 in (2e-3, 2.4e-3):
        half = syn.bandlimited_noise_burst(fs, 2e6, 300e-6, rng)
        scene.add(half, t_start_s=t0, freq_offset_hz=-5e6, snr_db=20.0, label="dropout",
                  bandwidth_hz=2e6)
    # a burst with a 400 kHz guard notch (two 1 MHz sub-bands)
    for off in (4e6 - 0.7e6, 4e6 + 0.7e6):
        sub = syn.bandlimited_noise_burst(fs, 1e6, 500e-6, rng)
        scene.add(sub, t_start_s=5e-3, freq_offset_hz=off, snr_db=20.0, label="notch",
                  bandwidth_hz=1e6)
    x = scene.render()
    power_db, freqs_hz, times_s = sp.stft_power_db(x, fs, FC, fft_size=1024)
    dt, df = times_s[1] - times_s[0], freqs_hz[1] - freqs_hz[0]
    common = dict(threshold_db=10.0, min_duration_s=3 * dt, min_bandwidth_hz=3 * df)

    plain = bu.detect_bursts(power_db, freqs_hz, times_s, **common)
    assert len(plain) == 4
    dropout = [b for b in plain if b.center_freq_hz < FC]
    notch = [b for b in plain if b.center_freq_hz > FC]
    assert len(dropout) == 2 and len(notch) == 2
    assert 50e-6 < dropout[1].t_start_s - dropout[0].t_end_s < 150e-6
    assert 200e3 < notch[1].f_low_hz - notch[0].f_high_hz < 500e3

    in_time = bu.detect_bursts(power_db, freqs_hz, times_s, close_time_s=150e-6, **common)
    assert len(in_time) == 3
    merged = [b for b in in_time if b.center_freq_hz < FC]
    assert len(merged) == 1
    assert merged[0].t_start_s == pytest.approx(dropout[0].t_start_s)
    assert merged[0].t_end_s == pytest.approx(dropout[1].t_end_s)
    assert merged[0].duration_s == pytest.approx(700e-6, abs=2 * dt)
    assert merged[0].bandwidth_hz == pytest.approx(2e6, abs=3 * df)

    in_freq = bu.detect_bursts(power_db, freqs_hz, times_s, close_freq_hz=500e3, **common)
    assert len([b for b in in_freq if b.center_freq_hz > FC]) == 1
    both = bu.detect_bursts(power_db, freqs_hz, times_s, close_time_s=150e-6,
                            close_freq_hz=500e3, **common)
    assert len(both) == 2
    wide = [b for b in both if b.center_freq_hz > FC][0]
    # the merged box spans both sub-bands; closing may also bridge a stray false-alarm
    # cell within close_freq_hz of the burst, inflating the box by up to that much
    assert notch[0].f_low_hz - 500e3 <= wide.f_low_hz <= notch[0].f_low_hz + df / 2
    assert notch[1].f_high_hz - df / 2 <= wide.f_high_hz <= notch[1].f_high_hz + 500e3
    assert 2.4e6 - 3 * df <= wide.bandwidth_hz <= 2.4e6 + 1e6
    # closing that is too small to bridge the gap changes nothing
    assert len(bu.detect_bursts(power_db, freqs_hz, times_s, close_time_s=dt,
                                close_freq_hz=df, **common)) == 4


def test_detect_bursts_from_iq_and_matching_helpers():
    fs = 10e6
    rng = np.random.default_rng(6)
    scene = syn.Scene(fs, FC, 5e-3, rng, noise_power_db=-60.0)
    scene.add(syn.bandlimited_noise_burst(fs, 2e6, 1e-3, rng), t_start_s=1e-3,
              freq_offset_hz=2e6, snr_db=20.0, label="b", bandwidth_hz=2e6)
    truth = scene.truth_bursts()
    found = bu.detect_bursts_from_iq(
        scene.render(), fs, FC, fft_size=512, threshold_db=10.0,
        min_duration_s=100e-6, min_bandwidth_hz=100e3,
    )
    assert len(found) == 1
    assert bu.time_freq_iou(found[0], truth[0]) > 0.8
    assert bu.match_bursts(found, truth) == ([(0, 0)], [], [])
    assert bu.match_bursts([], truth) == ([], [], [0])
    assert bu.match_bursts(found, []) == ([], [0], [])

    a = bu.Burst(0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0)
    assert bu.time_freq_iou(a, a) == pytest.approx(1.0)
    assert bu.time_freq_iou(a, bu.Burst(2.0, 3.0, 0.0, 1.0, 0.0, 0.0, 0.0)) == 0.0
    assert bu.time_freq_iou(a, {"t_start_s": 0.5, "t_end_s": 1.5, "f_low_hz": 0.0,
                                "f_high_hz": 1.0}) == pytest.approx(1 / 3)
    assert bu.time_freq_iou(a, bu.Burst(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)) == 0.0
