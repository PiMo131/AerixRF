"""S1 dataset adapters (Workstream D, T4).

Implements stage S1 of ``docs/design/dataset-normalization.md`` for two real
local datasets: per-format decoder -> native complex baseband stream +
declared native metadata. No DSP beyond dtype conversion happens here (S2
resampling/mixing lives in :mod:`aerix_rf.datasets.resample`).

Each adapter implements the :class:`Adapter` protocol: ``iter_recordings``
(cheap metadata scan, no IQ), ``load_iq`` (memory-mapped, returns
``(complex64, in_rate_hz, centre_hz | None, in_bw_hz | None)``), and
``labels`` (fills a :class:`~aerix_rf.datasets.spec.LabelsGroup` using the
spec's bounded enums -- unknown axes get the ``unknown``/``not_applicable``
sentinel, never a guess).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Protocol

import numpy as np

from ..sdr.capture import _read_cs8, _read_cs16
from .spec import (
    Activity,
    EmitterClass,
    EvidenceLevel,
    LabelInstance,
    LabelSource,
    LabelsGroup,
    LinkFamily,
    LinkRole,
)


@dataclass(frozen=True)
class RecordingMeta:
    """One S1 recording as seen by an adapter: cheap metadata only, no IQ
    loaded yet. ``source_paths`` is a tuple (not a single path) so a
    multi-file logical recording -- e.g. Zenodo 2020's ``_1of2``/``_2of2``
    halves, which the normalisation memo's S1 section says to concatenate
    before S2 as one group, never as the source paper's joined spectrum --
    can still be described as one ``RecordingMeta``. ``original_center_freq_hz``
    / ``original_bw_hz`` are the adapter's best *declared* (possibly nominal)
    values, used by :mod:`aerix_rf.datasets.prepare` as a fallback whenever
    :meth:`Adapter.load_iq` cannot report a more precise per-file value.
    ``original_center_freq_hz`` is ``Optional`` because some sources (e.g.
    RUB-SysSec DroneSecurity) never publish a capture centre frequency at
    all -- ``None`` means genuinely unknown and must never be defaulted to
    a plausible-looking value; see ``RubDroneSecurityAdapter`` below."""

    dataset_id: str
    recording_id: str
    device_id: str
    run_id: str
    source_paths: tuple[Path, ...]
    original_rate_hz: float
    original_center_freq_hz: Optional[float]
    original_bw_hz: float
    original_dtype: str
    capture_group: Optional[str] = None
    channel_id: Optional[str] = None
    # Free-text provenance note carried through to `WindowSidecar.notes`
    # (e.g. explaining an `original_center_freq_hz=None`). `None` means no
    # note, not "unknown".
    notes: Optional[str] = None
    extra: dict = field(default_factory=dict)


class Adapter(Protocol):
    """S1 adapter protocol. Structural (no base class required)."""

    dataset_id: str

    def iter_recordings(self, root: Path) -> Iterator[RecordingMeta]:
        """Enumerate this dataset's recordings. ``root`` is the *global*
        dataset root (``AERIX_RF_DATASET_ROOT``, e.g. ``~/rf-datasets``), not
        a per-adapter subdirectory: each adapter's on-disk mirror directory
        name (e.g. ``RUB-DroneSecurity``, ``ZenodoDroneRFVideo2020``) does
        not match its ``dataset_id`` slug (``rub_dronesecurity``,
        ``zenodo_drone_rf_video_2020`` -- the slug used for
        ``prepared/index.jsonl`` output), so each adapter hardcodes its own
        mirror directory name internally. Cheap: no IQ materialised."""
        ...

    def load_iq(
        self, rec: RecordingMeta
    ) -> tuple[np.ndarray, float, Optional[float], Optional[float]]:
        """Load ``rec``'s IQ as complex64. Returns
        ``(iq, in_rate_hz, centre_hz, in_bw_hz)``; ``centre_hz``/``in_bw_hz``
        may be ``None`` when the adapter cannot report a value more precise
        than ``rec``'s own declared metadata."""
        ...

    def labels(self, rec: RecordingMeta) -> LabelsGroup:
        """This recording's ``scene``/``window`` labels (section 3 of the
        normalisation memo)."""
        ...


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_sha256(rec: RecordingMeta) -> str:
    """sha256 covering ``rec``'s original file(s) (S0 provenance).

    A single-file recording gets that file's own sha256. A multi-file
    recording (halves) gets sha256 of the ordered concatenation of each
    part's own sha256 hex digest -- a combined-provenance hash, not a hash
    of the raw concatenated bytes, so it stays cheap for multi-hundred-MB
    halves and does not require materialising the concatenation twice."""

    if len(rec.source_paths) == 1:
        return _sha256_file(rec.source_paths[0])
    h = hashlib.sha256()
    for p in rec.source_paths:
        h.update(_sha256_file(p).encode("ascii"))
    return h.hexdigest()


def source_file_field(rec: RecordingMeta) -> str:
    """``Identity.source_file`` value: the file name(s), ``+``-joined for a
    multi-file (halves) recording."""

    return "+".join(p.name for p in rec.source_paths)


# ---------------------------------------------------------------------------
# Zenodo 4264467 (2020) -- "Radio-Frequency Control and Video Signal
# Recordings of Drones". Flat `<Manufacturer>_<model tokens>_<band>
# [_control|_video][_<N>of<M>].bin`, interleaved int16 I/Q. Rate/centre per
# the record's own description (research/datasets/manifest.json
# zenodo_drone_rf_video_2020 entry, confirmed against api.zenodo.org and the
# record's example.py/load_bin.py, which this task re-verified locally):
# 120 MS/s @ nominal 2.44 GHz for "2G" files (1.0 s/file at 480e6 B),
# 200 MS/s @ nominal 5.8 GHz for "5G" files (0.5 s/file at 400e6 B for a
# single file, or two 400e6 B halves for a 1.0 s recording).
# ---------------------------------------------------------------------------

_ZENODO_BAND_CENTER_HZ = {"2G": 2.44e9, "5G": 5.8e9}
_ZENODO_BAND_RATE_HZ = {"2G": 120e6, "5G": 200e6}
_ZENODO_PART_RE = re.compile(r"^(\d+)of(\d+)$")
_ZENODO_BAND_RE = re.compile(r"^(\d+)G$")
_ZENODO_MODE_TOKENS = ("control", "video")


@dataclass(frozen=True)
class _ZenodoParsed:
    manufacturer: str
    model: str
    band_token: str
    mode: Optional[str]
    part: Optional[tuple[int, int]]


def parse_zenodo_stem(stem: str) -> _ZenodoParsed:
    """Parse one Zenodo 2020 ``.bin`` filename stem (no extension) into its
    manufacturer/model/band/mode/part components. Raises ``ValueError`` on
    an unrecognised stem rather than guessing."""

    tokens = stem.split("_")
    if len(tokens) < 3:
        raise ValueError(f"cannot parse Zenodo filename stem: {stem!r}")
    manufacturer = tokens[0]
    part: Optional[tuple[int, int]] = None
    m = _ZENODO_PART_RE.match(tokens[-1])
    if m:
        part = (int(m.group(1)), int(m.group(2)))
        tokens = tokens[:-1]
    if not _ZENODO_BAND_RE.match(tokens[-1]):
        raise ValueError(f"no band token (e.g. '2G'/'5G') in Zenodo filename stem: {stem!r}")
    band_token = tokens[-1]
    model_tokens = tokens[1:-1]
    mode: Optional[str] = None
    if model_tokens and model_tokens[-1] in _ZENODO_MODE_TOKENS:
        mode = model_tokens[-1]
        model_tokens = model_tokens[:-1]
    if not model_tokens:
        raise ValueError(f"no model tokens in Zenodo filename stem: {stem!r}")
    return _ZenodoParsed(
        manufacturer=manufacturer,
        model="_".join(model_tokens).lower(),
        band_token=band_token,
        mode=mode,
        part=part,
    )


class ZenodoDroneRF2020Adapter:
    dataset_id = "zenodo_drone_rf_video_2020"
    # On-disk mirror directory name (differs from dataset_id -- see Adapter
    # protocol docstring).
    mirror_dir_name = "ZenodoDroneRFVideo2020"

    def iter_recordings(self, root: Path) -> Iterator[RecordingMeta]:
        base = root / self.mirror_dir_name / "original"
        groups: dict[tuple, list[tuple[int, Path]]] = {}
        parsed_by_key: dict[tuple, _ZenodoParsed] = {}
        for path in sorted(base.glob("*.bin")):
            if path.with_name(path.name + ".aria2").exists():
                continue  # incomplete download: refused per the normalisation memo S1 rule
            parsed = parse_zenodo_stem(path.stem)
            key = (parsed.manufacturer, parsed.model, parsed.band_token, parsed.mode)
            part_index = parsed.part[0] if parsed.part else 1
            groups.setdefault(key, []).append((part_index, path))
            parsed_by_key[key] = parsed

        # Single-file recordings first (cheap, deterministic real-run smoke
        # ordering), then multi-part (halves) recordings, both alphabetical
        # within each tier.
        def _sort_key(key: tuple) -> tuple:
            return (len(groups[key]) > 1, key)

        for key in sorted(groups, key=_sort_key):
            manufacturer, model, band_token, mode = key
            parts = sorted(groups[key], key=lambda t: t[0])
            paths = tuple(p for _, p in parts)
            recording_id = "_".join([manufacturer, model, band_token] + ([mode] if mode else []))
            yield RecordingMeta(
                dataset_id=self.dataset_id,
                recording_id=recording_id,
                device_id=f"{manufacturer}_{model}",
                run_id=recording_id,
                source_paths=paths,
                original_rate_hz=_ZENODO_BAND_RATE_HZ[band_token],
                original_center_freq_hz=_ZENODO_BAND_CENTER_HZ[band_token],
                # Analog/declared capture bandwidth is not documented locally
                # beyond "captured band == sample rate"; usable_bandwidth()
                # caps this at USABLE_BW_HZ regardless.
                original_bw_hz=_ZENODO_BAND_RATE_HZ[band_token],
                original_dtype="int16_interleaved",
                capture_group=recording_id if len(paths) > 1 else None,
                channel_id=band_token,
                extra={"manufacturer": manufacturer, "model": model, "mode": mode},
            )

    def load_iq(
        self, rec: RecordingMeta
    ) -> tuple[np.ndarray, float, Optional[float], Optional[float]]:
        arrays = [np.memmap(p, dtype="<i2", mode="r") for p in rec.source_paths]
        interleaved = arrays[0] if len(arrays) == 1 else np.concatenate(arrays)
        scaled = interleaved.astype(np.float32) / 32768.0  # int16 full-scale
        iq = scaled.view(np.complex64)
        return iq, rec.original_rate_hz, None, None

    def labels(self, rec: RecordingMeta) -> LabelsGroup:
        manufacturer = rec.extra["manufacturer"]
        model = rec.extra["model"]
        mode = rec.extra.get("mode")
        link_role = {
            "control": LinkRole.UPLINK_CONTROL,
            "video": LinkRole.DOWNLINK_VIDEO,
        }.get(mode, LinkRole.UNKNOWN)
        # link_family is deliberately left UNKNOWN: the normalisation memo's
        # per-dataset support table lists Zenodo's link_family as "per
        # model" with no explicit model->family table given (unlike DroneRF,
        # where the memo explicitly corrects the Phantom 3 mislabel). Rather
        # than guess OcuSync vs Lightbridge vs Wi-Fi per model, this is left
        # unknown pending a `[RESEARCH]` pass -- see handback report.
        scene = LabelInstance(
            emitter_class=EmitterClass.DRONE_LINK,
            link_family=LinkFamily.UNKNOWN,
            link_role=link_role,
            manufacturer=manufacturer,
            model=model,
            individual_id="unknown",
            activity=Activity.UNKNOWN,
            evidence_level=EvidenceLevel.OPERATOR_TRUTH,
            label_source=LabelSource.FILENAME_DERIVED,
        )
        window = scene.model_copy(
            update={"evidence_level": EvidenceLevel.PROBABILISTIC_CLASSIFICATION}
        )
        return LabelsGroup(scene=scene, window=window)


# ---------------------------------------------------------------------------
# RUB-SysSec DroneSecurity -- two pre-segmented DJI DroneID candidate-burst
# slices, interleaved float32 I/Q, 50 MS/s (see
# ~/rf-datasets/RUB-DroneSecurity/original/SOURCE.md and
# tests/test_droneid_rub_golden.py, both already-verified local records).
# ---------------------------------------------------------------------------

_RUB_RATE_HZ = 50e6
# The RUB-SysSec repo does NOT record the per-file capture centre frequency
# for mavic_air_2/mini2_sm: the live receiver hops a candidate-centre list
# (see research/briefs/droneid-channel-raster.md) rather than logging the
# frequency actually used for these pre-segmented offline samples, so no
# real value is known -- not even "which of the ~7 candidate 2.4 GHz
# centres". `RecordingMeta.original_center_freq_hz` and the WindowSidecar
# fields it feeds (`signal.center_freq_hz` / `source.original_center_freq_hz`)
# are `Optional[float]` precisely for this case: this adapter reports `None`
# rather than a sentinel or a fabricated-but-plausible ISM-band guess, and
# `WindowSidecar.notes` records why.
_RUB_UNKNOWN_CENTER_NOTE = (
    "capture centre frequency not published by RUB-SysSec; see "
    "research/briefs/droneid-channel-raster.md"
)
_RUB_MODEL_BY_FILE = {
    "mavic_air_2": "mavic_air_2",
    "mini2_sm": "mini_2",
}


class RubDroneSecurityAdapter:
    dataset_id = "rub_dronesecurity"
    # On-disk mirror directory name (differs from dataset_id -- see Adapter
    # protocol docstring).
    mirror_dir_name = "RUB-DroneSecurity"

    def iter_recordings(self, root: Path) -> Iterator[RecordingMeta]:
        base = root / self.mirror_dir_name / "original" / "samples"
        for name in sorted(_RUB_MODEL_BY_FILE):
            path = base / name
            if not path.exists():
                continue
            yield RecordingMeta(
                dataset_id=self.dataset_id,
                recording_id=name,
                device_id=_RUB_MODEL_BY_FILE[name],
                run_id=name,
                source_paths=(path,),
                original_rate_hz=_RUB_RATE_HZ,
                original_center_freq_hz=None,
                original_bw_hz=_RUB_RATE_HZ,
                original_dtype="float32_interleaved",
                notes=_RUB_UNKNOWN_CENTER_NOTE,
                extra={"model": _RUB_MODEL_BY_FILE[name]},
            )

    def load_iq(
        self, rec: RecordingMeta
    ) -> tuple[np.ndarray, float, Optional[float], Optional[float]]:
        raw = np.memmap(rec.source_paths[0], dtype="<f4", mode="r")
        iq = np.asarray(raw).view(np.complex64)
        return iq, _RUB_RATE_HZ, None, None

    def labels(self, rec: RecordingMeta) -> LabelsGroup:
        model = rec.extra["model"]
        # Highest evidence level the taxonomy allows for a decoded (not
        # operator-witnessed) label: EvidenceLevel.VALIDATED_DECODE (4), not
        # OPERATOR_TRUTH (5) -- these are protocol-CRC-validated DroneID
        # decodes (tests/test_droneid_rub_golden.py: decode_all(...) with
        # level == "C" and crc_ok True for both samples), not an operator's
        # own field observation.
        scene = LabelInstance(
            emitter_class=EmitterClass.DRONE_LINK,
            link_family=LinkFamily.OCUSYNC,
            link_role=LinkRole.BROADCAST_DRONEID,
            manufacturer="DJI",
            model=model,
            individual_id="unknown",
            # Flight state (flying/idle/etc.) is not documented for these
            # samples -- mini2_sm had no GPS lock and neither the repo nor
            # its README states an activity/flight state for either
            # sample -- so this stays Activity.UNKNOWN rather than
            # assuming "flying" from context.
            activity=Activity.UNKNOWN,
            evidence_level=EvidenceLevel.VALIDATED_DECODE,
            label_source=LabelSource.PROTOCOL_DECODE,
        )
        return LabelsGroup(scene=scene, window=scene)


# ---------------------------------------------------------------------------
# AERIX's own recorded sessions (Workstream D, T5) -- `aerix_rf.session.store
# .Session` output directories (ANTSDR cs16 @ 12.288 MS/s, HackRF cs8 @
# 20 MS/s, and any future receiver written by the same session format).
# session.json schema v2 fields are read with the same optional-key fallback
# rules `aerix_rf.sdr.capture.FileIQSource` already applies (schema-1
# sessions -- no `iq_format`/`iq_full_scale`/`bandwidth_hz`/`channel_id`/
# `timing` keys -- replay/normalise identically to schema-2 ones): iq_format
# absent -> cs8; cs8 full scale absent -> 128.0; cs16 full scale is REQUIRED
# (no default -- see capture.py), so a cs16 file with none recorded raises at
# `load_iq()` time via `_read_cs16` itself rather than being silently guessed.
# ---------------------------------------------------------------------------

_AERIX_BACKGROUND_KEYWORDS = ("ambient", "baseline", "smoke", "soak", "probe")


class AerixSessionAdapter:
    """S1 adapter for one AERIX field-session batch directory (this project's
    own recordings, not a third-party dataset).

    One :class:`RecordingMeta` per IQ file (= one 1.0 s window at *that
    file's own* recorded rate, ``files[i]['sample_rate']`` -- NOT
    necessarily the session's top-level ``sample_rate``, which for the
    ANTSDR backend is the pre-decimation IIO/ADC rate, not the stream rate
    actually written to disk). ``recording_id`` is ``<session_id>/<file>``
    and ``run_id`` is the bare ``session_id`` so every window of one session
    shares one split group (never split across train/val/test).

    A session directory's ``replays/<...>/session.json`` (a replay of an
    already-captured session, not a new original capture) is never picked
    up: :meth:`iter_recordings` globs exactly one directory level below
    ``original/``, so nested replay sessions are excluded by construction,
    not by an explicit filter.

    Label semantics: ``emitter_class`` comes from the session's own
    operator-authored ``test`` block ONLY -- never from ``detections.jsonl``/
    ``decode.jsonl`` (this adapter never reads those files at all). A
    ``drone_manufacturer``/``drone_model`` present in ``test`` is the
    strongest signal (operator flew a real aircraft during the capture); a
    session whose own label/``test_label`` names it as one of AERIX's
    routine no-drone test kinds (ambient/baseline/smoke/soak/probe) with no
    drone fields is ``background`` at the same operator-truth evidence
    level -- the operator's own choice of session name is how this
    project's field-test protocol records "no aircraft was present", the
    same kind of authored ground truth as a filled-in ``test`` block, not a
    filename-derived guess. Anything else (an un-suffixed/ambiguous session
    name, no drone fields) stays ``unknown`` at the lowest evidence level --
    never inferred from what a detector/decoder happened to find.
    """

    def __init__(self, dataset_id: str, mirror_dir_name: Optional[str] = None) -> None:
        self.dataset_id = dataset_id
        self.mirror_dir_name = mirror_dir_name or dataset_id

    def iter_recordings(self, root: Path) -> Iterator[RecordingMeta]:
        base = root / self.mirror_dir_name / "original"
        for session_json in sorted(base.glob("*/session.json")):
            session_dir = session_json.parent
            try:
                meta = json.loads(session_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue  # torn/unreadable session.json: skip, don't fail the whole scan
            yield from self._recordings_for_session(session_dir, meta)

    def _recordings_for_session(self, session_dir: Path, meta: dict) -> Iterator[RecordingMeta]:
        session_id = str(meta.get("session_id") or session_dir.name)
        session_receiver_type = meta.get("receiver_type")
        session_receiver_serial = meta.get("receiver_serial")
        session_receiver_backend = meta.get("receiver_backend")
        receiver_type = str(session_receiver_type or "unknown")
        session_bw_hz = meta.get("bandwidth_hz")
        session_iq_format = meta.get("iq_format")
        session_iq_full_scale = meta.get("iq_full_scale")
        session_center_hz = meta.get("center_freq_hz")
        test_block = dict(meta.get("test") or {})
        session_label = str(meta.get("label") or test_block.get("test_label") or "")

        receiver_extra = {
            "type": receiver_type,
            "backend": session_receiver_backend,
            "firmware": meta.get("receiver_firmware"),
            "gain_mode": meta.get("gain_mode"),
            "gain_db": (meta.get("gains") or {}).get("gain_db"),
            "clock": "host_wallclock",
        }

        for entry in meta.get("files") or []:
            rel = entry.get("file")
            if not rel:
                continue
            path = session_dir / rel
            if not path.exists():
                continue  # a listed file that never landed on disk (crash/partial session)

            file_receiver_type = str(
                entry.get("receiver_type") or session_receiver_type or "unknown"
            )
            file_receiver_serial = entry.get("receiver_serial")
            if file_receiver_serial is None:
                file_receiver_serial = session_receiver_serial
            file_receiver_backend = entry.get("receiver_backend")
            if file_receiver_backend is None:
                file_receiver_backend = session_receiver_backend
            device_id = (
                f"{file_receiver_type}_{file_receiver_serial or file_receiver_backend or 'unknown'}"
            )

            in_rate_hz = entry.get("sample_rate")
            in_rate_hz = float(in_rate_hz if in_rate_hz is not None else meta.get("sample_rate"))

            centre_hz = entry.get("center_freq_hz")
            centre_hz = centre_hz if centre_hz is not None else session_center_hz
            centre_hz = float(centre_hz) if centre_hz is not None else None

            bw_hz = entry.get("bandwidth_hz")
            bw_hz = bw_hz if bw_hz is not None else session_bw_hz
            bw_hz = float(bw_hz) if bw_hz is not None else in_rate_hz

            iq_format = str(entry.get("iq_format") or session_iq_format or "cs8")
            if iq_format == "cs8":
                fs = entry.get("iq_full_scale")
                fs = fs if fs is not None else session_iq_full_scale
                iq_full_scale = float(fs) if fs is not None else 128.0
            else:
                fs = entry.get("iq_full_scale")
                fs = fs if fs is not None else session_iq_full_scale
                iq_full_scale = float(fs) if fs is not None else None  # required by _read_cs16;
                # deliberately no default -- see the module docstring above.

            sample_count = entry.get("sample_count")
            if sample_count is None:
                sample_count = int(round(float(entry.get("duration_s", 1.0)) * in_rate_hz))
            sample_count = int(sample_count)

            capture_health = entry.get("capture_health") or {}
            note_parts = [f"{iq_format} session"]
            if iq_format == "cs8":
                note_parts.append("not native 12-bit (cs16)")
            ratio = capture_health.get("stream_rate_ratio")
            if ratio is not None:
                note_parts.append(f"stream_rate_ratio={ratio}")
            if capture_health.get("rate_warning"):
                note_parts.append("rate_warning=True")

            channel_id = entry.get("channel_id")

            yield RecordingMeta(
                dataset_id=self.dataset_id,
                recording_id=f"{session_id}/{rel}",
                device_id=device_id,
                run_id=session_id,
                source_paths=(path,),
                original_rate_hz=in_rate_hz,
                original_center_freq_hz=centre_hz,
                original_bw_hz=bw_hz,
                original_dtype=iq_format,
                channel_id=(str(channel_id) if channel_id is not None else None),
                notes="; ".join(note_parts),
                extra={
                    "sample_count": sample_count,
                    "iq_full_scale": iq_full_scale,
                    "iq_full_scale_source": "session_metadata",
                    "test": test_block,
                    "session_label": session_label,
                    "receiver": receiver_extra,
                },
            )

    def load_iq(
        self, rec: RecordingMeta
    ) -> tuple[np.ndarray, float, Optional[float], Optional[float]]:
        path = str(rec.source_paths[0])
        n = int(rec.extra["sample_count"])
        if rec.original_dtype == "cs8":
            iq = _read_cs8(path, 0, n)
        elif rec.original_dtype == "cs16":
            iq = _read_cs16(path, 0, n, full_scale=rec.extra.get("iq_full_scale"))
        else:
            raise ValueError(
                f"AerixSessionAdapter: unsupported iq_format {rec.original_dtype!r} "
                f"for {rec.recording_id!r} (expected 'cs8' or 'cs16')"
            )
        return iq, rec.original_rate_hz, None, None

    def labels(self, rec: RecordingMeta) -> LabelsGroup:
        test_block: dict[str, Any] = rec.extra.get("test") or {}
        manufacturer = test_block.get("drone_manufacturer")
        model = test_block.get("drone_model")
        label_text = str(rec.extra.get("session_label") or "").lower()

        if manufacturer or model:
            inst = LabelInstance(
                emitter_class=EmitterClass.DRONE_LINK,
                link_family=LinkFamily.UNKNOWN,
                link_role=LinkRole.UNKNOWN,
                manufacturer=manufacturer or "unknown",
                model=model or "unknown",
                individual_id=test_block.get("drone_serial") or "unknown",
                # Flight state (test_block['drone_state']) is not mapped onto
                # Activity here -- no session in the current corpus exercises
                # it and the free-text values AERIX's own test protocol uses
                # are not yet audited against the Activity enum's members;
                # left UNKNOWN rather than guessed.
                activity=Activity.UNKNOWN,
                evidence_level=EvidenceLevel.OPERATOR_TRUTH,
                label_source=LabelSource.OPERATOR_GROUND_TRUTH,
            )
        elif any(kw in label_text for kw in _AERIX_BACKGROUND_KEYWORDS):
            inst = LabelInstance(
                emitter_class=EmitterClass.BACKGROUND,
                link_family=LinkFamily.NOT_APPLICABLE,
                link_role=LinkRole.NOT_APPLICABLE,
                activity=Activity.UNKNOWN,
                evidence_level=EvidenceLevel.OPERATOR_TRUTH,
                label_source=LabelSource.OPERATOR_GROUND_TRUTH,
            )
        else:
            # Never inferred from detections.jsonl/decode.jsonl: an
            # unlabelled/ambiguous session name with no drone fields is
            # genuinely unknown, not assumed background.
            inst = LabelInstance(
                emitter_class=EmitterClass.UNKNOWN,
                link_family=LinkFamily.UNKNOWN,
                link_role=LinkRole.UNKNOWN,
                activity=Activity.UNKNOWN,
                evidence_level=EvidenceLevel.RF_CANDIDATE,
                label_source=LabelSource.UNKNOWN,
            )
        return LabelsGroup(scene=inst, window=inst)


ADAPTERS: dict[str, Adapter] = {
    ZenodoDroneRF2020Adapter.dataset_id: ZenodoDroneRF2020Adapter(),
    RubDroneSecurityAdapter.dataset_id: RubDroneSecurityAdapter(),
    "aerix_antsdr_ambient_2026_09_18": AerixSessionAdapter(
        dataset_id="aerix_antsdr_ambient_2026_09_18"
    ),
}
