"""DJI DroneID frame packing and field extraction (OcuSync <= 2.0 normal frame).

Byte layout is taken verbatim from proto17/dji_droneid
``matlab/updated_scripts/transmit/create_frame_bytes.m`` (the transmit side) and
``cpp/{add,remove}_turbo.cc`` (the turbo wrapping). One offset table drives both the
packer and the parser so they cannot disagree.

The 176-byte turbo info block is:
    [0:91]    the DJI frame  (length, header, fields, inner CRC16)
    [91:173]  82 zero "tail" bytes (garbage in real captures; zeroed here)
    [173:176] CRC24A (big-endian) over bytes [0:173]

All multi-byte integer fields are little-endian (``to_bytes.m`` is LSB-first).
Coordinates are stored as ``int32(round(value_deg * 1e7 / 57.2957795785523))``.

Source: https://github.com/proto17/dji_droneid
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .turbo import crc16_dji, crc24a

# Degrees <-> stored-int32 scaling (create_frame_bytes.m coord_adj).
COORD_ADJ = 10000000.0 / 57.2957795785523

MESSAGE_TYPE = 16
VERSION = 2

# Offsets within the 91-byte DJI frame (also the first 91 bytes of the 176 block).
OFF_LENGTH = 0
OFF_MSG_TYPE = 1
OFF_VERSION = 2
OFF_SEQUENCE = 3            # u16
OFF_STATE0 = 5             # u8
OFF_STATE1 = 6             # u8
OFF_SERIAL = 7            # 16 bytes
OFF_DRONE_LON = 23        # i32
OFF_DRONE_LAT = 27        # i32
OFF_HEIGHT = 31           # i16
OFF_ALTITUDE = 33         # i16
OFF_VEL_N = 35            # i16
OFF_VEL_E = 37            # i16
OFF_VEL_U = 39            # i16
OFF_YAW = 41              # i16
OFF_GPS_TIME = 43         # u64
OFF_APP_LAT = 51          # i32  (operator / phone-app latitude)
OFF_APP_LON = 55          # i32  (operator / phone-app longitude)
OFF_HOME_LON = 59         # i32  (note: home is lon-then-lat)
OFF_HOME_LAT = 63         # i32
OFF_PRODUCT_TYPE = 67     # u8
OFF_UUID_LEN = 68         # u8
OFF_UUID = 69             # 19 bytes
OFF_TRAILING_ZERO = 88    # u8 (0)
OFF_CRC16 = 89            # u16

DJI_FRAME_LEN = 91
FRAME_BODY_LEN = 88        # value of the length byte (header..trailing zero)
TAIL_BYTES = 82            # zero padding appended before CRC24A
PRE_CRC24_LEN = 173        # 91 + 82
TURBO_BYTES = 176          # 173 + 3 (CRC24A)


@dataclass
class DroneIdFrame:
    serial: str
    drone_lat: float
    drone_lon: float
    drone_height: float
    drone_altitude: float
    operator_lat: float
    operator_lon: float
    home_lat: float
    home_lon: float
    sequence: int
    yaw: float
    velocity_north: float
    velocity_east: float
    velocity_up: float
    gps_time_ms: int
    product_type: int
    uuid: str


def _coord_to_i32(deg: float) -> int:
    return int(round(deg * COORD_ADJ))


def _i32_to_coord(v: int) -> float:
    return v / COORD_ADJ


def pack_dji_frame(*, serial: str = "0123456789abcd",
                   drone_lat: float = 0.0, drone_lon: float = 0.0,
                   height: int = 0, altitude: int = 0,
                   operator_lat: float = 0.0, operator_lon: float = 0.0,
                   home_lat: float = 0.0, home_lon: float = 0.0,
                   sequence: int = 0, state0: int = 0, state1: int = 0,
                   velocity_north: int = 0, velocity_east: int = 0,
                   velocity_up: int = 0, yaw: int = 0, gps_time_ms: int = 0,
                   product_type: int = 0, uuid: bytes | str = b"\x00" * 19) -> bytes:
    """Build the 91-byte DJI frame (bit-exact with create_frame_bytes.m)."""
    if isinstance(uuid, str):
        uuid = uuid.encode("ascii")
    uuid = (uuid + b"\x00" * 19)[:19]
    serial_b = (serial.encode("ascii") + b"\x00" * 16)[:16]

    body = bytearray()
    body += struct.pack("<B", MESSAGE_TYPE)
    body += struct.pack("<B", VERSION)
    body += struct.pack("<H", sequence & 0xFFFF)
    body += struct.pack("<BB", state0 & 0xFF, state1 & 0xFF)
    body += serial_b
    body += struct.pack("<i", _coord_to_i32(drone_lon))
    body += struct.pack("<i", _coord_to_i32(drone_lat))
    body += struct.pack("<h", height)
    body += struct.pack("<h", altitude)
    body += struct.pack("<h", velocity_north)
    body += struct.pack("<h", velocity_east)
    body += struct.pack("<h", velocity_up)
    body += struct.pack("<h", yaw)
    body += struct.pack("<Q", gps_time_ms & 0xFFFFFFFFFFFFFFFF)
    body += struct.pack("<i", _coord_to_i32(operator_lat))
    body += struct.pack("<i", _coord_to_i32(operator_lon))
    body += struct.pack("<i", _coord_to_i32(home_lon))
    body += struct.pack("<i", _coord_to_i32(home_lat))
    body += struct.pack("<B", product_type & 0xFF)
    body += struct.pack("<B", len(uuid))
    body += uuid
    body += b"\x00"
    assert len(body) == FRAME_BODY_LEN, len(body)

    frame = bytes([len(body)]) + bytes(body)
    crc16 = crc16_dji(frame)
    frame += struct.pack("<H", crc16)
    assert len(frame) == DJI_FRAME_LEN, len(frame)
    return frame


def build_turbo_payload(dji_frame: bytes) -> bytes:
    """91-byte frame -> 176-byte turbo info block (add 82 zero bytes + CRC24A)."""
    if len(dji_frame) != DJI_FRAME_LEN:
        raise ValueError(f"expected {DJI_FRAME_LEN} bytes, got {len(dji_frame)}")
    payload = dji_frame + b"\x00" * TAIL_BYTES
    crc = crc24a(payload)
    payload += bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])
    assert len(payload) == TURBO_BYTES
    return payload


def parse_frame(frame: bytes) -> DroneIdFrame | None:
    """Parse a decoded turbo block (>= 91 bytes). Returns None if not a DroneID frame."""
    if len(frame) < DJI_FRAME_LEN:
        return None
    if frame[OFF_MSG_TYPE] != MESSAGE_TYPE or frame[OFF_VERSION] != VERSION:
        return None

    def i16(off):
        return struct.unpack_from("<h", frame, off)[0]

    def i32(off):
        return struct.unpack_from("<i", frame, off)[0]

    serial = frame[OFF_SERIAL:OFF_SERIAL + 16].split(b"\x00", 1)[0].decode("ascii", "replace")
    uuid_len = frame[OFF_UUID_LEN]
    uuid = frame[OFF_UUID:OFF_UUID + min(uuid_len, 19)].split(b"\x00", 1)[0].decode("ascii", "replace")

    return DroneIdFrame(
        serial=serial,
        drone_lon=_i32_to_coord(i32(OFF_DRONE_LON)),
        drone_lat=_i32_to_coord(i32(OFF_DRONE_LAT)),
        drone_height=float(i16(OFF_HEIGHT)),
        drone_altitude=float(i16(OFF_ALTITUDE)),
        operator_lat=_i32_to_coord(i32(OFF_APP_LAT)),
        operator_lon=_i32_to_coord(i32(OFF_APP_LON)),
        home_lon=_i32_to_coord(i32(OFF_HOME_LON)),
        home_lat=_i32_to_coord(i32(OFF_HOME_LAT)),
        sequence=struct.unpack_from("<H", frame, OFF_SEQUENCE)[0],
        yaw=float(i16(OFF_YAW)),
        velocity_north=float(i16(OFF_VEL_N)),
        velocity_east=float(i16(OFF_VEL_E)),
        velocity_up=float(i16(OFF_VEL_U)),
        gps_time_ms=struct.unpack_from("<Q", frame, OFF_GPS_TIME)[0],
        product_type=frame[OFF_PRODUCT_TYPE],
        uuid=uuid,
    )
