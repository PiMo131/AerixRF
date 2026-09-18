# HackRF hardware brief — sample rate / baseband filter facts

Status: verified from `greatscottgadgets/hackrf` firmware+host source (master branch,
fetched 2026-09-18) and https://hackrf.readthedocs.io/en/latest/sampling_rate.html.
Scope: exactly the facts needed to judge the 15.36 MS/s canonical live profile in
`docs/design/canonical-representation.md` D1/D2/D13. No hardware attached to the
research host — source/doc verification only, not bench-measured.

## Sample rate: 15.36 MS/s

`hackrf_set_sample_rate(dev, double freq)` (`host/libhackrf/src/hackrf.c`) does NOT
call a generic rational approximator on every input — it first checks whether `freq`
is (numerically, in double precision) already an integer number of Hz. 15,360,000.0
is exactly representable as a double and has zero fractional part, so the
continued-fraction search short-circuits at `divider = 1`, and it calls
`hackrf_set_sample_rate_manual(dev, 15360000, 1)` directly — i.e. it requests an
**exact** 15,360,000 Hz ADC/DAC clock from firmware, not an approximation of some
other rate. (Contrast: a rate like 15.36001 MS/s would NOT hit this fast path and
would get a rational divider search up to `MAX_N=32`.)

Firmware (`firmware/common/si5351c.c`) then realizes that clock via the Si5351C's
fractional-mode MultiSynth (rational P1/P2/P3 register triplet, not restricted to the
"preferred" integer clocks). The docs list 8/10/12.5/16/20 MHz as the MAX5864's
*lowest-jitter* preferred clocks — other rates including 15.36 MHz use fractional-N
synthesis, which is exact *on average* (locked to the 25 MHz reference) but carries
somewhat more clock jitter/spurs than the preferred integer set. Absolute accuracy is
bounded by the reference TCXO's ppm error (typ. ~20 ppm stock, better with TCXO
upgrades/GPSDO), same as any other rate — 15.36 MS/s is not special here.

**Conclusion:** yes, valid and exactly-requested (15,360,000 Hz, not an approximation
of the requested value); expect ordinary fractional-synthesis jitter, not a distinct
new limitation.

## Baseband filter (MAX2837)

Table (`max2837_ft[]`, `hackrf.c`): 1.75, 2.5, 3.5, 5, 5.5, 6, 7, 8, 9, 10, 12, 14,
15, 20, 24, 28 MHz. 12 MHz **is** a valid discrete step.

`hackrf_set_sample_rate()` / `_manual()` auto-select the filter every time the rate is
set: target = `0.75 * freq_hz / divider`, then `hackrf_compute_baseband_filter_bw()`
picks the **widest table entry ≤ target** (rounds down, never up).

At 15.36 MS/s: target = 0.75 × 15,360,000 = 11,520,000 Hz → auto-picked filter is
**10 MHz**, not 12 MHz (12 MHz > 11.52 MHz target, so it rounds down past it). Any
profile wanting 12 MHz must call `hackrf_set_baseband_filter_bandwidth()` explicitly,
*after* `hackrf_set_sample_rate()`, with `hackrf_compute_baseband_filter_bw(12_000_000)`
(exact match, returns 12,000,000).

12 MHz total filter width = ±6 MHz half-width, inside the ±7.68 MHz Nyquist edge of
15.36 MS/s complex sampling (1.68 MHz guard each side before aliasing) — consistent
with and slightly tighter than the memo's declared ±6 MHz usable band (D3). The
auto-picked 10 MHz (±5 MHz) would risk clipping a 9 MHz DroneID burst offset toward
band edge; 12 MHz explicit is the right call, but it must be set explicitly — current
`libhackrf.py` never calls `hackrf_set_baseband_filter_bandwidth`, so it always runs
on the auto-picked value for whatever rate is configured.

## USB transfer sizing vs 1 s windows

`_TRANSFER_BYTES = 262144` bytes/transfer (this is libhackrf's own hardcoded RX
transfer size, matches firmware's USB buffer). At 15.36 MS/s × 2 B/sample (cs8),
1.000 s = 30,720,000 B, not a multiple of 262144 (30,720,000 / 262144 = 117.19) — same
kind of ragged boundary that already exists at 20 MS/s (40,000,000 / 262144 = 152.6),
so this is not a new condition. No known libhackrf/firmware issue tied specifically to
non-integer-MHz rates or non-aligned window lengths; overflow/short-read accounting in
`_rx_callback` → `StreamAssembler.push` (`aerix_rf/sdr/libhackrf.py`,
`aerix_rf/sdr/stream.py`) is generic per-transfer accounting and doesn't assume any
alignment between transfer size and window size.

## Full scale / RSSI

MAX5864 ADC is 8-bit (native `cs8`, ±128 full scale, matches `_cs8_to_iq` /
`iq_full_scale` in `aerix_rf/sdr/capture.py`); effective bits are lower than 8 once
input-referred noise and gain-chain (LNA 0–40 dB step 8, VGA 0–62 dB step 2, amp fixed
+14 dB) nonlinearity/uncalibrated absolute gain are counted, so `rssi_dbfs` on HackRF
should stay flagged uncalibrated (`calibrated: false`) exactly as the memo's §4/§6
already requires — no HackRF-specific correction needed beyond that existing flag.

## Sources
- https://github.com/greatscottgadgets/hackrf/blob/master/host/libhackrf/src/hackrf.c
  (`hackrf_set_sample_rate`, `hackrf_set_sample_rate_manual`,
  `hackrf_compute_baseband_filter_bw`, `max2837_ft[]`)
- https://github.com/greatscottgadgets/hackrf/blob/master/firmware/common/si5351c.c
  (`si5351c_configure_multisynth`, fractional MS mode)
- https://hackrf.readthedocs.io/en/latest/sampling_rate.html (preferred low-jitter
  clocks 8/10/12.5/16/20 MHz, 1.75 MHz min filter, filter attenuation shape)

## Open items for the architect
- Not bench-verified: actual achieved rate/jitter on a real unit at 15.36 MS/s vs a
  "preferred" rate (8/10/12.5/16/20 MHz); recommend a short `hackrf_transfer` capture
  with a known CW tone and FFT-measured frequency error/spur floor before freezing D1
  on real hardware.
- HackRF One vs HackRF Pro: this brief is written against the shared libhackrf/
  firmware source, which both device variants use identically for sample-rate/filter
  control; no HackRF-variant-specific difference found for this question. If the repo
  later needs Pro-specific features (e.g. wider tuning range, bias-tee differences),
  confirm which physical unit is on hand before assuming parity — not yet resolved in
  this brief.
