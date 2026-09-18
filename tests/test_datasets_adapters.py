"""Tests for the Workstream D, T4 dataset adapters + prepare pipeline.

``test_prepare_dataset_synthetic`` exercises the full S1-S4 pipeline against
a fake adapter over a synthetic tiny dataset in a tmp root -- no downloads,
no dependency on the real local ``~/rf-datasets`` mirrors. The real-dataset
tests (RUB / Zenodo) skip when those mirrors are absent (same convention as
``tests/test_droneid_rub_golden.py``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import numpy as np
import pytest

from aerix_rf.datasets.adapters import (
    AerixSessionAdapter,
    RecordingMeta,
    RubDroneSecurityAdapter,
    ZenodoDroneRF2020Adapter,
    _ZENODO_BAND_CENTER_HZ,
    parse_zenodo_stem,
    source_file_field,
    source_sha256,
)
from aerix_rf.datasets.index import iter_dataset
from aerix_rf.datasets.prepare import prepare_dataset
from aerix_rf.datasets.resample import CANONICAL_RATE_HZ, usable_bandwidth
from aerix_rf.sdr.capture import _read_cs8, _read_cs16, to_cs16, to_cs8
from aerix_rf.datasets.spec import (
    Activity,
    EmitterClass,
    EvidenceLevel,
    LabelSource,
    LabelsGroup,
    LinkFamily,
    LinkRole,
    WindowSidecar,
)

DATASET_ROOT = Path(os.environ.get("AERIX_RF_DATASET_ROOT", "~/rf-datasets")).expanduser()


# ---------------------------------------------------------------------------
# Zenodo filename parsing table
# ---------------------------------------------------------------------------

_ZENODO_CASES = [
    ("DJI_inspire_2_2G", dict(manufacturer="DJI", model="inspire_2", band_token="2G", mode=None, part=None)),
    ("DJI_inspire_2_5G_1of2", dict(manufacturer="DJI", model="inspire_2", band_token="5G", mode=None, part=(1, 2))),
    ("DJI_matrice_210_5G_2of2", dict(manufacturer="DJI", model="matrice_210", band_token="5G", mode=None, part=(2, 2))),
    ("Parrot_mambo_control_2G", dict(manufacturer="Parrot", model="mambo", band_token="2G", mode="control", part=None)),
    ("Parrot_mambo_video_2G", dict(manufacturer="Parrot", model="mambo", band_token="2G", mode="video", part=None)),
    ("Yuneec_typhoon_h_5G", dict(manufacturer="Yuneec", model="typhoon_h", band_token="5G", mode=None, part=None)),
    (
        "DJI_phantom_4_pro_plus_2G",
        dict(manufacturer="DJI", model="phantom_4_pro_plus", band_token="2G", mode=None, part=None),
    ),
]


@pytest.mark.parametrize("stem,expected", _ZENODO_CASES)
def test_parse_zenodo_stem(stem, expected):
    parsed = parse_zenodo_stem(stem)
    assert parsed.manufacturer == expected["manufacturer"]
    assert parsed.model == expected["model"]
    assert parsed.band_token == expected["band_token"]
    assert parsed.mode == expected["mode"]
    assert parsed.part == expected["part"]


def test_parse_zenodo_stem_rejects_unrecognised():
    with pytest.raises(ValueError):
        parse_zenodo_stem("not_a_zenodo_file")


# ---------------------------------------------------------------------------
# RUB labels
# ---------------------------------------------------------------------------


def test_rub_labels_evidence_and_link_family():
    adapter = RubDroneSecurityAdapter()
    rec = RecordingMeta(
        dataset_id="rub_dronesecurity",
        recording_id="mavic_air_2",
        device_id="mavic_air_2",
        run_id="mavic_air_2",
        source_paths=(Path("/dev/null"),),
        original_rate_hz=50e6,
        original_center_freq_hz=2.44e9,
        original_bw_hz=50e6,
        original_dtype="float32_interleaved",
        extra={"model": "mavic_air_2"},
    )
    labels = adapter.labels(rec)
    assert isinstance(labels, LabelsGroup)
    for instance in (labels.scene, labels.window):
        assert instance.emitter_class == EmitterClass.DRONE_LINK
        assert instance.link_family == LinkFamily.OCUSYNC
        assert instance.link_role == LinkRole.BROADCAST_DRONEID
        assert instance.manufacturer == "DJI"
        assert instance.model == "mavic_air_2"
        # Highest evidence level the taxonomy allows for a decoded (not
        # operator-witnessed) label.
        assert instance.evidence_level == EvidenceLevel.VALIDATED_DECODE
        assert instance.label_source == LabelSource.PROTOCOL_DECODE
        # Flight state is not documented by the RUB-SysSec repo/README for
        # either sample -- must stay unknown, not a fabricated "flying".
        assert instance.activity == Activity.UNKNOWN

    rec_mini2 = RecordingMeta(
        **{**rec.__dict__, "recording_id": "mini2_sm", "extra": {"model": "mini_2"}}
    )
    assert adapter.labels(rec_mini2).scene.model == "mini_2"
    assert adapter.labels(rec_mini2).scene.activity == Activity.UNKNOWN


def test_rub_iter_recordings_center_freq_unknown():
    """RUB-SysSec does not record per-file capture centre frequency (no
    logged value, hopped candidate list in the live receiver -- see
    research/briefs/droneid-channel-raster.md). `RecordingMeta.
    original_center_freq_hz` (and the `WindowSidecar.signal.center_freq_hz`
    / `source.original_center_freq_hz` fields it feeds) is `Optional[float]`
    precisely for this case: the adapter reports a true `None`, never a
    sentinel or a fabricated plausible-looking value (e.g. a 2.44 GHz
    ISM-band guess)."""

    adapter = RubDroneSecurityAdapter()
    if not _RUB_DIR.is_dir():
        pytest.skip("RUB-DroneSecurity mirror not found under AERIX_RF_DATASET_ROOT")
    for rec in adapter.iter_recordings(DATASET_ROOT):
        assert rec.original_center_freq_hz is None
        assert rec.notes is not None
        assert "RUB-SysSec" in rec.notes


# ---------------------------------------------------------------------------
# Zenodo centre-frequency audit: values must trace to the record's own
# documentation (research/datasets/manifest.json zenodo_drone_rf_video_2020
# entry: "center_frequency_bands": "2.44 GHz and 5.8 GHz", sourced from the
# Zenodo record description via api.zenodo.org/records/4264467), never a
# guess. mode/manufacturer/model are filename-encoded; activity is not
# encoded anywhere in the record and must stay unknown.
# ---------------------------------------------------------------------------


def test_zenodo_band_center_matches_documented_values():
    assert _ZENODO_BAND_CENTER_HZ["2G"] == pytest.approx(2.44e9)
    assert _ZENODO_BAND_CENTER_HZ["5G"] == pytest.approx(5.8e9)


@pytest.mark.skipif(
    not (DATASET_ROOT / "ZenodoDroneRFVideo2020" / "original").is_dir(),
    reason="Zenodo 2020 mirror not found under AERIX_RF_DATASET_ROOT",
)
def test_zenodo_iter_recordings_center_freq_by_band():
    adapter = ZenodoDroneRF2020Adapter()
    recs = {r.recording_id: r for r in adapter.iter_recordings(DATASET_ROOT)}
    two_ghz = recs["DJI_inspire_2_2G"]
    five_ghz = recs["DJI_inspire_2_5G"]
    assert two_ghz.original_center_freq_hz == pytest.approx(2.44e9)
    assert five_ghz.original_center_freq_hz == pytest.approx(5.8e9)
    # Activity is not documented anywhere in the record: must stay unknown.
    assert adapter.labels(two_ghz).scene.activity == Activity.UNKNOWN
    assert adapter.labels(five_ghz).scene.activity == Activity.UNKNOWN


# ---------------------------------------------------------------------------
# Synthetic prepare_dataset() end-to-end via a fake adapter
# ---------------------------------------------------------------------------

_FAKE_RATE_HZ = 20e6


@dataclass
class _FakeAdapter:
    dataset_id: str = "synthetic_fake"

    def iter_recordings(self, root: Path) -> Iterator[RecordingMeta]:
        specs = [("rec_long", 1.3), ("rec_short", 0.4)]
        for name, duration_s in specs:
            path = root / "original" / f"{name}.f32"
            n = int(round(duration_s * _FAKE_RATE_HZ))
            t = np.arange(n, dtype=np.float64) / _FAKE_RATE_HZ
            tone = 0.5 * np.exp(2j * np.pi * 1.0e6 * t)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tone.astype(np.complex64).tobytes())
            yield RecordingMeta(
                dataset_id=self.dataset_id,
                recording_id=name,
                device_id="fake_device",
                run_id=name,
                source_paths=(path,),
                original_rate_hz=_FAKE_RATE_HZ,
                original_center_freq_hz=2.4e9,
                original_bw_hz=_FAKE_RATE_HZ,
                original_dtype="fake_complex64",
                extra={},
            )

    def load_iq(self, rec: RecordingMeta):
        iq = np.fromfile(rec.source_paths[0], dtype=np.complex64)
        return iq, rec.original_rate_hz, None, None

    def labels(self, rec: RecordingMeta) -> LabelsGroup:
        from aerix_rf.datasets.spec import LabelInstance

        inst = LabelInstance(
            emitter_class=EmitterClass.DRONE_LINK,
            manufacturer="fake_mfr",
            model="fake_model",
            activity=Activity.UNKNOWN,
            evidence_level=EvidenceLevel.RF_CANDIDATE,
            label_source=LabelSource.HEURISTIC_INFERENCE,
        )
        return LabelsGroup(scene=inst, window=inst)


def test_prepare_dataset_synthetic(tmp_path):
    adapter = _FakeAdapter()
    stats = prepare_dataset(
        dataset_id=adapter.dataset_id,
        adapter=adapter,
        root=tmp_path,
        limit=None,
        write_iq=True,
        write_tensor=True,
    )

    assert stats.recordings == 2
    # rec_long (1.3 s) -> one full 1.000 s window + one short 0.3 s window;
    # rec_short (0.4 s) -> one short 0.4 s window. 3 total, 2 short.
    assert stats.windows == 3
    assert stats.short_windows == 2
    assert stats.tensor_shape_example is not None

    index_rows = list(iter_dataset(adapter.dataset_id, root=tmp_path))
    assert len(index_rows) == 3
    for sc in index_rows:
        assert isinstance(sc, WindowSidecar)  # already validated by iter_dataset's model_validate_json

    prepared_dir = tmp_path / adapter.dataset_id / "prepared"
    json_files = sorted(prepared_dir.glob("*.json"))
    assert len(json_files) == 3
    for jf in json_files:
        data = json.loads(jf.read_text())
        WindowSidecar.model_validate(data)  # schema-valid sidecar on disk too

    tensor_files = sorted(prepared_dir.glob("*.tensor.npy"))
    iq_files = sorted(prepared_dir.glob("*.c64.npy"))
    assert len(tensor_files) == 3
    assert len(iq_files) == 3

    # Determinism: rerun into a fresh root produces identical artefact
    # bytes and identical sidecars except created_at.
    tmp_path2 = tmp_path.parent / (tmp_path.name + "_rerun")
    stats2 = prepare_dataset(
        dataset_id=adapter.dataset_id,
        adapter=_FakeAdapter(),
        root=tmp_path2,
        limit=None,
        write_iq=True,
        write_tensor=True,
    )
    assert stats2.windows == stats.windows
    assert stats2.short_windows == stats.short_windows

    prepared_dir2 = tmp_path2 / adapter.dataset_id / "prepared"
    for jf in sorted(prepared_dir.glob("*.json")):
        jf2 = prepared_dir2 / jf.name
        assert jf2.exists(), f"rerun missing sidecar {jf.name}"
        d1, d2 = json.loads(jf.read_text()), json.loads(jf2.read_text())
        d1["bookkeeping"].pop("created_at")
        d2["bookkeeping"].pop("created_at")
        assert d1 == d2, f"sidecar drifted on rerun: {jf.name}"

    for npy in sorted(prepared_dir.glob("*.npy")):
        npy2 = prepared_dir2 / npy.name
        assert npy2.exists()
        assert npy.read_bytes() == npy2.read_bytes(), f"artefact drifted on rerun: {npy.name}"


# ---------------------------------------------------------------------------
# Real-dataset smoke runs (skip if the local mirrors are absent)
# ---------------------------------------------------------------------------

_RUB_DIR = DATASET_ROOT / "RUB-DroneSecurity" / "original" / "samples"
_ZENODO_DIR = DATASET_ROOT / "ZenodoDroneRFVideo2020" / "original"


@pytest.mark.skipif(not _RUB_DIR.is_dir(), reason="RUB-DroneSecurity mirror not found under AERIX_RF_DATASET_ROOT")
def test_rub_iter_recordings_real():
    adapter = RubDroneSecurityAdapter()
    recs = list(adapter.iter_recordings(DATASET_ROOT))
    assert {r.recording_id for r in recs} == {"mavic_air_2", "mini2_sm"}


@pytest.mark.skipif(not _ZENODO_DIR.is_dir(), reason="Zenodo 2020 mirror not found under AERIX_RF_DATASET_ROOT")
def test_zenodo_iter_recordings_real():
    adapter = ZenodoDroneRF2020Adapter()
    recs = list(adapter.iter_recordings(DATASET_ROOT))
    assert len(recs) >= 10
    ids = {r.recording_id for r in recs}
    assert "DJI_inspire_2_2G" in ids


# ---------------------------------------------------------------------------
# AerixSessionAdapter (Workstream D, T5) -- AERIX's own recorded sessions
# (ANTSDR cs16 @ 12.288 MS/s, HackRF cs8 @ 20 MS/s; schema-2 and legacy
# schema-1 session.json).
# ---------------------------------------------------------------------------

_ANTSDR_SESSION_RATE_HZ = 12_288_000.0
_HACKRF_SESSION_RATE_HZ = 20_000_000.0


def _write_antsdr_session(root: Path, dataset_id: str, session_name: str, *, label: str,
                           test_block: dict, n_files: int = 2) -> str:
    """A tiny hand-built schema-2 ANTSDR session dir (cs16 @ 12.288 MS/s,
    full scale 2048.0, 10 MHz declared bandwidth -- deliberately narrower
    than the 12 MHz canonical usable width, so ``band_deficit`` must come
    out True). Returns the session_id."""

    session_id = f"sid-{session_name}"
    sdir = root / dataset_id / "original" / session_name
    (sdir / "iq").mkdir(parents=True)
    n = int(_ANTSDR_SESSION_RATE_HZ * 1.0)
    files = []
    for i in range(n_files):
        t = np.arange(n, dtype=np.float64) / _ANTSDR_SESSION_RATE_HZ
        iq = (0.3 * np.exp(2j * np.pi * 1.5e6 * t)).astype(np.complex64)
        raw = to_cs16(iq, full_scale=2048.0)
        rel = f"iq/capture_{i:04d}.cs16"
        (sdir / rel).write_bytes(raw)
        files.append({
            "file": rel,
            "sha256": "deadbeef",
            "sample_count": n,
            "duration_s": 1.0,
            "sample_rate": _ANTSDR_SESSION_RATE_HZ,
            "center_freq_hz": 2437e6,
            "captured_at": 1_800_000_000.0 + i,
            "complete": True,
            "receiver_type": "antsdr",
            "gain_db": 40.0,
            "capture_health": {
                "expected_samples": n, "received_samples": n,
                "stream_rate_ratio": 1.0325, "rate_warning": False,
                "capture_complete": True, "source_backend": "antsdr",
            },
            "iq_format": "cs16",
            "iq_full_scale": 2048.0,
            "bandwidth_hz": 10_000_000.0,
            "channel_id": 0,
        })
    meta = {
        "schema_version": 2,
        "session_id": session_id,
        "label": label,
        "receiver_type": "antsdr",
        "receiver_serial": None,
        "receiver_backend": "AntsdrIIOSource",
        "receiver_firmware": "v0.34-dirty",
        "iq_format": "cs16",
        "iq_full_scale": 2048.0,
        "bandwidth_hz": 10_000_000.0,
        "gain_mode": "manual",
        "sample_rate": 20_000_000.0,  # pre-decimation IIO rate, NOT the per-file rate
        "center_freq_hz": 2437e6,
        "gains": {"lna_gain": 16, "vga_gain": 24, "amp": False, "gain_db": 40.0},
        "test": test_block,
        "counts": {},
        "files": files,
    }
    (sdir / "session.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return session_id


def test_aerix_session_adapter_antsdr_background(tmp_path):
    dataset_id = "aerix_test_antsdr"
    _write_antsdr_session(
        tmp_path, dataset_id, "2026-09-18_000000_smoke_ambient",
        label="antsdr_iio smoke ambient",
        test_block={"test_label": "antsdr_iio smoke ambient", "drone_manufacturer": None,
                    "drone_model": None},
    )
    adapter = AerixSessionAdapter(dataset_id=dataset_id)
    recs = list(adapter.iter_recordings(tmp_path))
    assert len(recs) == 2

    rec0 = recs[0]
    assert rec0.recording_id == "sid-2026-09-18_000000_smoke_ambient/iq/capture_0000.cs16"
    assert rec0.device_id == "antsdr_AntsdrIIOSource"
    assert rec0.run_id == "sid-2026-09-18_000000_smoke_ambient"
    assert recs[1].run_id == rec0.run_id  # both windows share one split group
    assert rec0.original_rate_hz == pytest.approx(_ANTSDR_SESSION_RATE_HZ)
    assert rec0.original_center_freq_hz == pytest.approx(2437e6)
    assert rec0.original_bw_hz == pytest.approx(10e6)
    assert rec0.original_dtype == "cs16"
    assert rec0.notes is not None and "cs16 session" in rec0.notes
    assert "stream_rate_ratio=1.0325" in rec0.notes

    usable_bw_hz, band_deficit = usable_bandwidth(rec0.original_rate_hz, rec0.original_bw_hz)
    assert band_deficit is True
    assert usable_bw_hz == pytest.approx(10e6)

    labels = adapter.labels(rec0)
    for inst in (labels.scene, labels.window):
        assert inst.emitter_class == EmitterClass.BACKGROUND
        assert inst.evidence_level == EvidenceLevel.OPERATOR_TRUTH
        assert inst.label_source == LabelSource.OPERATOR_GROUND_TRUTH

    iq, in_rate_hz, centre_hz, bw_hz = adapter.load_iq(rec0)
    assert iq.dtype == np.complex64
    assert iq.size == int(_ANTSDR_SESSION_RATE_HZ)
    assert in_rate_hz == pytest.approx(_ANTSDR_SESSION_RATE_HZ)
    assert centre_hz is None and bw_hz is None  # already known via RecordingMeta fields
    expect = _read_cs16(str(rec0.source_paths[0]), 0, iq.size, full_scale=2048.0)
    assert np.array_equal(iq, expect)
    assert np.max(np.abs(iq)) <= 1.0


def test_aerix_session_adapter_drone_test_overrides_background_keywords():
    """A drone field present in ``test`` always wins over a background-ish
    session label -- e.g. a real flight test that happens to be named after
    a routine 'probe' session must not fall back to `background`."""

    adapter = AerixSessionAdapter(dataset_id="x")
    rec = RecordingMeta(
        dataset_id="x", recording_id="r", device_id="d", run_id="r",
        source_paths=(Path("/dev/null"),), original_rate_hz=1.0,
        original_center_freq_hz=None, original_bw_hz=1.0, original_dtype="cs16",
        extra={
            "test": {"drone_manufacturer": "DJI", "drone_model": "mavic_3"},
            "session_label": "probe_default",
        },
    )
    labels = adapter.labels(rec)
    assert labels.scene.emitter_class == EmitterClass.DRONE_LINK
    assert labels.scene.manufacturer == "DJI"
    assert labels.scene.model == "mavic_3"
    assert labels.scene.evidence_level == EvidenceLevel.OPERATOR_TRUTH
    assert labels.scene.label_source == LabelSource.OPERATOR_GROUND_TRUTH


def test_aerix_session_adapter_ambiguous_label_stays_unknown():
    adapter = AerixSessionAdapter(dataset_id="x")
    rec = RecordingMeta(
        dataset_id="x", recording_id="r", device_id="d", run_id="r",
        source_paths=(Path("/dev/null"),), original_rate_hz=1.0,
        original_center_freq_hz=None, original_bw_hz=1.0, original_dtype="cs16",
        extra={"test": {}, "session_label": "t4b1_check"},
    )
    labels = adapter.labels(rec)
    assert labels.scene.emitter_class == EmitterClass.UNKNOWN
    assert labels.scene.evidence_level == EvidenceLevel.RF_CANDIDATE
    assert labels.scene.label_source == LabelSource.UNKNOWN


def test_aerix_session_adapter_schema1_hackrf_legacy(tmp_path):
    """A minimal, hand-built schema-1 session.json (no iq_format/
    iq_full_scale/bandwidth_hz/channel_id/capture_health keys, cs8 file,
    HackRF-style 20 MS/s) must default to cs8/128.0 exactly like
    ``FileIQSource``'s own schema-1 fallback rule."""

    dataset_id = "aerix_test_hackrf"
    session_name = "2024-01-01_000000_baseline_run"
    sdir = tmp_path / dataset_id / "original" / session_name
    (sdir / "iq").mkdir(parents=True)
    n = int(_HACKRF_SESSION_RATE_HZ * 1.0)
    t = np.arange(n, dtype=np.float64) / _HACKRF_SESSION_RATE_HZ
    iq = (0.4 * np.exp(2j * np.pi * 2.0e6 * t)).astype(np.complex64)
    raw = to_cs8(iq)
    (sdir / "iq" / "capture_0001.cs8").write_bytes(raw)
    meta = {
        "schema_version": 1,
        "session_id": "legacy-hackrf-1",
        "label": "baseline_run",
        "files": [{
            "file": "iq/capture_0001.cs8",
            "sample_count": n,
            "sample_rate": _HACKRF_SESSION_RATE_HZ,
            "center_freq_hz": 2440e6,
            "receiver_type": "hackrf",
            "receiver_serial": "OLD-1",
        }],
        "test": {},
        "counts": {},
    }
    (sdir / "session.json").write_text(json.dumps(meta), encoding="utf-8")

    adapter = AerixSessionAdapter(dataset_id=dataset_id)
    recs = list(adapter.iter_recordings(tmp_path))
    assert len(recs) == 1
    rec = recs[0]
    assert rec.original_dtype == "cs8"
    assert rec.original_rate_hz == pytest.approx(_HACKRF_SESSION_RATE_HZ)
    assert rec.original_center_freq_hz == pytest.approx(2440e6)
    assert rec.device_id == "hackrf_OLD-1"

    labels = adapter.labels(rec)
    assert labels.scene.emitter_class == EmitterClass.BACKGROUND
    assert labels.scene.evidence_level == EvidenceLevel.OPERATOR_TRUTH

    iq_out, in_rate_hz, _, _ = adapter.load_iq(rec)
    assert iq_out.size == n
    assert np.max(np.abs(iq_out)) <= 1.0
    expect = _read_cs8(str(rec.source_paths[0]), 0, n)
    assert np.array_equal(iq_out, expect)


def test_aerix_session_adapter_prepare_upsamples_to_canonical(tmp_path):
    """12.288 MS/s -> 15.36 MS/s is a 5/4 up-sample: ``plan_chain`` must
    handle it with a single rational stage (no decimation needed), and the
    prepared canonical window must be exactly 1.0 s at ``CANONICAL_RATE_HZ``
    with a schema-valid sidecar recording the up-sample and the band
    deficit."""

    dataset_id = "aerix_test_prepare"
    _write_antsdr_session(
        tmp_path, dataset_id, "2026-09-18_000000_soak_check",
        label="soak_check", test_block={},
    )
    adapter = AerixSessionAdapter(dataset_id=dataset_id)
    stats = prepare_dataset(dataset_id=dataset_id, adapter=adapter, root=tmp_path,
                             limit=2, write_iq=False, write_tensor=True)
    assert stats.recordings == 2
    assert stats.windows == 2
    assert stats.short_windows == 0

    rows = list(iter_dataset(dataset_id, root=tmp_path))
    assert len(rows) == 2
    for sc in rows:
        assert sc.signal.sample_rate_hz == pytest.approx(CANONICAL_RATE_HZ)
        assert sc.signal.n_samples == int(CANONICAL_RATE_HZ * 1.0)
        assert sc.signal.duration_s == pytest.approx(1.0)
        assert sc.signal.band_deficit is True
        assert sc.source.original_rate_hz == pytest.approx(_ANTSDR_SESSION_RATE_HZ)
        assert sc.source.iq_full_scale_source == "session_metadata"
        chain = sc.source.resample_chain
        assert len(chain) == 1
        assert chain[0].op == "rational"
        assert chain[0].up == 5
        assert chain[0].down == 4
        assert sc.labels.scene.emitter_class == EmitterClass.BACKGROUND


# ---------------------------------------------------------------------------
# Real-mirror smoke: ~/rf-datasets/aerix_antsdr_ambient_2026_09_18 (skip if
# absent).
# ---------------------------------------------------------------------------

_AERIX_REAL_DIR = DATASET_ROOT / "aerix_antsdr_ambient_2026_09_18" / "original"


@pytest.mark.skipif(not _AERIX_REAL_DIR.is_dir(), reason="AERIX ANTSDR session mirror not found under AERIX_RF_DATASET_ROOT")
def test_aerix_session_adapter_real_mirror():
    from aerix_rf.datasets.adapters import ADAPTERS

    adapter = ADAPTERS["aerix_antsdr_ambient_2026_09_18"]
    recs = list(adapter.iter_recordings(DATASET_ROOT))
    assert len(recs) >= 200

    cs16_rec = next(r for r in recs if r.original_dtype == "cs16")
    iq, in_rate_hz, _, _ = adapter.load_iq(cs16_rec)
    assert iq.dtype == np.complex64
    assert iq.size == 12_288_000
    assert np.max(np.abs(iq)) <= 1.0 + 1e-6
    assert np.min(np.abs(iq)) >= 0.0
