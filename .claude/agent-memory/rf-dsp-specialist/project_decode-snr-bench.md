---
name: decode-snr-bench
description: How to read bench/canonical_rate_sweep.py results — the non-monotonic decode curve, why snr50_final_db is the only trustworthy metric, and the candidate-screening blocker weakness
metadata:
  type: project
---

`bench/canonical_rate_sweep.py` (synthetic DroneID decode-vs-SNR sweep) has one trap that will mislead
anyone reading its output cold.

**The P(decode) vs SNR curve is not monotonic.** Measured 2026-09-18 at n=200/point: ~0.5 plateau at
2–6 dB, dip to ~0.2 at 7–7.5 dB, true knee at 8–10 dB → 1.0. So the original `snr50_db` (first upward
crossing of 0.5) reports the *plateau*, not the operating threshold. It scatters ≥0.5 dB between
identical runs and produced two physically impossible results: "cs12 0.73 dB worse than cs8" and
"13.44 MS/s worse than 11.52". Use **`snr50_final_db`** (SNR above which success stays ≥0.5, added
2026-09-18) — reproduces to ~0.05 dB. Validated numbers (SNR50-final): 20 MS/s 9.3 · 15.36 8.6 ·
13.44 8.2 · 12.288 8.0 · 11.52 7.6 · cs8 8.5 · cs12 8.5.

**Two durable findings:**
- Required SNR *falls* as the capture window narrows (less out-of-band noise into the envelope/PSD/
  correlator front end; the decoder resamples to 15.36 anyway). Sub-canonical ANTSDR rates cost
  *coverage*, not sensitivity. Do not let anyone re-argue rate on sensitivity grounds.
- cs8 vs cs12 is a non-difference at these SNRs (≤0.1 dB). The cs16 case rests on headroom/blocker
  dynamic range, never on this bench.
- **Blocker failures are a *correlator* problem, not a screening problem** (diagnosed 2026-09-18).
  `_demodulate` applies no channel-select filter, so `zc_score` is normalised by full-band slice
  energy: a continuous emitter N dB above the burst multiplies the score by 10^(-N/20) exactly
  (clean 0.969 -> 0.087 with a +20 dB wideband blocker, 0.030 with a +30 dB CW) even when the centre
  estimate is *perfect*. Fix = zero-phase FIR channel filter at the 4.51 MHz DroneID band edge before
  correlation; cutoff placement is critical (brick wall at 4.60 MHz = 0/8 CRC, FIR at 4.51 = 8/8).
  Secondary: `_grow_band` grows through a stronger adjacent band, and `DRONEID_MAX_OCCUPIED_HZ=14e6`
  lets the resulting 12 MHz band still count as "DroneID-shaped". Design:
  `docs/design/decoder-blocker-robustness.md`.
- **The bench window is 1.70 burst lengths**, so `decode_all` takes the `n <= 4*in_burst` short path
  and never calls `find_burst_candidates`; envelope contrast is 0.72 dB (clean) / 0.01 dB (CW) against
  a 3 dB threshold. **This sweep proves nothing about envelope detection or about 1 s field windows.**

**Why:** three near-decisions were made on the broken first-crossing metric before it was caught.
**How to apply:** when any sweep result is quoted, ask which estimator produced it and whether the arms
were paired (they are not — per-arm seeds come from `hash((label, snr, trial))`, so arms see independent
noise draws and `PYTHONHASHSEED` makes runs non-reproducible). Related: [[canonical-representation]].
