# AERIX RF — ANTSDR-primary implementation and test plan

> **Working document for Claude Code**  
> Branch: `main`  
> **Primary receiver: ANTSDR E200 (AD9361, Zynq-7020, GbE)** — since 2026-09-18  
> Secondary / reference receiver: **HackRF / HackRF Pro** (first field-tested platform; stays supported)  
> Future optional hardware: **bladeRF 2.0** and other SoapySDR-capable receivers  
> Scope status: 2026-09-18 (roadmap revision 2; sections 4–7 describe the completed HackRF Phase 1 and are retained as history and as the HackRF regression baseline)

---


# 0. Project order — revision 2 (2026-09-18)

**What changed.** The ANTSDR E200 is now the primary receiver platform. HackRF remains a
supported secondary/reference backend and the regression baseline (its 2026-09-04 Mini 3
CRC-valid DroneID session is the golden HackRF capture). The original "do not start ANTSDR
until Phase 1 exit" rule is retired: Phase 1 delivered its core evidence (real-capture
CRC-valid decode, deterministic replay, differential scan) and the receiver abstraction is
stable enough to carry a second backend.

```text
PHASE 1  (done, HackRF)          RF engine, sessions/replay, Stage-1/2/3 separation,
                                 first CRC-valid DJI DroneID decode from real IQ (2026-09-04)

PHASE A  (active, ANTSDR)        A1 hardware discovery ......... done (research/briefs/antsdr-e200.md)
                                 A2 IQSource backend ........... docs/design/antsdr-backend.md, tasks T1–T6
                                 A3 canonical representation ... docs/design/canonical-representation.md
                                 A4 acceptance: ANTSDR -> capture -> session -> replay
                                                -> existing DroneID decoder -> CRC-valid frame

PHASE B/C (active, data)         all accessible RF/UAV datasets to $AERIX_RF_DATASET_ROOT
                                 (default ~/rf-datasets), master manifest, dataset brief
                                 research/briefs/rf-datasets.md

PHASE D  (after A3)              dataset normalisation to the canonical representation,
                                 leakage-safe splits, benchmark "does it generalise to our ANTSDR?"

PHASE E  (done, corpus)          local research corpus indexed: research/index.md + briefs

PHASE 2  (unchanged scope)       AERIX server integration: RF events, evidence, correlation,
                                 retention, fleet status — proceeds when the ANTSDR path is proven

LATER                            2R2T / timestamps / UHD-style firmware, protocol-event firmware,
                                 multi-receiver TDOA; bladeRF / USRP through the same abstraction
```

**Hard constraints carried forward**
- Passive/receive-only. No transmit, spoofing, jamming, takeover, interference, deauthentication,
  active interrogation.
- Application/DSP/classification/decode stay hardware-neutral; device behaviour lives behind
  `IQSource` + `ReceiverCapabilities`. HackRF must keep working after every ANTSDR change.
- Evidence levels stay separate: RF candidate → probabilistic class → protocol evidence →
  CRC-valid decode → operator ground truth.
- Firmware changes and persistent device settings on the E200 (image swap, U-Boot env, 2R2T
  unlock) are user-approval gates, never a builder decision.
- Do not commit datasets, IQ, PDFs, secrets. Manifests/loaders/scripts/small fixtures only.

**Measured E200 facts that shape the design** (details and evidence grades in
`research/briefs/antsdr-e200.md`): stock PlutoSDR-compatible IIO image, one RX exposed,
12-bit-in-int16 samples (`iq_full_scale` 2048), **sustained RX ceiling ≈ 59 MB/s ≈ 14.8 MS/s
on the iiod/Ethernet path** (5–10 MS/s clean, 15.36 marginal with silent loss, ≥20 unusable),
no overflow counter, no device timestamps. Hence: canonical representation 15.36 MS/s;
ANTSDR-IIO live profile 11.52 MS/s until the streaming path changes; legacy HackRF 20 MS/s
sessions are never rewritten.

---

# 1. Current repository state

Do not restart the implementation. Build on the current branch.

## Already implemented

### HackRF acquisition

Current sources include:

- `HackrfTransferSource`
- SoapySDR `HackRFSource`
- file replay
- simulator

Relevant file:

```text
aerix_rf/sdr/capture.py
```

The current code has already been exercised against real ambient RF with a HackRF.

### DSP / detection

Current chain:

```text
IQ
 -> spectrogram
 -> energy/spectral detector
 -> signature classifier
 -> optional DJI decoder
```

Relevant files:

```text
aerix_rf/dsp/spectrogram.py
aerix_rf/detect/energy.py
aerix_rf/classify/model.py
```

### DJI DroneID decoder

The branch now includes:

- Zadoff-Chu synchronization
- resampling to 15.36 MS/s
- STO / CFO handling
- OFDM demodulation
- channel equalization
- QPSK decisions
- LTE descrambling
- LTE de-rate-matching
- max-log-MAP Turbo decode
- CRC24A validation
- DJI frame parsing

Relevant files:

```text
aerix_rf/decode/droneid.py
aerix_rf/decode/turbo.py
aerix_rf/decode/frame.py
aerix_rf/decode/ofdm.py
aerix_rf/decode/zc.py
```

The decoder is currently **synthetic-validated**. It is not yet proven against a known real DroneID IQ recording from the HackRF.

### Classifier training

Current training supports synthetic data and public datasets including DroneRF.

DroneRF mapping has already been corrected so DJI and Parrot are not collapsed into one class, and validation can hold out complete source recordings to reduce leakage.

Do not undo this.

### Server path

A separate RF server path already exists:

```text
/v1/rf-detections:batch
rf_detections
```

The architectural decision to keep RF detections separate from ODID observations is correct.

However, **server work is Phase 2**. Do not let server integration block Phase 1 field testing.

---

# 2. Known critical issues to fix before field testing

## 2.1 Live ML inference is not currently wired in

`main.py` currently calls the rule-only path:

```python
cls = classify(det)
```

The function that actually loads and runs `AERIX_RF_MODEL` is:

```python
classify_spectrogram(spec, center_freq_mhz)
```

Fix this in Phase 1.

Required behavior:

```text
no model
 -> rule fallback

valid model
 -> ML classifier

broken/incompatible model
 -> warning
 -> rule fallback
 -> service continues
```

Live output must show:

```text
classification label
classification confidence
classification source/model version
```

Do not use classifier output as a prerequisite for protocol decoding. A valid protocol decode is stronger evidence than an ML label.

---

## 2.2 Stage 1 over-claims identity

The current energy detector assigns labels such as `dji_ocusync` based primarily on bandwidth/cadence.

That is too strong for 2.4 GHz environments because normal Wi-Fi can resemble wideband OFDM.

For Phase 1, separate the concepts:

```text
Stage 1 = RF morphology / candidate detection
Stage 2 = probabilistic UAS classification
Stage 3 = protocol decode / deterministic confirmation
```

Recommended Stage-1 vocabulary:

```text
noise
narrowband_candidate
wideband_candidate
burst_wideband_candidate
ofdm_candidate
fhss_candidate
continuous_wideband_candidate
analog_candidate
unknown
```

Recommended Stage-2 vocabulary can remain higher-level:

```text
dji_ocusync
wifi_uas
analog_fpv
other_uas
non_uas
unknown
```

A Stage-1 event must never be presented as a confirmed drone merely because it is 10–20 MHz wide.

---

## 2.3 HackRF cannot watch the entire 2.4 + 5.8 GHz space at once

Do not hide this limitation.

The Phase-1 implementation must explicitly use a **scan -> candidate -> lock -> inspect -> rescan** strategy.

High-level behavior:

```text
SCAN
  2.4 GHz configured range
  5 GHz / 5.8 GHz configured range
        ↓
find persistent/new candidate
        ↓
LOCK receiver around candidate
        ↓
continuous IQ capture
        ↓
detect + classify + decode
        ↓
periodically rescan / follow hop
```

The exact frequency presets must be configurable. Do not bake one regulatory-region assumption into the detector.

Provide sensible presets for the test tool, but keep raw start/stop frequencies user-configurable.

---

## 2.4 `hackrf_transfer` window-by-window capture has gaps

The current `HackrfTransferSource` starts a new CLI process for each capture window.

That is acceptable as a fallback and for simple recordings, but it is not the preferred live Phase-1 detector path because short RF bursts can occur during restart gaps.

For test-ready operation:

1. Prefer a continuous SoapySDR/libhackrf stream for locked-channel monitoring.
2. Keep `hackrf_transfer` as a robust capture/export fallback.
3. Detect/log stream errors, short reads and overflows.
4. Never silently treat a partial buffer as a normal full-quality frame.

Add capture-quality metadata to each processed window.

Suggested fields:

```text
expected_samples
received_samples
dropped_or_missing_samples
overflow_count
capture_complete
source_backend
```

---

# 3. Hardware abstraction — build this now, but only implement HackRF now

We want bladeRF and ANTSDR later without rewriting the DSP engine.

That does **not** mean implementing those receivers now.

Create/clean up a minimal hardware-neutral IQ source contract.

Example:

```python
class IQSource:
    @property
    def capabilities(self) -> ReceiverCapabilities: ...

    def tune(self, center_freq_hz: float) -> None: ...
    def windows(self) -> Iterator[IQWindow]: ...
    def close(self) -> None: ...
```

A window should carry the IQ and its metadata rather than returning a naked NumPy array forever.

Suggested model:

```python
@dataclass
class IQWindow:
    iq: np.ndarray
    captured_at: float
    sample_rate: float
    center_freq_hz: float
    receiver_type: str
    receiver_serial: str | None
    gain_db: float | None
    complete: bool
    dropped_samples: int | None
    metadata: dict
```

Suggested capabilities:

```python
@dataclass
class ReceiverCapabilities:
    receiver_type: str
    min_freq_hz: float
    max_freq_hz: float
    max_sample_rate: float
    max_instantaneous_bw_hz: float
    channels_rx: int
    supports_hardware_timestamps: bool
    supports_external_clock: bool
    supports_external_pps: bool
```

### Phase-1 implementations

Implement/use only:

```text
HackRFSource
HackrfTransferSource
FileIQSource
SimSource
```

Do not implement bladeRF or ANTSDR source classes now.

### Future rule

Any later SDR must feed the same downstream DSP contracts.

No DSP/classifier/decoder module should contain checks such as:

```python
if receiver == "hackrf":
...
elif receiver == "bladerf":
...
```

Receiver-specific behavior belongs in receiver adapters.

---

# 4. PHASE 1 — HackRF local RF test system

## Phase-1 goal

At the end of Phase 1 we must be able to take the HackRF and the test computer/box into the field and perform a repeatable test with two available DJI drones.

One known test aircraft is a DJI Mini. The exact model/version of the second DJI aircraft may be entered in the test metadata before testing.

Phase 1 does **not** require server connectivity.

Phase 1 should answer these questions with real evidence:

1. Can the HackRF find repeatable RF activity associated with Drone A?
2. Can it find repeatable RF activity associated with Drone B?
3. Which frequencies/bands are being used?
4. What RF morphology/cadence do we observe?
5. Does the classifier distinguish the signal from local Wi-Fi/background?
6. Can the DJI decoder obtain a CRC-valid real DroneID frame for a supported aircraft?
7. Can every test be replayed offline and produce materially identical results?

---

## Milestone 1.1 — stabilize the live HackRF pipeline

### Work

- Refactor `IQSource` / `IQWindow` as described above.
- Make continuous HackRF streaming the preferred live backend.
- Keep file/sim behavior working.
- Keep `hackrf_transfer` capture support.
- Add stream-quality counters.
- Add receiver metadata.
- Add clean shutdown/restart behavior.

### Acceptance

- Continuous capture can run for at least 10 minutes without process failure.
- Any overflow/short-read condition is counted and visible.
- `--sim` still works.
- file replay still works.
- existing tests remain green.

---

## Milestone 1.2 — wire the real classifier into live operation

### Work

- Use `classify_spectrogram()` from the live pipeline when a model is available.
- Keep the rule path as fallback.
- Expose classifier source/version/confidence.
- Do not gate decoder execution on classifier approval.
- Add an explicit `unknown`/abstain path where practical.

### Sample-rate handling

The current real DroneRF demonstration is at ~40 MS/s while the HackRF deployment path is normally 20 MS/s.

Do not pretend that the 40 MS/s bundle is a calibrated 20 MS/s deployment model.

For Phase 1 either:

1. create a documented preprocessing/resampling path and train a proper 20 MS/s model, or
2. run the ML output as experimental/advisory while collecting real HackRF test data to build a native model.

Option 2 is acceptable for the first field session.

### Acceptance

- A test model changes live classification.
- No model -> fallback works.
- Corrupt model -> fallback works.
- model/sample-rate mismatch is prominently logged.

---

## Milestone 1.3 — build HackRF scan-and-lock

The existing `sweep_locate.py` is a useful start. Turn the concept into a repeatable field workflow.

### Required operating modes

At minimum:

```text
baseline
scan
lock
capture
replay
```

Suggested commands/API shape; exact CLI names are flexible:

```bash
# measure environment with test drones off
uv run aerix-rf baseline --band 2.4 --seconds 30 --out sessions/site-baseline

# search for new/interesting signals
uv run aerix-rf scan --band 2.4
uv run aerix-rf scan --band 5.8

# lock to a discovered channel and inspect continuously
uv run aerix-rf lock --center-mhz 2437 --seconds 60

# save a labelled raw capture
uv run aerix-rf capture --center-mhz 2437 --seconds 30 \
    --label drone-a-motors-on --out sessions/test-001

# deterministic offline analysis
uv run aerix-rf replay sessions/test-001
```

Do not spend excessive time on perfect CLI ergonomics. A clear test tool is enough.

### Scan algorithm

Use a baseline differential where possible:

```text
current spectrum - baseline spectrum
```

Rank candidates using factors such as:

- power increase
- occupied bandwidth
- persistence
- burst behavior
- cadence
- frequency hopping behavior

Return multiple candidates, not just the hottest frequency.

### Acceptance

- Baseline can be recorded and reused.
- Scan returns a ranked candidate list.
- User can lock onto a candidate without editing code.
- Locked mode generates spectrogram/detection/classification/decode output.
- User can return to scanning.

---

## Milestone 1.4 — make capture/replay first-class

Field captures are one of the most valuable outputs of Phase 1.

Every significant test should generate a self-describing session directory.

Recommended structure:

```text
sessions/
  2026-09-xx_test_001/
    session.json
    iq/
      capture_0001.cs8
      capture_0002.cs8
    spectrograms/
    detections.jsonl
    decode.jsonl
    summary.md
```

### `session.json`

Capture at least:

```text
session_id
started_at
software_git_sha
receiver_type
receiver_serial if available
sample_rate
center_frequency / scan range
gain settings
antenna description
location optional
environment notes

test_label
drone_manufacturer
drone_model
drone_serial if intentionally recorded
drone_state
controller_state
motors_state
approx_distance_m optional
operator_notes
```

Also store per-file:

```text
SHA256
sample count
capture duration
capture complete/incomplete
```

### Important label semantics

A human saying "Drone A motors on" is **test-session ground truth about the test condition**.

It does not prove that every RF emitter in the recording belongs to Drone A.

Keep these separate:

```text
test_condition_label
RF classifier output
protocol-confirmed identity
```

This distinction will matter when Phase 2 creates training labels.

### Acceptance

- A field session is understandable later without relying on memory.
- Captured IQ can be replayed on another machine.
- Replay produces the same protocol-decode result and materially equivalent classifier/detector output.

---

## Milestone 1.5 — validate the real DJI decoder

The synthetic decoder work is useful but does not close the decoder task.

### Objective

Obtain and preserve at least one real HackRF recording containing a publicly decodable DJI DroneID transmission, if either available test drone uses a supported format.

### Validation hierarchy

```text
Level A
real IQ -> sync candidate

Level B
real IQ -> OFDM/descramble succeeds

Level C
real IQ -> Turbo + CRC24A valid

Level D
parsed serial/position agrees with independently known test information
```

Only Level C/D should be described as a successful real decode.

### Decoder robustness work

Before/while testing address known TODOs that materially block real capture decoding, particularly:

- integer/multi-subcarrier CFO handling
- 8-symbol variant if encountered
- multiple candidate bursts within a longer recording
- decoding burst-by-burst rather than passing a huge 1-second array blindly through expensive processing

Do not over-engineer unobserved variants before real testing.

### If the available drones are O4

Do not declare Phase 1 failed merely because encrypted O4 position cannot be decoded with the current local decoder.

For an O4 test aircraft, Phase 1 success can be:

```text
repeatable RF discovery
+ repeatable signal capture
+ repeatable spectral/cadence signature
+ classifier output
+ preserved raw IQ for later O4/ANTSDR work
```

O4-specific decoding/detection integration is primarily Phase 3 with ANTSDR.

---

## Milestone 1.6 — create a simple local test dashboard/report

Do not build the production AERIX UI yet.

Provide enough local visibility to operate a field test.

Minimum output should show:

```text
time
center frequency
peak frequency
signal score
SNR / relative power
occupied bandwidth
burst/cadence info
Stage-1 morphology
Stage-2 class + confidence + source
protocol-decode state
serial/location if CRC-valid decode exists
capture health
```

A terminal UI, local HTML page or simple FastAPI page is acceptable.

The goal is **testability**, not visual polish.

Provide a session summary generator that makes a Markdown report after a test session.

---

# 5. PHASE-1 two-drone field test protocol

Do not optimize only against one successful capture. Use a repeatable test matrix.

The two available aircraft should be called:

```text
DRONE_A = DJI Mini (exact model to be recorded)
DRONE_B = second DJI aircraft (exact model to be recorded)
```

Before the test, record exact model and firmware versions if readily available.

## Test 0 — environment baseline

No test drone/control link active.

Record:

- 2.4 GHz baseline
- configured 5 GHz/5.8 GHz baseline
- at least 5 minutes of representative local RF conditions
- nearby Wi-Fi channel activity if observable

Goal:

Establish what the site looks like without the test drones.

Expected:

- plenty of RF candidates may exist
- zero CRC-valid DJI identity decodes attributable to the test aircraft
- baseline saved for differential scan

---

## Test 1 — controller only

For each aircraft where practical:

```text
controller ON
dr one OFF
```

Record scan + locked captures.

Goal:

Learn which RF signatures belong to controller/control-link activity versus DroneID transmissions.

---

## Test 2 — aircraft powered, motors not running

For each drone:

```text
controller ON
aircraft ON
motors OFF
```

Record scan + lock + capture.

Goal:

Separate general OcuSync/control-link RF from the DroneID condition.

Do not assume power-on alone generates the same DroneID transmission as motors-running operation.

---

## Test 3 — motors/normal operational state

Operate the aircraft in a safe test configuration according to the manufacturer's procedures.

For each drone:

- scan 2.4 GHz
- scan configured 5 GHz/5.8 GHz range
- identify candidate(s)
- lock and capture
- run detector
- run classifier
- run protocol decoder
- preserve at least one long raw capture and several shorter event captures

Repeat at least three times per drone.

---

## Test 4 — distance variation

If the site allows it, repeat at several approximate ranges, for example:

```text
near
medium
farther practical test point
```

Record actual approximate distance in session metadata.

Do not use these results as calibrated ranging yet. They are for sensitivity/repeatability characterization.

---

## Test 5 — both drones

Optional but strongly useful after single-aircraft tests are understood.

Operate both test systems in a controlled manner and determine:

- can scanning reveal more than one active candidate?
- does lock-following one signal hide the other?
- can offline recordings distinguish them?
- if identities are decodable, can captures be associated correctly?

This test is informational; Phase 1 does not require one HackRF to continuously track both hopping drones simultaneously.

---

# 6. Phase-1 measurements and acceptance criteria

Phase 1 exits only when we have **real test evidence**, not just green unit tests.

## Required software criteria

Status as of 2026-09-04 (branch `aerix-rf`, HackRF Pro serial `…7313`, this laptop as the box):

- [x] Continuous HackRF live source works reliably. — `LibHackRFSource` (ctypes libhackrf, no
      SoapySDR). 10-minute ambient soak on 2440 MHz: 504 windows, no process failure, stream rate
      ratio 0.999. Ring-style queue (drop-oldest) so a slow consumer costs *gaps between*
      windows, never holes inside one; every transfer carries a sequence number and a window
      is `complete` only if its chunks are consecutive.
- [x] Capture health/overflow/short-read state is visible. — `IQWindow.health()` in every
      `detections.jsonl` record and the status line (`cap=ok | INCOMPLETE(-n) | gap=…ms`);
      summary.md shows complete/incomplete, cumulative overflow, stream lost between windows,
      min stream-rate ratio.
- [x] Scan -> candidate -> lock workflow works without code edits. — `aerix-rf baseline | scan |
      lock | capture` (`aerix_rf/scan/*`, hackrf_sweep based, ranked candidates with rise over
      baseline / persistence / burstiness / hop detection). Live-verified on ambient Wi-Fi.
- [x] Raw IQ session capture works. — `sessions/<utc>_<label>/{session.json, iq/*.cs8,
      spectrograms/, detections.jsonl, decode.jsonl, summary.md}`, sha256 per IQ file, disk
      guard + `--max-gb` cap.
- [x] Replay works deterministically. — `aerix-rf replay <session>`: sim session replays with
      score delta 0.000 and identical class/decode; the .cs8 codec is bit-exact for hardware
      windows (int8/128 both ways). Tampered IQ raises `SessionIntegrityError`.
- [x] Live ML path is actually wired in when a valid model is supplied. — `classify_window()`
      loads `$AERIX_RF_MODEL` / `models/signature.joblib`; label/confidence/source/model
      version in every record; abstains to `unknown` below 0.5; sample-rate mismatch → one
      prominent WARNING + `model_sample_rate_mismatch: true` on every record (advisory only,
      per option 2 in M1.2). **No model was used in the 2026-09-04 runs** (rule path).
- [x] Rule fallback works without a model. — and with a corrupt bundle (tested).
- [x] Stage 1 no longer claims drone identity solely from bandwidth. — Stage 1 emits a
      *morphology* (`noise | narrowband_candidate | wideband_candidate | burst_wideband_candidate |
      ofdm_candidate | fhss_candidate | continuous_wideband_candidate | analog_candidate |
      unknown`); identity lives in Stage 2 (`dji_ocusync | wifi_uas | analog_fpv | other_uas |
      non_uas | unknown`). The rule for `dji_ocusync` (≤ 0.6) needs OFDM/burst morphology,
      300–1000 ms cadence, 6–16 MHz, **2–8 sparse bursts with duty < 0.2** — the last clause
      was added after 2 of 504 ambient windows (157 Wi-Fi packets/s with a spurious 630 ms
      "cadence") were labelled dji_ocusync in the soak.
- [x] Protocol decode is independent from ML approval. — `pipeline.process_window` runs
      `decode_all()` on any non-noise window regardless of the Stage-2 label.
- [x] Field session report is generated. — `summary.md` per session (`aerix-rf report`).
- [x] Automated tests remain green. — see commit message for the count.

**What is real-hardware validated vs synthetic only (2026-09-04):**

| Component | Real HackRF | Synthetic |
|---|---|---|
| Continuous stream, health counters, retune | yes (10 min soak, ambient) | – |
| DC-spike removal (48 dB spike at f_c without it) | yes | test |
| Sweep baseline / differential scan / ranking | yes (ambient Wi-Fi ch 3/6/9 found) | 14 tests |
| Stage-1 morphology on ambient | yes (`fhss_candidate` / `burst_wideband_candidate`) | tests |
| Stage-2 rule labels | ambient only → `unknown`, 0 `dji_ocusync` after rule fix | tests |
| DroneID decode levels A/B/C, integer CFO, multi-burst | **no real burst yet** | 37 tests, CRC-valid on encoded synthetic bursts |
| Session store / replay / report | yes (sessions written from hardware) | 6 tests |
| ML classifier live path | not exercised (no model) | tests with a dummy bundle |

**Known limitations going into the field test:** a busy 2.4 GHz band makes almost every
window `plausible` (score is "interesting", not "drone"); the differential scan against a
baseline and the per-window morphology/cadence are what separate a drone from Wi-Fi, and only
a CRC-valid decode attributes identity. The laptop keeps up with the radio only while the
per-window pipeline stays under ~1 s (decode is budgeted at 0.25 s/window); if it does not,
`gap=` on the status line says how much stream was skipped between windows.

## Required real-world criteria

For **both available DJI drones**:

- [ ] A repeatable RF change can be found relative to baseline.
- [ ] At least one candidate frequency/channel can be locked and recorded.
- [ ] The same behavior can be reproduced in at least 3 independent runs.
- [ ] Raw IQ is saved with complete metadata.
- [ ] Offline replay sees the same key RF event(s).

For any test drone using a publicly decodable O2/O3 DroneID format:

- [ ] At least one real frame reaches CRC-valid decode, OR the blocker is isolated with preserved IQ and a specific decoder defect documented.
- [ ] If CRC-valid, decoded identity/location is compared with known test truth / Remote ID output where available.

For an O4-only aircraft:

- [ ] O4 inability to decrypt position locally is documented as expected rather than treated as a generic detector failure.
- [ ] Representative IQ is preserved for Phase 3 ANTSDR/O4 comparison.

## False-positive characterization

Run at least a 30-minute local baseline/ambient session after the detector is stable.

Measure separately:

```text
RF candidate rate
ML UAS-classification rate
CRC-valid DJI protocol decode rate
```

A Stage-1 RF candidate in busy spectrum is not automatically a false drone alert.

The most important safety invariant is:

```text
normal Wi-Fi must never become a protocol-confirmed DJI drone without a valid decode
```

---

# 7. Phase-1 deliverables

Claude should finish Phase 1 with these concrete outputs.

## Code

- hardware-neutral `IQSource`/`IQWindow` abstraction
- stable HackRF continuous source
- capture-quality metadata
- live ML integration
- morphology-vs-identity separation
- improved scan/lock tooling
- first-class capture/replay
- real-burst decoder improvements only as required by captured evidence
- local test status output
- session report generator

## Test assets

Do not commit huge IQ data to git.

Provide documented local storage structure and optional small fixtures only.

Expected real test artifacts outside git:

```text
baseline session
drone A sessions
drone B sessions
controller-only sessions
motors-off sessions
motors-on sessions
representative IQ captures
session reports
```

## Documentation

Update `aerix-rf/README.md` after Phase 1 to clearly state:

```text
what is real-hardware validated
what is only synthetic validated
which two aircraft were tested
which protocols decoded
which did not
known sensitivity / false-positive limitations
exact test commands
```

Do not claim successful O2/O3/O4 coverage without test evidence.

---

# 8. PHASE 2 — integrate the proven RF engine into AERIX server

Start Phase 2 only after Phase 1 field testing has produced useful real captures.

The goal is to integrate **the proven local RF event model**, not debug raw RF through the server.

## 8.1 Normalize local RF events

Introduce/use a receiver-independent event model, for example:

```python
@dataclass
class RFEvent:
    event_id: UUID
    sensor_id: str
    receiver_type: str
    captured_at: datetime

    center_freq_hz: float | None
    bandwidth_hz: float | None
    rssi_dbm: float | None
    snr_db: float | None

    signal_class: str | None
    signal_confidence: float | None

    uas_class: str | None
    uas_confidence: float | None

    protocol: str | None
    protocol_version: str | None
    decode_state: str | None

    identity: dict | None
    location: dict | None
    evidence: dict | None
    timing: dict | None
    calibration: dict | None
```

Exact field structure may differ, but keep the semantic separation.

---

## 8.2 Fix ODID/RF correlation semantics

The current `verified=true` behavior is too permissive if it simply means an ODID cue occurred in the same loop.

Replace/augment it with explicit correlation quality.

Suggested:

```text
correlation_level
0 none
1 temporal coincidence
2 temporal + site consistency
3 temporal + RF consistency
4 protocol-confirmed UAS signal
5 same identity confirmed by RF decode and ODID
```

And:

```text
label_quality = NONE | WEAK | STRONG | GROUND_TRUTH
```

Only truly strong/protocol-confirmed samples should feed automatic training as hard labels.

Phase-1 manual test-condition labels remain separate from server correlation.

---

## 8.3 RF sensor provisioning

Generalize away from a permanent HackRF-only fleet identity.

Preferred long-term concept:

```text
sensor_class = rf
receiver_type = hackrf
receiver_type = hackrf_pro
receiver_type = antsdr_e200_ad9361
receiver_type = bladerf2
receiver_type = generic_soapy
```

If a broad sensor-class migration is too invasive, preserve compatibility while adding receiver metadata cleanly.

Remove hard-coded heartbeat identifiers such as:

```python
["hackrf-1"]
```

---

## 8.4 Evidence

Server RF events should be able to reference:

```text
spectrogram
short IQ evidence clip
capture metadata
SHA256
classifier/model version
decoder version
```

Do not upload continuous IQ by default.

Short evidence/event captures are enough for normal operation.

---

## 8.5 Retention and privacy

Preserve the existing RF retention design.

Decoded operator coordinates or other personal data must retain stricter policy handling.

Training-data promotion must be explicit and auditable.

---

## Phase-2 exit criteria

- [ ] HackRF RF node provisions cleanly.
- [ ] Real Phase-1-style detections reach the server.
- [ ] Spectrogram/evidence metadata is preserved.
- [ ] RF and ODID remain distinct source types.
- [ ] Correlation never silently upgrades temporal coincidence to ground truth.
- [ ] Protocol-confirmed DJI identity can correlate to the corresponding AERIX track when data exists.
- [ ] Receiver health/heartbeat is visible.
- [ ] Retention works for RF rows/evidence.

---

# 9. PHASE 3 — ANTSDR E200 integration

> **Revision 2 note (2026-09-18):** this phase is now ACTIVE as "Phase A" (see §0). The
> sentence below about waiting for the server event model is retired. Authoritative,
> up-to-date material: `research/briefs/antsdr-e200.md` (device facts, firmware options),
> `docs/design/antsdr-backend.md` (backend design, builder tasks T1–T6),
> `docs/design/canonical-representation.md` (rates, formats, STFT, normalisation).
> Mode A (DJI protocol-event backend) stays a LATER track; Mode B (raw-IQ backend) is what
> Phase A implements first.


Only begin this after the HackRF pipeline is understood and the server event model is stable.

Primary target:

```text
ANTSDR E200 AD9361
```

The ANTSDR should not cause another DSP/server redesign.

It must plug into the abstractions created in Phases 1 and 2.

---

## 9.1 ANTSDR operating modes

ANTSDR should ultimately provide two complementary modes.

### Mode A — DJI protocol-event backend

Use the public ANTSDR DJI receiver ecosystem as an event source.

Reference:

```text
https://github.com/alphafox02/antsdr_dji_droneid
```

Target behavior:

```text
ANTSDR firmware
 -> public receiver protocol/output
 -> AntSdrDjiEventSource
 -> normalized RFEvent
 -> AERIX
```

Publicly documented capabilities currently include:

### O2/O3

- serial
- model
- drone GPS
- pilot GPS
- home GPS
- altitude/speed
- RSSI

### O4

- encrypted O4 detection
- session/hash ID
- frequency
- RSSI

Do not put an O4 hash into a serial field.

Represent it separately:

```text
protocol_version = O4
decode_state = encrypted_detected
session_hash = ...
```

### Optional DragonScope

If supported later, treat it as optional external enrichment.

AERIX must not depend on a licensed/internet service for basic RF detection.

---

## 9.2 ANTSDR raw-IQ backend

After event integration works:

```text
AD9361
 -> libiio/UHD
 -> IQWindow
 -> exact same DSP/classifier/decoder contracts used by HackRF
```

Use this for:

- non-DJI RF
- generic UAS classification
- unknown signals
- research captures
- cross-validation against HackRF
- future timing/localization work

Do not fork a second AERIX RF detector for ANTSDR.

---

## 9.3 timing groundwork

ANTSDR gives us a future path toward synchronized receivers.

Add/support timing metadata cleanly:

```text
capture_start_ns
sample_counter
clock_source
clock_uncertainty_ns
pps_locked
reference_10mhz_locked
```

Do not claim TDOA accuracy before synchronized multi-node measurements prove it.

TDOA is a later milestone built on this metadata.

---

## Phase-3 exit criteria

- [ ] ANTSDR can produce normalized AERIX RF events.
- [ ] Public O2/O3 events map correctly.
- [ ] Public O4 detections map correctly without pretending to have position.
- [ ] ANTSDR health is visible through the same fleet model.
- [ ] Raw-IQ ANTSDR mode can feed the same detector/classifier path as HackRF.
- [ ] HackRF still works after ANTSDR is added.
- [ ] No server schema is coupled specifically to ANTSDR firmware output.

---

# 10. bladeRF — deliberately later

Do **not** implement bladeRF during Phases 1–3 unless specifically requested.

The architecture should make later support easy.

Desired later implementation should be approximately:

```text
BladeRFSource
 -> IQWindow
 -> existing DSP
 -> existing classifier
 -> existing decoder
 -> existing RFEvent
```

Prefer a standard backend such as SoapySDR where it gives adequate access to required bladeRF features.

A successful architecture means bladeRF support is mostly a receiver adapter plus hardware-specific configuration/tests, not a rewrite of detection logic.

The same should be true for a future USRP or other SDR.

---

# 11. Testing philosophy

## Never optimize only for synthetic data

Synthetic tests are useful for regression and decoder correctness.

They are not evidence of real RF performance.

Maintain three distinct levels:

```text
unit/synthetic tests
recorded-IQ replay tests
live hardware field tests
```

All three matter.

---

## Prevent data leakage

For ML evaluation:

- split by recording/session, not arbitrary neighboring windows
- ideally split by separate collection session/day/site
- later, validate on drone hardware not present in the training set

Do not headline near-100% validation accuracy if train and validation contain adjacent windows from the same recording.

---

## Unknown must remain a valid answer

The RF system should be allowed to say:

```text
interesting wideband RF: high confidence
UAS likelihood: moderate
vendor/model: unknown
```

That is better than confidently assigning DJI to Wi-Fi.

---

# 12. Claude execution instructions

Claude Code should work through this document sequentially.

## Start here now

The next work session should implement **Phase 1 Milestone 1.1 first**.

Order:

1. inspect current `sdr/capture.py`, `main.py`, tests and CLI entrypoint
2. introduce the smallest useful `IQWindow`/capabilities abstraction without breaking replay/sim
3. make continuous HackRF streaming the preferred test path
4. expose stream health
5. add/adjust tests
6. run full test suite
7. update this document with completed checkboxes/notes
8. commit
9. then continue to Milestone 1.2

Do not start server migrations, ANTSDR code, bladeRF code, TDOA or UI product work during this first task.

### Execution log

- **2026-09-04** — Milestones 1.1–1.6 implemented on branch `aerix-rf` (see §6 "Required
  software criteria" for what is hardware- vs synthetic-validated). Field-test commands are in
  `README.md` → "Field test". Next: the two-drone protocol in §5 (Test 0 → Test 3, ≥ 3 runs
  per drone). No server, ANTSDR, bladeRF, TDOA or UI work was started; Phase 1 runs entirely
  without the server.
- **2026-09-04, field test 1** (laptop + HackRF Pro, stock antenna, at home; DJI Mini 3 with
  RC-N1, DJI Avata with Goggles 2 + motion controller; Test 0/3 style runs, captured to
  `sessions/`, not committed). Results:
  - **First success reached in part:** find → capture → distinguish → **decode** → replay all
    demonstrated on the Mini 3: four CRC-valid OcuSync 2 DroneID bursts at 2429.5 MHz (640 ms
    cadence, serial + sequence 18/19/20 consistent, coordinates 0.0 = no GPS fix), replayed
    bit-exactly from the session IQ. First found offline by a brute-force ZC scan of the known
    DroneID centres; the live decoder then missed it because the burst sat 7.5 MHz off the
    window centre and 20 dB under the RC hops / Wi-Fi beacons. Fixed (per-burst PSD shape
    screening + per-burst mixing to DC); `replay` of the session now yields `dec=C` live-fast.
  - **Not achieved:** no DroneID burst seen in any Mini 3 *flight* window (2412/2437/2455/
    2475 MHz steps) — so no real coordinates yet; the Avata was not unambiguously captured
    (5.8 GHz flat with the stock antenna, 2400–2412 MHz never covered).
  - **Mis-attribution caught by the all-off reference:** the strong 18 MHz / 102.4 ms bursts
    at 2413–2431 MHz first read as "goggles uplink" were the FRITZ!Box on Wi-Fi channel 3.
    Absolute `score` saturates at 1.0 in this band; only the differential scan and CRC-valid
    decodes are evidence. Stage 1/2 retune needed (fixed-channel links are not `fhss`; discount
    beacon-period and BLE-advertising sources; the `dji_ocusync` rule needs the RC-hop and
    video-frame signatures).
  - **Next field session:** Mini 3 in flight with a GPS fix, lock on 2437 (covers 2429.5 and
    2444.5) and on 2412/2455 for the other two centres; Avata with lock on 2402 plus a fresh
    all-off reference; 5.8 GHz needs a proper antenna/LNA.

---

# 13. Definition of overall success

The project should progress through evidence rather than roadmap claims.

## First success

```text
HackRF + two real DJI drones
 -> find RF
 -> capture RF
 -> distinguish it from ambient RF
 -> decode when protocol allows
 -> replay exact evidence offline
```

## Second success

```text
that proven local RF engine
 -> AERIX server
 -> trustworthy RF/ODID correlation
 -> evidence and retention
```

## Third success

```text
ANTSDR
 -> same AERIX contracts
 -> better DJI protocol coverage
 -> O4 detection
 -> generic IQ path
 -> timing foundation
```

Only after that should additional SDR hardware such as bladeRF be integrated.
