"""Server uplink: provisioning, heartbeat, Path 2 detections, Path 1a ODID-cue poll.

RF detections go to the NEW /v1/rf-detections:batch route, deliberately separate
from the ODID /v1/observations:batch pipeline. All network calls are best-effort:
a failure is logged and the loop continues (store-and-forward is a later refinement).
"""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

import httpx

from ..config import Config
from ..detect.energy import Detection

log = logging.getLogger("aerix.rf.uplink")

SCHEMA_VERSION = "1.0.0"

# contracts/rf-detection.v1.schema.json: signature_class enum. The box's stage-2
# vocabulary (classify.model.STAGE2_CLASSES) is richer; it is folded into the
# server enum here and only here. Phase 2 extends the contract (morphology,
# source/version, capture health); until then nothing else may be added to the
# envelope (additionalProperties: false).
CONTRACT_CLASSES = ("dji_ocusync", "wifi_drone", "fpv_analog", "noise", "unknown")

_STAGE2_TO_CONTRACT = {
    "dji_ocusync": "dji_ocusync",
    "wifi_uas": "wifi_drone",
    "analog_fpv": "fpv_analog",
    "non_uas": "noise",
    "other_uas": "unknown",     # the v1 enum has no "some drone" bucket
    "uas_link": "unknown",      # features_v2 generic UAS-link call; v1 enum has no bucket for it
    "background": "unknown",    # features_v2 negative class; v1 enum has no "background" bucket
    "unknown": "unknown",
    # legacy / contract labels pass straight through
    "wifi_drone": "wifi_drone",
    "fpv_analog": "fpv_analog",
    "noise": "noise",
}


def to_contract_class(stage2_label: str) -> str:
    """Stage-2 label -> rf-detection.v1 ``signature_class`` enum (never raises)."""
    return _STAGE2_TO_CONTRACT.get(str(stage2_label), "unknown")


class Uplink:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._client = httpx.Client(base_url=cfg.server_url, timeout=10.0, verify=False) \
            if cfg.server_url else None

    @property
    def enabled(self) -> bool:
        return self._client is not None and bool(self.cfg.token)

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.token}"}

    # --- provisioning (operator runs once; can also auto-provision) ---
    def provision(self) -> tuple[str, str] | None:
        if self._client is None:
            return None
        try:
            r = self._client.post("/v1/sensors:provision", json={"class": "hackrf"})
            r.raise_for_status()
            data = r.json()
            return data["sensor_id"], data["token"]
        except Exception as exc:  # noqa: BLE001
            log.warning("provision failed: %s", exc)
            return None

    def heartbeat(self, radios: list[str]) -> None:
        if not self.enabled:
            return
        body: dict[str, Any] = {"sensor_id": self.cfg.sensor_id, "radios": radios}
        if self.cfg.lat is not None and self.cfg.lon is not None:
            body["position"] = {"lat": self.cfg.lat, "lon": self.cfg.lon}
        try:
            self._client.post("/v1/devices/heartbeat", json=body, headers=self._auth())
        except Exception as exc:  # noqa: BLE001
            log.debug("heartbeat failed: %s", exc)

    # --- Path 2 / Path 1: RF detection frames ---
    def build_envelope(self, det: Detection, captured_at_iso: str, *,
                       signature_class: str, spectrogram_png: bytes | None = None,
                       odid_cue: dict | None = None, verified: bool = False,
                       decoded: dict | None = None) -> dict[str, Any]:
        env: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "detection_id": str(uuid.uuid4()),
            "sensor_id": self.cfg.sensor_id,
            "captured_at": captured_at_iso,
            "source": "hackrf",
            "detection_probability": round(det.score, 4),
            "rssi_dbm": round(det.rssi_dbm, 1),
            "band": self.cfg.band,
            "center_freq_mhz": round(det.peak_freq_mhz, 3),
            "bandwidth_mhz": round(det.occupied_bw_mhz, 2),
            "signature_class": to_contract_class(signature_class),
            "snr_db": round(det.snr_db, 1),
            "verified": verified,
        }
        if det.cadence_ms is not None:
            env["cadence_ms"] = round(det.cadence_ms, 1)
        if self.cfg.lat is not None and self.cfg.lon is not None:
            env["receiver_position"] = {"lat": self.cfg.lat, "lon": self.cfg.lon}
        if spectrogram_png is not None:
            env["spectrogram"] = {
                "png_base64": base64.b64encode(spectrogram_png).decode("ascii"),
            }
        if odid_cue is not None:
            env["odid_cue"] = odid_cue
        if decoded is not None:
            env["decoded"] = decoded
        return env

    def post_detections(self, envelopes: list[dict[str, Any]]) -> bool:
        if not self.enabled or not envelopes:
            return False
        try:
            r = self._client.post("/v1/rf-detections:batch",
                                  json={"rf_detections": envelopes}, headers=self._auth())
            r.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("rf-detections post failed: %s", exc)
            return False

    # --- Path 1a: poll for active ODID cues at this sensor's site ---
    def poll_odid_cues(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            r = self._client.get("/v1/rf/odid-cues",
                                 params={"sensor_id": self.cfg.sensor_id}, headers=self._auth())
            r.raise_for_status()
            return r.json().get("cues", [])
        except Exception as exc:  # noqa: BLE001
            log.debug("odid-cue poll failed: %s", exc)
            return []

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
