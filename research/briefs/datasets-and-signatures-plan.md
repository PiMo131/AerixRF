# Brief: What more the CSDN corpus + public datasets can do for AERIX RF

**Question.** Beyond what's already indexed, can the public RF datasets and the
CSDN/FPV corpus support (A) a Stage-2 drone-family/manufacturer classifier
trained/benchmarked against our own ANTSDR ambient negatives, plus a
receiver-ID probe once our O3/O4 campaign overlaps a public dataset model; and
(B) a table of corpus-derived RF signatures usable for hardware-neutral
Stage-1/2 rules?

## Part A — Public datasets as training/benchmark positives

### Dataset → coverage → pipeline status

| Dataset | DJI models (generation, confidence) | Other mfrs | Sample rate | IQ? | Size/class | Licence | Pipeline status |
|---|---|---|---|---|---|---|---|
| `zenodo_drone_rf_video_2020` (local, prepared) | Inspire 2, Matrice 100/210, Mavic Pro (OcuSync1, Med), Mavic Mini (enhanced-WiFi not OcuSync, Med), Phantom 4 / 4 Pro+ (Lightbridge2, not OcuSync, Med) | Parrot Disco/Mambo, Yuneec Typhoon H | 120 MHz@2.44GHz / 200 MHz@5.8GHz | Yes, int16 IQ | ~0.5-1s clips, 19 files, 8.6GB total | CC-BY-4.0 | **Enters canonical pipeline now** — clean high-SNR reference, but pre-O3/O4, no anechoic-to-field domain match |
| `dronerf` (local, complete) | Phantom 3 (pre-OcuSync, Med) | Parrot Bebop, AR Drone | 40 MSps | **No** — real-valued amplitude, not IQ | 3.8GB, 23 files | CC BY 4.0 | **Needs adapter** (magnitude-only ingestion path) before it can enter an IQ pipeline |
| `rub_dronesecurity` (local, complete) | Mavic Air 2, Mini 2 SE (both OcuSync2, High) | — | 50 MHz | Yes, complex64 | 2 captures | AGPL-3.0 | **Enters now** — already used for DroneID decode cross-check, not yet used as classifier training data |
| `dronerfb_dir` (local, 63.6GB, not yet read) | Not enumerated — needs paper/metadata read post-extraction | 6 drone types x 3 individuals | not confirmed | raw IQ (claimed) | ~64GB/18 airframes | Unknown (ScienceDB) | **Needs one focused read pass** before pipeline entry — unique per-individual-airframe labels once model names confirmed |
| `dronerfa` (not downloaded) | Not enumerated | multi-drone + WiFi/BT | ~100MHz BW/band (unverified) | claimed raw | ~570GB (unverified) | Unknown | **Not started** — largest multi-band open-set candidate but unverified in every technical detail |
| `rfuav` (HF `kitofrank/RFUAV`, **DJI subset download started this pass**) | AVATA2 (O4, Med), FPV COMBO (O3, Low-Med — DJI FPV system not independently confirmed as "O3" from a primary DJI source), MAVIC3 PRO (O3, Med), MINI3 (ambiguous — "Mini 3" non-Pro is commonly reported as O2, "Mini 3 Pro" as O3; RFUAV's label doesn't disambiguate, **flag as unconfirmed**), MINI4 PRO (O4, Med) | 31 more files are **RC transmitter units** (FlySky/FrSky/Futaba/JR Propo/Jumper/RadioMaster/Radiolink/SIYI/Skydroid/WFLY/Yunzhuo/Herelink/Devention/Dautel) — not drone airframes, despite the dataset's "37 UAV classes" framing | unconfirmed this pass | raw, per-model `.rar` (not spectrogram-only — see resolved-size note below) | Apache 2.0 | **DJI subset (5 files, ~43GB) downloading now**; 31 RC-vendor files identified as a fast-follow (not started, see USER_TODO) |
| `noisy_drone_rf_v1/v2` (Kaggle, gated) | not confirmed | not confirmed | 14 MHz | preprocessed IQ vectors | moderate | not confirmed | **Needs Kaggle auth** — steps in USER_TODO, unchanged this pass |
| UAVSig (IEEE DataPort open-access + UCLA Dataverse mirror, resolved 2026-09-18) | n/a — RC transmitters only | 17 RCs / 8 mfrs | ~20MSps (unconfirmed) | raw | unknown | unknown | **Access resolved, download not started** — needs IEEE account or Dataverse pull |
| CageDroneRF (GitHub `U-RAPTOR-PUB` code+weights; raw data behind a gated AeroDefense request form) | 23 models, not enumerated | — | unknown | claimed raw IQ | unknown | unknown | **Code/weights may be pullable now; raw IQ needs a human-submitted access request** — see USER_TODO |

**Resolved this pass:** the long-standing "RFUAV size discrepancy" (1.3TB paper claim vs
281.6GB corpus pointer) is now partially explained — the HF repo's own dataset-card
viewer reports 299GB counting only its `ImageSet-AllDrones-MatlabPipeline` +
`ValidationSet_5Drones` spectrogram-image folders; the **top-level per-model `.rar`
files are raw-ish frequency data, measured directly this pass at 109.2GB across 36
files** (not spectrograms). Neither figure reaches 1.3TB — likely the abstract's
figure describes a pre-release/internal capture volume, not what's published. Not
fully resolved; flag for a future pass if the exact number matters.

### Recommended first Stage-2 training set

1. **Positives:** `zenodo_drone_rf_video_2020` (10 airframes, clean high-SNR, already
   prepared) + `rub_dronesecurity` (2 OcuSync2 airframes, decode-validated) as the
   seed set, extended with the **RFUAV DJI subset** (5 models: AVATA2, FPV COMBO,
   MAVIC3 PRO, MINI3, MINI4 PRO — downloading now) once extracted and format-checked.
   This spans pre-OcuSync/Lightbridge, OcuSync1/2, and candidate O3/O4 models in one
   set — the broadest DJI-generation span currently obtainable without a gated
   request.
2. **Negatives:** our own `aerix_antsdr_ambient_2026_09_18` corpus (41GB, 2.4GHz
   ambient, no-drone ground truth, 8 sessions) — already the project's only
   operator-confirmed true-negative set; do not substitute a public "drone-off"
   class for this.
3. **Do not yet include** `dronerf` (format mismatch), `dronerfa`/`dronerfb_dir`
   (unread), or Kaggle/UAVSig/CageDroneRF (access not yet completed) in a first
   training run — each needs its own short verification pass first.

### Receiver-ID probe (runnable once O3/O4 campaign overlaps a public model)

Once AERIX's own ANTSDR captures of a DJI model that **also appears in the RFUAV DJI
subset** exist, run a same-model cross-corpus generalization probe: train a
classifier/fingerprint model on RFUAV's IQ for that model, test on AERIX's own
capture of the same model (and vice versa). This tests whether cross-recorder/
cross-environment domain shift dominates over genuine per-model or per-unit RF
signature — a prerequisite question before trusting any "individual airframe"
fingerprinting claim. **Candidate overlapping models (confirm exact SKU on
capture):** DJI Mini 3 / Mini 3 Pro, DJI Mini 4 Pro, DJI Mavic 3 Pro, DJI Avata 2,
DJI FPV Combo. This is a data/evaluation-design recommendation only — escalate the
actual classifier design to `rf-dsp-specialist`.

## Part B — Corpus-derived RF signatures for Stage-1/2 rules

| System | Band | Channel raster | Hop count/rate/dwell | Packet/burst duration | Bandwidth | Modulation | Duty cycle | Grade | Source (`research/library/...`) |
|---|---|---|---|---|---|---|---|---|---|
| **ExpressLRS 2.4GHz** | 2400.4-2479.4 MHz | 80 ch, 1.000 MHz spacing, sync ch = freq_count/2 | packet rate 50-1000Hz → dwell ~1-20ms; sync channel revisited every `freq_count` hops | per-packet (µs-scale, CRSF-derived) | LoRa 125kHz-1MHz / FLRC narrower | LoRa chirp / FLRC / GFSK | TDD 1:2…1:128 telemetry ratio | **PRIMARY (firmware source)** | `fpv/AERIX_FPV/control_links/ExpressLRS/FHSS_key_sources/FHSS.cpp`,`.h` |
| **ExpressLRS sub-GHz domains** | FCC915 903.5-926.9MHz(40ch); AU915(20ch); EU868 863.275-869.575MHz(13ch); TH920 920.5-924.7MHz(8ch,600kHz spacing) | see band | as above | as above | as above | as above | as above | **PRIMARY (firmware source)** | same file, regulatory-domain table |
| **SiK/3DR** | 433/915 MHz | ≤50 channels, NETID-shuffled | adaptive TDM | variable | narrowband GFSK | GFSK | adaptive | **PRIMARY (firmware source)** | `csdn_enriched/.../non_dji_telemetry/MAVLink/SiK_3DR_Holybro/source` |
| **mLRS** | 2.4G/915/433 | per-domain (source) | 50Hz control + 3-5kB/s telemetry | packet-level | LoRa/FLRC | LoRa/FLRC | TDD | **PRIMARY (firmware source)** | `csdn_enriched/.../non_dji_telemetry/MAVLink/mLRS/source` |
| **TBS Crossfire** | 915 MHz | closed hop set | 150 Hz | packet-level | LoRa | LoRa | TDD | **COMMUNITY (PLAUSIBLE grade)** | `NON_DJI_POSITION_MATRIX.md`, `GENERIC_HOPPING_FEATURES.md` |
| **FrSky ACCST/ACCESS** | 2.4G / 868-915MHz | closed FHSS | 100-200 Hz | packet-level | GFSK/LoRa | GFSK/LoRa | TDD | **COMMUNITY (PLAUSIBLE)** | same |
| **FlySky AFHDS2A** | 2.4 GHz | partly open | not specified | packet-level | GFSK | GFSK | TDD | **COMMUNITY (SUPPORTED — partly corroborable)** | same |
| **Futaba FASST/T-FHSS** | 2.4 GHz | closed | 100 Hz | packet-level | DSSS/FHSS | DSSS/FHSS | TDD | **COMMUNITY (PLAUSIBLE)** | same |
| **DJI DroneID (O1-O3)** | 2.4/5.8 GHz | 7 candidate 2.4GHz centres (2399.5-2474.5MHz, union of 2 disagreeing lists), 12 candidate 5.8GHz centres (2 lists disagree on all but one point) | burst interval **640ms measured** (NDSS'23, PRIMARY PAPER); no disclosed hop pattern | 9-symbol OFDM burst | ~9.0 MHz occupied (601 active subcarriers × 15 kHz SCS; the 1024-FFT decoder rate is 15.36 MS/s, not the occupied width) | OFDM/QPSK, LTE Turbo coding | bursty, non-continuous | **PRIMARY PAPER (burst interval/OFDM params); COMMUNITY (raster, empirical scan lists)** | `briefs/droneid-channel-raster.md`, `briefs/dji-ocusync-droneid-sources.md` |
| **Analog FPV VTX (5.8GHz, RTC6705/RX5808)** | 5.8 GHz (Band A/B/E/Fatshark/Raceband grids) | ~40 fixed channels, 1-2MHz-ish spacing per grid | continuous, not hopped | continuous transmission | ~6MHz analog FM video | Analog FM composite video | near-100% while armed | **COMMUNITY (hobbyist blogs; chips are real/corroborable independently)** | `fpv/AERIX_FPV/analog_video/channel_plans/` |
| **OpenHD/wifibroadcast** | 2.4/5.8 GHz (802.11 PHY) | WiFi 20/40MHz channels, injection-based, not classic hop | variable | frame-level, bitrate-adaptive | 20/40 MHz | 802.11 OFDM (raw injection) | continuous while streaming | **COMMUNITY** | `fpv/AERIX_FPV/digital_video/{OpenHD,wifibroadcast}/` |
| **HDZero** | 5.8 GHz | reuses analog raceband-like grid | continuous | frame-level | narrower than WiFi-based systems | proprietary OFDM | continuous while streaming | **COMMUNITY** | `fpv/AERIX_FPV/digital_video/HDZero/` |

**Top 5 rows by combined evidence strength + Stage-1 actionability:** ExpressLRS
2.4GHz raster (PRIMARY, exact numbers, directly codeable channel-grid detector);
ExpressLRS sub-GHz domains (PRIMARY, same); SiK 433/915 NETID-shuffle (PRIMARY,
distinguishes MAVLink-transparent links); DJI DroneID 640ms burst interval + OFDM
occupied BW (PRIMARY PAPER, load-bearing for any DroneID scan-dwell design); FlySky
AFHDS2A (best-corroborated COMMUNITY entry, worth a follow-up primary source check).

## Open questions
- `dronerfb_dir` and `dronerfa` model lists remain unread — both block any dataset
  table row from moving out of "needs adapter/needs read".
- RFUAV per-model `.rar` internal structure (sample rate, exact IQ format) not yet
  verified — first task once the current download completes.
- DJI "Mini 3" vs "Mini 3 Pro" OcuSync generation ambiguity in the RFUAV label is
  unresolved — do not assume O3 without checking the archive contents/paper.
- Crossfire/FrSky/Futaba rows remain COMMUNITY-only; no primary firmware or FCC
  filing was located in this corpus for their hop rasters.

## Sources
- `research/briefs/rf-datasets.md`, `research/datasets/manifest.json`, `research/datasets/USER_TODO.md`
- `research/index.md` (source-cluster catalog)
- `research/briefs/droneid-channel-raster.md`, `research/briefs/dji-ocusync-droneid-sources.md`
- `research/library/fpv/AERIX_FPV/control_links/ExpressLRS/FHSS_key_sources/{FHSS.cpp,FHSS.h}` (read directly this pass)
- `research/library/csdn_enriched/AERIX_RF_CSDN/generic_RF_detection/GENERIC_HOPPING_FEATURES.md`, `NON_DJI_POSITION_MATRIX.md` (read directly this pass)
- `https://huggingface.co/api/datasets/kitofrank/RFUAV` (file listing + sizes fetched directly this pass), `https://huggingface.co/datasets/kitofrank/RFUAV` (dataset card, fetched)
