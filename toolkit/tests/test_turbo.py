"""The LTE turbo code: the error correction that makes DroneID usable.

Before this existed the decoder read systematic bits straight off the
constellation, so a frame checked out only above 18 dB in-band signal-to-noise
and failed completely below 16. These tests hold the codec to the standard's
structure and to a measured coding gain, because both can regress silently.
"""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.droneid import constants as C
from antsdr_toolkit.droneid import fec, turbo


def _llr(stream: np.ndarray, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Soft values off an antipodal channel: bit 0 sends +1, bit 1 sends -1."""
    symbol = 1.0 - 2.0 * stream.astype(np.float64)
    return 2.0 * (symbol + sigma * rng.standard_normal(stream.size)) / sigma ** 2


# ---------------------------------------------------------------- interleaver


def test_every_interleaver_in_the_table_is_a_permutation():
    """188 block sizes, and a quadratic polynomial is only a permutation for
    the right coefficients. A typo in the table shows up here and nowhere else
    until a decode silently fails."""
    for size in turbo.QPP_PARAMS:
        assert len(set(turbo.qpp_interleaver(size).tolist())) == size, size


def test_the_table_matches_the_values_everyone_quotes():
    """The first and last rows of 3GPP TS 36.212 Table 5.1.3-3."""
    assert turbo.QPP_PARAMS[40] == (3, 10)
    assert turbo.QPP_PARAMS[6144] == (263, 480)
    assert len(turbo.QPP_PARAMS) == 188


def test_droneid_uses_a_block_size_that_is_in_the_table():
    """1408 bits is 176 bytes, and K+4 is the rate matcher's D."""
    assert C.PAYLOAD_BYTES * 8 == 1408
    assert 1408 in turbo.QPP_PARAMS
    assert turbo.QPP_PARAMS[1408] == (43, 88)
    assert 1408 + 4 == C.RATE_MATCH_D


def test_a_size_outside_the_table_is_refused_with_the_neighbours():
    with pytest.raises(ValueError, match="not an LTE code block size"):
        turbo.qpp_interleaver(1409)


# -------------------------------------------------------------------- trellis


def test_the_trellis_terminates_and_is_reversible():
    """Eight states, and every state reachable by exactly two predecessors."""
    next_state, parity = turbo.rsc_trellis()
    assert next_state.shape == (8, 2) and parity.shape == (8, 2)
    arrivals = np.zeros(8, dtype=int)
    for state in range(8):
        for bit in (0, 1):
            arrivals[next_state[state, bit]] += 1
    assert np.all(arrivals == 2), "the trellis is not a valid convolutional code"


def test_the_encoder_produces_three_streams_the_rate_matcher_accepts():
    bits = np.random.default_rng(0).integers(0, 2, 1408).astype(np.uint8)
    d0, d1, d2 = turbo.turbo_encode(bits)
    assert d0.size == d1.size == d2.size == C.RATE_MATCH_D
    assert np.array_equal(d0[:1408], bits), "the systematic stream is the input"
    assert fec.rate_match(d0, d1, d2).size == C.RATE_MATCH_E


def test_the_encoder_refuses_what_it_cannot_encode():
    with pytest.raises(ValueError, match="not an LTE code block size"):
        turbo.turbo_encode(np.zeros(100, dtype=np.uint8))
    with pytest.raises(ValueError, match="must be bits"):
        turbo.turbo_encode(np.full(1408, 7, dtype=np.uint8))


# -------------------------------------------------------------------- decoding


def test_a_clean_block_round_trips_exactly():
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 1408).astype(np.uint8)
    d0, d1, d2 = turbo.turbo_encode(bits)
    hard = [np.where(s == 0, 8.0, -8.0) for s in (d0, d1, d2)]
    assert np.array_equal(turbo.turbo_decode(*hard, iterations=2), bits)


@pytest.mark.parametrize("esn0_db", [-4.0, -2.0, 0.0, 2.0])
def test_the_code_corrects_a_channel_that_defeats_hard_decisions(esn0_db):
    """At -4 dB the raw error rate is about 18 %, and the block still comes
    out exact. That is the whole point of the code and the reason the
    receiver's sensitivity moved by ten decibels."""
    sigma = np.sqrt(0.5 * 10 ** (-esn0_db / 10))
    rng = np.random.default_rng(int(100 - esn0_db * 10))
    bits = rng.integers(0, 2, 1408).astype(np.uint8)
    d0, d1, d2 = turbo.turbo_encode(bits)
    soft = [_llr(s, sigma, rng) for s in (d0, d1, d2)]
    raw = np.count_nonzero((soft[0][:1408] < 0).astype(np.uint8) != bits) / 1408
    out = turbo.turbo_decode(*soft, iterations=8)
    assert np.array_equal(out, bits), f"raw BER was {raw:.3f}"
    if esn0_db <= -2.0:
        assert raw > 0.10, "the channel was not actually hard"


def test_it_gives_up_rather_than_hanging_when_the_channel_is_hopeless():
    """Below the waterfall it returns something wrong, and that is correct
    behaviour: the CRC is what rejects it, not the decoder."""
    rng = np.random.default_rng(0)
    noise = rng.standard_normal(C.RATE_MATCH_D)
    out = turbo.turbo_decode(noise, noise, noise, iterations=3)
    assert out.size == 1408 and out.dtype == np.uint8


def test_the_crc_callback_stops_early():
    """A correct block should not be iterated further, which both saves time
    and stops a good answer being walked away from."""
    rng = np.random.default_rng(1)
    bits = rng.integers(0, 2, 1408).astype(np.uint8)
    d0, d1, d2 = turbo.turbo_encode(bits)
    soft = [_llr(s, 0.7, rng) for s in (d0, d1, d2)]
    calls = []

    def check(candidate):
        calls.append(1)
        return np.array_equal(candidate, bits)

    out = turbo.turbo_decode(*soft, iterations=20, crc_check=check)
    assert np.array_equal(out, bits)
    assert len(calls) < 20, "the early exit never fired"


def test_mismatched_stream_lengths_are_refused():
    with pytest.raises(ValueError, match="three streams must match"):
        turbo.turbo_decode(np.zeros(1412), np.zeros(1412), np.zeros(10))


# ------------------------------------------------------------ rate matching


def test_soft_de_rate_matching_inverts_the_forward_path():
    """Built from the transmitter's own construction over position labels, so
    the two cannot drift apart the way a hand-derived inverse would."""
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 1408).astype(np.uint8)
    d0, d1, d2 = turbo.turbo_encode(bits)
    coded = fec.rate_match(d0, d1, d2)
    soft = np.where(coded == 0, 8.0, -8.0)
    s, p1, p2 = fec.rate_dematch_llr(soft)
    for recovered, original in ((s, d0), (p1, d1), (p2, d2)):
        assert np.array_equal((recovered < 0).astype(np.uint8), original)


def test_the_map_covers_every_transmitted_bit():
    mapping = fec.rate_match_map()
    assert mapping.shape == (C.RATE_MATCH_E, 2)
    assert set(np.unique(mapping[:, 0]).tolist()) == {0, 1, 2}
    assert mapping[:, 1].max() < C.RATE_MATCH_D


def test_de_rate_matching_refuses_the_wrong_length():
    with pytest.raises(ValueError, match="expected 7200 soft values"):
        fec.rate_dematch_llr(np.zeros(100))


def test_the_whole_chain_from_bits_to_bits():
    """Encode, rate match, add noise, de-rate-match, decode."""
    rng = np.random.default_rng(7)
    bits = rng.integers(0, 2, 1408).astype(np.uint8)
    coded = fec.rate_match(*turbo.turbo_encode(bits))
    sigma = 0.9
    symbol = 1.0 - 2.0 * coded.astype(np.float64)
    soft = 2.0 * (symbol + sigma * rng.standard_normal(coded.size)) / sigma ** 2
    assert np.array_equal(turbo.turbo_decode(*fec.rate_dematch_llr(soft),
                                             iterations=8), bits)
