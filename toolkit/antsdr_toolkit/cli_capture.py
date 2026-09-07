"""``antsdr-tk capture``: record IQ from the ANTSDR E200 into a SigMF pair.

The subcommand opens :class:`antsdr_toolkit.device.e200.E200Source`, streams
``--seconds`` worth of samples in ``--buffer``-sized reads and writes them
through :class:`antsdr_toolkit.io.sigmf_io.SigmfRecorder` as ``cf32_le`` at
full scale 1.0 (0 dBFS = 12-bit ADC full scale). Nothing is annotated; the
receiver settings land in the SigMF ``global`` section (``core:hw`` from
``--fw`` through :func:`antsdr_toolkit.hardware.hw_string`, ``antsdr:`` fields
for URI, RF ports, gain mode and buffer size). ``--dry-run`` resolves and
prints the configuration - including the host-link and AD9363 envelope
warnings from :func:`antsdr_toolkit.hardware.check_stream_config` - without
importing the hardware driver.

Integration: :func:`register` adds the subparser to an ``argparse``
``subparsers`` object with ``set_defaults(func=run)``; :func:`main` builds a
standalone parser for ``python -m antsdr_toolkit.cli_capture`` and tests.

Sources: the E200 limits and the ``2r2t`` / clock-calibration notes shown in
``--help`` come from :mod:`antsdr_toolkit.hardware` (MicroPhase antsdr_doc_en,
antsdr-fw-patch, pyadi-iio; see that module for the file references).
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Sequence
from typing import Any

from . import hardware as hw

__all__ = [
    "DEFAULT_RATE_HZ",
    "build_parser",
    "configure",
    "format_config",
    "main",
    "parse_channels",
    "register",
    "resolve_config",
    "run",
]

#: LTE 10 MHz rate: covers a DJI OcuSync carrier and a DroneID burst. It is
#: above the stock IIO firmware's continuous host-link ceiling, so the default
#: tier is "snapshot" (verified: host-streaming-tiers).
DEFAULT_RATE_HZ = 15.36e6
DEFAULT_TIER = "snapshot"
DEFAULT_GAIN_DB = 40.0
DEFAULT_BUFFER = 1 << 18
DEFAULT_DISCARD = 2
DEFAULT_SECONDS = 0.01
_POWER_FLOOR = 1e-24  # -240 dBFS keeps log10 finite for an all-zero capture

HELP = "record IQ from the ANTSDR E200 (pyadi-iio over Ethernet) into a SigMF pair"

EPILOG = f"""\
hardware ({hw.E200.name}, {hw.E200.transceiver}, {hw.E200.adc_bits}-bit):
  channels     0 = {hw.E200.rf_port_name(0)} (IIO voltage0), 1 = {hw.E200.rf_port_name(1)} \
(IIO voltage1; needs 2r2t firmware mode)
  sample rate  {hw.E200.sample_rate_min / 1e6:.3f} .. {hw.E200.sample_rate_max_1ch / 1e6:.2f} MSPS \
single channel, {hw.E200.sample_rate_max_2ch / 1e6:.2f} MSPS per channel with two
  host link    1 GbE. Continuous stream: about {hw.E200.host_ceiling(1) / 1e6:.0f} MSPS \
single channel and {hw.E200.host_ceiling(2) / 1e6:.0f} MSPS per channel with two on the stock \
IIO firmware (CPU-bound in iiod), about {hw.E200.host_ceiling(1, "uhd_sc16") / 1e6:.0f} MSPS on \
the UHD firmware; {hw.E200.host_ceiling(1, "uhd_wire_limit_sc16") / 1e6:.1f} MSPS is the sc16 \
wire limit of 1 GbE
  capture tier '--tier continuous' keeps the link inside those ceilings; '--tier snapshot' \
allows rates up to {hw.E200.sample_rate_max_1ch / 1e6:.2f} MSPS in a single RX buffer. \
Above the IIO host budget, multi-buffer captures are rejected: gaps are not timed.
  LO           {hw.E200.lo_min / 1e6:.0f} MHz .. {hw.E200.lo_max / 1e9:.0f} GHz as configured \
by the firmware (AD9363 datasheet: 325 MHz .. 3.8 GHz, 20 MHz)
  clean rates  {", ".join(f"{r / 1e6:g}" for r in hw.CLEAN_RATES)} MSPS \
(DroneID: {", ".join(f"{r / 1e6:g}" for r in hw.DRONEID_RATES)})
  gain         '--gain-mode manual' writes --gain; slow_attack / fast_attack / hybrid \
let the AGC choose (gain recorded as unknown)
  transmit     never: tx_hardwaregain is forced to {hw.TX_GAIN_OFF_DB:g} dB

enable the second RX chain (run on the device, once):
{hw.FW_SETENV_2R2T}
clock calibration against 10 MHz / PPS on the MMCX:
{hw.CLOCK_CALIBRATION_SYSFS}"""


def parse_channels(text: str) -> tuple[int, ...]:
    """``"0"`` / ``"0,1"`` / ``"1"`` -> tuple of channel indices (argparse ``type``)."""
    if isinstance(text, tuple):
        return tuple(int(c) for c in text)
    try:
        chans = tuple(int(t) for t in str(text).replace(" ", "").split(",") if t != "")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"channels must be comma-separated integers such as '0' or '0,1', got {text!r}"
        ) from None
    if not chans:
        raise argparse.ArgumentTypeError("channels must name at least one RX channel")
    return chans


def configure(parser: argparse.ArgumentParser) -> None:
    """Add the ``capture`` arguments to ``parser``."""
    parser.add_argument(
        "out_stem", metavar="OUT_STEM",
        help="output stem: writes OUT_STEM.sigmf-data and OUT_STEM.sigmf-meta",
    )
    parser.add_argument("--uri", default=hw.E200.default_uri,
                        help=f"libiio context URI (default {hw.E200.default_uri})")
    parser.add_argument("--freq", type=float, required=True, metavar="HZ",
                        help="RX centre frequency in Hz, e.g. 2437e6")
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE_HZ, metavar="SPS",
                        help=f"complex sample rate in Hz (default {DEFAULT_RATE_HZ:g})")
    parser.add_argument("--bw", type=float, default=None, metavar="HZ",
                        help="analog RF filter bandwidth in Hz (default: the sample rate)")
    parser.add_argument("--gain", type=float, default=DEFAULT_GAIN_DB, metavar="DB",
                        help=f"manual RX gain in dB (default {DEFAULT_GAIN_DB:g})")
    parser.add_argument("--gain-mode", choices=hw.GAIN_MODES, default="manual",
                        help="AD9361 gain control mode (default manual)")
    parser.add_argument("--channels", type=parse_channels, default=(0,), metavar="LIST",
                        help="RX channels, comma separated: 0 (SMA), 1 (IPEX) or 0,1")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS, metavar="S",
                        help=f"capture duration in seconds (default {DEFAULT_SECONDS:g})")
    parser.add_argument("--buffer", type=int, default=DEFAULT_BUFFER, metavar="N",
                        help=f"samples per rx() buffer and per write (default {DEFAULT_BUFFER})")
    parser.add_argument("--discard", type=int, default=DEFAULT_DISCARD, metavar="K",
                        help=f"buffers dropped after tuning (default {DEFAULT_DISCARD})")
    parser.add_argument("--tier", choices=tuple(hw.CAPTURE_TIERS), default=DEFAULT_TIER,
                        help=f"capture tier judged against the host link (default {DEFAULT_TIER}); "
                             "continuous = within IIO budget, snapshot = one high-rate RX buffer")
    parser.add_argument("--fw", default="pluto-iio", metavar="TAG",
                        help="firmware personality written into core:hw (default pluto-iio)")
    parser.add_argument("--description", default="", metavar="TEXT",
                        help="free text appended to core:description")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the resolved configuration and exit without touching hardware")


def register(subparsers: Any) -> None:
    """Add the ``capture`` subcommand to an ``argparse`` ``subparsers`` object."""
    parser = subparsers.add_parser(
        "capture", help=HELP, description=HELP, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    configure(parser)
    parser.set_defaults(func=run)


def resolve_config(args: argparse.Namespace) -> dict[str, Any]:
    """Validate the parsed arguments against the E200 limits; ``ValueError`` on violation."""
    from .io.sigmf_io import sigmf_paths

    rate = float(args.rate)
    fc = float(args.freq)
    bw = rate if args.bw is None else float(args.bw)
    channels = parse_channels(args.channels)
    seconds = float(args.seconds)
    if not seconds > 0.0:
        raise ValueError(f"--seconds must be positive, got {seconds}")
    n_samples = round(seconds * rate)
    if n_samples < 1:
        raise ValueError(f"--seconds {seconds} at {rate:g} SPS rounds to zero samples")
    if int(args.buffer) <= 0:
        raise ValueError(f"--buffer must be positive, got {args.buffer}")
    if int(args.discard) < 0:
        raise ValueError(f"--discard must be >= 0, got {args.discard}")
    tier = str(getattr(args, "tier", DEFAULT_TIER))
    warnings = hw.check_stream_config(
        rate, fc, channels=channels, rf_bandwidth_hz=bw,
        gain_mode=args.gain_mode, gain_db=args.gain, tier=tier,
    )
    data_path, meta_path = sigmf_paths(args.out_stem)
    return {
        "uri": str(args.uri),
        "hardware": hw.hw_string(str(args.fw)),
        "firmware": str(args.fw),
        "sample_rate_hz": rate,
        "center_freq_hz": fc,
        "rf_bandwidth_hz": bw,
        "channels": channels,
        "rf_ports": [hw.E200.rf_port_name(c) for c in channels],
        "gain_mode": str(args.gain_mode),
        "gain_db": float(args.gain),
        "buffer_size": int(args.buffer),
        "discard_buffers": int(args.discard),
        "tier": tier,
        "seconds": seconds,
        "n_samples": int(n_samples),
        "description": str(args.description),
        "data_path": str(data_path),
        "meta_path": str(meta_path),
        "warnings": warnings,
    }


def format_config(cfg: dict[str, Any]) -> str:
    """Human-readable table of :func:`resolve_config` output."""
    gain = (
        f"{cfg['gain_db']:.1f} dB" if cfg["gain_mode"] == "manual" else "AGC (recorded as unknown)"
    )
    channels = ", ".join(f"{c} ({p})" for c, p in zip(cfg["channels"], cfg["rf_ports"]))
    rows = [
        ("uri", cfg["uri"]),
        ("hardware", cfg["hardware"]),
        ("sample rate", f"{cfg['sample_rate_hz'] / 1e6:.6f} MHz"),
        ("center freq", f"{cfg['center_freq_hz'] / 1e6:.6f} MHz"),
        ("rf bandwidth", f"{cfg['rf_bandwidth_hz'] / 1e6:.6f} MHz"),
        ("channels", channels),
        ("gain mode", cfg["gain_mode"]),
        ("gain", gain),
        ("buffer", f"{cfg['buffer_size']} samples per channel"),
        ("discard", f"{cfg['discard_buffers']} buffers after tuning"),
        ("tier", cfg["tier"]),
        ("duration", f"{cfg['seconds']:.6f} s ({cfg['n_samples']} samples per channel)"),
        ("data file", cfg["data_path"]),
        ("meta file", cfg["meta_path"]),
        ("warnings", "; ".join(cfg["warnings"]) or "none"),
    ]
    return "\n".join(f"{key:<13}{value}" for key, value in rows)


def _db(power: float) -> float:
    return 10.0 * math.log10(max(float(power), _POWER_FLOOR))


def run(args: argparse.Namespace) -> int:
    """Entry point bound by :func:`register`; returns the process exit code."""
    cfg = resolve_config(args)
    for message in cfg["warnings"]:
        print(f"warning: {message}", file=sys.stderr)
    if args.dry_run:
        print("# dry run: hardware not touched")
        print(format_config(cfg))
        return 0

    # No hardware timestamps/overflow reports are available in this driver.
    # Do not join potentially discontinuous high-rate buffers into one timeline.
    ceiling = hw.E200.host_ceiling(len(cfg["channels"]))
    if cfg["sample_rate_hz"] > ceiling:
        if cfg["tier"] != "snapshot" or cfg["n_samples"] > cfg["buffer_size"]:
            raise ValueError(
                "above the IIO host budget, capture requires --tier snapshot and "
                "one RX buffer: reduce --seconds or increase --buffer to at least "
                f"{cfg['n_samples']}. Multi-buffer gap timing is not implemented")

    import numpy as np

    from .device.e200 import E200Source
    from .io.sigmf_io import SigmfRecorder

    try:
        source = E200Source(
            cfg["uri"],
            sample_rate_hz=cfg["sample_rate_hz"],
            center_freq_hz=cfg["center_freq_hz"],
            rf_bandwidth_hz=cfg["rf_bandwidth_hz"],
            gain_mode=cfg["gain_mode"],
            gain_db=cfg["gain_db"],
            channels=cfg["channels"],
            buffer_size=cfg["buffer_size"],
            discard_buffers=cfg["discard_buffers"],
            firmware=cfg["firmware"],
        )
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    n_total = cfg["n_samples"]
    chunk_size = cfg["buffer_size"]
    interrupted = False
    with source as src:
        info = src.info
        if cfg["description"]:
            info = info.replace(description=f"{info.description}; {cfg['description']}")
        print(f"# {info}")
        acc_power = 0.0
        peak_power = 0.0
        written = 0
        t0 = time.perf_counter()
        extra = dict(src.sigmf_extra_global())
        extra.update({
            "antsdr:capture_tier": cfg["tier"],
            "antsdr:sample_continuity": "unverified",
            "antsdr:timestamp_source": "host_wall_clock_not_hardware",
        })
        with SigmfRecorder(args.out_stem, info, extra_global=extra) as rec:
            try:
                while written < n_total:
                    chunk = src.read(min(chunk_size, n_total - written))
                    rec.write(chunk)
                    re = chunk.real.astype(np.float64)
                    im = chunk.imag.astype(np.float64)
                    power = re * re + im * im
                    acc_power += float(power.sum())
                    peak_power = max(peak_power, float(power.max()))
                    written += int(chunk.shape[-1])
            except KeyboardInterrupt:
                interrupted = True
        elapsed = time.perf_counter() - t0
        gains = ", ".join(f"{g:.1f} dB" for g in src.hardware_gain_db())

    n_values = max(written * info.n_channels, 1)
    duration = written / info.sample_rate_hz
    speed = duration / elapsed if elapsed > 0 else float("inf")
    print(f"wrote {written} samples per channel ({duration:.6f} s) in {elapsed:.2f} s "
          f"({speed:.2f}x realtime){' [interrupted]' if interrupted else ''}")
    print(f"  data   {rec.data_path}")
    print(f"  meta   {rec.meta_path}")
    print(f"  level  rms {_db(acc_power / n_values):.2f} dBFS, peak {_db(peak_power):.2f} dBFS")
    print(f"  gain   {gains} (hardware readback, channels {list(info.rx_channels)})")
    return 130 if interrupted else 0


def build_parser() -> argparse.ArgumentParser:
    """Standalone ``antsdr-tk``-style parser holding only the ``capture`` subcommand."""
    parser = argparse.ArgumentParser(prog="antsdr-tk", description=HELP)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``capture`` standalone (``python -m antsdr_toolkit.cli_capture capture ...``)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        return int(func(args))
    except (ValueError, OSError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

