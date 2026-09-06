"""Frequency bands, channel tables and DroneID centres used to plan a sweep.

Everything here is *data*: absolute frequencies in Hz (floats, per the toolkit
convention) plus the provenance of each number.  The band plans are the RF
extents a passive receiver should tile when looking for drone links; the
channel tables are the discrete carrier frequencies of protocols whose
channel grid is public, which :func:`antsdr_toolkit.scan.planner.plan_dwells`
groups into the fewest possible receiver dwells.

Verified vs inferred
--------------------
* **Verified** (read from the cited source files by the research phase):
  the 62-entry 5.8 GHz analog FPV channel table (:data:`FPV_5G8_CHANNELS`,
  ``fpv_scanner.sh`` lines 52-69 of lukeswitz/fpv-sdr; the L/5.3 band is
  also the "D / 5.3" row of sheaivey/rx5808-pro-diversity ``channels.cpp``),
  the DJI DroneID centre frequencies (:data:`DRONEID_CENTRES_MHZ`, union of
  RUB-SysSec/DroneSecurity ``droneid_receiver_live.py`` line 168 and the
  proto17/dji_droneid README, plus the four channels the MicroPhase O4
  firmware monitors), the ExpressLRS channel grids (:data:`ELRS_GRIDS`,
  ``src/lib/FHSS/FHSS.cpp``), the RF-Vision-UAV-Tracker sector centres
  5745/5785/5825 MHz (``backend_rk3588/config.py``), the OpenHD non-standard
  Wi-Fi extents (``ohd_interface/inc/wifi_channel.h``) and wfb-ng's default
  channel 165 (5825 MHz).
* **Inferred / regulatory**: the ITU ISM edges (2400-2483.5, 5725-5875,
  902-928, 433.05-434.79, 863-870 MHz) are standard allocations, not read
  from a repository; the 1.2/1.3 GHz analog FPV band (1080-1360 MHz) comes
  from common VTX channel plans and was **not** verified against a source in
  the research corpus.  Transmitting there is illegal in most jurisdictions
  (it overlaps GNSS L2/E6 and the 23 cm amateur allocation); this toolkit
  only ever receives.

Sources
-------
* https://github.com/lukeswitz/fpv-sdr (fpv_scanner.sh channel table; GPL/MIT
  mixed - only the table data is reproduced here)
* https://github.com/sheaivey/rx5808-pro-diversity (channels.cpp, L/5.3 band)
* https://github.com/RUB-SysSec/DroneSecurity (hop list; AGPL - data only)
* https://github.com/proto17/dji_droneid (README frequency list; MIT)
* https://github.com/alphafox02/antsdr_dji_droneid (O4 firmware 'auto' channels)
* https://github.com/ExpressLRS/ExpressLRS (src/lib/FHSS/FHSS.cpp regulatory domains)
* https://github.com/ALPssdz/RF-Vision-UAV-Tracker (5.8 GHz sector centres; MIT)
* https://github.com/OpenHD/OpenHD, https://github.com/svpcom/wfb-ng (Wi-Fi FPV extents)
* https://github.com/ArduPilot/SiK (433/868/915 MHz telemetry radios)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ALPSSDZ_SECTORS_MHZ",
    "BAND_PLANS",
    "DRONEID_CENTRES_MHZ",
    "ELRS_GRIDS",
    "FPV_5G8_CHANNELS",
    "FPV_SCAN_ORDER",
    "Band",
    "FpvChannel",
    "band_table",
    "elrs_channels_hz",
    "fpv_channel_freqs_hz",
    "get_band",
    "list_bands",
]

MHZ = 1e6


@dataclass(frozen=True)
class Band:
    """A contiguous RF extent worth tiling with receiver dwells.

    Attributes:
        name: Short identifier used on the command line (``--band``).
        f_low_hz, f_high_hz: Absolute band edges in Hz (``f_low_hz < f_high_hz``).
        note: What the band holds and any regulatory / hardware caveat.
        sources: URLs the edges were taken from (empty when purely regulatory).
    """

    name: str
    f_low_hz: float
    f_high_hz: float
    note: str = ""
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "f_low_hz", float(self.f_low_hz))
        object.__setattr__(self, "f_high_hz", float(self.f_high_hz))
        object.__setattr__(self, "sources", tuple(self.sources))
        if not self.name:
            raise ValueError("band name must not be empty")
        if not self.f_low_hz < self.f_high_hz:
            raise ValueError(f"{self.name}: need f_low_hz < f_high_hz, got "
                             f"{self.f_low_hz} >= {self.f_high_hz}")

    @property
    def center_freq_hz(self) -> float:
        return 0.5 * (self.f_low_hz + self.f_high_hz)

    @property
    def span_hz(self) -> float:
        return self.f_high_hz - self.f_low_hz

    def contains(self, freq_hz: float) -> bool:
        """``True`` when ``freq_hz`` lies inside the band (edges inclusive)."""
        return self.f_low_hz <= float(freq_hz) <= self.f_high_hz

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "f_low_hz": self.f_low_hz,
            "f_high_hz": self.f_high_hz,
            "center_freq_hz": self.center_freq_hz,
            "span_hz": self.span_hz,
            "note": self.note,
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class FpvChannel:
    """One entry of an analog 5.8 GHz FPV channel table (frequency in Hz)."""

    name: str
    band: str
    freq_hz: float

    @property
    def freq_mhz(self) -> float:
        return self.freq_hz / MHZ


_FPV_SDR = "https://github.com/lukeswitz/fpv-sdr"
_RX5808 = "https://github.com/sheaivey/rx5808-pro-diversity"
_DRONESECURITY = "https://github.com/RUB-SysSec/DroneSecurity"
_PROTO17 = "https://github.com/proto17/dji_droneid"
_ANTSDR_DJI = "https://github.com/alphafox02/antsdr_dji_droneid"
_ELRS = "https://github.com/ExpressLRS/ExpressLRS"
_ALPSSDZ = "https://github.com/ALPssdz/RF-Vision-UAV-Tracker"
_OPENHD = "https://github.com/OpenHD/OpenHD"
_WFB_NG = "https://github.com/svpcom/wfb-ng"
_SIK = "https://github.com/ArduPilot/SiK"

# ----- 5.8 GHz analog FPV channel table ------------------------------------
# Verified: fpv_scanner.sh lines 52-69 (62 entries, 53 unique frequencies,
# 5362-5945 MHz).  Duplicates are real (R1 = IMD1 = 5658, R2 = IMD2 = D2 = 5695,
# R7 = F8 = 5880 ...); the planner de-duplicates.  Band letters: R (Raceband),
# A (Boscam A), B (Boscam B), E (Boscam E / DJI), F (Fatshark / Airwave),
# IMD (IMD6 race subset of R), D (DJI FPV digital, fpv-sdr naming) and
# L (low band, 5.3 GHz, 37 MHz steps).
_FPV_TABLE_MHZ: tuple[tuple[str, str, float], ...] = (
    ("R1", "R", 5658), ("R2", "R", 5695), ("R3", "R", 5732), ("R4", "R", 5769),
    ("R5", "R", 5806), ("R6", "R", 5843), ("R7", "R", 5880), ("R8", "R", 5917),
    ("A1", "A", 5865), ("A2", "A", 5845), ("A3", "A", 5825), ("A4", "A", 5805),
    ("A5", "A", 5785), ("A6", "A", 5765), ("A7", "A", 5745), ("A8", "A", 5725),
    ("B1", "B", 5733), ("B2", "B", 5752), ("B3", "B", 5771), ("B4", "B", 5790),
    ("B5", "B", 5809), ("B6", "B", 5828), ("B7", "B", 5847), ("B8", "B", 5866),
    ("E1", "E", 5705), ("E2", "E", 5685), ("E3", "E", 5665), ("E4", "E", 5645),
    ("E5", "E", 5885), ("E6", "E", 5905), ("E7", "E", 5925), ("E8", "E", 5945),
    ("F1", "F", 5740), ("F2", "F", 5760), ("F3", "F", 5780), ("F4", "F", 5800),
    ("F5", "F", 5820), ("F6", "F", 5840), ("F7", "F", 5860), ("F8", "F", 5880),
    ("IMD1", "IMD", 5658), ("IMD2", "IMD", 5695), ("IMD3", "IMD", 5732),
    ("IMD4", "IMD", 5769), ("IMD5", "IMD", 5806), ("IMD6", "IMD", 5843),
    ("D1", "D", 5660), ("D2", "D", 5695), ("D3", "D", 5735), ("D4", "D", 5770),
    ("D5", "D", 5805), ("D6", "D", 5878), ("D7", "D", 5914), ("D8", "D", 5839),
    ("L1", "L", 5362), ("L2", "L", 5399), ("L3", "L", 5436), ("L4", "L", 5473),
    ("L5", "L", 5510), ("L6", "L", 5547), ("L7", "L", 5584), ("L8", "L", 5621),
)

FPV_5G8_CHANNELS: tuple[FpvChannel, ...] = tuple(
    FpvChannel(name, band, mhz * MHZ) for name, band, mhz in _FPV_TABLE_MHZ
)
"""62 analog FPV channels (fpv-sdr table); 53 unique frequencies, 5362-5945 MHz."""

FPV_SCAN_ORDER: tuple[str, ...] = ("R", "A", "F", "E", "B", "D", "L")
"""Band order fpv-sdr scans in (IMD is a subset of R and is not scanned separately)."""


def fpv_channel_freqs_hz(bands: Iterable[str] | None = None) -> list[float]:
    """Unique, ascending channel frequencies (Hz) of the FPV table, optionally per band letter."""
    wanted = None if bands is None else {b.upper() for b in bands}
    freqs = {c.freq_hz for c in FPV_5G8_CHANNELS if wanted is None or c.band in wanted}
    return sorted(freqs)


# ----- DJI DroneID centres ---------------------------------------------------
# Verified union of: DroneSecurity droneid_receiver_live.py:168
# [2414.5, 2429.502441, 2434.5, 2444.5, 2459.5, 2474.5, 5721.5, 5731.5, 5741.5,
#  5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5]; proto17 README
# [2399.5, 2414.5, 2429.5, 2444.5, 2459.5, 5756.5, 5776.5, 5796.5]; MicroPhase
# O4 firmware 'auto' mode strings [2434.5, 5756.5, 5776.5, 5816.5].  The
# DroneSecurity 2429.502441 entry is rounded to 2429.5 (2.4 kHz is far below
# the +-7.5 kHz CP-based CFO capture range of a DroneID receiver).
DRONEID_CENTRES_MHZ: tuple[float, ...] = (
    2399.5, 2414.5, 2429.5, 2434.5, 2444.5, 2459.5, 2474.5,
    5721.5, 5731.5, 5741.5, 5756.5, 5761.5, 5771.5, 5776.5, 5786.5, 5796.5,
    5801.5, 5816.5, 5831.5,
)
"""Known DJI DroneID (OcuSync 2/3) burst centre frequencies in MHz, ascending."""

DRONEID_OCCUPIED_HZ = 9e6
"""Occupied bandwidth of one DroneID burst (600 x 15 kHz + DC null; 15.36 MHz with guards)."""

# ----- ExpressLRS regulatory-domain grids -----------------------------------
# Verified: FHSS.cpp - (first channel MHz, spacing MHz, channel count).
ELRS_GRIDS: dict[str, tuple[float, float, int]] = {
    "2g4": (2400.4, 1.0, 80),        # ISM 2.4 GHz, 2400.4-2479.4 MHz
    "fcc915": (903.5, 0.6, 40),      # FCC 915, 903.5-926.9 MHz
    "eu868": (863.275, 0.525, 13),   # EU 868, 863.275-869.575 MHz
}


def elrs_channels_hz(domain: str) -> list[float]:
    """Channel centres (Hz) of an ExpressLRS regulatory domain (``ELRS_GRIDS`` key)."""
    try:
        start_mhz, step_mhz, count = ELRS_GRIDS[domain]
    except KeyError as exc:
        raise ValueError(f"unknown ELRS domain {domain!r}; choose from {sorted(ELRS_GRIDS)}") from exc
    return [(start_mhz + k * step_mhz) * MHZ for k in range(count)]


ALPSSDZ_SECTORS_MHZ: tuple[float, ...] = (5745.0, 5785.0, 5825.0)
"""RF-Vision-UAV-Tracker sweep sectors (40 MHz wide at 40 MSPS, covering 5725-5845 MHz)."""


# ----- band plans ------------------------------------------------------------
def _band(name: str, low_mhz: float, high_mhz: float, note: str, *sources: str) -> Band:
    return Band(name, low_mhz * MHZ, high_mhz * MHZ, note, tuple(sources))


_BANDS: tuple[Band, ...] = (
    _band(
        "ism-2g4", 2400.0, 2483.5,
        "ITU 2.4 GHz ISM (regulatory edges, inferred). Holds Wi-Fi, OcuSync/DroneID "
        "(2399.5-2474.5 MHz centres), ELRS 2.4 (80 x 1 MHz from 2400.4 MHz), FrSky/Flysky/"
        "DSMX/HoTT/S-FHSS RC links. One 56 MHz-wide E200 tune covers most of it; at the "
        "20 MSPS host rate it takes six dwells.",
        _ELRS, _DRONESECURITY, _PROTO17,
    ),
    _band(
        "ism-5g8", 5725.0, 5875.0,
        "ITU 5.8 GHz ISM (regulatory edges, inferred). RF-Vision-UAV-Tracker sectors "
        "5745/5785/5825 MHz (40 MHz each) cover 5725-5845 MHz; DJI 5.8 GHz DroneID centres "
        "5721.5-5831.5 MHz; wfb-ng default channel 165 = 5825 MHz.",
        _ALPSSDZ, _DRONESECURITY, _WFB_NG,
    ),
    _band(
        "fpv-5g8-wide", 5645.0, 5945.0,
        "Analog 5.8 GHz FPV: the 40 standard A/B/E/F/R channels plus DJI-FPV (D) and IMD "
        "subsets span E4 5645 MHz to E8 5945 MHz (fpv-sdr table, verified). Each analog "
        "carrier is FM with ~5 MHz peak deviation (energy within +-4.5 MHz).",
        _FPV_SDR, _RX5808,
    ),
    _band(
        "fpv-l-band", 5362.0, 5621.0,
        "Analog FPV low band L1-L8 (5.3 GHz, 37 MHz steps, verified from fpv-sdr and "
        "rx5808-pro-diversity 'D / 5.3' row). Outside the ISM allocation in most regions.",
        _FPV_SDR, _RX5808,
    ),
    _band(
        "fpv-1g2", 1080.0, 1360.0,
        "Analog 1.2/1.3 GHz FPV video (common VTX plans 1080-1360 MHz; INFERRED, not "
        "verified against a source in the research corpus). Regulatory: overlaps GNSS "
        "L2/E6 and the 23 cm amateur allocation - transmission is illegal in most "
        "jurisdictions; this toolkit is passive receive only.",
    ),
    _band(
        "eu868", 863.0, 870.0,
        "EU 863-870 MHz SRD band (regulatory edges, inferred). ELRS EU868 = 13 channels at "
        "525 kHz from 863.275 MHz (verified, FHSS.cpp); TBS Crossfire, FrSky R9 and SiK "
        "868 telemetry radios live here too.",
        _ELRS, _SIK,
    ),
    _band(
        "us915", 902.0, 928.0,
        "US 902-928 MHz ISM (regulatory edges, inferred). ELRS FCC915 = 40 channels at "
        "600 kHz from 903.5 MHz (verified, FHSS.cpp); SiK/RFD900 hop over 50 channels here.",
        _ELRS, _SIK,
    ),
    _band(
        "ism-433", 433.05, 434.79,
        "ITU region-1 433 MHz ISM (regulatory edges, inferred). ELRS 433 domains and SiK "
        "433 telemetry radios (10 hop channels). Battlefield ELRS forks use arbitrary "
        "400-1000 MHz windows, so also consider a wide sub-GHz survey.",
        _ELRS, _SIK,
    ),
    _band(
        "wifi-5", 5150.0, 5895.0,
        "5 GHz Wi-Fi (U-NII-1..4 regulatory edges, inferred) used by wfb-ng/OpenIPC "
        "(default ch 165 = 5825 MHz, HT20 MCS1) and OpenHD. NOTE: OpenHD's channel table "
        "also lists non-standard 5080-6085 MHz (and 2312-2712 MHz) entries at 10/20/40 MHz "
        "widths, so a Wi-Fi-FPV hunt should extend to 5080-6085 MHz (verified from "
        "wifi_channel.h).",
        _OPENHD, _WFB_NG,
    ),
    _band(
        "dji-2g4", 2399.5, 2474.5,
        "Union of the known 2.4 GHz DJI DroneID centres (verified: DroneSecurity hop list + "
        "proto17 README). Edges are centre frequencies; each burst occupies ~9 MHz "
        "(15.36 MHz with guards), so the RF extent is ~2395-2479 MHz. Bursts are ~640 us "
        "every ~600 ms and a drone dwells 12-20 bursts per channel.",
        _DRONESECURITY, _PROTO17,
    ),
    _band(
        "dji-5g8", 5721.5, 5831.5,
        "Union of the known 5.8 GHz DJI DroneID centres (verified: DroneSecurity hop list, "
        "proto17 README, MicroPhase O4 firmware 'auto' channels 5756.5/5776.5/5816.5). "
        "Edges are centre frequencies; RF extent ~5717-5836 MHz.",
        _DRONESECURITY, _PROTO17, _ANTSDR_DJI,
    ),
)

BAND_PLANS: dict[str, Band] = {b.name: b for b in _BANDS}
"""Named band plans selectable with ``antsdr-tk sweep --band NAME``."""


def get_band(name_or_band: str | Band) -> Band:
    """Resolve a band name (case-insensitive) or pass a :class:`Band` through."""
    if isinstance(name_or_band, Band):
        return name_or_band
    key = str(name_or_band).strip().lower()
    try:
        return BAND_PLANS[key]
    except KeyError as exc:
        raise ValueError(f"unknown band {name_or_band!r}; choose from {list_bands()}") from exc


def list_bands() -> list[str]:
    """Band names in definition order."""
    return list(BAND_PLANS)


def band_table(bands: Sequence[Band] | None = None) -> list[dict[str, Any]]:
    """Plain rows (``Band.to_dict``) for printing or JSON export."""
    return [b.to_dict() for b in (bands if bands is not None else _BANDS)]
