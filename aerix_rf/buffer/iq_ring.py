"""On-disk rolling raw-IQ store for plausible-detection seconds (upload mode 4).

Bounded by design: entries older than `retention_s` are purged on every write, so
raw IQ (which can contain a drone's/operator's position once decoded) never lives
longer than the configured window. This bound is the GDPR-relevant guarantee.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np


class IQRing:
    def __init__(self, directory: str | Path, retention_s: int = 24 * 3600) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.retention_s = retention_s

    def store(self, iq: np.ndarray, captured_at: float, meta: dict) -> str:
        """Persist one IQ window (complex64) + sidecar metadata, keyed by timestamp."""
        key = f"{int(captured_at * 1000):015d}"
        np.save(self.dir / f"{key}.npy", np.asarray(iq, dtype=np.complex64))
        (self.dir / f"{key}.json").write_text(json.dumps({**meta, "captured_at": captured_at}))
        self.purge()
        return key

    def get(self, key: str) -> np.ndarray | None:
        f = self.dir / f"{key}.npy"
        return np.load(f) if f.exists() else None

    def nearest(self, captured_at: float, tolerance_s: float = 1.5) -> str | None:
        """Key of the retained window closest to a timestamp (for on-demand pull)."""
        target = int(captured_at * 1000)
        best, best_dt = None, tolerance_s * 1000
        for f in self.dir.glob("*.npy"):
            dt = abs(int(f.stem) - target)
            if dt <= best_dt:
                best, best_dt = f.stem, dt
        return best

    def purge(self) -> int:
        cutoff = int((time.time() - self.retention_s) * 1000)
        removed = 0
        for f in self.dir.glob("*.npy"):
            if int(f.stem) < cutoff:
                f.unlink(missing_ok=True)
                (self.dir / f"{f.stem}.json").unlink(missing_ok=True)
                removed += 1
        return removed
