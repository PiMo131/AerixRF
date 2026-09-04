"""Full-band drone locator via `hackrf_sweep` differencing.

One 20 MHz HackRF window can't cover the ~83 MHz of 2.4 GHz plus 5.8 GHz that
DJI OcuSync roams. So to *find* a transmitting drone: capture an ambient baseline
sweep (drone off), then a live sweep, and subtract -- the drone's channel is the
region that got newly hot. Feed the hottest centre back into the box's
`center_freq_mhz` for a targeted capture / decode.

Usage:
    python -m aerix_rf.tools.sweep_locate baseline 2400 2485 base_24.csv
    python -m aerix_rf.tools.sweep_locate find     2400 2485 base_24.csv
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile

import numpy as np


def parse_sweep_csv(path: str) -> tuple[np.ndarray, np.ndarray]:
    """hackrf_sweep CSV -> (freqs_mhz sorted unique, mean power_db).

    A capture holds many sweeps over the dwell; bursty signals (Wi-Fi) vary
    wildly sweep-to-sweep, so we AVERAGE all sweeps per frequency bin -- in
    linear power, not dB -- to get a stable estimate that differencing can trust.
    Row: date,time,hz_low,hz_high,bin_width,num_samples,dB,dB,...
    """
    freqs: list[float] = []
    powers: list[float] = []
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 7:
                continue
            try:
                lo = float(row[2]); bw = float(row[4])
                vals = [float(v) for v in row[6:]]
            except ValueError:
                continue
            for i, v in enumerate(vals):
                freqs.append((lo + bw * (i + 0.5)) / 1e6)
                powers.append(v)
    f = np.asarray(freqs); p_db = np.asarray(powers)
    if f.size == 0:
        return f, p_db
    lin = np.power(10.0, p_db / 10.0)
    uf, inv = np.unique(f, return_inverse=True)
    sums = np.zeros(uf.size); cnt = np.zeros(uf.size)
    np.add.at(sums, inv, lin)
    np.add.at(cnt, inv, 1)
    return uf, 10.0 * np.log10(sums / cnt)


def diff_sweeps(live: tuple[np.ndarray, np.ndarray],
                baseline: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Per-frequency (live - baseline) dB, baseline interpolated onto live's grid."""
    fl, pl = live
    fb, pb = baseline
    return fl, pl - np.interp(fl, fb, pb)


def hottest_new(live, baseline, min_delta_db: float = 6.0, min_width_mhz: float = 3.0):
    """Return (center_mhz, delta_db, width_mhz) of the strongest region that is
    newly hot vs baseline, or None if nothing rose by min_delta over min_width."""
    f, d = diff_sweeps(live, baseline)
    hot = d > min_delta_db
    if not hot.any():
        return None
    # Widest contiguous hot run (drone links are contiguous; stray bins are not).
    best = None
    i = 0
    n = len(f)
    while i < n:
        if hot[i]:
            j = i
            while j + 1 < n and hot[j + 1]:
                j += 1
            width = f[j] - f[i]
            if width >= min_width_mhz:
                center = float((f[i] + f[j]) / 2)
                delta = float(d[i:j + 1].max())
                if best is None or delta > best[1]:
                    best = (center, delta, float(width))
            i = j + 1
        else:
            i += 1
    return best


def run_sweep(f_lo_mhz: int, f_hi_mhz: int, out: str,
              bin_hz: int = 500000, lna: int = 16, vga: int = 24,
              duration_s: float = 2.0) -> None:
    """Capture ~duration_s of continuous sweeps (many passes) so per-bin
    averaging in parse_sweep_csv has enough samples to be stable."""
    try:
        subprocess.run(
            ["hackrf_sweep", "-f", f"{f_lo_mhz}:{f_hi_mhz}", "-w", str(bin_hz),
             "-l", str(lna), "-g", str(vga), "-r", out],
            check=True, capture_output=True, timeout=duration_s,
        )
    except subprocess.TimeoutExpired:
        pass  # expected: we stop the continuous sweep after duration_s; CSV is valid


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 4:
        print(__doc__)
        return 2
    cmd, lo, hi, path = argv[0], int(argv[1]), int(argv[2]), argv[3]

    if cmd == "baseline":
        run_sweep(lo, hi, path)
        f, p = parse_sweep_csv(path)
        print(f"baseline saved: {path}  ({f.size} bins, floor {np.median(p):.0f} dB)")
        return 0

    if cmd == "find":
        fd, live_path = tempfile.mkstemp(suffix=".csv"); os.close(fd)
        try:
            run_sweep(lo, hi, live_path)
            hit = hottest_new(parse_sweep_csv(live_path), parse_sweep_csv(path))
        finally:
            os.unlink(live_path)
        if hit is None:
            print("no new signal vs baseline -> no drone found in this band")
            return 0
        center, delta, width = hit
        print(f"CANDIDATE: {center:.1f} MHz  (+{delta:.1f} dB over baseline, ~{width:.1f} MHz wide)")
        print(f"  -> point the box at it:  AERIX_RF_CENTER_MHZ={center:.0f} uv run aerix-rf")
        return 0

    print(f"unknown command {cmd!r}"); return 2


if __name__ == "__main__":
    raise SystemExit(main())
