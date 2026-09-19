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

    Label semantics: when an ``annotations.json`` (``aerix-rf annotate``,
    ``docs/field/positives-protocol.md``) exists next to the session, its
    per-window operator-timeline label always wins, and each annotated
    interval becomes its own ``run_id`` split group
    (``<session_id>/<interval_id>``). Otherwise ``emitter_class`` comes from
    the session's own operator-authored ``test`` block ONLY -- never from
    ``detections.jsonl``/``decode.jsonl`` (this adapter never reads those
    files at all). A
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
            annotations = self._load_annotations(session_dir)
            yield from self._recordings_for_session(session_dir, meta, annotations)

    @staticmethod
    def _load_annotations(session_dir: Path) -> Optional[dict]:
        """Loads ``annotations.json`` (written by ``aerix-rf annotate``, see
        ``aerix_rf.annotate`` and ``docs/field/positives-protocol.md``) next
        to this session, if present. A torn/unreadable file is treated the
        same as absent (falls back to the ``test``-block heuristics below)
        rather than failing the whole scan."""
        path = session_dir / "annotations.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _recordings_for_session(
        self, session_dir: Path, meta: dict, annotations: Optional[dict] = None
    ) -> Iterator[RecordingMeta]:
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
        # Session-level READ-BACK device state, when the backend records
        # one (not yet emitted by any session in the current corpus --
        # forward-compatible key, see docs/design/features-and-benchmark.md
        # S5#1). A per-file `receiver_readback` (checked below) wins over
        # this session-level one when both are present.
        session_readback = meta.get("receiver_readback")

        # Cumulative (expected, received) sample totals across this
        # session's files, in `files[]` order, used to compute
        # `session_deficit_frac` as-of each file -- see the per-file loop
        # below. Only files with a `capture_health` that carries explicit
        # `expected_samples` + (`received_samples` or
        # `dropped_or_missing_samples`) contribute; a legacy session whose
        # only capture-health signal is a noisy per-window
        # `stream_rate_ratio` never contributes here, and
        # `session_deficit_frac` stays `None` for every one of its windows.
        cum_expected = 0
        cum_received = 0
        cum_any = False

        # index -> this file's `annotations.json` window entry (operator
        # timeline truth), when an annotation file exists for this session.
        # Matched by `files[]` array position, the same index `aerix-rf
        # annotate` itself enumerates from before sorting its own output by
        # `captured_at` -- see `aerix_rf.annotate.annotate_session`.
        annotation_by_index: dict[int, dict] = {}
        if annotations is not None:
            for w in annotations.get("windows") or []:
                idx = w.get("index")
                if idx is not None:
                    annotation_by_index[int(idx)] = w

        for file_index, entry in enumerate(meta.get("files") or []):
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
            # `rate_warning=...` is deliberately no longer added here: it is
            # now the typed `signal.window_deficit_frac` /
            # `signal.capture_complete` sidecar fields below, not a free-text
            # note (docs/design/features-and-benchmark.md S5#5).

            channel_id = entry.get("channel_id")

            # window_deficit_frac: this file's own (expected - delivered) /
            # expected sample fraction. `None` when the file's
            # capture_health does not carry explicit expected/received
            # counts (old sessions only logged a noisy per-window
            # `stream_rate_ratio` -- never treated as a deficit fraction).
            expected = capture_health.get("expected_samples")
            received = capture_health.get("received_samples")
            if received is None and capture_health.get("dropped_or_missing_samples") is not None:
                if expected is not None:
                    received = expected - capture_health["dropped_or_missing_samples"]
            window_deficit_frac: Optional[float] = None
            if expected is not None and received is not None and expected > 0:
                window_deficit_frac = (expected - received) / expected
                cum_expected += expected
                cum_received += received
                cum_any = True

            # session_deficit_frac: same ratio, cumulative over this
            # session's files up to and including this one. Stays `None`
            # until at least one file with usable expected/received counts
            # has been seen; a purely legacy session (no file ever carries
            # them) leaves this `None` for every window rather than
            # deriving a number from the noisy per-window ratio.
            session_deficit_frac: Optional[float] = None
            if cum_any and cum_expected > 0:
                session_deficit_frac = (cum_expected - cum_received) / cum_expected

            capture_complete = capture_health.get("capture_complete")
            if capture_complete is not None:
                capture_complete = bool(capture_complete)

            file_readback = entry.get("receiver_readback")
            readback = file_readback if file_readback is not None else session_readback

            file_receiver_extra = dict(receiver_extra)
            file_receiver_extra["rf_bandwidth_hz"] = bw_hz
            file_receiver_extra["readback"] = readback

            # An `aerix-rf annotate` pass is operator-truth ground truth
            # (evidence level 5) for this specific window and always wins
            # over the `test`-block heuristics in `labels()` below. Each
            # annotated interval is also its own split group -- windows from
            # different intervals of the same session (e.g. `off-baseline`
            # vs `on-near`) must never share a `run_id`, or a group-level
            # train/val/test splitter could put a background window and its
            # paired positive window in the same split by construction.
            annotation_window = annotation_by_index.get(file_index)
            run_id = session_id
            if annotation_window is not None:
                run_id = f"{session_id}/{annotation_window['interval_id']}"

            yield RecordingMeta(
                dataset_id=self.dataset_id,
                recording_id=f"{session_id}/{rel}",
                device_id=device_id,
                run_id=run_id,
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
                    "receiver": file_receiver_extra,
                    "health": {
                        "window_deficit_frac": window_deficit_frac,
                        "session_deficit_frac": session_deficit_frac,
                        "capture_complete": capture_complete,
                    },
                    "annotation": annotation_window,
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
        annotation_window = rec.extra.get("annotation")
        if annotation_window is not None:
            # Operator timeline truth (`aerix-rf annotate`, evidence level 5)
            # always wins over the `test`-block heuristics below -- see
            # docs/field/positives-protocol.md and aerix_rf.annotate.
            inst = LabelInstance(**annotation_window["label"])
            return LabelsGroup(scene=inst, window=inst)

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


# ---------------------------------------------------------------------------
# RFUAV (this project's local mirror, ~/rf-datasets/rfuav/original) -- one
# .rar per drone/RC-transmitter model. Extracted layout (re-verified
# 2026-09-19 against DJI_MINI4_PRO.rar, DJI_AVATA2.rar, FLYSKY_FS_I6X.rar,
# FRSKY_X20R.rar and FUTABA_T14SG.rar -- see
# ~/rf-datasets/rfuav/original/FORMAT.md for the full evidence trail):
#
#   extracted/<ARCHIVE_NAME>/<Drone Name>/[VTSBW=<N>/]pack<K>.xml
#                                          [VTSBW=<N>/]pack<K>_<a>-<b>s.iq
#
# The "<Drone Name>" nesting level (matching the XML's own <Drone> field, but
# read from the *folder* name -- some archives' <Drone> XML text has a
# manufacturer typo, e.g. FRSKY_X20R's pack1.xml says
# "<Drone>FLYSKY X20R</Drone>", so the folder name is the reliable key, not
# the XML text) is present for EVERY archive, DJI and non-DJI alike. Only
# the DJI (and Autel) airframe archives add a further "VTSBW=<N>/" level
# (one pack per video-transmission bandwidth setting); the 31 RC-transmitter
# archives have no such concept and put pack<K>.xml/.iq directly under
# "<Drone Name>/". A prior version of this adapter only globbed
# "<top-level dir>/VTSBW=*/pack*.xml" one level deep, so it silently missed
# this "<Drone Name>/" nesting entirely for every real per-archive
# extraction and only ever saw a single stray duplicate manual extraction
# (a leftover "extracted/DJI MINI4 PRO/" directory with no matching
# "DJI MINI4 PRO.rar" archive, one nesting level shallower than the other 36)
# -- see FORMAT.md's "Duplicate/stray directory" section. `iter_recordings`
# below instead recurses for `pack*.xml` under each archive-name directory
# and infers the `<Drone Name>` folder relative to wherever the xml actually
# sits, so it is agnostic to how many levels of nesting a given archive has.
#
# Every archive's pack<K>.xml -- RC-transmitter ones included -- carries the
# same SignalHound-style fields read here (never a hardcoded constant):
# DataType="Complex Float", SampleRate, CenterFrequency, IFBandwidth,
# SampleCount. The earlier belief that the 32 non-DJI archives ship with "no
# XML metadata" was wrong -- they have it, just one directory level
# shallower (no VTSBW=<N> grouping). Centre frequency is therefore always
# known per-pack from the XML, not synthesized/guessed: e.g. FLYSKY_FS_I6X
# and FRSKY_X20R both declare CenterFrequency=2440000000.000 (2.44 GHz,
# 2.4 GHz ISM), matching their RC-uplink function; DJI_AVATA2's VTSBW=40 pack
# declares 5760000000.000 (5.76 GHz), its 5.8 GHz video-downlink band.
#
# .iq byte-count / dtype check (FORMAT.md): every file checked this pass
# (DJI_MINI4_PRO, DJI_AVATA2, FLYSKY_FS_I6X, FRSKY_X20R, FUTABA_T14SG) is
# exactly SampleCount * 8 bytes with zero header bytes -- confirmed complex64
# (float32 I + float32 Q interleaved) by exact byte-count match for every
# model checked, not assumed from the "Complex Float" string alone or from
# the DJI archives only.
# ---------------------------------------------------------------------------

import logging
import xml.etree.ElementTree as ET

_rfuav_logger = logging.getLogger(__name__ + ".rfuav")

_RFUAV_IQ_STEM_RE = re.compile(r"^pack(\d+)_(\d+)-(\d+)s$")


@dataclass(frozen=True)
class _RfuavPackMeta:
    drone: str
    sample_rate_hz: float
    center_freq_hz: float
    if_bandwidth_hz: float
    sample_count: int
    scale_factor: Optional[float]
    reference_snr_level: Optional[float]
    serial_number: Optional[str]
    note: Optional[str]


def parse_rfuav_pack_xml(path: Path) -> _RfuavPackMeta:
    """Parse one RFUAV ``pack<K>.xml`` (SignalHound-style capture metadata,
    see FORMAT.md). Raises on a missing required field rather than
    defaulting -- an RFUAV archive whose XML omits ``SampleRate``/
    ``CenterFrequency``/``IFBandwidth``/``SampleCount`` must fail loudly,
    never fall back to the DJI_MINI4_PRO constants documented above (those
    are this pack's own declared values, not a dataset-wide default)."""

    root_el = ET.parse(path).getroot()

    def _text(tag: str) -> Optional[str]:
        el = root_el.find(tag)
        return el.text.strip() if el is not None and el.text else None

    data_type = _text("DataType")
    note: Optional[str] = None
    if data_type != "Complex Float":
        note = (
            f"unexpected <DataType>{data_type!r}</DataType> in {path.name}; "
            "this adapter assumes complex64 (verified only for 'Complex "
            "Float') -- VERIFY before trusting this recording's IQ"
        )
    scale_factor_text = _text("ScaleFactor")
    ref_snr_text = _text("ReferenceSNRLevel")
    return _RfuavPackMeta(
        drone=_text("Drone") or "unknown",
        sample_rate_hz=float(_text("SampleRate")),
        center_freq_hz=float(_text("CenterFrequency")),
        if_bandwidth_hz=float(_text("IFBandwidth")),
        sample_count=int(_text("SampleCount")),
        scale_factor=float(scale_factor_text) if scale_factor_text else None,
        reference_snr_level=float(ref_snr_text) if ref_snr_text else None,
        serial_number=_text("SerialNumber"),
        note=note,
    )


@dataclass(frozen=True)
class _RfuavLabel:
    manufacturer: str
    model: str
    link_family: LinkFamily
    note: Optional[str] = None
    # UNKNOWN for the DJI/Autel airframe tables below (an aircraft's own
    # capture is not asserted uplink vs downlink from the archive name
    # alone -- see the existing DJI VTSBW comment); UPLINK_CONTROL for the
    # RC-transmitter-only table, where the recording is, by MODELS.md
    # category, definitionally a bare control-uplink capture with no
    # airframe present.
    link_role: LinkRole = LinkRole.UNKNOWN


# manufacturer/model/link_family per extracted top-level folder name (== the
# archive's own <Drone> XML field), for the 5 complete DJI archives this
# task covers. link_family per
# research/briefs/dji-generations-and-o3o4-identification.md's generation
# table: Avata 2 and Mini 4 Pro are O4, Mavic 3 Pro and DJI FPV are
# O3/O3+ -- all OcuSync-family generations, hence LinkFamily.OCUSYNC for all
# four. "DJI MINI3" is deliberately left LinkFamily.UNKNOWN: the archive/XML
# name does not disambiguate "Mini 3" (non-Pro -- that brief's A-FIELD row
# calls this DJI O2) from "Mini 3 Pro" (O3); both readings are still
# OcuSync, but which specific aircraft/generation the archive holds is
# unresolved without RFUAV's own paper/README (not consulted this pass), so
# this stays UNKNOWN with a note rather than asserting OCUSYNC on an
# unresolved model reading.
_RFUAV_MINI3_NOTE = (
    "RFUAV archive/XML name 'DJI MINI3' does not disambiguate Mini 3 "
    "(non-Pro, DJI O2 per dji-generations-and-o3o4-identification.md's "
    "A-FIELD row) from Mini 3 Pro (O3); link_family left unknown pending "
    "RFUAV paper/README confirmation."
)
_RFUAV_DJI_LABELS: dict[str, _RfuavLabel] = {
    "DJI AVATA2": _RfuavLabel("DJI", "avata_2", LinkFamily.OCUSYNC),
    "DJI AVATA 2": _RfuavLabel("DJI", "avata_2", LinkFamily.OCUSYNC),
    "DJI FPV COMBO": _RfuavLabel("DJI", "fpv_combo", LinkFamily.OCUSYNC),
    "DJI FPV": _RfuavLabel("DJI", "fpv_combo", LinkFamily.OCUSYNC),
    "DJI MAVIC3 PRO": _RfuavLabel("DJI", "mavic_3_pro", LinkFamily.OCUSYNC),
    "DJI MAVIC 3 PRO": _RfuavLabel("DJI", "mavic_3_pro", LinkFamily.OCUSYNC),
    "DJI MINI4 PRO": _RfuavLabel("DJI", "mini_4_pro", LinkFamily.OCUSYNC),
    "DJI MINI 4 PRO": _RfuavLabel("DJI", "mini_4_pro", LinkFamily.OCUSYNC),
    "DJI MINI3": _RfuavLabel("DJI", "mini_3", LinkFamily.UNKNOWN, note=_RFUAV_MINI3_NOTE),
    "DJI MINI 3": _RfuavLabel("DJI", "mini_3", LinkFamily.UNKNOWN, note=_RFUAV_MINI3_NOTE),
}

# Non-DJI drone airframe (1 archive, MODELS.md "Non-DJI drone airframe"
# section): a full aircraft capture, same treatment as the DJI table above
# (link_role left unknown, not asserted uplink_control), not the
# RC-transmitter-only table below.
_RFUAV_AUTEL_SKYLINK_NOTE = (
    "Autel SkyLink is a proprietary adaptive-hopping link across "
    "2.4/5.8/5.2 GHz (MODELS.md, Medium evidence: Autel FAQ/product pages "
    "confirm the tri-band hopping scheme, no public PHY spec found); no "
    "LinkFamily enum member exists for SkyLink, so this stays unknown "
    "rather than asserted into an unrelated bucket (e.g. ocusync). Archive "
    "filename 'DAUTEL' is a naming artifact for Autel Robotics, not a real "
    "brand (MODELS.md)."
)
_RFUAV_AIRFRAME_LABELS: dict[str, _RfuavLabel] = {
    "DAUTEL EVO NANO": _RfuavLabel(
        "Autel Robotics", "evo_nano", LinkFamily.UNKNOWN, note=_RFUAV_AUTEL_SKYLINK_NOTE
    ),
}

# RC-transmitter-only recordings (31 archives, MODELS.md "RC-transmitter-only
# recordings" section): a bare control-uplink capture, no airframe present.
# `link_family` is only asserted (LinkFamily.FHSS_RC -- the taxonomy's one
# generic FHSS-RC bucket; there is no per-named-protocol enum member for
# ACCESS/AFHDS2A/AFHDS3/FASST/T-FHSS specifically) for the three
# manufacturer families MODELS.md documents against a named, if not
# per-SKU-verified, manufacturer protocol: FrSky ACCESS, FlySky AFHDS2A/3,
# Futaba FASST/FASSTest/T-FHSS. Every other manufacturer/model in this table
# is MODELS.md "Low" evidence (protocol name itself unconfirmed against a
# manufacturer manual, or -- RadioMaster/Jumper -- genuinely
# module-dependent at capture time) and stays LinkFamily.UNKNOWN rather than
# guessing a bucket. `link_role` is LinkRole.UPLINK_CONTROL for every row in
# this table (never guessed per-row): MODELS.md's own category boundary
# ("RC-transmitter-only") is what licenses this, not a per-model RF
# observation.
_RFUAV_RC_TRANSMITTER_ONLY_NOTE = (
    "RC transmitter recording only; no airframe present in this capture "
    "(MODELS.md 'RC-transmitter-only recordings' category)."
)


def _rfuav_rc_label(
    manufacturer: str, model: str, link_family: LinkFamily, evidence_note: str
) -> _RfuavLabel:
    return _RfuavLabel(
        manufacturer,
        model,
        link_family,
        note=f"{_RFUAV_RC_TRANSMITTER_ONLY_NOTE} {evidence_note}",
        link_role=LinkRole.UPLINK_CONTROL,
    )


_RFUAV_RC_LABELS: dict[str, _RfuavLabel] = {
    "DEVENTION DEVO": _rfuav_rc_label(
        "Walkera", "devo", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary 2.4GHz FHSS, exact protocol name (e.g. WK-2401/2801) unconfirmed.",
    ),
    "FLYSKY EL 18": _rfuav_rc_label(
        "FlySky", "el18", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: AFHDS 3.",
    ),
    "FLYSKY FS I6X": _rfuav_rc_label(
        "FlySky", "fs_i6x", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: AFHDS 2A.",
    ),
    "FLYSKY NV 14": _rfuav_rc_label(
        "FlySky", "nv14", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: AFHDS 3.",
    ),
    "FRSKY X14": _rfuav_rc_label(
        "FrSky", "x14", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: ACCESS.",
    ),
    "FRSKY X20R": _rfuav_rc_label(
        "FrSky", "x20r", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: ACCESS. Note: this archive's own pack1.xml "
        "<Drone> field is mistyped 'FLYSKY X20R' -- the folder name (FrSky, "
        "correct) is used here, not the XML text.",
    ),
    "FRSKY X9DP2019": _rfuav_rc_label(
        "FrSky", "x9d_plus_2019", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: ACCESS (firmware-upgradeable; also supports legacy ACCST D16).",
    ),
    "FUTABA T10J": _rfuav_rc_label(
        "Futaba", "t10j", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: FASST/FASSTest (2.4GHz).",
    ),
    "FUTABA T14SG": _rfuav_rc_label(
        "Futaba", "t14sg", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: FASSTest/T-FHSS.",
    ),
    "FUTABA T16IZ": _rfuav_rc_label(
        "Futaba", "t16iz", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: T-FHSS.",
    ),
    "FUTABA T18SZ": _rfuav_rc_label(
        "Futaba", "t18sz", LinkFamily.FHSS_RC,
        "MODELS.md Medium evidence: FASSTest/T-FHSS.",
    ),
    "HERELINK HX4": _rfuav_rc_label(
        "CUAV / CubePilot", "hx4", LinkFamily.UNKNOWN,
        "MODELS.md Medium evidence: proprietary digital HD control+video link described as "
        "LTE-like/OFDM by vendor docs, not a hopping FHSS RC protocol -- no PHY spec published.",
    ),
    "JR PROPO XG14": _rfuav_rc_label(
        "JR Propo", "xg14", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: DMSS (JR's proprietary 2.4GHz protocol).",
    ),
    "JR PROPO XG7": _rfuav_rc_label(
        "JR Propo", "xg7", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: DMSS.",
    ),
    "JUMPER T14": _rfuav_rc_label(
        "Jumper", "t14", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: multi-protocol radio, native RF module at capture time not confirmed.",
    ),
    "JUMPER TPROV2": _rfuav_rc_label(
        "Jumper", "t_pro_v2", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: commonly ships with internal ExpressLRS (ELRS), not confirmed for this capture.",
    ),
    "RADIOLINK AT10 II": _rfuav_rc_label(
        "Radiolink", "at10_ii", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary 2.4GHz FHSS, exact protocol name unconfirmed.",
    ),
    "RADIOLINK AT9S PRO": _rfuav_rc_label(
        "Radiolink", "at9s_pro", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary 2.4GHz FHSS, exact protocol name unconfirmed.",
    ),
    "RADIOMASTER BOXER": _rfuav_rc_label(
        "RadioMaster", "boxer", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: EdgeTX multi-protocol radio, internal module at capture time not confirmed.",
    ),
    "RADIOMASTER TX16S": _rfuav_rc_label(
        "RadioMaster", "tx16s", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: EdgeTX multi-protocol radio, internal module at capture time not confirmed.",
    ),
    "SIYI FT24": _rfuav_rc_label(
        "SIYI", "ft24", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary digital HD control+datalink, no PHY spec published.",
    ),
    "SIYI MK15": _rfuav_rc_label(
        "SIYI", "mk15", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary digital HD control+datalink, no PHY spec published.",
    ),
    "SIYI MK32": _rfuav_rc_label(
        "SIYI", "mk32", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary digital HD control+datalink, no PHY spec published.",
    ),
    "SKYDROID H12": _rfuav_rc_label(
        "Skydroid", "h12", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary digital HD control+datalink, no PHY spec published.",
    ),
    "SKYDROID T10": _rfuav_rc_label(
        "Skydroid", "t10", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary digital HD control+datalink, no PHY spec published.",
    ),
    "WFLY ET10": _rfuav_rc_label(
        "WFLY", "et10", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary 2.4GHz protocol, exact name unconfirmed.",
    ),
    "WFLY ET16S": _rfuav_rc_label(
        "WFLY", "et16s", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary 2.4GHz protocol, exact name unconfirmed.",
    ),
    "WFLY WFT09SII": _rfuav_rc_label(
        "WFLY", "wft09s_ii", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: proprietary 2.4GHz protocol, exact name unconfirmed.",
    ),
    "YUNZHUO H12": _rfuav_rc_label(
        "Yunzhuo", "h12", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: protocol not confirmed; naming overlaps Skydroid H12, possibly rebrand -- unverified.",
    ),
    "YUNZHUO H16": _rfuav_rc_label(
        "Yunzhuo", "h16", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: protocol not confirmed.",
    ),
    "YUNZHUO H30": _rfuav_rc_label(
        "Yunzhuo", "h30", LinkFamily.UNKNOWN,
        "MODELS.md Low evidence: protocol not confirmed.",
    ),
}


def _rfuav_device_slug(folder_name: str) -> str:
    return re.sub(r"[\s_]+", "_", folder_name.strip()).lower()


class RfuavAdapter:
    """S1 adapter for the local RFUAV mirror
    (``~/rf-datasets/rfuav/original``): per-model ``.rar`` archives
    extracted to ``original/extracted/<ARCHIVE_NAME>/<Drone Folder>/
    [VTSBW=<N>/]pack<K>.xml`` + ``pack<K>_<a>-<b>s.iq``. See the
    module-level comment above and
    ``~/rf-datasets/rfuav/original/FORMAT.md`` for the format evidence
    trail (verified against DJI_MINI4_PRO.rar, DJI_AVATA2.rar,
    FLYSKY_FS_I6X.rar, FRSKY_X20R.rar, FUTABA_T14SG.rar).

    One :class:`RecordingMeta` per ``.iq`` slice (each already ~1.0 s at the
    source 100 MS/s rate). ``iter_recordings`` recurses for ``pack*.xml``
    under each top-level ``<ARCHIVE_NAME>`` directory rather than assuming a
    fixed nesting depth, so it handles both the DJI/Autel airframe layout
    (an extra ``VTSBW=<N>/`` grouping level per video-bandwidth setting) and
    the RC-transmitter layout (no such level -- ``pack<K>.xml`` sits
    directly under the ``<Drone Folder>``). ``run_id`` groups a pack's
    slices (``<device_slug>/<VTSBW folder>/pack<K>`` when a VTSBW level
    exists, else ``<device_slug>/pack<K>``) so one continuous multi-second
    capture is never split across train/val/test. A top-level
    ``extracted/`` directory whose name does not match any ``<name>.rar``
    sibling under ``original/`` is skipped (logged, not silent) as a
    stray/duplicate extraction -- see FORMAT.md.

    Labelling: the 5 DJI airframe archives use :data:`_RFUAV_DJI_LABELS`,
    the 1 non-DJI airframe (Autel) archive uses
    :data:`_RFUAV_AIRFRAME_LABELS`, and the 31 RC-transmitter-only archives
    use :data:`_RFUAV_RC_LABELS` (``emitter_class=DRONE_LINK``,
    ``link_role=UPLINK_CONTROL`` -- no separate taxonomy value exists for
    "RC transmitter, no airframe"). Any folder name in none of these three
    tables still enumerates/loads but gets ``EmitterClass.UNKNOWN`` /
    ``EvidenceLevel.RF_CANDIDATE`` rather than a guessed ``drone_link``
    label.
    """

    dataset_id = "rfuav"
    mirror_dir_name = "rfuav"

    def iter_recordings(self, root: Path) -> Iterator[RecordingMeta]:
        original_dir = root / self.mirror_dir_name / "original"
        base = original_dir / "extracted"
        if not base.is_dir():
            return
        # Restricts iteration to directories that actually correspond to one
        # of this mirror's own `.rar` archives (by stem). Guards against a
        # stray/duplicate manual extraction whose directory name doesn't
        # match any archive -- e.g. this mirror's own leftover
        # "extracted/DJI MINI4 PRO/" (no "DJI MINI4 PRO.rar" sibling; the
        # real archive is "DJI_MINI4_PRO.rar", extracted to
        # "extracted/DJI_MINI4_PRO/"), which duplicates DJI_MINI4_PRO.rar's
        # own content and would otherwise be double-counted (identical
        # `device_id`/`recording_id`s under the folder-name-based scheme
        # below). Left empty (no filtering) when `original_dir` has no
        # `.rar` files at all -- e.g. a synthetic test mirror that only
        # constructs the `extracted/` tree directly.
        archive_stems = {p.stem for p in original_dir.glob("*.rar")}
        for archive_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            if archive_stems and archive_dir.name not in archive_stems:
                _rfuav_logger.info(
                    "RfuavAdapter: skipping extracted/%s -- no matching "
                    "%s.rar under %s (stray/duplicate extraction)",
                    archive_dir.name, archive_dir.name, original_dir,
                )
                continue
            if archive_dir.with_name(archive_dir.name + ".aria2").exists():
                _rfuav_logger.info(
                    "RfuavAdapter: skipping extracted/%s -- incomplete download (.aria2 sibling)",
                    archive_dir.name,
                )
                continue
            for xml_path in sorted(archive_dir.rglob("pack*.xml")):
                if xml_path.with_name(xml_path.name + ".aria2").exists():
                    _rfuav_logger.info(
                        "RfuavAdapter: skipping %s -- incomplete download (.aria2 sibling)", xml_path
                    )
                    continue
                pack_dir = xml_path.parent
                pack_id = xml_path.stem  # e.g. "pack1"
                try:
                    pack_num = int(pack_id.removeprefix("pack"))
                except ValueError:
                    _rfuav_logger.info(
                        "RfuavAdapter: skipping %s -- unrecognised pack xml name", xml_path
                    )
                    continue
                # A VTSBW=<N> grouping level is DJI/Autel-airframe-specific
                # (one pack per video-transmission bandwidth setting); RC-
                # transmitter archives put pack<K>.xml directly under the
                # "<Drone Folder>" -- see the module-level comment above.
                # `folder_name` (used for `_rfuav_device_slug` and for the
                # label-table lookup in `labels()`) is always the "<Drone
                # Folder>" name, however many levels of nesting sit above
                # the pack xml.
                if pack_dir.name.startswith("VTSBW="):
                    channel_id: Optional[str] = pack_dir.name
                    folder_name = pack_dir.parent.name
                else:
                    channel_id = None
                    folder_name = pack_dir.name
                device_slug = _rfuav_device_slug(folder_name)
                try:
                    meta = parse_rfuav_pack_xml(xml_path)
                except (ValueError, TypeError, AttributeError) as exc:
                    _rfuav_logger.info(
                        "RfuavAdapter: skipping %s -- failed to parse pack xml (%s)", xml_path, exc
                    )
                    continue
                channel_part = f"{channel_id}/" if channel_id else ""
                run_id = f"{device_slug}/{channel_part}{pack_id}"
                for iq_path in sorted(pack_dir.glob(f"{pack_id}_*-*s.iq")):
                    if iq_path.with_name(iq_path.name + ".aria2").exists():
                        _rfuav_logger.info(
                            "RfuavAdapter: skipping %s -- incomplete download (.aria2 sibling)", iq_path
                        )
                        continue
                    m = _RFUAV_IQ_STEM_RE.match(iq_path.stem)
                    if not m or int(m.group(1)) != pack_num:
                        continue
                    recording_id = f"{device_slug}/{channel_part}{iq_path.stem}"
                    yield RecordingMeta(
                        dataset_id=self.dataset_id,
                        recording_id=recording_id,
                        device_id=device_slug,
                        run_id=run_id,
                        source_paths=(iq_path,),
                        original_rate_hz=meta.sample_rate_hz,
                        original_center_freq_hz=meta.center_freq_hz,
                        original_bw_hz=meta.if_bandwidth_hz,
                        original_dtype="float32_interleaved",
                        channel_id=channel_id,
                        notes=meta.note,
                        extra={
                            "folder_name": folder_name,
                            "xml_drone": meta.drone,
                            "sample_count": meta.sample_count,
                            "scale_factor": meta.scale_factor,
                            "reference_snr_level": meta.reference_snr_level,
                            "serial_number": meta.serial_number,
                        },
                    )

    def load_iq(
        self, rec: RecordingMeta
    ) -> tuple[np.ndarray, float, Optional[float], Optional[float]]:
        raw = np.memmap(rec.source_paths[0], dtype="<f4", mode="r")
        expected_samples = int(rec.extra["sample_count"])
        if raw.size % 2 != 0:
            raise ValueError(
                f"RfuavAdapter: {rec.source_paths[0]} has {raw.size} float32 "
                "values -- odd count, cannot pair into complex64 samples -- "
                "format assumption (complex64, no header) may not hold for "
                "this file"
            )
        actual_samples = raw.size // 2
        if actual_samples > expected_samples:
            raise ValueError(
                f"RfuavAdapter: {rec.source_paths[0]} has {raw.size} float32 "
                f"values ({actual_samples} complex64 samples), more than "
                f"expected {expected_samples * 2} (2 * XML "
                f"SampleCount={expected_samples}) -- format assumption "
                "(complex64, no header) may not hold for this file"
            )
        iq = np.asarray(raw).view(np.complex64)
        if actual_samples < expected_samples:
            # A pack's last `.iq` slice legitimately covers less than the
            # nominal ~1 s if the capture ended mid-slice (verified against
            # 6 real slices across the corpus, all exactly a whole number of
            # complex64 samples and all the numerically-last slice of their
            # pack -- see prepare_full2.log / FORMAT.md). Any byte count
            # that is not a whole number of complex64 samples, or exceeds
            # the XML-declared count, still means the format assumption
            # itself may not hold (raised above) -- only a clean, smaller
            # sample count is treated as a legitimate short tail.
            rec.extra["truncated_tail"] = True
            rec.extra["expected_sample_count"] = expected_samples
            rec.extra["sample_count"] = actual_samples
            _rfuav_logger.info(
                "RfuavAdapter: %s is a short tail slice -- %d complex64 "
                "samples vs XML SampleCount=%d; accepted as truncated_tail",
                rec.source_paths[0], actual_samples, expected_samples,
            )
        return iq, rec.original_rate_hz, rec.original_center_freq_hz, rec.original_bw_hz

    def labels(self, rec: RecordingMeta) -> LabelsGroup:
        folder_key = rec.extra["folder_name"].upper()
        label = (
            _RFUAV_DJI_LABELS.get(folder_key)
            or _RFUAV_AIRFRAME_LABELS.get(folder_key)
            or _RFUAV_RC_LABELS.get(folder_key)
        )
        if label is None:
            inst = LabelInstance(
                emitter_class=EmitterClass.UNKNOWN,
                link_family=LinkFamily.UNKNOWN,
                link_role=LinkRole.UNKNOWN,
                activity=Activity.UNKNOWN,
                evidence_level=EvidenceLevel.RF_CANDIDATE,
                label_source=LabelSource.UNKNOWN,
            )
            return LabelsGroup(scene=inst, window=inst)
        inst = LabelInstance(
            emitter_class=EmitterClass.DRONE_LINK,
            link_family=label.link_family,
            # For the DJI/Autel airframe tables: VTSBW almost certainly
            # abbreviates "video transmission signal bandwidth" (consistent
            # with OcuSync's selectable 10/20/40 MHz video-downlink channel
            # width), but no README/paper text inside the archive confirms
            # this -- see FORMAT.md -- so link_role stays unknown rather
            # than asserted as downlink_video. For the RC-transmitter table,
            # `label.link_role` is UPLINK_CONTROL (see
            # `_RFUAV_RC_LABELS`/`_rfuav_rc_label` above) -- licensed by
            # MODELS.md's own "RC-transmitter-only" category boundary, not a
            # per-model RF observation.
            link_role=label.link_role,
            manufacturer=label.manufacturer,
            model=label.model,
            individual_id=str(rec.extra.get("serial_number") or "unknown"),
            activity=Activity.UNKNOWN,
            evidence_level=EvidenceLevel.OPERATOR_TRUTH,
            label_source=LabelSource.DATASET_METADATA,
        )
        return LabelsGroup(scene=inst, window=inst)


# ---------------------------------------------------------------------------
# Zenodo 19870020 -- "FPV Analogue Video IQ Dataset" (analog_fpv_public,
# Workstream D, T7). HackRF One wideband frequency-SWEEP captures: 100 MHz
# .. 5.98 GHz on a 20 MHz grid (295 tuned frequencies), 10 contiguous
# 65536-sample dwell blocks per frequency before retuning, 20 MS/s,
# interleaved float32 I/Q already unit-scale (complex64 view, no further
# scaling) -- see ~/rf-datasets/analog_fpv_public/original/FORMAT.md for the
# byte-count / value-range / spectrum verification evidence trail (checked
# against `chunk10.zip` only).
#
# The shared top-level `iq_recording_meta.csv` gives one row of ground truth
# per *sweep* (one `iq.bin`): `drone_freq` (the VTX carrier in MHz, or the
# literal string "none" for a no-TX control sweep), `vtx_power_mw`,
# `distance _m`, `environment`, free-text `notes`. Its header is malformed
# (`vtx_power_mw\,distance _m` -- a literal unescaped backslash before a
# comma) and is repaired before parsing; see FORMAT.md.
#
# `RecordingMeta` granularity is one *dwell* (10 contiguous blocks at one
# `center_freq`), NOT one per `iq.bin`: a sweep's `drone_freq` ground truth
# is only true for the dwell(s) actually tuned to that frequency -- a sweep
# spends 294/295 of its dwells tuned far from the VTX. Treating the whole
# sweep as a single recording would force one wrong label across the file
# (either a false-positive TX label on 294 background dwells, or discarding
# real background data by calling the whole sweep "unknown"). This is a
# deliberate deviation from a literal "one recording per IQ file" reading;
# see the handback report.
# ---------------------------------------------------------------------------

_ANALOG_FPV_RATE_HZ = 20_000_000.0
_ANALOG_FPV_BYTES_PER_SAMPLE = 8  # complex64: 2 x float32
# A dwell's tuned `center_freq` (Hz, integer in the sweep's own metadata.csv)
# is matched to the sweep-level `drone_freq` (MHz, float, possibly
# fractional) within this tolerance before calling it "the TX dwell".
_ANALOG_FPV_FREQ_MATCH_TOL_HZ = 1.0


@dataclass(frozen=True)
class _AnalogFpvSweepMeta:
    sweep_id: str
    drone_freq_hz: Optional[float]  # None == "none" (no-TX control sweep)
    vtx_power_mw: float
    distance_m: str
    environment: str
    notes: str


def _parse_analog_fpv_meta_csv(path: Path) -> dict[str, _AnalogFpvSweepMeta]:
    """Parse the dataset's shared `iq_recording_meta.csv`, repairing its
    malformed header (see the module-comment above and FORMAT.md): splitting
    naively on `,` gives 13 tokens for 13 data columns once a stray trailing
    backslash is stripped from each token."""

    import csv

    out: dict[str, _AnalogFpvSweepMeta] = {}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = [h.strip().rstrip("\\").strip() for h in next(reader)]
        for row in reader:
            if not row or not row[0].strip():
                continue
            rec = dict(zip(header, row))
            drone_freq_raw = (rec.get("drone_freq") or "none").strip()
            drone_freq_hz = (
                None if drone_freq_raw.lower() == "none" else float(drone_freq_raw) * 1e6
            )
            distance_m = (rec.get("distance_m") or rec.get("distance _m") or "").strip()
            sweep_id = (rec.get("iq_folder") or "").strip()
            if not sweep_id:
                continue
            out[sweep_id] = _AnalogFpvSweepMeta(
                sweep_id=sweep_id,
                drone_freq_hz=drone_freq_hz,
                vtx_power_mw=float(rec.get("vtx_power_mw") or 0),
                distance_m=distance_m,
                environment=(rec.get("environment") or "").strip(),
                notes=(rec.get("notes") or "").strip(),
            )
    return out


def _iter_analog_fpv_dwells(path: Path) -> Iterator[tuple[int, int, int]]:
    """Group a sweep's per-block `metadata.csv` (`timestamp,center_freq,
    offset_bytes,num_samples`) into contiguous same-`center_freq` runs.
    Yields ``(center_freq_hz, first_offset_bytes, total_samples)`` per run,
    in file order. Contiguity (no gap between blocks) is verified by byte
    arithmetic, not assumed."""

    import csv

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = [
            (int(r["center_freq"]), int(r["offset_bytes"]), int(r["num_samples"]))
            for r in reader
        ]
    i = 0
    n = len(rows)
    while i < n:
        freq, off0, _ = rows[i]
        j = i
        while j < n and rows[j][0] == freq:
            j += 1
        last_off, last_ns = rows[j - 1][1], rows[j - 1][2]
        total_samples = (last_off - off0) // _ANALOG_FPV_BYTES_PER_SAMPLE + last_ns
        yield freq, off0, total_samples
        i = j


class AnalogFpvZenodoAdapter:
    """S1 adapter for the local Zenodo 19870020 mirror
    (``~/rf-datasets/analog_fpv_public/original``): ``chunk<N>.zip`` archives
    extracted to ``original/extracted/chunk<N>/chunk<N>/sweep_<ts>/{metadata.csv,
    iq.bin}``, cross-referenced against the shared ``iq_recording_meta.csv``.
    See the module-level comment above and
    ``~/rf-datasets/analog_fpv_public/original/FORMAT.md``.
    """

    dataset_id = "analog_fpv_public"
    mirror_dir_name = "analog_fpv_public"

    def iter_recordings(self, root: Path) -> Iterator[RecordingMeta]:
        base = root / self.mirror_dir_name / "original"
        meta_csv = base / "iq_recording_meta.csv"
        extracted = base / "extracted"
        if not meta_csv.is_file() or not extracted.is_dir():
            return
        sweep_meta = _parse_analog_fpv_meta_csv(meta_csv)
        for chunk_dir in sorted(p for p in extracted.iterdir() if p.is_dir()):
            for sweep_dir in sorted(chunk_dir.glob("*/sweep_*")):
                if not sweep_dir.is_dir():
                    continue
                meta = sweep_meta.get(sweep_dir.name)
                if meta is None:
                    continue  # sweep on disk but absent from the shared CSV: skip, never guess
                iq_path = sweep_dir / "iq.bin"
                dwell_csv = sweep_dir / "metadata.csv"
                if not iq_path.is_file() or not dwell_csv.is_file():
                    continue
                run_id = f"{chunk_dir.name}/{sweep_dir.name}"
                for center_hz, off0, n_samples in _iter_analog_fpv_dwells(dwell_csv):
                    is_tx_freq = (
                        meta.drone_freq_hz is not None
                        and abs(center_hz - meta.drone_freq_hz) < _ANALOG_FPV_FREQ_MATCH_TOL_HZ
                    )
                    device_id = (
                        f"vtx_{meta.vtx_power_mw:.0f}mw"
                        if meta.drone_freq_hz is not None
                        else "no_tx"
                    )
                    notes = (
                        f"analog_fpv_public sweep dwell; sweep drone_freq="
                        f"{meta.drone_freq_hz!r} Hz; vtx_power_mw={meta.vtx_power_mw}; "
                        f"distance_m={meta.distance_m}; environment={meta.environment}"
                    )
                    if meta.notes:
                        notes += f"; dataset_notes={meta.notes}"
                    yield RecordingMeta(
                        dataset_id=self.dataset_id,
                        recording_id=f"{run_id}/f{center_hz}",
                        device_id=device_id,
                        run_id=run_id,
                        source_paths=(iq_path,),
                        original_rate_hz=_ANALOG_FPV_RATE_HZ,
                        original_center_freq_hz=float(center_hz),
                        # No declared IF/anti-alias bandwidth narrower than
                        # the sample rate is documented (see FORMAT.md).
                        original_bw_hz=_ANALOG_FPV_RATE_HZ,
                        original_dtype="float32_interleaved",
                        channel_id=f"f{center_hz}",
                        notes=notes,
                        extra={
                            "offset_bytes": off0,
                            "n_samples": n_samples,
                            "is_tx_freq": is_tx_freq,
                            "drone_freq_hz": meta.drone_freq_hz,
                            "vtx_power_mw": meta.vtx_power_mw,
                            "no_tx_sweep": meta.drone_freq_hz is None,
                        },
                    )

    def load_iq(
        self, rec: RecordingMeta
    ) -> tuple[np.ndarray, float, Optional[float], Optional[float]]:
        off0 = int(rec.extra["offset_bytes"])
        n_samples = int(rec.extra["n_samples"])
        raw = np.fromfile(
            rec.source_paths[0], dtype="<f4", count=n_samples * 2, offset=off0
        )
        if raw.size != n_samples * 2:
            raise ValueError(
                f"AnalogFpvZenodoAdapter: {rec.source_paths[0]} yielded "
                f"{raw.size} float32 values at offset {off0}, expected "
                f"{n_samples * 2} (2 * n_samples={n_samples}) -- dwell "
                "grouping from metadata.csv may not match iq.bin's actual length"
            )
        iq = raw.view(np.complex64)
        return iq, rec.original_rate_hz, rec.original_center_freq_hz, rec.original_bw_hz

    def labels(self, rec: RecordingMeta) -> LabelsGroup:
        if rec.extra["no_tx_sweep"]:
            # Dataset's own no-TX control sweep: every dwell in it is
            # confirmed background by the dataset's own ground truth.
            inst = LabelInstance(
                emitter_class=EmitterClass.BACKGROUND,
                link_family=LinkFamily.NOT_APPLICABLE,
                link_role=LinkRole.NOT_APPLICABLE,
                activity=Activity.OFF,
                evidence_level=EvidenceLevel.OPERATOR_TRUTH,
                label_source=LabelSource.DATASET_METADATA,
            )
            return LabelsGroup(scene=inst, window=inst)
        if rec.extra["is_tx_freq"]:
            inst = LabelInstance(
                emitter_class=EmitterClass.DRONE_LINK,
                link_family=LinkFamily.ANALOG_FPV,
                link_role=LinkRole.DOWNLINK_VIDEO,
                individual_id=f"vtx_{rec.extra['vtx_power_mw']:.0f}mw",
                activity=Activity.UNKNOWN,
                evidence_level=EvidenceLevel.OPERATOR_TRUTH,
                label_source=LabelSource.DATASET_METADATA,
            )
            return LabelsGroup(scene=inst, window=inst)
        # A dwell from a TX sweep, but tuned away from `drone_freq`: the
        # dataset never explicitly asserts "no signal here", only "the VTX
        # is at drone_freq" -- absence at this other frequency is this
        # adapter's own frequency-separation inference, not a dataset label.
        inst = LabelInstance(
            emitter_class=EmitterClass.BACKGROUND,
            link_family=LinkFamily.NOT_APPLICABLE,
            link_role=LinkRole.NOT_APPLICABLE,
            activity=Activity.UNKNOWN,
            evidence_level=EvidenceLevel.PROBABILISTIC_CLASSIFICATION,
            label_source=LabelSource.HEURISTIC_INFERENCE,
        )
        return LabelsGroup(scene=inst, window=inst)


ADAPTERS: dict[str, Adapter] = {
    ZenodoDroneRF2020Adapter.dataset_id: ZenodoDroneRF2020Adapter(),
    RubDroneSecurityAdapter.dataset_id: RubDroneSecurityAdapter(),
    RfuavAdapter.dataset_id: RfuavAdapter(),
    AnalogFpvZenodoAdapter.dataset_id: AnalogFpvZenodoAdapter(),
    "aerix_antsdr_ambient_2026_09_18": AerixSessionAdapter(
        dataset_id="aerix_antsdr_ambient_2026_09_18"
    ),
}
