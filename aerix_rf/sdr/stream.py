"""Backend-neutral continuous-stream -> fixed-size ``IQWindow`` assembly.

Lifted out of ``libhackrf.py`` (see docs/design/antsdr-backend.md #2, T2): every
continuous-RX backend (HackRF, and later ANTSDR via UHD or libiio) shares one
producer/consumer shape -- a producer thread hands off small chunks as they
arrive, a consumer thread assembles exactly ``n_samples`` and stamps the result
with honest capture-health metadata. Keeping that assembly in one place makes
``overflow_count`` / ``gap_before_samples`` / ``complete`` / ``dropped_samples``
mean the same thing on every backend by construction, not by review.

Design:
  * The producer calls :meth:`StreamAssembler.push` once per received chunk. A
    chunk is either already-converted ``complex64`` IQ, or a *raw* interleaved
    I,Q array (any dtype: HackRF's int8, AD9361's int16, ...) plus a
    ``raw_to_iq`` converter given once at construction time. Conversion (and
    any float scaling) is deferred to the *consumer* thread exactly like the
    pre-refactor ``HackRFStream`` -- the producer thread (often a USB/network
    callback with a tight deadline) only stores a cheap view/copy of the chunk.
  * Thread-safe handoff is a bounded ``queue.Queue`` with a drop-OLDEST policy:
    on overflow the oldest buffered chunk is evicted (not the new one), so the
    queue always holds the most recent contiguous stretch of stream and a
    window built from it is complete; the loss surfaces as a gap *between*
    windows (``gap_before_samples`` / rising ``overflow_count``) rather than a
    hole inside one. Identical to the pre-refactor ``HackRFStream`` behaviour.
  * Loss accounting is honest by construction. Every chunk (and every eviction)
    carries a ``dropped_before`` value: ``0`` (contiguous), a known positive
    sample count, or ``None`` (a gap is known to exist but cannot be sized).
    ``reports_drops=False`` marks a producer that can *never* assert an exact
    loss count at all (e.g. libiio with no per-buffer sequence number): every
    window then reports ``dropped_samples=None`` /
    ``loss_detection="inferred_rate_only"`` unconditionally -- never a
    fabricated 0 -- and ``complete`` reflects only whether the window was
    filled in time, per docs/design/antsdr-backend.md #2 Path B.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

log = logging.getLogger("aerix.rf.sdr.stream")

_DEFAULT_QUEUE_MAX_S = 2.0
_DEFAULT_CHUNK_SAMPLES_HINT = 131072   # only used to size the queue depth
_RAW_UNITS_PER_SAMPLE = 2              # interleaved I,Q -> 2 raw elements/sample

CLIP_WARNING_FRACTION = 1e-4           # clip_fraction above this trips clip_warning.
                                        # At the default ANTSDR profile (12.288e6
                                        # samples/window) that is >1229 clipped
                                        # samples in one window -- not a single
                                        # stray outlier, real sustained clipping.


def raw_clip_stats(raw: np.ndarray, full_scale: float) -> tuple[int, float, int]:
    """Clip/peak stats for one interleaved raw I,Q chunk (any signed integer dtype).

    Returns ``(clip_count, peak_abs, sample_count)``:
      * ``clip_count``: complex samples where ``|I| >= full_scale - 1`` or
        ``|Q| >= full_scale - 1`` -- one raw code below the declared full scale,
        since a symmetric two's-complement range has no positive value AT full
        scale (int8 tops out at +127, not +128; ANTSDR's 12-bit-in-int16 tops
        out at +2047, not +2048).
      * ``peak_abs``: the single largest |I| or |Q| raw magnitude in this chunk.
      * ``sample_count``: number of complex samples in this chunk (``raw.size // 2``).

    A single vectorised pass (two ``np.abs`` + two comparisons) -- cheap enough
    to run on every pushed chunk on the producer thread; see module docstring.
    """
    n = raw.size // _RAW_UNITS_PER_SAMPLE
    if n == 0:
        return 0, 0.0, 0
    i = np.abs(raw[0::2].astype(np.float64, copy=False))
    q = np.abs(raw[1::2].astype(np.float64, copy=False))
    threshold = float(full_scale) - 1.0
    clip_count = int(np.count_nonzero((i >= threshold) | (q >= threshold)))
    peak_abs = float(max(float(i.max()), float(q.max())))
    return clip_count, peak_abs, n
_DEFAULT_RATE_WINDOW_S = 10.0          # ``stream_rate_ratio_recent`` trailing-window
                                        # width. Must be several multiples of a
                                        # realistic chunk cadence (~85ms at the
                                        # default ANTSDR profile) so ordinary OS
                                        # scheduling jitter on a handful of chunks
                                        # can't swing the ratio by itself -- a 5s
                                        # window (the previous default) false-fired
                                        # ``rate_warning`` on 487/599 windows of a
                                        # real loss-free 600s soak (see
                                        # docs/design/antsdr-backend.md "Measured
                                        # host-path throughput (2026-09-18)").


@dataclass
class _Chunk:
    raw: Any                       # complex64 ndarray, or raw interleaved ndarray
    ts: float                      # wall-clock at chunk arrival (producer side)
    center_freq_hz: float
    dropped_before: Optional[int]  # samples known lost immediately before this
                                    # chunk; 0 = contiguous, None = unquantifiable
    device_time_ns: Optional[int] = None
    raw_stats: Optional[tuple[int, float, int]] = None  # (clip_count, peak_abs,
                                    # sample_count) on the RAW ints of this chunk,
                                    # from raw_clip_stats(); None when the
                                    # assembler has no raw_full_scale configured
                                    # (this producer can't/doesn't report clip
                                    # health) -- never a fabricated 0.

    def sample_count(self, raw_to_iq: Optional[Callable]) -> int:
        return self.raw.size if raw_to_iq is None else self.raw.size // _RAW_UNITS_PER_SAMPLE

    def start_ts(self, raw_to_iq: Optional[Callable], sample_rate: float) -> float:
        """Host time of this chunk's FIRST sample.

        ``ts`` is stamped by the producer when the chunk finishes arriving
        (after ``buf.read()`` / the USB callback fires with the data), i.e. it
        approximates the *last* sample's arrival time, not the first. Back
        out the chunk's duration to get the first sample's time.
        """
        return self.ts - self.sample_count(raw_to_iq) / sample_rate


class StreamAssembler:
    """Assemble a continuous producer stream into fixed-size ``IQWindow``s.

    One producer thread calls :meth:`push` per received chunk (any size); one
    consumer thread calls :meth:`read_window` to pull exactly ``n_samples``.
    """

    def __init__(self, sample_rate: float, *,
                 raw_to_iq: Optional[Callable[[np.ndarray], np.ndarray]] = None,
                 reports_drops: bool = True,
                 queue_max_s: float = _DEFAULT_QUEUE_MAX_S,
                 chunk_samples_hint: int = _DEFAULT_CHUNK_SAMPLES_HINT,
                 channel_id: int = 0,
                 bandwidth_hz: Optional[float] = None,
                 still_active: Optional[Callable[[], bool]] = None,
                 rate_window_s: float = _DEFAULT_RATE_WINDOW_S,
                 raw_full_scale: Optional[float] = None) -> None:
        self.sample_rate = float(sample_rate)
        self._raw_to_iq = raw_to_iq
        self.reports_drops = bool(reports_drops)
        self.channel_id = int(channel_id)
        self.bandwidth_hz = bandwidth_hz
        # ``raw_full_scale``: the ADC's native full-scale magnitude (128.0 for
        # HackRF's int8, 2048.0 for ANTSDR's 12-bit-in-int16) -- see
        # ``raw_clip_stats``. When set, every pushed chunk gets clip/peak stats
        # computed automatically (unless the caller already supplies
        # ``raw_stats`` explicitly to ``push()``); when ``None`` (sim/file, or
        # any producer that never configures it), every window's
        # clip_fraction/peak_abs_frac/clip_warning are honestly ``None``/``False``.
        self._raw_full_scale = raw_full_scale
        self._stopped = threading.Event()
        self._still_active = still_active or (lambda: not self._stopped.is_set())

        max_chunks = max(8, int(queue_max_s * self.sample_rate / max(1, chunk_samples_hint)))
        self._q: "queue.Queue[_Chunk]" = queue.Queue(maxsize=max_chunks)
        self._lock = threading.Lock()

        self._leftover: Optional[_Chunk] = None

        self.overflow_count = 0
        self.short_reads = 0
        self.tail_discarded_samples = 0  # samples buffered but never handed to a window
                                          # (discarded by flush(): a retune, or stream end
                                          # with data still queued/leftover)
        self.total_samples = 0     # samples handed to the consumer across all windows
        self._pushed_samples = 0   # samples ever pushed (incl. later-evicted), for rate ratio
        self._running_sample_index = 0
        # ``stream_rate_ratio``'s clock starts at the FIRST PUSHED CHUNK, not at
        # assembler construction: device setup/tuning happens between __init__
        # and the producer thread's first push, and counting that dead time as
        # lost stream falsely tanks the ratio (see docs/design/antsdr-backend.md).
        self._first_push_ts: Optional[float] = None
        # Trailing-window rate baseline: (ts, cumulative _pushed_samples) snapshots,
        # pruned to keep roughly the last ``rate_window_s`` seconds. A PURE
        # lifetime-since-first-push average (the previous implementation) never
        # recovers from a one-time startup transient (kernel-buffer priming, a
        # slow first refill, ...): a single early stall permanently drags the
        # ratio for the rest of an hours-long capture because the deficit is
        # divided by ever-growing total elapsed time (see
        # docs/design/antsdr-backend.md "Measured host-path throughput"). Once
        # enough stream has been seen, the ratio is computed over this trailing
        # window instead so it reflects *current* health and self-heals after a
        # transient, while still falling back to the lifetime average during
        # the first ``rate_window_s`` seconds (too little data for a windowed
        # estimate to be meaningful).
        self.rate_window_s = float(rate_window_s)
        self._rate_hist: "deque[tuple[float, int]]" = deque()

    # --- producer side -------------------------------------------------------
    def push(self, chunk: np.ndarray, ts: float, center_freq_hz: float, *,
              dropped_before: Optional[int] = 0, device_time_ns: Optional[int] = None,
              raw_stats: Optional[tuple[int, float, int]] = None) -> None:
        """Hand off one chunk. Called from the producer thread; must be cheap.

        ``chunk`` is a ``complex64`` ndarray if this assembler has no
        ``raw_to_iq``, otherwise the raw interleaved I,Q ndarray (any dtype)
        the producer received -- conversion happens later, in the consumer.
        ``dropped_before``: samples known lost immediately before this chunk
        (``0`` = contiguous with the previous one), or ``None`` if the
        producer knows a gap occurred but cannot size it.
        ``raw_stats``: ``(clip_count, peak_abs, sample_count)`` from
        ``raw_clip_stats(chunk, full_scale)`` if the caller already computed
        it; otherwise, when this assembler has a ``raw_full_scale`` and
        ``chunk`` is raw ints (``raw_to_iq`` configured), it is computed here
        automatically. ``None`` on both counts means this window's clip
        health is honestly unknown, never a fabricated 0.
        """
        if chunk.size == 0:
            return
        if raw_stats is None and self._raw_full_scale is not None and self._raw_to_iq is not None:
            raw_stats = raw_clip_stats(chunk, self._raw_full_scale)
        item = _Chunk(raw=chunk, ts=ts, center_freq_hz=float(center_freq_hz),
                      dropped_before=dropped_before, device_time_ns=device_time_ns,
                      raw_stats=raw_stats)
        with self._lock:
            if self._first_push_ts is None:
                self._first_push_ts = ts
            self._pushed_samples += item.sample_count(self._raw_to_iq)
            self._rate_hist.append((ts, self._pushed_samples))
            # Keep one entry at/just-before the window boundary as the baseline
            # anchor, plus everything inside the window -- not just everything
            # inside it -- so the windowed estimate always spans >= rate_window_s.
            while len(self._rate_hist) > 1 and ts - self._rate_hist[1][0] >= self.rate_window_s:
                self._rate_hist.popleft()
        try:
            self._q.put_nowait(item)
        except queue.Full:
            # Drop the OLDEST item, not this one: the queue then always holds
            # the most recent, mutually contiguous stretch of stream.
            with self._lock:
                self.overflow_count += 1
            try:
                evicted = self._q.get_nowait()
            except queue.Empty:
                evicted = None
            if evicted is not None:
                if evicted.dropped_before is None or item.dropped_before is None:
                    item.dropped_before = None
                else:
                    item.dropped_before = (evicted.dropped_before
                                            + evicted.sample_count(self._raw_to_iq)
                                            + item.dropped_before)
            try:
                self._q.put_nowait(item)
            except queue.Full:
                pass

    def mark_stopped(self) -> None:
        """Producer signals the stream has ended; wakes any blocked reader."""
        self._stopped.set()

    def flush(self) -> None:
        """Discard buffered/leftover data (e.g. immediately after a retune).

        Every discarded sample is counted in ``tail_discarded_samples`` -- this
        is data that will never appear in any window, as distinct from
        ``dropped_samples`` (loss the assembler detected *while* filling a
        window) or ``overflow_count`` (queue-full evictions during push()).
        """
        with self._lock:
            if self._leftover is not None:
                self.tail_discarded_samples += self._leftover.sample_count(self._raw_to_iq)
            self._leftover = None
        while True:
            try:
                c = self._q.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self.tail_discarded_samples += c.sample_count(self._raw_to_iq)

    # --- consumer side ---------------------------------------------------
    def read_window(self, n_samples: int, timeout_s: Optional[float] = None):
        """Assemble exactly ``n_samples`` complex64 samples from the stream.

        Returns ``(iq, info)``, or ``None`` if the stream stopped before
        ``n_samples`` could be assembled. ``info`` carries capture health:
        completeness, dropped samples (honest ``None`` when unknowable),
        overflow/gap counters, stream-rate ratio, and the generalized
        ``channel_id`` / ``bandwidth_hz`` / ``timing`` fields.
        """
        deadline = time.time() + (timeout_s if timeout_s is not None
                                   else 3.0 * n_samples / self.sample_rate + 1.0)
        want = n_samples if self._raw_to_iq is None else n_samples * _RAW_UNITS_PER_SAMPLE
        parts: list[np.ndarray] = []
        piece_stats: list[Optional[tuple[int, float, int]]] = []  # one entry per
                                # piece in ``parts``, from that piece's ``_Chunk.raw_stats``
        have = 0
        t_first: Optional[float] = None
        center: Optional[float] = None
        device_time_ns: Optional[int] = None
        known_gap = 0           # known-exact dropped samples INSIDE this window
        unknown_gap = False     # an unquantifiable gap boundary fell inside this window
        gap_before = 0          # known loss between the previous window and this one

        with self._lock:
            if self._leftover is not None:
                left = self._leftover
                self._leftover = None
            else:
                left = None
        # ``last_piece``/``last_piece_start_ts`` track whichever chunk (the
        # carried-over leftover, or the most recently popped queue chunk)
        # currently forms the TAIL of ``parts`` -- only that piece can end up
        # split across this window and the next window's leftover, so it is
        # the only one whose start time we need to remember.
        last_piece: Optional[_Chunk] = None
        last_piece_start_ts: Optional[float] = None

        if left is not None:
            parts.append(left.raw)
            piece_stats.append(left.raw_stats)
            have = left.raw.size
            # ``left.ts`` already IS the exact first-sample host time of this
            # leftover (by construction below), not a chunk-arrival time.
            t_first = left.ts
            center = left.center_freq_hz
            device_time_ns = left.device_time_ns
            last_piece = left
            last_piece_start_ts = left.ts

        first_pull = have == 0
        while have < want:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                c = self._q.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if not self._still_active():
                    return None
                continue
            start_ts = c.start_ts(self._raw_to_iq, self.sample_rate)
            if first_pull:
                # Gap between the end of the previous window and the start of
                # this one: not a hole INSIDE this window, but worth reporting.
                gap_before = c.dropped_before if c.dropped_before is not None else 0
                t_first = start_ts
                center = c.center_freq_hz
                device_time_ns = c.device_time_ns
                first_pull = False
            else:
                if c.dropped_before is None:
                    unknown_gap = True
                else:
                    known_gap += c.dropped_before
            parts.append(c.raw)
            piece_stats.append(c.raw_stats)
            have += c.raw.size
            last_piece = c
            last_piece_start_ts = start_ts

        buf = np.concatenate(parts) if parts else np.zeros(0, dtype=(np.complex64 if self._raw_to_iq is None else np.int8))
        if buf.size > want:
            overflow = buf.size - want           # raw units spilling into the next window
            raw_per_sample = 1 if self._raw_to_iq is None else _RAW_UNITS_PER_SAMPLE
            leftover_stats: Optional[tuple[int, float, int]] = None
            if last_piece is not None and last_piece_start_ts is not None:
                consumed = last_piece.raw.size - overflow   # raw units of last_piece kept here
                leftover_ts = last_piece_start_ts + (consumed / raw_per_sample) / self.sample_rate
                # The last piece straddles this window boundary: its whole-chunk
                # ``raw_stats`` (if any) belongs partly here, partly to the
                # leftover carried into the next window. Re-split it exactly
                # (cheap: it's the same data already in hand, one extra pass
                # only on this boundary chunk) rather than double-counting it
                # in both windows or discarding it from the leftover entirely.
                if piece_stats and piece_stats[-1] is not None and self._raw_full_scale is not None:
                    kept_raw = last_piece.raw[:consumed]
                    tail_raw = last_piece.raw[consumed:]
                    piece_stats[-1] = raw_clip_stats(kept_raw, self._raw_full_scale)
                    leftover_stats = raw_clip_stats(tail_raw, self._raw_full_scale)
            else:
                leftover_ts = t_first or time.time()
            with self._lock:
                self._leftover = _Chunk(raw=buf[want:].copy(), ts=leftover_ts,
                                        center_freq_hz=center or 0.0, dropped_before=0,
                                        device_time_ns=device_time_ns, raw_stats=leftover_stats)
            buf = buf[:want]

        iq = self._raw_to_iq(buf) if self._raw_to_iq is not None else buf
        if iq.dtype != np.complex64:
            iq = iq.astype(np.complex64)

        short = iq.size < n_samples
        if short:
            with self._lock:
                self.short_reads += 1
        with self._lock:
            self.total_samples += iq.size
            self._running_sample_index += iq.size

        if not self.reports_drops:
            dropped_samples: Optional[int] = None
            loss_detection = "inferred_rate_only"
            complete = not short
        elif unknown_gap:
            dropped_samples = None
            loss_detection = "unknown_gap"
            complete = False
        else:
            dropped_samples = known_gap + max(0, n_samples - iq.size)
            loss_detection = "exact"
            complete = known_gap == 0 and not short

        now = time.time()
        with self._lock:
            first_push_ts = self._first_push_ts
            pushed_samples = self._pushed_samples
            baseline = self._rate_hist[0] if self._rate_hist else None

        # ``stream_rate_ratio`` is now CUMULATIVE since the first pushed chunk
        # (samples pushed / (elapsed x Fs)) -- deliberately NOT a trailing
        # window. A per-window trailing-window estimate is noisy by
        # construction: window boundaries, GC pauses, and normal scheduling
        # jitter move a handful of milliseconds of "recent" data in or out of
        # a short window, so the ratio swings +/-5-10% window to window even
        # with zero real loss (see docs/design/antsdr-backend.md "Measured
        # host-path throughput (2026-09-18)": 0.96-1.08 jitter and false
        # warnings on ~55/60 loss-free windows). The cumulative average has no
        # such noise floor and turns a real 5% loss over 10 minutes into a
        # small, honest, monotonically-informative ``samples_deficit`` sample
        # count instead of alarm-fatigue noise. ``stream_rate_ratio_recent``
        # (the old trailing-``rate_window_s`` estimate) is still reported
        # alongside it for callers that want current-instant health and can
        # tolerate its noise -- e.g. to catch a stream that has actually
        # stopped, which a cumulative average over a long capture would mask
        # for a long time.
        if first_push_ts is None:
            elapsed = 0.0
            ratio = 1.0
            samples_deficit = 0
        else:
            elapsed = now - first_push_ts
            if elapsed > 0.5:
                expected = elapsed * self.sample_rate
                ratio = pushed_samples / expected
                samples_deficit = int(round(expected - pushed_samples))
            else:
                ratio = 1.0
                samples_deficit = 0

        # ``samples_deficit_recent``: the (honest, non-negative) sample deficit
        # accrued strictly WITHIN the trailing ``rate_window_s`` baseline, as
        # opposed to ``samples_deficit`` which is since the first pushed chunk.
        # A caller combines this with ``ratio_recent`` to distinguish "the
        # recent ratio dipped because of ordinary chunk-timing/GC jitter with
        # zero real samples lost" (deficit ~0) from "the recent ratio dipped
        # because the stream is actually behind" (deficit > 0) -- see
        # docs/design/antsdr-backend.md "Measured host-path throughput
        # (2026-09-18)".
        if first_push_ts is None:
            ratio_recent = 1.0
            samples_deficit_recent = 0
        elif baseline is not None and (now - baseline[0]) > 0.5:
            baseline_ts, baseline_samples = baseline
            recent_elapsed = now - baseline_ts
            recent_pushed = pushed_samples - baseline_samples
            ratio_recent = recent_pushed / (recent_elapsed * self.sample_rate)
            samples_deficit_recent = max(0, int(round(recent_elapsed * self.sample_rate - recent_pushed)))
        else:
            ratio_recent = ratio
            samples_deficit_recent = max(0, samples_deficit)

        timing: dict[str, Any] = {"clock_source": "host_wallclock",
                                  "sample_index": self._running_sample_index}
        if device_time_ns is not None:
            timing["clock_source"] = "device"
            timing["device_time_ns"] = int(device_time_ns)

        # Clip/peak health: aggregate the per-piece ``raw_stats`` collected above
        # (see ``raw_clip_stats``). Any piece with unknown stats (``None`` --
        # e.g. this assembler has no ``raw_full_scale``) makes the WHOLE
        # window's clip health honestly unknown rather than partially counted.
        clip_count_sum = 0
        peak_abs_max = 0.0
        raw_n_sum = 0
        stats_known = bool(piece_stats)
        for ps in piece_stats:
            if ps is None:
                stats_known = False
                continue
            cc, pk, ns = ps
            clip_count_sum += cc
            if pk > peak_abs_max:
                peak_abs_max = pk
            raw_n_sum += ns
        if stats_known and raw_n_sum > 0 and self._raw_full_scale is not None:
            clip_fraction: Optional[float] = clip_count_sum / raw_n_sum
            peak_abs_frac: Optional[float] = peak_abs_max / self._raw_full_scale
            clip_warning = clip_fraction > CLIP_WARNING_FRACTION
        else:
            clip_fraction = None
            peak_abs_frac = None
            clip_warning = False

        info = {
            "captured_at": t_first if t_first is not None else time.time(),
            "center_freq_hz": center if center is not None else 0.0,
            "complete": bool(complete),
            "dropped_samples": dropped_samples,
            "overflow_count": int(self.overflow_count),
            "gap_before_samples": int(gap_before),
            "short_reads": int(self.short_reads),
            "stream_rate_ratio": round(float(ratio), 4),
            "stream_rate_ratio_recent": round(float(ratio_recent), 4),
            "stream_rate_elapsed_s": round(float(elapsed), 3),
            "samples_deficit": int(samples_deficit),
            "samples_deficit_recent": int(samples_deficit_recent),
            "loss_detection": loss_detection,
            "channel_id": self.channel_id,
            "bandwidth_hz": self.bandwidth_hz,
            "timing": timing,
            "clip_fraction": clip_fraction,
            "peak_abs_frac": peak_abs_frac,
            "clip_warning": bool(clip_warning),
        }
        return iq, info
