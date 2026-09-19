"""Tests for `aerix-rf annotate` (aerix_rf.annotate): turning an operator
timeline (docs/field/positives-protocol.md) into a per-window
`annotations.json` next to a recorded session.
"""

from __future__ import annotations

import json
import os
import time as time_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aerix_rf import cli
from aerix_rf.annotate import (
    ANNOTATIONS_FILENAME,
    TimelineError,
    annotate_session,
    format_summary,
    write_annotations,
)
from aerix_rf.datasets.spec import EmitterClass, EvidenceLevel, LabelSource

SESSION_START_ISO = "2026-09-19T06:00:00.000Z"
SESSION_START_TS = datetime.fromisoformat(SESSION_START_ISO.replace("Z", "+00:00")).timestamp()

# Interval boundaries (offsets in seconds from session start) chosen so the
# +/-5 s transition guard band leaves a few genuinely non-transition windows
# in the middle of the (widest) first interval -- see the module docstring
# arithmetic in the handback for how t=6,7,8 were picked.
_BOUNDARIES = {"off-baseline": 0, "rc-only": 14, "on-near": 16, "off-final": 18}


def _write_session(session_dir: Path, *, test_block: dict | None = None) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(20):
        files.append({"file": f"iq/capture_{i:04d}.cs16", "captured_at": SESSION_START_TS + i})
    meta = {
        "schema_version": 2,
        "session_id": "sid-annot-1",
        "label": "positives_24",
        "started_at": SESSION_START_ISO,
        "test": test_block or {},
        "files": files,
    }
    (session_dir / "session.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_timeline(path: Path, *, tz_line: str | None = "TZ: UTC") -> None:
    lines = []
    if tz_line is not None:
        lines.append(tz_line)
    lines += [
        "06:00:00 off-baseline baseline, drones off",
        "06:00:14 rc-only controller linked, no aircraft",
        "06:00:16 on-near drone on, ~2 m",
        "06:00:18 off-final wrap up",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_annotate_session_intervals_and_labels(tmp_path):
    session_dir = tmp_path / "session"
    _write_session(session_dir, test_block={"drone_manufacturer": "DJI", "drone_model": "mavic_3"})
    timeline_path = tmp_path / "timeline.txt"
    _write_timeline(timeline_path)

    out = annotate_session(session_dir, timeline_path)
    assert out["schema"] == 1
    assert out["tz"] == "UTC"
    assert [itv["id"] for itv in out["intervals"]] == ["off-baseline", "rc-only", "on-near", "off-final"]
    assert out["intervals"][0]["start_iso"] == SESSION_START_ISO
    assert out["intervals"][0]["note"] == "baseline, drones off"

    windows = out["windows"]
    assert len(windows) == 20
    by_index = {w["index"]: w for w in windows}

    for i in range(0, 14):
        assert by_index[i]["interval_id"] == "off-baseline"
    for i in range(14, 16):
        assert by_index[i]["interval_id"] == "rc-only"
    for i in range(16, 18):
        assert by_index[i]["interval_id"] == "on-near"
    for i in range(18, 20):
        assert by_index[i]["interval_id"] == "off-final"

    # Every window is evidence level 5 / operator truth at the top level.
    for w in windows:
        assert w["evidence_level"] == int(EvidenceLevel.OPERATOR_TRUTH) == 5
        assert w["label_source"] == "operator_truth"

    # +/-5 s guard band around boundaries {0, 14, 16, 18}: only t=6,7,8 are
    # far enough from every boundary to NOT be a transition window.
    expected_non_transition = {6, 7, 8}
    for i in range(20):
        assert by_index[i]["transition"] == (i not in expected_non_transition), i

    off_label = by_index[0]["label"]
    assert off_label["emitter_class"] == "background"
    assert off_label["activity"] == "off"
    assert off_label["evidence_level"] == 5
    assert off_label["label_source"] == "operator_ground_truth"

    rc_label = by_index[14]["label"]
    assert rc_label["emitter_class"] == "drone_link"
    assert rc_label["link_role"] == "uplink_control"
    assert rc_label["activity"] == "powered_idle"
    assert rc_label["manufacturer"] == "DJI"
    assert rc_label["model"] == "mavic_3"

    on_label = by_index[16]["label"]
    assert on_label["emitter_class"] == "drone_link"
    assert on_label["manufacturer"] == "DJI"
    assert on_label["model"] == "mavic_3"

    final_label = by_index[18]["label"]
    assert final_label["emitter_class"] == "background"


def test_annotate_session_manufacturer_defaults_unknown_without_test_block(tmp_path):
    session_dir = tmp_path / "session"
    _write_session(session_dir, test_block={})
    timeline_path = tmp_path / "timeline.txt"
    _write_timeline(timeline_path)

    out = annotate_session(session_dir, timeline_path)
    on_label = next(w for w in out["windows"] if w["interval_id"] == "on-near")["label"]
    assert on_label["manufacturer"] == "unknown"
    assert on_label["model"] == "unknown"


def test_annotate_session_free_form_interval_id_stays_unknown_class(tmp_path):
    session_dir = tmp_path / "session"
    _write_session(session_dir)
    timeline_path = tmp_path / "timeline.txt"
    timeline_path.write_text(
        "TZ: UTC\n06:00:00 my-weird-id a custom interval\n", encoding="utf-8"
    )
    out = annotate_session(session_dir, timeline_path)
    for w in out["windows"]:
        assert w["interval_id"] == "my-weird-id"
        assert w["label"]["emitter_class"] == "unknown"
        # Still operator truth about *timing*, even though the class is
        # unmapped.
        assert w["evidence_level"] == 5


def test_annotate_session_idempotent(tmp_path):
    session_dir = tmp_path / "session"
    _write_session(session_dir, test_block={"drone_manufacturer": "DJI", "drone_model": "mavic_3"})
    timeline_path = tmp_path / "timeline.txt"
    _write_timeline(timeline_path)

    out1 = annotate_session(session_dir, timeline_path)
    path1 = write_annotations(session_dir, out1)
    text1 = path1.read_text(encoding="utf-8")

    out2 = annotate_session(session_dir, timeline_path)
    assert out2 == out1
    path2 = write_annotations(session_dir, out2)
    text2 = path2.read_text(encoding="utf-8")
    assert text1 == text2
    assert path1 == session_dir / ANNOTATIONS_FILENAME


def test_annotate_session_rejects_window_before_first_interval(tmp_path):
    session_dir = tmp_path / "session"
    _write_session(session_dir)
    timeline_path = tmp_path / "timeline.txt"
    # First interval starts one second after the session's first window.
    timeline_path.write_text("TZ: UTC\n06:00:01 off-baseline late start\n", encoding="utf-8")
    with pytest.raises(TimelineError):
        annotate_session(session_dir, timeline_path)


def test_annotate_session_tz_local_vs_utc(tmp_path, monkeypatch):
    """`TZ: local` timeline lines are interpreted in the system's local
    timezone (fixed to a known non-UTC offset here so the test is
    deterministic regardless of the machine running it) and converted to
    UTC; `TZ: UTC` (or the default) takes the same wall-clock digits as UTC
    directly."""

    if not hasattr(time_mod, "tzset"):
        pytest.skip("time.tzset() not available on this platform")

    monkeypatch.setenv("TZ", "Etc/GMT-2")  # POSIX Etc sign convention: UTC+2, no DST
    time_mod.tzset()
    try:
        session_dir = tmp_path / "session"
        _write_session(session_dir)
        timeline_path = tmp_path / "timeline_local.txt"
        # 06:00:00 local (UTC+2) == 04:00:00 UTC -- before the session's own
        # 06:00:00 UTC start, so re-anchor this session to start later too.
        meta_path = session_dir / "session.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["started_at"] = "2026-09-19T04:00:00.000Z"
        for i, f in enumerate(meta["files"]):
            f["captured_at"] = datetime(2026, 9, 19, 4, 0, 0, tzinfo=timezone.utc).timestamp() + i
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        timeline_path.write_text("TZ: local\n06:00:00 off-baseline local start\n", encoding="utf-8")

        out = annotate_session(session_dir, timeline_path)
        assert out["intervals"][0]["start_iso"] == "2026-09-19T04:00:00.000Z"
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time_mod.tzset()


def test_format_summary_counts_windows_and_transitions(tmp_path):
    session_dir = tmp_path / "session"
    _write_session(session_dir, test_block={"drone_manufacturer": "DJI", "drone_model": "mavic_3"})
    timeline_path = tmp_path / "timeline.txt"
    _write_timeline(timeline_path)
    out = annotate_session(session_dir, timeline_path)
    summary = format_summary(out)
    assert "off-baseline" in summary
    assert "rc-only" in summary
    assert "on-near" in summary
    assert "off-final" in summary
    assert "TOTAL" in summary
    # 14 off-baseline windows, of which 11 are transition windows (all but
    # t=6,7,8).
    assert "off-baseline" in summary and "14" in summary


def test_cli_annotate_help():
    ap = cli.build_parser()
    with pytest.raises(SystemExit) as exc:
        ap.parse_args(["annotate", "--help"])
    assert exc.value.code == 0


def test_cli_annotate_runs_end_to_end(tmp_path, capsys):
    session_dir = tmp_path / "session"
    _write_session(session_dir, test_block={"drone_manufacturer": "DJI", "drone_model": "mavic_3"})
    timeline_path = tmp_path / "timeline.txt"
    _write_timeline(timeline_path)

    rc = cli.main(["annotate", str(session_dir), str(timeline_path)])
    assert rc == 0
    out_path = session_dir / ANNOTATIONS_FILENAME
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload["windows"]) == 20
    captured = capsys.readouterr()
    assert "TOTAL" in captured.out
    assert "annotations:" in captured.out
