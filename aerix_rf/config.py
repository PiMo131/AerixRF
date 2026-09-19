"""Box configuration: SDR, framing, detection thresholds, upload modes, identity.

Loaded from environment variables (AERIX_RF_*) with sane defaults so the box runs
in --sim mode out of the box. Real deployments set server_url/token/position.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _envf(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v not in (None, "") else default


def _envi(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else default


def _envb(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v in (None, ""):
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _envs(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class Config:
    # --- SDR front end ---
    sample_rate: float = 20e6          # HackRF Pro max; >= 15.36e6 needed for DroneID.
                                        # Fixed-profile backends (antsdr_iio) ignore this
                                        # unless sample_rate_requested is True -- see below.
    sample_rate_requested: bool = False  # True once --sample-rate / $AERIX_RF_SAMPLE_RATE was
                                        # explicitly set (vs. this dataclass's own default),
                                        # so a backend with a fixed rate profile (antsdr_iio)
                                        # can tell "apply this rate" from "use your own default".
    center_freq_mhz: float = 2440.0    # a DJI OcuSync 2.4 GHz centre; sweep later
    gain_db: float = 40.0              # SoapySDR overall gain (soapy source only); also the
                                        # generic --gain-db for antsdr_iio's manual RX gain.
    gain_mode: str = "manual"          # generic RX gain mode: manual | agc_slow | agc_fast
                                        # (antsdr_iio only; HackRF backends ignore this).
    lna_gain: int = 16                 # hackrf_transfer LNA gain, 0-40 step 8
    vga_gain: int = 24                 # hackrf_transfer VGA gain, 0-62 step 2
    amp: bool = False                  # front-end amp (+14 dB); off for strong nearby signals
    antsdr_uri: str = ""               # ANTSDR libiio network URI (antsdr_iio only);
                                        # "" = backend default (ip:192.168.1.10)
    antsdr_profile: str = ""           # antsdr_iio named profile: default | antsdr_13p44 |
                                        # antsdr_11p52; "" = backend default ("default")
    band: str = "2.4GHz"
    iq_file: str = ""                  # replay a captured .cs8 (int8) or .cs16 (int16, e.g.
                                        # ANTSDR) IQ file instead of live SDR; format/full-scale
                                        # come from session metadata, see sdr/capture.py FileIQSource

    # --- framing / spectrogram ---
    window_s: float = 1.0              # one detection frame per second
    fft_size: int = 1024

    # --- detection thresholds ---
    score_threshold: float = 0.60      # a "plausible detection"
    snr_threshold_db: float = 8.0
    occupied_bw_ref_mhz: float = 10.0  # a DroneID/OcuSync burst is ~10 MHz wide

    # --- upload modes (independent flags; see plan) ---
    mode1_png_on_detection: bool = True    # PNG only when score > threshold
    mode2_png_every_second: bool = False   # PNG every second regardless
    mode3_iq_on_request: bool = True       # serve retained IQ on request
    mode4_retain_iq: bool = True           # keep plausible-detection IQ locally
    iq_retention_s: int = 24 * 3600        # >= 24 h, then auto-purge (GDPR)

    # --- identity / server uplink ---
    server_url: str = ""               # e.g. https://host:8180 ; empty = no uplink
    sensor_id: str = ""
    token: str = ""                    # "<sensor_id>~<secret>"
    site_id: str = ""
    lat: float | None = None           # HackRF sensor position
    lon: float | None = None
    odid_cue_poll_s: float = 1.0       # Path 1a poll cadence

    # --- local cue + control API (Path 1b) ---
    local_bind: str = "0.0.0.0"
    local_port: int = 8770
    local_token: str = ""              # shared secret for the LAN API
    mdns_name: str = "aerix-rf"

    # --- decode gates ---
    decode_third_party_mavlink: bool = False  # default OFF: gates
                                        # aerix_rf.decode.sik.mavlink parsing of
                                        # third-party MAVLink fields recovered
                                        # from SiK links (docs/design/
                                        # sik-mavlink-passive-decode.md S3).
                                        # Decoded positions/sysid are personal
                                        # data (retention_class="personal_7d").
                                        # env AERIX_RF_DECODE_THIRD_PARTY_MAVLINK

    # --- runtime ---
    sim: bool = False                  # use the synthetic IQ source (no hardware)

    @classmethod
    def from_env(cls) -> "Config":
        lat = os.environ.get("AERIX_RF_LAT")
        lon = os.environ.get("AERIX_RF_LON")
        sr_env = os.environ.get("AERIX_RF_SAMPLE_RATE")
        return cls(
            sample_rate=_envf("AERIX_RF_SAMPLE_RATE", cls.sample_rate),
            sample_rate_requested=sr_env not in (None, ""),
            center_freq_mhz=_envf("AERIX_RF_CENTER_MHZ", cls.center_freq_mhz),
            gain_db=_envf("AERIX_RF_GAIN_DB", cls.gain_db),
            gain_mode=_envs("AERIX_RF_ANTSDR_GAIN_MODE", cls.gain_mode),
            antsdr_uri=_envs("AERIX_RF_ANTSDR_URI", cls.antsdr_uri),
            antsdr_profile=_envs("AERIX_RF_ANTSDR_PROFILE", cls.antsdr_profile),
            band=_envs("AERIX_RF_BAND", cls.band),
            fft_size=_envi("AERIX_RF_FFT", cls.fft_size),
            score_threshold=_envf("AERIX_RF_SCORE_THRESHOLD", cls.score_threshold),
            snr_threshold_db=_envf("AERIX_RF_SNR_THRESHOLD_DB", cls.snr_threshold_db),
            mode1_png_on_detection=_envb("AERIX_RF_MODE1", cls.mode1_png_on_detection),
            mode2_png_every_second=_envb("AERIX_RF_MODE2", cls.mode2_png_every_second),
            mode3_iq_on_request=_envb("AERIX_RF_MODE3", cls.mode3_iq_on_request),
            mode4_retain_iq=_envb("AERIX_RF_MODE4", cls.mode4_retain_iq),
            iq_retention_s=_envi("AERIX_RF_IQ_RETENTION_S", cls.iq_retention_s),
            server_url=_envs("AERIX_RF_SERVER_URL", cls.server_url),
            sensor_id=_envs("AERIX_RF_SENSOR_ID", cls.sensor_id),
            token=_envs("AERIX_RF_TOKEN", cls.token),
            site_id=_envs("AERIX_RF_SITE_ID", cls.site_id),
            lat=float(lat) if lat not in (None, "") else None,
            lon=float(lon) if lon not in (None, "") else None,
            local_bind=_envs("AERIX_RF_LOCAL_BIND", cls.local_bind),
            local_port=_envi("AERIX_RF_LOCAL_PORT", cls.local_port),
            local_token=_envs("AERIX_RF_LOCAL_TOKEN", cls.local_token),
            mdns_name=_envs("AERIX_RF_MDNS_NAME", cls.mdns_name),
            decode_third_party_mavlink=_envb(
                "AERIX_RF_DECODE_THIRD_PARTY_MAVLINK", cls.decode_third_party_mavlink
            ),
            sim=_envb("AERIX_RF_SIM", cls.sim),
        )
