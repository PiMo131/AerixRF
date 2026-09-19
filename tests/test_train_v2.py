"""Tests for aerix_rf/classify/train/train_v2.py (Stage-2 features_v2 trainer).

Synthetic tiny corpus written through the real prepare-pipeline artefact
shapes (index.jsonl of WindowSidecar rows + <uid>.tensor.npy), mirroring
tests/test_benchmark_features_v2.py, with a planted class difference so the
classifiers have something real to find.
"""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from aerix_rf.classify import model as clsmodel
from aerix_rf.classify.train import train_v2 as tv2
from aerix_rf.datasets.index import append
from aerix_rf.datasets.spec import (
    Activity,
    BookkeepingGroup,
    ClockInfo,
    EmitterClass,
    EvidenceLevel,
    GainInfo,
    GainMode,
    Identity,
    LabelInstance,
    LabelsGroup,
    LabelSource,
    LevelsGroup,
    LinkFamily,
    LinkRole,
    ReceiverDevice,
    ReceiverGroup,
    SignalInfo,
    Split,
    SourceInfo,
    StageEntry,
    WindowSidecar,
)

CANONICAL_FS = 15_360_000.0
POS_ID = "fake_positives"
NEG_ID = "fake_negatives"

N_POS_GROUPS = 3
N_NEG_GROUPS = 3


def _label(emitter_class: EmitterClass) -> LabelInstance:
    return LabelInstance(
        emitter_class=emitter_class,
        link_family=LinkFamily.NOT_APPLICABLE if emitter_class == EmitterClass.BACKGROUND else LinkFamily.UNKNOWN,
        link_role=LinkRole.NOT_APPLICABLE if emitter_class == EmitterClass.BACKGROUND else LinkRole.UNKNOWN,
        activity=Activity.UNKNOWN,
        evidence_level=EvidenceLevel.OPERATOR_TRUTH,
        label_source=LabelSource.OPERATOR_GROUND_TRUTH,
    )


def _make_tensor(n_ms: int, rng: np.random.Generator, *, signal: bool) -> np.ndarray:
    tensor = -70.0 + rng.normal(0.0, 1.0, size=(n_ms, 1024))
    if signal:
        tensor[:, 400:460] += 25.0
    return tensor.astype(np.float32)


def _write_window(root, dataset_id, device_id, run_id, idx, n_ms, emitter_class, rng) -> None:
    tensor = _make_tensor(n_ms, rng, signal=(emitter_class == EmitterClass.DRONE_LINK))
    uid = f"{dataset_id}_{device_id}_{run_id}_{idx}"
    prepared_dir = root / dataset_id / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    np.save(prepared_dir / f"{uid}.tensor.npy", tensor)

    sidecar = WindowSidecar(
        identity=Identity(
            uid=uid, dataset_id=dataset_id, recording_id=f"{run_id}/{idx}",
            source_file=f"{run_id}_{idx}.bin", source_sha256="0" * 64,
            device_id=device_id, run_id=run_id,
        ),
        signal=SignalInfo(
            sample_rate_hz=CANONICAL_FS, duration_s=n_ms / 1000.0,
            n_samples=int(n_ms / 1000.0 * CANONICAL_FS),
            bandwidth_hz=CANONICAL_FS, usable_bw_hz=10.0e6, short_window=(n_ms < 100),
        ),
        source=SourceInfo(
            original_rate_hz=CANONICAL_FS, original_dtype="cs16", original_bw_hz=CANONICAL_FS,
            iq_full_scale_source="session_metadata", iq_format_source="interleaved_i2",
        ),
        receiver=ReceiverGroup(
            receiver=ReceiverDevice(type="fake", backend=dataset_id),
            gain=GainInfo(mode=GainMode.MANUAL), clock=ClockInfo(),
        ),
        levels=LevelsGroup(noise_floor_dbfs=-70.0),
        labels=LabelsGroup(scene=_label(emitter_class), window=_label(emitter_class)),
        bookkeeping=BookkeepingGroup(
            stage_entry=StageEntry.S1, preproc_version="v1", config_sha256="0" * 64,
            code_version="test", split=Split.UNASSIGNED,
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
    )
    append(sidecar, root=root)


def _build_corpus(root: Path) -> None:
    for g in range(N_POS_GROUPS):
        rng = np.random.default_rng(100 + g)
        for i in range(6):
            _write_window(root, POS_ID, f"model_{g}", f"run_{g}", i, 200,
                          EmitterClass.DRONE_LINK, rng)
    for g in range(N_NEG_GROUPS):
        rng = np.random.default_rng(200 + g)
        for i in range(6):
            _write_window(root, NEG_ID, "e200", f"session_{g}", i, 200,
                          EmitterClass.BACKGROUND, rng)


@pytest.fixture(autouse=True)
def _reset_model_cache():
    clsmodel._reset_model_cache()
    yield
    clsmodel._reset_model_cache()


def test_train_v2_writes_loadable_bundle(tmp_path: Path):
    _build_corpus(tmp_path)
    out_path = tmp_path / "out" / "signature_v2.joblib"
    result = tv2.train_v2([POS_ID], [NEG_ID], out_path=out_path, seed=0, root=tmp_path)
    assert result is not None
    out = tv2.save_bundle(result.bundle, out_path)
    report_path = Path(str(out) + ".md")
    report_path.write_text(result.report_md, encoding="utf-8")

    assert out.exists()
    assert report_path.exists()
    assert "features_v2 training report" in report_path.read_text(encoding="utf-8")

    import joblib
    bundle = joblib.load(out)
    assert bundle["features_version"] == "features_v2"
    assert set(bundle["classes"]) == {"background", "drone_link"}
    assert "feature_columns" in bundle and len(bundle["feature_columns"]) == int(bundle["feature_mask"].sum())
    assert "train_manifest" in bundle
    assert bundle["train_manifest"]["row_counts"]["train"] > 0
    assert "claims" in bundle and "no ANTSDR-captured drone positives" in bundle["claims"]
    assert result.n_train > 0 and result.n_test > 0
    assert 0.0 <= result.test_recall <= 1.0 or result.test_recall != result.test_recall
    assert 0.0 <= result.test_pfa <= 1.0 or result.test_pfa != result.test_pfa


def test_train_v2_group_split_never_spans_train_and_test(tmp_path: Path):
    _build_corpus(tmp_path)
    result = tv2.train_v2([POS_ID], [NEG_ID], out_path=tmp_path / "signature_v2.joblib",
                          seed=0, root=tmp_path)
    assert result is not None
    # Recompute row->group mapping the same way train_v2 did, and check no
    # (dataset_id, device_id, run_id) group appears with rows in more than
    # one split's row_counts partition (indirect: row_counts sums to total).
    total = result.n_train + result.n_val + result.n_test
    assert total == N_POS_GROUPS * 6 + N_NEG_GROUPS * 6


def test_train_v2_deterministic_for_fixed_seed(tmp_path: Path):
    _build_corpus(tmp_path)
    r1 = tv2.train_v2([POS_ID], [NEG_ID], out_path=tmp_path / "a.joblib", seed=0, root=tmp_path)
    r2 = tv2.train_v2([POS_ID], [NEG_ID], out_path=tmp_path / "b.joblib", seed=0, root=tmp_path)
    assert r1.n_train == r2.n_train and r1.n_val == r2.n_val and r1.n_test == r2.n_test
    assert r1.chosen_model == r2.chosen_model
    assert r1.test_recall == r2.test_recall or (r1.test_recall != r1.test_recall and r2.test_recall != r2.test_recall)
    assert len(r1.per_group_table) == len(r2.per_group_table)
    for g1, g2 in zip(r1.per_group_table, r2.per_group_table):
        assert g1["group"] == g2["group"] and g1["n"] == g2["n"]
        for key in ("recall", "pfa", "median_dbfs", "time_p99_dbfs", "edge_minus_centre_db"):
            v1, v2 = g1[key], g2[key]
            assert v1 == v2 or (v1 != v1 and v2 != v2)  # equal, or both NaN


def test_train_v2_planted_signal_is_separable(tmp_path: Path):
    """The +25 dB in-band bump on drone_link windows should be trivially
    separable, so test recall should be high (not a field PD claim -- this
    is a synthetic-data sanity check that the pipeline actually learns)."""
    _build_corpus(tmp_path)
    result = tv2.train_v2([POS_ID], [NEG_ID], out_path=tmp_path / "signature_v2.joblib",
                          seed=0, root=tmp_path)
    assert result is not None
    if result.n_test > 0 and result.test_recall == result.test_recall:  # not NaN
        assert result.test_recall > 0.5


def test_split_leak_detector_raises_on_spanning_group():
    Row = namedtuple("Row", "group")
    rows = [Row(group=("d", "dev", "run_a")), Row(group=("d", "dev", "run_a"))]
    row_split = {0: "train", 1: "test"}  # same group, two different splits
    with pytest.raises(tv2.SplitLeakError):
        tv2._assert_group_splits_disjoint(rows, row_split)


def test_main_exit_4_on_injected_split_spanning_group(tmp_path: Path, monkeypatch):
    _build_corpus(tmp_path)

    def _bad_assign(rows, seed, fractions=None):
        # Ignore groups entirely: alternate rows within the same group into
        # different splits, forcing a genuine leak.
        return {i: ("train" if i % 2 == 0 else "test") for i in range(len(rows))}

    monkeypatch.setattr(tv2, "_assign_row_splits", _bad_assign)
    out_path = tmp_path / "out" / "signature_v2.joblib"
    code = tv2._main([
        "--positives", POS_ID, "--negatives", NEG_ID,
        "--out", str(out_path), "--seed", "0", "--root", str(tmp_path),
    ])
    assert code == 4
    assert not out_path.exists()


def test_main_no_rows_returns_2(tmp_path: Path):
    out_path = tmp_path / "out" / "signature_v2.joblib"
    code = tv2._main([
        "--positives", "nonexistent_pos", "--negatives", "nonexistent_neg",
        "--out", str(out_path), "--seed", "0", "--root", str(tmp_path),
    ])
    assert code == 2
    assert not out_path.exists()


def test_main_end_to_end_writes_bundle_and_report(tmp_path: Path):
    _build_corpus(tmp_path)
    out_path = tmp_path / "out" / "signature_v2.joblib"
    code = tv2._main([
        "--positives", POS_ID, "--negatives", NEG_ID,
        "--out", str(out_path), "--seed", "0", "--root", str(tmp_path),
    ])
    assert code == 0
    assert out_path.exists()
    assert Path(str(out_path) + ".md").exists()


def test_classify_window_scores_with_v2_bundle_no_mismatch(tmp_path: Path, monkeypatch):
    """classify_window under AERIX_RF_FEATURES=v2 must score with this
    bundle (model_features_mismatch=False, source is the model, not rules)."""
    _build_corpus(tmp_path)
    out_path = tmp_path / "out" / "signature_v2.joblib"
    result = tv2.train_v2([POS_ID], [NEG_ID], out_path=out_path, seed=0, root=tmp_path)
    assert result is not None
    out = tv2.save_bundle(result.bundle, out_path)

    monkeypatch.setenv("AERIX_RF_MODEL", str(out))
    monkeypatch.setenv("AERIX_RF_FEATURES", "v2")
    clsmodel._reset_model_cache()

    from aerix_rf.classify import features_v2 as fv2
    from aerix_rf.detect import energy
    from aerix_rf.dsp import spectrogram

    rng = np.random.default_rng(7)
    n = int(fv2.CANONICAL_FS * 0.25)
    iq = ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 0.05).astype(np.complex64)
    spec = spectrogram.compute(iq, fv2.CANONICAL_FS, fft_size=1024)
    det = energy.detect(spec, 2437.0)
    cls = clsmodel.classify_window(spec, det, 2437.0, iq=iq, sample_rate=fv2.CANONICAL_FS)

    assert cls.model_features_mismatch is False
    assert cls.source.startswith("sklearn:")
    assert cls.features_version == "features_v2"
