"""Backend registry + ``make_source`` selection, and ``aerix-rf info``'s
never-raises table (T3).

These tests never touch real hardware: every probe is monkeypatched.
"""

from __future__ import annotations

import argparse
import json

import pytest

from aerix_rf.config import Config
from aerix_rf.sdr import registry as reg
from aerix_rf.sdr.capture import ReceiverCapabilities, make_source


def _entry(name, available, reason, factory=None):
    def probe():
        return available, reason
    if factory is None:
        def factory(cfg):  # noqa: ARG001
            raise AssertionError(f"{name} factory should not be called")
    return reg.BackendEntry(name, factory, probe, None)


def test_auto_order_all_unavailable_lists_every_backend_with_reason(monkeypatch):
    fake = {
        "libhackrf": _entry("libhackrf", False, "libhackrf.so not found"),
        "soapy": _entry("soapy", False, "SoapySDR not importable"),
        "hackrf_transfer": _entry("hackrf_transfer", False, "hackrf_transfer not on PATH"),
    }
    monkeypatch.setattr(reg, "REGISTRY", fake)
    monkeypatch.setattr(reg, "AUTO_ORDER", ("libhackrf", "soapy", "hackrf_transfer"))
    cfg = Config(sim=False, iq_file="")
    with pytest.raises(RuntimeError) as ei:
        make_source(cfg)
    msg = str(ei.value)
    for name, reason in (("libhackrf", "libhackrf.so not found"),
                         ("soapy", "SoapySDR not importable"),
                         ("hackrf_transfer", "hackrf_transfer not on PATH")):
        assert name in msg and reason in msg


def test_auto_order_picks_first_available(monkeypatch):
    calls = []

    class DummySource:
        def __init__(self, cfg):
            calls.append(cfg)

    fake = {
        "libhackrf": _entry("libhackrf", False, "not present"),
        "soapy": _entry("soapy", True, "importable", factory=DummySource),
        "hackrf_transfer": _entry("hackrf_transfer", True, "on PATH",
                                  factory=lambda cfg: (_ for _ in ()).throw(
                                      AssertionError("should not reach hackrf_transfer"))),
    }
    monkeypatch.setattr(reg, "REGISTRY", fake)
    monkeypatch.setattr(reg, "AUTO_ORDER", ("libhackrf", "soapy", "hackrf_transfer"))
    cfg = Config(sim=False, iq_file="")
    src = make_source(cfg)
    assert isinstance(src, DummySource)
    assert calls == [cfg]


def test_explicit_unknown_backend_raises_clear_error():
    cfg = Config(sim=False, iq_file="")
    with pytest.raises(RuntimeError) as ei:
        make_source(cfg, prefer="not_a_real_backend")
    msg = str(ei.value)
    assert "not_a_real_backend" in msg
    assert "libhackrf" in msg  # names the known backends


def test_explicit_unavailable_backend_raises_clear_error(monkeypatch):
    fake = {"libhackrf": _entry("libhackrf", False, "libhackrf.so not found")}
    monkeypatch.setattr(reg, "REGISTRY", fake)
    cfg = Config(sim=False, iq_file="")
    with pytest.raises(RuntimeError) as ei:
        make_source(cfg, prefer="libhackrf")
    assert "libhackrf" in str(ei.value) and "not found" in str(ei.value)


# --- cli wiring: --backend help, HackRF-only flags, receiver metadata --------

def test_cli_backend_help_lists_every_registry_name():
    from aerix_rf import cli
    ap = cli.build_parser()
    lock = next(a for a in ap._subparsers._group_actions[0].choices["lock"]._actions
               if a.dest == "backend")
    for name in reg.REGISTRY:
        assert name in lock.help


def test_cli_hackrf_only_flag_rejected_for_other_backend():
    from aerix_rf import cli
    ns = argparse.Namespace(sim=False, center_mhz=None, backend="antsdr_iio",
                            lna=16, vga=None, amp=False, sample_rate=None,
                            gain_db=None, gain_mode=None, antsdr_uri=None, antsdr_profile=None)
    with pytest.raises(SystemExit):
        cli._cfg_from(ns)


def test_cli_hackrf_flags_ok_for_hackrf_backend():
    from aerix_rf import cli
    ns = argparse.Namespace(sim=False, center_mhz=None, backend="libhackrf",
                            lna=16, vga=24, amp=True, sample_rate=None,
                            gain_db=None, gain_mode=None, antsdr_uri=None, antsdr_profile=None)
    cfg = cli._cfg_from(ns)
    assert cfg.lna_gain == 16 and cfg.vga_gain == 24 and cfg.amp is True


def test_cli_antsdr_flags_flow_into_config():
    from aerix_rf import cli
    ns = argparse.Namespace(sim=False, center_mhz=2437.0, backend="antsdr_iio",
                            lna=None, vga=None, amp=False, sample_rate=8_500_000.0,
                            gain_db=55.0, gain_mode="agc_slow",
                            antsdr_uri="ip:10.0.0.5", antsdr_profile="antsdr_13p44")
    cfg = cli._cfg_from(ns)
    assert cfg.antsdr_uri == "ip:10.0.0.5"
    assert cfg.antsdr_profile == "antsdr_13p44"
    assert cfg.gain_mode == "agc_slow"
    assert cfg.gain_db == 55.0
    assert cfg.sample_rate == 8_500_000.0 and cfg.sample_rate_requested is True


def test_cli_receiver_meta_uses_source_not_cfg_defaults(monkeypatch):
    """Reproduces the T4b-1 bug: cfg.sample_rate is the Config default (20e6);
    the constructed source's actual sample_rate (12.288e6, from its profile)
    and the registry backend name must be what end up in session metadata."""
    import sys
    from aerix_rf import cli
    from aerix_rf.config import Config
    from tests.test_antsdr_iio import _build_fake_iio
    from aerix_rf.sdr.antsdr_iio import AntsdrIIOSource

    monkeypatch.setitem(sys.modules, "iio", _build_fake_iio())
    cfg = Config(sim=False, center_freq_mhz=2437.0)   # sample_rate stays the 20e6 default
    src = AntsdrIIOSource(center_freq_hz=cfg.center_freq_mhz * 1e6, window_seconds=0.01)
    try:
        meta = cli._receiver_meta(src, cfg)
        assert meta["sample_rate"] == 12_288_000.0    # not cfg.sample_rate (20e6)
        assert meta["backend"] == "antsdr_iio"          # registry name, not the class name
        assert meta["center_freq_hz"] == 2437e6
        assert meta["lna_gain"] is None and meta["vga_gain"] is None and meta["amp"] is None
    finally:
        src.close()


def test_antsdr_iio_reports_unavailable_with_reason():
    entry = reg.REGISTRY["antsdr_iio"]
    available, reason = entry.probe()
    assert available is False
    assert reason  # non-empty, explains why (T4 not implemented yet)
    assert "antsdr_iio" not in reg.AUTO_ORDER  # placeholder must not be auto-selected


def test_registry_covers_all_documented_backends():
    for name in ("libhackrf", "hackrf_transfer", "soapy", "file", "sim", "antsdr_iio"):
        assert name in reg.REGISTRY


@pytest.mark.parametrize("name", ["libhackrf", "hackrf_transfer", "soapy", "sim"])
def test_static_capabilities_populated(name):
    caps = reg.REGISTRY[name].capabilities
    assert isinstance(caps, ReceiverCapabilities)
    assert caps.backend == name if name != "sim" else caps.backend == "sim"
    assert caps.tuning_range_hz[1] > caps.tuning_range_hz[0]
    assert caps.sample_rates_hz[1] > 0


def test_hackrf_capabilities_values():
    caps = reg.REGISTRY["libhackrf"].capabilities
    assert caps.receiver_type == "hackrf"
    assert caps.tuning_range_hz == (1e6, 6e9)
    assert caps.sample_rates_hz == (2e6, 20e6)
    assert caps.max_instantaneous_bw_hz == 20e6
    assert caps.native_iq_format == "cs8"
    assert caps.native_full_scale == 128.0
    assert caps.supports_drop_reporting is True
    assert caps.supports_sweep is True
    names = {g.name: g for g in caps.gain_stages}
    assert names["lna"].min_db == 0.0 and names["lna"].max_db == 40.0 and names["lna"].step_db == 8.0
    assert names["vga"].min_db == 0.0 and names["vga"].max_db == 62.0 and names["vga"].step_db == 2.0
    assert names["amp"].max_db == 14.0


def test_file_capabilities_none_in_registry():
    # "file" capabilities depend on the session/meta being replayed, not on a
    # static registry entry -- FileIQSource.capabilities is what's authoritative.
    assert reg.REGISTRY["file"].capabilities is None


# --- aerix-rf info: never raises on a host with no attached devices ------------

def test_cmd_info_never_raises_with_no_devices(monkeypatch):
    from aerix_rf import cli

    fake = {
        "libhackrf": _entry("libhackrf", False, "libhackrf.so not found"),
        "hackrf_transfer": _entry("hackrf_transfer", False, "not on PATH"),
        "soapy": _entry("soapy", False, "not importable"),
        "file": _entry("file", True, "no hardware required"),
        "sim": reg.REGISTRY["sim"],
        "antsdr_iio": _entry("antsdr_iio", False, "not implemented yet"),
    }
    monkeypatch.setattr(reg, "REGISTRY", fake)
    monkeypatch.setattr(reg, "AUTO_ORDER", ("libhackrf", "soapy", "hackrf_transfer"))
    # cmd_info imports REGISTRY/AUTO_ORDER from aerix_rf.sdr.registry at call time,
    # so patching the module's attributes (above) is sufficient.

    ns = argparse.Namespace(backend=None, sim=False, center_mhz=None, sample_rate=None,
                            lna=None, vga=None, amp=False, json=False, verbose=False)
    rc = cli.cmd_info(ns)
    assert rc == 0


def test_cmd_info_output_shape(monkeypatch, capsys):
    from aerix_rf import cli

    fake = {
        "libhackrf": _entry("libhackrf", False, "libhackrf.so not found"),
        "hackrf_transfer": _entry("hackrf_transfer", False, "not on PATH"),
        "soapy": _entry("soapy", False, "not importable"),
        "file": _entry("file", True, "no hardware required"),
        "sim": reg.REGISTRY["sim"],
        "antsdr_iio": _entry("antsdr_iio", False, "not implemented yet"),
    }
    monkeypatch.setattr(reg, "REGISTRY", fake)
    monkeypatch.setattr(reg, "AUTO_ORDER", ("libhackrf", "soapy", "hackrf_transfer"))

    ns = argparse.Namespace(backend=None, sim=False, center_mhz=None, sample_rate=None,
                            lna=None, vga=None, amp=False, json=False, verbose=False)
    cli.cmd_info(ns)
    out = json.loads(capsys.readouterr().out)
    assert {"backends", "auto_order", "selected_backend", "capabilities", "model"} <= out.keys()
    assert isinstance(out["backends"], list) and len(out["backends"]) == 6
    for row in out["backends"]:
        assert {"name", "available", "reason"} <= row.keys()
    assert out["selected_backend"] is None  # nothing available
    assert out["capabilities"] is None
    assert "error" not in out  # must not collapse to {"error": ...} on no hardware


def test_cmd_info_selects_available_backend_capabilities(monkeypatch, capsys):
    from aerix_rf import cli

    fake = {
        "libhackrf": _entry("libhackrf", False, "not found"),
        "hackrf_transfer": _entry("hackrf_transfer", False, "not on PATH"),
        "soapy": _entry("soapy", True, "importable", factory=lambda cfg: None),
        "file": _entry("file", True, "no hardware required"),
        "sim": reg.REGISTRY["sim"],
        "antsdr_iio": _entry("antsdr_iio", False, "not implemented yet"),
    }
    from aerix_rf.sdr.capture import hackrf_capabilities
    fake["soapy"] = reg.BackendEntry("soapy", lambda cfg: None, fake["soapy"].probe,
                                     hackrf_capabilities("soapy"))
    monkeypatch.setattr(reg, "REGISTRY", fake)
    monkeypatch.setattr(reg, "AUTO_ORDER", ("libhackrf", "soapy", "hackrf_transfer"))

    ns = argparse.Namespace(backend=None, sim=False, center_mhz=None, sample_rate=None,
                            lna=None, vga=None, amp=False, json=False, verbose=False)
    cli.cmd_info(ns)
    out = json.loads(capsys.readouterr().out)
    assert out["selected_backend"] == "soapy"
    assert out["capabilities"]["backend"] == "soapy"
    assert out["capabilities"]["receiver_type"] == "hackrf"
