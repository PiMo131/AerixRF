---
name: analog-fpv-58
description: Analog 5.8 GHz FPV detector design — the three measured/derived traps (10 MHz sweep-seam comb on the Band A lattice, Band A == 802.11 U-NII-3 centres, 13 % grid false-match) and the duty-1.0 noise-floor trap.
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
