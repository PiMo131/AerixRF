# Sources

Annotated bibliography of everything the research sweep read or found. Every entry carries
the language, the kind of source, a relevance score (1 marginal .. 5 must-read) and a
confidence flag: **verified** means an agent fetched the page or cloned the code and read it;
**snippet** means only a search-engine snippet was available because the development sandbox
cannot reach that host. Snippet-only facts must be re-checked against the original before
they drive a design decision. The wish list of pages to download by hand is at the end.

Total unique sources: 296. By language: English 208, Chinese 50, Russian 24, Ukrainian 8, Dutch 6. By kind: github 144, blog 38, doc 30, paper 25, vendor 20, forum 17, standard 10, dataset 7, other 4, video 1.

Sections follow the research lenses. A source found by several lenses is listed once, under the first.


## DJI DroneID and OcuSync

### RUB-SysSec/DroneSecurity - Drone-ID receiver for DJI OcuSync 2.0 (NDSS 2023 artefact)
`5/5` · English · github · 2023 · verified  
<https://github.com/RUB-SysSec/DroneSecurity>


Official code of 'Drone Security and the Mysterious Case of DJI's DroneID' (NDSS 2023, RUB-SysSec: Schiller, Chlosta, Schloegel, Bars, Eisenhofer, Scharnowski, Domke, Schönherr, Holz). Python receiver (offline and live via UHD) that detects candidate frames, correlates Zadoff-Chu sequences, extracts OFDM symbols, QPSK-demodulates, descrambles, turbo-decodes and CRC-checks DroneID payloads (serial, drone/pilot/home GPS, altitude, velocities). It is the academic reference for the DroneID/OcuSync broadcast waveform and its payload format.


- License AGPL-3.0; last commit 2023-03-10 'FAQ, add LICENSE' (cloned); tested with DJI Mini 2 and Mavic Air 2.
- helpers.py: NFFT=1024, 601 carriers (600+DC), CP_LENGTHS=[80,72,72,72,72,72,72,72,80] (9 symbols), legacy Mavic Pro/Mavic 2 = 8 symbols [80,72x6,80]; ZC symbols index [3,5] (0-based) normal, [2,4] legacy; C2 frames have 73 carriers (1.92 MHz) with 7 symbols and ZC at [0,6].
- packetizer.py: burst-length gates: droneid 630-665 us (legacy 565-600 us), c2 500-520 us, beacon/pairing 490-540 us, video 630-665 us at ~20 MHz width; detection is STFT energy + Welch PSD band-width test (8-11 MHz for DroneID, 18-22 MHz for video).
- droneid_receiver_live.py hop list (MHz): 2414.5, 2429.502441, 2434.5, 2444.5, 2459.5, 2474.5, 5721.5, 5731.5, 5741.5, 5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5; 1.3 s dwell per frequency at 50 MSPS; locks on a frequency after a decode and releases after 10 empty runs; 2 worker processes; README says live mode needs 'quite powerful machines'.
- qpsk.py: brute-forces the 4 QPSK rotations, descrambles with gold(1600, n, 0x12345678), takes a 1412-bit systematic window at offset 4148 of the cyclic buffer, undoes LTE sub-block interleaving (RM_PERM_TURBO) and ignores parity streams (no real turbo decoding).
- droneid_packet.py: struct '<BBBHH16siihhhhhhQiiiiBB20sH' (91 bytes); lat/lon = int32/174533.0; altitude/height ft->m; CRC-16 poly 0x11021 init 0x3692 reflected (crcmod); serial reads 'SecureStorage?' when the drone withholds it; product-type table 1..70 (Inspire 1 .. Mini SE).
- Issues: #46 Mavic 3 Classic (O3) - ZC 600/147 found but constellation unusable (open); #43 Phantom 4 Pro V2 not detected by the repo at 62.5 MSPS but decoded by an ANTSDR, and a 14-symbol signal with two sync symbols was seen; #50 Mavic Air 3S O4 shows a recurring 500 us burst with 4 ZC sequences (open, July 2026); #41 live receiver 'only hops and finds nothing' (open).
- Live hop list (MHz): 2414.5, 2429.502441, 2434.5, 2444.5, 2459.5, 2474.5, 5721.5, 5731.5, 5741.5, 5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5.
- _(13 more facts in the JSON index)_

*E200:* Best starting point for a Python/NumPy host-side decoder fed by the E200 over Ethernet (replace the UHD source with libiio/SoapySDR); hop list and dwell logic are directly reusable. Not fast enough for continuous 56 MHz processing without a rewrite.

### lukeswitz/fpv-sdr - cross-platform 5.8 GHz analog FPV decoding (supports ANTSDR)
`5/5` · English · github · 2026 · verified  
<https://github.com/lukeswitz/fpv-sdr>


GNU Radio based scanner/decoder for analog NTSC/PAL FPV video that lists the ANTSDR E200 (UHD backend, 20 Msps) as the recommended radio. Includes a headless detector (fpv_detect.py) with an FM-envelope statistic that separates analog FPV from Wi-Fi/OFDM, a 64-channel/8-band table (incl. DJI and Low band), a terminal spectrum sweep, and the vendored gr-ntsc-rc decoder. This is the closest existing thing to an E200 FPV toolkit.


- Capture bandwidth set per radio: HackRF 12, bladeRF 18, ANTSDR/USRP 20, Pluto 8 Msps; override with samp-rate.
- Decodes 5.8 GHz analog FPV with any SDR reaching the band, including ANTSDR.
- MIT licence with a bundled GPLv3 NTSC decoder; 91 commits on main (page fetched 2026-09).
- Supported SDRs listed explicitly include ANTSDR E200 as the primary option.
- Functions: channel search, tune by channel/frequency, gain control, sync fine-tuning.
- Supported radios: ANTSDR E200 (uhd, 'recommended'), USRP B210/B200mini, BladeRF 2.0 micro, HackRF One, ADALM-Pluto (~8 Msps USB2 cap); CaribouLite too narrow (2.5 MHz).
- Capture rate auto-set per radio: HackRF 12, BladeRF 18, ANTSDR/USRP 20, Pluto 8 Msps; user can set samp-rate 10..16.
- Channels: 64 across 8 bands (Raceband, A, B, E, F, IMD, D=DJI, L=Low) 5362-5945 MHz; DJI band D1-D8 = 5660, 5695, 5735, 5770, 5805, 5878, 5914, 5839 MHz (fpv_scanner.sh).
- _(4 more facts in the JSON index)_

*E200:* Shows the E200 is already a first-class target in this ecosystem and gives a GNU Radio source configuration for it.

### proto17/dji_droneid - DJI DroneID RF Analysis (MATLAB/Octave + C++ + GNU Radio branches)
`5/5` · English · github · 2022-2024 · verified  
<https://github.com/proto17/dji_droneid>


The reference open reverse-engineering of the OcuSync DroneID burst by David Protzman. Offline MATLAB/Octave pipeline (ZC detection, CFO, equalisation, descrambling) plus a C++ tool (turbofec + CRCpp) that removes LTE rate matching / turbo coding and checks CRC-24. GNU Radio OOT modules exist on branches but the author declared them 'not very good' in Oct 2022 and the rewrite stalled. MIT licensed; main last touched 2024-05-27.


- License: MIT (Copyright 2022 David Protzman); main branch last commit 2024-05-27 'Update README.md' (cloned).
- Test hardware: Ettus B205-mini at 30.72 MSPS, DJI Mini 2; signal ~10 MHz occupied (15.36 MHz incl. guards), bursts every ~600 ms.
- PHY: 9 OFDM symbols (some drones send 8, skipping symbol 1); symbols 4 and 6 (1-based) are Zadoff-Chu with roots 600 and 147 generated as length-601 with the DC element removed; 600 data carriers, 15 kHz spacing; FFT = Fs/15e3; long CP = Fs/192000 (80 samples @15.36 MSPS), short CP = 4.6875 us (72 samples); CP schedule long,short x7,long; remaining symbols QPSK; no pilots.
- Scrambler = LTE Gold sequence (36.211 7.2, Nc=1600) with x2 init 0x12345678 bit-reversed; in the 9-symbol case symbol 1 is zeroed by the scrambler and the sequence restarts for the other 8 symbols (7200 bits).
- cpp/remove_turbo.cc: 7200 soft bits -> lte_rate_match_rv (D=1412, E=7200, rv=0) -> lte_turbo_decode 4 iterations -> 176 bytes; CRC-24 LTE-A over the block must zero; the inner payload = length byte + 88 bytes + 0x00 + CRC-16.
- transmit/calculate_crc.m: payload CRC-16 is DJI's Guidance-SDK table CRC with init 0x3692; transmit/create_frame_bytes.m documents the 91-byte frame (msg type 16, version 2, seq, state_info, 16-byte serial, lon/lat int32 scaled 1e7/57.2957795, height, altitude, v_n/v_e/v_up, yaw, phone GPS time uint64, app lat/lon, home lon/lat, product type, uuid_len, 19-byte uuid).
- Known centre frequencies listed: 2.3995, 2.4145, 2.4295, 2.4445, 2.4595 GHz and 5.7565, 5.7765, 5.7965 GHz.
- Branch gr-droneid-update-3.10 (last commit 2022-09-22) has blocks extractor, time_sync, demodulation, decode (GPL-3.0-or-later header), normalized_xcorr_estimate and a drone_id_test.grc with an osmosdr source; branch gr-droneid-rewrite (2022-10-16) only has detector + burst_extractor blocks.
- _(19 more facts in the JSON index)_

*E200:* Gives every constant needed to write a native decoder for the E200 host or ARM core; sample rate must be 15.36e6 x 2^n (E200/AD9361 supports 15.36, 30.72, 61.44 MSPS exactly). Nothing here runs live; use as the algorithm reference, not as a runtime.

### tmbinc notes on the DJI OcuSync 2 physical layer
`5/5` · English · github · 2021 · verified  
<https://github.com/tmbinc/random/tree/master/dji/ocusync2>


Felix Domke's notes on OcuSync 2.0: LTE-like OFDM with 20/10/3/1.4 MHz bandwidths, 15 kHz subcarrier spacing, FFT 2048 for 20 MHz (1201 active), 72/144 CP, ~1 ms packets, QPSK first symbol then QPSK/QAM, Zadoff-Chu references, downlink/uplink/broadcast (DroneID) link types, implemented on DJI's 'Sparrow' ASIC. The best public description of how an OcuSync video link looks on air.


- Bandwidth modes 20, 10, 3 and 1.4 MHz; 20 MHz mode uses 1201 subcarriers at 15 kHz (~18 MHz occupied).
- Downlink frame: RS0 \| D x6 \| RS1 \| D x6 \| RS0, ~1 ms; CP 144 (20 MHz) / 72 (10 MHz) samples with extended CP (+16/+8) on first, middle and last symbols.
- Reference symbols are LTE-like Zadoff-Chu sequences; data QPSK or higher QAM; DC carrier phase ~20 deg + k*90 deg.
- Uplink (controller->drone) uses frequency hopping; broadcast type carries remote identification.
- Bandwidths '20MHz, 10MHz, 3MHz, 1.4MHz' plus a '1.4MHz-CA (likely collision avoidance aka frequency hopping)' mode.
- FFT size 2048 for 20 MHz; subcarrier spacing 15 kHz; 1201 active subcarriers (20 MHz) / 601 (10 MHz); CP 144 (20 MHz) / 72 (10 MHz), extended 144+16 / 72+8 on select symbols.
- Packets ~1 ms; 'The first signal is always QPSK', later QPSK or higher QAM; LTE-like Zadoff-Chu sequences; DC subcarrier (600 for 20 MHz) unused.
- Link types: downlink (drone-to-RC), uplink (RC-to-drone), broadcast (remote drone id / flight info).
- _(11 more facts in the JSON index)_

*E200:* Gives the fingerprints (frame length, ZC reference symbol spacing, bandwidths) to detect and classify OcuSync video/C2 activity on the E200 even when DroneID is encrypted.

### CSDN (futon): 通过USRP B200软件无线电SDR方式解码无人机坐标飞手坐标 (decode drone and pilot coordinates with a USRP B200)
`4/5` · Chinese · blog · 2023 · snippet  
<https://blog.csdn.net/futon/article/details/131232535>


The well-known Chinese write-up of running DJI DroneID decoding on a USRP B200 (same AD9361 class as the E200). Claims real-time decoding of serial number, drone lat/lon, home-point and pilot coordinates for Mini 2, Mavic Air 2 and Mavic 2 Pro. Useful as a Chinese-language walkthrough and evidence of which models are decodable with a B200-class front end.


- Uses a USRP B200-mini to capture and decode OcuSync DroneID and extract drone/pilot location.
- Related Chinese material: Zhihu translation of the NDSS paper (https://zhuanlan.zhihu.com/p/612103881), CSDN guides on the dji_droneid toolkit (601 subcarriers, 15 kHz, 15.36 MHz, brute-forced QPSK orientation) and '通信算法之264: DJI O2 协议物理层逆向工程解析' (https://blog.csdn.net/leegang12/article/details/147245156).
- Real-time decode of DJI serial number, precise drone lat/lon, return-to-home point and operator coordinates
- Models demonstrated: Mini 2, Mavic Air 2, Mavic 2 Pro
- Hardware: USRP B200 (AD9364, 56 MHz) — comparable RF chain to E200/AD9361
- Mirror: https://2048.csdn.net/681db80ea5baf817cf4a06d5.html
- Uses USRP B200 (AD9364, same RF family as E200) with the open-source DroneID decoder chain.

*E200:* No new technical content for the E200; confirms there is no independent Chinese open-source DroneID implementation beyond mirrors of proto17/RUB (gitcode mirror of dji_droneid).

### Conner Bender - DJI drone IDs are not encrypted (arXiv 2207.10795)
`4/5` · English · paper · 2022 · snippet  
<https://arxiv.org/abs/2207.10795>


Pre-print showing real-time capture of both Enhanced Wi-Fi and OcuSync DroneID with low-cost SDR (LimeSDR + GNU Radio); documents that a drone stays on one frequency for 12-20 DroneID bursts before hopping and tabulates 2.4/5.8 GHz centre frequencies.


- GNU Radio flowgraph with LimeSDR; any SDR delivering 32-bit float IQ at up to 15.36 MSPS can capture DroneID.
- A signal broadcasts on a frequency until 12-20 DroneIDs are emitted before hopping; Table II lists 2.4 GHz and 5.8 GHz centre frequencies for DroneID.
- Covers detection of Enhanced Wi-Fi DroneID (76-byte packet after dji_ie_on) and OcuSync DroneID.

*E200:* Supports a dwell-time design: 12-20 bursts x ~600 ms per channel means several seconds per channel, so a slow hop schedule on the E200 will not miss drones.

### Drone Security and the Mysterious Case of DJI's DroneID (NDSS 2023)
`4/5` · English · paper · 2023 · snippet  
<https://www.ndss-symposium.org/ndss-paper/drone-security-and-the-mysterious-case-of-djis-droneid>


Schiller, Chlosta, Schloegel et al. reverse-engineered DJI firmware and the OcuSync 2 radio link, documented DroneID for the first time, built a COTS-hardware decoder and reported 16 vulnerabilities to DJI. It is the academic source behind the DroneSecurity repo and the origin of most Chinese/Russian secondary coverage.


- Decoder built from cheap COTS hardware based on firmware reverse engineering; DroneID data is not encrypted and reveals pilot and drone location.
- 16 vulnerabilities reported to DJI before publication; DJI took steps to fix them.
- Companion tweet by Thorsten Holz: receiver works live with an SDR or offline on captures (https://x.com/thorstenholz/status/1631194204587147265).

*E200:* Background and threat-model reference; the PHY details are in the repo, the paper adds the DUML framing/firmware context.

### Kismet dot11_ie_221_dji_droneid.h - Wi-Fi beacon DJI DroneID IE parser
`4/5` · English · github · 2018-2025 · verified  
<https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h>


Parser for the vendor-specific IE that Wi-Fi DJI drones (Spark, Mavic Air, Mavic Pro Wi-Fi mode, etc.) append to 802.11 beacons: OUI 26:37:12, subcommand 0x10 flight telemetry and 0x11 flight purpose. Same field set as the OcuSync payload, which is why samples2djidroneid reuses it.


- OUI 0x263712; subcmd 0x10 = telemetry (version, seq, state_info, serial, raw lon/lat /174533, altitude, height, v_north/east/up, pitch/roll/yaw /100/57.296, home and app lat/lon, product_type, uuid, gps_time in v2); 0x11 = serial, drone_id, purpose strings.
- State flags: serial valid, user privacy enabled, homepoint set, uuid set, motors on, in air, gps valid, altitude/height/horizontal/vertical valid, pitch/roll valid.
- Kismet classifies matches as manufacturer DJI, match type 'DroneID WiFi' and keeps a 128-entry telemetry history (phy_uav_drone.cc).

*E200:* Defines the shared DroneID field semantics (state flags, scaling) that any E200 decoder output should map to; also the Wi-Fi path a monitor-mode NIC beside the E200 can cover.

### OpenDroneID receiver-android transmitter-devices.md - which DJI models broadcast standard Remote ID and how
`4/5` · English · doc · 2022-2025 · verified  
<https://github.com/opendroneid/receiver-android/blob/master/transmitter-devices.md>


Community-maintained list of Remote ID transmitters; the DJI Mavic 3 and Mini 3 Pro entries state that DJI broadcasts standard (ASTM F3411 / ASD-STAN 4709-002) Remote ID over Wi-Fi Beacon only, not Bluetooth and not Wi-Fi NAN, with <500 m smartphone range.


- DJI Mavic 3: Wi-Fi Beacon only (BT4/BT5 no, NAN no), 'Range < 500 meters via smartphone'.
- DJI Mini 3 Pro: Wi-Fi Beacon only, same note.
- Entries added by PRs #75/#76 in July 2022 (issues page).

*E200:* Tells the toolkit that for DJI the standard ODID path is 802.11 beacons (2.4 GHz Wi-Fi channels), i.e. a monitor-mode Wi-Fi NIC or a Wi-Fi beacon decoder on the E200, not BLE.

### WarDragon detection-capabilities.md - what the ANTSDR/DragonSDR stack really decodes
`4/5` · English · doc · 2025-2026 · verified  
<https://github.com/alphafox02/WarDragon/blob/main/docs/software/detection-capabilities.md>


Capability matrix from the WarDragon docs: OcuSync 2 and standard OcuSync 3 give full telemetry, OcuSync 3 Pro / O4+ only 'activity detection' (hash) unless DragonScope is licensed; also lists Remote ID Wi-Fi/BT5 ranges and DroneID range expectations.


- OcuSync 2 full telemetry; OcuSync 3 (standard) full telemetry; OcuSync 3 Pro / O4+ hash-only by default, full telemetry requires DragonScope subscription with data connectivity.
- 'DJI drones only broadcast DroneID while motors are spinning'; O4 Air units confirmed as activity detection; DJI Neo 2 with add-on module gives full DroneID decode.
- DroneID range: several hundred m urban, 1-2 km clear LOS with stock antenna, up to ~10 km with external LNA + directional antenna; Wi-Fi Remote ID 700 m+; BT5 LE Coded S8 500 m-1 km+.
- DragonSDR spec: ~70 MHz-6 GHz, dual-channel receive, output via dji_receiver.py.

*E200:* Sets realistic expectations for what the E200 firmware yields per OcuSync generation and typical ranges with stock antennas.

### Department 13 white paper 'Anatomy of DJI's Drone Identification Implementation' (2017, GitHub mirror)
`3/5` · English · other · 2017 · snippet  
<https://github.com/MAVProxyUser/CIAJeepDoors/blob/main/Anatomy-of-DJI-Drone-ID-Implementation1.pdf>


Original public description of DJI's Wi-Fi DroneID (Mavic/Spark, mid-2017): flight_info pushed to the Wi-Fi subsystem as a beacon IE every 200 ms alternating Flight_Reg_Info and Flight_Purpose packets; it also mentions three packet structures including OcuSync. Source of the /174533 coordinate scaling used by all decoders.


- DJI implemented DroneID on Mavic in mid-July 2017; Wi-Fi products then were Mavic and Spark.
- Packets sent down the Wi-Fi link every 200 ms alternating Flight_Purpose and Flight_Reg_Info.
- Referenced by DroneSecurity and samples2djidroneid for the coordinate scaling (int/174533.0).

*E200:* Historical spec for the Wi-Fi DroneID variant and the payload semantics.

### Drone Remote Identification Based on Zadoff-Chu Sequences and Time-Frequency Images (arXiv 2504.02844, IEEE TCCN)
`3/5` · English · paper · 2025 · snippet  
<https://arxiv.org/abs/2504.02844>


Classifier that fuses ZC cross-correlation features with spectrogram features on the DroneRFa dataset to identify drone models (99.11% max accuracy). Relevant because ZC-based features are exactly what an E200 detector can compute cheaply for DJI classification without decoding.


- Uses prior knowledge of ZC sequences in DJI frames from the DroneRFa dataset; cross-correlation with locally generated ZC sequences as features, fused with time-frequency images.
- Reported +2.5% average accuracy over prior methods, 99.11% best case across flight distances; published in IEEE Transactions on Cognitive Communications and Networking.
- Follow-up: 'Cognitive Fusion of ZC Sequences and Time-Frequency Images for Out-of-Distribution Detection of Drone Signals' (arXiv 2601.18326).

*E200:* Blueprint for an on-E200 'DJI-family classifier' that works on encrypted O4 links: correlate against ZC roots per generation and combine with STFT features.

### Identifying and Analyzing DJI Drone Signals (RTU ETR proceedings, 2025)
`3/5` · English · paper · 2025 · snippet  
<https://journals.ru.lv/index.php/ETR/article/download/8486/6933/10816>


Conference paper with SDR waterfall measurements of a DJI Air 3 (O4), Mini 4 Pro and Phantom 4. Snippets give PSD extents and DroneID width but also contain statements that contradict better sources (e.g. Mini 4 Pro = Lightbridge, DroneID = FHSS); use with care.


- Method: HackRF One with DragonOS tools (HackRF Spectral Analyzer, SDR++, Inspectrum).
- Consumer DJI models use OcuSync 2, 3 and O3+ operating on 2.4 and 5.8 GHz simultaneously, switching bands on link quality.
- Measured PSD of the DJI link spans 2435–2470 MHz
- Claims DroneID uses 5–10 MHz 'frequency hopping spread spectrum' and is unencrypted (width agrees with proto17; 'FHSS' is a mischaracterisation of the OFDM burst on rotating centre frequencies)
- Claims Mini 4 Pro uses Lightbridge with strong periodic peaks/fixed hop pattern (contested: Mini 4 Pro ships O4)
- O4 and Lightbridge rely on QPSK with adaptive 64-QAM in strong signal

*E200:* Low; shows what purely visual/energy analysis can and cannot do compared with decoding.

### Kismet 2025-09-R1 release notes (AntSDR DJI DroneID source added)
`3/5` · English · blog · 2025 · snippet  
<https://www.kismetwireless.net/posts/kismet-2025-09-r1>


Stable Kismet release that adds the AntSDR DJI DroneID datasource; Kali packages it as kismet-capture-antsdr-droneid (kismet_cap_antsdr_droneid).


- Kismet 2025-09-R1 'added an AntSDR DJI DroneID source'.
- Kali kismet package 2025.09.R1 lists kismet-capture-antsdr-droneid / kismet_cap_antsdr_droneid (https://www.kali.org/tools/kismet/).

*E200:* A packaged consumer for the E200 legacy DroneID firmware exists in mainstream distros.

### MavicPilots threads on EU Remote ID behaviour of DJI Mini 3 / Mini 3 Pro / Mavic 3
`3/5` · English · forum · 2022-2024 · snippet  
<https://mavicpilots.com/threads/does-the-dji-mini-3-pro-have-remoteid-in-the-eu-that-broadcasts-the-location-and-altitude.151947>


Forum evidence on when DJI drones actually emit standard Remote ID in Europe: Mavic 3 was found broadcasting (receivable in the OpenDroneID app) from firmware 01.00.0800 worldwide; Mini 3 (C0) had RID switched off in Europe by DJI; Mini 3 Pro only after firmware updates; Android reception takes 30-60 s and reaches ~600 m LOS.


- Mavic 3 on 01.00.0800 appears in the OpenDroneID app regardless of FCC/CE region (https://mavicpilots.com/threads/bad-news-to-everyone-rid-was-already-active-in-01-00-0800-firmware-and-the-drone-appears-in-opendroneid-app.132574/page-5).
- 'Remote ID on Mini 3 is turned OFF in Europe. It was ON with early firmwares, but DJI disconnected this' and Mini 3 Pro broadcasts only after FW update.
- OpenDroneID on a Samsung Tab A7 received beacons up to ~600 m LOS but needed 30-60 s to catch a drone; C0 class drones are not required to broadcast in the EU, C1 can enable it; Mini 4 Pro can be upgraded to C1 with a pilot-ID menu in DJI Fly.
- DJI RID cannot be received on iOS because Apple exposes no Wi-Fi beacon API (repeated across threads).

*E200:* Expect EU DJI Remote ID coverage to be model/class/firmware dependent (C0 models silent); do not assume every DJI drone seen via OcuSync also shows up as ODID Wi-Fi Beacon.

### MicroPhase GitHub organisation (antsdr-fw, antsdr-fw-patch, antsdr_uhd, antsdr_doc_en)
`3/5` · English · github · 2021-2026 · verified  
<https://github.com/MicroPhase>


The vendor publishes the generic ANTSDR firmware build system, UHD driver and docs, but no DroneID/DJI source; the DroneID decoder binaries were built from a private 'antsdr-fw-patch-drone' tree (per build paths inside the binaries) and are distributed only as SD images via alphafox02 and CrowdSupply.


- Visible repos: antsdr-fw (143 stars), antsdr-fw-patch (106), antsdr_uhd (101), antsdr-pynq, antsdr_doc_en, antsdr_standalone; none mention drone/DJI.
- antsdr_doc_en source tree contains no 'droneid'/'dji' text (grepped after clone).
- CrowdSupply update 'AntSDR E200 - DJI DroneID Detection' (blocked, snippet) says the decoder runs on the E200 ARM core, outputs via serial or network and that 'drones that use OcuSync 2 or 3 like the Mini2 or Mini3Pro work best' because 'DJI has encrypted some models'.

*E200:* You can rebuild the generic PlutoSDR-style firmware (antsdr-fw-patch) to add your own DSP, but the vendor's DroneID DSP cannot be modified or audited.

### TranSIC-Net: Transformer OFDM symbol demodulation validated on DroneID signals (Sensors 2025)
`3/5` · English · paper · 2025 · snippet  
<https://www.mdpi.com/1424-8220/25/20/6488>


Academic paper using DroneID as a test signal; its background section states that DroneID hops over 13 frequency points in 2.4/5.8 GHz, sends 12-20 bursts per point per cycle, and uses 9 OFDM symbols with ZC pilots at symbols 4 and 6 over a 1024-point FFT with ~600 active subcarriers.


- Frequency hopping over 13 frequency points in the 2.4 GHz and 5.8 GHz bands; ~12-20 DroneID signals per point per hopping cycle.
- Nine OFDM symbols per frame, symbols 4 and 6 are ZC pilots with distinct roots, seven QPSK data symbols; 1024-point FFT, ~600 active subcarriers.

*E200:* Independent confirmation of the PHY constants and of the 13-channel hop set (union of the proto17 and DroneSecurity lists).

### alphafox02/dragonsdr_dji_droneid - DragonSDR (WarDragon-branded ANTSDR) DroneID receiver
`3/5` · English · github · 2026 · verified  
<https://github.com/alphafox02/dragonsdr_dji_droneid>


Byte-for-byte the same dji_receiver.py/dragonscope.py as antsdr_dji_droneid, re-branded for the 'DragonSDR' that ships in WarDragon kits, with first-boot auto-config and UDP transport on port 52002. Confirms that DragonSDR = ANTSDR firmware line.


- README differs from antsdr_dji_droneid only in device naming and kit defaults (diffed after cloning); dji_receiver.py identical logic.
- Kit defaults: ipaddr_eth 172.31.100.2, udp_dest 172.31.100.1:52002, gain_mode fast_attack, device_mode auto (5.8 GHz hop), request_time 1 s for O4 telemetry refresh.
- Last commit 2026-08-31.

*E200:* Same as antsdr_dji_droneid; useful only to confirm the UDP variant of the protocol.

### anarkiwi/samples2djidroneid - Dockerised offline DJI DroneID decode from I/Q files
`3/5` · English · github · 2024-2026 · verified  
<https://github.com/anarkiwi/samples2djidroneid>


Apache-2.0 wrapper that builds proto17's Octave scripts and remove_turbo in Docker, patches process_file.m to take CLI arguments, and decodes the resulting FRAME hex with a Python struct copied from Kismet. Only OcuSync 2; only 15.36 or 30.72 MSPS. Maintained by the IQTLabs/gamutRF author, last touched 2026-06-20 (dependabot).


- License Apache-2.0; pins proto17 commit 7fa0fc4; Ubuntu 24.04 + octave + turbofec build.
- Input must be complex float32 at 15.36e6 or 30.72e6 sps (FFT size must be a power of two = Fs/15e3); frames need not be centred.
- Observed: with the drone forced to 5 GHz video, DroneID still appears at 2.4295 GHz among other 2.4 GHz channels.
- Output JSON keys: framelen, msgtype, version, seqno, state_info, serial_no, longitude, latitude, height, altitude, velocity_*, yaw, phone_app_gps_time, phone_app_lat/lon, home_lat/lon, product_type, uuid_length, uuid, crc.
- Warns that detection is slow under co-channel Wi-Fi interference.

*E200:* Quickest way to validate E200 recordings (record at 15.36 or 30.72 MSPS, run the container) before writing anything custom.

### 知乎: DJI大疆OcuSync系列通信协议终极指南 (OcuSync 1.0 / O2 / O3 / O4 guide)
`3/5` · Chinese · blog · 2023 · snippet  
<https://zhuanlan.zhihu.com/p/667452286>


Chinese overview of the OcuSync generations (dual-band 2.4/5.8 GHz, automatic band selection, O3 dual-band MIMO with 10 MHz channels, O4 dynamic band switching); useful for mapping DJI model -> OcuSync generation when deciding which decoders apply.


- OcuSync 2.0: dual-band with automatic band selection; O3: dual-band MIMO, H.265, 28 ms latency claims; O3 products operate on 2.4 and 5.8 GHz with 10 MHz channel bandwidth and dynamic channel selection.
- O4 (Air 3, Mini 4 Pro, Matrice 4) switches between 2.4 and 5.8 GHz dynamically and hops within the band.
- OcuSync uses CP-OFDM and frequency hopping for critical control data; real-time spectrum analysis to switch bands within a video frame time.
- O3 adds triple adaptation (frequency/bit-rate/protocol), OFDM-MIMO, LDPC FEC.

*E200:* Model-to-generation lookup only.

### DeFliTeam/DroneDetection - Kismet-based Wi-Fi DroneID / Remote ID receiver
`2/5` · English · github · 2023-2024 · verified  
<https://github.com/DeFliTeam/DroneDetection>


Raspberry Pi/Jetson build using Kismet, aircrack-ng and Intel 8265 / Panda Wi-Fi cards with LNA/filter chains to catch Wi-Fi Remote ID and DJI enhanced Wi-Fi DroneID (OUI 26:37:12); pulls JSON from the Kismet REST API. No SDR.


- Targets two beacon types: Wi-Fi Remote ID and DJI Wi-Fi DroneID (OUI 26:37:12); Python + kismet_rest; no license; 15 commits, 0 stars.

*E200:* Shows the Wi-Fi-NIC companion path for the DJI Wi-Fi/ODID beacons that the E200 cannot decode natively.

### Drone Detection and Identification Using SDR: Analysis of DJI Mini 2 Drone ID Signals (2025)
`2/5` · English · paper · 2025 · snippet  
<https://www.researchgate.net/publication/391371984_Drone_Detection_and_Identification_Using_SDR_Analysis_of_DJI_Mini_2_Drone_ID_Signals>


Applied study capturing OcuSync 2 with a USRP B210 at 50 MHz and using STFT / Welch PSD to detect DroneID and OcuSync activity in 2.4/5.8 GHz; replicates the RUB approach.


- USRP B210 at 50 MHz sample rate; STFT and Welch PSD used to locate DroneID bursts and OcuSync 2.0 traffic in 2.4 and 5.8 GHz.

*E200:* Confirms 50 MHz-class capture (within the E200's 56 MHz) is a workable front-end bandwidth for the 2.4 GHz DroneID set.

### Habr (news, March 2023): researchers intercept DJI drone signals and obtain pilot location
`2/5` · Russian · blog · 2023 · snippet  
<https://habr.com/ru/news/720088>


Russian coverage of the NDSS/RUB work; together with xakep.ru and securitylab.ru articles it shows the Russian-language community mainly re-reports the GitHub decoder rather than publishing independent tooling. An earlier Habr article (657997) describes Aeroscope's 30-mile DroneID reception.


- DroneID transmits drone and operator coordinates unencrypted; a GitHub tool to decode it was published (RUB-SysSec).
- Aeroscope article: DJI sells Aeroscope to regulators/law enforcement to receive DroneID up to ~30 miles (https://habr.com/ru/articles/657997/).
- Xakep (https://xakep.ru/2023/03/03/droneid-hacked/) and SecurityLab (https://www.securitylab.ru/news/536745.php) repeat the same findings; no Russian/Ukrainian open-source DroneID decoder was found in searches.

*E200:* None technical; confirms the source base is the two GitHub repos.

### Olafseisler/dji-drone-detector - OcuSync downlink detector for HackRF
`2/5` · English · github · 2023 · verified  
<https://github.com/Olafseisler/dji-drone-detector>


Small Python/SoapySDR project that detects the DJI OcuSync downlink (video) signal rather than DroneID, tested with OcuSync <= 2.0 on a HackRF; file and streaming modes.


- Detects DJI OcuSync downlink protocol; tested only with OcuSync <= 2.0; Python 3 with numpy/scipy/matplotlib/SoapySDR; 7 commits, no license shown.
- Entry points read_from_file_blockwise or stream_from_sdr.

*E200:* Marginal; energy/shape-based OcuSync presence detection idea only.

### alphafox02/droneid-go - Open Drone ID receiver (Wi-Fi/BT5) that also ingests DJI DroneID over ZMQ
`2/5` · English · github · 2025-2026 · verified  
<https://github.com/alphafox02/droneid-go>


Go binary (not open source) implementing ASTM F3411-19/22a Wi-Fi beacon/NAN and BT5 LR reception with Sniffle dongles, plus a ZMQ input for DJI DroneID from the ANTSDR receiver; publishes unified JSON on ZMQ 4224 for DragonSync.


- 'droneid-go is not open source at this time'; Linux x86_64/ARM64; needs monitor-mode Wi-Fi and Sniffle-compatible BLE dongle; ZMQ 4224 output, health on 4227; accepts DJI DroneID ZMQ from DragonSDR receiver.

*E200:* Illustrates the integration pattern (DJI over ZMQ merged with ODID) but cannot be reused as code.

### DroneDefence/dji_droneid_antsdr - fork of proto17/dji_droneid
`1/5` · English · github · 2023 · verified  
<https://github.com/DroneDefence/dji_droneid_antsdr>


A fork that surfaces when searching 'ANTSDR DroneID' in Chinese; on inspection it is the proto17/dji_droneid MATLAB/C++/GNU Radio analysis code marked work-in-progress, not an E200 firmware. Low value beyond confirming there is no separate Chinese ANTSDR DroneID firmware fork.


- README identical in substance to proto17 (frequencies 2.3995-2.4595 / 5.7565-5.7965 GHz, 9 symbols, ZC 600/147); no live decoder, no E200 code found.
- README: WORK IN PROGRESS; DJI Mini 2 test recordings at 30.72 MSPS; ZC sequences at symbols 4 and 6, QPSK, 9 OFDM symbols
- No firmware build steps, no E200/ARM/RX2 references

*E200:* None beyond upstream.

### bkerler/dji_droneid - fork of proto17/dji_droneid
`1/5` · English · github · 2023 · verified  
<https://github.com/bkerler/dji_droneid>


Fork by Bjoern Kerler with 194 commits; page shows no documented additions over upstream (same MATLAB/C++/GNU Radio layout).


- No fork-specific README changes visible; same work-in-progress status text.

*E200:* None beyond upstream.


## ANTSDR E200 platform

### MicroPhase/antsdr-fw-patch - PlutoSDR-compatible (libiio) firmware for E310/E200/E310V2
`5/5` · English · github · 2025 · verified  
<https://github.com/MicroPhase/antsdr-fw-patch>


Patch set applied on top of analogdevicesinc/plutosdr-fw v0.39 (submodule branch v0.39) that produces antsdre200.frm/.dfu/.itb and an SD boot image. This is the factory QSPI personality reachable as ip:192.168.1.10 by libiio, gr-iio, pyadi-iio, SoapyPlutoSDR, SDR++/SDRangel.


- Build: Vivado 2023.2 (v0.39), Linaro GCC 7.3-2018.05 external toolchain (Xilinx GCC incompatible with buildroot); export TARGET=e200; sh patch.sh e200; cd plutosdr-fw && sudo -E make; make sdimg for SD boot.
- 'DFU mode is just for e310 e310v2(e316), e200 is unsupport' - the E200 QSPI is updated from a running system (update_frm.sh antsdre200.frm per docs) or via u-boot 'loaddfu' from SD, not via dfu-util.
- 2R2T is off by default (mode=1r1t): enable with fw_setenv attr_name compatible; fw_setenv attr_val ad9361; fw_setenv compatible ad9361; fw_setenv mode 2r2t; reboot (QSPI), or edit uEnv.txt (mode=2r2t, adi_loadvals, add attr_name/attr_val/compatible) for SD boot.
- Releases: v0.34 (Jun), v0.38 (Dec 18), v0.39 (Dec 19) 'firmware of ant and e200 and e310v2', plus 'antsdr-E200-E310-mesh-firmware' tag antsdr_mesh (Jan 13, 4 assets, notes not loadable).

*E200:* The default personality of the user's E200; the toolkit's libiio/pyadi-iio path and the 2-RX enablement procedure come from here.

### MicroPhase/antsdr_doc_en - official ANTSDR documentation source (E200 reference manual, UHD, libiio, IP, clock calibration, GPIO, schematic, demos)
`5/5` · English · doc · 2025 · verified  
<https://github.com/MicroPhase/antsdr_doc_en>


Sphinx source of antsdr-doc-en.readthedocs.io, cloned and read. Contains the E200 hardware manual, RF-parameter/selection table, unboxing guide (boot switch, credentials), UHD/libiio/GNU Radio pages, IP/MAC setting, clock calibration via the ad5660mp IIO device, GPIO, plus demo C code (demo/iio/main.c, demo/uhd/main.cpp) and the public schematic.


- E200: Zynq 7020, AD9361 (70 MHz-6 GHz, 200 kHz-56 MHz analog BW) or AD9363, 12-bit ADC/DAC, 1 GbE, USB-C UART, 8 GPIO, 1 PPS/10 MHz input, PS DDR3 512 MB (E310: 1 GB).
- Selection table: E200 'RF channel: SMA:1T1R IPEX:1T1R', 'Transmission bandwidth to host: 20MSPS' (E310: 10 MSPS, E316: 20 MSPS), 'API: Libiio & UHD'.
- Factory state: Pluto firmware in QSPI; DIP switch under the Ethernet port labelled BOOT/QSPI/SD; Pluto fw IP 192.168.1.10, root/analog, 115200 baud, CH340 USB-UART; UHD firmware 'can only be started under the SD card', login root/microphase, IP set with 'ip_set 192.168.1.10'.
- Permanent IP change on Pluto fw: fw_setenv ipaddr_eth <ip>; MAC: fw_setenv ethaddr ...; SD boot: edit uEnv.txt (ethaddr=...).
- Clock calibration: IIO device ad5660mp with in_voltage_dac_mode (0 auto/1 manual, default manual, DAC 23000), in_voltage_dac_ref_sel (0:10M 1:PPS 2:GPS), in_voltage_dac_locked; 10 MHz reference via SMA-to-MMCX cable on the 10/PPS port.
- Pluto-fw GPIO: EMIO gpio 995-1002 via /sys/class/gpio; iio devices listed: ad9361-phy, mp-gpio, xadc, ref-pll, cf-ad9361-dds-core-lpc, cf-ad9361-lpc.
- GNU Radio: gr-iio is built into GNU Radio >= 3.10; PlutoSDR Source parameters: RF bandwidth, sample rate, LO, tracking (quadrature, RF DC, BB DC), gain mode manual/slow_attack/hybrid/fast_attack, FIR filter file; FMCOMMS firmware (Kuiper image) 'supports 2T2R operation at a 61.44Msps sampling rate' on-board.
- 'Xilinx Zynq 7020 (integrated dual-core ARM Cortex-A9 and Artix-7 FPGA)'; 'Analog Devices AD9361/9363'; '1 Gigabit Ethernet interface'.
- _(6 more facts in the JSON index)_

*E200:* Ground truth for all setup steps in a getting-started toolkit: boot modes, credentials, IPs, 2nd channel location, host-rate spec, reference-clock discipline.

### MicroPhase/antsdr_uhd - UHD host driver + firmware for ANTSDR E200/E310V2
`5/5` · English · github · 2026 · verified  
<https://github.com/MicroPhase/antsdr_uhd>


Official UHD firmware/driver for the E200 (SD-card image, static IP 192.168.1.10, 1000M Ethernet only, uhd_find_devices). This is the backend fpv-sdr uses for the E200 and the path that makes gr-ieee802-11, DroneSecurity (UHD python) and other USRP-oriented code run on the E200. A Pluto-compatible IIO firmware (antsdr-fw-patch) is the alternative.


- Quick start: download v1.0 build_sdimg.zip, copy bitstream/devicetree/kernel/BOOT.bin to a FAT32 SD card, boot from SD; default static IP 192.168.1.10; Ethernet link must be 1000M.
- Host driver is Ettus UHD with an added E200 interface; releases: v0.1 'e200 uhd (firmware release)' and v1.0 (buildroot rootfs with SSH, UHD 4.1.0.0, adds E310V2 and U220); '174 commits to master since v1.0'.
- Open issues include #102 'antsdr_uhd fpga build causes critical timing closure warnings on 2019.1', #103 'Running UHD software locally on AntSDR', #98 'No UHD Devices Found', #108 'Issue with E200' (closed May 2026).
- Repo contains firmware/ (FPGA, u-boot, kernel, buildroot) and host/ (UHD with E200 support); release v1.0 build_sdimg.zip.
- uhd_find_devices discovers the E200 on the LAN at 192.168.1.10 by default.
- Supports ANTSDR-E200 and ANTSDR-E310v2; default IP 192.168.1.10; 'ethernet ... can only works at 1000M speed'.
- Flash by copying release build to FAT32 SD card; verify with ping / uhd_find_devices.
- IIO firmware 'compatible with plutosdr firmware' available in antsdr-fw-patch; ecosystem: GNU Radio, DragonOS, srsRAN_4G.
- _(8 more facts in the JSON index)_

*E200:* Primary UHD path for the E200; use it when the toolkit should be USRP-API based (GNU Radio uhd blocks, SoapyUHD, srsRAN, ICE9).

### alphafox02/antsdr_dji_droneid - ANTSDR E200 DJI DroneID detection firmware + host receiver (WarDragon/DragonSync)
`5/5` · English · github · 2026 · verified  
<https://github.com/alphafox02/antsdr_dji_droneid>


The de-facto E200 DroneID stack: two closed-source MicroPhase firmware SD images (legacy 'done_dji_release' 2024-03-06, and O4-aware 'drone_dji_rid_decode' 2026-01-14) plus a Python host bridge (dji_receiver.py) that turns the board's TCP/UDP output into an Open-Drone-ID-shaped JSON list on ZMQ port 4221 for DragonSync/Kismet/TAK. O2/O3 are fully decoded on the ARM core; O4 gives only a per-session hash, frequency and RSSI unless the paid DragonScope cloud service is used. Actively maintained (last commit 2026-08-31).


- Install: extract zip to SD root, switch to SD, power on. Config once via serial (tio /dev/ttyUSB0, root/analog in QSPI mode): fw_setenv ipaddr_eth, tcp_serverip, tcp_serverport 52002, gain_mode fast_attack, heart_beate_time 30, api_host, request_time 1, auth_secret, token_secret, device_serial, device_mode auto ('auto' hops 5.8 GHz channels); new firmware SSH is root/'1'; defaults to 192.168.1.10 if ipaddr_eth unset.
- Legacy firmware: AntSDR is a TCP server on port 41030 sending binary frames (FFT-based detection + OFDM decode); new firmware: AntSDR connects OUT to tcp_serverip:52002 and sends text CSV (fields: ..., freq, rssi, ..., drone lon/lat, pilot lon/lat, home lon/lat, height\|..., speed\|...); DragonScope variant uses UDP 52002.
- Supported: O2/O3 unencrypted (Mini 2, Mini 3 Pro, Air 2S, Mavic 3) with serial, model, drone/pilot/home GPS, altitude, speed, RSSI; O4 encrypted (Mini 5) only hash ID + frequency + RSSI unless the proprietary DragonScope licence/firmware is used; 'DJI drones only broadcast DroneID when motors are spinning'.
- On-board init chain S55drone -> droneangle.sh -> daemon, watchdog respawns every second; service_controller.sh stops/starts it. Kismet capture only works with the legacy 41030 binary protocol.
- uEnv.txt in both images is the stock antsdre200 Pluto-style environment (mode=1r1t, maxcpus=1, loaddfu writes antsdre200.dfu to QSPI) - i.e. the DroneID image is a modified Pluto-firmware build, not UHD.
- Repo cloned; last commit 2026-08-31; no LICENSE file at repo root (service_controller.sh carries an MIT header); author notes WarDragon Pro/Elite kits contain proprietary capabilities not in the repo.
- Firmware zips: build_sdimg_drone_net.zip (files dated 2024-03-06) -> /usr/sbin/done_dji_release (legacy, TCP server on 41030, binary frames) and build_sdimg_drone_o4.zip (2026-01-14) -> /sbin/drone_dji_rid_decode (new, TCP client to fw_setenv tcp_serverip:tcp_serverport=52002, text CSV; DragonScope variant sends UDP). uEnv.txt in both images sets mode=1r1t and maxcpus=1 (single RX channel, single core).
- Strings in both binaries (extracted from the ramdisks): libiio + libfftw3f only (no GNU Radio), AD9361 path clocks 'RRX 983040000 245760000 122880000 61440000 61440000 61440000' (i.e. 61.44 MSPS baseband), functions set_zc600/set_zc147, lte_rate_match_rv, lte_turbo_decode, Decoder::gold/magic/magic_soft/calculateLLR (soft-decision turbo on ARM), get_long_cp_len/get_short_cp_len, cfo_correct, cross_correlation_find_peak_by_fft; legacy binary opens /dev/my-axi-droneid-filter0 (custom FPGA filter). Build path '/home/jcc/work/Git/mp/antsdr-fw-patch-drone/...' shows a private tree, not on MicroPhase GitHub.
- _(13 more facts in the JSON index)_

*E200:* Ready-made DJI DroneID detector for the E200 that could feed AERIX's future_sdr receiver class; its ZMQ JSON is a natural integration point, but it is single-purpose (no raw IQ while running).

### ant_impl.cpp - E200 UHD device implementation (channels, rate limits, transport)
`5/5` · English · github · 2026 · verified  
<https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp>


Driver source that defines the RX antenna options and the AD9361 chain enabling logic. RX direction offers {TX/RX, RX2}; selecting RX2 sets perif.ant_rx2 and switches the FPGA RF state machine to STATE_RX1_RX2 / STATE_RX2_RX2. Confirms the second receive path is selectable from software under UHD (set_rx_antenna("RX2")).


- '_product = B210; // The RF/DSP structure is B210-compatible' with _fe1=0,_fe2=1; enforce_tick_rate_limits: max_chans = 2, max tick rate = AD9361_MAX_CLOCK_RATE (61.44 MHz) / 2 when 2 channels are used, i.e. 30.72 MHz per channel; '2 RX 1 TX and 1 RX 2 TX configurations not possible'.
- UDP ports: FIND 49100, CTRL 49200, DATA_TX 49202/49203, DATA_RX 49204; default transport recv_buff_size/send_buff_size 1e6 bytes, 16 frames of MTU size (overridable via device args recv_buff_size=).
- check_fpga_compat expects B200_FPGA_COMPAT_NUM = 16 for the B210 flow (the older doc/probe output shows 'FPGA Version: 7.0' with '_Product B205MINI(COMPATIBLE)', i.e. the B205 compat 7 flow) - host and FPGA must come from matching revisions or probing throws 'Expected FPGA compatibility number'.
- Discovery reply carries a board_version string; if it does not start with 'E' the product defaults to E200; only 'E310  v2' is marked GPSDO-capable.
- RX antennas: std::vector<std::string>{"TX/RX", "RX2"}; TX only "TX/RX" (lines 968-969)
- set antenna rejects anything but TX/RX or RX2 (line 1378); ant_rx2 flag drives STATE_RX1_RX2 vs STATE_RX1_TXRX (1336-1358)
- set_active_chains(enb_tx1, enb_tx2, enb_rx1, enb_rx2) supports two RX chains (1393-1405)
- Host README test: two E200s at 7.68 MS/s each gave ~492 Mbit/s aggregate sc16 RX payload (from https://raw.githubusercontent.com/MicroPhase/antsdr_uhd/master/host/README.md)

*E200:* Defines what the toolkit can ask of the E200 under UHD: 2 coherent RX channels at <=30.72 MSPS each or 1 channel at <=61.44 MSPS (before Ethernet limits), and which UDP ports must be open.

### ant_io_impl.cpp - RX streamer: OTW formats sc16/sc12/sc8/fc32, spp, flow control
`5/5` · English · github · 2026 · verified  
<https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_io_impl.cpp>


Streamer setup for the ANTSDR UHD driver. Shows that the over-the-wire sample format is programmable per radio (SR_RX_FMT register) and that the E200 build uses FPGA source flow control with a host-side credit window.


- otw_format defaults to sc16; 'sc16' -> SR_RX_FMT=0, 'sc12' -> 1, 'fc32' -> 2, 'sc8' -> 3 (poke32 to the radio core), so 8-bit and 12-bit wire formats are accepted by the driver (FPGA-side packing inherited from Ettus radio_legacy; not benchmarked in any source found).
- spp = min(4092, (recv_frame_size - hdr)/bytes_per_item) - 'FPGA FIFO maximum for framing at full rate'; with a 1500-byte MTU this is ~360 samples/packet for sc16.
- 'ANTSDR-E200 builds radio_legacy with SOURCE_FLOW_CONTROL enabled' and the host returns credits (ANT_RX_FC_WINDOW_PACKETS/ANT_RX_FC_UPDATE_PACKETS); E310V2 uses a different FPGA configuration and must not receive these packets.
- set_auto_tick_rate throws 'Requested sampling rate exceeds maximum tick rate' if rate > 61.44e6/num_chans.

*E200:* Tells the toolkit how to lower Ethernet load (otw_format=sc8 or sc12 in stream args) and that host UDP buffers/MTU determine packet size and overflow behaviour.

### antsdr_uhd host README - build flags, product= key, dual-E200 stress test
`5/5` · English · doc · 2026 · verified  
<https://github.com/MicroPhase/antsdr_uhd/blob/master/host/README.md>


Build instructions for the ANTSDR-enabled UHD (cmake -DENABLE_ANT=ON -DENABLE_USB=ON, install to /opt/antsdr-uhd) and MicroPhase's own long-duration test scripts. Contains the only vendor-published wire-rate arithmetic for the E200.


- uhd_usrp_probe --args="addr=192.168.1.10,product=E200" - the product key selects the E200 FPGA flow-control behaviour when discovery metadata is absent.
- The ANT component has a build-time dependency on ENABLE_USB; do not mix these UHD 4.1 tools/libuhd with applications linked against UHD 4.9 (ABI mismatch).
- Stress test default: --rate 7.68e6 --channels 0 per device, 'about 492 Mbit/s of aggregate sc16 RX payload for two devices' (i.e. ~246 Mbit/s per E200 at 7.68 MSPS sc16); aggregate wire rate = devices x channels x rate x 32 bit.
- Board SSH password for the UHD firmware is 'microphase' (ANTSDR_SSH_PASSWORD=microphase).

*E200:* Gives the exact host build recipe and a vendor-validated 7.68 MSPS/device baseline for a multi-E200 GbE deployment.

### jonkraft/Pluto_Beamformer - DIY 2-element digital beamformer/DoA with ADALM-PLUTO rev C (2 RX)
`5/5` · English · github · 2023 · verified  
<https://github.com/jonkraft/Pluto_Beamformer>


Analog Devices engineer Jon Kraft's Python scripts (pyadi-iio) doing phase-sweep DoA, monopulse tracking and MVDR DoA with the two RX channels of one AD9361. Because the E200's IIO firmware presents the same adi.ad9361 interface over Ethernet, these scripts are the most direct 2-antenna interferometry starting point for the E200.


- Uses rx_enabled_channels=[0,1] on an AD9363/AD9361 with the 2nd RX on U.FL; implements a phase-calibration step and DOA peak plot (Pluto_beamformer_PlotPeaks_youtube.py).
- ADI EZ answer: the two RX channels of Pluto rev C 'are coherent'.
- Pluto_MVDR_DOA.py: 'my_sdr = adi.ad9361(uri=sdr_ip)', 'my_sdr.rx_enabled_channels = [0, 1]  # enable Rx1 and Rx2', 'd = c/(2*center_freq) # distance between Rx antennas in meters. Set d to c/(2*f)', 'phase_offset = -0.3  # calibration between the two Rx channels in rad', 'Nr = 2  # number of receive channels'.
- Pluto_beamformer_PlotPeaks_youtube.py: 'samp_rate = 2e6    # must be <=30.72 MHz if both channels are enabled'; 'd_wavelength = 0.5 # distance between elements as a fraction of wavelength. This is normally 0.5'; discards 20 buffers: '# let Pluto run for a bit, to do all its calibrations, then get a buffer'.
- DoA estimate obtained by sweeping delay_phases = arange(-180,180,2) applied to Rx_1 (plus phase_cal) and maximising the summed FFT peak; steering angle via arcsin(phase*c/(2*pi*f*d)).
- MVDR weights w = R^-1 s / (s^H R^-1 s) computed on 2x2 covariance; conventional and MVDR spectra scanned -90..+90 deg.
- README: 'part of a video series where we use the ADALM-PLUTO rev C to build a low cost digital phased array beamformer'.

*E200:* Directly portable to the E200 (same AD936x IIO stack) for a 2-antenna bearing estimate of drone links.

### open-sdr/openwifi - Linux mac80211 802.11 SDR stack; antsdr_e200 supported board
`5/5` · English · github · 2024 · verified  
<https://github.com/open-sdr/openwifi>


Full 802.11a/g/n SDR NIC for Zynq+AD9361 boards, with the MicroPhase ANTSDR E200 as a supported board (kernel_boot/boards/antsdr_e200). In monitor mode the FPGA passes every received frame (including bad-CRC frames and control frames) to Linux mac80211, so standard pcap tools can capture RID beacons on the E200 itself with no IQ streaming. Cloned and read.


- Board table row: 'antsdr_e200 \| MicroPhase enhanced ADALM-PLUTO (smaller/cheaper) \| NO need' (Vivado licence); build docs say install Vivado 2021.1 with Vitis.
- README: 'Mode tested: Ad-hoc; Station; AP, Monitor'; monitor_ch.sh and inject_80211 app note; real-time CSI notes.
- antsdr_e200 board README: 'The ethernet is placed at the PL side ... above 20MSPS sample rate ... bandwidth of the Ethernet will reach 80MB/s ... we moved the network port to the PL side. But this has no effect on IIO-based SDR drivers, because we still use ZYNQ's GEM controller' (openwifi-hw copy says 15 MSPS / 60 MB/s).
- antsdr (E310) notes.md: RF switch is fixed to the >3 GHz path (blocks <3 GHz) - a quirk to check on E200 when using openwifi at 2.4 GHz.
- Docs (antsdr_doc_en E310 page): image written with dd, copy BOOT/openwifi/AntSDR_e200 files to BOOT partition, login password 'openwifi', board IP 192.168.10.122, ./openwifi/setup_once.sh, wgd.sh, fosdem.sh.
- antsdr_e200 entry: 'MicroPhase enhanced ADALM-PLUTO (smaller/cheaper)' with board notes in kernel_boot/boards/antsdr_e200
- Also lists neptunesdr and LibreSDR (Zynq 7020 + AD9361) as unofficial boards
- Board table lists 'antsdr_e200 \| MicroPhase enhanced ADALM-PLUTO (smaller/cheaper)' with no Vivado licence needed; board notes say the E200 Ethernet sits on the PL side because >20 MSPS over PS Ethernet (80 MB/s) is impractical for the Zynq CPU
- _(3 more facts in the JSON index)_

*E200:* Gives a Wi-Fi monitor-mode personality for Beacon/NAN Remote ID sniffing on the same hardware; mutually exclusive with IIO/UHD streaming (separate SD image).

### ADI whitepaper - Phase Synchronization Capability of AD9361 for DoA
`4/5` · English · doc · 2016 · snippet  
<https://wiki.analog.com/_media/resources/tools-software/linux-software/doa_whitepaper.pdf>


ADI's description of phase alignment across AD9361 channels (blocked domain; facts from search snippets). Key caveat for using the E200's 2 RX for direction finding.


- 'When using the internal LOs multiple transceivers will have a random phase relationship, which will change when LO is changed, sample rate is changed, gain (in some cases) is changed, and even during quadrature tracking'.
- 'Phase synchronization is valid until the LOs are retuned or sample rates change or gains are modified' - so calibration must be repeated after every retune.
- Within one AD9361 both RX channels share the RX LO (chip PLL); a fixed but unknown offset remains and is removed by calibration (FMComms5 phase-sync procedure).

*E200:* A scanning drone detector that hops LO frequencies will need per-hop phase calibration (or a reference injection) before any DoA from RX1/RX2 is trusted.

### ANT-E200 public (development) schematic Rev 1.0, 15/7/2022
`4/5` · English · doc · 2022 · verified  
<https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf>


15-page development schematic (full HW schematics are not open). Text extracted from the cloned PDF confirms the clock tree, RF connector routing, Ethernet PHY, flash and DDR parts.


- CLOCK page: 'DEFAULT: TCXO +/-0.5PPM', 'OPTIONAL1: VCTCXO +/-0.28PPM', X1 = 40M oscillator, U60 DAC (AD5660 per docs) with DAC_DIN/SCLK/nSYNC lines, REF_CLKIN_10M / PPS via J18 MMCX-KE, REF_CLK_REQ enables external clock.
- RF page: RX1/TX1 and RX2/TX2 with RX2A/TX2A pairs going to J5/J6 U.FL connectors (2 U.FL) while RX1/TX1 go to SMA; TX_AMP_EN gates a TX PA; balun front-end.
- Ethernet PHY RTL8211F (RGMII to PL), QSPI W25Q256 (32 MB), DDR3 MT41K256M16 (512 MB), Zynq XC7Z020, I2C EEPROM (used for IP storage by the UHD firmware).
- The public schematic symbol is drawn as AD9363; the AD9361 variant uses the same footprint (docs list AD9361/9363 as options).

*E200:* Confirms that a 2-antenna coherent setup requires a pigtail on the internal U.FL RX2, and that the reference is a 0.5 ppm TCXO unless disciplined by 10 MHz/PPS.

### Kismet capture_antsdr_droneid.c - datasource for the legacy AntSDR DroneID firmware
`4/5` · English · github · 2024 · verified  
<https://github.com/kismetwireless/kismet/blob/master/capture_antsdr_droneid/capture_antsdr_droneid.c>


Kismet's C capture source connects to the E200's legacy firmware TCP port and parses its binary frames into JSON for the UAV phy. It documents the exact legacy wire format and explicitly discards 'encrypted' (non-UTF-8) records. Shipped in Kismet 2025-09-R1 as kismet_cap_antsdr_droneid.


- Source definition: antsdr-droneid:host=<ip>,port=<port>; hardware string 'antsdr-droneid'.
- Frame header struct {uint16 header; uint8 packet_type; uint16 length; data[]} packed LE; payload struct antsdr_droneid {char serial[64]; char device_type[64]; uint8 device_type_8; double app_lat, app_lon, drone_lat, drone_lon, height, altitude, home_lat, home_lon, freq, speed_e, speed_n, speed_u; uint32 rssi}.
- dji_receiver.py parses the same layout (serial at [0:64], app_lat at data[129:137] ... rssi int16 at [225:227]).
- Source definition: antsdr-droneid:host=<ip>,port=<port> (both mandatory).
- Frame header (little-endian, packed): uint16 header, uint8 packet_type, uint16 length; only packet_type 0x01 is handled.
- Payload struct: char serial[64], char device_type[64], uint8 device_type_8, doubles app_lat, app_lon, drone_lat, drone_lon, height, altitude, home_lat, home_lon, freq, speed_e, speed_n, speed_u, uint32 rssi (alphafox02 reads rssi as int16 at the same offset).
- Records whose serial/device_type are not valid UTF-8 are dropped with the comment 'Possibly encrypted droneid has invalid data'.
- Emits JSON with json_type 'antsdr-droneid' (fields serial_number, device_type, drone_lat/lon/height/alt, home, app, freq, speed_e/n/u, rssi) via cf_send_json; phy_uav_drone.cc turns it into uav.device telemetry with synthesised MAC and heading/speed from velocity.

*E200:* Exact wire format if the toolkit wants to ingest the legacy on-board decoder directly instead of via dji_receiver.py.

### antsdr_uhd firmware README - Vivado/SDK 2019.1 SD image build
`4/5` · English · doc · 2026 · verified  
<https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/README.md>


Describes the one-command firmware build (scripts/build_image.sh e200) producing BOOT.bin, antsdr.bit, uImage, uEnv.txt, devicetree.dtb, uramdisk.image.gz for the SD FAT partition. Uses Vivado/SDK 2019.1 and buildroot (not PetaLinux).


- Toolchain: Vivado 2019.1 + SDK 2019.1, part xc7z020clg400-2, ARM cross-compiler from SDK 2019.1; rootfs is buildroot (VERSIONS file: hdl 2019_r2, linux adi-xilinx-2020.1, u-boot v0.20-PlutoSDR).
- Default Ethernet address 192.168.1.10/24; bitstream name antsdr.bit must match uEnv.txt; rootfs is loaded as uramdisk.image.gz from the boot partition (no ext4 partition).
- The E200 FPGA project is built with verilog define TARGET_B210=1 (two radio_legacy instances) and PROTOCOL=1GbE RGMII; PL clocks derived from CLK_40MHz_FPGA.
- On-board IP is persisted by the 'ip_set <ip>' tool which writes to the I2C EEPROM at /sys/bus/i2c/devices/0-0050/eeprom.

*E200:* Needed if the toolkit will rebuild or customise the UHD FPGA image (e.g. to add on-board detection logic).

### hz12opensource/libresdr - 27.5 MSPS over GbE with libiio on a Zynq-7020/AD9361 Pluto clone
`4/5` · English · github · 2024 · verified  
<https://github.com/hz12opensource/libresdr>


Firmware fork for LibreSDR (same Zynq 7020 + AD9361 + GbE class as the E200) that raises continuous libiio streaming from stock ~11-12 MSPS to 20 MSPS (default) and 27.5 MSPS (overclocked). Best available quantitative reference for what the Pluto/IIO personality can do over Ethernet.


- Stock firmware ~11-12 MSPS continuous; optimized kernel/buildroot 20 MSPS at 750 MHz CPU / 525 MHz DDR; 27.5 MSPS with CPU 1100 MHz / DDR 750 MHz overclock.
- Uses AD9361 LVDS mode to maximize 2T2R; recommends SDR++ buffer of 1,000,000 samples; author says the limit became the host ('Ethernet running at ~900Mbps').
- Patches are LibreSDR-specific but the techniques (iiod/kernel tuning, larger buffers) apply to other Zynq-7020/AD9361 boards.

*E200:* Sets realistic expectations: stock IIO firmware ~11-12 MSPS sc16 single channel; ~20 MSPS needs iiod/kernel work; anything above needs UHD or on-board processing.

### libiio discussion #875 - Stream throughput benchmark (includes Zynq-7000/ANTSDR over 1 GbE)
`4/5` · English · github · 2024 · verified  
<https://github.com/analogdevicesinc/libiio/discussions/875>


Community benchmarks of the libiio network backend on Zynq-7000 devices including an ANTSDR, comparing libiio 0.23 and 1.0 and listing the optimizations that matter (block size, -O3, CPU affinity, zero-copy).


- Zynq-7000/ANTSDR over 1G Ethernet: libiio 0.23 host ~44.7 MB/s (~11 MSPS sc16, 1 ch); libiio 1.0 device-only 63.4 MB/s; libiio 1.0 both sides 48-52 MB/s, 82-84 MB/s after optimizations (~20 MSPS).
- LibreSDR: stock ~47 MB/s, optimized 108 MB/s (27 MSPS); Pluto USB 2.0 ~48 MB/s.
- Bottleneck: 'large portion of CPU cycles are spent on copying data from memory to TCP socket'; larger block sizes, pinning iiod to a core, and -O3 help.

*E200:* Quantifies the IIO ceiling on the E200 class and argues for libiio >= 1.0 on both host and device firmware.

### pyadi-iio adi/ad936x.py - ad9361/ad9364/Pluto classes
`4/5` · English · github · 2025 · verified  
<https://github.com/analogdevicesinc/pyadi-iio/blob/main/adi/ad936x.py>


Python API used with the Pluto-compatible firmware over ip:192.168.1.10. The ad9361 class exposes both RX channels and per-channel gain controls.


- ad9364: _rx_channel_names ['voltage0','voltage1'] (I/Q of one RX); ad9361: ['voltage0'...'voltage3'] i.e. two complex RX; properties gain_control_mode_chan0/1, rx_hardwaregain_chan0/1, rx_lo, rx_rf_bandwidth, sample_rate; Pluto class adds FPGA filter support.
- Typical usage: sdr = adi.ad9361(uri='ip:192.168.1.10'); sdr.rx_enabled_channels = [0, 1]; sdr.rx() returns both channels (requires 2r2t on the board).

*E200:* Fastest way to script dual-channel captures and gain/AGC experiments on the E200.

### BatchDrake/AntSDRPlugin - SigDigger plugin: dual-RX AntSDR/Pluto source with phase comparison
`3/5` · English · github · 2024 · verified  
<https://github.com/BatchDrake/AntSDRPlugin>


SigDigger plugin by the SigDigger author that opens an AntSDR/Pluto with dual RX via libiio/libad9361 and visualizes the RX1-RX2 phase difference (YIQ colour wheel). Demonstrates practical 2-RX coherent capture on AntSDR through the IIO firmware.


- Requires 'AntSDR/Pluto with dual RX enabled' (2r2t), libiio and libad9361; default URIs ip:192.168.1.10 (Ethernet) / 192.168.2.1 (USB).
- Author notes elsewhere that he used an AntSDR E310 with 2r2t and a hack to SigDigger.

*E200:* Reference implementation for a phase-difference (bearing) display using the E200's two RX chains.

### Crowd Supply - AntSDR E200 campaign page and updates (Answering Your Questions, Some Key Features, Bluetooth sniffer, openwifi, DroneID)
`3/5` · English · vendor · 2023 · snippet  
<https://www.crowdsupply.com/microphase-technology/antsdr-e200>


Vendor campaign page plus updates. Domain blocked; facts from search snippets. Confirms connectors, clock spec, GPSDO accuracy claim, and that ICE9 Bluetooth sniffer works with the UHD firmware.


- '2x2 MIMO with two SMA antenna connectors and two U.FL connectors', gigabit Ethernet 'with an offload engine to improve throughput'; FPGA: 85K logic cells, 53,200 LUT, 220 DSP, 4.9 Mb BRAM.
- AD9363 variant $299 (325-3800 MHz, 20 MHz), AD9361 variant $499 (70 MHz-6 GHz, 56 MHz), 12-bit, 200 kS/s-61.44 MS/s.
- '40 MHz TCXO with +/-0.5 ppm'; with a GPSDO providing 10 MHz + PPS 'the accuracy of the local oscillator can reach +/-10 ppb'.
- ICE9 Bluetooth sniffer example with the UHD firmware: ./ice9-bluetooth -l -c 2427 -C 20 -i usrp- (20 BLE channels = 20 MHz) - a UHD-firmware use that resembles wideband drone-link capture.

*E200:* Marketing-level specs and two worked UHD/openwifi examples; treat throughput claims as unverified.

### EngineerZone - Pluto Rev C coherent reception using 2 RX channels
`3/5` · English · forum · 2023 · snippet  
<https://ez.analog.com/adieducation/university-program/f/q-a/566569/pluto-rev-c-coherent-reception-using-2-rx-channels>


ADI Q&A confirming that the two RX channels of a single AD9361/AD9363 are coherent (shared LO); page blocked, facts from snippets.


- 'When asked about coherence of the two receive channels, the answer is yes, they are coherent'.
- A separate EZ thread notes that for DF across multiple chips an external LO/sync is required; not needed within one chip.

*E200:* Supports using E200 RX1+RX2 (same AD9361) for 2-element interferometry without external LO hardware.

### MicroPhase/antsdr_fmcomms - FMCOMMS2/3/4-style Kuiper Linux image boot files for ANTSDR
`3/5` · English · github · 2023 · snippet  
<https://github.com/MicroPhase/antsdr_fmcomms>


Boot files that let the ADI Kuiper Linux image run on ANTSDR so the board behaves like an FMCOMMS2/3 (full Linux, IIO local context). Docs claim 2T2R at 61.44 Msps on-board.


- Docs: 'The ANTSDR FMCOMMS2/3/4 image supports 2T2R operation at a 61.44Msps sampling rate'; image written with dd, boot files from MicroPhase cloud storage copied to BOOT; static IP set in /etc/network/interfaces.
- E200 and E310 boot files differ.

*E200:* A full-Debian on-board personality for running libiio-based detectors locally on the ARM core at full AD9361 rate (no Ethernet bottleneck).

### MicroPhase/antsdr_standalone - bare-metal (no-OS) ADI HDL projects for E310/E200/E316
`3/5` · English · github · 2023 · verified  
<https://github.com/MicroPhase/antsdr_standalone>


Vivado 2021.1 / Vitis 2021.1 projects (hdl/project/antsdre200, app_e200) based on ADI HDL + no-OS 'based on ADRV9361, 2R2T', controllable over serial for LO/rate/gain. Path for custom Zynq applications without Linux.


- Requires Vivado 2021.1 and Vitis 2021.1; build via source ../scripts/adi_make.tcl; adi_make::lib all; source ./system_project.tcl in hdl/project/antsdre200.
- App folders app_e200/app_e310/app_e316; exported .xsa used to create the Vitis platform.

*E200:* Starting point if the toolkit ever moves detection into custom PL/no-OS code on the E200.

### RTL-SDR.com - DJI DroneID detection running on the AntSDR E200 CPU
`3/5` · English · blog · 2024 · snippet  
<https://www.rtl-sdr.com/dji-droneid-detection-running-on-the-antsdr-e200-cpu>


News item on MicroPhase's on-board DroneID decoder (decoder on the ARM core, output via serial or network), based on proto17/dji_droneid and RUB-SysSec/DroneSecurity. Domain blocked; facts from snippets.


- 'The AntSDR team managed to get DJI DroneID decoding working on the AntSDR's onboard ARM processor ... outputting decoded data via the serial or network port'.
- 'Drones that use Occusync 2 or 3 like the Mini2 or Mini3Pro work best, because other models may be encrypted'; MicroPhase provided a test firmware via Google Drive.

*E200:* Origin of the legacy DroneID firmware; no public source found for the MicroPhase decoder binary.

### RadioReference - Phase noise issue with ANTSDR E200 vs Pluto SDR
`3/5` · English · forum · 2025 · snippet  
<https://forums.radioreference.com/threads/phase-noise-issue-with-antsdr-e200-vs-pluto-sdr.502838>


User report that a 1 GHz LO / 1 MHz tone looks much wider (visible phase noise) on the E200 than on a Pluto with 0.5 ppm TCXO; tested disciplined/undisciplined and modified the DAC loop filter without improvement. Domain blocked; snippets only.


- Pluto: 'very sharp peak with no visible phase noise'; E200: 'much wider and contains noticeable phase noise'.
- User modified the U60 DAC output filter cutoff from 300 Hz to 0.72 Hz - no change; no resolution reported.

*E200:* Flag for the toolkit: close-in phase noise may be worse than Pluto; matters for narrowband telemetry decoding and for phase-based DoA.

### SDR++ issue #1478 - Support AntSDR default firmware and device string in scanning
`3/5` · English · github · 2025 · verified  
<https://github.com/AlexandreRouma/SDRPlusPlus/issues/1478>


Shows how the AntSDR IIO firmware identifies itself on the network and why SDR++'s Pluto module filters it out.


- iio_info -S finds '[ip:ant.local] 192.168.1.10 (Analog Devices ANTSDR Rev.C (Z7020-AD9361)), serial=db61bc88071e3a26'.
- SDR++ logs 'Ignored IIO device ... (Analog Devices ANTSDR Rev.C (Z7020-AD9361))' because it looks for 'PlutoSDR' in the string; open enhancement, no resolution in the issue.

*E200:* Any toolkit code that auto-discovers Pluto devices must match 'ANTSDR' too (or use an explicit ip: URI / ant.local mDNS).

### openwifi releases - v1.4.0 Notter (adds antsdr_e200), v1.5.0 Shahecheng
`3/5` · English · github · 2024 · verified  
<https://github.com/open-sdr/openwifi/releases>


Release history relevant to the E200 image.


- v1.4.0 (2023-01-28): Vivado 2021.1; boards added Sdrpi, antsdr_e200, neptunesdr, PYNQSDR; single SD image for 32/64-bit; flashed with 'sudo dd bs=512 count=31116288 if=openwifi-1.4.0-notter.img'.
- v1.5.0 (2024-08-06): Vivado 2022.2 with ADI Kuiper 2022_R2; 'Zynq 7020 (lowest-end supported)', antsdr e310v2 added; better multipath DSP, deterministic ADC/DAC timing for MIMO.
- v1.2.0/1.3.0: 802.11n, arbitrary packet injection, CSI extraction, IQ capture with real-time AGC, CSI radar.

*E200:* Pick v1.4.0 or newer image; check that antsdr_e200 boot files are still shipped in the newest image.

### AUR libuhd-antsdr-git - packaging of the ANTSDR UHD fork
`2/5` · English · other · 2024 · snippet  
<https://aur.archlinux.org/packages/libuhd-antsdr-git>


Arch packaging of a btashton fork of antsdr_uhd; comments document the practical pain points of the UHD 4.1-based fork on modern distros.


- 'As of boost 1.85.0, the package can't compile since it needs boost/filesystem/convenient.hpp'; GNU Radio must be rebuilt against this libuhd for the uhd blocks to see the E200.

*E200:* Toolkit should pin a known-good distro/boost or ship a container for the ANTSDR UHD build.

### CNX Software - AntSDR E200 Gigabit Ethernet SDR (Zynq 7020, 70 MHz-6 GHz)
`2/5` · English · blog · 2023 · snippet  
<https://www.cnx-software.com/2023/07/03/antsdr-e200-gigabit-ethernet-connected-sdr-with-xilinx-zynq-soc-fpga-supports-70-mhz-6-ghz-range>


Spec roundup from the campaign; useful only as a second source for the headline numbers.


- Sample rate 200 kS/s - 61.44 MS/s; 12-bit ADC/DAC; 2x2 MIMO; 1x GbE; 'Ethernet bandwidth is between USB 2.0 and USB 3.0'.

*E200:* Secondary confirmation of hardware specs.

### F5OEO/ad9361KB - AD9361/Zynq knowledge base (PlutoSDR clones, Pluto+, AntSDR, LibreSDR)
`2/5` · English · github · 2024 · snippet  
<https://github.com/F5OEO/ad9361KB>


Evariste Courjaud's notes repo about Pluto-class boards including AntSDR; README content did not render through WebFetch, so it should be cloned and read.


- Described as notes 'about platforms like PlutoSDR and clone, Pluto+, AntSDR, LibreSDR'.

*E200:* Potential source of firmware tricks (DC offset, clocking, iiod tuning) for AntSDR; unread.

### MicroPhase/antsdr-fw - original (archived) ANTSDR firmware
`2/5` · English · github · 2023 · verified  
<https://github.com/MicroPhase/antsdr-fw>


Older PlutoSDR-fw fork for E310/E200 built with Vivado 2019.1; archived and superseded by antsdr-fw-patch which 'will track the upstream of plutosdr'. Also hosts a copy of the E200 public schematic.


- Archived/read-only; Vivado 2019.1; SD (make sdimg), DFU and JTAG bootstrap flashing described.
- Points users to antsdr-fw-patch for current builds.

*E200:* Historical only; use antsdr-fw-patch.

### MicroPhase/gnu-radio-demo - GNU Radio flowgraph examples for ANTSDR
`2/5` · English · github · 2023 · verified  
<https://github.com/MicroPhase/gnu-radio-demo>


Eleven chapters of GRC demos (filters, tags, AM/FM/ASK/BPSK/QPSK/FSK, DVB-S) for ANTSDR using the Pluto blocks.


- Chapters 1-11: intro, filter, tag/message, AM, FM, ASK, BPSK, QPSK, FSK, DVB-S, DVB-S with webcam; GNU Radio version not stated; no dual-RX example.

*E200:* Teaching material only; no drone-relevant flowgraphs.

### bkerler/antsdr_new - community up-to-date PlutoSDR-based firmware for ANTSDR E310
`2/5` · English · github · 2023 · verified  
<https://github.com/bkerler/antsdr_new>


Community fork keeping E310 firmware current (kernel 5.10, 2r2t, RF switch control, Vitis 2022.1). E310 only, but shows the community maintenance model.


- E310 only ('older ANTSDR B220 not supported'); 2r2t support, Linux 5.10, SD and DFU flashing; author: 'RF performance still needs to be further optimized'.

*E200:* Not directly usable on E200; a template if the toolkit needs a modernised IIO firmware for E200.


## RF detection and classification with ML

### DroneGoHome/U-RAPTOR-PUB (CageDroneRF toolkit: data pipeline, YOLO detection, SNR-stratified evaluation)
`5/5` · English · github · 2026 · verified  
<https://github.com/DroneGoHome/U-RAPTOR-PUB>


Official MIT-licensed toolkit (Rostami, Faysal, Xia, Kasasbeh, Gao, Wang; arXiv:2601.03302; Rowan University / AeroDefense). Raw complex .dat recordings at 20 MSps (constants: SAMPLING_RATE 20e6, CENTER_FREQ 2.447e9, FFT 1024, RECORDING_TIME 15 s), filenames Manufacturer_Model_Bandwidth_FreqMHz_Mode; recordings at 905 MHz, 2.4 GHz and 5.8 GHz, indoors/outdoors and in a shielded cage ('SR20M_G50_cage_RT15'), plus multi-drone mixes, laptop Wi-Fi video, 5G and environmental captures. Synthetic variants via AWGN/Rayleigh/Rician at SNR -15..35 dB; YOLO detection on spectrograms.


- License MIT; last commit 2026-03-26; 8.4k lines Python.
- src/data/constants.py: SAMPLING_RATE 20e6, CENTER_FREQ 2.447e9, FFT_SIZE 1024, complex64 memmap input, 15 s recordings.
- Test sets at SNR -15,-5,5,15,25,35 dB with ~1/3 AWGN, 1/3 Rayleigh, 1/3 Rician (K in [SNR-5,SNR+5] dB), background class 3x others, viridis colormap.
- Also includes ResNet18 binary drone/no-drone classifier and autoencoder code (src/pytorch), and an RFUAV loader (src/data/rfuav.py) so the tools run on RFUAV too.
- Class names seen in code include DJI_Phantom4, Autel_EXOII, HolyStone_HS110G and '_RC' remote-controller variants.
- constants.py: SAMPLING_RATE = 20e6, FFT_SIZE = 1024, CENTER_FREQ = 2.447e9, 15 s recordings
- SNR test sets at -15, -5, 5, 15, 25, 35 dB with ~33% AWGN / 33% Rayleigh / 33% Rician; background class = 3x other classes; viridis colormap
- Pipeline segments .dat IQ recordings into overlapping samples, saves spectrogram PNGs and meta_data.json; YOLO models evaluated over conf/IoU thresholds
- _(5 more facts in the JSON index)_

*E200:* Best architectural template: 20 MSps at 2.447 GHz is exactly an E200 operating point; the augmentation/evaluation code can be reused on E200 captures even if CageDroneRF raw data access is not granted.

### DroneRFa: 用于侦测低空无人机的大规模无人机射频信号数据集 (JEIT, Zhejiang University)
`5/5` · Chinese · dataset · 2024 · verified  
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570>


JEIT 2024 46(4):1147-1156, 俞宁宁/毛盛健/周成伟/孙国威/史治国/陈积明, Zhejiang University (Key Lab of Collaborative Sensing and Autonomous Unmanned Systems) with Chengde police. Full PDF was read from the maojinxiang/DroneRFA_24-Dataset clone. Beyond the dataset itself (known from round 1) the paper contains the acquisition recipe and a per-model table of hop-block and video-link statistics (Table 4) that can be used directly as hand-crafted detection rules.


- Download via JEIT data page (jeit.ac.cn/web/data/getData?dataType=Dataset3) and SciDB China; DroneRFa archive is ~574 GB (rfml-moe-hub docs).
- DroneRFb-DIR: 13 classes (6 drone types x 2 individuals + background), .mat HDF5 with I/Q float32 of 4,000,000 samples at 80 MSps (rfml-moe-hub docs).
- Chinese blog roundup '无人机射频侦测开源数据集汇总' on gitcode.csdn.net lists these plus DroneRF/DroneDetect/RFUAV.
- Receiver: NI USRP-2955, 100 MS/s I/Q, 80 MHz instantaneous BW, 14-bit ADC, gain set to 50 dB, VERT2450 3 dBi omni; PCIe to a Xeon W-2245 host running LabVIEW; capture-store period of 10 M samples so continuity breaks every 0.1 s.
- Channels: RF0 centred 2440 MHz and RF1 centred 5800 MHz (RF0 915 MHz + RF1 2440 MHz for FrSky X20 / Taranis Plus).
- Outdoor distances coded D00=20-40 m, D01=40-80 m, D10=80-150 m; indoor ~2 m; 24 classes T0000 (background incl. BT/WiFi) ... T11000; each segment >=100 M samples, .mat with keys RF0_I/RF0_Q.
- Table 4 hop-block features: DJI OcuSync-era models (Air 2S, Mini 3 Pro, Mavic 3, M300, M30T) hop-block BW 2.2 MHz / dwell 0.52 ms; Mavic Pro, Mini 2, P4P RTK, Avata 1.1 MHz / 0.52 ms; Lightbridge-era (P4P, M200, M100, Inspire 2, M600 Pro) 1.2 MHz / 2.2 ms with 12 ms nearest-hop spacing and a 14 ms video period at 68 % duty; Avata video period 10 ms at 12 % duty; RC transmitters: FrSky X20 0.42 MHz/2.8 ms, RadioLink AT9S 5.0 MHz/2.1 ms, Futaba T14SG 2.0 MHz/2.0 ms, 云卓 T12 1.7 MHz/4.6 ms.
- Baseline ResNet-18 on STFT (N=1024, 50 % overlap, input 2x1024x1024) of 1 M-sample (10 ms) windows: accuracy 97.73 %, 53 fps; dropping window length to 256 k samples gives 72.7 %; frequency resolution 128 gives 87.9 % at 217 fps.
- _(1 more facts in the JSON index)_

*E200:* Richest Chinese-origin data for DJI-class links, but 80-100 MSps captures must be decimated/cropped to E200 bandwidth; registration on SciDB required.

### kitoweeknd/RFUAV (RFUAV benchmark: 37 UAVs, 1.3 TB raw IQ, YOLOv5 detection + ResNet identification)
`5/5` · English · github · 2025 · verified  
<https://github.com/kitoweeknd/RFUAV>


Official repo (Apache-2.0, 436 stars) for the largest open drone-RF benchmark: raw float32 interleaved IQ from a USRP at 100 MSps for 35 recorded drone/RC types (public subset: 37 raw clips), plus spectrograms, YOLOv5 detection, 15+ classifiers, SNR estimation/adjustment tools (-20..+20 dB, 2 dB steps) and a two-stage detect-then-classify pipeline. Data on Hugging Face kitofrank/RFUAV; detection subset on Roboflow. Its per-drone XML sidecar schema and its definition of an RF 'fingerprint' as frequency-hop bandwidth/duration/duty-cycle/pattern-period plus video bandwidth are directly reusable design templates.


- License Apache-2.0; last commit 2025-12-09; data, spectrograms and weights on Hugging Face kitofrank/RFUAV, detection subset on Roboflow.
- Raw data: np.fromfile float32, default sample_rate 100e6, Hamming STFT with stft_point 256-2048; per-drone XML records CenterFrequency, SampleRate, IFBandwidth, ReferenceSNRLevel.
- Two-stage config (example/two_stage/sample.json): detector yolov5 RFUAV_stage1.pt + classifier stage2.pth (ResNet YAML).
- Benchmark evaluates mAP/Top-K/F1 separately per SNR from -20 to 20 dB; README recommends augmentation because training set is only at native SNR.
- Paper snippets: bands 985 MHz/2.4 GHz/5.8 GHz; STFT point 256 gave best accuracy across SNRs, 1024 degraded; ViT-L-32 best overall 56.44% across all SNRs and 100% at SNR>=10 dB, ResNet18 best at SNR<=-10 dB (22.39%).
- Repo also documents drone FHSS descriptors: hop bandwidth, hop duration, video bandwidth, duty cycle, hop-pattern period.
- 35 drone types; subset of 37 raw clips plus spectrograms public on Hugging Face/Roboflow; Apache-2.0.
- 'directly collected using USRP devices'; 100 MHz sampling rate, centre ~2400 MHz; binary IQ.
- _(11 more facts in the JSON index)_

*E200:* Code and two-stage architecture are portable, but all spectrograms/weights assume 100 MSps captures; E200 tops out at 56 MHz (61.44 MSps), so models must be retrained on re-rendered spectrograms (or raw IQ decimated/cropped) and 5.8 GHz video links wider than 56 MHz will be partially observed.

### r4d10n/rfml-moe-hub (Drone-RFML-Hub: 30+ models across RFUAV, DroneRFb-DIR, DroneRFa, DRFF-R2, RTL-ML)
`5/5` · English · github · 2026 · verified  
<https://github.com/r4d10n/rfml-moe-hub>


Third-party research hub (MIT) with per-dataset documentation, SciDB/HF download scripts and cross-architecture benchmarks. Its notes are the only reachable description of DroneRFb-DIR (SciDB 84cf9101e739402784b1396783881202: 6 drone types x 3 individuals + background, 80 MSps, 2.4-2.48 GHz, .mat v7.3 with I/Q float32 (1,4000000)=50 ms, FCS/VTS, LOS/NLOS, 2177 train + 2513 test files, 64 GB) and DRFF-R2 (arXiv:2603.00106, SciDB b8a16448c1284fd1be1ded9ccc45be20: 26 individual DJI drones across 8 models, 7 scenarios, 400.6 GB, 730 .mat files). Also carries an extensive practitioner survey with dataset table (DroneDetect, CardRF, UAVSig, VTI_DroneSET).


- License MIT; last commit 2026-04-11; checkpoints/ directory is empty (.gitkeep only).
- RFUAV 37-class: MaxViT-Base 97.8% (118.7M params), YOLOv11n-cls 97.4% (~1.6M), MobileNetV3-Large 97.1% (4.2M), LWMExpert raw-IQ 94.1% (1.3M), statistical features + RF 95.7%.
- Cross-individual DroneRFb-DIR (train units 1&2, test unit 3): ConvNeXt-Base 92.0% vs statistical features 42.3%.
- Claims spectrogram with hot colormap, FFT=256, Hamming is optimal across RFUAV and RTL-ML; expert-trust ranking spectrogram > IQ stats > cyclostationary > HOS.
- features/energy_gate.py implements a Neyman-Pearson energy detector with self-calibrating noise floor (p_fa, rolling buffer percentile); evaluation/openset.py implements OpenMax with Weibull fits.
- Dataset docs: DroneRFb-DIR 80 MSps 2.4-2.48 GHz .mat HDF5 (I,Q float32 4,000,000 samples), DroneRFa 574 GB 80 MSps dual-receiver, DRFF-R2 26 DJI units of 8 models (arXiv 2603.00106).
- Best results: MaxViT-Base 97.8% (RFUAV, 37 classes, spectrograms); LWMExpert 94.1% on raw IQ with 1.3M params; statistical features + RF 95.7% on RFUAV but 100% on RTL-ML (800 samples)
- Cross-individual test (DroneRFb-DIR, train on units 1&2, test on unit 3): statistical features collapse to 42.3%, ConvNeXt-Base 92.0%
- _(8 more facts in the JSON index)_

*E200:* Feature extractors, energy gate and OpenMax are pure PyTorch/numpy and portable; DroneRFb/DroneRFa at 80 MSps exceed E200 bandwidth so retraining on decimated data is needed; the MobileNetV3/YOLOv11n-cls results justify a CPU-only laptop classifier.

### sgluege/Noisy-Drone-RF-Signal-Classification-v2 (dataset loader for Kaggle Noisy Drone RF v2)
`5/5` · English · github · 2025 · verified  
<https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification-v2>


Loader and inspection scripts for the Noisy Drone RF Signal Classification v2 dataset (Kaggle), which stores each sample as a .pt file with x_iq [2,1048576], integer target and SNR encoded in the filename. Dataset mixes real drone/RC recordings with lab noise (Bluetooth, Wi-Fi, amplifier) and Gaussian noise across a wide SNR range, which is what makes it useful for low-SNR training.


- License GPL-3.0; last commit 2025-09-25.
- File naming IQdata_sampleX_targetY_snrZ.pt; class_stats.csv and SNR_stats.csv describe the distribution.
- Dataset card in rf-signal-intelligence lists the 7 classes and notes sample counts per class (paper snippet: 1280 DJI, 3472 FutabaT14, 801 FutabaT7, 801 Graupner, 1663 Taranis, 855 Turnigy, 8872 Noise).
- Spectrogram transform is the same n_fft=1024/hop=1024 complex STFT as the training repo.
- README cites Glüge et al., 'Robust Low-Cost Drone Detection and Classification Using Convolutional Neural Networks in Low SNR Environments', IEEE J. RFID vol. 8, 2024, doi 10.1109/JRFID.2024.3487303; samples stored as IQdata_sampleX_targetY_snrZ.pt.
- Search snippet: classes DJI, FutabaT14, FutabaT7, Graupner, Taranis, Turnigy, Noise; vectors of 16384 samples ~1.2 ms at 14 MHz with Bluetooth/Wi-Fi/amplifier lab noise.
- Files: class_stats.csv, SNR_stats.csv, IQdata_sample*.pt with keys x_iq, y, snr; spectrogram transform n_fft=1024, hop 1024, two-sided.
- Third-party survey: recorded with USRP B210 at 14 MSps, 6 drones + 4 controllers + interference, ~23 GB; windows ~1,048,576 samples (~75 ms).
- _(1 more facts in the JSON index)_

*E200:* Best public training/validation dataset for a first E200 classifier because its 14 MSps bandwidth is within E200 limits; class set is RC-transmitter heavy (Futaba/Taranis/Graupner/Turnigy) plus one DJI class, so DJI OcuSync variants are under-represented.

### sgluege/Robust-Drone-Detection-and-Classification (VGG11_BN drone/RC classifier, Glüge et al. IEEE JRFID 2024)
`5/5` · English · github · 2024 · verified  
<https://github.com/sgluege/Robust-Drone-Detection-and-Classification>


Reproduction code for a VGG11_BN classifier that takes a 2^20-sample IQ window (about 74.9 ms at 14 MSps), turns it into a 1024x1024 two-channel (Re/Im) complex STFT via torchaudio, and classifies 7 classes (DJI, FutabaT14, FutabaT7, Graupner, Taranis, Turnigy, Noise). It is the only open project found that combines released weights, a public IQ dataset at an E200-compatible sample rate, SNR-resolved evaluation, and a documented field test with a USRP.


- License GPL-3.0; last commit 2024-11-14; trained models and results on Zenodo record 14065652.
- Input pipeline (load_dataset.py): torchaudio Spectrogram n_fft=1024, win_length=1024, hop_length=1024, hann window, onesided=False, power=None (complex), then Re/Im stacked as 2 channels and divided by window length.
- 5-fold CV mean test accuracy 0.942 (weighted/balanced 0.928) on the Kaggle Noisy Drone RF v2 dataset; per-SNR confusion matrices generated by eval_model_with_cm_per_SNR_cv5.py.
- Paper abstract (arXiv 2406.18624, snippet): >=85% balanced accuracy at SNR > -12 dB on the dev set, >80% in the field test depending on distance and antenna direction; field system used a USRP B210 at 14 Msps, original recordings at 56 MHz.
- Training one epoch of VGG11_BN takes about 5 minutes on an A100 (README); no CPU inference latency published.
- Per-fold test accuracy 0.930-0.947 and weighted accuracy 0.924-0.930 (VGG11_BN, 50 epochs, lr 0.005, batch 8)
- One epoch takes ~5 min on a single NVIDIA A100
- Dataset classes include DJI, FutabaT14, Taranis, Noise (sample images at SNR 30, 6, 26, 22, -4 dB)
- _(4 more facts in the JSON index)_

*E200:* Directly applicable: E200 (AD9361) can stream 14 MSps over 1 GbE with margin; the 1024x1024 complex STFT of 74.9 ms windows maps 1:1 onto E200 captures. Only caveat is receiver gain/noise-figure differences vs the B210 used for the dataset.

### Al-Sad/DroneRF (official DroneRF dataset code: LabVIEW, MATLAB, Python DNN)
`4/5` · English · github · 2021 · verified  
<https://github.com/Al-Sad/DroneRF>


Official companion repo for the DroneRF database (Mendeley DOI 10.17632/f4c2b4n755.1). Contains the LabVIEW 'RF Record-Playback' project used with NI USRP hardware, plus MATLAB/Python scripts that reveal the format: two 40 MHz channels ('L' and 'H' CSV files, fs=40e6 each) covering the lower/upper halves of the 2.4 GHz band, segments of 1e7 samples, BUI label codes for background (00000), Parrot Bebop (10000-10011, 4 modes), Parrot AR Drone (10100-10111) and DJI Phantom (11000).


- License Apache-2.0; last commit 2021-01-28; dataset on Mendeley doi 10.17632/f4c2b4n755.1.
- DroneRF is the dataset most affected by segment-level leakage per arXiv 2607.01025; only three old drones.
- Three drones (Parrot Bebop, AR Drone, DJI Phantom 3 per secondary sources) in four modes: on, hovering, flying, video recording; recorded with USRP SDRs
- Reported accuracies 99.7% (2-class), 84.5% (4-class), 46.8% (10-class) per the Glüge 2023 paper's related-work section
- No complex IQ and no BT/Wi-Fi noise recordings (Glüge et al. 2023)
- Code licence Apache-2.0; dataset CC BY 4.0 per song-lalala/drone-rf-id README; raw CSV download ~40 GB (drone-rf-id) while a third-party table lists 3.75 GB (likely aggregated .mat).
- Demo_2_Snippets.m uses fs = 40e6 per channel; Demo_3_Analysis.m treats the combined band as 80 MHz; Main_1 aggregates 1e5-sample segments with 2048 frequency bins.
- Only 3 drones (Bebop, AR Drone, Phantom 3) with 10 classes incl. 4 flight modes for two of them; data are real-valued CSV amplitude samples, not complex IQ.
- _(1 more facts in the JSON index)_

*E200:* Historical baseline only; three obsolete drones and leakage-prone protocol make it unsuitable as the toolkit's primary training set.

### DaftJun/S3R (Open Set Learning for RF-Based Drone Recognition via Signal Semantics, IEEE TIFS 2024)
`4/5` · English · github · 2025 · verified  
<https://github.com/DaftJun/S3R>


Official PyTorch implementation of S3R: STFT spectra (2048-point Hamming, 50% overlap) are fed to three dilated-convolution branches (dilation 1/3/5) that build a semantic embedding trained with a contrastive/centre loss; unknown drones are rejected by distance to class centres with per-class covariance. Data are .mat files with RF0 (2440 MHz) and RF1 (5800 MHz) I/Q at 100 MSps.


- No LICENSE file in repo; last commit 2025-04-28; ~840 lines Python.
- raw2tfs/plt.py: h5py load of RF0_I/RF0_Q or RF1_I/RF1_Q, fs=100e6, 2048 freq bins, Hamming, 50% hop, 10*log10 magnitude.
- train.py: MyDataset resizes features to 512, NET has three conv stacks with dilation 1,3,5 and a semantic_dim linear head; test_stage_1.py reports known-acceptance/unknown-rejection metrics; class covariance used for outlier check.
- Dataset on IEEE DataPort (doi 10.21227/wv7h-sv64) with 9 experiment groups mapping to paper scenarios I-VI; companion DroneRFb-Spectra spectrogram dataset has 14,460 samples of 7 brands (DJI, Vbar, FrSky, Futaba, Taranis, RadioLink, Skydroid) and paper reports 96.64% average accuracy (snippet).
- Follow-up arXiv 2603.24268 (incremental open-set with Mahalanobis rejection + K-Means/GMM discovery) has no public code found.
- raw2tfs/plt.py uses fs = 100e6 and channel center 2440 MHz for STFT generation
- Nine experiment groups map to scenarios I-VI and I-A/B/C of the paper; contrastive loss (contLoss.py) plus two test stages
- Same Zhejiang group behind the DroneRFa/DroneRFb datasets (JEIT 2025, DOI 10.11999/JEIT240804 per secondary source)
- _(4 more facts in the JSON index)_

*E200:* Open-set head and dilated-conv semantic extractor are portable; training data are 100 MSps dual-band so E200 users must retrain on 56 MHz-or-narrower spectrograms; the 'known vs unknown' evaluation protocol is the right one for AERIX unknown-drone alerts.

### DroneDetect Dataset (Swinney & Woods, IEEE DataPort 2021)
`4/5` · English · dataset · 2021 · snippet  
<https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine>


IQ recordings from a Nuand bladeRF via GNU Radio of seven UAS (DJI Mavic 2 Air S, Mavic Pro, Mavic Pro 2, Inspire 2, Mavic Mini, Phantom 4, Parrot Disco) in three flight modes, with subsets recorded under Bluetooth, Wi-Fi, both and no interference.


- DOI 10.21227/5jjj-1m32; used by IQTLabs/RFClassification and Aditya20101/RF-signal-based-UAV-Identification-and-Classification.
- RFClassification reports 0.854 accuracy for 7-class PSD+SVM on 20 ms windows.
- 60 MHz sample rate float32 IQ (from IQT loader); 7 UAS classes, 21 mode classes referenced in related Swinney papers.
- Licence not verified (IEEE DataPort open access).

*E200:* Useful for DJI-heavy training if its bladeRF sample rate (<=61.44 MSps) is re-verified; interference subsets are valuable for realistic 2.4 GHz backgrounds.

### How Much Do RF Drone Benchmarks Overstate? A Controlled Study and Theory of Data Leakage in UAV Signal Identification (Shulman, 2026)
`4/5` · English · paper · 2026 · snippet  
<https://arxiv.org/abs/2607.01025>


Shows that the near-perfect accuracies reported on DroneRF-style benchmarks come from segment-level cross-validation that places near-duplicate slices of the same recording in train and test; formalises the optimism with Cover's function-counting theorem and shows classifiers can memorise the recording-to-label map when recordings are few relative to feature dimension.


- arXiv 2607.01025, submitted 2026-07-01, single author David Shulman.
- Recommends recording-level (group) splits; the leakage effect grows when the number of independent recordings is small.

*E200:* Dictates the toolkit's evaluation design: split by capture session/drone unit, never by window, and treat published 99% numbers as upper bounds.

### IQTLabs/RFClassification (PSD+SVM, VGG/ResNet transfer learning, RF-UAVNet on DroneRF/DroneDetect)
`4/5` · English · github · 2022 · verified  
<https://github.com/IQTLabs/RFClassification>


Reference implementation using DroneRF and DroneDetect (IEEE DataPort). Its loader documents DroneDetect's format: float32 complex64 IQ at 60 MHz sample rate, 240,000,000-sample files, interference conditions CLEAN/BLUE/WIFI/BOTH encoded 00/01/10/11, directory DroneDetect_V2; reports PSD+SVM and VGG16 results.


- License Apache-2.0; last commit 2022-09-29.
- DroneRF binary detection: PSD(NFFT=1024)+SVM accuracy 0.983 at 0.286 ms inference on a 20 ms sample; raw IQ 1D-conv RF-UAVNet 0.998 at 1.078 ms (i9-9820X/Titan RTX).
- DroneDetect 7-class: PSD+SVM 0.854 (9.96 ms), SPEC+VGG16 0.816, PSD+VGG16 0.825 on 20 ms samples; accuracy rises with sample length (10 ms 0.769, 20 ms 0.836, 50 ms 0.894) and is insensitive to NFFT.
- Contains gamutRF dataloaders and test_code_on_pi/run_model.py for feasibility on RPi 4.
- Binary detection on DroneRF: PSD(NFFT=1024)+SVM acc 0.983 at 0.286 ms; raw 1D conv RF-UAVNet 0.998 at 1.078 ms (i9-9820X + Titan RTX)
- DroneDetect multiclass: PSD+SVM 0.854 (9.96 ms), SPEC+VGG16 0.816 (5.7 ms)
- Window length matters more than FFT size: 10 ms 0.769, 20 ms 0.836, 50 ms 0.894 accuracy; NFFT 256/512/1024 gives 0.841/0.840/0.855
- test_code_on_pi/ contains RPi4 real-time prediction feasibility scripts
- _(4 more facts in the JSON index)_

*E200:* PSD+SVM presence detector is trivially portable to E200 IQ and runs in real time on any CPU; multi-class results are dataset-specific and pre-date modern DJI links.

### IQTLabs/gamutRF (GNU Radio SDR scanner/collector with Torchserve image/IQ inference)
`4/5` · English · github · 2025 · verified  
<https://github.com/IQTLabs/gamutRF>


Docker-orchestrated GNU Radio scanner that sweeps frequency ranges, retunes after a configurable number of FFT points exceed a power threshold, produces spectrogram images (image_inference block) and sends them to Torchserve for identification; can run on Pi4/Pi5 or x86+GPU. gr-iqtlabs provides the retune_pre_fft/retune_fft, iq_inference, image_inference and vkfft blocks (SoapySDR, GNU Radio >= 3.10.6). Both repos are archived (gr-iqtlabs read-only since July 2025).


- License Apache-2.0; last commit 2025-08-25.
- Sources: gamutrf/ettus_source.py builds uhd.usrp_source with fc32 streams; gamutrf/soapy_source.py uses gnuradio soapy driver strings.
- Inference options in grscan.py: image_inference (spectrogram images to Torchserve, min confidence, min dB) and iq_inference (raw IQ with squelch) provided by gr-iqtlabs blocks.
- Typically deployed on x86_64 + NVIDIA GPU but components run on Pi4/Pi5; retune logic counts valid IQ samples before hopping (gr-iqtlabs retune_pre_fft).
- Sweep/retune driven by power-threshold energy detection in gr-iqtlabs
- Identification via image (spectrogram) or IQ PyTorch models served by Torchserve
- Deployment typically x86_64 + NVIDIA GPU; components can be distributed over a network
- Companion rfml repo auto-labels SigMF IQ by signal power / occupied bandwidth and uses TorchSig augmentation

*E200:* Usable as the capture/scan orchestrator for E200 via UHD; however the underlying gr-iqtlabs blocks were archived in July 2025, so long-term maintenance falls on the toolkit.

### IQTLabs/rfml (SigMF auto-labelling + IQ/spectrogram model training, TorchSig augmentation, Torchserve export)
`4/5` · English · github · 2025 · verified  
<https://github.com/IQTLabs/rfml>


Pipeline to auto-annotate SigMF recordings by power thresholding and bandwidth estimation (Gaussian mixture or spectral threshold), then train both raw-IQ and spectrogram models with TorchSig augmentation and export torchscript/.mar files for gamutRF. Experiments include DJI Mini 2 video vs telemetry and Mavic 3 video vs Remote ID labels.


- Last commit 2025-06-09; uses Poetry; label_scripts/label_mavic.py, label_mini2*.py, label_mavic3_lab.py present.
- annotation_utils.annotate parameters: avg_window_len, power_estimate_duration, force_threshold_db, bandwidth_estimation (GMM or float threshold), annotation_seconds, bandwidth_limits, set_bandwidth, dc_block, fft_len.
- Experiment example classes: mavic3_video, mavic3_remoteid, environment; mini2_video, mini2_telem; reported IQ training accuracy 98.10% on one experiment log.
- Recommends collecting isolated signals in a foil-lined Pelican-case Faraday enclosure and adding a background 'environment' class.
- annotation_utils.annotate() parameters: avg_window_len, power_estimate_duration, bandwidth_estimation via GMM or spectral thresholding, writes .sigmf-meta.
- Recommends inspectrum for reviewing SigMF annotations.

*E200:* SigMF annotation + training loop is hardware-independent and is the most direct path from E200 captures to a custom DJI/RC model; TorchSig dependency is heavy but CPU-capable.

### Marchev-Science/case-drone-signature-classification (CardRF dataset description and case tasks)
`4/5` · English · github · 2024 · verified  
<https://github.com/Marchev-Science/case-drone-signature-classification>


Mirror/case-study repo reproducing the CardRF README (authors Medaiyese, Ezuma, Lauf, Adeniran). Captures made Aug 2020 at NC State's AERPAW Lake Wheeler site with a Keysight MSOS604A oscilloscope (metadata XInc 5e-11 s = 20 GSa/s, 5,000,000 points = 250 us per capture, scale 6.581e-06 V), LOS at 8-12 m and NLOS (Inspire, Matrice 600, Phantom only); raw CSV traces plus a processed set of 1024-sample steady-state slices.


- License MIT; last commit 2024-06-22.
- Each raw CardRF signal has 5 million points spanning 0.25 ms (i.e. ~20 GSa/s oscilloscope capture), scale factor 6.581e-06 V; dataset ~65 GB .mat on IEEE DataPort.
- Four signal categories: UAV, UAV controller, Bluetooth, Wi-Fi; LOS and NLOS subtrees; train/test split provided
- Processed CardRF slices have 1024 sampling points each; references [2] Medaiyese et al. 'Hierarchical learning framework for UAV detection and identification' (arXiv) and [3] wavelet-transform analytics for RF-based UAV detection
- Secondary source reports wavelet scattering + SqueezeNet 98.9% at 10 dB across 17 controllers with 0.37 ms inference
- Devices: UAV DJI Phantom 4, Inspire, Matrice 600, Mavic Pro 1, Beebeerun FPV mini quad, 3DR Iris FS-TH9x; Bluetooth iPhone 6S, iPhone 7, iPad 3, FitBit Charge3, Motorola E5 Cruise; Wi-Fi Cisco Linksys E3200, TP-Link TL-WR940N.
- Directory levels: LOS/NLOS -> Train/Test -> BLUETOOTH/UAV/UAV_controller/WIFI -> device -> FLYING/HOVERING/VIDEOING.
- Signals labelled with transient and steady-state portions (Fig. 6) - explicit RF-fingerprinting design.
- _(1 more facts in the JSON index)_

*E200:* Low: CardRF is an oscilloscope-bandwidth RF-fingerprinting dataset, not SDR baseband IQ, so models trained on it do not transfer to 56 MHz E200 captures.

### Measurement based FHSS-type Drone Controller Detection at 2.4GHz: An STFT Approach (Kaplan et al., 2020)
`4/5` · English · paper · 2020 · snippet  
<https://arxiv.org/abs/2003.03614>


Over-the-air measurements of FHSS RC controllers at 2.4 GHz; uses STFT to extract hop sequences and the autocorrelation of the STFT to estimate time guards/dwell, validated vs SNR, window size and distance. A ready-made recipe for the hop-timing feature extractor.


- Image-processing on spectrograms plus ACF-based hop-period estimation differentiates UAV RC signals; published IEEE VTC 2020.
- No public code repository found.
- STFT captures the hopping sequence; time guards are computed from the ACF of the STFT to separate controllers; measured in hilly suburban terrain with foliage; results as normalized MSE vs SNR/window/Tx-Rx separation.
- Snippet: a Futaba controller showed dwell time 1.44 ms over 2.40-2.45 GHz with hopping sequence f1 f1 f2 f3 f3 f4.

*E200:* Algorithmic recipe for an FHSS hop-pattern extractor on top of gr-fhss_utils burst tags; must be re-implemented in numpy.

### Robust Low-Cost Drone Detection and Classification in Low SNR Environments (Glüge et al., 2024)
`4/5` · English · paper · 2024 · snippet  
<https://arxiv.org/abs/2406.18624>


Paper behind the Noisy Drone RF v2 dataset and VGG classifier: recordings of DJI Phantom, Futaba T7C/T14SG, Graupner mx-16, Taranis ACCST and Turnigy 9X transmitters/receivers at 56 MHz, mixed with lab noise, and a live field test with a standard PC + USRP B210 at 14 Msps.


- All CNNs reached >=85% balanced accuracy at SNR > -12 dB on the dev set; field test >80% depending on distance and antenna direction.
- Dataset vectors are non-overlapping 2^20 samples (~74.9 ms at 14 MHz).
- IEEE JRFID vol. 8, pp. 821-830, 2024; Zenodo 14065652 hosts trained VGG11_BN.

*E200:* Establishes that a laptop + 14 MSps SDR is enough for real-time drone/RC classification, matching the E200 over Ethernet.

### rameyjm7/rf-signal-intelligence (live SDR replay/receive VGG classifier on NoisyDroneRFv2, ONNX/TensorRT)
`4/5` · English · github · 2026 · verified  
<https://github.com/rameyjm7/rf-signal-intelligence>


TensorFlow re-implementation of the Glüge full-complex spectrogram VGG with a config-driven CLI, ONNX export, CPU ONNX Runtime inference script and a documented over-the-air replay test (bladeRF TX to HackRF RX at 2.399 GHz, 20 MS/s). Useful as a reference for windowing/normalisation and deployment, but weights and the live SDR framing code are withheld.


- License: 'RF Signal Intelligence Non-Commercial Source-Available License' (not OSI); last commit 2026-08-08.
- Model input (1024,1024,2) float32: window 1,048,576 IQ samples, nfft=1024, hop=1024, hann, fftshift, normalise by std and clip to [-6,6]; burst-start finder selects a high-power window before STFT.
- Offline accuracy 0.9769 (natural held-out) / 0.9803 (balanced) with min SNR -6 dB filter; live OTA 68/70 exact matches at SNR>=20 dB; Jetson TensorRT FP16 mean latency 79 ms.
- Pretrained weights, tuned confidence gates and gateway integration are explicitly private; public repo only has preprocessing/export helpers.
- Dataset card warns about leakage: never split windows from the same capture across train/test.
- Offline accuracy 0.9769 (natural test) / 0.9803 (balanced) on NoisyDroneRFv2 (7 classes)
- OTA replay at 2.399 GHz, 20 MS/s, 20 MHz: 68/70 exact class matches (0.971) at SNR >= 20 dB
- Jetson TensorRT FP16: 79.0 ms mean latency, 12.58 qps, 7/7 classes matched
- _(2 more facts in the JSON index)_

*E200:* Preprocessing recipe is directly portable to E200 IQ (20 MS/s OTA test is within E200 bandwidth); licence forbids commercial use, so treat as reference only for AERIX.

### sandialabs/gr-fhss_utils (GNU Radio FHSS utilities: FFT burst tagger, centre-frequency estimation, dehoppers, SigMF writer)
`4/5` · English · github · 2023 · verified  
<https://github.com/sandialabs/gr-fhss_utils>


Sandia's GNU Radio module for frequency-hopping signals: an FFT burst detector that keeps a per-bin dynamic noise floor over history_size FFTs, tags bursts that stay threshold dB above it for lookahead FFTs, estimates burst centre frequency/bandwidth ('middle-out'), extracts bursts to PDUs and writes SigMF metadata; also coarse/fine dehoppers for FSK hop sets.


- Last commit 2023-08-17; part of the Sandia gr-pdu_utils family.
- GRC blocks: fft_burst_tagger, cf_estimate, coarse_dehopper, fine_dehopper, fsk_burst_extractor_hier, s_and_h_detector, sigmf_meta_writer, tagged_burst_to_pdu, fft_peak, burst_tag_debug.
- Burst tagger parameters: threshold (dB above moving floor), history_size, lookahead, burst_pre_len, burst_post_len; derived from gr-iridium.
- FFT burst detector 'maintains a dynamic noise floor estimate for each bin over the prior history_size FFTs' and tags bursts that exceed threshold dB for at least lookahead FFTs; burst_pre_len/burst_post_len pad tags.
- 'Middle Out' centre frequency and bandwidth estimation uses the noise-floor estimate and a Gaussian window; dataset de-hopper does coarse FFT peak sample-and-hold plus fine instantaneous-frequency correction (works well for FSK).
- Derived from gr-iridium; companion modules gr-pdu_utils etc.
- Dynamic noise floor per FFT bin over the prior history_size FFTs; burst_pre_len/burst_post_len adjust tag placement
- Center-frequency and bandwidth estimation per burst; two-stage dehopper for FHSS FSK
- _(1 more facts in the JSON index)_

*E200:* Ideal front-end for extracting RC hop bursts (ELRS/Crossfire/Futaba/DJI control) from 20-56 MHz E200 captures; per-burst centre/bandwidth/duration/period features feed FHSS hop-pattern classification.

### Design and development of an SDR-based system for real-time detection and characterization of drone RF signatures (Scientific Reports, 2026)
`3/5` · English · paper · 2026 · snippet  
<https://www.nature.com/articles/s41598-026-48925-1>


Low-cost USRP B210 + Ubuntu/Python system that renders spectrograms in real time and runs YOLOv5 and Faster R-CNN detectors trained on a self-built drone/non-drone dataset evaluated across SNRs; closest published analogue of the intended E200 laptop setup.


- USRP B210 (70 MHz-6 GHz, up to 61.44 MS/s) with Python real-time spectrogram generation and inference; YOLOv5 vs Faster R-CNN compared under varying SNR.
- No code repository was found in search results.

*E200:* Architecture is identical to E200-over-Ethernet + laptop; would need reimplementation since no code was located.

### IQEngine (web SigMF viewer/annotator with detector plugins)
`3/5` · English · github · 2025 · snippet  
<https://github.com/iqengine/iqengine>


Browser-based SigMF spectrogram viewer/editor with a plugin API (OpenAPI, Python/GNU Radio templates) and a built-in threshold/minimum-bandwidth detector that writes annotations; convenient for labelling E200 captures before training.


- Built on SigMF; plugins run server-side and are triggered from the browser; ships a detection algorithm producing annotations from threshold and min bandwidth parameters.
- sigmf-python (github.com/sigmf/sigmf-python) is the reference library for reading/writing recordings.

*E200:* Recommended annotation front-end if the toolkit standardises on SigMF for E200 recordings.

### IQTLabs/gr-iqtlabs (GNU Radio OOT blocks: image_inference, iq_inference, retune_fft, write_freq_samples)
`3/5` · English · github · 2025 · verified  
<https://github.com/IQTLabs/gr-iqtlabs>


The block library behind gamutRF: builds spectrogram images for inference, correlates IQ and power for IQ models, retunes the source after threshold-validated FFTs, writes compressed samples per frequency and can offload FFT to Vulkan (vkfft). Archived read-only on 2025-07-01.


- License Apache-2.0; archived July 1, 2025.
- Blocks: image_inference, iq_inference, iq_inference_standalone, retune_pre_fft, retune_fft, tuneable_test_source, vector_roll, vector_to_json, vkfft, write_freq_samples.

*E200:* C++ blocks compile against GNU Radio 3.10 and are SDR-agnostic; archived status means bugs must be fixed in a fork.

### TorchSig (RFML toolkit: WidebandSig53, YOLOv8 spectrogram detector, GNU Radio inference block)
`3/5` · English · github · 2025 · snippet  
<https://github.com/torchdsp/torchsig>


Open-source PyTorch signal-ML framework with synthetic wideband datasets, augmentation transforms, a YOLOv8-based wideband energy/signal detector and a GNU Radio OOT block that overlays detections on live spectrograms (GRCon 2024/2025 papers). Used by IQTLabs/rfml for augmentation.


- YOLOv8 size-X trained for energy detection on wideband spectrograms; 57 signal types in the library; GRCon 2024 paper describes the GNU Radio block and spectrogram tools.
- Gradiant mirrors it as COM-SIGINT-Spectrum-Awareness-torchsig.

*E200:* Provides generic burst-detection-on-spectrogram models and augmentation for training on E200 captures; drone-specific labels must be added.

### diannel231/drone_detection (GNU Radio 3.10 blocks: Energy_Detector, OFDM_Estimator, Drone_ML)
`3/5` · English · github · 2023 · verified  
<https://github.com/diannel231/drone_detection>


CSU master's-project blocks for HackRF: a Python Neyman-Pearson energy detector (threshold = noise mean + Qinv(Pfa)*std), a C++ OFDM parameter estimator adapted from gr-inspector (subcarrier spacing, symbol time, CP length) and an sklearn block that classifies drones from the OFDM parameters.


- License GPL-3.0-or-later (SPDX headers); last commit 2023-05-25.
- Energy_Detector.py: decim_block averaging \|x\| over N samples, Pfa parameter, publishes (avg,detection) PMT message.
- Drone_ML/ml_testing.py loads a pickled sklearn model (KNN/RF/LinearSVC/GaussianNB) and classifies on OFDM features.
- Combines energy detection, OFDM parameter estimation and an ML classification block in one flowgraph
- Recommends native Linux to avoid latency between SDR and blocks

*E200:* OFDM-parameter estimation is a cheap, interpretable way to separate DJI OcuSync/Wi-Fi OFDM video links from FHSS RC links on E200 data; code quality is student-level.

### Instructions for anti-UAV crew: drone detector based on tinySA Ultra spectrum analyzer (Kyiv, 2024)
`2/5` · Ukrainian · doc · 2024 · snippet  
<https://rtotech.org/wp-content/uploads/2025/01/Tiny_SA_drone.pdf>


Field instruction (Ukraine, 2024) for using a tinySA Ultra with firmware v3.2.0 as a drone detector: watch multiple ISM bands, highlight drone-typical signals, alarm on detection. Confirms that frontline practice is manual spectrogram recognition of FPV/Mavic signals rather than ML.


- tinySA Ultra firmware v3.2.0 used for drone detection instructions; tinySA firmware source is at github.com/erikkaashoek/tinySA.
- Ukrainian vendor pages describe drone-detector firmware features: simultaneous multi-band view, highlighting drone-like signals, alarms.

*E200:* Defines the operator expectations (multi-band watch, highlighted drone signatures, audible alert) an E200 toolkit UI should match; no reusable code.

### edwardrybka/FPV_DETECTED_1.2_5.8GHZ (Ukrainian RX5808-based analog FPV drone detector)
`2/5` · Ukrainian · github · 2025 · verified  
<https://github.com/edwardrybka/FPV_DETECTED_1.2_5.8GHZ>


Ukrainian open-hardware detector built on a Raspberry Pi Pico with RX5808 receiver modules and a TA8804 video demodulator that alerts on approaching analog FPV drones at 1.2 and 5.8 GHz; representative of the RSSI-scan approach widely used in Ukraine.


- License Apache-2.0; README in Ukrainian (with some Russian); 18 commits.
- Claimed range about 1.6 km in open field for a 200 mW transmitter at 1.8 m height.

*E200:* Not SDR code, but documents which analog FPV channel plans and RSSI thresholds field users rely on; useful as a ground-truth comparison for an E200 FPV scanner.

### phwl/cyclostationary (Python FAM spectral-correlation-density estimator with notebooks)
`2/5` · English · github · 2023 · snippet  
<https://github.com/phwl/cyclostationary>


Small Python/Jupyter implementation of the FFT Accumulation Method for spectral correlation density with examples for several modulations; the practical starting point for cyclostationary features (rfml-moe-hub found such features rank below spectrograms for sporadic drone bursts).


- Implements SCD via FAM in numpy with demonstration notebooks.
- rfml-moe-hub reports cyclostationary features at 95.6% on RTL-ML but 'fails on sporadic signals' and ranks them below spectrogram/IQ statistics.

*E200:* Optional feature branch for separating OFDM (DJI/Wi-Fi) from FSK/LoRa RC links; compute-heavy for 20+ MHz streams.

### smittix/intercept (RF platform with 'Drone Intelligence' mode: Remote ID + hackrf_sweep/rtl_433 band detector)
`2/5` · English · github · 2026 · verified  
<https://github.com/smittix/intercept>


Actively maintained Apache-2.0 SIGINT web platform whose drone module combines Remote ID with a very simple RF control-link detector: hackrf_sweep power above -90 dBm in 433/868/2.4/5.8 GHz bands and rtl_433 hits, mapped to protocol names by frequency range only.


- License Apache-2.0; last commit 2026-08-31.
- utils/drone/rf_detector.py: _HACKRF_THRESHOLD_DBM = -90, band table 433-435, 868-869, 2400-2484, 5725-5875 MHz; signatures.py maps frequency ranges to names such as DJI_OCUSYNC.
- Correlator merges RF observations with Remote ID contacts by frequency/protocol.

*E200:* Illustrates the false-positive-prone band-threshold approach the toolkit should avoid; its Remote ID/correlator structure is a reasonable UX reference for feeding an observation network.

### tesorrells/RF-Drone-Detection (Georgia Tech passive drone detection: hackrf_sweep + Wi-Fi OUI monitor)
`2/5` · English · github · 2025 · verified  
<https://github.com/tesorrells/RF-Drone-Detection>


Capstone project evaluating passive detection methods; the released v1.0.0 detects Wi-Fi-based drones by matching MAC OUIs to drone manufacturers and documents its false-positive/spoofing weaknesses, alongside hackrf_sweep and GNU Radio energy-detection experiments and Jetson TK1 deployment notes.


- Last commit 2025-05-21; no licence file observed.
- Detection is OUI-lookup only; proposed future work is vibration-noise modelling of drone signals.
- OUI-based detection is vulnerable to MAC spoofing and to false positives from non-drone devices of the same manufacturers
- Proposes vibration-noise modelling as a future discriminator

*E200:* Low value; only the hackrf_sweep-to-FFT scripts are marginally relevant.

### zeroXzero/saife (SAIFE adversarial-autoencoder spectrum anomaly detector on PSD)
`2/5` · English · github · 2019 · verified  
<https://github.com/zeroXzero/saife>


Reference implementation of SAIFE (arXiv 1807.08316): an adversarial autoencoder over PSD vectors that flags spectrum anomalies (unexpected signals) at a fixed false-alarm rate and learns interpretable bandwidth/centre-frequency features; the code is TensorFlow 1.12/TFLearn and dormant.


- Paper claims >80% anomaly detection accuracy at 1% constant false-alarm rate (snippet).
- Repo has 4 commits, TF 1.12.0 + TFLearn, HackRF and eSense data loaders, no licence stated.

*E200:* Concept (PSD autoencoder for 'unknown emitter in band') is right for open-world alerts, but the code needs a full PyTorch rewrite.

### Suliman8/SkyShield (RF drone detection & threat classification 'system' - README only)
`1/5` · English · github · 2026 · verified  
<https://github.com/Suliman8/SkyShield>


Despite the GitHub description, the repository contains only README.md, index.html, summary.pdf and CLAUDE.md; the source tree is listed as 'coming soon' and the licence is a proprietary all-rights-reserved notice. It also documents jamming/GPS-spoofing 'neutralisation' methods, which are out of scope for passive receive.


- LICENSE: 'PROPRIETARY LICENSE ... All Rights Reserved' (Suliman Khan, 2026); last commit 2026-02-08 'remove open-source references, add proprietary notice'.
- No Python or other source files exist in the repo (find returned zero .py files).
- Hardware plan: RTL-SDR v4 / HackRF / USRP B210, FMCW radar modules, Jetson.

*E200:* Not reusable: no code, proprietary licence, and active-countermeasure content conflicts with passive-only AERIX policy.

### Методы обнаружения сигналов управления БПЛА, определение их параметров (AlexGyver community thread)
`1/5` · Russian · forum · 2024 · snippet  
<https://community.alexgyver.ru/threads/metody-obnaruzhenija-signalov-upravlenija-bpla-opredelenie-ix-parametrov.8000>


Russian hobbyist thread discussing how to detect UAV control signals with SDR and spectrograms and estimate their parameters; together with habr overview articles it shows the Russian-language open scene is dominated by manual HackRF/SDR# waterfall inspection and commercial detectors, with no open ML drone classifiers surfaced.


- Discussion centres on SDR spectrogram observation of control links; no code released.
- CyberLeninka results on 'обнаружение БПЛА' are surveys or a VAE on RadioML 2018.01A, not drone-specific code.

*E200:* Confirms a gap: no Russian/Ukrainian open ML drone-RF code found; E200 toolkit must rely on English/Chinese sources.


## RC control and telemetry links

### DIY-Multiprotocol-TX-Module (Multiprotocol/*.ino: FrSkyDVX_common, FrSkyX, FrSkyD, FrSkyR9_sx1276, DSM_cyrf6936, AFHDS2A_a7105, Futaba_cc2500, HOTT_cc2500)
`5/5` · English · github · 2026 · verified  
<https://github.com/pascallanger/DIY-Multiprotocol-TX-Module>


Open re-implementation of ~100 RC protocols on CC2500/A7105/NRF24/CYRF6936/SX1276 chips. Every hop-table size, packet period and chip channel spacing for FrSky D8/D16, FrSky R9 (900 MHz LoRa), Flysky AFHDS/AFHDS-2A, Futaba S-FHSS, Graupner HoTT, Spektrum DSM2/DSMX, Hubsan and Potensic is a compile-time constant. This is the single best verified source for the 2.4 GHz FHSS RC rows of the table.


- FrSky D8 (FrSkyD_cc2500.ino): 47 hop channels generated as (i*0x1E)%0xEB, 9 ms packet period; CC2500 register set MDMCFG4/3=0xAA/0x39, DEVIATN 0x42 -> 31.0 kbps 2-FSK, 31.7 kHz deviation, 135 kHz RX filter (computed from CC2500 formulas with 26 MHz XTAL).
- FrSky D16 (FrSkyX_cc2500.ino): 47 channels stepped by chanskip, 9 ms period; MDMCFG4/3=0x7B/0x61 -> 70.0 kbps (X2 v2.1 0x84 -> 77 kbps, comment 'bitrate 70K->77K'), deviation 57 kHz, 232 kHz filter; EU-LBT set 0x7B/0xF8 -> 100 kbps.
- FrSky R9 (FrSkyR9_sx1276.ino): SX1276 LoRa BW 500 kHz, CR 4/5, SF6, manual hopping over FCC 43 / EU 19 / FLEX 29 channels, ~20 ms packet period (return 20000-460).
- DSM (DSM_cyrf6936.ino): 11 ms or 22 ms frames, second channel written 4.01 ms after the first (DSM_CH1_CH2_DELAY 4010), bind on odd channel 13, DSM2_SFC period 16.5 ms.
- AFHDS2A (AFHDS2A_a7105.ino): AFHDS2A_NUMFREQ 16 hop channels, 3850 us packet period, 38-byte TX / 37-byte RX (telemetry) packets.
- Futaba S-FHSS (Futaba_cc2500.ino comments): data rate 128,143 bps 2-FSK, filter 232 kHz, channel spacing 249,938 Hz with every 6th channel used (1.5 MHz effective spacing), 4 preamble bytes, 13-byte packets, 6.8 ms period.
- Graupner HoTT (HOTT_cc2500.ino): 75 RF channels, 10 ms period, 50-byte TX / 22-byte RX packets, MSK with FEC and 32-bit sync word; MDMCFG4/3=0x2D/0x3B -> 249.9 kbps, 542 kHz filter.
- Protocols_Details.md: HoTT, S-FHSS, FrSky D/X/X2 on CC2500; DSM, Devo, J6Pro on CYRF6936; Flysky/AFHDS2A/Hubsan on A7105; FrSky R9 on SX1276 (915/868); FrSky ACCESS absent.
- _(6 more facts in the JSON index)_

*E200:* All listed protocols are 2.4 GHz (or 868/915 for R9) FSK/LoRa links with 3.85-22 ms periods and 16-75 hop channels; a 56 MHz E200 capture of 2.400-2.456 GHz sees most hops of each.

### ESP32_CRSFSniffer - Crossfire 868 MHz air-link sniffer on Heltec ESP32/SX1276
`5/5` · English · github · 2022 · verified  
<https://github.com/g3gg0/ESP32_CRSFSniffer>


ESP32+SX1276 receiver that follows a TBS Crossfire link. The source code fixes the Crossfire 150 Hz FSK parameters, channel grid, hop-table length, slot timing and packet lengths in numbers, and documents the packet framing (packet type, 10-bit sticks, telemetry, CRC). Directly transferable to a GNU Radio FSK demod on the E200.


- Hardware: 'Heltec LoRa ESP32 with SX1276' plus OLED; milestones include 'Display channel values', 'Add hopping support', 'Scan hopping sequence'; marked WIP, analysis-only.
- cfgBitrate = 85000 baud, cfgFreqDev = 42300 Hz (FSK), packet_ms = 6666.67 us (150 Hz schedule), learnSchedLength ~6676 us
- Channel grid cfgChanDist = 260 kHz from startFreq 860 MHz (868 band) or 900 MHz (915 band); hoppingSequence[150] entries
- Uplink payload length 0x17 = 23 bytes, downlink 0x0D = 13 bytes
- Frame comment: byte0 packet type 3 = normal FSK data, 1 = 50 Hz mode; 80 bits = 8 sticks × 10 bits; telemetry length/flags; CRC at end
- No encryption; the CRC is the only pairing discriminator

*E200:* Register values in its code can be transcribed into gr-lora_sdr parameters.

### ExpressLRS firmware (src/lib/FHSS/FHSS.cpp, src/src/common.cpp, src/lib/OTA/OTA.h, SX1280Driver, SX127xDriver)
`5/5` · English · github · 2026 · verified  
<https://github.com/ExpressLRS/ExpressLRS>


The authoritative source for how ELRS looks on air: regulatory-domain frequency tables, FHSS sequence generator, per-rate modulation tables (SF/BW/CR/preamble/interval/hop interval/TOA), OTA packet layout and CRC seeding. Everything a heuristic classifier and a future decoder need is in code, not docs.


- FHSS domains (FHSS.cpp): AU915 915.5-926.9 MHz 20 ch; FCC915 903.5-926.9 MHz 40 ch (600 kHz spacing); EU868 863.275-869.575 MHz 13 ch (525 kHz); IN866 4 ch; AU433/EU433 3 ch; US433 433.25-438.0 MHz 8 ch; US433W 423.5-438.0 MHz 20 ch; TH920 8 ch; ISM2G4/CE_LBT 2400.4-2479.4 MHz 80 ch (1 MHz spacing).
- FHSS sequence: length 256 truncated to a multiple of freq_count, sync channel = freq_count/2 (band centre) forced at every multiple of freq_count, remaining entries shuffled by rngN seeded from the UID (binding phrase MD5); requirement comments: 'sync every n hops, no two repeated channels, equal occurrence, pseudorandom'.
- 2.4 GHz SX1280 rate table (common.cpp): FLRC F1000/F500/D500/D250 = BR 0.65 Mb/s BW 0.6 MHz, BT 1, CR 1/2, 32-bit preamble, hop every 2 packets, interval 1000/2000/1000/1000 us; LoRa 500 Hz SF5 CR_LI 4/6, 333 Hz Full SF5 CR_LI 4/8 (13-byte), 250 Hz SF6, 150 Hz SF7, 100 Hz Full SF7, 50 Hz SF8 - all BW_0800 (812.5 kHz), preamble 12 (14 for SF6), hop every 4 packets (2 for 50 Hz), intervals 2000/3003/4000/6666/10000/20000 us.
- Time-on-air per packet (RFperf table, us): F1000 389; LoRa2G4 500 Hz 1507, 333 Hz 2374, 250 Hz 3300, 150 Hz 5871, 100 Hz Full 7605, 50 Hz 10798; 900 MHz 200 Hz 4380, 100 Hz Full 6690, 100 Hz 8770, 50 Hz 18560, 25 Hz 29950.
- 900 MHz SX127x modes all use BW 500 kHz: 200 Hz SF6 CR4/7 preamble 8; 100 Hz Full SF6 CR4/8; 100 Hz SF7 CR4/7; 50 Hz SF8 CR4/7 preamble 10; 25 Hz SF9 CR4/7 preamble 10; hop every 4 packets (2 for 25 Hz and DVDA); default LoRa sync word 0x12 (SX127xRegs.h).
- LR1121/LR2021 targets add GFSK modes (300 kb/s, BW 467 kHz, fdev 100 kHz, 16-bit preamble, 1000 Hz) on both 900 MHz and 2.4 GHz, plus dual-band LoRa modes (X150: 900 MHz SF6 BW500 + 2.4 GHz SF7 BW800 simultaneously) and Gemini (second radio at half-domain offset, FHSSGeminiFreq()).
- Sync packets (OTA.h OTA_Sync_s) carry fhssIndex, nonce, rfRateEnum, UID4 and UID5 in plaintext; RFperf table: sync packet interval when disconnected is 3-11 ms at 2.4 GHz and 600 ms at 900 MHz, 5000 ms when connected.
- PHY framing: SX1280 LoRa uses fixed-length (implicit header) packets with no LoRa CRC ('CRC is only on for FLRC', SX1280.cpp:512); ELRS's own CRC14 (poly 0x2E57, 8-byte OTA4) or CRC16 (0x3D65, 13-byte OTA8) is seeded with (UID[4]<<8\|UID[5]) ^ OTA_VERSION_ID<<8 ^ nonce; IQ inversion = UID[5]&1; FLRC uses a UID-derived 32-bit sync word, UID-derived CRC seed and 3-byte CRC, whitening disabled.
- _(1 more facts in the JSON index)_

*E200:* All ELRS bands (433/868/915/2.4 GHz) are inside the E200's 70 MHz-6 GHz range; the 80-channel 2.4 GHz domain spans 79 MHz so the 56 MHz max bandwidth can only see ~70% of it at once, while the 900 MHz domains (<=23.4 MHz wide) fit entirely.

### GNU_Radio_ExpressLRS - An implementation of ExpressLRS in GNU Radio (FAU CAAI, GRCon25)
`5/5` · English · github · 2025 · verified  
<https://github.com/Diamond-D0gs/GNU_Radio_ExpressLRS>


The only public GNU Radio ELRS implementation: TX and RX flowgraphs built on gr-lora_sdr blocks plus a Python 'FHSS Controller' block that re-implements the ELRS hop-sequence generator (MD5 binding phrase -> seed, ELRS LCG). Includes a COTS-ELRS capture flowgraph for PlutoSDR at 61.44 MS/s. Starting point for an E200 ELRS follower/decoder.


- Flowgraphs use lora_sdr lora_rx/lora_tx hierarchical blocks with sync_word [0x12], impl_head True, has_crc True, pay_len 6/8 and iio_pluto_source/sink; cot_elrs_capture.grc captures a COTS transmitter at samp_rate 61,440,000.
- elrs_receiver_epy_block_0.py reproduces ELRS FHSS: seed = (uid[2]<<24)\|(uid[3]<<16)\|(uid[4]<<8)\|(uid[5]^OTA_VERSION_ID) with uid = md5(binding_phrase)[0:6], LCG seed=(0x343FD*seed+0x269EC3)%0x80000000, sequence length 256, same block-swap shuffle as FHSS.cpp.
- No README; validate.py counts missed packets over 1000-packet runs, i.e. the project validates its own TX->RX loopback, not decoding of COTS ELRS payloads (their RX uses LoRa CRC/explicit-header conventions ELRS does not use).

*E200:* Flowgraphs use iio_pluto_source/sink (libiio); the ANTSDR E200 is also an AD9361/libiio device, so swapping in a plutoSDR-style IIO source over Ethernet is straightforward.

### gr-lora_sdr - EPFL GNU Radio 3.10 LoRa transceiver
`5/5` · English · github · 2024 · verified  
<https://github.com/tapparelj/gr-lora_sdr>


Reference open LoRa PHY for GNU Radio 3.10 (TX+RX, SF5-12, CR 0-4, implicit/explicit header, soft decoding, low-SNR sync). Directly usable for 900 MHz ELRS, Crossfire and FrSky R9 (SX127x-class LoRa at BW 500 kHz); not directly usable for 2.4 GHz ELRS LoRa (SX1280 long-interleaver CR, unresolved SX1280 issue).


- README: 'Spreading factors: 5-12 (SF5 and SF6 are not compatible with SX126x)', coding rates 0-4, implicit and explicit header, payload 1-255 bytes, sync word selection, CRC verification, low-datarate optimisation, soft-decision decoding; tested with RFM95, SX1276, SX1262; GNU Radio 3.10; GPL-3.0; conda package available.
- lib/ contains frame_sync, fft_demod, gray_demap, deinterleaver, hamming_dec, dewhitening, crc_verif blocks; no code references a long-interleaver (SX1280 CR_LI) mode.
- Papers: Tapparel et al., SPAWC 2020 (arXiv 2002.08208) and GRCon 2024 'Design and Implementation of LoRa Physical Layer in GNU Radio'.

*E200:* Runs on the Linux host; a BW 500 kHz LoRa channel needs only ~1-2 MS/s per channel, so many parallel channelised decoders can be run from one 56 MHz E200 capture.

### DroneRFb-DIR: 用于非合作无人机个体识别的射频信号数据集 (电子与信息学报, zh)
`4/5` · Chinese · dataset · 2025 · snippet  
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT240804>


Chinese open dataset aimed at RF fingerprinting of individual airframes rather than model classification: 6 drone types, 3 individuals each, plus a background class, captured with SDR in an urban setting over 2.4-2.48 GHz as raw IQ, covering flight-control and video signals plus ambient interference. Complements DroneRFa (same group, JEIT230570). Hosted on ScienceDB (blocked) — no GitHub mirror found.


- Collected over 2.4-2.48 GHz; contains flight-control, video-transmission and surrounding interference signals; proposes an individual-identification method based on fast frequency estimation and time-domain correlation.
- 6 drone types x 3 individuals + 1 background class; >40 segments per type; >4 million samples per segment; raw I/Q
- Band 2.4-2.48 GHz; includes flight-control (RC) and video-transmission signals and surrounding interference
- Authors Ren Junyu, Yu Ningning, Zhou Chengwei, Shi Zhiguo, Chen Jiming (Zhejiang Univ.); JEIT 2025 vol 47 no 3 pp 573-581
- Data page: https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202 ; journal data page https://jeit.ac.cn/news/Dataset7-1/49eecb2e-8565-4007-ac33-f8f352f74dc1.htm ; PDF https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4

*E200:* 2.4-2.48 GHz span (80 MHz) exceeds one 56 MHz E200 window; dataset would need band-splitting to match.

### Hacking the DSMx Drone RC protocol (GNU Radio Conference proceedings)
`4/5` · English · paper · 2021 · snippet  
<https://pubs.gnuradio.org/index.php/grcon/article/view/97>


Paper behind gr-dsmx-rc: DSMx is a FHSS+DSSS GFSK 1 Mb/s protocol on CYRF6936; the GNU Radio decoder detects, follows the hop sequence and identifies the transmitter by manufacturer ID. PDF blocked from fetch; facts from abstract/snippets.


- DSMx works on a CYRF6936 radio implementing frame-based transmission with FHSS and DSSS on GFSK at 1 Mbit/s in the 2.4 GHz ISM band; DSMX uses 23 channels derived from the transmitter GUID, DSM2 uses 2.

*E200:* Confirms DSMX is fully decodable (unencrypted) with an SDR.

### Implementation and Analysis of ExpressLRS Under Interference Using GNU Radio (GRCon 2025)
`4/5` · English · paper · 2025 · snippet  
<https://events.gnuradio.org/event/26/contributions/771/attachments/238/622/GabrielGarcia-FAUCAAI-Grcon25.pdf>


GRCon25 paper accompanying the GNU_Radio_ExpressLRS repo: first open-source ELRS in GNU Radio, built on gr-lora with frequency hopping, software- and hardware-in-the-loop with PlutoSDRs; shows spectrograms of a COTS FCC915 ELRS TX beaconing while searching for a receiver and of five simulated ELRS TXs.


- A COTS ExpressLRS transmitter in the FCC915 domain was captured with an ADALM-Pluto; spectrograms show frequency-hopping beacon packets while the TX searches for a connection.
- Implementation extends the GNU Radio LoRa implementation to support frequency hopping; evaluated under several interference types.

*E200:* Same AD9361 front end as PlutoSDR; results transfer directly.

### Reverse Engineering A 900 MHz RC Transmitter And Receiver (TBS Crossfire, g3gg0)
`4/5` · English · blog · 2022 · snippet  
<https://hackaday.com/2022/02/20/reverse-engineering-a-900-mhz-rc-transmitter-and-receiver>


Summary of g3gg0's Crossfire teardown: receiver = PIC32 + SX1272 LoRa modem; SPI-sniffed register settings reveal modulation and the hop sequence; packets are simple with a brute-forced CRC; no protection against eavesdropping. Establishes Crossfire as LoRa-on-SX1272, i.e. decodable with SX127x-compatible SDR LoRa code.


- Receiver module consists of little more than a PIC32 microcontroller and an SX1272 LoRa modem; hop sequence derived from sniffed register settings; CRC brute-forced; 'no security against eavesdropping or deliberate interference'.
- Search snippet from g3gg0.de: on most modes Crossfire uses channels 0-49 for TX->RX and the receiver answers exactly 50 channels up (50-99).

*E200:* 868/915 MHz LoRa at SX1272 bandwidths (<=500 kHz) is within gr-lora_sdr/SDRangel capability on the E200.

### SiK - firmware for Si1000/Si106x telemetry radios (Firmware/radio/freq_hopping.c, tdm.c, main.c, radio_443x.c)
`4/5` · English · github · 2024 · verified  
<https://github.com/ArduPilot/SiK>


Source of truth for 3DR/Holybro/RFD 433/868/915 MHz MAVLink telemetry radios: GFSK air rates, FHSS channel plan, TDM window/hop timing and optional Golay ECC/AES. Enables a GFSK burst-timing signature and, with a demod, plaintext MAVLink recovery.


- Air data rates (kbps): 2, 4, 8, 16, 19, 24, 32, 48, 64, 96, 128, 192, 250; default AIR_SPEED 64, NETID 25, ECC off, DUTY_CYCLE 100, MAX_WINDOW 131 ms (parameters.c).
- Default band plans (main.c): 433.05-434.79 MHz 10 channels; 470-471 MHz 10; 868-870 MHz 10; 915-928 MHz MAX_FREQ_CHANNELS = 50; channel_spacing = (freq_max-freq_min)/(num_channels+2).
- freq_hopping.c: channel map shuffled from NetID-derived seed; tdm.c changes frequency at the start and end of each transmit window (fhop_window_change), windows sized from air rate (silence_period = 2*packet_latency); Golay 23/12 ECC and MAVLink framing optional; AT&E sets an AES key in newer firmware.

*E200:* Sub-GHz band fits entirely within 56 MHz; GFSK at <=250 kb/s is trivial for host-side demod.

### SiKW00F - Drone SiK Radio Detection & MAVLink Telemetry Eavesdropping Toolkit
`4/5` · English · github · 2025 · verified  
<https://github.com/nicholasaleks/sikw00f>


Demonstrates that SiK links are detectable and readable: a third SiK radio with modified firmware runs promiscuous to harvest NetIDs, then follows the NetID-derived hop sequence and logs plaintext MAVLink (HEARTBEAT, GLOBAL_POSITION_INT, GPS_RAW_INT, ...). Uses a SiK radio, not an SDR, but defines what an SDR-side SiK decoder should output.


- README: SiK radios use FHSS with a pseudo-random sequence derived from the NetID; stock firmware hardware-filters on NetID, custom firmware adds 'NetID Header Control Bypasses, Real-Time NetID Overwrite, Silent Statistic Frames, State Machine Synchronization'.
- Modes: --scan (passive NetID/channel discovery), --autotune <NET_ID> (copy S3 NETID, S8/S9 min/max freq, S10 channels), --eavesdrop (MAVLink capture to SQLite).

*E200:* Blueprint for a passive SiK follower on the E200: detect GFSK bursts, decode header to get NetID, then track hops.

### [FPV] Analysis of TBS Crossfire, reverse engineering the air link (g3gg0.de)
`4/5` · English · blog · 2022 · snippet  
<https://www.g3gg0.de/wordpress/fpv/fpv-analysis-of-tbs-crossfire>


Primary Crossfire reverse-engineering write-up with the SX1272 register dumps (LoRa SF/BW/CR, sync, CRC, channel plan). Fetch blocked here; must be read directly to fill in the exact per-mode LoRa parameters.


- Crossfire uses channel hopping with sequence recoverable from register settings; TX channels 0-49, RX replies on 50-99.

*E200:* Needed to parameterise a Crossfire LoRa detector/decoder.

### gr-dsmx-rc - GNU Radio Spektrum DSMX decoder (Morin & Cardoso, INSA Lyon)
`4/5` · English · github · 2017 · verified  
<https://github.com/lscardoso/gr-dsmx-rc>


Only public SDR decoder for a legacy 2.4 GHz RC protocol: preambleDetection block correlates the CYRF6936 SOP/PN codes per channel, Despreader de-spreads the DSSS chips, bindListener parses bind packets; example flowgraph runs at 4 MS/s intermediate rate. Needs porting from GR 3.7-era build to 3.10.


- Blocks: dsmx_preambleDetection(channel), dsmx_Despreader, dsmx_bindListener; preamble detector searches 9 PN-code columns per channel row with an error threshold of 5 bits and then verifies the inverted SOP to confirm data rate.
- Example DSMxDemod.grc uses intermediate_samp_rate = 4e6 and a 32-sample decimation variable.
- GRCon paper abstract: decoder 'is able to detect a transmission, decode transmitted data, find and follow the corresponding frequency jump sequence and identify the emitter by its manufacturing ID'.

*E200:* DSMX is 2.4 GHz GFSK 1 Mb/s; the E200 can capture the whole 2.4 GHz ISM band in two 56 MHz halves or channelise around the 23-channel hop set.

### gr-lora_sdr issue #143: Trouble demodulating SX1280 LoRa signal vs RFM9x - same settings, different results
`4/5` · English · github · 2025 · verified  
<https://github.com/tapparelj/gr-lora_sdr/issues/143>


Open, unanswered issue: identical logical settings decode SX127x at 915 MHz but produce nothing for SX1280 at 2.39 GHz (SF7, BW 200/250 kHz, CR 4/5, ~14-symbol preamble). Evidence that 2.4 GHz SX1280 LoRa (the ELRS 2.4 GHz PHY) is not yet handled by the main open decoder.


- User tried sync words 0x12/0x1424 and BW 200/250 kHz; chirps look correct in Inspectrum but gr-lora_sdr outputs nothing; no maintainer response as of fetch.

*E200:* Warns that a 2.4 GHz ELRS LoRa decoder on the E200 will need SX1280-specific work (preamble/sync/interleaver), not just retuning.

### Data-driven classification of low-power communication signals by an unauthenticated user using a software-defined radio (Keshabhoina & Vasconcelos, Asilomar 2023)
`3/5` · English · paper · 2023 · snippet  
<https://arxiv.org/abs/2309.04088>


Shows that an SDR observer can jointly infer a LoRa signal's bandwidth and spreading factor from the instantaneous-frequency structure using a neural classifier - exactly the SF/BW identification step needed to label ELRS/Crossfire/R9 LoRa bursts before attempting decode.


- Relates joint (BW, SF) inference to a classification problem exploiting a structural pattern in the instantaneous frequency representation, implemented with neural networks.

*E200:* Feature extraction on host from E200 IQ.

### Drone Remote Controller RF Signal Dataset (Ezuma, Erden, Kumar, Ozdemir, Guvenc)
`3/5` · English · dataset · 2020 · snippet  
<https://ieee-dataport.org/open-access/drone-remote-controller-rf-signal-dataset>


17 RC controllers from 8 manufacturers (Spektrum, Futaba, Graupner, FlySky, JR, Turnigy, DJI ...) at 2.4 GHz, ~1000 captures each of 0.25 ms, recorded with an oscilloscope. Useful for waveform-level signatures of legacy FHSS radios, not for ELRS/Crossfire.


- 17 drone RCs, ~1000 RF signals each, 0.25 ms per record, all in the 2.4 GHz band, drones idle during capture.

*E200:* Captures are oscilloscope-based (very high sample rate), so preprocessing is required before comparing with 56 MHz E200 IQ.

### MILELRS v2.30 firmware (Ukrainian ExpressLRS 3.3.2 derivative) - EW_SCANNER, CUSTOM_FREQ_TELEM, MULTI_BAND
`3/5` · English · blog · 2025 · snippet  
<https://cybershafarat.com/2025/04/06/milelrs-v2-30-firmware-introduces-substantial-upgrades-based-on-expresslrs-3-3-2>


Describes the Ukrainian military ELRS fork: user-defined start/stop frequencies instead of regulatory domains, simultaneous multi-band (433/900/2400) links, telemetry moved to separate bands, and an on-board RF scanner. Shows that battlefield ELRS may appear anywhere in ~400-1000 MHz, so detectors must key on LoRa PHY signature rather than fixed ELRS channel tables.


- MILELRS can split packets between two ranges on one receiver (e.g. 750-760 MHz and 950-960 MHz) and duplicate links across 433/900/2400 MHz; 'there are no specified ranges in the settings - you need to specify the beginning and end of the frequency range yourself'.
- v2.30 adds EW_SCANNER (RF detection/mapping across a defined range, toggled by a remote switch), CUSTOM_FREQ_TELEM and MULTI_BAND (up to three paired TX-RX channels on independent bands).

*E200:* E200 can sweep 400-1000 MHz in ~11 x 56 MHz steps; LoRa chirp detection must be frequency-agnostic.

### NCC Group Technical Advisory - ExpressLRS vulnerabilities allow for hijack of control link
`3/5` · English · blog · 2022 · snippet  
<https://www.nccgroup.com/research/technical-advisory-expresslrs-vulnerabilities-allow-for-hijack-of-control-link>


Documents that ELRS sync packets leak most of the binding UID and that the link is unauthenticated/unencrypted; for a passive toolkit this means sync packets are a decodable identifier of a specific TX/RX pair.


- Sync packets expose 75% of the binding phrase's UID needed for link takeover; binding phrase is hashed with MD5; CRSF telemetry (MAVLink, GPS coordinates, altitude, speed) is sent in plaintext over the RF link.

*E200:* Justifies building a sync-packet parser (UID4/UID5 + rate + hop index) as a per-transmitter fingerprint.

### Roger Writes #3 / AFHDS and AFHDS-2A (Flysky protocol notes)
`3/5` · English · blog · 2019 · snippet  
<https://fareham.org/rw3-afhds2a.shtml>


Concise description of the Flysky A7105-based AFHDS/AFHDS-2A air protocol: 160 x 500 kHz channels, 500 kb/s, 16 random hop channels sent during bind, 3.85 ms period with a listen slot one channel down for telemetry. Complements the Multiprotocol code.


- AFHDS-1 and AFHDS-2A split 2400-2483 MHz into 160 channels of 500 kHz; over-air rate 500 kbps; 16-bit payload CRC and 32-bit packet ID; AFHDS-2A adds FEC (4 data bits sent as 7 bits).
- TX switches between sending channels with a 3.85 ms period and listens one channel down for the remainder of the period; the 16 channels are generated by the TX and sent to the RX during bind.

*E200:* 500 kb/s GFSK bursts every 3.85 ms on 16 of 160 channels is a distinctive 2.4 GHz signature.

### SDRangel ChirpChat (LoRa-compatible) demodulator plugin
`3/5` · English · doc · 2025 · verified  
<https://github.com/f4exb/sdrangel/blob/master/plugins/channelrx/demodchirpchat/readme.md>


GUI LoRa-compatible demod inside SDRangel: configurable SF, CR 4/5-4/8, sync word, optional header, bandwidth list derived from 500/400/333/384 kHz bases. Handy for quick manual checks of 900 MHz ELRS/Crossfire, but its maximum bandwidth is 500 kHz so it cannot demodulate 812.5 kHz 2.4 GHz ELRS.


- Bandwidth options are 500 kHz, 400 kHz, 333.333 kHz and 384 kHz divided by powers of two (max 500 kHz); baseband must be at least twice the bandwidth; decode errors likely below 4 dB SNR; 'LoRa compatible protocol based on the reverse engineering performed by the community'.

*E200:* SDRangel has a PlutoSDR/libiio input; E200 can be used through its IIO network back end for live viewing.

### SkySweep32 - multi-band passive drone detector on ESP32 (ru/en README)
`3/5` · Russian · github · 2025 · verified  
<https://github.com/bobberdolle1/SkySweep32>


Bilingual (RU/EN) open-source ESP32-S3 detector with CC1101 (855-925 MHz), SX1281 (2.4 GHz) and RX5808 (5.8 GHz) energy front-ends, GNSS, microSD, ESP-NOW mesh and an experimental BLE Remote ID parser. It is the reference for what the RU-language DIY scene can do without an SDR: pure RSSI tiering, no identity. Rev C hardware has never been built or RF-characterised.


- README (fetched): 'does not jam, inject RF, deny GPS, identify transmitters from RSSI, or provide directional finding'; bands 855-925 MHz, 2.4 GHz, 5.8 GHz; 'No Rev C board has been physically assembled, bench-tested, RF-characterized'.
- Search snippets (older README) claim TFLite classification of drone classes from RSSI variance and 'hop' patterns and cascaded VCO countermeasures for DJI/Walksnail/ELRS - contradicts current README.
- Front-ends: Ebyte E07-900M10S/CC1101 sampled at 860/890/920 MHz; E28-2G4M12SX/SX1281 instantaneous RSSI; RX5808 with eight hardware-selected channels and analog RSSI
- Detection is relative normalized RSSI 0-100 with tiers LOW/MEDIUM/HIGH/CRITICAL at 45/60/75/85 (src/config.h); README explicitly says it does not identify transmitters, DF, jam or deny GPS
- Remote ID: BLE scan for service UUID 0000fffa, parses ASTM F3411-22a message types Basic ID/Location/System/Operator ID (src/remote_id_detector.h)
- GPL-3.0; last commit 2026-08-13; status 'NOT PRODUCTION VALIDATED'; docs in docs/ru and docs/en; KiCad Rev C in hardware/rev_c
- Earlier revisions/search snippets advertised 'fingerprinting' and 'countermeasures'; current code contains neither

*E200:* Only as a list of bands/heuristics to compare against; no reusable DSP.

### gr-lora - GNU Radio blocks for receiving LoRa (Robyns et al.)
`3/5` · English · github · 2017 · verified  
<https://github.com/rpp0/gr-lora>


Original reverse-engineered LoRa receiver for GNU Radio; receive-only, single channel, no CRC checks, tested with USRP B201; older GNU Radio/python2 tooling. Historically important, but gr-lora_sdr supersedes it for new work.


- README: does not support CRC checks of payload/header nor decoding multiple channels simultaneously; example trace 868.1 MHz SF7 CR4/8 BW125; Docker image provided; DOI 10.5281/zenodo.853201.

*E200:* Usable only after porting to GR 3.10; prefer gr-lora_sdr.

### Прошивка MILERLS оппонентов / Инструкция по прошивке управления MILELRS (techuav.github.io, ru)
`3/5` · Russian · doc · 2025 · snippet  
<https://techuav.github.io/%D0%9F%D0%9B%D0%90%D0%A2%D0%A4%D0%9E%D0%A0%D0%9C%D0%90_FPV/%D0%9F%D1%80%D0%BE%D1%88%D0%B8%D0%B2%D0%BA%D0%B0/%D0%9F%D1%80%D0%BE%D1%88%D0%B8%D0%B2%D0%BA%D0%B0_MILERLS_%D0%BE%D0%BF%D0%BF%D0%BE%D0%BD%D0%B5%D0%BD%D1%82%D0%BE%D0%B2.html>


Russian-language field documentation describing the opponent's (Ukrainian) MILELRS firmware and how to flash MILELRS-type control links; corroborates that custom-frequency ELRS forks are in wide use on both sides, which affects which bands an ELRS detector must cover.


- MILELRS is custom receiver firmware built on the ExpressLRS platform by Ukrainian engineers in the first half of 2024 (search snippet).

*E200:* Supports scanning the full 400-1000 MHz range for LoRa chirps.

### ELRS技术详解：基于LORA的低功耗远程无线电系统及其特性 (CSDN, zh)
`2/5` · Chinese · blog · 2024 · snippet  
<https://blog.csdn.net/csdnpmsm/article/details/137477858>


Chinese ELRS explainers confirming the RF parameters to look for: SX127x at 433/868/915 MHz and SX1280/1281 at 2.4 GHz, LoRa and FLRC modulation, FHSS, and the standard TX power ladder. Nothing beyond the English ELRS docs, but useful for Chinese labels in a signal library.


- ELRS 'has evolved from an amateur DIY solution to a de facto standard in consumer drone applications, featuring adaptive frequency hopping, TDD bidirectional links and minimalist data packets'; supports FLRC on 2.4 GHz for higher rate/lower latency.
- Bands 2.4 GHz, 433/868/915 MHz; radios SX127x (sub-GHz) and SX1280/SX1281 (2.4 GHz); LoRa + FLRC
- FHSS adaptive hopping; telemetry returned in-band by time division
- Power steps 25/100/250/500/1000/2000 mW (14-33 dBm)
- Zhihu: https://zhuanlan.zhihu.com/p/720873035 , https://zhuanlan.zhihu.com/p/695156875 ; CSDN dual-band ELRS: https://blog.csdn.net/lida2003/article/details/143709303

*E200:* Context/terminology for Chinese sources.

### HeimdallRF - pocket ESP32 passive drone detector (868/915 MHz, 2.4 GHz, 5.8 GHz)
`2/5` · English · github · 2025 · verified  
<https://github.com/autrion/HeimdallRF>


Passive RSSI-scanning ESP32 detector covering LoRa/Crossfire/LRS at 868/915, ELRS/FrSky/Wi-Fi FPV at 2.4 GHz and analog video at 5.8 GHz; MIT + Commons Clause. Representative of the many ESP32 'detectors' that only do energy detection - a baseline the E200 toolkit should clearly exceed.


- README: RSSI scanning, 'Passive only - no jamming', OLED UI, USB-CDC logging; firmware MIT with Commons Clause, hardware CERN-OHL-S with Commons Clause; radio chips not named in README.

*E200:* Baseline comparison only.

### New Frsky Air Protocol - ACCESS (Oscar Liang) / Multiprotocol issue #239 and #487
`2/5` · English · blog · 2019 · snippet  
<https://oscarliang.com/frsky-access-protocol>


Explains that FrSky ACCESS (2.4 GHz and 900 MHz, up to 24 channels) is encrypted specifically to prevent the reverse engineering that happened to ACCST, and therefore is absent from the open Multiprotocol module. For the toolkit: ACCESS is detect/classify-only.


- ACCESS is applied to both 900 MHz and 2.4 GHz and supports up to 24 channels; unencrypted ACCST was reverse engineered, one reason for FrSky moving to the encrypted ACCESS protocol; DIY multiprotocol modules cannot support ACCESS.

*E200:* Detect-only class.

### PrivacyLRS - encrypted fork of ExpressLRS
`2/5` · English · github · 2024 · snippet  
<https://github.com/sensei-hacker/PrivacyLRS>


Fork that wraps the same ELRS physical layer with ChaCha20 encryption so telemetry/positions cannot be read. Relevant as the counter-example: same on-air signature as ELRS (detectable, classifiable) but not decodable.


- 'PrivacyLRS wraps the same physical layer with ChaCha20' and 'uses strong encryption to make it impossible for other people to read your telemetry'.

*E200:* Classifier output should distinguish 'ELRS-like PHY' (detectable) from 'payload decoded' (only for stock ELRS).

### Анализатор спектра или детектор дронов: что выбрать (FPV клуб, ru)
`2/5` · Russian · blog · 2025 · snippet  
<https://fpv-club.ru/analizator-spektra-ili-detektor-dronov-otlichija>


Russian comparison of spectrum analysers vs. signature-based drone detectors; states that detectors passively recognise signatures of DJI OcuSync, Autel, ELRS and Crossfire, and that SDR analysers reveal digital signal structure better than sweeping analysers - i.e. the same design thesis as this toolkit.


- Modern detectors passively scan for characteristic signatures of control/telemetry protocols including DJI OcuSync, Autel, ELRS and Crossfire; ELRS and Crossfire operate in 433 MHz, 868 MHz and 2.4 GHz bands.
- SDR analysers (HackRF) better show digital signal structure; sweep analysers (TinySA ZS407) more accurately measure level/frequency of analog components
- Signature detectors passively look for OcuSync, Autel, ELRS, Crossfire and Wi-Fi link signatures
- tinySA Ultra: 800 MHz normal, 6.0 GHz ultra mode; newer tinySA monitors to 7.3 GHz (per techuav post)

*E200:* Motivates signature (timing/bandwidth) classification over RSSI-only detection.

### Детектори дронів 2025: як обрати найкращий пристрій для виявлення безпілотників (Мілітарний, uk)
`2/5` · Ukrainian · blog · 2025 · snippet  
<https://militarnyi.com/uk/special-projects/yak-vybraty-detektor-droniv-oglyad-modelej-i-klyuchovi-kryteriyi-vyboru>


Ukrainian overview of commercial FPV/drone detectors; lists the bands they scan for ELRS/FPV links, which documents the de-facto operating ranges of battlefield RC links (well outside the ELRS regulatory domains).


- Arrakis 4 detects FSK signals at 860-928 / 955-1020 MHz and ELRS/FPV at 720-915 MHz within 3-4 km; another device covers 433/450/750/868/915/921 MHz plus SDR 2.4 GHz with ELRS (LoRa) scanning and 500-2000 m range.

*E200:* Band list to seed E200 sweep plans.

### Протоколи керування FPV: Lora, ELRS, Crossfire (reb.com.ua, uk)
`2/5` · Ukrainian · blog · 2024 · snippet  
<https://reb.com.ua/protokoli-keruvannya-fpv-lora-elrs-crossfire>


Ukrainian EW-community explainer of FPV control protocols (LoRa, ELRS, Crossfire) and their bands; useful as a language bridge for Ukrainian terminology and for the claim of 30+ km 900 MHz ELRS ranges.


- ELRS uses 900 MHz (868/915) and 2.4 GHz with ranges up to 30+ km in 900 MHz mode.

*E200:* Context only.

### ExpressLRS Backpack firmware (ESP8285 ESP-NOW / Wi-Fi sidecar)
`1/5` · English · github · 2025 · snippet  
<https://github.com/ExpressLRS/Backpack>


Many ELRS TX modules carry a second ESP8285 that talks ESP-NOW (802.11 data frames at 2.4 GHz) to goggles/VRX and exposes a Wi-Fi AP ('ExpressLRS TX Backpack') only in Wi-Fi mode. A secondary, Wi-Fi-decodable fingerprint of an ELRS pilot, but not present in flight unless enabled.


- TX-backpack uses an additional ESP8285 chip communicating via ESP-NOW with other ESP8285 devices for command/control; Wi-Fi SSID appears as 'ExpressLRS TX Backpack' in Wi-Fi mode.

*E200:* Detectable with a Wi-Fi/ESP-NOW sniffer path (gr-ieee802-11) rather than the LoRa path.

### Skydroid T10 2.4 GHz 10ch FHSS transmitter manual (and Herelink FCC listings 2ARLU-HC06071 / 2A7W3-HX406210)
`1/5` · English · vendor · 2023 · snippet  
<https://manuals.plus/skydroid/t10-2-4ghz-10ch-fhss-transmitter-with-r10-mini-receiver-manual>


Only public data found on the Chinese integrated RC+video systems: Skydroid T10 is a 2.4 GHz FHSS link with digital video (7 km) and data (10 km); Herelink air unit FCC IDs exist but the test reports (modulation, bandwidth) could not be fetched. These links are digital-video-class signals rather than narrowband RC links.


- Skydroid T10 'uses FHSS technology ... dual antenna plus dual RF module, digital video transmission up to 7 km and data transmission up to 10 km'; Herelink FCC IDs 2ARLU-HC06071 (controller) and 2A7W3-HX406210 (air unit v1.1).

*E200:* Likely wideband (multi-MHz) 2.4 GHz OFDM-like signals; treat under the video-link lens.


## Video links

### svpcom/wfb-ng - WFB-ng raw-802.11 long-range packet link (used by OpenIPC, PX4 docs)
`5/5` · English · github · 2026 · verified  
<https://github.com/svpcom/wfb-ng>


Reference implementation of wifibroadcast-NG by Vasily Evseenko (Russian author, Telegram-based community). Code reveals the exact on-air fingerprint: 802.11 data frames with a fixed 57:42 MAC prefix, radiotap MCS injection, ChaCha20-Poly1305 encrypted payload. Default config: 5825 MHz (ch 165), 20 MHz, MCS1, STBC1, LDPC1, video FEC 8/12.


- src/wifibroadcast.hpp ieee80211_header: 0x08,0x01,0x00,0x00 (data frame, not protected, ToDS), RA ff:ff:ff:ff:ff:ff, TA/SA = 0x57,0x42,aa,bb,cc,dd where last 4 bytes = channel_id = (link_id<<8)+radio_port; rx BPF: ether[0x0a:2]==0x5742.
- radiotap_header_ht: TX_FLAGS NOACK + MCS field (bw/gi/stbc/fec known); radiotap_header_vht variant for VHT; frame_type can be 'data' or 'rts' (0xb4).
- master.cfg defaults: wifi_channel = 165 (5825 MHz, 20 MHz), bandwidth 20 (or 40), force_vht False, short_gi False, stbc 1, ldpc 1, mcs_index 1; [video] fec_k 8, fec_n 12; radio_mtu 1445; WIFI_MTU 4045.
- Payload encrypted/authenticated with libsodium aead_chacha20poly1305 (session key exchanged in session packets) -> video not decodable without keys.
- Supported cards: RTL8812AU/EU (patched drivers), Atheros AR9350 (ath9k SoC); any monitor-mode card can RX.
- Stream allocation: 0-15 video, 16-31 MAVLink, 32-47 tunnel; downlink 0-127, uplink 128-255.

*E200:* Detection/attribution of wfb-ng links is best done with a monitor-mode NIC keyed on the 57:42 MAC prefix and channel_id; on the E200 they appear as 20/40 MHz 802.11n bursts at MCS1 around 5825 MHz by default, decodable only as far as the legacy preamble.

### zubon2003/5G8atv-rf-hackrf-decoder (fpvdec) - standalone C++20 FM-ATV NTSC decoder for 5.8 GHz FPV
`5/5` · English · github · 2026 · verified  
<https://github.com/zubon2003/5G8atv-rf-hackrf-decoder>


Real-time color NTSC decoder for 5.8 GHz analog FPV using a HackRF at 10 MSPS with no GNU Radio dependency. Documents the on-air FM-ATV parameters (5 MHz peak deviation, energy within +/-4.5 MHz), a two-stage AFC for VTX drift, and the full DSP chain. Has a Japanese README as well. The IQ front-end is HackRF-only but the decoder core is portable to E200 IQ.


- Default sample rate 10e6: 'FPV FM video fits in +-4.5 MHz (measured: <0.3% energy outside)'; 8e6 keeps coarse color, <=7e6 grayscale, ~6e6 minimum (src/config.hpp, README).
- FM peak deviation default 5e6 Hz (--dev); polarity can be inverted for non-standard VTX; 4.9 MHz complex channel LPF; 3.58 MHz chroma BPF; sync path on 1 MHz LPF stream.
- Two-stage AFC: cold-start VTX offsets of +2..3 MHz and ~1 MHz warm-up drift are tracked automatically.
- At 10 MSPS the FM audio subcarrier is outside Nyquist (config.hpp comment), i.e. not decoded.
- Channel table: A 5865..5725 (-20 MHz steps), B 5733,5752,5771,5790,5809,5828,5847,5866, E 5705,5685,5665,5645,5885,5905,5925,5945, F 5740..5880 (+20), R 5658,5695,5732,5769,5806,5843,5880,5917 MHz.
- Performance: ~2.4x real time at 10 MSPS on an i7-9700K; raw IQ record ~20 MB/s (cs8).
- License MIT; forked from GOROman/famicom-rf-hackrf-decoder.

*E200:* Decoder core can be fed E200 IQ (10 MSPS int8/float) via UHD or libiio with a small source shim; its measured +/-4.5 MHz occupancy is an *energy* figure for one VTX, not a capture requirement in general: the audio subcarriers and PAL chroma need more, and this project's own signal model swings to +6.4 MHz at peak white and aliases below 12.75 MSPS. Capture at 20 MSPS, which still leaves room for multi-channel sweeps.

### Kismet kismet_uav.conf - Wi-Fi drone SSID/OUI fingerprint rules
`4/5` · English · github · 2026 · verified  
<https://raw.githubusercontent.com/kismetwireless/kismet/master/conf/kismet_uav.conf>


Kismet's built-in UAV matcher: regex SSID plus OUI mask rules for DJI (Phantom3_, Mavic_, DJI-MAVIC3, DJI-MINI3-Pro-, Spark-, TELLO, OSMO_, 60:60:1F), Parrot (BebopDrone, Bebop2, ardrone2, SkyController; A0:14:3D, 90:3A:E6, 90:03:B7, 00:26:7E), 3DR Solo (SoloLink_), Propel, Attop YD-UFO, Syma FPV_WIFI_xxxx, XBM etc. Directly reusable for a monitor-mode Wi-Fi drone classifier.


- DJI rules all use OUI 60:60:1F with SSIDs ^Phantom3_.*, ^Mavic_.*, ^DJI-MAVIC3.*, ^DJI-MINI3-Pro-.*, ^Spark-(?!RC-).*, ^Spark-RC-.*, ^TELLO.*, ^OSMO_.*, ^Mavic-[0-9A-F]{6}$.
- Parrot rules: ^BebopDrone.* (A0:14:3D), ^Bebop2.* (90:3A:E6 / A0:14:3D), ^ardrone2.* (90:03:B7 / 00:26:7E), ^SkyController.* (A0:14:3D), ^JumpingSumo-.*.
- 3DR Solo ^SoloLink_.* (8A:DC:96); Syma ^FPV_WIFI__[0-9A-F]{4}$ (58:04:54); Attop ^YD[_-]UFO[_-].* across six OUIs; Propel/XBM toy drones.
- Format: uav_match=<id>:name=..,model=..,ssid=<regex>,mac=<OUI>/<mask>.

*E200:* Not SDR-level, but the toolkit's Wi-Fi-NIC companion stage can import these rules verbatim for Tello/Parrot/DJI-Wi-Fi identification.

### OpenHD/OpenHD - open-source HD digital FPV over raw Wi-Fi (channel list incl. non-standard 2.3/2.6/5.9-6.1 GHz)
`4/5` · English · github · 2026 · verified  
<https://github.com/OpenHD/OpenHD>


OpenHD core. ohd_interface/inc/wifi_channel.h enumerates every frequency OpenHD can use, including non-standard 2312-2712 MHz and 5080-6085 MHz entries, and validate_settings_helper.h restricts channel width to 10/20/40 MHz. wifi_card.h lists supported chipsets (RTL88x2AU/BU/CU/EU, 8852BU, Atheros, MT7921u). Critical for deciding the scan span of a detector.


- 2.4 GHz list includes non-standard 2312, 2332, 2352, 2372, 2392, 2492, 2512, 2612, 2692, 2712 MHz plus standard ch 1-14 (2412-2484).
- 5 GHz list runs 5080 (ch16) ... 5825 (165), 5845 (169), 5865 (173), 5885 (177), 5905, 5925, 5945, 5965, 5985, 6005, 6025, 6045, 6065, 6085 MHz; comment: 5885 'not valid in any country - but it works on rtl8812bu', 'More illegal channels' for 5905+.
- is_valid_channel_width: 10, 20 or 40 MHz only ('OpenHD does not use channel width <20Mhz' comment aside).
- WiFiCardType enum: OPENHD_RTL_88X2AU/BU/CU/EU, OPENHD_RTL_8852BU, RTL_88X2AU/BU, ATHEROS, MT_7921u, RALINK, INTEL, BROADCOM, AIC, QUALCOMM.
- README: 'OpenHD configures the Wi-Fi adapter in a way that is closer to a simple broadcast, much like analog video transmission'.

*E200:* An E200 sweep for OpenHD-class links must cover 2.3-2.7 GHz and 5.08-6.09 GHz, not just regulatory Wi-Fi channels; width detector must handle 10/20/40 MHz OFDM.

### OpenHD/wifibroadcast (Consti10) - OpenHD's wifibroadcast library with its own 802.11 header
`4/5` · English · github · 2026 · verified  
<https://github.com/OpenHD/wifibroadcast>


OpenHD's transport library. Ieee80211Header.hpp shows OpenHD frames use FC 0x08 0x01, broadcast RA and 13:22:33:44:55:xx source/dest MACs whose last byte is the radio port, plus an RTS (0xb4) variant; the legacy OpenHD 2.0 header used 0x08 0x02 with the first MAC byte as port. Distinguishes OpenHD from svpcom wfb-ng (57:42) in a sniffer.


- Ieee80211HeaderRaw data = {0x08,0x01, 0x00,0x00, ff:ff:ff:ff:ff:ff, 13:22:33:44:55:66, 13:22:33:44:55:66, seq}; 'the last byte of the mac address is recycled as a port number' (SRC_MAC_LASTBYTE=15, DST_MAC_LASTBYTE=21).
- u8aIeeeHeader_rts = {0xb4,0x01,0x00,0x00, 0xff...} RTS-type control frames with payload also supported.
- OldWifibroadcastIeee8021Header (OpenHD 2.0): 0x08,0x02 data frames, first MAC byte overwritten with encoded port.
- Radiotap TX helper supports IEEE80211_RADIOTAP_F_TX_RTS flag, MCS/HT and VHT injection.

*E200:* Provides the second MAC fingerprint (13:22:33:44:55:xx) for a Wi-Fi-NIC attribution stage alongside wfb-ng's 57:42.

### WFB-NG Data Transport Standard [Draft] (Jun 20, 2026)
`4/5` · English · standard · 2026 · verified  
<https://github.com/svpcom/wfb-ng/blob/master/doc/wfb-ng-std-draft.md>


RFC-style specification of the wfb-ng wire format: MAC addressing (W,B + link id + radio port), packet types (data=1, session=2), FEC (Reed-Solomon Vandermonde), encryption, stream ranges, and claimed rates (up to 8 Mbps at MCS1). The definitive reference for building a passive wfb-ng classifier.


- 'The MAC address therefore has the format 0x57, 0x42, 0xaa, 0xbb, 0xcc, 0xdd ... first two bytes are the protocol header (W, B), next three bytes are the link id, last byte is the stream (radio port)'; 0x57 marks multicast + locally administered.
- 'rates up to 8 Mbps (MCS 1 modulation) over distances of tens of kilometers' with RTL8812AU/EU adapters.
- Packet types: data (packet_type=1, nonce=(block_idx<<8)+fragment_idx) and session (packet_type=2); FEC type WFB_FEC_VDM_RS 0x1.
- Encryption: aead_chacha20poly1305 via libsodium; session packets carry the session key encrypted.

*E200:* Defines the header bytes an E200-side or NIC-side classifier should match; confirms payload is undecodable passively.

### bastibl/gr-ieee802-11 - IEEE 802.11 a/g/p OFDM transceiver for GNU Radio (5/10/20 MHz)
`4/5` · English · github · 2026 · verified  
<https://github.com/bastibl/gr-ieee802-11>


Host-side OFDM Wi-Fi receiver in GNU Radio whose wifi_rx.grc example takes a UHD source at 5/10/20 MHz and feeds decoded MAC frames to gr-foo's Wireshark connector (/tmp/wifi.pcap). With antsdr_uhd providing a UHD driver for the E200, this is the IQ-streaming alternative to openwifi for capturing RID beacons, at the cost of ~20 MSPS over Ethernet and host CPU. Cloned and read.


- README: 'IEEE 802.11 a/g/p transceiver'; branches maint-3.7 ... maint-3.10 track GNU Radio versions; tested with N210/B210 and off-the-shelf Wi-Fi cards.
- examples/wifi_rx.grc samp_rate options '[5e6, 10e6, 20e6]', default 10e6.
- README: cannot ACK in time ('architectural limitation of USRP + GNU Radio'), needs volk_profile 'to deal with the high rate of incoming samples', shared-memory and real-time priority tuning.
- No mention of 802.11n HT/MCS decoding anywhere in the README.
- Supports 802.11a/g/p at standard 5/10/20 MHz channelizations; maint branches track GNU Radio versions
- Wireshark connector via gr-foo for frame inspection
- wifi_rx.grc uses uhd_usrp_source with samp_rate chooser options [5e6, 10e6, 20e6], default 10e6; standard 20 MHz Wi-Fi beacons need 20e6
- Decoded frames go through ieee802_11_decode_mac -> foo_wireshark_connector -> file sink '/tmp/wifi.pcap'
- _(1 more facts in the JSON index)_

*E200:* Usable on the E200 (UHD source at 20 MSPS) to decode legacy-rate injected frames (DroneBridge, some EZ-WifiBroadcast setups) and to detect preambles; HT-rate wfb-ng/OpenHD payloads need a monitor-mode NIC instead.

### hd-zero/hdzero-vtx - HDZero VTX firmware (8051 in DM5680 baseband, DM6300 RF)
`4/5` · English · github · 2026 · verified  
<https://github.com/hd-zero/hdzero-vtx>


Open firmware for HDZero VTXs. Shows the VTX is a Divimath DM5680 baseband with a built-in 8051 and a separate DM6300 RF chip programmed over registers (channel PLL words, power). The channel plan in common.h is Raceband R1-R8, E1, F1/F2/F4 and Low band L1-L8. No AD9361 reference anywhere in the code.


- README: firmware 'runs on a built-in 8051 MCU of DM5680 which is the Baseband chip of VTX'; supports VTX Whoop, Whoop Lite, Race V1/V2, Freestyle.
- src/common.h: FREQ_R1..R8 = 5658,5695,5732,5769,5806,5843,5880,5917; FREQ_E1 5705; FREQ_F1 5740; FREQ_F2 5760; FREQ_F4 5800; FREQ_L1..L8 = 5362,5399,5436,5473,5510,5547,5584,5621 MHz.
- src/dm6300.c: DM6300_SetChannel writes PLL words (init6300_fnum[ch]) and per-channel tables; DM6300_SetPower; single-tone RF test mode exists.
- Modulation/OFDM parameters and occupied bandwidth are not present in the open code (baseband PHY is closed inside DM5680).

*E200:* HDZero is detect-only for the E200: use the channel plan above for energy detection; no open PHY to decode.

### luyii-code-1/dji-ocusync-droneid-research - reproducible O2/O4 DroneID PHY + packet analysis (Mini 5 Pro, Aug 2026)
`4/5` · English · github · 2026 · verified  
<https://github.com/luyii-code-1/dji-ocusync-droneid-research>


Recent (verified 2026-08-27) research repo with HackRF-based scanner, O2 PHY/FEC decoder and O4 packet tool. Reports O4 main-link 99% bandwidth ~8.92 MHz at 2403-2412 MHz, 5 ms periodicity with activity windows, 1024-FFT/15 kHz/600-carrier numerology, and O4 use of SM2 public-key and AES-128-CTR for key/telemetry packets. States that 5 ms periodicity alone cannot separate video, C2, RID and DroneID.


- OFDM: 'FFT 1024', 'subcarrier space 15 kHz', 'active carriers 600 (DC excluded)', normal CP 72 (long CP 80) samples; O2 frame ~643.2 us, 9 symbols.
- O4: 5 ms periodicity; 0-3.27 ms strong activity, 3.27-4.47 ms gap, 4.47-5.00 ms activity; 99% bandwidth 8.921-8.926 MHz spanning ~2403.071-2411.992 MHz.
- Experimental scan centers 2399.5/2414.5/2429.5/2444.5/2459.5 MHz (15 MHz raster) - 'experimental scan centers rather than universal official frequencies'.
- HackRF int8 IQ at 20 MS/s resampled x96/125 to 15.36 MS/s; tools: o4_packet_tool.py, o2_droneid_decode.py, droneid_hackrf_scanner.py, TurboFEC adapter.
- O4: SM2 for 'AA' key-material packets, AES-128-CTR for '87' telemetry packets; only DJI Mini 5 Pro validated; O2 Mini 2 shows plaintext DroneID after power-on.
- O2 PHY: 15.36 MS/s, 1024-point FFT, 15 kHz subcarrier spacing, ~600 active carriers, nine symbols with Zadoff-Chu roots 600 and 147, frame ~643 us.
- Scan centres tested on a '15 MHz raster': 2399.5, 2414.5, 2429.5, 2444.5, 2459.5 MHz ('experimental scan centers rather than universal official frequencies').
- O4: AA packets carry SM2 ciphertext 'C1 (64 bytes) + C3 (32 bytes) + C2 (16 bytes)'; 87 packets decrypted with 'AES-128-CTR(key=note, IV=nonce8 \|\| 0x00x8)'; private key not public.
- _(1 more facts in the JSON index)_

*E200:* Shows a 15.36 MS/s processing rate (E200-native AD9361 rate) and a 15 MHz scan raster that an E200 scanner can adopt for DJI O2/O4 detection.

### sheaivey/rx5808-pro-diversity - DIY 5.8 GHz FPV diversity receiver (authoritative RX5808 channel table)
`4/5` · English · github · n/a · verified  
<https://github.com/sheaivey/rx5808-pro-diversity>


Widely forked Arduino RX5808 receiver project whose src/rx5808-pro-diversity/channels.cpp carries the canonical 40-channel A/B/E/F/R table plus the optional L (5.3 GHz) band and the RTC6715 register formula. Useful as a citation source for channel tables and as the reference the FPV community's scanners use.


- channelFreqTable: A 5865,5845,5825,5805,5785,5765,5745,5725; B 5733,5752,5771,5790,5809,5828,5847,5866; E 5705,5685,5665,5645,5885,5905,5925,5945; F/Airwave 5740,5760,5780,5800,5820,5840,5860,5880; R/Immersion Raceband 5658,5695,5732,5769,5806,5843,5880,5917.
- USE_LBAND adds D/5.3 band: 5362,5399,5436,5473,5510,5547,5584,5621 MHz (37 MHz spacing).
- RX5808 register value = ((f-479)/2) split into N (/32) and A (%32) fields, i.e. 2 MHz LO steps with a 479 MHz IF offset.

*E200:* Use as the channel-table source of truth for the E200 sweep plan; the IF/LO formula shows why RX5808-type scanners only give RSSI while the E200 can demodulate.

### Bit101-git/passive_drone_detection-PDD - ESP32 + RX5808 + NRF24L01 passive FPV/FHSS detector
`3/5` · English · github · 2026 · verified  
<https://github.com/Bit101-git/passive_drone_detection-PDD>


Low-cost detector that sweeps 72 analog-FPV frequencies over 5.3-5.9 GHz across nine bands (A,B,E,F,R,U,O,L,H) using RX5808 RSSI with automatic noise-floor calibration (250 samples) and dynamic thresholds, and watches 2.4 GHz FHSS energy with an NRF24L01 RPD. Illustrates the RSSI-only baseline the E200 can outperform.


- Bands A, B, E, F, R, U, O, L, H x 8 channels = 72 frequencies, ~5.3-5.9 GHz.
- 5.8 GHz detection: RSSI mean/std with dynamic thresholds from 250-sample startup calibration.
- 2.4 GHz: NRF24L01 RPD over channels 0-83 (~2.400-2.483 GHz) to flag FHSS patterns; 'FHSS detected != ELRS confirmed'.
- MIT license.

*E200:* Its band list (adds U, O, H bands beyond A/B/E/F/R/L) and calibration scheme are a template for the E200 sweep; the E200 adds modulation confirmation.

### DroneBridge/DroneBridge - bidirectional raw-Wi-Fi link (RTS/DATA/BEACON raw frames, ESP32 variant)
`3/5` · English · github · n/a · verified  
<https://github.com/DroneBridge/DroneBridge>


Older wifibroadcast-derived system. common/db_raw_send_receive.c shows its raw frames: radiotap with fixed data-rate field (0x18 placeholder), frame control 0xb4 (RTS), 0x08 (DATA) or 0x80 (beacon), a 10-byte DroneBridge v2 header with comm_id. ESP32 build is telemetry-only Wi-Fi AP. Gives a third raw-injection fingerprint family.


- radiotap_header_pre: version 0, length 0x0d, present bitmap 0x04,0x80 (rate + TX flags), rate byte 0x18 'will be overwritten' (legacy rate injection).
- frame_control_pre_rts {0xb4,0x00,0x00,0x00}, frame_control_pre_data {0x08,0x00,0x00,0x00}, beacon {0x80,...} (beacon RX not implemented); DB_RAW_V2_HEADER_LENGTH 10 with comm_id byte.
- README: '500 m - 2 km with standard hardware', '110ms glass to glass latency', MAVLink/iNAV telemetry, Raspberry Pi and ESP32 targets.

*E200:* Legacy-rate (non-HT) injection means DroneBridge frames are within reach of gr-ieee802-11-style OFDM decoding on the E200 at 20 MHz, unlike HT/MCS wfb-ng frames.

### Kismet dot11_ie_221_dji_droneid.h - DJI DroneID over Wi-Fi beacon vendor IE (OUI 26:37:12)
`3/5` · English · github · 2026 · verified  
<https://raw.githubusercontent.com/kismetwireless/kismet/master/dot11_parsers/dot11_ie_221_dji_droneid.h>


Parser for DJI's Wi-Fi-carried DroneID: vendor-specific IE 221 under OUI 26:37:12 with subcommand 0x10 (flight telemetry/location) and 0x11 (flight purpose). Shows that DJI Wi-Fi-mode drones broadcast decodable identity/telemetry in beacons, independent of the OcuSync OFDM DroneID.


- vendor_oui() = 0x263712; 'packets with a subcommand of 0x10 include flight telemetry and location', 0x11 = flight purpose.
- Classes dji_subcommand_flight_reg / dji_subcommand_flight_purpose parse serial, position etc. from the IE.

*E200:* Decodable with any monitor-mode NIC; complements the OcuSync-DroneID SDR path for DJI attribution.

### OpenIPC wiki - FPV (wfb-ng on IP-camera SoCs)
`3/5` · English · doc · 2026 · verified  
<https://github.com/OpenIPC/wiki/blob/master/en/fpv.md>


OpenIPC's FPV page (Russian original moved to the English branch). Recommends 5 GHz with RTL8812AU (AR9271 for 2.4 GHz only), channels 60 and above, wfb-ng with gs.key encryption, H.264/H.265 video. Confirms OpenIPC air units are wfb-ng emitters and therefore share the 57:42 fingerprint.


- Supported chips: RTL8812AU (5 GHz recommended) and AR9271 (2.4 GHz only).
- '2.4GHz is completely saturated'; for RTL8812AU 'channels 60 and above are recommended'.
- Uses WFB-ng with encryption keys (gs.key); codecs H.264 and H.265.
- ru/fpv.md now only says the material moved to the international (en) branch.

*E200:* OpenIPC links are wfb-ng links: same detection strategy; expect them on 5.3-5.8 GHz channels >= 60.

### SDRangel ATV demodulator plugin - FM/AM analog TV demod (PAL/NTSC/custom)
`3/5` · English · doc · 2026 · verified  
<https://github.com/f4exb/sdrangel/blob/master/plugins/channelrx/demodatv/readme.md>


SDRangel's generic ATV demodulator supports FM (FM1/FM2/FM3), AM, USB/LSB, standards PAL625/PAL525/819L/ShortI/ShortNI/HSkip, adjustable FM deviation, sync levels, and needs >= 4 MS/s. Because SDRangel has PlutoSDR/UHD input plugins, it is the quickest GUI path to view analog FPV from an E200 running Pluto-compatible IIO firmware.


- Demod modes FM1/FM2/FM3 (FM3 most accurate for deviation), AM, USB, LSB (experimental, poor above 1 MS/s).
- 'A standard image quality for broadcast standard modes requires a sample rate of at least 4 MS/s'.
- Standards PAL625, PAL525, 819L, ShortI, ShortNI, HSkip; 32-819 lines; 1-30 fps; interleaved/non-interleaved; H/V sync toggles.
- No 5.8 GHz FPV-specific guidance in the doc.

*E200:* Works with E200 via SDRangel's PlutoSDR (ip:192.168.1.10) or UHD input at 10-20 MS/s for quick analog FPV viewing/recording.

### ficusdeltoidearobertbarany663/DroneRX - ESP32-S3 passive Wi-Fi drone identifier (OUI signatures)
`3/5` · English · github · 2026 · verified  
<https://github.com/ficusdeltoidearobertbarany663/DroneRX>


M5Stack CoreS3 sniffer that identifies drones from Wi-Fi beacons by protocol OUIs: ASTM F3411 ODID (FA:0B:BC), DJI DroneID (26:37:12), Parrot (90:3A:E6) and an 'FR' protocol (6A:5C:35), scanning channels 1-14. Useful as a compact OUI table for the Wi-Fi attribution stage.


- OUIs: FR 6A:5C:35, ASTM F3411 ODID FA:0B:BC, DJI DroneID 26:37:12, Parrot 90:3A:E6.
- Passive promiscuous scanning across Wi-Fi channels 1-14; outputs web map, BLE UART, WebSocket; no license file.

*E200:* OUI list feeds the NIC-side classifier; also transmits beacons, so ignore that part for a passive toolkit.

### hd-zero/hdzero-docs - HDZero documentation incl. Chinese (docs/zh) and Russian (docs/ru) pages
`3/5` · Chinese · doc · 2026 · verified  
<https://github.com/hd-zero/hdzero-docs>


Official HDZero docs repo with zh and ru translations. The Chinese box-operation page carries the Low-band table (L1-L8 中心频率) and the rule that only the Nano 90 540p60 mode uses 'HDZero BW = Narrow', all other modes 'Wide'. Also states HDZero 540p60 'reduces HDZero video bandwidth' for range. Serves as the Chinese/Russian-language evidence obtainable without web search.


- docs/zh/box-operation.md: '要启用低频段，请将 Source -> HDZero Band 设置为Lowband' with table L1..L8 = 5362,5399,5436,5473,5510,5547,5584,5621 MHz.
- docs/goggles-operation.md: 'Only Nano 90 camera supports 540p60 mode. When it is set to 540p60, the goggle needs to set Source > HDZero BW to Narrow. All other modes need to set Source > HDZero BW to Wide.'
- docs/zh/camera-nano90.md: 540p60 '通过降低 HDZero 视频带宽，提高了信号穿透力和距离' (lower video bandwidth for penetration/range).
- docs/zh/freestyle-v2.md: Freestyle V2 VTX outputs up to 1 W on R1, power falls with frequency; factory limited to 200 mW.
- docs/ru/box-operation.md carries the same Narrow/Wide note in Russian context.

*E200:* Gives the HDZero channel plan and the existence of a narrow mode for the E200 classifier; no numeric bandwidth.

### hd-zero/hdzero-goggle - HDZero goggle firmware (DM5680 + DM6302 receiver, Wide/Narrow BW modes)
`3/5` · English · github · 2026 · verified  
<https://github.com/hd-zero/hdzero-goggle>


Goggle-side firmware confirms the HDZero receiver is a DM5680 baseband plus DM6302 RF chip with two RX paths, exposes an 'HDZero BW' Wide/Narrow setting that reprograms both chips, and carries the standard analog band table (used for ELRS VTX-admin). Provides RSSI/link-quality fields that hint at what an SDR detector should reproduce.


- src/driver/dm5680.h includes dm6302.h; rx_status_t has rx_rssi[2], rx_DLQ (0-8 link quality), rx_Stat (video OK, 50/60 Hz).
- hardware-goggle2.c: changing hdz_bw calls DM5680_SetBR(bw) and DM6302_init(0, bw) -> two on-air bandwidth modes (Wide/Narrow, UI strings in page_source.c).
- src/core/elrs.c band table: E, F, R and L rows identical to the rx5808 table (L = 5362..5621).
- dm6302.c comment '02_RX1_PLL_11316(5658MHz)' shows the RX PLL word for R1.

*E200:* Confirms two HDZero bandwidth modes must be modelled in an E200 classifier; exact widths are not in the code (gap).

### BatchDrake/SigDigger - SoapySDR analyzer with real-time analog video decoding
`2/5` · English · github · 2026 · verified  
<https://github.com/BatchDrake/SigDigger>


SigDigger advertises real-time analog video decoding and SoapySDR device support; an rtl-sdr.com/DragonOS write-up (snippet only) shows it demodulating 5 GHz NTSC drone video via the symbol-stream viewer with a HackRF/BladeRF. Useful as a manual verification tool rather than a pipeline component.


- README: can 'decode analog video' in real time; SoapySDR device support (Pluto/ANTSDR via SoapyPlutoSDR not explicitly listed).
- Search snippet (rtl-sdr.com): 'SigDigger ... can be used to display NTSC Analog Video through its Symbol Stream viewer' (DragonOS demo with BladeRF/HackRF).

*E200:* Manual sanity-check viewer for E200 IQ via SoapyPlutoSDR/SoapyUHD.

### Matthias84/awesome-flying-fpv - curated list of open FPV/video-link software and hardware
`2/5` · English · github · 2026 · verified  
<https://github.com/Matthias84/awesome-flying-fpv>


Curated index that groups the open video-link ecosystem: OpenHD, RubyFPV, wfb-ng, OpenIPC sandbox-fpv, DroneBridge, EZ-WifiBroadcast, and analog RX projects FENIX-rx5808-pro-diversity and rpi-rx5808-stream. Good starting map, no RF parameters.


- Digital links listed: OpenHD, RubyFPV (rubyfpv.com), Wifibroadcast NG (svpcom), wfb-ng on OpenIPC (OpenIPC/sandbox-fpv, '120fps or 4k video'), DroneBridge, EZ WifiBroadcast ('oldest and first wifi based VTX setup').
- Analog RX: JyeSmith/FENIX-rx5808-pro-diversity (open hardware diversity module), xythobuz/rpi-rx5808-stream (RPi RX5808 streaming server).

*E200:* Discovery map only.

### RubyFPV/RubyFPV - open source digital FPV system (multi-band redundant raw-Wi-Fi links)
`2/5` · English · github · 2026 · verified  
<https://github.com/RubyFPV/RubyFPV>


Third major open digital FPV stack (299 stars). README claims multiple redundant radio links in 433/868/915 MHz, 2.3/2.4/2.5 and 5.8 GHz and support for Raspberry Pi, Radxa and OpenIPC hardware; encryption 'temporarily disabled'. On-air header not extracted (code not read) - a candidate for a deep read.


- 'multiple redundant radio links in different bands (433Mhz, 868/915Mhz, 2.3, 2.4, 2.5 and 5.8Ghz)'.
- Hardware: Raspberry, Radxa, OpenIPC.
- Encryption noted as 'temporarily disabled' in README.

*E200:* Another raw-802.11 emitter family to fingerprint; unencrypted state would make payload decodable in principle if the frame format were implemented.

### arall/sigint - distributed multi-protocol SDR detection with CoT/ATAK output
`2/5` · English · github · 2026 · verified  
<https://github.com/arall/sigint>


RTL-SDR/HackRF sensor network doing energy detection of short bursts, ADS-B/AIS/BLE/Remote ID/PMR/cellular decoding, SQLite storage and CoT streaming to ATAK with post-hoc triangulation. Not FPV-specific but an example architecture for feeding SDR drone detections into a network like AERIX.


- Supports RTL-SDR and HackRF; 'energy detection' for autonomous short-burst scanning; Meshtastic mesh between nodes.
- Detections stored in SQLite and 'stream as CoT events to ATAK'; Remote ID and drone detection listed among protocols.
- 'Detects radio emissions from distributed receivers using RTL-SDR and HackRF'; 'coordinates remote sensor nodes over a Meshtastic mesh'; detections 'stream as CoT events to ATAK for map overlay'.
- Signal classes: 'Short-burst signals (keyfobs, TPMS, pagers)' and 'longer transmissions (PMR voice, cellular uplinks)'.

*E200:* Architecture reference for the future_sdr receiver class (event schema, sensor coordination).

### hanyazou/TelloPy - Ryze/DJI Tello Wi-Fi control + video protocol (192.168.10.1:8889, video UDP 6038)
`2/5` · English · github · n/a · verified  
<https://github.com/hanyazou/TelloPy>


Python library whose internals document the Tello Wi-Fi protocol: open 2.4 GHz AP, UDP command socket to 192.168.10.1:8889, H.264 video pushed to UDP port 6038, plus video-rate/mode commands. Demonstrates a fully decodable consumer Wi-Fi drone video link.


- tello.py: tello_addr = ('192.168.10.1', 8889); video receive socket bound to UDP port 6038 with 512 kB receive buffer.
- protocol.py: VIDEO_ENCODER_RATE_CMD 0x0020, VIDEO_START_CMD 0x0025, VIDEO_MODE_CMD 0x0031, VIDEO_RECORD_CMD 0x0032.
- Kismet matches Tello SSID ^TELLO.* with OUI 60:60:1F.

*E200:* Tello video is decodable by joining/sniffing the open AP with a NIC; on the E200 it is just 20 MHz 802.11n at 2.4 GHz (detect/classify by SSID via NIC).

### rodizio1/EZ-WifiBroadcast - first-generation wifibroadcast image (2.3/2.4/2.5 and 5.2-5.8 GHz)
`2/5` · English · github · n/a · verified  
<https://github.com/rodizio1/EZ-WifiBroadcast>


Historic but still-flown wifibroadcast distribution. README states band support 2.3/2.4/2.5 GHz and 5.2-5.8 GHz, 1080p30 at up to 12 Mbit, ~125 ms latency, ranges to 30 km. Evidence that Wi-Fi-based FPV appears in the 2.3-2.5 GHz region outside ISM.


- 'Support for 2.3/2.4/2.5Ghz bands as well as 5.2Ghz to 5.8Ghz bands'.
- 'Up to 1920x1080p 30fps ... up to 12Mbit video bitrate'; 'Typical glass-to-glass latency of ~125ms'.
- 'Ranges of 300m to 3km can be easily achieved ... 30km was achieved'.

*E200:* Add 2.3-2.5 GHz to the E200 Wi-Fi-FPV sweep list.

### rtl-sdr.com - Decoding 5GHz NTSC Video from Drones with a HackRF, DragonOS and SigDigger
`2/5` · English · blog · n/a · snippet  
<https://www.rtl-sdr.com/decoding-5ghz-ntsc-video-from-drones-with-a-hackrf-dragonos-and-sigdigger>


Blog/video showing analog 5.8 GHz drone video demodulated in SigDigger and SDRangel on DragonOS with HackRF/BladeRF. Only the search snippet was available (domain blocked), but it documents that generic SDR ATV tools work on FPV signals.


- Snippet: SigDigger 'can be used to display NTSC Analog Video through its Symbol Stream viewer'.
- Companion YouTube: 'DragonOS Focal demodulating 5GHz analog drone video (SigDigger, SDRangel, BladeRF)'.

*E200:* Same workflow applies to E200 via SDRangel/SigDigger device plugins.


## Direction finding, TDOA and passive radar

### 30hours/blah2 - A real-time passive radar (486 stars)
`5/5` · English · github · 2025 · verified  
<https://github.com/30hours/blah2>


C++ real-time passive radar with reference + surveillance channel capture from RSPduo, USRP (B210), 2x HackRF, 2x RTL-SDR or KrakenSDR, producing delay-Doppler maps to a web front-end and JSON. Cloned: the USRP backend streams channels {0,1} with subdev 'A:A A:B' - the exact shape of a B210-compatible E200.


- README hardware list: 'SDRplay RSPDuo', 'USRP (only tested on the B210)', '2x HackRF with clock synchronisation and hardware trigger', '2x RTL-SDR with clock synchronisation', 'KrakenSDR with 2x channels only'.
- src/capture/usrp: set_rx_subdev_spec(subdev), set_rx_rate on all channels, per-channel gain, 'uhd::stream_args_t streamArgs("fc32", "sc16"); streamArgs.channels = {0, 1};'.
- config/config-usrp.yml: fs 2000000, fc 204640000, type 'Usrp', subdev 'A:A A:B', antenna ['RX2','RX2'], gain [20,20].
- Known issue: 'Currently have an issue where the USRP B210 is timing out after 5-10 mins and crashes the code'.
- '2 channel processing for a reference and surveillance signal'; outputs 'delay-Doppler maps to a web front-end' and JSON; tracker listed as future work; no drone-specific results.

*E200:* Most direct passive-radar path for E200: point the UHD backend at addr=192.168.1.10,product=E200 with subdev A:A A:B.

### ALPssdz/RF-Vision-UAV-Tracker - Multi-modal UAV monitoring with a ZYNQ-7020 + AD9364 RF node
`5/5` · English · github · 2025 · verified  
<https://github.com/ALPssdz/RF-Vision-UAV-Tracker>


Multi-node system whose RF sensing node is a Zynq-7020 + AD9364 board (56 MHz tuning bandwidth, libiio/pyadi-iio) sending IQ over TCP to an Orange Pi 5 that runs (1) a kurtosis-weighted RSSI pre-scan, (2) STFT spectrogram + YOLOv8n on the RK3588 NPU, (3) a cyclic-autocorrelation (CAF-FFT) discriminator that separates OcuSync from Wi-Fi by OFDM subcarrier spacing. Architecturally the closest public analogue to an E200-over-Ethernet deployment.


- 'ZYNQ-7020 FPGA board paired with an AD9364 transceiver', 40 MSps IQ, 56 MHz tuning bandwidth, GbE to an Orange Pi 5.
- OcuSync fingerprints: cyclic frequencies '10.5-14.5 kHz (OcuSync 15 kHz mode) and 22-30 kHz (30 kHz mode)'; sectors 5745/5785/5825 MHz; burst kurtosis 6-8 vs ~3 noise.
- 'No Direction-of-Arrival (DoA) or spatial localization implemented'; early prototype, mAP 0.995 on training data but live confidence 0.2-0.7.
- AD9364 at 40 MSps, 2.62M samples (~65 ms) per burst; stage-1 buffer 524,288 samples (13.1 ms), 3-frame median; kurtosis weighting beta=0.40 scores OcuSync bursts (kurtosis ~6-8) 40-80% higher than thermal noise (kurtosis 3)
- Stage 2: YOLOv8n RKNN FP16 ~30 ms/frame, 640x640 viridis waterfall, trained on RFUAV IQ (131 recordings, 5 DJI models, resampled to 40 MSps) + synthetic AWGN negatives; training mAP@0.5 0.995 but live confidence only ~0.2-0.7 (domain shift)
- Stage 3 cyclic frequencies at 40 MSps: OcuSync 2.0 (15 kHz spacing) alpha 10.5-14.5 kHz; OcuSync 3.0/4.0 (30 kHz) 22-30 kHz; Wi-Fi (312.5 kHz) 250 kHz, orthogonal; Wi-Fi leakage into the OcuSync test ~0.028% of P_WiFi
- Field validation with PlutoSDR mock TX at 5785/5825 MHz: NCC 2.02-7.85% above thresholds 1.8-3.25%; SMPS burst (alpha 14.4 kHz) and wideband noise rejected via CFS/PSR ratios; consistent alpha = 27.99 kHz detected
- Training mAP@0.5 0.995 but live SDR confidence only ~0.2-0.7 ('domain shift expected'); YOLO conf threshold lowered to 0.30.
- _(8 more facts in the JSON index)_

*E200:* Feature ideas (cyclostationary OcuSync detection) portable to E200; hardware is near-identical.

### MicroPhase antsdr_doc_en - E200 Hardware Manual, RF parameters, Clock Calibration and UHD pages
`5/5` · English · doc · 2025 · verified  
<https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md>


Vendor documentation repository (English + Chinese source_cn tree) for the ANTSDR E200/E310/E316/U-series. States the E200's interfaces, the 10M/PPS clock-synchronisation capability, the clock-calibration procedure through the ad5660mp IIO device, and shows a uhd_usrp_probe listing with external time/clock sources. This is the authoritative answer to whether the E200 exposes PPS/10 MHz inputs.


- E200 resource list: 'Xilinx Zynq 7020', 'Analog Devices AD9361/9363', '1 Gigabit Ethernet interface', '8-Pin 2.54mm pitch GPIO expansion port', '1 external PPS/10MHz reference entrance', '2 transmit channels and 2 receive channels, supporting half-duplex or full-duplex operation'.
- ANTSDR selection table (AntsdrE200_RF_parameters.md): RF channel E200 = 'SMA:1T1R IPEX:1T1R' (E310/E316 = '2T2R MIMO'); 'Transmission bandwidth to host 20MSPS' for E200; 'Clock synchronization 10M/PPS' for E200/E310/E316; API 'Libiio & UHD /C/C++ /PYTHON'.
- E200 clock-calibration page says the E310 method applies: log in via serial (root/analog), IIO device 'ad5660mp' with attributes in_voltage_dac_mode (0 automatic / 1 manual, default 1 with DAC value 23000), in_voltage_dac_ref_sel '0:10M 1:PPS 2:GPS', in_voltage_dac_locked (PLL lock status); the reference is connected with an SMA-to-MMCX cable to the '10/PPS' port.
- E200 UHD page probe output: 'Time sources: none, internal, external', 'Clock sources: internal, external', 'Sensors: ref_locked'; RX frontend 'Antennas: TX/RX, RX2'; note the shown firmware identified itself as 'B205MINI(COMPATIBLE)'.
- E316 UHD page: 'E316 supports simultaneous input of 10M and PPS, and E316 has an onboard GPSDO module' - such statements are absent for E200; U220/E316 list 'GPS sync input interface', E200 does not.
- Chinese mirror (source_cn) carries the same tables, e.g. 'RF channel \| SMA:1T1R IPEX:1T1R'.

*E200:* Direct: defines the E200's clock/PPS input, dual-channel connector situation (RX2 on IPEX) and host-throughput ceiling that constrain every DF/TDOA design.

### cherubimro/dronelocate - Passive RF localization of non-cooperative drones over Zenoh (TDOA)
`5/5` · English · github · 2026 · verified  
<https://github.com/cherubimro/dronelocate>


The only drone-specific open-source TDOA stack found. Distributed nodes (RTL-SDR, HackRF, or UHD B210-class with PPS-disciplined timestamps) publish detections and IQ over Zenoh; a supernode runs a Doppler-searching CAF, GCC-HT weighting, all-pairs GLS and an EKF. Research/demo grade; UHD path unverified on hardware. Cloned and read.


- uhd_source.py: 'UHD source for B210-class hardware (TinyB210, B205mini, Ettus B2xx)'; 'channels=[0] for single RX. channels=[0, 1] for the coherent pair'; if no gps_locked sensor: 'TDOA will need an external PPS on the PPS input, or reference-emitter calibration'; aligns device clock to UTC on a PPS edge (set_time_next_pps).
- README: CAF searches lag and Doppler jointly ('250-400 Hz differential Doppler observed at 2.437 GHz'); 'GCC weighting cuts timing error from 8.9 to 3.5 ns RMS'; all-pairs GLS; PDOP-minimised sensor selection; innovation-gated EKF with altitude prior.
- Emulated results (ten nodes): 'Horizontal error, median ~0.2 m', 'Vertical error, median ~2 m'; real-world limit 'surveyed node position error (3-5 m from a single GNSS fix, and it propagates one-to-one)'.
- Wire formats cf32 / ci8 / ci2 (12 KB per 10 ms, ~0.55 dB SNR loss); optional mTLS.
- Status: 'This is a research/demo codebase, not a finished product'; UHD support 'unverified against hardware'; no reference-emitter calibration loop; single-target tracking; authors recommend KrakenSDR for production and position TDOA as complementary to AoA.

*E200:* E200 under antsdr_uhd is a B210-class device with external PPS; with a GPSDO on the 10/PPS port each E200 could be a dronelocate node (needs hardware validation).

### KrakenSDR Wiki 04 - Antenna Array Setup (and 03 Background Theory)
`4/5` · English · doc · 2024 · verified  
<https://github.com/krakenrf/krakensdr_docs/wiki/04.-Antenna-Array-Setup>


Practical array-design rules from the KrakenSDR project: spacing as a fraction of wavelength, ULA vs UCA coverage and ambiguity, cable-length matching, and rough resolution figures. These are the numbers to apply to a two-element E200 interferometer.


- 'the spacing multiplier must be kept under 0.5 to avoid ambiguities'; 'keep the spacing multiplier above around 0.2 and closer to 0.5'; 'we typically set our arrays to s=0.33'; 'for 5-elements the accuracy starts to become unacceptable below around s=0.2'.
- ULA 'only valid for 180 degrees, and there is no way of knowing if the signal is coming from in front, or behind the array'.
- 'Up until about 900 MHz, all the coax cables connecting the antennas to KrakenSDR must be identical lengths to a tolerance within a centimeter.'
- Rough resolution: '5-element circular array spaced at 0.5λ, we might roughly expect a resolution of about 8 degrees'; '5-element linear array we could roughly expect about 3.4 degrees'.
- Background theory page: 'radio direction finding bearings will always have inaccuracies of several degrees'; 'Small arrays have less resolution, so they will absorb multipath corruption into the main lobe, skewing the result'; method named 'Correlative Interferometry'.

*E200:* Sets antenna spacing (lambda/2 = 6.2 cm at 2.4 GHz, 2.6 cm at 5.8 GHz), cable matching and expectation management for a 2-element E200 array.

### MarcinWachowiak/gr-aoa - GNU Radio MUSIC / root-MUSIC angle-of-arrival with USRP phase-sync blocks
`4/5` · English · github · 2023 · verified  
<https://github.com/MarcinWachowiak/gr-aoa>


Maintained successor of EttusResearch/gr-doa: GNU Radio OOT with MUSIC Linear Array and root-MUSIC blocks plus 'Calculate Phase Difference' and 'Shift Phase' blocks for multi-channel USRP phase synchronisation. Since the E200 appears as a USRP under antsdr_uhd, this is the GNU Radio route.


- 'GNU Radio package implementing MUSIC and root MUSIC angle of arrival algorithms'.
- Includes 'blocks necessary to provide phase synchronization of USRP devices' - 'Calculate Phase Difference' and 'Shift Phase'.
- 'an updated and improved version of https://github.com/EttusResearch/gr-doa'; examples directory with flowgraphs.

*E200:* Usable with the E200 through the antsdr_uhd UHD source (2 channels) in GNU Radio.

### ckoval7/df-aggregator - Networked DF software fusing bearings from multiple DoA receivers
`4/5` · English · github · 2025 · verified  
<https://github.com/ckoval7/df-aggregator>


Takes lines of bearing from several KrakenSDR/KerberosSDR stations, intersects them, clusters intersections with DBSCAN and outputs GeoJSON on a Cesium map. This is the multi-sensor AoA-to-position layer an E200 network would need.


- 'Networked DFing software that can handle multiple DOA receivers'; receivers connect via XML from KrakenSDR software.
- Intersections of LOBs are clustered with DBSCAN; 'A red ellipse represents the significant majority of the intersections in a particular cluster'; mean position shown as green dot; GeoJSON output.
- Filters LOBs by confidence and power thresholds; SSE live receiver updates; LOB history timeline replay.

*E200:* E200 DoA nodes emitting Kraken-style XML bearings could be fused here and forwarded to AERIX.

### krakenrf/heimdall_daq_fw - Coherent data acquisition chain for multichannel SDRs (KrakenSDR)
`4/5` · English · github · 2024 · verified  
<https://github.com/krakenrf/heimdall_daq_fw>


The DAQ layer of KrakenSDR: sample-level delay synchronisation, noise-source based amplitude/phase calibration and a documented 1024-byte IQ frame header. Cloned and read; the calibration maths in delay_sync.py is hardware-agnostic numpy and the frame format is what krakensdr_doa expects, so it is a template both for E200 channel calibration and for feeding E200 data into the Kraken DoA stack.


- delay_sync.py: 'It checks the sample level synchrony with calculating the cross correlation function of all the channels at two points. At zero and at non-zero offsets... The amplitude and phase offsets are determined from the eigendecomposition of the spatial-correlation matrix' (dominant eigenvector, normalised to std_ch_ind).
- delay_sync.py estimate_frac_delays: fractional sample delay from the slope of the phase-frequency difference curve fitted over 1024-sample blocks.
- delay_sync.py defaults: 'self.phase_diff_tolerance = 3 # deg, maximum allowable phase difference'; daq_chain_config.ini: en_noise_source_ctr = 1, corr_size = 65536, std_ch_ind = 0, amplitude_cal_mode = channel_power, cal_track_mode = 2, cal_frame_interval = 687, cal_frame_burst_size = 10, iq_adjust_source = explicit-time-delay.
- iq_header.py: header_size = 1024 bytes; fields include sync_word, frame_type (DATA/DUMMY/RAMP/CAL/TRIGW), active_ant_chs, rf_center_freq, adc_sampling_freq, sampling_freq, cpi_length, time_stamp, cpi_index, data_type, sample_bit_depth, delay_sync_flag, iq_sync_flag, sync_state, noise_source_state.
- README: 'Coherent data acquisition signal processing chain for multichannel SDRs'; tested on Raspberry Pi 4, x86 needs ~4 cores; Kraken wiki index: after boot 'the noise source will be activated, and each channel automatically correlated against the master channel (CH0 by default)'.

*E200:* Reusable algorithms for 2-channel phase/delay calibration; an E200-to-heimdall-frame bridge would let krakensdr_doa run unchanged on E200 IQ.

### krakenrf/krakensdr_doa - KrakenSDR direction-of-arrival DSP + web UI
`4/5` · English · github · 2025 · verified  
<https://github.com/krakenrf/krakensdr_doa>


The DoA application used with KrakenSDR. Cloned: it wraps pyArgus (Bartlett, Capon, MEM, MUSIC) plus its own MUSIC/ROOT-MUSIC and 'TNA', supports ULA/UCA/custom arrays, and ingests heimdall IQ frames either via shared memory or Ethernet. Output bearings are consumed by df-aggregator and TAK tools.


- kraken_sdr_signal_processor.py imports 'from pyargus import directionEstimation as de' and dispatches on DOA_algorithm in {'Bartlett','Capon','MEM','TNA','MUSIC','ROOT-MUSIC'} (own DOA_MUSIC and doa_root_music implementations).
- Web UI array options 'ULA', 'UCA', 'Custom'; ROOT-MUSIC is disabled for Custom arrays; spacing entered in metres and converted to wavelengths ('wavelength = 300 / daq_center_freq').
- README: 'These two modules [heimdall and DoA] can operate together either remotely through Ethernet connection or locally on the same host using shared-memory'; 'intended to demonstrate the DoA capabilities of the KrakenSDR and other RTL-SDR based coherent receiver systems which use the compatible data acquisition system - HeIMDALL DAQ Firmware'.

*E200:* Algorithms usable on E200 data after calibration; needs a heimdall-compatible frame feeder or direct pyArgus use.

### petotamas/pyArgus - Antenna array signal processing library in Python
`4/5` · English · github · 2024 · verified  
<https://github.com/petotamas/pyArgus>


Tamas Peto's DoA/beamforming library used inside krakensdr_doa. Arbitrary planar geometries, several DoA estimators and array utilities (forward-backward averaging, spatial smoothing) - a lightweight dependency for a 2-channel E200 DoA prototype.


- DoA algorithms: 'Bartlett (Fourier) method', 'Capon's method', 'Burg's Maximum Entropy Method (MEM)', 'Multiple Signal Classification (MUSIC)', MD-MUSIC.
- 'Arbitrary configured planar antenna systems' and 'Takes into account the pattern of the signal radiating elements'.
- Utilities: spatial correlation matrix estimation, forward-backward averaging, spatial smoothing, DoA plot highlighting ambiguous regions of ULAs; pip package 'pyargus'.

*E200:* Drop-in DoA estimators for E200 2x1 covariance matrices.

### pyapril/pyapril - Passive radar signal processing library for Python (Tamas Peto)
`4/5` · English · github · 2023 · verified  
<https://github.com/pyapril/pyapril>


Algorithm library covering clutter cancellation (Wiener-SMI, ECA family), beamforming, cross-correlation detection, CA-CFAR and target DoA, developed with KrakenSDR/KerberosSDR data. Suitable for offline experiments with E200 reference/surveillance recordings.


- Clutter cancellation: Wiener-SMI, ECA (standard, batched, sliding); beamspace methods MVDR, Max-SIR, principal eigenvalue.
- Detection: cross-correlation detector in time/frequency domains with Doppler windowing; hit processing CA-CFAR; target DoA estimation; metrics for clutter attenuation, noise floor, SINR.
- Input is 'reference and the surveillance signals for the detection stage'; credits BME Radarlab; GPLv3; passiveradar.eu.

*E200:* Python building blocks for a 2-channel E200 passive radar prototype before moving to blah2.

### 30hours/3lips - Target localisation for multi-static radar (blah2 nodes)
`3/5` · English · github · 2024 · verified  
<https://github.com/30hours/3lips>


Companion to blah2 that geolocates targets from several bistatic passive-radar nodes via ellipse/ellipsoid intersection or a closed-form spherical-intersection solution, exposed as a JSON API with Cesium visualisation.


- Ellipse Parametric: 'samples an ellipse (2D) at 0 altitude. Find intersections between 3 or more ellipses'; Ellipsoid Parametric 3D variant; Spherical Intersection 'a closed form solution which applies when a common receiver or transmitter are used'.
- 'Provides a JSON API for geolocation of targets given blah2 radar nodes'; parameters kept in a common processing loop rather than strict node time sync.

*E200:* Multi-E200 passive radar network could feed 3lips for drone position estimates.

### ADolbyB/sdr-beamforming - Phased-array beamforming code and resources across SDR platforms
`3/5` · English · github · 2024 · verified  
<https://github.com/ADolbyB/sdr-beamforming>


Survey-style repo comparing PlutoSDR, KrakenSDR, FMCOMMS5, USRP B210/N310 for beamforming/DoA/passive radar, with phase-calibration scripts and heavy citation of Jon Kraft's material. Useful for its hardware coherence matrix and cost figures.


- PlutoSDR (~$150) 'Requires external clock' for multi-unit coherence, using a '40 MHz reference clock from TI CDCLVC1310-EVM'; KrakenSDR (~$300), FMCOMMS5 (~$1,445), USRP B210 (~$2,165) listed as 'native phase coherence'.
- Includes 'Custom Python phase calibration scripts', 'Real-time phase offset correction', 'Digital phase shifting in baseband', 'Weighted sum beamforming', 'Adaptive null steering'; research focus lists passive radar and DoA.
- Cites Jon Kraft repos 'Pluto_Beamformer', 'PlutoSDR_Labs', 'PhasedArray'.

*E200:* Places a single E200 (2 coherent RX on one AD9361) in the 'native coherence' class at Pluto-like cost.

### DC9ST/tdoa-evaluation-rtlsdr - TDOA transmitter localisation with 3 RTL-SDRs synchronised by a reference transmitter
`3/5` · English · github · 2017 · verified  
<https://github.com/DC9ST/tdoa-evaluation-rtlsdr>


Stefan Scholl's MATLAB TDOA toolkit: receivers alternate between a known reference transmitter and the target frequency (librtlsdr-2freq) so no GPS/PPS is required; outputs hyperbolas and most-likely position on an HTML map. Demonstrates the reference-emitter synchronisation alternative to PPS.


- 'First frequency is the reference transmitter, second frequency is the measurement frequency'; three receivers, 2 Msps recordings via 'librtlsdr-2freq (modified librtlsdr for 2 frequency operation)'.
- Processing options: 'bandwidth filtering, correlation smoothing, correlation type switching, signal interpolation'; produces 'a html/javascript file with a map showing the receivers, the hyperbolas and the most likely position of the transmitter'.
- References blog at panoradio-sdr.de and 'Presentation at the Software Defined Radio Academy, 2017'.

*E200:* Model for a no-GPSDO TDOA fallback: E200 nodes could hop between a DVB-T/FM reference and the drone band.

### EttusResearch/gr-doa - Direction of arrival (MUSIC, root-MUSIC) for USRP
`3/5` · English · github · 2024 · verified  
<https://github.com/EttusResearch/gr-doa>


Original Ettus DoA package with calibration blocks for linear arrays; now repositioned as a demo of USRP X440 phase synchronisation and flagged as mature/not actively developed. Useful for its calibration methodology and whitepaper folder.


- 'gr-doa is a demonstration on the phase synchronization capability of Ettus Research's USRP X440'.
- Implements MUSIC and Root-MUSIC for linear arrays, relative phase offset measurement and correction, and antenna element calibration.
- Requires 'UHD >= 4.8.0.0', 'gnuradio >= 3.11.0.0', armadillo >= 12.6.7; 'mature and not under active development'; docs folder contains a whitepaper/ directory.

*E200:* Methodology reference; version requirements clash with antsdr_uhd's UHD 4.1, so gr-aoa is the practical variant.

### F-L-X-S/doa4rfc - Realtime Direction-of-Arrival estimation for RF communication protocols
`3/5` · English · github · 2024 · verified  
<https://github.com/F-L-X-S/doa4rfc>


Protocol-aware DoA (WiFi 802.11n, GPS L1, DVB-S2, OFDM) using MUSIC on MIMO-cabled USRP N210 pairs with half-wavelength spacing and exchangeable frame synchronisers. Illustrates DoA keyed on detected protocol frames - the pattern needed for bursty drone links.


- Hardware: 'two USRP N210 with the WBXv3 daughterboard' connected via MIMO cable; 'half wavelength' spacing.
- Protocols: 'IEEE 802.11n WiFi', 'GPS L1 C/A', 'DVB-S2', generic OFDM/single-carrier; 'The synchronizer type is exchangeable via template traits'.
- MUSIC in Python with phase offset correction; measurements folder but no quantitative accuracy in README.

*E200:* Design pattern: detect DroneID/Wi-Fi Remote ID frames first, then estimate DoA on the frame samples from RX1/RX2.

### LahiruJayasinghe/DeepDOA - RF-based direction finding of UAVs using a sparse denoising autoencoder DNN
`3/5` · English · github · 2017 · verified  
<https://github.com/LahiruJayasinghe/DeepDOA>


Code and partial dataset for arXiv:1712.01154 (Abeywickrama, Jayasinghe, Fu, Yuen): a DNN that infers UAV direction in 45-degree sectors from a single-channel receiver without phase synchronisation or calibration. An alternative when only one SMA RX is available.


- Paper: 'RF-Based Direction Finding of UAVs Using DNN', arXiv:1712.01154 (2017).
- 'a Sparse Denoising Autoencoder (SDAE)-based Deep Neural Network (DNN) for direction finding (DF)' without 'phase synchronization mechanism, an antenna calibration mechanism, and the analytical model of the antenna radiation pattern'; 'can be implemented using a single-channel RF receiver'.
- Partial training/testing datasets organised by 45-degree sectors; MIT license; no accuracy figures in README.

*E200:* Coarse sector DF with one channel plus a directional/switched antenna; complementary to interferometry.

### Max-Manning/passiveRadar - Python FM passive radar with clock-shared RTL-SDRs / KerberosSDR / B210
`3/5` · English · github · 2021 · verified  
<https://github.com/Max-Manning/passiveRadar>


Educational passive radar pipeline with example FM-illuminator dataset of aircraft, range-Doppler video output and experimental Kalman trackers. Lists cheap dual-channel hardware options including USRP B210.


- Cheapest option 'a pair of RTL-SDR dongles modified to share a clock'; also KerberosSDR, LimeSDR, BladeRF 2.0 Micro, USRP B210.
- Uses FM radio broadcasts; example dataset shows planes; ~20 min processing for the example.
- 'target tracking functionality is still under development, currently it suffers from a lot of false positives'; multitarget and simple Kalman trackers included.

*E200:* Reference implementation to reproduce with E200 RX1/RX2 as reference/surveillance.

### MicroPhase antsdr_doc_en source_cn - E200 中文参考手册 (Chinese reference manual)
`3/5` · Chinese · doc · 2025 · verified  
<https://github.com/MicroPhase/antsdr_doc_en/tree/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual>


Chinese-language originals of the E200 manual pages in the same repository, including RF parameter table, UHD probe output and the E310 clock-calibration walkthrough (10/PPS 端口, in_voltage_dac_ref_sel). Confirms the English translation and adds the vendor's Chinese wording.


- AntsdrE200_RF_parameters_cn.md: 'RF channel \| SMA:1T1R IPEX:1T1R' for E200, '2T2R MIMO' for E310/E316.
- AntsdrE200_UHD_cn.md shows 'Antennas: TX/RX, RX2' in the probe.
- Antsdr-Clock-calibration_cn.md: '将 SMA 转 MMCX 线缆的一端连接到 ANTSDR 的 10/PPS 端口，另一端连接到10M时钟上' and 'in_voltage_dac_ref_sel 0:10M 1:PPS 2:GPS'.
- U220 Chinese page: 'U220 ... 支持 GPSDO 精确同步与外部时钟输入，满足多通道协同或分布式部署需求' - GPSDO is a U220/E316 feature, not E200.

*E200:* Same as the English manual; useful when reading Chinese forum answers about the 10/PPS port.

### analogdevicesinc/libad9361-iio - AD9361 helper library incl. multi-chip sync and FMCOMMS5 phase sync
`3/5` · English · github · 2024 · verified  
<https://github.com/analogdevicesinc/libad9361-iio>


ADI's userspace library; ad9361_fmcomms5_phase_sync.c implements an iterative RF phase calibration loop (estimate phase difference, rotate via 'calibphase' attributes, repeat) and points to the ADI wiki on multi-chip sync. Useful as the vendor-sanctioned way to think about AD9361 phase alignment and its LO dependence.


- README: library for 'multi-chip synchronization on platforms like FMCOMMS5' and FIR filter design; files ad9361_multichip_sync.c and ad9361_fmcomms5_phase_sync.c.
- ad9361.h: '__api int ad9361_fmcomms5_phase_sync(struct iio_context *ctx, long long lo);' with links to wiki pages 'multi-chip-sync' and hardware-revision dependence of phase-sync performance.
- phase_sync() resets trx_phase_rotation to 0 on rx/tx master and slave, then calibrate_chain() iterates: estimate_phase_diff -> trx_phase_rotation(dev, phase) writing 'calibphase' on in_voltage0/1 until 'Remaining Phase error' is small; the source comments cite 'multi-chip-sync#rf_phase_difference'.

*E200:* Explains the calibphase IIO attribute available on the E200's ad9361-phy for applying a measured RX1/RX2 phase correction in hardware.

### einhar1/DDH2026-Kinetic-Ranger - Passive RF detection and time-to-impact estimation for AntSDR E200
`3/5` · English · github · 2026 · verified  
<https://github.com/einhar1/DDH2026-Kinetic-Ranger>


Hackathon project that captures IQ from an E200 through the Pluto/IIO-compatible interface and derives RSSI trend, Doppler closing-rate and time-to-intercept for an approaching transmitter. Single-channel only, but it is an existing E200 + IIO codebase with tests and replay.


- Requires 'a reachable Pluto/IIO-compatible AntSDR'; 'Live capture uses the receiver's first RX channel'.
- 'Live range is not absolute because transmitter power is unknown. The useful outputs are RSSI trend, closing-rate estimate, and time-to-impact estimate'; assumes constant velocity straight approach.
- Automated tests cover processing, alerting, API and recording/replay; browser-to-hardware path verified manually; 5 open issues.

*E200:* Directly targets the E200; shows Doppler/RSSI kinematics from one channel; could be extended to RX2.

### ChiefGokhlayeh/pluto-sdr-pr - Converting Pluto-SDR receivers into passive radar sensors (suspended)
`2/5` · English · github · 2022 · verified  
<https://github.com/ChiefGokhlayeh/pluto-sdr-pr>


Student project using two GPSDO-fed Pluto SDRs against an LTE-based 5G-broadcast illuminator; abandoned when the transmitter went off air. Shows that AD936x boards were chosen over RTL-SDR for bandwidth and that external GPS-DO was used for cross-device coherence.


- 'two coherent Pluto-SDR receivers fed by an external GPS-DO'; RTL-SDR rejected because 2.56 MHz stable bandwidth < 5 MHz LTE channel.
- Marked 'suspended'; 'I currently don't have any capacity to work on it'.

*E200:* Confirms that with one E200 the two AD9361 channels avoid the multi-device GPSDO coherence problem entirely.

### hcab14/TDoA - TDoA multilateration from GNSS-timestamped KiwiSDR recordings
`2/5` · English · github · 2023 · verified  
<https://github.com/hcab14/TDoA>


Octave toolkit that multilaterates HF/VLF emitters from KiwiSDR IQ files carrying GNSS timestamps. Demonstrates the 'timestamp at the sensor, correlate centrally' architecture that GPS-disciplined E200 nodes would replicate at UHF/microwave.


- Inputs are 'wav files with GNSS timestamps from KiwiSDRs' plus receiver positions in gnss_pos; Octave >= 4.2.2 with signal package; GPL-3.0.
- Includes proc_tdoa_DCF77.m reference-signal processing; focus on HF/VLF monitoring.

*E200:* Architecture analogy only; different band and hardware.

### pingbiqi/Anti-Drone-System - 无人机反制 (C-UAS) 检测/干扰 overview (Chinese)
`1/5` · Chinese · vendor · 2025 · verified  
<https://github.com/pingbiqi/Anti-Drone-System-C-UAS-Detection-Jamming-Defense>


Chinese-language GitHub page found under the anti-drone topic; it is promotional documentation for a commercial C-UAS vendor with no functioning code and no AD9361/ZYNQ direction-finding details. Included to document the (poor) yield of Chinese open-source DF material reachable without web search.


- '本项目提供专业的无人机反制（C-UAS）技术架构、射频干扰理论及部署方案' (provides C-UAS architecture, RF jamming theory and deployment schemes); '本项目仅提供技术理论与仿真参考' (theory and simulation reference only).
- No hardware specifics (no AD9361/ZYNQ/USRP), links to commercial products; SEO keyword section.

*E200:* None.


## Academic: detection methods

### Glüge et al. 2023 (NCTA/IJCCI): Robust Drone Detection and Classification from RF Signals using CNNs + Noisy Drone RF dataset
`5/5` · English · paper · 2023 · verified  
<https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification>


Paper (DOI 10.5220/0012176800003595, PDF included in the repo and read in full) comparing 1D IQ vs 2D spectrogram CNN inputs for detecting/classifying six RC/drone links plus a Bluetooth/Wi-Fi noise class across SNR -20..30 dB. Recorded in an anechoic chamber with a USRP B210 and LogPer antenna at 56 MHz then decimated to 14 MHz; dataset released on Kaggle. Key result: spectrograms roughly double balanced accuracy at -12 dB.


- Balanced accuracy at -12 dB: 0.842 (spectrogram VGG11) vs 0.413 (IQ VGG11); at 0 dB both ~0.98; at -18 dB 0.444 vs 0.225
- No significant difference between VGG11/13/16/19 within an input type (spectrogram overall acc 0.981-0.989, balanced 0.897-0.900)
- Classes: DJI Phantom 4 Pro/GL300F (2.44175 GHz, 1.7 MHz spacing, 2.18 ms bursts, 630 ms period), Futaba T7C, Futaba T14SG, Graupner mx-16, Taranis ACCST, Turnigy 9X, Noise (BT/Wi-Fi recorded in a busy university building + AWGN + USRP receiver noise)
- Vectors of 16384 samples (~1.2 ms at 14 MHz) selected by an energy threshold; SNR levels -20..30 dB in 2 dB steps; balanced accuracy needed because the noise class dominates and most errors are drone-vs-noise
- Authors: ZHAW, OST and armasuisse Science + Technology
- Files: class_stats.csv, SNR_stats.csv, dataset.pt; cite doi 10.5220/0012176800003595.

*E200:* 14 MSps at 2.4 GHz is trivially within E200 capability; the dataset can be used as-is to bootstrap a spectrogram CNN for the E200 and its noise class models urban 2.4 GHz interference.

### Open Drone ID core C library (ASTM F3411 / ASD-STAN prEN 4709-002) and receiver landscape
`5/5` · English · standard · 2022-2025 · verified  
<https://github.com/opendroneid/opendroneid-core-c>


Reference encoder/decoder for ASTM F3411 / ASD-STAN prEN 4709-002 messages, plus Wi-Fi Beacon and NAN frame builders, and (new) a separate libopendroneidcn library for China's GB 46750-2025 broadcast format. Its README carries the authoritative comparison table of what each rule (FAA, EU, Japan) mandates and which transports are mandatory. Cloned and read.


- Broadcast transports: Bluetooth 4 Legacy Advertising, Bluetooth 5 Long Range (+ Extended Advertising), Wi-Fi NAN and Wi-Fi Beacon; code compliant with the 2021/2022 standard updates
- iOS (up to 15) cannot receive BT5 Long Range, Wi-Fi NaN or Wi-Fi Beacon, only BT4 legacy
- Bluetooth sniffing recommended via TI boards running nccgroup/Sniffle; Linux scanner sxjack/unix_rid_capture; wireshark-dissector for both Wi-Fi and BT
- Protocol versions in header: 0 = ASTM F3411-19 (14 Feb 2020), 1 = ASD-STAN prEN 4709-002 P1 (31 Oct 2021), 2 = ASTM F3411-22a (25 May 2022)
- Comparison table: under ASD-STAN DRI, BT5 Long Range, Wi-Fi NaN 2.4/5 GHz and Wi-Fi Beacon 2.4/5 GHz are 'M5' (one of them mandatory) while BT4 Legacy Advertising is Optional; EU rule mandates operator registration ID, AGL/take-off height, operator dynamic position (take-off location allowed for add-ons)
- wifi.c: Wi-Fi Beacon vendor-specific IE uses ASD-STAN OUI FA:0B:BC with oui_type 0x0D; NAN uses Wi-Fi Alliance OUI 50:6F:9A oui_type 0x13 and cluster ID 50:6F:9A:01:00:FF; ODID_MESSAGE_SIZE 25 bytes, ODID_PACK_MAX_MESSAGES 9
- Location message always at 1 s; Basic ID/System may be 3 s; 5 Hz required if a channel other than 2.4 GHz ch 6 or 5 GHz ch 149 is used
- iOS (up to 15) only exposes BT4 legacy advertising to apps; README points to nccgroup/Sniffle for Bluetooth sniffing and to sxjack/unix_rid_capture as a basic Wi-Fi NaN/Beacon + Bluetooth scanner
- _(4 more facts in the JSON index)_

*E200:* No SDR receiver is listed; the practical RID path is a Wi-Fi monitor-mode dongle plus a Sniffle/nRF52840 dongle, with the E200 reserved for non-RID links.

### ICE9 Bluetooth Sniffer: all-channel BLE sniffing with bladeRF/HackRF/USRP
`4/5` · English · github · 2023-2025 · verified  
<https://github.com/mikeryan/ice9-bluetooth-sniffer>


The most capable open-source SDR Bluetooth sniffer: channelises 4–60 MHz of IQ into 2 MHz Bluetooth channels and detects BR and BLE packets, writing pcap. It links against libuhd for USRP, so it may run against the E200 through MicroPhase's antsdr_uhd fork (untested). No support for BLE 5 Coded PHY (long range) is documented, which is the transport EU/ASD-STAN add-on modules commonly use.


- Wideband 4-60 MHz capture on HackRF/USRP; all-channel on bladeRF; outputs PCAP for Wireshark
- No mention of BLE Coded PHY (S=2/S=8) or extended advertising in README/help
- Supports bladeRF, with wideband sniffing (4-60 MHz) for HackRF and USRP; needs libhackrf, libbladerf and/or libuhd for live capture
- Polyphase channelizer: 1 x 20 MHz -> 20 x 2 MHz; channelizer is the CPU bottleneck
- Detects BR packets (libbtbb techniques) then BLE packets; no mention of 2M or Coded PHY support
- Can read from a file with -f; writes Wireshark-compatible PCAP with -w

*E200:* Only bladeRF/HackRF/USRP backends; would need a libiio/Soapy backend and Coded PHY support before it could give the E200 a Remote ID BT5 path.

### unix_rid_capture: Linux Wi-Fi/Bluetooth ASTM F3411 Remote ID capture (rtl8812au + nRF52840)
`4/5` · English · github · 2021-2024 · verified  
<https://github.com/sxjack/unix_rid_capture>


Small Linux tool (libpcap + bluez + opendroneid-core-c) that captures RID from a monitor-mode Wi-Fi dongle (rtl8812au tested), Bluetooth HCI via bluez, or an nRF52840 sniffer dongle, outputting JSON and GPX. Tested on Raspberry Pi 3B, which is a comparable ARM class to the E200's Zynq PS.


- Requires a monitor-mode Wi-Fi card (rtl8812au tested) on channel 6 and optionally an nRF52840 dongle with sniffer firmware
- States it 'probably won't receive Bluetooth 5 advertising without external hardware'
- JSON output convertible to GPX; UDP output on port 32001
- Hardware: monitor-mode Wi-Fi adapters (rtl8812au), bluez >= 5.10 Bluetooth, nRF52840 dongle with sniffer firmware; Raspberry Pi 3B tested
- 'Probably won't receive Bluetooth 5 advertising without external hardware'
- JSON output (MAC, operator ID, UAV position, heading, speed, timestamps) and Perl scripts to GPX; needs root or cap_net_raw

*E200:* Confirms BT5 Long Range reception needs dedicated hardware; suits the AERIX receiver-node side rather than the E200.

### Two-stage RF drone detection under Wi-Fi/Bluetooth interference with open-set model identification
`3/5` · English · github · 2026 · verified  
<https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model>


Student pipeline (with LaTeX report) whose stage 1 is a whole-capture spectrogram CNN gating IQ into noise / wifi / bluetooth / drone, and stage 2 a ResNet + ArcFace metric-learning classifier with softmax-confidence rejection returning UNKNOWN for unseen drone models; a third task classifies protocol. Trains on RFUAV, Noisy Drone RF v2 and the NIST TN 2237 Wi-Fi/Bluetooth IQ reference set.


- Explicit Wi-Fi and Bluetooth negative classes from NIST TN 2237 (.h5, 2.4/5.8 GHz)
- Open-set rejection via ArcFace embeddings + confidence threshold; targets >90-95% soft recall in report.json; no published accuracy in README
- Supports SigMF input (--sigmf) as well as RFUAV and Noisy Drone formats
- Manifest splits by source; Stage 1 window 16,384 samples; Noisy v2 captures ~1M samples (~75 ms at 14 MHz) so high-energy crop offsets are used.
- Notes that some RFUAV files were dropped for missing Drone XML metadata.
- NIST TN 2237 dataset used as the non-drone Wi-Fi/Bluetooth class (Kaggle mirror 'nist-wifi-bluetooth-iq').

*E200:* Shows how to combine the three open IQ datasets into one training set with explicit interference classes, which is the false-alarm strategy an urban E200 node needs.

### bkerler/DroneID: Open Drone ID sniffer/spoofer with Bluetooth (Sniffle dongle), Wi-Fi and DJI receivers over ZMQ
`3/5` · English · github · 2023-2025 · verified  
<https://github.com/bkerler/DroneID>


Multi-source Remote ID receiver that takes Bluetooth via a Sonoff (Sniffle) dongle, Wi-Fi via monitor-mode interface or pcap replay and DJI DroneID via a separate receiver module, merges them in a ZMQ decoder and publishes decoded drone identities. Also includes a spoofer (transmit side is out of scope for AERIX).


- Three receiver stages publish raw messages to ZMQ ports; a central decoder aggregates and republishes
- Bluetooth reception relies on a Sonoff dongle with Sniffle firmware, not an SDR
- DJI proprietary receiver module included (used with antsdr_dji_droneid)

*E200:* The ZMQ contract used by the E200 DroneID firmware; AERIX 'future_sdr' ingestion could subscribe to this stream.

### gr-inspector: signal detector, OFDM parameter estimation and AMC toolbox (GSoC 2016)
`3/5` · English · github · 2016-2020 · verified  
<https://github.com/gnuradio/gr-inspector>


GNU Radio toolbox with an energy-based signal detector, blind OFDM parameter estimation (carrier spacing, symbol time, FFT size, cyclic prefix), blind OFDM synchronization and TensorFlow-based modulation classification. Targets GNU Radio 3.8 and is lightly maintained.


- OFDM estimator recovers subcarrier spacing and CP length blindly (cyclic-prefix autocorrelation approach), which is exactly the OcuSync 15 kHz / DroneID signature
- Requires GNU Radio 3.8; the drone_detection ODU toolbox adapted its OFDM and energy code to GR 3.10

*E200:* Useful reference implementation for a CP-based OFDM discriminator (OcuSync vs Wi-Fi) on the host.

### HydraWarden: passive 2.4 GHz RF drone detection/classification with RSSI free-space-path-loss ranging (HackRF)
`2/5` · English · github · 2026 · verified  
<https://github.com/iRuperth/hydra-warden>


Open passive detector using a HackRF One at 2.4 GHz, a binary detection CNN and a multi-class manufacturer/model CNN on spectrograms, plus a proximity tracker that converts RSSI to range with a free-space path-loss model and raises GREEN/YELLOW/RED alerts; ships a React HUD and a simulator mode.


- Two-stage CNN (detect, then classify DJI Mavic/Phantom, Parrot Anafi, Autel EVO II, Skydio 2)
- Range estimated from RSSI via FSPL and approach/retreat trend from a rolling buffer

*E200:* Illustrates the (crude) RSSI-to-range approach; an E200 node could improve on it with calibrated gain and the 10M/PPS reference.

### RF-UAVNet (Huynh-The et al., IEEE) MATLAB implementation on DroneRF
`2/5` · English · github · 2022 · verified  
<https://github.com/ThienHuynhThe/RF-based-Drone-Surveillance-with-DL>


MATLAB code and a normalized/reorganized DroneRF copy for RF-UAVNet, a 1D convolutional network for drone detection, type classification and operation-mode recognition; re-implemented in PyTorch by IQTLabs RFClassification where it reached 0.998 binary accuracy at 1.08 ms.


- Original DroneRF at data.mendeley.com/datasets/f4c2b4n755/1; RF_UAVNet.m and main_trainingDL.m provided
- 1D raw-sample CNN alternative to spectrogram models
- Includes DroneRF data after normalisation; original at data.mendeley.com/datasets/f4c2b4n755/1.

*E200:* Lightweight 1D CNN candidate for on-ARM inference once retrained on E200 IQ.


## Academic: datasets and fingerprinting

### DroneRFa: A Large-scale Dataset of Drone Radio Frequency Signals for Detecting Low-altitude Drones (JEIT 46(4), 2024; PDF read from GitHub mirror)
`5/5` · Chinese · paper · 2024 · verified  
<https://doi.org/10.11999/JEIT230570>


Zhejiang University (Yu Ningning, Shi Zhiguo, Chen Jiming et al.) dataset paper. Dual-channel NI USRP-2955 capture at 100 MS/s per channel (RF0 at 2440 MHz, RF1 at 5800 MHz; 915/2440 MHz for FrSky X20 and Taranis Plus), gain 50 dB, VERT2450 antenna, LabVIEW. 24 drone/controller classes + 1 background (with BT/Wi-Fi), 9 outdoor flying types at 20-40/40-80/80-150 m and 15 indoor types at ~2 m; >=12 segments per class, each >=1e8 samples; .mat (HDF5) with RF0_I/RF0_Q/RF1_I/RF1_Q float64; files <=1.5 GB; >=1 TB total.


- Drone list: DJI Phantom 3, Phantom 4 Pro, Matrice 200, Matrice 100, Air 2S, Mini 3 Pro, Inspire 2, Mavic Pro, Mini 2, Mavic 3, Matrice 300, Phantom 4 Pro RTK, Matrice 30T, Avata, DJI-module DIY, Matrice 600 Pro; controllers VBar, FrSky X20, Futaba T6IZ, Taranis Plus, RadioLink AT9S, Futaba T14SG, Yunzhuo T12, Yunzhuo T10.
- Known flaw: 'capture-store-capture-store' acquisition breaks continuity every 10M samples (0.1 s); analysis windows <0.1 s are unaffected.
- Baseline: ResNet-18 on (2,1024,1024) STFT of 1e6-sample (~10 ms) samples, 9809/3217/3299 split, accuracy 0.9773 at 53 fps; shrinking time length to 256 drops accuracy to 0.727.
- Filename encoding T<type>_D<distance>_S<segment>; S0000-0111 initial band (915 MHz or 2.4 GHz), S1000-1111 switched to 2.4/5.8 GHz.
- Download page stated in paper: https://jeit.ac.cn/web/data/getData?dataType=Dataset3; third-party mirror on SciDB is a single ~574 GB RAR (fileId c403fc76444e4b9989e4f3ff570f3b3d).

*E200:* Richest multi-band (915/2.4/5.8 GHz) and distance-labelled dataset, but 100 MS/s dual-channel; the E200's two RX chains share one AD9361 LO so its simultaneous 2.4+5.8 GHz design cannot be replicated directly; decimate to <=56 MHz and use RF0/RF1 separately.

### RFUAV dataset on Hugging Face (raw IQ, spectrograms, weights)
`5/5` · English · dataset · 2025 · snippet  
<https://huggingface.co/datasets/kitofrank/RFUAV>


Hosting location of the RFUAV raw IQ, spectrograms and model weights. Page could not be fetched (egress blocked); size figures come from a third-party downloader repo: 102 GB compressed in 37 .rar files, ~263 GB extracted, ~1.3 TB total raw claimed.


- Third-party notes (r4d10n/rfml-moe-hub datasets/rfuav.md): 102 GB compressed (37 rar), ~263 GB extracted, 37 drone/RC classes, .iq float32 files ~763 MB each (=1 s at 100 MSps), folders by VTS bandwidth 10/20/40/60 MHz, USRP X310, 5.765 GHz centre.
- Dataset licence on Hugging Face not verified.

*E200:* Download via huggingface-hub; needs resampling to <=56 MHz before use as E200 training data.

### CageDroneRF: A Large-Scale RF Benchmark and Toolkit for Drone Perception (arXiv, Jan 2026)
`4/5` · English · paper · 2026 · snippet  
<https://arxiv.org/abs/2601.03302>


Paper for CDRF; not fetchable (arXiv blocked). Facts above come from the official repo's README/citation block.


- Citation from repo: Rostami et al., arXiv preprint arXiv:2601.03302, 2026.
- Described as 'built from real-world captures and systematically generated synthetic variants'.

*E200:* Read for the benchmark protocol; hardware specifics (SDR model) remain unverified.

### DroneRFA_24-Dataset: spectrogram subset built from Zhejiang University's DroneRFa (includes the JEIT paper PDF)
`4/5` · Chinese · github · 2025 · verified  
<https://github.com/maojinxiang/DroneRFA_24-Dataset>


A lightweight 24-class (background + 23 drone types) spectrogram dataset derived from DroneRFa, with the generation script (h5py reader for the .mat IQ, STFT) and the original DroneRFa paper PDF. Gives the DroneRFa download page on SciDB (dataSetId=34f0a91e8a544904998b8fdc44477380) and explains the class codes T0000..T11000.


- DroneRFa is 'too large (mat format) to download easily'; author's subset is 24 classes; demo CNN/ResNet18 weights included.
- generate_spectrogram_dataset.py reads segments from .mat via h5py without loading whole files; DEFAULT_CLASSES lists T0000-T1111 and T10000-T11000.
- SciDB download: https://www.scidb.cn/en/detail?dataSetId=34f0a91e8a544904998b8fdc44477380

*E200:* Quickest way to get a small DroneRFa-derived training set; the reader code shows how to consume DroneRFa's RF0/RF1 I/Q HDF5 layout.

### Noisy Drone RF Signal Classification v2 (Kaggle hosting)
`4/5` · English · dataset · 2024 · snippet  
<https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2>


Kaggle hosting of the ZHAW dataset (page not fetchable). Used by several downstream projects (rf-signal-intelligence VGG 0.977 offline accuracy and 68/70 over-the-air replay matches; 2_Stage_Drone_Detection_Model).


- rameyjm7/rf-signal-intelligence: VGG full-complex spectrogram 0.9769 natural / 0.9803 balanced held-out accuracy; live bladeRF TX -> HackRF RX replay 68/70 exact matches over seven classes.
- Licence and exact size unverified (survey says ~23 GB).

*E200:* Kaggle CLI download; suitable for a first E200 classifier.

### Robust RF-Based Drone Identification under Co-Channel Interference (DroneRF SNR benchmark, 2026)
`4/5` · English · github · 2026 · verified  
<https://github.com/song-lalala/drone-rf-id>


Benchmark study on DroneRF: four architectures (compact CNN, ResNet-18, EfficientNet-B0, ViT-Small) all collapse to near-random accuracy at <= -5 dB SNR; random-SNR additive-noise training recovers most of it. Ships processed 128x128 STFT spectrograms (4,540: Background 820 / Bebop 1,680 / AR Drone 1,620 / Phantom 420) and pretrained weights.


- 4-class clean accuracy: compact CNN 82.9% -> 85.5% with robust training; ResNet-18 82.2% -> 87.5%.
- At -5 dB: compact CNN 37.1% -> 76.5%; ResNet-18 21.9% -> 81.1% with random-SNR training (range -5..20 dB, p_clean 0.2).
- Preprocessing: 10 chunks of 1e6 samples per CSV, n_fft 512, hop 2048; states DroneRF raw CSVs are ~40 GB and licensed CC BY 4.0.
- Code MIT.

*E200:* Recipe (random-SNR noise injection during training) transfers directly to any E200-collected dataset; also shows why clean lab datasets overstate field accuracy.

### Practitioner survey (2023-2026) inside rfml-moe-hub: UAVSig, CV-YOLO, CrossRF, DC-CNN, FDGAF-CNN results
`3/5` · English · doc · 2026 · snippet  
<https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md>


Third-party literature survey (LLM-assisted, unverified) summarising fingerprinting results: UAVSig (UCLA CORES, 2024) = 4 identical DJI M100 + controllers, 720 files, 50 MHz BW at 50 MSps on a USRP B205mini, hosted on UCLA Dataverse; CV-YOLO (Zhao & Cabric 2025) 93.8% single-drone individual fingerprinting, 67.7% two-drone, 86.5% cross-temporal; CrossRF (arXiv:2505.18200) 99.03% cross-channel with ADDA vs 26.39% without; DC-CNN 99.5% 4-class / 74.1% 8-class on DroneRF; FDGAF-CNN 98.72% DroneRF / 98.67% DroneRFa; wavelet scattering + SqueezeNet 98.9% at 10 dB on the 17-controller/8-manufacturer Ezuma-style dataset.


- UAVSig recorded on USRP B205mini (AD9364) at 50 MSps - the closest AD936x-class individual-fingerprinting dataset to the E200.
- Multi-domain supervised contrastive open-set UAV work (arXiv:2508.12689) used 20 known + 5 unknown classes at 100 MS/s.
- All numbers are second-hand; primary pages (UCLA Dataverse, IEEE DataPort for CardRF/Ezuma) not reachable in this session.

*E200:* Points to UAVSig as the dataset to obtain for individual-unit fingerprinting on AD9364-class hardware; treat all accuracies as unverified.

### RF Drone Detection EMI Robustness Benchmark (DroneRF, recording-level grouped splits)
`3/5` · English · github · 2026 · verified  
<https://github.com/greenbeanss/dronerf-emi-robustness>


Companion code for an IEEE Access submission that evaluates 11 detectors on DroneRF under 5 synthetic industrial-EMI profiles x 7 SNR levels, using recording-level grouped partitions (whole recordings assigned to train/val/test before windowing) and capacity-matched clean/augmented pairs. Documents the leakage problem in window-level DroneRF splits and provides EMI noise generators (Middleton Class-A, SCADA/PLC, partial discharge, Wi-Fi congestion).


- Uses 'recording-level grouped data partitions (every source recording assigned entirely to train/val/test before window selection)' with 5 rotations.
- Window-length sensitivity study at 2048/8192/32768 samples; fixed-FPR operating points and event-level voting analyses.
- Requires DroneRF from data.mendeley.com/datasets/f4c2b4n755/1 (~retains its own licence).

*E200:* The grouped-split protocol and the Wi-Fi-congestion/EMI augmentations are what an E200 toolkit should adopt for honest evaluation.

### RF-TCNet: lightweight topology-compression network for drone RF fingerprint identification (DroneRF + DroneRFa)
`3/5` · English · github · 2025 · verified  
<https://github.com/FAITHSHUNAA/RF-TCNet-A-Lightweight-Topology-Compression-Network-for-Drone-RF-Fingerprint-Identification>


Cloned. Lightweight CNN/transformer hybrid with 'dynamic frequency attention' trained on DroneRF and DroneRFa spectrograms generated by an 'ECSG' preprocessing script (src/ECSG.py). Same author also publishes MPAFNet (multi-path attention fusion, claims 100/99.7/99.5 % on three tasks). No paper link in README.


- Splits are done per image inside each class subfolder (random shuffle), i.e. window-level, not recording-level.
- No accuracy numbers in README.
- Pipeline: raw RF -> ECSG spectrogram -> RF_TCNet_Train.py / RF_TCNet_Test.py; claims very low trainable parameter count for edge use.
- Datasets: DroneRF (Qatar) and DroneRFa (ZJU); MIT licence; 8 stars.

*E200:* Illustrates the common (leaky) evaluation practice on DroneRFa; not directly reusable.

### Reproduction of 'From Lab to Field Trials: Real-Time Multimodel Drone Detection in Low-SNR Environments' (LowSNR_DroneRF, Kaggle)
`3/5` · English · github · 2026 · verified  
<https://github.com/jainarein/LowSNR-DroneRF-Reproduction>


Independent reproduction of Tanveer et al. (IEEE A&E Systems Magazine, Feb 2026) using the public Kaggle dataset laibatanveer/merged (~3 GB, 137,557,132 rows). Documents serious dataset flaws: the IQSAMPLES column holds non-negative power values not complex IQ, only OFF/ARMED labels exist, and the file is strictly ordered by class.


- Reproduced RF accuracy 83.99% vs paper's 93%; AUC 0.927 vs 0.94; ANN 68.0% vs 75-76%; CNN 73.2% vs 75%.
- Paper describes 3 s segments at 10 MHz sampling; public file has no segment IDs and no raw IQ.
- Paper's Table 3 (75% CNN) and Table 6 (92.3% CNN) are inconsistent.

*E200:* Negative example: a 'low-SNR field' dataset that cannot be used for IQ-based work; illustrates the checks (sign, ordering, label set) a toolkit's dataset loader should run.

### SE-DCNet: dual-domain (1D IQ + 2D STFT) fusion with SE attention for UAV RF fingerprint identification
`3/5` · Chinese · github · 2025 · verified  
<https://github.com/maojinxiang/SE-DCNet>


Cloned. Chinese-README PyTorch project (student at China University of Petroleum) fusing a 1-D IQ CNN branch with a 2-D STFT EfficientNet-B0 branch through an SE block; includes 1D/2D/ResNet/TCN ablations, noise-robustness sweep and pretrained weights. Trained on DroneRFa .mat files (RF0_I/RF0_Q, 1 M-sample = 10 ms windows, ~650 samples/class).


- dataset.py builds samples with N=512 STFT and T=2096 sequence length from .mat offsets; test_robustness_v2.py sweeps channels and SNRs.
- No licence file.
- Reads DroneRFa keys RF0_I/RF0_Q; samples of 1,000,000 points (10 ms at 100 MS/s); 6:2:2 split; test scripts hard-code 9 classes.
- Robustness evaluated at SNR -10, -5, 0, 5, 10 dB via synthetic noise injection.
- Companion repo maojinxiang/DroneRFA_24-Dataset (12 stars) ships pre-computed 24-class spectrograms, a ResNet-18/CNN demo and the DroneRFa JEIT PDF.

*E200:* Shows a raw-IQ + spectrogram fusion design that could run on a host attached to the E200.

### GENESYS Lab (Northeastern) GitHub organisation
`1/5` · English · github · 2025 · verified  
<https://github.com/genesys-neu>


Checked for UAV RF-fingerprinting datasets (the lab published UAV fingerprinting papers); the org page lists ni-rf-data-recording-api (NI/USRP recording API, MIT), TRACTOR, t-prime, target (UAV distributed beamforming) but no public drone fingerprinting dataset.


- ni-rf-data-recording-api (44 stars) is a generic Python API for recording real-world RF datasets with NI USRPs.

*E200:* No dataset; the recording API could inspire an E200 recorder design.


## Chinese-language academic work

### Remote ID Monitor — 无人机远程识别监控系统 (Go/Raspberry Pi Remote ID monitor supporting ASTM F3411, GB 42590 and GB 46750)
`5/5` · Chinese · github · 2025 · verified  
<https://github.com/luolitao/remoteid>


Cloned and read. Go 1.25 backend (gopacket/libpcap) on a Raspberry Pi in Wi-Fi monitor mode, Vue 3 front end, SQLite, WebSocket, TUI, pcap offline parsing, alerts, CSV/JSON export, plus a spoofer. Implements three protocol decoders: ASTM/ASD-STAN, China GB 42590-2023 and GB 46750 (variable-length). The most complete open reference for parsing Chinese Remote ID formats.


- All three protocols share the vendor IE OUI FA:0B:BC with OUI type 0x0D (backend/internal/drone/parser.go); legacy OUI 06:05:04 / type 0xFD also accepted.
- Discrimination rule (cmd/ridparse/main.go): GB 46750 if data[1]==0xFF and version high 3 bits == 0x1; otherwise message header low nibble 0x1 = GB 42590 protocol version, 0x2 = ASTM F3411-22a.
- Supports Wi-Fi Beacon and NAN action frames (subtype 13, WFA OUI 50:6F:9A + FA:0B:BC); 2.4 GHz only; no BLE; MIT licence.
- gb42590.go notes a bug fix: in GB 42590 Classification occupies the low 3 bits and Operator Location Type the next 2 bits of the System message byte.
- All three protocols ride the same Vendor Specific IE (0xDD) with OUI FA:0B:BC and OUI type 0x0D; ASTM F3411-22a is header low nibble 0x2, GB 42590-2023 is header low nibble 0x1 (25-byte messages, 12-bit direction, invalid 0x0FFF), GB 46750 is data[1]==0xFF variable-length with a 3-byte x 7-bit data-identifier bitmap for 21 items
- GB 46750 encodings: altitude (raw/2)-1000 m (or -9000 for relative), heading uint16 LE x 0.1 deg, timestamp 6-byte LE Unix ms
- NAN service discovery carried in Action frames (subtype 13) with Wi-Fi Alliance OUI 50:6F:9A
- Includes tools/spoofer (drone signal simulator) and offline pcap/pcapng parsing (ridparse -file)

*E200:* Not SDR code, but the parser logic is what AERIX's future_sdr receiver class needs to be compatible with when Chinese-format frames appear; could be ported to run on decoded 802.11 beacons from openwifi on the E200.

### XC-RemoteID — 符合 GB 46750-2025 国标的无人机 Remote ID 发射器固件 (GB 46750-2025 compliant ESP32 Remote ID transmitter)
`5/5` · Chinese · github · 2026 · verified  
<https://github.com/luolitao/XC-RemoteID>


ESP32 transmitter for China's GB 46750-2025, derived from ArduRemoteID. The README summarises the standard's obligations (continuous broadcast that cannot be switched off, <=1 s interval, BLE 5.0 extended advertising or Wi-Fi beacon, 120 h rolling log, take-off interlock, ADS-B prohibited) and its transition periods. Useful as a plain-language digest of GB 46750 since the standard PDF is blocked.


- GB 46750-2025《民用无人驾驶航空器系统运行识别规范》published 2025-10-31, effective 2026-05-01; 12-month retrofit window, 36-month transition; network reporting mandatory; ADS-B explicitly forbidden.
- Packet format: type + version + length + bitmap of 21 data items; identity = unique product code (GB/T 41300) + real-name registration flag; coordinates WGS-84 or CGCS2000; README says timestamp is Unix ms 6-byte little-endian (the esp32-crid-sim encoder instead writes 4-byte seconds since 2019-01-01 — unresolved discrepancy).
- BLE: service-data AD type 0x16 with UUID 0xFFFA and subtype 0x0D, extended advertising interval 1600 (1 s), +9 dBm; Wi-Fi: vendor IE OUI FA:0B:BC type 0x0D in Beacon and Probe Response.
- Standard text link: https://www.caac.gov.cn/XXGK/XXGK/BZGF/BZGF_GJBZ/202601/t20260120_229783.html
- GB 46750-2025 published 2025-10-31, effective 2026-05-01; links to CAAC publication page and a CAAC 2026-03-06 notice on network-mode identification
- §6.1.2: must use at least Bluetooth 5.0 broadcast mode or Wi-Fi broadcast mode; firmware uses BLE 5.0 Extended Advertising + Wi-Fi Beacon; BT4.2 chips cannot carry a full packet (31-byte limit)
- Identity = product serial (GB/T 41300) + last 8 digits of the CAAC real-name registration number; WGS-84 or CGCS2000; network reporting mandatory with cache/resend
- Transition: manufacturers must retrofit sold drones with a module within 12 months of publication; 36-month transition for retrofitted systems

*E200:* If Chinese-market drones or retrofit modules appear in EU airspace they will broadcast this format; AERIX's ODID-based parser will not decode it without an extension.

### DroneRFb-DIR: 用于非合作无人机个体识别的射频信号数据集 (DroneRFb-DIR: RF dataset for non-cooperative drone individual identification)
`4/5` · Chinese · dataset · 2025 · snippet  
<https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202>


JEIT 2025 47(3):573-581, DOI 10.11999/JEIT240804, 任俊宇/俞宁宁/周成伟/史治国/陈积明 (Zhejiang University, State Key Lab of Industrial Control, Hangzhou Dianzi University, ZJU Jinhua Institute). SDR captures of 6 drone types x 3 physical individuals plus one urban background class, intended for RF-fingerprint identification of specific airframes rather than models. Hosted on SciDB (blocked from this sandbox).


- Raw I/Q storage, each class >=40 segments of >=4 M samples, sampled over 2.4-2.48 GHz (80 MHz span).
- Contains flight-control (FCS), video-transmission (VTS) and surrounding-device interference signals in urban scenes.
- SciDB dataSetId 84cf9101e739402784b1396783881202; paper PDF at https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4.

*E200:* Useful to test whether per-airframe fingerprinting survives the E200's narrower capture; same 80 MHz caveat as DroneRFa.

### ESP32 C-RID (Remote ID Scanner & Simulator) — 无人机远程识别扫描/模拟 (ESP32-S3 Remote ID scanner and emitter, ASTM + GB 42590 + GB 46750)
`4/5` · Chinese · github · 2025 · verified  
<https://github.com/luolitao/esp32-crid>


Cloned. ESP-IDF 6 project with main_rx (promiscuous sniffer + parser built on the official opendroneid library + tracker + JSON over UART1) and main_tx (beacon simulator). Parser tries GB 46750, then GB 42590, then ASTM. Handy low-cost companion receiver and JSON event schema (uav_discovery/uav_update/uav_timeout).


- Header discrimination in README: ASTM 0xF1, GB 42590 0xF1 (3-byte pack header [0xF1][25][MsgCount] vs ASTM 2-byte [0xF1][MsgCount]), GB 46750 0xFF.
- Defaults: OUI FA:0B:BC, vendor type 0x0D, IE 221, channel 6 (2.437 GHz), 1 Hz.
- Emits single-line JSON with mac, rssi, channel, transport, protocol, basic_id, location, self_id; 5-minute timeout tracker.

*E200:* JSON schema is a ready-made template for an SDR-side Remote ID emitter feeding the AERIX observation contract.

### ESP32 中国民用无人机远程识别（C-RID）模拟发射器 (ESP32 C-RID Wi-Fi beacon simulator, GB 42590 / IB-TM-2024-01 / GB 46750)
`4/5` · Chinese · github · 2025 · verified  
<https://github.com/luolitao/esp32-crid-sim>


Cloned. MIT-licensed ESP-IDF beacon emulator with web UI, OTA and patrol-track simulation; contains a complete GB 46750 encoder (rid_gb46750.c) and the 25-byte GB 42590 message builders, i.e. a test signal source for any receiver.


- GB 42590: five fixed 25-byte messages Basic ID 0x0, Location 0x1, Self-ID 0x3, System 0x4, Operator ID 0x5 (no Auth message required by the Chinese standard).
- GB 46750 encoder layout: byte0 data type 0xFF, byte1 version 0x20, bytes 2-4 flag bitmap, then fields in flag order (UAS ID 20 B, reg flag, category, class, GCS pos type, GCS lat/lon 2x int32, GCS alt u16, UA lat/lon, track u8, ground speed u8, rel alt, vert speed, geo alt, baro alt, op status, coord type, NACp, GVA, NACv, timestamp u32, ts accuracy).
- Wireshark filter suggested: wlan.tag.oui == fa:0b:bc; default channel 6, 1 Hz.

*E200:* Use as a bench emitter to validate an E200/openwifi or Wi-Fi-dongle Remote ID receiver against both Chinese formats.

### 低信噪比条件下无人机射频信号实时检测方法 (Real-time drone RF signal detection under low SNR)
`4/5` · Chinese · paper · 2023 · snippet  
<https://signal.ejournal.org.cn/article/doi/10.16798/j.issn.1003-0530.2023.05.016>


信号处理 (Journal of Signal Processing) 2023 39(5):919-928, 苏志刚/晏翔/韩冰. Lightweight multi-branch convolutional backbone plus attention operating on full-capture spectrograms to detect drone signals at very low SNR in real time. PDF on sciengine (blocked here).


- Detection accuracy 94.63-94.75 % in the -15 to -6 dB range and 97.35-97.50 % over -15 to +15 dB.
- Inference time 1.61 ms per spectrogram.
- PDF: https://www.sciengine.com/parse/pdf/1003-0530/F1FDEFB8A2684310A37ED805A8E2679C.pdf

*E200:* Architecture is small enough to be a candidate for the host-side or Zynq-ARM detection stage; SNR figures are from synthetic noise injection, not long-range field captures.

### 基于梅尔倒谱系数的无人机探测与识别方法 (Drone detection and recognition based on Mel-frequency cepstral coefficients)
`4/5` · Chinese · paper · 2025 · snippet  
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT241111?viewType=HTML>


JEIT 2025 (vol 47). Collects drone video-link signals with a USRP N210, extracts MFCC as RF fingerprint features and classifies with a tiny GRU; also reports 3-D localisation. Authors/affiliation not visible in snippets.


- Recognition accuracy 98 % with a GRU of only 1.6 k parameters trained in 9 s.
- 3-D localisation error below 1 m (setup not described in snippet).
- Hardware: USRP N210 (max 25 MS/s over GbE, i.e. comparable to E200 streaming).

*E200:* N210-class bandwidth means the features were computed on <=25 MHz captures; MFCC+GRU is cheap enough to run on the E200's ARM core.

### GB42590 报文解析方法 (GB 42590 broadcast message parsing guide, CSDN)
`3/5` · Chinese · blog · 2024 · snippet  
<https://blog.csdn.net/qq_41126242/article/details/143920008>


CSDN article giving a field-level parsing method for GB 42590-2023 broadcast Remote ID messages; companion post 143707020 covers a GB 42590 transceiver, and DOIT_SZ 137604501 describes a dual-band (2.4/5.8 GHz) Wi-Fi module receiver.


- GB 42590-2023 requires Wi-Fi beacon vendor-specific IE (element 221) with OUI FA:0B:BC; broadcast over Wi-Fi 2400-2476 MHz or 5725-5829 MHz, or Bluetooth.
- Manufacturers may fill the payload with OpenDroneID message types (Basic ID, Location, Self ID, System, Operator ID).

*E200:* Note the 5.8 GHz Wi-Fi option: none of the open receivers found (luolitao/remoteid, esp32-crid) listen there, but the E200 can.

### P3X OFDM Receiver board (Lightbridge PHY notes, dji-firmware-tools wiki)
`3/5` · English · doc · 2018 · verified  
<https://github.com/o-gs/dji-firmware-tools/wiki/P3X-OFDM-Receiver-board>


Fetched. Hardware teardown notes for the Phantom 3 Lightbridge receiver: AD9363 (later Artosyn AR8003) transceiver with Cyclone V FPGA / AR8001 ASIC, described as WiMAX-derived OFDM with custom framing and adaptive BPSK-64QAM, 2.3-2.6 GHz. Explains the 2.2 ms hop dwell / 14 ms video period family in DroneRFa Table 4.


- Lightbridge is WiMAX-based OFDM with custom scrambling; AR8003 supports BPSK/QPSK/16QAM/64QAM adaptive over 2.3-2.6 GHz or 3.3-3.8 GHz.
- No FFT size or frame structure documented.
- Early boards: Analog Devices AD9363 2x2 transceiver + Altera Cyclone V 5CEFA4U19I7 FPGA; STM32F103 configures via SPI
- Later P01007.14: Artosyn AR8003 WiMAX 2T2R transceiver (2.3–2.6 GHz or 3.3–3.8 GHz) + AR8001 baseband replacing the FPGA
- Adaptive BPSK/QPSK/16QAM/64QAM

*E200:* Background for classifying older DJI (P3/P4/Inspire 2/M600) links; the AD9363 on the drone side is the same family as the E200's AD9361.

### 基于多维信号特征的无人机探测识别方法 (Drone detection and recognition based on multi-dimensional signal features)
`3/5` · Chinese · paper · 2023 · snippet  
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230302?viewType=HTML>


JEIT paper combining an adaptive triangular-threshold detector on received spectra, channel-state-information analysis with OMP parameter estimation for locating the drone, and box-counting dimension plus radial-integration bispectrum (RIB) features for classification. Authors not surfaced by search.


- Detection: adaptive triangle threshold to separate drone signals from other wireless signals.
- Classification features: box dimension and radial integration bispectrum; reported accuracy up to 100 % (small test set implied).

*E200:* Feature set is classical DSP; cheap to port, but reported accuracy should be treated as lab-only.

### 基于小波熵特征的无人机射频信号识别算法研究 (Drone RF signal recognition based on wavelet-entropy features)
`3/5` · Chinese · paper · 2025 · snippet  
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT250051?viewType=HTML>


JEIT 2025 47(8):2736-2745, 刘冰/时明心/刘佳琪. Wavelet-entropy statistics of hop signals fed to a DNN for drone-signal recognition. Largely a feature-engineering re-implementation of Western DroneRF-style pipelines.


- Defines statistical features of frequency-hopping signals and uses a deep neural network classifier.
- Affiliation not visible; PDF blocked.

*E200:* Wavelet entropy is bandwidth-agnostic and could be computed on a 20 MHz E200 slice.

### 基于深度学习的无人机检测和识别研究综述 (Survey of deep-learning drone detection and recognition)
`3/5` · Chinese · paper · 2024 · snippet  
<https://signal.ejournal.org.cn/article/doi/10.16798/j.issn.1003-0530.2024.04.001>


信号处理 2024 40(4) survey covering visual, acoustic, radar and RF drone detection with deep learning, including RF datasets and methods. Best single Chinese-language literature map for this topic.


- Reviews RF-signal detection and recognition alongside vision/audio/radar; published in the same issue as a UAV RF-fingerprint domain-adaptation paper (10.16798/j.issn.1003-0530.2024.04.004: Transformer encoder + domain-adversarial network for drone emitter individual identification).
- The journal has an open call for a special issue '无人机通信频谱感知与智能信号识别' (https://signal.ejournal.org.cn/news/48), signalling a coming batch of Chinese RF-drone papers.

*E200:* Reading list only.

### 独角兽暑期训练营 \| 无人机广播信号盲分析 (Unicorn Team summer camp: blind analysis of drone broadcast signals)
`3/5` · Chinese · blog · 2019 · snippet  
<https://www.anquanke.com/post/id/168279>


2019 write-up from the 360 Unicorn Team training camp on blind analysis of DJI broadcast (DroneID) signals: spectrum scanning to separate periodic small packets from the wide video downlink and uplink control channel. Predates the RUB DroneSecurity work and is the earliest Chinese public DroneID analysis.


- Identified periodic small-packet broadcasts separate from video and control channels and hypothesised they were DroneID for drone localisation/identification.

*E200:* Historical; methodology (blind periodicity search) is reusable for unknown links.

### Wifi干扰下无人机图传信号的射频识别方法 (RF identification of drone video-link signals under Wi-Fi interference) - patent CN113518374A
`2/5` · Chinese · other · 2021 · snippet  
<https://patents.google.com/patent/CN113518374A/zh>


Chinese patent describing FFT, EMD denoising, extraction of 30 time/frequency statistical features and SVM / decision-tree / NN / random-forest classifiers to identify drone video signals in the presence of Wi-Fi. This is essentially the Ezuma/Al-Sa'd DroneRF pipeline re-cast as a patent, not novel.


- Pipeline: FFT -> EMD denoise -> 30 statistical features -> classical ML.
- A related patent CN118673374A claims a neural-network drone RF detection method.

*E200:* Confirms that the Western feature pipeline is what Chinese practitioners also use; nothing E200-specific.

### 基于噪声指纹的无人机检测与识别 (Drone detection and identification based on noise fingerprints)
`2/5` · Chinese · paper · 2025 · snippet  
<https://www.juestc.uestc.edu.cn/article/doi/10.12178/1001-0548.2024309>


Journal of UESTC (电子科技大学学报) paper using the noise floor / noise fingerprint of drone transmitters for detection and identification; only the title was retrievable.


- Title indicates a noise-fingerprint approach distinct from spectrogram CNNs; authors and numbers not retrievable.

*E200:* Unknown until the PDF is read.

### 基于无线电技术的民用无人机侦测与管控方法在监所环境的探究 (Radio-based civil drone detection and control in prison environments)
`2/5` · Chinese · paper · 2018 · snippet  
<https://www.hanspub.org/journal/paperinformation?paperid=26813>


Hans Publishers open-access paper on extracting spectral features of civil drone radio signals, locating them and managing them around prisons; an applied-engineering view of a Chinese deployment scenario.


- Starts from the radio signals civil drones use and covers feature extraction, localisation and control (the control part is out of scope for passive receive).

*E200:* Low; deployment lessons only.

### 无人机跳频信号识别技术介绍 (Drone frequency-hopping signal recognition, vendor explainer)
`2/5` · Chinese · vendor · 2024 · snippet  
<https://www.techphant.cn/blog/103897.html>


Vendor (技象科技) explainer of how Chinese counter-drone products detect FHSS control links: wideband scan, FFT + energy detection to catch hop transients, time-frequency extraction of carrier, dwell time and hop sequence, then HMM or deep-learning pattern engines. Also quotes typical RC cycle timing.


- Claims >95 % recognition of random hop sequences using trained hop-pattern models.
- Quotes RC transmitters cycling through their hop set every ~7 ms with the drone receiver scanning faster and locking on.

*E200:* Confirms industry practice: dwell-time/hop-spacing statistics are the primary FHSS discriminators, all measurable in 20 MHz.

### 电子与信息学报 数据集专栏 (JEIT dataset column, now redirecting to SciDB)
`2/5` · Chinese · doc · 2025 · snippet  
<https://jeit.ac.cn/web/data/getData?dataType=Dataset1>


JEIT's dataset portal; the journal states its datasets (DroneRFa, DroneRFb-DIR and others) have moved to the CAS Science Data Bank (scidb.cn). Also linked: ZJU ISEE news item announcing the 反无人机组 (anti-drone group) DroneRFa release (http://www.isee.zju.edu.cn/2024/0708/c21123a2944315/page.htm).


- All JEIT-published drone RF datasets are on SciDB; registration required; files are large .mat segments.

*E200:* Download logistics only.

### 面向远距离高速无人机检测的OFDM通信感知一体化参考信号设计 (OFDM ISAC reference-signal design for long-range high-speed UAV detection)
`1/5` · Chinese · paper · 2025 · snippet  
<https://radars.ac.cn/article/doi/10.12000/JR24240>


Journal of Radars 2025 14(4):842-853. Active integrated sensing and communication design; included to record that the 雷达学报/通信学报 stream on UAV detection is radar/ISAC oriented and not passive RF, so it is out of scope for an E200 passive toolkit.


- Active OFDM ISAC waveform design, not passive reception.

*E200:* None (transmit required).


## Chinese-language community and vendor sources

### ANTSDR 时钟校准 (ANTSDR clock calibration) — E310 page that the E200 page explicitly points to as applicable
`5/5` · Chinese · doc · 2025 · verified  
<https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration_cn.md>


The only place the external-reference discipline procedure is documented. The 10M/PPS input is handled by an IIO device named ad5660mp (an AD5660 DAC steering the VCXO). Attributes select manual/auto mode and whether the reference is 10 MHz, PPS or GPS; a lock flag reports PLL lock. Needed for any TDOA/multi-receiver AERIX deployment.


- IIO device iio:device0 'ad5660mp' with attrs in_voltage_dac_mode (0 auto,1 manual; default 1), in_voltage_dac_value, in_voltage_dac_read_value (default 23000), in_voltage_dac_ref_sel (0:10M 1:PPS 2:GPS), in_voltage_dac_locked
- Auto-lock to 10 MHz: echo 0 > in_voltage_dac_mode; echo 0 > in_voltage_dac_ref_sel; wait tens of seconds; cat in_voltage_dac_locked -> 1
- Physical hookup requires an SMA-to-MMCX cable into the 10/PPS port (E310 photo); E200 page says method is identical
- Firmware banner: v0.39, https://github.com/MicroPhase/antsdr-fw-patch
- Other IIO devices listed: ad9361-phy, xadc, cf-ad9361-dds-core-lpc, cf-ad9361-lpc
### E200 RF / ANTSDR 选型 (E200 RF parameters and ANTSDR model selection table) — MicroPhase official Chinese docs
`5/5` · Chinese · doc · 2025 · verified  
<https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters_cn.md>


Official Chinese selection table comparing E200/E310/E316. It is the authoritative statement that the E200 RF ports are 'SMA:1T1R IPEX:1T1R', that host streaming is 20 MSPS over 1 GbE, that DDR is 512 MB (vs 1 GB on E310/E316), that 10M/PPS sync exists and that both libiio and UHD APIs are supported. Also mirrors the E200 TX power curves.


- RF channel: SMA 1T1R + IPEX 1T1R (E310/E316 are 2T2R MIMO on SMA)
- Instantaneous bandwidth 56 MHz (AD9361) / 20 MHz (AD9363)
- Transmission bandwidth to host: 20 MSPS (E310 only 10 MSPS)
- PS DDR3 512 MB on E200 vs 1 GB on E310/E316
- Clock sync 10M/PPS; API libiio & UHD, C/C++/Python
- Local clone: /tmp/claude-0/-home-user-aerix-v2/8f01e3c2-dc35-5950-904f-84c7a819e91d/scratchpad/repos/antsdr_doc_en/source_cn/...
### antsdr-fw-patch README (Pluto firmware for ANTSDR; 2r2t mode section)
`5/5` · English · github · 2025 · verified  
<https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md>


The Pluto-compatible firmware build for E200/E310. Its '2r2t' section is the only documented way to enable the second receiver on the E200 (the IPEX 1T1R port) under the libiio/Pluto firmware: u-boot environment variables in QSPI mode, or uEnv.txt edits for SD boot. It also links the official Taobao listings and states the E200 cannot be flashed via DFU.


- QSPI boot: fw_setenv attr_name compatible; fw_setenv attr_val ad9361; fw_setenv compatible ad9361; fw_setenv mode 2r2t; reboot
- SD boot: edit uEnv.txt mode=1r1t -> mode=2r2t, adi_loadvals fdt addr ${devicetree_load_address}, add run adi_loadvals and #{fit_config} to sdboot, append attr_name/attr_val/compatible lines
- Official Taobao E200 listing: https://item.taobao.com/item.htm?id=691394502321 (E310: id=647986963313, E310V2: id=708976727818)
- Firmware built with Vivado 2023.2 (v0.39); sh patch.sh e200; outputs antsdre200.dfu/.frm/.itb and zynq-antsdre200.dtb
- DFU flash update is only for E310/E310v2(E316); 'e200 is unsupport'
### E200 UHD (E200 UHD build and probe) — MicroPhase official Chinese docs
`4/5` · Chinese · doc · 2025 · verified  
<https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD_cn.md>


Chinese UHD page with the exact cmake invocation for the MicroPhase UHD fork and a full uhd_usrp_probe dump for the E200. The probe shows the device enumerating as a B205MINI-compatible product with RX antennas 'TX/RX' and 'RX2', 50-6000 MHz tuning, 0-76 dB RX gain, 200 kHz-56 MHz bandwidth, and internal/external clock and time sources.


- cmake -DENABLE_X400=OFF -DENABLE_N320=OFF -DENABLE_X300=OFF -DENABLE_USRP2=OFF -DENABLE_USRP1=OFF -DENABLE_N300=OFF -DENABLE_E320=OFF -DENABLE_E300=OFF ../ ; default install /usr/local/lib/uhd
- uhd_usrp_probe: '[E200] _Product B205MINI(COMPATIBLE)', FPGA Version 7.0, 'No mboard EEPROM found'
- RX Frontend A: Antennas TX/RX, RX2; Freq 50-6000 MHz; Gain PGA 0-76 dB step 1; BW 200 kHz-56 MHz; sensors temp, rssi, lo_locked
- Time sources none/internal/external; Clock sources internal/external; sensor ref_locked
- Demo device args are type=ant (demo/uhd/main.cpp)
### E200 开箱检测 (E200 unboxing and inspection) — MicroPhase official Chinese docs (also at antsdr-docs.microphase.cn)
`4/5` · Chinese · doc · 2025 · verified  
<https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination_cn.md>


Chinese getting-started page. Lists exactly what ships in the box, the factory firmware state (Pluto firmware in QSPI, UHD firmware boots from SD), default IP/credentials/baud, the BOOT QSPI/SD DIP switch under the Ethernet jack, CH340 serial chip, and that SDR#/SDR++ connect via 192.168.1.10. Confirms no IPEX pigtail or GPSDO is bundled.


- Box contents (standard kit): SDR x1, USB cable x1, rubber-duck antennas x2, card reader x1, Ethernet cable x1, 32 GB SD card x1
- Pluto firmware pre-flashed in QSPI; UHD firmware must boot from SD card
- Pluto firmware default IP 192.168.1.10, user root / password analog, UART 115200 baud (CH340)
- Boot-mode DIP switch (QSPI/SD) is below the Ethernet port; green LED blinks after boot
- Same page served at https://antsdr-docs.microphase.cn/en/latest/cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination_cn.html
### 通信算法之292：大疆DJI云哨系统-DroneID物理层协议解析-O1/O2/O3/O4机型都可以CRC正确 (Comms algorithm #292: DJI 'Yunshao' (Aeroscope) system — DroneID PHY analysis, CRC-correct on O1/O2/O3/O4 models) — CSDN, leegang12 series
`4/5` · Chinese · blog · 2025 · snippet  
<https://blog.csdn.net/leegang12/article/details/149397403>


One entry of a long 2025 CSDN series by 'leegang12' that claims an independent reverse-engineering of the DJI Aeroscope/DroneID physical layer from large captures, with receivers that CRC-validate O1 through O4 airframes. Companion posts cover 640 ms periodicity (#267), rate de-matching and Turbo decoding (#283, soft decoding +3 dB), demod threshold ~5 dB (#305), packet types (#320), O2 video-link PHY (#254, #264), Remote ID (#256) and DJI RID frame format (#258). No public code was found; CSDN is blocked so all facts are snippet-level.


- Series claims CRC-correct DroneID decoding for O1/O2/O3/O4 generation DJI drones
- Turbo decoding done with soft decisions, cited as 3 dB better than hard decisions
- Demodulation threshold reported around 5 dB (#305: https://blog.csdn.net/leegang12/article/details/149977416)
- Receiver includes integer and fractional frequency-offset estimation and a rate de-matching module (#283: https://blog.csdn.net/leegang12/article/details/148471288)
- Related: #267 640 ms DroneID period (https://blog.csdn.net/leegang12/article/details/147321812); #296 PHY protocol from mass captures (https://blog.csdn.net/leegang12/article/details/149822783); #320 packet types (https://blog.csdn.net/leegang12/article/details/150761143); #254 O2 PHY (https://blog.csdn.net/leegang12/article/details/146934408); #264 O2 reverse engineering (https://blog.csdn.net/leegang12/article/details/147245156); #258 DJI RID frame format (https://blog.csdn.net/leegang12/article/details/146977731); #256 Remote ID (https://blog.csdn.net/leegang12/article/details/146936478); #281 open-source DroneID project issues (https://blog.csdn.net/leegang12/article/details/148402169)
- DroneID described as 2.4/5.8 GHz OFDM, 1024-point FFT, ~600 ms bursts, 10 MHz (15.56 MHz with guards)
- DroneID parameters quoted: 30.72 MS/s, 601 occupied subcarriers, 15 kHz spacing, ZC sequence in the 4th OFDM symbol, ~10 MHz (15.56 MHz with guards), burst roughly every 600-640 ms.
- O2 PHY: 1024-point FFT OFDM, CP between symbols; author claims O1/O2/O3/O4 DroneID frames decode with correct CRC.
- _(1 more facts in the JSON index)_
### openwifi kernel_boot/boards/antsdr_e200 README (ANTSDR-E200 board notes)
`3/5` · English · github · 2024 · verified  
<https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md>


Explains the key architectural difference of the E200: Ethernet MAC/PHY is placed on the PL side so that >20 MSPS baseband streaming (~80 MB/s) does not saturate the weak Zynq PS; IIO drivers still use the GEM controller. This is why E200 (not E310) supports UHD streaming. Also the openwifi port that makes the E200 an 802.11 a/g/n receiver (relevant for WiFi-beacon Remote ID capture on-device).


- 'The ethernet is placed at the PL side' to stream baseband >20 MSPS (~80 MB/s)
- IIO drivers unaffected because ZYNQ GEM controller is still used
- openwifi board dir exists for antsdr_e200 (boot files differ from E310 per MicroPhase Chinese doc)
- MicroPhase Chinese openwifi guide: ./openwifi/setup_once.sh; ./wgd.sh; ./fosdem.sh; AP web UI at 192.168.13.1
### 基于AD9361的图传hdzero图传介绍 (Introduction to the AD9361-based HDZero video link) — 科创网
`3/5` · Chinese · forum · 2021 · snippet  
<https://www.kechuang.org/t/89181>


Chinese forum explanation of the HDZero architecture: Divimath (迪威码, Xi'an) DM5680 baseband chip does OFDM modulation of uncompressed video and hands I/Q to an AD9361; the receiver demodulates OFDM from an AD9361. Together with the EEWorld ADI/Divimath press piece it gives the numbers needed to build an HDZero signature (non-hopping OFDM, fixed 5.8 GHz channel).


- TX: AHD video -> DM5680 baseband (OFDM) -> DAC -> AD9361 RF -> PA -> antenna; RX: AD9361 -> OFDM demod -> display
- DM5680 transmits raw uncompressed video; latency < 1 ms; up to 1080p30
- Range 1.3 km at 5.8 GHz / 20 dBm, 22 km at 520 MHz / 30 dBm (https://news.eeworld.com.cn/mp/ADI/a60568.jspx)
### 大疆发布 DJI O4 地面站 (DJI releases the O4 ground station) — IT之家; plus O4 Air Unit launch article
`3/5` · Chinese · vendor · 2025 · snippet  
<https://www.ithome.com/0/965/621.htm>


Chinese launch coverage giving O4 operating bands. O4 Air Unit / Air Unit Pro use 5.170-5.250 GHz and 5.725-5.850 GHz; the O4 ground station adds sub-2 GHz, 2.4 GHz, 5.2 GHz and 5.8 GHz with seamless switching, and a 12-antenna dual-polarised array. Determines which sub-bands an E200 must scan for O4-class links.


- O4 Air Unit / Pro bands: 5.170-5.250 GHz and 5.725-5.850 GHz (https://digi.ithome.com/archiver/823/622.htm)
- O4 ground station: automatic switching among sub-2 GHz, 2.4 GHz, 5.2 GHz, 5.8 GHz; 12-antenna array, dual polarisation
- Latency 20 ms standard / 15 ms racing mode
### 大疆图传技术参数对比 你了解多少？ (How much do you know about DJI video-link parameter comparison?) — CSDN
`3/5` · Chinese · blog · 2025 · snippet  
<https://blog.csdn.net/qq_43464910/article/details/151153810>


Chinese comparison of DJI link generations (Wi-Fi, Lightbridge, OcuSync 1/2/3, O3/O4) with range and latency numbers. Lightbridge is described as an FPGA + AD9361 design; OcuSync as 2.4/5.8 dual-band with real-time spectrum analysis for band choice. Handy for a per-generation signature table.


- Lightbridge implemented with FPGA + '9361' (AD9361) chip (per besovideo article https://www.besovideo.com/detail?t=2&i=1605)
- OcuSync: 2.4/5.8 GHz dual band, automatic least-interference band selection, OFDM, MIMO, H.265, FEC, AMC, hopping and power control
- M300 RTK OcuSync range up to 15 km (FCC)
### 无人机侦测：频谱无线电侦测设备技术详解 (Drone detection: technical details of spectrum/radio detection equipment) — CSDN, dong2010hong series
`3/5` · Chinese · blog · 2024 · snippet  
<https://blog.csdn.net/dong2010hong/article/details/142590321>


Vendor-style explainer of how Chinese commercial RF drone detectors are built: wideband receiver, FFT feature extraction, feature/fingerprint library matching to identify manufacturer and model, amplitude-comparison direction finding, TDOA for multi-station, black/white lists and pilot localisation. Companion posts: #138107124 (spectrum-analyser implementation) and #142896540 (core techniques). Good checklist for what a 'signal library' should contain.


- Typical monitored range 300-6000 MHz; receiver sensitivity quoted as -120 dBm or better
- Identification of manufacturer/model by feature matching against a signal characteristic library
- Direction finding by amplitude comparison; multi-station TDOA for location; also AOA
- Features listed: black/white lists, pilot (飞手) localisation, 24/7 360-degree monitoring independent of weather/light
- Related posts: https://blog.csdn.net/dong2010hong/article/details/138107124 and https://blog.csdn.net/dong2010hong/article/details/142896540
### 无人机射频侦测开源数据集汇总 (Roundup of open drone RF detection datasets) — AtomGit/GitCode community, liweinjit
`3/5` · Chinese · blog · 2025 · snippet  
<https://gitcode.csdn.net/6a2459d5662f9a54cb7ac49a.html>


A Chinese-maintained roundup of open drone-RF datasets described as continuously updated. Likely lists DroneRF, DroneRFa, DroneRFb-DIR, DroneDetect, CardRF and others with links; worth pulling by hand to cross-check round-1 dataset coverage.


- Claims a comprehensive, continuously updated list of open-source drone RF detection datasets
- Blocked domain; contents not verified
### 解读GB42590-2023《民用无人驾驶航空器系统安全要求》 (Reading GB 42590-2023 'Safety requirements for civil UAS') — NetEase
`3/5` · Chinese · standard · 2024 · snippet  
<https://www.163.com/dy/article/KCLCCD000552L9R6.html>


Explainer of China's first mandatory national UAS standard. Relevant to AERIX because it obliges light/small drones to broadcast identification over WiFi or Bluetooth (plus network reporting), i.e. Chinese-market drones now emit a broadcast Remote ID that an Open Drone ID observer may already be able to receive. Byte-level compatibility with ASTM F3411 was not confirmed by any Chinese source found.


- GB 42590-2023 took effect 2024-06-01; 17 requirement areas incl. electronic fencing and remote identification
- Light and small UAS must automatically broadcast ID information via WiFi or Bluetooth during flight and report via network to a management platform
- Related: https://www.techphant.cn/blog/108112.html (RemoteID monitoring equipment), https://zhuanlan.zhihu.com/p/648904833 (idME remote-ID device), http://www.cst-cb.com/cn_news/details-458.html
### DJI FPV图传系统全面解析：Wi-Fi、LightBridge、OcuSync (Full analysis of DJI FPV video links: Wi-Fi, Lightbridge, OcuSync) — Zhihu
`2/5` · Chinese · blog · 2020 · snippet  
<https://zhuanlan.zhihu.com/p/114100500>


Zhihu column describing the evolution and RF architecture of DJI links; OcuSync first used on Mavic Pro as Lightbridge upgrade, with bidirectional sensing to avoid interfered channels and adaptive video bitrate. Background for classification labels per DJI generation.


- OcuSync first shipped on Mavic Pro as an upgrade of Lightbridge
- Bidirectional 'intelligent sensing' avoids interfered channels and adapts bitrate, saving ~30% bandwidth
### 反无人机系统算法分析、计算设备硬件配置推荐 (Counter-UAS system algorithm analysis and compute hardware recommendations) — Zhihu
`2/5` · Chinese · blog · 2025 · snippet  
<https://zhuanlan.zhihu.com/p/32801277889>


Zhihu piece on C-UAS algorithm stacks (RF spectrum + radar + EO fusion, Doppler/TOA positioning) and what compute to buy. Marginal, but it frames how Chinese integrators partition detection vs classification vs localisation.


- Positioning via Doppler and TOA before directed jamming; multi-sensor fusion with radar and optics
### 大疆无人机SDR 链路 (DJI drone SDR link) — CSDN
`2/5` · Chinese · blog · 2025 · snippet  
<https://blog.csdn.net/dota51888/article/details/147770477>


Describes DJI's SDR-based transmission behaviour from the user side: three-band 'seamless' auto hopping among 2.4 GHz, 5.8 GHz and DFS (5.2 GHz) bands, automatic channel selection based on measured interference. Useful to justify scanning all three bands with the E200.


- DJI SDR link auto-switches between 2.4 GHz, 5.8 GHz and DFS bands when interference is detected
- Channel choice is driven by on-board spectrum sensing of the environment
### 我国无人机，FPV图传与遥控链路通信频段划分 (China's frequency allocation for UAV FPV video and RC links) — 创研数字通讯
`2/5` · Chinese · vendor · 2023 · snippet  
<https://www.idc-rf.com/news/1183.html>


Chinese vendor summary of the MIIT band plan for UAV links (sub-GHz, 1.4 GHz, 2.4 GHz, 5.8 GHz). Relevant because Chinese-market industrial drones may use 840.5-845 MHz / 1430-1444 MHz allocations that EU-centric scans miss; exact figures were not in the snippet and must be verified from the page.


- Describes Chinese national allocation of UAV RC/video bands (numbers not in snippet; verify by hand)
- Related: https://www.techphant.cn/blog/98863.html (choosing video-link bands)
### 教程分享 \| C-RID 无人机唯一产品识别码广播模块使用教程 (Tutorial: C-RID drone unique product identification code broadcast module) — bilibili
`2/5` · Chinese · video · 2025 · snippet  
<https://www.bilibili.com/video/BV1RRtEzvEZS>


Bilibili tutorial for a Chinese add-on 'C-RID' broadcast module implementing the GB 42590 unique-product-ID broadcast, and discussing RID/DID parsing for drone localisation. A cheap way to obtain a known-good Chinese RID transmitter for testing an AERIX receiver against Chinese-format broadcasts.


- Module broadcasts the Chinese 'unique product identification code' (唯一产品识别码) per GB 42590
- Video discusses RID and DID parsing for localisation
### 无人机测试系列：大疆精灵3遥控+图传信号实测 (Drone test series: measured DJI Phantom 3 RC + video link signals) — 面包板社区 (EET-China)
`2/5` · Chinese · forum · 2016 · snippet  
<https://mbb.eet-china.com/blog/1675150-368785.html>


Older Chinese bench measurement of a Phantom 3 RC uplink and video downlink with a spectrum analyser. Useful as a reference for legacy Lightbridge/WiFi-era signatures; details not visible in snippet.


- Spectrum-analyser measurement of Phantom 3 remote-control and image-transmission signals (details behind blocked page)
### 软件无线电SDR加人工智能算法实现无人机频谱探测 (SDR plus AI algorithms for drone spectrum detection) — CSDN
`2/5` · Chinese · blog · 2024 · snippet  
<https://blog.csdn.net/yuejich/article/details/136309170>


Chinese overview of SDR+AI drone spectrum detection: portable USRP prototypes, cyclostationary features and pseudo-Doppler for drones talking to controllers, micro-Doppler for 'silent' drones, and VITA-49 based spectrum monitoring platforms. Context piece rather than code.


- Mentions USRP-based portable prototypes using cyclostationary features and pseudo-Doppler DF
- Mentions VITA 49 spectrum monitoring platforms and fingerprint libraries with TDOA
### 侦测与反制 - 无人机防御 - 海康威视 (Detection and countermeasures — drone defence — Hikvision)
`1/5` · Chinese · vendor · 2025 · snippet  
<https://www.hikvision.com/cn/products/drone-products/udf/detection-prevention>


Hikvision C-UAS product line page: spectrum detection, EO and radar detection, then alerting and countermeasures. Marketing-level, but it is a mainstream Chinese vendor's taxonomy of a detection pipeline; the 50+ vendor list at 艾邦智飞 (https://www.aibangfly.com/a/6327) gives further names for spec-sheet mining.


- Pipeline: spectrum detection + EO + radar -> alert -> force RTH/land
- Vendor list of 50+ Chinese C-UAS suppliers at https://www.aibangfly.com/a/6327

## Russian- and Ukrainian-language sources

### Прошивка MILELRS оппонентов / Прошивка MILELRS v3.50 Руководство пользователя (Russian mirror of the Ukrainian MilELRS v3.50 user manual, in the techuav.github.io dump of the 'ТЭЧ БпЛА \| FPV' / 'ПЛАТФОРМА_FPV' Telegram channels)
`5/5` · Russian · github · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ПЛАТФОРМА_FPV/Прошивка/Прошивка_MILERLS_оппонентов.html>


Full Russian text of the Ukrainian military ExpressLRS fork (MilELRS 3.50, based on ELRS 3.5.2) as mirrored by a Russian FPV channel. It lists exactly which frequency ranges each radio chip is driven to, the CUSTOM_FREQ mechanism for arbitrary 20 MHz sub-bands, separate telemetry frequencies to hide the control channel, encryption keys, MULTI_BAND parallel links, an EW_SCANNER that sweeps e.g. 730-830 MHz, two-antenna DF of jammers and a 'DETECTOR' mode that turns an RX module into an analyser/DF for other signals. This is the single most concrete description of what frequency-agile frontline RC links look like in RF terms.


- SX1276/78 modules: bands '433' and '900', frequencies 360-560 and 720-1020 MHz; SX1280: 2100-2700 MHz; LR1121: 150-2800 MHz split into '433','900','2400', usable 150-800 and 1010-2100 MHz with reduced power
- Some SX1276 modules do not work below 740 MHz; LR1121 modules have low power in 1010-2100 MHz
- CUSTOM_FREQ=740,760,0 sets a 20 MHz operating band; third parameter is a separate telemetry frequency 'to hide the main control frequency from the enemy'; CUSTOM_FREQ2 adds a second band (e.g. 940-960) and telemetry bandwidth is half the main band
- EW_SCANNER='12,730,830' sweeps 730-830 MHz from a remote switch; EW_RSSI shows max jammer level; works best on True Diversity RX with two radio modules (e.g. Happymodel ES900 Dual)
- MilELRS can use the two antennas of a True Diversity RX to determine direction to a jammer (v2.52 'Пеленгация РЭБ'); DETECTOR (v3.40) lets an RX module analyse and DF 'PRFR' signals (details in DETECTOR.pdf, not in dump)
- MULTI_BAND duplicates the link over several parallel ExpressLRS pairs (v2.20); Gemini TX auto-switches between frequency bands (v3.20); packet rates 14/25/44/82 Hz; 2.4 GHz modes 22 Hz and 44 Hz add 6/3 dB sensitivity
- Encryption via RX_KEY/TX_KEY generated on milpilots.com; TX_LOCK prevents copying firmware; functionality co-developed with the 'Барвинок-5' team
- Listed 433-band hardware: ELRS400UA (390-500 MHz), ChDB Mk3 (410-525), LOKI_400 (365-535, 1 W), COALAS_45 (410-530, 7 W); LR1121 hardware: BVNA/Ariadna T1A0/R1A0 (1850-2050 MHz), AERONETIX LR1121 (150-700 MHz), CYCLONE LR1211_400 (370-590)

*E200:* Defines the sweep plan a European E200 toolkit needs if it wants to see frontline-derived ELRS forks: LoRa-chirp detection over 150-1100 MHz and 1.7-2.8 GHz, not just 868/915/2400; expect 20 MHz-wide hop sets anywhere in those ranges, missing or relocated telemetry, and 14-82 Hz packet cadence.

### Таблица частот VTX (VTX frequency table) - ПЛАТФОРМА_FPV, mirrored on techuav.github.io
`5/5` · Russian · doc · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ПЛАТФОРМА_FPV/Видеосвязь/Таблица_частот_VTX..html>


A consolidated channel plan for analog and digital FPV video transmitters actually sold into the Russian/Ukrainian market, from 460 MHz to 6184 MHz, including DJI O3 and Walksnail channel centres. This is the best single band list for a video-link sweep.


- Analog VTX bands listed: 460-600 MHz (8 ch), 910-1360 MHz (15 ch incl. 1258, 1280), 1405-1680 MHz (12 ch), 2290-2510 MHz (12 ch), 3310-3495 MHz, 3200-3700 MHz (A-E), 3330-3480 (BeastFPV), 3700-4150 MHz, 4500-4685 MHz, 3000-4938 MHz (bands A/B/E/F/r/P/H/U), 4867-6184 MHz
- 5.8 GHz digital rows: DJI V1 25 Mbps 5660/5695/5735/5770/5805/5878/5914/5839; DJI O3 10/20 MHz 5669/5705/5768/5804/5839/5876/5912, O3 40 MHz 5677/5794/5902; Walksnail race/25/50 Mbps rows; HDZero row follows
- Separate posts give per-model JSON channel/power tables: Foxeer Reaper Infinity 4.9-6.0 GHz 10 W 64-80 ch, RushFPV 3.3 GHz 16 ch 3.17-3.47 GHz 2 W, iFlight BLITZ 3.3 GHz 5 ch 3.25-3.37 GHz, AKK Alpha 5 W 5.3-5.9 GHz 64 ch

*E200:* Directly usable as the channel-centre table for an analog-video detector on the E200 (FM video, 15.625 kHz line structure) across 0.46-6.0 GHz, plus DJI O3 / Walksnail OFDM channel centres.

### techuav.github.io - static mirror of the Russian Telegram channels 'ТЭЧ БпЛА \| FPV', 'ПЛАТФОРМА_FPV' and 'БПЛА ВСУ' (11 470 HTML pages)
`4/5` · Russian · github · 2025 · verified  
<https://github.com/techuav/techuav.github.io>


A clonable dump (last commit 2025-08-07) of Russian frontline FPV know-how: firmware docs (MilELRS, MILPACK, TBF, G13), VTX channel tables, detector reviews (Asel, Bulat, ZOV, Skydroid S10, Dronoskop-4.7 appear thousands of times), translated Ukrainian and US counter-UAS manuals, and drone identification threads. Grep-able offline; the most efficient way to reach Telegram-only material from this lens.


- Cloned to /tmp/claude-0/-home-user-aerix-v2/8f01e3c2-dc35-5950-904f-84c7a819e91d/scratchpad/repos/techuav.github.io; branch main; docs/ maps to site root
- Contains translated 'Борьба с БПЛА' (ВСУ 2019) and 'ATP 3-01.81 Counter-UAS' (US Army 2023) manuals and the Ukrainian 2024 unmanned-systems doctrine
- Kolibri series Ukrainian FPV: MilELRS with encrypted keys, 80-channel VTX from 2.5 W (identification thread)
- Many posts on fiber-optic FPV drones (no RF emission)

*E200:* Reference corpus for band planning and for naming Russian/Ukrainian link types in a classifier taxonomy.

### Азы РЭБ, или коротко о главном (EW basics, in short) - ТЭЧ БпЛА \| FPV Telegram post mirrored on techuav.github.io
`4/5` · Russian · forum · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Азы_РЭБ_или_коротко_о_главном.html>


Russian frontline explainer on choosing jammers that, as a by-product, documents how FPV control frequencies drifted over time under EW pressure. Useful as a dated timeline of where control links actually live.


- 2022-2023: FPV used standard 850-925 MHz; in the second half (of 2023) the band widened to 750-1060 MHz
- 'At present there are not isolated cases of control on 433 MHz, and use of the 415-640 MHz range'
- Example given: a drone flying on 'ELRS 755 MHz'
- Author stresses not to confuse video-channel frequencies with control-channel frequencies; recommends studying captured hardware and keeping horizontal links with EW/SIGINT units

*E200:* Gives concrete band edges (415-640, 750-1060 MHz) for a sub-GHz LoRa/ELRS energy detector on the E200.

### Пост про цифру оппонентов: Новая цифра (Post about the opponents' digital video: OpenIPC) - ТЭЧ БпЛА \| FPV post
`4/5` · Russian · forum · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Большинство_выбрало_пост_про_цифру_оппонентов.html>


Russian analysis of Ukrainian OpenIPC-based digital FPV video units: Wi-Fi-chip video with narrowed bandwidth and the option to move to non-standard Wi-Fi bands, and the explicit claim that handheld drone detectors do not see them.


- OpenIPC serial units use RTL8812 Wi-Fi chips, which limits them to 4900-5990 MHz today
- Firmware modified so the channel bandwidth 'can even be 10 MHz'
- Same system can run on other Wi-Fi bands: 3.55-3.7 GHz or 5.925-7.125 GHz
- 'Your drone detector does not see these drones'; recommends monitoring up to 7.3 GHz with the new tinySA

*E200:* Wi-Fi-derived (OpenIPC/wfb-ng style) video with 10 MHz channels in 3.5-3.7 GHz and 4.9-6 GHz is a signal class the E200 can capture in one 20 MSPS window; 5.925-7.125 GHz is outside its range.

### Сегодня зафиксировано применение противником FPV дронов с видеопередатчиками выше 6.2 ГГц (Enemy FPV drones with video transmitters above 6.2 GHz recorded today) - ТЭЧ БпЛА \| FPV post
`4/5` · Russian · forum · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Сегодня_зафиксировано_применение_противником_FPV_дронов_с_видеопередатчиками_выше_6.2_ГГц_в_тыловых_.html>


Short frontline alert that FPV video links above 6.2 GHz are in use and that all common Russian handheld detectors are blind there. Directly relevant because the E200/AD9361 tops out at 6 GHz.


- FPV video transmitters above 6.2 GHz observed in rear areas
- 'These frequencies are above the range of all drone detectors ZOV, BULAT, H9LP, Skydroid'
- Only 'Дроноскоп 4.7' (to 7.3 GHz) or the Arinst SSA R3 spectrum analyser can see them; the channel is 'working on FPV interception 7.3+ GHz'

*E200:* The E200's 70 MHz-6 GHz tuning range cannot cover this; plan for a block downconverter or a tinySA/Arinst-class sweep companion for 6-7.3 GHz if that threat class matters.

### Passive SDR Radar Project / Система пассивного радиолокационного наблюдения на основе KrakenSDR (paired with habr article 'Как мы превратили цифровое ТВ в радар')
`3/5` · Russian · github · 2025 · verified  
<https://github.com/Stanislav-sipiko/passive-sdr-radar>


Russian-language open-source passive coherent location project using DVB-T2 (546 MHz) as illuminator with KrakenSDR + Raspberry Pi 5, aimed at UAV/missile detection. Code is a documented pipeline scaffold (capture, CAF, MTI/CFAR, DBSCAN clustering, Kalman tracker, WebSocket map) but its own TODO says real KrakenSDR data is not yet connected.


- Illuminator: DVB-T2 at 546 MHz; hardware KrakenSDR 5-channel + RPi5, GPS/PPS for sync; GPL-3.0
- Pipeline: capture/kraken_reader.py (file or UDP IQ), caf/caf.py, detect/cfar.py, postprocess morphology+clustering, track/tracker.py (Kalman + Hungarian), realtime/ws_server.py; ~2.2k lines Python; last commit 2025-10-12
- TODO: 'Подключение реальных данных с KrakenSDR', improve CFAR, target identification
- Habr 966044 (blocked here) describes it as a balcony-deployable, transmitter-less airspace monitor

*E200:* Relevant as a complementary path for RF-silent (fiber-optic) drones: the E200's two coherent RX channels (SMA + internal IPEX) could serve as reference+surveillance for a small PCL experiment reusing this CAF/CFAR structure.

### Барвінок-5 - програмно-апаратний комплекс для систем радіоуправління на базі ExpressLRS (Barvinok-5, Ukrainian military ELRS firmware/hardware complex) - Український FPV Форум
`3/5` · Ukrainian · forum · 2025 · snippet  
<https://fpvua.org/resources/barvinok-5.158>


Ukrainian FPV forum resource page for the Barvinok-5 ELRS derivative (co-developer of MilELRS features). Blocked for fetching; snippets confirm telemetry is disabled because it unmasks the control channel, dual-channel mode across two frequencies, and a backpack firmware with extended video channels. A sibling thread 'MafiaELRS' exists.


- Telemetry disabled ('telemetry unmasks the control channel')
- Two-channel mode: two transmitters and two receivers on different frequencies
- Backpack firmware with extended channel sets for the video receiver; docs at barvinok-5.notion.site
- Related thread: 'MafiaELRS' (https://fpvua.org/threads/mafiaelrs.631/)

*E200:* Downlink/telemetry-based detection can be silent; a detector must key on the ground-station uplink and on the VTX.

### Детектор видеосигнала «Чуйка 3.0» (Ukrainian analog-video detector 'Chuyka 3.0') - report mirrored on techuav.github.io
`3/5` · Russian · forum · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Украинские_каналы_сообщают_о_создании_детектор_видеосигнала_Чуйка_3.0_для_защиты_от_дронов_ВС_РФ..html>


Specification of a Ukrainian FPV video detector that displays the operator's picture; its scan bands are a useful field-derived list of where analog video actually is.


- Scan bands: 900-1680 MHz, 3060-3700 MHz and 4990-6000 MHz with parallel fast auto-scan
- Claimed range 4 km; shows up to three sources with their frequencies; audio alert grows as the drone approaches
- Works by demodulating analog video so the user sees the operator's screen

*E200:* Confirms three analog-video sweep windows (0.9-1.7, 3.06-3.7, 4.99-6.0 GHz) that fit the E200 range.

### Особенности обнаружения аналоговых видеоканалов FPV в диапазоне 4800-6200 МГц детекторами дронов (Peculiarities of detecting analog FPV video channels in 4800-6200 MHz with drone detectors) - КВАДРО КОД
`3/5` · Russian · vendor · 2025 · snippet  
<https://4code.ru/publications/band5800>


Russian detector vendor (Alissum series) technical note on analog FPV in the extended 4.8-6.2 GHz band; blocked for fetching. Snippets indicate the vendor sweeps 4800-6200 MHz in 3-5 s and uses neural-network signal-type recognition to reject Wi-Fi, and that as of early 2025 there are more than 130 FPV channels in the 5.8 GHz band.


- Alissum scans 4800-6200 MHz with signal analysis in 3-5 s
- Vendor claims neural-network recognition of UAV signal types that works in the presence of Wi-Fi and other comms signals; detects DJI, Autel, Wi-Fi drones and FPV; video in 2400/4900/5800 MHz
- Early-2025 count: over 130 FPV channels in the 5.8 GHz band; Alissum-6 19 000 RUB, ~1 km LOS, <=90 g; Alissum-8 62 000 RUB
- Companion publication 'МАТРАСЕР' describes a tool for recording the radio air with the detector (https://4code.ru/publications/matracer)

*E200:* Design target for a 4.8-6.2 GHz video detector: full-band sweep under 5 s and a Wi-Fi-vs-FPV discriminator; consider an IQ 'air recorder' mode like МАТРАСЕР for building labelled datasets.

### Приймач ELRS 433 МГц (150-700 МГц) + 2.4 ГГц (1.7-2.7 ГГц) LR1121 DBR1 ESP8285 Aeronetix (ELRS receiver 150-700 MHz + 1.7-2.7 GHz on LR1121)
`3/5` · Ukrainian · vendor · 2025 · snippet  
<https://flasharmy.com.ua/prijmach-elrs-433-mgts-150-700-mgts-2-4-ggts-1-7-2-7-ggts-lr1121-dbr1-esp8285-aeronetix>


Ukrainian retail listing of a dual-band LR1121 ELRS receiver whose stated coverage (150-700 MHz and 1.7-2.7 GHz) shows commodity hardware now supports control links far outside ISM allocations; tested with MilELRS, modified ELRS and Барвінок-5 firmware.


- Receiver combines a 150-700 MHz low-frequency subsystem and a 1.7-2.7 GHz high-frequency subsystem on ESP8285 + LR1121
- Verified to work with MilELRS, modified ELRS and Барвінок-5 firmware

*E200:* Sub-GHz LoRa detector must extend down to 150 MHz; 1.7-2.1 GHz is a plausible control band adjacent to LTE.

### Розробка та збірка детектора дронів і сканера частот відео-передавача ФПВ (Design and assembly of a drone detector and FPV video-transmitter frequency scanner) - smell.co.ua (Ukraine)
`3/5` · Ukrainian · blog · 2025 · snippet  
<https://smell.co.ua/blog/pro-bezpilotni-aparaty/rozrobka-ta-zbirka-detektora-droniv-i-skanera-chastot-video-peredavacha-fpv>


Ukrainian maker blog and small shop documenting DIY detectors: an RX5808-based 4.9-6.1 GHz video scanner with auto/manual channel search and RCA video out, controlled by an ESP32-S2 board, and a pocket 700-1020 MHz scanner (optionally extended by a 400 MHz range) that shows the detected frequency. Blocked for fetching; facts from snippets.


- Video scanner-detector works 4.9-6.1 GHz with automatic or manual active-channel search, external screen via RCA; built on RX5808 with an ESP32-S2 dev board
- Pocket scanner covers 700-1020 MHz, expandable with a 400 MHz range; scanner principle with LED/sound alert and detected frequency on a display (https://smell.co.ua/detektor-droniv-viyavlennya-signaliv-bpla/1-skaner-chastoti-700-1020-mgc-detektor-droniv.html)

*E200:* Shows the Ukrainian volunteer baseline: 700-1020 MHz plus optional ~400 MHz for control, 4.9-6.1 GHz for video.

### Скрываем аналоговый видеосигнал (Hiding the analog video signal: inverter vs scrambler) - ПЛАТФОРМА_FPV post
`3/5` · Russian · forum · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ПЛАТФОРМА_FPV/Видеосвязь/Скрываем_аналоговый_видеосигнал..html>


Shows that analog FPV video on the front is increasingly inverted or scrambled with paired encoder/decoder boxes, so a detector that relies on demodulating a recognisable picture will fail while energy/line-structure detection still works.


- Two techniques in use: video inverter (reversible quickly with another inverter) and video scrambler ('practically impossible to decode in the available time')
- Both are TX/RX pairs fitted to the VTX and VRX; the author recommends the scrambler

*E200:* Classify analog video by FM spectral signature (sync-line harmonics) rather than by picture content; decoded picture may be unusable.

### Что такое Спецсвязь Гермес? (What is 'Hermes' special comms?) - Russian proprietary FPV link, ТЭЧ БпЛА \| FPV post
`3/5` · Russian · vendor · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Что_такое_Спецсвязь_Гермес.html>


Vendor description of a Russian domestic drone/robot control link that is explicitly not an ELRS/TBS fork: own protocol with AES, IP addressing and wide frequency hopping. Relevant because ELRS/CRSF signature matching will not label it.


- 'Multi-band link on one drone/robot with FHSS up to 400 MHz'; antenna/FHSS settings up to 100 MHz
- Own protocol with IP addressing inside and AES packet encryption; 'not a fork of ELRS/TBS'
- Control and video frequencies changeable from the operator's radio via Lua script; multi-bind; hibernation ('ambush drones') and wired/airborne repeaters; modem with USB/UART/Ethernet

*E200:* A classifier needs an 'unknown wide FHSS' class; expect hop spans of 100-400 MHz that exceed a 20 MSPS capture window, so use sweep statistics rather than single-window decoding.

### Выносной видеоприемник СОВА 3.3 5.8 (Remote video receiver 'SOVA' 3.3/5.8 by Гагаринг) - ТЭЧ БпЛА \| FPV post
`2/5` · Russian · vendor · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Выносной_видеоприемник_СОВА_3.3_5.8.html>


A remote-mounted dual video receiver (3.3-3.6 GHz and 4.9-6.1 GHz) that is marketed both for FPV and as a drone detector / interceptor of other people's video, showing how 3.3 GHz video has become a standard band.


- Two receivers: 3.3-3.6 GHz and 4.9-6.1 GHz; antenna/receiver head up to 300 m from the operator over twisted pair
- Remote channel switching enables 'search/interception of others' video streams and a drone-detector function'; 40 000 RUB

*E200:* Confirms 3.3-3.6 GHz as a mandatory video sweep window.

### Детектор дронів SENSE-3 / HUNTER-3 - тридіапазонний відеосканер FPV-дронів 1.2 / 3.3 / 5.8 ГГц (Ukrainian tri-band FPV video scanners), plus 'Чатовий' FPV detector
`2/5` · Ukrainian · vendor · 2025 · snippet  
<https://www.martial.com.ua/shop/portatyvni-detektory-droniv/detektor-droniv-sense-3-trydiapazonnyj-videoskaner-fpv-droniv-1-2-3-3-5-8-hhts>


Ukrainian market listings of video-scanner detectors built from three receiver modules (1.2, 3.3, 5.8 GHz) that auto-identify active channels and show the analog picture; the militarnyi.com 2025 buyer's guide describes the same three-module architecture and lists 'Xenon-L' covering 0.9, 1.2, 2.4 and 4.9-6.0 GHz.


- HUNTER-3 / SENSE-3 / 'Чатовий': simultaneous 1.2 / 3.3 / 5.8 GHz analog video scanning with picture output
- Buyer's guide: 'FPV most often works in 1.2, 2.4, 3.3 and 5.8 GHz'; typical approach is several receiver modules scanned by a microcontroller (https://militarnyi.com/uk/special-projects/yak-vybraty-detektor-droniv-oglyad-modelej-i-klyuchovi-kryteriyi-vyboru/)
- SKYNOVA 'Перець' detector: 915 MHz, 2.4 GHz, 5.8 GHz

*E200:* Confirms 1.2 and 3.3 GHz analog video as first-class targets for a European toolkit.

### Как мы превратили цифровое ТВ в радар / Open Source проект по мониторингу воздушного пространства на SDR (How we turned digital TV into a radar)
`2/5` · Russian · blog · 2025 · snippet  
<https://habr.com/ru/articles/966044>


Habr write-up of the passive-sdr-radar project above; blocked for fetching but the snippet gives the design rationale (DVB-T2 OFDM as a strong known illuminator, KrakenSDR + RPi5 cost like a router, networks of passive receivers).


- Uses DVB-T2 signal at 546 MHz as a stable, powerful, known-structure OFDM illuminator
- KrakenSDR and Raspberry Pi 5; project is fully open source at github.com/Stanislav-sipiko/passive-sdr-radar

*E200:* Background for a passive-radar side experiment; not RF-signature based.

### Нестандартные частоты FPV: как выбрать VTX для обхода помех (Non-standard FPV frequencies: choosing a VTX to evade interference) and 'FPV-видеосистема на 1,2-1,3 ГГц' (dronoagregator.ru)
`2/5` · Russian · blog · 2025 · snippet  
<https://modelistam.com.ua/nestandartnye-chastoty-kak-vybrati-dlya-obhoda-pomeh-a-365>


Hobby-market articles that spell out the 1.2/1.3 GHz analog channel range and that 700-750 MHz control is 'a new promising direction' for long-range FPV.


- 1.2-1.3 GHz gear channels range 1080-1360 MHz with 1256 and 1280 MHz the most popular; '1.2' and '1.3' equipment use different grids
- 700-750 MHz described as a new direction for long-range FPV control (r202x.com)

*E200:* Channel edges for 1.2 GHz video detection.

### Портативный всенаправленный детектор дронов 'Булат' v.3: обзор модели (Review of the 'Bulat' v3 omnidirectional detector), plus Uralsistems 'Булат v4' review and f9.market 'Сокол-10' listing
`2/5` · Russian · vendor · 2025 · snippet  
<https://4vision.ru/blog/portativnyj-vsenapravlennyj-detektor-dronov-bulat-v3-obzor-modeli>


Russian reviews/listings of the mass-market handheld detectors (Bulat, Asel, Sokol-10/Skydroid S-10) that give claimed ranges and a field test with an ELRS 915 MHz + 5.8 GHz video FPV where the 5.8 GHz reaction was late.


- Bulat: detection up to 1.5 km, up to 15 h autonomy; in a test with 5.8 GHz video + 915 MHz ELRS the 5.8 GHz response was delayed
- Sokol-10 (Skydroid S-10): 300 MHz-6 GHz
- Bulat v4 quick guide PDF: https://static.insales-cdn.com/files/1/2222/36325550/original/detektor-bpla-bulat-v4_quickguide_main.pdf; Bulat v4 review https://uralsistems.ru/blog/bulat-v4-obzor-tehnicheskih-harakteristik-i-vozmozhnostej

*E200:* Latency benchmark: per-band sweep dwell must catch a 5.8 GHz analog carrier within a second or two.

### Спектроанализатор Мастерок-4 / детектор Тень (Russian 'Masterok-4' spectrum analyser and 'Ten' detector) - ТЭЧ БпЛА \| FPV post
`2/5` · Russian · forum · 2025 · verified  
<https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/РЭР_и_подразделениям_про_борьбе_с_дронами_-_изделие_спектроанализатор_радиодиапазона_Мастерок-4_от_О.html>


Shows the upper frequency limits Russian units now consider necessary for detectors (7.2-10 GHz) and that vendors promise DF, networking and a laptop mode.


- Masterok-4 (OKB 'Чистое небо') extended upper range: 300 MHz to 7.2 GHz
- 'Тень' detector covers 100 MHz to 10 GHz; promises DF, networked operation and use as a laptop front-end (@detectordronov)

*E200:* Benchmark for coverage expectations; E200 covers 0.07-6 GHz only.

### Drone-Finder-ELRS - Drone finder ELRS for TX15 (EdgeTX Lua script using ELRS/CRSF RSSI and LQ), surfaced via Ukrainian FPV forum thread 'Lua скрипт для пошуку дрона за RSSI'
`1/5` · English · github · 2026 · verified  
<https://github.com/p3gass/Drone-Finder-ELRS>


Small GPL-3 Lua script that turns a Radiomaster TX15 into a Geiger-style RSSI/LQ finder for a lost ELRS drone. Marginal for detection, but illustrates that the Ukrainian scene reads RSSI/LQ from the ELRS link itself.


- Uses ELRS/CRSF telemetry RSSI and LQ with audio feedback intensifying toward the drone; EdgeTX on TX15; GPL-3.0

*E200:* Marginal.

### Макет пеленгатора на основе SDR-технологии (Prototype direction finder based on SDR technology) - CyberLeninka; also 'Обнаружение беспилотных летательных аппаратов: существующие решения и возможности'
`1/5` · Russian · paper · 2024 · snippet  
<https://cyberleninka.ru/article/n/maket-pelengatora-na-osnove-sdr-tehnologii>


Russian open-access papers on SDR direction finding and a survey of UAV detection methods (radar, RF, EO, acoustic). Only abstracts reachable; no code or datasets found.


- Survey article covers radar, radio/radio-technical, electro-optical and acoustic detection (https://cyberleninka.ru/article/n/obnaruzhenie-bespilotnyh-letatelnyh-apparatov-suschestvuyuschie-resheniya-i-vozmozhnosti)
- 'Разработка архитектуры нейронной сети для восстановления радиосигнала с БПЛА' uses a variational autoencoder trained on RadioML 2018.01A, not on drone data

*E200:* Low; Russian academic RF-ML work found here reuses Western datasets and does not publish code.

### Сигнализатор приближающегося квадрокоптера (Approaching-quadcopter alarm) - AlexGyver Community thread
`1/5` · Russian · forum · 2025 · snippet  
<https://community.alexgyver.ru/threads/signalizator-priblizhajuschegosja-kvadrokoptera.7280>


Long Russian hobby-electronics thread on DIY drone alarms; repeatedly surfaces for RX5808+Arduino 5.8 GHz detectors, nRF24L01-based 2.4 GHz sniffers and ESP32-S2 controllers. Blocked for fetching; only snippet-level detail.


- Existing 5.8 GHz detector projects on RX5808 with Arduino; an ESP32-S2 board used as controller
- Simple Arduino + nRF24L01 detectors with open firmware capture 2.4 GHz control signals and alert by sound/LED

*E200:* Marginal; documents the RSSI-only baseline.


## Regulation and Remote ID

### "Een bijzondere inspanning" — ITenRecht case document on art. 139c lid 2 sub 1 Sr (legal interpretation of 'special effort')
`5/5` · Dutch · doc · snippet  
<https://www.itenrecht.nl/documents/ecli/56e8eb1b-5a94-40f9-9451-3e83c35ff8c2.pdf>


A Dutch court/legal document (ECLI-linked PDF hosted by ITenRecht) discussing what counts as 'bijzondere inspanning' under art. 139c lid 2 sub 1 Sr. Per the search snippet, signals via the ether are in principle free and receiving/recording them is in principle permitted, but no longer when a special effort is made, 'which is the case if the tapping or recording occurs systematically and the receiving device consists of more than one apparatus'. That reading directly affects a networked, always-on, multi-node RF monitoring system.


- Snippet: intent of art. 139c lid 2 sub 1 Sr is that ether signals are in principle free, so tapping/recording via a radio receiver is in principle permitted
- Snippet: it is no longer permitted once a special effort is made, which is the case when tapping/recording is systematic and the receiving installation consists of more than one apparatus
- Domain blocked for fetch; the exact facts of the case (which signals, which equipment) are unverified

*E200:* A multi-node AERIX SDR network that systematically records private control/video/telemetry link content could be argued to be a 'bijzondere inspanning'; Remote ID and DroneID beacons are broadcast by design (and RID is legally mandated to be receivable by anyone), so they sit far more safely inside the exemption.

### Art. 139c Wetboek van Strafrecht — Aftappen gegevens die worden overgedragen via telecommunicatie (Dutch Criminal Code art. 139c, interception of telecom data)
`5/5` · Dutch · standard · 2018 · snippet  
<https://maxius.nl/wetboek-van-strafrecht/artikel139c>


The Dutch criminal provision that governs interception/recording of data transmitted via telecommunications. Lid 1 criminalises intentional and unlawful tapping or recording of data not intended for you; lid 2 sub 1 exempts data received with a radio receiver unless a 'bijzondere inspanning' (special effort) was made or a not-permitted receiving device was used. This is the pivot on which passive drone-RF reception in NL turns.


- Lid 1: up to 2 years imprisonment or fine for intentionally and unlawfully tapping/recording, with a technical aid, data not intended for you that is transmitted via telecommunications or an automated work
- Lid 2 sub 1: lid 1 does not apply to data received via a 'radio-ontvangapparaat', unless a 'bijzondere inspanning' was made to enable reception or a 'niet toegestane ontvanginrichting' was used
- Search summary: intercepting encryption keys or spoofing a MAC address are given as examples of 'special effort' that would remove the exemption

*E200:* Passive reception and decoding of unencrypted drone links and Remote ID with an off-the-shelf SDR falls under the lid-2 radio exemption in principle; the exemption is the design constraint for AERIX's future_sdr class.

### The process of encrypting DJI DroneID has commenced (Aerial Defence)
`5/5` · English · vendor · 2024 · snippet  
<https://www.aerial-defence.com/the-process-of-encrypting-dji-droneid-has-commenced>


Counter-drone vendor post reporting that from January 2024 DJI began encrypting the DroneID signal on newer models (Mavic 3 series, Mini 4 Pro, Avata) once updated to the latest firmware, and that AeroScope owners were invited from about November 2023 to install a firmware update plus an 'AeroScope Upgrade Module' dongle (EA500) whose function includes decrypting the new signal. If accurate, open DroneID decoders lose the newest DJI drones.


- From January 2024 DJI encrypts DroneID on newer models (Mavic 3 Series, Mini 4 Pro, Avata) when on latest firmware
- Since ~November 2023 AeroScope users are offered an internal SDR firmware update plus an upgrade module dongle (EA500) that decrypts the new signal
- AeroDefense (aerodefense.tech) independently reports the encryption renders many AeroScope-style detectors ineffective for new DJI drones

*E200:* Sets expectations for proto17/DroneSecurity-style decoders on the E200: they will work for older DJI models/firmware but not for encrypted DroneID; detection (energy/burst signature) still works, decoding does not. Do not attempt decryption (art. 139c 'bijzondere inspanning').

### opendroneid/wireshark-dissector — Dissector of Open Drone ID broadcast protocol for Wireshark
`5/5` · English · github · verified  
<https://github.com/opendroneid/wireshark-dissector>


Lua dissector for Wireshark decoding Open Drone ID over Wi-Fi Beacon, Wi-Fi NAN and Bluetooth 4 (BT5 'next', but sample BT5 long-range pcapng is included and code has BT5 offsets). The README documents a capture setup using a monitor-mode Wi-Fi adapter and a Nordic nRF52840 dongle with sniffer firmware for BT4 and BT5 Coded PHY. Ships sample captures usable as unit-test vectors.


- Constants in opendroneid-dissector.lua: ASTM_UUID = 0xfffa, ODID_APP_CODE = 0x0d; Wi-Fi OUIs asdstan FA:0B:BC and parrot 90:3A:E6; NAN attribute strings 04 09 50 6f 9a 13 and 88 69 19 9d 92 09
- BT5 long-range frames add 5 bytes to field offsets; HCI extended advertising adds 17 (BT5_OFF_ADDER = 17)
- Sample files: odid_wifi_sample.pcap, odid_wifi_bcn_sample.pcap, odid_bt5_lr_sample.pcapng
- Bluetooth capture validated with the nRF52840 dongle: select 'Find auxiliary pointer data' and 'Scan and follow devices on LE Coded PHY' for BT5 long range

*E200:* Sample pcaps give ground-truth test vectors for a decoder; the nRF52840 setup is the pragmatic BLE companion to an E200 that handles Wi-Fi.

### ASD-STAN Direct Remote ID — Introduction to the European digital RID UAS Standard (whitepaper PDF)
`4/5` · English · doc · 2021 · snippet  
<https://cms.stan-shop.org/uploads/2024/01/ASD-STAN_DRI_Introduction_to_the_European_digital_RID_UAS_Standard.pdf>


The official ASD-STAN whitepaper summarising prEN 4709-002 (Direct Remote Identification). It explains the message set (Basic ID, Location, System, Operator ID, Self ID, Authentication, Message Pack) and the Bluetooth/Wi-Fi transports chosen for Europe. Blocked domain; the opendroneid-core-c README (verified) reproduces its key mandatory/optional choices.


- prEN 4709-002 developed by ASD-STAN to meet Delegated Regulation 2019/945 and Implementing Regulation 2019/947
- Defines broadcast methods (Bluetooth and Wi-Fi) compatible with ASTM F3411 v1.1
- Defines 6 messages plus a 7th Message Pack used on Wi-Fi NAN, Wi-Fi Beacon and Bluetooth Long Range extended advertising

*E200:* Primary reference for the EU message formats to implement in a decoder.

### Commission Implementing Decision (EU) 2024/2103 of 30 July 2024 on the harmonised standard for direct remote identification of unmanned aircraft (in support of Delegated Regulation (EU) 2019/945)
`4/5` · English · standard · 2024 · snippet  
<https://eur-lex.europa.eu/eli/dec_impl/2024/2103/oj>


Publishes in the Official Journal, 'with restriction', the reference of the harmonised standard for direct remote identification (the CEN/ASD-STAN EN 4709-002 line) supporting Regulation 2019/945. This gives EN 4709-002 presumption-of-conformity status for C-class drones and is the formal EU anchor for the Wi-Fi Beacon / NAN / BLE transports the receiver must implement.


- Decision dated 30 July 2024; entered into force on the day of OJ publication
- Publishes the DRI harmonised standard reference 'with restriction' (restriction text not retrieved)
- Drafted in support of Delegated Regulation (EU) 2019/945 (class marks C0–C6)

*E200:* Sets the normative transport set (EN 4709-002) an EU RID receiver must cover.

### De Wet Computercriminaliteit: Aftappen van gegevens (Arnoud Engelfriet, Ius Mentis) — Computer Crime Act: interception of data
`4/5` · Dutch · blog · snippet  
<https://www.iusmentis.com/beveiliging/hacken/computercriminaliteit/aftappengegevens>


Well-known Dutch IT-law explainer on art. 139c Sr and related provisions. Explains the radio-reception exemption and gives concrete examples of what removes it (special effort such as obtaining encryption keys, MAC spoofing). Useful plain-language baseline for a legal note in the AERIX repo.


- Explains that data received by radio is exempt unless special effort or an unauthorised receiver is used
- Gives interception of encryption keys and MAC-address spoofing as examples of 'special effort'
- Search results also cite ECLI:NL:RBROT:2016:5814 (TorRAT) and ECLI:NL:RBROT:2011:BU6142 as 139c case law (not drone-specific)

*E200:* Implies: do not attempt to break encryption (e.g. DJI's post-2024 encrypted DroneID) or impersonate devices; stick to decoding what is transmitted in the clear.

### Nieuwe richtlijn: politie mag drones verstoren, overnemen en zelfs neerschieten (Dronewatch) — New directive: police may jam, take over and even shoot down drones
`4/5` · Dutch · blog · 2026 · snippet  
<https://www.dronewatch.nl/2026/03/17/nieuwe-richtlijn-politie-mag-drones-verstoren-overnemen-en-zelfs-neerschieten>


News on the Dutch Minister of Justice and Security's temporary counter-drone policy framework (Staatscourant 2026 nr. 2035, 17 March 2026). It lists which means police and Defence may use against unwanted drones, from landing to signal disruption, take-over and use of firearms; it applies retroactively from 19 December 2025 until 1 July 2026 while permanent legislation is examined. Establishes that active counter-measures are a state monopoly.


- Temporary policy framework published by the Minister of Justice and Security; retroactive from 19 December 2025, valid until 1 July 2026
- Explicitly enumerates means for police and Defence: landing a drone, disrupting signals, taking over, use of a firearm
- Prompted by a rapid increase in drone incidents; permanent embedding in law is being examined

*E200:* Confirms the project boundary: AERIX/E200 must stay receive-only; jamming, spoofing or take-over are reserved for authorities. Detection output could be a feed for those authorities.

### cyber-defence-campus/droneRemoteIDSpoofer — Bluetooth and Wi-Fi based Drone Remote ID spoofer (ASD-STAN) demonstrating protocol security limitations
`4/5` · English · github · verified  
<https://github.com/cyber-defence-campus/droneRemoteIDSpoofer>


Research tool showing that ASD-STAN/ASTM Remote ID broadcasts can be forged with a monitor-mode Wi-Fi adapter and a standard BLE HCI adapter, and that spoofed drones show up in commercial receivers including DJI AeroScope and OpenDroneID apps. The protocol has no authentication or integrity, which is a design fact for any observation network ingesting RID.


- Spoofs Wi-Fi Beacon (802.11 beacon frames, monitor mode) and BLE (HCI advertisements), independently or simultaneously
- 'The protocol itself does not provide authentication or cryptographic integrity'
- Spoofed drones appear on compliant receivers including DJI AeroScope and OpenDroneID applications; implements ASTM F3411-19/22

*E200:* AERIX should carry a trust/plausibility score per RID observation and can use the E200's independent RF-link detection (DroneID/OcuSync/ELRS energy) to corroborate or flag spoofed RID.

### nccgroup/Sniffle — A sniffer for Bluetooth 5 and 4.x LE (TI CC26x2/CC1352 firmware)
`4/5` · English · github · verified  
<https://github.com/nccgroup/Sniffle>


Hardware (not SDR) BLE sniffer firmware for cheap TI CC26x2/CC1352 boards and Sonoff dongles that supports all BT5 PHYs including Coded PHY, follows extended-advertising auxiliary pointers, and can capture advertisements on all three primary channels. Recommended by the opendroneid project for receiving RID; the practical way to cover BT5 long-range RID next to an E200.


- 'Support for all BT5 PHY modes (regular 1M, 2M, and coded modes)'; -l uses long range (coded) PHY for primary advertising
- -e enables following auxiliary pointers in Bluetooth 5 extended advertising
- Captures advertisements from a target MAC on all three primary advertising channels with a single sniffer; PCAP export and Wireshark plugin
- Hardware: CC26x2R, CC2652RB, CC1352R/P Launchpads, SONOFF CC2652P USB Dongle Plus, Catsniffer V3

*E200:* Complements the E200: E200/openwifi for Wi-Fi Beacon RID, a ~15 EUR Sonoff CC2652P dongle with Sniffle for BLE4/BLE5-coded RID.

### Drone Scanner (Dronetag help) — Remote ID scanner app documentation
`3/5` · English · vendor · snippet  
<https://help.dronetag.com/drone-scanner>


Help page for the open-source Drone Scanner app (Dronetag). Documents that it decodes BT4, BT5, Wi-Fi Beacon and Wi-Fi NAN, that on iOS Apple's restrictions prevent Wi-Fi scanning so the app 'won't pick up DJI drones using Wi-Fi', and that Android reception depends on the device's scan refresh rate. Confirms from the receiver side that DJI is Wi-Fi-based.


- App examines RID broadcast via Bluetooth 4, Bluetooth 5, Wi-Fi Beacon and Wi-Fi NAN
- On iOS the app cannot receive Wi-Fi RID and therefore does not see DJI drones using Wi-Fi
- Dronetag Beacon add-on transmits over Bluetooth with up to 3 km range (vendor claim)

*E200:* Reinforces the two-path receiver design: Wi-Fi Beacon (DJI, Parrot) plus BLE5 coded (add-on modules).

### GB 42590-2023 民用无人驾驶航空器系统安全要求 (Civil unmanned aircraft system safety requirements) — 国家标准全文公开系统
`3/5` · Chinese · standard · 2023 · snippet  
<https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=0DC41035BA23EF2C5B94E6482492AF1E>


China's first mandatory national standard for micro/light/small civil drones (published 2023-05-23, effective 2024-06-01) with 17 technical requirements including geofencing and remote identification. Light and small UA must report identification to the state supervision platform over the network and automatically broadcast identification via Wi-Fi or Bluetooth in flight; secondary sources say the broadcast follows ASTM F3411-22a message content.


- Published 2023-05-23, implemented 2024-06-01; newly manufactured micro/light/small drones needed RID from 1 Jan 2024 per xktest/sohu summaries
- Remote ID: network reporting to the integrated supervision service platform plus automatic Wi-Fi or Bluetooth broadcast during flight
- luolitao/remoteid (verified) shows GB 42590 broadcast shares OUI FA:0B:BC with ASTM but uses protocol-version nibble 1 and a 12-bit direction field

*E200:* Chinese-market DJI/other drones imported to NL with China firmware may broadcast this format; parse it alongside ASTM.

### Nieuwe wetgeving op gebied van afluisteren (evel.nl scanner-hobby page) — New legislation on listening-in
`3/5` · Dutch · forum · snippet  
<https://www.evel.nl/aflwet.htm>


Hobbyist scanner-community page summarising Dutch listening law. States that listening to everything transmitted over the air is allowed, including encoded data traffic and even decoding it, but information may not be passed to third parties and recording/saving is not permitted. Community discussions linked in the same search disagree on the decoding point, so treat as an informal, possibly dated, position.


- Claims: receiving and listening to everything over the air with scanners/receivers is permitted in NL, including decoding encoded data
- Claims: information obtained may not be shared with third parties; recording/saving is not permitted; criminal activity must be reported
- Snippet notes conflicting community interpretations on whether decoding encoded broadcasts is legal

*E200:* The 'no recording / no sharing' claim, if it reflects current law (unverified), would conflict with an observation network that stores and distributes decoded link content; it does not obviously conflict with storing RID broadcasts.

### Remote ID for drones mandatory in EU since 2024 (skyzr)
`3/5` · English · blog · 2024 · snippet  
<https://www.skyzr.com/en/drone-laws/remote-id-for-drones-mandatory-in-eu-since-2024>


Summarises the EU obligation: from 1 January 2024 drones marked C1, C2, C3 (and C5/C6) in the Open category and any drone flown in the Specific category below 120 m must have an active, updated Remote ID; drones under 250 g without a camera and toys are exempt. It also claims a 1 January 2026 end of transition making RID mandatory for all drones over 250 g regardless of class mark, which I could not verify against EU law and consider doubtful.


- From 1 Jan 2024: C1/C2/C3 class-marked drones and Specific-category operations below 120 m must operate with active DRI
- Exempt: drones < 250 g without a camera/sensor capturing personal data, and toys
- Unverified claim: from 1 Jan 2026 RID mandatory for all drones > 250 g regardless of class marking

*E200:* Defines which drones over NL should be emitting RID at all; legacy (no class mark) drones in Open category and C0 drones may legally be silent, so RF-link detection remains necessary.

### Remote ID via WiFi vs. Bluetooth (MavicPilots forum thread)
`3/5` · English · forum · snippet  
<https://mavicpilots.com/threads/remote-id-via-wifi-vs-bluetooth.143189>


User discussion establishing that DJI implements Remote ID over Wi-Fi (Wi-Fi Beacon) rather than Bluetooth on models such as the Mini 3, and that since 2017 DJI drones have additionally emitted the proprietary AeroScope beacon (DroneID). Combined with the Drone Scanner help page and the DJI forum thread on NAN, it fixes the transport an EU receiver must prioritise for DJI.


- Many DJI drones, including the Mini 3, use Wi-Fi for Remote ID
- Since 2017 DJI drones broadcast a proprietary beacon receivable only by AeroScope
- Related DJI forum thread (forum.dji.com/thread-279235): a user received EASA-format RID from a Mini 3 Pro via Wi-Fi NaN, which appears disabled in a later firmware; MavicPilots thread 151947 says RID on the Mini 3 is turned off in Europe

*E200:* Wi-Fi Beacon on 2.4 GHz channel 6 is the must-have RID path for DJI in NL; BLE-only sniffing would miss DJI.

### Remote Identification in Europe: All you need to know (Dronavia)
`3/5` · English · vendor · 2024 · snippet  
<https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union>


Vendor explainer (RID add-on maker) on EU direct remote identification. States DRI has been mandatory since 1 January 2024 per EN 4709-002, integrated natively by DJI/Parrot or via add-on modules, for class-marked C1–C6 drones in Open and for all Specific-category operations. Also notes France's separate 'double identification' regime.


- DRI mandatory in the EU since 1 January 2024 in accordance with EN 4709-002
- Applies to all drones in the Specific category and all class-marked C1/C2/C3/C4/C5/C6 drones in the Open category
- Compliance either native (DJI, Parrot) or via add-on broadcast modules

*E200:* Add-on modules (Dronetag, Dronavia) typically use BLE, so an EU receiver must not be Wi-Fi-only.

### Vergunningen voor drones en modelvliegtuigen — Rijksinspectie Digitale Infrastructuur (RDI) (Licences for drones and model aircraft)
`3/5` · Dutch · doc · snippet  
<https://www.rdi.nl/onderwerpen/vergunningen-en-registraties/luchtvaart/onbemande-luchtvaartuigen-en-drones>


RDI (formerly Agentschap Telecom) is the Dutch frequency regulator and supervisor. The page and sibling pages cover licensing of drone transmit frequencies, licence-free use, and the requirement for a permit for X-band radar used for drone detection. No RDI page found that addresses receive-only SDR monitoring specifically.


- RDI regulates and controls Dutch frequency use, sets guidelines, grants permits and monitors
- Radar-based drone detection uses its own frequency and requires an RDI permit (X-band example)
- Sibling page 'Vergunningvrij frequentiegebruik' covers licence-free use; no statement on passive receivers found

*E200:* Passive E200 reception needs no RDI frequency licence as far as found (uncertain: no explicit RDI statement located); any active radar or transmit experiments would.

### cyber-defence-campus/RemoteIDReceiver — Web application to monitor drones based on Remote ID over WiFi and Bluetooth (Swiss Cyber-Defence Campus)
`3/5` · English · github · verified  
<https://github.com/cyber-defence-campus/RemoteIDReceiver>


Proof-of-concept Remote ID monitoring platform from the Swiss armasuisse Cyber-Defence Campus: Python backend (REST + WebSocket) plus Vue/MapLibre frontend, capturing Wi-Fi beacons from a monitor-mode adapter with full ASD-STAN message-type support; BLE and NAN listed as future work. Architecturally close to what an AERIX future_sdr node would need.


- Requires a Wi-Fi adapter in monitor mode; currently Wi-Fi beacons only
- Full support for all ASD-STAN (prEN 4709-002) Remote ID message types
- Explicitly 'a proof of concept and is not intended for production use'

*E200:* Reusable parsing/back-end pattern; input could be pcap from openwifi on the E200 instead of a USB adapter.

### opendroneid/receiver-android — Example Android receiver application for Remote ID
`3/5` · English · github · verified  
<https://github.com/opendroneid/receiver-android>


Reference Android receiver for BT4, BT5 long range, Wi-Fi NAN and Wi-Fi Beacon, compliant with ASTM F3411 and ASD-STAN prEN 4709-002. Its README documents why phones are poor RID sensors (Wi-Fi beacon scan throttling on Android 8+, BT5 coded PHY only on few chipsets), which motivates a dedicated SDR/monitor-mode receiver.


- Wi-Fi Beacon scanning is throttled by default on Android 8+; must be disabled in developer options
- BT5 Long Range/Extended Advertising reception reliable only on some phones (Samsung Galaxy S10, Huawei Mate 20 Pro named); others pause due to power saving
- Wi-Fi NAN reception tested on Samsung Galaxy S10

*E200:* Justifies an always-on infrastructure receiver over phone apps for the AERIX network.

### С марта подключение гражданских дронов к системе «ЭРА-ГЛОНАСС» будет обязательным (Interfax) — From March, connecting civil drones to ERA-GLONASS becomes mandatory
`3/5` · Russian · other · 2026 · snippet  
<https://www.interfax.ru/russia/1071959>


Russian news on Government Decree No. 83 of 2 February 2026 (Ministry of Transport): from 1 March 2026 civil UAVs over 250 g must carry remote-identification equipment that forms and transmits an identification index, aircraft category, altitude and coordinates to the operator of the state system ERA-GLONASS. ComNews adds that AO GLONASS is testing a hybrid 'Russian DroneID analogue' for areas without cellular coverage and that ERA-GLONASS ingests cellular, satellite, hybrid trackers and ADS-B. No Bluetooth/Wi-Fi broadcast standard was found, so Russian RID is network-based, not locally receivable.


- Decree No. 83 of 2 Feb 2026: mandatory ERA-GLONASS connection for civil drones > 250 g from 1 March 2026
- Data transmitted: identification index, category, flight altitude, coordinates, to the ERA-GLONASS operator (network path)
- ComNews (comnews.ru/content/244060): AO GLONASS testing a hybrid remote-ID 'analogue of DroneID' for zones without cellular; system accepts cellular, satellite, hybrid trackers and ADS-B (АЗН-В)

*E200:* Russian-registered drones should not be expected to emit ODID-style broadcasts; nothing for the E200 to decode beyond generic RF-link detection (and possibly ADS-B 1090 MHz if a hybrid tracker uses it, unverified).

### FAQs about FAA Remote ID Compliance (DJI Support)
`2/5` · English · vendor · snippet  
<https://support.dji.com/help/content?customId=en-us03400007747&spaceId=34&re=US&lang=en>


DJI's FAQ on the FAA rule (14 CFR Part 89). Together with the ASTM pages it establishes that the US means of compliance is ASTM F3411-22a overlaid by ASTM F3586-22, that enforcement began 16 March 2024, and that firmware-upgraded drones must carry the label 'ASTM F3411-22a-RID-B'. Relevant mainly because US-configured DJI drones broadcast protocol version 2 with Session ID/serial and operator position.


- ASTM F3586-22 is an overlay to F3411-22a identifying mandatory portions for 14 CFR Part 89 (store.astm.org/f3586-22.html)
- FAA enforcement of operator RID requirements began 16 March 2024 after a grace period
- Drones upgraded via firmware must be labelled 'ASTM F3411-22a-RID-B'

*E200:* Same wire format as EU (protocol version 2), so one decoder covers FAA- and EU-configured drones.

### JiaoXianjun/BTLE — BLE (Bluetooth Low Energy) SDR sniffer/transmitter for HackRF and bladeRF
`2/5` · English · github · verified  
<https://github.com/JiaoXianjun/BTLE>


Older SDR BLE implementation (same author as openwifi) implementing the 1 Mbps GFSK PHY for all advertising and data channel packet formats, with connection-following. Only 1M PHY, so unusable for BT5 long-range RID; included to close the question of whether any SDR tool decodes Coded PHY.


- Implements 'BLE standard 1Mbps GFSK PHY' only; all ADV and DATA channel packet formats of Core v4.0
- Supported hardware: HackRF (primary) and bladeRF (compile flag); no Coded PHY or 2M PHY

*E200:* Reference code only; would need porting to E200 IQ and would not cover EU BT5 long-range broadcasts.


## Signal parameter references

### CubePilot docs: Herelink Wireless Communication (GitHub source)
`4/5` · English · doc · 2024 · verified  
<https://github.com/CubePilot/cubepilot-docs/blob/master/herelink/herelink-user-guides/wireless-communication.md>


Source markdown of the Herelink settings page; enumerates the selectable downlink and uplink channel bandwidths, which are LTE-like (1.4/10/20 MHz), and the hopping switch.


- Downlink modes DL_10M / DL_20M; uplink modes UL_1.4M / UL_10M / UL_20M; 1.4 MHz preferred under heavy interference
- Downlink signal hopping switch selects the best working frequency automatically; fixed-frequency selection also possible

*E200:* Herelink shares LTE-numerology widths with OcuSync; distinguishing them needs the centre-frequency plan (2409–2462 MHz only) and probably CP/ZC pattern differences.

### Phantom 3 Lightbridge Frequencies (PhantomPilots forum)
`4/5` · English · forum · 2015 · snippet  
<https://phantompilots.com/threads/phantom-3-lightbridge-frequencies.51693>


Forum measurements/firmware tables of the Phantom 3 Pro/Lightbridge 2 downlink channel plan and the separate control-link band. Best available numbers for the Lightbridge 2 row.


- Video downlink in ~10 MHz wide channels from 2280 to 2600 MHz = 32 channels (CH1 2.285 GHz ... CH32 2.595 GHz); only the 2400–2483 subset is legal/used in stock firmware
- Control (uplink) is ~1–2 MHz wide and hops only within 2400–2490 MHz
- Lightbridge/LB2 used on Phantom 3 Pro/Adv, Phantom 4, Inspire 1, M100/M600; OFDM downlink

*E200:* A 10 MHz OFDM downlink with 1–2 MHz FHSS uplink is a distinct pair signature from OcuSync's 1.4/3 MHz LTE-like uplink packets.

### [FPV] Analysis of TBS Crossfire, reverse engineering the air link (g3gg0.de)
`4/5` · English · blog · 2021 · snippet  
<https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire>


The blog write-up behind the sniffer: SPI-sniffed the PIC32→SX1272 registers to recover modulation and hop sequence. Confirms the 150 Hz mode is FSK and only the 50 Hz mode is LoRa. Page itself is blocked; numbers come from search snippets and agree with the code.


- 150 Hz mode: FSK with 42.48 kHz frequency shift and 85.1 kBaud
- 50 Hz mode uses LoRa; 150 Hz FSK does not reach LoRa range
- Receiver is PIC32 + SX1272; hop sequence read from register writes; RACE modes stay on one channel, hopping uses channels 0–99
- Protocol offers no security against eavesdropping

*E200:* Confirms Crossfire is decodable passively at both rates (FSK demod for 150 Hz, LoRa SF/BW to be measured for 50 Hz).

### hd-zero/hdzero-vtx src/dm6300.c and src/common.h (HDZero channel table)
`4/5` · English · github · 2024 · verified  
<https://github.com/hd-zero/hdzero-vtx/blob/main/src/dm6300.c>


Firmware for the HDZero DM6300 VTX; frequencies[] and freq_tab[] enumerate exactly which 5.8 GHz centre frequencies an HDZero transmitter can use. Combined with the ~27 MHz channel width this yields the HDZero row of the table.


- Race band R1–R8: 5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917 MHz
- E1 5705 MHz; Fatshark F1 5740, F2 5760, F4 5800 MHz
- Low band L1–L8: 5362, 5399, 5436, 5473, 5510, 5547, 5584, 5621 MHz
- Only 20 discrete channels exist; VTX chip is DM6300 (DM5680 on older units)

*E200:* A 27 MHz-wide HDZero carrier centred on one of 20 known frequencies exceeds the 20 MSPS host stream; detect by energy/edge in a 20 MHz window and tag by nearest table entry.

### rx5808-pro-diversity channels.cpp (analog 5.8 GHz A/B/E/F/R/L table)
`4/5` · English · github · 2019 · verified  
<https://github.com/sheaivey/rx5808-pro-diversity/blob/master/src/rx5808-pro-diversity/channels.cpp>


Canonical 5.8 GHz analog FPV band table as used by RX5808 receivers; gives all 40 centre frequencies of bands A, B, E, F(atshark), R(aceband) and L(ow).


- Band A: 5865 5845 5825 5805 5785 5765 5745 5725 MHz
- Raceband: 5658 5695 5732 5769 5806 5843 5880 5917 MHz (37 MHz spacing)
- Low band: 5362 5399 5436 5473 5510 5547 5584 5621 MHz
- Bands B/E/F occupy 5733–5905 MHz with 19–20 MHz spacing

*E200:* Analog FM video needs ~8–10 MHz of the 20 MSPS window per channel; scanning 40 channels at 20 MHz steps takes ~30 retunes.

### Autel EVO MAX 4T: Autel SkyLink 3.0 technology (Autelpilot)
`3/5` · English · vendor · 2023 · snippet  
<https://www.autelpilot.com/blogs/news/autel-evo-max-4t-autel-skylink-3-0-technology>


Vendor blog with the only band/throughput numbers found for Autel SkyLink 2.0 and 3.0. No channel width or OFDM parameters; FCC reports (blocked) would supply them.


- SkyLink 3.0 (EVO Max 4T): 6 antennas, 4 bands 900 MHz / 2.4 / 5.2 / 5.8 GHz auto-switched, 1080p60, 64 Mbps, <150 ms, 20 km
- SkyLink 2.0 (EVO II series, Smart Controller SE): 2.4 / 5.8 / 900 MHz tri-band frequency hopping, 15 km, up to 2.7K

*E200:* Autel adds a 900 MHz component absent from DJI; a sub-GHz wideband OFDM burst near 900 MHz is a useful Autel discriminator to verify.

### CubePilot docs: Herelink Blue Air Unit Specifications
`3/5` · English · doc · 2024 · snippet  
<https://docs.cubepilot.org/user-guides/cubepilot-ecosystem/cubepilot-partners/union-robotics/herelink-blue/herelink-blue-user-guide/air-unit/air-unit-specifications>


Air-unit spec sheet giving the exact frequency range per bandwidth mode and receiver sensitivity. Page blocked; numbers from snippet.


- 10 MHz mode: 2409–2459 MHz; 20 MHz mode: 2412–2462 MHz
- Receive sensitivity -99 dBm at 20 MHz bandwidth; interference recovery <1 s; 2.4 GHz ISM only

*E200:* Whole Herelink plan (2409–2462 MHz) fits inside one 56 MHz AD9361 window; a 20 MSPS host stream covers half of it.

### DJI Mobile SDK OcuSyncBandwidth reference
`3/5` · English · doc · 2019 · snippet  
<https://developer.dji.com/iframe/mobile-sdk-doc/android/reference/dji/common/airlink/OcuSyncBandwidth.html>


Official SDK enum for OcuSync 1/2 downlink channel bandwidths and their nominal throughput. Anchors the 10/20 MHz values against the CSDN '8 MHz' claim.


- OcuSync downlink bandwidth options: 10 MHz (up to 23 Mbps) and 20 MHz (up to 46 Mbps)

*E200:* Both OcuSync 1/2 widths fit a 20 MSPS window when centred.

### DJI O4+ Transmission (Loyalty Drones)
`3/5` · English · blog · 2025 · snippet  
<https://loyaltydrones.com/dji-o4-transmission-revolutionizing-fpv-drone-technology>


Retail-side spec summary of the O4 Air Unit Pro: maximum and selectable channel bandwidths and antenna configuration. Only public statement of the 60 MHz figure found within budget.


- O4 Air Unit Pro maximum communication bandwidth 60 MHz, selectable 20 or 40 MHz
- O4 on Mini 4 Pro: 2.4 and 5.8 GHz, 2T4R; 23 dBm CE on 5.1 GHz band
- O4 ~40 Mbps vs ~15–18 Mbps for O3

*E200:* 20/40/60 MHz OFDM in 2.4/5.1/5.8 GHz; only the 20 MHz mode is fully capturable over 1 GbE.

### DJI Ocusync P1, S1 & S2 Chipset History (Mads Tech Wiki)
`3/5` · English · blog · 2024 · snippet  
<https://fpvwiki.co.uk/dji-ocusync-p1-soc>


Chipset history tying OcuSync generations to DJI's Pigeon/Sparrow SoCs and stating the maximum RF bandwidth per generation; source for the O4 >80 MHz capability claim.


- OcuSync 4 (2023, Mini 4 Pro, Avata 2) runs on the Sparrow 2 (S2) chipset with bandwidth up to and beyond 80 MHz
- OcuSync 3 on Mavic 3 series; OcuSync 4 on Air 3 / Mini 4 Pro

*E200:* O4 links can be wider than the AD9361's 56 MHz; classifier must treat O4 as partially observed.

### ExpressLRS src/src/common.cpp (air-rate tables)
`3/5` · English · github · 2025 · verified  
<https://github.com/ExpressLRS/ExpressLRS/blob/master/src/src/common.cpp>


Round-1 item; cited briefly for the rate table that the classifier needs next to Crossfire. Lists LoRa bandwidth/SF/CR and packet interval per rate for 900 MHz (SX127x/LR11xx) and 2.4 GHz (SX1280 LoRa and FLRC).


- 900 MHz LoRa: BW 500 kHz, SF6–SF9, intervals 5000/10000/20000/40000 us (200/100/50/25 Hz), 250 Hz SF5 on LR11xx
- 2.4 GHz LoRa: BW 800 kHz, SF5–SF8, intervals 2000–20000 us (500–50 Hz)
- 2.4 GHz FLRC: 0.65 Mb/s, BW 0.6 MHz, BT 1, CR 1/2, intervals 1000/2000 us (1000/500 Hz), DVDA variants

*E200:* Distinguish ELRS from Crossfire by chirp (LoRa) vs FSK and by 1–40 ms period vs fixed 6.667 ms.

### FCC ID 2A78Z-AVATAR Walksnail Digital HD FPV System
`3/5` · English · standard · 2022 · snippet  
<https://fccid.io/2A78Z-AVATAR>


FCC grant entry for Walksnail Avatar (blocked); combined with GetFPV/Oscar Liang snippets it gives the channel count, band overlap with analog, codec and latency. Exact centre frequencies and occupied bandwidth remain unpublished in accessible sources.


- 8 channels on 5.8 GHz; channels 1–3 overlap analog 5.8 GHz, 7–8 cleanest at busy fields
- Spec sheet band 5.15–5.85 GHz (FCC/CE/SRRC/MIC variants); H.265, 1080p60, min latency 22 ms
- Power 25 mW–2 W

*E200:* Expect an OFDM carrier of roughly 20 MHz at one of 8 fixed 5.8 GHz slots; width must be measured.

### FCC ID SS3-201402241 DJI LIGHTBRIDGE (ground unit) test report
`3/5` · English · standard · 2014 · snippet  
<https://fccid.io/SS3-201402241/Test-Report/Test-Report-2219514>


FCC 15.247 report for the original (2014) Lightbridge ground station; gives the uplink band and modulation. Page blocked, values from search snippet.


- Frequency range 2405.376–2477.056 MHz, GFSK modulation (ground/uplink)
- Legacy Lightbridge video channels ~2 MHz vs ~10 MHz for Lightbridge 2; different channel-to-frequency mapping

*E200:* Legacy Lightbridge uplink is a narrowband GFSK hopper; decodable-status unknown, treat as detect-only.

### Guide: 1.2GHz-1.3GHz FPV Video System (Oscar Liang)
`3/5` · English · blog · 2023 · snippet  
<https://oscarliang.com/1-2ghz-fpv-guide>


Hobby reference for the 1.2/1.3 GHz analog band: channel span, popular channels, and the US legal subset. No FCC-measured widths available for this band.


- Channels range 1080–1360 MHz; 1256 and 1280 MHz most popular
- US legal: 1258 and 1280 MHz only; international transmitters have up to 9 channels; band hardware spans 1060–1380 MHz
- Analog FM video, same NTSC/PAL baseband as 5.8 GHz

*E200:* E200 (70 MHz–6 GHz) covers 1.2 GHz; a 20 MHz window at 1268 MHz catches both US channels at once.

### HDZero Digital HD FPV System (GetFPV product page)
`3/5` · English · vendor · 2024 · snippet  
<https://www.getfpv.com/fpv/hd-fpv/hdzero-digital-hd-fpv-system.html>


Vendor page stating the HDZero channel width and chipset; the only width number found for HDZero.


- HDZero operates on channels roughly 27 MHz wide
- Up to eight operators on standard 5.8 GHz frequencies; powered by DM5680/DM6300
- Race V3 VTX modes 540p90 / 720p60 / 1080p30, 25/200 mW

*E200:* 27 MHz occupied bandwidth is the distinguishing feature vs analog (~6–8 MHz), Walksnail and DJI O3 widths.

### Skydio Connect: Resilient Connectivity Suite for Skydio X10
`3/5` · English · vendor · 2024 · snippet  
<https://www.skydio.com/connect>


Skydio's own description of the X10 link options (Connect SL point-to-point, Connect 5G cellular). Gives bands, antenna count, EIRP and encryption; modulation not published.


- Connect SL: 2400–2483.5 MHz and 5150–5850 MHz, 2Tx/4Rx, 34.7 dBmi (2.4 GHz) / 35.9 dBmi (5 GHz), up to 12 km
- Connect SL is a proprietary point-to-point link with AES-256 encryption; Connect 5G uses cellular

*E200:* Encrypted proprietary link: detect/classify only; a 5G-cellular-controlled X10 emits no dedicated C2 link at all.

### fpv-sdr README (analog FPV scanner supporting ANTSDR)
`3/5` · English · github · 2025 · verified  
<https://github.com/mikaelnousiainen/fpv-sdr>


Round-1 analog FPV decoder; cited for its extended 64-channel plan (adds DJI and U/O style low bands to the classic 40) and for the fact that it already drives ANTSDR at 20 Msps.


- 64 channels across 8 bands: Raceband, A, B, E, Fatshark, ImmersionRC, DJI, Low, spanning 5362–5945 MHz
- Capture bandwidth defaults: HackRF 12, bladeRF 18, ANTSDR/USRP 20, Pluto 8 Msps
- PAL 625/50 and NTSC standards supported

*E200:* Proves a 20 MSPS ANTSDR stream is sufficient for analog FPV demodulation on the host.

### FCC ID 2AG6IANAFI PARROT DRONE SAS Wi-Fi drone ANAFI (DTS test report R051-24)
`2/5` · English · standard · 2018 · snippet  
<https://fccid.io/2AG6IANAFI>


FCC filing confirming the Anafi is certified as a plain DTS (Wi-Fi) device on 2.4 and 5 GHz; forum note that it defaults to 2.4 GHz. Report blocked.


- Anafi certified as 'Wi-Fi drone' under DTS rules (802.11 OFDM), 2.4 GHz and 5 GHz
- Defaults to 2.4 GHz for range, 5 GHz optional in congested areas; Skycontroller 3 is a Wi-Fi station

*E200:* Detect via 802.11 beacon/probe decoding (gr-ieee802-11 at 20 MHz); payload is WPA2-encrypted.

### FCC ID 2ATGZQZYZH16 SKYDROID H16 (user manual)
`2/5` · English · standard · 2020 · snippet  
<https://fccid.io/2ATGZQZYZH16>


Manual in the FCC filing for the Skydroid H16 ground station; gives band, power and spread-spectrum type for the H16/H12 family of 2.4 GHz integrated RC+video links common on Chinese industrial drones.


- H16: 16 channels, 2.400–2.483 GHz, FHSS, 20 dBm (CE) / 23 dBm (FCC), 1080p video
- H12: 12 channels, same band, FHSS; T10: 10-channel 2.4 GHz FHSS

*E200:* Detect-only for now; width and hop timing not published.

### 大疆OcuSync图传技术解析：如何实现超远距离低延迟视频传输 (DJI OcuSync video-link technology explained) - CSDN
`2/5` · Chinese · blog · 2025 · snippet  
<https://blog.csdn.net/weixin_29216049/article/details/158087603>


Chinese overview of OcuSync (OFDM, MIMO, hopping, AMC). Claims a single video module occupies 8 MHz, which conflicts with DJI SDK 10/20 MHz and tmbinc's ~18 MHz OBW; record as contested.


- States 'in the ISM band a single video transmission module occupies 8 MHz bandwidth' (contested)
- Lists dual-band 2.4/5.8 dynamic switching, OFDM, MIMO, intelligent hopping, AMC

*E200:* Do not use the 8 MHz figure for the classifier.


## Wanted downloads

Pages, PDFs and datasets the sandbox could not reach. Priority 1 = needed for a design
decision, 2 = would sharpen a number, 3 = nice to have. Drop files in `inbox/`.

| Prio | URL | Why | Lens |
|---|---|---|---|
| 1 | <http://asd-stan.org/downloads/asd-stan-pren-4709-002-p1/> | Free official text of ASD-STAN prEN 4709-002 P1 (EU Direct Remote ID): exact transport, timing and message requirements. | regulatory-rid |
| 1 | <https://4code.ru/publications/band5800> | Vendor technical note on analog FPV detection across 4800-6200 MHz (channel counts, sweep timing, Wi-Fi rejection) - blocked here, only snippets | web-ru-community |
| 1 | <https://blog.csdn.net/futon/article/details/131232535> | The known Chinese USRP B200 DroneID decoding walkthrough (Mini 2 / Mavic Air 2 / Mavic 2 Pro, pilot coordinates); CSDN is blocked from this session. | web-zh-community |
| 1 | <https://blog.csdn.net/leegang12/article/details/149397403> | leegang12 series entry claiming CRC-correct DroneID decoding for O1/O2/O3/O4; also fetch #283 (148471288), #296 (149822783), #305 (149977416), #320 (150761143), #254 (146934408), #264 (147245156), #258 (146977731), #267 (147321812), #281 (148402169) to extract PHY parameters and packet types. | web-zh-community |
| 1 | <https://cms.stan-shop.org/uploads/2024/01/ASD-STAN_DRI_Introduction_to_the_European_digital_RID_UAS_Standard.pdf> | ASD-STAN DRI whitepaper; readable summary of EN 4709-002 for the toolkit docs. | regulatory-rid |
| 1 | <https://fccid.io/2A78Z-AVATAR> | Walksnail Avatar FCC filing: channel list and occupied bandwidth for the Avatar OFDM link. | signal-reference-tables |
| 1 | <https://fccid.io/2AGNTMDC240958A/Test-Report/Test-report-part-3-6031063> | Autel EVO II V3 (SkyLink 2.0) FCC test report: occupied bandwidth / 99% OBW plots per band incl. 900 MHz — the only way to get Autel widths. | signal-reference-tables |
| 1 | <https://fccid.io/SS3-OAS11709/Test-Report/Test-Report-3634081> | DJI OcuSync Air System (O3-era air unit) 15.247 report: measured OBW for 10/20/40 MHz modes and hop channel list. | signal-reference-tables |
| 1 | <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT241111> | MFCC+GRU paper: authors, N210 capture settings, feature extraction and the 3-D localisation method. | academic-zh |
| 1 | <https://smell.co.ua/blog/pro-bezpilotni-aparaty/rozrobka-ta-zbirka-detektora-droniv-i-skanera-chastot-video-peredavacha-fpv> | Ukrainian DIY build log of an RX5808/ESP32-S2 video scanner and 700-1020 MHz scanner; may contain schematics and firmware links | web-ru-community |
| 1 | <https://www.caac.gov.cn/XXGK/XXGK/BZGF/BZGF_GJBZ/202601/t20260120_229783.html> | Official GB 46750-2025 publication page; needed to settle the packet layout (timestamp encoding, field sizes) before writing a decoder. | academic-zh |
| 1 | <https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire/> | Full Crossfire reverse-engineering write-up incl. LoRa settings of the 50 Hz mode and hop-sequence derivation. | signal-reference-tables |
| 1 | <https://www.itenrecht.nl/documents/ecli/56e8eb1b-5a94-40f9-9451-3e83c35ff8c2.pdf> | The only located Dutch legal source interpreting 'bijzondere inspanning' (art. 139c lid 2 sub 1 Sr) as systematic recording with more than one apparatus; decisive for a multi-node passive network's legal note. | regulatory-rid |
| 1 | <https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202> | DroneRFb-DIR raw I/Q dataset (6 types x 3 individuals, 2.4-2.48 GHz) for individual-fingerprint experiments. | academic-zh |
| 1 | <https://www.sciengine.com/parse/pdf/1003-0530/F1FDEFB8A2684310A37ED805A8E2679C.pdf> | Full text of 苏志刚 et al. 2023 low-SNR real-time detector (architecture, dataset, SNR protocol). | academic-zh |
| 2 | <https://4code.ru/doc/alissum_vn/manual_vn.pdf> | Alissum-ВН remote detector manual: bands, sweep behaviour, alert semantics of a NN-based RU detector | web-ru-community |
| 2 | <https://4code.ru/publications/matracer> | Describes the 'МАТРАСЕР' air-recording tool used to collect detector training data - useful pattern for an E200 IQ recorder | web-ru-community |
| 2 | <https://blog.csdn.net/dong2010hong/article/details/142590321> | Commercial RF-detector design explainer (300-6000 MHz, -120 dBm, feature library, amplitude DF, TDOA); also 138107124 and 142896540 by the same author for signal-library schema ideas. | web-zh-community |
| 2 | <https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4> | DroneRFb-DIR paper PDF: SDR model, sample rate, drone list, baseline accuracies. | academic-zh |
| 2 | <https://counteruavhub.com/tools/drone-frequency-database/> | Aggregated drone frequency/signal database covering Yuneec, Hubsan, Holy Stone, Potensic etc.; cross-check table rows for small brands. | signal-reference-tables |
| 2 | <https://eur-lex.europa.eu/eli/dec_impl/2024/2103/oj> | Implementing Decision (EU) 2024/2103 with the annex naming the harmonised EN 4709-002 edition and its 'restriction'. | regulatory-rid |
| 2 | <https://fccid.io/2A6CG-HX406210> | Herelink Air Unit FCC filing: OBW and channel table to separate Herelink from OcuSync. | signal-reference-tables |
| 2 | <https://fpvua.org/resources/barvinok-5.158/> | Barvinok-5 resource page (and https://barvinok-5.notion.site) - Ukrainian ELRS derivative frequency/telemetry behaviour from the primary source | web-ru-community |
| 2 | <https://gitcode.csdn.net/6a2459d5662f9a54cb7ac49a.html> | Chinese roundup of open drone-RF datasets; cross-check against the round-1 dataset list for anything missed (e.g. Chinese-only datasets). | web-zh-community |
| 2 | <https://habr.com/ru/articles/966044/> | Habr article behind passive-sdr-radar: DVB-T2 illuminator choice, KrakenSDR/RPi5 setup, measured results | web-ru-community |
| 2 | <https://img.antpedia.com/standard/files/pdfs_ora/GB2025/20251130/GB+46750-2025.pdf> | Full text of GB 46750-2025 (民用无人驾驶航空器系统运行识别规范) for implementing the Chinese broadcast format beyond the libopendroneidcn README. | regulatory-rid |
| 2 | <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230302?viewType=HTML> | Multi-dimensional feature paper: adaptive triangular threshold and RIB bispectrum details. | academic-zh |
| 2 | <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT250051?viewType=HTML> | Wavelet-entropy feature definitions for hop signals. | academic-zh |
| 2 | <https://journals.ru.lv/index.php/ETR/article/download/8486/6933/10816> | ETR 2025 paper PDF with waterfall measurements of Air 3 (O4), Mini 4 Pro and Phantom 4 — check its bandwidth figures and correct its protocol attributions. | signal-reference-tables |
| 2 | <https://militarnyi.com/uk/special-projects/yak-vybraty-detektor-droniv-oglyad-modelej-i-klyuchovi-kryteriyi-vyboru/> | 2025 Ukrainian detector market overview with per-model band lists (Xenon-L, Chatovyi, HUNTER-3 etc.) | web-ru-community |
| 2 | <https://phantompilots.com/threads/phantom-3-channel-frequency-table.51100/> | Full 32-entry Lightbridge 2 channel↔frequency table (page 1–2). | signal-reference-tables |
| 2 | <https://signal.ejournal.org.cn/cn/article/pdf/preview/10.16798/j.issn.1003-0530.2024.04.001.pdf> | Chinese survey of DL drone detection incl. RF datasets/methods - literature map. | academic-zh |
| 2 | <https://veiligesmartcities.nl/wp-content/uploads/2026/03/stcrt-2026-2035.pdf> | Staatscourant 2026 nr. 2035: the temporary Dutch counter-drone policy framework (who may detect/disrupt/take over); defines the boundary for private passive detection. | regulatory-rid |
| 2 | <https://wetten.overheid.nl/BWBR0001854/> | Authoritative current text of Wetboek van Strafrecht art. 139c (and 139d/441) to quote verbatim in the legal note. | regulatory-rid |
| 2 | <https://www.163.com/dy/article/KCLCCD000552L9R6.html> | GB 42590-2023 interpretation; the standard text itself (民用无人驾驶航空器系统安全要求) is needed to check whether the WiFi/Bluetooth broadcast RID follows ASTM F3411 message formats. | web-zh-community |
| 2 | <https://www.aerial-defence.com/the-process-of-encrypting-dji-droneid-has-commenced/> | Details on which DJI models/firmware encrypt DroneID from Jan 2024 and the AeroScope EA500 upgrade; sets expectations for DroneID decoding on the E200. | regulatory-rid |
| 2 | <https://www.digidow.eu/publications/2021-christof-masterthesis/Christof_2021_MasterThesis_DJIProtocolReverseEngineering.pdf> | Master thesis reverse-engineering the DJI Wi-Fi control protocol (Spark/Tello/Mavic Air class) — decodability of DJI Wi-Fi drones. | signal-reference-tables |
| 2 | <https://www.mdpi.com/2504-446X/10/2/117> | Drones 2026 'Wideband Monitoring System of Drone Emissions Based on SDR Technology with RFNoC' — likely contains per-drone measured spectra and an FPGA-side pipeline comparable to the E200's Zynq. | signal-reference-tables |
| 2 | <https://www.scidb.cn/en/detail?dataSetId=34f0a91e8a544904998b8fdc44477380> | DroneRFa dataset itself (known) - needed to re-cut 20 MHz sub-bands for E200-compatible training. | academic-zh |
| 2 | <https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202&version=V1&code=j00173> | DroneRFb-DIR raw IQ dataset (2.4-2.48 GHz, 6 types x 3 individuals) for RF-fingerprint experiments; plus the paper PDF https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4 | web-zh-community |
| 3 | <http://www.idc-rf.com/news/1183.html> | Chinese MIIT allocation of UAV RC/video bands (possible 840.5-845 MHz and 1430-1444 MHz allocations that EU scans miss); numbers must be verified from the page. | web-zh-community |
| 3 | <https://arxiv.org/pdf/2510.11343> | TBRD (TESLA-authenticated Broadcast Remote ID) paper: background for an authenticity/plausibility field in the AERIX contract. | regulatory-rid |
| 3 | <https://cyberleninka.ru/article/n/maket-pelengatora-na-osnove-sdr-tehnologii> | Russian SDR direction-finder prototype paper (full text PDF) | web-ru-community |
| 3 | <https://cyberleninka.ru/article/n/obnaruzhenie-bespilotnyh-letatelnyh-apparatov-suschestvuyuschie-resheniya-i-vozmozhnosti> | Russian survey of UAV detection methods incl. RF; check for cited datasets | web-ru-community |
| 3 | <https://developer.dji.com/iframe/mobile-sdk-doc/android/reference/dji/common/airlink/OcuSyncBandwidth.html> | Official OcuSync 10/20 MHz bandwidth enum and throughput; cite in the table. | signal-reference-tables |
| 3 | <https://fccid.io/2ATGZQZYZH16/User-Manual/user-manual-5022131.pdf> | Skydroid H16 manual/report for band plan and hop details. | signal-reference-tables |
| 3 | <https://fccid.io/2AYVYFMWRJ03A8/Test-Report/Test-Report-5627719> | FIMI X8 SE 2022 DTS report: confirms Wi-Fi 20/40 MHz modes and 5.8 GHz channels for the FIMI row. | signal-reference-tables |
| 3 | <https://fccid.io/SS3-201402241/Test-Report/Test-Report-2219514> | Original Lightbridge ground-unit report (GFSK, 2405–2477 MHz): channel spacing and OBW for the legacy row. | signal-reference-tables |
| 3 | <https://fccid.io/SS3-MM1A1702/Test-Report/Test-Report-3402160> | DJI Spark Wi-Fi test report: 2.4/5.8 GHz 802.11 channel widths for the DJI Wi-Fi-drone row. | signal-reference-tables |
| 3 | <https://fpv-club.ru/analizator-spektra-ili-detektor-dronov-otlichija/> | HackRF vs tinySA vs signature-detector comparison with screenshots of FPV signals | web-ru-community |
| 3 | <https://item.taobao.com/item.htm?id=691394502321> | Official MicroPhase E200 Taobao listing; check current price, accessory bundles (GPSDO, IPEX pigtail, MMCX cable) and AD9361 vs AD9363 variants. | web-zh-community |
| 3 | <https://max.book118.com/html/2023/0809/6011140203005211.shtm> | GB 42590-2023 full text (民用无人驾驶航空器系统安全要求) for the remote-identification clause and its Wi-Fi/Bluetooth broadcast requirements. | regulatory-rid |
| 3 | <https://mbb.eet-china.com/blog/1675150-368785.html> | Spectrum-analyser measurements of DJI Phantom 3 RC uplink and video downlink (legacy Lightbridge-era signature). | web-zh-community |
| 3 | <https://modelistam.com.ua/nestandartnye-chastoty-kak-vybrati-dlya-obhoda-pomeh-a-365/> | Non-standard FPV video frequency guide (1.2/1.3/3.3 GHz grids) | web-ru-community |
| 3 | <https://patents.google.com/patent/CN113518374A/zh> | Patent text listing the 30 statistical features used for video-link identification under Wi-Fi interference. | academic-zh |
| 3 | <https://phantompilots.com/threads/lightbridge-and-ocusync-protocol-description.147896/> | Forum thread describing Lightbridge/OcuSync framing beyond the tmbinc notes. | signal-reference-tables |
| 3 | <https://signal.ejournal.org.cn/cn/article/pdf/preview/10.16798/j.issn.1003-0530.2024.04.004.pdf> | Domain-adaptation (Transformer + DANN) for drone emitter individual identification. | academic-zh |
| 3 | <https://static.insales-cdn.com/files/1/2222/36325550/original/detektor-bpla-bulat-v4_quickguide_main.pdf> | Bulat v4 quick guide: exact bands and signature classes of the most common RU handheld detector | web-ru-community |
| 3 | <https://www.anquanke.com/post/id/168279> | 2019 Unicorn Team blind analysis of DJI broadcast signals. | academic-zh |
| 3 | <https://www.bilibili.com/video/BV1RRtEzvEZS/> | C-RID (Chinese unique-product-ID) broadcast module tutorial; identifies a cheap transmitter to validate an AERIX receiver against Chinese-format RID. | web-zh-community |
| 3 | <https://www.caac.gov.cn/PHONE/HDJL/YJZJ/202502/P020250212316294948285.pdf> | CAAC draft of the GB operational-identification standard (预审 version) showing the evolution to GB 46750-2025. | regulatory-rid |
| 3 | <https://www.comnews.ru/content/244060/2026-03-04/2026-w10/1008/grazhdanskie-bespilotniki-vselilas-era-glonass> | ComNews article on ERA-GLONASS drone identification and the hybrid 'DroneID analogue'; needed to learn whether any RF broadcast component exists. | regulatory-rid |
| 3 | <https://www.ithome.com/0/965/621.htm> | DJI O4 ground station band list (sub-2 GHz/2.4/5.2/5.8) and O4 Air Unit bands 5.170-5.250 / 5.725-5.850 GHz for the scan plan; also https://digi.ithome.com/archiver/823/622.htm | web-zh-community |
| 3 | <https://www.juestc.uestc.edu.cn/article/doi/10.12178/1001-0548.2024309> | UESTC noise-fingerprint drone detection paper (title only known). | academic-zh |
| 3 | <https://www.kechuang.org/t/89181> | HDZero DM5680 + AD9361 architecture write-up for building an HDZero OFDM signature; plus https://news.eeworld.com.cn/mp/ADI/a60568.jspx for the range/latency figures. | web-zh-community |
| 3 | <https://zhuanlan.zhihu.com/p/667452286> | DJI大疆OcuSync系列通信协议终极指南 (OcuSync 1–4 protocol guide, zh) — Chinese summary of per-generation bandwidths/bands. | signal-reference-tables |
