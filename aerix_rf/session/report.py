"""Markdown session summary (Milestone 1.6 "session summary generator").

``build_summary(session)`` renders ``summary.md`` from session.json,
detections.jsonl and decode.jsonl. Everything is optional: a partial or
crashed session must still produce a report, so missing fields render as
``n/a`` / ``0`` and never raise.

Record fields this module reads
-------------------------------

detections.jsonl (one dict per detector/classifier output; caller-built):

    ts                 ISO time (added by Session.log_detection if missing)
    captured_at        epoch seconds of the window start (optional)
    center_freq_hz     tuned centre (Hz)      -- also accepts center_freq_mhz
    peak_freq_hz       strongest bin (Hz)     -- also accepts peak_freq_mhz / freq_mhz
    score              detector score 0..1
    snr_db             SNR / relative power
    occupied_bw_mhz    occupied bandwidth     -- also accepts bw_mhz
    burst_count        bursts in the window
    cadence_ms         inter-burst period, if periodic (null otherwise)
    plausible          bool, score/SNR above threshold
    morphology         Stage-1 shape label (e.g. ofdm_burst / wideband / narrowband / noise)
    class              Stage-2 class label (also accepts signature_class)
    confidence         Stage-2 confidence 0..1
    class_source       "model" | "rules" | "fallback" ...
    decode_state       protocol-decode state string (optional)
    capture_health     dict as produced by IQWindow.health():
                         expected_samples, received_samples,
                         dropped_or_missing_samples, overflow_count,
                         capture_complete, source_backend

decode.jsonl (one dict per protocol-decode attempt):

    ts, captured_at    as above
    level              best validation level reached: "A" | "B" | "C" | "D"
                       (A sync candidate, B OFDM/descramble ok, C Turbo+CRC24A
                       valid, D parsed serial/position matches known truth)
    crc_ok             bool
    serial             decoded serial (if CRC-valid)
    drone_lat, drone_lon
    drone_model / protocol / error   free text (optional)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from .store import Session

LEVEL_ORDER = {"A": 1, "B": 2, "C": 3, "D": 4}
LEVEL_TEXT = {
    "A": "A - sync candidate",
    "B": "B - OFDM/descramble ok",
    "C": "C - Turbo + CRC24A valid",
    "D": "D - parsed serial/position agrees with known test truth",
}


# --- small helpers --------------------------------------------------------------

def _f(x: Any) -> float | None:
    try:
        if x is None or isinstance(x, bool):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _fmt(x: Any, nd: int = 2, unit: str = "") -> str:
    v = _f(x)
    if v is None:
        return "n/a" if x in (None, "") else str(x)
    return f"{v:.{nd}f}{unit}"


def _mhz(hz: Any) -> str:
    v = _f(hz)
    return "n/a" if v is None else f"{v / 1e6:.3f} MHz"


def _str(x: Any) -> str:
    return "n/a" if x is None or x == "" else str(x)


def _table(headers: list[str], rows: Iterable[Iterable[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return out


def _peak_hz(rec: dict[str, Any]) -> float | None:
    for k, scale in (("peak_freq_hz", 1.0), ("peak_freq_mhz", 1e6), ("freq_mhz", 1e6)):
        v = _f(rec.get(k))
        if v is not None:
            return v * scale
    return None


def _bw_mhz(rec: dict[str, Any]) -> float | None:
    for k in ("occupied_bw_mhz", "bw_mhz"):
        v = _f(rec.get(k))
        if v is not None:
            return v
    return None


def _class(rec: dict[str, Any]) -> str | None:
    v = rec.get("class", rec.get("signature_class"))
    return None if v in (None, "") else str(v)


# --- sections -------------------------------------------------------------------

def _header(s: Session) -> list[str]:
    m = s.meta
    g = m.get("gains") or {}
    centre = _mhz(m.get("center_freq_hz")) if m.get("center_freq_hz") is not None else "n/a"
    rng = m.get("scan_range_hz")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        centre += f" (scan {_mhz(rng[0])} - {_mhz(rng[1])})"
    counts = m.get("counts") or {}
    rows = [
        ("Session id", _str(m.get("session_id"))),
        ("Label", _str(s.label)),
        ("Started", _str(m.get("started_at"))),
        ("Ended", _str(m.get("ended_at"))),
        ("Duration", _fmt(m.get("duration_s"), 1, " s")),
        ("Software", f"{_str(m.get('software_version'))} @ git {_str(m.get('software_git_sha'))}"),
        ("Receiver", f"{_str(m.get('receiver_type'))} / serial {_str(m.get('receiver_serial'))}"
                     + (f" / backend {m['receiver_backend']}" if m.get("receiver_backend") else "")),
        ("Sample rate", _mhz(m.get("sample_rate")).replace("MHz", "Msps")),
        ("Centre / scan", centre),
        ("Band", _str(m.get("band"))),
        ("Gains", f"LNA {_str(g.get('lna_gain'))}, VGA {_str(g.get('vga_gain'))}, "
                  f"amp {'on' if g.get('amp') else 'off'}, total {_fmt(g.get('gain_db'), 1, ' dB')}"),
        ("Antenna", _str(m.get("antenna"))),
        ("Location", _str(m.get("location")) if m.get("location") else "n/a"),
        ("Environment notes", _str(m.get("environment_notes"))),
        ("Counts", ", ".join(f"{k} {v}" for k, v in counts.items()) or "n/a"),
    ]
    return [f"# Session summary: {s.label or s.session_id}", "",
            *_table(["Field", "Value"], rows), ""]


def _test_block(s: Session) -> list[str]:
    t = s.meta.get("test") or {}
    lines = ["## Test condition (operator ground truth, verbatim)", "",
             "_These labels describe the test set-up as entered by the operator. They are "
             "not classifier or decoder output and do not attribute individual emitters._", ""]
    if not t:
        return lines + ["(no test block recorded)", ""]
    lines += _table(["Key", "Value"], [(k, _str(v)) for k, v in t.items()])
    return lines + [""]


def _health(s: Session, dets: list[dict[str, Any]]) -> list[str]:
    files = s.files
    n_files = len(files)
    n_complete = sum(1 for f in files if f.get("complete", True))
    dropped_files = sum(int(f.get("dropped_samples") or 0) for f in files)
    total_s = sum(float(f.get("duration_s") or 0.0) for f in files)

    # From the detection records (each carries capture_health from IQWindow.health()).
    hs = [d.get("capture_health") for d in dets if isinstance(d.get("capture_health"), dict)]
    win = len(hs)
    win_complete = sum(1 for h in hs if h.get("capture_complete", True))
    dropped = sum(int(h.get("dropped_or_missing_samples") or 0) for h in hs)
    overflow = max((int(h.get("overflow_count") or 0) for h in hs), default=0)   # cumulative counter
    gap = sum(int(h.get("gap_before_samples") or 0) for h in hs)
    ratios = [float(h["stream_rate_ratio"]) for h in hs if h.get("stream_rate_ratio") is not None]
    backends = Counter(str(h.get("source_backend")) for h in hs if h.get("source_backend"))

    rows = [
        ("Detection windows (records with capture_health)", win),
        ("  complete / incomplete", f"{win_complete} / {win - win_complete}"),
        ("  dropped or missing samples (sum)", dropped),
        ("  overflow count (cumulative, final)", overflow),
        ("  stream lost between windows (sum)", f"{gap} samples"),
        ("  stream rate ratio (min)", f"{min(ratios):.4f}" if ratios else "n/a"),
        ("  source backends", ", ".join(f"{k} x{v}" for k, v in backends.items()) or "n/a"),
        ("Recorded IQ files", n_files),
        ("  complete / incomplete", f"{n_complete} / {n_files - n_complete}"),
        ("  dropped samples in files (sum)", dropped_files),
        ("  recorded duration", f"{total_s:.2f} s"),
    ]
    return ["## Capture health", "", *_table(["Metric", "Value"], rows), ""]


def _file_table(s: Session) -> list[str]:
    files = s.files
    lines = ["## Recorded IQ files", ""]
    if not files:
        return lines + ["(no IQ recorded)", ""]
    rows = []
    for f in files:
        rows.append((f.get("file", "?"),
                     _fmt(f.get("duration_s"), 3, " s"),
                     f"{int(f.get('sample_count') or 0):,}",
                     _mhz(f.get("center_freq_hz")),
                     _mhz(f.get("sample_rate")).replace("MHz", "Msps"),
                     str(f.get("sha256", ""))[:12],
                     "yes" if f.get("complete", True) else "NO",
                     _str(f.get("dropped_samples"))))
    return lines + _table(["File", "Duration", "Samples", "Centre", "Rate", "sha256", "Complete", "Dropped"], rows) + [""]


def _detections(dets: list[dict[str, Any]]) -> list[str]:
    lines = ["## Detections (detections.jsonl)", ""]
    n = len(dets)
    if n == 0:
        return lines + ["No detection records.", ""]

    plausible = sum(1 for d in dets if d.get("plausible") is True)
    morph = Counter(_str(d.get("morphology")) for d in dets)
    cls_conf: dict[str, list[float]] = defaultdict(list)
    cls_n: Counter = Counter()
    sources: Counter = Counter()
    for d in dets:
        c = _class(d)
        if c is not None:
            cls_n[c] += 1
            v = _f(d.get("confidence"))
            if v is not None:
                cls_conf[c].append(v)
        if d.get("class_source") not in (None, ""):
            sources[str(d["class_source"])] += 1

    peaks = Counter()
    for d in dets:
        p = _peak_hz(d)
        if p is not None:
            peaks[round(p / 1e6)] += 1
    cad = [v for v in (_f(d.get("cadence_ms")) for d in dets) if v is not None]
    bursts = [v for v in (_f(d.get("burst_count")) for d in dets) if v is not None]
    scores = [v for v in (_f(d.get("score")) for d in dets) if v is not None]
    snrs = [v for v in (_f(d.get("snr_db")) for d in dets) if v is not None]
    bws = [v for v in (_bw_mhz(d) for d in dets) if v is not None]
    dstate = Counter(str(d["decode_state"]) for d in dets if d.get("decode_state") not in (None, ""))

    lines += [f"- Records: **{n}**",
              f"- Plausible (`plausible: true`): **{plausible}** ({plausible / n:.0%})",
              f"- Max score: {_fmt(max(scores), 3) if scores else 'n/a'}; "
              f"mean score: {_fmt(mean(scores), 3) if scores else 'n/a'}",
              f"- Max SNR: {_fmt(max(snrs), 1, ' dB') if snrs else 'n/a'}; "
              f"mean SNR: {_fmt(mean(snrs), 1, ' dB') if snrs else 'n/a'}",
              f"- Occupied bandwidth: median {_fmt(median(bws), 1, ' MHz') if bws else 'n/a'}, "
              f"max {_fmt(max(bws), 1, ' MHz') if bws else 'n/a'}",
              ""]

    lines += ["### Stage-1 morphology", "",
              *_table(["Morphology", "Count"], sorted(morph.items(), key=lambda kv: -kv[1])), ""]

    lines += ["### Stage-2 class", ""]
    if cls_n:
        rows = []
        for c, k in sorted(cls_n.items(), key=lambda kv: -kv[1]):
            conf = cls_conf.get(c) or []
            rows.append((c, k, _fmt(mean(conf), 3) if conf else "n/a", len(conf)))
        lines += _table(["Class", "Count", "Mean confidence", "With confidence"], rows)
    else:
        lines.append("(no class labels)")
    lines += ["", "Class sources seen: " + (", ".join(f"`{k}` x{v}" for k, v in sources.most_common()) or "n/a"), ""]

    lines += ["### Top peak frequencies (1 MHz bins)", ""]
    if peaks:
        lines += _table(["Peak (MHz)", "Windows"], [(f"{k}", v) for k, v in peaks.most_common(5)])
    else:
        lines.append("(no peak frequencies recorded)")
    lines.append("")

    lines += ["### Burst / cadence", ""]
    if cad:
        lines += [f"- Windows with a periodic cadence: {len(cad)} / {n}",
                  f"- Cadence ms: min {min(cad):.1f}, median {median(cad):.1f}, max {max(cad):.1f}"]
    else:
        lines.append("- No periodic cadence reported.")
    if bursts:
        lines.append(f"- Bursts per window: mean {mean(bursts):.1f}, max {int(max(bursts))}")
    if dstate:
        lines.append("- Protocol-decode state seen: " + ", ".join(f"`{k}` x{v}" for k, v in dstate.most_common()))
    return lines + [""]


def _decodes(decs: list[dict[str, Any]]) -> list[str]:
    lines = ["## Protocol decode (decode.jsonl)", ""]
    if not decs:
        return lines + ["No decode attempts recorded.", ""]
    levels = Counter(str(d.get("level")).upper() for d in decs if d.get("level") not in (None, ""))
    best = max((lv for lv in levels if lv in LEVEL_ORDER), key=lambda lv: LEVEL_ORDER[lv], default=None)
    crc = [d for d in decs if d.get("crc_ok") is True]
    lines += [f"- Attempts: **{len(decs)}**",
              f"- Best level reached: **{LEVEL_TEXT.get(best, best) if best else 'none'}**",
              "- Level histogram: " + (", ".join(f"{lv} x{levels[lv]}" for lv in sorted(levels)) or "n/a"),
              f"- CRC-valid decodes: **{len(crc)}**",
              ""]
    if best in ("C", "D") or crc:
        lines.append("_Level C/D reached: this counts as a real decode per the validation hierarchy._")
    else:
        lines.append("_No Level C/D result: no CRC-valid real decode in this session._")
    lines.append("")
    if crc:
        rows = [(_str(d.get("ts")), _str(d.get("serial")), _str(d.get("drone_lat")),
                 _str(d.get("drone_lon")), _str(d.get("level")), _str(d.get("drone_model") or d.get("protocol")))
                for d in crc]
        lines += ["### CRC-valid decodes", "",
                  *_table(["ts", "serial", "lat", "lon", "level", "model/protocol"], rows), ""]
    errs = Counter(str(d["error"]) for d in decs if d.get("error") not in (None, ""))
    if errs:
        lines += ["Errors / failure reasons: " + ", ".join(f"`{k}` x{v}" for k, v in errs.most_common(5)), ""]
    return lines


def _interpretation(s: Session, dets: list[dict[str, Any]], decs: list[dict[str, Any]]) -> list[str]:
    t = s.meta.get("test") or {}
    n = len(dets)
    plausible = sum(1 for d in dets if d.get("plausible") is True)
    crc = sum(1 for d in decs if d.get("crc_ok") is True)
    hs = [d.get("capture_health") for d in dets if isinstance(d.get("capture_health"), dict)]
    incomplete = sum(1 for h in hs if not h.get("capture_complete", True))
    cls = Counter(c for c in (_class(d) for d in dets) if c is not None)
    top = f"most frequent stage-2 class `{cls.most_common(1)[0][0]}`" if cls else "no stage-2 class labels"
    cond = ", ".join(f"{k}={v}" for k, v in t.items()
                     if v not in (None, "") and k in ("drone_model", "drone_state", "controller_state",
                                                       "motors_state", "approx_distance_m")) or "not specified"
    text = (f"This session (`{s.label or s.session_id}`) recorded {len(s.files)} IQ file(s) and "
            f"{n} detection window(s), of which {plausible} were flagged plausible and {incomplete} had "
            f"incomplete capture; {top}; {len(decs)} protocol-decode attempt(s) and {crc} CRC-valid "
            f"decode(s). The operator-entered test condition was: {cond}. That condition is ground "
            "truth about the test set-up only: it does not prove that every RF emitter observed in "
            "these recordings belongs to the test aircraft. Attribution of a specific emitter to the "
            "test drone requires a protocol-confirmed identity (Level C/D decode) or independent "
            "corroboration; RF-classifier output on its own is a signature class, not an identity.")
    return ["## Interpretation", "", text, ""]


# --- public API -----------------------------------------------------------------

def build_summary(session: Session) -> str:
    """Render the Markdown summary for ``session`` (never raises on partial data)."""
    dets = session.detections()
    decs = session.decodes()
    parts: list[str] = []
    parts += _header(session)
    parts += _test_block(session)
    parts += _health(session, dets)
    parts += _file_table(session)
    parts += _detections(dets)
    parts += _decodes(decs)
    parts += _interpretation(session, dets, decs)
    return "\n".join(parts).rstrip() + "\n"


def write_summary(session: Session, name: str = "summary.md") -> Path:
    out = session.path / name
    out.write_text(build_summary(session), encoding="utf-8")
    return out
