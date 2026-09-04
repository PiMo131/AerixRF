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
from aerix_rf.decode import droneid
from aerix_rf.decode.droneid import (
    decode, decode_all, find_burst_candidates, available, demodulate,
    generate_scrambler_seq, descramble_payload,
)
from aerix_rf.decode.zc import (
    zc_time_domain, find_zc_symbol_start, find_zc_symbol_start_int_cfo, normalized_xcorr,
)


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


# ---------------------------------------------------------------------------
# Window-level decoding: 1 s @ 20 MS/s HackRF-style captures, burst by burst
# ---------------------------------------------------------------------------

_FS_IN = 20e6
_ONE_SECOND = int(_FS_IN)


def _noise_window(n: int, noise_power: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    iq = rng.standard_normal(n, dtype=np.float32) + 1j * rng.standard_normal(n, dtype=np.float32)
    iq *= np.float32(np.sqrt(noise_power / 2.0))
    return iq.astype(np.complex64)


def _embed(window: np.ndarray, burst_iq: np.ndarray, burst_fs: float, offset: int) -> int:
    """Resample a (unit-power, zero-padded) 15.36 MHz burst to 20 MS/s and add it in.

    Returns the input-rate index of the burst's first sample.
    """
    up = ofdm.resample_to(burst_iq.astype(np.complex128), burst_fs, _FS_IN).astype(np.complex64)
    window[offset:offset + up.size] += up
    return offset


def _window_with_bursts(bursts, *, snr_db: float, seed: int, n: int = _ONE_SECOND):
    """`bursts` = [(offset_samples, EncodedBurst)], bursts are unit power -> SNR in dB."""
    w = _noise_window(n, 10.0 ** (-snr_db / 10.0), seed)
    for off, b in bursts:
        _embed(w, b.iq, b.sample_rate, off)
    return w


_PAD = 600     # zero pad (snr_db=None) on both sides so resampling has no edge transient


def test_find_burst_candidates_two_bursts_in_one_second():
    b1 = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=21)
    b2 = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=22)
    rng = np.random.default_rng(23)
    offs = sorted(int(v) for v in rng.integers(100_000, _ONE_SECOND - 100_000, 2))
    assert offs[1] - offs[0] > 50_000
    w = _window_with_bursts([(offs[0], b1), (offs[1], b2)], snr_db=10.0, seed=23)

    cands = find_burst_candidates(w, _FS_IN)
    assert len(cands) == 2
    burst_in = ofdm.burst_length(ofdm.NOMINAL_SAMPLE_RATE) * _FS_IN / ofdm.NOMINAL_SAMPLE_RATE
    pad_in = _PAD * _FS_IN / ofdm.NOMINAL_SAMPLE_RATE
    for (start, end, peak), off in zip(sorted(cands), offs):
        assert abs(start - (off + pad_in)) < 1000          # within ~2 envelope blocks
        assert abs((end - start) - burst_in) < 1500
        assert 0.5 < peak < 2.0                             # unit-power burst + noise


def test_decode_all_two_bursts_one_second_window_10db():
    fields2 = dict(_FIELDS, serial="SECONDDRONE00001", drone_lat=51.9, drone_lon=4.4)
    b1 = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=31)
    b2 = make_encoded_burst(fields2, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=32)
    rng = np.random.default_rng(33)
    offs = sorted(int(v) for v in rng.integers(100_000, _ONE_SECOND - 100_000, 2))
    assert offs[1] - offs[0] > 50_000
    w = _window_with_bursts([(offs[0], b1), (offs[1], b2)], snr_db=10.0, seed=33)

    import time
    t0 = time.perf_counter()
    attempts = decode_all(w, _FS_IN)
    elapsed = time.perf_counter() - t0
    # Measured ~0.14 s on the dev laptop (0.3 s under load); spec target < 1.5 s.
    assert elapsed < 1.5, f"decode_all took {elapsed:.2f}s"

    assert len(attempts) >= 2
    good = [a for a in attempts if a.level == "C"]
    assert len(good) == 2
    assert [a.error for a in attempts] == [None] * len(attempts)
    for a, off, f in zip(good, offs, (_FIELDS, fields2)):
        assert a.crc_ok and a.result is not None
        assert a.result.serial == f["serial"]
        assert abs(a.result.drone_lat - f["drone_lat"]) < _COORD_TOL
        assert abs(a.result.drone_lon - f["drone_lon"]) < _COORD_TOL
        assert a.integer_cfo_bins == 0
        assert abs(a.cfo_hz) < 500.0
        assert a.zc_score > 0.8 and a.zc6_score > 0.8
        assert 0.6 < a.duration_ms < 0.7
        assert a.snr_db is not None and 8.0 < a.snr_db < 14.0
        # Reported span refined to the synchronized burst (input-rate samples).
        expect_start = off + _PAD * _FS_IN / ofdm.NOMINAL_SAMPLE_RATE
        assert abs(a.start_sample - expect_start) < 10

    # decode() is the first CRC-valid result in time order.
    res = decode(w, _FS_IN)
    assert res is not None and res.serial == _FIELDS["serial"]


@pytest.mark.parametrize("cfo_bins,expect_k", [(2.3, 2), (-1.7, -2)])
def test_decode_all_integer_cfo(cfo_bins, expect_k):
    inject = cfo_bins * ofdm.CARRIER_SPACING_HZ                     # +34.5 kHz / -25.5 kHz
    b = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD,
                           seed=41, cfo_hz=inject)
    w = _window_with_bursts([(1_500_000, b)], snr_db=12.0, seed=42, n=3_000_000)
    attempts = decode_all(w, _FS_IN)
    assert len(attempts) == 1
    a = attempts[0]
    assert a.error is None
    assert a.level == "C" and a.crc_ok and a.result.serial == _FIELDS["serial"]
    assert a.integer_cfo_bins == expect_k
    assert abs(a.cfo_hz - inject) < 500.0
    assert a.demod is not None and a.demod.integer_cfo_bins == expect_k


def test_demodulate_integer_cfo_half_bin_wrap():
    # +0.49 and -0.51 subcarriers straddle the fractional estimator's +/-7.5 kHz
    # wrap: the integer search must absorb the wrap (k=0 vs k=-1) transparently.
    for bins, expect_k in ((0.49, 0), (-0.51, -1), (3.9, 4), (-4.0, -4)):
        inject = bins * ofdm.CARRIER_SPACING_HZ
        b = make_encoded_burst(_FIELDS, snr_db=20.0, seed=43, cfo_hz=inject)
        d = demodulate(b.iq, b.sample_rate)
        assert d is not None, bins
        assert d.integer_cfo_bins == expect_k, bins
        assert abs(d.cfo_hz - inject) < 400.0, bins
        assert droneid.decode_frame(d) is not None, bins


def test_zc_bank_is_ambiguous_without_second_pilot():
    # Documents why sym-6 disambiguation exists: a ZC shifted by k bins still
    # correlates ~0.9+ with the unshifted taps (at a slightly different lag).
    b = make_burst(snr_db=None, pad_start=500, seed=44)
    fft_size = ofdm.fft_size_for(b.sample_rate)
    _p, _s, _k, per_shift, per_peaks = find_zc_symbol_start_int_cfo(
        b.iq.astype(complex), fft_size, 4, shifts=range(-4, 5))
    assert per_shift[4] > 0.99                     # true k = 0
    assert per_shift.min() > 0.85                  # every wrong k also "matches"
    assert np.ptp(per_peaks) <= 20                 # ...within a few samples


def test_decode_all_pure_noise_is_empty_and_fast():
    w = _noise_window(_ONE_SECOND, 0.1, seed=51)
    import time
    t0 = time.perf_counter()
    attempts = decode_all(w, _FS_IN)
    elapsed = time.perf_counter() - t0
    # Envelope only (no ZC search): measured ~0.05 s; spec target < 0.3 s.
    assert elapsed < 0.3, f"decode_all on noise took {elapsed:.2f}s"
    assert all(a.level in ("none", "A") for a in attempts)
    assert attempts == []
    assert decode(w, _FS_IN) is None


def test_decode_all_corrupted_burst_no_exception():
    # Second half of the burst replaced by same-power noise (keeps the envelope
    # DroneID-shaped): ZC sym 4 still syncs, sym 6 cannot confirm, CRC fails.
    b = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=61)
    bad = b.iq.copy()
    half = _PAD + (bad.size - 2 * _PAD) // 2
    rng = np.random.default_rng(62)
    m = bad.size - half
    bad[half:] = ((rng.standard_normal(m) + 1j * rng.standard_normal(m)) / np.sqrt(2)).astype(np.complex64)
    w = _noise_window(3_000_000, 0.1, seed=63)
    _embed(w, bad, b.sample_rate, 1_200_000)

    attempts = decode_all(w, _FS_IN)
    assert len(attempts) == 1
    a = attempts[0]
    assert a.error is None
    assert a.level in ("A", "B")
    assert a.crc_ok is False and a.result is None
    assert a.zc_score > 0.8
    assert a.zc6_score < droneid.ZC6_CONFIRM_THRESHOLD
    assert decode(w, _FS_IN) is None

    # Zeroed second half on a short pre-cut slice: same contract, no exception.
    zeroed = b.iq.copy()
    zeroed[half:] = 0
    short = decode_all(zeroed, b.sample_rate)
    assert len(short) == 1 and short[0].level in ("A", "B") and not short[0].crc_ok
    assert short[0].error is None
    assert decode(zeroed, b.sample_rate) is None


def test_decode_all_isolates_per_burst_exceptions(monkeypatch):
    b1 = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=71)
    b2 = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=72)
    w = _window_with_bursts([(500_000, b1), (2_000_000, b2)], snr_db=12.0, seed=73, n=3_000_000)

    real = droneid.decode_frame
    calls = []

    def flaky(demod, iterations=8):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(demod, iterations)

    monkeypatch.setattr(droneid, "decode_frame", flaky)
    attempts = decode_all(w, _FS_IN)
    assert len(attempts) == 2
    # Candidates are processed strongest-first, so either burst may have hit
    # the exception; exactly one did, and it did not stop the other.
    failed = [a for a in attempts if a.error is not None]
    ok = [a for a in attempts if a.error is None]
    assert len(failed) == 1 and failed[0].error == "RuntimeError: boom"
    assert failed[0].level == "B" and not failed[0].crc_ok
    assert len(ok) == 1 and ok[0].level == "C" and ok[0].result.serial == _FIELDS["serial"]


def test_decode_short_slice_keeps_old_contract():
    # Pre-cut bursts (<= 4 burst lengths) skip segmentation: same answers as before.
    b = make_encoded_burst(_FIELDS, snr_db=15.0, seed=81)
    attempts = decode_all(b.iq, b.sample_rate)
    assert len(attempts) == 1 and attempts[0].level == "C"
    assert attempts[0].result.serial == _FIELDS["serial"]
    assert abs(attempts[0].start_sample - b.burst_start) <= 2
    # Unencoded burst: front end fine (B), CRC fails, decode() -> None.
    u = make_burst(snr_db=None, seed=82)
    att = decode_all(u.iq, u.sample_rate)
    assert len(att) == 1 and att[0].level == "B" and not att[0].crc_ok
    assert decode(u.iq, u.sample_rate) is None


def _ambient_window(seed: int, n_bursts: int = 12, n: int = _ONE_SECOND) -> np.ndarray:
    """Ambient 2.4 GHz stand-in: noise plus Wi-Fi/BT-like noise bursts of 0.5-1.0 ms."""
    rng = np.random.default_rng(seed)
    w = _noise_window(n, 0.05, seed)
    for i in range(n_bursts):
        off = 200_000 + i * ((n - 400_000) // n_bursts)
        m = int(rng.integers(10_000, 20_000))
        p = 0.05 * 10 ** (rng.uniform(8, 15) / 10)
        w[off:off + m] += ((rng.standard_normal(m) + 1j * rng.standard_normal(m))
                           * np.sqrt(p / 2)).astype(np.complex64)
    return w


def test_decode_all_ambient_non_droneid_bursts_are_cheap():
    # Live-HackRF finding: ambient Wi-Fi/BT yields ~8 candidates per second, all
    # level "none"; each must be rejected by the single-correlation gate cheaply.
    w = _ambient_window(seed=91)
    assert len(find_burst_candidates(w, _FS_IN)) == 8          # max_bursts cap hit
    import time
    decode_all(w, _FS_IN)                                       # warm-up (FFT plans etc.)
    t0 = time.perf_counter()
    attempts = decode_all(w, _FS_IN)
    elapsed = time.perf_counter() - t0
    # Measured ~0.11 s (8 gated rejects + envelope); coordinator target < 0.25 s.
    assert elapsed < 0.35, f"ambient decode_all took {elapsed:.2f}s"
    assert len(attempts) == 8
    assert all(a.level == "none" and a.result is None and a.error is None for a in attempts)
    assert all(a.zc_score < droneid.DEFAULT_CORRELATION_THRESHOLD for a in attempts)
    assert all(0.4 <= a.duration_ms <= 1.5 for a in attempts)


def test_decode_all_budget_skips_weaker_candidates():
    b1 = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=101)
    b2 = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=102)
    w = _noise_window(3_000_000, 0.1, seed=103)
    _embed(w, b1.iq, b1.sample_rate, 500_000)
    _embed(w, (b2.iq * np.float32(1.5)), b2.sample_rate, 2_000_000)   # stronger
    full = decode_all(w, _FS_IN, budget_s=None)
    assert [a.level for a in full] == ["C", "C"]
    assert all(a.error is None for a in full)

    capped = decode_all(w, _FS_IN, budget_s=1e-9)
    assert len(capped) == 1                                    # strongest one only
    assert capped[0].level == "C" and capped[0].start_sample > 1_900_000
    assert capped[0].error is not None and "1 weaker candidate(s) not attempted" in capped[0].error
    assert "budget_s=1e-09 exceeded" in capped[0].error


# ---------------------------------------------------------------------------
# Field lesson (Mini 3, 2026-09-04): the DroneID channel sits off the window
# centre and 20 dB below the RC hops / Wi-Fi beacons in the same window.
# ---------------------------------------------------------------------------

def _embed_offset(window: np.ndarray, burst_iq: np.ndarray, burst_fs: float,
                  offset: int, offset_hz: float) -> None:
    """Add a burst at `offset_hz` from the window centre, clipped by a real
    front end (built at 40 MS/s, mixed, then decimated to 20 MS/s so the part
    outside +/-10 MHz is filtered away rather than aliased)."""
    up = ofdm.resample_to(burst_iq.astype(np.complex128), burst_fs, 2 * _FS_IN)
    t = np.arange(up.size) / (2 * _FS_IN)
    up = up * np.exp(2j * np.pi * offset_hz * t)
    down = ofdm.resample_to(up, 2 * _FS_IN, _FS_IN).astype(np.complex64)
    window[offset:offset + down.size] += down


def _band_noise_burst(rng, n: int, center_hz: float, bw_hz: float, power: float) -> np.ndarray:
    x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    f = np.fft.fftfreq(n, 1.0 / _FS_IN)
    X = np.fft.fft(x)
    X[np.abs(f - center_hz) > bw_hz / 2] = 0
    x = np.fft.ifft(X)
    return (x / np.sqrt(np.mean(np.abs(x) ** 2)) * np.sqrt(power)).astype(np.complex64)


@pytest.mark.parametrize("offset_mhz", [-7.5, 5.0, 0.0])
def test_decode_all_off_centre_droneid_under_stronger_ambient(offset_mhz):
    b = make_encoded_burst(_FIELDS, snr_db=None, pad_start=_PAD, pad_end=_PAD, seed=111)
    rng = np.random.default_rng(112)
    w = _noise_window(_ONE_SECOND, 0.1, seed=112)                      # DroneID SNR 10 dB
    _embed_offset(w, b.iq, b.sample_rate, 7_000_000, offset_mhz * 1e6)
    # Wi-Fi beacon look-alikes: 18 MHz wide, 1 ms, 15 dB above the DroneID burst.
    for off in (1_000_000, 3_050_000, 5_100_000, 12_000_000, 16_000_000):
        w[off:off + 20_000] += _band_noise_burst(rng, 20_000, 0.0, 18e6, 10 ** 1.5)
    # RC uplink hops: 2 MHz wide, 0.5 ms, 15 dB up, on a 2 MHz raster.
    for i, off in enumerate(range(200_000, _ONE_SECOND - 200_000, 1_400_000)):   # ~70 ms per hop
        fc = (-5 + (i % 6)) * 2e6 + 1e6
        w[off:off + 10_000] += _band_noise_burst(rng, 10_000, fc, 2e6, 10 ** 1.5)

    attempts = decode_all(w, _FS_IN)
    good = [a for a in attempts if a.level == "C"]
    assert len(good) == 1, [(a.level, a.center_offset_hz, a.occupied_bw_hz) for a in attempts]
    a = good[0]
    assert a.result.serial == _FIELDS["serial"]
    assert abs(a.result.drone_lat - _FIELDS["drone_lat"]) < _COORD_TOL
    assert a.droneid_shaped
    assert abs(a.center_offset_hz - offset_mhz * 1e6) < 150e3
    assert abs(a.cfo_hz - offset_mhz * 1e6) < 1e3
    if offset_mhz == -7.5:
        assert a.occupied_bw_hz < 8e6                     # clipped at the window edge
    else:
        assert 8.5e6 < a.occupied_bw_hz < 9.6e6
    assert all(a.error is None for a in attempts)
    # The stronger ambient bursts were examined but ranked behind the shaped one.
    assert not any(x.droneid_shaped for x in attempts if x is not a)


def test_burst_spectrum_shapes():
    rng = np.random.default_rng(5)
    wifi = _band_noise_burst(rng, 20_000, 0.0, 18e6, 1.0)
    c, bw = droneid.burst_spectrum(wifi, _FS_IN)
    assert bw > 16e6 and abs(c) < 0.5e6
    rc = _band_noise_burst(rng, 10_000, 3e6, 2e6, 1.0)
    c, bw = droneid.burst_spectrum(rc, _FS_IN)
    assert 1.5e6 < bw < 2.8e6 and abs(c - 3e6) < 0.1e6
    assert droneid.burst_spectrum(np.zeros(0, dtype=np.complex64), _FS_IN) == (0.0, 0.0)
