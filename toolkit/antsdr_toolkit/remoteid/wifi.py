"""Pull Open Drone ID out of an 802.11 Beacon frame.

DJI transmits standard Remote ID over Wi-Fi Beacon and nothing else: no
Bluetooth, no Wi-Fi NAN *(verified: verdict 7, ``dji-eu-rid``)*.  So for the
DJI airframes that must broadcast, this path is the whole receiver.

Where the payload sits
----------------------
A beacon frame carries a list of information elements, and Open Drone ID rides
in a vendor-specific one::

    element id  0xDD (221, vendor specific)
    length      1 byte, of everything after it
    oui         FA:0B:BC        ASD-STAN
    oui type    0x0D
    counter     1 byte, incremented per transmission
    payload     an Open Drone ID message pack

The counter is the only part not defined by the message format itself; it
comes from ``ODID_service_info`` in ``opendroneid/opendroneid-core-c``
(``libopendroneid/odid_wifi.h``).  It is useful for spotting a replayed or
duplicated frame, so it is returned rather than skipped.

What this module is not
-----------------------
It does not receive.  It parses frames that something else captured, which
means a commodity Wi-Fi adapter in monitor mode, not the E200: openwifi on the
E200 is OFDM-only and cannot demodulate the 802.11b rates that reference
Remote ID beacons use on 2.4 GHz *(verified: verdict 6,
``openwifi-personality``)*.  That is a genuine gap in the E200's coverage, and
pretending otherwise would put a hole in a detection network.

Remote ID is also unauthenticated, so a frame proves only that something
transmitted it.  Spoofing needs no special equipment
(``cyber-defence-campus/droneRemoteIDSpoofer``).  Treat a decoded identity as
a claim, corroborated by the RF observations around it.

Pure standard library.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from .odid import MessagePack, decode_pack

__all__ = [
    "ASD_STAN_OUI",
    "BEACON_FIXED_BYTES",
    "ODID_OUI_TYPE",
    "OdidBeacon",
    "find_odid_element",
    "iter_information_elements",
    "parse_beacon",
    "parse_service_info",
    "strip_radiotap",
]

#: ASD-STAN's organisationally unique identifier, and the type byte that marks
#: the element as Open Drone ID rather than any other ASD-STAN payload.
ASD_STAN_OUI = b"\xfa\x0b\xbc"
ODID_OUI_TYPE = 0x0D

#: Vendor-specific element id.
_VENDOR_ELEMENT = 221
#: 802.11 MAC header: frame control, duration, three addresses, sequence.
_MAC_HEADER_BYTES = 24
#: Beacon fixed parameters before the elements: timestamp, interval, capability.
BEACON_FIXED_BYTES = 12


@dataclass(frozen=True)
class OdidBeacon:
    """Everything one beacon frame yielded."""

    pack: MessagePack
    message_counter: int
    transmitter_mac: str | None
    ssid: str | None

    def summary(self) -> dict[str, Any]:
        out = self.pack.summary()
        out["message_counter"] = self.message_counter
        out["transmitter_mac"] = self.transmitter_mac
        out["ssid"] = self.ssid
        return out


def strip_radiotap(frame: bytes) -> bytes:
    """Remove a radiotap header if one is present.

    Radiotap starts with a zero version byte, a pad byte and a little-endian
    16-bit length covering the header itself.  Captures from ``libpcap`` on a
    monitor-mode interface usually carry one; frames from other sources do
    not, so this detects rather than assumes.
    """
    if len(frame) >= 4 and frame[0] == 0 and frame[1] == 0:
        length = struct.unpack_from("<H", frame, 2)[0]
        if 8 <= length <= len(frame):
            return frame[length:]
    return frame


def iter_information_elements(body: bytes):
    """Yield ``(element_id, payload)`` over a tag-length-value element list.

    Stops at the first element whose declared length runs past the end of the
    buffer, rather than raising: a truncated capture is ordinary, and the
    elements before the truncation are still good.
    """
    offset = 0
    while offset + 2 <= len(body):
        element_id, length = body[offset], body[offset + 1]
        start = offset + 2
        if start + length > len(body):
            return
        yield element_id, body[start:start + length]
        offset = start + length


def find_odid_element(body: bytes) -> bytes | None:
    """The Open Drone ID vendor element's payload, or ``None``.

    Returns everything after the OUI type byte, which is the service info: a
    counter followed by the message pack.
    """
    for element_id, payload in iter_information_elements(body):
        if (element_id == _VENDOR_ELEMENT and len(payload) >= 4
                and payload[:3] == ASD_STAN_OUI and payload[3] == ODID_OUI_TYPE):
            return payload[4:]
    return None


def parse_service_info(service_info: bytes) -> tuple[int, MessagePack]:
    """Split the counter from the message pack and decode the pack."""
    if len(service_info) < 4:
        raise ValueError(f"service info needs a counter and a pack, got "
                         f"{len(service_info)} byte(s)")
    return service_info[0], decode_pack(service_info[1:])


def _ssid(body: bytes) -> str | None:
    for element_id, payload in iter_information_elements(body):
        if element_id == 0:
            return payload.decode("utf-8", "replace") or None
    return None


def _mac(raw: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in raw)


def parse_beacon(frame: bytes) -> OdidBeacon | None:
    """Decode Open Drone ID from a whole 802.11 beacon frame.

    Accepts a frame with or without a radiotap header.  Returns ``None`` when
    the frame is not a beacon or carries no Open Drone ID element, which is
    the normal case for almost every frame in the air; raises only when the
    element is present but malformed, because that is worth knowing about.
    """
    data = strip_radiotap(frame)
    if len(data) < _MAC_HEADER_BYTES + BEACON_FIXED_BYTES:
        return None
    # Type 0 subtype 8 is a beacon: the low two bits of byte 0 are the
    # protocol version, then type, then subtype.
    frame_control = data[0]
    if (frame_control & 0x0C) >> 2 != 0 or (frame_control >> 4) & 0x0F != 8:
        return None

    body = data[_MAC_HEADER_BYTES + BEACON_FIXED_BYTES:]
    service_info = find_odid_element(body)
    if service_info is None:
        return None
    counter, pack = parse_service_info(service_info)
    return OdidBeacon(pack=pack, message_counter=counter,
                      transmitter_mac=_mac(data[10:16]), ssid=_ssid(body))


def build_beacon(service_info: bytes, *, ssid: str = "RID-TEST",
                 transmitter_mac: bytes = b"\x60\x60\x1f\x00\x00\x01") -> bytes:
    """A minimal beacon frame carrying ``service_info``, for tests.

    Not a transmitter and not transmittable: the toolkit is receive-only
    (``antsdr/docs/decisions/ADR-0001``).  This exists so the parser can be
    tested against a frame rather than against its own output.
    """
    if len(transmitter_mac) != 6:
        raise ValueError(f"a MAC address is 6 bytes, got {len(transmitter_mac)}")
    header = (struct.pack("<BB H", 0x80, 0x00, 0)      # beacon, no duration
              + b"\xff" * 6 + transmitter_mac + transmitter_mac
              + struct.pack("<H", 0))                   # sequence control
    fixed = struct.pack("<QHH", 0, 100, 0x0421)
    ssid_bytes = ssid.encode("utf-8")[:32]
    elements = bytes([0, len(ssid_bytes)]) + ssid_bytes
    vendor = ASD_STAN_OUI + bytes([ODID_OUI_TYPE]) + service_info
    if len(vendor) > 255:
        raise ValueError(f"a vendor element holds 255 bytes, got {len(vendor)}")
    elements += bytes([_VENDOR_ELEMENT, len(vendor)]) + vendor
    return header + fixed + elements
