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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Protocol

import numpy as np

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


ADAPTERS: dict[str, Adapter] = {
    ZenodoDroneRF2020Adapter.dataset_id: ZenodoDroneRF2020Adapter(),
    RubDroneSecurityAdapter.dataset_id: RubDroneSecurityAdapter(),
}
