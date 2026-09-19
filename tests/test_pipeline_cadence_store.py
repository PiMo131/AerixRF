"""Tests for aerix_rf.pipeline.SessionCadenceStore -- the bounded rolling
multi-window BurstEvent pool that backs session-level R3 cadence evidence
(docs/design/stage1-link-signatures.md S4) and forwards ``frame_dt_s`` to
``period_test``'s C1 sub-frame dt-filter across window boundaries
(independent review fix 2026-09-19 #2a).
"""

from __future__ import annotations

import numpy as np

from aerix_rf.detect.bursts import BurstEvent
from aerix_rf.pipeline import SessionCadenceStore


def _ev(t_start: float, dur_s: float, centre_hz: float, bw_hz: float) -> BurstEvent:
    return BurstEvent(
        t_start=t_start, t_end=t_start + dur_s, duration_s=dur_s,
        centre_hz=centre_hz, bw_6db_hz=bw_hz,
        peak_db_over_floor=20.0, mean_db_over_floor=15.0, n_frames=3,
        edge_clipped=False,
    )


def test_session_cadence_store_cotemporal_pairs_across_windows_not_periodic():
    """Two windows, each contributing co-temporal (dt~=0) burst pairs at two
    different centres on irregular (non-periodic) ticks -- the same
    degenerate pattern ``test_c1_cotemporal_trains_do_not_alias_to_range_top``
    guards against within one window, but here split across two ``add()``
    calls with a real ``frame_dt_s``. The pooled, session-level period result
    must not report a spurious period: the dt-filter should drop the
    co-temporal pairs, and the remaining (irregular) inter-tick gaps must not
    concentrate."""
    rng = np.random.default_rng(42)

    def _window_events(n: int) -> list[BurstEvent]:
        ticks = sorted(rng.uniform(0.0, 1.0, size=n))
        out = []
        for t in ticks:
            out.append(_ev(float(t), 0.5e-3, 2400.0e6, 0.3e6))
            out.append(_ev(float(t), 0.5e-3, 2450.0e6, 0.3e6))
        return out

    store = SessionCadenceStore()
    store.add(_window_events(20), captured_at=0.0, frame_dt_s=250e-6)
    store.add(_window_events(20), captured_at=2.0, frame_dt_s=250e-6)

    assert store.frame_dt_s == 250e-6   # max-over-windows forwarding (#2a)

    result = store.result()
    assert result is not None
    assert result.period.passed is False


def test_session_cadence_store_pools_genuine_640ms_cadence_across_windows():
    """A genuinely periodic ~640 ms-cadence link, sampled a few bursts per
    window (as a single 1 s window structurally cannot see >=5 events
    spanning >=3 s -- design S1), must be recoverable once pooled across
    windows in absolute (session) time. Exercises the real
    ``SessionCadenceStore.add()``/``result()`` API, not the module function
    directly."""
    rng = np.random.default_rng(7)
    period_s = 0.640
    n_events = 16
    jitter_s = 0.005   # 5 ms jitter, well under the period

    global_times = [i * period_s + float(rng.normal(0.0, jitter_s)) for i in range(n_events)]

    store = SessionCadenceStore(window_s=12.0)   # span (~9.6 s) fits with margin
    events_per_window = 4
    for w in range(0, n_events, events_per_window):
        chunk = global_times[w:w + events_per_window]
        captured_at = chunk[0]
        local_events = [_ev(t - captured_at, 0.5e-3, 2440.0e6, 0.3e6) for t in chunk]
        store.add(local_events, captured_at=captured_at, frame_dt_s=250e-6)

    result = store.result()
    assert result is not None
    assert result.period.passed is True
    assert result.period.t_hat_s is not None
    assert abs(result.period.t_hat_s - period_s) / period_s <= 0.05
