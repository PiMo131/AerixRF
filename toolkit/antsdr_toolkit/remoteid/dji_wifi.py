"""DJI's own DroneID, carried in an 802.11 vendor element.

Not to be confused with the standard Remote ID in :mod:`.odid`, which is a
different payload under a different OUI and is there because the law requires
it.  This one is DJI's proprietary DroneID, the same field set the OcuSync
side channel carries, but riding in a Wi-Fi beacon instead of an OFDM burst.
It appears on DJI's Wi-Fi-link aircraft: the Spark, Mavic Air and Tello class,
and possibly on newer models when they are flown in a phone-direct Wi-Fi mode
rather than on an OcuSync controller.

Why it is worth having
----------------------
It needs no SDR and no keys.  A commodity adapter in monitor mode sees it, and
the payload is in the clear.  For an aircraft whose OcuSync DroneID is
encrypted and whose class mark carries no Remote ID obligation, this is the
one remaining published route to a serial number, so it is worth testing on
any airframe with a Wi-Fi mode before concluding that nothing can identify it.

Whether a given modern airframe emits this element in its Wi-Fi mode is
**untested by this project and unreported anywhere in its research record**.
The module exists so that the experiment is one command rather than a project.

Confidence, which is not uniform across the record
--------------------------------------------------
The layout below comes from Kismet's parser
(``kismetwireless/kismet``, ``dot11_parsers/dot11_ie_221_dji_droneid``), and
the two halves of that parser do not carry the same weight:

* **Parsed and trusted there:** the four-byte element header, then
  ``version``, ``sequence``, ``state_info``, a 16-byte serial, longitude and
  latitude.  Thirty-three bytes in total, which :data:`CONFIDENT_BYTES`
  computes rather than states.
* **Declared but commented out there**, explicitly because the field ordering
  was not certain: altitude, height, the velocity components, attitude, the
  home point, the operator position, product type and the UUID.

This module parses the first group and returns it as fact.  It parses the
second group only when asked, because the ordering is inferred from the
*OcuSync* frame layout in :mod:`antsdr_toolkit.droneid` rather than
established for this transport, and it marks the result accordingly.  A field
that a reference implementation deliberately declined to decode should not be
presented as a measurement.

Coordinates use the same radians-times-1e7 encoding as the OcuSync frame, so
they share :data:`antsdr_toolkit.droneid.constants.COORD_SCALE`.  They are
also validated the same way, per coordinate against its own range, for the
reason recorded under H2 in ``antsdr/research/validation/``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from ..droneid import constants as C
from .wifi import iter_information_elements, strip_radiotap

__all__ = [
    "CONFIDENT_BYTES",
    "DJI_OUI",
    "SUBCOMMAND_FLIGHT_PURPOSE",
    "SUBCOMMAND_FLIGHT_REG",
    "DjiWifiDroneId",
    "find_dji_element",
    "parse_dji_beacon",
    "parse_flight_reg",
]

#: DJI's organisationally unique identifier for this element.
DJI_OUI = b"\x26\x37\x12"

#: Element subcommands. 0x10 carries the telemetry; 0x11 carries free text the
#: operator typed, which is not parsed here.
SUBCOMMAND_FLIGHT_REG = 0x10
SUBCOMMAND_FLIGHT_PURPOSE = 0x11

#: How far into the element the reference parser goes before its own author
#: stopped trusting the field order: the four-byte header plus version,
#: sequence, state, a 16-byte serial and the two coordinates. Everything up to
#: here is decoded as fact; past it, only on request and flagged.
#:
#: Derived rather than written down, because counting it by hand is how it
#: goes wrong: the first attempt at this module said 30.
CONFIDENT_BYTES = struct.calcsize("<BBBB") + struct.calcsize("<BHH16sii")

_VENDOR_ELEMENT = 221
#: Element header: vendor_type, two unknown bytes, subcommand.
_HEADER = struct.Struct("<BBBB")
#: The trusted part: version, sequence, state, serial, longitude, latitude.
_CONFIDENT = struct.Struct("<BHH16sii")
#: The rest, in the order the OcuSync frame uses. Inferred, not established.
_EXTENDED = struct.Struct("<hhhhhhQiiiiBB")


@dataclass(frozen=True)
class DjiWifiDroneId:
    """One DJI DroneID record lifted out of a beacon."""

    serial: str
    latitude: float | None
    longitude: float | None
    version: int
    sequence: int
    state_info: int
    subcommand: int
    transmitter_mac: str | None = None
    ssid: str | None = None
    #: Everything past :data:`CONFIDENT_BYTES`, or ``None`` when it was not
    #: requested or the record was too short to hold it.
    extended: dict[str, Any] | None = None

    @property
    def position(self) -> tuple[float, float] | None:
        if self.latitude is None or self.longitude is None:
            return None
        return self.latitude, self.longitude

    @property
    def product_name(self) -> str | None:
        """Model name, when the extended fields were parsed and mapped.

        Carries the same warning as the rest of :attr:`extended`: the product
        type byte's position is inferred from the OcuSync frame, not
        established for this transport.
        """
        if not self.extended:
            return None
        code = self.extended.get("product_type")
        return None if code is None else C.product_name(int(code))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "serial": self.serial, "position": self.position,
            "version": self.version, "sequence": self.sequence,
            "state_info": self.state_info, "subcommand": self.subcommand,
            "transmitter_mac": self.transmitter_mac, "ssid": self.ssid,
        }
        if self.extended is not None:
            out["extended_unverified_layout"] = self.extended
        return out


def _pair(lat_raw: int, lon_raw: int) -> tuple[float | None, float | None]:
    """A coordinate pair, each half checked against its own range.

    The same rule as everywhere else in the toolkit: latitude to 90, longitude
    to 180, a zero *pair* means no fix but a lone zero is a real place, and
    half a position is not a position. See H2 in the validation record.
    """
    if lat_raw == 0 and lon_raw == 0:
        return None, None
    latitude = lat_raw / C.COORD_SCALE
    longitude = lon_raw / C.COORD_SCALE
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None, None
    return latitude, longitude


def find_dji_element(body: bytes) -> bytes | None:
    """The DJI vendor element's payload from a beacon body, or ``None``.

    Returns everything after the three OUI bytes, so the element header is the
    first four bytes of the result.
    """
    for element_id, payload in iter_information_elements(body):
        if element_id == _VENDOR_ELEMENT and len(payload) >= 4 and payload[:3] == DJI_OUI:
            return payload[3:]
    return None


def parse_flight_reg(record: bytes, *, extended: bool = False) -> DjiWifiDroneId | None:
    """Decode a flight-registration record, header included.

    Returns ``None`` for a subcommand this does not decode, which includes the
    free-text flight-purpose record. Raises :class:`ValueError` only when the
    record claims to be telemetry and is too short to be, because that is a
    malformed frame rather than an uninteresting one.

    With ``extended``, the fields past :data:`CONFIDENT_BYTES` are decoded too
    and returned in :attr:`DjiWifiDroneId.extended`. They are read in the order
    the OcuSync frame uses, which the reference parser declined to trust for
    this transport, so treat them as a hypothesis to check against a real
    capture rather than as readings.
    """
    if len(record) < _HEADER.size:
        raise ValueError(f"a DJI element header is {_HEADER.size} bytes, got {len(record)}")
    _vendor_type, _unk1, _unk2, subcommand = _HEADER.unpack_from(record, 0)
    if subcommand != SUBCOMMAND_FLIGHT_REG:
        return None

    body = record[_HEADER.size:]
    if len(body) < _CONFIDENT.size:
        raise ValueError(
            f"a flight-registration record needs {_CONFIDENT.size} bytes after its "
            f"header, got {len(body)}")
    version, sequence, state, serial_raw, lon_raw, lat_raw = _CONFIDENT.unpack_from(body, 0)
    latitude, longitude = _pair(lat_raw, lon_raw)

    extra: dict[str, Any] | None = None
    if extended:
        rest = body[_CONFIDENT.size:]
        if len(rest) >= _EXTENDED.size:
            (height, altitude, v_n, v_e, v_u, yaw, gps_time,
             pilot_lat, pilot_lon, home_lon, home_lat,
             product_type, uuid_len) = _EXTENDED.unpack_from(rest, 0)
            pilot = _pair(pilot_lat, pilot_lon)
            home = _pair(home_lat, home_lon)
            extra = {
                "height_m": float(height), "altitude_m": float(altitude),
                "v_north_m_s": float(v_n), "v_east_m_s": float(v_e),
                "v_up_m_s": float(v_u), "yaw_deg": yaw / 100.0,
                "gps_time_ms": int(gps_time),
                "pilot_position": pilot if pilot[0] is not None else None,
                "home_position": home if home[0] is not None else None,
                "product_type": int(product_type),
                "uuid": rest[_EXTENDED.size:_EXTENDED.size + min(int(uuid_len), 20)].hex(),
                "_warning": "field order inferred from the OcuSync frame, not "
                            "established for the Wi-Fi element; the reference "
                            "parser leaves these undecoded",
            }

    return DjiWifiDroneId(
        serial=serial_raw.split(b"\x00", 1)[0].decode("utf-8", "replace"),
        latitude=latitude, longitude=longitude,
        version=int(version), sequence=int(sequence), state_info=int(state),
        subcommand=int(subcommand), extended=extra)


def parse_dji_beacon(frame: bytes, *, extended: bool = False) -> DjiWifiDroneId | None:
    """Decode DJI DroneID from a whole 802.11 beacon frame.

    Accepts a frame with or without a radiotap header. Returns ``None`` when
    the frame is not a beacon or carries no DJI element, which is the normal
    case for almost every frame in the air.
    """
    data = strip_radiotap(frame)
    if len(data) < 24 + 12:
        return None
    frame_control = data[0]
    if (frame_control & 0x0C) >> 2 != 0 or (frame_control >> 4) & 0x0F != 8:
        return None
    body = data[24 + 12:]
    record = find_dji_element(body)
    if record is None:
        return None
    parsed = parse_flight_reg(record, extended=extended)
    if parsed is None:
        return None
    ssid = None
    for element_id, payload in iter_information_elements(body):
        if element_id == 0:
            ssid = payload.decode("utf-8", "replace") or None
            break
    return DjiWifiDroneId(
        serial=parsed.serial, latitude=parsed.latitude, longitude=parsed.longitude,
        version=parsed.version, sequence=parsed.sequence, state_info=parsed.state_info,
        subcommand=parsed.subcommand, extended=parsed.extended,
        transmitter_mac=":".join(f"{b:02x}" for b in data[10:16]), ssid=ssid)


def build_beacon(record_body: bytes, *, subcommand: int = SUBCOMMAND_FLIGHT_REG,
                 ssid: str = "DJI-TEST",
                 transmitter_mac: bytes = b"\x60\x60\x1f\x00\x00\x03") -> bytes:
    """A beacon carrying a DJI element, for tests. Never transmitted (ADR-0001)."""
    from .wifi import build_beacon as _build

    element = DJI_OUI + _HEADER.pack(0x00, 0x00, 0x00, subcommand) + record_body
    header = (struct.pack("<BB H", 0x80, 0x00, 0)
              + b"\xff" * 6 + transmitter_mac + transmitter_mac + struct.pack("<H", 0))
    fixed = struct.pack("<QHH", 0, 100, 0x0421)
    ssid_bytes = ssid.encode("utf-8")[:32]
    elements = bytes([0, len(ssid_bytes)]) + ssid_bytes
    if len(element) > 255:
        raise ValueError(f"a vendor element holds 255 bytes, got {len(element)}")
    elements += bytes([_VENDOR_ELEMENT, len(element)]) + element
    del _build
    return header + fixed + elements
