"""Tests for aerix_rf.sdr.shmring.ShmRing (backend-neutral chunk ring, T7a).

All tests run single-process/threads-only: no multiprocessing.Process is
spawned. "Writer" and "reader" roles are just method calls on the same (or
attached) ring object.
"""

import os
import subprocess
import time

import numpy as np
import pytest

from aerix_rf.sdr import shmring
from aerix_rf.sdr.shmring import ShmRing


def _iq_chunk(n_samples: int, offset: int) -> np.ndarray:
    """Deterministic interleaved int16 I/Q pattern keyed by `offset`."""
    idx = np.arange(n_samples * 2, dtype=np.int16)
    return idx + np.int16(offset)


@pytest.fixture
def ring():
    r = ShmRing.create(
        slots=8,
        slot_samples=16,
        sample_rate=13.44e6,
        iq_format="cs16",
        full_scale=2048.0,
    )
    yield r
    r.close()
    r.unlink()


def test_create_attach_roundtrip(ring):
    other = ShmRing.attach(ring.name)
    try:
        assert other.slot_count == 8
        assert other.chunk_samples == 16
        assert other.iq_format == "cs16"
        assert other.sample_rate == pytest.approx(13.44e6)
        assert other.full_scale == pytest.approx(2048.0)
    finally:
        other.close()


def test_write_read_roundtrip(ring):
    chunk = _iq_chunk(16, offset=100)
    seq = ring.write_chunk(
        chunk, center_freq_hz=2437e6, clip_count=3, peak_abs=0.5, meta_epoch=7
    )
    assert seq == 0

    result = ring.read_next()
    assert result is not None
    assert result.header.seq == 0
    assert result.header.n_samples == 16
    assert result.header.center_freq_hz == pytest.approx(2437e6)
    assert result.header.clip_count == 3
    assert result.header.peak_abs == pytest.approx(0.5)
    assert result.header.meta_epoch == 7
    assert result.host_dropped_samples == 0
    assert result.host_overrun_events == 0
    assert result.host_loss_detection == "exact_ring"
    assert result.data.shape == (16, 2)
    np.testing.assert_array_equal(result.data.reshape(-1), chunk)

    # No new data yet.
    assert ring.read_next() is None


def test_wrap_around_keeps_up(ring):
    n_chunks = ring.slot_count + 3  # forces reuse of every slot at least once
    for i in range(n_chunks):
        chunk = _iq_chunk(ring.chunk_samples, offset=i)
        ring.write_chunk(chunk, sample_index=i * ring.chunk_samples)

        result = ring.read_next()
        assert result is not None, f"expected chunk {i}"
        assert result.header.seq == i
        assert result.header.sample_index == i * ring.chunk_samples
        assert result.host_overrun_events == 0
        assert result.host_dropped_samples == 0
        np.testing.assert_array_equal(
            result.data.reshape(-1), _iq_chunk(ring.chunk_samples, offset=i)
        )


def test_reader_falls_behind_reports_exact_loss(ring):
    k = 3
    n_chunks = ring.slot_count + k
    for i in range(n_chunks):
        ring.write_chunk(_iq_chunk(ring.chunk_samples, offset=i))

    result = ring.read_next()
    assert result is not None
    assert result.host_overrun_events == 1
    assert result.host_dropped_samples == k * ring.chunk_samples
    assert result.host_loss_detection == "exact_ring"
    # The oldest surviving chunk is seq == k.
    assert result.header.seq == k
    np.testing.assert_array_equal(
        result.data.reshape(-1), _iq_chunk(ring.chunk_samples, offset=k)
    )

    # Next read should be the following chunk, loss-free.
    result2 = ring.read_next()
    assert result2.header.seq == k + 1
    assert result2.host_overrun_events == 0
    assert result2.host_dropped_samples == 0


def test_torn_read_is_retried_not_returned(ring):
    ring.write_chunk(_iq_chunk(ring.chunk_samples, offset=0))

    fired = {"done": False}

    def clobber():
        if fired["done"]:
            return
        fired["done"] = True
        # Wrap all the way around so the slot currently being read gets
        # overwritten mid-copy by the producer.
        for j in range(1, ring.slot_count + 1):
            ring.write_chunk(_iq_chunk(ring.chunk_samples, offset=j))

    result = ring.read_next(_mid_read_hook=clobber)
    assert fired["done"]
    assert result is not None
    # The retry must land on fresh, self-consistent data (the new occupant
    # of that slot), never a torn mix of old/new bytes.
    assert result.header.seq == ring.slot_count
    np.testing.assert_array_equal(
        result.data.reshape(-1), _iq_chunk(ring.chunk_samples, offset=ring.slot_count)
    )
    assert result.host_overrun_events == 1
    assert result.host_dropped_samples == ring.slot_count * ring.chunk_samples


def test_producer_alive_false_after_heartbeat_stops(ring):
    assert ring.producer_alive(timeout=0.5) is False  # never beaten yet
    ring.heartbeat()
    assert ring.producer_alive(timeout=0.5) is True
    time.sleep(0.6)
    assert ring.producer_alive(timeout=0.5) is False


def test_sweep_stale_rings_removes_dead_pid_ring():
    prefix = f"aerix-ring-swtest-{os.getpid()}-"
    name = prefix + "0"
    r = ShmRing.create(slots=4, slot_samples=8, sample_rate=1e6, name=name)
    try:
        p = subprocess.Popen(["true"])
        dead_pid = p.pid
        p.wait()

        import struct as _struct

        _struct.pack_into("<I", r._buf, shmring._OFF_PID, dead_pid)

        removed = shmring.sweep_stale_rings(prefix)
        assert name in removed

        with pytest.raises(FileNotFoundError):
            ShmRing.attach(name).close()
    finally:
        r.close()
        try:
            r.unlink()
        except Exception:
            pass


def test_sweep_stale_rings_keeps_alive_pid_ring():
    prefix = f"aerix-ring-swtest2-{os.getpid()}-"
    name = prefix + "0"
    r = ShmRing.create(slots=4, slot_samples=8, sample_rate=1e6, name=name)
    try:
        r.heartbeat()  # records our own (very much alive) pid
        removed = shmring.sweep_stale_rings(prefix)
        assert name not in removed
        other = ShmRing.attach(name)
        other.close()
    finally:
        r.close()
        r.unlink()


def test_writer_throughput_microbench():
    """Pace writes to real-time 13.44 MS/s and measure writer CPU cost.

    This is the acceptance target from docs/design/antsdr-backend.md T7:
    the producer's memcpy+header-write path must cost well under one full
    core at the target rate.
    """
    sample_rate = 13.44e6
    slot_samples = 1 << 16  # 65536 samples/chunk -> ~4.88 ms/chunk
    duration_s = 5.0

    r = ShmRing.create(
        slots=64, slot_samples=slot_samples, sample_rate=sample_rate, iq_format="cs16"
    )
    try:
        chunk = np.zeros(slot_samples * 2, dtype=np.int16)
        chunk_period_s = slot_samples / sample_rate
        n_chunks = int(duration_s / chunk_period_s)

        start_wall = time.perf_counter()
        start_cpu = time.process_time()
        next_deadline = start_wall
        for _ in range(n_chunks):
            r.write_chunk(chunk, center_freq_hz=2437e6)
            next_deadline += chunk_period_s
            sleep_for = next_deadline - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)
        wall_elapsed = time.perf_counter() - start_wall
        cpu_elapsed = time.process_time() - start_cpu

        achieved_rate = (n_chunks * slot_samples) / wall_elapsed
        cpu_fraction = cpu_elapsed / wall_elapsed
        print(
            f"\n[microbench] n_chunks={n_chunks} achieved_rate={achieved_rate:.0f} sps "
            f"(target {sample_rate:.0f}) cpu_fraction={cpu_fraction:.4f} of one core"
        )

        assert achieved_rate >= sample_rate * 0.95
        assert cpu_fraction < 0.20
    finally:
        r.close()
        r.unlink()
