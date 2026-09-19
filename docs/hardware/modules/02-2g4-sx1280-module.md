# Module 2 — 2.4 GHz receiver (SX1280), 2400–2500 MHz

Version 0.1, 2026-09-19. Read `00-common-slot-interface.md` first; everything there applies.
Purpose: fast RSSI sweeps of 2400–2500 MHz for DJI-class wideband/persistence scoring and the Zala-class
video sweep, plus LoRa CAD/packet reception at 2.4 GHz (ELRS 2.4). All output is stage-1/2 evidence.
This module does **not** replace the SDR path: it has no IQ, only RSSI and demodulated LoRa/FLRC packets.

## 1. Hardware

| Item | Requirement |
|---|---|
| Radio | Semtech **SX1280** (or SX1281, the RX-only-ranging-less variant is fine since ranging is not used). |
| Reference | 52 MHz TCXO (±2 ppm) or crystal ±10 ppm. TCXO preferred: the ELRS CAD at 812.5 kHz BW / SF5 tolerates ±10 ppm, but frequency-error reporting per packet needs the TCXO. |
| RF front end | RX only: antenna → optional band-pass (2400–2500 MHz SAW/BAW, ≤ 1.5 dB IL) → SX1280 RF input via the datasheet balun/match. No RF switch needed if the TX path is left unmatched; if the reference design's SPDT is kept for layout reuse, tie its control to RX permanently. |
| Optional LNA | Footprint for a 2.4 GHz LNA (e.g. 1 dB NF, +15 dB) with bypass 0 Ω; not fitted in v1. The SX1280 NF (~7 dB in RSSI mode) is adequate for the sweep use; the LNA matters only for far ELRS packets. |
| Antenna | u.FL to an external 2.4 GHz antenna; the module must **not** share the antenna with the ESP32-S3 (its Wi‑Fi/BLE is disabled anyway; use a bare ESP32-S3 chip or a WROOM with the antenna unused). |
| Bus | SPI ≤ 18 MHz: SCK/MISO/MOSI/NSS, RESET, **BUSY**, **DIO1**, DIO2 optional. |
| ESP32-S3 | WROOM-1-N8R8 or bare chip with 8 MB flash + 8 MB PSRAM (sweep history: 8 sweeps × 256 bins plus 250-bin history). Place the ESP32 at the far end from the u.FL; its 40 MHz clock's 60th harmonic is 2400 MHz. |
| Power | SX1280 RX ≈ 10 mA; module total ≈ 100 mA. |
| Shield | Shield can over SX1280 + match + filter. |

## 2. Firmware requirements

### 2.1 Scan plan (defaults, configurable via CFG)

* Sweep raster A (Tsukorok-compatible): 2400.0–2499.6 MHz, 400 kHz steps, 250 channels, 40 µs settle,
  RSSI via `GetRssiInst` in FSK mode (beginFSK 2400 MHz, 250 kbps, 195 kHz deviation as the reference).
  Cadence: one sweep per second for class C; eight sweeps back-to-back every 5 s for the scoring pass.
* Sweep raster B (Zala-class video): 2200.0–2399.6 MHz, 400 kHz, 60 µs settle, once per 5 s when
  enabled (the SX1280 tunes down to 2400 MHz only per datasheet; **verify** that the part receives at
  2200–2400 MHz with acceptable RSSI accuracy — the Tsukorok does this out of spec. If not, the raster B
  requirement is dropped and noted in HELLO capabilities).
* Fine raster for the server: 256 × 390.625 kHz from 2400 MHz (the DroneID/OcuSync bin size used in the
  Tsukorok scoring), selectable instead of raster A.
* LoRa: CAD/receive at 2.4 GHz, BW 812.5 kHz, SF 5–8, CR 4/6 (SF5) or 4/8, sync 0x14 and 0x12, preamble
  12 (ELRS 2.4 profile); 400 kHz channel steps over a CFG-defined range ≤ 100 MHz wide; per-packet
  RSSI, SNR, frequency error, first 32 bytes.
* Track mode on CMD: f ± 10 MHz at 400 kHz, 80 µs settle, two passes (for a server-directed re-check).

### 2.2 Detection logic on the module

* Implement the Tsukorok stage-1 rules as **candidate producers**, not as alarms: 16-channel window
  (≥ 8 of 16 above the gate) with the < 125/250 broadband guard; spectral score A (median + 5 dB
  segments, width 26–52 bins, persistence ≥ 3 of 8) and score B (width 18–60 bins, persistence, 85 %
  fill, 5 dB centre-edge margin) as in the extraction brief §7.1; time-domain burst test on request
  (class G trace to the host instead of on-module classification).
* ALARM (class A) only when a candidate persists ≥ 2 consecutive scoring passes **and** the score
  exceeds the CFG threshold; everything else is class E CANDIDATE with the score attached, so the server
  can re-tune thresholds from data.
* Noise-level histogram (the "Skydio" metric) is reported in HEALTH, never as an alarm.

### 2.3 Data produced

Classes A, B (LoRa packets), C (250-point sweep per second, i8 dBm, plus the optional 500-point raster B
every 5 s), D (occupancy per 400 kHz channel every 60 s), E (candidates with score A/B, width, centre),
F. Class G over USB: 8-sweep spectrum blocks (2 048 bytes) and 8 192-sample time-domain RSSI traces.

## 3. Module-specific acceptance tests

1. Sweep timing: 250 channels in ≤ 15 ms including settle; RSSI repeatability ±1.5 dB on a −60 dBm CW.
2. RSSI linearity: −100 to −30 dBm within ±3 dB against a reference at 2440 MHz.
3. Wi‑Fi rejection check (bench, not a spec): a 20 MHz Wi‑Fi channel at −50 dBm must appear as a
   ~51-bin block; the module must report it as CANDIDATE, not ALARM, with the default thresholds.
4. ELRS profile: SF5/812.5 kHz test packets at −100 dBm received on ≥ 90 % of attempts; frequency
   error within ±5 kHz of the applied offset.
5. Raster B feasibility measurement at 2200–2400 MHz documented (pass/fail recorded in HELLO caps).
6. No emission (common test 6) — including no LoRa CAD-then-TX and no ranging.
