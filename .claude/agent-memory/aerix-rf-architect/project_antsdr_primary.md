---
name: antsdr-primary-pivot
description: As of 2026-09-18 ANTSDR E200/AD9361 is the PRIMARY AERIX RF receiver; HackRF is secondary/reference. Workstreams A-E defined by user.
metadata:
  type: project
---

On 2026-09-18 the user redefined the roadmap: ANTSDR E200 (AD9361) is now the PRIMARY target receiver; HackRF remains a supported secondary/test/reference backend. The old "Phase 3 = ANTSDR, don't start until Phase 1 exit" ordering in `AERIX_RF_ANTSDR_PROJECT.md` is obsolete and must be rewritten.

**Why:** User decision; the ANTSDR is (probably) physically attached to the dev machine and datasets are wanted locally for ML/protocol work.

**How to apply:** Five parallel workstreams were commissioned:
- A: ANTSDR bring-up — A1 hardware discovery (no firmware flashing), A2 `IQSource` backend, A3 canonical live IQ representation (rf-dsp-specialist; defines the ML preprocessing target), A4 acceptance = ANTSDR capture → session → replay → existing DroneID decoder → CRC-valid decode, with the 2026-09-04 HackRF Mini 3 session as golden reference.
- B: download all accessible RF/UAV datasets to `~/rf-datasets/` (outside git), master manifest, gated-dataset TODOs for user.
- C: `research/briefs/rf-datasets.md` dataset table + engineering literature review.
- D: dataset normalization plan — must follow A3, never destroy originals, split by recording/device not random frames.
- E: CSDN/local research corpus inventory → `research/index.md`.
Keep DSP/classify/decode hardware-neutral; HackRF must keep working. See [[host-environment-2026-09]] and [[user-directive-style]].
