"""Analog FPV video decoding: does a picture survive the round trip?

The whole point of the synthesiser is that these tests can assert on picture
content rather than on signal statistics.  A decoder that locks, counts the
right number of lines and returns a plausible-looking grey rectangle is
useless, so every test here checks something about the image itself.
"""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.analog import video_decode as vd
from antsdr_toolkit.analog import video_synth as vs

FS = 20e6


def _round_trip(standard: str, height: int, *, noise: float = 0.002,
                seed: int = 3, width: int = 320):
    source = vs.test_pattern(height, width)
    iq = vs.video_from_image(source, FS, standard=standard, n_fields=2,
                             noise=noise, rng=np.random.default_rng(seed))
    fields, name = vd.decode_from_iq(iq, FS, width=width)
    return source, fields, name


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a.ravel(), b.ravel())[0, 1])


@pytest.mark.parametrize(("standard", "height"), [("ntsc", 480), ("pal", 576)])
def test_picture_survives_the_round_trip(standard, height):
    """Image to composite video to FM and back returns the same picture."""
    source, fields, name = _round_trip(standard, height)
    assert name == standard
    assert len(fields) == 2
    frame = next(vd.weave(fields))
    assert frame.shape == source.shape
    assert _correlation(frame, source) > 0.99
    assert np.abs(frame - source).mean() < 0.03


@pytest.mark.parametrize(("standard", "height"), [("ntsc", 480), ("pal", 576)])
def test_no_row_is_displaced(standard, height):
    """Every row lands where it belongs, not one line up or six.

    A whole-field shift is the characteristic failure of counting the vertical
    interval's pulses as lines, and it barely moves the mean error while
    ruining the picture.  Checking the worst row catches it; checking the mean
    does not.
    """
    source, fields, _name = _round_trip(standard, height)
    frame = next(vd.weave(fields))
    row_error = np.abs(frame - source).mean(axis=1)
    assert row_error.max() < 0.1, f"worst row {int(row_error.argmax())} at {row_error.max():.3f}"


def test_the_asymmetric_feature_stays_where_it_was_put():
    """The test pattern's white box is bottom-left, and must decode there.

    A vertically flipped or field-swapped decode still correlates well against
    a mostly symmetric pattern.  This is the assertion that does not.
    """
    source, fields, _name = _round_trip("ntsc", 480)
    frame = next(vd.weave(fields))
    bottom_left = frame[330:470, 2:70].mean()
    top_left = frame[10:80, 2:70].mean()
    assert bottom_left > 0.9, f"box missing from bottom left: {bottom_left:.3f}"
    assert top_left < 0.2, f"box appeared in the top left: {top_left:.3f}"
    assert source[330:470, 2:70].mean() > 0.9


def test_grey_bars_decode_as_distinct_monotonic_steps():
    """The eight bars come back in order and separated."""
    _source, fields, _name = _round_trip("ntsc", 480)
    frame = next(vd.weave(fields))
    # Sample the middle of each bar, away from the low-pass ringing at edges.
    levels = np.array([frame[10:30, index * 40 + 20].mean() for index in range(8)])
    assert np.all(np.diff(levels) > 0.05), f"bars not monotonic: {np.round(levels, 3)}"
    assert levels[0] < 0.1 and levels[-1] > 0.9


def test_it_survives_three_times_the_noise():
    """Degrades rather than falling over."""
    source, fields, name = _round_trip("ntsc", 480, noise=0.006)
    assert name == "ntsc"
    frame = next(vd.weave(fields))
    assert _correlation(frame, source) > 0.95


# ------------------------------------------------------------------ mechanics


def test_the_width_gate_rejects_the_vertical_interval_and_keeps_the_lines():
    """Both impostors are removed and every real line survives.

    NTSC here: two fields of 240 active plus 13 blanked lines is 506 real sync
    pulses.  The ungated count is higher because the vertical interval's
    equalising and broad pulses are counted, and because noise on black
    picture content dips under the threshold.
    """
    source = vs.test_pattern(480, 320)
    iq = vs.video_from_image(source, FS, standard="ntsc", n_fields=2)
    demod = vd.fm_demod(iq, FS, lowpass_hz=4e6)
    ungated = vd.sync_edges(demod, FS, "ntsc", width_filter=False)
    gated = vd.sync_edges(demod, FS, "ntsc")
    assert gated.size < ungated.size
    assert gated.size == pytest.approx(506, abs=4)
    # What survives is spaced one line apart, not half a line.
    spacing = np.diff(gated) / (vd.STANDARDS["ntsc"].line_period_s * FS)
    assert np.median(spacing) == pytest.approx(1.0, abs=0.01)
    assert (spacing < 0.75).sum() == 0, "half-line pulses got through the gate"


def test_the_sync_integrator_separates_broad_pulses_from_lines():
    """Ordinary lines read about a 7 % duty cycle, vertical sync far more."""
    iq = vs.video_from_image(vs.test_pattern(480, 320), FS, standard="ntsc", n_fields=2)
    demod = vd.fm_demod(iq, FS, lowpass_hz=4e6)
    metric = vd.sync_metric(demod, FS, "ntsc")
    assert np.median(metric) < 0.2
    assert metric.max() > 0.6
    assert vd.field_starts(demod, FS, "ntsc").size == 2


def test_pulse_widths_measures_the_three_pulse_shapes():
    """Sync, equalising and broad pulses are three separated populations."""
    iq = vs.video_from_image(vs.test_pattern(480, 320), FS, standard="ntsc", n_fields=2)
    demod = vd.fm_demod(iq, FS, lowpass_hz=4e6)
    edges = vd.sync_edges(demod, FS, "ntsc", width_filter=False)
    widths_us = vd.pulse_widths(demod, edges) / FS * 1e6
    # The synthesiser writes 4.7 us sync, 2.3 us equalising, 27.1 us broad.
    assert ((widths_us > 4.0) & (widths_us < 5.5)).sum() > 400
    assert ((widths_us > 1.8) & (widths_us < 3.0)).sum() >= 12
    assert (widths_us > 20.0).sum() >= 6


def test_a_line_is_black_referenced_on_its_own_back_porch():
    """A DC offset on the whole capture does not change the picture.

    This is what per-line clamping buys: an FM discriminator's output wanders,
    and without restoring black on the back porch the picture would wander
    with it.
    """
    source = vs.test_pattern(480, 320)
    baseband = vs.composite_from_image(source, FS, standard="ntsc", n_fields=2)
    shifted = baseband + 0.004
    plain = vd.decode_fields(baseband, FS, "ntsc", width=320)
    offset = vd.decode_fields(shifted, FS, "ntsc", width=320)
    assert len(plain) == len(offset) == 2
    assert np.abs(plain[0].image - offset[0].image).mean() < 0.01


def test_identify_standard_tells_ntsc_from_pal():
    """0.8 % apart in line rate, and the answer has to be one or the other."""
    for standard in ("ntsc", "pal"):
        iq = vs.video_from_image(vs.test_pattern(480, 320), FS, standard=standard, n_fields=2)
        demod = vd.fm_demod(iq, FS, lowpass_hz=4e6)
        name, period = vd.identify_standard(demod, FS)
        assert name == standard
        assert period == pytest.approx(vd.STANDARDS[standard].line_period_s, rel=0.003)


def test_noise_alone_yields_no_picture():
    """No lock, no frames. Slicing a picture out of noise is worse than none."""
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(400_000) + 1j * rng.standard_normal(400_000)) / np.sqrt(2)
    fields, name = vd.decode_from_iq(noise.astype(np.complex64), FS)
    assert name is None
    assert fields == []


def test_a_carrier_without_vertical_sync_yields_no_fields():
    """``composite_video`` has line sync but no field structure."""
    iq = vs.video_carrier(FS, 0.02, standard="ntsc")
    demod = vd.fm_demod(iq, FS, lowpass_hz=4e6)
    assert vd.sync_edges(demod, FS, "ntsc").size > 200      # lines are there
    assert vd.field_starts(demod, FS, "ntsc").size == 0     # fields are not
    assert vd.decode_fields(demod, FS, "ntsc") == []


# ------------------------------------------------------------------ image out


def test_write_png_is_a_readable_greyscale_png(tmp_path):
    """Hand-rolled PNG, so check the container as well as the pixels."""
    import struct
    import zlib

    image = vs.test_pattern(64, 96)
    path = vd.write_png(str(tmp_path / "frame.png"), image)
    with open(path, "rb") as handle:
        blob = handle.read()
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    length = struct.unpack(">I", blob[8:12])[0]
    assert blob[12:16] == b"IHDR"
    width, height, depth, colour = struct.unpack(">IIBB", blob[16:16 + 10])
    assert (width, height, depth, colour) == (96, 64, 8, 0)
    assert blob[-12:] == struct.pack(">I", 0) + b"IEND" + struct.pack(
        ">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    assert length == 13


def test_write_pgm_round_trips_the_pixels(tmp_path):
    image = vs.test_pattern(32, 64)
    path = vd.write_pgm(str(tmp_path / "frame.pgm"), image)
    with open(path, "rb") as handle:
        blob = handle.read()
    assert blob.startswith(b"P5\n64 32\n255\n")
    pixels = np.frombuffer(blob[len(b"P5\n64 32\n255\n"):], dtype=np.uint8)
    assert pixels.size == 32 * 64
    assert np.abs(pixels.reshape(32, 64) / 255.0 - image).max() < 0.01


@pytest.mark.parametrize("bad", [np.zeros((0, 4)), np.zeros(8), np.zeros((2, 2, 2))])
def test_image_writers_reject_what_is_not_an_image(tmp_path, bad):
    with pytest.raises(ValueError):
        vd.write_png(str(tmp_path / "x.png"), bad)


# ------------------------------------------------------------------ contracts


def test_weave_interleaves_and_needs_matching_shapes():
    a = vd.DecodedField(np.zeros((4, 3)), 0.0, 4, "ntsc")
    b = vd.DecodedField(np.ones((4, 3)), 0.1, 4, "ntsc")
    frame = next(vd.weave([a, b]))
    assert frame.shape == (8, 3)
    assert np.all(frame[0::2] == 0.0) and np.all(frame[1::2] == 1.0)
    odd = vd.DecodedField(np.ones((5, 3)), 0.2, 5, "ntsc")
    assert list(vd.weave([a, odd])) == []
    assert list(vd.weave([a])) == []


def test_decoded_field_reports_incompleteness():
    full = vd.DecodedField(np.zeros((240, 8)), 0.0, 240, "ntsc")
    short = vd.DecodedField(np.zeros((240, 8)), 0.0, 100, "ntsc")
    assert full.complete and not short.complete
    assert short.to_dict()["n_lines_found"] == 100


@pytest.mark.parametrize("call", [
    lambda: vd.decode_fields(np.zeros(100), FS, "secam"),
    lambda: vd.decode_fields(np.zeros(100), FS, "ntsc", width=0),
    lambda: vs.composite_from_image(np.zeros((4, 4)), FS, standard="secam"),
    lambda: vs.composite_from_image(np.zeros(4), FS),
    lambda: vs.composite_from_image(np.zeros((4, 4)), FS, n_fields=0),
    lambda: vs.test_pattern(2, 2),
])
def test_bad_arguments_raise(call):
    with pytest.raises(ValueError):
        call()


def test_a_sample_rate_too_low_to_render_a_line_is_refused():
    with pytest.raises(ValueError, match="too low"):
        vs.composite_from_image(np.zeros((8, 8)), 100e3, standard="ntsc")


def test_slice_level_sits_between_blanking_and_the_sync_tip():
    """The reason the decoder does not use ``fpv.SYNC_THRESHOLD``."""
    from antsdr_toolkit.analog import fpv
    assert fpv.SYNC_LEVEL < vd.SLICE_LEVEL < fpv.BLANKING_LEVEL
    # Midway, so black and sync are equally far from it.
    assert vd.SLICE_LEVEL - fpv.SYNC_LEVEL == pytest.approx(
        fpv.BLANKING_LEVEL - vd.SLICE_LEVEL)
    # And further from black than the detector's own threshold is.
    assert (fpv.BLANKING_LEVEL - vd.SLICE_LEVEL) > (fpv.BLANKING_LEVEL - fpv.SYNC_THRESHOLD)
