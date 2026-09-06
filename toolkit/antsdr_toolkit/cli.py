"""``antsdr-tk`` command line: inspect and replay SigMF captures.

Subcommands are registered in :data:`COMMANDS`; adding one means writing a
``configure(parser)`` / ``run(args) -> int`` pair and appending a
:class:`Command`. Heavy imports happen inside the ``run`` functions so
``antsdr-tk --help`` stays instant and never touches hardware libraries.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from . import __version__

_POWER_FLOOR = 1e-24  # -240 dBFS: keeps log10 finite for all-zero chunks


def power_db(power: float) -> float:
    """10*log10 of a linear power relative to full scale 1.0, floored."""
    return 10.0 * math.log10(max(float(power), _POWER_FLOOR))


def _mhz(hz: float) -> str:
    return f"{hz / 1e6:.6f} MHz"


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    configure: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace], int]


# --------------------------------------------------------------------------
# info
# --------------------------------------------------------------------------
def _configure_info(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", help="SigMF stem, .sigmf-meta or .sigmf-data")
    parser.add_argument("--json", action="store_true", help="print as JSON")


def _run_info(args: argparse.Namespace) -> int:
    from .io.sigmf_io import SigmfReader

    with SigmfReader(args.path, mmap=True) as reader:
        info = reader.info
        captures = reader.metadata.get("captures") or [{}]
        row = {
            "data_file": str(reader.data_path),
            "meta_file": str(reader.meta_path),
            "hardware": info.hardware,
            "datatype": reader.datatype.name,
            "sample_rate_hz": info.sample_rate_hz,
            "center_freq_hz": info.center_freq_hz,
            "bandwidth_hz": info.bandwidth_hz,
            "rx_channels": list(info.rx_channels),
            "gain_db": info.gain_db,
            "n_samples": reader.n_samples,
            "duration_s": reader.duration_s,
            "datetime_utc": captures[0].get("core:datetime"),
            "n_annotations": len(reader.annotations),
            "description": info.description,
        }
    if args.json:
        print(json.dumps(row, indent=2))
        return 0
    gain = "n/a" if row["gain_db"] is None else f"{row['gain_db']:.1f} dB"
    lines = [
        ("data file", row["data_file"]),
        ("hardware", row["hardware"]),
        ("datatype", row["datatype"]),
        ("sample rate", _mhz(row["sample_rate_hz"])),
        ("center freq", _mhz(row["center_freq_hz"])),
        ("bandwidth", _mhz(row["bandwidth_hz"])),
        ("channels", ", ".join(str(c) for c in row["rx_channels"])),
        ("gain", gain),
        ("samples", f"{row['n_samples']} per channel"),
        ("duration", f"{row['duration_s']:.6f} s"),
        ("datetime", row["datetime_utc"] or "n/a"),
        ("annotations", str(row["n_annotations"])),
        ("description", row["description"] or "-"),
    ]
    for key, value in lines:
        print(f"{key:<13}{value}")
    return 0


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------
def _configure_replay(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", help="SigMF stem, .sigmf-meta or .sigmf-data")
    parser.add_argument("--chunk", type=int, default=65536, metavar="N", help="samples per chunk")
    parser.add_argument("--max-chunks", type=int, default=None, metavar="M",
                        help="stop after M chunks")
    parser.add_argument("--channel", type=int, default=None, metavar="C", help="replay one channel")
    parser.add_argument("--loop", action="store_true", help="wrap around (needs --max-chunks)")


def _run_replay(args: argparse.Namespace) -> int:
    from .device.file_source import SigmfFileSource

    if args.chunk <= 0:
        raise ValueError("--chunk must be positive")
    if args.loop and args.max_chunks is None:
        raise ValueError("--loop replays forever; give --max-chunks")
    with SigmfFileSource(args.path, loop=args.loop, channel=args.channel) as src:
        rate = src.info.sample_rate_hz
        print(f"# {src.info}")
        total = 0
        n_chunks = 0
        chunks = itertools.islice(src.iter_chunks(args.chunk), args.max_chunks)
        for index, chunk in enumerate(chunks):
            n = chunk.shape[-1]
            re = chunk.real.astype(np.float64)
            im = chunk.imag.astype(np.float64)
            power = re * re + im * im  # linear power per sample, full scale 1.0
            print(
                f"chunk {index:6d}  t={total / rate:10.6f} s  n={n:7d}  "
                f"rms={power_db(power.mean()):7.2f} dBFS  peak={power_db(power.max()):7.2f} dBFS"
            )
            total += n
            n_chunks = index + 1
        print(f"# {n_chunks} chunks, {total} samples, {total / rate:.6f} s")
    return 0


COMMANDS: tuple[Command, ...] = (
    Command("info", "print StreamInfo, sample count and duration of a SigMF recording",
            _configure_info, _run_info),
    Command("replay", "stream a SigMF recording in chunks and summarise each chunk",
            _configure_replay, _run_replay),
)


# Subcommands that live in their own module because they need heavy or
# optional imports (hardware drivers, scipy).  Each exposes
# ``register(subparsers)`` and sets ``func`` on its own parser.  They are
# imported inside :func:`build_parser` so that one broken or half-installed
# module costs its own subcommand, not the whole CLI.
EXTERNAL_COMMANDS: tuple[str, ...] = (
    "cli_capture", "cli_sweep", "cli_classify", "cli_droneid", "cli_video",
    "cli_remoteid",
)


def _register_external(subparsers: argparse._SubParsersAction) -> list[str]:
    """Register the optional subcommand modules; return the names that failed."""
    import importlib

    failed: list[str] = []
    for name in EXTERNAL_COMMANDS:
        try:
            module = importlib.import_module(f".{name}", __package__)
            module.register(subparsers)
        except Exception:  # noqa: BLE001 - a broken extra must not kill the CLI
            failed.append(name)
    return failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk",
                                     description="ANTSDR E200 drone-detection toolkit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for command in COMMANDS:
        sub = subparsers.add_parser(command.name, help=command.help, description=command.help)
        command.configure(sub)
        sub.set_defaults(_run=command.run)
    _register_external(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``antsdr-tk`` console script; returns the exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    run = getattr(args, "_run", None) or getattr(args, "func", None)
    if run is None:
        parser.print_help()
        return 2
    try:
        return int(run(args))
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
