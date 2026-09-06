"""Tests for truthful SigMF metadata around discontinuous E200 snapshots."""

from __future__ import annotations

import json

import numpy as np
import pytest

from antsdr_toolkit.device.base import StreamInfo
from antsdr_toolkit.device.file_source import SigmfFileSource
from antsdr_toolkit.io.segmented_sigmf import SegmentedSigmfRecorder
from antsdr_toolkit.io.sigmf_io import read_sigmf, validate_metadata


def _write_snapshot(stem):
    info = StreamInfo(15.36e6, 2.437e9, hardware="fake-e200")
    extra = {
        "antsdr:capture_tier": "snapshot",
        "antsdr:timing_contiguous": False,
    }
    first = np.arange(8, dtype=np.float32).astype(np.complex64)
    second = (100 + np.arange(5, dtype=np.float32)).astype(np.complex64)
    with SegmentedSigmfRecorder(stem, info, extra_global=extra) as rec:
        rec.write(first)
        rec.start_segment()
        rec.write(second)
    return info, first, second


def test_snapshot_buffers_are_separate_capture_segments(tmp_path):
    stem = tmp_path / "snap"
    info, first, second = _write_snapshot(stem)

    samples, _info, meta = read_sigmf(stem)
    np.testing.assert_array_equal(samples, np.concatenate([first, second]))
    assert meta["global"]["antsdr:capture_tier"] == "snapshot"
    assert meta["global"]["antsdr:timing_contiguous"] is False
    assert len(meta["captures"]) == 2
    assert meta["captures"][0]["core:sample_start"] == 0
    assert meta["captures"][1]["core:sample_start"] == len(first)
    assert meta["captures"][1]["core:frequency"] == info.center_freq_hz
    assert meta["captures"][1]["antsdr:continuity"] == "unknown-gap-before"
    assert "core:global_index" not in meta["captures"][1]
    assert "core:datetime" not in meta["captures"][1]
    validate_metadata(meta)

    on_disk = json.loads((tmp_path / "snap.sigmf-meta").read_text())
    assert on_disk["captures"] == meta["captures"]


def test_replay_never_crosses_unknown_snapshot_gap(tmp_path):
    stem = tmp_path / "snap"
    _info, first, second = _write_snapshot(stem)

    with SigmfFileSource(stem) as src:
        assert not src.timing_contiguous
        assert src.discontinuity_starts == (len(first),)
        # A large request is deliberately shortened at the gap. Calling read
        # again enters the next segment, so timing features cannot span it.
        a = src.read(1000)
        b = src.read(1000)
        np.testing.assert_array_equal(a, first)
        np.testing.assert_array_equal(b, second)

    with pytest.raises(ValueError, match="discontinuous SigMF snapshot"):
        SigmfFileSource(stem, loop=True)


def test_segment_requires_prior_samples_and_open_recorder(tmp_path):
    info = StreamInfo(10e6, 915e6, hardware="fake-e200")
    rec = SegmentedSigmfRecorder(tmp_path / "bad", info)
    try:
        with pytest.raises(ValueError, match="write at least one sample"):
            rec.start_segment()
        rec.write(np.zeros(4, dtype=np.complex64))
    finally:
        rec.close()
    with pytest.raises(ValueError, match="closed"):
        rec.start_segment()
