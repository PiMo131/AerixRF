"""Tests for antsdr_toolkit.io.sigmf_io: write/read/record SigMF, datatype scaling."""

from __future__ import annotations

import json
import pathlib
import re

import numpy as np
import pytest

from antsdr_toolkit import __version__
from antsdr_toolkit.device.base import StreamInfo
from antsdr_toolkit.io.sigmf_io import (
    SigmfReader,
    SigmfRecorder,
    parse_datatype,
    read_sigmf,
    sigmf_paths,
    stream_info_from_metadata,
    write_sigmf,
)


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(1234)


@pytest.fixture
def info() -> StreamInfo:
    return StreamInfo(
        sample_rate_hz=2e6,
        center_freq_hz=2.437e9,
        rx_channels=(0,),
        gain_db=32.0,
        hardware="antsdr-e200",
        description="unit test capture",
        rf_bandwidth_hz=1.6e6,
    )


def make_iq(rng: np.random.Generator, n: int, channels: int | None = None) -> np.ndarray:
    shape = (n,) if channels is None else (channels, n)
    x = rng.standard_normal(shape) + 1j * rng.standard_normal(shape)
    return (0.1 * x).astype(np.complex64)


def write_raw_dataset(
    directory: pathlib.Path,
    name: str,
    components: np.ndarray,
    datatype: str,
    *,
    extra_global: dict | None = None,
) -> pathlib.Path:
    """Hand-craft a minimal SigMF pair the way third-party (firmware) tools would."""
    data = directory / f"{name}.sigmf-data"
    meta = directory / f"{name}.sigmf-meta"
    data.write_bytes(components.tobytes())
    doc = {
        "global": {"core:datatype": datatype, "core:sample_rate": 1e6, **(extra_global or {})},
        "captures": [{"core:sample_start": 0, "core:frequency": 100e6}],
        "annotations": [],
    }
    meta.write_text(json.dumps(doc))
    return data


# --------------------------------------------------------------------------
# paths / datatypes
# --------------------------------------------------------------------------
def test_sigmf_paths_resolve_stem_and_both_extensions(tmp_path):
    stem = tmp_path / "cap.2437MHz"
    expected = (tmp_path / "cap.2437MHz.sigmf-data", tmp_path / "cap.2437MHz.sigmf-meta")
    assert sigmf_paths(stem) == expected
    assert sigmf_paths(str(stem) + ".sigmf-data") == expected
    assert sigmf_paths(str(stem) + ".sigmf-meta") == expected
    with pytest.raises(ValueError):
        sigmf_paths(".sigmf-data")


@pytest.mark.parametrize(
    "name, itemsize, is_complex, scale",
    [("cf32_le", 4, True, 1.0), ("ci16_le", 2, True, 2**-15), ("ci8", 1, True, 2**-7),
     ("rf32_le", 4, False, 1.0), ("cu8", 1, True, 2**-7)],
)
def test_parse_datatype(name, itemsize, is_complex, scale):
    dt = parse_datatype(name)
    assert dt.component_dtype.itemsize == itemsize
    assert dt.is_complex is is_complex
    assert dt.scale == scale
    assert dt.sample_bytes == itemsize * (2 if is_complex else 1)


@pytest.mark.parametrize("bad", ["cf16_le", "ci16", "xyz", "", "ci128_le"])
def test_parse_datatype_rejects_unknown(bad):
    with pytest.raises(ValueError):
        parse_datatype(bad)


# --------------------------------------------------------------------------
# write / read round trips
# --------------------------------------------------------------------------
def test_write_read_roundtrip_cf32(tmp_path, rng, info):
    x = make_iq(rng, 1000)
    data_path, meta_path = write_sigmf(
        tmp_path / "rt", x, info, datetime_utc="2026-09-05T12:34:56.000000Z"
    )
    assert data_path.name == "rt.sigmf-data" and meta_path.name == "rt.sigmf-meta"
    assert data_path.stat().st_size == 1000 * 8  # cf32: 2 x float32 per sample

    samples, info_back, meta = read_sigmf(meta_path)
    assert samples.dtype == np.complex64 and samples.shape == (1000,)
    np.testing.assert_array_equal(samples, x)
    assert info_back == info  # frozen dataclass equality: every field survived

    glob = meta["global"]
    assert glob["core:datatype"] == "cf32_le"
    assert glob["core:sample_rate"] == 2e6
    assert re.fullmatch(r"\d+\.\d+\.\d+", glob["core:version"])
    assert glob["core:hw"] == "antsdr-e200"
    assert glob["core:description"] == "unit test capture"
    assert glob["core:recorder"] == f"antsdr_toolkit/{__version__}"
    assert len(meta["captures"]) == 1
    assert meta["captures"][0]["core:frequency"] == 2.437e9
    assert meta["captures"][0]["core:datetime"] == "2026-09-05T12:34:56.000000Z"
    assert meta["captures"][0]["core:sample_start"] == 0


def test_default_datetime_is_iso8601_utc(tmp_path, rng, info):
    _, meta_path = write_sigmf(tmp_path / "dt", make_iq(rng, 10), info)
    stamp = json.loads(meta_path.read_text())["captures"][0]["core:datetime"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", stamp)


def test_read_sigmf_mmap_is_readonly_view_and_copy_is_writable(tmp_path, rng, info):
    x = make_iq(rng, 256)
    _, meta_path = write_sigmf(tmp_path / "mm", x, info)
    view, _, _ = read_sigmf(meta_path, mmap=True)
    copy, _, _ = read_sigmf(meta_path, mmap=False)
    assert view.flags.writeable is False
    assert copy.flags.writeable is True
    np.testing.assert_array_equal(view, x)
    np.testing.assert_array_equal(copy, x)


def test_multichannel_roundtrip_is_channel_interleaved(tmp_path, rng):
    info = StreamInfo(1e6, 915e6, rx_channels=(0, 1), hardware="synthetic")
    x = make_iq(rng, 300, channels=2)
    data_path, meta_path = write_sigmf(tmp_path / "mc", x, info)
    # on disk: s0c0, s0c1, s1c0, s1c1, ...
    raw = np.fromfile(data_path, dtype="<c8")
    np.testing.assert_array_equal(raw.reshape(300, 2).T, x)
    samples, info_back, meta = read_sigmf(meta_path)
    assert meta["global"]["core:num_channels"] == 2
    assert samples.shape == (2, 300)
    np.testing.assert_array_equal(samples, x)
    assert info_back.rx_channels == (0, 1)
    samples_copy, _, _ = read_sigmf(meta_path, mmap=False)
    np.testing.assert_array_equal(samples_copy, x)


def test_written_files_validate_and_load_with_reference_sigmf_library(tmp_path, rng, info):
    sigmf = pytest.importorskip("sigmf")
    from sigmf.sigmffile import fromfile

    x = make_iq(rng, 500)
    _, meta_path = write_sigmf(tmp_path / "ref", x, info, annotations=[
        {"core:sample_start": 10, "core:sample_count": 20, "core:label": "wifi"},
    ])
    ref = fromfile(str(meta_path), skip_checksum=True)
    ref.validate()  # raises on schema violation
    np.testing.assert_array_equal(ref.read_samples().reshape(-1).astype(np.complex64), x)
    assert ref.get_global_field(sigmf.SAMPLE_RATE_KEY) == info.sample_rate_hz
    assert ref.get_annotations()[0]["core:label"] == "wifi"

    x2 = make_iq(rng, 64, channels=2)
    _, meta2 = write_sigmf(tmp_path / "ref2", x2, info.replace(rx_channels=(0, 1)))
    ref2 = fromfile(str(meta2), skip_checksum=True)
    ref2.validate()
    np.testing.assert_array_equal(ref2.read_samples().T.astype(np.complex64), x2)


def test_invalid_datetime_is_rejected_before_data_is_written(tmp_path, rng, info):
    pytest.importorskip("sigmf")
    with pytest.raises(ValueError, match="not valid SigMF"):
        write_sigmf(tmp_path / "bad", make_iq(rng, 8), info, datetime_utc="yesterday")
    assert not (tmp_path / "bad.sigmf-data").exists()


def test_extra_global_passthrough_and_protected_keys(tmp_path, rng, info):
    _, meta_path = write_sigmf(
        tmp_path / "eg", make_iq(rng, 8), info,
        extra_global={"core:author": "tester", "antsdr:custom": [1, 2]},
    )
    glob = json.loads(meta_path.read_text())["global"]
    assert glob["core:author"] == "tester" and glob["antsdr:custom"] == [1, 2]
    with pytest.raises(ValueError):
        write_sigmf(tmp_path / "eg2", make_iq(rng, 8), info,
                    extra_global={"core:datatype": "ci16_le"})


def test_channel_count_mismatch_raises(tmp_path, rng, info):
    with pytest.raises(ValueError):
        write_sigmf(tmp_path / "bad", make_iq(rng, 8, channels=2), info)
    with pytest.raises(ValueError):
        write_sigmf(tmp_path / "bad2", make_iq(rng, 8), info.replace(rx_channels=(0, 1)))


# --------------------------------------------------------------------------
# fixed-point input formats produced by the E200 firmware
# --------------------------------------------------------------------------
@pytest.mark.parametrize("mmap", [True, False])
def test_read_ci16_le_scales_to_unit_full_scale(tmp_path, mmap):
    comps = np.array([-32768, 0, 32767, 16384, 0, -16384, 1, -1], dtype="<i2")
    data = write_raw_dataset(tmp_path, "i16", comps, "ci16_le")
    samples, info, _meta = read_sigmf(data, mmap=mmap)
    expected = np.array(
        [-1.0 + 0j, 32767 / 32768 + 0.5j, 0 - 0.5j, (1 - 1j) / 32768], dtype=np.complex64
    )
    assert samples.dtype == np.complex64
    np.testing.assert_array_equal(samples, expected)  # exact: scaling is a power of two
    assert info.sample_rate_hz == 1e6 and info.center_freq_hz == 100e6
    assert info.hardware == "unknown" and info.rx_channels == (0,)


def test_read_ci8_scales_to_unit_full_scale(tmp_path):
    comps = np.array([-128, 127, 64, -64], dtype=np.int8)
    data = write_raw_dataset(tmp_path, "i8", comps, "ci8")
    samples, _, _ = read_sigmf(data)
    np.testing.assert_array_equal(
        samples, np.array([-1.0 + (127 / 128) * 1j, 0.5 - 0.5j], dtype=np.complex64)
    )


def test_read_ci16_multichannel_and_header_bytes(tmp_path):
    # 3 samples x 2 channels, preceded by a 4-byte header that must be skipped
    comps = np.arange(12, dtype="<i2") * 1000
    padded = np.concatenate([np.zeros(2, "<i2"), comps])
    data = write_raw_dataset(tmp_path, "hdr", padded, "ci16_le",
                             extra_global={"core:num_channels": 2, "core:header_bytes": 4})
    samples, info, _ = read_sigmf(data)
    assert samples.shape == (2, 3) and info.rx_channels == (0, 1)
    expected = (comps.astype(np.float32) / 32768).view(np.complex64).reshape(3, 2).T
    np.testing.assert_array_equal(samples, expected)


def test_reader_random_access_clips_at_end(tmp_path, rng, info):
    x = make_iq(rng, 100)
    _, meta_path = write_sigmf(tmp_path / "ra", x, info)
    with SigmfReader(meta_path) as reader:
        assert len(reader) == 100 and reader.duration_s == pytest.approx(100 / 2e6)
        np.testing.assert_array_equal(reader.read(90, 50), x[90:])
        assert reader.read(100, 10).shape == (0,)
        chunk = reader.read(0, 10)
        assert chunk.flags.writeable and chunk.flags.c_contiguous
    with pytest.raises(ValueError):
        reader.read(0, 1)


def test_reader_missing_files_and_bad_metadata(tmp_path):
    with pytest.raises(FileNotFoundError):
        SigmfReader(tmp_path / "nope")
    (tmp_path / "nometa.sigmf-data").write_bytes(b"\0" * 8)
    with pytest.raises(FileNotFoundError):
        SigmfReader(tmp_path / "nometa")
    (tmp_path / "nometa.sigmf-meta").write_text(
        json.dumps({"global": {"core:datatype": "cf32_le"}}))
    with pytest.raises(ValueError, match="core:sample_rate"):
        SigmfReader(tmp_path / "nometa")


# --------------------------------------------------------------------------
# streaming recorder
# --------------------------------------------------------------------------
def test_recorder_streams_chunks_and_sorts_annotations(tmp_path, rng, info):
    chunks = [make_iq(rng, n) for n in (300, 500, 200)]
    rec = SigmfRecorder(tmp_path / "stream", info, datetime_utc="2026-01-01T00:00:00.000000Z")
    for chunk in chunks:
        rec.write(chunk)
    assert rec.samples_written == 1000
    assert rec.duration_s == pytest.approx(1000 / 2e6)
    rec.annotate(600, 100, freq_lower_hz=2.436e9, freq_upper_hz=2.438e9, label="late", snr_db=12.5)
    rec.annotate(10, 50, label="early", **{"foo:bar": "baz"})
    rec.close()
    rec.close()  # idempotent
    assert rec.closed
    with pytest.raises(ValueError):
        rec.write(chunks[0])

    samples, _, meta = read_sigmf(tmp_path / "stream")
    np.testing.assert_array_equal(samples, np.concatenate(chunks))
    anns = meta["annotations"]
    assert [a["core:sample_start"] for a in anns] == [10, 600]
    assert anns[0] == {"core:sample_start": 10, "core:sample_count": 50,
                       "core:label": "early", "foo:bar": "baz"}
    assert anns[1]["core:freq_lower_edge"] == 2.436e9
    assert anns[1]["core:freq_upper_edge"] == 2.438e9
    assert anns[1]["antsdr:snr_db"] == 12.5


def test_recorder_context_manager_writes_meta_and_friendly_annotations(tmp_path, rng, info):
    with SigmfRecorder(tmp_path / "ctx", info) as rec:
        rec.write(make_iq(rng, 16))
        rec.add_annotation({"sample_start": 2, "sample_count": 3, "label": "x"})
        with pytest.raises(ValueError):
            rec.add_annotation({"core:label": "no start"})
    assert (tmp_path / "ctx.sigmf-meta").exists()
    meta = json.loads((tmp_path / "ctx.sigmf-meta").read_text())
    assert meta["annotations"] == [
        {"core:sample_start": 2, "core:sample_count": 3, "core:label": "x"}]
    pytest.importorskip("sigmf")
    from antsdr_toolkit.io.sigmf_io import validate_metadata

    validate_metadata(meta)


def test_stream_info_from_metadata_defaults():
    meta = {"global": {"core:sample_rate": 4e6, "core:num_channels": 2}, "captures": []}
    info = stream_info_from_metadata(meta)
    assert info == StreamInfo(4e6, 0.0, rx_channels=(0, 1))
    assert info.bandwidth_hz == 4e6
    with pytest.raises(ValueError):
        stream_info_from_metadata({"global": {}})


def test_antsdr_namespace_is_declared_as_extension_and_validates_cleanly(tmp_path, rng, info):
    """Undeclared namespaces become a hard ValidationError in future sigmf versions."""
    import warnings

    sigmf = pytest.importorskip("sigmf")
    from sigmf.sigmffile import fromfile

    _, meta_path = write_sigmf(tmp_path / "ext", make_iq(rng, 8), info,
                               extra_global={"core:extensions": [
                                   {"name": "other", "version": "1.0.0", "optional": True}]})
    exts = json.loads(meta_path.read_text())["global"]["core:extensions"]
    assert [e["name"] for e in exts] == ["other", "antsdr"]
    assert exts[1] == {"name": "antsdr", "version": __version__, "optional": True}
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any "undeclared extension" warning fails the test
        fromfile(str(meta_path), skip_checksum=True).validate()
    assert sigmf.EXTENSIONS_KEY == "core:extensions"
