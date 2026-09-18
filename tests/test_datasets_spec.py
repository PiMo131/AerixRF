"""Tests for aerix_rf.datasets: sidecar schema (spec.py) and index (index.py).

Companion to docs/design/dataset-normalization.md T1 acceptance criteria:
round-trip equality; missing-field / unknown-enum / extra-key rejection;
`unknown` vs `not_applicable` kept distinct; group-level deterministic split
assignment; index append/iterate on a monkeypatched dataset root.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from aerix_rf.datasets import SCHEMA_VERSION, WindowSidecar
from aerix_rf.datasets.index import (
    append,
    assign_splits,
    filter_index,
    group_key,
    iter_all,
    iter_dataset,
)
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
    ReceiverDevice,
    ReceiverGroup,
    ResampleStage,
    SignalInfo,
    SourceInfo,
    Split,
    StageEntry,
)


def _make_sidecar(**overrides) -> WindowSidecar:
    base = dict(
        identity=Identity(
            uid="deadbeef00000001",
            dataset_id="dronerf",
            recording_id="10000_H_00",
            source_file="RF Data_10000_H/10000H_0.csv",
            source_sha256="a" * 64,
            device_id="10000",
            run_id="10000_H",
            channel_id="H",
        ),
        signal=SignalInfo(
            sample_rate_hz=15.36e6,
            duration_s=0.25,
            n_samples=3_840_000,
            center_freq_hz=2.44e9,
            bandwidth_hz=15.36e6,
            usable_bw_hz=15.36e6,
            short_window=True,
        ),
        source=SourceInfo(
            original_rate_hz=40e6,
            original_dtype="float64",
            original_center_freq_hz=2.44e9,
            original_bw_hz=40e6,
            iq_full_scale_source="unknown",
            iq_format_source="real_amplitude",
            resample_chain=[
                ResampleStage(op="decimate", down=2, numtaps=63, window="hann", cutoff_hz=9.6e6, stopband_db=60.0),
                ResampleStage(op="resample_poly", up=96, down=125, numtaps=127, window="hann", cutoff_hz=7.68e6, stopband_db=60.0),
            ],
        ),
        receiver=ReceiverGroup(
            receiver=ReceiverDevice(type="USRP B210"),
            gain=GainInfo(mode=GainMode.UNKNOWN),
            clock=ClockInfo(),
        ),
        levels=LevelsGroup(),
        labels=LabelsGroup(
            scene=LabelInstance(
                emitter_class=EmitterClass.DRONE_LINK,
                link_family=LinkFamily.WIFI_DRONE,
                evidence_level=EvidenceLevel.OPERATOR_TRUTH,
                label_source=LabelSource.DATASET_METADATA,
            ),
            window=LabelInstance(
                emitter_class=EmitterClass.BACKGROUND,
                link_family=LinkFamily.NOT_APPLICABLE,
                activity=Activity.OFF,
                evidence_level=EvidenceLevel.RF_CANDIDATE,
                label_source=LabelSource.HEURISTIC_INFERENCE,
            ),
        ),
        bookkeeping=BookkeepingGroup(
            stage_entry=StageEntry.S1,
            preproc_version="v1",
            config_sha256="b" * 64,
            code_version="0.1.0",
            created_at="2026-09-18T00:00:00.000Z",
        ),
    )
    base.update(overrides)
    return WindowSidecar(**base)


# --------------------------------------------------------------------------
# Round-trip
# --------------------------------------------------------------------------


def test_round_trip_model_json_model():
    sc = _make_sidecar()
    dumped = sc.model_dump_json()
    restored = WindowSidecar.model_validate_json(dumped)
    assert restored == sc
    assert restored.schema_version == SCHEMA_VERSION


def test_round_trip_via_plain_dict():
    sc = _make_sidecar()
    as_dict = json.loads(sc.model_dump_json())
    restored = WindowSidecar.model_validate(as_dict)
    assert restored == sc


def test_round_trip_receiver_gain_readback_and_health_fields():
    """docs/design/features-and-benchmark.md S5#1/#5: gain.db/mode,
    receiver.receiver.rf_bandwidth_hz, receiver.readback, and the three
    signal-group capture-health fields all survive a JSON round trip."""

    sc = _make_sidecar(
        signal=SignalInfo(
            sample_rate_hz=15.36e6,
            duration_s=1.0,
            n_samples=15_360_000,
            center_freq_hz=2.437e9,
            bandwidth_hz=15.36e6,
            usable_bw_hz=10e6,
            band_deficit=True,
            window_deficit_frac=0.01,
            session_deficit_frac=0.005,
            capture_complete=False,
        ),
        receiver=ReceiverGroup(
            receiver=ReceiverDevice(
                type="antsdr",
                backend="AntsdrIIOSource",
                firmware="v0.34-dirty",
                rf_bandwidth_hz=10e6,
            ),
            gain=GainInfo(mode=GainMode.MANUAL, db=40.0),
            clock=ClockInfo(),
            readback={
                "hardwaregain_db": 39.75,
                "gain_control_mode": "manual",
                "rf_bandwidth_hz": 1.0e7,
                "sampling_frequency_hz": 1.2288e7,
                "rf_port": "A_BALANCED",
                "rx_lo_hz": 2.437e9,
            },
        ),
    )
    dumped = sc.model_dump_json()
    restored = WindowSidecar.model_validate_json(dumped)
    assert restored == sc
    assert restored.signal.window_deficit_frac == pytest.approx(0.01)
    assert restored.signal.session_deficit_frac == pytest.approx(0.005)
    assert restored.signal.capture_complete is False
    assert restored.receiver.receiver.rf_bandwidth_hz == pytest.approx(10e6)
    assert restored.receiver.gain.mode == GainMode.MANUAL
    assert restored.receiver.gain.db == pytest.approx(40.0)
    assert restored.receiver.readback["hardwaregain_db"] == pytest.approx(39.75)
    assert restored.receiver.readback["gain_control_mode"] == "manual"


def test_health_and_readback_fields_default_none():
    sc = _make_sidecar()
    assert sc.signal.window_deficit_frac is None
    assert sc.signal.session_deficit_frac is None
    assert sc.signal.capture_complete is None
    assert sc.receiver.receiver.rf_bandwidth_hz is None
    assert sc.receiver.readback is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_signal_window_deficit_frac_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        SignalInfo(
            sample_rate_hz=15.36e6,
            duration_s=1.0,
            n_samples=15_360_000,
            bandwidth_hz=15.36e6,
            usable_bw_hz=15.36e6,
            window_deficit_frac=bad,
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_signal_session_deficit_frac_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        SignalInfo(
            sample_rate_hz=15.36e6,
            duration_s=1.0,
            n_samples=15_360_000,
            bandwidth_hz=15.36e6,
            usable_bw_hz=15.36e6,
            session_deficit_frac=bad,
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_receiver_device_rf_bandwidth_hz_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        ReceiverDevice(rf_bandwidth_hz=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_receiver_group_readback_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        ReceiverGroup(
            receiver=ReceiverDevice(),
            gain=GainInfo(mode=GainMode.UNKNOWN),
            clock=ClockInfo(),
            readback={"hardwaregain_db": bad},
        )


# --------------------------------------------------------------------------
# Rejection: missing fields, unknown enums, extra keys
# --------------------------------------------------------------------------


def test_missing_required_field_rejected():
    sc = _make_sidecar()
    payload = json.loads(sc.model_dump_json())
    del payload["identity"]["dataset_id"]
    with pytest.raises(ValidationError):
        WindowSidecar.model_validate(payload)


def test_unknown_enum_value_rejected():
    sc = _make_sidecar()
    payload = json.loads(sc.model_dump_json())
    payload["labels"]["scene"]["emitter_class"] = "spaceship"
    with pytest.raises(ValidationError):
        WindowSidecar.model_validate(payload)


def test_extra_key_rejected_top_level():
    sc = _make_sidecar()
    payload = json.loads(sc.model_dump_json())
    payload["unexpected_top_level_field"] = 1
    with pytest.raises(ValidationError):
        WindowSidecar.model_validate(payload)


def test_extra_key_rejected_nested_group():
    sc = _make_sidecar()
    payload = json.loads(sc.model_dump_json())
    payload["signal"]["extra_field"] = 1
    with pytest.raises(ValidationError):
        WindowSidecar.model_validate(payload)


# --------------------------------------------------------------------------
# unknown vs not_applicable distinctness
# --------------------------------------------------------------------------


def test_unknown_and_not_applicable_are_distinct_link_family():
    assert LinkFamily.UNKNOWN != LinkFamily.NOT_APPLICABLE
    assert LinkFamily.UNKNOWN.value == "unknown"
    assert LinkFamily.NOT_APPLICABLE.value == "not_applicable"

    unknown_sc = _make_sidecar()
    unknown_sc.labels.window.link_family = LinkFamily.UNKNOWN
    na_sc = _make_sidecar()
    na_sc.labels.window.link_family = LinkFamily.NOT_APPLICABLE
    assert unknown_sc.labels.window.link_family != na_sc.labels.window.link_family

    dumped_unknown = json.loads(unknown_sc.model_dump_json())
    dumped_na = json.loads(na_sc.model_dump_json())
    assert dumped_unknown["labels"]["window"]["link_family"] == "unknown"
    assert dumped_na["labels"]["window"]["link_family"] == "not_applicable"


def test_unknown_and_not_applicable_are_distinct_link_role():
    from aerix_rf.datasets.spec import LinkRole

    assert LinkRole.UNKNOWN != LinkRole.NOT_APPLICABLE


# --------------------------------------------------------------------------
# assign_splits
# --------------------------------------------------------------------------


def _synthetic_index(n_groups: int = 50, windows_per_group: int = 4) -> list[WindowSidecar]:
    out = []
    for g in range(n_groups):
        for w in range(windows_per_group):
            out.append(
                _make_sidecar(
                    identity=Identity(
                        uid=f"uid_{g:03d}_{w:03d}",
                        dataset_id="synth",
                        recording_id=f"rec_{g:03d}",
                        source_file=f"synth/{g:03d}_{w:03d}.bin",
                        source_sha256="c" * 64,
                        device_id=f"dev_{g:03d}",
                        run_id=f"run_{g:03d}",
                    )
                )
            )
    return out


def test_assign_splits_keeps_group_together():
    idx = _synthetic_index()
    splits = assign_splits(idx, seed=1)
    by_group: dict = {}
    for sc in idx:
        key = group_key(sc)
        by_group.setdefault(key, set()).add(splits[key])
    for key, split_set in by_group.items():
        assert len(split_set) == 1


def test_assign_splits_deterministic_for_seed():
    idx = _synthetic_index()
    a = assign_splits(idx, seed=42)
    b = assign_splits(list(reversed(idx)), seed=42)
    assert a == b


def test_assign_splits_varies_with_seed():
    idx = _synthetic_index()
    a = assign_splits(idx, seed=1)
    b = assign_splits(idx, seed=2)
    assert a != b


def test_assign_splits_approximate_fractions():
    idx = _synthetic_index(n_groups=50)
    splits = assign_splits(idx, seed=7, fractions={"train": 0.8, "val": 0.1, "test": 0.1})
    groups = set(group_key(sc) for sc in idx)
    counts = {Split.TRAIN: 0, Split.VAL: 0, Split.TEST: 0}
    for key in groups:
        counts[splits[key]] += 1
    n = len(groups)
    assert 30 <= counts[Split.TRAIN] <= 45  # ~40/50 expected
    assert counts[Split.VAL] + counts[Split.TEST] >= 3
    assert sum(counts.values()) == n


def test_assign_splits_rejects_bad_fractions():
    idx = _synthetic_index(n_groups=2)
    with pytest.raises(ValueError):
        assign_splits(idx, fractions={"train": 0.0, "val": 0.0})


# --------------------------------------------------------------------------
# index append/iterate/filter on a monkeypatched dataset root
# --------------------------------------------------------------------------


def test_index_append_and_iterate(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIX_RF_DATASET_ROOT", str(tmp_path))
    sc1 = _make_sidecar()
    sc2 = _make_sidecar(
        identity=Identity(
            uid="deadbeef00000002",
            dataset_id="dronerf",
            recording_id="10000_H_01",
            source_file="RF Data_10000_H/10000H_1.csv",
            source_sha256="a" * 64,
            device_id="10000",
            run_id="10000_H",
            channel_id="H",
        )
    )
    append(sc1)
    append(sc2)

    read_back = list(iter_dataset("dronerf"))
    assert read_back == [sc1, sc2]

    index_path = tmp_path / "dronerf" / "prepared" / "index.jsonl"
    assert index_path.exists()
    assert len(index_path.read_text().strip().splitlines()) == 2


def test_index_iterate_missing_dataset_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIX_RF_DATASET_ROOT", str(tmp_path))
    assert list(iter_dataset("nonexistent")) == []


def test_index_iter_all_and_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIX_RF_DATASET_ROOT", str(tmp_path))
    sc_dronerf = _make_sidecar()
    sc_other = _make_sidecar(
        identity=Identity(
            uid="feedface00000001",
            dataset_id="zenodo_drone_rf_video_2020",
            recording_id="dji_inspire_2_2G",
            source_file="DJI_inspire_2_2G.bin",
            source_sha256="d" * 64,
            device_id="dji_inspire_2",
            run_id="dji_inspire_2_2G",
        )
    )
    append(sc_dronerf)
    append(sc_other)

    all_sidecars = list(iter_all())
    assert {sc.identity.dataset_id for sc in all_sidecars} == {"dronerf", "zenodo_drone_rf_video_2020"}

    only_dronerf = filter_index(all_sidecars, dataset_id="dronerf")
    assert len(only_dronerf) == 1
    assert only_dronerf[0].identity.dataset_id == "dronerf"

    only_device = filter_index(all_sidecars, device_id="dji_inspire_2")
    assert len(only_device) == 1


def test_group_key_uses_dataset_device_run():
    sc = _make_sidecar()
    assert group_key(sc) == ("dronerf", "10000", "10000_H")


# --------------------------------------------------------------------------
# center_freq_hz / original_center_freq_hz Optional[float]: `None` means
# genuinely unknown, never a fabricated placeholder or sentinel value. Must
# validate, round-trip through JSON, and reject non-finite (NaN/inf).
# --------------------------------------------------------------------------


def test_center_freq_hz_none_validates_and_round_trips():
    sc = _make_sidecar(
        signal=SignalInfo(
            sample_rate_hz=15.36e6,
            duration_s=0.25,
            n_samples=3_840_000,
            center_freq_hz=None,
            bandwidth_hz=15.36e6,
            usable_bw_hz=15.36e6,
            short_window=True,
        ),
        source=SourceInfo(
            original_rate_hz=40e6,
            original_dtype="float64",
            original_center_freq_hz=None,
            original_bw_hz=40e6,
            iq_full_scale_source="unknown",
            iq_format_source="real_amplitude",
        ),
        notes="capture centre frequency not published; see research/briefs/...",
    )
    assert sc.signal.center_freq_hz is None
    assert sc.source.original_center_freq_hz is None

    dumped = sc.model_dump_json()
    payload = json.loads(dumped)
    assert payload["signal"]["center_freq_hz"] is None
    assert payload["source"]["original_center_freq_hz"] is None
    assert payload["notes"] == sc.notes

    restored = WindowSidecar.model_validate_json(dumped)
    assert restored == sc
    assert restored.signal.center_freq_hz is None
    assert restored.source.original_center_freq_hz is None


def test_notes_defaults_to_none():
    sc = _make_sidecar()
    assert sc.notes is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_signal_center_freq_hz_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        SignalInfo(
            sample_rate_hz=15.36e6,
            duration_s=0.25,
            n_samples=3_840_000,
            center_freq_hz=bad,
            bandwidth_hz=15.36e6,
            usable_bw_hz=15.36e6,
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_source_original_center_freq_hz_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        SourceInfo(
            original_rate_hz=40e6,
            original_dtype="float64",
            original_center_freq_hz=bad,
            original_bw_hz=40e6,
            iq_full_scale_source="unknown",
            iq_format_source="real_amplitude",
        )


def test_no_absolute_hz_helper_exists_yet():
    """Documents current state for the reviewer: as of this schema change,
    no function in aerix_rf.datasets or aerix_rf.classify computes an
    absolute RF frequency (e.g. band edges) from `center_freq_hz` /
    `original_center_freq_hz` -- confirmed by grep across both packages.
    When such a helper is added, it must raise or explicitly flag on
    `None` rather than silently defaulting (e.g. to 0.0) or adding None to
    an offset. There is nothing to unit-test yet because no such helper
    exists; this test exists so a future helper addition trips this
    module's test suite for a reviewer to notice and add real coverage."""

    import ast
    import inspect

    from aerix_rf.datasets import tensor as tensor_mod
    from aerix_rf.datasets import index as index_mod

    for mod in (tensor_mod, index_mod):
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                "center_freq_hz",
                "original_center_freq_hz",
            ):
                pytest.fail(
                    f"{mod.__name__} now references {node.attr}; add explicit "
                    "None-handling coverage for it and update this test"
                )
