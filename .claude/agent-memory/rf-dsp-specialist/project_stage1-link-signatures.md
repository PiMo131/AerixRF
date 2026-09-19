---
name: stage1-link-signatures
description: Stage-1/2 hop-raster, hop-rate and cadence rules (2026-09-19) - the Rayleigh lattice test, why a 2 MHz raster is single-dwell-undecidable, and why cadence must leave the 1 s window
metadata:
  type: project
---

Memo: `docs/design/stage1-link-signatures.md` (151 lines). Builds on [[canonical-representation]] (D8
200 us detector frames, D11 absolute-Hz 10 MHz common band) and [[features-v2-benchmark]].

**Decision.** Replace `energy.py`'s centroid-spread `fhss_candidate` heuristic with three estimators:
burst channelization (-6 dB edge midpoint centre), a frequency-lattice (raster) test and a time-lattice
(period) test. Both lattice tests use the same Rayleigh concentration statistic
`R = |(1/M) sum exp(j2pi c_m/Delta)|` with null `P(R>=r) ~ exp(-M r^2)`, so the false-match probability
is an explicit number instead of a tuned threshold. Operating point for a level-2 grid claim:
**M >= 10 clusters and R >= 0.93** (family-wise p <= 1.7e-4 after Bonferroni over 6 Delta candidates).

**Why (hard to re-derive):**
- **Jitter budget is load-bearing.** R is attenuated by `exp(-2pi^2 sigma_f^2/Delta^2)`. At Delta = 1 MHz,
  sigma_f = 50 kHz gives 0.952 but 100 kHz gives 0.82 - i.e. a *true* 1 MHz grid fails the 0.93 threshold
  unless the burst-centre estimator reaches **sigma_f <= 60 kHz (4 bins at 15 kHz)**. Any burst-centre
  implementation must be validated against that number first.
- **Delta >= 2 MHz is single-dwell-undecidable.** Only floor(10/Delta)+1 = 6 channels fit the 10 MHz
  common band, so M >= 10 is unreachable in one dwell. The DJI RC 2 MHz raster (measured 2026-09-04)
  therefore needs >= 3 **dithered** dwell centres accumulated in absolute Hz. Non-dithered periodic dwell
  scheduling against a periodic hopper samples a biased sub-lattice and biases the spacing estimate.
- **BLE data channels are 37 x 2 MHz from 2404**, i.e. the same raster *and* the same 0-mod-2-MHz offset
  as the DJI RC uplink. Raster alone can never separate them; the separator is the time lattice (BLE
  connection intervals are 7.5 ms - 4 s quantised to 1.25 ms, one channel change per event, vs ~0.5 ms
  bursts at >= 200 Hz for the RC link). Wi-Fi and BLE advertising cannot reach M >= 10 in a 10 MHz dwell
  at all (fixed 5 MHz raster / 3 channels 24-54 MHz apart), so they are excluded by construction.
- **Cadence cannot be measured in a 1 s window.** At 640 ms there is at most one interval, so the existing
  300-1000 ms `cadence_bonus` fires on noise; and `_estimate_cadence_ms` runs on the whole-band envelope,
  so ambient Wi-Fi sets every candidate's cadence. Cadence must be per channel cluster and must move to a
  session-level burst-event stream (>= 5 bursts over >= 3 s for a DroneID cadence candidate).
- **ELRS observability:** 80 ch over 79 MHz means only rho = 0.125 of hops land in a 10 MHz dwell;
  coupon-collector for 8 of 10 in-band channels needs ~14.3 in-band bursts = 2.3 s at 50 Hz, 0.76 s at
  150 Hz. So 1 s dwells only decide the 1 MHz grid above ~150 Hz packet rate.
- ELRS 2.4 centres are ≡ 0.400 MHz (mod 1.000). That offset match is carried as
  `consistent_with: ["expresslrs_2g4_grid"]`, never as a vendor token in the label. Offset claims are void
  unless the receiver LO error is calibrated and recorded per window; spacing claims survive.

**How to apply:** this is the reference for any hop/raster/cadence question. Acceptance budget on the 571
prepared ANTSDR ambient windows: zero `fhss_*_grid_candidate` and zero `droneid_cadence_candidate`;
<= 1 `rc_link_family_candidate`; `hopping_candidate` (level 1) may fire up to 5 %. Public RC-vendor and
Zenodo captures validate the *estimator* only - PFA comes from the ANTSDR ambient corpus alone.
Unresolved and blocking: the DJI RC hop-set span and raster offset mod 2 MHz, and ELRS FLRC/LoRa
air-times per rate.
