"""Tests for antsdr_toolkit.dsp.spectrum (STFT power, Welch PSD, noise floor)."""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.dsp import spectrum as sp

FS = 10e6
FC = 2.4e9


def _complex_noise(rng: np.random.Generator, n: int, power: float = 1.0) -> np.ndarray:
    """Circular complex Gaussian noise with total power ``power``."""
    x = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    return (x * np.sqrt(power / 2.0)).astype(np.complex64)


def _tone(n: int, freq_hz: float, fs: float, amplitude: float = 1.0) -> np.ndarray:
    t = np.arange(n) / fs
    return (amplitude * np.exp(2j * np.pi * freq_hz * t)).astype(np.complex64)


# --------------------------------------------------------------------------- db helpers


def test_db_helpers_floor_and_values():
    assert sp.db(1.0) == pytest.approx(0.0)
    assert sp.db(100.0) == pytest.approx(20.0)
    assert np.isfinite(sp.db(0.0))
    assert sp.db(0.0) == pytest.approx(-200.0)
    assert sp.db_amplitude(1.0) == pytest.approx(0.0)
    assert sp.db_amplitude(10.0) == pytest.approx(20.0)
    assert sp.db_amplitude(1j) == pytest.approx(0.0)
    assert np.isfinite(sp.db_amplitude(0.0))
    # dtype preserved for float32 maps (memory-friendly spectrograms)
    assert sp.db(np.ones(4, dtype=np.float32)).dtype == np.float32
    assert sp.db(np.ones(4, dtype=np.int64)).dtype == np.float64


def test_fft_freqs_hz_absolute_ascending():
    f = sp.fft_freqs_hz(1024, FS, FC)
    assert f.shape == (1024,)
    assert np.all(np.diff(f) > 0)
    assert f[0] == pytest.approx(FC - FS / 2)
    assert f[512] == pytest.approx(FC)
    assert f[-1] == pytest.approx(FC + FS / 2 - FS / 1024)


# --------------------------------------------------------------------------- STFT


def test_stft_axes_are_absolute_ascending_and_tone_reads_0_db():
    fft_size = 1000  # 10 kHz bins: a +1 MHz tone lands exactly on bin +100
    n = 20_000
    x = _tone(n, 1e6, FS)
    power_db, freqs_hz, times_s = sp.stft_power_db(x, FS, FC, fft_size=fft_size)

    hop = fft_size // 2
    n_frames = 1 + (n - fft_size) // hop
    assert power_db.shape == (n_frames, fft_size)
    assert power_db.dtype == np.float32
    assert freqs_hz.shape == (fft_size,)
    assert times_s.shape == (n_frames,)

    # absolute, monotonically increasing frequency axis spanning fc +- fs/2
    assert np.all(np.diff(freqs_hz) > 0)
    assert freqs_hz[0] == pytest.approx(FC - FS / 2)
    assert freqs_hz[fft_size // 2] == pytest.approx(FC)
    # frame centres in seconds
    assert np.all(np.diff(times_s) > 0)
    assert times_s[0] == pytest.approx(fft_size / 2 / FS)
    assert times_s[1] - times_s[0] == pytest.approx(hop / FS)

    # the tone peaks at centre + 1 MHz and reads ~0 dB in every frame
    peak_bins = np.argmax(power_db, axis=1)
    assert np.all(freqs_hz[peak_bins] == pytest.approx(FC + 1e6))
    peak_db = power_db[np.arange(n_frames), peak_bins]
    assert np.all(np.abs(peak_db) < 0.1)
    # and is far above the (zero) background at other bins
    assert np.median(power_db) < -100


def test_stft_amplitude_scaling_and_hop():
    x = _tone(8192, 0.0, FS, amplitude=0.1)  # -20 dB tone at DC
    power_db, freqs_hz, times_s = sp.stft_power_db(x, FS, FC, fft_size=256, hop=256)
    assert power_db.shape == (8192 // 256, 256)
    assert times_s[1] - times_s[0] == pytest.approx(256 / FS)
    dc = np.argmin(np.abs(freqs_hz - FC))
    assert power_db[:, dc] == pytest.approx(-20.0, abs=0.05)


def test_stft_short_input_is_padded_to_one_frame_and_channels_averaged():
    x = _tone(100, 0.0, FS)
    power_db, _, times_s = sp.stft_power_db(x, FS, FC, fft_size=256)
    assert power_db.shape == (1, 256)
    assert times_s.shape == (1,)

    # two channels: one carries the tone, one is silent -> linear average = -3 dB
    two = np.stack([_tone(2048, 0.0, FS), np.zeros(2048, np.complex64)])
    p2, f2, _ = sp.stft_power_db(two, FS, FC, fft_size=256)
    dc = np.argmin(np.abs(f2 - FC))
    assert p2[:, dc] == pytest.approx(-3.01, abs=0.05)

    with pytest.raises(ValueError):
        sp.stft_power_db(np.zeros((2, 2, 16), np.complex64), FS, FC)
    with pytest.raises(ValueError):
        sp.stft_power_db(x, FS, FC, fft_size=256, hop=0)


def test_stft_noise_level_matches_window_enbw():
    """White noise of total power P reads P * ENBW/N per bin (Hann ENBW = 1.5 bins)."""
    rng = np.random.default_rng(1)
    x = _complex_noise(rng, 200_000, power=1.0)
    power_db, _, _ = sp.stft_power_db(x, FS, FC, fft_size=1024)
    mean_lin = np.mean(10 ** (power_db.astype(np.float64) / 10))
    assert 10 * np.log10(mean_lin) == pytest.approx(10 * np.log10(1.5 / 1024), abs=0.3)


# --------------------------------------------------------------------------- Welch


def test_welch_white_noise_is_flat():
    rng = np.random.default_rng(2)
    x = _complex_noise(rng, 400_000, power=1.0)
    freqs_hz, psd_db = sp.welch_psd_db(x, 1e6, FC, nfft=1024)
    assert freqs_hz.shape == (1024,) and psd_db.shape == (1024,)
    assert np.all(np.diff(freqs_hz) > 0)
    assert freqs_hz[0] == pytest.approx(FC - 0.5e6)
    # flat within a few dB across the whole band ...
    assert psd_db.max() - psd_db.min() < 3.0
    # ... at the level predicted by the Hann ENBW for a 0 dB total
    assert psd_db.mean() == pytest.approx(10 * np.log10(1.5 / 1024), abs=0.5)


def test_welch_tone_reads_0_db_and_density_scaling():
    x = _tone(65_536, 1e6, FS)
    freqs_hz, psd_db = sp.welch_psd_db(x, FS, FC, nfft=1000)  # bin exactly on +1 MHz
    assert freqs_hz[np.argmax(psd_db)] == pytest.approx(FC + 1e6)
    assert psd_db.max() == pytest.approx(0.0, abs=0.1)

    # density scaling of white noise: total power 1 spread over fs Hz -> -70 dB/Hz at 10 MHz
    rng = np.random.default_rng(3)
    noise = _complex_noise(rng, 200_000, 1.0)
    _, dens_db = sp.welch_psd_db(noise, FS, FC, nfft=1024, scaling="density")
    assert dens_db.mean() == pytest.approx(-10 * np.log10(FS), abs=0.5)

    # multi-channel input averages linear power
    two = np.stack([x, np.zeros_like(x)])
    _, p2 = sp.welch_psd_db(two, FS, FC, nfft=1000)
    assert p2.max() == pytest.approx(-3.01, abs=0.1)


# --------------------------------------------------------------------------- noise floor


def _noise_map(rng: np.random.Generator, frames: int, bins: int, mean_db: float) -> np.ndarray:
    """dB power map of complex-Gaussian noise: per-cell power is exponential."""
    lin = rng.exponential(10 ** (mean_db / 10), size=(frames, bins))
    return sp.db(lin).astype(np.float32)


def test_noise_floor_ignores_short_bursts():
    rng = np.random.default_rng(4)
    frames, bins = 600, 256
    clean = _noise_map(rng, frames, bins, -70.0)
    busy = clean.copy()
    # 10 % of frames carry a +30 dB burst over bins 100..150
    burst_frames = rng.choice(frames, size=int(0.1 * frames), replace=False)
    busy[np.ix_(burst_frames, np.arange(100, 150))] += 30.0

    floor_clean = sp.estimate_noise_floor_db(clean)
    floor_busy = sp.estimate_noise_floor_db(busy)
    assert floor_busy.shape == (bins,)
    # bins without bursts are untouched; burst bins shift by the tiny
    # percentile re-ranking (0.2 -> 0.22 of the noise cells: ~0.5 dB), not by 30 dB
    assert np.array_equal(floor_busy[:100], floor_clean[:100])
    assert np.max(np.abs(floor_busy - floor_clean)) < 1.5
    # the 20th percentile sits ~6.5 dB below the mean noise power ...
    assert floor_clean.mean() == pytest.approx(-70.0 + 10 * np.log10(-np.log(0.8)), abs=0.5)
    # ... and bias correction recovers the mean
    corrected = sp.estimate_noise_floor_db(clean, bias_correct=True)
    assert corrected.mean() == pytest.approx(-70.0, abs=0.5)
    assert sp.percentile_bias_db(20.0) == pytest.approx(6.51, abs=0.02)

    # even a 30 % duty cycle only re-ranks the percentile (+1.8 dB expected), it
    # never tracks the burst level
    heavy = clean.copy()
    heavy_frames = rng.choice(frames, size=int(0.3 * frames), replace=False)
    heavy[np.ix_(heavy_frames, np.arange(100, 150))] += 30.0
    floor_heavy = sp.estimate_noise_floor_db(heavy)
    assert np.max(floor_heavy - floor_clean) < 3.5
    assert np.max(floor_heavy) < -60.0


def test_noise_floor_smoothing_and_axis():
    rng = np.random.default_rng(5)
    p = _noise_map(rng, 200, 128, -60.0)
    raw = sp.estimate_noise_floor_db(p)
    smooth = sp.estimate_noise_floor_db(p, smooth_bins=9)
    assert smooth.shape == raw.shape == (128,)
    assert np.all(np.isfinite(smooth))
    assert np.std(smooth) < np.std(raw)
    # transposed map with axis=1 gives the same answer
    assert np.allclose(sp.estimate_noise_floor_db(p.T, axis=1), raw)
    # a constant map returns that constant (percentile semantics, no correction)
    const = np.full((50, 8), -55.0, dtype=np.float32)
    assert np.allclose(sp.estimate_noise_floor_db(const), -55.0)
    with pytest.raises(ValueError):
        sp.percentile_bias_db(0.0)
