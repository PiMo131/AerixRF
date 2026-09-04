"""Local cue + control API (Path 1b), LAN-only, mDNS-advertised as <name>.local.

Lets the co-located ESP (or any local device) direct the box directly, without a
server round-trip and even when the uplink is down. The main loop drains the
CueBus each second; a cue there triggers a verified snapshot exactly like a
server (Path 1a) cue, tagged source="local".
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from fastapi import FastAPI, Header, HTTPException
import uvicorn

from ..config import Config

log = logging.getLogger("aerix.rf.local")


class CueBus:
    """Thread-safe hand-off from the API thread to the detection loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: deque[dict] = deque(maxlen=64)

    def push(self, cue: dict) -> None:
        with self._lock:
            self._items.append(cue)

    def drain(self) -> list[dict]:
        with self._lock:
            out = list(self._items)
            self._items.clear()
        return out


def build_app(cfg: Config, bus: CueBus, iq_ring=None) -> FastAPI:
    app = FastAPI(title="AERIX RF local control", docs_url=None, openapi_url=None)

    def _check(token: str | None) -> None:
        if cfg.local_token and token != cfg.local_token:
            raise HTTPException(status_code=401, detail="bad local token")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "sensor_id": cfg.sensor_id or None}

    @app.post("/cue")
    def cue(body: dict, x_local_token: str | None = Header(default=None)) -> dict:
        # Local ODID/detection cue -> verified Path-1b snapshot.
        _check(x_local_token)
        bus.push({
            "kind": "odid",
            "source": "local",
            "serial": body.get("serial"),
            "transport": body.get("transport"),
            "rssi": body.get("rssi"),
            "ts": body.get("ts") or time.time(),
        })
        return {"accepted": True}

    @app.post("/snapshot")
    def snapshot(x_local_token: str | None = Header(default=None)) -> dict:
        _check(x_local_token)
        bus.push({"kind": "snapshot", "source": "local", "ts": time.time()})
        return {"accepted": True}

    @app.get("/iq/{key}")
    def iq(key: str, x_local_token: str | None = Header(default=None)) -> dict:
        _check(x_local_token)
        if iq_ring is None:
            raise HTTPException(status_code=404, detail="iq retention disabled")
        arr = iq_ring.get(key)
        if arr is None:
            raise HTTPException(status_code=404, detail="no iq for key")
        return {"key": key, "samples": int(arr.size)}  # metadata; bytes fetched via a stream later

    return app


class LocalControl:
    def __init__(self, cfg: Config, bus: CueBus, iq_ring=None) -> None:
        self.cfg = cfg
        self.app = build_app(cfg, bus, iq_ring)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._zc = None

    def start(self) -> None:
        config = uvicorn.Config(self.app, host=self.cfg.local_bind,
                                port=self.cfg.local_port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        self._advertise_mdns()

    def _advertise_mdns(self) -> None:
        try:
            import socket
            from zeroconf import ServiceInfo, Zeroconf

            self._zc = Zeroconf()
            info = ServiceInfo(
                "_http._tcp.local.",
                f"{self.cfg.mdns_name}._http._tcp.local.",
                addresses=[socket.inet_aton(_local_ip())],
                port=self.cfg.local_port,
                properties={"role": "aerix-rf"},
                server=f"{self.cfg.mdns_name}.local.",
            )
            self._zc.register_service(info)
            log.info("mDNS: %s.local:%d", self.cfg.mdns_name, self.cfg.local_port)
        except Exception as exc:  # noqa: BLE001
            log.warning("mDNS advertise failed (LAN cue by IP still works): %s", exc)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._zc is not None:
            self._zc.close()


def _local_ip() -> str:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()
