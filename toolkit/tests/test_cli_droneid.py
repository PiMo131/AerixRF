"""The ``droneid`` subcommand on a synthetic recording."""

from __future__ import annotations

import json

import numpy as np
import pytest

from antsdr_toolkit import cli, cli_droneid
from antsdr_toolkit.device.base import StreamInfo
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
    # the frequency offset is reported; the synthetic burst was given 4 kHz
    cfo_line = next(line for line in out.splitlines() if "cfo" in line)
    cfo = float(cfo_line.split("cfo")[1].split("Hz")[0])
    assert cfo == pytest.approx(4000.0, abs=200.0)


def test_json_output_carries_detection_and_frame(recording, tmp_path):
    path = tmp_path / "out.json"
    assert cli_droneid.main([str(recording), "--json", str(path)]) == 0
    doc = json.loads(path.read_text())
    assert doc["n_bursts"] == 1 and doc["n_decoded"] == 1
    burst = doc["bursts"][0]
    assert burst["detection"]["score"] > 0.5
    assert burst["frame"]["serial"] == "CLITEST000000001"
    assert burst["frame"]["crc24_ok"] and burst["frame"]["crc16_ok"]


def test_a_rate_the_receiver_cannot_use_is_retuned_rather_than_refused(tmp_path, capsys):
    # 20 MSPS is not a multiple of the subcarrier spacing, so it cannot be
    # decoded as it stands - and it is exactly the rate the E200's host link
    # likes. Rather than refusing it, the command says it is finding the
    # occupied bands and resampling. This file has nothing in it to find, so
    # the run still fails; what is asserted is *why*.
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



def test_crc_failed_candidate_never_exports_plausible_positions(recording, tmp_path, monkeypatch, capsys):
    from dataclasses import replace
    from antsdr_toolkit.droneid import receiver as rx

    payload = synth.make_payload_bytes(synth.DroneIdTx())
    frame = rx.parse_frame(payload)
    assert frame is not None
    invalid = replace(frame, crc16_ok=False, crc24_ok=False)
    detection = rx.BurstDetection(0, 0.8, 0.9, 0.0, 20.0, 0.0,
                                  zc_root=None, root_agnostic=True)
    monkeypatch.setattr(rx, 'process', lambda *a, **kw: [(detection, invalid)])
    output = tmp_path / 'invalid.json'
    assert cli_droneid.main([str(recording), '--json', str(output)]) == 0
    result = json.loads(output.read_text())
    candidate = result['bursts'][0]
    assert candidate['frame'] is None
    assert candidate['decode_status'] == 'unidentified'
    assert candidate['crc_checks'] == {'crc16_ok': False, 'crc24_ok': False}
    assert candidate['detection']['root_agnostic'] is True
    assert candidate['detection']['zc_root'] is None
    assert result['processing_sample_rate_hz'] == FS
    assert 'encrypted OcuSync 4 payload' not in capsys.readouterr().out
