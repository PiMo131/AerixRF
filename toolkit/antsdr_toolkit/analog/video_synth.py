"""Synthetic composite video, so the analog chain can be tested.

Two levels of fidelity, for two different jobs.

:func:`composite_video` repeats one line shape and is enough to exercise
*detection*: the line rate, the envelope and the occupied bandwidth are all
correct, so :func:`~antsdr_toolkit.analog.fpv.detect_fpv` and
:func:`~antsdr_toolkit.analog.fpv.sync_lock` have something real to measure.
It carries no vertical sync and no picture, so nothing can be decoded from it.

:func:`composite_from_image` builds a complete field sequence around an actual
image: vertical sync with its broad pulses, the equalising pulses either side,
the remaining blanked lines, and then one active line per image row.  Passing
it through :func:`fm_modulate` and back through
:func:`~antsdr_toolkit.analog.video_decode.decode_from_iq` returns the picture,
which is the only way to know the decoder works without an analog transmitter
on the bench.

Two deliberate simplifications, both stated because they limit what a passing
test proves:

* **The interlace is segmented, not true 2:1.**  Alternate image rows go to
  alternate fields, but every field starts on a whole line boundary.  Real
  interlace offsets the second field by half a line, and that offset is how a
  television knows which field is which.  A decoder that relies on it would
  pass here and fail on air; this toolkit's decoder deliberately does not.
* **No colour subcarrier and no audio subcarriers.**  The luma is the whole
  signal, so this material cannot show whether chroma leaks into the picture,
  which on a real capture it does.

Test and calibration material only.  It is never transmitted: the toolkit is
receive-only (``antsdr/docs/decisions/ADR-0001``).
"""

from __future__ import annotations

import numpy as np

from .fpv import BLANKING_LEVEL, QUAD_DEMOD_DIVISOR_HZ, SYNC_LEVEL, WHITE_LEVEL

__all__ = [
    "STANDARDS",
    "composite_from_image",
    "composite_video",
    "fm_modulate",
    "test_pattern",
    "video_carrier",
    "video_from_image",
]

#: Line timing of each standard: (line, sync, back porch, active, front porch)
#: in seconds, and the number of active lines per field.
STANDARDS = {
    "ntsc": (63.5e-6, 4.7e-6, 4.7e-6, 52.6e-6, 1.5e-6, 240),
    "pal": (64.0e-6, 4.7e-6, 5.7e-6, 51.95e-6, 1.65e-6, 288),
}

#: Lines of vertical blanking per field, and how the vertical interval is
#: built: three lines of pre-equalising pulses, three of broad (vertical sync)
#: pulses, three of post-equalising, then plain blanked lines to make up the
#: count. The broad pulses are what a sync separator integrates to find the
#: field, so their width is the number that matters here.
BLANKING_LINES = {"ntsc": 22, "pal": 24}
EQUALISING_S = 2.3e-6
BROAD_S = 27.1e-6

#: Backwards-compatible alias; the level itself lives in :mod:`.fpv` so the
#: decoder and the synthesiser cannot drift apart.
BLANK_LEVEL = BLANKING_LEVEL

#: Blanking to peak white, the excursion one unit of picture occupies. Kept
#: equal to :data:`video_decode.VIDEO_SPAN` so a round trip is an identity.
_SPAN = WHITE_LEVEL - BLANKING_LEVEL


def composite_video(sample_rate_hz: float, duration_s: float, *,
                    standard: str = "ntsc",
                    rng: np.random.Generator | None = None) -> np.ndarray:
    """A composite video waveform of the requested length, without vertical sync.

    The active line is filled with a smooth ramp plus a little noise, which is
    enough to give the modulated carrier a realistic bandwidth without
    pretending to be a picture. Use :func:`composite_from_image` when the test
    needs something a decoder can actually resolve.
    """
    if standard not in STANDARDS:
        raise ValueError(f"standard must be one of {tuple(STANDARDS)}, got {standard!r}")
    rng = np.random.default_rng(0) if rng is None else rng
    fs = float(sample_rate_hz)
    line_s, sync_s, back_s, _active_s, front_s, _lines = STANDARDS[standard]
    n_line = round(line_s * fs)
    n_sync = round(sync_s * fs)
    n_back = round(back_s * fs)
    n_front = round(front_s * fs)
    n_active = max(n_line - n_sync - n_back - n_front, 1)

    line = np.empty(n_line, dtype=np.float64)
    line[:n_sync] = SYNC_LEVEL
    line[n_sync:n_sync + n_back] = BLANKING_LEVEL
    # The picture starts at blanking rather than at the decoder's nominal
    # black level, which sits *below* the sync threshold: starting there would
    # put a second threshold crossing in every line and halve the lock score.
    ramp = np.linspace(BLANKING_LEVEL, WHITE_LEVEL, n_active)
    line[n_sync + n_back:n_sync + n_back + n_active] = ramp
    line[n_sync + n_back + n_active:] = BLANKING_LEVEL

    n_total = round(float(duration_s) * fs)
    repeats = int(np.ceil(n_total / n_line)) + 1
    field = np.tile(line, repeats)[:n_total]
    return field + 0.002 * rng.standard_normal(n_total)


def test_pattern(height: int, width: int) -> np.ndarray:
    """A picture with features a decoder can be checked against.

    Grey bars across the top third give known horizontal steps, a vertical
    gradient fills the middle, and a white box on the left of the bottom third
    breaks the symmetry so a vertically flipped or half-line-shifted decode is
    obvious rather than plausible. Values are 0 (black) to 1 (peak white).
    """
    h, w = int(height), int(width)
    if h < 6 or w < 8:
        raise ValueError(f"pattern needs at least 6x8, got {h}x{w}")
    image = np.zeros((h, w), dtype=np.float64)
    third = h // 3

    bars = np.linspace(0.0, 1.0, 8, endpoint=True)
    image[:third] = bars[np.minimum((np.arange(w) * 8) // w, 7)]
    image[third:2 * third] = np.linspace(0.0, 1.0, 2 * third - third)[:, None]
    image[2 * third:] = 0.15
    image[2 * third + 1:h - 1, 1:max(2, w // 4)] = 1.0
    return image


def _line(n_line: int, n_sync: int, n_back: int, n_front: int,
          picture: np.ndarray | None) -> np.ndarray:
    """One active or blanked line at the standard's levels."""
    line = np.full(n_line, BLANKING_LEVEL, dtype=np.float64)
    line[:n_sync] = SYNC_LEVEL
    if picture is not None:
        n_active = n_line - n_sync - n_back - n_front
        if n_active > 0:
            resampled = np.interp(np.linspace(0.0, picture.size - 1.0, n_active),
                                  np.arange(picture.size), picture)
            line[n_sync + n_back:n_sync + n_back + n_active] = (
                BLANKING_LEVEL + np.clip(resampled, 0.0, 1.0) * _SPAN)
    return line


def _pulse_train(n_line: int, n_low: int) -> np.ndarray:
    """One line carrying two half-line pulses, as the vertical interval uses.

    Equalising and broad pulses differ only in how long they stay low, which
    is exactly what the decoder's integrator measures.
    """
    line = np.full(n_line, BLANKING_LEVEL, dtype=np.float64)
    half = n_line // 2
    low = max(1, min(int(n_low), half - 1))
    line[:low] = SYNC_LEVEL
    line[half:half + low] = SYNC_LEVEL
    return line


def composite_from_image(
    image: np.ndarray,
    sample_rate_hz: float,
    *,
    standard: str = "ntsc",
    n_fields: int = 2,
    interlace: bool = True,
    rng: np.random.Generator | None = None,
    noise: float = 0.002,
) -> np.ndarray:
    """A full field sequence carrying ``image``, vertical sync included.

    ``image`` is a 2-D array in 0..1. With ``interlace`` the even rows go to
    the first field and the odd rows to the second, so a full frame needs
    ``2 * active_lines_per_field`` rows; without it every field carries the
    whole image resampled to the field height.

    ``n_fields`` fields are emitted, cycling through the parities, so
    ``n_fields=2`` is one frame and a decoder's :func:`weave` can be tested.
    """
    if standard not in STANDARDS:
        raise ValueError(f"standard must be one of {tuple(STANDARDS)}, got {standard!r}")
    picture = np.asarray(image, dtype=np.float64)
    if picture.ndim != 2 or picture.size == 0:
        raise ValueError(f"image must be a non-empty 2-D array, got shape {picture.shape}")
    if int(n_fields) < 1:
        raise ValueError(f"n_fields must be positive, got {n_fields}")
    rng = np.random.default_rng(0) if rng is None else rng

    fs = float(sample_rate_hz)
    line_s, sync_s, back_s, _active_s, front_s, active_lines = STANDARDS[standard]
    n_line = round(line_s * fs)
    n_sync = round(sync_s * fs)
    n_back = round(back_s * fs)
    n_front = round(front_s * fs)
    if n_sync < 1 or n_back < 1 or n_line - n_sync - n_back - n_front < 2:
        # Below about 1 MSPS the sync pulse and back porch round to zero
        # samples and the line comes out with no sync at all, which looks
        # like a signal and decodes to nothing.
        raise ValueError(
            f"{fs / 1e6:g} MSPS is too low to render a {standard} line: "
            f"sync would be {n_sync} and the back porch {n_back} samples")

    n_equal = max(1, round(EQUALISING_S * fs))
    n_broad = max(1, round(BROAD_S * fs))
    blanked = _line(n_line, n_sync, n_back, n_front, None)
    equalising = _pulse_train(n_line, n_equal)
    broad = _pulse_train(n_line, n_broad)
    n_blank_lines = BLANKING_LINES[standard]

    chunks: list[np.ndarray] = []
    for field_index in range(int(n_fields)):
        # Vertical interval: 3 equalising, 3 broad, 3 equalising, then plain
        # blanked lines. The decoder finds the field on the broad pulses.
        chunks.extend([equalising] * 3)
        chunks.extend([broad] * 3)
        chunks.extend([equalising] * 3)
        chunks.extend([blanked] * max(0, n_blank_lines - 9))

        if interlace:
            rows = picture[field_index % 2::2]
        else:
            rows = picture
        if rows.shape[0] == 0:
            rows = picture
        # Resample the field's rows to the standard's active line count.
        row_index = np.linspace(0.0, rows.shape[0] - 1.0, active_lines)
        for position in row_index:
            lo = int(np.floor(position))
            hi = min(lo + 1, rows.shape[0] - 1)
            frac = position - lo
            row = rows[lo] * (1.0 - frac) + rows[hi] * frac
            chunks.append(_line(n_line, n_sync, n_back, n_front, row))

    out = np.concatenate(chunks)
    if noise:
        out = out + float(noise) * rng.standard_normal(out.size)
    return out


def fm_modulate(baseband: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    """Frequency-modulate at the scaling :func:`..fpv.fm_demod` inverts."""
    x = np.asarray(baseband, dtype=np.float64).ravel()
    fs = float(sample_rate_hz)
    gain = 2.0 * np.pi * QUAD_DEMOD_DIVISOR_HZ / fs
    phase = np.cumsum(x * gain)
    return np.exp(1j * phase).astype(np.complex64)


def video_carrier(sample_rate_hz: float, duration_s: float, *,
                  standard: str = "ntsc",
                  rng: np.random.Generator | None = None) -> np.ndarray:
    """A ready-made analog FPV carrier: composite video, frequency-modulated."""
    baseband = composite_video(sample_rate_hz, duration_s, standard=standard, rng=rng)
    return fm_modulate(baseband, sample_rate_hz)


def video_from_image(image: np.ndarray, sample_rate_hz: float, *,
                     standard: str = "ntsc", n_fields: int = 2,
                     interlace: bool = True,
                     rng: np.random.Generator | None = None,
                     noise: float = 0.002) -> np.ndarray:
    """A modulated carrier carrying ``image``: the decoder's round-trip input."""
    baseband = composite_from_image(image, sample_rate_hz, standard=standard,
                                    n_fields=n_fields, interlace=interlace,
                                    rng=rng, noise=noise)
    return fm_modulate(baseband, sample_rate_hz)
