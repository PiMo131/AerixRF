"""Open Drone ID messages: ASTM F3411 and ASD-STAN EN 4709-002.

This is the identity broadcast European law compels a drone to make, and for a
fleet of modern DJI airframes it is the *only* identity available: OcuSync 4
encrypts its proprietary DroneID payload, so the serial number and the
operator's position come from here or from nowhere.

It is also the safest data class to work with.  Receiving a mandated one-way
public broadcast is the paradigm case of listening to the free ether, which is
why ``antsdr/docs/decisions/ADR-0011`` treats Remote ID differently from
everything else the toolkit touches.

Who has to broadcast
--------------------
Under EU 2019/945 the obligation attaches to the class label, not to the
aircraft.  C1 and above must broadcast; **C0, the sub-250 g class, is exempt**.
That exemption is not a technicality for this project: it is why a DJI Neo
(135 g) and a Mini 4 Pro on its standard battery (249 g) are silent here,
while a Mini 4 Pro on the heavier Intelligent Flight Battery Plus crosses
250 g and starts broadcasting.  The battery decides whether the aircraft is
identifiable.  See ``antsdr/research/regulatory.md``.

The wire format
---------------
Every message is exactly 25 bytes.  Byte 0 carries the message type in its
high nibble and the protocol version in its low nibble; the remaining 24 bytes
depend on the type.  Multi-byte integers are little-endian.  A *message pack*
(type 0xF) prefixes up to nine of them with three bytes giving the single
message size and the count.

Protocol versions seen in the field are 0 (ASTM F3411-19), 1 (ASD-STAN
prEN 4709-002 P1) and 2 (ASTM F3411-22a).  They share this layout, so a
decoder does not branch on the version; it records it.

Field scaling follows the reference encoder exactly, and the details are the
kind that are silently wrong in a from-memory implementation:

* Latitude and longitude are degrees times 10^7, as ``int32``.
* Altitudes and height are ``(value + 1000) / 0.5``, so -1000 m is the
  invalid marker rather than a legal reading.
* Horizontal speed has **two scales** chosen by a flag bit: without it,
  ``value * 0.25`` m/s; with it, ``value * 0.75 + 63.75`` m/s.  Reading it as
  a single scale is wrong for everything above 63.75 m/s.
* Direction is 0-179 degrees in a byte, plus 180 when the east/west flag is
  set, because 360 does not fit in eight bits.  A byte above 179 is therefore
  malformed rather than a large bearing, and decodes to unknown.
* There is one genuine collision in the format, and it is worth knowing about
  before it is met in the field: on the fine speed scale 255 encodes both
  63.75 m/s and "no value", because ``MAX_SPEED_H`` is 254.25 while
  ``INV_SPEED_H`` is 255.  The reference encoder emits the ambiguous pair.
  This decoder reads it as unknown, which is the safe reading, and this
  module's encoder sidesteps it by using the coarse scale for that speed.
* The Location timestamp is tenths of a second **since the top of the hour**,
  so it needs an hour from somewhere else to become absolute.  The System
  timestamp is seconds since 2019-01-01, which is absolute.

Sources, read rather than remembered: ``opendroneid/opendroneid-core-c``,
files ``libopendroneid/opendroneid.h`` (structures, enums, invalid-value
constants) and ``libopendroneid/opendroneid.c`` (encode and decode helpers,
scaling constants).  Cross-checked against the transport table in
``antsdr/research/regulatory.md``.

This module is pure standard library, no numpy, so it can run anywhere a
receiver does.
"""

from __future__ import annotations

import datetime as _dt
import struct
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ALT_ADDER",
    "ALT_DIV",
    "CLASS_EU",
    "ID_TYPES",
    "INVALID",
    "LATLON_MULT",
    "MESSAGE_SIZE",
    "MESSAGE_TYPES",
    "PACK_MAX_MESSAGES",
    "SYSTEM_EPOCH",
    "UA_TYPES",
    "AuthMessage",
    "BasicIdMessage",
    "LocationMessage",
    "MessagePack",
    "OperatorIdMessage",
    "SelfIdMessage",
    "SystemMessage",
    "UnknownMessage",
    "decode_message",
    "decode_pack",
    "encode_basic_id",
    "encode_location",
    "encode_pack",
    "encode_system",
]

#: Every Open Drone ID message is this long, message packs included.
MESSAGE_SIZE = 25
#: A pack carries at most this many messages (opendroneid.h).
PACK_MAX_MESSAGES = 9

LATLON_MULT = 1e7
ALT_DIV = 0.5
ALT_ADDER = 1000
_SPEED_DIV = (0.25, 0.75)
_VSPEED_DIV = 0.5
#: Horizontal speed at which the encoder switches to its coarse scale.
_SPEED_BREAK = 255 * _SPEED_DIV[0]

#: The System message's timestamp epoch, per opendroneid.h: "Relative to
#: 00:00:00 01/01/2019 UTC/Unix Time".
SYSTEM_EPOCH = _dt.datetime(2019, 1, 1, tzinfo=_dt.timezone.utc)

#: Sentinel values that mean "no value", not a reading. Decoding these as
#: numbers is the most common way a Remote ID display invents data: an
#: unknown altitude becomes a confident -1000 m.
INVALID = {
    "direction_deg": 361,
    "speed_h_m_s": 255,
    "speed_v_m_s": 63,
    "altitude_m": -1000.0,
    "timestamp": 0xFFFF,
}

MESSAGE_TYPES = {
    0: "basic_id", 1: "location", 2: "auth", 3: "self_id",
    4: "system", 5: "operator_id", 0xF: "packed",
}

ID_TYPES = {
    0: "none", 1: "serial_number", 2: "caa_registration_id",
    3: "utm_assigned_uuid", 4: "specific_session_id",
}

UA_TYPES = {
    0: "none", 1: "aeroplane", 2: "helicopter_or_multirotor", 3: "gyroplane",
    4: "hybrid_lift", 5: "ornithopter", 6: "glider", 7: "kite",
    8: "free_balloon", 9: "captive_balloon", 10: "airship",
    11: "free_fall_parachute", 12: "rocket", 13: "tethered_powered_aircraft",
    14: "ground_obstacle", 15: "other",
}

_STATUS = {0: "undeclared", 1: "ground", 2: "airborne", 3: "emergency",
           4: "remote_id_system_failure"}
_OPERATOR_LOCATION = {0: "takeoff", 1: "live_gnss", 2: "fixed"}
_CLASSIFICATION = {0: "undeclared", 1: "eu"}
#: EU class labels. C0 is the one that matters most here, because it carries
#: no Remote ID obligation at all.
CLASS_EU = {0: "undeclared", 1: "C0", 2: "C1", 3: "C2", 4: "C3", 5: "C4",
            6: "C5", 7: "C6"}
_CATEGORY_EU = {0: "undeclared", 1: "open", 2: "specific", 3: "certified"}
_DESC_TYPES = {0: "text", 1: "emergency", 2: "extended_status"}


def _text(raw: bytes) -> str:
    """A fixed-width ASCII field, NUL-padded, as text."""
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def _nibbles(byte: int) -> tuple[int, int]:
    """``(low, high)``: protocol version and message type live in one byte."""
    return byte & 0x0F, (byte >> 4) & 0x0F


@dataclass(frozen=True)
class _Base:
    protocol_version: int
    raw: bytes = field(repr=False)

    @property
    def message_type(self) -> str:
        return MESSAGE_TYPES.get(_nibbles(self.raw[0])[1], "reserved")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"message_type": self.message_type,
                               "protocol_version": self.protocol_version}
        for key, value in self.__dict__.items():
            if key != "raw":
                out[key] = value
        out.pop("protocol_version", None)
        out["protocol_version"] = self.protocol_version
        return out


@dataclass(frozen=True)
class BasicIdMessage(_Base):
    """Who: an identifier and what kind of aircraft carries it."""

    id_type: str
    ua_type: str
    uas_id: str

    @property
    def is_serial(self) -> bool:
        return self.id_type == "serial_number"


@dataclass(frozen=True)
class LocationMessage(_Base):
    """Where the aircraft is, how fast and which way."""

    status: str
    direction_deg: float | None
    speed_h_m_s: float | None
    speed_v_m_s: float | None
    latitude: float | None
    longitude: float | None
    altitude_baro_m: float | None
    altitude_geo_m: float | None
    height_m: float | None
    height_over_takeoff: bool
    horizontal_accuracy: int
    vertical_accuracy: int
    speed_accuracy: int
    baro_accuracy: int
    timestamp_s_into_hour: float | None
    timestamp_accuracy: int

    @property
    def position(self) -> tuple[float, float] | None:
        if self.latitude is None or self.longitude is None:
            return None
        return self.latitude, self.longitude


@dataclass(frozen=True)
class SelfIdMessage(_Base):
    """A free-text description of the flight, chosen by the operator."""

    description_type: str
    description: str


@dataclass(frozen=True)
class SystemMessage(_Base):
    """Where the operator is, and the aircraft's class label."""

    operator_location_type: str
    classification_type: str
    operator_latitude: float | None
    operator_longitude: float | None
    area_count: int
    area_radius_m: int
    area_ceiling_m: float | None
    area_floor_m: float | None
    class_eu: str
    category_eu: str
    operator_altitude_geo_m: float | None
    timestamp: _dt.datetime | None

    @property
    def operator_position(self) -> tuple[float, float] | None:
        if self.operator_latitude is None or self.operator_longitude is None:
            return None
        return self.operator_latitude, self.operator_longitude

    @property
    def exempt_from_remote_id(self) -> bool:
        """True for C0, the sub-250 g class with no broadcast obligation.

        A C0 aircraft that is broadcasting is doing so voluntarily, so its
        absence from a scan proves nothing about whether it is flying.
        """
        return self.class_eu == "C0"


@dataclass(frozen=True)
class OperatorIdMessage(_Base):
    """The operator's registration identifier."""

    operator_id_type: int
    operator_id: str


@dataclass(frozen=True)
class AuthMessage(_Base):
    """One page of an authentication payload, which may span several pages."""

    auth_type: int
    data_page: int
    last_page_index: int | None
    length: int | None
    timestamp: _dt.datetime | None
    auth_data: bytes


@dataclass(frozen=True)
class UnknownMessage(_Base):
    """A message type this decoder does not know: kept, not discarded."""

    type_code: int


def _u16(raw: bytes, offset: int) -> int:
    return struct.unpack_from("<H", raw, offset)[0]


def _i32(raw: bytes, offset: int) -> int:
    return struct.unpack_from("<i", raw, offset)[0]


def _latlon(value: int) -> float | None:
    """Degrees, or ``None`` when the field is zero or out of range.

    Exactly (0, 0) is how every implementation signals "no fix", so it is
    treated as unknown rather than as a position in the Gulf of Guinea.
    """
    degrees = value / LATLON_MULT
    if value == 0 or not -90.0 <= degrees <= 180.0:
        return None
    return degrees


def _altitude(encoded: int) -> float | None:
    metres = encoded * ALT_DIV - ALT_ADDER
    return None if metres <= INVALID["altitude_m"] else metres


def decode_message(raw: bytes) -> _Base:
    """Decode one 25-byte Open Drone ID message.

    Raises :class:`ValueError` if the buffer is not exactly 25 bytes; a short
    read is a framing bug, and guessing at the missing bytes would produce a
    plausible message from nothing.
    """
    if len(raw) != MESSAGE_SIZE:
        raise ValueError(f"a message is {MESSAGE_SIZE} bytes, got {len(raw)}")
    version, type_code = _nibbles(raw[0])

    if type_code == 0:
        return BasicIdMessage(
            protocol_version=version, raw=raw,
            id_type=ID_TYPES.get((raw[1] >> 4) & 0x0F, "reserved"),
            ua_type=UA_TYPES.get(raw[1] & 0x0F, "reserved"),
            uas_id=_text(raw[2:22]))

    if type_code == 1:
        flags = raw[1]
        speed_mult = flags & 0x01
        east_west = (flags >> 1) & 0x01
        height_type = (flags >> 2) & 0x01
        direction = raw[2] + 180 * east_west
        speed_raw = raw[3]
        vspeed_raw = struct.unpack_from("<b", raw, 4)[0]
        speed = (speed_raw * _SPEED_DIV[0] if not speed_mult
                 else speed_raw * _SPEED_DIV[1] + _SPEED_BREAK)
        stamp = _u16(raw, 21)
        return LocationMessage(
            protocol_version=version, raw=raw,
            status=_STATUS.get((flags >> 4) & 0x0F, "reserved"),
            # The encoder writes 0..179 and puts the top half of the circle in
            # the flag, so a byte above 179 is not a large bearing, it is a
            # malformed field. INV_DIR is 361, which a byte cannot even hold.
            direction_deg=None if raw[2] > 179 else float(direction),
            speed_h_m_s=None if speed_raw == INVALID["speed_h_m_s"] and speed_mult == 0
            else float(speed),
            speed_v_m_s=None if vspeed_raw == INVALID["speed_v_m_s"]
            else vspeed_raw * _VSPEED_DIV,
            latitude=_latlon(_i32(raw, 5)), longitude=_latlon(_i32(raw, 9)),
            altitude_baro_m=_altitude(_u16(raw, 13)),
            altitude_geo_m=_altitude(_u16(raw, 15)),
            height_m=_altitude(_u16(raw, 17)),
            height_over_takeoff=height_type == 0,
            horizontal_accuracy=raw[19] & 0x0F, vertical_accuracy=(raw[19] >> 4) & 0x0F,
            speed_accuracy=raw[20] & 0x0F, baro_accuracy=(raw[20] >> 4) & 0x0F,
            timestamp_s_into_hour=None if stamp == INVALID["timestamp"] else stamp / 10.0,
            timestamp_accuracy=raw[23] & 0x0F)

    if type_code == 2:
        page = raw[1] & 0x0F
        auth_type = (raw[1] >> 4) & 0x0F
        if page == 0:
            seconds = struct.unpack_from("<I", raw, 4)[0]
            return AuthMessage(
                protocol_version=version, raw=raw, auth_type=auth_type, data_page=0,
                last_page_index=raw[2], length=raw[3],
                timestamp=(SYSTEM_EPOCH + _dt.timedelta(seconds=seconds)) if seconds else None,
                auth_data=raw[8:25])
        return AuthMessage(protocol_version=version, raw=raw, auth_type=auth_type,
                           data_page=page, last_page_index=None, length=None,
                           timestamp=None, auth_data=raw[2:25])

    if type_code == 3:
        return SelfIdMessage(protocol_version=version, raw=raw,
                             description_type=_DESC_TYPES.get(raw[1], "reserved"),
                             description=_text(raw[2:25]))

    if type_code == 4:
        seconds = struct.unpack_from("<I", raw, 20)[0]
        return SystemMessage(
            protocol_version=version, raw=raw,
            operator_location_type=_OPERATOR_LOCATION.get(raw[1] & 0x03, "reserved"),
            classification_type=_CLASSIFICATION.get((raw[1] >> 2) & 0x07, "reserved"),
            operator_latitude=_latlon(_i32(raw, 2)),
            operator_longitude=_latlon(_i32(raw, 6)),
            area_count=_u16(raw, 10), area_radius_m=raw[12] * 10,
            area_ceiling_m=_altitude(_u16(raw, 13)),
            area_floor_m=_altitude(_u16(raw, 15)),
            class_eu=CLASS_EU.get(raw[17] & 0x0F, "reserved"),
            category_eu=_CATEGORY_EU.get((raw[17] >> 4) & 0x0F, "reserved"),
            operator_altitude_geo_m=_altitude(_u16(raw, 18)),
            timestamp=(SYSTEM_EPOCH + _dt.timedelta(seconds=seconds)) if seconds else None)

    if type_code == 5:
        return OperatorIdMessage(protocol_version=version, raw=raw,
                                 operator_id_type=raw[1], operator_id=_text(raw[2:22]))

    return UnknownMessage(protocol_version=version, raw=raw, type_code=type_code)


@dataclass(frozen=True)
class MessagePack:
    """A type-0xF container carrying several messages in one frame."""

    protocol_version: int
    single_message_size: int
    messages: list[_Base]

    def of_type(self, name: str) -> list[_Base]:
        return [m for m in self.messages if m.message_type == name]

    @property
    def uas_id(self) -> str | None:
        """The first identifier in the pack, if it carries one."""
        for message in self.messages:
            if isinstance(message, BasicIdMessage) and message.uas_id:
                return message.uas_id
        return None

    def summary(self) -> dict[str, Any]:
        """The fields an operator actually wants, pulled from across the pack."""
        out: dict[str, Any] = {"uas_id": self.uas_id,
                               "n_messages": len(self.messages),
                               "types": [m.message_type for m in self.messages]}
        for message in self.messages:
            if isinstance(message, BasicIdMessage) and "id_type" not in out:
                out["id_type"] = message.id_type
                out["ua_type"] = message.ua_type
            elif isinstance(message, LocationMessage):
                out["position"] = message.position
                out["altitude_geo_m"] = message.altitude_geo_m
                out["height_m"] = message.height_m
                out["status"] = message.status
                out["speed_h_m_s"] = message.speed_h_m_s
            elif isinstance(message, SystemMessage):
                out["operator_position"] = message.operator_position
                out["class_eu"] = message.class_eu
            elif isinstance(message, OperatorIdMessage):
                out["operator_id"] = message.operator_id
        return out


def decode_pack(raw: bytes) -> MessagePack:
    """Decode a message pack: a 3-byte header then ``count`` messages.

    The header's own message-size field is honoured rather than assumed, and a
    pack claiming more data than it carries raises rather than returning the
    messages that happen to fit.
    """
    if len(raw) < 3:
        raise ValueError(f"a message pack header is 3 bytes, got {len(raw)}")
    version, type_code = _nibbles(raw[0])
    if type_code != 0xF:
        raise ValueError(f"not a message pack: type nibble is {type_code:#x}, expected 0xf")
    size, count = raw[1], raw[2]
    if size != MESSAGE_SIZE:
        raise ValueError(f"pack declares {size}-byte messages, expected {MESSAGE_SIZE}")
    if not 1 <= count <= PACK_MAX_MESSAGES:
        raise ValueError(f"pack declares {count} messages, expected 1 to {PACK_MAX_MESSAGES}")
    needed = 3 + size * count
    if len(raw) < needed:
        raise ValueError(f"pack declares {count} messages ({needed} bytes) but only "
                         f"{len(raw)} are present")
    return MessagePack(protocol_version=version, single_message_size=size,
                       messages=[decode_message(raw[3 + i * size:3 + (i + 1) * size])
                                 for i in range(count)])


# --------------------------------------------------------------- encoding
# Only what tests and a replay tool need. Never transmitted (ADR-0001).

def _header(type_code: int, version: int = 2) -> int:
    return ((type_code & 0x0F) << 4) | (version & 0x0F)


def encode_basic_id(uas_id: str, *, id_type: int = 1, ua_type: int = 2,
                    version: int = 2) -> bytes:
    body = struct.pack("<BB20s3x", _header(0, version), ((id_type & 0x0F) << 4) | (ua_type & 0x0F),
                       uas_id.encode("ascii", "replace")[:20])
    assert len(body) == MESSAGE_SIZE
    return body


def encode_location(*, latitude: float, longitude: float, altitude_geo_m: float = 0.0,
                    height_m: float = 0.0, altitude_baro_m: float = 0.0,
                    direction_deg: float = 0.0, speed_h_m_s: float = 0.0,
                    speed_v_m_s: float = 0.0, status: int = 2,
                    timestamp_s_into_hour: float = 0.0, version: int = 2) -> bytes:
    east_west = 1 if direction_deg >= 180 else 0
    direction = round(direction_deg) - 180 * east_west
    # The fine scale tops out at 255 * 0.25 = 63.75 m/s, but 255 is also the
    # "no value" sentinel, so that one legal speed has two meanings on the
    # wire. The reference encoder emits the ambiguous pair; this one steps up
    # to the coarse scale instead, which represents the same speed
    # unambiguously. See the collision note in the module docstring.
    speed = round(speed_h_m_s / _SPEED_DIV[0])
    if speed_h_m_s <= _SPEED_BREAK and speed < INVALID["speed_h_m_s"]:
        speed_mult = 0
    else:
        speed_mult = 1
        speed = round(max(0.0, speed_h_m_s - _SPEED_BREAK) / _SPEED_DIV[1])
    flags = ((status & 0x0F) << 4) | (east_west << 1) | speed_mult

    def alt(value: float) -> int:
        return max(0, min(0xFFFF, round((value + ALT_ADDER) / ALT_DIV)))

    body = struct.pack(
        "<BBBBbiiHHHBBHBx", _header(1, version), flags,
        max(0, min(255, direction)), max(0, min(255, speed)),
        max(-128, min(127, round(speed_v_m_s / _VSPEED_DIV))),
        round(latitude * LATLON_MULT), round(longitude * LATLON_MULT),
        alt(altitude_baro_m), alt(altitude_geo_m), alt(height_m),
        0, 0, round(timestamp_s_into_hour * 10), 0)
    assert len(body) == MESSAGE_SIZE, len(body)
    return body


def encode_system(*, operator_latitude: float, operator_longitude: float,
                  class_eu: int = 2, category_eu: int = 1,
                  operator_altitude_geo_m: float = 0.0,
                  timestamp: _dt.datetime | None = None, version: int = 2) -> bytes:
    seconds = 0 if timestamp is None else int((timestamp - SYSTEM_EPOCH).total_seconds())
    body = struct.pack(
        "<BBiiHBHHBHIx", _header(4, version), 0x04,  # classification_type = EU
        round(operator_latitude * LATLON_MULT),
        round(operator_longitude * LATLON_MULT),
        0, 0, 0, 0,
        ((category_eu & 0x0F) << 4) | (class_eu & 0x0F),
        max(0, min(0xFFFF, round((operator_altitude_geo_m + ALT_ADDER) / ALT_DIV))),
        max(0, seconds))
    assert len(body) == MESSAGE_SIZE, len(body)
    return body


def encode_pack(messages: list[bytes], *, version: int = 2) -> bytes:
    """Wrap messages in a type-0xF pack."""
    if not 1 <= len(messages) <= PACK_MAX_MESSAGES:
        raise ValueError(f"a pack holds 1 to {PACK_MAX_MESSAGES} messages, got {len(messages)}")
    for message in messages:
        if len(message) != MESSAGE_SIZE:
            raise ValueError(f"a message is {MESSAGE_SIZE} bytes, got {len(message)}")
    return bytes([_header(0xF, version), MESSAGE_SIZE, len(messages)]) + b"".join(messages)
