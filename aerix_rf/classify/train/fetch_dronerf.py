#!/usr/bin/env python3
"""Fetch a representative DroneRF subset and prepare truncated CSVs.

DroneRF (Al-Sa'd et al., Mendeley 10.17632/f4c2b4n755.1) ships as .rar archives
of comma-separated RF amplitude series, one archive per (drone, band). The full
set is ~4 GB. This grabs a subset (background + 3 drones, both bands), streams a
capped prefix of a few inner CSV segments out of each archive (genuine DroneRF
CSVs, just shorter), verifies the sha256, and deletes the .rar. Data is
gitignored.

The archives use a RAR3 compression method p7zip's `7z` cannot decode
("Unsupported Method"); libarchive can, so extraction goes through libarchive-c.

Run (private env, ephemeral deps):

    export UV_PROJECT_ENVIRONMENT=.venv-train
    uv run --with libarchive-c,requests \
      python -m aerix_rf.classify.train.fetch_dronerf

To fetch the FULL dataset instead, list every file id from the public API
(see README) and drop the per-rar segment cap (`SEGMENTS_PER_RAR`/`CAP_BYTES`).
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import libarchive

# .../aerix_rf/classify/train/fetch_dronerf.py -> aerix-rf/
_PKG_ROOT = Path(__file__).resolve().parents[3]
DRONERF_DIR = _PKG_ROOT / "data" / "dronerf"   # gitignored
CSV_DIR = DRONERF_DIR / "csv"
RAW_DIR = DRONERF_DIR / "raw"

# Cap per inner CSV: ~48 MB of text ≈ 8.3 M samples ≈ 0.21 s at 40 MS/s.
CAP_BYTES = 48 * 1024 * 1024
# How many leading segments to pull from each archive (balances the classes).
SEGMENTS_PER_RAR = {
    "RF Data_00000_H1.rar": 3,
    "RF Data_00000_L1.rar": 3,
    "RF Data_10000_H.rar": 2,
    "RF Data_10000_L.rar": 2,
    "RF Data_10100_H.rar": 2,
    "RF Data_10100_L.rar": 2,
    "RF Data_11000_H.rar": 3,
    "RF Data_11000_L1.rar": 3,
}

# (filename, mendeley file id, sha256) — the representative subset.
FILES = [
    ("RF Data_00000_H1.rar", "2ee1bbc4-418d-4cdf-b146-8e8f00e860b1",
     "4fc4521d7f9b34d738dec1de78571ff4d3a99141920804cd90cf715c5587ece9"),
    ("RF Data_00000_L1.rar", "991726e5-a214-4828-9a34-a0e7c978db89", None),
    ("RF Data_10000_H.rar", "8ee8e8a0-dc69-4925-af4b-bea9b03f60c8", None),
    ("RF Data_10000_L.rar", "58b15d1f-ed79-40bf-bfca-18580e5dc18e", None),
    ("RF Data_10100_H.rar", "226b0c56-4c71-474f-bbfe-2d7eccde3f5a", None),
    ("RF Data_10100_L.rar", "189336e2-62ce-4801-941c-2624e979ee12", None),
    ("RF Data_11000_H.rar", "fb553ab8-2bbe-484c-b978-d43bc849869c", None),
    ("RF Data_11000_L1.rar", "03362ccf-884d-412e-9074-bfc6137216b4",
     "77ca5ba635fc87c0da047d7c691c38f845cecdd17b0b0274822fdb6e4aea0588"),
]

URL = ("https://data.mendeley.com/public-files/datasets/"
       "f4c2b4n755/files/{fid}/file_downloaded")


def download(fid: str, dest: Path) -> None:
    subprocess.run(
        ["curl", "-fSL", "--max-time", "900", "-C", "-", "-A", "Mozilla/5.0",
         URL.format(fid=fid), "-o", str(dest)],
        check=True,
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_prefix(rar: Path, n_segments: int) -> int:
    """Extract a capped prefix of the first ``n_segments`` inner CSVs."""
    written = 0
    with libarchive.file_reader(str(rar)) as arc:
        for entry in arc:
            if written >= n_segments:
                break
            name = Path(entry.pathname).name
            if not name.lower().endswith(".csv"):
                continue
            out = CSV_DIR / name
            buf = bytearray()
            for block in entry.get_blocks():
                buf += block
                if len(buf) >= CAP_BYTES:
                    break
            cut = buf.rfind(b",")          # trim the last (possibly partial) value
            if cut > 0:
                buf = buf[:cut]
            out.write_bytes(bytes(buf))
            print(f"    -> {name}  ({len(buf)/1e6:.1f} MB)")
            written += 1
    return written


def main() -> int:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for fname, fid, want_hash in FILES:
        rar = RAW_DIR / fname
        n = SEGMENTS_PER_RAR.get(fname, 2)
        # Skip if we already prepared enough CSVs from this archive.
        bui_band = fname.replace("RF Data_", "").replace("FR Data_", "")
        bui_band = bui_band.split(".")[0].replace("_", "")[:6]  # e.g. 00000H
        existing = list(CSV_DIR.glob(f"{bui_band}_*.csv"))
        if len(existing) >= n:
            print(f"[skip] {fname}: {len(existing)} CSVs already prepared")
            continue
        print(f"[get ] {fname}")
        if not rar.exists():
            download(fid, rar)
        if want_hash:
            got = sha256(rar)
            if got != want_hash:
                print(f"    !! sha256 mismatch for {fname}: {got}", file=sys.stderr)
                return 1
            print("    sha256 ok")
        extract_prefix(rar, n)
        rar.unlink(missing_ok=True)       # reclaim disk immediately
    csvs = sorted(CSV_DIR.glob("*.csv"))
    print(f"\nPrepared {len(csvs)} CSV segments in {CSV_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
