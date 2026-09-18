---
name: hackrf-samplerate-filter-facts
description: Verified libhackrf/firmware facts on sample-rate exactness and baseband filter auto-selection, esp. for the 15.36 MS/s canonical profile
metadata:
  type: project
---

Durable device facts (source-verified 2026-09-18, `greatscottgadgets/hackrf` master):

- `hackrf_set_sample_rate(dev, double freq)`: if `freq` is exactly integer Hz in
  double precision (e.g. 15,360,000.0), it short-circuits to `divider=1` and requests
  that exact Hz value via `hackrf_set_sample_rate_manual` — not an approximation.
  Non-integer-Hz requests go through a continued-fraction search (`MAX_N=32`).
- Si5351C realizes any rate via fractional-mode MultiSynth (rational P1/P2/P3); only
  8/10/12.5/16/20 MHz are the MAX5864's *lowest-jitter preferred* clocks per GSG docs
  — other rates (incl. 15.36 MHz) work but are not specially called out as low-jitter.
- Baseband filter table (`max2837_ft[]`): 1.75/2.5/3.5/5/5.5/6/7/8/9/10/12/14/15/20/24/28 MHz.
  Auto-selection on every `hackrf_set_sample_rate*` call: target = `0.75*rate`, picks
  **widest table entry ≤ target (rounds down)**. At 15.36 MS/s target=11.52 MHz →
  auto-picks **10 MHz, not 12 MHz**. 12 MHz needs an explicit
  `hackrf_set_baseband_filter_bandwidth(dev, hackrf_compute_baseband_filter_bw(12_000_000))`
  call *after* `hackrf_set_sample_rate`. `aerix_rf/sdr/libhackrf.py` currently never
  calls this — it always runs on the rate-driven auto-picked filter.
- `_TRANSFER_BYTES=262144` (libhackrf RX transfer size) not being a divisor of a 1 s
  window's byte count is normal at every HackRF rate (also true at legacy 20 MS/s),
  not a 15.36-specific issue. `StreamAssembler` (`aerix_rf/sdr/stream.py`) handles this
  generically; no known driver-side bug tied to non-integer-MHz rates.
- MAX5864 ADC is 8-bit nominal (cs8, ±128); effective bits lower once
  noise/gain-chain (LNA/VGA/amp) uncalibrated gain is counted — HackRF `rssi_dbfs`
  should always be `calibrated: false`.

Full writeup: `research/briefs/hackrf.md`. See [[hackrf-hardware-identity]] for the
One-vs-Pro ambiguity tracking note.
