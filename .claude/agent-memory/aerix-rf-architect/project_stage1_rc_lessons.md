---
name: stage1-rc-lessons
description: 2026-09-19 RC-positives bench on RFUAV — Stage-1 rules had structural defects (period_test dt=0 degeneracy, event cap as time cut, unbounded clustering, single-look floor, bin-pitch limit); also a lesson about reading bench JSON before declaring a result
metadata:
  type: project
---

Stage-1 link-signature rules were evaluated against 31 RFUAV RC transmitters (100 MS/s X310, crowded 2.4 GHz):
136 level-1 labels on 28/31 models vs 0/100 ANTSDR ambient; level-2 grid/family rules 0/428.
Diagnosis (docs/design/stage1-rc-positives-2026-09-19.md) found five structural defects, not tuning:
period_test dt=0 degeneracy (always passes at range top), 64-event cap = first ~5 ms only, cluster chaining
without max width, single-look periodogram floor (BW over-estimated 15–50×), grid test needs bin ≤ Δ/20
(fine at canonical 15.36 MS/s, impossible at 100 MS/s/1024 bins).

**Why:** the ambient FA budget had been declared "met" while grid rules were "not exercised" — the positives
bench is what exposed that the rules were structurally blind. Any future "FA budget met" claim must be paired
with a positives bench on real recordings.

**How to apply:** (1) never trust a level-2 rule until it has fired on real positives; (2) when a bench summary
looks like all-zero, read the per-record labels before reporting — I misreported "0/31" once because I looked
for a `counts` key that did not exist; (3) fix order matters: C3 clustering before C2 cap; (4) C4 per-bin floor is
detector-local — do NOT change the canonical STFT/tensor for it; (5) evidence from RFUAV stays level 1–2
(third-party receiver, crowded band) — same-receiver single-TX captures are the conversion path.
