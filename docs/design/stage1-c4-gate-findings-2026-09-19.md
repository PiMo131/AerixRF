# C4 merge-gate evidence (branch wip/stage1-c4 @ 0125deb)
## Status: in progress

## Baseline counts (bench/out/stage1_fa_budget_c4_looks1.json)
session | n_windows | hopping_candidate | rate
--- | --- | --- | ---
t4b1_check | 20 | 2 | 10.0 %
soak10min_b | 122 | 14 | 11.5 %
probe_default | 60 | 9 | 15.0 %
probe_k32_4m | 59 | 2 | 3.4 %
a_iq_default | 300 | 7 | 2.3 %
soak600_k32_4m_iq | 599 | 12 | 2.0 %
TOTAL 1160 windows / 46 hopping_candidate (3.97 %)
(prompt's per-session split 0/5/3/5/16/9 does not match the JSON; JSON is authoritative, total 46 agrees)

Three sessions are ALREADY over the 5 % per-session budget on raw count, so item (iv)
only helps if most of those windows are correct BLE/Zigbee hopper labels.

## ITEM (iv) result — 46/46 hopping windows reproduced on 0125deb
Capture: all windows LO 2437 MHz, fs 12.288 MS/s -> visible band 2430.86-2443.14 MHz.
Frame dt = 250 us, so burst duration is quantised at 250 us: the "BLE 150-400 us"
criterion is NOT testable on this corpus (every short burst reads 250 us).
Every window is event-cap saturated (n_events = 256).

Two distinct regimes:
* sessions 1-4 (t4b1_check, soak10min_b, probe_default, probe_k32_4m; 27 windows):
  hop sets are 3-4 repeat clusters on the ABSOLUTE even-MHz 2 MHz grid
  (2432/2434/2436/2438/2440/2442, centre scatter <= 120 kHz, SNR 15-42 dB) plus
  one wideband Wi-Fi cluster (bw 1.3-4.3 MHz, 10-27 ms bursts). 2 MHz-grid
  hopper = correct level-1 morphology.
* sessions 5-6 (a_iq_default, soak600; 19 windows): hop sets are band-EDGE lines
  at 2430.88 / 2443.10 MHz (bw ~0 kHz, SNR 2-3 dB, present in every window) plus
  near-edge speckle and one persistent off-grid 2442.3 MHz cluster. These are
  receiver/edge artefacts -> genuine false alarms.

per-session: HOPPER_OK / UNKNOWN(mixed) / FA
 t4b1_check   20 win:  1 / 1 / 0   -> FA 0.0 %, worst-case 5.0 %
 soak10min_b 122 win: 11 / 3 / 0   -> FA 0.0 %, worst-case 2.5 %
 probe_default 60 win: 5 / 4 / 0   -> FA 0.0 %, worst-case 6.7 %
 probe_k32_4m  59 win: 2 / 0 / 0   -> FA 0.0 %, worst-case 0.0 %
 a_iq_default 300 win: 0 / 0 / 7   -> FA 2.3 %
 soak600      599 win: 0 / 5 / 7   -> FA 1.2 %, worst-case 2.0 %

Verdict (iv): the FA budget is met per session ONCE correct labels are removed.
Worst case (UNKNOWN counted as FA): 5.0 / 2.5 / 6.7 / 0.0 / 2.3 / 2.0 %.
Best case (UNKNOWN = mixed BLE+Wi-Fi, i.e. partly correct): 0 / 0 / 0 / 0 / 2.3 / 1.2 %.
Caveat: "BLE" here is 2 MHz-grid morphology (level 1), NOT identity. Advertising
channels 2402/2426/2480 are all OUTSIDE the captured band, so the adv-channel
test is unavailable, and the 250 us frame pitch makes the 150-400 us burst test
unavailable. Evidence is: absolute even-MHz alignment, <=120 kHz scatter, 3-4
repeat clusters per window, sustained over 4 sessions / ~20 min.
Spur-vs-emitter: the even-MHz comb is ABSENT in sessions 5-6 at the same LO, so
it is not an LO/clock spur comb; the 2430.88/2443.10 MHz lines ARE in every
session-5/6 window and ARE receiver band-edge artefacts. Clean confirmation
would need one ambient capture at a different LO (e.g. 2432 or 2442 MHz).

## ITEM (iii) result — fragment-rule hazard on RFUAV RC data
Precondition does not occur in the data: across 28 slices x 8 RC models
(FLYSKY_FS_I6X, FRSKY_X9DP2019, JUMPER_T14, FUTABA_T16IZ, DJI_MINI3,
SKYDROID_T10, FLYSKY_NV_14, FRSKY_X20R), measured with the C4 per-bin floor:
  - widest contiguous run of standing occupancy (floor excess >= 3 dB): 0.0-0.3 MHz
  - fraction of bins with floor excess >= 3 dB: 0.00 %
  - frames containing a >= 16 MHz simultaneous occupancy: 0.0 %
i.e. no active >= 8 MHz occupant. (This contradicts the "heavy wideband
occupancy" statement in docs/design/stage1-rc-positives-2026-09-19.md S0, which
was measured before the per-bin floor: that occupancy was the scalar-floor
percolation artefact, not a real occupant.)

Injected-occupant duty sweep (SIMULATION: 20 MHz band-limited Gaussian occupant
added offline to stored RFUAV IQ, 12 dB SNR, 500 us on/off blocks; 0.15 s slices):
 model            duty   IN n  frag%  mask%  EXCL%  |  OUT n  frag%  mask%  EXCL%
 FRSKY_X9DP2019   0.00     12    0.0    0.0    0.0  |    12    0.0    0.0    0.0
 FRSKY_X9DP2019   0.15     14    0.0  100.0  100.0  |    12    0.0    0.0    0.0
 FRSKY_X9DP2019   0.35      6    0.0  100.0  100.0  |    12    0.0    0.0    0.0
 FUTABA_T16IZ     0.00     34    0.0   91.2   91.2  |    15    0.0   53.3   53.3
 FUTABA_T16IZ     0.15     27    0.0  100.0  100.0  |    15    0.0   86.7   86.7
 FUTABA_T16IZ     0.35      6    0.0  100.0  100.0  |    14    0.0   85.7   85.7
 FUTABA_T16IZ     0.60      6    0.0  100.0  100.0  |    12    0.0   33.3   33.3
 (duty 1.00 -> mask 0 %: a fully continuous occupant is absorbed by the per-bin
  floor and never becomes a >= 2.5 MHz EVENT, so no span is anchored.)

`is_unresolved_fragment` = 0.0 % on true RC hop bursts everywhere, inside and
outside, at every duty. The fail-closed hazard is real but lives in
`is_occupancy_masked`, not in the fragment rule.
