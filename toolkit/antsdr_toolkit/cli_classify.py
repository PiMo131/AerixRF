"""``antsdr-tk classify``: name the emitters in a SigMF recording.

Runs the whole chain on a capture - STFT, burst detection, per-emitter
clustering, burst-set features, signature scoring - and prints one block per
emitter with the evidence behind the verdict.  It is deliberately verbose:
the point of the heuristic stage is that a person can check it.

The detector gates matter.  A bare threshold on a spectrogram produces a
false alarm in about ``exp(-threshold_db / 10 * ln 10)`` of its cells, which
is thousands of one-cell "bursts" in a second of wideband capture, so the
defaults require a burst to span several frames and several bins.  Loosen
them with ``--min-duration`` and ``--min-bandwidth`` when hunting something
short and narrow, and expect the false-alarm count to rise.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

__all__ = ["build_parser", "configure", "main", "register", "run"]

HELP = "detect, cluster and name the emitters in a SigMF recording"

DEFAULT_FFT = 1024
DEFAULT_THRESHOLD_DB = 10.0
DEFAULT_TOP_K = 3


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("recording", help="SigMF stem, .sigmf-meta or .sigmf-data")
    parser.add_argument("--band", default=None, metavar="ID",
                        help="band id hint (see 'sweep --list-bands'); "
                             "families outside it are scored down, not dropped")
    parser.add_argument("--restrict-to-band", action="store_true",
                        help="drop families that do not list the band instead of penalising them")
    parser.add_argument("--fft", type=int, default=DEFAULT_FFT, metavar="N",
                        help=f"STFT size (default {DEFAULT_FFT})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_DB, metavar="DB",
                        help=f"detection threshold above the noise floor "
                             f"(default {DEFAULT_THRESHOLD_DB:g} dB)")
    parser.add_argument("--min-duration", type=float, default=None, metavar="S",
                        help="shortest accepted burst (default: 3 STFT frames)")
    parser.add_argument("--min-bandwidth", type=float, default=None, metavar="HZ",
                        help="narrowest accepted burst (default: 3 STFT bins)")
    parser.add_argument("--cluster-gap", type=float, default=5e6, metavar="HZ",
                        help="centre-frequency gap that starts a new emitter (default 5 MHz)")
    parser.add_argument("--max-samples", type=int, default=1 << 24, metavar="N",
                        help="read at most this many samples (default 16777216)")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_K, metavar="K",
                        help=f"candidates listed per emitter (default {DEFAULT_TOP_K})")
    parser.add_argument("--json", dest="json_path", default=None, metavar="PATH",
                        help="also write the full result as JSON")


def register(subparsers: Any) -> None:
    """Add the ``classify`` subcommand."""
    parser = subparsers.add_parser("classify", help=HELP, description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    configure(parser)
    parser.set_defaults(func=run, _run=run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk classify", description=HELP)
    configure(parser)
    return parser


def _fmt_hz(value: float) -> str:
    if abs(value) >= 1e9:
        return f"{value / 1e9:.6f} GHz"
    return f"{value / 1e6:.4f} MHz"


def _fmt_s(value: float) -> str:
    if value < 1e-3:
        return f"{value * 1e6:.1f} us"
    if value < 1.0:
        return f"{value * 1e3:.3f} ms"
    return f"{value:.3f} s"


def run(args: argparse.Namespace) -> int:
    """Entry point bound by :func:`register`; returns the process exit code."""
    from .classify.heuristic import classify_clusters, margin
    from .device.file_source import SigmfFileSource
    from .dsp.bursts import detect_bursts_from_iq

    with SigmfFileSource(args.recording) as src:
        info = src.info
        n = min(int(args.max_samples), src.n_samples)
        x = src.read(n)
    if x.ndim > 1:
        x = x[0]
    if x.size == 0:
        print("error: recording is empty", file=sys.stderr)
        return 1

    fft_size = int(args.fft)
    fs = info.sample_rate_hz
    dt = (fft_size // 2) / fs
    df = fs / fft_size
    min_duration = 3 * dt if args.min_duration is None else float(args.min_duration)
    min_bandwidth = 3 * df if args.min_bandwidth is None else float(args.min_bandwidth)
    window_s = x.size / fs

    bursts = detect_bursts_from_iq(
        x, fs, info.center_freq_hz, fft_size=fft_size,
        threshold_db=float(args.threshold),
        min_duration_s=min_duration, min_bandwidth_hz=min_bandwidth,
    )
    groups = classify_clusters(
        bursts, window_s=window_s, cluster_gap_hz=float(args.cluster_gap),
        band_hint=args.band, top_k=int(args.top),
    )

    print(f"# {info}")
    print(f"# {x.size} samples, {_fmt_s(window_s)}, STFT {fft_size} "
          f"({_fmt_hz(df)} x {_fmt_s(dt)} cells), threshold {args.threshold:g} dB")
    print(f"# gates: duration >= {_fmt_s(min_duration)}, bandwidth >= {_fmt_hz(min_bandwidth)}")
    print(f"# {len(bursts)} burst(s) in {len(groups)} emitter group(s)"
          + (f", band hint {args.band}" if args.band else ""))
    if not groups:
        print("\nnothing detected: lower --threshold or relax the gates")

    payload: dict[str, Any] = {
        "recording": str(args.recording),
        "sample_rate_hz": fs,
        "center_freq_hz": info.center_freq_hz,
        "window_s": window_s,
        "n_bursts": len(bursts),
        "band_hint": args.band,
        "emitters": [],
    }
    for index, (feats, cands) in enumerate(groups, start=1):
        centre = feats.occupied_span_hz
        print(f"\nemitter {index}: {feats.n_bursts} burst(s), "
              f"bandwidth {_fmt_hz(feats.bandwidth_median_hz)}, "
              f"duration {_fmt_s(feats.duration_median_s)}, "
              f"interval {_fmt_s(feats.interval_median_s)}, "
              f"duty {feats.duty_cycle:.3f}, "
              f"{feats.n_distinct_centers} centre(s), "
              f"hop rate {feats.hop_rate_hz:.1f} Hz, span {_fmt_hz(centre)}")
        for cand in cands:
            flag = "" if cand.in_band else " [out of band]"
            print(f"  {cand.score:5.2f}  {cand.display:<38} "
                  f"{cand.decodability:<12}{flag}")
            print(f"         {cand.explanation}")
        if len(cands) > 1:
            print(f"  margin to the runner-up: {margin(cands):.2f}")
        payload["emitters"].append({
            "features": feats.to_dict(),
            "candidates": [c.to_dict() for c in cands],
        })

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        print(f"\n# wrote {args.json_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
