"""``antsdr-tk sweep``: step a band or channel list and print an activity table.

Registered through :func:`register` (the integrator wires it into
``antsdr_toolkit.cli``).  Heavy imports happen inside :func:`run_sweep` so
``--help`` never touches scipy or a hardware library; the E200 driver is
imported lazily from ``antsdr_toolkit.device.e200`` and only when ``--uri``
is given.

Sample sources: ``--uri ip:192.168.1.10`` opens the ANTSDR E200 through the
Pluto-compatible IIO firmware (passive receive only - the driver never
configures TX); ``--file capture`` replays a SigMF recording as one fixed
dwell at its own centre (retuning is impossible, so ``--band``/``--freqs``
only select which targets are reported).  ``--rate`` defaults to 20 MSPS,
the realistic single-channel host rate of the E200 over 1 GbE.

Family classification runs at **emitter** level, not dwell level. A dwell in
the 2.4 GHz band routinely holds Wi-Fi, a control link and a video downlink at
once, so the bursts are clustered by centre frequency and bandwidth and each
cluster is scored on its own timing and shape. The families column lists the
best candidate for each emitter found, so more than one entry means more than
one transmitter, not more than one guess about the same signal.

An earlier version looked up ``classify_dwell`` on ``antsdr_toolkit.classify``,
which that module has never exported, so the column was always ``-``. Setting
:data:`classifier` still overrides the built-in scorer, which is how a trained
model gets dropped in later (``ADR-0007``).

Sources: https://github.com/lukeswitz/fpv-sdr (scanner defaults: settle
0.08 s, dwell 0.06 s, usable 0.8, 4096-bin PSD),
https://github.com/ALPssdz/RF-Vision-UAV-Tracker (discard buffers after
retune, kurtosis ranking).  Constants verified there; the table layout and
JSON document shape are this toolkit's own.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .device.base import SampleSource
    from .scan.planner import Dwell
    from .scan.sweep import DwellResult

__all__ = ["classifier", "register", "run_sweep"]

classifier: Callable[[DwellResult], Sequence[tuple[str, float]]] | None = None
"""Override the built-in scorer: ``classifier(result) -> [(family, confidence), ...]``."""

_E200_MODULE = "antsdr_toolkit.device.e200"
_E200_CLASS_NAMES = ("E200Source", "AntsdrE200Source", "AntsdrSource", "IioSource")
_TABLE_HEADER = f"{'centre_MHz':>12} {'floor_dB':>9} {'occ':>4} {'bursts':>7} {'kappa':>6} " \
                f"{'score':>7}  families"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``sweep`` subparser; ``args.func(args)`` runs it and returns an exit code."""
    from .scan.bands import list_bands

    p = subparsers.add_parser(
        "sweep",
        help="step the receiver over a band or channel list and rank the dwells by activity",
        description="Stepped-frequency sweep: retune, settle, capture, PSD occupancy, "
                    "kurtosis and burst detection per dwell; dwells are ranked by activity.",
    )
    what = p.add_argument_group("what to sweep")
    what.add_argument("--band", choices=list_bands(), help="named band plan (see --list-bands)")
    what.add_argument("--freqs", metavar="MHZ[,MHZ...]",
                      help="target channel frequencies in MHz, grouped into dwells greedily")
    what.add_argument("--fpv-table", action="store_true",
                      help="targets = the 53 unique fpv-sdr 5.8 GHz analog channel frequencies")
    what.add_argument("--list-bands", action="store_true", help="print the band plans and exit")
    how = p.add_argument_group("receiver and timing")
    how.add_argument("--uri", metavar="URI", help="E200 IIO uri, e.g. ip:192.168.1.10")
    how.add_argument("--file", metavar="PATH", help="SigMF recording to replay instead of hardware")
    how.add_argument("--rate", type=float, default=20e6, metavar="HZ",
                     help="sample rate in Hz (default 20e6, the E200 1 GbE host ceiling)")
    how.add_argument("--gain", type=float, default=None, metavar="DB", help="E200 RX gain in dB")
    how.add_argument("--usable", type=float, default=0.8, metavar="FRAC",
                     help="usable fraction of the sample rate per dwell (default 0.8)")
    how.add_argument("--dwell", type=float, default=0.06, metavar="S",
                     help="capture length per dwell in seconds (default 0.06)")
    how.add_argument("--settle", type=float, default=0.08, metavar="S",
                     help="sleep after each retune in seconds (default 0.08)")
    how.add_argument("--discard", type=int, default=2, metavar="N",
                     help="dwell-length reads discarded after each retune, on top of the "
                          "driver's own flush (default 2)")
    how.add_argument("--runs", type=int, default=1, metavar="N",
                     help="number of full sweeps (default 1; 0 = until the file ends)")
    how.add_argument("--order", choices=("sequential", "random"), default="sequential",
                     help="dwell visiting order per run")
    how.add_argument("--seed", type=int, default=None, help="seed for --order random")
    dsp = p.add_argument_group("analysis")
    dsp.add_argument("--fft", type=int, default=4096, metavar="N", help="PSD size (default 4096)")
    dsp.add_argument("--threshold", type=float, default=6.0, metavar="DB",
                     help="occupancy threshold above the noise floor (default 6)")
    out = p.add_argument_group("output")
    out.add_argument("--json", dest="json_out", metavar="PATH",
                     help="write plan, per-run results and the occupancy map as JSON")
    out.add_argument("--events", metavar="PATH",
                     help="append one DetectionEvent per burst as JSON lines")
    out.add_argument("--sensor-id", default="antsdr-e200-0", help="sensor id stamped on events")
    out.add_argument("--psd", action="store_true", help="include PSD arrays in --json output")
    p.set_defaults(func=run_sweep)


# --------------------------------------------------------------------------- helpers
def _parse_freqs_mhz(text: str) -> list[float]:
    freqs = []
    for token in text.replace(";", ",").split(","):
        token = token.strip()
        if token:
            freqs.append(float(token) * 1e6)
    if not freqs:
        raise ValueError("--freqs needs at least one frequency in MHz")
    return freqs


def _open_e200(uri: str, sample_rate_hz: float, center_freq_hz: float,
               gain_db: float | None) -> SampleSource:
    """Import the E200 driver lazily; the class is looked up by conventional names.

    The driver module is written by another author; ``open_source(uri, ...)``
    is preferred when present, else the first class named in
    ``_E200_CLASS_NAMES`` is constructed with keyword arguments.
    """
    unavailable = (f"E200 driver {_E200_MODULE} is not available: {{exc}}. Install the 'e200' "
                   "extra (pyadi-iio + pylibiio) and the native libiio library, or use --file")
    try:
        mod = importlib.import_module(_E200_MODULE)
    except ImportError as exc:
        raise ValueError(unavailable.format(exc=exc)) from exc
    kwargs: dict[str, Any] = {"sample_rate_hz": sample_rate_hz, "center_freq_hz": center_freq_hz}
    if gain_db is not None:
        kwargs["gain_db"] = gain_db
    factory = getattr(mod, "open_source", None)
    if factory is None:
        for name in _E200_CLASS_NAMES:
            factory = getattr(mod, name, None)
            if factory is not None:
                break
    if factory is None:
        raise ValueError(f"{_E200_MODULE} exposes neither open_source() nor a known source class")
    try:
        return factory(uri, **kwargs)
    except ImportError as exc:  # the driver imports pyadi-iio lazily inside the constructor
        raise ValueError(unavailable.format(exc=exc)) from exc


def _band_hint(center_freq_hz: float) -> str | None:
    """Which signature band a dwell centre falls in, for the classifier."""
    if 2.4e9 <= center_freq_hz <= 2.5e9:
        return "ism-2g4"
    if 5.1e9 <= center_freq_hz <= 6.0e9:
        return "ism-5g8"
    if 8.5e8 <= center_freq_hz <= 9.3e8:
        return "ism-868"
    return None


def _families(result: DwellResult) -> list[tuple[str, float]]:
    """Name the emitters in one dwell, best candidate per emitter.

    A dwell is not one signal. In the 2.4 GHz band it routinely holds Wi-Fi, a
    control link and a video downlink at once, so the classifier runs at
    *emitter* level: bursts are clustered by centre frequency and bandwidth
    first, and each cluster is scored on its own timing and shape. Returning a
    single flat list of families for a whole dwell, which the placeholder this
    replaces did, mixes the statistics of unrelated transmitters and produces
    a confident average of nothing.

    ``classifier`` still overrides this when a caller sets it, which is how a
    trained model would be dropped in later (``ADR-0007``).
    """
    if classifier is not None:
        return [(str(name), float(conf)) for name, conf in classifier(result)]
    if not result.bursts:
        return []
    from .classify.heuristic import classify_clusters

    groups = classify_clusters(
        result.bursts, window_s=result.duration_s,
        band_hint=_band_hint(result.center_freq_hz), top_k=1)
    out: list[tuple[str, float]] = []
    for _features, candidates in groups:
        # The scorer returns an "unknown" pseudo-family when nothing clears
        # its threshold. That is the honest answer, and it must not travel as
        # a family *name*: `scan.events` documents `family` as None when
        # unclassified, and a consumer reading the string "unknown" would
        # take it for a claim about the waveform. The burst is still emitted;
        # only the label is withheld.
        if candidates and candidates[0].family != "unknown":
            out.append((candidates[0].display, float(candidates[0].score)))
    return out


def _format_row(result: DwellResult, families: Sequence[tuple[str, float]]) -> str:
    fam = ", ".join(f"{n}:{c:.2f}" for n, c in families[:3]) or "-"
    return (
        f"{result.center_freq_hz / 1e6:12.3f} {result.noise_floor_db:9.1f} "
        f"{len(result.occupancy):4d} {len(result.bursts):7d} {result.kurtosis:6.2f} "
        f"{result.activity_score:7.1f}  {fam}"
    )


def _build_plan(args: argparse.Namespace) -> list[Dwell]:
    from .scan.bands import fpv_channel_freqs_hz
    from .scan.planner import plan_dwells

    chosen = [bool(args.band), bool(args.freqs), bool(args.fpv_table)]
    if sum(chosen) > 1:
        raise ValueError("give only one of --band, --freqs and --fpv-table")
    if args.band:
        return plan_dwells(args.band, args.rate, usable_fraction=args.usable)
    if args.freqs:
        return plan_dwells(_parse_freqs_mhz(args.freqs), args.rate, usable_fraction=args.usable)
    if args.fpv_table:
        return plan_dwells(fpv_channel_freqs_hz(), args.rate, usable_fraction=args.usable)
    return []


# --------------------------------------------------------------------------- command
def run_sweep(args: argparse.Namespace) -> int:
    """Execute the ``sweep`` subcommand; returns the process exit code."""
    if args.list_bands:
        from .scan.bands import BAND_PLANS

        for band in BAND_PLANS.values():
            print(f"{band.name:<14}{band.f_low_hz / 1e6:10.3f} - {band.f_high_hz / 1e6:9.3f} MHz  "
                  f"{band.note}")
        return 0
    if bool(args.uri) == bool(args.file):
        print("error: give exactly one of --uri (E200) or --file (SigMF)", file=sys.stderr)
        return 2
    if args.runs < 0 or args.dwell <= 0.0 or args.rate <= 0.0:
        print("error: --runs must be >= 0 and --dwell/--rate positive", file=sys.stderr)
        return 2

    import numpy as np

    from . import __version__
    from .scan.events import (
        JsonlEventWriter,
        events_from_dwell,
        rf_port_from_info,
        source_from_info,
    )
    from .scan.sweep import OccupancyMap, Sweeper

    plan = _build_plan(args)
    if args.uri and not plan:
        print("error: --uri needs --band, --freqs or --fpv-table", file=sys.stderr)
        return 2

    if args.file:
        from .device.file_source import SigmfFileSource

        source: SampleSource = SigmfFileSource(args.file)
    else:
        source = _open_e200(args.uri, args.rate, plan[0].center_freq_hz, args.gain)

    rng = np.random.default_rng(args.seed) if args.seed is not None else None
    runs: list[list[DwellResult]] = []
    occupancy = OccupancyMap(threshold_db=args.threshold)
    writer = JsonlEventWriter(args.events) if args.events else None
    try:
        sweeper = Sweeper(
            source, plan or None, dwell_s=args.dwell, settle_s=args.settle,
            discard_buffers=args.discard, fft_size=args.fft, rng=rng,
            usable_fraction=args.usable, order=args.order,
            occupancy_threshold_db=args.threshold,
        )
        info = source.info
        print(f"# {info}")
        print(f"# {len(sweeper.plan)} dwell(s), dwell {args.dwell:.3f} s, settle {args.settle:.3f} s, "
              f"discard {args.discard}, fixed tuning: {sweeper.fixed_tuning}")
        n_runs = None if args.runs == 0 else args.runs
        for run_index, results in enumerate(sweeper.iter_runs(n_runs)):
            runs.append(results)
            occupancy.update(results)
            print(f"# run {run_index}")
            print(_TABLE_HEADER)
            for r in results:
                fams = _families(r)
                print(_format_row(r, fams))
                if writer is not None:
                    writer.write_many(events_from_dwell(
                        r, sensor_id=args.sensor_id, source=source_from_info(info),
                        rf_port=rf_port_from_info(info), families=fams,
                    ))
        if not runs:
            print("# no data (source exhausted before the first dwell)")
        if args.json_out:
            doc = {
                "tool": "antsdr-tk sweep",
                "version": __version__,
                "source": info.to_dict(),
                "settings": {
                    "sample_rate_hz": args.rate, "usable_fraction": args.usable,
                    "dwell_s": args.dwell, "settle_s": args.settle, "discard_buffers": args.discard,
                    "fft_size": args.fft, "occupancy_threshold_db": args.threshold,
                    "order": args.order, "seed": args.seed,
                },
                "plan": [d.to_dict() for d in sweeper.plan],
                "runs": [[r.to_dict(include_psd=args.psd) for r in results] for results in runs],
                "occupancy_map": occupancy.to_dict(),
            }
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2)
                fh.write("\n")
            print(f"# wrote {args.json_out}")
        if writer is not None:
            print(f"# wrote {writer.count} event(s) to {args.events}")
    finally:
        if writer is not None:
            writer.close()
        source.close()
    return 0
