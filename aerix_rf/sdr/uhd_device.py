"""ANTSDR E200 / AD9361 UHD (MicroPhase ``uhd-antsdr`` fork) device glue (T8).

Sibling of ``antsdr_iio_device.py`` (the libiio path to the SAME physical
box): owns the ``uhd`` import, ``MultiUSRP`` open/configure, config readback,
tuning, and packet-loop RX chunk assembly. Does NOT own any producer/consumer
thread or int16 -> complex64 scaling -- see ``producer_main.py``'s
``UhdProducerSource`` for the adapter that plugs this into the acquisition
producer OS process (T7's shape), exactly like ``AntsdrIioProducerSource``
does for ``AntsdrIioDevice``.

Full-scale measurement (2026-09-19, live E200/B210-labelled UHD fork,
``addr=192.168.1.10``, ambient 2437 MHz, manual gain 40 dB, ``StreamArgs("sc16",
"sc16")``): observed max |I|=114, |Q|=83 out of a signed 16-bit container.
That is consistent with the AD9361's native 12-bit sample RIGHT-justified in
int16 (same convention as the libiio path's ``antsdr_iio_device.IQ_FULL_SCALE
= 2048.0``), not left-justified to the full int16 range (32768) -- a
left-justified reading would put ambient noise at a suspiciously tiny
fraction (<0.4%) of full scale, whereas 114/2048 (~5.6%) is an ordinary
ambient noise floor at this gain, matching the libiio path's own convention
for the identical hardware. Kept as this module's OWN constant (not imported
from ``antsdr_iio_device``): it is a UHD-fork-specific measurement, not
something this module should silently inherit if the libiio path's constant
ever changes for unrelated reasons.

Loss accounting: this UHD fork DOES report overflow as an explicit RX
metadata error code (unlike the libiio path, which has no such counter --
see antsdr_iio.py). ``recv_chunk`` turns that into an EXACT lost-sample count
by comparing the ``time_spec`` of the last good packet before an overflow
against the first good packet after it (never an inferred rate) -- see
``recv_chunk``'s docstring. This is why the ANTSDR/UHD backend's
``loss_detection`` is unconditionally ``"device_reported"``, unlike the
libiio backend's ``"inferred_rate_only"``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import numpy as np

from .capture import GainStage, ReceiverCapabilities

log = logging.getLogger("aerix.rf.sdr.uhd_device")

DEFAULT_ADDR = "addr=192.168.1.10"
DEFAULT_SAMPLE_RATE = 15.36e6          # canonical uhd-antsdr-fork rate; no resampling needed
DEFAULT_BANDWIDTH_HZ = 12.0e6
DEFAULT_GAIN_DB = 40.0
DEFAULT_ANTENNA = "RX2"
DEFAULT_CHANNEL = 0

# AD9361's own advertised rate range and this backend's documented tuning
# range (architect/task-specified; see registry.py's antsdr_uhd_proc entry).
SAMPLE_RATE_RANGE_HZ = (2.083e6, 61.44e6)
TUNING_RANGE_HZ = (50e6, 6e9)
GAIN_RANGE_DB = (0.0, 76.0)

IQ_FULL_SCALE = 2048.0  # see module docstring measurement

_IMPORT_HINT = (
    "uhd python bindings not importable in this interpreter. This backend needs the "
    "MicroPhase uhd-antsdr fork's python (see ~/rf-tools/uhd-antsdr/ENV.sh, "
    "$UHD_ANTSDR_PYTHON) -- set $AERIX_RF_UHD_PYTHON to that interpreter's path so the "
    "acquisition producer subprocess is spawned with it, not this process's own interpreter."
)


def _load_uhd():
    """Lazy ``import uhd``; never a hard dependency of this module or the registry."""
    try:
        import uhd
    except Exception as exc:  # noqa: BLE001
        raise ImportError(_IMPORT_HINT) from exc
    return uhd


def antsdr_uhd_capabilities() -> ReceiverCapabilities:
    """Static capabilities for the ``antsdr_uhd_proc`` registry backend (T8).

    ``receiver_type="antsdr"`` (not "uhd"): this is the SAME physical
    ANTSDR E200/AD9361 box as "antsdr_iio"/"antsdr_proc", just read through a
    different host library -- see ``antsdr_iio_capabilities()`` for the same
    convention on that backend. ``channel_count=2`` documents the AD9361's
    second RX chain as a HARDWARE capability even though
    ``UhdDevice``/``DEFAULT_CHANNEL`` only opens channel 0 today.
    ``timestamp_quality="device_counter"``/``loss_counter_available=True``
    are the two facts this backend can claim that the libiio path honestly
    cannot: a real device ``time_spec`` and an explicit
    ``ERROR_CODE_OVERFLOW`` (see this module's docstring and ``recv_chunk``).
    """
    return ReceiverCapabilities(
        receiver_type="antsdr",
        backend="antsdr_uhd_proc",
        tuning_range_hz=TUNING_RANGE_HZ,
        sample_rates_hz=SAMPLE_RATE_RANGE_HZ,
        sample_rate_is_range=True,
        max_instantaneous_bw_hz=DEFAULT_BANDWIDTH_HZ,
        channel_count=2,
        gain_stages=(GainStage("rx", GAIN_RANGE_DB[0], GAIN_RANGE_DB[1], None),),
        gain_modes=("manual",),
        native_iq_format="cs16",
        native_full_scale=IQ_FULL_SCALE,
        supports_device_timestamps=True,
        supports_drop_reporting=True,
        supports_sweep=False,
        reference_inputs=("none",),
        timestamp_quality="device_counter",
        loss_counter_available=True,
    )


class UhdDevice:
    """Device-only ANTSDR/UHD glue: open, configure, read back config, tune,
    assemble RX chunks, close. No producer/consumer thread and no complex64
    scaling -- callers own the hot loop; this class owns only calls into
    ``uhd``.
    """

    def __init__(self, *, addr: str | None = None, sample_rate: float = DEFAULT_SAMPLE_RATE,
                 center_freq_hz: float = 2440e6, gain_db: float = DEFAULT_GAIN_DB,
                 bandwidth_hz: float | None = DEFAULT_BANDWIDTH_HZ,
                 antenna: str = DEFAULT_ANTENNA, channel: int = DEFAULT_CHANNEL) -> None:
        self._uhd = _load_uhd()
        self.addr = addr or os.environ.get("AERIX_RF_UHD_ADDR", DEFAULT_ADDR)
        self.sample_rate = float(sample_rate)
        self._center_hz = float(center_freq_hz)
        self.gain_db = float(gain_db)
        self.bandwidth_hz = float(bandwidth_hz) if bandwidth_hz else None
        self.antenna = str(antenna)
        self.channel = int(channel)

        self.device_overflows = 0
        self.readback: dict[str, Any] = {}
        # Set by recv_chunk(); consumed by producer_main's UhdProducerSource.
        self.last_device_time_ns: Optional[int] = None
        self.last_gap_samples: int = 0

        self._stream_started = False
        self._last_end_time_s: Optional[float] = None
        self._overflow_pending = False
        self._leftover: Optional[np.ndarray] = None  # int16 pairs held across recv_chunk() calls

        self.usrp = self._uhd.usrp.MultiUSRP(self.addr)
        self.usrp.set_rx_rate(self.sample_rate, self.channel)
        self.usrp.set_rx_freq(self._uhd.libpyuhd.types.tune_request(self._center_hz), self.channel)
        self.usrp.set_rx_gain(self.gain_db, self.channel)
        self.usrp.set_rx_antenna(self.antenna, self.channel)

        self._bw_supported = False
        if self.bandwidth_hz:
            try:
                self.usrp.set_rx_bandwidth(self.bandwidth_hz, self.channel)
                self._bw_supported = True
            except Exception as exc:  # noqa: BLE001 -- not every fork/daughterboard supports this
                log.warning("set_rx_bandwidth(%.4g Hz) not supported on this device: %s",
                            self.bandwidth_hz, exc)

        stream_args = self._uhd.usrp.StreamArgs("sc16", "sc16")
        stream_args.channels = [self.channel]
        self._rx = self.usrp.get_rx_stream(stream_args)
        self.max_num_samps = int(self._rx.get_max_num_samps())
        self._pkt_buf = np.zeros((1, self.max_num_samps), dtype=np.int32)
        self._md = self._uhd.types.RXMetadata()

        self._refresh_readback()

    @property
    def center_freq_hz(self) -> float:
        return self._center_hz

    # --- device configuration -------------------------------------------------
    def _refresh_readback(self) -> dict[str, Any]:
        rb: dict[str, Any] = {
            "source": "uhd",
            "loss_detection": "device_reported",
            "sample_rate_hz": self.usrp.get_rx_rate(self.channel),
            "center_freq_hz": self.usrp.get_rx_freq(self.channel),
            "gain_db": self.usrp.get_rx_gain(self.channel),
            "antenna": self.usrp.get_rx_antenna(self.channel),
            "bandwidth_hz": (self.usrp.get_rx_bandwidth(self.channel) if self._bw_supported else None),
            "mboard_name": self.usrp.get_mboard_name(self.channel),
            "time_source": self.usrp.get_time_source(self.channel),
            "clock_source": self.usrp.get_clock_source(self.channel),
            "has_time_spec": self._md.has_time_spec if self._md is not None else None,
            "device_overflows": self.device_overflows,
        }
        try:
            info = self.usrp.get_usrp_rx_info(self.channel)
            rb["mboard_serial"] = info.get("mboard_serial")
        except Exception:  # noqa: BLE001 -- best-effort only
            rb["mboard_serial"] = None
        self.readback = rb
        return rb

    def tune(self, center_freq_hz: float) -> dict[str, Any]:
        """Set the RX LO (RETUNE) and refresh the readback dict. A retune
        breaks time_spec continuity on purpose (the caller flushes its
        assembler on the RETUNE flag -- see producer_main.py), so this resets
        the last-good-packet time tracker rather than let the next packet
        look like a spurious overflow-sized gap."""
        self._center_hz = float(center_freq_hz)
        self.usrp.set_rx_freq(self._uhd.libpyuhd.types.tune_request(self._center_hz), self.channel)
        self._last_end_time_s = None
        self._overflow_pending = False
        return self._refresh_readback()

    # --- RX stream -----------------------------------------------------------
    def start(self) -> None:
        cmd = self._uhd.types.StreamCMD(self._uhd.types.StreamMode.start_cont)
        cmd.stream_now = True
        self._rx.issue_stream_cmd(cmd)
        self._stream_started = True

    def recv_chunk(self, n_samples: int, timeout: float = 1.0) -> np.ndarray:
        """Assemble ``n_samples`` of interleaved int16 I/Q by looping
        MTU-sized ``rx.recv()`` packets (UHD's own max packet size, not
        ``n_samples`` -- ``self.max_num_samps`` is typically far smaller).

        Sets, as a side effect (consumed by ``producer_main.UhdProducerSource``):
          * ``self.last_device_time_ns`` -- the device ``time_spec`` of the
            FIRST sample in the returned chunk, converted to ns (``None`` if
            this fork never reported ``has_time_spec`` for any packet in it).
          * ``self.last_gap_samples`` -- samples lost to a UHD-reported
            ``ERROR_CODE_OVERFLOW`` immediately before this chunk, computed
            EXACTLY as ``round((t_good_after - t_expected_after) * sample_rate)``
            where ``t_expected_after`` is the last good packet's own
            ``time_spec + n/sample_rate`` -- never inferred from a rate ratio.
            0 when no overflow happened.

        No data is discarded at a packet boundary that doesn't land exactly
        on ``n_samples``: the unused tail of a packet is kept in
        ``self._leftover`` and drained first on the next call.
        """
        if not self._stream_started:
            self.start()
        ErrCode = self._uhd.types.RXMetadataErrorCode
        out = np.empty(n_samples * 2, dtype=np.int16)
        filled = 0
        chunk_device_time_ns: Optional[int] = None
        gap_samples = 0

        if self._leftover is not None and self._leftover.size:
            take = min(self._leftover.size // 2, n_samples)
            out[: take * 2] = self._leftover[: take * 2]
            filled += take
            self._leftover = self._leftover[take * 2:] if take * 2 < self._leftover.size else None

        while filled < n_samples:
            k = self._rx.recv(self._pkt_buf, self._md, timeout)
            err = self._md.error_code
            if err == ErrCode.overflow:
                self.device_overflows += 1
                self._overflow_pending = True
                continue
            if err != ErrCode.none or k == 0:
                # Timeout/late/other transient error: no data this iteration,
                # not treated as an overflow (no exact gap can be attributed).
                continue

            pkt = self._pkt_buf[0, :k].view(np.int16).copy()
            if self._md.has_time_spec:
                t = self._md.time_spec.get_real_secs()
                if self._overflow_pending and self._last_end_time_s is not None:
                    gap_s = t - self._last_end_time_s
                    if gap_s > 0:
                        gap_samples += int(round(gap_s * self.sample_rate))
                self._overflow_pending = False
                if chunk_device_time_ns is None:
                    chunk_device_time_ns = int(round(t * 1e9))
                self._last_end_time_s = t + k / self.sample_rate

            take = min(k, n_samples - filled)
            out[filled * 2:(filled + take) * 2] = pkt[: take * 2]
            filled += take
            if take < k:
                self._leftover = pkt[take * 2:]

        self.last_device_time_ns = chunk_device_time_ns
        self.last_gap_samples = gap_samples
        return out

    def close(self) -> None:
        if self._stream_started and getattr(self, "_rx", None) is not None:
            try:
                self._rx.issue_stream_cmd(self._uhd.types.StreamCMD(self._uhd.types.StreamMode.stop_cont))
            except Exception:  # noqa: BLE001 -- best-effort device teardown
                pass
        self._rx = None
        self.usrp = None
