# AERIX RF — engineering backlog (architect-maintained)

Small, approved-in-principle items discovered during work. Each needs a bounded builder task
and independent review before it is "done". Evidence-wording rules apply.

## Decoder / protocol
- [x] (done 2026-09-18, pending review) Blocker-robustness fix — zc6-ranked centre selection + gated refinement:
      bench n=60 → B_wb_blocker/CW arms all at the 6 dB floor (were 15.4/11.4/8.4), clean unchanged, 135 ms/window.
      Blocker-robustness fix (failure split shows hypothesis SELECTION is the cause: forced true centre decodes 119/120):
      an attempted ZC4-only ±100 kHz refinement REGRESSED real-IQ decodes and was reverted 2026-09-18. Re-attempt only
      with a reliable local-search scorer (actual zc6/demod score, STO search), keep "break only on level ≥ B" and
      a 60 kHz DC-fallback dedup; acceptance = RUB golden identical + `B_wb_blocker` knee ≤ 12 dB. Route via rf-dsp-specialist.
- [ ] Unreproduced one-off failure (2026-09-18) of `test_twelve_mhz_band_not_droneid_shaped` +
      `test_centre_hypotheses_band_peel` during a full-file run that overlapped a concurrent edit of the
      test file; 35 reruns × 16 seeds green, assertions hold with >1 MHz margin. Diagnostic messages added.
      If it recurs: capture system load + FFT thread count in situ.
- [x] (done 2026-09-18) Wideband adjacent blocker (+20 dB, 4.5–8.5 MHz) knee was 15.4 dB vs target ≤12 dB — filter transition
      band overlaps the blocker; `_grow_band` still grows through adjacent bands. Follow-up DSP tuning.
- [ ] Widen `bench/canonical_rate_sweep.py` default SNR floor below 6 dB: true clean knee is now ≈2.8 dB in-band.
- [ ] Document the two SNR conventions: `decode/_synth.make_encoded_burst(snr_db)` = full-band AWGN over Fs;
      `bench/canonical_rate_sweep.py` = in-band over the 9.015 MHz occupied band (≈2.3 dB more favourable at
      15.36 MS/s). All quoted decode thresholds (knee ≤6–9 dB) are IN-BAND. Add a docstring + helper to convert.
- [ ] `tests/test_decode.py` budget-sensitive tests (two_bursts_10db, off_centre_under_stronger_ambient)
      fail under CPU contention (load ≈ 14 while a bench ran; pass in 2.7 s idle). Make them
      independent of wall-clock budget (`budget_s=None` or generous) so CI/parallel work is stable.
- [ ] Surface `product_type`, `uuid`, `gps_time`, state bits on `DroneIdResult` (currently only on
      `frame.DroneIdFrame`) so the RUB golden fixture can pin them. (found 2026-09-18)
- [ ] Post-CRC semantic checks as **evidence-quality labels, not filters**: coordinate range,
      exact-zero coords = "no GPS lock", gps_time plausibility, product_type known, sequence
      monotonic within a track. Log, never drop CRC24A-valid frames. (rf-protocol-analyst)
- [ ] `frame.py`: comment that RUB names offsets 31/33 altitude/height while we (proto17) name them
      height/altitude — offsets identical, labels swapped.
- [ ] **Screening weakness (confirmed, synthetic):** `decode/droneid.py::burst_spectrum` anchors the
      occupied-band search at `argmax(psd)`; a *continuous* in-window emitter stronger than the drone
      (CW +30 dB at 6 MHz, or +20 dB adjacent-channel OFDM-like noise) makes `droneid_shaped=False`
      and mis-centres the mix → 0 % decode up to 16 dB SNR. Time-disjoint bursts (field Wi-Fi/RC)
      are unaffected. Fix: screen several spectral peaks / excise spurs before measuring occupied
      bandwidth. Bounded builder task + bench arms `B_wb_blocker` as acceptance.
- [ ] Bench `canonical_rate_sweep.py`: seeds from `hash((label,snr,trial))` are not reproducible across
      processes — use a stable hash so arms are paired and runs reproducible.
- [ ] Owed evidence: replay the 2026-09-04 HackRF golden session natively (20 MS/s) and resampled to
      canonical 15.36 — must yield identical CRC-valid frames. **Session is not on this machine.**

## Non-DJI (approved 2026-09-19)
- [x] SiK/MAVLink passive chain built (T1–T4, synthetic level 1, 194 tests); NEXT: a real SiK recording (field, user) to
      reach level 3/4; `detect_bursts` −6 dB edge-midpoint centre is biased ~−54 kHz on bimodal FSK spectra — the SiK
      pipeline applies a centroid refinement; consider the same refinement option in Stage-1 for narrow FSK hops.
- [ ] SiK/MAVLink passive telemetry decoder (GFSK demod + SiK framing + MAVLink parse) — design brief first; zero public IQ,
      needs a recorded capture (no transmit by us).
- [ ] Analog FPV: Zenodo 19870020 chunk10 = 3 sweeps at 1240 MHz / 25 mW (1.2 GHz analog video) → validates FM-video shape
      + dwell confirmation, NOT the 5.8 GHz grid; another chunk (hundreds of GB) needed for 5.8 GHz — user approval.
- [ ] Analog FPV (old note): validate the detector on Zenodo 19870020 chunk10 (real VTX IQ, HackRF 20 MS/s, `vtx_power_mw`); use its
      25/600 mW rows to set the shape-ratio/BW expectations; consider more chunks (4.2 TB total) only with user approval.
- [ ] Analog 5.8 GHz FPV carrier-grid detector on sweeps (F/Raceband grids); video content demod approved for research.
- [ ] Wi-Fi drones: RF-level detection only in AERIX RF; frame parsing → ESP32 system.
- [ ] ExpressLRS raster/period validation on real IQ (RFUAV RC set or field recording).

## Classifier / datasets
- [ ] DroneRFb-DIR downloaded+verified (63 GB, sha256 in manifest) but is a SPLIT zip set (`twin_droneRF.zip` + `.z01–.z31`):
      recombine with `zip -s 0 … --out combined.zip` (~63 GB extra), inspect the inner layout, then write the adapter
      (RF fingerprinting: 6 types × 3 individuals per the dataset brief).
- [ ] G6 spectral floor: measured exact at ≤7 MHz continuous (70 %), collapses abruptly at 8 MHz (occ 0.70→0.32,
      level 25→11.8 dB, tilt-invariance lost). Analog FPV (6–8 MHz) straddles the edge ⇒ G6 readouts for FPV are
      morphology-only. Fix options: adaptive quiet-bin fraction, occupancy-aware fallback, or wider dwell. (tests in
      `tests/test_features_v2.py::test_g6_fpv_*`)
- [x] (Fable) Rename the current benchmark output a *pipeline-integrity check*; run the M2 synthetic at 8 MHz continuous
      (analog FPV 6–8 MHz in a 10 MHz dwell = 60–80 % occupancy, at the spectral-floor limit). Frame analog FPV as an
      emitter class (stage 1–2), never protocol evidence.
- [ ] (Fable) Same-receiver positives protocol needs controls: ≥3 distances; RC/phone ON with aircraft OFF (confuser);
      Wi-Fi co-channel active during ON; per-window clip fraction + drop estimate logged.
- [ ] Tier-D outlier session `a_iq_default` (quiet band, raised+flattened floor): live read-back shows LO/gain/mode
      correct and the afternoon soak sees intermediate Wi-Fi load ⇒ ambient traffic varies by hour (scene), but
      the floor-shape change is unexplained. Hypothesis: the "U-shaped" floor of Wi-Fi-saturated sessions is
      Wi-Fi-induced (p10-over-time absorbs persistent Wi-Fi), not the receiver's. Resolve with read-back state
      recorded per session and an ON/OFF-scheduled capture. Until then: never mix sessions across hours as one
      "background" group without a session-level receiver-state table.
- [ ] (progress 2026-09-18: 2.4 → 1.21 s at 12.288 MS/s, 0.65 s at 15.36 after complex64 live resample, larger FFT chunks, cached taps; profiled floor ≈0.3 s without a compiled STFT/power kernel or dropping percentile-heavy groups — architecture decision pending user compute budget)
      Live `features_v2` path costs ≈2.6 s per 1 s window (12.288 MS/s): `features_v2_from_iq` runs two full STFTs
      (`ml_tensor` + unchunked `canonical_stft` for detector frames) and the 5/4 live resample uses the
      4145-tap dataset-grade FIR (~1.1 s). Target ≤150 ms: single STFT feeding both reductions, and a
      short live-grade resampler (or run the canonical STFT at the native rate with bin remapping). Until
      then `AERIX_RF_FEATURES=v1` default; v2 opt-in. (F4, 2026-09-18)
- [x] (done) Dataset folder naming: downloads sit under display names (`RUB-DroneSecurity/`, `ZenodoDroneRFVideo2020/`)
      while `prepare` writes under manifest `dataset_id` (`rub_dronesecurity/`). Decision 2026-09-18: `dataset_id`
      is canonical — librarian to move/symlink `original/` dirs and update `manifests/datasets.json` paths.
- [ ] `classify/train/data.py::_dronerf_label` maps DJI Phantom 3 to `dji_ocusync`; Phantom 3 is
      Lightbridge. The current trained bundle carries this mislabel.
- [ ] DroneRF CSVs are REAL-VALUED amplitude series (librarian, medium-high confidence from secondary
      sources) — cannot enter the complex-IQ canonical path. Design a magnitude-only adapter with its own
      `stage_entry` and exclude DroneRF from IQ-based benchmarks; update `docs/design/dataset-normalization.md`.
- [ ] Zenodo 4264467 is 120 MS/s (2.4 GHz, 1.0 s/file) and 200 MS/s (5.8 GHz, 0.5 s/file) int16 — add
      120→(÷6)→20→96/125 and 200→(÷10)→20→96/125 chains + tests to `datasets/resample.py`; the 0.5 s
      files yield short windows (`short_window` flag).
- [x] Retire duplicate manifest entry `dji_droneid_iq_rub_syssec` in favour of `rub_dronesecurity`.
- [ ] Locate data hosts for CageDroneRF and UAVSig.

## Receiver / sessions
- [ ] Re-record 2.4/5.8 GHz baselines with the fixed stitcher (`usable_frac`/`overlap_hz`/`step_hz` also to be persisted
      into `scan/sweep.py` Baseline meta) and confirm the +7 dB hardware bump is gone (synthetic model reproduced a dip).
- [x] (fixed 2026-09-19, synthetic-verified) `RetuneWelchSweep` stitching leaves a +7 dB comb (4 bins) at every 10 MHz step seam (measured in
      `sweeps_2026_09_18/base_58.npz`) — coincides with the FPV Band-A lattice. Fix: overlap steps and trim/weight
      passband edges; synthetic test: flat noise floor across steps → no seam. Until then FPV detection masks ±0.75 MHz.
- [ ] `producer_main` robustness: live `antsdr_proc` runs DO terminate the producer on completion (verified by process
      listing; an earlier "orphan" was a pgrep self-match plus one stale fake-iio test process). Still add
      `prctl(PR_SET_PDEATHSIG)` + a consumer-heartbeat timeout so a crashed consumer can never leave a producer
      holding the IIO buffer; test by killing the parent.
- [x] (done 2026-09-19, accepted §14.2) **T7 producer process** (from §14.1: in-process GIL contention is THE loss mechanism; OS contention causes none):
      run the libiio producer in its own OS process with a shared-memory ring + per-chunk header; design in
      `docs/design/antsdr-backend.md` (hardware-architect, 2026-09-18). Acceptance: BIST-verified zero gaps with a
      deliberately slow consumer and under pytest-style load.
- [ ] (Fable 2026-09-18) Add `timestamp_quality` and `loss_counter_available` to `ReceiverCapabilities`; multi-receiver
      code must refuse to run where they are absent. Treat the IIO ceiling as this phase's constant, not architectural.
- [ ] (Fable) Event-gated raw retention: cs16 at 12.288 MS/s ≈ 177 GB/h; decide disk/retention budget with user.
- [ ] `samples_deficit` can go negative on a loss-free run (−665 k samples over 60 s ≈ device clock 0.09 %
      fast relative to host wall clock). Decide: keep signed (honest) but document; consider estimating the
      clock offset from the first N seconds and reporting `deficit_vs_measured_rate`. (2026-09-18 live check:
      60 windows, 0 warnings, recent ratio 0.979–0.999, max refill gap 4.2 ms.)
- [x] (done 2026-09-18) `rate_warning` false alarms: rule now requires cumulative < 0.995 after 10 s OR
      (recent < 0.97 AND real deficit growth); all diagnostic health keys persisted in sessions.
- [x] (done 2026-09-18) Device read-back state recorded per session (`receiver_readback`, per-file
      `readback_mismatch`); typed `window_deficit_frac`/`session_deficit_frac` in sidecars.
- [x] (done 2026-09-18) Clean 10-min soak: 600/600 windows, idle host, default buffers, no IQ.
- [ ] `antsdr_iio`: demote the per-50-refill INFO log to DEBUG; `max inter-refill gap` always prints 0.000 s
      (counter bug — should be ≈0.085 s at 1 M-sample buffers). Hardware sweep 2026-09-18: 2.4/5.8 GHz
      baselines finite, live differential scan correct (no candidates in a stable environment).
- [x] (done 2026-09-18) `RetuneWelchSweep.step_hz` fallback uses `capabilities.max_instantaneous_bw_hz` (analog max) — decision
      2026-09-18: derive step from the live source's actual sample rate × usable fraction (ANTSDR default
      10 MHz; sim 20 MS/s → 12 MHz) and cap by capabilities; fix `cli.py` baseline floor print to `nanmedian`.
      Do together with the first hardware `baseline --backend antsdr_iio` run.
- [ ] `capture` has a hardcoded per-session IQ cap (~6 GB; prints "IQ cap … reached" and keeps detecting).
      Expose as `--max-iq-gb` / config and record `iq_capped` + the cap in `session.json`; at cs16 12.288 MS/s
      the cap is hit after ~122 s.
- [ ] E200 IIO buffer is single-client: a second capture evicts the running one silently. Detect the
      refill failure and end the session with an explicit `device_lost` reason in `session.json`.
- [ ] HackRF 15.36 MS/s profile: libhackrf auto-selects a 10 MHz baseband filter at 15.36 MS/s (0.75×rate
      → table step 10). Add ctypes decls for `hackrf_compute_baseband_filter_bw` /
      `hackrf_set_baseband_filter_bandwidth`, call explicitly after `hackrf_set_sample_rate`, expose
      `baseband_filter_bw_hz`, record it in `IQWindow.bandwidth_hz`. See `research/briefs/hackrf.md`.
      Bench-verify with a CW tone when a HackRF is attached (filter corner, `stream_rate_ratio` ≥ 0.99).
- [x] (tail_discarded_samples added) On stream stop, the partially assembled last window is discarded silently (pre-existing, preserved
      by T2). Decision 2026-09-18: keep discarding (sub-window IQ cannot run the 1 s pipeline) but
      expose `tail_discarded_samples` in session health. Revisit for long ANTSDR captures.
- [x] (done 2026-09-18: cs16 requires explicit full scale) `CS16_DEFAULT_FULL_SCALE = 32767.0`: decide whether cs16 should *require* an explicit
      `iq_full_scale` (ANTSDR = 2048) to avoid a silent 24 dB RSSI error.
- [x] Backend-neutral sweep — done 2026-09-18 (T5), hardware-verified 2.4/5.8 GHz baselines + live scan.
- [ ] ADC full-scale confirmation at saturation on the E200 (needs a bench CW source).
- [ ] DroneID dwell schedule for narrow windows: candidate centres 2414.5/2429.5/2444.5/2459.5 MHz
      (+ unresolved others, 5.8 GHz unresolved), ≥2 × 640 ms per dwell. See
      `research/briefs/droneid-channel-raster.md`.

## User-gated
- [ ] Copy the 2026-09-04 field sessions (Mini 3 / Avata) from the field box to this machine
      (`sessions/`, gitignored) — needed for the golden-replay binding and A4 acceptance comparison.
- [ ] `sudo usermod -aG dialout jarvis` (E200 UART console).
- [ ] Firmware path: stay on stock IIO vs SD-card trial of MicroPhase UHD-style firmware.
- [ ] Approve DroneRFa (~570 GB) and RFUAV full (0.3–1.3 TB) downloads; derived-IQ storage cap.
- [ ] IEEE DataPort / Kaggle credentials (see `research/datasets/USER_TODO.md`).

## Stage-1 C4 (parked 2026-09-19)
- [ ] Branch `wip/stage1-c4` holds the per-bin floor / P_fa thresholds / Welch looks / C3b work (710 tests pass,
      independently reviewed PASS-with-conditions) but ambient FA `hopping_candidate` rose 11 -> 199/1160 (17 %).
      NOT on main. Needs: fragment/skirt fix or C6 (frequency-local floor reference), Wi-Fi discounts re-validated
      with corrected bandwidths, ≥20 dB R2 regression test, CPU cost of the default-on second STFT (`iq=` path),
      explicit decision on the R5 cadence-suppression false-negative risk (real RC link inside an active Wi-Fi channel).
- [ ] C5 (grid-resolution guard G1/G2, bench `full_band_4096` column) not started — spec in docs/design/stage1-c4-c5-spec.md.
