---
name: blocker-failure-split
description: Under the adjacent wideband blocker the DroneID decode fails at centre-hypothesis selection, not at sync/CFO/turbo — measured 2026-09-18, with the two specific mechanisms.
metadata:
  type: project
---

At the `B_wb_blocker` knee (+20 dB band-limited OFDM-like blocker at +4.5…+8.5 MHz, 40 windows per SNR at
10/12/14 dB in-band), DroneID decode failures are a **detection/hypothesis-selection** problem, not a
sync/decode problem. A forced-centre probe (mix to the ground-truth 0 Hz burst centre, same slice, same
channel FIR, same front end) recovers the serial in 119/120 windows, while the real pipeline succeeds in
58/120. Budget exhaustion was never a cause (0/120). The clean arm at 4-6 dB fails differently — every
failure is CRC/turbo at the correct centre (zc6 0.50-0.73), i.e. genuine low-SNR decode.

Two mechanisms, both in `_centre_hypotheses` / the `decode_all` hypothesis loop:
1. Blocker skirt truncates the upper edge of the grown occupied band, biasing the peel centre to
   -0.1…-0.4 MHz; `PEEL_DEDUP_HZ = 0.5e6` then suppresses the 0.0 fallback so the true centre is never
   offered. A >60 kHz mix error leaves a 4.5-6.5 subcarrier residual: the ZC4 gate still fires 0.84-0.97
   (shift ambiguity) but zc6 confirm collapses to ~0.02.
2. The hypothesis loop breaks on `level != "none"`, so a wrong centre at -0.5…-1.7 MHz that reaches level
   "A" blocks the true centre that sits next in the list.

**Why:** Fable required this number before authorising any decoder redesign; it decides whether effort goes
into per-subband envelope/hypothesis ordering or into the FIR/CFO chain.
**How to apply:** Do not redesign the channel-select FIR or the CFO estimator for adjacent-blocker
robustness — the headroom is already there. Fix hypothesis generation/ordering first (break only on level
"B"; shrink the DC-fallback dedup to ~60 kHz; de-bias the band-edge estimate next to a peeled neighbour).
Remember the forced probe used ground truth, so it is an upper bound, not an algorithm. Resolved 2026-09-18 by [[centre-hypothesis-scorer]] — do NOT pursue the de-bias suggestion below, it was measured and rejected. Single synthetic
blocker geometry, no stored-IQ/live confirmation — evidence level 1-2 only. See
[[decode-snr-bench]] and docs/design/decoder-blocker-robustness.md "§ Failure split (2026-09-18)".
