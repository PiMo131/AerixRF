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
    RfuavAdapter,
    RubDroneSecurityAdapter,
    ZenodoDroneRF2020Adapter,
    _ZENODO_BAND_CENTER_HZ,
    parse_rfuav_pack_xml,
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
    GainMode,
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
                           test_block: dict, n_files: int = 2,
                           capture_health_overrides: Optional[list] = None) -> str:
    """A tiny hand-built schema-2 ANTSDR session dir (cs16 @ 12.288 MS/s,
    full scale 2048.0, 10 MHz declared bandwidth -- deliberately narrower
    than the 12 MHz canonical usable width, so ``band_deficit`` must come
    out True). Returns the session_id.

    ``capture_health_overrides`` (optional): a list of length ``n_files``,
    each entry either ``None`` (keep the default full-rate capture_health)
    or a dict that replaces the default ``capture_health`` for that file
    entirely -- used by the receiver-metadata/capture-health tests below.
    """

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
        default_health = {
            "expected_samples": n, "received_samples": n,
            "stream_rate_ratio": 1.0325, "rate_warning": False,
            "capture_complete": True, "source_backend": "antsdr",
        }
        override = capture_health_overrides[i] if capture_health_overrides else None
        capture_health = override if override is not None else default_health
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
            "capture_health": capture_health,
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


def test_aerix_session_adapter_receiver_gain_and_health_new_session(tmp_path):
    """docs/design/features-and-benchmark.md S5#1/#5, new-format session:
    sidecar receiver.gain.{mode,db}, receiver.receiver.{backend,firmware,
    rf_bandwidth_hz} and signal.{window,session}_deficit_frac /
    capture_complete are all filled from session.json, not left at their
    generic third-party-dataset placeholder."""

    dataset_id = "aerix_test_health"
    n = int(_ANTSDR_SESSION_RATE_HZ * 1.0)
    overrides = [
        {  # 12,288,000 expected / 12,165,120 received -> 0.01 deficit
            "expected_samples": n, "received_samples": 12_165_120,
            "stream_rate_ratio": 0.99, "rate_warning": True,
            "capture_complete": False, "source_backend": "antsdr",
        },
        {  # second file: fully delivered
            "expected_samples": n, "received_samples": n,
            "stream_rate_ratio": 1.0, "rate_warning": False,
            "capture_complete": True, "source_backend": "antsdr",
        },
    ]
    _write_antsdr_session(
        tmp_path, dataset_id, "2026-09-18_000001_soak_check",
        label="soak_check", test_block={}, capture_health_overrides=overrides,
    )
    adapter = AerixSessionAdapter(dataset_id=dataset_id)
    stats = prepare_dataset(dataset_id=dataset_id, adapter=adapter, root=tmp_path,
                             limit=2, write_iq=False, write_tensor=True)
    assert stats.windows == 2

    rows = sorted(iter_dataset(dataset_id, root=tmp_path), key=lambda sc: sc.identity.recording_id)

    sc0 = rows[0]
    assert sc0.receiver.gain.mode == GainMode.MANUAL
    assert sc0.receiver.gain.db == pytest.approx(40.0)
    assert sc0.receiver.receiver.backend == "AntsdrIIOSource"
    assert sc0.receiver.receiver.firmware == "v0.34-dirty"
    assert sc0.receiver.receiver.rf_bandwidth_hz == pytest.approx(10e6)
    assert sc0.signal.window_deficit_frac == pytest.approx(0.01)
    assert sc0.signal.session_deficit_frac == pytest.approx(0.01)
    assert sc0.signal.capture_complete is False

    sc1 = rows[1]
    # Cumulative across both files: (2n - (12_165_120 + n)) / 2n == 0.005
    assert sc1.signal.window_deficit_frac == pytest.approx(0.0)
    assert sc1.signal.session_deficit_frac == pytest.approx(0.005)
    assert sc1.signal.capture_complete is True
    # gain/backend fields are session-wide, same on every window
    assert sc1.receiver.gain.db == pytest.approx(40.0)


def test_aerix_session_adapter_legacy_stream_rate_ratio_only_health_is_none(tmp_path):
    """An old session whose only capture-health signal is a noisy
    per-window ``stream_rate_ratio`` (no expected_samples/received_samples)
    must leave both deficit fields ``None`` -- never derived from the noisy
    ratio."""

    dataset_id = "aerix_test_legacy_health"
    overrides = [
        {"stream_rate_ratio": 0.87, "rate_warning": True},
        {"stream_rate_ratio": 1.04, "rate_warning": False},
    ]
    _write_antsdr_session(
        tmp_path, dataset_id, "2026-09-18_000002_soak_check",
        label="soak_check", test_block={}, capture_health_overrides=overrides,
    )
    adapter = AerixSessionAdapter(dataset_id=dataset_id)
    recs = list(adapter.iter_recordings(tmp_path))
    assert len(recs) == 2
    for rec in recs:
        assert rec.extra["health"]["window_deficit_frac"] is None
        assert rec.extra["health"]["session_deficit_frac"] is None
        assert rec.extra["health"]["capture_complete"] is None
        # notes must no longer contain a free-text rate_warning marker
        assert "rate_warning" not in (rec.notes or "")
        assert "stream_rate_ratio=" in (rec.notes or "")


def test_aerix_session_adapter_schema1_receiver_and_health_fields_unknown(tmp_path):
    """A minimal schema-1 session.json (no gains/capture_health/bandwidth_hz
    keys at all) must leave the new receiver/health fields at their
    genuinely-unknown defaults, never a guessed value."""

    dataset_id = "aerix_test_schema1_health"
    session_name = "2024-01-01_000000_baseline_run"
    sdir = tmp_path / dataset_id / "original" / session_name
    (sdir / "iq").mkdir(parents=True)
    n = int(_HACKRF_SESSION_RATE_HZ * 1.0)
    t = np.arange(n, dtype=np.float64) / _HACKRF_SESSION_RATE_HZ
    iq = (0.4 * np.exp(2j * np.pi * 2.0e6 * t)).astype(np.complex64)
    (sdir / "iq" / "capture_0001.cs8").write_bytes(to_cs8(iq))
    meta = {
        "schema_version": 1,
        "session_id": "legacy-hackrf-2",
        "label": "baseline_run",
        "files": [{
            "file": "iq/capture_0001.cs8",
            "sample_count": n,
            "sample_rate": _HACKRF_SESSION_RATE_HZ,
            "center_freq_hz": 2440e6,
            "receiver_type": "hackrf",
            "receiver_serial": "OLD-2",
        }],
        "test": {},
        "counts": {},
    }
    (sdir / "session.json").write_text(json.dumps(meta), encoding="utf-8")

    adapter = AerixSessionAdapter(dataset_id=dataset_id)
    rec = next(adapter.iter_recordings(tmp_path))
    assert rec.extra["health"] == {
        "window_deficit_frac": None, "session_deficit_frac": None, "capture_complete": None,
    }
    assert rec.extra["receiver"]["gain_db"] is None
    assert rec.extra["receiver"]["gain_mode"] is None
    assert rec.extra["receiver"]["readback"] is None
    # No session-level bandwidth_hz -> falls back to the file's own rate.
    assert rec.extra["receiver"]["rf_bandwidth_hz"] == pytest.approx(_HACKRF_SESSION_RATE_HZ)


def test_aerix_session_adapter_prefers_annotations_json(tmp_path):
    """When `annotations.json` (`aerix-rf annotate`, T-annotate) exists next
    to a session, its per-window operator-timeline label wins over the
    `test`-block heuristics, and each annotated interval becomes its own
    `run_id` split group -- never the bare session_id shared across the
    whole session (see AerixSessionAdapter's docstring)."""

    dataset_id = "aerix_test_annotations"
    session_name = "2026-09-19_060000_positives_24"
    session_id = _write_antsdr_session(
        tmp_path, dataset_id, session_name,
        label="positives_24",
        test_block={"drone_manufacturer": "DJI", "drone_model": "mavic_3"},
        n_files=2,
    )
    sdir = tmp_path / dataset_id / "original" / session_name
    annotations = {
        "schema": 1,
        "tz": "UTC",
        "session_id": session_id,
        "intervals": [
            {"id": "off-baseline", "start_iso": "2026-09-19T06:00:00.000Z",
             "end_iso": "2026-09-19T06:00:01.000Z", "note": "baseline"},
            {"id": "on-near", "start_iso": "2026-09-19T06:00:01.000Z",
             "end_iso": "2026-09-19T06:00:02.000Z", "note": "drone near"},
        ],
        "windows": [
            {
                "index": 0, "file": "iq/capture_0000.cs16", "captured_at": 1_800_000_000.0,
                "interval_id": "off-baseline",
                "label": {
                    "emitter_class": "background", "link_family": "not_applicable",
                    "link_role": "not_applicable", "manufacturer": "unknown", "model": "unknown",
                    "individual_id": "unknown", "activity": "off",
                    "evidence_level": 5, "label_source": "operator_ground_truth",
                },
                "evidence_level": 5, "label_source": "operator_truth", "transition": False,
            },
            {
                "index": 1, "file": "iq/capture_0001.cs16", "captured_at": 1_800_000_001.0,
                "interval_id": "on-near",
                "label": {
                    "emitter_class": "drone_link", "link_family": "unknown", "link_role": "unknown",
                    "manufacturer": "DJI", "model": "mavic_3", "individual_id": "unknown",
                    "activity": "unknown", "evidence_level": 5, "label_source": "operator_ground_truth",
                },
                "evidence_level": 5, "label_source": "operator_truth", "transition": False,
            },
        ],
    }
    (sdir / "annotations.json").write_text(json.dumps(annotations), encoding="utf-8")

    adapter = AerixSessionAdapter(dataset_id=dataset_id)
    recs = list(adapter.iter_recordings(tmp_path))
    assert len(recs) == 2
    rec0, rec1 = recs

    assert rec0.run_id == f"{session_id}/off-baseline"
    assert rec1.run_id == f"{session_id}/on-near"
    assert rec0.run_id != rec1.run_id  # each interval is its own split group

    labels0 = adapter.labels(rec0)
    assert labels0.scene.emitter_class == EmitterClass.BACKGROUND
    assert labels0.scene.evidence_level == EvidenceLevel.OPERATOR_TRUTH
    assert labels0.scene.label_source == LabelSource.OPERATOR_GROUND_TRUTH

    labels1 = adapter.labels(rec1)
    assert labels1.scene.emitter_class == EmitterClass.DRONE_LINK
    assert labels1.scene.manufacturer == "DJI"
    assert labels1.scene.model == "mavic_3"

    stats = prepare_dataset(dataset_id=dataset_id, adapter=adapter, root=tmp_path,
                             limit=1, write_iq=False, write_tensor=True)
    assert stats.windows == 1
    sc = next(iter_dataset(dataset_id, root=tmp_path))
    # This session's own session.json carries real receiver/health metadata
    # (an ANTSDR session, unlike the legacy-schema1 HackRF fixture above) --
    # annotating a session must not blank out its receiver/capture-health
    # sidecar fields, only add/override the operator-truth label + run_id
    # split group (see AerixSessionAdapter's docstring).
    assert sc.receiver.gain.mode == GainMode.MANUAL
    assert sc.receiver.gain.db == pytest.approx(40.0)
    assert sc.receiver.readback is None
    assert sc.signal.window_deficit_frac == pytest.approx(0.0)
    assert sc.signal.session_deficit_frac == pytest.approx(0.0)
    assert sc.signal.capture_complete is True


# ---------------------------------------------------------------------------
# Real-mirror smoke: ~/rf-datasets/aerix_antsdr_ambient_2026_09_18 (skip if
# absent).
# ---------------------------------------------------------------------------

_AERIX_REAL_DIR = DATASET_ROOT / "aerix_antsdr_ambient_2026_09_18" / "original"



# ---------------------------------------------------------------------------
# RfuavAdapter (Workstream D, T6) -- pack<K>.xml (SignalHound-style
# metadata) + pack<K>_<a>-<b>s.iq (raw complex64, no header) synthetic
# archive layout, no .rar/unrar dependency. Format verified empirically
# against the real DJI_MINI4_PRO.rar extraction -- see
# ~/rf-datasets/rfuav/original/FORMAT.md.
# ---------------------------------------------------------------------------

_RFUAV_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<SignalHoundIQFile Version="1.0">
    <DeviceType>USRPX310</DeviceType>
    <Drone>{drone}</Drone>
    <SerialNumber>{serial}</SerialNumber>
    <DataType>{data_type}</DataType>
    <ReferenceSNRLevel>29</ReferenceSNRLevel>
    <CenterFrequency>2450000000.000</CenterFrequency>
    <SampleRate>{sample_rate}</SampleRate>
    <IFBandwidth>{sample_rate}</IFBandwidth>
    <ScaleFactor>60</ScaleFactor>
    <IQFileName>{pack}.iq</IQFileName>
    <SampleCount>{sample_count}</SampleCount>
</SignalHoundIQFile>
"""


def _write_rfuav_iq_slice(path: Path, n_samples: int, start_value: float = 0.0) -> np.ndarray:
    """Writes ``n_samples`` complex64 values (interleaved float32 I/Q) as a
    header-less raw file, the same layout FORMAT.md documents for a real
    ``pack<K>_<a>-<b>s.iq``. Returns the complex64 array written, for the
    caller to assert ``load_iq`` round-trips it exactly."""

    iq = (np.arange(n_samples, dtype=np.float32) + start_value) + 1j * (
        np.arange(n_samples, dtype=np.float32) * 0.5 + start_value
    )
    iq = iq.astype(np.complex64)
    iq.view(np.float32).tofile(path)
    return iq


def _build_rfuav_mirror(
    root: Path, drone: str = "DJI TESTMODEL", n_samples: int = 4, sample_rate_hz: float = 1000.0
) -> Path:
    """Builds ``root/rfuav/original/extracted/<drone>/VTSBW=10/pack1.xml`` +
    two 1-second-numbered ``.iq`` slices, plus an incomplete
    ``VTSBW=20/pack2.xml``(+``.aria2``) pack that ``iter_recordings`` must
    refuse (same S1 incomplete-download rule the Zenodo adapter already
    applies)."""

    base = root / "rfuav" / "original" / "extracted" / drone
    pack1_dir = base / "VTSBW=10"
    pack1_dir.mkdir(parents=True)
    (pack1_dir / "pack1.xml").write_text(
        _RFUAV_XML_TEMPLATE.format(
            drone=drone, serial="00099", data_type="Complex Float", pack="pack1",
            sample_count=n_samples, sample_rate=sample_rate_hz,
        ),
        encoding="utf-8",
    )
    _write_rfuav_iq_slice(pack1_dir / "pack1_0-1s.iq", n_samples, start_value=0.0)
    _write_rfuav_iq_slice(pack1_dir / "pack1_1-2s.iq", n_samples, start_value=100.0)

    pack2_dir = base / "VTSBW=20"
    pack2_dir.mkdir(parents=True)
    (pack2_dir / "pack2.xml").write_text(
        _RFUAV_XML_TEMPLATE.format(
            drone=drone, serial="00100", data_type="Complex Float", pack="pack2",
            sample_count=n_samples, sample_rate=sample_rate_hz,
        ),
        encoding="utf-8",
    )
    (pack2_dir / "pack2.xml.aria2").write_text("", encoding="utf-8")  # incomplete download
    _write_rfuav_iq_slice(pack2_dir / "pack2_0-1s.iq", n_samples)
    return base


def test_rfuav_parse_pack_xml(tmp_path):
    xml_path = tmp_path / "pack1.xml"
    xml_path.write_text(
        _RFUAV_XML_TEMPLATE.format(
            drone="DJI MINI4 PRO", serial="00014", data_type="Complex Float",
            pack="pack1", sample_count=100_000_000, sample_rate=1000.0,
        ),
        encoding="utf-8",
    )
    meta = parse_rfuav_pack_xml(xml_path)
    assert meta.drone == "DJI MINI4 PRO"
    assert meta.sample_rate_hz == pytest.approx(1000.0)
    assert meta.center_freq_hz == pytest.approx(2.45e9)
    assert meta.if_bandwidth_hz == pytest.approx(1000.0)
    assert meta.sample_count == 100_000_000
    assert meta.scale_factor == pytest.approx(60.0)
    assert meta.reference_snr_level == pytest.approx(29.0)
    assert meta.serial_number == "00014"
    assert meta.note is None  # "Complex Float" is the verified/expected DataType


def test_rfuav_parse_pack_xml_unexpected_datatype_flagged(tmp_path):
    xml_path = tmp_path / "pack_weird.xml"
    xml_path.write_text(
        _RFUAV_XML_TEMPLATE.format(
            drone="DJI MINI4 PRO", serial="00014", data_type="Complex Int16",
            pack="pack1", sample_count=10, sample_rate=1000.0,
        ),
        encoding="utf-8",
    )
    meta = parse_rfuav_pack_xml(xml_path)
    assert meta.note is not None
    assert "Complex Int16" in meta.note


def test_rfuav_iter_recordings_synthetic(tmp_path):
    _build_rfuav_mirror(tmp_path)
    adapter = RfuavAdapter()
    recs = {r.recording_id: r for r in adapter.iter_recordings(tmp_path)}

    # pack2 (VTSBW=20) is incomplete (pack2.xml.aria2 sibling) and must be
    # refused entirely -- only pack1's two slices are enumerated.
    assert set(recs) == {
        "dji_testmodel/VTSBW=10/pack1_0-1s",
        "dji_testmodel/VTSBW=10/pack1_1-2s",
    }
    r0 = recs["dji_testmodel/VTSBW=10/pack1_0-1s"]
    r1 = recs["dji_testmodel/VTSBW=10/pack1_1-2s"]
    assert r0.device_id == "dji_testmodel"
    # Both slices of one pack share a run_id: one continuous capture must
    # never be split across train/val/test.
    assert r0.run_id == r1.run_id == "dji_testmodel/VTSBW=10/pack1"
    assert r0.original_rate_hz == pytest.approx(1000.0)
    assert r0.original_center_freq_hz == pytest.approx(2.45e9)
    assert r0.channel_id == "VTSBW=10"


def test_rfuav_load_iq_round_trips_and_checks_sample_count(tmp_path):
    _build_rfuav_mirror(tmp_path, n_samples=4)
    adapter = RfuavAdapter()
    recs = {r.recording_id: r for r in adapter.iter_recordings(tmp_path)}
    rec = recs["dji_testmodel/VTSBW=10/pack1_0-1s"]
    iq, rate_hz, centre_hz, bw_hz = adapter.load_iq(rec)
    assert iq.dtype == np.complex64
    assert iq.size == 4
    expected = np.array([0, 1, 2, 3], dtype=np.float32) + 1j * (
        np.array([0, 1, 2, 3], dtype=np.float32) * 0.5
    )
    np.testing.assert_allclose(iq, expected.astype(np.complex64))
    assert rate_hz == pytest.approx(1000.0)
    assert centre_hz == pytest.approx(2.45e9)
    assert bw_hz == pytest.approx(1000.0)

    # Corrupt sample_count so load_iq's own byte-count check must fire
    # rather than silently returning a truncated/misaligned array.
    import dataclasses
    bad_rec = dataclasses.replace(rec, extra={**rec.extra, "sample_count": 999})
    with pytest.raises(ValueError):
        adapter.load_iq(bad_rec)


@pytest.mark.parametrize(
    "folder_name,expected_model,expected_link_family",
    [
        ("DJI AVATA2", "avata_2", LinkFamily.OCUSYNC),
        ("DJI FPV COMBO", "fpv_combo", LinkFamily.OCUSYNC),
        ("DJI MAVIC3 PRO", "mavic_3_pro", LinkFamily.OCUSYNC),
        ("DJI MINI4 PRO", "mini_4_pro", LinkFamily.OCUSYNC),
    ],
)
def test_rfuav_labels_dji_mapping(folder_name, expected_model, expected_link_family):
    adapter = RfuavAdapter()
    rec = RecordingMeta(
        dataset_id="rfuav",
        recording_id="x",
        device_id="x",
        run_id="x",
        source_paths=(Path("/dev/null"),),
        original_rate_hz=1000.0,
        original_center_freq_hz=2.45e9,
        original_bw_hz=1000.0,
        original_dtype="float32_interleaved",
        extra={"folder_name": folder_name, "serial_number": "00001"},
    )
    labels = adapter.labels(rec)
    assert labels.scene.emitter_class == EmitterClass.DRONE_LINK
    assert labels.scene.manufacturer == "DJI"
    assert labels.scene.model == expected_model
    assert labels.scene.link_family == expected_link_family
    assert labels.scene.evidence_level == EvidenceLevel.OPERATOR_TRUTH
    assert labels.scene.label_source == LabelSource.DATASET_METADATA


def test_rfuav_labels_mini3_ambiguous_link_family_unknown():
    """'DJI MINI3' cannot be disambiguated between Mini 3 (non-Pro, DJI O2)
    and Mini 3 Pro (O3) from the archive name alone -- link_family must stay
    unknown rather than guessing either OcuSync generation."""

    adapter = RfuavAdapter()
    rec = RecordingMeta(
        dataset_id="rfuav",
        recording_id="x",
        device_id="x",
        run_id="x",
        source_paths=(Path("/dev/null"),),
        original_rate_hz=1000.0,
        original_center_freq_hz=2.45e9,
        original_bw_hz=1000.0,
        original_dtype="float32_interleaved",
        extra={"folder_name": "DJI MINI3", "serial_number": "00002"},
    )
    labels = adapter.labels(rec)
    assert labels.scene.emitter_class == EmitterClass.DRONE_LINK
    assert labels.scene.model == "mini_3"
    assert labels.scene.link_family == LinkFamily.UNKNOWN


def test_rfuav_labels_unmapped_folder_stays_unknown():
    """A folder not in `_RFUAV_DJI_LABELS` (e.g. one of the 32 non-DJI
    RC-transmitter archives, not yet verified) must never be defaulted to
    drone_link."""

    adapter = RfuavAdapter()
    rec = RecordingMeta(
        dataset_id="rfuav",
        recording_id="x",
        device_id="x",
        run_id="x",
        source_paths=(Path("/dev/null"),),
        original_rate_hz=1000.0,
        original_center_freq_hz=2.45e9,
        original_bw_hz=1000.0,
        original_dtype="float32_interleaved",
        extra={"folder_name": "FLYSKY EL18", "serial_number": "unknown"},
    )
    labels = adapter.labels(rec)
    assert labels.scene.emitter_class == EmitterClass.UNKNOWN
    assert labels.scene.evidence_level == EvidenceLevel.RF_CANDIDATE


def test_rfuav_prepare_dataset_synthetic(tmp_path):
    # sample_rate_hz=200_000.0 makes each 200_000-sample slice exactly 1.0 s
    # (one canonical window per recording); the default 1000.0 Hz used by
    # other synthetic tests would make this a 200 s recording (200 windows).
    _build_rfuav_mirror(tmp_path, n_samples=200_000, sample_rate_hz=200_000.0)
    adapter = RfuavAdapter()
    stats = prepare_dataset(
        "rfuav", adapter, root=tmp_path, limit=None, write_iq=False, write_tensor=True
    )
    assert stats.recordings == 2
    assert stats.windows == 2


# ---------------------------------------------------------------------------
# Real-mirror smoke: ~/rf-datasets/rfuav/original/extracted (skip if
# absent -- the DJI archives are large and extraction is a separate,
# detached step, see FORMAT.md).
# ---------------------------------------------------------------------------

_RFUAV_REAL_DIR = DATASET_ROOT / "rfuav" / "original" / "extracted"


@pytest.mark.skipif(not _RFUAV_REAL_DIR.is_dir(), reason="RFUAV extracted mirror not found under AERIX_RF_DATASET_ROOT")
def test_rfuav_adapter_real_mirror():
    from aerix_rf.datasets.adapters import ADAPTERS

    adapter = ADAPTERS["rfuav"]
    recs = list(adapter.iter_recordings(DATASET_ROOT))
    assert len(recs) >= 1

    rec = recs[0]
    iq, rate_hz, centre_hz, bw_hz = adapter.load_iq(rec)
    assert iq.dtype == np.complex64
    assert rate_hz == pytest.approx(100e6)
    assert centre_hz == pytest.approx(2.45e9)
    assert np.all(np.isfinite(iq))
    assert np.max(np.abs(iq)) > 0.0  # not a silent/all-zero capture

    labels = adapter.labels(rec)
    assert labels.scene.manufacturer == "DJI"


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
