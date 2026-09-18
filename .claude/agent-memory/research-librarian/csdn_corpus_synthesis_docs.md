---
name: csdn-corpus-synthesis-docs
description: Where the pre-built synthesis/gap-analysis documents live inside the raw csdn_enriched/fpv archives — read these before re-deriving conclusions from raw articles
metadata:
  type: reference
---

The `csdn_enriched` and `fpv` archives (see `[[csdn-fpv-corpus-2026-09]]`) were produced by a prior scraping/analysis pass that already wrote high-quality, decision-oriented synthesis documents alongside the raw per-article captures. These are NOT copied into the git-tracked repo (library is gitignored) — they live only in `research/library/`. Read them first for any question in their scope; they already did the cross-referencing work.

- `research/library/csdn_enriched/AERIX_RF_CSDN/INDEX.md` — Part 1 (17-article leegang12 DJI/OcuSync index with per-article findings + a consolidated cross-article physical-layer parameter table with conflicts flagged) and Part 2 (non-leegang12 RF research extension index table: RF classification, RF fingerprinting, DOA, TDOA, datasets, FPGA).
- `research/library/csdn_enriched/AERIX_RF_CSDN/CSDN_RF_GAP_REPORT.md` — priority-ranked (P0-P3) gap analysis of what the non-DJI material adds vs. the existing DJI decoder work; the "detect/classify/locate without decoding" strategic framing for O4.
- `research/library/csdn_enriched/AERIX_RF_CSDN/ENRICHMENT_REPORT_NON_DJI.md` + `NON_DJI_POSITION_MATRIX.md` — per-vendor (DJI, MAVLink/SiK, mLRS, ExpressLRS, Crossfire, FrSky, Futaba, FlySky, RadioLink, Parrot, Autel, Yuneec, Skydio, Skydroid, Paparazzi) capability matrix: DIRECT_DECODE / NEEDS_PHY / GEOLOCATION_ONLY / DETECTION_ONLY / NO_EVIDENCE, each with an evidence grade and "remaining experiment."
- `research/library/csdn_enriched/AERIX_RF_CSDN/generic_RF_detection/GENERIC_HOPPING_FEATURES.md` — candidate vendor-independent FHSS/hopping-link detector features (per-hop, hopping-sequence, link-structure, cyclostationary), synthesized from DroneRFa/RFUAV/SiK/ELRS sources.
- `research/library/csdn_enriched/AERIX_RF_CSDN/TODO.md` — open dataset-download items (DroneRFa 573.65 GB on ScienceDB, RFUAV 281.6 GB on HuggingFace, etc.) — **this is the dataset-librarian's territory**, do not duplicate, just be aware it exists if asked.
- `research/library/fpv/AERIX_FPV/INDEX.md` — 75-article FPV index table with per-article evidence-class grading (VERIFIED_PRIMARY/SUPPORTED/PLAUSIBLE/UNVERIFIED/CONTRADICTED) already assigned; includes a flagged list of AI-generated/fabricated-citation articles (`ELRS_receiver_tech_part2` cites 10 fake `github.com/xxx/...` placeholder repos) and a contradicted-numbers article (`ELRS_vtx_frequency_planning` claims wrong channel spacing vs. the firmware source).
- `research/library/fpv/AERIX_FPV/RESEARCH_PRIORITY.md` and `DOWNLOAD_MANIFEST.md` — not yet read in detail (2026-09-18 pass); check before starting any FPV-specific build work.

**How to apply:** When the architect routes a non-DJI-vendor, FHSS-detector, or FPV-specific question to research-librarian, read the relevant synthesis doc above first rather than re-scanning all raw articles — they already cross-reference the raw material and flag contradictions/fabrications.
