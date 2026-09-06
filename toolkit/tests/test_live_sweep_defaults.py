"""Regression tests for live E200 sweep timing and host-link defaults."""

from __future__ import annotations

import argparse
import sys
import types

import numpy as np

from antsdr_toolkit import cli_sweep
from antsdr_toolkit.device.base import SampleSource, StreamInfo


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antsdr-tk")
    cli_sweep.register(parser.add_subparsers(dest="command"))
    return parser


def test_live_sweep_defaults_do_not_layer_upstream_delays_on_e200_flush():
    args = _parser().parse_args([
        "sweep", "--uri", "ip:192.168.1.10", "--freqs", "2412,2437,2462",
    ])
    assert args.rate == 10e6
    assert args.dwell == 0.06
    assert args.settle == 0.0
    assert args.discard == 0


class _FakeE200(SampleSource):
    def __init__(self, sample_rate_hz: float, center_freq_hz: float) -> None:
        self._rate = float(sample_rate_hz)
        self._center = float(center_freq_hz)
        self.warnings = ["20.000 MSPS exceeds the stock-IIO continuous host ceiling"]
        self.closed = False

    @property
    def info(self) -> StreamInfo:
        return StreamInfo(self._rate, self._center, hardware="fake-e200")

    def retune(self, center_freq_hz: float) -> None:
        self._center = float(center_freq_hz)

    def read(self, n_samples: int) -> np.ndarray:
        return np.zeros(int(n_samples), dtype=np.complex64)

    def close(self) -> None:
        self.closed = True


def test_explicit_high_rate_driver_warning_is_visible(monkeypatch, capsys):
    made: list[_FakeE200] = []

    def open_source(_uri: str, **kwargs):
        src = _FakeE200(kwargs["sample_rate_hz"], kwargs["center_freq_hz"])
        made.append(src)
        return src

    fake = types.ModuleType("antsdr_toolkit.device.e200")
    fake.open_source = open_source
    monkeypatch.setitem(sys.modules, "antsdr_toolkit.device.e200", fake)

    args = _parser().parse_args([
        "sweep", "--uri", "ip:192.168.1.10", "--freqs", "2437",
        "--rate", "20e6", "--dwell", "0.001", "--fft", "256",
    ])
    assert args.func(args) == 0
    out = capsys.readouterr()
    assert "warning:" in out.err
    assert "continuous host ceiling" in out.err
    assert made and made[0].closed
