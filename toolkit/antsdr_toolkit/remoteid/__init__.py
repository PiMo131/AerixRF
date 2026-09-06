"""Standard Remote ID: the identity broadcast the law compels.

``odid`` decodes ASTM F3411 / ASD-STAN EN 4709-002 messages and message packs;
``wifi`` pulls them out of an 802.11 Beacon frame, which is the only transport
DJI implements.

For a fleet of OcuSync 4 airframes this is the whole identity story, because
their proprietary DroneID payload is encrypted. The catch is the class label:
C0, under 250 g, carries no obligation at all, so a DJI Neo and a Mini 4 Pro
on its standard battery broadcast nothing here.
"""

from .odid import (
    BasicIdMessage,
    LocationMessage,
    MessagePack,
    OperatorIdMessage,
    SystemMessage,
    decode_message,
    decode_pack,
)
from .wifi import OdidBeacon, find_odid_element, parse_beacon

__all__ = [
    "BasicIdMessage",
    "LocationMessage",
    "MessagePack",
    "OdidBeacon",
    "OperatorIdMessage",
    "SystemMessage",
    "decode_message",
    "decode_pack",
    "find_odid_element",
    "parse_beacon",
]
