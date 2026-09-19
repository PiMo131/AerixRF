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
from dataclasses import dataclass, field, replace as dc_replace
from datetime import datetime, timezone
from typing import Any

from .config import Config
from .dsp import spectrogram
from .dsp.spectrogram import Spectrogram
from .detect import energy
from .detect.energy import Detection
from .detect import raster as raster_mod
from .detect.bursts import BurstEvent
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
                        "continuous_wideband_candidate", "unknown",
                        # stage-1 link-signature vocabulary (replaces "fhss_candidate")
                        "fhss_1mhz_grid_candidate", "fhss_2mhz_grid_candidate",
                        "rc_link_family_candidate", "hopping_candidate",
                        "fixed_channel_burst_candidate", "droneid_cadence_candidate"}


@dataclass
class SessionCadenceStore:
    """Bounded (~10 s) rolling store of :class:`BurstEvent`\\ s across windows,
    in absolute (session) time, so R3 cadence (docs/design/stage1-link-signatures.md
    S4) can see the >= 5 events spanning >= 3 s that a single 1 s window
    structurally cannot (design S1: 640 ms gives <= 1 interval per window).

    Not threaded through by default: ``process_window`` only consults one when
    a caller explicitly passes it, so existing single-window callers (tests,
    anything that doesn't own a multi-window session loop) keep today's pure,
    stateless behaviour. ``cli.py``'s live and replay loops each own one
    instance for the lifetime of a run.
    """
    window_s: float = 10.0
    events: list[BurstEvent] = field(default_factory=list)
    # Independent review fix (2026-09-19 #2a): frame_dt_s was not forwarded
    # to analyze_raster() here, so period_test()'s C1 sub-frame dt-filter
    # (docs/design/stage1-rc-positives-2026-09-19.md) was silently inactive
    # for session-level (multi-window, pooled) evidence -- co-temporal
    # trains pooled across windows could alias to a near-zero dt just as the
    # single-window path did before C1. Tracked as the MAX frame_dt_s of all
    # contributing windows (not per-event; the dt-filter only needs a single
    # conservative floor, and windows in one session normally share one
    # frame pitch, so taking the max is a documented, simple, safe choice
    # rather than a per-event lookup).
    frame_dt_s: float | None = None

    def add(self, det_events: list[BurstEvent], captured_at: float,
            frame_dt_s: float | None = None) -> None:
        if not det_events:
            return
        shifted = [dc_replace(e, t_start=e.t_start + captured_at, t_end=e.t_end + captured_at)
                   for e in det_events]
        self.events.extend(shifted)
        cutoff = max(e.t_end for e in self.events) - self.window_s
        self.events = [e for e in self.events if e.t_end >= cutoff]
        if frame_dt_s is not None and frame_dt_s > 0.0:
            self.frame_dt_s = frame_dt_s if self.frame_dt_s is None else max(self.frame_dt_s, frame_dt_s)

    def result(self):
        """Latest session-level ``RasterResult``, or ``None`` if empty."""
        if not self.events:
            return None
        return raster_mod.analyze_raster(self.events, frame_dt_s=self.frame_dt_s)


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
    cadence_source: str = "window"                          # "window" | "session" (T3)

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
            "cadence_source": self.cadence_source,
            "stage1": dict(getattr(d, "stage1", {}) or {}),
            "plausible": self.plausible,
            "class": c.signature_class,
            "class_confidence": round(c.confidence, 3),
            "confidence": round(c.confidence, 3),          # alias read by session.report
            "class_source": c.source,
            "class_abstained": bool(getattr(c, "abstained", False)),
            "model_sample_rate_mismatch": bool(getattr(c, "sample_rate_mismatch", False)),
            "features_version": getattr(c, "features_version", None),
            "model_features_mismatch": bool(getattr(c, "model_features_mismatch", False)),
            "features_valid_fraction": (
                None if getattr(c, "features_valid_fraction", None) is None
                else round(c.features_valid_fraction, 3)
            ),
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
                # Additive fields (band-peel multi-hypothesis decode attempts).
                # Old readers/reports that don't know these keys are unaffected.
                "hypotheses_tried": int(getattr(a, "hypotheses_tried", 0)),
                "chosen_center_offset_mhz": getattr(a, "chosen_center_offset_mhz", None),
                "alt_centers_mhz": [round(h / 1e6, 3) for h in getattr(a, "alt_centers_hz", ())],
                # Additive (2026-09-18): rest of frame.DroneIdFrame + post-CRC
                # evidence-quality labels now on DroneIdResult. Old readers that
                # don't know these keys are unaffected.
                "product_type": getattr(res, "product_type", None),
                "uuid": getattr(res, "uuid", None),
                "gps_time_ms": getattr(res, "gps_time_ms", None),
                "semantic_flags": list(getattr(res, "semantic_flags", []) or []),
                "evidence_quality": getattr(res, "evidence_quality", None),
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
        if hb.get("clip_warning"):
            cf = hb.get("clip_fraction")
            health += f" clip={cf * 100:.1f}%" if cf is not None else " clip=?"
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
                   decode_min_score: float = 0.25,
                   session_cadence: SessionCadenceStore | None = None) -> FrameResult:
    """Run every stage on one window. Pure function of (window, cfg, model file)
    unless the caller threads a ``session_cadence`` accumulator through a run's
    windows (T3 session-level R3; see ``SessionCadenceStore``) -- omitted by
    default so single-window callers (tests) stay pure and deterministic."""
    t0 = time.perf_counter()
    center_mhz = win.center_freq_hz / 1e6

    spec = spectrogram.compute(win.iq, win.sample_rate, cfg.fft_size)
    det = energy.detect(spec, center_mhz, cfg.snr_threshold_db, cfg.occupied_bw_ref_mhz, cfg.gain_db,
                        iq=win.iq)
    cls = classify_model.classify_window(spec, det, center_mhz,
                                         iq=win.iq, sample_rate=win.sample_rate)
    plausible = det.score >= cfg.score_threshold

    cadence_source = "window"
    if session_cadence is not None:
        session_cadence.add(det.events, win.captured_at, det.frame_dt_s)
        sres = session_cadence.result()
        if sres is not None:
            if "droneid_cadence_candidate" in sres.labels and det.morphology != "noise":
                det.morphology = "droneid_cadence_candidate"
                if "droneid_cadence_candidate" not in det.stage1.get("labels", []):
                    det.stage1["labels"] = list(det.stage1.get("labels", [])) + ["droneid_cadence_candidate"]
            if det.cadence_ms is None and sres.period.passed and sres.period.n_intervals >= 3:
                det.cadence_ms = sres.period.t_hat_s * 1000.0
                cadence_source = "session"

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
                       elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                       cadence_source=cadence_source)
