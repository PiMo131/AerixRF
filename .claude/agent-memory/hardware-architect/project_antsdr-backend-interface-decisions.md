---
name: antsdr-backend-interface-decisions
description: Rationale behind the ANTSDR backend interface decisions (normalization, sample-rate default, iq_format, shared StreamAssembler, honest None for unknown loss)
metadata:
  type: project
---

Design decisions proposed 2026-09-18 in `docs/design/antsdr-backend.md` (awaiting
architect approval). The reasoning, not the code shape, is what matters here:

1. **`IQWindow.iq` is complex64 normalized to ±1.0 of ADC full scale, always.** Each
   backend declares its own `full_scale` divisor (HackRF 128; AD9361 2048 or 32768
   depending on 12-bit justification — *must be measured*, a wrong guess shifts every
   RSSI by 24 dB silently).

2. **Default ANTSDR rate: 12.288 MS/s** (SUPERSEDED the original 15.36 MS/s proposal,
   2026-09-18). The original reasoning was that 15.36 MHz equals `ofdm.NOMINAL_SAMPLE_RATE`
   so the DroneID decoder stops resampling, and that 20 MS/s (640 Mbit/s cs16) is marginal
   on 1 GbE from a Zynq-7020. Measurement killed it: BIST-tone runs (brief §14) show 15.36
   is **unusable** on this image (ratio 0.503, millions of phase jumps) — it is above the
   iiod ceiling, not merely marginal. 12.288 MS/s is the default (gap-free over 600 s,
   exact 5/4 canonical ratio, integer STFT timing) and 13.44 MS/s is a validated named
   profile. The rate-vs-resampling tradeoff was the right axis; the ceiling was the
   missing fact.

3. **`iq_format` / `iq_full_scale` in `session.json`, defaulting to cs8/128.0 when
   absent.** That default is what keeps every existing HackRF session replayable without
   migration. `Session.open()` does no `schema_version` check, so additive changes are
   safe by construction — preserve that property.

4. **One shared `StreamAssembler` for all live backends.** Health semantics
   (`overflow_count`, `gap_before_samples`, `complete`, `dropped_samples`) must be
   identical across HackRF/UHD/libiio *by construction*, not by code review.

5. **On the libiio path, report `dropped_samples=None`, never a fabricated 0.** libiio
   gives no per-buffer sequence number; inferring loss only from rate drift is weaker
   evidence and the record must say so (`loss_detection="inferred_rate_only"`).

**Why:** these are the five places where a convenient shortcut would quietly corrupt
evidence quality (RSSI, replay, capture health) rather than fail loudly.

**How to apply:** treat these as the defaults to defend in review; any deviation needs an
explicit reason recorded. Related: [[antsdr-primary-receiver]],
[[hackrf-couplings-in-abstraction]].
