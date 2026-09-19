---
name: analog-fpv-58
description: Analog 5.8 GHz FPV detector — the grid/seam/duty-1.0 traps plus the measured carrier-estimation rule (−12 dB edge midpoint, never the spectral peak) and the mid-band vs blanking carrier-convention gap.
metadata:
  type: project
---

Design: `docs/design/analog-fpv-detector.md` (2026-09-19, user approved analog 5.8 detection; video demod approved
for research but is a separate document, brief FLAG-B). Durable facts that are expensive to re-derive:

**Grid membership is weak evidence.** 40 published analog channels (A 5725+20n, B 5733+19n, E discontinuous,
F 5740+20n, R 5658+37n) at ±0.5 MHz tolerance cover ~13 % of 5645-5945 MHz. Per band ~2.7 %; k co-band carriers
≈ 5·(2.7 %)^k. A single on-grid carrier is ~1-in-8 chance. Always emit `grid_false_match_p`. Collisions that must be
reported as sets: 5880 = F8 = R7; 5732 (R3) vs 5733 (B1); HDZero's FCC set **is** Raceband.

**Band A is frequency-identical to 802.11 U-NII-3 centres** (5745/5765/5785/5805/5825/5845/5865). Any A-grid hit
needs dwell confirmation; morphology (BW, duty, `R_shape`) is the only discriminator, never frequency.

**Measured 2026-09-19 in `base_58.npz`** (ANTSDR `RetuneWelchSweep`, 5725-5875 MHz, 1 row, floor −88 dB): a
deterministic +7.0 dB comb in 4-bin groups at every 10 MHz step **seam** (5734.25-5735.75, 5744.25-5745.75, …),
i.e. exactly on the Band A 20 MHz lattice. Baseline differencing cancels it only because it is stationary; a seam
mask (±0.75 MHz of `step_hz` seams) is still required. Not yet checked whether `hackrf_sweep` shows the same comb.

**`detect_bursts` default noise floor (5th percentile per bin over time) is invalid for any duty-1.0 emitter** —
the emitter defines its own floor and nothing gates. Pass an explicit floor from off-carrier bins or the baseline.
Same failure class as `features-and-benchmark.md` §1.7 (G6 collapses above ~70 % occupancy), so G6 spectral-floor
features give only "persistent wideband emitter present" here, never BW/level. See [[decode-snr-bench]] for the
related pattern of a statistic quietly measuring the wrong thing.

**Dwell stage must offset-tune (+3 MHz).** Tuning to f_c puts the DC/LO leakage spur exactly on the FM residual
carrier and corrupts the shape ratio; the offset also brings the +6.0/+6.5 MHz audio subcarriers inside a 12 MHz
usable span. Reuse of `detect/raster.py`'s Rayleigh lattice helpers for the 19/20/37 MHz grids is the intended
path — see [[stage1-link-signatures]].

**Carrier estimation: never the spectral peak for wideband FM video** (measured 2026-09-19, T1 fixtures, 500 kHz
bins). The strongest bins of an FM-video spectrum are wherever the instantaneous frequency *dwells* (blanking line,
sync-tip line, luma-ramp plateau) — an asymmetric, content-dependent structure several bins wide, not a peak.
Peak + parabolic interpolation measured **0.59-0.84 MHz** of centre error against a planted carrier. Fix: carrier =
**midpoint of the −12 dB band edges** of the baseline-differenced, 3-bin-smoothed row, edges refined by *linear*
interpolation in dB (linear is the right sub-bin model on a skirt; parabolic belongs on a peak). The contour level
is itself a measured choice: −6/−10 dB still sits inside the dwell structure (up to +0.76 MHz error, +0.58 MHz on
the real `base_58` ambient), −20 dB runs into the one-sided colour-subcarrier/ramp shoulder (+0.49 to +0.86 MHz),
−12/−15 dB gives ≤0.09 MHz. Achieved −15/+75/−15/−43 kHz on four fixtures. Same edge-midpoint principle as the
DroneID centroid in `detect/bursts.py` — this is now twice-validated across unrelated signal classes.

Two related measurement traps found with it: (a) occupied-bandwidth walks must use **outermost** threshold
crossings — a contiguous walk outward from the peak stops at an FM spectrum's internal notches and understated the
−20 dB width by ~1.6 MHz; (b) one occupied band contains several local maxima, so peaks must be de-duplicated by
their (identical) edge midpoint before cross-sweep clustering.

**Open evidence gap — carrier convention.** The estimator assumes the published channel frequency is the *mid-band*
of the emitted spectrum (what an analog RX's symmetric IF filter implies). If a real VTX instead puts its
blanking/residual-carrier line on the published channel, every estimate is biased **+0.9 MHz** (measured with
`fmvideo_sim(carrier_convention="blanking")`) — larger than τ = 0.5 MHz, i.e. grid matching would break entirely.
RESEARCH NEEDED: a measured spectrum of a real 5.8 GHz analog VTX showing where the published channel sits inside
the occupied band, and at what dB level its ~9 MHz occupied bandwidth is quoted. Related ambiguity: the design
doc's "4-8 MHz p-p" deviation is only self-consistent with the 5-9 MHz (−20 dB) BW window when read as
peak-to-peak (sim default is now 2.7 MHz one-sided); read as one-sided it gives 11.8 MHz and fails the window.
