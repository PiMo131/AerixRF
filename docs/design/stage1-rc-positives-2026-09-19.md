# Stage-1 link-signature rules vs. real RC-transmitter IQ (RFUAV) — 2026-09-19

Author: rf-dsp-specialist. Read-only investigation; **no `aerix_rf/` file was
changed** by this work. All numbers below come from diagnostic scripts run
outside the repo tree plus `bench/out/stage1_rc_positives.json`.

**Evidence level: 2 at best (public-dataset probabilistic morphology).** RFUAV
is a third-party USRP X310 capture (100 MS/s, `IFBandwidth` 100 MHz, centre
2440 MHz, complex float32, `ReferenceSNRLevel 30`), not an AERIX-operated
receiver: different antenna, front end, AGC, and RF environment. Folder names
(`FLYSKY_FS_I6X`, …) are the dataset's own labels and are **not** an identity
claim about any burst measured here; no burst in these captures has been
attributed to a specific transmitter by decode. The captures are *not* clean:
all three inspected slices contain heavy wideband (Wi-Fi-like) occupancy
alongside the narrowband hop traffic, so per-burst attribution from a single
capture is not available at any stage of this note.

## 1. What was tested

`bench/stage1_rc_positives.py` runs the live Stage-1 entry point
(`aerix_rf.detect.energy.detect` → `dsp.spectrogram.compute` →
`detect.bursts.detect_bursts` → `detect.raster.analyze_raster`) over 31 RFUAV
RC-transmitter models, 428 windows, in two modes: `full_band` (native
100 MS/s, 1024-bin STFT) and `dwell` (re-centred on `argmax` of the mean PSD,
resampled to the 15.36 MS/s canonical rate).

This investigation added four read-only diagnostics on one 1 s slice
(`pack1_0-1s.iq`) of three models with documented rasters
(`FLYSKY_FS_I6X` = AFHDS2A-family, `FRSKY_X9DP2019` = ACCST/ACCESS-family,
`FUTABA_T14SG` = FASST/T-FHSS-family):

* **A — ground truth**: full time coverage, 1024-pt FFT every 1024 samples
  (10.24 µs frames, 97 650 frames/s, no decimation), robust per-bin floor
  (per-bin median + 6 dB), event cap removed.
* **B — bench frames, uncapped**: the same `spectrogram.compute` output the
  live path uses (hop 25 000, 4 000 frames, 250 µs frame pitch), robust
  per-bin floor, event cap removed.
* **C/D — cap sweep on the exact live path**: `energy.detect` unchanged except
  `detect_bursts(max_events=…)` at 64 / 256 / 512 / 1024 / ∞, with the R4
  hopping-gate internals (narrow clusters, repeat clusters, reuse ratio,
  lag-1 autocorrelation) dumped.
* **E — floor sweep**: live scalar `noise_lin` vs per-bin floors.

## 2. Result table

First correction to the premise: **the bench output is not all-zero.** Across
428 windows it emitted 136 level-1 labels — 103 `fixed_channel_burst_candidate`
and 33 `hopping_candidate` — in 28 of 31 models. The ANTSDR ambient control
emitted **zero** of either in 100 windows. What is genuinely zero is the whole
**level-2** set: `fhss_1mhz_grid_candidate`, `fhss_2mhz_grid_candidate`,
`rc_link_family_candidate`, `droneid_cadence_candidate` — 0/428.

| Bench label | full_band | dwell | models with ≥1 | ambient control (100 win) |
|---|---|---|---|---|
| `fhss_1mhz_grid_candidate` | 0 | 0 | 0 | 0 |
| `fhss_2mhz_grid_candidate` | 0 | 0 | 0 | 0 |
| `rc_link_family_candidate` | 0 | 0 | 0 | 0 |
| `droneid_cadence_candidate` | 0 | 0 | 0 | 0 |
| `hopping_candidate` | 17 | 16 | 8 | 0 |
| `fixed_channel_burst_candidate` | 1 | 102 | 22 | 0 |
| tag `INSUFFICIENT_CHANNELS` | — | — | 320/428 windows | 100/100 |
| tag `wifi_like_wideband` | — | — | 409/428 windows | 36/100 |

Diagnostics on the three inspected slices (1 s each, 100 MS/s):

| | FLYSKY_FS_I6X | FRSKY_X9DP2019 | FUTABA_T14SG |
|---|---|---|---|
| A: bursts found (full coverage) | 3 050 | 7 651 | 20 230 |
| A: median burst BW | **308 kHz** | **412 kHz** | **362 kHz** |
| A: median burst duration | 10 µs¹ | 31 µs¹ | 20 µs¹ |
| A: clusters / narrow-repeat | 33 / 32 | 16 / 14 | **1** / 1 |
| A: widest single cluster span | 14.3 MHz | 67.4 MHz | **99.4 MHz** |
| B: bursts (bench frames, uncapped, robust floor) | 443 | 542 | 3 110 |
| B: median BW / clusters / narrow-repeat | 591 kHz / 73 / 36 | 295 kHz / 75 / 48 | 327 kHz / 19 / 16 |
| B: best raster R (any Δ) | 0.31 | 0.27 | 0.61 |
| **Live path** (scalar floor), cap 64 | 64 ev, t-span **3.7 ms**, BW_med **5.7 MHz**, 2 repeat | 64 ev, t-span **5.7 ms**, BW_med **4.9 MHz**, 2 repeat | 64 ev, t-span **5.7 ms**, BW_med **18.8 MHz**, 1 repeat |
| Live path, cap 256 | `hopping_candidate` (9 repeat) | `hopping_candidate` (6 repeat) | `hopping_candidate` (7 repeat) |
| Live path, cap 1024 | none (3 repeat) | `hopping_candidate` (5 repeat) | none (3 repeat) |
| Live path, uncapped (9.1–9.7 k events) | none, **1 cluster** | none, 4 clusters | none, 4 clusters |
| Period test, every cap | t̂ = **1.000 s**, R = 1.00, passed | same | same |

¹ duration at 10.24 µs frame granularity is a lower bound (a 1-frame event).
Burst *bandwidth* is the reliable ground-truth number here: 300–410 kHz median,
i.e. narrowband RC-style channels, ~1/3 of an FFT bin-pair at 97.7 kHz bins.

## 3. Root cause

Not one cause. Five independent defects, in order of decisiveness:

**C1 — `period_test` returns the window length, always (decisive for
`rc_link_family_candidate`).** Every single record, real or ambient, reports
`t_hat_s = 1.0` with `R = 1.0` and `passed = True`. Mechanism: bursts that are
simultaneous in time but separated in frequency produce **dt = 0** intervals in
the pooled, time-sorted event list. A set of identical values has Rayleigh
R = 1 at *every* trial period, so `passing` contains the whole grid, and the
"report the largest passing candidate" alias rule
(`aerix_rf/detect/raster.py`, `period_test`) picks the top of
`FREE_PERIOD_RANGE_S` = 1.0 s. `rc_link_family_candidate` requires
`1e-3 <= t_hat_s <= 20e-3`, so it **cannot fire, by construction, in any window
containing co-temporal bursts** — which is every real 2.4 GHz window. This is
not tuning; it is a degenerate-input hole in the statistic.

**C2 — `_MAX_EVENTS = 64` truncates the analysis to the first ~0.5 % of the
window.** The 64 events returned span 3.7 / 5.7 / 5.7 ms of a 1 000 ms window,
because `scipy.ndimage.label` numbers components in raster (time-major) order
and `_channelise` stops at the cap. Hop-set coverage and revisit counts are
therefore measured over ~5 ms — at a 3.85 ms packet period that is 1–2 packets.
Raising the cap to 256 flips **all three** models to `hopping_candidate`
(6–9 narrow repeat clusters, reuse ratio 5.8–9.2, |lag-1| ≤ 0.10).

**C3 — `cluster_centres` is single-linkage with no maximum cluster width, so it
chains at high event density.** The merge threshold is
`max(100 kHz, 0.75 · max(BW_i, BW_j))`. Once the event list is dense, each
neighbouring pair is within that threshold and the chain runs across the whole
band: FUTABA variant A collapses 20 143 events into **one cluster spanning
99.4 MHz**; the live path uncapped collapses FLYSKY to 1 cluster. This is why
the cap sweep is non-monotonic (256 works, 1024 and ∞ fail) — more events make
clustering *worse*. Any fix to C2 without a fix to C3 will regress again.

**C4 — the gate/hysteresis pair is set against a single-look periodogram.**
`spectrogram.compute` takes one 1024-pt FFT per hop with no averaging, so each
noise bin is exponentially distributed (100 % relative std). The hold gate is
floor + 3 dB: with the floor at the per-bin median, P(noise pixel holds) = 25 %,
and 4-connected labelling percolates across the band. That is exactly what the
live scalar floor produces: median burst bandwidth **5.7 / 4.9 / 18.8 MHz**
against a ground truth of **0.31 / 0.41 / 0.36 MHz** — a 15–50× overestimate,
which then feeds C3's bandwidth-scaled merge threshold (0.75 × 5 MHz ≈ 4 MHz)
and guarantees chaining. Moving the floor to per-bin median + 6 dB (arm at
+12 dB, hold at +9 dB over the median; P(noise holds) ≈ 4e-4) restores
295–591 kHz bandwidths and 19–75 clusters on the *same* frames. The live
scalar `noise_lin` is also a poor estimator over a 100 MHz span (per-bin median
varies p10→p90 by 6–7 dB across the band).

**C5 — the level-2 grid test is resolution-starved in `full_band` mode, even
when everything above is fixed.** The Rayleigh lattice test needs
R ≥ 0.93; for centre jitter σ_f, R ≈ exp(−2π²σ_f²/Δ²), so at Δ = 1 MHz the
**total** centre-error budget is σ_f ≤ 59 kHz. At 100 MS/s with 1024 bins the
bin pitch alone is 97.7 kHz (quantisation σ ≈ 28 kHz before any estimator
error), and the −6 dB edge-midpoint walk on a 300 kHz burst spans only ~3 bins.
Best observed raster R with clean clusters was 0.27–0.61 — consistent with
σ_f ≈ 150–250 kHz, i.e. estimator-limited, not "no grid present". The canonical
15.36 MS/s dwell (15 kHz bins at 1024) is *not* affected; this is a
wideband-mode limit. A 1 MHz-grid claim from a 100 MS/s / 1024-bin STFT should
not be attempted; ≥4096 bins (24 kHz) is the minimum for that mode.

**C6 (bench-only, not a rule defect) — the dwell emulation tunes to the wrong
place.** `_process_one_iq` re-centres on `argmax` of the mean PSD; for both
FLYSKY and FRSKY that was **2390.0 MHz**, the extreme lower band edge (a
band-edge/roll-off artefact). The `dwell` column therefore mostly measures a
band edge, not the link; its 102 `fixed_channel_burst_candidate` hits should be
read accordingly. Same weakness already recorded for the decode-SNR bench.

**Is it a data problem?** No. The RC uplinks are present and measurable: 3 050 /
7 651 / 20 230 narrowband bursts per second, median bandwidth 0.31–0.41 MHz,
spread over the full 2390–2490 MHz span with 16–75 distinct channel clusters
recoverable at 250 µs frame pitch. Neither "TX idle" nor "hop set too wide for
1 s" is supported. What the data *do* show is that the captures are crowded, so
a stage-1 morphology label here is a statement about channel-use pattern only.

## 4. Fix / recommendation

Minimal, bounded, in priority order. **Not implemented here** — builder work,
each item needs the ambient FA budget re-run (`bench/stage1_fa_budget.py`;
hopping FA must stay ≤ ~1 % on the ANTSDR ambient corpus, currently 0/100).

1. **`period_test` (raster.py): reject degenerate intervals.** Drop `dt` below
   one frame period (or below a configurable `PERIOD_MIN_DT_S`) before the
   Rayleigh scan, and require the winning candidate to have at least
   `N_MIN_PERIOD` *surviving* intervals; additionally refuse any candidate
   within a few percent of the search-range top (an un-identifiable period).
   Acceptance: on ambient windows `t_hat_s` must stop being 1.0 s; on the three
   RFUAV slices the pooled dt histogram should be re-examined *after* the fix
   before any claim about 3.85/9 ms is made.
2. **Event budget (bursts.py `_MAX_EVENTS`): make it uniform in time, not
   first-64.** Either raise the cap and select the strongest N events, or
   stratify: keep the cap but allocate it across equal time strata of the
   window. 256 is the empirically working point here; the cost of 256 events is
   dominated by the per-event profile slice, not the labelling. Keep it
   configurable per mode (wideband scan vs canonical dwell).
3. **`cluster_centres`: bound the cluster width.** Cap the merge threshold at
   an absolute maximum (e.g. `min(0.75·BW, CLUSTER_MAX_MERGE_HZ ≈ 1 MHz)`) and
   refuse to grow a cluster beyond a maximum span (e.g. 2 × its own BW). This
   is what stops the 99.4 MHz single cluster and makes the cap change safe.
4. **Per-bin noise floor into `detect_bursts`.** `detect_bursts` already accepts
   an array; `energy.detect` passes a scalar. Pass a per-bin robust floor and
   re-derive the arm/hold offsets for a single-look periodogram (or average
   L ≥ 4 FFTs per detector frame in `spectrogram.compute`, which is the
   cleaner fix: it both restores the design's "200 µs frame" semantics and
   tightens the noise distribution by 10·log10(L)/√L).
5. **Bin-width guard for the grid test.** Refuse/flag level-2 grid labels when
   `bin_hz > Δ/20` (≈ 50 kHz at Δ = 1 MHz), and scale `fft_size` with sample
   rate in wideband modes. This keeps `full_band` honest instead of silently
   failing R ≥ 0.93.
6. **Bench-only: replace `argmax(mean PSD)` dwell centring** with the ranked
   centre-hypothesis scorer already used elsewhere, or at minimum exclude the
   outer 10 % of the band.

Sequencing note: 1 and 3 are safe in isolation; 2 must land **after** 3, and 4
changes every threshold downstream, so it needs the full FA re-run plus the
synthetic Stage-1 fixtures.

## 5. Evidence discipline

* `hopping_candidate` / `fixed_channel_burst_candidate` are level 1
  (channel-use morphology). 33 + 103 of them on RFUAV vs 0 on ambient is
  suggestive but is **not** evidence that the labelled bursts came from the RC
  transmitter named in the folder: the same captures carry wideband Wi-Fi-like
  occupancy in 409/428 windows.
* No level-2, -3, -4 evidence exists for these captures. Nothing here supports
  a family claim, and no vendor token was emitted (`consistent_with` empty
  throughout).
* The receiver differs from ours; thresholds validated here must be re-checked
  on ANTSDR/HackRF captures before being treated as operating points.

## 6. Next steps

1. Builder task for fixes 1 + 3 (bounded, testable against existing raster unit
   fixtures), then re-run `bench/stage1_fa_budget.py` and
   `bench/stage1_rc_positives.py`.
2. Then fix 2, re-run both; expect `hopping_candidate` on most RC models and a
   *measured* ambient FA number (must stay ≤ ~1 %).
3. Then decide on fix 4 (frame averaging in `spectrogram.compute`) as its own
   change with its own review — it moves the detector's operating point
   everywhere, including decode gating.
4. Separately: record the pooled inter-burst dt histogram per model after fix 1
   and compare with the brief's primary period table. Only then is a statement
   about 3.85 ms / 9 ms cadence in these captures defensible.
5. Open gap: we have no capture where the RC uplink is the *only* emitter, so
   per-burst attribution remains unavailable. An operator-supplied bench
   capture (one bound TX, quiet band, ANTSDR) would convert several of these
   level-1 observations into level-5 test truth.

## 7. Implementation notes (2026-09-19)

**C1 (`period_test`, `aerix_rf/detect/raster.py`).** Rewritten to estimate
the fundamental period FIRST, directly from the data
(`t_hat_0 = median(dt)`), and gate pass/fail on the Rayleigh statistic AT
THAT ESTIMATE, replacing the old "largest passing dictionary/free-search
candidate" rule (unsound for any sufficiently regular `dt` set: a single
repeated interval concentrates R ≈ 1 at *every* trial period, so "largest
passing" silently picked the largest alias). Three guards were added on top:
* a sub-frame `dt`-filter drops degenerate near-zero intervals (co-temporal
  bursts at different centres, adjacent in the pooled time-sorted list)
  below one detector frame period (`frame_dt_s`, or the minimum observed
  event duration if `frame_dt_s` is unknown) before the Rayleigh scan;
* a winning candidate at/near the TOP of the free-search range
  (`FREE_PERIOD_RANGE_S`) is rejected (`source="range_top_rejected"`) rather
  than reported, since the Rayleigh statistic trivially rises as the trial
  period approaches the range top regardless of real periodicity;
* `frame_pitch_too_coarse` guard (independent-review finding #3): if
  `frame_dt_s` exceeds `FRAME_PITCH_MAX_FRAC_OF_MIN_PERIOD` (0.5) of the
  smallest modelled ExpressLRS period (1 ms), the dt-filter's own
  quantisation is no longer fine enough to trust — it can erase a
  genuinely fast, regular train wholesale (every true inter-arrival falls
  below the filter floor) rather than only removing artefacts. Any result
  computed under this condition is now reported as `passed=False`,
  `source="frame_pitch_too_coarse"` on every return path, instead of at
  face value.

**C2 (`aerix_rf/detect/bursts.py`).** Capped burst extraction at the
strongest 256 candidate events per window (peak-power ranked) and replaced a
full-array `scipy.ndimage` statistics pass with a foreground-only gather
(compute per-event stats only over each event's own bounding pixels, not the
whole frame × bin array). Measured on the existing
`test_timing_bound_1s_window_at_12_288_msps` fixture: median wall time
78.7 ms → 40.3 ms (7-repeat median, warm-up call excluded). Note for the
independent reviewer: this timing test is environment-noise-sensitive (it
passed in 3/3 isolated re-runs during this session but flaked once — 56.08 ms
vs the 50 ms budget — under full-suite/parallel load); the regression itself
(pre-fix baseline) is not in dispute, only the CI margin on a shared box.

**C3 (`cluster_centres`, `aerix_rf/detect/raster.py`).** Two independent
bounds on top of the existing bandwidth-scaled single-linkage merge rule:
a total-span bound (`CLUSTER_MAX_SPAN_HZ`, a cluster may not grow past this
centre-to-centre span from its first member regardless of how many
consecutive pairwise gaps stay under threshold — this is what stops
unbounded chaining at high event density; a 20 143-event real capture had
collapsed into one 99.4 MHz-wide cluster), and a per-pair merge-threshold
cap scaled to `HOP_MAX_CLUSTER_BW_HZ` rather than a flat 1 MHz
(`CLUSTER_MAX_MERGE_HZ` alone, independent-review finding #1: a flat 1 MHz
cap overrode the bandwidth-scaled floor for any occupant wider than
~1.33 MHz, splitting one genuine wideband burst's sparse -6 dB edge
estimates — e.g. a 2.4 MHz emitter sampled near its edges, gap ~1.1–2.2 MHz
— into a spurious multi-cluster "hop set"). The cap is now
`max(CLUSTER_MAX_MERGE_HZ, bw_separation_frac * HOP_MAX_CLUSTER_BW_HZ)`, the
widest occupant this module still treats as a single hop channel, so a real
single-emitter's edge jitter no longer exceeds the merge threshold while the
span bound remains the only defence against unbounded chaining. Regression
test: `test_c3_sparse_wideband_burst_stays_one_cluster` (3 events, 2.4 MHz
bandwidth, ~1.1 MHz apart → 1 cluster); the existing dense 60 MHz/1 MHz-grid
fixture (`test_c3_cluster_centres_bounds_span_at_high_event_density`, 300
events) still resolves to ≥ 55 clusters, confirming the span bound alone
(not the merge-cap widening) is what prevents high-density chaining.

**`frame_dt_s` wiring.** Forwarded end-to-end: `energy.detect()` now carries
`frame_dt_s` on its `Detection`; `pipeline.SessionCadenceStore.add()` takes
an optional `frame_dt_s` per window and tracks the MAX over all contributing
windows (a session normally shares one frame pitch, and the dt-filter only
needs a single conservative floor — not a per-event lookup); `result()`
forwards that stored max into `analyze_raster()`; `bench/stage1_rc_positives.py`
forwards its detector's frame pitch the same way. Independent-review finding
#2a: before this fix, `SessionCadenceStore` never forwarded `frame_dt_s`, so
the C1 sub-frame dt-filter was silently inactive for session-level (pooled,
multi-window) evidence even though it was active for single-window
`analyze_raster()` calls — co-temporal trains pooled *across* windows could
alias the same way the single-window path did pre-C1. Regression tests:
`tests/test_pipeline_cadence_store.py` —
`test_session_cadence_store_cotemporal_pairs_across_windows_not_periodic`
(co-temporal pairs split across two `add()` calls, `frame_dt_s=250e-6` →
`period.passed is False`) and
`test_session_cadence_store_pools_genuine_640ms_cadence_across_windows`
(genuine ~640 ms cadence sampled 4 events/window over 4 windows → pooled
`period.t_hat_s` within 5 % of 0.640 s, `passed is True`).

**Independent review outcomes recorded.** Harmonic-alias probe: a
genuinely 4 ms-periodic train no longer aliases to a harmonic — reported
4 ms in, 4 ms out (`test_c1_genuine_8ms_period_detected` and the new
`test_period_test_frame_pitch_too_coarse` fine-pitch branch both confirm the
estimator recovers the true fundamental, not a multiple). A Poisson
(non-periodic, memoryless-arrival) null was probed and correctly rejected
(no spurious pass). The estimator was also checked for permutation
invariance of the input event ordering (pooling/sorting is by `t_start`
inside `period_test`, so caller-supplied event order does not change the
result).

**DECISION: `R_MIN_PERIOD = 0.93` kept.** Measured RC/ELRS/DroneID-class
link timing shows ≈5–6 % interval jitter around the nominal period; these
links are crystal-timed (drift ≪ 1 %) and the dominant jitter source is
frame-pitch quantisation of the observation itself, not the link. Modelled
as `σ ≈ 0.29 · frame_dt_s` (uniform-quantisation-noise approximation): an
83 µs pitch bucket on a 1 ms detector frame gives `R ≈ 0.99`, comfortably
inside the 0.93 gate. The originally-considered 10 % jitter case is not a
target link class for this gate (it would represent either a genuinely
noisier/non-crystal timing source or a much coarser frame pitch than any
current backend uses) and was not used to set the threshold.

**FA budget after fix:** TODO — architect to fill from the running
`bench/stage1_fa_budget.py` re-run.

**RC positives after fix:** TODO — architect to fill from the running
`bench/stage1_rc_positives.py` re-run.

### FA budget after fix (ambient corpus, 6 sessions / 1160 windows, 2026-09-19 13:12)

`| TOTAL | 1160 | 0 | 0 | 0 | 11 | 205 | 0 | 6 | 0 | 1160 | 0 |`

- **hopping_candidate <= 5% of windows**: PASS -- 11/1160 = 0.95% — before the fix: 12/1160 = 1.03 %. Level-2 labels (grid / rc_link_family / droneid_cadence) remain 0 on
ambient. INSUFFICIENT_CHANNELS still 1160/1160: the grid test is still not *exercised* by ambient RF — only
the RC-positives bench exercises it. Timing test (`test_timing_bound_1s_window_at_12_288_msps`, 50 ms budget)
flakes at 52–56 ms only while two benches and the RFUAV prepare share the CPU; 40 ms median when idle.

### RC positives after C1–C3 (bench rerun, fixed harness, 2026-09-19 ~13:40)

Same 31 RFUAV RC transmitters, 428 windows (dwell + full_band per slice), ANTSDR ambient control 100 windows.

| metric | before (v1) | after C1–C3 (v2) |
|---|---|---|
| models with ≥1 level-1 label | 27/31 | **30/31** |
| `hopping_candidate` windows | 33 | **191** (dwell 46, full_band 145) |
| `fixed_channel_burst_candidate` | 103 (102 were band-edge dwells, C6) | 1 |
| `period.passed` | 375 (degenerate dt=0 / range-top) | 12 (all `free_search`) |
| level-2: `fhss_1mhz_grid_candidate` / `rc_link_family_candidate` | 0 / 0 | **1 / 2** (2 models) |
| `INSUFFICIENT_CHANNELS` tags | 320 | 246 |
| ambient control positives | 0/100 | 0/100 (`wifi_like_wideband` 40) |

Reading: the degenerate period passes are gone (375 → 12) and the hopping rule now fires on most transmitters
while the ambient control stays at zero. Level-2 remains almost closed — as diagnosed, bandwidth is still
over-estimated by the single-look scalar floor (C4) and the 100 MS/s column is resolution-limited (C5); those are
specified in `stage1-c4-c5-spec.md`. Evidence: level 1–2, third-party X310 capture, crowded band; no burst is
attributed to any named transmitter.
