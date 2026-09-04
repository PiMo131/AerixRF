"""Synthetic DJI-DroneID-like OFDM burst generator, for testing the decoder.

Builds a spec-accurate 9-symbol OcuSync-<=2.0 burst at 15.36 MHz: ZC pilots in
symbols 4 and 6 (1-based), random QPSK on the 600 data carriers elsewhere, correct
cyclic-prefix schedule, optional AWGN / carrier-frequency offset / lead-in padding.
This mirrors the transmit path in proto17/dji_droneid (matlab/updated_scripts/transmit)
closely enough to validate ZC sync and OFDM demod. It does NOT touch aerix_rf/sdr/sim.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import ofdm
from .zc import zc_time_domain


@dataclass
class SynthBurst:
    iq: np.ndarray                   # complex64 samples
    sample_rate: float
    burst_start: int                 # index of first CP sample within `iq`
    payload_bits: np.ndarray         # [9, 1200] injected pre-scramble bits
    scrambled: bool                  # whether payload symbols were scrambled


@dataclass
class EncodedBurst:
    """A fully-encoded DroneID burst plus the ground-truth frame fields."""
    iq: np.ndarray
    sample_rate: float
    burst_start: int
    fields: dict                     # the known serial / lat / lon / ... that went in
    frame_bytes: bytes               # 176-byte turbo info block (for reference)


def _qpsk_from_bits(bits: np.ndarray) -> np.ndarray:
    """Inverse of ofdm.quantize_qpsk: (b0,b1) pairs -> unit QPSK points.

    00->1+j, 01->1-j, 10->-1+j, 11->-1-j (matches quantize_qpsk.m).
    """
    b0 = bits[0::2]
    b1 = bits[1::2]
    i = np.where(b0 == 0, 1.0, -1.0)
    q = np.where(b1 == 0, 1.0, -1.0)
    return (i + 1j * q) / np.sqrt(2.0)


def make_burst(sample_rate: float = ofdm.NOMINAL_SAMPLE_RATE, *,
               snr_db: float | None = 15.0, cfo_hz: float = 0.0,
               pad_start: int = 500, pad_end: int = 500,
               scramble: bool = False, seed: int = 0) -> SynthBurst:
    """Generate one synthetic DroneID burst embedded in noise padding.

    Generated at 15.36 MHz. `snr_db=None` disables noise entirely (clean burst,
    still with padding). `scramble=True` applies the LTE scrambler to the payload
    symbols so the decoder's descramble stage round-trips to `payload_bits`.
    """
    rng = np.random.default_rng(seed)
    fs = sample_rate
    fft_size = ofdm.fft_size_for(fs)
    schedule = ofdm.cp_schedule(fs)
    dci = ofdm.data_carrier_indices(fft_size)

    payload_bits = rng.integers(0, 2, size=(ofdm.NUM_OFDM_SYMBOLS, dci.size * 2)).astype(np.int8)

    # Optionally scramble the six payload symbols exactly as the decoder expects.
    tx_bits = payload_bits.copy()
    if scramble:
        from .droneid import generate_scrambler_seq
        data_rows = [s - 1 for s in ofdm.DATA_SYMBOLS_1B]
        seq = generate_scrambler_seq(len(data_rows) * dci.size * 2).reshape(len(data_rows), dci.size * 2)
        for r, row in enumerate(data_rows):
            tx_bits[row] = payload_bits[row] ^ seq[r]

    iq = _tx_bits_to_iq(tx_bits, fs, fft_size, schedule, dci,
                        snr_db=snr_db, cfo_hz=cfo_hz,
                        pad_start=pad_start, pad_end=pad_end, rng=rng)

    return SynthBurst(
        iq=iq.astype(np.complex64),
        sample_rate=fs,
        burst_start=pad_start,
        payload_bits=payload_bits,
        scrambled=scramble,
    )


def _tx_bits_to_iq(tx_bits: np.ndarray, fs: float, fft_size: int, schedule, dci,
                   *, snr_db: float | None, cfo_hz: float,
                   pad_start: int, pad_end: int, rng) -> np.ndarray:
    """Turn a [9, 1200] scrambled-bit matrix into a padded, noisy IQ burst.

    ZC symbols (4 & 6, 1-based) are inserted from the golden sequence; every other
    symbol carries QPSK from ``tx_bits``. The RNG draw order (lead, tail, noise) is
    kept stable so callers reproduce bit-exact output for a given seed.
    """
    # Build each OFDM symbol's time-domain samples (fft_size) then prepend its CP.
    burst_parts = []
    for idx in range(ofdm.NUM_OFDM_SYMBOLS):
        sym_1b = idx + 1
        if sym_1b in ofdm.ZC_SYMBOLS_1B:
            td = zc_time_domain(fft_size, sym_1b)
        else:
            freq = np.zeros(fft_size, dtype=np.complex128)
            freq[dci] = _qpsk_from_bits(tx_bits[idx])
            # synth: ifft(ifftshift(F)); demod: fftshift(fft(t)) -> round-trips.
            td = np.fft.ifft(np.fft.ifftshift(freq))
        cp = td[-schedule[idx]:]
        burst_parts.append(np.concatenate([cp, td]))
    burst = np.concatenate(burst_parts)

    # Normalize burst power to ~1.0 so SNR is meaningful.
    burst = burst / np.sqrt(np.mean(np.abs(burst) ** 2))

    # Apply a carrier-frequency offset to the burst.
    if cfo_hz:
        n = np.arange(burst.size)
        burst = burst * np.exp(1j * 2 * np.pi * cfo_hz / fs * n)

    lead = (rng.standard_normal(pad_start) + 1j * rng.standard_normal(pad_start)) / np.sqrt(2.0)
    tail = (rng.standard_normal(pad_end) + 1j * rng.standard_normal(pad_end)) / np.sqrt(2.0)
    if snr_db is None:
        lead *= 0.0
        tail *= 0.0
    iq = np.concatenate([lead, burst, tail]).astype(np.complex128)

    if snr_db is not None:
        noise_p = 10.0 ** (-snr_db / 10.0)
        noise = (rng.standard_normal(iq.size) + 1j * rng.standard_normal(iq.size))
        noise *= np.sqrt(noise_p / 2.0)
        iq = iq + noise
    return iq


def make_encoded_burst(fields: dict | None = None, *,
                       sample_rate: float = ofdm.NOMINAL_SAMPLE_RATE,
                       snr_db: float | None = 30.0, cfo_hz: float = 0.0,
                       pad_start: int = 500, pad_end: int = 500,
                       seed: int = 0) -> EncodedBurst:
    """Encode a full DroneID frame end-to-end into an IQ burst.

    Runs the complete transmit chain: frame bytes -> CRC16 -> CRC24A -> LTE turbo
    encode -> rate match (E=7200) -> LTE scramble -> QPSK -> OFDM (+ ZC pilots).
    ``fields`` overrides any packer keyword (serial, drone_lat, drone_lon,
    operator_lat, operator_lon, home_lat, home_lon, height, altitude, ...). The
    returned IQ is decodable by :func:`aerix_rf.decode.droneid.decode`.
    """
    from . import turbo as T
    from . import frame as F
    from .droneid import generate_scrambler_seq

    fields = dict(fields or {})
    dji_frame = F.pack_dji_frame(**fields)
    payload = F.build_turbo_payload(dji_frame)             # 176 bytes

    info_bits = T.bytes_to_bits(payload)                   # 1408 bits
    d0, d1, d2 = T.turbo_encode(info_bits)
    e = T.rate_match(d0, d1, d2)                            # 7200 bits

    # Scramble so the decoder's descramble stage recovers `e` exactly.
    seq = generate_scrambler_seq(e.size)
    scrambled = (e ^ seq).astype(np.int8)

    fs = sample_rate
    fft_size = ofdm.fft_size_for(fs)
    schedule = ofdm.cp_schedule(fs)
    dci = ofdm.data_carrier_indices(fft_size)

    data_rows = [s - 1 for s in ofdm.DATA_SYMBOLS_1B]      # [1,2,4,6,7,8]
    tx_bits = np.zeros((ofdm.NUM_OFDM_SYMBOLS, dci.size * 2), dtype=np.int8)
    chunks = scrambled.reshape(len(data_rows), dci.size * 2)
    for r, row in enumerate(data_rows):
        tx_bits[row] = chunks[r]

    rng = np.random.default_rng(seed)
    iq = _tx_bits_to_iq(tx_bits, fs, fft_size, schedule, dci,
                        snr_db=snr_db, cfo_hz=cfo_hz,
                        pad_start=pad_start, pad_end=pad_end, rng=rng)

    return EncodedBurst(
        iq=iq.astype(np.complex64),
        sample_rate=fs,
        burst_start=pad_start,
        fields=fields,
        frame_bytes=payload,
    )
