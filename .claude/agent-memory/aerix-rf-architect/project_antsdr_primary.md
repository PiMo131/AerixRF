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
User answers 2026-09-19: 2nd-SD-card image trial APPROVED (persistent 2R2T NOT approved); both bands equally important; HackRF 2026-09-04 sessions NOT retrievable (Tier C blocked until side-by-side capture); user will have O3/O4 aircraft, O2 uncertain; wants more use of CSDN corpus + public datasets. 2026-09-19 state: Stage-1 link-signature rules (bursts/raster/energy) live with FA budget met on 1,160 ambient windows; UHD-mode trial: 2 RX + timestamps + overflow reporting, 15.36 sc16/20 sc8 clean short-run, 600 s soak failed with 212 KB host UDP buffers (needs user sysctl); non-DJI targets ranked — legal flags A (MAVLink payload), B (video content), C (Wi-Fi frames) await user ruling; top-3 = RFUAV RC-transmitter subset, ExpressLRS validation, analog 5.8 GHz carrier grid. User rulings 2026-09-19: legal flag A (passive MAVLink/SiK payload decode) APPROVED for research; B (video content) APPROVED for research; C (Wi-Fi frames) → frame parsing belongs to the ESP32 system, AERIX RF does RF-level detection only. TDOA IS IN SCOPE ⇒ UHD image is the target path (timestamps, 2 RX) pending the buffered soak; build a `uhd` producer for ProcessIQSource. Field-box hardware/disk still unanswered. Keep DSP/classify/decode hardware-neutral; HackRF must keep working. See [[host-environment-2026-09]] and [[user-directive-style]].
