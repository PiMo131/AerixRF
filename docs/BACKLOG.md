# AERIX RF — engineering backlog (architect-maintained)

Small, approved-in-principle items discovered during work. Each needs a bounded builder task
and independent review before it is "done". Evidence-wording rules apply.

## Decoder / protocol
- [ ] Unreproduced one-off failure (2026-09-18) of `test_twelve_mhz_band_not_droneid_shaped` +
      `test_centre_hypotheses_band_peel` during a full-file run that overlapped a concurrent edit of the
      test file; 35 reruns × 16 seeds green, assertions hold with >1 MHz margin. Diagnostic messages added.
      If it recurs: capture system load + FFT thread count in situ.
- [ ] Wideband adjacent blocker (+20 dB, 4.5–8.5 MHz) knee is 15.4 dB vs target ≤12 dB — filter transition
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

## Classifier / datasets
- [ ] Dataset folder naming: downloads sit under display names (`RUB-DroneSecurity/`, `ZenodoDroneRFVideo2020/`)
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
- [ ] Retire duplicate manifest entry `dji_droneid_iq_rub_syssec` in favour of `rub_dronesecurity`.
- [ ] Locate data hosts for CageDroneRF and UAVSig.

## Receiver / sessions
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
- [ ] On stream stop, the partially assembled last window is discarded silently (pre-existing, preserved
      by T2). Decision 2026-09-18: keep discarding (sub-window IQ cannot run the 1 s pipeline) but
      expose `tail_discarded_samples` in session health. Revisit for long ANTSDR captures.
- [ ] `CS16_DEFAULT_FULL_SCALE = 32767.0`: decide whether cs16 should *require* an explicit
      `iq_full_scale` (ANTSDR = 2048) to avoid a silent 24 dB RSSI error.
- [ ] Backend-neutral sweep (`scan`/`baseline` currently shell out to `hackrf_sweep`) — design task T5.
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
