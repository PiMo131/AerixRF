# AERIX RF — Common dataset preprocessing & normalisation layer

Status: design memo (rf-dsp-specialist, 2026-09-18), Workstream D. Companion to
`docs/design/canonical-representation.md` (rate/format/STFT decisions, referenced as A3-D*).
Tags: `[MEASURE]` needs a number, `[RESEARCH]` needs the librarian, `[USER]` needs a call.

## 0. Conclusion

Every dataset and every live session converges on one artefact pair: a **canonical window** (complex64 at
15.36 MS/s, ≤1.000 s, absolute-Hz axis) plus a **JSON sidecar** carrying provenance, receiver state, label
*with its evidence level*, and split group. Tensors (`[T×1024]` float32 dBFS, 1 ms frames) are the training
corpus; canonical IQ is kept only for curated decode subsets. The loaders in
`aerix_rf/classify/train/data.py` cannot reach this — they stamp native rates, never resample, group by CSV
instead of by session, and use a fraction-of-band feature axis (A3-D11) — so they are replaced.

Two rules do most of the work: **never fabricate signal to make shapes match** (no zero-padding, no
stitching, no upsampling a narrow band and calling it 12 MHz), and **separate what was in the room from
what is in the window**.

## 1. Pipeline stages

```
S0 original/        immutable, read-only, sha256 per file          (never rewritten)
S1 adapter          per-format decoder -> native complex baseband stream + declared native metadata
S2 conditioning     band-slice/mix -> integer decimate to >=19.2 MS/s -> one rational stage -> 15.36
S3 windowing        integer 1 ms frame grid; target 1.000 s = 15 360 000 samples; no padding
S4 canonical window <uid>.c64.npy (complex64, +-1.0) + <uid>.json sidecar
S5 canonical STFT   FFT 1024 / Hann / hop 512, coherent-gain normalised, dBFS  (A3-D7)
S6 ML tensor        linear block-mean x30 -> [n_frames x 1024] float32 dBFS    (A3-D9)
S7 features         absolute-Hz axis over the usable mask; floor subtraction at feature time (A3-D10)
```

Entry points differ per dataset; the sidecar records `stage_entry` so nothing claims more provenance than
it has: `S1` (raw IQ), `S3` (pre-segmented IQ vectors, e.g. the Kaggle noisy set), `S6_image`
(spectrogram-only, never joins the canonical tensor corpus).

**S1 adapters** (one module per format, no DSP beyond dtype conversion):
* **DroneRF** — `.rar` of ASCII CSV segments (verified: `RF Data_10000_H.rar` = 21 files, ~94 MB each,
  `RF Data_<BUI>_<L|H>/<BUI><L|H>_<seg>.csv`). 40 MS/s; `L`/`H` are two *separate receivers* covering the
  lower and upper half of 2.4 GHz. Stream `7z x -so` into the parser — never materialise the ~40 GB of
  ASCII. Each segment is ~10^7 values ≈ **0.25 s**.
  Two hard rules: (a) never stitch segments into 1 s windows — separate captures, fabricated continuity;
  (b) never concatenate L and H spectra as the source paper does — the receivers are not phase-coherent, so
  the joint 2048-bin spectrum is an artefact. `[MEASURE]` real amplitude series (current loader assumes so
  and applies `hilbert`) vs interleaved I/Q: count values per segment and test conjugate symmetry. Guessing
  costs a factor of two in time or in band.
* **Zenodo 4264467 (2020)** — flat `.bin`, **interleaved int16 complex** (verified: ±8.7k values, centre-bin
  LO spike, 480 000 000 B = 120e6 complex samples). Rate undocumented locally; the strong burst occupies
  17.3 % of the captured band, so for a ~10 MHz OcuSync downlink **Fs ≈ 60 MS/s, 2.000 s/file** — working
  assumption, `[RESEARCH]` confirm. `*_1of2/_2of2` are halves of one recording: concatenate before S2, one
  group. Refuse any `.bin` with a sibling `.aria2` (incomplete download).
* **RUB-SysSec** — interleaved float32 at 50 MS/s (`tests/test_droneid_rub_golden.py` is authoritative),
  pre-segmented 4.5 / 14.55 ms burst slices. *Fragments*, not windows: true `duration_s`,
  `short_window: true`, decode-only, never padded. AGPL — stays under `~/rf-datasets/`, never in the repo.
* **DroneRFb-DIR / DroneRFa (SciDB)** — zip of per-segment raw IQ; dtype, scaling, rate unconfirmed
  `[RESEARCH]`. Write the adapter against the dataset's own metadata, not a guess; until then it raises.
* **Spectrogram-only (DroneRFb-Spectra, DroneRFz)** — 512x512 images, unknown STFT parameters, unknown dB
  reference, colormap quantisation. `S6_image`, `dbfs_reference: unknown`; auxiliary/pretraining only, never
  reported in the same table as canonical-tensor results.

**S2 rules** (from A3-D14/15, §7 of the A3 memo):
* Band-slice first when the target occupies < half the source band: mix to DC -> FIR LPF -> integer
  decimate to the smallest rate ≥ **19.2 MS/s** -> one `resample_poly`. 40 -> ÷2 -> 96/125; 60 -> ÷2 ->
  64/125; 50 and 100 `[MEASURE: exact integer pair]`.
* Transition band strictly between 12.0 and 15.36 MHz; stopband ≥ 60 dB. A decimated Wi-Fi blocker folding
  into the usable band becomes a phantom emitter, then a phantom class.
* **Source wider than 12 MHz** (DroneRF 20, Zenodo 60, DroneRFa 100): *tile* on a 12 MHz stride, do not
  centre-crop; each slice records its `center_freq_hz` and offset in `resample_chain`. Extra
  emitter-centred slices are allowed but carry `slice_reason: emitter_centred` and the parent group.
* **Source narrower than 12 MHz**: still resample to 15.36 MS/s (universal grid) but set `usable_bw_hz` to
  the true width and `band_deficit: true`; features use the *intersection* mask. Never expose the dataset's
  filter skirt to the classifier — a receiver fingerprint that scores brilliantly and transfers to nothing.

**S3 windowing.** Target 1.000 s = 15 360 000 samples; short sources give short windows with true
`duration_s` and `n_frames = round(1000*duration_s)`. **Zero-padding to 1000 frames is forbidden** — a
constant silent tail is a perfect dataset label a CNN finds in one epoch. Batching masks, or samples fixed
0.25 s sub-tensors.

## 2. Sidecar schema (`<uid>.json`, `schema_version: 1`) — superset of `session.json` (A3 §8)

| Group | Fields |
|---|---|
| identity | `uid` (hash, §5), `dataset_id`, `recording_id`, `source_file`, `source_sha256`, `device_id`, `run_id`, `capture_group`, `channel_id`, `slice_index`, `slice_reason` |
| signal | `sample_rate_hz` (15.36e6), `duration_s`, `n_samples`, `center_freq_hz`, `bandwidth_hz`, `usable_bw_hz`, `band_deficit`, `short_window` |
| source | `original_rate_hz`, `original_dtype`, `original_center_freq_hz`, `original_bw_hz`, `iq_full_scale_source`, `iq_format_source`, `resample_chain[]` = ordered `{op, up, down, mix_hz, numtaps, window, cutoff_hz, stopband_db}` |
| receiver | `receiver {type, backend, firmware, driver, antenna}`, `gain {mode: manual\|agc\|unknown, db, stages, changed_within_window}`, `dc_offset_corrected`, `quadrature_corrected`, `clock {source, pps_locked}` |
| levels | `noise_floor_dbfs`, `rssi_dbfs`, `occupied_bw_hz`, `bw_saturated`, `calibrated: false` |
| labels | `scene {...}`, `window {...}` (see §3), each with `evidence_level` 1-5 and `label_source` |
| bookkeeping | `stage_entry`, `preproc_version`, `config_sha256`, `code_version`, `artifact_sha256`, `split`, `created_at` |

`gain.mode: "unknown"` is mandatory wherever AGC state is undocumented — which is most public data. Any
window with `gain.mode != "manual"` is excluded from absolute-RSSI features (A3-D12), so most public data
trains on shape, not level. An honest constraint, not a bug.

## 3. Label taxonomy

Two independent label objects, because conflating them is the main way datasets lie: `scene` = what the
operator had switched on (usually **evidence level 5**, constant over a run); `window` = what produced the
energy in *this* slice (level **1-2** unless a decode raised it). A DroneRF "drone on" window in a slice
where the drone is not transmitting is not a drone window.

Hierarchy — each level an explicit enum containing both `unknown` and `not_applicable` (different things):

* `emitter_class`: background | wifi | bluetooth | other_ism | drone_link | mixed | unknown
* `link_family`: ocusync | lightbridge | wifi_drone | fhss_rc | analog_fpv | unknown | not_applicable
* `link_role`: uplink_control | downlink_video | broadcast_droneid | unknown | not_applicable
* `manufacturer` / `model` / `individual_id` (dataset serial or airframe id), each with `unknown`
* `activity`: off | powered_idle | connected_idle | hovering | flying | flying_video | unknown

One imputation rule only: `model -> manufacturer` and `model -> link_family` via an explicit versioned
table; never the reverse. `mixed` is a real answer for urban captures and must not be collapsed to the
strongest emitter. Per-dataset support:

| Dataset | emitter_class | link_family | model | individual_id | activity | scene evidence |
|---|---|---|---|---|---|---|
| DroneRF | from BUI leading digit (0 = background) | wifi_drone (Parrot) / lightbridge (Phantom 3 — **not** OcuSync) | 3 models | unknown | 4 modes from BUI digits 3-5 | 5 |
| Zenodo 2020 | drone_link or background per slice | per model | 10 models | unknown (1 airframe each) | control vs video from filename | 5 (anechoic) |
| RUB | drone_link | ocusync | mavic_air_2 / mini_2 | unknown | flying | 5 + level-4 decode |
| DroneRFb-DIR | drone_link / background | FCS vs VTS | 6 types | **3 individuals per type** | unknown | 5 `[RESEARCH]` |
| DroneRFa | drone_link / wifi / bluetooth | unknown | unknown | unknown | unknown | `[RESEARCH]` |
| DroneRFb-Spectra | per RC vendor | fhss_rc mostly | vendor only | unknown | unknown | 5, image-only |

Note the existing `_dronerf_label` maps DJI Phantom 3 to `dji_ocusync`. Phantom 3 is **Lightbridge**, not
OcuSync. That mislabel is currently baked into the trained bundle and must not survive this rework.

## 4. Leakage-safe splitting

Group key = `(dataset_id, device_id, run_id)`; splits assigned per **group**, never per frame. Frequency
tiles of one recording, DroneRF L/H halves, Zenodo `1of2/2of2` halves and all segments of one session share
a group. Adjacent 1 s windows share emitter, channel, receiver state and noise realisation, so a random
frame split inflates accuracy to meaninglessness.

Support: DroneRF — group = `(BUI, band)` archive (~5 s session), not the CSV (today's loader groups per CSV
= still leaky). Zenodo — one recording per (model, band): no in-dataset run split exists, only model-level
hold-out. RUB — 2 fragments, evaluation only. DroneRFb-DIR — the only set supporting "unseen individual of
a seen model". DroneRFa/Spectra — group metadata unknown; assume one group per class.

Hold-out tiers, reported separately and never averaged:
* **A — in-dataset, group held out.** Upper bound; label it "same receiver, unseen run".
* **B — leave-one-dataset-out.** The honest generalisation number.
* **C — cross-receiver.** Public-trained model evaluated on our own HackRF captures.
* **D — ANTSDR ambient hold-out**, never used for training or model selection: hours of no-drone ambient
  across the working day, Wi-Fi/BT-heavy scenes, and a known drone with operator truth. Only Tier D may
  back an operational PD/PFA claim.

Mandatory control: a **receiver-ID probe** — a classifier predicting `dataset_id` from the same features.
Its (likely near-perfect) accuracy measures the confound, and is why Tier A is never quoted alone.
Anechoic caveat: Zenodo's empty slices are *not* a background class for PFA work — a model taught
"quiet = no drone" fires on every Wi-Fi burst in the field.

## 5. Storage budget

Canonical IQ complex64 = **122.88 MB per 1.000 s window**; ML tensor `[1000x1024]` float32 = **4.096 MB**;
a 0.25 s DroneRF window = 30.7 MB IQ / 1.02 MB tensor.

| Dataset | usable signal | 12 MHz tiles | window-seconds | IQ if kept | tensors |
|---|---|---|---|---|---|
| DroneRF | ~115 s @ 40 MS/s (23 archives, 0.25 s segments) | 2 per half-band | ~230 | ~28 GB | ~0.95 GB |
| Zenodo 2020 | ~36 s @ 60 MS/s (8.6 GB int16) | 5 | ~180 | ~22 GB | ~0.74 GB |
| RUB | 19 ms | 1 | 0.02 | 2.4 MB | negligible |
| DroneRFb-DIR | 64 GB, rate unknown | `[MEASURE]` | `[MEASURE]` | do not keep IQ wholesale | est. 2-6 GB |
| DroneRFa | ~570 GB (not downloaded) | — | — | never | `[USER]` before download |

Policy: **tensors always, IQ selectively** — keep IQ for decode subsets (RUB, Zenodo DJI 2.4 GHz burst
slices, our golden sessions), a stratified ~5 % per dataset for debugging, and anything hand-flagged in
error analysis. The rest is deleted after S6, re-derivable from `original/` + config. Cap `[USER]` (~250 GB).

## 6. Determinism & provenance

* `uid = sha256(source_sha256 || source_file || slice_spec || window_index || config_sha256)[:16]`; same
  inputs + config => same uid, byte-identical artefact.
* The preprocessing config is a versioned file (`configs/preprocess/v1.json`) hashed into every sidecar with
  `code_version`. **Do not rely on `scipy.signal.resample_poly` defaults**: design filters explicitly
  (numtaps/window/cutoff in `resample_chain`) so a scipy upgrade cannot silently change the corpus.
  `artifact_sha256` covers the `.npy`; `prepare --verify` recomputes a random 1 % and fails loudly.
* A flat `index.jsonl` (one row per window, all scalar sidecar fields) is the only thing trainers and
  splitters read — never a directory walk.
* Reproduce: `python -m aerix_rf.datasets.prepare --config configs/preprocess/v1.json --dataset dronerf
  --out ~/rf-datasets/DroneRF/canonical [--tiles all] [--keep-iq curated]`.

## 7. Implementation plan for `python-builder`

Bounded and ordered; every acceptance test builds its own **synthetic mini-dataset** (fake CSV/rar, fake
int16 `.bin` with a known tone) — no downloads.

1. **T1 `aerix_rf/datasets/spec.py` + `index.py`** — sidecar dataclass, JSON schema v1, §3 enums, index
   read/write. *Accept:* round-trip equality; missing field and unknown enum rejected; `unknown` vs
   `not_applicable` preserved distinctly.
2. **T2 `datasets/resample.py`** — mix/band-slice + two-stage canonical resampler with explicit FIR taps,
   emitting `resample_chain`. *Accept:* a +3 MHz tone lands within 1 bin after the chain; a +18 MHz tone
   (source 40 MS/s) is ≥60 dB down; output byte-identical on repeat; chain metadata replays the taps.
3. **T3 `window.py` + `tensor.py`** — 1 ms-grid windowing (no padding), canonical STFT ->
   `[n_frames x 1024]` dBFS. *Accept:* full-scale tone reads 0.0 dBFS ±0.1 (coherent-gain fix);
   `n_frames == round(1000*duration_s)`; 0.25 s input gives 250 frames, not 1000 with zeros.
4. **T4 adapters** `dronerf.py`, `zenodo2020.py` on synthetic fixtures; filename -> label table; groups.
   *Accept:* known tone lands at the right absolute Hz in the right tile; `.bin` with sibling `.aria2`
   refused; DroneRF L/H share `run_id`, differ in `channel_id`.
5. **T5 `split.py`** — deterministic group-hash splitter, leave-one-dataset-out / leave-one-device-out
   iterators. *Accept:* no group spans splits; stable under input reordering; a deliberately random split
   fails the built-in leakage check.
6. **T6 rework `classify/train/features.py`** to the absolute-Hz axis over the usable mask, with
   `band_deficit` handling. *Accept:* the same synthetic emitter at 15.36 and 20 MS/s gives feature vectors
   within tolerance — the portability property that is the point of the change.
7. **T7 first real run**: DroneRF (one BUI/band pair) + two Zenodo files; report window counts, storage and
   the §4 receiver-ID probe accuracy before any classifier result is quoted.

`load_dronedetect`, `load_dronerfb_spectra` and the DroneRF Hilbert path retire at T4/T7; keep
`synth_dataset` (retuned to 15.36 MS/s) as fixture generator, and keep the `AERIX_RF_DATA_ROOT` /
no-downloads-in-library discipline.

## 8. Open items

* `[MEASURE]` DroneRF CSV: real amplitude series or interleaved I/Q. Blocks T4 correctness.
* `[MEASURE]`/`[RESEARCH]` Zenodo 4264467 exact Fs (assumed 60 MS/s / 2.000 s per file, from 17.3 %
  occupancy of a ~10 MHz burst) and its int16 full scale; confirm from the record's loader script.
* `[RESEARCH]` DroneRFb-DIR/DroneRFa file layout, dtype, rate, metadata schema, individual-ID encoding;
  DroneRF's receiver/antenna chain (two USRP front ends? shared clock?).
* `[MEASURE]` filter design for the ≥60 dB stopband at each decimation ratio (taps vs cost).
* `[USER]` derived-storage cap; whether DroneRFa's ~570 GB is wanted at all; whether a Tier-D ANTSDR
  ambient set can be captured on site and for how long; and whether a HackRF/ANTSDR side-by-side ambient
  capture is possible — the only clean way to separate receiver confound from emitter signal in Tier C.
