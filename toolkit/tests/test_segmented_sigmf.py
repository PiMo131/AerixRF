"""Tests for truthful SigMF metadata around discontinuous E200 snapshots."""

from __future__ import annotations

import json

import numpy as np

from antsdr_toolkit.device.base import StreamInfo
from antsdr_toolkit.io.segmented_sigmf import SegmentedSigmfRecorder
from antsdr_toolkit.io.sigmf_io import read_sigmf, validate_metadata


def test_snapshot_buffers_are_separate_capture_segments(tmp_path):
    stem = tmp_path / "snap"
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


def test_segment_requires_prior_samples_and_open_recorder(tmp_path):
    info = StreamInfo(10e6, 915e6, hardware="fake-e200")
    rec = SegmentedSigmfRecorder(tmp_path / "bad", info)
    try:
        try:
            rec.start_segment()
        except ValueError as exc:
            assert "write at least one sample" in str(exc)
        else:  # pragma: no cover - regression guard
            raise AssertionError("empty segment was accepted")
        rec.write(np.zeros(4, dtype=np.complex64))
    finally:
        rec.close()
    try:
        rec.start_segment()
    except ValueError as exc:
        assert "closed" in str(exc)
    else:  # pragma: no cover - regression guard
        raise AssertionError("closed recorder accepted a segment")
