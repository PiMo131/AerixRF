"""Standard Remote ID: the identity broadcast the law compels.

``odid`` decodes ASTM F3411 / ASD-STAN EN 4709-002 messages and message packs;
``wifi`` pulls them out of an 802.11 Beacon frame, which is the only transport
DJI implements.

``dji_wifi`` reads a second, quite different payload out of the same beacons:
DJI's own proprietary DroneID under OUI 26:37:12, which its Wi-Fi-link
aircraft carry and which no regulation governs. That one matters most for the
airframes standard Remote ID misses.

The catch on the standard side is the class mark: C1 and above must broadcast
and C0 need not, so a DJI Neo and a Mini 4 Pro as shipped are under no
obligation and are generally reported silent there. The DJI element is the
remaining published route to a serial number for such an aircraft, if it
emits one at all in Wi-Fi mode, which nobody in this project's research record
has tested.
"""

from .dji_wifi import DjiWifiDroneId, parse_dji_beacon
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
    "DjiWifiDroneId",
    "LocationMessage",
    "MessagePack",
    "OdidBeacon",
    "OperatorIdMessage",
    "SystemMessage",
    "decode_message",
    "decode_pack",
    "find_odid_element",
    "parse_beacon",
    "parse_dji_beacon",
]
