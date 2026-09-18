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

``--source antsdr_iio`` is a placeholder for T7c: it raises
``NotImplementedError`` before any ring/device activity so this module never
touches ``antsdr_iio.py``. ``--source synthetic`` drives ``SyntheticSource``,
a deterministic tone generator with fault-injection hooks
(``--stall-after``/``--die-after``/``--drop-chunk``) used by the T7b test
suite to exercise the ring's exact loss accounting and the consumer's
producer-death handling without any hardware.
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


def build_source(args: argparse.Namespace):
    if args.source == "synthetic":
        return SyntheticSource(
            sample_rate=args.rate, chunk_samples=args.chunk_samples,
            center_freq_hz=args.center, stall_after=args.stall_after,
            die_after=args.die_after, drop_chunk=args.drop_chunk,
        )
    if args.source == "antsdr_iio":
        # T7c wires this up against the real device (antsdr_iio.py). Not here.
        raise NotImplementedError("T7c")
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
            with state["lock"]:
                state["center_freq_hz"] = float(req["center_freq_hz"])
                state["retune_pending"] = True
                state["meta_epoch"] += 1
                state["readback"]["center_freq_hz"] = state["center_freq_hz"]
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
        return 1
    except Exception as exc:  # noqa: BLE001
        ring.mark_error(2)
        sys.stderr.write(f"producer: source init failed: {exc}\n")
        return 1

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
            due = start_mono + index * chunk_duration
            if not _wait_until(due, state["stop"]):
                break
            raw = source.read_chunk(index)
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
        exit_code = 1
    finally:
        ring.heartbeat(STATE_STOPPED if exit_code == 0 else STATE_ERROR)
        state["stop"].set()
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
    return p.parse_args(argv)


def main() -> None:
    logging.basicConfig(level=os.environ.get("AERIX_RF_LOG_LEVEL", "WARNING"))
    args = parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
