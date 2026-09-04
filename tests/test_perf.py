"""Real-time budget guard: a 20 Msps / 1 s window must process fast enough for
the 1 Hz loop. Uses a generous bound and best-of-N so it won't flake on a
loaded / slow CI box; set AERIX_SKIP_PERF=1 to skip entirely.
"""

import os
import time

import pytest

from aerix_rf.dsp import spectrogram
from aerix_rf.detect import energy
from aerix_rf.sdr.sim import synth_iq

SAMPLE_RATE = 20e6
CENTER_MHZ = 2431.5
BUDGET_MS = 600.0     # generous vs the < 400 ms target; loop period is 1000 ms
RUNS = 3


@pytest.mark.skipif(os.environ.get("AERIX_SKIP_PERF") == "1",
                    reason="perf test skipped via AERIX_SKIP_PERF=1")
def test_20msps_window_under_budget():
    # Build IQ and warm up outside the timed region.
    iq = synth_iq(SAMPLE_RATE, 1.0, drone=True, snr_db=15.0,
                  burst_bw_hz=8e6, cadence_s=0.06, seed=1)
    spec = spectrogram.compute(iq, SAMPLE_RATE, fft_size=1024)
    det = energy.detect(spec, CENTER_MHZ)

    best_ms = float("inf")
    for _ in range(RUNS):
        t = time.perf_counter()
        spec = spectrogram.compute(iq, SAMPLE_RATE, fft_size=1024)
        det = energy.detect(spec, CENTER_MHZ)
        best_ms = min(best_ms, (time.perf_counter() - t) * 1e3)

    assert best_ms < BUDGET_MS, f"compute+detect {best_ms:.0f} ms exceeds {BUDGET_MS:.0f} ms"
    # Sanity: still a valid detection on the drone-like input.
    assert det.score > 0.60, det
