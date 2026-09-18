"""Tests for aerix_rf.datasets.window (Workstream D, T3 -- S3 fixed windowing)."""

from __future__ import annotations

import numpy as np

from aerix_rf.datasets.window import iter_windows, n_expected_windows

FS = 15_360_000.0  # canonical rate


def test_one_exact_second_yields_single_non_short_window():
    n = int(FS)  # exactly 1.000 s
    iq = np.zeros(n, dtype=np.complex64)
    windows = list(iter_windows(iq, FS))
    assert len(windows) == 1
    start, w, short = windows[0]
    assert start == 0
    assert w.shape[-1] == 15_360_000
    assert short is False
    assert n_expected_windows(n, FS) == 1


def test_quarter_second_yields_single_short_window():
    n = int(round(0.25 * FS))  # 3,840,000
    iq = np.zeros(n, dtype=np.complex64)
    windows = list(iter_windows(iq, FS))
    assert len(windows) == 1
    start, w, short = windows[0]
    assert start == 0
    assert w.shape[-1] == n
    assert short is True
    assert n_expected_windows(n, FS) == 1


def test_1_7s_yields_one_full_and_one_short_window_on_grid():
    n = int(round(1.7 * FS))  # 26,112,000
    iq = np.zeros(n, dtype=np.complex64)
    windows = list(iter_windows(iq, FS))
    assert len(windows) == 2

    start0, w0, short0 = windows[0]
    assert start0 == 0
    assert w0.shape[-1] == 15_360_000
    assert short0 is False

    start1, w1, short1 = windows[1]
    # Second window starts exactly at the 1.000 s grid boundary.
    assert start1 == 15_360_000
    assert w1.shape[-1] == n - 15_360_000
    assert short1 is True

    assert n_expected_windows(n, FS) == 2


def test_trailing_partial_ms_is_dropped_not_fabricated():
    # One full 1.000 s window plus 10.5 grid-ms worth of samples: the
    # trailing 0.5 ms cannot form a whole 1 ms-grid step and must be
    # dropped, not padded into a visible short window.
    grid_step = 15360  # samples per ms at FS
    n = 15_360_000 + 10 * grid_step + grid_step // 2
    iq = np.zeros(n, dtype=np.complex64)
    windows = list(iter_windows(iq, FS))
    assert len(windows) == 2
    start1, w1, short1 = windows[1]
    assert start1 == 15_360_000
    assert w1.shape[-1] == 10 * grid_step  # half-ms remainder dropped
    assert short1 is True


def test_source_shorter_than_one_grid_step_yields_no_windows():
    iq = np.zeros(100, dtype=np.complex64)  # << 15360 samples/ms at FS
    assert list(iter_windows(iq, FS)) == []
    assert n_expected_windows(100, FS) == 0


def test_start_sample_and_short_flag_match_across_iter_and_count():
    n = int(round(2.5 * FS))
    iq = np.arange(n, dtype=np.complex64)
    windows = list(iter_windows(iq, FS))
    assert n_expected_windows(n, FS) == len(windows)
    assert [w[0] for w in windows] == [0, 15_360_000, 30_720_000]
    assert [w[2] for w in windows] == [False, False, True]
