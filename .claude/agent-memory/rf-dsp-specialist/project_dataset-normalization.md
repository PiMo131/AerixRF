---
name: dataset-normalization
description: Workstream D dataset preprocessing design (2026-09-18) — canonical window + sidecar pipeline, verified public-dataset formats, and the leakage/label traps that are expensive to rediscover
metadata:
  type: project
---

Design memo: `docs/design/dataset-normalization.md` (223 lines). Builds on [[canonical-representation]].
Pipeline: `original/` (sha256, immutable) → per-format adapter → band-slice/decimate-to-≥19.2 → one
rational stage → 15.36 MS/s → ≤1.000 s window (complex64 + JSON sidecar) → canonical STFT → `[n×1024]`
dBFS tensor → features.

**Verified on disk 2026-09-18** (do not re-derive):
- DroneRF `~/rf-datasets/DroneRF/original` = 23 `.rar`, each ~21 ASCII CSV segments of ~94 MB ≈ 10^7
  values ≈ **0.25 s at 40 MS/s**. `L`/`H` are two *separate receivers* (lower/upper half of 2.4 GHz).
  Open question that blocks the adapter: real amplitude series (current loader Hilberts it) vs I/Q.
- Zenodo 4264467 = flat `.bin`, **interleaved int16** (±8.7k, LO spike at centre). 480 MB file = 120e6
  complex samples; strong burst occupies 17.3 % of band → **Fs ≈ 60 MS/s, 2.000 s/file** (inferred, not
  documented). `.aria2` siblings = incomplete downloads.
- RUB samples = interleaved float32 @ 50 MS/s, 4.5/14.55 ms fragments (`tests/test_droneid_rub_golden.py`).

**Why the non-obvious rules exist:**
- Zero-padding short records to 1000 frames, stitching DroneRF segments, concatenating its L+H spectra (as
  the source paper does), or upsampling a narrow band to "12 MHz" all fabricate a perfect dataset label.
- Two label objects: `scene` (what was switched on, level 5) vs `window` (what made this energy, level 1-2).
- Group = (dataset, device, run); frequency tiles and 1of2/2of2 halves share the group. Zenodo has one
  recording per (model, band) so no in-dataset run split exists; DroneRFb-DIR is the only set with
  individual-airframe IDs. Always run the receiver-ID probe before quoting any accuracy.
- `_dronerf_label` in `classify/train/data.py` maps DJI Phantom 3 to `dji_ocusync` — it is **Lightbridge**;
  that mislabel is baked into the current bundle.

**How to apply:** treat this as the reference for any dataset ingestion question; re-check the
`[MEASURE]`/`[RESEARCH]` items (DroneRF CSV dtype, Zenodo Fs, DroneRFb-DIR/DroneRFa layout) before code
depends on them.
