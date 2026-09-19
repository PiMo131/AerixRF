# Analog 5.8 GHz FPV video-carrier detector (design)

Owner: `rf-dsp-specialist`, 2026-09-19. Scope: **detection only** of a continuous analog FM video carrier and its
position on a published channel grid. Content demod is approved for research but is a different document and a
different legal posture (brief FLAG-B) — out of scope here. Passive receive only.

## 1. Conclusion
A sweep-level persistence + grid-lattice detector is buildable now on existing infrastructure, but **grid membership
is weak evidence on its own**: 40 published channels at ±0.5 MHz cover ~13 % of 5645-5945 MHz, so a random carrier is
on-grid ~1 time in 8. Two measured facts make it worse and dominate the design: (a) Band A (5725+20n) is
**frequency-identical to 802.11 U-NII-3 centres** 5745/5765/…/5865; (b) our own ANTSDR sweep of the 5.8 band contains
a **deterministic +7 dB comb at 10 MHz spacing** (the `RetuneWelchSweep` step seams) that lands on the Band A lattice.
Level-2 promotion therefore needs morphology (occupied BW, duty ≈ 1, FM shape) **plus** either multiple co-band
carriers or a dwell confirmation — never grid position alone.

## 2. Assumptions and signal model
Emitter: 25-800 mW analog VTX (RTC6705-class), fixed channel, no hopping, continuous while powered. Receiver: HackRF
sweep, or ANTSDR E200 retune sweep (10 MHz usable/step) and dwell at 12.288/15.36 MS/s (≤12 MHz usable). A stored
`scan.sweep.Baseline` for the same band/gains exists. VTX centre accuracy is **unmeasured** (§11); the ±0.5 MHz grid
tolerance τ is a placeholder budget.
Pre-emphasised composite CVBS (PAL 625/50 or NTSC 525/60) FM-modulated onto the carrier, peak deviation ~4-8 MHz
p-p. Baseband: luma 0-5 MHz, colour subcarrier 4.4336 (PAL) / 3.5795 MHz (NTSC), line 15.625/15.734 kHz, field
50/60 Hz; audio on an FM subcarrier at +6.0 and/or +6.5 MHz. Consequences used below: **occupied BW** ≈ 5-9 MHz at
−20 dB (Carson, B ≈ 2(Δf + f_m)), narrower than any Wi-Fi/OFDM video link; a **residual carrier** (sync-tip dwell)
makes the PSD peaked, not flat-topped; **duty ≈ 1.0**, no packet structure or cadence. Line/field periodicity is
recoverable only after FM demod — out of scope.

## 3. Stage A — sweep-level candidate (level 1)
Input: `(freqs_mhz, power_matrix[n_rows, n_bins] dB, Baseline)` from any `SweepSource` over **5645-5945 MHz**
(config option to extend to 5325-5620 for the rare D/U/O/L bands — a non-compliant DIY build is *more* likely there).
1. **Δ spectrum** per row: `row − baseline.interp(freqs)`; 3-bin smoothing in linear power.
2. **Seam mask**: reject peaks within `±seam_guard_mhz` (0.75) of a sweep-step seam derived from the source's
   `step_hz` and band start. Mandatory for `RetuneWelchSweep` — see the §7 measurement that motivates it.
3. **Peak pick** per row: local maxima with `Δ ≥ peak_delta_db` (start 8) and prominence `≥ 4 dB`.
4. **Carrier estimate** (CORRECTED 2026-09-19 after T1 measurement — supersedes "3-point parabolic interpolation
   on the peak", which was wrong): the carrier is the **midpoint of the −12 dB edges of the occupied band** in the
   baseline-differenced, 3-bin-smoothed row, each edge refined by *linear* interpolation in dB between the last
   in-band and first out-of-band bin. Rationale: wideband FM video is not a peaked spectrum. Its strongest bins are
   wherever the instantaneous frequency *dwells* (blanking line, sync-tip line, luma plateau); that structure is
   several bins wide, asymmetric, and moves with picture content, so a peak-based estimator measured **0.59-0.84 MHz**
   of error against a planted carrier on the 500 kHz grid — 2-3× the ±250 kHz budget. Sub-bin refinement belongs on
   the *edges*, not on the peak (same edge-midpoint principle as the DroneID centroid in `detect/bursts.py`).
   The contour level matters and was measured on four fixtures (three flat-floor, one real `base_58.npz` ambient):
   −6/−10 dB sits *inside* the dwell structure (error up to +0.76 MHz, +0.58 MHz on the real-ambient row); −20 dB runs
   out into the one-sided shoulder of colour-subcarrier/ramp products (+0.49 to +0.86 MHz); −12/−15 dB gives
   **|error| ≤ 0.09 MHz**. Achieved after the fix: **−15 kHz / +75 kHz / −15 kHz / −43 kHz** on those four fixtures,
   i.e. inside the ±100 kHz target. `carrier_edge_drop_db` (12 dB), `edge_margin_db` (4 dB) stay configurable, and
   every record reports which estimator was used (`carrier_estimator`). Caveat: this estimator assumes the published
   channel frequency is the **mid-band** of the emitted spectrum. That is unverified for real hardware (§11): if a
   real VTX instead puts its blanking/residual-carrier line on the published channel, every estimate is biased by
   ≈ +0.9 MHz (measured with `fmvideo_sim(carrier_convention="blanking")`), which would exceed τ = 0.5 MHz and
   break grid matching. **A measured VTX spectrum is required before the ±250 kHz budget can be claimed on-air.**
5. **Occupied BW**: −20 dB width about the peak in absolute power-over-floor, valid only when `peak_over_floor ≥
   25 dB`, else the −10 dB width. Accept 5-9 MHz (−20 dB) / 3-7 MHz (−10 dB). Widths use the same interpolated
   **outermost** crossings — a contiguous walk outwards from the peak stops at the first internal notch of an FM
   spectrum and understated the width by ~1.6 MHz at −20 dB. Measured on `fmvideo_sim` (midband, default deviation
   2.7 MHz one-sided = 5.4 MHz p-p, mid-range of §2's "4-8 MHz p-p"): raw binned profile −20 dB **5.4 MHz**,
   −10 dB **4.5 MHz**; through the detector (smoothed) **5.86-6.30 MHz** / **3.82-5.25 MHz** — inside both windows.
   Reading §2's 4-8 MHz as *one-sided* instead (deviation 4 MHz, 8 MHz p-p) gives 11.8 MHz at −20 dB and falls
   outside the accepted window, so the two readings are not interchangeable; which one a real VTX follows is open.
6. **Persistence**: same centre (±0.75 MHz) in `≥ min_sweeps` (3) consecutive rows — `base_58.npz` has `n_sweeps = 1`
   and so does *not* exercise this test. Output: `analog_video_carrier_candidate` per surviving centre.

## 4. Grid matching and false-match probability (level 2 gate)
Grids (from `research/library/.../channel_plans/CHANNEL_DATABASE.md`, evidence class SUPPORTED, community):
A 5725+20n (descending index), B 5733+19n, E discontinuous (5645-5705 and 5885-5945), F 5740+20n, R 5658+37n.
- Per-band chance coincidence at τ = 0.5 MHz: `p_band ≈ 8·2τ/300 MHz = 2.7 %`; union over 5 bands (Bonferroni) ≈ 13 %.
  For k carriers on the *same* lattice `p ≈ 5·(2.7 %)^k` → k=2: 3.6e-3, k=3: 1.0e-4. **Report it on every hit.**
- Prefer the **lattice test over absolute positions**: reuse `detect/raster.py`'s Rayleigh machinery
  (`_rayleigh_stat`, `_p_false_corrected`) on the centres with `deltas_hz = (19e6, 20e6, 37e6)`; the recovered
  `offset_hz` separates A from F (15 MHz apart mod 20) once ≥2 carriers exist.
- **Band A is down-weighted by default** (`band_a_requires_dwell = True`): it collides with U-NII-3 Wi-Fi centres.
  Ambiguities reported as sets, never resolved: 5880 = F8 = R7; 5732 (R3) vs 5733 (B1).

## 5. Stage B — dwell confirmation (level 2)
Tune and dwell 1 s. **Offset-tune the LO to f_c + 3 MHz**: tuning to f_c would put the DC-LO leakage spur exactly
where the FM residual carrier is and corrupt the shape ratio; the offset also brings the +6.0/+6.5 MHz audio
subcarriers inside a 12 MHz usable span.
1. **Noise floor must be supplied explicitly.** `detect_bursts`' default floor (5th percentile per bin over time) is
   invalid for a duty-1.0 emitter — the emitter defines its own floor and nothing gates. Pass a floor from off-carrier
   bins (|f − f_c| > 6 MHz) or from the 5.8 baseline. Same failure class as `features-and-benchmark.md` §1.7 (G6's
   quietest-30 % reference collapses above ~70 % occupancy), so **G6 spectral-floor features are not used here**.
2. **Continuity**: `detect_bursts` on 200 µs D8 frames, filtered for `duration_s ≥ 0.5`. A true analog carrier yields
   one event spanning the whole dwell with `edge_clipped = True` **in time** — here a positive indicator, the inverse
   of its usual meaning. Also require `frac_time_occupied ≥ 0.98` inside f_c ± 2 MHz.
3. **FM shape ratio** `R_shape = P(|f−f_c| ≤ 1 MHz) / P(|f−f_c| ≤ 4 MHz)`, linear power. Expected FM video 0.4-0.7 (peaked), 20 MHz OFDM ≈ 0.12, 10 MHz OFDM ≈ 0.25; start at `R_shape ≥ 0.35`. **Hypothesis until measured.** Optional strengthener, never required: a persistent < 300 kHz spike at f_c + 6.0 or + 6.5 MHz.

## 6. Output vocabulary
Level 1 `analog_video_carrier_candidate`: `centre_hz`, `bw_20db_hz`, `delta_db`, `n_sweeps_present`, `seam_masked`.
Level 2 `analog_fpv_grid_candidate` adds `grid`, `grid_residual_hz`, `grid_false_match_p`, `r_shape`,
`frac_time_occupied`, and `consistent_with` = *all* colliding labels, e.g. `["F8 5880", "R7 5880"]`. Forbidden: any
brand, any `analog_fpv_detected`, any aircraft-present claim — "consistent with the Raceband lattice" is the
strongest wording this detector can justify.

## 7. Confounders and rejection
| Confounder | Why it fires | Rejection |
|---|---|---|
| 802.11 U-NII-3 (5745-5865) | centres identical to Band A | 20/40/80 MHz BW, duty < 1, beacon cadence (`raster._wifi_beacon_like`), low `R_shape`; Band A always needs dwell |
| DJI O3/O4 video | strong 5.8 emitter | 10/20/40 MHz flat-top OFDM, bursty, off-grid |
| HDZero | FCC channel set **is** Raceband | ~27 MHz, digital burst structure — BW check is the only discriminator; frequency cannot decide |
| Walksnail / OpenHD | 20/40 MHz | BW + duty; OpenHD sits on Wi-Fi channels, off the analog grids |
| TDWR / weather radar (5.6-5.65 GHz) | abuts our lower edge | pulsed, low duty, antenna-rotation amplitude periodicity |
| **Receiver seam comb (measured)** | `base_58.npz` shows +7.0 dB groups at every 10 MHz step seam (5734.25-5735.75, 5744.25-5745.75, … 30 seams), i.e. on the Band A lattice | baseline differencing (comb is stationary) **plus** the §4.2 seam mask; optionally offset the sweep band start so seams fall off-grid |
| LO/DC leakage in the dwell | sits exactly at the tuned centre | offset-tune +3 MHz (§6) |

## 8. Validation
- **Synthetic** (`fmvideo_sim`): PAL/NTSC luma + sync + colour subcarrier + audio subcarrier → FM modulator,
  configurable deviation. Unit tests: occupied BW vs deviation (Carson); `R_shape` separation against a synthetic
  20 MHz OFDM burst train; **carrier-estimation bias swept over sub-bin offsets in 50 kHz steps** — this is what
  turns the ±100 kHz target into a measured number.
- **Replay**: `~/rf-datasets/aerix_antsdr_ambient_2026_09_18/original/sweeps_2026_09_18/base_58.npz` (5725-5875 MHz,
  1 row, floor −88 dB, max −80.9 dB = the seam comb) must yield **0 candidates** — but report that one row cannot
  exercise persistence and self-baselining cancels the comb: necessary, weak. A ≥5-row 5645-5945 MHz ambient baseline is
  needed for a real FA number.
- **Field** (user): HackRF/E200 sweep at an FPV field — several simultaneous R-grid carriers is the k≥3 case where the lattice statistic is decisive. AERIX must not transmit; any bench VTX must be one the user is authorised to operate.

## 9. Builder tasks
- **T1 (`python-builder`)** `aerix_rf/detect/analog_fpv.py`: `find_carriers(freqs_mhz, power_matrix, baseline, *, cfg)`
  → level-1 candidates; `match_grid(centres_hz)` → grid + `grid_false_match_p` (reusing `detect/raster.py`'s Rayleigh
  helpers); seam mask; CLI wiring. **Acceptance**: 0 candidates on `base_58.npz`; a synthetic 6 MHz carrier at 5843 MHz
  over that baseline recovered within ±250 kHz in 3/3 rows; every record carries `grid_false_match_p`; a carrier at
  5845 (Band A) is emitted only as level 1.
- **T2 (`python-builder`)** `aerix_rf/dsp/fmvideo_sim.py` + `confirm_carrier()`. **Acceptance**: injected f_c within
  ±150 kHz at ≥10 dB SNR; `frac_time_occupied ≥ 0.98`; `R_shape` ≥ 2× that of a synthetic 20 MHz OFDM burst set at equal
  total power; a test that fails with the default percentile floor covers the explicit-floor path.
Configurable: band edges, `peak_delta_db`, `seam_guard_mhz`, `min_sweeps`, τ, BW window, `R_shape`, dwell length, LO
offset, `band_a_requires_dwell`.

## 10. Cost and files
Stage A is O(n_bins) per row on a 600-bin grid — negligible next to the sweep itself. On ANTSDR, 300 MHz / 10 MHz =
30 steps × 2 dwells per row, so ≥3 rows costs tens of seconds; `hackrf_sweep` is far cheaper. Stage B is one 1 s
dwell plus one `detect_bursts` call (<50 ms/dwell, already measured). New: `aerix_rf/detect/analog_fpv.py`,
`aerix_rf/dsp/fmvideo_sim.py`, `tests/test_analog_fpv.py`, `tests/test_fmvideo_sim.py`; edited: `aerix_rf/cli.py`;
read-only: `scan/sweep.py`, `scan/candidates.py`, `detect/bursts.py`, `detect/raster.py`, `sdr/sweep.py`.

## 11. Open evidence gaps
- `RESEARCH NEEDED:` RTC6705/VTX centre-frequency accuracy and temperature drift (sets τ; currently a guess), and
  measured occupied BW / deviation for common VTX at 25 and 600 mW (every BW number here is Carson + community tables).
- `RESEARCH NEEDED:` does `research/library/fpv/AERIX_FPV/analog_video/sample_IQ/NOTES.md` resolve to a real downloadable IQ capture or only a recipe? Public analog 5.8 IQ would remove the field-session dependency for T1/T2.
- Unmeasured: whether the 10 MHz seam comb is specific to `RetuneWelchSweep` or also appears in `hackrf_sweep` for this band (HackRF tiles differently) — check before trusting the seam mask. `R_shape`/duty thresholds are hypotheses; no analog FPV signal has ever been observed by this project.

## Research findings 2026-09-19

- **RTC6705 ppm/PLL step (τ):** no datasheet-level crystal ppm or PLL step size found, local
  or web (datasheet PDF exists at richwave.com.tw/wildlab mirror but was not fetched this
  pass). Local corpus (CSDN, grade PLASUIBLE/single-source, no instrument named) gives phase
  noise (-90 dBc/Hz@100kHz, -115@1MHz) and power (+13/+2 dBm) but not frequency accuracy.
  **Best available proxy, COMMUNITY grade, wrong chip family:** `ExpressLRS_rf_performance_measured`
  (SX1280, not RTC6705) measured **±10 kHz at 25°C, 35–80 kHz drift across 10→50°C** between
  two modules — order-of-magnitude only, not a substitute for RTC6705 data. Recommend τ stay
  a conservative guess (current ±0.5 MHz is generous relative to this proxy) until an RTC6705
  datasheet or bench measurement is obtained. **Action for RF-DSP:** fetch the RTC6705-DST-001
  datasheet (PDF found at wildlab.org/wp-content/uploads/2015/07/RTC6705-DST-001.pdf) directly
  if τ needs tightening — not read this pass, budget-limited.
- **Occupied BW / deviation vs power:** no 25 mW vs 600 mW comparative measurement found,
  local or web. Local corpus has one independent SDR measurement (batchdrake/RTL-SDR.com,
  VERIFIED_PRIMARY for method, PLASUIBLE for generality): **~9 MHz occupied FM bandwidth**
  for one low-power analog camera, vs the **30 MHz community channel-plan spacing** (Oscar
  Liang, SUPPORTED/vendor-repeated, not independently measured) — these are different
  quantities (occupancy vs raster spacing), not a power-dependent pair. No shape-ratio data
  found either. Existing design guidance ("detect on measured occupancy, map to raster after")
  stands; the 25↔600 mW BW-vs-power question is still open.
- **Sample IQ NOTES.md:** confirmed recipe-only, no capture (already stated in that file).
  **However, a real, openly-licensed capture exists and was NOT previously known to this
  corpus:** Zenodo record 19870020, "FPV Analogue Video IQ Dataset" (pub. 2026-04-30, CC-BY-4.0),
  HackRF One captures of active analog-VTX sweeps plus no-TX ground truth, with per-sweep
  metadata (drone_freq, vtx_power_mw, distance_m, environment, hackrf_lna/vga, sample_rate=20
  Msps) in `iq_recording_meta.csv`. Full dataset is 4.2 TB across 10 chunk zips (0.99–3.4 GB
  each); only `chunk10.zip` (994.8 MB, smallest) was downloaded this pass, to
  `~/rf-datasets/analog_fpv_public/original/` (manifest at
  `~/rf-datasets/analog_fpv_public/manifest.md`) — download was still in progress at
  handback (aria2c preallocates file size, so `ls -la` size is not a completion signal; check
  `chunk10_aria2.log`). The `vtx_power_mw` column means this dataset can also answer the
  25/600 mW BW question above once unzipped and cross-referenced, without a field session.
  **Grade: COMMUNITY/self-published, CC-BY-4.0, not yet verified by this project as decodable.**
  Second dataset found (Zenodo 4264467, "RF Control and Video Signal Recordings of Drones",
  CC-BY-4.0, 8.6 GB) includes 5.8 GHz video from DJI/Yuneec models at 200 Msps but is
  digital-link video, not analog FM — not relevant to this detector.

## Real-data check (Zenodo 19870020 chunk10, 2026-09-19)

Three 32.8 ms dwells of a real 25 mW analog VTX at the published 1240 MHz (HackRF, 20 MS/s; `bench/analog_fpv_public_check.py`):
- Spectral peak +620…+627 kHz above the published frequency; per-row −12 dB edge-midpoint carrier estimates
  1239.18 / 1239.18 / 1240.32 MHz (1.14 MHz spread, picture-content dependent). ⇒ treat the published channel as
  band centre ±1 MHz: `GRID_TOL_MHZ_DEFAULT = 1.0`, `DEFAULT_PERSIST_TOL_MHZ = 1.5` (adjacent channels are
  ≥19 MHz apart, so no ambiguity). Supersedes the 0.25/0.5/0.75 MHz placeholders.
- −6 dB bandwidth 2.8–5.1 MHz; `dwell_confirm` shape ratio 0.50–0.55; audio subcarrier detected at +6.0 MHz;
  continuity: two rows at 1.00, one at 0.9945 — the criterion is now `frac_time_occupied ≥ 0.98`.
- Sweep level: a self-baseline (median of rows that all contain the emitter) cancels an always-present carrier
  → 0 candidates — baselines must be recorded WITHOUT the emitter; with a median-filter spectral floor the carrier
  is found at 1239.56 MHz (`analog_video_carrier_candidate`). 5645–5945 MHz negative control: 0 candidates.
Evidence: level 2 for FM-video shape/continuity on 1.2 GHz analog video from one dataset; the 5.8 GHz grid match is
still unvalidated on air (needs another Zenodo chunk or a field sweep). Test count: 14.
