# rf-dsp-specialist memory

- [Canonical representation decision](project_canonical-representation.md) — 15.36 MS/s / cs16 / 12 MHz usable band, and the reasoning that is hard to re-derive.
- [Dataset normalization pipeline](project_dataset-normalization.md) — Workstream D preprocessing design + verified DroneRF/Zenodo/RUB on-disk formats and the leakage traps.
- [Decode SNR bench pitfalls](project_decode-snr-bench.md) — the non-monotonic decode curve, snr50_final_db, and the argmax(psd) blocker weakness.
- [Stage-2 features_v2 + first benchmark](project_features-v2-benchmark.md) — 292-D absolute-Hz features on the 10 MHz common band, receiver-ID probe thresholds, and why the benchmark is PFA-only.
- [First benchmark results (2026-09-18)](project_first-benchmark-results.md) — the chamber-vs-ambient shortcut, the fac0aacf receiver-state outlier, and why below-chance BA is not a pass.
- [Blocker failure split (2026-09-18)](project_blocker-failure-split.md) — the wideband-blocker knee is centre-hypothesis selection, not sync/CFO/turbo.
- [Centre-hypothesis scorer](project_centre-hypothesis-scorer.md) — zc6 not zc4 ranks centres; ranked full-sync + gated refinement fixes the wb blocker, edge de-bias rejected.
