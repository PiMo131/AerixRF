---
name: first-benchmark-results
description: Why the 2026-09-18 features_v2 benchmark showed PFA=1.0 on one ANTSDR session and a below-chance receiver-ID probe - the chamber-vs-ambient shortcut, GroupKFold size-balancing, and the rate_warning false positives
metadata:
  type: project
---

Extends [[features-v2-benchmark]]. Write-up: `docs/design/features-and-benchmark.md` S5.

**The Stage-2 boundary learned on the local corpus is a chamber-vs-ambient discriminator, not a drone
detector.** Zenodo positives are anechoic (quiet band + one emitter); the ANTSDR ambient sessions are
Wi-Fi ch 6 at 2437 MHz saturating the entire 10 MHz dwell >95 % of the time at +24 dB. So the decision
rule is "saturated band = background, quiet band = drone". Any quiet ANTSDR window is a false alarm.

**Why:** we have no ANTSDR-captured positives, so the only within-receiver contrast available to the
classifier is scene occupancy.

**How to apply:** never read a Tier-A/B recall number from this corpus as detection skill; the single
highest-value acquisition is ANTSDR positives with an interleaved ON/OFF schedule *inside one session*
(same room, same front-end state), which removes the shortcut. Until then Tier D PFA is the only honest
metric.

Durable measured facts (recomputed from all 571 prepared ANTSDR rows, G3 masked):
- Session `fac0aacf` (300 s `a_iq_default`) is a **receiver-state** outlier, not a scene outlier: in-band
  median floor -78.6 dBFS vs -81.2..-83.7 for the other five, time-p99 -73.6 dBFS vs -56..-60 (band
  completely empty), and the passband *shape* changed (edge-minus-centre +1..+3 dB vs a U-shaped
  +7..+9.5 dB that all five other sessions share). A scene change cannot alter floor shape and a scalar
  gain change cannot flatten it -> front-end state (rf_bandwidth / AGC / port). 208 of 290 feature columns
  separate it with single-feature AUC exactly 0 or 1; the top separators are all scene-occupancy
  (`g4_widest_cluster_bw_hz` 9.7e4 vs 9.85e6 Hz, `g2_occ_frac_6db` 0.018 vs 0.989), *not* level - the
  per-bin floor subtraction correctly absorbed the 5 dB offset.
- Every ANTSDR sidecar has `receiver.gain mode=unknown, db=None`, so receiver-state changes are currently
  invisible in metadata. Log gain mode/db, rx_rf_bandwidth and antenna port per capture.
- **BA below chance is never a PASS.** `GroupKFold` balances folds by row count, so the 298-row session
  landed alone in fold 0 and fold 1 held 20 rows: 90 % of pooled out-of-fold predictions came from folds
  with zero Zenodo test rows. A constant predictor scores balanced accuracy exactly 0.5, so BA < 0.5 means
  an anti-correlated boundary on held-out groups = session-level domain shift, not absence of device leak.
  Probe needs StratifiedGroupKFold, a per-fold class guard, per-fold confusion output, and an
  INCONCLUSIVE verdict.
- The old per-window `rate_warning` is a trailing-window rate estimate and fires on loss-free runs
  (per-session cumulative ratios 0.67-1.27). It removed 121/122, 56/60 and 54/59 windows of the
  Wi-Fi-rich sessions, leaving the anomalous quiet session as 88 % of the ANTSDR class - i.e. the sidecar
  bug directly caused the probe's class composition. Replace with a typed `samples_deficit` (per window
  and per session) from a monotone sample counter.
