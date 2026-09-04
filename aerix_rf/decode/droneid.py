"""Stage-3 DJI DroneID decode (best-effort, OcuSync <= 2.0).

Ported from proto17/dji_droneid and anarkiwi/samples2djidroneid. The front end is
wired end-to-end: burst detection via ZC correlation, resampling to 15.36 MHz,
time/frequency synchronization (ZC + cyclic-prefix STO + CP-based CFO), OFDM
demodulation, ZC channel equalization, QPSK demod, and LTE Gold-sequence
descrambling. What is NOT yet implemented is the LTE rate-matching / Turbo decode
and field extraction (serial, lat/lon), which the reference offloads to a C++
`remove_turbo` program -- see the TODOs in :func:`decode`.

`decode()` therefore returns a DroneIdResult with `protocol` set but location/serial
fields None until Turbo decode lands; the recoverable intermediates (sync offset,
CFO, demodulated symbols, descrambled bits) are exposed via :func:`demodulate`.

Only OcuSync <= 2.0 is decodable; O3/O4 are encrypted. Decoded operator location is
personal data -> retention-gated server-side.

Source: https://github.com/proto17/dji_droneid
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import ofdm
from .zc import find_zc_symbol_start

# LTE scrambler second-LFSR init: the 31-bit literal 0x12345678 pattern from
# process_file.m, bit-reversed (fliplr). Kept verbatim from the reference.
_X2_INIT = np.array(list(reversed([
    0, 0, 1,   0, 0, 1, 0,   0, 0, 1, 1,   0, 1, 0, 0,
    0, 1, 0, 1,   0, 1, 1, 0,   0, 1, 1, 1,   1, 0, 0, 0,
])), dtype=np.int8)

# ZC correlation score below which we declare "no decodable burst present".
DEFAULT_CORRELATION_THRESHOLD = 0.5


@dataclass
class DroneIdResult:
    serial: str | None
    drone_lat: float | None
    drone_lon: float | None
    operator_lat: float | None
    operator_lon: float | None
    protocol: str        # e.g. "ocusync2"


@dataclass
class DroneIdDemod:
    """Recoverable front-end products of a DroneID burst (pre-Turbo-decode)."""
    sync_offset: int                 # burst start sample index (in 15.36 MHz stream)
    zc_score: float                  # peak ZC correlation, 0..1
    cfo_hz: float                    # estimated & corrected carrier freq offset
    sample_rate: float               # working rate (15.36 MHz)
    fft_size: int
    freq_symbols: np.ndarray         # [9, fft_size] fftshift(fft(symbol))
    data_carriers: np.ndarray        # [9, 600] equalized data-carrier symbols
    qpsk_bits: np.ndarray            # [9, 1200] hard-decision bits per symbol
    descrambled_bits: np.ndarray     # [7200] descrambled payload bits
    resampled: bool = False


def generate_scrambler_seq(num_bits: int, x2_init: np.ndarray = _X2_INIT) -> np.ndarray:
    """LTE pseudo-random (Gold) sequence generator (generate_scrambler_seq.m).

    x1 fixed init [1,0,...,0]; Nc=1600 offset; c(n) = x1(n+Nc) ^ x2(n+Nc).
    """
    nc = 1600
    total = num_bits + nc
    x1 = np.zeros(total + 31, dtype=np.int8)
    x2 = np.zeros(total + 31, dtype=np.int8)
    x1[0] = 1                                        # x1_init = [1,0,...,0]
    x2[:31] = x2_init
    for n in range(total):
        x1[n + 31] = (x1[n + 3] + x1[n]) & 1
        x2[n + 31] = (x2[n + 3] + x2[n + 2] + x2[n + 1] + x2[n]) & 1
    return (x1[nc:nc + num_bits] ^ x2[nc:nc + num_bits]).astype(np.int8)


def descramble_payload(qpsk_bits: np.ndarray) -> np.ndarray:
    """Descramble the 6 payload OFDM symbols (process_file.m).

    Selects 1-based symbols [2,3,5,7,8,9] (ZC symbols 4/6 and the leading symbol 1
    are excluded), row-major flattens to 7200 bits, and XORs with the scrambler.
    """
    data_rows = [s - 1 for s in ofdm.DATA_SYMBOLS_1B]     # -> [1,2,4,6,7,8]
    payload = qpsk_bits[data_rows, :].reshape(-1).astype(np.int8)
    seq = generate_scrambler_seq(payload.size)
    return (payload ^ seq).astype(np.int8)


def demodulate(iq: np.ndarray, sample_rate: float,
               correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
               ) -> DroneIdDemod | None:
    """Run the DroneID front end; return recoverable intermediates or None.

    None is returned when no burst correlates above `correlation_threshold`.
    """
    iq = np.asarray(iq, dtype=np.complex128)

    # (2) Resample to the nominal 15.36 MHz if the input differs.
    resampled = abs(sample_rate - ofdm.NOMINAL_SAMPLE_RATE) >= 1.0
    work = ofdm.resample_to(iq, sample_rate, ofdm.NOMINAL_SAMPLE_RATE)
    fs = ofdm.NOMINAL_SAMPLE_RATE
    fft_size = ofdm.fft_size_for(fs)

    if work.size < ofdm.burst_length(fs):
        return None

    # (3a) Coarse time sync: correlate for the first ZC sequence (symbol 4).
    zc_peak, zc_score = find_zc_symbol_start(work, fft_size, symbol_index=4)
    if zc_score < correlation_threshold:
        return None

    # ZC symbol 4's data starts `sum(cp[0:4]) + 3*fft` after the burst start.
    schedule = ofdm.cp_schedule(fs)
    pre_zc4 = sum(schedule[:4]) + fft_size * 3
    coarse_start = zc_peak - pre_zc4

    # (3b) Refine with cyclic-prefix STO around the coarse estimate.
    burst_start = ofdm.find_sto_cp(work, fs, coarse_start)
    if burst_start < 0 or burst_start + ofdm.burst_length(fs) > work.size:
        burst_start = max(0, min(coarse_start, work.size - ofdm.burst_length(fs)))

    # (3c) Coarse CFO from a short-CP symbol and correct it.
    cfo_hz = ofdm.estimate_cfo(work, fs, burst_start)
    work = ofdm.apply_cfo(work, fs, cfo_hz)

    # (4) OFDM demod: strip CPs, FFT each symbol.
    _time_syms, freq_syms = ofdm.extract_ofdm_symbols(work, fs, burst_start)

    # ZC channel estimate (symbol 4) -> zero-forcing equalizer on data carriers.
    dci = ofdm.data_carrier_indices(fft_size)
    channel = ofdm.zc_channel(freq_syms[3], fft_size, 4)[dci]

    data_carriers = np.zeros((ofdm.NUM_OFDM_SYMBOLS, dci.size), dtype=np.complex128)
    qpsk_bits = np.zeros((ofdm.NUM_OFDM_SYMBOLS, dci.size * 2), dtype=np.int8)
    for idx in range(ofdm.NUM_OFDM_SYMBOLS):
        eq = freq_syms[idx, dci] * channel
        data_carriers[idx] = eq
        qpsk_bits[idx] = ofdm.quantize_qpsk(eq)

    # (5) Descramble the payload symbols.
    descrambled = descramble_payload(qpsk_bits)

    return DroneIdDemod(
        sync_offset=int(burst_start),
        zc_score=float(zc_score),
        cfo_hz=float(cfo_hz),
        sample_rate=fs,
        fft_size=fft_size,
        freq_symbols=freq_syms,
        data_carriers=data_carriers,
        qpsk_bits=qpsk_bits,
        descrambled_bits=descrambled,
        resampled=resampled,
    )


def decode(iq: np.ndarray, sample_rate: float) -> DroneIdResult | None:
    """Attempt to decode a DJI DroneID burst from an IQ window.

    Returns None when no decodable (OcuSync <= 2.0) burst is present. The front end
    (sync + OFDM demod + descramble) is implemented; the fields below remain None
    until the LTE rate-match / Turbo decode stage lands.

    TODO(stage-3): LTE de-rate-match + Turbo decode of `demod.descrambled_bits`
        (7200 bits -> ~176-byte frame). The reference offloads this to the C++
        `remove_turbo` program (proto17/dji_droneid cpp/remove_turbo). Port it or
        shell out, then parse the frame per DroneSecurity/arxiv 2207.10795.
    TODO(stage-3): after Turbo decode, verify the frame CRC and extract fields
        (serial, drone lat/lon, operator lat/lon, home lat/lon, altitude) into the
        DroneIdResult below.
    TODO(stage-3): integer (multi-subcarrier) CFO via the DC-null search in the ZC
        symbol (process_file.m) -- currently only fractional CFO is corrected, so
        offsets |f| must be < half a subcarrier (7.5 kHz).
    TODO(stage-3): handle the 8-symbol drone variant (leading symbol absent);
        find_sto_cp already ignores symbol 1, but symbol extraction assumes 9.
    """
    demod = demodulate(iq, sample_rate)
    if demod is None:
        return None
    # Front end succeeded but frame decode is not implemented yet; surface the
    # protocol so callers know a decodable burst was seen.
    return DroneIdResult(
        serial=None,
        drone_lat=None,
        drone_lon=None,
        operator_lat=None,
        operator_lon=None,
        protocol="ocusync2",
    )


def available() -> bool:
    """Whether the demod front end is wired in (True once sync+OFDM demod exist)."""
    return True
