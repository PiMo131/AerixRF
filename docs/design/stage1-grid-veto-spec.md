# Stage-1 grid veto (C4 gate item (ii) fix) — builder-ready spec

Status: DESIGN, 2026-09-19. Target branch: `wip/stage1-c4`. Evidence level of everything below:
level 1–2 on a **public X310 corpus** (RFUAV), no operator truth, no decode. Nothing here asserts
identity; the veto only removes an unsupported level-2 claim.

Defect (ground truth: `docs/design/stage1-level2-alignment-2026-09-19.md`, summarised in
`stage1-rc-positives-2026-09-19.md` "Gate (ii) result"): `fhss_1mhz_grid_candidate` fires with
r = 0.95–0.99 / M = 32–65 on SIYI MK15, WFLY ET10, WFLY ET16S (partially Radiolink AT9S Pro)
windows that contain **no narrowband hop comb** — one always-on carrier plus a diffuse
19–74 MHz, 3–10 %-duty occupant. `rc_link_family_candidate` is genuine on 4/5 models and must
survive. The defect is in the lattice path (`raster.raster_test` / `cluster_centres` admission /
`analyze_raster`), not in the C4 per-bin floor.

## S1. Why near-floor scatter inside a wide occupant produces a high lattice r

1. **The C4 per-bin floor dissolves the occupant into speckle.** Inside a continuously occupied
   band the per-bin floor tracks the occupant's own PSD, so the occupant surfaces not as one
   ≥ 8 MHz event but as many 0.3–1.2 MHz local maxima (OFDM ripple + modulation speckle) plus
   carrier skirt. Each gets a `-6 dB` edge-midpoint "centre" that is a threshold artefact.
2. **The existing occupancy mask cannot see it.** `wideband_occupancy_spans()` anchors spans on
   *events* with `bw_6db_hz ≥ WIDEBAND_SPAN_MIN_BW_HZ` (2.5 MHz). Under the per-bin floor those
   anchor events no longer exist, so `spans == []` and `is_occupancy_masked()` in
   `cluster_centres` (raster.py:461) is a no-op exactly in the case it was written for. The
   occupancy evidence that *does* survive is per-event `floor_occupied_span_hz` (pre-clamp
   contiguous occupied run, `bursts._occupied_span_hz`) — currently only consumed by
   `is_unresolved_fragment`, and only in conjunction with `bw_noise_limited AND bw < 300 kHz`,
   which the 0.3–1.2 MHz speckle maxima escape.
3. **The statistic is not protected by its own p-value.** `_p_false_corrected(M, r, n_trials)`
   = `min(1, n_trials·exp(-M r²))` with `n_trials = 6 + 570 = 576`. At M = 32, r = 0.99 it
   returns ≈ 1e-11; at M = 65, r = 0.95, ≈ 1e-23. **No Bonferroni factor of any plausible size
   can veto this**, because the rejected null ("cluster centres i.i.d. uniform") is not the
   alternative that matters. The clustering step imposes a hard-core minimum separation
   (`max(100 kHz, 0.75·BW)`, capped) and the speckle correlation length imposes a characteristic
   pitch, so the centres are a repulsive point process with a preferred spacing *by
   construction*. M is also not the number of independent phase draws: several clusters inside
   one clump contribute nearly the same phase, so the true effective n is the clump count, and
   `exp(-M r²)` overstates the evidence in the exponent.
4. **The debias is one-sided.** `r_debiased = min(1, r·min(1.15, 1/exp(-2π²σ_f²/Δ²)))` can only
   *raise* r; it can never flag the physical contradiction it is derived from. Note the implied
   budget: r = 0.99 at Δ = 1 MHz requires centre RMS error ≤ 22.6 kHz, r = 0.95 ≤ 51 kHz — far
   tighter than an edge-midpoint estimate from a near-floor burst measured through a 300 kHz T1
   smoothing kernel at 24.4 kHz bins can plausibly be. An r that tight, with members this weak,
   is evidence of a **deterministic comb** (receiver spurs / a standing structure), not of a hop
   set. `_p_false` is doing its job for its own null; the null is the wrong one.

Open hypothesis worth one offline check (not a runtime gate): the exact 1.000 MHz / r ≈ 0.99
result across unrelated models smells like an X310 **reference-spur comb** at 1 MHz PFD spacing,
i.e. an instrumentation artefact of the corpus. Test: is `offset_hz mod 1 MHz` the same across
models and present in signal-free windows of the same recordings? If yes, it is receiver-borne.

## S2. Member admission for the lattice (new, R1 pre-filter)

Build an **admitted member set** before `raster_test`. Clusters keep their existing construction
(C3 bounds unchanged); admission only decides which clusters may vote in the lattice and in the
new label gate. All thresholds configurable module constants.

A cluster is **admitted** iff all hold:

* `GRID_MEMBER_MIN_BURSTS = 3` bursts, and `GRID_MEMBER_MIN_RATE_HZ = 2.0` bursts/s over the
  analysed span (a 16-channel, 250 Hz link gives ~15 bursts/s/channel; a 50 Hz link ~3 — both
  pass; the ground-truth contaminant "channels" sit at < 1 % duty with 1–2 crossings).
* median member `peak_db_over_floor ≥ GRID_MEMBER_MIN_PEAK_DB = 9.0` (= `bursts.EDGE_DB` + 3 dB
  margin) **and** no member with `bw_noise_limited` in the majority: below `EDGE_DB` over the
  hold threshold the −6 dB width and hence the centre are not measurable at all.
* not an unresolved fragment (`is_unresolved_fragment`, unchanged, fail-open on unknown).
* **not inside a concurrent wide occupant**: re-anchor occupancy on the floor measurement, not on
  event width — `GRID_VETO_OCCUPANT_MIN_SPAN_HZ = 8.0e6`; a cluster is excluded if the median
  `floor_occupied_span_hz` of its members ≥ 8 MHz, or if its centre lies inside a merged span
  built from members with `floor_occupied_span_hz ≥ 8 MHz` that is concurrent with ≥ 50 % of the
  cluster's bursts. (New helper `floor_occupancy_spans(events, min_span_hz)`; keep
  `wideband_occupancy_spans` as-is for R4.)
* **not in the skirt of a near-CW carrier**: any cluster whose active fraction of the window
  ≥ `GRID_CARRIER_DUTY = 0.9` is a standing carrier, not a hop channel; exclude it and every
  cluster whose centre is within `max(1.5 · carrier bw_6db_hz, GRID_CARRIER_GUARD_HZ = 1.0e6)`
  of it (LO/AGC/IMD skirt and regrowth).

Admission is **masking, not refutation** — the wording used for `is_occupancy_masked` applies
verbatim: a real hopper transmitting under a Wi-Fi/video occupant is masked, and the remedy is
multi-dwell on a quieter centre, not a lower threshold.

## S3. Minimum-evidence rule for the level-2 grid label

Let `A` = admitted clusters, `Δ̂` = winning spacing from `raster_test` run **on A's centres only**.
Emit `fhss_1mhz_grid_candidate` / `fhss_2mhz_grid_candidate` only if all hold:

1. `len(A) ≥ GRID_M_MIN_ADMITTED = 8` (M_MIN_RASTER stays 10 for the diagnostic r computed over
   all clusters; the label needs 8 *admitted*, each already ≥ 3 bursts).
2. admitted centre span ≥ `GRID_MIN_SPAN_DELTAS = 6` × Δ̂ (mod-Δ concentration inside a clump
   narrower than a few Δ is trivial and carries no lattice information).
3. lattice occupancy ≥ `GRID_MIN_LATTICE_FILL = 0.20` — admitted channels / integer lattice
   positions between the lowest and highest admitted centre.
4. lattice energy explanation ≥ `GRID_MIN_ENERGY_EXPLAINED = 0.60` — Σ burst energy of admitted
   narrow bursts within `±0.15·Δ̂` of a lattice position / Σ energy of all admitted narrow bursts
   (energy proxy: `10^(mean_db_over_floor/10) · duration_s · bw_6db_hz`).
5. `_p_false_corrected` recomputed with `n = len(A)` (not all-cluster M) and the existing 576
   trial count.

Failure modes of the gate:
* (1) or (2) fails → existing `INSUFFICIENT_CHANNELS` (an unknown, not a "no").
* (3), (4) or (5) fails, **or** ≥ 50 % of the pre-admission clusters were removed by the
  occupant/carrier-skirt rules → new tag **`GRID_CONTAMINATION_SUSPECTED`** added to `TAG_VOCAB`,
  with a note naming which rule fired and the removed-cluster count. Tag, never a label; it means
  "a lattice was found, but its members are not measurable independent channels".
* Also always emit a diagnostic note when `r > 1.15 · exp(-2π²σ_f²/Δ̂²)` with σ_f measured from
  repeat clusters: the members' own centre jitter contradicts the lattice tightness (S1.4).

## S4. Robustness of r (Skydroid 0.0 vs 0.989)

`r = 0.0` on the Skydroid T10 1–2 s window is **not a failed fit**: it is the `insufficient`
sentinel returned when `m < m_min` (`RasterEvidence(None, None, m, 0.0, 0.0, 1.0, …)`). The
neighbouring window crossed 10 clusters and scored 0.989 on the same physical structure. The
instability is therefore in **cluster count**, which is density-dependent (single-linkage chaining
vs the 5 MHz span cap), not in the Rayleigh estimator. Fixes:

* never report `rayleigh_r = 0.0` as a statistic — set it to `None` when `insufficient` is true,
  so bench/GT tooling cannot read "not attempted" as "no lattice" (this is the whole reason the
  GT pass saw r behaving randomly in both directions);
* report `n_clusters_raw`, `n_admitted`, `n_removed_by_rule` in `RasterEvidence`/`as_dict()`;
* the free-Δ step (10 kHz) is already matched to Δ²/W at Δ = 1 MHz, W = 100 MHz — do **not**
  change the offset/Δ resolution; it is not the problem.

Must NOT change: C1 period estimator (median-anchored t̂, range-top rejection, frame-pitch
guard), C2/C3 cluster merge cap and span cap, C5 G1/G2 guard semantics ("insufficient
resolution, not a negative result"), fail-open on unknown `floor_occupied_span_hz`, the
`rc_link_family_candidate` path (R4 hopping + R2 period), and the vendor-token discipline.

## S5. Acceptance

On the 40 RFUAV level-2 windows (`bench/stage1_rc_positives.py`):
* `fhss_1mhz_grid_candidate` must disappear on **SIYI MK15 (1), WFLY ET10 (9), WFLY ET16S (8)**
  — 18/20 of that label's fires — replaced by `GRID_CONTAMINATION_SUSPECTED` or
  `INSUFFICIENT_CHANNELS`; Radiolink AT9S Pro (2) may go either way but must be reported.
* `rc_link_family_candidate` retained on FLYSKY_FS_I6X, FLYSKY_NV_14, JR_PROPO_XG7, SKYDROID_T10
  (19/20 windows); the single marginal FUTABA_T18SZ window may drop without failing the gate.
* Ambient FA budget unchanged: level-2 count stays 0 (`bench/stage1_fa_budget.py`).

Tests (`tests/test_detect_raster.py` unless noted):
1. `test_grid_veto_speckle_inside_wideband_occupant_no_grid_label` — synthetic: 1 CW carrier +
   40 near-floor 0.6 MHz maxima on an exact 1 MHz comb, each with `floor_occupied_span_hz` 20 MHz
   → no grid label, `GRID_CONTAMINATION_SUSPECTED` present.
2. `test_grid_veto_genuine_1mhz_hopper_still_labelled` — the existing ELRS 250 Hz/1 s fixture
   keeps `fhss_1mhz_grid_candidate` (regression on `test_elrs_1mhz_grid_decidable_at_250hz`).
3. `test_grid_veto_carrier_skirt_clusters_excluded` — duty-1.0 carrier + skirt clusters within
   1 MHz are dropped from the admitted set.
4. `test_grid_veto_weak_members_rejected_below_peak_floor` — identical lattice at 7 dB vs 12 dB
   peak-over-floor: only the 12 dB case labels.
5. `test_grid_veto_energy_explanation_and_fill_rules` — lattice fill < 0.20 and explained
   energy < 0.60 each independently withhold the label.
6. `test_raster_insufficient_reports_none_not_zero_r` — `insufficient` ⇒ `rayleigh_r is None`,
   `INSUFFICIENT_CHANNELS` tag, no grid label (Skydroid bimodality).
7. `test_tag_vocab_contains_grid_contamination_suspected` — vocabulary assertion.
8. `tests/test_stage1_rc_positives.py::test_level2_grid_label_absent_on_contaminated_models` —
   corpus-level acceptance for S5 bullet 1.

Files likely touched: `aerix_rf/detect/raster.py` (admission helpers, `raster_test` signature,
`analyze_raster` gate, `TAG_VOCAB`, `RasterEvidence` fields), `tests/test_detect_raster.py`,
`tests/test_stage1_rc_positives.py`, `bench/stage1_rc_positives.py` (report the new tag/columns),
`docs/design/stage1-link-signatures.md` + `docs/design/stage1-c4-c5-spec.md` (record the veto),
`docs/design/stage1-rc-positives-2026-09-19.md` (gate (ii) resolution). `aerix_rf/detect/bursts.py`
only if `floor_occupied_span_hz` needs to be populated on a path that currently leaves it 0.0;
`aerix_rf/detect/energy.py` unchanged unless the tag must reach the pipeline record.

Cost: admission is O(events) plus one merged-span pass — negligible next to the STFT.

## S6. Open evidence gaps

* Whether the exact 1.000 MHz comb is receiver-borne (X310 spur) or emitter-borne is unresolved;
  needs the S1 invariance check on signal-free windows of the same recordings.
* No corpus source for SIYI MK15 / WFLY ET10 / ET16S air interfaces. **RESEARCH NEEDED:**
  primary or vendor documentation on SIYI MK15 and WFLY ET10/ET16S RF link type (COFDM
  video+control vs narrowband FHSS), occupied bandwidth and channel plan — route to
  `research-librarian`.
* Admission thresholds (3 bursts, 2 bursts/s, 9 dB) are derived from this corpus plus first
  principles; they need one ambient re-run and, eventually, operator-truth captures.
