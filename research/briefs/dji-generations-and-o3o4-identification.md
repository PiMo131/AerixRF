# DJI aircraft ↔ link generation, and O3/O4 identification without payload decode

Owner: `rf-protocol-analyst`, 2026-09-19, for the positives campaign. Companions:
`briefs/dji-ocusync-droneid-sources.md` (PHY), `briefs/droneid-channel-raster.md` (centres).

## Evidence grades

**A-FIELD** = AERIX's own capture/measurement. **A-IQ** = third-party real IQ held locally (RUB-SysSec
`mavic_air_2`, `mini2_sm`). **B-VENDOR** = DJI spec/manual-level fact from analyst model knowledge,
**not verified against a DJI page this pass** — librarian must confirm before external quoting.
**C-COMMUNITY** = CSDN secondary claim (leegang12 unless noted). **D-UNVERIFIED** = hypothesis only.

---

## Q1 — Aircraft ↔ link generation ↔ DroneID decodability

**Correction to the campaign premise, up front.** "O3 = not decodable" is *not* what the evidence says.
The corpus shows an **O3 airframe (Mini 3 Pro) decoding to full plaintext telemetry** (pkt_len 88,
version 2, `device_type: 'Mini 3 Pro'`, `crc_packet '30ef' = crc_calculated`; article 292), and a
**Mavic 3 (O3+) plaintext decode** (article 288). Article 264 states the DroneID PHY is common across
"OcuSync 2.0, 3.0 or 3+". The correct statement of our position is:
**O2 = proven decodable by AERIX; O3/O3+ = expected decodable, never tested by AERIX; O4 = payload
encrypted, transport recoverable.** The campaign should test O3, not assume it fails.

| Aircraft (release) | Link generation | DroneID decodable by our decoder | Grade (generation) | Note |
|---|---|---|---|---|
| Mavic 2 Pro / Zoom (2018) | OcuSync 2.0 | Yes (short-frame variant: symbol 1 omitted, 576 µs) | B-VENDOR + C | 264: "Mavic 2 and earlier" short frame — our decoder must tolerate 8-symbol frames |
| Mavic Mini (2019) / Mini SE (2021) | **Enhanced Wi-Fi, not OcuSync** | **Unknown — do not assume** | B-VENDOR | Wi-Fi-link airframes; whether they emit the OFDM DroneID burst at all is unresolved in-corpus. **Avoid as campaign reference** |
| Mavic Air 2 (2020) | OcuSync 2.0 | **Yes — proven** | A-IQ | RUB `samples/mavic_air_2`, bit-exact vs their receiver |
| Mini 2 (2020) | OcuSync 2.0 | **Yes — proven** | A-IQ | RUB `samples/mini2_sm`; plaintext `device_type: 'Mini 2'` in 288 |
| Air 2S (2021) | **OcuSync 3.0** | Expected yes, untested | B-VENDOR | Commonly mis-stated as O2. Treat as O3 until a DJI page confirms |
| DJI FPV (2021) | OcuSync 3.0 | Expected yes, untested | B-VENDOR | |
| Mavic 3 / Classic / Cine (2021–22) | O3 → **O3+** | Expected yes | C-COMMUNITY (288 plaintext decode) | Plaintext `device_type: 'DJI Mavic 3'` observed |
| Mini 3 Pro (2022) | OcuSync 3.0 | **Plaintext decode shown in corpus** | C-COMMUNITY (292) | Strongest single argument that O3 is decodable |
| **Mini 3 (non-Pro, 2022)** | **DJI O2** | **Yes — proven by AERIX** | **A-FIELD** | Field 2026-09-04, 2429.5 MHz, 640 ms cadence, serial + consecutive seq |
| Avata (2022) | OcuSync 3.0 | Untested — **user already has one** | B-VENDOR | 2026-09-04: only 5.8 GHz seen (below stock-antenna floor), 2400–2412 MHz never captured |
| **Mini 2 SE (2023)** | **DJI O2** | Expected yes | B-VENDOR | Cheap, common — good borrow target |
| Air 3 (2023) | **O4** | Transport only | B-VENDOR | |
| Mini 4 Pro (2023) | **O4** | Transport only | B-VENDOR | |
| Mavic 3 Pro (2023) | O3+ | Expected yes | B-VENDOR | |
| **Mini 4K (2024)** | **DJI O2** | Expected yes | B-VENDOR | Cheapest current-production O2 airframe. Best single "borrow this one" answer |
| Avata 2 (2024) | **O4** | Transport only | B-VENDOR | |
| Neo (2024) | **O4** (uncertain) | Transport only | B-VENDOR, **uncertain** | Lightest/cheapest O4; also supports phone-Wi-Fi control — link in use may differ per control mode. Verify |
| Air 3S (2024) | **O4** | Transport only | B-VENDOR | |
| Flip (2025) | **O4** | Transport only | B-VENDOR | |
| Mavic 4 Pro (2025) | **O4+** | Transport only, **O4+ untested anywhere** | B-VENDOR, uncertain | No in-corpus evidence that O4+ shares the O4 DroneID transport |
| Mini 5 Pro (2025) | O4 / O4+ (uncertain) | Transport only | **D-UNVERIFIED** | Post-dates the corpus entirely |
| Neo 2 (2025–26) | unknown | unknown | **D-UNVERIFIED** | Do not state a generation |

**O2 shortlist for borrowing (cheap, common, in production or widely second-hand):**
`Mini 4K` > `Mini 2 SE` > `Mini 2` > `Mini 3 (non-Pro)` > `Mavic Air 2`.
Avoid `Mavic Mini` / `Mini SE` (Wi-Fi link, unresolved). **Do not substitute `Mini 3 Pro` or `Air 2S`
for an O2 test — both are O3.**

---

## Q2 — Identifying O3 and O4 without payload decode

### What the corpus establishes about the O3/O4 DroneID burst

| Property | O3 / O3+ | O4 | Grade |
|---|---|---|---|
| Frame structure | Same 9-symbol OFDM burst as O2 | Same (author's unmodified chain reaches CRC) | C-COMMUNITY (264, 292) |
| ZC sync | Roots 600 / 147 at symbols 4 and 6, 601 subcarriers, 1024-FFT, 15 kHz SCS | Same — implied, since sync succeeds | C-COMMUNITY (264, 281) |
| Occupied BW / Fs | ~10 MHz occupied, 15.36 MHz sample rate | Same (implied) | C + A-FIELD (our Mini 3 screen keys on 4–14 MHz occupied) |
| Cadence | 640 ms (NDSS'23, measured); 600 ms claimed in 281 | Not independently measured | B/C |
| Payload | **Plaintext**, pkt_len 88, version 2 | **Encrypted** — high-entropy bytes, no ASCII serial, no zero runs (320 §三) | C-COMMUNITY (292, 320) |
| CRC | 16-bit message CRC (`30ef`, `8ffa`, `f557`, `5c39`) | 16-bit `0xC5 0x0A`, `crc_byte == crc_calc` | C-COMMUNITY (292, 326) |
| CRC poly/init | **Not disclosed** — deliberately blurred in 326; brute-forceable from a shown I/O pair | same, unknown | C, gap |
| Unencrypted O4 header fields | n/a | **None demonstrated anywhere** | C — absence is explicit, not a search failure |

### Verdicts

**(a) Deterministic burst detection — YES, and it is generation-agnostic.**
If the ZC roots are unchanged across O1–O4, ZC correlation at symbols 4/6 is a deterministic detector
for *any* DroneID burst regardless of payload encryption. This is a stronger claim than energy/morphology
and it is the cheapest O4 capability we can build. **Not yet verified against an O4 signal by anyone we
can check** — the only support is that the corpus author's O2 chain reached CRC on O4, which requires
sync to have worked.

**(b) CRC-verified "confirmed DJI O3/O4 frame" (evidence level 3) — PLAUSIBLE, NOT ESTABLISHED.**
A CRC pass on O4 requires the *entire* transport to be right: CFO/TO, equalisation, QPSK, Gold
descrambling (same seed), de-rate-matching (same K/N/D/E), Turbo decode, then CRC16. The corpus asserts
this works unmodified on O4 but publishes only two matching CRC bytes from one screenshot, single author.
**A 16-bit CRC on a self-consistent decode is a ~1/65536 false-positive per frame — that is strong enough
for level 3 *if reproduced*, but the reproduction has not happened.** We may not claim it until we do it
ourselves. Note also: we do not currently hold the Gold seed / rate-matching parameters independently of
`proto17` / RUB code, and neither repo was validated against O4.

**(c) Unencrypted O4 header fields — NO. Claim nothing.**
No `pkt_len`, `device_type`, sequence number, or product type has been shown for O4 in any source we hold.
Article 320's claimed "encryption key packet" figure is a **duplicate of the encrypted-data-packet image**
(byte-identical, MD5 `6061bef60482cfd3bacfe0b1e716f7ac`) — it is not evidence of a key-packet layout.
Commercial claims of "session/hash ID" for O4 (quoted in `AERIX_RF_ANTSDR_PROJECT.md` §O4) are vendor
marketing with no method disclosed; do not treat them as reachable capability.

### O3/O4 video/control-link morphology for Stage-1 rules

The corpus is **weak** here; our own field data is stronger.
- **A-FIELD (Mini 3, O2, 2026-09-04):** RC uplink = 2 MHz hops, ~0.5 ms dwell, 2 MHz raster.
  Video downlink = 10–13 MHz OFDM, ~3 ms bursts, 20/40/60 ms period, channel moves in flight.
- **B-VENDOR:** O3/O4 offer selectable 10/20/40 MHz channel bandwidth in 2.4 and 5.8 GHz; O4 adds
  5.1 GHz in some regions. Not verified against a DJI page this pass.
- **C/PLAUSIBLE-only:** the one O3 field-test article in the FPV archive
  (`fpv/.../digital_video/DJI_FPV/ocusync3_field_test/`) claims "64→256 subcarriers, 2×2→4×4 MIMO,
  64→256-QAM" — graded PLAUSIBLE by the archive itself and arithmetically unsupported.
  **Do not build Stage-1 rules on it.**
- Consequence: a 20/40 MHz DJI video downlink will look *wider* than the 10 MHz our current
  `droneid_shaped` PSD screen (4–14 MHz occupied) accepts. The screen is for the DroneID burst and is
  correct; the **Stage-1 link-morphology rule is what needs new O3/O4 evidence.**

---

## What the positives campaign must measure

Ranked. Each has a machine-testable acceptance criterion.

1. **O3 DroneID plaintext test (Avata, already owned).** Capture 2400–2412 MHz *and* 2429.5/2414.5/
   2444.5/2459.5 MHz, plus 5.8 GHz DroneID centres, powered-on and in flight.
   *Accept:* ≥1 window with ZC hit **and** CRC-valid plaintext with `device_type` matching the airframe.
   *Refute:* ZC hits present, CRC fails or payload high-entropy ⇒ O3 is not plaintext for this model.
2. **O4 transport-to-CRC test.** Any O4 airframe (Neo / Avata 2 / Mini 4 Pro / Air 3S / Flip).
   *Accept:* ZC detection rate ≥ that of a same-range O2 reference, **and** ≥20 frames where
   `crc_byte == crc_calc` with the unmodified O2 chain, **and** decoded payload bytes fail a plaintext
   sanity check (no ASCII serial, entropy > 7.5 bits/byte).
   That triple is the minimum to claim "confirmed DJI O4 DroneID frame, payload encrypted" at level 3.
3. **Per-generation link morphology sweep.** For each aircraft: occupied BW, burst duration, burst
   period, hop raster, band, at idle / video-on / in-flight, on the E200 at 12.288 MS/s.
   *Accept:* a table with ≥100 bursts per (aircraft, mode) and the resulting Stage-1 separation from
   Wi-Fi/BLE stated as a confusion matrix, not a prose claim.
4. Secondary: short-frame (8-symbol) handling if a Mavic 2-era airframe appears; and a DroneID burst
   **in flight** for O2 (still never seen by AERIX — outstanding from 2026-09-04).

## Claims that must NOT be made yet

- "AERIX decodes O3." Not until criterion 1 passes. The corpus decode is someone else's receiver.
- "AERIX detects/confirms O4." Not until criterion 2 passes.
- "O4 exposes a session/hash ID." No method exists in anything we hold.
- "Air 2S / Mini 3 Pro are O2." They are O3.
- Any generation statement for Mini 5 Pro, Neo 2, or O4+ (Mavic 4 Pro) — D-UNVERIFIED.

## Research gaps (for `research-librarian`)

- **RESEARCH NEEDED:** primary DJI spec-page or FCC-filing confirmation of the video-transmission
  generation for: Air 2S, Mini 2 SE, Mini 4K, Mini 3 (non-Pro), Neo, Mavic 4 Pro, Mini 5 Pro, Neo 2.
  A per-model DJI spec URL + retrieval date per row would upgrade this table from B-VENDOR to PRIMARY.
- **RESEARCH NEEDED:** does any source (DJI page, FCC, or otherwise) state whether Mavic Mini / Mini SE
  (Enhanced Wi-Fi) transmit a DroneID burst at all?
- **RESEARCH NEEDED:** any second, independent source (not leegang12) reporting a successful CRC check on
  an O4 DroneID frame. Currently single-source and load-bearing for our whole O4 plan.
- Still open from the PHY brief: pilots-vs-no-pilots; 24-bit CRC poly/init; de-rate-matching K/N/D/E.
