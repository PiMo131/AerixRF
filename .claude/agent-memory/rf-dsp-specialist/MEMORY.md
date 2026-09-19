# rf-dsp-specialist memory

- [Canonical representation decision](project_canonical-representation.md) — 15.36 MS/s / cs16 / 12 MHz usable band, and the reasoning that is hard to re-derive.
- [Dataset normalization pipeline](project_dataset-normalization.md) — Workstream D preprocessing design + verified DroneRF/Zenodo/RUB on-disk formats and the leakage traps.
- [Decode SNR bench pitfalls](project_decode-snr-bench.md) — the non-monotonic decode curve, snr50_final_db, and the argmax(psd) blocker weakness.
- [Stage-2 features_v2 + first benchmark](project_features-v2-benchmark.md) — 292-D absolute-Hz features on the 10 MHz common band, receiver-ID probe thresholds, and why the benchmark is PFA-only.
- [First benchmark results (2026-09-18)](project_first-benchmark-results.md) — the chamber-vs-ambient shortcut, the fac0aacf receiver-state outlier, and why below-chance BA is not a pass.
- [Blocker failure split (2026-09-18)](project_blocker-failure-split.md) — the wideband-blocker knee is centre-hypothesis selection, not sync/CFO/turbo.
- [Centre-hypothesis scorer](project_centre-hypothesis-scorer.md) — zc6 not zc4 ranks centres; ranked full-sync + gated refinement fixes the wb blocker, edge de-bias rejected.
- [Stage-1 link-signature rules](project_stage1-link-signatures.md) — Rayleigh lattice test for hop rasters, the 60 kHz centre-jitter budget, and why 2 MHz rasters and 640 ms cadence need multi-dwell.
- [Analog 5.8 GHz FPV detector](project_analog-fpv-58.md) — carrier = −12 dB edge midpoint (never the peak), grid false-match ~13 %, Band A == U-NII-3, seam comb, duty-1.0 floor trap.
- [SiK 2-GFSK T1 demod](project_sik-gfsk-t1.md) — post-detection matched filter = the missing dB, OBW98 calibration, preamble-gated 2-bit sync arithmetic.
