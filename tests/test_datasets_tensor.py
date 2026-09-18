"""Tests for aerix_rf.datasets.tensor (Workstream D, T3 -- S5/S6 canonical STFT)."""

from __future__ import annotations

import tracemalloc

import numpy as np
import pytest

from aerix_rf.datasets.tensor import (
    CANONICAL_FFT,
    CANONICAL_HOP,
    canonical_products,
    canonical_stft,
    detector_frames,
    ml_tensor,
    power_dbfs,
    usable_mask,
)

FS = 15_360_000.0  # canonical rate


def _bin_centre_tone(n_samples: int, bin_index: int, fs: float = FS) -> np.ndarray:
    """Full-scale complex tone landing exactly on FFT bin ``bin_index``
    (fftshifted convention: bin CANONICAL_FFT//2 is DC)."""

    freq_hz = (bin_index - CANONICAL_FFT // 2) * (fs / CANONICAL_FFT)
    t = np.arange(n_samples, dtype=np.float64) / fs
    return np.exp(2j * np.pi * freq_hz * t).astype(np.complex64)


def test_full_scale_tone_reads_0_dbfs_in_power_dbfs():
    n = CANONICAL_HOP * 4 + CANONICAL_FFT  # a handful of frames
    iq = _bin_centre_tone(n, bin_index=600)
    stft = canonical_stft(iq, FS)
    assert stft.shape[1] == CANONICAL_FFT
    db = power_dbfs(stft)
    # canonical_stft's very last frame is always the bounded trailing-edge
    # pad case (module docstring): frame count is len(iq)//hop, and that
    # last frame's Hann window necessarily reaches past the true data by up
    # to one hop, so its magnitude is legitimately attenuated. Only the
    # non-edge frames are checked here.
    peak_per_frame = db[:-1].max(axis=1)
    assert np.allclose(peak_per_frame, 0.0, atol=0.1)
    assert np.argmax(db[0]) == 600


def test_full_scale_tone_reads_0_dbfs_after_block_means():
    frames_per_ms = 30
    n = frames_per_ms * CANONICAL_HOP + CANONICAL_FFT
    iq = _bin_centre_tone(n, bin_index=700)
    tensor = ml_tensor(iq, FS)
    assert tensor.shape[0] >= 1
    peak_per_frame = tensor.max(axis=1)
    assert np.allclose(peak_per_frame, 0.0, atol=0.1)
    assert np.argmax(tensor[0]) == 700


def test_tone_at_plus_3mhz_lands_on_correct_absolute_hz_bin():
    n = CANONICAL_HOP * 8 + CANONICAL_FFT
    t = np.arange(n, dtype=np.float64) / FS
    iq = np.exp(2j * np.pi * 3_000_000.0 * t).astype(np.complex64)
    stft = canonical_stft(iq, FS)
    db = power_dbfs(stft)
    freqs = np.fft.fftshift(np.fft.fftfreq(CANONICAL_FFT, d=1.0 / FS))
    peak_bin = np.argmax(db[2])
    bin_hz = FS / CANONICAL_FFT
    assert abs(freqs[peak_bin] - 3_000_000.0) <= bin_hz


def test_quarter_second_gives_250_ml_frames():
    n = int(round(0.25 * FS))
    iq = np.zeros(n, dtype=np.complex64)
    tensor = ml_tensor(iq, FS)
    assert tensor.shape == (250, CANONICAL_FFT)
    assert tensor.dtype == np.float32


def test_one_second_gives_exactly_1000_ml_frames():
    n = int(FS)
    iq = np.zeros(n, dtype=np.complex64)
    tensor = ml_tensor(iq, FS)
    assert tensor.shape == (1000, CANONICAL_FFT)


def test_usable_mask_selects_exactly_bins_within_6mhz():
    mask = usable_mask(FS, 12.0e6)
    freqs = np.fft.fftshift(np.fft.fftfreq(CANONICAL_FFT, d=1.0 / FS))
    expected = (freqs >= -6.0e6) & (freqs <= 6.0e6)
    assert np.array_equal(mask, expected)
    assert mask.dtype == np.bool_
    assert mask.sum() == 801  # +-400 bins of 15 kHz around DC, inclusive


def test_detector_frames_block_means_linear_power():
    power_lin = np.ones((18, CANONICAL_FFT), dtype=np.float32) * 4.0
    out = detector_frames(power_lin, factor=6)
    assert out.shape == (3, CANONICAL_FFT)
    assert np.allclose(out, 4.0)
    assert out.dtype == np.float32


def test_detector_frames_drops_remainder():
    power_lin = np.ones((20, CANONICAL_FFT), dtype=np.float32)
    out = detector_frames(power_lin, factor=6)
    assert out.shape == (3, CANONICAL_FFT)  # 2 frames dropped


def test_ml_tensor_memory_does_not_materialise_full_stft():
    # A smaller-but-nontrivial window (100 ms) so the test runs fast while
    # still exercising the chunked streaming path (frames_per_ms * chunk_ms
    # STFT frames in flight, never the whole window's worth).
    n = int(round(0.5 * FS))
    iq = (np.random.default_rng(0).standard_normal(n) + 1j * np.random.default_rng(1).standard_normal(n)).astype(
        np.complex64
    )
    tracemalloc.start()
    tracemalloc.reset_peak()
    tensor = ml_tensor(iq, FS)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert tensor.shape[0] == 500
    # Full complex64 STFT for 0.5 s would be ~15000 * 1024 * 8 = 123 MB;
    # the streamed implementation must stay well under that.
    assert peak < 120 * 1024 * 1024


def test_ml_tensor_dtype_and_shape_general():
    n = int(round(2.0 * FS))
    iq = np.zeros(n, dtype=np.complex64)
    tensor = ml_tensor(iq, FS)
    assert tensor.dtype == np.float32
    assert tensor.shape == (2000, CANONICAL_FFT)


@pytest.mark.parametrize("n_ms", [0, 1])
def test_ml_tensor_short_inputs_do_not_crash(n_ms):
    n = n_ms * 15360
    iq = np.zeros(max(n, 10), dtype=np.complex64)
    tensor = ml_tensor(iq, FS)
    assert tensor.shape[1] == CANONICAL_FFT
    assert tensor.shape[0] >= 0


def test_canonical_products_matches_old_two_pass_path():
    """F5 single-STFT fusion: canonical_products' (ml_tensor, detector_frames)
    outputs must be bit-for-bit identical to the old two-pass composition
    (a standalone ml_tensor() call plus a standalone canonical_stft() call
    fed through detector_frames()) on a non-trivial synthetic 1 s window --
    this is the "prepare path stays byte-identical" proof for F5."""
    n = int(round(1.0 * FS))  # exactly 1.000 s -> 30000 STFT frames, non-aligned edge case avoided
    rng = np.random.default_rng(7)
    iq = ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 0.1).astype(np.complex64)
    # A tone to make sure the comparison isn't just noise-floor-trivial.
    t = np.arange(n, dtype=np.float64) / FS
    iq = (iq + 0.3 * np.exp(2j * np.pi * 2_000_000.0 * t)).astype(np.complex64)

    old_tensor = ml_tensor(iq, FS)
    old_stft = canonical_stft(iq, FS)
    old_power_lin = (old_stft.real.astype(np.float64) ** 2 + old_stft.imag.astype(np.float64) ** 2)
    old_det = detector_frames(old_power_lin, factor=6)

    new_tensor, new_det = canonical_products(iq, FS)

    assert new_tensor.shape == old_tensor.shape
    assert np.array_equal(new_tensor, old_tensor)
    assert new_det.shape == old_det.shape
    assert np.array_equal(new_det, old_det)


def test_canonical_products_detector_frames_exceed_ms_grid_on_non_multiple_window():
    """A window whose STFT frame count isn't a multiple of frames_per_ms
    (30) still yields whole trailing detector blocks (factor 6) beyond the
    last full ms block -- exercises the leftover-tail branch."""
    # 1005 hop-512 frames: 33 ms blocks (990 frames) but 167 detector blocks
    # (1002 frames) -- 3 more detector frames than 33*5=165.
    n = 1005 * CANONICAL_HOP
    rng = np.random.default_rng(11)
    iq = ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 0.1).astype(np.complex64)

    tensor, det = canonical_products(iq, FS)
    assert tensor.shape[0] == 33
    assert det.shape[0] == 167

    old_stft = canonical_stft(iq, FS)
    old_power_lin = (old_stft.real.astype(np.float64) ** 2 + old_stft.imag.astype(np.float64) ** 2)
    old_det = detector_frames(old_power_lin, factor=6)
    assert np.array_equal(det, old_det)


def test_ml_tensor_still_equals_canonical_products_first_element():
    n = int(round(0.3 * FS))
    rng = np.random.default_rng(3)
    iq = ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 0.2).astype(np.complex64)
    assert np.array_equal(ml_tensor(iq, FS), canonical_products(iq, FS)[0])
