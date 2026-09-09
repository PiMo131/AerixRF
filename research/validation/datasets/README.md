# Datasets worth downloading

The short list, ranked by what each one lets this project *prove*. The long
catalogue with every dataset the research sweep could find, including the ones
not worth the disk, is [`../../datasets.md`](../../datasets.md); the reasoning
behind the ranking is its section 2.

Two things to know before spending bandwidth:

- **The E200 cannot replay most of these natively.** Its host link streams
  10–20 MSPS continuously and snapshots to 61.44 MSPS. Anything recorded wider
  than 56 MHz can only be consumed after decimation, never reproduced.
- **None of them contain your fleet's link generation.** Every public DroneID
  capture is OcuSync 2. The Avata, Avata 2, Mini 4 Pro and Neo are O3/O4, and
  the only recording of any of them that exists is the one made on 2026-09-04
  (see the last section). No public corpus has ExpressLRS, Crossfire, HDZero,
  Walksnail or WFB-NG traffic either, and nothing was recorded in an EU urban
  spectrum environment.

Sizes and licences marked *unverified* come from third-party notes: the sweep
could not reach IEEE DataPort, Mendeley, Kaggle, Zenodo, SciDB or Hugging Face,
and neither can this sandbox. Check them on the page before downloading.

## 1. For the DroneID decoder — already validated

| | |
|---|---|
| **RUB-SysSec DroneSecurity samples** | <https://github.com/RUB-SysSec/DroneSecurity> → `samples/` |
| What | Two OcuSync 2 DroneID recordings, Mini 2 and Mavic Air 2, from the NDSS 2023 reference receiver. 50 MSPS interleaved float32, 7.6 MB total. Published decodes to check against. |
| Why | The golden vectors. This toolkit decodes 10 of 10 and 2 of 2 from them; the reference gets 7 and 1. Hash-checked regression runner: `toolkit/examples/validate_real_droneid.py`. |
| Caveat | **Not contiguous recordings** — triggered 970 µs extractions, concatenated. Timing, duty cycle and hop period measured from them belong to the extractor, not the drone. Manifest and proof: [`rub-syssec.md`](rub-syssec.md). |
| Size / access | 7.6 MB, clone the repo. Pin commit `9ff8198`. |

## 2. For detection and classification — the training material

| | |
|---|---|
| **RFUAV** | <https://huggingface.co/datasets/kitofrank/RFUAV> · code <https://github.com/kitoweeknd/RFUAV> · paper <https://arxiv.org/abs/2503.09033> |
| What | 37 drone and RC classes at 100 MSPS float32 from a USRP X310, 2.4 and 5.8 GHz, with per-clip XML. Includes **Avata 2, Mini 4 Pro, Mini 3, DJI FPV, Mavic 3 Pro**, SIYI, Herelink, RadioMaster, Jumper. |
| Why | The only public set whose class list looks like what actually flies here in 2026, and the only one containing your airframes. Resample by 5 to 20 MSPS to match the E200 streaming tier. Start with the 5- or 7-class subset. |
| Caveat | Video/control-link recordings, not DroneID bursts. Licence on the HF page never verified. Centre frequency reported inconsistently (2.4 GHz vs 5.765 GHz) by different sources. |
| Size / access | ~102 GB in 37 RAR parts, ~263 GB extracted. Hugging Face, public. *Blocked from this sandbox.* |

| | |
|---|---|
| **Noisy Drone RF Signal Classification v2** | <https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2> · loader <https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2> |
| What | ZHAW / armasuisse. USRP B210 in an anechoic chamber, 56 MSPS decimated to 14 MSPS at 2.440 GHz, with **explicit per-sample SNR labels from −20 to +30 dB in 2 dB steps**. Shipped as `.pt` tensors. |
| Why | The only corpus recorded on AD936x-class hardware at a rate the E200 sets natively. Gives the classifier its first honest detection-versus-SNR curve. |
| Caveat | Size disputed: ~23 GB reported, ~140 GB computed from the file schema. Pull a few `.pt` files first. Licence unverified. |
| Size / access | 23–140 GB. Kaggle CLI. *Blocked from this sandbox.* |

| | |
|---|---|
| **CageDroneRF (CDRF)** | request portal <https://aerodefense.tech/u-raptor-data-request> · toolkit <https://github.com/DroneGoHome/U-RAPTOR-PUB> |
| What | Rowan University and AeroDefense, 2026. **20 MSPS complex** — E200-native — at 905 MHz, 2.4 GHz and 5.8 GHz. 30 models, indoor / outdoor / cage, multi-drone mixes, and explicit non-drone classes (laptop Wi-Fi video, 5G, environment). |
| Why | The closest thing to what the E200 will record itself, and the only set with deliberate negatives at the same rate. |
| Caveat | Human request process — **start it now**, it takes time. Licence unknown. Capture hardware unstated. |
| Size / access | Not stated. By request. |

| | |
|---|---|
| **DroneDetect** | <https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine> |
| What | Swinney and Woods, 2020/21. BladeRF at 60 MSPS complex64, 2.4 GHz, seven drones, recorded under four interference conditions: **CLEAN / BLUETOOTH / WIFI / BOTH**. |
| Why | The interference-condition labels are what lets you measure false alarms from Wi-Fi and Bluetooth honestly — the question that decides whether the survey chain is worth anything. |
| Caveat | Decimate by 3 to 20 MSPS. BladeRF variant unstated. Directory structure known only through IQT Labs' loader. |
| Size / access | ~66 GB. IEEE DataPort account (free). *Blocked from this sandbox.* |

## 3. For false-alarm rejection — the negatives

| | |
|---|---|
| **NIST TN 2237 Wi-Fi / Bluetooth IQ** | via <https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model> · Kaggle mirror `nist-wifi-bluetooth-iq` |
| What | Real Wi-Fi and Bluetooth IQ at 2.4 and 5.8 GHz, `.h5`. No drones at all. |
| Why | A detector that fires on an access point is worthless. This is the cheapest way to find out whether yours does. |
| Caveat | Primary NIST publication and licence not established; the Kaggle mirror is third-hand. |
| Size / access | Not stated. Kaggle. |

## 4. For the harder questions — when the basics work

| | |
|---|---|
| **DroneRFb-DIR** | <https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202> · paper PDF <https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4> |
| What | JEIT 2025. NI USRP-2955 at 80 MSPS, 2.4–2.48 GHz. Several **individual units of the same drone model**. |
| Why | The only cross-individual benchmark. Hand-crafted features collapse from 100 % to 42 % across units here while a ConvNeXt holds 92 %. If the toolkit ever claims to recognise a *model*, this is the honest test. |
| Size / access | 64 GB, 32-part zip. SciDB registration (Chinese academic host). |

| | |
|---|---|
| **S3R** | <https://dx.doi.org/10.21227/wv7h-sv64> · Drive mirror <https://drive.google.com/file/d/1pdmxJmbM6aiMZlq6Hlr30PCeEewVL9oC/view> · code <https://github.com/DaftJun/S3R> |
| What | IEEE TIFS 2024. Nine ready-made known/unknown class splits in DroneRFa format, 100 MS/s at 2440 and 5800 MHz. |
| Why | The open-set protocol: what does the classifier say about a drone it has never seen? One loader covers S3R, DroneRFa and DroneRFA_24. |
| Size / access | Not stated. IEEE DataPort account or the Drive mirror. |

| | |
|---|---|
| **DroneRFa** | <https://www.scidb.cn/en/detail?dataSetId=34f0a91e8a544904998b8fdc44477380> · paper <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570> |
| What | Zhejiang University, JEIT 2024. NI USRP-2955 dual channel, 100 MS/s with 80 MHz bandwidth, at 915 / 2440 / 5800 MHz. 24 classes with **distance labels**. |
| Why | Multi-band and distance-labelled; re-cut into 20 MHz sub-bands for E200-rate training. Third priority only because of its size. |
| Size / access | ≥ 1 TB; a 574 GB single-RAR mirror exists. SciDB registration. |

## 5. Reference only — download for one specific reason or not at all

- **DroneRF** (Al-Sa'd 2019) — <https://data.mendeley.com/datasets/f4c2b4n755/1>. CSV amplitude,
  **no IQ**, 2 × 40 MSPS real-valued halves. Fine as a binary drone/no-drone fixture — it is what
  the `aerix-rf` branch's shipped `dronerf.joblib` was trained on — but everything beyond binary is
  leakage-inflated. 3.75 GB or ~40 GB depending on who you ask. CC BY 4.0, unconfirmed.
- **DRFF-R2** (2026) — 400 GB, 730 `.mat` files, and **nobody has established its sample rate**.
  Read <https://arxiv.org/abs/2603.00106> first; do not download on speculation.
- **UAVSig** (UCLA CORES, 2024) — four identical Matrice 100 units on a B205mini at 50 MSPS,
  for individual fingerprinting. Every fact about it is unverified and the Dataverse record was
  never located.
- **ZHAW VGG11_BN weights** — <https://zenodo.org/records/14065652>. Not data; a trained model
  for a zero-training baseline on Noisy Drone RF. Check the licence.

## 6. Not worth the disk

- **LowSNR_DroneRF** (Kaggle `laibatanveer/merged`) — no IQ, broken labels.
- **RTL-ML** — RTL-SDR at 1 MSPS, VHF/UHF, no drones.
- **CardRF** and the **Ezuma RC controller set** — oscilloscope captures at 20 GSa/s, 250 µs each.
  Interesting for transient-fingerprint theory, not replayable as baseband IQ.
- **Any spectrogram-only re-release** (DroneRFb-Spectra and similar) as a primary training source.
  Use the IQ they were rendered from.

## 7. The dataset that matters most is not on any server

On **2026-09-04** a field session was recorded with a HackRF Pro and a stock antenna: a **DJI Mini 3
on the ground and a DJI Avata**, home environment. It produced the first CRC-valid DroneID decodes
from a self-made capture (four OcuSync 2 bursts at 2429.5 MHz, 20 dB under the RC hops and Wi-Fi
beacons) and drove the off-centre band search on the `aerix-rf` branch. Record in
`aerix-rf/AERIX_RF_ANTSDR_PROJECT.md`.

That session is the only recording in existence of an O3 airframe alongside this project's own
receiver chain, and no public download will replace it. The gaps every corpus above leaves —
O3/O4 DroneID, ELRS/Crossfire/HDZero/Walksnail, an EU urban noise floor, this antenna, this
receiver — close only by recording more of these. The next one wanted, per that branch's own
notes: Mini 3 *in flight* with a GPS fix, locked on 2437 MHz. Store them as SigMF per
[`../../../docs/decisions/ADR-0002-sigmf-recordings.md`](../../../docs/decisions/ADR-0002-sigmf-recordings.md)
and put a hash in this directory, not the IQ.
