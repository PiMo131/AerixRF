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
