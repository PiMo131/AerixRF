---
name: rc-link-raster-facts-2026-09-19
description: Stage-1 §11 five-item research answers (DJI RC uplink raster, ExpressLRS air-time, FlySky AFHDS2A, BLE hop-increment, Wi-Fi beacon jitter) and the FCC-access dead end
metadata:
  type: project
---

Answered `docs/design/stage1-link-signatures.md` §11 items 1-5, written to
`research/briefs/rc-link-raster-facts.md`. Key things worth remembering so I don't retry the
same dead ends:

## FCC filing mirrors are all network-blocked from this sandbox
`fccid.io`, `fcc.report`, and even `apps.fcc.gov/oetcf/eas` (the FCC's own OET database) all
returned **HTTP 403** (Akamai/anti-bot) to both `curl` and `WebFetch` this pass. Tried:
`fcc.report/FCC-ID/SS3-T161906/...`, `fccid.io/SS3-MT2WD2007`, `fcc.report/FCC-ID/SS3-MT2WD2007/5783297.pdf`,
`apps.fcc.gov/oetcf/eas/reports/GenericSearch.cfm`. **Don't retry these URLs expecting a
different result** — this is a sandbox network-egress limitation, not evidence the documents
don't exist. If DJI RC uplink hop-set parameters are ever needed again, this route needs either
a non-sandboxed fetch (ask the user to pull the PDF and drop it in `research/library/`) or a
live RF capture instead.

## DJI RC 2.4 GHz uplink raster — still genuinely unknown (item 1, BLOCKING per architect)
NDSS'23 (Schiller et al.) only says the control uplink is "frequency hopping with narrower
[channels]" than the 20 MHz OFDM downlink, sourced generically to "the FCC ID database" with
**no numbers** (checked full text this pass, not just the abstract — confirmed no citation
number attached to that specific sentence). Their actual FCC citation ([15], `SS3-MT2WD2007`,
DJI Mini 2) is used elsewhere for RC hardware, not this claim. `EP3659264A1` ("frequency
hopping in an uplink control channel") looked promising from a search snippet but is an
**unrelated Qualcomm LTE/NR PUCCH patent** — false lead, don't re-check it. The local leegang12
17-article DJI corpus (our best DJI source) is 100% DroneID-broadcast/OFDM/ZC physical layer —
zero mentions of RC-to-aircraft uplink hopping. This gap has no known primary source in reach;
only a live capture or a non-sandboxed FCC pull can close it.

## ExpressLRS — period vs. air-time distinction matters
`src/include/common.h` on GitHub `ExpressLRS/ExpressLRS` `master` (fetched raw this pass) gives
`interval` (the packet **period**, i.e. 1/rate) as a PRIMARY, directly-quotable value: 50Hz=
20000us, 150Hz=6667us, 250Hz=4000us, 500Hz(LoRa)=2000us, 1000Hz(FLRC)=1000us. This is **not**
the on-air transmission duration (which is shorter and SF/BW/CR- or bitrate-dependent) — I did
not locate the actual rate-config array with preamble/payload timing in `src/lib/{SX1280Driver,
OTA}` (checked `SX1280.h`, `SX1280Driver.h`, `OTA.h` — none had it; likely in a target-specific
`tx_main.cpp`/`rx_main.cpp` not checked due to budget). Secondary blogs conflate "20ms airtime
at 50Hz" with this period value — don't repeat that conflation.

## FlySky AFHDS2A — confirmed still COMMUNITY/UNKNOWN
Local `FlySky/NOTES.md` says explicitly "No RF air-interface RE" (only iBUS serial layer is
reverse-engineered locally). No FCC/firmware primary found via web this pass either. Matches
the design doc's own caution not to admit AFHDS2A to the Δ dictionary yet.

## BLE hop-increment is not a usable blind-RF discriminator
Algorithm #1 hopIncrement ∈ [5,16] (Bluetooth Core Spec Vol 6 Part B §4.5.8, confirmed via
MathWorks' toolbox docs which quote the spec range) — but this requires decoding the access
address/payload to observe, so it adds nothing to an undecoded spectrogram/burst detector.
Algorithm #2 (BT5.0+) is PRNG-based, no fixed increment. Connection-interval lattice (7.5ms-4s,
1.25ms steps) is the only part of this that's already a usable blind feature, and it's already
in §5's `ble_connection_like` rule — don't invent a new feature request around hop-increment.

## Wi-Fi beacon jitter is one-sided, not symmetric
102.4ms nominal (100 TU) is exact/high-confidence. Real deviation is CSMA/CA contention delay
— TBTT can only be **late**, never early, per CWNP/Intuitibits practitioner write-ups (no formal
measurement paper found). Suggested to `rf-dsp-specialist` via the brief: make the beacon-
interval tolerance asymmetric (tighter early bound, looser late bound) instead of symmetric
±2% — flagged as a design suggestion, not a hard number (no percentile table exists).

## DIY-Multiprotocol-TX-Module firmware closes the FlySky/DSM/FrSky hop-table gap
`pascallanger/DIY-Multiprotocol-TX-Module` GitHub `master` branch is a real, shipping open firmware that transmits
these protocols from actual radio ICs (A7105 for FlySky AFHDS2A, CYRF6936 for Spektrum DSM2/DSMX, CC2500 for
FrSky D/X) — its channel-selection and packet-timing code is PRIMARY evidence, not reverse-engineering inference.
Fetched+read (raw GitHub, 2026-09-19): `AFHDS2A_a7105.ino`, `DSM_cyrf6936.ino`, `FrSkyX_cc2500.ino`,
`FrSkyD_cc2500.ino`, `A7105_SPI.ino`. Mirrored at `research/library/rc_firmware/diy_multiprotocol/` (gitignored).
Full extracted tables are in `research/briefs/rc-link-raster-facts.md` under "DIY-Multiprotocol primary tables
(2026-09-19)" — don't re-derive, just cite that section. Key numbers for quick recall:
- **AFHDS2A**: 16 hop channels out of a 164-channel universe (`band_no*41+1+(rnd%41)`, min spacing 5 units),
  fixed **3850 µs** RF packet period (~260 Hz) — this is NOT the same as the 50-400 Hz servo-refresh field in the
  settings packet, don't conflate them.
- **Spektrum DSM2/DSMX**: frame period is **11 ms** (8-11 channel, high-rate mode) or **22 ms** (default,
  3-12 channels); DSM2_SFC variant uses 16.5 ms. Hop-channel selection is bind-ID-keyed table lookup
  (`DSMR_ID_FREQ[]`), not simple arithmetic — confirmed to exist, not fully traced line-by-line.
- **FrSky D and X**: both use **47 hop channels**, fixed **9000 µs (9 ms, ~111 Hz)** RF packet period. FrSkyX adds
  a bind-derived `chanskip` stride (visit order through the 47 channels varies per bind) instead of FrSkyD's fixed
  +1 step. Don't mistake FrSkyX's region-variant sub-state timings (4000/5200/4200/3400 µs, LBT vs FCC telemetry/CCA
  windows) for the main packet period — those are inside one 9 ms frame, not the frame period itself.
- **Not resolved this pass** (still COMMUNITY-grade or open): the actual MHz-per-channel-register-step for A7105
  (AFHDS2A) and CC2500 (FrSky D/X) — would need a datasheet cross-reference against the `*_A7105_regs[]` init
  tables in `A7105_SPI.ino` or the CC2500 base-frequency registers (not fetched). If asked for absolute-frequency
  raster (not just hop-count/period) for these three protocols, this is the next thing to fetch, not a re-read of
  what's already mirrored.
