"""Reproduce the public RUB-SysSec decode checks through the actual CLI.

Run from antsdr/toolkit after installation (or PYTHONPATH=.):
  python examples/validate_real_droneid.py --samples /path/to/DroneSecurity/samples

No downloads or hardware access. Input hashes are checked before processing.
The input files are extracted bursts, not continuous RF timelines.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import platform
import tempfile
from pathlib import Path

import numpy as np
import scipy

from antsdr_toolkit import cli_droneid
from antsdr_toolkit.device.base import StreamInfo
from antsdr_toolkit.io.sigmf_io import write_sigmf

UPSTREAM_COMMIT = "9ff819843bee48fb140a0704ec78aff757896dea"
SAMPLES = {
    "mini2_sm": {
        "sha256": "5a17913cb11cde2919347054700345c9e5595eaff7818980d332b8ac8910bc55",
        "bytes": 5820000, "decoded": 10,
    },
    "mavic_air_2": {
        "sha256": "623fa40f190d3fd859ec2fd62b379ad9a01a0485db3179ae29ac2e3c7a070450",
        "bytes": 1802240, "decoded": 2,
    },
}


def check_result(name: str, result: dict) -> list[str]:
    """Check CRC-valid CLI output against published positions and branch baseline.

    Counts 10/2 are regression targets from this branch, not upstream claims.
    Upstream publishes 7/1. Coordinate tolerance allows its rounded conversion
    constant; it is not a claim of GPS accuracy.
    """
    errors = []
    frames = [b["frame"] for b in result["bursts"] if b.get("frame")]
    valid = [f for f in frames if f["crc16_ok"] and f["crc24_ok"]]
    if len(valid) != SAMPLES[name]["decoded"]:
        errors.append(f"expected {SAMPLES[name]['decoded']} valid frames, got {len(valid)}")
    if len(frames) != len(valid):
        errors.append("CLI exported invalid payload fields")
    if result["n_decoded"] != len(valid):
        errors.append("decoded count disagrees with valid frame records")
    sequences = [f["sequence"] for f in valid]
    # Retransmissions may repeat a sequence. Check duplicate detections in
    # the same processed band, not uniqueness of the transmitter's counter.
    locations = [(b["band_offset_hz"], b["detection"]["sample_start"])
                 for b in result["bursts"] if b.get("frame")]
    if len(locations) != len(set(locations)):
        errors.append("duplicate detection at the same band/sample location")
    if name == "mini2_sm":
        for f in valid:
            if f["drone_lat"] is not None or f["drone_lon"] is not None:
                errors.append("Mini 2 fixture must preserve absent drone GPS fix")
            for key, expected in (("pilot_lat", 51.447176178716916),
                                  ("pilot_lon", 7.266528392911369)):
                if f[key] is None or abs(f[key] - expected) > 5e-5:
                    errors.append(f"Mini 2 {key} differs from published reference")
    else:
        if set(sequences) != {589, 591}:
            errors.append(f"expected Mavic sequences 589 and 591, got {sequences}")
        for f in valid:
            if f["sequence"] != 591:
                continue
            for key, expected in (("drone_lat", 51.44633393111904),
                                  ("drone_lon", 7.26721594197086),
                                  ("pilot_lat", 51.44620788045814),
                                  ("pilot_lon", 7.267101350460944)):
                if f[key] is None or abs(f[key] - expected) > 5e-5:
                    errors.append(f"Mavic {key} differs from published reference")
            if abs(f["height_m"] - 12.8) > 0.02:
                errors.append("Mavic height differs from published 12.8 m")
    return errors


def validate(samples: Path, methods: list[str]) -> dict:
    report = {
        "upstream_commit": UPSTREAM_COMMIT,
        "python": platform.python_version(), "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scope": "extracted OcuSync 2 bursts; no timing, range, O3/O4 or hardware claims",
        "runs": [], "passed": True,
    }
    for name, spec in SAMPLES.items():
        data = (samples / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != spec["bytes"] or digest != spec["sha256"]:
            raise ValueError(f"{name}: input size/hash mismatch; refusing to decode")
        iq = np.frombuffer(data, dtype="<c8")
        with tempfile.TemporaryDirectory(prefix="antsdr-validation-") as work:
            stem = Path(work) / name
            # Unknown RF centre explicitly marked. Zero is only a baseband origin.
            write_sigmf(stem, iq, StreamInfo(50e6, 0.0, hardware="RUB-SysSec recording"),
                        extra_global={"antsdr:rf_center_known": False,
                                      "antsdr:sample_continuity": "extracted_bursts"})
            for method in methods:
                output = Path(work) / "decoded.json"
                log = io.StringIO()
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    status = cli_droneid.main([str(stem), "--method", method,
                                              "--json", str(output), "--quiet"])
                if status != 0:
                    raise RuntimeError(f"{name}/{method}: CLI failed: {log.getvalue()}")
                result = json.loads(output.read_text())
                errors = check_result(name, result)
                report["runs"].append({"sample": name, "sha256": digest,
                                       "method": method, "decoded": result["n_decoded"],
                                       "sequences": [b["frame"]["sequence"]
                                                     for b in result["bursts"] if b["frame"]],
                                       "errors": errors, "passed": not errors})
                report["passed"] = report["passed"] and not errors
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--methods", nargs="+", choices=("zc", "cp", "both"), default=["both"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate(args.samples, args.methods)
    except (OSError, ValueError, RuntimeError) as exc:
        report = {"passed": False, "error": str(exc)}
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
