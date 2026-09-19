"""Stage-1 T3 false-alarm budget (docs/design/stage1-link-signatures.md S9).

Runs the SAME Stage-1 code path the live pipeline uses
(``aerix_rf.pipeline.process_window`` -> ``aerix_rf.detect.energy.detect``,
which is where T1 burst extraction / T2 raster+cadence live) over every
recorded IQ window of the ANTSDR ambient corpus, and counts how often each
level-1/level-2 label or discount tag fires, plus the session-level cadence
accumulator (``aerix_rf.pipeline.SessionCadenceStore``) result.

IQ is read via ``aerix_rf.session.store.Session.iq_windows()``, which builds
one ``FileIQSource`` per recorded file from the file's own ``session.json``
metadata (sample_rate, iq_format, iq_full_scale) and reads it with
``aerix_rf.sdr.capture._read_cs16`` for cs16 files -- the exact function
``cmd_replay`` uses for the same purpose, so this is not a re-implementation
of the cs16 -> complex64 conversion, it is the one the pipeline already has.

Decode (stage 3) is intentionally OFF here (``decode=False``): the false-alarm
budget is about stage-1 morphology/label counts only, and DroneID decode adds
~10x runtime for no information this script uses.

Usage:
    uv run python bench/stage1_fa_budget.py [--root DIR] [--workers N] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path.home() / "rf-datasets" / "aerix_antsdr_ambient_2026_09_18" / "original"

# Sessions in scope (task spec): the cs8 smoke session and the no-iq soak600
# session are deliberately excluded (no cs16 IQ to walk, or wrong format).
SESSION_NAME_SUBSTR = (
    "t4b1_check",
    "soak10min_b",
    "probe_default",
    "probe_k32_4m",
    "a_iq_default",
    "soak600_k32_4m_iq",
)

LEVEL1_LEVEL2_LABELS = (
    "fhss_1mhz_grid_candidate",
    "fhss_2mhz_grid_candidate",
    "rc_link_family_candidate",
    "hopping_candidate",
    "fixed_channel_burst_candidate",
    "droneid_cadence_candidate",
)
TAGS = ("wifi_beacon_like", "ble_connection_like", "INSUFFICIENT_CHANNELS")
ALL_COUNTED = LEVEL1_LEVEL2_LABELS + TAGS


def _find_sessions(root: Path) -> list[Path]:
    out = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir() or not (sub / "session.json").exists():
            continue
        if any(name in sub.name for name in SESSION_NAME_SUBSTR):
            out.append(sub)
    return out


def _run_one_session(session_path_str: str) -> dict[str, Any]:
    """Runs in a worker process: open the session, walk every recorded IQ
    window through the real pipeline entry point, tally labels/tags."""
    from aerix_rf.config import Config
    from aerix_rf.pipeline import process_window, SessionCadenceStore
    from aerix_rf.session.store import Session

    session_path = Path(session_path_str)
    src = Session.open(session_path)
    cfg = Config.from_env()
    session_cadence = SessionCadenceStore()

    counts = {k: 0 for k in ALL_COUNTED}
    n_windows = 0
    windows_with_any_level2 = 0
    session_droneid_ever = False
    session_final_labels: list[str] = []
    t0 = time.perf_counter()

    for win in src.iq_windows(cfg):
        fr = process_window(win, cfg, decode=False, session_cadence=session_cadence)
        n_windows += 1
        stage1 = getattr(fr.det, "stage1", {}) or {}
        labels = set(stage1.get("labels", []))
        tags = set(stage1.get("tags", []))
        # process_window promotes a session-level droneid_cadence_candidate
        # verdict onto det.morphology/labels for the *current* window only;
        # fold that in too so a session-level fire is never missed here.
        if getattr(fr.det, "morphology", None) == "droneid_cadence_candidate":
            labels.add("droneid_cadence_candidate")
        for lbl in LEVEL1_LEVEL2_LABELS:
            if lbl in labels:
                counts[lbl] += 1
        if "droneid_cadence_candidate" in labels:
            session_droneid_ever = True
        for tag in TAGS:
            if tag in tags:
                counts[tag] += 1
        if labels & set(LEVEL1_LEVEL2_LABELS[:5]):  # excludes droneid_cadence (session-only)
            windows_with_any_level2 += 1

    sres = session_cadence.result()
    if sres is not None:
        session_final_labels = list(sres.labels)
        if "droneid_cadence_candidate" in session_final_labels:
            session_droneid_ever = True

    return {
        "session": session_path.name,
        "n_windows": n_windows,
        "counts": counts,
        "session_droneid_cadence_ever": session_droneid_ever,
        "session_final_cadence_labels": session_final_labels,
        "elapsed_s": time.perf_counter() - t0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=str(Path(__file__).parent / "out" / "stage1_fa_budget.md"))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    root = Path(args.root)
    sessions = _find_sessions(root)
    if not sessions:
        print(f"no matching sessions under {root}")
        return 1
    print(f"{len(sessions)} sessions: {[s.name for s in sessions]}", flush=True)

    results: list[dict[str, Any]] = []
    workers = max(1, min(args.workers, len(sessions), 10))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_one_session, str(s)): s for s in sessions}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001 - surface which session failed
                print(f"FAILED: {s.name}: {exc!r}")
                raise
            results.append(r)
            print(f"done: {r['session']} ({r['n_windows']} windows, {r['elapsed_s']:.1f}s)", flush=True)

    results.sort(key=lambda r: r["session"])

    totals = {k: 0 for k in ALL_COUNTED}
    total_windows = 0
    total_droneid_sessions = 0
    total_level2_hopping_windows = 0
    for r in results:
        total_windows += r["n_windows"]
        for k in ALL_COUNTED:
            totals[k] += r["counts"][k]
        if r["session_droneid_cadence_ever"]:
            total_droneid_sessions += 1
        total_level2_hopping_windows += r["counts"]["hopping_candidate"]

    hopping_pct = 100.0 * totals["hopping_candidate"] / total_windows if total_windows else 0.0

    lines = []
    lines.append("# Stage-1 T3 false-alarm budget (ANTSDR ambient corpus)")
    lines.append("")
    lines.append(f"Root: `{root}`")
    lines.append(f"Sessions: {len(results)}; total windows: {total_windows}")
    lines.append("")
    header = ["session", "windows"] + list(ALL_COUNTED) + ["droneid@session"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for r in results:
        row = [r["session"], str(r["n_windows"])]
        row += [str(r["counts"][k]) for k in ALL_COUNTED]
        row += ["yes" if r["session_droneid_cadence_ever"] else "no"]
        lines.append("| " + " | ".join(row) + " |")
    totals_row = ["TOTAL", str(total_windows)] + [str(totals[k]) for k in ALL_COUNTED] + [str(total_droneid_sessions)]
    lines.append("| " + " | ".join(totals_row) + " |")
    lines.append("")

    lines.append("## Budget verdict (design S9)")
    lines.append("")
    verdict_lines = []
    ok = True

    def check(name: str, cond: bool, detail: str):
        nonlocal ok
        verdict_lines.append(f"- **{name}**: {'PASS' if cond else 'FAIL'} -- {detail}")
        ok = ok and cond

    check("fhss_1mhz_grid_candidate == 0", totals["fhss_1mhz_grid_candidate"] == 0,
          f"{totals['fhss_1mhz_grid_candidate']}/{total_windows}")
    check("fhss_2mhz_grid_candidate == 0", totals["fhss_2mhz_grid_candidate"] == 0,
          f"{totals['fhss_2mhz_grid_candidate']}/{total_windows}")
    check("rc_link_family_candidate <= 1", totals["rc_link_family_candidate"] <= 1,
          f"{totals['rc_link_family_candidate']}/{total_windows}")
    check("droneid_cadence_candidate == 0 (window and session)",
          totals["droneid_cadence_candidate"] == 0 and total_droneid_sessions == 0,
          f"{totals['droneid_cadence_candidate']}/{total_windows} windows, "
          f"{total_droneid_sessions}/{len(results)} sessions")
    check("hopping_candidate <= 5% of windows", hopping_pct <= 5.0,
          f"{totals['hopping_candidate']}/{total_windows} = {hopping_pct:.2f}%")

    lines.extend(verdict_lines)
    lines.append("")
    lines.append(f"**Overall: {'PASS' if ok else 'FAIL -- see per-rule detail above and per-session table'}**")
    lines.append("")
    lines.append("Discount tags (informational, not budgeted): "
                 f"wifi_beacon_like={totals['wifi_beacon_like']}, "
                 f"ble_connection_like={totals['ble_connection_like']}, "
                 f"INSUFFICIENT_CHANNELS={totals['INSUFFICIENT_CHANNELS']}.")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {out_path}")
    print("\n".join(lines))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2))

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
