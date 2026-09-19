# Passive decode design: SiK-class telemetry radios carrying MAVLink

Owner: `rf-protocol-analyst`, 2026-09-19. Scope: **passive receive only**. No transmission of any kind.
User ruling on record: passive decoding of third-party MAVLink over SiK/mLRS is **approved for research**
(FLAG-A cleared for research use; retention rules in §3 still apply).

Primary source for §1 unless stated: ArduPilot **SiK** firmware `Firmware/radio/{main,parameters,freq_hopping,
radio_443x,tdm,packet,golay}.c` (`research/library/.../SiK_3DR_Holybro/source/ArduPilot_SiK_master.zip`).
Grades: **PRIMARY** = read out of that source this pass. **INFERRED** = argued from chip datasheet behaviour or
firmware we did not read line-by-line. Version scope: SiK master, **Si1000/Si4432 (`radio_443x.c`) boards**
(3DR/Holybro/RFD900a/p, mRo900). RFD900**x**/Si446x (`radio_446x.c`) is a *different* register set and is out of
scope for every number below.

## 1. SiK PHY from the firmware

**Modulation / rates.** 2-level GFSK, Si4432 packet handler. Air data rates (`air_data_rates[]`, kbps):
`2, 4, 8, 16, 19, 24, 32, 48, 64, 96, 128, 192, 250`. Default `AIR_SPEED=64`. Rate selection picks the first
table entry ≥ the requested value. Optional Manchester (`MANCHESTER`, default 0, unavailable >128 kbps) — when
on, on-air symbol rate is **2×** the air rate. **PRIMARY.**

**Deviation / modulation index.** Register table row 12 is `EZRADIOPRO_FREQUENCY_DEVIATION` (0x72):
`0x03,0x06,0x0D,0x1A,0x1E,0x26,0x33,0x4D,0x66,0x9A,0xCD,0xFE,0xFE` (PRIMARY). Converting with the Si4432 FD step
of **625 Hz/LSB** (INFERRED — datasheet, not in firmware) gives Δf ≈ 1.875, 3.75, 8.13, 16.25, 18.75, 23.75,
31.88, 48.13, 63.75, 96.25, 128.1, 158.75, 158.75 kHz, i.e. **Δf ≈ R_b (h = 2Δf/R_b ≈ 2.0)** for 8–128 kbps,
h ≈ 1.875 at 2/4 kbps, and a **deviation ceiling at 158.75 kHz** giving h ≈ 1.65 at 192 kbps and **h ≈ 1.27 at
250 kbps**. Carson occupied BW ≈ 2(Δf + R_b/2) ≈ 2·R_b for h≈2 → ~192 kHz at 64 kbps (fits the 250 kHz raster),
but ~570 kHz at 250 kbps (**adjacent channels overlap at max rate** — a real demod constraint, INFERRED).

**Band plans and channel raster** (`main.c` board defaults; all PRIMARY):

| Board band | freq_min | freq_max | default `num_channels` | spacing = (max−min)/(N+2) |
|---|---|---|---|---|
| 433 | 433.050 MHz | 434.790 MHz | 10 | 145.0 kHz |
| 470 | 470.000 | 471.000 | 10 | 83.3 kHz |
| 868 | 868.000 | 870.000 | 10 | 166.7 kHz |
| 915 | 915.000 | 928.000 | **50 = `MAX_FREQ_CHANNELS`** | **250.0 kHz exactly** |

`MIN_FREQ`/`MAX_FREQ`/`NUM_CHANNELS` params (defaults 0 = "use board values") override these; `NUM_CHANNELS` is
clamped to [1, 50]. Base is then shifted: `freq_min += spacing/2`, and **if N > 5 a NETID-seeded pseudorandom
offset `(r_rand()*625) % spacing` is added** — so the absolute grid phase is unknown until NETID is known, but
the **spacing is not**. Caveat (INFERRED): the hop-step register is written in **10 kHz units**
(`scale_uint32(spacing, 10000)`, 8-bit, ≤2.55 MHz), so realised spacing is quantised to a multiple of 10 kHz —
exact at 915 (25), quantised at 433/868/470. Channel *k* centre = base + k·spacing, k = 0…N−1.

**Hop schedule.** `fhop_init()` fills `channel_map[i]=i` then applies a *naive* shuffle (ascending `i=0..n-2`, `j=((uint8_t)r_rand()) % n`, i.e. an 8-bit draw `(r_next>>16)&0xFF` modulo the whole array — NOT Fisher-Yates) with the LCG `r_next = r_next*1103515245 + 12345 (mod 2^32)` seeded by **`r_srand(seed)`**, seed = NETID on unencrypted links and `crc16(key)` when AES is enabled (so a recovered seed is only a NETID on unencrypted links). `raster.py::hop_map()` is a line-by-line transcription of `Firmware/radio/freq_hopping.c` (see `research/briefs/sik-freq-hopping-firmware.md`; test vector `hop_map(25,10)==[0,9,5,2,6,7,4,3,8,1]`). Channel 0 additionally sits at a seed-dependent offset within one spacing when N>5 (`main.c:417-428`) — raster *phase* is seed-dependent; not yet modelled (TODO, brief §6). (default NETID **25**). The transmit channel advances **+1 (mod N) at every TDM window change**, so the observed
physical sequence is a fixed cyclic permutation of period N. **PRIMARY.** If AES is compiled in *and* enabled the
seed becomes `crc16(32, key)` instead — the hop order is then not derivable from NETID.

**TDM timing.** `ticks_per_byte = (8 + 8000000/(air_rate·1000))/16 + 1` (16 µs ticks);
`packet_latency = (8+5)·ticks_per_byte + 13`; burst duration ≈ `packet_latency + len·ticks_per_byte`.
`MAX_WINDOW` default **131 ms** (13-bit window field limit). Dwell per channel = the TX window; the two ends
alternate windows with silence periods between. `DUTY_CYCLE` (default 100) and `LBT_RSSI` (default 0 = off)
change burst statistics on EU builds. **PRIMARY.**

**Preamble / sync.** `PREAMBLE_LENGTH = 16 nibbles = 64 bits` of alternating symbols; preamble *detection*
threshold 5 nibbles (20 bits). `HEADER_CONTROL_2` is written with `SYNCLEN_2BYTE` → **2 sync bytes**. The
firmware **never writes the sync-word registers** (grep: no `SYNC_WORD` write in `radio_443x.c`), so the value is
the Si4432 power-on default, conventionally **0x2DD4**. Grade: the *length* (2 bytes) and *non-override* are
PRIMARY; the *value* 0x2DD4 is **INFERRED** (datasheet default) → see §4 research gap.

**Packet framing.** Two mutually exclusive modes selected by `ECC` (default **0**):
- `ECC=0` (no Golay): hardware packet handler, `SYNCLEN_2BYTE` + **`HDLEN_2BYTE` header = the 16-bit NETID**
  (`TRANSMIT_HEADER_3 = netid>>8`, `_2 = netid&0xFF`, with `CHECK_HEADER` filtering on RX) + 1 length byte +
  payload + **hardware CRC-16**. Consequence: **NETID is transmitted in cleartext in every packet** — no search
  needed. (CRC-16 variant used by the Si4432 `ENCRC|CRC_16` setting is INFERRED, verify empirically.)
- `ECC=1` (Golay): sync only, no hardware header/CRC. On-air = `golay_encode({netid_lo, netid_hi, length})`
  (6 B) ‖ `golay_encode({crc16_lo, crc16_hi, length})` (6 B) ‖ `golay_encode(payload padded to ×3)`. Total
  `elen = (rlen+6)·2`. Golay(24,12), rate 1/2, corrects 3 bit errors per 12 data bits; `crc16()` is SiK's own,
  computed over the **unencoded** payload. NETID is again in the clear (just Golay-coded). **PRIMARY.**

`MAX_PACKET_LENGTH = 252`. The payload is the transparent serial stream **plus a 2-byte `tdm_trailer` at the
end** (`window:13, command:1, bonus:1, resend:1`; +2 bytes CRC on AES builds) — a decoder must strip it before
handing bytes to the MAVLink parser. **PRIMARY.**

**MAVLink layer.** `MAVLINK` param default **1** (PRIMARY); the framing-alignment logic lives in `mavlink.c`,
which was not read line-by-line this pass — the claim "radio packets tend to contain whole MAVLink messages" is
**INFERRED**. MAVLink framing itself is PRIMARY (protocol spec): v1 `STX=0xFE`, 6-byte header
(len, seq, sysid, compid, msgid), payload, CRC-16/MCRF4XX over bytes 1…end **plus the per-message `CRC_EXTRA`
byte**; v2 `STX=0xFD`, 10-byte header (len, incompat, compat, seq, sysid, compid, msgid[3]), zero-trimmed
payload, same CRC rule, plus a 13-byte signature when `incompat_flags & 0x01`.

**AES.** `INCLUDE_AES` is an optional build; `ENCRYPTION_LEVEL` default **0 (off)**. When enabled the payload is
encrypted and the hop seed changes → **detect/geolocate only, no decode**. **PRIMARY.**

## 2. Passive receiver design (fits the existing pipeline)

**Dwell.** One wideband dwell per band; the whole default hop set fits in a single capture.
- **915 (US/AU):** centre **921.5 MHz**, span 915–928 = 13 MHz → **15.36 MS/s** dwell covers it with margin.
  ANTSDR/AD9361 (70 MHz–6 GHz, 12-bit) is the preferred receiver; HackRF (1 MHz–6 GHz, 8-bit) can do 15–16 MS/s
  but with less dynamic range for weak bursts beside strong ISM neighbours.
- **868 (EU):** centre 869.0, 2 MHz span — any supported rate; **433:** centre 433.92, 1.74 MHz span.
- If `MIN_FREQ`/`MAX_FREQ` were customised the set can sit anywhere in the board's constrained range
  (433: 414–460; 868: 849–889; 915: 868–935) — the estimator must not assume the default edges.

**Chain.** dwell IQ → existing Stage-1 `detect_bursts` (`aerix_rf/detect/bursts.py:248`) → per burst:
centre-frequency and occupied-bandwidth estimate → snap to a candidate raster (spacing hypothesis from the set of
observed centres, not from a hardcoded table) → rate hypothesis from occupied BW (≈2·R_b at h≈2) cross-checked
against burst duration quantisation (`ticks_per_byte`) → channelise/decimate → quadrature/FM discriminator →
timing recovery (Gardner or M&M) at the hypothesised R_b → bit slice → **sync search for the 2-byte sync word,
trying both polarities and bit orders** → header parse (NETID, length) → Golay decode if ECC framing matches →
`crc16` / hardware-CRC check → strip `tdm_trailer` → MAVLink v1/v2 parse → **CRC + `CRC_EXTRA` validation**.

**Evidence mapping.** L1 burst candidate; L2 "SiK-like sub-GHz GFSK FHSS" from raster + burst-duration + window
cadence; **L3 protocol evidence** = sync word found and the *same* NETID recovered from ≥5 bursts on ≥3 distinct
channels; **L4 validated decode only on a MAVLink CRC_EXTRA pass** — never on sync/NETID alone.

**Hop-set / NETID handling.** Do **not** brute-force NETID: with either framing it is in the header in clear.
The observed channel order directly gives `channel_map` (useful for tracking one link across channels); NETID→map
confirmation via the LCG replay is an optional consistency check, not a prerequisite.

## 3. What is extractable, and the retention rule

Once MAVLink frames validate: `sysid`/`compid` (link/device identity), `HEARTBEAT` (airframe type, autopilot
type, base mode, system status), `GPS_RAW_INT`/`GLOBAL_POSITION_INT` (lat/lon/alt/heading/velocity),
`HOME_POSITION` (**operator/launch location**), `ATTITUDE`, `SYS_STATUS`, `BATTERY_STATUS`.

Retention: **aircraft position, home position and NETID/sysid are personal data** and take the **same 7-day
expiry as DroneID operator position**. The parser stays behind an explicit config flag
(e.g. `decode.third_party_mavlink`, default **off**) with the authorisation basis recorded; detection and L2/L3
classification remain available with the flag off. Video/content payloads over MAVLink are out of scope (FLAG-B).

## 4. Validation without transmitting

1. **Public IQ search (preferred, blocked).** Corpus position is that no public SiK/MAVLink IQ exists.
   `RESEARCH NEEDED:` targeted re-check by `research-librarian` of GitHub (`gr-*` OOT examples, `sigmf` sample
   collections), Zenodo, IEEE DataPort and SigMF-tagged archives for *any* 433/868/915 MHz SiK/3DR/RFD900
   recording, including bench captures published alongside telemetry-radio blog posts.
2. **Opportunistic field recording (user's decision).** Record at an FPV/RC/model field where ArduPilot/PX4
   operators are already transmitting for their own purposes. AERIX transmits nothing. This is the only route
   that yields real-world ground truth, and it is the **user's** call — no build task may assume it.
3. **Synthetic generator (unit tests only).** Build an encoder that mirrors the §1 framing exactly (preamble,
   sync, header, Golay, crc16, trailer, MAVLink) plus a GFSK modulator with configurable CFO/SNR/timing offset.
   **A synthetic-only pass is evidence level 1 and cannot support any claim that AERIX decodes SiK**, because the
   generator and the decoder share the same model assumptions (notably the unverified 0x2DD4 sync value and the
   CRC-16 variant). Synthetic results may only be reported as "decoder self-consistency verified".
   `RESEARCH NEEDED:` confirm the Si4432 POR sync word and the `ENCRC|CRC_16` polynomial from the Si4432
   datasheet/AN440 — both are single points of failure for real-signal sync.

## 5. Builder task split

| # | Task | Owner | Acceptance |
|---|---|---|---|
| T1 | GFSK burst demod: channelise, FM discriminate, timing recovery, bit slice | `python-builder` | On synthetic bursts at 2 / 64 / 250 kbps, CFO ±20 ppm, timing offset ±0.5 sym, SNR ≥ 12 dB: BER < 1e-3 and preamble/sync lock ≥ 99 % over 1000 bursts; graceful failure (no lock, no crash) at SNR ≤ 0 dB |
| T2 | SiK deframer: sync search, header, Golay(24,12), crc16, trailer strip, NETID extraction | `python-builder` | Bit-exact round trip against the firmware-faithful encoder in both `ECC=0` and `ECC=1` modes; corrects exactly 3 injected bit errors per Golay codeword and rejects 4; on 1e6 random byte streams, false frame-accept rate < 1e-6 |
| T3 | MAVLink v1/v2 parser behind `decode.third_party_mavlink` (default off) + 7-day expiry on position fields | `python-builder` | Parses `pymavlink`-generated streams 1:1 including v2 zero-trimming and signatures; zero CRC false-accepts on 1e6 random frames; `GLOBAL_POSITION_INT` field round-trip exact; with the flag off, zero position fields reach storage |
| T4 | Sub-GHz dwell config (433/868/915) + hop-raster/channel-count estimator feeding Stage-1 | `sdr-backend-builder` | On synthetic multi-channel captures recovers spacing within 5 kHz and channel count exactly for N ∈ {10, 50}; on existing ambient sub-GHz captures emits **0** SiK claims above L1 |

## 6. Risks

- **AES-enabled links** → payload encrypted *and* hop order reseeded: detect/geolocate only. Detect this case
  (sync + valid framing but persistent CRC failure) and report it explicitly rather than as a decode failure.
- **mLRS is not this PHY.** mLRS is LoRa/FLRC on SX12xx; it carries MAVLink natively but shares nothing below the
  payload. Do not reuse T1/T2 for it without a separate PHY brief.
- **Region split.** EU 868 builds use 10 channels, LBT and duty-cycle limiting (different burst statistics);
  US 915 uses 50 channels. A detector tuned on one will underperform on the other.
- **RFD900x / Si446x** boards use `radio_446x.c` — every register-derived number in §1 is out of scope for them.
- **Raster quantisation** (10 kHz hop-step units), the **NETID-seeded base offset**, `MANCHESTER`, and non-default
  `MIN_FREQ`/`MAX_FREQ`/`NUM_CHANNELS`/`AIR_SPEED` all break hardcoded values: infer, never assume.

## Independent review (test-reviewer, 2026-09-19, part A) — PASS WITH CONDITIONS

- 194 passed / 1 skipped (skip = pymavlink not installed, not a logic skip).
- BER: the **asserted and documented** figure is BER < 1e-3 at 12 dB in-band SNR (noise referenced to a 2·rate_bps
  bandwidth, i.e. Eb/N0 ≈ 15 dB; complex noise, bandwidth-normalised — verified). The "4.8e-5 at 12 dB" number
  quoted in an earlier status report was an ad-hoc measurement from the DSP rewrite session, NOT a committed
  assertion — treat < 1e-3 as the claim of record.
- Third-party MAVLink payload parsing is OFF by default (`decode_third_party_mavlink`, env override, tested);
  position/identity fields carry `retention_class=personal_7d`. Downstream *enforcement* of retention is outside
  this module and unverified here.
- No transmit/send/write-to-device code paths in `aerix_rf/decode/sik/` (receive-only confirmed).
- Evidence ladder as coded: level 1 any burst; level 2 `sik_like_hopper_candidate` (raster/Rayleigh + ≥5 bursts);
  level 3 `sik_netid_confirmed` (≥5 CRC-valid SiK frames over ≥3 channels); level 4 only with MAVLink CRC-16 +
  CRC_EXTRA. No vendor/drone identity asserted; `netid` is a firmware config value, not an operator identity.
- Conditions / open: (1) no negative-control test with non-SiK ISM hoppers or dense multi-emitter scenes — level 2/3
  false-positive rate is untested; (2) thresholds (5 frames / 3 channels / 5 bursts) are design-derived, not
  validated against a real 64 kbps SiK link; (3) everything is level-1 synthetic self-consistency until a real SiK
  recording exists.

## Independent review (test-reviewer, 2026-09-19, part B) — PASS WITH CONDITIONS

- Provenance: sync word 0x2DD4 (Si4432 POR default, AN440), hardware CRC-16/ARC and SiK software CRC (`crc.c`),
  Golay(23,12) tables (regex-extracted from `Firmware/radio/golay23.h`) are traceable to firmware/datasheet.
  **The hop-map LCG in `raster.py` (`_LCG_A/_LCG_C`, Fisher-Yates seeded by NETID) is NOT sourced — it is a
  task-spec formula.** NETID recovery is therefore self-consistency only until verified against `fhop_init()`
  in the local SiK firmware (`research/library/…/ArduPilot_SiK_master.zip`) — verification delegated 2026-09-19.
- Golay: 2000/2000 random 1–3-bit error blocks corrected; 4-bit errors spread over the 48-bit block → 10 % silent
  mis-decodes (single-codeword-confined 4-bit case not run; expected ~100 % mis-correct — CRC is the guard).
- Robustness (`decode_sik_window`, fixture): pure noise ×3 seeds → 0 bursts, 0 CRC-valid frames; CFO ±20 kHz and
  rate ±2 % → 40/40 CRC-valid, NETID 25, unchanged. No breaking point located (larger sweep not run).
- Gap: no wideband OFDM/Wi-Fi waveform simulator in the repo → false-CRC-under-wideband-interferer untested.

## Independent verification of hop_map() (test-reviewer, 2026-09-19) — PASS

Fresh C reimplementation typed from `freq_hopping.c` (gcc, 8051 integer widths) vs `raster.py::hop_map()`:
0/410 mismatches (N∈{10,50}, seeds {0,1,25,4242,65535} + 200 random each); `hop_map(25,10)==[0,9,5,2,6,7,4,3,8,1]`;
16-bit seed wrap (`hop_map(65536,n)==hop_map(0,n)`) faithful; `_hop_maps_all_seeds` == scalar for 1000 checks.
Still outstanding: validation against a running SiK radio / real capture with known NETID (level 3/4 conversion).
