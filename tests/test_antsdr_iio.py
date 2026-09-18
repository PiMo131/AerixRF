"""Hardware-free tests for aerix_rf.sdr.antsdr_iio.AntsdrIIOSource.

No real ANTSDR / libiio is available in CI, so every test injects a fake
`iio` module (Context/Device/Channel/Buffer) via ``monkeypatch.setitem`` on
``sys.modules``. The fake mimics only the pylibiio shapes this backend
actually calls: ``Context(uri)``, ``ctx.find_device(name)``,
``device.find_channel(id, is_output)``, ``channel.attrs[name].value``,
``device.set_kernel_buffers_count(n)``, ``iio.Buffer(device, n, cyclic)``
with blocking-free ``refill()``/``read()``.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from aerix_rf.sdr import antsdr_iio, registry


# --- fake iio module builder -------------------------------------------------

def _make_ramp_chunk(n_samples: int) -> bytes:
    """Deterministic interleaved int16 I,Q: I ramps -2048..2047 (period 4096,
    endpoints included every period), Q is always 0. Large enough test windows
    always contain >=1 full period, so both scaling endpoints are exercised."""
    k = np.arange(n_samples, dtype=np.int64)
    i_vals = ((k % 4096) - 2048).astype(np.int16)
    q_vals = np.zeros(n_samples, dtype=np.int16)
    raw = np.empty(n_samples * 2, dtype=np.int16)
    raw[0::2] = i_vals
    raw[1::2] = q_vals
    return raw.tobytes()


def _build_fake_iio(chunk_fn=None, ctx_attrs=None):
    chunk_fn = chunk_fn or _make_ramp_chunk
    ctx_attrs = dict(ctx_attrs or {"fw_version": "v0.36", "hw_model": "ANTSDR E200"})

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

        def refill(self) -> None:
            self._data = chunk_fn(self.samples_count)

        def read(self) -> bytes:
            return self._data

    class FakeContext:
        def __init__(self, uri: str):
            self.uri = uri
            self.attrs = dict(ctx_attrs)
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


def _make_source(monkeypatch, **kwargs):
    fake = _build_fake_iio()
    monkeypatch.setitem(sys.modules, "iio", fake)
    kwargs.setdefault("window_seconds", 0.001)   # keep windows tiny/fast in tests
    kwargs.setdefault("buffer_samples", 4096)
    kwargs.setdefault("kernel_buffers", 2)
    return antsdr_iio.AntsdrIIOSource(**kwargs)


# --- configuration / attrs ----------------------------------------------------

def test_default_profile_sets_attrs(monkeypatch):
    src = _make_source(monkeypatch)
    try:
        rx_ctrl = src._rx_ctrl
        assert rx_ctrl.attrs["sampling_frequency"].value == "12288000"
        assert rx_ctrl.attrs["rf_bandwidth"].value == "10000000"
        assert rx_ctrl.attrs["gain_control_mode"].value == "manual"
        assert rx_ctrl.attrs["hardwaregain"].value == "40"
        assert src.rxdev.kernel_buffers_count == 2
        assert src._i_chan.enabled is True
        assert src._q_chan.enabled is True
    finally:
        src.close()


@pytest.mark.parametrize("profile,rate,bw", [
    ("antsdr_13p44", "13440000", "11000000"),
    ("antsdr_11p52", "11520000", "10000000"),
])
def test_named_profiles(monkeypatch, profile, rate, bw):
    src = _make_source(monkeypatch, profile=profile)
    try:
        assert src._rx_ctrl.attrs["sampling_frequency"].value == rate
        assert src._rx_ctrl.attrs["rf_bandwidth"].value == bw
    finally:
        src.close()


def test_unknown_profile_raises(monkeypatch):
    fake = _build_fake_iio()
    monkeypatch.setitem(sys.modules, "iio", fake)
    with pytest.raises(ValueError, match="unknown ANTSDR profile"):
        antsdr_iio.AntsdrIIOSource(profile="does-not-exist")


def test_sample_rate_override_applied_and_recorded(monkeypatch):
    """An explicit --sample-rate overrides the profile's rate, is validated
    against the AD9361 range, and shows up as the effective rate everywhere
    (applied to the device attr, ``src.sample_rate``, window metadata)."""
    src = _make_source(monkeypatch, sample_rate=8_000_000.0)
    try:
        assert src.sample_rate == 8_000_000.0
        assert src._rx_ctrl.attrs["sampling_frequency"].value == "8000000"
        win = next(src.windows())
        assert win.sample_rate == 8_000_000.0
    finally:
        src.close()


def test_sample_rate_override_out_of_range_raises(monkeypatch):
    fake = _build_fake_iio()
    monkeypatch.setitem(sys.modules, "iio", fake)
    with pytest.raises(ValueError, match="outside the ANTSDR/AD9361 capability range"):
        antsdr_iio.AntsdrIIOSource(sample_rate=1.0)  # below 2.083e6


def test_sample_rate_override_above_sustained_ceiling_warns(monkeypatch, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="aerix.rf.sdr.antsdr_iio"):
        src = _make_source(monkeypatch, sample_rate=20_000_000.0)  # above 13.44e6, within chip range
    try:
        assert src.sample_rate == 20_000_000.0
        assert any("sustained" in r.message for r in caplog.records)
    finally:
        src.close()


def test_center_freq_hz_property_reflects_tune(monkeypatch):
    src = _make_source(monkeypatch, center_freq_hz=2440e6)
    try:
        assert src.center_freq_hz == 2440e6
        src.tune(2450e6)
        assert src.center_freq_hz == 2450e6
    finally:
        src.close()


# --- window assembly / scaling -------------------------------------------------

def test_window_length_exact(monkeypatch):
    src = _make_source(monkeypatch)
    try:
        n = int(src.sample_rate * src.window_seconds)
        win = next(src.windows())
        assert win.iq.size == n
        assert win.expected_samples == n
        assert win.sample_rate == src.sample_rate
    finally:
        src.close()


def test_scaling_endpoints(monkeypatch):
    src = _make_source(monkeypatch, window_seconds=0.01)   # several ramp periods
    try:
        win = next(src.windows())
        assert np.isclose(win.iq.real.max(), 2047.0 / 2048.0)
        assert np.isclose(win.iq.real.min(), -1.0)          # -2048 / 2048.0
        assert np.allclose(win.iq.imag, 0.0)                # Q was always 0
    finally:
        src.close()


def test_window_metadata(monkeypatch):
    src = _make_source(monkeypatch)
    try:
        win = next(src.windows())
        assert win.metadata["iq_format"] == "cs16"
        assert win.metadata["iq_full_scale"] == 2048.0
        assert win.metadata["loss_detection"] == "inferred_rate_only"
        assert win.metadata["gain_mode"] == "manual"
        assert win.metadata["gain_db"] == 40.0
        assert win.metadata["receiver_firmware"] == "v0.36"
        assert win.bandwidth_hz == 10.0e6
        assert win.receiver_type == "antsdr"
        assert win.dropped_samples is None   # honest None, never a fabricated 0
    finally:
        src.close()


def test_capabilities(monkeypatch):
    src = _make_source(monkeypatch)
    try:
        caps = src.capabilities
        assert caps.receiver_type == "antsdr"
        assert caps.backend == "antsdr_iio"
        assert caps.native_iq_format == "cs16"
        assert caps.native_full_scale == 2048.0
        assert caps.supports_drop_reporting is False
        assert caps.supports_device_timestamps is False
        assert caps.supports_sweep is False
        assert caps.tuning_range_hz == (70e6, 6e9)
        assert caps.firmware == "v0.36"
        gain_stage = caps.gain_stages[0]
        assert gain_stage.name == "rx"
        assert gain_stage.min_db == 0.0 and gain_stage.max_db == 73.0
        assert caps.gain_modes == ("manual", "agc_slow", "agc_fast")
    finally:
        src.close()


# --- tune ----------------------------------------------------------------------

def test_tune_updates_lo_and_flushes(monkeypatch):
    src = _make_source(monkeypatch, center_freq_hz=2440e6)
    try:
        assert src._lo_ctrl.attrs["frequency"].value == "2440000000"
        flushed = {"called": False}
        monkeypatch.setattr(src._asm, "flush", lambda: flushed.__setitem__("called", True))
        src.tune(2450e6)
        assert src._lo_ctrl.attrs["frequency"].value == "2450000000"
        assert src._center_hz == 2450e6
        assert flushed["called"] is True
    finally:
        src.close()


# --- rate warning ---------------------------------------------------------------

def test_rate_warning_below_threshold(monkeypatch):
    """A producer that has been delivering ~90% of the nominal rate for >= 2s
    of measured stream time must raise rate_warning -- this drives the
    source's ratio -> rate_warning mapping (RATE_WARNING_RATIO=0.999, gated on
    >= 2s of ``stream_rate_elapsed_s``) with a realistic sustained-shortfall
    reading, not just a low ratio with no elapsed time attached (see
    test_no_rate_warning_below_2s for that early-window case)."""
    src = _make_source(monkeypatch)
    try:
        n = int(src.sample_rate * src.window_seconds)
        fake_iq = np.zeros(n, dtype=np.complex64)
        fake_info = {
            "captured_at": 0.0, "center_freq_hz": src._center_hz, "complete": True,
            "dropped_samples": None, "overflow_count": 0, "gap_before_samples": 0,
            "short_reads": 0, "stream_rate_ratio": 0.90, "stream_rate_elapsed_s": 2.5,
            "loss_detection": "inferred_rate_only",
            "channel_id": 0, "bandwidth_hz": src.rf_bandwidth, "timing": {},
        }
        monkeypatch.setattr(src._asm, "read_window", lambda *a, **kw: (fake_iq, fake_info))
        win = next(src.windows())
        assert win.metadata["stream_rate_ratio"] == 0.90
        assert win.metadata["rate_warning"] is True
        assert src._rate_warning is True
    finally:
        src.close()


def test_no_rate_warning_below_2s(monkeypatch):
    """The same low ratio, but before 2s of stream time have been measured,
    must NOT raise rate_warning -- early windows don't have enough data for
    the ratio to be trustworthy yet (see antsdr_iio.windows())."""
    src = _make_source(monkeypatch)
    try:
        n = int(src.sample_rate * src.window_seconds)
        fake_iq = np.zeros(n, dtype=np.complex64)
        fake_info = {
            "captured_at": 0.0, "center_freq_hz": src._center_hz, "complete": True,
            "dropped_samples": None, "overflow_count": 0, "gap_before_samples": 0,
            "short_reads": 0, "stream_rate_ratio": 0.42, "stream_rate_elapsed_s": 0.3,
            "loss_detection": "inferred_rate_only",
            "channel_id": 0, "bandwidth_hz": src.rf_bandwidth, "timing": {},
        }
        monkeypatch.setattr(src._asm, "read_window", lambda *a, **kw: (fake_iq, fake_info))
        win = next(src.windows())
        assert win.metadata["rate_warning"] is False
        assert src._rate_warning is False
    finally:
        src.close()


def test_no_rate_warning_at_full_rate(monkeypatch):
    src = _make_source(monkeypatch)
    try:
        n = int(src.sample_rate * src.window_seconds)
        fake_iq = np.zeros(n, dtype=np.complex64)
        fake_info = {
            "captured_at": 0.0, "center_freq_hz": src._center_hz, "complete": True,
            "dropped_samples": None, "overflow_count": 0, "gap_before_samples": 0,
            "short_reads": 0, "stream_rate_ratio": 1.0, "loss_detection": "inferred_rate_only",
            "channel_id": 0, "bandwidth_hz": src.rf_bandwidth, "timing": {},
        }
        monkeypatch.setattr(src._asm, "read_window", lambda *a, **kw: (fake_iq, fake_info))
        win = next(src.windows())
        assert win.metadata["rate_warning"] is False
    finally:
        src.close()


# --- lifecycle -------------------------------------------------------------------

def test_close_stops_thread(monkeypatch):
    src = _make_source(monkeypatch)
    assert src._thread is not None
    assert src._thread.is_alive()
    src.close()
    assert src._thread is None
    # windows() must not hang forever once the stream is stopped: the
    # generator returns (StopIteration) rather than blocking, so next()'s
    # default is what we get back.
    assert next(src.windows(), "stopped") == "stopped"


def test_missing_devices_raises_clear_error(monkeypatch):
    fake = _build_fake_iio()
    fake.Context = lambda uri: types.SimpleNamespace(
        uri=uri, attrs={}, find_device=lambda name: None,
    )
    monkeypatch.setitem(sys.modules, "iio", fake)
    with pytest.raises(RuntimeError, match="ANTSDR devices not found"):
        antsdr_iio.AntsdrIIOSource()


def test_import_error_message_without_iio(monkeypatch):
    monkeypatch.setitem(sys.modules, "iio", None)   # forces `import iio` to raise ImportError
    with pytest.raises(ImportError, match="uv sync --extra antsdr"):
        antsdr_iio.AntsdrIIOSource()


# --- registry ---------------------------------------------------------------------

def test_registry_probe_available_with_fake_iio(monkeypatch):
    fake = _build_fake_iio()
    monkeypatch.setitem(sys.modules, "iio", fake)
    available, reason = registry.REGISTRY["antsdr_iio"].probe()
    assert available is True
    assert "importable" in reason


def test_registry_probe_unavailable_without_iio(monkeypatch):
    monkeypatch.setitem(sys.modules, "iio", None)
    available, reason = registry.REGISTRY["antsdr_iio"].probe()
    assert available is False
    assert "uv sync --extra antsdr" in reason


def test_registry_static_capabilities():
    caps = registry.REGISTRY["antsdr_iio"].capabilities
    assert caps is not None
    assert caps.receiver_type == "antsdr"
    assert caps.backend == "antsdr_iio"


def test_registry_factory_builds_source(monkeypatch):
    fake = _build_fake_iio()
    monkeypatch.setitem(sys.modules, "iio", fake)
    from aerix_rf.config import Config
    cfg = Config(sim=False)
    src = registry.REGISTRY["antsdr_iio"].factory(cfg)
    try:
        assert isinstance(src, antsdr_iio.AntsdrIIOSource)
        assert src.gain_db == cfg.gain_db
    finally:
        src.close()


def test_make_antsdr_iio_uses_profile_rate_by_default(monkeypatch):
    """cfg.sample_rate carries Config's HackRF-ish 20e6 dataclass default, but
    with no --sample-rate given (sample_rate_requested=False) the factory must
    NOT pass it through -- the backend picks its own profile rate instead."""
    fake = _build_fake_iio()
    monkeypatch.setitem(sys.modules, "iio", fake)
    from aerix_rf.config import Config
    cfg = Config(sim=False, antsdr_profile="antsdr_13p44")
    assert cfg.sample_rate_requested is False
    src = registry.REGISTRY["antsdr_iio"].factory(cfg)
    try:
        assert src.sample_rate == 13_440_000.0   # profile rate, not cfg.sample_rate (20e6)
    finally:
        src.close()


def test_make_antsdr_iio_applies_explicit_sample_rate(monkeypatch):
    fake = _build_fake_iio()
    monkeypatch.setitem(sys.modules, "iio", fake)
    from aerix_rf.config import Config
    cfg = Config(sim=False, sample_rate=8_000_000.0, sample_rate_requested=True)
    src = registry.REGISTRY["antsdr_iio"].factory(cfg)
    try:
        assert src.sample_rate == 8_000_000.0
    finally:
        src.close()


def test_antsdr_not_in_auto_order():
    # ANTSDR is a separate physical box; never auto-selected over HackRF backends.
    assert "antsdr_iio" not in registry.AUTO_ORDER
