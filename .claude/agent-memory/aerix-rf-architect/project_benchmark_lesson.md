---
name: benchmark-first-results-lesson
description: 2026-09-18 first cross-receiver benchmark — anechoic public positives vs one-room ambient negatives yields a chamber-vs-ambient discriminator (PFA 1.0 on a quiet session); receiver-ID probe PASS withdrawn (fold artefact); sidecars must record device read-back state and typed deficits.
metadata:
  type: project
---

First features_v2 benchmark (docs/design/features-and-benchmark.md §5): Tier D PFA = 0 on five Wi-Fi-saturated ANTSDR sessions and ≈1.0 on one quiet-band session (`a_iq_default`, raised+flattened floor, Wi-Fi absent) — the classifier learned "saturated band = background, quiet band = drone" because the only positives are anechoic Zenodo recordings. The receiver-ID probe's "PASS" (BA 0.43) was an evaluation artefact (GroupKFold folds with zero positive rows) and is WITHDRAWN. The old per-window `rate_warning` excluded 233/571 windows spuriously and shaped class composition.

**Why:** Nothing in the current corpus can support a PD or cross-receiver claim; the useful output was falsifying the classifier and exposing metadata gaps (sidecar `receiver.gain` None; requested-not-read-back device state).

**How to apply:** Highest-value acquisition = ANTSDR-captured drone positives with interleaved ON/OFF in ONE session (same room/front-end), operator-logged intervals, device state read back and recorded. Probe must use StratifiedGroupKFold with per-fold class/group guards and an INCONCLUSIVE verdict. Treat any "clean separation" between datasets as confound until a label-matched probe passes. See [[canonical-representation-decisions]], [[a4-acceptance-progress]].
