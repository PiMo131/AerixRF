"""SigMF recording and playback of IQ captures.

Wire format: recordings are written as ``cf32_le`` (interleaved little-endian
float32 I/Q pairs, full scale ``|x| == 1.0`` = 0 dBFS). Multi-channel data is
channel-interleaved per sample (``s0c0, s0c1, s1c0, ...``) with
``core:num_channels`` set, as the SigMF specification prescribes, and is
``(channels, n)`` in memory. Reading additionally accepts the fixed-point
``ci16_le`` / ``ci8`` the E200/AD9361 firmware produces natively (plus the
other standard datatypes): integer components are scaled by ``2**-(bits-1)``
(unsigned ones re-centred first) so the integer full-scale range maps onto
``[-1, 1)`` and 0 dBFS means the same thing for every input format.

Toolkit-specific metadata lives in the ``antsdr:`` namespace, declared in
``core:extensions`` (``antsdr:gain_db``, ``antsdr:rx_channels``,
``antsdr:rf_bandwidth_hz``), so a :class:`StreamInfo` round-trips losslessly
while the file remains valid SigMF.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import IO, Any

import numpy as np

from .. import __version__
from ..device.base import StreamInfo, empty_iq

DATASET_EXT = ".sigmf-data"
METADATA_EXT = ".sigmf-meta"
ARCHIVE_EXT = ".sigmf"
WRITE_DATATYPE = "cf32_le"
NAMESPACE = "antsdr"
_FALLBACK_SPEC_VERSION = "1.2.0"
_ANNOTATION_ALIASES = {
    "sample_start": "core:sample_start",
    "sample_count": "core:sample_count",
    "freq_lower_hz": "core:freq_lower_edge",
    "freq_upper_hz": "core:freq_upper_edge",
    "label": "core:label",
}
_DATATYPE_RE = re.compile(r"^([cr])([fiu])(8|16|32|64)(?:_(le|be))?$")

PathLike = str | os.PathLike

__all__ = [
    "DatatypeInfo", "SigmfReader", "SigmfRecorder", "components_to_complex64",
    "global_from_stream_info", "load_metadata", "parse_datatype", "read_sigmf", "sigmf_paths",
    "stream_info_from_metadata", "utc_now_iso8601", "validate_metadata", "write_sigmf",
]


# ----- paths, time and validation --------------------------------------------
def sigmf_paths(stem_or_path: PathLike) -> tuple[pathlib.Path, pathlib.Path]:
    """Resolve a stem, ``.sigmf-data`` or ``.sigmf-meta`` path to ``(data, meta)`` paths.

    Only a trailing SigMF extension is stripped, so dotted stems such as
    ``capture.2437MHz`` survive unchanged.
    """
    path = pathlib.Path(stem_or_path)
    name = path.name
    for ext in (DATASET_EXT, METADATA_EXT, ARCHIVE_EXT):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    if not name:
        raise ValueError(f"cannot derive a SigMF stem from {os.fspath(stem_or_path)!r}")
    return path.with_name(name + DATASET_EXT), path.with_name(name + METADATA_EXT)


def utc_now_iso8601() -> str:
    """Current UTC time as the ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` string SigMF expects."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def spec_version() -> str:
    """SigMF specification version written into ``core:version``."""
    try:
        import sigmf

        return str(sigmf.__specification__)
    except (ImportError, AttributeError):  # pragma: no cover - sigmf is a hard dependency
        return _FALLBACK_SPEC_VERSION


def validate_metadata(metadata: Mapping[str, Any]) -> None:
    """Validate a metadata document against the SigMF JSON schema (``ValueError`` on failure).

    Uses the ``sigmf`` reference implementation; if it cannot be imported the
    check is skipped so writing never depends on it at runtime.
    """
    try:
        from sigmf import SigMFFile
    except ImportError:  # pragma: no cover - sigmf is a hard dependency
        return
    try:
        SigMFFile(metadata=json.loads(json.dumps(dict(metadata)))).validate()
    except Exception as exc:
        raise ValueError(f"metadata is not valid SigMF: {exc}") from exc


def load_metadata(meta_path: PathLike) -> dict[str, Any]:
    """Parse a ``.sigmf-meta`` JSON document and check the mandatory sections."""
    with open(meta_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or "global" not in doc:
        raise ValueError(f"{os.fspath(meta_path)} is not a SigMF metadata document")
    doc.setdefault("captures", [])
    doc.setdefault("annotations", [])
    return doc


# ----- datatypes --------------------------------------------------------------
@dataclass(frozen=True)
class DatatypeInfo:
    """Decoded SigMF ``core:datatype`` string.

    ``component_dtype`` is the on-disk numpy dtype of one real component (byte
    order included); a complex sample is two consecutive components. Converting
    to float subtracts ``offset`` then multiplies by ``scale`` so the integer
    full-scale range maps onto ``[-1, 1)``.
    """

    name: str
    component_dtype: np.dtype
    is_complex: bool
    offset: float
    scale: float

    @property
    def components_per_sample(self) -> int:
        return 2 if self.is_complex else 1

    @property
    def sample_bytes(self) -> int:
        return self.component_dtype.itemsize * self.components_per_sample


def parse_datatype(datatype: str) -> DatatypeInfo:
    """Decode e.g. ``"ci16_le"`` -> int16 little-endian complex, scale ``2**-15``."""
    name = str(datatype).strip().lower()
    match = _DATATYPE_RE.match(name)
    if match is None:
        raise ValueError(f"unsupported SigMF datatype {datatype!r}")
    kind, fmt, bits_s, endian = match.groups()
    bits = int(bits_s)
    if fmt == "f" and bits < 32:
        raise ValueError(f"{datatype!r}: float datatypes must be 32 or 64 bit")
    if bits > 8 and endian is None:
        raise ValueError(f"{datatype!r}: multi-byte datatypes need an _le/_be suffix")
    order = "<" if endian == "le" else ">" if endian == "be" else "|"
    component = np.dtype(f"{order}{fmt}{bits // 8}")
    offset = float(2 ** (bits - 1)) if fmt == "u" else 0.0
    scale = 1.0 if fmt == "f" else float(2.0 ** -(bits - 1))
    return DatatypeInfo(name, component, kind == "c", offset, scale)


def components_to_complex64(
    raw: np.ndarray, datatype: DatatypeInfo, n_channels: int = 1
) -> np.ndarray:
    """Convert flat on-disk components to full-scale complex64 IQ.

    ``raw`` holds ``n * n_channels * components_per_sample`` components in file
    order. Returns a fresh, writable, C-contiguous ``(n,)`` array for one
    channel or ``(n_channels, n)`` otherwise; real datatypes get a zero Q part.
    """
    comps = np.asarray(raw)  # plain ndarray view (drops the memmap subclass)
    per_frame = datatype.components_per_sample * max(n_channels, 1)
    if comps.size % per_frame:
        raise ValueError(f"{comps.size} components is not a whole number of {per_frame}-frames")
    floats = comps.astype(np.float32)  # always copies and normalises byte order
    if datatype.offset:
        floats -= np.float32(datatype.offset)
    if datatype.scale != 1.0:
        floats *= np.float32(datatype.scale)
    iq = floats.view(np.complex64) if datatype.is_complex else floats.astype(np.complex64)
    return iq if n_channels <= 1 else np.ascontiguousarray(iq.reshape(-1, n_channels).T)


# ----- StreamInfo <-> metadata ------------------------------------------------
def stream_info_from_metadata(
    metadata: Mapping[str, Any], *, default_hardware: str = "unknown"
) -> StreamInfo:
    """Build a :class:`StreamInfo` from a SigMF document (first capture = tuning)."""
    glob = metadata.get("global", {})
    if "core:sample_rate" not in glob:
        raise ValueError("SigMF metadata lacks core:sample_rate")
    captures = metadata.get("captures") or []
    center = float(captures[0].get("core:frequency", 0.0)) if captures else 0.0
    n_channels = int(glob.get("core:num_channels", 1))
    rx = glob.get(f"{NAMESPACE}:rx_channels")
    if not rx or len(rx) != n_channels:
        rx = tuple(range(n_channels))
    gain = glob.get(f"{NAMESPACE}:gain_db")
    rf_bw = glob.get(f"{NAMESPACE}:rf_bandwidth_hz")
    return StreamInfo(
        sample_rate_hz=float(glob["core:sample_rate"]),
        center_freq_hz=center,
        rx_channels=tuple(int(c) for c in rx),
        gain_db=None if gain is None else float(gain),
        hardware=str(glob.get("core:hw", default_hardware)),
        description=str(glob.get("core:description", "")),
        rf_bandwidth_hz=None if rf_bw is None else float(rf_bw),
    )


def global_from_stream_info(
    info: StreamInfo, extra_global: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build the ``global`` section for a ``cf32_le`` recording of ``info``.

    ``extra_global`` is merged last (it may not change the datatype or channel
    count); the ``antsdr`` extension is always declared in ``core:extensions``.
    """
    glob: dict[str, Any] = {
        "core:datatype": WRITE_DATATYPE,
        "core:sample_rate": info.sample_rate_hz,
        "core:version": spec_version(),
        "core:hw": info.hardware,
        "core:description": info.description,
        "core:recorder": f"antsdr_toolkit/{__version__}",
        f"{NAMESPACE}:rx_channels": list(info.rx_channels),
    }
    if info.n_channels > 1:
        glob["core:num_channels"] = info.n_channels
    if info.gain_db is not None:
        glob[f"{NAMESPACE}:gain_db"] = info.gain_db
    if info.rf_bandwidth_hz is not None:
        glob[f"{NAMESPACE}:rf_bandwidth_hz"] = info.rf_bandwidth_hz
    if extra_global:
        for key in ("core:datatype", "core:num_channels"):
            if key in extra_global and extra_global[key] != glob.get(key):
                raise ValueError(f"extra_global may not override {key}")
        glob.update(extra_global)
    extensions = list(glob.get("core:extensions") or [])
    if not any(isinstance(e, Mapping) and e.get("name") == NAMESPACE for e in extensions):
        extensions.append({"name": NAMESPACE, "version": __version__, "optional": True})
    glob["core:extensions"] = extensions
    return glob


def _normalise_annotation(annotation: Mapping[str, Any]) -> dict[str, Any]:
    """Map friendly keys to ``core:`` keys and namespace the rest under ``antsdr:``."""
    out: dict[str, Any] = {}
    for key, value in annotation.items():
        if ":" in key:
            out[key] = value
        elif key in _ANNOTATION_ALIASES:
            out[_ANNOTATION_ALIASES[key]] = value
        else:
            out[f"{NAMESPACE}:{key}"] = value
    if "core:sample_start" not in out:
        raise ValueError("annotation needs core:sample_start")
    out["core:sample_start"] = int(out["core:sample_start"])
    if "core:sample_count" in out:
        out["core:sample_count"] = int(out["core:sample_count"])
    json.dumps(out)  # fail early on non-serialisable values
    return out


# ----- writing ----------------------------------------------------------------
class SigmfRecorder:
    """Streaming ``cf32_le`` recorder: append chunks, annotate, close.

    Global and capture metadata are validated against the SigMF schema before
    the data file is created, so a bad ``extra_global`` or timestamp never
    leaves a half-written capture behind. ``.sigmf-meta`` is written on
    :meth:`close` (idempotent; also triggered by the context manager).
    """

    def __init__(
        self,
        stem: PathLike,
        info: StreamInfo,
        *,
        datetime_utc: str | None = None,
        extra_global: Mapping[str, Any] | None = None,
    ) -> None:
        self.data_path, self.meta_path = sigmf_paths(stem)
        self.info = info
        self.datetime_utc = datetime_utc or utc_now_iso8601()
        self._global = global_from_stream_info(info, extra_global)
        self._captures = [{
            "core:sample_start": 0,
            "core:frequency": info.center_freq_hz,
            "core:datetime": self.datetime_utc,
        }]
        self._annotations: list[dict[str, Any]] = []
        self.samples_written = 0
        self._closed = False
        validate_metadata(self.metadata())
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[bytes] | None = open(self.data_path, "wb")  # noqa: SIM115 - closed in close()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def duration_s(self) -> float:
        return self.samples_written / self.info.sample_rate_hz

    def metadata(self) -> dict[str, Any]:
        """Current metadata document (annotations sorted by sample start)."""
        return {
            "global": dict(self._global),
            "captures": [dict(c) for c in self._captures],
            "annotations": sorted(self._annotations, key=lambda a: a["core:sample_start"]),
        }

    def write(self, samples: np.ndarray) -> None:
        """Append ``(n,)`` or ``(channels, n)`` samples as interleaved cf32_le."""
        if self._fh is None:
            raise ValueError("recorder is closed")
        x = np.asarray(samples)
        n_channels = self.info.n_channels
        if x.ndim == 1:
            if n_channels != 1:
                raise ValueError(f"expected ({n_channels}, n) samples for a multi-channel stream")
            frames = x
        elif x.ndim == 2:
            if x.shape[0] != n_channels:
                raise ValueError(f"expected {n_channels} channels on axis 0, got {x.shape[0]}")
            frames = x.T  # (n, channels): channel-interleaved per sample on disk
        else:
            raise ValueError(f"samples must be 1-D or 2-D, got shape {x.shape}")
        self._fh.write(np.ascontiguousarray(frames, dtype=np.dtype("<c8")).tobytes())
        self.samples_written += int(frames.shape[0])

    def annotate(
        self,
        sample_start: int,
        sample_count: int,
        *,
        freq_lower_hz: float | None = None,
        freq_upper_hz: float | None = None,
        label: str | None = None,
        **extra: Any,
    ) -> None:
        """Add an annotation; extra keys are namespaced ``antsdr:`` unless already prefixed."""
        ann: dict[str, Any] = {"sample_start": sample_start, "sample_count": sample_count}
        if freq_lower_hz is not None:
            ann["freq_lower_hz"] = float(freq_lower_hz)
        if freq_upper_hz is not None:
            ann["freq_upper_hz"] = float(freq_upper_hz)
        if label is not None:
            ann["label"] = str(label)
        ann.update(extra)
        self.add_annotation(ann)

    def add_annotation(self, annotation: Mapping[str, Any]) -> None:
        """Add an annotation given with SigMF keys (``core:...``) or the friendly aliases."""
        self._annotations.append(_normalise_annotation(annotation))

    def close(self) -> None:
        """Flush the data file and write ``.sigmf-meta``; safe to call repeatedly."""
        if self._closed:
            return
        self._closed = True
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(self.metadata(), fh, indent=2)
            fh.write("\n")

    def __enter__(self) -> SigmfRecorder:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def write_sigmf(
    stem: PathLike,
    samples: np.ndarray,
    info: StreamInfo,
    *,
    datetime_utc: str | None = None,
    annotations: Sequence[Mapping[str, Any]] = (),
    extra_global: Mapping[str, Any] | None = None,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Write a whole ``(n,)`` / ``(channels, n)`` array as a SigMF recording.

    Returns ``(data_path, meta_path)``. ``annotations`` pass through (SigMF
    keys or the friendly aliases accepted by :meth:`SigmfRecorder.annotate`).
    """
    with SigmfRecorder(stem, info, datetime_utc=datetime_utc, extra_global=extra_global) as rec:
        rec.write(samples)
        for ann in annotations:
            rec.add_annotation(ann)
    return rec.data_path, rec.meta_path


# ----- reading ----------------------------------------------------------------
class SigmfReader:
    """Random-access reader over a SigMF dataset, memory-mapped by default.

    :meth:`read` always returns a fresh complex64 array at full scale 1.0;
    :attr:`samples` exposes the whole dataset, as a zero-copy read-only view
    for native ``cf32_le`` data when ``mmap`` is on.
    """

    def __init__(self, path: PathLike, *, mmap: bool = True) -> None:
        self.data_path, self.meta_path = sigmf_paths(path)
        for p in (self.meta_path, self.data_path):
            if not p.is_file():
                raise FileNotFoundError(f"SigMF file not found: {p}")
        self.metadata = load_metadata(self.meta_path)
        glob = self.metadata["global"]
        self.datatype = parse_datatype(str(glob.get("core:datatype", "")))
        self.n_channels = max(int(glob.get("core:num_channels", 1)), 1)
        self.info = stream_info_from_metadata(self.metadata)
        self.header_bytes = int(glob.get("core:header_bytes", 0))
        payload = self.data_path.stat().st_size - self.header_bytes
        payload -= int(glob.get("core:trailing_bytes", 0))
        self.n_samples = max(payload, 0) // (self.datatype.sample_bytes * self.n_channels)
        n_components = self.n_samples * self.n_channels * self.datatype.components_per_sample
        self.mmap = bool(mmap)
        dtype = self.datatype.component_dtype
        self._raw: np.ndarray | None
        if n_components == 0:
            self._raw = np.empty((0,), dtype=dtype)
        elif self.mmap:
            self._raw = np.memmap(self.data_path, dtype=dtype, mode="r",
                                  offset=self.header_bytes, shape=(n_components,))
        else:
            self._raw = np.fromfile(self.data_path, dtype=dtype, count=n_components,
                                    offset=self.header_bytes)

    def __len__(self) -> int:
        return self.n_samples

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.info.sample_rate_hz

    @property
    def annotations(self) -> list[dict[str, Any]]:
        return list(self.metadata.get("annotations", []))

    def read(self, start: int, count: int) -> np.ndarray:
        """Return up to ``count`` samples from ``start`` (clipped to the dataset end)."""
        if self._raw is None:
            raise ValueError("reader is closed")
        if start < 0 or count < 0:
            raise ValueError("start and count must be non-negative")
        start = min(start, self.n_samples)
        count = min(count, self.n_samples - start)
        if count == 0:
            return empty_iq(self.n_channels)
        per = self.n_channels * self.datatype.components_per_sample
        raw = self._raw[start * per : (start + count) * per]
        return components_to_complex64(raw, self.datatype, self.n_channels)

    @property
    def samples(self) -> np.ndarray:
        """Whole dataset: zero-copy read-only view for mmap'd cf32_le, else a copy."""
        if self._raw is None:
            raise ValueError("reader is closed")
        native = self.datatype.is_complex and self.datatype.component_dtype == np.dtype(np.float32)
        if native and self.n_samples > 0:
            iq = np.asarray(self._raw).view(np.complex64)
            return iq if self.n_channels == 1 else iq.reshape(-1, self.n_channels).T
        return self.read(0, self.n_samples)

    def close(self) -> None:
        self._raw = None

    def __enter__(self) -> SigmfReader:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def read_sigmf(
    path: PathLike, *, mmap: bool = True
) -> tuple[np.ndarray, StreamInfo, dict[str, Any]]:
    """Read a whole recording: ``(samples complex64, StreamInfo, metadata dict)``.

    With ``mmap=True`` a native ``cf32_le`` file comes back as a read-only,
    lazily paged view; other datatypes (and ``mmap=False``) yield an in-memory
    copy scaled to full scale 1.0.
    """
    reader = SigmfReader(path, mmap=mmap)
    return reader.samples, reader.info, reader.metadata
