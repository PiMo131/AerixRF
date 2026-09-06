"""Tests for antsdr_toolkit.device.synthetic (emitters, Scene, SyntheticSource)."""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.device.base import SampleSource, StreamInfo
from antsdr_toolkit.dsp import spectrum as sp


def _power(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.complex128)
    return float(np.mean(x.real**2 + x.imag**2))


def _energy_fraction_in_band(x: np.ndarray, fs: float, bw: float) -> float:
    p = np.abs(np.fft.fft(np.asarray(x, dtype=np.complex128))) ** 2
    f = np.fft.fftfreq(len(x), d=1.0 / fs)
    return float(p[np.abs(f) <= bw / 2].sum() / p.sum())


# --------------------------------------------------------------------------- generators


def test_awgn_power_and_dtype():
    rng = np.random.default_rng(0)
    x = syn.awgn(200_000, rng)
    assert x.dtype == np.complex64 and x.shape == (200_000,)
    assert _power(x) == pytest.approx(1.0, rel=0.02)
    y = syn.awgn(200_000, rng, power_db=-20.0)
    assert _power(y) == pytest.approx(0.01, rel=0.02)
    # circular: I and Q carry equal power
    assert np.mean(x.real**2) == pytest.approx(np.mean(x.imag**2), rel=0.05)
    assert syn.awgn(0, rng).shape == (0,)
    # deterministic for a seeded generator
    assert np.array_equal(
        syn.awgn(64, np.random.default_rng(3)), syn.awgn(64, np.random.default_rng(3))
    )


def test_bandlimited_noise_burst_is_flat_inside_band_and_unit_power():
    rng = np.random.default_rng(1)
    fs, bw = 20e6, 4e6
    x = syn.bandlimited_noise_burst(fs, bw, 2e-3, rng)
    assert x.dtype == np.complex64
    assert len(x) == 40_000
    assert _power(x) == pytest.approx(1.0, abs=1e-3)
    assert _energy_fraction_in_band(x, fs, bw) >= 0.95
    # flat inside, steep roll-off outside: > 40 dB between the inner band and out-of-band
    p = np.abs(np.fft.fft(x.astype(np.complex128))) ** 2
    f = np.fft.fftfreq(len(x), d=1.0 / fs)
    inner = p[np.abs(f) <= 0.45 * bw]
    outer = p[np.abs(f) >= 0.6 * bw]
    assert 10 * np.log10(inner.mean() / outer.mean()) > 40.0
    # flat: the inner band split in quarters agrees within 1 dB
    quarters = np.array_split(np.sort(f[np.abs(f) <= 0.45 * bw]), 4)
    levels = [10 * np.log10(p[np.isin(f, q)].mean()) for q in quarters]
    assert max(levels) - min(levels) < 1.0
    # a bandwidth wider than fs degenerates to white noise, still unit power
    w = syn.bandlimited_noise_burst(fs, 2 * fs, 1e-4, rng)
    assert _power(w) == pytest.approx(1.0, abs=1e-3)
    with pytest.raises(ValueError):
        syn.bandlimited_noise_burst(fs, bw, 0.0, rng)


def test_lora_chirps_sweep_the_bandwidth():
    rng = np.random.default_rng(2)
    fs, bw, sf = 1e6, 125e3, 7
    n_chips = 2**sf
    symbols = [0, 37, 64, 100, 127, 1, 50, 90]
    x = syn.lora_chirps(fs, bw, sf, len(symbols), rng, symbols=symbols)
    n_sym = round(n_chips / bw * fs)  # 1024 samples per symbol at 1 MS/s
    assert x.dtype == np.complex64
    assert len(x) == n_sym * len(symbols)
    assert _power(x) == pytest.approx(1.0, abs=1e-3)  # constant envelope

    f_inst = syn.instantaneous_frequency_hz(x, fs)
    # the sweep covers the whole bandwidth, never leaves it
    assert f_inst.min() == pytest.approx(-bw / 2, abs=0.02 * bw)
    assert f_inst.max() == pytest.approx(bw / 2, abs=0.02 * bw)
    assert np.percentile(f_inst, 1) < -0.9 * bw / 2
    assert np.percentile(f_inst, 99) > 0.9 * bw / 2
    for i, s in enumerate(symbols):
        # f_inst[k] spans samples k..k+1, so drop the last entry that straddles the next symbol
        seg = f_inst[i * n_sym : (i + 1) * n_sym - 1]
        # symbol value sets the start frequency of the up-chirp ...
        assert seg[1] == pytest.approx(-bw / 2 + bw * s / n_chips, abs=bw / n_chips)
        # ... which rises linearly at bw / T_symbol and wraps once (s > 0) or never (s == 0)
        drops = np.flatnonzero(np.diff(seg) < -bw / 2)
        assert len(drops) == (1 if s > 0 else 0)
        if s > 0:
            assert drops[0] == pytest.approx(n_sym * (1 - s / n_chips), abs=3)
        rising = np.diff(seg)[np.diff(seg) > -bw / 2]
        assert np.allclose(rising, bw / (n_sym / fs) / fs, rtol=0.02, atol=1.0)

    # random symbols come from rng, reproducibly, and are validated
    a = syn.lora_chirps(fs, bw, sf, 4, np.random.default_rng(9))
    b = syn.lora_chirps(fs, bw, sf, 4, np.random.default_rng(9))
    assert np.array_equal(a, b)
    with pytest.raises(ValueError):
        syn.lora_chirps(fs, bw, sf, 2, rng, symbols=[0, n_chips])
    with pytest.raises(ValueError):
        syn.lora_chirps(bw / 2, bw, sf, 2, rng)


def test_fm_video_like_occupies_roughly_carson_bandwidth():
    rng = np.random.default_rng(3)
    fs = 40e6
    for dev, bb in [(6e6, 6e6), (1e6, 1e6)]:
        x = syn.fm_video_like(fs, 5e-3, rng, deviation_hz=dev, baseband_bw_hz=bb)
        assert x.dtype == np.complex64 and len(x) == 200_000
        assert _power(x) == pytest.approx(1.0, abs=1e-3)  # constant envelope
        carson = 2 * (dev + bb)
        obw99 = syn.occupied_bandwidth_hz(x, fs, fraction=0.99, nfft=1024)
        assert 0.6 * carson <= obw99 <= 1.2 * carson
        # wideband FM: wider than the deviation range alone, spectrum centred on 0
        assert obw99 > 2 * dev * 1.1
        f_inst = syn.instantaneous_frequency_hz(x, fs)
        assert np.abs(f_inst).max() <= 1.05 * dev
        assert abs(np.mean(f_inst)) < 0.05 * dev
    # same-seed determinism
    assert np.array_equal(
        syn.fm_video_like(fs, 1e-4, np.random.default_rng(5)),
        syn.fm_video_like(fs, 1e-4, np.random.default_rng(5)),
    )


def test_gfsk_burst_deviation_and_unit_power():
    rng = np.random.default_rng(4)
    fs, rs = 2e6, 100e3
    x = syn.gfsk_burst(fs, rs, 400, rng, modulation_index=0.5, bt=0.5)
    assert x.dtype == np.complex64 and len(x) == 8000
    assert _power(x) == pytest.approx(1.0, abs=1e-3)
    peak = 0.5 * rs / 2  # h * Rs / 2 = 25 kHz
    f_inst = syn.instantaneous_frequency_hz(x, fs)[40:-40]  # skip the amplitude ramps
    assert np.abs(f_inst).max() == pytest.approx(peak, rel=0.05)
    assert np.median(np.abs(f_inst)) > 0.6 * peak
    # roughly (1 + h) * Rs wide (99 % OBW), i.e. narrowband compared with the sample rate
    obw = syn.occupied_bandwidth_hz(x, fs, nfft=1024)
    assert 0.5 * rs <= obw <= 2.0 * rs
    # explicit bits: a long run of ones sits at +peak
    ones = syn.gfsk_burst(fs, rs, 40, rng, bits=[1] * 40)
    f_ones = syn.instantaneous_frequency_hz(ones, fs)[100:-100]
    assert np.allclose(f_ones, peak, rtol=0.02)
    # non-integer samples per symbol is fine
    y = syn.gfsk_burst(fs, 57.6e3, 100, rng)
    assert len(y) == round(100 * fs / 57.6e3)
    with pytest.raises(ValueError):
        syn.gfsk_burst(fs, 1.5e6, 10, rng)


# --------------------------------------------------------------------------- Scene


FS = 20e6
FC = 2.44e9


def _scene(seed: int = 7, duration_s: float = 20e-3) -> syn.Scene:
    return syn.Scene(FS, FC, duration_s, np.random.default_rng(seed), noise_power_db=-60.0)


def test_scene_snr_scaling_measured_from_stft():
    scene = _scene()
    bw = 2e6
    burst = syn.bandlimited_noise_burst(FS, bw, 5e-3, np.random.default_rng(8))
    emission = scene.add(burst, t_start_s=5e-3, freq_offset_hz=3e6, snr_db=20.0, label="ofdm")
    assert emission.bandwidth_hz == pytest.approx(bw, rel=0.1)
    assert emission.t_start_s == pytest.approx(5e-3) and emission.t_end_s == pytest.approx(10e-3)
    assert len(scene.emissions) == 1

    x = scene.render()
    assert x.dtype == np.complex64 and x.shape == (400_000,)
    # noise level before the burst is the configured -60 dBFS
    assert 10 * np.log10(_power(x[:90_000])) == pytest.approx(-60.0, abs=0.2)

    power_db, freqs_hz, times_s = sp.stft_power_db(x, FS, FC, fft_size=1024)
    truth = scene.truth_bursts()
    assert len(truth) == 1 and truth[0]["label"] == "ofdm"
    assert truth[0]["f_low_hz"] == pytest.approx(FC + 3e6 - bw / 2, abs=0.1 * bw)
    assert truth[0]["f_high_hz"] == pytest.approx(FC + 3e6 + bw / 2, abs=0.1 * bw)

    box = truth[0]
    in_band = (freqs_hz >= box["f_low_hz"] + 0.1 * bw) & (freqs_hz <= box["f_high_hz"] - 0.1 * bw)
    in_time = (times_s >= box["t_start_s"] + 0.5e-3) & (times_s <= box["t_end_s"] - 0.5e-3)
    before = times_s < box["t_start_s"] - 0.5e-3
    lin = 10 ** (power_db.astype(np.float64) / 10)
    signal_cell = lin[np.ix_(in_time, in_band)].mean()
    noise_cell = lin[np.ix_(before, in_band)].mean()
    assert 10 * np.log10(signal_cell / noise_cell) == pytest.approx(20.0, abs=1.5)

    # an explicit bandwidth overrides the estimate and changes the scale accordingly
    e2 = scene.add(
        burst, t_start_s=12e-3, freq_offset_hz=-4e6, snr_db=20.0, label="x", bandwidth_hz=4e6
    )
    assert e2.bandwidth_hz == 4e6
    expected_scale = emission.scale * np.sqrt(4e6 / emission.bandwidth_hz)
    assert e2.scale == pytest.approx(expected_scale, rel=1e-6)


def test_scene_clips_to_bounds_and_validates():
    scene = _scene(duration_s=10e-3)
    tone = np.exp(2j * np.pi * 0.01 * np.arange(60_000)).astype(np.complex64)
    early = scene.add(tone, t_start_s=-1e-3, freq_offset_hz=0.0, snr_db=10.0, label="early")
    assert early.t_start_s == 0.0
    assert early.t_end_s == pytest.approx(2e-3)
    assert len(early.samples) == 40_000
    late = scene.add(tone, t_start_s=9e-3, freq_offset_hz=1e6, snr_db=10.0, label="late")
    assert late.t_end_s == pytest.approx(scene.duration_s)
    assert len(late.samples) == 20_000
    truth = scene.truth_bursts()
    assert [t["label"] for t in truth] == ["early", "late"]
    assert truth[1]["t_end_s"] == pytest.approx(10e-3)
    assert scene.render().shape == (200_000,)

    with pytest.raises(ValueError):
        scene.add(tone, t_start_s=20e-3, freq_offset_hz=0.0, snr_db=10.0, label="outside")
    with pytest.raises(ValueError):
        scene.add(tone, t_start_s=0.0, freq_offset_hz=FS, snr_db=10.0, label="off-band")
    with pytest.raises(ValueError):
        silent = np.zeros(100, np.complex64)
        scene.add(silent, t_start_s=0.0, freq_offset_hz=0.0, snr_db=10.0, label="silent")
    # emissions near the band edge get their truth box clipped to the scene span
    edge = scene.add(
        tone, t_start_s=0.0, freq_offset_hz=FS / 2, snr_db=10.0, label="edge", bandwidth_hz=1e6
    )
    assert scene.truth_bursts()[-1]["f_high_hz"] == pytest.approx(FC + FS / 2)
    assert edge.freq_offset_hz == FS / 2


def test_scene_fhss_sequences():
    channels = [-5e6, -2e6, 0.0, 2e6, 5e6]
    rng = np.random.default_rng(11)

    def burst(duration_s: float) -> np.ndarray:
        return syn.gfsk_burst(FS, 100e3, round(duration_s * 100e3), rng)

    scene = _scene(duration_s=50e-3)
    seq = scene.fhss(
        burst,
        channels_hz=channels,
        hop_rate_hz=200.0,
        burst_duration_s=3e-3,
        t_start_s=0.0,
        t_end_s=35e-3,
        snr_db=15.0,
        label="fhss",
        order="sequential",
    )
    assert len(seq) == 7
    assert [e.freq_offset_hz for e in seq] == [channels[k % 5] for k in range(7)]
    assert [e.t_start_s for e in seq] == pytest.approx([k * 5e-3 for k in range(7)])
    assert all(e.duration_s == pytest.approx(3e-3) for e in seq)
    assert all(e.label == "fhss" and e.snr_db == 15.0 for e in seq)

    # zero-argument generator is also accepted and truncated to the burst duration
    rnd = scene.fhss(
        lambda: syn.awgn(100_000, rng),
        channels_hz=channels,
        hop_rate_hz=100.0,
        burst_duration_s=2e-3,
        t_start_s=10e-3,
        t_end_s=50e-3,
        snr_db=5.0,
        label="rnd",
        order="random",
    )
    assert len(rnd) == 4
    assert all(e.freq_offset_hz in channels for e in rnd)
    assert all(len(e.samples) == 40_000 for e in rnd)
    assert len(scene.truth_bursts()) == 11
    with pytest.raises(ValueError):
        scene.fhss(
            burst, channels_hz=channels, hop_rate_hz=10.0, burst_duration_s=1e-3,
            t_start_s=0.0, t_end_s=1e-3, snr_db=0.0, label="bad", order="shuffle",
        )


def test_scene_render_is_deterministic():
    def build(seed: int) -> np.ndarray:
        scene = _scene(seed=seed, duration_s=5e-3)
        chirps = syn.lora_chirps(FS, 500e3, 7, 4, np.random.default_rng(seed))
        scene.add(chirps, t_start_s=1e-3, freq_offset_hz=-1e6, snr_db=12.0, label="lora")
        return scene.render()

    a, b = build(21), build(21)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, build(22))
    scene = _scene(seed=1, duration_s=1e-3)
    assert np.array_equal(scene.render(), scene.render())  # idempotent


# --------------------------------------------------------------------------- SyntheticSource


def test_synthetic_source_reads_chunks_and_exhausts():
    scene = _scene(duration_s=5e-3)
    noise = syn.awgn(20_000, np.random.default_rng(1))
    scene.add(noise, t_start_s=1e-3, freq_offset_hz=2e6, snr_db=10.0, label="n", bandwidth_hz=FS)
    with syn.SyntheticSource.from_scene(scene) as src:
        assert isinstance(src, SampleSource)
        assert isinstance(src.info, StreamInfo)
        assert src.info.hardware == "synthetic"
        assert src.info.sample_rate_hz == FS and src.info.center_freq_hz == FC
        assert src.n_samples == 100_000
        first = src.read(1000)
        assert first.dtype == np.complex64 and first.shape == (1000,)
        assert np.array_equal(first, scene.render()[:1000])
        chunks = list(src.iter_chunks(30_000))
        assert [len(c) for c in chunks] == [30_000, 30_000, 30_000, 9_000]
        assert src.read(10).shape == (0,)
        src.reset()
        assert src.read(5).shape == (5,)
        with pytest.raises(NotImplementedError):
            src.retune(FC + 1e6)
    with pytest.raises(RuntimeError):
        src.read(1)
    src.close()  # idempotent


def test_synthetic_source_loop_and_from_samples():
    samples = np.arange(10, dtype=np.complex64)
    info = StreamInfo(sample_rate_hz=1e6, center_freq_hz=1e9, hardware="synthetic")
    src = syn.SyntheticSource(samples, info, loop=True)
    out = src.read(25)
    assert out.shape == (25,)
    assert np.array_equal(out, np.tile(samples, 3)[:25])
    assert np.array_equal(src.read(3), samples[5:8])
    # the returned chunk is a copy, not a view into the buffer
    out[:] = 0
    assert src.read(0).shape == (0,)
    assert np.array_equal(syn.SyntheticSource(samples, info).read(100), samples)
    with pytest.raises(ValueError):
        src.read(-1)
