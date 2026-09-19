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
4. **Carrier estimate**: 3-point parabolic interpolation in dB on the 500 kHz grid. Budget **±250 kHz worst case,
   ±100 kHz target** — the FM-video peak is not parabolic, so the bias must be *measured* (§8) before quoting tighter.
5. **Occupied BW**: −20 dB width about the peak in absolute power-over-floor, valid only when `peak_over_floor ≥
   25 dB`, else the −10 dB width. Accept 5-9 MHz (−20 dB) / 3-7 MHz (−10 dB).
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
