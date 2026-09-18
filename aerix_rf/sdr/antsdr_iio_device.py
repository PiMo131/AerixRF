"""ANTSDR E200 / AD9361 libiio device glue -- factored out of ``antsdr_iio.py``
(T7c-1) so it can be reused WITHOUT the assembler/producer-thread shape by the
acquisition producer OS process (``producer_main.py``'s ``antsdr_iio`` source
branch), while ``antsdr_iio.AntsdrIIOSource`` (in-process thread backend)
keeps working by inheriting this same code.

Owns: the ``iio`` import, URI/profile resolution, opening ``ad9361-phy`` +
``cf-ad9361-lpc`` + their channels, applying RX config (sample rate,
bandwidth, gain mode/db, LO), reading back config attrs into a plain dict,
tuning the LO, refilling/reading the RX buffer, and closing everything down.
Does NOT own any producer/consumer thread, ``StreamAssembler``, or int16 ->
complex64 scaling -- see ``antsdr_iio.py`` and ``producer_main.py`` for the
two callers that add those on top.

See ``antsdr_iio.py``'s module docstring for the underlying hardware facts
(12-bit right-justified int16 samples, no overflow/sequence counter, readback
vs. requested-config distinction, measured throughput ceiling) -- this module
only relocates the code, it does not change any of those facts.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Optional

log = logging.getLogger("aerix.rf.sdr.antsdr_iio_device")

DEFAULT_URI = "ip:192.168.1.10"
IQ_FULL_SCALE = 2048.0                 # 12-bit, right-justified in int16 (measured)
KERNEL_BUFFERS = 8
BUFFER_SAMPLES = 1_048_576

# AD9361's own advertised rate range, and the measured sustained host/GbE-link
# ceiling on top of it (see antsdr_iio.py module docstring) -- both live here
# (not only in ReceiverCapabilities) because this module validates/warns on
# an explicit sample_rate override independently of that dataclass.
SAMPLE_RATE_RANGE_HZ = (2.083e6, 61.44e6)
MAX_SUSTAINED_RATE_HZ = 13.44e6

# Readback-vs-requested tolerance (see antsdr_iio.py module docstring
# "requested config is not proof of actual state"). Architect-approved
# tolerances, not measured AD9361 precision limits.
READBACK_TOL_GAIN_DB = 0.5             # hardwaregain, manual mode only
READBACK_TOL_RATE_FRAC = 0.01          # rf_bandwidth / sampling_frequency, +/-1%
READBACK_TOL_LO_HZ = 1000.0            # RX LO, +/-1 kHz
RSSI_READ_BUDGET_MS = 5.0              # per-call rssi attr read budget; see read_rssi_if_cheap

# Architect-approved default + named profiles (sample_rate Hz, rf_bandwidth Hz).
PROFILES: dict[str, dict[str, float]] = {
    "default": {"sample_rate": 12.288e6, "rf_bandwidth": 10.0e6},
    "antsdr_13p44": {"sample_rate": 13.44e6, "rf_bandwidth": 11.0e6},
    "antsdr_11p52": {"sample_rate": 11.52e6, "rf_bandwidth": 10.0e6},
}

_IMPORT_HINT = (
    "python-iio (pylibiio) is required for the ANTSDR backend. Install with "
    "`uv sync --extra antsdr` plus the libiio runtime; on this host also set "
    "LD_LIBRARY_PATH=/home/jarvis/aerix-rf/.antsdr-tools/mamba/envs/antsdr/lib"
)

_LEADING_FLOAT_RE = re.compile(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?")


def _load_iio():
    """Lazy ``import iio``; never a hard dependency of this module or the registry."""
    try:
        import iio
    except Exception as exc:  # noqa: BLE001
        raise ImportError(_IMPORT_HINT) from exc
    return iio


def _parse_leading_float(s: Optional[str]) -> Optional[float]:
    """Parse the leading numeric token of an attr string, e.g. ``"40.000000 dB"``
    -> ``40.0``, ``"12288000"`` -> ``12288000.0``. ``None`` on anything
    unparseable (missing attr, empty string, non-numeric) -- callers must treat
    that as "could not verify", not as a silent 0.0."""
    if not s:
        return None
    m = _LEADING_FLOAT_RE.match(s.strip())
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def resolve_profile(name: Optional[str]) -> dict[str, float]:
    """Look up a named profile; ``None`` -> ``$AERIX_RF_ANTSDR_PROFILE`` -> "default"."""
    key = (name or os.environ.get("AERIX_RF_ANTSDR_PROFILE") or "default").strip()
    try:
        return dict(PROFILES[key])
    except KeyError:
        raise ValueError(
            f"unknown ANTSDR profile {key!r}; known profiles: {', '.join(sorted(PROFILES))}"
        ) from None


class AntsdrIioDevice:
    """Device-only ANTSDR E200 / AD9361 libiio glue: open, configure, read
    back config attrs, tune, refill/read the RX buffer, close.

    No producer/consumer thread and no complex64 scaling -- callers own the
    hot loop; this class owns only calls into ``iio``.
    """

    def __init__(self, *, uri: str | None = None, profile: str | None = None,
                 sample_rate: float | None = None,
                 center_freq_hz: float = 2440e6, gain_mode: str = "manual",
                 gain_db: float = 40.0, kernel_buffers: int = KERNEL_BUFFERS,
                 buffer_samples: int = BUFFER_SAMPLES) -> None:
        self._iio = _load_iio()
        self.uri = uri or os.environ.get("AERIX_RF_ANTSDR_URI", DEFAULT_URI)
        prof = resolve_profile(profile)
        self.rf_bandwidth = float(prof["rf_bandwidth"])
        if sample_rate is not None:
            # Caller asked to override this fixed profile's rate: apply it,
            # but validate against the AD9361's own range and warn (not
            # reject) above the measured sustained link ceiling -- the chip
            # still accepts it, `stream_rate_ratio` just won't stay near 1.0.
            lo, hi = SAMPLE_RATE_RANGE_HZ
            if not (lo <= sample_rate <= hi):
                raise ValueError(
                    f"--sample-rate {sample_rate:g} Hz is outside the ANTSDR/AD9361 "
                    f"capability range {lo:g}-{hi:g} Hz"
                )
            if sample_rate > MAX_SUSTAINED_RATE_HZ:
                log.warning(
                    "ANTSDR sample_rate %.3f MS/s exceeds the measured sustained "
                    "link ceiling %.3f MS/s; expect stream_rate_ratio to drop below 1.0",
                    sample_rate / 1e6, MAX_SUSTAINED_RATE_HZ / 1e6,
                )
            self.sample_rate = float(sample_rate)
        else:
            self.sample_rate = float(prof["sample_rate"])
        self.gain_mode = str(gain_mode)
        self.gain_db = float(gain_db)
        # ``kernel_buffers``/``buffer_samples`` ctor args win; else an env var
        # (diagnosing sustained-throughput host-path config without a CLI
        # flag); else the module default.
        self.kernel_buffers = int(os.environ.get("AERIX_RF_ANTSDR_KBUFS", kernel_buffers)
                                   if kernel_buffers == KERNEL_BUFFERS else kernel_buffers)
        self.buffer_samples = int(os.environ.get("AERIX_RF_ANTSDR_BUFSAMPLES", buffer_samples)
                                   if buffer_samples == BUFFER_SAMPLES else buffer_samples)
        self._center_hz = float(center_freq_hz)
        # Config readback state (see antsdr_iio.py module docstring);
        # populated by ``_refresh_readback`` after open and after every
        # ``tune()``.
        self.readback: dict[str, Any] = {}
        self.readback_mismatch: bool = False
        # rssi read-cost gate: None = not measured yet, True/False = decided
        # on the first call (see ``_read_rssi_if_cheap``).
        self._rssi_enabled: Optional[bool] = None
        self._rssi_read_ms: Optional[float] = None
        self._buf = None

        self.ctx = self._iio.Context(self.uri)
        self.phy = self.ctx.find_device("ad9361-phy")
        self.rxdev = self.ctx.find_device("cf-ad9361-lpc")
        if self.phy is None or self.rxdev is None:
            raise RuntimeError(
                f"ANTSDR devices not found on {self.uri!r} "
                "(need ad9361-phy + cf-ad9361-lpc; wrong URI or device off?)"
            )

        self._rx_ctrl = self.phy.find_channel("voltage0", False)   # RX input ctrl
        self._lo_ctrl = self.phy.find_channel("altvoltage0", True)  # RX LO (output chan)
        self._i_chan = self.rxdev.find_channel("voltage0", False)
        self._q_chan = self.rxdev.find_channel("voltage1", False)
        for ch in (self._i_chan, self._q_chan):
            ch.enabled = True

        ctx_attrs = getattr(self.ctx, "attrs", {}) or {}
        self.fw_version = ctx_attrs.get("fw_version")
        self.hw_model = ctx_attrs.get("hw_model") or ctx_attrs.get("ad9361-phy,model")

        self._apply_config(apply_lo=True)
        self.rxdev.set_kernel_buffers_count(self.kernel_buffers)
        self._refresh_readback()

    @property
    def center_freq_hz(self) -> float:
        return self._center_hz

    # --- device configuration -------------------------------------------------
    def _apply_config(self, *, apply_lo: bool) -> None:
        """Set runtime-only phy attrs (nothing persisted to the device)."""
        self._rx_ctrl.attrs["sampling_frequency"].value = str(int(self.sample_rate))
        self._rx_ctrl.attrs["rf_bandwidth"].value = str(int(self.rf_bandwidth))
        self._rx_ctrl.attrs["gain_control_mode"].value = self.gain_mode
        if self.gain_mode == "manual":
            # "%g"-style formatting: "40" for a whole-number dB value (matches the
            # attribute strings a real ad9361-phy round-trips), "40.5" otherwise.
            self._rx_ctrl.attrs["hardwaregain"].value = f"{self.gain_db:g}"
        if apply_lo:
            self._lo_ctrl.attrs["frequency"].value = str(int(self._center_hz))

    def _attr_value(self, chan, name: str) -> Optional[str]:
        """Best-effort read of ``chan.attrs[name].value``; ``None`` if the attr
        doesn't exist on this firmware/channel or the read otherwise fails --
        a readback that can't be verified must never be mistaken for a match."""
        try:
            return chan.attrs[name].value
        except Exception:  # noqa: BLE001 -- KeyError (fake) or OSError (real libiio)
            return None

    def _refresh_readback(self) -> dict[str, Any]:
        """Read back ``ad9361-phy`` config attrs after a config change (open or
        ``tune()``) and compare against what was requested; see
        antsdr_iio.py module docstring "requested config is not proof of
        actual state"."""
        hw_raw = self._attr_value(self._rx_ctrl, "hardwaregain")
        mode_raw = self._attr_value(self._rx_ctrl, "gain_control_mode")
        bw_raw = self._attr_value(self._rx_ctrl, "rf_bandwidth")
        fs_raw = self._attr_value(self._rx_ctrl, "sampling_frequency")
        port_raw = self._attr_value(self._rx_ctrl, "rf_port_select")
        lo_raw = self._attr_value(self._lo_ctrl, "frequency")

        rb: dict[str, Any] = {
            "hardwaregain_db": _parse_leading_float(hw_raw),
            "hardwaregain_raw": hw_raw,
            "gain_control_mode": mode_raw,
            "rf_bandwidth_hz": _parse_leading_float(bw_raw),
            "rf_bandwidth_raw": bw_raw,
            "sampling_frequency_hz": _parse_leading_float(fs_raw),
            "sampling_frequency_raw": fs_raw,
            "rf_port": port_raw,
            "rx_lo_hz": _parse_leading_float(lo_raw),
            "rx_lo_raw": lo_raw,
            "fw_version": self.fw_version,
            "hw_model": self.hw_model,
        }

        mismatches: list[str] = []
        if self.gain_mode == "manual":
            got = rb["hardwaregain_db"]
            if got is None or abs(got - self.gain_db) > READBACK_TOL_GAIN_DB:
                mismatches.append(f"hardwaregain requested={self.gain_db:g}dB readback={got!r}")
        if rb["gain_control_mode"] != self.gain_mode:
            mismatches.append(
                f"gain_control_mode requested={self.gain_mode!r} readback={rb['gain_control_mode']!r}"
            )
        bw_got = rb["rf_bandwidth_hz"]
        if bw_got is None or abs(bw_got - self.rf_bandwidth) > READBACK_TOL_RATE_FRAC * self.rf_bandwidth:
            mismatches.append(f"rf_bandwidth requested={self.rf_bandwidth:g}Hz readback={bw_got!r}")
        fs_got = rb["sampling_frequency_hz"]
        if fs_got is None or abs(fs_got - self.sample_rate) > READBACK_TOL_RATE_FRAC * self.sample_rate:
            mismatches.append(f"sampling_frequency requested={self.sample_rate:g}Hz readback={fs_got!r}")
        lo_got = rb["rx_lo_hz"]
        if lo_got is None or abs(lo_got - self._center_hz) > READBACK_TOL_LO_HZ:
            mismatches.append(f"rx_lo requested={self._center_hz:g}Hz readback={lo_got!r}")

        self.readback = rb
        self.readback_mismatch = bool(mismatches)
        if mismatches:
            log.warning("ANTSDR readback mismatch (device may not be in the requested "
                        "state): %s", "; ".join(mismatches))
        return rb

    def _read_rssi_if_cheap(self) -> Optional[float]:
        """Read ``voltage0.rssi`` (e.g. ``"32.75 dB"``). Cost is measured on
        the first call: if it exceeds ``RSSI_READ_BUDGET_MS`` this read is
        permanently disabled for this device (an occasional slow read is
        tolerated; only a sustained-slow first measurement disables it) and
        every subsequent call returns ``None``."""
        if self._rssi_enabled is False:
            return None
        t0 = time.time()
        raw = self._attr_value(self._rx_ctrl, "rssi")
        dt_ms = (time.time() - t0) * 1000.0
        if self._rssi_enabled is None:
            self._rssi_enabled = dt_ms <= RSSI_READ_BUDGET_MS
            self._rssi_read_ms = dt_ms
            if not self._rssi_enabled:
                log.warning(
                    "ANTSDR rssi attr read took %.2f ms (> %.1f ms budget); "
                    "disabling per-window rssi readback for this session",
                    dt_ms, RSSI_READ_BUDGET_MS,
                )
        if not self._rssi_enabled:
            return None
        return _parse_leading_float(raw)

    def tune(self, center_freq_hz: float) -> dict[str, Any]:
        """Set the RX LO on the device and refresh the readback dict. Does
        NOT flush any assembler/ring -- callers that have one do that
        themselves right after this returns."""
        self._center_hz = float(center_freq_hz)
        self._lo_ctrl.attrs["frequency"].value = str(int(self._center_hz))
        return self._refresh_readback()

    # --- RX buffer ---------------------------------------------------------
    def open_buffer(self):
        self._buf = self._iio.Buffer(self.rxdev, self.buffer_samples, False)
        return self._buf

    def refill_read(self) -> bytes:
        """Blocking ``buf.refill()`` -> ``buf.read()``; raises whatever
        ``iio`` raises on a device-side error (callers decide what that means)."""
        self._buf.refill()
        return self._buf.read()

    def close(self) -> None:
        self._buf = None
