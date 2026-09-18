---
name: protocol-droneid-evidence-gating
description: How to reason about DroneID decode confidence — CRC24A false-pass math, why cross-frame consistency beats any single CRC, and which semantic sanity checks to gate on
metadata:
  type: project
---

Evidence-gating stance for DJI DroneID decodes (OcuSync <= 2).

**Why:** AERIX's evidence ladder (CLAUDE.md) forbids presenting weak evidence as a confirmed decode;
a CRC pass on a single burst is often quoted as if it were proof, and it needs quantifying.

**How to apply:**
- CRC24A false-pass probability is 2^-24 ≈ 6e-8 per candidate. With our additional parse gate
  (msg_type==16 and version==2, 16 more constrained bits) it is far lower. For a 10-candidate file,
  P(any false pass) ≈ 6e-7. So "10/10 CRC valid" is never suspicious on statistical grounds — a high
  CRC pass rate means the front end is working, not that the check is loose.
- The genuinely strong evidence is *cross-frame consistency*: same serial across N frames, monotonic
  (or fixed-step) sequence numbers, operator coordinates agreeing to sub-metre across frames. That
  independent corroboration is worth more than any single frame's CRC.
- Recommended post-CRC semantic checks are for **evidence labelling / telemetry-quality flags, not
  for suppressing frames**: |lat| <= 90, |lon| <= 180, exact-zero coords meaning "no GPS lock" (real
  in mini2_sm), gps_time plausibility, product_type in the known table, seq monotonic within a track.
  A CRC24A-valid frame that fails a range check is far more likely a genuine DJI oddity than a decode
  error — log it, do not drop it.
- Claim discipline: a CRC-valid DroneID decode is stage-4 "validated deterministic decode" only for
  the *fields the frame carries*. It says nothing about O3/O4 decodability, and serial-field content
  is attacker-controllable (RUB demonstrated this) so a serial is an identifier, never an
  authentication.

See [[protocol-droneid-rub-crosscheck]].
