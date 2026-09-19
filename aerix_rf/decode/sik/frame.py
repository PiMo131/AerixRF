"""SiK hardware-frame deframer: sync-relative header/CRC/Golay parsing,
NETID extraction, ``tdm_trailer`` strip. Bit-exact port of the framing logic
in SiK firmware ``Firmware/radio/radio_443x.c`` (ECC=0 and ECC=1 TX/RX paths)
and ``Firmware/radio/tdm.c`` (``struct tdm_trailer``), both read this pass
from ``research/library/.../SiK_3DR_Holybro/source/ArduPilot_SiK_master.zip``.

**Evidence level 1 (synthetic).** Validated only against the encoder in this
same module (``sik_encode_frame``, TX-side only -- AERIX never transmits)
and against random-bitstream false-accept testing. This does NOT demonstrate
decoding a real SiK radio; real-radio validation is pending a field
recording (design doc S4). MAVLink parsing of the recovered payload is a
separate module (T3), not implemented here.

Framing summary (design doc S1, ``docs/design/sik-mavlink-passive-decode.md``):

* **ECC=0** (hardware packet handler, no Golay): 2-byte NETID header
  (on-air order ``[netid_hi, netid_lo]``, per
  ``TRANSMIT_HEADER_3=netid>>8, TRANSMIT_HEADER_2=netid&0xFF`` in
  ``radio_set_network_id()``) + 1 length byte + ``length`` payload bytes +
  2-byte hardware CRC-16. CRC variant: **CRC-16/ARC** ("IBM", poly 0x8005,
  init 0x0000, refin=refout=true, xorout=0x0000; check("123456789")=0xBB3D),
  per AN440 register 0x30 POR default reasserted by SiK
  (``research/briefs/rc-link-raster-facts.md`` Q1, High confidence on the
  polynomial *name*). Two details are **INFERRED, not read out of a
  datasheet register-coverage table this pass**, and are flagged here as
  the single points of failure for real-signal ECC=0 CRC validation: (a)
  the CRC is computed over ``netid(2) || length(1) || payload`` -- i.e. the
  Si4432's optional header-in-CRC coverage is assumed *on* -- and (b) the
  on-air byte order of the 2-byte CRC is MSB-first (``[crc_hi, crc_lo]``).
* **ECC=1** (Golay, ``golay.py``): no hardware header/CRC. On-air =
  ``golay_encode([netid_lo, netid_hi, length])`` (6B header block) ``||``
  ``golay_encode([crc_lo, crc_hi, length])`` (6B CRC block, ``crc16`` = SiK's
  *own* software CRC-16, ``crc.c``, computed over the unencoded, unpadded
  ``length``-byte payload) ``||`` ``golay_encode(payload padded to a
  multiple of 3 with zero bytes)``. Total on-air length
  ``elen = (rlen + 6) * 2`` where ``rlen = ceil(length/3)*3``. Byte order of
  the header/CRC 3-byte pre-Golay blocks (``[netid_lo, netid_hi, length]``
  and ``[crc_lo, crc_hi, length]``) is copied directly from
  ``radio_transmit_golay()`` / the mirrored RX path in ``radio_443x.c``
  (PRIMARY, not inferred).
* Both modes: the final 2 bytes of the ``length``-byte payload are a
  ``tdm_trailer`` (``tdm.c``: ``uint16_t window:13, command:1, bonus:1,
  resend:1``), which this module strips and decodes separately. **INFERRED**
  bit/byte order: SiK is built with SDCC for the 8051 target
  (``Firmware/include/rules.mk``: ``CC = sdcc -mmcs51``); SDCC's mcs51 port
  packs bitfields LSB-first from bit 0 of the underlying storage unit and
  stores multi-byte integers little-endian (unlike Keil C51's big-endian
  convention) -- so ``trailer`` is treated as a little-endian ``uint16_t``
  with ``window`` in bits 0-12. This has not been confirmed against a SiK
  binary's disassembly; it only needs to be self-consistent for the
  synthetic round trip tested here.
* Deliberate deviation from the firmware: ``radio_443x.c``'s RX path additionally
  rejects a Golay frame whose decoded NETID doesn't match *this radio's own*
  configured NETID (``radio_set_network_id``). A passive receiver has no
  "own" NETID to filter on -- it needs to *recover* NETID, not filter by it
  (design doc S2: "Do not brute-force NETID ... it is in the header in
  clear"). ``parse_hw_frame``/``deframe`` therefore do not implement that
  gate; they report whatever NETID and CRC-validity the frame carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple, Union

from .golay import golay_decode, golay_encode

MAX_PACKET_LENGTH = 252  # firmware Firmware/radio/radio.h MAX_PACKET_LENGTH


# ---------------------------------------------------------------------------
# CRCs
# ---------------------------------------------------------------------------

def crc16_hw_arc(data: bytes) -> int:
    """CRC-16/ARC ("IBM"): poly 0x8005, init 0x0000, refin=refout=True,
    xorout=0x0000. This is the Si4432 hardware ``ENCRC|CRC_16`` engine used
    by SiK's ECC=0 (non-Golay) framing (see module docstring for coverage
    caveats). ``crc16_hw_arc(b"123456789") == 0xBB3D`` (standard check
    vector for this CRC variant).
    """
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


# SiK's own software CRC-16 tables (Firmware/radio/crc.c), extracted
# programmatically (not retyped) from the firmware source.
_CRC_TAB1 = (
    0x00, 0x00, 0x10, 0x21, 0x20, 0x42, 0x30, 0x63, 0x40, 0x84, 0x50, 0xA5, 0x60, 0xC6, 0x70, 0xE7,
    0x81, 0x08, 0x91, 0x29, 0xA1, 0x4A, 0xB1, 0x6B, 0xC1, 0x8C, 0xD1, 0xAD, 0xE1, 0xCE, 0xF1, 0xEF,
    0x12, 0x31, 0x02, 0x10, 0x32, 0x73, 0x22, 0x52, 0x52, 0xB5, 0x42, 0x94, 0x72, 0xF7, 0x62, 0xD6,
    0x93, 0x39, 0x83, 0x18, 0xB3, 0x7B, 0xA3, 0x5A, 0xD3, 0xBD, 0xC3, 0x9C, 0xF3, 0xFF, 0xE3, 0xDE,
    0x24, 0x62, 0x34, 0x43, 0x04, 0x20, 0x14, 0x01, 0x64, 0xE6, 0x74, 0xC7, 0x44, 0xA4, 0x54, 0x85,
    0xA5, 0x6A, 0xB5, 0x4B, 0x85, 0x28, 0x95, 0x09, 0xE5, 0xEE, 0xF5, 0xCF, 0xC5, 0xAC, 0xD5, 0x8D,
    0x36, 0x53, 0x26, 0x72, 0x16, 0x11, 0x06, 0x30, 0x76, 0xD7, 0x66, 0xF6, 0x56, 0x95, 0x46, 0xB4,
    0xB7, 0x5B, 0xA7, 0x7A, 0x97, 0x19, 0x87, 0x38, 0xF7, 0xDF, 0xE7, 0xFE, 0xD7, 0x9D, 0xC7, 0xBC,
    0x48, 0xC4, 0x58, 0xE5, 0x68, 0x86, 0x78, 0xA7, 0x08, 0x40, 0x18, 0x61, 0x28, 0x02, 0x38, 0x23,
    0xC9, 0xCC, 0xD9, 0xED, 0xE9, 0x8E, 0xF9, 0xAF, 0x89, 0x48, 0x99, 0x69, 0xA9, 0x0A, 0xB9, 0x2B,
    0x5A, 0xF5, 0x4A, 0xD4, 0x7A, 0xB7, 0x6A, 0x96, 0x1A, 0x71, 0x0A, 0x50, 0x3A, 0x33, 0x2A, 0x12,
    0xDB, 0xFD, 0xCB, 0xDC, 0xFB, 0xBF, 0xEB, 0x9E, 0x9B, 0x79, 0x8B, 0x58, 0xBB, 0x3B, 0xAB, 0x1A,
    0x6C, 0xA6, 0x7C, 0x87, 0x4C, 0xE4, 0x5C, 0xC5, 0x2C, 0x22, 0x3C, 0x03, 0x0C, 0x60, 0x1C, 0x41,
    0xED, 0xAE, 0xFD, 0x8F, 0xCD, 0xEC, 0xDD, 0xCD, 0xAD, 0x2A, 0xBD, 0x0B, 0x8D, 0x68, 0x9D, 0x49,
    0x7E, 0x97, 0x6E, 0xB6, 0x5E, 0xD5, 0x4E, 0xF4, 0x3E, 0x13, 0x2E, 0x32, 0x1E, 0x51, 0x0E, 0x70,
    0xFF, 0x9F, 0xEF, 0xBE, 0xDF, 0xDD, 0xCF, 0xFC, 0xBF, 0x1B, 0xAF, 0x3A, 0x9F, 0x59, 0x8F, 0x78,
)

_CRC_TAB2 = (
    0x91, 0x88, 0x81, 0xA9, 0xB1, 0xCA, 0xA1, 0xEB, 0xD1, 0x0C, 0xC1, 0x2D, 0xF1, 0x4E, 0xE1, 0x6F,
    0x10, 0x80, 0x00, 0xA1, 0x30, 0xC2, 0x20, 0xE3, 0x50, 0x04, 0x40, 0x25, 0x70, 0x46, 0x60, 0x67,
    0x83, 0xB9, 0x93, 0x98, 0xA3, 0xFB, 0xB3, 0xDA, 0xC3, 0x3D, 0xD3, 0x1C, 0xE3, 0x7F, 0xF3, 0x5E,
    0x02, 0xB1, 0x12, 0x90, 0x22, 0xF3, 0x32, 0xD2, 0x42, 0x35, 0x52, 0x14, 0x62, 0x77, 0x72, 0x56,
    0xB5, 0xEA, 0xA5, 0xCB, 0x95, 0xA8, 0x85, 0x89, 0xF5, 0x6E, 0xE5, 0x4F, 0xD5, 0x2C, 0xC5, 0x0D,
    0x34, 0xE2, 0x24, 0xC3, 0x14, 0xA0, 0x04, 0x81, 0x74, 0x66, 0x64, 0x47, 0x54, 0x24, 0x44, 0x05,
    0xA7, 0xDB, 0xB7, 0xFA, 0x87, 0x99, 0x97, 0xB8, 0xE7, 0x5F, 0xF7, 0x7E, 0xC7, 0x1D, 0xD7, 0x3C,
    0x26, 0xD3, 0x36, 0xF2, 0x06, 0x91, 0x16, 0xB0, 0x66, 0x57, 0x76, 0x76, 0x46, 0x15, 0x56, 0x34,
    0xD9, 0x4C, 0xC9, 0x6D, 0xF9, 0x0E, 0xE9, 0x2F, 0x99, 0xC8, 0x89, 0xE9, 0xB9, 0x8A, 0xA9, 0xAB,
    0x58, 0x44, 0x48, 0x65, 0x78, 0x06, 0x68, 0x27, 0x18, 0xC0, 0x08, 0xE1, 0x38, 0x82, 0x28, 0xA3,
    0xCB, 0x7D, 0xDB, 0x5C, 0xEB, 0x3F, 0xFB, 0x1E, 0x8B, 0xF9, 0x9B, 0xD8, 0xAB, 0xBB, 0xBB, 0x9A,
    0x4A, 0x75, 0x5A, 0x54, 0x6A, 0x37, 0x7A, 0x16, 0x0A, 0xF1, 0x1A, 0xD0, 0x2A, 0xB3, 0x3A, 0x92,
    0xFD, 0x2E, 0xED, 0x0F, 0xDD, 0x6C, 0xCD, 0x4D, 0xBD, 0xAA, 0xAD, 0x8B, 0x9D, 0xE8, 0x8D, 0xC9,
    0x7C, 0x26, 0x6C, 0x07, 0x5C, 0x64, 0x4C, 0x45, 0x3C, 0xA2, 0x2C, 0x83, 0x1C, 0xE0, 0x0C, 0xC1,
    0xEF, 0x1F, 0xFF, 0x3E, 0xCF, 0x5D, 0xDF, 0x7C, 0xAF, 0x9B, 0xBF, 0xBA, 0x8F, 0xD9, 0x9F, 0xF8,
    0x6E, 0x17, 0x7E, 0x36, 0x4E, 0x55, 0x5E, 0x74, 0x2E, 0x93, 0x3E, 0xB2, 0x0E, 0xD1, 0x1E, 0xF0,
)


def sik_crc16(data: bytes) -> int:
    """SiK's own software CRC-16 (``Firmware/radio/crc.c``), used to protect
    the payload in the Golay/ECC=1 framing path. Bit-exact port of ``crc16()``
    (table-driven, byte-at-a-time, ``high``/``low`` accumulator, initial
    state 0/0). This is *not* CRC-16/ARC and not any named standard CRC --
    it is SiK's bespoke table pair, extracted programmatically from
    ``crc.c`` (not retyped).
    """
    high = 0
    low = 0
    for b in data:
        k = (high << 1) & 0xFF
        tab = _CRC_TAB2 if (high & 0x80) else _CRC_TAB1
        new_high = low ^ tab[k]
        new_low = b ^ tab[k + 1]
        high, low = new_high & 0xFF, new_low & 0xFF
    return (high << 8) | low


# ---------------------------------------------------------------------------
# tdm_trailer (Firmware/radio/tdm.c)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TdmTrailer:
    """``struct tdm_trailer { uint16_t window:13, command:1, bonus:1, resend:1; }``
    (``tdm.c``). See module docstring for the INFERRED little-endian /
    LSB-first-bitfield packing assumption (SDCC mcs51 target).
    """

    window: int
    command: bool
    bonus: bool
    resend: bool

    @classmethod
    def decode(cls, raw: bytes) -> "TdmTrailer":
        if len(raw) != 2:
            raise ValueError("tdm_trailer is exactly 2 bytes")
        v = raw[0] | (raw[1] << 8)
        return cls(
            window=v & 0x1FFF,
            command=bool((v >> 13) & 1),
            bonus=bool((v >> 14) & 1),
            resend=bool((v >> 15) & 1),
        )

    def encode(self) -> bytes:
        if not (0 <= self.window <= 0x1FFF):
            raise ValueError("tdm_trailer.window must fit in 13 bits")
        v = (
            (self.window & 0x1FFF)
            | (int(bool(self.command)) << 13)
            | (int(bool(self.bonus)) << 14)
            | (int(bool(self.resend)) << 15)
        )
        return bytes((v & 0xFF, (v >> 8) & 0xFF))


_DEFAULT_TRAILER = TdmTrailer(window=1, command=False, bonus=False, resend=False)


# ---------------------------------------------------------------------------
# SikFrame
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SikFrame:
    """A deframed SiK hardware packet.

    ``length`` is the on-air length field as the firmware defines it (the
    payload byte count *including* the trailing 2-byte ``tdm_trailer``).
    ``payload`` is the ``tdm_trailer``-stripped user payload (the bytes
    ``packet_get_next``/the serial stream would see), i.e.
    ``len(payload) == length - 2`` whenever ``length >= 2``.
    Evidence level 1 (synthetic) -- see module docstring.
    """

    netid: int
    length: int
    payload: bytes
    crc_ok: bool
    ecc: bool
    trailer: Optional[TdmTrailer]
    bit_errors_corrected: int


def _split_trailer(payload_full: bytes) -> Tuple[bytes, Optional[TdmTrailer]]:
    if len(payload_full) < 2:
        return payload_full, None
    trailer = TdmTrailer.decode(payload_full[-2:])
    return payload_full[:-2], trailer


# ---------------------------------------------------------------------------
# Bit/byte normalisation
# ---------------------------------------------------------------------------

BitsOrBytes = Union[bytes, bytearray, Sequence[int]]


def _bits_to_bytes(bits: Sequence[int]) -> bytes:
    n = len(bits) - (len(bits) % 8)
    out = bytearray(n // 8)
    for i in range(0, n, 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | (int(bits[i + j]) & 1)
        out[i // 8] = byte
    return bytes(out)


def _to_bytes(data: BitsOrBytes) -> bytes:
    """Accept either a byte string/array, or a sequence of individual bits
    (0/1 ints, MSB-first per byte), and normalise to bytes. A sequence is
    treated as bits only if *every* element is 0 or 1; otherwise it is
    treated as a sequence of byte values.
    """
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    values = [int(v) for v in data]
    if values and all(v in (0, 1) for v in values):
        return _bits_to_bytes(values)
    return bytes(v & 0xFF for v in values)


# ---------------------------------------------------------------------------
# Encode (TX side, for round-trip tests only -- AERIX never transmits)
# ---------------------------------------------------------------------------

def sik_encode_frame(
    netid: int,
    payload: bytes,
    ecc: bool,
    trailer: Optional[TdmTrailer] = None,
) -> bytes:
    """Build the on-air hardware-frame bytes (post preamble/sync) for a SiK
    packet, bit-exact with ``radio_443x.c``'s ECC=0 hardware-CRC path and
    ``radio_transmit_golay()``'s ECC=1 path. ``payload`` is the user payload
    (trailer excluded); a ``tdm_trailer`` is appended per ``tdm.c`` before
    framing. Encoder-only: used by this module's own tests to validate the
    decoder against a firmware-faithful bit layout. AERIX does not transmit.
    """
    if trailer is None:
        trailer = _DEFAULT_TRAILER
    full = bytes(payload) + trailer.encode()
    length = len(full)
    if length > MAX_PACKET_LENGTH:
        raise ValueError(f"on-air length {length} exceeds MAX_PACKET_LENGTH")
    if not (0 <= netid <= 0xFFFF):
        raise ValueError("netid must fit in 16 bits")

    if not ecc:
        header = bytes(((netid >> 8) & 0xFF, netid & 0xFF, length))
        crc = crc16_hw_arc(header + full)
        return header + full + bytes(((crc >> 8) & 0xFF, crc & 0xFF))

    rlen = ((length + 2) // 3) * 3
    padded = full + bytes(rlen - length)
    hdr_block = golay_encode(bytes((netid & 0xFF, (netid >> 8) & 0xFF, length)))
    crc = sik_crc16(full)
    crc_block = golay_encode(bytes((crc & 0xFF, (crc >> 8) & 0xFF, length)))
    payload_block = golay_encode(padded) if rlen else b""
    return hdr_block + crc_block + payload_block


# ---------------------------------------------------------------------------
# Decode (RX side)
# ---------------------------------------------------------------------------

def _parse_ecc0(data: bytes) -> Optional[SikFrame]:
    if len(data) < 3 + 2:
        return None
    netid = (data[0] << 8) | data[1]
    length = data[2]
    if len(data) < 3 + length + 2:
        return None
    payload_full = data[3 : 3 + length]
    crc_bytes = data[3 + length : 3 + length + 2]
    computed = crc16_hw_arc(data[0 : 3 + length])
    received = (crc_bytes[0] << 8) | crc_bytes[1]
    crc_ok = computed == received
    payload, trailer = _split_trailer(payload_full)
    return SikFrame(
        netid=netid,
        length=length,
        payload=payload,
        crc_ok=crc_ok,
        ecc=False,
        trailer=trailer,
        bit_errors_corrected=0,
    )


def _parse_ecc1(data: bytes) -> Optional[SikFrame]:
    if len(data) < 12:
        return None
    hdr, err_h = golay_decode(data[0:6])
    netid = hdr[0] | (hdr[1] << 8)
    hdr_length = hdr[2]
    rlen = ((hdr_length + 2) // 3) * 3
    expected_elen = 2 * rlen + 12
    if len(data) < expected_elen:
        return None

    crc_hdr, err_c = golay_decode(data[6:12])
    crc1 = crc_hdr[0] | (crc_hdr[1] << 8)
    length = crc_hdr[2]

    bit_errors = err_h + err_c
    if rlen == 0:
        payload_padded = b""
    else:
        payload_padded, err_p = golay_decode(data[12:expected_elen])
        bit_errors += err_p
    payload_full = payload_padded[:length]

    crc2 = sik_crc16(payload_full)
    crc_ok = (crc1 == crc2) and (length <= rlen) and (hdr_length == length)
    payload, trailer = _split_trailer(payload_full)
    return SikFrame(
        netid=netid,
        length=length,
        payload=payload,
        crc_ok=crc_ok,
        ecc=True,
        trailer=trailer,
        bit_errors_corrected=bit_errors,
    )


def parse_hw_frame(bits_or_bytes: BitsOrBytes, ecc: bool) -> Optional[SikFrame]:
    """Parse a hardware frame (the bytes immediately following preamble+sync)
    under a single ECC hypothesis. Returns ``None`` if the buffer is too
    short to be structurally valid for that hypothesis; otherwise returns a
    :class:`SikFrame` whose ``crc_ok`` reports whether the CRC matched
    (Golay-corrected data is still returned even when the CRC fails, so a
    caller can distinguish "wrong ECC hypothesis" from "correct hypothesis,
    corrupted frame"). Trailing bytes beyond the frame's own length field are
    ignored (tolerant of a longer buffer, e.g. from :func:`deframe`).
    """
    data = _to_bytes(bits_or_bytes)
    if ecc:
        return _parse_ecc1(data)
    return _parse_ecc0(data)


def deframe(
    bitstream: BitsOrBytes,
    sync_offset: int,
    ecc_hypotheses: Iterable[bool] = (False, True),
) -> Optional[SikFrame]:
    """Given a bitstream and the bit offset immediately after a located sync
    word, try each ECC hypothesis in turn and return the first frame whose
    CRC validates, else ``None``.

    ``bitstream`` may be raw bits (0/1 ints, MSB-first) or bytes; if bytes,
    ``sync_offset`` is interpreted as a *bit* offset into the byte sequence
    (``sync_offset // 8`` must be an integer number of bytes -- non-byte-
    aligned offsets into a bytes buffer are not supported, only into a bit
    sequence).
    """
    if isinstance(bitstream, (bytes, bytearray)):
        if sync_offset % 8 != 0:
            raise ValueError(
                "byte-aligned sync_offset required when bitstream is bytes; "
                "pass individual bits for sub-byte offsets"
            )
        data = bytes(bitstream)[sync_offset // 8 :]
    else:
        bits = list(bitstream)[sync_offset:]
        data = _bits_to_bytes(bits)

    for ecc in ecc_hypotheses:
        frame = parse_hw_frame(data, ecc)
        if frame is not None and frame.crc_ok:
            return frame
    return None
