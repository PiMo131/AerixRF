"""The airframe table: does it answer "what can I get from this drone"?

These tests guard the conclusions the research produced, so that a later edit
to the table cannot quietly restore a claim the evidence refuted. The most
important of those is that some airframes have no identity source at all.
"""

from __future__ import annotations

import pytest

from antsdr_toolkit import fleet


def test_the_sub_250_gram_airframes_have_no_identity_source_at_all():
    """The finding that shapes the whole plan.

    An OcuSync 4 airframe that is also class C0 has an encrypted proprietary
    identity and no obligation to broadcast a standard one. It is detectable
    and, by any published means, not identifiable.
    """
    for key in ("mini_4_pro", "neo"):
        airframe = fleet.AIRFRAMES[key]
        assert airframe.droneid_encrypted is True
        assert airframe.eu_class == "C0"
        assert airframe.takeoff_weight_g <= 250.0
        assert airframe.remote_id_exempt
        assert fleet.identity_sources(key) == []
        assert airframe.tier == "B"


def test_the_avata_2_is_identifiable_because_it_is_heavy_enough():
    """Same encrypted link, different class label, opposite outcome."""
    avata2 = fleet.AIRFRAMES["avata_2"]
    assert avata2.droneid_encrypted is True
    assert avata2.takeoff_weight_g > 250.0 and avata2.eu_class == "C1"
    assert not avata2.remote_id_exempt
    sources = fleet.identity_sources("avata_2")
    assert len(sources) == 1 and "Remote ID" in sources[0]
    assert avata2.tier == "C"


def test_open_code_decodes_exactly_two_airframes():
    """If this count grows, an open O3 decoder finally landed."""
    decodable = {k for k, a in fleet.AIRFRAMES.items() if a.open_decodable}
    assert decodable == set(fleet.OPEN_DECODABLE) == {"mini_2", "mavic_air_2"}
    for key in decodable:
        assert fleet.AIRFRAMES[key].droneid_encrypted is False
        assert fleet.AIRFRAMES[key].tier == "A"


def test_no_encrypted_airframe_is_claimed_as_decodable():
    """The invariant that would matter most if it were ever broken."""
    for key, airframe in fleet.AIRFRAMES.items():
        if airframe.droneid_encrypted:
            assert not airframe.open_decodable, key
            assert not airframe.firmware_decodable, key


def test_ocusync_3_is_plaintext_but_needs_the_closed_firmware():
    """Plaintext is not the same as readable by open code."""
    for key in ("mini_3_pro", "air_2s", "mavic_3"):
        airframe = fleet.AIRFRAMES[key]
        assert airframe.droneid_encrypted is False
        assert airframe.firmware_decodable and not airframe.open_decodable


def test_every_class_label_agrees_with_the_broadcast_obligation():
    """C1 and above must broadcast; C0 and unmarked are exempt."""
    for key, airframe in fleet.AIRFRAMES.items():
        if airframe.broadcasts_remote_id:
            assert airframe.eu_class not in (None, "C0"), key
        if airframe.eu_class == "C0":
            assert not airframe.broadcasts_remote_id, key


def test_weight_and_class_do_not_contradict_each_other():
    for key, airframe in fleet.AIRFRAMES.items():
        if airframe.eu_class == "C0" and airframe.takeoff_weight_g is not None:
            assert airframe.takeoff_weight_g <= 250.0, key


@pytest.mark.parametrize("query", ["Mini 4 Pro", "mini_4_pro", "MINI4PRO",
                                   "mini-4-pro", "  Mini 4 Pro  "])
def test_lookup_is_forgiving_about_how_a_name_is_written(query):
    assert fleet.lookup(query) is fleet.AIRFRAMES["mini_4_pro"]


def test_an_unknown_airframe_returns_nothing_rather_than_a_guess():
    assert fleet.lookup("Parrot Anafi") is None
    assert fleet.observation_tier("Parrot Anafi") is None
    assert fleet.identity_sources("Parrot Anafi") == []


def test_every_tier_letter_is_documented():
    for airframe in fleet.AIRFRAMES.values():
        assert airframe.tier in fleet.TIERS


def test_every_row_carries_its_confidence_and_serialises():
    for key, airframe in fleet.AIRFRAMES.items():
        assert airframe.confidence in ("verified", "snippet"), key
        row = airframe.to_dict()
        assert row["name"] and row["tier"] in fleet.TIERS


def test_product_types_are_only_claimed_where_open_code_maps_one():
    """The integer is printed as a model name, so a wrong one is worse than none."""
    for key, airframe in fleet.AIRFRAMES.items():
        if airframe.product_type is not None:
            assert airframe.open_decodable, key
