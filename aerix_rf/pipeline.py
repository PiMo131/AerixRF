"""One IQ window through the whole chain -- shared by live, lock, capture and replay.

    IQWindow -> spectrogram -> stage-1 morphology (energy) -> stage-2 class -> stage-3 decode

The three stages are kept semantically separate on purpose (see the project doc):

  * stage 1 says what the RF *looks like* (morphology, score = "how interesting"),
  * stage 2 says what it *probably is* (probabilistic label + confidence + source),
  * stage 3 says what it *provably is* (CRC-valid protocol decode).

A decode is never gated on the classifier: a valid protocol decode is stronger
evidence than any ML label, so the decoder runs whenever stage 1 sees candidate
bursts, regardless of what stage 2 thinks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import Config
from .dsp import spectrogram
from .dsp.spectrogram import Spectrogram
from .detect import energy
from .detect.energy import Detection
from .classify import model as classify_model
from .classify.model import Classification
from .decode import droneid
from .sdr.capture import IQWindow


def iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Morphologies for which a DroneID decode attempt is worth the CPU. Decode is
# cheap on quiet windows (envelope only) but we still skip flat noise.
_DECODE_MORPHOLOGIES = {"burst_wideband_candidate", "ofdm_candidate", "wideband_candidate",
                        "fhss_candidate", "continuous_wideband_candidate", "unknown"}


@dataclass
class FrameResult:
    window: IQWindow
    spec: Spectrogram
    det: Detection
    cls: Classification
    plausible: bool
    attempts: list[Any] = field(default_factory=list)     # decode.DecodeAttempt
    decoded: Any = None                                    # decode.DroneIdResult | None
    elapsed_ms: float = 0.0

    # --- derived -------------------------------------------------------------
    @property
    def captured_at(self) -> float:
        return self.window.captured_at

    @property
    def decode_level(self) -> str:
        """Best validation level reached this window: none | A | B | C (see doc §1.5)."""
        order = {"none": 0, "A": 1, "B": 2, "C": 3, "D": 4}
        best = "none"
        for a in self.attempts:
            lvl = getattr(a, "level", "none")
            if order.get(lvl, 0) > order[best]:
                best = lvl
        return best

    def record(self) -> dict[str, Any]:
        """The detections.jsonl line: everything the field report needs."""
        d = self.det
        c = self.cls
        return {
            "ts": iso(self.captured_at),
            "captured_at": self.captured_at,
            "center_freq_mhz": self.window.center_freq_hz / 1e6,
            "peak_freq_mhz": round(d.peak_freq_mhz, 3),
            "score": round(d.score, 3),
            "snr_db": round(d.snr_db, 1),
            "rssi_dbm": round(d.rssi_dbm, 1),
            "bw_mhz": round(d.occupied_bw_mhz, 2),
            "burst_count": d.burst_count,
            "cadence_ms": None if d.cadence_ms is None else round(d.cadence_ms, 1),
            "duty_cycle": round(getattr(d, "duty_cycle", 0.0), 3),
            "morphology": getattr(d, "morphology", "unknown"),
            "plausible": self.plausible,
            "class": c.signature_class,
            "class_confidence": round(c.confidence, 3),
            "confidence": round(c.confidence, 3),          # alias read by session.report
            "class_source": c.source,
            "class_abstained": bool(getattr(c, "abstained", False)),
            "model_sample_rate_mismatch": bool(getattr(c, "sample_rate_mismatch", False)),
            "decode_level": self.decode_level,
            "decode_state": self.decode_level,             # alias read by session.report
            "decode_attempts": len(self.attempts),
            "crc_ok": self.decoded is not None,
            "serial": getattr(self.decoded, "serial", None),
            "capture_health": self.window.health(),
            "elapsed_ms": round(self.elapsed_ms, 1),
        }

    def decode_records(self) -> list[dict[str, Any]]:
        """decode.jsonl lines, one per attempted burst."""
        out = []
        for a in self.attempts:
            res = getattr(a, "result", None)
            out.append({
                "ts": iso(self.captured_at),
                "captured_at": self.captured_at,
                "center_freq_mhz": self.window.center_freq_hz / 1e6,
                "start_sample": getattr(a, "start_sample", None),
                "duration_ms": getattr(a, "duration_ms", None),
                "peak_power_db": getattr(a, "peak_power_db", None),
                "level": getattr(a, "level", "none"),
                "zc_score": getattr(a, "zc_score", None),
                "cfo_hz": getattr(a, "cfo_hz", None),
                "integer_cfo_bins": getattr(a, "integer_cfo_bins", None),
                "center_offset_mhz": round(getattr(a, "center_offset_hz", 0.0) / 1e6, 3),
                "occupied_bw_mhz": round(getattr(a, "occupied_bw_hz", 0.0) / 1e6, 2),
                "droneid_shaped": bool(getattr(a, "droneid_shaped", False)),
                "crc_ok": bool(getattr(a, "crc_ok", False)),
                "error": getattr(a, "error", None),
                "serial": getattr(res, "serial", None),
                "protocol": getattr(res, "protocol", None),
                "drone_lat": getattr(res, "drone_lat", None),
                "drone_lon": getattr(res, "drone_lon", None),
                "operator_lat": getattr(res, "operator_lat", None),
                "operator_lon": getattr(res, "operator_lon", None),
                "home_lat": getattr(res, "home_lat", None),
                "home_lon": getattr(res, "home_lon", None),
                "drone_height": getattr(res, "drone_height", None),
            })
        return out

    def status_line(self) -> str:
        """Compact human line for the field terminal."""
        d, c, w = self.det, self.cls, self.window
        hb = w.health()
        health = "ok" if hb["capture_complete"] else f"INCOMPLETE(-{hb['dropped_or_missing_samples']})"
        if hb.get("rate_warning") and hb["capture_complete"]:
            ratio = hb.get("stream_rate_ratio")
            health = f"RATE({ratio:.2f})" if ratio is not None else "RATE(?)"
        if hb.get("gap_before_samples"):
            health += f" gap={hb['gap_before_samples'] / self.window.sample_rate * 1000:.0f}ms"
        cad = f"{d.cadence_ms:.0f}ms" if d.cadence_ms else "-"
        dec = self.decode_level
        if self.decoded is not None:
            dec = f"C serial={self.decoded.serial} lat={self.decoded.drone_lat} lon={self.decoded.drone_lon}"
        flag = "*" if self.plausible else " "
        return (f"{iso(self.captured_at)[11:23]} {w.center_freq_hz/1e6:7.1f}MHz "
                f"pk={d.peak_freq_mhz:7.1f} {flag}score={d.score:.2f} snr={d.snr_db:4.1f}dB "
                f"bw={d.occupied_bw_mhz:4.1f}MHz bursts={d.burst_count:3d} cad={cad:>6} "
                f"morph={getattr(d, 'morphology', '?'):<26} "
                f"cls={c.signature_class}({c.confidence:.2f},{c.source}) "
                f"dec={dec} cap={health} {self.elapsed_ms:.0f}ms")


def process_window(win: IQWindow, cfg: Config, *, decode: bool = True,
                   decode_min_score: float = 0.25) -> FrameResult:
    """Run every stage on one window. Pure function of (window, cfg, model file)."""
    t0 = time.perf_counter()
    center_mhz = win.center_freq_hz / 1e6

    spec = spectrogram.compute(win.iq, win.sample_rate, cfg.fft_size)
    det = energy.detect(spec, center_mhz, cfg.snr_threshold_db, cfg.occupied_bw_ref_mhz, cfg.gain_db)
    cls = classify_model.classify_window(spec, det, center_mhz)
    plausible = det.score >= cfg.score_threshold

    attempts: list[Any] = []
    decoded = None
    morph = getattr(det, "morphology", "unknown")
    if decode and win.iq.size and (det.score >= decode_min_score or morph in _DECODE_MORPHOLOGIES) \
            and morph != "noise":
        attempts = droneid.decode_all(win.iq, win.sample_rate)
        for a in attempts:
            if getattr(a, "crc_ok", False) and getattr(a, "result", None) is not None:
                decoded = a.result
                break

    return FrameResult(window=win, spec=spec, det=det, cls=cls, plausible=plausible,
                       attempts=attempts, decoded=decoded,
                       elapsed_ms=(time.perf_counter() - t0) * 1000.0)
