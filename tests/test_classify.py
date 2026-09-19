"""Stage-2 classifier: the trained model separates drone from noise, the
rule-based ``classify(det)`` keeps working with or without a saved model, and
the rules never call ambient Wi-Fi a drone.

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
    # Binary model labels ("drone"/"noise") are canonicalised to stage-2 names;
    # the raw model label is still exposed.
    assert drone.signature_class == "other_uas" and drone.model_label == "drone"
    assert noise.signature_class == "non_uas" and noise.model_label == "noise"
    assert drone.source.startswith("sklearn:")
    assert drone.model_version == drone.source.split(":", 1)[1]
    assert 0.0 <= drone.confidence <= 1.0
    assert drone.abstained is False
    assert drone.sample_rate_mismatch is False       # trained and run at SAMPLE_RATE

    # classify_window is the live entry point: same model path, det is optional context.
    det = energy.detect(_spec(_drone_iq(101)), 2431.5)
    live = clsmodel.classify_window(_spec(_drone_iq(101)), det, 2431.5)
    assert live.signature_class == "other_uas" and live.source == drone.source


def test_classify_spectrogram_falls_back_without_model(monkeypatch, tmp_path):
    # Point at a non-existent path -> no model -> rule-based fallback, no crash.
    monkeypatch.setenv("AERIX_RF_MODEL", str(tmp_path / "does-not-exist.joblib"))
    clsmodel._reset_model_cache()
    assert not clsmodel.model_available()

    res = clsmodel.classify_spectrogram(_spec(_drone_iq(7)), center_freq_mhz=2431.5)
    assert res.source == "rule"
    assert res.signature_class in clsmodel.STAGE2_CLASSES
    assert res.model_version is None

    det = energy.detect(_spec(_drone_iq(7)), 2431.5)
    live = clsmodel.classify_window(_spec(_drone_iq(7)), det, 2431.5)
    assert live.source == "rule" and live.signature_class == res.signature_class


# --- classify(det) works both with and without a saved model present -----------

def _det(iq):
    return energy.detect(_spec(iq), 2431.5)


def test_classify_det_works_without_model(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIX_RF_MODEL", str(tmp_path / "absent.joblib"))
    clsmodel._reset_model_cache()
    c = clsmodel.classify(_det(_drone_iq(11)))
    assert c.source == "rule"
    assert c.signature_class in clsmodel.STAGE2_CLASSES
    assert c.signature_class != "non_uas"
    assert clsmodel.classify(_det(_noise_iq(12))).signature_class == "non_uas"


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


# --- stage-2 rules: conservative identity from stage-1 morphology ---------------

def _rule(iq, sample_rate):
    det = energy.detect(spectrogram.compute(iq, sample_rate, fft_size=1024), 2431.5)
    return det, clsmodel.classify(det)


def test_rule_continuous_wideband_is_not_dji():
    """SAFETY INVARIANT: a ~16-20 MHz continuous wideband emitter with no cadence
    (what ambient 2.4 GHz Wi-Fi / any OFDM video link looks like) must never be
    labelled dji_ocusync by the rules -- 'wideband' alone is not a drone."""
    sr = 20e6
    for bw in (16e6, 18.5e6):
        iq = synth_iq(sr, 0.25, drone=True, snr_db=12.0, burst_bw_hz=bw,
                      burst_ms=1000.0, cadence_s=10.0, seed=4)
        det, c = _rule(iq, sr)
        assert det.snr_db > 8.0 and det.occupied_bw_mhz > 12.0, det   # it IS seen ...
        assert c.signature_class != "dji_ocusync", (det, c)           # ... but not claimed
        assert c.source == "rule"
    # 16 MHz continuous -> no identity at all.
    det, c = _rule(synth_iq(sr, 0.25, drone=True, snr_db=12.0, burst_bw_hz=16e6,
                            burst_ms=1000.0, cadence_s=10.0, seed=4), sr)
    assert c.signature_class == "unknown" and c.confidence == 0.0


def test_rule_wifi_like_packets_are_unknown():
    """Random wideband packets (bursty OFDM, no periodic cadence) -> unknown."""
    rng = np.random.default_rng(7)
    sr, n = 20e6, int(20e6 * 0.5)
    iq = ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)).astype(np.complex64)
    t0 = 0
    while t0 < n:
        seg = min(int(rng.uniform(0.2e-3, 2e-3) * sr), n - t0)
        s = rng.standard_normal(seg) + 1j * rng.standard_normal(seg)
        f = np.fft.fftshift(np.fft.fftfreq(seg, 1 / sr))
        S = np.fft.fftshift(np.fft.fft(s)); S[np.abs(f) > 8e6] = 0
        iq[t0:t0 + seg] += (4.0 * np.fft.ifft(np.fft.ifftshift(S))).astype(np.complex64)
        t0 += seg + int(rng.uniform(0.1e-3, 3e-3) * sr)
    det, c = _rule(iq, sr)
    assert det.occupied_bw_mhz > 12.0 and det.burst_count > 10, det
    assert c.signature_class == "unknown", (det, c)


def test_rule_cadenced_10mhz_bursts_may_be_dji_with_bounded_confidence():
    """10 MHz bursts every 600 ms over >= 1.5 s (the DroneID-like shape) may be
    called dji_ocusync, but never with more than moderate confidence."""
    sr = 20e6
    det, c = _rule(synth_iq(sr, 1.6, drone=True, snr_db=15.0, burst_bw_hz=10e6,
                            cadence_s=0.6, seed=3), sr)
    assert det.cadence_ms is not None and 300 <= det.cadence_ms <= 1000, det
    assert c.signature_class == "dji_ocusync", (det, c)
    assert 0.0 < c.confidence <= 0.6
    assert c.source == "rule" and c.abstained is False


def test_rule_fast_burst_train_without_droneid_cadence_is_unknown():
    """Same 8 MHz bursts but at a 60 ms cadence: wideband OFDM-ish, not DroneID."""
    det, c = _rule(synth_iq(SAMPLE_RATE, 0.3, drone=True, snr_db=15.0,
                            burst_bw_hz=8e6, cadence_s=0.06, seed=1), SAMPLE_RATE)
    assert det.morphology in ("ofdm_candidate", "burst_wideband_candidate")
    assert c.signature_class == "unknown"


def test_rule_noise_is_non_uas_and_narrowband_is_unknown():
    _, c = _rule(synth_iq(SAMPLE_RATE, 0.3, drone=False, seed=2), SAMPLE_RATE)
    assert c.signature_class == "non_uas" and c.confidence >= 0.5

    det, c = _rule(synth_iq(SAMPLE_RATE, 0.3, drone=True, snr_db=20.0, burst_bw_hz=0.5e6,
                            burst_ms=5.0, cadence_s=0.1, seed=5), SAMPLE_RATE)
    assert det.morphology == "narrowband_candidate"
    assert c.signature_class == "unknown"


def test_rule_analog_candidate_is_low_confidence_analog_fpv():
    sr = 20e6
    det, c = _rule(synth_iq(sr, 0.25, drone=True, snr_db=12.0, burst_bw_hz=18.5e6,
                            burst_ms=1000.0, cadence_s=10.0, seed=4), sr)
    assert det.morphology == "analog_candidate"
    assert c.signature_class == "analog_fpv" and c.confidence <= 0.3


def test_rule_handles_legacy_detection_without_morphology():
    # A hand-built Detection (older callers / tests) still classifies.
    det = energy.Detection(score=0.1, snr_db=2.0, rssi_dbm=-60, peak_freq_mhz=2431.5,
                           occupied_bw_mhz=0.0, burst_count=0, cadence_ms=None,
                           signature_class="noise")
    assert clsmodel.classify(det).signature_class == "non_uas"


def test_canonical_label_covers_dataset_and_stage2_labels():
    for raw, want in (("wifi_drone", "wifi_uas"), ("fpv_analog", "analog_fpv"),
                      ("noise", "non_uas"), ("drone", "other_uas"),
                      ("dji_ocusync", "dji_ocusync"), ("unknown", "unknown"),
                      ("something_else", "unknown"),
                      ("drone_link", "uas_link"), ("background", "background")):
        assert clsmodel.canonical_label(raw) == want
    for c in clsmodel.STAGE2_CLASSES:
        assert clsmodel.canonical_label(c) == c


@pytest.mark.parametrize("raw,want", [
    ("dji_ocusync", "dji_ocusync"),
    ("wifi_drone", "wifi_uas"),
    ("fpv_analog", "analog_fpv"),
    ("noise", "non_uas"),
    ("drone", "other_uas"),
    ("unknown", "unknown"),
    ("something_else", "unknown"),
])
def test_canonical_label_v1_mappings_are_byte_identical(raw, want):
    """features_v2's drone_link/background addition must not disturb any
    pre-existing (v1 dataset / rule-vocabulary) mapping."""
    assert clsmodel.canonical_label(raw) == want


def test_canonical_label_v2_bundle_labels_are_generic_uas_link_not_identity():
    # "drone_link" (features_v2 positive class) -> the generic, family-agnostic
    # stage-2 label, never one of the identity buckets (dji_ocusync etc.).
    assert clsmodel.canonical_label("drone_link") == "uas_link"
    assert clsmodel.canonical_label("background") == "background"
    assert "uas_link" in clsmodel.STAGE2_CLASSES and "background" in clsmodel.STAGE2_CLASSES


# --- ML path: abstain, sample-rate mismatch, corrupt model ---------------------

def _tiny_bundle(path, *, sample_rate, priors, version="tiny-test"):
    """A genuine (pickle-safe) sklearn estimator whose predict_proba is a fixed
    prior over three model labels -- lets us dial the confidence precisely."""
    import joblib
    from sklearn.dummy import DummyClassifier
    from aerix_rf.classify.train import features as feat

    labels = []
    for lab, k in priors.items():
        labels += [lab] * k
    X = np.zeros((len(labels), feat.PSD_BINS), dtype=np.float32)
    est = DummyClassifier(strategy="prior").fit(X, labels)
    joblib.dump({"model": est, "kind": "sklearn", "feature_kind": "psd",
                 "psd_bins": feat.PSD_BINS, "spec_shape": feat.SPEC_SHAPE,
                 "classes": sorted(priors), "sample_rate": sample_rate,
                 "fft_size": FFT, "version": version}, path)
    return path


def test_ml_abstains_below_threshold(tmp_path, monkeypatch):
    # Top class "dji_ocusync" has P = 0.4 < ABSTAIN_THRESHOLD -> unknown, abstained.
    p = _tiny_bundle(tmp_path / "m.joblib", sample_rate=SAMPLE_RATE,
                     priors={"dji_ocusync": 4, "wifi_drone": 3, "noise": 3})
    monkeypatch.setenv("AERIX_RF_MODEL", str(p))
    clsmodel._reset_model_cache()
    c = clsmodel.classify_spectrogram(_spec(_drone_iq(31)), 2431.5)
    assert c.source == "sklearn:tiny-test" and c.model_version == "tiny-test"
    assert c.abstained is True
    assert c.signature_class == "unknown"
    assert c.model_label == "dji_ocusync"
    assert abs(c.confidence - 0.4) < 1e-6              # kept, so callers can see why
    assert c.sample_rate_mismatch is False


def test_ml_confident_prediction_is_canonicalised(tmp_path, monkeypatch):
    p = _tiny_bundle(tmp_path / "m.joblib", sample_rate=SAMPLE_RATE,
                     priors={"wifi_drone": 7, "noise": 3})
    monkeypatch.setenv("AERIX_RF_MODEL", str(p))
    clsmodel._reset_model_cache()
    c = clsmodel.classify_spectrogram(_spec(_noise_iq(32)), 2431.5)
    assert c.abstained is False
    assert c.signature_class == "wifi_uas" and c.model_label == "wifi_drone"
    assert abs(c.confidence - 0.7) < 1e-6


def test_ml_sample_rate_mismatch_is_flagged_and_warned_once(tmp_path, monkeypatch, caplog):
    # Bundle says 40 MS/s (the DroneRF demo rate); frames are at SAMPLE_RATE.
    p = _tiny_bundle(tmp_path / "m40.joblib", sample_rate=40e6,
                     priors={"noise": 9, "dji_ocusync": 1})
    monkeypatch.setenv("AERIX_RF_MODEL", str(p))
    clsmodel._reset_model_cache()
    caplog.set_level("WARNING", logger="aerix.rf.classify")

    a = clsmodel.classify_spectrogram(_spec(_noise_iq(41)), 2431.5)
    b = clsmodel.classify_spectrogram(_spec(_noise_iq(42)), 2431.5)
    assert a.sample_rate_mismatch is True and b.sample_rate_mismatch is True
    assert a.signature_class == "non_uas" and a.source == "sklearn:tiny-test"

    warns = [r for r in caplog.records if r.levelname == "WARNING" and "UNCALIBRATED" in r.getMessage()]
    assert len(warns) == 1, [r.getMessage() for r in caplog.records]
    assert "4e+07" in warns[0].getMessage() and "1e+07" in warns[0].getMessage()


def test_corrupt_model_warns_once_and_falls_back(tmp_path, monkeypatch, caplog):
    p = tmp_path / "corrupt.joblib"
    p.write_bytes(b"this is not a joblib file")
    monkeypatch.setenv("AERIX_RF_MODEL", str(p))
    clsmodel._reset_model_cache()
    caplog.set_level("WARNING", logger="aerix.rf.classify")

    assert not clsmodel.model_available()
    for seed in (51, 52, 53):
        c = clsmodel.classify_spectrogram(_spec(_noise_iq(seed)), 2431.5)
        assert c.source == "rule" and c.signature_class == "non_uas"
    warns = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warns) == 1, [r.getMessage() for r in warns]   # once per (path, mtime)

    # A bundle without a "model" key is rejected the same way.
    import joblib
    q = tmp_path / "bad.joblib"
    joblib.dump({"not_a_model": 1}, q)
    monkeypatch.setenv("AERIX_RF_MODEL", str(q))
    clsmodel._reset_model_cache()
    caplog.clear()
    assert clsmodel.classify_spectrogram(_spec(_noise_iq(54)), 2431.5).source == "rule"
    assert clsmodel.classify_spectrogram(_spec(_noise_iq(55)), 2431.5).source == "rule"
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


def test_model_changes_live_classification(tmp_path, monkeypatch):
    """Acceptance 1.2: the same window classifies differently with a model
    present vs absent, and the source says which path produced the label."""
    spec = _spec(_noise_iq(61))
    det = energy.detect(spec, 2431.5)

    monkeypatch.setenv("AERIX_RF_MODEL", str(tmp_path / "absent.joblib"))
    clsmodel._reset_model_cache()
    without = clsmodel.classify_window(spec, det, 2431.5)
    assert without.source == "rule" and without.signature_class == "non_uas"

    p = _tiny_bundle(tmp_path / "m.joblib", sample_rate=SAMPLE_RATE,
                     priors={"dji_ocusync": 9, "noise": 1})
    monkeypatch.setenv("AERIX_RF_MODEL", str(p))
    clsmodel._reset_model_cache()
    with_model = clsmodel.classify_window(spec, det, 2431.5)
    assert with_model.source == "sklearn:tiny-test"
    assert with_model.signature_class == "dji_ocusync"
    assert with_model.signature_class != without.signature_class
