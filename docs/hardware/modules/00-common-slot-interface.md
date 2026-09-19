# AERIX01 receiver modules — common slot interface and data contract

Version 0.1, 2026-09-19. Applies to the three receiver modules specified in
`01-subghz-sx1276-module.md`, `02-2g4-sx1280-module.md` and `03-5g8-rx5808-module.md`.
Base board: AERIX01 V1 (schematic PM_AERIX01_V1, sheets "Dual ESP32-C5", "Dual ESP32S3", "USB HUB").

Decisions already taken (do not re-open without the project lead):

| Topic | Decision |
|---|---|
| Slots used | The two ESP32-C5 slots and the AUX ESP32-S3 slot. The MAIN S3 stays the system controller. |
| Base board | V1 as built, plus **one small change**: route GNSS_PPS to one pin of each receiver slot (§4). |
| Module MCU | ESP32-S3 (module with PSRAM, e.g. ESP32-S3-WROOM-1-N8R8 or bare chip + flash/PSRAM). |
| Data path | UART to the MAIN S3 for alarms, near-alarms and compact diagnostics; USB (already routed to the USB2517 hub) for bulk data to the Linux host. |
| Uplink assumption | Ethernet/PoE; per-sensor upstream budget of tens of kB/s is available. |
| Transmit | Firmware-only lock-out. Standard radio wiring; TX is never initialised. RX-only is a firmware requirement in every module spec. |
| Sub-GHz band | 860–1020 MHz. |
| Diagnostic set | Raw packet heads, full RSSI sweeps, per-channel occupancy statistics. Receiver health is a lower-priority extra. |

Note on the AUX slot: the AUX S3 also owns the LTE modem control/UART lines and the AUX SPI expansion
header. Putting a receiver module there removes LTE control unless the modem is driven from the MAIN S3
in firmware. If LTE is required at a site, only the two C5 slots carry receiver modules there.

## 1. Mechanical

* Same outline, mounting and header positions as the existing ESP32-C5 module drawing (base-board
  mechanical reference; the hardware designer holds the master outline). Modules must be interchangeable
  between the two C5 slots and the AUX slot.
* Headers: two 1×12 2.54 mm (base side PPTC121LFBN-RC) and two 1×4 2.54 mm (base side 61300411821),
  same positions as the C5 module.
* Antenna: one u.FL (IPEX MHF1) at the same corner as on the existing modules; 50 Ω, ground-stitched
  microstrip, ≤ 15 mm from radio pin to connector. A shield can over the radio section is required for
  the sub-GHz and 2.4 GHz modules (matches the existing modules and keeps the ESP32 clock harmonics away
  from the receiver).
* Height envelope: as the existing module (shield can + u.FL); no components under the module on the base
  board side.
* Silkscreen: module type, revision, and the slot compatibility mark "C5/AUX".

## 2. Electrical interface (what the base board provides)

From the schematic, a C5 slot connects only these nets (all other header pins are unconnected on V1):

| Base header pin | Net | Module ESP32-S3 pin | Notes |
|---|---|---|---|
| Left 1×12, pin 12 | +3V3 (through 120 Ω @100 MHz ferrite, 10 µF) | 3V3 | see current budget |
| Left 1×12, pin 10 | MCU_EN (RST header pulls low) | EN (CHIP_PU) | 10 k pull-up on module, 1 µF to GND |
| Left 1×12, pins 1 and 6 | GND | GND | |
| Right 1×12, pin 10 | UART_TX0 → MAIN S3 RX | U0TXD (GPIO43) | 3.3 V logic |
| Right 1×12, pin 9 | UART_RX0 ← MAIN S3 TX | U0RXD (GPIO44) | |
| Right 1×12, pin 3 | BOOT header (C5 slot: GPIO28 position) | GPIO0 via 0 Ω option R_BOOT_A | strap; see §2.1 |
| 1×4 "USB", pins 2/3 | USB D−/D+ → hub downstream port | GPIO19/GPIO20 (USB_D−/D+) | keep as a 90 Ω pair, ESD diode array |
| 1×4 "USB", pins 1/4 | GND | GND | |
| 1×4 "GPIO", pins 1–3 | C5 GPIO9/10/5 positions (unconnected on base) | spare, bring out for test | |
| Right 1×12, pin 6 | **GNSS_PPS (new, §4)** | GPIO4 (input) via 0 Ω option R_PPS | |

### 2.1 Slot-compatibility rules

* Use **only** 3V3, GND, EN, UART0, USB and the PPS pin on the base side. Every other header pin is
  no-connect on the module, so that the same module drops into the AUX S3 slot (which routes modem, SPI
  and I²C nets to other pins) without conflict. The designer must verify against the base netlist that
  3V3/EN/GND/UART0/USB sit at the same header positions in all three slots; where the BOOT or PPS position
  differs per slot, provide 0 Ω option resistors (R_BOOT_A/B, R_PPS_A/B) so one PCB serves all slots.
* Boot strapping: GPIO0 also on a module-side push button and a test pad; GPIO46 and GPIO45 strapped per
  Espressif defaults (GPIO46 low, GPIO45 low for 3.3 V flash).
* EN: 10 k to 3V3 and 1 µF to GND on the module; the base RST header shorts EN to GND.

### 2.2 Power

* Supply: single 3V3 through the base ferrite. Modules must not back-feed 5 V and must not draw from USB
  VBUS (the hub ports 1–4 have no switched VBUS to the module headers).
* Budget per module: ≤ 250 mA average, ≤ 500 mA for 10 ms peaks. Wi‑Fi and BLE on the module ESP32-S3
  are disabled in firmware (they are not needed and would add 300 mA peaks and 2.4 GHz self-interference).
* Local decoupling: 10 µF + 100 nF at the module input, separate LDO or filtered 3V3 rail for the radio
  (≥ 40 dB rejection at 100 kHz–10 MHz; a 3.3 V → 3.0 V LDO for the radio is acceptable if the radio
  supports it) so ESP32 switching noise does not desensitise the receiver.

### 2.3 Clocking

* Radio TCXO or crystal per the module spec (frequency accuracy drives channel raster and CAD
  performance; ±10 ppm max for sub-GHz and 2.4 GHz, TCXO preferred on the sub-GHz module).
* ESP32-S3 40 MHz crystal as usual; keep its harmonics (e.g. 2400 MHz = 60 × 40 MHz) in mind in the
  layout of the 2.4 GHz module: place the ESP32 at the far end from the u.FL.

## 3. UART contract to the MAIN S3

### 3.1 Link

* 3.3 V UART, **921 600 baud, 8N1**, no hardware flow control (RTS/CTS are not routed). Fallback speed
  115 200 for bring-up; speed negotiated by the MAIN S3 with `CFG.baud` after boot.
* Framing: COBS-encoded frames, 0x00 delimiter, CRC‑16/CCITT (0x1021, init 0xFFFF) over the decoded
  payload. Maximum frame 512 bytes.
* Flow control: credit based. The MAIN S3 grants credits (`ACK.credits`, frames the module may send);
  the module never sends more than the granted number of frames and drops low-priority classes first
  (§3.3) when credits run out. This is what makes "no RTS/CTS" safe.
* Direction: module → MAIN S3 carries data; MAIN S3 → module carries configuration, time and credits.

### 3.2 Frame payload

```
u8  type        message type (§3.4)
u8  seq         wraps at 255; gaps let the S3 count drops
u32 t_us        microseconds since the last PPS edge (or since boot if no PPS yet, flag in HEALTH)
u16 pps_count   number of PPS edges seen since boot (rolls over)
...             type-specific body, little-endian, fixed layouts, no strings
```

Every module tags every record with (`pps_count`, `t_us`). The MAIN S3 converts that to UTC using its
GNSS time and forwards; this gives ~1 µs relative timestamps between modules on the same base board and
across sensors, which the server needs for multi-sensor correlation.

### 3.3 Data classes and "enough"

"Enough" is defined as: every class below at its nominal rate, simultaneously, in an urban worst case,
with 3× headroom on the link. Sizes are payload bytes on the wire after COBS (≈ +1 %).

| Class | Content | Nominal rate (urban worst case) | Bytes/s | Priority (dropped last = 1) |
|---|---|---|---|---|
| A ALARM | detector verdict: type code, freq, bandwidth/bitrate, RSSI, SNR, score, fingerprint (syncword or hash), count, first/last time | ≤ 2/s | 200 | 1 |
| B PACKET (near-alarm) | every packet above the RSSI gate: freq, bitrate/SF/BW, RSSI, SNR, frequency error, preamble length, **first 32 bytes** (64 bytes on request), CRC-present flag | 20/s sub-GHz; 5/s LoRa | 2 000 | 2 |
| C SWEEP | full RSSI vector: sub-GHz 1 600 × 1 B (100 kHz) every 5 s; 2.4 GHz 250 × 1 B every 1 s; 5.8 GHz 175 × 1 B every 1 s | per module | 320 / 250 / 175 | 4 |
| D OCCUPANCY | per channel (same raster as C): busy fraction (u8), RSSI p50/p95 (i8), burst count (u8) — sent as a delta once per 60 s | 1 per minute | ≤ 110 | 3 |
| E CANDIDATE | stage-1 morphology events without alarm: freq, width, duration, score, why-rejected code | ≤ 5/s | 250 | 3 |
| F HEALTH | noise floor per band, AGC/gain state, radio temperature, PLL lock, dropped-frame and credit-starvation counters, PPS present, firmware hash | every 10 s | 10 | 1 |
| G TRACE (bulk, USB only) | raw time-domain RSSI traces (e.g. 8 192 samples), long packet bodies, high-rate sweeps | on request | up to 200 kB/s on USB | USB only |

Total on the UART in the worst case: ≈ 3 kB/s per module against ≈ 90 kB/s available at 921 600 baud.
Three modules fan into three separate UARTs on the MAIN S3, so there is no shared-bus contention; the
MAIN S3 must be able to forward 3 × 3 kB/s plus its own traffic over Ethernet (trivial) and, in the LTE
fallback profile, must be able to switch classes C and E off per module with `CFG`.

### 3.4 Message types

| type | dir | name | body |
|---|---|---|---|
| 0x01 | M→S | HELLO | module type, hw rev, fw version/hash, capabilities bitmap, PPS present |
| 0x02 | S→M | CFG | TLV list: band plan, freq step, bitrate list, SF list, RSSI gate per band, sweep cadence, class enable mask, packet head length (32/64), baud |
| 0x03 | S→M | TIME | UTC seconds of the last PPS edge, leap flag; sent once per second after each PPS |
| 0x04 | S→M | ACK | last seq received, credits granted |
| 0x10 | M→S | ALARM | class A |
| 0x11 | M→S | PACKET | class B |
| 0x12 | M→S | SWEEP | class C (chunked, chunk index/total in body) |
| 0x13 | M→S | OCCUPANCY | class D |
| 0x14 | M→S | CANDIDATE | class E |
| 0x1F | M→S | HEALTH | class F |
| 0x20 | S→M | CMD | start/stop scan, run self-test, request TRACE over USB, reboot to bootloader |
| 0x7F | both | LOG | text, debug only, class 5 (first to be dropped) |

All numeric fields: frequencies in Hz (u32), RSSI/SNR in 0.25 dB steps (i16), bitrates in bps (u32),
bandwidths in Hz (u32), durations in µs (u32).

### 3.5 USB

* USB 2.0 full/high speed device on the ESP32-S3 native USB (TinyUSB): one CDC-ACM interface for the
  same framed protocol (for bench use and for the Linux host), plus one vendor bulk endpoint for class G.
* USB is optional at runtime: the module must run fully on UART alone (no host present). Enumeration must
  not depend on VBUS (self-powered device, VBUS sense on GPIO via divider only for connect detection).
* The hub's upstream is one USB 2.0 link shared by everything on the board: class G is throttled by the
  host, not by the module.

## 4. Base-board change: GNSS PPS to the receiver slots

* Add one trace from the GNSS `TIMEPULSE` net (MAX‑M10S pin 4, series 33 Ω R86, currently only on the
  MAIN S3 P3 header) to one currently-unconnected header pin in each of the three receiver slots.
  Proposed position: right 1×12 header pin 6 (the C5 "GPIO15" position; verify the equivalent position
  on the AUX slot is free). Series 33 Ω at each branch, 3.3 V CMOS, 100 ms high pulse once per second.
* Fan-out: MAX‑M10S TIMEPULSE can drive four CMOS inputs directly; if trace lengths exceed ~15 cm add a
  single 74LVC1G17 buffer near the GNSS.
* Modules capture PPS on a GPIO with an ISR (or the ESP32-S3 GPTimer capture) and reset `t_us`.
* With this change, timestamps between modules are within ±1 µs; without it (V1 unchanged) the module
  clocks are synced over UART `TIME` messages and are only good to ±1 ms, which is enough for alarms but
  not for cross-sensor burst matching.

## 5. Firmware requirements common to all modules

* Framework: ESP-IDF 5.x (Arduino component optional), RadioLib for the SX radios, TinyUSB for USB.
* Receive-only: no call to any transmit, CAD-then-TX, beacon or ranging API; radio TX pins and PA control
  are left in their reset state; compile-time `CONFIG_AERIX_RX_ONLY=y` removes TX code paths. A unit
  test greps the linked image for TX entry points.
* Boot: HELLO within 2 s of EN release; scanning starts only after CFG (defaults stored in NVS if the
  S3 is silent for 5 s).
* Watchdog on the scan loop; HEALTH every 10 s; no dynamic allocation in the scan loop.
* Every record carries `pps_count`/`t_us`; sweeps carry the exact start/stop time of the sweep.
* NVS holds: band plan, gates, cadences, module serial, calibration offsets (RSSI offset per band from
  a reference measurement, applied on the server, transmitted in HELLO).
* OTA of the module firmware through the MAIN S3 (`CMD` reboot-to-bootloader + UART loader) or USB.

## 6. Acceptance tests (per module, before the design is signed off)

1. Slot fit in both C5 slots and the AUX slot; RST/BOOT headers work; enumerates on the hub.
2. 3V3 current ≤ 250 mA average during scanning, ≤ 500 mA peak.
3. Receiver sensitivity within 3 dB of the radio datasheet at the u.FL with the ESP32 running the scan
   loop (proves the supply filtering and layout).
4. UART: 1 hour at 921 600 baud with classes A–F at nominal rate, zero CRC errors, zero credit starvation.
5. PPS: two modules on one base board timestamp a common test burst within 2 µs.
6. Spurious emissions: no measurable emission from the module in any band (spectrum analyser at the
   antenna port, RBW 10 kHz) — proves the receive-only claim in hardware terms.
7. Module-specific tests in each module document.
