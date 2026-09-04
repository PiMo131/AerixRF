"""Tests for stage-3 DJI DroneID decode front end (ZC sync + OFDM demod).

Validated against synthetic spec-accurate bursts from aerix_rf.decode._synth.
"""

from __future__ import annotations

import numpy as np
import pytest

from aerix_rf.decode import ofdm
from aerix_rf.decode._synth import make_burst
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
# decode() top-level contract
# ---------------------------------------------------------------------------

def test_decode_returns_result_on_burst():
    b = make_burst(snr_db=15.0, seed=10)
    res = decode(b.iq, b.sample_rate)
    assert res is not None
    assert res.protocol == "ocusync2"
    # Field extraction (serial/lat/lon) is a documented TODO -> None for now.
    assert res.serial is None and res.drone_lat is None


def test_decode_returns_none_on_noise():
    rng = np.random.default_rng(11)
    n = ofdm.burst_length(ofdm.NOMINAL_SAMPLE_RATE) * 2
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    assert decode(noise, ofdm.NOMINAL_SAMPLE_RATE) is None
