"""Build a DroneID burst from a frame, so the receiver can be tested.

Without a DJI drone on the bench there is no way to know whether a decoder
works.  This module generates a burst that is correct in every respect the
receiver depends on - frame layout, CRC-16, CRC-24A, rate matching,
scrambling, QPSK mapping, Zadoff-Chu pilots, cyclic prefixes, timing - and can
then be given a frequency offset, a timing offset and noise.  A decode of that
burst exercises the whole chain.

One deliberate simplification: the two parity streams of the turbo code are
filled with a deterministic pseudo-random pattern instead of being computed by
a real LTE turbo encoder.  The receiver reads only the systematic bits (see
:mod:`antsdr_toolkit.droneid.fec`), so the parity content does not affect the
result, and writing an encoder whose decoder does not exist yet would be
pretence.  What this does mean is that these bursts cannot be used to measure
coding gain - they measure everything *except* the turbo code.

This is test and calibration material.  It is never transmitted: the toolkit
is receive-only (``antsdr/docs/decisions/ADR-0001``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from . import constants as C
from . import fec
from .zc import carrier_indices, zc_frequency

__all__ = ["DEFAULT_TX", "DroneIdTx", "make_burst", "make_frame_bytes", "place_burst"]

#: Degrees to the int32 encoding DJI uses. Shared with the receiver so the
#: two halves of the codec cannot disagree; see :data:`constants.COORD_SCALE`.
_DEG_SCALE = C.COORD_SCALE


@dataclass(frozen=True)
class DroneIdTx:
    """The fields a synthetic burst carries."""

    serial: str = "TEST0123456789AB"
    drone_lat: float = 51.9225
    drone_lon: float = 4.47917
    pilot_lat: float = 51.9230
    pilot_lon: float = 4.47990
    home_lat: float = 51.9231
    home_lon: float = 4.47995
    height_m: float = 42.0
    altitude_m: float = 61.0
    v_north_m_s: float = 3.0
    v_east_m_s: float = -1.5
    v_up_m_s: float = 0.5
    yaw_deg: float = 214.0
    gps_time_ms: int = 1_756_000_000_000
    product_type: int = 63  # Mini 2
    sequence: int = 7
    state_info: int = 0x1234
    uuid: bytes = b""


def _deg_to_int(deg: float) -> int:
    return round(float(deg) * _DEG_SCALE)


DEFAULT_TX = DroneIdTx()
"""A single shared example transmitter, used as the default everywhere."""


def make_frame_bytes(tx: DroneIdTx = DEFAULT_TX) -> bytes:
    """The 91-byte DroneID frame, CRC-16 included.

    Layout (little-endian), as documented by the reference transmitter::

        length(1) type(1) version(1) sequence(2) state(2) serial(16)
        lon(4) lat(4) height(2) altitude(2) v_n(2) v_e(2) v_u(2) yaw(2)
        gps_time(8) pilot_lat(4) pilot_lon(4) home_lon(4) home_lat(4)
        product(1) uuid_len(1) uuid(19) pad(1) crc16(2)
    """
    serial = tx.serial.encode("ascii", "replace")[:16].ljust(16, b"\x00")
    uuid = tx.uuid[:19].ljust(19, b"\x00")
    body = struct.pack(
        "<BBBHH16siihhhhhhQiiiiBB19sB",
        88,                    # length byte, as the reference encoder writes it
        16,                    # message type
        2,                     # version
        int(tx.sequence) & 0xFFFF,
        int(tx.state_info) & 0xFFFF,
        serial,
        _deg_to_int(tx.drone_lon),
        _deg_to_int(tx.drone_lat),
        round(tx.height_m),
        round(tx.altitude_m),
        round(tx.v_north_m_s),
        round(tx.v_east_m_s),
        round(tx.v_up_m_s),
        round(tx.yaw_deg * 100.0),
        int(tx.gps_time_ms),
        _deg_to_int(tx.pilot_lat),
        _deg_to_int(tx.pilot_lon),
        _deg_to_int(tx.home_lon),
        _deg_to_int(tx.home_lat),
        int(tx.product_type) & 0xFF,
        len(tx.uuid) & 0xFF,
        uuid,
        0,
    )
    assert len(body) == C.FRAME_BYTES - 2, len(body)
    crc = fec.crc16_dji(body)
    return body + struct.pack("<H", crc)


def make_payload_bytes(tx: DroneIdTx = DEFAULT_TX, *,
                       tail: bytes | None = None) -> bytes:
    """The 176-byte turbo payload: frame, tail bytes and CRC-24A."""
    frame = make_frame_bytes(tx)
    filler = bytes(C.PAYLOAD_BYTES - 3 - len(frame)) if tail is None else tail
    if len(filler) != C.PAYLOAD_BYTES - 3 - len(frame):
        raise ValueError(f"tail must be {C.PAYLOAD_BYTES - 3 - len(frame)} bytes")
    body = frame + filler
    crc = fec.crc24a(body)
    return body + bytes(((crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF))


def _coded_bits(payload: bytes, rng: np.random.Generator) -> np.ndarray:
    """Rate-matched, scrambled bits for one burst.

    The systematic stream is the payload; the parity streams are noise, for
    the reason given in the module docstring.
    """
    systematic = np.concatenate([fec.bytes_to_bits(payload),
                                 np.zeros(4, dtype=np.uint8)])  # four tail bits
    assert systematic.size == C.RATE_MATCH_D
    parity1 = rng.integers(0, 2, C.RATE_MATCH_D).astype(np.uint8)
    parity2 = rng.integers(0, 2, C.RATE_MATCH_D).astype(np.uint8)
    coded = fec.rate_match(systematic, parity1, parity2)
    return fec.scramble(coded)


def _qpsk(bits: np.ndarray) -> np.ndarray:
    """LTE QPSK: bit pair (b0, b1) -> ((1-2b0) + j(1-2b1)) / sqrt(2)."""
    b = np.asarray(bits, dtype=np.uint8).reshape(-1, 2)
    real = 1.0 - 2.0 * b[:, 0]
    imag = 1.0 - 2.0 * b[:, 1]
    return ((real + 1j * imag) / np.sqrt(2.0)).astype(np.complex128)


def make_burst(
    sample_rate_hz: float = 15.36e6,
    tx: DroneIdTx = DEFAULT_TX,
    *,
    rng: np.random.Generator | None = None,
    legacy: bool = False,
) -> np.ndarray:
    """One complete DroneID burst as complex64 at unit average power.

    9 symbols (8 with ``legacy``), cyclic prefixes included: 9880 samples at
    15.36 MSPS.
    """
    rng = np.random.default_rng(0) if rng is None else rng
    n_fft = C.fft_size(sample_rate_hz)
    cps = C.cp_schedule(sample_rate_hz, legacy=legacy)
    payload = make_payload_bytes(tx)
    bits = _coded_bits(payload, rng)
    symbols_bits = bits.reshape(len(C.DATA_SYMBOLS), -1)

    idx = carrier_indices(n_fft)
    n_symbols = len(cps)
    data_positions = C.data_symbol_indices(legacy=legacy)
    zc_positions = C.ZC_SYMBOLS if not legacy else tuple(i - 1 for i in C.ZC_SYMBOLS)

    out = np.zeros(C.burst_length(sample_rate_hz, legacy=legacy), dtype=np.complex128)
    pos = 0
    data_seen = 0
    for sym in range(n_symbols):
        spectrum = np.zeros(n_fft, dtype=np.complex128)
        if sym in zc_positions:
            root = C.ZC_ROOTS[zc_positions.index(sym)]
            spectrum = zc_frequency(root, n_fft) / np.sqrt(C.N_DATA_CARRIERS)
        elif sym in data_positions:
            spectrum[idx] = _qpsk(symbols_bits[data_seen]) / np.sqrt(C.N_DATA_CARRIERS)
            data_seen += 1
        else:
            # symbol 0: the scrambler makes it descramble to zeros; the
            # reference transmitter sends the scrambler sequence itself.
            filler = fec.gold_sequence(C.N_DATA_CARRIERS * 2)
            spectrum[idx] = _qpsk(filler) / np.sqrt(C.N_DATA_CARRIERS)
        body = np.fft.ifft(np.fft.ifftshift(spectrum)) * n_fft / np.sqrt(n_fft)
        cp = cps[sym]
        out[pos:pos + cp] = body[-cp:]
        out[pos + cp:pos + cp + n_fft] = body
        pos += cp + n_fft
    assert data_seen == len(C.DATA_SYMBOLS)
    power = float(np.mean(np.abs(out) ** 2))
    if power > 0:
        out /= np.sqrt(power)
    return out.astype(np.complex64)


def place_burst(
    sample_rate_hz: float,
    n_samples: int,
    *,
    burst: np.ndarray | None = None,
    t_start_s: float = 0.0,
    cfo_hz: float = 0.0,
    snr_db: float = 20.0,
    rng: np.random.Generator | None = None,
    tx: DroneIdTx = DEFAULT_TX,
    sample_offset: float = 0.0,
) -> np.ndarray:
    """Place one burst in noise with a frequency and timing offset.

    ``snr_db`` is the burst power relative to the noise power *in the burst's
    own 9 MHz*, not over the whole sample rate, so the number means the same
    thing at 15.36 and 61.44 MSPS.  ``sample_offset`` adds a fractional-sample
    delay, which is what makes a synchroniser's job realistic.
    """
    rng = np.random.default_rng(0) if rng is None else rng
    fs = float(sample_rate_hz)
    if burst is None:
        burst = make_burst(fs, tx, rng=rng)
    burst = np.asarray(burst, dtype=np.complex64)

    if sample_offset:
        n = burst.size
        spectrum = np.fft.fft(burst)
        freqs = np.fft.fftfreq(n)
        spectrum *= np.exp(-2j * np.pi * freqs * float(sample_offset))
        burst = np.fft.ifft(spectrum).astype(np.complex64)

    start = round(float(t_start_s) * fs)
    if start < 0 or start + burst.size > int(n_samples):
        raise ValueError(
            f"burst of {burst.size} samples at t={t_start_s:g} s does not fit in "
            f"{n_samples} samples at {fs / 1e6:g} MSPS"
        )

    noise_power = 1.0
    occupied_fraction = C.occupied_bandwidth_hz() / fs
    # Burst power that puts the in-band SNR at snr_db: the noise inside the
    # occupied 9 MHz is only `occupied_fraction` of the total noise power.
    burst_power = noise_power * occupied_fraction * (10.0 ** (float(snr_db) / 10.0))

    out = (rng.standard_normal(int(n_samples)) + 1j * rng.standard_normal(int(n_samples)))
    out = (out / np.sqrt(2.0)).astype(np.complex64)
    scaled = burst * np.sqrt(burst_power, dtype=np.float32)
    if cfo_hz:
        n = np.arange(burst.size, dtype=np.float64)
        scaled = (scaled * np.exp(2j * np.pi * float(cfo_hz) * n / fs)).astype(np.complex64)
    out[start:start + burst.size] += scaled
    return out
