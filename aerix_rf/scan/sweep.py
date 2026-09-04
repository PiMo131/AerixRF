"""hackrf_sweep acquisition + parsing for the scan workflow.

Builds on :mod:`aerix_rf.tools.sweep_locate` (which averages every sweep into
one spectrum) but keeps the INDIVIDUAL sweeps, because burstiness / persistence
/ hopping can only be judged from how a region behaves sweep-to-sweep.

hackrf_sweep CSV quirks handled here (observed on hackrf_sweep 2024.x):

* Row: ``date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, ...``
  and ONE SWEEP IS SPREAD OVER MANY ROWS (one row per FFT-segment; 20 rows for
  a 100 MHz span at the default 5 MHz segment).
* Rows inside a sweep are NOT monotonic in frequency (2400, 2410, 2405, 2415,
  ...) because each 20 MHz tune emits its two half-FFTs in hardware order.
* The bin width in the file is not the requested ``-w`` value: it is
  ``20 MHz / fft_size`` after hackrf_sweep rounds (500 kHz -> 454 545.45 Hz).
* Timestamps repeat across many rows/sweeps, so they cannot delimit sweeps.
  A sweep boundary is therefore detected as "hz_low wrapped back around":
  the first row that would write a bin already filled in the current sweep.
* The last sweep is usually cut off when the process is stopped; incomplete
  sweeps are dropped.

Sweeps are fast: ~100+ sweeps/s for a 100 MHz span, so a 2 s dwell yields a
few hundred sweeps. Single sweeps are very noisy (~6 dB per-bin std on the
noise floor); consumers average in LINEAR power (see :func:`average_db`).

Baseline storage: a single ``.npz`` (``freqs_mhz``, ``power_db`` arrays plus a
``meta`` JSON string with the scalar fields), written by
:func:`save_baseline`, read by :func:`load_baseline`.
"""

from __future__ import annotations

import csv
import json
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

__all__ = [
    "Baseline",
    "average_db",
    "parse_sweep_csv_multi",
    "run_hackrf_sweep",
    "sweep_once",
    "record_baseline",
    "save_baseline",
    "load_baseline",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def average_db(power_matrix: np.ndarray) -> np.ndarray:
    """Average a ``[n_sweeps, n_bins]`` dB matrix over sweeps, in linear power.

    Averaging in dB under-weights bursts; averaging in linear power is what
    the differential in :mod:`aerix_rf.tools.sweep_locate` does and what the
    baseline needs. NaN bins are ignored.
    """
    m = np.asarray(power_matrix, dtype=float)
    if m.ndim == 1:
        return m.copy()
    lin = np.power(10.0, m / 10.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return 10.0 * np.log10(np.nanmean(lin, axis=0))


def parse_sweep_csv_multi(path: str | os.PathLike) -> tuple[np.ndarray, np.ndarray]:
    """hackrf_sweep CSV -> ``(freqs_mhz, power_matrix)``.

    ``freqs_mhz`` is the sorted grid of bin centres (MHz); ``power_matrix`` is
    ``[n_sweeps, n_bins]`` in dB, one row per COMPLETE sweep. Sweep boundary:
    a row that would overwrite a bin already filled in the current sweep, i.e.
    ``hz_low`` wrapped back to the start of the range. Sweeps with missing bins
    (the truncated last one) are dropped. Returns empty arrays (``(0,)``,
    ``(0, 0)``) for an empty/unparseable file.
    """
    rows: list[tuple[int, np.ndarray]] = []   # (hz_low, bin centre keys in Hz), values
    vals_per_row: list[np.ndarray] = []
    keys_per_row: list[np.ndarray] = []
    with open(path, newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 7:
                continue
            try:
                lo = float(row[2])
                bw = float(row[4])
                vals = np.array([float(v) for v in row[6:]], dtype=float)
            except ValueError:
                continue
            if vals.size == 0 or bw <= 0:
                continue
            centres_hz = lo + bw * (np.arange(vals.size) + 0.5)
            keys_per_row.append(np.rint(centres_hz).astype(np.int64))
            vals_per_row.append(vals)
            rows.append((int(round(lo)), keys_per_row[-1]))

    if not rows:
        return np.zeros(0), np.zeros((0, 0))

    all_keys = np.unique(np.concatenate(keys_per_row))
    n_bins = all_keys.size

    # Sweep boundary: a row that would write a bin that is already filled in
    # the current sweep, i.e. hz_low wrapped back to the start of the range.
    # (Not "hz_low == min": rows inside a tune step are out of order, and a
    # sweep with a dropped row must not swallow the next one.)
    sweeps: list[np.ndarray] = []
    cur = np.full(n_bins, np.nan)
    filled = np.zeros(n_bins, dtype=bool)
    for (_lo, keys), vals in zip(rows, vals_per_row):
        idx = np.searchsorted(all_keys, keys)
        if filled[idx].any():
            sweeps.append(cur)
            cur = np.full(n_bins, np.nan)
            filled = np.zeros(n_bins, dtype=bool)
        cur[idx] = vals
        filled[idx] = True
    sweeps.append(cur)

    matrix = np.vstack(sweeps)
    complete = ~np.isnan(matrix).any(axis=1)
    if complete.any():
        matrix = matrix[complete]
    # else: every sweep is partial (e.g. a grid that changed mid-file); keep NaNs
    return all_keys.astype(float) / 1e6, matrix


# --------------------------------------------------------------------------- #
# acquisition
# --------------------------------------------------------------------------- #

def run_hackrf_sweep(lo_mhz: float, hi_mhz: float, out: str | os.PathLike,
                     seconds: float, *, bin_hz: int = 500_000,
                     lna: int = 16, vga: int = 24, amp: bool = False) -> None:
    """Run ``hackrf_sweep`` continuously for ``seconds`` and stop it cleanly.

    Like :func:`aerix_rf.tools.sweep_locate.run_sweep` but sends SIGINT first
    (hackrf_sweep flushes the CSV on SIGINT) and only SIGKILLs if it does not
    exit. Raises ``RuntimeError`` if hackrf_sweep exits early with an error
    (device busy / not found), with its stderr in the message.
    """
    cmd = ["hackrf_sweep", "-f", f"{int(round(lo_mhz))}:{int(round(hi_mhz))}",
           "-w", str(int(bin_hz)), "-l", str(int(lna)), "-g", str(int(vga)),
           "-a", "1" if amp else "0", "-r", os.fspath(out)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _, err = proc.communicate(timeout=max(0.1, float(seconds)))
        # exited on its own before the dwell was over -> something went wrong
        msg = " | ".join(l.strip() for l in err.decode(errors="replace").splitlines()
                         if l.strip())[:300]
        raise RuntimeError(f"hackrf_sweep exited early (rc={proc.returncode}): {msg}")
    except subprocess.TimeoutExpired:
        pass
    proc.send_signal(signal.SIGINT)
    try:
        proc.communicate(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate(timeout=3.0)


def sweep_once(lo_mhz: float, hi_mhz: float, seconds: float = 2.0, *,
               bin_hz: int = 500_000, lna: int = 16, vga: int = 24,
               amp: bool = False, retries: int = 1,
               keep_csv: str | os.PathLike | None = None,
               ) -> tuple[np.ndarray, np.ndarray, int]:
    """One live pass: ``(freqs_mhz, power_matrix [n_sweeps, n_bins] dB, n_sweeps)``.

    The matrix holds every complete sweep captured during the dwell; use
    :func:`average_db` for the single averaged spectrum. Retries once (by
    default) when no sweep was captured -- another process may briefly hold
    the HackRF. ``keep_csv`` writes the raw CSV there instead of a temp file.
    """
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        if keep_csv is not None:
            path = os.fspath(keep_csv)
            cleanup = False
        else:
            fd, path = tempfile.mkstemp(prefix="aerix_sweep_", suffix=".csv")
            os.close(fd)
            cleanup = True
        try:
            try:
                run_hackrf_sweep(lo_mhz, hi_mhz, path, seconds, bin_hz=bin_hz,
                                 lna=lna, vga=vga, amp=amp)
            except RuntimeError as e:
                last_err = e
            freqs, matrix = parse_sweep_csv_multi(path)
        finally:
            if cleanup:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if matrix.shape[0] > 0:
            return freqs, matrix, int(matrix.shape[0])
        if attempt < retries:
            time.sleep(0.5)
    raise RuntimeError(
        f"hackrf_sweep produced no complete sweep in {seconds}s"
        + (f" ({last_err})" if last_err else "")
    )


# --------------------------------------------------------------------------- #
# baseline
# --------------------------------------------------------------------------- #

@dataclass
class Baseline:
    """Averaged ambient spectrum of a band, recorded with the test drones OFF.

    ``power_db`` is the per-bin mean in LINEAR power over ``n_sweeps`` sweeps,
    expressed in dB (so it is comparable with frame-averaged live sweeps).
    """
    lo_mhz: float
    hi_mhz: float
    bin_hz: float
    freqs_mhz: np.ndarray
    power_db: np.ndarray
    n_sweeps: int
    dwell_s: float
    recorded_at: str = ""                       # ISO-8601 UTC
    gains: dict = field(default_factory=dict)   # {"lna": 16, "vga": 24, "amp": False}

    def interp(self, freqs_mhz: np.ndarray) -> np.ndarray:
        """Baseline power resampled onto another frequency grid (edge-clamped)."""
        return np.interp(np.asarray(freqs_mhz, dtype=float), self.freqs_mhz, self.power_db)

    @property
    def floor_db(self) -> float:
        return float(np.median(self.power_db)) if self.power_db.size else float("nan")


def record_baseline(lo_mhz: float, hi_mhz: float, seconds: float = 30.0, *,
                    bin_hz: int = 500_000, lna: int = 16, vga: int = 24,
                    amp: bool = False, retries: int = 1) -> Baseline:
    """Sweep ``lo..hi`` for ``seconds`` and average all sweeps into a Baseline."""
    freqs, matrix, n = sweep_once(lo_mhz, hi_mhz, seconds, bin_hz=bin_hz,
                                  lna=lna, vga=vga, amp=amp, retries=retries)
    actual_bin_hz = float(np.median(np.diff(freqs)) * 1e6) if freqs.size > 1 else float(bin_hz)
    return Baseline(
        lo_mhz=float(lo_mhz), hi_mhz=float(hi_mhz), bin_hz=actual_bin_hz,
        freqs_mhz=freqs, power_db=average_db(matrix), n_sweeps=n,
        dwell_s=float(seconds),
        recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        gains={"lna": int(lna), "vga": int(vga), "amp": bool(amp)},
    )


def _npz_path(path: str | os.PathLike) -> Path:
    p = Path(path)
    return p if p.suffix == ".npz" else p.with_name(p.name + ".npz")


def save_baseline(b: Baseline, path: str | os.PathLike) -> Path:
    """Write ``b`` as a single ``.npz`` (``.npz`` appended if missing). Returns the path."""
    p = _npz_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "lo_mhz": b.lo_mhz, "hi_mhz": b.hi_mhz, "bin_hz": b.bin_hz,
        "n_sweeps": b.n_sweeps, "dwell_s": b.dwell_s,
        "recorded_at": b.recorded_at, "gains": b.gains, "format": 1,
    }
    np.savez_compressed(p, freqs_mhz=np.asarray(b.freqs_mhz, dtype=float),
                        power_db=np.asarray(b.power_db, dtype=float),
                        meta=np.array(json.dumps(meta)))
    return p


def load_baseline(path: str | os.PathLike) -> Baseline:
    """Read a baseline written by :func:`save_baseline`."""
    p = _npz_path(path)
    if not p.exists() and Path(path).exists():
        p = Path(path)
    with np.load(p, allow_pickle=False) as z:
        meta = json.loads(str(z["meta"]))
        freqs = np.asarray(z["freqs_mhz"], dtype=float)
        power = np.asarray(z["power_db"], dtype=float)
    return Baseline(
        lo_mhz=float(meta["lo_mhz"]), hi_mhz=float(meta["hi_mhz"]),
        bin_hz=float(meta["bin_hz"]), freqs_mhz=freqs, power_db=power,
        n_sweeps=int(meta["n_sweeps"]), dwell_s=float(meta["dwell_s"]),
        recorded_at=str(meta.get("recorded_at", "")), gains=dict(meta.get("gains", {})),
    )
