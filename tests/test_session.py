"""Field-test session store + summary (Milestones 1.4 / 1.6)."""

from __future__ import annotations

import hashlib
import json
import uuid

import numpy as np
import pytest

from aerix_rf.config import Config
from aerix_rf.sdr.capture import (
    FileIQSource,
    IQWindow,
    _read_cs8,
    _read_cs16,
    to_cs16,
    to_cs8,
)
from aerix_rf.sdr.sim import synth_iq
from aerix_rf.session import Session, SessionIntegrityError, build_summary, write_summary
from aerix_rf.session.store import IQ_DIR, SESSION_FILE

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
    # ANTSDR-only diagnostics must pass through honestly as ``None`` (not
    # silently dropped) on a sim source, so session.json is diagnosable
    # offline for every backend without a fixed/incomplete key set.
    for entry in files:
        health = entry["capture_health"]
        for k in ("samples_deficit_recent", "readback_mismatch", "rssi_db_readback",
                  "max_refill_gap_ms", "stream_rate_ratio_recent", "stream_rate_elapsed_s",
                  "samples_deficit"):
            assert k in health, k
            assert health[k] is None, (k, health[k])


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


# --- T1: cs8/cs16 codec, schema-2 metadata, schema-1 back-compat, IQWindow defaults ---

def test_cs8_cs16_roundtrip_and_scaling():
    rng = np.random.default_rng(7)
    iq = (rng.uniform(-1, 1, 4000) + 1j * rng.uniform(-1, 1, 4000)).astype(np.complex64)
    iq = (iq / (np.max(np.abs(iq)) + 1e-9) * 0.95).astype(np.complex64)

    # cs8: exact int8 recovery (within 1/128 quantization), matches to_cs8/_read_cs8.
    raw8 = to_cs8(iq)
    assert len(raw8) == iq.size * 2
    back8 = _read_cs8_bytes(raw8)
    assert np.max(np.abs(back8.real - iq.real)) <= 0.5 / 128 + 1e-6
    assert np.max(np.abs(back8.imag - iq.imag)) <= 0.5 / 128 + 1e-6

    # cs16 @ ANTSDR full_scale=2048.0: values stay in [-1, 1) and are exact to
    # the int16 quantization step (1/2048), i.e. far tighter than cs8's 1/128.
    raw16 = to_cs16(iq, full_scale=2048.0)
    assert len(raw16) == iq.size * 4
    back16 = _read_cs16_bytes(raw16, full_scale=2048.0)
    assert np.all(back16.real >= -1.0) and np.all(back16.real < 1.0)
    assert np.all(back16.imag >= -1.0) and np.all(back16.imag < 1.0)
    assert np.max(np.abs(back16.real - iq.real)) <= 0.5 / 2048 + 1e-6
    assert np.max(np.abs(back16.imag - iq.imag)) <= 0.5 / 2048 + 1e-6
    # cs16 is strictly finer-grained than cs8 for the same signal.
    assert np.max(np.abs(back16.real - iq.real)) < np.max(np.abs(back8.real - iq.real))

    # Exact integer recovery: build I/Q pairs from known int16 values and check
    # _read_cs16 recovers them exactly (no rounding drift from float encode).
    known_i = np.array([0, 2047, -2048, 100], dtype=np.int16)
    known_q = np.array([1, -1, 1999, -1999], dtype=np.int16)
    interleaved = np.empty(known_i.size * 2, dtype=np.int16)
    interleaved[0::2] = known_i
    interleaved[1::2] = known_q
    decoded = _read_cs16_bytes(interleaved.tobytes(), full_scale=2048.0)
    assert np.allclose(decoded.real, known_i.astype(np.float32) / 2048.0, atol=1e-7)
    assert np.allclose(decoded.imag, known_q.astype(np.float32) / 2048.0, atol=1e-7)


def _read_cs8_bytes(raw: bytes) -> np.ndarray:
    arr = np.frombuffer(raw, dtype=np.int8).astype(np.float32)
    return ((arr[0::2] + 1j * arr[1::2]) / 128.0).astype(np.complex64)


def _read_cs16_bytes(raw: bytes, full_scale: float) -> np.ndarray:
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    return ((arr[0::2] + 1j * arr[1::2]) / float(full_scale)).astype(np.complex64)


def test_create_non_hackrf_receiver_keeps_explicit_none_gains(tmp_path):
    """A non-HackRF backend (e.g. antsdr_iio via cli._receiver_meta) passes
    lna_gain/vga_gain/amp as explicit None rather than omitting the keys --
    Session.create() must honor that (rcv.get(k, default) returns the stored
    None, it does not fall back to cfg's HackRF defaults) instead of silently
    reporting HackRF gain-stage values for a radio that has none."""
    cfg = Config(sample_rate=12_288_000.0, sim=False)
    s = Session.create(tmp_path, "antsdr gains", cfg=cfg,
                       receiver={"receiver_type": "antsdr", "backend": "antsdr_iio",
                                "sample_rate": 12_288_000.0, "center_freq_hz": 2437e6,
                                "lna_gain": None, "vga_gain": None, "amp": None,
                                "gain_db": 55.0, "gain_mode": "manual"})
    assert s.meta["receiver_backend"] == "antsdr_iio"
    assert s.meta["sample_rate"] == 12_288_000.0
    assert s.meta["gains"] == {"lna_gain": None, "vga_gain": None, "amp": False, "gain_db": 55.0}


def test_write_iq_cs16_session_roundtrip(tmp_path):
    """write_iq(iq_format="cs16") -> session.json metadata -> replay, end to end."""
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    s = Session.create(tmp_path, "cs16 test", cfg=cfg,
                       receiver={"receiver_type": "antsdr", "iq_format": "cs16",
                                "iq_full_scale": 2048.0})
    w = _window(3, 1_700_000_100.0, 2440e6)
    s.write_iq(w, iq_format="cs16", iq_full_scale=2048.0)
    s.finalize()

    entry = s.meta["files"][0]
    assert entry["file"].endswith(".cs16")
    assert entry["iq_format"] == "cs16"
    assert entry["iq_full_scale"] == 2048.0

    wins = list(s.iq_windows(cfg))
    assert len(wins) == 1
    got = wins[0]
    assert np.max(np.abs(got.iq.real - w.iq.real)) <= 0.5 / 2048 + 1e-6
    assert np.max(np.abs(got.iq.imag - w.iq.imag)) <= 0.5 / 2048 + 1e-6
    # cs16 replay is closer to the original than a cs8 replay of the same signal would be.
    assert np.max(np.abs(got.iq.real - w.iq.real)) < 0.5 / 128


def test_schema1_session_replays_identically(tmp_path):
    """A minimal, hand-built schema-1 session.json (no iq_format/iq_full_scale/
    bandwidth_hz/channel_id/timing keys, cs8 file) must replay with the same
    samples/defaults as the equivalent schema-2 session."""
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    iq = synth_iq(SR, DUR, drone=True, seed=9)
    iq = (iq / (np.max(np.abs(iq)) + 1e-9) * 0.95).astype(np.complex64)

    sdir = tmp_path / "2024-01-01_000000_legacy"
    (sdir / IQ_DIR).mkdir(parents=True)
    raw = to_cs8(iq)
    (sdir / IQ_DIR / "capture_0001.cs8").write_bytes(raw)
    entry = {
        "file": "iq/capture_0001.cs8",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sample_count": iq.size,
        "duration_s": DUR,
        "sample_rate": SR,
        "center_freq_hz": 2440e6,
        "captured_at": 1_700_000_200.0,
        "receiver_type": "hackrf",
        "receiver_serial": "OLD-1",
        "gain_db": 40.0,
        "complete": True,
        # deliberately NO iq_format / iq_full_scale / bandwidth_hz / channel_id / timing
    }
    meta = {
        "schema_version": 1,
        "session_id": str(uuid.uuid4()),
        "label": "legacy",
        "files": [entry],
        "counts": {},
        "test": {},
    }
    (sdir / SESSION_FILE).write_text(json.dumps(meta, indent=2))

    s = Session.open(sdir)
    assert s.meta.get("schema_version") == 1
    wins = list(s.iq_windows(cfg))
    assert len(wins) == 1
    got = wins[0]
    expect = _read_cs8(str(sdir / "iq" / "capture_0001.cs8"), 0, iq.size)
    assert np.array_equal(got.iq, expect)
    assert np.max(np.abs(got.iq.real - iq.real)) <= 0.5 / 128 + 1e-6
    # cs8/128.0 default applied even though the keys are absent from session.json.
    assert got.metadata["iq_format"] == "cs8"
    assert got.metadata["iq_full_scale"] == 128.0
    # New-in-schema-2 IQWindow fields fall back to the dataclass defaults.
    assert got.bandwidth_hz is None
    assert got.channel_id == 0
    assert got.timing == {}


def test_iqwindow_legacy_construction_gets_new_defaults():
    """IQWindow built with only the pre-T1 positional/keyword args still gets the
    new generalized fields at their documented defaults."""
    iq = np.zeros(8, dtype=np.complex64)
    w = IQWindow(iq=iq, captured_at=123.0, sample_rate=SR, center_freq_hz=2440e6,
                receiver_type="hackrf", receiver_serial="S1", gain_db=30.0)
    assert w.bandwidth_hz is None
    assert w.channel_id == 0
    assert w.timing == {}


def test_to_cs16_clips_to_declared_full_scale():
    """to_cs16 clips at the DECLARED full_scale, not a fixed int16 range: with
    full_scale=2048.0, 2.0 (well outside +-1) must land at the max representable
    code (2047), not wrap or hit +-32767."""
    iq = np.array([2.0 + 2.0j], dtype=np.complex64)
    raw = to_cs16(iq, full_scale=2048.0)
    vals = np.frombuffer(raw, dtype=np.int16)
    assert vals[0] == 2047  # I
    assert vals[1] == 2047  # Q
    # Symmetric negative clip: -round(full_scale) == -2048.
    raw_neg = to_cs16(np.array([-2.0 - 2.0j], dtype=np.complex64), full_scale=2048.0)
    vals_neg = np.frombuffer(raw_neg, dtype=np.int16)
    assert vals_neg[0] == -2048
    assert vals_neg[1] == -2048


def test_read_cs16_requires_explicit_full_scale():
    with pytest.raises(ValueError):
        _read_cs16("/nonexistent", 0, 1, full_scale=None)


def test_fileiqsource_cs16_without_full_scale_raises(tmp_path):
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    raw = to_cs16(np.zeros(N, dtype=np.complex64), full_scale=2048.0)
    p = tmp_path / "capture_0001.cs16"
    p.write_bytes(raw)
    with pytest.raises(ValueError):
        FileIQSource(cfg, path=str(p), meta={"sample_rate": SR, "iq_format": "cs16"})


def test_write_iq_cs16_without_full_scale_raises(tmp_path):
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    s = Session.create(tmp_path, "cs16 missing scale", cfg=cfg, receiver={})
    w = _window(4, 1_700_000_300.0, 2440e6)
    with pytest.raises(ValueError):
        s.write_iq(w, iq_format="cs16")


def test_write_iq_records_receiver_readback_and_per_file_mismatch(tmp_path):
    """A readback-capable backend (antsdr_iio) stamps window.metadata with
    "readback"/"readback_mismatch"; Session.write_iq must record the FIRST
    window's readback once at the top level (receiver_readback) and each
    file's own readback_mismatch, so a session with a flagged mismatch is
    diagnosable after the fact (see antsdr_iio module docstring)."""
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    s = Session.create(tmp_path, "readback test", cfg=cfg,
                       receiver={"receiver_type": "antsdr", "iq_format": "cs16",
                                "iq_full_scale": 2048.0})
    rb1 = {"hardwaregain_db": 40.0, "gain_control_mode": "manual",
           "rf_bandwidth_hz": 10.0e6, "sampling_frequency_hz": 12.288e6,
           "rx_lo_hz": 2440e6, "fw_version": "v0.36"}
    w1 = _window(6, 1_700_000_500.0, 2440e6)
    w1.metadata["readback"] = rb1
    w1.metadata["readback_mismatch"] = False
    s.write_iq(w1, iq_format="cs16", iq_full_scale=2048.0)

    rb2 = dict(rb1, hardwaregain_db=55.0)
    w2 = _window(7, 1_700_000_501.0, 2440e6)
    w2.metadata["readback"] = rb2
    w2.metadata["readback_mismatch"] = True
    s.write_iq(w2, iq_format="cs16", iq_full_scale=2048.0)
    s.finalize()

    meta = json.loads((s.path / "session.json").read_text())
    assert meta["receiver_readback"] == rb1        # from the FIRST window only
    assert meta["files"][0]["readback_mismatch"] is False
    assert meta["files"][1]["readback_mismatch"] is True


def test_write_iq_cs8_keeps_default_full_scale(tmp_path):
    """cs8 is unaffected by the cs16 required-full-scale rule -- default 128.0 holds."""
    cfg = Config(sample_rate=SR, window_s=DUR, sim=True)
    s = Session.create(tmp_path, "cs8 default", cfg=cfg, receiver={})
    w = _window(5, 1_700_000_400.0, 2440e6)
    s.write_iq(w)  # no iq_format/iq_full_scale -> cs8 @ 128.0, must not raise
    entry = s.meta["files"][0]
    assert entry["iq_format"] == "cs8"
    assert entry["iq_full_scale"] == 128.0
