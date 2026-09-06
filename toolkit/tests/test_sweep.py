"""Tests for antsdr_toolkit.scan.sweep (Sweeper, analyse_dwell, OccupancyMap) and cli_sweep."""

from __future__ import annotations

import argparse
import json
import types

import numpy as np
import pytest

from antsdr_toolkit import cli_sweep
from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.device.base import SampleSource, StreamInfo
from antsdr_toolkit.device.file_source import SigmfFileSource
from antsdr_toolkit.io.sigmf_io import write_sigmf
from antsdr_toolkit.scan import sweep as sw
from antsdr_toolkit.scan.planner import Dwell, plan_dwells

FS = 20e6
FC = 2.44e9
DJI_OFFSET = 4e6
DJI_BW = 9e6
DJI_PERIOD = 6e-3
DJI_DURATION = 0.64e-3
FHSS_CHANNELS = [-6.5e6, -5.5e6, -4.5e6, -3.5e6]


# --------------------------------------------------------------------------- fixtures


def _busy_scene(seed: int = 3, duration_s: float = 60e-3) -> syn.Scene:
    """DJI-like 9 MHz burst train at +4 MHz plus a 4-channel GFSK FHSS train below DC."""
    rng = np.random.default_rng(seed)
    scene = syn.Scene(FS, FC, duration_s, rng, noise_power_db=-60.0)
    t = 1e-3
    while t + DJI_DURATION <= duration_s:
        burst = syn.bandlimited_noise_burst(FS, DJI_BW, DJI_DURATION, rng)
        scene.add(burst, t_start_s=t, freq_offset_hz=DJI_OFFSET, snr_db=25.0, label="dji",
                  bandwidth_hz=DJI_BW)
        t += DJI_PERIOD
    scene.fhss(
        lambda d: syn.gfsk_burst(FS, 100e3, round(d * 100e3), rng),
        channels_hz=FHSS_CHANNELS, hop_rate_hz=500.0, burst_duration_s=1.5e-3,
        t_start_s=0.0, t_end_s=duration_s, snr_db=20.0, label="fhss", order="sequential",
    )
    return scene


@pytest.fixture(scope="module")
def busy_result() -> sw.DwellResult:
    scene = _busy_scene()
    with syn.SyntheticSource.from_scene(scene) as src:
        sweeper = sw.Sweeper(src, dwell_s=60e-3)
        assert sweeper.fixed_tuning
        results = sweeper.run_once()
    assert len(results) == 1
    return results[0]


@pytest.fixture(scope="module")
def noise_result() -> sw.DwellResult:
    scene = syn.Scene(FS, FC, 60e-3, np.random.default_rng(5), noise_power_db=-60.0)
    with syn.SyntheticSource.from_scene(scene) as src:
        return sw.Sweeper(src, dwell_s=60e-3).run_once()[0]


class TunableFake(SampleSource):
    """Retunable source replaying one looping buffer per centre frequency."""

    def __init__(self, buffers: dict[float, np.ndarray], sample_rate_hz: float) -> None:
        self._buffers = {float(k): np.asarray(v, dtype=np.complex64) for k, v in buffers.items()}
        self._center = next(iter(self._buffers))
        self._fs = float(sample_rate_hz)
        self._pos = 0
        self.retunes: list[float] = []
        self.reads: list[int] = []

    @property
    def info(self) -> StreamInfo:
        return StreamInfo(self._fs, self._center, hardware="antsdr-e200")

    def retune(self, center_freq_hz: float) -> None:
        if float(center_freq_hz) not in self._buffers:
            raise ValueError(f"no scene at {center_freq_hz}")
        self.retunes.append(float(center_freq_hz))
        self._center = float(center_freq_hz)
        self._pos = 0

    def read(self, n_samples: int) -> np.ndarray:
        buf = self._buffers[self._center]
        idx = (np.arange(self._pos, self._pos + n_samples) % len(buf)).astype(np.intp)
        self._pos = (self._pos + n_samples) % len(buf)
        self.reads.append(int(n_samples))
        return buf[idx]


def _two_sector_source(fs: float = 4e6) -> tuple[TunableFake, float, float]:
    # 100 ms of scene: the sweeper discards two dwell-length buffers before it
    # keeps one, so the captured window starts well inside the recording and
    # the test does not depend on TunableFake wrapping around.
    quiet_fc, busy_fc = 2.41e9, 2.45e9
    quiet = syn.Scene(fs, quiet_fc, 100e-3, np.random.default_rng(1), noise_power_db=-60.0)
    busy = syn.Scene(fs, busy_fc, 100e-3, np.random.default_rng(2), noise_power_db=-60.0)
    rng = np.random.default_rng(9)
    for k in range(19):  # a 1 ms burst every 5 ms from t = 2 ms
        burst = syn.bandlimited_noise_burst(fs, 1e6, 1e-3, rng)
        busy.add(burst, t_start_s=2e-3 + k * 5e-3, freq_offset_hz=0.8e6, snr_db=20.0,
                 label="b", bandwidth_hz=1e6)
    src = TunableFake({quiet_fc: quiet.render(), busy_fc: busy.render()}, fs)
    return src, quiet_fc, busy_fc


# --------------------------------------------------------------------------- primitives


def test_kurtosis_reference_values():
    rng = np.random.default_rng(0)
    noise = syn.awgn(200_000, rng)
    assert sw.kurtosis(noise) == pytest.approx(sw.KAPPA_GAUSSIAN, abs=0.05)
    tone = np.exp(2j * np.pi * 0.01 * np.arange(10_000)).astype(np.complex64)
    assert sw.kurtosis(tone) == pytest.approx(1.0, abs=1e-3)
    gated = noise.copy()
    gated[60_000:] = 0.0  # 30 % duty -> kappa ~ 2 / 0.3
    assert sw.kurtosis(gated) == pytest.approx(2.0 / 0.3, rel=0.05)
    assert sw.kurtosis(np.zeros(100, np.complex64)) == sw.KURTOSIS_CAP
    assert sw.kurtosis(gated, cap=4.0) == 4.0
    # a DC offset does not count as signal: de-meaned first
    assert sw.kurtosis(noise + 3.0) == pytest.approx(2.0, abs=0.05)
    # multi-channel input averages the channels
    both = np.stack([noise, tone[:200_000] if len(tone) >= 200_000 else np.resize(tone, 200_000)])
    assert sw.kurtosis(both) == pytest.approx(1.5, abs=0.05)
    with pytest.raises(ValueError):
        sw.kurtosis(np.zeros(0, np.complex64))


def test_occupancy_from_psd_notch_gap_and_min_bins():
    rng = np.random.default_rng(1)
    n, df = 256, 1e4
    freqs = FC + (np.arange(n) - n // 2) * df
    psd = -80.0 + 0.2 * rng.standard_normal(n)
    psd[40:61] += 20.0  # a 21-bin signal ...
    psd[50:53] -= 20.0  # ... with a 3-bin OFDM-like null to bridge
    psd[n // 2 - 2 : n // 2 + 3] += 30.0  # LO leak in the 5 centre bins
    psd[200] += 15.0  # a lone spur bin
    floor, segs, mask = sw.occupancy_from_psd(
        freqs, psd, threshold_db=6.0, center_freq_hz=FC, dc_notch_bins=5, max_gap_hz=5 * df,
        min_bins=3,
    )
    assert floor == pytest.approx(-80.0, abs=0.5)
    assert len(segs) == 1
    seg = segs[0]
    assert seg.f_low_hz == pytest.approx(freqs[40] - df / 2)
    assert seg.f_high_hz == pytest.approx(freqs[60] + df / 2)
    assert seg.bandwidth_hz == pytest.approx(21 * df)
    assert seg.snr_db == pytest.approx(20.0, abs=1.0)
    assert seg.peak_db == pytest.approx(seg.snr_db + floor)
    f_low, f_high, peak, snr = seg  # tuple unpacking as promised
    assert (f_low, f_high, peak, snr) == tuple(seg)
    assert seg.to_dict()["center_freq_hz"] == pytest.approx(seg.center_freq_hz)
    assert mask[40:61].all() and not mask[n // 2] and not mask[200]
    # with a smaller bridge the null splits the signal in two
    _, split, _ = sw.occupancy_from_psd(freqs, psd, center_freq_hz=FC, max_gap_hz=df, min_bins=3)
    assert len(split) == 2
    # a signal straddling DC survives the notch because the gap bridge is at least the notch
    psd2 = -80.0 + 0.2 * rng.standard_normal(n)
    psd2[n // 2 - 20 : n // 2 + 20] += 20.0
    _, straddle, _ = sw.occupancy_from_psd(freqs, psd2, center_freq_hz=FC, max_gap_hz=df)
    assert len(straddle) == 1 and straddle[0].bandwidth_hz == pytest.approx(40 * df)
    assert sw.occupancy_from_psd(np.zeros(0), np.zeros(0))[1] == []
    with pytest.raises(ValueError):
        sw.occupancy_from_psd(freqs, psd[:-1])


def test_activity_score_monotone_and_zero_for_noise():
    assert sw.activity_score(0.0, 0.0, 2.0) == 0.0
    assert sw.activity_score(-1.0, -3.0, 1.0) == 0.0  # negative excess clamps to 0
    base = sw.activity_score(3.0, 10.0, 2.0)
    assert base == pytest.approx(8.0)
    assert sw.activity_score(3.0, 10.0, 6.0) == pytest.approx(8.0 * (1 + 0.4 * 4 / 2))
    assert sw.activity_score(6.0, 10.0, 2.0) > base
    assert sw.activity_score(3.0, 20.0, 2.0) > base


# --------------------------------------------------------------------------- fixed sources


def test_busy_scene_occupancy_lands_in_the_right_sub_bands(busy_result):
    r = busy_result
    assert r.center_freq_hz == FC and r.sample_rate_hz == FS
    assert r.span_hz == pytest.approx(0.8 * FS)
    assert r.n_samples == round(60e-3 * FS) and r.duration_s == pytest.approx(60e-3)
    assert r.freqs_hz.min() >= r.f_low_hz - 1.0 and r.freqs_hz.max() <= r.f_high_hz + 1.0
    assert np.all(np.diff(r.freqs_hz) > 0) and r.freqs_hz.shape == r.psd_db.shape
    assert r.targets == ()

    segs = r.occupancy
    assert 5 <= len(segs) <= 7  # 4 FHSS channels + the DJI band (a split or two tolerated)
    dji = [s for s in segs if s.f_low_hz <= FC + DJI_OFFSET <= s.f_high_hz]
    assert len(dji) == 1
    assert 8e6 <= dji[0].bandwidth_hz <= 10.5e6
    assert dji[0].center_freq_hz == pytest.approx(FC + DJI_OFFSET, abs=0.3e6)
    assert dji[0].snr_db > 10.0
    for off in FHSS_CHANNELS:
        hits = [s for s in segs if s.f_low_hz <= FC + off <= s.f_high_hz]
        assert len(hits) == 1, off
        assert hits[0].bandwidth_hz < 1e6 and hits[0].snr_db > 6.0
    # the gap between the FHSS block and the DJI band stays empty
    assert not [s for s in segs if FC - 3.0e6 <= s.center_freq_hz <= FC - 0.7e6]
    assert 0.3 < r.occupied_fraction < 0.8
    assert r.mean_excess_db > 3.0
    assert r.peak_snr_db == max(s.snr_db for s in segs)


def test_busy_scene_kurtosis_bursts_and_features(busy_result, noise_result):
    r = busy_result
    assert r.kurtosis > 2.5  # bursty
    assert noise_result.kurtosis == pytest.approx(2.0, abs=0.1)
    wide = [b for b in r.bursts if b.bandwidth_hz > 7e6]
    narrow = [b for b in r.bursts if b.bandwidth_hz < 1e6]
    assert 8 <= len(wide) <= 12  # 10 DJI-like bursts
    assert len(narrow) >= 25  # 30 FHSS hops
    assert np.median([b.duration_s for b in wide]) == pytest.approx(DJI_DURATION, rel=0.25)
    assert np.median([b.duration_s for b in narrow]) == pytest.approx(1.5e-3, rel=0.25)
    starts = sorted(b.t_start_s for b in wide)
    assert np.median(np.diff(starts)) == pytest.approx(DJI_PERIOD, rel=0.05)
    f = r.features
    assert f.n_bursts == len(r.bursts)
    assert f.n_distinct_centers >= 5
    assert f.hop_rate_hz > 100.0
    assert 0.5 < f.duty_cycle <= 1.0
    assert r.activity_score > 5.0 * noise_result.activity_score + 5.0

    d = r.to_dict()
    assert d["n_bursts"] == len(r.bursts) and len(d["occupancy"]) == len(r.occupancy)
    assert d["features"]["n_bursts"] == f.n_bursts and "psd_db" not in d
    assert json.dumps(d)  # serialisable
    full = r.to_dict(include_psd=True)
    assert len(full["psd_db"]) == len(full["freqs_hz"]) == r.psd_db.size


def test_noise_only_dwell_is_quiet(noise_result):
    r = noise_result
    assert r.occupancy == [] and r.occupied_fraction == 0.0
    assert r.peak_snr_db == 0.0
    assert abs(r.mean_excess_db) < 1.0
    assert len(r.bursts) <= 2  # isolated noise cells are filtered by the size gates
    assert r.activity_score < 1.0


def test_analyse_dwell_accepts_multichannel_and_validates():
    rng = np.random.default_rng(4)
    x = syn.awgn(50_000, rng, power_db=-40.0)
    both = np.stack([x, 0.5 * x])
    r = sw.analyse_dwell(both, 2e6, 1e9, 1.6e6, fft_size=512, burst_fft_size=256)
    assert r.kurtosis == pytest.approx(2.0, abs=0.1)
    assert r.span_hz == 1.6e6 and r.freqs_hz.size < 512
    assert sw.analyse_dwell(x, 2e6, 1e9).span_hz == 2e6  # default: whole sample rate
    with pytest.raises(ValueError):
        sw.analyse_dwell(x, 2e6, 1e9, 3e6)
    with pytest.raises(ValueError):
        sw.analyse_dwell(np.zeros(0, np.complex64), 2e6, 1e9)


# --------------------------------------------------------------------------- tunable source


def test_sweeper_retunes_settles_discards_and_ranks():
    src, quiet_fc, busy_fc = _two_sector_source()
    fs = src.info.sample_rate_hz
    plan = [Dwell(quiet_fc, 0.8 * fs), Dwell(busy_fc, 0.8 * fs, (busy_fc + 0.8e6,))]
    sleeps: list[float] = []
    ticks = iter(range(100, 200))
    sweeper = sw.Sweeper(
        src, plan, dwell_s=0.02, settle_s=0.08, discard_buffers=2, fft_size=1024,
        sleep=sleeps.append, clock=lambda: float(next(ticks)), burst_fft_size=256,
    )
    assert not sweeper.fixed_tuning and sweeper.plan == plan
    results = sweeper.run_once()
    assert src.retunes == [quiet_fc, busy_fc]
    assert sleeps == [0.08, 0.08]
    n = round(0.02 * fs)
    assert src.reads == [n] * 6  # (2 discards + 1 capture) per dwell
    assert [r.center_freq_hz for r in results] == [busy_fc, quiet_fc]  # ranked, most active first
    busy, quiet = results
    assert busy.activity_score > quiet.activity_score
    assert busy.targets == (busy_fc + 0.8e6,)
    assert len(busy.occupancy) == 1 and busy.occupancy[0].center_freq_hz == pytest.approx(
        busy_fc + 0.8e6, abs=0.15e6)
    assert 4 <= len(busy.bursts) <= 6 and quiet.occupancy == []
    assert busy.kurtosis > 2.5 and quiet.kurtosis == pytest.approx(2.0, abs=0.1)
    assert {busy.t_wall_s, quiet.t_wall_s} == {100.0, 101.0}
    assert sweeper.n_runs == 1
    # sleeps are skipped entirely when settle_s == 0
    src.retunes.clear()
    sleeps.clear()
    sw.Sweeper(src, plan, dwell_s=0.01, settle_s=0.0, discard_buffers=0, sleep=sleeps.append,
               burst_fft_size=256, fft_size=1024).run_once()
    assert sleeps == [] and src.retunes == [quiet_fc, busy_fc]


def test_sweeper_random_order_and_revisit_top():
    src, quiet_fc, busy_fc = _two_sector_source()
    fs = src.info.sample_rate_hz
    plan = [Dwell(quiet_fc, 0.8 * fs), Dwell(busy_fc, 0.8 * fs)]
    kw = {"dwell_s": 0.01, "settle_s": 0.0, "discard_buffers": 0, "fft_size": 1024, "burst_fft_size": 256,
              "sleep": lambda s: None}
    orders = []
    for seed in (1, 2, 3, 4, 5, 6):
        src.retunes.clear()
        sw.Sweeper(src, plan, order="random", rng=np.random.default_rng(seed), **kw).run_once()
        orders.append(tuple(src.retunes))
    assert all(sorted(o) == sorted([quiet_fc, busy_fc]) for o in orders)
    assert len(set(orders)) == 2  # both permutations occur over a few seeds
    src.retunes.clear()
    a = sw.Sweeper(src, plan, order="random", rng=np.random.default_rng(7), **kw).run_once()
    first = list(src.retunes)
    src.retunes.clear()
    sw.Sweeper(src, plan, order="random", rng=np.random.default_rng(7), **kw).run_once()
    assert src.retunes == first  # deterministic for a seeded generator

    src.retunes.clear()
    src.reads.clear()
    sweeper = sw.Sweeper(src, plan, revisit_top=1, revisit_dwell_s=0.02, **kw)
    results = sweeper.run_once()
    assert src.retunes == [quiet_fc, busy_fc, busy_fc]  # sweep, then dwell longer on the best
    assert src.reads == [round(0.01 * fs)] * 2 + [round(0.02 * fs)]
    assert results[0].center_freq_hz == busy_fc
    assert results[0].n_samples == round(0.02 * fs) and results[1].n_samples == round(0.01 * fs)
    assert a[0].n_samples == round(0.01 * fs)

    runs = list(sweeper.iter_runs(2))
    assert len(runs) == 2 and sweeper.n_runs == 3


def test_sweeper_validation():
    src, quiet_fc, _busy_fc = _two_sector_source()
    fs = src.info.sample_rate_hz
    with pytest.raises(ValueError):
        sw.Sweeper(src)  # tunable source without a plan
    with pytest.raises(ValueError):
        sw.Sweeper(src, [Dwell(quiet_fc, 2 * fs)])
    with pytest.raises(ValueError):
        sw.Sweeper(src, [Dwell(quiet_fc, fs)], dwell_s=0.0)
    with pytest.raises(ValueError):
        sw.Sweeper(src, [Dwell(quiet_fc, fs)], order="shuffle")
    with pytest.raises(ValueError):
        sw.Sweeper(src, [Dwell(quiet_fc, fs)], discard_buffers=-1)
    assert sw.is_fixed_tuning(syn.SyntheticSource(np.zeros(10, np.complex64),
                                                  StreamInfo(1e6, 1e9)))
    assert not sw.is_fixed_tuning(src)


# --------------------------------------------------------------------------- file source + map


@pytest.fixture(scope="module")
def recording(tmp_path_factory) -> tuple[str, float]:
    fs, fc = 4e6, 915e6
    scene = syn.Scene(fs, fc, 40e-3, np.random.default_rng(21), noise_power_db=-60.0)
    rng = np.random.default_rng(22)
    for k in range(4):  # bursts only in the first half of the file
        burst = syn.gfsk_burst(fs, 200e3, 200, rng)
        scene.add(burst, t_start_s=1e-3 + k * 4e-3, freq_offset_hz=-1e6, snr_db=25.0, label="g")
    info = StreamInfo(fs, fc, hardware="synthetic", description="sweep test")
    stem = tmp_path_factory.mktemp("sweep") / "rec"
    write_sigmf(stem, scene.render(), info)
    return str(stem), fc


def test_file_source_runs_consecutive_dwells_and_occupancy_map(recording):
    stem, fc = recording
    with SigmfFileSource(stem) as src:
        fs = src.info.sample_rate_hz
        # a multi-dwell plan is collapsed to the file's own centre; matching targets are kept
        plan = plan_dwells([fc - 1e6, fc + 0.5e6, fc + 30e6], fs)
        sweeper = sw.Sweeper(src, plan, dwell_s=0.02, fft_size=1024, burst_fft_size=256)
        assert sweeper.fixed_tuning and len(sweeper.plan) == 1
        assert sweeper.plan[0].center_freq_hz == fc
        assert sweeper.plan[0].span_hz == pytest.approx(0.8 * fs)
        assert sweeper.plan[0].targets == (fc - 1e6, fc + 0.5e6)
        occ = sw.OccupancyMap(threshold_db=6.0)
        runs = list(sweeper.iter_runs())
        assert len(runs) == 2  # 40 ms file / 20 ms dwells, then exhausted
        assert sweeper.run_once() == []
        first, second = runs[0][0], runs[1][0]
        assert first.targets == (fc - 1e6, fc + 0.5e6)
        assert len(first.bursts) == 4 and len(first.occupancy) == 1
        assert first.occupancy[0].center_freq_hz == pytest.approx(fc - 1e6, abs=0.1e6)
        assert second.occupancy == [] and len(second.bursts) <= 1
        assert first.t_wall_s > 0.0  # real clock on file sources
        for results in runs:
            occ.update(results)

    assert len(occ) == 1 and occ.n_runs == 2
    entry = occ.entry(fc)
    assert entry.n_runs == 2 and entry.n_bursts == len(first.bursts) + len(second.bursts)
    assert np.array_equal(entry.max_hold_db, np.maximum(first.psd_db, second.psd_db))
    frac = entry.occupancy
    band = (entry.freqs_hz > fc - 1.1e6) & (entry.freqs_hz < fc - 0.9e6)
    assert np.all(frac[band] == 0.5)  # occupied in one run of two
    quiet = entry.freqs_hz > fc + 0.5e6
    assert np.all(frac[quiet] == 0.0)
    assert entry.kurtosis_max == pytest.approx(max(first.kurtosis, second.kurtosis))
    segs = occ.segments(min_fraction=0.5)
    assert len(segs) == 1
    assert segs[0]["f_low_hz"] < fc - 1e6 < segs[0]["f_high_hz"] and segs[0]["occupancy"] == 0.5
    assert occ.segments(min_fraction=0.6) == []

    doc = json.loads(occ.to_json())
    assert doc["schema"] == sw.OCCUPANCY_MAP_SCHEMA and doc["n_runs"] == 2
    assert len(doc["dwells"]) == 1
    row = doc["dwells"][0]
    assert row["center_freq_hz"] == fc and row["n_bins"] == entry.freqs_hz.size
    assert len(row["max_hold_db"]) == len(row["occupancy"]) == row["n_bins"]
    assert max(row["occupancy"]) == 0.5
    assert row["noise_floor_db"]["median"] == pytest.approx(
        np.median([first.noise_floor_db, second.noise_floor_db]))
    assert row["bin_hz"] == pytest.approx(fs / 1024)
    # a result with a different frequency axis at the same centre is rejected
    other = sw.analyse_dwell(np.ones(4096, np.complex64), fs, fc, 0.8 * fs, fft_size=512)
    with pytest.raises(ValueError):
        occ.update([other])


# --------------------------------------------------------------------------- cli


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk")
    cli_sweep.register(parser.add_subparsers(dest="command"))
    return parser


def _run(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    return int(args.func(args))


def test_cli_sweep_on_file_prints_table_and_writes_json(recording, tmp_path, capsys):
    stem, fc = recording
    out = tmp_path / "sweep.json"
    events = tmp_path / "events.jsonl"
    rc = _run(["sweep", "--file", stem, "--dwell", "0.02", "--runs", "0", "--fft", "1024",
               "--json", str(out), "--events", str(events), "--sensor-id", "bench-1"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "centre_MHz" in text and "# run 0" in text and "# run 1" in text
    assert f"{fc / 1e6:12.3f}" in text
    doc = json.loads(out.read_text())
    assert doc["tool"] == "antsdr-tk sweep" and len(doc["runs"]) == 2
    assert doc["plan"][0]["center_freq_hz"] == fc
    assert doc["runs"][0][0]["n_bursts"] == 4
    assert doc["occupancy_map"]["n_runs"] == 2
    assert "psd_db" not in doc["runs"][0][0]
    lines = [ln for ln in events.read_text().splitlines() if ln.strip()]
    assert len(lines) == doc["runs"][0][0]["n_bursts"] + doc["runs"][1][0]["n_bursts"]
    first = json.loads(lines[0])
    assert first["sensor_id"] == "bench-1" and first["source"] == "synthetic"
    assert first["rf_port"] == "RX1" and first["family"] is None


def test_cli_sweep_argument_errors_and_band_listing(recording, capsys):
    stem, _ = recording
    assert _run(["sweep", "--list-bands"]) == 0
    out = capsys.readouterr().out
    assert "fpv-5g8-wide" in out and "5645.000" in out
    assert _run(["sweep", "--band", "ism-2g4"]) == 2  # no source
    assert "exactly one" in capsys.readouterr().err
    assert _run(["sweep", "--uri", "ip:1.2.3.4", "--file", stem]) == 2
    assert _run(["sweep", "--uri", "ip:1.2.3.4"]) == 2  # nothing to sweep
    assert "needs --band" in capsys.readouterr().err
    assert _run(["sweep", "--file", stem, "--runs", "-1"]) == 2
    with pytest.raises(ValueError):
        _run(["sweep", "--file", stem, "--band", "ism-2g4", "--freqs", "2412"])
    with pytest.raises(ValueError):
        _run(["sweep", "--file", stem, "--freqs", " , "])
    # without a driver module --uri fails with a clear message
    with pytest.raises(ValueError, match="E200 driver"):
        _run(["sweep", "--uri", "ip:192.168.1.10", "--freqs", "2414.5,2429.5", "--rate", "4e6"])


def test_cli_sweep_with_fake_e200_driver(monkeypatch, capsys):
    src, quiet_fc, busy_fc = _two_sector_source()
    seen: dict[str, object] = {}

    def open_source(uri, **kwargs):
        seen.update(uri=uri, **kwargs)
        return src

    fake = types.ModuleType("antsdr_toolkit.device.e200")
    fake.open_source = open_source
    monkeypatch.setitem(__import__("sys").modules, "antsdr_toolkit.device.e200", fake)
    monkeypatch.setattr(cli_sweep, "classifier",
                        lambda r: [("ofdm-burst", 0.75)] if r.bursts else [])
    freqs = f"{quiet_fc / 1e6},{busy_fc / 1e6}"
    rc = _run(["sweep", "--uri", "ip:192.168.1.10", "--freqs", freqs, "--rate", "4e6",
               "--dwell", "0.01", "--settle", "0", "--discard", "1", "--gain", "40",
               "--fft", "1024"])
    assert rc == 0
    assert seen["uri"] == "ip:192.168.1.10" and seen["sample_rate_hz"] == 4e6
    assert seen["gain_db"] == 40.0 and seen["center_freq_hz"] == quiet_fc
    assert src.retunes == [quiet_fc, busy_fc]
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith(("#", " " * 4 + "c"))]
    assert any("ofdm-burst:0.75" in ln for ln in rows)
    assert out.index(f"{busy_fc / 1e6:12.3f}") < out.index(f"{quiet_fc / 1e6:12.3f}")
