"""The signature table must stay internally consistent and traceable."""

from __future__ import annotations

import pytest

from antsdr_toolkit.classify import signatures as sg
from antsdr_toolkit.scan import bands as bd


def test_every_signature_is_well_formed():
    assert len(sg.SIGNATURES) >= 20
    for s in sg.SIGNATURES:
        assert s.family and s.display
        assert s.decodability in sg.DECODABILITY
        assert s.confidence in sg.CONFIDENCE
        assert s.sources, f"{s.family} has no source"
        for url in s.sources:
            assert url.startswith("http"), f"{s.family}: {url!r} is not a URL"
        assert len(s.notes) > 40, f"{s.family}: notes too thin to be useful"
        ranges = s.constrained()
        assert ranges, f"{s.family} constrains nothing"
        for name, (lo, hi) in ranges.items():
            assert lo <= hi and lo >= 0.0, f"{s.family}.{name}"
        # A signature must be scoreable: the classifier needs at least two
        # structural features (duty cycle and hop rate are legitimately zero
        # for half the table, so they cannot select a family on their own).
        from antsdr_toolkit.classify.heuristic import MIN_FEATURES, STRUCTURAL

        structural = [k for k in ranges if k in STRUCTURAL]
        assert len(structural) >= MIN_FEATURES, (
            f"{s.family} constrains only {structural}; it can never be selected")


def test_families_are_unique_and_addressable():
    names = sg.families()
    assert len(names) == len(set(names)) == len(sg.SIGNATURES)
    assert sg.by_family("dji_droneid").decodability == "decodable"
    with pytest.raises(KeyError):
        sg.by_family("no_such_family")


def test_bands_exist_in_the_band_plans():
    known = set(bd.BAND_PLANS)
    for s in sg.SIGNATURES:
        assert s.bands, f"{s.family} names no band"
        unknown = set(s.bands) - known
        assert not unknown, f"{s.family} names unknown bands {unknown}"


def test_band_filters():
    in_2g4 = set(sg.families_in_band("ism-2g4"))
    assert "elrs_2g4_lora_250hz" in in_2g4 and "frsky_d8_d16" in in_2g4
    assert "elrs_900_lora_100hz" not in in_2g4
    assert "analog_fpv_video" in sg.families_in_band("fpv-5g8-wide")
    assert set(sg.families_in_band(None)) == set(sg.families())
    assert len(list(sg.signatures_for_band("eu868"))) >= 4


def test_droneid_row_matches_the_reverse_engineered_phy():
    s = sg.by_family("dji_droneid")
    lo, hi = s.duration_s
    assert lo <= 643.2e-6 <= hi, "the 643.2 us burst must be inside the accepted range"
    lo, hi = s.bandwidth_hz
    assert lo <= 9e6 <= hi, "9 MHz occupied (600 carriers x 15 kHz) must fit"
    lo, hi = s.interval_s
    assert lo <= 0.6 <= hi, "the ~600 ms repetition must fit"
    assert 2429.5e6 in s.channel_plan and 5756.5e6 in s.channel_plan
    assert len(s.channel_plan) == len(set(s.channel_plan))


def test_elrs_rows_cover_the_published_packet_rates():
    fam = {s.family for s in sg.SIGNATURES}
    for rate in ("500hz", "250hz", "150hz", "50hz"):
        assert f"elrs_2g4_lora_{rate}" in fam
    for rate in ("200hz", "100hz", "50hz"):
        assert f"elrs_900_lora_{rate}" in fam
    # 2.4 GHz is detect-only, sub-GHz is a decode candidate (verified: elrs-decodability)
    assert sg.by_family("elrs_2g4_lora_250hz").decodability == "detect_only"
    assert sg.by_family("elrs_2g4_flrc").decodability == "detect_only"
    assert sg.by_family("elrs_900_lora_100hz").decodability == "decodable"
    # the documented 250 Hz timing: 3.3 ms bursts every 4 ms, hop every 4 packets
    s = sg.by_family("elrs_2g4_lora_250hz")
    assert s.duration_s[0] <= 3.3e-3 <= s.duration_s[1]
    assert s.interval_s[0] <= 4e-3 <= s.interval_s[1]
    assert s.hop_rate_hz[0] <= 1.0 / 16e-3 <= s.hop_rate_hz[1]
    assert s.bandwidth_hz[0] <= 812.5e3 <= s.bandwidth_hz[1]


def test_decodability_is_recorded_honestly():
    encrypted = {s.family for s in sg.SIGNATURES if s.decodability == "encrypted"}
    assert {"dji_o4_airlink", "dji_ocusync2_video", "dji_ocusync_c2"} <= encrypted
    assert sg.by_family("analog_fpv_video").decodability == "decodable"
    assert sg.by_family("hdzero_video").decodability == "detect_only"
    assert sg.by_family("wifi_broadcast_fpv").decodability == "detect_only"


def test_serialisation_round_trips_to_json_types():
    import json

    table = sg.as_table()
    assert len(table) == len(sg.SIGNATURES)
    text = json.dumps(table)
    back = json.loads(text)
    assert back[0]["family"] == sg.SIGNATURES[0].family
    assert isinstance(back[0]["ranges"], dict) and back[0]["sources"]
