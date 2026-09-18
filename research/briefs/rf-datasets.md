# Brief: Public RF/IQ datasets for AERIX RF

**Question.** What public RF/IQ drone datasets exist, what do they actually
contain, what state are they in on disk/access, and which AERIX workstream
(detection, classification/fingerprinting, protocol decode, localization)
does each one actually serve?

**Status of this brief.** Continuation of an interrupted librarian pass
(2026-09-18). Local downloads are still in progress at time of writing — see
`bash ~/rf-datasets/manifests/status.sh` for live state, not the numbers
below. Full machine-readable catalog: `research/datasets/manifest.json`.
Manual-access steps: `research/datasets/USER_TODO.md`.

## Confidence discipline

Every technical claim below is one of: (a) read directly from a primary
source this pass, (b) carried over from a prior pass's corpus pointer
(marked as such), or (c) inferred from search-result summaries only (marked
"unverified" — do not build code assumptions on these without reading the
actual paper/dataset card first).

## Dataset table

| Dataset | Year | Access | Format | Bands | #devices | Approx. size | AERIX relevance | Confidence |
|---|---|---|---|---|---|---|---|---|
| DroneRF (Mendeley f4c2b4n755) | 2019 | open | raw RF time-domain, .rar | 2.4 GHz | 3 drones | 4.0 GB | detection/classification baseline, low realism | High (local, complete, verified vs file list) |
| DroneRFa (SciDB) | 2023 | open (unverified this pass) | raw, not confirmed | 915MHz/2.4/5.8 GHz | multi-drone + WiFi/BT | ~570 GB (corpus pointer, unverified) | best multi-band open-set detection candidate found | Medium (search summary only) |
| DroneRFb-DIR (SciDB) | 2025 | open, direct URL | raw IQ, zip | 2.4-2.48 GHz | 6 types x 3 individuals | ~64 GB | individual-emitter fingerprinting (unique among these) | Medium (download in progress, paper not read) |
| DroneRFb-Spectra (IEEE DataPort) | ~2024-25 | gated | STFT spectrogram images only | 3 ISM bands | 7 RC/link vendors | unknown | spectrogram-classifier training only, no raw IQ | Low-Medium (search summary only) |
| DroneRFz/DroneRFB ext (IEEE DataPort) | unknown | gated | spectrogram, "diverse EM environments" | unknown | unknown | unknown | robustness/generalization testing, untriaged | Low (name + abstract only) |
| DroneRF2025 (IEEE DataPort) | 2025 | gated | unknown | unknown | unknown | unknown | untriaged, name-only discovery | Unknown |
| RFUAV (HuggingFace kitofrank/RFUAV) | 2025 | open | raw + spectrogram + weights | unknown | 35 drone models, 37 devices | ~1.3 TB (paper) vs 281.6 GB (corpus pointer) — discrepancy unresolved | largest model-diversity classification benchmark found | Medium (host confirmed, content not inspected) |
| Noisy Drone RF Signal Classification v1/v2 (Kaggle) | 2024 | open, needs Kaggle auth | preprocessed IQ vectors, per-SNR-bin | not confirmed | not confirmed | moderate | best available for low-SNR detection ROC/threshold tuning (explicit -20..30dB bins) | Medium (paper title/abstract read via search) |
| CardRF (IEEE DataPort / AERPAW) | ~2022-23 | gated (IEEE), maybe AERPAW mirror unconfirmed | .mat, 5M samples/0.25ms | not confirmed | UAV+BT+WiFi | 65+ GB | best candidate for WiFi/BT false-positive testing at outdoor range/SNR | Low-Medium |
| UAVSig | 2024 | unresolved | raw, same capture shape as CardRF | not confirmed | 17 RCs, 8 mfrs, incl. same-model pairs | unknown | RC-side (uplink) individual fingerprinting | Low (paper found, no data host) |
| CageDroneRF (arXiv 2601.03302) | 2026-03 | unresolved | raw IQ + augmentation toolkit | unknown | 23 models / 39 classes | unknown | potentially the single most valuable set found (largest diversity, cage+outdoor, open tooling) IF access resolves | Low (very recent, access not located) |
| AERPAW RF/TDOA family (Dataset-15/28 etc.) | 2024-25 | open (Dryad mirror) / portal | TDOA/RSS timestamps + position logs, NOT raw IQ | 3.32 GHz test source | AERPAW AADM test platform | moderate | localization/TDOA methodology only — NOT a real drone-protocol dataset | Medium |
| Radio-Frequency Control/Video Recordings of Drones (Zenodo 4264467) | 2020 | open, CC-BY-4.0 | raw IQ .bin, anechoic | 2.44/5.8 GHz | 10 drones (DJI/Parrot/Yuneec) | 8.6 GB | clean high-SNR reference for demod/sync bring-up | High (file list + licence read directly) |
| RUB-SysSec/DroneSecurity IQ captures | unknown | present locally, do not re-download | raw IQ, DJI DroneID | unknown | 2 (Mavic Air 2, Mini 2 SE) | small | DroneID decoder cross-validation | High (previously indexed, confirmed still present) |

## Engineering review by AERIX workstream

**(a) Detection, incl. Wi-Fi/BT rejection and low-SNR / open-set.**
Strongest near-term candidates: `noisy_drone_rf_v1/v2` (Kaggle) for
SNR-swept detection-threshold validation — it is the only set found with an
explicit, evenly-populated per-SNR-bin structure (-20..30 dB, 2 dB steps),
which is exactly what a PD/PFA curve needs. `cardrf` is the best-targeted
Wi-Fi/BT confuser set but is IEEE-DataPort-gated and its technical detail is
still thin (search-summary only). `dronerfa` is the best multi-band
(900 MHz/2.4/5.8 GHz) open-set candidate on paper but is unverified in
detail and very large (~570 GB claim). Do not treat "contains Wi-Fi/BT
samples" as proof of low-false-positive performance until the actual class
balance and SNR range are read from the paper.

**(b) Classification / fingerprinting, incl. individual-device ID.**
`rfuav` is the largest model-diversity set found (35 drone models) and is
now confirmed openly hosted on Hugging Face — this is the standout new
finding of this pass. For *individual airframe* fingerprinting specifically
(not just model classification), `dronerfb_dir` is unique among everything
found: labels are per-individual-airframe (3 individuals per drone type),
which DroneRF/DroneRFa/RFUAV do not offer. `uavsig` would be the RC-side
(controller) analogue but its data host is unresolved. `cagedronerf` may
turn out to be even better than RFUAV for diversity (23 models, dual
cage/outdoor) but access is unresolved — flag for priority follow-up.

**(c) Protocol work (DroneID/OcuSync 1/2/O3/O4, Wi-Fi drones, FHSS RC,
analog/digital FPV).** None of the newly-found bulk RF datasets are
protocol-labeled or come with known-plaintext/ground-truth bitstreams —
they support "contains emissions of interest" (stage-1/stage-2 evidence per
AERIX's evidence-level scale) but NOT "enables decoding research" in the
sense of validated deterministic decode. The two assets that actually help
decode-feasibility work are code/IQ pairs already in the local corpus, not
bulk datasets: `proto17/dji_droneid` (decoder source) and the
`RUB-SysSec/DroneSecurity` real IQ captures (2 airframes) — both already
routed to `rf-protocol-analyst` via `research/briefs/dji-ocusync-droneid-sources.md`.
The Zenodo 4264467 anechoic set is useful only as a *clean* high-SNR
synchronization/demod bring-up aid (no protocol ground truth, but the
absence of noise helps isolate algorithm bugs from channel effects) — it
does not by itself constitute protocol evidence.

**(d) Localization (RSSI/TDOA/coherent/DOA).** Kept strictly separate per
task instructions: the AERPAW RF/TDOA family (`aerpaw_rf_localization_suite`)
is the only localization-focused asset found. Important caveat: its RF
source is a *controlled test transmitter* on the AERPAW AADM platform at
3.32 GHz, not a real consumer-drone downlink — so it validates TDOA/DOA
*methodology and hardware geometry*, not drone-protocol-specific
localization. Do not cite it as evidence about real DroneID/OcuSync/FHSS
signal localizability.

## Open questions / follow-ups for the architect

1. RFUAV size discrepancy (1.3 TB per arXiv abstract vs 281.6 GB corpus
   pointer in `research/index.md`) is unresolved — likely different release
   subsets, needs one direct read of the Hugging Face dataset card.
2. UAVSig and CageDroneRF data hosts are unresolved; CageDroneRF in
   particular looks like the single best-diversity dataset if it turns out
   to be genuinely open — worth a dedicated follow-up search before the next
   major planning gate on classification/fingerprinting.
3. DroneRFa's and DroneRFb-DIR's exact sample rate, recording hardware, and
   drone-model list are not yet confirmed from the papers themselves (only
   from search-result summaries) — needs a focused read once each finishes
   downloading/extracting.
4. Whether the AERPAW portal listing of CardRF offers a non-IEEE-gated
   direct download was not checked this pass.

## Sources consulted this pass (web search / fetch, not deep reads unless noted)

- DroneRF: https://data.mendeley.com/datasets/f4c2b4n755/1 (file list, previously fetched, re-verified against local files this pass)
- DroneRFa: https://www.scidb.cn/en/detail?dataSetId=34f0a91e8a544904998b8fdc44477380 ; https://jeit.ac.cn/en/article/doi/10.11999/JEIT230570
- DroneRFb-DIR: https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202 ; https://jeit.ac.cn/en/article/doi/10.11999/JEIT240804
- DroneRFb-Spectra / DroneRFz-DroneRFB / DroneRF2025: ieee-dataport.org landing pages (titles/abstracts only)
- RFUAV: https://github.com/kitoweeknd/RFUAV (README fetched), https://arxiv.org/abs/2503.09033 (abstract), https://huggingface.co/datasets/kitofrank/RFUAV (host confirmed, not opened)
- Noisy Drone RF v1/v2: https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2 ; https://zenodo.org/records/14065652
- CardRF: https://ieee-dataport.org/documents/cardinal-rf-cardrf-outdoor-uavuasdrone-rf-signals-bluetooth-and-wifi-signals-dataset ; https://aerpaw.org/dataset/cardinal-rf-cardrf-an-outdoor-uav-uas-drone-rf-signals-with-bluetooth-and-wifi-signals-dataset/
- UAVSig: https://ieeexplore.ieee.org/abstract/document/10773837/ (abstract only)
- CageDroneRF: https://arxiv.org/abs/2601.03302 (abstract only)
- AERPAW: https://aerpaw.org/dataset/aerpaw-rf-sensor-measurements-with-uav-july-2024/ ; https://aerpaw.org/dataset/multi-modal-rf-sensor-and-radar-dataset-for-uav-tracking/ ; https://datadryad.org/dataset/doi:10.5061/dryad.vq83bk44h ; https://arxiv.org/pdf/2502.01771
- Zenodo 4264467: https://zenodo.org/records/4264467 (file list + licence fetched directly)
- RUB-SysSec/DroneSecurity, proto17/dji_droneid: local corpus, `research/index.md` lines 26-27 (not re-read this pass)
