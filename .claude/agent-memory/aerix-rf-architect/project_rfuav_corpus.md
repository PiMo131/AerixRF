---
name: rfuav-corpus
description: RFUAV corpus (109 GB, 37 models incl. 31 RC transmitters) fully local and prepared 2026-09-19; how it is used (RC positives bench, classifier retrain) and its evidence limits (X310 receiver, crowded band)
metadata:
  type: project
---

RFUAV (arXiv 2503.09033, Apache-2.0) is fully downloaded (~/rf-datasets/rfuav/original, 109 GB, SHA-verified) and
prepared at canonical 15.36 MS/s (~/rf-datasets/rfuav/prepared, 349 recordings, 1.4 GB) as of 2026-09-19.
Recordings are 100 MS/s complex64 1 s slices, centre 2440 MHz, USRP X310, crowded 2.4 GHz (≈95 % of windows
carry Wi-Fi-like occupancy). 31 of 37 models are RC transmitters — the only real RC-link positives we have.

**Why:** it is the largest legally open RF/UAV corpus and the one that exposed the Stage-1 structural defects
(see [[stage1-rc-lessons]]); it also drives the first classifier retrain with real RC positives.

**How to apply:** treat results on it as level 1–2 (third-party receiver, different band conditions); any
"drone-vs-background" classifier number trained on RFUAV positives vs ANTSDR ambient negatives MUST be paired
with the receiver-ID probe (chamber-vs-ambient confound, see [[benchmark-lesson]]) and a cross-receiver holdout
(RUB/Zenodo DJI). Prepare has no resume flag — move `prepared/` aside before rerunning; the 6 short pack-tail
slices are legitimate (`truncated_tail`). Bench `bench/stage1_rc_positives.py` takes ~15 min with 6 workers and
starves the 50 ms detect_bursts timing test while running.
