---
name: protocol-sik-phy-facts
description: Durable PRIMARY SiK/Si4432 PHY facts (rates, deviation, band rasters, NETID hop seed, framing) and the two unverified single points of failure for a decoder
metadata:
  type: project
---

**SiK-class telemetry radios are the one non-DJI link whose entire PHY we can quote from shipping firmware — and the NETID is transmitted in cleartext in every packet header, so no key/ID search is ever needed.**

**Why:** derived 2026-09-19 directly from `ArduPilot_SiK_master.zip` (`Firmware/radio/`) for `docs/design/sik-mavlink-passive-decode.md`. Version scope is strictly **Si1000/Si4432 boards (`radio_443x.c`)**; RFD900x/Si446x (`radio_446x.c`) is a different register set and none of this transfers.

Facts worth not re-deriving:
- Air rates (kbps): 2,4,8,16,19,24,32,48,64,96,128,192,250; default `AIR_SPEED=64`. Deviation register table × 625 Hz/LSB ⇒ Δf ≈ R_b, i.e. **modulation index h ≈ 2.0** for 8–128 kbps, **ceiling 158.75 kHz** ⇒ h ≈ 1.65 @192k and **1.27 @250k** (adjacent channels overlap at 250 kbps).
- Raster = `(freq_max − freq_min)/(N+2)`, base += spacing/2 + a **NETID-seeded pseudorandom offset** when N>5. Defaults: 433.050–434.790/10 ch (145 kHz); 470.0–471.0/10; 868.0–870.0/10 (166.7 kHz); **915.0–928.0 / 50 ch / 250 kHz exact** (13 MHz ⇒ one 15.36 MS/s dwell sees the whole hop set). Hop-step register is **8-bit in 10 kHz units** (`radio_443x.c:614-626`, hence the 2.55 MHz guard) ⇒ realised spacing = firmware's floored Hz division rounded half-up to 10 kHz; base carrier quantised to 625 Hz (<480 MHz) / 1250 Hz (>480 MHz).
- Hop map (exact, `freq_hopping.c:84-118`, re-verified 2026-09-19) = the **naive benpfaff swap-shuffle, NOT Fisher-Yates/Durstenfeld**: `for i in 0..n-2: j = ((uint8_t)r_rand()) % n; swap(a[i],a[j])`, i.e. ascending loop, `j` modulo **n** (not i+1), and the draw **truncated to 8 bits** — `r_rand()` itself is `x=x*1103515245+12345` mod 2^32 returning `(x>>16)&0x7FFF`, seeded `r_srand(NETID)` (default 25). Channel index advances +1 mod N per TDM window (`MAX_WINDOW` default 131 ms); when locked both ends use the same physical channel, so an observer sees `channel_map[(c0+t) mod N]`. AES enabled ⇒ seed becomes `crc16(32,key)` and payload encrypted ⇒ **detect-only**. A Durstenfeld/`% (i+1)`/15-bit-draw transcription (which our first raster.py implementation used) agrees with the real map only at chance level — full diff, Python transcription and test vector `hop_map(25,10)==[0,9,5,2,6,7,4,3,8,1]` in `research/briefs/sik-freq-hopping-firmware.md`.
- Framing: 64-bit preamble, **2 sync bytes**; `ECC=0` (default) ⇒ HW header = the 16-bit NETID + length + HW CRC-16; `ECC=1` ⇒ Golay(24,12) over {netid,len}, {crc16,len}, payload. Either way **NETID is in the clear**. Payload ends with a 2-byte `tdm_trailer` (window:13/command/bonus/resend) that must be stripped before MAVLink parsing. `MAX_PACKET_LENGTH=252`.
- **Two unverified single points of failure** for any decoder: the sync-word *value* (firmware never writes the register ⇒ assumed Si4432 POR default 0x2DD4) and the `ENCRC|CRC_16` polynomial variant. Both are datasheet lookups, not firmware facts — a synthetic-only test suite shares these assumptions and therefore proves nothing about real signals.

**How to apply:** quote these instead of re-unzipping the firmware; always attach the Si4432-only version scope; and refuse any "SiK decode works" claim that rests on synthetic IQ or on sync/NETID recovery alone — evidence level 4 requires a MAVLink `CRC_EXTRA` pass on a real capture. Related: [[protocol-non-dji-decodability]], [[protocol-legal-flags-third-party-payload]].
