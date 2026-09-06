"""Tests for antsdr_toolkit.bridges.dji_droneid: parsers, encoder, framers and transports.

Network tests use ephemeral ports on 127.0.0.1, run the blocking transports in
daemon threads and always bound waits with timeouts so they never hang.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from collections.abc import Callable

import pytest

from antsdr_toolkit.bridges.dji_droneid import (
    DjiDroneIdReport,
    LegacyFramer,
    LineFramer,
    connect_legacy,
    encode_csv_line,
    parse_csv_line,
    parse_legacy_frame,
    receive_udp,
    serve_new_firmware,
)

O2_LINE = ("dji_O,2,2444.5,-52,DJI Mini 2(63),3N2CJ5K001Z7XY,4.8952,52.3702,4.8950,52.3700,"
           "4.8951,52.3701,12.0|100.0,300|400|-50;")
O4_LINE = "dji_O,4,5775.0,-70,dji(4f8a2c),,0.0,0.0,0.0,0.0,0.0,0.0,0.0|0.0,0|0|0"
TIMEOUT = 5.0
FIELD_NAMES = {
    "protocol", "encrypted", "serial", "model", "model_code", "hash_id", "freq_mhz", "rssi_dbm",
    "drone_lat", "drone_lon", "pilot_lat", "pilot_lon", "home_lat", "home_lon", "altitude_m",
    "height_agl_m", "speed_h_m_s", "speed_v_m_s", "raw", "received_at_utc",
}


def wait_for(pred: Callable[[], bool], timeout: float = TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def assert_reports_close(a: DjiDroneIdReport, b: DjiDroneIdReport, *,
                         ignore: tuple[str, ...] = ("raw", "received_at_utc")) -> None:
    da, db = a.to_dict(), b.to_dict()
    for key, va in da.items():
        if key in ignore:
            continue
        if isinstance(va, float):
            assert db[key] == pytest.approx(va), key
        else:
            assert db[key] == va, key


def build_legacy_frame(*, serial: str = "1581F5BKD225C00A5NUD", model: str = "DJI Mavic 3",
                       app=(52.37, 4.895), drone=(52.3702, 4.8952), home=(52.3701, 4.8951),
                       height: float = 100.0, altitude: float = 120.0, freq: float = 2444.5,
                       speeds=(3.0, 4.0, -1.0), rssi: int = -55, ptype: int = 0x01) -> bytes:
    """Build a legacy frame with struct, following the documented offsets independently."""
    payload = bytearray(227)
    payload[0:64] = serial.encode().ljust(64, b"\x00")
    payload[64:128] = model.encode().ljust(64, b"\x00")
    values = [app[0], app[1], drone[0], drone[1], height, altitude, home[0], home[1], freq, *speeds]
    for i, value in enumerate(values):  # 129, 137, ..., 217
        struct.pack_into("<d", payload, 129 + 8 * i, value)
    struct.pack_into("<h", payload, 225, rssi)
    return bytes([0xAA, 0x55, ptype]) + struct.pack("<H", 5 + len(payload)) + bytes(payload)


def start_thread(target, *args, **kwargs) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return thread


# --------------------------------------------------------------------------
# CSV parser / encoder
# --------------------------------------------------------------------------
def test_parse_o2_line_fields():
    r = parse_csv_line(O2_LINE, received_at_utc="2026-09-05T12:00:00+00:00")
    assert r is not None and r.protocol == "O2" and r.encrypted is False
    assert (r.serial, r.model, r.model_code) == ("3N2CJ5K001Z7XY", "DJI Mini 2", "63")
    assert r.hash_id is None
    assert r.freq_mhz == 2444.5 and r.rssi_dbm == -52 and isinstance(r.rssi_dbm, int)
    assert (r.drone_lat, r.drone_lon) == (52.3702, 4.8952)  # lon precedes lat on the wire
    assert (r.pilot_lat, r.pilot_lon) == (52.37, 4.895)
    assert (r.home_lat, r.home_lon) == (52.3701, 4.8951)
    assert r.altitude_m == pytest.approx(120.0)  # first value x10 as the host tooling does
    assert r.height_agl_m == 100.0
    assert r.speed_h_m_s == pytest.approx(5.0)  # hypot(300, 400) cm/s -> m/s
    assert r.speed_v_m_s == pytest.approx(-0.5)
    assert r.raw == O2_LINE and r.received_at_utc == "2026-09-05T12:00:00+00:00"


def test_parse_o4_hash_line():
    r = parse_csv_line(O4_LINE)
    assert r is not None and r.protocol == "O4" and r.encrypted is True
    assert r.hash_id == "4f8a2c" and r.model is None and r.model_code is None and r.serial is None
    assert r.freq_mhz == 5775.0 and r.rssi_dbm == -70
    assert r.drone_lat is None and r.pilot_lon is None and r.home_lat is None
    assert r.altitude_m == 0.0 and r.speed_h_m_s == 0.0


def test_parse_tolerates_whitespace_crlf_and_missing_semicolon():
    variants = [O2_LINE + "\r\n", "  " + O2_LINE.rstrip(";") + "\n", O2_LINE.rstrip(";")]
    ref = parse_csv_line(O2_LINE)
    for line in variants:
        r = parse_csv_line(line)
        assert r is not None
        assert_reports_close(ref, r)
        assert "\n" not in r.raw


def test_unknown_and_out_of_range_positions_become_none():
    line = ("dji_O,3,2414.5,-60,DJI Air 3(88),SER1,4.9,52.4,0.0,0.0,200.0,52.1,"
            "5.5|20.0,0|0|0")
    r = parse_csv_line(line)
    assert r is not None and r.protocol == "O3"
    assert (r.drone_lat, r.drone_lon) == (52.4, 4.9)
    assert (r.pilot_lat, r.pilot_lon) == (None, None)  # 0.0 = unknown
    assert (r.home_lat, r.home_lon) == (None, None)  # lon 200 out of range -> whole pair dropped
    assert r.altitude_m == pytest.approx(55.0)


@pytest.mark.parametrize("line", [
    "", "=", "   \n", "dji_O", "dji_O,2", "dji_O,2,2444.5,-52,DJI Mini 2(63),SER,1,2,3,4,5,6,7",
    "hello,2,2444.5,-52,DJI Mini 2(63),SER,1,2,3,4,5,6,7|8,9|10|11",
    O2_LINE.replace("dji_O,2,", "dji_O,9,"), O2_LINE.replace("dji_O,2,", "dji_O,,"),
    "debug: frame sync lost", "dji_O2,2,2444.5,-52,x(1),s,1,2,3,4,5,6,7|8,9|10|11",
])
def test_malformed_lines_return_none(line):
    assert parse_csv_line(line) is None


def test_bad_numeric_fields_become_none_without_rejecting_line():
    line = "dji_O,2,abc,??,DJI Mini 2(63),SER,4.9,52.4,4.9,52.4,4.9,52.4,x|y,1|2"
    r = parse_csv_line(line)
    assert r is not None and r.serial == "SER" and r.model == "DJI Mini 2"
    assert r.freq_mhz is None and r.rssi_dbm is None
    assert r.altitude_m is None and r.height_agl_m is None
    assert r.speed_h_m_s is None and r.speed_v_m_s is None
    assert (r.drone_lat, r.drone_lon) == (52.4, 4.9)


def test_model_field_variants():
    base = "dji_O,2,2444.5,-52,{},SER,4.9,52.4,0,0,0,0,1|2,0|0|0"
    r = parse_csv_line(base.format("DJI Mavic 3 (Pro)(78)"))
    assert (r.model, r.model_code) == ("DJI Mavic 3 (Pro)", "78")
    r = parse_csv_line(base.format("Unknown"))
    assert (r.model, r.model_code) == ("Unknown", None)
    r = parse_csv_line(base.format("()"))
    assert (r.model, r.model_code) == (None, None)
    r = parse_csv_line(base.format("dji()").replace("dji_O,2,", "dji_O,4,"))
    assert r.encrypted and r.hash_id is None and r.model is None


def test_csv_round_trip_o2_and_o4():
    for line in (O2_LINE, O4_LINE):
        first = parse_csv_line(line)
        encoded = encode_csv_line(first)
        assert encoded.startswith("dji_O,") and encoded.endswith(";")
        assert encoded.count(",") == 13
        assert_reports_close(first, parse_csv_line(encoded))
    assert encode_csv_line(parse_csv_line(O4_LINE)).startswith("dji_O,4,5775.0,-70,dji(4f8a2c),,")


def test_encode_from_constructed_report():
    rep = DjiDroneIdReport(protocol="O3", serial="S1", model="DJI Air 3", model_code="88",
                           freq_mhz=2414.5, rssi_dbm=-40, drone_lat=51.5, drone_lon=-0.12,
                           pilot_lat=51.49, pilot_lon=-0.11, altitude_m=55.0, height_agl_m=30.0,
                           speed_h_m_s=7.5, speed_v_m_s=1.0)
    back = parse_csv_line(encode_csv_line(rep))
    assert back is not None
    assert_reports_close(rep, back)
    # Unknown values encode as 0.0/empty and a legacy report is emitted as OcuSync 2.
    legacy = DjiDroneIdReport(protocol="legacy", serial="L1", model="DJI Mini 3")
    line = encode_csv_line(legacy)
    assert line.startswith("dji_O,2,0.0,0,DJI Mini 3(),L1,0.0,0.0,")
    assert parse_csv_line(line).protocol == "O2"


def test_report_validation_and_to_dict_is_json_serialisable():
    with pytest.raises(ValueError):
        DjiDroneIdReport(protocol="O5")
    d = parse_csv_line(O2_LINE).to_dict()
    assert set(d) == FIELD_NAMES
    assert json.loads(json.dumps(d))["model"] == "DJI Mini 2"


# --------------------------------------------------------------------------
# Framers
# --------------------------------------------------------------------------
def test_line_framer_splits_lines_across_chunks():
    f = LineFramer()
    assert f.feed(b"dji_O,2,ab") == []
    assert f.feed(b"c\r\n=\ndji_O,3") == ["dji_O,2,abc", "="]
    assert f.feed(b",x;dji_O,4,partial") == ["dji_O,3,x"]  # ';' also terminates a record
    assert f.feed(b"") == []
    assert f.flush() == ["dji_O,4,partial"]
    assert f.flush() == []


def test_line_framer_newline_only_and_oversize_guard():
    f = LineFramer(delimiters=b"\n")
    assert f.feed(b"a;b\nc;") == ["a;b"]
    assert f.flush() == ["c;"]
    g = LineFramer(max_line_bytes=16)
    assert g.feed(b"x" * 20) == []  # garbage without terminator is discarded
    assert g.feed(b"ok\n") == ["ok"]
    with pytest.raises(ValueError):
        LineFramer(delimiters=b"")


def test_legacy_framer_reassembles_across_chunks():
    frame = build_legacy_frame()
    f = LegacyFramer()
    assert f.feed(frame[:50]) == []
    assert f.feed(frame[50:] + frame[:10]) == [frame]
    assert f.feed(frame[10:] + frame) == [frame, frame]
    assert f.feed(b"") == []
    assert f.feed(b"\xaa\x55\x02" + struct.pack("<H", 6) + b"x") == [b"\xaa\x55\x02\x06\x00x"]


def test_legacy_framer_discards_corrupt_stream_instead_of_stalling():
    frame = build_legacy_frame()
    f = LegacyFramer()
    assert f.feed(b"\x00\x00\x01\x02\x00" + frame) == []  # length 2 < header: buffer dropped
    assert f.feed(frame) == [frame]  # framing restarts cleanly on the next chunk
    huge = b"\xaa\x55\x01" + struct.pack("<H", 60000)
    assert f.feed(huge + frame[:20]) == []  # bogus length must not make the bridge wait forever
    assert f.feed(frame) == [frame]
    assert LegacyFramer(max_frame_bytes=100).feed(frame) == []  # tighter bound is configurable


# --------------------------------------------------------------------------
# Legacy binary frames
# --------------------------------------------------------------------------
def test_parse_legacy_frame_fields():
    frame = build_legacy_frame()
    r = parse_legacy_frame(frame, received_at_utc="t0")
    assert r is not None and r.protocol == "legacy" and r.encrypted is False
    assert r.serial == "1581F5BKD225C00A5NUD" and r.model == "DJI Mavic 3"
    assert r.model_code is None and r.hash_id is None
    assert r.freq_mhz == 2444.5 and r.rssi_dbm == -55
    assert (r.drone_lat, r.drone_lon) == (52.3702, 4.8952)
    assert (r.pilot_lat, r.pilot_lon) == (52.37, 4.895)  # app_* fields
    assert (r.home_lat, r.home_lon) == (52.3701, 4.8951)
    assert r.altitude_m == 120.0 and r.height_agl_m == 100.0
    assert r.speed_h_m_s == pytest.approx(5.0) and r.speed_v_m_s == -1.0
    assert r.raw == frame.hex() and r.received_at_utc == "t0"


def test_parse_legacy_frame_hz_frequency_unknown_position_and_trailing_bytes():
    r = parse_legacy_frame(build_legacy_frame(freq=2444.5e6, app=(0.0, 0.0), serial=""))
    assert r.freq_mhz == pytest.approx(2444.5)
    assert r.pilot_lat is None and r.pilot_lon is None and r.serial is None
    frame = build_legacy_frame()
    assert_reports_close(parse_legacy_frame(frame), parse_legacy_frame(frame + b"trailing"))


def test_parse_legacy_frame_rejects_other_types_and_short_frames():
    assert parse_legacy_frame(build_legacy_frame(ptype=0x02)) is None
    assert parse_legacy_frame(build_legacy_frame()[:100]) is None
    assert parse_legacy_frame(b"\xaa\x55\x01") is None
    assert parse_legacy_frame(b"") is None


# --------------------------------------------------------------------------
# Transports (end to end on 127.0.0.1)
# --------------------------------------------------------------------------
def test_serve_new_firmware_end_to_end():
    reports: list[DjiDroneIdReport] = []
    stop, listening, addr = threading.Event(), threading.Event(), {}

    def on_listening(bound):
        addr["v"] = bound
        listening.set()

    def on_report(report):
        reports.append(report)
        if len(reports) == 1:
            raise RuntimeError("consumer bug must not kill the bridge")

    thread = start_thread(serve_new_firmware, "127.0.0.1", 0, on_report,
                          stop_event=stop, on_listening=on_listening)
    try:
        assert listening.wait(TIMEOUT) and addr["v"][1] > 0
        payload = (O2_LINE + "\r\n=\n" + O4_LINE + "\n").encode()
        cut1, cut2 = 25, len(O2_LINE) + 8  # split inside line 1 and inside line 2
        with socket.create_connection(addr["v"], timeout=TIMEOUT) as fake_firmware:
            for part in (payload[:cut1], payload[cut1:cut2], payload[cut2:]):
                fake_firmware.sendall(part)
                time.sleep(0.02)
        assert wait_for(lambda: len(reports) == 2)
        assert [r.protocol for r in reports] == ["O2", "O4"]
        assert reports[0].serial == "3N2CJ5K001Z7XY" and reports[1].hash_id == "4f8a2c"
        assert reports[0].received_at_utc and reports[0].received_at_utc.endswith("+00:00")
        time.sleep(0.05)
        assert len(reports) == 2
    finally:
        stop.set()
        thread.join(TIMEOUT)
    assert not thread.is_alive()


def test_receive_udp_end_to_end():
    reports: list[DjiDroneIdReport] = []
    stop, listening, addr = threading.Event(), threading.Event(), {}

    def on_listening(bound):
        addr["v"] = bound
        listening.set()

    thread = start_thread(receive_udp, "127.0.0.1", 0, reports.append,
                          stop_event=stop, on_listening=on_listening)
    try:
        assert listening.wait(TIMEOUT)
        payload = (O2_LINE + "\n").encode()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload[:30], addr["v"])  # datagrams split the line
            time.sleep(0.02)
            sock.sendto(payload[30:], addr["v"])
        assert wait_for(lambda: len(reports) == 1)
        assert reports[0].protocol == "O2" and reports[0].drone_lat == 52.3702
    finally:
        stop.set()
        thread.join(TIMEOUT)
    assert not thread.is_alive()


def test_connect_legacy_end_to_end_with_reconnect():
    reports: list[DjiDroneIdReport] = []
    connected: list[tuple] = []
    stop = threading.Event()
    frame = build_legacy_frame()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        srv.settimeout(TIMEOUT)
        host, port = srv.getsockname()[:2]
        thread = start_thread(connect_legacy, host, port, reports.append,
                              stop_event=stop, reconnect_s=0.1, on_connected=connected.append)
        try:
            conn, _ = srv.accept()
            with conn:
                conn.sendall(frame[:100])
                time.sleep(0.02)
                conn.sendall(frame[100:])
                assert wait_for(lambda: len(reports) == 1)
            conn2, _ = srv.accept()  # client reconnects after the drop
            with conn2:
                other = build_legacy_frame(rssi=-30, ptype=0x02)  # non-DroneID type is skipped
                conn2.sendall(other + frame)
                assert wait_for(lambda: len(reports) == 2)
        finally:
            stop.set()
            thread.join(TIMEOUT)
    assert not thread.is_alive() and len(connected) == 2
    assert reports[0].serial == "1581F5BKD225C00A5NUD" and reports[1].rssi_dbm == -55
    assert reports[0].received_at_utc and reports[0].received_at_utc.endswith("+00:00")


def test_connect_legacy_without_reconnect_returns_when_peer_closes():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        srv.settimeout(TIMEOUT)
        host, port = srv.getsockname()[:2]
        thread = start_thread(connect_legacy, host, port, lambda r: None, reconnect_s=0.0)
        conn, _ = srv.accept()
        conn.close()
        thread.join(TIMEOUT)
    assert not thread.is_alive()
    # Connection refused with reconnecting disabled also returns promptly.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    thread = start_thread(connect_legacy, "127.0.0.1", free_port, lambda r: None, reconnect_s=0.0)
    thread.join(TIMEOUT)
    assert not thread.is_alive()
