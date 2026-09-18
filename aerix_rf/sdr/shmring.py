"""Backend-neutral shared-memory chunk ring for SDR producer/consumer IPC.

Implements the ring described in ``docs/design/antsdr-backend.md``, section
"T7 -- acquisition producer as a separate OS process", subsection 2 ("Ring
and header (backend-neutral)"). This module has no libiio/HackRF/DSP
dependencies: any producer that can hand over raw int16 interleaved IQ
chunks (ANTSDR/libiio at cs16, HackRF at cs8 promoted to int16, a file
replay tool, ...) can publish into this ring, and any consumer can read it.

Layout (bytes)::

    [0, GLOBAL_HEADER_SIZE)                     global header page (4 KiB)
    [GLOBAL_HEADER_SIZE, payload_off)           slot header table (64 B/slot)
    [payload_off, payload_off + slots*slot_bytes)  slot payloads (int16 IQ)

Producer never blocks on the reader: ``write_chunk`` always writes to slot
``seq % slot_count`` and publishes the slot header's ``seq`` field last (the
seqlock). The reader re-checks ``seq`` after copying a slot; if it changed,
the writer lapped it mid-read and the read is retried. Reader-side loss is
always exact: it is derived from the sequence-number gap against the ring's
slot geometry (``host_loss_detection="exact_ring"``), never inferred.
"""

from __future__ import annotations

import os
import struct
import time
import uuid
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Callable, List, Optional

import numpy as np

MAGIC = b"AERX"
VERSION = 1

GLOBAL_HEADER_SIZE = 4096
SLOT_HEADER_SIZE = 64
PAGE_SIZE = 4096

# Global header fields, in order:
#   magic, version, slot_count, slot_bytes, chunk_samples, sample_rate,
#   iq_format, raw_full_scale, write_seq, read_seq, producer_pid,
#   producer_state, heartbeat_mono_ns, producer_errno.
_GLOBAL_FMT = "<4sIIIId8sdQQIIQi"
_GLOBAL_SIZE = struct.calcsize(_GLOBAL_FMT)
assert _GLOBAL_SIZE <= GLOBAL_HEADER_SIZE

_OFF_WRITE_SEQ = struct.calcsize("<4sIIIId8sd")
_OFF_READ_SEQ = _OFF_WRITE_SEQ + 8
_OFF_PID = _OFF_READ_SEQ + 8
_OFF_STATE = _OFF_PID + 4
_OFF_HEARTBEAT = _OFF_STATE + 4
_OFF_ERRNO = _OFF_HEARTBEAT + 8
assert _OFF_ERRNO + 4 == _GLOBAL_SIZE

# Per-slot header tail (everything after the 8-byte `seq` seqlock field):
#   sample_index, n_samples, flags, t_mono_ns, t_wall_ns, center_freq_hz,
#   clip_count, peak_abs, meta_epoch, 4 reserved padding bytes.
_SLOT_TAIL_FMT = "<QIIQQdIfI4x"
_SLOT_SIZE = 8 + struct.calcsize(_SLOT_TAIL_FMT)
assert _SLOT_SIZE == SLOT_HEADER_SIZE

FLAG_RETUNE = 1 << 0
FLAG_RESTART = 1 << 1
FLAG_WARN = 1 << 2

STATE_INIT = 0
STATE_RUNNING = 1
STATE_STOPPED = 2
STATE_ERROR = 3


def _round_up(value: int, align: int) -> int:
    return (value + align - 1) // align * align


@dataclass
class SlotHeader:
    seq: int
    sample_index: int
    n_samples: int
    flags: int
    t_mono_ns: int
    t_wall_ns: int
    center_freq_hz: float
    clip_count: int
    peak_abs: float
    meta_epoch: int


@dataclass
class ReadResult:
    header: SlotHeader
    data: np.ndarray  # shape (n_samples, 2) int16, columns = [I, Q]
    host_dropped_samples: int
    host_overrun_events: int
    host_loss_detection: str = "exact_ring"


class ShmRing:
    """Fixed-slot ring of raw int16 IQ chunks over POSIX shared memory.

    One process (the producer) calls ``write_chunk``; it never blocks on the
    reader and always overwrites the oldest slot. One process (the consumer)
    calls ``read_next``; falling behind is detected and accounted for
    exactly, never silently.
    """

    def __init__(self, shm: shared_memory.SharedMemory, owner: bool):
        self._shm = shm
        self._buf = shm.buf
        self._owner = owner
        (
            magic,
            version,
            self.slot_count,
            self.slot_bytes,
            self.chunk_samples,
            self.sample_rate,
            iq_format,
            self.full_scale,
            write_seq,
            _read_seq,
            _pid,
            _state,
            _hb,
            _errno,
        ) = struct.unpack_from(_GLOBAL_FMT, self._buf, 0)
        if magic != MAGIC:
            raise ValueError(f"bad ring magic {magic!r} in {shm.name!r}")
        if version != VERSION:
            raise ValueError(f"unsupported ring version {version}")
        self.iq_format = iq_format.rstrip(b"\x00").decode("ascii")
        self._slot_header_off = GLOBAL_HEADER_SIZE
        self._payload_off = _round_up(
            GLOBAL_HEADER_SIZE + self.slot_count * SLOT_HEADER_SIZE, PAGE_SIZE
        )
        # Writer-local state (only meaningful in the producer process).
        self._next_seq = write_seq
        self._next_sample_index = 0
        # Reader-local state (only meaningful in the consumer process).
        self._last_consumed_seq = -1

    # -- construction -------------------------------------------------

    @classmethod
    def create(
        cls,
        slots: int = 32,
        slot_samples: int = 1 << 20,
        sample_rate: float = 0.0,
        iq_format: str = "cs16",
        full_scale: float = 2048.0,
        name: Optional[str] = None,
    ) -> "ShmRing":
        if name is None:
            name = f"aerix-ring-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        slot_bytes = slot_samples * 4  # interleaved int16 I/Q: 4 bytes/sample
        header_table_size = slots * SLOT_HEADER_SIZE
        payload_off = _round_up(GLOBAL_HEADER_SIZE + header_table_size, PAGE_SIZE)
        total_size = payload_off + slots * slot_bytes
        shm = shared_memory.SharedMemory(name=name, create=True, size=total_size)
        try:
            struct.pack_into(
                _GLOBAL_FMT,
                shm.buf,
                0,
                MAGIC,
                VERSION,
                slots,
                slot_bytes,
                slot_samples,
                float(sample_rate),
                iq_format.encode("ascii")[:8].ljust(8, b"\x00"),
                float(full_scale),
                0,  # write_seq
                0,  # read_seq
                0,  # producer_pid
                STATE_INIT,
                0,  # heartbeat_mono_ns
                0,  # producer_errno
            )
        except Exception:
            shm.close()
            shm.unlink()
            raise
        return cls(shm, owner=True)

    @classmethod
    def attach(cls, name: str) -> "ShmRing":
        shm = shared_memory.SharedMemory(name=name, create=False)
        return cls(shm, owner=False)

    @property
    def name(self) -> str:
        return self._shm.name

    @property
    def slot_samples(self) -> int:
        return self.chunk_samples

    @property
    def total_size(self) -> int:
        return self._payload_off + self.slot_count * self.slot_bytes

    # -- producer side --------------------------------------------------

    def heartbeat(self, state: int = STATE_RUNNING) -> None:
        struct.pack_into("<I", self._buf, _OFF_PID, os.getpid())
        struct.pack_into("<I", self._buf, _OFF_STATE, state)
        struct.pack_into("<Q", self._buf, _OFF_HEARTBEAT, time.monotonic_ns())

    def mark_error(self, errno_value: int) -> None:
        struct.pack_into("<I", self._buf, _OFF_STATE, STATE_ERROR)
        struct.pack_into("<i", self._buf, _OFF_ERRNO, int(errno_value))

    def write_chunk(
        self,
        raw,
        *,
        n_samples: Optional[int] = None,
        flags: int = 0,
        t_mono_ns: Optional[int] = None,
        t_wall_ns: Optional[int] = None,
        center_freq_hz: float = 0.0,
        clip_count: int = 0,
        peak_abs: float = 0.0,
        meta_epoch: int = 0,
        sample_index: Optional[int] = None,
    ) -> int:
        """Publish one chunk. Never blocks; overwrites the oldest slot."""
        data = np.asarray(raw, dtype=np.int16).reshape(-1)
        total_int16 = data.shape[0]
        if n_samples is None:
            if total_int16 % 2 != 0:
                raise ValueError("raw buffer length must be even (I/Q interleaved)")
            n_samples = total_int16 // 2
        if n_samples > self.chunk_samples:
            raise ValueError(
                f"chunk of {n_samples} samples exceeds slot capacity {self.chunk_samples}"
            )
        seq = self._next_seq
        slot_idx = seq % self.slot_count
        payload_off = self._payload_off + slot_idx * self.slot_bytes
        view = np.ndarray(
            shape=(self.chunk_samples * 2,),
            dtype=np.int16,
            buffer=self._buf,
            offset=payload_off,
        )
        view[: n_samples * 2] = data[: n_samples * 2]

        if sample_index is None:
            sample_index = self._next_sample_index
        if t_mono_ns is None:
            t_mono_ns = time.monotonic_ns()
        if t_wall_ns is None:
            t_wall_ns = time.time_ns()

        hdr_off = self._slot_header_off + slot_idx * SLOT_HEADER_SIZE
        # Write everything except `seq` first; publish `seq` last (seqlock).
        struct.pack_into(
            _SLOT_TAIL_FMT,
            self._buf,
            hdr_off + 8,
            sample_index,
            n_samples,
            flags,
            t_mono_ns,
            t_wall_ns,
            float(center_freq_hz),
            clip_count,
            float(peak_abs),
            meta_epoch,
        )
        struct.pack_into("<Q", self._buf, hdr_off, seq)

        self._next_seq = seq + 1
        self._next_sample_index = sample_index + n_samples
        struct.pack_into("<Q", self._buf, _OFF_WRITE_SEQ, self._next_seq)
        return seq

    # -- consumer side ----------------------------------------------------

    def read_next(
        self, copy: bool = True, _mid_read_hook: Optional[Callable[[], None]] = None
    ) -> Optional[ReadResult]:
        """Return the next unread chunk, or None if none is available yet.

        On falling behind, `host_dropped_samples`/`host_overrun_events` on
        the returned result account for the exact number of samples the
        ring physically lost (seq-gap x slot geometry), never a guess.
        """
        write_seq = struct.unpack_from("<Q", self._buf, _OFF_WRITE_SEQ)[0]
        next_expected = self._last_consumed_seq + 1
        if write_seq <= next_expected:
            return None  # nothing new published yet

        dropped_chunks = 0
        overrun = False
        lag = write_seq - next_expected
        if lag > self.slot_count:
            skip_to = write_seq - self.slot_count
            dropped_chunks += skip_to - next_expected
            next_expected = skip_to
            overrun = True

        while True:
            slot_idx = next_expected % self.slot_count
            hdr_off = self._slot_header_off + slot_idx * SLOT_HEADER_SIZE
            seq0 = struct.unpack_from("<Q", self._buf, hdr_off)[0]
            if seq0 < next_expected:
                # Not actually published yet (race with a concurrent writer);
                # nothing to report this call.
                return None
            if seq0 > next_expected:
                # The writer lapped us again since the check above.
                dropped_chunks += seq0 - next_expected
                next_expected = seq0
                overrun = True

            (
                sample_index,
                n_samples,
                flags,
                t_mono_ns,
                t_wall_ns,
                center_freq_hz,
                clip_count,
                peak_abs,
                meta_epoch,
            ) = struct.unpack_from(_SLOT_TAIL_FMT, self._buf, hdr_off + 8)

            payload_off = self._payload_off + slot_idx * self.slot_bytes
            view = np.ndarray(
                shape=(self.chunk_samples * 2,),
                dtype=np.int16,
                buffer=self._buf,
                offset=payload_off,
            )
            if _mid_read_hook is not None:
                _mid_read_hook()
            sliced = view[: n_samples * 2]
            out = np.array(sliced, copy=True) if copy else sliced

            seq1 = struct.unpack_from("<Q", self._buf, hdr_off)[0]
            if seq1 != seq0:
                # Torn read: writer overwrote this slot mid-copy. Retry.
                continue
            break

        self._last_consumed_seq = seq0
        struct.pack_into("<Q", self._buf, _OFF_READ_SEQ, seq0)

        header = SlotHeader(
            seq=seq0,
            sample_index=sample_index,
            n_samples=n_samples,
            flags=flags,
            t_mono_ns=t_mono_ns,
            t_wall_ns=t_wall_ns,
            center_freq_hz=center_freq_hz,
            clip_count=clip_count,
            peak_abs=peak_abs,
            meta_epoch=meta_epoch,
        )
        return ReadResult(
            header=header,
            data=out.reshape(-1, 2),
            host_dropped_samples=dropped_chunks * self.chunk_samples,
            host_overrun_events=1 if overrun else 0,
        )

    def producer_alive(self, timeout: float = 1.0) -> bool:
        state = struct.unpack_from("<I", self._buf, _OFF_STATE)[0]
        heartbeat_ns = struct.unpack_from("<Q", self._buf, _OFF_HEARTBEAT)[0]
        if heartbeat_ns == 0 or state == STATE_ERROR or state == STATE_STOPPED:
            return False
        age_ns = time.monotonic_ns() - heartbeat_ns
        return age_ns <= int(timeout * 1e9)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        if self._buf is not None:
            try:
                self._buf.release()
            except Exception:
                pass
            self._buf = None
        try:
            self._shm.close()
        except Exception:
            pass

    def unlink(self) -> None:
        try:
            self._shm.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    except OSError:
        return False
    return True


def sweep_stale_rings(prefix: str, shm_dir: str = "/dev/shm") -> List[str]:
    """Unlink rings under `prefix` whose recorded producer pid is dead.

    Meant to be called once at process startup, before creating a new ring,
    so crashed producers don't leak shared-memory segments across runs.
    """
    removed: List[str] = []
    try:
        entries = os.listdir(shm_dir)
    except OSError:
        return removed
    for entry in entries:
        if not entry.startswith(prefix):
            continue
        try:
            ring = ShmRing.attach(entry)
        except (FileNotFoundError, ValueError, OSError):
            continue
        try:
            pid = struct.unpack_from("<I", ring._buf, _OFF_PID)[0]
            if _pid_alive(pid):
                continue
            ring.unlink()
            removed.append(entry)
        finally:
            ring.close()
    return removed
