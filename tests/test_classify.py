"""Stage-2 classifier: the trained model separates drone from noise, and the
rule-based ``classify(det)`` keeps working with or without a saved model.

Run (private env + ephemeral train deps, no shared uv sync):

    UV_PROJECT_ENVIRONMENT=.venv-train \
      uv run --with scikit-learn,joblib pytest tests/test_classify.py -q
"""

from pathlib import Path

import numpy as np
import pytest

from aerix_rf.dsp import spectrogram
from aerix_rf.detect import energy
from aerix_rf.sdr.sim import synth_iq
from aerix_rf.classify import model as clsmodel

# Real DroneRF subset, prepared by data/dronerf/fetch_dronerf.py (gitignored).
# The real-data test below is skipped unless it is present, so CI stays green
# and light; the synthetic tests always run.
_DRONERF_DIR = Path(__file__).resolve().parents[1] / "data" / "dronerf"
_HAVE_DRONERF = bool(list(_DRONERF_DIR.glob("**/*.csv")))

# Small, fast, internally consistent: train and infer at the SAME sample rate so
# the fractional-band PSD feature is comparable (a model is only valid at its
# training rate). 10 MS/s over short windows keeps the suite quick.
SAMPLE_RATE = 10e6
DURATION_S = 0.12
FFT = 512


def _spec(iq):
    return spectrogram.compute(iq, SAMPLE_RATE, fft_size=FFT)


def _drone_iq(seed):
    return synth_iq(SAMPLE_RATE, DURATION_S, drone=True, snr_db=16.0,
                    burst_bw_hz=8e6, cadence_s=0.06, seed=seed)


def _noise_iq(seed):
    return synth_iq(SAMPLE_RATE, DURATION_S, drone=False, seed=seed)


# --- training on the synthetic dataset -----------------------------------------

def test_binary_model_separates_drone_from_noise(tmp_path):
    from aerix_rf.classify.train import train as trainer

    out = tmp_path / "signature.joblib"
    res = trainer.train_and_save(dataset="synth", feature_kind="psd", algo="rf",
                                 out_path=out, sample_rate=SAMPLE_RATE,
                                 duration_s=DURATION_S, fft_size=FFT,
                                 n_per_class=40, binary=True, seed=1)
    assert out.exists()
    assert set(res.classes) == {"drone", "noise"}
    # PSD features make drone-vs-noise near-trivial; demand high val accuracy.
    assert res.val_accuracy >= 0.90, res.report


def test_multiclass_model_trains_and_predicts(tmp_path):
    from aerix_rf.classify.train import train as trainer

    out = tmp_path / "signature.joblib"
    res = trainer.train_and_save(dataset="synth", feature_kind="psd", algo="rf",
                                 out_path=out, sample_rate=SAMPLE_RATE,
                                 duration_s=DURATION_S, fft_size=FFT,
                                 n_per_class=40, binary=False, seed=2)
    assert set(res.classes) == {"dji_ocusync", "wifi_drone", "fpv_analog", "noise"}
    # 4-class is harder than binary but the classes are well separated by design.
    assert res.val_accuracy >= 0.75, res.report


# --- real DroneRF data path (opt-in: skipped unless the subset is present) ------

@pytest.mark.skipif(not _HAVE_DRONERF,
                    reason="DroneRF subset absent; run data/dronerf/fetch_dronerf.py")
def test_dronerf_real_path_separates_drone_from_background(tmp_path):
    """The real-data loader parses DroneRF CSVs and a model trained on them
    separates a real drone from real background RF (which includes ambient
    Wi-Fi/Bluetooth) -- the domain gap the synthetic-only model had.

    Uses a leak-free split: whole recordings are held out for validation
    (frames from one CSV are near-duplicates), so the accuracy is honest.
    """
    from aerix_rf.classify.train import data as d
    from aerix_rf.classify.train import train as trainer

    # Cap frames per class to keep the test bounded; still >=2 recordings/class
    # so the recording-grouped validation split is meaningful.
    ds = d.load_dronerf(fft_size=512, max_per_class=30)
    assert ds.sample_rate == 40e6, "DroneRF is a 40 MS/s capture; bundle must record it"
    assert "groups" in ds.meta and len(ds.meta["groups"]) == len(ds)
    assert "noise" in set(ds.labels)
    assert set(ds.labels) & set(d.DRONE_CLASSES), "expected at least one drone class"

    # Binary drone-vs-background, grouped (leak-free) split.
    X = trainer.features_matrix(ds, "psd")
    y = d.to_binary(ds.labels)
    model, m = trainer.train_sklearn(X, y, algo="rf", seed=0,
                                     groups=ds.meta["groups"])
    assert m["grouped"] is True, "validation must hold out whole recordings"
    assert m["confusion"] is not None
    assert m["val_accuracy"] >= 0.7, m["report"]

    # End-to-end: a saved real-data bundle drives classify_spectrogram, and its
    # recorded sample_rate is the true capture rate (not the box's 20 MS/s).
    res = trainer.train_and_save(dataset="dronerf", feature_kind="psd", algo="rf",
                                 out_path=tmp_path / "dronerf.joblib",
                                 fft_size=512, max_per_class=30, binary=True)
    assert res.grouped is True
    import joblib
    bundle = joblib.load(tmp_path / "dronerf.joblib")
    assert bundle["sample_rate"] == 40e6


# --- inference wiring: classify_spectrogram uses the model when present ---------

def test_classify_spectrogram_uses_model(tmp_path, monkeypatch):
    from aerix_rf.classify.train import train as trainer

    out = tmp_path / "signature.joblib"
    trainer.train_and_save(dataset="synth", feature_kind="psd", algo="rf",
                           out_path=out, sample_rate=SAMPLE_RATE,
                           duration_s=DURATION_S, fft_size=FFT,
                           n_per_class=40, binary=True, seed=3)

    monkeypatch.setenv("AERIX_RF_MODEL", str(out))
    clsmodel._reset_model_cache()
    assert clsmodel.model_available()

    drone = clsmodel.classify_spectrogram(_spec(_drone_iq(101)))
    noise = clsmodel.classify_spectrogram(_spec(_noise_iq(202)))
    assert drone.signature_class == "drone"
    assert noise.signature_class == "noise"
    assert drone.source.startswith("sklearn:")
    assert 0.0 <= drone.confidence <= 1.0


def test_classify_spectrogram_falls_back_without_model(monkeypatch, tmp_path):
    # Point at a non-existent path -> no model -> rule-based fallback, no crash.
    monkeypatch.setenv("AERIX_RF_MODEL", str(tmp_path / "does-not-exist.joblib"))
    clsmodel._reset_model_cache()
    assert not clsmodel.model_available()

    res = clsmodel.classify_spectrogram(_spec(_drone_iq(7)), center_freq_mhz=2431.5)
    assert res.source == "rule"
    assert res.signature_class in {"dji_ocusync", "wifi_drone", "fpv_analog", "noise"}


# --- classify(det) works both with and without a saved model present -----------

def _det(iq):
    return energy.detect(_spec(iq), 2431.5)


def test_classify_det_works_without_model(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIX_RF_MODEL", str(tmp_path / "absent.joblib"))
    clsmodel._reset_model_cache()
    c = clsmodel.classify(_det(_drone_iq(11)))
    assert c.source == "rule"
    assert c.signature_class != "noise"
    assert clsmodel.classify(_det(_noise_iq(12))).signature_class == "noise"


def test_classify_det_works_with_model_present(tmp_path, monkeypatch):
    from aerix_rf.classify.train import train as trainer

    out = tmp_path / "signature.joblib"
    trainer.train_and_save(dataset="synth", feature_kind="psd", algo="rf",
                           out_path=out, sample_rate=SAMPLE_RATE,
                           duration_s=DURATION_S, fft_size=FFT,
                           n_per_class=30, binary=True, seed=5)
    monkeypatch.setenv("AERIX_RF_MODEL", str(out))
    clsmodel._reset_model_cache()

    # classify(det) is the rule path regardless of a present model: still "rule".
    c = clsmodel.classify(_det(_drone_iq(21)))
    assert c.source == "rule"
    assert 0.0 <= c.confidence <= 1.0


# --- feature extractor is robust to fft_size (live 1024 vs trained 512) ---------

def test_feature_dim_independent_of_fft_size():
    from aerix_rf.classify.train import features as feat

    a = feat.extract(spectrogram.compute(_drone_iq(1), SAMPLE_RATE, fft_size=512))
    b = feat.extract(spectrogram.compute(_drone_iq(1), SAMPLE_RATE, fft_size=1024))
    assert a.shape == b.shape == (feat.PSD_BINS,)

    # The 'spec' (downsampled-spectrogram) feature is also exercised and
    # fft_size-independent, at its fixed flattened dimension.
    sa = feat.extract(spectrogram.compute(_drone_iq(1), SAMPLE_RATE, fft_size=512), "spec")
    sb = feat.extract(spectrogram.compute(_drone_iq(1), SAMPLE_RATE, fft_size=1024), "spec")
    assert sa.shape == sb.shape == (feat.SPEC_SHAPE[0] * feat.SPEC_SHAPE[1],)
