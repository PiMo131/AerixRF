"""Synthetic RF emitters and scene composition for testing without hardware.

The generators below produce complex baseband IQ (``np.complex64``) at unit
average power (``mean(|x|^2) == 1``) unless stated otherwise, so that a
:class:`Scene` can scale them to a requested in-band SNR.  They are
stand-ins for the waveform *families* seen in drone links, not
bit-accurate implementations:

* :func:`bandlimited_noise_burst` - OFDM-like flat burst (OcuSync, Wi-Fi, ...)
* :func:`lora_chirps`             - LoRa CSS up-chirps (long-range telemetry)
* :func:`fm_video_like`           - wideband analog FM (analog FPV video)
* :func:`gfsk_burst`              - GFSK (SiK, FrSky, ELRS-like FSK links)

Conventions: sample rates / frequencies in Hz, times in seconds, powers in
dB relative to full scale 1.0.  Frequency offsets are relative to the scene
centre; :meth:`Scene.truth_bursts` reports absolute Hz.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import ndimage, special

from .base import SampleSource, StreamInfo

__all__ = [
    "awgn",
    "bandlimited_noise_burst",
    "lora_chirps",
    "fm_video_like",
    "gfsk_burst",
    "occupied_bandwidth_hz",
    "instantaneous_frequency_hz",
    "Emission",
    "Scene",
    "SyntheticSource",
]

_TWO_PI = 2.0 * math.pi


# --------------------------------------------------------------------------- helpers


def _unit_power(x: np.ndarray) -> np.ndarray:
    """Scale ``x`` to ``mean(|x|^2) == 1`` and return it as complex64."""
    x = np.asarray(x, dtype=np.complex128)
    p = float(np.mean(x.real * x.real + x.imag * x.imag))
    if p > 0.0:
        x = x / math.sqrt(p)
    return x.astype(np.complex64)


def _apply_ramps(x: np.ndarray, n_ramp: int) -> np.ndarray:
    """Multiply the first/last ``n_ramp`` samples by raised-cosine rise/fall ramps.

    Emulates PA ramp-up/down and keeps burst edges from splattering across
    the whole band.  No-op when the burst is too short for two ramps.
    """
    n_ramp = int(n_ramp)
    if n_ramp <= 1 or 2 * n_ramp > len(x):
        return x
    ramp = 0.5 * (1.0 - np.cos(np.pi * (np.arange(n_ramp) + 0.5) / n_ramp))
    x = np.array(x, copy=True)
    x[:n_ramp] *= ramp
    x[-n_ramp:] *= ramp[::-1]
    return x


def _phase_to_iq(freq_hz: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    """Integrate an instantaneous-frequency trajectory (Hz) into a unit-envelope IQ signal."""
    cycles = np.cumsum(np.asarray(freq_hz, dtype=np.float64)) / float(sample_rate_hz)
    cycles -= np.floor(cycles)  # keep the argument small for float precision
    return np.exp(1j * _TWO_PI * cycles).astype(np.complex64)


def instantaneous_frequency_hz(x: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    """Instantaneous frequency (Hz) from the unwrapped phase difference; length ``n-1``."""
    phase = np.unwrap(np.angle(np.asarray(x, dtype=np.complex128)))
    return np.diff(phase) * float(sample_rate_hz) / _TWO_PI


def occupied_bandwidth_hz(
    x: np.ndarray, sample_rate_hz: float, *, fraction: float = 0.99, nfft: int = 4096
) -> float:
    """Occupied bandwidth containing ``fraction`` of the signal energy (ITU-style OBW).

    The spectrum is an averaged Hann periodogram of ``min(nfft, len(x))``
    points; equal tails of ``(1 - fraction) / 2`` are excluded on each side.
    Resolution (and the minimum result) is one bin, ``fs / nfft``.
    """
    x = np.asarray(x, dtype=np.complex64).ravel()
    n = len(x)
    if n == 0:
        raise ValueError("cannot estimate the bandwidth of an empty signal")
    nfft = int(min(nfft, n))
    n_seg = n // nfft
    w = 0.5 - 0.5 * np.cos(_TWO_PI * np.arange(nfft) / nfft)
    seg = x[: n_seg * nfft].reshape(n_seg, nfft) * w
    spec = np.fft.fft(seg, axis=-1)
    p = np.fft.fftshift((spec.real**2 + spec.imag**2).mean(axis=0).astype(np.float64))
    total = p.sum()
    if total <= 0.0:
        raise ValueError("cannot estimate the bandwidth of an all-zero signal")
    cum = np.cumsum(p) / total
    tail = (1.0 - float(fraction)) / 2.0
    lo = int(np.searchsorted(cum, tail, side="left"))
    hi = int(np.searchsorted(cum, 1.0 - tail, side="left"))
    return max(hi - lo + 1, 1) * float(sample_rate_hz) / nfft


# --------------------------------------------------------------------------- generators


def awgn(n: int, rng: np.random.Generator, power_db: float = 0.0) -> np.ndarray:
    """Circularly-symmetric complex Gaussian noise with total power ``power_db`` (dBFS)."""
    n = int(n)
    if n < 0:
        raise ValueError("n must be >= 0")
    scale = np.float32(math.sqrt(10.0 ** (power_db / 10.0) / 2.0))
    re = rng.standard_normal(n, dtype=np.float32)
    im = rng.standard_normal(n, dtype=np.float32)
    return (re * scale + 1j * (im * scale)).astype(np.complex64)


def bandlimited_noise_burst(
    sample_rate_hz: float,
    bandwidth_hz: float,
    duration_s: float,
    rng: np.random.Generator,
    *,
    transition_fraction: float = 0.04,
    ramp_samples: int = 64,
) -> np.ndarray:
    """OFDM-like burst: Gaussian noise with a flat spectrum inside ``bandwidth_hz``.

    Shaping is done in the FFT domain: unity inside the band, a raised-cosine
    roll-off over the outer ``transition_fraction`` of the bandwidth (inside
    the nominal edges) and zero outside, so essentially all energy stays
    within ``bandwidth_hz``.  Short raised-cosine time ramps soften the burst
    edges.  Unit average power.
    """
    fs = float(sample_rate_hz)
    bw = float(bandwidth_hz)
    n = int(round(float(duration_s) * fs))
    if n <= 0:
        raise ValueError("duration_s * sample_rate_hz must round to >= 1 sample")
    if bw <= 0.0:
        raise ValueError("bandwidth_hz must be > 0")
    x = awgn(n, rng).astype(np.complex128)
    if bw < fs and n >= 8:
        f_abs = np.abs(np.fft.fftfreq(n, d=1.0 / fs))
        half = bw / 2.0
        tr = max(float(transition_fraction) * bw, 2.0 * fs / n)
        inner = max(half - tr, 0.0)
        mask = np.zeros(n)
        mask[f_abs <= inner] = 1.0
        edge = (f_abs > inner) & (f_abs <= half)
        mask[edge] = 0.5 * (1.0 + np.cos(np.pi * (f_abs[edge] - inner) / (half - inner)))
        x = np.fft.ifft(np.fft.fft(x) * mask)
    x = _apply_ramps(x, min(int(ramp_samples), n // 10))
    return _unit_power(x)


def lora_chirps(
    sample_rate_hz: float,
    bandwidth_hz: float,
    spreading_factor: int,
    n_symbols: int,
    rng: np.random.Generator,
    symbols: Sequence[int] | None = None,
) -> np.ndarray:
    """LoRa-style chirp-spread-spectrum symbols (up-chirps with cyclic shifts).

    A symbol lasts ``2**SF / bandwidth_hz`` seconds, during which the
    instantaneous frequency sweeps linearly from ``-bw/2`` to ``+bw/2``;
    symbol value ``s`` (``0 <= s < 2**SF``) starts the sweep at
    ``-bw/2 + bw * s / 2**SF`` and wraps once.  The phase is integrated
    directly on the output sample grid, which equals the standard
    ``2**SF``-chips-per-symbol sequence resampled to ``sample_rate_hz``
    (identical when ``sample_rate_hz == bandwidth_hz``).  Constant envelope,
    unit power.  Random symbols are drawn from ``rng`` unless given.
    """
    fs = float(sample_rate_hz)
    bw = float(bandwidth_hz)
    sf = int(spreading_factor)
    if sf < 1:
        raise ValueError("spreading_factor must be >= 1")
    if fs < bw:
        raise ValueError("sample_rate_hz must be >= bandwidth_hz to represent the chirp")
    n_chips = 2**sf
    if symbols is None:
        sym = rng.integers(0, n_chips, size=int(n_symbols))
    else:
        sym = np.asarray(symbols, dtype=np.int64)
        if sym.shape != (int(n_symbols),):
            raise ValueError("symbols must have length n_symbols")
        if np.any((sym < 0) | (sym >= n_chips)):
            raise ValueError(f"symbols must lie in [0, {n_chips})")
    t_symbol = n_chips / bw
    n = int(round(int(n_symbols) * t_symbol * fs))
    t = np.arange(n, dtype=np.float64) / fs
    k = np.minimum((t / t_symbol).astype(np.int64), int(n_symbols) - 1)
    tau = t - k * t_symbol
    frac = np.mod(sym[k] / n_chips + tau / t_symbol, 1.0)
    freq = -bw / 2.0 + bw * frac
    return _phase_to_iq(freq, fs)


def fm_video_like(
    sample_rate_hz: float,
    duration_s: float,
    rng: np.random.Generator,
    deviation_hz: float = 6e6,
    baseband_bw_hz: float = 6e6,
) -> np.ndarray:
    """Continuous wideband FM of low-pass noise: an analog FPV video stand-in.

    The message is Gaussian noise low-passed to ``baseband_bw_hz`` and then
    mapped through the Gaussian CDF so its amplitude is uniform on (-1, 1);
    the instantaneous frequency therefore fills ``+-deviation_hz`` evenly,
    like a video signal driving the full deviation range.  By Carson's rule
    the occupied bandwidth is roughly ``2 * (deviation_hz + baseband_bw_hz)``
    and the caller must choose ``sample_rate_hz`` at least that large to
    avoid aliasing.  Constant envelope, unit power.
    """
    fs = float(sample_rate_hz)
    n = int(round(float(duration_s) * fs))
    if n <= 0:
        raise ValueError("duration_s * sample_rate_hz must round to >= 1 sample")
    m = rng.standard_normal(n)
    if 0.0 < float(baseband_bw_hz) < fs / 2.0 and n >= 8:
        f = np.fft.rfftfreq(n, d=1.0 / fs)
        m = np.fft.irfft(np.fft.rfft(m) * (f <= float(baseband_bw_hz)), n)
    sigma = float(np.std(m))
    if sigma > 0.0:
        m = special.erf(m / (sigma * math.sqrt(2.0)))  # ~uniform on (-1, 1)
    return _phase_to_iq(float(deviation_hz) * m, fs)


def gfsk_burst(
    sample_rate_hz: float,
    symbol_rate_hz: float,
    n_bits: int,
    rng: np.random.Generator,
    modulation_index: float = 0.5,
    bt: float = 0.5,
    *,
    bits: Sequence[int] | None = None,
) -> np.ndarray:
    """Gaussian-filtered FSK burst (SiK / FrSky / ELRS-like telemetry links).

    Bits (random unless ``bits`` is given) are mapped to NRZ +-1 at
    ``symbol_rate_hz``, smoothed by a Gaussian filter with bandwidth
    ``bt * symbol_rate_hz`` and used as instantaneous frequency with peak
    deviation ``modulation_index * symbol_rate_hz / 2``.  Non-integer
    samples-per-symbol ratios are supported (symbol boundaries are placed
    on the nearest sample).  One-symbol raised-cosine ramps are applied at
    both ends; unit power.
    """
    fs = float(sample_rate_hz)
    rs = float(symbol_rate_hz)
    n_bits = int(n_bits)
    if rs <= 0.0 or fs < 2.0 * rs:
        raise ValueError("need sample_rate_hz >= 2 * symbol_rate_hz > 0")
    if n_bits <= 0:
        raise ValueError("n_bits must be >= 1")
    if bits is None:
        b = rng.integers(0, 2, size=n_bits)
    else:
        b = np.asarray(bits, dtype=np.int64)
        if b.shape != (n_bits,):
            raise ValueError("bits must have length n_bits")
    sps = fs / rs
    n = int(round(n_bits * sps))
    idx = np.minimum((np.arange(n) / sps).astype(np.int64), n_bits - 1)
    nrz = (2.0 * b[idx] - 1.0).astype(np.float64)
    if float(bt) > 0.0:
        sigma = math.sqrt(math.log(2.0)) / (_TWO_PI * float(bt) * rs) * fs  # samples
        nrz = ndimage.gaussian_filter1d(nrz, sigma, mode="nearest")
    freq = float(modulation_index) * rs / 2.0 * nrz
    x = _apply_ramps(_phase_to_iq(freq, fs), int(round(sps)))
    return _unit_power(x)


# --------------------------------------------------------------------------- scene


@dataclass
class Emission:
    """Ground truth for one signal added to a :class:`Scene`.

    ``samples`` is the actual contribution to the scene: scaled to the
    requested SNR, mixed to ``freq_offset_hz`` and cropped to the scene
    bounds, starting at scene time ``t_start_s``.  ``bandwidth_hz`` is the
    occupied bandwidth used to define the in-band SNR.
    """

    t_start_s: float
    freq_offset_hz: float
    samples: np.ndarray
    label: str
    snr_db: float
    t_end_s: float = 0.0
    bandwidth_hz: float = 0.0
    scale: float = 1.0

    @property
    def duration_s(self) -> float:
        return self.t_end_s - self.t_start_s


class Scene:
    """Compose emissions on top of white noise at a fixed sample rate and centre.

    ``noise_power_db`` is the *total* noise power (dBFS) over the sample
    rate, i.e. the noise PSD is ``10**(noise_power_db/10) / sample_rate_hz``
    per Hz.  Each emission is scaled so that its average in-band PSD (power
    divided by its occupied bandwidth) sits ``snr_db`` above that noise PSD -
    the SNR a spectrogram cell inside the signal shows, independent of FFT
    size.  Rendering is deterministic for a given seeded ``rng``.
    """

    def __init__(
        self,
        sample_rate_hz: float,
        center_freq_hz: float,
        duration_s: float,
        rng: np.random.Generator,
        noise_power_db: float = -60.0,
    ) -> None:
        self.sample_rate_hz = float(sample_rate_hz)
        self.center_freq_hz = float(center_freq_hz)
        self.noise_power_db = float(noise_power_db)
        self.n_samples = int(round(float(duration_s) * self.sample_rate_hz))
        if self.n_samples <= 0:
            raise ValueError("duration_s * sample_rate_hz must round to >= 1 sample")
        self.duration_s = self.n_samples / self.sample_rate_hz
        self._rng = rng
        self._noise_seed = int(rng.integers(0, np.iinfo(np.int64).max))
        self._signal = np.zeros(self.n_samples, dtype=np.complex64)
        self.emissions: list[Emission] = []

    @property
    def noise_psd(self) -> float:
        """Linear noise power spectral density (full-scale^2 per Hz)."""
        return 10.0 ** (self.noise_power_db / 10.0) / self.sample_rate_hz

    def add(
        self,
        samples: np.ndarray,
        *,
        t_start_s: float,
        freq_offset_hz: float,
        snr_db: float,
        label: str,
        bandwidth_hz: float | None = None,
    ) -> Emission:
        """Mix ``samples`` to ``freq_offset_hz`` at ``t_start_s`` and add them at ``snr_db``.

        ``bandwidth_hz`` overrides the 99 % occupied bandwidth estimated from
        ``samples`` when defining the in-band SNR.  Parts of the emission
        outside the scene duration are clipped; an emission entirely outside
        the scene or a carrier offset beyond ``+-fs/2`` raises ``ValueError``.
        """
        fs = self.sample_rate_hz
        x = np.asarray(samples, dtype=np.complex64).ravel()
        if len(x) == 0:
            raise ValueError("samples must not be empty")
        if abs(float(freq_offset_hz)) > fs / 2.0:
            raise ValueError("freq_offset_hz must lie within +-sample_rate_hz/2")
        p_in = float(np.mean(x.real.astype(np.float64) ** 2 + x.imag.astype(np.float64) ** 2))
        if p_in <= 0.0:
            raise ValueError("samples must carry non-zero power")
        bw = float(bandwidth_hz) if bandwidth_hz is not None else occupied_bandwidth_hz(x, fs)
        p_target = 10.0 ** (float(snr_db) / 10.0) * self.noise_psd * bw
        scale = math.sqrt(p_target / p_in)

        start = int(round(float(t_start_s) * fs))
        s0, s1 = max(start, 0), min(start + len(x), self.n_samples)
        if s1 <= s0:
            raise ValueError("emission lies entirely outside the scene")
        idx = np.arange(s0, s1, dtype=np.float64)
        cycles = np.mod(idx * (float(freq_offset_hz) / fs), 1.0)
        mixed = (x[s0 - start : s1 - start].astype(np.complex128) * scale) * np.exp(
            1j * _TWO_PI * cycles
        )
        mixed = mixed.astype(np.complex64)
        self._signal[s0:s1] += mixed
        emission = Emission(
            t_start_s=s0 / fs,
            freq_offset_hz=float(freq_offset_hz),
            samples=mixed,
            label=str(label),
            snr_db=float(snr_db),
            t_end_s=s1 / fs,
            bandwidth_hz=bw,
            scale=scale,
        )
        self.emissions.append(emission)
        return emission

    def fhss(
        self,
        samples_fn: Callable[..., np.ndarray],
        *,
        channels_hz: Sequence[float],
        hop_rate_hz: float,
        burst_duration_s: float,
        t_start_s: float,
        t_end_s: float,
        snr_db: float,
        label: str,
        order: str = "random",
    ) -> list[Emission]:
        """Add a frequency-hopping sequence of bursts; returns the emissions added.

        Hops start every ``1 / hop_rate_hz`` seconds from ``t_start_s`` while
        the start time is before ``t_end_s``.  ``samples_fn`` generates each
        burst: it is called as ``samples_fn(burst_duration_s)`` if it accepts
        an argument, else as ``samples_fn()``; output longer than
        ``burst_duration_s`` is truncated.  ``channels_hz`` are offsets from
        the scene centre, visited cyclically (``order="sequential"``) or drawn
        uniformly from the scene ``rng`` (``order="random"``).
        """
        if order not in ("random", "sequential"):
            raise ValueError("order must be 'random' or 'sequential'")
        channels = [float(c) for c in channels_hz]
        if not channels:
            raise ValueError("channels_hz must not be empty")
        if float(hop_rate_hz) <= 0.0:
            raise ValueError("hop_rate_hz must be > 0")
        try:
            takes_duration = bool(inspect.signature(samples_fn).parameters)
        except (TypeError, ValueError):  # callables without an introspectable signature
            takes_duration = False
        period = 1.0 / float(hop_rate_hz)
        n_burst = max(1, int(round(float(burst_duration_s) * self.sample_rate_hz)))
        n_hops = int(math.ceil((float(t_end_s) - float(t_start_s)) / period - 1e-9))
        added: list[Emission] = []
        for k in range(max(n_hops, 0)):
            t = float(t_start_s) + k * period
            if t >= self.duration_s:
                break
            if order == "sequential":
                offset = channels[k % len(channels)]
            else:
                offset = channels[int(self._rng.integers(len(channels)))]
            burst = samples_fn(float(burst_duration_s)) if takes_duration else samples_fn()
            burst = np.asarray(burst, dtype=np.complex64).ravel()[:n_burst]
            added.append(
                self.add(burst, t_start_s=t, freq_offset_hz=offset, snr_db=snr_db, label=label)
            )
        return added

    def render(self) -> np.ndarray:
        """Return noise + all emissions as complex64 of length ``n_samples``."""
        noise = awgn(self.n_samples, np.random.default_rng(self._noise_seed), self.noise_power_db)
        return (noise + self._signal).astype(np.complex64)

    def truth_bursts(self) -> list[dict]:
        """Ground-truth boxes: ``t_start_s, t_end_s, f_low_hz, f_high_hz`` (absolute), ``label``."""
        fc, fs = self.center_freq_hz, self.sample_rate_hz
        out = []
        for e in self.emissions:
            out.append(
                {
                    "t_start_s": e.t_start_s,
                    "t_end_s": e.t_end_s,
                    "f_low_hz": max(fc + e.freq_offset_hz - e.bandwidth_hz / 2.0, fc - fs / 2.0),
                    "f_high_hz": min(fc + e.freq_offset_hz + e.bandwidth_hz / 2.0, fc + fs / 2.0),
                    "label": e.label,
                }
            )
        return out


# --------------------------------------------------------------------------- source


class SyntheticSource(SampleSource):
    """A :class:`SampleSource` that replays an in-memory IQ array (e.g. a rendered scene).

    ``read`` returns consecutive chunks (copies), fewer samples at the end
    and an empty array once exhausted; with ``loop=True`` the buffer repeats
    forever.  ``retune`` is not supported (the scene is rendered at a fixed
    centre) and raises ``NotImplementedError`` from the base class.
    """

    def __init__(
        self,
        samples: np.ndarray,
        info: StreamInfo,
        *,
        loop: bool = False,
        scene: Scene | None = None,
    ) -> None:
        self._samples = np.ascontiguousarray(samples, dtype=np.complex64)
        self._info = info
        self._loop = bool(loop)
        self._pos = 0
        self._closed = False
        self.scene = scene

    @classmethod
    def from_scene(
        cls, scene: Scene, *, loop: bool = False, description: str = ""
    ) -> SyntheticSource:
        """Render ``scene`` and wrap it with a matching ``StreamInfo(hardware="synthetic")``."""
        info = StreamInfo(
            sample_rate_hz=scene.sample_rate_hz,
            center_freq_hz=scene.center_freq_hz,
            hardware="synthetic",
            description=description or f"synthetic scene, {len(scene.emissions)} emissions",
        )
        return cls(scene.render(), info, loop=loop, scene=scene)

    @property
    def info(self) -> StreamInfo:
        return self._info

    @property
    def n_samples(self) -> int:
        return len(self._samples)

    @property
    def position(self) -> int:
        """Index of the next sample to be returned (modulo the buffer length when looping)."""
        return self._pos

    def reset(self) -> None:
        self._pos = 0

    def read(self, n_samples: int) -> np.ndarray:
        n = int(n_samples)
        if n < 0:
            raise ValueError("n_samples must be >= 0")
        if self._closed:
            raise RuntimeError("SyntheticSource is closed")
        total = len(self._samples)
        if self._loop and total > 0:
            idx = (np.arange(self._pos, self._pos + n) % total).astype(np.intp)
            self._pos = (self._pos + n) % total
            return self._samples[idx]
        out = self._samples[self._pos : self._pos + n].copy()
        self._pos += len(out)
        return out

    def close(self) -> None:
        self._closed = True
