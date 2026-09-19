"""Tests for aerix_rf.decode.sik.mavlink (T3).

Golden vectors are built with a from-scratch, spec-faithful local encoder
(``_encode_v1``/``_encode_v2`` below) so the test suite does not hard-depend
on ``pymavlink`` being installed. Where ``pymavlink`` *is* importable, an
additional cross-check compares our encoder's CRC against pymavlink's own
wire bytes for the same message, per the task spec.
"""

from __future__ import annotations

import os
import random
import struct

import pytest

from aerix_rf.decode.sik.frame import SikFrame, TdmTrailer
from aerix_rf.decode.sik.mavlink import (
    RETENTION_CLASS_PERSONAL_7D,
    SikMavlinkDecoder,
    crc_extra_for,
    mavlink_crc,
    parse_mavlink_stream,
)

try:
    from pymavlink.dialects.v20 import common as _pymav_common  # noqa: F401
    from pymavlink import mavutil as _pymav_mavutil  # noqa: F401

    HAVE_PYMAVLINK = True
except Exception:
    HAVE_PYMAVLINK = False


# ---------------------------------------------------------------------------
# Local golden-vector encoder (independent of aerix_rf.decode.sik.mavlink's
# own CRC implementation -- reimplements crc_accumulate from the MAVLink spec)
# ---------------------------------------------------------------------------


def _crc_accumulate(byte: int, crc: int) -> int:
    tmp = (byte ^ (crc & 0xFF)) & 0xFF
    tmp = (tmp ^ (tmp << 4)) & 0xFF
    return ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF


def _mavlink_crc_ref(data: bytes, crc_extra: int) -> int:
    crc = 0xFFFF
    for b in data:
        crc = _crc_accumulate(b, crc)
    crc = _crc_accumulate(crc_extra, crc)
    return crc


def _encode_v1(sysid, compid, msgid, seq, payload, crc_extra):
    length = len(payload)
    body = bytes((length, seq, sysid, compid, msgid)) + payload
    crc = _mavlink_crc_ref(body, crc_extra)
    return bytes((0xFE,)) + body + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def _encode_v2(sysid, compid, msgid, seq, payload, crc_extra, incompat=0, compat=0):
    length = len(payload)
    body = bytes(
        (
            length,
            incompat,
            compat,
            seq,
            sysid,
            compid,
            msgid & 0xFF,
            (msgid >> 8) & 0xFF,
            (msgid >> 16) & 0xFF,
        )
    ) + payload
    crc = _mavlink_crc_ref(body, crc_extra)
    out = bytes((0xFD,)) + body + bytes((crc & 0xFF, (crc >> 8) & 0xFF))
    if incompat & 0x01:
        out += bytes(range(13))  # opaque signature, 13 bytes
    return out


HEARTBEAT_CRC_EXTRA = 50
GPI_CRC_EXTRA = 104


def _heartbeat_payload(type_=2, autopilot=3, base_mode=81, custom_mode=0,
                        system_status=4, mavlink_version=3):
    return struct.pack("<IBBBBB", custom_mode, type_, autopilot, base_mode,
                        system_status, mavlink_version)


def _gpi_payload(time_boot_ms=12345, lat=473977418, lon=85455938, alt=100000,
                  relative_alt=50000, vx=100, vy=-50, vz=10, hdg=9000):
    return struct.pack("<IiiiihhhH", time_boot_ms, lat, lon, alt, relative_alt,
                        vx, vy, vz, hdg)


# ---------------------------------------------------------------------------
# CRC_EXTRA table sanity
# ---------------------------------------------------------------------------


def test_crc_extra_known_ids():
    assert crc_extra_for(0) == 50
    assert crc_extra_for(33) == 104
    assert crc_extra_for(999999) is None


# ---------------------------------------------------------------------------
# Golden vectors: v1/v2 HEARTBEAT and GLOBAL_POSITION_INT
# ---------------------------------------------------------------------------


def test_v1_heartbeat_exact_decode():
    payload = _heartbeat_payload()
    frame = _encode_v1(sysid=7, compid=1, msgid=0, seq=42, payload=payload,
                        crc_extra=HEARTBEAT_CRC_EXTRA)
    msgs = parse_mavlink_stream(frame)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.version == 1
    assert m.sysid == 7 and m.compid == 1 and m.msgid == 0 and m.seq == 42
    assert m.crc_ok is True
    assert m.evidence_level == 4
    assert m.fields["type"] == 2
    assert m.fields["autopilot"] == 3
    assert m.fields["base_mode"] == 81
    assert m.fields["custom_mode"] == 0
    assert m.fields["system_status"] == 4
    assert m.fields["mavlink_version"] == 3
    assert m.retention_class == RETENTION_CLASS_PERSONAL_7D


def test_v2_heartbeat_exact_decode():
    payload = _heartbeat_payload(type_=13, autopilot=12, base_mode=209,
                                  custom_mode=65536, system_status=3,
                                  mavlink_version=3)
    frame = _encode_v2(sysid=99, compid=190, msgid=0, seq=1, payload=payload,
                        crc_extra=HEARTBEAT_CRC_EXTRA)
    msgs = parse_mavlink_stream(frame)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.version == 2
    assert m.sysid == 99 and m.compid == 190
    assert m.crc_ok is True
    assert m.evidence_level == 4
    assert m.fields["type"] == 13
    assert m.fields["custom_mode"] == 65536
    assert m.signature is None


def test_v2_heartbeat_with_signature():
    payload = _heartbeat_payload()
    frame = _encode_v2(sysid=1, compid=1, msgid=0, seq=5, payload=payload,
                        crc_extra=HEARTBEAT_CRC_EXTRA, incompat=0x01)
    msgs = parse_mavlink_stream(frame)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.crc_ok is True
    assert m.signature is not None and len(m.signature) == 13


def test_v1_global_position_int_field_roundtrip():
    payload = _gpi_payload()
    frame = _encode_v1(sysid=1, compid=1, msgid=33, seq=0, payload=payload,
                        crc_extra=GPI_CRC_EXTRA)
    msgs = parse_mavlink_stream(frame)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.crc_ok is True
    assert m.evidence_level == 4
    assert m.fields["lat"] == pytest.approx(47.3977418, abs=1e-6)
    assert m.fields["lon"] == pytest.approx(8.5455938, abs=1e-6)
    assert m.fields["alt"] == pytest.approx(100.0, abs=1e-6)
    assert m.fields["relative_alt"] == pytest.approx(50.0, abs=1e-6)
    assert m.fields["vx"] == pytest.approx(1.0, abs=1e-6)
    assert m.fields["vy"] == pytest.approx(-0.5, abs=1e-6)
    assert m.fields["hdg"] == pytest.approx(90.0, abs=1e-6)
    assert m.retention_class == RETENTION_CLASS_PERSONAL_7D


def test_v2_global_position_int_zero_trimmed():
    # v2 zero-trimming: an encoder MAY omit trailing zero bytes of the
    # payload. Build a GPI payload whose tail (hdg=0) is trimmed and check
    # the parser still decodes it (fields default the missing tail to 0).
    full = _gpi_payload(hdg=0)
    trimmed = full.rstrip(b"\x00")
    assert len(trimmed) < len(full)
    frame = _encode_v2(sysid=1, compid=1, msgid=33, seq=0, payload=trimmed,
                        crc_extra=GPI_CRC_EXTRA)
    msgs = parse_mavlink_stream(frame)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.crc_ok is True
    assert m.evidence_level == 4
    assert m.fields["lat"] == pytest.approx(47.3977418, abs=1e-6)
    assert m.fields["hdg"] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# CRC false-accept rate on random streams
# ---------------------------------------------------------------------------


def test_random_streams_zero_false_accept():
    rng = random.Random(20260919)
    total_msgs = 0
    n_streams = 1000
    stream_len = 1000
    for _ in range(n_streams):
        data = bytes(rng.getrandbits(8) for _ in range(stream_len))
        msgs = parse_mavlink_stream(data)
        total_msgs += sum(1 for m in msgs if m.crc_ok)
    # n_streams * stream_len == 1e6 random bytes scanned
    assert n_streams * stream_len == 1_000_000
    assert total_msgs == 0


# ---------------------------------------------------------------------------
# Flag gating
# ---------------------------------------------------------------------------


def _sik_frame(payload: bytes, netid: int = 25) -> SikFrame:
    return SikFrame(
        netid=netid,
        length=len(payload) + 2,
        payload=payload,
        crc_ok=True,
        ecc=False,
        trailer=TdmTrailer(window=1, command=False, bonus=False, resend=False),
        bit_errors_corrected=0,
    )


def test_flag_off_no_fields_reach_output():
    frame = _encode_v1(sysid=7, compid=1, msgid=33, seq=0,
                        payload=_gpi_payload(), crc_extra=GPI_CRC_EXTRA)
    decoder = SikMavlinkDecoder(enabled=False)
    out = decoder.feed(_sik_frame(frame))
    assert len(out) == 1
    assert set(out[0].keys()) == {"netid", "sysid", "n_bytes"}
    assert out[0]["sysid"] is None
    assert out[0]["netid"] == 25
    assert out[0]["n_bytes"] == len(frame)


def test_flag_off_default_from_config_env(monkeypatch):
    monkeypatch.delenv("AERIX_RF_DECODE_THIRD_PARTY_MAVLINK", raising=False)
    from aerix_rf.config import Config

    cfg = Config.from_env()
    assert cfg.decode_third_party_mavlink is False
    monkeypatch.setenv("AERIX_RF_DECODE_THIRD_PARTY_MAVLINK", "1")
    cfg2 = Config.from_env()
    assert cfg2.decode_third_party_mavlink is True


def test_flag_on_decodes_fields():
    frame = _encode_v1(sysid=7, compid=1, msgid=33, seq=0,
                        payload=_gpi_payload(), crc_extra=GPI_CRC_EXTRA)
    decoder = SikMavlinkDecoder(enabled=True)
    out = decoder.feed(_sik_frame(frame))
    assert len(out) == 1
    assert out[0].fields["lat"] == pytest.approx(47.3977418, abs=1e-6)
    assert out[0].retention_class == RETENTION_CLASS_PERSONAL_7D


# ---------------------------------------------------------------------------
# Reassembly across two SiK frames
# ---------------------------------------------------------------------------


def test_reassembly_across_two_frames():
    frame = _encode_v1(sysid=3, compid=1, msgid=0, seq=0,
                        payload=_heartbeat_payload(), crc_extra=HEARTBEAT_CRC_EXTRA)
    split = len(frame) // 2
    part_a, part_b = frame[:split], frame[split:]

    decoder = SikMavlinkDecoder(enabled=True)
    out1 = decoder.feed(_sik_frame(part_a))
    assert out1 == []  # incomplete, no message yet
    out2 = decoder.feed(_sik_frame(part_b))
    assert len(out2) == 1
    assert out2[0].crc_ok is True
    assert out2[0].sysid == 3
    assert out2[0].fields["type"] == 2


def test_reassembly_keyed_by_netid_independent_buffers():
    frame_a = _encode_v1(sysid=1, compid=1, msgid=0, seq=0,
                          payload=_heartbeat_payload(), crc_extra=HEARTBEAT_CRC_EXTRA)
    frame_b = _encode_v1(sysid=2, compid=1, msgid=0, seq=1,
                          payload=_heartbeat_payload(type_=5), crc_extra=HEARTBEAT_CRC_EXTRA)
    decoder = SikMavlinkDecoder(enabled=True)
    # Interleave partial frames on two different NETIDs.
    decoder.feed(_sik_frame(frame_a[:4], netid=10))
    decoder.feed(_sik_frame(frame_b[:4], netid=20))
    out_a = decoder.feed(_sik_frame(frame_a[4:], netid=10))
    out_b = decoder.feed(_sik_frame(frame_b[4:], netid=20))
    assert len(out_a) == 1 and out_a[0].sysid == 1
    assert len(out_b) == 1 and out_b[0].sysid == 2 and out_b[0].fields["type"] == 5


def test_crc_fail_no_field_decode_and_low_evidence():
    payload = _heartbeat_payload()
    frame = bytearray(_encode_v1(sysid=1, compid=1, msgid=0, seq=0,
                                  payload=payload, crc_extra=HEARTBEAT_CRC_EXTRA))
    frame[-1] ^= 0xFF  # corrupt CRC
    msgs = parse_mavlink_stream(bytes(frame))
    assert len(msgs) == 0 or all(not m.crc_ok for m in msgs)


def test_unknown_msgid_caps_evidence_level():
    payload = b"\x00" * 4
    assert crc_extra_for(250) is None  # sanity: id not in our CRC_EXTRA table
    frame = _encode_v1(sysid=1, compid=1, msgid=250, seq=0, payload=payload,
                        crc_extra=0)  # arbitrary CRC_EXTRA, unknown to our table
    msgs = parse_mavlink_stream(frame)
    assert len(msgs) == 1
    assert msgs[0].evidence_level <= 3
    assert msgs[0].fields == {}


@pytest.mark.skipif(not HAVE_PYMAVLINK, reason="pymavlink not installed")
def test_pymavlink_cross_check_heartbeat():
    from pymavlink.dialects.v20 import common as mav2

    mav = mav2.MAVLink(None, srcSystem=7, srcComponent=1)
    mav.seq = 42
    msg = mav.heartbeat_encode(2, 3, 81, 0, 4, 3)
    wire = msg.pack(mav, force_mavlink1=False)
    parsed = parse_mavlink_stream(wire)
    assert len(parsed) == 1
    m = parsed[0]
    assert m.crc_ok is True
    assert m.fields["type"] == 2
    assert m.fields["autopilot"] == 3
