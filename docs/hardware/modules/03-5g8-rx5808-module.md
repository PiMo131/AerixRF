# Module 3 — 5.8 GHz RSSI receiver (RX5808 / RTC6715), 5645–5945 MHz

Version 0.1, 2026-09-19. Read `00-common-slot-interface.md` first; everything there applies.
Purpose: receive-only replacement for the Tsukorok's AMICCOM A5133 path (5725–5899 MHz RSSI sweeps,
steep-edge/width rules for FPV-video-class and DJI-5.8-class candidates). The RX5808 is an analog
5.8 GHz video receiver whose tuner is SPI-programmable and which provides an analog RSSI output; it
cannot transmit, has no data path, and covers a wider band than the A5133. All output is stage-1 evidence.

## 1. Hardware

| Item | Requirement |
|---|---|
| Receiver | **RX5808** module (RTC6715-based) in SPI mode — the SPI-mod (remove the fixed-channel resistor, expose CH1/CH2/CH3 as SPI CLK/DATA/LE). Prefer a module variant with a shielded tuner and a u.FL; if only a solder-pad antenna version is available, add a short 50 Ω trace to a u.FL. Alternative if RX5808 supply is a problem: any RTC6715 or RTC6712 board with SPI-accessible synthesizer and RSSI pin. |
| Tuning | RTC6715 synthesizer register: frequency = 2 × (N × 32 + A) × 1 MHz / … (per RTC6715 datasheet; ~1 MHz nominal steps achievable). Required plan: 5645–5945 MHz in 1 MHz steps (≈ 300 channels), with the Tsukorok plan 5725–5899 MHz as the default subset. |
| RSSI | Analog RSSI pin (≈ 0.5–1.1 V over ≈ −90 to −40 dBm, module dependent) → RC filter (1 kΩ / 10 nF) → ESP32-S3 ADC1 channel; also route to a test pad. Add a precision 2.5 V or 3.0 V ADC reference or use the ESP32-S3 calibrated attenuation setting; the ADC noise floor must be ≤ 1 LSB rms at 12 bits after the RC filter. |
| Settling | RTC6715 PLL lock ≈ 20–35 ms after a frequency write. This dominates the sweep time (§2.1) and is the main difference from the A5133 (µs-class channel switching). |
| Video output | Not used; terminate per module datasheet, do not route. |
| Antenna | u.FL to a 5.8 GHz antenna (RHCP/LHCP not required for RSSI; a linear 5.8 GHz whip is acceptable). Keep the module's own antenna pad unused or matched to the u.FL. |
| Power | RX5808 ≈ 180–200 mA at 3.3 V (check the specific module; some need 3.3–5 V). ESP32-S3 ≈ 60 mA. Module total ≈ 250 mA average — at the slot budget limit; the designer must confirm the base 3V3 rail and ferrite (FB10/FB11: 120 Ω @ 100 MHz, check its DC rating ≥ 500 mA) can supply it, or fit a local 5 V-less arrangement (there is no 5 V on the slot). If the rail cannot, use the AUX slot for this module and note the constraint. |
| Shield | The RX5808 module is shielded; add a ground fence around the ADC/RSSI trace. |

## 2. Firmware requirements

### 2.1 Scan plan (defaults, configurable via CFG)

* Default plan: 5725–5899 MHz, 1 MHz steps, 175 channels (Tsukorok-compatible). Extended plan:
  5645–5945 MHz (covers all FPV race bands A/B/E/F/R).
* Per channel: write synthesizer, wait for lock (measured, default 30 ms), read RSSI as the mean of
  16 ADC samples over 2 ms. Sweep time ≈ 175 × 32 ms ≈ 5.6 s for the default plan, ≈ 10 s extended.
  This is a hardware property; the spec for class C is therefore **one sweep per 6 s** (default plan).
* Adaptive mode: after a full sweep, re-visit only channels above the gate every 1 s (track set of up
  to 16 channels), full sweep every 6 s.
* RSSI gate per CFG (default: floor + 10 dB, floor measured at boot with the antenna port terminated by
  the module itself — the module has no internal termination, so the boot floor is the quietest channel
  of the first sweep).

### 2.2 Detection logic on the module

* Candidate rules ported from the Tsukorok 5.8 GHz spectral algorithm (extraction brief §2.3):
  thresholds from −65 dBm down to −99 dBm in 5 dB steps, segments with gap tolerance 5 channels, width
  16–69 MHz, edges stable within 5 MHz across adjacent thresholds, two consecutive positive sweeps.
  Output: class E CANDIDATE with centre, width, edge-stability score.
* 16-channel window rule (≥ 8 of 16 above gate, fewer than half of all channels above) as a second
  candidate producer.
* ALARM only when a candidate persists ≥ 3 sweeps (≈ 18 s) and is not on a channel that the MAIN S3 has
  marked whitelisted (5 GHz Wi‑Fi channels 149–165 fall inside the band; the server whitelist handles
  them, the module only flags).
* No time-domain burst classification on this module (the RSSI path is too slow for it).

### 2.3 Data produced

Classes A, C (175- or 300-point sweep, i8 dBm, every 6 s), D (per-MHz occupancy every 60 s), E, F
(RSSI ADC reference voltage, PLL lock time statistics). No class B (no packets exist on this receiver).
Class G over USB: continuous RSSI ADC stream on one channel (up to 10 kS/s) for burst-timing work on
the host.

## 3. Module-specific acceptance tests

1. Tuning: every channel of the extended plan locks; lock time ≤ 35 ms measured on the RSSI settling.
2. RSSI curve: monotonic from −95 to −40 dBm on a 5800 MHz CW within ±3 dB after calibration (store
   the two-point calibration in NVS and report it in HELLO).
3. Sweep time ≤ 6.5 s default plan, ≤ 11 s extended plan.
4. Supply current ≤ 250 mA average at 3.3 V; boot-time inrush ≤ 500 mA / 10 ms.
5. A 20 MHz 5.8 GHz Wi‑Fi channel at −50 dBm is reported as CANDIDATE (steep-edge rule), never as ALARM
   with default settings.
6. No emission (common test 6): the RTC6715 LO leakage at the antenna port must be below −57 dBm
   (receiver spurious-emission limit).
