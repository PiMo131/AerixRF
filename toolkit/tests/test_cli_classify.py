"""The ``classify`` subcommand end to end on a synthetic SigMF recording."""

from __future__ import annotations

import json

import numpy as np
import pytest

from antsdr_toolkit import cli, cli_classify
from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.io.sigmf_io import write_sigmf

FS = 30.72e6
FC = 2.4415e9


@pytest.fixture
def recording(tmp_path):
    """A 60 ms scene with one wide periodic emitter and one narrow hopper."""
    scene = syn.Scene(FS, FC, 60e-3, np.random.default_rng(21), noise_power_db=-60.0)
    rng = np.random.default_rng(22)
    for k in range(11):
        burst = syn.bandlimited_noise_burst(FS, 10e6, 600e-6, rng)
        scene.add(burst, t_start_s=2e-3 + k * 5e-3, freq_offset_hz=10e6, snr_db=22.0,
                  label="video", bandwidth_hz=10e6)
    t, idx = 1e-3, 0
    while t < 55e-3:
        burst = syn.gfsk_burst(FS, 200e3, 400, rng)
        scene.add(burst, t_start_s=t, freq_offset_hz=-8e6 + (idx % 4) * 1e6, snr_db=25.0,
                  label="hop", bandwidth_hz=400e3)
        t += 4e-3
        idx += 1
    stem = tmp_path / "scene"
    src = syn.SyntheticSource.from_scene(scene)
    write_sigmf(stem, src.read(src.n_samples), src.info)
    return stem


def test_classify_prints_one_block_per_emitter(recording, capsys):
    code = cli_classify.main([str(recording), "--band", "ism-2g4", "--fft", "512",
                              "--min-duration", "200e-6", "--min-bandwidth", "300e3"])
    assert code == 0
    out = capsys.readouterr().out
    assert "emitter 1:" in out and "emitter 2:" in out
    assert "burst(s) in 2 emitter group(s)" in out
    assert "band hint ism-2g4" in out
    assert "margin to the runner-up" in out
    # the header states the analysis settings, not just the answer
    assert "STFT 512" in out and "threshold 10 dB" in out
    assert "gates: duration >= 200.0 us" in out


def test_classify_writes_json_with_features_and_candidates(recording, tmp_path, capsys):
    out_path = tmp_path / "result.json"
    code = cli_classify.main([str(recording), "--fft", "512", "--min-duration", "200e-6",
                              "--min-bandwidth", "300e3", "--json", str(out_path), "--top", "2"])
    assert code == 0
    doc = json.loads(out_path.read_text())
    assert doc["sample_rate_hz"] == FS and doc["center_freq_hz"] == FC
    assert doc["n_bursts"] > 0 and len(doc["emitters"]) == 2
    first = doc["emitters"][0]
    assert set(first) == {"features", "candidates"}
    assert first["features"]["n_bursts"] > 0
    assert 1 <= len(first["candidates"]) <= 3  # --top 2 plus a possible 'unknown'
    for cand in first["candidates"]:
        assert 0.0 <= cand["score"] <= 1.0
        assert cand["decodability"] in {"decodable", "detect_only", "encrypted"}
        assert cand["explanation"]


def test_wide_emitter_is_named_a_wide_family(recording, capsys):
    cli_classify.main([str(recording), "--band", "ism-2g4", "--fft", "512",
                       "--min-duration", "200e-6", "--min-bandwidth", "300e3"])
    out = capsys.readouterr().out
    wide_block = out.split("emitter ")[-1]
    # 10 MHz every 5 ms is an OcuSync-class downlink; the table cannot tell O4
    # from OcuSync 2 on burst shape alone, and says so through a small margin.
    assert "OcuSync" in wide_block or "O4" in wide_block


def test_nothing_detected_is_reported_not_crashed(tmp_path, capsys):
    quiet = syn.Scene(FS, FC, 5e-3, np.random.default_rng(23), noise_power_db=-60.0)
    stem = tmp_path / "quiet"
    src = syn.SyntheticSource.from_scene(quiet)
    write_sigmf(stem, src.read(src.n_samples), src.info)
    assert cli_classify.main([str(stem), "--fft", "512"]) == 0
    out = capsys.readouterr().out
    assert "0 burst(s) in 0 emitter group(s)" in out
    assert "nothing detected" in out


def test_missing_recording_exits_one(tmp_path, capsys):
    assert cli_classify.main([str(tmp_path / "absent")]) == 1
    assert "error:" in capsys.readouterr().err


def test_registered_in_the_top_level_cli(recording, capsys):
    parser = cli.build_parser()
    args = parser.parse_args(["classify", str(recording), "--fft", "512"])
    assert getattr(args, "_run", None) is not None or getattr(args, "func", None) is not None
    assert cli.main(["classify", str(recording), "--fft", "512",
                     "--min-duration", "200e-6", "--min-bandwidth", "300e3"]) == 0
    assert "emitter 1:" in capsys.readouterr().out
