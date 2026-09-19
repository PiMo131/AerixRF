"""T4 acceptance tests: sub-GHz dwell raster/NETID estimator + end-to-end
synthetic SiK/MAVLink pipeline (docs/design/sik-mavlink-passive-decode.md).

**Evidence level 1 (synthetic).** Every fixture here is built from this
project's own generator (:mod:`aerix_rf.decode.sik.synth`,
:func:`aerix_rf.decode.sik.frame.sik_encode_frame`, a local from-scratch
MAVLink v1 encoder). A pass demonstrates decoder self-consistency only, per
every module's own docstring in this package -- NOT real-SiK-radio decoding.

Timeline note: the design doc's TDM-window numbers (<=131 ms) describe real
SiK timing; to keep this test's IQ buffer small (tens of MB, not GB) the
inter-burst period used here is compressed to 8 ms (vs. a real link's tens of
ms). This does not affect what is being tested: the raster (frequency-only)
and NETID (hop *order* only) estimators are both independent of absolute
timing, and the GFSK/frame decode chain operates per burst regardless of the
gap between bursts.
"""

from __future__ import annotations

import struct
import time

import numpy as np
import pytest

from aerix_rf.decode.sik.frame import TdmTrailer, sik_encode_frame
from aerix_rf.decode.sik.pipeline import decode_sik_window
from aerix_rf.decode.sik.raster import (
    BAND_LIMITS_HZ,
    estimate_sik_raster,
    hop_map,
    netid_candidates_from_sequence,
)
from aerix_rf.decode.sik.synth import make_sik_burst

FS = 15.36e6
BAND = "sik915"
FREQ_MIN_HZ, FREQ_MAX_HZ, N_CHANNELS = BAND_LIMITS_HZ[BAND]
CENTRE_HZ = 921.5e6
SPACING_HZ = (FREQ_MAX_HZ - FREQ_MIN_HZ) / (N_CHANNELS + 2)  # 250 kHz exact (S1)
NETID = 25
RATE_BPS = 64000
PERIOD_S = 8e-3  # compressed TDM period, see module docstring
N_WINDOWS = 40
SNR_DB = 20.0  # in-band SNR (2*rate_bps reference BW), see _capture_noise_sigma

assert SPACING_HZ == pytest.approx(250e3)
assert N_CHANNELS == 50


def _capture_noise_sigma(snr_db: float, rate_bps: float, fs: float, amplitude: float = 1.0) -> float:
    """Per-component sigma of the *dwell-wide* receiver noise that puts a
    unit-amplitude burst at ``snr_db`` in-band SNR, referenced to a
    ``2*rate_bps`` noise bandwidth (the same SNR convention
    :func:`aerix_rf.decode.sik.synth.make_sik_burst` uses internally).

    The noise MUST be generated once for the whole window, not per burst.
    ``make_sik_burst(snr_db=...)`` adds AWGN across the full ``fs`` of the
    burst's own buffer, sized for a 2*rate_bps reference bandwidth: at
    fs = 15.36 MS/s and 64 kbps that is 15.36e6/1.28e5 = 21 dB more total
    noise power than the in-band figure, i.e. each embedded burst raised the
    noise floor of the *entire 15.36 MHz dwell* by ~24 dB for its own
    duration. With a 54% burst duty cycle that also made the per-bin median
    floor the burst-time floor, so the detector saw a band-wide 24 dB
    "signal" at every hop and hit its event cap on splatter. That is a
    fixture artefact, not receiver physics: one narrowband transmitter does
    not raise the whole band's floor. Bursts are therefore generated
    noiseless (``snr_db=None``) and embedded in one stationary AWGN dwell.
    """
    n0 = amplitude ** 2 / ((10.0 ** (snr_db / 10.0)) * 2.0 * rate_bps)
    return float(np.sqrt(n0 * fs / 2.0))


def _channel_freq_hz(physical_channel: int) -> float:
    # Base offset spacing/2 (S1); the NETID-seeded extra offset is a fixed
    # fraction here (not bit-exact to the firmware's own r_rand draw --
    # unmodelled per S2, and irrelevant to what's tested: spacing/N/NETID
    # recovery, never the absolute offset value).
    base = FREQ_MIN_HZ + SPACING_HZ / 2.0 + 0.15 * SPACING_HZ
    return base + physical_channel * SPACING_HZ


def _heartbeat_v1(seq: int, sysid: int = 7, compid: int = 1) -> bytes:
    """Minimal from-scratch MAVLink v1 HEARTBEAT encoder (CRC_EXTRA=50),
    independent of aerix_rf.decode.sik.mavlink's own CRC implementation --
    mirrors tests/test_sik_mavlink.py's local golden-vector encoder."""

    def _crc_accum(byte, crc):
        tmp = (byte ^ (crc & 0xFF)) & 0xFF
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        return ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF

    payload = struct.pack("<IBBBBB", 0, 2, 3, 81, 4, 3)  # custom_mode..mavlink_version
    body = bytes((len(payload), seq, sysid, compid, 0)) + payload
    crc = 0xFFFF
    for b in body:
        crc = _crc_accum(b, crc)
    crc = _crc_accum(50, crc)  # HEARTBEAT CRC_EXTRA
    return bytes((0xFE,)) + body + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def _embed(capture: np.ndarray, burst_iq: np.ndarray, start_idx: int, freq_offset_hz: float) -> None:
    n = min(len(burst_iq), len(capture) - start_idx)
    if n <= 0:
        return
    t = np.arange(n) / FS
    shifted = burst_iq[:n] * np.exp(1j * 2.0 * np.pi * freq_offset_hz * t)
    capture[start_idx:start_idx + n] += shifted.astype(np.complex64)


def _build_915_capture(seed: int = 20260919):
    rng = np.random.default_rng(seed)
    chans = hop_map(NETID, N_CHANNELS)
    n_samples = int(round(N_WINDOWS * PERIOD_S * FS))
    sigma = _capture_noise_sigma(SNR_DB, RATE_BPS, FS)
    capture = (sigma * (rng.standard_normal(n_samples) + 1j * rng.standard_normal(n_samples))).astype(np.complex64)

    physical_channels = []
    for w in range(N_WINDOWS):
        phys_ch = chans[w % N_CHANNELS]
        physical_channels.append(phys_ch)
        freq_hz = _channel_freq_hz(phys_ch)
        payload = _heartbeat_v1(seq=w)
        frame_bytes = sik_encode_frame(NETID, payload, ecc=False,
                                        trailer=TdmTrailer(window=w % 8192, command=False,
                                                            bonus=False, resend=False))
        burst = make_sik_burst(
            payload_bytes=frame_bytes, rate_bps=RATE_BPS, fs=FS,
            cfo_hz=float(rng.uniform(-2e3, 2e3)),
            snr_db=None,  # dwell-wide noise instead, see _capture_noise_sigma
            timing_offset_s=float(rng.uniform(-0.3, 0.3)) / RATE_BPS,
            seed=int(rng.integers(0, 2**31 - 1)),
        )
        start_idx = int(round(w * PERIOD_S * FS)) + int(rng.integers(0, 200))
        _embed(capture, burst.iq, start_idx, freq_hz - CENTRE_HZ)

    return capture, physical_channels


# ---------------------------------------------------------------------------
# raster.py unit tests
# ---------------------------------------------------------------------------

def test_estimate_sik_raster_915_spacing_and_n():
    freqs = [_channel_freq_hz(c) for c in hop_map(NETID, N_CHANNELS)]
    # simulate several revisits per channel over multiple cycles
    freqs = freqs * 3
    ev = estimate_sik_raster(freqs, BAND)
    assert not ev.insufficient
    assert ev.spacing_hz == pytest.approx(SPACING_HZ, abs=5e3)
    assert ev.consistent
    assert ev.n_channels == N_CHANNELS


def test_estimate_sik_raster_insufficient_on_too_few_bursts():
    ev = estimate_sik_raster([915.1e6, 915.6e6], BAND)
    assert ev.insufficient
    assert not ev.consistent


def test_netid_candidates_from_sequence_recovers_unique_netid():
    chans = hop_map(NETID, N_CHANNELS)
    observed = [chans[w % N_CHANNELS] for w in range(N_WINDOWS)]
    result = netid_candidates_from_sequence(observed, N_CHANNELS)
    assert result.unique
    assert result.candidates == [NETID]


def test_netid_candidates_wrong_map_length_no_false_unique():
    # A short, ambiguous observed sequence should not spuriously claim a
    # unique NETID; with only 2 hops many NETIDs can match by chance.
    result = netid_candidates_from_sequence([3, 17], N_CHANNELS, k=2)
    assert result.best_match_count >= 2
    assert len(result.candidates) >= 1  # not a strong claim either way


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

def test_pipeline_915_synthetic_end_to_end_level3_without_flag():
    capture, _phys = _build_915_capture()
    t0 = time.perf_counter()
    result = decode_sik_window(capture, FS, CENTRE_HZ, BAND, flag_third_party_mavlink=False)
    elapsed_s = time.perf_counter() - t0

    assert result["n_bursts"] >= 35
    raster_ev = result["raster"]
    assert raster_ev.spacing_hz == pytest.approx(SPACING_HZ, abs=5e3)
    assert raster_ev.consistent
    assert raster_ev.n_channels == N_CHANNELS
    assert result["labels"]["sik_like_hopper_candidate"] is True

    assert result["n_crc_valid_frames"] >= 35
    assert result["netid"] == NETID
    assert result["labels"]["sik_netid_confirmed"] is True
    assert result["evidence_level"] == 3
    assert result["labels"]["sik_mavlink_confirmed"] is False  # flag was off

    duration_s = len(capture) / FS
    budget_s = 0.5 * (duration_s / 1.0)  # scale the <500 ms/1 s-window budget
    assert elapsed_s < max(budget_s, 0.5), f"{elapsed_s:.3f}s for a {duration_s:.3f}s window"


def test_pipeline_915_synthetic_level4_with_flag():
    capture, _phys = _build_915_capture()
    result = decode_sik_window(capture, FS, CENTRE_HZ, BAND, flag_third_party_mavlink=True)

    assert result["netid"] == NETID
    assert result["evidence_level"] == 4
    assert result["labels"]["sik_mavlink_confirmed"] is True
    heartbeats = [m for m in result["mavlink_messages"]
                  if getattr(m, "msgid", None) == 0 and getattr(m, "crc_ok", False)]
    assert len(heartbeats) >= 30
    assert all(m.fields.get("type") == 2 for m in heartbeats)


def test_pipeline_ambient_negative_no_level2():
    rng = np.random.default_rng(4242)
    duration_s = 0.3
    n_samples = int(round(duration_s * FS))
    sigma = _capture_noise_sigma(SNR_DB, 64000, FS)
    capture = (sigma * (rng.standard_normal(n_samples) + 1j * rng.standard_normal(n_samples))).astype(np.complex64)

    for _ in range(15):
        freq_offset = float(rng.uniform(-5.5e6, 5.5e6))  # off any 250 kHz/25-multiple grid
        rate_bps = 64000
        payload = bytes(rng.integers(0, 256, size=20, dtype=np.uint8))
        netid = int(rng.integers(0, 65536))
        frame_bytes = sik_encode_frame(netid, payload, ecc=False)
        burst = make_sik_burst(payload_bytes=frame_bytes, rate_bps=rate_bps, fs=FS,
                                cfo_hz=float(rng.uniform(-2e3, 2e3)), snr_db=None,
                                seed=int(rng.integers(0, 2**31 - 1)))
        start_idx = int(rng.integers(0, max(1, n_samples - len(burst.iq))))
        _embed(capture, burst.iq, start_idx, freq_offset)

    result = decode_sik_window(capture, FS, CENTRE_HZ, BAND, flag_third_party_mavlink=True)
    assert result["evidence_level"] < 2
    assert result["labels"]["sik_like_hopper_candidate"] is False
    assert result["labels"]["sik_netid_confirmed"] is False
    assert result["labels"]["sik_mavlink_confirmed"] is False


def test_pipeline_noise_only_emits_nothing():
    rng = np.random.default_rng(99)
    n_samples = int(round(0.2 * FS))
    capture = (0.05 * (rng.standard_normal(n_samples) + 1j * rng.standard_normal(n_samples))).astype(np.complex64)
    result = decode_sik_window(capture, FS, CENTRE_HZ, BAND, flag_third_party_mavlink=True)
    assert result["n_bursts"] == 0
    assert result["evidence_level"] == 0
    assert all(v is False for v in result["labels"].values())
