# AERIX RF / ANTSDR — Full implementation scope

> **Working document for Claude Code**  
> Branch: `aerix-rf`  
> Scope owner: AERIX RF  
> Primary target hardware: **ANTSDR E200 AD9361**  
> Secondary/legacy target: **HackRF / HackRF Pro**  
> Status snapshot: 2026-09-04, branch head before this document: `c32663e5ec1226fe0f1d314f41f24be8e9207999`

---

## 0. Mission

Turn the current `aerix-rf` prototype into a hardware-independent, production-oriented passive RF sensing subsystem for AERIX with the ANTSDR E200 as the primary SDR platform.

The system must be able to:

1. Detect RF activity that is plausibly related to drones without requiring Remote ID.
2. Decode DJI DroneID/OcuSync telemetry when the protocol is publicly decodable.
3. Detect DJI O4 transmissions even when position telemetry cannot be decoded locally.
4. Correlate RF detections with AERIX Remote ID observations without poisoning the RF training dataset.
5. Preserve raw IQ around meaningful detections for later analysis/training.
6. Support generic ML-based RF classification in addition to protocol-specific DJI decoding.
7. Prepare the data model for synchronized multi-node RF localization (TDOA) without pretending that the current implementation already has TDOA-grade timing.
8. Keep HackRF support working while making ANTSDR a first-class receiver.
9. Keep RF detections separate from the ODID `observations` invariant.
10. Fail safely: uncertainty must be represented as uncertainty, never silently upgraded to a confirmed drone/identity/location.

This project is **receive-only/passive**. Do not add transmit, spoofing, jamming, interference, takeover, or active interrogation features.

---

# 1. Current repository state

The current branch is already substantially implemented. Do **not** restart from scratch.

## Already present

### RF pipeline

Current main path:

```text
capture
  -> spectrogram
  -> stage-1 energy/spectral detector
  -> rule classifier
  -> optional DJI DroneID decode
  -> IQ retention
  -> RF ingest endpoint
  -> rf_detections table
```

Relevant files:

- `aerix_rf/main.py`
- `aerix_rf/sdr/capture.py`
- `aerix_rf/dsp/spectrogram.py`
- `aerix_rf/detect/energy.py`
- `aerix_rf/classify/model.py`
- `aerix_rf/decode/*`
- `aerix_rf/buffer/iq_ring.py`
- `aerix_rf/uplink/client.py`
- `contracts/rf-detection.v1.schema.json`
- `db/migrations/038_sensor_class_hackrf.sql`
- `db/migrations/039_rf_detections.sql`

### HackRF

HackRF capture is working via:

- `hackrf_transfer`
- SoapySDR fallback
- file replay
- simulation

The branch has been tested end-to-end on real HackRF hardware for ambient RF:

```text
live capture -> detect -> spectrogram -> ingest -> rf_detections
```

There has **not yet been a validated real-drone field detection** in this branch.

### DJI OcuSync / DroneID decoder

The branch now contains:

- Zadoff-Chu synchronization
- resampling to 15.36 MS/s
- timing synchronization
- CFO correction
- OFDM demodulation
- channel equalization
- QPSK hard decisions
- LTE descrambling
- LTE de-rate-matching
- max-log-MAP Turbo decode
- CRC24A validation
- DJI frame parsing
- serial and position fields

Relevant files:

- `aerix_rf/decode/droneid.py`
- `aerix_rf/decode/turbo.py`
- `aerix_rf/decode/frame.py`
- `aerix_rf/decode/ofdm.py`
- `aerix_rf/decode/zc.py`

The full chain is currently **synthetic-validated**, including exact serial/GPS round trips down to the tested SNR range. It is **not yet validated against a known real DroneID IQ capture**. Preserve that distinction everywhere.

### Real training data

The branch now has a real DroneRF loader and training helper.

Important improvements already made:

- DJI Phantom -> `dji_ocusync`
- Parrot Bebop / AR -> `wifi_drone`
- background -> `noise`
- validation can hold out complete recordings with `GroupShuffleSplit`

This fixes the earlier class-collapse/leakage concern. Do not undo it.

The current DroneRF demonstration is at the dataset's ~40 MS/s rate. It is not yet a valid drop-in deployment model for a 20 MS/s live receiver.

### Server separation

The design decision to keep RF detections separate from ODID observations is correct and must remain.

RF detections currently use:

```text
POST /v1/rf-detections:batch
```

and storage in:

```text
rf_detections
```

Do not force RF events into the ODID `observations` table.

### Retention

The current RF table supports retention classes and expiry, including stricter handling when decoded operator position is present. Keep the retention model.

---

# 2. Critical gaps in the current branch

These are the highest-priority issues found in the current code.

## P0-1 — the trained ML model is not used by the live loop

`aerix_rf/main.py` currently imports:

```python
from .classify.model import classify
```

and runs:

```python
cls = classify(det)
```

But `classify()` is explicitly the **rule-only** path.

The actual model-loading inference function is:

```python
classify_spectrogram(spec, center_freq_mhz)
```

Therefore installing/training `models/signature.joblib` currently does not alter live classification.

### Required fix

Wire the trained classifier into the live path while preserving the rule detector as a fallback.

Desired semantics:

```text
Stage 1: signal candidate detector
Stage 2: ML classifier / open-set classifier
Stage 3: protocol decoder
```

Do not make a model load failure kill the RF service.

### Acceptance

- A test model placed in `AERIX_RF_MODEL` changes live output.
- With no model, rules continue to work.
- Invalid/corrupt model -> warning + fallback, no process crash.
- Live output includes classifier source/version.

---

## P0-2 — `verified=true` is currently unsafe as training ground truth

The live loop currently marks a frame verified if any active ODID cue is drained in the same processing cycle.

That is insufficient.

Example failure:

```text
BLE Remote ID from a drone occurs
            +
SDR happens to be centered on / dominated by unrelated Wi-Fi
            =
RF frame currently becomes verified=true
```

This can poison AERIX's own training dataset.

### Required redesign

Replace a single binary concept with explicit correlation quality.

Recommended model:

```text
correlation_level
0 = none
1 = temporal coincidence only
2 = temporal + site/spatial consistency
3 = temporal + RF/frequency/signature consistency
4 = protocol-confirmed drone signal
5 = same identity confirmed by decoded RF + ODID
```

Alternative naming is acceptable, but semantics must be explicit.

Recommended fields:

```text
correlation_level
correlation_score
correlation_reasons[]
label_quality
label_source
```

Suggested label quality:

```text
NONE
WEAK
STRONG
GROUND_TRUTH
```

Only protocol-confirmed or identity-matched samples should be treated as true ground truth by default.

Temporal coincidence alone may be retained as a **weak label**, never silently treated as hard truth.

### Acceptance

- An arbitrary ODID cue does not automatically make the current RF frame ground truth.
- The server can distinguish weakly correlated vs protocol-confirmed samples.
- Training code can select only `GROUND_TRUTH`, or optionally `STRONG` + `GROUND_TRUTH`.
- Existing `verified` can remain temporarily for compatibility, but must be derived/documented rather than ambiguous.

---

## P0-3 — ANTSDR is allowed in the contract but not implemented as a receiver

`rf-detection.v1.schema.json` already permits:

```text
source = hackrf | antsdr | sdr
```

But acquisition currently only implements:

- HackRF
- file
- simulator

ANTSDR must become a first-class runtime source, not just a roadmap sentence.

---

## P0-4 — provisioning is HackRF-specific

Migration `038_sensor_class_hackrf.sql` adds only `hackrf` as a sensor class.

The heartbeat also contains a hardcoded receiver label:

```python
uplink.heartbeat(["hackrf-1"])
```

Do not add an ever-growing enum of every SDR model if it can be avoided.

Recommended model:

```text
sensor_class = rf
receiver_type = hackrf
receiver_type = hackrf_pro
receiver_type = antsdr_e200_ad9361
receiver_type = usrp_b2xx
receiver_type = bladerf2
receiver_type = generic_soapy
```

If changing `sensor_class` is too invasive for this phase, add `antsdr` cleanly and create a follow-up migration toward generic `rf`. Do not make ANTSDR pretend to be HackRF.

---

## P0-5 — stage 1 currently over-claims signal identity

`detect/energy.py` currently maps bandwidth/cadence heuristics directly to labels such as:

- `dji_ocusync`
- `wifi_drone`
- `fpv_analog`

This is too strong for a generic energy detector.

Normal Wi-Fi can look like a wide OFDM signal. A 20 MHz Wi-Fi transmission can easily resemble the current wideband rule.

### Required semantics

Stage 1 should describe **RF morphology**, not drone identity.

Suggested stage-1 labels:

```text
noise
unknown_narrowband
unknown_wideband
burst_wideband
burst_ofdm_candidate
continuous_wideband
fhss_candidate
analog_wideband_candidate
```

Stage 2 / Stage 3 can then provide higher-level labels:

```text
dji_ocusync
wifi_uas
analog_fpv
other_uas
non_uas
unknown
```

Do not remove the detector score; split **signal candidate confidence** from **drone classification confidence**.

---

# 3. ANTSDR target architecture

## Hardware target

Primary hardware:

```text
ANTSDR E200 + AD9361
```

Do not target the AD9363 variant as the primary AERIX unit because 5.8 GHz is required.

Official ANTSDR documentation currently describes the E200/AD9361 as roughly:

- RF coverage to 6 GHz
- up to 56 MHz RF/channel bandwidth at the AD9361
- Zynq XC7Z020
- 1 GbE host interface
- external 10 MHz / PPS synchronization input
- libiio / UHD support
- practical host-stream bandwidth lower than the RFIC's full analog bandwidth

Relevant docs:

- https://antsdr-docs.microphase.cn/en/latest/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.html
- https://antsdr-docs.microphase.cn/en/latest/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.html

## Public DJI ANTSDR implementation

Reference project:

- https://github.com/alphafox02/antsdr_dji_droneid

Current public behavior documented there:

### O2/O3

Public receiver reports fields including:

- serial
- model
- drone GPS
- pilot GPS
- home GPS
- altitude
- speed
- RSSI

### O4 public firmware

Public receiver supports encrypted O4 **detection**, with fields such as:

- session/hash identifier
- frequency
- RSSI

Position is not available from the public receiver alone.

### DragonScope

DragonScope can enrich O4 with position, but it is licensed/internet-dependent.

AERIX must **not require DragonScope** for basic operation.

It may be supported later as an optional enrichment provider behind a clean interface.

---

# 4. Receiver abstraction

Do not implement ANTSDR by scattering `if antsdr:` throughout the pipeline.

Create explicit receiver/provider abstractions.

Recommended split:

```text
ReceiverSource
├── HackRF IQ source
├── File IQ source
├── Sim IQ source
├── ANTSDR raw-IQ source
└── ANTSDR protocol-event source
```

The important point is that ANTSDR has **two useful operating modes**.

## Mode A — ANTSDR protocol/event backend

```text
ANTSDR FPGA/ARM firmware
        -> TCP/UDP/ZMQ DJI events
        -> AERIX ANTSDR adapter
        -> normalized RF event
```

This should be implemented first.

Do not unnecessarily stream raw IQ to Python just to recreate a decoder that the ANTSDR firmware already provides.

## Mode B — ANTSDR generic raw-IQ backend

```text
AD9361
 -> libiio/UHD IQ
 -> AERIX spectrogram
 -> signal detector
 -> ML classifier
 -> optional local decoder
```

This is required for:

- non-DJI signals
- generic RF classification
- research/training captures
- unknown protocols
- future RF localization work

Implement it after the event backend is stable.

---

# 5. Normalize receiver outputs into events

Introduce a receiver-independent internal event type instead of making server contracts depend on one device's format.

Example internal model (names may be adjusted):

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

    identity: ...
    location: ...
    timing: ...
    calibration: ...
    evidence: ...
```

This internal object can later be serialized into the server envelope.

The exact implementation need not copy this literally; preserve the separation of concepts.

---

# 6. Extend decoded DJI semantics

The current `decoded` structure is too O2-centric.

The data model must distinguish:

```text
identity serial
```

from:

```text
O4 session/hash identifier
```

Never place an O4 session hash into the serial field.

Recommended normalized DJI fields:

```text
vendor: DJI
model
protocol
protocol_version

decode_state:
  protocol_detected
  encrypted_detected
  decoded

serial
session_id
session_hash

drone:
  lat
  lon
  altitude
  height
  speed_horizontal
  speed_vertical

operator:
  lat
  lon

home:
  lat
  lon

rf:
  frequency_hz
  rssi_dbm

decoder:
  name
  version
  firmware_version
```

For O4 public detection:

```text
protocol = dji_ocusync
protocol_version = O4
decode_state = encrypted_detected
session_hash = ...
location = null
```

That is a valid, useful event.

---

# 7. ANTSDR DJI event adapter — first hardware milestone

Implement support for the public `alphafox02/antsdr_dji_droneid` output before implementing raw-IQ ANTSDR capture.

Current public reference receiver supports:

- new firmware: reversed TCP connection to host, default port 52002
- UDP on 52002 as alternative transport
- ZMQ publisher on 4221
- legacy firmware path on 41030

AERIX should not need all modes on day one.

## Minimum implementation

Implement at least one well-supported path first, preferably the normalized host output rather than reimplementing firmware internals.

Suggested:

```text
AntSdrDjiEventSource
```

with support for either:

1. subscribing to the local ZMQ output, or
2. parsing the public host receiver output directly.

Choose the lowest-maintenance integration after inspecting the actual public message format.

### Required properties

- reconnect automatically
- tolerate malformed messages
- expose firmware/device identity
- preserve O4 hash separately
- include exact receive time
- no duplicate storm after reconnect
- clear health state when the ANTSDR becomes unavailable

### Acceptance

Provide replay fixtures captured from the public ANTSDR receiver format so tests do not require live hardware.

Tests must cover:

- O2/O3 decoded example
- O4 detection-only example
- malformed event
- reconnect/replay behavior
- duplicate handling

---

# 8. ANTSDR raw-IQ source

After event integration works, implement a generic raw-IQ source.

Preferred APIs:

- libiio first if simplest/stable on E200
- UHD if it is demonstrably more reliable for this use case
- Soapy only if it does not introduce needless extra layers

Do not hardcode assumptions from HackRF `cs8` into ANTSDR processing.

ANTSDR is 12-bit-class RF hardware and its sample format/scaling/calibration differs from HackRF.

## Required features

- receiver selection by config
- center frequency
- sample rate
- analog bandwidth
- gain mode / AGC mode
- channel selection
- overflow detection
- timestamp metadata where available
- calibration metadata
- clean close/reconnect
- replayable capture format

## Important throughput constraint

Do not assume that the complete AD9361 56 MHz RF bandwidth can always be continuously streamed over the E200 host link into Python.

Design the architecture so that:

- protocol-specific FPGA/ARM processing can stay on-device
- raw IQ can use narrower windows when needed
- short triggered high-value captures can be retained
- server never depends on full-band continuous IQ streaming

---

# 9. Multi-band strategy

A single narrow live IQ window is not equivalent to continuous coverage of all relevant 2.4/5.x GHz channels.

For ANTSDR DJI firmware, let its supported hopping/scanning mechanism perform DJI-specific coverage where possible.

For generic RF detection, design a configurable scan plan.

Example:

```yaml
scan_profiles:
  drone_24:
    ranges:
      - [2400e6, 2483.5e6]

  drone_58:
    ranges:
      - [5725e6, 5875e6]
```

Do not implement a naive sweep that spends so little dwell time per channel that short transmissions are systematically missed.

Record scan metadata so the server knows when the receiver was actually observing a frequency.

Suggested fields:

```text
scan_profile
center_freq
observed_start
observed_end
dwell_ms
coverage_fraction
```

This will matter when interpreting a non-detection.

---

# 10. Timing model — prepare now for TDOA

AERIX currently records millisecond-level `captured_at` values. That is enough for map/event correlation but not enough for RF TDOA.

The E200 provides an external 10 MHz/PPS synchronization input, so future synchronized deployment is realistic.

Do **not** claim TDOA accuracy until hardware timestamping and synchronization have been measured.

Add timing metadata now.

Recommended fields:

```text
capture_start_ns
capture_end_ns
sample_index_start
sample_count
sample_rate

clock_source:
  system
  ntp
  ptp
  gps_pps
  external_pps
  unknown

clock_locked
reference_10mhz_locked
pps_locked
clock_uncertainty_ns
```

The implementation should distinguish:

```text
host arrival timestamp
```

from:

```text
RF sample / hardware timestamp
```

Do not use host socket arrival time as if it were TDOA-grade RF arrival time.

---

# 11. O4 localization roadmap

O4 payload decryption is **not** a required dependency for AERIX RF.

AERIX should support several location methods with explicit provenance.

Recommended location result fields:

```text
location_method
location_confidence
location_accuracy_m
participating_sensor_ids[]
```

Methods:

```text
decoded_rf
remote_id_correlation
tdoa
aoa
rssi_area
external_enrichment
```

## Phase 1 — Remote ID fusion

If an O4 RF hit is correlated with a valid BLE/Wi-Fi Remote ID track, use the RID position with explicit provenance.

Do not call this O4-decrypted GPS.

## Phase 2 — RSSI area estimate

Multiple nodes can provide a coarse RF probability area using calibrated RSSI.

Treat this as approximate.

Do not report false precision.

## Phase 3 — TDOA research

Future design:

```text
same O4 hash/session
      +
short synchronized IQ snippets from >= 3 receivers
      -> cross-correlation
      -> delta-t measurements
      -> hyperbolic position solve
```

The O4 session/hash is useful for associating detections across nodes, but the actual TDOA measurement must come from synchronized waveform/sample timing, not from normal server event timestamps.

### TDOA research deliverables

Later, not P0:

- synchronized capture fixture format
- cross-correlation tool
- simulated geometry tests
- measured PPS lock quality
- known transmitter field test
- uncertainty ellipse output
- minimum geometry checks / GDOP-like quality metric

Do not begin field TDOA claims before the timing layer is implemented and measured.

---

# 12. RF calibration model

Current HackRF `rssi_dbm` is approximate and effectively derived from dBFS/gain assumptions.

This is fine for prototype relative strength but insufficient for meaningful cross-sensor comparison.

Add metadata such as:

```text
receiver_type
receiver_serial
rf_channel

gain_mode
gain_db
lna_gain_db
vga_gain_db
agc_state
adc_overload
clipping_detected

antenna_id
antenna_gain_db
polarization
cable_loss_db
filter_profile
lna_profile

calibration_id
calibration_date
receiver_temperature_c
```

Not every field must be present for every receiver.

### Calibration principle

Never silently compare RSSI from:

```text
HackRF A
ANTSDR B
ANTSDR C with AGC
```

as if all values were absolute calibrated dBm.

Expose a quality/provenance flag.

---

# 13. Classifier redesign

## Keep the new real-data work

Preserve:

- correct DroneRF DJI vs Parrot labels
- grouped split by source recording
- common feature extraction for training/live paths

## Fix live inference

See P0-1.

## Add open-set / abstain behavior

A classifier must be allowed to say:

```text
unknown
```

or:

```text
abstain
```

Do not force every RF transmission into a known drone class.

## Separate three questions

Recommended hierarchy:

### A. Signal presence

```text
interesting RF signal vs background/noise
```

### B. UAS likelihood

```text
uas_rf
non_uas_rf
unknown
```

### C. Family/vendor/protocol

```text
dji_ocusync
wifi_uas
analog_fpv
other_uas
unknown
```

A future model can add vendor/model identification, but do not make that a prerequisite for initial production detection.

## Model metadata

Model bundle must include at least:

```text
model_id
model_version
trained_at
feature_version
training_sample_rate
training_bandwidth
classes
dataset_manifest_hash
validation_summary
```

Avoid opaque model files that cannot later be audited.

---

# 14. Training datasets / validation program

Current DroneRF work is only a starting point.

Add loaders/evaluation support progressively for public datasets such as:

- DroneRF
- DroneDetect
- RFUAV
- UAVSig
- CardRF
- Noisy Drone RF / robust low-SNR datasets
- additional real AERIX captures

The project does not need to download multi-terabyte datasets automatically.

## Critical validation rule

Do not report random-window validation from the same recording/session as evidence of real-world generalization.

Prefer splits by:

1. recording/session
2. location/site
3. day
4. receiver hardware
5. drone physical unit

Best validation later:

```text
train on known sessions/sites
validate on unseen sessions
final test on unseen site + unseen physical drone where possible
```

## Hard negatives are mandatory

Collect and label:

- Wi-Fi AP traffic
- Wi-Fi client traffic
- Bluetooth
- video streaming
- phones/hotspots
- nearby industrial RF
- other ISM-band emitters
- quiet background

A production RF detector is judged more by rejecting these than by recognizing clean lab drone signals.

---

# 15. Field capture mode

Add a deliberate field-test/capture mode.

It should make it easy to create reproducible AERIX RF datasets.

Suggested metadata:

```text
capture_id
site_id
operator test note
drone manufacturer/model
physical drone identifier (test-only pseudonym acceptable)
controller model
firmware version
motors state
flight state
known drone GPS
known operator GPS
receiver position
receiver config
antenna config
weather optional
start/end time
```

Do not require personal information beyond what is needed for a controlled test.

Provide a manifest next to IQ files so data never becomes anonymous binary blobs with unknown sample rate/frequency/gain.

---

# 16. Real DJI decoder validation

The new Python Turbo/CRC/frame decoder is promising but currently synthetic-only.

This is a dedicated milestone.

## Required validation sequence

1. Obtain a known public or self-captured O2/O3 DroneID IQ recording.
2. Run the existing public decoder against it where possible.
3. Run AERIX decoder.
4. Compare:
   - CRC outcome
   - serial
   - drone position
   - operator position
   - home position
   - sequence
5. Save a short legal/re-distributable fixture if licensing permits; otherwise save a synthetic fixture plus test instructions for the private real sample.

## Decoder correctness issues to check

Existing TODOs include:

- integer / multi-subcarrier CFO handling
- 8-symbol variant

Also verify:

- endianness
- signed coordinate/value conversion
- altitude/height semantics
- CRC implementation against real frames
- malformed frame bounds checking

Do not delete the synthetic encode/decode tests; add real-data validation alongside them.

---

# 17. Security hardening

## Local API authentication

Current `local_token` is optional. In the current implementation, an empty token effectively makes local cue/snapshot calls unauthenticated.

That is unsafe once cues influence labels/training/evidence.

### Required behavior

Development/simulation may explicitly allow unauthenticated local API.

Production mode must require authentication.

At minimum:

- mandatory secret/token
- timestamp
- replay window or nonce

Prefer mTLS later for appliance-to-appliance communication if practical.

## Training/model supply chain

`joblib`/pickle-style model loading is code-execution capable if the model file is malicious.

Do not blindly auto-download and load arbitrary model files.

For managed deployment implement one of:

- signed model artifacts + pinned hashes
- a safer serialization/runtime such as ONNX where appropriate

At minimum verify SHA-256 + expected model metadata before activating a model.

## ANTSDR network input

Treat ANTSDR TCP/UDP/ZMQ data as untrusted input:

- length limits
- field validation
- malformed messages must not crash service
- no `eval`
- no shell interpolation
- reconnect rate limiting

---

# 18. Server contract evolution

Do not break v1 consumers silently.

Prefer either:

- backward-compatible optional fields within the current `1.x` contract, or
- an explicit `rf-detection.v2` if semantics change incompatibly.

Fields likely needed:

```text
receiver_type
receiver_serial
hardware_revision
firmware_version

signal_class
signal_confidence
classifier_class
classifier_confidence
classifier_source

protocol
protocol_version
decode_state
session_hash

correlation_level
correlation_score
correlation_reasons
label_quality

capture_start_ns
capture_end_ns
clock_source
clock_uncertainty_ns
pps_locked
reference_10mhz_locked

calibration_id
rssi_quality

location_method
location_accuracy_m
participating_sensor_ids
```

Avoid storing the same meaning under several ambiguous fields.

---

# 19. AERIX server fusion behavior

Do not create a new independent map track for every 1-second RF frame.

Add/prepare an RF event-to-track fusion layer.

Potential association keys:

1. decoded serial — strongest
2. O4 session/hash — strong within session
3. ODID identity correlation
4. frequency/hopping fingerprint + time
5. spatial/RSSI consistency
6. classifier signature

Recommended track state:

```text
rf_track_id
first_seen
last_seen
protocol/vendor
identity/session hash
best location + provenance
participating sensors
confidence
last RF frequencies
```

Do not merge two nearby unknown emitters solely because they have similar RSSI.

---

# 20. Health / fleet management

ANTSDR must appear as a proper AERIX sensor in fleet management.

Heartbeat should report dynamic capabilities, not `hackrf-1`.

Example:

```json
{
  "receiver_type": "antsdr_e200_ad9361",
  "receiver_serial": "...",
  "capabilities": [
    "rf_iq",
    "dji_o2_decode",
    "dji_o3_decode",
    "dji_o4_detect",
    "pps_sync"
  ],
  "firmware_version": "...",
  "clock_locked": false,
  "temperature_c": null,
  "last_rf_event_at": "..."
}
```

Health states should distinguish:

```text
host service healthy
receiver connected
RF stream healthy
DJI decoder source healthy
server uplink healthy
clock sync healthy
```

---

# 21. Suggested implementation order

Claude should work in this order unless a concrete dependency requires adjustment.

## Milestone 0 — audit / cleanup

- [ ] Run current full test suite and record baseline.
- [ ] Fix stale decoder docstrings that still say Turbo decode is not implemented.
- [ ] Update README wording that says only OcuSync <=2 is decodable if public ANTSDR support is now broader for O2/O3.
- [ ] Do not change behavior unnecessarily in this milestone.

## Milestone 1 — correctness of current live system

- [ ] Wire `classify_spectrogram()` into live runtime.
- [ ] Preserve rule fallback.
- [ ] Emit classifier source/confidence.
- [ ] Separate signal detection confidence from classifier confidence.
- [ ] Add tests proving live inference uses installed model.

## Milestone 2 — safe correlation / labels

- [ ] Replace ambiguous `verified` semantics with correlation/label quality.
- [ ] Implement time-window checks using cue timestamp.
- [ ] Add site/sensor scope checks.
- [ ] Preserve weak labels separately.
- [ ] Update schema, ingest writer, DB migration and tests.

## Milestone 3 — receiver abstraction

- [ ] Create receiver capability/type abstraction.
- [ ] Remove hardcoded `hackrf-1` heartbeat.
- [ ] Preserve HackRF functionality.
- [ ] Add ANTSDR configuration namespace.

## Milestone 4 — ANTSDR DJI event integration

- [ ] Inspect current `alphafox02/antsdr_dji_droneid` message format.
- [ ] Add replay fixtures.
- [ ] Implement `AntSdrDjiEventSource`.
- [ ] Map O2/O3 fields.
- [ ] Map O4 hash/frequency/RSSI without fake serial/location.
- [ ] Add reconnect/dedup/health behavior.
- [ ] Feed normalized events into RF server path.

## Milestone 5 — contract / server normalization

- [ ] Extend `decoded`/RF contract for protocol version, decode state, O4 hash.
- [ ] Add receiver metadata.
- [ ] Add location provenance.
- [ ] Add migrations with backward-compatible reads where required.

## Milestone 6 — real decoder validation

- [ ] Validate Python O2/O3 decode against real IQ.
- [ ] Compare with public reference decoder.
- [ ] Fix CFO / 8-symbol support if real captures require it.
- [ ] Add regression fixture or documented private fixture process.

## Milestone 7 — ANTSDR raw IQ

- [ ] Implement libiio/UHD source.
- [ ] Add gain/bandwidth/channel config.
- [ ] Handle overflow.
- [ ] Preserve source sample metadata.
- [ ] Add ANTSDR replay format tests.

## Milestone 8 — RF detector taxonomy

- [ ] Make stage 1 morphology-only.
- [ ] Add open-set/unknown behavior.
- [ ] Keep stage 2 UAS classification separate.
- [ ] Add hard-negative Wi-Fi/BT tests.

## Milestone 9 — timing/calibration

- [ ] Add hardware/host timestamp distinction.
- [ ] Add PPS/10 MHz status fields.
- [ ] Add calibration metadata.
- [ ] Do not implement fake TDOA from millisecond timestamps.

## Milestone 10 — dataset expansion

- [ ] Deployment-rate DroneRF model.
- [ ] DroneDetect loader validation.
- [ ] RFUAV loader/evaluation.
- [ ] hard-negative AERIX capture set.
- [ ] site/session/hardware holdout evaluation.

## Milestone 11 — RF track fusion

- [ ] Aggregate per-frame events.
- [ ] O4 hash/session association.
- [ ] Remote ID correlation with provenance.
- [ ] confidence decay / track expiry.

## Milestone 12 — localization research

- [ ] synchronized IQ capture format.
- [ ] PPS timing characterization.
- [ ] cross-correlation prototype.
- [ ] simulated TDOA solve.
- [ ] known-transmitter field trial.
- [ ] uncertainty output.

---

# 22. Definition of done for the ANTSDR phase

The first ANTSDR production milestone is complete when all of the following are true:

1. HackRF regression path still passes.
2. ANTSDR E200 can be configured as an AERIX RF receiver without pretending to be HackRF.
3. AERIX receives public ANTSDR DJI events continuously and reconnects after failure.
4. O2/O3 fields are normalized correctly.
5. O4 produces a valid detection with session/hash + RF data and **no fabricated location**.
6. The live ML model actually runs when installed.
7. Stage-1 signal score and stage-2 classifier confidence are distinct.
8. ODID coincidence alone cannot create ground-truth RF training data.
9. Receiver/firmware/capability health is visible in heartbeat/fleet management.
10. Local cue endpoints are authenticated in production mode.
11. Contract/database migrations are covered by tests.
12. README describes actual current capabilities and limitations.
13. Full test suite is green.
14. At least one real ANTSDR hardware integration test has been documented.

---

# 23. Test strategy

Every milestone must add tests before being considered finished.

Required categories:

## Unit

- signal morphology
- classifier fallback
- model live path
- correlation scoring
- ANTSDR parser
- O4 mapping
- DJI frame parser
- timing metadata validation

## Fixture/replay

- HackRF `.cs8`
- ANTSDR O2/O3 event
- ANTSDR O4 event
- malformed ANTSDR input
- duplicated ANTSDR input
- model mismatch

## Integration

```text
source -> local processing -> envelope -> ingest validation
```

for:

- sim
- file replay
- HackRF where hardware CI is available
- ANTSDR replay

## Field/manual

Document commands and expected results for:

- known DJI O2/O3 drone
- known DJI O4 drone
- drone OFF / Wi-Fi-heavy environment
- receiver disconnect/reconnect
- server uplink loss/recovery

---

# 24. Performance / resource constraints

Do not optimize blindly, but measure:

```text
CPU %
RAM
IQ buffer growth
processing latency
lost/overflow samples
events/s
uplink bytes/s
```

For each receiver mode.

Targets should favor reliable capture/detection over PNG generation.

Spectrogram PNGs are evidence/UI products, not the primary signal-processing format.

Do not continuously upload raw IQ.

Retain/upload IQ only according to configured evidence/training policies.

---

# 25. Documentation requirements

Keep these documents aligned with actual implementation:

- `aerix-rf/README.md`
- this project scope
- `aerix_rf/classify/train/README.md`
- contract schema comments
- migration comments

Document:

- supported receivers
- ANTSDR firmware assumptions
- O2/O3/O4 capability matrix
- installation
- network ports
- security settings
- model activation
- field capture
- calibration
- known limitations

Never document synthetic validation as real-hardware validation.

---

# 26. External references to use

Claude should inspect current upstream code before implementing adapters; do not code from assumptions in this document if upstream changed.

### ANTSDR DJI

- https://github.com/alphafox02/antsdr_dji_droneid
- https://github.com/alphafox02/DroneID
- https://github.com/alphafox02/DragonSync

### DJI DroneID decoding

- https://github.com/RUB-SysSec/DroneSecurity
- https://github.com/proto17/dji_droneid
- https://github.com/anarkiwi/samples2djidroneid

### RF classification

- https://github.com/IQTLabs/RFClassification
- https://github.com/IQTLabs/gamutRF
- https://github.com/kitoweeknd/RFUAV

### ANTSDR hardware/API

- https://antsdr-docs.microphase.cn/en/latest/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.html
- https://antsdr-docs.microphase.cn/en/latest/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.html

---

# 27. Working rules for Claude

1. **Read the existing implementation before replacing anything.** There is already meaningful work here.
2. **Do not delete HackRF support.** ANTSDR is additive and becomes primary.
3. **Do not merge RF detections into ODID observations.**
4. **Do not label temporal coincidence as ground truth.**
5. **Do not fabricate O4 location.** Null + provenance is better than false precision.
6. **Do not require licensed DragonScope for core AERIX functionality.**
7. **Do not claim TDOA until real synchronized timing has been measured.**
8. **Do not treat RSSI across devices as calibrated without calibration metadata.**
9. **Do not train/evaluate using leaked windows from the same recording on both sides of a split.**
10. **Keep uncertainty explicit.** `unknown` is a valid result.
11. **Every changed server contract requires tests and migration consideration.**
12. **Every hardware parser must have replay fixtures.**
13. **Update README/status after each completed milestone.**
14. **Prefer small, reviewable commits by milestone.**
15. **Before declaring a phase done, run dependency/syntax, security/input, and execution-simulation checks in addition to unit tests.**

---

# 28. First task to execute now

Start with Milestones 0–2 only.

Do not jump directly into raw ANTSDR IQ support.

### First implementation batch

1. Run baseline tests and record exact count/results.
2. Fix stale decoder documentation.
3. Wire the actual trained classifier into `main.py`.
4. Split signal detection score from classifier result/confidence.
5. Add live-inference regression tests.
6. Design and implement safe correlation/label-quality semantics.
7. Extend schema/database/uplink only as required for that correlation change.
8. Keep backward compatibility where practical.
9. Run full tests.
10. Commit.

Then proceed to receiver abstraction and ANTSDR DJI event integration.

---

# 29. Expected end-state architecture

```text
                           AERIX RF NODE

   ┌─────────────────────────────────────────────────────────┐
   │                                                         │
   │  HackRF              ANTSDR E200                        │
   │    │                ┌───────────────┐                   │
   │    │ IQ             │ DJI FPGA/ARM  │                   │
   │    │                │ event output  │                   │
   │    │                └──────┬────────┘                   │
   │    │                       │                            │
   │    │                O2/O3 decoded                       │
   │    │                O4 hash/RSSI/freq                   │
   │    │                       │                            │
   │    ▼                       ▼                            │
   │ Raw IQ source       Protocol event source               │
   │    │                       │                            │
   │    ▼                       │                            │
   │ Spectrogram                │                            │
   │    │                       │                            │
   │ Signal detector            │                            │
   │    │                       │                            │
   │ ML classifier              │                            │
   │    │                       │                            │
   │ Optional decoder           │                            │
   │    └──────────────┬────────┘                            │
   │                   ▼                                     │
   │             NORMALIZED RF EVENT                         │
   │                   │                                     │
   │         ┌─────────┴───────────┐                         │
   │         │                     │                         │
   │     ODID/RID cues       local RF correlation            │
   │         │                     │                         │
   │         └─────────┬───────────┘                         │
   │                   ▼                                     │
   │             RF EVENT / TRACK                            │
   │                   │                                     │
   │          IQ/evidence retention                          │
   └───────────────────┼─────────────────────────────────────┘
                       │
                       ▼
                   AERIX SERVER
                       │
          identity / location / RF fusion
                       │
      ┌────────────────┼─────────────────┐
      │                │                 │
  decoded RF      Remote ID         future TDOA
   location       correlation      synchronized RF
```

The core principle is:

> **Protocol decode, RF classification, Remote ID correlation, and RF localization are independent evidence sources that converge into one AERIX track. None is allowed to masquerade as another.**
