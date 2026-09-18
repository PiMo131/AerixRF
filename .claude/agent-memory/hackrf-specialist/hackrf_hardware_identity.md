---
name: hackrf-hardware-identity
description: Tracking note on HackRF One vs HackRF Pro ambiguity in this repo — not yet resolved which physical unit is used for field tests
metadata:
  type: project
---

The repo/docs refer to "HackRF" generically (sometimes "HackRF One"); a "HackRF Pro"
has not been confirmed as the field unit as of 2026-09-18. libhackrf/firmware source
for sample-rate and baseband-filter control (`hackrf_set_sample_rate`,
`hackrf_compute_baseband_filter_bw`, MAX2837 filter table) is shared code used
identically by both variants as of the current `greatscottgadgets/hackrf` master
branch, so findings in [[hackrf-samplerate-filter-facts]] apply to either. Differences
that WOULD matter (tuning range extension, bias-tee, PortaPack compat, USB3 vs USB2,
enclosure/RF front-end changes) have not been checked and should not be assumed equal
across variants. Ask the architect which exact unit is the field-test device before
relying on any Pro-specific claim.
