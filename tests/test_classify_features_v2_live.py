"""Live-pipeline wiring for features_v2 (docs/design/features-and-benchmark.md
S4 F4): classify_window / model.py select the extractor from
$AERIX_RF_FEATURES, refuse to score a features-version mismatch, and the
pipeline's detections.jsonl record carries features_version /
model_features_mismatch / features_valid_fraction.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from aerix_rf.classify import model as clsmodel
from aerix_rf.config import Config
from aerix_rf.detect import energy
from aerix_rf.dsp import spectrogram
from aerix_rf import pipeline
from aerix_rf.sdr.capture import IQWindow

ANTSDR_FS = 12_288_000.0


def _noise_iq(fs: float, duration_s: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(fs * duration_s)
    return ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 0.05).astype(np.complex64)


def _window(fs: float, duration_s: float, seed: int = 0) -> IQWindow:
    iq = _noise_iq(fs, duration_s, seed)
    return IQWindow(iq=iq, captured_at=time.time(), sample_rate=fs,
                    center_freq_hz=2437e6, receiver_type="sim")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("AERIX_RF_MODEL", raising=False)
    monkeypatch.delenv("AERIX_RF_FEATURES", raising=False)
    clsmodel._reset_model_cache()
    yield
    clsmodel._reset_model_cache()


def test_default_active_version_is_v1():
    assert clsmodel.active_features_version() == clsmodel.FEATURES_V1


def test_pipeline_records_features_version_with_no_model():
    win = _window(ANTSDR_FS, 0.25)
    cfg = Config()
    res = pipeline.process_window(win, cfg, decode=False)
    rec = res.record()
    assert rec["features_version"] == clsmodel.FEATURES_V1
    assert rec["model_features_mismatch"] is False
    assert rec["class_source"] == "rule"


def test_pipeline_v2_env_produces_finite_features_and_record(monkeypatch):
    monkeypatch.setenv("AERIX_RF_FEATURES", "v2")
    win = _window(ANTSDR_FS, 1.0)
    cfg = Config()
    res = pipeline.process_window(win, cfg, decode=False)
    rec = res.record()
    assert rec["features_version"] == "features_v2"
    # No bundle loaded -> rule fallback, never a silent mis-scored ML call.
    assert rec["class_source"] == "rule"
    assert rec["model_features_mismatch"] is False


def test_v1_bundle_under_v2_active_sets_mismatch_and_falls_back(monkeypatch):
    """A bundle declaring features_v1 must never be scored while the live
    pipeline's active extractor is features_v2 -- model_features_mismatch is
    set and the rule-based classifier answers instead."""
    bundle = {
        "model": object(),          # never touched: mismatch short-circuits before use
        "kind": "sklearn",
        "version": "test",
        "feature_kind": "psd",
        "sample_rate": ANTSDR_FS,
        "features_version": "features_v1",
    }
    clsmodel._model_cache["key"] = ("fake", 0.0)
    clsmodel._model_cache["bundle"] = bundle
    monkeypatch.setattr(clsmodel, "_load_bundle", lambda: bundle)
    monkeypatch.setenv("AERIX_RF_FEATURES", "v2")

    iq = _noise_iq(ANTSDR_FS, 0.25)
    spec = spectrogram.compute(iq, ANTSDR_FS, fft_size=1024)
    det = energy.detect(spec, 2437.0)
    cls = clsmodel.classify_window(spec, det, 2437.0, iq=iq, sample_rate=ANTSDR_FS)

    assert cls.model_features_mismatch is True
    assert cls.source == "rule"
    assert cls.features_version == "features_v2"


def test_v2_active_without_iq_falls_back_to_rules_no_crash(monkeypatch):
    monkeypatch.setenv("AERIX_RF_FEATURES", "v2")
    iq = _noise_iq(ANTSDR_FS, 0.25)
    spec = spectrogram.compute(iq, ANTSDR_FS, fft_size=1024)
    det = energy.detect(spec, 2437.0)
    # No iq/sample_rate passed -> classify_window must not crash.
    cls = clsmodel.classify_window(spec, det, 2437.0)
    assert cls.source == "rule"
    assert cls.features_version == "features_v2"


def test_live_v2_extraction_matches_training_path_byte_identical(monkeypatch):
    """Live features_v2 extraction (resample + canonical tensor) must equal
    the offline features_v2_from_iq path bit-for-bit at the canonical rate
    (design doc F4 accept criterion)."""
    from aerix_rf.classify import features_v2 as fv2

    iq = _noise_iq(fv2.CANONICAL_FS, 0.3, seed=3)
    vec_live, mask_live, frac = clsmodel._extract_features_v2_live(iq, fv2.CANONICAL_FS)
    feats_offline = fv2.features_v2_from_iq(iq, fs=fv2.CANONICAL_FS)
    assert np.array_equal(vec_live, feats_offline.vector)
    assert np.array_equal(mask_live, feats_offline.valid_mask)
    assert 0.0 <= frac <= 1.0
    assert np.all(np.isfinite(vec_live))


def test_v2_live_timing_1s_window_generous_bound():
    """Measures the full live v2 path (resample 12.288->15.36 MS/s + canonical
    tensor + features) on a 1 s ANTSDR-rate window. Bound is deliberately
    generous (this path is expensive -- see the F4 result packet); the
    number asserted here is not a real-time budget claim."""
    iq = _noise_iq(ANTSDR_FS, 1.0, seed=9)
    t0 = time.perf_counter()
    vec, mask, frac = clsmodel._extract_features_v2_live(iq, ANTSDR_FS)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert np.all(np.isfinite(vec))
    assert elapsed_ms < 10_000.0, f"features_v2 live path took {elapsed_ms:.0f} ms"
