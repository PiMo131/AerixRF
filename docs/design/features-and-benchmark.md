# Stage-2 features v2 + first cross-receiver benchmark

Status: design, 2026-09-18. Builds on `docs/design/canonical-representation.md` (15.36 MS/s canonical,
FFT 1024 / hop 512, ANTSDR live 12.288 MS/s -> 5/4 to canonical) and `docs/design/dataset-normalization.md`
(canonical `[n_ms x 1024]` dBFS tensor, sidecar, group splits, tiers A-D).

**Conclusion.** The current `classify/train/features.py` axis is a *fraction of the captured band*, which
is why the DroneRF bundle is rate-locked and why nothing transfers across receivers. `features_v2` replaces
it with an absolute-Hz axis restricted to the HackRF n ANTSDR **common usable band of 10.0 MHz**, plus
time-domain occupancy/cadence and shape descriptors, all expressed relative to a *per-bin* noise floor.
The benchmark that this unlocks today measures **false-positive behaviour on real ANTSDR ambient** and
**recall on public (anechoic) positives**. It does **not** measure field detection performance, because we
have zero ANTSDR-captured drone positives.

## 1. `features_v2`

### 1.1 Axis and band

Input is the canonical tensor `T = ml_tensor(iq, fs)`, float32 dBFS, `[n_ms x 1024]`, 1.000 ms frames,
plus the 200 us `detector_frames` for the time-domain group. Bin centre `f_k = (k - 512) * 15 000 Hz`
(fftshifted, bin 512 = DC = tuned centre).

* Common band: HackRF declares 12.0 MHz usable, ANTSDR-IIO 10.0 MHz -> **10.0 MHz** is the intersection
  and the only band in which a model may be shared. `usable_mask(15.36e6, 10.0e6)` already yields it.
* **Exact bin range: k in [179, 845] inclusive = 667 bins, spanning +-4.995 MHz (9.990 MHz).**
* **DC notch: k in [510, 514]** (+-30 kHz) is replaced by linear interpolation across the notch before any
  statistic. LO leakage is a pure receiver fingerprint and differs per device/gain.
* Sub-band grid for fixed-length output: 64 sub-bands, sub-band `j` = bins
  `[179 + floor(j*667/64), 179 + floor((j+1)*667/64))` -> 10 or 11 bins each (~156-165 kHz).
  The grid is anchored in absolute Hz, so it is identical for every receiver and every dataset.
* Windows whose tuned centre differs are **not** re-aligned: the axis is offset-from-tune, and tuning
  raster differences are a real, reportable limitation (a 2437 MHz dwell clips a 2429.5 MHz DroneID burst).

### 1.2 Noise-floor reference (the device-independence lever)

Two floors, deliberately different:

* **Per-bin floor** `nf_k` = 10th percentile over time of `T[:, k]`. Subtracting it removes analog filter
  shape, passband tilt/ripple, gain, NF *and* any static CW interferer, per receiver, with no calibration
  file. All shape/level features are computed on `R = T - nf_k` ("dB above local floor").
* **Scalar floor** `nf0` = median over k of `nf_k`, used only as the occupancy threshold reference and for
  the SNR-like scalars.

`nf0` itself (absolute dBFS) is **not** in the feature vector; it is the single strongest receiver
fingerprint. It is carried in the sidecar/context for diagnostics only.

### 1.3 Feature groups (total 292, fixed length, float32, deterministic)

| # | Group | Dim | Content | Reference |
|---|---|---|---|---|
| G1 | sub-band level | 192 | per sub-band median / p90 / p99 of `R` over time (dB above floor) | relative |
| G2 | band scalars | 8 | spectral flatness of the time-median PSD, freq-kurtosis, freq-skew, p99-p50 spread, occupied-bin fraction at +6/+10 dB, peak-to-floor dB, centroid offset (Hz, absolute) | relative (centroid absolute Hz) |
| G3 | occupancy / cadence | 12 | duty cycle; bursts/s; burst-duration p10/p50/p90 (200 us frames); inter-burst-interval p10/p50/p90; normalised autocorrelation peak height and lag of the frame-power series; fraction of frames above floor+6 dB; on/off power ratio | relative + absolute time |
| G4 | bandwidth / shape | 10 | occupied BW at -3/-10/-20 dB below in-band peak; left/right roll-off slope (dB/MHz); flat-top ratio; number of contiguous occupied clusters; widest-cluster BW; cluster BW p50; symmetry about the occupied centroid | relative levels, absolute Hz widths |
| G5 | time-frequency dynamics | 70 | per sub-band (p90-p50) of `R` over time (64); spectral-flux p50/p90; argmax-bin hop rate; argmax-bin spread (Hz); fraction of frames with >1 cluster; time-variance of occupied BW | relative |

`features_v2` is a module-level constant list of names + a `FEATURES_VERSION = "features_v2"` string; the
name list is the contract and is hashed into the bundle.

**Rules that must hold:**
* Window duration is never a feature, and no feature may be a monotone function of `n_ms`.
* G3/G5 require observation time. Features in G3 and the flux/hop parts of G5 are only defined for windows
  with `n_ms >= 100`; shorter windows (RUB fragments are 4.5 / 14.55 ms) set a `feature_valid_mask` and may
  only be scored with G1/G2/G4. Silently zero-filling G3 on RUB fragments would make "fragment" and
  "drone" the same feature.
* No cross-window statistics, no dataset-level normalisation: everything is computed inside one window, so
  live and training paths are literally the same code (the property the current module already gets right).

### 1.4 Device-confound list and how each is neutralised

| Confound | Effect on naive features | Neutralisation | Residual risk |
|---|---|---|---|
| RF/BB gain, AGC state | whole PSD shifts in dB | per-bin floor subtraction; `nf0` excluded | AGC *changes mid-window* distort G3 -> log AGC state in sidecar, prefer fixed gain |
| ADC bits (HackRF 8b, AD9361 12b) | different quantisation floor, different tail shape | relative dB + p99 capped; no feature below floor+0 dB | high-percentile tails still differ; probe must check |
| Analog filter shape / passband ripple | static tilt looks like "shape" | per-bin floor is exactly this template | filter edges excluded by the 10 MHz band restriction |
| Noise-figure / floor level | absolute level | relative dB everywhere | detection *threshold* in dB above floor is device-fair, sensitivity is not |
| LO leakage / DC spur | huge centre bin | DC notch interpolation | large IQ imbalance images remain |
| RBW / sample rate | different bin power | all inputs decimated to the canonical 15.36 MS/s / 1024 grid before features | resampling ripple from public-dataset decimation |
| Record length | length-correlated stats | G3 gating + no duration feature | short-fragment datasets can only be scored on shape |
| Tuning offset | signal at different bins | axis is offset-from-tune, absolute Hz | emitter-raster mismatch is a real loss, not hidden |
| `iq_full_scale` (2048 vs 32767) | dBFS offset | relative dB | affects only diagnostics `[MEASURE]` |

### 1.6 Implementation review 2026-09-18 (rf-dsp-specialist; F1 accept with blockers)

Bin arithmetic verified: `k in [179,845]` = 667 bins = +-4.995 MHz, fftshift index 512 = DC, notch [510,514] = +-30 kHz; test-5's -0.4 MHz / 9 MHz substitution is legitimate (spans -4.90..+4.50 MHz). All groups are deterministic and finite-safe (no NaN/Inf path found); the defects below are *definitional*, not coding errors.

**M1 blocker - shape reference blind to duty < 0.5.** G2/G4/centroid run on `r_med = median_t(R)`. Measured: 2 MHz emitter, +20 dB, duty 0.30 -> `g2_occ_frac_6db` 0.000, `g2_peak_to_floor_db` 0.6, `g4_bw_m3db_hz` 10.01 MHz, i.e. indistinguishable from noise; DroneID beacons and FHSS control links are all far below 50 % duty. Fix: `r_shape = percentile(R, q_shape=99.0, axis=0)` feeds G2/G4/centroid (no name/dim change); G1 keeps median/p90/p99 since it carries duty. Verified: 2 MHz at duty 0.02 then reads bw 2.00 MHz, level 19.3 dB.

**M2 blocker - the temporal floor absorbs any emitter with duty > 0.9.** Measured: 6 MHz continuous +25 dB -> `occ6` 0.000, `peak_to_floor` 0.5 dB. Decision: **(b) window-internal spectral floor, with (a) as sidecar-only** - no cross-window state, so live == replay still holds. `nfs_k = polyval(polyfit(deg=2, x=(k-512)/333))` of `r_shape`'s absolute-dB PSD, fitted over the quietest 30 % of in-band bins, then one refit over bins with residual <= +3 dB; fall back to `percentile(S,10)` if fewer than 40 bins survive. `nf_k` and G1-G5 unchanged. Add **G6, 10 dims (292 -> 302)** on `Rs = T - nfs_k`: occ_frac at +6/+20 dB, persistent_bw_hz, widest_cluster_hz, level_p50/p90_db, centroid_hz, flatness_occupied, frac_time_occupied (frames with band-max `Rs` > 6 dB), floor_delta_db = `median_k(nf_k - nfs_k)` (how much the temporal floor swallowed). A slow cross-window `nf0` history may live in the sidecar for diagnostics but must not enter the vector.
*Acceptance test, prototyped, 300 ms windows:* 6 MHz / +25 dB / duty 1.0 -> occ 0.601, bw 6.01 MHz, level 25.0 dB, frac_time 1.00, delta 23.9 dB, **bit-identical under +20 dB gain and under +-3 and +-6 dB linear tilt**; noise-only -> occ 0.000, bw 0.0 MHz, delta -1.1 dB; the same emitter at duty 0.20 -> occ 0.601 but frac_time 0.20, delta -1.0 dB, so persistent and bursty separate. Limit to report rather than hide: above ~70 % band occupancy the spectral floor degrades too (9 MHz continuous -> occ 0.36, widest 1.83 MHz, delta 1.1 dB), so a centred continuous 20 MHz Wi-Fi channel is unrecoverable inside a 10 MHz dwell - that is a scan-placement problem, not a feature problem.

**M3 blocker - G5 argmax features degenerate.** `g5_argmax_hop_rate` measured 0.997 / 1.000 / 0.997 and `g5_argmax_spread_hz` 2.98 / 2.86 / 2.63 MHz for noise / continuous emitter / burst: argmax over 667 noise-dominated bins carries nothing. Fix: argmax over the 64 sub-band means, count only frames whose band-max `R` >= +6 dB, define a hop as a move of >= 2 sub-bands, and emit 0 + invalid if fewer than 2 frames qualify.

**M4 must-fix - G3 crosses statistic domains.** `nf0` comes from the 30-average tensor while the threshold is applied to 6-average detector frames, so frames from `dsp/spectrogram.py` (documented ~6 dB scale offset) silently shift +3/+6 dB. Use `nf0_det = median_k(percentile_t(10*log10(band_lin), 10))`. G3 is also a *band-mean* detector - a 300 kHz burst needs ~+21 dB per-bin SNR to cross +3 dB - so make the statistic greatest-of over the 64 sub-bands. Keep +3/+6 dB, `q_shape`, `deg` and `keep` configurable.

**M5 must-fix - the autocorrelation always returns lag 1** (measured peak 0.999 at 0.200 ms on a periodic burst train): the global ACF max excluding lag 0 is at lag 1 for any smooth series. Use unbiased normalisation and take the first local max *after* the ACF first crosses zero, lag <= n/2.

**Receiver-ID leak (Q4).** Hop-timing jitter is not a leak path (hop 512 and the x30 block-mean are fixed by the canonical representation); *noise-fluctuation scale* is. `g5_flux_p50` measured 150 / 226 / 451 / 754 and `g1_sb00_p99` 0.73 / 1.08 / 2.16 / 3.51 for per-bin noise sigma 0.2 / 0.3 / 0.6 / 1.0 dB - a direct readout of ADC bit-depth, decimation-induced bin correlation and notch interpolation. Self-normalise (divide flux by the median per-frame flux of the 32 quietest sub-bands; subtract the across-sub-band median from `g5_sbXX_p90_p50`); `g5_flux_*`, `g5_sbXX_p90_p50` and `g1_*_p99` are the first ablation targets if the label-matched probe fails. Dropped samples also spike flux, so the sidecar must carry a per-window drop count and such windows must be excluded from the probe.

**Should-fix.** An unoccupied window gives G4 bw3 = bw10 = bw20 = 10.01 MHz, flat-top 1.0 and roll-off 0 - the same encoding a band-filling emitter gets, and roll-off 0 also means "contours coincide". Gate G4 to zeros when `max(r_shape) < 6 dB` and clamp coincident-contour roll-off to a documented maximum.

**Tests and sequencing.** No current test uses duty < 0.5 or duty = 1.0 (all are 0.70-0.75), which is exactly why M1 and M2 survived; add the M2 acceptance case plus duty in {0.02, 0.20, 1.00}. M1-M3 change feature values and M2 changes the 292-D name contract, so all three must land **before** F2/F3 train anything - make the dimension change once, now.

## 2. Receiver-ID probe (mandatory control)

Train a classifier (same pipeline, grouped split) to predict `dataset_id` / `receiver_id` from
`features_v2`. Report **balanced accuracy** against chance `1/K`.

Two variants, and the second is the one that matters:

1. **Unrestricted probe** (all windows). This is an *upper bound only*: `dataset_id` is confounded with
   emitter content (Zenodo = drones in an anechoic chamber, ANTSDR = Wi-Fi ambient), so high accuracy here
   may be real signal difference, not device leakage.
2. **Label-matched probe** — restricted to one label at a time (today: background/empty windows, the only
   label present in more than one dataset). This isolates device confound.

Pass thresholds (label-matched probe):
* `<= chance + 0.10` -> pass; features are device-fair enough to quote Tier A/B.
* `chance + 0.10 .. chance + 0.25` -> conditional; report the number next to every accuracy figure.
* `> chance + 0.25` -> fail. Run the permutation-importance ablation, drop or re-reference the leaking
  features, re-run. No cross-receiver claim may be made while the probe fails.

The probe result is written into the benchmark report and into any model bundle metadata.

## 3. Benchmark protocol on data that is local *today*

### 3.1 What exists

* `drone_link` positives: `zenodo_drone_rf_video_2020` (2.44 GHz band files, 120 MS/s -> canonical;
  10 models, one recording per (model, band) -> **no in-dataset run split**), and `rub_dronesecurity`
  (DJI O2 DroneID fragments, 50 MS/s, pre-segmented, 4.5/14.55 ms -> shape features only, evaluation only).
* `background` / Wi-Fi ambient negatives: ANTSDR sessions captured 2026-09-18 at 2437 MHz, 12.288 MS/s
  cs16, Wi-Fi-dominated. **This is the only real-world negative truth we have.**
* `dronerf` is real-valued amplitude only (I/Q question still open) -> excluded from v2 benchmark.
* HackRF 2026-09-04 sessions are **not on this machine** -> Tier C is not runnable. `[USER]`

### 3.2 Tiers

| Tier | Setup | Supports the claim | Does NOT support |
|---|---|---|---|
| **A** | in-dataset, group held out (Zenodo model-level hold-out; group = `(dataset, device, run)`) | "same receiver, unseen model, anechoic: separable" | any field number; Zenodo has no interference, so its "empty" slices are not a background class |
| **B** | leave-one-dataset-out: train Zenodo (+ANTSDR negatives), test RUB positives | "recall transfers to another receiver/another DJI link" | PFA (RUB has no negatives); RUB fragments are pre-segmented, i.e. someone already did the detection |
| **C** | cross-receiver on our own HackRF captures | — | **blocked**, no local HackRF sessions |
| **D** | ANTSDR ambient hold-out, never used for training or threshold selection | **false-alarm rate on real crowded 2.4 GHz** | PD — there are no ANTSDR drone positives |

Tier D needs two disjoint ANTSDR ambient splits by session group: a *dev* split for choosing the operating
threshold and a *test* split (different session/day) reported once.

### 3.3 Metrics

* Window-level PD (recall) per positive **group**, never pooled: report min/median/max across the 10 Zenodo
  models, since a single model can carry the mean.
* PFA per window **and** false alarms per hour of ambient at the operating point chosen on the Tier-D dev
  split. FA/hour is the number an operator can act on.
* PR curve + AUPRC per tier; class priors in the benchmark are arbitrary, so ROC-AUC alone is misleading.
* Confidence intervals by **group bootstrap** (resample groups, not windows). With ~10 positive groups the
  intervals will be wide; that is the honest answer, not a defect to hide.
* Every table carries the receiver-ID probe number for the same feature set.

### 3.4 Honest framing (must appear verbatim in the generated report)

> We have no ANTSDR-captured drone positives. This benchmark measures (a) false-positive behaviour of the
> Stage-2 classifier on real ANTSDR ambient RF and (b) recall on public positives captured by other
> receivers, mostly in an anechoic chamber. It is not a field detection-performance measurement, and no
> number in it is a PD claim for the deployed system. All positives are evidence level 5 *scene* truth from
> the source dataset, not per-window truth; Stage-2 output remains evidence level 2.

## 4. Builder tasks (ordered, bounded, synthetic-testable)

**F1 — `aerix_rf/classify/features_v2.py` + tests.** Implement the 292-D vector over `[n_ms x 1024]` dBFS
tensors + detector frames. Pure function, no I/O, no sklearn. Export `FEATURES_VERSION`, `FEATURE_NAMES`,
`extract_v2(tensor, detector_frames, fs, usable_bw_hz) -> (np.ndarray[292], valid_mask)`.
*Accept:* synthetic fixtures — (i) pure noise -> all relative levels ~0 dB, duty ~0; (ii) CW tone at a known
offset -> centroid within one bin, occupied BW ~= RBW; (iii) 10 MHz OFDM-like burst train at 500 ms cadence
-> G3 cadence lag within +-1 frame, duty within 10 %; (iv) the same signal at +20 dB gain and on a +15 dB
sloped noise floor -> vector unchanged within 0.5 dB (the confound test); (v) DC spur -> no effect;
(vi) 4.5 ms input -> G3 entries masked invalid, no exception; (vii) byte-identical output across two runs.

**F2 — `bench/receiver_id_probe.py`.** Grouped split, balanced accuracy vs chance, both variants (§2),
permutation importance top-20, JSON + stdout summary, non-zero exit on `fail`.
*Accept:* synthetic two-"device" set differing only by gain/floor -> probe at chance; differing by an
injected per-bin passband tilt that bypasses the floor subtraction -> probe near 1.0 (the probe can detect).

**F3 — `bench/benchmark_features_v2.py`.** Runs tiers A/B/D over the normalised window store, emits
`bench/reports/features_v2_<date>.md` with one table per tier, per-group rows, group-bootstrap CIs, the
probe number, the §3.4 paragraph, and the dataset/code/feature versions + config sha256.
*Accept:* runs end to end on a small synthetic store; refuses to run if any group spans two splits; refuses
to report Tier C without HackRF data rather than silently omitting it.

**F4 — wire into live Stage-2.** `aerix_rf/classify/model.py` uses `features_v2` when the bundle declares
`model_features_version == "features_v2"`; rule fallback stays intact and untouched; a mismatch sets a new
`Classification.model_features_mismatch` flag (alongside the existing `sample_rate_mismatch`), logs once,
and falls back to rules rather than feeding wrong-shape vectors.
*Accept:* existing fallback tests still pass; a bundle with no version string -> rules + flag; a v2 bundle
-> ML path; live and training vectors byte-identical on the same window.

## 5. First results and interpretation (2026-09-18)

rf-dsp-specialist reading of `bench/out/benchmark_features_v2.md` and `bench/out/receiver_id_probe*.md`.
All numbers below recomputed from the prepared ANTSDR corpus (571 rows, all 6 sessions, G3 masked).

**5.1 Tier-D PFA = 1.0 on session `fac0aacf` is a receiver-state change, not a neighbour's AP.**
Per-session in-band (bins 179-845) means over windows - median dBFS / time-p99 dBFS / passband
edge-minus-centre: the 5 other sessions -81.2..-83.7 / -56..-60 / +7..+9.5 dB (U-shaped, identical across
sessions); `fac0aacf` -78.6 / -73.6 / +1..+3 dB (shallow monotone tilt). Three facts must be explained together: the floor is ~5 dB higher, the band is *empty* (p99 only ~5 dB
above the median, i.e. no emitter at all), and the **shape** of the noise floor changed. A scene change
(AP off) cannot change floor shape; a scalar gain change cannot flatten it. The joint signature -
elevated, flattened floor with zero external energy - points at the front end: default `rx_rf_bandwidth`
/ gain-mode (AGC) / antenna-port state of the `a_iq_default` path, i.e. the "same antenna and gain" premise
is falsified by the data. Sidecar `receiver.gain` is `mode=unknown, db=None` for every session, so this
cannot be confirmed from metadata - itself the gap to close.

**5.2 What separates it (top-10, standardized mean difference `fac0aacf` vs the rest).**
`g4_widest_cluster_bw_hz` (9.7e4 vs 9.85e6 Hz, smd -19.6), `g1_sb2x-3x_p90` (2.7 vs 23-25 dB, smd -13..-16),
`g2_occ_frac_10db` (0.005 vs 0.959), `g2_occ_frac_6db` (0.018 vs 0.989), `g5_sb2x_p90_p50` (0.4 vs 12).
Every one is a **scene-occupancy** feature, not a level or time-dynamics feature: the per-bin floor
subtraction did its job on the 5 dB offset. 208 of 290 columns separate the session perfectly
(single-feature AUC 0.000 or 1.000) - a domain change, not drift.

**5.3 Mechanism of PFA = 1.0.** In the other 5 sessions Wi-Fi ch 6 (2437 MHz, 20 MHz wide) saturates the
whole 10 MHz dwell >95 % of the time at +24 dB. Zenodo positives are anechoic: quiet band plus one
emitter. The learned boundary is therefore **"saturated band = background, quiet band = drone"** - a
chamber-vs-ambient discriminator, not a drone detector. `fac0aacf` is a quiet ANTSDR band, so every window
lands on the positive side. PFA = 1.0 falsifies the classifier, not the session; it is the most useful
number in the run. It is amplified by 5.5: `rate_warning` removed 121/122, 56/60 and 54/59 windows of the
Wi-Fi-rich sessions, leaving `fac0aacf` as 298/338 = 88 % of the whole ANTSDR class.

**5.4 Receiver-ID probe BA 0.434 is an evaluation artefact, not evidence of no leakage.** `GroupKFold`
balances folds by *size*: fold 0 = the 298 `fac0aacf` rows alone, fold 1 = 20 rows - 90 % of pooled
out-of-fold predictions come from folds with **zero Zenodo test rows**, so they cannot contribute to the
Zenodo recall term, while that term rests on 16 rows in 3 folds trained on 9-14 Zenodo vs 328-333 ANTSDR.
A constant predictor scores BA exactly 0.5, so BA < 0.5 requires an *anti-correlated* boundary on held-out
groups: it measures session-level domain shift, not device fingerprint, and `margin <= +0.10 -> PASS`
turned a broken evaluation into a green light. Fixes: `StratifiedGroupKFold`; a per-fold guard (>=2 groups
and >=5 rows of each class in train and test, else drop the fold and say so); `class_weight="balanced"`
plus majority-group subsampling to <=4x; report per-fold confusion and per-class recall, not only pooled
BA; and a verdict level **INCONCLUSIVE** for BA below chance or any guard trip - PASS must require an
*informative* probe.

**5.5 `rate_warning` exclusion.** The flag came from a trailing-window rate estimate; per-session cumulative
ratios on loss-free runs span 0.67-1.27, so it is a false-positive generator. For existing sidecars exclude
rows only from sessions with a real deficit (`soak10min_b`, ~5 %) - that restores 233 rows and rebalances
the ANTSDR negative pool. Going forward replace the `notes` string with a typed `samples_deficit` =
`(expected - delivered)/expected` from a monotone sample counter, stored per window *and* cumulatively per
session; exclusion becomes `window.samples_deficit > 1e-3 or session.samples_deficit > 1e-2`.

**5.6 What the benchmark can and cannot claim.** It can claim that `features_v2` extraction is stable over
571 real ANTSDR ambient windows and 18 public positives, that recall on anechoic public positives is high
(Tier A median 1.000, Tier B 2 groups), and that the current Stage-2 boundary produces zero false alarms on
five Wi-Fi-saturated ANTSDR ambient sessions and 3600 FA/h on one quiet-band session. It **cannot** claim
any detection probability for the deployed system, any cross-receiver transfer (the label-matched probe is
still not runnable, and the unrestricted probe is now known to be uninformative), or that Tier-A recall
reflects anything other than an anechoic-vs-Wi-Fi-ambient contrast; no number here is evidence above
level 2. **Single highest-value acquisition: ANTSDR-captured drone positives with an interleaved ON/OFF
schedule inside one session** - same room, same receiver state, operator-logged transmit intervals - so
positives and background share both scene and front-end state and the chamber-vs-ambient shortcut dies.
Record `gain.mode`, `gain.db`, `rx_rf_bandwidth` and antenna port per capture while doing it.

## 6. Open items

* `[USER]` ANTSDR-captured **drone positives** with operator truth — the single highest-value capture we
  can make. Without them Tier D is PFA-only and no PD claim exists for our receiver.
* `[USER]` HackRF 2026-09-04 sessions onto this machine (or re-capture) to unblock Tier C.
* `[MEASURE]` ANTSDR ambient session root/path and count of usable hours (not found on this host during
  this pass); needed to size the Tier-D dev/test split.
* `[MEASURE]` `iq_full_scale` for AD9361 (2048?) — diagnostics only, but the report prints absolute dBFS.
* `[MEASURE]` HackRF usable-band claim of 12.0 MHz at the canonical rate (filter roll-off), which sets the
  intersection band; if it is narrower, the 10.0 MHz common band shrinks and §1.1 bin range changes.
* `[RESEARCH NEEDED]` DroneRF CSV dtype (real amplitude vs I/Q) before it can rejoin the benchmark.
* Zenodo Fs is now confirmed 120 MS/s (2.44 GHz) / 200 MS/s (5.8 GHz) in the manifest — the older
  "~60 MS/s" inference in the normalisation memo is superseded.

## 7. Files likely affected

`aerix_rf/classify/features_v2.py` (new), `aerix_rf/classify/train/features.py` (kept as `features_v1`,
frozen), `aerix_rf/classify/train/data.py` + `train.py` (emit `model_features_version`),
`aerix_rf/classify/model.py` (F4), `aerix_rf/datasets/tensor.py` (no change expected; `usable_mask` reused),
`bench/receiver_id_probe.py`, `bench/benchmark_features_v2.py` (new), `tests/test_features_v2.py` (new),
`docs/design/dataset-normalization.md` (cross-link tiers).
