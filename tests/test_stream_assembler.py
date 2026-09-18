"""Unit tests for the backend-neutral ``StreamAssembler`` (T2).

Covers: exact-size chunks, ragged chunk sizes, a hole with a known dropped
count, a hole with unknown (unquantifiable) drops, a producer that can never
report drops at all (``reports_drops=False``, the libiio case), a stop
mid-window, and that the HackRF producer path (via ``libhackrf._cs8_to_iq``)
still yields the pre-refactor documented ``info`` keys.
"""

import threading
import time

import numpy as np
import pytest

from aerix_rf.sdr.stream import StreamAssembler

SR = 10.0  # samples/s -- tiny, just for arithmetic convenience in tests


def cplx(n, start=0):
    """n deterministic complex64 samples, distinguishable by value."""
    return np.arange(start, start + n, dtype=np.float32).astype(np.complex64)


# --- exact-size chunks -----------------------------------------------------

def test_exact_size_chunks_fill_window():
    asm = StreamAssembler(SR)
    asm.push(cplx(5, 0), time.time(), 100e6, dropped_before=0)
    out = asm.read_window(5, timeout_s=1.0)
    assert out is not None
    iq, info = out
    assert iq.size == 5
    assert np.array_equal(iq, cplx(5, 0))
    assert info["complete"] is True
    assert info["dropped_samples"] == 0
    assert info["overflow_count"] == 0
    assert info["gap_before_samples"] == 0
    assert info["loss_detection"] == "exact"
    assert info["stream_rate_ratio"] > 0


# --- ragged chunk sizes, leftover carried across windows -------------------

def test_ragged_chunks_split_across_window_boundary():
    asm = StreamAssembler(SR)
    # 2 + 3 + 4 = 9 samples pushed; window size 5 -> first window consumes
    # 2+3, second window gets the leftover 0 from chunk2 plus chunk3's tail.
    asm.push(cplx(2, 0), time.time(), 100e6, dropped_before=0)
    asm.push(cplx(3, 2), time.time(), 100e6, dropped_before=0)
    asm.push(cplx(4, 5), time.time(), 100e6, dropped_before=0)

    iq1, info1 = asm.read_window(5, timeout_s=1.0)
    assert iq1.size == 5
    assert np.array_equal(iq1, cplx(5, 0))
    assert info1["complete"] is True

    iq2, info2 = asm.read_window(4, timeout_s=1.0)
    assert iq2.size == 4
    assert np.array_equal(iq2, cplx(4, 5))
    assert info2["complete"] is True


# --- hole with a KNOWN dropped count ----------------------------------------

def test_known_dropped_count_inside_window_via_explicit_hint():
    asm = StreamAssembler(SR)
    asm.push(cplx(5, 0), time.time(), 100e6, dropped_before=0)
    # Producer reports it knows exactly 3 samples were lost before this chunk
    # (e.g. an authoritative overflow counter from the driver).
    asm.push(cplx(5, 5), time.time(), 100e6, dropped_before=3)
    iq, info = asm.read_window(10, timeout_s=1.0)
    assert iq.size == 10
    assert info["complete"] is False
    assert info["dropped_samples"] == 3
    assert info["loss_detection"] == "exact"


def test_known_dropped_count_from_queue_overflow_eviction():
    # Tiny queue: the 3rd push must evict the 1st (drop-oldest), and the
    # assembler knows the evicted chunk's exact size.
    asm = StreamAssembler(SR, queue_max_s=100.0, chunk_samples_hint=1000000)
    # Force maxsize=8 (the implementation's floor) -> fill it, then overflow.
    for i in range(8):
        asm.push(cplx(1, i), time.time(), 100e6, dropped_before=0)
    asm.push(cplx(1, 8), time.time(), 100e6, dropped_before=0)  # evicts sample 0
    assert asm.overflow_count == 1
    iq, info = asm.read_window(8, timeout_s=1.0)
    assert iq.size == 8
    # samples 1..8 (8 of them); sample 0 (1 sample) known-lost.
    assert np.array_equal(iq, cplx(8, 1))
    assert info["dropped_samples"] == 1
    assert info["complete"] is False
    assert info["overflow_count"] == 1


# --- hole with UNKNOWN drops -------------------------------------------------

def test_unknown_gap_inside_window_is_honest_none():
    asm = StreamAssembler(SR)
    asm.push(cplx(5, 0), time.time(), 100e6, dropped_before=0)
    # Producer knows a gap happened but cannot size it.
    asm.push(cplx(5, 5), time.time(), 100e6, dropped_before=None)
    iq, info = asm.read_window(10, timeout_s=1.0)
    assert iq.size == 10
    assert info["dropped_samples"] is None
    assert info["complete"] is False
    assert info["loss_detection"] == "unknown_gap"


def test_reports_drops_false_never_fabricates_zero():
    # The libiio case: the producer can never assert an exact loss count, even
    # when every chunk it pushes looks perfectly contiguous.
    asm = StreamAssembler(SR, reports_drops=False)
    asm.push(cplx(5, 0), time.time(), 100e6, dropped_before=0)
    asm.push(cplx(5, 5), time.time(), 100e6, dropped_before=0)
    iq, info = asm.read_window(10, timeout_s=1.0)
    assert iq.size == 10
    assert info["dropped_samples"] is None
    assert info["loss_detection"] == "inferred_rate_only"
    # Filled exactly in time -> honestly reported complete, per design doc
    # Path B: "windows are marked complete=True but with dropped_samples=None".
    assert info["complete"] is True


# --- stop mid-window ---------------------------------------------------------

def test_stop_mid_window_returns_none():
    asm = StreamAssembler(SR)
    asm.push(cplx(2, 0), time.time(), 100e6, dropped_before=0)
    asm.mark_stopped()
    out = asm.read_window(5, timeout_s=0.3)
    assert out is None


def test_stream_rate_ratio_present_and_gap_before_between_windows():
    asm = StreamAssembler(SR, queue_max_s=100.0, chunk_samples_hint=1000000)
    for i in range(8):
        asm.push(cplx(1, i), time.time(), 100e6, dropped_before=0)
    iq1, info1 = asm.read_window(8, timeout_s=1.0)  # consume exactly, no leftover
    assert iq1.size == 8
    # Now push a chunk with a KNOWN gap before it (first chunk of the *next*
    # window) -- this must show up as gap_before_samples, not a hole inside
    # this window, and complete stays True for this second window.
    asm.push(cplx(4, 20), time.time(), 100e6, dropped_before=6)
    iq2, info2 = asm.read_window(4, timeout_s=1.0)
    assert iq2.size == 4
    assert info2["gap_before_samples"] == 6
    assert info2["complete"] is True
    assert info2["dropped_samples"] == 0


# --- HackRF producer path: info keys match the pre-refactor contract -------

# Documented, pre-refactor ``HackRFStream.read_window`` info keys (see the
# T2 task packet / git history of aerix_rf/sdr/libhackrf.py before the
# StreamAssembler extraction) plus ``capture.py:LibHackRFSource`` which reads
# every one of these out of ``info`` by name.
PRE_REFACTOR_INFO_KEYS = {
    "captured_at", "center_freq_hz", "complete", "dropped_samples",
    "overflow_count", "gap_before_samples", "short_reads", "stream_rate_ratio",
}


# --- stream_rate_ratio: controlled-clock accuracy + startup-transient recovery
#
# Root cause of the 2026-09-18 ANTSDR soak-test anomaly (see
# docs/design/antsdr-backend.md "Measured host-path throughput (2026-09-18)"):
# the ratio was a LIFETIME average anchored at the first pushed chunk. A single
# one-time startup transient (a slow first refill/buffer-fill) permanently
# suppressed the reported ratio for the rest of an hours-long capture, because
# the deficit was divided by ever-growing total elapsed time (0.65-0.79 for
# ~500 windows, only reaching the true ~0.947 steady-state value at the very
# end of a 590s run). ``StreamAssembler`` now uses a trailing window
# (``rate_window_s``, default 5s) once enough stream has been seen, so it
# reflects *current* throughput and self-heals after a transient.

class _FakeClock:
    """Deterministic, manually-advanced clock swapped in for ``time.time``."""

    def __init__(self, t0: float = 1_000_000.0):
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _raw_to_iq_i16(raw):
    raw = raw.astype(np.float32)
    iq = raw[0::2] + 1j * raw[1::2]
    return (iq / 2048.0).astype(np.complex64)


def _run_synthetic_stream(monkeypatch, *, rate_frac: float, total_s: float,
                           sample_rate: float = 12.288e6, chunk_samples: int = 16384,
                           rate_window_s: float = 5.0, phase2_rate_frac: float | None = None,
                           phase2_after_s: float | None = None):
    """Push chunks at ``rate_frac`` of ``sample_rate`` with realistic wall-clock
    pacing (a controllable, manually-advanced fake clock, not real sleeps), and
    read 1s windows as they become available. Returns the list of
    ``stream_rate_ratio`` values, one per completed window, in order.

    ``phase2_rate_frac``/``phase2_after_s``: optionally switch to a second,
    different rate after ``phase2_after_s`` of pushed stream time -- models a
    sustained early-capture throughput dip that later recovers (see the live
    2026-09-18 ANTSDR soak-test anomaly this reproduces).
    """
    import aerix_rf.sdr.stream as streammod

    clock = _FakeClock()
    monkeypatch.setattr(streammod.time, "time", clock)

    asm = streammod.StreamAssembler(sample_rate, raw_to_iq=_raw_to_iq_i16,
                                     reports_drops=False, queue_max_s=5.0,
                                     chunk_samples_hint=chunk_samples,
                                     rate_window_s=rate_window_s)
    n = int(sample_rate * 1.0)
    nominal_chunk_dt = chunk_samples / sample_rate
    ratios = []
    pushed_s = 0.0
    while pushed_s < total_s:
        current_frac = rate_frac
        if phase2_rate_frac is not None and pushed_s >= (phase2_after_s or 0.0):
            current_frac = phase2_rate_frac
        dt = nominal_chunk_dt / current_frac
        clock.advance(dt)
        raw = np.zeros(chunk_samples * 2, dtype=np.int16)
        asm.push(raw, clock(), 2437e6, dropped_before=0)
        pushed_s += nominal_chunk_dt / current_frac
        if asm._pushed_samples - asm.total_samples >= n:
            win = asm.read_window(n, timeout_s=0.01)
            if win is not None:
                ratios.append(win[1]["stream_rate_ratio"])
    return ratios


def test_rate_ratio_at_nominal_rate_reads_near_one(monkeypatch):
    ratios = _run_synthetic_stream(monkeypatch, rate_frac=1.0, total_s=5.0)
    assert len(ratios) >= 4
    # small chunks (16384 samples ~= 1.3ms) keep first-window boundary bias
    # negligible; every window should read close to 1.0.
    for r in ratios:
        assert abs(r - 1.0) <= 0.01, ratios


def test_rate_ratio_at_95pct_rate_reads_near_0_95(monkeypatch):
    ratios = _run_synthetic_stream(monkeypatch, rate_frac=0.95, total_s=5.0)
    assert len(ratios) >= 4
    for r in ratios:
        assert abs(r - 0.95) <= 0.01, ratios


def test_rate_ratio_self_heals_after_sustained_early_dip(monkeypatch):
    """Reproduces the live 2026-09-18 ANTSDR soak-test anomaly at reduced scale:
    the real 590s capture ran at ~65% instantaneous throughput for its first
    ~63 windows (~65-95s, per ``captured_at`` deltas in the recorded session),
    then recovered to ~100% for the remaining ~500 windows -- yet the reported
    ``stream_rate_ratio`` only climbed from 0.67 to 0.947 gradually over the
    ENTIRE 590s, because it was a lifetime average anchored at stream start.

    This test models the same two-phase shape at 1/10th scale (6.3s dip, then
    recovery) and requires the FIXED ratio to settle near the recovered
    (~1.0) steady state within ``rate_window_s`` of the recovery, not still be
    dragged toward the old ~0.7-0.9 lifetime-average value seconds later.
    """
    ratios = _run_synthetic_stream(monkeypatch, rate_frac=0.65, total_s=15.0,
                                    rate_window_s=5.0,
                                    phase2_rate_frac=1.0, phase2_after_s=6.3)
    assert len(ratios) >= 10
    # Early windows (during the dip) do read low, honestly.
    assert ratios[0] < 0.75
    # By ~5-6s after recovery (>= rate_window_s), the ratio must reflect
    # CURRENT throughput, not the stale lifetime average -- the live run's
    # equivalent metric was still reading ~0.70-0.76 at this relative point.
    for r in ratios[-3:]:
        assert r >= 0.97, ratios


def test_hackrf_producer_path_preserves_documented_info_keys():
    from aerix_rf.sdr.libhackrf import _cs8_to_iq

    asm = StreamAssembler(SR, raw_to_iq=_cs8_to_iq, reports_drops=True)
    raw = np.array([10, 20, -10, -20, 30, 40], dtype=np.int8)  # 3 cs8 samples
    asm.push(raw, time.time(), 2440e6, dropped_before=0)
    iq, info = asm.read_window(3, timeout_s=1.0)
    assert iq.size == 3
    assert iq.dtype == np.complex64
    expected = np.array([10 + 20j, -10 - 20j, 30 + 40j], dtype=np.complex64) / 128.0
    assert np.allclose(iq, expected)
    assert PRE_REFACTOR_INFO_KEYS <= set(info.keys())
    # additive T1/T2 fields must also be present
    assert "loss_detection" in info
    assert "channel_id" in info
    assert "bandwidth_hz" in info
    assert "timing" in info and info["timing"]["clock_source"] == "host_wallclock"
