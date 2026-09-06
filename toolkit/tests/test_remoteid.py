"""Standard Remote ID decoding: ASTM F3411 / EN 4709 over Wi-Fi Beacon.

The scaling rules are where a from-memory implementation goes wrong, so most
of these tests are about numbers rather than about framing: the two-scale
horizontal speed, the altitude offset, the direction flag, the two different
timestamp epochs, and the sentinel values that must decode to "unknown"
rather than to a confident wrong reading.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import struct

import pytest

from antsdr_toolkit.remoteid import odid, wifi

SERIAL = "1581F5FMD24AB00C1234"


def _pack_bytes(**location) -> bytes:
    return odid.encode_pack([
        odid.encode_basic_id(SERIAL),
        odid.encode_location(**{"latitude": 51.9225, "longitude": 4.47917, **location}),
        odid.encode_system(operator_latitude=51.9230, operator_longitude=4.47990),
    ])


# ------------------------------------------------------------------ framing


def test_a_beacon_frame_yields_the_identity_and_both_positions():
    frame = wifi.build_beacon(bytes([7]) + _pack_bytes(altitude_geo_m=61.0, height_m=42.0),
                              ssid="RID-1581F5FMD24AB")
    beacon = wifi.parse_beacon(frame)
    assert beacon is not None
    summary = beacon.summary()
    assert summary["uas_id"] == SERIAL
    assert summary["id_type"] == "serial_number"
    assert summary["position"] == pytest.approx((51.9225, 4.47917), abs=1e-6)
    assert summary["operator_position"] == pytest.approx((51.9230, 4.47990), abs=1e-6)
    assert summary["message_counter"] == 7
    assert summary["ssid"] == "RID-1581F5FMD24AB"
    assert beacon.transmitter_mac == "60:60:1f:00:00:01"


def test_a_radiotap_header_is_stripped():
    frame = wifi.build_beacon(bytes([1]) + _pack_bytes())
    radiotap = struct.pack("<BBHI", 0, 0, 12, 0) + b"\x00" * 4
    assert wifi.strip_radiotap(radiotap + frame) == frame
    assert wifi.parse_beacon(radiotap + frame) is not None
    # A frame that merely starts with two zero bytes is not radiotap.
    assert wifi.strip_radiotap(b"\x00\x00\xff\xff" + b"x" * 20).startswith(b"\x00\x00")


def test_frames_without_open_drone_id_return_none_rather_than_raising():
    """Almost every frame in the air is one of these."""
    plain = wifi.build_beacon(bytes([0]) + _pack_bytes())
    body_start = 24 + wifi.BEACON_FIXED_BYTES
    # An ordinary beacon: same header, but only an SSID element.
    ordinary = plain[:body_start] + bytes([0, 4]) + b"wifi"
    assert wifi.parse_beacon(ordinary) is None
    assert wifi.parse_beacon(b"") is None
    assert wifi.parse_beacon(b"\x00" * 40) is None
    # A data frame, not a beacon.
    data_frame = bytes([0x08]) + plain[1:]
    assert wifi.parse_beacon(data_frame) is None


def test_a_vendor_element_from_someone_else_is_ignored():
    """Only ASD-STAN's OUI with type 0x0D is Open Drone ID."""
    body = bytes([221, 5]) + b"\x00\x50\xf2" + bytes([1, 0])   # Microsoft WPA
    assert wifi.find_odid_element(body) is None
    wrong_type = bytes([221, 5]) + wifi.ASD_STAN_OUI + bytes([0x0C, 0])
    assert wifi.find_odid_element(wrong_type) is None
    right = bytes([221, 6]) + wifi.ASD_STAN_OUI + bytes([wifi.ODID_OUI_TYPE, 9, 9])
    assert wifi.find_odid_element(right) == bytes([9, 9])


def test_a_truncated_element_list_keeps_what_came_before_it():
    good = bytes([0, 3]) + b"abc"
    truncated = bytes([221, 40]) + b"short"
    elements = list(wifi.iter_information_elements(good + truncated))
    assert elements == [(0, b"abc")]


# ------------------------------------------------------------------ scaling


@pytest.mark.parametrize("speed", [0.0, 1.0, 63.0, 63.75, 64.0, 100.0, 254.0])
def test_horizontal_speed_survives_both_of_its_scales(speed):
    """Below 63.75 m/s the step is 0.25, above it 0.75. One scale is wrong."""
    raw = odid.encode_location(latitude=0.1, longitude=0.1, speed_h_m_s=speed)
    decoded = odid.decode_message(raw)
    assert decoded.speed_h_m_s == pytest.approx(speed, abs=0.4)


@pytest.mark.parametrize("direction", [0.0, 90.0, 179.0, 180.0, 181.0, 270.0, 359.0])
def test_direction_survives_the_east_west_flag(direction):
    """360 does not fit in a byte, so the top bit of the circle is a flag."""
    decoded = odid.decode_message(
        odid.encode_location(latitude=0.1, longitude=0.1, direction_deg=direction))
    assert decoded.direction_deg == pytest.approx(direction, abs=1.0)


@pytest.mark.parametrize("altitude", [-999.0, -100.0, 0.0, 42.0, 1000.0, 5000.0])
def test_altitude_carries_its_offset(altitude):
    """Encoded as (metres + 1000) / 0.5, so the resolution is half a metre."""
    decoded = odid.decode_message(
        odid.encode_location(latitude=0.1, longitude=0.1, altitude_geo_m=altitude))
    assert decoded.altitude_geo_m == pytest.approx(altitude, abs=0.25)


@pytest.mark.parametrize("speed", [-62.0, -1.5, 0.0, 3.0, 62.0])
def test_vertical_speed_is_signed(speed):
    decoded = odid.decode_message(
        odid.encode_location(latitude=0.1, longitude=0.1, speed_v_m_s=speed))
    assert decoded.speed_v_m_s == pytest.approx(speed, abs=0.25)


def test_latitude_and_longitude_keep_their_precision():
    """Degrees times 10^7 is about a centimetre, so nothing should be lost."""
    decoded = odid.decode_message(
        odid.encode_location(latitude=-33.8688197, longitude=151.2092955))
    assert decoded.latitude == pytest.approx(-33.8688197, abs=1e-7)
    assert decoded.longitude == pytest.approx(151.2092955, abs=1e-7)


def test_the_two_timestamps_use_two_different_epochs():
    """Location counts tenths of a second into the hour; System counts from 2019."""
    location = odid.decode_message(
        odid.encode_location(latitude=0.1, longitude=0.1, timestamp_s_into_hour=1234.5))
    assert location.timestamp_s_into_hour == pytest.approx(1234.5, abs=0.05)

    when = dt.datetime(2026, 9, 6, 10, 30, tzinfo=dt.timezone.utc)
    system = odid.decode_message(
        odid.encode_system(operator_latitude=0.1, operator_longitude=0.1, timestamp=when))
    assert system.timestamp == when
    assert odid.SYSTEM_EPOCH == dt.datetime(2019, 1, 1, tzinfo=dt.timezone.utc)


# ------------------------------------------------------------ unknown values


def test_sentinels_decode_to_unknown_not_to_a_number():
    """The commonest way a Remote ID display invents data."""
    raw = bytearray(odid.encode_location(latitude=0.1, longitude=0.1))
    raw[2] = 255            # direction: invalid is 361, so 255 with no flag
    raw[3] = 255            # horizontal speed
    raw[4] = 63             # vertical speed
    raw[15:17] = struct.pack("<H", 0)   # geo altitude: encodes to -1000 m
    raw[21:23] = struct.pack("<H", 0xFFFF)
    decoded = odid.decode_message(bytes(raw))
    assert decoded.direction_deg is None
    assert decoded.speed_h_m_s is None
    assert decoded.speed_v_m_s is None
    assert decoded.altitude_geo_m is None
    assert decoded.timestamp_s_into_hour is None


def test_a_null_island_position_is_no_fix_not_a_position():
    raw = bytearray(odid.encode_location(latitude=0.0, longitude=0.0))
    decoded = odid.decode_message(bytes(raw))
    assert decoded.latitude is None and decoded.longitude is None
    assert decoded.position is None


# ---------------------------------------------------------------- semantics


def test_the_c0_class_is_flagged_as_exempt_from_broadcasting():
    """The finding that decides whether a Neo or a Mini 4 Pro is visible."""
    exempt = odid.decode_message(
        odid.encode_system(operator_latitude=51.9, operator_longitude=4.4, class_eu=1))
    obliged = odid.decode_message(
        odid.encode_system(operator_latitude=51.9, operator_longitude=4.4, class_eu=2))
    assert exempt.class_eu == "C0" and exempt.exempt_from_remote_id
    assert obliged.class_eu == "C1" and not obliged.exempt_from_remote_id


def test_basic_id_distinguishes_a_serial_from_a_session_id():
    serial = odid.decode_message(odid.encode_basic_id("ABC123", id_type=1))
    session = odid.decode_message(odid.encode_basic_id("ABC123", id_type=4))
    assert serial.is_serial and serial.id_type == "serial_number"
    assert not session.is_serial and session.id_type == "specific_session_id"
    assert serial.ua_type == "helicopter_or_multirotor"


def test_a_short_identifier_is_not_padded_with_nul_bytes():
    decoded = odid.decode_message(odid.encode_basic_id("SHORT"))
    assert decoded.uas_id == "SHORT"


@pytest.mark.parametrize("type_code", [0, 1, 2, 3, 4, 5])
def test_every_defined_message_type_decodes_to_its_own_class(type_code):
    raw = bytes([(type_code << 4) | 2]) + bytes(24)
    decoded = odid.decode_message(raw)
    assert decoded.message_type == odid.MESSAGE_TYPES[type_code]
    assert decoded.protocol_version == 2


def test_an_unknown_message_type_is_kept_not_discarded():
    decoded = odid.decode_message(bytes([(0x0A << 4) | 2]) + bytes(24))
    assert isinstance(decoded, odid.UnknownMessage)
    assert decoded.type_code == 0x0A


def test_authentication_pages_have_two_different_layouts():
    page0 = bytes([0x22, 0x10, 3, 40]) + struct.pack("<I", 1000) + bytes(17)
    first = odid.decode_message(page0)
    assert first.data_page == 0 and first.last_page_index == 3 and first.length == 40
    assert len(first.auth_data) == 17
    later = odid.decode_message(bytes([0x22, 0x11]) + bytes(23))
    assert later.data_page == 1 and later.last_page_index is None
    assert len(later.auth_data) == 23


def test_self_id_carries_free_text():
    raw = bytes([0x32, 0]) + b"survey flight".ljust(23, b"\x00")
    decoded = odid.decode_message(raw)
    assert decoded.description == "survey flight"
    assert decoded.description_type == "text"


def test_operator_id_is_read_from_its_own_message():
    raw = bytes([0x52, 0]) + b"NLD87astrdge12k".ljust(20, b"\x00") + bytes(3)
    decoded = odid.decode_message(raw)
    assert decoded.operator_id == "NLD87astrdge12k"


# ------------------------------------------------------------------ packing


def test_a_pack_round_trips_and_reports_what_it_holds():
    pack = odid.decode_pack(_pack_bytes())
    assert len(pack.messages) == 3
    assert [m.message_type for m in pack.messages] == ["basic_id", "location", "system"]
    assert pack.uas_id == SERIAL
    assert len(pack.of_type("location")) == 1


@pytest.mark.parametrize(("raw", "match"), [
    (b"", "3 bytes"),
    (bytes([0x22, 25, 1]) + bytes(25), "not a message pack"),
    (bytes([0xF2, 20, 1]) + bytes(20), "20-byte messages"),
    (bytes([0xF2, 25, 0]), "0 messages"),
    (bytes([0xF2, 25, 10]) + bytes(250), "10 messages"),
    (bytes([0xF2, 25, 3]) + bytes(30), "only 33 are present"),
])
def test_a_malformed_pack_raises_rather_than_returning_what_fits(raw, match):
    with pytest.raises(ValueError, match=match):
        odid.decode_pack(raw)


@pytest.mark.parametrize("length", [0, 24, 26, 50])
def test_a_message_must_be_exactly_25_bytes(length):
    with pytest.raises(ValueError, match="25 bytes"):
        odid.decode_message(bytes(length))


def test_encode_pack_rejects_wrong_sizes():
    good = odid.encode_basic_id("X")
    with pytest.raises(ValueError, match="1 to 9 messages"):
        odid.encode_pack([])
    with pytest.raises(ValueError, match="1 to 9 messages"):
        odid.encode_pack([good] * 10)
    with pytest.raises(ValueError, match="25 bytes"):
        odid.encode_pack([b"short"])


def test_service_info_needs_a_counter_and_a_pack():
    with pytest.raises(ValueError, match="counter and a pack"):
        wifi.parse_service_info(b"\x01")


def test_build_beacon_checks_its_own_arguments():
    with pytest.raises(ValueError, match="6 bytes"):
        wifi.build_beacon(b"\x00" * 30, transmitter_mac=b"\x01\x02")
    with pytest.raises(ValueError, match="255 bytes"):
        wifi.build_beacon(b"\x00" * 300)


def test_every_message_is_the_size_the_standard_says():
    """A struct format that drifts is the classic silent break here."""
    assert len(odid.encode_basic_id("X")) == odid.MESSAGE_SIZE == 25
    assert len(odid.encode_location(latitude=1.0, longitude=1.0)) == 25
    assert len(odid.encode_system(operator_latitude=1.0, operator_longitude=1.0)) == 25
    assert len(odid.encode_pack([odid.encode_basic_id("X")] * 9)) == 3 + 9 * 25


# ------------------------------------------------------------------- capture


def _write_pcap(path, frames, link_type=105):
    with open(path, "wb") as handle:
        handle.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, link_type))
        for index, frame in enumerate(frames):
            handle.write(struct.pack("<IIII", 1_757_000_000 + index, 500, len(frame), len(frame)))
            handle.write(frame)
    return str(path)


def test_a_classic_pcap_is_read_without_a_third_party_library(tmp_path):
    from antsdr_toolkit.cli_remoteid import iter_pcap_frames
    frames = [wifi.build_beacon(bytes([n]) + _pack_bytes()) for n in (1, 2, 3)]
    read = list(iter_pcap_frames(_write_pcap(tmp_path / "rid.pcap", frames)))
    assert [f for _t, f in read] == frames
    assert read[0][0] == pytest.approx(1_757_000_000.0005, abs=1e-3)
    assert [wifi.parse_beacon(f).message_counter for _t, f in read] == [1, 2, 3]


def test_a_capture_that_is_not_wifi_is_refused(tmp_path):
    from antsdr_toolkit.cli_remoteid import iter_pcap_frames
    path = _write_pcap(tmp_path / "eth.pcap", [b"\x00" * 60], link_type=1)
    with pytest.raises(ValueError, match="not 802.11"):
        list(iter_pcap_frames(path))


def test_a_file_that_is_not_a_capture_is_refused(tmp_path):
    from antsdr_toolkit.cli_remoteid import iter_pcap_frames
    path = tmp_path / "notes.txt"
    path.write_bytes(b"this is not a pcap file at all")
    with pytest.raises(ValueError, match="not a pcap"):
        list(iter_pcap_frames(str(path)))
    empty = tmp_path / "empty.pcap"
    empty.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="too short"):
        list(iter_pcap_frames(str(empty)))


def test_a_truncated_pcap_yields_the_frames_that_are_whole(tmp_path):
    """A capture cut off mid-write is ordinary; what arrived is still good."""
    from antsdr_toolkit.cli_remoteid import iter_pcap_frames
    frames = [wifi.build_beacon(bytes([n]) + _pack_bytes()) for n in (1, 2)]
    path = pathlib.Path(_write_pcap(tmp_path / "cut.pcap", frames))
    path.write_bytes(path.read_bytes()[:-20])
    assert len(list(iter_pcap_frames(str(path)))) == 1


def test_the_cli_decodes_a_capture_and_groups_by_identifier(tmp_path, capsys):
    from antsdr_toolkit import cli_remoteid
    frames = [wifi.build_beacon(bytes([n]) + _pack_bytes()) for n in (1, 2)]
    frames.append(wifi.build_beacon(
        bytes([1]) + odid.encode_pack([odid.encode_basic_id("SECOND-DRONE")]),
        transmitter_mac=b"\x60\x60\x1f\x00\x00\x02"))
    path = _write_pcap(tmp_path / "two.pcap", frames)
    assert cli_remoteid.main([path, "--unique", "--json", str(tmp_path / "out.json")]) == 0
    out = capsys.readouterr().out
    assert SERIAL in out and "SECOND-DRONE" in out
    assert "(2 beacons)" in out
    assert "2 distinct identifier(s)" in out
    written = json.loads((tmp_path / "out.json").read_text())
    assert len(written) == 3


def test_the_cli_says_so_when_nothing_decodes(tmp_path, capsys):
    from antsdr_toolkit import cli_remoteid
    path = _write_pcap(tmp_path / "quiet.pcap", [b"\x80\x00" + b"\x00" * 60])
    assert cli_remoteid.main([path]) == 1
    assert "C0 aircraft under 250 g" in capsys.readouterr().err


def test_the_cli_decodes_a_single_hex_frame(capsys):
    from antsdr_toolkit import cli_remoteid
    frame = wifi.build_beacon(bytes([4]) + _pack_bytes())
    assert cli_remoteid.main(["--hex", frame.hex()]) == 0
    assert SERIAL in capsys.readouterr().out


# ------------------------------------------------ coordinate ranges (H2)


@pytest.mark.parametrize(("lat", "lon", "ok"), [
    (0.0, 0.0, False),          # both zero: the no-fix signal
    (51.9225, 4.47917, True),   # Rotterdam
    (-33.8688, 151.2093, True), # Sydney, southern and eastern
    (0.0, 4.47917, True),       # on the equator: a real place, not "no fix"
    (51.9225, 0.0, True),       # on the Greenwich meridian: likewise
    (90.0, 180.0, True),        # the corners are legal
    (-90.0, -180.0, True),
])
def test_positions_at_and_around_the_limits(lat, lon, ok):
    """Latitude runs to 90 and longitude to 180, and a lone zero is a place."""
    decoded = odid.decode_message(odid.encode_location(latitude=lat, longitude=lon))
    if ok:
        assert decoded.position is not None, f"{lat}, {lon} was rejected"
        assert decoded.latitude == pytest.approx(lat, abs=1e-6)
        assert decoded.longitude == pytest.approx(lon, abs=1e-6)
    else:
        assert decoded.position is None


def test_a_latitude_beyond_90_is_rejected_even_though_a_longitude_there_is_fine():
    """The bug this guards: one range used for both coordinates.

    150 degrees is an impossible latitude and an ordinary longitude. A shared
    check either accepts the first or rejects the second; it cannot be right
    about both.
    """
    impossible_lat = struct.pack("<i", round(150.0 * odid.LATLON_MULT))
    fine_lon = struct.pack("<i", round(150.0 * odid.LATLON_MULT))
    raw = bytearray(odid.encode_location(latitude=1.0, longitude=1.0))
    raw[5:9] = impossible_lat
    raw[9:13] = fine_lon
    assert odid.decode_message(bytes(raw)).position is None

    # And the mirror: -150 is an impossible latitude, a fine longitude.
    raw = bytearray(odid.encode_location(latitude=1.0, longitude=1.0))
    raw[5:9] = struct.pack("<i", round(-40.0 * odid.LATLON_MULT))
    raw[9:13] = struct.pack("<i", round(-150.0 * odid.LATLON_MULT))
    decoded = odid.decode_message(bytes(raw))
    assert decoded.position is not None, "a Pacific longitude was rejected"
    assert decoded.longitude == pytest.approx(-150.0, abs=1e-6)


def test_half_a_position_is_no_position():
    """A valid latitude beside an impossible longitude is not half a fix."""
    raw = bytearray(odid.encode_location(latitude=1.0, longitude=1.0))
    raw[9:13] = struct.pack("<i", round(200.0 * odid.LATLON_MULT))
    decoded = odid.decode_message(bytes(raw))
    assert decoded.latitude is None and decoded.longitude is None


def test_the_operator_position_uses_the_same_rules():
    system = odid.decode_message(
        odid.encode_system(operator_latitude=0.0, operator_longitude=0.0))
    assert system.operator_position is None
    ok = odid.decode_message(
        odid.encode_system(operator_latitude=-33.8688, operator_longitude=151.2093))
    assert ok.operator_position == pytest.approx((-33.8688, 151.2093), abs=1e-6)


def test_the_two_ranges_are_declared_separately():
    assert odid.LATITUDE_RANGE == (-90.0, 90.0)
    assert odid.LONGITUDE_RANGE == (-180.0, 180.0)
    assert odid.LATITUDE_RANGE != odid.LONGITUDE_RANGE
