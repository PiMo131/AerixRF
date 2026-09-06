"""Analog video links: the one drone signal an open receiver still decodes.

``fpv`` holds the 5.8 GHz channel plan, the detection metrics that separate a
frequency-modulated video carrier from Wi-Fi, and a line-rate lock that says
which analog standard is on the air.

``video_decode`` goes the rest of the way and turns the carrier into pictures:
sync separation, per-line black restoration, field assembly and image output.
``video_synth`` builds the material both are tested against, including a full
field sequence carrying a real image so a decode can be checked against the
picture that went in rather than against a signal statistic.
"""

from .fpv import CHANNELS, FpvDetection, detect_fpv, envelope_cv, nearest_channel, sync_lock
from .video_decode import (
    DecodedField,
    decode_fields,
    decode_from_iq,
    identify_standard,
    weave,
    write_png,
)

__all__ = [
    "CHANNELS",
    "DecodedField",
    "FpvDetection",
    "decode_fields",
    "decode_from_iq",
    "detect_fpv",
    "envelope_cv",
    "identify_standard",
    "nearest_channel",
    "sync_lock",
    "weave",
    "write_png",
]
