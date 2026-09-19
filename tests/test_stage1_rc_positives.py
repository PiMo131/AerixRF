"""Synthetic smoke tests for bench/stage1_rc_positives.py.

No dependency on the real RFUAV/ANTSDR corpora (those are validated by
running the bench script itself, see docs/design/
stage1-rc-positives-2026-09-19.md) -- this file only exercises the script's
own plumbing (model filtering, pack/slice discovery, and the full_band/dwell
processing wrapper) against small synthetic inputs, so a regression in the
bench harness itself is caught without needing multi-GB dataset mirrors on
CI/dev boxes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))

import stage1_rc_positives as bench  # noqa: E402


def test_skip_model_excludes_dji_and_autel():
    assert bench._skip_model("DJI_MINI4_PRO")
    assert bench._skip_model("DJI MINI4 PRO")
    assert bench._skip_model("DAUTEL_EVO_NANO")
    assert not bench._skip_model("FRSKY_X14")
    assert not bench._skip_model("FUTABA_T10J")


def test_model_expect_known_and_default():
    fs = bench._model_expect("FLYSKY_FS_I6X")
    assert fs["period_s"] == 3.85e-3
    afhds3 = bench._model_expect("FLYSKY_EL_18")
    assert afhds3["period_s"] is None  # AFHDS3, not AFHDS2A -- no primary number
    frsky = bench._model_expect("FRSKY_X20R")
    assert frsky["n_channels"] == 47
    unknown = bench._model_expect("SOME_UNSEEN_MODEL")
    assert unknown is bench._DEFAULT_EXPECT
    assert unknown["period_s"] is None


def test_find_packs_and_slices_non_dji_layout(tmp_path):
    """Mirrors the REAL non-DJI RFUAV layout: <model>/<Drone Name>/pack1.xml
    + pack1_<a>-<b>s.iq, with NO VTSBW=<N>/ folder -- the layout
    RfuavAdapter.iter_recordings does not currently enumerate (see
    handback)."""
    model_dir = tmp_path / "FRSKY_X14"
    inner = model_dir / "FRSKY X14"
    inner.mkdir(parents=True)
    (inner / "pack1.xml").write_text("<SignalHoundIQFile/>")
    for a in range(3):
        (inner / f"pack1_{a}-{a + 1}s.iq").write_bytes(b"\x00" * 16)
    # A second, unrelated pack number's slice must not be picked up by pack1's glob.
    (inner / "pack2.xml").write_text("<SignalHoundIQFile/>")
    (inner / "pack2_0-1s.iq").write_bytes(b"\x00" * 16)

    packs = bench._find_packs(model_dir)
    assert {p.name for p in packs} == {"pack1.xml", "pack2.xml"}

    pack1_xml = next(p for p in packs if p.stem == "pack1")
    slices = bench._find_slices(pack1_xml, 1)
    assert [p.name for p in slices] == ["pack1_0-1s.iq", "pack1_1-2s.iq", "pack1_2-3s.iq"]


def test_find_slices_caps_at_max_and_respects_aria2_marker(tmp_path):
    d = tmp_path / "pack_dir"
    d.mkdir()
    xml = d / "pack1.xml"
    xml.write_text("<SignalHoundIQFile/>")
    for a in range(12):
        (d / f"pack1_{a}-{a + 1}s.iq").write_bytes(b"\x00" * 8)
    # Mark one slice as an incomplete aria2 download -- must be excluded.
    (d / "pack1_2-3s.iq.aria2").write_bytes(b"")

    slices = bench._find_slices(xml, 1)
    assert len(slices) == bench.MAX_SLICES_PER_RECORDING
    assert "pack1_2-3s.iq" not in {p.name for p in slices}


def _synthetic_hopping_iq(fs: float, n: int, seed: int = 0) -> np.ndarray:
    """A short synthetic burst-hopping-like complex signal: repeated narrow
    tones at a few frequencies with silence between, well above the noise
    floor -- just needs to be enough for detect_bursts to find >=1 event
    per window and for the full_band/dwell pipeline to run end-to-end
    without error. Not used to assert any specific label (that is the real
    dataset's job); only that the wrapper functions produce well-formed
    records."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs
    iq = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64) * 0.01
    tones_hz = [0.5e6, 1.5e6, 2.5e6]
    burst_len = int(0.001 * fs)
    pos = 0
    k = 0
    while pos + burst_len < n:
        f = tones_hz[k % len(tones_hz)]
        seg = np.exp(2j * np.pi * f * t[pos:pos + burst_len]).astype(np.complex64)
        iq[pos:pos + burst_len] += seg
        pos += burst_len * 4
        k += 1
    return iq


def test_process_one_iq_end_to_end_synthetic():
    fs_hz = 20_000_000.0
    n = int(fs_hz * 0.05)  # 50 ms synthetic window -- enough frames, fast test
    iq = _synthetic_hopping_iq(fs_hz, n)
    center_freq_hz = 2_450_000_000.0

    records = bench._process_one_iq(iq, fs_hz, center_freq_hz, "SYNTH_MODEL", "SYNTH_MODEL/pack1", "pack1_0-1s.iq")

    assert len(records) == 2
    modes = {r["mode"] for r in records}
    assert modes == {"full_band", "dwell"}
    for r in records:
        assert r["model"] == "SYNTH_MODEL"
        assert isinstance(r["labels"], list)
        assert isinstance(r["tags"], list)
        assert "delta_hz" in r["raster"]
        assert "t_hat_s" in r["period"]
        assert r["fs_hz"] > 0

    dwell = next(r for r in records if r["mode"] == "dwell")
    # Dwell path must actually be resampled to the canonical rate, not left
    # at the native rate (the whole point of the full_band-vs-dwell split).
    from aerix_rf.datasets.resample import CANONICAL_RATE_HZ
    assert dwell["fs_hz"] == CANONICAL_RATE_HZ
    # Selection provenance (task item (c)): the dwell record must carry the
    # chosen-centre selection metric; full_band never re-centres, so it must not.
    assert dwell["dwell_select"] is not None
    assert dwell["dwell_select"]["method"] in ("occupancy_grid", "fallback_guard_too_wide_for_band")
    full_band = next(r for r in records if r["mode"] == "full_band")
    assert full_band["dwell_select"] is None


def test_dwell_center_by_occupancy_prefers_midband_hopping_over_edge_rolloff():
    """Regression for the C6 bench-only defect (docs/design/
    stage1-rc-positives-2026-09-19.md sec 3/4 item 6): raw argmax(mean PSD)
    landed on the extreme band edge for FLYSKY/FRSKY. Build a synthetic PSD
    with a persistent, flickering band-edge roll-off (which the OLD
    argmax(mean PSD) logic picks) plus a genuine mid-band hopping cluster
    (several distinct channels, each active a minority of frames) and assert
    the NEW selector lands its dwell centre in the mid-band cluster, not the
    edge."""
    from aerix_rf.dsp.spectrogram import Spectrogram

    fs_hz = 100_000_000.0
    fft_size = 1024
    bin_hz = fs_hz / fft_size
    freqs = (np.arange(fft_size) - fft_size // 2) * bin_hz
    n_frames = 300
    rng = np.random.default_rng(1)

    power_db = np.full((n_frames, fft_size), -80.0, dtype=np.float32)

    # Persistent band-edge roll-off: bins 0..40 (~-50.0..-46.1 MHz), well
    # inside the >=5 MHz edge guard, flickering above its own floor 30% of
    # frames -- exactly the kind of artefact the OLD raw argmax(mean PSD)
    # picked (it dominates the plain time-average because it never turns off
    # across the whole band elsewhere).
    edge_bins = list(range(0, 41))
    for b in edge_bins:
        active = rng.random(n_frames) < 0.3
        power_db[active, b] = -40.0

    # Real mid-band hopping cluster: several distinct channels well inside
    # the guarded region, each on a minority of frames (a hop set, not a
    # continuous carrier).
    mid_bins = [500, 540, 580, 620, 660]
    for b in mid_bins:
        active = rng.random(n_frames) < 0.3
        power_db[active, b] = -55.0

    spec = Spectrogram(freqs_hz=freqs, power_db=power_db, sample_rate=fs_hz, hop=fft_size // 2)

    # Sanity: confirm the OLD raw argmax(mean PSD) would indeed have picked
    # the edge on this synthetic PSD (otherwise this test would not exercise
    # the regression at all).
    old_style_bin = int(power_db.mean(axis=0).argmax())
    assert old_style_bin in edge_bins

    offset_hz, meta = bench._dwell_center_by_occupancy(spec, fs_hz)

    mid_lo_hz, mid_hi_hz = freqs[min(mid_bins)], freqs[max(mid_bins)]
    assert mid_lo_hz <= offset_hz <= mid_hi_hz, (
        f"expected a mid-band dwell centre in [{mid_lo_hz}, {mid_hi_hz}] Hz, got {offset_hz} Hz")
    lo_edge = freqs.min() + bench._DWELL_EDGE_GUARD_HZ
    hi_edge = freqs.max() - bench._DWELL_EDGE_GUARD_HZ
    assert lo_edge <= offset_hz <= hi_edge  # never inside the guarded edge band
    assert meta["method"] == "occupancy_grid"
    assert meta["occupancy"] > 0.0


def test_load_slice_rejects_wrong_sample_count(tmp_path):
    p = tmp_path / "pack1_0-1s.iq"
    p.write_bytes(np.zeros(20, dtype="<f4").tobytes())  # 10 complex samples
    try:
        bench._load_slice(p, expected_samples=999)
        assert False, "expected ValueError"
    except ValueError:
        pass
