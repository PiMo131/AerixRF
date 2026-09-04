"""Time the RF DSP pipeline (compute + detect, plus to_png) on a 20 Msps window.

This mirrors the per-second work main.py does per window. Run:

    UV_PROJECT_ENVIRONMENT=.venv-perf uv run python bench/bench_pipeline.py

Prints best-of-N ms per stage; the real-time 1 Hz loop needs compute+detect
well under 1 s (target < 400 ms).
"""

from __future__ import annotations

import time

import numpy as np

from aerix_rf.dsp import spectrogram
from aerix_rf.detect import energy
from aerix_rf.sdr.sim import synth_iq

SAMPLE_RATE = 20e6      # field rate
CENTER_MHZ = 2431.5
FFT_SIZE = 1024
RUNS = 5


def _best(fn, *args):
    fn(*args)  # warm-up (JIT/thread-pool/window cache), not timed
    best = float("inf")
    out = None
    for _ in range(RUNS):
        t = time.perf_counter()
        out = fn(*args)
        best = min(best, time.perf_counter() - t)
    return best, out


def main() -> None:
    # Build IQ outside the timed region (synth_iq at 20M samples is itself slow).
    iq = synth_iq(SAMPLE_RATE, 1.0, drone=True, snr_db=15.0,
                  burst_bw_hz=8e6, cadence_s=0.06, seed=1)
    print(f"window: {iq.size} samples ({iq.size / SAMPLE_RATE:.1f} s @ "
          f"{SAMPLE_RATE / 1e6:.0f} Msps), fft_size={FFT_SIZE}")

    tc, spec = _best(lambda x: spectrogram.compute(x, SAMPLE_RATE, FFT_SIZE), iq)
    td, det = _best(lambda s: energy.detect(s, CENTER_MHZ), spec)
    tp, _png = _best(spectrogram.to_png, spec)

    frames, bins = spec.power_db.shape
    print(f"stft frames={frames} bins={bins} hop={spec.hop} "
          f"dtype={spec.power_db.dtype}")
    print(f"compute : {tc * 1e3:7.1f} ms")
    print(f"detect  : {td * 1e3:7.1f} ms")
    print(f"----------------------")
    print(f"c+d     : {(tc + td) * 1e3:7.1f} ms  (real-time budget < 1000 ms)")
    print(f"to_png  : {tp * 1e3:7.1f} ms  (only on windows we upload)")
    print(f"detection: score={det.score:.3f} snr={det.snr_db:.1f} "
          f"bw={det.occupied_bw_mhz:.1f}MHz bursts={det.burst_count} "
          f"cadence={det.cadence_ms} class={det.signature_class}")


if __name__ == "__main__":
    main()
