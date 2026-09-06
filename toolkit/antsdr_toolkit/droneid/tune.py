"""Get from a wideband capture to something :mod:`.receiver` can decode.

The receiver wants a burst centred at zero and sampled at a multiple of the
15 kHz subcarrier spacing.  A recording almost never arrives that way.  You
tune an E200 to a channel centre, sample at whatever the host link sustains,
and the aircraft puts its DroneID burst wherever inside that span it likes:
the RUB-SysSec captures this toolkit is validated against sit 9.6 MHz off
centre in a 50 MSPS recording.  This module closes that gap - find the band,
mix it down, resample - and it is the difference between a receiver that works
on prepared files and one that works on captures.

How the band is found
---------------------
A DroneID burst occupies 600 subcarriers at 15 kHz, which is exactly 9 MHz,
and it has hard edges.  So the search does not threshold and hunt for
contiguous runs; it slides a 9 MHz window across the averaged power spectrum
and reads off where the window is brightest.  That answers the question asked
- where are 9 MHz of signal - rather than the question a threshold answers,
which is where the signal is louder than some number that depends on how much
noise is in the rest of the capture.

The same idea appears in :func:`~.receiver.integer_offset_bins`, one FFT
further down the chain, and for the same reason.

What it does not do
-------------------
It does not identify the emitter.  Nine megahertz of Wi-Fi, a video downlink,
or another manufacturer's OFDM will all be returned if they are the brightest
thing in the capture.  The result is a *candidate centre*, and it is the
receiver's burst detection that decides whether anything is there.  That is
why :func:`centres_hz` returns several: handing all of them to the receiver
and keeping whatever detects costs one pass each and cannot be fooled.
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from . import constants as C

__all__ = [
    "DEFAULT_MAX_CENTRES",
    "centres_hz",
    "power_spectrum",
    "prepare",
    "to_baseband",
]

#: How many candidate bands :func:`centres_hz` returns by default. More than
#: one because a capture can hold two aircraft, and because the brightest 9 MHz
#: in the span is not always the one that decodes.
DEFAULT_MAX_CENTRES = 3

#: Spectrum resolution for the band search. 2048 bins over a 50 MSPS capture is
#: 24 kHz per bin, fine enough to place a 9 MHz band to well under a subcarrier
#: and coarse enough that one burst of a few hundred microseconds still
#: averages into something smooth.
_NFFT = 2048


def power_spectrum(x: np.ndarray, *, n_fft: int = _NFFT) -> np.ndarray:
    """Mean periodogram of ``x``, fft-shifted, ``n_fft`` bins.

    Averaged over as many whole windows as the capture holds, Hann-weighted so
    that a strong burst does not smear across the whole span through the
    sidelobes of a rectangular window.
    """
    xs = np.asarray(x, dtype=np.complex128).ravel()
    n = int(n_fft)
    if xs.size < n:
        raise ValueError(f"need at least {n} samples for a {n}-bin spectrum, got {xs.size}")
    window = np.hanning(n)
    frames = xs.size // n
    total = np.zeros(n, dtype=np.float64)
    for i in range(frames):
        total += np.abs(np.fft.fftshift(np.fft.fft(xs[i * n:(i + 1) * n] * window))) ** 2
    return total / frames


def centres_hz(x: np.ndarray, sample_rate_hz: float, *,
               max_centres: int = DEFAULT_MAX_CENTRES,
               n_fft: int = _NFFT,
               width_hz: float | None = None,
               min_excess_db: float = 3.0) -> list[float]:
    """Candidate band centres relative to the capture's own centre, in Hz.

    Brightest first, non-overlapping, and only those carrying at least
    ``min_excess_db`` more power per bin than the capture's median bin, which
    is what keeps an empty recording from returning its own noise floor as a
    discovery.  An empty list means nothing in the span looks like an occupied
    channel of the right width.
    """
    fs = float(sample_rate_hz)
    width = C.occupied_bandwidth_hz() if width_hz is None else float(width_hz)
    power = power_spectrum(x, n_fft=n_fft)
    n = power.size
    bins = max(1, round(width / (fs / n)))
    if bins >= n:
        raise ValueError(
            f"a {width / 1e6:.3g} MHz band does not fit in a {fs / 1e6:.3g} MSPS capture")
    cumulative = np.concatenate([[0.0], np.cumsum(power)])
    window_power = cumulative[bins:] - cumulative[:-bins]  # sum over each placement
    floor = float(np.median(power)) * bins
    if floor <= 0:
        return []
    # Only placements that are a local maximum of the sliding energy, or sit
    # against an end of the span. Sliding a window onto a band makes its energy
    # climb, so every position on the way up is bright without being a band:
    # taking the brightest, excluding its neighbourhood and taking the next
    # brightest lands on that slope just outside the exclusion and reports the
    # shoulder of one signal as a second signal. A local maximum cannot.
    interior = np.ones(window_power.size, dtype=bool)
    interior[1:-1] = ((window_power[1:-1] >= window_power[:-2])
                      & (window_power[1:-1] >= window_power[2:]))
    order = np.argsort(-window_power)
    taken: list[int] = []
    for start in order:
        if len(taken) >= int(max_centres):
            break
        if window_power[start] < floor * 10 ** (float(min_excess_db) / 10.0):
            break
        if not interior[start]:
            continue
        if any(abs(int(start) - t) < bins for t in taken):
            continue
        taken.append(int(start))
    # Bin index to a frequency offset from the capture centre.
    return [((t + bins / 2.0) - n / 2.0) * (fs / n) for t in sorted(taken)]


def to_baseband(x: np.ndarray, sample_rate_hz: float, centre_hz: float, *,
                target_rate_hz: float = 15.36e6) -> np.ndarray:
    """Mix ``centre_hz`` down to zero and resample to ``target_rate_hz``.

    Resampling is rational and anti-aliased (``scipy.signal.resample_poly``),
    with the ratio taken exactly where it is exact: 50 MSPS to 15.36 is
    192/625 with nothing left over.  A rate whose ratio is irrational is
    approximated to within a part in ten thousand, which is a hundredth of a
    subcarrier over a whole burst.
    """
    from scipy.signal import resample_poly

    fs = float(sample_rate_hz)
    target = float(target_rate_hz)
    xs = np.asarray(x, dtype=np.complex128).ravel()
    if fs <= 0 or target <= 0:
        raise ValueError(f"sample rates must be positive, got {fs} and {target}")
    if float(centre_hz):
        n = np.arange(xs.size, dtype=np.float64)
        xs = xs * np.exp(-2j * np.pi * float(centre_hz) * n / fs)
    if math.isclose(fs, target, rel_tol=1e-9):
        return xs.astype(np.complex64)
    ratio = Fraction(target / fs).limit_denominator(10000)
    up, down = ratio.numerator, ratio.denominator
    if up <= 0:
        raise ValueError(f"cannot resample {fs} Hz to {target} Hz")
    return resample_poly(xs, up, down).astype(np.complex64)


def prepare(x: np.ndarray, sample_rate_hz: float, *,
            target_rate_hz: float = 15.36e6,
            max_centres: int = DEFAULT_MAX_CENTRES,
            **kwargs) -> list[tuple[float, np.ndarray]]:
    """Every candidate band of a capture, each as ``(centre_hz, baseband)``.

    The centre is relative to the capture's own centre frequency, so adding
    the recording's ``frequency`` metadata gives the absolute one.  Hand each
    array to :func:`~.receiver.process` and keep whatever detects; a capture
    already centred and at the target rate comes back as a single pass-through
    entry rather than being resampled for no reason.
    """
    fs = float(sample_rate_hz)
    found = centres_hz(x, fs, max_centres=max_centres, **kwargs)
    if not found:
        if math.isclose(fs, float(target_rate_hz), rel_tol=1e-9):
            return [(0.0, np.asarray(x, dtype=np.complex64).ravel())]
        return []
    return [(centre, to_baseband(x, fs, centre, target_rate_hz=target_rate_hz))
            for centre in found]
