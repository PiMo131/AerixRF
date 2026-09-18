---
name: centre-hypothesis-scorer
description: zc6 (not zc4) is the only frequency-selective scorer for DroneID centre-hypothesis selection; ranked full-sync + zc6-gated refinement fixes the wideband blocker, and edge de-biasing is a rejected dead end.
metadata:
  type: project
---

Measured 2026-09-18 on the synthetic bench (40 windows/point) plus both RUB real-IQ files.

**zc4 must never be used to compare centre hypotheses.** Its ZC shift ambiguity keeps it at 0.84-0.97 for
a centre error of hundreds of kHz, so as a comparator it nudges already-correct centres (including DC)
50-100 kHz off. That is exactly how the first fix attempt regressed real IQ (RUB mavic 0/1, mini2 5/10)
and was reverted. **zc6** — the equalized sym-6 confirm computed after the STO/integer-CFO search inside
`_demodulate` — is the selective metric (~0.9 correct, 0.01-0.03 at 60 kHz error) and is already computed;
ranking hypotheses by it costs one extra `_demodulate` per hypothesis (~35 ms at 15.36 MS/s), not new DSP.

Outcome per option (clean 4/5/6 dB — baseline 35/38/37; RUB — baseline 1/10; wb blocker 10/12/14 dB —
baseline 18/19/21):
- rank all peel hypotheses by (zc6, zc4): clean/RUB identical, wb 26/30/27.
- + zc6-gated ±100…400 kHz refinement (trigger zc6<0.35 and zc4≥0.4): clean/RUB identical, wb 40/39/40,
  and ≥0.975 from 6 to 14 dB → `snr50_final_db` drops off the bottom of the grid from 15.4. **Recommended.**
- de-biasing `_grow_band` next to a peeled neighbour (reconstruct centre from the clean edge + nominal
  9.015 MHz): **destroys the clean arm, 1/120.** Rejected; do not retry without instrumenting the
  interaction with `PEEL_DEDUP_HZ`'s suppression of the mandatory 0.0 fallback.

Two reusable constraints: an early accept at zc6 ≥ 0.75 is what keeps clean/RUB bit-identical (one
hypothesis, one demod, baseline path); and any centre-refinement grid step must stay ≤ `2*K*15 kHz`
(= 120 kHz, the integer-CFO capture range) so the existing ±4-bin search absorbs the residual.

**Why:** the wb-blocker knee was a hypothesis-selection artifact, not sync robustness ([[blocker-failure-split]]).
**How to apply:** evidence level 1-2, single synthetic blocker geometry; the RUB files only prove
non-regression, not blocker performance. Cost on crowded real windows is still unmeasured because
`_segment_envelope` yields 0 candidates on noise. Design written up in
docs/design/decoder-blocker-robustness.md "§ Scorer design (2026-09-18)". See also [[decode-snr-bench]].
