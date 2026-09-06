"""What only a real capture could have caught.

Every bug pinned here survived a full synthetic test suite, and each survived
for the same reason: a synthesised burst starts exactly where the synthesiser
put it and is read back by the same code that wrote it. A round trip cannot
see a timing error, and it cannot see two fields swapped as long as both ends
swap them together. These tests are written to fail on the mistakes rather
than to confirm the round trip.

The measurements behind them are in ``antsdr/research/validation/``.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from antsdr_toolkit.droneid import constants as C
from antsdr_toolkit.droneid import receiver as rx
from antsdr_toolkit.droneid import synth, tune

FS = 15.36e6


def _capture(offset_hz: float = 0.0, pad: int = 4000) -> np.ndarray:
    burst = synth.make_burst(sample_rate_hz=FS)
    zeros = np.zeros(pad, dtype=np.complex64)
    x = np.concatenate([zeros, burst, zeros]).astype(np.complex64)
    if offset_hz:
        n = np.arange(x.size, dtype=np.float64)
        x = (x * np.exp(2j * np.pi * float(offset_hz) * n / FS)).astype(np.complex64)
    return x


# --- the frequency offset -------------------------------------------------

@pytest.mark.parametrize("offset_hz", [0.0, 3e3, -6.2e3, 15e3, -30e3, 45.5e3,
                                       -75e3, 120e3, -135e3, 300e3])
def test_the_whole_offset_is_recovered_not_just_its_fraction(offset_hz):
    """A wrap is a wrap whichever gate found the burst."""
    x = _capture(offset_hz)
    for method in ("zc", "cp"):
        results = rx.process(x, FS, threshold=0.5, method=method)
        assert results, f"{method} found no burst at {offset_hz:+.0f} Hz"
        detection, frame = results[0]
        assert abs(detection.cfo_hz - offset_hz) < 200.0, (
            f"{method} reported {detection.cfo_hz:+.0f} Hz for {offset_hz:+.0f} Hz")
        assert frame is not None and frame.crc24_ok and frame.crc16_ok


def test_a_timing_error_is_not_reported_as_a_frequency():
    """The trap that cost every frame of the first real capture.

    A Zadoff-Chu correlation slides in time under a frequency offset, so a
    burst read a few samples early scores best at an offset that is not there.
    Starting three samples early must not move the reported offset by the
    26 kHz that three samples of slide are worth.
    """
    x = _capture()
    detection = rx.find_bursts_cp(x, FS)[0]
    honest = rx.resolve_cfo(x, detection.sample_start, FS)
    early = rx.resolve_cfo(x, detection.sample_start - 3, FS)
    assert abs(early - honest) < 500.0, (
        f"three samples of timing error moved the offset by {early - honest:+.0f} Hz")


def test_the_integer_part_comes_from_where_the_band_is():
    x = _capture(45e3)  # exactly three subcarriers
    start = rx.find_bursts_cp(x, FS)[0].sample_start
    fine, spacing = rx.cfo_from_prefix(x, start, FS)
    assert abs(fine) < spacing / 2 + 1.0, "the prefix estimate should be the fraction"
    window = x[start:start + C.burst_length(FS)]
    turns = np.exp(-2j * np.pi * fine * np.arange(window.size) / FS)
    assert rx.integer_offset_bins(window * turns, 0, FS) == 3


# --- the vertical fields --------------------------------------------------

def test_altitude_precedes_height_and_both_are_feet():
    """Pinned by byte offset, because a round trip cannot see this.

    The frame carries altitude at bytes 31-32 and height at 33-34, in feet
    (3 header + 2 sequence + 2 state + 16 serial + 4 lon + 4 lat = 31).
    Both ends of this toolkit had them the other way round and unconverted,
    and every synthetic test passed. The numbers below are the ones that
    reproduce the height RUB-SysSec published for their ``mavic_air_2``
    capture; see ``antsdr/research/validation/``.
    """
    tx = synth.DroneIdTx(height_m=12.8, altitude_m=43.0)
    raw = synth.make_frame_bytes(tx)
    altitude_raw, height_raw = struct.unpack_from("<hh", raw, 31)
    assert (altitude_raw, height_raw) == (141, 42)

    frame = rx.parse_frame(raw.ljust(C.PAYLOAD_BYTES, b"\x00"))
    assert frame is not None
    assert frame.height_m == pytest.approx(12.8, abs=0.02)
    # 43.0 m encodes as 141 ft, which reads back as 42.98 m: the field is a
    # whole number of feet, so a third of a metre is the finest it can carry.
    assert frame.altitude_m == pytest.approx(42.98, abs=0.02)
    assert frame.height_m < frame.altitude_m


def test_a_real_capture_field_layout():
    """The exact bytes of the RUB-SysSec ``mavic_air_2`` frame's two heights.

    141 and 42 as sent; 43.0 m and 12.80 m as read. The published figure for
    that flight is 12.8 m, which is the height and not the altitude: reading
    them the other way round claims the aircraft was 43 m up.
    """
    assert 141 / C.FEET_PER_METRE == pytest.approx(42.98, abs=0.01)
    assert 42 / C.FEET_PER_METRE == pytest.approx(12.80, abs=0.01)


# --- the channel estimate -------------------------------------------------

def test_the_channel_estimate_is_flat_across_the_burst():
    """One estimate for the whole burst, not a ramp fitted to two noisy ones.

    Extrapolating the pilots out to symbols 1 and 8 left an error floor that
    no amount of signal removed. The test is that a clean burst equalises to a
    constellation with no per-symbol spread: every data symbol should land the
    same distance from its ideal point.
    """
    x = _capture()
    detection = rx.find_bursts_cp(x, FS)[0]
    burst = x[detection.sample_start:detection.sample_start + C.burst_length(FS)]
    equalised = rx._equalise(rx._symbols(burst.astype(np.complex128), FS, False), FS, False)
    spread = []
    for index in C.data_symbol_indices():
        values = equalised[index]
        scale = np.sqrt(np.mean(np.abs(values) ** 2) / 2.0)
        ideal = scale * (np.sign(values.real) + 1j * np.sign(values.imag))
        spread.append(float(np.mean(np.abs(values - ideal)) / scale))
    assert max(spread) < 0.05, f"per-symbol error {max(spread):.3f} is not flat: {spread}"


# --- getting to the receiver at all ---------------------------------------

def test_a_wideband_capture_is_found_mixed_down_and_decoded():
    """The whole point of :mod:`~antsdr_toolkit.droneid.tune`.

    A burst 9.6 MHz off centre in a 50 MSPS recording is what a real capture
    looks like, and it was undecodable by this toolkit until the band search
    existed. The numbers here are the geometry of the RUB-SysSec captures.
    """
    rng = np.random.default_rng(11)
    wide_rate = 50e6
    burst = synth.make_burst(sample_rate_hz=FS)
    # Interpolate the 15.36 MSPS burst up to 50 MSPS and put it off centre.
    from scipy.signal import resample_poly

    up = resample_poly(burst.astype(np.complex128), 625, 192)
    x = (rng.normal(0, 0.02, 120_000) + 1j * rng.normal(0, 0.02, 120_000))
    at = 40_000
    x[at:at + up.size] += up
    n = np.arange(x.size, dtype=np.float64)
    x = (x * np.exp(2j * np.pi * 9.6e6 * n / wide_rate)).astype(np.complex64)

    centres = tune.centres_hz(x, wide_rate)
    assert centres, "the occupied band was not found"
    assert min(abs(c - 9.6e6) for c in centres) < 0.3e6

    decoded = []
    for _centre, band in tune.prepare(x, wide_rate):
        for _detection, frame in rx.process(band, FS, threshold=0.5, method="cp"):
            if frame is not None and frame.crc24_ok and frame.crc16_ok:
                decoded.append(frame)
    assert decoded, "found the band but decoded nothing in it"
    assert decoded[0].serial == synth.DEFAULT_TX.serial


def test_a_shoulder_is_not_reported_as_a_second_band():
    """Sliding a window onto one band makes every position on the way bright."""
    rng = np.random.default_rng(5)
    wide_rate = 50e6
    from scipy.signal import resample_poly

    up = resample_poly(synth.make_burst(sample_rate_hz=FS).astype(np.complex128), 625, 192)
    x = (rng.normal(0, 0.02, 200_000) + 1j * rng.normal(0, 0.02, 200_000))
    for at in (20_000, 60_000, 100_000):
        x[at:at + up.size] += up
    x = x.astype(np.complex64)
    centres = tune.centres_hz(x, wide_rate, max_centres=4, min_excess_db=0.0)
    assert len(centres) == 1, f"one emission reported as {len(centres)} bands: {centres}"


def test_an_empty_capture_yields_no_bands():
    rng = np.random.default_rng(7)
    noise = (rng.normal(0, 1, 100_000) + 1j * rng.normal(0, 1, 100_000)).astype(np.complex64)
    assert tune.centres_hz(noise, 50e6) == []


def test_resampling_is_exact_where_it_can_be():
    x = np.ones(50_000, dtype=np.complex64)
    out = tune.to_baseband(x, 50e6, 0.0, target_rate_hz=15.36e6)
    assert abs(out.size - 50_000 * 192 / 625) <= 2
    same = tune.to_baseband(x, FS, 0.0, target_rate_hz=FS)
    assert same.size == x.size
