# RC/control-link raster facts for Stage-1 signature vocabulary

**Question:** five discriminator facts requested by `docs/design/stage1-link-signatures.md` §11 (items 1-5): DJI RC
2.4 GHz uplink raster, ExpressLRS air-time-per-rate, FlySky AFHDS2A channel plan, BLE hop-increment behaviour, and
real-world Wi-Fi beacon-interval spread.

## 1. DJI RC 2.4 GHz uplink hop-set span / channel count / raster offset — **UNKNOWN (BLOCKING, unresolved)**
No primary numeric source found this pass. NDSS'23 (Schiller et al.) states only that "the control uplink uses
frequency hopping with narrower [channels than the 20 MHz OFDM downlink]," sourced generically to "the FCC ID
database" with **no channel count, spacing, span, or offset given** in the paper text (checked full body, not just
abstract). Their citation [15] (`FCC ID SS3-MT2WD2007`, DJI Mini 2) is cited elsewhere in the paper for RC hardware,
not for this sentence. I attempted to pull that filing's test-report exhibits directly (`fccid.io`, `fcc.report`,
and `apps.fcc.gov/oetcf/eas` — the FCC's own OET database) — **all three returned HTTP 403 (Akamai/anti-bot block)**
from this sandbox; this is a network-access limitation, not evidence that the data doesn't exist. A DJI/Qualcomm
patent that looked promising (`EP3659264A1`, "Frequency hopping in an uplink control channel") is an **unrelated
Qualcomm LTE/NR PUCCH patent**, not DJI RF — false lead, discard. The local 17-article leegang12 DJI corpus (our
densest DJI source) covers DroneID-broadcast and OFDM/ZC physical layer only — zero hits for "跳频"/"hopping" — it
does not cover the RC→aircraft control uplink at all.
**How Stage-1 should use it:** §2(e)'s BLE-vs-DJI-RC raster separation **cannot be evidence-based today**. Do not
hardcode a DJI-RC raster/offset value. Two paths forward: (a) architect routes a live HackRF/ANTSDR capture of an
actual DJI RC transmitting (RC powered, no aircraft link needed) to `hardware-architect`/device specialists —
this is now the only way to close the gap short of buying FCC exhibit access from a non-blocked network; (b) accept
the rule stays gated behind "co-located 20 MHz OFDM downlink present" (already true per §2(e)) rather than raster
alone, and treat this as a permanent design constraint, not a temporary unknown.

## 2. ExpressLRS air-time per packet, 50 Hz–1000 Hz — **PRIMARY for period, UNKNOWN for on-air duration**
`src/include/common.h` (`ExpressLRS/ExpressLRS`, fetched from GitHub `master` this pass) defines
`expresslrs_mod_settings_s.interval`, commented **"interval in us [that] corresponds to that frequency"** — i.e.
the packet *repetition period*, not the transmitted symbol duration:
50 Hz → 20000 µs, 150 Hz → 6667 µs, 250 Hz → 4000 µs, 500 Hz (LoRa) → 2000 µs, 1000 Hz (`RATE_FLRC_2G4_1000HZ`) →
1000 µs. These period values are PRIMARY (shipping firmware header, directly quoted) and match `FHSS.cpp`'s 80×1 MHz
channel table (`FREQ_HZ_TO_REG_VAL(2400400000)`…`2479400000`, sync channel = count/2+1) already in the corpus. The
*actual on-air transmission duration* (SF/BW/CR-dependent for LoRa, bitrate-dependent for FLRC — always shorter
than `interval`) lives in a rate-config array we did not locate in `src/lib/{SX1280Driver,OTA}` this pass (not a
negative result — likely in a target-specific `tx_main.cpp`/`rx_main.cpp` not checked; budget-limited). Secondary
sources (blog posts) conflate "20 ms airtime at 50 Hz" with the period above — **do not cite that as on-air
duration**.
**How Stage-1 should use it:** the `interval` values above are safe, primary-grade edges for the *hop-cadence*
(packets-per-second / re-hop timing) part of the duration histogram; do **not** use them as the occupied-burst-width
edge — that still needs either a firmware follow-up read of the target-specific rate table or a bench measurement
(route to `sdr-backend-builder`/`hackrf-specialist` if precision on the burst-width edge specifically is needed).

## 3. FlySky AFHDS2A channel spacing/count/hop rate — **COMMUNITY/UNKNOWN, do not admit to Δ dictionary**
No primary source (firmware, decompiled binary, or FCC filing) found in the local corpus or via web this pass. The
corpus's own `non_dji_telemetry/RC_telemetry/FlySky/NOTES.md` states explicitly: "No RF air-interface RE" — only
iBUS/PPM *serial*-layer parsing has been reverse-engineered locally, not the 2.4 GHz FHSS air interface. Public web
search this pass surfaced no FCC-grade or firmware-grade AFHDS2A channel table either (multiprotocol-TX-module
implementations exist per the corpus but were not verified as primary this pass).
**How Stage-1 should use it:** confirms the design doc's own caution — leave AFHDS2A out of the Δ dictionary until
someone reads the actual multiprotocol-module AFHDS2A source (a bounded follow-up request, not done here) or an FCC
filing is reachable.

## 4. BLE channel-selection Algorithm #1/#2 hop-increment + connection-interval lattice — **PRIMARY (well-established spec facts)**
- **Algorithm #1** (mandatory, BT4.0+): `hopIncrement` is drawn from the integer range **[5, 16]** (11 possible
  values) — Bluetooth Core Specification Vol 6, Part B, §4.5.8 (cross-confirmed via MathWorks' Bluetooth Toolbox
  reference page, which quotes the spec range directly). Successive selected channels differ by this fixed
  increment (mod 37, with the "remap" table skipping bad channels) — a **regular, small-increment lattice**.
- **Algorithm #2** (BT5.0+, used whenever both sides support it): channel is a PRNG function of the event counter +
  access address, not a fixed increment — **effectively pseudorandom** across the used-channel set, no fixed-delta
  discriminator available.
- **Connection interval**: 7.5 ms – 4.0 s in 1.25 ms steps — standard Core-spec Vol 6 Part B §4.5.1 parameter
  (high-confidence, textbook fact, not separately re-verified against spec PDF this pass but not disputed anywhere).
**How Stage-1 should use it:** hop-increment is **not usable as a blind RF (undecoded) discriminator** — you cannot
observe `hopIncrement` without demodulating the access address and payload, so it does nothing for a spectrogram/
burst-only detector. What *is* passively observable is the **connection-interval periodicity itself**: a BLE
connection's burst cadence is quantised to 1.25 ms steps inside [7.5 ms, 4 s] — already captured by §5's
`ble_connection_like` cadence check; this item doesn't add a new blind feature, it only explains *why* Algorithm #2
links look more random than #1 ones if anyone ever gets far enough to decode channel maps. Recommend not spending
further budget trying to make hop-increment a Stage-1 feature.

## 5. Real-world Wi-Fi beacon-interval spread around 102.4 ms — **COMMUNITY (credible practitioner sources), Medium confidence**
Nominal is exact: 100 TU × 1.024 ms/TU = 102.4 ms (802.11 standard, high confidence). TBTT is a *target*, not a
guarantee: per CWNP and Intuitibits (established Wi-Fi practitioner technical sites, not peer-reviewed, but
consistent with 802.11 medium-access rules) actual beacons are delayed — never early — by CSMA/CA contention when
the medium is busy at TBTT; under load this produces a **one-sided, right-skewed jitter** (some intervals well over
102.4 ms, essentially none under). No specific quantitative jitter-distribution paper was found this pass (searched
directly; none returned). Clock-drift-induced jitter (oscillator ppm error) is a separate, much smaller effect than
contention-induced delay in busy environments.
**How Stage-1 should use it:** §9's ±2% beacon-interval discount tolerance should probably be **asymmetric**
(tighter early-side, looser late-side) rather than symmetric, since real deviation is contention-driven and
one-directional — flag this as a design suggestion to `rf-dsp-specialist`, not a hard number (no measured percentile
table exists to set the late-side bound precisely).

## DIY-Multiprotocol primary tables (2026-09-19)

**Question:** does the open-source DIY-Multiprotocol-TX-Module firmware (`pascallanger/DIY-Multiprotocol-TX-Module`,
GitHub, `master` branch) contain primary channel/hop-table and packet-timing facts for FlySky AFHDS2A, Spektrum
DSM2/DSMX, and FrSky D/X? **Yes** — this firmware transmits these protocols from real hardware (A7105/CYRF6936/CC2500
radio ICs), so its channel-selection and timing code is a **PRIMARY, directly-quotable source** for the OTA raster,
upgrading all three rows below from COMMUNITY/UNKNOWN. Grade: **PRIMARY (open firmware implementing the protocol)**.
Mirrored locally at `research/library/rc_firmware/diy_multiprotocol/{AFHDS2A_a7105.ino, DSM_cyrf6936.ino,
FrSkyX_cc2500.ino, FrSkyD_cc2500.ino, A7105_SPI.ino}` (fetched raw from GitHub `master`, 2026-09-19; gitignored, not
committed to the repo per project policy on raw library files).

### FlySky AFHDS2A (A7105, `AFHDS2A_a7105.ino`)
- **Hop set size:** 16 channels (`AFHDS2A_NUMFREQ = 16`), selected per-bind from a 164-channel universe.
- **Channel derivation (`AFHDS2A_calc_channels()`):** `band_no = ((idx<<1 | (idx>>1)&1) + rx_tx_addr[3]) & 3` (i.e.
  a 4-way band selection keyed off the low byte of the bound TX address), then
  `next_ch = band_no*41 + 1 + (rnd>>idx) % 41` — channel range **1..164** (A7105 channel-register units, not raw
  MHz), with a minimum spacing of 5 channel-units enforced between any two of the 16 selected channels
  (`if(distance<5) retry`). `rnd` is address-derived, so the hop set is fixed per bound TX/RX pair, not
  re-randomized per session — matches the known AFHDS2A behaviour that a given transmitter always reuses the same
  16-channel set after binding.
- **Channel-to-frequency mapping:** register-level only (`A7105_WriteReg(A7105_0F_PLL_I/CHANNEL, channel)`), LO base
  programmed to 2400 MHz (`bip=0x4b // 2400MHz (default)` in `A7105_AdjustLOBaseFreq()`). The exact channel-unit-to-
  MHz step was **not resolved from source this pass** (would need the A7105 datasheet's channel-spacing register
  cross-referenced against the `FLYSKY_A7105_regs[]`/`AFHDS2A_A7105_regs[]` init tables in `A7105_SPI.ino`, budget did
  not allow); the commonly-cited 1 MHz/channel-unit step for A7105 FlySky variants is a **COMMUNITY** figure, not
  confirmed here — do not upgrade that specific number to PRIMARY.
- **Packet period:** fixed **3850 µs air-interface cycle** (`return 3850-AFHDS2A_WRITE_TIME;` / `return 3850;` in the
  state machine, i.e. ~259.7 Hz RF packet rate) — independent of the AFHDS2A_PACKET_SETTINGS servo-refresh-rate field
  (50-400 Hz, user-configurable, encoded in packet payload, not the RF cadence itself). **Do not conflate the
  50-400 Hz "refresh rate" setting with the fixed ~3850 µs RF packet period** — a common confusion point.

### Spektrum DSM2/DSMX (CYRF6936, `DSM_cyrf6936.ino`)
- **Frame period:** two hardware-supported cadences selected by channel count and a mode flag
  (`MODE_11MS_BIT_MASK`): **11 ms** (channel counts 8-11, high-rate/high-channel-count mode) and **22 ms** (default,
  3-12 channels, lower rate) — comments in source: "22+11ms for 3..7 channels", "22ms for 8..12 channels", "11ms for
  8..11 channels". DSM2_SFC variant uses a distinct **16500 µs (16.5 ms)** period (`DSM2_SFC_PERIOD = 16500`).
  `DSM_CH1_CH2_DELAY = 4010 µs` is the fixed intra-frame gap between the channel-1 and channel-2 sub-packet writes
  within one frame (DSM transmits 2 packets per frame on 2 different channels for diversity/redundancy).
- **Hop-channel derivation:** channel selection is **not** a simple arithmetic hop formula like AFHDS2A/FrSky — it
  uses a bind-time pseudo-random-derived channel table (`DSMR_ID_FREQ[row][...]` lookup keyed by a bind ID, plus a
  `tmpch[]` candidate-selection loop enforcing minimum spacing between the two active channels, mirrored at
  `hopping_frequency[0]`/`[1]`). Full table-generation algorithm was visible in source but not fully traced this
  pass (719-line file, budget-limited) — sufficient to confirm PRIMARY existence of a hop table, not to reproduce it
  byte-for-byte here.
- **Bind channel:** fixed at CYRF channel `0x0D` (13) for the bind phase (`DSM_BIND_CHANNEL`), separate from the
  post-bind hop set.

### FrSky D and FrSky X (CC2500, `FrSkyD_cc2500.ino` / `FrSkyX_cc2500.ino`)
- **Hop set size:** **47 channels** for both D and X variants — `hopping_frequency[counter % 47]` (FrSkyD) and
  `hopping_frequency_no = (hopping_frequency_no + FrSkyX_chanskip) % 47` (FrSkyX, which additionally uses a
  bind-derived `FrSkyX_chanskip` stride instead of a fixed +1 step, so the visit *order* through the 47 channels is
  session/bind-specific even though the *set size* is always 47).
- **Packet period:** fixed **9000 µs (9 ms, ~111 Hz)** RF frame rate for both D and X in the common case
  (`return 9000;` / `telemetry_set_input_sync(9000);` in both files). FrSkyD has one shortened observed interval,
  `7500 µs` on a specific telemetry sub-state (`FRSKY_DATA4`); FrSkyX has region-variant sub-timings (LBT vs FCC:
  4000/5200/4200/3400 µs) for internal telemetry/CCA windows, not the main 9 ms hop cadence itself — **do not treat
  the 4000-5200 µs values as the packet period**, they are sub-state timings inside the 9 ms frame.
- **Channel-to-frequency mapping:** written directly to the CC2500 `CHANNR` register per hop
  (`CC2500_WriteReg(CC2500_0A_CHANNR, hopping_frequency[...])`); actual MHz-per-register-step depends on the
  CC2500 base-frequency/channel-spacing register config, which was **not traced this pass** (same limitation as
  AFHDS2A above) — treat any specific MHz-spacing claim for FrSky D/X as still COMMUNITY until the CC2500 config
  table is read.

### Net effect on the design-doc raster table
FlySky AFHDS2A, Spektrum DSM2/DSMX, and FrSky D/X all move from **COMMUNITY/UNKNOWN → PRIMARY** for hop-set size and
RF packet period (the two facts most directly useful for a blind cadence/hop-count Stage-1 discriminator). The
channel-to-RF-frequency step size for all three remains **COMMUNITY-grade or unresolved** — a live capture or a
deeper register-table read (A7105/CC2500 datasheet cross-reference) is still needed before any absolute-frequency
raster claim for these three protocols can be called PRIMARY.

### Sources (this addendum)
- GitHub `pascallanger/DIY-Multiprotocol-TX-Module`, `master` branch, fetched raw 2026-09-19:
  - `Multiprotocol/AFHDS2A_a7105.ino` — https://raw.githubusercontent.com/pascallanger/DIY-Multiprotocol-TX-Module/master/Multiprotocol/AFHDS2A_a7105.ino
  - `Multiprotocol/DSM_cyrf6936.ino` — https://raw.githubusercontent.com/pascallanger/DIY-Multiprotocol-TX-Module/master/Multiprotocol/DSM_cyrf6936.ino
  - `Multiprotocol/FrSkyX_cc2500.ino` — https://raw.githubusercontent.com/pascallanger/DIY-Multiprotocol-TX-Module/master/Multiprotocol/FrSkyX_cc2500.ino
  - `Multiprotocol/FrSkyD_cc2500.ino` — https://raw.githubusercontent.com/pascallanger/DIY-Multiprotocol-TX-Module/master/Multiprotocol/FrSkyD_cc2500.ino
  - `Multiprotocol/A7105_SPI.ino` — https://raw.githubusercontent.com/pascallanger/DIY-Multiprotocol-TX-Module/master/Multiprotocol/A7105_SPI.ino (register init tables only, channel-spacing not resolved)
- GitHub repo file listing via `api.github.com/repos/pascallanger/DIY-Multiprotocol-TX-Module/contents/Multiprotocol`
  (used to find the correct FrSky filename set).

## Sources
- NDSS'23 Schiller et al. (`research/library/.../ndss2023_f217_paper.pdf` reference; re-fetched+`pdftotext`'d this
  pass from `ndss-symposium.org`), full text scanned for FCC/hop/channel mentions.
- `fccid.io`, `fcc.report`, `apps.fcc.gov/oetcf/eas` — attempted, all HTTP 403 this pass (network-blocked, not
  evidence-negative).
- `patents.google.com/patent/EP3659264A1` — checked and discarded (unrelated Qualcomm LTE patent).
- GitHub `ExpressLRS/ExpressLRS` `master` branch: `src/include/common.h` (rate enum + `interval` field, fetched
  raw), `src/lib/FHSS/FHSS.cpp`/`FHSS.h` (already in local corpus, channel table cross-checked).
- `research/library/csdn_enriched/AERIX_RF_CSDN/non_dji_telemetry/RC_telemetry/FlySky/NOTES.md` (local, read).
- Bluetooth Core Specification Vol 6 Part B §4.5.8 (hop increment) / §4.5.1 (connection interval) — via
  `mathworks.com/help/bluetooth/...` secondary confirmation, spec itself not directly fetched this pass.
- CWNP (`cwnp.com/cwnp-wifi-blog/80211-beacon-intervals`), Intuitibits (`intuitibits.com/2017/08/28/...`) —
  practitioner technical write-ups on TBTT/beacon jitter.

## SiK datasheet confirmation & public IQ (2026-09-19)

**Q1 — Si4432/Si1000 (EZRadioPRO) POR sync word, CRC option, freq-deviation LSB, data-rate scaling; which
CRC SiK firmware selects.**

Confidence: **High** (primary datasheet + primary firmware source, both directly read this pass).

- Source: Silicon Labs **AN440 Rev 0.9**, "Si4430/31/32 Register Descriptions" (`silabs.com/documents/public/
  application-notes/AN440.pdf`), mirrored to `research/library/datasheets/
  Silabs_AN440_Si4430-31-32_Register_Descriptions.pdf` (gitignored, not committed).
- **Sync word registers 0x36–0x39** ("Sync Word 3..0"): POR defaults are `0x36=2Dh, 0x37=D4h, 0x38=00h,
  0x39=00h` (AN440 register table, p.~5 register-map row, detailed register section ~line 81-84 of extracted
  text). SiK's `radio_443x.c` never writes these registers (`grep -i sync` on the file matches only
  `HEADER_CONTROL_2` sync-length config, no `SYNC_WORD_*` writes) — so the POR default stands. SiK configures
  2-byte sync via `EZRADIOPRO_SYNCLEN_2BYTE` in `HEADER_CONTROL_2` (0x33), which per AN440 uses the top two
  sync bytes → **effective on-air sync word is `0x2D 0xD4`**, confirming the design doc's "0x2DD4" expectation
  exactly (not "0x2DD400" or a 4-byte value).
- **CRC**: register **0x30 "Data Access Control"**, bits `encrc` (D2) and `crc[1:0]` (D1:D0). AN440 gives the
  polynomial table: `00=CCITT, 01=CRC-16 (IBM), 10=IEC-16, 11=Biacheva`. **POR reset value of 0x30 is `0x8D`
  = `1000_1101`**, i.e. `encrc=1` and `crc[1:0]=01` already at power-on — so CRC-16(IBM) with hardware CRC
  enabled is the chip's *default*, not something SiK must actively select. SiK's `radio_443x.c` (line ~840)
  nonetheless explicitly writes `EZRADIOPRO_ENCRC | EZRADIOPRO_CRC_16` in the non-Golay code path (constants
  defined in `Firmware/include/Si1000_defs.h`: `EZRADIOPRO_CRC_16 = 0x01`, `EZRADIOPRO_ENCRC = 0x04`),
  reasserting the POR default → **SiK uses hardware CRC-16 (IBM polynomial)** when not in Golay/FEC mode. In
  the Golay-encoding path (`feature_golay==true`), SiK instead computes its **own software CRC-16** (`crc.c`,
  ArduPilot's own table-driven CRC-16, not the Si4432 hardware engine) and Golay-encodes it, because Golay
  needs bit-error correction before the CRC check — confirmed by the code comment at line ~825-827.
- **Frequency deviation**: register 0x72, POR default `0x20`. AN440 formula (line ~2373): `Fd = 625 Hz ×
  fd[8:0]` (9-bit value, MSB `fd[8]` lives in register 0x71 D2). Confirms the design doc's 625 Hz LSB exactly.
- **TX data rate scaling**: registers 0x6E/0x6F (`txdr[15:0]`), POR default `0x0A3D` = 40 kbps (AN440 states
  this explicitly). Formula: `TX_DR = 10^6 × txdr[15:0] / 2^16 bps` if Modulation-Mode-Control-1 (0x70) bit 5
  = 0, or `/2^21` if that bit = 1 (low-data-rate mode). SiK's own rate table (`radio_443x.c` ~line 668-670)
  writes `TX_DATA_RATE_1/0` and `FREQUENCY_DEVIATION` per selected air rate from its own precomputed constant
  tables (2.4/4.8/9.6/19.2/38.4/57.6/64/125/250 kbps rows) rather than computing the formula at runtime —
  the per-rate register bytes in those tables are consistent with the AN440 formula (spot-checked the 64 kbps
  row: not re-derived digit-by-digit this pass, treat as **Medium** for the specific per-row byte values,
  **High** for the formula and defaults themselves).

**Q2 — Public raw IQ of SiK/3DR/RFD900 telemetry.**

Result: **none found**. Searched GitHub ("gr-sik", "3DR radio" sigmf, RFD900 iq recording), Zenodo/IEEE
DataPort/Kaggle (via general web search, not queried natively — no API access from this environment), and
GNU Radio's SigMF recordings wiki page. No dataset, repo, or mailing-list attachment surfaced containing a
labeled SiK/3DR/RFD900 telemetry IQ capture. Adjacent-but-not-matching hits: `sigmf/SigMF` (spec repo, no
data), `danidask/SiKset` (a CLI *setup* tool, not captures), `ArduPilot/SiK` (firmware source, already
in local corpus), a `LakeShark-Signal-Corpus` repo advertising "reviewed SigMF IQ recordings for open radio
decoder testing" — **not verified to contain SiK/telemetry signals specifically**; if this becomes relevant,
someone should open the repo and check its manifest before relying on it (flagging as unread, not vetted).
No DEF CON/BlackHat drone-talk capture matching SiK/RFD900 turned up in this pass either. **Conclusion:
opportunistic field recording (already noted in the design doc as the user's call) remains the only known
route to real SiK ground-truth IQ.**

## Open follow-ups (not done this pass, name if reopened)
- DJI RC uplink raster: needs either a non-sandboxed FCC exhibit fetch or a live capture — architect decision.
- ExpressLRS true on-air duration table: needs a deeper firmware read (`tx_main.cpp`/rate-config array) or bench
  measurement.
- ~~FlySky AFHDS2A: needs a multiprotocol-TX-module firmware source read~~ — DONE 2026-09-19, see "DIY-Multiprotocol
  primary tables" addendum above (hop-set-size and packet-period now PRIMARY; MHz-per-channel-step still open).
- A7105/CC2500 channel-register-to-MHz step size (affects AFHDS2A, FrSky D/X absolute frequency raster): needs a
  datasheet cross-reference against `A7105_SPI.ino`'s `*_A7105_regs[]` init tables / the CC2500 base-freq registers
  in `CC2500_SPI.ino` (not fetched this pass) — or a live capture measuring actual hop spacing.
- Spektrum DSM2/DSMX bind-derived hop-table generation algorithm (`DSMR_ID_FREQ[]` lookup + `tmpch[]` selection
  loop in `DSM_cyrf6936.ino`): PRIMARY existence confirmed, full derivation not traced line-by-line this pass.
