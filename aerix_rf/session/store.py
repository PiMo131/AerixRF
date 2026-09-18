"""Field-test sessions: a self-describing directory per test (Milestone 1.4).

Layout::

    <root>/<YYYY-MM-DD_HHMMSS>_<slug(label)>/
        session.json        metadata + test-condition block + per-file records
        iq/capture_NNNN.cs8 raw int8 IQ (hackrf_transfer format), sha256 in session.json
        spectrograms/       PNGs written by write_spectrogram()
        detections.jsonl    one JSON dict per detector/classifier output
        decode.jsonl        one JSON dict per protocol-decode attempt
        summary.md          written by aerix_rf.session.report.write_summary()

Label semantics (spec, "Important label semantics"): the ``test`` block in
session.json is *human ground truth about the test condition* ("Drone A, motors
on, 30 m"). It is never touched by classifier or decoder output; those live in
detections.jsonl / decode.jsonl. A test label does not prove that every emitter
in the recording belongs to the test aircraft.

session.json is rewritten atomically (temp file + rename) after every mutation
so a crash mid-session leaves a readable, if truncated, session.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .. import __version__
from ..config import Config
from ..sdr.capture import (
    CS16_DEFAULT_FULL_SCALE,
    FileIQSource,
    IQWindow,
    iq_sample_count,
    to_cs8,
    to_cs16,
)

SESSION_FILE = "session.json"
DETECTIONS_FILE = "detections.jsonl"
DECODE_FILE = "decode.jsonl"
IQ_DIR = "iq"
SPEC_DIR = "spectrograms"

# Test-condition keys (spec list). All are written, missing -> null.
TEST_KEYS = (
    "test_label", "drone_manufacturer", "drone_model", "drone_serial",
    "drone_state", "controller_state", "motors_state", "approx_distance_m",
    "operator_notes",
)


class SessionIntegrityError(RuntimeError):
    """A recorded IQ file no longer matches the sha256 stored in session.json."""


def _utc_iso(ts: float | None = None) -> str:
    dt = datetime.now(timezone.utc) if ts is None else datetime.fromtimestamp(ts, timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def slugify(label: str, max_len: int = 48) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", label.strip()).strip("_").lower()
    return (s or "session")[:max_len]


def git_short_sha() -> str | None:
    """Best-effort ``git rev-parse --short HEAD`` in the package directory."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=Path(__file__).resolve().parent, capture_output=True,
                             text=True, timeout=5)
    except Exception:  # noqa: BLE001 -- git missing, not a repo, ...
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _atomic_write_json(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=False, default=_json_default)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _json_default(o: Any) -> Any:
    """Make numpy scalars / Paths / bytes-free objects serialisable."""
    if hasattr(o, "item"):
        try:
            return o.item()
        except Exception:  # noqa: BLE001
            pass
    if hasattr(o, "tolist"):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue   # a torn last line from a crash; never fail a reader on it
            if isinstance(rec, dict):
                out.append(rec)
    return out


class Session:
    """One field-test session directory. Use :meth:`create` or :meth:`open`."""

    def __init__(self, path: Path, meta: dict[str, Any]) -> None:
        self.path = Path(path)
        self.meta = meta

    # --- construction ------------------------------------------------------

    @classmethod
    def create(cls, root: str | Path, label: str, *, cfg: Config, receiver: dict[str, Any],
               test: dict[str, Any] | None = None, notes: str = "",
               location: dict[str, Any] | None = None) -> "Session":
        """Create ``<root>/<YYYY-MM-DD_HHMMSS>_<slug(label)>/`` and its session.json.

        ``receiver`` may carry ``receiver_type``, ``receiver_serial``, ``sample_rate``,
        ``center_freq_hz``, ``scan_range_hz`` ([lo, hi]), ``lna_gain``, ``vga_gain``,
        ``amp``, ``gain_db``, ``antenna``, ``backend``; anything missing falls back to
        ``cfg``. ``test`` holds the test-condition block (see ``TEST_KEYS``); the
        ``antenna`` description may also be given there.
        """
        root = Path(root)
        now = datetime.now(timezone.utc)
        base = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{slugify(label)}"
        path = root / base
        n = 1
        while path.exists():          # two sessions within one second
            n += 1
            path = root / f"{base}_{n}"
        (path / IQ_DIR).mkdir(parents=True, exist_ok=False)
        (path / SPEC_DIR).mkdir(exist_ok=True)

        rcv = dict(receiver or {})
        test = dict(test or {})
        test_block = {k: test.get(k) for k in TEST_KEYS}
        if test_block["test_label"] is None:
            test_block["test_label"] = label
        # Anything extra the operator put in the test dict is kept, but only
        # under the test block -- never merged with classifier output.
        for k, v in test.items():
            if k not in test_block and k != "antenna":
                test_block[k] = v

        lna = rcv.get("lna_gain", cfg.lna_gain)
        vga = rcv.get("vga_gain", cfg.vga_gain)
        gain_db = rcv.get("gain_db")
        if gain_db is None:
            gain_db = float(lna + vga) if lna is not None and vga is not None else cfg.gain_db

        meta: dict[str, Any] = {
            "schema_version": 2,
            "session_id": str(uuid.uuid4()),
            "label": label,
            "started_at": _utc_iso(now.timestamp()),
            "ended_at": None,
            "duration_s": None,
            "software_git_sha": git_short_sha(),
            "software_version": __version__ or "0.1.0",
            "receiver_type": rcv.get("receiver_type", "sim" if cfg.sim else "hackrf"),
            "receiver_serial": rcv.get("receiver_serial"),
            "receiver_backend": rcv.get("backend"),
            # New in schema 2, all optional / defaulted -- see docs/design/antsdr-backend.md
            # section 4. A schema-1 reader (or an old session.json with none of these
            # keys) is unaffected: every consumer treats them as optional with the
            # documented default (cs8 / 128.0 / None / None).
            "receiver_firmware": rcv.get("receiver_firmware"),
            "receiver_driver": rcv.get("receiver_driver"),
            "iq_format": rcv.get("iq_format", "cs8"),
            "iq_full_scale": float(rcv.get("iq_full_scale", 128.0)),
            "bandwidth_hz": rcv.get("bandwidth_hz"),
            "gain_mode": rcv.get("gain_mode"),
            "sample_rate": float(rcv.get("sample_rate", cfg.sample_rate)),
            "center_freq_hz": (None if rcv.get("center_freq_hz", cfg.center_freq_mhz * 1e6) is None
                               else float(rcv.get("center_freq_hz", cfg.center_freq_mhz * 1e6))),
            "scan_range_hz": rcv.get("scan_range_hz"),
            "band": rcv.get("band", cfg.band),
            "window_s": float(rcv.get("window_s", cfg.window_s)),
            "gains": {"lna_gain": lna, "vga_gain": vga, "amp": bool(rcv.get("amp", cfg.amp)),
                      "gain_db": gain_db},
            "antenna": rcv.get("antenna") or test.get("antenna") or "",
            "location": dict(location) if location else None,
            "environment_notes": notes or "",
            "test": test_block,
            "counts": {"iq_windows": 0, "spectrograms": 0, "detections": 0, "decodes": 0},
            "files": [],
        }
        s = cls(path, meta)
        s._flush()
        return s

    @classmethod
    def open(cls, path: str | Path) -> "Session":
        path = Path(path)
        with open(path / SESSION_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict) or "session_id" not in meta:
            raise ValueError(f"{path / SESSION_FILE} is not a session.json")
        meta.setdefault("files", [])
        meta.setdefault("test", {})
        meta.setdefault("counts", {})
        return cls(path, meta)

    # --- properties --------------------------------------------------------

    @property
    def session_id(self) -> str:
        return str(self.meta.get("session_id"))

    @property
    def label(self) -> str:
        return str(self.meta.get("label") or self.meta.get("test", {}).get("test_label") or "")

    @property
    def files(self) -> list[dict[str, Any]]:
        return self.meta.setdefault("files", [])

    @property
    def test(self) -> dict[str, Any]:
        return self.meta.setdefault("test", {})

    def _flush(self) -> None:
        _atomic_write_json(self.path / SESSION_FILE, self.meta)

    def set(self, key: str, value: Any) -> None:
        """Set a top-level session.json key (not inside the test block)."""
        if key in ("files",):
            raise ValueError("files is managed by write_iq()")
        self.meta[key] = value
        self._flush()

    # --- writers -----------------------------------------------------------

    def write_iq(self, window: IQWindow, name: str | None = None, *,
                 iq_format: str = "cs8", iq_full_scale: float | None = None) -> Path:
        """Store ``window.iq`` as ``iq/capture_NNNN.<ext>`` and record it in session.json.

        ``iq_format``: ``"cs8"`` (default, unchanged legacy behaviour -- fixed 128.0
        full scale, matches ``to_cs8``) or ``"cs16"`` for wider dynamic range (e.g.
        research captures / ANTSDR 12-bit data). ``iq_full_scale`` is ignored for
        cs8 (always 128.0, to_cs8's own fixed scale); for cs16 it is REQUIRED --
        there is no safe default (32767.0 generic vs 2048.0 ANTSDR/AD9361
        12-bit-in-int16 differ by ~24 dB) -- pass 2048.0 for measured ANTSDR data.
        """
        if iq_format not in ("cs8", "cs16"):
            raise ValueError(f"unknown iq_format {iq_format!r}")
        if iq_format == "cs16" and iq_full_scale is None:
            raise ValueError(
                "write_iq(iq_format='cs16') requires an explicit iq_full_scale "
                "(e.g. 2048.0 for ANTSDR/AD9361 12-bit-in-int16 data, 32767.0 for "
                "a generic 16-bit recording) -- there is no safe default."
            )
        iq_dir = self.path / IQ_DIR
        iq_dir.mkdir(exist_ok=True)
        ext = ".cs8" if iq_format == "cs8" else ".cs16"
        if name is None:
            name = f"capture_{len(self.files) + 1:04d}{ext}"
        elif not name.endswith(ext):
            name += ext
        out = iq_dir / name
        if iq_format == "cs8":
            iq_full_scale = 128.0
            data = to_cs8(window.iq)
        else:
            # iq_full_scale is guaranteed non-None here (checked above).
            data = to_cs16(window.iq, full_scale=iq_full_scale)
        with open(out, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        sha = hashlib.sha256(data).hexdigest()
        n = int(window.iq.size)
        entry: dict[str, Any] = {
            "file": f"{IQ_DIR}/{name}",
            "sha256": sha,
            "sample_count": n,
            "duration_s": (n / window.sample_rate) if window.sample_rate else 0.0,
            "sample_rate": float(window.sample_rate),
            "center_freq_hz": float(window.center_freq_hz),
            "captured_at": float(window.captured_at),
            "captured_at_iso": _utc_iso(window.captured_at),
            "complete": bool(window.complete),
            "dropped_samples": (None if window.dropped_samples is None else int(window.dropped_samples)),
            "expected_samples": (None if window.expected_samples is None else int(window.expected_samples)),
            "receiver_type": window.receiver_type,
            "receiver_serial": window.receiver_serial,
            "gain_db": window.gain_db,
            "capture_health": window.health(),
            # New in schema 2, all optional / defaulted on read (see FileIQSource /
            # Session.iq_windows()): iq_format absent -> "cs8", iq_full_scale
            # absent -> 128.0, bandwidth_hz/timing absent -> None/{}, channel_id
            # absent -> 0.
            "iq_format": iq_format,
            "iq_full_scale": float(iq_full_scale),
            "bandwidth_hz": window.bandwidth_hz,
            "channel_id": int(window.channel_id),
            "timing": dict(window.timing) if window.timing else {},
        }
        # Receiver config readback (currently only antsdr_iio populates
        # window.metadata["readback"] -- see docs/design/antsdr-backend.md):
        # the REQUESTED config alone is not proof the device was actually in
        # that state, so a readback-capable backend's first window's readback
        # is recorded once at the top level, and every file records whether
        # ITS window's readback matched the requested config at capture time.
        if "readback_mismatch" in window.metadata:
            entry["readback_mismatch"] = bool(window.metadata["readback_mismatch"])
        if not self.files and isinstance(window.metadata.get("readback"), dict):
            self.meta["receiver_readback"] = dict(window.metadata["readback"])
        self.files.append(entry)
        self.meta.setdefault("counts", {})["iq_windows"] = len(self.files)
        self._flush()
        return out

    def write_spectrogram(self, png_bytes: bytes, captured_at: float, tag: str = "") -> Path:
        d = self.path / SPEC_DIR
        d.mkdir(exist_ok=True)
        stamp = datetime.fromtimestamp(float(captured_at), timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3]
        suffix = f"_{slugify(tag, 32)}" if tag else ""
        out = d / f"spec_{stamp}{suffix}.png"
        k = 1
        while out.exists():
            k += 1
            out = d / f"spec_{stamp}{suffix}_{k}.png"
        with open(out, "wb") as f:
            f.write(png_bytes)
        counts = self.meta.setdefault("counts", {})
        counts["spectrograms"] = int(counts.get("spectrograms", 0)) + 1
        self._flush()
        return out

    def _append_jsonl(self, fname: str, record: dict[str, Any], counter: str) -> None:
        rec = dict(record)
        rec.setdefault("ts", _utc_iso())
        line = json.dumps(rec, default=_json_default, separators=(",", ":"))
        with open(self.path / fname, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        counts = self.meta.setdefault("counts", {})
        counts[counter] = int(counts.get(counter, 0)) + 1
        self._flush()

    def log_detection(self, record: dict[str, Any]) -> None:
        """Append one detector/classifier record (see report.py for the fields used)."""
        self._append_jsonl(DETECTIONS_FILE, record, "detections")

    def log_decode(self, record: dict[str, Any]) -> None:
        """Append one protocol-decode attempt (see report.py for the fields used)."""
        self._append_jsonl(DECODE_FILE, record, "decodes")

    def finalize(self, extra: dict[str, Any] | None = None, *, source: Any | None = None) -> None:
        """Stamp ended_at / duration_s / counts (and any ``extra`` keys) into session.json.

        ``source``: the live ``IQSource`` this session was recorded from, if any
        (e.g. a ``ProcessIQSource``). If it has a ``stream_end_reason`` attribute
        (``"completed" | "producer_lost" | "device_lost" | "user_stop"`` --
        see ``process_source.py``), that value is stamped into the top-level
        ``stream_end_reason`` key; a source with no such attribute (every
        backend except the OS-process producer path today), or no ``source``
        passed at all, records ``None`` -- never a guessed default."""
        now = datetime.now(timezone.utc)
        self.meta["ended_at"] = _utc_iso(now.timestamp())
        try:
            started = datetime.fromisoformat(str(self.meta["started_at"]).replace("Z", "+00:00"))
            self.meta["duration_s"] = round((now - started).total_seconds(), 3)
        except (KeyError, ValueError):
            self.meta["duration_s"] = None
        counts = self.meta.setdefault("counts", {})
        counts["iq_windows"] = len(self.files)
        counts["iq_samples"] = int(sum(int(f.get("sample_count", 0)) for f in self.files))
        counts["iq_duration_s"] = float(sum(float(f.get("duration_s", 0.0)) for f in self.files))
        counts["detections"] = len(self.detections())
        counts["decodes"] = len(self.decodes())
        counts["spectrograms"] = len(list((self.path / SPEC_DIR).glob("*.png"))) \
            if (self.path / SPEC_DIR).is_dir() else 0
        for k, v in (extra or {}).items():
            if k == "test":
                raise ValueError("finalize() must not overwrite the test-condition block")
            self.meta[k] = v
        self.meta["stream_end_reason"] = getattr(source, "stream_end_reason", None)
        self._flush()

    # --- readers -----------------------------------------------------------

    def detections(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path / DETECTIONS_FILE)

    def decodes(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path / DECODE_FILE)

    def verify(self) -> list[dict[str, Any]]:
        """sha256-check every recorded file; returns the entries that FAIL (empty = ok)."""
        bad = []
        for entry in self.files:
            p = self.path / entry["file"]
            if not p.exists() or sha256_file(p) != entry.get("sha256"):
                bad.append(entry)
        return bad

    def iq_windows(self, cfg: Config) -> Iterator[IQWindow]:
        """Replay every recorded IQ file in order, exactly as captured.

        Each file becomes a :class:`FileIQSource` with the file's own sample_rate /
        center / captured_at / receiver metadata, so replay on another machine is
        independent of that machine's config. ``cfg.window_s`` is overridden with
        the file's duration so one recorded window yields one replayed window.
        The sha256 is verified before a file is read.
        """
        from dataclasses import replace
        for entry in self.files:
            p = self.path / entry["file"]
            if not p.exists():
                raise SessionIntegrityError(f"{self.session_id}: missing IQ file {p}")
            got = sha256_file(p)
            if got != entry.get("sha256"):
                raise SessionIntegrityError(
                    f"{self.session_id}: sha256 mismatch for {entry['file']}: "
                    f"session.json says {entry.get('sha256')}, file is {got} "
                    "(file modified, truncated or corrupted since capture)")
            sr = float(entry.get("sample_rate") or cfg.sample_rate)
            # iq_format/iq_full_scale absent (schema-1 session, written before this
            # field existed) -> None here, and FileIQSource itself applies the
            # cs8/128.0 default -- this is the load-bearing backward-compat path.
            iq_fmt = entry.get("iq_format")
            n = int(entry.get("sample_count") or iq_sample_count(str(p), iq_fmt or "cs8"))
            # +0.5 sample so int(sr * window_s) in FileIQSource lands on n exactly
            # (n / sr alone can round to n-1 in float64).
            file_cfg = replace(cfg, sample_rate=sr, window_s=(n + 0.5) / sr if sr else cfg.window_s)
            meta = {k: entry.get(k) for k in ("sample_rate", "center_freq_hz", "captured_at",
                                              "receiver_type", "receiver_serial", "gain_db",
                                              "iq_format", "iq_full_scale")}
            src = FileIQSource(file_cfg, path=str(p), meta=meta)
            for w in src.windows():
                w.complete = bool(entry.get("complete", True))
                w.dropped_samples = entry.get("dropped_samples")
                w.expected_samples = entry.get("expected_samples", w.expected_samples)
                # New-in-schema-2 fields; absent on a schema-1 entry -> defaults
                # matching IQWindow's own dataclass defaults (None / 0 / {}).
                w.bandwidth_hz = entry.get("bandwidth_hz")
                w.channel_id = int(entry.get("channel_id") or 0)
                w.timing = dict(entry.get("timing") or {})
                w.metadata.update({"session_id": self.session_id, "session_file": entry["file"],
                                   "sha256": got, "replay": True})
                if isinstance(entry.get("capture_health"), dict):
                    w.metadata.setdefault("overflow_count",
                                          entry["capture_health"].get("overflow_count", 0))
                yield w

    def __repr__(self) -> str:
        return f"Session({self.path}, id={self.session_id}, files={len(self.files)})"
