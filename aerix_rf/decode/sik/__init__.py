"""SiK-class (Si4432, ArduPilot SiK firmware) GFSK PHY decode chain.

Evidence level 1 (synthetic) throughout this package: everything here is
validated only against a synthetic generator (``synth.py``) that shares the
same model assumptions as the demodulator (notably the *inferred*, not
firmware-confirmed, 0x2DD4 sync word). This does NOT demonstrate decoding a
real SiK radio. See ``docs/design/sik-mavlink-passive-decode.md`` (T1).
"""

from .gfsk import demod_gfsk, estimate_rate, find_sync
from .synth import SIK_AIR_RATES_BPS, SikBurst, make_sik_burst

__all__ = [
    "demod_gfsk",
    "estimate_rate",
    "find_sync",
    "make_sik_burst",
    "SikBurst",
    "SIK_AIR_RATES_BPS",
]
