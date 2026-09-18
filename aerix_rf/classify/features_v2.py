"""``features_v2``: absolute-Hz, receiver-independent Stage-2 feature vector.

Implements ``docs/design/features-and-benchmark.md`` S1, including the
"Implementation review 2026-09-18" (S1.6, rf-dsp-specialist) must-fixes
M1-M5 and the new G6 group. Unlike ``classify/train/features.py`` (frozen as
``features_v1``: a *fraction of the captured band*, rate-locked to whatever
the training set used), this module operates on the canonical
``[n_ms x 1024]`` dBFS tensor produced by ``aerix_rf/datasets/tensor.py``
(FFT 1024 / hop 512 at 15.36 MS/s) and expresses every level feature
relative to a **per-bin** noise floor, over a fixed absolute-Hz band (the
HackRF/ANTSDR common usable band, +-4.995 MHz around the tuned centre). This
is what makes a live window and a training window produce byte-identical
vectors regardless of receiver gain, ADC bit-depth, or analog passband shape
(see the design doc S1.4 "device-confound list").

Pure function, no I/O, no sklearn. The 302-D name list (:func:`feature_names_v2`)
is the contract; any change to it is a breaking bundle-format change. As of
this pass no trained bundle exists yet for ``features_v2`` (F2/F3 have not
trained anything), so the 292 -> 302 dimension change here is free -- see
S1.6 "Tests and sequencing".

Feature groups (see the design doc S1.3/S1.6 for the full rationale):

    G1  192  per sub-band (64 sub-bands) median/p90/p99 of R = T - nf_k over
              time. The p99 column is self-normalised against the 32
              quietest sub-bands (S1.6 Q4) to remove the receiver
              noise-fluctuation-scale leak; median/p90 carry duty and are
              left alone.
    G2    8  band scalars (flatness, freq-kurtosis/skew, p99-p50 spread,
              occupied-bin fraction @ +6/+10 dB, peak-to-floor dB, centroid
              offset in absolute Hz), fed by ``r_shape = percentile(R, 99,
              axis=0)`` (M1), not the time-median -- the median is blind to
              duty < 0.5.
    G3   12  occupancy/cadence, derived from 200 us detector frames;
              requires >= 100 ms of observation, else masked invalid. Floor
              is ``nf0_det``, computed from the detector frames themselves
              (M4), not the 30-average ``ml_tensor``; the on/off statistic
              is greatest-of over the 64 sub-bands, not a band mean (M4);
              the autocorrelation lag uses unbiased normalisation and the
              first local max after the first zero crossing (M5).
    G4   10  occupied bandwidth / roll-off / cluster shape, fed by
              ``r_shape`` (M1); zero-gated below a +6 dB peak and with a
              documented roll-off clamp for coincident contours
              (should-fix).
    G5   70  time-frequency dynamics; the flux/hop/multi-cluster/BW-jitter
              part requires >= 100 ms of observation like G3. Argmax
              hop/spread are computed over the 64 sub-band means, gated on
              a +6 dB band-max and a >=2-sub-band hop definition (M3), not
              the raw per-bin argmax (which is noise-dominated). Flux and
              the per-sub-band (p90-p50) spread are self-normalised against
              the 32 quietest sub-bands (S1.6 Q4).
    G6   10  window-internal-spectral-floor group (M2/G6, new): occupied
              fraction at +6/+20 dB, persistent occupied bandwidth, widest
              persistent cluster, occupied-level p50/p90, centroid, occupied
              flatness, fraction of *frames* with any sub-band above the
              window-internal floor + 6 dB, and floor_delta_db (how much
              the temporal per-bin floor ``nf_k`` was pulled up by a
              high-duty/continuous emitter relative to the window-internal
              spectral floor ``nfs_k``). G1-G5's per-bin temporal floor
              ``nf_k`` absorbs any emitter with duty > ~0.9; G6 is the fix,
              using a deg-2 polynomial fit of the quietest in-band bins
              instead of a per-bin time percentile.

``nf0`` (the scalar, absolute-dBFS floor from the 30-average tensor) is
deliberately *excluded* from the vector -- it is the single strongest
receiver fingerprint (S1.2) -- and is returned separately in
:class:`FeaturesV2.nf0_dbfs` for diagnostics only. ``nfs_k`` (the G6
window-internal spectral floor) is purely window-local (no cross-window
state) and also never enters the vector directly, only via G6's derived
scalars.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..datasets import tensor as _tensor

CANONICAL_FFT = _tensor.CANONICAL_FFT  # 1024
CANONICAL_FS = 15_360_000.0

# S1.1: exact common-band bin range (inclusive), DC notch (inclusive), grid.
BIN_LO = 179
BIN_HI = 845
N_BAND_BINS = BIN_HI - BIN_LO + 1  # 667
DC_LO = 510
DC_HI = 514
N_SUBBANDS = 64
BIN_HZ = CANONICAL_FS / CANONICAL_FFT  # 15 000 Hz

_FULL_FREQS = np.fft.fftshift(np.fft.fftfreq(CANONICAL_FFT, d=1.0 / CANONICAL_FS))
FREQS_BAND = _FULL_FREQS[BIN_LO:BIN_HI + 1].astype(np.float64)  # (667,)

_SUBBAND_EDGES = tuple((j * N_BAND_BINS) // N_SUBBANDS for j in range(N_SUBBANDS + 1))
SUBBAND_CENTER_HZ = np.array(
    [FREQS_BAND[_SUBBAND_EDGES[j]:_SUBBAND_EDGES[j + 1]].mean() for j in range(N_SUBBANDS)],
    dtype=np.float64,
)

# Local (band-relative) DC-notch bounds: k in [510,514] absolute -> [331,335] local.
_DC_LOCAL_LO = DC_LO - BIN_LO
_DC_LOCAL_HI = DC_HI - BIN_LO
_DC_LEFT = _DC_LOCAL_LO - 1   # 330
_DC_RIGHT = _DC_LOCAL_HI + 1  # 336

_EPS = 1e-6
_FRAME_DT_S = 200e-6  # 200 us detector frames (factor 6 at hop 512 / 15.36 MS/s)

# M1: shape statistic feeding G2/G4/centroid, and its moment dead-zone.
_Q_SHAPE = 99.0
_MOMENT_DEADZONE_DB = 3.0

# Should-fix: G4 zero-gate + roll-off clamp for coincident/unoccupied contours.
_G4_PEAK_GATE_DB = 6.0
# Steepest slope resolvable at 1-bin (15 kHz) resolution: a 10 dB drop
# within one bin. Used as a documented sentinel instead of 0 (which reads
# "flat") or inf (which is unusable downstream) when the -3 dB and -10 dB
# (or -10/-20 dB) contours land on the same bin.
ROLLOFF_CLAMP_DB_PER_MHZ = 10.0 / (BIN_HZ / 1.0e6)  # ~666.7 dB/MHz

# M2/G6: window-internal spectral floor (deg-2 polyfit of the quietest
# in-band bins, one refit pass, fallback to a flat p10 floor).
_NFS_DEG = 2
_NFS_QUIET_FRAC = 0.30
_NFS_REFIT_RESIDUAL_DB = 3.0
_NFS_MIN_SURVIVORS = 40
_X_AXIS = ((BIN_LO + np.arange(N_BAND_BINS, dtype=np.float64)) - 512.0) / 333.0

# S1.6 Q4: self-normalisation reference set size.
_N_QUIET_SUBBANDS = 32

_G1_LEN, _G2_LEN, _G3_LEN, _G4_LEN, _G5_LEN, _G6_LEN = 192, 8, 12, 10, 70, 10
FEATURES_V2_DIM = _G1_LEN + _G2_LEN + _G3_LEN + _G4_LEN + _G5_LEN + _G6_LEN  # 302

G1_SLICE = slice(0, _G1_LEN)
G2_SLICE = slice(_G1_LEN, _G1_LEN + _G2_LEN)
G3_SLICE = slice(G2_SLICE.stop, G2_SLICE.stop + _G3_LEN)
G4_SLICE = slice(G3_SLICE.stop, G3_SLICE.stop + _G4_LEN)
G5_SLICE = slice(G4_SLICE.stop, G4_SLICE.stop + _G5_LEN)
G6_SLICE = slice(G5_SLICE.stop, G5_SLICE.stop + _G6_LEN)

FEATURES_VERSION = "features_v2"


def _build_names() -> tuple[str, ...]:
    g1 = [
        f"g1_sb{j:02d}_{stat}"
        for j in range(N_SUBBANDS)
        for stat in ("median", "p90", "p99")
    ]
    g2 = [
        "g2_flatness",
        "g2_freq_kurtosis",
        "g2_freq_skew",
        "g2_p99_p50_spread_db",
        "g2_occ_frac_6db",
        "g2_occ_frac_10db",
        "g2_peak_to_floor_db",
        "g2_centroid_offset_hz",
    ]
    g3 = [
        "g3_duty_cycle",
        "g3_bursts_per_s",
        "g3_burst_dur_p10_ms",
        "g3_burst_dur_p50_ms",
        "g3_burst_dur_p90_ms",
        "g3_ibi_p10_ms",
        "g3_ibi_p50_ms",
        "g3_ibi_p90_ms",
        "g3_autocorr_peak",
        "g3_autocorr_lag_ms",
        "g3_frac_frames_floor6db",
        "g3_on_off_power_ratio",
    ]
    g4 = [
        "g4_bw_m3db_hz",
        "g4_bw_m10db_hz",
        "g4_bw_m20db_hz",
        "g4_rolloff_left_db_per_mhz",
        "g4_rolloff_right_db_per_mhz",
        "g4_flat_top_ratio",
        "g4_n_clusters",
        "g4_widest_cluster_bw_hz",
        "g4_cluster_bw_p50_hz",
        "g4_symmetry",
    ]
    g5 = [f"g5_sb{j:02d}_p90_p50" for j in range(N_SUBBANDS)] + [
        "g5_flux_p50",
        "g5_flux_p90",
        "g5_argmax_hop_rate",
        "g5_argmax_spread_hz",
        "g5_frac_multicluster",
        "g5_bw_time_std_hz",
    ]
    g6 = [
        "g6_occ_frac_6db",
        "g6_occ_frac_20db",
        "g6_persistent_bw_hz",
        "g6_widest_cluster_hz",
        "g6_level_p50_db",
        "g6_level_p90_db",
        "g6_centroid_hz",
        "g6_flatness_occupied",
        "g6_frac_time_occupied",
        "g6_floor_delta_db",
    ]
    names = tuple(g1 + g2 + g3 + g4 + g5 + g6)
    assert len(names) == FEATURES_V2_DIM, len(names)
    assert len(set(names)) == FEATURES_V2_DIM, "duplicate feature name"
    return names


FEATURE_NAMES = _build_names()


def feature_names_v2() -> tuple[str, ...]:
    """The fixed, ordered 302-name contract for ``features_v2``."""
    return FEATURE_NAMES


@dataclass(frozen=True)
class FeaturesV2:
    vector: np.ndarray          # float32 [302]
    valid_mask: np.ndarray      # bool [302], False where G3/G5 are undefined
    nf0_dbfs: float             # scalar in-band floor, diagnostics only, not in vector
    version: str = FEATURES_VERSION
    names: tuple[str, ...] = FEATURE_NAMES


def _interp_dc_notch(band: np.ndarray) -> np.ndarray:
    """Replace local columns [_DC_LOCAL_LO, _DC_LOCAL_HI] with a linear
    interpolation between the columns immediately outside the notch,
    per row (S1.1 DC notch)."""
    out = band.copy()
    if band.shape[0] == 0:
        return out
    left_vals = band[:, _DC_LEFT]
    right_vals = band[:, _DC_RIGHT]
    idxs = np.arange(_DC_LEFT + 1, _DC_RIGHT)
    span = float(_DC_RIGHT - _DC_LEFT)
    fracs = (idxs - _DC_LEFT) / span
    out[:, idxs] = left_vals[:, None] * (1.0 - fracs)[None, :] + right_vals[:, None] * fracs[None, :]
    return out


def _clusters(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs of a 1-D boolean array as (start, end) inclusive
    index pairs, in ascending order. No wrap-around."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    return list(zip(starts.tolist(), ends.tolist()))


def _quiet_bin_mask(quiet_idx: np.ndarray) -> np.ndarray:
    mask = np.zeros(N_BAND_BINS, dtype=bool)
    for j in quiet_idx:
        lo, hi = _SUBBAND_EDGES[int(j)], _SUBBAND_EDGES[int(j) + 1]
        mask[lo:hi] = True
    return mask


def _g1_subband_levels(r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """G1: per sub-band median/p90/p99 of ``r`` over time. S1.6 Q4:
    ``p99`` is self-normalised by subtracting the median p99 of the
    ``_N_QUIET_SUBBANDS`` quietest sub-bands (ranked by their own raw p99),
    which removes the ADC/decimation noise-fluctuation-scale leak on
    background windows without touching median/p90 (which carry duty).
    Returns ``(g1_vector[192], quiet_subband_idx)`` -- the latter is reused
    by G5 for the same self-normalisation reference set."""
    meds = np.zeros(N_SUBBANDS, dtype=np.float64)
    p90s = np.zeros(N_SUBBANDS, dtype=np.float64)
    raw_p99 = np.zeros(N_SUBBANDS, dtype=np.float64)
    for j in range(N_SUBBANDS):
        lo, hi = _SUBBAND_EDGES[j], _SUBBAND_EDGES[j + 1]
        flat = r[:, lo:hi].reshape(-1)
        if flat.size:
            med, p90, p99 = np.percentile(flat, (50.0, 90.0, 99.0))
        else:
            med, p90, p99 = 0.0, 0.0, 0.0
        meds[j], p90s[j], raw_p99[j] = med, p90, p99

    n_quiet = min(_N_QUIET_SUBBANDS, N_SUBBANDS)
    quiet_idx = np.argsort(raw_p99, kind="stable")[:n_quiet]
    quiet_ref = float(np.median(raw_p99[quiet_idx])) if n_quiet else 0.0
    p99_norm = raw_p99 - quiet_ref

    out = np.zeros(_G1_LEN, dtype=np.float64)
    for j in range(N_SUBBANDS):
        out[3 * j:3 * j + 3] = (meds[j], p90s[j], p99_norm[j])
    return out, quiet_idx


def _weighted_moments(shape_db: np.ndarray, deadzone_db: float = _MOMENT_DEADZONE_DB) -> tuple[float, float, float]:
    """(centroid_hz, skew, kurtosis) of a relative-dB PSD shape statistic,
    weighted by excess linear power above the local floor (P - 1, clipped
    at 0), with a +``deadzone_db`` dead-zone: bins at or below the
    dead-zone get zero weight regardless of their linear-power excess (M1),
    so residual per-bin noise fluctuation cannot pull the centroid/moments
    away from the true occupied region. Returns neutral zeros / peak-bin
    centre when there is no signal above the dead-zone."""
    power = np.power(10.0, shape_db / 10.0)
    weight = np.where(shape_db > deadzone_db, np.clip(power - 1.0, 0.0, None), 0.0)
    total = float(weight.sum())
    if total <= _EPS:
        peak_idx = int(np.argmax(shape_db)) if shape_db.size else N_BAND_BINS // 2
        return float(FREQS_BAND[peak_idx]), 0.0, 0.0
    mean_f = float(np.sum(weight * FREQS_BAND) / total)
    var_f = float(np.sum(weight * (FREQS_BAND - mean_f) ** 2) / total)
    if var_f <= _EPS:
        return mean_f, 0.0, 0.0
    skew = float(np.sum(weight * (FREQS_BAND - mean_f) ** 3) / total) / var_f ** 1.5
    kurt = float(np.sum(weight * (FREQS_BAND - mean_f) ** 4) / total) / var_f ** 2 - 3.0
    return mean_f, skew, kurt


def _g2_band_scalars(r_shape: np.ndarray) -> np.ndarray:
    """G2 band scalars, fed by ``r_shape = percentile(R, 99, axis=0)``
    (M1) rather than the time-median, which is blind to duty < 0.5."""
    if r_shape.size == 0:
        return np.zeros(_G2_LEN, dtype=np.float64)
    power = np.power(10.0, r_shape / 10.0)
    flatness = float(np.exp(np.mean(np.log(power + _EPS))) / (np.mean(power) + _EPS))
    centroid_hz, skew, kurt = _weighted_moments(r_shape)
    p99_p50 = float(np.percentile(r_shape, 99.0) - np.percentile(r_shape, 50.0))
    occ6 = float(np.mean(r_shape > 6.0))
    occ10 = float(np.mean(r_shape > 10.0))
    peak_floor = float(np.max(r_shape))
    return np.array(
        [flatness, kurt, skew, p99_p50, occ6, occ10, peak_floor, centroid_hz],
        dtype=np.float64,
    )


def _cluster_containing(mask: np.ndarray, anchor: int) -> tuple[int, int]:
    for s, e in _clusters(mask):
        if s <= anchor <= e:
            return s, e
    return anchor, anchor


def _clamped_rolloff(near_db: float, far_db: float, span_mhz: float) -> float:
    """dB/MHz slope, clamped to +-``ROLLOFF_CLAMP_DB_PER_MHZ`` (should-fix:
    coincident -3/-10 dB contours used to silently read 0 dB/MHz, i.e. the
    same encoding as "no roll-off" / a flat-topped signal)."""
    if span_mhz <= (BIN_HZ / 1.0e6) / 2.0:
        return ROLLOFF_CLAMP_DB_PER_MHZ
    value = (near_db - far_db) / span_mhz
    return float(np.clip(value, -ROLLOFF_CLAMP_DB_PER_MHZ, ROLLOFF_CLAMP_DB_PER_MHZ))


def _g4_bandwidth_shape(r_shape: np.ndarray) -> np.ndarray:
    """G4 bandwidth/shape, fed by ``r_shape`` (M1). Should-fix: gated to
    all-zero when the in-band peak is below +6 dB (an unoccupied window
    used to read as a band-filling 10 MHz signal, bw3==bw10==bw20)."""
    if r_shape.size == 0 or float(np.max(r_shape)) < _G4_PEAK_GATE_DB:
        return np.zeros(_G4_LEN, dtype=np.float64)

    peak = float(np.max(r_shape))
    peak_idx = int(np.argmax(r_shape))
    s3, e3 = _cluster_containing(r_shape >= (peak - 3.0), peak_idx)
    s10, e10 = _cluster_containing(r_shape >= (peak - 10.0), peak_idx)
    s20, e20 = _cluster_containing(r_shape >= (peak - 20.0), peak_idx)
    bw3 = (e3 - s3 + 1) * BIN_HZ
    bw10 = (e10 - s10 + 1) * BIN_HZ
    bw20 = (e20 - s20 + 1) * BIN_HZ

    left_mhz = (FREQS_BAND[s3] - FREQS_BAND[s10]) / 1.0e6
    rolloff_left = _clamped_rolloff(r_shape[s3], r_shape[s10], left_mhz)
    right_mhz = (FREQS_BAND[e10] - FREQS_BAND[e3]) / 1.0e6
    rolloff_right = _clamped_rolloff(r_shape[e3], r_shape[e10], right_mhz)

    flat_top_ratio = float(bw3 / bw20) if bw20 > 0 else 0.0

    clusters6 = _clusters(r_shape >= 6.0)
    n_clusters = float(len(clusters6))
    widths = [(e - s + 1) * BIN_HZ for s, e in clusters6]
    widest = float(max(widths)) if widths else 0.0
    med_width = float(np.median(widths)) if widths else 0.0

    centroid_hz, _, _ = _weighted_moments(r_shape)
    left_extent = centroid_hz - FREQS_BAND[s3]
    right_extent = FREQS_BAND[e3] - centroid_hz
    denom = abs(left_extent) + abs(right_extent)
    symmetry = float(1.0 - abs(left_extent - right_extent) / denom) if denom > _EPS else 1.0
    symmetry = float(np.clip(symmetry, 0.0, 1.0))

    return np.array(
        [bw3, bw10, bw20, rolloff_left, rolloff_right, flat_top_ratio,
         n_clusters, widest, med_width, symmetry],
        dtype=np.float64,
    )


def _compute_nf0_det(band_lin: np.ndarray) -> float:
    """M4: G3's floor, derived from the detector frames themselves (not
    the 30-average ``ml_tensor``, which silently shifts +3/+6 dB relative
    to ``dsp/spectrogram.py``'s ~6 dB different scaling)."""
    n = band_lin.shape[0]
    if n == 0:
        return 0.0
    db = 10.0 * np.log10(np.maximum(band_lin, 1e-12))
    nf_k_det = np.percentile(db, 10.0, axis=0)
    return float(np.median(nf_k_det))


def _autocorr_peak_lag(x: np.ndarray, dt_s: float) -> tuple[float, float]:
    """M5: unbiased-normalised autocorrelation peak height + lag (ms).

    The naive biased-normalisation ACF's global non-zero-lag max is at lag
    1 for any smooth series (measured: peak 0.999 at 0.200 ms on a
    periodic burst train), because the ``1/n`` biased estimator tapers
    monotonically with lag. Dividing by ``n - lag`` (unbiased) removes that
    taper; the *first local max after the first zero crossing* is then the
    fundamental period, not an autocorrelation-function artefact. Lag is
    capped at ``n // 2``."""
    n = x.size
    if n < 4:
        return 0.0, 0.0
    x = x - np.mean(x)
    max_lag = n // 2
    if max_lag < 1:
        return 0.0, 0.0
    full = np.correlate(x, x, mode="full")
    mid = n - 1
    raw = full[mid:mid + max_lag + 1]
    counts = (n - np.arange(0, max_lag + 1)).astype(np.float64)
    ac = raw / counts
    if ac[0] <= _EPS:
        return 0.0, 0.0
    ac = ac / ac[0]

    zero_idx = None
    for lag in range(1, max_lag + 1):
        if ac[lag] <= 0.0:
            zero_idx = lag
            break
    if zero_idx is None or zero_idx >= max_lag:
        return 0.0, 0.0

    peak_lag = None
    for lag in range(zero_idx, max_lag):
        if ac[lag] >= ac[lag - 1] and ac[lag] >= ac[lag + 1]:
            peak_lag = lag
            break
    if peak_lag is None:
        seg = ac[zero_idx:max_lag + 1]
        peak_lag = zero_idx + int(np.argmax(seg))

    return float(ac[peak_lag]), float(peak_lag * dt_s * 1000.0)


def _g3_occupancy_cadence(band_lin: np.ndarray, nf0_det_dbfs: float) -> np.ndarray:
    """G3 occupancy/cadence. M4: the on/off statistic is greatest-of over
    the 64 sub-bands (a 300 kHz burst needs ~+21 dB per-bin SNR to cross
    +3 dB as a band mean over 667 bins); M5: the autocorrelation uses
    :func:`_autocorr_peak_lag`."""
    n_frames = band_lin.shape[0]
    if n_frames == 0:
        return np.zeros(_G3_LEN, dtype=np.float64)

    subband_power = np.zeros((n_frames, N_SUBBANDS), dtype=np.float64)
    for j in range(N_SUBBANDS):
        lo, hi = _SUBBAND_EDGES[j], _SUBBAND_EDGES[j + 1]
        subband_power[:, j] = np.mean(band_lin[:, lo:hi], axis=1)
    greatest_power = np.max(subband_power, axis=1)  # M4: greatest-of, not band-mean
    frame_db = 10.0 * np.log10(np.maximum(greatest_power, 1e-12))

    thr_soft = nf0_det_dbfs + 3.0
    thr_hard = nf0_det_dbfs + 6.0
    on_soft = frame_db > thr_soft
    on_hard = frame_db > thr_hard

    duty = float(np.mean(on_soft))
    frac_hard = float(np.mean(on_hard))

    total_time = n_frames * _FRAME_DT_S
    bursts = _clusters(on_soft)
    n_bursts = len(bursts)
    bursts_per_s = float(n_bursts / total_time) if total_time > 0 else 0.0

    if bursts:
        durs_ms = np.array([(e - s + 1) * _FRAME_DT_S * 1000.0 for s, e in bursts])
        d10, d50, d90 = np.percentile(durs_ms, (10.0, 50.0, 90.0))
    else:
        d10 = d50 = d90 = 0.0

    if len(bursts) >= 2:
        starts_ms = np.array([s * _FRAME_DT_S * 1000.0 for s, _ in bursts])
        ibi = np.diff(starts_ms)
        i10, i50, i90 = np.percentile(ibi, (10.0, 50.0, 90.0))
    else:
        i10 = i50 = i90 = 0.0

    peak_height, lag_ms = _autocorr_peak_lag(frame_db, _FRAME_DT_S)

    on_vals = greatest_power[on_hard]
    off_vals = greatest_power[~on_hard]
    nf0_lin = 10.0 ** (nf0_det_dbfs / 10.0)
    on_mean = float(np.mean(on_vals)) if on_vals.size else nf0_lin
    off_mean = float(np.mean(off_vals)) if off_vals.size else nf0_lin
    on_off_ratio = float(on_mean / off_mean) if off_mean > 1e-12 else 0.0

    return np.array(
        [duty, bursts_per_s, d10, d50, d90, i10, i50, i90,
         peak_height, lag_ms, frac_hard, on_off_ratio],
        dtype=np.float64,
    )


def _g5_time_frequency(r: np.ndarray, quiet_idx: np.ndarray) -> np.ndarray:
    """G5 time-frequency dynamics.

    M3: argmax hop-rate/spread are computed over the 64 sub-band *means*
    per frame (not the raw per-bin argmax, which is noise-dominated: 667
    noise bins vs. a handful of signal bins), gated on a +6 dB band-max and
    a >=2-sub-band hop definition; spread is the std of the gated frames'
    sub-band centre frequencies only.

    S1.6 Q4: flux is self-normalised by dividing by the median per-frame
    flux of the ``_N_QUIET_SUBBANDS`` quietest sub-bands (``quiet_idx``,
    shared with G1); the per-sub-band (p90-p50) vector is self-normalised
    by subtracting the median of that same quiet-sub-band subset.
    """
    n_ms = r.shape[0]
    out64 = np.zeros(N_SUBBANDS, dtype=np.float64)
    for j in range(N_SUBBANDS):
        lo, hi = _SUBBAND_EDGES[j], _SUBBAND_EDGES[j + 1]
        flat = r[:, lo:hi].reshape(-1)
        if flat.size:
            p50, p90 = np.percentile(flat, (50.0, 90.0))
            out64[j] = p90 - p50

    if n_ms == 0:
        tail = np.zeros(6, dtype=np.float64)
        return np.concatenate([out64, tail])

    quiet_ref = float(np.median(out64[quiet_idx])) if quiet_idx.size else 0.0
    out64_norm = out64 - quiet_ref

    subband_means = np.zeros((n_ms, N_SUBBANDS), dtype=np.float64)
    for j in range(N_SUBBANDS):
        lo, hi = _SUBBAND_EDGES[j], _SUBBAND_EDGES[j + 1]
        subband_means[:, j] = np.mean(r[:, lo:hi], axis=1)
    band_max = np.max(subband_means, axis=1)
    gate = band_max >= _G4_PEAK_GATE_DB
    argmax_sb = np.argmax(subband_means, axis=1)
    gated = argmax_sb[gate]
    if gated.size >= 2:
        diffs = np.abs(np.diff(gated))
        hop_rate = float(np.mean(diffs >= 2))
        spread_hz = float(np.std(SUBBAND_CENTER_HZ[gated]))
    else:
        hop_rate = 0.0
        spread_hz = 0.0

    if n_ms >= 2:
        flux = np.sum(np.abs(np.diff(r, axis=0)), axis=1)
        flux_p50_raw, flux_p90_raw = np.percentile(flux, (50.0, 90.0))
        quiet_mask = _quiet_bin_mask(quiet_idx)
        if np.any(quiet_mask):
            flux_quiet = np.sum(np.abs(np.diff(r[:, quiet_mask], axis=0)), axis=1)
            ref_scale = max(float(np.median(flux_quiet)), _EPS)
        else:
            ref_scale = _EPS
        flux_p50 = float(flux_p50_raw / ref_scale)
        flux_p90 = float(flux_p90_raw / ref_scale)
    else:
        flux_p50 = flux_p90 = 0.0

    mask_frames = r >= 6.0
    n_multi = 0
    bw_list = np.zeros(n_ms, dtype=np.float64)
    for t in range(n_ms):
        idx = np.flatnonzero(mask_frames[t])
        if idx.size:
            clusters_t = _clusters(mask_frames[t])
            if len(clusters_t) > 1:
                n_multi += 1
            bw_list[t] = (idx.max() - idx.min() + 1) * BIN_HZ
    frac_multi = float(n_multi / n_ms)
    bw_std = float(np.std(bw_list))

    tail = np.array([flux_p50, flux_p90, hop_rate, spread_hz, frac_multi, bw_std], dtype=np.float64)
    return np.concatenate([out64_norm, tail])


def _compute_nfs_k(S: np.ndarray) -> np.ndarray:
    """M2: window-internal spectral floor. ``S`` is the absolute-dB,
    p99-over-time PSD (``percentile(band, 99, axis=0)``). A deg-2
    polynomial in ``x = (k_abs - 512) / 333`` is fit over the quietest
    ``_NFS_QUIET_FRAC`` of in-band bins, then refit once over bins whose
    residual against that first fit is <= ``_NFS_REFIT_RESIDUAL_DB``;
    falls back to a flat ``percentile(S, 10)`` floor if fewer than
    ``_NFS_MIN_SURVIVORS`` bins survive the refit selection (or the fit is
    degenerate)."""
    n = S.size
    if n == 0:
        return S.copy()

    def _flat_fallback() -> np.ndarray:
        return np.full(n, float(np.percentile(S, 10.0)), dtype=np.float64)

    n_quiet = max(_NFS_DEG + 1, int(round(_NFS_QUIET_FRAC * n)))
    order = np.argsort(S, kind="stable")
    quiet_idx = order[:n_quiet]
    try:
        coeffs0 = np.polyfit(_X_AXIS[quiet_idx], S[quiet_idx], _NFS_DEG)
    except (np.linalg.LinAlgError, ValueError):
        return _flat_fallback()
    fit0 = np.polyval(coeffs0, _X_AXIS)
    residual = S - fit0
    survive_idx = np.flatnonzero(residual <= _NFS_REFIT_RESIDUAL_DB)
    if survive_idx.size < _NFS_MIN_SURVIVORS:
        return _flat_fallback()
    try:
        coeffs1 = np.polyfit(_X_AXIS[survive_idx], S[survive_idx], _NFS_DEG)
    except (np.linalg.LinAlgError, ValueError):
        return _flat_fallback()
    return np.polyval(coeffs1, _X_AXIS)


def _g6_window_floor(band: np.ndarray, nf_k: np.ndarray) -> np.ndarray:
    """G6 (M2): occupancy/level/centroid group derived from the
    window-internal spectral floor ``nfs_k`` (:func:`_compute_nfs_k`),
    which does not absorb high-duty/continuous emitters the way the
    per-bin temporal floor ``nf_k`` does."""
    n_ms = band.shape[0]
    if n_ms == 0:
        return np.zeros(_G6_LEN, dtype=np.float64)

    S = np.percentile(band, _Q_SHAPE, axis=0)
    nfs_k = _compute_nfs_k(S)
    rs_shape = S - nfs_k

    mask6 = rs_shape > 6.0
    occ6 = float(np.mean(mask6))
    occ20 = float(np.mean(rs_shape > 20.0))

    clusters6 = _clusters(mask6)
    widths = [(e - s + 1) * BIN_HZ for s, e in clusters6]
    persistent_bw = float(sum(widths)) if widths else 0.0
    widest = float(max(widths)) if widths else 0.0

    if np.any(mask6):
        level_p50 = float(np.percentile(rs_shape[mask6], 50.0))
        level_p90 = float(np.percentile(rs_shape[mask6], 90.0))
        power = np.power(10.0, rs_shape[mask6] / 10.0)
        flatness_occ = float(np.exp(np.mean(np.log(power + _EPS))) / (np.mean(power) + _EPS))
    else:
        level_p50 = level_p90 = 0.0
        flatness_occ = 0.0

    centroid_hz, _, _ = _weighted_moments(rs_shape)

    rs_band = band - nfs_k[None, :]
    frame_max = np.max(rs_band, axis=1)
    frac_time = float(np.mean(frame_max > 6.0))

    floor_delta = float(np.median(nf_k - nfs_k))

    return np.array(
        [occ6, occ20, persistent_bw, widest, level_p50, level_p90,
         centroid_hz, flatness_occ, frac_time, floor_delta],
        dtype=np.float64,
    )


def extract_features_v2(
    tensor_dbfs: np.ndarray,
    detector_frames_lin: np.ndarray | None,
    fs_hz: float = CANONICAL_FS,
) -> FeaturesV2:
    """302-D ``features_v2`` vector from the canonical dBFS tensor.

    ``tensor_dbfs`` is ``ml_tensor(iq, fs)``'s output: float ``[n_ms, 1024]``
    dBFS. ``detector_frames_lin`` is ``detector_frames(power_lin)``'s output
    (200 us, *linear* power, ``[n_frames, 1024]``); pass ``None`` if
    unavailable, which invalidates G3 (occupancy/cadence). ``features_v2`` is
    defined only on the canonical 15.36 MS/s / FFT-1024 representation --
    both are checked and a mismatch raises.
    """
    tensor_dbfs = np.asarray(tensor_dbfs, dtype=np.float64)
    if tensor_dbfs.ndim != 2 or tensor_dbfs.shape[1] != CANONICAL_FFT:
        raise ValueError(
            f"features_v2 requires a [n_ms, {CANONICAL_FFT}] canonical tensor, "
            f"got shape {tensor_dbfs.shape!r}"
        )
    if abs(float(fs_hz) - CANONICAL_FS) > 1.0:
        raise ValueError(
            f"features_v2 is defined only on the canonical {CANONICAL_FS!r} Hz "
            f"representation, got fs_hz={fs_hz!r}"
        )

    n_ms = tensor_dbfs.shape[0]
    band = tensor_dbfs[:, BIN_LO:BIN_HI + 1]
    band = _interp_dc_notch(band)

    if n_ms > 0:
        nf_k = np.percentile(band, 10.0, axis=0)
    else:
        nf_k = np.zeros(N_BAND_BINS, dtype=np.float64)
    nf0 = float(np.median(nf_k)) if n_ms > 0 else 0.0
    r = band - nf_k[None, :]
    # M1: G2/G4/centroid are fed by the time-p99 shape statistic, not the
    # time-median (which is blind to duty < 0.5).
    r_shape = np.percentile(r, _Q_SHAPE, axis=0) if n_ms > 0 else np.zeros(N_BAND_BINS, dtype=np.float64)

    g1, quiet_idx = _g1_subband_levels(r)
    g2 = _g2_band_scalars(r_shape)
    g4 = _g4_bandwidth_shape(r_shape)
    g5 = _g5_time_frequency(r, quiet_idx)
    g6 = _g6_window_floor(band, nf_k)

    g3_ok = False
    if detector_frames_lin is not None:
        dfl = np.asarray(detector_frames_lin, dtype=np.float64)
        if dfl.ndim == 2 and dfl.shape[1] == CANONICAL_FFT and dfl.shape[0] > 0:
            band_lin = _interp_dc_notch(dfl[:, BIN_LO:BIN_HI + 1])
            # M4: G3's floor comes from the detector frames themselves, not
            # the 30-average ml_tensor's nf0.
            nf0_det = _compute_nf0_det(band_lin)
            g3 = _g3_occupancy_cadence(band_lin, nf0_det)
            g3_ok = True
        else:
            g3 = np.zeros(_G3_LEN, dtype=np.float64)
    else:
        g3 = np.zeros(_G3_LEN, dtype=np.float64)

    vector = np.concatenate([g1, g2, g3, g4, g5, g6])
    vector = np.nan_to_num(vector, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    valid = np.ones(FEATURES_V2_DIM, dtype=bool)
    if n_ms < 100 or not g3_ok:
        valid[G3_SLICE] = False
    if n_ms < 100:
        valid[G5_SLICE] = False

    return FeaturesV2(vector=vector, valid_mask=valid, nf0_dbfs=nf0, names=FEATURE_NAMES)


def features_v2_from_iq(iq: np.ndarray, fs: float = CANONICAL_FS) -> FeaturesV2:
    """Convenience end-to-end path: raw canonical-rate IQ -> ``features_v2``.

    Runs the same canonical tensor pipeline (``aerix_rf/datasets/tensor.py``)
    that dataset normalisation uses, then :func:`extract_features_v2`. This
    is intended for offline analysis / tests; live/streaming code that
    already holds ``ml_tensor``/``detector_frames`` output should call
    :func:`extract_features_v2` directly rather than recomputing the STFT.
    """
    if abs(float(fs) - CANONICAL_FS) > 1.0:
        raise ValueError(
            f"features_v2_from_iq is defined only on the canonical "
            f"{CANONICAL_FS!r} Hz representation, got fs={fs!r}"
        )
    iq = np.asarray(iq)
    tensor_dbfs = _tensor.ml_tensor(iq, fs)
    stft = _tensor.canonical_stft(iq, fs)
    power_lin = (stft.real.astype(np.float64) ** 2 + stft.imag.astype(np.float64) ** 2)
    detector_frames_lin = _tensor.detector_frames(power_lin, factor=6)
    return extract_features_v2(tensor_dbfs, detector_frames_lin, fs_hz=fs)
