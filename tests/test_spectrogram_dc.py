"""Receiver DC / LO-leak spike must not become a permanent detection at the tuned frequency."""

import numpy as np

from aerix_rf.dsp import spectrogram
from aerix_rf.detect import energy


def test_dc_spike_is_blanked():
    rng = np.random.default_rng(0)
    n = 2_000_000
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64) * 0.02
    iq = noise + np.complex64(0.0 + 0.02j)          # HackRF-like DC offset, same size as the noise RMS
    spec = spectrogram.compute(iq, 20e6, 1024)
    c = 512
    centre = spec.power_db[:, c - 4:c + 5].mean()
    elsewhere = spec.power_db[:, 100:400].mean()
    assert abs(centre - elsewhere) < 1.5
    det = energy.detect(spec, 2440.0)
    assert det.morphology == "noise", det


def test_remove_dc_can_be_disabled():
    n = 200_000
    iq = np.full(n, 0.0 + 0.05j, dtype=np.complex64)
    spec = spectrogram.compute(iq, 20e6, 1024, remove_dc=False)
    assert spec.power_db[:, 512].mean() > spec.power_db[:, 100].mean() + 40
