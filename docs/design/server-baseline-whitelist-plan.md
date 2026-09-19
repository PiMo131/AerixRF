# Server-side baseline, whitelist and ODID-labelled learning — mini-plan (draft for the architect gate)

Status: draft for review, 2026-09-19. Scope requested by the user after the Tsukorok firmware analysis
(`research/briefs/tsukorok-firmware-5.5.12-rf-extraction.md`): points 1 (per-sensor baseline and
differencing), 2 (stationarity and schedule filters), 3 (data-built word/channel whitelists) and 8 (Open Drone
ID receptions as free labels), plus three user constraints:

* the baseline is built in **quiet windows** — periods known to be drone-free — or continuously with such
  windows marked, not only as a noise level but as an **inventory of what is transmitting**, obtained by
  **decoding the frames** that are there;
* the inventory runs **for a long time** (weeks to months) and keeps running;
* every sensor has a **tunable RSSI gate** below which a candidate is not even examined or decoded, so the
  detector does not "look too far".

Everything below is receive-only and fits the existing paths: Path 2 detections and Path 1 ODID-verified
snapshots (`README.md`, `aerix_rf/uplink/client.py`), the session store (`aerix_rf/session/store.py`) and the
stage-1/2/3 separation (`aerix_rf/detect`, `classify`, `decode`).

## 1. Vocabulary

| Term | Meaning here |
|---|---|
| **Emitter record** | One observed transmitter feature at one sensor: band, centre frequency, bandwidth or bitrate, stage-1 morphology, a protocol identification when a frame decoded, and a *fingerprint* (see below). |
| **Fingerprint** | A stable, non-personal key for "the same emitter again": protocol + channel + a hashed frame-header identifier (e.g. the hashed M‑Bus/Z‑Wave address, the hashed Wi‑Fi BSSID, the 32-bit post-preamble word for unknown FSK). Raw identifiers never leave the sensor unhashed. |
| **Quiet window** | A time interval at one sensor during which no drone is present, established by rule (§3.2). Baselines are only *updated* inside quiet windows. |
| **Baseline** | Per sensor, per band: (a) occupancy statistics per channel and hour-of-day, (b) the emitter inventory with presence statistics. |
| **Whitelist** | The subset of the inventory classified as infrastructure (stationary, scheduled, or positively identified as a non-UAS protocol). Learned, expiring, never hand-edited except to *remove* an entry. |
| **RSSI gate** | Per sensor, per band: the level below which stage-1 candidates are recorded as occupancy only and are neither decoded nor forwarded as candidates. |

## 2. Data model (server)

Records are small (hundreds of bytes); the volume driver is the number of emitter observations, not IQ.
No IQ leaves the sensor except Path 1 snapshots as today.

```
sensor            id, site, lat/lon, antenna, receiver_type, rssi_calibration (per band offset dB, may be null)
sensor_gate       sensor_id, band, rssi_gate_dbm, set_by (auto|operator), valid_from
occupancy_bin     sensor_id, band, channel_hz (100 kHz bins sub-GHz, 1 MHz 2.4/5.8), hour_of_day, dow,
                  n_windows, p_busy, rssi_p50, rssi_p95, updated_at          # only updated in quiet windows
emitter_obs       sensor_id, t, band, f_center_hz, bw_hz|bitrate_bps, morphology, protocol (nullable),
                  fingerprint (hash, nullable), rssi_dbm, snr_db, n_bursts, decode_level (none|header|full),
                  in_quiet_window (bool)
emitter           fingerprint, first_seen, last_seen, n_obs, n_sensors, sensors[], presence_profile
                  (24x7 histogram), period_s (if scheduled), rssi_stability (std over days), class
                  (infrastructure|transient|unknown|uas_confirmed), whitelist_until (nullable)
quiet_window      sensor_id, t_start, t_end, source (rule|operator|odid_absence), version
odid_cue          (exists) serial-hashed, sensor_id, t_start, t_end, lat/lon   # Path 1
label             emitter_obs_id -> {positive_odid, negative_quiet, unlabelled}, derived nightly
```

Retention follows the existing policy (30 d default, 180 d verified); `emitter` rows are aggregates
without timestamps of individual observations beyond first/last seen, so they can live longer (proposal: 1 y).

## 3. Baseline construction

### 3.1 What the sensor sends

Every window, in addition to today's Path 2 frame:

1. Occupancy vector per channel above the receiver noise floor (not above the gate): the gate limits what we
   *decode*, not what we *count*. Costs ~1–2 kB per window sub-GHz.
2. One `emitter_obs` per stage-1 cluster **above the RSSI gate**, with the best available identification:
   * sub-GHz FSK: bitrate class, post-preamble 32-bit word (hashed fingerprint = sha256(protocol|channel|word)),
     and if a known header parses (§3.3) the protocol name and hashed address;
   * LoRa: SF/BW class from CAD or from a demodulated header, LoRaWAN DevAddr hashed when the MHDR parses;
   * 2.4/5.8 GHz: morphology, occupied bandwidth, cadence, and for Wi‑Fi the hashed BSSID and channel when a
     beacon is decodable from the same IQ (the E200 can do this from the capture; an ESP32 side-sniffer is an
     alternative);
   * DJI: stage-3 result as today.

### 3.2 Quiet-window rules (all must hold for a window to count as quiet at that sensor)

* No Path 1 ODID cue within ±T_guard (proposal 10 min) at this sensor or any sensor within R (proposal 2 km).
* No stage-2 label of `dji_ocusync`, `wifi_drone`, `fpv_analog` with confidence above c_q (proposal 0.5) at
  this sensor within ±T_guard.
* No `uas_confirmed` emitter observed within ±T_guard.
* Operator override: a site can be declared quiet (e.g. night hours at an industrial site) or never-quiet
  (airfield). Overrides are versioned.

Why not "no candidates at all": in a city there are always stage-1 candidates; the baseline must include them,
otherwise it never learns the Wi‑Fi and the meters. Quiet means "no drone evidence", not "no signals".

Baseline updates happen only for windows inside quiet windows. Observations outside quiet windows are stored
with `in_quiet_window = false` and still feed the inventory (so a drone that flies daily is *seen* in the
inventory) but never the whitelist.

### 3.3 Continuous frame inventory ("what is there")

The point of decoding in the baseline is to turn "an FSK thing at 868.3 MHz" into "an M‑Bus meter, address
hash X, every 900 s". Decoders to add, all receive-only and all open standards, in priority order of
false-alarm relevance from the Tsukorok analysis:

1. Wireless M‑Bus (EN 13757‑4) modes S/T/C at 868.3/868.95/869.525 MHz — meters are the densest sub-GHz
   population in EU cities.
2. Z‑Wave (ITU‑T G.9959) at 868.42 MHz, 9.6/40/100 kbps — 40 kbps sits next to the 38.15 kbps "Orlan" class.
3. Generic SRD FSK headers at 38.4/57.6 kbps (CC1101/Si44xx defaults): no standard frame, so the fingerprint is
   the post-preamble word + channel; classification is by stationarity only.
4. LoRaWAN MHDR/DevAddr at 868.1/868.3/868.5 (and 867.x) MHz, 125 kHz; Meshtastic at 869.525 MHz.
5. Wi‑Fi beacons (BSSID, channel, width) for 2.4/5.8 GHz.
6. Optional later: UHF RFID interrogator signatures (865–868 MHz), GSM/LTE uplink identification by burst
   structure (577 µs / 4.6 ms) — identify, never decode.

Each decoder produces `protocol`, hashed address, and channel; nothing from payloads is stored.
Implementation home: `aerix_rf/decode/inventory/` (new), sharing the FSK demodulator with the sub-GHz
candidate module proposed in the Tsukorok brief §8.

### 3.4 RSSI gate per sensor

* Definition: `rssi_gate_dbm[sensor, band]`. Candidates below it: counted in occupancy, not decoded, not
  forwarded. Candidates above it: decoded/fingerprinted and forwarded as `emitter_obs`.
* Auto proposal from the baseline: gate = the level at which the quiet-window candidate rate falls below
  N_q per hour (proposal N_q = 20) for that band, floored at noise+10 dB and capped at −60 dBm. Recomputed
  weekly; applied only after operator confirmation the first time, automatically afterwards if the change is
  < 3 dB.
* Operator tuning through the server (`sensor_gate` row); the sensor polls it with the existing heartbeat.
* The gate is a *range* control, not a *sensitivity* control: it deliberately trades far, weak drones for a
  workable candidate rate. Sensor density, not gate depth, is how coverage is restored.
* RSSI is uncalibrated today (README caveat); gates are therefore per sensor and per receiver, and a
  calibration offset field exists so they can be expressed in dBm once a reference measurement is done.

## 4. Stationarity and schedule classification (nightly job, per emitter)

Inputs: the emitter's presence profile (24×7 histogram of observation counts), inter-observation intervals,
RSSI series per sensor, number of sensors seeing it.

Rules (INFERRED design, thresholds to be tuned on the first month of data):

* `infrastructure` if seen on ≥ D_inf distinct days (proposal 7) with RSSI std ≤ 3 dB at every sensor that sees
  it, OR a period test on the inter-observation intervals passes (Rayleigh/periodogram as in
  `aerix_rf/detect/raster.py`) with a period in the SRD schedule set (meter/alarm/beacon intervals), OR the
  protocol is a positively identified non-UAS standard (§3.3 items 1, 2, 4, 5).
* `transient` if seen in ≤ 2 sessions of ≤ 60 min each, RSSI varying monotonically ≥ 6 dB within a session,
  or seen by ≥ 2 sensors with a moving RSSI ordering.
* `uas_confirmed` if any observation falls inside a Path 1 ODID cue window and matches the cue's band (§6).
* Otherwise `unknown`.

Whitelist = infrastructure entries with `whitelist_until = last_seen + 30 d`. Entries expire; an emitter that
stops for 30 days must re-earn its place. Operators can *remove* an entry (with reason); they cannot add one
without an observation.

Filter effect: a stage-1 candidate whose fingerprint or (protocol, channel) is whitelisted at that sensor is
demoted to occupancy; a candidate without fingerprint on a channel whose baseline p_busy at that hour is above
p_wl (proposal 0.8) is demoted unless its bandwidth/morphology differs from the baseline population of that
channel. Demoted candidates are still stored (in_quiet_window flag) — nothing is dropped, only not alerted.

## 5. Differencing (what escalates)

An observation escalates to the analyst queue / alert path when at least one holds:

* fingerprint not in the whitelist AND channel occupancy above baseline p95 for that hour;
* a whitelisted emitter appears at a sensor where it has never been seen, or with RSSI ≥ 10 dB above its
  baseline (a moved or new device — still infrastructure, but worth one look);
* cross-band pairing: an unwhitelisted sub-GHz/2.4 GHz link and a 2.4/5.8 GHz wideband candidate within
  ±60 s at the same sensor;
* multi-sensor: the same fingerprint at ≥ 2 sensors within 5 min with non-static RSSI ordering;
* any stage-3 decode (unchanged).

Alert levels follow the project evidence levels: automatic alert only at level 3 and above (decoded ID, or a
static-word match plus corroboration); levels 1–2 go to the heat map.

## 6. ODID-labelled learning (point 8)

* Positive set: every `emitter_obs` inside a Path 1 cue window at that sensor whose band matches the cue's
  aircraft class (the cue carries the ODID serial → manufacturer/model → expected link bands). One cue window
  labels *all* co-temporal candidates positive only after the corroboration check in §5; single-sensor
  coincidences without corroboration are labelled `positive_weak`.
* Negative set: every observation inside a quiet window at a sensor with `infrastructure` or `unknown` class.
* Held-out sites: at least two sensors are never used for training, only for evaluation, to detect
  site-memorisation.
* Consumers: stage-2 `classify/train` (replacing the synthetic-only bundle caveat in the README), the
  whitelist rules' thresholds (§4), and the FA-budget bench (`docs/design/stage1-fa-budget-2026-09-19.md`)
  which gets real negatives.
* Reporting: monthly per-site precision/recall against ODID truth, with the caveat that ODID-equipped aircraft
  are a biased sample (compliant consumer drones); the report must say so.

## 7. Privacy and policy

* Identifiers (BSSID, meter/Z‑Wave addresses, LoRaWAN DevAddr, ODID serial) are hashed with a per-deployment
  salt before storage; the salt lives only on the server.
* The inventory attributes *devices*, never people; no payload bytes are stored; frames are decoded only to
  the header fields needed for the fingerprint.
* Retention: `emitter_obs` per the existing detection policy; `emitter` aggregates 1 y; operator overrides and
  gate changes are audit-logged.
* Receive-only throughout; the Tsukorok's TX-strobe behaviour is a reason not to use that device as a sensor.

## 8. Phasing

| Phase | Deliverable | Depends on |
|---|---|---|
| P0 (2 weeks) | Schema + occupancy vector + `emitter_obs` without decoders (fingerprint = morphology+channel+word); quiet-window rules from ODID cues; RSSI gate plumbing via heartbeat | existing Path 1/2 |
| P1 (3 weeks) | Sub-GHz FSK demodulator + post-preamble word extraction on the E200 (shared with the Tsukorok-derived candidate module); M‑Bus and Z‑Wave header decoders; Wi‑Fi beacon BSSID from 2.4 GHz IQ | P0 |
| P2 (2 weeks) | Nightly emitter classification, whitelist lifecycle, differencing rules, analyst queue view | P0, one month of data |
| P3 (2 weeks) | ODID-labelled training set, held-out evaluation, monthly report | P1, P2 |
| P4 | LoRaWAN/Meshtastic headers, RFID/GSM identification, auto-gate proposals | P2 |

## 9. Questions for the user (decision packet)

1. Quiet-window definition: is "no ODID cue within 10 min / 2 km and no stage-2 drone label > 0.5" acceptable,
   or do you want operator-declared quiet hours per site as the primary source?
2. RSSI gate policy: auto-proposed weekly with operator confirmation, or operator-only? What starting value per
   band (proposal −85 dBm sub-GHz, −80 dBm 2.4/5.8 GHz, before calibration)?
3. Which non-UAS protocols must be positively identified in phase 1: M‑Bus and Z‑Wave (proposed), or also
   LoRaWAN and Wi‑Fi beacons immediately?
4. Fingerprint hashing: per-deployment salt (proposed) or per-site salt (stronger privacy, no cross-site
   matching of the same infrastructure)?
5. Whitelist expiry 30 days and infrastructure threshold 7 distinct days: acceptable starting values?
6. Alert threshold: confirm "automatic alert only at evidence level ≥ 3"; levels 1–2 to a heat map only.
7. Multi-sensor corroboration radius (proposal 2 km) and time window (5 min): do sensor spacings support that?
8. Held-out sites for evaluation: can two sensors be reserved?
9. Should the inventory also count GSM/LTE uplink activity (identify only) to explain sub-GHz candidate bursts,
   or is that out of scope for privacy reasons?
10. Server compute: nightly batch is enough for classification; do you want the differencing rules (§5) to run
    server-side in near-real-time (seconds) or on the sensor with a pushed whitelist?
11. Does the existing server schema allow a new `emitter_obs` route beside the RF detection route, or must it
    ride inside the Path 2 frame?
12. Retention for `emitter` aggregates (proposal 1 year): acceptable under the current data policy?
