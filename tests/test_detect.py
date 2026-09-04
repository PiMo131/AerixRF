"""The core promise: the detector fires on a drone-like signal, stays quiet on noise."""

import numpy as np

from aerix_rf.dsp import spectrogram
from aerix_rf.detect import energy
from aerix_rf.sdr.sim import synth_iq

SAMPLE_RATE = 10e6      # smaller than the 20e6 field rate keeps the test fast
CENTER_MHZ = 2431.5


def _detect(iq):
    spec = spectrogram.compute(iq, SAMPLE_RATE, fft_size=1024)
    return energy.detect(spec, CENTER_MHZ)


def test_drone_signal_scores_high():
    iq = synth_iq(SAMPLE_RATE, 0.3, drone=True, snr_db=15.0,
                  burst_bw_hz=8e6, cadence_s=0.06, seed=1)
    det = _detect(iq)
    assert det.score > 0.60, det
    assert det.snr_db > 8.0
    assert det.occupied_bw_mhz > 4.0
    assert det.signature_class != "noise"


def test_noise_scores_low():
    iq = synth_iq(SAMPLE_RATE, 0.3, drone=False, seed=2)
    det = _detect(iq)
    assert det.score < 0.30, det
    assert det.signature_class == "noise"


def test_spectrogram_png_roundtrips():
    iq = synth_iq(SAMPLE_RATE, 0.2, drone=True, seed=3)
    spec = spectrogram.compute(iq, SAMPLE_RATE, fft_size=512)
    png = spectrogram.to_png(spec)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 100
