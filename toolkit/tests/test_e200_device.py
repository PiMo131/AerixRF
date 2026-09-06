"""Tests for antsdr_toolkit.device.e200 against a fake pyadi-iio module (no hardware).

``make_fake_adi`` builds an ``adi`` look-alike whose ``ad9364`` / ``ad9361``
classes record every attribute write in order, mimic the pyadi quirks that
matter (gain writes dropped unless the chain is in ``'manual'`` mode,
``sample_rate`` floor, missing ``voltageN`` channels on 1r1t firmware) and
return deterministic int16-count buffers from ``rx()`` exactly as pyadi does
(``I + 1j*Q`` -> complex128). ``expected_iq`` gives the same stream as
full-scale complex64 so reads can be checked across buffer boundaries.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import itertools
import logging
import sys
import types
from types import ModuleType
from typing import ClassVar

import numpy as np
import pytest

from antsdr_toolkit import hardware as hw
from antsdr_toolkit.device.base import SampleSource, StreamInfo
from antsdr_toolkit.device.e200 import E200Source, import_adi, open_source, probe

FULL_SCALE = 2048.0
FW_VERSION = "v0.39"
URI = "ip:10.0.0.7"

# Firmware (dtsi) defaults reported by a freshly booted device.
DTSI_DEFAULTS = {
    "sample_rate": 30_720_000,
    "rx_lo": 2_400_000_000,
    "rx_rf_bandwidth": 18_000_000,
    "gain_control_mode_chan0": "slow_attack",
    "rx_hardwaregain_chan0": 71.0,
    "gain_control_mode_chan1": "slow_attack",
    "rx_hardwaregain_chan1": 71.0,
}


def raw_counts(start: int, n: int, channel: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """int16 (I, Q) counts of the fake stream for global sample indices ``start .. start+n``."""
    g = np.arange(start, start + n, dtype=np.int64)
    i = (g + 1000 * channel) % 4096 - 2048
    q = (3 * g + 7 + 1000 * channel) % 4096 - 2048
    return i.astype(np.int16), q.astype(np.int16)


def expected_iq(start: int, n: int, channel: int = 0) -> np.ndarray:
    """What ``E200Source.read`` must return for that stream segment (complex64, /2048)."""
    i, q = raw_counts(start, n, channel)
    return ((i.astype(np.float32) + 1j * q.astype(np.float32)) / np.float32(FULL_SCALE)).astype(
        np.complex64
    )


# --------------------------------------------------------------------------
# fake libiio objects and fake adi module
# --------------------------------------------------------------------------
class FakeAttr:
    def __init__(self, value) -> None:
        self.value = str(value)


class FakeChannel:
    def __init__(self, id: str, *, output: bool = False, scan_element: bool = False,
                 attrs: dict | None = None) -> None:
        self.id = id
        self.output = output
        self.scan_element = scan_element
        self.attrs = {k: FakeAttr(v) for k, v in (attrs or {}).items()}


class FakeDevice:
    def __init__(self, name: str, channels: list[FakeChannel]) -> None:
        self.name = name
        self.channels = channels

    def find_channel(self, name: str, output: bool = False) -> FakeChannel | None:
        for ch in self.channels:
            if ch.id == name and ch.output == output:
                return ch
        return None


class FakeContext:
    def __init__(self, uri: str, *, phy_chains: int = 2, data_chains: int = 2,
                 attrs: dict | None = None) -> None:
        self.uri = uri
        self.attrs = {"fw_version": FW_VERSION,
                      "hw_model": "Analog Devices ANTSDR Rev.C (Z7020/AD9363)"} if attrs is None else attrs
        phy = [FakeChannel("altvoltage0", output=True,
                           attrs={"frequency": DTSI_DEFAULTS["rx_lo"]})]
        for c in range(phy_chains):
            phy.append(FakeChannel(f"voltage{c}", attrs={
                "sampling_frequency": DTSI_DEFAULTS["sample_rate"],
                "rf_bandwidth": DTSI_DEFAULTS["rx_rf_bandwidth"],
                "gain_control_mode": DTSI_DEFAULTS[f"gain_control_mode_chan{c}"],
                "hardwaregain": f"{DTSI_DEFAULTS[f'rx_hardwaregain_chan{c}']:.6f} dB",
            }))
        data = [FakeChannel(f"voltage{k}", scan_element=True) for k in range(2 * data_chains)]
        self.devices = [
            FakeDevice("ad9361-phy", phy),
            FakeDevice("cf-ad9361-lpc", data),
            FakeDevice("cf-ad9361-dds-core-lpc", []),
        ]

    def find_device(self, name: str) -> FakeDevice | None:
        return next((d for d in self.devices if d.name == name), None)


class FakeSdr:
    """pyadi-iio ad936x stand-in; class attributes are set by :func:`make_fake_adi`."""

    _rx_channel_names: ClassVar[list[str]] = ["voltage0", "voltage1"]
    _phy_chains = 2
    _data_chains = 2
    _probe = True
    _fail_open = False
    _ctx_attrs: dict | None = None

    def __init__(self, uri: str = "", **_: object) -> None:
        if self._fail_open:
            raise Exception("No device found")  # noqa: TRY002 - pyadi raises bare Exception
        d = self.__dict__
        d["uri"] = uri
        d["writes"] = []
        d["rx_calls"] = 0
        d["_rxbuf"] = None
        d["destroyed"] = 0
        d["closed"] = False
        d["ctx"] = FakeContext(uri, phy_chains=self._phy_chains, data_chains=self._data_chains,
                               attrs=self._ctx_attrs)
        d["_ctrl"] = self.ctx.find_device("ad9361-phy")
        d["_rxadc"] = self.ctx.find_device("cf-ad9361-lpc") if self._probe else object()
        d["rx_enabled_channels"] = [0]
        d["rx_buffer_size"] = 1024
        for key, value in DTSI_DEFAULTS.items():
            if key.endswith("chan1") and self._phy_chains < 2:
                continue
            d[key] = value

    def __setattr__(self, name: str, value) -> None:
        self.writes.append((name, value))
        if name == "sample_rate" and value < 521e3:
            raise ValueError("Error: Does not currently support sample rates below 521e3")
        if name == "rx_enabled_channels" and max(value) > len(self._rx_channel_names) / 2 - 1:
            raise Exception("RX mapping exceeds available channels")  # noqa: TRY002
        if name.endswith("chan1") and self._phy_chains < 2:
            # pyadi _set_iio_attr: find_channel('voltage1') is None -> .attrs fails
            raise AttributeError("'NoneType' object has no attribute 'attrs'")
        if (name.startswith("rx_hardwaregain_chan")
                and self.__dict__.get(f"gain_control_mode_chan{name[-1]}") != "manual"):
            return  # silently dropped, exactly like pyadi's setter
        self.__dict__[name] = value

    def rx(self):
        if self._rxbuf is None:  # lazy buffer creation (compat_libiio_v0_rx._rx_init_channels)
            for name in self._rx_channel_names:
                if self.ctx.find_device("cf-ad9361-lpc").find_channel(name) is None:
                    raise Exception(f"Channel {name} not found")  # noqa: TRY002 - as pyadi
            self.__dict__["_rxbuf"] = object()
        k = self.rx_calls
        self.__dict__["rx_calls"] = k + 1
        n = int(self.rx_buffer_size)
        out = []
        for c in self.rx_enabled_channels:
            i, q = raw_counts(k * n, n, c)
            out.append(i + 1j * q)  # complex128 of integer counts, like pyadi
        return out[0] if len(out) == 1 else out

    def rx_destroy_buffer(self) -> None:
        self.__dict__["_rxbuf"] = None
        self.__dict__["destroyed"] += 1

    def close(self) -> None:
        self.__dict__["closed"] = True


def make_fake_adi(*, phy_chains: int = 2, data_chains: int = 2, probe: bool = True,
                  fail_open: bool = False, ctx_attrs: dict | None = None) -> ModuleType:
    """Build a fake ``adi`` module; ``module.instances`` lists every constructed object."""
    mod = types.ModuleType("adi")
    mod.instances = []
    attrs = {"_phy_chains": phy_chains, "_data_chains": data_chains, "_probe": probe,
             "_fail_open": fail_open, "_ctx_attrs": ctx_attrs}

    def _init(self, uri="", **kwargs):
        FakeSdr.__init__(self, uri, **kwargs)
        mod.instances.append(self)

    mod.ad9364 = type("ad9364", (FakeSdr,), {
        **attrs, "_rx_channel_names": ["voltage0", "voltage1"], "__init__": _init})
    mod.ad9361 = type("ad9361", (FakeSdr,), {
        **attrs, "_rx_channel_names": ["voltage0", "voltage1", "voltage2", "voltage3"],
        "__init__": _init})
    return mod


def make_fake_iio(*, data_chains: int = 2) -> ModuleType:
    mod = types.ModuleType("iio")

    def context(uri: str) -> FakeContext:
        return FakeContext(uri, data_chains=data_chains)

    mod.Context = context
    return mod


def open_e200(fake: ModuleType, **overrides) -> E200Source:
    kwargs = {"sample_rate_hz": 2.5e6, "center_freq_hz": 2.437e9, "gain_db": 30.0,
              "buffer_size": 1000, "discard_buffers": 2, "adi_module": fake}
    kwargs.update(overrides)
    return E200Source(URI, **kwargs)


# --------------------------------------------------------------------------
# the fake itself must reproduce the pyadi quirks the driver works around
# --------------------------------------------------------------------------
def test_fake_drops_gain_unless_manual_like_pyadi():
    sdr = make_fake_adi().ad9364(uri=URI)
    sdr.rx_hardwaregain_chan0 = 10.0  # AGC mode active -> silently ignored
    assert sdr.rx_hardwaregain_chan0 == 71.0
    sdr.gain_control_mode_chan0 = "manual"
    sdr.rx_hardwaregain_chan0 = 10.0
    assert sdr.rx_hardwaregain_chan0 == 10.0
    with pytest.raises(ValueError):
        sdr.sample_rate = 400e3
    x = sdr.rx()
    assert x.dtype == np.complex128 and x.shape == (1024,)


# --------------------------------------------------------------------------
# E200Source
# --------------------------------------------------------------------------
def test_single_channel_configuration_order_and_info():
    fake = make_fake_adi()
    src = open_e200(fake)
    assert isinstance(src, SampleSource)
    (sdr,) = fake.instances
    assert isinstance(sdr, fake.ad9364)  # one chain -> adi.ad9364
    assert sdr.uri == URI
    assert [name for name, _ in sdr.writes] == [
        "sample_rate", "rx_rf_bandwidth", "rx_lo",
        "gain_control_mode_chan0", "rx_hardwaregain_chan0",
        "tx_hardwaregain_chan0", "rx_buffer_size",
    ]
    writes = dict(sdr.writes)
    assert writes["sample_rate"] == 2_500_000 and isinstance(writes["sample_rate"], int)
    assert writes["rx_rf_bandwidth"] == 2_500_000
    assert writes["rx_lo"] == 2_437_000_000 and isinstance(writes["rx_lo"], int)
    assert writes["gain_control_mode_chan0"] == "manual"
    assert writes["tx_hardwaregain_chan0"] == -89
    assert writes["rx_buffer_size"] == 1000
    assert sdr.rx_hardwaregain_chan0 == 30.0  # effective: mode was set first
    assert sdr.rx_calls == 2  # discard_buffers consumed at start-up

    info = src.info
    assert isinstance(info, StreamInfo)
    assert info.sample_rate_hz == 2.5e6 and info.center_freq_hz == 2.437e9
    assert info.rx_channels == (0,) and info.gain_db == 30.0
    assert info.hardware == hw.hw_string(f"pluto-iio {FW_VERSION}")
    assert "0=SMA RX1" in info.description and URI in info.description
    assert info.rf_bandwidth_hz is None and info.bandwidth_hz == 2.5e6
    assert src.rf_ports == ("SMA RX1",) and src.channels == (0,)
    assert src.uri == URI and src.sdr is sdr and src.gain_mode == "manual"
    assert src.warnings == []
    assert src.hardware_gain_db() == (30.0,)
    extra = src.sigmf_extra_global()
    assert extra["antsdr:rf_ports"] == ["SMA RX1"] and extra["antsdr:uri"] == URI
    assert extra["antsdr:gain_mode"] == "manual" and extra["antsdr:adc_bits"] == 12
    src.close()


def test_read_scales_counts_and_spans_buffer_boundaries():
    fake = make_fake_adi()
    with open_e200(fake) as src:
        (sdr,) = fake.instances
        first = src.read(1500)  # buffers 2 and 3, 500 samples left over
        assert first.dtype == np.complex64 and first.shape == (1500,)
        assert first.flags.c_contiguous
        np.testing.assert_array_equal(first, expected_iq(2000, 1500))
        assert sdr.rx_calls == 4
        second = src.read(700)  # remainder 500 + 200 of buffer 4
        np.testing.assert_array_equal(second, expected_iq(3500, 700))
        assert sdr.rx_calls == 5
        one = src.read(1)
        np.testing.assert_array_equal(one, expected_iq(4200, 1))
        assert sdr.rx_calls == 5
        big = src.read(4799)  # exactly drains buffer 8 -> no remainder
        np.testing.assert_array_equal(big, expected_iq(4201, 4799))
        assert sdr.rx_calls == 9
        nxt = src.read(10)
        np.testing.assert_array_equal(nxt, expected_iq(9000, 10))
        assert sdr.rx_calls == 10
        # exact 12-bit scaling: -2048 -> -1.0, +2047 -> 2047/2048
        full = np.concatenate([first, second, one, big, nxt])
        assert full.real.min() == -1.0 and full.real.max() == np.float32(2047 / 2048)
        assert full.imag.min() == -1.0
        with pytest.raises(ValueError):
            src.read(0)
        chunks = list(itertools.islice(src.iter_chunks(3000), 3))
        assert [c.shape for c in chunks] == [(3000,)] * 3


def test_agc_modes_skip_the_manual_gain_write():
    fake = make_fake_adi()
    with open_e200(fake, gain_mode="fast_attack") as src:
        (sdr,) = fake.instances
        names = [name for name, _ in sdr.writes]
        assert "gain_control_mode_chan0" in names and "rx_hardwaregain_chan0" not in names
        assert dict(sdr.writes)["gain_control_mode_chan0"] == "fast_attack"
        assert src.info.gain_db is None
        assert "AGC fast_attack" in src.info.description
        assert src.hardware_gain_db() == (71.0,)  # whatever the AGC currently holds
        assert src.sigmf_extra_global()["antsdr:gain_mode"] == "fast_attack"


def test_retune_discards_buffers_and_updates_info():
    fake = make_fake_adi()
    with open_e200(fake) as src:
        (sdr,) = fake.instances
        src.read(500)  # buffer 2 read, 500 samples remain
        assert sdr.rx_calls == 3
        src.retune(5.8e9)
        assert sdr.writes[-1] == ("rx_lo", 5_800_000_000)
        assert sdr.rx_calls == 5  # two buffers discarded
        np.testing.assert_array_equal(src.read(10), expected_iq(5000, 10))  # remainder dropped
        assert src.info.center_freq_hz == 5.8e9
        assert src.info.sample_rate_hz == 2.5e6 and src.info.rx_channels == (0,)
        assert src.info.hardware == hw.hw_string(f"pluto-iio {FW_VERSION}")
        n_writes = len(sdr.writes)
        with pytest.raises(ValueError):
            src.retune(50e6)  # below the LO range: nothing written
        assert len(sdr.writes) == n_writes and src.info.center_freq_hz == 5.8e9


def test_two_channels_use_ad9361_and_return_2_by_n():
    fake = make_fake_adi()
    with open_e200(fake, channels=(0, 1), buffer_size=512, discard_buffers=1) as src:
        (sdr,) = fake.instances
        assert isinstance(sdr, fake.ad9361)
        names = [name for name, _ in sdr.writes]
        assert names[0] == "rx_enabled_channels" and sdr.rx_enabled_channels == [0, 1]
        assert names.index("gain_control_mode_chan0") < names.index("rx_hardwaregain_chan0")
        assert names.index("gain_control_mode_chan1") < names.index("rx_hardwaregain_chan1")
        assert sdr.rx_hardwaregain_chan0 == 30.0 and sdr.rx_hardwaregain_chan1 == 30.0
        writes = dict(sdr.writes)
        assert writes["tx_hardwaregain_chan0"] == -89 and writes["tx_hardwaregain_chan1"] == -89
        x = src.read(1000)
        assert x.shape == (2, 1000) and x.dtype == np.complex64 and x.flags.c_contiguous
        np.testing.assert_array_equal(x[0], expected_iq(512, 1000, 0))
        np.testing.assert_array_equal(x[1], expected_iq(512, 1000, 1))
        y = src.read(100)
        np.testing.assert_array_equal(y[1], expected_iq(1512, 100, 1))
        assert src.info.rx_channels == (0, 1) and src.info.n_channels == 2
        assert src.rf_ports == ("SMA RX1", "IPEX RX2")
        assert "1=IPEX RX2" in src.info.description
        assert src.sigmf_extra_global()["antsdr:rf_ports"] == ["SMA RX1", "IPEX RX2"]
        assert src.hardware_gain_db() == (30.0, 30.0)
        assert next(src.iter_chunks(64)).shape == (2, 64)


def test_ipex_only_channel_streams_one_dimensional():
    fake = make_fake_adi()
    with open_e200(fake, channels=(1,), buffer_size=256, discard_buffers=0) as src:
        (sdr,) = fake.instances
        assert isinstance(sdr, fake.ad9361) and sdr.rx_enabled_channels == [1]
        names = [name for name, _ in sdr.writes]
        assert "gain_control_mode_chan1" in names and "gain_control_mode_chan0" not in names
        x = src.read(300)
        assert x.shape == (300,)
        np.testing.assert_array_equal(x, expected_iq(0, 300, 1))
        assert src.info.rx_channels == (1,) and src.rf_ports == ("IPEX RX2",)


def test_two_channels_on_1r1t_firmware_explain_the_2r2t_fix():
    # (a) probed before any write: the RX data core lacks voltage2/voltage3
    fake = make_fake_adi(phy_chains=1, data_chains=1)
    with pytest.raises(ValueError, match="fw_setenv mode 2r2t") as excinfo:
        open_e200(fake, channels=(0, 1))
    message = str(excinfo.value)
    assert "voltage2" in message and "IPEX RX2" in message and URI in message
    assert "fw_setenv attr_name compatible" in message and "reboot" in message
    (sdr,) = fake.instances
    assert sdr.writes == [] and sdr.closed and sdr.destroyed == 1
    # (b) the driver object cannot be probed; the chain-1 gain write fails
    fake = make_fake_adi(phy_chains=1, data_chains=1, probe=False)
    with pytest.raises(ValueError, match="fw_setenv mode 2r2t") as excinfo:
        open_e200(fake, channels=(0, 1))
    assert "driver error" in str(excinfo.value) and "NoneType" in str(excinfo.value)
    # (c) writes succeed, buffer creation fails with pyadi's "Channel voltage2 not found"
    fake = make_fake_adi(phy_chains=2, data_chains=1, probe=False)
    with pytest.raises(ValueError, match="fw_setenv mode 2r2t") as excinfo:
        open_e200(fake, channels=(0, 1))
    assert "Channel voltage2 not found" in str(excinfo.value)
    (sdr,) = fake.instances
    assert sdr.closed
    # single channel on 1r1t firmware is fine
    with open_e200(make_fake_adi(phy_chains=1, data_chains=1)) as src:
        assert src.read(5).shape == (5,)


def test_open_failure_is_an_oserror_with_hints():
    fake = make_fake_adi(fail_open=True)
    with pytest.raises(OSError, match="cannot open the E200") as excinfo:
        open_e200(fake)
    text = str(excinfo.value)
    assert URI in text and "192.168.1.10" in text and "No device found" in text


@pytest.mark.parametrize(
    "overrides",
    [
        {"sample_rate_hz": 100e6},
        {"sample_rate_hz": 400e3},
        {"sample_rate_hz": 40e6, "channels": (0, 1)},
        {"center_freq_hz": 50e6},
        {"rf_bandwidth_hz": 100e6},
        {"gain_mode": "auto"},
        {"gain_db": 99.0},
        {"channels": (2,)},
        {"channels": ()},
        {"buffer_size": 0},
        {"discard_buffers": -1},
    ],
)
def test_invalid_configuration_never_opens_the_device(overrides):
    fake = make_fake_adi()
    with pytest.raises(ValueError):
        open_e200(fake, **overrides)
    assert fake.instances == []


def test_close_is_idempotent_and_blocks_further_use():
    fake = make_fake_adi()
    src = open_e200(fake)
    (sdr,) = fake.instances
    with src:
        src.read(10)
    assert src.sdr is None and sdr.destroyed == 1 and sdr.closed
    src.close()
    assert sdr.destroyed == 1
    for call in (lambda: src.read(1), lambda: src.retune(2.4e9), src.hardware_gain_db):
        with pytest.raises(ValueError):
            call()
    assert "closed" in repr(src) and "E200Source(" in repr(src)
    assert src.info.center_freq_hz == 2.437e9  # info survives close


def test_firmware_tag_override_and_detection():
    fake = make_fake_adi()
    with open_e200(fake, firmware="uhd") as src:
        assert src.info.hardware == "MicroPhase ANTSDR E200 (Zynq-7020, AD9363, fw=uhd)"
    with open_e200(make_fake_adi(ctx_attrs={})) as src:
        assert src.info.hardware == hw.hw_string("pluto-iio")
    with open_e200(make_fake_adi(ctx_attrs={"fw_version": FakeAttr(" v0.38 ")})) as src:
        assert src.info.hardware == hw.hw_string("pluto-iio v0.38")


def test_host_ceiling_warning_is_kept_and_logged(caplog):
    fake = make_fake_adi()
    with (
        caplog.at_level(logging.WARNING, logger="antsdr_toolkit.device.e200"),
        open_e200(fake, sample_rate_hz=30.72e6, rf_bandwidth_hz=18e6) as src,
    ):
        assert len(src.warnings) == 1 and "host-link" in src.warnings[0]
        assert src.info.rf_bandwidth_hz == 18e6 and src.info.bandwidth_hz == 18e6
    assert any("host-link" in rec.getMessage() for rec in caplog.records)


# --------------------------------------------------------------------------
# lazy import of pyadi-iio
# --------------------------------------------------------------------------
def test_default_import_path_uses_sys_modules_adi(monkeypatch):
    fake = make_fake_adi()
    monkeypatch.setitem(sys.modules, "adi", fake)
    assert import_adi() is fake
    with E200Source(URI, sample_rate_hz=4e6, center_freq_hz=915e6, buffer_size=64,
                    discard_buffers=0) as src:
        assert fake.instances and src.read(8).shape == (8,)


def test_open_source_factory_matches_the_constructor():
    fake = make_fake_adi()
    with open_source(URI, sample_rate_hz=4e6, center_freq_hz=915e6, gain_db=20.0,
                     buffer_size=128, discard_buffers=0, adi_module=fake) as src:
        assert isinstance(src, E200Source) and src.info.gain_db == 20.0
        assert fake.instances[0].rx_hardwaregain_chan0 == 20.0
        np.testing.assert_array_equal(src.read(130), expected_iq(0, 130))


def test_missing_pyadi_gives_install_instructions(monkeypatch):
    monkeypatch.setitem(sys.modules, "adi", None)  # makes ``import adi`` raise ImportError
    with pytest.raises(ImportError, match=r"antsdr-toolkit\[e200\]") as excinfo:
        E200Source(URI, sample_rate_hz=4e6, center_freq_hz=915e6)
    assert "libiio" in str(excinfo.value)


class _BrokenBindingFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Emulates pylibiio without the native library: ``import adi`` raises AttributeError."""

    def find_spec(self, name, path=None, target=None):
        if name == "adi":
            return importlib.util.spec_from_loader(name, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise AttributeError("python: undefined symbol: iio_get_backends_count")


def test_broken_libiio_binding_is_reported_as_importerror(monkeypatch):
    monkeypatch.delitem(sys.modules, "adi", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BrokenBindingFinder(), *sys.meta_path])
    with pytest.raises(ImportError, match="iio_get_backends_count") as excinfo:
        import_adi()
    assert "pip install" in str(excinfo.value)


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------
def test_probe_via_libiio_context():
    out = probe(URI, iio_module=make_fake_iio())
    assert out["backend"] == "libiio" and out["uri"] == URI
    assert out["context_attrs"]["fw_version"] == FW_VERSION
    assert out["devices"] == ["ad9361-phy", "cf-ad9361-lpc", "cf-ad9361-dds-core-lpc"]
    assert out["rx_data_channels"] == ["voltage0", "voltage1", "voltage2", "voltage3"]
    assert out["two_channel_capable"] is True
    assert out["rx_lo_hz"] == 2.4e9 and out["sample_rate_hz"] == 30.72e6
    assert out["rf_bandwidth_hz"] == 18e6
    assert out["gain_control_mode"] == {0: "slow_attack", 1: "slow_attack"}
    assert out["rx_hardwaregain_db"] == {0: 71.0, 1: 71.0}
    assert out["rf_ports"] == {0: "SMA RX1", 1: "IPEX RX2"}
    assert out["hardware"] == hw.hw_string(f"pluto-iio {FW_VERSION}")
    one = probe(URI, iio_module=make_fake_iio(data_chains=1))
    assert one["two_channel_capable"] is False and one["rf_ports"] == {0: "SMA RX1"}


def test_probe_via_pyadi_fallback():
    fake = make_fake_adi()
    out = probe(URI, adi_module=fake)
    (sdr,) = fake.instances
    assert isinstance(sdr, fake.ad9361) and sdr.closed and sdr.destroyed == 1
    assert out["backend"] == "pyadi-iio"
    assert out["two_channel_capable"] is True
    assert out["rx_lo_hz"] == 2.4e9 and out["sample_rate_hz"] == 30.72e6
    assert out["rf_bandwidth_hz"] == 18e6
    assert out["gain_control_mode"] == {0: "slow_attack", 1: "slow_attack"}
    assert out["rx_hardwaregain_db"][0] == 71.0
    assert out["rf_ports"] == {0: "SMA RX1", 1: "IPEX RX2"}
    assert out["hardware"] == hw.hw_string(f"pluto-iio {FW_VERSION}")
    one = probe(URI, adi_module=make_fake_adi(phy_chains=1, data_chains=1))
    assert one["two_channel_capable"] is False
    assert one["gain_control_mode"] == {0: "slow_attack"} and one["rf_ports"] == {0: "SMA RX1"}


def test_probe_without_any_binding_reports_install_help(monkeypatch):
    monkeypatch.setitem(sys.modules, "adi", None)
    monkeypatch.setitem(sys.modules, "iio", None)
    with pytest.raises(ImportError, match="pip install"):
        probe(URI)
