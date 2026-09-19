---
name: c4-perbin-floor-reconciliation
description: C4 per-bin noise floor - measured Hann look model (rho2=0.48, not W/1.5), clamp-reference and reject-to-reference rules, bounded -6 dB edge walk, C3b grid-cap split point, and the unresolved skirt-speckle item C6.
metadata:
  type: project
---

Validated 2026-09-19 while reconciling the C4/C3b implementation against
`docs/design/stage1-c4-c5-spec.md` (see that file's "§ Implementation
reconciliation 2026-09-19" for the full write-up and the measured tables).

**Effective looks from frequency smoothing.** A W-bin boxcar over a Hann STFT gives
`L_eff = W^2 / (W + 2*rho2*(W-1))` with `rho2 ~= 0.48`, NOT `W/1.5`. Measured
`L_hat = mean^2/var` on white-noise STFT frames: W=3 -> 1.85, 15 -> 7.91, 25 -> 13.02,
31 -> 16.11. The ENBW factor 1.5 is a resolution penalty, not a variance reduction;
using it made the arm threshold 0.45 dB low and the arm-pixel rate 17x the 1e-6 target.

**Clamp reference for a per-bin floor.** `F_ref = median over bins` is only valid below
50 % band occupancy. One 16 MHz emitter in a 20 MHz capture puts the median on the
signal and inverts the whole estimator. The reference must come from an
occupancy-immune estimate (non-burst *time* slices, or a 5th percentile over bins) —
in this repo `energy.detect`'s existing scalar `noise_lin`.

**Reject to the reference, not to the boundary.** Clipping a contaminated bin to
`F_ref + CLAMP_DB` leaves the occupant's margin at `(SNR - CLAMP_DB)`, so a 10-15 dB
continuous emitter sits right at the arm threshold and fragments into speckle. Once the
clamp binds, the bin's own estimate is known bad: use `F_ref`.

**-6 dB edge walks must be bounded by the noise.** An edge walk that only stops at
`peak - 6 dB` returns the whole captured band for any component whose peak is less than
6 dB above its hold threshold. Bound it with `max(peak - EDGE_DB, floor_db + hyst_db)`.
This dominated a "median bandwidth = full band" result on 300 kHz bursts.

**Merge caps vs a channel grid.** An anti-grid-bridging merge cap must apply only to
pairs narrower than the smallest grid step under test (`min(DEFAULT_DELTAS_HZ)`), not to
everything under the hop-channel BW ceiling — otherwise one wideband emitter sampled by
sparse -6 dB centre estimates splits into a fake hop set. Time-overlap conditioning does
NOT separate these cases (sparse samples of one emitter are often non-co-temporal).

**Unresolved (C6).** A per-bin floor always leaves a skirt band around a strong
continuous occupant where `signal/floor` crosses the arm threshold, so the emitter
fragments there (~16 bins -> ~229 fragment events in the 16 MHz test). Frequency gap
bridging does not fix it. The fix is a frequency-LOCAL robust reference (running low
quantile over ~2 MHz, ~3 dB rejection radius), which first needs
`test_perbin_floor_tracks_tilted_noise` re-specified in dB/MHz (it currently uses an
unphysical ~8 dB/MHz tilt across 64 bins). Interim guard lives at the evidence layer:
`energy._is_fragment_of_wideband` suppresses a window cadence when the dominant cluster
is concurrent with a >=4x wider event. Related: [[stage1-c4-c5-decisions]],
[[stage1-rc-defects]].
