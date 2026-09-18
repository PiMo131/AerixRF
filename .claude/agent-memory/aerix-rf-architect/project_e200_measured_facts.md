---
name: e200-measured-facts
description: ANTSDR E200 as measured 2026-09-18 — IIO Pluto-compatible firmware, single RX, ~59 MB/s (~14.8 MS/s) sustained ceiling on iiod path, no overflow counter, no timestamps; 2R2T unlockable via U-Boot env.
metadata:
  type: project
---

E200 at `ip:192.168.1.10` (host 192.168.1.20 via nmcli profile `antsdr-e200-static`). Firmware: PlutoSDR-compatible IIO image `v0.34-dirty` (2023), self-reports "PlutoSDR Rev.C Z7010-AD9364" but hardware is XC7Z020 + 2R2T AD9361-class. Only ONE RX exposed (`cf-ad9361-lpc` voltage0/1, `le:S12/16>>0`, full scale ±2048 DOCUMENTED not measured). MEASURED sustained RX ceiling ≈ 57–60 MB/s ≈ 14.8 MS/s complex int16, identical via Python bindings and C `iio_readdev` ⇒ device-side (iiod/ARM/TCP), not host. 5/10 MS/s clean; 15.36 at 0.94–0.98 (silent loss); 20/30 unusable. No overflow/xflow counter; `samples_pps` ENODEV ⇒ no device timestamps today — ANTSDR does not beat HackRF on timing yet. 2R2T unlock = persistent `fw_setenv compatible ad9361 / mode 2r2t` (NOT done; needs user approval). MicroPhase also ships UHD-compatible firmware (FPGA-side streaming) — candidate for higher rates + timestamps; unevaluated. Third-party `alphafox02/antsdr_dji_droneid` firmware exists — unevaluated.

**Why:** These numbers drove the canonical-rate decision (must be ≤ ~14 MS/s on IIO path) and the firmware question.

**How to apply:** Re-measure if firmware or libiio version changes. Any claim of "ANTSDR 20 MS/s" is false on this image. Firmware switches and U-Boot env changes are user-approval gates. Brief: `research/briefs/antsdr-e200.md`.
