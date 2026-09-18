# Tsukorok Drone Detector — Device Investigation Brief

**Project:** AERIX RF
**Date:** 2026-09-18
**Evidence basis:** direct interaction with one physical unit + light public-infrastructure recon
**Scope:** passive analysis of an operator-owned device; no exploitation of vendor systems

---

## 1. Executive summary

The "Tsukorok" (Цукорок, internal name `cukorok`) is a Ukrainian handheld passive
drone detector by Drone Spices Ltd. A physical unit was connected over USB and
characterised without opening the case or modifying firmware.

We fully recovered the device's **command interface, live RF detection
configuration, detection model, and over-the-air (OTA) update architecture.**
We did **not** obtain the firmware binary: the OTA transfer is protected by TLS
and could not be extracted by passive capture. Whether it can be extracted by
active TLS interception is **untested and unresolved** (see §7).

The recovered RF parameters are directly useful to AERIX RF: they show which
sub-GHz drone-telemetry links a fielded detector keys on, and at what rates.

---

## 2. Device identification

| Property | Value |
|---|---|
| Product | Tsukorok / Цукорок ("Vanilla Sugar") drone detector |
| Vendor | Drone Spices Ltd (UA / London) |
| USB ID | `303a:1001` (Espressif ESP32-S3, USB-Serial-JTAG) |
| Internal name | `cukorok` |
| HW revision | tsukorok-S3-V4 |
| Firmware | 5.5.6 |
| Device id | 2008937968 |
| MAC / serial | F0:F5:BD:77:18:70 |
| Radio (inferred) | SX1280 (2.4 GHz, FLRC) + SX126x (sub-GHz, LoRa/GFSK) |
| Sensitivity | −132 dBm (vendor spec) |
| Bands (vendor) | 720–1020 MHz, 2.4–2.5 GHz |

The FLRC modulation support and −132 dBm sensitivity are the fingerprints that
point to a Semtech SX1280 + SX126x radio pair rather than a wideband SDR.

---

## 3. Method

1. **USB console** — the device exposes a text command console over its CDC-ACM
   port (115200 8N1). A vendor manual (Tsukorok 2.0) documents the command set;
   additional 5.5.6 commands were found by safe prefix/word probing.
2. **OTA capture** — the host laptop was turned into the Wi-Fi access point the
   device looks for (`drone_spices` / `87654321`), with a wildcard DNS and
   passive packet capture, no route to the internet ("log-only"). The device was
   driven to attempt an update via the USB console, and its network behaviour was
   recorded.

No firmware was flashed and no persistent device setting was intentionally
changed. (One probe transiently cleared the scan ranges; it was detected by
before/after diff and immediately restored — see §9.)

---

## 4. Console command set

Documented (manual) + observed (5.5.6):

| Command | Effect | Class |
|---|---|---|
| `status` / `device` | version, id, heap | read |
| `settings` | full live config dump | read |
| `freq ranges read` | current scan windows | read |
| `lora read` | LoRa spreading factors | read |
| `alarm read` | alarm timing config | read |
| `preamble` | preamble size | read |
| `wifi client scan` | list APs | read |
| `log view` | detection history | read |
| `wifi client connect <ssid> <pw>` | join Wi-Fi | action |
| `wifi client disconnect` | leave Wi-Fi | action |
| `update` | OTA firmware update | action |
| `upload captures` | send stored signatures to vendor | action |
| `freq ranges <a-b> <c-d> <e-f>` | set scan windows | **mutating** |
| `rssi threshold <x>` | set alarm sensitivity | **mutating** |
| `lora` / `fsk` / `alarm` | set SF / bitrate / alarm banks | **mutating** |
| `tracking <enable\|disable>` | Orlan tracking mode | **mutating** |
| `mode <sleep\|rssi\|normal>` | operating mode | **mutating** |
| `reset settings` | factory defaults | **destructive** |
| `restart` | reboot | action |

Console matching is **prefix-based and case-insensitive** — a single leading
character selects a whole command — which is why blind single-letter enumeration
is unsafe on this device.

---

## 5. Live RF detection configuration (read off the unit)

```
current_mode   = normal (3)
rssi_threshold = 94
tracking       = 0 (off)
preamble_size  = 16
freq_ranges    = 860–885 MHz | 895–928 MHz | 970–1020 MHz
bitrates       = [57600, 80000, 15235, 0]     (G)FSK symbol rates
spreading_factors = [9, 8, 0, 0]              LoRa SFs
alarm timings  = fsk[500,2500,1] lora[400,1000,1] rssi[500,2700,1] tracking[300,750,1]
```

**Interpretation (strong inference, not vendor-confirmed):** the detector is a
**packet-radio demodulator bank**, not a spectral/energy classifier. It parks
GFSK and LoRa receivers on specific, measured drone telemetry/control-link
parameters across three sub-GHz windows and raises an alarm on RSSI above
threshold. The oddly specific bitrates — especially `15235` bps — are measured
signatures of particular drone links, functionally a target list. The
`upload captures` command ships accumulated signatures back to the vendor,
implying a crowd-sourced signature database.

---

## 6. OTA update architecture (packet-captured)

Update sequence, confirmed by capture:

1. **Time gate first.** The device resolves `pool.ntp.org` and `time.nist.gov`
   and performs SNTP (`:123`). Without a valid clock it aborts before any
   firmware request (TLS cert validity needs correct time).
2. **HTTPS to `dev.drone-spices.com:443`.** After time sync it resolves that
   host and opens TLS; the ClientHello SNI = `dev.drone-spices.com`.
3. The firmware GET and transfer occur **inside** TLS.

Notable: the unit updates from a **`dev` / staging** channel.

Backend hosts (from the single Let's Encrypt certificate's SAN list):

| Host | Role |
|---|---|
| `dev.drone-spices.com` | OTA endpoint + Ukrainian staging site |
| `terminal.drone-spices.com` | browser Web-Serial console (same command interface) |
| `landing.drone-spices.com` | product landing page |
| `tsukorok.drone-spices.com` | public product page |

Support/updates channel: `t.me/drone_spices_bot`.

---

## 7. Can the firmware be extracted from the traffic?

**Passive capture (mirroring / Wireshark): No.** The transfer is inside TLS with
ephemeral-key (ECDHE / forward-secrecy) session keys. Captured traffic is
ciphertext and cannot be decrypted even with the server's private key.

**Active TLS interception (mitmproxy): Unresolved — worth one test.** Terminating
the TLS with our own certificate would expose the plaintext OTA URL and firmware,
*if* the device does not validate the certificate chain. This was **not** tested:
the log-only endpoint never presented a certificate (it closed the socket after
the ClientHello), so the device's abort proves only that it needs a real TLS
responder — **not** that it validates the signer. Many ESP OTA builds, especially
dev channels, skip validation. A single controlled test (self-signed cert on an
intercepting proxy that relays to the real server) resolves this:

- device completes handshake → not validating → firmware recoverable in cleartext;
- device rejects → validating/pinned → only the hardware route remains.

---

## 8. Routes to the firmware binary — status

| Route | Status |
|---|---|
| Passive traffic capture | ✗ ruled out (TLS forward secrecy) |
| Active TLS intercept (mitmproxy) | ? untested — recommended next experiment |
| Public OTA path on server | ✗ not publicly served; not blindly enumerated (vendor dev server) |
| Web flasher (`serial.html`/`terminal`) | ✗ Web-Serial console only, no firmware fetch |
| Hardware flash dump (BOOT→GPIO0) | ? 6 attempts booted the app; verify pad = GPIO0, else likely `DIS_DOWNLOAD_MODE` fused |
| Ask vendor (`t.me/drone_spices_bot`) | ↺ clean legitimate route to an official image |

---

## 9. Relevance to AERIX RF

- The sub-GHz windows (`860–885 / 895–928 / 970–1020 MHz`), GFSK bitrates
  (`57600 / 80000 / 15235`) and LoRa SFs (`9 / 8`) are concrete, reusable
  parameters for our own **passive** detection of the same drone-telemetry link
  classes.
- The architecture is a useful contrast to AERIX RF's wideband ANTSDR/HackRF
  approach: a cheap fixed-parameter demod bank vs. wideband capture + analysis.
- Evidence discipline: these parameters are RF-candidate / protocol-morphology
  level, not validated decodes. They indicate *what a commercial detector keys
  on*, not confirmed drone identities.

---

## 10. Safety / integrity notes

- Operator-owned device; passive analysis only. No transmit, jamming, spoofing,
  or takeover.
- No exploitation of vendor infrastructure; public-facing recon was minimal and
  stopped short of enumeration.
- One transient config change (scan ranges) was made accidentally by a probe and
  fully restored; verified by before/after diff.
- `current_mode` read 3 then 2 across power cycles; left as-is (device-managed
  runtime state), not rewritten.
