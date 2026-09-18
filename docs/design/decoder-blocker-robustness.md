# Decoder blocker robustness — root cause and design (rf-dsp, 2026-09-18)

## Conclusion

The multi-peak `burst_spectrum` work was necessary but not sufficient, and the "loss is upstream in
the envelope detector" hypothesis is **refuted for this bench**. The dominant defect is *downstream*
of screening: **`_demodulate` has no channel-select filter, so the ZC correlation score is normalised
by full-band slice energy and a strong out-of-band emitter collapses it below threshold.**

Measured at 15.36 MS/s, SNR 14 dB, perfect centre (`mix = 0`, whole window):

| arm | zc_score | predicted `0.969 x 10^(-blocker_dB/20)` | grade |
|---|---|---|---|
| clean | 0.969 | — | B, CRC ok |
| `B_wb_blocker` (+20 dB) | 0.087 | 0.097 | none |
| CW (+30 dB) | 0.030 | 0.031 | none |

The match to the level law is exact: the correlator measures blocker power, not sync quality. Notching
the blocker and changing nothing else restores `C`/CRC in both arms. Secondary defect (real, but not the blocker): `_grow_band` grows *through* a stronger adjacent band
(bins above the peak satisfy "within `FLOOR_DB` of the peak"), so the wb arm's best alternate is
centre **+1.583 MHz, bw 12.195 MHz**, still flagged `droneid_shaped` because
`DRONEID_MAX_OCCUPIED_HZ = 14 MHz`. Mixing by that centre gives zc 0.116. Centre tolerance is tight:
a deliberate 200 kHz error drops a clean window from CRC-ok to grade A.

## Why the envelope hypothesis is refuted here, and the signal model

`_make_master_burst` produces a window of **1.70 burst lengths**, so `decode_all` takes the
`n <= 4 * in_burst` short path and makes **one candidate spanning the whole window**;
`find_burst_candidates` is never called. Envelope contrast (max block / median block) is
**0.72 dB clean, 1.15 dB wb, 0.01 dB cw** against a 3 dB threshold, and `_segment_envelope` returns
**0 candidates in every arm including clean**. The bench does not test envelope detection at all —
itself a gap, since the field 1 s-window case (continuous emitter 20-30 dB above a 0.64 ms burst ⇒
median floor pinned to the blocker) is real and untested. Slice model: DroneID burst (601 x 15 kHz ⇒
9.015 MHz occupied) + AWGN + one continuous emitter, CW at +6.0 MHz (+30 dB) or band-limited Gaussian
occupying +4.5…+7.68 MHz after window clipping (+20 dB, PSD density ~23 dB above the DroneID band).
wb/DroneID band overlap is only ~7.5 kHz — **separable by filtering**, but only with the passband edge
at ~4.51 MHz.

## Chosen design (validated in prototype)

Per candidate slice, in `_demodulate`'s caller:

1. **Band-peel centre hypotheses.** On the slice PSD, repeat up to `PEEL_ROUNDS = 8`: take argmax,
   `_grow_band` it, emit `(centre, bw)`, zero those bins. Keep only hypotheses with
   `|centre| < fs/2 - 1 MHz` and `4.0 MHz <= bw <= 11.0 MHz`; preserve peel (power) order; dedup at
   0.5 MHz; **always append `centre = 0.0` as a final fallback**. Because the blocker's bins are
   zeroed first, the DroneID band's edges are then clean: wb yields exactly one hypothesis,
   `(-0.022 MHz, 8.98 MHz)` — true centre.
2. **Channel-select filter after mixing, before correlation.** Zero-phase FIR,
   `firwin(129, 4.51e6, fs=fs, window=("kaiser", 10.0))` applied with `filtfilt`. Cutoff placement is
   critical, not cosmetic: a brick wall at 4.60 MHz gives **0/8 CRC** on wb while the 4.51 MHz FIR
   gives **8/8 at 10 dB SNR** (each extra 10 kHz of passband admits ~0.2x the whole burst power).
3. Try hypotheses in order, stop at the first `grade != "none"` that decodes.

Prototype (n=8/point, bench generator), CRC at 9/10/12/14 dB — clean 5,8,8,8 (unchanged);
CW +30 dB 3,8,8,8 (was 0 everywhere); wb +20 dB 4,7,5,6 (was 0 everywhere).
wb is not yet saturated, but `mix = 0` + the same filter is 8/8 at 10/12/14 dB, so the remaining loss
is hypothesis generation, not the filter — hence the mandatory `centre = 0.0` fallback and the
tunables below.

## Options considered and rejected

(a) duty-cycle excision of persistent bins and (c) per-bin median whitening cannot be validated here
(window = 1.7 burst lengths, burst duty cycle 59 %); both remain the right answer for 1 s field
windows — defer to that work item. (b) per-subband envelope detection is orthogonal to this failure.
(d) correlator-first raster search is affordable (1.9 ms/centre) but strictly worse than (1)+(2):
peeling gets the same answer from one PSD. A level-invariant raster scorer (in-band minus guard-band
contrast, minus flatness) picks the blocker first on wb and the true centre only to ±0.5 MHz — too
coarse to mix with. Rejected.

## Parameters that must stay configurable

`CHANNEL_FILTER_CUTOFF_HZ` (4.51e6), `CHANNEL_FILTER_TAPS` (129), Kaiser beta (10.0),
`PEEL_ROUNDS` (8), peel shape window (4.0e6…11.0e6), `PEEL_DEDUP_HZ` (0.5e6), `MAX_CENTRE_HYPOTHESES`
(4). Tighten `DRONEID_MAX_OCCUPIED_HZ` from 14e6 to 11e6 (a 12.2 MHz band is not DroneID).

## Cost

Measured: mix + filter + `_demodulate` = **1.9 ms per hypothesis** on a 1.1 ms slice at 15.36 MS/s;
peel is 1024-bin PSD arithmetic (<0.2 ms). At `MAX_CENTRE_HYPOTHESES = 4` that is ≤8 ms per envelope
candidate — well inside the 150 ms/window target. Filtering is per *slice*, never per window.

## Expected failure modes / new false-candidate risk

Peeling can split one real band in two at low SNR (extra ~2 ms, no false CRC). A co-channel blocker
overlapping >1 MHz of the DroneID band is not fixed by any of this. The FIR attenuates the outermost
DroneID carriers (~6 dB at the edge) — channel estimation should absorb it, but `B_canonical`
sensitivity must be re-measured, not assumed. Peel order is power order, so a stronger
DroneID-shaped neighbour costs one wasted 1.9 ms attempt; it cannot create a false *decode* (CRC
gates level C).

## Builder task

Files: `aerix_rf/decode/droneid.py` only (plus `tests/test_decode.py`).

1. `_channel_filter(iq, sample_rate, cutoff_hz, taps, beta)` — cached FIR design, `filtfilt`; skip if
   the slice is shorter than `3 * taps`.
2. `_centre_hypotheses(iq, sample_rate)` — the band peel above (needs a `_grow_band` variant that also
   returns the `(lo, hi)` bin span; do not change `_grow_band`'s public behaviour).
3. In `decode_all`, replace the "primary centre + `alt_centers_hz`" loop with one ordered hypothesis
   loop: mix, channel-filter, demodulate. Keep `alt_centers_hz` populated for reporting.
4. **Fix the budget defect**: `budget_s` is checked only at the top of the candidate loop
   (`droneid.py` ~792-816) — the alternate-centre loop runs unbounded. Check elapsed inside the
   hypothesis loop and record skips.
5. Keep `burst_spectrum` / `_burst_spectrum_candidates` public behaviour unchanged (RUB golden).

Acceptance:
- `bench/canonical_rate_sweep.py` `B_wb_blocker` reports a finite `snr50_final_db` ≤ ~12 dB and the CW
  blocker arms likewise; `B_canonical_15p36msps` stays within 0.3 dB of 8.60 dB (n≥100, `PYTHONHASHSEED`
  fixed);
- `tests/test_droneid_rub_golden.py` bit-identical;
- `tests/test_decode.py` green, plus a new test: synthetic burst + 30 dB CW at +6 MHz decodes, and a
  test that a 12 MHz-wide grown band is not `droneid_shaped`;
- mean decode time per bench window ≤ 1.5x the current value; 1 s-window runtime unchanged within 10 %.

## Open evidence gaps

- Field 1 s windows: envelope detection under a continuous +20…30 dB emitter is untested here
  (median-floor pinning). Needs a long-window bench arm or stored IQ before any field claim.
- The 2026-09-04 capture (DroneID 20 dB below neighbours) must be replayed against the fix as evidence
  level 4, not re-argued from the synthetic bench.
- Time-disjoint Wi-Fi/RC bursts are unmodelled; the peel is per-slice so it should be neutral, but
  that is an assumption, not a measurement.

## § Failure split (2026-09-18)

Question (Fable gate): at the `B_wb_blocker` knee, does the decode fail at candidate detection or at
sync/decode? Method: 40 windows per SNR, bench helpers `_make_master_burst` / `_resample_arm` /
`_add_wb_blocker`; `decode_all` instrumented externally (wrappers on `_rank_candidates`,
`_centre_hypotheses`, `_demodulate`) plus an unbudgeted forced-centre probe (mix 0 Hz = ground-truth
burst centre, same slice, same FIR, same front end). Script: scratchpad `failure_split.py` (not committed).

| arm | SNR | success | no_correct_hyp | budget_exh | wrong_centre_early_sync | sync_fail@correct | crc_fail@correct |
|---|---|---|---|---|---|---|---|
| B_wb_blocker | 10 | 18 | 12 | 0 | 8 | 2 | 0 |
| B_wb_blocker | 12 | 19 | 8 | 0 | 11 | 1 | 1 |
| B_wb_blocker | 14 | 21 | 10 | 0 | 6 | 3 | 0 |
| clean B_canonical | 4 | 35 | 0 | 0 | 0 | 0 | 5 |
| clean B_canonical | 5 | 38 | 0 | 0 | 0 | 0 | 2 |
| clean B_canonical | 6 | 37 | 0 | 0 | 0 | 0 | 3 |

Conclusion: detection dominates. With the blocker present, the forced-centre probe decodes the serial in
119/120 windows at 10/12/14 dB, i.e. the FIR + ZC/CFO/turbo chain already has the SNR headroom; the 15.4 dB
SNR50_final is a centre-hypothesis artifact, not a sync-robustness limit. Two distinct mechanisms:
1. Centre-estimate bias (30/120). The blocker skirt truncates the upper edge of the grown band, so the
   peel centre lands at -0.1…-0.4 MHz instead of 0. `_centre_hypotheses` then suppresses the 0.0 fallback
   (`PEEL_DEDUP_HZ = 0.5e6`), so the true centre is never offered. Where |h| > K*15 kHz = 60 kHz the slice
   is mixed by the biased amount, leaving a 4.5-6.5 subcarrier residual: ZC4 gate still fires (0.84-0.97,
   shift ambiguity) but zc6 confirm collapses (0.01-0.03) -> level "A", the 6 `sync_fail@correct` rows.
2. Wrong-centre early exit (25/120). Hypothesis 0 at -0.5…-1.7 MHz reaches level "A" and breaks the loop
   before hypothesis 1 (the true 0.0 centre) is tried. The loop breaks on `level != "none"`, and the ZC4
   gate is not frequency-selective enough to reject a 1.7 MHz centre error.
Budget was never the cause (0/120): 8 candidates/window is not where the time goes.
Clean-arm baseline failure mode is different and expected: every failure is CRC/turbo at the correct
centre (forced probe also fails, zc6 0.50-0.73) — i.e. genuine low-SNR decode, not detection.

Implication: per-subband envelope / hypothesis ordering work is justified; the FIR and the CFO estimator
should not be redesigned for this arm. Cheapest fixes, in order: (a) only break the hypothesis loop on
level "B", keeping the best "A" for reporting; (b) make the DC/true-centre fallback survive dedup (append
unless a kept centre is within ~60 kHz, not 500 kHz); (c) de-bias the occupied-band edge estimate when an
adjacent band was peeled, or add a fine +-100 kHz centre refinement before demod.

Caveats: the forced probe mixes to the known true centre, so it is an upper bound on achievable
performance, not a proposed algorithm; a real receiver still has to estimate that centre. Single synthetic
blocker geometry (+20 dB, +4.5…+8.5 MHz, time-coincident); no stored-IQ or live confirmation yet.
