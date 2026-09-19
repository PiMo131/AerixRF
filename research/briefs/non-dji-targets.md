# Brief: Non-DJI links AERIX can work on — ranked targets

Owner: `rf-protocol-analyst`, 2026-09-19. Question asked by the user: *which non-DJI brands/links can we
actually work on?* Built from `NON_DJI_POSITION_MATRIX.md`, `GENERIC_HOPPING_FEATURES.md`, the per-vendor
`NOTES.md` set under `research/library/.../non_dji_telemetry/` and `.../fpv/AERIX_FPV/`, plus
`research/briefs/{rc-link-raster-facts,datasets-and-signatures-plan}.md` and
`docs/design/stage1-link-signatures.md`. No new web research was performed.

## 0. Conclusion in four lines
- **Detection/family-classification is available for essentially every non-DJI link** we listed; it is gated by
  capture hardware and labelled IQ, not by protocol knowledge.
- **Payload decode is realistically available for exactly two families: SiK/3DR-class MAVLink radios and the
  open LoRa RC stacks (ExpressLRS / mLRS).** Everything else is closed, encrypted, or Wi-Fi-with-WPA2.
- **The only link with a fully primary, numeric, immediately codeable RF signature is ExpressLRS** (firmware
  channel tables + packet intervals). That makes it the best *validation* target even though it is not the best
  decode target.
- **Decoding third-party MAVLink telemetry is a policy question, not a technical one** — see §4.

## 1. Capability ladder used in the table
`DETECT` = level-1/2 RF candidate + morphology. `FAMILY` = level-2 probabilistic link-family label, no vendor
claim. `DEVICE` = level-3 protocol evidence identifying a specific unit (e.g. UID/NETID/MAC). `DECODE` =
level-4 validated payload decode. Evidence grades: **PRIMARY** (shipping source / spec / standard),
**COMMUNITY** (open RE implementation or corroborated practitioner material), **INFERRED** (argued from
chip/band/marketing facts only). Effort: **S** ≤1 wk one builder, **M** 2–4 wks, **L** ≥1 quarter/research.

## 2. Ranked target table

| # | Link / protocol | Brands / aircraft | Band(s) | PHY summary | AERIX capability (grade) | Data we hold | What we lack | Effort | Legal |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **ExpressLRS 2.4** | ELRS-equipped FPV/freestyle/long-range builds; RadioMaster, BetaFPV, Happymodel TX/RX | 2400.4–2479.4 MHz | LoRa (125 kHz–1 MHz) + FLRC; **80 ch × 1.000 MHz**, sync ch = count/2+1; UID-seeded FHSS; TDD telemetry 1:2…1:128; packet interval 20000/6667/4000/2000/1000 µs for 50/150/250/500/1000 Hz | DETECT+FAMILY **PRIMARY** (raster + interval are firmware constants); DEVICE **L** (UID recoverable only via hop-sequence matching, unproven); DECODE **COMMUNITY/L** (CRSF GPS is chunked into 5/10-byte OTA payloads, not verbatim) | firmware `FHSS.cpp/.h`, `common.h`; **no IQ anywhere** | live or recorded ELRS IQ at ≥2 packet rates; on-air burst-duration table (period is known, duration is not) | S for FAMILY, L for DECODE | — (open, unencrypted by default; decode still touches third-party telemetry, see §4) |
| 2 | **SiK / 3DR / Holybro (+RFD900, CUAV P9)** | ArduPilot/PX4 airframes, most DIY and many commercial platforms | 433 / 868 / 915 MHz | Si4432 GFSK ≤250 kbps; FHSS ≤50 ch, **hop map = LCG shuffle seeded by NETID (default 25)**; Golay FEC; adaptive TDM/LBT/AFA; AES optional and **OFF by default**; MAVLink carried **transparently** | DETECT+FAMILY **PRIMARY**; DEVICE **PRIMARY-mechanism** (NETID is a small search space); DECODE **PRIMARY-mechanism / demo NOT_FOUND** — de-hop → Golay → MAVLink bytes | firmware source (ArduPilot/SiK) incl. `freq_hopping.c`, `parameters.c`; **no IQ** | a SiK radio pair to receive, or any public IQ (none exists); a GFSK/Golay receiver | M | **FLAG-A (blocking)** — recovers third-party position/telemetry in cleartext |
| 3 | **Analog 5.8 GHz FPV video** | every analog VTX (RTC6705/TBS/ImmersionRC), most racing/freestyle quads, many toy FPV kits | 5645–5945 MHz | Continuous analog FM composite video, ~6 MHz occupied, **fixed channel** (no hop); 40-ch grid: F = 5740+20n, Raceband = 5658+37n, B = 19 MHz grid, A descending, E discontinuous | DETECT+FAMILY **COMMUNITY** (chips/grids independently corroborable); DEVICE **INFERRED** only; DECODE = video demod — technically easy, out of scope for third-party signals | channel database (all 5 bands); HackRF covers 5.8 with margin | any 5.8 GHz capture session — we have none; our Stage-1 work is 2.4-only | S | **FLAG-B** — carrier detection fine; demodulating third-party video content is not |
| 4 | **RC 2.4 GHz closed FHSS: FrSky ACCST/ACCESS, Futaba FASST/T-FHSS, FlySky AFHDS2A/3, RadioLink, Spektrum DSM2/DSMX** | Nearly all hobby transmitters; the "controller present" half of a drone scene | 2.4 GHz (FrSky also 868/915) | GFSK/2-FSK/MSK (CC2500: FrSky D/L/V/X), A7105 (FlySky AFHDS/AFHDS2A), CYRF6936 DSSS+adaptive FHSS (DSM2/DSMX), Futaba DSSS/FHSS; 100–200 Hz frame rates; **no public air-interface raster for any of them** | DETECT+FAMILY **COMMUNITY**; DEVICE **COMMUNITY/L** (DSMX/AFHDS2A bind IDs are implemented in DIY-Multiprotocol-TX-Module — an open TX firmware, i.e. a real RE foothold we have not read); DECODE of control frames possible in principle, **no GPS on the link** for most | **RFUAV raw IQ: 31 RC-transmitter files** across FlySky/FrSky/Futaba/JR Propo/Jumper/RadioMaster/RadioLink/SIYI/Skydroid/WFLY/Devention + DroneRFa class labels | the RFUAV RC subset is identified but **not downloaded/format-verified**; no primary raster for any vendor | S (classify) / M (raster RE) | — (control frames carry no position; decoding them is still third-party traffic) |
| 5 | **Skydroid / Herelink / SIYI integrated HD datalinks** | Agricultural and commercial ArduPilot/PX4 platforms (H12/H16/H30, Hx4, MK15/MK32) | 2.4 GHz (+sub-GHz on some) | Proprietary OFDM-ish video+telemetry modem, **undocumented**; payload very often MAVLink | DETECT+FAMILY **COMMUNITY**; DECODE **INFERRED-only** — payload is probably open, PHY is not | **RFUAV IQ: Skydroid 8.38 GB, SIYI 6.68 GB, Herelink 2.26 GB** | modem PHY; any bind/ground-truth pairing | M (classify) / L (PHY RE) | **FLAG-A** if PHY is ever solved (MAVLink again) |
| 6 | **Parrot Wi-Fi (Anafi, Bebop, AR.Drone 2.0)** | Parrot consumer/prosumer | 2.4 / 5 GHz 802.11 | Standard 802.11 a/g/n — the PHY is a public standard, so Wi-Fi tooling applies directly. AR.Drone 2.0: **open AP + cleartext navdata UDP**. Bebop/Anafi: WPA2 on current firmware, ARSDK payload open but encrypted in transit | DETECT+DEVICE **PRIMARY** (802.11 management frames are in the clear → SSID pattern + OUI = deterministic device identification without any RE); DECODE: **legacy AR.Drone only** (COMMUNITY); modern Parrot = no | DroneRF/Zenodo spectra incl. Bebop/AR.Drone | a monitor-mode Wi-Fi capture path in AERIX (we have none); SSID/OUI table | S (OUI/SSID detect) | **FLAG-C** — 802.11 management-frame observation vs. associating/decrypting are very different legally |
| 7 | **Wi-Fi-controlled toy drones (class)** | Syma/Eachine/Holy Stone/Potensic and hundreds of OEMs | 2.4 GHz 802.11 | Aircraft runs an **open or trivially-keyed SoftAP**; control via UDP; video via MJPEG/H.264 over UDP; SSID strings are highly vendor-patterned | DETECT+DEVICE **PRIMARY** (same management-frame argument as row 6); DECODE **INFERRED** (varies per OEM, no single protocol) | none in corpus; nothing in RFUAV/DroneRFa | an SSID/OUI corpus; any capture | S (detect) | **FLAG-C** |
| 8 | **OpenHD / wifibroadcast** | DIY long-range HD FPV, OpenIPC cameras | 2.4 / 5.8 GHz | **Raw 802.11 injection** (no association, no beacons): 20/40 MHz OFDM, FEC'd video, bitrate-adaptive, continuous while streaming. Recent wifibroadcast versions encrypt (libsodium) | DETECT+FAMILY **COMMUNITY** (distinctive: 802.11 PHY with *no* beacon/management traffic — a strong discriminator) | corpus notes only, no numbers | measured occupancy/timing; encryption status per version | M | **FLAG-B/C** |
| 9 | **TBS Crossfire / Tracer** | Long-range FPV, TBS ecosystem | 868/915 MHz (Crossfire), 2.4 GHz (Tracer) | LoRa (Crossfire) / FSK (Tracer), ~150 Hz; **closed proprietary firmware, hop sequence undocumented** | DETECT+FAMILY **INFERRED-to-COMMUNITY**; DECODE **NO** — CRSF-over-serial GPS is a *different layer*; do not infer air-side GPS from it | none | everything on the air side | M (detect only) | — (no decode planned) |
| 10 | **Autel SkyLink (EVO / EVO II / Max)** | Autel consumer/enterprise | 2.4 / 5.8 GHz | Proprietary hopped OFDM, O4-class; no public RE at all | DETECT+FAMILY **COMMUNITY** (IQ-backed); DECODE **none** | **RFUAV IQ: EVO NANO 3.37 GB** | everything protocol-side; PHY RE is a DJI-scale multi-quarter effort | M (classify) / L (PHY) | — |
| 11 | **Yuneec (Typhoon consumer; H520 commercial)** | Yuneec | 2.4 / 5.8 GHz | Consumer: proprietary, undocumented. H520: proprietary modem carrying **PX4 MAVLink** | DETECT **COMMUNITY**; DECODE: consumer **no**, H520 **INFERRED** (payload open, modem unknown) | Zenodo 2020 set contains Typhoon H spectra | modem PHY; any H520 capture | M | **FLAG-A** if H520 PHY solved |
| 12 | **Skydio (2 / X2 / X10)** | Skydio | 2.4 / 5.8 GHz + Wi-Fi | Encrypted by design, vendor-stated | DETECT+FAMILY **INFERRED**; DECODE **explicitly out of scope** | none | everything | L | — (do not pursue decode) |
| 13 | **HDZero** | HDZero VTX/VRX, race quads | 5.8 GHz | Proprietary digital, narrower than Wi-Fi-based systems, reuses a raceband-like grid, continuous while streaming, low latency | DETECT **COMMUNITY** (the one corpus article is a latency review, UNVERIFIED, with no RF numbers) | nothing measurable | occupied BW, numerology, timing — all unmeasured | M | **FLAG-B** |
| 14 | **Walksnail Avatar** | Caddx/Walksnail VTX | 5.8 GHz | Proprietary OFDM, **20 MHz @25 Mbps / 40 MHz @50 Mbps** (vendor figures, not measured), encrypted video | DETECT **INFERRED**; DECODE **out of scope (encrypted)** | corpus explicitly records **"empty — and that is the finding"**: no public RF material exists | a Walksnail system + ANTSDR (40 MHz exceeds HackRF) | M | **FLAG-B** |
| 15 | **mLRS** | DIY MAVLink-RC hybrid builds | 2.4 / 868-915 / 433 MHz | Open firmware; LoRa/FLRC; 50 Hz control + 3–5 kB/s telemetry; **MAVLink native** | DETECT+FAMILY **PRIMARY**; DECODE **PRIMARY-mechanism** (same class as ELRS but MAVLink is not chunked into CRSF) | firmware source | IQ; low deployment base means low field priority | M | **FLAG-A** |
| 16 | **Paparazzi / PPRZLink** | Research/academic airframes | depends on radio (XBee/SiK/Wi-Fi) | Transport-dependent; PPRZLink payload fully open, typically unencrypted | Inherits whatever the underlying radio row gives; on a SiK-class radio it is **row 2 + a different parser** | protocol definitions | same as row 2 | S on top of row 2 | **FLAG-A** |

## 3. What we hold vs. what we lack — the one structural fact
The systems where **decode is plausible** (SiK, ELRS, mLRS, Paparazzi, and the MAVLink-carrying commercial
datalinks) are exactly the systems with **no public raw IQ**. The systems with **abundant public raw IQ**
(RFUAV's 15 manufacturers / 37 transmitters) are exactly the ones where only **detection and classification**
are supportable. That inversion, not protocol knowledge, is the real constraint on this whole workstream.

## 4. Legal / ethics flags needing a user ruling before any build
- **FLAG-A — third-party MAVLink telemetry decode (SiK, mLRS, Paparazzi, Herelink/SIYI/Skydroid/H520 if solved).**
  Passive receive is technically trivial and the payload is cleartext, but it recovers another operator's
  position, home location and airframe telemetry. Technically in scope for a passive project; **needs an
  explicit user ruling before a decoder is written.** Recommended default: build the *detector*, gate the
  *payload parser* behind an explicit config flag plus a documented authorisation basis.
- **FLAG-B — third-party video content (analog 5.8, HDZero, Walksnail, OpenHD).** Detecting and characterising
  the carrier is clearly in scope. **Demodulating third-party video content is not**, and the corpus's own
  `proprietary_detection_only/NOTES.md` already draws this line. Video demod only for a transmitter the user
  owns and is authorised to operate.
- **FLAG-C — Wi-Fi-based aircraft (Parrot, toy drones, OpenHD).** Observing 802.11 management frames (SSID,
  OUI, beacons) is ordinary passive spectrum use. Associating, decrypting, or capturing data frames is not.
  Keep any Wi-Fi path strictly at the management-frame/PHY level unless the user rules otherwise.
- **No-transmit constraint has a real consequence here.** Bench-validating ELRS or SiK requires *someone* to
  key a transmitter. AERIX must not do this. The compliant options are: (a) recorded third-party IQ, (b)
  capture at a location where operators are already transmitting for their own purposes (an FPV field), or
  (c) the user personally operates a radio they are licensed/authorised to operate, which is the user's
  decision and must not be assumed by any agent or written into a build task.

## 5. Top 3 targets for next quarter
1. **RFUAV 31-file RC-transmitter subset → Stage-1/2 family validation.** The only asset that needs no
   hardware, no transmission and no legal ruling, and it directly feeds the `docs/design/stage1-link-signatures.md`
   §9 validation table, which currently has no positives for R1/R2. *First step:* download and format-verify
   the 31 non-DJI RFUAV files (dataset-librarian), confirm sample rate/IQ layout, label by vendor.
2. **ExpressLRS 2.4 GHz raster + period estimator validation.** The only non-DJI link where every number in
   the acceptance criteria is a primary firmware constant, so a pass/fail is unambiguous. *First step:* decide
   the capture route under §4's no-transmit constraint — recorded IQ if any can be sourced, otherwise an FPV
   field session; do **not** task a builder with "borrow an ELRS TX and key it."
3. **Analog 5.8 GHz FPV carrier-grid detector.** Highest ratio of field prevalence to effort: continuous
   carriers on documented fixed grids, no hop-following, no decode, no legal ruling needed for detection, and
   it extends AERIX beyond its current 2.4-only posture. *First step:* a HackRF sweep of 5645–5945 MHz at an
   FPV flying field to confirm the F/Raceband grid structure appears as predicted.

Deliberately **not** in the top 3: SiK (highest decode value but blocked on FLAG-A and on having any capture at
all), Autel/Skydio/Walksnail (no protocol foothold), Crossfire/Futaba (closed, detection-only).

## 6. Machine-testable acceptance criteria (per target, for whoever builds)
- **ExpressLRS 2.4 raster:** over a capture containing a known ELRS link, R1 reports `spacing_hz = 1.000e6 ± 20 kHz`
  with `rayleigh_r ≥ 0.93`, `n_channels ≥ 10`, and `offset_hz ≡ 0.400 MHz (mod 1.000 MHz) ± 100 kHz` after LO
  calibration; R2 reports `t_hat_s` within 2 % of the configured packet interval from `common.h`. False alarms
  on the 571 ANTSDR ambient windows: 0.
- **RC-vendor family classifier:** per-vendor balanced accuracy reported with a **cross-recorder** split (train
  RFUAV, test AERIX-captured) — an in-corpus-only score is not acceptance evidence.
- **Analog 5.8 detector:** ≥3 simultaneous carriers whose centres fit one of the documented grids (F: 5740+20n,
  R: 5658+37n, B: 19 MHz) with residual < 2 MHz; report measured centres, **never a band letter**, since
  5880 = F8 = R7 and 5732/5733 collide.
- **SiK (if FLAG-A is cleared):** de-hopped GFSK frames that pass Golay correction and yield MAVLink frames whose
  CRC-16 checks against the message-specific `CRC_EXTRA`; a decoded `GLOBAL_POSITION_INT` must round-trip against
  operator-provided ground truth.

## 7. Claims that must NOT be made yet
- That AERIX "supports" any non-DJI system — nothing in this table has been validated against a capture yet.
- That Crossfire/FrSky/Futaba GPS is recoverable because CRSF/S.Port define GPS frames (serial layer ≠ air layer).
- Any FlySky AFHDS2A, DSMX, or Crossfire channel raster — none is primary-sourced; keep them out of the Δ dictionary.
- That RFUAV supports any decode claim; it contains no protocol-level captures and no telemetry ground truth.
- Any Walksnail/HDZero RF number as measured — all current figures are vendor marketing or unverified blogs.

## 8. Research gaps (route to `research-librarian` if reopened)
- `RESEARCH NEEDED:` does DIY-Multiprotocol-TX-Module's source contain primary channel/hop tables for AFHDS2A,
  DSM2/DSMX and FrSky D/X? It is open firmware that *implements* these protocols and is the single most likely
  path from COMMUNITY to PRIMARY for four vendors at once. Only a CSDN summary of it is in the corpus.
- `RESEARCH NEEDED:` ExpressLRS true on-air burst duration per rate (not `interval`) — needs the target-specific
  rate-config array, unresolved in `rc-link-raster-facts.md` §2.
- `RESEARCH NEEDED:` any public IQ of a SiK/ELRS/mLRS/Crossfire link anywhere. Corpus says none exists; a
  targeted re-check is cheap and would unblock target 2 without any transmission.
- Unresolved: OpenHD/wifibroadcast encryption status by version; Walksnail occupied bandwidth (measurement task,
  needs ANTSDR); Herelink/SIYI/Skydroid modem PHY identification.
