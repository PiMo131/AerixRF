"""Minimal fake ``iio`` module, importable by a real subprocess (T7c-1b).

Used ONLY by ``producer_main.py``'s ``--fake-iio`` flag so the whole
``antsdr_iio`` producer path (device open/configure/readback/tune/refill,
ring write, control channel) can be exercised end to end -- via a real
``python -m aerix_rf.sdr.producer_main`` subprocess -- with no ANTSDR
hardware. Deliberately a separate, smaller copy of the fake in
``tests/test_antsdr_iio.py`` (not imported from there): this one must be
importable from a real subprocess by module path, not only from pytest's
``sys.path``/rootdir.

Mimics only the pylibiio shapes ``antsdr_iio_device.AntsdrIioDevice`` calls:
``Context(uri)``, ``ctx.find_device(name)``, ``device.find_channel(id,
is_output)``, ``channel.attrs[name].value``, ``device.set_kernel_buffers_count(n)``,
``iio.Buffer(device, n, cyclic)`` with blocking-free ``refill()``/``read()``.
"""

from __future__ import annotations

import types
from typing import Callable, Optional

import numpy as np


def _default_chunk(n_samples: int) -> bytes:
    """Deterministic interleaved int16 I,Q: I ramps -2048..2047 (period 4096),
    Q is always 0 -- same shape as test_antsdr_iio.py's ramp chunk."""
    k = np.arange(n_samples, dtype=np.int64)
    i_vals = ((k % 4096) - 2048).astype(np.int16)
    q_vals = np.zeros(n_samples, dtype=np.int16)
    raw = np.empty(n_samples * 2, dtype=np.int16)
    raw[0::2] = i_vals
    raw[1::2] = q_vals
    return raw.tobytes()


def build_fake_iio(*, die_after: Optional[int] = None,
                    chunk_fn: Optional[Callable[[int], bytes]] = None) -> types.ModuleType:
    """Build one fresh fake ``iio`` module.

    ``die_after``: the buffer's ``refill()`` raises ``OSError`` on the
    (0-indexed) refill call at this count -- simulates a real libiio
    device-side failure mid-stream (``--fake-iio-die-after`` fault injection).
    """
    chunk_fn = chunk_fn or _default_chunk

    class FakeAttr:
        def __init__(self, value: str = ""):
            self.value = value

    class _AttrDict(dict):
        def __missing__(self, key):
            a = FakeAttr()
            self[key] = a
            return a

    class FakeChannel:
        def __init__(self, cid: str, output: bool):
            self.id = cid
            self.output = output
            self.enabled = False
            self.attrs = _AttrDict()

    class FakeDevice:
        def __init__(self, name: str):
            self.name = name
            self._channels: dict[tuple[str, bool], FakeChannel] = {}
            self.attrs = _AttrDict()
            self.kernel_buffers_count = None

        def find_channel(self, cid: str, is_output: bool = False):
            key = (cid, is_output)
            if key not in self._channels:
                self._channels[key] = FakeChannel(cid, is_output)
            return self._channels[key]

        def set_kernel_buffers_count(self, n: int) -> None:
            self.kernel_buffers_count = n

    class FakeBuffer:
        def __init__(self, device, samples_count, cyclic):
            self.device = device
            self.samples_count = samples_count
            self.cyclic = cyclic
            self._data = b""
            self._refill_count = 0

        def refill(self) -> None:
            idx = self._refill_count
            self._refill_count += 1
            if die_after is not None and idx == die_after:
                raise OSError("fake ANTSDR: injected device-side refill failure")
            self._data = chunk_fn(self.samples_count)

        def read(self) -> bytes:
            return self._data

    class FakeContext:
        def __init__(self, uri: str):
            self.uri = uri
            self.attrs = {"fw_version": "fake-0.1", "hw_model": "FAKE-ANTSDR"}
            self._devices = {
                "ad9361-phy": FakeDevice("ad9361-phy"),
                "cf-ad9361-lpc": FakeDevice("cf-ad9361-lpc"),
            }

        def find_device(self, name: str):
            return self._devices.get(name)

    mod = types.ModuleType("iio")
    mod.Context = FakeContext
    mod.Buffer = FakeBuffer
    return mod
