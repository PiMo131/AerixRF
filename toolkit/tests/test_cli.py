"""Tests for the antsdr-tk command line (info / replay)."""

from __future__ import annotations

import importlib.metadata
import json
import pathlib
import subprocess
import sys

import numpy as np
import pytest

from antsdr_toolkit import __version__, cli
from antsdr_toolkit.device.base import StreamInfo
from antsdr_toolkit.io.sigmf_io import write_sigmf

N = 10_000


@pytest.fixture(scope="module")
def recording(tmp_path_factory) -> pathlib.Path:
    rng = np.random.default_rng(7)
    x = (0.5 * (rng.standard_normal(N) + 1j * rng.standard_normal(N))).astype(np.complex64)
    x[:4000] = 0.0  # first chunk silent -> very low rms/peak
    info = StreamInfo(2e6, 2.437e9, gain_db=40.0, hardware="antsdr-e200", description="cli test")
    stem = tmp_path_factory.mktemp("cli") / "capture"
    write_sigmf(stem, x, info, datetime_utc="2026-09-05T10:00:00.000000Z",
                annotations=[{"sample_start": 0, "sample_count": 10, "label": "a"}])
    return stem


def test_info_prints_stream_info_samples_and_duration(recording, capsys):
    assert cli.main(["info", str(recording)]) == 0
    out = capsys.readouterr().out
    assert "antsdr-e200" in out
    assert "2437.000000 MHz" in out
    assert "2.000000 MHz" in out
    assert f"{N} per channel" in out
    assert f"{N / 2e6:.6f} s" in out
    assert "40.0 dB" in out
    assert "2026-09-05T10:00:00.000000Z" in out
    assert "annotations  1" in out


def test_info_json(recording, capsys):
    assert cli.main(["info", str(recording) + ".sigmf-meta", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["n_samples"] == N
    assert row["duration_s"] == pytest.approx(N / 2e6)
    assert row["sample_rate_hz"] == 2e6 and row["center_freq_hz"] == 2.437e9
    assert row["datatype"] == "cf32_le" and row["rx_channels"] == [0]


def test_replay_prints_one_line_per_chunk(recording, capsys):
    assert cli.main(["replay", str(recording), "--chunk", "4000"]) == 0
    lines = capsys.readouterr().out.splitlines()
    chunk_lines = [l for l in lines if l.startswith("chunk")]
    assert len(chunk_lines) == 3  # 4000 + 4000 + 2000
    assert "n=   4000" in chunk_lines[0] and "n=   2000" in chunk_lines[2]
    assert "rms=" in chunk_lines[1] and "dBFS" in chunk_lines[1]
    silent_rms = float(chunk_lines[0].split("rms=")[1].split()[0])
    loud_rms = float(chunk_lines[1].split("rms=")[1].split()[0])
    assert silent_rms < -200 and -5 < loud_rms < 1  # E|x|^2 = 0.5 -> -3 dBFS
    assert "t=  0.002000 s" in chunk_lines[1]
    assert lines[-1].startswith(f"# 3 chunks, {N} samples")


def test_replay_max_chunks_and_loop(recording, capsys):
    assert cli.main(["replay", str(recording), "--chunk", "3000", "--max-chunks", "2"]) == 0
    assert sum(l.startswith("chunk") for l in capsys.readouterr().out.splitlines()) == 2
    assert cli.main(["replay", str(recording), "--chunk", "6000",
                     "--loop", "--max-chunks", "5"]) == 0
    out = capsys.readouterr().out
    assert sum(l.startswith("chunk") for l in out.splitlines()) == 5
    assert "n=   6000" in out.splitlines()[-2]  # looping never shortens a chunk
    assert cli.main(["replay", str(recording), "--loop"]) == 1  # would run forever
    assert cli.main(["replay", str(recording), "--chunk", "0"]) == 1


def test_errors_return_nonzero_and_go_to_stderr(tmp_path, capsys):
    assert cli.main(["info", str(tmp_path / "missing")]) == 1
    assert "error:" in capsys.readouterr().err
    assert cli.main([]) == 2  # no subcommand -> help
    assert "usage" in capsys.readouterr().out.lower()
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_module_entry_point_runs_as_subprocess(recording):
    proc = subprocess.run(
        [sys.executable, "-m", "antsdr_toolkit.cli", "info", str(recording)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "antsdr-e200" in proc.stdout


def test_console_script_registered_and_version_matches():
    try:
        dist = importlib.metadata.distribution("antsdr-toolkit")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("antsdr-toolkit is not installed in this interpreter")
    assert dist.version == __version__
    scripts = {ep.name: ep.value for ep in dist.entry_points if ep.group == "console_scripts"}
    assert scripts.get("antsdr-tk") == "antsdr_toolkit.cli:main"
