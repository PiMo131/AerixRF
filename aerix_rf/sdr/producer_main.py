"""AERIX RF acquisition producer entrypoint -- a separate OS process (T7b).

Run as ``python -m aerix_rf.sdr.producer_main --ring NAME --source ... ...``.
See docs/design/antsdr-backend.md, section "T7 -- acquisition producer as a
separate OS process". This process does ONLY device (or synthetic) reads,
``raw_clip_stats`` on the raw ints, and a ring write -- no complex64
conversion, no DSP (that stays in the consumer, see ``process_source.py``).

Two IPC channels to the parent (consumer) process, both created BEFORE this
process starts (by ``ProcessIQSource``):
  * the shared-memory ring (``shmring.ShmRing``, attached by name);
  * a control socketpair, inherited as an already-open fd (``--control-fd``),
    carrying newline-delimited JSON requests/replies (``tune``, ``set_params``,
    ``get_readback``, ``stop``, ``ping``).

``--source antsdr_iio`` (T7c-1b) opens a real ANTSDR E200 / AD9361 device via
``antsdr_iio_device.AntsdrIioDevice`` and adapts its blocking
refill/read/tune/readback calls to this module's ``read_chunk(index)`` shape
(see ``AntsdrIioProducerSource`` below) -- no synthetic wall-clock pacing:
the device paces itself, so the main loop's schedule-based wait is skipped
for this source. ``--fake-iio`` installs a hardware-free fake ``iio`` module
(``_fake_iio.build_fake_iio``) into ``sys.modules`` before the device opens,
so the whole antsdr_iio producer path can run end to end with no hardware
(used by the T7c-1b test suite via ``ProcessIQSource``). ``--source
synthetic`` drives ``SyntheticSource``, a deterministic tone generator with
fault-injection hooks (``--stall-after``/``--die-after``/``--drop-chunk``)
used by the T7b test suite to exercise the ring's exact loss accounting and
the consumer's producer-death handling without any hardware.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
from typing import Any, Optional

import numpy as np

from .shmring import FLAG_RETUNE, STATE_ERROR, STATE_RUNNING, STATE_STOPPED, ShmRing
from .stream import raw_clip_stats

log = logging.getLogger("aerix.rf.sdr.producer_main")

_MAX_WAIT_SLICE_S = 0.05   # cap on any single sleep so `stop` is noticed promptly

# Exit codes the consumer (ProcessIQSource.stream_end_reason) maps to a
# stream_end_reason. 0 is a clean stop (the consumer asked for it, or the
# source ran out on its own with no error); everything else is a producer
# failure of some kind. EXIT_DEVICE_LOST is deliberately distinct from every
# other failure code so the consumer can tell "the device itself broke"
# (e.g. an ANTSDR refill()/libiio-side error) apart from a generic producer
# crash -- see AntsdrIioProducerSource.read_chunk / DeviceLostError below.
EXIT_OK = 0
EXIT_SOURCE_INIT_FAILED = 1
EXIT_MAIN_LOOP_ERROR = 3
EXIT_DEVICE_LOST = 4


# --- tiny newline-delimited JSON helpers, shared with the consumer side ------

def send_json_line(wfile: Any, obj: dict) -> None:
    wfile.write(json.dumps(obj))
    wfile.write("\n")
    wfile.flush()


def recv_json_line(rfile: Any) -> Optional[dict]:
    line = rfile.readline()
    if not line:
        return None  # EOF: peer closed the control channel
    line = line.strip()
    if not line:
        return None
    return json.loads(line)


# --- synthetic source with fault injection -----------------------------------

class SyntheticSource:
    """Deterministic tone generator, no hardware.

    ``read_chunk(index)`` returns interleaved int16 I/Q for chunk ``index``,
    or ``None`` if this chunk is being deliberately dropped
    (``--drop-chunk``). ``--die-after`` calls ``os._exit`` unconditionally
    (simulates an abrupt crash: no cleanup, no final heartbeat -- exactly
    what a killed process looks like to the consumer). ``--stall-after``
    sleeps 0.5 s exactly once.
    """

    def __init__(self, *, sample_rate: float, chunk_samples: int,
                 center_freq_hz: float, stall_after: Optional[int] = None,
                 die_after: Optional[int] = None, drop_chunk: Optional[int] = None,
                 amplitude: float = 1500.0) -> None:
        self.sample_rate = float(sample_rate)
        self.chunk_samples = int(chunk_samples)
        self.center_freq_hz = float(center_freq_hz)
        self.stall_after = stall_after
        self.die_after = die_after
        self.drop_chunk = drop_chunk
        self.amplitude = float(amplitude)
        self._stalled = False

    def read_chunk(self, index: int) -> Optional[np.ndarray]:
        if self.die_after is not None and index == self.die_after:
            sys.stderr.write(f"producer: injected die-after at chunk {index}\n")
            sys.stderr.flush()
            os._exit(1)  # noqa: SLF001 -- deliberate: simulate a hard kill, no cleanup
        if self.stall_after is not None and index == self.stall_after and not self._stalled:
            self._stalled = True
            time.sleep(0.5)
        if self.drop_chunk is not None and index == self.drop_chunk:
            return None
        n = self.chunk_samples
        t = (np.arange(n, dtype=np.float64) + index * n) / self.sample_rate
        tone_hz = self.sample_rate / 8.0
        i = np.round(self.amplitude * np.cos(2 * np.pi * tone_hz * t)).astype(np.int16)
        q = np.round(self.amplitude * np.sin(2 * np.pi * tone_hz * t)).astype(np.int16)
        raw = np.empty(n * 2, dtype=np.int16)
        raw[0::2] = i
        raw[1::2] = q
        return raw


class DeviceLostError(RuntimeError):
    """Raised by :meth:`AntsdrIioProducerSource.read_chunk` when the ANTSDR
    device's own ``refill()``/``read()`` fails mid-stream (a real libiio-side
    error, not a Python bug in this module) -- the caller (``run()``) treats
    this as unrecoverable and exits with :data:`EXIT_DEVICE_LOST`."""


class AntsdrIioProducerSource:
    """Adapts :class:`~aerix_rf.sdr.antsdr_iio_device.AntsdrIioDevice`'s
    blocking refill/read/tune/readback calls to this module's
    ``read_chunk(index)`` shape.

    Unlike ``SyntheticSource``, this source is device-paced, not wall-clock
    scheduled: ``refill_read()`` already blocks until the device has a full
    buffer ready, so ``run()`` skips its schedule-based ``_wait_until`` for
    this source (a fixed wall-clock schedule built for the synthetic
    generator would otherwise throttle a real device to that schedule's
    cadence instead of the device's own pace).
    """

    def __init__(self, device: "AntsdrIioDevice") -> None:  # noqa: F821 -- see import below
        self.device = device
        self.center_freq_hz = device.center_freq_hz
        self.sample_rate = device.sample_rate
        self.device.open_buffer()

    def read_chunk(self, index: int) -> np.ndarray:  # noqa: ARG002 -- index unused, device-paced
        try:
            data = self.device.refill_read()
        except Exception as exc:  # noqa: BLE001 -- any iio-side failure means the device is lost
            raise DeviceLostError(str(exc)) from exc
        return np.frombuffer(data, dtype="<i2")

    def readback(self) -> dict:
        """Current device config readback, tagged with this backend's fixed
        ``loss_detection`` (see antsdr_iio.py module docstring: this firmware
        has no overflow/sequence counter, so it is unconditionally
        ``"inferred_rate_only"``, never an exact count)."""
        rb = dict(self.device.readback)
        rb["loss_detection"] = "inferred_rate_only"
        rb["source"] = "antsdr_iio"
        return rb

    def tune(self, center_freq_hz: float) -> dict:
        """Set the LO on the device and return the refreshed readback (same
        ``loss_detection``/``source`` tagging as :meth:`readback`)."""
        self.device.tune(center_freq_hz)
        self.center_freq_hz = center_freq_hz
        return self.readback()

    def close(self) -> None:
        self.device.close()


def build_source(args: argparse.Namespace):
    if args.source == "synthetic":
        return SyntheticSource(
            sample_rate=args.rate, chunk_samples=args.chunk_samples,
            center_freq_hz=args.center, stall_after=args.stall_after,
            die_after=args.die_after, drop_chunk=args.drop_chunk,
        )
    if args.source == "antsdr_iio":
        from .antsdr_iio_device import AntsdrIioDevice

        if getattr(args, "fake_iio", False):
            from ._fake_iio import build_fake_iio
            sys.modules["iio"] = build_fake_iio(die_after=args.fake_iio_die_after)
        device = AntsdrIioDevice(
            sample_rate=args.rate, center_freq_hz=args.center,
            gain_mode="manual", gain_db=40.0, buffer_samples=args.chunk_samples,
        )
        return AntsdrIioProducerSource(device)
    raise ValueError(f"unknown --source {args.source!r}")


# --- control channel (producer side: replies only) ---------------------------

class ControlServer(threading.Thread):
    """Background thread answering control requests from the consumer.

    Mutates ``state`` (a plain dict guarded by ``state['lock']``) so the main
    loop can pick up ``tune``/``set_params``/``stop`` cheaply each iteration.
    """

    def __init__(self, sock: socket.socket, state: dict) -> None:
        super().__init__(name="producer-control", daemon=True)
        self._sock = sock
        self._state = state
        self._rfile = sock.makefile("r")
        self._wfile = sock.makefile("w")

    def run(self) -> None:
        try:
            while True:
                try:
                    req = recv_json_line(self._rfile)
                except ValueError:
                    self._reply({"ok": False, "error": "bad_json"})
                    continue
                except OSError:
                    break
                if req is None:
                    break  # EOF: consumer closed the control channel
                self._handle_request(req)
        except Exception:  # noqa: BLE001
            log.exception("producer control thread stopped unexpectedly")
        finally:
            self._state["stop"].set()

    def _reply(self, obj: dict) -> None:
        try:
            send_json_line(self._wfile, obj)
        except OSError:
            pass

    def _handle_request(self, req: dict) -> None:
        op = req.get("op")
        state = self._state
        if op == "tune":
            freq = float(req["center_freq_hz"])
            source = state.get("source")
            # A source with its own `.tune()` (AntsdrIioProducerSource) owns
            # setting the LO on real hardware and refreshing the device
            # readback; SyntheticSource has no such method, so this falls
            # back to the original behaviour (metadata-only, no hardware).
            tune_fn = getattr(source, "tune", None)
            rb_update = tune_fn(freq) if tune_fn is not None else None
            with state["lock"]:
                state["center_freq_hz"] = freq
                state["retune_pending"] = True
                state["meta_epoch"] += 1
                if rb_update is not None:
                    state["readback"].update(rb_update)
                else:
                    state["readback"]["center_freq_hz"] = freq
            self._reply({"ok": True})
        elif op == "set_params":
            with state["lock"]:
                for key in ("gain_db", "rf_bandwidth_hz", "sample_rate"):
                    if key in req:
                        state["readback"][key] = req[key]
                state["meta_epoch"] += 1
            self._reply({"ok": True})
        elif op == "get_readback":
            with state["lock"]:
                self._reply({"ok": True, "meta_epoch": state["meta_epoch"],
                              "readback": dict(state["readback"])})
        elif op == "ping":
            self._reply({"ok": True, "pong": True})
        elif op == "stop":
            state["stop"].set()
            self._reply({"ok": True})
        else:
            self._reply({"ok": False, "error": f"unknown op {op!r}"})


def _wait_until(due_mono: float, stop_evt: threading.Event) -> bool:
    """Sleep (in small slices) until ``due_mono``; return False if `stop_evt`
    fires first. A tight schedule kept as absolute times (not a per-chunk
    relative sleep) so a stall's catch-up is a genuine back-to-back write
    burst, not silently re-paced -- see ``--stall-after`` in the module
    docstring and docs/design/antsdr-backend.md T7's overrun test."""
    while True:
        remaining = due_mono - time.monotonic()
        if remaining <= 0:
            return True
        if stop_evt.is_set():
            return False
        time.sleep(min(remaining, _MAX_WAIT_SLICE_S))


def run(args: argparse.Namespace) -> int:
    ring = ShmRing.attach(args.ring)
    control_sock = socket.socket(fileno=args.control_fd)

    state = {
        "lock": threading.Lock(),
        "stop": threading.Event(),
        "center_freq_hz": float(args.center),
        "retune_pending": False,
        "meta_epoch": 0,
        "source": None,  # set below, once built; read by ControlServer's tune handler
        "readback": {
            "source": args.source,
            "loss_detection": "n/a",  # synthetic: no device to silently lose samples
            "center_freq_hz": float(args.center),
            "sample_rate": float(args.rate),
        },
    }
    ctrl = ControlServer(control_sock, state)
    ctrl.start()

    try:
        source = build_source(args)
    except NotImplementedError as exc:
        ring.mark_error(1)
        sys.stderr.write(f"producer: {exc}\n")
        return EXIT_SOURCE_INIT_FAILED
    except Exception as exc:  # noqa: BLE001
        ring.mark_error(2)
        sys.stderr.write(f"producer: source init failed: {exc}\n")
        return EXIT_SOURCE_INIT_FAILED

    # A device-backed source (AntsdrIioProducerSource) has its own real
    # readback (gain/mode/bandwidth/LO) once open -- merge it in now (and bump
    # meta_epoch so a consumer that already saw epoch 0 knows to re-fetch)
    # instead of leaving the synthetic-shaped placeholder readback in place.
    readback_fn = getattr(source, "readback", None)
    with state["lock"]:
        state["source"] = source
        if readback_fn is not None:
            state["readback"].update(readback_fn())
            state["meta_epoch"] += 1
    # Real hardware paces itself (refill_read() blocks until data is ready);
    # only the synthetic generator needs the wall-clock schedule below.
    device_paced = readback_fn is not None

    full_scale = ring.full_scale
    chunk_samples = args.chunk_samples
    chunk_duration = chunk_samples / args.rate
    start_mono = time.monotonic()
    next_sample_index = 0
    index = 0
    exit_code = 0
    ring.heartbeat(STATE_RUNNING)
    try:
        while not state["stop"].is_set():
            if device_paced:
                if state["stop"].is_set():
                    break
            else:
                due = start_mono + index * chunk_duration
                if not _wait_until(due, state["stop"]):
                    break
            try:
                raw = source.read_chunk(index)
            except DeviceLostError as exc:
                log.error("producer: ANTSDR device lost: %s", exc)
                ring.mark_error(4)
                sys.stderr.write(f"producer: device lost: {exc}\n")
                exit_code = EXIT_DEVICE_LOST
                break
            index += 1
            ring.heartbeat(STATE_RUNNING)
            if raw is None:
                # Dropped chunk: no slot written, but the sample counter still
                # advances so the gap is visible via `sample_index` even though
                # the ring's own seq sequence stays contiguous.
                next_sample_index += chunk_samples
                continue
            with state["lock"]:
                flags = FLAG_RETUNE if state["retune_pending"] else 0
                state["retune_pending"] = False
                center = state["center_freq_hz"]
                epoch = state["meta_epoch"]
            clip_count, peak_abs, _ = raw_clip_stats(raw, full_scale)
            ring.write_chunk(
                raw, sample_index=next_sample_index, flags=flags,
                center_freq_hz=center, clip_count=clip_count,
                peak_abs=float(peak_abs), meta_epoch=epoch,
            )
            next_sample_index += chunk_samples
    except Exception as exc:  # noqa: BLE001
        log.exception("producer main loop stopped unexpectedly")
        ring.mark_error(3)
        sys.stderr.write(f"producer: main loop error: {exc}\n")
        exit_code = EXIT_MAIN_LOOP_ERROR
    finally:
        ring.heartbeat(STATE_STOPPED if exit_code == 0 else STATE_ERROR)
        state["stop"].set()
        close_fn = getattr(source, "close", None)
        if close_fn is not None:
            try:
                close_fn()
            except Exception:  # noqa: BLE001 -- best-effort device teardown
                log.exception("producer: error closing source")
        try:
            control_sock.close()
        except OSError:
            pass
    return exit_code


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m aerix_rf.sdr.producer_main")
    p.add_argument("--ring", required=True)
    p.add_argument("--source", choices=("synthetic", "antsdr_iio"), default="synthetic")
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--center", type=float, required=True)
    p.add_argument("--chunk-samples", type=int, required=True)
    p.add_argument("--control-fd", type=int, required=True)
    p.add_argument("--stall-after", type=int, default=None)
    p.add_argument("--die-after", type=int, default=None)
    p.add_argument("--drop-chunk", type=int, default=None)
    p.add_argument("--fake-iio", action="store_true",
                   help="--source antsdr_iio only: install a hardware-free fake `iio` "
                        "module before opening the device (no ANTSDR needed; T7c-1b tests)")
    p.add_argument("--fake-iio-die-after", type=int, default=None,
                   help="--fake-iio only: the fake device's refill() raises on the Nth call "
                        "(0-indexed), simulating a real device-side failure mid-stream")
    return p.parse_args(argv)


def main() -> None:
    logging.basicConfig(level=os.environ.get("AERIX_RF_LOG_LEVEL", "WARNING"))
    args = parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
