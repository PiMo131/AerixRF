"""On-air parameters of the drone link families, as a machine-readable table.

Every row is what the research phase could establish about one waveform
family: where it lives, how wide its bursts are, how long they last, how
often they repeat, how far and how fast it hops, and whether an open
receiver can decode it or only see it.  ``antsdr_toolkit.classify.heuristic``
scores measured :class:`~antsdr_toolkit.dsp.features.BurstFeatures` against
these rows; nothing here is learned from data.

Reading a row
-------------
Ranges are inclusive ``(low, high)`` pairs in SI units (Hz, seconds) and are
deliberately wide: they describe what a *detector* should accept, not the
nominal specification.  ``None`` means the family does not constrain that
feature, and the classifier then ignores it instead of penalising it.

``confidence`` says how the numbers were obtained:

``verified``
    Read out of source code, a standard, or a measurement in a fetched
    document.
``snippet``
    Only a search-result snippet or a secondary source was reachable from
    the development sandbox; re-check before relying on it.
``inferred``
    Derived here from a verified number (for example a dwell time computed
    from a packet rate and a hop interval), or a deliberate detector
    tolerance around one.

``decodability`` is the honest state of open tooling, not of the protocol:

``decodable``
    An open implementation exists that recovers payload from IQ.
``detect_only``
    The waveform is recognisable but no open decoder exists (proprietary,
    undocumented, or the modulation is unimplemented in SDR frameworks).
``encrypted``
    The payload is encrypted; detection and fingerprinting are all that is
    available without keys.

Sources are the URLs the numbers came from; the full annotated bibliography
is ``antsdr/research/sources.md`` and the adversarial re-checks are in
``antsdr/research/verification-log.md``.

Caveats worth carrying into any conclusion drawn from this table
----------------------------------------------------------------
* Hop-set sizes and channel plans are regulatory-domain dependent.  The
  values here are the EU/global tables where the source gave one.
* Several families (Autel SkyLink, Skydio, Walksnail, HDZero) have no public
  physical-layer documentation at all; their rows are coarse and marked
  ``snippet`` or ``inferred``, and exist so the classifier can say "this
  looks like a wideband digital video link" rather than "unknown".
* Frontline-modified ExpressLRS forks tune far outside the ISM bands
  (360-560 MHz, 720-1020 MHz), so band membership must never be a veto.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

__all__ = [
    "DECODABILITY",
    "SIGNATURES",
    "Signature",
    "by_family",
    "families",
    "families_in_band",
    "signatures_for_band",
]

DECODABILITY = ("decodable", "detect_only", "encrypted")
CONFIDENCE = ("verified", "snippet", "inferred")

Range = tuple[float, float]


@dataclass(frozen=True)
class Signature:
    """One link family and the burst statistics that identify it."""

    family: str
    """Stable identifier, e.g. ``"elrs_2g4_lora_250hz"``."""
    display: str
    """Human-readable name for reports."""
    bands: tuple[str, ...]
    """Band ids from :mod:`antsdr_toolkit.scan.bands` where it is expected."""
    decodability: str
    notes: str
    sources: tuple[str, ...]
    confidence: str = "verified"

    bandwidth_hz: Range | None = None
    """Occupied bandwidth of one burst."""
    duration_s: Range | None = None
    """Length of one burst."""
    interval_s: Range | None = None
    """Time between consecutive burst starts on the same emitter."""
    duty_cycle: Range | None = None
    hop_rate_hz: Range | None = None
    """Centre-frequency changes per second (0 for a fixed-frequency link)."""
    n_distinct_centers: Range | None = None
    """Distinct centres expected in a window of a few tens of milliseconds."""
    center_spacing_hz: Range | None = None
    """Spacing of the channel grid, where the family has one."""
    channel_plan: tuple[float, ...] = ()
    """Exact channel centres in Hz, when the source published them."""
    weights: Mapping[str, float] = field(default_factory=dict)
    """Per-feature weight overrides; features absent here use 1.0."""

    def __post_init__(self) -> None:
        if self.decodability not in DECODABILITY:
            raise ValueError(f"{self.family}: decodability must be one of {DECODABILITY}")
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"{self.family}: confidence must be one of {CONFIDENCE}")
        if not self.sources:
            raise ValueError(f"{self.family}: every signature needs at least one source URL")
        for name in ("bandwidth_hz", "duration_s", "interval_s", "duty_cycle",
                     "hop_rate_hz", "n_distinct_centers", "center_spacing_hz"):
            rng = getattr(self, name)
            if rng is None:
                continue
            lo, hi = rng
            if not (lo <= hi):
                raise ValueError(f"{self.family}.{name}: low {lo} exceeds high {hi}")
            if lo < 0.0:
                raise ValueError(f"{self.family}.{name}: negative low bound {lo}")

    def constrained(self) -> dict[str, Range]:
        """The feature ranges this family actually constrains."""
        out: dict[str, Range] = {}
        for name in ("bandwidth_hz", "duration_s", "interval_s", "duty_cycle",
                     "hop_rate_hz", "n_distinct_centers", "center_spacing_hz"):
            rng = getattr(self, name)
            if rng is not None:
                out[name] = rng
        return out

    def weight(self, feature: str) -> float:
        return float(self.weights.get(feature, 1.0))

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "display": self.display,
            "bands": list(self.bands),
            "decodability": self.decodability,
            "confidence": self.confidence,
            "notes": self.notes,
            "sources": list(self.sources),
            "ranges": {k: list(v) for k, v in self.constrained().items()},
            "channel_plan_hz": list(self.channel_plan),
        }


# --------------------------------------------------------------------------- sources
_PROTO17 = "https://github.com/proto17/dji_droneid"
_DRONESEC = "https://github.com/RUB-SysSec/DroneSecurity"
_TMBINC = "https://github.com/tmbinc/random/tree/master/dji/ocusync2"
_ELRS = "https://github.com/ExpressLRS/ExpressLRS"
_MULTI = "https://github.com/pascallanger/DIY-Multiprotocol-TX-Module"
_CRSF = "https://github.com/g3gg0/ESP32_CRSFSniffer"
_SIK = "https://github.com/ArduPilot/SiK"
_FPVSDR = "https://github.com/lukeswitz/fpv-sdr"
_5G8ATV = "https://github.com/zubon2003/5G8atv-rf-hackrf-decoder"
_WFBNG = "https://github.com/svpcom/wfb-ng"
_OPENHD = "https://github.com/OpenHD/OpenHD"
_HDZERO = "https://github.com/hd-zero/hdzero-vtx/blob/main/src/dm6300.c"
_DRONERFA = "https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570"
_RFVISION = "https://github.com/ALPssdz/RF-Vision-UAV-Tracker"
_ANTSDR_DRONEID = "https://github.com/alphafox02/antsdr_dji_droneid"
_LUYII = "https://github.com/luyii-code-1/dji-ocusync-droneid-research"
_HERELINK = ("https://github.com/CubePilot/cubepilot-docs/blob/master/herelink/"
             "herelink-user-guides/wireless-communication.md")
_KISMET_UAV = "https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf"
_ODID = "https://github.com/opendroneid/opendroneid-core-c"

#: DroneID burst centres, union of the proto17 and DroneSecurity observations.
DRONEID_CENTRES_HZ: tuple[float, ...] = (
    2399.5e6, 2414.5e6, 2429.5e6, 2434.5e6, 2444.5e6, 2459.5e6, 2474.5e6,
    5721.5e6, 5731.5e6, 5741.5e6, 5756.5e6, 5761.5e6, 5771.5e6, 5786.5e6,
    5801.5e6, 5816.5e6, 5831.5e6,
)


def _elrs_lora_2g4(name: str, display: str, burst_s: float, interval_s: float,
                   dwell_s: float, note: str) -> Signature:
    """One ExpressLRS 2.4 GHz packet rate: 812.5 kHz LoRa on the 1 MHz grid."""
    return Signature(
        family=name, display=display, bands=("ism-2g4",), decodability="detect_only",
        confidence="verified",
        bandwidth_hz=(0.6e6, 1.1e6), duration_s=(0.6 * burst_s, 1.6 * burst_s),
        interval_s=(0.8 * interval_s, 1.25 * interval_s),
        hop_rate_hz=(0.5 / dwell_s, 2.0 / dwell_s),
        center_spacing_hz=(0.8e6, 1.2e6), n_distinct_centers=(2.0, 80.0),
        notes=(
            "SX1280 LoRa, bandwidth code 0x18 (812.5 kHz), SF5-SF8 with the long "
            "interleaver, implicit header, hardware CRC off, IQ inverted when UID[5] "
            "is odd. No open SDR decoder implements the SX1280 PHY, so this is "
            "detect-only. The hop table is 80 channels at 1 MHz from 2400.4 to "
            "2479.4 MHz, i.e. 79 MHz, wider than the E200's 56 MHz: a sweep sees a "
            "slice of the hop set, so n_distinct_centers is a lower bound. " + note
        ),
        sources=(_ELRS, "https://github.com/Diamond-D0gs/GNU_Radio_ExpressLRS"),
        weights={"center_spacing_hz": 0.7, "n_distinct_centers": 0.5},
    )


def _elrs_lora_900(name: str, display: str, burst_s: float, interval_s: float,
                   dwell_s: float) -> Signature:
    """One ExpressLRS sub-GHz packet rate: 500 kHz SX127x LoRa."""
    return Signature(
        family=name, display=display, bands=("eu868", "us915"), decodability="decodable",
        confidence="verified",
        bandwidth_hz=(0.35e6, 0.7e6), duration_s=(0.6 * burst_s, 1.6 * burst_s),
        interval_s=(0.8 * interval_s, 1.25 * interval_s),
        hop_rate_hz=(0.5 / dwell_s, 2.0 / dwell_s),
        center_spacing_hz=(0.4e6, 0.8e6), n_distinct_centers=(2.0, 40.0),
        notes=(
            "SX127x-format LoRa: 500 kHz, SF6-SF9, CR 4/7-4/8, sync word 0x12, "
            "implicit header, CRC off. gr-lora_sdr demodulates this family, and the "
            "ExpressLRS OTA layer is unencrypted (CRC14 poly 0x2E57 seeded from the "
            "UID carried in the clear by sync packets), so payload recovery is "
            "plausible - but no public project has demonstrated it end to end, so "
            "treat 'decodable' as a candidate, not a capability (verified: "
            "elrs-decodability). EU868 is 13 channels at 525 kHz (863.275-869.575 "
            "MHz), FCC915 is 40 at 600 kHz (903.5-926.9 MHz)."
        ),
        sources=(_ELRS, "https://github.com/tapparelj/gr-lora_sdr"),
        weights={"center_spacing_hz": 0.7, "n_distinct_centers": 0.5},
    )


SIGNATURES: tuple[Signature, ...] = (
    # ----------------------------------------------------------------- DJI
    Signature(
        family="dji_droneid",
        display="DJI DroneID burst (OcuSync 2/3)",
        bands=("dji-2g4", "dji-5g8", "ism-2g4", "ism-5g8"),
        decodability="decodable",
        bandwidth_hz=(7.5e6, 11e6), duration_s=(0.55e-3, 0.70e-3),
        interval_s=(0.45, 0.8), duty_cycle=(0.0, 0.01),
        n_distinct_centers=(1.0, 2.0),
        channel_plan=DRONEID_CENTRES_HZ,
        notes=(
            "LTE-like OFDM: 15 kHz subcarriers, 600 data carriers plus a null DC "
            "(9 MHz occupied, 15.36 MHz with guards), 9 symbols (8 on Mavic Pro and "
            "Mavic 2) with cyclic prefixes 80/72 at 15.36 MSPS, Zadoff-Chu pilots "
            "with roots 600 and 147 on symbols 4 and 6, QPSK data. A burst is "
            "643.2 us and repeats about every 600 ms, which is why the duty cycle is "
            "near zero. Decodable in the clear on OcuSync 2 and 3; the O4 generation "
            "encrypts the payload (verified: dji-generation-coverage). Whether a drone "
            "transmits before its motors spin is contested and model-dependent."
        ),
        sources=(_PROTO17, _DRONESEC, _ANTSDR_DRONEID),
        weights={"interval_s": 1.5, "duration_s": 1.5, "n_distinct_centers": 0.5},
    ),
    Signature(
        family="dji_ocusync2_video",
        display="DJI OcuSync 2 video downlink",
        bands=("dji-2g4", "dji-5g8", "ism-2g4", "ism-5g8"),
        decodability="encrypted",
        bandwidth_hz=(8e6, 22e6), duration_s=(0.5e-3, 1.5e-3),
        interval_s=(0.8e-3, 6e-3), duty_cycle=(0.15, 1.0),
        n_distinct_centers=(1.0, 3.0),
        notes=(
            "LTE numerology at 15 kHz subcarrier spacing: FFT 2048 in the 20 MHz "
            "mode with 1201 active carriers (about 18 MHz occupied), FFT 1024 in the "
            "10 MHz mode, cyclic prefix 144/72, roughly 1 ms frames with Zadoff-Chu "
            "reference symbols; 3 and 1.4 MHz modes also exist. DroneSecurity's "
            "packetizer gates video bursts at 630-665 us and 18-22 MHz. A "
            "cyclic-prefix autocorrelation separates this from Wi-Fi, whose "
            "subcarrier spacing is 312.5 kHz."
        ),
        sources=(_TMBINC, _DRONESEC, _RFVISION),
        weights={"duty_cycle": 0.7},
    ),
    Signature(
        family="dji_ocusync_c2",
        display="DJI OcuSync control uplink (C2)",
        bands=("dji-2g4", "ism-2g4", "ism-5g8"),
        decodability="encrypted",
        bandwidth_hz=(1.2e6, 2.4e6), duration_s=(0.4e-3, 0.6e-3),
        interval_s=(1e-3, 20e-3), hop_rate_hz=(20.0, 2000.0),
        n_distinct_centers=(2.0, 40.0),
        notes=(
            "The controller-to-aircraft link: 73 carriers (1.92 MHz) over 7 symbols, "
            "500-520 us per burst, frequency hopping. DroneRFa's per-model table "
            "measures OcuSync-era hop blocks at 1.1-2.2 MHz with a 0.52 ms dwell, "
            "which is the same object seen with a different instrument."
        ),
        sources=(_DRONESEC, _TMBINC, _DRONERFA),
        confidence="verified",
        weights={"n_distinct_centers": 0.6},
    ),
    Signature(
        family="dji_o4_airlink",
        display="DJI O4 / O4+ air link (encrypted)",
        bands=("dji-2g4", "dji-5g8", "ism-2g4", "ism-5g8", "wifi-5"),
        decodability="encrypted",
        bandwidth_hz=(7e6, 12e6), duration_s=(0.4e-3, 0.7e-3),
        interval_s=(4e-3, 6e-3),
        notes=(
            "Air 3 and later (Mini 4 Pro, Avata 2, Neo, Mini 5 Pro, Mavic 4). A 2026 "
            "measurement of a Mini 5 Pro puts the main link at about 8.92 MHz 99 % "
            "bandwidth with 5 ms periodicity; the DroneID burst still demodulates to "
            "a clean QPSK constellation but its payload is encrypted, so an open "
            "receiver gets a per-session hash, the frequency and RSSI. The O4 ground "
            "station also uses sub-2 GHz, 2.4, 5.2 and 5.8 GHz with automatic "
            "switching, so the 5.2 GHz DFS block belongs in the scan plan. The 5 ms "
            "periodicity alone does not separate video from control from DroneID."
        ),
        sources=(_LUYII, _ANTSDR_DRONEID, "https://www.ithome.com/0/965/621.htm"),
        confidence="snippet",
    ),
    Signature(
        family="dji_lightbridge2",
        display="DJI Lightbridge 2 downlink",
        bands=("ism-2g4",),
        decodability="encrypted",
        bandwidth_hz=(8e6, 12e6), duration_s=(8e-3, 20e-3),
        interval_s=(10e-3, 18e-3), duty_cycle=(0.5, 0.85),
        notes=(
            "About 10 MHz of OFDM on a 32-channel plan (2285-2595 MHz by design, "
            "2400-2483 MHz in stock firmware), paired with a 1-2 MHz hopping control "
            "uplink. DroneRFa measures the Lightbridge-era models (Phantom 4 Pro, "
            "M200, M100, Inspire 2, M600 Pro) at a 1.2 MHz hop block with a 2.2 ms "
            "dwell, 12 ms between neighbouring hops, and a 14 ms video frame at 68 % "
            "duty - the numbers used here."
        ),
        sources=(_DRONERFA, "https://phantompilots.com/threads/phantom-3-lightbridge-frequencies.51693/"),
        confidence="snippet",
    ),
    Signature(
        family="dji_wifi_drone",
        display="DJI Wi-Fi drone (Spark, Mavic Air, Tello)",
        bands=("ism-2g4", "wifi-5", "ism-5g8"),
        decodability="decodable",
        bandwidth_hz=(16e6, 45e6), duration_s=(20e-6, 5e-3), duty_cycle=(0.05, 1.0),
        notes=(
            "Plain 802.11: the beacons are in the clear and carry both the SSID/OUI "
            "fingerprint Kismet matches (DJI 60:60:1F, SSID ^TELLO.*) and, on older "
            "models, DJI's proprietary DroneID vendor IE (OUI 26:37:12, subcommands "
            "0x10 telemetry and 0x11 purpose, one beacon every 200 ms). The video "
            "and control payload is WPA2-encrypted; Tello is the exception because "
            "its access point is open."
        ),
        sources=(_KISMET_UAV, "https://github.com/kismetwireless/kismet"),
    ),
    # -------------------------------------------------------- RC control links
    _elrs_lora_2g4("elrs_2g4_lora_500hz", "ExpressLRS 2.4 GHz LoRa 500 Hz",
                   1.51e-3, 2e-3, 8e-3, "500 Hz: hops every 4 packets."),
    _elrs_lora_2g4("elrs_2g4_lora_250hz", "ExpressLRS 2.4 GHz LoRa 250 Hz",
                   3.3e-3, 4e-3, 16e-3, "250 Hz: hops every 4 packets."),
    _elrs_lora_2g4("elrs_2g4_lora_150hz", "ExpressLRS 2.4 GHz LoRa 150 Hz",
                   5.87e-3, 6.67e-3, 26.7e-3, "150 Hz: hops every 4 packets."),
    _elrs_lora_2g4("elrs_2g4_lora_50hz", "ExpressLRS 2.4 GHz LoRa 50 Hz",
                   10.8e-3, 20e-3, 40e-3, "50 Hz: hops every 2 packets."),
    Signature(
        family="elrs_2g4_flrc",
        display="ExpressLRS 2.4 GHz FLRC (F500/F1000, D250/D500)",
        bands=("ism-2g4",), decodability="detect_only",
        bandwidth_hz=(0.4e6, 0.9e6), duration_s=(0.2e-3, 0.6e-3),
        interval_s=(0.8e-3, 2.5e-3), hop_rate_hz=(250.0, 1200.0),
        center_spacing_hz=(0.8e6, 1.2e6), n_distinct_centers=(2.0, 80.0),
        notes=(
            "Semtech FLRC at 0.65 Mb/s in 0.6 MHz with a UID-derived 32-bit sync "
            "word and CRC seed: 0.39 ms bursts every 1 ms at F1000, hopping every 2 "
            "packets. No open SDR demodulator implements FLRC, so this is the "
            "shortest and fastest thing on the 1 MHz ExpressLRS grid and nothing "
            "more can be said about it."
        ),
        sources=(_ELRS,),
        weights={"center_spacing_hz": 0.7, "n_distinct_centers": 0.5},
    ),
    _elrs_lora_900("elrs_900_lora_200hz", "ExpressLRS 868/915 MHz LoRa 200 Hz",
                   4.38e-3, 5e-3, 20e-3),
    _elrs_lora_900("elrs_900_lora_100hz", "ExpressLRS 868/915 MHz LoRa 100 Hz",
                   8.77e-3, 10e-3, 40e-3),
    _elrs_lora_900("elrs_900_lora_50hz", "ExpressLRS 868/915 MHz LoRa 50 Hz",
                   18.6e-3, 20e-3, 80e-3),
    Signature(
        family="crossfire_150hz",
        display="TBS Crossfire 150 Hz (FSK)",
        bands=("eu868", "us915"), decodability="decodable",
        bandwidth_hz=(0.15e6, 0.45e6), duration_s=(0.3e-3, 3e-3),
        interval_s=(5e-3, 8e-3), hop_rate_hz=(50.0, 300.0),
        center_spacing_hz=(0.2e6, 0.32e6), n_distinct_centers=(2.0, 50.0),
        notes=(
            "Plain FSK at 85 kBaud with 42.3 kHz deviation on a 260 kHz channel "
            "grid from 860 MHz (EU) or 900 MHz (US), a 150-slot hop sequence and a "
            "6.667 ms slot carrying a 23-byte uplink and a 13-byte downlink. "
            "Unencrypted, so decodable in principle; the 50 Hz mode is LoRa instead. "
            "The primary write-up (g3gg0.de) was unreachable from the sandbox, so "
            "the per-mode parameters come from the sniffer source."
        ),
        sources=(_CRSF, "https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire/"),
        confidence="snippet",
    ),
    Signature(
        family="frsky_d8_d16",
        display="FrSky ACCST D8/D16",
        bands=("ism-2g4",), decodability="detect_only",
        bandwidth_hz=(0.15e6, 1.2e6), duration_s=(0.1e-3, 3e-3),
        interval_s=(8e-3, 10e-3), hop_rate_hz=(80.0, 130.0),
        n_distinct_centers=(2.0, 47.0),
        notes=(
            "CC2500-based FHSS: 9 ms frame over a 47-channel hop set. D8 is 31 kbps "
            "2-FSK, D16 is 70-77 kbps (100 kbps under EU listen-before-talk). Fully "
            "specified in the Multiprotocol firmware but with no SDR decoder, and "
            "the newer ACCESS protocol is proprietary."
        ),
        sources=(_MULTI,),
        weights={"n_distinct_centers": 0.6},
    ),
    Signature(
        family="flysky_afhds2a",
        display="Flysky AFHDS-2A",
        bands=("ism-2g4",), decodability="detect_only",
        bandwidth_hz=(0.3e6, 0.9e6), duration_s=(0.1e-3, 1.5e-3),
        interval_s=(3.4e-3, 4.3e-3), hop_rate_hz=(230.0, 300.0),
        center_spacing_hz=(0.4e6, 0.6e6), n_distinct_centers=(2.0, 16.0),
        notes=(
            "A7105-based: 500 kbps over 16 channels drawn from a 160-entry 500 kHz "
            "grid, 3.85 ms frame. The older AFHDS uses a 1.51 ms frame."
        ),
        sources=(_MULTI,),
    ),
    Signature(
        family="futaba_sfhss",
        display="Futaba S-FHSS",
        bands=("ism-2g4",), decodability="detect_only",
        bandwidth_hz=(0.3e6, 1.5e6), duration_s=(0.1e-3, 2.5e-3),
        interval_s=(6.2e-3, 7.5e-3), hop_rate_hz=(130.0, 165.0),
        center_spacing_hz=(1.3e6, 1.7e6), n_distinct_centers=(2.0, 30.0),
        notes="128 kbps over a 30-channel hop set on a 1.5 MHz grid, 6.8 ms frame.",
        sources=(_MULTI,),
    ),
    Signature(
        family="graupner_hott",
        display="Graupner HoTT",
        bands=("ism-2g4",), decodability="detect_only",
        bandwidth_hz=(0.3e6, 1.2e6), duration_s=(0.1e-3, 3e-3),
        interval_s=(9e-3, 11e-3), hop_rate_hz=(85.0, 115.0),
        n_distinct_centers=(2.0, 75.0),
        notes="250 kbps MSK with forward error correction over 75 channels, 10 ms frame.",
        sources=(_MULTI,),
    ),
    Signature(
        family="spektrum_dsmx",
        display="Spektrum DSM2/DSMX",
        bands=("ism-2g4",), decodability="decodable",
        bandwidth_hz=(0.8e6, 2.5e6), duration_s=(0.1e-3, 1.5e-3),
        interval_s=(10e-3, 23e-3), hop_rate_hz=(40.0, 110.0),
        n_distinct_centers=(2.0, 23.0),
        notes=(
            "CYRF6936 direct-sequence spread spectrum at 1 Mb/s GFSK on a 23-channel "
            "table, 11 ms (DSMX) or 22 ms (DSM2) frames. gr-dsmx-rc demodulates it, "
            "including the transmitter's manufacturer ID, but the code targets GNU "
            "Radio 3.7 and needs a port."
        ),
        sources=(_MULTI, "https://github.com/lscardoso/gr-dsmx-rc"),
    ),
    Signature(
        family="sik_telemetry",
        display="SiK / RFD telemetry radio (MAVLink)",
        bands=("eu868", "us915", "ism-433"), decodability="decodable",
        bandwidth_hz=(0.05e6, 0.5e6), duration_s=(0.5e-3, 30e-3),
        interval_s=(5e-3, 100e-3), hop_rate_hz=(5.0, 200.0),
        n_distinct_centers=(2.0, 50.0),
        notes=(
            "GFSK at 2-250 kb/s (64 kb/s by default) in a time-division scheme that "
            "changes frequency at the start and end of every transmit window, "
            "hopping over 10 channels at 433/868 MHz or 50 at 915 MHz with a "
            "NetID-seeded order. The MAVLink payload is plaintext unless AES is "
            "enabled, so aircraft telemetry (including position) is readable."
        ),
        sources=(_SIK, "https://github.com/nicholasaleks/sikw00f"),
    ),
    # ------------------------------------------------------------- video links
    Signature(
        family="analog_fpv_video",
        display="Analog FPV video (FM)",
        bands=("fpv-5g8-wide", "ism-5g8", "fpv-l-band", "fpv-1g2"),
        decodability="decodable",
        bandwidth_hz=(6e6, 20e6), duration_s=(20e-3, 3600.0),
        duty_cycle=(0.9, 1.0), hop_rate_hz=(0.0, 1.0),
        n_distinct_centers=(1.0, 1.0),
        notes=(
            "Wideband FM of composite video: a continuous noise-like hump with no "
            "discrete carrier, and on RTC6705-class transmitters two weak FM audio "
            "subcarriers 6.0 and 6.5 MHz out, 25-30 dB down. The occupied bandwidth "
            "is neither the 19-20 MHz channel spacing nor the 23-27 MHz Carson "
            "estimate quoted in communities: one measurement of a 25 mW transmitter "
            "kept more than 99 % of the energy within +/-4.5 MHz, and 10 MSPS "
            "decodes NTSC colour, though 20 MSPS is the safer capture rate "
            "(verified: analog-fpv-bandwidth). The distinguishing measurement is the "
            "envelope: constant-modulus FM reads a coefficient of variation of "
            "0.3-0.56 against 1.2-3.2 for Wi-Fi and other OFDM."
        ),
        sources=(_FPVSDR, _5G8ATV),
        weights={"duty_cycle": 1.5, "duration_s": 0.7},
    ),
    Signature(
        family="hdzero_video",
        display="HDZero digital video",
        bands=("fpv-5g8-wide", "ism-5g8", "fpv-l-band"),
        decodability="detect_only",
        bandwidth_hz=(20e6, 30e6), duty_cycle=(0.8, 1.0),
        hop_rate_hz=(0.0, 1.0), n_distinct_centers=(1.0, 1.0),
        notes=(
            "A Divimath DM5680 baseband driving a DM6300 radio, about 27 MHz wide on "
            "the fixed channels R1-R8, E1, F1/F2/F4 and L1-L8. The modulation is "
            "OFDM but undocumented, so it is recognisable by width and by sitting "
            "still on a known channel, and nothing more."
        ),
        sources=(_HDZERO, "https://www.getfpv.com/fpv/hd-fpv/hdzero-digital-hd-fpv-system.html"),
        confidence="snippet",
    ),
    Signature(
        family="wifi_broadcast_fpv",
        display="Wi-Fi broadcast FPV (wfb-ng, OpenHD, OpenIPC)",
        bands=("ism-5g8", "wifi-5", "ism-2g4"),
        decodability="detect_only",
        bandwidth_hz=(16e6, 45e6), duty_cycle=(0.3, 1.0),
        hop_rate_hz=(0.0, 1.0), n_distinct_centers=(1.0, 2.0),
        notes=(
            "Injected 802.11 data frames rather than an association: wfb-ng uses "
            "frame control 0x08 0x01 with the broadcast receiver address and a "
            "transmitter address starting 57:42, HT MCS1 in 20 MHz on channel 165 "
            "(5825 MHz) by default; OpenHD uses its own 13:22:33:44:55 prefix and a "
            "channel list that includes non-standard 2312-2712 and 5080-6085 MHz "
            "entries. Every payload is ChaCha20-Poly1305 encrypted, so links are "
            "attributable by MAC prefix in monitor mode but never decodable "
            "passively. Note that gr-ieee802-11 decodes only legacy 802.11a/g/p, "
            "not the HT frames these stacks inject by default."
        ),
        sources=(_WFBNG, _OPENHD, "https://github.com/bastibl/gr-ieee802-11"),
    ),
    Signature(
        family="wifi_generic",
        display="Wi-Fi (802.11), not drone-specific",
        bands=("ism-2g4", "wifi-5", "ism-5g8"),
        decodability="detect_only",
        bandwidth_hz=(16e6, 45e6), duration_s=(20e-6, 5e-3),
        hop_rate_hz=(0.0, 2.0), n_distinct_centers=(1.0, 3.0),
        notes=(
            "The dominant false alarm in both ISM bands. Its 312.5 kHz subcarrier "
            "spacing gives a cyclic-prefix autocorrelation peak near 250 kHz, far "
            "from the 10.5-14.5 kHz and 22-30 kHz peaks of OcuSync numerologies, "
            "which is the cheapest way to reject it. Remote ID also rides on Wi-Fi "
            "beacons, so a Wi-Fi classification is not by itself uninteresting."
        ),
        sources=(_RFVISION, _ODID),
        weights={"bandwidth_hz": 0.8},
    ),
    Signature(
        family="herelink",
        display="Herelink ground link",
        bands=("ism-2g4",), decodability="encrypted",
        bandwidth_hz=(8e6, 22e6), duty_cycle=(0.2, 1.0),
        n_distinct_centers=(1.0, 3.0),
        notes=(
            "An LTE-numerology link confined to 2409-2459 MHz (10 MHz mode) or "
            "2412-2462 MHz (20 MHz mode). It looks like OcuSync to a width-only "
            "classifier; separating the two needs the channel plan or the cyclic "
            "prefix structure, and no source documents Herelink's."
        ),
        sources=(_HERELINK,),
        confidence="snippet",
    ),
)


def _validate() -> None:
    seen: set[str] = set()
    for sig in SIGNATURES:
        if sig.family in seen:
            raise ValueError(f"duplicate signature family {sig.family!r}")
        seen.add(sig.family)


_validate()

_BY_FAMILY: Mapping[str, Signature] = MappingProxyType({s.family: s for s in SIGNATURES})


def families() -> tuple[str, ...]:
    """Every known family id, in table order."""
    return tuple(_BY_FAMILY)


def by_family(family: str) -> Signature:
    """Look one signature up by id; ``KeyError`` when unknown."""
    return _BY_FAMILY[family]


def signatures_for_band(band: str | None) -> Iterator[Signature]:
    """Signatures expected in ``band`` (all of them when ``band`` is ``None``)."""
    for sig in SIGNATURES:
        if band is None or band in sig.bands:
            yield sig


def families_in_band(band: str | None) -> tuple[str, ...]:
    """Family ids expected in ``band``."""
    return tuple(s.family for s in signatures_for_band(band))


def as_table(rows: Sequence[Signature] = SIGNATURES) -> list[dict[str, object]]:
    """The table as plain dictionaries, for JSON output or a report."""
    return [s.to_dict() for s in rows]
