"""IQ sources: the real HackRF (via SoapySDR) and a simulated source.

SoapySDR is imported lazily so the box runs in --sim mode on a machine with no
SDR libraries. Each source yields one `window_s` block of complex64 per read.
"""

from __future__ import annotations

from typing import Iterator

import numpy as np

from ..config import Config
from .sim import synth_iq


class IQSource:
    """Minimal interface: iterate fixed-size complex64 windows."""

    def windows(self) -> Iterator[np.ndarray]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - default
        pass


class SimSource(IQSource):
    """Endless synthetic stream; alternates drone/quiet windows so both paths run."""

    def __init__(self, cfg: Config, drone_period: int = 3) -> None:
        self.cfg = cfg
        self.drone_period = drone_period
        self._i = 0

    def windows(self) -> Iterator[np.ndarray]:
        while True:
            drone = (self._i % self.drone_period) != 0
            yield synth_iq(self.cfg.sample_rate, self.cfg.window_s,
                           drone=drone, seed=self._i)
            self._i += 1


class HackRFSource(IQSource):
    """Live HackRF via SoapySDR. Raises a clear error if the bindings are absent."""

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
        self._SOAPY_SDR_CF32 = SOAPY_SDR_CF32
        self.dev = SoapySDR.Device(dict(driver="hackrf"))
        self.dev.setSampleRate(SOAPY_SDR_RX, 0, cfg.sample_rate)
        self.dev.setFrequency(SOAPY_SDR_RX, 0, cfg.center_freq_mhz * 1e6)
        self.dev.setGain(SOAPY_SDR_RX, 0, cfg.gain_db)
        self.stream = self.dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self.dev.activateStream(self.stream)

    def windows(self) -> Iterator[np.ndarray]:  # pragma: no cover - hardware path
        n = int(self.cfg.sample_rate * self.cfg.window_s)
        chunk = 1 << 16
        while True:
            buf = np.empty(n, dtype=np.complex64)
            got = 0
            while got < n:
                take = min(chunk, n - got)
                tmp = np.empty(take, dtype=np.complex64)
                sr = self.dev.readStream(self.stream, [tmp], take)
                if sr.ret > 0:
                    buf[got:got + sr.ret] = tmp[:sr.ret]
                    got += sr.ret
                elif sr.ret < 0:
                    # timeout/overflow: emit what we have rather than stall
                    break
            yield buf[:got] if got < n else buf

    def close(self) -> None:  # pragma: no cover - hardware path
        try:
            self.dev.deactivateStream(self.stream)
            self.dev.closeStream(self.stream)
        except Exception:
            pass


def _read_cs8(path: str, offset_samples: int, n_samples: int) -> np.ndarray:
    """Read int8 interleaved I,Q (hackrf_transfer .cs8) -> complex64, scaled to +-1."""
    raw = np.fromfile(path, dtype=np.int8, count=n_samples * 2, offset=offset_samples * 2)
    iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
    return (iq / 128.0).astype(np.complex64)


class FileIQSource(IQSource):
    """Replay a captured .cs8 file window by window (for offline analysis/tests)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.path = cfg.iq_file

    def windows(self):
        n = int(self.cfg.sample_rate * self.cfg.window_s)
        import os
        total = os.path.getsize(self.path) // 2      # complex samples in the file
        for start in range(0, total - n + 1, n):
            yield _read_cs8(self.path, start, n)


class HackrfTransferSource(IQSource):
    """Live HackRF via the `hackrf_transfer` CLI (no SoapySDR bindings needed).

    Captures one window_s block per read to a temp file, then reads it back.
    There is a small inter-capture gap (CLI setup/teardown) -- acceptable for
    phase-1 detection; the SoapySDR path (HackRFSource) is gap-free when available.
    """

    def __init__(self, cfg: Config) -> None:
        import shutil
        if not shutil.which("hackrf_transfer"):
            raise RuntimeError("hackrf_transfer not on PATH; install the `hackrf` package or use --sim")
        self.cfg = cfg

    def windows(self):
        import os
        import subprocess
        import tempfile
        n = int(self.cfg.sample_rate * self.cfg.window_s)
        while True:
            fd, path = tempfile.mkstemp(suffix=".cs8")
            os.close(fd)
            try:
                cmd = ["hackrf_transfer", "-r", path,
                       "-f", str(int(self.cfg.center_freq_mhz * 1e6)),
                       "-s", str(int(self.cfg.sample_rate)),
                       "-l", str(self.cfg.lna_gain), "-g", str(self.cfg.vga_gain),
                       "-n", str(n)]
                if self.cfg.amp:
                    cmd += ["-a", "1"]
                subprocess.run(cmd, check=True, capture_output=True,
                               timeout=self.cfg.window_s + 15)
                yield _read_cs8(path, 0, n)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def make_source(cfg: Config) -> IQSource:
    import shutil
    if cfg.sim:
        return SimSource(cfg)
    if cfg.iq_file:
        return FileIQSource(cfg)
    if shutil.which("hackrf_transfer"):
        return HackrfTransferSource(cfg)
    return HackRFSource(cfg)
