"""Bridge to the ANTSDR E200 DJI DroneID firmware output (text lines and legacy binary).

The E200 can run a MicroPhase-built firmware that demodulates DJI DroneID on
the SDR (OcuSync 2/3 decoded, OcuSync 4 detected but encrypted) and pushes one
report per decode over Ethernet.  This is an independent re-implementation of
its two wire formats plus blocking socket transports that deliver
:class:`DjiDroneIdReport` values to a callback.  Pure standard library.

Wire formats
------------
New firmware (text): the E200 is the TCP *client* (host port 52002) or sends
UDP datagrams that may split lines.  One comma-separated line per decode,
optionally ending with ``;``::

    dji_O,<proto>,<freq_mhz>,<rssi_db>,<model>(<code>),<serial>,
          <drone_lon>,<drone_lat>,<pilot_lon>,<pilot_lat>,<home_lon>,<home_lat>,
          <altitude>|<height>,<vE>|<vN>|<vU>;

``proto`` 2/3 = decoded OcuSync 2/3; 4 = encrypted O4, where field 4 is
``dji(<hash>)`` with a per-drone hash id and the serial is usually empty.
Longitudes precede latitudes.  Other lines (debug prints, ``=`` heart-beats)
are ignored.

Legacy firmware (binary): the host connects to the E200 on TCP 41030 and reads
frames ``[?, ?, type, len_lo, len_hi, payload...]`` where type 0x01 is DroneID
and ``len`` (little-endian) is the total frame length including the header.
Payload: serial [0:64] and model [64:128] (NUL-padded UTF-8), little-endian
float64 at 129 app_lat, 137 app_lon, 145 drone_lat, 153 drone_lon,
161 height_agl, 169 geodetic_altitude, 177 home_lat, 185 home_lon, 193 freq,
201/209/217 speed_e/n/u (m/s), int16 rssi at 225.

Inferred, not documented
------------------------
MicroPhase publishes no format specification; the layouts were reconstructed
from third-party host tooling (alphafox02/antsdr_dji_droneid), so these are
assumptions: the CSV altitude is multiplied by 10 (0.1 m units?) while height
is metres; CSV velocities are cm/s; the legacy ``freq`` is MHz (values above
1e5 are treated as Hz); the two leading legacy header bytes and payload byte
128 are unknown and unchecked; ``0.0`` coordinates mean unknown, and a
``(lat, lon)`` pair with either component missing, zero, non-finite or out of
range is reported as ``None``/``None``.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
import socket
import struct
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "DEFAULT_LEGACY_PORT", "DEFAULT_NEW_FIRMWARE_PORT", "DjiDroneIdReport", "LegacyFramer",
    "LineFramer", "connect_legacy", "encode_csv_line", "parse_csv_line", "parse_legacy_frame",
    "receive_udp", "serve_new_firmware",
]

log = logging.getLogger(__name__)

DEFAULT_NEW_FIRMWARE_PORT = 52002
DEFAULT_LEGACY_PORT = 41030
CSV_PREFIX = "dji_O"
CSV_FIELD_COUNT = 14
CSV_ALTITUDE_SCALE = 10.0  # assumed 0.1 m units, mirrors host tooling (unverified)
CSV_SPEED_SCALE = 0.01  # cm/s -> m/s (assumed)
LEGACY_TYPE_DRONEID = 0x01
LEGACY_HEADER_LEN = 5
LEGACY_RSSI_OFFSET = 225
LEGACY_MIN_PAYLOAD_LEN = LEGACY_RSSI_OFFSET + 2
PROTOCOLS = ("O2", "O3", "O4", "legacy")
_CSV_PROTOCOLS = {"2": "O2", "3": "O3", "4": "O4"}
_CSV_DIGITS = {"O2": "2", "O3": "3", "O4": "4", "legacy": "2"}  # legacy fw only decoded O2
_MODEL_RE = re.compile(r"^(.*)\(([^()]*)\)$")
_LEGACY_FLOATS = {  # payload offset of each little-endian float64
    "app_lat": 129, "app_lon": 137, "drone_lat": 145, "drone_lon": 153, "height_agl": 161,
    "altitude": 169, "home_lat": 177, "home_lon": 185, "freq": 193,
    "speed_e": 201, "speed_n": 209, "speed_u": 217,
}
_POLL_S = 0.2  # socket timeout used to poll stop events
_CONNECT_TIMEOUT_S = 2.0
_RECV_BYTES = 4096


@dataclass(frozen=True)
class DjiDroneIdReport:
    """One DroneID broadcast, normalised across the firmware formats.

    ``protocol`` is ``"O2"``/``"O3"`` (decoded), ``"O4"`` (encrypted; only
    ``hash_id`` and RF facts are known) or ``"legacy"``.  Frequencies are MHz,
    RSSI is the firmware's dB figure, coordinates are WGS-84 degrees (``None``
    when unknown), ``altitude_m`` is geodetic, ``height_agl_m`` is above the
    take-off point, ``speed_h_m_s`` is ``hypot(vE, vN)`` and ``speed_v_m_s``
    is positive up.  ``raw`` keeps the source line (or frame hex) and
    ``received_at_utc`` an ISO 8601 stamp set by the transports.
    """

    protocol: str
    encrypted: bool = False
    serial: str | None = None
    model: str | None = None
    model_code: str | None = None
    hash_id: str | None = None
    freq_mhz: float | None = None
    rssi_dbm: int | None = None
    drone_lat: float | None = None
    drone_lon: float | None = None
    pilot_lat: float | None = None
    pilot_lon: float | None = None
    home_lat: float | None = None
    home_lon: float | None = None
    altitude_m: float | None = None
    height_agl_m: float | None = None
    speed_h_m_s: float | None = None
    speed_v_m_s: float | None = None
    raw: str = ""
    received_at_utc: str | None = None

    def __post_init__(self) -> None:
        if self.protocol not in PROTOCOLS:
            raise ValueError(f"protocol must be one of {PROTOCOLS}, got {self.protocol!r}")

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-serialisable dict of all fields."""
        return dataclasses.asdict(self)


ReportCallback = Callable[[DjiDroneIdReport], None]


# --------------------------------------------------------------------------
# Field helpers
# --------------------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _float(text: str) -> float | None:
    """Parse a float, ``None`` on failure or non-finite value."""
    try:
        value = float(text.strip())
    except (ValueError, AttributeError):
        return None
    return value if math.isfinite(value) else None


def _int(text: str) -> int | None:
    value = _float(text)
    return None if value is None else round(value)


def _position(lat: float | None, lon: float | None) -> tuple[float | None, float | None]:
    """Validate a coordinate pair: unknown (0.0), non-finite or out of range -> (None, None)."""
    if lat is None or lon is None or lat == 0.0 or lon == 0.0:
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lon)) or abs(lat) > 90.0 or abs(lon) > 180.0:
        return None, None
    return float(lat), float(lon)


def _freq_mhz(value: float | None) -> float | None:
    """Normalise to MHz; a value above 1e5 cannot be MHz so it is assumed to be Hz."""
    if value is None or value <= 0.0:
        return None
    return value / 1e6 if value > 1e5 else value


def _speeds(v_e: float | None, v_n: float | None, v_u: float | None,
            scale: float) -> tuple[float | None, float | None]:
    """Horizontal magnitude and vertical component in m/s from E/N/U components."""
    speed_h = None if v_e is None or v_n is None else math.hypot(v_e, v_n) * scale
    return speed_h, (None if v_u is None else v_u * scale)


def _split_bar(text: str, n: int) -> list[float | None]:
    parts = text.split("|")
    return [_float(p) for p in parts] if len(parts) == n else [None] * n


def _split_model(text: str) -> tuple[str, str]:
    """``"DJI Mini 2(63)" -> ("DJI Mini 2", "63")``; no parentheses -> (text, "")."""
    match = _MODEL_RE.match(text.strip())
    return (match.group(1).strip(), match.group(2).strip()) if match else (text.strip(), "")


def _cstr(data: bytes) -> str | None:
    """Decode a NUL-padded UTF-8 field; ``None`` when empty."""
    return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip() or None


def _fmt(value: float | None) -> str:
    return "0.0" if value is None else repr(float(value))


# --------------------------------------------------------------------------
# Parsers / encoder
# --------------------------------------------------------------------------
def parse_csv_line(line: str, *, received_at_utc: str | None = None) -> DjiDroneIdReport | None:
    """Parse one new-firmware ``dji_O`` text line; ``None`` for anything else.

    Non-report lines, too few fields or an unknown protocol give ``None``;
    an unparsable numeric field becomes ``None`` without rejecting the line.
    """
    raw = line.strip()
    body = raw.rstrip(";").strip()
    if not body.startswith(CSV_PREFIX + ","):
        return None
    f = [p.strip() for p in body.split(",")]
    if len(f) < CSV_FIELD_COUNT:
        return None
    protocol = _CSV_PROTOCOLS.get(f[1])
    if protocol is None:
        return None
    encrypted = protocol == "O4"
    name, code = _split_model(f[4])
    if encrypted:  # "dji(<hash>)": the name is a constant tag, not a model
        model = None if name.lower() in ("", "dji") else name
        model_code, hash_id = None, code or None
    else:
        model, model_code, hash_id = name or None, code or None, None
    drone_lat, drone_lon = _position(_float(f[7]), _float(f[6]))
    pilot_lat, pilot_lon = _position(_float(f[9]), _float(f[8]))
    home_lat, home_lon = _position(_float(f[11]), _float(f[10]))
    altitude, height = _split_bar(f[12], 2)
    speed_h, speed_v = _speeds(*_split_bar(f[13], 3), scale=CSV_SPEED_SCALE)
    return DjiDroneIdReport(
        protocol=protocol, encrypted=encrypted, serial=f[5] or None, model=model,
        model_code=model_code, hash_id=hash_id, freq_mhz=_freq_mhz(_float(f[2])),
        rssi_dbm=_int(f[3]), drone_lat=drone_lat, drone_lon=drone_lon, pilot_lat=pilot_lat,
        pilot_lon=pilot_lon, home_lat=home_lat, home_lon=home_lon,
        altitude_m=None if altitude is None else altitude * CSV_ALTITUDE_SCALE,
        height_agl_m=height, speed_h_m_s=speed_h, speed_v_m_s=speed_v, raw=raw,
        received_at_utc=received_at_utc,
    )


def legacy_frame_length(header: bytes) -> int | None:
    """Total frame length announced by a legacy header; ``None`` if fewer than 5 bytes."""
    if len(header) < LEGACY_HEADER_LEN:
        return None
    return struct.unpack_from("<H", header, 3)[0]


def parse_legacy_frame(frame: bytes, *,
                       received_at_utc: str | None = None) -> DjiDroneIdReport | None:
    """Parse one legacy binary frame (header + payload); ``None`` if not a DroneID report."""
    frame = bytes(frame)
    length = legacy_frame_length(frame)
    if length is None or frame[2] != LEGACY_TYPE_DRONEID:
        return None
    payload = frame[LEGACY_HEADER_LEN:length]
    if len(payload) < LEGACY_MIN_PAYLOAD_LEN:
        return None
    v: dict[str, float | None] = {}
    for key, offset in _LEGACY_FLOATS.items():
        value = struct.unpack_from("<d", payload, offset)[0]
        v[key] = value if math.isfinite(value) else None
    drone_lat, drone_lon = _position(v["drone_lat"], v["drone_lon"])
    pilot_lat, pilot_lon = _position(v["app_lat"], v["app_lon"])
    home_lat, home_lon = _position(v["home_lat"], v["home_lon"])
    speed_h, speed_v = _speeds(v["speed_e"], v["speed_n"], v["speed_u"], scale=1.0)
    return DjiDroneIdReport(
        protocol="legacy", serial=_cstr(payload[0:64]), model=_cstr(payload[64:128]),
        freq_mhz=_freq_mhz(v["freq"]),
        rssi_dbm=struct.unpack_from("<h", payload, LEGACY_RSSI_OFFSET)[0],
        drone_lat=drone_lat, drone_lon=drone_lon, pilot_lat=pilot_lat, pilot_lon=pilot_lon,
        home_lat=home_lat, home_lon=home_lon, altitude_m=v["altitude"],
        height_agl_m=v["height_agl"],
        speed_h_m_s=speed_h, speed_v_m_s=speed_v, raw=frame.hex(), received_at_utc=received_at_utc,
    )


def encode_csv_line(report: DjiDroneIdReport) -> str:
    """Render a report as a new-firmware ``dji_O`` line (inverse of :func:`parse_csv_line`).

    For tests and fake-firmware servers.  Unknown values are written as
    ``0.0``/empty, the horizontal speed goes into the east component and a
    ``legacy`` report gets protocol digit ``2``, so those are not identities.
    """
    if report.protocol == "O4":
        model_field = f"dji({report.hash_id or ''})"
    else:
        model_field = f"{report.model or ''}({report.model_code or ''})"
    altitude = None if report.altitude_m is None else report.altitude_m / CSV_ALTITUDE_SCALE
    v_e = None if report.speed_h_m_s is None else report.speed_h_m_s / CSV_SPEED_SCALE
    v_u = None if report.speed_v_m_s is None else report.speed_v_m_s / CSV_SPEED_SCALE
    fields = [
        CSV_PREFIX, _CSV_DIGITS[report.protocol], _fmt(report.freq_mhz),
        str(report.rssi_dbm or 0),
        model_field, report.serial or "", _fmt(report.drone_lon), _fmt(report.drone_lat),
        _fmt(report.pilot_lon), _fmt(report.pilot_lat),
        _fmt(report.home_lon), _fmt(report.home_lat),
        f"{_fmt(altitude)}|{_fmt(report.height_agl_m)}", f"{_fmt(v_e)}|0.0|{_fmt(v_u)}",
    ]
    return ",".join(fields) + ";"


# --------------------------------------------------------------------------
# Framers
# --------------------------------------------------------------------------
class LineFramer:
    """Reassemble text lines from arbitrary byte chunks (TCP segments or UDP datagrams).

    Records end at any byte in ``delimiters`` (default: newline or the ``;``
    record terminator, so either or both work).  Empty lines are dropped.  A
    partial line stays buffered until its terminator arrives; :meth:`flush`
    returns it (e.g. on connection close) and a buffer exceeding
    ``max_line_bytes`` without a terminator is discarded to bound memory.
    """

    def __init__(self, *, delimiters: bytes = b"\n;", max_line_bytes: int = 4096,
                 encoding: str = "utf-8") -> None:
        if not delimiters:
            raise ValueError("delimiters must contain at least one byte")
        self._split = re.compile(b"[" + re.escape(delimiters) + b"]").split
        self._max = int(max_line_bytes)
        self._encoding = encoding
        self._buf = bytearray()

    def _decode(self, chunk: bytes) -> str:
        return chunk.decode(self._encoding, errors="replace").strip()

    def feed(self, data: bytes) -> list[str]:
        """Append ``data`` and return every complete, non-empty line now available."""
        self._buf += data
        parts = self._split(bytes(self._buf))
        self._buf = bytearray(parts.pop())
        if len(self._buf) > self._max:
            log.warning("LineFramer: discarding %d bytes without a line terminator", len(self._buf))
            self._buf.clear()
        return [s for s in map(self._decode, parts) if s]

    def flush(self) -> list[str]:
        """Return the buffered partial line (if any) and reset."""
        rest = self._decode(bytes(self._buf))
        self._buf.clear()
        return [rest] if rest else []


class LegacyFramer:
    """Reassemble legacy binary frames from a TCP byte stream using the length header.

    The frame has no known magic bytes, so alignment cannot be recovered
    byte-wise.  A header announcing a length below the header size or above
    ``max_frame_bytes`` marks the stream as corrupt: the buffer is discarded
    (logged) and framing restarts at the next chunk, which for a firmware
    that writes one frame per send re-aligns on its own.
    """

    def __init__(self, *, max_frame_bytes: int = 4096) -> None:
        self._max = int(max_frame_bytes)
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        """Append ``data`` and return every complete frame (header included)."""
        self._buf += data
        frames: list[bytes] = []
        while len(self._buf) >= LEGACY_HEADER_LEN:
            length = legacy_frame_length(self._buf)
            if length is None or not LEGACY_HEADER_LEN <= length <= self._max:
                log.warning("LegacyFramer: implausible frame length %s, discarding %d bytes",
                            length, len(self._buf))
                self._buf.clear()
                break
            if len(self._buf) < length:
                break
            frames.append(bytes(self._buf[:length]))
            del self._buf[:length]
        return frames


# --------------------------------------------------------------------------
# Transports (blocking; run them in a thread and set ``stop_event`` to stop)
# --------------------------------------------------------------------------
def _deliver(on_report: ReportCallback, report: DjiDroneIdReport) -> None:
    try:
        on_report(report)
    except Exception:
        log.exception("DroneID report callback failed")


def _deliver_lines(lines: Iterable[str], on_report: ReportCallback) -> None:
    stamp = _utc_now_iso()
    for line in lines:
        report = parse_csv_line(line, received_at_utc=stamp)
        if report is not None:
            _deliver(on_report, report)


def _recv_loop(sock: socket.socket, stop: threading.Event) -> Iterable[bytes]:
    """Yield received chunks until the peer closes, an error occurs or ``stop`` is set."""
    sock.settimeout(_POLL_S)
    while not stop.is_set():
        try:
            data = sock.recv(_RECV_BYTES)
        except TimeoutError:
            continue
        except OSError:
            return
        if not data:
            return
        yield data


def _serve_text_connection(conn: socket.socket, peer: Any, on_report: ReportCallback,
                           stop: threading.Event) -> None:
    framer = LineFramer()
    with conn:
        for data in _recv_loop(conn, stop):
            _deliver_lines(framer.feed(data), on_report)
        _deliver_lines(framer.flush(), on_report)
    log.info("DroneID firmware %s disconnected", peer)


def serve_new_firmware(host: str, port: int, on_report: ReportCallback, *,
                       stop_event: threading.Event | None = None,
                       on_listening: Callable[[tuple[str, int]], None] | None = None) -> None:
    """Accept new-firmware TCP connections and deliver each decoded line to ``on_report``.

    Blocks until ``stop_event`` is set.  One daemon thread serves each
    connection with its own :class:`LineFramer`.  ``on_listening`` receives
    the bound ``(host, port)`` once the socket listens, which is how callers
    learn an ephemeral port (``port=0``).
    """
    stop = stop_event if stop_event is not None else threading.Event()
    threads: list[threading.Thread] = []
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen()
        srv.settimeout(_POLL_S)
        if on_listening is not None:
            on_listening(srv.getsockname()[:2])
        while not stop.is_set():
            try:
                conn, peer = srv.accept()
            except TimeoutError:
                continue
            log.info("DroneID firmware connected from %s", peer)
            thread = threading.Thread(target=_serve_text_connection,
                                      args=(conn, peer, on_report, stop),
                                      name=f"droneid-{peer[0]}:{peer[1]}", daemon=True)
            thread.start()
            threads = [t for t in threads if t.is_alive()] + [thread]
    for thread in threads:
        thread.join(timeout=5 * _POLL_S)


def receive_udp(host: str, port: int, on_report: ReportCallback, *,
                stop_event: threading.Event | None = None,
                on_listening: Callable[[tuple[str, int]], None] | None = None) -> None:
    """Receive new-firmware lines over UDP; blocks until ``stop_event`` is set.

    Datagrams may split lines, so bytes are reassembled per sender address
    with a :class:`LineFramer`.
    """
    stop = stop_event if stop_event is not None else threading.Event()
    framers: dict[Any, LineFramer] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(_POLL_S)
        if on_listening is not None:
            on_listening(sock.getsockname()[:2])
        while not stop.is_set():
            try:
                data, peer = sock.recvfrom(65535)
            except TimeoutError:
                continue
            if len(framers) > 64 and peer not in framers:
                framers.clear()
            _deliver_lines(framers.setdefault(peer, LineFramer()).feed(data), on_report)


def connect_legacy(host: str, port: int, on_report: ReportCallback, *,
                   stop_event: threading.Event | None = None, reconnect_s: float = 5.0,
                   on_connected: Callable[[tuple[str, int]], None] | None = None) -> None:
    """Connect to a legacy-firmware E200 and deliver each DroneID frame to ``on_report``.

    Blocks until ``stop_event`` is set.  ``reconnect_s`` is the delay before
    retrying after a failed connect or a dropped connection; a value ``<= 0``
    disables reconnecting so the call returns once the first connection ends.
    ``on_connected`` receives the peer ``(host, port)`` after each connect.
    """
    stop = stop_event if stop_event is not None else threading.Event()
    while not stop.is_set():
        try:
            sock = socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT_S)
        except OSError as exc:
            log.warning("legacy DroneID connect to %s:%d failed: %s", host, port, exc)
        else:
            with sock:
                if on_connected is not None:
                    on_connected(sock.getpeername()[:2])
                framer = LegacyFramer()
                for data in _recv_loop(sock, stop):
                    stamp = _utc_now_iso()
                    for frame in framer.feed(data):
                        report = parse_legacy_frame(frame, received_at_utc=stamp)
                        if report is not None:
                            _deliver(on_report, report)
            log.info("legacy DroneID connection to %s:%d closed", host, port)
        if reconnect_s <= 0.0 or stop.wait(reconnect_s):
            return
