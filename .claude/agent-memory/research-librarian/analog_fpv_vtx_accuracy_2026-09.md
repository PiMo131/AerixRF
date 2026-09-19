---
name: analog-fpv-vtx-accuracy-2026-09
description: RTC6705 ppm/drift and occupied-BW research trail for analog-fpv-detector.md (2026-09-19); what was found, what's still open
metadata:
  type: project
---

Task: fill two RESEARCH NEEDED items in `docs/design/analog-fpv-detector.md` (architect-owned,
append-only — findings went into a "Research findings 2026-09-19" addendum at the bottom of
that file, not into agent memory as the primary record).

**RTC6705/VTX crystal ppm + PLL step (sets grid tolerance τ):** not found, local or web, this
pass. Local corpus (`research/library/fpv/AERIX_FPV/analog_video/channel_plans/RTC6705_chip/`,
`.../RF_detection/5G8_analog_vtx_circuit/`, `.../RF_detection/Zeus800mW_vtx_teardown/`) are all
CSDN blog posts, grade PLASUIBLE, no instrument named — they give phase noise and power, not
frequency accuracy. A real RTC6705-DST-001 datasheet PDF exists at
`wildlab.org/wp-content/uploads/2015/07/RTC6705-DST-001.pdf` (found via web search, NOT fetched
this pass — budget-limited). **If τ ever needs to be tightened past the current guess, fetch that
datasheet PDF directly first** — it's the one PRIMARY source identified and unread.
Best proxy found (wrong chip, COMMUNITY grade): ExpressLRS SX1280 measured ±10 kHz @25°C,
35-80 kHz drift across 10-50°C between two modules (`control_links/ExpressLRS/ELRS_rf_performance_measured`
in the local corpus, also cited in `AERIX_FPV/RESEARCH_PRIORITY.md` line ~155).

**Occupied BW vs VTX power (25 mW vs 600 mW):** no comparative measurement found anywhere.
Local corpus has one independent SDR measurement (batchdrake / RTL-SDR.com writeups, cited in
`CHANNEL_DATABASE.md` section 4): ~9 MHz occupied FM BW for one low-power camera, vs the 30 MHz
community channel-plan spacing (Oscar Liang, vendor-repeated) — these are occupancy vs raster
spacing, not a power-dependent pair, and no shape-ratio data exists. Question remains open.

**Sample IQ:** `analog_video/sample_IQ/NOTES.md` confirmed recipe-only (no capture), as it
already stated. **New finding not previously in this corpus:** Zenodo record 19870020, "FPV
Analogue Video IQ Dataset" (2026-04-30, CC-BY-4.0) — real HackRF One analog-VTX IQ captures
with per-sweep metadata including `vtx_power_mw`, `drone_freq`, sample_rate=20 Msps, in
`iq_recording_meta.csv`. 4.2 TB total across chunk1-10.zip (0.99-3.4 GB each). Downloaded the
smallest, `chunk10.zip` (994.8 MB), to `~/rf-datasets/analog_fpv_public/original/`
(manifest: `~/rf-datasets/analog_fpv_public/manifest.md`) via detached aria2c — **not verified
complete/unzipped/decodable by this project yet.** Because it has a `vtx_power_mw` column, this
dataset could also close the 25/600 mW BW question above once unzipped, without a field session
— flag this to whoever picks up T1/T2 validation. Second Zenodo dataset found (4264467, "RF
Control and Video Signal Recordings of Drones", CC-BY-4.0, 8.6 GB, 200 Msps) has 5.8 GHz video
from DJI/Yuneec but it's digital-link, not analog FM — not relevant here, noted for completeness
only.

Reminder to self re: aria2c — it preallocates full target file size immediately, so `ls -la`
size looking "complete" during a download is NOT a completion signal; always check the
`.aria2` control file presence or the download log. (Same gotcha already recorded in
[[rf_datasets_workstream_2026-09]].)
