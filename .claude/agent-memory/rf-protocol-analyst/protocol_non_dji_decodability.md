---
name: protocol-non-dji-decodability
description: Durable protocol facts on which non-DJI drone links are decodable vs detection-only, and the data/legal constraints that actually gate the work
metadata:
  type: project
---

**The non-DJI landscape splits cleanly: decode is plausible only for SiK/3DR-class MAVLink radios and the open LoRa RC stacks (ExpressLRS, mLRS, Paparazzi-on-SiK). Everything else is closed, encrypted, or Wi-Fi-with-WPA2 and collapses to detection/classification/geolocation.**

**Why:** established 2026-09-19 from primary firmware (ArduPilot/SiK `freq_hopping.c`+`parameters.c`, ExpressLRS `FHSS.cpp`/`common.h`) plus the corpus's `NON_DJI_POSITION_MATRIX.md`. Durable, version-scoped facts worth not re-deriving:
- SiK: Si4432 GFSK ≤250 kbps, ≤50 ch, hop map = LCG shuffle seeded by NETID (**default 25**), Golay FEC, **AES off by default**, MAVLink carried *transparently* — so bytes recovered = MAVLink directly.
- ExpressLRS 2.4: **80 ch × 1.000 MHz from 2400.4 MHz**, sync ch = count/2+1, UID-seeded FHSS, packet *interval* (not on-air duration) 20000/6667/4000/2000/1000 µs at 50/150/250/500/1000 Hz. CRSF GPS is **chunked into 5/10-byte OTA payloads, not sent verbatim** — decode is much harder than SiK despite both being open.
- Crossfire/FrSky/Futaba/RadioLink: serial layer (CRSF/S.Port/SBUS) is open, **air layer is not**. Never infer air-side GPS from a serial-layer GPS frame — this is the single most common error in this domain.
- Autel/Skydio/Walksnail/HDZero: no protocol foothold at all; vendor figures only.

**The structural inversion that gates everything:** links where decode is plausible (SiK/ELRS/mLRS/Crossfire/Parrot) have **no public raw IQ**; links with abundant public IQ (RFUAV's 15 mfrs / 37 transmitters, incl. 31 RC-transmitter files, Autel EVO NANO, Herelink, SIYI, Skydroid) support **only** detection/classification. RFUAV supports no decode claim for any system.

**How to apply:** when asked "can we do brand X", answer from the ladder detect/family/device/decode with an evidence grade, and state which side of the inversion X sits on. Full ranked table, acceptance criteria, and research gaps live in `research/briefs/non-dji-targets.md`. Related: [[protocol-legal-flags-third-party-payload]], [[rc-link-raster-facts]].
