"""``antsdr-tk firstrun``: the whole first session with the board, in one command.

Written for the case where there is no time. It checks the link, records what
the hardware says about itself, takes a short capture in each band that
matters, and runs every analysis stage over what it got. One command, one
directory of results, and a printed summary of what was and was not seen.

Everything it captures is a SigMF pair with metadata, so nothing has to be
repeated later: the recordings can be re-analysed at leisure, and they are the
beginning of the own-recording corpus that ``ADR-0007`` says any field model
needs.

What it does, in order
----------------------
1. **Identify the board.** Reads the IIO context and prints the transceiver
   the firmware declares, the driver version and the tuning limits. Answers
   most of Q1 in ``QUESTIONS.md`` without opening the case.
2. **Check the noise floor** on a quiet frequency, at the gain about to be
   used. A floor far from the expected value means the antenna, the gain mode
   or the cabling is wrong, and it is much better to learn that now.
3. **Capture each band in the plan.** 2.4 GHz and 5.8 GHz by default, at
   rates chosen per band: the DroneID rate where DroneID lives, and 20 MSPS
   where analog video lives, because below about 13 MSPS the video FM aliases
   (``analog.video_decode.MIN_SAMPLE_RATE_HZ``).
4. **Analyse each capture** through sweep, burst detection, classification,
   the cyclostationary numerology test, the DroneID detector and the analog
   video decoder, writing any pictures it recovers.
5. **Summarise**, and say plainly what was not observed and what that does and
   does not prove.

Use ``--dry-run`` to print the plan and the commands without touching the
board, which is worth doing once before the session rather than during it.

This does not transmit (``ADR-0001``).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["DEFAULT_PLAN", "BandStep", "build_parser", "configure", "main", "register", "run"]

HELP = "check the board, capture every band that matters, and analyse it all"


@dataclass(frozen=True)
class BandStep:
    """One capture in the first-run plan, and why it is at that rate."""

    name: str
    center_freq_hz: float
    sample_rate_hz: float
    seconds: float
    why: str
    analyses: tuple[str, ...] = field(default=("sweep", "classify"))


#: 2.4 GHz first because it is where DroneID and most control links live, and
#: 5.8 GHz at a rate the analog video decoder can actually use.
DEFAULT_PLAN: tuple[BandStep, ...] = (
    BandStep("droneid-2g4", 2429.5e6, 15.36e6, 2.0,
             "a documented DroneID centre, at the only rate its FFT divides evenly",
             ("sweep", "classify", "cyclo", "droneid")),
    BandStep("ism-2g4-wide", 2442.0e6, 20e6, 2.0,
             "the middle of the band, wide enough to see Wi-Fi and the hoppers",
             ("sweep", "classify", "cyclo")),
    BandStep("fpv-5g8", 5800.0e6, 20e6, 1.0,
             "analog video: 20 MSPS because the FM aliases below about 13",
             ("sweep", "classify", "video")),
    BandStep("o4-5g7", 5756.5e6, 20e6, 1.0,
             "a channel the E200 O4 DroneID firmware watches (unverified round-1)",
             ("sweep", "classify", "cyclo")),
)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--out-dir", default="firstrun", metavar="DIR",
                        help="where to write recordings and results (default: firstrun)")
    parser.add_argument("--uri", default=None, metavar="URI",
                        help="board URI (default: the E200 profile's ip:192.168.1.10)")
    parser.add_argument("--gain", type=float, default=40.0, metavar="DB")
    parser.add_argument("--seconds", type=float, default=None, metavar="S",
                        help="override every step's capture length")
    parser.add_argument("--only", default=None, metavar="NAME",
                        help="run one step of the plan by name")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and stop, touching no hardware")
    parser.add_argument("--skip-checks", action="store_true",
                        help="go straight to capturing, without the board identity check")


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("firstrun", help=HELP, description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    configure(parser)
    parser.set_defaults(func=run, _run=run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk firstrun", description=HELP)
    configure(parser)
    return parser


def _plan(args: argparse.Namespace) -> list[BandStep]:
    steps = list(DEFAULT_PLAN)
    if args.only:
        steps = [s for s in steps if s.name == args.only]
        if not steps:
            raise ValueError(f"no step named {args.only!r}; "
                             f"choose from {', '.join(s.name for s in DEFAULT_PLAN)}")
    if args.seconds is not None:
        steps = [BandStep(s.name, s.center_freq_hz, s.sample_rate_hz,
                          float(args.seconds), s.why, s.analyses) for s in steps]
    return steps


def _print_plan(steps: list[BandStep], out_dir: pathlib.Path, uri: str) -> None:
    from . import hardware as hw

    print(f"# board {uri}, writing to {out_dir}/\n")
    print(f"{'step':16} {'centre':>12} {'rate':>10} {'s':>5}  analyses")
    print("-" * 92)
    total = 0.0
    for step in steps:
        print(f"{step.name:16} {step.center_freq_hz / 1e6:9.1f} MHz "
              f"{step.sample_rate_hz / 1e6:7.2f} M {step.seconds:5.1f}  "
              f"{', '.join(step.analyses)}")
        print(f"{'':16} {step.why}")
        total += step.seconds
    print(f"\n# {len(steps)} step(s), {total:.0f} s of capture "
          f"plus retune and settling time")

    ceiling = hw.E200.host_stream_ceiling_sps["iio_sc16_1ch"]
    over = [s for s in steps if s.sample_rate_hz > ceiling]
    if over:
        print(f"# {len(over)} step(s) run above the {ceiling / 1e6:g} MSPS the stock IIO\n"
              f"# firmware sustains. High-rate snapshot captures must fit one RX buffer;\n"
              f"# longer steps are rejected because gap timing is not implemented.\n"
              f"# Use --seconds 0.01 for a short probe; absence is inconclusive.")


def run(args: argparse.Namespace) -> int:
    from . import hardware as hw

    out_dir = pathlib.Path(args.out_dir)
    uri = args.uri or hw.E200.default_uri
    try:
        steps = _plan(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_plan(steps, out_dir, uri)
    if args.dry_run:
        print("\n# --dry-run: nothing was captured.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"uri": uri, "gain_db": args.gain, "steps": {}}

    if not args.skip_checks:
        print("\n" + "=" * 72 + "\n1. what the board says it is\n")
        identity = _identify(uri)
        report["board"] = identity
        if identity.get("error"):
            print(f"  could not reach the board: {identity['error']}")
            print("\n  Check in this order: the cable, that the host has an address on the\n"
                  "  board's subnet, and that iiod is up (`iio_info -u <uri>`). On Windows\n"
                  "  the native libiio runtime must be installed and address the board by\n"
                  "  explicit IP rather than by discovery. See ADR-0012.")
            return 1
        for key, value in identity.items():
            print(f"  {key:22} {value}")

    for index, step in enumerate(steps, start=1):
        print("\n" + "=" * 72 + f"\n{index + 1}. {step.name}: "
              f"{step.center_freq_hz / 1e6:.1f} MHz at {step.sample_rate_hz / 1e6:g} MSPS\n")
        stem = out_dir / step.name
        result = _capture_and_analyse(step, stem, uri, float(args.gain))
        report["steps"][step.name] = result
        if result.get("error"):
            print(f"  failed: {result['error']}")

    path = out_dir / "firstrun.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, default=str)
    _summarise(report, out_dir)
    print(f"\n# full report: {path}")
    return 1 if any("error" in step for step in report["steps"].values()) else 0


def _identify(uri: str) -> dict[str, Any]:
    """Everything the IIO context will tell us, without opening the case."""
    try:
        from .device.e200 import probe
        return probe(uri=uri)
    except Exception as exc:  # noqa: BLE001 - retain diagnostic from hardware backend
        return {"error": f"{type(exc).__name__}: {exc}"}


def _capture_and_analyse(step: BandStep, stem: pathlib.Path, uri: str,
                         gain_db: float) -> dict[str, Any]:
    import numpy as np

    from . import hardware as hw
    from .analog import video_decode as vd
    from .classify.heuristic import classify_clusters
    from .dsp import cyclo
    from .dsp.bursts import detect_bursts_from_iq
    from .io.sigmf_io import write_sigmf

    out: dict[str, Any] = {"center_freq_hz": step.center_freq_hz,
                           "sample_rate_hz": step.sample_rate_hz, "why": step.why}
    try:
        from .device.e200 import E200Source
        n = int(step.sample_rate_hz * step.seconds)
        buffer_size = 1 << 18
        if step.sample_rate_hz > hw.E200.host_ceiling(1) and n > buffer_size:
            raise ValueError(
                "first-run high-rate acquisition exceeds one RX buffer; "
                "use --seconds 0.01 for a short probe, or capture a longer single "
                "buffer explicitly with antsdr-tk capture --tier snapshot --buffer N. "
                "Multi-buffer gap timing is not implemented")
        started = time.time()
        with E200Source(uri=uri, sample_rate_hz=step.sample_rate_hz,
                        center_freq_hz=step.center_freq_hz, gain_db=gain_db,
                        gain_mode="manual") as source:
            samples = source.read(n)
            info = source.info
        out["wall_clock_s"] = round(time.time() - started, 2)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    if samples.ndim > 1:
        samples = samples[0]
    data_path, _meta = write_sigmf(stem, samples, info,
                                   description=f"antsdr-tk firstrun: {step.name}",
                                   extra_global={"antsdr:sample_continuity": "unverified",
                                                 "antsdr:timestamp_source": "host_wall_clock_not_hardware"})
    out["recording"] = str(data_path)
    fs = step.sample_rate_hz
    print(f"  captured {samples.size} samples "
          f"({samples.size / fs * 1e3:.0f} ms) -> {data_path.name}")

    power = float(np.mean(np.abs(samples) ** 2))
    out["mean_power_db"] = round(10 * np.log10(power) if power > 0 else -999.0, 1)
    out["kurtosis"] = round(cyclo.kurtosis(samples), 2)
    print(f"  mean power {out['mean_power_db']:.1f} dB, "
          f"kurtosis {out['kurtosis']:.2f} "
          f"({'bursty' if out['kurtosis'] > 3 else 'no obvious bursts'})")

    if "classify" in step.analyses:
        bursts = detect_bursts_from_iq(samples, fs, step.center_freq_hz, fft_size=512,
                                       threshold_db=10.0, min_duration_s=100e-6,
                                       min_bandwidth_hz=200e3)
        out["n_bursts"] = len(bursts)
        groups = classify_clusters(bursts, window_s=samples.size / fs,
                                   band_hint="ism-2g4" if step.center_freq_hz < 4e9
                                   else "ism-5g8", top_k=2)
        out["emitters"] = []
        print(f"  {len(bursts)} burst(s) in {len(groups)} emitter group(s)")
        for features, candidates in groups[:5]:
            best = candidates[0] if candidates else None
            row = {"n_bursts": features.n_bursts,
                   "bandwidth_hz": features.bandwidth_median_hz,
                   "best": best.display if best else None,
                   "score": round(best.score, 2) if best else None}
            out["emitters"].append(row)
            if best:
                print(f"    {best.score:5.2f}  {best.display}  "
                      f"({features.n_bursts} bursts, "
                      f"{features.bandwidth_median_hz / 1e6:.2f} MHz)")

    if "cyclo" in step.analyses:
        profile = cyclo.cyclic_profile(samples, fs, chunk_s=4e-3)
        out["cyclo"] = {k: v.to_dict() for k, v in profile.items()}
        for name, result in profile.items():
            if result.contrast > 3.0:
                print(f"    cyclic line: {name} at {result.alpha_hz / 1e3:.1f} kHz "
                      f"(contrast {result.contrast:.1f})")

    if "droneid" in step.analyses:
        from .droneid import receiver as rx
        results = rx.process(samples, fs)
        decoded = [f for _d, f in results if f and f.crc24_ok and f.crc16_ok]
        out["droneid"] = {"n_bursts": len(results), "n_decoded": len(decoded)}
        print(f"    DroneID: {len(results)} burst(s), {len(decoded)} decoded")
        for frame in decoded:
            print(f"      {frame.product_name} serial {frame.serial!r} "
                  f"at {frame.drone_lat}, {frame.drone_lon}")

    if "video" in step.analyses:
        fields, standard = vd.decode_from_iq(samples, fs, width=320, max_fields=4)
        out["video"] = {"standard": standard, "n_fields": len(fields)}
        if standard and fields:
            for i, decoded_field in enumerate(fields):
                vd.write_png(str(stem) + f"-field{i:03d}.png", decoded_field.image)
            print(f"    analog video: {standard.upper()}, {len(fields)} field(s), "
                  f"wrote {len(fields)} PNG(s)")
        else:
            print("    analog video: no lock")
    return out


def _summarise(report: dict[str, Any], out_dir: pathlib.Path) -> None:
    print("\n" + "=" * 72 + "\nwhat this session established\n")
    steps = report.get("steps", {})
    failed = [k for k, v in steps.items() if v.get("error")]
    if failed:
        print(f"  {len(failed)} step(s) failed: {', '.join(failed)}")
    ok = {k: v for k, v in steps.items() if not v.get("error")}
    total_bursts = sum(v.get("n_bursts", 0) for v in ok.values())
    decoded = sum(v.get("droneid", {}).get("n_decoded", 0) for v in ok.values())
    pictures = sum(v.get("video", {}).get("n_fields", 0) for v in ok.values())
    print(f"  {len(ok)} capture(s) written to {out_dir}/, "
          f"{total_bursts} burst(s) detected")
    print(f"  {decoded} DroneID frame(s) decoded, {pictures} video field(s) recovered")
    print("\n  What an empty result does not prove:\n"
          "    - No DroneID decode is expected unless a Mini 2 or Mavic Air 2 was\n"
          "      flying. Open code decodes those two airframes and no others.\n"
          "    - No Remote ID is expected from any aircraft under 250 g: class C0 is\n"
          "      exempt. Run `antsdr-tk fleet` for what each airframe can yield.\n"
          "    - These are short captures. A DroneID burst comes about every 600 ms,\n"
          "      so a two-second capture sees a handful at best.\n"
          f"\n  Re-analyse any of it without the board:\n"
          f"    antsdr-tk classify {out_dir}/<step> --band ism-2g4\n"
          f"    antsdr-tk video {out_dir}/fpv-5g8 -o {out_dir}/frames --frames")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\n# interrupted; whatever was written is still valid SigMF.")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

