"""Box service: the 1 Hz detection loop with server uplink and local cue API.

  capture -> pipeline (spectrogram / morphology / class / decode) -> {Path 2 stream, Path 1 snapshot}

Runs on real hardware or, with --sim, on a synthetic IQ stream. Uplink is optional:
without a server URL/token it runs detection-only and prints one status line per
second. The field-test commands (scan/lock/capture/replay) live in ``cli.py`` and
share ``pipeline.process_window`` with this loop, so what you test offline is what
runs here.
"""

from __future__ import annotations

import json
import logging
import time

from .config import Config
from .dsp import spectrogram
from .pipeline import process_window, iso
from .sdr.capture import make_source
from .buffer.iq_ring import IQRing
from .uplink.client import Uplink
from .local.server import CueBus, LocalControl

log = logging.getLogger("aerix.rf")


def run(cfg: Config, once: bool = False, as_json: bool = True) -> None:
    source = make_source(cfg)
    ring = IQRing("./iq_store", cfg.iq_retention_s) if cfg.mode4_retain_iq else None
    uplink = Uplink(cfg)
    bus = CueBus()
    local = LocalControl(cfg, bus, ring)
    local.start()

    caps = source.capabilities
    radio_id = f"{caps.receiver_type}:{getattr(source, 'serial', None) or 'unknown'}"
    log.info("aerix-rf up: source=%s radio=%s uplink=%s local=%s.local:%d",
             type(source).__name__, radio_id, uplink.enabled, cfg.mdns_name, cfg.local_port)

    last_heartbeat = 0.0
    recent_cues: dict[str, float] = {}   # serial -> last handled ts, for dedup

    try:
        for win in source.windows():
            captured_at = win.captured_at or time.time()
            fr = process_window(win, cfg)
            det, cls, plausible = fr.det, fr.cls, fr.plausible

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

            decoded = None
            if fr.decoded is not None:
                decoded = {k: v for k, v in fr.decoded.__dict__.items() if v is not None}

            # NOTE: `verified` here means "an ODID cue coincided with this window" --
            # temporal coincidence only. Correlation quality is a Phase-2 server concern.
            verified = active_cue is not None
            want_png = cfg.mode2_png_every_second or (cfg.mode1_png_on_detection and plausible) or verified
            send = plausible or cfg.mode2_png_every_second or verified

            png = spectrogram.to_png(fr.spec) if (want_png and send and uplink.enabled) else None
            if (plausible or verified or decoded) and ring is not None:
                ring.store(win.iq, captured_at, {"score": det.score, "class": cls.signature_class,
                                                 "morphology": getattr(det, "morphology", None),
                                                 "verified": verified, "crc_ok": decoded is not None,
                                                 "center_freq_hz": win.center_freq_hz,
                                                 "capture_health": win.health()})

            if send and uplink.enabled:
                odid_cue = None
                if active_cue is not None:
                    odid_cue = {"serial": active_cue.get("serial"),
                                "source": active_cue.get("source", "server"),
                                "transport": active_cue.get("transport")}
                env = uplink.build_envelope(det, iso(captured_at), signature_class=cls.signature_class,
                                            spectrogram_png=png, odid_cue=odid_cue,
                                            verified=verified, decoded=decoded)
                uplink.post_detections([env])

            if as_json:
                rec = fr.record()
                rec.update({"verified": verified, "sent": bool(send and uplink.enabled)})
                print(json.dumps(rec), flush=True)
            else:
                print(fr.status_line(), flush=True)

            if not win.complete:
                log.warning("incomplete capture window: %s", win.health())

            if uplink.enabled and captured_at - last_heartbeat > 60.0:
                uplink.heartbeat([radio_id])
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
    from .cli import main as cli_main
    raise SystemExit(cli_main())


if __name__ == "__main__":
    main()
