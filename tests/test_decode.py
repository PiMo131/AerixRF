"""Tests for stage-3 DJI DroneID decode front end (ZC sync + OFDM demod).

Validated against synthetic spec-accurate bursts from aerix_rf.decode._synth.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerix_rf.decode import ofdm
from aerix_rf.decode import turbo as T
from aerix_rf.decode import frame as F
from aerix_rf.decode._synth import make_burst, make_encoded_burst
from aerix_rf.decode.droneid import (
    decode, available, demodulate, generate_scrambler_seq, descramble_payload,
)
from aerix_rf.decode.zc import zc_time_domain, find_zc_symbol_start, normalized_xcorr


# ---------------------------------------------------------------------------
# Parameter / primitive sanity
# ---------------------------------------------------------------------------

def test_ofdm_parameters_1536():
    fs = ofdm.NOMINAL_SAMPLE_RATE
    assert ofdm.fft_size_for(fs) == 1024
    assert ofdm.cyclic_prefix_lengths(fs) == (80, 72)
    assert ofdm.cp_schedule(fs) == [80, 72, 72, 72, 72, 72, 72, 72, 80]
    assert ofdm.burst_length(fs) == 9 * 1024 + 2 * 80 + 7 * 72 == 9880
    dci = ofdm.data_carrier_indices(1024)
    assert dci.size == 600
    assert 512 not in dci                      # DC excluded
    assert dci.min() == 212 and dci.max() == 812


def test_available_is_true():
    assert available() is True


def test_zc_autocorrelation_peak():
    # A ZC symbol correlated against itself peaks sharply at lag 0.
    taps = zc_time_domain(1024, 4)
    padded = np.concatenate([np.zeros(1024, dtype=complex), taps, np.zeros(1024, dtype=complex)])
    scores = normalized_xcorr(padded, taps)
    peak = int(np.argmax(scores))
    assert scores[peak] > 0.99
    assert peak == 1024                        # start of the taps within the pad


# ---------------------------------------------------------------------------
# Time synchronization
# ---------------------------------------------------------------------------

def test_zc_sync_finds_symbol4_start_clean():
    b = make_burst(snr_db=None, pad_start=500, seed=1)
    fft_size = ofdm.fft_size_for(b.sample_rate)
    peak, score = find_zc_symbol_start(b.iq.astype(complex), fft_size, symbol_index=4)
    schedule = ofdm.cp_schedule(b.sample_rate)
    expected = b.burst_start + sum(schedule[:4]) + fft_size * 3
    assert score > 0.9
    assert abs(peak - expected) <= 1


def test_sto_cp_recovers_exact_burst_start():
    b = make_burst(snr_db=None, pad_start=500, seed=2)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    assert abs(d.sync_offset - b.burst_start) <= 1


def test_sto_cp_burst_start_with_noise():
    b = make_burst(snr_db=15.0, pad_start=500, seed=3)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    assert abs(d.sync_offset - b.burst_start) <= 2


# ---------------------------------------------------------------------------
# Frequency synchronization
# ---------------------------------------------------------------------------

def test_cfo_estimate_clean():
    inject = 3000.0
    b = make_burst(snr_db=None, cfo_hz=inject, seed=4)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    assert abs(d.cfo_hz - inject) < 100.0


def test_cfo_estimate_with_noise():
    inject = -2500.0
    b = make_burst(snr_db=15.0, cfo_hz=inject, seed=5)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    assert abs(d.cfo_hz - inject) < 400.0


# ---------------------------------------------------------------------------
# End-to-end OFDM demod: recover injected QPSK bits on data symbols
# ---------------------------------------------------------------------------

_DATA_ROWS = [s - 1 for s in ofdm.DATA_SYMBOLS_1B]      # [1,2,4,6,7,8]


def test_demod_recovers_qpsk_bits_clean():
    b = make_burst(snr_db=None, seed=6)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    for row in _DATA_ROWS:
        assert np.array_equal(d.qpsk_bits[row], b.payload_bits[row]), f"symbol {row}"


def test_demod_recovers_qpsk_bits_15db():
    b = make_burst(snr_db=15.0, seed=7)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    total = 0
    errors = 0
    for row in _DATA_ROWS:
        total += b.payload_bits[row].size
        errors += int(np.count_nonzero(d.qpsk_bits[row] != b.payload_bits[row]))
    ber = errors / total
    assert ber < 1e-3, f"BER too high: {ber}"


# ---------------------------------------------------------------------------
# Descramble round-trip (scrambled synth -> descrambled == injected payload)
# ---------------------------------------------------------------------------

def test_scrambler_is_deterministic_and_binary():
    seq = generate_scrambler_seq(7200)
    assert seq.shape == (7200,)
    assert set(np.unique(seq).tolist()).issubset({0, 1})
    assert np.array_equal(seq, generate_scrambler_seq(7200))


def test_descramble_roundtrip():
    b = make_burst(snr_db=None, scramble=True, seed=8)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    expected = b.payload_bits[_DATA_ROWS, :].reshape(-1)
    assert np.array_equal(d.descrambled_bits, expected)


# ---------------------------------------------------------------------------
# Resampling path (input at a non-nominal rate)
# ---------------------------------------------------------------------------

def test_decode_via_resample_from_20mhz():
    b = make_burst(snr_db=None, pad_start=500, seed=9)
    up = ofdm.resample_to(b.iq.astype(complex), ofdm.NOMINAL_SAMPLE_RATE, 20e6)
    d = demodulate(up, 20e6)
    assert d is not None
    assert d.resampled is True
    # Round-tripped 15.36 -> 20 -> 15.36, so the offset returns to ~pad_start.
    assert abs(d.sync_offset - 500) <= 3


# ---------------------------------------------------------------------------
# decode() top-level contract (now includes Turbo decode + CRC + field parse)
# ---------------------------------------------------------------------------

def test_decode_returns_none_on_noise():
    rng = np.random.default_rng(11)
    n = ofdm.burst_length(ofdm.NOMINAL_SAMPLE_RATE) * 2
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    assert decode(noise, ofdm.NOMINAL_SAMPLE_RATE) is None


def test_decode_none_on_unencoded_burst():
    # A burst with random QPSK payload (no valid Turbo frame) must fail CRC -> None.
    b = make_burst(snr_db=None, seed=10)
    assert decode(b.iq, b.sample_rate) is None


# ---------------------------------------------------------------------------
# Turbo back-end unit layers (encode/decode, rate-match inversion, CRC)
# ---------------------------------------------------------------------------

def test_qpp_interleaver_is_bijection():
    pi = T.qpp_interleaver(T.K_INFO)
    assert pi.size == T.K_INFO
    assert np.array_equal(np.sort(pi), np.arange(T.K_INFO))


def test_turbo_encode_decode_roundtrip_clean():
    rng = np.random.default_rng(0)
    info = rng.integers(0, 2, T.K_INFO).astype(np.int8)
    d0, d1, d2 = T.turbo_encode(info)
    assert d0.size == d1.size == d2.size == T.D_STREAM
    l0, l1, l2 = T.bits_to_llr(d0), T.bits_to_llr(d1), T.bits_to_llr(d2)
    dec, _, _ = T.turbo_decode(l0, l1, l2, iterations=3)
    assert np.array_equal(dec, info)


def test_rate_match_forward_reverse_inverts():
    rng = np.random.default_rng(1)
    d0, d1, d2 = T.turbo_encode(rng.integers(0, 2, T.K_INFO).astype(np.int8))
    e = T.rate_match(d0, d1, d2)
    assert e.size == T.E_RATE
    r0, r1, r2 = T.de_rate_match(T.bits_to_llr(e))
    assert np.array_equal((r0 < 0).astype(np.int8), d0)
    assert np.array_equal((r1 < 0).astype(np.int8), d1)
    assert np.array_equal((r2 < 0).astype(np.int8), d2)


def test_full_turbo_chain_corrects_errors():
    # Effective rate ~0.2: the decoder should fix a heavy raw bit-flip rate.
    rng = np.random.default_rng(2)
    info = rng.integers(0, 2, T.K_INFO).astype(np.int8)
    d0, d1, d2 = T.turbo_encode(info)
    e = T.rate_match(d0, d1, d2)
    flip = rng.random(e.size) < 0.10
    e[flip] ^= 1
    r0, r1, r2 = T.de_rate_match(T.bits_to_llr(e))
    dec, _, _ = T.turbo_decode(r0, r1, r2, iterations=8)
    assert np.array_equal(dec, info)


def test_crc24a_zeroes_out():
    rng = np.random.default_rng(3)
    payload = bytes(rng.integers(0, 256, 173).astype(np.uint8))
    c = T.crc24a(payload)
    full = payload + bytes([(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF])
    assert T.crc24a(full) == 0


def test_frame_pack_parse_roundtrip():
    fr = F.pack_dji_frame(serial="TESTSERIAL012345", drone_lat=1.0, drone_lon=2.0)
    assert len(fr) == F.DJI_FRAME_LEN
    payload = F.build_turbo_payload(fr)
    assert len(payload) == F.TURBO_BYTES and T.crc24a(payload) == 0
    p = F.parse_frame(payload)
    assert p is not None and p.serial == "TESTSERIAL012345"


# ---------------------------------------------------------------------------
# End-to-end encode -> decode: exact serial + GPS recovery
# ---------------------------------------------------------------------------

_FIELDS = dict(
    serial="1581F5FKD227ABCD",
    drone_lat=52.3702157, drone_lon=4.8951679,
    operator_lat=52.3600000, operator_lon=4.9000000,
    home_lat=52.3500000, home_lon=4.9100000,
    height=120, altitude=95, sequence=42,
)

# GPS is quantized to int32 = round(deg * 1e7/57.2957795785523), step ~5.7e-6 deg.
_COORD_TOL = 1e-5


def test_encode_decode_exact_serial_and_gps_clean():
    b = make_encoded_burst(_FIELDS, snr_db=None, seed=3)
    res = decode(b.iq, b.sample_rate)
    assert res is not None
    assert res.protocol == "ocusync2"
    assert res.serial == _FIELDS["serial"]                 # serial recovers exactly
    assert abs(res.drone_lat - _FIELDS["drone_lat"]) < _COORD_TOL
    assert abs(res.drone_lon - _FIELDS["drone_lon"]) < _COORD_TOL
    assert abs(res.operator_lat - _FIELDS["operator_lat"]) < _COORD_TOL
    assert abs(res.operator_lon - _FIELDS["operator_lon"]) < _COORD_TOL
    assert abs(res.home_lat - _FIELDS["home_lat"]) < _COORD_TOL
    assert abs(res.home_lon - _FIELDS["home_lon"]) < _COORD_TOL
    assert res.drone_height == 120 and res.drone_altitude == 95
    assert res.sequence == 42


def test_encode_decode_exact_at_15db():
    b = make_encoded_burst(_FIELDS, snr_db=15.0, seed=4)
    res = decode(b.iq, b.sample_rate)
    assert res is not None
    assert res.serial == _FIELDS["serial"]
    assert abs(res.drone_lat - _FIELDS["drone_lat"]) < _COORD_TOL
    assert abs(res.drone_lon - _FIELDS["drone_lon"]) < _COORD_TOL


def test_encode_decode_negative_coords():
    fields = dict(serial="WESTHEMISPHERE00", drone_lat=-33.8688, drone_lon=151.2093,
                  operator_lat=-33.87, operator_lon=151.21)
    b = make_encoded_burst(fields, snr_db=None, seed=5)
    res = decode(b.iq, b.sample_rate)
    assert res is not None and res.serial == fields["serial"]
    assert abs(res.drone_lat - fields["drone_lat"]) < _COORD_TOL
    assert abs(res.drone_lon - fields["drone_lon"]) < _COORD_TOL


def test_encode_decode_none_on_corruption():
    # Corrupt the descrambled bits hard enough that CRC cannot validate.
    b = make_encoded_burst(_FIELDS, snr_db=None, seed=6)
    d = demodulate(b.iq, b.sample_rate)
    assert d is not None
    rng = np.random.default_rng(6)
    corrupted = d.descrambled_bits.copy()
    flip = rng.random(corrupted.size) < 0.45          # near-random -> CRC must fail
    corrupted[flip] ^= 1
    from aerix_rf.decode.droneid import DroneIdDemod
    from dataclasses import replace
    d2 = replace(d, descrambled_bits=corrupted)
    from aerix_rf.decode.droneid import decode_frame
    assert decode_frame(d2) is None
