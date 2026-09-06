# Landscape: state of the art in RF drone detection, classification and decoding

What follows is the state of the art organised by what an **ANTSDR E200** can actually do with each
signal family, written for an RF engineer who did not sit through the research sweep. Every number,
frequency, licence and model name below carries the source it came from. Where the evidence is
snippet-only, contradictory or unverified, the text says so instead of smoothing it over.

Conventions used throughout:

* **verified** means an agent cloned the repository or fetched the page and read it; **snippet**
  means only a search-engine snippet was reachable from the sandbox. The bibliography at
  [sources.md](sources.md) carries the flag per source.
* Eight design-critical claims went through an adversarial verification pass. They are cited as
  *(verified: verdict N, ...)* where N is the position in `verdicts.json`, mirrored in
  [verification-log.md](verification-log.md).
* Two further claims were queued for that pass but the agent budget ran out, so they are labelled
  **unverified round-1** wherever they are used: the E200 O4 firmware channel set
  (`o4-firmware-channels`) and the OcuSync PHY summary (`ocusync-phy`).
* Hardware numbers are only summarised here; the full treatment is in
  [hardware-e200.md](hardware-e200.md). Waveform parameter tables live in
  [signal-reference.md](signal-reference.md), datasets in [datasets.md](datasets.md), legal limits in
  [regulatory.md](regulatory.md), and the Chinese/Russian/Ukrainian view in
  [foreign-perspective.md](foreign-perspective.md).

The three E200 constraints that shape everything below, in one paragraph: the AD9361 front end
covers 70 MHz to 6 GHz with up to 56 MHz analog bandwidth, but the host link is a single 1 GbE port
with a 1500-byte MTU, which caps continuous single-channel sc16 streaming at about 29.6 MSPS by
arithmetic and at the vendor's stated **20 MSPS** in practice, with roughly 10 MSPS per channel in
two-channel mode *(verified: verdict 2, host streaming tiers,
[vendor table](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md))*.
Snapshot capture at up to 61.44 MSPS is possible on both firmware personalities because the DMA
lands in DDR first; sustained streaming at that rate is not *(verified: verdict 2)*. The board has
one SMA RX/TX pair and a second pair on internal u.FL, both fed by one AD9361 and therefore sharing
one RX LO *(verified: verdict 1, `rf-ports`)*.

---

## 1. DJI DroneID and OcuSync 2/3/4

### 1.1 The DroneID burst: what is agreed

DroneID is a short LTE-flavoured OFDM broadcast that a DJI aircraft emits alongside its OcuSync
control/video link. The parameters below are agreed independently by
[proto17/dji_droneid](https://github.com/proto17/dji_droneid) (MATLAB/Octave/C++, MIT) and
[RUB-SysSec/DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity) (Python, AGPL-3.0), both read
in full.

| Parameter | Value | Source |
|---|---|---|
| Subcarrier spacing | 15 kHz | [proto17](https://github.com/proto17/dji_droneid), [DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity) |
| Active carriers | 600 data + null DC (601-length ZC with DC element removed) | [proto17](https://github.com/proto17/dji_droneid) |
| Occupied bandwidth | ~9 MHz ("10 MHz" nominal, 15.36 MHz including guards) | [proto17](https://github.com/proto17/dji_droneid) |
| Valid sample rates | any Fs with Fs/15e3 a power of two: 15.36 (FFT 1024), 30.72 (2048), 61.44 MSPS (4096) | [proto17](https://github.com/proto17/dji_droneid), [samples2djidroneid](https://github.com/anarkiwi/samples2djidroneid) |
| Symbols per burst | 9 (8 on Mavic Pro / Mavic 2, symbol 1 skipped) | [proto17](https://github.com/proto17/dji_droneid) |
| Cyclic prefix schedule | long, short x7, long: [80,72,72,72,72,72,72,72,80] at 15.36 MSPS | [DroneSecurity helpers.py](https://github.com/RUB-SysSec/DroneSecurity) |
| Zadoff-Chu pilots | symbols 4 and 6 (1-based), roots 600 and 147 | [proto17](https://github.com/proto17/dji_droneid) |
| Data modulation | QPSK, no pilots | [proto17](https://github.com/proto17/dji_droneid) |
| Scrambler | LTE Gold sequence (36.211 §7.2, Nc=1600), x2 init 0x12345678 bit-reversed | [proto17](https://github.com/proto17/dji_droneid) |
| FEC | LTE rate de-matching D=1412, E=7200, rv=0, then turbo decode, CRC-24 LTE-A over 176 bytes | [proto17 cpp/remove_turbo.cc](https://github.com/proto17/dji_droneid) |
| Payload | 91-byte frame, DJI CRC-16 (poly 0x11021, init 0x3692, reflected) | [proto17](https://github.com/proto17/dji_droneid), [DroneSecurity droneid_packet.py](https://github.com/RUB-SysSec/DroneSecurity) |
| Burst length | 9880 samples = 643.2 us at 15.36 MSPS (legacy 8-symbol: 8784 samples = 571.9 us) | [DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity) |
| Repetition | about every 600 ms | [proto17](https://github.com/proto17/dji_droneid) |
| Payload contents | serial, drone lat/lon, height, altitude, v_n/v_e/v_up, yaw, pilot (phone) lat/lon, home lat/lon, product type, 19-byte UUID | [proto17 create_frame_bytes.m](https://github.com/proto17/dji_droneid) |

Two practical warnings from the code read. First, the payload field order is **not** agreed between
implementations: DroneSecurity reads altitude then height and divides by 3.281 as feet, while
proto17 and samples2djidroneid read height then altitude as raw int16, and samples2djidroneid orders
`home_latitude` before `home_longitude` where the other two order longitude first
([deep read of DroneSecurity + proto17](https://github.com/RUB-SysSec/DroneSecurity)). Any toolkit
decoder has to be validated against a drone at a known position. Second, DroneSecurity's decode path
has **no FEC at all**: it keeps only the systematic bits and brute-forces the four QPSK rotations, so
2 of 9 frames fail CRC even on the repo's own clean `mini2_sm` capture
([DroneSecurity Packet.py](https://github.com/RUB-SysSec/DroneSecurity)). proto17's ZC equaliser plus
real turbo decode is the version with range.

Detection windows used by DroneSecurity's packetiser are a useful, verified gating table: DroneID
630-665 us at 8-11 MHz occupied width, legacy DroneID 565-600 us, OcuSync C2 500-520 us,
beacon/pairing 490-540 us, video 630-665 us at roughly 20 MHz
([DroneSecurity packetizer.py](https://github.com/RUB-SysSec/DroneSecurity)).

### 1.2 Which generations are decodable, and which are encrypted

This is the single most consequential finding for the project, and the round-1 version of it was
wrong in an important way. The corrected statement *(verified: verdict 4, DJI generation coverage)*:

* Open decoders are demonstrated only on **OcuSync-2-era** aircraft: DJI Mini 2 and Mavic Air 2
  ([DroneSecurity README](https://github.com/RUB-SysSec/DroneSecurity/blob/public_squash/README.md)),
  Mini 2 only for proto17
  ([proto17 Test.md](https://github.com/proto17/dji_droneid/blob/main/Test.md)), and
  "currently only Occusync 2.0 is decoded" for
  [samples2djidroneid](https://github.com/anarkiwi/samples2djidroneid).
* Even inside OcuSync 2 there are holes: the Mavic 2 Pro is detected (ZC roots 600/147 found) but
  "existing decoders don't support Mavic 2 parameters"
  ([DroneSecurity #49](https://github.com/RUB-SysSec/DroneSecurity/issues/49), June 2026).
* **OcuSync 3 is not encrypted, but no public code decodes it.** proto17's Mavic 3 analysis stopped
  at ZC identification (roots 600 and 385, each twice, 6 data symbols)
  ([proto17 wiki](https://github.com/proto17/dji_droneid/wiki/DJI-Mavic-3-DroneID-Analysis)), and
  every O3 issue is open or closed unresolved:
  [#51](https://github.com/proto17/dji_droneid/issues/51),
  [#58](https://github.com/proto17/dji_droneid/issues/58) (10 symbols, four ZC, 7200 bits),
  [#43](https://github.com/proto17/dji_droneid/issues/43),
  [DroneSecurity #46](https://github.com/RUB-SysSec/DroneSecurity/issues/46) (Mavic 3 Classic: "decoding
  fails at the next step").
* The **encryption boundary is O4**, not "O3 Pro". O3+/O3 Pro aircraft (Mavic 3 family, Inspire 3)
  sit on the unencrypted side; O4 begins with the Air 3 (2023) and covers Mini 4 Pro, Avata 2, Neo,
  Air 3S, Flip, Mavic 4 Pro, Mini 5 Pro and Avata 360 *(verified: verdict 4)*.
* On O4 the burst still demodulates cleanly. proto17 [#50](https://github.com/proto17/dji_droneid/issues/50)
  (May 2024) reports a clean QPSK constellation but an encrypted payload;
  [#65](https://github.com/proto17/dji_droneid/issues/65) (Avata 360, O4+) reports 9 MHz, 10 symbols
  arranged "qpsk x3 + zc x2 + zc x2 + qpsk x3" with the **ZC root index changing between frames**;
  [DroneSecurity #50](https://github.com/RUB-SysSec/DroneSecurity/issues/50) reports a recurring
  ~500 us burst with four ZC sequences on an Air 3S, constant across 10/20/40 MHz settings.
* O4 payloads are recoverable only through a **paid cloud service**. The MicroPhase O4 firmware
  binary contains an online decrypt call `/api/o4online/decrypt?hex=` with
  `Authorization`/`auth_secret`/`token_secret`, and
  [dragonscope.py](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/dragonscope.py)
  forwards the encrypted hex to a licensed remote endpoint that returns `sn`/`lat`/`lon`
  *(verified: verdict 4)*. [proto17 #63](https://github.com/proto17/dji_droneid/issues/63)
  ("does anyone have the O4 decryption key... looking to purchase it") is unanswered.
* Coverage holes that are not O2/O3/O4 at all: LightBridge / OcuSync 1 aircraft such as the
  Phantom 4 Pro V2 produce a 14-symbol, two-sync-symbol signal that DroneSecurity cannot decode but
  an ANTSDR reportedly can
  ([DroneSecurity #43](https://github.com/RUB-SysSec/DroneSecurity/issues/43)); Wi-Fi-link DJI drones
  put DroneID in an 802.11 vendor IE (OUI 26:37:12) instead, parsed by
  [Kismet](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h),
  not by any OFDM decoder.

One widely repeated operational claim is **contested**: "DJI drones only broadcast DroneID when
motors are spinning" appears only in
[alphafox02's README](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/README.md) and the
[WarDragon capability doc](https://github.com/alphafox02/WarDragon/blob/main/docs/software/detection-capabilities.md).
It is contradicted for O2-era firmware by proto17's own recording instructions ("Power on the drone
(shouldn't need the controller to be on)",
[proto17 wiki](https://github.com/proto17/dji_droneid/wiki/Using-the-MATLAB-Code)), by DroneSecurity's
`mini2_sm` capture taken before GPS lock, and by the protocol itself carrying separate `motor_on` and
`in_air` state bits ([Kismet IE parser](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h))
*(verified: verdict 4)*. Treat the start condition as unknown per model and measure it.

### 1.3 Open decoders: maturity, licence, what they cost to run

| Project | Language / licence | Input | Status | Notes |
|---|---|---|---|---|
| [proto17/dji_droneid](https://github.com/proto17/dji_droneid) | MATLAB/Octave + C++, MIT | float32 IQ at 15.36/30.72/61.44 MSPS | last commit 2024-05-27 | Only complete chain incl. turbo decode (needs ttsou/turbofec, CRCpp; licences unverified). Also has a **transmit** chain usable to synthesise test bursts |
| [proto17 gr310 branch](https://github.com/proto17/dji_droneid) | GNU Radio 3.10 OOT, GPL-3.0-or-later headers, no LICENSE file | stream | 2022-09-22, author calls it weak | Only detector/burst-extractor blocks; poor STO/CFO/equalisation by its own README |
| [RUB-SysSec/DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity) | Python, AGPL-3.0 | file, or live via USRP B205-mini at 50 MSPS | 2023-03-10, "no new features planned" | Does not run on modern numpy (`np.complex` at qpsk.py:46) or Python 3.12 (`distutils`); live mode writes 520 MB per 1.3 s dwell to disk; users report it "only hops and finds nothing" ([#41](https://github.com/RUB-SysSec/DroneSecurity/issues/41)) |
| [anarkiwi/samples2djidroneid](https://github.com/anarkiwi/samples2djidroneid) | Docker wrapper, Apache-2.0 | complex float32 at 15.36e6 or 30.72e6 only | 2026-06-20 | Runs proto17 under Octave; O2 only |
| [luyii-code-1/dji-ocusync-droneid-research](https://github.com/luyii-code-1/dji-ocusync-droneid-research) | Python, HackRF | int8 IQ at 20 MSPS resampled x96/125 to 15.36 MSPS | verified 2026-08-27 | O2 decoder plus an O4 packet tool; reports O4 uses SM2 for key packets and AES-128-CTR for telemetry packets, validated on Mini 5 Pro only |

There is therefore **no maintained open-source real-time host decoder**. The AGPL on DroneSecurity
also means it cannot be vendored into a permissively licensed toolkit; only proto17 (MIT) and
samples2djidroneid (Apache-2.0) can be reused with attribution
([deep read licences](https://github.com/RUB-SysSec/DroneSecurity)), which is the basis of
[ADR-0003](../docs/decisions/ADR-0003-third-party-code-and-licences.md).

A Chinese CSDN series by `leegang12` claims CRC-correct DroneID decoding across O1 to O4 with soft
turbo decoding (+3 dB over hard decisions) and a ~5 dB demodulation threshold
([post 292](https://blog.csdn.net/leegang12/article/details/149397403)), but CSDN is blocked from the
sandbox, no code repository was found, and the claim is snippet-level only. See
[foreign-perspective.md](foreign-perspective.md).

### 1.4 The closed E200 DroneID firmware and what it emits

The only thing that decodes OcuSync 3 today is MicroPhase's **closed-source ARM binary**,
redistributed as SD-card images in
[alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid): `done_dji_release`
(2024-03-06) and `drone_dji_rid_decode` (build 2026-01-14). The binaries link only libiio and
libfftw3f and contain LTE turbo/rate-matching plus ZC600/ZC147 correlator symbols; no source exists
on MicroPhase's GitHub *(verified: verdict 4)*. The image is a modified Pluto-firmware build, not
UHD (`uEnv.txt` shows the stock `mode=1r1t, maxcpus=1` Pluto environment)
([alphafox02 image contents](https://github.com/alphafox02/antsdr_dji_droneid)).

Outputs, both verified:

* **Legacy** firmware: TCP server on port 41030 emitting little-endian binary frames
  `{uint16 header; uint8 type; uint16 len}` then `char serial[64]; char device_type[64]; uint8;
  double app_lat, app_lon, drone_lat, drone_lon, height, altitude, home_lat, home_lon, freq,
  speed_e, speed_n, speed_u; uint32 rssi`, which is exactly what Kismet's
  [capture_antsdr_droneid.c](https://github.com/kismetwireless/kismet/blob/master/capture_antsdr_droneid/capture_antsdr_droneid.c)
  parses (source definition `antsdr-droneid:host=<ip>,port=<port>`; added in
  [Kismet 2025-09-R1](https://www.kismetwireless.net/posts/kismet-2025-09-r1/), snippet).
* **New** firmware: the board connects *outward* to `tcp_serverip:52002` and pushes CSV lines
  `dji_O,<2/3|4>,freq,rssi,model(code)|dji(hash),serial,lon,lat,pilot_lon,pilot_lat,home_lon,home_lat,alt|height,vE|vN|vU,...;`
  which [dji_receiver.py](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/dji_receiver.py)
  maps to Open-Drone-ID-shaped JSON (Basic ID / Location-Vector / Self-ID / System / Frequency
  Message) on ZMQ port 4221 ([alphafox02](https://github.com/alphafox02/antsdr_dji_droneid)).
* Configuration is by U-Boot environment over serial: `tcp_serverip`, `tcp_serverport 52002`,
  `gain_mode fast_attack`, `heart_beate_time 30`, `device_mode auto`, plus `api_host`,
  `auth_secret`, `token_secret`, `device_serial` for the O4 online decrypt path
  ([alphafox02](https://github.com/alphafox02/antsdr_dji_droneid)).
* Capability split, from the vendor-adjacent
  [WarDragon doc](https://github.com/alphafox02/WarDragon/blob/main/docs/software/detection-capabilities.md):
  O2 and standard O3 give full telemetry; O3 Pro / O4+ give hash only by default, with full
  telemetry requiring a DragonScope subscription and internet connectivity.

An **unverified round-1** finding (queued as `o4-firmware-channels`, never adversarially checked)
holds that the O4 firmware in `device_mode auto` monitors only 2434.5, 5756.5, 5776.5 and
5816.5 MHz, runs the AD9361 single-channel with a 61.44 MSPS path clock, and that the legacy firmware
uses an FPGA correlator at `/dev/my-axi-droneid-filter0`
([alphafox02 image strings](https://github.com/alphafox02/antsdr_dji_droneid)). If true it means
2.4 GHz coverage of the DroneID hop set is incomplete out of the box; it must be re-checked on the
device before any coverage claim is made.

Known DroneID centre frequencies, as an observational union rather than a documented plan:
DroneSecurity's live receiver hops 16 frequencies (2414.5, 2429.502441, 2434.5, 2444.5, 2459.5,
2474.5, 5721.5, 5731.5, 5741.5, 5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5 MHz) with a
1.3 s dwell at 50 MSPS ([DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity)); the union with
proto17's list spans 2399.5-2474.5 MHz and 5721.5-5831.5 MHz. luyii uses a 15 MHz raster
(2399.5/2414.5/2429.5/2444.5/2459.5 MHz), explicitly described as "experimental scan centers rather
than universal official frequencies"
([luyii](https://github.com/luyii-code-1/dji-ocusync-droneid-research)). The exact hop sequence and
dwell are not documented anywhere open; see [Gaps](#gaps).

### 1.5 Non-DroneID OcuSync traffic: fingerprints, not payloads

The OcuSync video and C2 links themselves are not decodable by anything open, but they have a strong
structural fingerprint. The following is an **unverified round-1** summary (`ocusync-phy`), assembled
from sources whose individual confidence flags are given:

* OcuSync 2 downlink (verified, [tmbinc's notes](https://github.com/tmbinc/random/tree/master/dji/ocusync2)):
  20/10/3/1.4 MHz modes; 20 MHz mode uses 1201 subcarriers at 15 kHz (~18 MHz occupied); frame
  layout `RS0 | D x6 | RS1 | D x6 | RS0` of about 1 ms; CP 144 samples (20 MHz) or 72 (10 MHz) with
  extended CP (+16/+8) on the first, middle and last symbols; reference symbols are LTE-like
  Zadoff-Chu; uplink is frequency-hopping.
* O4 main link on a DJI Mini 5 Pro (verified repo, single measurement,
  [luyii](https://github.com/luyii-code-1/dji-ocusync-droneid-research)): 99% bandwidth
  8.921-8.926 MHz spanning about 2403.071-2411.992 MHz, with 5 ms periodicity (0-3.27 ms strong
  activity, 3.27-4.47 ms gap, 4.47-5.00 ms activity). The same repo warns that **5 ms periodicity
  alone cannot separate video, C2, Wi-Fi/BLE Remote ID and DroneID**.
* Cyclic-prefix autocorrelation separates OcuSync from Wi-Fi because Wi-Fi's 312.5 kHz spacing puts
  its cyclic feature near 250 kHz while OcuSync sits at 10.5-14.5 kHz (15 kHz numerology) or
  22-30 kHz (30 kHz numerology). This is implemented and measured in
  [RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker), which consistently
  observes alpha = 27.99 kHz, but only against a PlutoSDR replaying RFUAV recordings, never a live
  aircraft.

Nothing above should be treated as settled DJI documentation. The RF-Vision deep read flags that its
own README explanation of the 27.99 kHz peak ("CP=1/4 at 35 kHz spacing") is arithmetically
inconsistent with its `tau = 1333` (30 kHz spacing); a 96-sample CP at 30 kHz spacing is the
arithmetic that fits ([deep read](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)).

### 1.6 On-board versus host processing

Both are demonstrated, and they answer different questions. Running the closed firmware puts the
whole decode on the Zynq ARM and ships only decoded records over Ethernet, which sidesteps the 1 GbE
IQ budget completely ([alphafox02](https://github.com/alphafox02/antsdr_dji_droneid)) but monopolises
the board: the DroneID image is a full alternative Linux personality shipped as SD-card zips
([alphafox02](https://github.com/alphafox02/antsdr_dji_droneid)), and only one personality can boot
at a time because the stock IIO firmware lives in QSPI while UHD and the SD images are selected by
the BOOT DIP switch *(verified: verdict 6, personality exclusivity;
[unpacking guide](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md))*. Host
processing at 15.36 MSPS is comfortably inside the 20 MSPS Ethernet budget and covers exactly one
DroneID channel per tune; note that **20 MSPS itself is not a valid DroneID rate** because
20e6/15e3 = 1333.3 is not an integer, so the AD9361 must be set to 15.36 MSPS or the stream
resampled ([deep read of DroneSecurity/proto17](https://github.com/proto17/dji_droneid)). This split
is what [ADR-0005](../docs/decisions/ADR-0005-processing-location.md) and
[ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md) formalise.

---

## 2. Wi-Fi based drones and Remote ID

### 2.1 Remote ID transports and what they require

Under ASD-STAN DRI the mandatory-one-of transports are Bluetooth 5 Long Range (Coded PHY plus
extended advertising), Wi-Fi NAN and Wi-Fi Beacon on 2.4 or 5 GHz; Bluetooth 4 legacy advertising is
optional ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)). The on-air
identifiers are the beacon/NAN vendor IE with OUI `FA:0B:BC` type `0x0D`, the NAN service OUI
`50:6F:9A` type `0x13`, and the BLE service-data UUID `0xFFFA` with app code `0x0D`, carrying 25-byte
messages packed up to 9, with Location at 1 Hz
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c),
[wireshark-dissector](https://github.com/opendroneid/wireshark-dissector)).

DJI implements **Wi-Fi Beacon only**: no DJI model is documented on BLE or NAN. This is verified for
Mavic 3 and Mini 3 Pro from
[opendroneid's transmitter-devices.md](https://github.com/opendroneid/receiver-android/blob/master/transmitter-devices.md),
for the Air 2S from [receiver-android #93](https://github.com/opendroneid/receiver-android/issues/93)
("added RID support through WiFi Beacon") and for the Mavic 3 Enterprise from
[#99](https://github.com/opendroneid/receiver-android/issues/99) ("Transport type: Beacon (Wi-Fi)");
newer models rest on forum snippets *(verified: verdict 7, `dji-eu-rid`)*. Which band and channel DJI
uses (2.4 GHz ch 6 versus 5 GHz ch 149) is **not established**. A BLE-only or iOS-based receiver will
see no DJI aircraft at all, because iOS up to 15 cannot receive BT5 Long Range, Wi-Fi NAN or Wi-Fi
Beacon ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)).

EU availability is narrower than "model and firmware dependent": DRI is mandated for C1+ class marks
and specific-category operations, so C0 sub-250 g DJI aircraft (Mini 3, Mini 4 Pro, and by extension
Neo and Flip) are exempt and are reported to broadcast nothing in Europe *(verified: verdict 7)*. The
regulatory detail is in [regulatory.md](regulatory.md). The practical consequence for a Netherlands
observation network is blunt: for the sub-250 g O4 fleet there is neither decodable Remote ID nor
decodable DroneID, so the RF classifier is the only route.

### 2.2 What an SDR can and cannot do here

The honest answer is that **an SDR is the wrong tool for Remote ID**, and the research says so
against the project's initial hypothesis.

`openwifi` does officially support the board: `antsdr_e200` appears in the
[openwifi README board table](https://github.com/open-sdr/openwifi/blob/master/README.md), with
board files under
[kernel_boot/boards/antsdr_e200](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md),
an FPGA design in openwifi-hw, a prebuilt bitstream in openwifi-hw-img, and since August 2026 a
compact Buildroot image stated to have been booted with AP/client plus iperf3 on real E200 hardware
*(verified: verdict 6)*. Monitor mode delivers every received frame including bad-CRC frames to
mac80211 with radiotap `SIGNAL_DBM` and `RX_INCLUDES_FCS`, and packet injection, CSI and IQ capture
(iq_len < 4096 on the Z7020) all work *(verified: verdict 6)*.

But openwifi is **OFDM-only** and cannot demodulate 802.11b DSSS/CCK, and its own README notes this
"is usually the case during beacon transmission"
([openwifi README](https://github.com/open-sdr/openwifi/blob/master/README.md)). Reference Remote ID
transmitters beacon at the 11b lowest basic rate: opendroneid's
[transmitter-linux beacon.conf](https://github.com/opendroneid/transmitter-linux/blob/master/beacon.conf)
uses `hw_mode=g`, `channel=6` with no `basic_rates` override, and the ESP32 modules
([ArduRemoteID WiFi_TX.cpp](https://github.com/ArduPilot/ArduRemoteID/blob/master/RemoteIDModule/WiFi_TX.cpp),
[esp32-crid](https://github.com/luolitao/esp32-crid)) never call `esp_wifi_set_protocol` or
`esp_wifi_config_80211_tx_rate`, so the ESP-IDF default 11B|11G|11N protocol applies. An
openwifi-mode E200 will therefore most likely **miss the mainstream 2.4 GHz Beacon Remote ID**
*(verified: verdict 6)*. Three further blockers: the free FPGA image's Xilinx Viterbi decoder runs
under an evaluation licence and halts after about two hours, needing an FPGA reload; only one 20 MHz
channel can be watched at a time, so ch 6 and ch 149 cannot be covered simultaneously; and Bluetooth
Remote ID is out of reach entirely *(verified: verdict 6)*.

The host-side alternative, [gr-ieee802-11](https://github.com/bastibl/gr-ieee802-11), decodes only
802.11a/g/p legacy OFDM at 5, 10 or 20 MHz sample rates, with no HT/MCS support mentioned anywhere in
its README. It also cannot ACK in time and needs `volk_profile` to keep up
([gr-ieee802-11](https://github.com/bastibl/gr-ieee802-11)). And the three BLE primary advertising
channels (2402/2426/2480 MHz) plus Wi-Fi ch 6 (2437 MHz) span 78 MHz, more than the E200's 56 MHz
analog bandwidth and far more than its ~20 MSPS Ethernet budget, so a single E200 must choose one
window ([regulatory lens](https://github.com/bastibl/gr-ieee802-11),
[openwifi](https://github.com/open-sdr/openwifi)).

No surveyed open SDR tool decodes **BLE 5 Coded PHY**:
[ice9-bluetooth-sniffer](https://github.com/mikeryan/ice9-bluetooth-sniffer) does BR and BLE 1M over
HackRF/bladeRF/USRP with no mention of S=2/S=8, and [BTLE](https://github.com/JiaoXianjun/BTLE) is
1M only. A ~15 EUR CC2652P dongle running [Sniffle](https://github.com/nccgroup/Sniffle) supports
"all BT5 PHY modes (regular 1M, 2M, and coded modes)". The pragmatic architecture is therefore a
commodity monitor-mode Wi-Fi NIC plus a Sniffle dongle beside the E200, which is what
[ADR-0010](../docs/decisions/ADR-0010-band-coverage.md) records.

Remote ID is also **unauthenticated and trivially spoofable** with a monitor-mode adapter or a BLE
HCI dongle ([droneRemoteIDSpoofer](https://github.com/cyber-defence-campus/droneRemoteIDSpoofer)),
and Russian/Ukrainian re-flash guides document DJI firmware commands `aeroscope_off`,
`aeroscope_random`, `aeroscope_z` and `aeroscope_heart` that silence DroneID or broadcast fake
positions, alongside builds with "DRONE ID, OpenDroneId, NFZ" disabled
([techuav registry](https://github.com/techuav/techuav.github.io)) *(verified: verdict 4)*. Any
identity claim needs a corroboration score against an independent RF detection.

### 2.3 Wi-Fi-link drones themselves

Consumer Wi-Fi drones are attributable from unencrypted management frames even though their payload
is WPA2-encrypted. [Kismet's kismet_uav.conf](https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf)
carries SSID-regex plus OUI rules: DJI `60:60:1F` with `^Phantom3_.*`, `^Mavic_.*`, `^DJI-MINI3-Pro-.*`,
`^TELLO.*`, `^Spark-.*`; Parrot `A0:14:3D`/`90:3A:E6` with `^BebopDrone.*`, `^Bebop2.*`,
`^SkyController.*`; 3DR Solo `8A:DC:96` `^SoloLink_.*`; Syma `58:04:54`; plus Attop and Propel toys.
Parrot Anafi, DJI Spark/Mavic Air/Tello, FIMI X8 and Yuneec models are certified as plain 802.11 DTS
devices ([fccid.io/2AG6IANAFI](https://fccid.io/2AG6IANAFI), snippet).

China's mandatory broadcast Remote ID adds two more formats that an ASTM-only parser silently drops:
GB 42590-2023 (effective 2024-06-01) uses the same `FA:0B:BC` / `0x0D` vendor IE but a 3-byte pack
header `[0xF1][25][counter]` and protocol-version nibble `0x1`, and GB 46750-2025 (effective
2026-05-01) uses a variable-length bitmap format starting `0xFF 0x20` with 21 fields and optional
CGCS2000 coordinates ([luolitao/remoteid](https://github.com/luolitao/remoteid),
[XC-RemoteID](https://github.com/luolitao/XC-RemoteID),
[esp32-crid-sim](https://github.com/luolitao/esp32-crid-sim)). The two open implementations disagree
on the GB 46750 timestamp encoding (6-byte Unix milliseconds versus 4-byte seconds since 2019-01-01),
so the standard text is needed before implementing a decoder
([XC-RemoteID](https://github.com/luolitao/XC-RemoteID)).

---

## 3. RC and telemetry links

### 3.1 ExpressLRS: the dominant modern link

ELRS is fully open, which makes it the best-documented RC link and the one with the sharpest
detect-versus-decode boundary. The hop tables are explicit in
[FHSS.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/FHSS/FHSS.cpp): ISM2G4 and
CE_LBT use 80 channels at 1 MHz spacing over 2400.4-2479.4 MHz; FCC915 uses 40 channels at 600 kHz
over 903.5-926.9 MHz; EU868 uses 13 channels at 525 kHz over 863.275-869.575 MHz; AU915 20 channels
over 915.5-926.9 MHz; US433W 20 channels over 423.5-438.0 MHz. The sequence is length 256 truncated
to a multiple of the channel count, with the band-centre sync channel forced at every multiple and
the rest shuffled by a UID-seeded RNG.

The verified mode table, from
[common.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/src/common.cpp) and the
`RFperf` time-on-air table:

| Mode | Modulation | Bandwidth | Packet interval | Time on air | Hop cadence |
|---|---|---|---|---|---|
| 2G4 F1000 (FLRC) | FLRC 0.65 Mb/s, BT 1, CR 1/2, 32-bit sync | 0.6 MHz | 1000 us | 389 us | every 2 packets |
| 2G4 F500/D500/D250 (FLRC) | as above | 0.6 MHz | 1000-2000 us | - | every 2 packets |
| 2G4 500 Hz | LoRa SF5, CR_LI 4/6 | 812.5 kHz (BW_0800) | 2000 us | 1507 us | every 4 |
| 2G4 333 Hz Full | LoRa SF5, CR_LI 4/8 | 812.5 kHz | 3003 us | 2374 us | every 4 |
| 2G4 250 Hz | LoRa SF6 | 812.5 kHz | 4000 us | 3300 us | every 4 |
| 2G4 150 Hz | LoRa SF7 | 812.5 kHz | 6666 us | 5871 us | every 4 |
| 2G4 50 Hz | LoRa SF8 | 812.5 kHz | 20000 us | 10798 us | every 2 |
| 900 200 Hz | LoRa SF6, CR 4/7, preamble 8 | 500 kHz | 5000 us | 4380 us | every 4 |
| 900 100 Hz | LoRa SF7, CR 4/7 | 500 kHz | 10000 us | 8770 us | every 4 |
| 900 50 Hz | LoRa SF8, CR 4/7, preamble 10 | 500 kHz | 20000 us | 18560 us | every 4 |
| 900 25 Hz | LoRa SF9, CR 4/7, preamble 10 | 500 kHz | 40000 us | 29950 us | every 2 |
| 900/2G4 1000 Hz (LR1121) | GFSK 300 kb/s, fdev 100 kHz | 467 kHz | 1000 us | - | - |

**2.4 GHz ELRS is detect-only.** All LoRa rates use SX1280 bandwidth code 0x18 with the long
interleaver (CR_LI 4/6 or 4/8), implicit header, hardware CRC off and IQ inverted whenever UID[5] is
odd, and no public SDR decoder implements the SX1280 PHY at all, let alone the undocumented long
interleaver: [gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr) is tested on RFM95/SX1276/SX1262
with no SX1280 support and its [issue #143](https://github.com/tapparelj/gr-lora_sdr/issues/143)
(SX1280 at SF7/CR 4/5) is unanswered; [rpp0/gr-lora](https://github.com/rpp0/gr-lora) rejects SF<6
and lists only sub-GHz transmitters;
[SDRangel ChirpChat](https://github.com/f4exb/sdrangel/blob/master/plugins/channelrx/demodchirpchat/readme.md)
tops out at 500 kHz bandwidth *(verified: verdict 3, ELRS decodability)*. The FLRC and LR1121 GFSK
rates are not LoRa at all and have no open demodulator either. On top of that, the 80-channel
2.4 GHz hop set spans 79 MHz, wider than the E200's 56 MHz analog bandwidth, so 2.4 GHz ELRS has to
be handled as a swept chirp-and-timing detector rather than a full-band capture *(verified:
verdict 3)*.

**Sub-GHz ELRS is a decode candidate, not a demonstrated decode.** The SX127x parameters (500 kHz,
SF6-SF9, CR 4/7-4/8, implicit header, CRC off, default sync word 0x12, preamble 8-10) are inside
gr-lora_sdr's supported space, but no public project has shown an end-to-end decode against real ELRS
radios: [Diamond-D0gs/GNU_Radio_ExpressLRS](https://github.com/Diamond-D0gs/GNU_Radio_ExpressLRS)
re-implements the ELRS OTA/FHSS/CRC layer but validates only SDR-to-SDR with non-ELRS LoRa parameters
(SF7, BW 125 kHz, CR 4/5) *(verified: verdict 3)*. Two caveats narrow it further: LR1121/LR2021
hardware adds SX126x-style SF5 rates that gr-lora_sdr explicitly does not match, and SF6, the most
used sub-GHz rate, is forced into SX127x compatibility through an undocumented register
([LR1121.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/LR1121Driver/LR1121.cpp))
and needs measurement.

The **crypto situation is favourable**: there is none. Every SYNC packet carries UID4 and UID5 in the
clear, which is exactly the CRC14 (poly 0x2E57, 8-byte OTA4) / CRC16 (poly 0x3D65, 13-byte OTA8)
initialiser, XORed with `~modelId` in UID5's low 6 bits when ModelMatch is on (64 candidates), and
since [PR #3294](https://github.com/ExpressLRS/ExpressLRS/pull/3294) (merged 2025-10-08, V4.0)
non-sync packets XOR the per-packet nonce into the initialiser, so a sniffer must track the nonce
*(verified: verdict 3)*. No binding phrase is needed, and capturing the whole sub-GHz hop band
removes any need to know the FHSS seed. Downlink telemetry is plaintext CRSF and can carry aircraft
GPS *(verified: verdict 3)*.

Finally, an ELRS transmitter **radiates whenever it is powered**, sending sync packets every 3-11 ms
(2.4 GHz) or 600 ms (900 MHz) while hopping when no receiver is linked
([ExpressLRS](https://github.com/ExpressLRS/ExpressLRS), with PlutoSDR spectrograms in the
[GRCon25 slides](https://events.gnuradio.org/event/26/contributions/771/attachments/238/622/GabrielGarcia-FAUCAAI-Grcon25.pdf)).
A pilot's handset is detectable before anything flies.

### 3.2 Other RC links: decodable versus detect-only

| Link | PHY | Hop set / period | Decoder status |
|---|---|---|---|
| TBS Crossfire 150 Hz | FSK, 85.1 kBaud, 42.48 kHz deviation, 260 kHz grid | 150-slot sequence, 6.667 ms slot (23-byte up, 13-byte down), TX ch 0-49, RX 50-99 | Unencrypted, no open SDR decoder; parameters from [g3gg0](https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire/) (snippet, blocked) and [ESP32_CRSFSniffer](https://github.com/g3gg0/ESP32_CRSFSniffer) |
| TBS Crossfire 50 Hz | LoRa on SX1272 | as above | Decodable in principle with SX127x-compatible code once per-mode SF/BW/CR are transcribed ([g3gg0](https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire/), snippet) |
| FrSky D8 | 2-FSK 31 kbps | 47 ch, 9 ms | Fully specified in [Multiprotocol](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module), no SDR decoder |
| FrSky D16 | 70-77 kbps (100 kbps EU-LBT) | 47 ch, 9 ms | as above |
| Futaba S-FHSS | 128 kbps | 30 ch on 1.5 MHz grid, 6.8 ms | as above |
| Graupner HoTT | 250 kbps MSK + FEC | 75 ch, 10 ms | as above |
| Flysky AFHDS-2A | 500 kbps | 16 of 160 x 500 kHz ch, 3.85 ms (AFHDS 1.51 ms) | as above |
| Spektrum DSM2/DSMX | 1 Mb/s GFSK DSSS | 23-ch tables, 11 or 22 ms frames | **Only legacy link with a working open SDR decoder**: [gr-dsmx-rc](https://github.com/lscardoso/gr-dsmx-rc) does SOP/PN correlation, despreading, hop following and MFG-ID identification at 4 MSPS (GNU Radio 3.7 era, needs a port) |
| FrSky R9 (868/915) | LoRa BW 500 kHz, SF6, CR 4/5 | 29 (FLEX) / 43 (FCC) / 19 (EU) ch, ~20 ms | Collides with ELRS 900 in modulation; separable only by hop set and period ([Multiprotocol](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module)) |
| FrSky ACCESS, Futaba FASST, Flysky AFHDS 3 | proprietary | - | No public reverse engineering; detect-only ([oscarliang](https://oscarliang.com/frsky-access-protocol/)) |
| SiK / RFD / Holybro telemetry | GFSK 2-250 kb/s (default 64 kb/s), [ArduPilot/SiK](https://github.com/ArduPilot/SiK) | 10 ch (433/868) to 50 (915), spacing (fmax-fmin)/(N+2), NetID-seeded shuffle, frequency change at the start and end of every TDM window ([SiK](https://github.com/ArduPilot/SiK)) | Plaintext MAVLink unless AES enabled; [sikw00f](https://github.com/nicholasaleks/sikw00f) harvests NetIDs and eavesdrops GPS/attitude, but with a **modified SiK radio**, not an SDR |
| Herelink | LTE numerology, 1.4/10/20 MHz | 2409-2459 MHz (10 MHz mode) / 2412-2462 MHz (20 MHz) | Looks like OcuSync to a width-only classifier; no CP/reference-symbol structure published ([CubePilot docs](https://github.com/CubePilot/cubepilot-docs/blob/master/herelink/herelink-user-guides/wireless-communication.md)) |

### 3.3 Hop-timing fingerprints as the classification primitive

Because most of these links are undecodable, the practical classifier input is the (bandwidth, burst
duration, packet period, hop cadence) tuple. Two independent sources support this. The ELRS timing
table above is exact and derived from firmware constants. The Chinese DroneRFa dataset paper adds
per-model rule features measured from real captures: OcuSync-era DJI hop blocks are 1.1-2.2 MHz wide
with 0.52 ms dwell, LightBridge-era DJI are 1.2 MHz / 2.2 ms with 12 ms hop spacing and a 14 ms video
frame at 68% duty, Avata video is 10 ms at 12% duty, and RC transmitters range from 0.42 MHz
(FrSky X20) to 5.0 MHz (RadioLink AT9S)
([JEIT 10.11999/JEIT230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)). RFUAV formalises
the same idea as five protocol-level "fingerprint" parameters: frequency-hop signal bandwidth, hop
duration, hop duty cycle, hop-pattern period and video-link bandwidth
([RFUAV](https://github.com/kitoweeknd/RFUAV)). All five are cheap enough to compute on the E200's
ARM core and map naturally onto observation metadata.

### 3.4 Custom-band forks break every channel table

Frontline ELRS derivatives ignore regulatory domains entirely. MilELRS 3.50 and Barvinok-5 drive
SX1276 modules over 360-560 and 720-1020 MHz, SX1280 over 2100-2700 MHz, and LR1121 over 150-800 and
1010-2100 MHz, with `CUSTOM_FREQ` selecting arbitrary ~20 MHz sub-bands such as 740-760 or
940-960 MHz ([techuav mirror](https://github.com/techuav/techuav.github.io)). MilELRS also moves
telemetry to a separate frequency to hide the control frequency, and Barvinok-5 disables telemetry
entirely, so the drone-side downlink may be silent and only the ground transmitter's uplink is
detectable ([techuav](https://github.com/techuav/techuav.github.io)). Russian sources date the
control-band drift as 850-925 MHz (2022-23), 750-1060 MHz (late 2023), then 433 MHz and 415-640 MHz
([techuav](https://github.com/techuav/techuav.github.io)). A channel-table-driven detector is
therefore structurally wrong for anything but hobby traffic; the detector must be frequency-agnostic
over 150 MHz to 2.8 GHz. Full treatment in [foreign-perspective.md](foreign-perspective.md).

---

## 4. Video links

### 4.1 Analog 5.8 GHz: the one video family that is fully decodable

Analog FPV is wideband FM of a 1 Vpp composite video signal, and on RTC6705-class VTX (the dominant
chipset) there are two FM audio subcarriers at 6.0 and 6.5 MHz sitting 25-30 dB below the video
carrier; the RTC6705 datasheet specifies **no** main-carrier video deviation
([RichWave RTC6705 datasheet, shipped in OpenVTx](https://github.com/OpenVTx/OpenVTx/blob/master/docs/RTC6705-RichWave.pdf))
*(verified: verdict 5, analog FPV bandwidth)*. The "5 MHz peak deviation" figure that circulates is a
decoder scale constant (`fpvdec --dev` default), not a specification
([5G8atv config.hpp](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder/blob/main/src/config.hpp)).

The corrected picture *(verified: verdict 5)*: a 10 MSPS capture yields a usable NTSC colour picture,
demonstrated on one 25 mW whoop VTX with a HackRF where the author measured under 0.3% of energy
outside +/-4.5 MHz, but it does **not** decode the signal fully. The 6.0/6.5 MHz audio subcarriers
and PAL chroma (4.43 + ~1.1 = 5.5 MHz) exceed Nyquist at 10 MSPS, sync tips sit at the 4.9 MHz filter
edge, and VTX drift of 1-3 MHz at power-up eats the margin without AFC
([5G8atv](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder),
[fpv-sdr](https://github.com/lukeswitz/fpv-sdr)). The claim also contains an internal inconsistency:
a true +/-5 MHz swing would park roughly 7% of line time outside +/-4.5 MHz, so the tested VTX must
have swung less *(verified: verdict 5)*. The community "20-27 MHz" figure is neither pure spacing nor
a worst-case deviation: 19-20 MHz is the A/B/E/F channel spacing (Raceband 37 MHz), and 23-27 MHz is a
Carson-rule estimate with the audio subcarrier or an 8 MHz "video bandwidth" as f_max *(verified:
verdict 5)*.

[lukeswitz/fpv-sdr](https://github.com/lukeswitz/fpv-sdr) is the closest thing to an E200 FPV toolkit
and names the E200 its recommended radio (`--sdr uhd`, reached at 192.168.1.10). Its verified
defaults: detection sweep at 40 MSPS for UHD radios with 4096-bin FFTs and 0.8 usable fraction per
chunk, viewer at 20 MSPS, post-demod video LPF at 2 MHz (so it is luma-only), acceptance gates of
SNR >= 12 dB, in-band(10 MHz) minus shoulder(18 MHz) >= 3 dB, and FM envelope coefficient of
variation <= 0.8 (analog FPV measures 0.3-0.56, Wi-Fi/OFDM 1.2-3.2)
([fpv-sdr deep read](https://github.com/lukeswitz/fpv-sdr)). Two cautions from that deep read: the
40 MSPS sweep rate is above what 1 GbE can stream in sc16, so the E200 almost certainly overflows and
the detector only survives because it reads time-averaged probes; and noise alone has a
Rayleigh-envelope CV around 0.52, so the CV gate cannot reject noise by itself. Its licence is also
contradictory: MIT at the top level, `SPDX-License-Identifier: GPL-3.0` in every Python file, and a
vendored GPLv3 gr-ntsc-rc decoder ([fpv-sdr](https://github.com/lukeswitz/fpv-sdr)).

Channel plans to sweep, all verified from firmware tables: the 40-entry A/B/E/F/R analog plan
5645-5945 MHz plus the L/5.3 band 5362-5621 MHz in 37 MHz steps
([rx5808-pro-diversity channels.cpp](https://github.com/sheaivey/rx5808-pro-diversity/blob/master/src/rx5808-pro-diversity/channels.cpp));
fpv-sdr's DJI band 5660/5695/5735/5770/5805/5839/5878/5914 MHz
([fpv-sdr](https://github.com/lukeswitz/fpv-sdr)); and HDZero's 20 discrete channels R1-R8
(5658-5917), E1 5705, F1/F2/F4 5740/5760/5800 and L1-L8 5362-5621 MHz
([hdzero-vtx common.h](https://github.com/hd-zero/hdzero-vtx/blob/main/src/dm6300.c)). Russian and
Ukrainian sources report analog video far outside that: 460-600, 910-1360, 1405-1680, 2290-2510,
3000-4938 and 4867-6184 MHz, with reports of VTX above 6.2 GHz which the E200 cannot reach at all
([techuav VTX frequency table](https://github.com/techuav/techuav.github.io)). They also report
analog video being inverted or scrambled with paired encoder/decoder boxes, which forces
classification onto the FM spectral signature rather than a decodable picture
([techuav](https://github.com/techuav/techuav.github.io)).

### 4.2 Digital video: detect and classify only

* **HDZero**: the open firmware exposes a Divimath DM5680 baseband with DM6300 (VTX) and DM6302
  (goggle) radio chips and a two-state Wide/Narrow bandwidth mode, but the PHY is closed inside the
  DM5680 and no modulation or occupied-bandwidth figure appears in the code
  ([hdzero-vtx](https://github.com/hd-zero/hdzero-vtx),
  [hdzero-goggle](https://github.com/hd-zero/hdzero-goggle)). A secondary Chinese source describes it
  as OFDM feeding an AD9361 with sub-1 ms latency ([kechuang](https://www.kechuang.org/t/89181),
  snippet), which the firmware code does not support; treat the AD9361 claim as unconfirmed.
* **Walksnail Avatar, Autel SkyLink, Skydio, Yuneec, Fimi**: no open-source PHY or decoder exists on
  GitHub for any of them ([topic pages](https://github.com/topics/walksnail)); Autel SkyLink 2.0 hops
  900 MHz / 2.4 / 5.8 GHz with SkyLink 3.0 adding 5.2 GHz, and Skydio X10 Connect SL is an AES-256
  proprietary 2T4R link on 2400-2483.5 and 5150-5850 MHz, but no channel widths are published
  ([Autel](https://www.autelpilot.com/blogs/news/autel-evo-max-4t-autel-skylink-3-0-technology),
  [Skydio](https://www.skydio.com/connect), snippets).
* **DJI O3/O4 video**: not decodable. Verified widths exist only for OcuSync 2 (20/10/3/1.4 MHz,
  [tmbinc](https://github.com/tmbinc/random/tree/master/dji/ocusync2)) and the single O4 Mini 5 Pro
  measurement above. Chinese sources add that the DJI O4 Air Unit transmits in 5.170-5.250 GHz and
  5.725-5.850 GHz while the ground station also uses sub-2 GHz, 2.4 GHz and 5.2 GHz with automatic
  switching ([ithome](https://www.ithome.com/0/965/621.htm), snippet), which means a 2.4/5.8-only scan
  plan misses the 5.2 GHz DFS block.

### 4.3 Wi-Fi-based video: attribution by MAC, never decode

Both major open digital FPV stacks inject raw 802.11 frames with fixed, recognisable addresses.

[wfb-ng](https://github.com/svpcom/wfb-ng) (used by OpenIPC) sends data frames with frame control
`0x08 0x01`, RA `ff:ff:ff:ff:ff:ff` and TA/SA `57:42:<link_id:3><radio_port:1>`, where `0x57 0x42`
are the ASCII "WB" protocol header; its receive BPF is literally `ether[0x0a:2]==0x5742`
([wfb-ng](https://github.com/svpcom/wfb-ng),
[std draft](https://github.com/svpcom/wfb-ng/blob/master/doc/wfb-ng-std-draft.md)). Defaults are
channel 165 (5825 MHz), 20 MHz, MCS 1, STBC 1, LDPC 1, video FEC 8/12
([master.cfg](https://github.com/svpcom/wfb-ng)). Every payload is encrypted and authenticated with
libsodium's ChaCha20-Poly1305, so the link is **attributable by MAC prefix but never decodable
passively** ([wfb-ng](https://github.com/svpcom/wfb-ng)).

[OpenHD's wifibroadcast](https://github.com/OpenHD/wifibroadcast) uses a different header
(`0x08 0x01`, MACs `13:22:33:44:55:<port>`, with optional `0xb4` RTS-type frames), and OpenHD's
channel list includes non-standard entries at 2312-2712 MHz and 5080-6085 MHz with 10/20/40 MHz
widths, some marked "not valid in any country - but it works on rtl8812bu"
([OpenHD](https://github.com/OpenHD/OpenHD)). A Wi-Fi-FPV detector must therefore scan 2.3-2.7 GHz
and 5.08-6.09 GHz rather than only regulatory Wi-Fi channels.
[DroneBridge](https://github.com/DroneBridge/DroneBridge) is the odd one out: it injects at legacy
rates (radiotap rate byte, `0x08 0x00` data and `0xb4 0x00` RTS frames), which is exactly what
gr-ieee802-11 can decode.

---

## 5. Detection and classification techniques

### 5.1 Energy and burst detection with an adaptive noise floor

The field-proven first stage is a per-bin adaptive noise floor. Sandia's
[gr-fhss_utils](https://github.com/sandialabs/gr-fhss_utils) `fft_burst_tagger` (derived from
gr-iridium) keeps a per-bin dynamic noise floor over `history_size` FFTs and tags bursts that stay
`threshold` dB above it for `lookahead` FFTs, with masking of occupied bins, pre/post padding and
coarse centre-frequency and bandwidth estimation; `cf_estimate` then refines centre and bandwidth by
RMS centroid, half-power or "middle-out", and `sigmf_meta_writer` emits SigMF annotations
([gr-fhss_utils deep read](https://github.com/sandialabs/gr-fhss_utils)). Its examples run at 16 MSPS
(Sidekiq) and 30 MSPS (USRP) with FFT 256 and `burst_width` 500 kHz; at the E200's ~20 MSPS an
N of 256-512 gives 39-78 kHz bins and 12.8-25.6 us frames
([gr-fhss_utils deep read](https://github.com/sandialabs/gr-fhss_utils)).

It cannot be used directly. It is GPL-3.0-or-later so it cannot be vendored; it compiles with
`-mavx` and `_mm256` intrinsics so it will not build for the Zynq ARM
([issues #8, #21](https://github.com/sandialabs/gr-fhss_utils)); and it carries unfixed defects:
`set_threshold()` divides by `history_size` making runtime threshold changes unusable
([#26](https://github.com/sandialabs/gr-fhss_utils)), a `burst_width` below one bin yields zero-width
bursts ([#11](https://github.com/sandialabs/gr-fhss_utils)), the reported magnitude is inflated by
10*log10(history_size) dB, and the auto-reset when more than `max_bursts` are active drops the noise
floor and stops detection for `history_size` frames, which in a busy 2.4 GHz band can oscillate
([gr-fhss_utils deep read](https://github.com/sandialabs/gr-fhss_utils)). The project has had no
commits since 2023-08-17 and no maintainer response to 2025 issues. Re-implementation of the
algorithm in numpy is the recommendation
([ADR-0007](../docs/decisions/ADR-0007-detection-pipeline-heuristics-before-ml.md)).

Cheap statistical gating works well as a pre-filter. A PSD(1024) plus SVM binary drone/no-drone
detector reaches 0.983 accuracy at 0.286 ms per 20 ms window on an i9-9820X
([IQTLabs/RFClassification](https://github.com/IQTLabs/RFClassification)). Kurtosis is a good burst
gate: RF-Vision computes kappa = mean|x|^4 / (mean|x|^2)^2 capped at 20 with a 3-frame median and an
EMA of 0.35, and reports burst kurtosis of 6-8 against noise
([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)); the deep read flags that
its reference value of 3 is the real-valued figure and that circular complex Gaussian noise has
E|x|^4/(E|x|^2)^2 = 2, so the weighting onset is wrong as shipped
([deep read](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)).

### 5.2 Cyclostationary discrimination

The most transferable protocol-level test found is RF-Vision's stage 3: with `tau = round(Fs/spacing)`,
form `z = x[tau:] * conj(x[:-tau])`, take `NCC = |fft(z)| / (len(z) * power)`, and look for a peak in
the alpha window for the numerology of interest (22-30 kHz for 30 kHz spacing, 10.5-14.5 kHz for
15 kHz spacing, single bin at 250 kHz for Wi-Fi's 312.5 kHz). It scores each candidate with a peak
sharpness ratio (PSR), a cyclic frequency stability check across chunks (sigma < 500 Hz) and a
weighted composite, with per-sector thresholds learned by a calibration run
([RF-Vision deep read](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). Everything is Fs-generic
once tau and the chunk length are parameterised, so at 20 MSPS tau_30k = 667, tau_15k = 1333,
tau_wifi = 64 and the chunk becomes 80,000 samples, with the NCC noise floor rising by sqrt(2) so the
hard floors must be re-derived ([deep read](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). The
same deep read records that its own calibration and detector use mismatched chunk parameters
(200k/0.75 versus 160k/0.80), that the README's `bg_max` formula does not match the p95 code, and
that LTE 15 kHz and NR 30 kHz numerologies can produce OcuSync-like cyclic responses, which is a
false-alarm source in any European city. [gr-inspector](https://github.com/gnuradio/gr-inspector)
provides a reference blind OFDM parameter estimator (carrier spacing, symbol time, CP length) for
GNU Radio 3.8.

### 5.3 Spectrogram CNNs and their SNR behaviour

The headline comparison is real but narrower than usually quoted *(verified: verdict 8,
spectrogram-versus-IQ)*. From the NCTA 2023 paper bundled in
[sgluege/Noisy-Drone-RF-Signal-Classification](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification):

| Input | VGG11 | VGG13 | VGG16 | VGG19 |
|---|---|---|---|---|
| Balanced accuracy, all SNR: raw IQ (1D VGG) | 0.790 | 0.784 | 0.780 | 0.783 |
| Balanced accuracy, all SNR: complex STFT (2D VGG) | 0.900 | 0.897 | 0.899 | 0.898 |
| Balanced accuracy at -12 dB: raw IQ | 0.413 | 0.350 | 0.344 | 0.350 |
| Balanced accuracy at -12 dB: complex STFT | 0.842 | 0.819 | 0.829 | 0.812 |

Five qualifications that the raw numbers hide, all established in verdict 8:

1. The comparison is a naive 1D VGG (3-tap Conv1d, 25 epochs, from scratch) against the same network
   in 2D on an **invertible transform of the same samples**, so it demonstrates an inductive-bias and
   optimisation effect, not an information difference. The authors themselves say an IQ model with
   comparable performance may exist.
2. The gap is zero at SNR >= 0 dB, where both reach about 0.98
   ([Noisy-Drone-RF](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification)).
3. SNR is defined as burst carrier power over **full 14 MHz band** noise power, so for a 1-3 MHz RC
   link "-12 dB" is roughly -1 to -5 dB in band; the numbers do not transfer to datasets with other
   sample rates or SNR conventions (RFUAV 100 MSPS, DroneRF 40 MSPS real-valued)
   *(verified: verdict 8)*.
4. Third-party evidence says architecture matters more than input domain: on DroneRFa with synthetic
   channels, an IQ-only CNN-LSTM matches an STFT-EfficientNet at -10 dB AWGN (about 69% versus 68%)
   while an STFT-ResNet gets 47% and a plain IQ-CNN 33%
   ([SE-DCNet](https://github.com/maojinxiang/SE-DCNet)), though STFT models are more consistently
   robust under Rayleigh/Rician fading.
5. "Depth barely matters" holds only within the VGG family on this dataset, and reflects that
   low-SNR performance is information-limited; window length matters more, which is why the 2024
   follow-up moved from 16,384-sample (1.2 ms) to 1,048,576-sample (74.9 ms) windows
   ([Robust-Drone-Detection-and-Classification](https://github.com/sgluege/Robust-Drone-Detection-and-Classification)).

Window length is independently confirmed as the dominant knob: DroneDetect PSD+SVM scores 0.769 /
0.836 / 0.894 at 10 / 20 / 50 ms with accuracy insensitive to NFFT
([RFClassification](https://github.com/IQTLabs/RFClassification)), ZJU's ResNet-18 baseline drops
from 97.7% on 10 ms windows to 72.7% on 2.5 ms
([JEIT 10.11999/JEIT230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)), and the consensus
capture buffer across projects is 65-100 ms (ZHAW 74.9 ms at 14 MSPS, CageDroneRF 0.5 s windows at
0.1 s steps, RF-Vision 65.5 ms at 40 MSPS)
([U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB),
[RF-Vision](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). RFUAV separately reports that an STFT
of 256 points beat 1024 across SNRs on its data ([RFUAV](https://github.com/kitoweeknd/RFUAV)).

Only one project ships released weights, a public IQ dataset and a field test at an E200-compatible
rate: Glüge's VGG11_BN (GPL-3.0), 2^20-sample windows at 14 MSPS rendered as a 1024x1024 two-channel
complex STFT (n_fft = hop = 1024), 7 classes, 5-fold test accuracy 0.942 and >= 85% balanced accuracy
above -12 dB ([Robust-Drone-Detection-and-Classification](https://github.com/sgluege/Robust-Drone-Detection-and-Classification),
[arXiv 2406.18624](https://arxiv.org/abs/2406.18624)). Its class list is the problem: one DJI Phantom
4 Pro / GL300F link plus five hobby transmitters (Futaba T7C, Futaba T14SG, Graupner mx-16, FrSky
Taranis ACCST, Turnigy 9X) and Noise, with **no** OcuSync 2/3/4, no ELRS, no Crossfire and no 5.8 GHz
video ([deep read](https://github.com/sgluege/Robust-Drone-Detection-and-Classification)).

### 5.4 Open-set rejection

Closed-set classifiers are the wrong shape for an observation network that will meet links it has
never seen. [S3R](https://github.com/DaftJun/S3R) (IEEE TIFS 2024) is the implemented recipe: a
2048-point Hamming STFT with 50% hop, three dilated convolution branches (dilations 1, 3, 5) producing
a semantic embedding, and known/unknown decisions from class-centre distances with per-class
covariance, reaching 96.64% closed-set accuracy on DroneRFb-Spectra (14,460 samples, 7 brands: DJI,
Vbar, FrSky, Futaba, Taranis, RadioLink, Skydroid). Two blockers: the repository has **no LICENCE
file** and the data are 100 MSPS dual-band, so re-rendering to E200 rates is required
([S3R](https://github.com/DaftJun/S3R)). Its dataset ships nine predefined known/unknown splits,
which is the evaluation protocol worth copying.

### 5.5 Data leakage: published accuracies are not reproducible

This is confirmed and quantified *(verified: verdict 8)*. Shulman 2026
([arXiv 2607.01025](https://arxiv.org/abs/2607.01025), code
[spectrahawk](https://github.com/shulm/spectrahawk)) shows AR-versus-Bebop type identification on
DroneRF falling from macro-F1 0.742 [0.728, 0.755] to 0.455 [0.439, 0.470], which is chance, under
leave-one-recording-out evaluation, with only 4 independent recordings per drone; essentially all the
inflation is within-recording segment leakage. The original
[Al-Sad/DroneRF Classification.py](https://github.com/Al-Sad/DroneRF/blob/master/Python/Classification.py)
uses `StratifiedKFold(shuffle=True)` over segments.

But the inflation is task- and capacity-dependent, and the corrected claim says so: binary
drone-versus-background detection stays strong under grouped evaluation (ROC-AUC 0.978 +/- 0.017),
and a grouped-versus-window benchmark with weak 2048-sample models changed accuracy by only 0-3
points (binary RF 0.871 to 0.857; type 0.55 to 0.54; mode 0.43 to 0.41)
([dronerf-emi-robustness results](https://github.com/greenbeanss/dronerf-emi-robustness)), because
those small models were already near the honest level. The inflation is a property of high-capacity
models memorising many windows per recording.

Note the same problem in the low-SNR spectrogram results themselves: Glüge's protocol is five random
stratified splits over windows from single anechoic-chamber recordings per class (and the folds are
not even disjoint), and SE-DCNet's split puts all 109 source `.mat` files in train, validation and
test ([verdict 8](https://github.com/maojinxiang/SE-DCNet)). Other datasets carry their own hygiene
faults: RF-TCNet and DroneRFA_24 split shuffled spectrogram images inside each class, the
LowSNR_DroneRF Kaggle file stores power values rather than IQ with only OFF/ARMED labels and is
ordered by class, and DroneRFa has acquisition gaps every 10M samples (0.1 s) so windows must stay
below 0.1 s ([RF-TCNet](https://github.com/FAITHSHUNAA/RF-TCNet-A-Lightweight-Topology-Compression-Network-for-Drone-RF-Fingerprint-Identification),
[LowSNR-DroneRF-Reproduction](https://github.com/jainarein/LowSNR-DroneRF-Reproduction),
[JEIT 10.11999/JEIT230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)). A second leakage
pathway is receiver-specific: CFO, DC offset and noise-floor fingerprints correlate with capture
hardware when classes are collected on different radios
([2_Stage_Drone_Detection_Model](https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model)).

### 5.6 Domain shift, lab to field

Three independent measurements say the same thing. Hand-crafted statistical features fall from 100%
to 42.3% when tested on an unseen individual drone unit of the same model (DroneRFb-DIR, train on
individuals 1-2, test on 3) while ConvNeXt-Base keeps 92.0%
([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub), self-reported). CrossRF on UAVSig rises from
26.39% to 99.03% cross-channel only with adversarial domain adaptation
([rfml-moe-hub survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md),
unverified secondary). And most directly relevant: RF-Vision's YOLOv8n reports training mAP@0.5 of
0.995 on RFUAV recordings resampled to 40 MSPS but only 0.2-0.7 confidence on live SDR data, which is
why its configuration lowers the detection threshold to 0.30
([RF-Vision config.py](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). Its own midterm report
concedes that Wi-Fi is expected to pass the YOLO stage because there are no Wi-Fi, 4G or 5G negatives
in the training set ([RF-Vision docs](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). On DroneRF,
compact CNN and ResNet-18 accuracy drops to 37.1% and 21.9% at -5 dB without noise injection and
recovers to 76.5% and 81.1% with random-SNR training
([drone-rf-id](https://github.com/song-lalala/drone-rf-id)).

### 5.7 Edge versus host inference budgets

| Workload | Cost | Platform | Source |
|---|---|---|---|
| Glüge VGG11_BN on 1024x1024 complex STFT | ~156 GMAC (~312 GFLOP) and ~268 MB first-layer activation per 75 ms window | not real-time on CPU, impossible on the Zynq ARM | [deep read](https://github.com/sgluege/Robust-Drone-Detection-and-Classification) |
| VGG spectrogram inference | 79 ms FP16 | Jetson, TensorRT | [rf-signal-intelligence](https://github.com/rameyjm7/rf-signal-intelligence) |
| YOLOv8n on 640x640 waterfall | ~30 ms | RK3588 NPU | [RF-Vision](https://github.com/ALPssdz/RF-Vision-UAV-Tracker) |
| PSD(1024) + SVM binary detection | 0.286 ms per 20 ms window | i9-9820X | [RFClassification](https://github.com/IQTLabs/RFClassification) |
| MobileNetV3-Large (4.2M params) on RFUAV 37-class | 97.1% | laptop-class | [rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub) |
| YOLOv11n-cls (~1.6M) / MaxViT-Base (118.7M) on RFUAV | 97.4% / 97.8% | laptop-class | [rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub) |

The E200 carries a dual Cortex-A9 with 512 MB of DDR3
([hardware-e200.md](hardware-e200.md), from
[the vendor manual](https://github.com/MicroPhase/antsdr_doc_en)), so the split is forced: capture,
decimation and energy/kurtosis gating on the board, classification on the Ethernet-attached host.
That is [ADR-0005](../docs/decisions/ADR-0005-processing-location.md). Two Chinese results suggest
small models could eventually run on the ARM (a multi-branch CNN with attention at 94.6-94.8%
detection between -15 and -6 dB SNR with 1.61 ms inference, and an MFCC+GRU model with only 1.6k
parameters at 98% on USRP N210 captures,
[信号处理 2023](https://signal.ejournal.org.cn/article/doi/10.16798/j.issn.1003-0530.2023.05.016),
[JEIT 10.11999/JEIT241111](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT241111?viewType=HTML)), but
both are snippet-level and neither ships code.

SigMF is the interchange format across everything usable: IQTLabs' [rfml](https://github.com/IQTLabs/rfml)
auto-labels bursts into `.sigmf-meta` (power threshold plus GMM bandwidth estimate),
[gr-fhss_utils](https://github.com/sandialabs/gr-fhss_utils) has a `sigmf_meta_writer`, and
[IQEngine](https://github.com/iqengine/iqengine) annotates SigMF in the browser. Recording as SigMF
from day one is [ADR-0002](../docs/decisions/ADR-0002-sigmf-recordings.md).

---

## 6. Localisation: two-channel DoA, TDOA, passive radar

### 6.1 Two-channel DoA on one AD9361

The physics is favourable and the practice is not. Both E200 receive chains come from a single
AD9361 and share one RX RFPLL, so they are intrinsically coherent and sampled on the same clock
*(verified: verdict 1, `rf-ports`)*. [jonkraft/Pluto_Beamformer](https://github.com/jonkraft/Pluto_Beamformer)
demonstrates the whole chain on the same silicon with `adi.ad9361(...)`, `rx_enabled_channels=[0,1]`,
`d = c/(2f)` and a per-setup constant phase offset (hard-coded -0.3 rad in the MVDR script), with the
explicit note that the sample rate must be <= 30.72 MHz with both channels enabled
([Pluto_Beamformer deep read](https://github.com/jonkraft/Pluto_Beamformer)).

Five things stand between that and a bearing the toolkit can publish:

1. **RX2 is on internal u.FL.** MicroPhase's own table lists the E200 as "SMA:1T1R IPEX:1T1R" against
   "2T2R MIMO" for the E310/E316
   ([RF parameters](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md)).
   The CrowdSupply campaign states the kit ships a U.FL-to-SMA bulkhead pigtail rated under 2 dB to
   6 GHz (snippet), so the pair is reachable *(verified: verdict 1)*.
2. **There is no RF switching at all.** The UHD FPGA top drives only `tx_amp_en1` with all SFDX/SRX
   switch lines commented out, so the "TX/RX" and "RX2" antenna names UHD prints are B210 driver
   leftovers and are no-ops; RX1 is hard-wired to its SMA *(verified: verdict 1,
   [antsdr_e200.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/antsdr_e200.v))*.
   Note this **contradicts** an earlier round-1 finding that RX2 is selectable with
   `set_rx_antenna("RX2")`
   ([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp));
   the verified reading wins.
3. **Phase is only stable within a tune state.** ADI's EngineerZone answer for the Pluto rev C (same
   single-chip 2RX topology) states the RX1/RX2 relative phase stays constant as long as LO and
   sample rate are not touched, and that rewriting either, even with the same value, can change it
   because the driver re-runs RX QEC, RF DC and BBF calibrations
   ([ez.analog.com thread 601154](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/f/q-a/601154/adalm-pluto-revc-phase-between-rx1-rx2-is-not-stable),
   snippet) *(verified: verdict 1)*. The magnitude of the per-retune jump is **not established by any
   source**, and gain dependence is asserted from first principles only. Nobody has published a
   measurement on the E200.
4. **The second channel must be unlocked on Pluto firmware.** The stock QSPI image declares the chip
   as `adi,ad9364` and u-boot strips `adi,2rx-2tx-mode-enable` when `mode=1r1t`, so RX2 does not exist
   until `fw_setenv attr_name compatible; fw_setenv attr_val ad9361; fw_setenv compatible ad9361;
   fw_setenv mode 2r2t; reboot` is run (or the uEnv.txt equivalent for SD boot). It is **not** needed
   for the UHD firmware or for openwifi *(verified: verdict 1,
   [antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md))*.
5. **Two elements is a coarse sensor.** KrakenSDR's array rules apply directly: keep the spacing
   multiplier under 0.5 to avoid ambiguities and above about 0.2, a linear array is "only valid for
   180 degrees, and there is no way of knowing if the signal is coming from in front, or behind", and
   "radio direction finding bearings will always have inaccuracies of several degrees" with small
   arrays absorbing multipath into the main lobe
   ([KrakenSDR wiki 03/04](https://github.com/krakenrf/krakensdr_docs/wiki/04.-Antenna-Array-Setup)).
   Their own resolution estimates are for **five** elements (about 3.4 degrees for a 5-element linear
   array at 0.5 lambda). Cable lengths must match to within a centimetre up to about 900 MHz
   ([KrakenSDR wiki](https://github.com/krakenrf/krakensdr_docs/wiki/04.-Antenna-Array-Setup)), which
   is a real problem when one element is on an SMA jack and the other on a pigtail. At 2.4 GHz the
   E200 pair should sit 2.5-6 cm apart.

Because the toolkit is passive, calibration cannot use a TX loopback and needs an external common
reference (a splitter-fed source, or an over-the-air beacon at a known bearing)
*(verified: verdict 1)*. KrakenSDR's [heimdall](https://github.com/krakenrf/heimdall_daq_fw)
`delay_sync.py` is a reusable, hardware-agnostic template for that: cross-correlation at zero and
non-zero lag for sample alignment, amplitude and phase offsets from the dominant eigenvector of the
spatial correlation matrix with a 3-degree tolerance, and fractional delay from the phase-versus-
frequency slope. Bridging E200 IQ into heimdall's 1024-byte-header frame format would let
[krakensdr_doa](https://github.com/krakenrf/krakensdr_doa) (Bartlett, Capon, MEM, MUSIC, ROOT-MUSIC
via pyArgus) run unchanged.

The rate budget bites here too: two coherent channels are limited to roughly 10 MSPS each, which is
below the 15.36 MSPS DroneID PHY rate, so DroneID direction finding needs on-board preprocessing or
decimated/burst capture rather than full-rate two-channel streaming *(verified: verdicts 1 and 2)*.
This is why [ADR-0009](../docs/decisions/ADR-0009-localisation-deferred.md) defers localisation.

### 6.2 TDOA

Exactly one drone-specific open TDOA project was found, and it is research-grade.
[cherubimro/dronelocate](https://github.com/cherubimro/dronelocate) needs B210-class UHD nodes with a
`gps_locked` sensor or an external PPS, uses a Doppler-searching CAF with GCC weighting that "cuts
timing error from 8.9 to 3.5 ns RMS", and reports about 0.2 m median horizontal and 2 m median
vertical error **in emulation only**. Its own README says the UHD path is "unverified against
hardware", that surveyed node position error (3-5 m from a single GNSS fix) propagates one to one,
and that the authors recommend KrakenSDR AoA for production with TDOA as complementary. The E200 has
one MMCX 10 MHz/PPS input disciplined through an `ad5660mp` IIO device (`ref_sel` 0:10M, 1:PPS,
2:GPS) and the UHD driver exposes `clock_source` and `time_source` with `set_time_next_pps`, but
there is **no onboard GPSDO**; the `gpsdo` option is enabled only for the E310 v2
([E200 reference manual](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md),
[ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)).
A GPS-free fallback exists in [DC9ST's design](https://github.com/DC9ST/tdoa-evaluation-rtlsdr), where
receivers alternate between a known reference transmitter and the target frequency so relative clock
offsets are solved from the reference; dronelocate lists exactly that as not yet implemented.

### 6.3 Passive radar

No open passive-radar project documents drone or micro-Doppler detections.
[blah2](https://github.com/30hours/blah2) supports a USRP B210 with `subdev 'A:A A:B'` and channels
{0,1} at 2 MSPS in its example config, but targets FM/DAB/LTE illuminators and aircraft, and its
README records an unresolved B210 timeout after 5-10 minutes.
[pyapril](https://github.com/pyapril/pyapril) supplies the DSP building blocks (Wiener-SMI and ECA
clutter cancellation, cross-correlation detection, CA-CFAR, target DoA) under GPLv3. The Russian
[passive-sdr-radar](https://github.com/Stanislav-sipiko/passive-sdr-radar) uses DVB-T2 at 546 MHz with
a KrakenSDR and a CAF-CFAR-Kalman pipeline, but its own TODO says real KrakenSDR data are not yet
connected. Passive-radar drone detection with the E200 would therefore be **original work**, not
reuse, and would be the only route to RF-silent fibre-optic FPV aircraft
([passive-sdr-radar](https://github.com/Stanislav-sipiko/passive-sdr-radar)).

For context on what "detectable" means in the field, the vendor-adjacent WarDragon documentation
claims DroneID reception at several hundred metres in urban settings, 1-2 km clear line of sight with
a stock antenna and up to about 10 km with an external LNA and directional antenna, Wi-Fi Remote ID
beyond 700 m, and BT5 LE Coded S8 at 500 m to over 1 km
([WarDragon](https://github.com/alphafox02/WarDragon/blob/main/docs/software/detection-capabilities.md)).
These are unmeasured vendor figures, and Russian field tests of handheld detectors report roughly
1-1.5 km with delayed reaction to 5.8 GHz analog video
([4vision](https://4vision.ru/blog/portativnyj-vsenapravlennyj-detektor-dronov-bulat-v3-obzor-modeli),
snippet). No academic detection-range or link-budget model for 2.4/5.8 GHz drone links was found in
the allowed sources.

---

## 7. What this means for the toolkit

Priorities, highest first, each with the evidence that puts it where it is.

**P1. Wideband burst detection with a per-bin adaptive noise floor, re-implemented in numpy.**
It is the one stage that works on every signal family, decodable or not, it is well specified by
[gr-fhss_utils](https://github.com/sandialabs/gr-fhss_utils), and it cannot be reused directly because
of GPLv3 plus AVX-only intrinsics ([deep read](https://github.com/sandialabs/gr-fhss_utils)). Pair it
with a kurtosis burst gate (correcting the noise reference to 2.0 for complex baseband,
[RF-Vision deep read](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)) and emit SigMF annotations
([rfml](https://github.com/IQTLabs/rfml)). See
[ADR-0007](../docs/decisions/ADR-0007-detection-pipeline-heuristics-before-ml.md).

**P2. DJI DroneID as three explicit tiers, not one decoder.** Tier A (identity plus position) for
O2/O3 via the closed E200 firmware, because it is the only thing that decodes O3 today
([alphafox02](https://github.com/alphafox02/antsdr_dji_droneid); *verified: verdict 4*); Tier B
(presence only) for O4/O4+, emitting hash, frequency, RSSI and time and never a serial or position
([proto17 #50](https://github.com/proto17/dji_droneid/issues/50)); Tier C (identity via standard
Remote ID) for everything else. Keep [proto17](https://github.com/proto17/dji_droneid) (MIT) as the
inspectable open fallback and regression bench, and do not promise O3 or Mavic 2 decoding from it.
See [ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md).

**P3. A generation-agnostic ZC and burst fingerprinter in front of any decoder.** Fixed roots 600/147
hold for O2 and 600/385 for O3, but O4+ changes the root between frames
([proto17 #65](https://github.com/proto17/dji_droneid/issues/65)), and LightBridge produces a
14-symbol signal no open decoder handles
([DroneSecurity #43](https://github.com/RUB-SysSec/DroneSecurity/issues/43)). Detect on burst
geometry (630-665 us at 8-11 MHz, ~600 ms cadence) plus a root-agnostic ZC test rather than on a
template.

**P4. Cyclostationary OFDM discrimination as the false-alarm filter.** The CP autocorrelation test
separates OcuSync numerologies from Wi-Fi's 250 kHz cyclic feature and is Fs-generic
([RF-Vision](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)); budget for LTE 15 kHz and NR 30 kHz
false alarms, which the source project explicitly warns about
([RF-Vision midterm report](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). This claim set is
**unverified round-1** (`ocusync-phy`) and needs a bench check.

**P5. Analog 5.8 GHz FPV capture and decode at 20 MSPS.** It is the only video family that is fully
decodable, the E200 is already the recommended radio for the reference implementation
([fpv-sdr](https://github.com/lukeswitz/fpv-sdr)), and 20 MSPS is both fpv-sdr's own E200 default and
inside the Ethernet budget. Treat 10-12 MSPS as a fallback (10 MSPS gives NTSC colour, 12 or more is
needed for PAL chroma), always run AFC because VTX are 1-3 MHz off at power-up, and flag PAL colour as
an unsupported gap in all open decoders *(verified: verdict 5)*.

**P6. RC-link detection by timing signature, with sub-GHz ELRS decode as a stretch goal.** Every
2.4 GHz ELRS mode is detect-only and its hop set is wider than the E200's analog bandwidth
*(verified: verdict 3)*, so build a swept chirp-and-timing detector using the exact ELRS interval
table ([common.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/src/common.cpp)). Sub-GHz
ELRS is a decode candidate via a channelised [gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr)
chain plus the ELRS OTA layer, but no public project has demonstrated it against real radios, so it
must be validated with an owned TX/RX pair before it is advertised *(verified: verdict 3)*.

**P7. Wi-Fi FPV attribution by MAC prefix.** Cheap, deterministic, and it covers the whole
OpenIPC/OpenHD ecosystem: `57:42:...` for [wfb-ng](https://github.com/svpcom/wfb-ng),
`13:22:33:44:55:xx` for [OpenHD](https://github.com/OpenHD/wifibroadcast), plus Kismet's SSID and OUI
rules for consumer Wi-Fi drones
([kismet_uav.conf](https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf)).
Payloads are ChaCha20-Poly1305 encrypted and will never be decodable passively
([wfb-ng](https://github.com/svpcom/wfb-ng)).

**P8. Remote ID on commodity dongles, not on the E200.** An openwifi-mode E200 most likely misses the
mainstream 1 Mbps DSSS beacons, cannot receive Bluetooth at all, watches one 20 MHz channel at a
time, and halts after about two hours on the evaluation-licensed Viterbi decoder *(verified: verdict
6)*. Use a monitor-mode NIC with 802.11b/g/n/a plus a Sniffle-class BLE 5 dongle
([Sniffle](https://github.com/nccgroup/Sniffle)), and parse ASTM/EN 4709 alongside GB 42590 and
GB 46750 ([luolitao/remoteid](https://github.com/luolitao/remoteid)). See
[ADR-0010](../docs/decisions/ADR-0010-band-coverage.md).

**P9. Spectrogram classification on the host, with a leakage-proof protocol as a hard rule.** Use a
time-frequency front end by default and treat "raw IQ versus spectrogram" as an architecture choice
rather than an information choice *(verified: verdict 8)*. Use small backbones
([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)) and spend the budget on window length
(tens of ms), SNR-aware training and the burst detector in front. Split by
recording/session/device/day, test E200 captures against models trained on public data, and report
detection metrics separately from type-ID accuracy, because DroneRF-family type accuracies are
non-reproducible upper bounds *(verified: verdict 8)*.

**P10. Use the protocol decoders as the ground-truth labeller.** DroneID, Remote ID and (later) ELRS
give free labels for E200 captures, which is the only realistic escape from the few-recording regime
that produces the leakage above *(verified: verdict 8)*. Public corpora need decimation first: RFUAV
is 100 MSPS, DroneRFa 100 MS/s per channel, DroneRFb-DIR 80 MSPS, DroneDetect 60 MSPS, against
E200-compatible ZHAW v2 at 14 MSPS and CageDroneRF at 20 MSPS
([datasets.md](datasets.md), [RFUAV](https://github.com/kitoweeknd/RFUAV),
[U-RAPTOR-PUB](https://github.com/DroneGoHome/U-RAPTOR-PUB)).

**P11. Two-channel DoA only after a characterisation run.** Everything needed exists
([Pluto_Beamformer](https://github.com/jonkraft/Pluto_Beamformer),
[heimdall](https://github.com/krakenrf/heimdall_daq_fw)), but no measured RX1/RX2 phase figure exists
for the E200, the pair must be fed by a length-matched pigtail, and a two-element array gives a
180-degree cone with front/back ambiguity and errors of several degrees
([KrakenSDR wiki](https://github.com/krakenrf/krakensdr_docs/wiki/04.-Antenna-Array-Setup))
*(verified: verdict 1)*. Ship a first-run script that records phase across retunes, rate changes and
gain steps before any bearing is published
([ADR-0009](../docs/decisions/ADR-0009-localisation-deferred.md)).

**P12. TDOA and passive radar: research backlog, not roadmap.** The only drone TDOA project is
emulation-validated with an unverified UHD path
([dronelocate](https://github.com/cherubimro/dronelocate)), the E200 has no onboard GPSDO
([E200 manual](https://github.com/MicroPhase/antsdr_doc_en)), and no open passive-radar project has
published a drone detection ([blah2](https://github.com/30hours/blah2),
[passive-sdr-radar](https://github.com/Stanislav-sipiko/passive-sdr-radar)).

Everything above stays receive-only. Active measures in the Netherlands are reserved to police and
Defence under the temporary framework in Staatscourant 2026 nr. 2035
([dronewatch summary](https://www.dronewatch.nl/2026/03/17/nieuwe-richtlijn-politie-mag-drones-verstoren-overnemen-en-zelfs-neerschieten/),
[stcrt-2026-2035](https://veiligesmartcities.nl/wp-content/uploads/2026/03/stcrt-2026-2035.pdf)), which
is [ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md) and
[ADR-0011](../docs/decisions/ADR-0011-legal-posture.md); the detail is in
[regulatory.md](regulatory.md).

---

## Gaps

What the evidence could not establish, drawn from the lenses' open questions and the verification
pass. These are the things to measure or fetch before they drive a design decision.

**DJI and OcuSync**

* The `o4-firmware-channels` claim (E200 O4 firmware hopping only 2434.5/5756.5/5776.5/5816.5 MHz,
  1r1t at a 61.44 MSPS path clock, legacy firmware using an FPGA correlator at
  `/dev/my-axi-droneid-filter0`) was never adversarially verified; the agent budget ran out.
* The `ocusync-phy` claim set (OcuSync 2 numerology, O3/O4 ~30 kHz spacing, ~9 MHz 99% bandwidth and
  5 ms periodicity on the Mini 5 Pro, CP autocorrelation versus Wi-Fi) was likewise never verified.
* The exact DroneID hop sequence and dwell are not documented anywhere open; the 13-point set and the
  12-20 bursts per channel figure come from paywalled or blocked papers, and the frequency lists in
  the repos are observational unions.
* O4/O3 Pro encryption is opaque: no public information on algorithm or key handling, and the
  firmware's per-session hash derivation could not be verified.
* Open O3 decoding is unproven in every public repo while the closed E200 firmware claims it; the O3
  burst variant would have to be reverse-engineered from E200 captures.
* The licence of [alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) is
  ambiguous (no root LICENSE, MIT header only in one script) and the redistributed firmware binaries
  carry no stated licence.
* Whether DroneID transmission really requires spinning motors is unresolved per model.
* `leegang12`'s CSDN claim of CRC-correct O1-O4 decoding is snippet-only with no code.

**Remote ID and Wi-Fi**

* The PHY rate of commercial (for example DJI) Remote ID beacon frames is unverified, so whether an
  OFDM-only receiver can see them is unknown; capture with a COTS card and read the radiotap data
  rate before relying on openwifi.
* Which band and channel DJI uses for Remote ID (2.4 GHz ch 6 versus 5 GHz ch 149) is not established.
* Per-model EU behaviour for 2024-2026 DJI aircraft rests on forum reports; no authoritative DJI
  statement could be fetched.
* No open SDR decoder exists for BLE 5 Coded PHY, and the feasibility of implementing S=8 on E200 IQ
  or in its FPGA is unknown.
* The GB 46750 timestamp encoding is contradicted between the two open implementations, and it is
  unknown whether China-market drones emitting GB frames appear in the Netherlands.

**RC and telemetry**

* TBS Crossfire per-mode LoRa parameters (SF/BW/CR, preamble, sync, spacing for the 150/50/4 Hz
  modes) could not be fetched; only the FSK 150 Hz figures and the channel split are confirmed.
* No open demodulator exists for Semtech FLRC, and none for SX1280 LoRa with the long interleaver.
* Herelink and Skydroid H16 physical layers are unknown; fccid.io is blocked.
* FrSky ACCESS, Futaba FASST and Flysky AFHDS 3 have no public reverse engineering.
* No public IQ dataset contains ELRS, Crossfire, SiK or AFHDS-2A signals; own captures are required.
* MilELRS and similar forks are closed source; their band information comes from secondary
  Russian/Ukrainian sources and vendor sheets.

**Video**

* HDZero and Walksnail Avatar on-air modulation, symbol rate and occupied bandwidth are undocumented
  in every open repository; only channel plans and chip names are verified.
* DJI O3/O4 video-link bandwidths could not be verified from a fetched primary source.
* Analog FM video occupied bandwidth rests on one unreproduced hobbyist measurement with an 8-bit
  HackRF; energy beyond +/-10 MHz was invisible in that test and audio-equipped or high-power VTX
  were not measured.
* No open source exists for Autel SkyLink, Skydio, Yuneec or Fimi links.

**Detection, classification, datasets**

* No public pretrained model exists for DJI OcuSync 3/4, ELRS, Crossfire or Remote-ID-era links at
  E200 sample rates; the only released weights cover one legacy DJI class plus five hobby
  transmitters.
* No SigMF-format drone dataset containing ELRS/Crossfire/DJI O3/O4 was found.
* CPU inference latency of the 1024x1024 complex-STFT VGG on a laptop was never measured; only the
  Jetson TensorRT figure exists.
* The accuracy cost of decimating or re-rendering 80-100 MSPS corpora to E200 bandwidth has not been
  quantified by any source.
* Several dataset facts (DroneDetect, CardRF, Ezuma, UAVSig, DroneRFb-DIR, DRFF-R2) rest on
  third-party GitHub notes because IEEE DataPort, Mendeley, Zenodo, Kaggle, SciDB, Hugging Face and
  arXiv were all egress-blocked; licences and sizes need re-checking.
* Whether [gamutRF](https://github.com/IQTLabs/gamutRF) / gr-iqtlabs (archived read-only 2025-07-01)
  should be reused or replaced by a light Python UHD/SoapySDR capture loop is an open design decision.

**Hardware, localisation, platform**

* No measured RX1/RX2 phase-coherence or drift figure exists for the E200; only chip-level statements.
* The maximum sustainable two-channel rate over 1 GbE was never measured on either firmware, and
  whether sc8/sc12 over-the-wire formats actually work on the E200 FPGA is unverified.
* No quantitative DoA accuracy for a two-element AD9361 interferometer was found anywhere.
* Whether the E200's single 10 MHz/PPS MMCX input can take both simultaneously, and whether the UHD
  "external" clock source actually locks the AD9361 reference, is unverified.
* A RadioReference report of worse close-in phase noise than a Pluto at 1 GHz is unresolved and the
  thread could not be fetched; it needs a bench check before narrowband decoding is trusted.
* Nobody has reported E200-based TDOA, and dronelocate's UHD path is unverified on any hardware.
* Whether heimdall or pyArgus DoA can run in real time on the E200's dual Cortex-A9 alongside IIO
  streaming is untested.

**Legal**

* The Dutch "bijzondere inspanning" interpretation under art. 139c Sr comes only from a search
  snippet; no case law specific to drone RF monitoring was found, and GDPR handling of stored Remote
  ID operator identifiers by a private network has no Dutch or EASA guidance. See
  [regulatory.md](regulatory.md).

**Coverage of non-English communities**

* Chinese (CSDN, Zhihu, bilibili, CNKI), Russian (habr, cyberleninka) and Ukrainian primary sources
  were largely egress-blocked, and the WebSearch budget was exhausted part-way through the sweep, so
  several lenses fell back to GitHub-hosted material only. No Chinese-language work using the ANTSDR
  E200 for drone detection was found at all, and the Russian/Ukrainian open scene is ESP32/RSSI
  hardware rather than IQ-level tooling. Details in
  [foreign-perspective.md](foreign-perspective.md).
