"""Tests for antsdr_toolkit.scan.events (DetectionEvent, JSONL writer, dwell conversion)."""

from __future__ import annotations

import json
import uuid

import numpy as np
import pytest

from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.device.base import StreamInfo
from antsdr_toolkit.dsp.bursts import Burst
from antsdr_toolkit.scan import events as ev
from antsdr_toolkit.scan import sweep as sw


def _event(**overrides) -> ev.DetectionEvent:
    base = {
        "sensor_id": "e200-lab-1", "received_at_utc": "2026-09-06T10:00:00.000Z",
        "center_freq_hz": 2.4295e9, "f_low_hz": 2.425e9, "f_high_hz": 2.434e9, "bandwidth_hz": 9e6,
        "t_start_s": 0.0123, "duration_s": 0.00064, "peak_db": -45.5, "snr_db": 21.0,
        "source": "antsdr-e200", "rf_port": "RX1", "sample_rate_hz": 15.36e6,
        "family": "dji-droneid", "family_confidence": 0.8,
        "evidence": {"kurtosis": 6.7, "iq": ev.iq_reference("cap/rec", 1000, 9880)},
    }
    base.update(overrides)
    return ev.DetectionEvent(**base)


def test_event_json_round_trip_and_defaults():
    e = _event()
    assert e.schema_version == "0.1"
    uuid.UUID(e.event_id)  # generated, valid
    text = e.to_json()
    doc = json.loads(text)
    assert list(doc)[:2] == ["schema_version", "event_id"]
    assert doc["evidence"]["iq"] == {"sigmf": "cap/rec", "sample_start": 1000, "sample_count": 9880}
    back = ev.DetectionEvent.from_json(text)
    assert back == e
    assert ev.DetectionEvent.from_dict(e.to_dict()) == e
    # ids are unique per event unless given
    assert _event().event_id != _event().event_id
    fixed = str(uuid.uuid4())
    assert _event(event_id=fixed).event_id == fixed
    # unknown keys are ignored, missing required keys are not
    extra = e.to_dict()
    extra["future_field"] = 1
    assert ev.DetectionEvent.from_dict(extra) == e
    del extra["snr_db"]
    with pytest.raises(ValueError):
        ev.DetectionEvent.from_dict(extra)
    with pytest.raises(ValueError):
        ev.DetectionEvent.from_dict({**e.to_dict(), "schema_version": "1.0"})
    # numeric fields are normalised to float, so ints in JSON compare equal
    assert ev.DetectionEvent.from_dict({**e.to_dict(), "peak_db": -45.5}).peak_db == -45.5


def test_event_validation():
    with pytest.raises(ValueError):
        _event(source="hackrf")
    with pytest.raises(ValueError):
        _event(family_confidence=1.5)
    with pytest.raises(ValueError):
        _event(f_low_hz=2.44e9, f_high_hz=2.43e9)
    with pytest.raises(ValueError):
        _event(sensor_id="")
    with pytest.raises(ValueError):
        _event(event_id="not-a-uuid")
    with pytest.raises(ValueError):
        _event(sample_rate_hz=0.0)
    with pytest.raises(ValueError):
        _event(duration_s=-1.0)
    with pytest.raises(TypeError):
        _event(evidence={"arr": np.zeros(3)})  # not JSON-serialisable
    for source in ev.SOURCES:
        assert _event(source=source).source == source


def test_helpers_from_stream_info():
    assert ev.rf_port_from_info(StreamInfo(1e6, 1e9, rx_channels=(0,))) == "RX1"
    assert ev.rf_port_from_info(StreamInfo(1e6, 1e9, rx_channels=(1,))) == "RX2"
    assert ev.rf_port_from_info(StreamInfo(1e6, 1e9, rx_channels=(0, 1))) == "RX1+RX2"
    assert ev.rf_port_from_info(StreamInfo(1e6, 1e9, rx_channels=(3,))) == "ch3"
    assert ev.source_from_info(StreamInfo(1e6, 1e9, hardware="antsdr-e200")) == "antsdr-e200"
    assert ev.source_from_info(StreamInfo(1e6, 1e9, hardware="ANTSDR E200 rev C")) == "antsdr-e200"
    assert ev.source_from_info(StreamInfo(1e6, 1e9, hardware="synthetic")) == "synthetic"
    assert ev.source_from_info(StreamInfo(1e6, 1e9, hardware="file")) == "file"
    assert ev.source_from_info(StreamInfo(1e6, 1e9, hardware="unknown")) == "file"
    stamp = ev.utc_now_iso()
    assert stamp.endswith("Z") and "T" in stamp and len(stamp) == 24
    with pytest.raises(ValueError):
        ev.iq_reference("x", -1, 10)


def test_from_burst_and_jsonl_writer(tmp_path):
    burst = Burst(0.010, 0.011, 2.41e9, 2.412e9, peak_db=-40.0, mean_db=-46.0, snr_db=18.0)
    e = ev.DetectionEvent.from_burst(
        burst, sensor_id="s", source="file", rf_port="RX1", sample_rate_hz=4e6,
        received_at_utc="2026-09-06T10:00:00.000Z", evidence={"note": "x"},
    )
    assert e.center_freq_hz == pytest.approx(2.411e9) and e.bandwidth_hz == pytest.approx(2e6)
    assert e.t_start_s == 0.010 and e.duration_s == pytest.approx(1e-3)
    assert e.peak_db == -40.0 and e.snr_db == 18.0 and e.family is None
    assert e.evidence == {"note": "x", "kind": "burst", "mean_db": -46.0}
    seg = sw.OccupiedSegment(2.40e9, 2.41e9, -50.0, 12.0)
    s = ev.DetectionEvent.from_segment(
        seg, t_start_s=0.0, duration_s=0.06, sensor_id="s", source="synthetic", rf_port="RX2",
        sample_rate_hz=20e6,
    )
    assert s.bandwidth_hz == pytest.approx(10e6) and s.evidence["kind"] == "occupancy"
    assert s.duration_s == 0.06 and s.snr_db == 12.0

    path = tmp_path / "events" / "log.jsonl"
    with ev.JsonlEventWriter(path) as writer:
        writer.write(e)
        assert writer.write_many([s, _event()]) == 2
        assert writer.count == 3
    events = ev.read_jsonl_events(path)
    assert len(events) == 3 and events[0] == e and events[1] == s
    # append mode adds to the file, overwrite mode replaces it
    with ev.JsonlEventWriter(path) as writer:
        writer.write(_event())
    assert len(ev.read_jsonl_events(path)) == 4
    with ev.JsonlEventWriter(path, append=False) as writer:
        writer.write(_event())
    assert len(list(ev.iter_jsonl_events(path))) == 1
    # a writer that never wrote creates no file
    lazy = ev.JsonlEventWriter(tmp_path / "never.jsonl")
    lazy.close()
    assert not (tmp_path / "never.jsonl").exists()


def test_events_from_dwell_result():
    fs, fc = 2e6, 868.3e6
    scene = syn.Scene(fs, fc, 30e-3, np.random.default_rng(8), noise_power_db=-60.0)
    rng = np.random.default_rng(9)
    for k in range(3):
        scene.add(syn.gfsk_burst(fs, 100e3, 100, rng), t_start_s=2e-3 + k * 8e-3,
                  freq_offset_hz=-0.3e6, snr_db=25.0, label="g")
    x = scene.render()
    result = sw.analyse_dwell(x, fs, fc, 1.6e6, t_wall_s=1_700_000_000.0, fft_size=1024,
                              burst_fft_size=256)
    assert len(result.bursts) == 3 and len(result.occupancy) == 1
    ref = ev.iq_reference("captures/868", 0, len(x))
    events = ev.events_from_dwell(
        result, sensor_id="e200-1", source="synthetic", rf_port="RX1", iq=ref,
        families=[("gfsk-telemetry", 0.6), ("lora", 0.2)],
    )
    assert len(events) == 3
    for e, b in zip(events, result.bursts):
        assert e.f_low_hz == b.f_low_hz and e.t_start_s == b.t_start_s
        assert e.family == "gfsk-telemetry" and e.family_confidence == 0.6
        assert e.received_at_utc == "2023-11-14T22:13:20.000Z"  # from t_wall_s
        assert e.evidence["iq"] == ref and e.evidence["kurtosis"] == result.kurtosis
        assert e.evidence["noise_floor_db"] == result.noise_floor_db
        assert e.evidence["families"] == [["gfsk-telemetry", 0.6], ["lora", 0.2]]
        assert e.evidence["features"]["n_bursts"] == 3
        assert e.sample_rate_hz == fs and e.source == "synthetic"
        json.loads(e.to_json())
    assert len({e.event_id for e in events}) == 3
    with_occ = ev.events_from_dwell(result, sensor_id="s", source="file", rf_port="RX1",
                                    include_occupancy=True)
    assert len(with_occ) == 4
    occ = with_occ[-1]
    assert occ.evidence["kind"] == "occupancy" and occ.duration_s == result.duration_s
    assert occ.family is None and occ.received_at_utc.endswith("Z")
    # a dwell without a wall clock is stamped "now"
    result.t_wall_s = 0.0
    now_events = ev.events_from_dwell(result, sensor_id="s", source="file", rf_port="RX1")
    assert now_events[0].received_at_utc[:4] >= "2026"
