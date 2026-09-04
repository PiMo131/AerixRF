"""IQ retention purge (GDPR bound) and envelope shape."""

import time

import numpy as np

from aerix_rf.buffer.iq_ring import IQRing
from aerix_rf.config import Config
from aerix_rf.uplink.client import Uplink
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
