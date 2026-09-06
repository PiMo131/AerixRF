"""Tell OFDM waveforms apart by their cyclic prefix, not by their shape.

A 20 MHz Wi-Fi frame and a 20 MHz OcuSync video downlink look the same to a
burst detector: same width, similar duration, both in the same band.  What
separates them is their numerology.  Every OFDM symbol repeats the tail of
its own body at the front as a cyclic prefix, so the signal correlates with
itself at a lag of exactly one FFT length, and that correlation repeats at
the symbol rate.  The symbol rate differs by more than an order of magnitude
between the families:

============================  ==============  ====================  ===============
Family                        Subcarriers     Symbol rate (alpha)   Lag (at 20 MSPS)
============================  ==============  ====================  ===============
Wi-Fi 802.11a/g/n             312.5 kHz       about 250 kHz         64 samples
LTE / DJI OcuSync 2, DroneID  15 kHz          10.5 to 14.5 kHz      1333 samples
DJI OcuSync 3 / O4            about 30 kHz    22 to 30 kHz          667 samples
============================  ==============  ====================  ===============

The method is the cyclic autocorrelation: multiply the signal by a delayed
conjugate copy, and look for a line in the spectrum of the product.  The line
sits at ``alpha = fs / (N_fft + N_cp)``, the symbol rate including the prefix,
so its position also measures the prefix length.

The alpha windows and the decision weights come from a fielded Zynq-7020 plus
AD9364 system (ALPssdz/RF-Vision-UAV-Tracker), which measured a consistent
28 kHz line on DJI links and used the 250 kHz Wi-Fi line to raise its
threshold in a busy band.  Its exact subcarrier spacing for OcuSync 3 and 4 is
a hypothesis, not a measurement, and this toolkit's own research could not
verify it, so the ``ocusync_30k`` numerology is labelled accordingly.

The honest caveat: LTE and 5G New Radio use the same 15 and 30 kHz
numerologies.  A cyclic line in the OcuSync window says "an LTE-family OFDM
signal", not "a drone".  It is a discriminator against Wi-Fi, not a detector
of drones, and the surrounding evidence has to do the rest.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

__all__ = [
    "NUMEROLOGIES",
    "CyclicResult",
    "Numerology",
    "caf_ncc",
    "cyclic_profile",
    "kurtosis",
    "peak_in_window",
]

#: Excess kurtosis reference for complex circular Gaussian noise. The fourth
#: moment over the squared second moment is exactly 2 for complex noise, not
#: the 3 of a real Gaussian: getting this wrong makes every noise-only dwell
#: look bursty.
KAPPA_GAUSSIAN = 2.0


@dataclass(frozen=True)
class Numerology:
    """One OFDM family's subcarrier spacing and where to look for its line."""

    name: str
    subcarrier_spacing_hz: float
    alpha_window_hz: tuple[float, float]
    """Where the symbol-rate line may sit: the spacing divided by (1 + CP)."""
    note: str = ""
    verified: bool = True

    def lag_samples(self, sample_rate_hz: float) -> int:
        """Delay to correlate at: one FFT length, ``fs / spacing``."""
        return round(float(sample_rate_hz) / self.subcarrier_spacing_hz)


#: The three numerologies worth testing in the drone bands.
NUMEROLOGIES: Mapping[str, Numerology] = MappingProxyType({
    "ocusync_15k": Numerology(
        "ocusync_15k", 15e3, (10.5e3, 14.5e3),
        "LTE numerology: OcuSync 2 video and control, and the DroneID burst. "
        "Also LTE and 5G NR, which are the false alarms to worry about.",
    ),
    "ocusync_30k": Numerology(
        "ocusync_30k", 30e3, (22e3, 30e3),
        "The hypothesis for OcuSync 3 and O4, from a fielded detector that "
        "consistently measured a 28 kHz line on DJI links. The underlying "
        "subcarrier spacing was not verified by this project's research.",
        verified=False,
    ),
    "wifi": Numerology(
        "wifi", 312.5e3, (240e3, 260e3),
        "802.11a/g/n: 3.2 us symbols with a 0.8 us prefix give a 250 kHz line. "
        "Present in both drone bands almost everywhere.",
    ),
})


@dataclass(frozen=True)
class CyclicResult:
    """What one numerology's test found."""

    name: str
    peak: float
    """Height of the strongest line in the window, normalised (0 to 1-ish)."""
    alpha_hz: float
    """Where it sat: the symbol rate including the cyclic prefix."""
    contrast: float
    """Peak over the median of the rest of the window. Near 1 means no line."""
    lag_samples: int
    verified_numerology: bool = True

    @property
    def cp_fraction(self) -> float:
        """Prefix length as a fraction of the FFT, implied by ``alpha_hz``.

        ``alpha = spacing / (1 + cp_fraction)``, so a 1/14 prefix on a 15 kHz
        numerology puts the line at 14 kHz.  Zero when no line was found.
        """
        if self.alpha_hz <= 0.0:
            return 0.0
        spacing = NUMEROLOGIES[self.name].subcarrier_spacing_hz if self.name in NUMEROLOGIES else 0.0
        if spacing <= 0.0:
            return 0.0
        return float(spacing / self.alpha_hz - 1.0)

    def to_dict(self) -> dict[str, float | str | bool]:
        return {
            "name": self.name,
            "peak": round(float(self.peak), 6),
            "alpha_hz": round(float(self.alpha_hz), 1),
            "contrast": round(float(self.contrast), 3),
            "cp_fraction": round(self.cp_fraction, 4),
            "lag_samples": int(self.lag_samples),
            "verified_numerology": bool(self.verified_numerology),
        }


def caf_ncc(x: np.ndarray, lag: int) -> np.ndarray:
    """Normalised cyclic autocorrelation of ``x`` at one delay.

    ``|FFT(x[lag:] * conj(x[:-lag]))| / (N * mean|x|^2)``.  For circular
    Gaussian noise every bin averages ``sqrt(pi) / (2 * sqrt(N))``, about
    0.886 / sqrt(N), so the floor falls as the analysis window grows; that is
    the number to compare a peak against.
    """
    signal = np.asarray(x, dtype=np.complex128).ravel()
    lag = int(lag)
    if lag <= 0:
        raise ValueError(f"lag must be positive, got {lag}")
    if signal.size <= lag + 1:
        return np.zeros(0, dtype=np.float64)
    signal = signal - signal.mean()
    power = float(np.mean(np.abs(signal) ** 2))
    if power <= 0.0:
        return np.zeros(0, dtype=np.float64)
    product = signal[lag:] * np.conj(signal[:-lag])
    spectrum = np.abs(np.fft.fft(product))
    return spectrum / (product.size * power)


def peak_in_window(ncc: np.ndarray, sample_rate_hz: float,
                   window_hz: tuple[float, float]) -> tuple[float, float, float]:
    """Strongest line inside a cyclic-frequency window.

    Returns ``(peak, alpha_hz, contrast)`` where the contrast is the peak
    divided by the median of the other bins in the window: about 1 when there
    is no line, well above 2 when there is.
    """
    values = np.asarray(ncc, dtype=np.float64).ravel()
    if values.size == 0:
        return 0.0, 0.0, 0.0
    resolution = float(sample_rate_hz) / values.size
    lo = max(1, round(float(window_hz[0]) / resolution))
    hi = min(values.size // 2, round(float(window_hz[1]) / resolution) + 1)
    if hi <= lo:
        return 0.0, 0.0, 0.0
    segment = values[lo:hi]
    index = int(np.argmax(segment))
    peak = float(segment[index])
    alpha = float((lo + index) * resolution)
    rest = np.delete(segment, index)
    median = float(np.median(rest)) if rest.size else 0.0
    contrast = float(peak / median) if median > 0 else float("inf")
    return peak, alpha, contrast


def cyclic_profile(
    x: np.ndarray,
    sample_rate_hz: float,
    *,
    names: tuple[str, ...] = tuple(NUMEROLOGIES),
    chunk_s: float = 4e-3,
    overlap: float = 0.0,
    peak_weight: float = 0.65,
) -> dict[str, CyclicResult]:
    """Test a capture against each numerology and return one result per family.

    The signal is cut into chunks of ``chunk_s`` (4 ms by default, long enough
    to hold sixty 15 kHz symbols) and the per-chunk results are combined as
    ``peak_weight * max + (1 - peak_weight) * mean``.  Weighting the maximum
    is what makes a bursty emitter visible: a link with a 20 % duty cycle
    contributes a strong line in one chunk in five, which an average would
    dilute below the noise floor.
    """
    signal = np.asarray(x, dtype=np.complex128).ravel()
    fs = float(sample_rate_hz)
    if not 0.0 <= overlap < 1.0:
        raise ValueError(f"overlap must be in [0, 1), got {overlap}")
    chunk = max(round(float(chunk_s) * fs), 64)
    step = max(1, round(chunk * (1.0 - overlap)))
    starts = list(range(0, max(1, signal.size - chunk + 1), step)) or [0]

    out: dict[str, CyclicResult] = {}
    for name in names:
        numerology = NUMEROLOGIES[name]
        lag = numerology.lag_samples(fs)
        peaks: list[float] = []
        alphas: list[float] = []
        contrasts: list[float] = []
        for start in starts:
            piece = signal[start:start + chunk]
            if piece.size <= lag + 1:
                continue
            ncc = caf_ncc(piece, lag)
            peak, alpha, contrast = peak_in_window(ncc, fs, numerology.alpha_window_hz)
            peaks.append(peak)
            alphas.append(alpha)
            contrasts.append(contrast)
        if not peaks:
            out[name] = CyclicResult(name, 0.0, 0.0, 0.0, lag, numerology.verified)
            continue
        combined = peak_weight * max(peaks) + (1.0 - peak_weight) * float(np.mean(peaks))
        best = int(np.argmax(peaks))
        finite = [c for c in contrasts if np.isfinite(c)]
        out[name] = CyclicResult(
            name=name, peak=float(combined), alpha_hz=float(alphas[best]),
            contrast=float(np.median(finite)) if finite else float("inf"),
            lag_samples=lag, verified_numerology=numerology.verified,
        )
    return out


def noise_floor_ncc(n_samples: int) -> float:
    """Expected per-bin cyclic autocorrelation of complex Gaussian noise.

    ``sqrt(pi) / (2 * sqrt(N))``: the mean magnitude of a Rayleigh-distributed
    bin.  A peak needs to beat this by a comfortable factor, and because the
    window is searched for a maximum the effective floor is a few times higher.
    """
    n = int(n_samples)
    if n <= 0:
        return float("inf")
    return float(np.sqrt(np.pi) / (2.0 * np.sqrt(n)))


def kurtosis(x: np.ndarray, *, cap: float = 20.0) -> float:
    """``mean|x|^4 / (mean|x|^2)^2``, capped: 2.0 for noise, about 2/duty for bursts.

    A gated signal that is on a fraction ``d`` of the time reads about
    ``2 / d``, so it is a cheap burstiness measure to rank dwells with before
    spending anything on a spectrogram.
    """
    signal = np.asarray(x, dtype=np.complex128).ravel()
    if signal.size == 0:
        raise ValueError("kurtosis needs at least one sample")
    signal = signal - signal.mean()
    power = np.abs(signal) ** 2
    second = float(np.mean(power))
    if second <= 0.0:
        return float(cap)
    return float(min(np.mean(power ** 2) / (second ** 2), cap))
