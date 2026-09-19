# AERIX RF — Project Status (living document)

*Maintained by the architect session; updated with every commit that changes scope, plan or evidence.
Last update: 2026-09-19. Audience: technical manager. One page; details link to the repo.*

## 1. Scope — what AERIX RF is (and is not)

AERIX RF is the **passive, receive-only RF/SDR** side of AERIX drone detection. AERIX's ESP-based
receivers hear Open Drone ID broadcasts; AERIX RF covers what they cannot: DJI OcuSync-family links,
other control/video links, analog and digital FPV. It **detects** RF activity, **classifies** it, and
**decodes** where the protocol allows (proven: DJI DroneID on OcuSync 2; OcuSync 3/3+ expected decodable, untested; O4 payload encrypted).

It never transmits, jams, spoofs, deauthenticates or interrogates. Retention and privacy rules are
enforced at ingest (decoded operator positions expire after 7 days).

Primary receiver since 2026-09-18: **ANTSDR E200** (AD9361, Zynq-7020, Gigabit Ethernet).
Secondary/reference receiver: **HackRF / HackRF Pro** (the first field-tested platform, still supported).

## 2. Goals and success criteria

| Goal | Success criterion | Status |
|---|---|---|
| G1 Trustworthy RF instrument on the E200 | live capture → self-describing session → deterministic replay; measured, not assumed, sample integrity | **Met** (2026-09-18/19) |
| G2 DJI DroneID decode on the E200 (acceptance "A4") | CRC-valid frame captured by the E200 from a real OcuSync-2 aircraft | Software proven on real IQ; **needs an O2 aircraft** |
| G3 Honest detection/classification benchmark | claims backed by same-receiver positives and real ambient negatives; leakage-safe | Pipeline built; **needs the positives campaign** |
| G4 Server integration | RF events, evidence, correlation, retention in AERIX | Unchanged from the HackRF phase; resumes after G2/G3 |
| G5 Future: multi-receiver localisation | timestamps + loss counters available on the receiver | Not on the current firmware; **decision pending** |

Evidence discipline (applies to every claim below): 1 RF candidate/morphology → 2 probabilistic
classification → 3 protocol-specific evidence → 4 CRC-valid decode → 5 operator ground truth.
A stage-1 candidate is never reported as a confirmed drone.

## 3. Plan — phases and workstreams

- **A. ANTSDR bring-up** — hardware discovery ✅, receiver backend ✅, canonical signal representation ✅,
  acceptance A4 (decode on the E200) ⏳ aircraft-dependent.
- **B/C. Datasets** — download all accessible public RF/UAV datasets, catalogue them, review usefulness ✅
  (ongoing for gated sets).
- **D. Normalisation + benchmark** — one canonical representation for live and training data,
  leakage-safe splits, receiver-confound controls ✅ built; first honest results in ✅.
- **E. Research corpus** — 1,113 unique local sources indexed with evidence grades ✅.
- **F. Positives campaign** — capture real aircraft (O2 for decode; O3/O4 for detection) on the E200 with
  an operator timeline (`docs/field/positives-protocol.md`) ⏳ next.
- **G. Firmware trial** — second-SD-card UHD-style image (timestamps, higher rate) ⏳ approved, preparing.
- **Server integration** — after F.

## 4. Progress to date (what is actually proven)

**Proven on the E200 hardware (receive-only, measured):**
- Live pipeline at 12.288 MS/s: capture → detect → classify → decode → session → bit-exact replay.
- Sample integrity: with the AD9361's built-in test tone, **0 lost samples in 7.4 billion** over 10 minutes at
  12.288 and 13.44 MS/s; 15.36 MS/s is unusable on this firmware. The only loss mechanism found — CPU
  contention inside the Python process — is eliminated by the new producer-process backend, which passed the
  same test both idle and under heavy load.
- Sessions record device read-back state, clipping, and exact host-side loss; `scan`/`baseline` sweeps work.

**Proven on independent real DJI recordings:** our DroneID decoder reproduces the published telemetry of
the RUB-SysSec captures (Mavic Air 2, Mini 2) bit-exactly and is frozen as a regression fixture. Earlier
(2026-09-04) a Mini 3 was decoded live with the HackRF.

**Synthetic-only (level 1–2) so far:** decoder sensitivity knee (≈3 dB in-band) and its robustness to
strong adjacent emitters; the classifier feature set's device-invariance properties.

**First benchmark result — deliberately reported as a negative:** trained on anechoic public positives vs
one room's Wi-Fi-heavy negatives, a classifier learned "quiet band = drone" (false-alarm rate 0 on five
sessions, ~100 % on a quieter one). That is exactly the confound the design predicted; it is why the
positives campaign is the next step, not more training.

## 5. Key measured facts and decisions

| Topic | Decision / fact | Evidence |
|---|---|---|
| Canonical representation | 15.36 MS/s, 1 s windows, FFT 1024, absolute dBFS | design memo + synthetic sweeps |
| ANTSDR live profile | 12.288 MS/s default, 13.44 validated, cs16 full-scale 2048, manual gain | measured (BIST, soaks) |
| Firmware | stay on stock IIO image; trial a UHD-style image from a second SD card (approved) | measured ceiling ≈59 MB/s; no timestamps on IIO |
| Loss handling | producer in its own process + exact ring accounting; rate monitor with real deficits | measured |
| Decoder | validated on real IQ; blocker-robust via zc6-ranked centre selection | real IQ + synthetic bench |
| Benchmark honesty | no detection-probability or cross-receiver claim yet; receiver-ID probe is a mandatory control | first results §5 of the design doc |

## 6. Open items, risks, needs

**Needs from the team**
- First campaign measurement: the **Avata (O3) plaintext-decode test** (available). For a guaranteed O2
  reference: Mini 4K / Mini 2 SE / Mini 2 / Mini 3 non-Pro / Mavic Air 2. O4 aircraft for detection-only positives
  and the O4 CRC-identification experiment.
- Answers: is multi-receiver/TDOA in scope (drives the firmware decision)? Field-box hardware and disk budget
  (raw cs16 is ≈177 GB/h, so capture must be event-gated)?
- Housekeeping: IEEE DataPort / Kaggle credentials for gated datasets; approval for the very large sets
  (DroneRFa ≈570 GB, RFUAV up to 1.3 TB).

**Main risks**
- Without same-receiver positives, no classifier claim is defensible (mitigation: campaign F).
- The IIO firmware has no timestamps: fine for detection, a dead end for TDOA (mitigation: SD-card trial G).
- Live classifier features cost ≈1.2 s per second of signal on this workstation; the field box may need the
  cheaper v1 features (decision pending hardware choice).

## 7. Where to look

`README.md` (status log) · `AERIX_RF_ANTSDR_PROJECT.md` (plan, §0 decisions/questions) ·
`docs/design/*.md` (architecture memos) · `research/briefs/*.md` (evidence briefs) ·
`docs/BACKLOG.md` (engineering backlog) · `docs/field/positives-protocol.md` (campaign checklist).
Tests: 396 passing. Commits on `main`: 16 since the pivot.
