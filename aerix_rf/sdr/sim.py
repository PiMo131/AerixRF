"""Synthetic IQ for testing the detection chain without a HackRF.

Generates complex noise, optionally with a bandlimited burst (a stand-in for a
DJI DroneID / OcuSync OFDM burst) repeated at a ~600 ms cadence. Good enough to
prove the detector fires on a drone-like signal and stays quiet on noise.
"""

from __future__ import annotations

import numpy as np


def synth_iq(sample_rate: float, duration_s: float, *, drone: bool = True,
             snr_db: float = 15.0, burst_bw_hz: float = 10e6,
             burst_ms: float = 3.0, cadence_s: float = 0.6,
             seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(sample_rate * duration_s)
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)
    iq = noise.astype(np.complex64)
    if not drone:
        return iq

    burst_len = max(16, int(burst_ms * 1e-3 * sample_rate))
    amp = 10.0 ** (snr_db / 20.0)
    step = max(burst_len, int(cadence_s * sample_rate))
    t0 = int(0.01 * sample_rate)
    while t0 < n:
        seg = min(burst_len, n - t0)
        s = rng.standard_normal(seg) + 1j * rng.standard_normal(seg)
        # Bandlimit to burst_bw via an FFT mask -> a ~burst_bw-wide OFDM-like blob.
        freqs = np.fft.fftshift(np.fft.fftfreq(seg, d=1.0 / sample_rate))
        S = np.fft.fftshift(np.fft.fft(s))
        S[np.abs(freqs) > burst_bw_hz / 2.0] = 0.0
        s = np.fft.ifft(np.fft.ifftshift(S))
        iq[t0:t0 + seg] += (amp * s).astype(np.complex64)
        t0 += step
    return iq
