---
name: datasets-and-signatures-2026-09-19
description: RFUAV per-model raw-file discovery, DJI-subset download, and the Stage-1/2 signature table sourced from ExpressLRS/SiK/GENERIC_HOPPING_FEATURES.md
metadata:
  type: project
---

Delivered `research/briefs/datasets-and-signatures-plan.md` answering "what more
can we do with CSDN + public datasets" for two uses: Stage-2 classifier training
set + receiver-ID probe design, and a hardware-neutral Stage-1/2 RF signature
table.

**Key finding — RFUAV is NOT spectrogram-only.** The HF dataset card's "299GB,
imagefolder" framing only describes `ImageSet-AllDrones-MatlabPipeline` and
`ValidationSet_5Drones`. The repo's **top level has 36 per-model `.rar` files
totaling 109.2GB, measured directly** via
`curl -s "https://huggingface.co/api/datasets/kitofrank/RFUAV/tree/main"` — this
is raw-ish per-model frequency data, anonymously downloadable at
`https://huggingface.co/datasets/kitofrank/RFUAV/resolve/main/<urlencoded name>`,
no auth/gating. This measurement also partially resolves the old "1.3TB vs 281.6GB"
size-discrepancy open question from `briefs/rf-datasets.md` — still not fully
resolved (neither number matches 109.2GB or 299GB), flag if it matters later.

**Curation decision:** full 36-file set is 109.2GB, over the 100GB budget I was
given. I chose the 5 DJI files (~43GB: AVATA2, FPV COMBO, MAVIC3 PRO, MINI3,
MINI4 PRO) as the curated subset because they are the highest-value overlap
candidates for AERIX's own O3/O4 ANTSDR campaign (receiver-ID / cross-corpus
generalization probe). Left the other 31 files (RC-transmitter vendors: FlySky,
FrSky, Futaba, JR Propo, Jumper, RadioMaster, Radiolink, SIYI, Skydroid, WFLY,
Yunzhuo, Herelink, Devention, Dautel — ~66GB) as a documented fast-follow in
`research/datasets/USER_TODO.md`, not started. **Important caveat for whoever
extracts these:** most of RFUAV's "37 UAV classes" are actually RC transmitter
units, not drone airframes — don't assume every RFUAV file is an airframe capture.

**Download mechanics that worked:** `aria2c -i <urlfile> -x4 -s4 -c
--auto-file-renaming=false --allow-overwrite=false --dir=... --log=...`,
launched with `nohup ... & disown` from Bash. **Gotcha:** `--log=~/path/...`
does NOT tilde-expand reliably in this environment when placed right after `=`
in a piped/nohup context — use `$HOME` explicitly or the command silently
fails with "Failed to open the file ~/...". Manifest of URLs lives at
`~/rf-datasets/manifests/rfuav_dji_subset_urls.txt`; download log at
`~/rf-datasets/manifests/rfuav_dji_subset_download.log`.

**DJI OcuSync-generation confidence for RFUAV's DJI labels (do not overclaim):**
Avata 2 = O4 (Med), Mini 4 Pro = O4 (Med), Mavic 3 Pro = O3 (Med), FPV Combo = O3
(Low-Med, not independently confirmed from a primary DJI source), "Mini 3" =
**ambiguous** — RFUAV's label doesn't disambiguate plain Mini 3 (commonly O2)
from Mini 3 Pro (commonly O3). Don't hardcode this as O3 without checking what's
actually in the archive once extracted.

**Signature table sources confirmed by direct read this pass (not just index
pointers):** `fpv/AERIX_FPV/control_links/ExpressLRS/FHSS_key_sources/FHSS.cpp`
and `.h` (2.4GHz: 2400.4-2479.4MHz, 80 ch, 1MHz spacing, sync channel =
freq_count/2; sub-GHz regulatory domain table with exact MHz/channel-count per
domain — PRIMARY firmware source, directly quotable);
`generic_RF_detection/GENERIC_HOPPING_FEATURES.md` and
`NON_DJI_POSITION_MATRIX.md` (protocol-mapping table with VERIFIED_PRIMARY /
PLAUSIBLE / SUPPORTED grades already assigned by the archive's own scheme —
reused those grades rather than re-deriving).

See [[droneid_channel_raster]] for the DroneID-specific raster/burst-interval
detail this brief draws on (640ms burst interval, 2.4/5.8GHz candidate centres).
