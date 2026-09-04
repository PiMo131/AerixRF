"""IQ sources behind one hardware-neutral contract.

Every source yields :class:`IQWindow` objects -- the IQ block *plus* the metadata
that says where it came from and whether it is trustworthy (receiver, tuning,
completeness, dropped samples). Nothing downstream (DSP / classifier / decoder)
may branch on the receiver type; receiver-specific behaviour lives in the adapter.

Phase-1 adapters (HackRF only, by design):

  * ``LibHackRFSource``      -- continuous stream via libhackrf (ctypes, no SoapySDR
                                needed). Preferred live path: gap-free, with
                                overflow / short-read counters.
  * ``HackrfTransferSource`` -- one ``hackrf_transfer`` process per window. Robust
                                fallback / export path; has inter-window gaps.
  * ``HackRFSource``         -- SoapySDR, if the bindings happen to be present.
  * ``FileIQSource``         -- replay a ``.cs8`` recording (deterministic).
  * ``SimSource``            -- synthetic IQ, no hardware.

Later SDRs (ANTSDR, bladeRF, USRP) are new adapters that yield the same window.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import numpy as np

from ..config import Config
from .sim import synth_iq

log = logging.getLogger("aerix.rf.sdr")


# --- the contract --------------------------------------------------------------

@dataclass
class ReceiverCapabilities:
    receiver_type: str
    min_freq_hz: float
    max_freq_hz: float
    max_sample_rate: float
    max_instantaneous_bw_hz: float
    channels_rx: int = 1
    supports_hardware_timestamps: bool = False
    supports_external_clock: bool = False
    supports_external_pps: bool = False


@dataclass
class IQWindow:
    """One block of complex64 IQ and the facts needed to trust/replay it."""
    iq: np.ndarray
    captured_at: float                 # wall-clock at window START (s, epoch)
    sample_rate: float
    center_freq_hz: float
    receiver_type: str
    receiver_serial: str | None = None
    gain_db: float | None = None
    complete: bool = True              # False: short read / gap / overflow inside window
    dropped_samples: int | None = None # known-lost samples inside this window
    expected_samples: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def received_samples(self) -> int:
        return int(self.iq.size)

    @property
    def duration_s(self) -> float:
        return self.iq.size / self.sample_rate if self.sample_rate else 0.0

    def health(self) -> dict[str, Any]:
        """Capture-quality summary carried into every detection record."""
        exp = self.expected_samples if self.expected_samples is not None else self.iq.size
        return {
            "expected_samples": int(exp),
            "received_samples": int(self.iq.size),
            "dropped_or_missing_samples": int(self.dropped_samples or 0) + max(0, int(exp) - int(self.iq.size)),
            "overflow_count": int(self.metadata.get("overflow_count", 0)),
            "capture_complete": bool(self.complete),
            "source_backend": self.receiver_type,
        }


# Well-known HackRF limits (HackRF One / Pro share the host API).
HACKRF_CAPS = ReceiverCapabilities(
    receiver_type="hackrf",
    min_freq_hz=1e5, max_freq_hz=6e9,
    max_sample_rate=20e6, max_instantaneous_bw_hz=20e6,
)


class IQSource:
    """Iterate fixed-size IQ windows; retune between windows."""

    receiver_type: str = "unknown"

    @property
    def capabilities(self) -> ReceiverCapabilities:  # pragma: no cover - interface
        raise NotImplementedError

    def tune(self, center_freq_hz: float) -> None:  # pragma: no cover - default
        """Retune; takes effect on the next window."""
        raise NotImplementedError

    def windows(self) -> Iterator[IQWindow]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - default
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --- simulation ----------------------------------------------------------------

SIM_CAPS = ReceiverCapabilities("sim", 0.0, 1e10, 1e8, 1e8)


class SimSource(IQSource):
    """Endless synthetic stream; alternates drone/quiet windows so both paths run."""

    receiver_type = "sim"

    def __init__(self, cfg: Config, drone_period: int = 3) -> None:
        self.cfg = cfg
        self.drone_period = drone_period
        self._i = 0
        self._center_hz = cfg.center_freq_mhz * 1e6

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return SIM_CAPS

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)

    def windows(self) -> Iterator[IQWindow]:
        while True:
            drone = (self._i % self.drone_period) != 0
            t0 = time.time()
            iq = synth_iq(self.cfg.sample_rate, self.cfg.window_s, drone=drone, seed=self._i)
            yield IQWindow(iq=iq, captured_at=t0, sample_rate=self.cfg.sample_rate,
                           center_freq_hz=self._center_hz, receiver_type="sim",
                           gain_db=self.cfg.gain_db, expected_samples=iq.size,
                           metadata={"sim_drone": drone, "sim_index": self._i})
            self._i += 1


# --- .cs8 helpers / file replay -----------------------------------------------

def _read_cs8(path: str, offset_samples: int, n_samples: int) -> np.ndarray:
    """Read int8 interleaved I,Q (hackrf_transfer .cs8) -> complex64, scaled to +-1."""
    raw = np.fromfile(path, dtype=np.int8, count=n_samples * 2, offset=offset_samples * 2)
    iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
    return (iq / 128.0).astype(np.complex64)


def to_cs8(iq: np.ndarray) -> bytes:
    """complex64 in +-1 -> int8 interleaved I,Q bytes (the hackrf_transfer format)."""
    x = np.asarray(iq, dtype=np.complex64)
    out = np.empty(x.size * 2, dtype=np.int8)
    out[0::2] = np.clip(np.round(x.real * 127.0), -128, 127).astype(np.int8)
    out[1::2] = np.clip(np.round(x.imag * 127.0), -128, 127).astype(np.int8)
    return out.tobytes()


def cs8_sample_count(path: str) -> int:
    return os.path.getsize(path) // 2


class FileIQSource(IQSource):
    """Replay a captured .cs8 file window by window (offline analysis / tests).

    ``center_freq_hz`` / ``sample_rate`` come from the config (or a session's
    metadata via ``meta``) because the raw file carries neither.
    """

    receiver_type = "file"

    def __init__(self, cfg: Config, path: str | None = None,
                 meta: dict[str, Any] | None = None) -> None:
        self.cfg = cfg
        self.path = path or cfg.iq_file
        self.meta = dict(meta or {})
        self.sample_rate = float(self.meta.get("sample_rate", cfg.sample_rate))
        self._center_hz = float(self.meta.get("center_freq_hz", cfg.center_freq_mhz * 1e6))
        self._t0 = float(self.meta.get("captured_at", 0.0))

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return ReceiverCapabilities("file", 0.0, 1e10, self.sample_rate, self.sample_rate)

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)   # only relabels; the file is what it is

    def windows(self) -> Iterator[IQWindow]:
        n = int(self.sample_rate * self.cfg.window_s)
        total = cs8_sample_count(self.path)
        for i, start in enumerate(range(0, total - n + 1, n)):
            yield IQWindow(iq=_read_cs8(self.path, start, n),
                           captured_at=self._t0 + start / self.sample_rate,
                           sample_rate=self.sample_rate, center_freq_hz=self._center_hz,
                           receiver_type=str(self.meta.get("receiver_type", "file")),
                           receiver_serial=self.meta.get("receiver_serial"),
                           gain_db=self.meta.get("gain_db"), expected_samples=n,
                           metadata={"file": self.path, "window_index": i,
                                     "offset_samples": start})


# --- HackRF via hackrf_transfer (fallback, gapped) -----------------------------

class HackrfTransferSource(IQSource):
    """Live HackRF via the `hackrf_transfer` CLI, one process per window.

    Robust and needs nothing but the `hackrf` package, but each window is a
    separate capture: bursts that fall in the setup/teardown gap are missed.
    Use for recordings/export; ``LibHackRFSource`` is the live detector path.
    """

    receiver_type = "hackrf"

    def __init__(self, cfg: Config) -> None:
        import shutil
        if not shutil.which("hackrf_transfer"):
            raise RuntimeError("hackrf_transfer not on PATH; install the `hackrf` package or use --sim")
        self.cfg = cfg
        self._center_hz = cfg.center_freq_mhz * 1e6
        self.serial = hackrf_serial_from_info()

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return HACKRF_CAPS

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)

    def capture_to_file(self, path: str, n_samples: int, center_hz: float | None = None) -> None:
        import subprocess
        center = self._center_hz if center_hz is None else float(center_hz)
        cmd = ["hackrf_transfer", "-r", path, "-f", str(int(center)),
               "-s", str(int(self.cfg.sample_rate)),
               "-l", str(self.cfg.lna_gain), "-g", str(self.cfg.vga_gain), "-n", str(n_samples)]
        if self.cfg.amp:
            cmd += ["-a", "1"]
        subprocess.run(cmd, check=True, capture_output=True,
                       timeout=n_samples / self.cfg.sample_rate + 15)

    def windows(self) -> Iterator[IQWindow]:
        import tempfile
        n = int(self.cfg.sample_rate * self.cfg.window_s)
        while True:
            fd, path = tempfile.mkstemp(suffix=".cs8")
            os.close(fd)
            try:
                t0 = time.time()
                center = self._center_hz
                self.capture_to_file(path, n, center)
                got = cs8_sample_count(path)
                iq = _read_cs8(path, 0, min(n, got))
                yield IQWindow(iq=iq, captured_at=t0, sample_rate=self.cfg.sample_rate,
                               center_freq_hz=center, receiver_type="hackrf",
                               receiver_serial=self.serial,
                               gain_db=float(self.cfg.lna_gain + self.cfg.vga_gain),
                               complete=(got >= n), expected_samples=n,
                               dropped_samples=max(0, n - got),
                               metadata={"backend": "hackrf_transfer", "gapped": True,
                                         "lna_gain": self.cfg.lna_gain, "vga_gain": self.cfg.vga_gain,
                                         "amp": self.cfg.amp})
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def hackrf_serial_from_info() -> str | None:
    """Best-effort serial via `hackrf_info` (used by the CLI-based source)."""
    import shutil
    import subprocess
    if not shutil.which("hackrf_info"):
        return None
    try:
        out = subprocess.run(["hackrf_info"], capture_output=True, text=True, timeout=5).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        if "Serial number" in line:
            return line.split(":", 1)[1].strip()
    return None


# --- HackRF via libhackrf (continuous; preferred live path) --------------------

class LibHackRFSource(IQSource):
    """Continuous, gap-free HackRF stream through libhackrf (see ``libhackrf.py``).

    Windows are cut from one uninterrupted RX stream; overflows (consumer too slow)
    and short reads are counted and stamped on the affected window rather than
    silently emitted as if complete.
    """

    receiver_type = "hackrf"

    def __init__(self, cfg: Config) -> None:
        from .libhackrf import HackRFStream
        self.cfg = cfg
        self.stream = HackRFStream(sample_rate=cfg.sample_rate,
                                   center_freq_hz=cfg.center_freq_mhz * 1e6,
                                   lna_gain=cfg.lna_gain, vga_gain=cfg.vga_gain, amp=cfg.amp)
        self.serial = self.stream.serial
        self.stream.start()

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return HACKRF_CAPS

    def tune(self, center_freq_hz: float) -> None:
        self.stream.tune(center_freq_hz)

    def windows(self) -> Iterator[IQWindow]:
        n = int(self.cfg.sample_rate * self.cfg.window_s)
        while True:
            win = self.stream.read_window(n)
            if win is None:
                return   # stream stopped / device lost
            iq, info = win
            yield IQWindow(iq=iq, captured_at=info["captured_at"], sample_rate=self.cfg.sample_rate,
                           center_freq_hz=info["center_freq_hz"], receiver_type="hackrf",
                           receiver_serial=self.serial,
                           gain_db=float(self.cfg.lna_gain + self.cfg.vga_gain),
                           complete=info["complete"], expected_samples=n,
                           dropped_samples=info["dropped_samples"],
                           metadata={"backend": "libhackrf", "gapped": False,
                                     "overflow_count": info["overflow_count"],
                                     "short_reads": info["short_reads"],
                                     "stream_rate_ratio": info["stream_rate_ratio"],
                                     "lna_gain": self.cfg.lna_gain, "vga_gain": self.cfg.vga_gain,
                                     "amp": self.cfg.amp})

    def close(self) -> None:
        self.stream.close()


# --- HackRF via SoapySDR (if bindings exist) -----------------------------------

class HackRFSource(IQSource):
    """Live HackRF via SoapySDR. Raises a clear error if the bindings are absent."""

    receiver_type = "hackrf"

    def __init__(self, cfg: Config) -> None:
        try:
            import SoapySDR
            from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
        except Exception as exc:  # pragma: no cover - hardware path
            raise RuntimeError(
                "SoapySDR python bindings not found. Install the OS packages "
                "(soapysdr-module-hackrf, python3-soapysdr, hackrf) or run with --sim."
            ) from exc
        self.cfg = cfg
        self._SOAPY_SDR_RX = SOAPY_SDR_RX
        self._center_hz = cfg.center_freq_mhz * 1e6
        self.dev = SoapySDR.Device(dict(driver="hackrf"))
        self.dev.setSampleRate(SOAPY_SDR_RX, 0, cfg.sample_rate)
        self.dev.setFrequency(SOAPY_SDR_RX, 0, self._center_hz)
        self.dev.setGain(SOAPY_SDR_RX, 0, cfg.gain_db)
        self.stream = self.dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self.dev.activateStream(self.stream)

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return HACKRF_CAPS

    def tune(self, center_freq_hz: float) -> None:  # pragma: no cover - hardware path
        self._center_hz = float(center_freq_hz)
        self.dev.setFrequency(self._SOAPY_SDR_RX, 0, self._center_hz)

    def windows(self) -> Iterator[IQWindow]:  # pragma: no cover - hardware path
        n = int(self.cfg.sample_rate * self.cfg.window_s)
        chunk = 1 << 16
        while True:
            t0 = time.time()
            buf = np.empty(n, dtype=np.complex64)
            got = 0
            short = 0
            while got < n:
                take = min(chunk, n - got)
                tmp = np.empty(take, dtype=np.complex64)
                sr = self.dev.readStream(self.stream, [tmp], take)
                if sr.ret > 0:
                    buf[got:got + sr.ret] = tmp[:sr.ret]
                    got += sr.ret
                elif sr.ret < 0:
                    short += 1
                    break    # timeout/overflow: emit what we have rather than stall
            yield IQWindow(iq=buf[:got], captured_at=t0, sample_rate=self.cfg.sample_rate,
                           center_freq_hz=self._center_hz, receiver_type="hackrf",
                           gain_db=self.cfg.gain_db, complete=(got >= n and short == 0),
                           expected_samples=n, dropped_samples=n - got,
                           metadata={"backend": "soapysdr", "short_reads": short})

    def close(self) -> None:  # pragma: no cover - hardware path
        try:
            self.dev.deactivateStream(self.stream)
            self.dev.closeStream(self.stream)
        except Exception:
            pass


# --- factory -------------------------------------------------------------------

def make_source(cfg: Config, prefer: str | None = None) -> IQSource:
    """Pick the live backend. ``prefer`` (or ``$AERIX_RF_BACKEND``) may force one of
    ``libhackrf`` | ``hackrf_transfer`` | ``soapy``; default order is continuous
    libhackrf, then hackrf_transfer, then SoapySDR."""
    import shutil
    if cfg.sim:
        return SimSource(cfg)
    if cfg.iq_file:
        return FileIQSource(cfg)

    prefer = prefer or os.environ.get("AERIX_RF_BACKEND", "").strip().lower() or None
    order = {"libhackrf": ["libhackrf"], "hackrf_transfer": ["hackrf_transfer"],
             "soapy": ["soapy"]}.get(prefer, ["libhackrf", "hackrf_transfer", "soapy"])

    errors: list[str] = []
    for backend in order:
        try:
            if backend == "libhackrf":
                return LibHackRFSource(cfg)
            if backend == "hackrf_transfer" and shutil.which("hackrf_transfer"):
                return HackrfTransferSource(cfg)
            if backend == "soapy":
                return HackRFSource(cfg)
        except Exception as exc:  # noqa: BLE001 -- try the next backend
            errors.append(f"{backend}: {exc}")
            log.warning("IQ backend %s unavailable: %s", backend, exc)
    raise RuntimeError("no usable HackRF backend: " + "; ".join(errors))
