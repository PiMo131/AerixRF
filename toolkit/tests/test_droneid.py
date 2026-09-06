"""The DroneID chain: constants, pilots, coding, and a full loopback decode.

The loopback tests build a burst with :mod:`antsdr_toolkit.droneid.synth`,
put it in noise with a frequency and timing offset, and require the receiver
to recover the exact frame that went in.  That is the only honest way to test
a decoder without a drone on the bench, and it exercises everything except
the turbo code, which this toolkit does not implement (see
:mod:`antsdr_toolkit.droneid.fec`).
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest

from antsdr_toolkit.droneid import constants as C
from antsdr_toolkit.droneid import fec, synth, zc
from antsdr_toolkit.droneid import receiver as rx

FS = 15.36e6


# ------------------------------------------------------------------- constants


def test_waveform_constants_match_the_reverse_engineered_phy():
    assert C.fft_size(15.36e6) == 1024
    assert C.fft_size(30.72e6) == 2048
    assert C.fft_size(61.44e6) == 4096
    assert C.cp_schedule(15.36e6) == (80, 72, 72, 72, 72, 72, 72, 72, 80)
    assert C.cp_schedule(30.72e6) == (160,) + (144,) * 7 + (160,)
    assert C.cp_schedule(61.44e6) == (320,) + (288,) * 7 + (320,)
    assert C.burst_length(15.36e6) == 9880
    assert C.burst_duration_s(15.36e6) == pytest.approx(643.2e-6, rel=1e-4)
    # the burst lasts the same time at every rate
    for rate in C.SUPPORTED_RATES_HZ:
        assert C.burst_duration_s(rate) == pytest.approx(643.2e-6, rel=1e-3)
    assert C.zc_body_offsets(15.36e6) == (3368, 5560)
    assert C.RATE_MATCH_E == 7200 and C.RATE_MATCH_D == 1412
    assert C.occupied_bandwidth_hz() == 9e6


def test_legacy_bursts_drop_the_first_symbol():
    assert len(C.cp_schedule(FS, legacy=True)) == C.LEGACY_SYMBOLS
    assert C.burst_length(FS, legacy=True) == 8784
    assert C.burst_duration_s(FS, legacy=True) == pytest.approx(571.9e-6, rel=1e-3)


def test_rates_that_are_not_a_multiple_of_the_spacing_are_refused():
    # 20 MSPS is the E200's host-link ceiling on the UHD firmware and the
    # rate people reach for first; it is not a legal DroneID rate.
    with pytest.raises(ValueError, match="not a multiple"):
        C.fft_size(20e6)
    assert not C.is_supported_rate(20e6)
    assert all(C.is_supported_rate(r) for r in C.SUPPORTED_RATES_HZ)
    with pytest.raises(ValueError, match="too few"):
        C.fft_size(6e6)  # integer FFT of 400 bins, too small for 601 carriers


def test_hop_centres_and_product_table():
    assert 2429.5e6 in C.HOP_CENTRES_HZ and 5756.5e6 in C.HOP_CENTRES_HZ
    assert C.channel_for(2429.4e6) == 2429.5e6
    assert C.channel_for(2500e6) is None
    assert C.PRODUCT_TYPES[63] == "Mini 2" and C.PRODUCT_TYPES[68] == "DJI Mavic 3"


# ----------------------------------------------------------------- Zadoff-Chu


def test_zc_symbol_construction():
    z600 = zc.zc_time(600, FS)
    z147 = zc.zc_time(147, FS)
    assert z600.shape == (1024,) and z600.dtype == np.complex64
    # 600 of 1024 bins occupied, DC null
    spec = np.fft.fftshift(np.fft.fft(z600.astype(np.complex128)))
    occupied = np.abs(spec) > 0.1 * np.abs(spec).max()
    assert occupied.sum() == C.N_DATA_CARRIERS
    assert not occupied[512]  # DC carrier is empty
    # constant amplitude on the occupied carriers: the defining property
    mag = np.abs(spec[occupied])
    assert mag.std() / mag.mean() < 1e-6
    assert not np.allclose(z600, z147)


def test_root_600_is_nearly_its_own_time_reversal():
    # 600 = 601 - 1, so the root-600 chirp is close to symmetric; root 147 is
    # not. Measured values, and the reason root 600 is the search pilot.
    assert zc.half_symmetry(zc.zc_time(600, FS)) > 0.8
    assert zc.half_symmetry(zc.zc_time(147, FS)) < 0.6
    assert zc.half_symmetry(np.zeros(0, np.complex64)) == 0.0


def test_zc_autocorrelation_peaks_sharply():
    z = zc.zc_time(600, FS).astype(np.complex128)
    score = rx.correlate_zc(np.concatenate([np.zeros(100), z, np.zeros(100)]), 600, FS)
    peak = int(np.argmax(score))
    assert peak == 100 and score[peak] > 0.99
    away = np.concatenate([score[:peak - 20], score[peak + 20:]])
    assert away.max() < 0.35


# ------------------------------------------------------------- coding and CRC


def test_gold_sequence_is_the_lte_one():
    seq = fec.gold_sequence(7200)
    assert seq.shape == (7200,) and set(np.unique(seq)) <= {0, 1}
    assert 0.45 < seq.mean() < 0.55  # balanced
    # deterministic and seed-dependent
    assert np.array_equal(seq, fec.gold_sequence(7200))
    assert not np.array_equal(seq, fec.gold_sequence(7200, c_init=1))


def test_scrambling_is_an_involution():
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, 7200).astype(np.uint8)
    assert np.array_equal(fec.descramble(fec.scramble(bits)), bits)


def test_rate_matching_round_trips_the_systematic_bits():
    rng = np.random.default_rng(1)
    systematic = rng.integers(0, 2, C.RATE_MATCH_D).astype(np.uint8)
    p1 = rng.integers(0, 2, C.RATE_MATCH_D).astype(np.uint8)
    p2 = rng.integers(0, 2, C.RATE_MATCH_D).astype(np.uint8)
    coded = fec.rate_match(systematic, p1, p2)
    assert coded.shape == (C.RATE_MATCH_E,)
    assert np.array_equal(fec.rate_unmatch_systematic(coded), systematic)
    # the parity streams genuinely change the coded bits
    other = fec.rate_match(systematic, p2, p1)
    assert not np.array_equal(coded, other)
    # but not the recovered systematic bits
    assert np.array_equal(fec.rate_unmatch_systematic(other), systematic)


def test_sub_block_interleaver_shape_and_inverse():
    bits = np.arange(C.RATE_MATCH_D, dtype=np.uint8) % 2
    out, nulls = fec.sub_block_interleave(bits)
    n_rows = int(np.ceil(C.RATE_MATCH_D / 32))
    assert out.size == n_rows * 32 == nulls.size
    assert nulls.sum() == n_rows * 32 - C.RATE_MATCH_D


def test_crcs():
    assert fec.crc24a(b"") == 0
    assert fec.crc24a(bytes(10)) == 0  # zero data, zero remainder
    assert fec.crc24a(b"\x01") != 0
    # a payload with its CRC appended has a zero remainder
    body = bytes(range(173))
    crc = fec.crc24a(body)
    payload = body + bytes(((crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF))
    assert fec.crc24a(payload) == 0 and fec.check_payload_crc(payload)
    # DJI's CRC-16 is seeded, so it differs from a plain CRC-16
    assert fec.crc16_dji(b"") == C.CRC16_INIT
    assert fec.crc16_dji(b"123456789") != fec.crc16_dji(b"123456789", init=0)


def test_turbo_decoder_is_absent_and_says_so():
    with pytest.raises(NotImplementedError, match="systematic bits only"):
        fec.turbo_decode(np.zeros(10))


def test_bit_and_byte_conversion():
    data = bytes([0b10110010, 0x00, 0xFF])
    bits = fec.bytes_to_bits(data)
    assert bits[:8].tolist() == [1, 0, 1, 1, 0, 0, 1, 0]
    assert fec.bits_to_bytes(bits) == data
    with pytest.raises(ValueError, match="multiple of 8"):
        fec.bits_to_bytes(np.zeros(7, np.uint8))


# --------------------------------------------------------------- the frame


def test_frame_round_trips_through_the_synthesiser_and_parser():
    tx = synth.DroneIdTx(serial="ABC123XYZ", drone_lat=52.0, drone_lon=4.5,
                         product_type=63, height_m=17.0)
    frame = synth.make_frame_bytes(tx)
    assert len(frame) == C.FRAME_BYTES
    payload = synth.make_payload_bytes(tx)
    assert len(payload) == C.PAYLOAD_BYTES and fec.crc24a(payload) == 0

    parsed = rx.parse_frame(payload)
    assert parsed is not None
    assert parsed.crc16_ok and parsed.crc24_ok
    assert parsed.serial == "ABC123XYZ"
    assert parsed.product_name == "Mini 2"
    assert parsed.drone_lat == pytest.approx(52.0, abs=1e-4)
    assert parsed.drone_lon == pytest.approx(4.5, abs=1e-4)
    assert parsed.height_m == pytest.approx(17.0, abs=0.5)
    assert parsed.yaw_deg == pytest.approx(tx.yaw_deg, abs=0.1)


def test_zero_positions_are_reported_as_unknown_not_as_the_gulf_of_guinea():
    tx = synth.DroneIdTx(pilot_lat=0.0, pilot_lon=0.0, home_lat=0.0, home_lon=0.0)
    parsed = rx.parse_frame(synth.make_payload_bytes(tx))
    assert parsed is not None
    assert parsed.pilot_lat is None and parsed.pilot_lon is None
    assert parsed.home_lat is None and parsed.home_lon is None
    assert parsed.drone_lat is not None


def test_frame_serialises():
    import json

    parsed = rx.parse_frame(synth.make_payload_bytes())
    assert parsed is not None
    doc = json.loads(json.dumps(parsed.to_dict()))
    assert doc["product_name"] == "Mini 2" and doc["crc24_ok"] is True
    assert doc["speed_h_m_s"] == pytest.approx(np.hypot(3.0, 1.5), abs=0.6)


# ------------------------------------------------------------------- loopback


def _capture(cfo_hz=0.0, snr_db=25.0, t_start_s=2e-3, sample_offset=0.37,
             seconds=0.02, fs=FS, tx=None, seed=5, legacy=False):
    tx = synth.DroneIdTx() if tx is None else tx
    burst = synth.make_burst(fs, tx, rng=np.random.default_rng(1), legacy=legacy)
    return synth.place_burst(fs, int(seconds * fs), burst=burst, t_start_s=t_start_s,
                             cfo_hz=cfo_hz, snr_db=snr_db, sample_offset=sample_offset,
                             rng=np.random.default_rng(seed))


def test_clean_burst_decodes_to_the_transmitted_frame():
    tx = synth.DroneIdTx(serial="LOOPBACK00000001", drone_lat=51.5, drone_lon=4.0)
    x = _capture(tx=tx)
    results = rx.process(x, FS)
    assert len(results) == 1
    detection, frame = results[0]
    assert detection.score > 0.7
    assert detection.confirm_score > 0.9  # cyclic prefixes line up
    assert detection.t_start_s == pytest.approx(2e-3, abs=2e-6)
    assert frame is not None and frame.crc16_ok and frame.crc24_ok
    assert frame.serial == "LOOPBACK00000001"
    assert frame.drone_lat == pytest.approx(51.5, abs=1e-4)
    assert frame.drone_lon == pytest.approx(4.0, abs=1e-4)


@pytest.mark.parametrize("cfo", [0.0, 1500.0, 7000.0, 15000.0, 60000.0, -60000.0, 120000.0])
def test_decoding_survives_a_large_frequency_offset(cfo):
    # The cyclic prefix alone would give up beyond 7.5 kHz. The Zadoff-Chu
    # chirp slides instead of fading, and the slide is the coarse estimate.
    x = _capture(cfo_hz=cfo)
    detections = rx.find_bursts(x, FS)
    assert len(detections) == 1, f"no detection at {cfo} Hz"
    assert detections[0].cfo_hz == pytest.approx(cfo, abs=200.0)
    frame = rx.decode_burst(x, FS, detections[0])
    assert frame is not None and frame.crc24_ok and frame.crc16_ok


def test_frequency_estimate_uses_the_chirp_slide():
    assert rx.zc_shift_hz_per_sample(FS) == pytest.approx(8804.0, rel=1e-3)
    # A sample at 30.72 MSPS is half as long, so it is worth half the offset;
    # the underlying chirp rate, 135.2 GHz per second, is rate-independent.
    assert rx.zc_shift_hz_per_sample(30.72e6) == pytest.approx(
        rx.zc_shift_hz_per_sample(FS) / 2.0, rel=1e-9)
    for rate in C.SUPPORTED_RATES_HZ:
        assert rx.zc_shift_hz_per_sample(rate) * rate == pytest.approx(1.352e11, rel=1e-3)
    x = _capture(cfo_hz=60000.0)
    detections = rx.find_bursts(x, FS)
    assert detections and detections[0].cfo_hz == pytest.approx(60000.0, abs=200.0)


def test_second_pilot_is_reported_but_does_not_gate():
    # Root 147 decorrelates rather than sliding, so at 30 kHz it is useless as
    # a confirmation even though the burst is perfectly good.
    x = _capture(cfo_hz=30000.0)
    detections = rx.find_bursts(x, FS)
    assert len(detections) == 1
    assert detections[0].zc147_score < 0.3
    assert detections[0].confirm_score > 0.9
    assert rx.decode_burst(x, FS, detections[0]).crc24_ok


@pytest.mark.parametrize("rate", [15.36e6, 30.72e6])
def test_decoding_at_every_supported_rate(rate):
    x = _capture(fs=rate, seconds=0.01, t_start_s=1e-3)
    results = rx.process(x, rate)
    assert len(results) == 1
    _detection, frame = results[0]
    assert frame is not None and frame.crc24_ok


def test_several_bursts_are_found_in_time_order():
    tx = synth.DroneIdTx()
    burst = synth.make_burst(FS, tx, rng=np.random.default_rng(1))
    n = int(0.05 * FS)
    rng = np.random.default_rng(9)
    x = ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)).astype(np.complex64)
    starts = [int(0.005 * FS), int(0.020 * FS), int(0.035 * FS)]
    scale = np.sqrt(C.occupied_bandwidth_hz() / FS * 10 ** 2.5, dtype=np.float32)
    for start in starts:
        x[start:start + burst.size] += burst * scale
    detections = rx.find_bursts(x, FS)
    assert [d.sample_start for d in detections] == starts
    assert all(rx.decode_burst(x, FS, d).crc24_ok for d in detections)


def test_noise_alone_produces_no_detections():
    rng = np.random.default_rng(7)
    n = 300_000
    noise = ((rng.standard_normal(n) + 1j * rng.standard_normal(n))
             / np.sqrt(2)).astype(np.complex64)
    assert rx.find_bursts(noise, FS) == []
    # a strong wideband burst that is not DroneID is not a DroneID burst
    from antsdr_toolkit.device.synthetic import bandlimited_noise_burst

    other = bandlimited_noise_burst(FS, 9e6, 643e-6, np.random.default_rng(3))
    noise[100_000:100_000 + other.size] += other * 3.0
    assert rx.find_bursts(noise, FS) == []


def test_low_signal_to_noise_fails_the_crc_rather_than_lying():
    # Without turbo decoding the receiver runs out of margin around 15 dB; the
    # contract is that it says so through the CRC instead of inventing a frame.
    x = _capture(snr_db=6.0)
    for detection in rx.find_bursts(x, FS):
        frame = rx.decode_burst(x, FS, detection)
        if frame is not None:
            assert not (frame.crc16_ok and frame.crc24_ok)


def test_detection_serialises():
    import json

    x = _capture()
    doc = json.loads(json.dumps(rx.find_bursts(x, FS)[0].to_dict()))
    assert doc["sample_start"] > 0 and 0.0 <= doc["score"] <= 1.0
    assert "cfo_hz" in doc and "zc147_score" in doc


def test_degenerate_inputs():
    assert rx.find_bursts(np.zeros(10, np.complex64), FS) == []
    assert rx.correlate_zc(np.zeros(10, np.complex64), 600, FS).size == 0
    assert rx.parse_frame(b"") is None
    assert rx.cp_coherence(np.zeros(100, np.complex64), -1, FS) == 0.0
    scores = np.array([0.0, 1.0, 0.0])
    assert rx.interpolate_peak(scores, 1) == pytest.approx(1.0)
    assert rx.interpolate_peak(scores, 0) == 0.0  # cannot interpolate at the edge


# ------------------------------------------------ coordinate ranges (H2)


def _frame_with(lat_deg, lon_deg, **kw):
    """A synthetic frame whose drone position is set to an exact pair."""
    from antsdr_toolkit.droneid import synth
    tx = synth.DroneIdTx(drone_lat=lat_deg, drone_lon=lon_deg, **kw)
    return synth.make_frame_bytes(tx)


@pytest.mark.parametrize(("lat", "lon"), [
    (51.9225, 4.47917),      # Rotterdam
    (-33.8688, 151.2093),    # Sydney: southern and eastern
    (0.0, 4.47917),          # on the equator, which is a real place
    (51.9225, 0.0),          # on the Greenwich meridian, likewise
])
def test_a_lone_zero_coordinate_is_a_place_not_a_missing_fix(lat, lon):
    """Only a zero *pair* means no fix. The equator has airspace over it."""
    from antsdr_toolkit.droneid import constants as C
    frame = _frame_with(lat, lon)
    import struct
    fields = struct.unpack("<BBBHH16siihhhhhhQiiiiBB19sBH", frame)
    lon_raw, lat_raw = fields[6], fields[7]
    assert lat_raw == pytest.approx(lat * C.COORD_SCALE, abs=1.0)
    assert lon_raw == pytest.approx(lon * C.COORD_SCALE, abs=1.0)


def test_the_encoder_and_decoder_share_one_coordinate_scale():
    """They previously carried their own, disagreeing by about 2.5 m.

    174533.0 in the receiver against 1e7 / 57.2957795785523 in the
    synthesiser: 4.3 parts in ten million, which the round-trip test's
    tolerance was too wide to notice.
    """
    import math

    from antsdr_toolkit.droneid import constants as C
    from antsdr_toolkit.droneid import synth
    assert synth._DEG_SCALE is C.COORD_SCALE
    assert C.COORD_SCALE == pytest.approx(1e7 * math.pi / 180.0, rel=1e-15)
    # The old receiver constant differed by enough to matter at Dutch latitudes.
    old = 174533.0
    error_m = 52.0 * (old / C.COORD_SCALE - 1.0) * 111_320
    assert abs(error_m) > 2.0, "the mismatch this test guards was smaller than thought"


# ------------------------------------- the product-type table's ceiling


def test_the_product_table_ceiling_is_stated_rather_than_hidden():
    """It stops at 70 and every DJI airframe since is above that.

    Found by an independent audit: a Mini 3 Pro decode would have rendered
    "unknown (73)", which reads like a failed decode when in fact everything
    except the model name resolved.
    """
    from antsdr_toolkit.droneid import constants as C
    assert C.MAX_KNOWN_PRODUCT_TYPE == 70
    assert C.PRODUCT_TYPES[C.MAX_KNOWN_PRODUCT_TYPE] == "Mini SE"
    # The limitation is documented where a reader will meet it: in the source
    # comment above the table, and in what product_name() returns.
    source = pathlib.Path(C.__file__).read_text(encoding="utf-8")
    assert "The table stops at 70" in source
    assert "Guessing here would" in source


def test_a_newer_model_says_it_is_newer_not_merely_unknown():
    from antsdr_toolkit.droneid import constants as C
    name = C.product_name(73)
    assert "73" in name
    assert "newer than the published table" in name
    assert "70" in name and "Mini SE" in name
    assert not name.startswith("unknown ("), "the old, misleading message is back"


def test_a_gap_below_the_ceiling_reads_differently_from_a_newer_model():
    """Two different situations, and conflating them loses information."""
    from antsdr_toolkit.droneid import constants as C
    gap = C.product_name(62)          # inside the range, absent from the table
    newer = C.product_name(90)        # above the range
    assert "gap in the published table" in gap
    assert "newer than the published table" in newer
    assert gap != newer


def test_a_known_product_type_is_unchanged():
    from antsdr_toolkit.droneid import constants as C
    assert C.product_name(63) == "Mini 2"
    assert C.product_name(58) == "Mavic Air 2"


def test_no_unsourced_model_names_were_invented():
    """The audit suggested adding 73, 75, 90 and others.

    No primary source reachable from this project confirms any of them:
    neither reference decoder ships a lookup table and Kismet's parser has
    none. A wrong model name on a detection is a confident false
    identification, which is worse than a missing one, so the gap stays.
    """
    from antsdr_toolkit.droneid import constants as C
    for code in (73, 75, 77, 82, 90):
        assert code not in C.PRODUCT_TYPES, f"{code} was added without a source"


# ------------------------------------- root-agnostic detection (audit item)


def _place(cfo_hz=0.0, snr_db=20.0, fs=15.36e6, n=400_000, t_start_s=0.005, seed=3):
    from antsdr_toolkit.droneid import synth
    return synth.place_burst(fs, n, t_start_s=t_start_s, cfo_hz=cfo_hz, snr_db=snr_db,
                             rng=np.random.default_rng(seed)), round(t_start_s * fs)


@pytest.mark.parametrize("cfo", [0.0, 2e3, 5e3, -7e3, 9e3, 14e3, 30e3, 60e3, 120e3, -120e3])
def test_the_root_agnostic_detector_finds_the_burst_at_every_offset(cfo):
    """Detection must not depend on knowing the Zadoff-Chu root.

    The fixed root-600 matched filter is an OcuSync 2 pilot. OcuSync 3 is
    reported to use a different pair and an OcuSync 4 variant to vary its
    roots frame to frame, so a fixed-root gate is blind to the generations a
    modern fleet flies, and it fails silently.
    """
    from antsdr_toolkit.droneid import receiver as rx
    x, truth = _place(cfo_hz=cfo)
    found = rx.find_bursts_cp(x, 15.36e6)
    assert len(found) == 1, f"{len(found)} detections at {cfo/1e3:g} kHz"
    assert found[0].sample_start == truth
    assert found[0].root_agnostic is True
    assert found[0].confirm_score > 0.9


@pytest.mark.parametrize("cfo", [0.0, 5e3, 9e3, 30e3, 120e3])
def test_the_root_is_identified_once_the_offset_is_removed(cfo):
    """A matched filter decorrelates under an offset, so correct it first."""
    from antsdr_toolkit.droneid import receiver as rx
    x, _truth = _place(cfo_hz=cfo)
    found = rx.find_bursts_cp(x, 15.36e6)
    assert found[0].zc_root == 600
    assert found[0].cfo_hz == pytest.approx(cfo, abs=100.0)


def test_the_symbol_walk_uses_the_real_schedule_not_a_fixed_stride():
    """The bug this guards cost 2192 samples, which is not a random number.

    The prefixes run 80, then seven of 72, then 80 at 15.36 MSPS. A fixed
    stride of 1104 accumulates 8 samples of error per symbol and lands exactly
    one Zadoff-Chu-to-Zadoff-Chu gap out, so the second pilot is read as the
    first and the root is reported as 147 instead of 600. It looked like a
    successful decode.
    """
    from antsdr_toolkit.droneid import constants as C
    from antsdr_toolkit.droneid import receiver as rx

    fs = 15.36e6
    starts = rx._symbol_starts_before(100_000, fs)
    assert len(starts) == len(C.cp_schedule(fs))
    steps = -np.diff(starts)
    assert steps[0] == C.cp_schedule(fs)[0] + C.fft_size(fs)
    assert len(set(steps.tolist())) > 1, "the schedule is not uniform and the walk must not be"
    # And the true start is reachable from any interior symbol boundary.
    boundary = 100_000 + C.cp_schedule(fs)[0] + C.fft_size(fs)
    assert 100_000 in rx._symbol_starts_before(boundary, fs)


def test_a_root_is_only_claimed_when_it_wins_decisively():
    """Different roots cross-correlate at 1/sqrt(601) = 0.04, so a real match
    beats the runner-up more than twentyfold. Two near-equal scores mean
    neither matched, and None is the honest answer."""
    from antsdr_toolkit.droneid import receiver as rx
    assert rx.ROOT_MARGIN < 1.0
    rng = np.random.default_rng(0)
    noise = ((rng.standard_normal(40_000) + 1j * rng.standard_normal(40_000))
             / np.sqrt(2)).astype(np.complex64)
    root, score = rx.estimate_zc_root(noise, 100, 15.36e6)
    assert root is None and score < 0.2


def test_an_unrecognised_root_is_still_a_detection():
    """A burst matching no published root is the interesting case, not a miss."""
    from antsdr_toolkit.droneid import receiver as rx
    x, truth = _place()
    found = rx.find_bursts_cp(x, 15.36e6, scan_min=0.2)
    assert found and found[0].sample_start == truth
    # The field is optional, so a None root must not break serialisation.
    row = found[0].to_dict()
    assert isinstance(row, dict)


def test_the_prefix_offset_estimator_has_the_right_sign():
    """A sign error here is invisible whenever the offset is near a multiple
    of the 15 kHz subcarrier spacing, which is where a lazy test would look."""
    from antsdr_toolkit.droneid import receiver as rx
    for cfo in (2e3, -3e3, 6e3):
        x, truth = _place(cfo_hz=cfo)
        estimate, ambiguity = rx.cfo_from_prefix(x, truth, 15.36e6)
        assert ambiguity == pytest.approx(15e3, rel=1e-6)
        assert estimate == pytest.approx(cfo, abs=150.0), f"sign or scale wrong at {cfo}"


def test_the_prefix_estimator_wraps_and_says_so():
    """Beyond half a subcarrier the estimate is aliased, by construction."""
    from antsdr_toolkit.droneid import receiver as rx
    x, truth = _place(cfo_hz=30e3)
    estimate, ambiguity = rx.cfo_from_prefix(x, truth, 15.36e6)
    assert abs(estimate) <= ambiguity / 2 + 1.0
    assert estimate == pytest.approx(0.0, abs=200.0)   # 30 kHz is 2 whole wraps


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_noise_produces_no_root_agnostic_detections(seed):
    from antsdr_toolkit.droneid import receiver as rx
    rng = np.random.default_rng(seed)
    noise = ((rng.standard_normal(600_000) + 1j * rng.standard_normal(600_000))
             / np.sqrt(2)).astype(np.complex64)
    assert rx.find_bursts_cp(noise, 15.36e6) == []


def test_two_bursts_are_two_detections_not_eighteen():
    """One burst raises the profile at all nine of its symbol boundaries."""
    from antsdr_toolkit.droneid import constants as C
    from antsdr_toolkit.droneid import receiver as rx
    from antsdr_toolkit.droneid import synth

    fs = 15.36e6
    x, first = _place(n=600_000)
    burst = synth.make_burst(fs, rng=np.random.default_rng(9))
    power = (C.occupied_bandwidth_hz() / fs) * 10 ** (20 / 10)
    second = round(0.025 * fs)
    x[second:second + burst.size] += (burst * np.sqrt(power)).astype(np.complex64)
    found = rx.find_bursts_cp(x, fs)
    assert [d.sample_start for d in found] == [first, second]


def test_the_root_agnostic_path_works_at_30_msps():
    from antsdr_toolkit.droneid import receiver as rx
    fs = 30.72e6
    x, truth = _place(cfo_hz=40e3, fs=fs, n=800_000, seed=5)
    found = rx.find_bursts_cp(x, fs)
    assert len(found) == 1 and found[0].sample_start == truth
    assert found[0].zc_root == 600


def test_both_gates_report_a_root_so_merging_never_loses_it():
    """The matched filter knows its root by construction; the other measures it."""
    from antsdr_toolkit.droneid import receiver as rx
    x, _truth = _place(cfo_hz=60e3, snr_db=25.0, seed=6)
    zc = rx.find_bursts(x, 15.36e6)
    cp = rx.find_bursts_cp(x, 15.36e6)
    assert zc and cp
    assert zc[0].zc_root == 600 and zc[0].root_agnostic is False
    assert cp[0].zc_root == 600 and cp[0].root_agnostic is True


@pytest.mark.parametrize("method", ["zc", "cp", "both"])
def test_every_detection_method_decodes_the_same_frame(method):
    from antsdr_toolkit.droneid import receiver as rx
    x, _truth = _place(cfo_hz=60e3, snr_db=25.0, seed=6)
    results = rx.process(x, 15.36e6, method=method)
    assert len(results) == 1
    _detection, frame = results[0]
    assert frame is not None and frame.crc24_ok and frame.crc16_ok
    assert frame.serial == "TEST0123456789AB"


def test_both_does_not_report_one_burst_twice():
    """The two gates find the same burst; merging must dedupe it."""
    from antsdr_toolkit.droneid import receiver as rx
    x, _truth = _place(cfo_hz=10e3, snr_db=25.0, seed=6)
    assert len(rx.process(x, 15.36e6, method="both")) == 1


def test_an_unknown_method_is_refused():
    from antsdr_toolkit.droneid import receiver as rx
    with pytest.raises(ValueError, match="must be 'zc', 'cp' or 'both'"):
        rx.process(np.zeros(1000, dtype=np.complex64), 15.36e6, method="magic")
