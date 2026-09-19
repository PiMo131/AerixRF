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

## Status 2026-09-19 (main)

C4 implemented and reconciled on branch `wip/stage1-c4` (see that branch's copy of this document for
"§ Implementation reconciliation" R1–R5). Ambient FA on the branch: hopping 199/1160 = 17.2 % vs 0.95 % on main →
parked; main keeps C1–C3 only. Do not merge without an FA rerun ≤ ~1.5 % and level-2 = 0.

### C5 implemented on main (2026-09-19)

`analyze_raster(..., bin_hz=)`: G1 (`bin_hz > Δ/20`) is a **column-level** tag — `GRID_RESOLUTION_LIMITED` is
emitted whenever the caller's bin pitch cannot resolve a tested grid step, independent of channel count, so a
resolution-limited column is always visibly marked; G2 (median burst width < 8 bins) applies only when a 1/2 MHz
lattice was actually found. Level-2 grid labels are withheld under either guard; numeric RasterEvidence fields stay
populated for diagnostics. Registry rates 12.288/13.44/15.36/20 MS/s at 1024 never trip G1; the bench `full_band`
column (100 MS/s/1024) does, and the new `full_band_4096` column (24.4 kHz bins) does not. Ambient FA unchanged:
11/1160 hopping, level-2 0 (bench/out/stage1_fa_budget_after_c5.md).
