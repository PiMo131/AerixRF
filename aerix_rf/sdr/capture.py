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
  * ``FileIQSource``         -- replay a ``.cs8``/``.cs16`` recording (deterministic).
  * ``SimSource``            -- synthetic IQ, no hardware.

Backend selection (``make_source``) is driven by :mod:`aerix_rf.sdr.registry`, a
name -> factory + availability-probe table, so a later SDR (ANTSDR, bladeRF,
USRP) is a new adapter *and* a new registry entry, without this module growing
backend-specific branches in ``make_source`` itself.
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

@dataclass(frozen=True)
class GainStage:
    """One controllable gain element (HackRF's lna/vga/amp, AD9361's rx gain, ...)."""
    name: str
    min_db: float
    max_db: float
    step_db: float | None = None   # None: continuous/unknown step


@dataclass
class ReceiverCapabilities:
    """What a backend/device *can* do, so callers consult this instead of
    hardcoding numbers that only happen to be true for one radio (see
    docs/design/antsdr-backend.md section 3).
    """
    receiver_type: str                         # "hackrf" | "sim" | "file" | "antsdr" | ...
    backend: str                                # "libhackrf" | "hackrf_transfer" | "soapy" | ...
    tuning_range_hz: tuple[float, float] = (0.0, 0.0)
    sample_rates_hz: tuple[float, ...] = (0.0, 0.0)
    sample_rate_is_range: bool = True           # True: sample_rates_hz is (min, max);
                                                 # False: sample_rates_hz is a discrete list
    max_instantaneous_bw_hz: float = 0.0
    channel_count: int = 1
    gain_stages: tuple[GainStage, ...] = field(default_factory=tuple)
    gain_modes: tuple[str, ...] = ("manual",)   # e.g. "manual" | "agc_slow" | "agc_fast"
    native_iq_format: str = "cs8"
    native_full_scale: float = 128.0
    supports_device_timestamps: bool = False
    supports_drop_reporting: bool = False
    supports_sweep: bool = False                # hackrf_sweep-style hardware sweep
    reference_inputs: tuple[str, ...] = ("none",)  # e.g. "none" | "ext10m" | "pps"
    firmware: str | None = None
    driver_version: str | None = None


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
    # --- generalized (multi-receiver) fields, all defaulted / additive ---------
    bandwidth_hz: float | None = None  # analog RX filter bandwidth, if settable/known
                                        # (distinct from sample_rate; e.g. AD9361
                                        # rx_rf_bandwidth). None: unknown/not applicable.
    channel_id: int = 0                # RX channel index; 0 for every single-channel
                                        # source today (HackRF, sim, file replay).
    timing: dict[str, Any] = field(default_factory=dict)
    # ``timing`` provenance keys (all optional, backend-populated):
    #   clock_source    "host" | "internal" | "external_10mhz" | "gpsdo"
    #   sample_index    monotonic sample counter, valid within one stream
    #   device_time_ns  hardware timestamp, if the backend has one (else absent)
    #   pps_locked      bool, if a PPS reference is in use
    #   clock_uncertainty_ns
    # An empty dict means "no timing provenance recorded" (today: every existing
    # backend), not "host wall clock verified" -- callers must not assume host
    # timing accuracy from an empty ``timing``; ``captured_at`` remains the only
    # guaranteed timestamp.

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
            "gap_before_samples": int(self.metadata.get("gap_before_samples", 0)),
            "stream_rate_ratio": self.metadata.get("stream_rate_ratio"),
            # Both honestly ``None`` (not fabricated 0/1.0) on backends that
            # don't populate ``metadata`` with these keys (e.g. sim, file
            # replay, HackRF) -- previously missing entirely from every
            # session.json/detections.jsonl record on every backend, incl.
            # ANTSDR where they ARE always populated (see stream.py).
            "stream_rate_ratio_recent": self.metadata.get("stream_rate_ratio_recent"),
            "stream_rate_elapsed_s": self.metadata.get("stream_rate_elapsed_s"),
            "samples_deficit": self.metadata.get("samples_deficit"),
            "samples_deficit_recent": self.metadata.get("samples_deficit_recent"),
            "rate_warning": bool(self.metadata.get("rate_warning", False)),
            "loss_detection": self.metadata.get("loss_detection"),
            "capture_complete": bool(self.complete),
            "source_backend": self.receiver_type,
            # ANTSDR-only diagnostics (see antsdr_iio.py); honestly ``None``
            # on backends (sim/HackRF/file) that never populate these keys.
            "readback_mismatch": self.metadata.get("readback_mismatch"),
            "rssi_db_readback": self.metadata.get("rssi_db_readback"),
            "max_refill_gap_ms": self.metadata.get("max_refill_gap_ms"),
        }


# Well-known HackRF limits (HackRF One / Pro share the host API). Real hardware
# numbers: 1 MHz-6 GHz tuning, 2-20 MS/s, 20 MHz max instantaneous BW (fixed --
# HackRF has no settable RX filter distinct from sample rate), 1 RX channel,
# lna 0-40 dB step 8, vga 0-62 dB step 2, amp a fixed +14 dB toggle, native cs8
# @ 128.0 full scale, no hardware timestamps, drop reporting available (see
# stream.py's StreamAssembler), hackrf_sweep for hardware-swept scans, no
# external clock/PPS input on a stock HackRF One/Pro.
_HACKRF_GAIN_STAGES = (
    GainStage("lna", 0.0, 40.0, 8.0),
    GainStage("vga", 0.0, 62.0, 2.0),
    GainStage("amp", 0.0, 14.0, 14.0),   # on/off toggle, modeled as a single 14 dB step
)


def hackrf_capabilities(backend: str) -> ReceiverCapabilities:
    """HackRF capabilities, parameterised only by which host backend is talking to it
    (libhackrf / hackrf_transfer / soapy) -- the radio itself is identical."""
    return ReceiverCapabilities(
        receiver_type="hackrf",
        backend=backend,
        tuning_range_hz=(1e6, 6e9),
        sample_rates_hz=(2e6, 20e6),
        sample_rate_is_range=True,
        max_instantaneous_bw_hz=20e6,
        channel_count=1,
        gain_stages=_HACKRF_GAIN_STAGES,
        gain_modes=("manual",),
        native_iq_format="cs8",
        native_full_scale=128.0,
        supports_device_timestamps=False,
        supports_drop_reporting=True,
        supports_sweep=True,
        reference_inputs=("none",),
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

def sim_capabilities() -> ReceiverCapabilities:
    return ReceiverCapabilities(
        receiver_type="sim",
        backend="sim",
        tuning_range_hz=(0.0, 1e10),
        sample_rates_hz=(1e3, 1e8),
        sample_rate_is_range=True,
        max_instantaneous_bw_hz=1e8,
        channel_count=1,
        gain_stages=(),
        gain_modes=("manual",),
        native_iq_format="complex64",   # in-memory synthetic IQ, no wire format
        native_full_scale=1.0,
        supports_device_timestamps=False,
        supports_drop_reporting=False,  # sim never drops
        supports_sweep=False,
        reference_inputs=("none",),
    )


SIM_CAPS = sim_capabilities()


class SimSource(IQSource):
    """Endless synthetic stream; alternates drone/quiet windows so both paths run."""

    receiver_type = "sim"

    # synth_iq() produces unit-RMS noise; a HackRF delivers int8/128, i.e. a
    # noise floor of a few LSB. Scale to that so sim windows survive the .cs8
    # round trip (session store / replay) without clipping.
    SCALE = 1.0 / 24.0

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
            iq = (synth_iq(self.cfg.sample_rate, self.cfg.window_s, drone=drone, seed=self._i)
                  * self.SCALE).astype(np.complex64)
            yield IQWindow(iq=iq, captured_at=t0, sample_rate=self.cfg.sample_rate,
                           center_freq_hz=self._center_hz, receiver_type="sim",
                           gain_db=self.cfg.gain_db, expected_samples=iq.size,
                           metadata={"sim_drone": drone, "sim_index": self._i})
            self._i += 1


# --- .cs8 / .cs16 helpers / file replay -----------------------------------------

# cs8 behaviour is UNCHANGED (fixed +-128 full scale, matches the radio's own int8
# samples bit-for-bit) -- do not add a full_scale parameter here. cs16 takes an
# explicit full_scale because it is used for more than one ADC: a generic 16-bit
# convention (32767.0, symmetric with the file-format's own range) and ANTSDR's
# left/right-justified 12-bit-in-16-bit data (2048.0, per the AD9361 survey), which
# differ by 24 dB and must never be silently conflated. There is deliberately no
# fallback default anywhere a cs16 full scale is *required but unknown*: FileIQSource,
# ``_read_cs16`` and ``Session.write_iq`` all raise ``ValueError`` instead.

def _read_cs8(path: str, offset_samples: int, n_samples: int) -> np.ndarray:
    """Read int8 interleaved I,Q (hackrf_transfer .cs8) -> complex64, scaled to +-1."""
    raw = np.fromfile(path, dtype=np.int8, count=n_samples * 2, offset=offset_samples * 2)
    iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
    return (iq / 128.0).astype(np.complex64)


def to_cs8(iq: np.ndarray) -> bytes:
    """complex64 in +-1 -> int8 interleaved I,Q bytes (the hackrf_transfer format).

    Scale is 128 in BOTH directions (matches ``_read_cs8`` and the radio's own
    int8 samples), so a window read from hardware round-trips bit-exactly."""
    x = np.asarray(iq, dtype=np.complex64)
    out = np.empty(x.size * 2, dtype=np.int8)
    out[0::2] = np.clip(np.round(x.real * 128.0), -128, 127).astype(np.int8)
    out[1::2] = np.clip(np.round(x.imag * 128.0), -128, 127).astype(np.int8)
    return out.tobytes()


CS16_DEFAULT_FULL_SCALE = 32767.0  # generic (non-ANTSDR) cs16 convention; used ONLY as
                                    # ``to_cs16``'s own explicit default (a caller that
                                    # wants the ANTSDR 2048.0 convention must pass it).
                                    # Nothing that *reads* cs16 (FileIQSource, session
                                    # metadata, ``_read_cs16``) is allowed to fall back
                                    # to it silently -- see the comment above.


def _read_cs16(path: str, offset_samples: int, n_samples: int, *, full_scale: float) -> np.ndarray:
    """Read int16 interleaved I,Q -> complex64, scaled to +-1 by ``full_scale``.

    ``full_scale`` is REQUIRED (no default): it must match how the file was
    written (``to_cs16``'s own ``full_scale``), because the same on-disk dtype
    (int16) carries different effective ranges depending on the ADC/wire format
    (e.g. AD9361 12-bit data at 2048.0 vs a generic full-range 16-bit convention
    at 32767.0). Getting this wrong shifts RSSI by up to ~24 dB without raising
    any error if it were silently defaulted -- callers must always pass the
    value recorded in ``session.json`` (``iq_full_scale``), never assume one.
    """
    if full_scale is None:
        raise ValueError(
            "_read_cs16() requires an explicit full_scale (2048.0 for ANTSDR/AD9361 "
            "12-bit-in-int16 data, 32767.0 for a generic 16-bit recording) -- there "
            "is no safe default."
        )
    itemsize = np.dtype(np.int16).itemsize
    raw = np.fromfile(path, dtype=np.int16, count=n_samples * 2,
                       offset=offset_samples * 2 * itemsize)
    iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
    return (iq / float(full_scale)).astype(np.complex64)


def to_cs16(iq: np.ndarray, full_scale: float = CS16_DEFAULT_FULL_SCALE) -> bytes:
    """complex64 in +-1 -> int16 interleaved I,Q bytes, scaled by ``full_scale``.

    Clips to the *declared* full scale (``[-round(full_scale), round(full_scale) - 1]``),
    not a fixed int16 range -- so the +-1.0 complex64 contract holds for any
    ``full_scale`` (e.g. ANTSDR's 2048.0), not only the default 32767.0. See
    ``_read_cs16`` for why ``full_scale`` is otherwise a required, explicit
    parameter rather than a hardcoded constant on the read side."""
    x = np.asarray(iq, dtype=np.complex64)
    fs = float(full_scale)
    lo = -round(fs)
    hi = round(fs) - 1
    out = np.empty(x.size * 2, dtype=np.int16)
    out[0::2] = np.clip(np.round(x.real * fs), lo, hi).astype(np.int16)
    out[1::2] = np.clip(np.round(x.imag * fs), lo, hi).astype(np.int16)
    return out.tobytes()


IQ_BYTES_PER_SAMPLE = {"cs8": 2, "cs16": 4}  # bytes for one interleaved I,Q pair


def iq_sample_count(path: str, iq_format: str = "cs8") -> int:
    """Sample count of a raw IQ file, format-aware (cs8: 2 B/sample, cs16: 4 B/sample)."""
    try:
        bps = IQ_BYTES_PER_SAMPLE[iq_format]
    except KeyError:
        raise ValueError(f"unknown iq_format {iq_format!r}") from None
    return os.path.getsize(path) // bps


def cs8_sample_count(path: str) -> int:
    """Back-compat alias: cs8-specific sample count (unchanged behaviour)."""
    return iq_sample_count(path, "cs8")


class FileIQSource(IQSource):
    """Replay a captured .cs8/.cs16 file window by window (offline analysis / tests).

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
        # iq_format / iq_full_scale: THE backward-compatibility rule. A session.json
        # written before schema_version 2 (or a bare .cs8 handed in via --iq-file)
        # has neither key. ``meta.get(...)`` then returns None, and we fall back to
        # the legacy cs8/128.0 convention -- every pre-existing HackRF session must
        # keep replaying bit-identically through this default. cs16 gets NO such
        # default: a cs16 file with no recorded full scale is a data-integrity bug,
        # not something to silently guess at (see module docstring above).
        self.iq_format = str(self.meta.get("iq_format") or "cs8")
        if self.iq_format not in IQ_BYTES_PER_SAMPLE:
            raise ValueError(f"unknown iq_format {self.iq_format!r} in session metadata")
        if self.iq_format == "cs8":
            self.iq_full_scale = float(self.meta.get("iq_full_scale") or 128.0)
        else:
            fs = self.meta.get("iq_full_scale")
            if fs is None:
                raise ValueError(
                    "cs16 IQ requires an explicit iq_full_scale (session.json's "
                    "receiver.iq_full_scale / files[].iq_full_scale) -- none was "
                    "recorded, and there is no safe default: the same int16 dtype "
                    "means +-32767.0 for a generic recording and +-2048.0 for "
                    "ANTSDR/AD9361 12-bit-in-int16 data, a ~24 dB difference."
                )
            self.iq_full_scale = float(fs)

    @property
    def capabilities(self) -> ReceiverCapabilities:
        """Derived from the session/meta this file was replayed from -- the *receiver
        of record*, not a generic 'file backend' capability (a replay is only ever
        as capable as whatever originally captured it)."""
        bw = self.meta.get("bandwidth_hz")
        return ReceiverCapabilities(
            receiver_type=str(self.meta.get("receiver_type", "file")),
            backend="file",
            tuning_range_hz=(self._center_hz, self._center_hz),
            sample_rates_hz=(self.sample_rate, self.sample_rate),
            sample_rate_is_range=False,
            max_instantaneous_bw_hz=float(bw) if bw else self.sample_rate,
            channel_count=1,
            gain_stages=(),
            gain_modes=("manual",),
            native_iq_format=self.iq_format,
            native_full_scale=self.iq_full_scale,
            supports_device_timestamps=bool(self.meta.get("timing")),
            supports_drop_reporting=True,   # replayed complete/dropped_samples are honest
            supports_sweep=False,
            reference_inputs=("none",),
            firmware=self.meta.get("receiver_firmware"),
            driver_version=self.meta.get("receiver_driver"),
        )

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)   # only relabels; the file is what it is

    def windows(self) -> Iterator[IQWindow]:
        n = int(self.sample_rate * self.cfg.window_s)
        total = iq_sample_count(self.path, self.iq_format)
        for i, start in enumerate(range(0, total - n + 1, n)):
            if self.iq_format == "cs8":
                iq = _read_cs8(self.path, start, n)
            else:
                iq = _read_cs16(self.path, start, n, full_scale=self.iq_full_scale)
            yield IQWindow(iq=iq,
                           captured_at=self._t0 + start / self.sample_rate,
                           sample_rate=self.sample_rate, center_freq_hz=self._center_hz,
                           receiver_type=str(self.meta.get("receiver_type", "file")),
                           receiver_serial=self.meta.get("receiver_serial"),
                           gain_db=self.meta.get("gain_db"), expected_samples=n,
                           metadata={"file": self.path, "window_index": i,
                                     "offset_samples": start,
                                     "iq_format": self.iq_format,
                                     "iq_full_scale": self.iq_full_scale})


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
        return hackrf_capabilities("hackrf_transfer")

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
        return hackrf_capabilities("libhackrf")

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
                           bandwidth_hz=info.get("bandwidth_hz"),
                           channel_id=int(info.get("channel_id", 0)),
                           timing=dict(info.get("timing") or {}),
                           metadata={"backend": "libhackrf", "gapped": False,
                                     "overflow_count": info["overflow_count"],
                                     "gap_before_samples": info.get("gap_before_samples", 0),
                                     "short_reads": info["short_reads"],
                                     "stream_rate_ratio": info["stream_rate_ratio"],
                                     "loss_detection": info.get("loss_detection"),
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
        return hackrf_capabilities("soapy")

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
    """Pick the live backend via the :mod:`aerix_rf.sdr.registry` table.

    ``prefer`` (or ``$AERIX_RF_BACKEND``) forces one named backend -- an unknown
    name or an unavailable one is a clear error naming what is missing. With no
    preference, tries :data:`aerix_rf.sdr.registry.AUTO_ORDER` in turn; if every
    entry is unavailable/fails, the error lists all of them with their reasons.
    """
    if cfg.sim:
        return SimSource(cfg)
    if cfg.iq_file:
        return FileIQSource(cfg)

    from .registry import REGISTRY, AUTO_ORDER  # lazy: avoid importing every backend eagerly

    prefer = prefer or os.environ.get("AERIX_RF_BACKEND", "").strip().lower() or None
    if prefer:
        entry = REGISTRY.get(prefer)
        if entry is None:
            raise RuntimeError(
                f"unknown backend {prefer!r}; known backends: {', '.join(sorted(REGISTRY))}"
            )
        available, reason = entry.probe()
        if not available:
            raise RuntimeError(f"backend {prefer!r} unavailable: {reason}")
        return entry.factory(cfg)

    errors: list[str] = []
    for name in AUTO_ORDER:
        entry = REGISTRY[name]
        available, reason = entry.probe()
        if not available:
            errors.append(f"{name}: {reason}")
            continue
        try:
            return entry.factory(cfg)
        except Exception as exc:  # noqa: BLE001 -- try the next backend
            errors.append(f"{name}: {exc}")
            log.warning("IQ backend %s unavailable: %s", name, exc)
    raise RuntimeError("no usable IQ backend: " + "; ".join(errors))
