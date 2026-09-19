# AERIX RF — Project Status (living document)

*Maintained by the architect session; updated with every commit that changes scope, plan or evidence.
Last update: 2026-09-19 (evening). Audience: technical manager. One page; details link to the repo.*

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
| G2 DJI DroneID decode on the E200 (acceptance "A4") | CRC-valid frame captured by the E200 from a real OcuSync-2/3 aircraft | Software proven on real IQ; **next: Avata (O3+) test — checklist ready** |
| G3 Honest detection/classification benchmark | claims backed by same-receiver positives and real ambient negatives; leakage-safe | Pipeline built; **needs the positives campaign** |
| G4 Server integration | RF events, evidence, correlation, retention in AERIX | Unchanged from the HackRF phase; resumes after G2/G3 |
| G5 Future: multi-receiver localisation | timestamps + loss counters available on the receiver | **Available in UHD mode** (2 RX, per-packet timestamps, external clock) — trial in progress; scope decision pending |

Evidence discipline (applies to every claim below): 1 RF candidate/morphology → 2 probabilistic
classification → 3 protocol-specific evidence → 4 CRC-valid decode → 5 operator ground truth.
A stage-1 candidate is never reported as a confirmed drone.

## 3. Plan — phases and workstreams

- **A. ANTSDR bring-up** — hardware discovery ✅, receiver backend ✅, canonical signal representation ✅,
  acceptance A4 (decode on the E200) ⏳ aircraft-dependent.
- **B/C. Datasets** — download all accessible public RF/UAV datasets, catalogue them, review usefulness ✅
  (ongoing for gated sets). RFUAV corpus (109 GB, 349 recordings / 37 models incl. 31 RC transmitters) fully
  local; adapter handles XML-less recordings and short tail slices; full `prepare` at the canonical
  15.36 MS/s is **complete** (2026-09-19 evening: 349/349 recordings, 1.4 GB tensors; manifest updated).
  `features_v2` has been retrained on the RFUAV positives (§D).
- **D. Normalisation + benchmark** — one canonical representation for live and training data,
  leakage-safe splits, receiver-confound controls ✅ built; first honest results in ✅.
  **Update (2026-09-19 evening):** `features_v2` retrained on the 349 RFUAV positives vs. 449 ANTSDR
  ambient negatives; receiver-ID probe **CONDITIONAL** (balanced accuracy 0.647 — part of the class
  separation is receiver fingerprint, not signal content); cross-receiver holdout recall 0.875 (14/16)
  on the Zenodo set. Tier D receiver-state confound unchanged. Evidence level 2 at best; the blocking
  need is unchanged — drone positives captured on our own E200 (`docs/field/positives-protocol.md`).
  Doc: `docs/design/features-and-benchmark.md` §6.
- **E. Research corpus** — 1,113 unique local sources indexed with evidence grades ✅.
- **F. Positives campaign** — capture real aircraft (O2 for decode; O3/O4 for detection) on the E200 with
  an operator timeline (`docs/field/positives-protocol.md`) ⏳ next.
- **G. Firmware trial** — second-SD-card UHD image ✅ booted; 15.36 MS/s sc16 and 20 MS/s sc8 stream clean in
  short runs, one 10-min soak failed (host socket buffer suspected) ⏳ needs a sysctl on the host to conclude.
- **I. Non-DJI targets (approved 2026-09-19)** — ranked brief with legal flags; user approved passive MAVLink
  payload decode and video-content demod for research (Wi-Fi frame parsing → ESP32 system). SiK/MAVLink
  passive-decode chain now **complete end-to-end on synthetic data** (T1–T4; 197 tests): GFSK BER < 1e-3 at
  12 dB in-band SNR; Golay/CRC deframe; 250 kHz/N=50 raster; seed (NETID, unencrypted links only) recovery;
  MAVLink payload parsing OFF by default (`decode_third_party_mavlink`), `personal_7d` retention tagging.
  Independently reviewed (two reviewers): **PASS with conditions** — the review found the hop-map PRNG was
  *not* the firmware algorithm, fixed by transcribing `freq_hopping.c` from the local ArduPilot SiK source
  and verified 410/410 against an independently compiled C rig. Evidence level 1 (synthetic) — needs one
  real SiK recording (field, user) to reach level 3/4. Brief: `research/briefs/sik-freq-hopping-firmware.md`;
  design: `docs/design/sik-mavlink-passive-decode.md`. Analog-FPV detector: measured parameters from real
  1240 MHz Zenodo VTX captures (level 2, shape) — `docs/design/analog-fpv-detector.md`. New negative-control
  generators (`aerix_rf/dsp/ofdm_sim.py`): Wi-Fi-like OFDM bursts/scenes and BLE-like GFSK scenes (802.11a-style
  STF/LTF from memory, flagged unverified vs the standard) for Stage-1 and SiK false-positive testing. TDOA is
  in scope → the UHD image (timestamps, 2 RX) is the target platform, pending the buffered soak.
- **H. Stage-1 link-signature rules** — burst extraction + raster/period/cadence tests ✅ built; false-alarm audit on
  1,160 real ambient windows: `hopping` 1.0 % (budget 5 %) and DroneID-cadence 0 after one rule correction ✅;
  the FHSS-grid rules were never triggered by ambient RF (not exercised — needs real hopper positives, e.g. RFUAV RC set).
  **Update:** bench run against 31 RFUAV RC transmitters (`bench/stage1_rc_positives.py`) produced 136 level-1
  labels on 28/31 models vs 0/100 on ANTSDR ambient, and 0/428 on level-2 grid rules. Diagnosis found five
  structural defects (period test degenerate on dt=0 and on constant intervals; a 64-event cap that was
  actually a time cut; unbounded cluster chaining; single-look floor over-estimating bandwidth 15–50×; grid
  test resolution-starved at 100 MS/s). C1–C3 fixed and committed (`41a1787`) after independent review caught
  two further defects (merge cap splitting wideband bursts; `frame_dt_s` not forwarded on the session path);
  ambient false-alarm rate after the fix: `hopping` 11/1160 (0.95 %), level-2 = 0.
  **Update (2026-09-19 evening):** C5 (grid-resolution guard) committed (`7affe10`) — a `GRID_RESOLUTION_LIMITED`
  tag withholds level-2 grid labels when bin pitch > Δ/20 (G1) or burst width < 8 bins (G2); ambient
  false-alarm rate unchanged (`hopping` 11/1160 = 0.95 %, level-2 0). RC-positives bench v3 (dwell /
  full_band / full_band_4096 windows, 2 models): level-1 still fires on 30/31 transmitters; the first
  1 MHz-grid hits appear (5 windows, 2 models), all in the new 24.4 kHz-bin (`full_band_4096`) column,
  which is tagged `GRID_RESOLUTION_LIMITED` on 214/214 rows; ambient control 0/100. C4 (per-bin floor /
  P_fa thresholds / Welch looks) is **parked on `wip/stage1-c4`**, not on `main`: 710 tests pass and
  independent review was PASS-with-conditions, but the ambient hopping false-alarm rate rose from
  0.95 % to 17.2 % — a regression the FA bench catches — so it was held back; `rf-dsp-specialist` is
  diagnosing (skirt fragments / Wi-Fi discounts vs. corrected bandwidths). Lesson recorded: detector-threshold
  changes must pass the ambient FA bench before merge. Evidence: level 1–2 on a third-party X310 capture in a
  crowded band; same-receiver single-TX captures on the E200 are the conversion path to level 5. Docs:
  `docs/design/stage1-rc-positives-2026-09-19.md` (bench v3 is the final section).
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

**UHD-mode trial (2026-09-19, second SD card, reversible):** the E200 presents as a 2-channel receiver with
per-packet timestamps and reported overflows. 30–120 s runs: 15.36 MS/s sc16 (canonical rate, no resampling)
and 20 MS/s sc8 clean; 20 MS/s sc16 overflows with the default 212 KB host socket buffer; one 10-minute soak
lost the device mid-run (cause open). Decision rule unchanged: adopt only after a clean 10-minute soak with the
host buffer raised; otherwise revert to the proven IIO path.

**Decoder scope correction:** per primary sources, OcuSync 3/3+ DroneID is expected decodable (only O4 is
encrypted). The user's Avata (O3+) is therefore a live decode-test candidate — checklist in
`docs/field/avata-o3-decode-test.md`. Aircraft/link-generation table verified against dji.com.

**Non-DJI expansion, detail (2026-09-19):** the SiK/MAVLink passive-decode chain (§3.I) is complete
end-to-end on synthetic data and independently reviewed twice — PASS with conditions; the review's main
catch was a hop-map PRNG that did not match the firmware, fixed by transcribing `freq_hopping.c` and
verified 410/410 against an independently compiled C rig. Evidence level 1 (synthetic) throughout; a real
SiK recording is the conversion path to level 3/4. Stage-1's RC-positives bench (§3.H) found five structural
defects in the burst/period/cluster/bandwidth/grid tests; three are fixed and committed, cutting ambient
false alarms to `hopping` 11/1160 (0.95 %) and level-2 grid to 0. **Update (2026-09-19 evening):** C5 (grid-
resolution guard) is also committed — ambient FA unchanged, and the RC-positives bench v3 shows the first
1 MHz-grid hits (5 windows, 2 models), correctly withheld as `GRID_RESOLUTION_LIMITED` at the 24.4 kHz-bin
resolution. C4 (threshold/floor rework) is parked on `wip/stage1-c4`: it passed its own tests and
independent review but regressed the ambient FA bench (0.95 % → 17.2 %), so it stays off `main` pending
diagnosis. RFUAV `prepare` finished (349/349 recordings, 1.4 GB tensors) and `features_v2` was retrained
on it vs. ANTSDR ambient negatives; the receiver-ID confound probe is CONDITIONAL (balanced accuracy
0.647) and cross-receiver holdout recall is 0.875 (14/16, Zenodo) — level 2 at best, same blocking need
(same-receiver positives).

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
| Firmware | IIO image remains the proven production path (`antsdr_proc`, BIST gap-free); UHD image trialled from SD — decision after a buffered 10-min soak | measured (§14, §15 of the E200 brief) |
| Loss handling | producer in its own process + exact ring accounting; rate monitor with real deficits | measured |
| Decoder | validated on real IQ; blocker-robust via zc6-ranked centre selection | real IQ + synthetic bench |
| Benchmark honesty | no detection-probability or cross-receiver claim yet; receiver-ID probe is a mandatory control | first results §5 of the design doc |
| SiK hop-map | firmware algorithm transcribed from `freq_hopping.c`; naive shuffle, 8-bit draw mod n, 16-bit seed; NETID → seed only on unencrypted links | verified 410/410 vs independently compiled C rig |
| Stage-1 RC-positives | five structural defects found (period test, event cap, cluster chaining, bandwidth floor, grid resolution); C1–C3 fixed | `bench/stage1_rc_positives.py`, independent review |
| Stage-1 C5 grid guard | `GRID_RESOLUTION_LIMITED` tag withholds level-2 grid labels when bin pitch > Δ/20 or bursts < 8 bins; ambient FA unchanged; first 1 MHz-grid hits (bench v3) correctly flagged | commit `7affe10`; ambient 11/1160 (0.95 %), level-2 0; bench v3 214/214 flagged |
| Stage-1 C4 threshold rework | PARKED on `wip/stage1-c4` — passes own tests + review, but ambient hopping FA rose 0.95 % → 17.2 %; not merged | 710 tests, independent review PASS-with-conditions; ambient FA bench regression |
| Classifier features_v2 (RFUAV) | retrained on 349 RFUAV positives vs. 449 ANTSDR ambient negatives; receiver-ID confound CONDITIONAL | balanced acc. 0.647 (receiver-ID probe); cross-receiver holdout recall 0.875 (14/16, Zenodo) |

## 6. Open items, risks, needs

*2026-09-19 evening: no new open decisions for the user. The E200 field items below (sysctl soak, Avata
O3+ decode test, positives campaign, SiK radio recording) remain the highest-value inputs.*

**Needs from the team**
- First campaign measurement: the **Avata (O3) plaintext-decode test** (available). For a guaranteed O2
  reference: Mini 4K / Mini 2 SE / Mini 2 / Mini 3 non-Pro / Mavic Air 2. O4 aircraft for detection-only positives
  and the O4 CRC-identification experiment.
- **Blocking on the host owner:** one sudo command for the UHD trial: `sudo sysctl -w net.core.rmem_max=50000000 net.core.wmem_max=50000000`.
- Answers: is multi-receiver/TDOA in scope (now feasible in UHD mode — the main reason to prefer it)? Field-box
  hardware and disk budget (raw cs16 is ≈177 GB/h, so capture must be event-gated)?
- Positives campaign: the Avata test first (`docs/field/avata-o3-decode-test.md`), then the ON/OFF protocol
  (`docs/field/positives-protocol.md`); an O2 reference aircraft (Mini 4K / Mini 2 SE / Mini 2 / Mini 3 / Mavic Air 2) if available.
- Housekeeping: IEEE DataPort / Kaggle credentials for gated datasets; approval for the very large sets
  (DroneRFa ≈570 GB, RFUAV up to 1.3 TB); `dialout` group membership.
- A real SiK radio recording (field, user) — the only path from the SiK/MAVLink chain's current level-1
  (synthetic) evidence to level 3/4.

**Main risks**
- Without same-receiver positives, no classifier claim is defensible (mitigation: campaign F).
- The IIO firmware has no timestamps: fine for detection, a dead end for TDOA (mitigation: SD-card trial G).
- Live classifier features cost ≈1.2 s per second of signal on this workstation; the field box may need the
  cheaper v1 features (decision pending hardware choice).

**Working practice**
- Subagent turn limits are being hit repeatedly, producing deliverables written early; independent review is
  now catching real defects in every recent batch (Stage-1 C4/C5, the SiK hop-map). Treat this as a working
  practice to keep — every builder deliverable gets an independent review pass before it is trusted — not as
  a one-off complaint.

## 7. Where to look

`README.md` (status log) · `AERIX_RF_ANTSDR_PROJECT.md` (plan, §0 decisions/questions) ·
`docs/design/*.md` (architecture memos) · `research/briefs/*.md` (evidence briefs) ·
`docs/BACKLOG.md` (engineering backlog) · `docs/field/positives-protocol.md` (campaign checklist).
Tests: 705 collected (incl. 197 SiK, 52 Stage-1, 8 OFDM/BLE negative-control) on `main`; a further 710
on the parked `wip/stage1-c4` branch (not merged). Commits on `main`: 46+ since the pivot.
