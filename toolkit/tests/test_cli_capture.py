"""Tests for the ``capture`` subcommand (antsdr_toolkit.cli_capture) with the fake adi module."""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pytest
from test_e200_device import FW_VERSION, expected_iq, make_fake_adi

from antsdr_toolkit import cli_capture
from antsdr_toolkit import hardware as hw
from antsdr_toolkit.io.sigmf_io import read_sigmf, validate_metadata

URI = "ip:10.0.0.7"


def row(key: str, value: str) -> str:
    """One line of ``format_config`` output (13-column key)."""
    return f"{key:<13}{value}"


def test_dry_run_prints_configuration_without_hardware(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "adi", None)  # any driver import would fail loudly
    stem = tmp_path / "scan"
    argv = ["capture", "--uri", URI, "--freq", "2437e6", "--dry-run", str(stem)]
    assert cli_capture.main(argv) == 0
    out, err = capsys.readouterr()
    # 15.36 MSPS is above the stock IIO continuous ceiling, so the default
    # snapshot tier reports a duty cycle instead of staying silent.
    assert err.count("warning:") == 1 and "duty cycle" in err
    assert "dry run" in out
    assert row("uri", URI) in out
    assert row("hardware", "MicroPhase ANTSDR E200 (Zynq-7020, AD9363, fw=pluto-iio)") in out
    assert row("sample rate", "15.360000 MHz") in out
    assert row("center freq", "2437.000000 MHz") in out
    assert row("rf bandwidth", "15.360000 MHz") in out
    assert row("channels", "0 (SMA RX1)") in out
    assert row("gain mode", "manual") in out and row("gain", "40.0 dB") in out
    assert row("buffer", "262144 samples") in out and row("discard", "2 buffers") in out
    assert row("duration", "0.010000 s (153600 samples per channel)") in out
    assert row("tier", "snapshot") in out
    assert row("data file", f"{stem}.sigmf-data") in out
    assert row("meta file", f"{stem}.sigmf-meta") in out
    assert "duty cycle" in out
    assert not (tmp_path / "scan.sigmf-data").exists()
    # a rate inside the continuous ceiling warns about nothing
    argv = ["capture", "--uri", URI, "--freq", "2437e6", "--rate", "10e6",
            "--tier", "continuous", "--dry-run", str(stem)]
    assert cli_capture.main(argv) == 0
    out, err = capsys.readouterr()
    assert err == "" and row("warnings", "none") in out and row("tier", "continuous") in out


def test_dry_run_reports_host_ceiling_and_two_channel_settings(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "adi", None)
    argv = ["capture", "--freq", "5.8e9", "--rate", "30.72e6", "--bw", "18e6", "--channels", "0,1",
            "--gain-mode", "slow_attack", "--fw", "pluto-iio v0.39", "--tier", "continuous",
            "--dry-run", str(tmp_path / "x")]
    assert cli_capture.main(argv) == 0
    out, err = capsys.readouterr()
    assert row("channels", "0 (SMA RX1), 1 (IPEX RX2)") in out
    assert row("gain", "AGC (recorded as unknown)") in out
    assert "fw=pluto-iio v0.39" in out
    assert "host-link" in out and "6 MSPS per channel" in out and "3.8 GHz" in out
    assert err.count("warning:") == 2  # host link + AD9363 LO envelope (18 MHz bw is fine)


def test_capture_writes_a_valid_sigmf_pair(monkeypatch, tmp_path, capsys):
    fake = make_fake_adi()
    monkeypatch.setitem(sys.modules, "adi", fake)
    stem = tmp_path / "rec"
    argv = ["capture", "--uri", URI, "--freq", "2437e6", "--rate", "2.5e6", "--seconds", "0.01",
            "--buffer", "4096", "--discard", "1", "--gain", "30", "--fw", f"pluto-iio {FW_VERSION}",
            "--description", "bench", str(stem)]
    assert cli_capture.main(argv) == 0
    out, err = capsys.readouterr()
    assert err == ""
    (sdr,) = fake.instances
    assert sdr.closed and sdr.destroyed == 1
    assert dict(sdr.writes)["tx_hardwaregain_chan0"] == -89

    samples, info, meta = read_sigmf(stem)
    assert samples.shape == (25000,) and samples.dtype == np.complex64
    np.testing.assert_array_equal(samples, expected_iq(4096, 25000))  # one buffer discarded
    assert info.sample_rate_hz == 2.5e6 and info.center_freq_hz == 2.437e9
    assert info.rx_channels == (0,) and info.gain_db == 30.0
    assert info.hardware == hw.hw_string(f"pluto-iio {FW_VERSION}")
    assert info.description.endswith("; bench") and "SMA RX1" in info.description
    glob = meta["global"]
    assert glob["core:datatype"] == "cf32_le"
    assert glob["antsdr:uri"] == URI and glob["antsdr:rf_ports"] == ["SMA RX1"]
    assert glob["antsdr:gain_mode"] == "manual" and glob["antsdr:rx_buffer_size"] == 4096
    assert glob["antsdr:adc_bits"] == 12
    assert meta["annotations"] == []
    validate_metadata(meta)

    assert "wrote 25000 samples per channel (0.010000 s)" in out
    assert f"{stem}.sigmf-data" in out and f"{stem}.sigmf-meta" in out
    assert "dBFS" in out and "gain   30.0 dB" in out
    assert "MicroPhase ANTSDR E200" in out


def test_capture_two_channels(monkeypatch, tmp_path):
    fake = make_fake_adi()
    monkeypatch.setitem(sys.modules, "adi", fake)
    stem = tmp_path / "two"
    argv = ["capture", "--freq", "915e6", "--rate", "4e6", "--seconds", "0.001", "--buffer", "1000",
            "--discard", "0", "--channels", "0,1", str(stem)]
    assert cli_capture.main(argv) == 0
    samples, info, meta = read_sigmf(stem)
    assert samples.shape == (2, 4000) and info.rx_channels == (0, 1)
    np.testing.assert_array_equal(samples[0], expected_iq(0, 4000, 0))
    np.testing.assert_array_equal(samples[1], expected_iq(0, 4000, 1))
    assert meta["global"]["core:num_channels"] == 2
    assert meta["global"]["antsdr:rf_ports"] == ["SMA RX1", "IPEX RX2"]
    assert json.loads((tmp_path / "two.sigmf-meta").read_text())["captures"][0]["core:frequency"] == 915e6
    (sdr,) = fake.instances
    assert isinstance(sdr, fake.ad9361)


def test_missing_driver_and_invalid_settings_exit_one(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "adi", None)
    stem = tmp_path / "nope"
    assert cli_capture.main(["capture", "--freq", "2437e6", str(stem)]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and "antsdr-toolkit[e200]" in err and "libiio" in err
    assert not (tmp_path / "nope.sigmf-data").exists()

    fake = make_fake_adi()
    monkeypatch.setitem(sys.modules, "adi", fake)
    for extra in (["--rate", "100e6"], ["--seconds", "0"], ["--buffer", "0"],
                  ["--freq", "50e6"], ["--channels", "2"], ["--gain-mode", "manual", "--gain", "99"]):
        argv = ["capture", "--freq", "2437e6", *extra, str(stem)]
        assert cli_capture.main(argv) == 1, extra
        assert "error:" in capsys.readouterr().err
    assert fake.instances == []  # rejected before the device was opened

    fake = make_fake_adi(phy_chains=1, data_chains=1)
    monkeypatch.setitem(sys.modules, "adi", fake)
    assert cli_capture.main(["capture", "--freq", "2437e6", "--channels", "0,1", str(stem)]) == 1
    assert "fw_setenv mode 2r2t" in capsys.readouterr().err

    fake = make_fake_adi(fail_open=True)
    monkeypatch.setitem(sys.modules, "adi", fake)
    assert cli_capture.main(["capture", "--freq", "2437e6", str(stem)]) == 1
    assert "cannot open the E200" in capsys.readouterr().err


def test_argparse_errors(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_capture.main(["capture", str(tmp_path / "x")])  # --freq is required
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit):
        cli_capture.main(["capture", "--freq", "1e9", "--channels", "0,x", str(tmp_path / "x")])
    assert "comma-separated" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli_capture.main(["capture", "--freq", "1e9", "--gain-mode", "agc", str(tmp_path / "x")])
    assert cli_capture.main([]) == 2
    assert "capture" in capsys.readouterr().out


def test_help_documents_2r2t_and_clock_calibration(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_capture.main(["capture", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "fw_setenv mode 2r2t" in out
    assert "in_voltage_dac_mode" in out and "ad5660mp" in out
    assert "SMA RX1" in out and "IPEX RX2" in out
    assert "12 MSPS" in out and "61.44 MSPS" in out and "snapshot" in out


def test_register_into_a_parent_parser(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "adi", None)
    parser = argparse.ArgumentParser(prog="antsdr-tk")
    subparsers = parser.add_subparsers(dest="command")
    cli_capture.register(subparsers)
    args = parser.parse_args(["capture", "--freq", "2.4e9", "--dry-run", str(tmp_path / "s")])
    assert args.command == "capture" and args.func is cli_capture.run
    assert args.channels == (0,) and args.rate == cli_capture.DEFAULT_RATE_HZ == 15.36e6
    assert args.func(args) == 0
    assert "2400.000000 MHz" in capsys.readouterr().out


def test_resolve_config_and_parse_channels():
    assert cli_capture.parse_channels("0") == (0,)
    assert cli_capture.parse_channels("1, 0") == (1, 0)
    assert cli_capture.parse_channels((0, 1)) == (0, 1)
    with pytest.raises(argparse.ArgumentTypeError):
        cli_capture.parse_channels("")
    ns = argparse.Namespace(uri=URI, freq=2.437e9, rate=10e6, bw=None, gain=40.0,
                            gain_mode="manual", channels="0", seconds=0.5, buffer=8192,
                            discard=2, fw="pluto-iio", description="", out_stem="cap",
                            dry_run=True)
    cfg = cli_capture.resolve_config(ns)
    assert cfg["n_samples"] == 5_000_000 and cfg["channels"] == (0,)
    assert cfg["rf_bandwidth_hz"] == 10e6 and cfg["rf_ports"] == ["SMA RX1"]
    assert cfg["data_path"] == "cap.sigmf-data" and cfg["warnings"] == []
    text = cli_capture.format_config(cfg)
    assert "10.000000 MHz" in text and "5000000 samples" in text



@pytest.mark.parametrize('tier,seconds', [('continuous', '0.001'), ('snapshot', '1')])
def test_high_rate_multibuffer_or_continuous_capture_is_rejected_before_hardware(
        tier, seconds, monkeypatch, tmp_path, capsys):
    fake = make_fake_adi()
    monkeypatch.setitem(sys.modules, 'adi', fake)
    stem = tmp_path / 'unsafe-timeline'
    assert cli_capture.main(['capture', '--freq', '2437e6', '--rate', '15.36e6',
                             '--tier', tier, '--seconds', seconds, str(stem)]) == 1
    assert 'Multi-buffer gap timing is not implemented' in capsys.readouterr().err
    assert not fake.instances
    assert not stem.with_suffix('.sigmf-data').exists()


def test_one_buffer_snapshot_records_capture_limits(monkeypatch, tmp_path):
    fake = make_fake_adi()
    monkeypatch.setitem(sys.modules, 'adi', fake)
    stem = tmp_path / 'snapshot'
    assert cli_capture.main(['capture', '--freq', '2437e6', '--rate', '15.36e6',
                             '--seconds', '0.001', '--buffer', '16384', str(stem)]) == 0
    samples, _, meta = read_sigmf(stem)
    assert samples.shape == (15360,)
    assert meta['global']['antsdr:capture_tier'] == 'snapshot'
    assert meta['global']['antsdr:sample_continuity'] == 'unverified'
    assert meta['global']['antsdr:timestamp_source'] == 'host_wall_clock_not_hardware'
