"""``antsdr-tk remoteid``: decode standard Remote ID from captured Wi-Fi frames.

Reads 802.11 frames from a pcap or pcapng file, or raw hex on the command
line, and prints the drone and operator identity each one carries.

Where the frames come from
--------------------------
Two different payloads ride in these beacons and this command reads both.
The ASD-STAN element (OUI FA:0B:BC) is standard Remote ID, the identity the
law compels from class C1 upward.  The DJI element (OUI 26:37:12) is DJI's own
proprietary DroneID, unregulated, carried by its Wi-Fi-link aircraft.  An
airframe with no Remote ID obligation may still emit the second, which makes
it worth looking for on anything with a Wi-Fi flight mode.

Not from the E200.  DJI broadcasts standard Remote ID as an 802.11 Beacon, and
openwifi on the E200 is OFDM-only, so it cannot demodulate the 802.11b rates
that reference Remote ID beacons use on 2.4 GHz *(verified: verdict 6)*.  The
receiver is a commodity Wi-Fi adapter in monitor mode::

    sudo ip link set wlan1 down
    sudo iw wlan1 set monitor control
    sudo ip link set wlan1 up
    sudo iw wlan1 set channel 6
    sudo tcpdump -i wlan1 -w rid.pcap type mgt subtype beacon

Then ``antsdr-tk remoteid rid.pcap``.  Which channel to sit on is not
established for DJI: 2.4 GHz channel 6 and 5 GHz channel 149 are the usual
guesses, so hop if you can.

What a result does and does not prove
-------------------------------------
Remote ID is unauthenticated.  A decoded serial number is a *claim* made by
whatever transmitted the frame, and spoofing it needs no special equipment.
Treat it as one observation among several, not as ground truth.

Silence proves even less, and for three separate reasons.  The EU obligation
attaches to the class mark rather than to a weight, so C1 and above must
broadcast while C0 need not; a DJI Neo or a Mini 4 Pro as shipped is generally
reported silent on the standard element even while airborne.  But exemption
permits silence without compelling it, a C0 aircraft may broadcast anyway, and
DJI offers a C1 label upgrade that turns the obligation on.  So an empty
result is not an empty sky, and the DJI element is worth checking separately
on anything with a Wi-Fi flight mode.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
from typing import Any

__all__ = ["build_parser", "configure", "iter_pcap_frames", "main", "register", "run"]

HELP = "decode Remote ID and DJI DroneID from captured Wi-Fi frames"

_PCAP_MAGIC = {0xA1B2C3D4: ("<", 1e-6), 0xD4C3B2A1: ("<", 1e-6),
               0xA1B23C4D: ("<", 1e-9), 0x4D3CB2A1: ("<", 1e-9)}
#: Link types that carry 802.11 frames: raw 802.11, and 802.11 with radiotap.
_WIFI_LINKTYPES = {105, 127}


def iter_pcap_frames(path: str):
    """Yield ``(timestamp_s, frame_bytes)`` from a classic pcap or a pcapng.

    Written by hand rather than through scapy or dpkt so that reading a
    capture needs nothing beyond the standard library.  Only the block types a
    Wi-Fi capture actually uses are handled; anything else is skipped.
    """
    with open(path, "rb") as handle:
        blob = handle.read()
    if len(blob) < 4:
        raise ValueError(f"{path}: too short to be a capture file")

    magic = struct.unpack("<I", blob[:4])[0]
    if magic == 0x0A0D0D0A:
        yield from _iter_pcapng(blob, path)
        return
    big = struct.unpack(">I", blob[:4])[0]
    for candidate, order in ((magic, "<"), (big, ">")):
        if candidate in _PCAP_MAGIC:
            _, resolution = _PCAP_MAGIC[candidate]
            yield from _iter_pcap(blob, order, resolution, path)
            return
    raise ValueError(f"{path}: not a pcap or pcapng file (magic {magic:#010x})")


def _iter_pcap(blob: bytes, order: str, resolution: float, path: str):
    link_type = struct.unpack_from(order + "I", blob, 20)[0]
    if link_type not in _WIFI_LINKTYPES:
        raise ValueError(f"{path}: link type {link_type} is not 802.11 "
                         f"(expected one of {sorted(_WIFI_LINKTYPES)})")
    offset = 24
    while offset + 16 <= len(blob):
        seconds, fraction, captured, _original = struct.unpack_from(order + "IIII", blob, offset)
        offset += 16
        if offset + captured > len(blob):
            return
        yield seconds + fraction * resolution, blob[offset:offset + captured]
        offset += captured


def _iter_pcapng(blob: bytes, path: str):
    offset, order, resolution = 0, "<", 1e-6
    while offset + 12 <= len(blob):
        block_type = struct.unpack_from(order + "I", blob, offset)[0]
        if block_type == 0x0A0D0D0A:  # section header: settles the byte order
            order = "<" if struct.unpack_from("<I", blob, offset + 8)[0] == 0x1A2B3C4D else ">"
        length = struct.unpack_from(order + "I", blob, offset + 4)[0]
        if length < 12 or offset + length > len(blob):
            return
        if block_type == 6:  # enhanced packet block
            high, low, captured = struct.unpack_from(order + "III", blob, offset + 12)
            start = offset + 28
            yield ((high << 32) | low) * resolution, blob[start:start + captured]
        offset += length
    if offset == 0:
        raise ValueError(f"{path}: no readable pcapng blocks")


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", nargs="?",
                        help="pcap/pcapng file of 802.11 frames")
    parser.add_argument("--hex", dest="hex_frame", default=None, metavar="HEX",
                        help="decode one frame given as hex instead of reading a file")
    parser.add_argument("--json", dest="json_path", default=None, metavar="PATH",
                        help="write every decoded beacon as JSON")
    parser.add_argument("--unique", action="store_true",
                        help="print each identifier once instead of every beacon")
    parser.add_argument("--dji-extended", action="store_true",
                        help="also decode the DJI element's fields past the 30 bytes "
                             "the reference parser trusts; the layout is inferred, "
                             "so results are marked unverified")


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("remoteid", help=HELP, description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    configure(parser)
    parser.set_defaults(func=run, _run=run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk remoteid", description=HELP)
    configure(parser)
    return parser


def _show(summary: dict[str, Any], count: int | None = None) -> None:
    seen = f"  ({count} beacons)" if count else ""
    label = {"dji_droneid_wifi": "DJI DroneID over Wi-Fi",
             "standard_remote_id": "standard Remote ID"}.get(summary.get("kind"), "")
    print(f"\n{summary.get('uas_id') or '<no identifier>'}"
          f"  [{summary.get('id_type', '?')}]{seen}"
          + (f"   {label}" if label else ""))
    position = summary.get("position")
    if position:
        print(f"  drone     {position[0]:.6f}, {position[1]:.6f}"
              f"   height {_number(summary.get('height_m'), 'm')}"
              f"  altitude {_number(summary.get('altitude_geo_m'), 'm')}")
    operator = summary.get("operator_position")
    if operator:
        print(f"  operator  {operator[0]:.6f}, {operator[1]:.6f}")
    bits = [f"status {summary.get('status', '?')}",
            f"speed {_number(summary.get('speed_h_m_s'), 'm/s')}"]
    if summary.get("class_eu"):
        bits.append(f"class {summary['class_eu']}")
    if summary.get("operator_id"):
        bits.append(f"operator id {summary['operator_id']}")
    print("  " + "  ".join(bits))
    if summary.get("ssid"):
        print(f"  ssid {summary['ssid']}  mac {summary.get('transmitter_mac')}")


def _number(value: Any, unit: str) -> str:
    return "unknown" if value is None else f"{value:.1f} {unit}"


def run(args: argparse.Namespace) -> int:
    from .remoteid import wifi

    frames: list[tuple[float, bytes]] = []
    if args.hex_frame:
        frames = [(0.0, bytes.fromhex(args.hex_frame.replace(" ", "").replace(":", "")))]
    elif args.source:
        if not pathlib.Path(args.source).exists():
            print(f"error: {args.source}: no such file", file=sys.stderr)
            return 1
        frames = list(iter_pcap_frames(args.source))
        print(f"# {args.source}: {len(frames)} frame(s)")
    else:
        print("error: give a capture file or --hex", file=sys.stderr)
        return 1

    from .remoteid import dji_wifi

    decoded: list[dict[str, Any]] = []
    malformed = 0
    n_standard = n_dji = 0
    for timestamp, frame in frames:
        # A frame can carry either element, and they are different things: the
        # ASD-STAN one is the identity the law compels, the DJI one is DJI's
        # own proprietary DroneID riding in a beacon. Both are checked.
        try:
            beacon = wifi.parse_beacon(frame)
        except ValueError as exc:
            malformed += 1
            print(f"# malformed Open Drone ID element: {exc}", file=sys.stderr)
            beacon = None
        if beacon is not None:
            summary = beacon.summary()
            summary["timestamp"] = timestamp
            summary["kind"] = "standard_remote_id"
            decoded.append(summary)
            n_standard += 1
            continue
        try:
            dji = dji_wifi.parse_dji_beacon(frame, extended=bool(args.dji_extended))
        except ValueError as exc:
            malformed += 1
            print(f"# malformed DJI DroneID element: {exc}", file=sys.stderr)
            continue
        if dji is None:
            continue
        summary = dji.to_dict()
        summary["timestamp"] = timestamp
        summary["kind"] = "dji_droneid_wifi"
        summary["uas_id"] = dji.serial
        summary["id_type"] = "serial_number"
        decoded.append(summary)
        n_dji += 1

    kinds = []
    if n_standard:
        kinds.append(f"{n_standard} standard Remote ID")
    if n_dji:
        kinds.append(f"{n_dji} DJI DroneID (Wi-Fi)")
    print(f"# {len(decoded)} beacon(s)" + (": " + ", ".join(kinds) if kinds else "")
          + (f", {malformed} malformed" if malformed else ""))
    if not decoded:
        print("# nothing decoded. Remember that EU class C0 aircraft under 250 g\n"
              "# are exempt and broadcast nothing, so silence is not absence.",
              file=sys.stderr)

    if args.unique:
        groups: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = {}
        for summary in decoded:
            key = summary.get("uas_id") or summary.get("transmitter_mac") or "?"
            groups[key] = summary
            counts[key] = counts.get(key, 0) + 1
        for key, summary in groups.items():
            _show(summary, counts[key])
        print(f"\n# {len(groups)} distinct identifier(s)")
    else:
        for summary in decoded:
            _show(summary)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(decoded, handle, indent=1, default=str)
        print(f"\n# wrote {args.json_path}")
    return 0 if decoded else 1


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
