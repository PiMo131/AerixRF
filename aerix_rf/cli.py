"""Field-test CLI: baseline / scan / lock / capture / replay / report / info / run.

The HackRF sees ~20 MHz at a time, so finding a drone is an explicit
``scan -> candidate -> lock -> inspect -> rescan`` loop, driven from here:

    aerix-rf info
    aerix-rf baseline --band 2.4 --seconds 30 --out sessions/site-baseline-24
    aerix-rf scan     --band 2.4 --baseline sessions/site-baseline-24.npz
    aerix-rf lock     --center-mhz 2437 --seconds 60 --label drone-a-motors-on
    aerix-rf capture  --center-mhz 2437 --seconds 30 --label drone-a-motors-on
    aerix-rf replay   sessions/2026-09-04_..._drone-a-motors-on
    aerix-rf report   sessions/2026-09-04_..._drone-a-motors-on
    aerix-rf run [--sim]          # the 1 Hz box service (server uplink optional)

``lock`` and ``capture`` both record a self-describing session directory
(session.json / iq / spectrograms / detections.jsonl / decode.jsonl / summary.md).
``lock`` keeps IQ only for plausible windows (plus ``--record-all``); ``capture``
keeps every window. Test-condition flags (--drone-model, --motors-state, ...) are
recorded as ground truth about the *test*, never as claims about every emitter.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from .config import Config
from .pipeline import process_window, FrameResult

log = logging.getLogger("aerix.rf.cli")

DEFAULT_SESSION_ROOT = os.environ.get("AERIX_RF_SESSIONS", "sessions")


# --- helpers -------------------------------------------------------------------

def _cfg_from(args: argparse.Namespace) -> Config:
    cfg = Config.from_env()
    if getattr(args, "sim", False):
        cfg.sim = True
    if getattr(args, "center_mhz", None):
        cfg.center_freq_mhz = float(args.center_mhz)
    if getattr(args, "lna", None) is not None:
        cfg.lna_gain = int(args.lna)
    if getattr(args, "vga", None) is not None:
        cfg.vga_gain = int(args.vga)
    if getattr(args, "amp", False):
        cfg.amp = True
    if getattr(args, "sample_rate", None):
        cfg.sample_rate = float(args.sample_rate)
    return cfg


def _receiver_meta(source, cfg: Config) -> dict:
    caps = source.capabilities
    meta = {"receiver_type": caps.receiver_type, "receiver_serial": getattr(source, "serial", None),
            "backend": type(source).__name__, "sample_rate": cfg.sample_rate,
            "center_freq_hz": cfg.center_freq_mhz * 1e6,
            "lna_gain": cfg.lna_gain, "vga_gain": cfg.vga_gain, "amp": cfg.amp, "gain_db": cfg.gain_db}
    stream = getattr(source, "stream", None)
    if stream is not None and hasattr(stream, "info"):
        meta.update({k: v for k, v in stream.info().items() if k in ("board_id", "firmware")})
    return meta


def _test_meta(args: argparse.Namespace) -> dict:
    return {
        "test_label": args.label,
        "drone_manufacturer": getattr(args, "drone_manufacturer", None),
        "drone_model": getattr(args, "drone_model", None),
        "drone_serial": getattr(args, "drone_serial", None),
        "drone_state": getattr(args, "drone_state", None),
        "controller_state": getattr(args, "controller_state", None),
        "motors_state": getattr(args, "motors_state", None),
        "approx_distance_m": getattr(args, "distance_m", None),
        "antenna": getattr(args, "antenna", None),
        "operator_notes": getattr(args, "notes", None),
    }


def _add_test_flags(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("test-condition metadata (ground truth about the TEST, not attribution)")
    g.add_argument("--label", default="unlabelled", help="short test label, e.g. drone-a-motors-on")
    g.add_argument("--drone-manufacturer", default=None)
    g.add_argument("--drone-model", default=None)
    g.add_argument("--drone-serial", default=None, help="only if you intentionally want it recorded")
    g.add_argument("--drone-state", default=None, help="off | on | armed | flying")
    g.add_argument("--controller-state", default=None, help="off | on | linked")
    g.add_argument("--motors-state", default=None, help="off | on")
    g.add_argument("--distance-m", type=float, default=None)
    g.add_argument("--antenna", default=None)
    g.add_argument("--notes", default=None)
    g.add_argument("--session-root", default=DEFAULT_SESSION_ROOT)


def _add_radio_flags(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("radio")
    g.add_argument("--center-mhz", type=float, default=None)
    g.add_argument("--sample-rate", type=float, default=None)
    g.add_argument("--lna", type=int, default=None, help="HackRF LNA gain 0-40 step 8")
    g.add_argument("--vga", type=int, default=None, help="HackRF VGA gain 0-62 step 2")
    g.add_argument("--amp", action="store_true", help="enable the +14 dB front-end amp")
    g.add_argument("--backend", default=None, help="libhackrf | hackrf_transfer | soapy")
    g.add_argument("--sim", action="store_true", help="synthetic IQ, no hardware")


def _print_frame(fr: FrameResult, as_json: bool) -> None:
    if as_json:
        print(json.dumps(fr.record()), flush=True)
    else:
        print(fr.status_line(), flush=True)


# --- commands ------------------------------------------------------------------

def cmd_info(args) -> int:
    from .sdr.capture import hackrf_serial_from_info
    try:
        from .sdr.libhackrf import HackRFStream
        s = HackRFStream(20e6, 2440e6)
        info = s.info()
        s.lib.hackrf_close(s.dev); s.lib.hackrf_exit()
        info["backend"] = "libhackrf (continuous)"
    except Exception as exc:  # noqa: BLE001
        info = {"error": str(exc), "serial_via_hackrf_info": hackrf_serial_from_info()}
    from .classify.model import model_available, _model_path
    info["model"] = str(_model_path()) if model_available() else None
    print(json.dumps(info, indent=2))
    return 0


def cmd_baseline(args) -> int:
    from .scan import bands, sweep
    lo, hi = bands.resolve_band(args.band)
    out = Path(args.out)
    print(f"recording baseline {lo:.1f}-{hi:.1f} MHz for {args.seconds:.0f}s -- keep the test drones OFF", flush=True)
    b = sweep.record_baseline(lo, hi, args.seconds, bin_hz=args.bin_hz, lna=args.lna or 16, vga=args.vga or 24)
    path = sweep.save_baseline(b, out)
    print(f"baseline saved: {path}  ({b.n_sweeps} sweeps averaged, {b.freqs_mhz.size} bins, "
          f"floor {float(np.median(b.power_db)):.0f} dB)")
    return 0


def cmd_scan(args) -> int:
    from .scan import bands, sweep, candidates
    lo, hi = bands.resolve_band(args.band)
    base = sweep.load_baseline(args.baseline) if args.baseline else None
    if base is not None and (abs(base.lo_mhz - lo) > 0.5 or abs(base.hi_mhz - hi) > 0.5):
        print(f"warning: baseline covers {base.lo_mhz}-{base.hi_mhz} MHz, scan is {lo}-{hi}; "
              "differencing only where they overlap", file=sys.stderr)
    rounds = max(1, int(args.rounds))
    for r in range(rounds):
        freqs, pm, _n = sweep.sweep_once(lo, hi, args.seconds, bin_hz=args.bin_hz,
                                         lna=args.lna or 16, vga=args.vga or 24)
        cands = candidates.rank_candidates(freqs, pm, base, min_delta_db=args.min_delta_db,
                                           min_width_mhz=args.min_width_mhz, max_candidates=args.max)
        hdr = f"scan {lo:.0f}-{hi:.0f} MHz  ({pm.shape[0]} sweeps, baseline={'yes' if base else 'self'})"
        print(hdr if rounds == 1 else f"[{r+1}/{rounds}] {hdr}")
        if not cands:
            print("  no candidates above threshold")
        else:
            print(candidates.summarize(cands))
            print(f"  -> lock the top one:  aerix-rf lock --center-mhz {cands[0].center_mhz:.0f} --seconds 60")
        if args.json:
            print(json.dumps([c.to_dict() for c in cands]))
    return 0


def _run_locked(args, *, record_all: bool) -> int:
    """Shared body of `lock` and `capture`: stream one channel through the pipeline
    into a session directory."""
    from .sdr.capture import make_source
    from .session.store import Session
    from .session.report import write_summary
    from .dsp import spectrogram

    cfg = _cfg_from(args)
    Path(args.session_root).mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(args.session_root).free / 1e9
    per_window_mb = cfg.sample_rate * cfg.window_s * 2 / 1e6
    if free_gb < 1.0:
        print(f"error: only {free_gb:.1f} GB free under {args.session_root}; refusing to record", file=sys.stderr)
        return 2
    max_bytes = float(args.max_gb) * 1e9
    if max_bytes > free_gb * 1e9 - 0.5e9:
        max_bytes = free_gb * 1e9 - 0.5e9
        print(f"warning: --max-gb capped to {max_bytes/1e9:.1f} GB to leave 0.5 GB free", file=sys.stderr)
    print(f"disk: {free_gb:.1f} GB free, {per_window_mb:.0f} MB per window, IQ cap {max_bytes/1e9:.1f} GB "
          f"(~{max_bytes/1e6/per_window_mb:.0f} windows)", flush=True)

    source = make_source(cfg, prefer=args.backend)
    session = Session.create(args.session_root, args.label, cfg=cfg,
                             receiver=_receiver_meta(source, cfg), test=_test_meta(args),
                             notes=args.notes or "")
    session.set("mode", "capture" if record_all else "lock")
    print(f"session: {session.path}", flush=True)
    print(f"locked on {cfg.center_freq_mhz:.1f} MHz @ {cfg.sample_rate/1e6:.0f} MS/s "
          f"({type(source).__name__}) for {args.seconds:.0f}s -- Ctrl-C to stop early", flush=True)

    n_windows = 0
    n_plaus = 0
    n_crc = 0
    iq_bytes = 0
    iq_capped = False
    t_end = time.time() + args.seconds
    # Session I/O (int8 conversion, sha256, 40 MB write, PNG encode) runs on one
    # worker thread so the radio consumer stays ahead of real time; numpy /
    # hashlib / file I/O release the GIL. FIFO, so file numbering and jsonl
    # order match the capture order.
    writer = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    pending: list[concurrent.futures.Future] = []

    def _persist(win, fr: FrameResult, rec: dict, keep_iq: bool, want_png: bool) -> None:
        if keep_iq:
            rec["iq_file"] = session.write_iq(win).name
        if want_png:
            rec["spectrogram"] = session.write_spectrogram(
                spectrogram.to_png(fr.spec), win.captured_at, tag=getattr(fr.det, "morphology", "")).name
        session.log_detection(rec)
        for d in fr.decode_records():
            session.log_decode(d)

    try:
        for win in source.windows():
            fr = process_window(win, cfg, decode=not args.no_decode)
            n_windows += 1
            n_plaus += int(fr.plausible)
            n_crc += int(fr.decoded is not None)

            keep_iq = record_all or fr.plausible or fr.decoded is not None or fr.decode_level in ("A", "B")
            rec = fr.record()
            if keep_iq and iq_bytes + win.iq.size * 2 > max_bytes:
                keep_iq = False
                if not iq_capped:
                    iq_capped = True
                    print(f"IQ cap of {max_bytes/1e9:.1f} GB reached -- still detecting, no longer saving IQ "
                          f"(raise with --max-gb)", flush=True)
            if keep_iq:
                iq_bytes += win.iq.size * 2
            rec["iq_saved"] = keep_iq
            want_png = fr.plausible or record_all or args.png_all
            # Bound the backlog: if the disk cannot keep up, block here rather than
            # grow without limit (the radio queue then reports the loss honestly).
            pending = [f for f in pending if not f.done()]
            if len(pending) >= 3:
                pending[0].result()
            pending.append(writer.submit(_persist, win, fr, rec, keep_iq, want_png))
            _print_frame(fr, args.json)

            if time.time() >= t_end:
                break
    except KeyboardInterrupt:
        print("\nstopped by user", flush=True)
    finally:
        source.close()
        writer.shutdown(wait=True)
        for f in pending:
            exc = f.exception()
            if exc is not None:
                print(f"error while writing session data: {exc!r}", file=sys.stderr)
        session.finalize({"windows": n_windows, "plausible": n_plaus, "crc_valid_decodes": n_crc,
                          "iq_bytes": iq_bytes, "iq_capped": iq_capped})
        path = write_summary(session)
        print(f"\n{n_windows} windows, {n_plaus} plausible, {n_crc} CRC-valid decodes")
        print(f"report: {path}")
    return 0


def cmd_lock(args) -> int:
    return _run_locked(args, record_all=args.record_all)


def cmd_capture(args) -> int:
    return _run_locked(args, record_all=True)


def cmd_replay(args) -> int:
    """Deterministic offline re-run of a session's IQ; results go next to the originals."""
    from .session.store import Session
    from .session.report import write_summary
    from .dsp import spectrogram

    src = Session.open(args.session)
    cfg = _cfg_from(args)
    cfg.sample_rate = float(src.meta.get("sample_rate", cfg.sample_rate))
    out_root = Path(args.out) if args.out else src.path / "replays"
    rep = Session.create(out_root, f"replay-of-{src.path.name}", cfg=cfg,
                         receiver={"receiver_type": "file", "replay_of": str(src.path),
                                   "source_receiver": src.meta.get("receiver_type"),
                                   "sample_rate": cfg.sample_rate},
                         test=src.meta.get("test"), notes=f"replay of {src.path}")
    rep.set("mode", "replay")
    print(f"replaying {src.path} -> {rep.path}", flush=True)

    n = 0
    n_crc = 0
    orig = {r.get("iq_file"): r for r in src.detections() if r.get("iq_file")}
    diffs = []
    for win in src.iq_windows(cfg):
        fr = process_window(win, cfg, decode=not args.no_decode)
        rec = fr.record()
        rec["iq_file"] = Path(win.metadata.get("file", "")).name
        if args.png:
            rep.write_spectrogram(spectrogram.to_png(fr.spec), win.captured_at)
        rep.log_detection(rec)
        for d in fr.decode_records():
            rep.log_decode(d)
        _print_frame(fr, args.json)
        n += 1
        n_crc += int(fr.decoded is not None)
        o = orig.get(rec["iq_file"])
        if o:
            diffs.append({"file": rec["iq_file"],
                          "score": (o.get("score"), rec["score"]),
                          "class": (o.get("class"), rec["class"]),
                          "crc_ok": (o.get("crc_ok"), rec["crc_ok"]),
                          "serial": (o.get("serial"), rec["serial"])})
    rep.finalize({"windows": n, "crc_valid_decodes": n_crc, "compared_windows": len(diffs)})
    path = write_summary(rep)

    if diffs:
        same_crc = sum(1 for d in diffs if d["crc_ok"][0] == d["crc_ok"][1] and d["serial"][0] == d["serial"][1])
        same_cls = sum(1 for d in diffs if d["class"][0] == d["class"][1])
        max_ds = max(abs((d["score"][0] or 0) - (d["score"][1] or 0)) for d in diffs)
        print(f"\nreplay vs original over {len(diffs)} windows: decode identical {same_crc}/{len(diffs)}, "
              f"class identical {same_cls}/{len(diffs)}, max |score delta| {max_ds:.3f}")
    print(f"report: {path}")
    return 0


def cmd_report(args) -> int:
    from .session.store import Session
    from .session.report import write_summary, build_summary
    s = Session.open(args.session)
    path = write_summary(s)
    if args.print:
        print(build_summary(s))
    print(f"report: {path}")
    return 0


def cmd_run(args) -> int:
    from .main import run
    cfg = _cfg_from(args)
    run(cfg, once=args.once, as_json=not args.human)
    return 0


# --- parser --------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aerix-rf", description="AERIX RF/SDR drone-detection box + field-test tool")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("info", help="show the attached receiver and model status")
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("baseline", help="record an ambient sweep baseline (drones OFF)")
    p.add_argument("--band", default="2.4", help="preset (2.4, 5.8, 5.2, 900) or lo:hi MHz")
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--out", required=True, help="output path (.npz)")
    p.add_argument("--bin-hz", type=int, default=500_000)
    p.add_argument("--lna", type=int, default=None); p.add_argument("--vga", type=int, default=None)
    p.set_defaults(fn=cmd_baseline)

    p = sub.add_parser("scan", help="sweep a band and rank new/interesting signals")
    p.add_argument("--band", default="2.4")
    p.add_argument("--baseline", default=None, help="baseline .npz from `baseline`")
    p.add_argument("--seconds", type=float, default=4.0, help="dwell per scan round")
    p.add_argument("--rounds", type=int, default=1, help="repeat the scan N times")
    p.add_argument("--bin-hz", type=int, default=500_000)
    p.add_argument("--min-delta-db", type=float, default=6.0)
    p.add_argument("--min-width-mhz", type=float, default=1.0)
    p.add_argument("--max", type=int, default=8)
    p.add_argument("--lna", type=int, default=None); p.add_argument("--vga", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scan)

    for name, fn, help_ in (("lock", cmd_lock, "lock one channel: detect/classify/decode live, record a session"),
                            ("capture", cmd_capture, "like lock, but keep EVERY window's raw IQ")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--seconds", type=float, default=60.0)
        p.add_argument("--no-decode", action="store_true")
        p.add_argument("--png-all", action="store_true", help="save a spectrogram for every window")
        p.add_argument("--json", action="store_true", help="JSON status lines instead of the human line")
        p.add_argument("--max-gb", type=float, default=3.0,
                       help="stop writing raw IQ once the session exceeds this size (detections/decodes "
                            "keep logging); 1 s @ 20 MS/s = 40 MB")
        if name == "lock":
            p.add_argument("--record-all", action="store_true", help="keep raw IQ for every window")
        _add_radio_flags(p)
        _add_test_flags(p)
        p.set_defaults(fn=fn)

    p = sub.add_parser("replay", help="deterministic offline re-run of a session's raw IQ")
    p.add_argument("session")
    p.add_argument("--out", default=None, help="where to write the replay session (default: <session>/replays)")
    p.add_argument("--no-decode", action="store_true")
    p.add_argument("--png", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("report", help="(re)generate summary.md for a session")
    p.add_argument("session")
    p.add_argument("--print", action="store_true")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("run", help="the 1 Hz box service (server uplink if configured)")
    p.add_argument("--once", action="store_true")
    p.add_argument("--human", action="store_true", help="human status lines instead of JSON")
    _add_radio_flags(p)
    p.set_defaults(fn=cmd_run)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    known = {"info", "baseline", "scan", "lock", "capture", "replay", "report", "run"}
    # Back-compat: `aerix-rf --sim` / `aerix-rf --once` == `aerix-rf run ...`
    if not any(a in known for a in argv):
        argv = ["run"] + argv
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
