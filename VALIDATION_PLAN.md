# ANTSDR validation plan: re-audit first, real datasets second

**Status:** Working plan for the current `antsdr` branch  
**Branch at plan start:** `claude/antsdr-drone-rf-detection-ac0uxs`  
**Baseline reviewed before writing this plan:** `a7d8cf62ea8b3123a320b71c88b1917d93819eb7`  
**Purpose:** make the existing work trustworthy before spending time flying our own drones, then validate it against independent public RF/IQ recordings.

This plan is deliberately **not** a specification handed down as truth. The peer-review findings that triggered it are hypotheses to test. Claude must independently re-check the code, the upstream references, the mathematics and the tests. If a finding is wrong, incomplete or based on a different interpretation, do **not** change the implementation just to satisfy this document. Record the disagreement, show the evidence on both sides and raise a question in `QUESTIONS.md` for the maintainer when the choice materially changes behaviour, compatibility or claims.

The research phase already used a good pattern: multiple independent lenses, adversarial verification, a critic pass, explicit confidence levels and ADRs for decisions. This validation phase should use the same discipline for the implementation itself.

---

## 1. Order of work

Do the work in this order:

1. **Freeze and reproduce the current state.**
2. **Independently re-audit the existing code and claims.**
3. **Adversarially verify the peer-review findings below.**
4. **Resolve confirmed defects and documentation contradictions.**
5. **Run all synthetic/unit/regression tests again.**
6. **Pass Gate A: implementation internally trustworthy.**
7. **Re-check which public real RF/IQ datasets are actually usable today.**
8. **Build reproducible dataset adapters and immutable manifests.**
9. **Validate DroneID against independent real captures first.**
10. **Benchmark detector/classifier behaviour against broader real datasets.**
11. **Pass Gate B: external data validation credible.**
12. **Only then move to our own E200/HackRF captures and flying tests.**

Do not start ML training or tune thresholds to make a public benchmark look good before Gate B. Public datasets are validation data first.

---

# PHASE 0 — Freeze and reproduce the current state

## Goal

Know exactly what is being audited and make failures reproducible.

## Tasks

- Record current branch head SHA in the validation report.
- Record Python version, OS and dependency versions.
- Run the complete toolkit test suite before changing anything.
- Run lint/static checks already configured by the package.
- Run a package/import smoke test from a clean environment.
- Record failures exactly; do not repair them during this step.
- Check whether GitHub Actions exists for this branch. If there is still no CI, record that as a validation gap.
- Save a compact baseline report under a new validation directory, for example:

```text
antsdr/research/validation/
  README.md
  baseline.md
  review-findings.md
  disputes.md
  datasets/
  reports/
```

Do not put large IQ recordings in Git.

## Exit condition

A second developer can identify the exact commit and reproduce the same initial test state.

---

# PHASE 1 — Re-audit the work already done

## Goal

Review the implementation as if the earlier peer review did not exist. The purpose is to find errors in both directions: errors in the code **and errors in the review**.

Use the same four-pass engineering review style throughout:

### 1. Discovery

Map the complete current `antsdr/toolkit` path:

- hardware abstraction / `SampleSource`
- E200 source
- file/synthetic sources
- SigMF I/O
- spectrum/burst DSP
- sweep planner and scanner
- classifier/signatures
- DJI DroneID PHY/FEC/parser/synth
- analog FPV detector and video decoder
- Remote ID parser/capture path
- fleet/model capability logic
- AERIX event/output mapping
- CLIs and package entry points
- tests

Also review the **nine commits added after the previous peer review**, especially the new Remote ID, fleet and analog-video code. The fact that they were added after the earlier review means they have not had the same independent pass yet.

### 2. Dependency / syntax / interface pass

For every public function and CLI path:

- verify imports actually resolve;
- verify exported names match what callers look up;
- verify units and types at module boundaries;
- verify default values agree with the hardware mode they invoke;
- verify file metadata represents the physical capture correctly;
- verify tests do not rely on implementation-specific internals in a way that hides bugs.

### 3. Security / licence / data-integrity pass

- confirm third-party code boundaries still follow ADR-0003;
- confirm no incompatible code has been copied while implementing algorithms;
- confirm public datasets are not silently redistributed when their licence does not allow it;
- confirm raw-IQ evidence is not confused with decoded/derived drone identity;
- confirm output never claims more certainty than the decoder/detector has earned.

### 4. Execution simulation

Walk every major path end to end on paper and in tests:

```text
RF samples
 -> capture/file source
 -> timing semantics
 -> detector
 -> features
 -> classifier/decoder
 -> evidence/result
 -> CLI/event output
```

For each path ask: **what real physical event does each sample index, timestamp, frequency, unit and confidence value represent?**

---

# PHASE 2 — Independently verify the peer-review findings

## Rule

The items below are **review hypotheses**, not required conclusions.

For every item create a record with:

```text
Finding ID
Reviewer claim
Current implementation
Independent sources checked
Reproduction / test
Claude verdict: CONFIRMED | PARTLY | REJECTED | UNRESOLVED
Reasoning
Required change, if any
Question raised, if any
```

A `PARTLY` verdict is expected and useful. The original research phase showed that design-critical statements often become more accurate after being challenged.

## H1 — DJI DroneID frame layout and field semantics

Re-derive the 91-byte DJI frame layout independently from at least two credible implementations or primary/reference material where available.

Specifically verify:

- struct layout and total byte count;
- `altitude` versus `height` field order;
- raw units and feet/metres conversion;
- UUID length;
- serial length;
- CRC coverage;
- field signedness and scale;
- legacy 8-symbol variants if supported.

Do not assume the previous claim that the correct struct is `<BBBHH16siihhhhhhQiiiiBB20sH>` merely because it came from a reviewer. Re-open the reference implementation and prove the offsets byte by byte.

### Required anti-self-consistency test

The synthetic generator is **not** independent evidence for the parser. If synth and parser share the same wrong layout, their round trip still passes. Add a fixture whose expected bytes/fields come from an independent implementation or published real capture.

---

## H2 — Coordinate validation

Check whether latitude and longitude are validated against their own physical ranges:

- latitude: `[-90, +90]`
- longitude: `[-180, +180]`

Verify zero/unknown semantics from an independent source. Add explicit boundary tests.

---

## H3 — Snapshot capture and SigMF time semantics

Determine exactly what `snapshot` means in the current capture CLI and E200/IIO path.

Answer independently:

- Are buffers physically contiguous in RF time?
- If not, does the current `.sigmf-data` representation concatenate them as though they were contiguous?
- Does SigMF permit us to represent discontinuities using multiple captures/metadata in the way we need?
- Which downstream metrics become invalid if a gap is hidden?

At minimum consider:

- burst repetition interval;
- hop period/rate;
- duty cycle;
- absolute event timing;
- ML windows spanning a hidden gap.

Do not implement a proposed fix until the actual IIO/snapshot behaviour and SigMF representation have been checked.

---

## H4 — Retune settling and double discard

Measure or calculate the current observation duty cycle from the actual code path:

```text
retune
 -> E200 driver flush
 -> sweep settle sleep
 -> sweep-level discard reads
 -> recorded dwell
```

Check the defaults at the current buffer size/sample rate. Determine whether both discard layers are intentional and whether a dwell-sized discard is appropriate.

If the earlier ~21% observation-duty estimate is wrong, replace it with the correct measured/derived value. The goal is not to preserve the estimate; the goal is to know the real blind time.

Add timing/behaviour tests that make accidental double flushing visible.

---

## H5 — Live sweep default sample rate versus firmware personality

Verify the current `antsdr-tk sweep --uri ...` path from CLI to driver.

Check whether the default sample rate is appropriate for the firmware the driver actually opens. Distinguish clearly between:

- stock Pluto/IIO continuous streaming;
- stock-firmware snapshot capture;
- UHD personality continuous streaming;
- theoretical 1 GbE wire limit.

A warning may or may not be sufficient; decide based on whether users can unknowingly generate incomplete/dropped live data while the CLI appears healthy.

---

## H6 — Classifier integration from the sweep CLI

Trace the actual runtime symbol lookup.

Verify whether `cli_sweep` searches for a function that `antsdr_toolkit.classify` actually exports. If the hook works through another mechanism, document it and reject the finding. If not, add an integration test that runs the CLI without monkey-patching globals.

Also decide whether classification belongs at **dwell level** or **emitter/cluster level**. A dwell can contain more than one signal; do not force the current interface merely to keep compatibility with a placeholder.

---

## H7 — DroneID FEC/turbo capability claims

Independently inspect the open DroneID reference implementations again.

Verify:

- whether the NDSS/DroneSecurity path performs LTE turbo decoding;
- what the current toolkit actually extracts from rate-matched bits;
- whether the claimed sensitivity penalty has published or measured support;
- whether hard QPSK slicing currently throws away soft information a future turbo decoder needs.

Do not repeat the `~3 dB` figure unless evidence supports it. If it is only an engineering expectation, label it as such or remove it.

Capability wording must distinguish among:

- burst detected;
- payload bits extracted without FEC correction;
- CRC-valid frame decoded;
- full reference-grade turbo decode.

---

## H8 — Synthetic tests versus real compatibility

Inventory every test whose source signal is generated by toolkit code.

For each one state what it proves and what it **cannot** prove.

Examples:

- synth -> parser round trip proves internal consistency;
- synth -> ZC detector proves expected-signal detection under our own signal model;
- it does not prove compatibility with a real Mini 2 RF capture.

The goal is not to remove synthetic tests. They are valuable. The goal is to stop treating them as independent protocol validation.

---

## H9 — AERIX observation/event contract

Compare the current SDR event model with the current AERIX contracts on the same branch/default target.

Decide whether:

- generic RF detections;
- a DroneID burst with failed decode;
- a CRC-valid proprietary DJI DroneID frame;
- standard Open/Remote ID

are the same semantic event type or separate layers.

Do not create a new `RfDetectionEnvelope` merely because the reviewer suggested that name. First derive the requirements from existing AERIX consumers and schemas. If the cleanest design is a sibling envelope, write an ADR before integration.

---

## H10 — CRC failure and OcuSync 4 inference

Check every user-facing message that maps `CRC failure` to `O4/encrypted`.

A failed CRC can have multiple causes unless a reliable discriminator has been independently established. If no discriminator exists, output an evidence-based state such as `decode_failed` / `unknown` rather than a protocol-generation claim.

If Claude finds a reliable O4 discriminator, document and test it and reject this finding.

---

## H11 — CI and reproducibility

Check again whether CI now exists. At the start of this plan there was no `.github/workflows` directory visible on the branch.

Minimum automated checks should include, where supported:

- supported Python versions;
- `pytest`;
- lint/static checks already chosen by the project;
- package build/import smoke test;
- no-hardware CLI help/smoke tests.

Hardware tests remain separate.

---

## H12 — Documentation contradictions

Run a cross-document consistency pass across:

- `antsdr/README.md`
- `research/README.md`
- `QUESTIONS.md`
- ADRs
- module/CLI docstrings

Known example to re-check: the top-level README currently describes openwifi on the E200 as an identity path for DJI Remote ID, while newer research text and Q20 state that the E200/openwifi path cannot receive the relevant 2.4 GHz 802.11b RID beacons. Determine which statement is correct and align all documents.

Also re-check the analog FPV sample-rate wording: the recent decoder work found that captures below about 13 MSPS can appear to lock while producing a wrong image, so older `10 MSPS` claims must not survive elsewhere unnoticed.

---

## H13 — New work added after the previous review

The commits after the previous review added substantial code. Give these the same independent treatment rather than assuming "newer = better":

- `remoteid/odid.py`
- `remoteid/wifi.py`
- `cli_remoteid.py`
- `fleet.py`
- `cli_fleet.py`
- `analog/video_decode.py`
- updated `analog/video_synth.py`

At minimum verify:

- parser bounds/length checks;
- malformed-input behaviour;
- units and coordinate conventions;
- model/fleet capability claims against sources;
- whether test fixtures are independent or generated by the same assumptions;
- documentation versus implementation;
- false-success behaviour such as the analog decoder correctly discovered and fixed at low sample rates.

---

# Disagreement protocol — mandatory

The reviewer is not the authority and Claude is not the authority. Evidence wins; unresolved design choices go to the maintainer.

If Claude disagrees with any H1-H13 item and the disagreement changes code, protocol interpretation, hardware requirements, output semantics or product capability claims:

1. **Do not silently ignore the finding.**
2. Put the evidence for both interpretations in `research/validation/disputes.md`.
3. State Claude's preferred interpretation and confidence.
4. Add a new numbered question to `QUESTIONS.md` using the existing permanent-numbering style.
5. Give the maintainer a concrete choice, consequence and recommendation.
6. Do not block unrelated work while waiting; block only the affected path.

Use this question structure:

```markdown
**Qxx. Short decision title.**

Peer-review claim:
...

Independent re-check:
...

Evidence for interpretation A:
- ...

Evidence for interpretation B:
- ...

Consequence:
- A means ...
- B means ...

**Question:** which interpretation/behaviour should become the project decision?
**(rec.)** ...
```

If the evidence clearly disproves a peer-review finding, record `REJECTED`, add a regression test if useful, and move on. No maintainer question is needed unless there is still a product/design choice.

---

# GATE A — Internal implementation trustworthy

Do **not** start the public real-IQ dataset implementation until all of the following are true:

- every H1-H13 item has a verdict;
- all confirmed P0/P1 correctness defects are fixed or explicitly blocked by a maintainer/hardware question;
- disputed items are visible in `QUESTIONS.md`, not buried in comments;
- docs no longer contradict each other on material capabilities;
- unit/synthetic tests are green;
- independent fixtures exist for protocol fields where possible;
- live/snapshot timing semantics are explicit;
- output confidence/labels do not overclaim;
- CI/reproducibility status is documented.

This gate is about **knowing what the code means**, not about achieving good RF accuracy yet.

---

# PHASE 3 — Re-check the public dataset landscape

Only after Gate A, perform a fresh dataset pass. Do not copy the old `datasets.md` shortlist blindly; re-open the original sources and verify that download links, licences, file formats and reference outputs are still what the research record says.

The existing catalogue remains a starting index, not authority.

## Candidate groups to re-check

| Candidate | Primary purpose | Initial priority |
|---|---|---:|
| RUB-SysSec DroneSecurity real samples | independent DJI DroneID decoder golden vectors | P0 |
| proto17 / compatible published DroneID samples | second decoder/reference path | P0/P1 |
| Noisy Drone RF | detector/classifier robustness versus SNR and realistic interference | P1 |
| DroneDetect | independent 2.4 GHz multi-drone/interference corpus | P1 |
| RFUAV | broad model/domain-shift test | P1/P2 |
| CageDroneRF | modern broad-band real-world benchmark if access/licence permits | P1/P2 |
| DroneRFa / DroneRFb-DIR | model/unit/domain-shift evaluation | P2 |
| UAVSig / S3R | open-set / cross-domain work | P2 |
| DroneRF | legacy binary-regression sanity check only | P3 |

The final order may change after the re-check.

## Dataset acceptance checklist

A dataset is not "usable" until the following are known:

- original publisher/source;
- licence and redistribution restrictions;
- download method;
- SHA-256 of each immutable source archive/file we use;
- original sample rate;
- centre frequency/band;
- datatype/endian/interleaving;
- IQ versus real amplitude versus derived spectrogram/tensor;
- capture hardware;
- class labels and how ground truth was created;
- whether recordings are independent sessions or windows from a small number of captures;
- known leakage/benchmark flaws;
- whether expected decoder outputs exist;
- exact preprocessing required for our toolkit.

Do not convert a derived spectrogram dataset back into pretend IQ.

---

# PHASE 4 — Build a reproducible external-dataset harness

## Directory shape

A suggested shape, not mandatory if a cleaner project-native structure emerges:

```text
antsdr/
  external_tests/
    manifest.yaml
    README.md
    adapters/
      dronesecurity.py
      noisy_drone_rf.py
      dronedetect.py
      rfuav.py
    expected/
      ... small text/json golden outputs only ...
    reports/
```

Large source datasets remain outside Git.

## Manifest requirements

For every corpus/file used:

```text
name
version/date
source URL/DOI/repository
licence
local expected filename
SHA-256
original sample rate
centre frequency
sample format
capture hardware
allowed uses
preprocessing steps
reference implementation + pinned commit
```

Every conversion must be deterministic and scripted.

### Immutable-source rule

Never modify the downloaded original in place. Processing creates a derived file with its own manifest entry and hash.

### Resampling rule

When a real capture has to be converted to a toolkit-supported rate:

- record original and target rates;
- use a deterministic rational/polyphase conversion where possible;
- record filter parameters;
- preserve an unmodified original;
- test that the reference decoder result is not destroyed merely by the conversion.

---

# PHASE 5 — Real DJI DroneID golden validation first

This is the most important external test because it directly attacks the current self-consistency risk.

## Method

For each independently captured DJI file with a credible reference decode:

1. Run the upstream/reference decoder at a pinned commit.
2. Save a small expected JSON/text fixture containing only the fields needed for verification and allowed by the source/licence.
3. Run our detector/decoder against the same source recording or a documented deterministic resample.
4. Compare:
   - burst count/candidate offsets;
   - CFO where reference/ground truth permits;
   - CRC-valid frame count;
   - raw decoded 91-byte frame where available;
   - product/model;
   - serial;
   - drone lat/lon;
   - pilot lat/lon;
   - home lat/lon;
   - altitude/height;
   - velocity/yaw/time fields;
   - UUID length/content where present.
5. Record every mismatch. Do not massage expected values to match our parser.

## Required regression principle

At least one DroneID regression must depend on bytes/results that were **not produced by `antsdr_toolkit.droneid.synth`**.

## Pass criteria

Define pass criteria before tuning. Example structure:

```text
Protocol layout: exact byte/field agreement on CRC-valid reference frames
Coordinate/unit conversion: exact or documented tolerance
Burst detection: recall reported separately from payload decode success
Decode failures: reported as failures/unknown, not relabelled as O4 without evidence
```

Do not set a desired sensitivity number before seeing what the independent reference capture supports.

---

# PHASE 6 — Broader real-RF detector/classifier validation

Once real DroneID compatibility is established, test the generic RF front end.

## Metrics

Report at least:

- burst/event recall when ground truth permits;
- false alarms per unit recording time;
- precision/recall or ROC/PR where labels permit;
- occupied-bandwidth error;
- centre-frequency error;
- duration error;
- family top-1 and top-3 similarity/classification;
- unknown/open-set rejection rate;
- confusion against Wi-Fi/Bluetooth/background;
- performance versus SNR where the dataset defines SNR clearly.

Keep **detection**, **family classification** and **identity/decode** as separate scores.

## Leakage rules

Never split neighbouring windows from the same original recording across train/test and call them independent.

For any model fitting or threshold optimisation later:

- group by source recording;
- preferably hold out session/day/location;
- hold out physical airframe units where the corpus supports it;
- report per-SNR results rather than one aggregate score;
- include unknown signal families.

Initially, however, run the current heuristics **without training on the benchmark**. We want to see how they generalise before adapting them.

---

# PHASE 7 — External-validation report and decisions

Produce one report that separates facts from interpretation.

Recommended sections:

1. tested commit and environment;
2. datasets and exact source hashes;
3. preprocessing;
4. reference implementations and pinned commits;
5. DroneID golden-vector results;
6. generic detector results;
7. classifier results;
8. false positives/background results;
9. failures and unexplained observations;
10. changes made because of the datasets;
11. remaining questions;
12. what has **not** been validated.

Every significant improvement made after seeing a dataset should be labelled as such. If thresholds are tuned on dataset A, dataset A is no longer an untouched final test set.

---

# GATE B — Ready for own hardware/flight testing

We can move to real E200/HackRF/own-drone testing when:

- at least one independent real DJI capture passes the protocol/parser regression path;
- generic RF detection has been exercised on more than one independent real dataset;
- known interference/background data has been tested;
- false-positive behaviour is quantified, not anecdotal;
- sample-rate/resampling assumptions are documented;
- public-dataset licences are respected;
- no unresolved software correctness issue makes live results uninterpretable;
- limitations are written as limitations, not converted into confident labels.

Passing Gate B does **not** prove the E200 hardware path. It means the software is worth taking to hardware.

---

# PHASE 8 — Own hardware and drone tests later

This is intentionally deferred until the two gates above.

The future physical phase should then isolate what public recordings cannot answer:

- real E200/AD936x gain/noise/spurs;
- retune settling time;
- continuous-versus-snapshot behaviour;
- actual dropped samples/host throughput;
- 2.4/5.1/5.8 GHz sensitivity;
- antenna effects;
- detection range;
- scan duty cycle;
- model differences across the available DJI fleet;
- HackRF versus E200 behaviour where both are available.

Because software/protocol correctness will already have independent evidence, failures in this phase can be investigated as **hardware/channel/field** problems instead of being mixed with parser and DSP uncertainty.

---

# What not to do yet

Until Gate A and the first external golden vectors are complete:

- do not add more signal families simply to increase feature count;
- do not start a large ML model;
- do not optimise headline classification accuracy on synthetic data;
- do not rewrite the `SampleSource` architecture without evidence it is blocking validation;
- do not force SDR data into the existing AERIX ODID contract just to demonstrate integration;
- do not interpret a failed decode as an aircraft generation without an independent discriminator;
- do not treat a green synth round trip as proof of compatibility with a real transmitter.

---

# Definition of success for this plan

This phase succeeds when we can answer all of these questions with evidence:

1. **Does the current code represent samples and time truthfully?**
2. **Does the DJI parser agree with independent real/reference frames?**
3. **Can the detector find RF it did not generate itself?**
4. **Can it distinguish drone-like RF from ordinary background/interference without absurd false alarms?**
5. **Do the CLI and event outputs say only what the evidence supports?**
6. **Are disagreements between the reviewer and Claude visible and decidable by the maintainer?**
7. **Can another developer reproduce the same results from source hashes and pinned commits?**

Only after those answers are clear do we spend scarce time on our own flying tests.
