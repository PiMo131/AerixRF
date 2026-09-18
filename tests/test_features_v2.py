"""Tests for aerix_rf.classify.features_v2 (design doc
docs/design/features-and-benchmark.md S1, builder task F1)."""

from __future__ import annotations

import numpy as np
import pytest

from aerix_rf.classify.features_v2 import (
    BIN_HI,
    BIN_HZ,
    BIN_LO,
    CANONICAL_FS,
    FEATURES_V2_DIM,
    FEATURE_NAMES,
    G1_SLICE,
    G2_SLICE,
    G3_SLICE,
    G4_SLICE,
    G5_SLICE,
    G6_SLICE,
    N_BAND_BINS,
    N_SUBBANDS,
    _FRAME_DT_S,
    extract_features_v2,
    feature_names_v2,
    features_v2_from_iq,
)

FS = CANONICAL_FS
_FULL_FREQS = np.fft.fftshift(np.fft.fftfreq(1024, d=1.0 / FS))


def _base_tensor(rng: np.random.Generator, n_ms: int, floor_db: float = -70.0,
                  std: float = 0.3) -> np.ndarray:
    return (floor_db + rng.normal(0.0, std, size=(n_ms, 1024))).astype(np.float32)


def _add_band(tensor: np.ndarray, *, center_hz: float, width_hz: float,
              level_above_floor_db: float, duty: float) -> np.ndarray:
    """Elevate a contiguous full-1024 frequency range by
    ``level_above_floor_db`` for the first ``duty`` fraction of rows
    (contiguous on-block), leaving the rest untouched."""
    out = tensor.copy()
    lo, hi = center_hz - width_hz / 2.0, center_hz + width_hz / 2.0
    mask = (_FULL_FREQS >= lo) & (_FULL_FREQS <= hi)
    n_on = int(round(tensor.shape[0] * duty))
    out[:n_on][:, mask] += level_above_floor_db
    return out


def test_shape_dtype_and_determinism():
    rng = np.random.default_rng(1)
    tensor = _base_tensor(rng, 200)
    r1 = extract_features_v2(tensor, None, FS)
    r2 = extract_features_v2(tensor, None, FS)
    assert r1.vector.shape == (FEATURES_V2_DIM,)
    assert r1.vector.dtype == np.float32
    assert r1.valid_mask.shape == (FEATURES_V2_DIM,)
    assert r1.valid_mask.dtype == np.bool_
    assert r1.version == "features_v2"
    assert np.array_equal(r1.vector, r2.vector)
    assert np.array_equal(r1.valid_mask, r2.valid_mask)
    assert r1.nf0_dbfs == r2.nf0_dbfs


def test_gain_invariance_20db():
    rng = np.random.default_rng(2)
    base = _base_tensor(rng, 300)
    base = _add_band(base, center_hz=1.0e6, width_hz=2.0e6, level_above_floor_db=12.0, duty=0.75)
    boosted = base + 20.0

    r_base = extract_features_v2(base, None, FS)
    r_boost = extract_features_v2(boosted, None, FS)

    assert abs((r_boost.nf0_dbfs - r_base.nf0_dbfs) - 20.0) < 1e-3
    for sl, name in ((G1_SLICE, "G1"), (G2_SLICE, "G2"), (G4_SLICE, "G4"), (G6_SLICE, "G6")):
        diff = np.abs(r_base.vector[sl].astype(np.float64) - r_boost.vector[sl].astype(np.float64))
        assert np.max(diff) < 1e-3, f"{name} not gain-invariant: max diff {np.max(diff)}"


def test_sloped_noise_floor_invariance():
    rng = np.random.default_rng(3)
    base = _base_tensor(rng, 300)
    base = _add_band(base, center_hz=0.5e6, width_hz=2.0e6, level_above_floor_db=10.0, duty=0.75)

    # +-3 dB linear tilt across the full axis, static across time (this is
    # exactly what the per-bin floor is designed to absorb).
    tilt = 3.0 * (_FULL_FREQS / _FULL_FREQS.max())
    tilted = base + tilt[None, :].astype(np.float32)

    r_base = extract_features_v2(base, None, FS)
    r_tilted = extract_features_v2(tilted, None, FS)

    diff_g1 = np.abs(r_base.vector[G1_SLICE].astype(np.float64) - r_tilted.vector[G1_SLICE].astype(np.float64))
    assert np.max(diff_g1) < 0.5, f"sub-band features not floor-tilt invariant: max diff {np.max(diff_g1)}"

    # M2: the window-internal spectral floor nfs_k is a deg-2 polyfit, which
    # fully spans a linear tilt, so G6 should also be (near-)tilt-invariant.
    diff_g6 = np.abs(r_base.vector[G6_SLICE].astype(np.float64) - r_tilted.vector[G6_SLICE].astype(np.float64))
    assert np.max(diff_g6) < 1.0, f"G6 not floor-tilt invariant: max diff {np.max(diff_g6)}"


def test_dc_spur_no_effect_outside_notch():
    rng = np.random.default_rng(4)
    base = _base_tensor(rng, 250)
    base = _add_band(base, center_hz=-2.0e6, width_hz=1.0e6, level_above_floor_db=8.0, duty=0.7)
    spiked = base.copy()
    spiked[:, 512] += 40.0  # DC bin, well inside the [510,514] notch

    r_base = extract_features_v2(base, None, FS)
    r_spiked = extract_features_v2(spiked, None, FS)

    diff = np.abs(r_base.vector.astype(np.float64) - r_spiked.vector.astype(np.float64))
    assert np.max(diff) < 0.1, f"DC spur leaked into features: max diff {np.max(diff)}"


def test_9mhz_flat_band_bandwidth_and_centroid():
    # A literal 9 MHz band centred at -1 MHz does not fit inside the +-4.995
    # MHz common band (edge would be -5.5 MHz); centred at -0.4 MHz instead
    # so the full 9 MHz signal is observable without band-edge clipping.
    rng = np.random.default_rng(5)
    center_hz = -0.4e6
    width_hz = 9.0e6
    n_ms = 1000
    base = _base_tensor(rng, n_ms)
    tensor = _add_band(base, center_hz=center_hz, width_hz=width_hz,
                       level_above_floor_db=15.0, duty=0.75)

    result = extract_features_v2(tensor, None, FS)
    names = list(result.names)
    bw3 = float(result.vector[names.index("g4_bw_m3db_hz")])
    centroid = float(result.vector[names.index("g2_centroid_offset_hz")])

    assert abs(bw3 - width_hz) <= 0.3e6, f"occupied BW {bw3} Hz not within 0.3 MHz of {width_hz}"
    assert abs(centroid - center_hz) <= 0.2e6, f"centroid {centroid} Hz not within 0.2 MHz of {center_hz}"


def test_short_fragment_masks_g3_g5_only():
    rng = np.random.default_rng(6)
    tensor = _base_tensor(rng, 14)
    result = extract_features_v2(tensor, None, FS)

    assert np.all(np.isfinite(result.vector))
    assert np.all(result.valid_mask[G1_SLICE])
    assert np.all(result.valid_mask[G2_SLICE])
    assert np.all(result.valid_mask[G4_SLICE])
    assert np.all(result.valid_mask[G6_SLICE])
    assert not np.any(result.valid_mask[G3_SLICE])
    assert not np.any(result.valid_mask[G5_SLICE])


def test_names_length_and_spec_constants():
    names = feature_names_v2()
    assert len(names) == FEATURES_V2_DIM == 302
    assert len(set(names)) == len(names)
    assert names == FEATURE_NAMES

    assert BIN_LO == 179
    assert BIN_HI == 845
    assert N_BAND_BINS == BIN_HI - BIN_LO + 1 == 667
    assert N_SUBBANDS == 64
    assert BIN_HZ == pytest.approx(15_000.0)


def test_features_v2_from_iq_end_to_end():
    rng = np.random.default_rng(7)
    n = int(round(1.0 * FS))
    t = np.arange(n, dtype=np.float64) / FS
    noise = 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    tone = 0.05 * np.exp(2j * np.pi * 2.0e6 * t)
    iq = (noise + tone).astype(np.complex64)

    result = features_v2_from_iq(iq, FS)

    assert result.vector.shape == (FEATURES_V2_DIM,)
    assert result.vector.dtype == np.float32
    assert np.all(np.isfinite(result.vector))
    assert result.valid_mask.shape == (FEATURES_V2_DIM,)
    assert np.isfinite(result.nf0_dbfs)
    assert result.version == "features_v2"
    # a full 1.0 s window has 1000 ms -> G3/G5 should be valid
    assert np.all(result.valid_mask[G3_SLICE])
    assert np.all(result.valid_mask[G5_SLICE])


def test_wrong_fs_and_fft_size_raise():
    rng = np.random.default_rng(8)
    tensor = _base_tensor(rng, 50)
    with pytest.raises(ValueError):
        extract_features_v2(tensor, None, fs_hz=12.288e6)
    with pytest.raises(ValueError):
        extract_features_v2(tensor[:, :512], None, FS)


# ---------------------------------------------------------------------------
# Review 2026-09-18 (docs/design/features-and-benchmark.md S1.6) regression
# tests: M1-M5 must-fixes + G6 acceptance. The pre-review suite only used
# duty 0.70-0.75, which is exactly why M1/M2 survived (S1.6 "Tests and
# sequencing"); these add duty in {0.02, 0.20, 0.30, 1.00}.
# ---------------------------------------------------------------------------


def test_m1_low_duty_2mhz_emitter_no_longer_blind():
    """M1: r_shape = percentile(R, 99, axis=0) feeds G2/G4/centroid, so a
    duty-0.30 emitter is no longer indistinguishable from noise (design doc
    measured: r_med gave occ_frac_6db 0.000, peak_to_floor 0.6 dB, bw3
    10.01 MHz -- i.e. the whole band -- for this exact case)."""
    rng = np.random.default_rng(101)
    n_ms = 1000
    base = _base_tensor(rng, n_ms)
    tensor = _add_band(base, center_hz=0.0, width_hz=2.0e6,
                       level_above_floor_db=20.0, duty=0.30)

    result = extract_features_v2(tensor, None, FS)
    names = list(result.names)
    occ6 = float(result.vector[names.index("g2_occ_frac_6db")])
    peak_to_floor = float(result.vector[names.index("g2_peak_to_floor_db")])
    bw3 = float(result.vector[names.index("g4_bw_m3db_hz")])

    assert occ6 > 0.1, f"g2_occ_frac_6db {occ6} not > 0.1 (M1 regression)"
    assert peak_to_floor > 10.0, f"g2_peak_to_floor_db {peak_to_floor} not > 10 dB"
    assert abs(bw3 - 2.0e6) <= 0.4e6, f"g4_bw_m3db_hz {bw3} not within 0.4 MHz of 2.0 MHz"


def _burst_train_detector_frames(n_frames: int, period_ms: float, on_ms: float,
                                  level_above_floor_db: float = 20.0,
                                  floor_dbfs: float = -70.0) -> np.ndarray:
    """Synthetic 200 us detector frames (linear power, [n_frames, 1024]):
    a periodic, full-band burst train at ``period_ms`` cadence, on for
    ``on_ms`` per period."""
    floor_lin = 10.0 ** (floor_dbfs / 10.0)
    on_lin = 10.0 ** ((floor_dbfs + level_above_floor_db) / 10.0)
    frames = np.full((n_frames, 1024), floor_lin, dtype=np.float64)
    period_frames = int(round(period_ms / (_FRAME_DT_S * 1000.0)))
    on_frames = int(round(on_ms / (_FRAME_DT_S * 1000.0)))
    for start in range(0, n_frames, period_frames):
        frames[start:start + on_frames, :] = on_lin
    return frames.astype(np.float32)


def test_m4_m5_periodic_burst_train_cadence_and_autocorrelation():
    """M4 (greatest-of detector, nf0_det from the detector frames) + M5
    (unbiased-normalised autocorrelation, first local max after the first
    zero crossing): a 640 ms period burst train must read G3 IBI approx
    640 ms and an autocorrelation lag approx 640 ms, not 0.2 ms (the design
    doc measured the pre-fix ACF peak at 0.999 / 0.200 ms on exactly this
    kind of series -- lag 1 for any smooth series under biased
    normalisation)."""
    n_frames = 10_000  # 2.000 s of 200 us detector frames
    period_ms = 640.0
    on_ms = 100.0
    detector_frames_lin = _burst_train_detector_frames(n_frames, period_ms, on_ms)

    rng = np.random.default_rng(102)
    n_ms = n_frames // 5  # 5 detector frames per ms (factor 6 of 30 STFT frames/ms)
    tensor = _base_tensor(rng, n_ms)

    result = extract_features_v2(tensor, detector_frames_lin, FS)
    names = list(result.names)
    ibi_p50 = float(result.vector[names.index("g3_ibi_p50_ms")])
    lag_ms = float(result.vector[names.index("g3_autocorr_lag_ms")])

    assert abs(ibi_p50 - period_ms) <= 0.10 * period_ms, f"g3_ibi_p50_ms {ibi_p50} not within 10% of {period_ms}"
    assert abs(lag_ms - period_ms) <= 0.10 * period_ms, (
        f"g3_autocorr_lag_ms {lag_ms} not within 10% of {period_ms} (M5 regression: was ~0.2 ms)"
    )


def _hopping_tensor(rng: np.random.Generator, n_ms: int, block_ms: int,
                     centers_hz: list[float], width_hz: float = 100e3,
                     level_above_floor_db: float = 15.0) -> np.ndarray:
    tensor = _base_tensor(rng, n_ms)
    n_blocks = n_ms // block_ms
    for b in range(n_blocks):
        center = centers_hz[b % len(centers_hz)]
        lo, hi = center - width_hz / 2.0, center + width_hz / 2.0
        mask = (_FULL_FREQS >= lo) & (_FULL_FREQS <= hi)
        tensor[b * block_ms:(b + 1) * block_ms][:, mask] += level_above_floor_db
    return tensor


def test_m3_g5_argmax_hop_rate_separates_hopping_from_fixed():
    """M3: argmax over the 64 sub-band means, gated on band-max >= +6 dB,
    hop = move >= 2 sub-bands. Pre-fix the design doc measured hop_rate
    0.997/1.000/0.997 for noise/continuous/burst -- indistinguishable,
    because argmax over 667 noise-dominated bins carries nothing."""
    n_ms, block_ms = 200, 5
    rng_hop = np.random.default_rng(103)
    hopping = _hopping_tensor(rng_hop, n_ms, block_ms,
                               centers_hz=[-3.0e6, -1.0e6, 1.0e6, 3.0e6])
    rng_fixed = np.random.default_rng(104)
    fixed = _hopping_tensor(rng_fixed, n_ms, block_ms, centers_hz=[1.0e6])

    r_hop = extract_features_v2(hopping, None, FS)
    r_fixed = extract_features_v2(fixed, None, FS)
    names = list(r_hop.names)
    idx = names.index("g5_argmax_hop_rate")
    hop_rate_hopping = float(r_hop.vector[idx])
    hop_rate_fixed = float(r_fixed.vector[idx])

    assert hop_rate_fixed < 0.05, f"fixed-emitter hop_rate {hop_rate_fixed} not near 0"
    assert hop_rate_hopping > 0.15, f"hopping-emitter hop_rate {hop_rate_hopping} not clearly elevated"
    assert hop_rate_hopping - hop_rate_fixed > 0.10, (
        f"hop_rate did not separate: hopping={hop_rate_hopping} fixed={hop_rate_fixed}"
    )


def test_g6_window_internal_floor_acceptance():
    """M2/G6 acceptance case from S1.6: a 6 MHz / +25 dB / duty-1.0 emitter
    (which the *temporal* per-bin floor nf_k fully absorbs -- design doc
    measured occ6 0.000, peak_to_floor 0.5 dB pre-fix) must instead read as
    persistently occupied via the window-internal spectral floor nfs_k, be
    (near-)invariant to +20 dB gain and +-3/+-6 dB linear tilt, read ~0
    occupancy on noise, and separate persistent vs. bursty occupancy via
    frac_time_occupied at duty 0.20."""
    rng = np.random.default_rng(105)
    n_ms = 1000
    base = _base_tensor(rng, n_ms)
    emitter = _add_band(base, center_hz=0.0, width_hz=6.0e6,
                        level_above_floor_db=25.0, duty=1.0)

    r = extract_features_v2(emitter, None, FS)
    names = list(r.names)

    def g6(name):
        return float(r.vector[names.index(name)])

    assert abs(g6("g6_occ_frac_6db") - 0.6) < 0.1
    assert abs(g6("g6_persistent_bw_hz") - 6.0e6) < 0.5e6
    assert abs(g6("g6_frac_time_occupied") - 1.0) < 0.05
    assert g6("g6_floor_delta_db") > 15.0  # design doc measured ~23.9 dB

    # +20 dB gain invariance
    r_boost = extract_features_v2(emitter + 20.0, None, FS)
    diff_boost = np.abs(r.vector[G6_SLICE].astype(np.float64) - r_boost.vector[G6_SLICE].astype(np.float64))
    assert np.max(diff_boost) < 1e-3, f"G6 not gain-invariant: max diff {np.max(diff_boost)}"

    # +-3 / +-6 dB linear tilt invariance
    for tilt_db in (3.0, -3.0, 6.0, -6.0):
        tilt = tilt_db * (_FULL_FREQS / _FULL_FREQS.max())
        tilted = emitter + tilt[None, :].astype(np.float32)
        r_tilt = extract_features_v2(tilted, None, FS)
        diff_tilt = np.abs(r.vector[G6_SLICE].astype(np.float64) - r_tilt.vector[G6_SLICE].astype(np.float64))
        assert np.max(diff_tilt) < 1.5, f"G6 not tilt-invariant at {tilt_db} dB: max diff {np.max(diff_tilt)}"

    # noise-only
    rng_noise = np.random.default_rng(106)
    noise_only = _base_tensor(rng_noise, n_ms)
    r_noise = extract_features_v2(noise_only, None, FS)
    assert g6_of(r_noise, names, "g6_occ_frac_6db") < 0.05
    assert g6_of(r_noise, names, "g6_floor_delta_db") < 2.0

    # duty 0.20: same emitter, occupancy fraction (p99-over-time-based)
    # stays roughly the same, but frac_time_occupied separates it as bursty.
    rng2 = np.random.default_rng(107)
    base2 = _base_tensor(rng2, n_ms)
    emitter_burst = _add_band(base2, center_hz=0.0, width_hz=6.0e6,
                              level_above_floor_db=25.0, duty=0.20)
    r_burst = extract_features_v2(emitter_burst, None, FS)
    assert abs(g6_of(r_burst, names, "g6_frac_time_occupied") - 0.20) < 0.1


def g6_of(result, names, name):
    return float(result.vector[names.index(name)])


def test_noise_scale_self_normalisation():
    """S1.6 Q4: g5_flux_*, the per-sub-band (p90-p50) spread, and G1's p99
    column are self-normalised against the 32 quietest sub-bands. Design
    doc measured raw g5_flux_p50 150/226/451/754 and raw g1_sb00_p99
    0.73/1.08/2.16/3.51 for per-bin noise sigma 0.2/0.3/0.6/1.0 dB -- a ~5x
    swing driven purely by receiver noise-fluctuation scale. After
    self-normalisation the same sigma sweep should differ by far less."""
    n_ms = 300
    rng_a = np.random.default_rng(201)
    rng_b = np.random.default_rng(202)
    tensor_a = _base_tensor(rng_a, n_ms, std=0.3)
    tensor_b = _base_tensor(rng_b, n_ms, std=1.0)

    r_a = extract_features_v2(tensor_a, None, FS)
    r_b = extract_features_v2(tensor_b, None, FS)
    names = list(r_a.names)

    flux_a = float(r_a.vector[names.index("g5_flux_p50")])
    flux_b = float(r_b.vector[names.index("g5_flux_p50")])
    assert abs(flux_a - flux_b) < 0.10 * max(abs(flux_a), abs(flux_b), 1.0), (
        f"g5_flux_p50 not noise-scale invariant: {flux_a} vs {flux_b}"
    )

    p99_names = [n for n in names if n.endswith("_p99") and n.startswith("g1_sb")]
    p99_a = r_a.vector[[names.index(n) for n in p99_names]].astype(np.float64)
    p99_b = r_b.vector[[names.index(n) for n in p99_names]].astype(np.float64)
    assert np.max(np.abs(p99_a - p99_b)) < 1.0, (
        f"g1_*_p99 not noise-scale invariant: max abs diff {np.max(np.abs(p99_a - p99_b))}"
    )

    p90p50_names = [n for n in names if n.startswith("g5_sb") and n.endswith("_p90_p50")]
    pp_a = r_a.vector[[names.index(n) for n in p90p50_names]].astype(np.float64)
    pp_b = r_b.vector[[names.index(n) for n in p90p50_names]].astype(np.float64)
    assert np.max(np.abs(pp_a - pp_b)) < 1.0, (
        f"g5_sbXX_p90_p50 not noise-scale invariant: max abs diff {np.max(np.abs(pp_a - pp_b))}"
    )
