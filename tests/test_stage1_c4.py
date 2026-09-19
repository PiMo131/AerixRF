"""C4 acceptance tests (docs/design/stage1-c4-c5-spec.md): additive ``looks``
argument on ``dsp.spectrogram.compute``, per-bin Q25 noise floor + P_fa-
targeted gate/hold in ``detect.bursts``, and the detector-local multi-look
wiring in ``detect.energy.detect``. C5 (grid-resolution guard) is out of
scope for this module -- see ``tests/test_detect_raster.py`` for that when it
lands.

Minimum test set agreed with the architect (task packet), not the full list
in the design doc's "Tests required" section.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from aerix_rf.detect import bursts as bursts_mod
from aerix_rf.detect import energy
from aerix_rf.dsp import spectrogram

FFT = 1024


def _old_spectrogram_compute():
    """Import the pre-C4 ``compute`` (HEAD, before this change) as a
    standalone function object, so the bit-exact claim is checked against
    the actual prior implementation rather than merely against "looks=1
    equals the default", which would be tautological."""
    src = subprocess.run(
        ["git", "show", "HEAD:aerix_rf/dsp/spectrogram.py"],
        cwd=__file__.rsplit("/tests/", 1)[0], capture_output=True, text=True, check=True,
    ).stdout
    ns: dict = {}
    exec(compile(src, "old_spectrogram.py", "exec"), ns)
    return ns["compute"]


# --------------------------------------------------------------------------
# (a) spectrogram.compute(looks=...)
# --------------------------------------------------------------------------

def test_compute_looks1_bit_exact_vs_head():
    old_compute = _old_spectrogram_compute()
    rng = np.random.default_rng(42)
    n = 200_000
    iq = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)

    old_spec = old_compute(iq, 20e6, FFT)
    new_spec = spectrogram.compute(iq, 20e6, FFT)          # default looks=1
    new_spec_explicit = spectrogram.compute(iq, 20e6, FFT, looks=1)

    np.testing.assert_array_equal(old_spec.power_db, new_spec.power_db)
    np.testing.assert_array_equal(old_spec.power_db, new_spec_explicit.power_db)
    assert old_spec.hop == new_spec.hop == new_spec_explicit.hop
    np.testing.assert_array_equal(old_spec.freqs_hz, new_spec.freqs_hz)


def test_compute_looks4_equals_mean_of_4_contiguous_fft_powers():
    rng = np.random.default_rng(7)
    looks = 4
    n_starts = 6
    hop = looks * FFT
    n = n_starts * hop + FFT  # plenty of trailing samples
    iq = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)

    spec = spectrogram.compute(iq, 20e6, FFT, hop=hop, remove_dc=False, looks=looks)

    # Manually average the power of `looks` contiguous, non-overlapping FFTs
    # per reported frame, replicating the exact analysis window/scale.
    win = np.hanning(FFT).astype(np.float32)
    scale = 1.0 / (FFT * FFT)
    expected = np.empty_like(spec.power_db)
    for i in range(spec.power_db.shape[0]):
        t0 = i * hop
        acc = np.zeros(FFT, dtype=np.float64)
        for k in range(looks):
            seg = iq[t0 + k * FFT: t0 + (k + 1) * FFT] * win
            S = np.fft.fftshift(np.fft.fft(seg))
            acc += (S.real ** 2 + S.imag ** 2) * scale
        acc /= looks
        expected[i] = 10.0 * np.log10(acc + 1e-12)

    np.testing.assert_allclose(spec.power_db, expected, rtol=1e-4, atol=1e-3)


def test_compute_looks_clamped_when_hop_too_small():
    rng = np.random.default_rng(3)
    n = 500_000
    iq = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    hop = int(1.5 * FFT)   # room for only 1 full look

    spec_requested_8 = spectrogram.compute(iq, 20e6, FFT, hop=hop, looks=8)
    spec_looks1 = spectrogram.compute(iq, 20e6, FFT, hop=hop, looks=1)

    assert spec_requested_8.hop == hop == spec_looks1.hop   # hop never grows
    np.testing.assert_array_equal(spec_requested_8.power_db, spec_looks1.power_db)


# --------------------------------------------------------------------------
# (b) perbin_noise_floor_lin
# --------------------------------------------------------------------------

_L_EFF_FRAMES = {1: 40_000, 4: 10_000, 13: 4_000}  # frame counts chosen so the
                                                     # stride-decimated Q25 sampling
                                                     # s.d. (design doc (a): ~0.19 dB
                                                     # at N=2000, undecimated) is well
                                                     # under the 0.5 dB acceptance gate
                                                     # at every l_eff tested.


@pytest.mark.parametrize("l_eff", [1, 4, 13])
def test_perbin_floor_white_noise_within_half_db(l_eff):
    rng = np.random.default_rng(100 + l_eff)
    n_bins = 64
    n_frames = _L_EFF_FRAMES[l_eff]
    true_power = 3.7
    power = rng.gamma(shape=l_eff, scale=true_power / l_eff, size=(n_frames, n_bins))

    floor = bursts_mod.perbin_noise_floor_lin(power, l_eff=float(l_eff))
    err_db = 10.0 * np.log10(floor / true_power)
    assert np.all(np.abs(err_db) <= 0.5), err_db


def test_perbin_floor_tracks_moderately_occupied_bin():
    """At occupancy well under the 75% design boundary the Q25 estimator's
    combined-sample percentile still lands inside the *idle* population and
    stays close to true noise power. NOTE: the estimator is only unbiased in
    the limit of 0% occupancy -- the quantile it actually measures is the
    ``(FLOOR_QUANTILE / idle_fraction)``-th percentile of the idle
    distribution (order-statistic argument), which is a growing, DETERMINISTIC
    bias as occupancy approaches 75%, not a small perturbation. At exactly the
    70% occupancy figure this task's packet named, that bias is ~7.9 dB for
    L=1 (computed analytically: Gamma.ppf(0.25/0.30,1)/Gamma.ppf(0.25,1)),
    not the ~1 dB the packet described -- see
    ``test_perbin_floor_bounded_but_biased_near_75pct_occupancy`` below for
    that regime. 15% occupancy is used here instead to actually exercise the
    "stays within ~1 dB" claim."""
    rng = np.random.default_rng(11)
    n_bins = 8
    n_frames = 8000
    true_power = 2.0
    l_eff = 1.0
    power = rng.gamma(shape=l_eff, scale=true_power / l_eff, size=(n_frames, n_bins))

    occ_frac = 0.15
    n_occ = int(n_frames * occ_frac)
    idx = rng.choice(n_frames, size=n_occ, replace=False)
    power[idx, 3] = rng.gamma(shape=l_eff, scale=(true_power * 200.0) / l_eff, size=n_occ)

    floor = bursts_mod.perbin_noise_floor_lin(power, l_eff=l_eff)
    err_db = 10.0 * np.log10(floor[3] / true_power)
    assert abs(err_db) <= 1.0, err_db


def test_perbin_floor_bounded_but_biased_near_75pct_occupancy():
    """Regression/documentation test for a finding from this task: at 70%
    occupancy (near the design doc's stated 75% tolerance boundary) the Q25
    estimator is NOT within 1 dB of true noise power -- it is biased high by
    several dB (a deterministic order-statistic effect, see the docstring
    above), though it stays well short of the +-CLAMP_DB (10 dB) ceiling and
    remains finite/positive (i.e. it degrades gracefully rather than
    catastrophically). This is flagged for the architect: the task packet's
    "within +-1 dB ... at 70% occupied" acceptance description does not match
    the estimator's actual math."""
    rng = np.random.default_rng(11)
    n_bins = 8
    n_frames = 4000
    true_power = 2.0
    l_eff = 1.0
    power = rng.gamma(shape=l_eff, scale=true_power / l_eff, size=(n_frames, n_bins))

    occ_frac = 0.70
    n_occ = int(n_frames * occ_frac)
    idx = rng.choice(n_frames, size=n_occ, replace=False)
    power[idx, 3] = rng.gamma(shape=l_eff, scale=(true_power * 200.0) / l_eff, size=n_occ)

    floor = bursts_mod.perbin_noise_floor_lin(power, l_eff=l_eff)
    err_db = 10.0 * np.log10(floor[3] / true_power)
    assert 1.0 < abs(err_db) <= bursts_mod.FLOOR_CLAMP_DB, err_db
    assert np.isfinite(floor[3]) and floor[3] > 0.0


def test_perbin_floor_clamped_at_full_occupancy():
    rng = np.random.default_rng(12)
    n_bins = 16
    n_frames = 4000
    true_power = 1.5
    l_eff = 1.0
    power = rng.gamma(shape=l_eff, scale=true_power / l_eff, size=(n_frames, n_bins))

    # bin 0 occupied 100% of the time at +25 dB -> Q25 sits entirely on-signal
    power[:, 0] = rng.gamma(shape=l_eff, scale=(true_power * 10 ** 2.5) / l_eff, size=n_frames)

    floor = bursts_mod.perbin_noise_floor_lin(power, l_eff=l_eff)
    f_ref = float(np.median(floor))
    # Changed 2026-09-19 (see docs/design/stage1-c4-c5-spec.md
    # "S Implementation reconciliation"): a bin whose own Q25 is rejected by
    # the clamp falls back to the band-wide reference F_ref, NOT to the
    # rejection boundary F_ref + CLAMP_DB. Clipping to the boundary left a
    # continuously occupied bin with a floor 10 dB above true noise, so a
    # 12-15 dB continuous wideband emitter sat only ~5 dB over its own floor
    # and fragmented into 1-frame speckle (it produced a spurious
    # window-level cadence in tests/test_detect.py). The bin must still not
    # be self-blinded, which is what this asserts: its floor is the noise
    # reference, ~25 dB below the occupant.
    assert floor[0] == pytest.approx(f_ref, rel=0.02)
    assert abs(10.0 * np.log10(floor[0] / true_power)) < 0.5
    assert floor[0] < 0.1 * float(np.quantile(power[:, 0], 0.25))


# --------------------------------------------------------------------------
# (c) P_fa on pure noise
# --------------------------------------------------------------------------

def test_arm_pixel_rate_matches_arm_pfa_on_pure_noise():
    rng = np.random.default_rng(21)
    n_frames, n_bins = 2000, 1024
    true_power = 1.0
    power = rng.gamma(shape=1.0, scale=true_power, size=(n_frames, n_bins))

    gate_db = bursts_mod.threshold_db_for_pfa(bursts_mod.ARM_PFA, 1.0)
    gate_ratio = 10.0 ** (gate_db / 10.0)
    n_arm = int(np.count_nonzero(power >= true_power * gate_ratio))

    expected = n_frames * n_bins * bursts_mod.ARM_PFA
    assert n_arm <= 5, f"n_arm={n_arm}, expected~{expected:.2f}"


def test_detect_bursts_pure_noise_multi_seed_stays_near_arm_pfa_budget():
    """NOTE on the task packet's "0 events across 3 seeds" wording: with
    truly i.i.d. l_eff=1 Gamma(1) noise (no bin-to-bin/frame-to-frame
    correlation) an isolated arm pixel is, by ``_channelise``'s own logic,
    ALWAYS promoted to its own (n_frames=1, single-bin) event -- there is no
    minimum-size gate below the arm/hold hysteresis test. So the expected
    NUMBER OF SPURIOUS EVENTS on this synthetic i.i.d. input is the expected
    NUMBER OF ARM PIXELS itself, ``ARM_PFA * n_frames * n_bins`` ~= 2.05 per
    window (2000x1024), not << 1 -- "0 events in every one of 3 seeds" is a
    ~13% per-seed / <1% all-3 event, not a guarantee. (In the live detector
    this synthetic worst case does not arise: the 300 kHz frequency-smoothing
    boxcar correlates adjacent bins, reducing the number of independent
    frequency trials well below 1024 -- see ``bench/stage1_fa_budget.py`` for
    the real-corpus measurement, which is the authoritative acceptance test
    for false-alarm rate.) This test instead checks the total spurious event
    count over 3 seeds stays within a generous Poisson bound of the ARM_PFA
    budget, and that no spurious event is ever more than 1 frame / a few bins
    wide (i.e. it never becomes a wide, "real-looking" false burst)."""
    n_frames, n_bins = 2000, 1024
    fs = 12.288e6
    freqs = np.fft.fftshift(np.fft.fftfreq(n_bins, d=1.0 / fs))
    total_events = 0
    for seed in (1, 2, 3):
        rng = np.random.default_rng(seed)
        power = rng.gamma(shape=1.0, scale=1.0, size=(n_frames, n_bins))
        events = bursts_mod.detect_bursts(
            power, fs=fs, frame_dt_s=200e-6, freqs_hz=freqs, noise_floor_lin=1.0,
        )
        total_events += len(events)
        for ev in events:
            assert ev.n_frames <= 2
            assert ev.bw_6db_hz <= 4 * (fs / n_bins)

    expected = 3 * n_frames * n_bins * bursts_mod.ARM_PFA  # ~6.1
    assert total_events <= expected + 6.0 * np.sqrt(max(expected, 1.0)), total_events


# --------------------------------------------------------------------------
# (d) bandwidth truth on a narrow synthetic burst
# --------------------------------------------------------------------------

def test_narrowband_bw_perbin_floor_within_2x_of_truth():
    sample_rate = 12.288e6
    true_bw_hz = 300e3
    from aerix_rf.sdr.sim import synth_iq

    iq = synth_iq(sample_rate, 0.5, drone=True, snr_db=20.0, burst_bw_hz=true_bw_hz,
                  burst_ms=5.0, cadence_s=0.05, seed=9)
    spec = spectrogram.compute(iq, sample_rate, fft_size=FFT)
    det = energy.detect(spec, center_freq_mhz=2440.0, iq=iq)

    assert det.events, "no burst events extracted"
    bws = np.array([ev.bw_6db_hz for ev in det.events])
    median_bw = float(np.median(bws))
    assert median_bw <= 2.0 * true_bw_hz, f"median bw {median_bw} Hz, truth {true_bw_hz} Hz"


# --------------------------------------------------------------------------
# (e) energy.detect with iq= vs without
# --------------------------------------------------------------------------

def test_energy_detect_iq_matches_canonical_fields():
    sample_rate = 20e6
    from aerix_rf.sdr.sim import synth_iq

    iq = synth_iq(sample_rate, 0.3, drone=True, snr_db=15.0, burst_bw_hz=8e6,
                  cadence_s=0.06, seed=1)
    spec = spectrogram.compute(iq, sample_rate, fft_size=FFT)

    det_no_iq = energy.detect(spec, center_freq_mhz=2431.5)
    det_with_iq = energy.detect(spec, center_freq_mhz=2431.5, iq=iq)

    # Fields derived from `spec` (unaffected by the detector-local looks path).
    assert det_no_iq.snr_db == pytest.approx(det_with_iq.snr_db)
    assert det_no_iq.occupied_bw_mhz == pytest.approx(det_with_iq.occupied_bw_mhz)
    assert det_no_iq.duty_cycle == pytest.approx(det_with_iq.duty_cycle)
    assert det_no_iq.peak_freq_mhz == pytest.approx(det_with_iq.peak_freq_mhz)
    assert det_no_iq.burst_count == det_with_iq.burst_count
    assert det_no_iq.score == pytest.approx(det_with_iq.score)

    # The burst list itself is allowed (expected) to differ: the `iq=` path
    # runs a higher-look-count, per-bin-floor T1 pipeline on a finer-grained
    # local spectrogram.


# --------------------------------------------------------------------------
# (f) FA fix 2 (2026-09-19): sensitivity of the hop-set membership gate, the
#     fail-open behaviour of the fragment rule, and a strong-signal
#     regression against ``main``.
#
#     Context: the first form of ``raster.is_unresolved_fragment`` (bw_noise_
#     limited AND bw < 300 kHz) was a pure SNR test -- an independent
#     reviewer measured that it discarded ~100 % of genuine 300 kHz bursts
#     below ~10.5 dB SNR.  The third conjunct (the event's peak bin must sit
#     inside a >= 1 MHz CONTINUOUSLY OCCUPIED run) is what turns it back into
#     a fragment test.  These tests pin that down.
# --------------------------------------------------------------------------

_SENS_FS = 12.288e6
_SENS_BINS = 1024
_SENS_FRAMES = 200
_SENS_BW_HZ = 300e3           # one T1 frequency-smoothing kernel wide
_SENS_CENTRE_BIN = _SENS_BINS // 2 + 3   # off-centre: avoid the DC bin


def _sens_freqs() -> np.ndarray:
    return np.fft.fftshift(np.fft.fftfreq(_SENS_BINS, d=1.0 / _SENS_FS))


def _gauss_shape(bw_hz: float, centre_bin: int) -> np.ndarray:
    bin_hz = _SENS_FS / _SENS_BINS
    sigma_bins = max((bw_hz / 2.3548) / bin_hz, 0.5)   # FWHM -> sigma
    x = np.arange(_SENS_BINS) - centre_bin
    return np.exp(-0.5 * (x / sigma_bins) ** 2)


_SENS_LOOKS = 8.0             # the T1 path's effective look count: the 300 kHz
                              # frequency smoothing over ~25 bins gives
                              # L_eff ~ 8-12 after the Hann correlation
                              # correction.  Testing at L_eff = 1 would make
                              # the ARM threshold (~ -ln(P_fa) = 16 dB over the
                              # mean for a single look) the binding constraint
                              # instead of the fragment rule, which is not what
                              # this test is about.


def _hop_train_power(snr_db: float, seed: int, looks: float = _SENS_LOOKS) -> np.ndarray:
    """``looks``-averaged noise plus a 300 kHz component present on ~10 % of
    frames in short bursts -- the physical case the acceptance criterion is
    about (a hop dwell, not a continuously-on carrier).  Bursts never touch a
    time edge, so ``edge_clipped`` does not confound the count; a duty-1.0
    fixture would, because a component present in every frame IS time-edge
    clipped and is excluded by ``cluster_centres`` for that reason alone.
    """
    rng = np.random.default_rng(seed)
    power = rng.gamma(shape=looks, scale=1.0 / looks,
                      size=(_SENS_FRAMES, _SENS_BINS))
    sig = _gauss_shape(_SENS_BW_HZ, _SENS_CENTRE_BIN) * (10 ** (snr_db / 10.0) - 1.0)
    on = np.zeros(_SENS_FRAMES, dtype=bool)
    for k in range(5, _SENS_FRAMES - 5, 40):
        on[k:k + 4] = True
    return power + on[:, None] * sig[None, :]


def _fraction_counted(snr_db: float, n_trials: int, seed0: int) -> tuple[float, float]:
    """``(fraction detected, fraction of detected that are counted)``.

    "Counted" = survives the same filter ``raster.cluster_centres`` applies
    (not edge-clipped, not an unresolved fragment, not occupancy-masked) AND
    actually lands in a cluster at the true centre.
    """
    from aerix_rf.detect import raster as raster_mod

    freqs = _sens_freqs()
    centre_true = float(freqs[_SENS_CENTRE_BIN])
    detected = 0
    counted = 0
    for trial in range(n_trials):
        power = _hop_train_power(snr_db, seed0 + trial)
        floor, excess = bursts_mod.perbin_noise_floor_lin(
            power, l_eff=_SENS_LOOKS, ref_lin=1.0, return_excess=True)
        events = bursts_mod.detect_bursts(
            power, fs=_SENS_FS, frame_dt_s=200e-6, freqs_hz=freqs,
            noise_floor_lin=floor, floor_excess_db=excess, l_eff=_SENS_LOOKS)
        cand = [e for e in events if abs(e.centre_hz - centre_true) < 1e6]
        if not cand:
            continue
        detected += 1
        best = max(cand, key=lambda e: e.peak_db_over_floor)
        spans = raster_mod.wideband_occupancy_spans(events)
        if (best.edge_clipped or raster_mod.is_unresolved_fragment(best)
                or raster_mod.is_occupancy_masked(best, spans)):
            continue
        clusters = raster_mod.cluster_centres(events)
        if any(best in c.events for c in clusters):
            counted += 1
    return detected / n_trials, (counted / detected if detected else 0.0)


def test_hop_member_sensitivity_9db():
    """A genuine 300 kHz hop burst must survive the fragment gate at modest
    SNR.  Acceptance (architect): >= 90 % counted at 9 dB, >= 50 % at 7 dB.

    This is the regression that the FIRST form of the FA fix failed.  With
    the two-term rule (``bw_noise_limited and bw < 300 kHz``) the measured
    numbers on this fixture were 0 % counted at 5 dB and 68 % at 6 dB, and on
    the single-look reviewer fixture 0 % counted everywhere below ~10.5 dB:
    every burst whose peak sits under ~10 dB over its floor is
    ``bw_noise_limited`` by construction, and the smoothed width of a 300 kHz
    component sits right at the 300 kHz threshold.  The third conjunct (peak
    must sit inside a >= 1 MHz continuously-occupied run) is what makes the
    rule a fragment test rather than an SNR test.
    """
    det_9, frac_9 = _fraction_counted(9.0, n_trials=24, seed0=5000)
    det_7, frac_7 = _fraction_counted(7.0, n_trials=24, seed0=6000)
    assert det_9 >= 0.90, f"fixture problem: only {det_9:.2f} detected at 9 dB"
    assert det_7 >= 0.50, f"fixture problem: only {det_7:.2f} detected at 7 dB"
    assert frac_9 >= 0.90, f"9 dB: only {frac_9:.2f} of true bursts counted"
    assert frac_7 >= 0.50, f"7 dB: only {frac_7:.2f} of true bursts counted"


def test_fragment_rule_fails_open():
    """No occupancy information => never a fragment.

    ``floor_occupied_span_hz`` defaults to 0.0, which is what every caller
    that does not pass ``floor_excess_db`` to ``detect_bursts`` produces
    (offline replay of older stores, unit fixtures, third-party callers).
    Unknown must fail OPEN -- towards sensitivity -- because the rule DELETES
    events, so treating "unmeasured" as "inside a wideband occupant" would
    silently blind those paths.
    """
    from aerix_rf.detect import raster as raster_mod

    common = dict(t_start=0.0, t_end=1e-3, duration_s=1e-3, centre_hz=2.44e9,
                  bw_6db_hz=120e3, peak_db_over_floor=6.0,
                  mean_db_over_floor=4.0, n_frames=5, edge_clipped=False,
                  bw_noise_limited=True)

    unknown = bursts_mod.BurstEvent(**common)
    assert unknown.floor_occupied_span_hz == 0.0
    assert not raster_mod.is_unresolved_fragment(unknown)

    # Same event, but measured to sit on bins that are idle most of the
    # window (a real intermittent burst): still not a fragment.
    idle = bursts_mod.BurstEvent(**common, floor_occupied_span_hz=0.0,
                                 floor_excess_db=0.2)
    assert not raster_mod.is_unresolved_fragment(idle)

    # Only when the peak is measured INSIDE a wide, continuously occupied
    # run does the rule fire.
    inside = bursts_mod.BurstEvent(**common, floor_occupied_span_hz=4.0e6,
                                   floor_excess_db=9.0)
    assert raster_mod.is_unresolved_fragment(inside)


# Median ``bw_6db_hz`` of a 20 dB, 300 kHz component (seeds 4000..4007,
# scalar floor 1.0) measured with ``git show main:aerix_rf/detect/bursts.py``
# on 2026-09-19.  Hard-coded rather than recomputed so that this stays a
# regression against the RELEASED behaviour even after main moves.
_MAIN_STRONG_BW_HZ = 428315.3


def test_strong_component_bw_matches_main_within_5pct():
    """>= 20 dB regression: the FA-fix-2 changes (per-bin floor excess, the
    above-hold centroid centre) must not move the measured bandwidth of a
    strong, well-resolved component.

    The centroid fallback only fires when ``bw_noise_limited`` is set and it
    only repairs the CENTRE; ``bw_6db_hz`` must be untouched.  A drift here
    would mean the -6 dB edge walk itself changed, which would invalidate
    every stored bandwidth in the corpus.
    """
    freqs = _sens_freqs()
    centre_true = float(freqs[_SENS_CENTRE_BIN])
    bws = []
    for seed in range(4000, 4008):
        rng = np.random.default_rng(seed)
        power = rng.gamma(shape=1.0, scale=1.0, size=(_SENS_FRAMES, _SENS_BINS))
        power += _gauss_shape(_SENS_BW_HZ, _SENS_CENTRE_BIN)[None, :] * (
            10 ** (20.0 / 10.0) - 1.0)
        events = bursts_mod.detect_bursts(
            power, fs=_SENS_FS, frame_dt_s=200e-6, freqs_hz=freqs,
            noise_floor_lin=1.0)
        cand = [e for e in events if abs(e.centre_hz - centre_true) < 1e6]
        assert cand, f"seed {seed}: strong component not detected"
        best = max(cand, key=lambda e: e.peak_db_over_floor)
        bws.append(best.bw_6db_hz)

    median_bw = float(np.median(bws))
    rel = abs(median_bw - _MAIN_STRONG_BW_HZ) / _MAIN_STRONG_BW_HZ
    assert rel <= 0.05, (
        f"strong-component bw drifted {rel * 100:.1f} % from main "
        f"({median_bw:.0f} Hz vs {_MAIN_STRONG_BW_HZ:.0f} Hz)")
