---
name: project-dji-generation-decodability
description: Durable protocol facts on which DJI link generations are DroneID-decodable, and the premise error that "O3 is not decodable"
metadata:
  type: project
---

DJI DroneID decodability by generation, as of 2026-09-19:
- **O1/O2/O3/O3+ = plaintext**; **O4 = encrypted payload, transport recoverable to a 16-bit CRC.**
- AERIX has *proven* only O2 (Mini 3 field 2026-09-04; RUB IQ Mavic Air 2 / Mini 2). O3 is
  **untested by AERIX, not known-failing.**

**Why:** the project's own docs (`README.md`, `AERIX_RF_ANTSDR_PROJECT.md`) and several task briefs
repeat "O3/O4 not decodable". The corpus contradicts the O3 half: leegang12 article 292 shows a
**Mini 3 Pro (O3)** decoding to full plaintext (pkt_len 88, version 2, `crc_packet '30ef'`), article
288 shows a **Mavic 3 (O3+)** plaintext decode, and 264 states the DroneID PHY is common to
"OcuSync 2.0, 3.0 or 3+". Grouping O3 with O4 understates our reachable capability and mis-targets
test-aircraft procurement.

**How to apply:** when asked about generation coverage, split it three ways (proven / expected-untested /
encrypted), never two. Also correct the recurring model errors: **Air 2S and Mini 3 Pro are O3, not O2**;
**Mini 3 non-Pro, Mini 2 SE and Mini 4K are O2**; Mavic Mini / Mini SE are Enhanced Wi-Fi and must not be
used as O2 references. Full graded table and campaign acceptance criteria:
`research/briefs/dji-generations-and-o3o4-identification.md`. See also [[protocol-o4-evidence-limits]].
