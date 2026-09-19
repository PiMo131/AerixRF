"""Synthetic SiK-style 2-GFSK burst generator, for testing the demodulator only.

**Evidence level 1 (synthetic).** This generator encodes the PHY parameters
read out of the ArduPilot SiK firmware in
``docs/design/sik-mavlink-passive-decode.md`` S1 (air rates, deviation/h,
Gaussian BT, 64-bit alternating preamble, 2-byte sync). It shares model
assumptions with ``gfsk.py`` (same inferred 0x2DD4 sync value, same Gaussian
pulse-shaping model), so a passing test here is "decoder self-consistency
verified" and is **not** evidence that AERIX can decode a real SiK radio.

Modulation model
-----------------
2-level GFSK is built as "Gaussian-filtered NRZ -> FM":

1. Bits -> NRZ symbols a_k in {-1, +1} (bit 1 -> +1, bit 0 -> -1).
2. NRZ is oversampled by an internal fine factor and passed through a
   Gaussian FIR low-pass filter of unit DC gain, whose -3 dB bandwidth is
   ``bt * rate_bps`` (the standard GMSK/GFSK BT convention). Because the
   filter has unit DC gain, a long run of identical symbols settles to
   exactly the target deviation, so the peak frequency deviation is set by
   ``h``: ``deviation_hz = h * rate_bps / 2`` (``h = 2*deviation/rate_bps``,
   matching the firmware-derived table in the design doc).
3. The Gaussian-smoothed frequency waveform is resampled from the internal
   fine grid to the output sample rate ``fs`` by linear interpolation at
   sample instants ``n/fs + timing_offset_s``. Because the fine grid is much
   finer than both the symbol period and ``1/fs``, this gives an accurate,
   *and exactly-controllable*, arbitrary (sub-sample) timing offset without
   a separate fractional-delay filter.
4. A constant CFO (Hz) is added to the frequency waveform before phase
   integration (``phase = 2*pi*cumsum(freq)/fs``); ``iq = exp(1j*phase)``.
5. AWGN is added at the full sample rate, with power set so that the
   resulting SNR is the **in-band SNR referenced to a 2*rate_bps noise
   bandwidth** (i.e. ``N0 = signal_power / (snr_linear * 2*rate_bps)``,
   total complex noise power added is ``N0 * fs``). This matches how a
   receiver would report SNR after a channel filter roughly matched to the
   GFSK occupied bandwidth, without actually applying that filter here.

None of steps 1-5 involve real recorded RF; they are a model of the firmware
description only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# air_data_rates[] from SiK firmware main.c (S1, PRIMARY), bits/second.
SIK_AIR_RATES_BPS = (
    2000, 4000, 8000, 16000, 19000, 24000, 32000, 48000, 64000, 96000,
    128000, 192000, 250000,
)

# Nominal modulation index h = 2*deviation/rate_bps, from the firmware
# deviation register table converted with the Si4432 625 Hz/LSB step
# (design doc S1, "Deviation / modulation index"). INFERRED value at the
# top two rates (deviation ceiling).
_DEFAULT_SYNC_WORD = 0x2DD4  # Si4432 power-on default; INFERRED, not firmware-confirmed.
_PREAMBLE_BITS_DEFAULT = 64


def nominal_h(rate_bps: float) -> float:
    """Nominal modulation index for a SiK air rate, per the design doc's S1 table.

    h ~= 1.875 at 2/4 kbps, ~=2.0 for 8-128 kbps, 1.65 at 192 kbps, 1.27 at
    250 kbps (deviation-ceiling effect). Evidence level 1: this is the
    design doc's INFERRED conversion of the firmware's deviation register
    table, not a measurement on real hardware.
    """
    kbps = rate_bps / 1000.0
    if kbps <= 4.0:
        return 1.875
    if kbps <= 128.0:
        return 2.0
    if kbps <= 192.0:
        return 1.65
    return 1.27


def _int_to_bits(value: int, n: int, bit_order: str = "msb") -> np.ndarray:
    if bit_order == "msb":
        return np.array([(value >> (n - 1 - i)) & 1 for i in range(n)], dtype=np.uint8)
    if bit_order == "lsb":
        return np.array([(value >> i) & 1 for i in range(n)], dtype=np.uint8)
    raise ValueError(f"bit_order must be 'msb' or 'lsb', got {bit_order!r}")


def _bytes_to_bits(data: bytes, bit_order: str = "msb") -> np.ndarray:
    arr = np.frombuffer(bytes(data), dtype=np.uint8)
    bits = np.zeros(len(arr) * 8, dtype=np.uint8)
    shifts = range(7, -1, -1) if bit_order == "msb" else range(8)
    for i, s in enumerate(shifts):
        bits[i::8] = (arr >> s) & 1
    return bits


def _gaussian_lowpass_taps(bt: float, rate_bps: float, fs_fine: float, span: float = 4.0) -> np.ndarray:
    """Unit-DC-gain Gaussian FIR, -3 dB bandwidth = bt*rate_bps, sampled at fs_fine.

    Uses the standard GMSK/GFSK relation between -3 dB bandwidth B and the
    Gaussian time-domain std dev: sigma_t = sqrt(ln 2) / (2*pi*B).
    """
    bw_hz = bt * rate_bps
    sigma_t = np.sqrt(np.log(2.0)) / (2.0 * np.pi * bw_hz)
    ntaps = int(np.ceil(2 * span * sigma_t * fs_fine))
    ntaps += 1 - (ntaps % 2)  # force odd
    ntaps = max(ntaps, 3)
    n = np.arange(ntaps) - ntaps // 2
    t = n / fs_fine
    taps = np.exp(-0.5 * (t / sigma_t) ** 2)
    taps /= taps.sum()
    return taps


@dataclass
class SikBurst:
    """A synthetic SiK 2-GFSK burst plus the ground truth used to build it.

    Evidence level 1 (synthetic) -- see module docstring.
    """

    iq: np.ndarray               # complex64 samples at `fs`
    fs: float
    rate_bps: float
    h: float
    bt: float
    cfo_hz: float
    snr_db: Optional[float]
    timing_offset_s: float
    bit_order: str
    sync_word: int
    n_preamble_bits: int
    n_sync_bits: int
    preamble_bits: np.ndarray
    sync_bits: np.ndarray
    payload_bits: np.ndarray     # ground-truth payload bits, in `bit_order`
    all_bits: np.ndarray         # preamble + sync + payload, in `bit_order`
    meta: dict = field(default_factory=dict)


def make_sik_burst(
    payload_bytes: Optional[bytes] = None,
    bits: Optional[np.ndarray] = None,
    *,
    rate_bps: float,
    fs: float,
    h: Optional[float] = None,
    bt: float = 0.5,
    cfo_hz: float = 0.0,
    snr_db: Optional[float] = None,
    preamble_bits: int = _PREAMBLE_BITS_DEFAULT,
    sync: int = _DEFAULT_SYNC_WORD,
    bit_order: str = "msb",
    timing_offset_s: float = 0.0,
    settle_symbols: int = 2,
    fine_oversample: int = 64,
    seed: Optional[int] = None,
) -> SikBurst:
    """Build a synthetic SiK-style 2-GFSK burst. Evidence level 1 (synthetic).

    This does NOT demonstrate decoding a real SiK radio: the sync word
    (0x2DD4) and the Gaussian pulse-shaping model are inferred/assumed, not
    confirmed against firmware or hardware.

    Exactly one of ``payload_bytes`` / ``bits`` must be given (``bits`` is a
    0/1 array in ``bit_order``; ``payload_bytes`` is packed MSB/LSB-first per
    byte per ``bit_order``). ``h`` defaults to ``nominal_h(rate_bps)`` if not
    given. Returns a :class:`SikBurst` (``.iq`` is complex64).
    """
    if (payload_bytes is None) == (bits is None):
        raise ValueError("give exactly one of payload_bytes or bits")
    if bits is None:
        payload_bits = _bytes_to_bits(payload_bytes, bit_order)
    else:
        payload_bits = np.asarray(bits, dtype=np.uint8)
    if h is None:
        h = nominal_h(rate_bps)

    preamble = np.resize(np.array([1, 0], dtype=np.uint8), preamble_bits)
    sync_bits = _int_to_bits(sync, 16, bit_order)
    all_bits = np.concatenate([preamble, sync_bits, payload_bits])

    # Pad with settle symbols (repeat edge bit) so filter/interp edge
    # transients land outside the region of interest.
    padded = np.concatenate([
        np.full(settle_symbols, all_bits[0], dtype=np.uint8),
        all_bits,
        np.full(settle_symbols, all_bits[-1], dtype=np.uint8),
    ])
    a_k = np.where(padded, 1.0, -1.0)

    deviation_hz = h * rate_bps / 2.0
    fs_fine = fine_oversample * rate_bps
    nrz_fine = np.repeat(a_k, fine_oversample)
    taps = _gaussian_lowpass_taps(bt, rate_bps, fs_fine)
    freq_fine = np.convolve(nrz_fine, taps, mode="same") * deviation_hz

    t_fine = np.arange(len(freq_fine)) / fs_fine
    n_bits_total = len(padded)
    duration_s = n_bits_total / rate_bps
    n_out = int(round(duration_s * fs))
    t_out = np.arange(n_out) / fs + timing_offset_s
    freq_out = np.interp(t_out, t_fine, freq_fine, left=freq_fine[0], right=freq_fine[-1])

    freq_out = freq_out + cfo_hz
    phase = 2.0 * np.pi * np.cumsum(freq_out) / fs
    iq = np.exp(1j * phase).astype(np.complex64)

    rng = np.random.default_rng(seed)
    if snr_db is not None:
        signal_power = float(np.mean(np.abs(iq) ** 2))
        noise_bw = 2.0 * rate_bps
        snr_lin = 10.0 ** (snr_db / 10.0)
        n0 = signal_power / (snr_lin * noise_bw)
        noise_power_total = n0 * fs
        sigma = np.sqrt(noise_power_total / 2.0)
        noise = sigma * (rng.standard_normal(n_out) + 1j * rng.standard_normal(n_out))
        iq = (iq + noise).astype(np.complex64)

    return SikBurst(
        iq=iq,
        fs=fs,
        rate_bps=rate_bps,
        h=h,
        bt=bt,
        cfo_hz=cfo_hz,
        snr_db=snr_db,
        timing_offset_s=timing_offset_s,
        bit_order=bit_order,
        sync_word=sync,
        n_preamble_bits=preamble_bits,
        n_sync_bits=16,
        preamble_bits=preamble,
        sync_bits=sync_bits,
        payload_bits=payload_bits,
        all_bits=all_bits,
        meta={
            "deviation_hz": deviation_hz,
            "settle_symbols": settle_symbols,
            "n_samples": n_out,
        },
    )
