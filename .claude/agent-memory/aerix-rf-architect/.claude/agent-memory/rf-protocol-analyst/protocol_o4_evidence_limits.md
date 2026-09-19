---
name: protocol-o4-evidence-limits
description: Exactly what is and is not established about O4 DroneID, and what AERIX may not claim about it
metadata:
  type: project
---

O4 DroneID evidence state (2026-09-19), single-source and load-bearing:
- The **only** evidence that O4's transport is recoverable is leegang12 article 292: a screenshot of
  `crc_byte = 197 10` / `crc_calc = 197 10` (0xC5 0x0A) beside a clean QPSK constellation, with **no
  telemetry field shown**. One author, one screenshot, never independently reproduced.
- Article 320's claimed "encryption key packet" figure is a **byte-identical duplicate** of the
  encrypted-data-packet image (MD5 `6061bef60482cfd3bacfe0b1e716f7ac`). It is **not** evidence of a
  key-packet layout.
- No unencrypted O4 header field (pkt_len, device_type, sequence number, product type) exists in
  anything the project holds. Commercial "session/hash ID for O4" claims come with no method.

**Why:** the entire AERIX O4 plan (detect-and-confirm without decrypt) rests on this one screenshot.
Treating it as settled would let a level-3 "confirmed DJI O4 frame" claim ship unvalidated.

**How to apply:** an AERIX O4 confirmation claim needs all three of — ZC detection rate comparable to a
same-range O2 reference; ≥20 frames with `crc_byte == crc_calc` using the unmodified O2 chain; and the
decoded payload failing a plaintext sanity check (no ASCII serial, entropy > 7.5 bits/byte). Until then
say "O4 detection is an untested hypothesis", not "AERIX detects O4". See
[[project-dji-generation-decodability]].
