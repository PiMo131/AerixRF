---
name: e200-measured-facts
description: ANTSDR E200 as measured 2026-09-18 — IIO Pluto-compatible firmware, single RX, ~59 MB/s (~14.8 MS/s) sustained ceiling on iiod path, no overflow counter, no timestamps; 2R2T unlockable via U-Boot env.
metadata:
  type: project
---

E200 at `ip:192.168.1.10` (host 192.168.1.20 via nmcli profile `antsdr-e200-static`). Firmware: PlutoSDR-compatible IIO image `v0.34-dirty` (2023), self-reports "PlutoSDR Rev.C Z7010-AD9364" but hardware is XC7Z020 + 2R2T AD9361-class. Only ONE RX exposed (`cf-ad9361-lpc` voltage0/1, `le:S12/16>>0`, full scale ±2048 DOCUMENTED not measured). MEASURED sustained RX ceiling ≈ 57–60 MB/s ≈ 14.8 MS/s complex int16, identical via Python bindings and C `iio_readdev` ⇒ device-side (iiod/ARM/TCP), not host. 5/10 MS/s clean; 15.36 at 0.94–0.98 (silent loss); 20/30 unusable. No overflow/xflow counter; `samples_pps` ENODEV ⇒ no device timestamps today — ANTSDR does not beat HackRF on timing yet. 2R2T unlock = persistent `fw_setenv compatible ad9361 / mode 2r2t` (NOT done; needs user approval). MicroPhase also ships UHD-compatible firmware (FPGA-side streaming) — candidate for higher rates + timestamps; unevaluated. Third-party `alphafox02/antsdr_dji_droneid` firmware exists — unevaluated.

BIST tone test 2026-09-18 (AD9361 `bist_tone` debug attr, 600 s, production-like 8×1M buffering, idle host): 12.288 MS/s → 7,031 buffers, **0 gaps** (no phase jumps, none at buffer boundaries), ratio 0.99989. 13.44 MS/s idle: 7,690 buffers, 0 gaps (validated profile). 15.36 idle: ratio 0.50, 2.1 M jumps (broken). 12.288 under IN-PROCESS GIL contention: ratio 0.41, 8.8 M mid-buffer jumps (catastrophic); genuine multi-core OS contention unmeasured (earlier pytest-load soak: ≈5 %). See brief §14. 12.288 stays default; 13.44 is a validated alternative; OS-level contention (12 separate busy processes, nice 0) causes ZERO loss (§14.1); the mechanism is in-process GIL sharing between the libiio producer thread and the DSP consumer ⇒ architectural fix = producer in its own OS process (shared-memory ring); host-load rule stays as prudence only.

T7 ACCEPTED 2026-09-19: `antsdr_proc` (producer in its own process + shm ring) — 2×600 s BIST runs, idle and under pytest load, 0 phase jumps in 7.37 G samples each, host loss 0. Use `--backend antsdr_proc` for all future ANTSDR captures. Reminder: always verify `bist_tone`=0 after any BIST work (an agent died before its reset once).

UHD-MODE (SD trial 2026-09-19, MicroPhase antsdr_uhd v1.0 + fork host build): 2 RX channels, per-packet timestamps, overflow reporting; 15.36 MS/s sc16 and 20 MS/s sc8 clean over 30 s with default 212 KB socket buffers; 20 sc16 overflows (host buffer; needs sysctl rmem_max). Brief §15. Host fork env: `source ~/rf-tools/uhd-antsdr/ENV.sh`, bench script in session scratchpad `uhd_rx_bench.py`.

**Why:** These numbers drove the canonical-rate decision (must be ≤ ~14 MS/s on IIO path) and the firmware question.

**How to apply:** Re-measure if firmware or libiio version changes. Any claim of "ANTSDR 20 MS/s" is false on this image. Firmware switches and U-Boot env changes are user-approval gates. Brief: `research/briefs/antsdr-e200.md`.
