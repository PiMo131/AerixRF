"""Datasets for the stage-2 classifier.

Two worlds:

  1. A **synthetic** dataset built from ``aerix_rf.sdr.synth_iq`` so the whole
     training + inference pipeline runs and is testable *now*, with no
     multi-GB downloads. Class labels come from varying the synthesiser's
     bandwidth / cadence / SNR, matching the box's signature classes.

  2. **Loaders for the real public datasets** (DroneRF, DroneDetect,
     DroneRFb-Spectra). Actually fetching them is out of scope here -- they
     live behind IEEE DataPort / Mendeley registration and run to many GB --
     so each loader reads an already-downloaded, locally-prepared copy from a
     configurable root and raises a clear, actionable error if it is missing.
     See ``README.md`` for the prepare steps and URLs.

Everything returns the same shape: ``(specs, labels)`` where ``specs`` are
``dsp.spectrogram.Spectrogram`` objects, so ``features.extract`` is the only
thing that turns them into vectors -- identical to the live path.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ...dsp.spectrogram import Spectrogram, compute
from ...sdr.sim import synth_iq

# The box's four signature classes (stage-2 targets).
CLASSES = ("dji_ocusync", "wifi_drone", "fpv_analog", "noise")
DRONE_CLASSES = ("dji_ocusync", "wifi_drone", "fpv_analog")

# aerix-rf/ -- data.py is .../aerix_rf/classify/train/data.py
_PKG_ROOT = Path(__file__).resolve().parents[3]
# Where fetch_dronerf.py prepares the local subset (gitignored).
_DRONERF_DEFAULT = _PKG_ROOT / "data" / "dronerf"


@dataclass
class Dataset:
    specs: list[Spectrogram]
    labels: list[str]
    sample_rate: float
    fft_size: int
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.specs)


# --- class -> synthesiser knobs -------------------------------------------------
# Each class is a *region* of (bandwidth, cadence) space, not a point, so the
# model must learn the shape rather than memorise one waveform. FPV analog is a
# wide, effectively-continuous carrier (cadence 0 -> back-to-back bursts).
_CLASS_SYNTH = {
    #                 bw_hz range        cadence_s range   burst_ms   drone
    "dji_ocusync":  ((8e6, 12e6),        (0.30, 0.90),     3.0,       True),
    "wifi_drone":   ((1.5e6, 5e6),       (0.02, 0.08),     2.0,       True),
    "fpv_analog":   ((16e6, 20e6),       (0.0, 0.0),       3.0,       True),
    "noise":        ((0.0, 0.0),         (0.0, 0.0),       0.0,       False),
}


def synth_dataset(*, n_per_class: int = 60, sample_rate: float = 20e6,
                  duration_s: float = 0.12, fft_size: int = 1024,
                  classes: tuple[str, ...] = CLASSES,
                  snr_db_range: tuple[float, float] = (8.0, 22.0),
                  seed: int = 0) -> Dataset:
    """Build a labelled synthetic dataset from ``synth_iq``.

    ``sample_rate`` should match the deployment rate you intend to run the model
    at (the PSD feature is a *fraction of band*, so a model is only valid at its
    training rate). ``duration_s`` is kept short so training is fast; a few
    hundred ms is plenty for the burst structure to show.
    """
    rng = np.random.default_rng(seed)
    specs: list[Spectrogram] = []
    labels: list[str] = []
    for cls in classes:
        (bw_lo, bw_hi), (cad_lo, cad_hi), burst_ms, drone = _CLASS_SYNTH[cls]
        for i in range(n_per_class):
            snr = float(rng.uniform(*snr_db_range))
            bw = float(rng.uniform(bw_lo, bw_hi)) if bw_hi > 0 else 10e6
            cad = float(rng.uniform(cad_lo, cad_hi)) if cad_hi > 0 else 0.0
            # unique seed per sample so no waveform repeats
            s = int(rng.integers(1, 2**31 - 1))
            iq = synth_iq(sample_rate, duration_s, drone=drone, snr_db=snr,
                          burst_bw_hz=bw, burst_ms=burst_ms,
                          cadence_s=cad if cad > 0 else 1e-6, seed=s)
            specs.append(compute(iq, sample_rate, fft_size=fft_size))
            labels.append(cls)
    return Dataset(specs=specs, labels=labels, sample_rate=sample_rate,
                   fft_size=fft_size, meta={"source": "synthetic",
                                            "duration_s": duration_s})


def to_binary(labels: list[str]) -> list[str]:
    """Collapse the 4 classes to drone-vs-noise."""
    return ["drone" if l in DRONE_CLASSES else "noise" for l in labels]


# --- real dataset loaders -------------------------------------------------------
# These expect a locally-prepared copy (see README). They deliberately do NOT
# download anything. Roots are configurable via args or AERIX_RF_DATA_ROOT.

def _data_root(root: str | os.PathLike | None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("AERIX_RF_DATA_ROOT")
    if env:
        return Path(env)
    return Path.home() / "rf-datasets"


def _require_dir(p: Path, name: str, hint: str) -> None:
    if not p.is_dir():
        raise FileNotFoundError(
            f"{name} not found at {p}. It is not downloaded here.\n{hint}\n"
            f"See aerix_rf/classify/train/README.md for the prepare steps."
        )


# DroneRF BUI (Bird-of-Unusual-Interest) activity codes -> our signature class.
# A leading 0 = background (no drone). Otherwise the first two digits pick the
# drone: 10xxx = Parrot Bebop, 101xx = Parrot AR (both Wi-Fi control links),
# 110xx = DJI Phantom. DroneRF contains no analog-FPV emitter, so ``fpv_analog``
# is deliberately unmapped here (see README).
def _dronerf_label(bui: str) -> str | None:
    if bui.startswith("0"):
        return "noise"
    if bui.startswith("11"):        # DJI Phantom
        return "dji_ocusync"
    if bui.startswith("10"):        # Parrot Bebop / AR -- Wi-Fi control link
        return "wifi_drone"
    return None


def _dronerf_dir(root: str | os.PathLike | None) -> Path:
    """Resolve the DroneRF CSV directory.

    Priority: explicit ``root`` -> ``$AERIX_RF_DATA_ROOT/DroneRF`` (legacy
    layout) -> the packaged ``aerix-rf/data/dronerf`` the fetch script fills.
    """
    if root is not None:
        return Path(root)
    env = os.environ.get("AERIX_RF_DATA_ROOT")
    if env:
        return Path(env) / "DroneRF"
    return _DRONERF_DEFAULT


def load_dronerf(root: str | os.PathLike | None = None, *,
                 sample_rate: float | None = None, fft_size: int = 1024,
                 window_s: float = 0.02, hop_s: float = 0.01,
                 max_per_class: int | None = None) -> Dataset:
    """DroneRF (Al-Sa'd et al., Mendeley 10.17632/f4c2b4n755.1).

    CSVs of a **real** RF amplitude series, one file per (BUI activity code,
    band, segment); filenames look like ``10000H_0.csv`` / ``00000L_2.csv``.
    ``fetch_dronerf.py`` prepares a local subset under ``aerix-rf/data/dronerf``.

    Each CSV is read as a real signal, sliced into overlapping ``window_s``
    frames, made analytic via a Hilbert transform (real -> complex IQ), and run
    through the box's own ``spectrogram.compute`` so the features match the live
    path. Labels come from the BUI code (see ``_dronerf_label``).

    Sample-rate caveat: DroneRF was captured at **40 MS/s**, not the box's
    20 MS/s. The PSD feature is a *fraction of the captured band*, so a model
    trained here is only valid at 40 MS/s; the bundle records that rate and
    inference warns on a mismatch. ``sample_rate`` defaults to 40e6 for this
    reason -- do not let a caller silently stamp the box rate onto it.

    Grouping: every frame carries its source-CSV path in ``meta['groups']`` so
    the trainer can hold out *whole recordings* for validation (frames from one
    CSV are near-duplicates; a random split would leak and inflate accuracy).
    """
    sr = 40e6 if sample_rate is None else float(sample_rate)
    base = _dronerf_dir(root)
    _require_dir(base, "DroneRF",
                 "Run: python -m aerix_rf.classify.train.fetch_dronerf (Mendeley).")
    from scipy.signal import hilbert  # lazy: scipy only when a real load runs

    win = max(fft_size, int(round(sr * window_s)))
    hop = max(1, int(round(sr * hop_s)))

    specs: list[Spectrogram] = []
    labels: list[str] = []
    groups: list[str] = []
    counts: dict[str, int] = {}
    for csv in sorted(glob.glob(str(base / "**" / "*.csv"), recursive=True)):
        stem = Path(csv).stem
        bui = "".join(ch for ch in stem if ch.isdigit())[:5]
        if len(bui) < 5:
            continue
        label = _dronerf_label(bui)
        if label is None:
            continue
        if max_per_class and counts.get(label, 0) >= max_per_class:
            continue
        amp = np.fromfile(csv, sep=",").astype(np.float32)   # fast, single line
        if amp.size < win:
            continue
        for start in range(0, amp.size - win + 1, hop):
            if max_per_class and counts.get(label, 0) >= max_per_class:
                break
            seg = amp[start:start + win]
            # Skip the all-zero lead-in some captures carry (would be -inf dB).
            if not np.any(np.abs(seg) > 1e-9):
                continue
            iq = hilbert(seg).astype(np.complex64)
            specs.append(compute(iq, sr, fft_size=fft_size))
            labels.append(label)
            groups.append(Path(csv).name)
            counts[label] = counts.get(label, 0) + 1
    if not specs:
        raise RuntimeError(f"DroneRF present at {base} but no usable CSVs parsed.")
    return Dataset(specs, labels, sr, fft_size,
                   {"source": "DroneRF", "groups": groups, "window_s": window_s,
                    "hop_s": hop_s, "counts": counts})


def load_dronedetect(root: str | os.PathLike | None = None, *,
                     sample_rate: float = 60e6, fft_size: int = 1024,
                     window_s: float = 0.02,
                     max_per_class: int | None = None) -> Dataset:
    """DroneDetect (Swinney & Woods, IEEE DataPort). Raw interleaved-float32
    complex IQ (``.dat``) captured at 60 MS/s, filenames encode the drone model.

    Prepared layout expected::

        <root>/DroneDetect/<label>/*.dat

    where ``<label>`` is a directory you name after a signature class
    (``dji_ocusync`` / ``wifi_drone`` / ``fpv_analog`` / ``noise``). We read
    interleaved float32 -> complex64 and window it into frames.
    """
    base = _data_root(root) / "DroneDetect"
    _require_dir(base, "DroneDetect", "Download from IEEE DataPort (Swinney & Woods).")
    n = int(sample_rate * window_s)
    specs: list[Spectrogram] = []
    labels: list[str] = []
    counts: dict[str, int] = {}
    for dat in sorted(glob.glob(str(base / "*" / "*.dat"))):
        label = Path(dat).parent.name
        if max_per_class and counts.get(label, 0) >= max_per_class:
            continue
        raw = np.fromfile(dat, dtype=np.float32)
        if raw.size < 2 * n:
            continue
        iq = (raw[0:2 * n:2] + 1j * raw[1:2 * n:2]).astype(np.complex64)
        specs.append(compute(iq, sample_rate, fft_size=fft_size))
        labels.append(label)
        counts[label] = counts.get(label, 0) + 1
    if not specs:
        raise RuntimeError(f"DroneDetect present at {base} but no usable .dat parsed.")
    return Dataset(specs, labels, sample_rate, fft_size, {"source": "DroneDetect"})


def load_dronerfb_spectra(root: str | os.PathLike | None = None) -> tuple[np.ndarray, list[str]]:
    """DroneRFb-Spectra: pre-computed spectrogram *images* (one per sample),
    organised in per-class subdirectories.

    Prepared layout expected::

        <root>/DroneRFb-Spectra/<label>/*.png

    Returns ``(X, labels)`` where ``X`` is [N, H*W] flattened grayscale in
    [0,1] resampled to ``features.SPEC_SHAPE`` -- already a 'spec'-kind feature
    matrix, so it feeds ``train.train_model(..., precomputed=...)`` directly.
    """
    from PIL import Image
    from .features import SPEC_SHAPE

    base = _data_root(root) / "DroneRFb-Spectra"
    _require_dir(base, "DroneRFb-Spectra", "Download from the DroneRFb-Spectra release.")
    rows: list[np.ndarray] = []
    labels: list[str] = []
    for img_path in sorted(glob.glob(str(base / "*" / "*.png"))):
        label = Path(img_path).parent.name
        im = Image.open(img_path).convert("L").resize(SPEC_SHAPE[::-1])
        a = np.asarray(im, dtype=np.float32) / 255.0
        a = a - np.median(a)
        rows.append(a.reshape(-1))
        labels.append(label)
    if not rows:
        raise RuntimeError(f"DroneRFb-Spectra present at {base} but no PNGs parsed.")
    return np.stack(rows), labels
