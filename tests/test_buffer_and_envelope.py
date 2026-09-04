"""IQ retention purge (GDPR bound) and envelope shape."""

import time

import numpy as np

from aerix_rf.buffer.iq_ring import IQRing
from aerix_rf.config import Config
from aerix_rf.uplink.client import Uplink, CONTRACT_CLASSES, to_contract_class
from aerix_rf.classify.model import STAGE2_CLASSES
from aerix_rf.detect.energy import Detection


def test_iq_ring_stores_and_purges(tmp_path):
    ring = IQRing(tmp_path, retention_s=1)
    iq = (np.random.randn(1000) + 1j * np.random.randn(1000)).astype(np.complex64)

    # A fresh window is retrievable.
    key = ring.store(iq, time.time(), {"score": 0.9})
    assert ring.get(key) is not None
    assert ring.nearest(time.time(), tolerance_s=2.0) == key

    # An old window is purged on the next write (retention bound enforced).
    ring.store(iq, time.time() - 10, {"score": 0.1})
    ring.purge()
    assert ring.get(key) is not None       # recent one survived
    old = f"{int((time.time() - 10) * 1000):015d}"
    assert ring.get(old) is None           # stale one gone


def test_envelope_has_required_fields():
    cfg = Config(); cfg.sensor_id = "sdr-x"; cfg.lat = 1.0; cfg.lon = 2.0
    up = Uplink(cfg)
    det = Detection(score=0.8, snr_db=15, rssi_dbm=-40, peak_freq_mhz=2431.5,
                    occupied_bw_mhz=10.0, burst_count=2, cadence_ms=600.0,
                    signature_class="dji_ocusync")
    env = up.build_envelope(det, "2026-09-04T11:00:00.000Z", signature_class="dji_ocusync")
    for field in ("schema_version", "detection_id", "sensor_id", "captured_at",
                  "source", "detection_probability", "band"):
        assert field in env
    assert env["source"] == "hackrf"
    assert env["receiver_position"] == {"lat": 1.0, "lon": 2.0}
    assert env["signature_class"] == "dji_ocusync"
    # Stage-1 only fields never leak into the v1 envelope (additionalProperties: false).
    assert "morphology" not in env and "duty_cycle" not in env


def _contract_enum():
    import json
    from pathlib import Path
    schema = Path(__file__).resolve().parents[2] / "contracts" / "rf-detection.v1.schema.json"
    if not schema.exists():
        return set(CONTRACT_CLASSES)
    return set(json.loads(schema.read_text())["properties"]["signature_class"]["enum"])


def test_to_contract_class_maps_every_stage2_label_into_the_enum():
    enum = _contract_enum()
    assert set(CONTRACT_CLASSES) == enum
    for label in STAGE2_CLASSES:
        assert to_contract_class(label) in enum, label
    assert to_contract_class("wifi_uas") == "wifi_drone"
    assert to_contract_class("analog_fpv") == "fpv_analog"
    assert to_contract_class("non_uas") == "noise"
    assert to_contract_class("other_uas") == "unknown"
    assert to_contract_class("unknown") == "unknown"
    assert to_contract_class("dji_ocusync") == "dji_ocusync"
    # Legacy/contract labels pass through; garbage never escapes the enum.
    for legacy in CONTRACT_CLASSES:
        assert to_contract_class(legacy) == legacy
    assert to_contract_class("ofdm_candidate") == "unknown"


def test_envelope_signature_class_is_always_contract_enum():
    cfg = Config(); cfg.sensor_id = "sdr-x"
    up = Uplink(cfg)
    det = Detection(score=0.5, snr_db=12, rssi_dbm=-50, peak_freq_mhz=2431.5,
                    occupied_bw_mhz=16.0, burst_count=0, cadence_ms=None,
                    signature_class="unknown", morphology="continuous_wideband_candidate",
                    duty_cycle=0.96)
    enum = _contract_enum()
    for label in STAGE2_CLASSES:
        env = up.build_envelope(det, "2026-09-04T11:00:00.000Z", signature_class=label)
        assert env["signature_class"] in enum, label
    assert up.build_envelope(det, "2026-09-04T11:00:00.000Z",
                             signature_class="wifi_uas")["signature_class"] == "wifi_drone"
