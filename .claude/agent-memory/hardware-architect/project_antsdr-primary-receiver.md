---
name: antsdr-primary-receiver
description: As of 2026-09-18 the ANTSDR E200 is the PRIMARY receiver and HackRF is demoted to secondary/reference; design must serve both
metadata:
  type: project
---

As of 2026-09-18, ANTSDR E200 (AD9361 + Zynq, 1 GbE to host) is the **primary** raw-IQ
receiver for AERIX RF. HackRF is now a secondary/reference backend that must keep working
unchanged, including bit-exact replay of pre-existing `.cs8` sessions.

This reverses the ordering in `AERIX_RF_ANTSDR_PROJECT.md`, where ANTSDR was a Phase-3
item ("do not implement an ANTSDR source class now"). The project doc is stale on
sequencing; its *abstraction* guidance (§3) is still correct.

**Why:** the ANTSDR is the platform the deployed system will actually run on; the HackRF
was the bring-up platform and the source of the 2026-09-04 golden field-test session
(DJI Mini 3, CRC-valid DroneID decodes) that remains the regression reference.

**How to apply:** never propose a change that would make the HackRF path
lowest-common-denominator, and never make an ANTSDR-only feature (FPGA acceleration,
hardware timestamps, dual-RX, DJI-event firmware) a prerequisite for the baseline path.
The design note lives at `docs/design/antsdr-backend.md`. Related:
[[antsdr-backend-interface-decisions]], [[hackrf-couplings-in-abstraction]].
