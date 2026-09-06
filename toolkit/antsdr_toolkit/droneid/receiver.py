"""Find, synchronise and decode DroneID bursts in a capture.

The chain, in the order it runs:

1. **Find** the burst with a normalised cross-correlation against the
   root-600 Zadoff-Chu pilot (:func:`find_bursts`).  The correlation is
   phase-blind and survives a frequency offset of well over a megahertz,
   which is why it is the first stage rather than an energy detector.
2. **Confirm** it by the cyclic prefixes.  A DroneID burst repeats the tail
   of each of its nine symbols one FFT earlier; noise does not.  The mean
   coherence of those nine pairs is about 0.1 for noise and close to one for a
   burst, and because it uses only the *magnitude* of each correlation it does
   not care about a frequency offset.  The second pilot (root 147) is scored
   too and reported, but it is not the gate: unlike root 600 it decorrelates
   rather than sliding under an offset, and is already useless at 30 kHz.
3. **Estimate the frequency offset** from the cyclic prefixes: each prefix is
   a copy of the end of its own symbol one FFT later, so the phase of that
   correlation is the offset.  Unambiguous within half a subcarrier spacing,
   which is +-7.5 kHz.
4. **Refine the timing** by maximising the same cyclic-prefix correlation over
   a small window of offsets.
5. **Demodulate**: strip the prefixes, FFT each symbol, equalise with the
   known Zadoff-Chu pilots, slice QPSK, descramble, de-rate-match and check
   the two CRCs (:mod:`antsdr_toolkit.droneid.fec`).

The frequency offset is measured twice
--------------------------------------
A cyclic prefix resolves an offset only within half a subcarrier spacing,
+-7.5 kHz, which is not enough: two 0.5 ppm oscillators at 5.8 GHz can be
6 kHz apart before the transmitter's own error is counted.

Zadoff-Chu sequences are chirps, and a chirp answers a frequency offset by
*moving in time* rather than fading away.  The root-600 correlation still
peaks above 0.8 at an offset of 500 kHz, and the peak has slid by a distance
proportional to the offset: one sample per
``N_zc * subcarrier_spacing / N_fft`` = 8.80 kHz at 15.36 MSPS
(:data:`ZC_SHIFT_HZ_PER_SAMPLE`).  The cyclic-prefix correlation, whose
magnitude does not care about a common phase rotation, gives the true timing
independently.  The distance between the two is therefore a coarse frequency
estimate with a range of hundreds of kilohertz, and the cyclic-prefix phase
refines it (:func:`estimate_cfo`).

What this does not do
---------------------
No turbo decoding, so a burst that a real decoder would correct is reported
as a CRC failure; expect roughly 3 dB less sensitivity than a complete
implementation.  On synthetic bursts this receiver decodes cleanly at an
in-band signal-to-noise ratio of about 20 dB and fails below roughly 15 dB.
Bursts of OcuSync 4 drones are found and reported but their payload is
encrypted, so the CRC will fail (see ``antsdr/research/landscape.md``).
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import constants as C
from . import fec
from .zc import carrier_indices, zc_frequency, zc_time

__all__ = [
    "ZC_SHIFT_HZ_PER_SAMPLE",
    "BurstDetection",
    "DroneIdFrame",
    "coarse_frequency_offset",
    "correlate_zc",
    "cp_coherence",
    "decode_burst",
    "estimate_cfo",
    "find_bursts",
    "interpolate_peak",
    "process",
    "zc_shift_hz_per_sample",
]

#: Correlation score above which a peak is worth confirming. The reference
#: MATLAB uses 0.7 for clean captures and notes 0.2-0.9 as the usable span.
DEFAULT_THRESHOLD = 0.5
#: Least mean cyclic-prefix coherence a detection must show. Noise sits near
#: ``1 / sqrt(cp_length)``, about 0.11 for the 80-sample prefixes at
#: 15.36 MSPS; a burst at a usable signal-to-noise ratio is well above 0.5.
CONFIRM_MIN = 0.35
#: Samples either side of the expected root-147 peak to look in when scoring
#: the second pilot for the record.
CONFIRM_SEARCH = 320


@dataclass(frozen=True)
class BurstDetection:
    """One candidate burst found by the Zadoff-Chu correlator."""

    sample_start: int
    """Index of the first sample of the burst (its first cyclic prefix)."""
    score: float
    """Normalised root-600 correlation, 0 to 1."""
    confirm_score: float
    """Mean cyclic-prefix coherence over the burst's nine symbols, 0 to 1."""
    cfo_hz: float
    """Frequency offset: the pilot's chirp slide plus the prefix phase."""
    snr_db: float
    t_start_s: float
    zc147_score: float = 0.0
    """Root-147 correlation near its expected place. Informative only: this
    pilot decorrelates under a frequency offset instead of sliding, so it is
    near zero above about 10 kHz even on a perfectly good burst."""
    legacy: bool = False
    zc_root: int | None = None
    """Which candidate Zadoff-Chu root best matched, or ``None`` for none.

    ``None`` is not a failure. The roots are published only for OcuSync 2;
    a burst that is clearly there and matches no known root is a measurement
    of a generation nobody has characterised, and worth keeping."""
    root_agnostic: bool = False
    """True when the burst was found by cyclic-prefix structure rather than by
    a matched filter for a particular root."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_start": int(self.sample_start),
            "t_start_s": float(self.t_start_s),
            "score": round(float(self.score), 4),
            "confirm_score": round(float(self.confirm_score), 4),
            "zc147_score": round(float(self.zc147_score), 4),
            "cfo_hz": round(float(self.cfo_hz), 1),
            "snr_db": round(float(self.snr_db), 1),
            "legacy": bool(self.legacy),
        }


@dataclass(frozen=True)
class DroneIdFrame:
    """A decoded DroneID frame.

    Positions are ``None`` when the field held zero, which the protocol uses
    for "unknown": a drone without a GPS fix sends zeros, and so does one that
    has not been paired with a controller.
    """

    serial: str
    product_type: int
    product_name: str
    sequence: int
    state_info: int
    drone_lat: float | None
    drone_lon: float | None
    pilot_lat: float | None
    pilot_lon: float | None
    home_lat: float | None
    home_lon: float | None
    height_m: float
    altitude_m: float
    v_north_m_s: float
    v_east_m_s: float
    v_up_m_s: float
    yaw_deg: float
    gps_time_ms: int
    uuid: bytes
    crc16_ok: bool
    crc24_ok: bool
    raw: bytes = field(repr=False, default=b"")

    @property
    def speed_h_m_s(self) -> float:
        return float(np.hypot(self.v_north_m_s, self.v_east_m_s))

    def to_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "product_type": self.product_type,
            "product_name": self.product_name,
            "sequence": self.sequence,
            "state_info": self.state_info,
            "drone_lat": self.drone_lat, "drone_lon": self.drone_lon,
            "pilot_lat": self.pilot_lat, "pilot_lon": self.pilot_lon,
            "home_lat": self.home_lat, "home_lon": self.home_lon,
            "height_m": self.height_m, "altitude_m": self.altitude_m,
            "speed_h_m_s": round(self.speed_h_m_s, 3),
            "v_up_m_s": self.v_up_m_s, "yaw_deg": self.yaw_deg,
            "gps_time_ms": self.gps_time_ms,
            "uuid": self.uuid.hex(),
            "crc16_ok": self.crc16_ok, "crc24_ok": self.crc24_ok,
        }


def correlate_zc(x: np.ndarray, root: int, sample_rate_hz: float) -> np.ndarray:
    """Normalised correlation of ``x`` with a Zadoff-Chu pilot, 0 to 1.

    ``|sum(w * conj(z))|^2 / (sum|w|^2 * sum|z|^2)`` over every window ``w``,
    computed with an FFT convolution and a running energy sum.  Phase-blind,
    so a frequency offset reduces the peak but does not move it.
    """
    signal = np.asarray(x, dtype=np.complex64).ravel()
    ref = zc_time(root, sample_rate_hz)
    n = ref.size
    if signal.size < n:
        return np.zeros(0, dtype=np.float64)
    size = 1 << int(np.ceil(np.log2(signal.size + n)))
    corr = np.fft.ifft(np.fft.fft(signal, size) * np.conj(np.fft.fft(ref, size)))
    corr = corr[: signal.size - n + 1]
    power = np.abs(signal.astype(np.complex128)) ** 2
    csum = np.concatenate([[0.0], np.cumsum(power)])
    window_energy = csum[n:] - csum[:-n]
    ref_energy = float(np.sum(np.abs(ref.astype(np.complex128)) ** 2))
    denom = window_energy[: corr.size] * ref_energy
    with np.errstate(divide="ignore", invalid="ignore"):
        score = np.where(denom > 0, np.abs(corr) ** 2 / denom, 0.0)
    return np.clip(score, 0.0, 1.0)


def coarse_frequency_offset(burst: np.ndarray, sample_rate_hz: float, *,
                            legacy: bool = False, trim: int = 8) -> float:
    """Frequency offset from the cyclic prefixes, in Hz.

    Each prefix repeats the last samples of its own symbol one FFT length
    later, so the phase of their correlation is ``2 pi f N / fs``.  Averaged
    over every symbol.  Unambiguous only within +-fs/(2N) = +-7.5 kHz, half a
    subcarrier spacing.
    """
    x = np.asarray(burst, dtype=np.complex128).ravel()
    n_fft = C.fft_size(sample_rate_hz)
    total = 0.0 + 0.0j
    pos = 0
    for cp in C.cp_schedule(sample_rate_hz, legacy=legacy):
        lo = pos + trim
        hi = pos + cp - trim
        if hi > lo and pos + cp + n_fft + (hi - lo) <= x.size:
            prefix = x[lo:hi]
            tail = x[lo + n_fft:hi + n_fft]
            total += np.vdot(prefix, tail)
        pos += cp + n_fft
    if total == 0:
        return 0.0
    return float(np.angle(total) * sample_rate_hz / (2.0 * np.pi * n_fft))


def zc_shift_hz_per_sample(sample_rate_hz: float) -> float:
    """How far the Zadoff-Chu peak slides per hertz of frequency offset.

    A length-601 sequence spread over 601 subcarriers of 15 kHz sweeps
    9.015 MHz in one symbol of ``N_fft / fs`` seconds, so its chirp rate is
    ``N_zc * spacing * fs / N_fft`` = 135.2 GHz per second at every supported
    rate, and one *sample* of slide is worth ``N_zc * spacing / N_fft`` hertz:
    8804 Hz at 15.36 MSPS, half that at 30.72 MSPS because a sample there is
    half as long.
    """
    n_fft = C.fft_size(sample_rate_hz)
    return float(C.N_CARRIERS * C.SUBCARRIER_SPACING_HZ / n_fft)


#: The value of :func:`zc_shift_hz_per_sample` at 15.36 MSPS, for reference.
ZC_SHIFT_HZ_PER_SAMPLE = 8804.0


def estimate_cfo(x: np.ndarray, zc_peak: float, aligned_start: int,
                 sample_rate_hz: float, *, legacy: bool = False) -> tuple[float, float]:
    """Frequency offset from the pilot's slide plus the cyclic-prefix phase.

    ``zc_peak`` is where the root-600 correlation peaked, ideally interpolated
    to a fraction of a sample, and ``aligned_start`` is the burst start the
    cyclic-prefix search settled on.  Their difference is the chirp slide,
    worth :func:`zc_shift_hz_per_sample` each; the remainder comes from the
    prefix phase, which is exact but only within +-7.5 kHz.  The coarse value
    is deliberately *not* snapped to the subcarrier grid: one sample of slide
    is 8.8 kHz, more than the fine estimator's unambiguous range, so snapping
    would turn a small timing error into a 15 kHz error.  Returns
    ``(total_hz, coarse_hz)``.
    """
    fs = float(sample_rate_hz)
    expected_peak = aligned_start + C.zc_body_offsets(fs, legacy=legacy)[0]
    slide = float(zc_peak) - float(expected_peak)
    coarse = slide * zc_shift_hz_per_sample(fs)
    length = C.burst_length(fs, legacy=legacy)
    xs = np.asarray(x, dtype=np.complex128).ravel()
    if aligned_start < 0 or aligned_start + length > xs.size:
        return coarse, coarse
    burst = xs[aligned_start:aligned_start + length]
    if coarse:
        n = np.arange(burst.size, dtype=np.float64)
        burst = burst * np.exp(-2j * np.pi * coarse * n / fs)
    fine = coarse_frequency_offset(burst, fs, legacy=legacy)
    return coarse + fine, coarse


def _cp_metric(x: np.ndarray, start: int, sample_rate_hz: float, legacy: bool) -> float:
    """How well the cyclic prefixes line up when the burst starts at ``start``."""
    n_fft = C.fft_size(sample_rate_hz)
    total = 0.0
    pos = int(start)
    if pos < 0:
        return 0.0
    for cp in C.cp_schedule(sample_rate_hz, legacy=legacy):
        # The last symbol's tail ends exactly at the end of a buffer that holds
        # only the burst, so compare as much of the prefix as is present rather
        # than rejecting the alignment outright.
        usable = min(cp, x.size - (pos + n_fft), x.size - pos)
        if usable <= 0:
            break
        prefix = x[pos:pos + usable]
        tail = x[pos + n_fft:pos + n_fft + usable]
        total += abs(np.vdot(prefix, tail))
        pos += cp + n_fft
    return float(total)


def cp_coherence(x: np.ndarray, start: int, sample_rate_hz: float, *,
                 legacy: bool = False) -> float:
    """Mean normalised cyclic-prefix correlation of a burst at ``start``.

    Each of the nine prefixes is compared with the tail of its own symbol one
    FFT later; the magnitudes are normalised per symbol and averaged, so the
    result is a coherence in ``[0, 1]`` that is blind to any common phase
    rotation and therefore to the frequency offset.
    """
    xs = np.asarray(x, dtype=np.complex128).ravel()
    n_fft = C.fft_size(sample_rate_hz)
    pos = int(start)
    if pos < 0:
        return 0.0
    scores: list[float] = []
    for cp in C.cp_schedule(sample_rate_hz, legacy=legacy):
        usable = min(cp, xs.size - (pos + n_fft), xs.size - pos)
        if usable <= 0:
            break
        prefix = xs[pos:pos + usable]
        tail = xs[pos + n_fft:pos + n_fft + usable]
        denom = np.linalg.norm(prefix) * np.linalg.norm(tail)
        if denom > 0:
            scores.append(float(abs(np.vdot(prefix, tail)) / denom))
        pos += cp + n_fft
    return float(np.mean(scores)) if scores else 0.0


#: Candidate Zadoff-Chu roots to score a detected burst against, as generation
#: labels rather than as gates. 600 and 147 are the OcuSync 2 pair both
#: reference implementations agree on; 385 is reported alongside 600 for the
#: OcuSync 3 burst. The list is deliberately open: a burst whose best root is
#: none of these is still a burst, and its measured root is worth recording,
#: because nobody has published the roots for the later generations.
CANDIDATE_ZC_ROOTS = (600, 147, 385)

#: How far below the winner the runner-up must sit for a root to be claimed.
#: Different Zadoff-Chu roots cross-correlate at about ``1 / sqrt(601)`` = 0.04,
#: so a genuine match wins by more than an order of magnitude and anything
#: closer than half is a coin toss.
ROOT_MARGIN = 0.5

#: How many whole subcarrier spacings either side of the prefix estimate to
#: search when identifying a root. The prefix estimator wraps every 15 kHz;
#: nine either way covers the +/-135 kHz an uncalibrated TCXO and a real
#: aircraft between them can produce at 2.4 GHz.
CFO_WRAP_SEARCH = 9

#: Cyclic-prefix coherence a window must reach to open a root-agnostic
#: candidate. Lower than :data:`CONFIRM_MIN` because this is a coarse sweep
#: over every offset rather than a score at a known burst start, and the
#: alignment is off by up to half a symbol.
CP_SCAN_MIN = 0.28


def cp_profile(x: np.ndarray, sample_rate_hz: float, *,
               step: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """Cyclic-prefix coherence swept across the whole signal.

    Returns ``(offsets, coherence)``. Every OFDM symbol repeats its own tail
    one FFT length earlier, so correlating the two gives a peak wherever an
    OFDM signal of this numerology is present, **whatever the symbols carry**.
    That is the property this is for: it does not know or care which
    Zadoff-Chu root the pilots use.

    Why that matters here. :func:`find_bursts` gates on a matched filter for
    root 600, which is the OcuSync 2 pilot. OcuSync 3 is reported to use 600
    and 385, and an OcuSync 4 variant to vary its roots frame to frame
    (proto17 issue 65). A fixed-root gate is therefore blind to exactly the
    generations a modern fleet flies, and it fails silently: no detection
    looks the same as no drone.

    ``step`` trades resolution for speed. The default of 16 samples is far
    finer than the coarsest cyclic prefix (72 samples at 15.36 MSPS), so a
    burst cannot slip between two probes.
    """
    xs = np.asarray(x, dtype=np.complex128).ravel()
    fs = float(sample_rate_hz)
    n_fft = C.fft_size(fs)
    window = min(C.cp_schedule(fs))
    stride = max(1, int(step))
    last = xs.size - (n_fft + window)
    if last <= 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64)

    offsets = np.arange(0, last, stride, dtype=np.int64)
    # Sliding inner products, vectorised: sum over the window of
    # x[n+k] * conj(x[n+k+N]), normalised by both windows' energies.
    product = xs[:-n_fft] * np.conj(xs[n_fft:])
    energy_a = np.abs(xs[:-n_fft]) ** 2
    energy_b = np.abs(xs[n_fft:]) ** 2
    kernel = np.ones(window)
    num = np.abs(np.convolve(product, kernel, mode="valid"))
    den = np.sqrt(np.convolve(energy_a, kernel, mode="valid")
                  * np.convolve(energy_b, kernel, mode="valid"))
    with np.errstate(divide="ignore", invalid="ignore"):
        coherence = np.where(den > 0, num / den, 0.0)
    keep = offsets[offsets < coherence.size]
    return keep, coherence[keep]


def estimate_zc_root(x: np.ndarray, start: int, sample_rate_hz: float, *,
                     roots: Sequence[int] = CANDIDATE_ZC_ROOTS,
                     legacy: bool = False) -> tuple[int | None, float]:
    """Which candidate root best matches this burst's first pilot.

    Returns ``(root, score)``, or ``(None, best)`` when nothing clears half
    the detection threshold. Recording the answer per burst is how the roots
    of the unpublished generations eventually get measured: every capture of
    a real aircraft becomes a data point.
    """
    fs = float(sample_rate_hz)
    offset = C.zc_body_offsets(fs, legacy=legacy)[0]
    n_fft = C.fft_size(fs)
    at = int(start) + offset
    xs = np.asarray(x, dtype=np.complex64).ravel()
    if at < 0 or at + n_fft > xs.size:
        return None, 0.0
    scored: list[tuple[float, int]] = []
    for root in roots:
        ref = zc_time(int(root), fs)
        piece = xs[at:at + ref.size]
        if piece.size < ref.size:
            continue
        denom = np.linalg.norm(piece) * np.linalg.norm(ref)
        scored.append((float(abs(np.vdot(piece, ref)) / denom) if denom > 0 else 0.0, int(root)))
    if not scored:
        return None, 0.0
    scored.sort(reverse=True)
    best_score, best_root = scored[0]
    if best_score < DEFAULT_THRESHOLD / 2:
        return None, best_score
    # A real match is emphatic. Zadoff-Chu sequences of different roots
    # cross-correlate at about 1/sqrt(N), which is 0.04 here, so the right root
    # beats the runner-up more than twentyfold. Two roots scoring alike means
    # neither was matched and the difference is noise; saying so is better than
    # naming whichever won by a thousandth.
    if len(scored) > 1 and scored[1][0] > best_score * ROOT_MARGIN:
        return None, best_score
    return best_root, best_score


def cfo_from_prefix(x: np.ndarray, start: int, sample_rate_hz: float, *,
                    legacy: bool = False) -> tuple[float, float]:
    """Frequency offset from the cyclic prefixes, with its ambiguity.

    Returns ``(cfo_hz, unambiguous_range_hz)``. Each prefix is a copy of its
    own symbol's tail one FFT length later, so the phase of their correlation
    is ``2 pi * cfo * N_fft / fs``. Solving for the offset is the standard
    prefix estimator, and it is exact within one wrap of that phase.

    **It wraps at one subcarrier spacing.** ``fs / N_fft`` is 15 kHz for this
    numerology, so the estimate is unambiguous only within +/-7.5 kHz and a
    true offset of 120 kHz reads as whatever 120 kHz is modulo 15 kHz. That is
    a property of the method, not a bug, and it is why the returned range
    matters as much as the value: a caller that needs the whole offset must
    resolve the integer part another way, which is what the Zadoff-Chu chirp
    slide does in :func:`estimate_cfo` when a known root is available.
    """
    xs = np.asarray(x, dtype=np.complex128).ravel()
    fs = float(sample_rate_hz)
    n_fft = C.fft_size(fs)
    spacing = fs / n_fft
    pos = int(start)
    total = 0.0 + 0.0j
    for cp in C.cp_schedule(fs, legacy=legacy):
        usable = min(cp, xs.size - (pos + n_fft), xs.size - pos)
        if usable <= 0:
            break
        total += np.vdot(xs[pos:pos + usable], xs[pos + n_fft:pos + n_fft + usable])
        pos += cp + n_fft
    if total == 0:
        return 0.0, spacing
    # numpy's vdot conjugates its FIRST argument, so this is
    # sum(conj(prefix) * tail) = |s|^2 * exp(+j 2 pi f N / fs), and the sign of
    # the recovered offset is positive. Getting that backwards is invisible
    # whenever the true offset happens to be near a multiple of the subcarrier
    # spacing, which is exactly where a lazy test would look.
    return float(np.angle(total) * fs / (2.0 * np.pi * n_fft)), float(spacing)


def _symbol_starts_before(boundary: int, sample_rate_hz: float, *,
                          legacy: bool = False) -> list[int]:
    """Candidate burst starts, given that ``boundary`` is *some* symbol start.

    Returns one candidate per symbol position, computed from the cumulative
    cyclic-prefix schedule rather than from a fixed stride, because the
    schedule is not uniform.
    """
    cps = C.cp_schedule(sample_rate_hz, legacy=legacy)
    n_fft = C.fft_size(sample_rate_hz)
    cumulative, total = [0], 0
    for cp in cps[:-1]:
        total += cp + n_fft
        cumulative.append(total)
    return [int(boundary) - offset for offset in cumulative]


def find_bursts_cp(
    x: np.ndarray,
    sample_rate_hz: float,
    *,
    legacy: bool = False,
    max_bursts: int = 64,
    scan_min: float = CP_SCAN_MIN,
    confirm_min: float = CONFIRM_MIN,
    step: int = 16,
) -> list[BurstDetection]:
    """Find bursts without assuming any Zadoff-Chu root.

    Sweeps :func:`cp_profile` for offsets where the signal correlates with
    itself one FFT later, then tests each as a burst *start* by scoring all
    nine prefixes against the standard schedule. That second step is what
    separates a burst start from the eight other symbol boundaries inside the
    same burst: the schedule is asymmetric, 80 samples then seven of 72 then
    80 at 15.36 MSPS, so it only lines up at one offset.

    The detections carry ``score`` from the best matching candidate root
    rather than from a fixed one, and ``zc_root`` records which root that was,
    or ``None`` when none of the candidates matched. A burst with no
    recognised root is still returned: it is a real observation, and for the
    generations whose roots nobody has published it is the *interesting* one.
    """
    signal = np.asarray(x, dtype=np.complex64).ravel()
    fs = float(sample_rate_hz)
    length = C.burst_length(fs, legacy=legacy)
    offsets, coherence = cp_profile(signal, fs, step=step)
    if offsets.size == 0:
        return []

    candidates = offsets[coherence >= float(scan_min)]
    detections: list[BurstDetection] = []
    used: list[int] = []
    # Strongest first, so a burst is claimed by its best-aligned candidate.
    order = np.argsort(-coherence[coherence >= float(scan_min)])
    for index in order:
        if len(detections) >= int(max_bursts):
            break
        base = int(candidates[index])
        # Cheap pre-filter on the raw offset; the real test is on the resolved
        # start below, because one burst raises the profile at all nine of its
        # symbol boundaries and every one of them resolves to the same start.
        if any(abs(base - u) < length for u in used):
            continue
        # The profile marks a symbol boundary, which may be any of the nine.
        # Step back through the schedule to find which one starts the burst.
        #
        # The steps are not equal, and assuming they are is a real trap: the
        # prefixes run 80, then seven of 72, then 80 at 15.36 MSPS, so a fixed
        # stride of 1104 accumulates 8 samples of error per symbol and lands
        # 2192 samples out by the third one. That is exactly the gap between
        # the two Zadoff-Chu pilots, so the burst still "decodes", with the
        # second pilot read as the first and the root reported as 147 instead
        # of 600. Walking the actual cumulative schedule is the fix.
        best_start, best_confirm = -1, 0.0
        for trial in _symbol_starts_before(base, fs, legacy=legacy):
            for jitter in (-step, 0, step):
                start = trial + jitter
                if start < 0 or start + length > signal.size:
                    continue
                confirm = cp_coherence(signal, start, fs, legacy=legacy)
                if confirm > best_confirm:
                    best_start, best_confirm = start, confirm
        if best_start < 0 or best_confirm < float(confirm_min):
            continue
        start = refine_start(signal, best_start, fs, legacy=legacy)
        if start < 0 or start + length > signal.size:
            start = best_start
        confirm = cp_coherence(signal, start, fs, legacy=legacy)
        if confirm < float(confirm_min):
            continue

        if any(abs(start - u) < length // 2 for u in used):
            continue

        # The prefix estimator is exact but wraps every 15 kHz, so identifying
        # the root means searching the wraps: de-rotate by the fine estimate
        # plus each whole subcarrier within range, and keep the hypothesis that
        # matches a known root best. A matched filter decorrelates under any
        # uncorrected offset, so without this an ordinary OcuSync 2 burst
        # 30 kHz off its centre reports "no known root".
        fine, spacing = cfo_from_prefix(signal, start, fs, legacy=legacy)
        n = np.arange(signal.size, dtype=np.float64)
        best = (None, 0.0, fine)
        for k in range(-CFO_WRAP_SEARCH, CFO_WRAP_SEARCH + 1):
            hypothesis = fine + k * spacing
            probe = signal if k == 0 and abs(fine) < 1.0 else (
                signal * np.exp(-2j * np.pi * hypothesis * n / fs)).astype(np.complex64)
            root, score = estimate_zc_root(probe, start, fs, legacy=legacy)
            if score > best[1]:
                best = (root, score, hypothesis)
        root, root_score, cfo = best
        detections.append(BurstDetection(
            sample_start=int(start), score=float(root_score), confirm_score=float(confirm),
            cfo_hz=float(cfo), snr_db=_burst_snr_db(signal, start, length),
            t_start_s=start / fs, legacy=bool(legacy), zc_root=root,
            root_agnostic=True))
        used.append(int(start))
    detections.sort(key=lambda d: d.sample_start)
    return detections


def interpolate_peak(scores: np.ndarray, index: int) -> float:
    """Sub-sample peak position by fitting a parabola to three points.

    The frequency estimate reads the peak's distance from the aligned burst
    start, and one sample is worth 8.8 kHz, so a whole-sample peak is too
    coarse to resolve an offset the cyclic prefix can then finish.
    """
    i = int(index)
    if i <= 0 or i + 1 >= scores.size:
        return float(i)
    y0, y1, y2 = float(scores[i - 1]), float(scores[i]), float(scores[i + 1])
    denom = y0 - 2.0 * y1 + y2
    if denom == 0.0:
        return float(i)
    delta = 0.5 * (y0 - y2) / denom
    return float(i + np.clip(delta, -1.0, 1.0))


def refine_start(x: np.ndarray, start: int, sample_rate_hz: float, *,
                 search: int = 40, legacy: bool = False) -> int:
    """Move ``start`` by up to ``search`` samples to maximise the prefix fit."""
    xs = np.asarray(x, dtype=np.complex128).ravel()
    best, best_score = int(start), -1.0
    for offset in range(-int(search), int(search) + 1):
        candidate = int(start) + offset
        score = _cp_metric(xs, candidate, sample_rate_hz, legacy)
        if score > best_score:
            best, best_score = candidate, score
    return best


def find_bursts(
    x: np.ndarray,
    sample_rate_hz: float,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    legacy: bool = False,
    max_bursts: int = 64,
    refine: bool = True,
) -> list[BurstDetection]:
    """Locate DroneID bursts by their Zadoff-Chu pilots.

    Peaks in the root-600 correlation above ``threshold`` are kept, deduped
    within one symbol, and confirmed by the root-147 correlation two symbols
    later.  Returns detections in time order.
    """
    signal = np.asarray(x, dtype=np.complex64).ravel()
    fs = float(sample_rate_hz)
    n_fft = C.fft_size(fs)
    cps = C.cp_schedule(fs, legacy=legacy)
    zc_offsets = C.zc_body_offsets(fs, legacy=legacy)
    gap = zc_offsets[1] - zc_offsets[0]

    score600 = correlate_zc(signal, C.ZC_ROOTS[0], fs)
    if score600.size == 0:
        return []
    score147 = correlate_zc(signal, C.ZC_ROOTS[1], fs)

    candidates = np.flatnonzero(score600 >= float(threshold))
    detections: list[BurstDetection] = []
    used: list[int] = []
    order = candidates[np.argsort(-score600[candidates])]
    for idx in order:
        if len(detections) >= int(max_bursts):
            break
        if any(abs(int(idx) - u) < n_fft // 2 for u in used):
            continue
        start = int(idx) - zc_offsets[0]
        if start < 0 or start + C.burst_length(fs, legacy=legacy) > signal.size:
            continue
        if refine:
            start = refine_start(signal, start, fs, legacy=legacy)
            if start < 0 or start + C.burst_length(fs, legacy=legacy) > signal.size:
                continue
        confirm = cp_coherence(signal, start, fs, legacy=legacy)
        if confirm < CONFIRM_MIN:
            continue
        lo = max(0, int(idx) + gap - CONFIRM_SEARCH)
        hi = min(score147.size, int(idx) + gap + CONFIRM_SEARCH + 1)
        zc147 = float(score147[lo:hi].max()) if hi > lo else 0.0
        used.append(int(idx))
        peak = interpolate_peak(score600, int(idx))
        cfo, _coarse = estimate_cfo(signal, peak, start, fs, legacy=legacy)
        detections.append(BurstDetection(
            sample_start=start, score=float(score600[idx]), confirm_score=confirm,
            zc147_score=zc147, cfo_hz=cfo,
            snr_db=_burst_snr_db(signal, start, C.burst_length(fs, legacy=legacy)),
            t_start_s=start / fs, legacy=legacy,
            # This gate *is* a root-600 matched filter, so the root is known by
            # construction rather than measured. Recording it keeps the field
            # meaningful whichever gate produced the detection.
            zc_root=C.ZC_ROOTS[0], root_agnostic=False,
        ))
    detections.sort(key=lambda d: d.sample_start)
    _ = cps  # kept for readability of the schedule above
    return detections


def _burst_snr_db(signal: np.ndarray, start: int, length: int) -> float:
    """Burst power over the power of the quiet samples around it, in dB."""
    x = np.abs(np.asarray(signal[start:start + length], dtype=np.complex128)) ** 2
    if x.size == 0:
        return float("nan")
    burst_power = float(x.mean())
    before = signal[max(0, start - length):start]
    after = signal[start + length:start + 2 * length]
    quiet = np.concatenate([np.asarray(before), np.asarray(after)])
    if quiet.size == 0:
        return float("nan")
    noise_power = float(np.mean(np.abs(quiet.astype(np.complex128)) ** 2))
    if noise_power <= 0 or burst_power <= noise_power:
        return float("nan")
    return float(10.0 * np.log10((burst_power - noise_power) / noise_power))


def _symbols(burst: np.ndarray, sample_rate_hz: float, legacy: bool) -> np.ndarray:
    """FFT every symbol of a burst; returns ``(n_symbols, 600)`` carriers."""
    n_fft = C.fft_size(sample_rate_hz)
    idx = carrier_indices(n_fft)
    out = []
    pos = 0
    for cp in C.cp_schedule(sample_rate_hz, legacy=legacy):
        body = burst[pos + cp:pos + cp + n_fft]
        if body.size < n_fft:
            break
        spectrum = np.fft.fftshift(np.fft.fft(body, n_fft))
        out.append(spectrum[idx])
        pos += cp + n_fft
    return np.asarray(out, dtype=np.complex128)


def _equalise(symbols: np.ndarray, sample_rate_hz: float, legacy: bool) -> np.ndarray:
    """Zero-forcing equalisation from the two Zadoff-Chu pilots.

    The channel is estimated on each pilot symbol as ``received / known`` and
    interpolated linearly across the symbols between them, which tracks the
    slow phase ramp a residual frequency offset leaves behind.
    """
    n_fft = C.fft_size(sample_rate_hz)
    idx = carrier_indices(n_fft)
    zc_positions = C.ZC_SYMBOLS if not legacy else tuple(i - 1 for i in C.ZC_SYMBOLS)
    estimates = []
    for pos, root in zip(zc_positions, C.ZC_ROOTS):
        if pos >= symbols.shape[0]:
            return symbols
        known = zc_frequency(root, n_fft)[idx]
        with np.errstate(divide="ignore", invalid="ignore"):
            h = np.where(np.abs(known) > 0, symbols[pos] / known, 0.0)
        estimates.append(h)
    h0, h1 = estimates
    out = np.empty_like(symbols)
    span = max(zc_positions[1] - zc_positions[0], 1)
    for k in range(symbols.shape[0]):
        weight = np.clip((k - zc_positions[0]) / span, -1.0, 2.0)
        h = h0 * (1.0 - weight) + h1 * weight
        with np.errstate(divide="ignore", invalid="ignore"):
            out[k] = np.where(np.abs(h) > 1e-12, symbols[k] / h, 0.0)
    return out


def _qpsk_bits(carriers: np.ndarray) -> np.ndarray:
    """LTE QPSK slicing: ``(+,+) -> 00``, ``(+,-) -> 01``, ``(-,+) -> 10``."""
    real = np.real(carriers)
    imag = np.imag(carriers)
    bits = np.empty((carriers.size, 2), dtype=np.uint8)
    bits[:, 0] = (real < 0).astype(np.uint8)
    bits[:, 1] = (imag < 0).astype(np.uint8)
    return bits.reshape(-1)


def decode_burst(
    x: np.ndarray,
    sample_rate_hz: float,
    detection: BurstDetection,
    *,
    correct_cfo: bool = True,
) -> DroneIdFrame | None:
    """Demodulate and decode one detected burst; ``None`` if it will not decode.

    A frame is returned whenever the bits could be assembled, with
    ``crc24_ok`` and ``crc16_ok`` saying whether to trust it.  ``None`` means
    the burst was too short or the geometry did not work out at all.
    """
    signal = np.asarray(x, dtype=np.complex64).ravel()
    fs = float(sample_rate_hz)
    length = C.burst_length(fs, legacy=detection.legacy)
    start = detection.sample_start
    if start < 0 or start + length > signal.size:
        return None
    burst = signal[start:start + length].astype(np.complex128)
    if correct_cfo and detection.cfo_hz:
        n = np.arange(burst.size, dtype=np.float64)
        burst = burst * np.exp(-2j * np.pi * detection.cfo_hz * n / fs)

    symbols = _symbols(burst, fs, detection.legacy)
    if symbols.shape[0] < len(C.cp_schedule(fs, legacy=detection.legacy)):
        return None
    equalised = _equalise(symbols, fs, detection.legacy)
    data_idx = C.data_symbol_indices(legacy=detection.legacy)
    bits = np.concatenate([_qpsk_bits(equalised[i]) for i in data_idx])
    if bits.size != C.RATE_MATCH_E:
        return None
    coded = fec.descramble(bits)
    try:
        systematic = fec.rate_unmatch_systematic(coded)
    except ValueError:
        return None
    payload = fec.bits_to_bytes(systematic[: C.PAYLOAD_BYTES * 8])
    return parse_frame(payload)


def parse_frame(payload: bytes) -> DroneIdFrame | None:
    """Parse the 176-byte payload into a frame, checking both CRCs."""
    if len(payload) < C.FRAME_BYTES:
        return None
    crc24_ok = len(payload) == C.PAYLOAD_BYTES and fec.crc24a(payload) == 0
    frame = payload[: C.FRAME_BYTES]
    crc16_ok = fec.crc16_dji(frame[:-2]) == struct.unpack("<H", frame[-2:])[0]
    try:
        fields = struct.unpack("<BBBHH16siihhhhhhQiiiiBB19sBH", frame)
    except struct.error:
        return None
    (_length, _type, _version, sequence, state, serial_raw, lon, lat, height, altitude,
     v_n, v_e, v_u, yaw, gps_time, pilot_lat, pilot_lon, home_lon, home_lat,
     product, uuid_len, uuid_raw, _pad, _crc) = fields

    def _pair(lat_raw: int, lon_raw: int) -> tuple[float | None, float | None]:
        """One latitude and longitude, each checked against its own range.

        The two are not interchangeable: latitude runs to 90 degrees and
        longitude to 180. Checking both against one range, which an earlier
        version of this function did, accepts an impossible latitude of 150
        and rejects an ordinary Pacific longitude of -150.

        "No fix" is decided on the pair. A single zero is a real place: the
        equator and the Greenwich meridian both run through airspace.
        """
        if lat_raw == 0 and lon_raw == 0:
            return None, None
        latitude = float(lat_raw) / C.COORD_SCALE
        longitude = float(lon_raw) / C.COORD_SCALE
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            return None, None
        return latitude, longitude

    serial = serial_raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return DroneIdFrame(
        serial=serial,
        product_type=int(product),
        product_name=C.product_name(int(product)),
        sequence=int(sequence), state_info=int(state),
        drone_lat=_pair(lat, lon)[0], drone_lon=_pair(lat, lon)[1],
        pilot_lat=_pair(pilot_lat, pilot_lon)[0],
        pilot_lon=_pair(pilot_lat, pilot_lon)[1],
        home_lat=_pair(home_lat, home_lon)[0],
        home_lon=_pair(home_lat, home_lon)[1],
        height_m=float(height), altitude_m=float(altitude),
        v_north_m_s=float(v_n), v_east_m_s=float(v_e), v_up_m_s=float(v_u),
        yaw_deg=float(yaw) / 100.0, gps_time_ms=int(gps_time),
        uuid=bytes(uuid_raw[: int(uuid_len)]),
        crc16_ok=bool(crc16_ok), crc24_ok=bool(crc24_ok), raw=bytes(frame),
    )


def process(
    x: np.ndarray,
    sample_rate_hz: float,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    legacy: bool = False,
    method: str = "both",
) -> list[tuple[BurstDetection, DroneIdFrame | None]]:
    """Find every burst in a capture and try to decode each one.

    ``method`` chooses the gate:

    ``"zc"``
        The root-600 matched filter only. Sharpest on OcuSync 2, and blind to
        any generation using different roots.
    ``"cp"``
        Cyclic-prefix structure only (:func:`find_bursts_cp`). Finds a burst
        whatever its pilots are, which is the only way to see OcuSync 3 and 4.
    ``"both"``
        The default: run each and merge, keeping the matched-filter detection
        where the two agree, because its timing is the finer of the two.

    Merging rather than choosing matters because the two gates fail in
    opposite directions. The matched filter misses unknown roots entirely; the
    prefix gate needs a burst long enough to show its schedule and will miss a
    fragment the correlator still catches.
    """
    if method not in ("zc", "cp", "both"):
        raise ValueError(f"method must be 'zc', 'cp' or 'both', got {method!r}")
    fs = float(sample_rate_hz)
    found: list[BurstDetection] = []
    if method in ("zc", "both"):
        found.extend(find_bursts(x, fs, threshold=threshold, legacy=legacy))
    if method in ("cp", "both"):
        length = C.burst_length(fs, legacy=legacy)
        already = [d.sample_start for d in found]
        for detection in find_bursts_cp(x, fs, legacy=legacy):
            if not any(abs(detection.sample_start - s) < length // 2 for s in already):
                found.append(detection)
    found.sort(key=lambda d: d.sample_start)
    return [(d, decode_burst(x, fs, d)) for d in found]
