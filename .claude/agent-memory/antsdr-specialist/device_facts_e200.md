---
name: device-facts-e200
description: Core verified facts about the specific ANTSDR E200 unit AERIX RF owns — network access, firmware image, throughput ceiling, sample format, single-RX limitation
metadata:
  type: project
---

Our specific ANTSDR E200 unit is reachable at `ip:192.168.1.10` (host `192.168.1.20/24`, nmcli profile `antsdr-e200-static`, interface `enp0s31f6`). It runs a **stock Pluto-compatible IIO image** (`ad9361-phy,model: ad9364`, fw v0.34-dirty, kernel 5.4.0 built 2023-07-07) that exposes only **one RX I/Q pair** (`cf-ad9361-lpc` voltage0/voltage1) even though the underlying MicroPhase E200 hardware is documented 2R2T-capable AD9361/AD9363 silicon on a real Zynq XC7Z020 (the `hw_model` IIO context string self-reports as "Z7010" — that's a spoofed genuine-Pluto identity string inherited from the compatible image, not the real chip).

**Why:** this determines what the common IQ abstraction can assume from this device today, and prevents re-deriving these facts (or worse, assuming dual-RX works) in a future session.

**How to apply:** treat this device as single-RX-channel for any near-term AERIX architecture work. Full details, measured throughput table, gain/format tables, and firmware options are in `research/briefs/antsdr-e200.md` — read that file fresh rather than trusting this summary if precision matters, since it may go stale.

Key numbers to remember without re-deriving:
- Measured sustained throughput over our network path: safe at 5 and 10 MS/s (ratio ~1.0), marginal at 15.36 MS/s (0.94-0.98), and hard-capped around ~57-60 MB/s (~14.4-15.1 MS/s) at 20 and 30 MS/s requested — the AD9361/FPGA is not the bottleneck, the libiio-over-Ethernet/iiod path is.
- Sample format is `le:S12/16>>0`, full scale is documented as ±2048 (12-bit, sign-extended into int16), NOT ±32768 — different from whatever HackRF's constant is, do not share a normalization constant across the two devices without checking.
- No overflow/dropped-sample counter exposed over libiio on this image; no working per-sample timestamp (`samples_pps` attr → ENODEV on this image) — this device does not currently give better timing than HackRF's IQ stream despite AD9361 having PPS-related hardware attributes in principle.
- 2R2T unlock exists via `fw_setenv mode 2r2t` (+ compatible=ad9361, reboot) but is a **persistent flash/U-Boot env change** — never do this without explicit architect/user approval; it was deliberately left undone in the [[antsdr-e200-bootstrap]] session.

See also [[antsdr-e200-bootstrap]] for tooling/access setup and [[antsdr-firmware-strategy]] for the firmware-image decision reasoning.
