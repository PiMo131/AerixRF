---
name: c4-fa-regression-fix
description: Why the corrected per-bin floor manufactured ambient hop sets, and the two-part event-layer fix (unresolved fragments + wideband occupancy spans) that took hopping FA 17.2 % -> 1.38 %.
metadata:
  type: project
---

The C4 per-bin noise floor raises the floor estimate INSIDE continuously
occupied bins, and that single mechanism produces two distinct artefact
families. Both must be handled at the event layer, never by re-deriving
downstream bandwidth thresholds.

**Why:** on `wip/stage1-c4` the ANTSDR ambient corpus went from 11/1160 to
199/1160 `hopping_candidate` (and `fixed_channel_burst_candidate` 205 -> 0,
`wifi_beacon_like` 6 -> 0) purely from bandwidth/centre corruption. See
[[c4-perbin-floor-reconciliation]] for the floor estimator itself.

**How to apply:**

1. `_edge_cross` stops on `floor_db + hysteresis` whenever the peak is under
   `EDGE_DB + hold_db` (~10 dB) over its own floor. That is **72 %** of ambient
   events — `bw_noise_limited` alone is NOT a usable exclusion key; it must be
   ANDed with a resolution test (`bw < FRAGMENT_MAX_BW_HZ`, the T1 300 kHz
   smoothing width). No real component can measure narrower than the kernel
   that produced it.
2. The bigger half is **occupancy interior speckle**: a 20 MHz Wi-Fi channel
   is reported as a shifting set of 0.3-1.2 MHz local maxima with peaks
   3-42 dB over their own local floors, at stable distinct centres that repeat
   over the dwell. These are NOT weak fragments and no per-event SNR/width
   gate will remove them. The fix is to union wide events into frequency
   occupancy spans and mask narrow events inside a span >=4x wider.
   A per-event "concurrent with a >=4x wider event" containment test was
   measured and is far too weak: 6 of 1008 hop-set member events. Co-temporality
   must be dropped — the occupant's pieces are short, the occupancy is not.
3. Anchor the span at 2.5 MHz (`HOP_MAX_CLUSTER_BW_HZ`), not 8 MHz and not
   4 MHz: the detector reports the occupant's pieces, not the occupant.
   4 MHz -> 30/1160, 2.5 MHz -> 16/1160.
4. This is masking, not rejection: a hopper inside an occupied Wi-Fi channel is
   hidden. Consistent with the existing `wifi_like_wideband` note. Remedy is
   multi-dwell on a less occupied centre.

Durable side observations (2026-09-19):
* The 256 strongest-N event cap is **saturated in every ambient window**, so
  event COUNTS carry no information there and the surviving set is
  cap-rank-biased. Any future rule counting events must account for this.
* FA is strongly look-limited: 15 of 16 residual hop windows come from the 261
  non-`iq=` (single-look) windows (5.7 %) vs 1 of 899 `iq=` windows (0.1 %).
* Cost, 1 s at 12.288 MS/s (4000x1024): `spectrogram.compute` 64 ms,
  `energy.detect` 169 ms without `iq=`, 320 ms with. Multi-look is ~1.9x the
  detector; real time holds single-threaded, keep `iq=` opt-in per profile.
