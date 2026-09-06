"""The LTE turbo code, which is the error correction DroneID actually uses.

Without this the decoder reads the systematic bits straight off the QPSK
constellation and hopes they are all correct. Measured on this toolkit's own
synthetic burst before the code existed, that put the cliff at 18 dB in-band
signal-to-noise: bursts were detected reliably down to 10 dB and below, and
the CRC passed at 18 and above with nothing in between. A drone at any useful
distance sits in that gap.

What is here
------------
* :func:`qpp_interleaver` - the quadratic permutation polynomial interleaver,
  ``pi(i) = (f1 i + f2 i^2) mod K``, with the full 3GPP parameter table.
* :func:`turbo_encode` - the parallel concatenated encoder: two identical
  eight-state recursive systematic convolutional coders, the second fed the
  interleaved bits, each terminated with three tail steps.
* :func:`turbo_decode` - iterative max-log-MAP decoding. The two constituent
  decoders take turns, each passing the other what it learned that the other
  did not already know.

Where the numbers come from
---------------------------
The trellis and the tail arrangement were read out of srsRAN's encoder
(``srsran/srsRAN_4G``, ``lib/src/phy/fec/turbo/turbocoder.c``) rather than
reconstructed from a description, because the register update order and the
tail ordering are exactly what a from-memory implementation gets subtly wrong::

    in  = bit ^ (reg_2 ^ reg_1)
    out = reg_2 ^ (reg_0 ^ in)
    reg_2 = reg_1;  reg_1 = reg_0;  reg_0 = in

The interleaver table was extracted from the same project's
``tc_interl_lte.c`` and ``cbsegm.c`` and checked two ways: every row produces
a genuine permutation, and the first and last rows match the 3GPP values that
are quoted everywhere (K=40 gives 3 and 10, K=6144 gives 263 and 480).

DroneID uses K = 1408, which is 176 bytes, giving f1 = 43 and f2 = 88 and
three output streams of K+4 = 1412. That 1412 is
:data:`~antsdr_toolkit.droneid.constants.RATE_MATCH_D`, which is how the block
size was known before this module existed.

What a synthetic test does and does not prove
---------------------------------------------
Encoding with this and decoding with this proves the codec is self-consistent
and that the decoder recovers bits from noise, which is worth having and is
what the coding-gain measurement rests on. It does **not** prove
interoperability with DJI. One detail is genuinely unverified: 3GPP scatters
the twelve tail bits across the three streams in a specific order, and the
mapping used here follows srsRAN's flat output rather than a checked reading
of the standard's table. Twelve bits out of 4236 is under a third of a
percent, and they only terminate the trellis, so a wrong arrangement costs
almost nothing in performance and would not be visible in a synthetic test at
all. It would show up against a real capture, which is the only thing that can
settle it.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "QPP_PARAMS",
    "TAIL_BITS",
    "TRELLIS_STATES",
    "qpp_interleaver",
    "rsc_trellis",
    "turbo_decode",
    "turbo_encode",
]

#: The constituent encoder has three memory elements, so eight states.
TRELLIS_STATES = 8
#: Three tail steps per encoder, two encoders, two bits each: twelve in all,
#: which is four per output stream.
TAIL_BITS = 12

#: 3GPP TS 36.212 Table 5.1.3-3: block size to ``(f1, f2)``. Extracted from
#: srsRAN rather than typed from the standard, then checked for bijectivity.
QPP_PARAMS: dict[int, tuple[int, int]] = {
    40: (3, 10), 48: (7, 12), 56: (19, 42), 64: (7, 16),
    72: (7, 18), 80: (11, 20), 88: (5, 22), 96: (11, 24),
    104: (7, 26), 112: (41, 84), 120: (103, 90), 128: (15, 32),
    136: (9, 34), 144: (17, 108), 152: (9, 38), 160: (21, 120),
    168: (101, 84), 176: (21, 44), 184: (57, 46), 192: (23, 48),
    200: (13, 50), 208: (27, 52), 216: (11, 36), 224: (27, 56),
    232: (85, 58), 240: (29, 60), 248: (33, 62), 256: (15, 32),
    264: (17, 198), 272: (33, 68), 280: (103, 210), 288: (19, 36),
    296: (19, 74), 304: (37, 76), 312: (19, 78), 320: (21, 120),
    328: (21, 82), 336: (115, 84), 344: (193, 86), 352: (21, 44),
    360: (133, 90), 368: (81, 46), 376: (45, 94), 384: (23, 48),
    392: (243, 98), 400: (151, 40), 408: (155, 102), 416: (25, 52),
    424: (51, 106), 432: (47, 72), 440: (91, 110), 448: (29, 168),
    456: (29, 114), 464: (247, 58), 472: (29, 118), 480: (89, 180),
    488: (91, 122), 496: (157, 62), 504: (55, 84), 512: (31, 64),
    528: (17, 66), 544: (35, 68), 560: (227, 420), 576: (65, 96),
    592: (19, 74), 608: (37, 76), 624: (41, 234), 640: (39, 80),
    656: (185, 82), 672: (43, 252), 688: (21, 86), 704: (155, 44),
    720: (79, 120), 736: (139, 92), 752: (23, 94), 768: (217, 48),
    784: (25, 98), 800: (17, 80), 816: (127, 102), 832: (25, 52),
    848: (239, 106), 864: (17, 48), 880: (137, 110), 896: (215, 112),
    912: (29, 114), 928: (15, 58), 944: (147, 118), 960: (29, 60),
    976: (59, 122), 992: (65, 124), 1008: (55, 84), 1024: (31, 64),
    1056: (17, 66), 1088: (171, 204), 1120: (67, 140), 1152: (35, 72),
    1184: (19, 74), 1216: (39, 76), 1248: (19, 78), 1280: (199, 240),
    1312: (21, 82), 1344: (211, 252), 1376: (21, 86), 1408: (43, 88),
    1440: (149, 60), 1472: (45, 92), 1504: (49, 846), 1536: (71, 48),
    1568: (13, 28), 1600: (17, 80), 1632: (25, 102), 1664: (183, 104),
    1696: (55, 954), 1728: (127, 96), 1760: (27, 110), 1792: (29, 112),
    1824: (29, 114), 1856: (57, 116), 1888: (45, 354), 1920: (31, 120),
    1952: (59, 610), 1984: (185, 124), 2016: (113, 420), 2048: (31, 64),
    2112: (17, 66), 2176: (171, 136), 2240: (209, 420), 2304: (253, 216),
    2368: (367, 444), 2432: (265, 456), 2496: (181, 468), 2560: (39, 80),
    2624: (27, 164), 2688: (127, 504), 2752: (143, 172), 2816: (43, 88),
    2880: (29, 300), 2944: (45, 92), 3008: (157, 188), 3072: (47, 96),
    3136: (13, 28), 3200: (111, 240), 3264: (443, 204), 3328: (51, 104),
    3392: (51, 212), 3456: (451, 192), 3520: (257, 220), 3584: (57, 336),
    3648: (313, 228), 3712: (271, 232), 3776: (179, 236), 3840: (331, 120),
    3904: (363, 244), 3968: (375, 248), 4032: (127, 168), 4096: (31, 64),
    4160: (33, 130), 4224: (43, 264), 4288: (33, 134), 4352: (477, 408),
    4416: (35, 138), 4480: (233, 280), 4544: (357, 142), 4608: (337, 480),
    4672: (37, 146), 4736: (71, 444), 4800: (71, 120), 4864: (37, 152),
    4928: (39, 462), 4992: (127, 234), 5056: (39, 158), 5120: (39, 80),
    5184: (31, 96), 5248: (113, 902), 5312: (41, 166), 5376: (251, 336),
    5440: (43, 170), 5504: (21, 86), 5568: (43, 174), 5632: (45, 176),
    5696: (45, 178), 5760: (161, 120), 5824: (89, 182), 5888: (323, 184),
    5952: (47, 186), 6016: (23, 94), 6080: (47, 190), 6144: (263, 480),
}


def qpp_interleaver(k: int) -> np.ndarray:
    """The interleaving permutation for block size ``k``.

    ``pi[i]`` is where bit ``i`` of the interleaved sequence comes from, so
    ``interleaved = bits[qpp_interleaver(k)]``.
    """
    size = int(k)
    if size not in QPP_PARAMS:
        raise ValueError(
            f"{size} is not an LTE code block size; the nearest are "
            f"{max((s for s in QPP_PARAMS if s <= size), default=min(QPP_PARAMS))} and "
            f"{min((s for s in QPP_PARAMS if s >= size), default=max(QPP_PARAMS))}")
    f1, f2 = QPP_PARAMS[size]
    i = np.arange(size, dtype=np.int64)
    return ((f1 * i + f2 * i * i) % size).astype(np.int64)


def rsc_trellis() -> tuple[np.ndarray, np.ndarray]:
    """``(next_state, parity)``, each ``(8, 2)`` indexed by state and input bit.

    Built by running srsRAN's register update for every combination rather
    than by writing out a table, so the two cannot disagree.
    """
    next_state = np.zeros((TRELLIS_STATES, 2), dtype=np.int64)
    parity = np.zeros((TRELLIS_STATES, 2), dtype=np.int64)
    for state in range(TRELLIS_STATES):
        for bit in (0, 1):
            reg_0 = (state & 4) >> 2
            reg_1 = (state & 2) >> 1
            reg_2 = state & 1
            feedback = bit ^ (reg_2 ^ reg_1)
            out = reg_2 ^ (reg_0 ^ feedback)
            reg_2, reg_1, reg_0 = reg_1, reg_0, feedback
            next_state[state, bit] = (reg_0 << 2) | (reg_1 << 1) | reg_2
            parity[state, bit] = out
    return next_state, parity


def _encode_one(bits: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Run one constituent encoder; returns ``(systematic, parity, end_state)``."""
    next_state, parity_table = rsc_trellis()
    state = 0
    parity = np.empty(bits.size, dtype=np.uint8)
    for index, bit in enumerate(bits):
        parity[index] = parity_table[state, bit]
        state = next_state[state, bit]
    return bits.astype(np.uint8), parity, int(state)


def _terminate(state: int) -> tuple[np.ndarray, np.ndarray]:
    """Three tail steps that drive the encoder back to state zero.

    The input at each step is the feedback value itself, which makes the new
    register content zero; the systematic output is that input, not a data bit.
    """
    systematic = np.empty(3, dtype=np.uint8)
    parity = np.empty(3, dtype=np.uint8)
    for step in range(3):
        reg_0 = (state & 4) >> 2
        reg_1 = (state & 2) >> 1
        reg_2 = state & 1
        bit = reg_2 ^ reg_1
        feedback = bit ^ (reg_2 ^ reg_1)      # zero by construction
        out = reg_2 ^ (reg_0 ^ feedback)
        reg_2, reg_1, reg_0 = reg_1, reg_0, feedback
        systematic[step] = bit
        parity[step] = out
        state = (reg_0 << 2) | (reg_1 << 1) | reg_2
    return systematic, parity


def turbo_encode(bits: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Encode ``K`` bits into the three streams of ``K + 4`` the rate matcher wants.

    Returns ``(d0, d1, d2)``: systematic, first parity, second parity, each
    with four tail values appended.
    """
    data = np.asarray(bits, dtype=np.uint8).ravel()
    size = data.size
    if size not in QPP_PARAMS:
        raise ValueError(f"{size} bits is not an LTE code block size")
    if not np.all((data == 0) | (data == 1)):
        raise ValueError("input must be bits")

    permutation = qpp_interleaver(size)
    systematic, parity1, end1 = _encode_one(data)
    _interleaved, parity2, end2 = _encode_one(data[permutation])
    tail_sys1, tail_par1 = _terminate(end1)
    tail_sys2, tail_par2 = _terminate(end2)

    # srsRAN emits the twelve tail values as coder 1's three (systematic,
    # parity) pairs then coder 2's. Split into the three streams in that
    # order; see the caveat in the module docstring.
    tail = np.concatenate([
        tail_sys1, tail_par1, tail_sys2, tail_par2]).astype(np.uint8)
    d0 = np.concatenate([systematic, tail[0:4]])
    d1 = np.concatenate([parity1, tail[4:8]])
    d2 = np.concatenate([parity2, tail[8:12]])
    return d0, d1, d2


# ------------------------------------------------------------------ decoding
#
# Convention throughout: a log-likelihood ratio is log(P(bit=0) / P(bit=1)),
# so a positive value favours a zero. Getting this backwards decodes the
# complement of the message, which the CRC catches but only after wasting the
# whole block, so every function here states which way it runs.

_NEG_INF = -1.0e30


def _bcjr(llr_sys: np.ndarray, llr_par: np.ndarray, llr_apriori: np.ndarray,
          *, terminated: bool = True) -> np.ndarray:
    """One constituent decoder: extrinsic information about each input bit.

    Max-log-MAP, which replaces the exact ``log(e^a + e^b)`` with ``max(a, b)``.
    That costs a few tenths of a decibel against the full algorithm and removes
    the table lookup and the numerical range problems, which is the usual
    trade and the right one here.

    Returns *extrinsic* LLRs: what this decoder learned that its input did not
    already contain. Passing back the full a-posteriori value instead is the
    classic turbo bug, because the two decoders then feed each other their own
    prior belief and converge confidently on nonsense.
    """
    next_state, parity_table = rsc_trellis()
    n = llr_sys.size
    # Branch metric for each (state, input bit): the systematic and a-priori
    # terms depend only on the bit, the parity term on where the branch goes.
    sys_term = 0.5 * (llr_sys + llr_apriori)
    par = 0.5 * llr_par

    alpha = np.full((n + 1, TRELLIS_STATES), _NEG_INF)
    alpha[0, 0] = 0.0
    gamma = np.empty((n, TRELLIS_STATES, 2))
    for k in range(n):
        for bit in (0, 1):
            sign_bit = 1.0 - 2.0 * bit
            gamma[k, :, bit] = sign_bit * sys_term[k] + (
                1.0 - 2.0 * parity_table[:, bit]) * par[k]
        for bit in (0, 1):
            target = next_state[:, bit]
            candidate = alpha[k] + gamma[k, :, bit]
            np.maximum.at(alpha[k + 1], target, candidate)
        peak = alpha[k + 1].max()
        if peak > _NEG_INF / 2:
            alpha[k + 1] -= peak          # keep the metrics from drifting away

    beta = np.full((n + 1, TRELLIS_STATES), _NEG_INF)
    if terminated:
        beta[n, 0] = 0.0                  # the tail forces the trellis to zero
    else:
        beta[n, :] = 0.0
    for k in range(n - 1, -1, -1):
        for bit in (0, 1):
            beta[k] = np.maximum(beta[k], beta[k + 1][next_state[:, bit]]
                                 + gamma[k, :, bit])
        peak = beta[k].max()
        if peak > _NEG_INF / 2:
            beta[k] -= peak

    posterior = np.empty((n, 2))
    for bit in (0, 1):
        posterior[:, bit] = np.max(
            alpha[:-1] + gamma[:, :, bit] + beta[1:][:, next_state[:, bit]], axis=1)
    full = posterior[:, 0] - posterior[:, 1]
    return full - llr_sys - llr_apriori


def turbo_decode(llr_sys: np.ndarray, llr_par1: np.ndarray, llr_par2: np.ndarray,
                 *, iterations: int = 8, crc_check=None) -> np.ndarray:
    """Iteratively decode one code block back to ``K`` bits.

    ``llr_*`` are the three streams of ``K + 4`` values in the sign convention
    above. The tail values terminate the trellises and are dropped from the
    result.

    The two constituent decoders alternate, each handing the other its
    extrinsic information, interleaved or de-interleaved as appropriate. Give
    ``crc_check`` a callable taking the hard bits and returning ``True`` to
    stop as soon as the block is correct, which is both faster and a guard
    against the rare case where further iterations walk away from a good
    answer.
    """
    sys_full = np.asarray(llr_sys, dtype=np.float64).ravel()
    p1 = np.asarray(llr_par1, dtype=np.float64).ravel()
    p2 = np.asarray(llr_par2, dtype=np.float64).ravel()
    if not sys_full.size == p1.size == p2.size:
        raise ValueError(f"the three streams must match: got {sys_full.size}, "
                         f"{p1.size}, {p2.size}")
    k = sys_full.size - 4
    if k not in QPP_PARAMS:
        raise ValueError(f"{k} bits is not an LTE code block size")
    permutation = qpp_interleaver(k)
    inverse = np.argsort(permutation)

    # The systematic stream carries the data bits; the second decoder sees
    # them interleaved, and its own systematic tail values, which the first
    # decoder's tail does not supply.
    sys_a = np.concatenate([sys_full[:k], sys_full[k:]])
    sys_b = np.concatenate([sys_full[:k][permutation], np.zeros(4)])

    extrinsic = np.zeros(k)
    bits = np.zeros(k, dtype=np.uint8)
    for _ in range(max(1, int(iterations))):
        apriori_a = np.concatenate([extrinsic, np.zeros(4)])
        out_a = _bcjr(sys_a, p1, apriori_a)[:k]

        apriori_b = np.concatenate([out_a[permutation], np.zeros(4)])
        out_b = _bcjr(sys_b, p2, apriori_b)[:k]
        extrinsic = out_b[inverse]

        posterior = sys_full[:k] + out_a + extrinsic
        bits = (posterior < 0).astype(np.uint8)
        if crc_check is not None and crc_check(bits):
            break
    return bits
