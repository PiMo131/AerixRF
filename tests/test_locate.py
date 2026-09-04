"""The sweep-differential locator finds a newly-hot channel and ignores noise."""

import numpy as np

from aerix_rf.tools import sweep_locate as sl


def _grid(lo=2400.0, hi=2485.0, step=0.5):
    f = np.arange(lo, hi, step)
    return f, np.full(f.size, -70.0)   # flat baseline floor


def test_finds_injected_channel():
    f, base = _grid()
    live = base.copy()
    # A ~10 MHz OcuSync-like bump centred at 2450 MHz, +20 dB.
    live[(f >= 2445) & (f <= 2455)] += 20.0
    hit = sl.hottest_new((f, live), (f, base))
    assert hit is not None
    center, delta, width = hit
    assert 2448 <= center <= 2452
    assert delta >= 15
    assert width >= 8


def test_ignores_flat_and_scattered_noise():
    f, base = _grid()
    rng = np.random.default_rng(0)
    live = base + rng.normal(0, 1.5, f.size)     # jitter, no real signal
    assert sl.hottest_new((f, live), (f, base)) is None


def test_parse_sweep_csv(tmp_path):
    p = tmp_path / "s.csv"
    # date,time,hz_low,hz_high,bin_width,num_samples, then dB bins
    p.write_text("2026-09-04,12:00:00,2400000000,2405000000,1000000,8192,-70,-68,-66,-64,-62\n")
    f, pw = sl.parse_sweep_csv(str(p))
    assert f.size == 5
    assert abs(f[0] - 2400.5) < 0.01     # first bin centre in MHz
    assert pw[-1] == -62
