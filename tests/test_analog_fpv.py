"""T1 acceptance tests for aerix_rf.detect.analog_fpv (analog-fpv-detector.md).

Sweep rows are 500 kHz-bin, 5645-5945 MHz-style arrays. A planted carrier's
occupied-bandwidth shape is not hand-drawn: it comes from a Welch PSD of
``aerix_rf.dsp.fmvideo_sim.make_fm_video`` (default ``deviation_hz``, midband carrier convention),
binned to 500 kHz and embedded (power-summed) onto a floor, so the sweep
detector is exercised against the same generator T2 validates. All tests
seeded/deterministic.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import welch

from aerix_rf.detect import analog_fpv as afpv
from aerix_rf.detect.analog_fpv import dwell_confirm, sweep_candidates
from aerix_rf.detect.bursts import detect_bursts
from aerix_rf.dsp.fmvideo_sim import make_fm_video
from aerix_rf.scan.sweep import Baseline

BASE58 = ("/home/jarvis/rf-datasets/aerix_antsdr_ambient_2026_09_18/original/"
          "sweeps_2026_09_18/base_58.npz")

FLOOR_DB = -85.0
BIN_MHZ = 0.5
FREQS_MHZ = np.arange(5645.0, 5945.0, BIN_MHZ)


def _fmvideo_profile_db(deviation_hz: float = 2.7e6, fs: float = 20e6,
                         duration_s: float = 0.1, seed: int = 0):
    """(rel_freq_mhz, rel_db) of a Welch PSD of ``make_fm_video``, binned to
    500 kHz and peak-normalised to 0 dB -- the "shape" a real sweep would see."""
    iq = make_fm_video(fs, duration_s, deviation_hz=deviation_hz, audio_subcarriers=(), seed=seed)
    f, pxx = welch(iq, fs=fs, nperseg=4096, return_onesided=False, detrend=False)
    f = np.fft.fftshift(f)
    pxx = np.fft.fftshift(pxx)
    # Bin edges are offset by half a bin so a bin is CENTRED on rel=0 MHz
    # (the nominal carrier frequency), not split across a bin boundary
    # there. ``np.arange(-10e6, 10e6+bin_hz, bin_hz)`` puts an edge exactly
    # at 0 Hz, so the carrier's own PSD peak is arbitrarily divided between
    # the -0.25/+0.25 MHz bins depending on Welch-bin/FFT quantisation --
    # measured to bias the profile's own peak location by a full 250 kHz
    # (to +0.25 MHz) before this fix, which then propagates into a >500 kHz
    # sweep-detector centre-estimate bias once the profile is embedded on
    # the 500 kHz FREQS_MHZ test grid (see analog_fpv T1 handback).
    bin_hz = BIN_MHZ * 1e6
    edges = np.arange(-10e6 - bin_hz / 2.0, 10e6 + bin_hz, bin_hz)
    centers_mhz = ((edges[:-1] + edges[1:]) / 2) / 1e6
    idx = np.digitize(f, edges) - 1
    binned = np.zeros(len(centers_mhz))
    for k in range(len(centers_mhz)):
        m = idx == k
        binned[k] = pxx[m].sum() if m.any() else 0.0
    db = 10.0 * np.log10(binned + 1e-20)
    db -= db.max()
    return centers_mhz, db


_PROFILE_MHZ, _PROFILE_DB = _fmvideo_profile_db()


def _measured_bw_mhz(drop_db: float) -> float:
    """-drop_db occupied bandwidth of the cached fmvideo profile itself (a
    direct check of the generator, independent of the sweep detector).

    OUTERMOST crossings, not a contiguous walk outwards from the peak (T1
    correction 2026-09-19): an unsmoothed wideband-FM video spectrum has deep
    internal notches between its dwell lines (blanking line, sync-tip line,
    luma plateau), so a contiguous walk terminates at the first notch and
    understated the occupied bandwidth by ~1.6 MHz at -20 dB (4.0 vs 5.6 MHz)
    relative to what the detector -- which smooths over 3 bins first --
    actually measures on the same profile. Sub-bin edges by linear
    interpolation in dB, same convention as
    ``analog_fpv._band_edges_mhz``."""
    thresh = float(_PROFILE_DB.max()) - drop_db
    above = np.flatnonzero(_PROFILE_DB >= thresh)
    lo, hi = int(above[0]), int(above[-1])

    def _cross(i_in: int, i_out: int) -> float:
        y_in, y_out = float(_PROFILE_DB[i_in]), float(_PROFILE_DB[i_out])
        if y_in == y_out:
            return float(_PROFILE_MHZ[i_in])
        frac = (y_in - thresh) / (y_in - y_out)
        return float(_PROFILE_MHZ[i_in] + frac * (_PROFILE_MHZ[i_out] - _PROFILE_MHZ[i_in]))

    f_lo = _cross(lo, lo - 1) if lo > 0 else float(_PROFILE_MHZ[lo])
    f_hi = _cross(hi, hi + 1) if hi < len(_PROFILE_DB) - 1 else float(_PROFILE_MHZ[hi])
    return float(f_hi - f_lo)


def test_fmvideo_sim_occupied_bandwidth():
    """Document the achieved occupied bandwidth (design doc S8/S9 T2 acceptance)."""
    bw20 = _measured_bw_mhz(20.0)
    bw10 = _measured_bw_mhz(10.0)
    assert 5.0 <= bw20 <= 9.0, f"-20 dB occupied BW {bw20} MHz outside design target"
    assert 3.0 <= bw10 <= 7.0, f"-10 dB occupied BW {bw10} MHz outside design target"


def _embed_carrier(floor_db: np.ndarray, centre_mhz: float, delta_db: float,
                    freqs_mhz: np.ndarray = FREQS_MHZ) -> np.ndarray:
    """Add a carrier ``delta_db`` above the LOCAL floor at ``centre_mhz`` --
    a single reference level, not the (possibly structured, e.g. real-ambient
    seam-comb) per-bin ``floor_db`` array. A real VTX's transmitted power
    profile does not track the receiver's own noise-floor ripple at nearby
    frequencies; using the per-bin floor as an additive bias made the
    embedded carrier shape spuriously bulge wherever the real ambient
    baseline happened to have a bump (e.g. a sweep-step seam a couple of MHz
    away), biasing the parabolic centre estimate on the real-ambient test by
    ~700 kHz."""
    rel = freqs_mhz - centre_mhz
    sig_rel_db = np.interp(rel, _PROFILE_MHZ, _PROFILE_DB, left=-99.0, right=-99.0)
    local_floor_db = float(np.interp(centre_mhz, freqs_mhz, floor_db))
    sig_abs_db = local_floor_db + delta_db + sig_rel_db
    combined_lin = np.power(10.0, floor_db / 10.0) + np.power(10.0, sig_abs_db / 10.0)
    return 10.0 * np.log10(combined_lin)


def _flat_floor(rng: np.random.Generator | None = None, noise_std_db: float = 0.5) -> np.ndarray:
    floor = np.full(FREQS_MHZ.shape, FLOOR_DB)
    if rng is not None:
        floor = floor + rng.normal(0.0, noise_std_db, size=floor.shape)
    return floor


# A carrier present in EVERY sweep row cannot be found by self-baselining
# (median-across-rows collapses to the row itself when the signal is on
# 100% of the time -- scan/candidates.py's own documented self-baseline
# limitation). Tests with a persistent carrier therefore pass an explicit
# ambient-only baseline (the noise-free flat floor) rather than rely on
# ``baseline_db=None``.
_AMBIENT_BASELINE = np.full(FREQS_MHZ.shape, FLOOR_DB)


def _repeat_rows(row: np.ndarray, n: int) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(FREQS_MHZ, row.copy()) for _ in range(n)]


# --------------------------------------------------------------------------- #
# Stage A: sweep_candidates
# --------------------------------------------------------------------------- #

def test_persistent_raceband_pair_promotes_to_level2():
    """Two co-band Raceband carriers (R5 5806, R6 5843), persistent in 5/5
    sweeps, both promote to level 2 via the '>=2 co-band carriers' path
    (design doc S4/S9's own decisive multi-carrier case) -- not via grid
    position alone. NOTE: the task packet's own single-carrier acceptance
    line ("R7 5840 -> level 2 in 5 sweeps") conflicts with its own level-2
    gate definition ("on-grid AND shape AND persistence AND (>=2 co-band OR
    dwell-confirmed)") for a *lone* carrier with no dwell call; this test
    exercises the gate as specified using two co-band carriers instead --
    flagged for architect/reviewer attention."""
    rng = np.random.default_rng(3)
    row = _flat_floor(rng)
    row = _embed_carrier(row, 5806.0, delta_db=30.0)
    row = _embed_carrier(row, 5843.0, delta_db=28.0)
    sweeps = _repeat_rows(row, 5)

    # 100%-duty carriers cannot be found by self-baselining (see the
    # _AMBIENT_BASELINE note above) -- pass the explicit ambient floor.
    cands = sweep_candidates(sweeps, baseline_db=_AMBIENT_BASELINE)
    by_centre = sorted(cands, key=lambda c: c["centre_hz"])
    assert len(by_centre) == 2, by_centre

    c5806, c5843 = by_centre
    assert abs(c5806["centre_hz"] - 5806e6) <= 0.25e6
    assert abs(c5843["centre_hz"] - 5843e6) <= 0.25e6
    assert c5806["label"] == "analog_fpv_grid_candidate"
    assert c5843["label"] == "analog_fpv_grid_candidate"
    assert c5806["grid"] == "R" and c5806["grid_channel"] == 5
    assert c5843["grid"] == "R" and c5843["grid_channel"] == 6
    assert "R5 5806" in c5806["consistent_with"]
    assert "R6 5843" in c5843["consistent_with"]
    for c in by_centre:
        assert 0.0 < c["grid_false_match_p"] < 1.0
        assert c["n_sweeps_present"] == 5
    # k=2 co-band tightens the false-match probability vs a lone carrier (k=1)
    assert c5806["grid_false_match_p"] < afpv.grid_false_match_p(k=1)


def test_off_grid_carrier_is_level1_only():
    rng = np.random.default_rng(4)
    row = _flat_floor(rng)
    row = _embed_carrier(row, 5851.3, delta_db=30.0)
    cands = sweep_candidates(_repeat_rows(row, 5), baseline_db=_AMBIENT_BASELINE)
    assert len(cands) == 1
    c = cands[0]
    assert c["label"] == "analog_video_carrier_candidate"
    assert c["grid"] is None
    assert c["consistent_with"] == []
    assert abs(c["centre_hz"] - 5851.3e6) <= 0.25e6
    assert c["grid_false_match_p"] == afpv.grid_false_match_p(k=1)


def test_band_a_carrier_needs_dwell_for_level2():
    """T1 acceptance (design doc S9): a carrier at 5845 MHz (Band A2) is
    emitted only as level 1 without a dwell confirmation, even though it is
    on-grid, morphologically valid and persistent."""
    rng = np.random.default_rng(5)
    row = _flat_floor(rng)
    row = _embed_carrier(row, 5845.0, delta_db=30.0)
    cands = sweep_candidates(_repeat_rows(row, 5), baseline_db=_AMBIENT_BASELINE)
    assert len(cands) == 1
    c = cands[0]
    assert c["label"] == "analog_video_carrier_candidate"
    assert c["grid"] == "A" and c["band_a"] is True
    assert "A2 5845" in c["consistent_with"]

    # With an (externally supplied) dwell confirmation at the same centre,
    # the same scenario promotes to level 2.
    cands2 = sweep_candidates(_repeat_rows(row, 5), baseline_db=_AMBIENT_BASELINE,
                               dwell_confirmed_centres_hz=[5845e6])
    assert cands2[0]["label"] == "analog_fpv_grid_candidate"


def test_wifi_like_wideband_burst_not_level2():
    """A 20 MHz flat-topped, always-on emitter at 5745 MHz (Band A / U-NII-3)
    fails the occupied-bandwidth gate (5-9 MHz at -20 dB) outright -- it is
    not even a level-1 candidate, so it certainly is not level 2."""
    rng = np.random.default_rng(6)
    row = _flat_floor(rng)
    mask = np.abs(FREQS_MHZ - 5745.0) <= 10.0  # 20 MHz flat-topped plateau
    row = row.copy()
    plateau_lin = np.power(10.0, row / 10.0) + np.power(10.0, (FLOOR_DB + 20.0) / 10.0)
    row[mask] = 10.0 * np.log10(plateau_lin[mask])
    cands = sweep_candidates(_repeat_rows(row, 5))
    assert not any(c["label"] == "analog_fpv_grid_candidate" for c in cands)
    assert cands == [], cands


def test_persistence_requires_min_sweeps():
    rng = np.random.default_rng(7)
    floor_row = _flat_floor(rng)
    carrier_row = _embed_carrier(floor_row.copy(), 5806.0, delta_db=30.0)
    sweeps = [(FREQS_MHZ, carrier_row.copy()), (FREQS_MHZ, floor_row.copy()),
              (FREQS_MHZ, carrier_row.copy()), (FREQS_MHZ, floor_row.copy()),
              (FREQS_MHZ, floor_row.copy())]
    cands = sweep_candidates(sweeps)
    assert cands == [], "2-of-5 sweeps must not satisfy persistence (>=3)"


def test_seam_comb_masked_yields_zero_candidates():
    """Deterministic +7 dB, 4-bin (~2 MHz) comb at every 10 MHz step seam
    (design doc S7, measured in base_58.npz) must not produce any candidate
    once the mandatory seam mask is applied."""
    seam_centres = list(np.arange(5735.0, 5946.0, 10.0))
    row = _flat_floor(None)
    for s in seam_centres:
        mask = np.abs(FREQS_MHZ - s) <= 1.0  # ~4 bins wide
        lin = np.power(10.0, row / 10.0)
        lin[mask] = np.power(10.0, (FLOOR_DB + 7.0) / 10.0)
        row = 10.0 * np.log10(lin)
    cands = sweep_candidates(_repeat_rows(row, 5), seam_mhz=seam_centres)
    assert cands == []


def test_noise_only_yields_zero_candidates():
    rng = np.random.default_rng(8)
    sweeps = [(FREQS_MHZ, _flat_floor(rng, noise_std_db=1.5)) for _ in range(5)]
    assert sweep_candidates(sweeps) == []


def test_real_ambient_single_sweep_yields_zero_candidates():
    """base_58.npz has n_sweeps=1: persistence (>=3) cannot be exercised by
    this file at all, so a 0-candidate result here is necessary but weak
    evidence -- it does not by itself validate the false-alarm rate on real
    ambient RF (design doc S8)."""
    data = np.load(BASE58)
    freqs_mhz = data["freqs_mhz"]
    power_db = data["power_db"]
    cands = sweep_candidates([(freqs_mhz, power_db)])
    assert cands == []


def test_carrier_over_real_ambient_baseline_3_of_3():
    """T1 acceptance (design doc S9): a synthetic carrier at 5843 MHz over
    the real base_58.npz ambient (as a Baseline), recovered within
    +-250 kHz in 3/3 rows."""
    data = np.load(BASE58)
    baseline = Baseline(lo_mhz=float(data["freqs_mhz"][0]), hi_mhz=float(data["freqs_mhz"][-1]),
                         bin_hz=500_000.0, freqs_mhz=data["freqs_mhz"], power_db=data["power_db"],
                         n_sweeps=1, dwell_s=0.0)
    freqs_mhz = data["freqs_mhz"]
    floor_row = baseline.interp(freqs_mhz)
    carrier_row = _embed_carrier(floor_row.copy(), 5843.0, delta_db=30.0, freqs_mhz=freqs_mhz)
    sweeps = [(freqs_mhz, carrier_row.copy()) for _ in range(3)]
    cands = sweep_candidates(sweeps, baseline_db=baseline)
    assert len(cands) == 1
    c = cands[0]
    assert c["n_sweeps_present"] == 3
    assert abs(c["centre_hz"] - 5843e6) <= 0.25e6


# --------------------------------------------------------------------------- #
# Stage B: dwell_confirm
# --------------------------------------------------------------------------- #

def test_dwell_confirm_true_on_fmvideo_sim():
    fs = 15.36e6
    lo_offset_hz = 3.0e6
    iq = make_fm_video(fs, 1.0, carrier_offset_hz=-lo_offset_hz, deviation_hz=2.7e6,
                        snr_db=30.0, seed=1)
    res = dwell_confirm(iq, fs, lo_offset_hz=lo_offset_hz)
    assert res["confirmed"] is True
    assert res["continuous"] is True
    assert res["frac_time_occupied"] >= 0.98
    assert res["r_shape"] > 0.0
    assert set(res["audio_subcarriers_detected_hz"]) == {6.0e6, 6.5e6}


def test_dwell_confirm_false_on_bursty_wideband_emitter():
    fs = 15.36e6
    rng = np.random.default_rng(2)
    n = int(fs * 1.0)
    t = np.arange(n) / fs
    noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    freqs = np.fft.fftfreq(n, d=1.0 / fs)
    mask = np.abs(freqs - (-3.0e6)) <= 4.0e6  # ~8 MHz occupied, OFDM-like flat spectrum
    sig = np.fft.ifft(np.fft.fft(noise) * mask)
    sig = sig / np.sqrt(np.mean(np.abs(sig) ** 2))
    on_off = (((t * 5.0).astype(int) % 2) == 0).astype(np.float64)  # 100 ms on/off
    iq = (sig * on_off * 3.0).astype(np.complex64)

    res = dwell_confirm(iq, fs, lo_offset_hz=3.0e6)
    assert res["confirmed"] is False
    assert res["r_shape"] < 0.35 or res["continuous"] is False


def test_dwell_confirm_default_percentile_floor_would_fail():
    """S5.1: the default (5th-percentile-over-time) noise floor is invalid
    for a duty~1.0 emitter. Demonstrate directly against detect_bursts: at
    the residual-carrier bin the per-bin default floor sits close to the
    carrier's OWN power level (duty ~1.0), not the true receiver noise
    floor -- unlike an explicit off-carrier floor, it does not merely miss
    the long event outright here (the residual-carrier bin still has enough
    < 5th-percentile-of-time excursions, e.g. sync tip / field sync, to
    register one), it badly UNDERSTATES its true margin above the real noise
    floor (by >10 dB vs the explicit off-carrier floor) -- the reason
    dwell_confirm never trusts detect_bursts' own per-bin default and always
    computes an explicit off-carrier floor itself."""
    fs = 15.36e6
    lo_offset_hz = 3.0e6
    iq = make_fm_video(fs, 1.0, carrier_offset_hz=-lo_offset_hz, deviation_hz=2.7e6,
                        snr_db=30.0, seed=1)
    from aerix_rf.dsp import spectrogram
    spec = spectrogram.compute(iq, fs, fft_size=1024)
    lin = np.power(10.0, spec.power_db.astype(np.float64) / 10.0)
    freq_rel_carrier = spec.freqs_hz + lo_offset_hz
    frame_dt_s = (spec.hop or 512) / fs

    events_default_floor = detect_bursts(lin, fs=fs, frame_dt_s=frame_dt_s, freqs_hz=freq_rel_carrier)
    long_default = [e for e in events_default_floor if e.duration_s >= 0.5 and abs(e.centre_hz) <= 2.0e6]
    assert len(long_default) == 1
    default_margin_db = long_default[0].peak_db_over_floor

    off_carrier = np.abs(freq_rel_carrier) > 6.0e6
    explicit_floor_db = float(np.median(spec.power_db[:, off_carrier]))
    explicit_floor_lin = float(10.0 ** (explicit_floor_db / 10.0))
    events_explicit_floor = detect_bursts(lin, fs=fs, frame_dt_s=frame_dt_s, freqs_hz=freq_rel_carrier,
                                           noise_floor_lin=explicit_floor_lin)
    long_explicit = [e for e in events_explicit_floor if e.duration_s >= 0.5 and abs(e.centre_hz) <= 2.0e6]
    assert len(long_explicit) == 1
    explicit_margin_db = long_explicit[0].peak_db_over_floor

    assert explicit_margin_db - default_margin_db > 10.0, (
        "the default per-bin percentile floor must understate the true margin "
        "above the real noise floor for a duty~1 emitter")

    res = dwell_confirm(iq, fs, lo_offset_hz=lo_offset_hz)
    assert res["continuous"] is True
