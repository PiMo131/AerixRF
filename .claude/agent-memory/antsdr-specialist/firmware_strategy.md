---
name: antsdr-firmware-strategy
description: Decision reasoning for keeping the stock Pluto-compatible 1R1T image on the E200 instead of switching to 2R2T or UHD firmware
metadata:
  type: project
---

Recommendation as of 2026-09-18: keep the current stock Pluto-compatible (`ad9364` DT, 1R1T) firmware image on our ANTSDR E200. Do not switch to 2R2T (`fw_setenv mode 2r2t` + compatible=ad9361 + reboot) or to MicroPhase's UHD-compatible firmware without an explicit, approved reason.

**Why:** (1) our measured sustained network throughput ceiling via libiio/iiod over Ethernet is ~15 MS/s regardless of requested rate — a second RX channel would not currently be usable at meaningful rates given that ceiling is already the binding constraint, not the AD9361 front end. (2) The 2R2T unlock is a persistent U-Boot-env/flash-side change with a reboot — out of scope for passive, non-destructive bootstrap work, and reversibility/rollback wasn't characterized. (3) UHD firmware is a separate image/driver stack (`antsdr_uhd`) with its own integration cost, and nothing in AERIX's architecture currently needs UHD-specific features over libiio/IIO.

**How to apply:** if a future phase concretely needs two synchronized RX channels from one E200 (e.g. phase-difference/AOA experiments), revisit this — but first re-characterize the network throughput ceiling (point-to-point cable vs whatever topology is used then), and get explicit sign-off before making the persistent flash change. See `research/briefs/antsdr-e200.md` §9 for the exact command sequence and citations, and [[device-facts-e200]] for the throughput numbers driving this call.
