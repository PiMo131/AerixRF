"""Tests for antsdr_toolkit.hardware: E200 constants, rate planning, config checks."""

from __future__ import annotations

import subprocess
import sys

import pytest

from antsdr_toolkit import hardware as hw


def test_profile_encodes_verified_e200_facts():
    e = hw.E200
    assert e.name == "MicroPhase ANTSDR E200"
    assert e.transceiver.startswith("AD9363")
    assert dict(e.rf_ports) == {0: "SMA RX1", 1: "IPEX RX2"}
    assert e.n_rx_channels == 2
    assert e.adc_bits == 12 and e.full_scale_counts == 2048.0
    assert e.sample_rate_min == 521e3
    assert e.sample_rate_max_1ch == 61.44e6 and e.sample_rate_max_2ch == 30.72e6
    assert dict(e.host_stream_ceiling_sps) == {
        "iio_sc16_1ch": 20e6, "iio_sc16_2ch_per_ch": 10e6, "uhd_sc8_1ch": 40e6,
    }
    assert e.rf_bandwidth_max == 56e6 and e.rf_bandwidth_min == 200e3
    assert e.lo_min == 70e6 and e.lo_max == 6e9
    assert e.default_uri == "ip:192.168.1.10"
    assert e.sample_rate_default == 30.72e6 and e.rf_bandwidth_default == 18e6
    assert "unverified" in e.notes["uhd_sc8_1ch"]
    with pytest.raises(AttributeError):  # dataclasses.FrozenInstanceError
        e.adc_bits = 16


def test_port_names_and_interface_limits():
    e = hw.E200
    assert e.rf_port_name(0) == "SMA RX1" and e.rf_port_name(1) == "IPEX RX2"
    with pytest.raises(ValueError):
        e.rf_port_name(2)
    assert e.interface_max_rate(1) == 61.44e6
    assert e.interface_max_rate(2) == 30.72e6
    for bad in (0, 3):
        with pytest.raises(ValueError):
            e.interface_max_rate(bad)
    assert e.host_ceiling(1) == 20e6 and e.host_ceiling(2) == 10e6
    assert e.host_ceiling(1, "uhd_sc8") == 40e6
    assert e.host_ceiling(2, "uhd_sc8") is None


def test_firmware_personalities():
    names = [fw.name for fw in hw.E200.firmware]
    assert names == ["pluto-iio", "uhd", "dji-droneid"]
    pluto = hw.E200.firmware_by_name("pluto-iio")
    assert pluto is not None
    assert (pluto.boot, pluto.ip, pluto.username, pluto.password) == (
        "QSPI", "192.168.1.10", "root", "analog")
    uhd = hw.E200.firmware_by_name("uhd")
    assert (uhd.boot, uhd.password) == ("SD", "microphase")
    dji = hw.E200.firmware_by_name("dji-droneid")
    assert (dji.boot, dji.password) == ("SD", "1")
    assert "52002" in dji.api and "fast_attack" in dji.notes
    assert hw.E200.firmware_by_name("openwifi") is None


def test_hw_string():
    assert hw.hw_string("pluto-iio v0.39") == (
        "MicroPhase ANTSDR E200 (Zynq-7020, AD9363, fw=pluto-iio v0.39)")
    assert hw.hw_string() == "MicroPhase ANTSDR E200 (Zynq-7020, AD9363, fw=pluto-iio)"


def test_rate_tables_and_constants():
    assert hw.CLEAN_RATES == (
        2.5e6, 4e6, 5e6, 8e6, 10e6, 14e6, 15.36e6, 20e6, 30.72e6, 40e6, 56e6, 61.44e6)
    assert hw.DRONEID_RATES == (15.36e6, 30.72e6, 61.44e6)
    assert all(r in hw.CLEAN_RATES for r in hw.DRONEID_RATES)
    assert [r for r in hw.DRONEID_RATES if r <= hw.E200.host_ceiling(1)] == [15.36e6]
    assert hw.GAIN_MODES == ("manual", "slow_attack", "fast_attack", "hybrid")
    assert hw.TX_GAIN_OFF_DB == -89.0
    assert hw.IIO_DEVICE_NAMES["control"] == "ad9361-phy"
    assert hw.IIO_DEVICE_NAMES["rx_data"] == "cf-ad9361-lpc"
    assert hw.RX_DATA_CHANNELS[1] == ("voltage2", "voltage3")
    assert hw.PHY_RX_CHANNELS[1] == "voltage1"


@pytest.mark.parametrize(
    "target_bw, channels, host_ceiling, expected",
    [
        (10e6, 1, True, 15.36e6),     # DroneID: LTE 10 MHz -> 15.36 MSPS
        (20e6, 2, True, 10e6),        # two channels under the 10 MSPS/ch host ceiling
        (20e6, 2, False, 30.72e6),    # ceiling off: interface limit per channel
        (1e6, 1, True, 2.5e6),        # never below the smallest clean rate
        (13e6, 1, True, 20e6),        # 19.5 MSPS wanted -> 20 MSPS
        (50e6, 1, True, 20e6),        # cannot be covered: widest allowed
        (50e6, 1, False, 61.44e6),
        (5.8e6, 1, True, 10e6),       # 8.7 MSPS wanted -> 10 MSPS (Wi-Fi-like 5.8 MHz)
    ],
)
def test_recommend_sample_rate(target_bw, channels, host_ceiling, expected):
    assert hw.recommend_sample_rate(target_bw, channels, host_ceiling) == expected


def test_recommend_sample_rate_options_and_errors():
    assert hw.recommend_sample_rate(10e6, oversampling=1.0) == 10e6
    assert hw.recommend_sample_rate(10e6, rates=(4e6, 30.72e6), host_ceiling=False) == 30.72e6
    assert hw.recommend_sample_rate(10e6, rates=(4e6, 30.72e6)) == 4e6  # 30.72 > host ceiling
    assert hw.recommend_sample_rate(10e6, rates=(4e6, 30.72e6), channels=2) == 4e6
    with pytest.raises(ValueError):
        hw.recommend_sample_rate(0.0)
    with pytest.raises(ValueError):
        hw.recommend_sample_rate(1e6, channels=3)
    with pytest.raises(ValueError):
        hw.recommend_sample_rate(1e6, oversampling=0.5)
    with pytest.raises(ValueError):
        hw.recommend_sample_rate(1e6, rates=(100e6,))


def test_check_stream_config_clean_and_warnings():
    assert hw.check_stream_config(15.36e6, 2.437e9, gain_db=40.0) == []
    assert hw.check_stream_config(10e6, 2.437e9, channels=(0, 1), rf_bandwidth_hz=8e6) == []
    warnings = hw.check_stream_config(30.72e6, 5.8e9)
    assert len(warnings) == 3
    assert "host-link" in warnings[0] and "20 MSPS" in warnings[0]
    assert "3.8 GHz" in warnings[1]
    assert "20 MHz" in warnings[2]
    assert hw.check_stream_config(30.72e6, 2.4e9, rf_bandwidth_hz=18e6, host_ceiling=False) == []
    low = hw.check_stream_config(1e6, 915e6)
    assert len(low) == 1 and "decimat" in low[0]
    two = hw.check_stream_config(15.36e6, 2.4e9, channels=(0, 1))
    assert len(two) == 1 and "10 MSPS per channel" in two[0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_rate_hz": 100e6, "center_freq_hz": 2.4e9},
        {"sample_rate_hz": 400e3, "center_freq_hz": 2.4e9},
        {"sample_rate_hz": 40e6, "center_freq_hz": 2.4e9, "channels": (0, 1)},
        {"sample_rate_hz": 10e6, "center_freq_hz": 50e6},
        {"sample_rate_hz": 10e6, "center_freq_hz": 7e9},
        {"sample_rate_hz": 10e6, "center_freq_hz": 2.4e9, "rf_bandwidth_hz": 100e3},
        {"sample_rate_hz": 10e6, "center_freq_hz": 2.4e9, "rf_bandwidth_hz": 60e6},
        {"sample_rate_hz": 10e6, "center_freq_hz": 2.4e9, "gain_mode": "auto"},
        {"sample_rate_hz": 10e6, "center_freq_hz": 2.4e9, "gain_db": 90.0},
        {"sample_rate_hz": 10e6, "center_freq_hz": 2.4e9, "channels": ()},
        {"sample_rate_hz": 10e6, "center_freq_hz": 2.4e9, "channels": (0, 0)},
        {"sample_rate_hz": 10e6, "center_freq_hz": 2.4e9, "channels": (2,)},
    ],
)
def test_check_stream_config_rejects_out_of_range(kwargs):
    with pytest.raises(ValueError):
        hw.check_stream_config(**kwargs)


def test_documented_procedures_are_complete():
    lines = [l.strip() for l in hw.FW_SETENV_2R2T.splitlines() if not l.startswith("#")]
    assert lines[:5] == [
        "fw_setenv attr_name compatible",
        "fw_setenv attr_val ad9361",
        "fw_setenv compatible ad9361",
        "fw_setenv mode 2r2t",
        "reboot",
    ]
    assert "antsdr-fw-patch" in hw.FW_SETENV_2R2T
    assert "mode=2r2t" in hw.UENV_2R2T_SD and "adi_loadvals" in hw.UENV_2R2T_SD
    cal = hw.CLOCK_CALIBRATION_SYSFS
    for token in ("ad5660mp", "in_voltage_dac_mode", "in_voltage_dac_ref_sel",
                  "in_voltage_dac_locked", "in_voltage_dac_value", "23000",
                  "Antsdr-Clock-calibration.md"):
        assert token in cal
    assert cal.index("echo 0 > in_voltage_dac_mode") < cal.index("echo 0 > in_voltage_dac_ref_sel")


def test_module_imports_without_hardware_or_numpy():
    code = (
        "import sys, antsdr_toolkit.hardware as hw; "
        "assert 'adi' not in sys.modules and 'iio' not in sys.modules and "
        "'numpy' not in sys.modules, sorted(m for m in sys.modules if m in ('adi','iio','numpy')); "
        "print(hw.E200.default_uri)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ip:192.168.1.10"
