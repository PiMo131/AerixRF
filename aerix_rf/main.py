"""Box entry point: the 1 Hz detection loop wiring every stage together.

  capture -> spectrogram -> energy detect -> classify -> {Path 2 stream, Path 1 snapshot}

Runs with real hardware or, with --sim, on a synthetic IQ stream so the whole chain
is exercisable without a HackRF. Uplink is optional: without a server URL/token it
runs detection-only and prints one JSON status line per second.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone

from .config import Config
from .dsp import spectrogram
from .detect import energy
from .classify.model import classify
from .decode import droneid
from .sdr.capture import make_source
from .buffer.iq_ring import IQRing
from .uplink.client import Uplink
from .local.server import CueBus, LocalControl

log = logging.getLogger("aerix.rf")


def _iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def run(cfg: Config, once: bool = False) -> None:
    source = make_source(cfg)
    ring = IQRing("./iq_store", cfg.iq_retention_s) if cfg.mode4_retain_iq else None
    uplink = Uplink(cfg)
    bus = CueBus()
    local = LocalControl(cfg, bus, ring)
    local.start()

    log.info("aerix-rf up: sim=%s uplink=%s local=%s.local:%d",
             cfg.sim, uplink.enabled, cfg.mdns_name, cfg.local_port)

    last_heartbeat = 0.0
    recent_cues: dict[str, float] = {}   # serial -> last handled ts, for dedup

    try:
        for win in source.windows():
            iq = win.iq
            captured_at = win.captured_at or time.time()
            iso = _iso(captured_at)

            spec = spectrogram.compute(iq, cfg.sample_rate, cfg.fft_size)
            det = energy.detect(spec, cfg.center_freq_mhz,
                                cfg.snr_threshold_db, cfg.occupied_bw_ref_mhz, cfg.gain_db)
            cls = classify(det)
            plausible = det.score >= cfg.score_threshold

            # Path 1: gather ODID cues (1a server poll + 1b local bus), dedupe by serial.
            cues = uplink.poll_odid_cues() + bus.drain()
            active_cue = None
            for c in cues:
                serial = str(c.get("serial") or "unknown")
                if captured_at - recent_cues.get(serial, 0.0) < 2.0:
                    continue
                recent_cues[serial] = captured_at
                active_cue = c
                break

            # Decode tier (stage 3): best-effort, only worth trying on a plausible burst.
            decoded = None
            if plausible and droneid.available():
                res = droneid.decode(iq, cfg.sample_rate)
                if res is not None:
                    decoded = {k: v for k, v in res.__dict__.items() if v is not None}

            verified = active_cue is not None
            want_png = cfg.mode2_png_every_second or (cfg.mode1_png_on_detection and plausible) or verified
            send = plausible or cfg.mode2_png_every_second or verified

            png = spectrogram.to_png(spec) if (want_png and send and uplink.enabled) else None
            if (plausible or verified) and ring is not None:
                ring.store(iq, captured_at, {"score": det.score, "class": cls.signature_class,
                                             "verified": verified})

            if send and uplink.enabled:
                odid_cue = None
                if active_cue is not None:
                    odid_cue = {"serial": active_cue.get("serial"),
                                "source": active_cue.get("source", "server"),
                                "transport": active_cue.get("transport")}
                env = uplink.build_envelope(det, iso, signature_class=cls.signature_class,
                                            spectrogram_png=png, odid_cue=odid_cue,
                                            verified=verified, decoded=decoded)
                uplink.post_detections([env])

            print(json.dumps({
                "t": iso, "score": round(det.score, 3), "snr_db": round(det.snr_db, 1),
                "bw_mhz": round(det.occupied_bw_mhz, 1), "freq_mhz": round(det.peak_freq_mhz, 2),
                "cadence_ms": det.cadence_ms, "class": cls.signature_class,
                "plausible": plausible, "verified": verified, "sent": bool(send and uplink.enabled),
            }), flush=True)

            if uplink.enabled and captured_at - last_heartbeat > 60.0:
                uplink.heartbeat(["hackrf-1"])
                last_heartbeat = captured_at

            if once:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        uplink.close()
        local.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="AERIX RF/SDR drone-detection box")
    ap.add_argument("--sim", action="store_true", help="use synthetic IQ (no hardware)")
    ap.add_argument("--once", action="store_true", help="process one window and exit")
    ap.add_argument("--center-mhz", type=float, help="override centre frequency")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.from_env()
    if args.sim:
        cfg.sim = True
    if args.center_mhz:
        cfg.center_freq_mhz = args.center_mhz
    run(cfg, once=args.once)


if __name__ == "__main__":
    main()
