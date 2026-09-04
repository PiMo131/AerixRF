"""IQ -> spectrogram (the 'RF image') and PNG encoding.

Kept dependency-light: numpy + scipy.fft (pocketfft, multithreaded) for the
STFT, Pillow for the PNG. The same spectrogram feeds both the detector (as a dB
power matrix) and the uploaded image, so training data and live data are
produced by one pipeline.

Real-time budget: a 20 Msps / 1 s window must process in well under the 1 Hz
loop period. The heavy cost is the number of STFT frames (n_samples / hop). A
dense 50 %-overlap STFT over 20e6 samples is ~39 000 frames (a 160 MB matrix)
and neither the detector nor the (thumbnailed) PNG needs anywhere near that
time resolution. So when ``hop`` is left to the default we *cap the frame
count* by widening the hop -- decimating the time axis -- which keeps coarse
time/freq features (envelope, cadence, occupied bandwidth, SNR) intact while
cutting FFT work, allocation, and the per-element log by ~10x. An explicit
``hop`` is always honoured unchanged.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import scipy.fft as sfft

# Cap the STFT at ~this many time frames when hop is chosen automatically. A
# 3 ms drone burst still spans ~12 frames at 20 Msps, so bursts/cadence survive.
_TARGET_FRAMES = 4000

# Cache the (float32) analysis window per fft_size -- np.hanning is pure Python
# overhead we do not want on every 1 Hz call.
_WIN_CACHE: dict[int, np.ndarray] = {}


def _window(fft_size: int) -> np.ndarray:
    win = _WIN_CACHE.get(fft_size)
    if win is None:
        win = np.hanning(fft_size).astype(np.float32)
        _WIN_CACHE[fft_size] = win
    return win


@dataclass
class Spectrogram:
    freqs_hz: np.ndarray   # [F] baseband bin centres, fftshifted (negative..positive)
    power_db: np.ndarray   # [T, F] power in dB (relative to full scale)
    sample_rate: float
    hop: int | None = None  # samples between STFT frames (time-axis step)


# Zero-IF receivers (HackRF included) put a DC / LO-leak spike at the centre
# bin that can sit 40+ dB above the floor with no antenna attached. Left in, it
# is a permanent "detection" at exactly the tuned frequency. We subtract the
# window mean and then blank the centre +-_DC_BLANK_BINS bins by interpolating
# their neighbours (58 kHz of 20 MHz at fft 1024 -- nothing we care about).
_DC_BLANK_BINS = 1


def compute(iq: np.ndarray, sample_rate: float, fft_size: int = 1024,
            hop: int | None = None, remove_dc: bool = True) -> Spectrogram:
    """STFT of complex IQ -> [time, freq] dB power matrix (two-sided, centred).

    ``hop`` defaults to a value that caps the frame count (see module docstring);
    pass an explicit ``hop`` to force a specific time resolution. ``remove_dc``
    suppresses the receiver's DC spike (see ``_DC_BLANK_BINS``).
    """
    iq = np.asarray(iq, dtype=np.complex64)
    if remove_dc and iq.size:
        iq = iq - np.mean(iq).astype(np.complex64)
    if iq.size < fft_size:
        iq = np.pad(iq, (0, fft_size - iq.size))
    n = iq.size
    if hop is None:
        # Cap frames at ~_TARGET_FRAMES but never denser than 50 % overlap.
        hop = max(fft_size // 2, -(-n // _TARGET_FRAMES))

    win = _window(fft_size)
    frames = np.lib.stride_tricks.sliding_window_view(iq, fft_size)[::hop]
    # frames * win is a fresh temp, so pocketfft may overwrite it in place.
    spec = sfft.fft(frames * win, axis=1, workers=-1, overwrite_x=True)
    spec = sfft.fftshift(spec, axes=1)

    # Power (float32 throughout; python-scalar ops do not upcast under NEP 50).
    scale = np.float32(1.0 / (fft_size * fft_size))
    power = (spec.real * spec.real + spec.imag * spec.imag) * scale
    power_db = (10.0 * np.log10(power + np.float32(1e-12))).astype(np.float32, copy=False)
    if remove_dc and fft_size >= 8:
        c = fft_size // 2
        k = _DC_BLANK_BINS
        left = power_db[:, c - k - 3:c - k]
        right = power_db[:, c + k + 1:c + k + 4]
        fill = 0.5 * (left.mean(axis=1) + right.mean(axis=1))
        power_db[:, c - k:c + k + 1] = fill[:, None]

    freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate))
    return Spectrogram(freqs_hz=freqs.astype(np.float64),
                       power_db=power_db,
                       sample_rate=sample_rate,
                       hop=hop)


def to_png(spec: Spectrogram, max_width: int = 1024, max_height: int = 512) -> bytes:
    """Grayscale PNG of the spectrogram, freq on the vertical axis.

    Normalised per-image to [floor, peak] so a faint burst is still visible.
    Downsampled to <= max_width x max_height to keep the upload small. The
    spectrogram is already time-decimated for the detector; that is far more
    columns than the thumbnail keeps, so the image loses nothing visible.
    """
    from PIL import Image

    p = spec.power_db.T  # [freq, time]
    # Robust normalisation: 5th percentile floor -> 99.5th percentile peak.
    lo = np.percentile(p, 5.0)
    hi = np.percentile(p, 99.5)
    if hi <= lo:
        hi = lo + 1.0
    img = np.clip((p - lo) / (hi - lo), 0.0, 1.0)
    img = (img * 255.0).astype(np.uint8)
    im = Image.fromarray(img, mode="L")
    if im.width > max_width or im.height > max_height:
        im.thumbnail((max_width, max_height))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
