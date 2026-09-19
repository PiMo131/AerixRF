# aerix-rf — RF/SDR drone detection for AERIX

Adds **RF-based** drone detection to AERIX for the drones the ESP receivers can't see:
legacy DJI / OcuSync and other brands with no broadcast Remote ID. Runs on a Linux box
driving a passive SDR receiver. **Primary receiver (since 2026-09-18): ANTSDR E200**
(AD9361, Zynq-7020, Gigabit Ethernet). **Secondary/reference receiver: HackRF / HackRF Pro** —
the first field-tested platform, still fully supported. Both only stream IQ today, so all
DSP, detection and decoding run on the host behind a hardware-neutral `IQSource`.

## Hardware

| Receiver | Role | Host path | Live rate | Notes |
|---|---|---|---|---|
| ANTSDR E200 | primary | libiio over `ip:` (stock PlutoSDR-compatible IIO image) | 11.52 MS/s profile (clean); 15.36 marginal | 1 RX exposed, 12-bit-in-int16 (`iq_full_scale` 2048), **measured iiod ceiling ≈ 14.8 MS/s**, no overflow counter, no device timestamps. Facts, evidence grades and firmware options: `research/briefs/antsdr-e200.md` |
| HackRF / Pro | secondary, regression baseline | libhackrf / hackrf_transfer / Soapy | 20 MS/s (legacy), 15.36 profile | 8-bit `cs8`; `scan`/`baseline` use `hackrf_sweep` until the backend-neutral sweeper lands |

Design documents: `docs/design/antsdr-backend.md` (backend, capability model, session schema v2,
builder tasks T1–T6) and `docs/design/canonical-representation.md` (canonical 15.36 MS/s /
1 s / FFT-1024 representation shared by live detection and ML preprocessing).

Datasets live outside git under `$AERIX_RF_DATASET_ROOT` (default `~/rf-datasets`); see
`research/datasets/README.md`, the manifest there, `research/datasets/USER_TODO.md` for
gated sources, and `research/briefs/rf-datasets.md` for what each dataset is good for.

RF detection is a **separate server path** from the ODID `observations` pipeline: an RF
detection is an energy/spectral measurement of one second of spectrum that may carry no
decodable Remote ID at all. It is posted to `/v1/rf-detections:batch` and stored in the
`rf_detections` table — the append-only, ODID-only observation layer is never touched.

---

## The detection chain

`capture → spectrogram → stage-1 energy detect → stage-2 classify → {Path 2 stream, Path 1 snapshot}`

- **Stage 1 — energy/spectral** (`detect/energy.py`): unsupervised. Burst cadence (~600 ms
  OcuSync), ~10 MHz OFDM bandwidth, FHSS signature → `detection_probability`. Keys on signal
  *shape*, so it catches even encrypted O4 and analog FPV. Needs no training.
- **Stage 2 — classify** (`classify/model.py`, `classify/train/`): `signature_class`. Rule-based
  today; a scikit-learn model trained on real datasets drops in behind the same interface. The
  `--human`/log status line's `cls=` field can read `uas_link`: a probabilistic (evidence level 2)
  "this is some UAS RF link" call with unknown family/manufacturer, never an identity claim.
- **Stage 3 — DJI DroneID decode** (`decode/`): best-effort serial + drone/operator GPS for
  OcuSync ≤ 2.0. Full chain: ZC sync, resample, CFO, OFDM demod, equalize, QPSK, LTE descramble,
  de-rate-match, LTE Turbo decode (max-log-MAP), CRC24A gate, DJI frame parse. Synthetic-verified
  (exact serial + GPS round-trip down to 5 dB SNR) and **hardware-validated on a DJI Mini 3**
  (CRC-valid bursts at 2429.5 MHz, on the ground; see Status).

**Two server paths, both producing an RF image (spectrogram):**
- **Path 2** — the box's own detector fired → per-second frame `{location, probability, RSSI,
  band/freq, spectrogram}`.
- **Path 1** — an ODID cue coincided (certain drone) → a **verified** snapshot = ground-truth
  training label. Triggered by **1a** polling the server (`GET /v1/rf/odid-cues`) or **1b** a
  local cue POSTed to this box's LAN API (offline-resilient, lower latency).

**Finding a transmitting drone** (`tools/sweep_locate.py`): one 20 MHz HackRF window can't cover
the ~83 MHz of 2.4 GHz plus 5.8 GHz OcuSync roams, so a `hackrf_sweep` baseline is differenced
against a live sweep — the drone's channel is the region that got newly hot.

---

## Sources

Ported, adapted, or referenced:

| What | Source | Use |
|---|---|---|
| DJI DroneID OFDM decode | [proto17/dji_droneid](https://github.com/proto17/dji_droneid) | Stage-3 front end ported verbatim (FFT 1024, CP 80/72, ZC roots 600/147, LTE scrambler); Turbo decode is their C++ `remove_turbo` |
| DroneID from IQ (cross-check) | [anarkiwi/samples2djidroneid](https://github.com/anarkiwi/samples2djidroneid) | Parameter cross-verification |
| HackRF OcuSync correlation | [Olafseisler/dji-drone-detector](https://github.com/Olafseisler/dji-drone-detector) | Real-time energy/correlation detection idea |
| RF classification pipeline | [IQTLabs/RFClassification](https://github.com/IQTLabs/RFClassification) | Feature (PSD / spectrogram) + model scaffolding approach |
| "DJI DroneID is not encrypted" | [arXiv:2207.10795](https://arxiv.org/abs/2207.10795) | Frame layout / field semantics |
| SDR host stack | [Great Scott Gadgets HackRF](https://greatscottgadgets.com/hackrf/) (`hackrf`, `libhackrf`, SoapySDR) | Capture on real hardware |

**Public training datasets** (loaders in `classify/train/data.py`):
- **DroneRF** — Mendeley, open: https://data.mendeley.com/datasets/f4c2b4n755/1 (real drone + background RF)
- **DroneDetect** — IEEE DataPort (free account): raw IQ, 7 UAS, 3 modes
- **DroneRFb-Spectra** — IEEE DataPort: 512×512 spectrograms, 7 brands
- **RFUAV** — https://github.com/kitoweeknd/RFUAV : 35-drone raw-IQ benchmark

---

## Dependencies

**Python** (managed with `uv`; see `pyproject.toml`): numpy, scipy, pillow, httpx, pydantic,
fastapi, uvicorn, zeroconf.
- `train` extra: scikit-learn, joblib (classifier training).
- `train-cnn` extra: torch (documented, CNN slot not yet implemented).
- `pyusb` (ad-hoc, via `uv run --with pyusb`): lets the box talk to the HackRF with **no root
  install** — used to prove control before `hackrf` was installed.

**System — one of these for live capture** (else run `--sim`):
- `hackrf` package → `hackrf_transfer` (capture) + `hackrf_sweep` (locator) + `libhackrf`. This
  is the path the box uses today (`sdr/capture.HackrfTransferSource`). Also ships udev rules.
- or `soapysdr-module-hackrf` + `python3-soapysdr` for gap-free streaming
  (`sdr/capture.HackRFSource`); note the uv venv must be built `--system-site-packages` to see it.

---

## Design considerations

Decisions we made and why:

1. **RF detections are a separate path, not observations.** An AERIX observation is defined as
   *one reception of an Open Drone ID transmission* (`odid_raw` mandatory). A decode-less RF
   energy hit is not that. Forcing it into `observations` would dilute that append-only,
   ODID-only invariant across the whole system — so RF gets its own contract, table, and route.

2. **Detection runs on the box, not the HackRF.** The HackRF has no onboard DSP. A future
   **AntSDR** (FPGA) swap can fold decode into one box; the server contract is designed so that
   swap changes nothing server-side.

3. **Energy/spectral detection first.** It's unsupervised and shape-based, so it works with zero
   training data and catches encrypted O4 and analog FPV. Classification and decode layer on top.

4. **Two paths for a reason.** Path 1 (ODID-verified snapshots) turns the ESP's certain-drone
   detections into *labelled* RF training data — the engine that grows a real dataset over time.
   The local cue API (Path 1b) keeps that working with low latency even if the uplink is down.

5. **GDPR / retention is stamped at ingest.** `rf_detections` rows carry a tiered `expires_at`
   (30 d default, 180 d verified, **7 d when a decoded operator location is present** — personal
   data), swept by the worker under the same guarded-delete trigger as observations. The local
   raw-IQ buffer auto-purges at ≥24 h. Nothing is retained indefinitely without evidence
   promotion. Storage duration, not the act of decoding, is the audit-relevant control.

6. **Real-time on 20 Msps.** The STFT uses `scipy.fft` (multithreaded pocketfft) and caps the
   frame count (time-decimation) so compute+detect runs in ~120 ms/window — the detector's
   features (envelope, cadence, occupied bandwidth, SNR) are coarse-time and lose nothing.

7. **Attribution requires a differential.** The energy detector fires on *any* strong wideband
   signal — including Wi-Fi. A live test mislabelled ambient 2440 MHz Wi-Fi as a drone; a
   drone-OFF differential capture disproved it. So: never claim a detection from a single
   capture; confirm with on/off (single-frame) or baseline differencing (sweep). This is why the
   classifier **must** train on real data — synthetic-trained models don't reject real Wi-Fi.

8. **One HackRF window ≠ the whole band.** OcuSync roams 2.4 + 5.8 GHz; a 20 MHz window misses
   it. The sweep locator averages many sweeps (in linear power — single-shot is too noisy) and
   differences against a baseline to point the box at the right channel.

9. **Decode scope is honest.** OcuSync 2 DroneID is decodable (proven on real IQ); OcuSync 3/3+ is
   expected decodable per the research corpus but untested by us; O4 encrypts the payload (any "session
   hash" claim is unverified). See `research/briefs/dji-generations-and-o3o4-identification.md`. The front end is verified against *synthetic* bursts, not yet a real
   capture — flagged in `decode/droneid.py`.

---

## Run

```sh
uv sync

# No hardware -- synthetic IQ, one JSON status line per second:
uv run aerix-rf run --sim

# Real HackRF (libhackrf, continuous stream). Bare `aerix-rf` == `aerix-rf run`.
uv run aerix-rf info
uv run aerix-rf run --human

# With server uplink + sensor position:
AERIX_RF_SERVER_URL=https://host:8180 AERIX_RF_SENSOR_ID=sdr-... AERIX_RF_TOKEN='sdr-...~secret' \
AERIX_RF_LAT=52.1 AERIX_RF_LON=5.1 uv run aerix-rf run
```

Provision a `hackrf` sensor once: `POST /v1/sensors:provision {"class":"hackrf"}`.

**ANTSDR E200 / AD9361 (`antsdr_iio` backend, continuous libiio network RX):**
```sh
uv sync --extra antsdr   # pulls python-iio (pylibiio); also needs the libiio runtime on the host

# On this dev host, libiio itself lives in a micromamba env, not the system linker path:
export LD_LIBRARY_PATH=/home/jarvis/aerix-rf/.antsdr-tools/mamba/envs/antsdr/lib
# Elsewhere: install the libiio system package instead (e.g. `apt install libiio-dev` /
# `libiio-utils`) and skip LD_LIBRARY_PATH.

export AERIX_RF_ANTSDR_URI=ip:192.168.1.10   # or --antsdr-uri; default if unset

uv run aerix-rf info --backend antsdr_iio    # confirm it's importable/reachable before a capture
uv run aerix-rf capture --backend antsdr_iio --center-mhz 2437 --seconds 20 \
    --antsdr-profile default --label "antsdr smoke test"
#   --antsdr-profile: default (12.288 MS/s, clean over GbE) | antsdr_13p44 (13.44 MS/s, still
#   sustained) | antsdr_11p52 (11.52 MS/s). Above ~13.44 MS/s is within the AD9361's own range
#   but not this link's measured sustained throughput -- --sample-rate above that ceiling is
#   applied (not rejected) but logs a warning, and the session's `capture_health` will show it.
#   --gain-mode manual|agc_slow|agc_fast and --gain-db (manual mode) replace HackRF's
#   --lna/--vga/--amp, which this backend does not accept.
```
Every session window's `capture_health` carries `loss_detection: "inferred_rate_only"` and
`stream_rate_ratio` for this backend (the libiio firmware gives no per-buffer drop counter, so
`dropped_samples` is always `None`, never a fabricated 0) -- `cap=RATE(x)` in a status/report
line means the window was recorded at a fraction `x` of the nominal sample rate (measured over
wall time since the stream started), the only signal this backend has for silent sample loss.

**Local cue (Path 1b):**
```sh
curl -XPOST http://aerix-rf.local:8770/cue -H "X-Local-Token: $TOKEN" \
  -d '{"serial":"1581F...","transport":"ble_legacy","rssi":-60}'
```

**Train the classifier** (see `aerix_rf/classify/train/README.md`):
```sh
uv run --extra train python -m aerix_rf.classify.train.train --dataset dronerf --data-root <path> \
  --sample-rate 20e6 --out models/signature.joblib
# then: AERIX_RF_MODEL=models/signature.joblib uv run aerix-rf run   (default path: models/signature.joblib)
```

---

## Field test (Phase 1: scan -> lock -> capture -> replay -> report)

Everything below works **without the server**. Sessions land in `./sessions/<UTC>_<label>/`
(override with `--session-root` or `$AERIX_RF_SESSIONS`); each is self-describing:
`session.json` (receiver, gains, sample rate, software git sha, sha256 of every IQ file,
operator test labels), `iq/capture_NNNN.cs8` (raw int8 IQ), `spectrograms/*.png`,
`detections.jsonl`, `decode.jsonl`, `summary.md`. **Do not commit `sessions/`** (it is
gitignored; a 60 s lock is 2.4 GB).

The `--label/--drone-*/--motors-state/...` flags are *operator ground truth about the test
set-up*. They are stored under `test` in `session.json` and shown in the report as such; they
never feed the detector/classifier and never attribute an individual emitter.

```sh
# Test 0 -- baseline, drones + controllers OFF (30 s per band, 5 min is better)
uv run aerix-rf baseline --band 2.4 --seconds 60 --out sessions/base_24
uv run aerix-rf baseline --band 5.8 --seconds 60 --out sessions/base_58
uv run aerix-rf capture --seconds 300 --label "test0 baseline 2440" --center-mhz 2440

# Test 1/2/3 -- power the controller / aircraft / motors, then find what changed:
uv run aerix-rf scan --band 2.4 --baseline sessions/base_24 --rounds 3
uv run aerix-rf scan --band 5.8 --baseline sessions/base_58 --rounds 3
#   -> ranked candidates (centre, span, rise over baseline, persistence, burstiness, hopping)

# Lock the top candidate and record everything the pipeline sees:
uv run aerix-rf lock --center-mhz 2437 --seconds 60 \
    --label "test3 droneA motors on" --drone-manufacturer DJI --drone-model "Mini 4 Pro" \
    --drone-state flying --controller-state on --motors-state on --distance-m 20 \
    --antenna "stock 2.4 whip" --notes "run 1 of 3"
#   `capture` is the same but keeps *every* window's IQ (lock keeps only plausible windows
#   unless --record-all). Ctrl-C stops early; the session is finalised either way.

# Afterwards, offline -- must reproduce the same detections/decodes from the stored IQ:
uv run aerix-rf replay sessions/<session>            # -> sessions/<session>/replays/<...>/
uv run aerix-rf report sessions/<session> --print    # regenerate summary.md
```

Band presets: `2.4` (2400-2500), `5.8` (5725-5875), `5.2` (5150-5350), `900`; or `lo:hi` in MHz.
Radio flags on `lock/capture`: `--sample-rate --lna --vga --amp --backend libhackrf|hackrf_transfer|soapy`.

Status line fields: `score` = how *interesting* the RF is (0..1, **not** "is a drone"),
`morph` = stage-1 shape, `cls` = stage-2 label with confidence and source (`rule` or the
model version), `dec` = best decode level this window (`none/A/B/C`; `C` = CRC-valid frame,
prints serial + position), `cap` = capture health (`ok` or `INCOMPLETE(-n)`; the cumulative
`overflow_count` is in `detections.jsonl`).

---

## Status

- **2026-09-19 (afternoon) — Stage-1 link-signature rules live; UHD-mode trial; non-DJI ranking.** Stage-1 now
  extracts burst events (−6 dB edge-midpoint centres) and applies raster/period/cadence tests with a controlled,
  vendor-free vocabulary (`fhss_1mhz_grid_candidate`, `hopping_candidate`, `droneid_cadence_candidate`, …, tags
  `wifi_beacon_like`/`ble_connection_like`); on 1,160 real ambient windows `hopping` fires 1.0 % (budget 5 %) and DroneID-cadence 0 after one rule
  correction; the grid rules were not exercised by ambient RF and await real hopper positives
  (`docs/design/stage1-fa-budget-2026-09-19-run2.md`). The E200 booted MicroPhase's UHD image from a
  second SD card: 2 RX channels, per-packet timestamps, reported overflows; 15.36 sc16 / 20 sc8 clean in short runs,
  one 10-min soak failed with default host socket buffers — decision pending (`research/briefs/antsdr-e200.md` §15).
  Non-DJI targets ranked with legal flags (`research/briefs/non-dji-targets.md`); OcuSync 3/3+ DroneID is expected
  decodable per primary sources (Avata test checklist in `docs/field/`).
- **2026-09-19 — producer-process backend accepted.** `--backend antsdr_proc` runs the libiio acquisition in its own
  OS process behind a shared-memory ring with exact host loss accounting. Two 600 s BIST-tone runs through the full
  pipeline (idle, and under a looping pytest load) show **0 phase discontinuities in 7.37 G samples each**, 0 host
  drops. This is now the recommended ANTSDR backend; the in-process `antsdr_iio` remains as reference. Details:
  `research/briefs/antsdr-e200.md` §14.2, design in `docs/design/antsdr-backend.md` §T7.
- **2026-09-18 (late) — silent loss measured.** AD9361 BIST tone through the production buffering, 600 s per run:
  12.288 and 13.44 MS/s gap-free (0 discontinuities in 7,031 / 7,690 buffers); 15.36 MS/s broken (ratio 0.50);
  in-process (GIL) contention catastrophic (ratio 0.41) while 12 separate busy processes cause zero loss — the
  fix is a producer process, not a quiet host. 13.44 is now a validated named profile; 12.288 stays default. Details: `research/briefs/antsdr-e200.md` §14.
- **2026-09-18 (evening) — soak and benchmark honesty.** Clean 10-minute ANTSDR soak on an idle host:
  600/600 windows, no loss (the earlier −5 % was CPU contention from concurrent test runs). Sessions now
  record device **read-back** state (`receiver_readback`, `readback_mismatch`) and typed loss fields.
  First cross-receiver benchmark ran and *falsified* a naive classifier: with anechoic public positives vs
  one room's Wi-Fi-saturated negatives it learned "quiet band = drone" (PFA≈1.0 on a quieter session);
  the receiver-ID probe's first PASS was a fold artefact and is withdrawn (now StratifiedGroupKFold with
  guards and an INCONCLUSIVE verdict). No PD or cross-receiver claim is supported yet — see
  `docs/design/features-and-benchmark.md` §5. Highest-value next data: a DJI aircraft captured by the E200
  with interleaved ON/OFF intervals in one session.
- **2026-09-18 (later) — ANTSDR path live-verified.** `aerix-rf capture --backend antsdr_iio` runs the
  full pipeline on the E200 at 12.288 MS/s cs16; 300 s captures with and without IQ writing delivered
  300/300 windows (no loss on an idle host); replay is bit-exact. An earlier −5 % over 10 min coincided
  with concurrent heavy CPU load on the same host — the libiio path has no overflow counter, so keep the
  field box free of unrelated load (see `docs/design/antsdr-backend.md`). `scan`/`baseline` now run on any
  backend (retune + Welch sweep; hardware check owed). New `features_v2` (302-D, device-confound-aware)
  and dataset adapters for Zenodo-2020, RUB-SysSec and our own sessions feed the first cross-receiver
  benchmark (`docs/design/features-and-benchmark.md`). Still owed for acceptance A4: a CRC-valid DJI
  DroneID decode captured **by the E200** (needs a compatible aircraft powered nearby). 289 tests green.
- **2026-09-18 — roadmap revision 2, ANTSDR primary.** E200 reachable and streaming
  (receive-only) from this host; hardware brief, backend design and canonical-representation
  memo written; session schema v2 (`iq_format`/`iq_full_scale`, cs16) and new `IQWindow`
  provenance fields landed backward-compatibly (schema-1 sessions replay unchanged). The DJI
  DroneID decoder was run on the independent RUB-SysSec DroneSecurity real-IQ captures and
  reproduces their published telemetry exactly (1 + 10 CRC-valid frames; the 10-vs-7 delta is
  their receiver lacking a turbo decoder) — frozen as a regression fixture referenced via
  `AERIX_RF_DATASET_ROOT` (AGPL, not copied). ANTSDR live capture → replay → CRC-valid decode
  (acceptance test A4) is **not yet done**. Research corpus indexed under `research/`.
- **Software (Phase 1 of `AERIX_RF_ANTSDR_PROJECT.md`, 2026-09-04):** hardware-neutral
  `IQSource`/`IQWindow`, continuous libhackrf stream with health counters, DC-spike removal,
  Stage-1 morphology / Stage-2 identity / Stage-3 decode separation, live ML path with rule
  fallback, scan→lock workflow, self-describing sessions with sha256 + deterministic replay,
  burst-by-burst DroneID decoder with integer-CFO search and a per-window time budget,
  Markdown session reports. Server RF path (contract + migrations 038/039 + ingest + retention)
  unchanged from before. 102 tests green.
- **Verified on real HackRF (ambient only, no drone yet):** 10-minute continuous soak (504
  windows, no failure, stream-rate ratio 0.999); 30 s lock runs in real time (~0.3 s/window,
  all windows complete); baseline/scan finds ambient Wi-Fi channels vs baseline; sessions
  written from hardware and replayed. Ambient 2.4 GHz gives `fhss_candidate` /
  `burst_wideband_candidate` morphologies, Stage-2 `unknown`, **0 CRC-valid decodes** — as it
  must.
- **Verified with aircraft (field test 2026-09-04, DJI Mini 3 + DJI Avata, stock antenna):**
  first **CRC-valid DJI DroneID decodes** from a real capture — Mini 3 on the ground, DroneID
  channel 2429.5 MHz inside a 2437 MHz window, four bursts on the 640 ms cadence, serial and
  consecutive sequence numbers consistent across windows, coordinates 0.0 (no GPS fix indoors).
  Decoded offline first, then live-equivalent after the decoder fix below; `aerix-rf replay`
  of that session reproduces `dec=C` in ~0.36 s/window. Also characterised from IQ: the Mini 3
  RC uplink (2 MHz hops, ~0.5 ms, 2 MHz raster) and video downlink (10–13 MHz OFDM, ~3 ms,
  20/40/60 ms period, channel moves in flight).
- **Decoder lesson from the field:** the DroneID burst was ~20 dB *below* the RC hops and the
  neighbours' Wi-Fi beacons in the same window and 7.5 MHz off the window centre, so
  "strongest 8 bursts, assumed at DC" never reached it. `decode_all` now screens up to 256
  envelope candidates by per-burst PSD shape (occupied 4–14 MHz = DroneID-shaped; the RC's
  2 MHz and Wi-Fi's 18 MHz are not), tries shaped ones first and mixes each to DC by its own
  centre (window-edge-clipped bands handled). `decode.jsonl` carries `center_offset_mhz`,
  `occupied_bw_mhz`, `droneid_shaped`.
- **Not yet seen:** a DroneID burst *in flight* (all Mini 3 flight windows at 2412/2437/2455/
  2475 MHz: no ZC hit, so no coordinates decoded yet), and the Avata (O3) — its 5.8 GHz link is
  below the stock antenna's floor and 2400–2412 MHz was never captured. **Protocols decoded:**
  OcuSync 2 DroneID (Mini 3). Do not read this as O3/O4 coverage.
- **Synthetic only:** the ML classifier live path (dummy bundle). The DroneRF-trained bundle is
  a 40 MS/s bench demonstrator — if used live at 20 MS/s it is flagged
  `model_sample_rate_mismatch`. Stage-1/2 mislabel fixed-channel links as `fhss_candidate` and
  do not yet discount 102.4 ms Wi-Fi beacon sources or BLE advertising channels.
- **Known limitations:** one 20 MHz slice at a time; in a busy 2.4 GHz band nearly every window
  is `plausible` (score = "interesting RF", not "drone"), so use the differential scan and the
  morphology/cadence fields — only a CRC-valid decode attributes identity; RSSI is uncalibrated;
  the laptop must keep the per-window pipeline under ~1 s or windows are skipped (reported as
  `gap=`). Not done: `odid-cues` site-scoping; ESP-side `/cue` sender firmware.
