"""Tests for bench/benchmark_features_v2.py (F3, docs/design/features-and-benchmark.md S3/S4).

Synthetic tiny corpus: 3 fake "datasets" (playing zenodo/antsdr/rub roles),
12 groups total, written through the real prepare-pipeline artefact shapes
(`<uid>.tensor.npy` + index.jsonl of `WindowSidecar` rows) with a planted
class difference (an in-band level bump for `drone_link` windows), not
through the slow real dataset adapters.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))

from aerix_rf.datasets.index import append, dataset_root  # noqa: E402
from aerix_rf.datasets.spec import (  # noqa: E402
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

import benchmark_features_v2 as bfv  # noqa: E402

CANONICAL_FS = 15_360_000.0
ZENODO_ID = "fake_zenodo"
ANTSDR_ID = "fake_antsdr"
RUB_ID = "fake_rub"

N_ZENODO_MODELS = 4          # tier A group hold-out needs >=2
N_ANTSDR_SESSIONS = 6        # tier D leave-one-session-out needs >=2 (+1 reserved by tier A)
N_RUB_GROUPS = 2
# 4 + 6 + 2 = 12 groups total.


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
    """Floor at -70 dBFS + per-bin noise; `drone_link` windows get a planted
    +25 dB in-band bump over bins [400,460) for the whole window duration --
    a strong, deterministic class difference the classifiers must find."""
    tensor = -70.0 + rng.normal(0.0, 1.0, size=(n_ms, 1024))
    if signal:
        tensor[:, 400:460] += 25.0
    return tensor.astype(np.float32)


def _write_window(
    root: Path, dataset_id: str, device_id: str, run_id: str, idx: int,
    n_ms: int, emitter_class: EmitterClass, rng: np.random.Generator,
) -> None:
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
    # Zenodo-like: N_ZENODO_MODELS model groups, drone_link positives, 1 run
    # each, full-duration (200 ms >= 100 ms) windows.
    for m in range(N_ZENODO_MODELS):
        rng = np.random.default_rng(100 + m)
        for i in range(5):
            _write_window(root, ZENODO_ID, f"model_{m}", f"run_{m}", i, 200,
                          EmitterClass.DRONE_LINK, rng)

    # ANTSDR-like: N_ANTSDR_SESSIONS session groups, background negatives,
    # full-duration windows.
    for s in range(N_ANTSDR_SESSIONS):
        rng = np.random.default_rng(200 + s)
        for i in range(5):
            _write_window(root, ANTSDR_ID, "e200", f"session_{s}", i, 200,
                          EmitterClass.BACKGROUND, rng)

    # RUB-like: N_RUB_GROUPS groups, drone_link positives, short (15 ms)
    # pre-segmented fragments -> G3/G5 masked invalid.
    for g in range(N_RUB_GROUPS):
        rng = np.random.default_rng(300 + g)
        for i in range(3):
            _write_window(root, RUB_ID, f"rubmodel_{g}", f"frag_{g}", i, 15,
                          EmitterClass.DRONE_LINK, rng)


def _run(root: Path):
    return bfv.run_benchmark(zenodo_id=ZENODO_ID, antsdr_id=ANTSDR_ID, rub_id=RUB_ID, root=root)


def test_load_rows_counts(tmp_path: Path):
    _build_corpus(tmp_path)
    rows, skipped, meta = bfv.load_rows(ZENODO_ID, root=tmp_path)
    assert len(rows) == N_ZENODO_MODELS * 5
    assert meta.n_used == N_ZENODO_MODELS * 5
    assert not skipped
    assert all(r.emitter_class == "drone_link" for r in rows)


def test_all_tiers_run_on_synthetic_corpus(tmp_path: Path):
    _build_corpus(tmp_path)
    tier_a, tier_b, tier_d, dataset_meta, skip_counts = _run(tmp_path)

    assert tier_a.ran, tier_a.reason
    assert tier_b.ran, tier_b.reason
    assert tier_d.ran, tier_d.reason

    # tier A: one row per zenodo model group.
    assert len(tier_a.table) == N_ZENODO_MODELS
    # tier D: one row per antsdr session minus the one reserved by tier A.
    assert len(tier_d.table) == N_ANTSDR_SESSIONS
    # tier B: rows per RUB group present in the corpus.
    assert len(tier_b.table) == N_RUB_GROUPS
    # RUB windows are short: G3 and G5 must be excluded from tier B's columns.
    assert tier_b.columns_used < bfv.FEATURES_V2_DIM

    for dsid, meta in dataset_meta.items():
        assert meta.n_used > 0, dsid


def test_metrics_are_in_unit_interval(tmp_path: Path):
    _build_corpus(tmp_path)
    tier_a, tier_b, tier_d, _, _ = _run(tmp_path)

    for row in tier_a.table:
        for key in ("recall_logreg", "recall_gboost", "pr_auc_logreg", "pr_auc_gboost"):
            assert 0.0 <= row[key] <= 1.0, (key, row)
    for row in tier_b.table:
        for key in ("recall_logreg", "recall_gboost"):
            assert 0.0 <= row[key] <= 1.0, (key, row)
    for row in tier_d.table:
        for key in ("pfa_logreg", "pfa_gboost"):
            assert 0.0 <= row[key] <= 1.0, (key, row)
        # FA/hour is PFA * 3600, not itself bounded to [0, 1].
        assert row["fa_per_hour_logreg"] >= 0.0
        assert row["fa_per_hour_gboost"] >= 0.0

    # The planted +25 dB in-band bump should be trivially separable: tier A
    # recall and tier D's (1 - PFA) should both be strong on this synthetic
    # corpus.
    assert np.median([r["recall_gboost"] for r in tier_a.table]) > 0.8
    assert np.median([r["pfa_gboost"] for r in tier_d.table]) < 0.2


def test_deterministic_for_fixed_seed(tmp_path: Path):
    _build_corpus(tmp_path)
    a1, b1, d1, _, _ = _run(tmp_path)
    a2, b2, d2, _, _ = _run(tmp_path)
    assert a1.table == a2.table
    assert b1.table == b2.table
    assert d1.table == d2.table
    assert a1.summary == a2.summary


def test_refuses_on_injected_split_spanning_group(tmp_path: Path, monkeypatch):
    _build_corpus(tmp_path)
    # Collapse every window's group key to a single constant tuple: every
    # tier's train/test partitions now share that one group, which must be
    # detected and refused rather than silently used.
    monkeypatch.setattr(bfv, "_group_key", lambda sc: ("collapsed", "collapsed", "collapsed"))
    with pytest.raises(bfv.SplitLeakError):
        _run(tmp_path)


def test_main_exit_code_4_on_split_spanning_group(tmp_path: Path, monkeypatch):
    _build_corpus(tmp_path)
    monkeypatch.setattr(bfv, "_group_key", lambda sc: ("collapsed", "collapsed", "collapsed"))
    report_path = tmp_path / "out" / "benchmark_features_v2.md"
    code = bfv.main([
        "--zenodo-dataset", ZENODO_ID, "--antsdr-dataset", ANTSDR_ID, "--rub-dataset", RUB_ID,
        "--root", str(tmp_path), "--report", str(report_path),
    ])
    assert code == 4
    assert not report_path.exists()


def test_main_writes_report_with_framing_paragraph_and_tier_c_blocked(tmp_path: Path):
    _build_corpus(tmp_path)
    report_path = tmp_path / "out" / "benchmark_features_v2.md"
    code = bfv.main([
        "--zenodo-dataset", ZENODO_ID, "--antsdr-dataset", ANTSDR_ID, "--rub-dataset", RUB_ID,
        "--root", str(tmp_path), "--report", str(report_path),
            "--probe-report", str(tmp_path / "no_such_probe_report.md"),
    ])
    assert code == 0
    text = report_path.read_text(encoding="utf-8")
    assert bfv.FRAMING_PARAGRAPH in text
    assert "Tier C" in text and "BLOCKED" in text
    assert "Tier A" in text and "Tier B" in text and "Tier D" in text
    assert "receiver-ID probe report not found" in text  # no bench/out/receiver_id_probe.md under tmp_path
    assert "Dataset row counts and versions" in text


def test_main_no_rows_returns_2(tmp_path: Path):
    report_path = tmp_path / "out" / "benchmark_features_v2.md"
    code = bfv.main([
        "--zenodo-dataset", "nonexistent_a", "--antsdr-dataset", "nonexistent_b",
        "--rub-dataset", "nonexistent_c", "--root", str(tmp_path), "--report", str(report_path),
    ])
    assert code == 2
