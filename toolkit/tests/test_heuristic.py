"""The heuristic classifier, driven by synthetic scenes with known truth.

Every test builds a scene whose parameters come from the signature table, runs
the real detection chain (STFT -> bursts -> features), and checks that the
right family is named.  Nothing here mocks the DSP.
"""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.classify import heuristic as hc
from antsdr_toolkit.classify import signatures as sg
from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.dsp.bursts import detect_bursts_from_iq
from antsdr_toolkit.dsp.features import burst_features

FS = 30.72e6
FC = 2.4415e9


def _scene(duration_s: float, seed: int = 3) -> syn.Scene:
    return syn.Scene(FS, FC, duration_s, np.random.default_rng(seed), noise_power_db=-60.0)


def _detect(x, fc=FC, *, fft_size: int = 512, threshold_db: float = 10.0,
            min_duration_s: float | None = None, min_bandwidth_hz: float | None = None):
    """Detect with the gates a real detector needs to survive its own noise.

    A single-cell false alarm has probability exp(-threshold) per spectrogram
    cell, and a 50 ms scene at 30.72 MSPS with a 512-point FFT has about three
    million cells, so a bare threshold produces thousands of one-cell "bursts".
    Requiring a burst to span several frames and several bins removes them,
    which is exactly what the minimum duration and bandwidth of every
    signature imply anyway.
    """
    dt = (fft_size // 2) / FS
    df = FS / fft_size
    return detect_bursts_from_iq(
        x, FS, fc, fft_size=fft_size, threshold_db=threshold_db,
        min_duration_s=3 * dt if min_duration_s is None else min_duration_s,
        min_bandwidth_hz=3 * df if min_bandwidth_hz is None else min_bandwidth_hz,
    )


def _classify_scene(scene: syn.Scene, *, band_hint: str | None = "ism-2g4",
                    threshold_db: float = 10.0, fft_size: int = 512,
                    min_duration_s: float | None = None,
                    min_bandwidth_hz: float | None = None,
                    extra: dict | None = None, top_k: int = 5):
    x = scene.render()
    window_s = len(x) / FS
    bursts = _detect(x, scene.center_freq_hz if hasattr(scene, "center_freq_hz") else FC,
                     fft_size=fft_size, threshold_db=threshold_db,
                     min_duration_s=min_duration_s, min_bandwidth_hz=min_bandwidth_hz)
    feats = burst_features(bursts, window_s=window_s)
    return feats, hc.classify(feats, band_hint=band_hint, extra=extra, top_k=top_k)


def _names(cands) -> list[str]:
    return [c.family for c in cands]


# --------------------------------------------------------------------- membership


def test_membership_is_one_inside_and_geometric_outside():
    assert hc.membership(5e6, 4e6, 6e6) == 1.0
    assert hc.membership(4e6, 4e6, 6e6) == 1.0 and hc.membership(6e6, 4e6, 6e6) == 1.0
    # a factor of `tolerance` beyond an edge scores zero, symmetrically in ratio
    assert hc.membership(18e6, 4e6, 6e6, tolerance=3.0) == pytest.approx(0.0, abs=1e-9)
    assert hc.membership(4e6 / 3.0, 4e6, 6e6, tolerance=3.0) == pytest.approx(0.0, abs=1e-9)
    # halfway in log space is halfway in score
    assert hc.membership(6e6 * math_sqrt3(), 4e6, 6e6) == pytest.approx(0.5, abs=1e-6)
    assert hc.membership(60e6, 4e6, 6e6) == 0.0  # far outside clamps at zero
    assert hc.membership(float("nan"), 4e6, 6e6) == 0.0
    # a range that touches zero (duty cycle, hop rate) decays linearly instead
    assert hc.membership(0.0, 0.0, 0.01) == 1.0
    assert 0.0 < hc.membership(0.02, 0.0, 0.01) < 1.0
    assert hc.membership(1.0, 0.0, 0.01) == 0.0


def math_sqrt3() -> float:
    return 3.0 ** 0.5


# ------------------------------------------------------------------- DJI DroneID


def test_droneid_burst_train_is_named_droneid():
    # 9 MHz occupied, 643 us, every 600 ms: only three bursts fit a 1.3 s scene,
    # which is exactly the sparseness that identifies it.
    scene = _scene(1.4)
    rng = np.random.default_rng(11)
    for k in range(3):
        burst = syn.bandlimited_noise_burst(FS, 9e6, 643.2e-6, rng)
        scene.add(burst, t_start_s=0.05 + k * 0.6, freq_offset_hz=0.0, snr_db=22.0,
                  label="droneid", bandwidth_hz=9e6)
    feats, cands = _classify_scene(scene, band_hint="dji-2g4",
                                   min_duration_s=200e-6, min_bandwidth_hz=2e6)
    assert feats.n_bursts == 3
    assert cands[0].family == "dji_droneid", _names(cands)
    assert cands[0].score > 0.75
    assert "bandwidth_hz" in cands[0].matched and "interval_s" in cands[0].matched
    assert cands[0].decodability == "decodable"
    assert "fits" in cands[0].explanation


def test_ocusync_video_is_not_confused_with_droneid():
    # same width, but 600 us every 5 ms: a video downlink, not a DroneID beacon
    scene = _scene(60e-3)
    rng = np.random.default_rng(12)
    for k in range(11):
        burst = syn.bandlimited_noise_burst(FS, 10e6, 600e-6, rng)
        scene.add(burst, t_start_s=2e-3 + k * 5e-3, freq_offset_hz=0.0, snr_db=22.0,
                  label="video", bandwidth_hz=10e6)
    feats, cands = _classify_scene(scene, band_hint="dji-2g4",
                                   min_duration_s=200e-6, min_bandwidth_hz=2e6, top_k=30)
    assert feats.n_bursts >= 10
    top = _names(cands)[:2]
    assert "dji_ocusync2_video" in top, top
    assert top[0] != "dji_droneid"
    # The repetition rate is what separates them, and it is not a near miss:
    # 5 ms against 450-800 ms is a contradiction, so DroneID is capped below
    # the unknown threshold and can never be the answer for this emitter.
    droneid = next(c for c in cands if c.family == "dji_droneid")
    assert "interval_s" in droneid.mismatched
    assert droneid.per_feature["interval_s"] == 0.0
    assert droneid.score <= hc.CONTRADICTION_CAP
    assert "ruled out by" in droneid.explanation


# ------------------------------------------------------------------- ELRS / FHSS


def test_elrs_250hz_fhss_is_named_among_the_top_candidates():
    # 812.5 kHz LoRa chirps, 3.3 ms long, every 4 ms, hopping every 4 packets
    # over a 1 MHz grid: the published 250 Hz mode.
    scene = _scene(120e-3, seed=5)
    rng = np.random.default_rng(13)
    offsets = [(-4 + k) * 1e6 for k in range(8)]
    t = 2e-3
    idx = 0
    # SF7 at 812.5 kHz is a 157 us symbol, so 21 of them make the 3.3 ms packet
    # of the 250 Hz mode.
    n_symbols = max(1, round(3.3e-3 / (2 ** 7 / 812.5e3)))
    while t < 0.115:
        burst = syn.lora_chirps(FS, 812.5e3, 7, n_symbols, rng)
        scene.add(burst, t_start_s=t, freq_offset_hz=offsets[(idx // 4) % len(offsets)],
                  snr_db=25.0, label="elrs", bandwidth_hz=812.5e3)
        t += 4e-3
        idx += 1
    feats, cands = _classify_scene(scene, band_hint="ism-2g4", fft_size=256,
                                   min_duration_s=500e-6, min_bandwidth_hz=300e3)
    assert feats.n_bursts >= 20
    assert feats.n_distinct_centers >= 6
    names = _names(cands)
    assert any(n.startswith("elrs_2g4") for n in names), names
    best_elrs = next(c for c in cands if c.family.startswith("elrs_2g4"))
    assert best_elrs.score > 0.5
    assert "center_spacing_hz" in best_elrs.matched or "bandwidth_hz" in best_elrs.matched


def test_a_fixed_narrow_link_is_not_called_a_hopper():
    scene = _scene(120e-3, seed=6)
    rng = np.random.default_rng(14)
    t = 2e-3
    while t < 0.115:
        burst = syn.gfsk_burst(FS, 100e3, 200, rng)
        scene.add(burst, t_start_s=t, freq_offset_hz=1.0e6, snr_db=25.0,
                  label="fixed", bandwidth_hz=200e3)
        t += 10e-3
    feats, cands = _classify_scene(scene, band_hint="ism-2g4", fft_size=256,
                                   min_duration_s=300e-6, min_bandwidth_hz=100e3)
    assert feats.n_distinct_centers == 1 and feats.hop_rate_hz == 0.0
    hoppers = {"elrs_2g4_lora_250hz", "frsky_d8_d16", "flysky_afhds2a", "futaba_sfhss"}
    top = _names(cands)[0]
    assert top not in hoppers or cands[0].score < 0.6, _names(cands)


# ----------------------------------------------------------------- analog video


def test_continuous_fm_carrier_is_named_analog_fpv():
    scene = syn.Scene(FS, 5.8e9, 40e-3, np.random.default_rng(7), noise_power_db=-60.0)
    rng = np.random.default_rng(15)
    video = syn.fm_video_like(FS, 39e-3, rng, deviation_hz=5e6, baseband_bw_hz=4.2e6)
    scene.add(video, t_start_s=0.5e-3, freq_offset_hz=0.0, snr_db=25.0,
              label="fpv", bandwidth_hz=14e6)
    x = scene.render()
    bursts = _detect(x, 5.8e9, min_duration_s=5e-3, min_bandwidth_hz=2e6)
    feats = burst_features(bursts, window_s=len(x) / FS)
    # the envelope test is what an analog carrier is really identified by
    cands = hc.classify(feats, band_hint="fpv-5g8-wide", extra={"duty_cycle": 1.0})
    assert feats.duty_cycle > 0.8
    assert cands[0].family == "analog_fpv_video", _names(cands)
    assert cands[0].decodability == "decodable"


# ----------------------------------------------------------------------- unknown


def test_noise_only_is_unknown():
    scene = _scene(50e-3, seed=8)  # nothing added
    feats, cands = _classify_scene(scene)
    assert feats.n_bursts == 0
    assert cands[0].family == "unknown"
    assert "no signature above" in cands[0].explanation


def test_a_waveform_outside_every_range_is_unknown_with_near_misses():
    feats = _fake_features(bandwidth_median_hz=200e6, duration_median_s=1.0,
                           interval_median_s=1e-6, duty_cycle=0.5)
    cands = hc.classify(feats, band_hint="ism-2g4")
    assert cands[0].family == "unknown"
    assert len(cands) > 1  # near misses are still reported
    assert all(c.score < hc.UNKNOWN_BELOW for c in cands[1:])


# ------------------------------------------------------------------ band and API


def test_out_of_band_is_a_penalty_not_a_veto():
    feats = _fake_features(bandwidth_median_hz=9e6, duration_median_s=643e-6,
                           interval_median_s=0.6, duty_cycle=0.001,
                           n_distinct_centers=1)
    in_band = hc.classify(feats, band_hint="dji-2g4")[0]
    out_band = next(c for c in hc.classify(feats, band_hint="ism-433", top_k=30)
                    if c.family == "dji_droneid")
    assert in_band.family == "dji_droneid" and in_band.in_band
    assert not out_band.in_band
    assert out_band.score == pytest.approx(in_band.score * hc.OUT_OF_BAND_FACTOR, rel=1e-6)
    assert "outside the expected band" in out_band.explanation
    # restrict_to_band drops it entirely instead
    restricted = hc.classify(feats, band_hint="ism-433", restrict_to_band=True, top_k=30)
    assert "dji_droneid" not in _names(restricted)


def test_a_single_overlapping_feature_cannot_win():
    # only the bandwidth is known: fewer than MIN_FEATURES overlap for every
    # signature that constrains more, so nothing is scored on width alone.
    feats = _fake_features(bandwidth_median_hz=9e6, n_bursts=1)
    cands = hc.classify(feats, band_hint="ism-2g4")
    assert cands[0].family == "unknown", [c.family for c in cands]
    # ... and a duty cycle plus a hop rate of zero are not identity either:
    # with five bursts of unknown width nothing may be named.
    assert hc.classify(_fake_features(n_bursts=5))[0].family == "unknown"


def test_margin_reports_how_close_the_runner_up_is():
    feats = _fake_features(bandwidth_median_hz=9e6, duration_median_s=643e-6,
                           interval_median_s=0.6, duty_cycle=0.001, n_distinct_centers=1)
    cands = hc.classify(feats, band_hint="dji-2g4")
    assert hc.margin(cands) > 0.0
    assert hc.margin([cands[0]]) == 0.0


def test_candidates_serialise():
    feats = _fake_features(bandwidth_median_hz=9e6, duration_median_s=643e-6,
                           interval_median_s=0.6, duty_cycle=0.001, n_distinct_centers=1)
    d = hc.classify(feats, band_hint="dji-2g4")[0].to_dict()
    import json

    assert json.loads(json.dumps(d))["family"] == "dji_droneid"
    assert 0.0 <= d["score"] <= 1.0 and isinstance(d["matched"], list)


def test_classify_clusters_separates_two_emitters():
    scene = _scene(60e-3, seed=9)
    rng = np.random.default_rng(16)
    for k in range(11):  # wide OFDM-like video at +10 MHz
        burst = syn.bandlimited_noise_burst(FS, 10e6, 600e-6, rng)
        scene.add(burst, t_start_s=2e-3 + k * 5e-3, freq_offset_hz=10e6, snr_db=22.0,
                  label="video", bandwidth_hz=10e6)
    t, idx = 1e-3, 0
    while t < 55e-3:  # narrow hopper down at -8..-5 MHz
        burst = syn.gfsk_burst(FS, 200e3, 400, rng)
        scene.add(burst, t_start_s=t, freq_offset_hz=-8e6 + (idx % 4) * 1e6, snr_db=25.0,
                  label="hop", bandwidth_hz=400e3)
        t += 4e-3
        idx += 1
    x = scene.render()
    bursts = _detect(x, min_duration_s=200e-6, min_bandwidth_hz=300e3)
    groups = hc.classify_clusters(bursts, window_s=len(x) / FS, band_hint="ism-2g4")
    assert len(groups) == 2, [f.n_bursts for f, _ in groups]
    widths = sorted(f.bandwidth_median_hz for f, _ in groups)
    assert widths[0] < 2e6 < widths[1]
    # the wide group is called a wide family, the narrow one a narrow family
    wide = max(groups, key=lambda g: g[0].bandwidth_median_hz)
    narrow = min(groups, key=lambda g: g[0].bandwidth_median_hz)
    assert wide[1][0].family in {"dji_ocusync2_video", "dji_o4_airlink", "wifi_generic",
                                 "herelink", "dji_lightbridge2", "unknown"}
    assert narrow[1][0].family not in {"dji_ocusync2_video", "analog_fpv_video"}
    assert hc.classify_clusters([], window_s=1.0) == []


def _fake_features(**kwargs):
    """A BurstFeatures with only the named statistics set (others 0.0)."""
    from antsdr_toolkit.dsp.features import BurstFeatures

    base = {
        "n_bursts": kwargs.pop("n_bursts", 5), "window_s": kwargs.pop("window_s", 0.1),
        "duty_cycle": 0.0, "bandwidth_median_hz": 0.0, "bandwidth_p10_hz": 0.0, "bandwidth_p90_hz": 0.0,
        "duration_median_s": 0.0, "duration_p10_s": 0.0, "duration_p90_s": 0.0,
        "interval_median_s": 0.0, "interval_cv": 0.0, "n_distinct_centers": 0,
        "center_spacing_median_hz": 0.0, "hop_rate_hz": 0.0, "occupied_span_hz": 0.0,
        "snr_median_db": 20.0,
    }
    base.update(kwargs)
    return BurstFeatures(**base)


def test_every_signature_can_be_matched_by_its_own_midpoint():
    """A measurement at the centre of a signature's ranges must score it top-3."""
    misses: list[str] = []
    for sig in sg.SIGNATURES:
        ranges = sig.constrained()
        kwargs: dict[str, float] = {}
        for name, (lo, hi) in ranges.items():
            mid = (lo * hi) ** 0.5 if lo > 0 else (lo + hi) / 2.0
            field = hc.FEATURE_FIELDS[name]
            kwargs[field] = mid
        feats = _fake_features(**kwargs)
        band = sig.bands[0]
        names = _names(hc.classify(feats, band_hint=band, top_k=3))
        if sig.family not in names:
            misses.append(f"{sig.family} -> {names}")
    assert not misses, "signatures unreachable from their own midpoint:\n" + "\n".join(misses)
