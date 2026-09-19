# AERIX RF dataset access — manual steps required

These datasets cannot be fetched automatically (account/subscription/approval
required, or the access mechanism was not resolved by the research-librarian
in the 2026-09-18 pass). Each entry lists exactly what a human needs to do.

## IEEE DataPort (account required; some items subscription-gated)

Affects: `dronerfb_spectra`, `dronerfz_dronerfb_ext`, `dronerf2025`, `cardrf`.

Steps:
1. Create a free IEEE DataPort account at https://ieee-dataport.org (an IEEE
   account, not necessarily an IEEE membership, is enough for many "open
   access" listings — check each dataset page for an "Open Access" vs
   "Subscription" badge before assuming payment is needed).
2. Log in, open the dataset's landing page:
   - DroneRFb-Spectra: https://ieee-dataport.org/documents/dronerfb-spectra-rf-spectrogram-dataset-drone-recognition
   - DroneRFz/DroneRFB extension: https://ieee-dataport.org/documents/dronerfz-and-dronerfb-extension-rf-spectrogram-dataset-drone-recognition-across-diverse
   - DroneRF2025: https://ieee-dataport.org/documents/dronerf2025
   - CardRF: https://ieee-dataport.org/documents/cardinal-rf-cardrf-outdoor-uavuasdrone-rf-signals-bluetooth-and-wifi-signals-dataset
3. Use the "Download" tab for direct HTTP, or the "AWS S3 URI" tab if the set
   is large (CardRF is 65+ GB) — the S3 URI can be handed to `aria2c`/`aws s3
   cp` once you have the pre-signed link from your logged-in session.
4. IEEE DataPort links are typically session/account-bound — copy the
   resulting direct URL(s) into a note and tell research-librarian, or drop
   the files directly under `~/rf-datasets/<DatasetName>/original/` following
   the existing directory convention and note it in
   `~/rf-datasets/manifests/datasets.json` (`download_status`,
   `size_downloaded`).
5. For CardRF specifically: also check
   https://aerpaw.org/dataset/cardinal-rf-cardrf-an-outdoor-uav-uas-drone-rf-signals-with-bluetooth-and-wifi-signals-dataset/
   first — it may link to a non-IEEE-gated mirror or the same IEEE DataPort
   page; this was not fully checked this pass.

## Kaggle account + API token

Affects: `noisy_drone_rf_v1`, `noisy_drone_rf_v2`.

Steps:
1. Create a Kaggle account, go to Account settings, "Create New API Token" —
   downloads `kaggle.json`.
2. `pip install kaggle` (not installed in this environment as of 2026-09-18),
   place `kaggle.json` at `~/.kaggle/kaggle.json`, `chmod 600`.
3. `kaggle datasets download -d sgluege/noisy-drone-rf-signal-classification-v2 -p ~/rf-datasets/NoisyDroneRFv2/original --unzip`
   (and the `-v1` slug for v1: `sgluege/noisy-drone-rf-signal-classification`).
4. Alternative: check the Zenodo companion record
   https://zenodo.org/records/14065652 — if it carries the same files this
   avoids the Kaggle CLI entirely (not confirmed this pass whether it's a
   full mirror or just code/paper).

## Unresolved access / host (needs a focused follow-up search, not a blind download attempt)

- **UAVSig** — RESOLVED 2026-09-18. Data host located: **IEEE DataPort, open
  access, titled "Drone Remote Controller RF Signal Dataset"**
  (https://ieee-dataport.org/open-access/drone-remote-controller-rf-signal-dataset).
  Also mirrored at **UCLA Dataverse (CORES Lab)**, DOI 10.25346/S6/LVRRAE
  (https://dataverse.ucla.edu — search persistentId doi:10.25346/S6/LVRRAE).
  IEEE DataPort "open access" listings are typically downloadable without a
  paid subscription but do require a free IEEE account/login — not yet
  verified end-to-end (no download attempted this pass). Next step: create/
  use an IEEE account and attempt the download; if IEEE DataPort gates it
  behind subscription despite the "open-access" label, fall back to the UCLA
  Dataverse mirror first.
- **CageDroneRF (CDRF)** — RESOLVED (partially) 2026-09-18. Code, trained
  models, and (per the repo) the dataset are hosted at
  **https://github.com/DroneGoHome/U-RAPTOR-PUB** (project appears to be
  branded "U-RAPTOR" by AeroDefense, with CageDroneRF as the RF-benchmark
  component). There is also a **gated data request form**:
  https://aerodefense.tech/u-raptor-data-request — suggesting the *full*
  raw dataset may require a request/approval even though code+weights are
  public on GitHub. Next step: check the GitHub repo directly for a data/
  download section or release assets before assuming the request form is
  mandatory; if bulk raw IQ isn't in the repo itself, submit the AeroDefense
  request form (a human step, not automatable by research-librarian).
- **RFUAV full raw set (~1.3 TB)** — host IS known
  (https://huggingface.co/datasets/kitofrank/RFUAV, plus a smaller curated
  Roboflow detection subset), but the full raw pull was deliberately NOT
  started this pass given its size relative to the other in-flight downloads
  (DroneRFb-DIR ~64 GB, DroneRFa ~570 GB if started). Before pulling all
  1.3 TB, first fetch the much smaller Roboflow curated subset as a trial,
  and get explicit disk-budget sign-off from the architect.

## RFUAV — remaining RC-transmitter files (no account needed, fast-follow)

Resolved 2026-09-19: RFUAV's top-level raw data is 36 per-model `.rar` files
totaling 109.2GB (measured via `curl -s "https://huggingface.co/api/datasets/kitofrank/RFUAV/tree/main"`),
not the 299GB spectrogram-image figure shown on the HF dataset card (that figure
only counts the `ImageSet-AllDrones-MatlabPipeline`/`ValidationSet_5Drones` image
folders). The 5 DJI files (~43GB) were started automatically this pass — see
`research/datasets/manifest.json` id `rfuav_dji_subset`. The remaining 31 files are
**RC transmitter units, not drone airframes** (FlySky, FrSky, Futaba, JR Propo,
Jumper, RadioMaster, Radiolink, SIYI, Skydroid, WFLY, Yunzhuo, Herelink, Devention,
Dautel — ~66GB total). To pull them: reuse the URL pattern
`https://huggingface.co/datasets/kitofrank/RFUAV/resolve/main/<urlencoded filename>`
(anonymous, no auth needed, confirmed working this pass) with `aria2c -x4 -s4 -c`,
same as `~/rf-datasets/manifests/rfuav_dji_subset_urls.txt`. Not started — lower
priority than the DJI subset for AERIX's current O3/O4 workstream, but useful later
for the non-DJI RC-link detector.

## Large open datasets intentionally not yet started (no account needed, just budget/time)

- **DroneRFa** (~570 GB claim, unverified) — ScienceDB, open access observed
  previously. Recommend starting only after `DroneRFb-DIR` finishes and free
  disk is reconfirmed ≥ 200 GB headroom after the pull.
- **RFUAV full raw** — see above.

Report back to research-librarian once any of the above is manually
downloaded so `manifest.json` / `research/index.md` can be updated.
