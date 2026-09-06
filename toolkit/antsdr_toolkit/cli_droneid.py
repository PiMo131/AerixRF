"""``antsdr-tk droneid``: find and decode DJI DroneID bursts in a recording.

Reads a SigMF capture, correlates against the Zadoff-Chu pilots, and prints
one line per burst with the decode result.  A capture must be at a rate that
is a multiple of the 15 kHz subcarrier spacing with a power-of-two FFT:
15.36, 30.72 or 61.44 MSPS.  20 MSPS does not work, however convenient it is
for the E200's host link.

What a result means
-------------------
``crc24`` is the payload check and ``crc16`` the frame check; both must pass
before the serial number and positions are worth anything.  A burst that is
found but does not decode is still a real observation: it is either too weak
for a receiver without error correction (below roughly 15 dB in-band
signal-to-noise here), or it belongs to an OcuSync 4 drone, whose payload is
encrypted.  Either way the frequency, the time and the signal-to-noise ratio
are usable, which is what the presence tier of ``ADR-0006`` is about.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

__all__ = ["build_parser", "configure", "main", "register", "run"]

HELP = "find and decode DJI DroneID bursts in a SigMF recording"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("recording", help="SigMF stem, .sigmf-meta or .sigmf-data")
    parser.add_argument("--threshold", type=float, default=None, metavar="X",
                        help="Zadoff-Chu correlation threshold, 0 to 1 (default 0.5)")
    parser.add_argument("--legacy", action="store_true",
                        help="expect the 8-symbol burst of the Mavic Pro and Mavic 2")
    parser.add_argument("--max-samples", type=int, default=1 << 25, metavar="N",
                        help="read at most this many samples (default 33554432)")
    parser.add_argument("--json", dest="json_path", default=None, metavar="PATH",
                        help="write the full result as JSON")
    parser.add_argument("--quiet", action="store_true",
                        help="print only decoded frames, not every burst")


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("droneid", help=HELP, description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    configure(parser)
    parser.set_defaults(func=run, _run=run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk droneid", description=HELP)
    configure(parser)
    return parser


def run(args: argparse.Namespace) -> int:
    from .device.file_source import SigmfFileSource
    from .droneid import constants as C
    from .droneid import receiver as rx

    with SigmfFileSource(args.recording) as src:
        info = src.info
        x = src.read(min(int(args.max_samples), src.n_samples))
    if x.ndim > 1:
        x = x[0]
    fs = info.sample_rate_hz

    try:
        C.fft_size(fs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not C.is_supported_rate(fs):
        print(f"warning: {fs / 1e6:g} MSPS gives a non-power-of-two FFT; the reference "
              "implementations assume one", file=sys.stderr)

    threshold = rx.DEFAULT_THRESHOLD if args.threshold is None else float(args.threshold)
    results = rx.process(x, fs, threshold=threshold, legacy=bool(args.legacy))

    channel = C.channel_for(info.center_freq_hz)
    print(f"# {info}")
    print(f"# {x.size} samples, {x.size / fs * 1e3:.1f} ms, threshold {threshold:g}"
          + (f", known DroneID channel {channel / 1e6:.1f} MHz" if channel
             else ", not a documented DroneID centre"))
    decoded = sum(1 for _d, f in results if f and f.crc24_ok and f.crc16_ok)
    print(f"# {len(results)} burst(s), {decoded} decoded")

    payload: dict[str, Any] = {
        "recording": str(args.recording),
        "sample_rate_hz": fs,
        "center_freq_hz": info.center_freq_hz,
        "n_bursts": len(results),
        "n_decoded": decoded,
        "bursts": [],
    }
    for index, (detection, frame) in enumerate(results, start=1):
        ok = bool(frame and frame.crc24_ok and frame.crc16_ok)
        if not args.quiet or ok:
            print(f"\nburst {index}: t={detection.t_start_s * 1e3:8.3f} ms  "
                  f"score {detection.score:.3f}  prefix {detection.confirm_score:.3f}  "
                  f"cfo {detection.cfo_hz:+8.0f} Hz  snr {detection.snr_db:5.1f} dB")
            if frame is None:
                print("  no decode: the burst geometry did not resolve")
            elif ok:
                print(f"  {frame.product_name} serial {frame.serial!r}")
                print(f"  drone  {_pos(frame.drone_lat, frame.drone_lon)}  "
                      f"height {frame.height_m:.0f} m  altitude {frame.altitude_m:.0f} m")
                print(f"  pilot  {_pos(frame.pilot_lat, frame.pilot_lon)}")
                print(f"  home   {_pos(frame.home_lat, frame.home_lon)}")
                print(f"  speed  {frame.speed_h_m_s:.1f} m/s horizontal, "
                      f"{frame.v_up_m_s:.1f} m/s vertical, yaw {frame.yaw_deg:.1f} deg")
            else:
                print(f"  CRC failed (crc24 {frame.crc24_ok}, crc16 {frame.crc16_ok}): "
                      "too weak for a receiver without error correction, or an "
                      "encrypted OcuSync 4 payload")
        payload["bursts"].append({
            "detection": detection.to_dict(),
            "frame": frame.to_dict() if frame else None,
        })

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        print(f"\n# wrote {args.json_path}")
    return 0


def _pos(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return "unknown"
    return f"{lat:.6f}, {lon:.6f}"


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
