"""Tests for antsdr_toolkit.device.base (StreamInfo, SampleSource) and file_source."""

from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest

from antsdr_toolkit.device.base import IQ_DTYPE, SampleSource, StreamInfo, empty_iq
from antsdr_toolkit.device.file_source import SigmfFileSource
from antsdr_toolkit.io.sigmf_io import write_sigmf

N = 10_000
INFO = StreamInfo(1e6, 433.92e6, rx_channels=(0,), gain_db=20.0, hardware="antsdr-e200",
                  description="ramp", rf_bandwidth_hz=800e3)


def ramp(n: int, offset: int = 0) -> np.ndarray:
    """Index-encoded IQ so every sample reveals its position: x[i] = i - 1j*i."""
    idx = np.arange(offset, offset + n, dtype=np.float32)
    return (idx - 1j * idx).astype(np.complex64)


@pytest.fixture(scope="module")
def recording(tmp_path_factory) -> pathlib.Path:
    stem = tmp_path_factory.mktemp("rec") / "ramp"
    write_sigmf(stem, ramp(N), INFO)
    return stem


@pytest.fixture(scope="module")
def two_channel(tmp_path_factory) -> pathlib.Path:
    stem = tmp_path_factory.mktemp("rec2") / "two"
    x = np.stack([ramp(500), -ramp(500)])
    write_sigmf(stem, x, StreamInfo(2e6, 915e6, rx_channels=(0, 1), hardware="synthetic"))
    return stem


# --------------------------------------------------------------------------
# StreamInfo / SampleSource contract
# --------------------------------------------------------------------------
def test_stream_info_bandwidth_defaults_to_sample_rate_and_edges():
    info = StreamInfo(30.72e6, 2.437e9)
    assert info.bandwidth_hz == 30.72e6
    assert info.freq_lower_hz == pytest.approx(2.437e9 - 15.36e6)
    assert info.freq_upper_hz == pytest.approx(2.437e9 + 15.36e6)
    narrow = info.replace(rf_bandwidth_hz=20e6)
    assert narrow.bandwidth_hz == 20e6 and narrow.sample_rate_hz == 30.72e6
    assert info.n_channels == 1 and info.hardware == "unknown"


def test_stream_info_normalises_and_validates():
    info = StreamInfo("1000000", 100, rx_channels=[1, 0], gain_db=3)
    assert info.sample_rate_hz == 1e6 and isinstance(info.sample_rate_hz, float)
    assert info.rx_channels == (1, 0) and info.gain_db == 3.0
    assert info == StreamInfo(1e6, 100.0, rx_channels=(1, 0), gain_db=3.0)
    assert info.to_dict()["rx_channels"] == [1, 0] and info.to_dict()["bandwidth_hz"] == 1e6
    assert "MS/s" in str(info)
    for bad in ({"sample_rate_hz": 0, "center_freq_hz": 1},
                {"sample_rate_hz": 1, "center_freq_hz": 1, "rx_channels": ()},
                {"sample_rate_hz": 1, "center_freq_hz": 1, "rf_bandwidth_hz": -1}):
        with pytest.raises(ValueError):
            StreamInfo(**bad)


def test_empty_iq_shapes():
    assert empty_iq().shape == (0,) and empty_iq().dtype == IQ_DTYPE
    assert empty_iq(2).shape == (2, 0)


class _Counting(SampleSource):
    """Minimal finite source: yields ``total`` samples then an empty chunk."""

    def __init__(self, total: int) -> None:
        self.total, self.pos, self.closed = total, 0, 0

    @property
    def info(self) -> StreamInfo:
        return StreamInfo(1.0, 0.0, hardware="test")

    def read(self, n_samples: int) -> np.ndarray:
        n = min(n_samples, self.total - self.pos)
        self.pos += n
        return np.ones(n, dtype=IQ_DTYPE)

    def close(self) -> None:
        self.closed += 1


def test_sample_source_contract():
    with pytest.raises(TypeError):
        SampleSource()  # abstract
    with _Counting(10) as src:
        sizes = [c.shape[-1] for c in src.iter_chunks(4)]
        assert sizes == [4, 4, 2]
        assert src.read(4).shape == (0,)
        with pytest.raises(NotImplementedError):
            src.retune(1e9)
        with pytest.raises(ValueError):
            list(src.iter_chunks(0))
    assert src.closed == 1


# --------------------------------------------------------------------------
# SigmfFileSource
# --------------------------------------------------------------------------
def test_info_comes_from_metadata(recording):
    with SigmfFileSource(recording) as src:
        assert src.info == INFO  # hardware, gain, rf bandwidth all preserved
        assert src.n_samples == N and src.duration_s == pytest.approx(N / 1e6)
        assert src.position == 0 and src.remaining == N and not src.loop
        assert src.metadata["global"]["core:datatype"] == "cf32_le"
        assert "SigmfFileSource(" in repr(src)


@pytest.mark.parametrize("suffix", ["", ".sigmf-meta", ".sigmf-data"])
def test_accepts_stem_meta_or_data_path(recording, suffix):
    with SigmfFileSource(str(recording) + suffix) as src:
        assert src.n_samples == N


def test_read_until_exhausted(recording):
    with SigmfFileSource(recording) as src:
        sizes = []
        pos = 0
        while True:
            chunk = src.read(3000)
            if chunk.shape[-1] == 0:
                break
            assert chunk.dtype == np.complex64 and chunk.flags.writeable
            np.testing.assert_array_equal(chunk, ramp(chunk.shape[0], pos))
            pos += chunk.shape[0]
            sizes.append(chunk.shape[0])
        assert sizes == [3000, 3000, 3000, 1000]
        assert src.read(10).shape == (0,)  # stays exhausted
        assert src.remaining == 0


def test_iter_chunks_and_seek(recording):
    with SigmfFileSource(recording) as src:
        chunks = list(src.iter_chunks(4096))
        assert [c.shape[0] for c in chunks] == [4096, 4096, 1808]
        np.testing.assert_array_equal(np.concatenate(chunks), ramp(N))
        src.seek(9990)
        np.testing.assert_array_equal(src.read(100), ramp(10, 9990))
        with pytest.raises(ValueError):
            src.seek(N + 1)


def test_loop_wraps_and_always_returns_full_chunks(recording):
    with SigmfFileSource(recording, loop=True) as src:
        assert src.loop
        first = src.read(7000)
        second = src.read(7000)
        np.testing.assert_array_equal(first, ramp(7000))
        np.testing.assert_array_equal(second, np.concatenate([ramp(3000, 7000), ramp(4000)]))
        assert src.position == 4000
        big = src.read(25_000)  # spans several wraps
        assert big.shape == (25_000,)
        np.testing.assert_array_equal(big[:6000], ramp(6000, 4000))
        np.testing.assert_array_equal(big[6000:16000], ramp(N))
        src.seek(N + 5)  # modulo when looping
        assert src.position == 5


def test_channel_selection(two_channel):
    with SigmfFileSource(two_channel) as src:
        assert src.info.rx_channels == (0, 1)
        chunk = src.read(100)
        assert chunk.shape == (2, 100)
        np.testing.assert_array_equal(chunk[0], ramp(100))
        np.testing.assert_array_equal(chunk[1], -ramp(100))
        rest = list(src.iter_chunks(300))
        assert [c.shape for c in rest] == [(2, 300), (2, 100)]
        assert src.read(1).shape == (2, 0)
    with SigmfFileSource(two_channel, channel=1) as src:
        assert src.info.rx_channels == (1,) and src.info.n_channels == 1
        chunk = src.read(50)
        assert chunk.shape == (50,) and chunk.flags.c_contiguous
        np.testing.assert_array_equal(chunk, -ramp(50))
    with SigmfFileSource(two_channel, channel=1, loop=True) as src:
        assert src.read(1200).shape == (1200,)
    with pytest.raises(ValueError):
        SigmfFileSource(two_channel, channel=2)


def test_close_is_idempotent_and_read_after_close_fails(recording):
    src = SigmfFileSource(recording)
    src.close()
    src.close()
    with pytest.raises(ValueError):
        src.read(1)
    with pytest.raises(NotImplementedError):
        src.retune(1e9)
    with pytest.raises(ValueError):
        SigmfFileSource(recording).read(0)


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        SigmfFileSource("/nonexistent/capture.sigmf-meta")


def test_ci16_firmware_capture_without_hw_reports_file(tmp_path):
    """A capture written by third-party tooling (ci16_le, no core:hw) replays scaled."""
    comps = np.array([16384, -16384, 32767, 0], dtype="<i2")
    (tmp_path / "fw.sigmf-data").write_bytes(comps.tobytes())
    (tmp_path / "fw.sigmf-meta").write_text(json.dumps({
        "global": {"core:datatype": "ci16_le", "core:sample_rate": 61.44e6},
        "captures": [{"core:sample_start": 0, "core:frequency": 5.8e9}],
    }))
    with SigmfFileSource(tmp_path / "fw") as src:
        assert src.info.hardware == "file"
        assert src.info.sample_rate_hz == 61.44e6 and src.info.center_freq_hz == 5.8e9
        np.testing.assert_array_equal(
            src.read(10), np.array([0.5 - 0.5j, 32767 / 32768 + 0j], dtype=np.complex64)
        )


def test_empty_recording(tmp_path):
    write_sigmf(tmp_path / "empty", np.empty(0, dtype=np.complex64), INFO)
    with SigmfFileSource(tmp_path / "empty", loop=True) as src:
        assert src.n_samples == 0
        assert src.read(5).shape == (0,)
        assert list(src.iter_chunks(5)) == []
