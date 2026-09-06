"""``antsdr-tk fleet``: what can I actually get from this drone?

Prints, per airframe, the link generation, the EU class label and every route
to its identity. With no arguments it prints the whole table.

The answer that matters most is the empty one. An OcuSync 4 airframe marked
class C0 has an encrypted proprietary identity and no obligation to broadcast
a standard one, so it can be detected and tracked but usually not named.

Read "no identity" as "no published means yields a name", not as "invisible"
and not as a guarantee of silence. The obligation attaches to the class mark
rather than to the weight, a C0 aircraft may broadcast anyway, and DJI offers
an official C1 label upgrade for some models that turns the obligation on. A
Mini 4 Pro is in or out of this position depending on both its battery and
whether that upgrade was taken.

Examples::

    antsdr-tk fleet                       # the whole table
    antsdr-tk fleet "Mini 4 Pro" neo      # just these two, with the reasoning
    antsdr-tk fleet --tier B              # everything that is presence-only
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from typing import Any

__all__ = ["build_parser", "configure", "main", "register", "run"]

HELP = "what an E200 can detect, decode or identify for a given DJI airframe"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("airframe", nargs="*",
                        help="one or more airframes; omit for the whole table")
    parser.add_argument("--tier", choices=("A", "B", "C", "D"), default=None,
                        help="show only airframes in this observation tier")
    parser.add_argument("--json", dest="json_path", default=None, metavar="PATH",
                        help="write the selected rows as JSON")


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("fleet", help=HELP, description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    configure(parser)
    parser.set_defaults(func=run, _run=run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk fleet", description=HELP)
    configure(parser)
    return parser


def run(args: argparse.Namespace) -> int:
    from . import fleet

    if args.airframe:
        chosen, missing = [], []
        for name in args.airframe:
            found = fleet.lookup(name)
            (chosen if found else missing).append(found or name)
        for name in missing:
            print(f"# not in the table: {name!r}", file=sys.stderr)
        if not chosen:
            print("# nothing matched. Run without arguments to see the table.",
                  file=sys.stderr)
            return 1
    else:
        chosen = list(fleet.AIRFRAMES.values())

    if args.tier:
        chosen = [a for a in chosen if a.tier == args.tier]
        if not chosen:
            print(f"# no airframe in tier {args.tier}", file=sys.stderr)
            return 1

    detailed = bool(args.airframe) or len(chosen) <= 3
    if detailed:
        for airframe in chosen:
            _detail(airframe, fleet)
    else:
        print(f"{'airframe':24} {'link':26} {'class':6} {'g':>6} {'tier':5} identity")
        print("-" * 100)
        for airframe in chosen:
            sources = fleet.identity_sources(_key(airframe, fleet))
            summary = _short(sources)
            weight = "" if airframe.takeoff_weight_g is None else f"{airframe.takeoff_weight_g:6.0f}"
            print(f"{airframe.name:24} {airframe.link[:26]:26} "
                  f"{airframe.eu_class or '-'!s:6} {weight:>6} {airframe.tier:5} {summary}")
        print(f"\n# {len(chosen)} airframe(s). Tiers: "
              + "; ".join(f"{k} = {v}" for k, v in fleet.TIERS.items()))

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump([a.to_dict() for a in chosen], handle, indent=1)
        print(f"\n# wrote {args.json_path}")
    return 0


def _key(airframe: Any, fleet: Any) -> str:
    for key, value in fleet.AIRFRAMES.items():
        if value is airframe:
            return key
    return airframe.name


def _short(sources: list[str]) -> str:
    if not sources:
        return "none: detectable, not identifiable"
    return sources[0].split("(")[0].strip()


def _detail(airframe: Any, fleet: Any) -> None:
    print(f"\n{airframe.name}")
    print(f"  link          {airframe.link}")
    weight = "unknown" if airframe.takeoff_weight_g is None else f"{airframe.takeoff_weight_g:.0f} g"
    label = airframe.eu_class or "none (legacy, no class mark)"
    print(f"  EU class      {label}, {weight}"
          + ("   no Remote ID obligation as shipped" if airframe.remote_id_exempt else ""))
    encrypted = {True: "encrypted", False: "plaintext", None: "not established"}
    print(f"  DroneID       {encrypted[airframe.droneid_encrypted]}")
    print(f"  tier {airframe.tier}        {fleet.TIERS[airframe.tier]}")

    sources = fleet.identity_sources(_key(airframe, fleet))
    if sources:
        print("  identity from")
        for source in sources:
            print(f"    - {source}")
    else:
        print("  identity      NONE. No published means yields a serial number or a\n"
              "                position for this airframe. It can be detected, timed,\n"
              "                measured and tracked as a session, and that is all.")
    if airframe.note:
        print(textwrap.fill(airframe.note, 78, initial_indent="  ",
                            subsequent_indent="  "))
    print(f"  confidence    {airframe.confidence}")


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
