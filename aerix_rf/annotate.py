"""``aerix-rf annotate`` -- apply an operator timeline to a recorded session.

Implements the timeline pass of ``docs/field/positives-protocol.md``: an
operator logs each interval transition (aircraft off/on, controller
linked, Wi-Fi confuser, ...) to a plain-text ``timeline.txt`` during a
capture. This module turns that timeline into a per-window operator-truth
label file, ``annotations.json``, next to the session's own
``session.json``.

Timeline file format
---------------------
Optional first content line::

    TZ: UTC        # or: TZ: local

(default ``UTC``, matching ``session.json``'s own ``started_at``, which is
always UTC -- see ``aerix_rf.session.store._utc_iso``). Every following
line marks the START of one interval::

    HH:MM:SS <interval-id> <free note...>

and lasts until the next line (or the session's end). ``interval-id`` is
one of the protocol's fixed ids (``off-baseline``, ``rc-only``, ``on-near``,
``on-mid``, ``on-far``, ``on-wifi``, ``off-final``, ``gap``) or any
free-form id the operator chooses. Blank lines and lines starting with
``#`` are ignored. Only a time-of-day is given (no date): lines are
anchored to the session's own start date and rolled forward a calendar day
whenever a line's wall-clock time would otherwise be earlier than the
previous line's (so a timeline that crosses local midnight still produces
a monotonic interval sequence).

Label taxonomy choices (see handback for rationale)
----------------------------------------------------
- ``off-*`` / ``gap`` -> ``EmitterClass.BACKGROUND``, ``Activity.OFF``.
- ``rc-only`` -> ``EmitterClass.DRONE_LINK`` /
  ``LinkRole.UPLINK_CONTROL`` (the taxonomy has no separate "controller
  only, no airframe" emitter class; this is the closest bounded value),
  aircraft absent so ``Activity.POWERED_IDLE``.
- ``on-*`` (``on-near``/``on-mid``/``on-far``/``on-wifi``) ->
  ``EmitterClass.DRONE_LINK`` with ``manufacturer``/``model``/
  ``individual_id`` taken from ``session.json['test']`` when present, else
  ``"unknown"``. There is no dedicated taxonomy field for the O2/O3/O4
  link-generation distinction the protocol table calls out; it is not
  fabricated into ``link_family`` -- record it in the timeline's free note
  instead.
- any other (free-form) id -> ``EmitterClass.UNKNOWN``: the operator's
  timeline is still truth about *when* something happened, but this module
  must not guess an emitter class the protocol vocabulary doesn't define.

Every window in the ``annotations.json`` output that comes from a
recognised timeline interval is evidence level 5 (operator truth); this
module raises rather than guessing if any session window falls before the
timeline's first interval (an operator's timeline is expected to start at
or before session start -- a window with no covering interval means the
timeline is incomplete, not that it is silently background).

Determinism / idempotency: this module never reads the wall clock. Given
the same ``session.json`` + ``timeline.txt``, ``annotate_session`` always
returns byte-identical output, and re-running the CLI overwrites
``annotations.json`` with the same content.
"""

from __future__ import annotations

import bisect
import json
import re
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .datasets.spec import (
    Activity,
    EmitterClass,
    EvidenceLevel,
    LabelInstance,
    LabelSource,
    LinkFamily,
    LinkRole,
)

SCHEMA_VERSION = 1
TRANSITION_GUARD_S = 5.0
ANNOTATIONS_FILENAME = "annotations.json"

_TZ_LINE_RE = re.compile(r"^TZ:\s*(UTC|local)\s*$", re.IGNORECASE)
_LINE_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+(\S+)(?:\s+(.*))?$")


def _parse_iso_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TimelineError(ValueError):
    """Raised for a malformed timeline file or a session/timeline mismatch."""


# --------------------------------------------------------------------------
# Timeline parsing
# --------------------------------------------------------------------------


def _parse_timeline_text(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Returns ``(tz_mode, [(hms, interval_id, note), ...])`` in file order."""

    tz_mode = "UTC"
    events: list[tuple[str, str, str]] = []
    seen_first_content_line = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not seen_first_content_line:
            seen_first_content_line = True
            m_tz = _TZ_LINE_RE.match(line)
            if m_tz:
                tz_mode = m_tz.group(1).upper()
                continue
        m = _LINE_RE.match(line)
        if not m:
            raise TimelineError(f"timeline: cannot parse line: {raw_line!r}")
        hms, interval_id, note = m.group(1), m.group(2), (m.group(3) or "").strip()
        events.append((hms, interval_id, note))
    if not events:
        raise TimelineError("timeline: no interval lines found")
    return tz_mode, events


def _events_to_utc(
    events: list[tuple[str, str, str]], *, session_start_utc: datetime, tz_mode: str
) -> list[tuple[datetime, str, str]]:
    """Anchors each ``HH:MM:SS`` line to a calendar date (the session's own
    start date, in ``tz_mode``), rolling the date forward whenever a line
    would otherwise be earlier than the previous one -- so a timeline that
    crosses local midnight still comes out monotonic."""

    base_date: date = (
        session_start_utc.date() if tz_mode == "UTC" else session_start_utc.astimezone().date()
    )
    day_offset = 0
    prev: Optional[datetime] = None
    out: list[tuple[datetime, str, str]] = []
    for hms, interval_id, note in events:
        h, m, s = (int(x) for x in hms.split(":"))
        while True:
            naive = datetime.combine(base_date + timedelta(days=day_offset), dt_time(h, m, s))
            candidate = (
                naive.replace(tzinfo=timezone.utc) if tz_mode == "UTC" else naive.astimezone(timezone.utc)
            )
            if prev is not None and candidate < prev:
                day_offset += 1
                continue
            break
        prev = candidate
        out.append((candidate, interval_id, note))
    return out


# --------------------------------------------------------------------------
# Interval id -> LabelInstance
# --------------------------------------------------------------------------


def _is_background_id(interval_id: str) -> bool:
    return interval_id == "gap" or interval_id.startswith("off-")


def label_for_interval(interval_id: str, test_block: dict) -> LabelInstance:
    """Map one protocol interval id to a :class:`LabelInstance`. See the
    module docstring for the taxonomy choices."""

    if _is_background_id(interval_id):
        return LabelInstance(
            emitter_class=EmitterClass.BACKGROUND,
            link_family=LinkFamily.NOT_APPLICABLE,
            link_role=LinkRole.NOT_APPLICABLE,
            activity=Activity.OFF,
            evidence_level=EvidenceLevel.OPERATOR_TRUTH,
            label_source=LabelSource.OPERATOR_GROUND_TRUTH,
        )
    if interval_id == "rc-only":
        return LabelInstance(
            emitter_class=EmitterClass.DRONE_LINK,
            link_family=LinkFamily.UNKNOWN,
            link_role=LinkRole.UPLINK_CONTROL,
            manufacturer=test_block.get("drone_manufacturer") or "unknown",
            model=test_block.get("drone_model") or "unknown",
            individual_id="unknown",
            activity=Activity.POWERED_IDLE,
            evidence_level=EvidenceLevel.OPERATOR_TRUTH,
            label_source=LabelSource.OPERATOR_GROUND_TRUTH,
        )
    if interval_id.startswith("on-"):
        return LabelInstance(
            emitter_class=EmitterClass.DRONE_LINK,
            link_family=LinkFamily.UNKNOWN,
            link_role=LinkRole.UNKNOWN,
            manufacturer=test_block.get("drone_manufacturer") or "unknown",
            model=test_block.get("drone_model") or "unknown",
            individual_id=test_block.get("drone_serial") or "unknown",
            activity=Activity.UNKNOWN,
            evidence_level=EvidenceLevel.OPERATOR_TRUTH,
            label_source=LabelSource.OPERATOR_GROUND_TRUTH,
        )
    # Free-form id: operator truth about timing only, never a guessed class.
    return LabelInstance(
        emitter_class=EmitterClass.UNKNOWN,
        evidence_level=EvidenceLevel.OPERATOR_TRUTH,
        label_source=LabelSource.OPERATOR_GROUND_TRUTH,
    )


# --------------------------------------------------------------------------
# Session <-> timeline
# --------------------------------------------------------------------------


def annotate_session(session_dir: Path, timeline_path: Path) -> dict[str, Any]:
    """Builds the ``annotations.json`` payload for one session directory.
    Pure function of the two input files' contents -- never touches the
    wall clock, so re-running with the same inputs is idempotent."""

    session_dir = Path(session_dir)
    session_json_path = session_dir / "session.json"
    meta = json.loads(session_json_path.read_text(encoding="utf-8"))
    session_id = str(meta.get("session_id") or session_dir.name)
    test_block = dict(meta.get("test") or {})

    started_at_raw = meta.get("started_at")
    if not started_at_raw:
        raise TimelineError(f"{session_json_path}: no 'started_at' field; cannot anchor timeline")
    session_start_utc = _parse_iso_utc(started_at_raw)

    files = meta.get("files") or []
    windows_raw: list[tuple[int, Optional[str], float]] = []
    for idx, entry in enumerate(files):
        captured_at = entry.get("captured_at")
        if captured_at is None:
            raise TimelineError(
                f"{session_json_path}: files[{idx}] has no 'captured_at'; "
                "annotate needs a per-window timestamp"
            )
        windows_raw.append((idx, entry.get("file"), float(captured_at)))
    windows_raw.sort(key=lambda t: t[2])

    tz_mode, raw_events = _parse_timeline_text(Path(timeline_path).read_text(encoding="utf-8"))
    events_utc = _events_to_utc(raw_events, session_start_utc=session_start_utc, tz_mode=tz_mode)

    if windows_raw and windows_raw[0][2] < events_utc[0][0].timestamp():
        first_window_iso = _iso(datetime.fromtimestamp(windows_raw[0][2], tz=timezone.utc))
        raise TimelineError(
            f"{timeline_path}: first interval {events_utc[0][1]!r} starts at "
            f"{_iso(events_utc[0][0])}, after this session's first window "
            f"({first_window_iso}); the timeline must cover every window"
        )

    ended_at_raw = meta.get("ended_at")
    if ended_at_raw:
        session_end_utc = _parse_iso_utc(ended_at_raw)
    elif windows_raw:
        session_end_utc = datetime.fromtimestamp(windows_raw[-1][2], tz=timezone.utc)
    else:
        session_end_utc = events_utc[-1][0]
    if session_end_utc < events_utc[-1][0]:
        session_end_utc = events_utc[-1][0]

    intervals_out = []
    for i, (start, interval_id, note) in enumerate(events_utc):
        end = events_utc[i + 1][0] if i + 1 < len(events_utc) else session_end_utc
        intervals_out.append(
            {"id": interval_id, "start_iso": _iso(start), "end_iso": _iso(end), "note": note}
        )

    interval_starts = [e[0] for e in events_utc]
    label_cache: dict[str, LabelInstance] = {}
    windows_out = []
    for idx, rel, captured_at in windows_raw:
        wt = datetime.fromtimestamp(captured_at, tz=timezone.utc)
        pos = bisect.bisect_right(interval_starts, wt) - 1
        interval_id = events_utc[pos][1]
        transition = any(
            abs((wt - s).total_seconds()) <= TRANSITION_GUARD_S for s in interval_starts
        )
        label = label_cache.get(interval_id)
        if label is None:
            label = label_for_interval(interval_id, test_block)
            label_cache[interval_id] = label
        windows_out.append(
            {
                "index": idx,
                "file": rel,
                "captured_at": captured_at,
                "interval_id": interval_id,
                "label": label.model_dump(mode="json"),
                # Fixed provenance tag for the whole annotation pass (every
                # window annotate.py emits is operator truth by
                # construction) -- distinct from the nested `label.
                # label_source`, which uses spec.py's LabelSource enum
                # (`operator_ground_truth`) for downstream consumers.
                "evidence_level": int(EvidenceLevel.OPERATOR_TRUTH),
                "label_source": "operator_truth",
                "transition": transition,
            }
        )

    return {
        "schema": SCHEMA_VERSION,
        "tz": tz_mode,
        "session_id": session_id,
        "intervals": intervals_out,
        "windows": windows_out,
    }


def write_annotations(session_dir: Path, annotations: dict[str, Any]) -> Path:
    out_path = Path(session_dir) / ANNOTATIONS_FILENAME
    out_path.write_text(json.dumps(annotations, indent=2) + "\n", encoding="utf-8")
    return out_path


def format_summary(annotations: dict[str, Any]) -> str:
    """Human-readable ``windows per interval`` / transition-count table."""

    counts: dict[str, int] = {}
    transitions_by_interval: dict[str, int] = {}
    for w in annotations["windows"]:
        iid = w["interval_id"]
        counts[iid] = counts.get(iid, 0) + 1
        if w["transition"]:
            transitions_by_interval[iid] = transitions_by_interval.get(iid, 0) + 1

    order = [itv["id"] for itv in annotations["intervals"]]
    seen = set()
    ordered_ids = [i for i in order if not (i in seen or seen.add(i))]

    lines = [f"{'interval':<16} {'windows':>8} {'transition':>11}"]
    total_windows = 0
    total_transitions = 0
    for iid in ordered_ids:
        n = counts.get(iid, 0)
        t = transitions_by_interval.get(iid, 0)
        total_windows += n
        total_transitions += t
        lines.append(f"{iid:<16} {n:>8} {t:>11}")
    lines.append(f"{'TOTAL':<16} {total_windows:>8} {total_transitions:>11}")
    return "\n".join(lines)
