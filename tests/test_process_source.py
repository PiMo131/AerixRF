"""T7b acceptance tests: real subprocess producer + shared-memory ring.

No hardware. Uses ``aerix_rf.sdr.process_source.ProcessIQSource`` with
``source_type="synthetic"`` (``aerix_rf.sdr.producer_main.SyntheticSource``)
end to end -- a real ``python -m aerix_rf.sdr.producer_main`` subprocess, a
real POSIX shared-memory ring, a real control socketpair. Every test closes
its source in a ``finally`` so a failing assertion never leaves an orphan
producer process or a leaked ``/dev/shm`` segment.
"""

from __future__ import annotations

import itertools
import os

import pytest

from aerix_rf.sdr.process_source import ProcessIQSource, ProducerLostError

SAMPLE_RATE = 200_000.0
CHUNK_SAMPLES = 2_000  # 10 ms/chunk at SAMPLE_RATE


def _make(**kwargs) -> ProcessIQSource:
    kwargs.setdefault("source_type", "synthetic")
    kwargs.setdefault("sample_rate", SAMPLE_RATE)
    kwargs.setdefault("center_freq_hz", 2_440_000_000.0)
    kwargs.setdefault("chunk_samples", CHUNK_SAMPLES)
    return ProcessIQSource(**kwargs)


def test_clean_stream_zero_drops():
    src = _make(window_seconds=1.0)
    try:
        windows = list(itertools.islice(src.windows(), 3))
    finally:
        src.close()

    assert len(windows) == 3
    expected_n = int(SAMPLE_RATE * 1.0)
    for w in windows:
        assert w.iq.dtype.name == "complex64"
        assert w.iq.size == expected_n
        assert w.complete is True
        assert w.dropped_samples in (0, None)
        md = w.metadata
        for key in ("host_loss_detection", "host_dropped_samples",
                    "host_overrun_events", "loss_detection"):
            assert key in md
        assert md["host_loss_detection"] == "exact_ring"
        assert md["host_dropped_samples"] == 0
        assert md["host_overrun_events"] == 0
        assert md["loss_detection"] == "n/a"


def test_drop_chunk_exact_gap():
    src = _make(window_seconds=1.0, extra_args=["--drop-chunk", "5"])
    try:
        win = next(src.windows())
    finally:
        src.close()

    assert win.complete is False
    # Exactly one chunk (CHUNK_SAMPLES) was dropped inside this window.
    assert win.dropped_samples == CHUNK_SAMPLES
    assert win.metadata["host_dropped_samples"] == CHUNK_SAMPLES
    assert win.metadata["host_overrun_events"] == 0  # a producer-declared
    # drop, not a ring overrun -- the ring's own seq sequence stayed contiguous.


def test_stall_causes_exact_ring_overrun():
    src = _make(window_seconds=0.05, slots=2, extra_args=["--stall-after", "3"])
    try:
        last_md = None
        for w in itertools.islice(src.windows(), 40):
            last_md = w.metadata
            if last_md["host_overrun_events"] >= 1:
                break
    finally:
        src.close()

    assert last_md is not None
    assert last_md["host_dropped_samples"] > 0
    # Exact accounting (ring-level, proven deterministically in
    # test_shmring.py): every dropped sample is a whole chunk, never a partial
    # one. The exact NUMBER of overrun events a single 0.5s catch-up burst
    # produces on a real 2-slot ring depends on OS scheduling of two real
    # processes (a burst that outruns a 2ms reader poll can register as more
    # than one lap) -- >=1 is the honest, non-flaky assertion; ==0 would mean
    # the fault injection did nothing.
    assert last_md["host_dropped_samples"] % CHUNK_SAMPLES == 0
    assert last_md["host_overrun_events"] >= 1


def test_producer_death_raises_and_cleans_up():
    src = _make(window_seconds=1.0, extra_args=["--die-after", "5"])
    ring_name = src._ring.name
    try:
        with pytest.raises(ProducerLostError):
            for _ in src.windows():
                pass
    finally:
        src.close()

    assert src._proc.poll() is not None  # no orphan: process has exited
    assert ring_name not in os.listdir("/dev/shm")


def test_tune_flushes_and_new_windows_carry_new_center():
    src = _make(window_seconds=0.1)
    try:
        gen = src.windows()
        first = next(gen)
        assert first.center_freq_hz == pytest.approx(2_440_000_000.0)

        new_freq = 2_450_000_000.0
        src.tune(new_freq)

        seen_new = False
        for w in itertools.islice(gen, 10):
            if w.center_freq_hz == pytest.approx(new_freq):
                seen_new = True
                break
        assert seen_new
    finally:
        src.close()


def test_clean_close_leaves_no_shm_residue():
    src = _make(window_seconds=0.1)
    ring_name = src._ring.name
    try:
        next(src.windows())
    finally:
        src.close()

    assert ring_name not in os.listdir("/dev/shm")
