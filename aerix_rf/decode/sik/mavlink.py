"""MAVLink v1/v2 payload parser for SiK-carried telemetry (T3).

**Passive receive only.** AERIX never transmits and never interrogates a
MAVLink link; this module only parses bytes recovered from
:mod:`aerix_rf.decode.sik.frame` deframed payloads.

User ruling on record (``docs/design/sik-mavlink-passive-decode.md`` S3):
passive decoding of third-party MAVLink is approved for research, but is
gated by a default-OFF config flag ``decode.third_party_mavlink``
(env ``AERIX_RF_DECODE_THIRD_PARTY_MAVLINK=1``, see
:data:`aerix_rf.config.Config.decode_third_party_mavlink`). With the flag
off, :class:`SikMavlinkDecoder` never parses MAVLink fields -- it only
reports byte-stream metadata (``netid``, ``n_bytes``). Decoded field
dictionaries that contain a position, home position or identity field
(``sysid``/``compid``/lat/lon/alt) are personal data and are tagged
``retention_class="personal_7d"`` -- the same 7-day expiry class as
DroneID operator positions.

**Evidence level.** A :class:`MavlinkMessage` is evidence level 4
(validated deterministic decode) only when ``crc_ok`` is True (both the
MAVLink header/payload CRC-16/MCRF4XX *and* the per-message ``CRC_EXTRA``
byte matched). Any CRC mismatch, or an unknown message id when no
``CRC_EXTRA`` table entry is available, caps evidence at level <= 3
(structural framing evidence only -- STX/length/msgid are self-consistent
but the payload is not verified).

**Validation status.** Tested only against a from-scratch, spec-faithful
encoder in this module's own test file (golden vectors, optionally
cross-checked against ``pymavlink`` when importable) and against random
byte streams for false-accept rate. This is decoder self-consistency, not
real-radio validation (design doc S4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

MAVLINK_V1_STX = 0xFE
MAVLINK_V2_STX = 0xFD
MAVLINK_V2_SIGNATURE_LEN = 13

RETENTION_CLASS_PERSONAL_7D = "personal_7d"

# ---------------------------------------------------------------------------
# CRC-16/MCRF4XX (MAVLink's crc_accumulate), seed 0xFFFF.
# ---------------------------------------------------------------------------


def _crc_accumulate(byte: int, crc: int) -> int:
    tmp = (byte ^ (crc & 0xFF)) & 0xFF
    tmp = (tmp ^ (tmp << 4)) & 0xFF
    crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def mavlink_crc(data: bytes, crc_extra: Optional[int]) -> Optional[int]:
    """CRC-16/MCRF4XX over ``data`` (header bytes after STX, through payload,
    for both v1 and v2), plus the per-message ``crc_extra`` byte appended at
    the end (MAVLink's ``crc_extra`` scheme). Returns ``None`` if
    ``crc_extra`` is ``None`` (unknown message id -- caller must cap evidence
    at level <= 3, it cannot validate the CRC).
    """
    if crc_extra is None:
        return None
    crc = 0xFFFF
    for b in data:
        crc = _crc_accumulate(b, crc)
    crc = _crc_accumulate(crc_extra & 0xFF, crc)
    return crc & 0xFFFF


# ---------------------------------------------------------------------------
# CRC_EXTRA table for the common-dialect messages this project decodes.
# Values are the standard MAVLink common.xml CRC_EXTRA constants (fixed by
# the message's field layout/types per the MAVLink CRC_EXTRA algorithm --
# these are the same constants pymavlink/mavgen embed).
# ---------------------------------------------------------------------------

_CRC_EXTRA_BUILTIN: Dict[int, int] = {
    0: 50,    # HEARTBEAT
    1: 124,   # SYS_STATUS
    24: 24,   # GPS_RAW_INT
    30: 39,   # ATTITUDE
    33: 104,  # GLOBAL_POSITION_INT
    74: 20,   # VFR_HUD
    242: 104,  # HOME_POSITION
}

try:  # pragma: no cover - exercised only when pymavlink is installed
    from pymavlink.dialects.v20 import common as _mavcommon

    _CRC_EXTRA_TABLE: Dict[int, int] = dict(_mavcommon.MAVLink_message.crc_extra)
    _CRC_EXTRA_TABLE.update(_CRC_EXTRA_BUILTIN)
    _CRC_EXTRA_SOURCE = "pymavlink common.xml"
except Exception:  # pymavlink not importable -- use the embedded subset only
    _CRC_EXTRA_TABLE = dict(_CRC_EXTRA_BUILTIN)
    _CRC_EXTRA_SOURCE = "embedded common-dialect subset"


def crc_extra_for(msgid: int) -> Optional[int]:
    """``CRC_EXTRA`` for ``msgid``, or ``None`` if unknown to this build
    (see :data:`_CRC_EXTRA_SOURCE`: full table when ``pymavlink`` is
    importable, else only the messages this project decodes fields for)."""
    return _CRC_EXTRA_TABLE.get(msgid)


# Message ids whose fields this module knows how to decode into a dict.
# Anything else still gets a validated CRC (level 4 if crc_ok) but
# ``fields`` stays empty -- field-layout parsing is deliberately narrow to
# what design doc S3 lists as extractable.


def _decode_heartbeat(payload: bytes) -> Dict[str, object]:
    # HEARTBEAT (v2 wire layout): type(u8) autopilot(u8) base_mode(u8)
    # custom_mode(u32) system_status(u8) mavlink_version(u8)
    # NB: on-air field order is sorted by type size descending, then
    # declaration order (MAVLink wire-order rule), so custom_mode(u32)
    # comes first.
    if len(payload) < 9:
        return {}
    custom_mode = int.from_bytes(payload[0:4], "little")
    type_ = payload[4]
    autopilot = payload[5]
    base_mode = payload[6]
    system_status = payload[7]
    mavlink_version = payload[8]
    return {
        "type": type_,
        "autopilot": autopilot,
        "base_mode": base_mode,
        "custom_mode": custom_mode,
        "system_status": system_status,
        "mavlink_version": mavlink_version,
    }


def _decode_global_position_int(payload: bytes) -> Dict[str, object]:
    # time_boot_ms(u32) lat(i32) lon(i32) alt(i32) relative_alt(i32)
    # vx(i16) vy(i16) vz(i16) hdg(u16)
    if len(payload) < 28:
        return {}
    time_boot_ms = int.from_bytes(payload[0:4], "little")
    lat = int.from_bytes(payload[4:8], "little", signed=True)
    lon = int.from_bytes(payload[8:12], "little", signed=True)
    alt = int.from_bytes(payload[12:16], "little", signed=True)
    relative_alt = int.from_bytes(payload[16:20], "little", signed=True)
    vx = int.from_bytes(payload[20:22], "little", signed=True)
    vy = int.from_bytes(payload[22:24], "little", signed=True)
    vz = int.from_bytes(payload[24:26], "little", signed=True)
    hdg = int.from_bytes(payload[26:28], "little", signed=False)
    return {
        "time_boot_ms": time_boot_ms,
        "lat": lat * 1e-7,
        "lon": lon * 1e-7,
        "alt": alt / 1000.0,
        "relative_alt": relative_alt / 1000.0,
        "vx": vx / 100.0,
        "vy": vy / 100.0,
        "vz": vz / 100.0,
        "hdg": (hdg / 100.0) if hdg != 65535 else None,
    }


def _decode_gps_raw_int(payload: bytes) -> Dict[str, object]:
    # time_usec(u64) lat(i32) lon(i32) alt(i32) eph(u16) epv(u16) vel(u16)
    # cog(u16) fix_type(u8) satellites_visible(u8)
    if len(payload) < 30:
        return {}
    time_usec = int.from_bytes(payload[0:8], "little")
    lat = int.from_bytes(payload[8:12], "little", signed=True)
    lon = int.from_bytes(payload[12:16], "little", signed=True)
    alt = int.from_bytes(payload[16:20], "little", signed=True)
    eph = int.from_bytes(payload[20:22], "little")
    epv = int.from_bytes(payload[22:24], "little")
    vel = int.from_bytes(payload[24:26], "little")
    cog = int.from_bytes(payload[26:28], "little")
    fix_type = payload[28]
    satellites_visible = payload[29]
    return {
        "time_usec": time_usec,
        "lat": lat * 1e-7,
        "lon": lon * 1e-7,
        "alt": alt / 1000.0,
        "eph": eph,
        "epv": epv,
        "vel": vel / 100.0,
        "cog": cog / 100.0,
        "fix_type": fix_type,
        "satellites_visible": satellites_visible,
    }


def _decode_home_position(payload: bytes) -> Dict[str, object]:
    # lat(i32) lon(i32) altitude(i32) x/y/z(f32) q(4xf32) approach_x/y/z(f32)
    # [time_usec(u64) -- v2 extension, may be absent]
    import struct

    if len(payload) < 52:
        return {}
    lat = int.from_bytes(payload[0:4], "little", signed=True)
    lon = int.from_bytes(payload[4:8], "little", signed=True)
    altitude = int.from_bytes(payload[8:12], "little", signed=True)
    x, y, z = struct.unpack_from("<fff", payload, 12)
    return {
        "lat": lat * 1e-7,
        "lon": lon * 1e-7,
        "altitude": altitude / 1000.0,
        "x": x,
        "y": y,
        "z": z,
    }


def _decode_attitude(payload: bytes) -> Dict[str, object]:
    import struct

    if len(payload) < 28:
        return {}
    time_boot_ms = int.from_bytes(payload[0:4], "little")
    roll, pitch, yaw, rollspeed, pitchspeed, yawspeed = struct.unpack_from(
        "<ffffff", payload, 4
    )
    return {
        "time_boot_ms": time_boot_ms,
        "roll": roll,
        "pitch": pitch,
        "yaw": yaw,
        "rollspeed": rollspeed,
        "pitchspeed": pitchspeed,
        "yawspeed": yawspeed,
    }


def _decode_sys_status(payload: bytes) -> Dict[str, object]:
    if len(payload) < 31:
        return {}
    onboard_control_sensors_present = int.from_bytes(payload[0:4], "little")
    onboard_control_sensors_enabled = int.from_bytes(payload[4:8], "little")
    onboard_control_sensors_health = int.from_bytes(payload[8:12], "little")
    load = int.from_bytes(payload[12:14], "little")
    voltage_battery = int.from_bytes(payload[14:16], "little")
    current_battery = int.from_bytes(payload[16:18], "little", signed=True)
    return {
        "onboard_control_sensors_present": onboard_control_sensors_present,
        "onboard_control_sensors_enabled": onboard_control_sensors_enabled,
        "onboard_control_sensors_health": onboard_control_sensors_health,
        "load": load,
        "voltage_battery": voltage_battery / 1000.0,
        "current_battery": current_battery / 100.0 if current_battery != -1 else None,
    }


def _decode_vfr_hud(payload: bytes) -> Dict[str, object]:
    import struct

    if len(payload) < 20:
        return {}
    airspeed, groundspeed, alt, climb = struct.unpack_from("<ffff", payload, 0)
    heading, throttle = struct.unpack_from("<hH", payload, 16)
    return {
        "airspeed": airspeed,
        "groundspeed": groundspeed,
        "heading": heading,
        "throttle": throttle,
        "alt": alt,
        "climb": climb,
    }


_FIELD_DECODERS = {
    0: _decode_heartbeat,
    1: _decode_sys_status,
    24: _decode_gps_raw_int,
    30: _decode_attitude,
    33: _decode_global_position_int,
    74: _decode_vfr_hud,
    242: _decode_home_position,
}

# Full (non-trimmed) wire-payload length for each message above, used to
# zero-pad a MAVLink v2 zero-trimmed payload back to its nominal size before
# field decode (MAVLink v2 senders may omit trailing all-zero payload bytes;
# a receiver MUST zero-extend before interpreting fields).
_FIELD_PAYLOAD_LEN = {
    0: 9,
    1: 31,
    24: 30,
    30: 28,
    33: 28,
    74: 20,
    242: 52,
}


def _decode_fields(msgid: int, payload: bytes) -> Dict[str, object]:
    decoder = _FIELD_DECODERS.get(msgid)
    if decoder is None:
        return {}
    full_len = _FIELD_PAYLOAD_LEN.get(msgid)
    if full_len is not None and len(payload) < full_len:
        payload = bytes(payload) + bytes(full_len - len(payload))
    try:
        return decoder(payload)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# MavlinkMessage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MavlinkMessage:
    """A parsed MAVLink frame recovered from a SiK payload stream.

    ``evidence_level`` is 4 only when ``crc_ok`` is True (header+payload
    CRC-16/MCRF4XX *and* CRC_EXTRA both matched); otherwise <= 3. See module
    docstring for evidence-level and retention-tagging rules.
    """

    version: int  # 1 or 2
    sysid: int
    compid: int
    msgid: int
    seq: int
    crc_ok: bool
    fields: Dict[str, object]
    evidence_level: int
    signature: Optional[bytes] = None
    retention_class: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        if self.fields:
            # Any decoded field dict (identity/position or otherwise, e.g.
            # HEARTBEAT type/autopilot) originates from a third-party link
            # under the same authorisation basis; conservatively tag all
            # decoded-field messages with the personal-data retention class
            # per design doc S3 rather than trying to enumerate every
            # position-bearing field name.
            object.__setattr__(self, "retention_class", RETENTION_CLASS_PERSONAL_7D)


# ---------------------------------------------------------------------------
# Frame-level parse (single buffer -> messages), no reassembly.
# ---------------------------------------------------------------------------


def _try_parse_v1(data: bytes, start: int):
    """Attempt a v1 frame at ``data[start]`` (``data[start] == 0xFE``).
    Returns ``(MavlinkMessage, consumed_bytes)`` or ``None``.
    """
    if start + 6 > len(data):
        return None
    length = data[start + 1]
    seq = data[start + 2]
    sysid = data[start + 3]
    compid = data[start + 4]
    msgid = data[start + 5]
    payload_start = start + 6
    payload_end = payload_start + length
    frame_end = payload_end + 2
    if frame_end > len(data):
        return None
    payload = data[payload_start:payload_end]
    crc_recv = data[payload_end] | (data[payload_end + 1] << 8)
    crc_extra = crc_extra_for(msgid)
    crc_body = data[start + 1 : payload_end]  # len..payload, excludes STX
    computed = mavlink_crc(crc_body, crc_extra)
    crc_ok = computed is not None and computed == crc_recv
    evidence_level = 4 if crc_ok else (3 if computed is not None else 2)
    fields = _decode_fields(msgid, payload) if crc_ok else {}
    msg = MavlinkMessage(
        version=1,
        sysid=sysid,
        compid=compid,
        msgid=msgid,
        seq=seq,
        crc_ok=crc_ok,
        fields=fields,
        evidence_level=evidence_level,
    )
    return msg, frame_end - start


def _try_parse_v2(data: bytes, start: int):
    if start + 10 > len(data):
        return None
    length = data[start + 1]
    incompat_flags = data[start + 2]
    compat_flags = data[start + 3]
    seq = data[start + 4]
    sysid = data[start + 5]
    compid = data[start + 6]
    msgid = data[start + 7] | (data[start + 8] << 8) | (data[start + 9] << 16)
    payload_start = start + 10
    payload_end = payload_start + length
    has_sig = bool(incompat_flags & 0x01)
    sig_len = MAVLINK_V2_SIGNATURE_LEN if has_sig else 0
    frame_end = payload_end + 2 + sig_len
    if frame_end > len(data):
        return None
    payload = data[payload_start:payload_end]
    crc_recv = data[payload_end] | (data[payload_end + 1] << 8)
    signature = data[payload_end + 2 : frame_end] if has_sig else None
    crc_extra = crc_extra_for(msgid)
    crc_body = data[start + 1 : payload_end]  # len..payload, excludes STX
    computed = mavlink_crc(crc_body, crc_extra)
    crc_ok = computed is not None and computed == crc_recv
    evidence_level = 4 if crc_ok else (3 if computed is not None else 2)
    fields = _decode_fields(msgid, payload) if crc_ok else {}
    msg = MavlinkMessage(
        version=2,
        sysid=sysid,
        compid=compid,
        msgid=msgid,
        seq=seq,
        crc_ok=crc_ok,
        fields=fields,
        evidence_level=evidence_level,
        signature=signature,
    )
    return msg, frame_end - start


def parse_mavlink_stream(payload_bytes: bytes) -> list:
    """Scan ``payload_bytes`` for MAVLink v1/v2 frames, returning a list of
    :class:`MavlinkMessage` in stream order. Non-frame bytes (including a
    STX byte that does not lead to a structurally/CRC-valid frame) are
    skipped one byte at a time -- this is a *search*, not a strict framer,
    because SiK payloads may contain partial frames at buffer edges (see
    :class:`SikMavlinkDecoder` for cross-frame reassembly).
    """
    data = bytes(payload_bytes)
    out = []
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == MAVLINK_V1_STX:
            result = _try_parse_v1(data, i)
            if result is not None:
                msg, consumed = result
                out.append(msg)
                i += consumed
                continue
        elif b == MAVLINK_V2_STX:
            result = _try_parse_v2(data, i)
            if result is not None:
                msg, consumed = result
                out.append(msg)
                i += consumed
                continue
        i += 1
    return out


# ---------------------------------------------------------------------------
# SikMavlinkDecoder: per-NETID reassembly across SiK payload frames.
# ---------------------------------------------------------------------------


class SikMavlinkDecoder:
    """Reassembles MAVLink messages from a stream of :class:`SikFrame`
    (``aerix_rf.decode.sik.frame``) payloads, keyed by NETID (SiK's
    transparent-serial payload is a raw byte stream, so a MAVLink message
    may span two consecutive radio packets).

    **Gate.** If ``enabled`` is False (the default, mirroring
    ``decode.third_party_mavlink``), :meth:`feed` never parses MAVLink
    fields: it only returns byte-stream metadata
    (``{"netid": ..., "n_bytes": ...}``). No CRC/field parsing is
    attempted, and no :class:`MavlinkMessage` is ever constructed, when the
    gate is off.
    """

    # Cap the per-NETID unresolved-byte buffer so a bad or non-MAVLink
    # stream can't grow it unboundedly.
    _MAX_BUFFER = 4096

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._buffers: Dict[int, bytearray] = {}

    def feed(self, sik_frame) -> list:
        """Feed one deframed :class:`~aerix_rf.decode.sik.frame.SikFrame`.
        Only frames with ``crc_ok`` are appended to the reassembly buffer
        (a corrupted SiK frame would desync MAVLink framing anyway).
        Returns a list -- either ``[]``/metadata dicts (gate off) or
        :class:`MavlinkMessage` objects (gate on).
        """
        netid = sik_frame.netid
        n_bytes = len(sik_frame.payload)
        if not self.enabled:
            return [{"netid": netid, "sysid": None, "n_bytes": n_bytes}]

        if not sik_frame.crc_ok:
            return []

        buf = self._buffers.setdefault(netid, bytearray())
        buf.extend(sik_frame.payload)
        if len(buf) > self._MAX_BUFFER:
            # Drop the oldest overflow rather than growing unboundedly;
            # this may cost partial messages but keeps memory bounded.
            del buf[: len(buf) - self._MAX_BUFFER]

        messages = parse_mavlink_stream(bytes(buf))
        # Re-scan to find how many trailing bytes were *not* consumed by a
        # complete message (a possible partial message at the buffer's
        # tail), so we can keep only that tail for the next feed().
        consumed = _consumed_prefix_len(bytes(buf), messages)
        del buf[:consumed]
        return messages


def _consumed_prefix_len(data: bytes, messages: list) -> int:
    """Return the byte offset just past the last complete message found by
    :func:`parse_mavlink_stream`, so the caller can discard fully-parsed
    bytes and keep only a possible trailing partial frame. Re-derives the
    offset by re-walking the same scan (cheap; buffers are small) rather
    than threading consumed-length out of ``parse_mavlink_stream``'s public
    return type.
    """
    if not messages:
        # No complete message: keep the tail from the last plausible STX
        # onward (or the last few bytes generally) so a message split
        # exactly at a buffer boundary can still be completed by the next
        # feed(); if no STX at all, drop everything but a short tail.
        for j in range(len(data) - 1, -1, -1):
            if data[j] in (MAVLINK_V1_STX, MAVLINK_V2_STX):
                return j
        return max(0, len(data) - 1)

    i = 0
    n = len(data)
    last_end = 0
    while i < n:
        b = data[i]
        if b == MAVLINK_V1_STX:
            result = _try_parse_v1(data, i)
            if result is not None:
                _, consumed = result
                i += consumed
                last_end = i
                continue
        elif b == MAVLINK_V2_STX:
            result = _try_parse_v2(data, i)
            if result is not None:
                _, consumed = result
                i += consumed
                last_end = i
                continue
        i += 1
    return last_end
