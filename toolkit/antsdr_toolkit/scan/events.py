"""Provisional detection-event record for sweep and burst detections.

A :class:`DetectionEvent` is one thing the receiver noticed: an energy burst
or an occupied segment, bounded in time and frequency, with its level, an
optional waveform-family label and an ``evidence`` dict holding the numbers
the decision was made from (kurtosis, noise floor, burst features ...).
Events are appended to JSON Lines files (:class:`JsonlEventWriter`) so a
long unattended sweep leaves a replayable trail.

Schema status (``schema_version = "0.1"``)
-------------------------------------------
This is a **provisional** schema owned by the toolkit.  It will later be
mapped onto the AERIX observation contract
(``contracts/observation-envelope.v1.schema.json`` at the repository root),
whose ``source`` enum already reserves the receiver class ``future_sdr``
for SDR front ends.  Intended correspondence:

=====================  ==================================================
DetectionEvent         ObservationEnvelope v1
=====================  ==================================================
``event_id``           ``observation_id`` (the contract prefers UUIDv7 for
                       time ordering; v4 is generated here - revisit)
``sensor_id``          ``sensor_id`` (same pattern rules)
``received_at_utc``    ``received_at_utc`` (RFC 3339, ms precision)
``source``             ``source = "future_sdr"``; the toolkit value
                       (``antsdr-e200`` / ``file`` / ``synthetic``) and
                       ``rf_port`` move into ``radio``
``center_freq_hz`` ..  ``rf`` (frequency, level, SNR)
``family`` ..          no counterpart yet: the envelope describes an Open
                       Drone ID *reception* (``odid_raw`` is required) and
                       an RF energy detection carries no ODID bytes, so the
                       mapping needs either a contract extension or a
                       sibling "rf_detection" envelope - open question.
=====================  ==================================================

Raw IQ is **never embedded**: an event that wants to point at samples
carries ``evidence["iq"] = {"sigmf": <stem or path>, "sample_start": int,
"sample_count": int}`` (see :func:`iq_reference`), i.e. a SigMF recording
plus a sample range, exactly like a SigMF annotation.

Units follow the toolkit: Hz, seconds (``t_start_s`` relative to the start
of the capture the event came from), dB relative to full scale 1.0.
Sources: the AERIX contract file above; SigMF annotation semantics
(https://github.com/sigmf/SigMF).  Nothing here is hardware specific.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import IO, TYPE_CHECKING, Any

from ..device.base import StreamInfo
from ..dsp.bursts import Burst

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .sweep import DwellResult, OccupiedSegment

__all__ = [
    "SCHEMA_VERSION",
    "SOURCES",
    "DetectionEvent",
    "JsonlEventWriter",
    "events_from_dwell",
    "iq_reference",
    "iter_jsonl_events",
    "new_event_id",
    "read_jsonl_events",
    "rf_port_from_info",
    "source_from_info",
    "utc_now_iso",
]

SCHEMA_VERSION = "0.1"
SOURCES: tuple[str, ...] = ("antsdr-e200", "file", "synthetic")
"""Allowed ``DetectionEvent.source`` values (the receiver class the samples came from)."""

# Receive-chain labels.  Short and enumerable on purpose: which connector a
# chain comes out on (RX1 = SMA, RX2 = internal u.FL on the E200) is a
# property of the hardware, not of the observation, and lives in
# ``antsdr_toolkit.hardware.E200.rf_port_name``.
_E200_PORTS = {0: "RX1", 1: "RX2"}
_REQUIRED = (
    "sensor_id", "received_at_utc", "center_freq_hz", "f_low_hz", "f_high_hz", "bandwidth_hz",
    "t_start_s", "duration_s", "peak_db", "snr_db", "source", "rf_port", "sample_rate_hz",
)


def utc_now_iso() -> str:
    """Current UTC time as RFC 3339 with millisecond precision and a ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_event_id() -> str:
    """A fresh UUID4 string (the contract prefers UUIDv7; see the module docstring)."""
    return str(uuid.uuid4())


def _port_name(channel: int) -> str:
    return _E200_PORTS.get(channel, f"ch{channel}")


def rf_port_from_info(info: StreamInfo) -> str:
    """``"RX1"`` / ``"RX2"`` (joined with ``+``) for E200 channels, ``"chN"`` otherwise."""
    return "+".join(_port_name(int(c)) for c in info.rx_channels)


def source_from_info(info: StreamInfo) -> str:
    """Map ``StreamInfo.hardware`` onto :data:`SOURCES` (unknown hardware -> ``"file"``)."""
    hw = (info.hardware or "").lower()
    if hw in SOURCES:
        return hw
    if "e200" in hw or "antsdr" in hw:
        return "antsdr-e200"
    return "file"


def iq_reference(sigmf: str | os.PathLike, sample_start: int, sample_count: int) -> dict[str, Any]:
    """Evidence entry pointing at IQ samples in a SigMF recording (never embedded)."""
    if int(sample_start) < 0 or int(sample_count) < 0:
        raise ValueError("sample_start and sample_count must be >= 0")
    return {"sigmf": os.fspath(sigmf), "sample_start": int(sample_start),
            "sample_count": int(sample_count)}


@dataclass
class DetectionEvent:
    """One detection; see the module docstring for the schema and its status.

    ``family`` is the waveform family guessed by a classifier (``None`` when
    unclassified) with ``family_confidence`` in ``[0, 1]``; ``evidence`` is a
    free-form JSON-serialisable dict of the supporting measurements.
    """

    sensor_id: str
    received_at_utc: str
    center_freq_hz: float
    f_low_hz: float
    f_high_hz: float
    bandwidth_hz: float
    t_start_s: float
    duration_s: float
    peak_db: float
    snr_db: float
    source: str
    rf_port: str
    sample_rate_hz: float
    family: str | None = None
    family_confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=new_event_id)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("center_freq_hz", "f_low_hz", "f_high_hz", "bandwidth_hz", "t_start_s",
                     "duration_s", "peak_db", "snr_db", "sample_rate_hz", "family_confidence"):
            setattr(self, name, float(getattr(self, name)))
        self.sensor_id = str(self.sensor_id)
        self.received_at_utc = str(self.received_at_utc)
        self.source = str(self.source)
        self.rf_port = str(self.rf_port)
        self.event_id = str(self.event_id)
        self.schema_version = str(self.schema_version)
        self.evidence = dict(self.evidence)
        if self.family is not None:
            self.family = str(self.family)
        if not self.sensor_id:
            raise ValueError("sensor_id must not be empty")
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")
        if self.f_low_hz > self.f_high_hz:
            raise ValueError("f_low_hz must not exceed f_high_hz")
        if self.bandwidth_hz < 0.0 or self.duration_s < 0.0 or self.sample_rate_hz <= 0.0:
            raise ValueError("bandwidth_hz/duration_s must be >= 0 and sample_rate_hz > 0")
        if not 0.0 <= self.family_confidence <= 1.0:
            raise ValueError("family_confidence must lie in [0, 1]")
        try:
            uuid.UUID(self.event_id)
        except ValueError as exc:
            raise ValueError(f"event_id must be a UUID string, got {self.event_id!r}") from exc
        json.dumps(self.evidence)  # fail early on non-serialisable evidence

    # -- serialisation ---------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Plain dict with ``schema_version`` and ``event_id`` first."""
        d = dataclasses.asdict(self)
        ordered = {"schema_version": d.pop("schema_version"), "event_id": d.pop("event_id")}
        ordered.update(d)
        return ordered

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DetectionEvent:
        """Build from a dict; unknown keys are ignored (forward compatibility)."""
        missing = [k for k in _REQUIRED if k not in data]
        if missing:
            raise ValueError(f"event dict lacks required keys: {missing}")
        version = str(data.get("schema_version", SCHEMA_VERSION))
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ValueError(f"unsupported event schema_version {version!r}")
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    @classmethod
    def from_json(cls, text: str) -> DetectionEvent:
        return cls.from_dict(json.loads(text))

    # -- constructors from toolkit objects -------------------------------------
    @classmethod
    def from_burst(
        cls,
        burst: Burst,
        *,
        sensor_id: str,
        source: str,
        rf_port: str,
        sample_rate_hz: float,
        received_at_utc: str | None = None,
        family: str | None = None,
        family_confidence: float = 0.0,
        evidence: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> DetectionEvent:
        """Wrap a detected :class:`~antsdr_toolkit.dsp.bursts.Burst`."""
        ev = dict(evidence or {})
        ev.setdefault("kind", "burst")
        ev.setdefault("mean_db", float(burst.mean_db))
        return cls(
            sensor_id=sensor_id,
            received_at_utc=received_at_utc or utc_now_iso(),
            center_freq_hz=burst.center_freq_hz,
            f_low_hz=burst.f_low_hz,
            f_high_hz=burst.f_high_hz,
            bandwidth_hz=burst.bandwidth_hz,
            t_start_s=burst.t_start_s,
            duration_s=burst.duration_s,
            peak_db=burst.peak_db,
            snr_db=burst.snr_db,
            source=source,
            rf_port=rf_port,
            sample_rate_hz=sample_rate_hz,
            family=family,
            family_confidence=family_confidence,
            evidence=ev,
            event_id=event_id or new_event_id(),
        )

    @classmethod
    def from_segment(
        cls,
        segment: OccupiedSegment,
        *,
        t_start_s: float,
        duration_s: float,
        sensor_id: str,
        source: str,
        rf_port: str,
        sample_rate_hz: float,
        received_at_utc: str | None = None,
        evidence: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> DetectionEvent:
        """Wrap an :class:`~.sweep.OccupiedSegment` (time = the whole dwell)."""
        ev = dict(evidence or {})
        ev.setdefault("kind", "occupancy")
        f_low, f_high, peak_db, snr_db = segment
        return cls(
            sensor_id=sensor_id,
            received_at_utc=received_at_utc or utc_now_iso(),
            center_freq_hz=0.5 * (f_low + f_high),
            f_low_hz=f_low,
            f_high_hz=f_high,
            bandwidth_hz=f_high - f_low,
            t_start_s=t_start_s,
            duration_s=duration_s,
            peak_db=peak_db,
            snr_db=snr_db,
            source=source,
            rf_port=rf_port,
            sample_rate_hz=sample_rate_hz,
            evidence=ev,
            event_id=event_id or new_event_id(),
        )


def _wall_to_utc(t_wall_s: float) -> str:
    return (datetime.fromtimestamp(float(t_wall_s), tz=timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def events_from_dwell(
    result: DwellResult,
    *,
    sensor_id: str,
    source: str,
    rf_port: str,
    received_at_utc: str | None = None,
    include_occupancy: bool = False,
    iq: dict[str, Any] | None = None,
    families: Sequence[tuple[str, float]] = (),
) -> list[DetectionEvent]:
    """One event per detected burst (and per occupied segment when requested).

    ``received_at_utc`` defaults to the dwell's wall-clock capture start
    (``t_wall_s``, which is 0 for sources without a clock - then "now" is
    used).  ``iq`` is an :func:`iq_reference` dict attached to every event;
    ``families`` (``(name, confidence)`` pairs, best first) label all events
    of the dwell with the top family - a dwell-level placeholder until a
    per-burst classifier exists.
    """
    if received_at_utc is None:
        received_at_utc = _wall_to_utc(result.t_wall_s) if result.t_wall_s > 0 else utc_now_iso()
    family, confidence = (families[0][0], float(families[0][1])) if families else (None, 0.0)
    base_evidence: dict[str, Any] = {
        "dwell_center_freq_hz": result.center_freq_hz,
        "dwell_span_hz": result.span_hz,
        "dwell_duration_s": result.duration_s,
        "noise_floor_db": result.noise_floor_db,
        "kurtosis": result.kurtosis,
        "activity_score": result.activity_score,
        "n_bursts": len(result.bursts),
        "features": result.features.to_dict(),
    }
    if iq is not None:
        base_evidence["iq"] = dict(iq)
    if families:
        base_evidence["families"] = [[str(n), float(c)] for n, c in families]
    events = [
        DetectionEvent.from_burst(
            b, sensor_id=sensor_id, source=source, rf_port=rf_port,
            sample_rate_hz=result.sample_rate_hz, received_at_utc=received_at_utc,
            family=family, family_confidence=confidence, evidence=base_evidence,
        )
        for b in result.bursts
    ]
    if include_occupancy:
        events.extend(
            DetectionEvent.from_segment(
                seg, t_start_s=0.0, duration_s=result.duration_s, sensor_id=sensor_id,
                source=source, rf_port=rf_port, sample_rate_hz=result.sample_rate_hz,
                received_at_utc=received_at_utc, evidence=base_evidence,
            )
            for seg in result.occupancy
        )
    return events


# --------------------------------------------------------------------------- JSON Lines
class JsonlEventWriter:
    """Append :class:`DetectionEvent` records to a JSON Lines file (one event per line).

    Opens lazily on the first write, flushes after every line (a crash loses
    at most the line being written) and is a context manager.
    """

    def __init__(self, path: str | os.PathLike, *, append: bool = True) -> None:
        self.path = pathlib.Path(path)
        self._mode = "a" if append else "w"
        self._fh: IO[str] | None = None
        self.count = 0

    def _open(self) -> IO[str]:
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, self._mode, encoding="utf-8")  # noqa: SIM115 - closed in close()
        return self._fh

    def write(self, event: DetectionEvent) -> None:
        fh = self._open()
        fh.write(event.to_json())
        fh.write("\n")
        fh.flush()
        self.count += 1

    def write_many(self, events: Iterable[DetectionEvent]) -> int:
        n = 0
        for ev in events:
            self.write(ev)
            n += 1
        return n

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> JsonlEventWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def iter_jsonl_events(path: str | os.PathLike) -> Iterator[DetectionEvent]:
    """Yield the events of a JSON Lines file, skipping blank lines."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield DetectionEvent.from_json(line)


def read_jsonl_events(path: str | os.PathLike) -> list[DetectionEvent]:
    return list(iter_jsonl_events(path))
