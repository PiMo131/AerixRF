"""Tests for antsdr_toolkit.scan.bands and antsdr_toolkit.scan.planner."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from antsdr_toolkit.scan import bands as bd
from antsdr_toolkit.scan import planner as pl

MHZ = 1e6


# --------------------------------------------------------------------------- bands


def test_fpv_table_matches_fpv_sdr_facts():
    assert len(bd.FPV_5G8_CHANNELS) == 62
    uniq = bd.fpv_channel_freqs_hz()
    assert len(uniq) == 53
    assert uniq[0] == 5362 * MHZ and uniq[-1] == 5945 * MHZ
    assert uniq == sorted(uniq)
    assert {c.band for c in bd.FPV_5G8_CHANNELS} == {"R", "A", "B", "E", "F", "IMD", "D", "L"}
    by_name = {c.name: c for c in bd.FPV_5G8_CHANNELS}
    assert by_name["R1"].freq_mhz == by_name["IMD1"].freq_mhz == 5658
    assert by_name["R2"].freq_mhz == by_name["IMD2"].freq_mhz == by_name["D2"].freq_mhz == 5695
    assert by_name["R7"].freq_mhz == by_name["F8"].freq_mhz == 5880
    # L band: 37 MHz steps from 5362 MHz
    low = bd.fpv_channel_freqs_hz(["L"])
    assert len(low) == 8
    assert np.allclose(np.diff(low), 37 * MHZ)
    assert bd.fpv_channel_freqs_hz(["r", "IMD"]) == bd.fpv_channel_freqs_hz(["R"])
    assert set(bd.FPV_SCAN_ORDER) == {"R", "A", "F", "E", "B", "D", "L"}


def test_band_plans_edges_and_lookup():
    expected = {
        "ism-2g4": (2400.0, 2483.5), "ism-5g8": (5725.0, 5875.0),
        "fpv-5g8-wide": (5645.0, 5945.0), "fpv-l-band": (5362.0, 5621.0),
        "fpv-1g2": (1080.0, 1360.0), "eu868": (863.0, 870.0), "us915": (902.0, 928.0),
        "ism-433": (433.05, 434.79), "wifi-5": (5150.0, 5895.0),
        "dji-2g4": (2399.5, 2474.5), "dji-5g8": (5721.5, 5831.5),
    }
    assert set(bd.BAND_PLANS) == set(expected)
    for name, (lo, hi) in expected.items():
        band = bd.BAND_PLANS[name]
        assert band.name == name
        assert band.f_low_hz == pytest.approx(lo * MHZ)
        assert band.f_high_hz == pytest.approx(hi * MHZ)
        assert band.span_hz == pytest.approx((hi - lo) * MHZ)
        assert band.center_freq_hz == pytest.approx((lo + hi) / 2 * MHZ)
        assert band.note  # every band explains itself
    # every band except the inferred 1.2 GHz plan cites at least one source URL
    for name, band in bd.BAND_PLANS.items():
        if name != "fpv-1g2":
            assert band.sources and all(s.startswith("https://") for s in band.sources)
    assert "5080-6085" in bd.BAND_PLANS["wifi-5"].note  # OpenHD non-standard extent
    assert "illegal" in bd.BAND_PLANS["fpv-1g2"].note.lower()
    assert bd.get_band("DJI-2G4") is bd.BAND_PLANS["dji-2g4"]
    assert bd.get_band(bd.BAND_PLANS["eu868"]) is bd.BAND_PLANS["eu868"]
    with pytest.raises(ValueError):
        bd.get_band("nope")
    assert bd.list_bands()[0] == "ism-2g4"
    row = bd.BAND_PLANS["ism-433"].to_dict()
    assert row["f_low_hz"] == pytest.approx(433.05 * MHZ) and isinstance(row["sources"], list)
    assert bd.BAND_PLANS["ism-2g4"].contains(2437 * MHZ)
    assert not bd.BAND_PLANS["ism-2g4"].contains(2484 * MHZ)
    with pytest.raises(ValueError):
        bd.Band("bad", 2e9, 1e9)


def test_droneid_centres_and_elrs_grids():
    centres = bd.DRONEID_CENTRES_MHZ
    assert list(centres) == sorted(centres) and len(set(centres)) == len(centres)
    assert len(centres) == 19
    for f in (2414.5, 2429.5, 2434.5, 2444.5, 2459.5, 2474.5, 5721.5, 5731.5, 5741.5,
              5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5):  # DroneSecurity list
        assert f in centres
    for f in (2399.5, 5776.5, 5796.5):  # proto17 / O4 firmware extras
        assert f in centres
    two_g4 = [f for f in centres if f < 3000]
    five_g8 = [f for f in centres if f > 3000]
    assert all(bd.BAND_PLANS["dji-2g4"].contains(f * MHZ) for f in two_g4)
    assert all(bd.BAND_PLANS["dji-5g8"].contains(f * MHZ) for f in five_g8)
    assert bd.BAND_PLANS["dji-2g4"].f_low_hz == two_g4[0] * MHZ
    assert bd.BAND_PLANS["dji-5g8"].f_high_hz == five_g8[-1] * MHZ

    ch = bd.elrs_channels_hz("2g4")
    assert len(ch) == 80 and ch[0] == pytest.approx(2400.4 * MHZ)
    assert ch[-1] == pytest.approx(2479.4 * MHZ)
    assert np.allclose(np.diff(ch), 1.0 * MHZ)
    eu = bd.elrs_channels_hz("eu868")
    assert len(eu) == 13 and eu[-1] == pytest.approx(869.575 * MHZ)
    us = bd.elrs_channels_hz("fcc915")
    assert len(us) == 40 and us[-1] == pytest.approx(926.9 * MHZ)
    assert all(bd.BAND_PLANS["us915"].contains(f) for f in us)
    assert all(bd.BAND_PLANS["eu868"].contains(f) for f in eu)
    with pytest.raises(ValueError):
        bd.elrs_channels_hz("mars")


# --------------------------------------------------------------------------- planner


@pytest.mark.parametrize("rate_msps,expected", [(40, 16), (20, 24), (16, 24), (12, 28)])
def test_plan_reproduces_fpv_sdr_chunk_counts(rate_msps, expected):
    freqs = bd.fpv_channel_freqs_hz()
    plan = pl.plan_dwells(freqs, rate_msps * MHZ)
    assert len(plan) == expected
    usable = 0.8 * rate_msps * MHZ
    centres = [d.center_freq_hz for d in plan]
    assert centres == sorted(centres)
    covered = []
    for d in plan:
        assert d.span_hz == pytest.approx(usable)
        assert d.targets == tuple(sorted(d.targets))
        assert d.targets[-1] - d.targets[0] <= usable + 1e-6
        assert d.center_freq_hz == pytest.approx(0.5 * (d.targets[0] + d.targets[-1]))
        assert all(d.covers(t) for t in d.targets)
        covered.extend(d.targets)
    assert covered == freqs  # every unique target exactly once, in order


def test_plan_targets_details_and_overlap_guard():
    fs = 20 * MHZ
    freqs = [2412 * MHZ, 2437 * MHZ, 2412 * MHZ, 2417 * MHZ]  # duplicates, unsorted
    plan = pl.plan_dwells(freqs, fs)
    assert [d.targets for d in plan] == [(2412 * MHZ, 2417 * MHZ), (2437 * MHZ,)]
    assert plan[0].center_freq_hz == pytest.approx(2414.5 * MHZ)
    assert plan[1].center_freq_hz == pytest.approx(2437 * MHZ)
    assert plan[0].f_low_hz == pytest.approx(2406.5 * MHZ)
    assert plan[0].f_high_hz == pytest.approx(2422.5 * MHZ)
    d = plan[0].to_dict()
    assert d["targets"] == [2412 * MHZ, 2417 * MHZ] and d["span_hz"] == pytest.approx(16 * MHZ)
    assert pl.plan_dwells([], fs) == []
    # numpy input and a single target
    single = pl.plan_dwells(np.array([5.8e9]), fs)
    assert len(single) == 1 and single[0].center_freq_hz == 5.8e9

    # a 16 MHz-wide group fits exactly at overlap 0 ...
    edge = pl.plan_dwells([5700 * MHZ, 5716 * MHZ], fs)
    assert len(edge) == 1
    # ... but with a 25 % guard the grouping width shrinks to 12 MHz and it splits
    guarded = pl.plan_dwells([5700 * MHZ, 5716 * MHZ], fs, overlap=0.25)
    assert len(guarded) == 2
    for dw in guarded:
        for t in dw.targets:
            assert t - dw.f_low_hz >= 0.25 * 16 * MHZ / 2 - 1e-6
            assert dw.f_high_hz - t >= 0.25 * 16 * MHZ / 2 - 1e-6
    # A guard never lowers the dwell count.  At 20 MSPS the fpv-sdr table
    # happens to need 24 either way (the 37 MHz-spaced L band is one dwell per
    # channel regardless, and the dense 5645-5945 MHz group splits the same),
    # but at 16 MSPS the 12 MHz grouping width costs four more dwells.
    fpv = bd.fpv_channel_freqs_hz()
    assert len(pl.plan_dwells(fpv, fs, overlap=0.25)) >= len(pl.plan_dwells(fpv, fs)) == 24
    assert len(pl.plan_dwells(fpv, 16 * MHZ, overlap=0.25)) > len(pl.plan_dwells(fpv, 16 * MHZ))


def test_plan_band_tiling_covers_exactly():
    fs = 20 * MHZ
    usable = 16 * MHZ
    plan = pl.plan_dwells("ism-2g4", fs)  # 83.5 MHz span
    assert len(plan) == math.ceil((83.5 - 16) / 16) + 1 == 6
    assert plan[0].f_low_hz == pytest.approx(2400 * MHZ)
    assert plan[-1].f_high_hz == pytest.approx(2483.5 * MHZ)
    for a, b in itertools.pairwise(plan):
        assert b.center_freq_hz > a.center_freq_hz
        assert b.f_low_hz <= a.f_high_hz + 1e-6  # contiguous (small equal overlaps)
    assert all(d.span_hz == usable and d.targets == () for d in plan)
    steps = np.diff([d.center_freq_hz for d in plan])
    assert np.allclose(steps, steps[0]) and steps[0] <= usable + 1e-6

    # 25 % overlap: step 12 MHz -> 7 tiles, each neighbour pair shares >= 4 MHz
    dense = pl.plan_dwells(bd.BAND_PLANS["ism-2g4"], fs, overlap=0.25)
    assert len(dense) == 7
    for a, b in itertools.pairwise(dense):
        assert a.f_high_hz - b.f_low_hz >= 0.25 * usable - 1e-6

    # an exact multiple of the usable span tiles without any overlap
    band = bd.Band("x", 1e9, 1e9 + 48 * MHZ)
    exact = pl.plan_dwells(band, fs)
    assert len(exact) == 3
    assert [d.f_low_hz for d in exact] == pytest.approx([1e9, 1e9 + 16e6, 1e9 + 32e6])
    # a band narrower than the usable span is one dwell at the band centre
    narrow = pl.plan_dwells(bd.BAND_PLANS["ism-433"], 4 * MHZ)
    assert len(narrow) == 1
    assert narrow[0].center_freq_hz == pytest.approx(bd.BAND_PLANS["ism-433"].center_freq_hz)
    assert narrow[0].span_hz == pytest.approx(3.2 * MHZ)
    # the dji 2.4 GHz centres fit in two 56 MSPS dwells, the 5.8 GHz ones in three
    dji = pl.plan_dwells([f * MHZ for f in bd.DRONEID_CENTRES_MHZ], 56 * MHZ)
    assert len(dji) == 5
    assert sum(len(d.targets) for d in dji) == len(bd.DRONEID_CENTRES_MHZ)
    # ELRS 2.4 GHz grid at the E200 host rate: 17 channels per 16 MHz group -> 5 dwells
    assert len(pl.plan_dwells(bd.elrs_channels_hz("2g4"), fs)) == 5


def test_plan_validation_and_summary():
    with pytest.raises(ValueError):
        pl.plan_dwells([2.4e9], 0.0)
    with pytest.raises(ValueError):
        pl.plan_dwells([2.4e9], 20e6, usable_fraction=0.0)
    with pytest.raises(ValueError):
        pl.plan_dwells([2.4e9], 20e6, usable_fraction=1.5)
    with pytest.raises(ValueError):
        pl.plan_dwells([2.4e9], 20e6, overlap=1.0)
    with pytest.raises(ValueError):
        pl.plan_dwells([2.4e9, -1.0], 20e6)
    with pytest.raises(ValueError):
        pl.plan_dwells("unknown-band", 20e6)
    with pytest.raises(ValueError):
        pl.Dwell(2.4e9, 0.0)
    assert pl.usable_span_hz(20e6) == pytest.approx(16e6)
    assert pl.usable_span_hz(20e6, 1.0) == pytest.approx(20e6)

    plan = pl.plan_dwells(bd.fpv_channel_freqs_hz(), 40e6)
    summary = pl.plan_summary(plan)
    assert summary["n_dwells"] == 16 and summary["n_targets"] == 53
    assert summary["f_low_hz"] < 5362 * MHZ < 5945 * MHZ < summary["f_high_hz"]
    assert summary["total_span_hz"] == pytest.approx(16 * 32e6)
    assert pl.plan_summary([])["n_dwells"] == 0
