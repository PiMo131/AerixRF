"""Scrambling, rate matching and the two CRCs of a DroneID burst.

The chain a DroneID payload goes through, transmit order:

1. 91 frame bytes, the last two of which are a DJI CRC-16 over the first 89.
2. 82 tail bytes (zero in the reference encoder; real drones send bytes that
   change between power cycles and are not understood).
3. A CRC-24A over those 173 bytes, appended, giving 176 bytes = 1408 bits.
4. An LTE turbo encoder (rate 1/3, four tail bits per stream) producing three
   streams of D = 1412 bits.
5. LTE rate matching to E = 7200 bits, which is exactly what six QPSK symbols
   of 600 carriers hold.
6. XOR with 7200 bits of an LTE Gold sequence seeded with ``c_init``
   0x12345678.

This module implements everything except the turbo code itself.

Why the turbo decoder is not here
---------------------------------
Rate matching writes the systematic bits into the circular buffer first, and
E = 7200 is large enough that the whole systematic block appears in the buffer
before it wraps.  A receiver can therefore read the 1412 systematic bits
straight back out and check the CRC-24A, with no error correction at all.
That is what the NDSS reference receiver does, and it recovers about 78 % of
frames on a clean capture.  Turbo decoding would buy roughly 3 dB and is a
worthwhile follow-up (:func:`turbo_decode` is the hook), but the honest
statement today is that this toolkit decodes DroneID without error
correction and reports the CRC result.
"""

from __future__ import annotations

import numpy as np

from .constants import (
    CRC16_INIT,
    CRC16_POLY,
    CRC24A_POLY,
    PAYLOAD_BYTES,
    RATE_MATCH_D,
    RATE_MATCH_E,
    RM_PERM,
    SCRAMBLER_C_INIT,
    SCRAMBLER_NC,
)

__all__ = [
    "bits_to_bytes",
    "bytes_to_bits",
    "crc16_dji",
    "crc24a",
    "descramble",
    "gold_sequence",
    "rate_match",
    "rate_unmatch_systematic",
    "scramble",
    "sub_block_interleave",
]


def gold_sequence(length: int, c_init: int = SCRAMBLER_C_INIT,
                  n_c: int = SCRAMBLER_NC) -> np.ndarray:
    """LTE pseudo-random sequence of 36.211 section 7.2, as 0/1 bytes.

    Two 31-bit maximal-length shift registers, ``x1`` seeded with a single
    one and ``x2`` with ``c_init`` least-significant bit first, advanced
    ``n_c`` steps before the output is taken.
    """
    if length <= 0:
        raise ValueError(f"length must be positive, got {length}")
    total = int(n_c) + int(length)
    x1 = np.zeros(total + 31, dtype=np.uint8)
    x2 = np.zeros(total + 31, dtype=np.uint8)
    x1[0] = 1
    seed = int(c_init)
    for n in range(31):
        x2[n] = (seed >> n) & 1
    for n in range(total):
        x1[n + 31] = x1[n + 3] ^ x1[n]
        x2[n + 31] = x2[n + 3] ^ x2[n + 2] ^ x2[n + 1] ^ x2[n]
    nc = int(n_c)
    return (x1[nc:nc + length] ^ x2[nc:nc + length]).astype(np.uint8)


def scramble(bits: np.ndarray, c_init: int = SCRAMBLER_C_INIT) -> np.ndarray:
    """XOR ``bits`` with the Gold sequence; its own inverse."""
    b = np.asarray(bits, dtype=np.uint8).ravel()
    return (b ^ gold_sequence(b.size, c_init)).astype(np.uint8)


descramble = scramble  # the operation is an involution; both names read better


def sub_block_interleave(bits: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """LTE sub-block interleaver of 36.212 section 5.1.4.1.1.

    Writes ``D`` bits row-wise into a 32-column matrix padded at the front
    with ``<NULL>`` entries, permutes the columns by :data:`RM_PERM`, and
    reads out column-wise.  Returns the interleaved bit vector and a boolean
    mask marking the null (dummy) positions, which rate matching skips.
    """
    b = np.asarray(bits, dtype=np.uint8).ravel()
    d = b.size
    n_cols = 32
    n_rows = int(np.ceil(d / n_cols))
    n_dummy = n_rows * n_cols - d
    padded = np.full(n_rows * n_cols, 255, dtype=np.uint8)  # 255 marks a dummy
    padded[n_dummy:] = b
    matrix = padded.reshape(n_rows, n_cols)
    permuted = matrix[:, list(RM_PERM)]
    out = permuted.reshape(-1, order="F")  # column-wise read-out
    return np.where(out == 255, 0, out).astype(np.uint8), out == 255


def rate_match(systematic: np.ndarray, parity1: np.ndarray, parity2: np.ndarray,
               e: int = RATE_MATCH_E) -> np.ndarray:
    """LTE rate matching for redundancy version 0.

    The three interleaved streams are concatenated into a circular buffer
    (parity streams interlaced, as the standard requires) and ``e`` bits are
    read out from ``k0``, skipping dummy positions and wrapping as needed.
    """
    v0, null0 = sub_block_interleave(systematic)
    v1, null1 = sub_block_interleave(parity1)
    v2, null2 = sub_block_interleave(parity2)
    interlaced = np.empty(v1.size + v2.size, dtype=np.uint8)
    interlaced[0::2] = v1
    interlaced[1::2] = v2
    interlaced_null = np.empty(null1.size + null2.size, dtype=bool)
    interlaced_null[0::2] = null1
    interlaced_null[1::2] = null2
    buffer_ = np.concatenate([v0, interlaced])
    buffer_null = np.concatenate([null0, interlaced_null])
    keep = ~buffer_null
    usable = buffer_[keep]
    if usable.size == 0:
        raise ValueError("rate matching buffer is entirely null")
    k0 = _k0(v0.size)
    # k0 counts positions in the full buffer; translate it to the compacted one
    start = int(np.count_nonzero(keep[:k0]))
    idx = (np.arange(int(e)) + start) % usable.size
    return usable[idx].astype(np.uint8)


def _k0(v_size: int) -> int:
    """Starting position in the circular buffer for redundancy version 0.

    36.212 gives ``k0 = R * (2 * ceil(K_pi / (8 * R)) * rv + 2)`` with rv = 0,
    which is ``2 * R`` rows into the buffer, i.e. two rows of 32 columns.
    """
    n_cols = 32
    n_rows = v_size // n_cols
    return 2 * n_rows if n_rows else 0


def rate_unmatch_systematic(coded: np.ndarray, d: int = RATE_MATCH_D) -> np.ndarray:
    """Recover the ``d`` systematic bits from ``e`` rate-matched bits.

    The systematic stream occupies the first third of the circular buffer, so
    with E = 7200 and D = 1412 it is fully present and can be read back
    without touching the parity streams.  This is the no-error-correction path
    described in the module docstring.
    """
    e = np.asarray(coded, dtype=np.uint8).ravel()
    n_cols = 32
    n_rows = int(np.ceil(d / n_cols))
    n_dummy = n_rows * n_cols - d
    v_size = n_rows * n_cols
    # Rebuild the compacted buffer positions the transmitter read from.
    _, null0 = sub_block_interleave(np.zeros(d, dtype=np.uint8))
    total_usable_systematic = v_size - n_dummy
    start = int(np.count_nonzero(~null0[:_k0(v_size)]))
    # Positions 0..total_usable_systematic-1 of the compacted buffer hold the
    # interleaved systematic bits; the read-out started at `start` and wrapped.
    interleaved = np.zeros(total_usable_systematic, dtype=np.uint8)
    filled = np.zeros(total_usable_systematic, dtype=bool)
    # The compacted buffer is longer than the systematic part; only the first
    # `total_usable_systematic` entries belong to it.
    usable_total = _usable_buffer_size(d)
    for i, bit in enumerate(e):
        pos = (start + i) % usable_total
        if pos < total_usable_systematic and not filled[pos]:
            interleaved[pos] = bit
            filled[pos] = True
    if not filled.all():
        missing = int((~filled).sum())
        raise ValueError(
            f"{missing} of {total_usable_systematic} systematic bits were not covered by "
            f"the {e.size} coded bits; E is too small for this D"
        )
    return _sub_block_deinterleave(interleaved, d)


def _usable_buffer_size(d: int) -> int:
    """Non-null length of the full circular buffer for a block of ``d`` bits."""
    n_cols = 32
    n_rows = int(np.ceil(d / n_cols))
    n_dummy = n_rows * n_cols - d
    return 3 * (n_rows * n_cols) - 3 * n_dummy


def _sub_block_deinterleave(interleaved: np.ndarray, d: int) -> np.ndarray:
    """Inverse of :func:`sub_block_interleave` for one stream."""
    n_cols = 32
    n_rows = int(np.ceil(d / n_cols))
    n_dummy = n_rows * n_cols - d
    order = np.arange(n_rows * n_cols, dtype=np.int64)
    matrix = order.reshape(n_rows, n_cols)[:, list(RM_PERM)]
    positions = matrix.reshape(-1, order="F")  # buffer position -> padded index
    padded_is_dummy = np.zeros(n_rows * n_cols, dtype=bool)
    padded_is_dummy[:n_dummy] = True
    keep = ~padded_is_dummy[positions]
    padded = np.zeros(n_rows * n_cols, dtype=np.uint8)
    padded[positions[keep]] = np.asarray(interleaved, dtype=np.uint8)[: int(keep.sum())]
    return padded[n_dummy:].astype(np.uint8)


def bytes_to_bits(data: bytes | np.ndarray) -> np.ndarray:
    """Bytes to a most-significant-bit-first bit vector."""
    arr = np.frombuffer(bytes(data), dtype=np.uint8)
    return np.unpackbits(arr).astype(np.uint8)


def bits_to_bytes(bits: np.ndarray) -> bytes:
    """Most-significant-bit-first bit vector back to bytes."""
    b = np.asarray(bits, dtype=np.uint8).ravel()
    if b.size % 8:
        raise ValueError(f"bit count {b.size} is not a multiple of 8")
    return np.packbits(b).tobytes()


def crc24a(data: bytes) -> int:
    """CRC-24A of 36.212 section 5.1.1: polynomial 0x864CFB, zero seed."""
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= CRC24A_POLY
    return crc & 0xFFFFFF


def crc16_dji(data: bytes, init: int = CRC16_INIT) -> int:
    """DJI's reflected CRC-16 (polynomial 0x1021 reflected, seed 0x3692).

    The seed is DJI's, from their published Guidance SDK; the algorithm is the
    ordinary reflected CRC-16 with no final XOR.
    """
    reflected_poly = 0
    poly = CRC16_POLY
    for i in range(16):  # reflect the polynomial once
        if poly & (1 << i):
            reflected_poly |= 1 << (15 - i)
    crc = int(init) & 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ reflected_poly if crc & 1 else crc >> 1
    return crc & 0xFFFF


def check_payload_crc(payload: bytes) -> bool:
    """True when the 176-byte payload's trailing CRC-24A checks out."""
    if len(payload) != PAYLOAD_BYTES:
        raise ValueError(f"payload must be {PAYLOAD_BYTES} bytes, got {len(payload)}")
    return crc24a(payload) == 0


def turbo_decode(_llrs: np.ndarray) -> np.ndarray:  # pragma: no cover - not implemented
    """Placeholder for an LTE turbo decoder.

    Not implemented.  The systematic-only path in
    :func:`rate_unmatch_systematic` decodes clean captures without it; adding
    a max-log-MAP decoder is the next step for weak signals and would buy
    about 3 dB.  Raising here rather than silently degrading keeps the
    toolkit's capability claims honest.
    """
    raise NotImplementedError(
        "no turbo decoder yet: DroneID is decoded from the systematic bits only, "
        "which costs about 3 dB of sensitivity. See antsdr/research/landscape.md."
    )
