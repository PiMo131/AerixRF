"""``antsdr-tk droneid``: find and decode DJI DroneID bursts in a recording.

Reads a SigMF capture, correlates against the Zadoff-Chu pilots, and prints
one line per burst with the decode result.

Captures that are not already at a DroneID rate
-----------------------------------------------
The receiver itself needs a burst centred at zero and sampled at a multiple
of the 15 kHz subcarrier spacing with a power-of-two FFT: 15.36, 30.72 or
61.44 MSPS.  Recordings rarely arrive that way - you tune to a channel centre,
sample at whatever the host link sustains, and the aircraft puts its burst
where it likes inside the span - so ``--tune`` finds the occupied 9 MHz bands,
mixes each to zero and resamples to 15.36 MSPS before decoding.  It engages by
itself when the recording's own rate cannot work, which is what makes 20 MSPS
usable after all: convenient for the E200's host link, impossible for the
receiver directly, fine once retuned.

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
    parser.add_argument("--method", choices=("zc", "cp", "both"), default="both",
                        help="detection gate: zc is the root-600 matched filter, cp is "
                             "root-agnostic cyclic-prefix structure, both merges them "
                             "(default). Only cp can see OcuSync 3 and 4 bursts, whose "
                             "Zadoff-Chu roots differ or vary")
    parser.add_argument("--tune", dest="tune", action="store_true", default=None,
                        help="find the occupied 9 MHz bands and resample each to "
                             "15.36 MSPS before decoding. On by default when the "
                             "recording's own rate cannot be decoded directly")
    parser.add_argument("--no-tune", dest="tune", action="store_false",
                        help="decode the capture as it is, even if that cannot work")
    parser.add_argument("--bands", type=int, default=3, metavar="N",
                        help="how many candidate bands --tune may return (default 3)")
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

    # Can this rate be decoded at all as it stands? That decides whether tuning
    # is a choice or a necessity, and the user is told which.
    try:
        C.fft_size(fs)
        direct = C.is_supported_rate(fs)
        direct_error = None
    except ValueError as exc:
        direct, direct_error = False, str(exc)

    tuning = (not direct) if args.tune is None else bool(args.tune)
    if not direct and not tuning:
        print(f"error: {direct_error or f'{fs / 1e6:g} MSPS is not a DroneID rate'}"
              " -- drop --no-tune to have the bands found and resampled",
              file=sys.stderr)
        return 1
    if not direct and args.tune is None:
        print(f"# {fs / 1e6:g} MSPS cannot be decoded directly; finding the occupied "
              "bands and resampling to 15.36 MSPS", file=sys.stderr)
    elif direct and not C.is_supported_rate(fs):
        print(f"warning: {fs / 1e6:g} MSPS gives a non-power-of-two FFT; the reference "
              "implementations assume one", file=sys.stderr)

    threshold = rx.DEFAULT_THRESHOLD if args.threshold is None else float(args.threshold)
    if tuning:
        from .droneid import tune as tuner

        bands = tuner.prepare(x, fs, max_centres=max(1, int(args.bands)))
        band_rate = 15.36e6
    else:
        bands, band_rate = [(0.0, x)], fs

    channel = C.channel_for(info.center_freq_hz)
    print(f"# {info}")
    print(f"# {x.size} samples, {x.size / fs * 1e3:.1f} ms, threshold {threshold:g}"
          + (f", known DroneID channel {channel / 1e6:.1f} MHz" if channel
             else ", not a documented DroneID centre"))
    if tuning:
        print(f"# {len(bands)} candidate band(s) at "
              + (", ".join(f"{c / 1e6:+.3f} MHz" for c, _ in bands) or "none")
              + " from the capture centre")
        if not bands:
            print("# nothing in the span looks like an occupied 9 MHz channel",
                  file=sys.stderr)

    results: list[tuple[Any, Any, float]] = []
    for centre, band in bands:
        for detection, frame in rx.process(band, band_rate, threshold=threshold,
                                           legacy=bool(args.legacy),
                                           method=str(args.method)):
            results.append((detection, frame, centre))
    results.sort(key=lambda r: (r[2], r[0].sample_start))

    decoded = sum(1 for _d, f, _c in results if f and f.crc24_ok and f.crc16_ok)
    print(f"# {len(results)} burst(s), {decoded} decoded")

    payload: dict[str, Any] = {
        "recording": str(args.recording),
        "sample_rate_hz": fs,
        "center_freq_hz": info.center_freq_hz,
        "tuned": bool(tuning),
        "band_offsets_hz": [centre for centre, _ in bands],
        "n_bursts": len(results),
        "n_decoded": decoded,
        "bursts": [],
    }
    for index, (detection, frame, centre) in enumerate(results, start=1):
        ok = bool(frame and frame.crc24_ok and frame.crc16_ok)
        if not args.quiet or ok:
            where = (f"  band {centre / 1e6:+.3f} MHz" if tuning else "")
            print(f"\nburst {index}: t={detection.t_start_s * 1e3:8.3f} ms{where}  "
                  f"score {detection.score:.3f}  prefix {detection.confirm_score:.3f}  "
                  f"root {detection.zc_root if detection.zc_root is not None else '?':>4}  "
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
            "band_offset_hz": centre,
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
