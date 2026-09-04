"""LTE Turbo coding for DJI DroneID (3GPP TS 36.212), ported for AERIX.

This module implements the DroneID stage-3 back end: undo the LTE rate matching on
the 7200 descrambled bits, run an iterative SISO (max-log-MAP / BCJR) turbo decoder,
and validate the 24-bit CRC. An encoder path (turbo encode + rate match + the two
CRCs) is provided so the whole chain can be round-tripped against a known frame.

Everything here is bit-exact with the reference transmit/receive path used by
proto17/dji_droneid, which shells out to ttsou/turbofec:

  * Info block K = 1408 bits (176 bytes) -> per-stream length D = K + 4 = 1412.
  * Constituent RSC encoder: feedback g0 = 13 (octal), feedforward g1 = 15 (octal),
    i.e. turbofec's ``rgen = 0o13 = 11``, ``gen = 0o15 = 13`` (decimal), memory 3,
    8 states. Verbatim from ``turbofec/src/turbo_enc.c``.
  * QPP internal interleaver for K = 1408: f1 = 43, f2 = 88
    (TS 36.212 Table 5.1.3-3, turbofec row i = 104).
  * Rate matching (TS 36.212 5.1.4.1): 32-column sub-block interleavers, bit
    collection into a circular buffer, and RV=0 bit selection to E = 7200.
  * Frame CRC: CRC24A (CRC_24_LTEA, poly 0x864CFB) over all 176 bytes -> 0 on OK.

References (section numbers cited inline):
  3GPP TS 36.212 5.1.3.2 (turbo encoding), 5.1.3.2.3 (QPP), 5.1.4.1 (rate matching).
  https://github.com/proto17/dji_droneid  (cpp/add_turbo.cc, cpp/remove_turbo.cc)
  https://github.com/ttsou/turbofec        (src/turbo_enc.c, src/turbo_rate_match.c)
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Code parameters (DroneID normal frame; TS 36.212)
# ---------------------------------------------------------------------------
K_INFO = 1408                 # turbo info block length (bits) == 176 bytes
N_TAIL = 4                    # termination adds 4 entries per output stream
D_STREAM = K_INFO + N_TAIL    # 1412: per-stream length after termination
E_RATE = 7200                 # rate-matched output length (descrambled bits)

# RSC generator polynomials, turbofec convention (decimal of octal 13 / 15).
_RGEN = 0o13                  # 11: feedback  g0 = 1 + D^2 + D^3
_GEN = 0o15                   # 13: forward   g1 = 1 + D + D^3
_K_CONSTRAINT = 4             # turbofec code.k (memory 3 -> 8 states)
_N_STATES = 8

# QPP interleaver parameters for K = 1408 (TS 36.212 Table 5.1.3-3).
_QPP_F1 = 43
_QPP_F2 = 88

# Sub-block interleaver: 32 columns, inter-column permutation (TS 36.212 5.1.4.1.1).
_SUBBLOCK_COLS = 32
_COL_PERM = np.array([
    0, 16, 8, 24, 4, 20, 12, 28, 2, 18, 10, 26, 6, 22, 14, 30,
    1, 17, 9, 25, 5, 21, 13, 29, 3, 19, 11, 27, 7, 23, 15, 31,
], dtype=np.int64)

_LLR_MAG = 8.0                # magnitude for hard-bit -> LLR (max-log is scale-free)


def _parity(x: int) -> int:
    """Parity (XOR of bits) of a small non-negative integer."""
    return bin(x & 0xFFFF).count("1") & 1


# ---------------------------------------------------------------------------
# QPP interleaver (TS 36.212 5.1.3.2.3)
# ---------------------------------------------------------------------------

def qpp_interleaver(k: int = K_INFO) -> np.ndarray:
    """Return the QPP permutation ``pi`` of length ``k``.

    Interleaved bit i is taken from position ``pi[i] = (f1*i + f2*i^2) mod K``.
    Matches turbofec ``gen_deinterlv_map`` (which computes the same value).
    """
    i = np.arange(k, dtype=np.int64)
    pi = (_QPP_F1 * i + _QPP_F2 * i * i) % k
    return pi


# Cached permutation and its inverse (bijection sanity-checked at import).
_PI = qpp_interleaver(K_INFO)
assert np.array_equal(np.sort(_PI), np.arange(K_INFO)), "QPP is not a bijection"
_PI_INV = np.empty(K_INFO, dtype=np.int64)
_PI_INV[_PI] = np.arange(K_INFO)


def interleave(bits: np.ndarray) -> np.ndarray:
    return bits[_PI]


def deinterleave(bits: np.ndarray) -> np.ndarray:
    return bits[_PI_INV]


# ---------------------------------------------------------------------------
# Trellis for the constituent RSC encoder (derived from turbofec encode_n2)
# ---------------------------------------------------------------------------

def _build_trellis():
    """Precompute next-state / parity / feedback tables for the 8-state RSC.

    Replicates ``encode_n2`` bit-for-bit: state ``reg`` holds bits 0..2 (bit 3 is
    cleared by the trailing ``reg >>= 1``). For input bit c:
        fb  = parity(reg & rgen)
        reg2 = reg | ((fb ^ c) << 3)
        z   = parity(reg2 & gen)
        reg_next = reg2 >> 1
    """
    nxt = np.zeros((_N_STATES, 2), dtype=np.int64)
    par = np.zeros((_N_STATES, 2), dtype=np.int64)
    fb_tbl = np.zeros(_N_STATES, dtype=np.int64)
    for reg in range(_N_STATES):
        fb_tbl[reg] = _parity(reg & _RGEN)
        for c in (0, 1):
            fb = _parity(reg & _RGEN)
            reg2 = reg | ((fb ^ c) << (_K_CONSTRAINT - 1))
            nxt[reg, c] = reg2 >> 1
            par[reg, c] = _parity(reg2 & _GEN)
    return nxt, par, fb_tbl


_NEXT, _PAR, _FB = _build_trellis()

# Branch table for vectorized BCJR: 16 branches (state x input).
_BR_FROM = np.repeat(np.arange(_N_STATES), 2)          # from-state per branch
_BR_IN = np.tile(np.array([0, 1]), _N_STATES)          # input bit per branch
_BR_TO = _NEXT[_BR_FROM, _BR_IN]                        # to-state per branch
_BR_PAR = _PAR[_BR_FROM, _BR_IN]                        # parity out per branch
# Antipodal symbols (bit 0 -> +1, bit 1 -> -1) for systematic and parity.
_BR_SYS_SYM = 1.0 - 2.0 * _BR_IN
_BR_PAR_SYM = 1.0 - 2.0 * _BR_PAR


# ---------------------------------------------------------------------------
# Turbo encoder (TS 36.212 5.1.3.2, turbofec turbo_enc.c)
# ---------------------------------------------------------------------------

def _encode_rsc(info: np.ndarray):
    """Run one constituent encoder. Returns (systematic, parity, final_reg)."""
    reg = 0
    x = np.empty(info.size, dtype=np.int8)
    z = np.empty(info.size, dtype=np.int8)
    for i in range(info.size):
        fb = _parity(reg & _RGEN)
        reg |= (fb ^ int(info[i])) << (_K_CONSTRAINT - 1)
        x[i] = info[i]
        z[i] = _parity(reg & _GEN)
        reg >>= 1
    return x, z, reg


def turbo_encode(info: np.ndarray):
    """LTE turbo encode ``info`` (K bits). Returns (d0, d1, d2), each K+4 bits.

    d0 = systematic, d1 = parity 1, d2 = parity 2, with the 12 termination bits
    distributed per TS 36.212 5.1.3.2.2 exactly as turbofec ``turbo_term`` does.
    """
    info = np.asarray(info, dtype=np.int8)
    k = info.size
    d0 = np.zeros(k + N_TAIL, dtype=np.int8)
    d1 = np.zeros(k + N_TAIL, dtype=np.int8)
    d2 = np.zeros(k + N_TAIL, dtype=np.int8)

    x, z1, reg0 = _encode_rsc(info)
    d0[:k] = x
    d1[:k] = z1
    _, z2, reg1 = _encode_rsc(info[_PI])   # second encoder on interleaved bits
    d2[:k] = z2

    # Trellis termination (turbo_term): shift each register to zero, feeding back.
    def term(reg):
        out = []
        for _ in range(3):
            xt = _parity(reg & _RGEN)       # forced input == feedback -> drives to 0
            zt = _parity(reg & _GEN)
            out.append((xt, zt))
            reg >>= 1
        return out

    (xa, za), (xb, zb), (xc, zc) = term(reg0)
    (xa2, za2), (xb2, zb2), (xc2, zc2) = term(reg1)
    # d0: x_K, z_{K+1}, x'_K, z'_{K+1}
    d0[k + 0], d0[k + 1], d0[k + 2], d0[k + 3] = xa, zb, xa2, zb2
    # d1: z_K, x_{K+2}, z'_K, x'_{K+2}
    d1[k + 0], d1[k + 1], d1[k + 2], d1[k + 3] = za, xc, za2, xc2
    # d2: x_{K+1}, z_{K+2}, x'_{K+1}, z'_{K+2}
    d2[k + 0], d2[k + 1], d2[k + 2], d2[k + 3] = xb, zc, xb2, zc2
    return d0, d1, d2


# ---------------------------------------------------------------------------
# Rate matching (TS 36.212 5.1.4.1)
# ---------------------------------------------------------------------------

def _subblock_maps(d_len: int = D_STREAM):
    """Precompute the sub-block read maps and NULL masks (TS 36.212 5.1.4.1.1).

    Returns (R, k_pi, read0, read2, null0, null2) where read0 applies to streams 0
    and 1, read2 to stream 2. ``read[k]`` is the index into the row-major padded
    matrix (length k_pi, first ``Nd`` entries are NULL padding) that v[k] reads.
    """
    c = _SUBBLOCK_COLS
    r = int(np.ceil(d_len / c))
    k_pi = r * c
    nd = k_pi - d_len

    k = np.arange(k_pi, dtype=np.int64)
    col = k // r                                    # 0..C-1 (output column)
    row = k % r                                     # 0..R-1
    read0 = row * c + _COL_PERM[col]                # streams 0 & 1
    read2 = (_COL_PERM[col] + c * row + 1) % k_pi   # stream 2 (the "+1" shift)

    null0 = read0 < nd                              # padded NULL positions
    null2 = read2 < nd
    return r, k_pi, read0, read2, null0, null2


_R_SUB, _K_PI, _READ0, _READ2, _NULL0, _NULL2 = _subblock_maps(D_STREAM)
_K_W = 3 * _K_PI                                    # circular-buffer length
# Sanity: stream-2 map must also be a bijection over the padded matrix.
assert np.array_equal(np.sort(_READ2), np.arange(_K_PI)), "stream-2 map not a bijection"


def _pad_stream(d: np.ndarray) -> np.ndarray:
    """Prepend Nd NULL padding to a length-D stream -> length k_pi float array."""
    nd = _K_PI - d.size
    out = np.empty(_K_PI, dtype=np.float64)
    out[:nd] = 0.0
    out[nd:] = d
    return out


def _k0_rv0() -> int:
    """Bit-selection start index for RV=0 (TS 36.212 5.1.4.1.2): k0 = 2*R."""
    return 2 * _R_SUB


def rate_match(d0: np.ndarray, d1: np.ndarray, d2: np.ndarray, e: int = E_RATE) -> np.ndarray:
    """Forward LTE rate matching (encode direction). Returns ``e`` hard bits."""
    v0 = _pad_stream(np.asarray(d0, dtype=np.float64))[_READ0]
    v1 = _pad_stream(np.asarray(d1, dtype=np.float64))[_READ0]
    v2 = _pad_stream(np.asarray(d2, dtype=np.float64))[_READ2]

    # Bit collection into the circular buffer w (5.1.4.1.2).
    w = np.empty(_K_W, dtype=np.float64)
    w[:_K_PI] = v0
    w[_K_PI::2] = v1
    w[_K_PI + 1::2] = v2

    # NULL mask in w-space (v0 nulls, then interlaced v1/v2 nulls).
    w_null = np.empty(_K_W, dtype=bool)
    w_null[:_K_PI] = _NULL0
    w_null[_K_PI::2] = _NULL0
    w_null[_K_PI + 1::2] = _NULL2

    out = np.empty(e, dtype=np.int8)
    k0 = _k0_rv0()
    j = 0
    filled = 0
    while filled < e:
        idx = (k0 + j) % _K_W
        if not w_null[idx]:
            out[filled] = int(w[idx])
            filled += 1
        j += 1
    return out


def de_rate_match(e_llr: np.ndarray, d_len: int = D_STREAM):
    """Inverse rate matching (decode direction).

    Soft-accumulates the ``E`` received LLRs back into the circular buffer (repeated
    positions add), then inverts sub-block interleaving into the three stream LLRs.
    NULL / never-received positions come back as 0 (erasure). Returns (l0, l1, l2).
    """
    e_llr = np.asarray(e_llr, dtype=np.float64)
    w = np.zeros(_K_W, dtype=np.float64)

    w_null = np.empty(_K_W, dtype=bool)
    w_null[:_K_PI] = _NULL0
    w_null[_K_PI::2] = _NULL0
    w_null[_K_PI + 1::2] = _NULL2

    # Reproduce the fw selection order and scatter-add LLRs.
    k0 = _k0_rv0()
    e = e_llr.size
    j = 0
    filled = 0
    while filled < e:
        idx = (k0 + j) % _K_W
        if not w_null[idx]:
            w[idx] += e_llr[filled]
            filled += 1
        j += 1

    v0 = w[:_K_PI]
    v1 = w[_K_PI::2]
    v2 = w[_K_PI + 1::2]

    nd = _K_PI - d_len
    p0 = np.zeros(_K_PI); p0[_READ0] = v0
    p1 = np.zeros(_K_PI); p1[_READ0] = v1
    p2 = np.zeros(_K_PI); p2[_READ2] = v2
    return p0[nd:], p1[nd:], p2[nd:]


# ---------------------------------------------------------------------------
# BCJR constituent decoder (max-log-MAP)
# ---------------------------------------------------------------------------

_NEG_INF = -1e30


def _bcjr(ls: np.ndarray, lp: np.ndarray, la: np.ndarray) -> np.ndarray:
    """Max-log-MAP SISO decode of one terminated constituent code.

    ls, lp, la are length N = K+3 LLR arrays (systematic channel, parity channel,
    a-priori; la is 0 on the 3 tail steps). Returns the a-posteriori LLR (length N),
    with LLR convention log P(bit=0)/P(bit=1) (positive -> bit 0).
    """
    n = ls.size
    # Branch metric per step: gamma[k, b] = 0.5*(sys_sym*(ls+la) + par_sym*lp).
    # Shape (n, 16).
    sysla = (ls + la)[:, None]                    # (n,1)
    gamma = 0.5 * (_BR_SYS_SYM[None, :] * sysla + _BR_PAR_SYM[None, :] * lp[:, None])

    # Forward recursion (alpha), start state 0.
    alpha = np.full((n + 1, _N_STATES), _NEG_INF)
    alpha[0, 0] = 0.0
    for k in range(n):
        a_prev = alpha[k, _BR_FROM] + gamma[k]    # (16,)
        nxt = np.full(_N_STATES, _NEG_INF)
        np.maximum.at(nxt, _BR_TO, a_prev)
        alpha[k + 1] = nxt

    # Backward recursion (beta), terminated to state 0.
    beta = np.full((n + 1, _N_STATES), _NEG_INF)
    beta[n, 0] = 0.0
    for k in range(n - 1, -1, -1):
        b_next = beta[k + 1, _BR_TO] + gamma[k]   # (16,)
        cur = np.full(_N_STATES, _NEG_INF)
        np.maximum.at(cur, _BR_FROM, b_next)
        beta[k] = cur

    # A-posteriori LLR per step: max over branches with input 0 minus input 1.
    metric = alpha[np.arange(n)[:, None], _BR_FROM[None, :]] + gamma + \
        beta[np.arange(1, n + 1)[:, None], _BR_TO[None, :]]   # (n,16)
    is0 = (_BR_IN == 0)[None, :]
    m0 = np.max(np.where(is0, metric, _NEG_INF), axis=1)
    m1 = np.max(np.where(~is0, metric, _NEG_INF), axis=1)
    return m0 - m1


def turbo_decode(l0: np.ndarray, l1: np.ndarray, l2: np.ndarray,
                 iterations: int = 8, crc_ok=None):
    """Iterative turbo decode. l0/l1/l2 are length-D LLRs (systematic, par1, par2).

    Returns (info_bits[K], iters_used, crc_passed). If ``crc_ok`` is a callable it is
    invoked on the packed 176-byte candidate after each iteration for early exit.
    """
    k = K_INFO
    n = k + 3                                       # trellis steps per decoder

    # Systematic + parity channel LLRs laid out over N steps (info + 3 tail).
    ls1 = np.zeros(n); ls1[:k] = l0[:k]
    lp1 = np.zeros(n); lp1[:k] = l1[:k]
    # Decoder-1 tail (TS 36.212 5.1.3.2.2 mapping, see turbo_encode):
    ls1[k + 0], ls1[k + 1], ls1[k + 2] = l0[k + 0], l2[k + 0], l1[k + 1]   # x_K,x_{K+1},x_{K+2}
    lp1[k + 0], lp1[k + 1], lp1[k + 2] = l1[k + 0], l0[k + 1], l2[k + 1]   # z_K,z_{K+1},z_{K+2}

    ls2_info = l0[:k][_PI]                           # interleaved systematic
    ls2 = np.zeros(n); ls2[:k] = ls2_info
    lp2 = np.zeros(n); lp2[:k] = l2[:k]
    ls2[k + 0], ls2[k + 1], ls2[k + 2] = l0[k + 2], l2[k + 2], l1[k + 3]   # x'_K,x'_{K+1},x'_{K+2}
    lp2[k + 0], lp2[k + 1], lp2[k + 2] = l1[k + 2], l0[k + 3], l2[k + 3]   # z'_K,z'_{K+1},z'_{K+2}

    la1 = np.zeros(n)                               # a-priori for decoder 1
    info = np.zeros(k, dtype=np.int8)
    passed = False
    used = 0
    for it in range(iterations):
        used = it + 1
        # Decoder 1
        app1 = _bcjr(ls1, lp1, la1)
        le1 = app1[:k] - ls1[:k] - la1[:k]          # extrinsic (info positions)
        # Decoder 2 (a-priori = interleaved extrinsic)
        la2 = np.zeros(n)
        la2[:k] = le1[_PI]
        app2 = _bcjr(ls2, lp2, la2)
        le2 = app2[:k] - ls2[:k] - la2[:k]
        la1 = np.zeros(n)
        la1[:k] = le2[_PI_INV]                       # deinterleave extrinsic

        # Hard decision from decoder-2 a-posteriori (deinterleaved).
        info = (app2[:k][_PI_INV] < 0).astype(np.int8)
        if crc_ok is not None and crc_ok(info):
            passed = True
            break
    return info, used, passed


# ---------------------------------------------------------------------------
# CRC (TS 36.212 5.1.1) and the DJI inner CRC16
# ---------------------------------------------------------------------------

_CRC24A_POLY = 0x864CFB        # CRC_24_LTEA / 3GPP CRC24A, x^24 + ... (24-bit)


def crc24a(data: bytes) -> int:
    """CRC24A (3GPP TS 36.212 5.1.1, CRCpp CRC_24_LTEA): poly 0x864CFB, init 0."""
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= _CRC24A_POLY
        crc &= 0xFFFFFF
    return crc


# DJI inner CRC16 (calculate_crc.m): reflected, poly 0x8408, init 0x3692.
def crc16_dji(data: bytes) -> int:
    crc = 0x3692
    for byte in data:
        crc = (crc >> 8) ^ _CRC16_TABLE[(crc ^ byte) & 0xFF]
    return crc & 0xFFFF


def _build_crc16_table():
    table = np.zeros(256, dtype=np.uint32)
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if (c & 1) else (c >> 1)
        table[i] = c
    return table


_CRC16_TABLE = _build_crc16_table()
# Pin against the reference table in calculate_crc.m (first few entries).
assert _CRC16_TABLE[0] == 0x0000 and _CRC16_TABLE[1] == 0x1189
assert _CRC16_TABLE[2] == 0x2312 and _CRC16_TABLE[3] == 0x329B


def bits_to_bytes(bits: np.ndarray) -> bytes:
    """Pack an MSB-first bit array (length multiple of 8) into bytes."""
    bits = np.asarray(bits, dtype=np.uint8)
    return np.packbits(bits).tobytes()


def bytes_to_bits(data: bytes) -> np.ndarray:
    """Unpack bytes into an MSB-first bit array."""
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_llr(bits: np.ndarray, mag: float = _LLR_MAG) -> np.ndarray:
    """Hard bits -> LLRs (log P(0)/P(1)); bit 0 -> +mag, bit 1 -> -mag."""
    bits = np.asarray(bits)
    return (1.0 - 2.0 * bits) * mag


def decode_frame_bits(descrambled_bits: np.ndarray, iterations: int = 8):
    """Full back end: 7200 descrambled hard bits -> (176-byte frame, meta) or None.

    Returns (frame_bytes, {'iterations': n, 'crc': True}) on CRC success, else None.
    """
    e_llr = bits_to_llr(np.asarray(descrambled_bits))
    l0, l1, l2 = de_rate_match(e_llr)

    def _crc_ok(info_bits):
        frame = bits_to_bytes(info_bits)
        return crc24a(frame) == 0

    info, used, passed = turbo_decode(l0, l1, l2, iterations=iterations, crc_ok=_crc_ok)
    if not passed:
        return None
    frame = bits_to_bytes(info)
    return frame, {"iterations": used, "crc": True}
