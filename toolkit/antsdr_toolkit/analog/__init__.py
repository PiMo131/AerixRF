"""Analog video links: the one drone signal an open receiver still decodes.

``fpv`` holds the 5.8 GHz channel plan, the detection metrics that separate a
frequency-modulated video carrier from Wi-Fi, and a line-rate lock that says
which analog standard is on the air.
"""

from .fpv import CHANNELS, FpvDetection, detect_fpv, envelope_cv, nearest_channel, sync_lock

__all__ = [
    "CHANNELS",
    "FpvDetection",
    "detect_fpv",
    "envelope_cv",
    "nearest_channel",
    "sync_lock",
]
