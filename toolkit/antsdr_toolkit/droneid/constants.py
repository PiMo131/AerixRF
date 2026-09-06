"""Physical-layer constants of the DJI DroneID burst.

DroneID is the side channel DJI drones broadcast alongside the OcuSync link,
carrying the aircraft serial number, its position, the operator's position and
the take-off point.  It is LTE-like OFDM and was reverse engineered
independently by David Protzman (proto17/dji_droneid, MIT) and by the Ruhr
University Bochum group behind the NDSS 2023 paper (RUB-SysSec/DroneSecurity,
AGPL-3.0).  The two agree on every number below.

Everything here is a *protocol fact*, transcribed from the descriptions in
those projects and re-derived where a formula exists.  No code was copied
from the AGPL implementation; the MIT MATLAB reference was used to check the
formulas.  See ``antsdr/docs/decisions/ADR-0003`` for the licence policy and
``antsdr/research/landscape.md`` for what is and is not decodable.

The waveform
------------
============================  ====================================================
Subcarrier spacing            15 kHz
Occupied carriers             601 = 600 data carriers plus a null DC carrier
Occupied bandwidth            9 MHz (15.36 MHz including guards, "10 MHz")
FFT size                      ``sample_rate / 15 kHz`` (1024 at 15.36 MSPS)
Symbols per burst             9, or 8 on Mavic Pro and Mavic 2 ("legacy")
Cyclic prefix schedule        long, short x 7, long
Long CP                       ``round(sample_rate / 192000)``: 80 at 15.36 MSPS
Short CP                      ``round(4.6875 us * sample_rate)``: 72 at 15.36 MSPS
Burst length                  9880 samples = 643.2 us at 15.36 MSPS
Repetition                    about every 600 ms
Pilots                        Zadoff-Chu, roots 600 and 147, on symbols 4 and 6
Data                          QPSK, 1200 bits per symbol, no pilots
Scrambler                     LTE Gold sequence, c_init 0x12345678, Nc = 1600
Channel coding                LTE turbo, rate matched to E = 7200 from D = 1412
Payload                       176 bytes protected by CRC-24A, holding a 91-byte
                              frame protected by a DJI CRC-16
============================  ====================================================

Sample rates
------------
``sample_rate / 15 kHz`` must be an integer, and the reference implementations
additionally want a power-of-two FFT, which leaves 15.36, 30.72 and 61.44 MSPS.
20 MSPS - the figure people reach for because it is the E200's host-link
ceiling on the UHD personality - is **not** a valid DroneID rate: 20e6 / 15e3
is 1333.3.  Capture at 15.36 MSPS instead (a snapshot on the stock IIO
firmware, see ``antsdr_toolkit.hardware.CAPTURE_TIERS``).
"""

from __future__ import annotations

import math
from types import MappingProxyType

__all__ = [
    "COORD_SCALE",
    "CRC16_INIT",
    "CRC16_POLY",
    "CRC24A_POLY",
    "DATA_SYMBOLS",
    "FRAME_BYTES",
    "HOP_CENTRES_HZ",
    "LEGACY_SYMBOLS",
    "N_CARRIERS",
    "N_DATA_CARRIERS",
    "N_SYMBOLS",
    "PAYLOAD_BYTES",
    "PRODUCT_TYPES",
    "RATE_MATCH_D",
    "RATE_MATCH_E",
    "RM_PERM",
    "SCRAMBLER_C_INIT",
    "SCRAMBLER_NC",
    "SUBCARRIER_SPACING_HZ",
    "SUPPORTED_RATES_HZ",
    "ZC_ROOTS",
    "ZC_SYMBOLS",
    "burst_length",
    "cp_schedule",
    "fft_size",
    "is_supported_rate",
    "zc_body_offsets",
]

#: DJI encodes latitude and longitude as radians scaled by 1e7, so degrees are
#: multiplied by ``1e7 * pi / 180`` = 174532.925199...
#:
#: One definition, used by both the decoder and the burst synthesiser. They
#: previously carried their own: 174533.0 in the receiver against 1e7/57.29578
#: in the synthesiser. The difference is 4.3 parts in ten million, which is
#: about 2.5 m of position at Dutch latitudes, and the round-trip test did not
#: catch it because its tolerance was wider than the error. A shared constant
#: is the only way two sides of a codec cannot drift.
COORD_SCALE = 1e7 * math.pi / 180.0

SUBCARRIER_SPACING_HZ = 15e3
N_CARRIERS = 601          # 600 data carriers plus the null DC carrier
N_DATA_CARRIERS = 600
N_SYMBOLS = 9
LEGACY_SYMBOLS = 8        # Mavic Pro / Mavic 2 omit the first symbol

#: 0-based indices of the two Zadoff-Chu pilot symbols in a 9-symbol burst.
ZC_SYMBOLS = (3, 5)
#: Their roots, found by brute force in the reference implementation.
ZC_ROOTS = (600, 147)
#: 0-based indices of the symbols carrying QPSK payload. Symbol 0 descrambles
#: to all zeros and carries nothing, but is transmitted.
DATA_SYMBOLS = (1, 2, 4, 6, 7, 8)

#: LTE Gold scrambler (36.211 section 7.2).
SCRAMBLER_C_INIT = 0x12345678
SCRAMBLER_NC = 1600

#: LTE rate matching (36.212 section 5.1.4.1). D is the turbo output length
#: per stream (176 bytes plus four tail bits), E the number of coded bits that
#: fit the six QPSK data symbols.
RATE_MATCH_D = 1412
RATE_MATCH_E = 7200
#: Sub-block interleaver column permutation, 36.212 table 5.1.4-1.
RM_PERM = (0, 16, 8, 24, 4, 20, 12, 28, 2, 18, 10, 26, 6, 22, 14, 30,
           1, 17, 9, 25, 5, 21, 13, 29, 3, 19, 11, 27, 7, 23, 15, 31)

PAYLOAD_BYTES = 176       # what the turbo decoder yields, CRC-24A protected
FRAME_BYTES = 91          # the DroneID frame inside it, CRC-16 protected

#: CRC-24A of 36.212, used over the 176-byte payload.
CRC24A_POLY = 0x864CFB
#: DJI's CRC-16 over the 91-byte frame: reflected 0x1021 with this seed. The
#: seed comes from DJI's own Guidance SDK.
CRC16_POLY = 0x1021
CRC16_INIT = 0x3692

#: Sample rates with an integer FFT size and a power-of-two FFT.
SUPPORTED_RATES_HZ = (15.36e6, 30.72e6, 61.44e6)

#: Burst centres reported by the reference implementations, in Hz. The union
#: of proto17's list and DroneSecurity's live-receiver hop list; neither is a
#: complete channel plan and the hop *sequence* is not documented anywhere
#: open.
HOP_CENTRES_HZ = (
    2399.5e6, 2414.5e6, 2429.5e6, 2434.5e6, 2444.5e6, 2459.5e6, 2474.5e6,
    5721.5e6, 5731.5e6, 5741.5e6, 5756.5e6, 5761.5e6, 5771.5e6, 5786.5e6,
    5801.5e6, 5816.5e6, 5831.5e6,
)

#: Product type byte to model name, as transcribed by both reference projects.
#: Gaps in the numbering are gaps in the published table, not in the protocol.
PRODUCT_TYPES = MappingProxyType({
    1: "Inspire 1", 2: "Phantom 3 Series", 3: "Phantom 3 Series", 4: "Phantom 3 Std",
    5: "M100", 6: "ACEONE", 7: "WKM", 8: "NAZA", 9: "A2", 10: "A3",
    11: "Phantom 4", 12: "MG1", 14: "M600", 15: "Phantom 3 4k", 16: "Mavic Pro",
    17: "Inspire 2", 18: "Phantom 4 Pro", 20: "N2", 21: "Spark", 23: "M600 Pro",
    24: "Mavic Air", 25: "M200", 26: "Phantom 4 Series", 27: "Phantom 4 Adv",
    28: "M210", 30: "M210RTK", 31: "A3_AG", 32: "MG2", 34: "MG1A",
    35: "Phantom 4 RTK", 36: "Phantom 4 Pro V2.0", 38: "MG1P", 40: "MG1P-RTK",
    41: "Mavic 2", 44: "M200 V2 Series", 51: "Mavic 2 Enterprise",
    53: "Mavic Mini", 58: "Mavic Air 2", 59: "P4M", 60: "M300 RTK",
    61: "DJI FPV", 63: "Mini 2", 64: "AGRAS T10", 65: "AGRAS T30",
    66: "Air 2S", 67: "M30", 68: "DJI Mavic 3", 69: "Mavic 2 Enterprise Advanced",
    70: "Mini SE",
})


def fft_size(sample_rate_hz: float) -> int:
    """``sample_rate / 15 kHz``; ``ValueError`` when that is not an integer.

    The result need not be a power of two for this toolkit's own FFTs, but the
    reference implementations assume one, so non-power-of-two rates are
    accepted with the caller warned by :func:`is_supported_rate`.
    """
    ratio = float(sample_rate_hz) / SUBCARRIER_SPACING_HZ
    n = round(ratio)
    if abs(ratio - n) > 1e-6 or n <= 0:
        raise ValueError(
            f"sample_rate_hz {sample_rate_hz / 1e6:.6f} MSPS is not a multiple of the "
            f"{SUBCARRIER_SPACING_HZ / 1e3:.0f} kHz subcarrier spacing "
            f"(FFT size would be {ratio:.4f}); use one of "
            + ", ".join(f"{r / 1e6:g}" for r in SUPPORTED_RATES_HZ)
        )
    if n < N_CARRIERS:
        raise ValueError(
            f"sample_rate_hz {sample_rate_hz / 1e6:.6f} MSPS gives an FFT of {n} bins, "
            f"too few for the {N_CARRIERS} occupied carriers (9 MHz)"
        )
    return int(n)


def is_supported_rate(sample_rate_hz: float) -> bool:
    """True when the rate gives an integer, power-of-two FFT size."""
    try:
        n = fft_size(sample_rate_hz)
    except ValueError:
        return False
    return n & (n - 1) == 0


def cp_schedule(sample_rate_hz: float, *, legacy: bool = False) -> tuple[int, ...]:
    """Cyclic prefix lengths in samples: long, short x 7, long.

    ``long = round(fs / 192000)`` and ``short = round(4.6875 us * fs)``, which
    give (80, 72 x 7, 80) at 15.36 MSPS, (160, 144 x 7, 160) at 30.72 and
    (320, 288 x 7, 320) at 61.44.

    ``legacy`` is the eight-symbol variant of the Mavic Pro and Mavic 2:
    (long, short x 6, long).  It keeps both long prefixes - they bracket the
    burst - and drops one short symbol, giving 8784 samples at 15.36 MSPS.
    """
    fs = float(sample_rate_hz)
    fft_size(fs)  # validate
    long_cp = round(fs / 192000.0)
    short_cp = round(4.6875e-6 * fs)
    n_short = 6 if legacy else 7
    return (long_cp,) + (short_cp,) * n_short + (long_cp,)


def burst_length(sample_rate_hz: float, *, legacy: bool = False) -> int:
    """Total samples in one burst, cyclic prefixes included."""
    n = fft_size(sample_rate_hz)
    cps = cp_schedule(sample_rate_hz, legacy=legacy)
    return len(cps) * n + sum(cps)


def burst_duration_s(sample_rate_hz: float, *, legacy: bool = False) -> float:
    """Burst length in seconds: 643.2 us for a 9-symbol burst, at any rate."""
    return burst_length(sample_rate_hz, legacy=legacy) / float(sample_rate_hz)


def symbol_offsets(sample_rate_hz: float, *, legacy: bool = False) -> tuple[int, ...]:
    """Sample offset of each symbol's *body* (after its cyclic prefix)."""
    n = fft_size(sample_rate_hz)
    offsets: list[int] = []
    pos = 0
    for cp in cp_schedule(sample_rate_hz, legacy=legacy):
        pos += cp
        offsets.append(pos)
        pos += n
    return tuple(offsets)


def zc_body_offsets(sample_rate_hz: float, *, legacy: bool = False) -> tuple[int, ...]:
    """Sample offsets of the two Zadoff-Chu symbol bodies within a burst.

    3368 and 5560 at 15.36 MSPS for a 9-symbol burst: the first is
    ``long + 3 * (N + short)`` and the second follows two symbols later.
    """
    offsets = symbol_offsets(sample_rate_hz, legacy=legacy)
    idx = ZC_SYMBOLS if not legacy else tuple(i - 1 for i in ZC_SYMBOLS)
    return tuple(offsets[i] for i in idx)


def data_symbol_indices(*, legacy: bool = False) -> tuple[int, ...]:
    """Indices of the QPSK payload symbols within the extracted symbol list."""
    if not legacy:
        return DATA_SYMBOLS
    return tuple(i - 1 for i in DATA_SYMBOLS if i >= 1)


def channel_for(frequency_hz: float, *, tolerance_hz: float = 2e6) -> float | None:
    """Nearest known DroneID centre within ``tolerance_hz``, else ``None``."""
    best = min(HOP_CENTRES_HZ, key=lambda f: abs(f - float(frequency_hz)))
    return best if abs(best - float(frequency_hz)) <= float(tolerance_hz) else None


def occupied_bandwidth_hz() -> float:
    """9.0 MHz: 600 data carriers at 15 kHz spacing."""
    return N_DATA_CARRIERS * SUBCARRIER_SPACING_HZ


def guard_bandwidth_hz() -> float:
    """15.36 MHz: the nominal channel width including guard bands."""
    return 15.36e6


def _check_tables() -> None:
    assert len(RM_PERM) == 32 and sorted(RM_PERM) == list(range(32))
    assert RATE_MATCH_D == PAYLOAD_BYTES * 8 + 4
    assert RATE_MATCH_E == len(DATA_SYMBOLS) * N_DATA_CARRIERS * 2
    assert math.isclose(burst_duration_s(15.36e6), 643.229e-6, rel_tol=1e-4)


_check_tables()
