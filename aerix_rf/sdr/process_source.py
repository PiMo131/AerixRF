"""``IQSource`` backed by an acquisition producer running as a separate OS
process (T7b). See docs/design/antsdr-backend.md, "T7 -- acquisition producer
as a separate OS process".

This module owns the CONSUMER side of the T7 split: it spawns
``producer_main`` as a real subprocess, creates and owns the shared-memory
ring (``shmring.ShmRing``) the producer publishes into, talks the control
protocol (``tune``/``get_readback``/``stop``/``ping``), and runs a reader
thread that turns ring chunks into :class:`~aerix_rf.sdr.stream.StreamAssembler`
pushes -- exactly like ``AntsdrIIOSource``/``LibHackRFSource``'s producer
threads, except the "producer" here is a whole OS process instead of a
thread, and raw int16 -> complex64 conversion happens here (the consumer),
never in the producer.

Two independent loss vocabularies stay separate, on purpose (see the design
doc): ``loss_detection`` is the DEVICE-side signal (whatever the producer's
readback reports -- ``"n/a"`` for the synthetic source, since it has no
device to silently lose samples against); ``host_loss_detection`` is always
``"exact_ring"`` here, because every host-side loss this module can observe
-- a ring overrun (:class:`~aerix_rf.sdr.shmring.ShmRing` lapping the reader)
or a producer-declared chunk drop (a `sample_index` discontinuity with no
ring overrun at all, e.g. ``--drop-chunk`` fault injection) -- is an exact
count, never an inferred rate.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Iterator, Optional

import numpy as np

from .capture import IQSource, IQWindow, ReceiverCapabilities
from .producer_main import EXIT_DEVICE_LOST, recv_json_line, send_json_line
from .shmring import FLAG_RETUNE, ShmRing, sweep_stale_rings
from .stream import StreamAssembler

log = logging.getLogger("aerix.rf.sdr.process_source")

DEFAULT_SLOTS = 8
DEFAULT_CHUNK_SAMPLES = 65536
DEFAULT_FULL_SCALE = 2048.0
RING_PREFIX = "aerix-ring-"


class ControlChannelError(RuntimeError):
    """The control socket to the producer broke or timed out."""


class ProducerLostError(RuntimeError):
    """Raised by :meth:`ProcessIQSource.windows` when the producer process
    exited unexpectedly (not via our own ``close()``)."""


def _raw_to_iq(raw: np.ndarray, full_scale: float) -> np.ndarray:
    raw = raw.astype(np.float32)
    iq = raw[0::2] + 1j * raw[1::2]
    return (iq / full_scale).astype(np.complex64)


class ControlClient:
    """Request/reply JSON-line client for the producer's control socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._rfile = sock.makefile("r")
        self._wfile = sock.makefile("w")
        self._lock = threading.Lock()

    def request(self, op: str, timeout: float = 3.0, **kwargs: Any) -> dict:
        obj = {"op": op}
        obj.update(kwargs)
        with self._lock:
            self._sock.settimeout(timeout)
            try:
                send_json_line(self._wfile, obj)
                resp = recv_json_line(self._rfile)
            except OSError as exc:
                raise ControlChannelError(f"control channel error during {op!r}: {exc}") from exc
            finally:
                try:
                    self._sock.settimeout(None)
                except OSError:
                    pass
        if resp is None:
            raise ControlChannelError(f"control channel closed while waiting for {op!r} reply")
        return resp

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def process_capabilities(source_type: str, *, full_scale: float,
                          sample_rate: float) -> ReceiverCapabilities:
    return ReceiverCapabilities(
        receiver_type=f"process:{source_type}",
        # "antsdr_proc" is the registry backend name (registry.py) for the
        # "antsdr_iio" producer path, so a live ``ProcessIQSource`` instance's
        # own ``.capabilities.backend`` -- what ``cli._receiver_meta`` records
        # into session.json's ``receiver_backend`` -- names the actually
        # selected backend, not this module's generic plumbing name. Every
        # other source_type (only "synthetic" today, T7b) keeps that generic
        # name: it has no registry entry of its own to name-match.
        backend="antsdr_proc" if source_type == "antsdr_iio" else "process_source",
        tuning_range_hz=(0.0, 1e10),
        sample_rates_hz=(1e3, 1e8),
        sample_rate_is_range=True,
        max_instantaneous_bw_hz=sample_rate,
        channel_count=1,
        native_iq_format="cs16",
        native_full_scale=full_scale,
        supports_device_timestamps=False,
        supports_drop_reporting=True,
        timestamp_quality="host_wallclock",
        # The ring's overrun/producer-drop accounting is exact by construction
        # (seqlock-derived, or an explicit sample_index gap) -- see the module
        # docstring's `host_loss_detection` note.
        loss_counter_available=True,
    )


class ProcessIQSource(IQSource):
    """Continuous IQ stream from a producer running as its own OS process.

    Today only ``source_type="synthetic"`` is implemented end to end (no
    hardware); ``source_type="antsdr_iio"`` spawns the same producer, which
    immediately reports ``NotImplementedError("T7c")`` and exits -- surfaced
    here as an ordinary startup failure, not a special case in this class.
    """

    receiver_type = "process"

    def __init__(self, *, source_type: str = "synthetic", sample_rate: float,
                 center_freq_hz: float, chunk_samples: int = DEFAULT_CHUNK_SAMPLES,
                 slots: int = DEFAULT_SLOTS, full_scale: float = DEFAULT_FULL_SCALE,
                 window_seconds: float = 1.0, extra_args: Optional[list] = None,
                 start_timeout: float = 5.0) -> None:
        self.receiver_type = f"process:{source_type}"
        self._source_type = source_type
        self.sample_rate = float(sample_rate)
        self._center_hz = float(center_freq_hz)
        self.chunk_samples = int(chunk_samples)
        self.full_scale = float(full_scale)
        self.window_seconds = float(window_seconds)

        removed = sweep_stale_rings(RING_PREFIX)
        if removed:
            log.info("swept %d stale ring(s) at startup: %s", len(removed), removed)

        self._ring = ShmRing.create(
            slots=slots, slot_samples=self.chunk_samples, sample_rate=self.sample_rate,
            iq_format="cs16", full_scale=self.full_scale,
        )
        self._owns_ring = True
        self._proc: Optional[subprocess.Popen] = None
        self._ctrl: Optional[ControlClient] = None

        try:
            parent_sock, child_sock = socket.socketpair()
            argv = [
                sys.executable, "-m", "aerix_rf.sdr.producer_main",
                "--ring", self._ring.name,
                "--source", source_type,
                "--rate", repr(self.sample_rate),
                "--center", repr(self._center_hz),
                "--chunk-samples", str(self.chunk_samples),
                "--control-fd", str(child_sock.fileno()),
            ]
            if extra_args:
                argv += [str(a) for a in extra_args]

            self._proc = subprocess.Popen(argv, pass_fds=(child_sock.fileno(),))
            child_sock.close()
            self._ctrl = ControlClient(parent_sock)

            deadline = time.monotonic() + start_timeout
            while True:
                if self._proc.poll() is not None:
                    raise RuntimeError(
                        f"producer process exited during startup (code {self._proc.returncode})"
                    )
                if self._ring.producer_alive(timeout=start_timeout):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("producer process did not become alive within start_timeout")
                time.sleep(0.02)
        except Exception:
            self._cleanup(unlink=True)
            raise

        self._asm = StreamAssembler(
            self.sample_rate, raw_to_iq=lambda raw: _raw_to_iq(raw, self.full_scale),
            reports_drops=True, chunk_samples_hint=self.chunk_samples,
            still_active=lambda: self._running, raw_full_scale=self.full_scale,
        )

        self._running = True
        self._stopping = False
        self._closed = False
        self._producer_lost = False
        self._host_dropped_total = 0
        self._host_overrun_events_total = 0
        self._last_sample_index_end: Optional[int] = None
        self._meta_epoch_seen = -1
        self._readback: dict = {}
        self._readback_lock = threading.Lock()

        # Fetch the producer's readback synchronously, once, right here --
        # before the reader thread (and therefore before the first window)
        # exists -- instead of relying solely on the reader thread's
        # epoch-triggered refresh (_read_loop). That refresh only fires once
        # a ring chunk with a *new* meta_epoch has actually been read, so
        # without this call every window up to that point (including
        # possibly the first one written to a session) would carry an empty
        # ``readback`` dict, and Session.write_iq's "record the FIRST
        # window's readback" logic would capture that empty snapshot instead
        # of the real one. By the time producer_alive() above returned True,
        # the producer has already opened its device and merged the real
        # readback into its state (see producer_main.run(): readback merge
        # happens before ring.heartbeat(STATE_RUNNING)), so this is not a
        # race against producer startup -- only against our own reader
        # thread's first observed epoch, which this pre-empts.
        self._fetch_readback(0)

        self._reader_thread = threading.Thread(
            target=self._read_loop, name="process-source-reader", daemon=True,
        )
        self._reader_thread.start()

    # --- IQSource contract -----------------------------------------------
    @property
    def stream_end_reason(self) -> str:
        """Best-effort classification of why the stream ended, meant to be
        passed through to ``Session.finalize(extra={"stream_end_reason": ...})``:

          * ``"device_lost"``  -- the producer hit a hardware-specific
            unrecoverable error (exited with ``EXIT_DEVICE_LOST``, e.g. an
            ANTSDR ``refill()``/libiio-side failure -- see
            ``AntsdrIioProducerSource`` in ``producer_main.py``).
          * ``"producer_lost"`` -- the producer exited/died for any other
            reason before :meth:`close` was called.
          * ``"user_stop"``    -- :meth:`close` was called while the producer
            was still running (a normal, caller-initiated stop).
          * ``"completed"``    -- neither of the above: the producer is gone
            but this source was already stopping/stopped cleanly (exit 0),
            or the caller hasn't stopped anything unusual has happened yet.
        """
        if self._producer_lost:
            code = self._proc.poll() if self._proc is not None else None
            if code == EXIT_DEVICE_LOST:
                return "device_lost"
            return "producer_lost"
        if self._stopping:
            return "user_stop"
        return "completed"

    @property
    def capabilities(self) -> ReceiverCapabilities:
        return process_capabilities(
            self._source_type, full_scale=self.full_scale, sample_rate=self.sample_rate,
        )

    def tune(self, center_freq_hz: float) -> None:
        self._center_hz = float(center_freq_hz)
        self._ctrl.request("tune", center_freq_hz=self._center_hz)

    def windows(self) -> Iterator[IQWindow]:
        n = int(self.sample_rate * self.window_seconds)
        while True:
            win = self._asm.read_window(n)
            if win is None:
                if self._producer_lost:
                    code = self._proc.poll() if self._proc is not None else None
                    raise ProducerLostError(
                        f"acquisition producer process exited unexpectedly (exit code {code})"
                    )
                return
            iq, info = win
            with self._readback_lock:
                readback = dict(self._readback)
            yield IQWindow(
                iq=iq, captured_at=info["captured_at"], sample_rate=self.sample_rate,
                center_freq_hz=info["center_freq_hz"], receiver_type=self.receiver_type,
                complete=info["complete"], expected_samples=n,
                dropped_samples=info["dropped_samples"],
                bandwidth_hz=info.get("bandwidth_hz"),
                channel_id=int(info.get("channel_id", 0)),
                timing=dict(info.get("timing") or {}),
                metadata={
                    "backend": "process_source",
                    "source_type": self._source_type,
                    "iq_format": "cs16",
                    "iq_full_scale": self.full_scale,
                    "loss_detection": readback.get("loss_detection"),
                    "host_loss_detection": "exact_ring",
                    "host_dropped_samples": int(self._host_dropped_total),
                    "host_overrun_events": int(self._host_overrun_events_total),
                    "overflow_count": info["overflow_count"],
                    "gap_before_samples": info.get("gap_before_samples", 0),
                    "short_reads": info["short_reads"],
                    "stream_rate_ratio": info["stream_rate_ratio"],
                    "stream_rate_ratio_recent": info.get("stream_rate_ratio_recent"),
                    "stream_rate_elapsed_s": info.get("stream_rate_elapsed_s"),
                    "samples_deficit": info.get("samples_deficit"),
                    "samples_deficit_recent": info.get("samples_deficit_recent"),
                    "clip_fraction": info.get("clip_fraction"),
                    "peak_abs_frac": info.get("peak_abs_frac"),
                    "clip_warning": info.get("clip_warning", False),
                    "producer_pid": self._proc.pid if self._proc is not None else None,
                    "readback": readback,
                },
            )

    def close(self) -> None:
        """Idempotent teardown: send ``stop``, join the reader, then -- in a
        ``finally`` -- always terminate/SIGKILL the producer and unlink the
        ring, even if the control request or the reader join raised. Without
        this ``finally``, an unexpected exception here (e.g. a control-socket
        error that isn't a plain ``ControlChannelError``) would skip
        ``_cleanup()`` entirely and leave the producer subprocess running as
        an orphan holding the ring open (see live-capture evidence, T7c
        fix)."""
        if self._closed:
            return
        self._closed = True
        self._stopping = True
        try:
            if self._ctrl is not None:
                try:
                    self._ctrl.request("stop", timeout=1.0)
                except ControlChannelError:
                    pass
            self._running = False
            if hasattr(self, "_asm"):
                self._asm.mark_stopped()
            reader = getattr(self, "_reader_thread", None)
            if reader is not None:
                reader.join(timeout=2.0)
        finally:
            self._cleanup(unlink=True)

    # --- internals ---------------------------------------------------------
    def _fetch_readback(self, epoch: int) -> None:
        if self._ctrl is None:
            return
        try:
            resp = self._ctrl.request("get_readback", epoch=epoch)
        except ControlChannelError as exc:
            log.warning("readback fetch (epoch=%s) failed: %s", epoch, exc)
            return
        if resp.get("ok"):
            with self._readback_lock:
                self._readback = dict(resp.get("readback") or {})
        else:
            log.warning("readback fetch (epoch=%s) rejected by producer: %r", epoch, resp)

    def _read_loop(self) -> None:
        try:
            while not self._stopping:
                res = self._ring.read_next()
                if res is None:
                    if self._proc is not None and self._proc.poll() is not None and not self._stopping:
                        self._producer_lost = True
                        break
                    time.sleep(0.002)
                    continue

                header = res.header
                if header.meta_epoch != self._meta_epoch_seen:
                    self._meta_epoch_seen = header.meta_epoch
                    self._fetch_readback(header.meta_epoch)

                producer_gap = 0
                if self._last_sample_index_end is not None:
                    gap = header.sample_index - self._last_sample_index_end
                    if gap > 0:
                        producer_gap = gap
                self._last_sample_index_end = header.sample_index + header.n_samples

                dropped_before = res.host_dropped_samples + producer_gap
                self._host_dropped_total += dropped_before
                self._host_overrun_events_total += res.host_overrun_events

                if header.flags & FLAG_RETUNE:
                    self._asm.flush()

                raw_flat = res.data.reshape(-1)
                raw_stats = (header.clip_count, header.peak_abs, header.n_samples)
                ts = header.t_wall_ns / 1e9
                self._asm.push(
                    raw_flat, ts, header.center_freq_hz,
                    dropped_before=dropped_before, raw_stats=raw_stats,
                )
        finally:
            self._running = False
            if hasattr(self, "_asm"):
                self._asm.mark_stopped()

    def _terminate_process(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.wait(timeout=2.0)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2.0)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            self._proc.kill()
            self._proc.wait(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass

    def _cleanup(self, *, unlink: bool) -> None:
        try:
            self._terminate_process()
        except Exception:  # noqa: BLE001
            pass
        if self._ctrl is not None:
            self._ctrl.close()
        try:
            self._ring.close()
        except Exception:  # noqa: BLE001
            pass
        if unlink and self._owns_ring:
            try:
                self._ring.unlink()
            except Exception:  # noqa: BLE001
                pass
