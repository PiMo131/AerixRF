---
name: antsdr-backend-interface-decisions
description: Rationale behind the proposed ANTSDR backend interface decisions (normalization, 15.36 MS/s default, iq_format, shared StreamAssembler, honest None for unknown loss)
metadata:
  type: project
---

Design decisions proposed 2026-09-18 in `docs/design/antsdr-backend.md` (awaiting
architect approval). The reasoning, not the code shape, is what matters here:

1. **`IQWindow.iq` is complex64 normalized to ±1.0 of ADC full scale, always.** Each
   backend declares its own `full_scale` divisor (HackRF 128; AD9361 2048 or 32768
   depending on 12-bit justification — *must be measured*, a wrong guess shifts every
   RSSI by 24 dB silently).

2. **Default ANTSDR rate 15.36 MS/s, not 20 MS/s.** Two reasons that reinforce each
   other: 16-bit IQ at 20 MS/s is 640 Mbit/s, marginal on 1 GbE from a Zynq-7020; and
   15.36 MHz is exactly `ofdm.NOMINAL_SAMPLE_RATE`, so the DroneID decoder stops
   resampling. 20 MS/s stays selectable purely for parity with the HackRF golden session.

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
