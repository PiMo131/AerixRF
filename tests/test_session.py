"""Field-test session store + summary (Milestones 1.4 / 1.6)."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from aerix_rf.config import Config
from aerix_rf.sdr.capture import IQWindow, _read_cs8
from aerix_rf.sdr.sim import synth_iq
from aerix_rf.session import Session, SessionIntegrityError, build_summary, write_summary

SR = 1e6
DUR = 0.05
N = int(SR * DUR)

TEST = {
    "drone_manufacturer": "DJI", "drone_model": "Mini 4 Pro", "drone_state": "powered",
    "controller_state": "on", "motors_state": "off", "approx_distance_m": 30,
    "operator_notes": "bench, indoors", "antenna": "stock 2.4 GHz whip",
}


def _window(seed: int, t0: float, center_hz: float, **kw) -> IQWindow:
    iq = synth_iq(SR, DUR, drone=True, seed=seed)
    # Keep inside +-1 so the int8 round-trip is exact to 1/127.
    iq = (iq / (np.max(np.abs(iq)) + 1e-9) * 0.95).astype(np.complex64)
    return IQWindow(iq=iq, captured_at=t0, sample_rate=SR, center_freq_hz=center_hz,
                    receiver_type="sim", receiver_serial="SIM-1", gain_db=40.0,
                    expected_samples=iq.size, **kw)


def _health(win: IQWindow, overflow: int = 0) -> dict:
    win.metadata["overflow_count"] = overflow
    return win.health()


@pytest.fixture
def session(tmp_path):
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    s = Session.create(tmp_path / "sessions", "Test 2 aircraft powered", cfg=cfg,
                       receiver={"receiver_type": "sim", "receiver_serial": "SIM-1",
                                 "center_freq_hz": 2440e6, "lna_gain": 16, "vga_gain": 24},
                       test=TEST, notes="quiet lab", location={"lat": 52.0, "lon": 4.3})
    w1 = _window(1, 1_700_000_000.0, 2440e6)
    w2 = _window(2, 1_700_000_001.0, 2450e6, complete=False, dropped_samples=100)
    w2.metadata["overflow_count"] = 2          # as a libhackrf window would carry it
    s.write_iq(w1)
    s.write_iq(w2)
    s.write_spectrogram(b"\x89PNG fake", w1.captured_at, tag="det")
    s.log_detection({"captured_at": w1.captured_at, "center_freq_hz": 2440e6, "peak_freq_hz": 2441.2e6,
                     "score": 0.91, "snr_db": 18.5, "occupied_bw_mhz": 9.8, "burst_count": 3,
                     "cadence_ms": 600.0, "plausible": True, "morphology": "ofdm_burst",
                     "class": "dji_ocusync", "confidence": 0.8, "class_source": "model",
                     "capture_health": _health(w1)})
    s.log_detection({"captured_at": w2.captured_at, "center_freq_hz": 2450e6, "peak_freq_mhz": 2451.9,
                     "score": 0.32, "snr_db": 5.0, "bw_mhz": 2.0, "plausible": False,
                     "morphology": "narrowband", "class": "noise", "confidence": 0.6,
                     "class_source": "rules", "capture_health": _health(w2, overflow=2)})
    s.log_detection({"score": 0.5})   # partial record: must not break anything
    s.log_decode({"captured_at": w1.captured_at, "level": "A", "crc_ok": False, "error": "no_sync"})
    s.log_decode({"captured_at": w1.captured_at, "level": "C", "crc_ok": True, "serial": "1581F5FHD2345",
                  "drone_lat": 52.001, "drone_lon": 4.301})
    s.finalize(extra={"operator": "pm"})
    return s, cfg, (w1, w2)


def test_session_json_layout(session):
    s, _, (w1, w2) = session
    meta = json.loads((s.path / "session.json").read_text())
    assert s.path.name.endswith("_test_2_aircraft_powered")
    assert (s.path / "iq").is_dir() and (s.path / "spectrograms").is_dir()
    for k in ("session_id", "started_at", "ended_at", "duration_s", "software_git_sha", "software_version",
              "receiver_type", "receiver_serial", "sample_rate", "center_freq_hz", "gains", "antenna",
              "location", "environment_notes", "test", "files", "counts"):
        assert k in meta, k
    assert meta["gains"] == {"lna_gain": 16, "vga_gain": 24, "amp": False, "gain_db": 40.0}
    assert meta["antenna"] == "stock 2.4 GHz whip"
    assert meta["environment_notes"] == "quiet lab"
    assert meta["operator"] == "pm"
    t = meta["test"]
    assert t["test_label"] == "Test 2 aircraft powered"
    assert t["drone_model"] == "Mini 4 Pro" and t["motors_state"] == "off"
    assert t["drone_serial"] is None                      # not intentionally provided -> null
    assert "class" not in t and "antenna" not in t        # classifier output never in the test block

    files = meta["files"]
    assert len(files) == 2
    for entry, w in zip(files, (w1, w2)):
        p = s.path / entry["file"]
        assert p.exists()
        assert entry["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
        assert entry["sample_count"] == N == p.stat().st_size // 2
        assert entry["duration_s"] == pytest.approx(DUR)
        assert entry["center_freq_hz"] == w.center_freq_hz
        assert entry["captured_at"] == w.captured_at
        assert entry["receiver_type"] == "sim"
    assert files[0]["file"] == "iq/capture_0001.cs8" and files[1]["file"] == "iq/capture_0002.cs8"
    assert files[0]["complete"] is True and files[1]["complete"] is False
    assert files[1]["dropped_samples"] == 100
    assert meta["counts"]["iq_windows"] == 2 and meta["counts"]["detections"] == 3
    assert meta["counts"]["decodes"] == 2 and meta["counts"]["spectrograms"] == 1
    assert len(list((s.path / "spectrograms").glob("*.png"))) == 1


def test_replay_matches_original(session):
    s, cfg, (w1, w2) = session
    # Replay must not depend on the machine's config: use a "wrong" cfg on purpose.
    other = Config(sample_rate=20e6, center_freq_mhz=5800.0, window_s=1.0)
    wins = list(s.iq_windows(other))
    assert len(wins) == 2
    for got, orig in zip(wins, (w1, w2)):
        assert got.iq.size == orig.iq.size
        # Bit-exact with the codec's own round trip ...
        expect = _read_cs8(str(s.path / got.metadata["session_file"]), 0, orig.iq.size)
        assert np.array_equal(got.iq, expect)
        # ... and within one int8 LSB (1/128 per component) of the original.
        assert np.max(np.abs(got.iq.real - orig.iq.real)) <= 0.5 / 128 + 1e-6
        assert np.max(np.abs(got.iq.imag - orig.iq.imag)) <= 0.5 / 128 + 1e-6
        assert got.sample_rate == SR
        assert got.center_freq_hz == orig.center_freq_hz
        assert got.captured_at == pytest.approx(orig.captured_at)
        assert got.receiver_type == "sim" and got.receiver_serial == "SIM-1"
        assert got.metadata["replay"] is True and got.metadata["session_id"] == s.session_id
    assert wins[1].complete is False and wins[1].dropped_samples == 100
    assert wins[1].metadata["overflow_count"] == 2


def test_tamper_detected(session):
    s, cfg, _ = session
    p = s.path / "iq" / "capture_0002.cs8"
    raw = bytearray(p.read_bytes())
    raw[10] ^= 0x7F
    p.write_bytes(bytes(raw))
    assert [e["file"] for e in s.verify()] == ["iq/capture_0002.cs8"]
    it = s.iq_windows(cfg)
    next(it)                                    # file 1 is fine
    with pytest.raises(SessionIntegrityError, match="sha256 mismatch for iq/capture_0002.cs8"):
        next(it)


def test_open_roundtrip_and_readers(session):
    s, _, _ = session
    r = Session.open(s.path)
    assert r.session_id == s.session_id
    assert r.meta == json.loads((s.path / "session.json").read_text())
    assert len(r.files) == 2
    dets, decs = r.detections(), r.decodes()
    assert len(dets) == 3 and len(decs) == 2
    assert all("ts" in d for d in dets + decs)
    assert decs[1]["serial"] == "1581F5FHD2345"
    with pytest.raises(ValueError):
        r.finalize(extra={"test": {"drone_model": "overwritten"}})


def test_summary(session):
    s, _, _ = session
    md = build_summary(s)
    assert "Test 2 aircraft powered" in md
    assert s.session_id in md
    assert "Mini 4 Pro" in md and "motors_state | off" in md
    # health totals
    assert "Detection windows (records with capture_health) | 2" in md
    assert "complete / incomplete | 1 / 1" in md
    assert "overflow count (cumulative, final) | 2" in md
    assert "dropped or missing samples (sum) | 100" in md
    # file table
    assert "iq/capture_0001.cs8" in md and "iq/capture_0002.cs8" in md
    # detection stats
    assert "Records: **3**" in md and "Plausible (`plausible: true`): **1**" in md
    assert "| ofdm_burst | 1 |" in md and "| narrowband | 1 |" in md and "| n/a | 1 |" in md
    assert "| dji_ocusync | 1 | 0.800 | 1 |" in md
    assert "`model` x1" in md and "`rules` x1" in md
    assert "| 2441 | 1 |" in md and "| 2452 | 1 |" in md
    assert "Max score: 0.910" in md and "Max SNR: 18.5 dB" in md
    assert "median 600.0" in md
    # decode summary
    assert "Attempts: **2**" in md and "Best level reached: **C - Turbo + CRC24A valid**" in md
    assert "CRC-valid decodes: **1**" in md and "1581F5FHD2345" in md and "52.001" in md
    assert "`no_sync` x1" in md
    # interpretation
    assert "## Interpretation" in md
    assert "does not prove that every RF emitter" in md
    assert "1 CRC-valid" in md
    out = write_summary(s)
    assert out.name == "summary.md" and out.read_text() == md


def test_summary_on_empty_session(tmp_path):
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    s = Session.create(tmp_path, "empty", cfg=cfg, receiver={})
    md = build_summary(s)
    assert "No detection records." in md and "No decode attempts recorded." in md
    assert "(no IQ recorded)" in md and "0 CRC-valid" in md
    assert list(s.iq_windows(cfg)) == []
