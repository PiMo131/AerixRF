# Module 1 — Sub-GHz FSK/LoRa receiver (SX1276), 860–1020 MHz

Version 0.1, 2026-09-19. Read `00-common-slot-interface.md` first; everything there applies.
Purpose: the highest-value part of the Tsukorok reference chain — FSK packet reception with
post-preamble word capture, LoRa channel-activity detection (ELRS-class links), and full-band RSSI
sweeps for the server baseline. Evidence produced is stage-1/2 (candidates and probabilistic
classification); no protocol decode is claimed.

## 1. Hardware

| Item | Requirement |
|---|---|
| Radio | Semtech **SX1276** (not SX1278: the 862–1020 MHz PA/LNA band variant; SX1278 is the 137–525 MHz part). SX1262 is not a drop-in: the firmware uses SX127x register-level features (CAD DIO mapping, RX-single fast receive, FSK preamble-detect-without-sync). |
| Reference | 32 MHz **TCXO** (±2 ppm) preferred; 32 MHz crystal ±10 ppm acceptable. Rationale: 100 kHz channel raster and 500 kHz LoRa CAD tolerate ±10 ppm, but frequency-error reporting (used by the server to match words across sensors) is only meaningful with a TCXO. |
| RF front end | RF switch not required (RX only): connect the antenna to RFI_HF through the datasheet HF match; leave RFO_HF/PA_BOOST unconnected. Add a **band-pass or high-pass filter for 860–1020 MHz** (e.g. SAW 863–928 MHz is too narrow — use a discrete 5th-order high-pass at ~800 MHz plus low-pass at ~1.1 GHz) to keep GSM‑900 downlink at 925–960 MHz from desensitising the LNA when the sensor is near a base station. Note: 925–960 MHz sits inside the sweep plan; the filter is about overload, not about removing that band. |
| Optional LNA | Not in v1. Provide footprint + bypass 0 Ω for a 1 dB NF LNA (e.g. BGA2817-class) if field tests show the SX1276 NF (~6 dB) limits range; if fitted, add a 2‑stage filter before it. |
| Antenna | u.FL to an external 868/915 MHz antenna (dual-band 868/915 whip covers 860–930 MHz; a 900–1000 MHz coverage note must go to the antenna selection: most SRD antennas roll off above 930 MHz, the 970–1020 MHz range needs a wideband or dedicated antenna). |
| Bus to ESP32-S3 | SPI ≤ 10 MHz: SCK/MISO/MOSI/NSS, RESET, **DIO0, DIO1, DIO2** (all three needed: RxDone/CadDone, RxTimeout/CadDetected/FifoLevel, FifoLevel/SyncAddr), DIO5 optional (ModeReady). Use dedicated GPIOs with ISR capability. |
| ESP32-S3 | WROOM-1-N8R8 or equivalent: PSRAM required for sweep and occupancy buffers (1 600 channels × statistics), 8 MB flash for two OTA slots. |
| Power | Radio on a filtered/LDO 3.3 V branch (SX1276 RX ≈ 12 mA); ESP32-S3 ≈ 60–90 mA scanning with Wi‑Fi/BLE off. Module total ≈ 100 mA, well inside the 250 mA budget. |
| Shield | Shield can over SX1276 + match + filter. |

Pin map on the base headers: exactly as `00-common-slot-interface.md` §2; all radio signals stay on the
module. Bring SCK/MISO/MOSI/NSS/DIO0 to test pads.

## 2. Firmware requirements

### 2.1 Scan plan (defaults, all configurable via CFG)

* Band plan: 860–885, 895–928, 970–1020 MHz (the Tsukorok defaults), step 100 kHz → 1 080 channels;
  the module must also accept any set of up to 8 ranges inside 860–1020 MHz.
* Bitrate classes to receive (FSK, 2‑FSK/GFSK, RX BW 200 kHz, AFC on): 57.6, 80.0, 15.235 kbps (Tsukorok
  defaults) plus 38.4, 76.19 and 38.15 kbps, list configurable up to 8 entries. Preamble detector on,
  **sync word detection off** (fixed-length reception starting at the first byte after the preamble), so
  the first 4 bytes of every packet are the "word" the server fingerprints.
* LoRa: CAD at BW 500 kHz, SF 6–9, CR 4/7, sync 0x12 (ELRS-class), also BW 125/250 kHz SF 7–12 sync 0x12
  and 0x34 for the inventory of LoRaWAN/Meshtastic (identify, do not decode payloads).
* Scheduler: (1) RSSI pre-pass over the whole plan (1 080 channels, ≥ 140 µs dwell → ≈ 0.2 s); (2) FSK
  dwell only on channels above the RSSI gate, 50 ms per bitrate, longest-first; (3) LoRa CAD pass over
  the same active channels; (4) full sweep for class C every 5 s regardless. Target: full cycle ≤ 60 s in
  a quiet band, ≤ 3 min urban. This is deliberately faster than the Tsukorok (5–8 min).
* RSSI gate: per-band value from CFG (default −85 dBm before calibration); below it: counted in
  occupancy only, no packet reception attempted.

### 2.2 Detection logic on the module

* Static word table (from the Tsukorok firmware, §3.2 of the extraction brief) with normalisation
  (top bits 00/11 → mask 0x7FFFFFFF, else strip leading alternating bits) and the bitrate/band labels.
  The table is CFG-loadable; the server owns it.
* Repetition detector: same normalised word on the same channel ≥ 2 times within 20 min → CANDIDATE
  with fingerprint; band/bitrate rules as in the brief (§3.4) produce the type code.
* Every packet above the gate → class B PACKET regardless of detector outcome (this is the near-alarm
  stream the server wants). ALARM (class A) only for static-table hits or repetition hits **and** RSSI
  ≥ gate + 6 dB; the server makes the final call.
* Corrections: report raw RSSI and the applied offset separately; never bake the Tsukorok "+15 dB" style
  correction into the value.

### 2.3 Data produced

Classes A, B, C (1 600-point sweep every 5 s, 100 kHz raster, i8 dBm), D (per-channel occupancy every
60 s), E, F. Class G over USB: 100-byte packet bodies and 1 s continuous RSSI traces on request.

## 3. Module-specific acceptance tests

1. Sensitivity at 868.3 MHz, 38.4 kbps GFSK, PER 1 %: ≤ −104 dBm at the u.FL (SX1276 datasheet ≈
   −107 dBm at 38.4 kbps; the 3 dB margin covers filter and match loss).
2. Overload: with a −20 dBm CW at 942 MHz (GSM downlink) applied, sensitivity at 868.3 MHz degrades by
   ≤ 6 dB.
3. Word capture: a test transmitter (bench signal generator, not the module) sending a known 32-bit word
   at 57.6 kbps yields the same word in ≥ 99 % of class B records; frequency-error field within ±2 kHz
   of the applied offset.
4. LoRa CAD: SF7/500 kHz test packets at −110 dBm are detected on ≥ 90 % of passes.
5. Full cycle time ≤ 60 s with no activity, ≤ 180 s with 50 active channels.
6. No emission (common test 6).
