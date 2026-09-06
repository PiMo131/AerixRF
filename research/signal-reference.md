# Signal reference tables

Parameter tables for every drone-related link family the research sweep found evidence for, laid out
so that a heuristic classifier can be written straight off the page. The companion prose is in
[landscape.md](landscape.md); the platform limits are in [hardware-e200.md](hardware-e200.md); the
training corpora are in [datasets.md](datasets.md); the legal frame is in
[regulatory.md](regulatory.md); the Chinese, Russian and Ukrainian view is in
[foreign-perspective.md](foreign-perspective.md); the full bibliography with per-source
verified/snippet flags is in [sources.md](sources.md).

## How to read these tables

Every row carries a source link. Nothing here is from memory, and where the evidence is a search
snippet, a single hobbyist measurement or two sources that disagree, the row says so.

* **verified** means an agent cloned the repository or fetched the page and read it. **snippet**
  means only a search-engine snippet was reachable. **derived** means the number is arithmetic on
  verified constants (for example dwell = hop interval x packet interval), not something a source
  states directly.
* Eight design-critical claims went through an adversarial verification pass and are cited as
  *(verified: verdict N, name)*, mirrored in [verification-log.md](verification-log.md).
* Two claims were queued for that pass but the agent budget ran out. They are labelled
  **unverified round-1** wherever used: the E200 O4 firmware channel set (`o4-firmware-channels`)
  and the OcuSync generation PHY summary (`ocusync-phy`).
* The last-but-one column uses three states only:
  * **decodable** = an open-source implementation exists, or the protocol is fully specified in open
    code and unencrypted, so a payload decoder is a matter of work rather than research;
  * **detect-only** = the waveform can be found and classified but no open decoder exists (either
    the PHY is undocumented or no one has written one);
  * **encrypted** = the payload is cryptographically protected, so decoding is out of reach
    regardless of PHY work.

Column meanings: *band / channel plan* is where the emitter can legally or actually sit; *occupied
bandwidth* is the on-air width of one transmission, not the channel spacing; *burst or frame
duration* is one transmission; *repetition / hop rate* is the interval between consecutive
transmissions; *dwell* is how long the emitter stays on one frequency; *duty cycle* is burst
duration divided by repetition interval on the occupied channel.

**Platform constraint that shapes every "observable?" judgement below**: the AD9361 gives up to
56 MHz of analog bandwidth but the 1 GbE host link caps sustained single-channel sc16 streaming at
the vendor's stated 20 MSPS *(verified: verdict 2, host streaming tiers,
[vendor table](https://github.com/MicroPhase/antsdr_doc_en))*. Anything wider than about 20 MHz is
observed partially, or through a snapshot capture at up to 61.44 MSPS, or after decimation in the
Zynq PL.

---

## 1. DJI DroneID (broadcast identification burst)

DroneID is the short OFDM broadcast a DJI aircraft emits alongside its command/video airlink. It is
not standard Remote ID (section 6) and not the airlink itself (section 2).

| Family / mode | Band / channel plan | Occupied bandwidth | Burst or frame duration | Repetition / hop rate | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| DroneID, OcuSync 2 (Mini 2, Mavic Air 2) | 2399.5 / 2414.5 / 2429.5 / 2444.5 / 2459.5 MHz and 5756.5 / 5776.5 / 5796.5 MHz (proto17); wider live list in section 1.1 | ~9 MHz (600 data carriers x 15 kHz), "10 MHz" nominal, 15.36 MHz including guards | 9880 samples = 643.2 us at 15.36 MSPS (9 OFDM symbols) | ~600 ms | 12-20 bursts per channel before hopping | QPSK on 600 carriers, 15 kHz spacing, no pilots; CP schedule long, short x7, long = [80,72x7,80] at 15.36 MSPS | ~0.11 % (derived, 643 us / 600 ms) | Zadoff-Chu pilots at symbols 4 and 6, roots 600 and 147 | **decodable** | [proto17/dji_droneid](https://github.com/proto17/dji_droneid), [DroneSecurity helpers.py](https://github.com/RUB-SysSec/DroneSecurity), [Bender arXiv 2207.10795](https://arxiv.org/abs/2207.10795) (dwell, snippet) |
| DroneID, legacy 8-symbol (Mavic Pro, Mavic 2) | as above | ~9 MHz | 8784 samples = 571.9 us at 15.36 MSPS (8 symbols, first omitted) | ~600 ms | as above | as above, CP [80,72x6,80], ZC at symbols 3 and 5 | ~0.10 % (derived) | one symbol short; DroneSecurity gates it at 565-600 us | detect-only in open code (Mavic 2 Pro decode fails) | [DroneSecurity helpers.py](https://github.com/RUB-SysSec/DroneSecurity), [DroneSecurity #49](https://github.com/RUB-SysSec/DroneSecurity/issues/49) |
| DroneID, OcuSync 3 (Mavic 3 family, Air 2S, Mini 3 Pro) | 2.4 and 5.8 GHz, same raster | ~9-10 MHz | 10 OFDM symbols, four ZC symbols, no long CP, 7200 bits | not established | not established | QPSK + 4 ZC; Mavic 3 analysis found roots 600 and 385, each twice, with 6 data symbols | not established | four ZC symbols instead of two | **detect-only** in open code; decoded only by the closed E200 firmware | [proto17 #58](https://github.com/proto17/dji_droneid/issues/58), [proto17 Mavic 3 wiki](https://github.com/proto17/dji_droneid/wiki/DJI-Mavic-3-DroneID-Analysis), [DroneSecurity #46](https://github.com/RUB-SysSec/DroneSecurity/issues/46) *(verified: verdict 4, DJI generation coverage)* |
| DroneID, OcuSync 4 (Air 3, Mini 4 Pro, Avata 2, Neo, Air 3S, Flip, Mavic 4 Pro, Mini 5 Pro) | 2.4 and 5.8 GHz; E200 firmware auto mode watches 2434.5 / 5756.5 / 5776.5 / 5816.5 MHz (**unverified round-1**, `o4-firmware-channels`) | ~9 MHz; 99 % bandwidth measured 8.921-8.926 MHz on a Mini 5 Pro | ~500 us burst with 4 ZC sequences (Air 3S) | 5 ms periodicity measured on Mini 5 Pro (**unverified round-1**, `ocusync-phy`) | not established | QPSK demodulates cleanly; payload encrypted (SM2 for key packets, AES-128-CTR for telemetry on Mini 5 Pro) | not established | burst present, constellation clean, payload opaque; only a per-session hash, frequency and RSSI are recoverable offline | **encrypted** | [proto17 #50](https://github.com/proto17/dji_droneid/issues/50), [DroneSecurity #50](https://github.com/RUB-SysSec/DroneSecurity/issues/50), [luyii-code-1/dji-ocusync-droneid-research](https://github.com/luyii-code-1/dji-ocusync-droneid-research) *(verified: verdict 4)* |
| DroneID, OcuSync 4+ (Avata 360) | 5.8 GHz | ~9 MHz | 10 symbols: QPSK x3, ZC x2, ZC x2, QPSK x3 | not established | not established | ZC root indices change from frame to frame | not established | root-agnostic ZC detection is required; fixed 600/147 templates fail | **encrypted** | [proto17 #65](https://github.com/proto17/dji_droneid/issues/65) |
| DroneID, LightBridge / OcuSync 1 (Phantom 4 Pro V2) | 2.4 GHz | not established | 14-symbol signal with two sync symbols | not established | not established | not established | not established | "this burst does not exist in LightBridge technology": a different signal that only the closed E200 firmware decodes | detect-only in open code | [proto17 #50](https://github.com/proto17/dji_droneid/issues/50), [DroneSecurity #43](https://github.com/RUB-SysSec/DroneSecurity/issues/43) |
| DroneID over Wi-Fi (Spark, Mavic Air, Tello, older Wi-Fi models) | 802.11 beacon on the drone's own AP channel | 20 MHz 802.11 | beacon frame | every 200 ms, alternating Flight_Reg_Info and Flight_Purpose (snippet) | n/a | 802.11 OFDM | n/a | vendor IE OUI 26:37:12, subcommands 0x10 (telemetry) / 0x11 (purpose) | **decodable** with a monitor-mode NIC (Kismet parser) | [Kismet dot11_ie_221_dji_droneid.h](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h), [Department 13 white paper](https://github.com/MAVProxyUser/CIAJeepDoors/blob/main/Anatomy-of-DJI-Drone-ID-Implementation1.pdf) (snippet) |

### 1.1 DroneID centre-frequency lists (exact, as published)

| List | Frequencies (MHz) | Source |
|---|---|---|
| proto17, observed on a Mini 2 | 2399.5, 2414.5, 2429.5, 2444.5, 2459.5; 5756.5, 5776.5, 5796.5 | [proto17 README](https://github.com/proto17/dji_droneid) |
| DroneSecurity live receiver hop list (16 entries, 1.3 s dwell each at 50 MSPS) | 2414.5, 2429.502441, 2434.5, 2444.5, 2459.5, 2474.5; 5721.5, 5731.5, 5741.5, 5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5 | [droneid_receiver_live.py:168](https://github.com/RUB-SysSec/DroneSecurity) |
| luyii experimental scan centres (15 MHz raster, explicitly "not universal official frequencies") | 2399.5, 2414.5, 2429.5, 2444.5, 2459.5 | [luyii-code-1](https://github.com/luyii-code-1/dji-ocusync-droneid-research) |
| E200 O4 firmware, auto mode (**unverified round-1**, `o4-firmware-channels`) | 2434.5, 5756.5, 5776.5, 5816.5 | [alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) |
| Papers | "13 frequency points in the 2.4 GHz and 5.8 GHz bands, 12-20 DroneID signals per point per hopping cycle" (snippet) | [TranSIC-Net, Sensors 2025](https://www.mdpi.com/1424-8220/25/20/6488), [Bender arXiv 2207.10795](https://arxiv.org/abs/2207.10795) |

The union spans 2399.5-2474.5 MHz (75 MHz) and 5721.5-5831.5 MHz (110 MHz). Neither fits inside one
56 MHz AD9361 window, so any DroneID watch is a hop schedule, not a single tune. Valid processing
rates are any Fs with Fs/15e3 a power of two: 15.36 MSPS (FFT 1024), 30.72 (2048), 61.44 (4096)
([proto17 get_fft_size.m](https://github.com/proto17/dji_droneid),
[samples2djidroneid](https://github.com/anarkiwi/samples2djidroneid)).

---

## 2. DJI airlink: OcuSync and Lightbridge

| Family / mode | Band / channel plan | Occupied bandwidth | Burst or frame duration | Repetition / hop rate | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| OcuSync 2 downlink, 20 MHz mode | 2.4 and 5.8 GHz | 1201 subcarriers x 15 kHz = ~18 MHz occupied in a 20 MHz channel; native 30.72 MSPS, FFT 2048 | 15 OFDM symbols, ~1 ms, layout RS0 \| D x6 \| RS1 \| D x6 \| RS0 | continuous while linked | not established | QPSK first symbol, then QPSK or higher QAM; CP 144 samples, extended 144+16 on first/middle/last | high, continuous | LTE numerology with Zadoff-Chu reference symbols of length 1201 | **encrypted** (detect and classify only) | [tmbinc/random dji/ocusync2](https://github.com/tmbinc/random/tree/master/dji/ocusync2) |
| OcuSync 2 downlink, 10 MHz mode | as above | 601 subcarriers, FFT 1024, CP 72 (extended 72+8) | ~1 ms | continuous | not established | as above | high | fits whole inside a 20 MSPS E200 stream | encrypted | [tmbinc](https://github.com/tmbinc/random/tree/master/dji/ocusync2), [DJI SDK OcuSyncBandwidth](https://developer.dji.com/iframe/mobile-sdk-doc/android/reference/dji/common/airlink/OcuSyncBandwidth.html) (10 MHz up to 23 Mbps, 20 MHz up to 46 Mbps, snippet) |
| OcuSync 2 video burst (as gated by DroneSecurity) | 2.4 / 5.8 GHz | 18-22 MHz accepted band | 630-665 us | continuous | not established | OFDM | high | same duration window as DroneID but 2x the width, so width alone separates them | encrypted | [DroneSecurity packetizer.py](https://github.com/RUB-SysSec/DroneSecurity) |
| OcuSync C2 uplink (controller to drone) | 2.4 / 5.8 GHz; hops | 1.92 MHz (73 carriers); DroneSecurity accepts 1.2-1.95 MHz | 500-520 us, 7 symbols, ZC at symbols 1 and 7 | frequency hopping; hop rate not documented | 0.52 ms hop-block dwell measured independently by DroneRFa | QPSK OFDM, 15 kHz spacing | not established | narrow 1.9 MHz OFDM burst next to a wide downlink is the OcuSync pair signature | encrypted | [DroneSecurity helpers.py / packetizer.py](https://github.com/RUB-SysSec/DroneSecurity), [tmbinc](https://github.com/tmbinc/random/tree/master/dji/ocusync2), [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| OcuSync narrow modes | 2.4 / 5.8 GHz | 3 MHz and 1.4 MHz, plus a "1.4 MHz-CA (likely collision avoidance aka frequency hopping)" mode | ~1 ms frames | continuous | not established | OFDM, 15 kHz | not established | the 1.4 MHz mode is the fallback under interference | encrypted | [tmbinc](https://github.com/tmbinc/random/tree/master/dji/ocusync2) |
| OcuSync hop blocks, measured (Air 2S, Mini 3 Pro, Mavic 3, M300, M30T) | 2.4 GHz | 2.2 MHz per hop block | 0.52 ms | hopping | 0.52 ms | OFDM | not established | 2.2 MHz / 0.52 ms is the strongest published rule feature for modern DJI | encrypted | [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| OcuSync hop blocks, measured (Mavic Pro, Mini 2, P4P RTK, Avata) | 2.4 GHz | 1.1 MHz per hop block | 0.52 ms | hopping | 0.52 ms | OFDM | not established | half-width variant of the row above | encrypted | [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| OcuSync 3 (Mavic 3 series, Air 2S, Mini 3 Pro) | 2.4 and 5.8 GHz, 10 MHz channel bandwidth with dynamic channel selection (snippet) | 10 MHz claimed; 40 MHz mode exists per the Russian VTX table (section 5.3) | not established | not established | not established | OFDM; possible 30 kHz subcarrier spacing (**unverified round-1**, `ocusync-phy`; cyclic peak measured at 27.99 kHz) | not established | ~28 kHz cyclic frequency versus 250 kHz for Wi-Fi | encrypted | [Zhihu OcuSync guide](https://zhuanlan.zhihu.com/p/667452286) (snippet), [RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker) |
| OcuSync 4 / O4+ airlink | 2.4 GHz, 5.170-5.250 GHz and 5.725-5.850 GHz (Air Unit); ground station also sub-2 GHz, 2.4, 5.2, 5.8 GHz (snippet) | max 60 MHz, selectable 20 or 40 MHz (snippet); Sparrow-2 chipset "up to and beyond 80 MHz" (snippet); one measured main link at 8.92 MHz 99 % BW (Mini 5 Pro) | not established | 5 ms periodicity on a Mini 5 Pro (**unverified round-1**, `ocusync-phy`) | not established | OFDM, adaptive QPSK to 64-QAM | not established | wider than the E200 can capture in one tune above the 20 MHz mode | encrypted | [ithome O4 Air Unit](https://digi.ithome.com/archiver/823/622.htm) (snippet), [Loyalty Drones](https://loyaltydrones.com/dji-o4-transmission-revolutionizing-fpv-drone-technology/) (snippet), [fpvwiki chipset history](https://fpvwiki.co.uk/dji-ocusync-p1-soc) (snippet), [luyii](https://github.com/luyii-code-1/dji-ocusync-droneid-research) |
| Lightbridge 2 video downlink (Phantom 3 Pro/Adv, Phantom 4, Inspire 1, M100, M600) | 32 channels, 2285-2595 MHz (CH1 2.285 GHz to CH32 2.595 GHz); stock firmware confined to 2400-2483 MHz | ~10 MHz per channel | 14 ms video period at 68 % duty (measured) | 12 ms nearest-hop spacing (measured) | 2.2 ms hop-block dwell (measured) | OFDM, adaptive BPSK / QPSK / 16QAM / 64QAM on AD9363 + Cyclone V, later Artosyn AR8003 WiMAX transceiver | 68 % (measured) | 10 MHz OFDM downlink paired with a 1-2 MHz FHSS uplink, unlike OcuSync's 1.4/1.92 MHz LTE-style uplink | detect-only | [PhantomPilots frequency thread](https://phantompilots.com/threads/phantom-3-lightbridge-frequencies.51693/) (snippet), [dji-firmware-tools P3X OFDM wiki](https://github.com/o-gs/dji-firmware-tools/wiki/P3X-OFDM-Receiver-board), [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| Lightbridge 2 control uplink | 2400-2490 MHz | ~1-2 MHz | not established | hopping | not established | not established | not established | narrow hopper alongside the 10 MHz downlink | detect-only | [PhantomPilots](https://phantompilots.com/threads/phantom-3-lightbridge-frequencies.51693/) (snippet) |
| Lightbridge 1 ground unit (2014) | 2405.376-2477.056 MHz | ~2 MHz per channel | not established | hopping | not established | GFSK | not established | narrowband GFSK hopper, not OFDM | detect-only | [FCC ID SS3-201402241](https://fccid.io/SS3-201402241/Test-Report/Test-Report-2219514) (snippet) |
| Avata video link | 5.8 GHz | not established | video period 10 ms | 10 ms | not established | OFDM | 12 % (measured) | very low duty for a video link | encrypted | [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |

**Cross-check worth trusting**: DroneSecurity's C2 burst gate (500-520 us, from reading the
detector code, [packetizer.py](https://github.com/RUB-SysSec/DroneSecurity)) and DroneRFa's measured
OcuSync hop-block dwell (0.52 ms, from an independent 80 MHz capture campaign,
[Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)) agree to within the quantisation of
both. That makes ~0.5 ms the most
reliable single number for a DJI control-link hop.

---

## 3. Other integrated command-and-video links

| Family / mode | Band / channel plan | Occupied bandwidth | Burst or frame duration | Repetition / hop rate | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| Herelink / Herelink Blue, 10 MHz mode | 2409-2459 MHz, 2.4 GHz ISM only | 10 MHz | not established | downlink signal hopping selects the best frequency automatically; fixed-frequency also possible | not established | not established (LTE-like widths) | not established | LTE-numerology widths inside a narrow 2409-2462 MHz plan; receiver sensitivity -99 dBm at 20 MHz | detect-only | [CubePilot wireless-communication.md](https://github.com/CubePilot/cubepilot-docs/blob/master/herelink/herelink-user-guides/wireless-communication.md), [Herelink Blue air-unit spec](https://docs.cubepilot.org/user-guides/cubepilot-ecosystem/cubepilot-partners/union-robotics/herelink-blue/herelink-blue-user-guide/air-unit/air-unit-specifications) (snippet) |
| Herelink, 20 MHz mode | 2412-2462 MHz | 20 MHz | not established | as above | not established | not established | not established | overlaps Wi-Fi channels 1-11 exactly | detect-only | as above |
| Herelink uplink | 2.4 GHz | selectable 1.4 / 10 / 20 MHz; 1.4 MHz preferred under heavy interference | not established | not established | not established | not established | not established | 1.4 MHz option is shared with OcuSync, so width alone will not separate them | detect-only | [CubePilot](https://github.com/CubePilot/cubepilot-docs/blob/master/herelink/herelink-user-guides/wireless-communication.md) |
| Skydroid H16 / H12 / T10 | 2.400-2.483 GHz | not published | not published | FHSS | not published | FHSS, integrated 1080p video | not published | 16 / 12 / 10 channel variants; 20 dBm CE, 23 dBm FCC | detect-only | [FCC ID 2ATGZQZYZH16](https://fccid.io/2ATGZQZYZH16) (snippet), [Skydroid T10 manual](https://manuals.plus/skydroid/t10-2-4ghz-10ch-fhss-transmitter-with-r10-mini-receiver-manual) (snippet) |
| Autel SkyLink 2.0 (EVO II series) | 900 MHz, 2.4 GHz, 5.8 GHz tri-band frequency hopping | not published | not published | hopping | not published | not published | not published | the 900 MHz component is the discriminator against DJI, which has none | detect-only | [Autel SkyLink 3.0 blog](https://www.autelpilot.com/blogs/news/autel-evo-max-4t-autel-skylink-3-0-technology) (snippet) |
| Autel SkyLink 3.0 (EVO Max 4T) | 900 MHz, 2.4, 5.2, 5.8 GHz, auto-switched, 6 antennas | not published | not published | not published | not published | not published; 64 Mbps, 1080p60, <150 ms | not published | four bands including 5.2 GHz | detect-only | [Autel](https://www.autelpilot.com/blogs/news/autel-evo-max-4t-autel-skylink-3-0-technology) (snippet) |
| Skydio X10 Connect SL | 2400-2483.5 MHz and 5150-5850 MHz, 2Tx/4Rx | not published | not published | not published | not published | proprietary point-to-point, AES-256 | not published | 34.7 dBmi at 2.4 GHz, 35.9 dBmi at 5 GHz; a 5G-controlled X10 emits no dedicated C2 link at all | **encrypted** | [Skydio Connect](https://www.skydio.com/connect) (snippet) |
| Parrot Anafi and other Wi-Fi drones | 2.4 GHz default, 5 GHz optional | 802.11 20 MHz (DTS certification) | 802.11 frames | beacons at the AP's beacon interval | n/a | 802.11 OFDM | n/a | certified as a plain DTS device, so attribution is by SSID regex and OUI, not by waveform | beacons **decodable**, payload WPA2-**encrypted** | [FCC ID 2AG6IANAFI](https://fccid.io/2AG6IANAFI) (snippet), [Kismet kismet_uav.conf](https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf) |
| Tello / Ryze | 2.4 GHz open AP | 802.11 20 MHz | 802.11 frames | n/a | n/a | 802.11 | n/a | open AP, control on UDP 8889 and H.264 video on UDP 6038 from 192.168.10.1 | **decodable** with a NIC | [TelloPy](https://github.com/hanyazou/TelloPy), [Kismet uav conf](https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf) |
| Hubsan H107D / H501 | 2.4 GHz A7105 control plus analog VTX 5645-5900 MHz | control <1 MHz | not established | not established | not established | A7105 FSK | not established | toy-class pairing of a narrow 2.4 GHz control link with an analog 5.8 GHz VTX | control detect-only, video **decodable** as analog FM | [DIY-Multiprotocol-TX-Module](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module) |
| Potensic toy link | 2450, 2462, 2458, 2454 MHz (4 fixed channels) | narrow (XN297) | not established | 4100 us packet period | fixed channels, no hopping | XN297 FSK | not established | only four fixed frequencies, no hop sequence | detect-only | [DIY-Multiprotocol-TX-Module](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module) |

### 3.1 Kismet Wi-Fi drone fingerprints (for the NIC-side stage, not the SDR)

| Vendor | OUI | SSID regex | Source |
|---|---|---|---|
| DJI | 60:60:1F | `^Phantom3_.*`, `^Mavic_.*`, `^DJI-MAVIC3.*`, `^DJI-MINI3-Pro-.*`, `^Spark-(?!RC-).*`, `^Spark-RC-.*`, `^TELLO.*`, `^OSMO_.*`, `^Mavic-[0-9A-F]{6}$` | [kismet_uav.conf](https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf) |
| Parrot | A0:14:3D, 90:3A:E6, 90:03:B7, 00:26:7E | `^BebopDrone.*`, `^Bebop2.*`, `^ardrone2.*`, `^SkyController.*`, `^JumpingSumo-.*` | same |
| 3DR Solo | 8A:DC:96 | `^SoloLink_.*` | same |
| Syma | 58:04:54 | `^FPV_WIFI__[0-9A-F]{4}$` | same |
| Attop | six OUIs | `^YD[_-]UFO[_-].*` | same |

---

## 4. RC control and telemetry links

### 4.1 ExpressLRS, every packet rate

All rows read from `src/src/common.cpp` (commit 9ff3fa4, 2026-09-04) of
[ExpressLRS/ExpressLRS](https://github.com/ExpressLRS/ExpressLRS). "Dwell" is
`FHSShopInterval x interval`, "duty" is `TOA / interval`; both are derived arithmetic on the two
verified tables `ExpressLRS_AirRateConfig` and `ExpressLRS_AirRateRFperf`.

#### SX1280 targets (2.4 GHz)

| Rate | Band / channel plan | Occupied bandwidth | Burst duration (TOA) | Repetition | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| FLRC F1000 | ISM2G4 / CE_LBT, 80 ch, 2400.4-2479.4 MHz | 0.6 MHz | 389 us | 1000 us | 2 ms (hop every 2) | FLRC, BR 0.65 Mb/s, BT 1, CR 1/2, 32-bit UID-derived sync word, 3-byte CRC | 38.9 % | shortest burst of any ELRS mode | **detect-only** (no open FLRC demodulator exists) | common.cpp |
| FLRC F500 | as above | 0.6 MHz | 389 us | 2000 us | 4 ms | as above | 19.5 % | lowest duty cycle of the FLRC set | detect-only | common.cpp |
| FLRC D500 (DVDA x2) | as above | 0.6 MHz | 389 us | 1000 us | 2 ms | as above, each packet sent twice | 38.9 % | duplicate packets back to back | detect-only | common.cpp |
| FLRC D250 (DVDA x4) | as above | 0.6 MHz | 389 us | 1000 us | 2 ms | as above, sent four times | 38.9 % | four identical packets per control frame | detect-only | common.cpp |
| LoRa 500 Hz | as above | 812.5 kHz (BW code 0x18, "800") | 1507 us | 2000 us | 8 ms (hop every 4) | SF5, CR_LI 4/6, preamble 12, implicit header, no LoRa CRC, IQ inverted when UID[5] is odd | 75.4 % | SF5 chirps at 812.5 kHz | **detect-only** *(verified: verdict 3, ELRS decodability)* | common.cpp |
| LoRa 333 Hz Full | as above | 812.5 kHz | 2374 us | 3003 us | 12.0 ms | SF5, CR_LI 4/8, 13-byte OTA8 payload | 79.1 % | 3003 us interval is unique | detect-only | common.cpp |
| LoRa 250 Hz | as above | 812.5 kHz | 3300 us | 4000 us | 16 ms | SF6, CR_LI 4/8, preamble 14 | 82.5 % | preamble 14 instead of 12 | detect-only | common.cpp |
| LoRa 150 Hz | as above | 812.5 kHz | 5871 us | 6666 us | 26.7 ms | SF7, CR_LI 4/8 | 88.1 % | 6666 us interval collides with Crossfire 150 Hz and Futaba S-FHSS timing; modulation must break the tie | detect-only | common.cpp |
| LoRa 100 Hz Full | as above | 812.5 kHz | 7605 us | 10000 us | 40 ms | SF7, CR_LI 4/8, OTA8 | 76.1 % | 8-channel payload at 100 Hz | detect-only | common.cpp |
| LoRa 50 Hz | as above | 812.5 kHz | 10798 us | 20000 us | 40 ms (hop every 2) | SF8, CR_LI 4/8 | 54.0 % | longest 2.4 GHz burst | detect-only | common.cpp |

#### SX127x targets (sub-GHz)

| Rate | Band / channel plan | Occupied bandwidth | Burst duration (TOA) | Repetition | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| 200 Hz | one of the domains in 4.2 | 500 kHz | 4380 us | 5000 us | 20 ms (hop every 4) | SF6, CR 4/7, preamble 8, implicit header, hardware CRC off, sync word 0x12 | 87.6 % | most common sub-GHz rate; SF6 needs validation against real hardware | **decodable-candidate** (gr-lora_sdr supports the parameters; never demonstrated end to end) *(verified: verdict 3)* | common.cpp |
| 100 Hz Full | as above | 500 kHz | 6690 us | 10000 us | 40 ms | SF6, CR 4/8, OTA8 | 66.9 % | 13-byte OTA payload | decodable-candidate | common.cpp |
| 100 Hz | as above | 500 kHz | 8770 us | 10000 us | 40 ms | SF7, CR 4/7 | 87.7 % | SF7 at 500 kHz | decodable-candidate | common.cpp |
| 50 Hz | as above | 500 kHz | 18560 us | 20000 us | 80 ms | SF8, CR 4/7, preamble 10 | 92.8 % | highest duty of any ELRS mode | decodable-candidate | common.cpp |
| 25 Hz | as above | 500 kHz | 29950 us | 40000 us | 80 ms (hop every 2) | SF9, CR 4/7, preamble 10 | 74.9 % | ~30 ms burst is unmistakable | decodable-candidate | common.cpp |
| 50 Hz DVDA (x4) | as above | 500 kHz | 4380 us | 5000 us | 10 ms | SF6, CR 4/7, four sends | 87.6 % | SF6 timing of 200 Hz but only 50 Hz of unique control data | decodable-candidate | common.cpp |

#### LR1121 / LR2021 targets (extra rates not present on SX127x/SX1280)

| Rate | Band | Occupied bandwidth | Burst duration | Repetition | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| FSK 900 1000 Hz 8CH | sub-GHz domain | 467 kHz (LR2021: 476 kHz) | 658 us | 1000 us | 2 ms | GFSK 300 kb/s, fdev 100 kHz, 16-bit sync = UID[5],UID[4], SX127x-compatible whitening, CRC off | 65.8 % | a sub-GHz ELRS mode that is not LoRa at all | detect-only (needs a new GFSK demodulator) | common.cpp, [LR1121.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/LR1121Driver/LR1121.cpp) |
| LoRa 900 250 Hz | sub-GHz | 500 kHz | 3216 us | 4000 us | 16 ms | SF5, CR 4/8 | 80.4 % | SX126x-style SF5, which gr-lora_sdr states is not compatible with its SF5 | detect-only | common.cpp, [gr-lora_sdr README](https://github.com/tapparelj/gr-lora_sdr) |
| LoRa 900 200 Hz 8CH | sub-GHz | 500 kHz | 4240 us | 5000 us | 20 ms | SF5, CR 4/7, OTA8 | 84.8 % | same SF5 caveat | detect-only | common.cpp |
| GFSK 2G4 1000 / 500 DVDA / 250 DVDA | ISM2G4 | 467 kHz (LR2021: 476 kHz) | 690 us | 1000 us | 2 ms | GFSK 300 kb/s, fdev 100 kHz | 69.0 % | narrowband GFSK inside the 2.4 GHz ELRS grid | detect-only | common.cpp |
| LoRa dual 150 Hz | sub-GHz **and** 2.4 GHz simultaneously | 500 kHz + 812.5 kHz | 5871 us | 6666 us | 26.7 ms | SF6 BW500 CR 4/8 (900) plus SF7 BW800 CR_LI 4/6 (2.4) | 88.1 % | two synchronised bursts in two bands is a unique signature | detect-only | common.cpp |
| LoRa dual 100 Hz 8CH | as above | 500 kHz + 812.5 kHz | 7456 us | 10000 us | 40 ms | SF6 BW500 CR 4/8 plus SF7 BW800 CR_LI 4/8 | 74.6 % | as above | detect-only | common.cpp |

Sync-packet behaviour, useful because it makes a powered-up handset detectable before the aircraft
flies: `SyncPktIntervalDisconnected` is 3-11 ms on 2.4 GHz rates (0 for the 2.4 GHz 50 Hz rate) and
600 ms on all sub-GHz LoRa rates; `SyncPktIntervalConnected` is 5000 ms on every rate
([common.cpp `ExpressLRS_AirRateRFperf`](https://github.com/ExpressLRS/ExpressLRS)). Sync packets
carry `fhssIndex`, `nonce`, `rfRateEnum`, `tlmRatio`, UID4 and UID5 in clear text
([OTA.h](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/OTA/OTA.h)), and the NCC Group
advisory confirms that these leak most of the binding UID
([NCC Group 2022](https://research.nccgroup.com/2022/06/30/technical-advisory-expresslrs-vulnerabilities-allow-for-hijack-of-control-link/), snippet).
There is no encryption anywhere in `src/src` or `src/lib/OTA` *(verified: verdict 3)*.

### 4.2 ExpressLRS regulatory domains (exact frequency plans)

Start, stop and channel count are literals from
[`src/lib/FHSS/FHSS.cpp`](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/FHSS/FHSS.cpp);
spacing and span are derived as `(stop - start) / (count - 1)`, the formula the same file uses for
`freq_spread`.

| Domain | Range (MHz) | Channels | Spacing (derived) | Span (derived) | Sync channel (index count/2, derived) | Fits in one 56 MHz E200 window? |
|---|---|---|---|---|---|---|
| AU915 | 915.500-926.900 | 20 | 600 kHz | 11.4 MHz | index 10 = 921.5 MHz | yes |
| FCC915 | 903.500-926.900 | 40 | 600 kHz | 23.4 MHz | index 20 = 915.5 MHz | yes (needs ~25 MSPS, above the 20 MSPS host tier) |
| EU868 | 863.275-869.575 | 13 | 525 kHz | 6.3 MHz | index 6 = 866.425 MHz | yes |
| IN866 | 865.375-866.950 | 4 | 525 kHz | 1.575 MHz | index 2 = 866.425 MHz | yes |
| AU433 | 433.420-434.420 | 3 | 500 kHz | 1.0 MHz | index 1 = 433.920 MHz | yes |
| EU433 | 433.100-434.450 | 3 | 675 kHz | 1.35 MHz | index 1 = 433.775 MHz | yes |
| US433 | 433.250-438.000 | 8 | 678.6 kHz | 4.75 MHz | index 4 = 435.964 MHz | yes |
| US433W | 423.500-438.000 | 20 | 763.2 kHz | 14.5 MHz | index 10 = 431.132 MHz | yes |
| TH920 | 920.500-924.700 | 8 | 600 kHz | 4.2 MHz | index 4 = 922.9 MHz | yes |
| ISM2G4 / CE_LBT | 2400.400-2479.400 | 80 | 1.000 MHz | 79.0 MHz | index 40 = 2440.4 MHz | **no** (79 MHz > 56 MHz) |

The hop sequence is a length-256 array truncated to a multiple of the channel count, with the sync
channel forced at every multiple of the count and the remainder shuffled by a UID-seeded LCG
(`0x343FD`, `0x269EC3`), so a whole-band capture removes any need to know the binding phrase
([FHSS.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/FHSS/FHSS.cpp),
[GNU_Radio_ExpressLRS FHSS block](https://github.com/Diamond-D0gs/GNU_Radio_ExpressLRS)).

Battlefield forks abandon these tables entirely: MilELRS exposes `CUSTOM_FREQ=740,760,0` style
user-defined 20 MHz sub-bands, `CUSTOM_FREQ2` for a second band, `MULTI_BAND` for up to three
simultaneous TX-RX pairs, and separate telemetry frequencies; the underlying modules cover
360-560 and 720-1020 MHz (SX1276/78), 2100-2700 MHz (SX1280) and 150-2800 MHz (LR1121)
([techuav mirror of the MilELRS manual](https://github.com/techuav/techuav.github.io), verified
local read). Ukrainian and Russian detector vendors advertise ELRS coverage at 720-915 MHz and
700-1020 MHz ([militarnyi 2025](https://militarnyi.com/uk/special-projects/yak-vybraty-detektor-droniv-oglyad-modelej-i-klyuchovi-kryteriyi-vyboru/),
snippet). An ELRS detector must therefore key on the chirp and timing signature, not on a channel
table.

### 4.3 Other RC and telemetry links

| Family / mode | Band / channel plan | Occupied bandwidth | Burst or frame duration | Repetition / hop rate | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| TBS Crossfire, 150 Hz | 260.01 kHz grid from 860 MHz (EU) or 900 MHz (US); TX uses channels 0-49, RX replies exactly 50 channels up (50-99) | ~0.17 MHz on-air (85 kBaud, 42.3 kHz deviation); 260 kHz grid pitch | uplink 23 bytes (0x17), downlink 13 bytes (0x0D); ~2.2 ms uplink derived at 85 kb/s | 6666.67 us slot (learned schedule 6676 us) | one slot per channel, 150-entry hop sequence | 2-FSK, 85 kBaud, 42.3 kHz deviation (blog: 42.48 kHz, 85.1 kBaud) | ~33 % uplink (derived) | fixed 6.667 ms slot with a 150-slot sequence and a paired uplink/downlink channel offset of exactly 50 | **decodable** (unencrypted, CRC brute-forceable) | [ESP32_CRSFSniffer](https://github.com/g3gg0/ESP32_CRSFSniffer) (verified: `cfgBitrate=85000`, `cfgFreqDev=42300`, `cfgChanDist=260010`, `cfgStartFreq=860000000`, `packet_ms=6666.67`, `hoppingSequence[150]`), [g3gg0.de analysis](https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire/) (snippet), [Hackaday summary](https://hackaday.com/2022/02/20/reverse-engineering-a-900-mhz-rc-transmitter-and-receiver/) (snippet) |
| TBS Crossfire, 50 Hz | as above | LoRa; exact SF/BW/CR not recovered (the only source, g3gg0.de, was unreachable) | not established | not established | not established | LoRa on SX1272 | not established | only the 50 Hz mode is LoRa; 150 Hz is plain FSK | decodable in principle, parameters missing | [g3gg0.de](https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire/) (snippet) |
| TBS Tracer (2.4 GHz) | 2.4 GHz | not established | not established | 250 Hz mode, ~3 ms (round-1 note, unverified) | not established | chipset and modulation not verified (FLRC suspected) | not established | no primary source found in this sweep | detect-only | round-1 gap, see Gaps |
| FrSky D8 (ACCST) | 2.4 GHz, 47 hop channels generated as `(i*0x1E)%0xEB` | 135 kHz CC2500 RX filter | not established | 9000 us | one packet per channel | 2-FSK, 31.0 kb/s, 31.7 kHz deviation | not established | 47 channels at a 9 ms period | **decodable** in principle (fully specified, unencrypted); no SDR decoder exists | [DIY-Multiprotocol-TX-Module FrSkyD_cc2500.ino](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module) |
| FrSky D16 (ACCST) | 2.4 GHz, 47 channels stepped by `chanskip` | 232 kHz filter | not established | 9000 us | one packet per channel | 2-FSK, 70.0 kb/s (X2 v2.1 77 kb/s; EU-LBT set 100 kb/s), 57 kHz deviation | not established | same 47/9 ms structure as D8 but 2x the symbol rate | decodable in principle, no SDR decoder | [FrSkyX_cc2500.ino](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module) |
| FrSky R9 (900 MHz) | 43 channels (FCC), 29 (FLEX), 19 (EU) | 500 kHz | not established | ~20 ms (`return 20000-460`) | manual hopping | LoRa on SX1276, BW 500 kHz, SF6, CR 4/5 | not established | collides with ELRS 900 in modulation; separated by CR (4/5 vs 4/7-4/8) and hop-set size | decodable-candidate (same PHY class as ELRS sub-GHz) | [FrSkyR9_sx1276.ino](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module) |
| FrSky ACCESS | 900 MHz and 2.4 GHz, up to 24 channels | not published | not published | not published | not published | proprietary | not published | explicitly encrypted to prevent the reverse engineering that hit ACCST; absent from the open Multiprotocol module | **encrypted** | [Oscar Liang, ACCESS](https://oscarliang.com/frsky-access-protocol/) (snippet) |
| FrSky X20 handset (measured) | 915 MHz or 2.4 GHz | 0.42 MHz hop block | 2.8 ms | hopping | 2.8 ms | not stated | not stated | narrowest measured RC hop block in DroneRFa | detect-only | [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| Spektrum DSM2 | 2.4 GHz, 2 channels derived from the transmitter GUID | ~1 MHz | not established | 11 ms or 22 ms frames; DSM2_SFC period 16.5 ms; second channel written 4.01 ms after the first | 2 channels only | GFSK 1 Mb/s with DSSS on CYRF6936 | not established | only two hop channels | **decodable** (gr-dsmx-rc) | [DSM_cyrf6936.ino](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module), [gr-dsmx-rc](https://github.com/lscardoso/gr-dsmx-rc), [GRCon paper](https://pubs.gnuradio.org/index.php/grcon/article/view/97) (snippet) |
| Spektrum DSMX | 2.4 GHz, 23-channel table derived from the GUID | ~1 MHz | not established | 11 ms or 22 ms frames | one packet per channel | GFSK 1 Mb/s DSSS, CYRF6936 SOP/PN codes | not established | DSSS de-spreading identifies the emitter by manufacturer ID | **decodable** (gr-dsmx-rc: SOP/PN correlation, de-spreading, hop following, MFG-ID identification; 4 MS/s example flowgraph, GNU Radio 3.7-era) | [gr-dsmx-rc](https://github.com/lscardoso/gr-dsmx-rc) |
| Flysky AFHDS | 2.4 GHz, 16 of 160 x 500 kHz channels | 500 kHz channelisation | not established | 1510 us (variants 1460-1533 us) | one packet per channel | A7105 FSK | not established | ~1.5 ms period is the fastest of the legacy 2.4 GHz family | decodable in principle, no SDR decoder | [DIY-Multiprotocol-TX-Module](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module), [Roger Writes #3](https://fareham.org/rw3-afhds2a.shtml) (snippet) |
| Flysky AFHDS-2A | 2.4 GHz, 16 hop channels from 160 x 500 kHz slots (2400-2483 MHz), channels sent to the RX at bind time | 500 kHz | 38-byte TX / 37-byte RX packet; ~0.61 ms derived at 500 kb/s | 3850 us | one packet per channel; the TX listens one channel down for telemetry in the remainder of the period | GFSK 500 kb/s, 16-bit payload CRC, 32-bit packet ID, FEC (4 data bits as 7) | ~16 % (derived) | 3.85 ms period with a telemetry listen slot one channel below | decodable in principle, no SDR decoder | [AFHDS2A_a7105.ino](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module), [Roger Writes #3](https://fareham.org/rw3-afhds2a.shtml) (snippet) |
| Flysky AFHDS 3 | 2.4 GHz | not published | not published | not published | not published | not published | not published | no public reverse engineering found | detect-only | round-1 gap |
| Futaba S-FHSS | 2.4 GHz, 30 RF channels; CC2500 spacing 249.938 kHz with every 6th channel used, i.e. 1.5 MHz effective grid from 2399.9996 MHz | 232 kHz filter | 13-byte packet + 4 preamble bytes; ~1.06 ms derived at 128,143 bps | 6800 us | one packet per channel | 2-FSK, 128,143 bps | ~16 % (derived) | 1.5 MHz channel grid is unique among 2.4 GHz RC links | decodable in principle, no SDR decoder | [Futaba_cc2500.ino](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module) |
| Futaba, measured dwell | 2.40-2.45 GHz | not stated | not stated | hop sequence observed as f1 f1 f2 f3 f3 f4 | 1.44 ms | not stated | not stated | dwell recovered from the autocorrelation of the STFT | detect-only | [Kaplan et al., VTC 2020](https://arxiv.org/abs/2003.03614) (snippet) |
| Futaba T14SG (measured) | 2.4 GHz | 2.0 MHz hop block | 2.0 ms | hopping | 2.0 ms | not stated | not stated | wider hop block than S-FHSS's 232 kHz filter suggests, so the measurement is of the occupied hop block, not the modulation bandwidth | detect-only | [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| Futaba FASST / T-FHSS | 2.4 GHz | not published | not published | not published | not published | proprietary | not published | no public reverse engineering | detect-only | round-1 gap |
| Graupner HoTT | 2.4 GHz, 75 RF channels | 542 kHz filter | 50-byte TX / 22-byte RX; ~1.6 ms derived at 249.9 kb/s | 10000 us | one packet per channel | MSK with FEC, 249.9 kb/s, 32-bit sync word | ~16 % (derived) | 75 channels is the largest legacy 2.4 GHz hop set | decodable in principle, no SDR decoder | [HOTT_cc2500.ino](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module) |
| RadioLink AT9S (measured) | 2.4 GHz | 5.0 MHz hop block | 2.1 ms | hopping | 2.1 ms | not stated | not stated | widest RC hop block measured in DroneRFa | detect-only | [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| Yunzhuo T12 (measured) | 2.4 GHz | 1.7 MHz hop block | 4.6 ms | hopping | 4.6 ms | not stated | not stated | longest measured RC dwell in DroneRFa | detect-only | [DroneRFa Table 4](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| SiK / 3DR / Holybro / RFD telemetry | 433.05-434.79 MHz (10 ch), 470-471 MHz (10), 868-870 MHz (10), 915-928 MHz (up to 50); spacing = (fmax-fmin)/(N+2) | air rates 2, 4, 8, 16, 19, 24, 32, 48, 64, 96, 128, 192, 250 kb/s (default 64) | TDM transmit window, MAX_WINDOW 131 ms | frequency changes at the start and end of every transmit window | one TDM window | GFSK; optional Golay 23/12 ECC; AES optional in newer firmware | not established | NetID-seeded hop shuffle, MAVLink in clear unless AES is enabled | **decodable** (sikw00f demonstrates NetID harvesting and plaintext MAVLink capture, using a modified SiK radio rather than an SDR) | [ArduPilot/SiK](https://github.com/ArduPilot/SiK), [sikw00f](https://github.com/nicholasaleks/sikw00f) |
| PrivacyLRS | same as ELRS | same as ELRS | same as ELRS | same as ELRS | same as ELRS | ELRS PHY wrapped in ChaCha20 | same as ELRS | identical on-air signature to ELRS, but the payload is encrypted, so the classifier must distinguish "ELRS-like PHY detected" from "payload decoded" | **encrypted** | [PrivacyLRS](https://github.com/sensei-hacker/PrivacyLRS) (snippet) |

---

## 5. Video links

### 5.1 Analog FPV

The occupied-bandwidth question was contested and went through the verification pass. The corrected
position *(verified: verdict 5, analog FPV bandwidth)*:

* Analog 5.8 GHz FPV is wideband FM of a 1 Vpp composite video signal (NTSC 4.2 MHz, PAL about
  5-5.5 MHz including chroma), plus, on RTC6705-class VTX, two FM audio subcarriers at 6.0 and
  6.5 MHz sitting 25-30 dB below the video carrier.
* The RTC6705 datasheet specifies **no** main-carrier video deviation, so the widely quoted "5 MHz
  peak deviation" is a decoder scale constant (`fpvdec --dev` default), not a chipset specification.
* One hobbyist measurement on a 25 mW whoop VTX found less than 0.3 % of energy outside +/-4.5 MHz,
  which is why the `fpvdec` default sample rate is 10 MSPS. That measurement is unreproduced and
  internally in tension with a true +/-5 MHz swing, which would put roughly 7 % of line time (sync
  tips) outside +/-4.5 MHz.
* The commonly quoted "20-27 MHz" is neither channel spacing nor occupied bandwidth: 19-20 MHz is
  the A/B/E/F channel spacing, 37 MHz is Raceband spacing, and 23-27 MHz is a Carson-rule estimate
  2 x (deviation + f_max) that counts the audio subcarriers. Real 99 % bandwidth lies between about
  9 MHz (video only, low index) and about 20 MHz (Carson, video only), with faint subcarrier lines
  out to +/-11.5 MHz.

Sources for the five points above: [5G8atv config.hpp and README](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder),
[lukeswitz/fpv-sdr](https://github.com/lukeswitz/fpv-sdr),
[RTC6705 datasheet shipped in OpenVTx](https://github.com/OpenVTx/OpenVTx/blob/master/docs/RTC6705-RichWave.pdf),
[rx5808-pro-diversity channel table](https://github.com/sheaivey/rx5808-pro-diversity),
[Oscar Liang on FPV channels](https://oscarliang.com/fpv-channels/) (snippet).

| Family / mode | Band / channel plan | Occupied bandwidth | Burst or frame duration | Repetition / hop rate | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| Analog FPV, 5.8 GHz | 40-channel A/B/E/F/R table plus L/5.3 band (section 5.2) | ~9-10 MHz 99 % core; Carson estimate 18-27 MHz depending on whether the audio subcarriers count; channel spacing 19-20 MHz (A/B/E/F), 37 MHz (Raceband, L) | continuous | none, fixed channel | fixed (VTX are 2-3 MHz off at power-up and drift ~1 MHz in the first minutes) | wideband FM of composite video, plus optional FM audio subcarriers at 6.0 and 6.5 MHz at -25 to -30 dBc | 100 % | noise-like FM hump with no discrete carrier; envelope coefficient of variation 0.3-0.56 versus 1.2-3.2 for Wi-Fi/OFDM | **decodable** (NTSC colour demonstrated; PAL colour is an open gap in all open decoders) | [5G8atv-rf-hackrf-decoder](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder), [lukeswitz/fpv-sdr](https://github.com/lukeswitz/fpv-sdr), [RTC6705 datasheet in OpenVTx](https://github.com/OpenVTx/OpenVTx/blob/master/docs/RTC6705-RichWave.pdf) *(verified: verdict 5)* |
| Analog FPV, 1.2 / 1.3 GHz | channels 1080-1360 MHz; 1256 and 1280 MHz most popular; US legal subset 1258 and 1280 MHz only; hardware spans 1060-1380 MHz | same FM-ATV baseband as 5.8 GHz; no measured width found | continuous | none | fixed | wideband FM | 100 % | a 20 MHz window at 1268 MHz catches both US channels at once | decodable (same demodulator) | [Oscar Liang 1.2 GHz guide](https://oscarliang.com/1-2ghz-fpv-guide/) (snippet) |
| Analog FPV, other bands in frontline use | 460-600, 910-1360, 1405-1680, 2290-2510, 3200-3700, 3700-4150, 4500-4685, 4867-6184, 6110-7210 MHz | as above | continuous | none | fixed | wideband FM | 100 % | frontline VTX now sit well outside the classic 5.8 GHz plan; 6.2 GHz and above is beyond the AD9361's 6 GHz ceiling | decodable within 70 MHz-6 GHz only | [techuav mirror, "Таблица частот VTX"](https://github.com/techuav/techuav.github.io/blob/main/docs/%D0%9F%D0%9B%D0%90%D0%A2%D0%A4%D0%9E%D0%A0%D0%9C%D0%90_FPV/%D0%92%D0%B8%D0%B4%D0%B5%D0%BE%D1%81%D0%B2%D1%8F%D0%B7%D1%8C/%D0%A2%D0%B0%D0%B1%D0%BB%D0%B8%D1%86%D0%B0_%D1%87%D0%B0%D1%81%D1%82%D0%BE%D1%82_VTX..html) (verified local read) |

### 5.2 Analog 5.8 GHz channel tables (exact)

From [rx5808-pro-diversity channels.cpp](https://github.com/sheaivey/rx5808-pro-diversity/blob/master/src/rx5808-pro-diversity/channels.cpp)
and [5G8atv](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder), which agree entry for entry
(both verified):

| Band | CH1 | CH2 | CH3 | CH4 | CH5 | CH6 | CH7 | CH8 |
|---|---|---|---|---|---|---|---|---|
| A | 5865 | 5845 | 5825 | 5805 | 5785 | 5765 | 5745 | 5725 |
| B | 5733 | 5752 | 5771 | 5790 | 5809 | 5828 | 5847 | 5866 |
| E | 5705 | 5685 | 5665 | 5645 | 5885 | 5905 | 5925 | 5945 |
| F (Fatshark / Airwave) | 5740 | 5760 | 5780 | 5800 | 5820 | 5840 | 5860 | 5880 |
| R (Raceband) | 5658 | 5695 | 5732 | 5769 | 5806 | 5843 | 5880 | 5917 |
| L / D (low band, `USE_LBAND`) | 5362 | 5399 | 5436 | 5473 | 5510 | 5547 | 5584 | 5621 |

Additional bands found in E200-relevant tooling:

| Band | Frequencies (MHz) | Source |
|---|---|---|
| DJI analog / digital V1 band, "D" in fpv-sdr | 5660, 5695, 5735, 5770, 5805, 5878, 5914, 5839 | [fpv-sdr fpv_scanner.sh](https://github.com/lukeswitz/fpv-sdr) (verified), corroborated by the [techuav VTX table](https://github.com/techuav/techuav.github.io) row "DJI V1 25 Mbs" |
| U | 5325, 5348, 5366, 5384, 5402, 5420, 5438, 5456 | [techuav VTX table](https://github.com/techuav/techuav.github.io) |
| O | 5474, 5492, 5510, 5528, 5546, 5564, 5582, 5600 | same |
| L (extended) | 5333, 5373, 5413, 5453, 5493, 5533, 5573, 5613 | same |
| H | 5653, 5693, 5733, 5773, 5813, 5853, 5893, 5933 | same |
| X | 4990, 5020, 5050, 5080, 5110, 5140, 5170, 5200 | same |
| J | 4867, 4884, 4921, 4958, 4995, 5032, 5069, 5099 | same |
| K | 5960, 5980, 6000, 6020, 6040, 6060, 6080, 6100 | same |
| Z | 6002, 6028, 6054, 6080, 6106, 6132, 6158, 6184 | same |

`fpv-sdr`'s own scanner table holds 62 entries with 53 unique frequencies between 5362 and 5945 MHz
(the README says "64 channels across 8 bands"); a 40 MSPS detection sweep needs 16 chunks to cover
it, a 20 MSPS sweep needs 24 ([fpv-sdr deep read, verified](https://github.com/lukeswitz/fpv-sdr)).
An RX5808-class scanner project extends this to 72 frequencies across bands A, B, E, F, R, U, O, L
and H ([passive_drone_detection-PDD](https://github.com/Bit101-git/passive_drone_detection-PDD)).

### 5.3 Digital video links

| Family / mode | Band / channel plan | Occupied bandwidth | Burst or frame duration | Repetition / hop rate | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| HDZero | R1-R8 5658/5695/5732/5769/5806/5843/5880/5917, E1 5705, F1 5740, F2 5760, F4 5800, L1-L8 5362/5399/5436/5473/5510/5547/5584/5621 MHz (20 discrete channels) | "roughly 27 MHz" (vendor page, snippet); two on-air modes Wide and Narrow, widths not published | continuous | none, fixed channel | fixed | Divimath DM5680 OFDM baseband, DM6300 VTX radio, DM6302 goggle RX; PHY closed | 100 % | 27 MHz on a fixed table entry, far wider than analog's ~9-10 MHz core; Narrow mode is used only for 540p60 | **detect-only** (no open PHY) | [hdzero-vtx common.h / dm6300.c](https://github.com/hd-zero/hdzero-vtx), [hdzero-goggle](https://github.com/hd-zero/hdzero-goggle), [hdzero-docs](https://github.com/hd-zero/hdzero-docs), [GetFPV HDZero page](https://www.getfpv.com/fpv/hd-fpv/hdzero-digital-hd-fpv-system.html) (snippet, 27 MHz) |
| HDZero, Russian-market channel rows | FCC 5668, 5695, 5732, 5769, 5806, 5843, 5880, 5917; CE 5732, 5769, 5806, 5843 | as above | continuous | none | fixed | as above | 100 % | **contested**: the first FCC entry is 5668 MHz here but 5658 MHz in the HDZero firmware; treat the firmware value as authoritative and the table as a transcription | detect-only | [techuav VTX table](https://github.com/techuav/techuav.github.io) versus [hdzero-vtx common.h](https://github.com/hd-zero/hdzero-vtx) |
| Walksnail Avatar | 8 channels on 5.8 GHz; channels 1-3 overlap the analog band, 7-8 cleanest at busy fields; spec-sheet band 5.15-5.85 GHz | not published; expect roughly 20 MHz OFDM, unmeasured | continuous | none | fixed | not published; H.265, 1080p60, minimum latency 22 ms, 25 mW-2 W | 100 % | no open PHY or decoder exists anywhere on GitHub | detect-only | [FCC ID 2A78Z-AVATAR](https://fccid.io/2A78Z-AVATAR) (snippet, report blocked) |
| Walksnail, Russian-market channel rows | race mode 5658/5695/5732/5769/5806/5843/5880/5917; 25 Mbps 5658/5695/5732/5769/5805/5878/5914/5839; 50 Mbps 5695/5770/5878/5839 | as above | continuous | none | fixed | as above | 100 % | the 50 Mbps row uses only four channels, implying a wider carrier | detect-only | [techuav VTX table](https://github.com/techuav/techuav.github.io) |
| DJI digital FPV V1 | 25 Mbps 5660/5695/5735/5770/5805/5878/5914/5839; 50 Mbps 5695/5770/5878/5839 | not published | continuous | none | fixed | OFDM | 100 % | the 50 Mbps mode drops to four channels | encrypted | [techuav VTX table](https://github.com/techuav/techuav.github.io), corroborated by [fpv-sdr](https://github.com/lukeswitz/fpv-sdr) |
| DJI O3 air unit | 10/20 MHz: 5669, 5705, 5768, 5804, 5839, 5876, 5912 MHz; 40 MHz: 5677, 5794, 5902 MHz | 10, 20 or 40 MHz | not established | none while locked | fixed or dynamically selected | OFDM | 100 % | 40 MHz mode exceeds the 20 MSPS host stream, so only partial-band energy and edge features are available | encrypted | [techuav VTX table](https://github.com/techuav/techuav.github.io) |
| wfb-ng (used by OpenIPC) | default Wi-Fi channel 165 = 5825 MHz; OpenIPC recommends "channels 60 and above" on RTL8812AU | 20 MHz default, 40 MHz option | 802.11 data frames | continuous | fixed | 802.11n HT, default MCS 1, STBC 1, LDPC 1, video FEC 8/12 | high | frame control 0x08 0x01, RA ff:ff:ff:ff:ff:ff, TA/SA `57:42:<link_id:3><radio_port:1>`; BPF matches `ether[0x0a:2]==0x5742` | **encrypted** (ChaCha20-Poly1305 on every payload); attribution by MAC prefix only | [svpcom/wfb-ng](https://github.com/svpcom/wfb-ng), [WFB-NG transport draft](https://github.com/svpcom/wfb-ng/blob/master/doc/wfb-ng-std-draft.md), [OpenIPC wiki fpv.md](https://github.com/OpenIPC/wiki/blob/master/en/fpv.md) |
| OpenHD | 2.4 GHz list includes non-standard 2312, 2332, 2352, 2372, 2392, 2492, 2512, 2612, 2692, 2712 MHz plus channels 1-14; 5 GHz list runs 5080 to 6085 MHz including 5885, 5905, 5925, 5945, 5965, 5985, 6005, 6025, 6045, 6065, 6085 MHz (the source code labels several of these "illegal") | 10, 20 or 40 MHz only | 802.11 frames | continuous | fixed | raw 802.11 injection, HT/VHT capable | high | MAC `13:22:33:44:55:<port>`, optional 0xb4 RTS-type frames; a sweep must cover 2.3-2.7 and 5.08-6.09 GHz, not just regulatory Wi-Fi | detect-only / attribution by MAC | [OpenHD](https://github.com/OpenHD/OpenHD), [OpenHD/wifibroadcast](https://github.com/OpenHD/wifibroadcast) |
| DroneBridge | Wi-Fi channels | 20 MHz | 802.11 frames | continuous | fixed | legacy-rate injection (radiotap rate byte, frame control 0x08 0x00 data or 0xb4 0x00 RTS) | high | legacy rates put DroneBridge within reach of gr-ieee802-11 on the E200, unlike HT-rate wfb-ng/OpenHD frames | **decodable** at the 802.11 layer | [DroneBridge](https://github.com/DroneBridge/DroneBridge), [gr-ieee802-11](https://github.com/bastibl/gr-ieee802-11) |
| EZ-WifiBroadcast | 2.3/2.4/2.5 GHz and 5.2-5.8 GHz | 20 MHz | 802.11 frames | continuous | fixed | raw 802.11 | high | first-generation wifibroadcast; up to 1080p30 at 12 Mbit/s, ~125 ms glass to glass | detect-only | [EZ-WifiBroadcast](https://github.com/rodizio1/EZ-WifiBroadcast) |
| RubyFPV | 433 MHz, 868/915 MHz, 2.3, 2.4, 2.5 and 5.8 GHz, multiple redundant links | not published | 802.11 frames | continuous | fixed | raw 802.11 | high | multi-band redundancy; README says encryption is "temporarily disabled" | detect-only | [RubyFPV](https://github.com/RubyFPV/RubyFPV) |
| OpenIPC serial units (frontline) | RTL8812 limits them to 4900-5990 MHz today; channel bandwidth modified so it "can even be 10 MHz"; same system can run on 3.55-3.7 GHz or 5.925-7.125 GHz | 10, 20 or 40 MHz | 802.11 frames | continuous | fixed | raw 802.11 | high | a 10 MHz-wide 802.11 link at a non-standard centre is easy to miss with a channel-table scanner | encrypted (wfb-ng keys) | [techuav mirror](https://github.com/techuav/techuav.github.io) (verified local read) |

---

## 6. Remote ID and Bluetooth

| Family / mode | Band / channel plan | Occupied bandwidth | Burst or frame duration | Repetition / hop rate | Dwell | Modulation | Duty cycle | Distinguishing feature | Status | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| ASTM F3411 / EN 4709-002 over Wi-Fi Beacon | 2.4 GHz channel 6 or 5 GHz channel 149 by default; other channels allowed at a higher rate | 20 MHz 802.11 | beacon frame carrying up to 9 messages of 25 bytes each | Location message at 1 Hz (Basic ID and System may be 3 s); 5 Hz required if a channel other than 2.4 GHz ch 6 or 5 GHz ch 149 is used | n/a | 802.11 OFDM | n/a | vendor-specific IE with ASD-STAN OUI FA:0B:BC, OUI type 0x0D | **decodable** | [opendroneid-core-c wifi.c and README](https://github.com/opendroneid/opendroneid-core-c) |
| ASTM F3411 over Wi-Fi NAN | 2.4 and 5 GHz | 20 MHz | NAN service discovery in Action frames (subtype 13) | as above | n/a | 802.11 | n/a | Wi-Fi Alliance OUI 50:6F:9A, OUI type 0x13, cluster ID 50:6F:9A:01:00:FF | **decodable** | [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c), [wireshark-dissector](https://github.com/opendroneid/wireshark-dissector) |
| ASTM F3411 over Bluetooth 4 legacy advertising | BLE advertising channels | ~1 MHz | advertisement | as above | n/a | GFSK 1 Mb/s ("BLE standard 1Mbps GFSK PHY") | n/a | service-data UUID 0xFFFA with app code 0x0D; optional under ASD-STAN DRI but the only transport iOS up to 15 exposes to apps | **decodable** | [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c), [JiaoXianjun/BTLE](https://github.com/JiaoXianjun/BTLE) |
| ASTM F3411 over Bluetooth 5 Long Range | BLE advertising plus auxiliary channels | ~1 MHz | extended advertisement (offsets shift by 5 bytes versus BT4; HCI adds 17) | as above | n/a | Coded PHY (S8/S2) | n/a | no open SDR tool surveyed decodes Coded PHY; Sniffle on a CC26x2/CC1352 dongle does | **decodable** with a hardware sniffer, not with the E200 | [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c), [nccgroup/Sniffle](https://github.com/nccgroup/Sniffle), [ice9-bluetooth-sniffer](https://github.com/mikeryan/ice9-bluetooth-sniffer) |
| DJI standard Remote ID | 802.11 Beacon only; band and channel not established | 20 MHz | beacon | not established | n/a | 802.11 | n/a | Beacon-only is DJI's implementation choice, not a standard requirement; SSID typically `RID-<id>`; verified for Mavic 3, Mini 3 Pro, Air 2S, Mavic 3 Enterprise; C0 sub-250 g DJI models are reported to broadcast nothing in Europe | **decodable** where present | [opendroneid receiver-android transmitter-devices.md](https://github.com/opendroneid/receiver-android/blob/master/transmitter-devices.md) *(verified: verdict 7, `dji-eu-rid`)* |
| GB 42590-2023 (China, in force 2024-06-01) | Wi-Fi or Bluetooth; Wi-Fi broadcast additionally permitted at 5725-5829 MHz | as the carrier | 25-byte messages | not established | n/a | as the carrier | n/a | same OUI FA:0B:BC / type 0x0D as ASTM but protocol-version nibble 1 and a 12-bit direction field | **decodable** (luolitao/remoteid) | [luolitao/remoteid](https://github.com/luolitao/remoteid), [luolitao/XC-RemoteID](https://github.com/luolitao/XC-RemoteID) |
| GB 46750-2025 (China, effective 2026-05-01) | Bluetooth 5.0+ extended advertising or Wi-Fi 2.4/5.8 GHz | as the carrier | variable-length, `data[1]==0xFF`, 3-byte x 7-bit data-identifier bitmap for 21 items | not established | n/a | as the carrier | n/a | not wire-compatible with F3411; an ODID-only parser silently drops these frames | **decodable** (libopendroneidcn) | [opendroneid-core-c README China section](https://github.com/opendroneid/opendroneid-core-c), [XC-RemoteID](https://github.com/luolitao/XC-RemoteID) |

The three BLE primary advertising channels are recorded in the round-1 regulatory lens as
2402 / 2426 / 2480 MHz, which together with Wi-Fi channel 6 at 2437 MHz spans 78 MHz, more than the
AD9361's 56 MHz and far more than the ~20 MSPS host budget: the E200 must choose one of these
windows per tune rather than watching them all
(round-1 finding; supporting sources [ice9-bluetooth-sniffer](https://github.com/mikeryan/ice9-bluetooth-sniffer),
[gr-ieee802-11](https://github.com/bastibl/gr-ieee802-11), [openwifi](https://github.com/open-sdr/openwifi)).

---

## 7. Contested and unresolved numbers

| Quantity | Competing values | Resolution | Source |
|---|---|---|---|
| Analog FPV occupied bandwidth | "10 MSPS is enough, <0.3 % of energy outside +/-4.5 MHz" (fpvdec) versus "analog FPV typically uses a 30 MHz channel width" and 20-27 MHz community figures | *(verified: verdict 5)*: 99 % core is about 9-10 MHz; 19-20/37 MHz are channel spacings; 23-27 MHz is a Carson estimate including the 6.0/6.5 MHz audio subcarriers. Do not quote 27 MHz as occupied bandwidth without saying which of the three it is | [5G8atv](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder), [fpv-sdr](https://github.com/lukeswitz/fpv-sdr), [RTC6705 datasheet](https://github.com/OpenVTx/OpenVTx/blob/master/docs/RTC6705-RichWave.pdf) |
| "5 MHz peak deviation" for analog FPV | quoted as a chipset specification in community material | *(verified: verdict 5)*: it is the `fpvdec --dev` default scale constant. The RTC6705 datasheet has no video-deviation register and no Kvco | [RTC6705 datasheet](https://github.com/OpenVTx/OpenVTx/blob/master/docs/RTC6705-RichWave.pdf) |
| OcuSync 3 and 4 subcarrier spacing | 15 kHz (LTE-like, as in OcuSync 2) versus ~30 kHz | **unresolved**. `ocusync-phy` was queued for verification and never ran, so it stands as an **unverified round-1** finding. The only measurement is a repeatedly observed cyclic peak at 27.99 kHz on a Zynq-7020 + AD9364 node, which fits a 30 kHz spacing with an LTE-like 1/14 cyclic prefix. Implement both hypotheses (alpha windows 10.5-14.5 kHz and 22-30 kHz) | [RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker), [tmbinc](https://github.com/tmbinc/random/tree/master/dji/ocusync2) |
| OcuSync video occupied bandwidth | "a single video transmission module occupies 8 MHz" (CSDN) versus 10/20 MHz (DJI SDK) versus ~18 MHz measured OBW in the 20 MHz mode (tmbinc) | Use 10/20 MHz nominal and ~18 MHz occupied. The 8 MHz figure has no supporting measurement and should not be used | [CSDN OcuSync explainer](https://blog.csdn.net/weixin_29216049/article/details/158087603) (snippet), [DJI SDK](https://developer.dji.com/iframe/mobile-sdk-doc/android/reference/dji/common/airlink/OcuSyncBandwidth.html), [tmbinc](https://github.com/tmbinc/random/tree/master/dji/ocusync2) |
| DroneID modulation class | "DroneID uses 5-10 MHz frequency hopping spread spectrum" (ETR 2025) | Wrong characterisation. DroneID is an OFDM burst that appears on a small set of rotating centre frequencies; the width figure agrees with proto17, the "FHSS" label does not | [ETR 2025](https://journals.ru.lv/index.php/ETR/article/download/8486/6933/10816) (snippet), [proto17](https://github.com/proto17/dji_droneid) |
| Mini 4 Pro airlink generation | "Mini 4 Pro uses Lightbridge" (ETR 2025) | Wrong. The Mini 4 Pro ships OcuSync 4; it appears in the O4 model tables of the E200 firmware | [ETR 2025](https://journals.ru.lv/index.php/ETR/article/download/8486/6933/10816) (snippet), [alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) |
| "DJI drones only broadcast DroneID when motors are spinning" | asserted in one README | *(verified: verdict 4)*: **refuted for OcuSync-2-era firmware** (proto17 records DroneID from a powered-on Mini 2 with no controller; DroneSecurity's mini2_sm capture predates GPS lock) and **unverified for O4**. The protocol carries separate `motor_on` and `in_air` flags, so log them and measure per model | [alphafox02 README](https://github.com/alphafox02/antsdr_dji_droneid), [proto17 MATLAB wiki](https://github.com/proto17/dji_droneid/wiki/Using-the-MATLAB-Code), [DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity) |
| HDZero baseband silicon | "AD9361-based HDZero video link" (Chinese explainer) | **contested**. The open HDZero firmware shows DM5680 baseband with DM6300 (VTX) and DM6302 (goggle RX) and contains no AD9361 reference | [kechuang.org](https://www.kechuang.org/t/89181) (snippet) versus [hdzero-vtx](https://github.com/hd-zero/hdzero-vtx) (verified) |
| HDZero R1 centre frequency | 5658 MHz (firmware) versus 5668 MHz (Russian channel table) | Use 5658 MHz; the firmware constant `FREQ_R1` is authoritative | [hdzero-vtx common.h](https://github.com/hd-zero/hdzero-vtx), [techuav VTX table](https://github.com/techuav/techuav.github.io) |
| ELRS sub-GHz "decodable" | claimed decodable given CRC/UID handling | *(verified: verdict 3)*: **decodable-candidate**, not demonstrated. gr-lora_sdr supports the parameters but no public project has decoded a real ELRS radio end to end; the only GNU Radio ELRS project validates only its own loopback with non-ELRS LoRa parameters | [gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr), [GNU_Radio_ExpressLRS](https://github.com/Diamond-D0gs/GNU_Radio_ExpressLRS) |
| ELRS 2.4 GHz "detect-only" | claimed because of the SX1280 long interleaver | *(verified: verdict 3)*: confirmed and strengthened. gr-lora_sdr fails on plain-CR SX1280 frames too (issue #143, unanswered), SDRangel ChirpChat tops out at 500 kHz bandwidth, and the FLRC and LR1121 GFSK 2.4 GHz rates are not LoRa at all | [gr-lora_sdr #143](https://github.com/tapparelj/gr-lora_sdr/issues/143), [SDRangel ChirpChat](https://github.com/f4exb/sdrangel/blob/master/plugins/channelrx/demodchirpchat/readme.md) |
| E200 O4 firmware channel set and clocking | 2434.5 / 5756.5 / 5776.5 / 5816.5 MHz in auto mode, 1r1t at a 61.44 MSPS path clock, legacy firmware using an FPGA correlator at `/dev/my-axi-droneid-filter0` | **unverified round-1** (`o4-firmware-channels`); the verification pass never ran. Treat as a round-1 reading of firmware strings | [alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) |

---

## 8. Feature thresholds proposed for the first classifier

These bins are derived from the tables above. They are a starting point for a rule-based first
stage, not a validated classifier: every boundary should be re-measured against E200 captures before
it is frozen.

### 8.1 Occupied-bandwidth bins

| Bin | Range | Families that land here | What it separates | What it confuses |
|---|---|---|---|---|
| **B0** | < 0.55 MHz | ELRS sub-GHz LoRa (500 kHz), FrSky R9 (500 kHz), Crossfire 150 Hz (~0.17 MHz on a 260 kHz grid), FrSky D8 (135 kHz filter), D16 (232 kHz), S-FHSS (232 kHz), HoTT (542 kHz filter, borderline), SiK (<=250 kb/s), AFHDS-2A slot (500 kHz), FrSky X20 measured 0.42 MHz | separates all narrowband RC from everything DJI and every video link | ELRS-900, FrSky R9 and Crossfire 50 Hz all sit here as LoRa at 500 kHz and must be separated by timing and coding rate |
| **B1** | 0.55-1.5 MHz | ELRS FLRC (0.6 MHz), ELRS 2.4 LoRa (812.5 kHz), DSM2/DSMX (~1 MHz), BLE (~1 MHz), DJI hop blocks 1.1-1.2 MHz (LR11xx GFSK at 467/476 kHz sits just below, in B0) | separates the fast RC modes from the legacy 2.4 GHz FHSS family | DJI OcuSync/Lightbridge hop blocks fall in the same bin as DSM and ELRS FLRC; only the ~0.5 ms dwell and OFDM structure separate them |
| **B2** | 1.5-3 MHz | OcuSync C2 uplink (1.92 MHz, gate 1.2-1.95 MHz), DJI OcuSync hop blocks (2.2 MHz), legacy Lightbridge ground unit (~2 MHz GFSK), OcuSync 3 MHz mode, Futaba T14SG measured 2.0 MHz | strong DJI-control indicator when paired with a wide downlink in the same capture | measured RC hop blocks of 1.7-2.1 MHz (Yunzhuo T12, Futaba T14SG) overlap DJI hop blocks |
| **B3** | 3-7 MHz | RadioLink AT9S measured 5.0 MHz; otherwise sparse | a nearly empty bin, useful as an "unknown" flag | little |
| **B4** | 8-11 MHz | DroneID (~9 MHz), O4 main link (8.92 MHz measured), OcuSync/Lightbridge 2 10 MHz mode, Herelink DL_10M, analog FPV 99 % core (9-10 MHz), OpenIPC 10 MHz mode | the busiest and most dangerous bin | DroneID versus OcuSync 10 MHz versus analog FPV versus Herelink all collide; break with duration and duty (DroneID 643 us at 0.11 % duty; OcuSync ~1 ms continuous; analog FM continuous with envelope CV 0.3-0.56) |
| **B5** | 15-22 MHz | OcuSync 20 MHz mode (~18 MHz occupied), DroneSecurity's video gate 18-22 MHz, Wi-Fi 20 MHz, Herelink 20 MHz, wfb-ng/OpenHD 20 MHz, Walksnail (assumed, unmeasured) | separates video-class links from control links | Wi-Fi, wfb-ng, OpenHD, Herelink and OcuSync video are all 20 MHz OFDM; only cyclostationary alpha (250 kHz Wi-Fi versus 10.5-14.5 or 22-30 kHz DJI) and MAC-layer inspection separate them |
| **B6** | 25-30 MHz | HDZero (~27 MHz) | the only family with a nominal 27 MHz carrier | the Carson-rule estimate for analog FPV lands in the same bin, which is exactly the mistake verdict 5 corrects: use the 99 % core, not Carson, when binning analog |
| **B7** | > 35 MHz | OpenHD 40 MHz, DJI O3 40 MHz, DJI O4 40/60 MHz (chipset "beyond 80 MHz") | flags "partially observed" | anything in B7 exceeds the 20 MSPS host stream, so the measured width is a lower bound and the bin decision itself is unreliable |

### 8.2 Burst-duration bins

| Bin | Range | Families | Notes |
|---|---|---|---|
| **D0** | < 0.55 ms | ELRS FLRC 389 us, DJI OcuSync hop-block dwell 0.52 ms, OcuSync C2 500-520 us, O4 DroneID ~500 us, ELRS LR11xx GFSK 658 us (borderline) | the shortest bin is dominated by DJI control hops and ELRS racing modes; they are separated by bandwidth (1.1-2.2 MHz versus 0.6 MHz) and by OFDM versus FLRC structure |
| **D1** | 0.55-1.6 ms | DroneID 643.2 us (legacy 571.9 us), OcuSync downlink ~1 ms, ELRS 2.4 500 Hz 1507 us, S-FHSS ~1.06 ms (derived), AFHDS-2A ~0.61 ms (derived), Futaba measured dwell 1.44 ms, HoTT ~1.6 ms (derived) | DroneID's 643 us with 600 ms repetition is unique in this bin because of its duty cycle |
| **D2** | 1.6-6 ms | ELRS 2.4 333/250 Hz (2374/3300 us), ELRS 900 200 Hz and 50 Hz DVDA (4380 us), LR11xx 250/200 Hz (3216/4240 us), Crossfire uplink ~2.2 ms (derived), Lightbridge hop dwell 2.2 ms, RadioLink AT9S 2.1 ms, Yunzhuo T12 4.6 ms | the densest RC bin; hop-set size and modulation are needed |
| **D3** | 6-12 ms | ELRS 2.4 150/100 Hz (5871/7605 us), ELRS 900 100 Hz (8770 us), ELRS 2.4 50 Hz (10798 us), LR11xx dual 150/100 Hz (5871/7456 us) | long LoRa bursts; SF is recoverable from the chirp rate |
| **D4** | > 12 ms | ELRS 900 50 Hz (18560 us), 25 Hz (29950 us) | ~30 ms chirps are unmistakable |
| **DC** | continuous (no burst structure over a 50 ms window) | analog FPV, HDZero, Walksnail, DJI digital FPV, wfb-ng, OpenHD, Wi-Fi | this is the video/Wi-Fi class flag |

### 8.3 Repetition and hop-period bins

| Bin | Period | Families | Confusion and how to break it |
|---|---|---|---|
| **H0** | 1-2 ms | ELRS FLRC (1000/2000 us), ELRS LR11xx GFSK (1000 us) | both have a 2 ms dwell; FLRC occupies 0.6 MHz and the LR11xx GFSK mode 467 kHz (476 kHz on LR2021), so bandwidth breaks the tie |
| **H1** | 3.5-4.2 ms | AFHDS-2A 3850 us, Potensic 4100 us, ELRS 2.4 250 Hz 4000 us, ELRS 900 250 Hz 4000 us | LoRa chirp versus GFSK breaks ELRS from AFHDS-2A; Potensic uses only four fixed channels |
| **H2** | 6-7 ms | **Crossfire 6666.67 us, ELRS 150 Hz 6666 us, Futaba S-FHSS 6800 us** | the worst cluster in the whole table. Break with modulation (FSK 85 kBaud versus LoRa SF7 chirp versus FSK 128 kb/s), band (Crossfire sub-GHz only), channel grid (260 kHz versus 1 MHz versus 1.5 MHz) and hop-set size (150 versus 80 versus 30) |
| **H3** | 9-12 ms | FrSky D8/D16 9000 us, HoTT 10000 us, DSM 11 ms, Lightbridge 12 ms nearest-hop spacing, ELRS 100 Hz 10000 us | 47 versus 75 versus 23 channels, and MSK versus 2-FSK versus DSSS |
| **H4** | 16-22 ms | FrSky R9 ~20 ms, DSM 22 ms frames, ELRS 50 Hz 20000 us, DSM2 SFC 16.5 ms | R9 and ELRS 50 Hz are both 500 kHz LoRa; separate by CR and hop-set size |
| **H5** | 40-100 ms | ELRS 25 Hz 40000 us, ELRS dwells of 40 and 80 ms | dwell, not packet period, dominates here |
| **H6** | ~600 ms | DroneID repetition | uniquely long for a burst this narrow; combined with a 9 MHz width it is close to a single-feature identification |
| **H7** | seconds | DJI channel dwell of 12-20 DroneID bursts, i.e. roughly 7-12 s per channel (derived from 600 ms x 12-20, [Bender arXiv 2207.10795](https://arxiv.org/abs/2207.10795), snippet); [DroneSecurity's](https://github.com/RUB-SysSec/DroneSecurity) own live receiver uses a 1.3 s dwell per frequency | sets the minimum scan dwell for a DroneID watch |

### 8.4 Duty-cycle bins

| Bin | Range | Families |
|---|---|---|
| **U0** | < 1 % | DroneID (~0.11 % derived) |
| **U1** | 10-25 % | ELRS FLRC F500 (19.5 %), Avata video period at 12 % duty, AFHDS-2A and S-FHSS and HoTT (~16 % derived) |
| **U2** | 30-60 % | ELRS FLRC 1000 Hz (38.9 %), ELRS 2.4 50 Hz (54.0 %), Crossfire uplink (~33 % derived) |
| **U3** | 60-95 % | most ELRS LoRa rates (66.9-92.8 %), Lightbridge video period (68 % measured) |
| **U4** | ~100 % | analog FPV, HDZero, Walksnail, DJI digital video, wfb-ng, OpenHD, Wi-Fi |

Duty cycle is the cheapest single discriminator between a control link and a video link once a burst
detector is running, and it is the only feature that isolates DroneID from everything else in the
same bandwidth bin.

### 8.5 Cyclostationary alpha bins (second-stage confirmation)

| Alpha window | Hypothesis | Notes |
|---|---|---|
| 10.5-14.5 kHz | 15 kHz subcarrier spacing (OcuSync 2, DroneID, LTE) | `tau = round(Fs / 15e3)`: 2667 at 40 MSPS, 1333 at 20 MSPS |
| 22-30 kHz | 30 kHz spacing (OcuSync 3/4 hypothesis, 5G NR) | `tau = round(Fs / 30e3)`: 1333 at 40 MSPS, 667 at 20 MSPS; a stable peak at 27.99 kHz was measured repeatedly. **Unverified round-1** (`ocusync-phy`) |
| 250 kHz single bin | 802.11 OFDM (312.5 kHz spacing) | `tau = round(Fs / 312.5e3)`: 128 at 40 MSPS, 64 at 20 MSPS. Used as a Wi-Fi presence monitor, not as a detector |

Published detector constants at 40 MSPS, from a Zynq-7020 + AD9364 implementation
([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker), verified deep read):
normalised cyclic correlation thresholds 0.018 (30 kHz channel) and 0.014 (15 kHz channel) as hard
floors, per-sector calibrated as `max(floor, 2.0 x (0.4 x p95 + 0.6 x mean))`; peak-to-sidelobe ratio
threshold 2.2, raised to 3.2 when the 250 kHz Wi-Fi probe exceeds `max(0.010, 2 x ambient)`; cyclic
frequency selectivity threshold 2.0; alpha stability sigma below 500 Hz over at least 4 chunks;
composite score `0.45*NCC/th + 0.25*PSR-term + 0.20*CFS-term + 0.10*AFS` with a detect threshold of
1.0 and a strong bypass at `NCC >= 2.5 x th`. Chunk length is 4 ms with 80 % overlap. At the E200's
realistic 20 MSPS the tau values halve, the chunk becomes 80,000 samples, the alpha windows stay the
same in Hz, and the noise floor of the statistic rises by sqrt(2), so the hard floors must be
re-derived by re-running the calibration.

**Known confuser**: LTE at 15 kHz and 5G NR at 30 kHz produce OcuSync-like cyclic responses; the
same source flags this explicitly and its Wi-Fi rejection stage was never trained against LTE/NR.

### 8.6 First-stage detector gates worth copying

| Stage | Parameter | Value | Source |
|---|---|---|---|
| Wideband burst detection | threshold over the per-bin mean noise floor | 7 dB (GRC default) | [gr-fhss_utils fft_burst_tagger](https://github.com/sandialabs/gr-fhss_utils) |
| | FFT size / burst width / history / lookahead / pre / post | 1024 / 500 kHz / 64 (API default 512) / 10 frames / 5 / 20 | same |
| | frame duration at 20 MSPS with N=256-512 | 12.8-25.6 us, bins 39-78 kHz | same (derived) |
| Analog FPV confirmation | SNR margin over the 20th-percentile noise floor | >= 12 dB | [fpv-sdr fpv_detect.py](https://github.com/lukeswitz/fpv-sdr) |
| | in-band (10 MHz) minus shoulder ring (18 MHz) power | >= 3 dB | same |
| | envelope coefficient of variation | <= 0.8 (analog FPV measured 0.3-0.56, Wi-Fi/OFDM 1.2-3.2) | same |
| | chunk dwell / settle | 0.12 s / 0.2 s | same |
| DroneID candidate gates | burst duration window | 630-665 us (legacy 565-600 us) | [DroneSecurity packetizer.py](https://github.com/RUB-SysSec/DroneSecurity) |
| | occupied-bandwidth window | 8-11 MHz (C2 1.2-1.95 MHz, video 18-22 MHz) | same |
| | STFT for the energy gate | nfft 64, threshold 1.15 x mean \|STFT\|, +/-45 us padding | same |
| DroneID confirmation | normalised cross-correlation against the root-600 ZC waveform | threshold 0.7 (0.2-0.9 usable, 0.5 a good start) | [proto17 process_file.m](https://github.com/proto17/dji_droneid) |
| Sector ranking | kurtosis = mean(abs(x)^4) / mean(abs(x)^2)^2, capped at 20, 3-frame median, EMA 0.35 | score = `P x (1 + 0.40 x max(0, kappa - kappa_ref)/kappa_ref)`; use `kappa_ref = 2.0` for circular complex Gaussian noise, not the 3.0 in the original code | [RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker) (deep read correction) |

### 8.7 Analysis-window length

| Window | Reported performance | Source |
|---|---|---|
| 2.5 ms | 72.7 % (ResNet-18 on DroneRFa STFT) | [DroneRFa](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |
| 10 ms | 97.73 % on the same benchmark; 0.769 for a PSD+SVM on DroneDetect | [DroneRFa](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570), [RFClassification](https://github.com/IQTLabs/RFClassification) |
| 20 ms | 0.836 (PSD+SVM, DroneDetect) | [RFClassification](https://github.com/IQTLabs/RFClassification) |
| 50 ms | 0.894 (PSD+SVM, DroneDetect) | same |
| 65-100 ms | working buffer sizes in fielded systems: 2.62 M samples (~65 ms at 40 MSPS), 1.05 M samples (~75 ms at 14 MHz), 0.1 s stated as the period over which drone behaviour is fully visible | [RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker), [Noisy Drone RF v2](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2), [DroneRFa](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570) |

A 50-100 ms window is the right default: it holds several hops of every RC family in section 4, one
full 40 ms ELRS dwell, and enough of a 600 ms DroneID cycle to measure duty cycle after two
consecutive windows. Note also that spectrogram inputs beat raw IQ decisively at low SNR (balanced
accuracy 0.842 versus 0.413 at -12 dB, no difference at or above 0 dB) *(verified: verdict 8,
spectrogram versus raw IQ, [Glüge et al.](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification))*.

### 8.8 Families this scheme cannot separate today

1. **Herelink versus OcuSync.** Both are LTE-numerology 10/20 MHz links in 2.4 GHz. The only
   available discriminator is Herelink's narrow 2409-2462 MHz plan; no source gives Herelink's
   cyclic prefix or reference-symbol structure.
2. **Wi-Fi versus wfb-ng versus OpenHD versus Walksnail at 20 MHz.** All land in B5 with 100 % duty.
   Separation needs MAC-layer inspection (a monitor-mode NIC keyed on the `57:42` and
   `13:22:33:44:55` prefixes) or a cyclostationary test, not the E200's spectral features alone.
3. **ELRS sub-GHz versus FrSky R9 versus Crossfire 50 Hz.** All are 500 kHz SX127x-class LoRa.
   Coding rate, hop-set size and packet interval separate them in principle, but only after a chirp
   demodulator recovers SF and CR.
4. **DJI O3/O4 40 and 60 MHz modes.** Wider than the host stream, so the measured bandwidth is a
   lower bound and the B6/B7 boundary is not reliably observable.
5. **Custom-band ELRS forks.** MilELRS-class links can appear anywhere in 150-2800 MHz, so any rule
   keyed on the domain table in 4.2 will miss them; only the chirp plus timing signature survives.
6. **LTE and 5G NR versus DJI OcuSync** in the cyclostationary stage, because they share the 15 and
   30 kHz numerologies.

---

## Gaps

Ordered roughly by how much they would change the toolkit.

1. **OcuSync 3 and 4 numerology.** Whether O3/O4 use 30 kHz subcarrier spacing is unverified; the
   only evidence is a repeatedly measured 27.99 kHz cyclic peak. How the 40 and 60 MHz modes are
   framed is unknown. `ocusync-phy` was queued for adversarial verification and never ran.
2. **The E200 O4 firmware channel set** (2434.5 / 5756.5 / 5776.5 / 5816.5 MHz, 1r1t at a
   61.44 MSPS path clock, legacy firmware opening `/dev/my-axi-droneid-filter0`) is an unverified
   round-1 reading of firmware strings (`o4-firmware-channels`).
3. **DJI C2 uplink timing.** tmbinc gives 1.4 and 3 MHz packet widths and DroneSecurity gives a
   500-520 us burst, but the hop rate, dwell and packet period of the uplink are documented nowhere
   that was reachable.
4. **The exact DroneID hop sequence and per-channel dwell.** The 13-point set and the 12-20 bursts
   per channel come from blocked or paywalled papers; the published frequency lists are
   observational unions from three projects that do not agree.
5. **O4 DroneID encryption.** No public information exists on the algorithm or key handling. The
   per-session hash from the E200 firmware is presumably derived from the encrypted payload but this
   could not be verified. The decrypt path is a paid cloud service.
6. **Crossfire per-mode LoRa parameters.** The SF, BW, CR, preamble and channel spacing of the
   50 Hz and 4 Hz modes are only in g3gg0.de, which could not be fetched. TBS Tracer's chipset and
   modulation are unverified.
7. **No open demodulator for Semtech FLRC** (ELRS F1000/F500/D500/D250) exists in any SDR
   framework; it would have to be written from the SX1280 datasheet.
8. **SX1280 2.4 GHz LoRa** (long-interleaver coding rates, SF5/6 symbol format, 12/14-symbol
   preamble, header-less packets) is unimplemented in gr-lora_sdr, gr-lora and SDRangel;
   gr-lora_sdr issue #143 is open and unanswered.
9. **Autel SkyLink 2.0 and 3.0** channel widths, OFDM numerology and the bandwidth of the 900 MHz
   component are unpublished; the FCC test reports (2AGNTMDC240958A and others) were blocked.
10. **Walksnail Avatar** exact channel centres and occupied bandwidth are unknown; the FCC report
    (2A78Z-AVATAR) was blocked. The Russian channel table gives centres but no widths.
11. **HDZero Wide and Narrow bandwidths** are not numeric anywhere in the open firmware; only the
    existence of two modes and a vendor "roughly 27 MHz" statement were found.
12. **Herelink and Skydroid physical layers** (OFDM versus FHSS, channel bandwidth, hop behaviour)
    are unknown; fccid.io was blocked. Skydroid T10 is known only as "2.4 GHz FHSS".
13. **Skydio Connect SL** modulation, width and hop behaviour are unknown (AES-256, proprietary).
    Skydio 2's Wi-Fi 5 GHz link was not confirmed from a primary source.
14. **FrSky ACCESS, Futaba FASST/T-FHSS and Flysky AFHDS 3** have no public reverse engineering, so
    only detection is possible. The FrSky ACCST register-set-to-subprotocol mapping (which CC2500
    register set is D8 versus V8 versus L) was inferred from file order and should be checked
    against the Multiprotocol source comments.
15. **Analog FPV occupied bandwidth** rests on a single unreproduced hobbyist measurement with an
    8-bit receiver at an unknown span; audio-equipped and high-power VTX were never tested, and PAL
    chroma handling is missing from every open decoder. 2.4 GHz analog video channel plans were not
    found.
16. **Lightbridge 2 5.8 GHz variants** (the Phantom 4 Pro V1 5.8 GHz option) are not covered; the
    32-channel table is a 2.4 GHz plan from forum firmware dumps.
17. **No open IQ dataset contains ELRS, Crossfire, SiK or AFHDS-2A**, so every RC row in section 4
    that is marked "not established" has to be measured on the E200 with owned hardware.
18. **gr-ieee802-11's lack of 802.11n HT decoding** is inferred from its README (a/g/p only);
    whether its sync block reliably detects HT-mixed preambles from wfb-ng frames was not tested.
19. **BLE 5 Coded PHY** is not decoded by any open SDR tool surveyed, so BT5 Long Range Remote ID
    needs a hardware sniffer beside the E200 rather than the E200 itself.
20. **The two GB 46750 open implementations disagree** on the timestamp field (6-byte Unix
    milliseconds versus 4-byte seconds since 2019-01-01); the official standard text must be
    consulted before writing a decoder.
