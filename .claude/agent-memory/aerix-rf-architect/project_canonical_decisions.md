---
name: canonical-representation-decisions
description: Frozen 2026-09-18 — canonical 15.36 MS/s/1 s/FFT-1024 representation; ANTSDR-IIO live 12.288 MS/s cs16 fs2048 rf_bw 10 MHz; true DroneID decode knee 8-9 dB in-band SNR; features over common 10 MHz band.
metadata:
  type: project
---

Canonical representation (docs/design/canonical-representation.md): 15.36 MS/s, 1.000 s windows, STFT 1024/Hann/hop 512 coherent-gain-normalised, absolute dBFS stored, ML tensor [1000×1024]. ANTSDR-IIO live profile: **12.288 MS/s, rf_bandwidth 10.0 MHz, cs16 with iq_full_scale 2048, manual gain, stream_rate_ratio monitor flags <0.999** (13.44 and 11.52 exist as named profiles). HackRF stays cs8; legacy 20 MS/s sessions are never rewritten (96/125 resample on ingest). Classifier features over the HackRF∩ANTSDR usable band (10 MHz), absolute-Hz axis.

**Why:** Measured iiod ceiling ≈ 59 MB/s with silent loss; synthetic bench (n=200, corrected SNR50-final metric) shows the DroneID decode knee at 8–9 dB in-band SNR for all rates, with narrower windows marginally more sensitive — so rate is a coverage/throughput-margin decision, not sensitivity. Earlier "SNR50 ≈ 3 dB" figures were a metric artefact (first crossing of a non-monotonic curve).

**Fable review 2026-09-18:** canonical 15.36 / live 12.288 / cs16 / 10 MHz common feature band / probe-as-control are CLOSED — do not reopen or re-ask the user. Open traps: silent loss (measure with AD9361 BIST PRBS), clipping under manual gain (record clip fraction), A4 depends on aircraft generation (O2 needed), decoder failure split (detection vs sync) before redesign, analog FPV at the spectral-floor limit.

**How to apply:** Do not reopen the rate debate without new hardware measurements. cs8 vs cs16 was NOT decided by SNR (indistinguishable at 10 dB back-off) but by 12-bit headroom against in-window blockers. Evidence level: synthetic; golden-session binding still owed (session not on this machine). See [[e200-measured-facts]].
