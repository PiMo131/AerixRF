"""Stage-2 classifier = probabilistic UAS identity.

Stage 1 (``detect.energy``) only describes RF *shape* (``Detection.morphology``).
This module turns that shape -- plus, when a trained bundle is available, the
spectrogram itself -- into an identity claim in the stage-2 vocabulary::

    dji_ocusync   wifi_uas   analog_fpv   other_uas   non_uas   unknown

Entry points (all return a ``Classification``):

  * ``classify(det)``                      rule-based stage 2 from a Detection.
                                           Never touches a model file.
  * ``classify_spectrogram(spec, f, det)`` ML when a bundle loads, else rules.
  * ``classify_window(spec, det, f)``      what the live loop calls: ML if
                                           available, else rules.

Live behaviour required by the plan (2.1 / milestone 1.2)::

    no model            -> rule fallback            source == "rule"
    valid model         -> ML classifier            source == "sklearn:<ver>"
    broken model        -> warn once, rule fallback, service continues
    low-confidence ML   -> "unknown", abstained=True
    sample-rate mismatch-> WARNING once per bundle; Classification flags it

The rules are deliberately conservative: at 2.4 GHz ambient Wi-Fi is a 20 MHz
wideband OFDM emitter, so "wideband" alone is never a drone. Only a *cadenced*
(300-1000 ms) ~10 MHz burst train earns ``dji_ocusync``, and even then with
confidence <= 0.6. Deterministic confirmation is stage 3 (protocol decode);
never gate the decoder on this output.

Model bundles are produced by ``aerix_rf.classify.train``. Their labels are
canonicalised here (``wifi_drone`` -> ``wifi_uas`` etc.), so the dataset
labels never need renaming. scikit-learn / joblib are imported lazily so the box
runtime never needs them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..detect.energy import Detection

log = logging.getLogger("aerix.rf.classify")

# Default bundle path, resolved relative to the package (aerix-rf/models/...),
# matching train.DEFAULT_MODEL_PATH -- not the cwd.
_PKG_ROOT = Path(__file__).resolve().parents[2]      # .../aerix-rf
DEFAULT_MODEL_PATH = _PKG_ROOT / "models" / "signature.joblib"

STAGE2_CLASSES = ("dji_ocusync", "wifi_uas", "analog_fpv", "other_uas", "non_uas", "unknown")

# features_v2 wiring (docs/design/features-and-benchmark.md S4 F4). The live
# pipeline's active feature extractor is selected by $AERIX_RF_FEATURES ("v1"
# | "v2"), read fresh (not cached) so tests can flip it per-case, mirroring
# ``_model_path``. Default is "v1": measured on this host, the v2 path (an
# extra canonical STFT/tensor + resample for non-canonical live rates) costs
# ~1.4-3.3 s on a 1 s window -- far past any 1 Hz-loop budget -- so v2 must
# stay opt-in until that cost is addressed (see the F4 result packet).
FEATURES_V1 = "features_v1"      # aerix_rf.classify.train.features (frozen)
FEATURES_V2 = "features_v2"      # aerix_rf.classify.features_v2


def active_features_version() -> str:
    """The live pipeline's active Stage-2 feature extractor, from $AERIX_RF_FEATURES."""
    return FEATURES_V2 if os.environ.get("AERIX_RF_FEATURES", "v1").strip().lower() == "v2" else FEATURES_V1

# Below this predicted-class probability the ML path abstains ("unknown").
ABSTAIN_THRESHOLD = 0.5

# Model / dataset labels -> stage-2 vocabulary. Anything not listed maps to
# "unknown" (the raw label is still carried in Classification.model_label).
LEGACY_LABELS = {
    "dji_ocusync": "dji_ocusync",
    "wifi_drone": "wifi_uas",       # train/data.py CLASSES
    "fpv_analog": "analog_fpv",
    "noise": "non_uas",
    "drone": "other_uas",           # binary models (to_binary)
    "unknown": "unknown",
    **{c: c for c in STAGE2_CLASSES},
}

# Rule thresholds (stage-2 identity; stage-1 shape thresholds live in energy.py).
DJI_CADENCE_MS = (300.0, 1000.0)    # DroneID / OcuSync beacon cadence window
DJI_BW_MHZ = (6.0, 16.0)            # ~10 MHz burst; 20 MHz is Wi-Fi territory
DJI_MAX_CONFIDENCE = 0.6
# A DroneID-style beacon is SPARSE: a few sub-ms bursts per second. Ambient
# Wi-Fi with 150+ packets/s can still produce a "cadence" estimate in the
# 300-1000 ms window (seen live, 2 of 504 ambient windows), so the rule also
# requires few bursts and a low duty cycle.
DJI_MAX_BURSTS_PER_S = 8
DJI_MAX_DUTY = 0.2
ANALOG_CONFIDENCE = 0.3


@dataclass
class Classification:
    signature_class: str                 # stage-2 vocabulary (STAGE2_CLASSES)
    confidence: float                    # P(label); 0.0 for a rule "unknown"
    source: str                          # "rule" | "sklearn:<version>" | "cnn:<version>"
    model_version: str | None = None     # bundle version when source is a model
    model_label: str | None = None       # raw model label before canonicalisation
    abstained: bool = False              # ML confidence < ABSTAIN_THRESHOLD -> "unknown"
    sample_rate_mismatch: bool = False   # model trained at another rate: advisory only
    features_version: str | None = None       # active live extractor ("features_v1"/"features_v2")
    model_features_mismatch: bool = False     # bundle's features_version != active: rule fallback used
    features_valid_fraction: float | None = None  # share of unmasked features_v2 dims (v2 path only)


def canonical_label(label: str) -> str:
    """Map a model/dataset label to the stage-2 vocabulary."""
    return LEGACY_LABELS.get(str(label), "unknown")


# --- rule-based stage 2 --------------------------------------------------------

def classify(det: Detection) -> Classification:
    """Conservative rules from stage-1 morphology. Never depends on a model.

    Rule table (first match wins):

      noise                                              -> non_uas
      ofdm/burst_wideband, cadence 300-1000 ms,
          6 <= bw < 16 MHz, 2..8 bursts, duty < 0.2     -> dji_ocusync (<= 0.6)
      analog_candidate (>= 18 MHz continuous)            -> analog_fpv (0.3)
      anything else (narrowband, wideband w/o cadence,
          continuous wideband, fhss, unknown)            -> unknown (0.0)
    """
    morph = getattr(det, "morphology", None) or "unknown"
    if morph == "noise" or det.signature_class == "noise":
        conf = float(min(0.95, max(0.5, 1.0 - det.score)))
        return Classification("non_uas", conf, "rule")

    cad = det.cadence_ms
    cadenced = cad is not None and DJI_CADENCE_MS[0] <= cad <= DJI_CADENCE_MS[1]
    bw_ok = DJI_BW_MHZ[0] <= det.occupied_bw_mhz < DJI_BW_MHZ[1]
    sparse = (2 <= det.burst_count <= DJI_MAX_BURSTS_PER_S
              and float(getattr(det, "duty_cycle", 0.0)) < DJI_MAX_DUTY)
    if (morph in ("ofdm_candidate", "burst_wideband_candidate")
            and cadenced and bw_ok and sparse):
        conf = float(min(DJI_MAX_CONFIDENCE, 0.35 + 0.25 * det.score))
        return Classification("dji_ocusync", conf, "rule")

    if morph == "analog_candidate":
        return Classification("analog_fpv", ANALOG_CONFIDENCE, "rule")

    # Wideband without cadence is exactly what ambient Wi-Fi looks like; a
    # hopper could be Bluetooth or an RC link; narrowband is anything. No claim.
    return Classification("unknown", 0.0, "rule")


# --- model loading (lazy, cached by path+mtime, never fatal) --------------------

_model_cache: dict = {"key": None, "bundle": None}
_warned: set[tuple] = set()      # (kind, bundle key, ...) already logged at WARNING


def _model_path() -> Path:
    env = os.environ.get("AERIX_RF_MODEL")
    return Path(env) if env else DEFAULT_MODEL_PATH


def _reset_model_cache() -> None:
    """Drop the cached bundle and warn-once state. For tests that swap ``$AERIX_RF_MODEL``."""
    _model_cache["key"] = None
    _model_cache["bundle"] = None
    _warned.clear()


def _load_bundle():
    """Return the trained bundle dict, or None. Cached on (path, mtime).

    Any failure (missing file, no joblib/sklearn, unpicklable/version-skewed
    bundle) logs once per (path, mtime) and returns None so the caller falls
    back to rules -- the 1 Hz loop must never die on a bad model file.
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

    # A failed load is cached too (bundle=None) so the warning fires once per
    # file version, not every window.
    _model_cache["key"], _model_cache["bundle"] = key, bundle
    return bundle


def model_available() -> bool:
    return _load_bundle() is not None


def _warn_once(tag: tuple, msg: str, *args) -> None:
    if tag in _warned:
        log.debug(msg, *args)
        return
    _warned.add(tag)
    log.warning(msg, *args)


# --- ML stage 2 with rule fallback ---------------------------------------------

def classify_spectrogram(spec, center_freq_mhz: float = 0.0,
                         det: Detection | None = None) -> Classification:
    """ML classification from a spectrogram, with a rule-based fallback.

    Uses the trained bundle when present; otherwise (or on any model failure)
    runs the rules on ``det`` -- computed from ``spec`` if not given -- so this
    entry point is always safe to call.
    """
    bundle = _load_bundle()
    if bundle is None:
        return _rule_fallback(spec, center_freq_mhz, det)

    key = _model_cache["key"]
    version = str(bundle.get("version", "?"))
    src = f"{bundle.get('kind', 'sklearn')}:{version}"
    try:
        from .train import features as feat

        model_sr = bundle.get("sample_rate")
        mismatch = model_sr is not None and float(model_sr) != float(spec.sample_rate)
        if mismatch:
            _warn_once(("sr", key, float(spec.sample_rate)),
                       "aerix model %s was trained at %.3g S/s but live frames are %.3g S/s: "
                       "PSD features are a fraction of the captured band, so this model is "
                       "UNCALIBRATED at this rate -- treat its labels as advisory only "
                       "(train a native model at %.3g S/s to clear this)",
                       key[0], float(model_sr), float(spec.sample_rate), float(spec.sample_rate))

        x = feat.extract(spec, bundle.get("feature_kind", "psd"),
                         psd_bins=bundle.get("psd_bins", feat.PSD_BINS),
                         spec_shape=tuple(bundle.get("spec_shape", feat.SPEC_SHAPE)))
        x = x.reshape(1, -1)
        model = bundle["model"]
        raw = str(model.predict(x)[0])
        conf = _confidence(model, x, raw)
        label = canonical_label(raw)
        abstained = conf < ABSTAIN_THRESHOLD
        if abstained:
            label = "unknown"
        return Classification(signature_class=label, confidence=conf, source=src,
                              model_version=version, model_label=raw,
                              abstained=abstained, sample_rate_mismatch=mismatch)
    except Exception as exc:  # noqa: BLE001
        _warn_once(("infer", key), "aerix model inference failed (%s): %s; using rules",
                   key[0], exc)
        return _rule_fallback(spec, center_freq_mhz, det)


def _extract_features_v2_live(iq: np.ndarray, sample_rate: float) -> tuple[np.ndarray, np.ndarray, float]:
    """Raw live IQ at the capture rate -> ``features_v2`` vector.

    Resamples to the canonical 15.36 MS/s grid first (ANTSDR 12.288 MS/s,
    HackRF 20 MS/s are both non-canonical) via ``datasets.resample`` --
    ``features_v2`` is only defined on the canonical tensor and must never
    silently score a non-canonical spectrogram (design doc S4 F4). Imports
    are lazy so the default (v1) live path never pays for this module.
    """
    from ..datasets import resample as _resample
    from . import features_v2 as _fv2

    fs = float(sample_rate)
    if abs(fs - _fv2.CANONICAL_FS) > 1.0:
        # F6 perf task (2026-09-18): this was silently planning the
        # dataset-grade (60 dB stopband / ~1.68 MHz transition) chain --
        # the live-grade design (`grade="live"`, resample.py) existed but
        # was never requested here, so the live path always paid the
        # slower, offline-quality filter cost. Measured ~1.0 s at 12.288
        # MS/s before this fix; resample dominates the live path's latency
        # (see F6 result packet).
        chain = _resample.plan_chain(fs, _fv2.CANONICAL_FS, grade="live")
        iq = _resample.apply_chain(iq, chain, fs)
        fs = _fv2.CANONICAL_FS
    feats = _fv2.features_v2_from_iq(iq, fs=fs)
    frac = float(np.mean(feats.valid_mask)) if feats.valid_mask is not None else 1.0
    return feats.vector, feats.valid_mask, frac


def classify_window(spec, det: Detection, center_freq_mhz: float, *,
                    iq: np.ndarray | None = None,
                    sample_rate: float | None = None) -> Classification:
    """Live-loop entry: ML if a bundle is available, else the rules on ``det``.

    ``iq``/``sample_rate`` (the raw window, as held by the pipeline) are
    optional and only consulted when the active extractor is
    ``features_v2`` (S4 F4): the v1 path never needs them. A bundle whose
    declared ``features_version`` does not match the pipeline's active
    extractor is never scored -- ``Classification.model_features_mismatch``
    is set and the rule-based classifier is used instead, exactly like an
    unavailable/broken model.
    """
    active = active_features_version()
    bundle = _load_bundle()

    if bundle is not None:
        key = _model_cache["key"]
        bundle_features_version = str(bundle.get("features_version") or FEATURES_V1)
        if bundle_features_version != active:
            _warn_once(("features_mismatch", key, active),
                       "aerix model %s declares features_version=%s but the live pipeline's "
                       "active extractor is %s; refusing to score with mismatched features -- "
                       "using rules", key[0], bundle_features_version, active)
            cls = _rule_fallback(spec, center_freq_mhz, det)
            cls.features_version = active
            cls.model_features_mismatch = True
            return cls
    else:
        bundle_features_version = None

    if active != FEATURES_V2:
        cls = classify_spectrogram(spec, center_freq_mhz, det=det)
        cls.features_version = active
        return cls

    # active == FEATURES_V2 from here.
    if bundle is None or iq is None or sample_rate is None:
        cls = _rule_fallback(spec, center_freq_mhz, det)
        cls.features_version = active
        return cls

    key = _model_cache["key"]
    version = str(bundle.get("version", "?"))
    src = f"{bundle.get('kind', 'sklearn')}:{version}"
    try:
        vec, _valid_mask, frac = _extract_features_v2_live(iq, sample_rate)
        x = vec.reshape(1, -1)
        model = bundle["model"]
        raw = str(model.predict(x)[0])
        conf = _confidence(model, x, raw)
        label = canonical_label(raw)
        abstained = conf < ABSTAIN_THRESHOLD
        if abstained:
            label = "unknown"
        return Classification(signature_class=label, confidence=conf, source=src,
                              model_version=version, model_label=raw, abstained=abstained,
                              features_version=active, features_valid_fraction=frac)
    except Exception as exc:  # noqa: BLE001 -- never let a bad window kill the loop
        _warn_once(("infer_v2", key), "aerix features_v2 live inference failed (%s): %s; using rules",
                   key[0], exc)
        cls = _rule_fallback(spec, center_freq_mhz, det)
        cls.features_version = active
        return cls


def _confidence(model, x, label: str) -> float:
    """Predicted-class probability if the estimator exposes one, else 1.0."""
    try:
        proba = model.predict_proba(x)[0]
        classes = [str(c) for c in model.classes_]
        return float(proba[classes.index(label)])
    except Exception:  # noqa: BLE001 -- e.g. an estimator without predict_proba
        return 1.0


def _rule_fallback(spec, center_freq_mhz: float, det: Detection | None = None) -> Classification:
    if det is None:
        from ..detect.energy import detect
        det = detect(spec, center_freq_mhz)
    return classify(det)
