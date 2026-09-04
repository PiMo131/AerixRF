"""Train the stage-2 signature classifier and save a drop-in model bundle.

Default is a light scikit-learn model (RandomForest) on PSD features -- no
torch, trains in seconds, loads instantly on the box. A torch CNN on the
'spec' feature is a planned ``--model cnn`` slot (not yet implemented); the
``train-cnn`` optional-dependency group reserves the torch dependency for it.

The saved artefact is a *bundle* (dict), not a bare estimator, so inference
never has to re-guess the feature config::

    {
      "model":        fitted estimator (sklearn) or state (cnn),
      "kind":         "sklearn" | "cnn",
      "feature_kind": "psd" | "spec",
      "psd_bins":     int,
      "spec_shape":   (int, int),
      "classes":      [...],
      "sample_rate":  float,   # model is only valid at this rate
      "fft_size":     int,
      "version":      str,
    }

CLI::

    UV_PROJECT_ENVIRONMENT=.venv-train \
      uv run --with scikit-learn,joblib \
      python -m aerix_rf.classify.train.train --dataset synth --out models/signature.joblib
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import data as data_mod
from . import features as feat

VERSION = "rf-1"

# Default model path, resolved relative to the *package* (aerix-rf/models/...),
# not the cwd -- the box is not launched from the repo root.
_PKG_ROOT = Path(__file__).resolve().parents[3]      # .../aerix-rf
DEFAULT_MODEL_PATH = _PKG_ROOT / "models" / "signature.joblib"


@dataclass
class TrainResult:
    accuracy: float
    val_accuracy: float
    n_train: int
    n_val: int
    classes: list[str]
    report: str
    out_path: str


def features_matrix(ds: data_mod.Dataset, feature_kind: str = "psd") -> np.ndarray:
    """Dataset -> [N, D] feature matrix using the shared extractor."""
    return np.stack([feat.extract(s, feature_kind) for s in ds.specs])


def _split(X: np.ndarray, y: list[str], val_frac: float, seed: int):
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    n_val = max(1, int(len(y) * val_frac))
    val, tr = idx[:n_val], idx[n_val:]
    ya = np.asarray(y)
    return X[tr], ya[tr], X[val], ya[val]


def train_sklearn(X: np.ndarray, y: list[str], *, algo: str = "rf",
                  val_frac: float = 0.25, seed: int = 0):
    """Fit a scikit-learn classifier; return (fitted_model, TrainResult-ish dict)."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.svm import SVC
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, classification_report

    Xtr, ytr, Xval, yval = _split(X, y, val_frac, seed)
    if algo == "svm":
        model = make_pipeline(StandardScaler(),
                              SVC(C=10.0, kernel="rbf", probability=True,
                                  random_state=seed))
    else:
        model = RandomForestClassifier(n_estimators=200, max_depth=None,
                                       random_state=seed, n_jobs=-1)
    model.fit(Xtr, ytr)
    tr_acc = float(accuracy_score(ytr, model.predict(Xtr)))
    val_acc = float(accuracy_score(yval, model.predict(Xval)))
    report = classification_report(yval, model.predict(Xval), zero_division=0)
    classes = sorted(set(y))
    return model, {"accuracy": tr_acc, "val_accuracy": val_acc,
                   "n_train": len(ytr), "n_val": len(yval),
                   "classes": classes, "report": report}


def build_bundle(model, *, kind: str, feature_kind: str, classes: list[str],
                 sample_rate: float, fft_size: int) -> dict:
    return {
        "model": model,
        "kind": kind,
        "feature_kind": feature_kind,
        "psd_bins": feat.PSD_BINS,
        "spec_shape": feat.SPEC_SHAPE,
        "classes": classes,
        "sample_rate": sample_rate,
        "fft_size": fft_size,
        "version": VERSION,
    }


def save_bundle(bundle: dict, out_path: str | Path) -> Path:
    import joblib
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out)
    return out


def train_and_save(*, dataset: str = "synth", feature_kind: str = "psd",
                   algo: str = "rf", out_path: str | Path = DEFAULT_MODEL_PATH,
                   sample_rate: float = 20e6, duration_s: float = 0.12,
                   fft_size: int = 1024, n_per_class: int = 60,
                   binary: bool = False, seed: int = 0,
                   data_root: str | None = None) -> TrainResult:
    """End-to-end: build/load dataset -> features -> fit sklearn -> save bundle."""
    if dataset == "synth":
        ds = data_mod.synth_dataset(n_per_class=n_per_class, sample_rate=sample_rate,
                                     duration_s=duration_s, fft_size=fft_size, seed=seed)
    elif dataset == "dronerf":
        ds = data_mod.load_dronerf(data_root, sample_rate=sample_rate, fft_size=fft_size)
    elif dataset == "dronedetect":
        ds = data_mod.load_dronedetect(data_root, fft_size=fft_size)
    else:
        raise ValueError(f"unknown dataset {dataset!r} (synth|dronerf|dronedetect)")

    X = features_matrix(ds, feature_kind)
    y = data_mod.to_binary(ds.labels) if binary else ds.labels
    model, m = train_sklearn(X, y, algo=algo, seed=seed)
    bundle = build_bundle(model, kind="sklearn", feature_kind=feature_kind,
                          classes=m["classes"], sample_rate=ds.sample_rate,
                          fft_size=ds.fft_size)
    out = save_bundle(bundle, out_path)
    return TrainResult(accuracy=m["accuracy"], val_accuracy=m["val_accuracy"],
                       n_train=m["n_train"], n_val=m["n_val"],
                       classes=m["classes"], report=m["report"], out_path=str(out))


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train the AERIX stage-2 signature classifier")
    ap.add_argument("--dataset", default="synth", choices=["synth", "dronerf", "dronedetect"])
    ap.add_argument("--feature", default="psd", choices=list(feat.FEATURE_KINDS))
    ap.add_argument("--model", dest="algo", default="rf", choices=["rf", "svm"])
    ap.add_argument("--out", default=str(DEFAULT_MODEL_PATH))
    ap.add_argument("--sample-rate", type=float, default=20e6)
    ap.add_argument("--duration-s", type=float, default=0.12)
    ap.add_argument("--fft-size", type=int, default=1024)
    ap.add_argument("--n-per-class", type=int, default=60)
    ap.add_argument("--binary", action="store_true", help="drone-vs-noise instead of 4-class")
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    res = train_and_save(dataset=args.dataset, feature_kind=args.feature, algo=args.algo,
                         out_path=args.out, sample_rate=args.sample_rate,
                         duration_s=args.duration_s, fft_size=args.fft_size,
                         n_per_class=args.n_per_class, binary=args.binary,
                         seed=args.seed, data_root=args.data_root)
    print(f"classes      : {res.classes}")
    print(f"train acc    : {res.accuracy:.3f}")
    print(f"val   acc    : {res.val_accuracy:.3f}  (n_train={res.n_train}, n_val={res.n_val})")
    print(f"saved bundle : {res.out_path}")
    print(res.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
