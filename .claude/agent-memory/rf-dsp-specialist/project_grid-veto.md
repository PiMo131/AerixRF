---
name: grid-veto
description: Why the Stage-1 1 MHz lattice test fires on wideband contamination (C4 gate ii) — per-bin-floor speckle, dead occupancy mask, wrong Rayleigh null, r=0.0 sentinel.
metadata:
  type: project
---

Stage-1 `fhss_1mhz_grid_candidate` fired at r = 0.95–0.99 / M = 32–65 on RFUAV windows with no hop
comb (SIYI MK15, WFLY ET10/ET16S): one always-on carrier + a diffuse 19–74 MHz, 3–10 %-duty
occupant. Mechanism, in order of importance:

1. The C4 per-bin floor tracks an occupant's own PSD, so a wideband occupant never surfaces as a
   ≥ 2.5 MHz event — it becomes many 0.3–1.2 MHz speckle maxima. `wideband_occupancy_spans()`
   anchors on event width, so it returns `[]` and `is_occupancy_masked()` is a no-op exactly where
   it was needed. The surviving occupancy evidence is per-event `floor_occupied_span_hz`.
2. `_p_false_corrected` cannot veto this: 576 trials × exp(-M r²) is ~1e-11 at M=32/r=0.99. The
   null (i.i.d. uniform centres) is wrong — clustering imposes hard-core minimum separation and
   speckle imposes a pitch, and M over-counts independent phase draws (clumps).
3. The σ_f debias is one-sided (can only raise r), so it can never flag that r = 0.99 at
   Δ = 1 MHz implies ≤ 22.6 kHz centre RMS error — impossible for near-floor bursts through a
   300 kHz smoothing kernel. Tight r + weak members = deterministic comb, not a hop set.
4. `rayleigh_r = 0.0` is the `insufficient` sentinel, not a failed fit. Skydroid 0.0 vs 0.989 on
   neighbouring windows is cluster-count bimodality (density-dependent chaining), not estimator
   instability. Never read 0.0 as "no lattice".

Open: the exact 1.000 MHz comb across unrelated models may be an X310 reference-spur artefact of
the public corpus — check `offset mod 1 MHz` invariance and signal-free windows.

Spec: `docs/design/stage1-grid-veto-spec.md`. Related: [[stage1-c4-c5-decisions]],
[[stage1-link-signatures]], [[stage1-rc-defects]].
