"""DJI DroneID: constants, Zadoff-Chu pilots, detection, decoding.

An independent numpy implementation of the burst the DJI OcuSync link
broadcasts alongside video and control, built from the published descriptions
of proto17/dji_droneid (MIT) and RUB-SysSec/DroneSecurity (AGPL-3.0, read but
not copied).  See ``constants`` for the waveform and ``antsdr/research`` for
what the research established about which generations are decodable.
"""

from .constants import (
    HOP_CENTRES_HZ,
    PRODUCT_TYPES,
    SUPPORTED_RATES_HZ,
    burst_duration_s,
    burst_length,
    cp_schedule,
    fft_size,
    is_supported_rate,
)

__all__ = [
    "HOP_CENTRES_HZ",
    "PRODUCT_TYPES",
    "SUPPORTED_RATES_HZ",
    "burst_duration_s",
    "burst_length",
    "cp_schedule",
    "fft_size",
    "is_supported_rate",
]
