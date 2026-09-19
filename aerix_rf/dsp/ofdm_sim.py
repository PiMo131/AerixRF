"""Synthetic 802.11a/g-like OFDM (Wi-Fi) and BLE-like GFSK waveform generators.

**Evidence level 1 (synthetic).** These are ground-truth generators for
negative-controlling Stage-1 link-signature rules and the SiK GFSK decoder
against the dominant 2.4 GHz interferer class (Wi-Fi-like OFDM and
Bluetooth-LE-like GFSK). A pass against these generators is "the detector
does not fire on this synthetic model of the interferer" -- it is NOT
evidence about how a real Wi-Fi or BLE radio's spectrum behaves. Style
mirrors ``aerix_rf.dsp.fmvideo_sim`` and ``aerix_rf.decode.sik.synth``:
numpy-only (plus scipy.signal for resampling/FIR design), seeded, returns
complex64 baseband IQ at a requested sample rate.

OFDM PHY model (``make_ofdm_burst``)
-------------------------------------
Modelled on the 802.11a/g OFDM PLCP: 64-point FFT, 312.5 kHz subcarrier
spacing at the native 20 MHz rate, 52 used subcarriers (48 data + 4 pilot,
indices -26..-1 and 1..26, DC null), 0.8 microsecond (16-sample) cyclic
prefix per data symbol, and the standard short/long training preamble
(8 microseconds STF + 8 microseconds LTF = 16 microseconds total) when
``preamble=True``. The waveform is built at a "native" rate equal to
``bw_hz`` (so the default ``bw_hz=20e6`` reproduces the literal 802.11a
sample-rate/subcarrier-spacing numbers), then resampled to the caller's
``fs_hz`` with ``scipy.signal.resample_poly`` on an exact
``fractions.Fraction`` ratio.

Preamble sequence provenance (IMPORTANT -- read before treating this as a
standards-conformance reference):

* ``_STF_INDEX_VALUES`` (802.11a Table L-2-style short training sequence)
  and ``_LTF_INDEX_VALUES`` (802.11a Table L-6-style long training
  sequence) below are transcribed from memory of the widely-reproduced
  reference values (the same numbers appear, byte-for-byte as far as this
  author can tell, across many independent open-source 802.11a OFDM
  implementations). The STF passes an internal self-consistency check (its
  12 nonzero tones are exactly 4 subcarriers apart, which is required for
  the frequency-domain definition to produce a time-domain signal with the
  correct 16-sample/0.8 microsecond periodicity used by the autocorrelation
  test below) -- but neither array has been independently checked against
  the primary IEEE 802.11-2016 standard text from within this task. Treat
  both as **high-confidence-but-unverified**, not as a certified reference;
  a reviewer who needs bit-exact standards conformance (e.g. for a
  correlation-based real preamble detector) should have
  ``rf-protocol-analyst`` confirm them against the standard before relying
  on exact values. They are intentionally NOT suffixed ``_LIKE`` because
  they are believed correct, but this caveat stands in for that lower-
  confidence label where it matters.
* The 4 pilot subcarriers (indices -21, -7, 7, 21) use a fixed +1 BPSK
  value for every OFDM data symbol -- this is **not** the real 127-bit
  pilot polarity scrambler sequence (802.11a Eq 17-9), which this module
  does not implement. Good enough to exercise pilot-tone morphology, not a
  real pilot-tracking receiver.
* Data subcarrier bits are IID random per call (seeded); there is no real
  802.11 scrambler, convolutional coder, or interleaver. QPSK / 16-QAM
  constellation mappings use the standard Gray-coded bit assignments.

BLE-like GFSK model (``make_ble_like_scene``)
----------------------------------------------
A ~20-line "Gaussian-filtered NRZ -> FM" modulator (same technique as
``aerix_rf.decode.sik.synth``, reimplemented locally here rather than
imported, to keep this module decoupled from ``aerix_rf.decode``): NRZ bits
are oversampled, passed through a unit-DC-gain Gaussian FIR of -3 dB
bandwidth ``bt * rate_bps``, scaled to +/-``deviation_hz``, and integrated
to phase. Each synthetic packet is preamble (0xAA alternating bits) + a
32-bit access address (0x8E89BED6, the standard BLE advertising-channel
access address per the Bluetooth Core Spec -- transcribed from memory,
**not independently verified in this task**, and it is not used for any
correlation/sync logic here) + random payload bits. This is a channel-
occupancy/deviation model only: there is no CRC, whitening, or L2CAP
framing.
"""

from __future__ import annotations

from fractions import Fraction
from typing import List, Sequence, Tuple

import numpy as np
from scipy.signal import resample_poly

__all__ = [
    "make_ofdm_burst",
    "make_wifi_like_scene",
    "make_ble_like_scene",
]

# --- 802.11a preamble frequency-domain definitions (index -> value) -------
# See module docstring "Preamble sequence provenance" for the evidence
# caveat. Index range -26..26 (DC excluded), as in IEEE 802.11-2016 S17.3.3.

_SQRT13_6 = float(np.sqrt(13.0 / 6.0))
_STF_INDEX_VALUES = {  # "802.11a Table L-2"-style short training sequence
    -24: (1 + 1j) * _SQRT13_6, -20: (-1 - 1j) * _SQRT13_6,
    -16: (1 + 1j) * _SQRT13_6, -12: (-1 - 1j) * _SQRT13_6,
    -8: (-1 - 1j) * _SQRT13_6, -4: (1 + 1j) * _SQRT13_6,
    4: (-1 - 1j) * _SQRT13_6, 8: (-1 - 1j) * _SQRT13_6,
    12: (1 + 1j) * _SQRT13_6, 16: (1 + 1j) * _SQRT13_6,
    20: (1 + 1j) * _SQRT13_6, 24: (1 + 1j) * _SQRT13_6,
}

_LTF_SEQ = [  # index -26..26, "802.11a Table L-6"-style long training sequence
    1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1,
    1, 1, 1, 1, 0, 1, -1, -1, 1, 1, -1, 1, -1, 1, -1, -1, -1, -1, -1, 1, 1,
    -1, -1, 1, -1, 1, -1, 1, 1, 1, 1,
]
_LTF_INDEX_VALUES = {i - 26: float(v) for i, v in enumerate(_LTF_SEQ) if v != 0}

_PILOT_OFFSETS = (-21, -7, 7, 21)  # 802.11a pilot subcarrier indices (default n_used=52)


def _map_index_values_to_bins(index_values: dict, n_fft: int) -> np.ndarray:
    """Frequency-domain array (FFT bin order) from an {index: value} map."""
    x = np.zeros(n_fft, dtype=np.complex128)
    for idx, val in index_values.items():
        x[idx % n_fft] = val
    return x


def _preamble_iq(n_fft: int, cp_len: int) -> np.ndarray:
    """802.11a-like PLCP preamble at the native rate (STF then LTF), complex128.

    Structurally generic in ``n_fft``/``cp_len`` (exact only for the
    standard ``n_fft=64`` case -- see module docstring).
    """
    x_stf = np.fft.ifft(_map_index_values_to_bins(_STF_INDEX_VALUES, n_fft))
    short_period = max(n_fft // 4, 1)
    stf = np.tile(x_stf[:short_period], 10)  # 10 x 0.8us = 8us

    x_ltf = np.fft.ifft(_map_index_values_to_bins(_LTF_INDEX_VALUES, n_fft))
    gi2 = 2 * cp_len
    ltf = np.concatenate([x_ltf[-gi2:], x_ltf, x_ltf])  # double GI + two long symbols

    return np.concatenate([stf, ltf])


def _used_and_pilot_indices(n_used: int) -> Tuple[np.ndarray, np.ndarray]:
    half = n_used // 2
    used = np.concatenate([np.arange(-half, 0), np.arange(1, half + 1)])
    if n_used == 52:
        pilots = np.array(_PILOT_OFFSETS)
    else:
        # Generic fallback: scale the standard pilot fractions to this band.
        pilots = np.round(np.array([o / 26.0 for o in _PILOT_OFFSETS]) * half).astype(int)
        pilots[pilots == 0] = 1
    return used, pilots


_QPSK_MAP = {(0, 0): -1 - 1j, (0, 1): -1 + 1j, (1, 0): 1 - 1j, (1, 1): 1 + 1j}
_QAM16_LEVELS = {(0, 0): -3.0, (0, 1): -1.0, (1, 1): 1.0, (1, 0): 3.0}  # Gray-coded PAM4


def _modulate_bits(bits: np.ndarray, mod: str) -> np.ndarray:
    if mod == "qpsk":
        pairs = bits.reshape(-1, 2)
        return np.array([_QPSK_MAP[(b0, b1)] for b0, b1 in pairs], dtype=complex) / np.sqrt(2.0)
    if mod == "16qam":
        quads = bits.reshape(-1, 4)
        out = np.empty(len(quads), dtype=complex)
        for i, (b0, b1, b2, b3) in enumerate(quads):
            out[i] = complex(_QAM16_LEVELS[(b0, b1)], _QAM16_LEVELS[(b2, b3)])
        return out / np.sqrt(10.0)
    raise ValueError(f"unknown mod {mod!r}; expected 'qpsk' or '16qam'")


def make_ofdm_burst(fs_hz: float, duration_s: float, *,
                     bw_hz: float = 20e6, n_fft: int = 64, n_used: int = 52,
                     cp_len: int = 16, mod: str = "qpsk", preamble: bool = True,
                     seed: int | None = None) -> np.ndarray:
    """Complex64 baseband IQ of a synthetic 802.11a/g-like OFDM burst.

    Generated at a native rate of ``bw_hz`` (default 20 MHz, matching the
    real 802.11a subcarrier spacing/CP numbers), then resampled to
    ``fs_hz`` with ``scipy.signal.resample_poly`` on an exact
    ``fractions.Fraction(fs_hz, bw_hz)`` ratio. RMS-normalised to 1 before
    return. See module docstring for the preamble-sequence evidence
    caveat and the (non-standard) fixed pilot / random-data-bit model.
    """
    if mod not in ("qpsk", "16qam"):
        raise ValueError(f"unknown mod {mod!r}; expected 'qpsk' or '16qam'")
    rng = np.random.default_rng(seed)
    symbol_len = n_fft + cp_len
    used_idx, pilot_idx = _used_and_pilot_indices(n_used)
    data_idx = np.array([i for i in used_idx if i not in set(pilot_idx.tolist())])
    bits_per_sym = (2 if mod == "qpsk" else 4)

    pre = _preamble_iq(n_fft, cp_len) if preamble else np.zeros(0, dtype=np.complex128)
    pre_dur = len(pre) / bw_hz
    remaining_s = max(duration_s - pre_dur, 0.0)
    n_syms = max(int(np.ceil(remaining_s * bw_hz / symbol_len)), 0)
    if not preamble and n_syms == 0:
        n_syms = 1

    data_syms = []
    for _ in range(n_syms):
        bits = rng.integers(0, 2, size=len(data_idx) * bits_per_sym, dtype=np.uint8)
        syms = _modulate_bits(bits, mod)
        x_freq = _map_index_values_to_bins(
            dict(zip(pilot_idx.tolist(), [1.0 + 0j] * len(pilot_idx))), n_fft)
        for idx, s in zip(data_idx.tolist(), syms):
            x_freq[idx % n_fft] = s
        x_time = np.fft.ifft(x_freq) * np.sqrt(n_fft)
        data_syms.append(np.concatenate([x_time[-cp_len:], x_time]))

    parts = [pre] + data_syms if preamble else data_syms
    iq_native = np.concatenate(parts) if parts else np.zeros(1, dtype=np.complex128)

    n_target_native = max(int(round(duration_s * bw_hz)), 1)
    if len(iq_native) < n_target_native:
        iq_native = np.concatenate([iq_native, np.zeros(n_target_native - len(iq_native), dtype=complex)])
    else:
        iq_native = iq_native[:n_target_native]

    ratio = Fraction(fs_hz / bw_hz).limit_denominator(1000)
    if ratio.numerator != ratio.denominator:
        iq_out = resample_poly(iq_native, ratio.numerator, ratio.denominator)
    else:
        iq_out = iq_native

    rms = float(np.sqrt(np.mean(np.abs(iq_out) ** 2))) or 1.0
    iq_out = iq_out / rms
    return iq_out.astype(np.complex64)


def make_wifi_like_scene(fs_hz: float, window_s: float, *,
                          center_offsets_hz: Sequence[float] = (0.0,),
                          beacon_period_s: float = 0.1024,
                          beacon_len_s: float = 200e-6,
                          data_burst_lens_s: Tuple[float, float] = (100e-6, 2e-3),
                          duty: float = 0.2,
                          snr_db: float | None = None,
                          noise: bool = True,
                          seed: int | None = None,
                          ) -> Tuple[np.ndarray, List[Tuple[float, float, float, str]]]:
    """Composite Wi-Fi-like scene: beacon-cadence + random data OFMD bursts.

    Places synthetic ``make_ofdm_burst`` bursts on each of
    ``center_offsets_hz`` inside a ``window_s`` window sampled at
    ``fs_hz``: one periodic "beacon" burst every ``beacon_period_s``
    (default 102.4 ms = 100 TU, the real Wi-Fi beacon interval convention)
    of length ``beacon_len_s``, plus randomly-placed, randomly-sized
    "data" bursts (non-overlapping, lengths drawn uniformly from
    ``data_burst_lens_s``) up to an approximate ``duty`` fraction of the
    window. Returns ``(iq, events)`` where ``events`` is a list of
    ``(t_start_s, t_end_s, centre_offset_hz, kind)`` truth records sorted
    by start time, ``kind`` in ``{"beacon", "data"}``.

    Noise: if ``noise`` is True, complex AWGN is added; sized to
    ``snr_db`` relative to the mean power of the occupied (nonzero)
    samples if given, else a small fixed floor (rms 0.01 of the occupied
    signal rms) is used.
    """
    rng = np.random.default_rng(seed)
    n = max(int(round(window_s * fs_hz)), 1)
    iq = np.zeros(n, dtype=np.complex128)
    events: List[Tuple[float, float, float, str]] = []

    for offset in center_offsets_hz:
        ch_seed = int(rng.integers(0, 2**32 - 1))
        ch_rng = np.random.default_rng(ch_seed)
        ch_events: List[Tuple[float, float, float, str]] = []

        phase0 = float(ch_rng.uniform(0.0, beacon_period_s))
        t = phase0
        while t + beacon_len_s <= window_s:
            ch_events.append((t, t + beacon_len_s, offset, "beacon"))
            t += beacon_period_s

        budget = duty * window_s
        total_data = 0.0
        for _ in range(2000):
            if total_data >= budget:
                break
            length = float(ch_rng.uniform(*data_burst_lens_s))
            span = max(window_s - length, 0.0)
            start = float(ch_rng.uniform(0.0, span)) if span > 0 else 0.0
            end = start + length
            if any(not (end <= es or start >= ee) for es, ee, _, _ in ch_events):
                continue
            ch_events.append((start, end, offset, "data"))
            total_data += length

        for (t_start, t_end, off, kind) in ch_events:
            length_s = t_end - t_start
            burst_seed = int(ch_rng.integers(0, 2**32 - 1))
            burst = make_ofdm_burst(fs_hz, length_s, seed=burst_seed)
            n_ev = min(len(burst), n - max(int(round(t_start * fs_hz)), 0))
            i0 = int(round(t_start * fs_hz))
            if n_ev <= 0 or i0 >= n:
                continue
            t_local = np.arange(n_ev) / fs_hz
            rot = np.exp(1j * 2.0 * np.pi * off * t_local)
            iq[i0:i0 + n_ev] += (burst[:n_ev] * rot)

        events.extend(ch_events)

    if noise:
        active = np.abs(iq) > 0
        sig_power = float(np.mean(np.abs(iq[active]) ** 2)) if np.any(active) else 1.0
        if snr_db is not None:
            noise_power = sig_power / (10.0 ** (snr_db / 10.0))
        else:
            noise_power = (0.01 ** 2) * sig_power
        sigma = np.sqrt(max(noise_power, 1e-18) / 2.0)
        iq = iq + sigma * (rng.standard_normal(n) + 1j * rng.standard_normal(n))

    events.sort(key=lambda e: e[0])
    return iq.astype(np.complex64), events


def _gaussian_fir_unit_dc(bt: float, rate_bps: float, fs_fine: float, span: float = 4.0) -> np.ndarray:
    """Unit-DC-gain Gaussian FIR, -3 dB bandwidth = bt*rate_bps, at fs_fine."""
    bw_hz = bt * rate_bps
    sigma_t = np.sqrt(np.log(2.0)) / (2.0 * np.pi * bw_hz)
    ntaps = int(np.ceil(2 * span * sigma_t * fs_fine))
    ntaps += 1 - (ntaps % 2)
    ntaps = max(ntaps, 3)
    n = np.arange(ntaps) - ntaps // 2
    taps = np.exp(-0.5 * (n / (fs_fine * sigma_t)) ** 2)
    return taps / taps.sum()


def _gfsk_iq(bits: np.ndarray, rate_bps: float, deviation_hz: float, bt: float,
             fs: float, fine_oversample: int = 32) -> np.ndarray:
    """~20-line "Gaussian-filtered NRZ -> FM" GFSK modulator (self-contained;
    same technique as aerix_rf.decode.sik.synth, reimplemented locally so
    this module does not import from aerix_rf.decode)."""
    a_k = np.where(bits, 1.0, -1.0)
    fs_fine = fine_oversample * rate_bps
    nrz_fine = np.repeat(a_k, fine_oversample)
    taps = _gaussian_fir_unit_dc(bt, rate_bps, fs_fine)
    freq_fine = np.convolve(nrz_fine, taps, mode="same") * deviation_hz
    t_fine = np.arange(len(freq_fine)) / fs_fine
    duration_s = len(bits) / rate_bps
    n_out = max(int(round(duration_s * fs)), 1)
    t_out = np.arange(n_out) / fs
    freq_out = np.interp(t_out, t_fine, freq_fine, left=freq_fine[0], right=freq_fine[-1])
    phase = 2.0 * np.pi * np.cumsum(freq_out) / fs
    return np.exp(1j * phase).astype(np.complex64)


_BLE_ACCESS_ADDR = 0x8E89BED6  # standard BLE advertising-channel access address
# (Bluetooth Core Spec Vol 6 Part B S2.1.2); transcribed from memory, NOT
# independently verified in this task, and not used for any correlation/
# sync logic here -- it only shapes the bit sequence fed to the modulator.


def _ble_packet_bits(payload_bits: int, rng: np.random.Generator) -> np.ndarray:
    preamble = np.resize(np.array([1, 0], dtype=np.uint8), 8)  # 0xAA-style alternating
    aa_bits = np.array([(_BLE_ACCESS_ADDR >> i) & 1 for i in range(31, -1, -1)], dtype=np.uint8)
    payload = rng.integers(0, 2, size=max(payload_bits, 0), dtype=np.uint8)
    return np.concatenate([preamble, aa_bits, payload])


def make_ble_like_scene(fs_hz: float, window_s: float, *,
                         n_channels: int = 37,
                         channel_spacing_hz: float = 2e6,
                         conn_interval_s: float = 7.5e-3,
                         packet_lens_s: Tuple[float, float] = (150e-6, 400e-6),
                         rate_bps: float = 1e6,
                         deviation_hz: float = 250e3,
                         bt: float = 0.5,
                         snr_db: float | None = None,
                         noise: bool = True,
                         seed: int | None = None,
                         ) -> Tuple[np.ndarray, List[Tuple[float, float, float, str]]]:
    """Composite BLE-like scene: 1 Mb/s GFSK packets on a 2 MHz channel raster.

    ``n_channels`` channels (default 37, the BLE data-channel count) are
    placed on a ``channel_spacing_hz`` raster centred at baseband 0 (this
    is a baseband/IF placement, not the real absolute 2402 MHz BLE band).
    Each channel gets periodic packets at ``conn_interval_s`` cadence
    (default 7.5 ms), random length drawn from ``packet_lens_s``. Returns
    ``(iq, events)`` with events ``(t_start_s, t_end_s, centre_offset_hz,
    "ble_packet")`` sorted by start time. See module docstring for the
    GFSK model and access-address provenance caveat.
    """
    rng = np.random.default_rng(seed)
    n = max(int(round(window_s * fs_hz)), 1)
    iq = np.zeros(n, dtype=np.complex128)
    events: List[Tuple[float, float, float, str]] = []
    half = n_channels // 2
    offsets = (np.arange(n_channels) - half) * channel_spacing_hz

    for offset in offsets:
        ch_seed = int(rng.integers(0, 2**32 - 1))
        ch_rng = np.random.default_rng(ch_seed)
        phase0 = float(ch_rng.uniform(0.0, conn_interval_s))
        t = phase0
        while t < window_s:
            length = float(ch_rng.uniform(*packet_lens_s))
            t_end = min(t + length, window_s)
            if t_end > t:
                n_bits = max(int(round((t_end - t) * rate_bps)), 8)
                bits = _ble_packet_bits(n_bits - 40, ch_rng)  # 40 = preamble+access-addr
                pkt = _gfsk_iq(bits, rate_bps, deviation_hz, bt, fs_hz)
                i0 = int(round(t * fs_hz))
                n_ev = min(len(pkt), n - i0)
                if n_ev > 0 and i0 < n:
                    t_local = np.arange(n_ev) / fs_hz
                    rot = np.exp(1j * 2.0 * np.pi * float(offset) * t_local)
                    iq[i0:i0 + n_ev] += pkt[:n_ev] * rot
                    events.append((t, t + n_ev / fs_hz, float(offset), "ble_packet"))
            t += conn_interval_s

    if noise:
        active = np.abs(iq) > 0
        sig_power = float(np.mean(np.abs(iq[active]) ** 2)) if np.any(active) else 1.0
        if snr_db is not None:
            noise_power = sig_power / (10.0 ** (snr_db / 10.0))
        else:
            noise_power = (0.01 ** 2) * sig_power
        sigma = np.sqrt(max(noise_power, 1e-18) / 2.0)
        iq = iq + sigma * (rng.standard_normal(n) + 1j * rng.standard_normal(n))

    events.sort(key=lambda e: e[0])
    return iq.astype(np.complex64), events
