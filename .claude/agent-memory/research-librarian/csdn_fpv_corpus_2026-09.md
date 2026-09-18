---
name: csdn-fpv-corpus-2026-09
description: Inventory/dedup/grading results for the three local CSDN/FPV research zips ingested 2026-09-18 (Workstream E)
metadata:
  type: project
---

Ingested and indexed three local research drop zips on 2026-09-18 (task: "Workstream E"):
- `/home/jarvis/aerix-rf/AERIX_RF_CSDN.zip` (176 MB, 337 files) — 17-article leegang12 DJI DroneID/OcuSync series + an early draft of Part 2.
- `/home/jarvis/aerix-rf/AERIX_RF_CSDN_ENRICHED.zip` (354 MB, 506 files) — **strict superset** of the above (confirmed by sha256: every file in `csdn/` has a byte-identical twin in `csdn_enriched/` except 6 top-level `.md` docs that were later revised — INDEX.md, DOWNLOAD_MANIFEST.md, CSDN_RF_GAP_REPORT.md, additional_CSDN_sources/{NOTES.md,candidate_articles.md}, datasets/DroneRFa_ZJU/NOTES.md). Adds non-DJI telemetry (MAVLink/SiK/mLRS/ExpressLRS firmware sources), non-DJI vendor survey (Autel/Parrot/Skydio/Skydroid/Yuneec/Paparazzi), dataset pointers (DroneRFa, RFUAV, DroneRF_AlSad, DeepAoANet, RadSeg), RF classification/fingerprinting/localization CSDN articles, and synthesis docs.
- `/home/jarvis/aerix-rf/AERIX_FPV.zip` (342 MB, 734 files) — 75-article DIY/FPV-focused archive (analog+digital video, control links, RF classification/fingerprinting, DOA/TDOA). Confirmed it is research material (article scrapes), not raw IQ — kept in scope. **13 articles/image-sets overlap byte-identically with `csdn_enriched/`** (same CSDN articles re-scraped under different folder names — e.g. hierarchical_UAV_detection, DroneRFa article, EMD/EEMD fingerprinting, zero-shot emitter, ExpressLRS part1/2, TDOA reference, DOA multichannel_SDR).

**Dedup result across all three, sha256 over 1493 extracted files:** 1113 unique content hashes, 380 exact duplicate copies, 270 duplicate groups spanning more than one archive root.

**Working set going forward:** treat `research/library/csdn_enriched/AERIX_RF_CSDN/` and `research/library/fpv/AERIX_FPV/` as authoritative; `research/library/csdn/AERIX_RF_CSDN/` is redundant (kept on disk, safe to ignore/delete).

**Critical finding for AERIX decoder work:** the corpus is unanimous and internally consistent that **O4 payload is encrypted — only CRC verifies, no telemetry has ever been shown decoded from O4** anywhere in this corpus (leegang12/292 is the key article). O1-O3 decode to full plaintext telemetry with a detailed parameter set. See `[[dji-ocusync-droneid-sources]]` type reasoning captured in `research/briefs/dji-ocusync-droneid-sources.md`.

**Two mirrored code repos worth using for validation** (present locally, not yet executed/diffed this pass):
- `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/281/external_repos/proto17_dji_droneid_main.zip` — AERIX's existing decoder reference, now available locally.
- `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/281/external_repos/RUB-SysSec_DroneSecurity_public_squash.zip` — independent Python DroneID receiver **plus two real IQ captures** (`samples/mavic_air_2`, `samples/mini2_sm`). This is the best asset in the corpus for testing the leegang12 parameter claims (especially the unresolved pilots-vs-no-pilots contradiction, see brief) against real signals.

Briefs written: `research/briefs/dji-ocusync-droneid-sources.md`, `research/briefs/ofdm-sync-methods.md`. `research/index.md` fully rewritten as a compact cluster-level catalog (not one row per CSDN article — the archives' own per-article INDEX.md/NOTES.md already carry that granularity locally).

**Why:** architect commissioned a research-corpus audit (Workstream E) separate from a parallel dataset-librarian instance (owns `research/briefs/rf-datasets.md` + `research/datasets/*`) and the antsdr-specialist (owns `research/briefs/antsdr-e200.md`).

**How to apply:** Before re-reading raw articles for a DJI/OcuSync/non-DJI-RF question, check `research/briefs/dji-ocusync-droneid-sources.md` and `research/briefs/ofdm-sync-methods.md` first. For questions this pass didn't brief (RF fingerprinting/cross-day evaluation, DOA/TDOA, non-DJI vendor position matrix, FPV analog/digital video), see `[[csdn-corpus-synthesis-docs]]` for where the pre-built synthesis documents already live inside the raw archive — read those before re-deriving from scratch.
