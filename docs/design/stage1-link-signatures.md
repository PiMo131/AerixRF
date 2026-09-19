# AERIX RF — Stage-1/2 link-signature rules (hop raster, hop rate, cadence discounting)

Status: design memo (rf-dsp-specialist, 2026-09-19). Scope: hardware-neutral rules computable from the D8 detector frames (200 µs, [5000 x 1024])
inside one 10–12 MHz dwell; fixes the `fhss_candidate` mislabel and adds non-UAS cadence discounting. **No rule here produces a manufacturer
claim.** Inputs: `research/briefs/datasets-and-signatures-plan.md` §B, `aerix_rf/detect/energy.py`, `docs/design/canonical-representation.md`
D3/D8/D11.

## 0. Conclusion
Three estimators — burst channelization, a frequency-lattice (raster) test, a time-lattice (period) test — replace the current centroid-spread
heuristic. Both lattice tests use the same Rayleigh concentration statistic, so false-match probability is an explicit number, not a tuned
threshold. Structural results: a **1.000 MHz grid is decidable in one 1 s dwell at packet rates ≥150 Hz**; a **2 MHz raster is not** (≤6 channels
fit a 10 MHz dwell) and collides exactly with BLE data channels, so it needs multi-dwell accumulation plus a time-domain discriminator; and
**cadence cannot be established inside a 1 s window at all** (640 ms gives ≤1 interval) — it must move to a session-level burst-event stream.

## 1. Signal model and observability budget
Per dwell: 1.000 s at one tuned centre, 200 µs frames, 15 kHz bins, declared usable 12.0 MHz (D3), rules run on the HackRF∩ANTSDR common band **10.0
MHz** (D11). All frequencies are **absolute Hz** = tuned_centre + bin_offset − `lo_offset_hz`; a raster *offset* claim is invalid unless LO error is
calibrated and recorded per window (spacing claims survive an uncalibrated LO).

| Quantity | Value | Consequence |
|---|---|---|
| Detector frame | 200 µs | bursts <400 µs amplitude-smeared; duration below ~600 µs is quantisation-limited |
| Native STFT frame | 33.3 µs (hop 512 @15.36 MS/s) | duration-refinement path, gated bursts only |
| Bin | 15 kHz | burst-centre estimator must reach σ_f ≤ 60 kHz (§2) |
| ELRS 2.4 span | 2400.4–2479.4 MHz, 80 ch @1.000 MHz | ρ = 10/79 = **0.125** of hops land in a dwell |
| In-band burst rate | 0.125 × packet rate | 50 Hz→6.3/s, 150 Hz→18.8/s, 500 Hz→62.5/s |
| Channels per dwell | floor(10/Δ)+1 | Δ=0.6→17; Δ=1.0→**10–11**; Δ=2.0→**6**; Δ=5.0→3 |

Coupon-collector: 8 distinct of the 10 in-band ELRS channels needs ≈14.3 in-band bursts → **2.3 s at 50 Hz, 0.76 s at 150 Hz, 0.23 s at 500 Hz**.
Dwell length is therefore configurable and must be ≥3 s for slow links; 1 s only works above ~150 Hz.

## 2. R1 — hop-raster estimation
**(a) Channelize.** Per-burst centre = **−6 dB edge midpoint**, not the power centroid (the centroid moves with MCS/aggregation shape and is the
root cause of the current mislabel); width = −6 dB span. Cluster centres at 100 kHz; two clusters are distinct only if separated by ≥
max(0.75·max(BW_i,BW_j), 3 bins), which forbids one wide emitter splitting into a fake hop set. M = clusters holding ≥2 bursts.

**(b) Lattice test.** For Δ ∈ {0.6, 1.0, 1.5, 2.0, 2.5, 5.0} MHz plus one free Δ from a coarse search, over cluster centres c_m: `Z(Δ) = (1/M) Σ
exp(j2π c_m/Δ)`, `R = |Z|`, offset `φ = arg(Z)·Δ/2π (mod Δ)`. Uniform-centre null: `P(R ≥ r) ≈ exp(−M r²)`. **Operating point (family-wise p ≤
1.7e-4 after Bonferroni over 6 Δ): M ≥ 10 and R ≥ 0.93** (M=10→0.932, 12→0.851, 16→0.737). Centre jitter attenuates R by `exp(−2π²σ_f²/Δ²)`: at Δ=1
MHz, σ_f=50 kHz→0.952, σ_f=100 kHz→0.82. **Hence σ_f ≤ 60 kHz (4 bins) is a hard requirement — otherwise a true 1 MHz grid cannot clear the
threshold.** Carry both R and a debiased R′ = R/exp(−2π²σ̂_f²/Δ²) from within-cluster scatter σ̂_f, debias factor **capped at 1.15**.

**(c) Alias rule.** A true Δ grid also concentrates at Δ/2, Δ/3. Report the **largest** passing Δ; smaller passing multiples go in `aliases`, never
as separate detections. (Wi-Fi's 5 MHz centre raster trivially aliases onto 1 MHz — M≥10 is what protects us.)

**(d) Offset consistency.** ELRS 2.4 centres ≡ **0.400 MHz (mod 1.000)**; tolerance ±100 kHz (covers ±24 kHz receiver LO at 10 ppm plus emitter
crystal). A match sets `consistent_with: ["expresslrs_2g4_grid"]` — a consistency list, never an identity.

**(e) Δ ≥ 2 MHz is single-dwell-undecidable.** M_max = 6 < 10, so the DJI RC 2 MHz raster (measured 2026-09-04) needs cluster centres accumulated in
absolute Hz over **≥3 dwells at different centres**, and those centres must be **dithered**: a periodic dwell schedule against a periodic hopper
samples a biased sub-lattice and biases Δ̂.

**False-match vs Wi-Fi/BLE.** Wi-Fi 2.4 APs are fixed-channel on a 5 MHz raster with ≤1 channel fully inside a 10 MHz dwell → M=1, fails by
construction. BLE advertising is 3 fixed channels (2402/2426/2480) separated by 24/54 MHz → never ≥2 in a dwell. BLE *data* channels are 37 × 2 MHz
from 2404 — **the same 2 MHz raster and the same 0 mod 2 MHz offset as the DJI RC uplink**, so raster alone can never separate them and §3 must.
Expected grid false alarms over 571 ANTSDR ambient windows at p=1.7e-4: **0.1**.

## 3. R2 — hop rate, dwell time, packet-duration histogram
**Period test (span-free).** Inter-burst intervals within the channel-cluster set are near-integer multiples of packet period T: `R_T = |(1/N) Σ
exp(j2π Δt_n/T)|`, scanning T over the ELRS declared set {1, 2, 3, 4, 6.67, 10, 20 ms} = {1000…50 Hz} plus a free T. Require **N ≥ 10 intervals, R_T
≥ 0.93**. The alternative rate estimate F̂ = λ_obs/ρ requires an assumed hop span and must be reported as conditional on that span, never as
measured.

**Duration histogram.** Bins {<0.4, 0.4–1, 1–3, 3–10, >10 ms}; report the mode bin, not a scalar. DJI RC uplink ≈0.5 ms (2.5 frames → ±40 % from D8
alone; refine on 33.3 µs frames for ≤16 gated bursts). ELRS FLRC sub-ms, ELRS LoRa 125 kHz ms-scale.

**BLE discriminator.** BLE connection intervals are 7.5 ms–4 s **quantised to 1.25 ms**, one channel change per event. So `T̂ ≥ 7.5 ms AND T̂ ≡ 0
(mod 1.25 ms) AND per-hop BW ≤2 MHz AND one burst per period` ⇒ `ble_connection_like`, suppressing the RC-family label. A 0.5 ms / ≥200 Hz hopper on
the same raster is not BLE-consistent.

## 4. R3 — cadence: discount known non-UAS, recognise DroneID
Two defects in `_estimate_cadence_ms` today: it runs on the **whole-band** envelope `p_t` (ambient Wi-Fi therefore sets every candidate's cadence)
and on a **1 s window** (at 640 ms at most one interval exists, so the 300–1000 ms `cadence_bonus` fires on noise). Fixes: (1) cadence per **channel
cluster**, on that cluster's envelope only; (2) cadence moves to a **session-level burst-event stream** with absolute timestamps — ≥5 bursts
spanning ≥3 s, combined with a 7–11 MHz flat-top burst, for a level-2 `droneid_cadence_candidate` (the ≈9.0 MHz occupancy is what makes it
non-generic); (3) a configurable **discount table**: Wi-Fi beacon 102.4 ms and multiples n=1..5 at ±2 %, BLE advertising 20 ms–10.24 s in 0.625 ms
steps. BLE adds a uniform 0–10 ms `advDelay` per event (σ≈2.9 ms; peak width grows ∝√k), so require a **high-Q** cadence peak for any claim —
crystal-locked 640 ms stays sharp, BLE adverts do not. Beacon-lattice cadence **plus** a fixed ≥16 MHz flat-top channel ⇒ `wifi_beacon_like`, which
suppresses the level-2 label and never the level-1 detection.

## 5. R4 — fixed-channel vs hopping (the `fhss_candidate` fix)
Replace `_hop_spread_mhz` (max−min of per-burst centroid) with: `fixed_channel_burst_candidate` if M=1 and centre std < 0.25 × occupied BW;
`hopping_candidate` if M ≥ 3 **and** the centre series is near-white (|lag-1 autocorr| < 0.3) — a monotone or drifting centre is AGC/AFC/thermal
drift on one emitter, which is precisely the test the current code lacks; otherwise `unknown_channel_structure`.

## 6. R5 — output vocabulary and evidence wording
Level 1 (morphology): `fixed_channel_burst_candidate`, `hopping_candidate`, `wideband_ofdm_burst_candidate`, `continuous_wideband_candidate`,
`unknown_channel_structure`. Level 2 (probabilistic family, no manufacturer): `fhss_1mhz_grid_candidate`, `fhss_2mhz_grid_candidate`,
`rc_link_family_candidate` (hopping + T̂ ∈ 1–20 ms + per-hop BW ≤2 MHz + duration mode <3 ms), `droneid_cadence_candidate`. Discount tags:
`wifi_beacon_like`, `ble_connection_like`, `ble_advertising_like`. Diagnostic tags (never suppress, never a detection):
`wifi_like_wideband`, `INSUFFICIENT_CHANNELS` (grid test not attempted, too few channel clusters), `GRID_RESOLUTION_LIMITED`
(C5, `docs/design/stage1-c4-c5-spec.md` §"C5" — the grid test *was* run but the frequency resolution (`bin_hz`) or the measured
burst bandwidth is too coarse relative to the tested Δ to resolve the lattice; `fhss_1mhz_grid_candidate`/`fhss_2mhz_grid_candidate`
are withheld, not asserted-false). Mandatory structured evidence on every level-2 output: `raster = {spacing_hz,
offset_hz, n_channels, rayleigh_r, rayleigh_r_debiased, p_false, n_dwells}`, `period = {t_hat_s, n_intervals, rayleigh_r, p_false}`,
`consistent_with: [...]`. **Naming rule: no vendor token (`elrs`, `dji`, `flysky`) in a stage-1/2 label**; vendor consistency lives only in
`consistent_with`. Identity requires a CRC-valid decode (level 4).

## 7. Configurable parameters
Δ dictionary; M_min, R_min, p_target; σ_f budget and debias cap; cluster separation factor (0.75); whiteness threshold (0.3); dwell length,
per-centre repeat count and centre dither; ELRS rate set and offset tolerance; non-UAS discount table (beacon multiples, BLE steps); DroneID
period/tolerance; min bursts for cadence; duration histogram edges; max burst events per window.

## 8. Failure modes and cost
Uncalibrated LO invalidates offset claims. Multipath/fading drops hops → M under-counts → misses, not false alarms. Strong co-channel Wi-Fi
desensitises the detector (the 2026-09-04 capture had DroneID ~20 dB below the RC hops and the beacons); above ~70 % band occupancy both noise
floors degrade (features_v2 G6 limit) and burst extraction fails — a scan-placement problem, not a rule problem. Periodic dwell schedule × periodic
hopper → sub-lattice bias. Δ/2 aliasing if (c) is skipped. Two co-present hoppers merge into one channel set and can synthesise a spurious finer
grid — require per-cluster duration and level homogeneity before pooling. Cost: burst events already capped at 64; clustering O(B log B), raster
O(M×7), period O(N×8) → sub-millisecond against the existing ~50 ms detector; the 33.3 µs refinement is gated to ≤16 bursts over their own sub-band
(a few ms).

## 9. Validation data required, per rule
| Rule | Validates estimator with | Validates false alarms with |
|---|---|---|
| R1 Δ=1.0 grid | RFUAV **31 RC-vendor files** (FlySky/FrSky/RadioMaster/Jumper…) — best untouched asset for this memo; bench ELRS TX at 2 packet rates | 571 ANTSDR ambient windows; a live BLE-dense and Wi-Fi-dense scene |
| R1 Δ=2.0 grid (multi-dwell) | positives campaign: DJI RC uplink, ≥3 dithered dwell centres, idle + video + flight | ambient windows re-run through the same multi-dwell accumulator |
| R2 period | ELRS at declared rates; DJI RC ≈0.5 ms | BLE connection traffic (phone + earbuds) as a labelled negative |
| R3 cadence | RUB and 2026-09-04 DroneID sessions (640 ms, CRC-valid) | ANTSDR ambient (beacon-rich) sessions at session level |
| R4 fixed vs hopping | Zenodo fixed-channel positives; any hopper above | ambient Wi-Fi windows currently mislabelled `fhss_candidate` |

RC-vendor and Zenodo captures are effectively single-emitter/chamber recordings: they validate the **estimator**, not PFA. PFA comes only from the
ANTSDR ambient corpus (Tier D). **False-alarm budget (acceptance)** over the 571 prepared ANTSDR ambient windows: `fhss_1mhz_grid_candidate`
**0/571**; `fhss_2mhz_grid_candidate` **0/571**; `rc_link_family_candidate` **≤1/571**; `droneid_cadence_candidate` **0/571** and 0 at session level
(FA/hour = 0); `hopping_candidate` ≤5 % (level-1, allowed to fire). Any exceedance blocks the merge.

## 10. Builder tasks (3, bounded)
**T1 — `aerix_rf/detect/bursts.py` (new).** From D8 frames emit `BurstEvent(t_start_s, dur_s, f_centre_hz_abs, occ_bw_hz, peak_snr_db, flat_top)`
using the −6 dB edge midpoint; optional 33.3 µs refinement for ≤16 gated bursts; capped count; pure function, no I/O. *Acceptance:* synthetic tone
and 2 MHz-wide bursts at known centres recover centre within **σ_f ≤ 60 kHz** and duration within one frame; a fixed-channel Wi-Fi-like burst train
with varying in-band shape gives centre std < 0.25·BW — assert the centroid estimator fails this and the edge-midpoint passes.

**T2 — `aerix_rf/detect/raster.py` (new).** Clustering, Rayleigh raster test (debias + alias rule), Rayleigh period test, non-UAS discount table;
pure functions over a `BurstEvent` list. *Acceptance:* (i) synthetic ELRS-like hopper on the exact 2400.4 + k·1.000 MHz grid at 250 Hz → Δ̂ ±5 kHz,
offset ±50 kHz, M ≥ 10, p < 1.7e-4; at 50 Hz over 1 s it must return `INSUFFICIENT_CHANNELS` and pass over 3 s. (ii) synthetic DJI-RC-like 2 MHz
hopper, 0.5 ms bursts → single dwell `INSUFFICIENT_CHANNELS`, 3 dithered dwells pass. (iii) synthetic BLE data hopper (2 MHz raster, 30 ms interval,
1.25 ms-quantised) → `ble_connection_like`, **no** level-2 RC label. (iv) synthetic Wi-Fi beacons at 102.4 ms + BLE adverts on 3 fixed channels → no
level-2 label, `wifi_beacon_like` present.

**T3 — rewire `aerix_rf/detect/energy.py` + session cadence.** Replace `_hop_spread_mhz`/`fhss_candidate` with §5's vocabulary, consume T1/T2, move
cadence to a session-level burst-event accumulator, emit the structured `raster`/`period`/`consistent_with` fields, update
`aerix_rf/classify/model.py` label handling and the CLI/report fields. *Acceptance:* the §9 false-alarm budget over all 571 ANTSDR ambient windows,
reported per rule, plus existing detector tests green.

Likely files: `aerix_rf/detect/{bursts.py,raster.py,energy.py}`, `aerix_rf/classify/model.py`, `aerix_rf/cli.py`,
`tests/{test_detect.py,test_raster.py}`, `README.md` (limitations paragraph).

## 11. Open evidence gaps (RESEARCH NEEDED → architect → research-librarian)
1. **DJI RC 2.4 GHz uplink hop-set span, channel count and raster offset (mod 2 MHz).** Without the offset, §2(e) cannot separate a DJI RC grid from
   BLE data channels on raster alone.
2. **ExpressLRS FLRC/LoRa air-times per packet rate and RF mode** (primary firmware / SX1280 datasheet) — sets the duration histogram edges by
   measurement instead of inference.
3. **FlySky AFHDS2A channel spacing, channel count, frame rate** — COMMUNITY-grade only today, so no AFHDS2A entry may enter the Δ dictionary yet.
4. **Bluetooth Core spec channel-selection #1/#2 hop-increment behaviour** — is the successive-channel difference a usable extra BLE discriminator?
5. **Real-world Wi-Fi beacon interval distribution** (100 TU nominal; per-vendor deviation sets the ±2 % discount tolerance).


## §R4 revision (2026-09-19) — measured on 1,160 ANTSDR ambient windows

Run 1 (original R4): `hopping_candidate` on 758/1160 windows (65 %) — ambient Wi-Fi bursts (several MHz to
>10 MHz, edge-clipped in the 10 MHz dwell) were clustered as "hops"; `wifi_beacon_like` never fired.
Revision: the hop set is counted over NARROW clusters only (`HOP_MAX_CLUSTER_BW_HZ = 2.5 MHz`, not
edge-clipped); `hopping_candidate` requires ≥5 distinct narrow clusters each revisited (`HOPPING_MIN_M_REPEAT`),
plus whiteness; windows dominated by ≥10 MHz-wide bursts get the informational tag `wifi_like_wideband`; the
beacon discount uses per-cluster intervals with late-only tolerance and ≥3 intervals.
Run 2 (revised): grid 0, `droneid_cadence_candidate` 0, `rc_link_family_candidate` 0, `hopping_candidate` 12
(1.0 %), `fixed_channel_burst_candidate` 205, `wifi_beacon_like` 6, `INSUFFICIENT_CHANNELS` 1160 → §9 budget
MET. Trade-off accepted: a narrow hopper with < 5 channels visible in one dwell (e.g. a DJI-RC-like 2 MHz
raster) is NOT labelled from a single dwell (`INSUFFICIENT_CHANNELS`) — it needs the multi-dwell path.
Reports: `stage1-fa-budget-2026-09-19.md` (run 1), `stage1-fa-budget-2026-09-19-run2.md` (run 2).


**Wording correction (review 2026-09-19):** `INSUFFICIENT_CHANNELS` = 1160/1160 means the FHSS-grid lattice test (and hence `fhss_*_grid_candidate` / `rc_link_family_candidate`) was NEVER ATTEMPTED on this corpus — ambient RF in this room never presents ≥10 narrow burst clusters in a dwell. Read those rows as "grid-candidate false-alarm rate NOT EXERCISED by real ambient data", not as 0/1160 rejections. The exercised, budgeted results are `hopping_candidate` 12/1160 (1.0 %) and `droneid_cadence_candidate` 0/1160. Measured Stage-1 cost ≈210 ms per 1 s window (12.288 MS/s).
