# Stage-2 signature classifier — training pipeline

Trains the model behind `aerix_rf.classify.model.classify_spectrogram()`. The
box labels each 1-second frame with a `signature_class` in
`{dji_ocusync, wifi_drone, fpv_analog, noise}`. This pipeline learns that label
from spectrogram/PSD features, dropping in behind the existing rule-based
classifier (which stays as the fallback when no model file is present).

**Live features == training features.** Every path here builds its feature
vector from the box's own `dsp.spectrogram.compute()` via `features.py`, the
exact code the live loop uses. Do not add a second feature extractor.

```
train/
  features.py   IQ / spectrogram -> fixed-length feature vectors (psd | spec)
  data.py       synthetic dataset (synth_iq) + loaders for the real datasets
  train.py      sklearn RandomForest/SVM on PSD features, saves a joblib bundle
```

## Quick start (synthetic — runs now, no downloads)

The synthetic dataset is built from `aerix_rf.sdr.sim.synth_iq`, with class
labels created by varying bandwidth / cadence / SNR. It exists so the whole
pipeline is runnable and testable immediately.

To avoid racing parallel `uv sync` runs, use a **private env + ephemeral deps**:

```bash
cd aerix-rf
export UV_PROJECT_ENVIRONMENT=.venv-train

# train the default 4-class model at the field sample rate (20 MS/s)
uv run --with scikit-learn,joblib \
  python -m aerix_rf.classify.train.train \
  --dataset synth --model rf --feature psd \
  --sample-rate 20e6 --out models/signature.joblib

# tests
uv run --with scikit-learn,joblib pytest tests/test_classify.py -q
```

Useful flags: `--binary` (drone-vs-noise), `--model svm`, `--feature spec`,
`--n-per-class N`, `--duration-s S`, `--sample-rate HZ`, `--fft-size N`.

## Using a trained model on the box

`classify.model` loads the bundle from `$AERIX_RF_MODEL`, else the packaged
default `aerix-rf/models/signature.joblib`. If neither exists (or joblib/sklearn
is absent, or the file is corrupt), it silently falls back to the rule-based
classifier — the 1 Hz loop never dies on a bad model.

```bash
export AERIX_RF_MODEL=/path/to/signature.joblib
```

The saved artefact is a **bundle** (dict): the fitted estimator plus the feature
config (`feature_kind`, `psd_bins`, `spec_shape`), the class list, and the
`sample_rate` / `fft_size` it was trained at. Inference reads the extraction
params from the bundle. Note the PSD feature is a *fraction of the captured
band*, so **a model is only valid at its training `sample_rate`** — train at the
rate the box runs at (default 20 MS/s); a mismatch is logged at inference.

---

## Real public datasets

None of these are downloaded here (IEEE DataPort / Mendeley registration,
multi-GB). Download + prepare a local copy, point `--data-root` (or
`$AERIX_RF_DATA_ROOT`, default `~/rf-datasets`) at it, then train with
`--dataset dronerf|dronedetect`. Feature/label logic mirrors
[IQTLabs/RFClassification](https://github.com/IQTLabs/RFClassification) (PSD +
SVM, and downsampled-spectrogram features).

### DroneRF (Al-Sa'd et al.) — raw amplitude series, CSV  ✅ trained here

**This is the real dataset the shipped `models/dronerf.joblib` is trained on.**

- Data (Mendeley Data): <https://data.mendeley.com/datasets/f4c2b4n755/1>
  (DOI [10.17632/f4c2b4n755.1](http://dx.doi.org/10.17632/f4c2b4n755.1))
- Code / description: <https://github.com/Al-Sad/DroneRF>
- Access: **free, fully open** — no login needed for the public-files API.
- **Size: 4.03 GB**, 23 `.rar` archives in 4 folders (Background, Bepop, AR,
  Phantom). Each archive holds ten ~99 MB CSV segments (a single line of
  comma-separated RF amplitudes, captured at **40 MS/s**).
- Contents: 227 segments, 3 drones (DJI Phantom, Parrot Bebop, Parrot AR) plus
  background RF (ambient Wi-Fi/Bluetooth, **no drone**). Files are named by a
  BUI activity code; a leading `0` = background, otherwise a drone is present.
  Each recording is split into a high-band (`…H`) and low-band (`…L`) half.

#### Download (the exact commands that worked)

The full set is >3 GB, so `fetch_dronerf.py` grabs a **representative subset**
(background + all 3 drones, both bands; ~1.4 GB downloaded → ~1 GB of truncated
CSVs kept) and can be pointed at the full set by editing its `FILES` list. It writes
to the gitignored `aerix-rf/data/dronerf/`.

```bash
cd aerix-rf
export UV_PROJECT_ENVIRONMENT=.venv-train
# streams each .rar, verifies sha256, extracts a capped CSV prefix, deletes the .rar
uv run --with libarchive-c,requests \
  python -m aerix_rf.classify.train.fetch_dronerf
# -> Prepared 20 CSV segments in aerix-rf/data/dronerf/csv
```

Notes that cost time to discover:
- The archives are **RAR3 with a method `7z` cannot decode** ("Unsupported
  Method"); `libarchive` (via `libarchive-c`) decodes them fine — no `unrar`.
- Per-file public download URL (no auth), discovered from the site's own API:
  `GET https://data.mendeley.com/public-api/datasets/f4c2b4n755/folders/1`
  lists the 4 folders; `…/files?folder_id=<FOLDER_ID>&version=1` lists each
  file with a `content_details.download_url` of the form
  `https://data.mendeley.com/public-files/datasets/f4c2b4n755/files/<FILE_ID>/file_downloaded`
  (302 → S3, range-request friendly). The full `(filename, id, sha256)` list for
  the subset is baked into `classify/train/fetch_dronerf.py`.
- **Full set:** list every folder's files as above and drop the per-archive
  segment cap in `fetch_dronerf.py` (`SEGMENTS_PER_RAR`), then extract each CSV
  in full (remove `CAP_BYTES`).

Prepared layout (what `data.load_dronerf()` reads — recurses for `*.csv`):

```
aerix-rf/data/dronerf/csv/<BUI><H|L>_<segment>.csv      # e.g. 00000H_0.csv, 11000L_1.csv
```

Default root is `aerix-rf/data/dronerf` (override with `--data-root` or the
legacy `$AERIX_RF_DATA_ROOT/DroneRF`).

#### Label map (BUI → signature class)

The loader reads each CSV, slices it into overlapping 20 ms frames, forms an
analytic (Hilbert) IQ signal per frame, and runs it through the box's own
`spectrogram.compute` (identical to the live feature path). Labels:

| BUI prefix | drone | class |
|---|---|---|
| `0…`  (`00000`) | — background/ambient RF | `noise` |
| `10…` (`1000x` Bebop, `1010x` AR) | Parrot, Wi-Fi control link | `wifi_drone` |
| `11…` (`11000`) | DJI Phantom | `dji_ocusync` |

DroneRF has **no analog-FPV emitter**, so `fpv_analog` is intentionally left
unmapped (rather than forcing a wrong label). `--binary` collapses to
drone-vs-noise.

#### Train (the exact invocation) + results

```bash
# 3-class model shipped as models/dronerf.joblib
uv run --with scikit-learn,joblib,scipy python -m aerix_rf.classify.train.train \
  --dataset dronerf --model rf --feature psd --out models/dronerf.joblib

# binary drone-vs-background
uv run --with scikit-learn,joblib,scipy python -m aerix_rf.classify.train.train \
  --dataset dronerf --model rf --feature psd --binary \
  --out models/dronerf-binary.joblib
```

Validation uses a **recording-grouped split** (whole CSVs held out — frames
from one CSV are near-duplicates, so a random split would leak and read ~100 %).
On the prepared subset (237 frames: 72 noise / 96 wifi_drone / 69 dji_ocusync,
from 20 recordings):

- **Binary drone-vs-background:** seed-0 val accuracy **1.00**; across 6 seeds
  mean **0.92** (0.86–1.00). Confusion (seed 0): 46/46 drone, 12/12 noise — **zero
  drone↔background errors.** This is the headline: a real drone is cleanly
  separated from real background RF (including ambient Wi-Fi), the exact domain
  gap the synthetic-only model failed on.
- **3-class:** seed-0 val accuracy **0.948**; across 6 seeds mean **0.88**
  (0.80–0.95). Seed-0 confusion (rows = true):

  ```
               dji_ocusync   noise   wifi_drone
  dji_ocusync       20         0          2
  noise              0        12          0
  wifi_drone         1         0         23
  ```

  `noise` is perfectly separated from both drones; the only confusion is
  Phantom↔Parrot (the two drone families), which the binary model doesn't care
  about. Seed spread reflects the small recording count in this demonstrator
  subset — extract more segments/full CSVs for a tighter number.

#### ⚠️ Sample-rate & signal caveats (why this bundle is DroneRF-specific)

- **40 MS/s, not 20.** DroneRF is captured at 40 MS/s; the PSD feature is a
  *fraction of the captured band*, so this model is **only valid at 40 MS/s**.
  `load_dronerf` owns that rate (defaults to `40e6`, never overridden by
  `--sample-rate`) and the bundle records `sample_rate = 40e6`; `classify.model`
  logs a warning if a live 20 MS/s frame is fed to it. To deploy on the 20 MS/s
  box, retrain from IQ decimated to the box rate.
- **Analytic (real) signal.** DroneRF stores a real amplitude series; the loader
  makes it analytic via a Hilbert transform, which occupies only the positive
  half-band — unlike the box's genuinely-complex IQ. Combined with the rate
  difference, treat this bundle as a **bench demonstrator that proves the real
  data separates**, not a drop-in box model. `H` and `L` band halves are used as
  independent samples (extra within-class diversity).

### DroneDetect (Swinney & Woods, Univ. of Essex) — raw IQ, `.dat`

- Data (IEEE DataPort): <https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine>
- Paper record: <https://dblp.org/rec/data/10/SwinneyW22.html>
- Access: free IEEE DataPort account (open-access). Large (many GB).
- Contents: 7 UAS models (DJI Mavic 2/Pro/Pro 2/Mini, Inspire 2, Phantom 4,
  Parrot Disco), captured on a **Nuand bladeRF at 60 MS/s**, 2 s per recording
  (1.2×10⁸ complex samples), interleaved float32. Four interference subsets
  (clean / Bluetooth / Wi-Fi / both) and three flight modes (on/hover/fly).

Prepared layout expected by `data.load_dronedetect()` — sort `.dat` files into
one directory per signature class you want to train:

```
<root>/DroneDetect/<label>/*.dat        # label in {dji_ocusync, wifi_drone, fpv_analog, noise}
```

The loader reads interleaved float32 → complex64 and windows it (default 20 ms
frames at 60 MS/s). `--sample-rate` must match the intended deployment rate; if
you train from 60 MS/s captures, resample/decimate to the box rate first so the
fractional-band feature transfers.

### DroneRFb-Spectra — pre-computed spectrogram arrays

- Data (IEEE DataPort): <https://ieee-dataport.org/documents/dronerfb-spectra-rf-spectrogram-dataset-drone-recognition>
- Access: IEEE DataPort (subscription / IEEE membership for full download).
- Contents: 14,460 samples across 7 brands (DJI, Vbar, FrSky, Futaba, Taranis,
  RadioLink, Skydroid), captured on a USRP across three ISM bands in urban
  scenarios. Each spectrogram is **512×512**, made by STFT of a 50 ms IQ slice
  (distributed as `.npy` arrays). Good for the `spec` (image) feature / CNN.
- A newer extension, **DroneRFz / DroneRFB** (512×512 spectrograms, 7 models to
  1 km + 2 DJI at 50 m, heavier Wi-Fi/BT interference), is at
  <https://ieee-dataport.org/documents/dronerfz-and-dronerfb-extension-rf-spectrogram-dataset-drone-recognition-across-diverse>.

Prepared layout expected by `data.load_dronerfb_spectra()` (one dir per class).
The loader reads image files; convert the distributed `.npy` arrays to
grayscale PNGs first, or adapt the loader to `np.load` directly:

```
<root>/DroneRFb-Spectra/<label>/*.png      # or *.npy with a one-line loader tweak
```

It returns a ready `(X, labels)` matrix (`spec`-kind features) you feed straight
into `train.train_sklearn()` — bypass `--dataset` and call it directly.

### RFUAV (kitoweeknd et al.) — raw IQ benchmark, 35 drone types

- Code + data pointers: <https://github.com/kitoweeknd/RFUAV>
  (readme: <https://github.com/kitoweeknd/RFUAV/blob/main/readme.md>)
- Paper: *RFUAV: A Benchmark Dataset for UAV Detection and Identification*,
  <https://arxiv.org/html/2503.09033v2>
- Access: per the repo (raw IQ, high-SNR; check the repo for the current
  download link/license). A large modern benchmark; its two-stage FFT/STFT
  baseline is close in spirit to this box's detect→classify split.

To use RFUAV, decimate/window its raw IQ to the box sample rate and adapt a
loader modelled on `load_dronedetect()` (same interleaved-IQ → `compute()` →
`features.extract()` path).

---

## Optional: torch CNN (planned)

Default is scikit-learn (light, no torch). A CNN on the `spec` feature is a
planned `--model cnn` slot — **not yet implemented**. The `train-cnn`
optional-dependency group reserves the torch dependency for it:

```bash
uv sync --extra train --extra train-cnn      # adds torch (for the future CNN path)
```

(Not required for the sklearn pipeline or the tests.)

## References

- IQTLabs/RFClassification — PSD+SVM and spectrogram/PSD-image transfer
  learning, the approach mirrored here: <https://github.com/IQTLabs/RFClassification>
