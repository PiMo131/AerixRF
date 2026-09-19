# Tsukorok S3 v4 firmware 5.5.12 — RF drone-detection configuration and logic (static analysis)

Source image: `tsukor_s3v4_5.5.12_en.bin` (MD5 `c39c7a8fca0f4f2beae95c1c28eee8c6`, 1,182,928 bytes).
Method: Ghidra 11.4.2 headless (Xtensa:LE:32, all six ESP image segments loaded at their vaddrs, ~190 extra
function starts recovered by `entry a1` prologue scan) plus manual literal-pool decoding in Python. Every value
below is tagged **CONFIRMED** (read from bytes or from the decompiled instruction stream) or **INFERRED**.

Evidence-level note (AERIX RF policy): everything this device does is stage-1 RF morphology / stage-2
probabilistic classification. Nothing in the firmware performs a deterministic decode of any drone protocol;
the "syncwords" it uses are raw first-words after an FSK preamble, not decoded frames.

## 0. Corrections to the working assumptions in the task brief

| Item | Brief said | Firmware shows | Evidence |
|---|---|---|---|
| Segment file offsets | Seg0 data at 0x18 | Segment *data* starts 8 bytes later (0x20; 0x365A4; 0x3C038; 0x40020; 0x1108F0; 0x120C7C). DROM vaddr = 0x3C0E0020 + (file_off − 0x20). | ESP image header parse, CONFIRMED |
| 0x405C0–0x40700 "config struct" | data struct | It is the compiler literal pool (`l32r` constants) of the settings loader `FUN_4200b170` and neighbours, not a struct. Defaults are call arguments, see §1. | CONFIRMED |
| `rssi_threshold` default 94 | 94 | Default is **0xBC = 188**; the code uses it as `-(rssi_threshold >> 1)` = −94 dBm. | `FUN_4200b170` @ 0x4200b1a2, CONFIRMED |
| A5133 = sub-GHz path | sub-GHz | A5133 is the **5.8 GHz** receiver: channel plan 5725–5899 MHz, 1 MHz steps, ID 0xA1513300. Sub-GHz radio is an **SX1276/SX1278** (RadioLib SX127x, "SX1276Scanner"). No SX126x code paths found. | §2.3, §4 |
| RadioLib scan engine | | SX1280 (2.4 GHz) via RadioLib SX128x; SX127x for 300–1020 MHz; A5133 bit-banged 3-wire; CC2500 code path present but `cc2500 unsupported` for scans on this build. | §4 |

## 1. Settings: NVS keys, struct offsets, defaults

Loader: `FUN_4200b170` (0x4200b170–0x4200b74d) uses Arduino `Preferences` getters
(`FUN_4201cf58`=getUChar, `FUN_4201cf28`=getChar, `FUN_4201cf88`=getUShort, `FUN_4201cfe0`=getInt/getUInt,
`FUN_4201d020`=getBool, `FUN_4201d130`=getFloat, `FUN_4201d03c`=getString, `FUN_4201d0f0`=getBytes).
Saver: `FUN_42009e80` (0x42009e80). Struct offsets are those of the settings object `param_1`.
All rows CONFIRMED unless marked.

| NVS key | struct off | type | default | literal/insn address | notes |
|---|---|---|---|---|---|
| rssi_threshold | +0x00 | u8 | 0xBC (188) | insn 0x4200b1a2 (movi) | used as −(v>>1) dBm = −94 dBm |
| bitrate_first | +0x04 | u32 | 57600 | lit 0x42000618 (file 0x40618) | bps |
| bitrate_second | +0x08 | u32 | 80000 | lit 0x4200061c | bps |
| bitrate_third | +0x0C | u32 | 15235 | lit 0x42000620 | bps (Zala/Lancet class, see §5.3) |
| bitrate_forth | +0x10 | u32 | 0 | insn | disabled |
| sf_first | +0x14 | u8 | 9 | insn | LoRa SF |
| sf_second | +0x15 | u8 | 8 | insn | |
| sf_third | +0x16 | u8 | 0 | insn | |
| sf_forth | +0x17 | u8 | 0 | insn | |
| freq_step | +0x18 | u32 | 100000 | lit 0x42000428 | Hz, FSK sweep step |
| (freq ranges vector) | +0x1C..+0x24 | vector<pair<u32,u32>> | see below | | |
| randomized_fsk | +0x28 | u8 | 1 | insn | |
| tracking_menu | +0x29 | u8 | 0 | insn | |
| tracking | +0x2A | u8 | 0 | insn | |
| rssi_scn_tresh | +0x2B | u8 | 0x3C (60) | insn | used as −60 dBm in RSSI-scan mode (`FUN_42018668`) |
| detect_orlan | +0x2C | bool | 1 | insn | gates Orlan-class bitrates |
| detect_zl_la | +0x30 | u8/u32 | 1 | insn | 1 = ZL FSK on; 2 = also 2.4 GHz Zala video scan |
| detect_fpv | +0x34 | u8/u32 | 2 | insn | LoRa scan mode (1 or 2) |
| detect_fhss | +0x38 | bool | 0 | insn | FHSS/burst detector |
| jam_fpv | +0x39 | bool | 0 | key ptr lit 0x42000624 | only a flag; no TX code reached from it (see §6) |
| cc2500_enabled | +0x3E | bool | 1 | insn | actually the "DJI 2.4 GHz scan enabled" flag (CLI prints "DJI: enabled/disabled") |
| dji_sig_width | +0x3A | u8 | 0x1E (30) | insn | bins of 390.625 kHz (≈11.7 MHz) |
| dji_rssi_thrsh | +0x3B | i8 | 0xA1 (−95) | insn | dBm |
| dji_qblock | +0x3C | i8 | 6 | insn | quantisation block (bins) |
| dji_scan2 | +0x3D | i8 | 2 | insn | |
| dji_alg | +0x40 | u32 | 1 | insn | 1 candidate+time-domain; 2 both spectral scores; 3 either; 4 "paranoid" |
| skydio_alg | +0x44 | u32 | 0 | insn | 0 off; 1..4 selects threshold {70,60,50,40} (100 for index 0) |
| alarm_prmbl_len/frq/cnt | +0x48/+0x4A/+0x4C | u16/u16/u8 | 500 / 2500 / 1 | insn / lit 0x4200064c / insn | buzzer profile (ms, Hz, count) — not RF |
| alarm_track_len/frq/cnt | +0x4E/+0x50/+0x52 | | 300 / 750 / 1 | insn | buzzer |
| alarm_lora_len/frq/cnt | +0x54/+0x56/+0x58 | | 400 / 1000 / 1 | insn | buzzer |
| alarm_rssi_len/frq/cnt | +0x5A/+0x5C/+0x5E | | 500 / 2700 / 1 | insn / lit 0x42000650 | buzzer |
| (candidate alarm) | +0x60/+0x62/+0x64 | u16/u16/u8 | 700 / 2000 / 1 | lit 0x42000654 = 0x07D002BC | not an NVS key |
| preamble_size | +0x66 | u8 | 0x10 (16) | insn | bits |
| f_change_delay | +0x68 | u16 | 0x32 (50) | insn | ms wait after retune in FSK match |
| rxbw | +0x6C | u32 | 200 | insn | kHz |
| afcbw | +0x70 | u32 | 200 | insn | kHz; this is the value actually passed as SX127x rxBw |
| capture_size | +0x74 | u16 | 0x10 (16) | insn | |
| capture_data | +0x76 | u8 | 0 | insn | |
| paramp_rise | +0x77 | u8 | 0x1E (30) | insn | |
| autoreturn | +0x78 | bool | 1 | | |
| screensaver | +0x79 | bool | 1 | | |
| machine_read | +0x7C | u32 | 0 | | 1 CSV, 2 JSON, 3 CoT XML, 4 CoT "circle" (UTF‑16 XML), 5 Meshtastic text |
| alarm_method | +0x80 | u32 | 3 | | |
| agc | +0x84 | bool | 1 | | SX127x AGC on; 0 → manual gain 1 |
| ss_rx / ss_tx | +0x85/+0x86 | i8 | −1 / −1 | | |
| ext_comms | +0x88 | u32 | 0 | | 1 twin link, 3 Meshtastic |
| ext_comms_enbl | +0x8C | bool | 1 | | |
| twins_freq | +0x94 | float | 901.2 | lit 0x42000628 = 0x446149BA | MHz |
| walkie_freq | +0x90 | float | 446.0 | lit 0x4200062c = 0x43DF00CD | MHz (PMR446) |
| quick_act | +0x98 | u8 | 0 | | |
| ntp_server | +0xA0 | string | "pool.ntp.org" | lit 0x42000658 | |
| mesh_netid | +0xB0 | u32 | 0x12345678 | lit 0x42000660 | |
| mesh_key | +0xB4 | 32 bytes | zeros | | |
| short_name | +0xD4 | u32 | 0x4E4F4E45 ("ENON"/"NONE") | lit 0x42000664 | |
| latitude/longitude | (separate getters `FUN_4200ac2c/40`) | float | | | |

Frequency ranges (`freq1..3_start/end`, Hz, u32): loader reads them, accepts a pair only if both ends
> 704,999,999 Hz (lit 0x42000630 = 0x2A05723F); if the vector ends up empty it installs and *saves* the
defaults 860,000,000–885,000,000 / 895,000,000–928,000,000 / 970,000,000–1,020,000,000 Hz
(lits 0x42000634..0x42000648). CONFIRMED.

Other CLI-visible settings not in this loader: `cc2500_27mhz` (`FUN_4200a338`, crystal flag for the CC2500
path), `cc2500_csn_pin`, `activate_rnd`, notification pins, LAN settings, `licensee`. `elrs24` and `autolora`,
`zala video`, `morze freq` are menu item strings at 0x3C0E4966/0x3C0E495D/0x3C0E497B/0x3C0E49B6.

## 2. Per-detector parameter tables

### 2.1 2.4 GHz SX1280 — DJI "paranoid" sweep (`FUN_42007564`, 0x42007564–0x420076e9)

| Parameter | Value | Address | Status |
|---|---|---|---|
| Sweep start | 2,400,000,000 Hz | lit 0x4200022c | CONFIRMED |
| Sweep end (exclusive) | 2,500,000,000 Hz | lit 0x42000244 | CONFIRMED |
| Step | 400,000 Hz (250 channels) | lit 0x4200024c | CONFIRMED |
| Settle before RSSI | 40 µs (`FUN_42027a2c(0x28)`) | insn 0x420075f4 | CONFIRMED (µs INFERRED from callee) |
| RSSI read | SX128x `GetRssiInst` → −(reg/2) dBm (`FUN_42021910`) | 0x42021910 | CONFIRMED |
| Threshold | `dji_rssi_thrsh` (default −95 dBm) | cfg+0x3B | CONFIRMED |
| Window | 16-sample ring, sliding count of above-threshold samples | insn | CONFIRMED |
| Candidate rule | count > 7 (≥8 of last 16 = ≥3.2 MHz) | insn 0x420076c0 | CONFIRMED |
| Broadband guard | total above-threshold < 0x7D (125 = half the channels) | insn | CONFIRMED |
| Accumulator | ±1 per sweep, clamp 0..4, state at this+0x428 | insn | CONFIRMED |
| Confirm rule | accumulator > 1 | insn | CONFIRMED |
| Log | "1280 DJI paranoid scan: detected=%d, signal_history_accumulator=%d" | 0x3C0E1769 | |

### 2.2 2.4 GHz SX1280 — Zala video sweep (`FUN_420076ec`, 0x420076ec–0x42007842)

| Parameter | Value | Address | Status |
|---|---|---|---|
| Sweep | 2,200,000,000 + i·400,000 Hz, i = 0..499 (2200.0–2399.6 MHz) | lits 0x42000250, 0x4200024c; loop const 500 | CONFIRMED |
| Settle | 60 µs (0x3C) | insn | CONFIRMED |
| Threshold | −(rssi_threshold>>1) = −94 dBm (`FUN_420c799c`) | 0x420c799c | CONFIRMED |
| Candidate rule | window count > 6 (≥7 of 16 = ≥2.8 MHz) | insn 0x42007821 | CONFIRMED |
| Broadband guard | total < 0xFA (250) | insn | CONFIRMED |
| Accumulator | clamp 0..3 at this+0x429; confirm when > 1 | insn | CONFIRMED |
| Enable | only when `detect_zl_la == 2` (Tick, `FUN_40375ce4`) | 0x40375ce4 | CONFIRMED |

### 2.3 5.8 GHz A5133 (`FUN_420093c8` targeted, `FUN_40376410` paranoid, `FUN_403765fc` spectral, `FUN_420094bc` spectrum)

| Parameter | Value | Address | Status |
|---|---|---|---|
| Channel 0 | 5725 MHz (`ch = f_MHz − 5725`, reg 0x0E = ch) | lit 0x42000404 = 5725; `FUN_420090c4` writes reg 0x0E = (arg − 0x5D) | CONFIRMED |
| Last channel | 5899 MHz (spectrum loop 0xAF = 175 channels; scan end 5,900,000,000 Hz) | lit 0x42000410 = 5900; IRAM lits 0x40374534/0x40374538 | CONFIRMED |
| Step | 1,000,000 Hz | IRAM lit 0x40374538 | CONFIRMED |
| Settle | 40 µs before channel write, 5 µs after (paranoid/spectrum); 20 µs/20 µs (targeted) | insns | CONFIRMED |
| Threshold | `dji_rssi_thrsh` (−95 dBm) | cfg+0x3B | CONFIRMED |
| Paranoid rule | same 16-window, count > 7; broadband guard total < 0x57 (87); accumulator clamp 0..4; confirm > 1; **plus** immediate confirm (return 2 = "dji 5.8") if window shape test `FUN_420c78a8` passes | 0x40376410, 0x420c78a8 | CONFIRMED |
| Targeted (track) rule | 21 channels f−10…f+10 MHz, two passes, detect if > 10 samples above threshold | 0x420093c8 (lits 0x420003f8=−5735, 0x420003fc=−5714, 0x42000400=−5736) | CONFIRMED |
| Spectral rule | descending threshold −65 dBm step −5 down to −99; segment = ≥N contiguous samples above threshold with gap tolerance 5; width−16 < 54 (16..69 MHz); confirm when segment edges match previous threshold's segment within 5 MHz on both sides; accumulator clamp 0..1 (needs 2 consecutive positive sweeps) | 0x403765fc (consts −0x41, −5, 5, 0x10, 0x36, −99) | CONFIRMED |
| RSSI formula | dBm = ((raw_reg0x1E − cal[0x1C]) / (cal[0x1B] − cal[0x1C])) · 12.0 − 80.0 − 3.0 | `FUN_420091cc` (ROM __floatsidf/__subdf3/__divdf3/__muldf3; lits 0x420001d8=12.0, 0x420001cc=80.0, 0x42000174=3.0) | CONFIRMED |

### 2.4 2.4 GHz SX1280 — DJI spectral / candidate / Skydio algorithms (`FUN_40375ce4` Tick → `FUN_4200552c`, `FUN_42004acc`, `FUN_420074c8`+`FUN_4200512c`, `FUN_4200457c`)

Spectrum capture `FUN_40375c0c`: 8 sweeps × 256 bins, bin i = 2,400,000,000 + i·390,625 Hz (lits
0x40374440 = 2.4e9, 0x4037444c = 390625, count 0x800 = 2048 bytes), 20 µs settle, IRAM fast RSSI `FUN_4037789c`.
CONFIRMED.

Tick decision (CONFIRMED structure, parameter semantics INFERRED):

* `dji_alg == 4` → paranoid sweep §2.1.
* `dji_alg ∈ {1,2,3}` or `skydio_alg != 0` → capture spectrum; score A = `FUN_4200552c(spec, paramsA)`,
  score B = `FUN_4200552c(spec, paramsB)`.
  * paramsA raw literals (IRAM pool): bin_hz=390625.0 (0x4037447c:0x4117D784 hi), ints 5,5,2,1,10,26,52,20,
    double 39.0 (0x40374480), 3,4, double 100.0 (0x40374484). Result compared > 40.0 (0x40374488).
  * paramsB: bin_hz=390625.0, 5.0 (0x4037448c), 18, 60, 3, 3, 2, 25, 50, doubles 0.85 (0x40374490/94),
    12.0?/0.2 (0x40374498/9c), 0.4 (0x403744a4), 0.125 (0x403744a8), 100.0. Result compared > 3.14
    (0x403744ac) [INFERRED: split-double reconstruction].
  * `dji_alg==2`: A>0 && B>0; `dji_alg==3`: A>0 || B>0; `dji_alg==1`: candidate finder `FUN_42004acc`
    with {0.4, 6, 2, 159, 20, 102, 3} (0x403744b0..), then for each candidate a time-domain observation
    `FUN_420074c8` (8192 RSSI samples, lit 0x42000220 = 0x2000) at start+width/3 and end−width/3, classified by
    `FUN_4200512c` with {0x9C=156, 2, 750, 32, 75, 3, 0.3, 0.9, 64, 20, 5, 5, 0.5}; detection when both
    classifications pass.
  * `FUN_4200552c` internals (INFERRED): per-bin max over 8 sweeps, median noise floor + offset, segments
    above floor with gap merge, width limits (params +0x10/+0x14), persistence across sweeps (+0x38/+0x3C),
    fraction-above and edge tests; returns double score.
* Skydio (`skydio_alg` 1..4): metric from `FUN_4200457c`, thresholds table {100,70,60,50,40}[skydio_alg]
  (insns 0x403761xx), detection type 5.
* Result types: 1 = DJI 2.4G, 2 = Zala video, 3 = DJI 5.8, 5 = Skydio; display splits DJI into
  `dji ' '` (code 13) when width ≤ 80 bins and `dji 'e'` (code 18, "DJIe") when width > 80 bins
  (`FUN_4200d434` insn 0x4200d6a0). Alarm rate limit 3000 ms per type (lit 0x403744d0). CONFIRMED.

### 2.5 Sub-GHz FSK sweep (`FUN_42017404`, `FUN_403770a4` RSSI pre-pass, `FUN_40376e74` match; SX127x)

| Parameter | Value | Address | Status |
|---|---|---|---|
| Ranges | settings freq ranges (default 860–885, 895–928, 970–1020 MHz) | §1 | CONFIRMED |
| Step | `freq_step` (100 kHz) | cfg+0x18 | CONFIRMED |
| Bitrate list | bitrate_first..forth (57600, 80000, 15235) → `setBitRate(br/1000.0)` | `FUN_42017268` | CONFIRMED |
| Bitrate gating | 15235 only if `detect_zl_la ∈ {1,2}`; Orlan-class bitrates only if `detect_orlan` | `FUN_4201712c` | CONFIRMED |
| Orlan-class bitrates | 76190, 38150, 80000, and 55001..57999 | `FUN_420170e8` lits 0x420013a4=−76190, 0x420013a8=−38150, 0x420013ac=−80000, 0x42000f1c=−55001, 0x42000f20=2998 | CONFIRMED |
| RSSI pre-pass bitrate | 100 kbps (`FUN_42017390`) or rotating 57.6 / 76.19 / 38.15 kbps (`FUN_42017300`, lits 0x420013d0..d8) | | CONFIRMED |
| Pre-pass settle | 25 µs; channel active if RSSI ≥ −(rssi_threshold>>1) | `FUN_403770a4` | CONFIRMED |
| Noise correction | if > 30 % of channels read < −112 dBm, set correction flag; reported RSSI = raw + 15 | insns 0x403771b0..; lit 0x403746bc | CONFIRMED |
| Range adjust | after ≥3 active channels: range = [min_active − 2 MHz, max_active + 2 MHz] | `FUN_420174e8` lits 0x420013f0 = −2,000,000, 0x42000338 = 2,000,000 | CONFIRMED |
| Linear/random | every 3rd pass linear else randomized (`randomized_fsk`) | `FUN_42017404` | CONFIRMED |
| Radio init | `beginFSK(755.0 MHz, br, fdev 76.7 kHz, rxBw = afcbw (200 kHz), 10 dBm, preamble 16, OOK off)` | `FUN_42017200` lits 0x420013bc=755.0, 0x420013b8=76.7 | CONFIRMED |
| Alarm gate | packet received with any syncword-detector hit **and** RSSI(+corr) ≥ −(rssi_threshold>>1) | `FUN_40376e74` | CONFIRMED |
| Retune wait | `f_change_delay` (50 ms) unless ≥ 8 packets | cfg+0x68 | CONFIRMED |
| Unknown-drone search | `FUN_42019818`: linear FSK sweep, budget 1,800,000 ms (lit 0x42001574) | | CONFIRMED |
| RSSI-scan mode | `FUN_42018668`: 50 µs settle, +15 dB if >30 % channels < −112 dBm, callback if peak > −rssi_scn_tresh (−60 dBm) | | CONFIRMED |

### 2.6 Sub-GHz LoRa / ELRS (`FUN_42017e00/42017c20/42017d38` start, `FUN_42017e58/420180f0/420181e8` tick, `FUN_42018480` autosearch)

| Parameter | Value | Address | Status |
|---|---|---|---|
| Frequency step | 125,000 Hz | lit 0x42001470 | CONFIRMED |
| LoRa begin | `SX1278::begin(f MHz, bw 500.0 kHz, sf, cr 7, syncWord 0x12, 10 dBm, preamble 8, gain 0)` | `FUN_4201da3c` call at 0x42017cb2/0x42017d9c; lit 0x4200142c = 500.0 | CONFIRMED |
| Then | implicitHeader(8), setCRC(0), FIFO base 0, symbol timeout reg 0x1F = 0x20 | `FUN_4201e880/4201e314/4201db94/4201dab0` | CONFIRMED |
| Mode 1 (`detect_fpv`=1) | iterations 8 if start ≤ 959,999,999 Hz else 6 (lit 0x42001428); per-channel RSSI gate ≥ −94 dBm; CAD scan SF 6..9 (`FUN_4201d6f4`: reg 0x1E=0x60, reg 0x31=5; `FUN_4201d850` CAD → −14 preamble); 50 ms CAD window; fast RX 8 bytes; SNR>0 → good | `FUN_42017e58` | CONFIRMED |
| Mode 1 confirm | at last channel: max_rssi ≥ −199 and good·6 + bad·3 + timeouts ≥ 6; dominant-SF counter: SF6 > 5, SF7 > 8, SF8 > 5, SF9 > 4 → match callback (freq, rssi) | insns 0x42018010–0x420180b9 | CONFIRMED |
| Mode 2 (`detect_fpv`=2) | iterations 3 if ≤ 959,999,999 Hz else 2; SF = sf_first (9); CAD then RX; confirm good·6 + bad·3 ≥ 6 and (good ≥ 1 or bad ≥ 2) | `FUN_420180f0` | CONFIRMED |
| Autosearch (`autolora`) | LoRa modem, CR 7, BW 500, preamble 8, syncword 0x12, gain 1, AGC off, CRC off; SF 6..9 each 1000·2^k ms; "ELRS sf=%d, rssi=%d" | `FUN_42018480` | CONFIRMED |
| RSSI-mode radio | `beginFSK(start/1e6, 100 kbps, 76.7 kHz, afcbw, 10, 16)` | `FUN_420189a4` lit 0x4200102c = 100.0 | CONFIRMED |

### 2.7 2.4 GHz ELRS scan (`FUN_42007a30`, CLI "elrs scan", SX1280 LoRa)

| Parameter | Value | Address | Status |
|---|---|---|---|
| Validation | start/end within 2,200–2,600 MHz (lits 0x42000268 = 2,094,967,296, 0x4200026c = 400,000,000), span ≤ 100 MHz (0x42000278) | | CONFIRMED |
| begin | `SX128x::begin(2400.0, bw 812.5 kHz, sf 8, cr 8, syncWord 0x14, 2 dBm, preamble 12)` | `FUN_420213a8` @0x42007a9f; lits 0x42000218, 0x42000284 | CONFIRMED |
| Per SF | SF 5..8; CR = 6 for SF5 else 8 (`FUN_42020e58`), `setSpreadingFactor` (`FUN_42020dd0`) | insns 0x42007ae4.. | CONFIRMED |
| Channel step | 400,000 Hz; per-channel frequency-error correction accumulated if |err| ≤ 199,999 Hz (0x4200029c) | | CONFIRMED |
| Packet accept | receive 8 bytes, SNR > 0 and RSSI > threshold arg | | CONFIRMED |
| Report | "signal found" if > 1 packets per SF | | CONFIRMED |

### 2.8 2.4 GHz FPV / spectrum objects

`FUN_42007c9c` RSSI spectrum: 256 steps of 390,625 Hz from 2.4 GHz, 100 µs settle, folded to 128 bins.
`FUN_42007d20` "jammer scan"/FPV sweep: 400 steps of 250,000 Hz from 2.4 GHz (2400–2500 MHz), 50 µs settle,
RSSI clamped to [−100, −30] dBm. `FUN_42007f88` FPV tracker constants: 2400.0, 0.5, 6.0, 12.0, 5.0, 6, 2,
4.0, 0.1, 0.003, 2.0, 1.5, 8.0, 0.35, 0.0025, 1, 3.0, 0.78, 0.86, 24, 8, 0.82, 8.0, 45.0, 8.0, 0.7, 60.0,
6.0, 0.55, 35.0, 60.0, 80.0 (lits 0x420002c4–0x42000318) plus a 256-entry per-channel state template
{−100.0, 2.0, 0, 0, −100.0, −100.0, 0} at DROM 0x3C0E1958 (file 0x1958, 7168 bytes). Noise-level classifier
`FUN_42008094`: most frequent 3-dB-quantised level above −90 dBm; count > 70 → 80.0, > 50 → 60.0, > 30 → 40.0.
All CONFIRMED (semantics INFERRED).

## 3. Syncword / magic tables

### 3.1 How "syncwords" are obtained (CONFIRMED)

The SX127x is run in FSK RX with preamble detection; the first 32-bit word of each received packet is treated
as the sync word. `FUN_42011e04` normalises it: if the top two bits are 00 or 11 → `sw & 0x7FFFFFFF`
(lit 0x42000184); otherwise leading alternating (preamble-like) bits are stripped by shifting.
`FUN_42012694` rejects "unlikely" words: with mask 0x3FFFFFFF (lit 0x420000c0), a word is rejected if
`sw`, `~sw`, `sw^0x55555555` (0x42000fc8) or `sw^0xAAAAAAAA` (0x42000fcc) has ≤ 1 bit set.

Three detector classes are run per packet by `FUN_42012388` (virtual slot +8):

### 3.2 Static syncword table — class vtable 0x3C0E6B4C, ctor `FUN_42012c40` (0x42012c40–0x42012f01)

Each entry maps a word → detection type code. Lookup `FUN_420129a0` tries `sw`, `sw>>1`,
`(sw>>1)|0x04C4B400`, and the normalised forms. Note: the OR constant is decimal 80000000 (lit 0x42001004),
almost certainly intended as 0x80000000 — a firmware bug (INFERRED).

| # | Raw word (CONFIRMED, literal addr) | Normalised form also inserted (INFERRED via re-implementation) | Type code → label |
|---|---|---|---|
| 1 | 0xF17C1599 (0x4200100c) | 0x717C1599 | 2 → "Or" |
| 2 | 0xEC7C402F (0x42001010) | 0x6C7C402F | 2 → "Or" |
| 3 | 0xC55E38A9 (0x42001014) | 0x455E38A9 | 2 → "Or" |
| 4 | 0x2A2C1481 (0x42001018) | 0x2A2C1481 | 2 → "Or" |
| 5 | 0x12345678 (0x42000660) | 0x12345678 | 2 → "Or" |
| 6 | 0x69517E96 (0x4200101c) | 0x29517E96 | 3 → "Za" |
| 7 | 0xA545FA58 (0x42001020) | 0x0545FA58 | 5 → "ZL" |
| 8 | 0x0545FA58 (0x42001024, inserted normalised only) | 0x0545FA58 | 5 → "ZL" |
| 9 | 0x69696969 (0x42001028) | 0x29696969 | 4 → "El" |

Type-code → label table (`FUN_42012180`, strings at 0x3C0E6A48..0x3C0E6A71): 2 "Or,", 3 "Za," (or "?Za," if
bitrate not ≈15235), 4 "El,", 5 "ZL,", 6 "Lc,", 7 "?FPV,", 8 "FPVe,", 9 "Sc,", 10 "X3,", and for type 1
(learned word) "?Or," if bitrate ∈ [37901,38899] or [57101,58099], "?Sc," if bitrate == 15235, "?Za," if
bitrate ∈ [14701,15699], "?El," if bitrate ∈ [114701,115699], else "*,". CONFIRMED. Label semantics
(Or = Orlan, Za = Zala, ZL = ZalaLancet, El = ELRS, Lc = Lancet, Sc = ?, X3 = ?) INFERRED.

### 3.3 "cryptoorlan" — learned at runtime (class vtable 0x3C0E6A3C, detect `FUN_42011fd4`, 0x42011fd4–0x4201210e)

No seed list. Conditions: bitrate ∈ [55001, 57999] (lits 0x42000f1c/0x42000f20) and raw RSSI arg > 30.
Hash table entry = {syncword, freq_MHz, last_seen_ms, count}. Same word + same MHz → count++ and ignore;
same word at a different MHz → "not cryptoorlan"; new word → add ("cryptoorlan: adding syncword %x at %dmhz").
**Confirm**: when the table holds > 3 entries and > 3 of them have count == 1 (≥ 4 distinct, each seen once
— i.e., a syncword that changes every packet at ~57.6 kbps) → returns type 10 ("X3"). CONFIRMED.

### 3.4 Syncword-count detector (vtable 0x3C0E6B38, detect `FUN_42012804`, 0x42012804–0x4201297e) — learned

Entries expire after 1,200,000 ms (lit 0x42000fd0, `FUN_420126dc`). Rules (freq in Hz, br in bps):

* Repeated word, same freq: if freq ∈ [868e6, 928e6] and br ∈ [14701,15699] → ignore (0).
  Else `FUN_42012790`: count ≥ 2 and freq ∈ [865e6, 872e6] or [902e6, 928e6], and another entry with count ≥ 2
  exists in the same band → type 5 ("ZL"); otherwise type 6 ("Lc").
* Repeated word, different freq: `FUN_420125e4` br≈15235 and one freq in [865,872] MHz, other in
  [902,928] MHz → 6; `FUN_4201262c` br ∈ [84600,85600] and both freqs in [860,885] or [902,922] MHz → 7;
  `FUN_4201266c` br == 15235 and either freq > 970e6 → 9; else → 1 with the word.
  Lits: 0x42000f9c=−868e6, 0x42000fa0=60e6, 0x42000fa8=−865e6, 0x42000fac=7e6, 0x42000fb0=−902e6,
  0x42000fb4=26e6, 0x42000fb8=−84600, 0x42000fbc=−860e6, 0x42000fc0=25e6, 0x42000fc4=20e6. CONFIRMED.

### 3.5 Other magic

* A5133 ID code expected 0xA1513300 (byte0 0xA1 or 0xA2, then 'Q','3',0) — `FUN_42008f14`, string 0x3C0E3790. CONFIRMED.
* LoRa sync words: 0x12 sub-GHz scans, 0x14 for the 2.4 GHz ELRS scan, 0x35 for the "twin" link. CONFIRMED.
* Alarm magic tags 0xDFEDFE00/01/02, 0xBEEF0001 (lits 0x4200090c/0x420008f0/0x420008f8/0x420008e0) — internal queue tags. CONFIRMED.

## 4. Radio initialisation

### 4.1 SX1280 (RadioLib SX128x) — `FUN_4200835c` ctor, `FUN_42008480` init, `FUN_42007470` per-scan

* SPI bus pins SCK 17, MISO 15, MOSI 16, SS 18 (`FUN_4201ad7c(…,0x11,0xF,0x10,0x12)`); module
  NSS 18, IRQ 14, RST 12, BUSY 13; SPI clock 2,000,000 Hz (lit 0x42000338). GPIO 21 = RF section power enable.
* Every scan: reset, `beginFSK(2400.0 MHz, br 250 kbps, fdev 195.0 kHz, 10 dBm, preamble 16)`
  (`FUN_4202127c(…, lit 0x42000218=2400.0, 0xFA, lit 0x42000214=195.0, 10, 0x10)`), `startReceive(0xFFFF)`
  (lit 0x4200021c), then only `SetRfFrequency` (IRAM `FUN_40377904`) + `GetRssiInst` per channel; `sleep()` after.
* RSSI: −(reg 0x1F >> 1) dBm. All CONFIRMED.

### 4.2 A5133 (5.8 GHz, bit-banged 3-wire) — `FUN_42008f14` init, `FUN_42009108` calibration

* Pins: SDIO 16, SCK 17, CS 48 (`FUN_42008d2c(dev, 0x30, 0x11, 0x10)`); shares 16/17 with the SX1280 bus.
* Register write `FUN_42008c88(reg, val)`, read `FUN_42008cc0(reg|0x40)`, strobe `FUN_42008cfc(cmd|0x80)`,
  paged write `FUN_42008d40(reg, val, page)` = reg 0x35 ← page<<4 then reg.
* Init sequence (CONFIRMED bytes, DROM):
  * reg1=0x43, reg2=0x00, reg3=0x3F, reg4=0x00; regs 0x07..0x1F, 0x23..0x29, 0x2B..0x35 from table
    `0x3C0E38CA` (file 0x38CA, 54 bytes): `00 43 00 3f 00 00 00 00 00 0c 00 01 01 1f 00 1e 59 74 01 32 64 2c 40 1b 40 70 7b c9 91 ca 70 b1 00 00 00 a4 01 4f c0 80 30 00 00 c3 40 e7 57 74 f3 73 4d 15 0f 00`
  * reg 0x20 pages 0..12 from 0x3C0E38BD: `04 00 00 00 00 00 00 00 00 00 02 00 00`
  * reg 0x21 pages 0..12 from 0x3C0E38B0: `09 00 00 00 00 00 c0 00 7c 4f 01 43 3c`
  * reg 0x22 pages 0..5 from 0x3C0E38AA: `00 10 00 10 00 04`
  * reg 0x2A pages 0..12 from 0x3C0E389D: `00 01 f0 80 80 48 07 c0 3a 3e e8 80 00`
  * reg 0x37 = 0x77; reg 0x38 pages 0..11 from 0x3C0E3891: `8c 53 1e 64 1a 40 60 04 00 00 00 00`
  * regs 0x39,0x3A,0x3B,0x3C,0x3E = 0; then trim/CP/FT calibration `FUN_42008d6c` (reg 0x38 page 9 = 0xA0, read 8 bytes @0x3F).
* Calibration: reg2 = 0x63 (wait clear), channel-group calibration at channels 25, 75, 125 (`FUN_42008e98`:
  reg 0x0E = ch, reg2 = 0x1C, success if bit 4 of (reg0x25|reg0x26) clear), FBCF check reg 0x23 bit 4,
  RSSI cal values read from regs 0x1B/0x1C. Strobes: 0x58 standby-like, 0x50, 0x80 sleep, 0xC0 RX (INFERRED names).
* Channel: reg 0x0E = f_MHz − 5725. RSSI: reg 0x1E after 150 µs, formula in §2.3.

### 4.3 SX1276/SX1278 (RadioLib SX127x) — `FUN_42019b34` "Starting radio"

* SPI pins SCK 7, MISO 6, MOSI 8, SS 9; SPI clock 10,000,000 Hz (lit 0x42000260).
* `beginFSK(755.0 MHz, bitrate_first/1000 kbps, fdev 76.7 kHz, rxBw = afcbw kHz, 10 dBm, preamble 16, OOK 0)`,
  image calibration (reg 0x3B), AFC auto on (reg 0x0D bit 4, `FUN_4201ee14(1)`), `agc` → AGC else
  `setGain(1)` + LNA reg 0x0C; DIO0 ISR = IRAM `FUN_4037721c` (lit 0x420015d4); spreading-factor list init.
  All CONFIRMED (register-level identification of RadioLib methods INFERRED from register numbers).
* CC2500 path (`cc2500_27mhz`): only `FUN_42003ddc` init and `FUN_4200423c` "dji signal width" remain; scans
  report "cc2500 unsupported" (`FUN_4200877c`). CONFIRMED.

### 4.4 Comms radios on the same SX127x

* "twin" link: `SX1278::begin(twins_freq 901.2 MHz, bw 62.5 kHz (lit 0x4200161c), sf 8, cr 7, sync 0x35, 10 dBm, preamble 8)` — `FUN_4201a038`.
* Meshtastic: "LongFast" preset, hash 0x14, mesh_netid / mesh_key — `FUN_4201a1a0`. This path **transmits**
  (Meshtastic packets). Out of AERIX RF scope; noted for completeness.

## 5. Decision logic (annotated pseudocode)

### 5.1 2.4 GHz tick (IRAM `FUN_40375ce4`, called ≤ every 5000 ms from main loop `FUN_40376844`)

```
if !(cfg.dji_enabled || cfg.detect_zl_la == 2): return 0
power_on(GPIO21); spi_begin
det_24 = 0; det_zala = 0; det_58 = 0
if cfg.dji_alg == 4:
    det_24 = DJI_paranoid_sweep()                        # §2.1, FUN_42007564
elif cfg.dji_alg != 0 or cfg.skydio_alg != 0:
    spec = capture_8x256(2400 MHz, 390.625 kHz)          # FUN_40375c0c
    A = score(spec, paramsA) > 40.0 ; B = score(spec, paramsB) > 3.14   # FUN_4200552c
    if dji_alg == 2: det_24 = A && B
    if dji_alg == 3: det_24 = A || B
    if dji_alg == 1:
        for c in candidates(spec, {0.4,6,2,159,20,102,3}):        # FUN_42004acc
            td1 = observe_8192(c.start + c.width/3); td2 = observe_8192(c.end - c.width/3)
            det_24 |= classify(td1) && classify(td2)                # FUN_4200074c8 / FUN_4200512c
    if !det_24 and skydio_alg: det_24 = skydio_metric(spec) >= {100,70,60,50,40}[skydio_alg] (type 5)
if !det_24 and cfg.detect_zl_la == 2: det_zala = Zala_video_sweep()   # §2.2
spi_end
if !det_zala and a5133_present:
    r = (dji_alg==4) ? A5133_paranoid() : A5133_spectral()           # §2.3
    det_58 = (r == 2); det_24 |= (r != 0)
emit alarm (type 3 for 5.8, else 1/2/5) if ≥ 3000 ms since the last one of that type
```

### 5.2 Sub-GHz FSK match (IRAM `FUN_40376e74`, state 2 of `FUN_403771f0`)

```
on packet (after preamble detect, bitrate = current list entry, freq = current channel):
    rssi = read_rssi(); if noise_corr: rssi += 15
    hits = run_detectors(packet, len, freq, bitrate, rssi)   # FUN_42012388 → static table, cryptoorlan, count
    if hits empty: candidate_callback(freq, bitrate)         # "candidate f=%d, b=%d"  (stage-1 only)
    else:
        store_capture(freq, bitrate, rssi, first 0x16 bytes) → /fsk_data.bin
        if rssi < -(cfg.rssi_threshold >> 1): log "below threshold"; no alarm
        else: type = label(hits, bitrate); match_callback(freq, rssi, syncword, type, "%s %d.%d %d")
    if now - t_retune > cfg.f_change_delay or packets >= 8: next channel/bitrate
```

### 5.3 Sub-GHz LoRa mode 1 (`FUN_42017e58`) — see §2.6 for numbers

```
if rssi(ch) >= -94 dBm:
    LoRa modem, bw 500k, CAD for sf in 6..9 within 50 ms; on two consecutive CAD hits at sf:
        rx 8 bytes: snr > 0 → good++ ; else bad++ ; rx-timeout → tmo++, per_sf[sf]++
ch += 125 kHz
if ch is last: if max_rssi >= -199 and 6*good + 3*bad + tmo >= 6:
    sf* = argmax per_sf ; if per_sf[sf*] > {6:5, 7:8, 8:5, 9:4}[sf*]: match_callback(freq_of_max, max_rssi)
```

### 5.4 Track mode (`FUN_42008808`)

Mode 0/1 with target ≤ 705,032,704 Hz low-word (lit 0x42000388) → SX1280 `FUN_42007844`: f±10 MHz in 400 kHz
steps, 80 µs settle, two passes, detect if > 10 samples above −94 dBm; otherwise A5133 targeted scan (§2.3).

## 6. Other RF-relevant findings

* CoT/ATAK emission (`FUN_4201598c`): `<event version="2.0" uid="TS-DRONE-<type>-<id>" type="a-h-A-M-F-Q" how="m-g" time/start=now stale=now+3600 s (lit 0x42001278)>`, point lat/lon from settings, hae 10.0, ce 300.0, le 1e7 (lits 0x420012ac/b4/bc), `<detail><contact callsign="<type>"/></detail>`; sent by `FUN_4201533c` to `lan_notif_dmn/uri` (defaults empty). "COT circle" variant `FUN_42015dc0` is a UTF‑16 XML template at 0x3C0E7658. CSV line "detect;%lu;%f;%f;%d;%d;%s;%d;%llu;%lu" and JSON `{"action":"detect","device_id":…}`. CONFIRMED.
* Menu/labels: "%c Orlan+S %d", "%c ZalaLancet %s", "%c FPV %s", "%c DJI: %s", "%c ATAK %s", "FHSS/Brst r=%d" (FHSS/burst detector `FUN_42016b50`, params start 900e6/span 30e6/step 600e3 (lits 0x42001358/5c/60) and ratios 0.4/0.15 — INFERRED).
* Capture log format (`FUN_42018dbc`): "%d, %x%x%x%x, %d, %d, %d.%d, -%d" = time, 4 syncword bytes, bitrate, type, MHz.kHz, rssi/2.
* No transmit, jamming or spoofing code was found in the detection paths; `jam_fpv` is a stored flag only, and the only TX is the Meshtastic/twin notification link (§4.4).
* DJI OcuSync is not decoded; DJI detection is purely spectral (width/persistence in 2.4 GHz and 5.8 GHz), so its output is stage-1/stage-2 evidence only.

## 7. Follow-up pass (headless Ghidra, disassembly level) — resolutions of the former unknowns

A named Ghidra program archive (`tsukor_s3v4_5.5.12_named.gzf`, 173 functions named with plate comments) and
the reproduction scripts live in `tools/ghidra/tsukorok/`.

### 7.1 DJI 2.4 GHz parameter structs (CONFIRMED layouts from the `s32i` sequence in `TwoFourGScanner_Tick` 0x40375dad–0x40376080)

Two different scorers are used, not one:

**Algorithm A** — `DJI_ScoreA` (`FUN_42007270`, via wrapper 0x420073f4), params at stack 0x118:

| off | value | role (INFERRED from use) |
|---|---|---|
| +0x00 | double 390625.0 | bin width Hz |
| +0x08 | 5 | threshold offset dB above global median (`FUN_42006850` arg) |
| +0x0C | 5 | flatness tolerance dB (bins within ±5 dB of mean) |
| +0x10 | 5 | range penalty start (dB) |
| +0x14 | 2 | min segment width (bins) passed to segment finder |
| +0x18 | 1 | running-median half window (`FUN_42006c8c`) |
| +0x1C | 10 | trim percent for trimmed mean |
| +0x20 / +0x24 | 26 / 52 | preferred width window (bins ≈ 10–20 MHz) |
| +0x28 | 20 | gap merge (bins) and min width for features |
| +0x30 | double 39.0 | ideal width (bins ≈ 15.2 MHz) |
| +0x38 / +0x3C | 3 / 4 | per-bin sweep-count thresholds (of 8) |
| +0x40 / +0x48 | 0.0 / 100.0 | score clamp |

Pipeline: per-bin max over 8 sweeps → running median filter → segments above (median + 5 dB) with gap 20,
min width 2 → for each segment feature vector F (trimmed mean, mean−median, max−min, flatness fraction,
fraction of bins above threshold in ≥3 / ≥4 sweeps, per-sweep mean fractions) →
`s1 = clamp((mean−median−5)·2.5, 0, 25) + clamp((flat−0.55)·50, 0, 20) + widthTerm + clamp(10 − max(0, range−5)², 0, 10)`
where widthTerm = `clamp(25 − |w−39|·0.6, 8, 25)` inside [26, 52] else `clamp(12 − dist·0.8, 0, 12)`;
`s2 = clamp((p4−0.35)·60, 0, 30) + clamp((p3−0.5)·40, 0, 20) + clamp((f2−0.22)·80, 0, 20) + clamp((f1−0.25)·40, 0, 10) + clamp(mean−median−5, 0, 10)`;
score = max over segments of clamp(0.55·s1 + 0.45·s2, 0, 100); **tick threshold: score > 40.0** (lit 0x40374488).
Constants: lits 0x420001dc (2.5), 0x4200016c (25), 0x420001e0/e4 (0.55), 0x420001e8 (50), 0x420001b0 (20),
0x420001f4 (0.8), 0x420001d8 (12), 0x420001ec/f0 (0.6), 0x420001d4 (8), 0x42000170 (10), 0x420001b4/b8 (0.35),
0x420001bc (60), 0x42000188 (30), 0x42000178 (0.5), 0x420001c0 (40), 0x420001c4/c8 (0.22), 0x420001cc (80),
0x420001d0 (0.25), 0x4200017c/180 (0.45). All CONFIRMED.

**Algorithm B** — `DJI_ScoreB` (`FUN_4200552c`), params at stack 0x118 (memset then stores):

| off | value | role (INFERRED) |
|---|---|---|
| +0x00 | double 390625.0 | bin width |
| +0x08 | double 5.0 | dB above median for "above" |
| +0x10 / +0x14 | 18 / 60 | min / max segment width (bins ≈ 7–23 MHz) |
| +0x18 | 3 | gap merge |
| +0x20 | double 0.85 | fraction-above target |
| +0x28 | double 12.0 | dB scale |
| +0x30 | double 0.2 | |
| +0x38 / +0x3C | 3 / 2 | persistence: sweeps with ≥2 bins above; need ≥3 of 8 |
| +0x40 | double 0.4 | max fraction of "always-on" bins |
| +0x48 | double 0.85 | min fraction of above-threshold cells (bins × sweeps) |
| +0x50 | double 0.25 | edge fraction (edge bins = max(2, 0.25·w)) |
| +0x58 | double 5.0 | min centre − edge margin dB |
| +0x60 / +0x64 | 25 / 50 | soft width window (penalty (25−w)·3 below 25) |
| +0x68 | double 0.0 | score floor |
| +0x70 | double 100.0 | score cap |

**Tick threshold: score > 3.14** (lit 0x403744ac = 0x40490000). `dji_alg` 2 = A∧B, 3 = A∨B.
`dji_alg` 1 uses `Spec_FindCandidates` (`FUN_42004acc`, params {quantile 0.4, +6 dB, ≥2 sweeps, level −97 dBm (0x9F as i8), width 20..102 bins, gap 3}) and the time-domain classifier `TimeDomain_Classify` (`FUN_4200512c`) on two 8192-sample traces; class 1 (pass) requires burst count ≥ (param 0x2C − 2) with period/duty limits from the {156, 2, 750, 32, 75, 3, 0.3, 0.9, 64, 20, 5, 5, 0.5} block.
The "skydio" metric is the `NoiseLevelClassifier` output (80/60/40 by count of the dominant 3‑dB level > −90 dBm), compared with {100,70,60,50,40}[skydio_alg]. CONFIRMED.

### 7.2 A5133 strobes and registers — CONFIRMED against the A5133 datasheet v0.7 (Nov 2021, supplied by the user)

Datasheet facts used (§10.1, Table 10.3/11.1, §14.1, §17.1, register map):
SPI address byte: bit 7 = 1 strobe, bit 6 = read flag (matches the firmware's `reg|0x40` reads).
Strobes are 4-bit with A3..A0 don't-care when AFIDS = 0 and MIDS = 0 (reg 0x3E); the firmware writes reg 0x3E = 0.
Table 11.1: 1000 Sleep, 1001 Idle, 1010 Standby, 1011 PLL, 1100 RX (LNA on), **1101 TX (PA on)**, 1110/1111 FIFO
pointer resets. `FRF = 5725.001 MHz + CHN[7:0]·1 MHz` (reg 0x0E) — the firmware's 5725..5899 MHz plan is exact.
Reg 0x1E: write RTH (RSSI threshold), read ADC[7:0] (8-bit RSSI, ±6 dB accuracy). Reg 0x1B read = RH, reg 0x1C
read = RL (RSSI calibration high/low thresholds). Reg 0x23 bit 4 = FBCF (IF filter calibration fail), reg 0x25 bit 4 = VCCF
(VCO current cal fail), reg 0x26 bit 4 = VBCF (VCO band cal fail). Reg 0x35 = RF analog test, AGT[3:0] (bits 7:4) selects
the register page for 0x20/0x21/0x22/0x2A/0x38. Reg 0x3F = ID code. Reg 0x01 = mode control: firmware value 0x43 =
ARSSI (auto RSSI on RX entry) + FMS (FIFO mode) + ADCM. Reg 0x03 = FIFO end pointer: 0x3F → 64-byte packets.
Reg 0x21 page 8 = EXT2 with TPA[2:0] (PA current): firmware value 0x7C → TPA = 111 (maximum).
Background RSSI procedure (§17.1): RX strobe, stay ≥ 140 µs, exit RX, read ADC[7:0] — the firmware's 150 µs dwell matches.

Firmware strobe usage, decoded with that table:

| Firmware call | Byte on wire | Datasheet meaning | Where |
|---|---|---|---|
| `A5133_StrobeSleep` (0x80) | 1000xxxx | Sleep | after every sweep |
| `A5133_StrobeRX` (0xC0) | 1100xxxx | RX mode | start of each RSSI read (`FUN_420091cc`) |
| `A5133_StrobeTX_D8` (0xD8) | **1101**1000 | **TX mode** | 150 µs after RX in every RSSI read; 10 ms before calibration (`FUN_42009108`); 10 ms at every scan start (`FUN_42009398`/`FUN_42009538`) |
| `A5133_StrobeTX_D0` (0xD0) | **1101**0000 | **TX mode** | once after channel-group calibration at CHN 125 (5850 MHz) |

Consequence: the 5.8 GHz section is **not receive-only as coded**. The firmware uses the TX strobe as its
"exit RX" step. Each RSSI read leaves the chip in TX mode (PA enabled, TPA max) for the ~50–100 µs until the
next RX strobe (inside the datasheet's ~120 µs TX settling/ramp-up window, so a full packet is unlikely there),
but the two 10 ms dwells at calibration and at scan start are long enough for the FIFO-mode packet
(preamble + ID + 64 bytes, then auto-standby) to be transmitted on the current channel — after calibration that is
CHN 125 = 5850 MHz. Status: strobe bytes and datasheet semantics CONFIRMED; actual radiated emission is INFERRED
and should be verified with a HackRF/E200 capture at 5850 MHz while the device starts a 5.8 GHz scan. This is
either a firmware bug (author intended Standby 0xA0 or PLL 0xB0) or deliberate; the image contains no other TX use
of the A5133.

RSSI conversion (`A5133_ReadRssiDbm`): dBm = ((ADC − RL)/(RH − RL))·12 − 80 − 3, with RL/RH from regs 0x1C/0x1B
after calibration; the datasheet gives no dBm formula, so the 12/−83 mapping is the vendor's own (CONFIRMED values).

### 7.3 Detector registration order (CONFIRMED, `DetectorSet_Ctor` 0x42012534)
[0] syncword-count detector (vtable 0x3C0E6B38), [1] static table (0x3C0E6B4C), [2] cryptoorlan (0x3C0E6A3C).
`FSK_MatchOnPacket` uses the first hit with a non-zero syncword for the capture record; the label function
walks all hits and the last non-zero type wins the return code.

### 7.4 RadioLib identities (CONFIRMED by register)
`FUN_4201ee14` = `SX127x::setAFC` (reg 0x0D bit 4 AfcAutoOn); `FUN_4201db6c` = LNA boost HF (reg 0x0C bits 1:0 = 0b11
when enabled; RadioLib `setRxBoostedGainMode`-equivalent); `FUN_4201daf0` = custom bandwidth/SF set with the
500 kHz errata registers 0x36/0x3A.

### 7.5 Shape test and labels
`A5133_WindowShapeTest` (`FUN_420c78a8`, n = 16): find the peak index p; require 1 < p < n−1; require a strictly
rising pair (x[i] < x[i+1] < x[i+2]) somewhere before p−2 and, after p, a falling pair (x[j] > x[j+1] > x[j+2])
or a sample more than 4 dB below the peak → returns 1 (immediate "dji 5.8" confirm). CONFIRMED.
Labels "Sc" and "X3" have no other references in the image; by the naming pattern (Or = Orlan, Za = Zala,
ZL = ZalaLancet, El = ELRS, Lc = Lancet) "Sc" is most likely Supercam and "X3" the cryptoorlan class — INFERRED only.

### 7.6 Time-domain burst classifier (`dji_alg == 1`) — now traced

Parameter block (CONFIRMED from the `s8i/s32i` sequence at 0x40376179–0x403761b9, base stack 0x74, 0x38 bytes,
copied by `SkydioParams_Copy` 0x4200457c which also zeroes the run-statistics area):

| off | value | role (INFERRED from `TimeDomain_Accumulate` 0x420052f0 / `TimeDomain_Classify` 0x4200512c) |
|---|---|---|
| +0x00 | i8 −100 | RSSI threshold dBm separating "burst" from "gap" samples |
| +0x04 | 2 | hysteresis: a state change needs > 2 consecutive opposite samples |
| +0x08 | 750 | max allowed gap length (samples) — longer → reject |
| +0x0C / +0x10 | 32 / 75 | "short burst" length window; bursts with 32 < len < 75 are counted |
| +0x14 | 3 | reject if short-burst count ≥ 3 |
| +0x18 | 0.3 | min duty (burst samples / total) |
| +0x1C | 0.9 | max duty (above it the channel is treated as continuously occupied → class 0, pass) |
| +0x20 | 64 | min run length recorded into the long-burst / long-gap vectors |
| +0x24 | 20 | quantisation bucket (samples) for run-length histogramming |
| +0x28 | 5 | min number of long bursts and long gaps |
| +0x2C | 5 | min repeat count of the modal gap length (test uses value − 2 = 3 for gaps) |
| +0x30 / +0x34 | 0.5 / 0.5 | min fraction of runs covered by the modal length buckets (bursts / gaps) |

Samples: 8192 RSSI reads on one channel (`SX1280_ObserveTimeDomain`), each read ≈ 20–30 µs over SPI
(INFERRED), so the trace spans roughly 0.2 s and the 20-sample bucket ≈ 0.5 ms.
Decision: duty ≥ 0.9 → class 0 (pass, "continuous"); else reject (class 2) if max gap > 750 or
short-burst count ≥ 3 or duty < 0.3; else require ≥ 5 long bursts and ≥ 5 long gaps, quantise run lengths to
20-sample buckets, and pass (class 1) when the modal gap bucket repeats ≥ 3 times, the modal burst bucket
repeats ≥ 5 times and the top buckets cover ≥ 50 % of runs. A candidate is confirmed when both observed
channels (start + width/3 and end − width/3) pass. CONFIRMED structure, INFERRED naming.

### 7.7 Timing helpers (CONFIRMED)
`FUN_42027a2c` is Arduino `delayMicroseconds` (busy-wait on `esp_timer_get_time`), `FUN_42027a1c` is `delay(ms)`,
`FUN_42027a00` is `millis()`. All settle times quoted in §2 are therefore microseconds as stated.

### 7.8 Remaining unknowns
None at the static-analysis level. Open verification items are hardware measurements: (a) the 5.8 GHz TX-mode
emission described in §7.2; (b) whether the nine static sub-GHz syncwords occur in real captures.

## 8. Implications for AERIX RF (INFERRED, for the architect)

* This device is a useful *reference of vendor heuristics*, not of ground truth: every alarm it raises is
  stage‑1/2 evidence. Its "DJI" verdict is a spectral-width/persistence score in 2.4/5.8 GHz; AERIX RF's
  Stage‑1 morphology vocabulary already covers the same features (bandwidth ≈ 7–23 MHz, persistence across
  sweeps, edge steepness). The concrete thresholds in §7.1 are a reasonable prior for a "DJI-like wideband"
  candidate class, nothing more.
* The sub‑GHz FSK part is the most directly reusable: bitrate classes (57.6 k / 76.19 k / 38.15 k / 80 k Orlan‑class,
  15.235 k Zala/Lancet‑class, ≈85 k and ≈115 k for other classes), the 860–885 / 895–928 / 970–1020 MHz plan,
  and the nine static 32‑bit post-preamble words (§3.2). A HackRF/E200 capture at those bitrates can test whether
  those words actually appear — that would move them from "vendor table" to protocol-specific evidence (level 3).
* The ELRS logic (CAD on SF6–9 at 500 kHz, LoRa sync 0x12/0x14) is a cheap probabilistic test AERIX RF could
  emulate with a LoRa CAD-equivalent correlator on captured IQ, but it is not identification.
* Nothing here supports a deterministic decoder; the device stores only the first 0x16 bytes of a packet.
* Verification task for the hardware side: capture 5850 MHz (and a 5725–5899 MHz sweep) with the HackRF while the
  Tsukorok starts a 5.8 GHz scan, to confirm or refute the A5133 TX-mode emission (§7.2). If confirmed, the device
  must not be treated as a silent reference receiver during AERIX RF field tests at 5.8 GHz.
