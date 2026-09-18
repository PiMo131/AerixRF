"""ANTSDR E200 / AD9361 continuous RX via the libiio network context.

Path B only (docs/design/antsdr-backend.md section 2): plain ``python-iio``
(pylibiio) talking to the stock libiio IIOD network daemon on the E200, not the
UHD path and not the DJI-event accelerated firmware. It shares the exact
producer/consumer shape as ``libhackrf.py`` -- a producer thread blocks on
device reads and hands cheap chunks to the backend-neutral
:class:`~aerix_rf.sdr.stream.StreamAssembler`; all int16 -> complex64 scaling
happens in the consumer thread.

Hard device facts this module encodes (measured on the lab unit, not derived):
  * network context URI defaults to ``ip:192.168.1.10`` (``AERIX_RF_ANTSDR_URI``).
  * ``ad9361-phy`` is the control device; RX config lives on its INPUT channel
    ``voltage0`` (``sampling_frequency``, ``rf_bandwidth``, ``gain_control_mode``,
    ``hardwaregain``); the RX LO lives on its OUTPUT channel ``altvoltage0``
    (``frequency``, Hz as a decimal string).
  * ``cf-ad9361-lpc`` is the RX capture device; channels ``voltage0``=I,
    ``voltage1``=Q, native format ``le:S12/16>>0`` (12-bit, right-justified in
    an int16) -- so ``iq_full_scale = 2048.0``, NOT 32768.0. Getting this wrong
    silently shifts every RSSI by ~24 dB (see capture.py's cs16 full-scale
    discussion).
  * libiio gives no per-buffer overflow/sequence counter on this firmware, so
    this backend can NEVER assert an exact drop count -- ``StreamAssembler`` is
    constructed with ``reports_drops=False`` and every window's
    ``loss_detection`` is ``"inferred_rate_only"``. The only silent-loss
    signal is ``stream_rate_ratio`` (CUMULATIVE achieved/nominal samples since
    the first pushed chunk -- see stream.py) plus ``stream_rate_ratio_recent``
    (a noisier trailing >=10s estimate). ``rate_warning`` fires when the
    cumulative ratio drops below ``RATE_WARNING_RATIO`` (0.995) after
    ``RATE_WARNING_MIN_ELAPSED_S`` (10s) of history, OR the recent ratio drops
    below ``RATE_WARNING_RATIO_RECENT`` (0.97) AND the recent-window sample
    deficit (``samples_deficit_recent``) is at least
    ``RATE_WARNING_RECENT_DEFICIT_FRAC`` (0.5%) of one capture window's
    samples -- see docs/design/antsdr-backend.md "Measured host-path
    throughput (2026-09-18)" for why a bare trailing-window ratio threshold
    alone (no deficit evidence required) false-fired on 487/599 windows of a
    real loss-free 600s soak.
  * Measured throughput: 12.288 MS/s is clean over the GbE link; >=15.36 MS/s
    is lossy on this host/link -- see the profile table below.
  * The *requested* config (what this backend told ``ad9361-phy`` to do) is
    NOT proof of the *actual* device state -- a session found with a raised,
    flattened noise floor and no external signal had an identical requested
    config to a normal session, and there was no way to tell whether the
    device was actually in the requested state. This backend therefore reads
    back ``ad9361-phy`` input channel ``voltage0`` attrs (``hardwaregain``,
    ``gain_control_mode``, ``rf_bandwidth``, ``sampling_frequency``,
    ``rf_port_select``) and output channel ``altvoltage0`` attr (``frequency``,
    the RX LO) after every config change (open + each ``tune()``), stores them
    as ``self.readback``, and flags ``self.readback_mismatch`` (with a WARNING
    log) if any read-back value differs from the requested one beyond
    tolerance (gain +/-0.5 dB, rates/bandwidth +/-1%, LO +/-1 kHz, gain-control
    mode string). ``rssi`` (also on ``voltage0``) is read once per WINDOW
    instead, since it is a live measurement, not a config-echo value; see
    ``_read_rssi_if_cheap`` for the >5 ms cost bailout.

Capability notes NOT representable in ``ReceiverCapabilities`` today (no field
exists; documented here instead of extending that dataclass out of scope):
  * ``tuning_range_hz`` is advertised as (70e6, 6e9) here -- the AD9361
    datasheet's PLL actually tunes as low as ~46.875e6, but 70e6 is the range
    this backend documents/supports; treat anything below 70e6 as untested.
  * a sustained/reliable ceiling of ``max_sustained_rate_hz = 13.44e6`` exists
    on top of the nominal ``sample_rates_hz`` range advertised by the AD9361
    itself (2.083e6-61.44e6): rates above ~13.44e6 are within the chip's
    capability but not within this host/GbE link's measured sustained
    throughput (see DEVICE FACTS above). Callers should not pick a rate above
    13.44e6 and expect ``stream_rate_ratio`` to stay near 1.0.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Iterator, Optional

import numpy as np

from .capture import GainStage, IQSource, IQWindow, ReceiverCapabilities
from .stream import StreamAssembler

log = logging.getLogger("aerix.rf.sdr.antsdr_iio")

DEFAULT_URI = "ip:192.168.1.10"
IQ_FULL_SCALE = 2048.0                 # 12-bit, right-justified in int16 (measured)
KERNEL_BUFFERS = 8
BUFFER_SAMPLES = 1_048_576
QUEUE_MAX_S = 2.0
# Only silent-loss detector on this backend. Two-part gate (see
# docs/design/antsdr-backend.md "Measured host-path throughput (2026-09-18)"):
# the CUMULATIVE ratio is stable/low-noise but slow to react, so it needs a
# tight threshold and a minimum warm-up; the RECENT (trailing-window) ratio
# is noisy (chunk-timing/OS scheduling jitter) but reacts fast, so a bare
# threshold on it alone false-fired ``rate_warning`` on 487/599 windows of a
# real loss-free 600s soak (``stream_rate_ratio`` never dropped below 0.9998
# in that run). The recent branch therefore ALSO requires evidence of an
# actual sample deficit accrued during that same trailing window
# (``samples_deficit_recent``, from ``StreamAssembler`` -- honest, computed
# from chunk sample counts/timestamps, not wall-clock read deltas) of at
# least ``RATE_WARNING_RECENT_DEFICIT_FRAC`` of one capture window's samples:
# jitter alone (no lost samples) must never warn.
RATE_WARNING_RATIO = 0.995             # cumulative-ratio warning threshold
RATE_WARNING_MIN_ELAPSED_S = 10.0      # cumulative ratio must have this much history
RATE_WARNING_RATIO_RECENT = 0.97       # trailing-window ratio warning threshold
RATE_WARNING_RECENT_DEFICIT_FRAC = 0.005   # min recent-window deficit (frac of one
                                            # capture window's samples) to count as
                                            # a real, not merely jitter-driven, dip
MAX_SUSTAINED_RATE_HZ = 13.44e6        # measured link ceiling; see module docstring

# Readback-vs-requested tolerance (see module docstring "requested config is
# not proof of actual state"). Architect-approved tolerances, not measured
# AD9361 precision limits -- they exist to catch a genuinely wrong/stuck
# device state, not to assert exact round-trip equality of a string attr.
READBACK_TOL_GAIN_DB = 0.5             # hardwaregain, manual mode only
READBACK_TOL_RATE_FRAC = 0.01          # rf_bandwidth / sampling_frequency, +/-1%
READBACK_TOL_LO_HZ = 1000.0            # RX LO, +/-1 kHz
RSSI_READ_BUDGET_MS = 5.0              # per-window rssi attr read; see _read_rssi_if_cheap

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


def _cs16_2048_to_iq(raw: np.ndarray) -> np.ndarray:
    """int16 interleaved I,Q (AD9361 12-bit right-justified) -> complex64, /-2048."""
    raw = raw.astype(np.float32)
    iq = raw[0::2] + 1j * raw[1::2]
    return (iq / IQ_FULL_SCALE).astype(np.complex64)


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


_GAIN_STAGES = (GainStage("rx", 0.0, 73.0, None),)  # AD9361 RX hardwaregain, continuous


def antsdr_iio_capabilities(*, firmware: str | None = None) -> ReceiverCapabilities:
    """Static ANTSDR/AD9361 capabilities for the libiio backend.

    See the module docstring for two facts this dataclass has no field for:
    the advertised-vs-documented tuning floor, and ``MAX_SUSTAINED_RATE_HZ``.
    """
    return ReceiverCapabilities(
        receiver_type="antsdr",
        backend="antsdr_iio",
        tuning_range_hz=(70e6, 6e9),
        sample_rates_hz=(2.083e6, 61.44e6),
        sample_rate_is_range=True,
        max_instantaneous_bw_hz=56e6,
        channel_count=1,
        gain_stages=_GAIN_STAGES,
        gain_modes=("manual", "agc_slow", "agc_fast"),
        native_iq_format="cs16",
        native_full_scale=IQ_FULL_SCALE,
        supports_device_timestamps=False,
        supports_drop_reporting=False,
        supports_sweep=False,
        reference_inputs=("none",),
        firmware=firmware,
    )


class AntsdrIIOSource(IQSource):
    """Continuous ANTSDR E200 / AD9361 RX stream via the libiio network context.

    Producer thread: blocking ``buf.refill()`` -> ``buf.read()`` -> cheap
    ``np.frombuffer`` view -> :meth:`StreamAssembler.push`. All int16 ->
    complex64 scaling happens in the consumer thread inside the assembler,
    exactly like ``LibHackRFSource`` / ``HackRFStream``.
    """

    receiver_type = "antsdr"

    def __init__(self, *, uri: str | None = None, profile: str | None = None,
                 sample_rate: float | None = None,
                 center_freq_hz: float = 2440e6, gain_mode: str = "manual",
                 gain_db: float = 40.0, kernel_buffers: int = KERNEL_BUFFERS,
                 buffer_samples: int = BUFFER_SAMPLES,
                 window_seconds: float = 1.0) -> None:
        self._iio = _load_iio()
        self.uri = uri or os.environ.get("AERIX_RF_ANTSDR_URI", DEFAULT_URI)
        prof = resolve_profile(profile)
        self.rf_bandwidth = float(prof["rf_bandwidth"])
        if sample_rate is not None:
            # Caller (CLI --sample-rate) asked to override this fixed profile's
            # rate: apply it, but validate against the AD9361's own range and
            # warn (not reject) above the measured sustained link ceiling --
            # the chip still accepts it, `stream_rate_ratio` just won't stay
            # near 1.0 there (see module docstring).
            lo, hi = antsdr_iio_capabilities().sample_rates_hz
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
        # (for diagnosing sustained-throughput host-path config without a CLI
        # flag -- see docs/design/antsdr-backend.md "Measured host-path
        # throughput"); else the module default.
        self.kernel_buffers = int(os.environ.get("AERIX_RF_ANTSDR_KBUFS", kernel_buffers)
                                   if kernel_buffers == KERNEL_BUFFERS else kernel_buffers)
        self.buffer_samples = int(os.environ.get("AERIX_RF_ANTSDR_BUFSAMPLES", buffer_samples)
                                   if buffer_samples == BUFFER_SAMPLES else buffer_samples)
        self.window_seconds = float(window_seconds)
        self._center_hz = float(center_freq_hz)
        # Debug counters for diagnosing host-path throughput (refill cadence,
        # not device-reported -- this firmware has no overflow/seq counter).
        self._refill_count = 0
        self._refill_bytes = 0
        self._max_refill_gap_s = 0.0
        self._last_refill_end_ts: float | None = None
        # Config readback state (see module docstring); populated by
        # ``_refresh_readback`` after open and after every ``tune()``.
        self.readback: dict[str, Any] = {}
        self.readback_mismatch: bool = False
        # rssi read-cost gate: None = not measured yet, True/False = decided
        # on the first window (see ``_read_rssi_if_cheap``).
        self._rssi_enabled: Optional[bool] = None
        self._rssi_read_ms: Optional[float] = None

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

        self._asm = StreamAssembler(
            self.sample_rate, raw_to_iq=_cs16_2048_to_iq, reports_drops=False,
            queue_max_s=QUEUE_MAX_S, chunk_samples_hint=self.buffer_samples,
            bandwidth_hz=self.rf_bandwidth, still_active=lambda: self._running,
        )

        self._running = False
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._rate_warning = False
        self._start()

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

    def _refresh_readback(self) -> None:
        """Read back ``ad9361-phy`` config attrs after a config change (open or
        ``tune()``) and compare against what was requested; see module
        docstring "requested config is not proof of actual state"."""
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

    def _read_rssi_if_cheap(self) -> Optional[float]:
        """Read ``voltage0.rssi`` (e.g. ``"32.75 dB"``) once per window. This is
        an attr read over the network to the IIOD daemon, not a local register
        read, so its cost is measured on the first call: if it exceeds
        ``RSSI_READ_BUDGET_MS`` the per-window read is permanently disabled for
        this source (an occasional slow read is tolerated; only a sustained-slow
        first measurement disables it) and ``rssi_db_readback`` is ``None`` for
        every subsequent window."""
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

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return antsdr_iio_capabilities(firmware=self.fw_version or self.hw_model)

    @property
    def center_freq_hz(self) -> float:
        """Actual RX LO, for session metadata -- see ``cli._receiver_meta``."""
        return self._center_hz

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)
        self._lo_ctrl.attrs["frequency"].value = str(int(self._center_hz))
        self._refresh_readback()
        self._asm.flush()

    # --- producer thread -------------------------------------------------------
    def _start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="antsdr-iio-rx", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        buf = self._iio.Buffer(self.rxdev, self.buffer_samples, False)
        try:
            while not self._stop_evt.is_set():
                t_before = time.time()
                buf.refill()
                data = buf.read()
                t_after = time.time()
                if self._last_refill_end_ts is not None:
                    gap = t_before - self._last_refill_end_ts
                    if gap > self._max_refill_gap_s:
                        self._max_refill_gap_s = gap
                    if gap > 0.15:
                        log.warning("ANTSDR refill #%d: %.3fs gap since previous refill "
                                    "returned (host stalled reading the stream)",
                                    self._refill_count, gap)
                self._last_refill_end_ts = t_after
                self._refill_count += 1
                self._refill_bytes += len(data)
                if self._refill_count % 50 == 0:
                    log.info("ANTSDR refill #%d: %d bytes this refill, %.3fs refill+read "
                             "duration, max inter-refill gap so far %.3fs",
                             self._refill_count, len(data), t_after - t_before,
                             self._max_refill_gap_s)
                raw = np.frombuffer(data, dtype="<i2")
                if raw.size == 0:
                    continue
                self._asm.push(raw, t_after, self._center_hz, dropped_before=0)
        except Exception:  # noqa: BLE001 -- surface as a stopped stream, not a crash
            log.exception("ANTSDR RX thread stopped unexpectedly")
        finally:
            self._running = False
            self._asm.mark_stopped()
            log.info("ANTSDR RX thread stopped: %d refills, %d bytes total, "
                     "max inter-refill gap %.3fs", self._refill_count,
                     self._refill_bytes, self._max_refill_gap_s)

    # --- consumer / IQSource contract ------------------------------------------
    def windows(self) -> Iterator[IQWindow]:
        n = int(self.sample_rate * self.window_seconds)
        while True:
            win = self._asm.read_window(n)
            if win is None:
                return   # stream stopped / device lost
            iq, info = win
            ratio = info["stream_rate_ratio"]
            ratio_recent = info.get("stream_rate_ratio_recent", ratio)
            elapsed_s = info.get("stream_rate_elapsed_s", 0.0)
            deficit_recent = info.get("samples_deficit_recent", 0) or 0
            # Cumulative ratio: only trust it once >=10s of stream have been
            # measured from the first pushed chunk (a short/noisy cumulative
            # average is not trustworthy yet). Recent ratio: no warm-up gate --
            # it exists specifically to catch a stall or stalled-then-recovered
            # burst fast, so it must fire immediately if it's bad -- but ONLY
            # when the dip is backed by an actual sample deficit accrued in
            # that same trailing window, never on jitter alone (see
            # RATE_WARNING_RECENT_DEFICIT_FRAC above).
            rate_warning = ((ratio < RATE_WARNING_RATIO and elapsed_s >= RATE_WARNING_MIN_ELAPSED_S)
                             or (ratio_recent < RATE_WARNING_RATIO_RECENT
                                 and deficit_recent >= RATE_WARNING_RECENT_DEFICIT_FRAC * n))
            self._rate_warning = rate_warning
            rssi_db_readback = self._read_rssi_if_cheap()
            yield IQWindow(
                iq=iq, captured_at=info["captured_at"], sample_rate=self.sample_rate,
                center_freq_hz=info["center_freq_hz"], receiver_type="antsdr",
                receiver_serial=None, gain_db=self.gain_db,
                complete=info["complete"], expected_samples=n,
                dropped_samples=info["dropped_samples"],
                bandwidth_hz=info.get("bandwidth_hz"),
                channel_id=int(info.get("channel_id", 0)),
                timing=dict(info.get("timing") or {}),
                metadata={
                    "backend": "antsdr_iio",
                    "iq_format": "cs16",
                    "iq_full_scale": IQ_FULL_SCALE,
                    "bandwidth_hz": self.rf_bandwidth,
                    "gain_mode": self.gain_mode,
                    "gain_db": self.gain_db,
                    "loss_detection": info.get("loss_detection"),
                    "stream_rate_ratio": ratio,
                    "stream_rate_ratio_recent": ratio_recent,
                    "stream_rate_elapsed_s": elapsed_s,
                    "samples_deficit": info.get("samples_deficit"),
                    "samples_deficit_recent": info.get("samples_deficit_recent"),
                    "rate_warning": rate_warning,
                    "max_refill_gap_ms": round(self._max_refill_gap_s * 1000.0, 1),
                    "overflow_count": info["overflow_count"],
                    "gap_before_samples": info.get("gap_before_samples", 0),
                    "short_reads": info["short_reads"],
                    "receiver_firmware": self.fw_version or self.hw_model,
                    "uri": self.uri,
                    "readback": dict(self.readback),
                    "readback_mismatch": self.readback_mismatch,
                    "rssi_db_readback": rssi_db_readback,
                },
            )

    def close(self) -> None:
        self._stop_evt.set()
        self._running = False
        self._asm.mark_stopped()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
