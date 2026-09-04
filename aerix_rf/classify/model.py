"""Stage-2 classifier interface.

Two entry points, one contract -- both return a ``Classification(label,
confidence, source)`` so nothing downstream changes:

  * ``classify(det)``             -- the original, rule-based path driven by the
                                     energy detector's shape heuristics. Kept
                                     exactly as-is for existing callers
                                     (``main.py``). Never depends on a model file.
  * ``classify_spectrogram(spec)`` -- the ML path. Loads a trained model bundle
                                     (from ``$AERIX_RF_MODEL`` or the default
                                     ``models/signature.joblib``) and predicts
                                     from spectrogram features produced by the
                                     *same* extractor used in training. Falls
                                     back to the rule-based logic when no model
                                     is present, or if the model fails to load.

The model is trained by ``aerix_rf.classify.train`` on the public RF drone
datasets (DroneRF / DroneDetect / DroneRFb-Spectra) or the synthetic fallback.
scikit-learn / joblib are imported lazily so the box runtime never needs them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from ..detect.energy import Detection

log = logging.getLogger("aerix.rf.classify")

# Default bundle path, resolved relative to the package (aerix-rf/models/...),
# matching train.DEFAULT_MODEL_PATH -- not the cwd.
_PKG_ROOT = Path(__file__).resolve().parents[2]      # .../aerix-rf
DEFAULT_MODEL_PATH = _PKG_ROOT / "models" / "signature.joblib"


@dataclass
class Classification:
    signature_class: str
    confidence: float
    source: str          # "rule" | "sklearn:<version>" | "cnn:<version>"


def classify(det: Detection) -> Classification:
    # Rule-based path (unchanged): reuse the detector's shape heuristics;
    # confidence tracks the detection score so the field is populated
    # end-to-end. Independent of any trained model -- works with or without one.
    return Classification(signature_class=det.signature_class,
                          confidence=det.score, source="rule")


# --- model loading (lazy, cached by path+mtime, never fatal) --------------------

_model_cache: dict = {"key": None, "bundle": None}


def _model_path() -> Path:
    env = os.environ.get("AERIX_RF_MODEL")
    return Path(env) if env else DEFAULT_MODEL_PATH


def _reset_model_cache() -> None:
    """Drop the cached bundle. For tests that swap ``$AERIX_RF_MODEL``."""
    _model_cache["key"] = None
    _model_cache["bundle"] = None


def _load_bundle():
    """Return the trained bundle dict, or None. Cached on (path, mtime).

    Any failure (missing file, no joblib/sklearn, unpicklable/version-skewed
    bundle) logs once and returns None so the caller falls back to rules -- the
    1 Hz loop must never die on a bad model file.
    """
    path = _model_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _model_cache["key"], _model_cache["bundle"] = None, None
        return None

    key = (str(path), mtime)
    if _model_cache["key"] == key:
        return _model_cache["bundle"]

    bundle = None
    try:
        import joblib
        bundle = joblib.load(path)
        if not isinstance(bundle, dict) or "model" not in bundle:
            log.warning("aerix model at %s is not a valid bundle; using rules", path)
            bundle = None
    except Exception as exc:  # noqa: BLE001 -- never let a bad model kill the loop
        log.warning("aerix model load failed (%s): %s; using rules", path, exc)
        bundle = None

    _model_cache["key"], _model_cache["bundle"] = key, bundle
    return bundle


def model_available() -> bool:
    return _load_bundle() is not None


def classify_spectrogram(spec, center_freq_mhz: float = 0.0) -> Classification:
    """ML classification from a spectrogram, with a rule-based fallback.

    Uses the trained bundle when present; otherwise runs the energy detector on
    the spectrogram and returns its rule-based class, so this entry point is
    always safe to call.
    """
    bundle = _load_bundle()
    if bundle is None:
        return _rule_fallback(spec, center_freq_mhz)

    try:
        from .train import features as feat

        if spec.sample_rate != bundle.get("sample_rate"):
            log.debug("model trained at %.3g S/s but frame is %.3g S/s; PSD is "
                      "fractional-band so results may drift",
                      bundle.get("sample_rate", float("nan")), spec.sample_rate)

        x = feat.extract(spec, bundle.get("feature_kind", "psd"),
                         psd_bins=bundle.get("psd_bins", feat.PSD_BINS),
                         spec_shape=tuple(bundle.get("spec_shape", feat.SPEC_SHAPE)))
        x = x.reshape(1, -1)
        model = bundle["model"]
        label = str(model.predict(x)[0])
        conf = _confidence(model, x, label)
        src = f"{bundle.get('kind', 'sklearn')}:{bundle.get('version', '?')}"
        return Classification(signature_class=label, confidence=conf, source=src)
    except Exception as exc:  # noqa: BLE001
        log.warning("aerix model inference failed: %s; using rules", exc)
        return _rule_fallback(spec, center_freq_mhz)


def _confidence(model, x, label: str) -> float:
    """Predicted-class probability if the estimator exposes one, else 1.0."""
    try:
        proba = model.predict_proba(x)[0]
        classes = list(model.classes_)
        return float(proba[classes.index(label)])
    except Exception:  # noqa: BLE001 -- e.g. an estimator without predict_proba
        return 1.0


def _rule_fallback(spec, center_freq_mhz: float) -> Classification:
    from ..detect.energy import detect
    det = detect(spec, center_freq_mhz)
    return Classification(signature_class=det.signature_class,
                          confidence=det.score, source="rule")
