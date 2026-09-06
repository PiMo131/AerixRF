"""DJI's proprietary DroneID carried in an 802.11 vendor element.

A different payload from standard Remote ID, under a different OUI, and the
one remaining published route to a serial number for an airframe whose
OcuSync DroneID is encrypted and whose class mark carries no broadcast
obligation. Whether a modern airframe actually emits it in Wi-Fi mode is
untested, so these tests cover the parser, not the claim.
"""

from __future__ import annotations

import struct

import pytest

from antsdr_toolkit.droneid import constants as C
from antsdr_toolkit.remoteid import dji_wifi as dw

SERIAL = b"1581F5NEO0000001"
LAT, LON = 51.9225, 4.47917


def _confident(lat=LAT, lon=LON, serial=SERIAL, version=2, seq=7, state=0x1234):
    return struct.pack("<BHH16sii", version, seq, state, serial,
                       round(lon * C.COORD_SCALE), round(lat * C.COORD_SCALE))


def _extended():
    return struct.pack("<hhhhhhQiiiiBB", 42, 61, 3, -1, 0, 21400, 1_756_000_000_000,
                       round(51.9230 * C.COORD_SCALE), round(4.4799 * C.COORD_SCALE),
                       round(4.4799 * C.COORD_SCALE), round(51.9231 * C.COORD_SCALE), 63, 0)


def test_a_beacon_yields_the_serial_and_the_position():
    beacon = dw.parse_dji_beacon(dw.build_beacon(_confident(), ssid="DJI-Neo"))
    assert beacon is not None
    assert beacon.serial == SERIAL.decode()
    assert beacon.position == pytest.approx((LAT, LON), abs=1e-5)
    assert beacon.sequence == 7 and beacon.version == 2
    assert beacon.ssid == "DJI-Neo"
    assert beacon.transmitter_mac == "60:60:1f:00:00:03"


def test_the_uncertain_fields_are_withheld_unless_asked_for():
    """The reference parser stops at 30 bytes because it stopped trusting the order.

    Presenting a field a reference implementation deliberately declined to
    decode as though it were a measurement is the error this guards.
    """
    record = _confident() + _extended()
    plain = dw.parse_dji_beacon(dw.build_beacon(record))
    assert plain.extended is None
    assert plain.product_name is None

    asked = dw.parse_dji_beacon(dw.build_beacon(record), extended=True)
    assert asked.extended is not None
    assert asked.extended["height_m"] == 42.0
    assert asked.extended["altitude_m"] == 61.0
    assert asked.extended["home_position"] is not None
    assert asked.product_name == "Mini 2"


def test_the_uncertain_fields_carry_their_warning():
    """A consumer reading the JSON must see the caveat, not just the numbers."""
    beacon = dw.parse_dji_beacon(dw.build_beacon(_confident() + _extended()), extended=True)
    assert "_warning" in beacon.extended
    assert "inferred" in beacon.extended["_warning"]
    # And the serialised form names the uncertainty in the key itself.
    assert "extended_unverified_layout" in beacon.to_dict()
    assert "extended" not in beacon.to_dict()


def test_the_confident_boundary_matches_the_struct_it_describes():
    """Counted by hand this comes out wrong; it is derived for that reason."""
    assert dw.CONFIDENT_BYTES == dw._HEADER.size + dw._CONFIDENT.size
    # 4 header + (1 version + 2 seq + 2 state + 16 serial + 4 lon + 4 lat)
    assert dw.CONFIDENT_BYTES == 33


def test_coordinates_follow_the_same_rules_as_everywhere_else():
    """Per-coordinate ranges, and a zero pair rather than a zero field (H2)."""
    zero = struct.pack("<BHH16sii", 2, 1, 0, SERIAL, 0, 0)
    assert dw.parse_dji_beacon(dw.build_beacon(zero)).position is None

    # A lone zero longitude is the Greenwich meridian, which is a real place.
    meridian = struct.pack("<BHH16sii", 2, 1, 0, SERIAL, 0, round(51.9 * C.COORD_SCALE))
    assert dw.parse_dji_beacon(dw.build_beacon(meridian)).position is not None

    # An impossible latitude is rejected, and takes its longitude with it.
    bad = struct.pack("<BHH16sii", 2, 1, 0, SERIAL,
                      round(4.4 * C.COORD_SCALE), round(150.0 * C.COORD_SCALE))
    assert dw.parse_dji_beacon(dw.build_beacon(bad)).position is None


def test_the_coordinate_scale_is_shared_with_the_ocusync_decoder():
    """Same encoding, so it must be the same constant, not a second copy."""
    beacon = dw.parse_dji_beacon(dw.build_beacon(_confident()))
    assert beacon.latitude == pytest.approx(LAT, abs=1e-5)
    import math
    assert C.COORD_SCALE == pytest.approx(1e7 * math.pi / 180.0, rel=1e-15)


def test_the_flight_purpose_subcommand_is_recognised_and_not_decoded():
    """Free text the operator typed. Skipped, not treated as telemetry."""
    frame = dw.build_beacon(b"whatever", subcommand=dw.SUBCOMMAND_FLIGHT_PURPOSE)
    assert dw.parse_dji_beacon(frame) is None


def test_a_frame_without_a_dji_element_returns_none():
    from antsdr_toolkit.remoteid import odid, wifi
    standard = wifi.build_beacon(
        bytes([1]) + odid.encode_pack([odid.encode_basic_id("NOT-DJI")]))
    assert dw.parse_dji_beacon(standard) is None
    assert dw.parse_dji_beacon(b"") is None
    assert dw.parse_dji_beacon(b"\x00" * 40) is None


def test_another_vendors_element_is_not_mistaken_for_dji():
    body = bytes([221, 5]) + b"\x00\x50\xf2" + bytes([1, 0])
    assert dw.find_dji_element(body) is None


@pytest.mark.parametrize("length", [0, 1, 3])
def test_a_truncated_header_raises_rather_than_guessing(length):
    with pytest.raises(ValueError, match="header is 4 bytes"):
        dw.parse_flight_reg(bytes(length))


def test_a_telemetry_record_too_short_to_be_one_raises():
    """Claiming to be telemetry and being too small is malformed, not boring."""
    short = dw._HEADER.pack(0, 0, 0, dw.SUBCOMMAND_FLIGHT_REG) + bytes(10)
    with pytest.raises(ValueError, match="needs 29 bytes"):
        dw.parse_flight_reg(short)


def test_asking_for_extended_fields_that_are_not_there_is_not_an_error():
    """A short record is common; it must degrade, not raise."""
    beacon = dw.parse_dji_beacon(dw.build_beacon(_confident()), extended=True)
    assert beacon is not None and beacon.extended is None


def test_build_beacon_refuses_an_oversized_element():
    with pytest.raises(ValueError, match="255 bytes"):
        dw.build_beacon(b"\x00" * 300)


def test_the_cli_reads_both_element_types_from_one_capture(tmp_path, capsys):
    """The point of wiring it in: one pcap, both payloads, labelled apart."""
    from antsdr_toolkit import cli_remoteid
    from antsdr_toolkit.remoteid import odid, wifi

    standard = wifi.build_beacon(
        bytes([1]) + odid.encode_pack([
            odid.encode_basic_id("STANDARD-RID-1"),
            odid.encode_location(latitude=LAT, longitude=LON)]),
        ssid="RID-STD")
    dji = dw.build_beacon(_confident(), ssid="DJI-Neo")

    path = tmp_path / "mixed.pcap"
    with open(path, "wb") as handle:
        handle.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 105))
        for index, frame in enumerate((standard, dji, dji)):
            handle.write(struct.pack("<IIII", 1_757_000_000 + index, 0,
                                     len(frame), len(frame)))
            handle.write(frame)

    assert cli_remoteid.main([str(path), "--unique"]) == 0
    out = capsys.readouterr().out
    assert "1 standard Remote ID" in out and "2 DJI DroneID (Wi-Fi)" in out
    assert "STANDARD-RID-1" in out and SERIAL.decode() in out
    assert "standard Remote ID" in out and "DJI DroneID over Wi-Fi" in out
