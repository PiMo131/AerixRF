"""The ``droneid`` subcommand on synthetic recordings."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from antsdr_toolkit import cli, cli_droneid
from antsdr_toolkit.device.base import StreamInfo
from antsdr_toolkit.droneid import receiver as rx
from antsdr_toolkit.droneid import synth
from antsdr_toolkit.io.sigmf_io import write_sigmf

FS = 15.36e6
FC = 2429.5e6


@pytest.fixture
def recording(tmp_path):
    tx = synth.DroneIdTx(serial="CLITEST000000001", drone_lat=51.92, drone_lon=4.48)
    burst = synth.make_burst(FS, tx, rng=np.random.default_rng(1))
    x = synth.place_burst(FS, int(0.02 * FS), burst=burst, t_start_s=3e-3,
                          cfo_hz=4000.0, snr_db=25.0, rng=np.random.default_rng(4))
    stem = tmp_path / "droneid"
    write_sigmf(stem, x, StreamInfo(FS, FC, hardware="synthetic"))
    return stem


def test_decodes_and_prints_the_frame(recording, capsys):
    assert cli_droneid.main([str(recording)]) == 0
    out = capsys.readouterr().out
    assert "1 burst(s), 1 decoded" in out
    assert "known DroneID channel 2429.5 MHz" in out
    assert "Mini 2 serial 'CLITEST000000001'" in out
    assert "drone  51.9" in out and "pilot  51.9" in out and "home   51.9" in out
    cfo_line = next(line for line in out.splitlines() if "cfo" in line)
    cfo = float(cfo_line.split("cfo")[1].split("Hz")[0])
    assert cfo == pytest.approx(4000.0, abs=200.0)


def test_json_output_carries_only_crc_valid_telemetry(recording, tmp_path):
    path = tmp_path / "out.json"
    assert cli_droneid.main([str(recording), "--json", str(path)]) == 0
    doc = json.loads(path.read_text())
    assert doc["n_bursts"] == 1 and doc["n_decoded"] == 1
    burst = doc["bursts"][0]
    assert burst["detection"]["score"] > 0.5
    assert burst["decode"] == {"status": "decoded", "crc24_ok": True, "crc16_ok": True}
    assert burst["frame"]["serial"] == "CLITEST000000001"
    assert burst["frame"]["crc24_ok"] and burst["frame"]["crc16_ok"]


def test_crc_failed_parse_is_evidence_not_telemetry(recording, tmp_path, monkeypatch, capsys):
    """H10: CRC failure cannot identify O4 and must never publish coordinates."""
    frame = rx.parse_frame(synth.make_payload_bytes())
    assert frame is not None
    bad = replace(frame, crc24_ok=False, crc16_ok=False)
    detection = rx.BurstDetection(
        sample_start=100, score=0.8, confirm_score=0.9, cfo_hz=0.0,
        snr_db=7.0, t_start_s=100 / FS, zc_root=600,
    )

    def fake_process(*_args, **_kwargs):
        return [(detection, bad)]

    monkeypatch.setattr(rx, "process", fake_process)
    path = tmp_path / "failed.json"
    assert cli_droneid.main([str(recording), "--json", str(path)]) == 0
    out = capsys.readouterr().out
    assert "decode failed" in out
    assert "generation/cause unknown" in out
    assert "OcuSync 4" not in out and "encrypted" not in out

    doc = json.loads(path.read_text())
    burst = doc["bursts"][0]
    assert doc["n_bursts"] == 1 and doc["n_decoded"] == 0
    assert burst["decode"] == {
        "status": "decode_failed", "crc24_ok": False, "crc16_ok": False,
    }
    assert burst["frame"] is None, "CRC-failed coordinates leaked as telemetry"


def test_geometry_failure_is_distinct_from_crc_failure():
    assert cli_droneid._decode_evidence(None) == {
        "status": "geometry_failed", "crc24_ok": None, "crc16_ok": None,
    }


def test_a_rate_the_receiver_cannot_use_is_retuned_rather_than_refused(tmp_path, capsys):
    stem = tmp_path / "wrong_rate"
    write_sigmf(stem, np.zeros(1000, np.complex64), StreamInfo(20e6, FC))
    assert cli_droneid.main([str(stem)]) == 1
    err = capsys.readouterr().err
    assert "cannot be decoded directly" in err and "resampling" in err


def test_a_rate_the_receiver_cannot_use_is_refused_when_tuning_is_declined(tmp_path, capsys):
    stem = tmp_path / "wrong_rate_no_tune"
    write_sigmf(stem, np.zeros(1000, np.complex64), StreamInfo(20e6, FC))
    assert cli_droneid.main([str(stem), "--no-tune"]) == 1
    assert "not a multiple" in capsys.readouterr().err


def test_quiet_prints_only_decoded_bursts(recording, capsys):
    assert cli_droneid.main([str(recording), "--quiet"]) == 0
    assert "Mini 2" in capsys.readouterr().out


def test_registered_in_the_top_level_cli(recording, capsys):
    assert cli.main(["droneid", str(recording)]) == 0
    assert "decoded" in capsys.readouterr().out
