---
name: features-v2-benchmark
description: Stage-2 features_v2 design (absolute-Hz 10 MHz common band, 292-D) and the first cross-receiver benchmark's honest limits, decided 2026-09-18
metadata:
  type: project
---

Memo: `docs/design/features-and-benchmark.md` (196 lines). Builds on [[canonical-representation]] and
[[dataset-normalization]].

**Fact / decision.** `features_v2` = 292-D fixed vector over the canonical `[n_ms x 1024]` dBFS tensor:
G1 sub-band levels 192, G2 band scalars 8, G3 occupancy/cadence 12, G4 bandwidth/shape 10, G5
time-frequency dynamics 70. Axis is **absolute Hz** on the HackRF n ANTSDR common band = **10.0 MHz**,
i.e. fftshifted bins **k in [179, 845] = 667 bins, +-4.995 MHz** at 15.36 MS/s / FFT 1024 (verified
arithmetic); DC notch k in [510, 514] interpolated. `features.py` v1 (fraction-of-band) is frozen.

**Why (hard to re-derive):**
- The device-independence lever is a **per-bin** 10th-percentile noise floor, not the scalar floor v1 uses:
  per-bin subtraction removes analog filter shape, passband tilt, gain *and* static CW interferers with no
  calibration file. Absolute `nf0` is the strongest receiver fingerprint and is excluded from the vector.
- Record length is a leakage trap: RUB fragments are 4.5/14.55 ms, so cadence/duty features are undefined
  there. Zero-filling them would make "fragment" == "drone". Hence the `feature_valid_mask` and the
  `n_ms >= 100` gate on G3/G5-dynamics, and the rule that duration is never a feature.
- The receiver-ID probe must be run **label-matched** (background-only today). The unrestricted probe over
  `dataset_id` is an upper bound only, because dataset is confounded with emitter content (Zenodo = drones
  in an anechoic chamber, ANTSDR = Wi-Fi ambient). Pass threshold: label-matched balanced accuracy
  <= chance + 0.10; > chance + 0.25 blocks every cross-receiver claim.
- **We have no ANTSDR-captured drone positives.** The first benchmark therefore measures false-alarm
  behaviour on real ANTSDR ambient (Tier D, PFA/FA-per-hour only) plus recall on public anechoic positives
  (Tiers A/B). It is not a PD number. Tier C is blocked: the HackRF 2026-09-04 sessions are not on this
  machine. Zenodo's empty slices are not a background class.
- Metrics use group bootstrap (resample groups, not windows); with ~10 Zenodo positive groups the CIs are
  wide and that is the honest answer.

**How to apply:** treat as the reference for any Stage-2 feature/benchmark question. Re-check the
`[MEASURE]` items before depending on them (ANTSDR ambient session path was NOT findable on this host on
2026-09-18; HackRF 12.0 MHz usable-band claim unverified — if narrower, the 10 MHz band and the [179, 845]
bin range both change). Zenodo Fs is confirmed 120 MS/s @2.44 GHz / 200 MS/s @5.8 GHz, superseding the
"~60 MS/s" inference in [[dataset-normalization]].

**F1 implementation review (2026-09-18), durable DSP decisions** -- memo S1.6:
- Two floors, orthogonal: the **temporal** per-bin 10th-percentile `nf_k` is blind to duty > 0.9 (a 6 MHz
  continuous +25 dB emitter measured `occ6 = 0.000`); a **window-internal spectral** floor (deg-2 polyfit
  over the quietest 30 % of in-band bins, one refit at residual <= +3 dB) recovers it and is gain- and
  tilt-invariant. Adopted as new group **G6 (10 dims, 292 -> 302)**. No cross-window floor state in the
  vector -- that would break live == replay; `nf0` history stays sidecar-only.
  Hard limit: above ~70 % band occupancy both floors degrade, so a centred continuous 20 MHz Wi-Fi channel
  is unrecoverable in a 10 MHz dwell. That is a scan-placement problem.
- **A time-*median* PSD is the wrong shape reference**: it is blind to duty < 0.5, i.e. to every burst
  emitter we target. Use `percentile(R, 99, axis=0)`.
- **argmax-over-667-bins features are degenerate** (hop rate ~1.0 for noise, continuous emitter and burst
  alike). Any argmax/hop statistic must be taken over sub-band means and gated on band-max >= +6 dB.
- **Receiver-ID leak measured**: spectral flux and high-percentile spreads scale linearly with the per-bin
  noise dB sigma (flux_p50 150/226/451/754 at sigma 0.2/0.3/0.6/1.0 dB), so they read out ADC bit-depth and
  decimation-induced bin correlation. First ablation targets; self-normalise against the quietest sub-bands.
- Threshold references must be computed **within the same statistic domain** they are applied to (G3's
  floor came from the 30-average tensor but was applied to 6-average detector frames).
