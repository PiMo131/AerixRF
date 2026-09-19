---
name: rf-datasets-workstream-2026-09
description: State and findings of the Workstream B/C RF dataset acquisition pass (2026-09-18) - what's downloaded, what's gated, what's unresolved, and key discoveries (RFUAV HF host, CageDroneRF, aria2c prealloc gotcha).
metadata:
  type: project
---

Dataset acquisition workstream (2026-09-18) picked up after a prior librarian
run hit its turn limit mid-download with no manifest written. Deliverables
now exist at `~/rf-datasets/manifests/datasets.json` (source of truth),
mirrored to `~/aerix-rf/research/datasets/manifest.json`, plus
`~/aerix-rf/research/datasets/README.md`, `USER_TODO.md`, and
`~/aerix-rf/research/briefs/rf-datasets.md`. `~/rf-datasets/manifests/status.sh`
prints live per-dataset size + running aria2c jobs + disk.

**Why:** the architect wants a durable, reusable local dataset library so
detection/classification/fingerprinting work doesn't depend on re-downloading
or re-researching sources each session.

**How to apply:** before answering any future dataset question, run
`bash ~/rf-datasets/manifests/status.sh` first — downloads were in progress
at handback time and state will have changed. Update `manifest.json` in BOTH
places (`~/rf-datasets/manifests/` is the working copy, copy to
`~/aerix-rf/research/datasets/manifest.json` after edits) plus the brief when
status changes materially (download completes, new dataset located, access
resolved).

Key gotcha discovered: **aria2c's default 'prealloc' file allocation method
reserves the FULL target file size on disk the moment a download starts**, so
`du -sh` on a dataset directory shows 100% of expected size even at 0%
actual transfer. Always cross-check against the aria2c log's own %-complete
lines (or `status.sh`'s "Latest progress line" section), never against `du`
alone, when judging whether a large single-zip download (e.g. DroneRFb-DIR)
is actually done.

State as of 2026-09-18 ~06:26 UTC (WILL BE STALE — re-check status.sh):
- DroneRF (Mendeley): COMPLETE, 23/23 files verified against Mendeley file
  list (`dronerf_filelist.txt` in the old scratchpad), 3.8 GiB.
- DroneRFb-DIR (SciDB, single 63.6 GiB zip via getZipFile endpoint):
  COMPLETE and VERIFIED as of 2026-09-19. Survived one DNS-outage restart on
  2026-09-18 (see incident note further down / in the JSON `notes` field).
  `unzip -t` integrity check passed (32/32 members, no errors). SHA256 of
  the outer zip: `e0b2d57bf0a46ce85d1e53a345af1b61f77ea1e378811ba187b4b73383aa3a70`
  (self-computed only, no publisher checksum exists to cross-check against).
  Moved from `~/rf-datasets/DroneRFb-DIR/original/` to the canonical
  `~/rf-datasets/dronerfb_dir/original/`; `DroneRFb-DIR` is now a symlink to
  `dronerfb_dir`. **STRUCTURE GOTCHA — do not extract naively**: the outer
  zip's only top-level entry is `twin_droneRFa/`, containing 32 files that
  are themselves a SPLIT/SPANNED zip volume set (`twin_droneRF.zip` +
  `.z01`..`.z31`, ~2 GiB each). A plain `unzip` of the outer zip will NOT
  give you the dataset — you must reassemble first, e.g.
  `zip -s 0 twin_droneRF.zip --out combined.zip && unzip combined.zip`,
  which needs ~63 GiB of additional free disk (1.5 TB free as of
  2026-09-19, so fine) and was NOT attempted this pass. Inner file layout
  (per-drone folders, filenames, metadata) is still unknown — that's the
  next open item before this dataset is usable.
- DroneRFa (SciDB, ~570 GB per unverified corpus pointer): NOT STARTED.
  Recommend starting only after DroneRFb-DIR finishes and ≥200GB headroom is
  reconfirmed (disk was 1.6TB free / 5% used at pass start, so there is
  plenty of room, but don't run two multi-hundred-GB pulls concurrently
  without checking).
- Zenodo record 4264467 ("Radio-Frequency Control and Video Signal
  Recordings of Drones", 2020, CC-BY-4.0, 10 drones incl. DJI/Parrot/Yuneec,
  2.44/5.8GHz anechoic IQ .bin, only 8.6GB total): newly discovered and
  started this pass, small and fully open. One quirk: 3 of the *_1of2/_2of2
  split files hit a transient "Invalid range header" Content-Length mismatch
  from Zenodo's CDN when downloaded with -x4/-s4 parallel connections;
  fixed by removing stale .aria2 control files and re-launching with
  -x1 -s1 (single connection per file) which succeeded. If resuming, check
  file count == 19 .bin + 2 .py under
  `~/rf-datasets/ZenodoDroneRFVideo2020/original/`.

Key findings worth remembering without re-searching:
- **RFUAV** (arXiv 2503.09033, 35 drone models, largest diversity found) is
  hosted openly on Hugging Face: https://huggingface.co/datasets/kitofrank/RFUAV
  (raw + spectrograms + model weights), plus a smaller curated Roboflow
  detection subset. The GitHub repo (kitoweeknd/RFUAV) is code only. Size
  claim conflicts: ~1.3TB per arXiv abstract vs 281.6GB per a corpus pointer
  previously captured in `research/index.md` — unresolved, don't assume
  either number without reading the HF dataset card. Do NOT start the full
  pull without explicit architect sign-off on disk budget.
- **CageDroneRF** (arXiv 2601.03302, 2026-03, Rowan University): 23 drone
  models / 39 classes, dual Faraday-cage + outdoor capture, ships an open
  SNR/interferer augmentation toolkit. Looks like it could be the single
  best dataset for classification/fingerprinting IF the actual data release
  is genuinely open, but the data host was NOT located this pass (very
  recent paper) — worth a dedicated follow-up search, high priority.
- **UAVSig** (IEEE Xplore doc 10773837, 2024): 17 UAV remote controllers
  across 8 manufacturers incl. same-model pairs (good for RC-side individual
  fingerprinting). Data host NOT located this pass.
- **DroneRFb-DIR** (SciDB, JEIT 2025, DOI 10.11999/JEIT240804) is distinct
  from DroneRFa (JEIT 2023, DOI 10.11999/JEIT230570) — both same author
  group (Zhejiang University, Ren/Yu/Zhou/Shi/Chen) but DIR is specifically
  for *individual airframe* ID (6 types x 3 individuals each), not just
  model classification. Don't conflate the two.
- **CardRF** and **UAVSig** share an identical raw-capture shape (5 million
  samples / 0.25ms per signal) — possibly built on a shared capture
  pipeline/lab; not confirmed, just noted as a pattern.
- **AERPAW's RF/TDOA dataset family** (Dataset-15, Dataset-28, Dryad
  10.5061/dryad.vq83bk44h) is localization methodology data (Keysight
  N6841A fixed-tower sensors + AERPAW's own AADM test platform transmitting
  a controlled 3.32GHz test signal) — NOT a real drone-protocol capture.
  Keep this out of any "we have real DroneID/OcuSync data" claim.
- IEEE DataPort gates: `dronerfb_spectra`, `dronerfz_dronerfb_ext`,
  `dronerf2025`, `cardrf`. Kaggle-gated (needs `kaggle` CLI + API token, not
  installed in this environment as of 2026-09-18): `noisy_drone_rf_v1/v2`.
  Exact manual steps are in `research/datasets/USER_TODO.md` — keep that
  file, not memory, as the authoritative how-to (memory should only hold the
  "what/why", not step-by-step instructions that could drift from reality).
- `RUB-SysSec/DroneSecurity` real IQ (mavic_air_2, mini2_sm) and
  `proto17/dji_droneid` (decoder code) are already present inside the local
  csdn_enriched corpus per `research/index.md` lines 26-27 — do not
  re-download, do not list as missing.

Update 2026-09-18 (follow-up pass, housekeeping + research):
- Retired duplicate manifest entry `dji_droneid_iq_rub_syssec` (merged its
  one unique field — ZC/Gold/QPSK operating-mode note — into
  `rub_dronesecurity`, then deleted). `rub_dronesecurity` is now the sole
  canonical entry for the RUB-SysSec real-IQ samples in both
  `~/rf-datasets/manifests/datasets.json` and
  `~/aerix-rf/research/datasets/manifest.json` (16 entries total, was 17).
- **DroneRFb-DIR**: still in progress at re-check, ~16% actual transfer
  (~10 GiB/63 GiB per aria2c log), NOT stuck — same single-zip SciDB
  download from the prior pass, just slow (~4-5 MiB/s).
- **Zenodo 4264467 corrected**: the record has **25 files total**, not 21
  as the prior pass assumed — 19 `.bin` data files + `example.py` +
  `example.m` + `load_bin.py` + `load_bin.m` + 2 spectrogram PNG/JPGs. Local
  download has all 19 data files + example.py + load_bin.py (21/25); missing
  the 2 `.m` scripts and 2 tiny images (~210KB, cosmetic only, not a data
  gap). Spot-checked md5 (DJI_matrice_100_2G.bin, example.py, load_bin.py)
  against `api.zenodo.org/records/4264467` JSON — all match.
  **Sample rate CORRECTED**: verified directly from the Zenodo record's own
  description field (not the loader scripts) — 120 MS/s at 2.44 GHz files
  (120e6 samples = 1.0 s each), 200 MS/s at 5.8 GHz files (100e6 samples =
  0.5 s each), interleaved int16 little-endian I/Q. The DSP specialist's
  earlier guess of "~60 MS/s int16, 2.000s per file" was wrong — if anyone
  built code around that guess, it needs fixing.
- **DroneRF (Mendeley) format CONFIRMED real-valued amplitude, NOT I/Q**:
  multiple independent secondary sources (ScienceDirect/ResearchGate
  summaries of Allahham et al. 2019, Data in Brief) agree the CSV segments
  are magnitude/amplitude time-domain samples split across Low/High
  frequency sub-band channels — not complex I/Q pairs. This blocks any
  adapter that assumes complex64 I/Q input; DroneRF needs a
  magnitude-only ingestion path or must be excluded from I/Q pipelines.
  Not independently cross-checked against the primary Mendeley/Data-in-Brief
  PDF text itself this pass (secondary sources only, but they directly quote
  the original paper's own format description) — confidence Medium-High.
- **CageDroneRF data host located**: GitHub
  `https://github.com/DroneGoHome/U-RAPTOR-PUB` (code+weights, branded
  "U-RAPTOR" by AeroDefense) plus a gated request form
  `https://aerodefense.tech/u-raptor-data-request` for the full raw
  dataset — unclear yet whether raw IQ is actually in the GitHub repo or
  only behind the request form. Not verified by visiting the repo directly
  this pass (WebSearch only) — next pass should check the repo's actual
  contents before assuming the request form is required.
- **UAVSig data host located**: IEEE DataPort "Drone Remote Controller RF
  Signal Dataset" (open-access listing, likely still needs free IEEE login)
  at `ieee-dataport.org/open-access/drone-remote-controller-rf-signal-dataset`,
  mirrored at UCLA Dataverse (CORES Lab) DOI `10.25346/S6/LVRRAE`. Neither
  actually downloaded this pass.
- **DroneID/OcuSync decode-under-interference literature**: searched
  RUB-SysSec NDSS'23, GitHub issues, TranSIC-Net (MDPI Sensors 2025,
  PMC12567810, directly read), and a 2025 SDR/Mini-2 paper (blocked, 403).
  **No published source gives a co-channel/adjacent-strong-emitter decode
  number** comparable to AERIX's own +20 dB test — this looks like a real
  gap, not a search miss. TranSIC-Net gives clean BER-vs-SNR and range-based
  frame-pass-rate numbers but explicitly does not test interferer emitters.
  Full findings + citations in `research/briefs/dji-ocusync-droneid-sources.md`
  under "Decode thresholds and interference — literature". Do not re-run this
  search without new evidence — this appears to be exhausted for now; the
  two open leads (reading RUB-SysSec NDSS'23 PDF's own eval section directly,
  and the DroneSecurity GitHub issue #46 thread) are recorded there for
  whoever picks this up next.

Update 2026-09-18 (folder-layout housekeeping pass, ~07:29):
- **Canonical local folder is now `dataset_id`, not display name.** Architect
  decision: `aerix_rf.datasets.prepare` writes to `<root>/<dataset_id>/prepared/`,
  so the on-disk convention had to match. Moved `DroneRF/original` ->
  `dronerf/original`, `DroneRFa` -> `dronerfa` (was empty, download not
  started), `RUB-DroneSecurity/original` -> `rub_dronesecurity/original`,
  `ZenodoDroneRFVideo2020/original` -> `zenodo_drone_rf_video_2020/original`.
  Left a symlink at each old display-name path pointing to the new
  `dataset_id` dir (transitional, noted in `manifest.json.notes` for
  `dronerfb_dir`; not yet added per-entry for the four already-moved sets —
  if asked again, add one-line notes there too). `DroneRFb-DIR` was
  deliberately LEFT UNMOVED (still downloading, see below) — it is a real
  directory, not a symlink, until the transfer finishes.
- Added a `local_path` field (= `dataset_id`, relative to root) to every
  entry in both `~/rf-datasets/manifests/datasets.json` and
  `~/aerix-rf/research/datasets/manifest.json` (kept identical/mirrored, as
  before — always copy one to the other after edits, don't hand-edit only
  one). Confirmed all 16 `dataset_id` values already matched intended
  snake_case folder names (dronerf, dronerfa, dronerfb_dir,
  dronerfb_spectra, dronerfz_dronerfb_ext, dronerf2025, rfuav,
  noisy_drone_rf_v1/v2, cardrf, uavsig, cagedronerf,
  aerpaw_rf_localization_suite, zenodo_drone_rf_video_2020,
  proto17_dji_droneid_code, rub_dronesecurity).
- Rewrote `~/rf-datasets/manifests/status.sh`: now iterates real `dataset_id`
  directories (skips symlinks via `[ -L ]`) and prints `original=` size,
  `prepared=` size, and `prepared/index.jsonl` row count per dataset, in
  addition to the pre-existing disk/aria2c-job/log sections. Old version
  only printed a flat `du -sh` per top-level dir (would have double-counted
  once symlinks existed).
- Updated `~/aerix-rf/research/datasets/README.md` layout section to state
  the `dataset_id`-is-canonical rule and that display-name folders are
  transitional symlinks not to be written through.
- **DroneRFb-DIR progress at last check (2026-09-18 ~07:30): 31% actual
  transfer (~20 GiB / 63 GiB), ETA ~6h, single aria2c PID 117040 still
  alive.** (Prior memory said 16% at an earlier check — confirms it is
  progressing, not stuck, just slow at ~2 MiB/s.) Once it completes: move
  `DroneRFb-DIR/original` -> `dronerfb_dir/original`, remove the empty
  `DroneRFb-DIR` dir, symlink `DroneRFb-DIR` -> `dronerfb_dir`, matching the
  pattern used for the other four datasets this pass.
- Did NOT touch any `prepared/` contents (`rub_dronesecurity/prepared`,
  `zenodo_drone_rf_video_2020/prepared` untouched, only their `original/`
  subdirs were relocated into the same already-existing `dataset_id` parent).

Update 2026-09-18 (~08:30, Tier-D preservation task):
- New local dataset `aerix_antsdr_ambient_2026_09_18` added (17th entry, both
  manifests): 6 real ANTSDR E200 ambient-2.4GHz sessions rescued from an
  ephemeral session-scoped scratchpad before it would have vanished. This is
  AERIX's **only Tier-D (real-receiver negative-class) data** to date -
  operator ground truth "no drone present" for every session, Wi-Fi-dominated
  indoor bench ambient. Local copy at
  `~/rf-datasets/aerix_antsdr_ambient_2026_09_18/original/<session_dir>/`,
  full per-session breakdown + known issues in the dataset's own `SOURCE.md`
  (not duplicated in memory - read that file for specifics, not this note).
  271/271 present IQ files SHA-256-verified against each session's own
  `session.json` (0 mismatches, ~13 GB). One session
  (`2026-09-18_111959_soak10min`) has IQ deleted pre-preservation (metadata
  only, expected not a copy failure). One session (the smoke test) is **cs8**
  format, not native cs16 - do not silently mix it into a cs16 dataset
  loader without checking `iq_format` per session.
- `status.sh` required **no code change** - it already iterates every real
  (non-symlink) `dataset_id` dir under `$ROOT` generically, so the new
  dataset showed up automatically once its folder existed.
- Reminder for future asks like this: session-scoped scratchpads
  (`/tmp/claude-*/.../scratchpad/`) are ephemeral and can vanish between
  sessions - if the architect or a specialist mentions "live capture data"
  sitting in a scratchpad, treat it as at-risk and flag/propose preservation
  proactively rather than waiting to be asked again.

Update 2026-09-18 (~10:42 EDT, housekeeping pass 2 - soak600 preservation +
aria2c restart):
- Moved (not copied, same filesystem) the two finalized ANTSDR soak600
  sessions from `~/rf-sessions/soak_2026_09_18/` into
  `aerix_antsdr_ambient_2026_09_18/original/`: `soak600_default_noiq`
  (600 windows, 0 IQ by design, metadata/detections only, 121M) and
  `soak600_k32_4m_iq` (**actual dir name has 133337 not 133338 timestamp**
  - task description had a 1s typo, used the real dir; 599 cs16 IQ files,
    ~28G, all 599 SHA-256-verified against session.json, 0 mismatches).
  Also moved sweep baselines `base_24.npz`/`base_58.npz` into
  `original/sweeps_2026_09_18/` (unchecksummed, no per-file hash existed).
  Both soak600 sessions carry a `receiver_readback` block (live AD9361
  read-back, not just requested config) confirming gain 40dB manual,
  rf_bandwidth 10MHz, sampling_frequency 12.288MHz, rf_port A_BALANCED,
  rx_lo ~2437MHz (2436999998 Hz exact), hw_model "PlutoSDR Rev.C
  (Z7010-AD9364)" - useful precedent: `receiver_readback` is per-file in
  `files[]`, not session-level, on sessions produced by the newer capture
  pipeline (software_git_sha d04332d+). Full per-session table and
  integrity log now in `~/rf-datasets/aerix_antsdr_ambient_2026_09_18/SOURCE.md`
  (running total 870 IQ files verified, 0 mismatches, ~41-54GB depending on
  du apparent-vs-disk accounting). Dataset total now shows as `original=54G`
  in status.sh (up from ~13G).
- **DroneRFb-DIR aria2c had fully died** (not just stalled at 0B/s as the
  task description assumed) at 07:56 EDT with `errorCode=19 DNS resolution
  failed for china.scidb.cn` on all 6 connections - a ~2h46m silent gap
  before this pass caught it. DNS resolved fine on manual `curl` retest, so
  restarted with `-c -x6 -s6 -k1M` same `--out`/`--dir`/URL; confirmed
  clean resume from 22GiB/63GiB (35%), new PID, ~3-4 MiB/s, ETA ~3h.
  Incident recorded in `dronerfb_dir` manifest entry `notes` field (both
  manifest.json copies). **Lesson: always check `pgrep -af aria2c` actually
  shows a live process before trusting a "last known %" from the .out log -
  a fully-dead process leaves the same-looking stale progress line as a
  merely-stalled one, only the process list and .out/.log mtime distinguish
  them.**

Update 2026-09-19 (RFUAV non-DJI subset download + unrar install):
- **All 5 previously-downloaded RFUAV DJI files verified byte-exact** against the
  HF `api/tree/main` listing (DJI_AVATA2.rar 11409316020, DJI_FPV_COMBO.rar
  14998447951, DJI_MAVIC3_PRO.rar 5159757084, DJI_MINI3.rar 6484836469,
  DJI_MINI4_PRO.rar 4945879172 — all match exactly). No re-download needed.
- **RFUAV top-level file count corrected again**: HF tree API returns 39 file
  entries total (not 36/37 as prior passes estimated) = .gitattributes + README.md
  + 5 DJI .rar + **32** non-DJI .rar (not 31). Always re-count from the live
  `curl -s "https://huggingface.co/api/datasets/kitofrank/RFUAV/tree/main"` JSON
  rather than trusting a remembered count.
- Started the 32 non-DJI RC-transmitter/airframe files (~66.2GB: DAUTEL,
  DEVENTION, FlySky x3, FrSky x3, Futaba x4, Herelink, JR Propo x2, Jumper x2,
  RadioMaster x2, Radiolink x2, SIYI x3, Skydroid x2, WFLY x3, Yunzhuo x3) via
  detached `aria2c -c -x4 -s4 -j3 -k1M` (PID 334846 at launch), input file
  `~/rf-datasets/manifests/rfuav_nondji_urls.txt`, log
  `~/rf-datasets/manifests/rfuav_nondji_download.log`. URL pattern: HF resolve
  URLs redirect through `us.aws.cdn.hf.co/xet-bridge-us/...` (Hugging Face's Xet
  storage backend) — this is normal, not an error, do not treat the redirect
  itself as a failure signal. Observed aggregate throughput ~10-11 MiB/s early
  on; at that rate full completion is ~1.5-2h from the 2026-09-19 10:02 UTC
  start. New manifest entry `rfuav_nondji_subset` in both
  `research/datasets/manifest.json` and `~/rf-datasets/manifests/datasets.json`.
- **unrar was absent everywhere** (`~/.local/bin`, all micromamba envs) before
  this pass. Installed via `micromamba install -n base -c conda-forge unrar -y`
  — now at `~/.local/share/mamba/bin/unrar` in the `base` env (active by
  default per `micromamba env list`). Neither RFUAV subset has been extracted
  yet; that + confirming actual internal IQ format/sample rate is still open
  for whoever picks up RFUAV adapter work next.
- `research/datasets/USER_TODO.md`'s RFUAV section was rewritten to reflect
  "download started, no manual action needed" instead of "not started" —
  re-read that file (not this memory) for the current authoritative status
  since download state changes fast and this memory note will go stale.
