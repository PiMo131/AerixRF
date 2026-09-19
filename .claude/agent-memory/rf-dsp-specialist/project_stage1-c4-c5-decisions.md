---
name: stage1-c4-c5-decisions
description: Durable Stage-1 detector decisions from the C4/C5 spec — per-bin p25 floor with band clamp, PFA-targeted (not fixed-dB) gates, L_eff incl. frequency smoothing, free Welch looks, grid-resolution guard, and the C3b merge defect.
metadata:
  type: project
---

Spec: `docs/design/stage1-c4-c5-spec.md` (2026-09-19, design only). Decisions that are expensive to
re-derive:

- **Noise floor = per-bin 25th percentile over frames**, bias-corrected to the mean by
  `Q25(L)` (`0.2877` at L=1, `0.6339` at L=4), then clamped to `F_ref ± 10 dB` where `F_ref` is the
  median over bins. p25 not median: tolerates 75 % bin occupancy (Wi-Fi channels) at only ~0.05 dB
  extra jitter. The clamp is what stops a continuously occupied bin self-blinding; the occupant then
  surfaces as an edge-clipped wideband event (`wifi_like_wideband`), which is the wanted behaviour.
- **Thresholds must be specified as P_fa, not dB.** `energy.detect` frequency-smooths by
  `300 kHz / bin_hz` bins before `detect_bursts`, so effective looks vary by mode: ~13 at
  15.36 MS/s/1024 but only ~2 at 100 MS/s/1024. A fixed dB gate is 6+ dB wrong between modes — this
  was an unrecorded second half of C4. Targets: arm 1e-6, hold 2e-3, solved against Gamma(L_eff).
- **Welch looks are free at the canonical rate**: `_TARGET_FRAMES = 4000` gives hop = 3.75 × fft_size,
  so only 27 % of samples are examined. `L = floor(hop/fft_size)` averaging costs zero time
  resolution and takes coverage to 80 %. Detector-local only — the canonical 1024/Hann/hop-512 STFT
  and the ML tensor must not change.
- **C3b (new defect, must land with C4)**: `CLUSTER_MAX_MERGE_HZ = 1 MHz` is a *floor* on the merge
  radius. Harmless while BWs were inflated to 5 MHz; once BWs are correct (300–400 kHz) a 1 MHz merge
  radius destroys the 1 MHz grid the raster test is looking for. Needs `min(...)` semantics and
  `merge_hz <= min(Δ)/3`.
- **Grid guard**: `R ≈ exp(−2π²σ²/Δ²)` with `R_MIN = 0.93` → total centre-error budget `σ ≤ 0.0606·Δ`.
  G1 `bin_hz ≤ Δ/20`, G2 median burst BW ≥ 8 bins (the −6 dB edge walk needs bins to walk over; this
  is the term that actually caused R = 0.27–0.61 on RFUAV, not G1). No shipping receiver config
  (12.288 / 13.44 / 15.36 / 20 MS/s at 1024) trips G1 — only the 100 MS/s bench column.
- Bench `full_band` is **kept** as a documented resolution-limited column plus a new `full_band_4096`
  column; it is the only mode that sees a hop span wider than the 12 MHz dwell.

**Why:** C4/C5 were the two remaining root causes from [[stage1-rc-defects]]; C4 changes the
detector's operating point everywhere, so the reasoning behind each constant needs to survive.
**How to apply:** before touching Stage-1 gating, re-read this — especially the L_eff point, which is
invisible in `bursts.py` (the smoothing happens in `energy.py`).
