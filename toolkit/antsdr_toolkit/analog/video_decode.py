"""Turn a demodulated analog FPV carrier into pictures.

:mod:`antsdr_toolkit.analog.fpv` answers "is there an analog video transmitter
here, and on which channel".  This module answers the next question: *what is
it showing*.  Analog 5.8 GHz FPV is wideband FM of a CVBS composite video
signal, which is the same 1930s waveform a television used, so once the FM is
discriminated the picture can be sliced out of it directly.

Why this is worth having
------------------------
It is the only link in the drone bands this toolkit can read end to end with
no keys, no reverse engineering and no cooperation from the manufacturer.  A
DJI OcuSync 4 downlink is encrypted; ExpressLRS has no open decoder; but an
analog FPV video signal is in the clear by construction, because the receiver
goggles are a dumb FM demodulator.

An analog air unit usually carries no GNSS and broadcasts no position, so the
picture is the observation.  In practice it is often more informative than a
position would be: most flight controllers burn an on-screen display into the
video, so the frame carries battery voltage, timer, RSSI and, on a rig with a
GPS module, the coordinates and home distance as text in the image.

How the picture is found
------------------------
The waveform is a sequence of lines.  Each begins with a horizontal sync pulse
about 4.7 us long at a level below black, then a back porch at blanking level,
then the active picture, then a front porch::

    -0.04 |__            sync tip
          |  |
    -0.015|  |___                          ____   blanking / back porch
          |      \\____   picture      ____/
    +0.06 |           \\_____________/            peak white

Two features carry the geometry:

* **Horizontal sync** is a falling edge through a threshold between blanking
  and the sync tip, once per line period (63.5 us for NTSC, 64.0 us for PAL).
  It says where each line starts.
* **Vertical sync** is a group of *broad* pulses that sit below the threshold
  for most of a line instead of 7 % of one.  Sliding a window half a line long
  and measuring the fraction of it below threshold separates them cleanly:
  ordinary lines read about 0.07, broad pulses about 0.85.  This is what a
  sync separator chip does with an RC integrator, and it is robust because it
  does not depend on counting equalising pulses.

Levels are restored per line rather than globally.  The back porch of each
line is blanking by definition, so its median is that line's black reference;
subtracting it removes the slow DC wander an FM discriminator always has, and
is why a picture comes out level even when the carrier drifts.

What this does not do
---------------------
* **Colour.** Only luma is recovered.  Chroma is a quadrature subcarrier at
  3.579545 MHz (NTSC) or 4.43361875 MHz (PAL) which needs a burst-locked
  oscillator; separating it is a further piece of work, and at the 10 MSPS an
  E200 is comfortable with on the stock firmware the NTSC subcarrier is only
  just inside Nyquist.  Every frame here is greyscale.
* **True interlace.** Fields are decoded independently, each giving a picture
  of half the frame height.  :func:`weave` interleaves consecutive fields into
  a full-height frame, which is correct for a genuinely interlaced source and
  produces comb artefacts on motion.  The half-line offset that distinguishes
  the two fields of real 2:1 interlace is not measured, so ``weave`` cannot
  tell which field is odd and which is even; it assumes the first is the top.
* **Audio.** The 6.0 and 6.5 MHz FM audio subcarriers are outside the low-pass
  in :func:`~antsdr_toolkit.analog.fpv.fm_demod` and are discarded.

Sources for the timings are the standards themselves, mirrored in
``antsdr/research/signal-reference.md``; the sync and picture levels are the
scaling that :func:`~antsdr_toolkit.analog.fpv.fm_demod` produces, which
follows the reference decoder in ``zubon2003/5G8atv-rf-hackrf-decoder``.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from .fpv import BLANKING_LEVEL, SYNC_LEVEL, WHITE_LEVEL, fm_demod

__all__ = [
    "SLICE_LEVEL",
    "STANDARDS",
    "SYNC_WIDTH_RANGE",
    "VIDEO_SPAN",
    "DecodedField",
    "VideoStandard",
    "decode_fields",
    "decode_from_iq",
    "field_starts",
    "identify_standard",
    "pulse_widths",
    "sync_edges",
    "sync_metric",
    "weave",
    "write_pgm",
    "write_png",
]

#: Blanking-to-peak-white excursion in the units :func:`fpv.fm_demod` produces.
#: A line's own back porch supplies the zero, so only the span is needed to
#: scale a line to 0..1.
VIDEO_SPAN = WHITE_LEVEL - BLANKING_LEVEL


@dataclass(frozen=True)
class VideoStandard:
    """Line and field geometry of one analog television standard."""

    name: str
    line_period_s: float
    sync_s: float
    """Horizontal sync pulse width."""
    back_porch_s: float
    active_s: float
    active_lines_per_field: int
    lines_per_frame: float
    field_rate_hz: float

    @property
    def line_rate_hz(self) -> float:
        return 1.0 / self.line_period_s

    def samples_per_line(self, sample_rate_hz: float) -> float:
        return float(sample_rate_hz) * self.line_period_s


#: NTSC-M and PAL-B/G geometry. ``active_s`` is the visible part of a line,
#: and ``active_lines_per_field`` the visible lines of one field; the rest of
#: the 262.5 or 312.5 lines is vertical blanking.
STANDARDS: dict[str, VideoStandard] = dict(MappingProxyType({
    "ntsc": VideoStandard("ntsc", 63.5e-6, 4.7e-6, 4.7e-6, 52.6e-6, 240, 262.5, 59.94),
    "pal": VideoStandard("pal", 64.0e-6, 4.7e-6, 5.7e-6, 51.95e-6, 288, 312.5, 50.0),
}))


@dataclass(frozen=True)
class DecodedField:
    """One field: a greyscale image plus how well it was recovered."""

    image: np.ndarray
    """``(lines, width)`` float64 in 0..1, where 0 is black and 1 peak white."""
    t_start_s: float
    """Time of the vertical sync that opened this field."""
    n_lines_found: int
    """Sync edges actually found in the field; short means dropped lines."""
    standard: str

    @property
    def complete(self) -> bool:
        """True when every line of the field was found."""
        return self.n_lines_found >= STANDARDS[self.standard].active_lines_per_field

    def to_dict(self) -> dict[str, float | int | str | bool]:
        return {
            "t_start_s": round(float(self.t_start_s), 6),
            "lines": int(self.image.shape[0]),
            "width": int(self.image.shape[1]),
            "n_lines_found": int(self.n_lines_found),
            "standard": self.standard,
            "complete": bool(self.complete),
            "mean_level": round(float(self.image.mean()), 4),
        }


#: How far a pulse's width may stray from the standard's horizontal sync and
#: still be counted as the start of a line. Wide enough to survive the rise
#: time a 4 MHz low-pass adds, narrow enough to reject both of the vertical
#: interval's pulse shapes: for NTSC, sync is 4.7 us against equalising pulses
#: of 2.3 us (ratio 0.49) and broad pulses of 27.1 us (ratio 5.8).
SYNC_WIDTH_RANGE = (0.6, 2.0)

#: Where to slice sync from picture: halfway down the sync excursion.
#:
#: :data:`fpv.SYNC_THRESHOLD` sits at -0.020, only a fifth of the way from
#: blanking (-0.015) to the sync tip (-0.040). That is fine for the lock
#: *metric*, which only has to notice periodicity, but it is a poor slicing
#: level for a decoder: black picture content sits at blanking on any system
#: without a pedestal (PAL, NTSC-J), so a few millivolts of noise on a black
#: line dips under it and manufactures an edge. Slicing at the midpoint
#: instead puts six standard deviations between black and the threshold at the
#: noise level of a usable picture.
SLICE_LEVEL = (BLANKING_LEVEL + SYNC_LEVEL) / 2.0


def pulse_widths(demod: np.ndarray, edges: np.ndarray,
                 *, threshold: float = SLICE_LEVEL) -> np.ndarray:
    """How many samples the signal stays below ``threshold`` after each edge.

    A pulse still open at the end of the capture is measured to the end, which
    over-reports it; that only ever costs the final line.
    """
    values = np.asarray(demod, dtype=np.float64).ravel()
    idx = np.asarray(edges, dtype=np.int64).ravel()
    if idx.size == 0 or values.size == 0:
        return np.zeros(0, dtype=np.int64)
    below = values < float(threshold)
    # The sample after each falling edge is the first one below threshold, so
    # the pulse ends at the next sample that is not.
    not_below = np.flatnonzero(~below)
    ends = np.searchsorted(not_below, idx + 1, side="left")
    closes = np.where(ends < not_below.size, not_below[np.minimum(ends, not_below.size - 1)],
                      values.size)
    return np.maximum(closes - (idx + 1), 0).astype(np.int64)


def sync_edges(demod: np.ndarray, sample_rate_hz: float, standard: str = "ntsc",
               *, threshold: float = SLICE_LEVEL,
               width_filter: bool = True) -> np.ndarray:
    """Sample indices of the falling edges into sync, one per line.

    Every crossing is width-gated *before* being debounced, and the order
    matters more than it looks.

    The gate keeps a crossing only if the pulse it opens lasts about as long as
    the standard's horizontal sync.  That is a width discriminator, the job the
    pulse-width stage of a sync separator does, and it rejects two quite
    different impostors.  Short ones: noise on a black line dipping under the
    threshold for a sample or two, which a picture with large dark areas
    produces by the hundred.  Long ones: the *vertical* interval's equalising
    (about half the sync width) and broad (about six times it) pulses, which
    arrive at half-line intervals, and whose leading group lands at the end of
    the previous field where it would displace that field's last rows.

    Only the survivors are debounced over half a line period, because a
    low-passed sync edge crosses the threshold several times.  Debouncing
    first would be worse than useless: it keeps the *first* crossing in each
    window, so a noise dip early in a line evicts the real sync edge that
    follows it and the line is lost.

    Pass ``width_filter=False`` to inspect every crossing.
    """
    values = np.asarray(demod, dtype=np.float64).ravel()
    if values.size < 4:
        return np.zeros(0, dtype=np.int64)
    below = values < float(threshold)
    raw = np.flatnonzero(~below[:-1] & below[1:])
    if raw.size == 0:
        return np.zeros(0, dtype=np.int64)

    if width_filter:
        nominal = STANDARDS[standard].sync_s * float(sample_rate_hz)
        widths = pulse_widths(values, raw, threshold=threshold)
        lo, hi = SYNC_WIDTH_RANGE
        raw = raw[(widths >= lo * nominal) & (widths <= hi * nominal)]
        if raw.size == 0:
            return np.zeros(0, dtype=np.int64)

    min_gap = max(1, round(0.5 * STANDARDS[standard].line_period_s * float(sample_rate_hz)))
    kept = [int(raw[0])]
    for index in raw[1:]:
        if int(index) - kept[-1] >= min_gap:
            kept.append(int(index))
    return np.asarray(kept, dtype=np.int64)


def sync_metric(demod: np.ndarray, sample_rate_hz: float, standard: str = "ntsc",
                *, threshold: float = SLICE_LEVEL) -> np.ndarray:
    """Fraction of a half-line window spent below the sync threshold.

    This is the sync separator's integrator.  An ordinary line reads about
    ``sync_s / line_period_s`` (0.074 for NTSC); the broad pulses of vertical
    sync read far higher because they invert that duty cycle.  The returned
    array is the same length as ``demod``, each element being the mean over the
    window *starting* at that sample.
    """
    values = np.asarray(demod, dtype=np.float64).ravel()
    window = max(1, round(0.5 * STANDARDS[standard].line_period_s * float(sample_rate_hz)))
    if values.size < window:
        return np.zeros(0, dtype=np.float64)
    below = (values < float(threshold)).astype(np.float64)
    cumulative = np.concatenate([[0.0], np.cumsum(below)])
    return (cumulative[window:] - cumulative[:-window]) / window


def field_starts(demod: np.ndarray, sample_rate_hz: float, standard: str = "ntsc",
                 *, threshold: float = SLICE_LEVEL,
                 vsync_level: float = 0.5) -> np.ndarray:
    """Sample indices where each field's vertical sync begins.

    ``vsync_level`` is where the integrator of :func:`sync_metric` has to rise
    to count as vertical sync.  Half is a wide margin: ordinary lines sit near
    0.07 and broad pulses near 0.85, so anything from 0.3 to 0.7 behaves the
    same.  Detections closer together than three quarters of a field period are
    merged, since the several broad pulses of one vertical interval would
    otherwise each open a field.
    """
    metric = sync_metric(demod, sample_rate_hz, standard, threshold=threshold)
    if metric.size == 0:
        return np.zeros(0, dtype=np.int64)
    high = metric >= float(vsync_level)
    if not high.any():
        return np.zeros(0, dtype=np.int64)
    rises = np.flatnonzero(np.concatenate([[high[0]], ~high[:-1] & high[1:]]))
    spec = STANDARDS[standard]
    min_gap = round(0.75 * float(sample_rate_hz) / spec.field_rate_hz)
    kept = [int(rises[0])]
    for index in rises[1:]:
        if int(index) - kept[-1] >= min_gap:
            kept.append(int(index))
    return np.asarray(kept, dtype=np.int64)


def identify_standard(demod: np.ndarray, sample_rate_hz: float) -> tuple[str | None, float]:
    """Name the standard from the measured line rate.

    Returns ``(name, line_period_s)``, or ``(None, period)`` when the measured
    period is not within 0.3 % of either standard.  NTSC and PAL differ by only
    0.8 %, so the tolerance has to be tighter than that to mean anything; the
    same reasoning as :func:`~antsdr_toolkit.analog.fpv.sync_lock`.
    """
    best_name, best_period, best_error = None, 0.0, float("inf")
    for name, spec in STANDARDS.items():
        edges = sync_edges(demod, sample_rate_hz, name)
        if edges.size < 8:
            continue
        intervals = np.diff(edges) / float(sample_rate_hz)
        # Median over intervals near one line, so a dropped pulse (which gives
        # a double-length interval) does not drag the estimate.
        near = intervals[intervals < 1.5 * spec.line_period_s]
        if near.size < 4:
            continue
        period = float(np.median(near))
        error = abs(period - spec.line_period_s) / spec.line_period_s
        if error < best_error:
            best_name, best_period, best_error = name, period, error
    if best_name is None:
        return None, 0.0
    return (best_name if best_error <= 0.003 else None), best_period


def decode_fields(
    demod: np.ndarray,
    sample_rate_hz: float,
    standard: str = "ntsc",
    *,
    width: int = 320,
    threshold: float = SLICE_LEVEL,
    max_fields: int | None = None,
) -> list[DecodedField]:
    """Slice the demodulated signal into fields and return one image each.

    Every line is level-restored on its own back porch, resampled to ``width``
    pixels by linear interpolation, and scaled so blanking is 0 and peak white
    is 1.  Values outside that are clipped: a real signal overshoots.

    The active lines of a field are taken as the *last*
    ``active_lines_per_field`` sync edges before the next vertical sync,
    because vertical blanking sits at the beginning of a field.  Fields with
    too few lines are still returned, padded with black, and report
    ``n_lines_found`` so a caller can discard them.
    """
    if standard not in STANDARDS:
        raise ValueError(f"standard must be one of {tuple(STANDARDS)}, got {standard!r}")
    values = np.asarray(demod, dtype=np.float64).ravel()
    fs = float(sample_rate_hz)
    spec = STANDARDS[standard]
    if int(width) < 1:
        raise ValueError(f"width must be positive, got {width}")

    starts = field_starts(values, fs, standard, threshold=threshold)
    if starts.size == 0:
        return []
    edges = sync_edges(values, fs, standard, threshold=threshold)
    if edges.size == 0:
        return []

    n_back = max(1, round(spec.back_porch_s * fs))
    n_sync = max(1, round(spec.sync_s * fs))
    n_active = max(2, round(spec.active_s * fs))
    # Where the picture sits relative to a sync edge, and where the back porch
    # sits: both measured from the falling edge, as the standard defines them.
    active_from_edge = n_sync + n_back
    porch_slice = slice(n_sync, n_sync + n_back)
    sample_positions = np.linspace(0.0, n_active - 1.0, int(width))

    boundaries = list(starts) + [values.size]
    out: list[DecodedField] = []
    for index in range(len(starts)):
        lo, hi = int(boundaries[index]), int(boundaries[index + 1])
        in_field = edges[(edges >= lo) & (edges < hi)]
        if in_field.size == 0:
            continue
        # Choose the lines *before* worrying about truncation. A capture that
        # stops mid-line would otherwise drop that edge, and since the field is
        # counted back from its end, dropping the last edge shifts every row up
        # by one and puts a blanked line at the top of the picture.
        chosen = in_field[-spec.active_lines_per_field:]
        image = np.zeros((spec.active_lines_per_field, int(width)), dtype=np.float64)
        offset = spec.active_lines_per_field - chosen.size
        n_complete = 0
        for row, edge in enumerate(chosen):
            start = int(edge)
            porch = values[start + porch_slice.start:start + porch_slice.stop]
            black = float(np.median(porch)) if porch.size else BLANKING_LEVEL
            line = values[start + active_from_edge:start + active_from_edge + n_active]
            if line.size < 2:
                continue
            if line.size < n_active:
                # A truncated final line: interpolate over what arrived and
                # leave the rest of the row black, rather than losing the row.
                available = round(line.size / n_active * int(width))
                if available < 1:
                    continue
                image[offset + row, :available] = (
                    np.interp(np.linspace(0.0, line.size - 1.0, available),
                              np.arange(line.size), line) - black) / VIDEO_SPAN
                continue
            resampled = np.interp(sample_positions, np.arange(n_active), line)
            image[offset + row] = (resampled - black) / VIDEO_SPAN
            n_complete += 1
        np.clip(image, 0.0, 1.0, out=image)
        out.append(DecodedField(image=image, t_start_s=lo / fs,
                                n_lines_found=n_complete, standard=standard))
        if max_fields is not None and len(out) >= int(max_fields):
            break
    return out


def decode_from_iq(
    x: np.ndarray,
    sample_rate_hz: float,
    *,
    standard: str | None = None,
    width: int = 320,
    lowpass_hz: float = 4e6,
    max_fields: int | None = None,
) -> tuple[list[DecodedField], str | None]:
    """Discriminate the FM, name the standard if not given, and decode fields.

    Returns ``(fields, standard)``.  ``standard`` is ``None`` when the line
    rate matched neither NTSC nor PAL, in which case no fields are returned:
    slicing a picture out of a signal whose line rate is unknown produces a
    convincing-looking image of nothing, which is worse than no image.

    The default 4 MHz low-pass is wider than the 2 MHz that
    :func:`~antsdr_toolkit.analog.fpv.fm_demod` uses for detection, because
    detection only needs the sync pulses whereas a picture needs the luma
    bandwidth.  Both are inside the +/-4.5 MHz an FPV carrier occupies.
    """
    demod = fm_demod(x, sample_rate_hz, lowpass_hz=lowpass_hz)
    if demod.size == 0:
        return [], None
    name = standard
    if name is None:
        name, _period = identify_standard(demod, sample_rate_hz)
    if name is None:
        return [], None
    return decode_fields(demod, sample_rate_hz, name, width=width,
                         max_fields=max_fields), name


def weave(fields: Sequence[DecodedField]) -> Iterator[np.ndarray]:
    """Interleave consecutive field pairs into full-height frames.

    Yields one ``(2 * lines, width)`` array per pair, the first field on the
    even rows.  This is right for a genuinely interlaced source and combs on
    motion.  Which field is the top one is *not* measured, because that needs
    the half-line offset of true 2:1 interlace; if the picture looks torn
    vertically, drop the first field and weave again.
    """
    items = list(fields)
    for first, second in zip(items[::2], items[1::2]):
        if first.image.shape != second.image.shape:
            continue
        lines, width = first.image.shape
        frame = np.empty((lines * 2, width), dtype=np.float64)
        frame[0::2] = first.image
        frame[1::2] = second.image
        yield frame


def _to_bytes(image: np.ndarray) -> tuple[np.ndarray, int, int]:
    array = np.asarray(image, dtype=np.float64)
    if array.ndim != 2:
        raise ValueError(f"image must be 2-D, got shape {array.shape}")
    height, width = array.shape
    if height == 0 or width == 0:
        raise ValueError("image must not be empty")
    return (np.clip(array, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), height, width


def write_pgm(path: str, image: np.ndarray) -> str:
    """Write a greyscale image as binary PGM (P5). No dependencies."""
    data, height, width = _to_bytes(image)
    with open(path, "wb") as handle:
        handle.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        handle.write(data.tobytes())
    return path


def write_png(path: str, image: np.ndarray) -> str:
    """Write a greyscale image as PNG, using only ``zlib`` from the standard library.

    8-bit greyscale, no interlacing, one filter byte of 0 per row. Written by
    hand rather than through Pillow so that decoding a picture needs nothing
    beyond the toolkit's existing dependencies.
    """
    data, height, width = _to_bytes(image)
    raw = b"".join(b"\x00" + data[row].tobytes() for row in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(chunk(b"IHDR", header))
        handle.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        handle.write(chunk(b"IEND", b""))
    return path
