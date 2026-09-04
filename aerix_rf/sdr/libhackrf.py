"""Minimal ctypes binding to libhackrf for continuous RX.

Why not SoapySDR: the box only needs one thing from the radio -- an uninterrupted
int8 IQ stream -- and ``libhackrf.so`` ships with the ``hackrf`` package that is
already required for ``hackrf_transfer`` / ``hackrf_sweep``. No extra install.

Design:
  * libhackrf calls ``_rx_callback`` from its USB thread with ~256 KiB buffers.
    The callback only copies the bytes into a bounded queue and returns; all
    conversion happens in the consumer thread (``read_window``).
  * If the consumer falls behind and the queue is full, the buffer is DROPPED and
    counted (``overflow_count``) -- the affected window is stamped incomplete with
    the number of lost samples rather than silently shortened or stitched.
  * Retuning while streaming is supported by libhackrf; ``tune()`` records the new
    centre and flushes buffered (old-frequency) data so the next window is clean.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import queue
import threading
import time

import numpy as np

log = logging.getLogger("aerix.rf.libhackrf")

HACKRF_SUCCESS = 0
_TRANSFER_BYTES = 262144          # libhackrf's default RX transfer size
_QUEUE_MAX_S = 2.0                # seconds of buffered stream before we start dropping


class _hackrf_transfer(ctypes.Structure):
    _fields_ = [
        ("device", ctypes.c_void_p),
        ("buffer", ctypes.POINTER(ctypes.c_uint8)),
        ("buffer_length", ctypes.c_int),
        ("valid_length", ctypes.c_int),
        ("rx_ctx", ctypes.c_void_p),
        ("tx_ctx", ctypes.c_void_p),
    ]


class _read_partid_serialno(ctypes.Structure):
    _fields_ = [("part_id", ctypes.c_uint32 * 2), ("serial_no", ctypes.c_uint32 * 4)]


_RX_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_hackrf_transfer))

_lib = None


def load_lib():
    """Load libhackrf once; raise a clear error when it is not installed."""
    global _lib
    if _lib is not None:
        return _lib
    name = ctypes.util.find_library("hackrf") or "libhackrf.so.0"
    try:
        lib = ctypes.CDLL(name)
    except OSError as exc:
        raise RuntimeError(f"libhackrf not found ({name}); install the `hackrf` package") from exc

    lib.hackrf_init.restype = ctypes.c_int
    lib.hackrf_exit.restype = ctypes.c_int
    lib.hackrf_open.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.hackrf_open.restype = ctypes.c_int
    lib.hackrf_close.argtypes = [ctypes.c_void_p]
    lib.hackrf_set_sample_rate.argtypes = [ctypes.c_void_p, ctypes.c_double]
    lib.hackrf_set_freq.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.hackrf_set_lna_gain.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.hackrf_set_vga_gain.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.hackrf_set_amp_enable.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
    lib.hackrf_start_rx.argtypes = [ctypes.c_void_p, _RX_CB, ctypes.c_void_p]
    lib.hackrf_stop_rx.argtypes = [ctypes.c_void_p]
    lib.hackrf_is_streaming.argtypes = [ctypes.c_void_p]
    lib.hackrf_is_streaming.restype = ctypes.c_int
    lib.hackrf_error_name.argtypes = [ctypes.c_int]
    lib.hackrf_error_name.restype = ctypes.c_char_p
    lib.hackrf_board_id_read.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8)]
    lib.hackrf_version_string_read.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint8]
    lib.hackrf_board_partid_serialno_read.argtypes = [ctypes.c_void_p,
                                                      ctypes.POINTER(_read_partid_serialno)]
    for fn in ("hackrf_set_sample_rate", "hackrf_set_freq", "hackrf_set_lna_gain",
               "hackrf_set_vga_gain", "hackrf_set_amp_enable", "hackrf_start_rx",
               "hackrf_stop_rx", "hackrf_board_id_read", "hackrf_version_string_read",
               "hackrf_board_partid_serialno_read", "hackrf_close"):
        getattr(lib, fn).restype = ctypes.c_int
    _lib = lib
    return lib


def _check(lib, rc: int, what: str) -> None:
    if rc != HACKRF_SUCCESS:
        name = lib.hackrf_error_name(rc)
        raise RuntimeError(f"{what} failed: {name.decode() if name else rc}")


class HackRFStream:
    """One open HackRF in continuous RX. Thread-safe producer (USB) / consumer."""

    def __init__(self, sample_rate: float, center_freq_hz: float,
                 lna_gain: int = 16, vga_gain: int = 24, amp: bool = False) -> None:
        self.lib = load_lib()
        self.sample_rate = float(sample_rate)
        self.center_freq_hz = float(center_freq_hz)
        self.lna_gain, self.vga_gain, self.amp = int(lna_gain), int(vga_gain), bool(amp)

        _check(self.lib, self.lib.hackrf_init(), "hackrf_init")
        self.dev = ctypes.c_void_p()
        _check(self.lib, self.lib.hackrf_open(ctypes.byref(self.dev)), "hackrf_open")

        self.serial = self._read_serial()
        self.board_id, self.firmware = self._read_board()

        _check(self.lib, self.lib.hackrf_set_sample_rate(self.dev, self.sample_rate), "set_sample_rate")
        _check(self.lib, self.lib.hackrf_set_freq(self.dev, int(self.center_freq_hz)), "set_freq")
        _check(self.lib, self.lib.hackrf_set_lna_gain(self.dev, self.lna_gain), "set_lna_gain")
        _check(self.lib, self.lib.hackrf_set_vga_gain(self.dev, self.vga_gain), "set_vga_gain")
        _check(self.lib, self.lib.hackrf_set_amp_enable(self.dev, 1 if self.amp else 0), "set_amp")

        max_chunks = max(8, int(_QUEUE_MAX_S * self.sample_rate * 2 / _TRANSFER_BYTES))
        self._q: queue.Queue[tuple[bytes, float, float]] = queue.Queue(maxsize=max_chunks)
        self._lock = threading.Lock()
        self._leftover = b""
        self._leftover_center = self.center_freq_hz
        self.overflow_count = 0        # transfers dropped because the consumer lagged
        self.short_reads = 0           # windows that could not be filled in time
        self.total_samples = 0         # samples handed to the consumer
        self.received_bytes = 0        # bytes delivered by the radio (incl. dropped/flushed)
        self._started_at = 0.0
        self._streaming = False
        self._cb = _RX_CB(self._rx_callback)   # keep a reference: libhackrf holds the pointer

    # --- device info ---------------------------------------------------------
    def _read_serial(self) -> str | None:
        info = _read_partid_serialno()
        if self.lib.hackrf_board_partid_serialno_read(self.dev, ctypes.byref(info)) != HACKRF_SUCCESS:
            return None
        return "".join(f"{w:08x}" for w in info.serial_no)

    def _read_board(self) -> tuple[int | None, str | None]:
        bid = ctypes.c_uint8(0)
        board = bid.value if self.lib.hackrf_board_id_read(self.dev, ctypes.byref(bid)) == HACKRF_SUCCESS else None
        buf = ctypes.create_string_buffer(64)
        fw = buf.value.decode(errors="replace") if self.lib.hackrf_version_string_read(self.dev, buf, 63) == HACKRF_SUCCESS else None
        return board, fw

    def info(self) -> dict:
        return {"serial": self.serial, "board_id": self.board_id, "firmware": self.firmware,
                "sample_rate": self.sample_rate, "center_freq_hz": self.center_freq_hz,
                "lna_gain": self.lna_gain, "vga_gain": self.vga_gain, "amp": self.amp}

    # --- streaming -----------------------------------------------------------
    def _rx_callback(self, transfer) -> int:
        t = transfer.contents
        n = int(t.valid_length)
        if n <= 0:
            return 0
        data = ctypes.string_at(t.buffer, n)      # one memcpy, then hand off
        self.received_bytes += n
        try:
            self._q.put_nowait((data, time.time(), self.center_freq_hz))
        except queue.Full:
            with self._lock:
                self.overflow_count += 1
        return 0

    def start(self) -> None:
        _check(self.lib, self.lib.hackrf_start_rx(self.dev, self._cb, None), "start_rx")
        self._streaming = True
        self._started_at = time.time()

    def tune(self, center_freq_hz: float) -> None:
        center = float(center_freq_hz)
        _check(self.lib, self.lib.hackrf_set_freq(self.dev, int(center)), "set_freq")
        self.center_freq_hz = center
        self.flush()

    def flush(self) -> None:
        """Discard buffered data (e.g. after a retune)."""
        with self._lock:
            self._leftover = b""
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def is_streaming(self) -> bool:
        return self._streaming and self.lib.hackrf_is_streaming(self.dev) == 1

    def read_window(self, n_samples: int, timeout_s: float | None = None):
        """Assemble exactly ``n_samples`` complex64 from the stream.

        Returns ``(iq, info)`` or ``None`` if the stream has stopped. ``info``
        carries capture health: completeness, dropped samples, overflow count,
        and the ratio of achieved to nominal stream rate.
        """
        want = n_samples * 2
        deadline = time.time() + (timeout_s if timeout_s is not None else 3.0 * n_samples / self.sample_rate + 1.0)
        parts: list[bytes] = []
        have = 0
        t_first = None
        center = self.center_freq_hz
        overflow_before = self.overflow_count

        with self._lock:
            if self._leftover:
                parts.append(self._leftover)
                have = len(self._leftover)
                center = self._leftover_center
                self._leftover = b""
        while have < want:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                data, ts, c = self._q.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if not self.is_streaming():
                    return None
                continue
            if t_first is None:
                t_first = ts - len(data) / 2 / self.sample_rate
            if c != center and have == 0:
                center = c
            parts.append(data)
            have += len(data)

        buf = b"".join(parts)
        if have > want:
            with self._lock:
                self._leftover = buf[want:]
                self._leftover_center = center
            buf = buf[:want]

        raw = np.frombuffer(buf, dtype=np.int8)
        iq = (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / 128.0
        iq = iq.astype(np.complex64)

        overflowed = self.overflow_count - overflow_before
        dropped = overflowed * (_TRANSFER_BYTES // 2) + max(0, n_samples - iq.size)
        complete = overflowed == 0 and iq.size >= n_samples
        if iq.size < n_samples:
            with self._lock:
                self.short_reads += 1
        self.total_samples += iq.size
        # Achieved radio->host rate vs nominal: <~0.97 sustained means the USB
        # link is silently losing samples (libhackrf does not report that).
        elapsed = time.time() - self._started_at
        ratio = (self.received_bytes / 2 / (elapsed * self.sample_rate)) if elapsed > 0.5 else 1.0

        info = {
            "captured_at": t_first if t_first is not None else time.time(),
            "center_freq_hz": center,
            "complete": bool(complete),
            "dropped_samples": int(dropped),
            "overflow_count": int(self.overflow_count),
            "short_reads": int(self.short_reads),
            "stream_rate_ratio": round(float(ratio), 4),
        }
        return iq, info

    def close(self) -> None:
        if not self._streaming:
            return
        self._streaming = False
        try:
            self.lib.hackrf_stop_rx(self.dev)
        finally:
            try:
                self.lib.hackrf_close(self.dev)
            finally:
                self.lib.hackrf_exit()
