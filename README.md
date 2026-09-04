# aerix-rf — RF/SDR drone detection for AERIX

Adds **RF-based** drone detection to AERIX for the drones the ESP receivers can't see:
legacy DJI / OcuSync and other brands with no broadcast Remote ID. Runs on a small
Linux box (Raspberry Pi / mini-PC) driving a **HackRF Pro**. The HackRF only streams
IQ, so all DSP and detection run on the box, not the radio.

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
  today; a scikit-learn model trained on real datasets drops in behind the same interface.
- **Stage 3 — DJI DroneID decode** (`decode/`): best-effort serial + drone/operator GPS for
  OcuSync ≤ 2.0. Front end (ZC sync, resample, CFO, OFDM demod, equalize, QPSK, LTE descramble)
  is implemented and synthetic-verified; Turbo decode / field extraction is the remaining stage.

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

9. **Decode scope is honest.** Only OcuSync ≤ 2.0 is decodable (O3/O4 encrypted; O4 gives a
   session hash only). The front end is verified against *synthetic* bursts, not yet a real
   capture — flagged in `decode/droneid.py`.

---

## Run

```sh
uv sync

# No hardware — synthetic IQ, one JSON status line per second:
uv run aerix-rf --sim

# Real HackRF (after `sudo apt install hackrf`): uses hackrf_transfer capture
uv run aerix-rf

# With server uplink + sensor position:
AERIX_RF_SERVER_URL=https://host:8180 AERIX_RF_SENSOR_ID=sdr-... AERIX_RF_TOKEN='sdr-...~secret' \
AERIX_RF_LAT=52.1 AERIX_RF_LON=5.1 uv run aerix-rf
```

Provision a `hackrf` sensor once: `POST /v1/sensors:provision {"class":"hackrf"}`.

**Find a drone across the band:**
```sh
python -m aerix_rf.tools.sweep_locate baseline 2400 2485 base_24.csv   # drone OFF
python -m aerix_rf.tools.sweep_locate find     2400 2485 base_24.csv   # drone ON -> candidate channel
```

**Local cue (Path 1b):**
```sh
curl -XPOST http://aerix-rf.local:8770/cue -H "X-Local-Token: $TOKEN" \
  -d '{"serial":"1581F...","transport":"ble_legacy","rssi":-60}'
```

**Train the classifier** (see `aerix_rf/classify/train/README.md`):
```sh
uv run --extra train python -m aerix_rf.classify.train.train --dataset dronerf --data-root <path> \
  --sample-rate 20e6 --out models/signature.joblib
```

---

## Status

- **Software:** box detection chain, server RF path (contract + migrations 038/039 + ingest
  route + writer + retention), classifier pipeline, DroneID decode front end, sweep locator —
  all built and integrated; 31 tests green.
- **Verified on real HackRF:** full end-to-end (live capture → detect → spectrogram → ingest →
  `rf_detections`) proven on ambient RF; real-time (~155 ms/window).
- **Not yet done:** a real drone RF detection (needs a transmitting drone found via the sweep
  locator); DroneID Turbo decode + field extraction; classifier trained on real data (synthetic
  models don't reject Wi-Fi); `odid-cues` site-scoping; ESP-side `/cue` sender firmware.
