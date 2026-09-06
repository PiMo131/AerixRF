# Datasets: what exists, what fits an ANTSDR E200, and how to record our own

This is the dataset half of the research record. It catalogues every public drone-RF corpus the
sweep could reach, states what hardware and sample rate each was captured at, what is actually in
the files, what is wrong with them, and what it costs to make each one usable on an **ANTSDR E200**.
It then answers the two questions that matter for the toolkit: which corpora to start from, and how
to record our own captures so they can be compared with these and with each other.

Conventions, matching the rest of the research record:

* **verified** means an agent cloned the repository or fetched the page and read it; **snippet**
  means only a search-engine snippet or a third-party description was reachable from the sandbox.
  The per-source flag is in [sources.md](sources.md).
* Design-critical claims that went through the adversarial pass are cited as *(verified: verdict N)*
  where N is the position in `verdicts.json`, mirrored in [verification-log.md](verification-log.md).
* Two claims were queued for verification but the agent budget ran out; they are labelled
  **unverified round-1** wherever used (`o4-firmware-channels`, `ocusync-phy`).
* **A large share of this chapter is snippet-grade.** Every non-GitHub host that matters here
  (IEEE DataPort, Mendeley, Kaggle, Zenodo, Hugging Face, SciDB, jeit.ac.cn, arXiv, UCLA Dataverse)
  was egress-blocked for the whole sweep, and the WebSearch budget was already exhausted when the
  dataset lens ran ([dataset lens gaps](https://github.com/kitoweeknd/RFUAV)). Most dataset
  parameters below therefore come from code that reads the data (loaders, download scripts) rather
  than from the dataset pages themselves. Where that is the case, the text says so.

The three E200 numbers that decide dataset compatibility, from
[hardware-e200.md](hardware-e200.md): the AD9361 variant covers 70 MHz to 6 GHz with 56 MHz
instantaneous bandwidth and a 200 kS/s to 61.44 MS/s sample-rate range
([Crowd Supply](https://www.crowdsupply.com/microphase-technology/antsdr-e200), snippet;
[vendor RF table](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md));
continuous single-channel sc16 streaming to the host is capped at about 29.6 MSPS by the 1 GbE
1500-byte MTU and at the vendor's stated 20 MSPS in practice, with roughly 10 MSPS safe on stock
IIO firmware *(verified: verdict 2)*; snapshot capture up to 61.44 MSPS is possible on both firmware
personalities because the DMA lands in DDR first *(verified: verdict 2)*. Anything recorded above
about 56 MHz span cannot be reproduced on this board at all, only consumed after decimation.

---

## 0. Index of everything catalogued

| # | Dataset | Year | Capture front end | Rate / span | Bands | Raw IQ | Size | Access | E200 fit |
|---|---|---|---|---|---|---|---|---|---|
| 1.1 | DroneRF | 2019 | NI USRP via LabVIEW, model unstated | 2 x 40 MSPS, real-valued | 2.4 GHz (2 x 40 MHz halves) | no (CSV amplitude) | 3.75 GB or ~40 GB, contradictory | Mendeley, CC BY 4.0 | consume only |
| 1.2 | DroneDetect | 2020/21 | BladeRF, variant unstated | 60 MSPS complex64 | 2.4 GHz | yes | ~66 GB | IEEE DataPort | decimate 3 to 20 MSPS |
| 1.3 | CardRF | 2022 | Keysight MSOS604A scope, 20 GSa/s | 250 us per capture, real | RF, not baseband | no | 65+ GB | IEEE DataPort | not replayable |
| 1.4 | Ezuma RC dataset | 2020 | oscilloscope | 0.25 ms per record, real | 2.4 GHz | no | not stated | IEEE DataPort | not replayable |
| 1.5 | DroneRFa | 2024 | NI USRP-2955 dual channel | 100 MS/s per channel, 80 MHz IBW | 915 / 2440 / 5800 MHz | yes | >= 1 TB, 574 GB RAR mirror | SciDB, registration | decimate 5 to 20 MSPS |
| 1.6 | DroneRFb-DIR | 2025 | SDR, model unstated | 80 MSPS | 2.4 to 2.48 GHz | yes | 64 GB zip / 65 GB | SciDB, registration | decimate 4 to 20 MSPS |
| 1.7 | DRFF-R2 | 2026 | not stated | not stated | not stated | yes (.mat) | 400.6 GB, 730 files | SciDB, registration | unknown |
| 1.8 | S3R dataset | 2024 | DroneRFa-format | 100 MS/s, 2440 / 5800 MHz | 2.4 / 5.8 GHz | yes | not stated | IEEE DataPort + Google Drive | decimate 5 |
| 1.9 | RFUAV | 2025 | USRP X310 (third-party) | 100 MSPS float32 | 2.4 / 5.8 GHz | yes | 102 GB rar, ~263 GB out | Hugging Face | decimate 5, or 2/5 to 40 |
| 1.10 | CageDroneRF (CDRF) | 2026 | not stated | 20 MSPS complex | 905 MHz / 2.4 / 5.8 GHz | yes | not stated | request portal | native |
| 1.11 | Noisy Drone RF v1/v2 | 2023/24 | USRP B210 + LogPer, anechoic | 56 MSPS decimated to 14 MSPS | ~2.440 GHz | yes (.pt tensors) | ~23 GB reported | Kaggle | native |
| 1.12 | UAVSig | 2024 | USRP B205mini (survey) | 50 MSPS, 50 MHz | not stated | yes | 720 files | UCLA Dataverse | native snapshot |
| 1.13 | NIST TN 2237 | n/a | not stated | not stated | 2.4 + 5.8 GHz | yes (.h5) | not stated | Kaggle mirror | negatives only |
| 1.14 | LowSNR_DroneRF (Kaggle) | 2026 | not stated | 10 MHz claimed | not stated | **no** | ~3 GB | Kaggle | do not use |
| 1.15 | DroneSecurity samples | 2023 | USRP B200 family via UHD | 50 MSPS complex64 | 2.4 GHz | yes | 7.6 MB total | in-repo | native snapshot |
| 1.16 | samples2djidroneid | 2024-26 | n/a | 15.36 / 30.72 MSPS input | 2.4 GHz | **no data shipped** | n/a | GitHub | decoder only |
| 1.17 | RTL-ML | 2026 | RTL-SDR Blog V4 | 1.024 MSPS | VHF/UHF, no drones | yes (.npy) | 6.2 GB, 800 samples | Hugging Face | out of scope |

Derived and re-published sets (spectrograms or tensors, not raw IQ) are in section 1.18. Chinese
aggregation pages that may list more are in 1.19.

---

## 1. Catalogue

### 1.1 DroneRF (Al-Sa'd et al., 2019)

| Field | Value |
|---|---|
| Data DOI | [10.17632/f4c2b4n755.1](http://dx.doi.org/10.17632/f4c2b4n755.1), [Mendeley landing page](https://data.mendeley.com/datasets/f4c2b4n755/1) |
| Companion code | [Al-Sad/DroneRF](https://github.com/Al-Sad/DroneRF), Apache-2.0 (LICENSE read in the clone) |
| Papers | Al-Sa'd et al., Future Generation Computer Systems 2019, doi 10.1016/j.future.2019.05.007; Data in Brief 26:104313 ([repo README](https://github.com/Al-Sad/DroneRF)) |
| Capture chain | LabVIEW "RF Record-Playback" project with NI USRP hardware; the exact USRP model is not in the repo ([repo](https://github.com/Al-Sad/DroneRF)) |
| Rate and span | two channels "L" and "H" at fs = 40e6 each, covering the lower and upper halves of the 2.4 GHz band; `Demo_3_Analysis.m` treats the combined band as 80 MHz ([repo](https://github.com/Al-Sad/DroneRF)) |
| Format | CSV, real-valued amplitude samples, **not complex IQ**; segments of 1e7 samples; `Main_1` aggregates 1e5-sample segments into 2048 frequency bins ([repo](https://github.com/Al-Sad/DroneRF)) |
| Classes | BUI label codes: background 00000; Parrot Bebop 10000-10011 (4 flight modes); Parrot AR Drone 10100-10111; DJI Phantom 3 11000 ([repo](https://github.com/Al-Sad/DroneRF)) |
| Size | **contradictory**: ~40 GB raw CSV per [drone-rf-id](https://github.com/song-lalala/drone-rf-id), 3.75 GB in the [rfml-moe-hub survey table](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md) (likely the aggregated `.mat`) |
| Licence | dataset CC BY 4.0 per the [drone-rf-id README](https://github.com/song-lalala/drone-rf-id); not confirmed on the Mendeley page (blocked) |

Known flaws. Only three drones and ten classes, and the data are real amplitude rather than IQ, so
no phase-based or cyclostationary work is possible. Published accuracies on it are inflated:
Shulman 2026 shows AR-versus-Bebop type identification falling from macro-F1 0.742 to 0.455, which
is chance, under leave-one-recording-out, with only four independent recordings per drone
([arXiv 2607.01025](https://arxiv.org/abs/2607.01025), [spectrahawk](https://github.com/shulm/spectrahawk))
*(verified: verdict 8)*. The original
[Classification.py](https://github.com/Al-Sad/DroneRF/blob/master/Python/Classification.py) uses
`StratifiedKFold(shuffle=True)` over segments, which is exactly the leaky protocol. Binary
drone-versus-background survives grouped evaluation at ROC-AUC 0.978 +/- 0.017, and small
2048-sample models lose only 0 to 3 points under grouped splits (binary RF 0.871 to 0.857; type
0.55 to 0.54; mode 0.43 to 0.41), because they were already near the honest level
([dronerf-emi-robustness](https://github.com/greenbeanss/dronerf-emi-robustness))
*(verified: verdict 8)*.

E200 fit: consume only, and only as a regression fixture. Two 40 MSPS real channels do not map onto
an IQ pipeline, the drone set is a decade old, and the honest ceiling is binary detection.

### 1.2 DroneDetect (Swinney and Woods, 2020/21)

| Field | Value |
|---|---|
| Download | [IEEE DataPort open access](https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine) (page blocked from the sandbox) |
| Reference loader | [IQTLabs/RFClassification](https://github.com/IQTLabs/RFClassification) `loading_functions.py` |
| Front end | Nuand BladeRF; the exact variant is not stated by any source read, so its AD9361-family status is an assumption ([RFClassification](https://github.com/IQTLabs/RFClassification)) |
| Rate and format | float32 complex64 IQ at **60 MHz sample rate**, 240,000,000-sample files, directory `DroneDetect_V2` ([RFClassification](https://github.com/IQTLabs/RFClassification)) |
| Band | 2.4 GHz ([IEEE DataPort listing](https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine), snippet) |
| Content | 7 drones + 7 controllers; interference conditions CLEAN / BLUE / WIFI / BOTH encoded 00/01/10/11; flight modes; 21 mode classes referenced in related Swinney papers ([RFClassification](https://github.com/IQTLabs/RFClassification)) |
| Size | ~66 GB ([rfml-moe-hub survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md), unverified secondary) |
| Licence | IEEE DataPort "open access"; the actual data licence was not verified |
| Published baselines | 7-drone classification on 20 ms windows: PSD (NFFT=1024) + SVM 0.854, spectrogram + VGG16 0.816; 50 ms windows raise PSD+SVM to 0.894, while NFFT barely matters ([RFClassification](https://github.com/IQTLabs/RFClassification)) |

E200 fit: 60 MSPS is just above the E200's 56 MHz analog bandwidth, so decimate by 3 to 20 MSPS (or
by 2 to 30 MSPS for snapshot work). The genuinely valuable part is the **interference-condition
labelling**: CLEAN / BLUE / WIFI / BOTH is the template an urban AERIX node should copy for its own
field collections, because false alarms from Wi-Fi and Bluetooth are the dominant failure mode
([RFClassification](https://github.com/IQTLabs/RFClassification)).

### 1.3 CardRF (Cardinal RF, Medaiyese et al., 2022)

| Field | Value |
|---|---|
| Documentation read | [Marchev-Science/case-drone-signature-classification](https://github.com/Marchev-Science/case-drone-signature-classification) (mirror of the CardRF README) |
| Capture | August 2020 at NC State's AERPAW Lake Wheeler site with a **Keysight MSOS604A oscilloscope**; metadata XInc 5e-11 s = 20 GSa/s, 5,000,000 points = 250 us per capture, scale 6.581e-06 V ([mirror](https://github.com/Marchev-Science/case-drone-signature-classification)) |
| Geometry | LOS at 8 to 12 m; NLOS for Inspire, Matrice 600 and Phantom only ([mirror](https://github.com/Marchev-Science/case-drone-signature-classification)) |
| Devices | UAV: DJI Phantom 4, Inspire, Matrice 600, Mavic Pro 1, Beebeerun FPV mini quad, 3DR Iris FS-TH9x. Bluetooth: iPhone 6S, iPhone 7, iPad 3, FitBit Charge3, Motorola E5 Cruise. Wi-Fi: Cisco Linksys E3200, TP-Link TL-WR940N ([mirror](https://github.com/Marchev-Science/case-drone-signature-classification)) |
| Layout | LOS/NLOS -> Train/Test -> BLUETOOTH / UAV / UAV_controller / WIFI -> device -> FLYING / HOVERING / VIDEOING ([mirror](https://github.com/Marchev-Science/case-drone-signature-classification)) |
| Labels | transient and steady-state portions marked per signal; a processed set of 1024-sample steady-state slices is provided ([mirror](https://github.com/Marchev-Science/case-drone-signature-classification)) |
| Size | 65+ GB ([rfml-moe-hub survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md), unverified secondary) |
| Related papers | Medaiyese et al., "Hierarchical learning framework for UAV detection and identification" [arXiv:2107.04908](https://arxiv.org/abs/2107.04908); "Wavelet transform analytics for RF-based UAV detection" [arXiv:2102.11894](https://arxiv.org/abs/2102.11894) |

**Contradiction to record.** The rfml-moe-hub survey table lists CardRF as "17 controllers, 8
manufacturers"
([survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md)),
which is the description of the separate Ezuma remote-controller dataset (1.4), not the device list
in the CardRF README read above. Treat the survey row as wrong and the README device list as
authoritative until the IEEE DataPort page can be fetched.

E200 fit: none directly. These are real-valued oscilloscope traces at RF, not baseband IQ, so they
can be neither replayed by nor matched against an E200 capture without a simulated downconversion
stage. Their value is conceptual: they are the clearest worked example of separating a **transient**
(turn-on) fingerprint from a **steady-state** fingerprint, and they carry the Bluetooth and Wi-Fi
negative classes that a detector needs.

### 1.4 Drone Remote Controller RF Signal Dataset (Ezuma, Erden, Kumar, Ozdemir, Guvenc, 2020)

| Field | Value |
|---|---|
| Download | [IEEE DataPort open access](https://ieee-dataport.org/open-access/drone-remote-controller-rf-signal-dataset) (page blocked; description from search snippet) |
| Content | 17 RC controllers from 8 manufacturers (Spektrum, Futaba, Graupner, FlySky, JR, Turnigy, DJI and others), about 1000 captures each of 0.25 ms, all in the 2.4 GHz band, drones idle during capture ([listing](https://ieee-dataport.org/open-access/drone-remote-controller-rf-signal-dataset)) |
| Format | oscilloscope captures, very high sample rate, not baseband IQ ([listing](https://ieee-dataport.org/open-access/drone-remote-controller-rf-signal-dataset)) |
| Downstream result | wavelet scattering + SqueezeNet reported at 98.9% at 10 dB on this 17-controller / 8-manufacturer set ([rfml-moe-hub survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md), unverified secondary) |

E200 fit: same limitation as CardRF. Useful for legacy FHSS controller waveform studies, useless for
ExpressLRS or Crossfire, which post-date it (see [landscape.md](landscape.md) section 3).

### 1.5 DroneRFa (Zhejiang University, JEIT 2024)

| Field | Value |
|---|---|
| Paper | Yu Ningning, Shi Zhiguo, Chen Jiming et al., 电子与信息学报 46(4), 2024, [doi 10.11999/JEIT230570](https://doi.org/10.11999/JEIT230570) ([JEIT page](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)); PDF read from the [DroneRFA_24 mirror](https://github.com/maojinxiang/DroneRFA_24-Dataset) |
| Download | [SciDB dataSetId 34f0a91e8a544904998b8fdc44477380](https://www.scidb.cn/en/detail?dataSetId=34f0a91e8a544904998b8fdc44477380); the paper's own link `jeit.ac.cn/web/data/getData?dataType=Dataset3` now redirects there ([JEIT dataset column](https://jeit.ac.cn/web/data/getData?dataType=Dataset1)) |
| Receiver | NI USRP-2955, 100 MS/s I/Q, 80 MHz instantaneous bandwidth, 14-bit ADC, gain 50 dB, VERT2450 3 dBi omni, PCIe to a Xeon W-2245 host running LabVIEW ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)) |
| Channels | RF0 centred 2440 MHz, RF1 centred 5800 MHz; for FrSky X20 and Taranis Plus the pair is 915 MHz + 2440 MHz ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)) |
| Classes | 24 drone/controller classes plus background (background contains Bluetooth and Wi-Fi); 9 outdoor flying types at 20-40 / 40-80 / 80-150 m and 15 indoor types at ~2 m ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)) |
| Drone list | DJI Phantom 3, Phantom 4 Pro, Matrice 200, Matrice 100, Air 2S, Mini 3 Pro, Inspire 2, Mavic Pro, Mini 2, Mavic 3, Matrice 300, Phantom 4 Pro RTK, Matrice 30T, Avata, DJI-module DIY, Matrice 600 Pro; controllers VBar, FrSky X20, Futaba T6IZ, Taranis Plus, RadioLink AT9S, Futaba T14SG, Yunzhuo T12, Yunzhuo T10 ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)) |
| Format | `.mat` (HDF5) with `RF0_I` / `RF0_Q` / `RF1_I` / `RF1_Q` float64; files <= 1.5 GB; >= 12 segments per class, each >= 1e8 samples; total >= 1 TB ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)); third-party mirror is a single ~574 GB RAR, SciDB fileId c403fc76444e4b9989e4f3ff570f3b3d ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Filenames | `T<type>_D<distance>_S<segment>`; distances D00 = 20-40 m, D01 = 40-80 m, D10 = 80-150 m, indoor ~2 m; S0000-0111 initial band (915 MHz or 2.4 GHz), S1000-1111 after switching to 2.4/5.8 GHz ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)) |
| Baseline | ResNet-18 on a 2 x 1024 x 1024 STFT (N=1024, 50% overlap) of 1e6-sample (10 ms) windows: accuracy 97.73% at 53 fps on a 9809 / 3217 / 3299 split; window shortened to 256 k samples gives 72.7%; frequency resolution 128 gives 87.9% at 217 fps ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)) |
| Access | SciDB requires a registered email; downloads use `username`/`traceId` query parameters ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |

Known flaws. The acquisition is "capture-store-capture-store", which **breaks continuity every 10 M
samples, i.e. every 0.1 s**; the paper states analysis windows shorter than 0.1 s are unaffected
([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)). A third party describes the
rate as "80 MSps dual-receiver" ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)), which
conflicts with the paper's 100 MS/s sampling at 80 MHz instantaneous bandwidth; prefer the paper.
Almost every published model on it uses window-level or image-level splits: RF-TCNet and the
DroneRFA_24 spectrogram subset shuffle spectrogram images inside each class folder with a 7:2:1 or
6:2:2 split, and SE-DCNet's split puts all 109 source `.mat` files into train, validation and test
([RF-TCNet](https://github.com/FAITHSHUNAA/RF-TCNet-A-Lightweight-Topology-Compression-Network-for-Drone-RF-Fingerprint-Identification),
[SE-DCNet](https://github.com/maojinxiang/SE-DCNet)) *(verified: verdict 8)*.

Bonus content worth mining even without downloading the IQ: Table 4 of the paper gives measured
hop-block parameters per drone family (OcuSync-era Air 2S / Mini 3 Pro / Mavic 3 / M300 / M30T at
2.2 MHz hop-block bandwidth and 0.52 ms dwell; Mavic Pro / Mini 2 / P4P RTK / Avata at 1.1 MHz and
0.52 ms; Lightbridge-era P4P / M200 / M100 / Inspire 2 / M600 Pro at 1.2 MHz and 2.2 ms with 12 ms
nearest-hop spacing and a 14 ms video period at 68% duty; Avata video period 10 ms at 12% duty;
FrSky X20 0.42 MHz) ([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)). Those
feed [signal-reference.md](signal-reference.md) directly.

E200 fit: the richest multi-band and distance-labelled corpus available, but simultaneous 2.4 + 5.8
GHz capture cannot be reproduced on an E200, because the AD9361's two RX chains share one RX RFPLL
*(verified: verdict 1, `rf-ports`)*. Use RF0 and RF1 as separate single-band recordings, decimate
100 MS/s by 5 to 20 MSPS (or `resample_poly(7, 50)` for 14 MSPS work), and keep analysis windows below
0.1 s so the acquisition gaps never land inside a window.

### 1.6 DroneRFb-DIR (JEIT 2025)

| Field | Value |
|---|---|
| Paper | 任俊宇 / 俞宁宁 / 周成伟 / 史治国 / 陈积明 (Zhejiang University, Hangzhou Dianzi University, ZJU Jinhua Institute), JEIT 2025 47(3):573-581, [doi 10.11999/JEIT240804](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT240804); PDF at [sciengine](https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4) |
| Download | [SciDB dataSetId 84cf9101e739402784b1396783881202](https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202), registration required |
| Span and rate | 2.4 to 2.48 GHz (80 MHz span), 80 MSps ([rfml-moe-hub `datasets/droneRFb_dir.md`](https://github.com/r4d10n/rfml-moe-hub)) |
| Format | MATLAB v7.3 (HDF5) `.mat`, I and Q float32 arrays of shape (1, 4,000,000) = 50 ms per file; each class >= 40 segments of >= 4 M samples ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub), [SciDB listing](https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202)) |
| Classes | 13: 6 drone types x 2 training individuals plus a background class, with individual 3 of each type held out for test ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Signal types | FCS (flight control) and VTS (video transmission) per drone, LOS and NLOS, indoor and outdoor, with urban interference present ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub), [SciDB](https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202)) |
| Split sizes | 2177 train + 2513 test files ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Size | 64 GB compressed (32-part split zip), 65 GB extracted ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Benchmark | cross-individual (train individuals 1 and 2, test 3): ConvNeXt-Base 92.0%, MaxViT-Base 89.5%, hand-crafted statistical features 42.3%; at 7-type level ConvNeXt 94.2% ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub), self-reported) |

Caveats. Everything above except the SciDB id and the JEIT DOI comes from third-party notes; the
paper attribution itself is flagged as unverified by the hub author
([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)). The drone models behind types A to G are
not named in any source read.

E200 fit: this is the dataset that answers the question the toolkit actually cares about, namely
whether a classifier trained on our units generalises to somebody else's unit of the same model. The
80 MHz span is 1.4x the E200's window, so either decimate by 4 to 20 MSPS and accept the band edges,
or split the 80 MHz into two 40 MHz halves and treat them as separate observations, which is what an
E200 would have to do live anyway.

### 1.7 DRFF-R2 (2026)

| Field | Value |
|---|---|
| Source | [SciDB dataSetId b8a16448c1284fd1be1ded9ccc45be20](https://china.scidb.cn/), paper [arXiv:2603.00106](https://arxiv.org/abs/2603.00106) "A Multi-Scenario UAV RF Dataset with Real-World Acquisition"; all facts from [rfml-moe-hub `datasets/drffr2.md`](https://github.com/r4d10n/rfml-moe-hub) |
| Size | 400.6 GB, 730 `.mat` files; ~410 GB with derived spectrograms ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Units | 26 individual DJI airframes across 8 models: Mavic 3, Mavic 3C, Mavic 3S, Mavic Air 2, Mavic Air 2S, Mini 3 Pro, Mini 4 Pro, Mini 5 Pro ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Scenarios | 7 directories: single-drone flight states (cruise, ascend, descend, takeoff, landing, shading); mixed drones; hover; dual frequency; through RF-absorbing cotton; Wi-Fi mixed; environment ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Filenames | `<model>_<unit>_<state>.mat`, e.g. `mavic3_001_cruise.mat` ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Access | SciDB file-tree API (`POST /api/gin-sdb-filetree/public/file/childrenFileListByPath`) then per-file download with `username` and `traceId` set to a registered email; about 4 concurrent connections tolerated ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Sample rate | **not stated anywhere in the evidence** |

E200 fit: unknown until the sample rate is known. It is the only corpus that contains a **Mini 5 Pro**
and per-unit labels across flight states and interference conditions, so it is the natural test bed
for the O4-era work described in [landscape.md](landscape.md) section 1.2. Its scenario axis
(clean versus Wi-Fi mixed versus attenuated) is the cross-condition protocol our own recordings
should imitate.

### 1.8 S3R dataset (IEEE TIFS 2024)

| Field | Value |
|---|---|
| Code | [DaftJun/S3R](https://github.com/DaftJun/S3R), 42 stars |
| Data | [IEEE DataPort doi 10.21227/wv7h-sv64](https://dx.doi.org/10.21227/wv7h-sv64) plus a [Google Drive mirror](https://drive.google.com/file/d/1pdmxJmbM6aiMZlq6Hlr30PCeEewVL9oC/view) ([S3R](https://github.com/DaftJun/S3R)) |
| Format | DroneRFa-style: `T0101_D10_S0000.mat` with RF0/RF1 I and Q, fs = 100e6, channels 2440 and 5800 MHz ([S3R](https://github.com/DaftJun/S3R)) |
| Protocol | `experiment_groups` defines 9 known/unknown scenarios (I-VI and I-A/B/C) as lists of `./Data/<group>/<class>`; group 0 has 24 classes ([S3R](https://github.com/DaftJun/S3R)) |
| Reference STFT | 2048 bins, Hamming window, fs = 100e6, colour scale -80 to -20 dB (`raw2tfs/plt.py`) ([S3R](https://github.com/DaftJun/S3R)) |
| Citation | Yu, Wu, Zhou, Shi, Chen, IEEE TIFS 19:9894-9909, doi 10.1109/TIFS.2024.3463535 ([S3R](https://github.com/DaftJun/S3R)) |

The assignment brief listed this as "S3R / DroneRFb-Spectra". **No dataset named DroneRFb-Spectra
appears anywhere in the evidence**; only S3R and DroneRFb-DIR were found. Treat the name as
unconfirmed.

E200 fit: same 100 MS/s decimation as DroneRFa, and one loader serves both. The reason to take it is
the **open-set protocol**: nine predefined known/unknown splits, which is the only ready-made way to
evaluate "reject the drone model you have never seen" without inventing our own splits
([landscape.md](landscape.md) section 5.4).

### 1.9 RFUAV (Shi et al., 2025)

| Field | Value |
|---|---|
| Code | [kitoweeknd/RFUAV](https://github.com/kitoweeknd/RFUAV), Apache-2.0 (LICENSE read in the clone), 436 stars |
| Paper | [arXiv:2503.09033](https://arxiv.org/abs/2503.09033) ([repo README](https://github.com/kitoweeknd/RFUAV)) |
| Data | [Hugging Face kitofrank/RFUAV](https://huggingface.co/datasets/kitofrank/RFUAV); detection subset on [Roboflow](https://app.roboflow.com/rui-shi/drone-signal-detect-few-shot/models) ([repo README](https://github.com/kitoweeknd/RFUAV)) |
| Format | binary float32 interleaved I/Q `.iq`; ~763 MB per file = 1 s at 100 MSps; folders by VTS bandwidth 10 / 20 / 40 / 60 MHz ([rfml-moe-hub `datasets/rfuav.md`](https://github.com/r4d10n/rfml-moe-hub)) |
| Rate and centre | README examples use `sample_rate=100e6` and `Middle_Frequency=2400e6`; the third-party note gives USRP X310 at a 5.765 GHz centre. **Both cannot be the whole truth**; the per-clip XML is authoritative ([repo README](https://github.com/kitoweeknd/RFUAV), [rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| Per-clip XML | `DeviceType`, `Drone`, `SerialNumber`, `DataType`, `ReferenceSNRLevel`, `CenterFrequency`, `SampleRate`, `IFBandwidth`, `ScaleFactor` (dB) ([repo README section 3.1](https://github.com/kitoweeknd/RFUAV)) |
| Classes | 35 drone/RC types recorded; public subset = 37 raw clips plus images; configs cover 5, 7, 23 and 37 classes ([repo README](https://github.com/kitoweeknd/RFUAV)) |
| Named classes | includes Autel EVO Nano+, DJI Avata 2 / FPV Combo / Mavic 3 Pro / Mini 3 / Mini 4 Pro, FlySky EL18 and NV14, FrSky X14 and X9D+ 2019, Futaba T14SG / T16IZ / T18SZ, CubePilot Herelink v1.1, JR XG7 / XG14, Jumper T14 / T-Pro v2, RadioLink AT10 II, RadioMaster TX16S, SIYI FT24 / MK15 / MK32, SkyDroid H12, WFLY ET10 / WFT09SII, YunZhuo H16 / H30 ([rfml-moe-hub `datasets/rfuav.md`](https://github.com/r4d10n/rfml-moe-hub)) |
| Size | 102 GB compressed in 37 `.rar`, ~263 GB extracted, ~1.3 TB total raw claimed ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |
| SNR tooling | `SNREstimation/` with an `awgn1` MATLAB helper that iterates until the estimated SNR is within 0.1 dB of a target, stepping -20 to +20 dB in 2 dB steps (`NoisyData.m`, read in the clone) |
| Fingerprint definition | five parameters per drone: frequency-hopping signal bandwidth (FHSBW), hop duration (FHSDT), video-transmitted signal bandwidth (VSBW), hop duty cycle (FHSDC), hop pattern period (FHSPP) ([repo README](https://github.com/kitoweeknd/RFUAV)) |
| Licence | code Apache-2.0 (clone); **dataset licence on Hugging Face not verified** |
| Benchmarks | third-party 37-class reruns: MaxViT-Base 97.8% (118.7 M params), YOLOv11n-cls 97.4% (~1.6 M), MobileNetV3-Large 97.1% (4.2 M), raw-IQ LWMExpert 94.1% (1.3 M), statistical features + random forest 95.7%. The paper's own 5-class SNR-averaged figures: ViT-L-16 56.44% (98.55% at >= 10 dB), ResNet18 54.78% (99.93% at >= 10 dB) ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) |

E200 fit: 100 MSps is about 1.8x the E200's 56 MHz analog bandwidth and far beyond any streaming mode,
so it is training material only. The precedent already exists:
[RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker) resampled 131 RFUAV
recordings of 5 drone models with `resample_poly(2, 5)` to 40 MSPS, cut them into 2,621,440-sample
windows, rendered waterfalls and trained a YOLOv8n on them, reaching training mAP@0.5 of 0.995 but
only 0.2 to 0.7 confidence on live SDR data, which is why its threshold is set to 0.30
(`backend_rk3588/config.py`, `tools/build_and_train_yolo.py`, both read in the clone). That is the
domain-shift tax to budget for. The XML sidecar schema and the five-parameter fingerprint definition
are the most directly reusable design artefacts in the whole catalogue.

### 1.10 CageDroneRF / CDRF (Rowan University and AeroDefense, 2026)

| Field | Value |
|---|---|
| Toolkit | [DroneGoHome/U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB), MIT |
| Paper | Rostami, Faysal, Xia, Kasasbeh, Gao, Wang, [arXiv:2601.03302](https://arxiv.org/abs/2601.03302) (page not fetchable; citation block read from the repo) |
| Data access | request portal only: <https://aerodefense.tech/u-raptor-data-request>. No open download; **data licence unknown** ([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)) |
| Format | raw complex `.dat`; constants `SAMPLING_RATE 20e6`, `CENTER_FREQ 2.447e9`, `FFT 1024`, `RECORDING_TIME 15 s`; filenames `Manufacturer_Model_Bandwidth_FreqMHz_Mode` ([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)) |
| Bands | recordings at 905 MHz, 2.4 GHz and 5.8 GHz ([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)) |
| Environments | indoors, outdoors and in a shielded cage (tag `SR20M_G50_cage_RT15`), plus multi-drone mixes, laptop Wi-Fi video, 5G and environmental captures ([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)) |
| Models | 30 drone/RC models enumerated in the metadata: Autel EXO II, Autel X-Star, DJI FPV, Inspire 1, Inspire 2, Mavic 2 Pro, Mavic 3, Mavic Air, Mavic Mini 4, Mavic Pro, Mini 3, Phantom 4, Phantom 3 Adv, Tello, HolyStone HS110G and HS720E, Hubsan X4 Air, Parrot Anafi, KY601S, RadioMaster TX16S, Ruko F11GIM, Skydio 2, Yuneec Q500-HD, FreeFlight Alta X, plus `NoDrone` at 905 and 2442 MHz ([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)) |
| Windowing | 0.5 s windows with 0.1 s step; 19,487 windows in `temp_meta.json`, 76,632 in the YOLO metadata; tags include `armed`, `not_engaging`, `RC`, `vis` ([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)) |
| Synthetic variants | AWGN, Rayleigh and Rician at SNR -15 to +35 dB; test sets mix roughly 33% of each channel per SNR level; background class weighted 3x ([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)) |
| Capture hardware | **not stated in the repo** |

E200 fit: the closest of all the large corpora to E200 operating conditions. 20 MSPS complex
baseband is inside the AD9361's range and matches the vendor's 20 MSPS host figure exactly
([vendor RF table](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md))
*(verified: verdict 2)*, and the 905 MHz / 2.4 GHz / 5.8 GHz band set is the same scan plan an E200
node would run. Even before data access is granted, the MIT-licensed processing code (memory-mapped
`.dat` loader, filename metadata parser, SNR and fading test-set generator, signal-domain YOLO
augmentation in `src/yolo/augment_annotations.py`) is directly reusable
([repo](https://github.com/DroneGoHome/U-RAPTOR-PUB)).

### 1.11 Noisy Drone RF Signal Classification v1 and v2 (ZHAW / armasuisse)

| Field | Value |
|---|---|
| Loaders | v2 [sgluege/Noisy-Drone-RF-Signal-Classification-v2](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2); v1 [sgluege/Noisy-Drone-RF-Signal-Classification](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification); both GPL-3.0 (identical LICENSE md5 read in the clones) |
| Training code | [sgluege/Robust-Drone-Detection-and-Classification](https://github.com/sgluege/Robust-Drone-Detection-and-Classification), GPL-3.0 |
| Data | [Kaggle sgluege/noisy-drone-rf-signal-classification-v2](https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2); v1 at `sgluege/noisy-drone-rf-signal-classification`. **Dataset licence not verified** |
| Papers | v1: Glüge et al., NCTA 2023, doi 10.5220/0012176800003595 (PDF bundled in the v1 repo). v2: Glüge et al., IEEE J-RFID 8:821-830, 2024, doi 10.1109/JRFID.2024.3487303, [arXiv:2406.18624](https://arxiv.org/abs/2406.18624) |
| Recording | Ettus USRP B210 + LogPer antenna in an anechoic chamber at 56 MSPS, then decimated x4 to 14 MSPS with `scipy.signal.decimate` (8th-order Chebyshev I) (NCTA 2023 PDF sections 2.1-2.2, read in the clone) |
| Rate and centre | 14 MSPS complex, ~2.440 GHz; per-transmitter centres 2.44175 GHz (DJI, Futaba, Graupner, Noise), 2.440 GHz (Taranis), 2.445 GHz (Turnigy) (NCTA 2023 Table 1) |
| File schema | `IQdata_sample{X}_target{Y}_snr{Z}.pt`, a dict with `x_iq` float tensor (2, 1048576) [row 0 = I, row 1 = Q], `y` class index, `snr` in dB; plus `class_stats.csv` and `SNR_stats.csv` (`load_dataset.py` L26-38, read in the clone) |
| Window | 2^20 = 1,048,576 samples = 74.9 ms at 14 MSPS (`load_dataset.py` L209, L101) |
| Classes | 7: DJI (Phantom GL300F / Phantom 4 Pro), FutabaT14 (T14SG/R7008SB), FutabaT7 (T7C), Graupner (mx-16/GR-16), Noise, Taranis (ACCST/X8R), Turnigy 9X (confusion-matrix axes in `doc/img/cm_SNR-14.0.png`, class order from `eval_model_with_cm_per_SNR_cv5.py` L134-137) |
| SNR construction | drone burst located with a 256-sample moving-average energy threshold, normalised to carrier power 1 over burst samples; noise normalised to mean power 1; mixed as y = (sqrt(k) x + n) / sqrt(k+1) with k = 10^(SNR/10); SNR uniform over -20 to +30 dB in 2 dB steps, 679-685 samples per level; drone samples mixed 50% lab noise / 50% Gaussian (NCTA 2023 section 2.2 plus the Kaggle description, snippet) |
| Size | ~23 GB reported by the [rfml-moe-hub survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md); the deep read computes ~140-150 GB if the tensors are float32, so **the two do not agree** and the dtype was not verified |
| Baseline | VGG11_BN over five splits: test accuracy 0.9425 +/- 0.0066, balanced 0.9284 +/- 0.0034, ~5 min per epoch on an A100; weights on [Zenodo 14065652](https://zenodo.org/records/14065652) ([repo README](https://github.com/sgluege/Robust-Drone-Detection-and-Classification)) |
| v1 versus v2 | v1 used 16,384-sample vectors and 128x128 spectrograms; v2 uses 2^20-sample vectors and 1024x1024 spectrograms (NCTA PDF section 2.3 versus v2 code constants) |

Known flaws. The "5-fold CV" is five unseeded random stratified splits over windows drawn from
single anechoic-chamber recordings per class, so the folds overlap and the protocol is leaky
*(verified: verdict 8)*. The famous 0.842 versus 0.413 balanced accuracy at -12 dB (spectrogram
versus raw IQ) comes from the **v1/NCTA 2023 paper**, not from the 2024 J-RFID paper, and compares a
naive 1D VGG against the same VGG in 2D over an invertible transform of the same samples, so it
shows an inductive-bias effect rather than an information advantage; across all SNRs the gap is about
10 points and it is zero at SNR >= 0 dB *(verified: verdict 8)*. The SNR is defined as burst carrier
power over full-band (14 MHz) noise power, so "-12 dB" is roughly -1 to -5 dB in-band for a 1 to 3
MHz RC link and the number does not transfer to datasets with other spans *(verified: verdict 8)*.
GitHub issue #7 reports the model failing on a DJI Phantom 3 captured with a HackRF at 14 MHz, with
no maintainer reply ([repo issues](https://github.com/sgluege/Robust-Drone-Detection-and-Classification)).
The class set contains one old DJI link and five hobby RC transmitters: no OcuSync 2/3/4, no
ExpressLRS, no Crossfire, no 5.8 GHz video.

E200 fit: **the best fit in the catalogue on hardware grounds.** It was recorded on an AD9361-class
B210, at a rate the E200 can set natively, in a band the E200 covers, and 14 MSPS x 4 bytes = 56 MB/s
sits comfortably inside the streaming budget *(verified: verdict 2)*. Capture at 14 MSPS directly and
no resampling is needed; from 20 MSPS use `resample_poly(7, 10)`, from 15.36 MSPS `resample_poly(175, 192)`,
and from 56 MSPS `scipy.signal.decimate(x, 4)`, which reproduces the original chain exactly. The
model costs about 155.8 GMAC (~312 GFLOP) per 75 ms window with a 268 MB first-layer activation, so
it must be gated by an energy detector and cannot run on the Zynq ARM cores (computed layer by layer
in the deep read from `lib/model_VGG2D.py`). Note the licence: the code is GPL-3.0, so it may be
ported from its documented parameters but not vendored (see
[ADR-0003](../docs/decisions/ADR-0003-third-party-code-and-licences.md)).

### 1.12 UAVSig (UCLA CORES, 2024)

| Field | Value |
|---|---|
| Everything below | [rfml-moe-hub practitioner survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md), LLM-assisted and **unverified secondary**; the UCLA Dataverse page was unreachable |
| Content | 4 identical DJI Matrice 100 airframes plus controllers, 720 files |
| Capture | USRP B205mini, 50 MSps, 50 MHz bandwidth |
| Host | UCLA Dataverse |
| Downstream results | CV-YOLO (Zhao and Cabric 2025) 93.8% single-drone individual fingerprinting, 67.7% with two drones, 86.5% cross-temporal; CrossRF ([arXiv:2505.18200](https://arxiv.org/abs/2505.18200)) 99.03% cross-channel with adversarial domain adaptation versus 26.39% without |

E200 fit: the closest AD936x-class **individual**-fingerprinting corpus, since the B205mini uses an
AD9364. 50 MSPS is inside the AD9361's 61.44 MS/s range and can be captured as a snapshot but not
streamed *(verified: verdict 2)*. Four identical airframes is exactly the controlled setup needed to
test whether unit-level fingerprints survive our receiver. Its status is the weakest in this
catalogue: not one primary fact about it was verified.

### 1.13 NIST TN 2237 Wi-Fi / Bluetooth IQ

| Field | Value |
|---|---|
| Use | non-drone negative class in [TungAnhNguyen5/2_Stage_Drone_Detection_Model](https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model) |
| Format | `.h5` captures of Wi-Fi and Bluetooth at 2.4 and 5.8 GHz ([2-stage repo](https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model)) |
| Access | via a Kaggle mirror named `nist-wifi-bluetooth-iq` ([2-stage repo](https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model)) |
| Sample rate, size, licence | **not established by any source read** |

E200 fit: negatives only, but negatives are the scarcest resource in this catalogue. An urban
Netherlands node lives inside dense Wi-Fi and Bluetooth, and no drone dataset except DroneDetect and
CageDroneRF ships that interference as a labelled class.

### 1.14 LowSNR_DroneRF (Kaggle `laibatanveer/merged`) - a negative example

| Field | Value |
|---|---|
| Reproduction | [jainarein/LowSNR-DroneRF-Reproduction](https://github.com/jainarein/LowSNR-DroneRF-Reproduction) |
| Paper | Tanveer et al., IEEE A&E Systems Magazine, February 2026 ("From Lab to Field Trials: Real-Time Multimodel Drone Detection in Low-SNR Environments") ([reproduction repo](https://github.com/jainarein/LowSNR-DroneRF-Reproduction)) |
| Public file | ~3 GB, 137,557,132 rows ([reproduction repo](https://github.com/jainarein/LowSNR-DroneRF-Reproduction)) |
| Fatal flaws | the `IQSAMPLES` column holds non-negative power values, not complex IQ; only OFF and ARMED labels exist; the file is strictly ordered by class, with no segment IDs; the paper describes 3 s segments at 10 MHz sampling that are absent from the public file ([reproduction repo](https://github.com/jainarein/LowSNR-DroneRF-Reproduction)) |
| Reproduction gap | RF accuracy 83.99% versus the paper's 93%; AUC 0.927 versus 0.94; ANN 68.0% versus 75-76%; CNN 73.2% versus 75%; the paper's own Table 3 (75% CNN) and Table 6 (92.3% CNN) are mutually inconsistent ([reproduction repo](https://github.com/jainarein/LowSNR-DroneRF-Reproduction)) |

Do not use. It earns a place here because it defines the acceptance checks a dataset loader should
run before training anything: are the samples signed and complex, is there more than one label axis,
is the file ordered by class, and do segment identifiers exist.

### 1.15 DroneSecurity sample captures (RUB-SysSec, NDSS 2023)

| Field | Value |
|---|---|
| Repo | [RUB-SysSec/DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity), AGPL-3.0 (LICENSE added 2023-03-10, read in the clone) |
| Files | `samples/mini2_sm` 5,820,000 bytes = 727,500 complex64 = 14.55 ms at 50 MSPS with 10 bursts of ~640 us; `samples/mavic_air_2` 1,802,240 bytes = 225,280 complex64 = 4.51 ms with 3-4 bursts; both float32 interleaved IQ (byte counts measured on the clone) |
| Capture rate | 50 MSPS, dumped from the live receiver's detection stage (`inspectrum -r 50e6`) ([repo](https://github.com/RUB-SysSec/DroneSecurity)) |
| Ground truth | a scratch rerun reproduced the README exactly: `mini2_sm` gives 10 frame candidates, 9 decoded, 7 CRC OK; `mavic_air_2` gives 3 candidates and 1 CRC-OK "Mavic Air 2" frame at 51.44633 / 7.26722, height 12.8 (rerun logged in the deep read) |
| Format | raw complex, **not SigMF** ([repo](https://github.com/RUB-SysSec/DroneSecurity)) |

E200 fit: these two files are the only public DJI DroneID IQ ground truth found in the whole sweep,
and they are the acceptance test for any DroneID path on the E200. 50 MSPS is a snapshot rate on
this board, not a streaming rate *(verified: verdict 2)*. Note the AGPL-3.0 licence: the decoder must
be re-implemented from its description, not vendored
([ADR-0003](../docs/decisions/ADR-0003-third-party-code-and-licences.md)).

### 1.16 samples2djidroneid and proto17/dji_droneid: decoders, not datasets

[anarkiwi/samples2djidroneid](https://github.com/anarkiwi/samples2djidroneid) is Apache-2.0 and ships
**no IQ**: the repository contains only the Dockerised wrapper, `decode_djidroneid.py`, a patch for
proto17's `process_file.m`, and one screenshot named
`single_droneid_gain40_1_2429500000Hz_15360000sps.png`, whose filename encodes 2429.5 MHz at 15.36
MSPS (directory listing of the clone). Its input must be complex float32 at exactly 15.36e6 or
30.72e6 samples per second, because the FFT size must be a power of two equal to Fs / 15 kHz
([README](https://github.com/anarkiwi/samples2djidroneid)).

[proto17/dji_droneid](https://github.com/proto17/dji_droneid) recorded its DJI Mini 2 material with
an Ettus B205-mini (AD9364) at 30.72 MSPS but **does not publish the IQ**, stating the recordings
"likely contain GPS information" ([README](https://github.com/proto17/dji_droneid)). That is the
single most important logistical fact in this chapter for DroneID work: apart from the two
DroneSecurity files, every E200 DroneID test vector has to be recorded by us.

### 1.17 RTL-ML (out of scope, listed for completeness)

800 samples, 6.2 GB, NumPy `.npy` dictionaries, 1.024 MSps from an RTL-SDR Blog V4, seven VHF/UHF
classes (FM broadcast, NOAA, APRS, pager, ISM sensors, FRS/GMRS, noise), MIT licence, hosted at
`TrevTron/rtl-ml-dataset` on Hugging Face
([rfml-moe-hub `datasets/rtl_ml.md`](https://github.com/r4d10n/rfml-moe-hub)). It contains no drone
signals. It appears in the hub's benchmark tables, so any cross-dataset number quoted from that hub
must be checked for which dataset it refers to; statistical features hit 100% on RTL-ML's 800
samples and 42.3% on DroneRFb-DIR cross-individual
([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)).

### 1.18 Derived and re-published sets (spectrograms and tensors, not raw IQ)

| Set | Contents | Source |
|---|---|---|
| DroneRFA_24-Dataset | 24-class (background + 23 drone types) spectrogram subset built from DroneRFa, with the generating script (h5py segment reader + STFT) and the original JEIT PDF; demo CNN and ResNet18 weights; class codes T0000-T1111 and T10000-T11000 | [maojinxiang/DroneRFA_24-Dataset](https://github.com/maojinxiang/DroneRFA_24-Dataset) |
| drone-rf-id processed set | 4,540 128x128 STFT spectrograms from DroneRF: Background 820, Bebop 1,680, AR Drone 1,620, Phantom 420; preprocessing 10 chunks of 1e6 samples per CSV, n_fft 512, hop 2048; MIT code | [song-lalala/drone-rf-id](https://github.com/song-lalala/drone-rf-id) |
| RF-UAVNet / MATLAB DroneRF | a normalised and reorganised copy of DroneRF for detection, type and mode tasks; IQT reimplementation reaches 0.998 binary accuracy | [ThienHuynhThe/RF-based-Drone-Surveillance-with-DL](https://github.com/ThienHuynhThe/RF-based-Drone-Surveillance-with-DL), [IQTLabs/RFClassification](https://github.com/IQTLabs/RFClassification) |
| ZHAW model weights | VGG11_BN weights and per-SNR evaluation artefacts | [Zenodo 14065652](https://zenodo.org/records/14065652); licence not verified |
| RFUAV detection subset | curated few-shot spectrogram detection set | [Roboflow](https://app.roboflow.com/rui-shi/drone-signal-detect-few-shot/models) |

These are convenient but they lock in somebody else's STFT parameters and split policy. Use them for
sanity checks, never as the basis of a reported number.

### 1.19 Chinese-language aggregation pages, unfetched

* [gitcode.csdn.net/6a2459d5662f9a54cb7ac49a](https://gitcode.csdn.net/6a2459d5662f9a54cb7ac49a.html) -
  「无人机射频侦测开源数据集汇总」, a continuously updated Chinese roundup of open drone-RF datasets
  (blocked domain, contents unverified). This is the single most likely place to find a Chinese
  dataset this catalogue has missed.
* [JEIT dataset column](https://jeit.ac.cn/web/data/getData?dataType=Dataset1) - all JEIT-published
  drone RF datasets have moved to SciDB and require registration; the column also links the ZJU ISEE
  announcement of the DroneRFa release
  (<http://www.isee.zju.edu.cn/2024/0708/c21123a2944315/page.htm>).
* VTI_DroneSET - named only in the practitioner survey, used with a USRP-2954 and Jetson Orin NX by
  FLEDNet (MDPI Drones 9(243), 2025), with no download location given
  ([survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md),
  unverified secondary).

No NUAA (Nanjing University of Aeronautics and Astronautics) drone-RF dataset could be located, and
whether one exists publicly is unknown. See [foreign-perspective.md](foreign-perspective.md) for what
the Chinese and Russian community sources contribute elsewhere.

---

## 2. Which datasets to use first for an E200 toolkit, and why

The selection criteria, in order: (a) does it contain complex baseband IQ, (b) was it captured at a
rate the E200 can reach, (c) does it carry the labels the toolkit actually needs (SNR, interference
condition, unit identity, background), (d) can we get it at all.

**Tier 0, start here, this week.**

1. **DroneSecurity's two sample files** ([RUB-SysSec/DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity)).
   7.6 MB total, in the repo, with a reproducible expected output (10 candidates, 9 decoded, 7 CRC OK
   on `mini2_sm`; 1 CRC-OK frame on `mavic_air_2`). They make the DroneID path testable before the
   E200 has recorded anything, and they are the regression fixture for
   [ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md).
2. **Noisy Drone RF v2** ([Kaggle](https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2),
   loader at [sgluege/Noisy-Drone-RF-Signal-Classification-v2](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2)).
   The only corpus recorded on AD9361-class hardware at a rate the E200 sets natively (B210, 14 MSPS,
   2.440 GHz), with explicit per-sample SNR labels from -20 to +30 dB in 2 dB steps and a documented
   normalisation. It gives the toolkit its first end-to-end classifier and, more importantly, its
   first honest per-SNR curve. Download a handful of `.pt` files first to test the front end, since
   the full size is disputed (23 GB reported versus ~140 GB computed).

**Tier 1, the first real training set.**

3. **RFUAV** ([Hugging Face](https://huggingface.co/datasets/kitofrank/RFUAV)). 37 modern drone and
   RC classes including Avata 2, Mini 4 Pro, Mavic 3 Pro, SIYI, Herelink, RadioMaster and Jumper,
   which is the only public set whose class list resembles what actually flies over the Netherlands
   in 2026. Resample 100 MSPS by `resample_poly(2, 5)` to 40 MSPS as RF-Vision did, or by 5 to 20
   MSPS to match the E200 streaming tier
   ([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). Take the 5-class or
   7-class config first; the 37-class problem is not the toolkit's problem yet. Budget 102 GB of
   download and ~263 GB extracted ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)).
4. **CageDroneRF** ([request portal](https://aerodefense.tech/u-raptor-data-request)). Request access
   now, because the portal is a human process and the data is worth waiting for: 20 MSPS complex at
   905 MHz, 2.4 GHz and 5.8 GHz, 30 models, indoor/outdoor/cage, multi-drone mixes, and explicit
   non-drone recordings (laptop Wi-Fi video, 5G, environment). In the meantime clone the MIT toolkit
   and reuse its loader and augmentation code
   ([U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB)).

**Tier 2, for the questions that decide whether any of this works in the field.**

5. **DroneRFb-DIR** ([SciDB](https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202))
   for cross-individual generalisation. This is where hand-crafted statistical features collapse from
   100% to 42.3% while ConvNeXt-Base holds 92.0%
   ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)). If the toolkit ever claims to recognise
   a drone *model*, this is the dataset that tests the claim honestly.
6. **S3R** ([IEEE DataPort 10.21227/wv7h-sv64](https://dx.doi.org/10.21227/wv7h-sv64)) for the
   open-set protocol: nine ready-made known/unknown splits in DroneRFa format, so one loader covers
   S3R, DroneRFa and the DroneRFA_24 subset ([DaftJun/S3R](https://github.com/DaftJun/S3R)).
7. **DroneDetect** ([IEEE DataPort](https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine))
   and **NIST TN 2237** ([via 2_Stage_Drone_Detection_Model](https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model))
   for false-alarm rejection: CLEAN / BLUE / WIFI / BOTH conditions and real Wi-Fi and Bluetooth
   negatives at 2.4 and 5.8 GHz.

**Tier 3, reference and regression only.** DroneRF (binary detection fixture, everything above binary
is leakage-inflated *(verified: verdict 8)*), CardRF and the Ezuma controller set (transient
fingerprint theory, unusable as IQ), DRFF-R2 (400 GB, unknown sample rate, revisit when the arXiv
paper is readable), UAVSig (entirely unverified, request it if the Dataverse becomes reachable).

**Explicitly not worth toolkit time.** LowSNR_DroneRF (no IQ, broken labels), RTL-ML (no drones),
and any pre-rendered spectrogram redistribution used as a primary training source.

Two structural warnings that follow from the catalogue rather than from any one dataset. First, no
public corpus contains ExpressLRS, Crossfire, HDZero, Walksnail or WFB-NG traffic, which is most of
what a European hobbyist and most of what a non-DJI airframe actually transmits (see
[landscape.md](landscape.md) sections 3 and 4). Everything in this catalogue is DJI-heavy plus legacy
2.4 GHz FHSS controllers. Those classes will only exist if we record them. Second, nothing here was
recorded in the Netherlands, in an urban EU spectrum environment, on our antennas, with our receiver.
The measured cost of that mismatch is the RF-Vision result: mAP@0.5 of 0.995 in training, 0.2 to 0.7
confidence live ([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). Public
data buys a starting model, not a working one, which is why
[ADR-0007](../docs/decisions/ADR-0007-detection-pipeline-heuristics-before-ml.md) puts protocol-level
heuristics ahead of the classifier.

---

## 3. How to record our own dataset so it is comparable

Comparable means three things: another person can read the files without our code, our own numbers
can be compared across sessions, and a model trained on our data can be evaluated against the public
benchmarks without silently changing the protocol.

### 3.1 Container and metadata

Write SigMF, as decided in [ADR-0002](../docs/decisions/ADR-0002-sigmf-recordings.md): `.sigmf-data`
in `cf32_le` plus `.sigmf-meta`, with readers also accepting `ci16_le` and `ci8` because that is what
the AD9361 delivers natively. Bursts and ground truth go in SigMF annotations using
`core:sample_start`, `core:sample_count`, `core:freq_lower_edge`, `core:freq_upper_edge` and
`core:label`. The reference reader/writer is
[sigmf-python](https://github.com/sigmf/sigmf-python), and annotated recordings can be reviewed in
[IQEngine](https://github.com/iqengine/iqengine) or inspectrum, which is what
[IQTLabs/rfml](https://github.com/IQTLabs/rfml) recommends.

On top of the SigMF core fields, carry the per-capture parameters that the public datasets found
necessary. RFUAV's XML sidecar is the most complete published schema and every field has an obvious
SigMF home ([RFUAV README section 3.1](https://github.com/kitoweeknd/RFUAV)):

| RFUAV field | Meaning | What we record |
|---|---|---|
| `DeviceType` | acquisition device | `ANTSDR E200`, AD9361 or AD9363 variant, firmware personality (IIO or UHD) and version |
| `Drone` | drone type/model | model string plus airframe **unit id**, see 3.4 |
| `SerialNumber` | data pack serial | capture session id |
| `DataType` | raw data type | `cf32_le` / `ci16_le` |
| `ReferenceSNRLevel` | SNR of the drone packet | measured SNR with the convention stated, see 3.3 |
| `CenterFrequency` | centre of the capture | AD9361 LO in Hz |
| `SampleRate` | sample rate | Hz |
| `IFBandwidth` | bandwidth of the packet | `rx_rf_bandwidth` and, per annotation, the measured occupied bandwidth |
| `ScaleFactor` | hardware amplification in dB | AD9361 gain-control mode and gain in dB, plus any external LNA |

Add the fields no public dataset carries but every one of them needed after the fact: UTC time and
clock discipline (the E200 accepts an external 10 MHz or PPS reference through `ad5660mp`, see
[hardware-e200.md](hardware-e200.md)), antenna and port (SMA RX1 versus the u.FL RX2 pair, since only
RX1 is on SMA *(verified: verdict 1, `rf-ports`)*), geometry (range, LOS or NLOS, indoor or outdoor,
as DroneRFa and DroneRFb-DIR both do), and the interference condition in DroneDetect's vocabulary
(CLEAN / BLUE / WIFI / BOTH) ([RFClassification](https://github.com/IQTLabs/RFClassification)).
Encode the same information in the filename as well, the way every usable dataset does:
DroneRFa uses `T<type>_D<distance>_S<segment>`
([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)), CageDroneRF uses
`Manufacturer_Model_Bandwidth_FreqMHz_Mode`
([U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB)), and ZHAW uses
`IQdata_sample{X}_target{Y}_snr{Z}.pt`
([load_dataset.py](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2)). Redundancy
between filename and metadata is what saves a corpus when one of the two is lost.

Auto-annotation should not be hand-written. [IQTLabs/rfml](https://github.com/IQTLabs/rfml)'s
`annotation_utils.annotate()` already takes `avg_window_len`, `power_estimate_duration`,
`force_threshold_db`, `bandwidth_estimation` (Gaussian mixture or a float threshold),
`annotation_seconds`, `bandwidth_limits`, `set_bandwidth`, `dc_block` and `fft_len`, and writes
`.sigmf-meta` directly. For hopping links, [sandialabs/gr-fhss_utils](https://github.com/sandialabs/gr-fhss_utils)
provides `fft_burst_tagger` (per-bin dynamic noise floor over `history_size` FFTs, `threshold` dB,
`lookahead`, `burst_pre_len`, `burst_post_len`), `cf_estimate` and a `sigmf_meta_writer`; it is
GPL-3.0-or-later, so run it as a separate process rather than vendoring it
([ADR-0003](../docs/decisions/ADR-0003-third-party-code-and-licences.md)).

### 3.2 Sample rates and window lengths

Pick rates that both the E200 sustains and the public tooling accepts, so the same recording can be
replayed into more than one decoder:

| Rate | Why | E200 tier |
|---|---|---|
| 14 MSPS | matches Noisy Drone RF v2 exactly, no resampling ([load_dataset.py](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2)) | continuous on both personalities |
| 15.36 MSPS | minimum DroneID rate: FFT = Fs / 15 kHz must be a power of two; accepted by samples2djidroneid ([README](https://github.com/anarkiwi/samples2djidroneid)) | continuous on UHD, tuned IIO only *(verified: verdict 2)* |
| 20 MSPS | vendor host figure and CageDroneRF's native rate ([vendor table](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md), [U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB)) | continuous on UHD *(verified: verdict 2)* |
| 30.72 MSPS | proto17's DroneID recording rate on a B205-mini ([README](https://github.com/proto17/dji_droneid)) | snapshot, or sc12/sc8 experiment *(verified: verdict 2)* |
| 40 MSPS | RF-Vision's snapshot rate on Zynq-7020 + AD9364; RFUAV resamples to it ([RF-Vision](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)) | snapshot only, 25-40% duty cycle *(verified: verdict 2)* |
| 50 MSPS | DroneSecurity's capture rate and UAVSig's rate ([DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity)) | snapshot only |

Window lengths. The published consensus is 75 to 100 ms, and it comes from four independent places:
ZHAW uses 1,048,576-sample windows = 74.9 ms at 14 MHz
([load_dataset.py](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2)); DroneRFa
states drone periodicity is fully visible within 0.1 s and its own baseline uses 1e6-sample (10 ms)
windows, with accuracy falling from 97.73% to 72.7% when the window is cut to 256 k samples
([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)); CageDroneRF samples 0.5 s
windows at 0.1 s steps ([U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB)); and RF-Vision
buffers 2,621,440 samples = 65.5 ms at 40 MSPS per burst, with 524,288 samples = 13.1 ms for the RSSI
pre-scan ([RF-Vision](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). So: **capture buffers of at
least 100 ms**, analysis windows of 10 to 75 ms, and a short pre-scan window for the energy gate.
Note the DroneRFa constraint in reverse: because its acquisition breaks every 0.1 s, any window
length we choose above 0.1 s makes our data incomparable with it
([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)). DroneID needs far less:
a burst is 9 OFDM symbols, 9880 samples = 643.2 us at 15.36 MSPS, repeating about every 600 ms
([proto17 README](https://github.com/proto17/dji_droneid),
[DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity)), so a DroneID dwell is a timing problem,
not a window-length problem. The claim that O3/O4 links show ~5 ms periodicity on a Mini 5 Pro is an
**unverified round-1** finding (`ocusync-phy`) and must not be used to size windows until checked.

### 3.3 SNR annotation

State the convention or the number is meaningless. ZHAW defines SNR as burst carrier power over
full-band noise power at the configured 14 MHz span, which means "-12 dB" is roughly -1 to -5 dB
in-band for a 1 to 3 MHz RC link *(verified: verdict 8)*. Publish both: **in-band SNR** over the
measured occupied bandwidth of the annotated burst, and **full-band SNR** at the capture's sample
rate, with the sample rate recorded next to them. Never compare an SNR figure across datasets with
different spans.

For synthetic SNR sweeps, two documented recipes exist and they disagree in a way worth preserving.
ZHAW normalises the drone vector to carrier power 1 over burst samples only (burst located with a
256-sample moving-average energy threshold), normalises the noise vector to mean power 1, and mixes
as y = (sqrt(k) x + n) / sqrt(k+1) with k = 10^(SNR/10), sweeping -20 to +30 dB in 2 dB steps with
half lab noise and half Gaussian (NCTA 2023 section 2.2, verified from the PDF in the
[v1 repo](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification)). RFUAV instead estimates
the SNR already present in a clip and iteratively adds AWGN until the estimate is within 0.1 dB of a
target, stepping -20 to +20 dB in 2 dB steps (`SNREstimation/NoisyData.m`, read in the clone).
CageDroneRF goes further and mixes channel models, roughly a third each of AWGN, Rayleigh and Rician
per SNR level from -15 to +35 dB, weighting the background class 3x
([U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB)). Adopt the ZHAW mixing equation
(it is the only one written down as an equation), sweep RFUAV's range, and add the CageDroneRF fading
mix as a second axis. Crucially, **use recorded background rather than Gaussian noise** wherever
possible: our own 2.4 and 5.8 GHz urban background at several AD9361 gain settings is a resource no
public dataset has for our environment.

The evidence on why this matters is unambiguous. On DroneRF, compact CNN and ResNet-18 accuracy falls
to 37.1% and 21.9% at -5 dB without noise injection and recovers to 76.5% and 81.1% with random-SNR
training over -5 to +20 dB at p_clean 0.2 ([drone-rf-id](https://github.com/song-lalala/drone-rf-id)).
Clean training simply does not survive the field.

### 3.4 Splits: by session and by unit, never by window

This is the single most consequential protocol decision, and the verified evidence is unusually
sharp. Under leave-one-recording-out, DroneRF type identification falls from macro-F1 0.742 to 0.455,
which is chance ([arXiv 2607.01025](https://arxiv.org/abs/2607.01025)) *(verified: verdict 8)*. The
inflation is capacity-dependent: small models lose 0 to 3 points, high-capacity models lose
everything, because they memorise the recording-to-label map when the number of independent
recordings is small ([dronerf-emi-robustness](https://github.com/greenbeanss/dronerf-emi-robustness),
[arXiv 2607.01025](https://arxiv.org/abs/2607.01025)) *(verified: verdict 8)*.

Rules for our recorder and our evaluation harness:

1. **Recording-level grouped partitions.** Every source recording is assigned in its entirety to
   train, validation or test *before* any windowing, with several rotations; that is exactly what
   [dronerf-emi-robustness](https://github.com/greenbeanss/dronerf-emi-robustness) implements (5
   rotations) and what the toolkit should copy.
2. **Unit-level held-out sets.** Record more than one airframe of at least one model and hold one
   unit out entirely, which is the DroneRFb-DIR protocol (train individuals 1 and 2, test individual
   3) ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)). Without this, a "model classifier" is
   an unfalsifiable claim.
3. **Session-level held-out sets**, meaning a different day, location and antenna orientation. CV-YOLO
   reports 93.8% single-drone individual fingerprinting but 86.5% cross-temporal
   ([survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md),
   unverified secondary), and CrossRF on UAVSig goes from 26.39% to 99.03% cross-channel only with
   adversarial domain adaptation (same source). Time and channel are separate axes from unit
   identity.
4. **One receiver per class is a bug.** CFO, DC offset and noise floor correlate with capture
   hardware, so a class collected only on one radio is partly a hardware label
   ([2_Stage_Drone_Detection_Model](https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model)).
   If a second SDR is available, record part of every class on it.
5. **Report per-SNR balanced accuracy**, not a single accuracy. RFUAV scores every model at each SNR
   from -20 to +20 dB in 2 dB steps ([RFUAV](https://github.com/kitoweeknd/RFUAV)); ZHAW exports
   `acc_per_SNR.csv` and per-SNR confusion matrices down to -14 dB
   ([Robust-Drone-Detection-and-Classification](https://github.com/sgluege/Robust-Drone-Detection-and-Classification)).
   A single number hides exactly the regime the toolkit operates in.
6. **Include an open-set test.** S3R's nine known/unknown groups are the ready-made protocol
   ([DaftJun/S3R](https://github.com/DaftJun/S3R)); rfml-moe-hub's `evaluation/openset.py` implements
   OpenMax with Weibull fits if we need an implementation
   ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)).

### 3.5 Classes to record, including the ones that are not drones

Record background and interference as first-class labelled classes, not as leftovers. The public
precedent: DroneRFa's background class explicitly contains Bluetooth and Wi-Fi
([JEIT 230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)); DroneDetect encodes
CLEAN/BLUE/WIFI/BOTH per capture ([RFClassification](https://github.com/IQTLabs/RFClassification));
CardRF ships five Bluetooth and two Wi-Fi devices
([mirror](https://github.com/Marchev-Science/case-drone-signature-classification)); CageDroneRF
includes laptop Wi-Fi video, 5G and environmental recordings plus a `NoDrone` class at 905 and 2442
MHz ([U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB)); and IQTLabs recommends collecting
isolated signals in a foil-lined Pelican-case Faraday enclosure *and* adding a background
"environment" class ([rfml](https://github.com/IQTLabs/rfml)). RF-Vision's own report concedes that
Wi-Fi is expected to pass its YOLO stage because there were no Wi-Fi, 4G or 5G negatives in training
([RF-Vision](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). For an urban Dutch node this is the
difference between a usable detector and an alarm generator.

The classes no public dataset covers, and which therefore only exist if we record them: ExpressLRS
(2.4 GHz and 868/915 MHz), TBS Crossfire, HDZero, Walksnail Avatar, WFB-NG/OpenHD, and O4-era DJI
links (see [landscape.md](landscape.md) sections 1 to 4 and
[signal-reference.md](signal-reference.md)).

### 3.6 Validate by replay before trusting anything

Two published methods, both cheap. [rameyjm7/rf-signal-intelligence](https://github.com/rameyjm7/rf-signal-intelligence)
replays labelled Noisy Drone RF v2 IQ from a bladeRF, receives it on a HackRF and classifies it,
getting 68 of 70 exact class matches over seven classes at SNR >= 20 dB against 0.9769 natural and
0.9803 balanced offline accuracy; that measures the receiver chain end to end. RF-Vision's mock
transmitter does the same with a PlutoSDR at 40 MSPS, `tx_rf_bandwidth` 20 MHz, gain -10 dB, cyclic
buffer, 400,000-sample chunks resampled 2:5 and scaled to 32700, hopping 5745/5785/5825 MHz with a
2000 ms dwell and 10% dither ([RF-Vision](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). Note
that transmitting is out of scope for AERIX operationally
([ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md)); replay validation belongs in a
shielded enclosure with a second radio, and only there.

Then run the loader acceptance checks that LowSNR_DroneRF failed: samples must be signed and complex,
labels must have more than one axis, files must not be ordered by class, and segment or session
identifiers must exist ([LowSNR-DroneRF-Reproduction](https://github.com/jainarein/LowSNR-DroneRF-Reproduction)).

### 3.7 Storage budget

For scale: 20 MSPS in `cf32_le` is 160 MB/s, so 100 ms is 16 MB and one 15 s CageDroneRF-style
recording is 2.4 GB; in `ci16_le` those halve. RFUAV's 1 s at 100 MSps float32 is ~763 MB per file
([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)). This is why every large corpus in this
catalogue is measured in hundreds of gigabytes and why the toolkit should record short annotated
snapshots around detections rather than continuous streams
([ADR-0002](../docs/decisions/ADR-0002-sigmf-recordings.md)).

---

## 4. Wanted downloads

`wanted_downloads` was populated only by the round-2 lenses; the dataset lens itself recorded none,
so the dataset entries below are lifted from the Chinese lenses plus the access notes in the
catalogue. Priority 1 means it blocks work now.

| Pri | Item | Why | Access note |
|---|---|---|---|
| 1 | [Noisy Drone RF v2](https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2) | first E200-native classifier and per-SNR baseline | Kaggle CLI; confirm dataset licence and real size (23 GB reported versus ~140 GB computed) |
| 1 | [DroneRFb-DIR on SciDB](https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202&version=V1&code=j00173) plus the [paper PDF](https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4) | only cross-individual fingerprint benchmark; PDF should give the SDR model and drone identities | SciDB registration, 32-part zip, 64 GB |
| 1 | [CageDroneRF data request](https://aerodefense.tech/u-raptor-data-request) | 20 MSPS, 905/2.4/5.8 GHz, 30 models, cage and outdoor, non-drone classes | human request process, start early; licence unknown |
| 1 | [RFUAV on Hugging Face](https://huggingface.co/datasets/kitofrank/RFUAV) | modern 37-class training material and per-clip XML | 102 GB in 37 rar; **check the dataset licence on the HF page**, it was never verified |
| 2 | [DroneRFa on SciDB](https://www.scidb.cn/en/detail?dataSetId=34f0a91e8a544904998b8fdc44477380) | multi-band, distance-labelled, 24 classes; re-cut into 20 MHz sub-bands for E200 training | SciDB registration; ~574 GB single RAR mirror |
| 2 | [gitcode roundup of Chinese drone-RF datasets](https://gitcode.csdn.net/6a2459d5662f9a54cb7ac49a.html) | cross-check this catalogue for Chinese-only datasets we missed | blocked domain, fetch by hand |
| 2 | [DroneDetect on IEEE DataPort](https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine) | interference-condition labels; confirm the BladeRF variant | DataPort account |
| 2 | [S3R dataset](https://dx.doi.org/10.21227/wv7h-sv64) or its [Drive mirror](https://drive.google.com/file/d/1pdmxJmbM6aiMZlq6Hlr30PCeEewVL9oC/view) | open-set splits in DroneRFa format | DataPort account |
| 2 | [DRFF-R2 paper arXiv:2603.00106](https://arxiv.org/abs/2603.00106) | establish sample rate and receiver before committing 400 GB of download | arXiv blocked in the sweep |
| 2 | CardRF primary page (URL never captured; work from the [mirror](https://github.com/Marchev-Science/case-drone-signature-classification)) and the [Ezuma RC dataset](https://ieee-dataport.org/open-access/drone-remote-controller-rf-signal-dataset) | resolve the "17 controllers" contradiction in section 1.3 | DataPort account |
| 3 | [UAVSig on UCLA Dataverse](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md) (exact URL not captured) | AD9364-class individual fingerprinting, 4 identical M100 | find the Dataverse record; every fact about it is unverified |
| 3 | NIST TN 2237 (Kaggle mirror `nist-wifi-bluetooth-iq`) | Wi-Fi and Bluetooth negatives at 2.4 and 5.8 GHz | establish the primary NIST publication and licence |
| 3 | [Zenodo 14065652](https://zenodo.org/records/14065652) | ZHAW VGG11_BN weights for a zero-training baseline | check the record's licence before redistributing |

The full cross-lens wish list, including the Chinese and Russian community pages and the FCC filings
for [signal-reference.md](signal-reference.md), is at the end of [sources.md](sources.md).

---

## Gaps

What the evidence could not establish, drawn from the lens `gaps_or_open_questions` and the verdicts:

* **Every non-GitHub dataset host was unreachable.** IEEE DataPort, Mendeley, Zenodo, Kaggle, SciDB,
  jeit.ac.cn, Hugging Face, arXiv, PapersWithCode and UCLA Dataverse were all egress-blocked, and the
  WebSearch budget (200/200) was exhausted before the dataset lens started. DroneDetect, CardRF, the
  Ezuma controller set, UAVSig, VTI_DroneSET, DroneRFb-DIR and DRFF-R2 therefore rest on third-party
  GitHub notes. Their primary pages, licences and exact sizes are unverified.
* **Licences.** RFUAV's dataset licence on Hugging Face, CageDroneRF's data-use terms, the Kaggle
  licence for both ZHAW datasets, the Zenodo weights licence, and DroneRF's CC BY 4.0 claim (taken
  from a third-party README, not the Mendeley page) are all unconfirmed.
* **Capture hardware.** The SDR model is unknown for DroneRF (an NI USRP driven by LabVIEW, model not
  in the repo), DroneDetect (a BladeRF, variant unstated), CageDroneRF (nothing stated) and
  DroneRFb-DIR ("SDR"). RFUAV's USRP X310 and UAVSig's B205mini come from third parties only. The
  AD9361-equivalence arguments for DroneDetect and UAVSig therefore rest on second-hand statements.
* **DRFF-R2's sample rate, centre frequencies and bandwidth are unknown**, so its E200 compatibility
  cannot be assessed at all.
* **Contradictions left standing.** DroneRF size 3.75 GB versus ~40 GB; Noisy Drone RF v2 size ~23 GB
  reported versus ~140-150 GB computed from the file schema (dtype unverified); DroneRFa described as
  100 MS/s with 80 MHz IBW by the paper but "80 MSps" by rfml-moe-hub; RFUAV centred at 2.4 GHz per
  its README examples but 5.765 GHz per rfml-moe-hub; CardRF listed as "17 controllers, 8
  manufacturers" by the survey while its own README lists six UAVs, five Bluetooth and two Wi-Fi
  devices. None of these could be resolved from a primary source.
* **No dataset named "DroneRFb-Spectra" was found** anywhere in the evidence, only S3R and
  DroneRFb-DIR.
* **No public SigMF-formatted UAV dataset exists** in anything the sweep could reach. IQT Labs'
  `rfml` pipeline uses SigMF but its Mavic 3, Mini 2 and bladeRF Wi-Fi collections are not published,
  and gamutRF (archived) links no datasets. Our recordings would be among the first.
* **No Wi-Fi-layer drone dataset** (pcap or 802.11 traffic from Parrot or DJI Wi-Fi drones) was found;
  only Wi-Fi-as-interference IQ (NIST TN 2237, DroneDetect, CardRF, CageDroneRF).
* **No dataset contains ExpressLRS, Crossfire, HDZero, Walksnail or WFB-NG**, and none was recorded in
  an EU urban environment. Both gaps can only be closed by our own recording.
* **No NUAA drone-RF dataset could be located**, and whether one exists publicly is unknown. The
  Chinese aggregation page at gitcode was never fetched, so Chinese-only datasets may be missing from
  this catalogue entirely.
* **RFUAV's per-drone centre frequencies and SNR levels** could not be read (the abstract figure is
  too low-resolution), and its exact per-class recording counts are unknown.
* **DroneDetect's V2 directory structure and class definitions** are known only through the IQT
  loader, not the dataset documentation.
* **The SigMF core specification itself was not fetched.** The field names used in section 3.1 come
  from the project's own [ADR-0002](../docs/decisions/ADR-0002-sigmf-recordings.md) and from
  repositories that write SigMF, not from the specification text; confirm against the spec and
  [sigmf-python](https://github.com/sigmf/sigmf-python) before freezing the recorder's schema.
* **Two round-1 claims remain unverified** and are flagged wherever used: the E200 O4 DroneID
  firmware channel set (`o4-firmware-channels`) and the OcuSync PHY summary including the ~5 ms
  O3/O4 periodicity figure (`ocusync-phy`). Neither should size a capture window or a dwell schedule
  until checked.
