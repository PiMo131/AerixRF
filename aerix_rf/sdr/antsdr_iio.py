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
import threading
import time
from typing import Any, Iterator, Optional

import numpy as np

from .antsdr_iio_device import (
    BUFFER_SAMPLES,
    DEFAULT_URI,
    IQ_FULL_SCALE,
    KERNEL_BUFFERS,
    MAX_SUSTAINED_RATE_HZ,
    PROFILES,
    READBACK_TOL_GAIN_DB,
    READBACK_TOL_LO_HZ,
    READBACK_TOL_RATE_FRAC,
    RSSI_READ_BUDGET_MS,
    SAMPLE_RATE_RANGE_HZ,
    AntsdrIioDevice,
    _load_iio,
    _parse_leading_float,
    resolve_profile,
)
from .capture import GainStage, IQSource, IQWindow, ReceiverCapabilities
from .stream import StreamAssembler

log = logging.getLogger("aerix.rf.sdr.antsdr_iio")

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
# MAX_SUSTAINED_RATE_HZ, READBACK_TOL_*, RSSI_READ_BUDGET_MS, PROFILES,
# resolve_profile, _load_iio, _parse_leading_float now live in
# antsdr_iio_device.py (imported above) -- re-exported here under the same
# names since existing callers/tests reference them as ``antsdr_iio.NAME``.


def _cs16_2048_to_iq(raw: np.ndarray) -> np.ndarray:
    """int16 interleaved I,Q (AD9361 12-bit right-justified) -> complex64, /-2048."""
    raw = raw.astype(np.float32)
    iq = raw[0::2] + 1j * raw[1::2]
    return (iq / IQ_FULL_SCALE).astype(np.complex64)


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
        sample_rates_hz=SAMPLE_RATE_RANGE_HZ,
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
        # No device timestamp and no overflow/drop counter of any kind: the
        # IIO image exposes neither (measured 2026-09-18, see antsdr-specialist).
        # loss_detection is unconditionally "inferred_rate_only" (stream.py) --
        # a rate ratio, not an exact lost-sample count.
        timestamp_quality="host_wallclock",
        loss_counter_available=False,
    )


class AntsdrIIOSource(AntsdrIioDevice, IQSource):
    """Continuous ANTSDR E200 / AD9361 RX stream via the libiio network context.

    Inherits device-only open/configure/readback/tune/refill logic from
    :class:`~aerix_rf.sdr.antsdr_iio_device.AntsdrIioDevice` (T7c-1 factoring)
    and adds the producer-thread + :class:`StreamAssembler` shape on top:
    blocking ``buf.refill()`` -> ``buf.read()`` -> cheap ``np.frombuffer``
    view -> :meth:`StreamAssembler.push`. All int16 -> complex64 scaling
    happens in the consumer thread inside the assembler, exactly like
    ``LibHackRFSource`` / ``HackRFStream``.
    """

    receiver_type = "antsdr"

    def __init__(self, *, uri: str | None = None, profile: str | None = None,
                 sample_rate: float | None = None,
                 center_freq_hz: float = 2440e6, gain_mode: str = "manual",
                 gain_db: float = 40.0, kernel_buffers: int = KERNEL_BUFFERS,
                 buffer_samples: int = BUFFER_SAMPLES,
                 window_seconds: float = 1.0) -> None:
        super().__init__(
            uri=uri, profile=profile, sample_rate=sample_rate,
            center_freq_hz=center_freq_hz, gain_mode=gain_mode, gain_db=gain_db,
            kernel_buffers=kernel_buffers, buffer_samples=buffer_samples,
        )
        self.window_seconds = float(window_seconds)
        # Debug counters for diagnosing host-path throughput (refill cadence,
        # not device-reported -- this firmware has no overflow/seq counter).
        self._refill_count = 0
        self._refill_bytes = 0
        self._max_refill_gap_s = 0.0
        self._last_refill_end_ts: float | None = None

        self._asm = StreamAssembler(
            self.sample_rate, raw_to_iq=_cs16_2048_to_iq, reports_drops=False,
            queue_max_s=QUEUE_MAX_S, chunk_samples_hint=self.buffer_samples,
            bandwidth_hz=self.rf_bandwidth, still_active=lambda: self._running,
            raw_full_scale=IQ_FULL_SCALE,
        )

        self._running = False
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._rate_warning = False
        self._start()

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return antsdr_iio_capabilities(firmware=self.fw_version or self.hw_model)

    def tune(self, center_freq_hz: float) -> None:
        super().tune(center_freq_hz)
        self._asm.flush()

    # --- producer thread -------------------------------------------------------
    def _start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="antsdr-iio-rx", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self.open_buffer()
        try:
            while not self._stop_evt.is_set():
                t_before = time.time()
                data = self.refill_read()
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
                    "clip_fraction": info.get("clip_fraction"),
                    "peak_abs_frac": info.get("peak_abs_frac"),
                    "clip_warning": info.get("clip_warning", False),
                },
            )

    def close(self) -> None:
        self._stop_evt.set()
        self._running = False
        self._asm.mark_stopped()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        super().close()
