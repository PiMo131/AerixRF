# Stage-1 C4/C5 builder spec — per-bin noise floor and grid-resolution guard

Source diagnosis: `docs/design/stage1-rc-positives-2026-09-19.md` §3 (C4, C5), §4 (items 4, 5).
C1–C3 landed in 41a1787. **Design only — no `aerix_rf/` code changed by this note.**
Evidence level unchanged: everything below is level-1 morphology quality, never identity.

## C4 — per-bin noise floor + threshold re-derivation

### (a) Where the floor enters, and the estimator

`aerix_rf/detect/energy.py:230-236` computes a **scalar** `noise_lin` (mean linear power over
non-burst STFT slices, spread uniformly over all bins) and passes it at line ~279 as
`bursts_mod.detect_bursts(..., noise_floor_lin=noise_lin, ...)`. `detect_bursts` already accepts an
array: `aerix_rf/detect/bursts.py:114 _floor_lin()` broadcasts whatever it is to `[n_bins]`. So the
change is confined to what `energy.detect` computes; no signature change is required.

Proposed estimator, per bin `b` over the window's frames:

```
q25[b]   = np.quantile(P[::stride, b], 0.25)        # linear power, frames x bins
floor[b] = q25[b] / Q25(L_eff)                      # -> MEAN noise power per bin
floor[b] = clip(floor[b], F_ref / 10**(CLAMP_DB/10), F_ref * 10**(CLAMP_DB/10))
F_ref    = median over bins of floor[]              # band-wide robust reference
```

**Why the 25th percentile, not the median.** A quantile of a Gamma(L_eff) variate is an unbiased
noise estimator as long as the bin is *idle* for more than (1 − p) of the window. p = 0.25 tolerates
75 % occupancy; the median tolerates only 50 % — and a busy Wi-Fi channel or a continuous video
downlink sits above 50 % routinely. The price is negligible: the asymptotic s.d. of the sample
quantile for exponential noise is `sqrt(p/((1−p)N))` relative to the mean, i.e. 0.19 dB at p = 0.25,
N = 2000 vs 0.14 dB at p = 0.50 (inflate ~1.4× for STFT frame overlap; still < 0.3 dB).
Bias constants (pin these in a test, derive with `scipy.stats.gamma.ppf(0.25, L)/L`):
`Q25(1) = −ln(0.75) = 0.2877` (−5.41 dB), `Q25(4) = 0.6339` (−1.98 dB).

**Behaviour when a bin is occupied > 75 % of the time (Wi-Fi, continuous downlink).** The per-bin
estimate rises onto the signal and that bin self-blinds. This is why the ±`CLAMP_DB` clamp against
the band-wide reference is mandatory, not optional: `CLAMP_DB = 10 dB` (measured per-bin p10→p90
floor spread over a 100 MHz span is 6–7 dB, so 10 dB covers real analog tilt/roll-off but not a
20–30 dB occupied channel). Clamped bins stay armed for the whole window, so the occupant surfaces
as a wide, time-edge-clipped event → `wifi_like_wideband`, excluded from the hop-set count. That is
the wanted outcome: report the blocker, do not absorb it into the floor. The lower clamp protects
against filter notches and the DC-blank region (`spectrogram.compute` overwrites DC bins with a
neighbour mean, so they do not bias `F_ref`, but they must not produce a tiny floor either).

**Cost** at 12.288 MS/s, 1024 bins, ~2000 frames (8.2 M float32): `np.quantile` on the full array is
a full sort; use `np.partition(P[::stride], k, axis=0)` (introselect, O(N·B)) on a stride-decimated
frame set with `n_floor_frames >= 256`. At stride 4 (500 frames × 1024) that is ~0.5 M elements,
~4–8 ms, inside the 50 ms `detect_bursts` budget. Full-rate partition (~2 M elements) is ~15–25 ms
and would leave too little headroom — decimate.

### (b) Gate/hold thresholds, and the arithmetic

Today: `bursts.py:52-53` `GATE_DB = 6.0` (arm), `HYST_DB = 3.0` (hold), both **relative to whatever
floor is passed**. For a single-look periodogram the per-bin noise power is exponential
(χ²₂), so with the floor expressed as the **mean**, `P(pixel ≥ floor·10^(T/10)) = exp(−10^(T/10))`:

| T (dB over mean floor) | P_fa, L_eff = 1 | P_fa, L_eff = 4 |
|---|---|---|
| 3 | 1.4e-1 | 1.4e-1 |
| 5 | 4.2e-2 | 1.4e-3 |
| 6 | 1.9e-2 | 9.9e-5 |
| 7 | 6.4e-3 | 3.1e-6 |
| 8 | 1.8e-3 | 8.5e-8 |
| 12 | 1.3e-7 | — |

(L_eff = 4 column: `P_fa = exp(−Lx)·Σ_{k<L}(Lx)^k/k!`, x = 10^(T/10).) The old +3 dB hold against a
*median* floor is `exp(−ln2·2) = 0.25` — the 25 % quoted in the diagnosis; 4-connected labelling of a
25 %-dense mask percolates (site p_c = 0.593 is far away, but with 1-frame gap bridging plus the
bounding-box BW measurement it is enough to inflate BW 15–50×, exactly as observed).

**Do not hard-code dB.** `energy.detect` already frequency-smooths with
`uniform_filter1d(size = 300 kHz / bin_hz)` (`_T1_FREQ_SMOOTH_HZ = 300e3`), so the looks entering
`detect_bursts` are mode-dependent: 20 bins at 15.36 MS/s/1024 (L_freq ≈ 20/1.5 ≈ 13 independent
under Hann) but only 3 bins (L_freq ≈ 2) at the bench's 100 MS/s full_band. A fixed dB gate is
therefore 6+ dB wrong between modes — this is a second, previously unrecorded contributor to C4.
Specify the operating point as **P_fa targets** and solve for dB at runtime from
`L_eff = L_time × L_freq_eff`:

* arm `ARM_PFA = 1e-6` (≈ 0.3 false arm pixels per 2000×1024 window, so ≈ 0 spurious clusters);
* hold `HOLD_PFA = 2e-3` (≈ 4 000 hold pixels, but only those 4-connected to an arm pixel survive);
* implement `threshold_db_for_pfa(pfa, l_eff)` in `bursts.py`, keep `GATE_DB`/`HYST_DB` as the
  explicit-override path so existing callers and tests keep working.

Reference values: L_eff = 1 → arm +11.4 dB, hold +8.0 dB; L_eff = 4 → arm +7.2 dB, hold +5.1 dB;
L_eff = 13 → arm +4.3 dB, hold +2.9 dB. Sensitivity is not lost: a 350 kHz burst in 15 kHz bins
concentrates into ~23 bins, so per-bin SNR ≈ wideband SNR + 10·log10(1024/23) = +16.5 dB — a burst at
−5 dB dwell SNR still clears an +11 dB arm.

### (c) Also average L ≥ 4 FFTs per detector frame? — **Yes, detector-local, and it is free**

At the canonical rate `spectrogram.compute` picks `hop = max(fft/2, ceil(n/_TARGET_FRAMES))`
(`_TARGET_FRAMES = 4000`): for a 1 s / 15.36 MS/s dwell, hop = 3840 = 3.75 × fft_size. **Only 27 % of
the samples are ever looked at.** So set `L = min(L_max, floor(hop / fft_size))` contiguous,
non-overlapping 1024-pt FFTs averaged per detector frame: at canonical rate L = 3 costs **zero**
time resolution (`frame_dt_s` unchanged at 250 µs) and raises time coverage 27 % → 80 %, on top of
the χ²-tightening. `frame_dt_s` is multiplied by L **only** if `hop < L·fft_size`; forbid that case
(clamp L instead) so `frame_dt_s` never grows.

Implementation constraint: this is a **detector-local** product. Add an optional `looks: int = 1`
argument to `dsp/spectrogram.compute` (default preserves today's output bit-for-bit) and use it only
from `energy.detect`. **The canonical 1024 / Hann / hop-512 representation and the
`datasets/tensor.py` ML tensor MUST NOT change** — no retraining, no dataset regeneration.

Time-resolution consequences to respect:
* ELRS 1–4 ms periods: R2 needs ≥ 4 samples per period, so the detector frame pitch must satisfy
  `frame_dt_s ≤ T_min/4 = 250 µs`. Canonical dwell already meets this; make the pitch an explicit
  configurable (`detector_frame_dt_s`) rather than a by-product of `_TARGET_FRAMES`.
* 100 µs-class hops: with L = 3 the integration span is 200 µs, so a 100 µs hop is diluted by up to
  10·log10(200/100) = 3 dB and its `duration_s` is reported as one frame — a **lower bound** only.
  No duty-cycle or duration claim below `frame_dt_s` is admissible; keep the existing
  `_refine_duration` IQ path as the only source of sub-frame duration.

### (d) Knock-on effects

* **C3 merge threshold — a new defect this exposes.** `raster.py:362` uses
  `max_merge_hz = max(CLUSTER_MAX_MERGE_HZ=1 MHz, 0.75·HOP_MAX_CLUSTER_BW_HZ)`, i.e. the floor is
  1 MHz. That was harmless while BWs were inflated to 5 MHz, but with true 300–400 kHz bursts a
  1 MHz merge radius **merges adjacent channels of the 1 MHz grid we are testing for**. Require
  `merge_hz = min(CLUSTER_MAX_MERGE_HZ, max(tol_hz, 0.75·BW))` and additionally
  `merge_hz ≤ min(Δ_tested)/3 = 333 kHz` whenever a grid test will be run. Call this C3b; it must
  land with C4, not after.
* **`wifi_like_wideband`** (`WIFI_WIDEBAND_MIN_BW_HZ = 8 MHz`, plus `edge_clipped`) currently fires in
  409/428 RFUAV windows and 36/100 ambient — mostly an artefact of the inflated BWs. Expect a large
  drop. Record the new rate; a fall to **zero** on slices with visible Wi-Fi occupancy means the
  clamp is over-suppressing and is a failure, not a win.
* The `occupied_bw_mhz` / `duty_cycle` / `flat_top` fields in `energy.detect` still use the scalar
  `noise_floor`; leave them alone in this change (they feed classifier features) and record that
  divergence explicitly in the docstring.

### (e) Acceptance

1. **Bandwidth truth.** On the three RFUAV 1 s slices already measured (variant A full-coverage
   ground truth: FLYSKY_FS_I6X **308 kHz**, FRSKY_X9DP2019 **412 kHz**, FUTABA_T14SG **362 kHz**
   median `bw_6db_hz`; live scalar-floor path today: 5.7 / 4.9 / 18.8 MHz), the new live path must
   give a median within ×2 of truth: **154–616 / 206–824 / 181–724 kHz**. Note the 300 kHz frequency
   smoothing biases measured BW upward by up to ~300 kHz (variant B read 591 kHz for FLYSKY); if the
   median lands high, gate on the smoothed array but measure the −6 dB edges on the **unsmoothed**
   profile (optional `measure_lin` argument) rather than widening the tolerance.
2. **Cluster counts** in the variant-B range (19–75 per slice), never 1, never > 200.
3. **Ambient FA unchanged** (`bench/stage1_fa_budget.py`, ANTSDR ambient corpus): hopping ≤ ~1 %
   (currently 11/1160 = 0.95 %), level-2 labels = 0/1160.
4. **Timing**: `detect_bursts` ≤ 50 ms per 1 s / 12.288 MS/s window including the floor estimate;
   `spectrogram.compute(looks=L)` must not exceed L× the single-look FFT cost.

## C5 — grid-resolution guard

Rayleigh lattice concentration for centre-error σ_f is `R ≈ exp(−2π²σ_f²/Δ²)`; `R_MIN_RASTER = 0.93`
(`raster.py:83`) gives a **total** budget `σ_f ≤ Δ·sqrt(−ln 0.93 / 2π²) = 0.0606·Δ` (59 kHz at
Δ = 1 MHz). Two necessary conditions, both checked before any level-2 grid label:

* **G1**: `bin_hz ≤ Δ/20` — leaves the quantisation term `σ_q = bin_hz/√12 = Δ/69` at ~12 % of the
  budget, so the estimator gets the rest.
* **G2**: median `bw_6db_hz` of the contributing clusters `≥ 8·bin_hz` — the −6 dB edge-midpoint walk
  needs ≥ 8 bins across the burst to be sub-bin accurate. At 97.7 kHz bins a 300 kHz burst spans
  3 bins; this is the term that actually produced the observed R = 0.27–0.61 (σ_f ≈ 150–250 kHz).

If either fails for the Δ under test, emit tag **`GRID_RESOLUTION_LIMITED`** and do **not** emit
`fhss_1mhz_grid_candidate` / `fhss_2mhz_grid_candidate` (nor the `expresslrs_2g4`
`consistent_with` token). Keep the numeric `RasterEvidence` for diagnostics and add a note saying
this is "insufficient resolution", not a negative result. `analyze_raster` gains
`bin_hz: float | None = None` (forwarded from `energy.detect`, which already computes
`bin_hz = spec.sample_rate / n_freq` at line ~208); `None` = guard not evaluated + a note.

Registry combos at `fft_size = 1024` (G1 only; G2 is data-dependent):

| Mode | rate | bin_hz | Δ = 1 MHz (≤ 50 kHz) | Δ = 2 MHz (≤ 100 kHz) |
|---|---|---|---|---|
| ANTSDR iio default | 12.288 MS/s | 12.0 kHz | pass | pass |
| ANTSDR iio `antsdr_13p44` | 13.44 MS/s | 13.1 kHz | pass | pass |
| UHD/ANTSDR canonical | 15.36 MS/s | 15.0 kHz | pass | pass |
| HackRF legacy / `Config.sample_rate` | 20 MS/s | 19.5 kHz | pass | pass |
| Bench `full_band` (RFUAV native) | 100 MS/s | 97.7 kHz | **FAIL** | marginal pass (G1), **fails G2** |

So no shipping receiver configuration trips G1; only the wideband bench column does, which is the
honest reading of the 0/428 level-2 result.

**Bench `full_band`: keep, as a documented resolution-limited column.** It is the only mode that sees
a hop span wider than the canonical 12 MHz dwell, so dropping it loses the hop-set-coverage argument
entirely. It will now carry `GRID_RESOLUTION_LIMITED` in every window. Add a third bench column
`full_band_4096` (`fft_size = 4096` → 24.4 kHz at 100 MS/s, G1 pass at both Δ, G2 = 12 bins on a
300 kHz burst) — that is the column that actually answers "is there a 1 MHz grid in these captures".
Bench-only; the canonical representation is untouched.

## Tests required

`tests/test_detect_bursts.py`
* `test_perbin_floor_quantile_bias_constants` — `Q25(1)=0.2877`, `Q25(4)=0.6339` to 1e-4.
* `test_perbin_floor_tracks_tilted_noise` — synthetic AWGN with a 10 dB tilt across bins: per-bin
  floor within 1 dB of truth in every bin; the scalar estimator is > 4 dB off at the edges.
* `test_perbin_floor_clamped_under_continuous_occupancy` — one bin group occupied 100 % at +25 dB:
  its floor is clamped to `F_ref + 10 dB`, and the occupant is still emitted as an `edge_clipped`
  event (i.e. not self-blinded).
* `test_threshold_db_for_pfa_matches_gamma_tail` — `threshold_db_for_pfa` inverts the Gamma tail for
  L ∈ {1, 3, 4, 13} to 0.05 dB.
* `test_noise_only_window_false_pixel_rate` — pure AWGN, 2000×1024: armed-pixel count consistent with
  `ARM_PFA` within Poisson 3σ; **zero** promoted events with `bw_6db_hz > 4·bin_hz`.
* `test_narrowband_bw_not_inflated_by_single_look_floor` — synthetic 300 kHz burst at 10 dB dwell
  SNR: `bw_6db_hz` within ×1.5 of 300 kHz with the per-bin floor; the scalar floor overestimates
  by ≥ 5× (regression guard for C4 itself).
* `test_detect_bursts_timing_budget` — ≤ 50 ms for 1 s / 12.288 MS/s including the floor estimate.

`tests/test_dsp_spectrogram.py`
* `test_compute_looks_default_is_bit_identical` — `looks=1` output identical to today's.
* `test_compute_looks_preserves_frame_dt` — with `hop ≥ L·fft_size`, `hop`/frame count unchanged and
  the noise variance falls by ≈ 1/L.
* `test_compute_looks_clamped_when_hop_too_small` — `hop < L·fft_size` clamps L, never grows `hop`.

`tests/test_detect_raster.py`
* `test_grid_resolution_limited_tag_blocks_level2` — clusters on an exact 1 MHz lattice with
  `bin_hz = 97.7 kHz`: tag present, `fhss_1mhz_grid_candidate` absent, `consistent_with` empty.
* `test_grid_guard_passes_at_canonical_bin_width` — same clusters at `bin_hz = 15 kHz`: label emitted.
* `test_grid_guard_g2_burst_too_narrow_in_bins` — G1 passes, median BW = 3 bins: tag present.
* `test_bin_hz_none_evaluates_as_before` — backwards compatibility + note emitted.
* `test_merge_radius_does_not_span_one_grid_step` (C3b) — events on a 1 MHz raster with 350 kHz BW
  resolve to distinct clusters, not one merged cluster.
* `test_tag_vocab_contains_grid_resolution_limited`.

`tests/test_detect_energy.py` (or the existing energy test module)
* `test_energy_passes_perbin_floor_array` — `detect_bursts` receives an `[n_bins]` array, not a scalar.
* `test_wifi_like_wideband_rate_drops_on_synthetic_narrowband_scene` — a scene of 300 kHz hops plus
  one 20 MHz blob tags `wifi_like_wideband` exactly once and does not tag the hops.

## Files likely touched / what must NOT change

Touch: `aerix_rf/detect/bursts.py`, `aerix_rf/detect/energy.py`, `aerix_rf/detect/raster.py`,
`aerix_rf/dsp/spectrogram.py` (additive `looks` only), `bench/stage1_rc_positives.py`,
`bench/stage1_fa_budget.py`, the three test modules above, and this doc + agent memory.

Must **not** change: the canonical 1024 / Hann / hop-512 STFT and `aerix_rf/datasets/tensor.py`
detector-frame / ML tensor products (no retraining); the `BurstEvent` dataclass field names and
units; the level-1/level-2 label vocabulary (only a **tag** is added, and `TAG_VOCAB` must be
updated); `R_MIN_RASTER = 0.93`, `M_MIN_RASTER`, `DEFAULT_DELTAS_HZ`; the C1 `period_test`
fundamental-first rule, the C2 strongest-N event selection, and the C3 bounded cluster span.
Receive-only throughout.

## Open evidence gaps

* No capture exists where an RC uplink is the only emitter, so every number above is a detector-
  quality statement, not per-burst attribution.
* The per-bin floor and both thresholds are validated on a USRP X310 third-party capture and on
  ANTSDR ambient; they are **not** yet validated against an ANTSDR/HackRF capture containing a known
  bound transmitter (would be level-5 test truth).
* `L_freq_eff` under a Hann window with the 300 kHz boxcar is estimated (≈ size/1.5); measure it
  empirically on AWGN in `test_noise_only_window_false_pixel_rate` and pin the constant.

## § Implementation reconciliation 2026-09-19

Review of the uncommitted C4/C3b implementation against this spec, by the RF/DSP
specialist. Evidence level unchanged: everything here is level-1 morphology quality.
Five test failures; four distinct root causes, all in the *spec* or in a spec-to-code
translation, not in the builders' mechanics. `spectrogram.compute` default output is
still bit-exact (`test_compute_looks1_bit_exact_vs_head` passes, and it diffs against
`git show HEAD:` rather than against itself).

### R1 — `L_freq_eff = W/1.5` is wrong; the correct model is Hann adjacent-bin correlation

The spec asserted that a `W`-bin boxcar over a Hann-windowed STFT yields
`L_freq_eff = W/1.5` (the ENBW factor). That is the *resolution* penalty, not the
*variance* reduction. Adjacent Hann bins are power-correlated, so

```
L_freq_eff(W) = W^2 / (W + 2*rho2*(W-1)),   rho2 = |rho(1)|^2 ~= 0.48
```

Measured on 3905 x 1024 white-noise STFT frames (Hann, hop >= fft, so frames are
independent), `L_hat = mean^2/var` over bins 100..900:

| W | 1 | 3 | 5 | 9 | 15 | 20 | 25 | 31 |
|---|---|---|---|---|---|---|---|---|
| measured `L_hat` | 1.00 | 1.85 | 2.85 | 4.86 | 7.91 | 10.46 | 13.02 | 16.11 |
| model above | 1.00 | 1.83 | 2.78 | 4.76 | 7.76 | 10.28 | 12.83 | 15.90 |
| old `W/1.5` | 0.67 | 2.00 | 3.33 | 6.00 | 10.00 | 13.33 | 16.67 | 20.67 |

At the 15.36/12.288 MS/s dwell (`W = 25`) the old estimate gave `L_eff = 16.7` where the
truth is 13.0: the arm threshold came out 0.45 dB low and the **measured** arm-pixel rate
was 1.7e-5 against the 1e-6 target (17x), hold 5.9e-3 against 2e-3 (3x). Fixed:
`energy._l_freq_eff()` implements the model; `_L_FREQ_EFF_HANN_DIVISOR` is replaced by
`_L_FREQ_ADJ_BIN_RHO2 = 0.48`. `rho2` is an empirical constant measured here, not a
first-principles derivation — flagged as such in the code.

The `threshold_db_for_pfa` arithmetic itself is correct: `L=1 -> arm +11.40 / hold +7.93`,
`L=4 -> +7.27 / +4.83`, `L=13 -> +4.63 / +2.98`. The spec's reference table is slightly
off at `L=13` (it said arm +4.3 dB; the Gamma inversion gives +4.63 dB) and at `L=4`
hold (+5.1 vs +4.83). Treat the code, not the table, as authoritative.

### R2 — the -6 dB edge walk was unbounded below the noise floor

`test_narrowband_bw_perbin_floor_within_2x_of_truth` measured a **median**
`bw_6db_hz` of 12.288 MHz (the whole captured band) on a window containing only
300 kHz bursts. Cause: `_edge_cross` walked until `profile_db < peak - 6 dB` or the
array ended. For a marginal component (peak less than 6 dB above its own hold
threshold, e.g. a 1-frame noise-driven component) the -6 dB level lies **under the
noise floor**, so the walk never crossed and returned the band edge; a few dozen such
components then dominated the median. This is not specific to the per-bin floor — it
was latent before C4 and the corrected `l_eff` only changes how many marginal
components exist.

Fix: `_edge_cross` takes an optional per-bin `stop_db` profile; `_channelise` passes
`floor_db + hysteresis_db`. The walk stops at `max(peak - EDGE_DB, floor_db[j] + hyst_db)`
and interpolates to whichever limit bound. Rationale: a -6 dB edge cannot be measured
below the noise; the widest defensible claim is the width down to the detector's own
hold level. For any component clearing its hold threshold by >= `EDGE_DB` the bound
never binds, so strong bursts are unaffected. `edge_clipped` semantics are unchanged
(it still means "ran off the frequency/time edge of the array"), so no downstream
consumer (`wifi_like_wideband`, `_wideband_events`, `cluster_centres`' `usable` filter)
changes meaning.

### R3 — the clamp reference, and clamping to the boundary instead of to the reference

Two separate defects, both in C4(a) as specified.

**(a) `F_ref = median over bins` is invalid above 50 % band occupancy.** A 16 MHz
emitter in a 20 MHz capture puts the median ON the signal: every idle bin is clamped
*up* to `F_ref - 10 dB` (the detector goes noise-blind) and the occupant's own bins sit
~0 dB over their floor, so it fragments into speckle. `perbin_noise_floor_lin` now takes
`ref_lin`; `energy.detect` passes its existing scalar `noise_lin`, which is estimated
either from non-burst **time** slices (bursty branch) or from the 5th percentile over
bins (continuous branch) and therefore survives up to ~95 % frequency occupancy. The
per-bin Q25 estimate is unchanged — `ref_lin` governs the clamp only, so analog tilt is
still tracked per bin. The median-over-bins default is retained for standalone callers
and its validity limit is documented in the docstring.

**(b) A rejected bin must fall back to the reference, not to the rejection boundary.**
`np.clip` left a continuously occupied bin with a floor exactly `CLAMP_DB` above true
noise, so the occupant's detection margin is `(its SNR - 10 dB)`: a 15 dB continuous
wideband emitter was left ~4.9 dB over its own floor, i.e. right at the +5.6 dB arm
threshold, and speckled across the whole window. The spec's claim that "clamped bins
stay armed for the whole window" only holds for occupants above `CLAMP_DB + arm_db`
(~15.6 dB) — it is false in the 10-15 dB range that matters. Once the clamp binds we
have positive evidence the bin's own estimate is contaminated, so the best remaining
estimate is the band-wide reference itself: `np.where((floor < lo) | (floor > hi), f_ref, floor)`.
The low side is treated identically (a notch/dead bin gets the higher `F_ref`, the
fewer-false-alarm choice).

`tests/test_stage1_c4.py::test_perbin_floor_clamped_at_full_occupancy` asserted the old
boundary behaviour (`floor[0] == F_ref + CLAMP_DB`) and was rewritten to assert the new
one (`floor[0] == F_ref`, within 0.5 dB of true noise, and >= 10 dB below the occupied
bin's own Q25 — i.e. still not self-blinded). Justification: the assertion encoded an
implementation detail that this reconciliation shows to be wrong; the *requirement*
(occupied bins must not self-blind) is asserted more strongly than before.
`test_perbin_floor_bounded_but_biased_near_75pct_occupancy` is unaffected (its bias is
inside the rejection radius, so that bin keeps its own estimate).

### R4 — C3b vs the sparse-wideband merge requirement: resolved by the split point, not by a new rule

The conflict is real but narrower than it looked. Both requirements are satisfied by
`0.75 * pair_bw` alone; the flat cap only had to stop the *pre-existing*
`CLUSTER_MAX_MERGE_HZ = 1 MHz` floor from bridging a full 1 MHz grid step (note
`gap > thresh` is strict, so a pair exactly 1.0 MHz apart merged). The builders applied
the 333 kHz cap to every pair with `pair_bw <= HOP_MAX_CLUSTER_BW_HZ = 2.5 MHz`, which
swept in the 2.4 MHz single-emitter case and re-broke the independent-review fix.

Decision: the grid cap applies only when `pair_bw <= min(DEFAULT_DELTAS_HZ)` (1.0 MHz).
A burst wider than the smallest grid step under test cannot be a channel on that grid,
so the anti-grid-bridging cap has no purpose for it (and such events are excluded from
the hop-set count anyway). With that split point:

* 2.4 MHz pair, 1.1 MHz gap -> cap `max(1e6, 0.75*2.5e6) = 1.875 MHz`, thresh
  `0.75*2.4 = 1.8 MHz` > 1.1 MHz -> merges (one emitter, as the review requires);
* 0.3 MHz pair, 1.0 MHz gap -> cap 333 kHz, thresh `max(tol, 0.225) <= 0.225 MHz`
  < 1.0 MHz -> stays split (two channels of the 1 MHz grid, as C3b requires).

**Rejected alternative: condition on time overlap.** The three sparse samples in
`test_c3_sparse_wideband_burst_stays_one_cluster` are at t = 0.0/0.5/1.0 s — they are
*not* co-temporal, so a co-temporality rule would not have separated the two cases. A
BW-only rule does, provided the split point is the grid step rather than the hop-channel
BW ceiling. Neither test was weakened.

### R5 — residual: continuous-occupant skirt speckle (not fully fixed; new work item C6)

After R1-R3 the 16 MHz continuous emitter is correctly emitted as a single 3842-frame,
16.05 MHz event with the whole band's floor at the true noise level. But ~16 bins in its
spectral **skirt** still have a per-bin Q25 biased 2-10 dB high by the emitter itself
(inside the rejection radius, so not rejected), leaving the emitter marginally armed
there and producing ~229 short fragment events, one cluster of which (56 events,
31 kHz wide, at the +8 MHz edge) yielded a spurious window `cadence_ms = 2.6 ms`.

This is intrinsic to any per-bin floor: there is always a transition band where
`signal/floor` passes through the arm threshold. It cannot be removed by a *global*
clamp reference, and frequency-domain gap bridging does not help (measured: 1718 -> 1184
labels at 1-bin closing, 607 at 3-bin — the fragments are genuinely disconnected).

Interim fix at the evidence layer, which is where the false claim actually mattered:
`energy._is_fragment_of_wideband()` suppresses a window-level `cadence_ms` when the
dominant cluster is concurrent with, and within `0.75 x BW` of, an event at least
`4 x` wider. That is a defensible rule on its own terms (a cadence claim requires
resolved, separated bursts, not fragments of one occupant), not a test-specific patch.

**C6 (proposed, for the architect to schedule):** replace the single global clamp
reference with a frequency-**local** robust reference — a running low quantile of the
per-bin floor over a window specified in **Hz** (~2 MHz), with a tighter rejection
radius (~3 dB). That would reject skirt bins as well as interior bins. It cannot be
done under the current unit tests: `test_perbin_floor_tracks_tilted_noise` uses a 10 dB
tilt across 64 bins (~8 dB/MHz), far steeper than any real analog response, and any
local reference narrower than the array fails it. C6 therefore needs the tilt test
re-specified in Hz/MHz-per-MHz terms first.

### Files changed

`aerix_rf/detect/bursts.py`, `aerix_rf/detect/energy.py`, `aerix_rf/detect/raster.py`,
`tests/test_stage1_c4.py` (one assertion, justified in R3). `aerix_rf/dsp/spectrogram.py`,
`aerix_rf/pipeline.py`, `bench/stage1_rc_positives.py` unchanged by this reconciliation.

### Open evidence gaps

* `rho2 = 0.48` is measured on synthetic white noise through this exact STFT path only.
* The arm/hold P_fa targets are now *correct by construction* but their real-corpus
  consequence is unmeasured: `bench/stage1_fa_budget.py` must be rerun (all four root
  causes change the armed-pixel rate, and R3 raises sensitivity on occupied bins).
* Acceptance items 1 (RFUAV bandwidth truth, 3 slices), 2 (cluster counts 19-75) and
  3 (ambient FA) are not verified here — no bench was run.

## § FA regression 2026-09-19

Observed on `wip/stage1-c4` against the ANTSDR ambient corpus
(`bench/out/stage1_fa_budget_after_c4_v2.{md,json}`, 1160 windows, 6 sessions):

| label/tag | main | wip/stage1-c4 (after C4 reconcile) |
|---|---|---|
| `hopping_candidate` | 11 / 1160 (0.95 %) | **199 / 1160 (17.2 %)** |
| `fixed_channel_burst_candidate` | 205 | **0** |
| `wifi_beacon_like` | 6 | **0** |
| level-2 labels | 0 | 0 |

The pre-reconcile snapshot (`after_c4.json`) had 46/1160, so the reject-to-reference
clamp change of the C4 reconciliation is inside the causal chain, not incidental.

### Root cause (single mechanism, three symptoms)

The three numbers above are **one** failure, not three. The corrected per-bin floor
(`perbin_noise_floor_lin`, reject-to-reference clamp) raises the floor estimate
*inside* bins occupied for more than 75 % of the window — exactly the continuous
Wi-Fi / video occupants that dominate ambient 2.4 GHz. Those bins' own Q25 sits on
the signal; when the bin survives the ±`FLOOR_CLAMP_DB` test its floor is the
signal, and when it is rejected it is pulled to `F_ref`. Either way the *hold*
threshold `floor_db + hysteresis` inside the occupant is much closer to the
occupant's own PSD than it was on main.

`_edge_cross` walks out from the component peak to the −6 dB level but stops early
on `stop_db = floor_db + hysteresis_db`. When the peak is less than `EDGE_DB` above
its own hold threshold, the walk terminates within a bin or two of the peak and
returns a **noise-limited** edge. Consequences:

1. `bw_6db_hz` collapses from the occupant's true 16–20 MHz to sub-bin values.
   With the T1 300 kHz frequency-smoothing boxcar in `energy.detect` no real
   component can measure 6–60 kHz: such widths are threshold artefacts.
2. `centre_hz`, being the midpoint of those two artefact edges, is an artefact
   too — it is wherever the threshold happened to cut the noise skirt, and it
   *moves between bursts*, so repeated fragments of ONE occupant scatter across
   many apparent narrow "channels".
3. The discounts are keyed on the bandwidths that just collapsed:
   `WIFI_WIDEBAND_MIN_BW_HZ = 8 MHz` (`_wideband_events` → `wifi_like_wideband`)
   and `WIFI_BEACON_MIN_BW_HZ = 16 MHz` (`_wifi_beacon_like`). Both stop firing →
   `wifi_beacon_like` 6 → 0, and the R5 level-2 suppression path goes dead.
4. `fixed_vs_hopping` sees the occupant no longer as one wide cluster
   (`fixed_channel_burst_candidate`, 205 → 0) but as ≥ `HOPPING_MIN_M_REPEAT`
   narrow (≤ `HOP_MAX_CLUSTER_BW_HZ`) repeat clusters with a whitened lag-1
   centre autocorrelation — the literal definition of `hopping_candidate`.

So hypothesis (c) (discounts disabled by corrected bandwidths) and hypothesis (a)
(skirt fragments forming ≥ 5-revisit narrow channels) are the *same* mechanism seen
from the discount side and the hop side. (b) and (d) are downstream amplifiers, not
causes.

### Evidence level

This is a level-1 morphology defect. No level-2 label was ever emitted, on either
branch; the regression is that a stage-1 *channel-use* label was produced from
bandwidth/centre numbers that the detector had no resolution to support.

### Fix layer

The right layer is the **event**, not the rule thresholds. Re-deriving
`WIFI_WIDEBAND_MIN_BW_HZ` / `WIFI_BEACON_MIN_BW_HZ` downwards would be fitting the
discounts to a corrupted measurement and would make them fire on genuinely narrow
emitters. Instead `_channelise` now marks `BurstEvent.bw_noise_limited` when either
−6 dB edge walk was stopped by the noise limit, and consumers refuse to treat such
an event as a resolved channel:

* `cluster_centres` excludes `bw_noise_limited` events (as it already excludes
  `edge_clipped` ones) — they carry no usable centre;
* `_wideband_events` excludes them from the `edge_clipped` branch — a fragment at
  a band edge carries no evidence about occupancy width either.

`bw_noise_limited` is strictly narrower than, and supersedes, the R5 cadence
suppression added as a stopgap: it acts on the measurement that is invalid rather
than on the conclusion.

### Measurement (ANTSDR ambient, 40-window probe + full 1160-window bench)

| quantity | value |
|---|---|
| events flagged `bw_noise_limited` | 7404 / 10240 = **72 %** |
| events with `bw_6db_hz` < 2 FFT bins (30 kHz) | 17 % |
| `bw_6db_hz` in bins, p10/p50/p90 | 0.5 / 8.6 / 111 |
| events per window | **256 = the strongest-N cap, saturated in every window** |

`bw_noise_limited` alone is therefore NOT a usable exclusion key: at 72 % it
would discard every weak-but-real burst (any component whose peak sits under
`EDGE_DB + hold_db` ~ 10 dB over its floor), RC hop bursts included. It is used
only in conjunction with a resolution test — see `is_unresolved_fragment`.

The first probe measured the intended fix, plus two variants, on 40 ambient
windows (first 8 of each session — a deliberately dense subsample):

| rule | `hopping_candidate` / 40 |
|---|---|
| none (branch as found) | 29 |
| `bw_noise_limited` only | 11 |
| `bw_noise_limited` AND bw < 30 kHz (2 bins) | 12 |
| `bw_noise_limited` AND bw < 300 kHz (T1 kernel) | 13 |
| + wideband occupancy mask | **3** |

### Second mechanism: occupancy interior speckle (the larger half)

The fragment rule alone left 13/40. Inspecting the survivors showed they are
**not** sub-bin fragments: the repeat clusters are 0.3–1.2 MHz wide with peaks
3–42 dB over floor, at stable distinct centres (e.g. 2431.4 / 2432.1 / 2434.7 /
2439.1 / 2442.0 MHz), all inside the frequency span covered by 4–6 MHz wide
events. This is the same per-bin-floor mechanism acting one level up: inside a
continuously occupied band the floor tracks the occupant's own PSD, so a 20 MHz
Wi-Fi channel never surfaces as one >8 MHz event but as a shifting set of local
maxima — OFDM spectral ripple and modulation speckle — each individually well
above *its own* local floor. Their −6 dB midpoints are genuinely distinct and
they repeat over the dwell: `fixed_vs_hopping`'s definition of a hop set.

The architect's proposed per-event form of the rule ("narrow AND concurrent with
a ≥4× wider event") was measured and is too weak: it caught **6 of 1008** hop-set
member events, because the occupant's pieces are individually short and only
4–6 MHz wide. The working form drops the co-temporality requirement and unions
the wide events into occupancy **spans** first (`wideband_occupancy_spans`,
`is_occupancy_masked`): a narrow event whose centre lies inside a merged span at
least `WIDEBAND_SPAN_WIDTH_RATIO` (4×) wider than itself is a piece of that
occupancy, not a channel. `WIDEBAND_SPAN_MIN_BW_HZ` is set to
`HOP_MAX_CLUSTER_BW_HZ` (2.5 MHz) — "wider than any channel this module models"
— because the occupant's *pieces*, not the occupant, are what the detector
reports: an anchor at 4 MHz left 30/1160, at 2.5 MHz it leaves 16/1160.

This is **masking**, not rejection: a real hopper transmitting inside an occupied
Wi-Fi channel is masked. That is already the documented meaning of the
`wifi_like_wideband` note ("masked/insufficient, not 'no hopper'"), and the
remedy is multi-dwell accumulation on a less occupied centre.

### Result

`bench/out/stage1_fa_budget_c4_fix.{md,json}`, same 1160 ambient windows:

| label | main | branch (before fix) | branch (after fix) |
|---|---|---|---|
| `hopping_candidate` | 11 (0.95 %) | 199 (17.2 %) | **16 (1.38 %)** |
| `fixed_channel_burst_candidate` | 205 | 0 | 166 |
| level-2 labels (`fhss_*`, `rc_link_family`, `droneid_cadence`) | 0 | 0 | **0** |

Budget verdict PASS on every line. Branch tests green (59 passed:
`test_stage1_c4`, `test_detect_bursts`, `test_detect_raster`, `test_detect`,
`test_stage1_rc_positives`, `test_pipeline_cadence_store`) — in particular the
RC-positive fixtures still detect, so the occupancy mask is not eating genuine
hop sets in those captures.

The R5 cadence suppression was NOT removed: the only R5 suppression in the module
(`wifi_beacon_like`/`ble_connection_like` → drop level-2 family labels) predates
this branch, acts on cadence rather than on bandwidth, and is orthogonal to the
fragment/occupancy rules. There is no branch-local cadence stopgap to retire.

### Cost (reviewer condition)

`energy.detect`, 1 s window at 12.288 MS/s (4000 x 1024 frames), median of 5,
idle box:

| path | median |
|---|---|
| `spectrogram.compute` (prerequisite) | 63.9 ms |
| `energy.detect` **without** `iq=` | 168.9 ms |
| `energy.detect` **with** `iq=` (multi-look, `max_looks`) | 320.1 ms |

The multi-look path costs +151 ms, i.e. ~1.9x the detector, ~0.38 s of CPU per
second of capture including the spectrogram. Single-threaded real-time still
holds with margin on both paths, but the `iq=` path should stay opt-in per
receiver profile. Note the FA residual is concentrated in the NON-`iq=`
(single-look) sessions: 15 of the 16 remaining ambient `hopping_candidate`
windows come from the 261 windows captured without `iq=` (5.7 % of them), while
the two large `iq=` sessions (899 windows) contribute 1 (0.1 %). More looks buy fewer false hop sets.

### Remaining gap and open items

* 16/1160 (1.38 %) vs 11/1160 (0.95 %) on main. The residual is single-look
  speckle inside occupied spans that the span union does not reach (no
  >=2.5 MHz anchor event in that window). Candidate next step: derive the
  occupancy span from the per-bin floor's own clamp-rejection mask (bins whose
  Q25 was rejected to `F_ref` ARE the occupied bins) instead of from event
  widths — that is a direct occupancy measurement rather than an inference from
  fragments, but it requires passing the mask from `bursts` through to `raster`.
* The 256 strongest-N event cap is saturated in every ambient window. While
  saturated, "number of events" carries no information and the surviving set is
  biased toward whatever the cap ranks highest; any future rule that counts
  events (not clusters) must account for this.
* `FRAGMENT_MAX_BW_HZ` is hard-coded to the T1 smoothing width (300 kHz). If the
  front-end smoothing changes it must change with it; it should eventually be
  carried on the event or passed from `energy.detect`.

## § FA fix sensitivity 2026-09-19

Review finding on the FA fix (594eed9). Independent reviewer measurement on a
300 kHz component at 12.288 MS/s / 1024 bins:

* `bw_noise_limited` is True for 100 % of bursts at every SNR <= 13 dB and
  False at >= 14 dB;
* the resulting `is_unresolved_fragment` hop-set exclusion dropped 100 % of
  true bursts at <= 10.5 dB, 18 % at 11 dB, 0 % at >= 12.5 dB.

**Verdict: the 594eed9 rule was an SNR test, not a fragment test.** The two
conditions it used (`bw_noise_limited`, and a width below the 300 kHz T1
smoothing kernel) are both consequences of "peak less than `EDGE_DB` = 6 dB
above the hold threshold", so together they select *weak*, not *fragmented*.
RC-positives and DroneID work targets 8-10 dB SNR, i.e. exactly the region the
rule deleted. Not acceptable.

### The missing measurement: occupancy, not strength

A skirt/speckle maximum inside a standing Wi-Fi/video occupant and a weak hop
burst on an idle bin are indistinguishable by *strength*. They are trivially
distinguishable by *how long their bins are busy*, and the C4 per-bin floor
already measures that and then throws it away:

`perbin_noise_floor_lin` estimates each bin's floor as a debiased 25th
percentile over the window, then clamps/rejects it against the band-wide
reference `F_ref` (`FLOOR_CLAMP_DB` = 10 dB). The **pre-clamp** ratio
`10*log10(Q25_debiased / F_ref)` is the discriminant:

| bin | pre-clamp excess |
|---|---|
| idle bin carrying a 10 %-duty hop burst | ~0 dB (Q25 is the noise) |
| bin inside a continuously occupied Wi-Fi/video channel | many dB, usually past the 10 dB clamp so the estimate is *rejected* |

Raw excess alone is still not enough: a *continuously on* narrow emitter also
lifts its own bins (verified — the original reviewer fixture is a duty-1.0
tone, and its 300 kHz component reaches 0.58-0.84 MHz of excess >= 3 dB at
7-18 dB SNR). What separates a fragment from a channel is that the occupied
run around a fragment is **much wider than any channel this module models**.

### Rule implemented (FA fix 2)

`bursts.perbin_noise_floor_lin(..., return_excess=True)` now also returns the
pre-clamp per-bin excess in dB (free: the `np.partition` that produces it is
already paid for). `bursts._occupied_span_hz` converts it, once per window in
O(n_bins), into the width of the contiguous run of *occupied* bins
(`FLOOR_OCCUPIED_EXCESS_DB` = 3 dB) containing each bin. Each `BurstEvent`
records `floor_excess_db` (max over its own footprint, diagnostic) and
`floor_occupied_span_hz` (at its peak bin).

`raster.is_unresolved_fragment` gains a third, decisive conjunct:

```
bw_noise_limited  AND  bw_6db_hz < 300 kHz  AND
floor_occupied_span_hz >= FRAGMENT_MIN_OCCUPIED_SPAN_HZ (1.0 MHz)
```

1.0 MHz is above the widest hop channel this module models (the 1 MHz FHSS
raster) and far below the narrowest standing occupant of interest (5 MHz
analog FPV, 20 MHz Wi-Fi). **Unknown fails open**: an event with no occupancy
measurement (`floor_occupied_span_hz == 0.0`, the default when a caller does
not pass `floor_excess_db`) is never a fragment, so the rule can only ever be
armed by positive occupancy evidence.

Second half of the fix (item (c) of the review): when `bw_noise_limited`, the
-6 dB midpoint is a coin flip between two noise crossings, but the peak is
still a real local maximum. `_channelise` now re-estimates `centre_hz` as the
floor-subtracted power-weighted centroid of the bounded (`CENTROID_MAX_BINS` =
64) contiguous above-hold run around the peak, and records
`centre_source = "above_hold_centroid"`. `bw_6db_hz` stays a lower bound and
stays flagged by `bw_noise_limited`; only the centre is repaired. This is the
"keep it as a hop-set member with an unreliable bandwidth" branch: a weak
burst keeps a stable centre for R1/R2 instead of being dropped.

The `wideband_occupancy_spans` / `is_occupancy_masked` half of 594eed9 is
unchanged (R5 discriminant: a narrow event inside a merged occupancy span >= 4x
wider is masked, not rejected).

### Sensitivity, measured

Harness `item1_sensitivity_fix2.py` (rerunnable; same fixture family as the
reviewer's). "Counted" = survives the full `cluster_centres` usable filter
(not edge-clipped, not an unresolved fragment, not occupancy-masked), 60
trials/point, 12.288 MS/s / 1024 bins, 300 kHz Gaussian component.

Fixture **hop_train** (4-frame bursts every 40 frames, 10 % duty, isolated
band — the physical case the acceptance criterion is about):

| SNR dB | detected/60 | frac counted main | frac counted 594eed9 | frac counted fix 2 |
|---|---|---|---|---|
| 5 | 9 | 1.00 | 0.00 | 1.00 |
| 6 | 9 | 1.00 | 0.00 | 1.00 |
| 7 | 11 | 1.00 | 0.00 | **1.00** |
| 8 | 14 | 1.00 | 0.00 | 1.00 |
| 9 | 22 | 1.00 | 0.00 | **1.00** |
| 10 | 45 | 1.00 | 0.00 | 1.00 |
| 11 | 60 | 1.00 | 0.03 | 1.00 |
| 12 | 60 | 1.00 | 0.83 | 1.00 |
| 14 | 60 | 1.00 | 1.00 | 1.00 |
| 18 | 60 | 1.00 | 1.00 | 1.00 |

Acceptance (>= 90 % counted at 9 dB, >= 50 % at 7 dB): **PASS**, 100 % at both.
`floor_occupied_span_hz` is 0.00 MHz at every SNR for this fixture, i.e. the
rule is not merely inactive by luck — the occupancy evidence it requires is
genuinely absent. Regression-guarded by
`tests/test_detect_raster.py::test_hop_member_sensitivity_9db`.

Note on the *detected* column: below ~11 dB the component is not detected in
every trial at all. That is the arm/hold P_fa threshold, identical on main and
on the branch, and is a separate (real) sensitivity question from hop-set
membership — it is why the table reports the counted *fraction of detections*.

The reviewer's original duty-1.0 fixture behaves identically on main and on
fix 2 (frac_main == frac_fix2 at every SNR). Its apparent collapse above 9 dB
is `edge_clipped`: a component present in every frame touches both time edges
by construction, which `cluster_centres` has always excluded. That fixture
therefore cannot measure this rule above ~8 dB; use `hop_train`.

### False alarms, measured

ANTSDR ambient corpus, 1160 windows, `bench/out/stage1_fa_budget_c4_fix2.md`:

<!-- FA-TOTAL-ROW -->

### Open gaps

* The occupancy discriminant is blind to a standing occupant narrower than
  1 MHz that fragments (none observed; would need a narrowband continuous
  emitter with strong spectral ripple).
* A hopper that dwells >25 % of the window on one bin lifts its own bin's Q25;
  with a hop set of >= 4 channels each bin's duty is < 25 % and the excess stays
  ~0 dB, but a 2-channel hopper at 50 % duty per channel would self-flag. The
  1 MHz span floor protects it (its occupied run is one channel wide), but this
  is an untested corner.
* Not yet measured on real weak-hopper IQ: RC-positives at 8-10 dB SNR against
  a *live* Wi-Fi occupant is still the outstanding validation.

### CPU decision (2026-09-19)

`aerix_rf.pipeline.process_window` was calling `energy.detect(..., iq=win.iq)`
unconditionally, unlocking the C4(c) detector-local multi-look recompute on
every window at `MAX_DETECTOR_LOOKS = 8`. Measured wall time of
`energy.detect()`, synthetic 1 s complex64 IQ at 12.288 MS/s (fft_size=1024,
one narrowband bursty component + noise floor; `.venv`/scipy.fft
`workers=-1`), 15 repetitions after 1 warmup call, on a loaded 24-core box
(load average ~12 from two concurrent stage-1 benches running from this
worktree; min is the least-contended reading, closest to an idle box):

| `max_looks` (`iq=`)        | min (ms) | median (ms) |
|-----------------------------|---------:|------------:|
| 1, `iq=None` (no recompute) |    160.7 |       168.4 |
| 2                            |    341.6 |       398.3 |
| 3                            |    373.1 |       421.8 |
| 4                            |    382.7 |       468.7 |
| 8 (previous default)        |    369.9 |       436.5 |

At this rate/fft_size, `hop = 3072` (see `dsp.spectrogram`'s
`_TARGET_FRAMES` time-decimation) and `fft_size = 1024`, so
`n_looks = min(max_looks, hop // fft_size)` clamps to 3 for any
`max_looks >= 3` — `max_looks` in {3, 4, 8} all run the *same* recompute, and
even `looks=2` is nearly as expensive. `cProfile` on the `looks=3` recompute
path (`aerix_rf.dsp.spectrogram.compute`) shows the cost is dominated by the
second STFT's fancy-index gather of `looks` contiguous sub-frames per hop,
its FFT, and a `fftshift` over the full `[n_starts, looks, fft_size]` array —
not by the look count itself. Reordering `fftshift` to run after the
per-look mean (shifting a `[n_starts, fft_size]` real array instead of the
3x-larger complex one) measured no reliable improvement under this box's
contention (142 ms vs 158 ms on repeated A/B runs — noise-dominated, not a
real win) and was not adopted.

Deriving the multi-look product from the existing canonical `spec` instead of
a second STFT (this task's suggested alternative) is **not possible without
changing the canonical representation**: the canonical `Spectrogram` already
has its hop widened past `fft_size` (`_TARGET_FRAMES` decimation) specifically
to bound frame count, so it stores only one look's worth of samples per hop
step — the other `looks - 1` sub-frames per hop were never computed and
aren't recoverable by re-averaging `spec`'s own frames. Computing them
requires touching the raw `iq`, which is exactly what the recompute already
does; there is no cheaper equivalent that avoids a second STFT over the
window.

Conclusion: no `max_looks >= 2` fits the ~220 ms/window budget on top of the
~169 ms no-recompute baseline (extra cost is ~200-300 ms, roughly constant
across `looks` values, not proportional to them). Smallest change: disable
the detector-local recompute by default. `MAX_DETECTOR_LOOKS` in
`aerix_rf/detect/energy.py` is lowered from 8 to 1, and a new
`Config.detector_looks` knob (`AERIX_RF_DETECTOR_LOOKS`, default `1`) gates
whether `pipeline.process_window` passes `iq=win.iq` to `energy.detect()` at
all (`iq=None` when `detector_looks <= 1`, matching the measured ~169 ms
no-recompute path exactly). Setting `AERIX_RF_DETECTOR_LOOKS=2` (or higher)
re-enables C4(c) for anyone who can afford the measured cost (e.g. offline
replay/bench runs, not the 1 Hz live loop). C4(c) itself (the averaging math)
is unchanged; this is a call-site/default change only.

## Status 2026-09-19 (main)

Status: merged into main after the Fable gate 2026-09-19 (see stage1-rc-positives-2026-09-19.md).

### C5 implemented on main (2026-09-19)

`analyze_raster(..., bin_hz=)`: G1 (`bin_hz > Δ/20`) is a **column-level** tag — `GRID_RESOLUTION_LIMITED` is
emitted whenever the caller's bin pitch cannot resolve a tested grid step, independent of channel count, so a
resolution-limited column is always visibly marked; G2 (median burst width < 8 bins) applies only when a 1/2 MHz
lattice was actually found. Level-2 grid labels are withheld under either guard; numeric RasterEvidence fields stay
populated for diagnostics. Registry rates 12.288/13.44/15.36/20 MS/s at 1024 never trip G1; the bench `full_band`
column (100 MS/s/1024) does, and the new `full_band_4096` column (24.4 kHz bins) does not. Ambient FA unchanged:
11/1160 hopping, level-2 0 (bench/out/stage1_fa_budget_after_c5.md).
