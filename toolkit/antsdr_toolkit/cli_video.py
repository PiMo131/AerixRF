"""``antsdr-tk video``: decode analog FPV video from a recording into pictures.

Reads a SigMF capture of an analog 5.8 GHz FPV carrier, discriminates the FM,
finds the fields and writes one image per field (or per woven frame).

What a result means
-------------------
``standard`` is decided by the measured line rate and must be NTSC or PAL to
within 0.3 %; if it is neither, nothing is written, because slicing a picture
out of a signal whose line rate is unknown produces a convincing image of
nothing.

``complete`` says every line of a field was found.  An incomplete field still
carries a picture, with the missing lines black; a field that is short by a
handful of lines is normal at the start and end of a capture, and a field
short by many is a weak or interfered signal.

Sample rate
-----------
**Capture at 20 MSPS.**  Two independent reasons, and they do not depend on
each other.  The 6.0 and 6.5 MHz audio subcarriers and PAL chroma are outside
Nyquist below about 14 MSPS, so a lower rate cannot carry the whole signal
whatever the deviation.  And at this toolkit's modulation depth peak white
sits at +6.4 MHz, which aliases below 12.75 MSPS.

How much a real transmitter actually swings is not established: the RTC6705
datasheet gives no video deviation, and the one real measurement in the
research record decoded a whoop VTX at 10 MSPS, so that unit swung less than
the model here.  20 MSPS makes the question moot.

The failure below that rate is quiet, which is why this command warns.  Sync
pulses survive aliasing, so the line rate still measures correctly and a naive
decoder reports a complete field of nonsense.

20 MSPS is above what the stock IIO firmware streams continuously (11 to
13 MSPS), so analog video is a snapshot capture on that personality, or a job
for the UHD firmware.  See ADR-0004.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

__all__ = ["build_parser", "configure", "main", "register", "run"]

HELP = "decode analog FPV video from a SigMF recording into images"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("recording", help="SigMF stem, .sigmf-meta or .sigmf-data")
    parser.add_argument("-o", "--out-dir", default=".", metavar="DIR",
                        help="where to write the images (default: current directory)")
    parser.add_argument("--standard", choices=("ntsc", "pal"), default=None,
                        help="force a standard instead of measuring the line rate")
    parser.add_argument("--width", type=int, default=320, metavar="N",
                        help="pixels per line (default 320)")
    parser.add_argument("--max-fields", type=int, default=8, metavar="N",
                        help="stop after this many fields (default 8, 0 for all)")
    parser.add_argument("--frames", action="store_true",
                        help="weave field pairs into full-height frames")
    parser.add_argument("--format", choices=("png", "pgm"), default="png",
                        help="image format (default png)")
    parser.add_argument("--lowpass", type=float, default=4e6, metavar="HZ",
                        help="video low-pass after the discriminator (default 4e6)")
    parser.add_argument("--max-samples", type=int, default=1 << 26, metavar="N",
                        help="read at most this many samples (default 67108864)")
    parser.add_argument("--json", dest="json_path", default=None, metavar="PATH",
                        help="write the per-field report as JSON")


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("video", help=HELP, description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    configure(parser)
    parser.set_defaults(func=run, _run=run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk video", description=HELP)
    configure(parser)
    return parser


def run(args: argparse.Namespace) -> int:
    from .analog import fpv
    from .analog import video_decode as vd
    from .device.file_source import SigmfFileSource

    with SigmfFileSource(args.recording) as src:
        info = src.info
        x = src.read(min(int(args.max_samples), src.n_samples))
    if x.ndim > 1:
        x = x[0]
    fs = info.sample_rate_hz

    print(f"# {info}")
    channel = fpv.nearest_channel(info.center_freq_hz)
    print(f"# {x.size} samples, {x.size / fs * 1e3:.1f} ms"
          + (f", analog channel {channel}" if channel else ", not a documented FPV channel"))

    limit = None if int(args.max_fields) <= 0 else int(args.max_fields)
    fields, standard = vd.decode_from_iq(
        x, fs, standard=args.standard, width=int(args.width),
        lowpass_hz=float(args.lowpass), max_fields=limit)

    if standard is None:
        print("# no video: the line rate matched neither NTSC nor PAL to within 0.3 %.\n"
              "# Either this is not analog FPV, or the signal is too weak to slice sync\n"
              "# from picture. 'antsdr-tk classify' will say which.", file=sys.stderr)
        return 1
    print(f"# {standard.upper()}, {len(fields)} field(s), "
          f"{sum(f.complete for f in fields)} complete")
    if not fields:
        return 1

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write = vd.write_png if args.format == "png" else vd.write_pgm
    stem = pathlib.Path(str(args.recording)).stem.replace(".sigmf-meta", "")

    written: list[str] = []
    if args.frames:
        for index, frame in enumerate(vd.weave(fields)):
            path = out_dir / f"{stem}-frame{index:03d}.{args.format}"
            written.append(write(str(path), frame))
    else:
        for index, field in enumerate(fields):
            path = out_dir / f"{stem}-field{index:03d}.{args.format}"
            written.append(write(str(path), field.image))

    for index, field in enumerate(fields):
        flag = "" if field.complete else "  INCOMPLETE"
        print(f"field {index}: t={field.t_start_s * 1e3:8.3f} ms  "
              f"{field.n_lines_found:3d} lines  "
              f"mean level {field.image.mean():.3f}{flag}")
    print(f"\n# wrote {len(written)} image(s) to {out_dir}/")

    if args.json_path:
        payload = {
            "recording": str(args.recording),
            "sample_rate_hz": fs,
            "center_freq_hz": info.center_freq_hz,
            "channel": channel,
            "standard": standard,
            "n_fields": len(fields),
            "images": written,
            "fields": [f.to_dict() for f in fields],
        }
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        print(f"# wrote {args.json_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
