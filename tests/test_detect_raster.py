"""T2 acceptance tests for aerix_rf.detect.raster (stage1-link-signatures.md
rules R1-R5). Synthetic BurstEvent lists are built directly (no bursts.py
detector in the loop) since raster.py is a pure function over BurstEvent
values. Seeded wherever randomness is used.
"""

from __future__ import annotations

import numpy as np

from aerix_rf.detect.bursts import BurstEvent
from aerix_rf.detect.raster import (
    analyze_raster,
    cluster_centres,
)


def _ev(t_start: float, dur_s: float, centre_hz: float, bw_hz: float) -> BurstEvent:
    return BurstEvent(
        t_start=t_start, t_end=t_start + dur_s, duration_s=dur_s,
        centre_hz=centre_hz, bw_6db_hz=bw_hz,
        peak_db_over_floor=20.0, mean_db_over_floor=15.0, n_frames=3,
        edge_clipped=False,
    )


def _hopper(rng, *, n_inband: int, packet_period_s: float, in_band_prob: float,
            n_channels: int, base_hz: float, spacing_hz: float, bw_hz: float,
            dur_s: float, max_slots: int = 2_000_000) -> list[BurstEvent]:
    """A frequency hopper sampled at ``packet_period_s``; each packet has
    probability ``in_band_prob`` of landing inside the observed dwell (the
    rest hop elsewhere), matching design S1's coupon-collector model."""
    events = []
    t = 0.0
    slots = 0
    while len(events) < n_inband and slots < max_slots:
        if rng.random() < in_band_prob:
            k = int(rng.integers(0, n_channels))
            centre = base_hz + k * spacing_hz
            events.append(_ev(t, dur_s, centre, bw_hz))
        t += packet_period_s
        slots += 1
    return events


def _hopper_for_duration(rng, *, duration_s: float, packet_period_s: float,
                          in_band_prob: float, n_channels: int, base_hz: float,
                          spacing_hz: float, bw_hz: float, dur_s: float) -> list[BurstEvent]:
    events = []
    t = 0.0
    while t < duration_s:
        if rng.random() < in_band_prob:
            k = int(rng.integers(0, n_channels))
            centre = base_hz + k * spacing_hz
            events.append(_ev(t, dur_s, centre, bw_hz))
        t += packet_period_s
    return events


ELRS_BASE_HZ = 2400.4e6


# --------------------------------------------------------------------------
# cluster_centres
# --------------------------------------------------------------------------

def test_cluster_centres_excludes_edge_clipped_and_groups_by_gap():
    a = _ev(0.0, 1e-3, 2400.0e6, 0.3e6)
    b = _ev(1.0, 1e-3, 2400.03e6, 0.3e6)   # 30 kHz from a -> same cluster
    c = _ev(2.0, 1e-3, 2402.0e6, 0.3e6)    # far -> new cluster
    clipped = BurstEvent(t_start=3.0, t_end=3.001, duration_s=1e-3,
                          centre_hz=2500.0e6, bw_6db_hz=0.3e6,
                          peak_db_over_floor=20.0, mean_db_over_floor=15.0,
                          n_frames=3, edge_clipped=True)
    clusters = cluster_centres([a, b, c, clipped], tol_hz=100e3)
    assert len(clusters) == 2
    assert sum(cl.n for cl in clusters) == 3  # clipped event excluded
    sizes = sorted(cl.n for cl in clusters)
    assert sizes == [1, 2]


# --------------------------------------------------------------------------
# (i) ELRS 1 MHz grid: decidable at 250 Hz / 1 s, insufficient at 50 Hz / 1 s,
#     decidable at 50 Hz / 3 s.
# --------------------------------------------------------------------------

def test_elrs_1mhz_grid_decidable_at_250hz():
    # duration-based (not a fixed hop count): "20 hops in a 10 MHz dwell at
    # 250 Hz" is the design doc's naturally-occurring 1 s yield at
    # rho=0.125 in-band probability (design S1's table), not a literal
    # count -- coupon-collector coverage of all 10 in-band channels needs
    # more draws than a fixed n=20 reliably provides.
    rng = np.random.default_rng(0)
    events = _hopper_for_duration(rng, duration_s=1.0, packet_period_s=0.004,
                                   in_band_prob=0.125, n_channels=10,
                                   base_hz=ELRS_BASE_HZ, spacing_hz=1.0e6,
                                   bw_hz=0.3e6, dur_s=0.5e-3)
    result = analyze_raster(events)
    assert "fhss_1mhz_grid_candidate" in result.labels
    assert abs(result.raster.delta_hz - 1.0e6) <= 5e3
    assert abs(result.raster.offset_hz - 0.4e6) <= 50e3
    assert "expresslrs_2g4" in result.consistent_with
    assert "INSUFFICIENT_CHANNELS" not in result.tags


def test_elrs_1mhz_grid_insufficient_at_50hz_1s():
    rng = np.random.default_rng(2)
    events = _hopper_for_duration(rng, duration_s=1.0, packet_period_s=0.020,
                                   in_band_prob=0.125, n_channels=10,
                                   base_hz=ELRS_BASE_HZ, spacing_hz=1.0e6,
                                   bw_hz=0.3e6, dur_s=0.5e-3)
    result = analyze_raster(events)
    assert "INSUFFICIENT_CHANNELS" in result.tags
    assert "fhss_1mhz_grid_candidate" not in result.labels


def test_elrs_1mhz_grid_decidable_at_50hz_3s():
    rng = np.random.default_rng(2)
    events = _hopper_for_duration(rng, duration_s=3.0, packet_period_s=0.020,
                                   in_band_prob=0.125, n_channels=10,
                                   base_hz=ELRS_BASE_HZ, spacing_hz=1.0e6,
                                   bw_hz=0.3e6, dur_s=0.5e-3)
    result = analyze_raster(events)
    assert "fhss_1mhz_grid_candidate" in result.labels
    assert "INSUFFICIENT_CHANNELS" not in result.tags


# --------------------------------------------------------------------------
# (ii) DJI-RC-like 2 MHz hopper: single dwell undecidable (<=6 channels),
#      3 dithered dwells decidable.
# --------------------------------------------------------------------------

DJI_BASE_HZ = 2402.0e6


def test_2mhz_hopper_single_dwell_hopping_only():
    rng = np.random.default_rng(4)
    events = _hopper(rng, n_inband=30, packet_period_s=0.004, in_band_prob=1.0,
                      n_channels=6, base_hz=DJI_BASE_HZ, spacing_hz=2.0e6,
                      bw_hz=0.5e6, dur_s=0.5e-3)
    result = analyze_raster(events)
    assert "INSUFFICIENT_CHANNELS" in result.tags
    assert "fhss_2mhz_grid_candidate" not in result.labels
    assert "fhss_1mhz_grid_candidate" not in result.labels
    assert "hopping_candidate" in result.labels


def test_2mhz_hopper_three_dithered_dwells_decidable():
    events: list[BurstEvent] = []
    for dwell_idx, k0 in enumerate([0, 3, 6]):
        rng = np.random.default_rng(100 + dwell_idx)
        dwell_events = _hopper(rng, n_inband=30, packet_period_s=0.004, in_band_prob=1.0,
                                n_channels=6, base_hz=DJI_BASE_HZ + k0 * 2.0e6,
                                spacing_hz=2.0e6, bw_hz=0.5e6, dur_s=0.5e-3)
        events.extend(dwell_events)
    result = analyze_raster(events)
    assert result.raster.n_channels >= 10
    assert "fhss_2mhz_grid_candidate" in result.labels
    assert any("BLE" in n for n in result.notes)


# --------------------------------------------------------------------------
# (iii) BLE data hopper: 2 MHz raster, 1.25 ms-quantised connection interval
#       -> ble_connection_like, no rc/fhss label.
# --------------------------------------------------------------------------

def test_ble_data_hopper_tagged_not_labelled():
    rng = np.random.default_rng(5)
    n_channels = 37
    conn_interval_s = 30.0 * 1.25e-3   # 30 ms, exact 1.25 ms multiple
    events = []
    t = 0.0
    while t < 6.0:
        k = int(rng.integers(0, n_channels))
        events.append(_ev(t, 150e-6, 2404.0e6 + k * 2.0e6, 1.0e6))
        t += conn_interval_s
    result = analyze_raster(events)
    assert "ble_connection_like" in result.tags
    assert "fhss_2mhz_grid_candidate" not in result.labels
    assert "fhss_1mhz_grid_candidate" not in result.labels
    assert "rc_link_family_candidate" not in result.labels


# --------------------------------------------------------------------------
# (iv) Wi-Fi beacons (102.4 ms, late-only jitter) + BLE adverts (3 fixed
#      channels) -> wifi_beacon_like tag, no level-2 label.
# --------------------------------------------------------------------------

def test_wifi_beacons_and_ble_adverts_tags_only():
    rng = np.random.default_rng(6)
    events = []
    # Wi-Fi beacons: one AP, wide (20 MHz) fixed channel (2.4 GHz channel 11,
    # chosen far enough from the BLE advertising channels below that the
    # bandwidth-scaled cluster-separation floor -- 0.75*20 MHz = 15 MHz --
    # does not accidentally pull a narrowband advert into the AP's cluster),
    # 102.4 ms period, late-only jitter (contention delays, never advances --
    # facts brief #5).
    t = 0.0
    while t < 3.0:
        jitter = rng.uniform(0.0, 0.003)   # late-only, up to +3 ms
        events.append(_ev(t + jitter, 80e-6, 2462.0e6, 20.0e6))
        t += 0.1024
    # BLE adverts: strict 37/38/39 round-robin on 3 fixed, widely-separated
    # channels (2402/2426/2480 MHz), narrow bursts.
    advert_channels = [2402.0e6, 2426.0e6, 2480.0e6]
    ta = 0.0
    for i in range(60):
        events.append(_ev(ta, 300e-6, advert_channels[i % 3], 1.0e6))
        ta += 0.02 + rng.uniform(0.0, 0.010)   # 20 ms + 0-10 ms advDelay
    result = analyze_raster(events)
    assert "wifi_beacon_like" in result.tags
    assert "fhss_1mhz_grid_candidate" not in result.labels
    assert "fhss_2mhz_grid_candidate" not in result.labels
    assert "rc_link_family_candidate" not in result.labels
    assert "droneid_cadence_candidate" not in result.labels


# --------------------------------------------------------------------------
# (v) fixed-channel varying-shape burst -> fixed_channel_burst_candidate.
# --------------------------------------------------------------------------

def test_fixed_channel_varying_shape_burst():
    rng = np.random.default_rng(7)
    events = []
    for i in range(20):
        jitter = rng.normal(0.0, 20e3)   # small centre jitter, well < 0.25*BW
        bw = 18e6 + rng.normal(0.0, 1e6)
        events.append(_ev(i * 0.05, 1e-3, 2437.0e6 + jitter, bw))
    result = analyze_raster(events)
    assert "fixed_channel_burst_candidate" in result.labels
    assert result.raster.insufficient  # M=1 well below M_MIN_RASTER
    assert not any(l for l in result.labels if l.startswith("fhss_"))


# --------------------------------------------------------------------------
# (vi) DroneID-like 640 ms cadence, 9 MHz flat-top -> droneid_cadence_candidate.
# --------------------------------------------------------------------------

def test_droneid_cadence_candidate():
    rng = np.random.default_rng(8)
    events = []
    t = 0.0
    while t < 4.0:
        jitter = rng.normal(0.0, 1e-3)
        events.append(_ev(t + jitter, 20e-3, 2432.5e6, 9.0e6))
        t += 0.640
    result = analyze_raster(events)
    assert "droneid_cadence_candidate" in result.labels


# --------------------------------------------------------------------------
# (vii) noise: random centres, random times -> no labels, p > 0.05.
# --------------------------------------------------------------------------

def test_noise_no_labels_and_high_p_false():
    rng = np.random.default_rng(9)
    events = []
    for _ in range(80):
        t = rng.uniform(0.0, 3.0)
        centre = rng.uniform(2400e6, 2480e6)
        bw = rng.uniform(0.1e6, 1.0e6)
        events.append(_ev(t, rng.uniform(0.2e-3, 2e-3), centre, bw))
    events.sort(key=lambda e: e.t_start)
    result = analyze_raster(events)
    assert result.labels == []
    assert result.raster.p_false > 0.05


def test_result_labels_and_tags_are_from_controlled_vocabulary():
    rng = np.random.default_rng(10)
    events = _hopper(rng, n_inband=20, packet_period_s=0.004, in_band_prob=0.125,
                      n_channels=10, base_hz=ELRS_BASE_HZ, spacing_hz=1.0e6,
                      bw_hz=0.3e6, dur_s=0.5e-3)
    result = analyze_raster(events)
    from aerix_rf.detect.raster import LABEL_VOCAB, TAG_VOCAB
    assert all(l in LABEL_VOCAB for l in result.labels)
    assert all(t in TAG_VOCAB for t in result.tags)
    d = result.as_dict()
    assert "raster" in d and "period" in d
