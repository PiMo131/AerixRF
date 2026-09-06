"""Analog 5.8 GHz FPV video: find it, tell it from Wi-Fi, read its line rate.

Analog first-person-view video is wideband frequency modulation of a composite
video signal.  It is the one drone link an open receiver can still decode
completely, and it is the one most likely to be flying: the racing and
long-range communities never left it, and the frontline reporting in the
research says the same.

What it looks like
------------------
A noise-like hump about 9 to 10 MHz wide with no discrete carrier, sitting on
one of the published channels between 5362 and 5945 MHz (or on 1.2 and
2.4 GHz plans this module does not tabulate).  Transmitters of the common
RTC6705 class add two weak frequency-modulated audio subcarriers 6.0 and
6.5 MHz out, 25 to 30 dB below the video.

The occupied bandwidth is contested, and the research settled it: neither the
19 to 20 MHz channel spacing nor the 23 to 27 MHz Carson estimate that
circulate in communities are the occupied width.  One measurement of a 25 mW
transmitter kept more than 99 % of its energy within +-4.5 MHz.  A 10 MSPS
capture therefore decodes colour NTSC, though 20 MSPS is the safer capture
rate and is what the E200 is set to by the one project that supports it
(verified: ``analog-fpv-bandwidth`` in ``antsdr/research/verification-log.md``).

Three measurements, in increasing order of cost
-----------------------------------------------
1. **In-band against shoulder power** (:func:`channel_metrics`): a video
   carrier fills its own +-5 MHz and leaves the 5 to 9 MHz ring around it
   empty.  Wi-Fi, which is 20 MHz wide, does not.
2. **Envelope constancy** (:func:`envelope_cv`): frequency modulation has a
   constant envelope, so the coefficient of variation of ``|x|`` is 0.3 to
   0.56 on real transmitters against the 1.2 to 3.2 the reference scanner
   measured on Wi-Fi.  Two limits are worth knowing rather than discovering
   in the field.  Noise alone reads 0.52, so this cannot reject an empty
   channel; and a *continuous* orthogonal-frequency-division carrier reads
   0.52 too, because its envelope is Rayleigh like noise.  What the envelope
   really separates is bursty traffic, whose envelope swings between on and
   off, from a continuous carrier.  Bandwidth, measurement 1, is what
   separates a 10 MHz video hump from a 20 MHz data carrier.
3. **Line-rate lock** (:func:`sync_lock`): demodulate and look for the
   horizontal sync pulses at 63.5 us (NTSC) or 64.0 us (PAL).  This is proof
   rather than inference, and it says which standard is on the air.

The channel table, the gate thresholds and the demodulator scaling are
re-implemented from the description of lukeswitz/fpv-sdr, whose Python is
GPL-3.0 despite an MIT licence file; only the algorithm and its constants are
used here (``antsdr/docs/decisions/ADR-0003``).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

__all__ = [
    "CHANNELS",
    "FpvDetection",
    "channel_frequencies_hz",
    "channel_metrics",
    "detect_fpv",
    "envelope_cv",
    "fm_demod",
    "nearest_channel",
    "sync_lock",
]

#: The published analog channel plan, band letter to eight centre frequencies
#: in MHz. R is Raceband, A/B/E/F the original bands, L the low band and D the
#: DJI analog plan. Several frequencies appear in more than one band, which is
#: why :func:`nearest_channel` has a documented tie-break.
CHANNELS: Mapping[str, tuple[float, ...]] = MappingProxyType({
    "R": (5658.0, 5695.0, 5732.0, 5769.0, 5806.0, 5843.0, 5880.0, 5917.0),
    "A": (5865.0, 5845.0, 5825.0, 5805.0, 5785.0, 5765.0, 5745.0, 5725.0),
    "B": (5733.0, 5752.0, 5771.0, 5790.0, 5809.0, 5828.0, 5847.0, 5866.0),
    "E": (5705.0, 5685.0, 5665.0, 5645.0, 5885.0, 5905.0, 5925.0, 5945.0),
    "F": (5740.0, 5760.0, 5780.0, 5800.0, 5820.0, 5840.0, 5860.0, 5880.0),
    "D": (5660.0, 5695.0, 5735.0, 5770.0, 5805.0, 5878.0, 5914.0, 5839.0),
    "L": (5362.0, 5399.0, 5436.0, 5473.0, 5510.0, 5547.0, 5584.0, 5621.0),
})

#: Order to prefer when one frequency belongs to several bands: Raceband is
#: the most used, the lettered bands follow, and the DJI and low bands last.
BAND_PRIORITY = ("R", "A", "F", "E", "B", "D", "L")

#: Power is integrated over this width around the channel centre.
IN_BAND_HZ = 10e6
#: And compared with the ring out to this width.
SHOULDER_HZ = 18e6
#: Gates from the reference scanner: signal-to-noise over the sweep floor, and
#: how far the in-band power must stand above the shoulder.
MIN_SNR_DB = 12.0
MIN_PEAK_DB = 3.0
#: Envelope coefficient of variation below which a carrier is constant-modulus.
MAX_ENVELOPE_CV = 0.8

#: Demodulator scaling of the reference viewer, which fixes the absolute
#: levels the sync slicer expects.
QUAD_DEMOD_DIVISOR_HZ = 850e6 / 8.0
#: Composite video levels after that scaling.
SYNC_LEVEL = -0.04
SYNC_THRESHOLD = -0.020
BLACK_LEVEL = -0.02
WHITE_LEVEL = 0.06
#: Blanking, which is the level of the back porch. A decoder restores every
#: line's black on its own back porch, so this is the reference the picture is
#: measured against and the zero of :data:`video_decode.VIDEO_SPAN`. It sits
#: *above* :data:`BLACK_LEVEL`: that constant is the slicing level used to
#: separate sync from picture, not the black of a restored line.
BLANKING_LEVEL = -0.015
#: Line periods of the two analog standards.
LINE_PERIOD_S = MappingProxyType({"ntsc": 63.5e-6, "pal": 64.0e-6})


@dataclass(frozen=True)
class FpvDetection:
    """What one channel test concluded."""

    frequency_hz: float
    channel: str
    snr_db: float
    peak_db: float
    envelope_cv: float
    lock_ntsc: float
    lock_pal: float
    verdict: str
    """``"analog_fpv"``, ``"wideband_digital"`` or ``"none"``."""

    @property
    def standard(self) -> str | None:
        """Which analog standard locked, if either."""
        if max(self.lock_ntsc, self.lock_pal) < 0.5:
            return None
        return "ntsc" if self.lock_ntsc >= self.lock_pal else "pal"

    def to_dict(self) -> dict[str, object]:
        return {
            "frequency_hz": float(self.frequency_hz),
            "channel": self.channel,
            "snr_db": round(float(self.snr_db), 2),
            "peak_db": round(float(self.peak_db), 2),
            "envelope_cv": round(float(self.envelope_cv), 3),
            "lock_ntsc": round(float(self.lock_ntsc), 3),
            "lock_pal": round(float(self.lock_pal), 3),
            "standard": self.standard,
            "verdict": self.verdict,
        }


def channel_frequencies_hz() -> tuple[float, ...]:
    """Every distinct channel centre in the table, ascending, in Hz."""
    seen = {f * 1e6 for freqs in CHANNELS.values() for f in freqs}
    return tuple(sorted(seen))


def iter_channels() -> Iterator[tuple[str, float]]:
    """``("R1", 5658e6)`` and so on, in band-priority order."""
    for band in BAND_PRIORITY:
        for index, freq in enumerate(CHANNELS[band], start=1):
            yield f"{band}{index}", freq * 1e6


def nearest_channel(frequency_hz: float, *, tolerance_hz: float = 5e6) -> str | None:
    """Name the channel a frequency sits on, or ``None`` if none is near.

    Ties are broken by :data:`BAND_PRIORITY`: 5880 MHz is R7 rather than F8,
    and 5695 MHz is R2 rather than D2.
    """
    best: tuple[float, str] | None = None
    for name, freq in iter_channels():
        distance = abs(float(frequency_hz) - freq)
        if distance <= float(tolerance_hz) and (best is None or distance < best[0] - 1e-6):
            best = (distance, name)
    return best[1] if best else None


def channel_metrics(freqs_hz: np.ndarray, psd_db: np.ndarray, channel_freq_hz: float, *,
                    in_band_hz: float = IN_BAND_HZ, shoulder_hz: float = SHOULDER_HZ,
                    floor_db: float | None = None,
                    floor_percentile: float = 20.0) -> tuple[float, float]:
    """``(snr_db, peak_db)`` for one channel of a power spectrum.

    ``snr_db`` is the mean in-band power over the sweep's noise floor;
    ``peak_db`` is the mean in-band power over the shoulder ring, which is
    what separates a 10 MHz video hump from a 20 MHz Wi-Fi channel sitting on
    the same centre.
    """
    f = np.asarray(freqs_hz, dtype=np.float64).ravel()
    p = np.asarray(psd_db, dtype=np.float64).ravel()
    if f.shape != p.shape:
        raise ValueError("freqs_hz and psd_db must have the same length")
    if f.size == 0:
        return float("nan"), float("nan")
    offset = np.abs(f - float(channel_freq_hz))
    in_band = offset <= float(in_band_hz) / 2.0
    shoulder = (offset > float(in_band_hz) / 2.0) & (offset <= float(shoulder_hz) / 2.0)
    if not in_band.any():
        return float("nan"), float("nan")
    floor = float(np.percentile(p, float(floor_percentile))) if floor_db is None else float(floor_db)
    in_band_db = float(_mean_db(p[in_band]))
    snr = in_band_db - floor
    peak = in_band_db - float(_mean_db(p[shoulder])) if shoulder.any() else float("inf")
    return float(snr), float(peak)


def _mean_db(values_db: np.ndarray) -> float:
    """Mean of decibel values in the linear domain, back in decibels."""
    if values_db.size == 0:
        return float("nan")
    linear = 10.0 ** (np.asarray(values_db, dtype=np.float64) / 10.0)
    return float(10.0 * np.log10(max(float(linear.mean()), 1e-300)))


def envelope_cv(x: np.ndarray) -> float:
    """``std|x| / mean|x|``: 0.3 to 0.56 for analog video, 1.2 to 3.2 for OFDM.

    Complex Gaussian noise reads about 0.52 because its envelope is Rayleigh,
    so this number only means something once the signal is known to be present.
    """
    mag = np.abs(np.asarray(x, dtype=np.complex128).ravel())
    if mag.size == 0:
        return float("nan")
    mean = float(mag.mean())
    if mean <= 0.0:
        return float("nan")
    return float(mag.std() / mean)


def fm_demod(x: np.ndarray, sample_rate_hz: float, *,
             lowpass_hz: float = 2e6) -> np.ndarray:
    """Frequency-discriminate and low-pass, at the reference viewer's scaling.

    The gain constant ``fs / (2 pi * 106.25 MHz)`` is the one the reference
    decoder uses, and it is what puts the sync tip at -0.04 and peak white at
    +0.06 so the slicing levels here are meaningful.
    """
    signal = np.asarray(x, dtype=np.complex128).ravel()
    if signal.size < 2:
        return np.zeros(0, dtype=np.float64)
    fs = float(sample_rate_hz)
    gain = fs / (2.0 * np.pi * QUAD_DEMOD_DIVISOR_HZ)
    demod = np.angle(signal[1:] * np.conj(signal[:-1])) * gain
    return _lowpass(demod, fs, float(lowpass_hz))


def _lowpass(x: np.ndarray, sample_rate_hz: float, cutoff_hz: float) -> np.ndarray:
    """Hamming-windowed low pass, applied without a phase shift."""
    from scipy.signal import firwin, lfilter

    n_taps = 65
    nyquist = sample_rate_hz / 2.0
    cutoff = min(max(cutoff_hz, 1.0), nyquist * 0.98)
    taps = firwin(n_taps, cutoff / nyquist, window="hamming")
    filtered = lfilter(taps, [1.0], np.asarray(x, dtype=np.float64))
    return np.asarray(filtered[n_taps // 2:], dtype=np.float64)


def sync_lock(demod: np.ndarray, sample_rate_hz: float, standard: str = "ntsc",
              *, tolerance: float = 0.003) -> float:
    """How periodic the sync pulses are at the standard's line rate, 0 to 1.

    Falling edges through the sync threshold are found and the fraction of the
    intervals between them that match the line period is returned.  A locked
    picture scores well above 0.5 and noise scores near zero.

    Two details make the difference between a useful number and a useless one.
    Edges are debounced over half a line, because a low-passed and noisy sync
    edge crosses the threshold several times and each extra crossing is a
    short interval that scores nothing.  And the tolerance defaults to 0.3 %,
    deliberately tighter than the 0.8 % between the two standards: a looser
    window scores NTSC and PAL almost equally and the answer cannot say which
    is on the air.  A dropped pulse doubles an interval, so twice the period
    is accepted as well.
    """
    if standard not in LINE_PERIOD_S:
        raise ValueError(f"standard must be one of {tuple(LINE_PERIOD_S)}, got {standard!r}")
    values = np.asarray(demod, dtype=np.float64).ravel()
    if values.size < 16:
        return 0.0
    period = LINE_PERIOD_S[standard]
    below = values < SYNC_THRESHOLD
    raw_edges = np.flatnonzero(~below[:-1] & below[1:])
    if raw_edges.size < 4:
        return 0.0
    debounce = round(0.5 * period * float(sample_rate_hz))
    edges = _debounce(raw_edges, debounce)
    if edges.size < 4:
        return 0.0
    intervals = np.diff(edges) / float(sample_rate_hz)
    ratios = intervals / period
    hit = np.zeros(ratios.shape, dtype=bool)
    for multiple in (1.0, 2.0):
        hit |= np.abs(ratios - multiple) <= float(tolerance) * multiple
    return float(np.mean(hit))


def _debounce(indices: np.ndarray, min_gap: int) -> np.ndarray:
    """Drop edges that follow within ``min_gap`` samples of the last kept one."""
    if indices.size == 0 or min_gap <= 0:
        return indices
    kept = [int(indices[0])]
    for index in indices[1:]:
        if int(index) - kept[-1] >= min_gap:
            kept.append(int(index))
    return np.asarray(kept, dtype=np.int64)


def detect_fpv(
    x: np.ndarray,
    sample_rate_hz: float,
    center_freq_hz: float,
    *,
    fft_size: int = 4096,
    min_snr_db: float = MIN_SNR_DB,
    min_peak_db: float = MIN_PEAK_DB,
    max_cv: float = MAX_ENVELOPE_CV,
    check_sync: bool = True,
) -> FpvDetection:
    """Run all three tests on a capture centred on one channel."""
    from ..dsp.spectrum import welch_psd_db

    signal = np.asarray(x, dtype=np.complex64).ravel()
    fs = float(sample_rate_hz)
    freqs, psd = welch_psd_db(signal, fs, float(center_freq_hz), nfft=int(fft_size))
    snr_db, peak_db = channel_metrics(freqs, psd, float(center_freq_hz))
    cv = envelope_cv(signal)
    lock_ntsc = lock_pal = 0.0
    if check_sync and signal.size > 1000:
        demod = fm_demod(signal, fs)
        lock_ntsc = sync_lock(demod, fs, "ntsc")
        lock_pal = sync_lock(demod, fs, "pal")

    present = snr_db >= float(min_snr_db) and peak_db >= float(min_peak_db)
    if not present:
        verdict = "none"
    elif cv <= float(max_cv):
        verdict = "analog_fpv"
    else:
        verdict = "wideband_digital"
    return FpvDetection(
        frequency_hz=float(center_freq_hz),
        channel=nearest_channel(center_freq_hz) or "unlisted",
        snr_db=snr_db, peak_db=peak_db, envelope_cv=cv,
        lock_ntsc=lock_ntsc, lock_pal=lock_pal, verdict=verdict,
    )


def scan_channels(
    freqs_hz: np.ndarray,
    psd_db: np.ndarray,
    *,
    channels: Sequence[float] | None = None,
    min_snr_db: float = MIN_SNR_DB,
    min_peak_db: float = MIN_PEAK_DB,
) -> list[tuple[str, float, float, float]]:
    """Rank the channels inside one wide spectrum by signal-to-noise ratio.

    Returns ``(channel, frequency_hz, snr_db, peak_db)`` for the channels that
    pass both gates, strongest first.  This is the cheap first pass of a
    sweep: it needs only a power spectrum, no time-domain work.
    """
    f = np.asarray(freqs_hz, dtype=np.float64).ravel()
    if f.size == 0:
        return []
    lo, hi = float(f.min()), float(f.max())
    wanted = channel_frequencies_hz() if channels is None else [float(c) for c in channels]
    out: list[tuple[str, float, float, float]] = []
    for freq in wanted:
        if not lo + IN_BAND_HZ / 2 <= freq <= hi - IN_BAND_HZ / 2:
            continue
        snr, peak = channel_metrics(f, psd_db, freq)
        if np.isfinite(snr) and snr >= min_snr_db and peak >= min_peak_db:
            out.append((nearest_channel(freq) or "unlisted", freq, snr, peak))
    out.sort(key=lambda row: -row[2])
    return out
