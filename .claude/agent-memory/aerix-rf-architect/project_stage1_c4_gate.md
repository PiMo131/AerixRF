---
name: stage1-c4-gate
description: 2026-09-19 Fable gate on branch wip/stage1-c4 (per-bin floor / P_fa thresholds) — option A′ merge-after-gates; per-session FA budget rule; BLE/Zigbee hops are correct level-1 labels
metadata:
  type: project
---

Fable verdict 2026-09-19: merge `wip/stage1-c4` with the per-bin floor as DEFAULT (scalar floor kept as a named
fallback), gated on (i) ≥20 dB edge-walk regression test, (ii) level-2 fires on RFUAV aligned with the
transmitter's real channels (FAIL ⇒ HOLD), (iii) fragment rule not excluding real RC bursts inside active Wi-Fi.
Also (iv) characterise ambient `hopping_candidate` windows: BLE/Zigbee hoppers are correct labels, not FA.

**Why:** main's bandwidths are 15–50× wrong (single-look scalar floor) so level-2 rules are blind; the 0.95 %
ambient rate on main is the output of a broken estimator, not a validated baseline. The branch's mean FA (~4 %)
hides a per-session tail (12 % on the control session).

**How to apply:** FA budget = **≤ 5 % in every session and level-2 = 0 on ambient**, judged only on genuinely
false labels (fragments/spurs), not a corpus mean. Never quote the ambient rate as a field rate (X310 positives vs
E200 negatives — relative decisions only). Multi-look detector STFT is opt-in (`AERIX_RF_DETECTOR_LOOKS`) because
a second STFT costs 340–470 ms/window. First own-receiver RC capture protocol: paired RC-on/RC-off, same room,
Wi-Fi AP on (docs/field/positives-protocol.md addendum).
