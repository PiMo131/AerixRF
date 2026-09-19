---
name: stage1-rc-defects
description: Five measured Stage-1 defects found on real RFUAV RC captures (degenerate period_test, first-64 event cap, cluster chaining, single-look gate, grid bin-width limit)
metadata:
  type: project
---

Stage-1 produced **zero level-2 labels** on 31 RFUAV RC-transmitter models
(428 windows) but did emit 33 `hopping_candidate` + 103
`fixed_channel_burst_candidate` (level 1) vs 0/100 on the ANTSDR ambient
control. Root causes measured 2026-09-19 (details:
`docs/design/stage1-rc-positives-2026-09-19.md`), in order of decisiveness:

1. **`period_test` always returns t̂ = 1.0 s, R = 1.0, passed.** Co-temporal
   bursts at different centres give `dt = 0`; identical values have Rayleigh
   R = 1 at *every* trial period, so the "largest passing candidate" alias rule
   picks the top of `FREE_PERIOD_RANGE_S`. `rc_link_family_candidate` needs
   1–20 ms, so it can never fire in any real 2.4 GHz window.
2. **`_MAX_EVENTS = 64` truncates to the first ~5 ms of a 1 s window** —
   `scipy.ndimage.label` numbers components time-major, so the cap is a *time*
   cut, not a strength cut. Cap 256 flips all three inspected models to
   `hopping_candidate`.
3. **`cluster_centres` single-linkage chains** at high event density (no max
   cluster width): 20 143 events → ONE cluster spanning 99.4 MHz. This makes
   the cap sweep non-monotonic — 256 works, 1024 and ∞ fail. Fix the chaining
   before raising the cap.
4. **Gate/hold set against a single-look periodogram.** `spectrogram.compute`
   does no frame averaging, so noise bins are exponential; hold at floor+3 dB
   passes ~25 % of noise pixels and 4-connected labelling percolates. Live
   scalar floor measures burst BW at 4.9–18.8 MHz where the true median is
   **0.31–0.41 MHz** (15–50× over), which then feeds (3)'s bandwidth-scaled
   merge threshold. Per-bin median + 6 dB floor restores 0.3–0.6 MHz.
5. **Grid test is resolution-starved above ~30 MS/s.** R ≥ 0.93 at Δ = 1 MHz
   needs total centre jitter σ_f ≤ 59 kHz; 100 MS/s / 1024 bins = 97.7 kHz
   pitch (σ ≈ 28 kHz from quantisation alone). Observed best R 0.27–0.61 ≈
   σ_f 150–250 kHz — estimator-limited, NOT "no grid". Canonical 15.36 MS/s at
   1024 bins (15 kHz) is fine. Rule of thumb: need `bin_hz <= Δ/20`.

Ground truth for the RFUAV RC slices (level 2, third-party USRP X310 capture,
crowded band): the uplinks ARE present — 3 050–20 230 narrowband bursts/s,
median BW 0.31–0.41 MHz, 16–75 distinct channel clusters recoverable at 250 µs
frame pitch across 2390–2490 MHz. "TX idle" / "hop set too wide for 1 s" are
NOT supported explanations.

**Why:** the first reading of the bench output ("all zero") was wrong in two
ways — level-1 labels did fire, and the level-2 zeros were mechanism failures,
not evidence of absence.
**How to apply:** when Stage-1 output looks uniformly negative, check t̂ = 1.0 s
and n_events == 64 first — both are signatures of these defects, not of the
signal. Related: [[stage1-link-signatures]], [[decode-snr-bench]] (same
`argmax(psd)` centring weakness reappears in the RC bench's dwell emulation,
which tuned to the 2390 MHz band edge).
