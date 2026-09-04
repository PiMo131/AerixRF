"""Scan-and-lock library: band presets, multi-sweep parsing, candidate ranking.

Pure numpy / synthetic data -- no HackRF needed.
"""

import numpy as np
import pytest

from aerix_rf.scan import (
    BANDS,
    Baseline,
    average_db,
    load_baseline,
    parse_sweep_csv_multi,
    rank_candidates,
    resolve_band,
    save_baseline,
    summarize,
    to_dict,
)

LO, HI, STEP = 2400.0, 2500.0, 0.5
N_SWEEPS = 20
FLOOR = -70.0


def _grid():
    return np.arange(LO, HI, STEP) + STEP / 2      # bin centres


def _matrix(seed=0, jitter=1.5):
    rng = np.random.default_rng(seed)
    f = _grid()
    m = FLOOR + rng.normal(0, jitter, (N_SWEEPS, f.size))
    return f, m


def _bump(m, f, center, width, db=20.0, sweeps=None):
    sel = (f >= center - width / 2) & (f < center + width / 2)
    rows = range(m.shape[0]) if sweeps is None else sweeps
    for r in rows:
        m[r, sel] += db


def _baseline(f):
    return Baseline(lo_mhz=LO, hi_mhz=HI, bin_hz=STEP * 1e6, freqs_mhz=f,
                    power_db=np.full(f.size, FLOOR), n_sweeps=100, dwell_s=2.0)


def _near(cands, center, tol=2.0):
    hits = [c for c in cands if abs(c.center_mhz - center) <= tol]
    assert hits, f"no candidate near {center}: {[c.center_mhz for c in cands]}"
    return hits[0]


# --------------------------------------------------------------------------- #
# (a) persistent Wi-Fi + intermittent link, with baseline
# --------------------------------------------------------------------------- #

def test_persistent_and_intermittent_candidates():
    f, m = _matrix()
    _bump(m, f, 2437, 20)                                    # Wi-Fi, every sweep
    burst_sweeps = [1, 4, 6, 9, 11, 14, 16, 19]              # 8/20 = 40 %
    _bump(m, f, 2460, 10, sweeps=burst_sweeps)
    cands = rank_candidates(f, m, _baseline(f))
    assert len(cands) == 2
    wifi = _near(cands, 2437)
    link = _near(cands, 2460)

    assert abs(wifi.width_mhz - 20) <= 2
    assert abs(link.width_mhz - 10) <= 2
    assert wifi.persistence == pytest.approx(1.0)
    assert link.persistence == pytest.approx(0.4, abs=0.05)
    assert link.burstiness > wifi.burstiness + 3
    assert wifi.delta_db == pytest.approx(20, abs=3)
    assert link.mean_delta_db == pytest.approx(20, abs=3)
    assert not wifi.hopping and not link.hopping
    assert wifi.lo_mhz == pytest.approx(2427, abs=1.5)
    assert wifi.hi_mhz == pytest.approx(2447, abs=1.5)
    # documented default weighting: a bursty link outranks an always-on AP
    assert link.rank == 1 and wifi.rank == 2
    assert 0 < wifi.score < link.score <= 1
    assert cands[0].rank == 1 and cands[1].rank == 2

    d = to_dict(cands)
    assert isinstance(d, list) and d[0]["center_mhz"] == cands[0].center_mhz
    assert isinstance(d[0]["hop_channels_mhz"], list)
    txt = summarize(cands)
    assert f"{wifi.center_mhz:.1f}" in txt and f"{link.center_mhz:.1f}" in txt
    assert "score" in txt and len(txt.splitlines()) == 5      # header, rule, 2 rows, legend


def test_baseline_as_tuple_and_different_grid():
    f, m = _matrix()
    _bump(m, f, 2437, 20)
    coarse = np.arange(LO, HI + 1, 5.0)                       # baseline on 5 MHz grid
    cands = rank_candidates(f, m, (coarse, np.full(coarse.size, FLOOR)))
    assert len(cands) == 1 and abs(cands[0].center_mhz - 2437) < 2


# --------------------------------------------------------------------------- #
# (b) hopping
# --------------------------------------------------------------------------- #

def test_hopping_signal_is_flagged_and_merged():
    f, m = _matrix()
    chans = [2410, 2430, 2450, 2470]
    for k in range(N_SWEEPS):
        _bump(m, f, chans[k % 4], 10, sweeps=[k])
    cands = rank_candidates(f, m, _baseline(f))
    assert len(cands) == 1, summarize(cands)
    c = cands[0]
    assert c.hopping
    assert c.hop_score > 0.9
    assert len(c.hop_channels_mhz) == 4
    assert all(any(abs(h - x) < 2 for x in chans) for h in c.hop_channels_mhz)
    assert c.persistence == pytest.approx(1.0)
    assert abs(c.width_mhz - 10) <= 2                     # per-dwell width
    assert c.lo_mhz <= 2406 and c.hi_mhz >= 2474           # hop span
    assert c.center_mhz in [pytest.approx(x, abs=2) for x in chans]
    assert "hops over" in summarize(cands)


def test_random_hopping_is_flagged():
    rng = np.random.default_rng(7)
    f, m = _matrix(seed=3)
    m = np.vstack([m, m])                                   # 40 sweeps
    chans = [2410, 2430, 2450, 2470]
    for k in range(m.shape[0]):
        _bump(m, f, chans[rng.integers(4)], 10, sweeps=[k])
    cands = rank_candidates(f, m, _baseline(f))
    assert any(c.hopping and len(c.hop_channels_mhz) >= 3 for c in cands), summarize(cands)


def test_two_independent_persistent_signals_are_not_a_hop_group():
    f, m = _matrix()
    _bump(m, f, 2412, 20)
    _bump(m, f, 2462, 20)
    cands = rank_candidates(f, m, _baseline(f))
    assert len(cands) == 2 and not any(c.hopping for c in cands)


# --------------------------------------------------------------------------- #
# (c) self-baseline, (d) noise only
# --------------------------------------------------------------------------- #

def test_self_baseline_finds_intermittent_signal():
    f, m = _matrix()
    _bump(m, f, 2437, 20)
    _bump(m, f, 2460, 10, sweeps=[1, 4, 6, 9, 11, 14, 16, 19])
    cands = rank_candidates(f, m, None)
    link = _near(cands, 2460)
    assert link.persistence == pytest.approx(0.4, abs=0.05)
    assert abs(link.width_mhz - 10) <= 2


def test_pure_jitter_yields_nothing():
    f, m = _matrix(seed=42)
    assert rank_candidates(f, m, _baseline(f)) == []
    assert rank_candidates(f, m, None) == []
    assert summarize([]).startswith("(no candidates")


def test_max_candidates_and_frame_averaging():
    f, m = _matrix()
    m = np.vstack([m] * 10)                                  # 200 sweeps -> auto frames
    for c in (2405, 2420, 2435, 2450, 2465, 2480, 2495):
        _bump(m, f, c, 6)
    cands = rank_candidates(f, m, _baseline(f), max_candidates=3)
    assert len(cands) == 3 and [c.rank for c in cands] == [1, 2, 3]
    assert cands[0].n_frames == 50
    assert rank_candidates(f, m[:5], _baseline(f), frame_sweeps=5)[0].n_frames == 1


def test_empty_and_degenerate_inputs():
    f = _grid()
    assert rank_candidates(f, np.zeros((0, f.size)), None) == []
    assert rank_candidates(f[:1], np.zeros((3, 1)), None) == []


# --------------------------------------------------------------------------- #
# (e) bands
# --------------------------------------------------------------------------- #

def test_resolve_band():
    assert resolve_band("2.4") == BANDS["2.4"] == (2400.0, 2500.0)
    assert resolve_band("5.8") == (5725.0, 5875.0)
    assert resolve_band("5.2") == (5150.0, 5350.0)
    assert resolve_band("900") == (900.0, 930.0)
    assert resolve_band("2400:2483.5") == (2400.0, 2483.5)
    assert resolve_band("2400-2483.5") == (2400.0, 2483.5)
    assert resolve_band(" 5725 : 5850 ") == (5725.0, 5850.0)
    for bad in ("", "x", "2500:2400", "2.4:", "1:2:3"):
        with pytest.raises(ValueError):
            resolve_band(bad)


# --------------------------------------------------------------------------- #
# (f) CSV parsing
# --------------------------------------------------------------------------- #

_ROW = "2026-09-04, 12:00:00.0, {lo}, {hi}, 1000000.00, 8, {vals}\n"


def _row(lo_mhz, vals):
    return _ROW.format(lo=int(lo_mhz * 1e6), hi=int((lo_mhz + 5) * 1e6),
                       vals=", ".join(str(v) for v in vals))


def test_parse_sweep_csv_multi_splits_sweeps(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text(
        _row(2400, [-70, -71, -72, -73, -74]) + _row(2405, [-60, -61, -62, -63, -64])
        + _row(2400, [-50, -51, -52, -53, -54]) + _row(2405, [-40, -41, -42, -43, -44])
    )
    f, m = parse_sweep_csv_multi(p)
    assert f.shape == (10,) and m.shape == (2, 10)
    assert f[0] == pytest.approx(2400.5) and f[-1] == pytest.approx(2409.5)
    assert m[0, 0] == -70 and m[0, 5] == -60
    assert m[1, 0] == -50 and m[1, 9] == -44
    avg = average_db(m)
    assert avg[0] == pytest.approx(10 * np.log10((1e-7 + 1e-5) / 2))


def test_parse_sweep_csv_multi_out_of_order_rows_and_partial_tail(tmp_path):
    p = tmp_path / "s.csv"
    # hackrf_sweep order inside a tune step: 2400, 2410, 2405, 2415; then a
    # sweep cut off by the kill -> dropped.
    sweep = lambda base: (_row(2400, [base] * 5) + _row(2410, [base + 2] * 5)
                          + _row(2405, [base + 1] * 5) + _row(2415, [base + 3] * 5))
    p.write_text(sweep(-70) + sweep(-60) + _row(2400, [-1] * 5) + _row(2410, [-1] * 5))
    f, m = parse_sweep_csv_multi(p)
    assert m.shape == (2, 20)
    assert list(m[0, ::5]) == [-70, -69, -68, -67]        # re-ordered by frequency
    assert list(m[1, ::5]) == [-60, -59, -58, -57]
    assert not np.isnan(m).any()


def test_parse_sweep_csv_multi_empty(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("")
    f, m = parse_sweep_csv_multi(p)
    assert f.size == 0 and m.shape == (0, 0)


def test_save_load_baseline_roundtrip(tmp_path):
    f = _grid()
    b = Baseline(lo_mhz=LO, hi_mhz=HI, bin_hz=STEP * 1e6, freqs_mhz=f,
                 power_db=FLOOR + np.sin(f), n_sweeps=123, dwell_s=2.5,
                 recorded_at="2026-09-04T12:00:00+00:00", gains={"lna": 16, "vga": 24, "amp": False})
    path = save_baseline(b, tmp_path / "site-baseline")
    assert path.suffix == ".npz" and path.exists()
    b2 = load_baseline(tmp_path / "site-baseline")       # without suffix
    b3 = load_baseline(path)                             # with suffix
    for x in (b2, b3):
        assert (x.lo_mhz, x.hi_mhz, x.bin_hz, x.n_sweeps, x.dwell_s) == (LO, HI, STEP * 1e6, 123, 2.5)
        assert x.recorded_at == b.recorded_at and x.gains == b.gains
        np.testing.assert_allclose(x.freqs_mhz, f)
        np.testing.assert_allclose(x.power_db, b.power_db)
    assert b2.interp(np.array([2450.0]))[0] == pytest.approx(FLOOR + np.sin(2450.0), abs=0.05)
    assert abs(b2.floor_db - FLOOR) < 1
