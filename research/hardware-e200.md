# Hardware and firmware truth: MicroPhase ANTSDR E200

What the E200 actually is, what each firmware personality can and cannot do, and the
numbers that constrain every capture the toolkit will ever take. Everything here is
sourced. Where the vendor prose and the code disagree, the code wins and the
disagreement is named.

Companion documents: [landscape.md](landscape.md) for what the signals are,
[signal-reference.md](signal-reference.md) for waveform parameters,
[datasets.md](datasets.md), [regulatory.md](regulatory.md),
[foreign-perspective.md](foreign-perspective.md),
[verification-log.md](verification-log.md) for the adversarial checks quoted below, and
[sources.md](sources.md) for the full bibliography. Decisions that depend on this
document: [ADR-0004](../docs/decisions/ADR-0004-firmware-personality-and-capture-tiers.md),
[ADR-0005](../docs/decisions/ADR-0005-processing-location.md),
[ADR-0009](../docs/decisions/ADR-0009-localisation-deferred.md).

Two research claims used below were planned for adversarial verification but were never
run because the agent budget ran out. They are marked **(unverified, round 1)** wherever
they appear: the E200 O4 DroneID firmware channel list, and the OcuSync PHY parameters.

---

## 1. Board-level facts

The vendor page lists the E200 as "Xilinx Zynq 7020 (integrated dual-core ARM Cortex-A9
and Artix-7 FPGA)", "Analog Devices AD9361/9363", "1 Gigabit Ethernet interface",
"TYPE-C USB-UART interface", "8-Pin 2.54mm pitch GPIO expansion port", "1 external
PPS/10MHz reference entrance", "2 transmit channels and 2 receive channels, supporting
half-duplex or full-duplex operation" and a 12-bit ADC/DAC
([AntsdrE200_Reference_Manual.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md)).
The public 15-sheet development schematic (rev 1.0, dated 2022-10/11) fills in the part
numbers
([ANT-E200_Public.pdf](https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf)).

| Block | Value | Source |
|---|---|---|
| SoC | Zynq XC7Z020-CLG400, dual Cortex-A9 + Artix-7 fabric | [manual](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md), [schematic](https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf); FPGA part `xc7z020clg400-2` in both build flows ([UHD firmware README](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/README.md)) |
| FPGA fabric | 85K logic cells, 53,200 LUT, 220 DSP, 4.9 Mb BRAM | [Crowd Supply](https://www.crowdsupply.com/microphase-technology/antsdr-e200) (snippet only, vendor marketing) |
| Transceiver | AD9361 or AD9363 option; public schematic sheet 11 draws U11 as **AD9363** | [manual](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md), [schematic](https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf) sheets 1 and 11 |
| PS DDR3 | 512 MB, Micron MT41K256M16TW, 16-bit; device-tree memory size `0x20000000` | [AntsdrE200_RF_parameters.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md) ("PS 512MB"), schematic sheet 7, [linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch) |
| QSPI flash | 32 MB Winbond W25Q256 (compatible `n25q256a` in Linux, `n25q256a11` in U-Boot) | schematic sheet 2, [linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch), [u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch) |
| Removable storage | micro-SD; a 32 GB card ships in the kit | schematic sheet 2, [AntsdrE200_Unpacking_examination.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md) |
| Host link | 1 GbE, Realtek RTL8211F PHY on RGMII, HR911130A magjack; "can only works at 1000M speed" | schematic sheet 9, [antsdr_uhd README](https://github.com/MicroPhase/antsdr_uhd) |
| Console | Type-C connector wired D+/D- only to a CH340 USB-UART, 115200 baud | schematic sheet 8, [unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md) |
| GPIO header | J30, 10 pins: pin 1 VCC_3V3, pin 2 GND, pins 3-10 = GPIO_00..GPIO_07 on bank 13 (3.3 V), ESD-protected | schematic sheets 4 and 10 |
| Reference input | one MMCX jack J18 labelled "10/PPS", shared between 10 MHz and PPS | [manual](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md), schematic sheet 13 |
| PS clock | 33.333 MHz | schematic sheet 2 |
| Boot select | MIO[2..8] strapped, slide switch J32 (SK-3293S) labelled BOOT / QSPI / SD, below the Ethernet jack | schematic sheets 2 and 14, [unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md) |
| LEDs | green = FPGA DONE, blue = PS_LED0, red = PG_SYS; green blinks after a good boot | schematic sheet 15, [unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md) |
| Power | 2 A fuse F2 on VCC_5V | schematic power sheet |
| In the box | SDR, USB cable, 2 rubber antennas, card reader, Ethernet cable, 32 GB SD card | [unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md) |

QSPI partitioning (32 MB), from the device trees:

| Partition | Offset | Size |
|---|---|---|
| `qspi-fsbl-uboot` | 0x000000 | 1 MB |
| `qspi-uboot-env` | 0x100000 | 128 kB |
| `qspi-nvmfs` | 0x120000 | 0xE0000 |
| `qspi-linux` | 0x200000 | 30 MB |

Source: [linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch)
(`zynq-e200.dtsi`) and [u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch)
(`zynq-e200-sdr.dts`). The U-Boot environment lives at `/dev/mtd1`, offset 0, size
0x20000, in both the IIO and the UHD firmware (`fw_env.config` in
[antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch) and
[antsdr_uhd](https://github.com/MicroPhase/antsdr_uhd) buildroot board directories).

### 1.1 AD9361 versus AD9363: the identity question

This matters because it decides whether 5.8 GHz work and 56 MHz bandwidths are inside or
outside the silicon datasheet.

- The vendor manual lists both options: AD9361 covers 70 MHz to 6 GHz with 200 kHz to
  56 MHz analog bandwidth, AD9363 covers 325 MHz to 3.8 GHz with 200 kHz to 20 MHz
  ([manual](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md)).
- The public schematic sheet 11 draws the transceiver U11 as an **AD9363**, and the
  U-Boot model string is `Analog Devices ANTSDR Rev.C (Z7020/AD9363)`
  ([schematic](https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf),
  [u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch)).
- Crowd Supply sells two variants: AD9363 at $299 (325-3800 MHz, 20 MHz) and AD9361 at
  $499 (70 MHz-6 GHz, 56 MHz) ([Crowd Supply](https://www.crowdsupply.com/microphase-technology/antsdr-e200), snippet only).
- The IIO device tree declares `compatible = "adi,ad9364"` on `ad9361-phy`, and the
  2r2t procedure rewrites it to `ad9361` (see section 5). The AD9364 is a 1R1T part with
  the full 70 MHz-6 GHz / 56 MHz range, so declaring AD9364/AD9361 unlocks the wide
  tuning range regardless of what silicon is fitted
  ([linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch), verified: `rf-ports`).
- The IIO firmware banner over the network reads `Analog Devices ANTSDR Rev.C
  (Z7020-AD9361)` in `iio_info -S`
  ([SDR++ issue #1478](https://github.com/AlexandreRouma/SDRPlusPlus/issues/1478)).

Consequence: the firmware string is not evidence of the fitted part. Read the chip
marking on U11 on the actual board. If it is an AD9363, everything above 3.8 GHz and
above 20 MHz bandwidth runs outside the datasheet, which is a documented risk in the
research record and untested by the vendor documentation.

### 1.2 Clock tree, external reference and `ad5660mp`

Schematic sheet 13 (CLOCK) shows a 40 MHz oscillator X1 annotated "DEFAULT: TCXO
+/-0.5PPM, OPTIONAL1: VCTCXO +/-0.28PPM", steered by a DAC U60 over DAC_nSYNC / DAC_SCLK
/ DAC_DIN with VOUT through a 2.2 kohm series resistor R186, powered from an SPX3819 LDO
rail VCC_TCXO_3V3. A clock buffer distributes RF_REFCLK to the transceiver and FPGA_GCLK1
to the PL. The MMCX jack J18 feeds two paths: a buffered PPS line (specified
"PPSIN VIH 2~5V VOL 0~0.8V") and an AC-coupled path (100 nF C439, 49.9 ohm R301) to
REF_CLKIN_10M with a REF_CLK_REQ enable
([schematic](https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf)).

Computed from that 0.5 ppm figure, the free-running LO error is about 1.2 kHz at 2.4 GHz
and about 2.9 kHz at 5.8 GHz. Crowd Supply claims +/-10 ppb with a GPSDO supplying 10 MHz and PPS
([Crowd Supply](https://www.crowdsupply.com/microphase-technology/antsdr-e200), snippet).

The disciplining loop is exposed as an IIO device named `ad5660mp` (driver
`ad5660_mp.c`, compatible `microphase,ad5660`, registers based at 0x43C00000):

| Attribute | Register offset | Meaning |
|---|---|---|
| `in_voltage_dac_mode` | +0 | 0 = automatic, 1 = manual; the probe writes 1 |
| `in_voltage_dac_value` | +4 | manual DAC code; the probe writes 23000 |
| `in_voltage_dac_read_value` | +8 | current DAC code in automatic mode |
| `in_voltage_dac_ref_sel` | +12 | 0 = 10 MHz, 1 = PPS, 2 = GPS |
| `in_voltage_dac_locked` | +16 | PLL lock flag |

Sources: [Antsdr-Clock-calibration.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration.md)
(an E310 page that the E200 page points to as applicable), its Chinese mirror
[Antsdr-Clock-calibration_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration_cn.md),
and the driver in the [linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch).
Procedure: connect the reference with an SMA-to-MMCX cable to the "10/PPS" port, log in
(root / analog), `cd /sys/bus/iio/devices/iio:deviceN`, then

```sh
echo 0 > in_voltage_dac_mode        # automatic
echo 0 > in_voltage_dac_ref_sel     # 0 = 10 MHz, 1 = PPS, 2 = GPS
# wait tens of seconds
cat in_voltage_dac_locked           # expect 1
```

The FPGA side is `axi_vcxo_ctrl`: reg0 bit 0 = DAC mode, reg1[15:0] = manual value,
reg2 = read-back, reg3[1:0] = reference select (00 CLKIN_10MHz, 01 PPS_IN, 10 PPS_GPS),
reg4 = locked, with a default DAC code of 42580 in the HDL and a `b205_ref_pll` that
auto-detects a 10 MHz input within +/-5 ppm or a PPS within +/-200 ppm and declares lock
at 1 ppm tolerance, clocked at 200 MHz from the 40 MHz reference
([HDL patch](https://github.com/MicroPhase/antsdr-fw-patch), `library/axi_vcxo_ctrl`).
Note the two different default DAC codes, 23000 in the documented manual procedure and
42580 as the HDL default; the evidence does not reconcile them.

There is **no GPS on the E200**. The `ref_sel` value 2 exists in the register map, but the
IIO firmware's FPGA top level instantiates the wrapper with `.PPS_GPS(1'b0)`
([HDL patch](https://github.com/MicroPhase/antsdr-fw-patch), `projects/e200/system_top.v`,
checked in the cloned patch file),
the UHD driver enables the `gpsdo` option only for the product string `E310  v2`
([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)),
and the vendor documentation states an on-board GPSDO and separate 10 M / PPS inputs only
for the E316, never for the E200
([manual](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md)).
For a multi-node TDOA deployment the E200 therefore needs an external GPSDO feeding the
single MMCX jack, and PPS and 10 MHz cannot both be wired at once.

One unresolved user report: on
[RadioReference](https://forums.radioreference.com/threads/phase-noise-issue-with-antsdr-e200-vs-pluto-sdr.502838/)
(snippet only, page blocked) a 1 GHz LO with a 1 MHz tone is described as "much wider and
contains noticeable phase noise" on the E200 where a Pluto shows "very sharp peak with no
visible phase noise"; the poster changed the U60 DAC output filter corner from 300 Hz to
0.72 Hz with no effect and got no resolution. Treat close-in phase noise as unmeasured
and a risk for narrowband telemetry demodulation and for phase-based direction finding.

---

## 2. RF ports and what is reachable

The authoritative statement is MicroPhase's own selection table, identical in the English
and Chinese trees: for the E200 the "RF channel" row reads **`SMA:1T1R IPEX:1T1R`**,
while the E310 and E316 rows read `2T2R MIMO`
([AntsdrE200_RF_parameters.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md),
[AntsdrE200_RF_parameters_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters_cn.md)).
Schematic sheet 12 gives the routing:

| Logical channel | IIO channel | UHD channel | Connector | Path |
|---|---|---|---|---|
| RX1 | `voltage0` (I) / `voltage1` (Q) | 0 | **J3, SMA** | RX1A_P/N through a balun |
| TX1 | DDS ch 0 | 0 | **J4, SMA** | TX1A_P/N through a balun, then U6 PGA-102+ PA gated by `TX_AMP_EN` (1 = PA on) off a dedicated LDO |
| RX2 | `voltage2` / `voltage3` | 1 | **J6, U.FL / IPEX** | RX2A_P/N through a balun |
| TX2 | DDS ch 1 | 1 | **J5, U.FL / IPEX** | TX2A_P/N, no PA, no enable line |

Source: [schematic](https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf)
sheet 12; IIO channel naming from
[pyadi-iio adi/ad936x.py](https://github.com/analogdevicesinc/pyadi-iio/blob/main/adi/ad936x.py).

Three consequences, all verified (verified: `rf-ports`):

1. **There is no TX/RX or antenna switching on the E200 at all.** The UHD FPGA top level
   has the whole B200 front-end GPIO vector (the SFDX/SRX switch lines) commented out and
   drives only `assign tx_amp_en1 = fe0_gpio[7]`
   ([antsdr_e200.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/antsdr_e200.v)).
   The UHD driver still creates the B210 antenna property, so `uhd_usrp_probe` prints
   `Antennas: TX/RX, RX2` on RX frontend A
   ([AntsdrE200_UHD.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD.md)),
   but those names are B210 leftovers and are no-ops on this board. A round-1 finding in
   the research record claimed that `set_rx_antenna("RX2")` selects the IPEX port; that is
   **wrong** and was corrected by the adversarial check. RX1 is hard-wired to its SMA and
   RX2 to its U.FL; the only way to select a port is to enable the corresponding channel.
2. **The IPEX pair is not unreachable, but the pigtail situation is contradictory.** Crowd
   Supply states the kit ships a Hirose U.FL-to-SMA bulkhead pigtail with under 2 dB loss
   to 6 GHz ([Crowd Supply](https://www.crowdsupply.com/microphase-technology/antsdr-e200), snippet only),
   while MicroPhase's own unboxing page lists only "SDR, USB cable, 2 rubber antennas,
   card reader, Ethernet cable, 32 GB SD card"
   ([unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md)).
   Check the box. Without a pigtail there is no second antenna and no direction finding.
3. **Crowd Supply's "2x2 MIMO with two SMA antenna connectors and two U.FL connectors"**
   (snippet) is consistent with the schematic only if read as one SMA for RX1 and one for
   TX1; the board photo shows exactly two SMA jacks on the RF edge
   ([e200.png](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/ANTSDR_E200_Reference_Manual.assets/e200.png)).
   It is not two SMA receive ports.

For passive use the TX PA matters only as something to keep quiet. Under UHD the PA enable
comes from the front-end GPIO (`assign tx_amp_en1 = fe0_gpio[7]`,
[antsdr_e200.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/antsdr_e200.v)),
but on the IIO firmware the FPGA top level ties it high unconditionally
(`assign tx_amp_en = 1'b1` in `projects/e200/system_top.v` of the
[HDL patch](https://github.com/MicroPhase/antsdr-fw-patch), checked in the cloned patch
file), so the PA is enabled for as long as that personality runs. The correct passive
posture is therefore to hold the TX chain at maximum attenuation and never to call `tx()`,
per [ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md). The two personalities
use **opposite sign conventions** for that setting and must not be confused:

| Personality | Attribute or call | Value for maximum attenuation | Source |
|---|---|---|---|
| UHD | `set_tx_gain()` | **0.0 dB**, the bottom of the TX gain range the documented probe output reports as "gain 0-89.8 dB step 0.2" for FE-TX1 | [AntsdrE200_UHD.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD.md) probe output |
| IIO / pyadi | `tx_hardwaregain_chanX` | **-89**, the value the reference dual-RX script uses for a passive board | [Pluto_Beamformer deep read](https://github.com/jonkraft/Pluto_Beamformer) (`sdr.tx_hardwaregain_chan0 = -89  # passive`) |

On the IIO path the attribute is an attenuation expressed as a negative number, so -89 is
near the floor, not inside the 0.0 to 89.8 dB UHD gain range at all. The magnitude matches
UHD's own `AD9361_MAX_GAIN = 89.75` constant (`ad9361_device.cpp` lines 288-294, reached
through
[ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)),
which is an inference about the sign convention rather than a statement any source makes;
read back what the driver accepts before trusting it. Setting `0` on the IIO path would be
maximum output power. Whether the PA still
produces measurable LO leakage in that state is one of the numbers to measure (section 15).

---

## 3. Firmware personalities and how to boot each

The BOOT/QSPI/SD slide switch under the Ethernet jack selects the boot medium; the
personalities are mutually exclusive at boot time.

| Personality | Boots from | Login | Default IP | What it gives | Primary source |
|---|---|---|---|---|---|
| **IIO / PlutoSDR-compatible** (antsdr-fw-patch v0.39) | QSPI, factory-preloaded | root / `analog` | 192.168.1.10, mDNS `ant.local` | `iiod` over TCP; libiio, pyadi-iio, GNU Radio `gr-iio`, MATLAB. 1R1T until reconfigured | [antsdr-fw-patch README](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md), [unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md) |
| **UHD (B210-compatible)** (antsdr_uhd v1.0) | SD only | root / `microphase` | 192.168.1.10, persisted with `ip_set <ip>` into the I2C EEPROM | UHD 4.1 device `type=ant`, two radio chains, sc16/sc12/sc8/fc32 over the wire | [antsdr_uhd README](https://github.com/MicroPhase/antsdr_uhd), [host README](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/README.md), [firmware README](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/README.md) |
| **DJI DroneID, legacy** (`done_dji_release`, 2024-03-06) | SD | configured from QSPI Pluto mode as root / `analog` | 192.168.1.10 | TCP **server** on port 41030, little-endian binary detection frames | [alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) |
| **DJI DroneID, current** (`drone_dji_rid_decode`, 2026-01-14) | SD (zip filename disputed, see below) | root / `1` | from `ipaddr_eth` | TCP **client** to `tcp_serverip:52002` sending CSV lines | [alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) |
| **DJI DroneID, O4** (zip filename disputed, see below) | SD | root / `1` | from `ipaddr_eth` | O4 encrypted-ID detection: hash, frequency, RSSI | [alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid) |
| **openwifi** (board `antsdr_e200`) | SD | password `openwifi` (from the E310 openwifi page, which the E200 page defers to) | 192.168.10.122 (same E310 page) | mac80211 802.11a/g/n: monitor, injection, CSI, short IQ capture. No wideband IQ | [openwifi](https://github.com/open-sdr/openwifi), [board README](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md), [MicroPhase E200 page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_openwifi.md) |
| **Kuiper / FMCOMMS** | SD (dd image + MicroPhase boot files) | Kuiper defaults | static, set in `/etc/network/interfaces` | full Debian with a local IIO context; the E310 page claims "2T2R operation at a 61.44Msps sampling rate" on-board | [antsdr_fmcomms](https://github.com/MicroPhase/antsdr_fmcomms) (snippet), [AntsdrE310_fmcomms.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/AntsdrE310_fmcomms.md) |
| **Standalone / no-OS** | JTAG or SD | n/a | n/a | bare-metal ADI HDL + no-OS project `antsdre200`, LO/rate/gain over serial | [antsdr_standalone](https://github.com/MicroPhase/antsdr_standalone) |

Notes that cost time if missed:

- **DFU flashing does not work on the E200.** The firmware README says plainly "DFU mode
  is just for e310 e310v2(e316), e200 is unsupport"
  ([antsdr-fw-patch README](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md)).
  QSPI is rewritten either from U-Boot with `loaddfu` reading `boot.dfu` to 0x0,
  `e200.dfu` to 0x200000 and `uboot-env.dfu` to 0x100000 off a FAT SD, or from a running
  Linux with `update_frm.sh <file.frm>`, which checks the md5 and magic, `dd`s to
  `/dev/mtdblock3` and then sets `fit_size`
  ([u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch),
  buildroot patch `board/e200/update_frm.sh` in [antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch)).
- The UHD SD card is a plain FAT32 with `BOOT.bin`, `antsdr.bit` (the name must match
  `bitstream_image=antsdr.bit` in `uEnv.txt`), `uImage`, `uEnv.txt`, `devicetree.dtb` and
  `uramdisk.image.gz`; the rootfs is a ramdisk, there is no ext4 partition
  ([firmware README](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/README.md)).
- The DroneID SD images are modified **Pluto-firmware** builds, not UHD: their `uEnv.txt`
  is the stock `antsdre200` environment with `mode=1r1t` and `maxcpus=1`
  ([alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid)).
- **The zip-to-binary mapping is contradictory in the evidence and must be confirmed by
  unpacking the archive before flashing.** The round-1 reading of the repository says
  `build_sdimg_drone_net.zip` (files dated 2024-03-06) contains the **legacy**
  `/usr/sbin/done_dji_release` (TCP server on 41030, binary frames) and
  `build_sdimg_drone_o4.zip` (2026-01-14) contains the **new** `/sbin/drone_dji_rid_decode`
  (TCP client to `tcp_serverip:52002`, CSV). The deep read of the same repository says the
  opposite, that `build_sdimg_drone_net.zip` carries `drone_dji_rid_decode` and
  `build_sdimg_drone_o4.zip` is the O4 detection image. Both readings agree on which
  **binary** does what; only the filename attached to each disagrees. Extract the ramdisk
  and check for `done_dji_release` versus `drone_dji_rid_decode` before committing an SD
  card ([alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid)).
- openwifi on the E200 boots only from SD, so it excludes both streaming personalities.
  Inside the openwifi image the AD9361 IIO control driver is present but the `cf-ad9361`
  IQ DMA is disabled, so there is no wideband IQ stream; openwifi is also OFDM-only and
  cannot demodulate 802.11b DSSS/CCK, which is how most reference Remote ID beacon
  transmitters send on 2.4 GHz. The free FPGA image's Xilinx Viterbi decoder runs under an
  evaluation licence and halts after roughly two hours, detectable with
  `sdrctl dev sdr0 get reg rx 20` (openwifi verdict in [verification-log.md](verification-log.md);
  [openwifi README](https://github.com/open-sdr/openwifi/blob/master/README.md),
  [board README](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md)).
  A newer compact Buildroot image path carries an E200-specific SPL/MMC diagnostics patch
  written because "the ANTSDR E200 currently resets while entering the SPL MMC loader"
  ([patch](https://github.com/open-sdr/openwifi/blob/master/buildroot-external/patches/uboot/antsdr_e200/0002-antsdr-e200-spl-mmc-diagnostics.patch)).
- An E310-specific openwifi note warns that on that board the RF switch is fixed to the
  >3 GHz path, blocking below 3 GHz
  ([notes.md](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr/notes.md));
  the E200 has no such switch (section 2), so this quirk should not apply, but it has not
  been tested on an E200.

---

## 4. Default addresses, credentials and console

| Item | IIO / Pluto firmware | UHD firmware |
|---|---|---|
| Ethernet IP | 192.168.1.10 | 192.168.1.10 |
| Netmask / gateway | `netmask_eth`, `eth_gateway` = 192.168.1.1 | set by `S40network` |
| Login | root / `analog` | root / `microphase` |
| Hostname | `ant` (Buildroot `BR2_TARGET_GENERIC_HOSTNAME`), banner "Welcome to ANTSDR" | from the firmware environment |
| mDNS | `ant.local` | not documented |
| Serial console | 115200 8N1 on the CH340 (`ttyPS0`) | 115200 8N1 |
| Persistent IP | `fw_setenv ipaddr_eth <ip>` | `ip_set <ip>` then reboot (writes the I2C EEPROM at `/sys/bus/i2c/devices/0-0050/eeprom`) |
| MAC | `fw_setenv ethaddr xx:xx:...`; SD default in `uEnv.txt` is `00:0a:35:00:01:22` | n/a |
| Legacy USB gadget IPs | `ipaddr` (usb0) 192.168.2.1, `ipaddr_host` 192.168.2.10, inherited from Pluto and unreachable on the E200 because the Type-C port is UART-only | n/a |

Sources: [set_the_iio_firmware_ip.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_the_iio_firmware_ip.md),
[unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md),
the Buildroot `S40network` and defconfig in the
[antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch) e200 buildroot patch,
[antsdr_uhd host README](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/README.md)
(which also documents `ANTSDR_SSH_PASSWORD=microphase`), and
[SDR++ issue #1478](https://github.com/AlexandreRouma/SDRPlusPlus/issues/1478) for the
mDNS name and the network identity string.

`ifconfig` changes are lost on reboot on the IIO firmware; only `fw_setenv` persists
([set_the_iio_firmware_ip.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_the_iio_firmware_ip.md)).

Any host code that auto-discovers Pluto-class devices must match `ANTSDR` in the context
description as well as `PlutoSDR`, or use an explicit `ip:` URI: SDR++ logs
"Ignored IIO device ... (Analog Devices ANTSDR Rev.C (Z7020-AD9361))" for exactly this
reason ([issue #1478](https://github.com/AlexandreRouma/SDRPlusPlus/issues/1478)).

---

## 5. U-Boot environment variables

The environment is the configuration surface for the IIO and DroneID personalities.
`fw_printenv` / `fw_setenv` operate on `/dev/mtd1` offset 0, size 0x20000.

### 5.1 Enabling the second receiver (2r2t)

The stock IIO firmware boots 1R1T. Upstream Pluto U-Boot sets `mode=1r1t` in its default
environment, and the E200 U-Boot patch keeps ADI's logic: when `mode=1r1t` and the model
string matches, it removes `adi,2rx-2tx-mode-enable` from the device tree and forces the
DDS core to `adi,axi-ad9364-dds-6.00.a`; when `attr_name` and `attr_val` are both set it
applies `fdt set .../ad9361-phy@0 ${attr_name} ${attr_val}`
([u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch),
[linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch),
[upstream zynq-common.h](https://raw.githubusercontent.com/analogdevicesinc/u-boot-xlnx/pluto/include/configs/zynq-common.h)).

QSPI boot, from a shell on the board:

```sh
fw_setenv attr_name compatible
fw_setenv attr_val ad9361
fw_setenv compatible ad9361
fw_setenv mode 2r2t
reboot
```

or the same four as `setenv` plus `saveenv` and `reset` from the `ANTSDR> ` U-Boot prompt.
SD boot needs four edits to `uEnv.txt`: change `adi_loadvals` to use
`${devicetree_load_address}` instead of `${fit_load_address}`, change `mode=1r1t` to
`mode=2r2t`, add `run adi_loadvals` and `#{fit_config}` to the `sdboot` line, and append
`attr_name=compatible`, `attr_val=ad9361`, `compatible=ad9361`
([antsdr-fw-patch README](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md),
section "Support 2r2t mode"; the E200 documentation page defers to it via
[Antsdr-fw-patch.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-fw-patch.md)).

Verification after reboot: `iio_info -u ip:192.168.1.10` must list `voltage2` and
`voltage3` scan channels on `cf-ad9361-lpc`. Without them,
`rx_enabled_channels = [0, 1]` fails at buffer creation with
"No channel found with name: voltage1", which is exactly
[Pluto_Beamformer issue #2](https://github.com/jonkraft/Pluto_Beamformer).

This environment change is **only** needed on the IIO firmware. The UHD firmware's E200
bitstream is built with `TARGET_B210=1` and reports two radio chains, and openwifi's E200
device tree already carries `adi,2rx-2tx-mode-enable`
([antsdr_e200.tcl](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/antsdr_e200.tcl),
[openwifi devicetree.dts](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/devicetree.dts)) (verified: `rf-ports`).

One asymmetry to plan around: in the IIO HDL the FPGA RX FIR decimator is connected only
to ADC channel 0; channel 1 goes straight to `util_cpack2`
([HDL patch](https://github.com/MicroPhase/antsdr-fw-patch), `projects/e200/system_bd.tcl`).
So FPGA decimation, which is what makes the very low "filter auto" rates possible
([AntsdrE310_gnurdio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/AntsdrE310_gnurdio.md)),
is asymmetric in 2R2T. For any two-channel work, avoid FPGA decimation entirely, keep the
sample rate above the range where the decimator engages, and decimate on the host instead.

### 5.2 Variables worth knowing

| Variable | Default | Effect | Source |
|---|---|---|---|
| `mode` | `1r1t` | `2r2t` enables RX2/TX2 | [fw-patch README](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md) |
| `attr_name` / `attr_val` / `compatible` | unset; DT base is `adi,ad9364` | rewrites the `ad9361-phy` compatible string | [u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch) |
| `ipaddr_eth` | 192.168.1.10 | persistent eth0 address | [set_the_iio_firmware_ip.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_the_iio_firmware_ip.md) |
| `netmask_eth`, `eth_gateway` | gateway 192.168.1.1 | network config read by `S40network` | [antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch) buildroot patch |
| `ethaddr` | `00:0a:35:00:01:22` on SD | MAC address | [set_the_iio_firmware_ip.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_the_iio_firmware_ip.md) |
| `maxcpus` | `1` | in `bootargs`; setting 2 should bring up the second Cortex-A9 (inference from the bootargs, not documented by the vendor) | [u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch) |
| `fit_size` | written by `update_frm.sh` | size of the flashed FIT image | buildroot patch in [antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch) |

DroneID firmware adds its own set, written once from the QSPI Pluto personality over the
serial console
([alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid)):

| Variable | Documented value | Meaning |
|---|---|---|
| `tcp_serverip` | host running `dji_receiver.py` | where the board pushes reports |
| `tcp_serverport` | `52002` | must match `--listen-port` |
| `udp_dest_ip` / `udp_dest_port` | `52002` | alternative UDP transport |
| `gain_mode` | `fast_attack` | AD9361 AGC mode used for burst detection |
| `heart_beate_time` | `30` | heartbeat interval, spelling as in the firmware |
| `api_host`, `request_time`, `auth_secret`, `token_secret` | site-specific | the O4 online decryption service |
| `device_serial` | e.g. `antsdr_e200` | identifier in the reports |
| `device_mode` | `auto` | frequency plan; `auto` hops 5.8 GHz channels |

The legacy firmware instead listens as a TCP **server** on 41030 with binary frames
(`serial[64]`, `device_type[64]`, doubles for pilot/drone/home latitude and longitude,
height, altitude, frequency, speeds, then `rssi`), which is what Kismet's
`capture_antsdr_droneid` parses
([capture_antsdr_droneid.c](https://github.com/kismetwireless/kismet/blob/master/capture_antsdr_droneid/capture_antsdr_droneid.c)).
**(unverified, round 1)** The O4 firmware in `auto` mode appears from its strings to
monitor only 2434.5, 5756.5, 5776.5 and 5816.5 MHz, running 1R1T at a 61.44 MSPS path
clock, which would leave the 2.4 GHz DroneID hop set largely uncovered
([alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid)); the
legacy firmware is described as using an FPGA correlator at `/dev/my-axi-droneid-filter0`.
Neither was re-checked adversarially. See [landscape.md](landscape.md) and
[ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md).

---

## 6. Digital interface, sample-rate ceilings and 2-channel limits

The AD936x-to-FPGA link on the E200 is a **12-bit single-ended CMOS, DDR, single-port**
interface, not LVDS. Both firmware families configure it that way: the IIO HDL sets
`axi_ad9361` `CONFIG.CMOS_OR_LVDS_N = 1`, `MODE_1R1T = 0`, `ADC_INIT_DELAY = 21` and
constrains `rx_clk` to a 16.27 ns period, that is 61.44 MHz
([HDL patch](https://github.com/MicroPhase/antsdr-fw-patch), `projects/e200`), and the UHD
driver selects `AD9361_DDR_FDD_LVCMOS` with RX and TX data delay 0xF
([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)).

Because both channels are time-multiplexed on the same 12-bit DDR bus, the ceilings are:

| Configuration | Master clock / sample rate ceiling | Source |
|---|---|---|
| 1R1T | 61.44 MSPS | `AD9361_MAX_CLOCK_RATE = 61.44e6`, rx_clk constraint 16.27 ns |
| 2R2T | 30.72 MSPS **per channel** | `enforce_tick_rate_limits`: max tick = `AD9361_MAX_CLOCK_RATE / 2` for 2 channels; `set_auto_tick_rate` uses `61.44e6 / num_chans` ([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp), [ant_io_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_io_impl.cpp)) |
| Minimum | 220 kHz master clock under UHD; below that the AD9361 needs the FIR / FPGA decimator | `AD9361_MIN_CLOCK_RATE = 220e3` (`ad9361_device.cpp`, read from GitHub master via the UHD driver) |
| pyadi-iio floor | the `sample_rate` setter refuses below 521 kSPS and loads a FIR (decimation 4 at or below 20 MSPS, otherwise 2) | [adi/ad936x.py](https://github.com/analogdevicesinc/pyadi-iio/blob/main/adi/ad936x.py) |
| Vendor headline | "200 kS/s - 61.44 MS/s", 12-bit | [Crowd Supply](https://www.crowdsupply.com/microphase-technology/antsdr-e200) / [CNX Software](https://www.cnx-software.com/2023/07/03/antsdr-e200-gigabit-ethernet-connected-sdr-with-xilinx-zynq-soc-fpga-supports-70-mhz-6-ghz-range/) (snippets) |

UHD additionally inherits the B210 rule that 2 RX with 1 TX, or 1 RX with 2 TX, is
impossible ([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp));
irrelevant for passive work.

The IIO device tree ships a default rate path of 983.04 / 245.76 / 122.88 / 61.44 / 30.72
/ 30.72 MHz, that is **30.72 MSPS**, with 18 MHz RF bandwidth, RX LO 2.4 GHz, TX LO
2.45 GHz, TX attenuation 10000 mdB, slow-attack AGC on both RX chains
(`gc-rx1-mode = gc-rx2-mode = 2`), FDD mode, RX RF port input select 0 (RX1A/RX2A
balanced, locked), SPI at 10 MHz
([linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch),
`zynq-e200.dtsi`). Samples are 12-bit in a 16-bit container; the vendor libiio demo notes
that TX samples must be MSB-aligned, shifted left by 4
(`demo/iio/main.c` in [antsdr_doc_en](https://github.com/MicroPhase/antsdr_doc_en)).

LVDS is worth naming only to dismiss it: the LibreSDR project, a Zynq-7020 + AD9361 board
of the same class, "uses AD9361 LVDS mode to maximize 2T2R"
([libresdr](https://github.com/hz12opensource/libresdr)), but the E200 HDL as shipped is
CMOS in both personalities, so that route would require a new FPGA build and is untested.

---

## 7. Host streaming: what each personality really sustains

This is the single most consequential set of numbers for the toolkit, and it was checked
adversarially (verified: `host-streaming-tiers`).

**The physical ceiling.** The UHD path uses `udp_simple::mtu` = 1472-byte UDP payloads in
1500-byte frames with a 16-byte CHDR header and no jumbo frames. That gives 81,274
packets/s times 364 sc16 samples = **29.6 MSPS** maximum continuous single-channel sc16,
39.4 MSPS at sc12 and 59.2 MSPS at sc8. All three are **derived**, and they rest on the
16-byte header assumption behind the 364-sample figure (section 8): a larger CHDR header
lowers all three proportionally. 40 MSPS sc16 is 1.28 Gbit/s and is impossible on
any firmware ([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp),
[ant_io_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_io_impl.cpp)).
The Zynq-7000 GEM used by the IIO path has no jumbo-frame capability at all
(`zynq_config` in [macb_main.c](https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/cadence/macb_main.c)
lacks `MACB_CAPS_JUMBO`, which the ZynqMP config has).

**The architecture split**, in MicroPhase's own words on the openwifi board page: "For
some SDR applications, the Ethernet may be required to transmit baseband signals above
20MSPS sample rate. In this case, the bandwidth of the Ethernet will reach 80MB/s. If the
Ethernet on the PS side wants to run at this bandwidth, it will take up a lot of CPU
resources and the bandwidth is still difficult to meet. For this reason, we moved the
network port to the PL side. But this has no effect on IIO-based SDR drivers, because we
still use ZYNQ's GEM controller ... When we moved the ethernet to PL, the ANTSDR-E200
could support UHD driver."
([board README](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md)).
The openwifi-hw copy of the same text quotes 15 MSPS / 60 MB/s instead of 20 MSPS /
80 MB/s; the evidence does not resolve which figure is current. The UHD FPGA confirms the
split: `e200_eth_if_core.v` is an Ettus-derived `PROTOCOL="1GbE"` RGMII MAC with a CHDR
path and only an internal `arm_eth` port back to the PS
([e200_eth_if_core.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/e200_eth_if_core.v)),
while the IIO firmware routes everything through `&gem0` with `phy-mode = rgmii-rxid`
([linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch)).

| Path | Figure | Nature | Source |
|---|---|---|---|
| Vendor selection table | 20 MSPS "transmission bandwidth to host" (E310: 10 MSPS, E316: 20 MSPS) | table entry, no test data | [AntsdrE200_RF_parameters.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md) |
| IIO, stock firmware | roughly **47-52 MiB/s = 11-13 MSPS** sc16, 1 channel, CPU-bound in `iiod` | community measurement on a Zynq-7000/ANTSDR; the quoted thread values are 48 MiB/s (libiio 0.23 both sides) and 52 MiB/s (1.0-dev `iiod`, 0.23 host) | [libiio discussion #875](https://github.com/analogdevicesinc/libiio/discussions/875) (verified: `host-streaming-tiers`) |
| IIO, kernel/iiod tuned | 82-84 MiB/s = **~20-22 MSPS** with larger blocks, `-O3` kernel, `iiod` pinned to a core | same thread; also LibreSDR "20 MSPS without overclock, compared to ~10 MSPS stock" | [#875](https://github.com/analogdevicesinc/libiio/discussions/875), [libresdr](https://github.com/hz12opensource/libresdr) |
| IIO, overclocked | **27.5 MSPS** at 1100 MHz CPU / 750 MHz DDR | LibreSDR only, not ANTSDR firmware | [libresdr](https://github.com/hz12opensource/libresdr) |
| UHD, vendor stress test | 2 devices at 7.68 MSPS each = "about 492 Mbit/s of aggregate sc16 RX payload for two devices" over 14400 s | a default, explicitly not a maximum | [host README](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/README.md), [antsdr_dual_e200_stress.sh](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/utils/antsdr_dual_e200_stress.sh) |
| UHD, wire formats | sc16 / sc12 / fc32 / sc8 all implemented in driver and FPGA | `SR_RX_FMT` 0/1/2/3, `chdr_16sc_to_8sc.v` / `chdr_16sc_to_12sc.v` in the FPGA manifest; **no published throughput measurement** | [ant_io_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_io_impl.cpp) |
| Two channels | halve the per-channel rate: 14.8 MSPS sc16 wire maximum, ~10 MSPS per channel practical against the 20 MSPS vendor figure | arithmetic on the above | (verified: `host-streaming-tiers`) |
| Snapshot mode | any AD9361 rate up to 61.44 MSPS into a DDR buffer, then a slow transfer | the DMA lands in DDR first on both firmwares | (verified: `host-streaming-tiers`) |

Two corrections the research record needed:

- **"libiio 1.0 gives about 20 MSPS" is wrong.** There is no v1.x release: the newest tag
  is v0.26 from 2024-09-25, and the README says the main branch "contains what will
  eventually become libiio v1.0"
  ([libiio tags](https://github.com/analogdevicesinc/libiio/tags),
  [libiio](https://github.com/analogdevicesinc/libiio)). The 1.0-dev `iiod` alone moved
  the ANTSDR figure from 48 to 52 MiB/s; the 82-84 MiB/s result came from kernel flags,
  block size and core pinning
  ([#875](https://github.com/analogdevicesinc/libiio/discussions/875)). The stock ANTSDR
  IIO firmware is built on plutosdr-fw v0.39, which ships **libiio v0.26 and Linux 6.1**
  ([plutosdr-fw v0.39](https://github.com/analogdevicesinc/plutosdr-fw/releases/tag/v0.39)),
  untuned; an open request for an overclocked build has had no maintainer reply
  ([issue #29](https://github.com/MicroPhase/antsdr-fw-patch/issues/29)). Note a small
  unit disagreement inside the record itself: the round-1 reading of the same thread
  reports the stock figure as "~44.7 MB/s (~11 MSPS sc16, 1 ch)" while the verification
  pass quotes the thread as 48 and 52 **MiB/s**. The table above uses the verification
  pass's numbers; either way the conclusion, 11-13 MSPS, is the same.
- **The "40 MSPS from a Zynq-7020" claim in RF-Vision-UAV-Tracker is a snapshot rate, not
  a stream.** That project sets `sample_rate = 40e6`, `rx_rf_bandwidth = 40e6` and
  `rx_buffer_size = 2621440` on `adi.Pluto`, i.e. 65.5 ms and 10.5 MB per capture, with
  40-50 ms PLL settling sleeps and discarded buffers after every retune
  ([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)). At 50-108
  MB/s of transfer that 10.5 MB snapshot takes 97-210 ms, a 24-40 % duty cycle
  (verified: `host-streaming-tiers`). It is the right pattern for the E200, and it is not
  continuous streaming.

Host-side tuning that follows from the UHD driver's constants: the data transports are
created with an **empty** hints dictionary, so the `recv_buff_size` and `recv_frame_size`
device arguments never reach the data sockets. Tune `net.core.rmem_max` on the host
instead and leave those keys out
([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)).

---

## 8. UHD path: device args, ports, build

Build the MicroPhase fork into a private prefix and never mix it with a distribution UHD:

```sh
cmake -S host -B build-antsdr -DENABLE_ANT=ON -DENABLE_USB=ON \
      -DENABLE_PYTHON_API=ON -DCMAKE_INSTALL_PREFIX=/opt/antsdr-uhd
```

`ENABLE_ANT` has a build-time dependency on `ENABLE_USB`; the fork is UHD **4.1.0.0** and
must not be mixed with a system UHD 4.9 because of the ABI
([host README](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/README.md);
version from `UHDVersion.cmake`). Packaging notes report that "as of boost 1.85.0, the
package can't compile since it needs boost/filesystem/convenient.hpp" and that GNU Radio
must be rebuilt against this libuhd for the `uhd` blocks to see the E200
([AUR libuhd-antsdr-git](https://aur.archlinux.org/packages/libuhd-antsdr-git), snippet).

| Item | Value | Source |
|---|---|---|
| Device args | `type=ant`, `addr=`, `product=E200`, `serial`, `name`, `master_clock_rate` (disables auto tick rate), `enable_user_regs` | [ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp) |
| Typical invocations | `uhd_find_devices --args=addr=192.168.1.10`; `uhd_usrp_probe --args=addr=192.168.1.10,product=E200` (give `product=` when `addr=` is given directly) | [host README](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/README.md) |
| UDP ports | discovery 49100, control 49200, TX data 49202 and 49203, RX data 49204 (driver comment: "ports 49200-49210") | [ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp) |
| Discovery handshake | 8-byte hello with ids `'1'`, `'m'`, `'9'`, `'j'`; an 8-byte `'r'` dispatcher packet on the RX socket | same |
| Transports | 1472-byte frames, 16 send and 16 receive frames, 1e6-byte socket buffers when the key is absent | same |
| `spp` | `min(4092, (recv_frame_size - header) / bytes_per_item)`, about 364 sc16 / 485 sc12 / 728 sc8 samples per packet (**derived**, assuming a 16-byte CHDR header, i.e. `max_if_hdr_words32 = 7` on top of a 1472-byte UDP payload; the deep read flags the header size as an assumption) | [ant_io_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_io_impl.cpp) |
| RX flow control | E200 only: window 128 packets, credit every 16 packets, sent as CHDR context packets on the control socket with SID 0x11/0x21 | same |
| Default tick rate | 16 MHz with automatic selection (`DEFAULT_TICK_RATE 16e6`, `DEFAULT_DECIM 128`) | [ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp) |
| Cross-process lock | `flock` on `/run/lock/iqtaxi-device-<hash of addr>.lock`; a second process gets "ANTSDR device \<addr\> is busy" | same, commit 2026-08-25 |
| Clock / time sources | `clock_source` internal or external, `time_source` none, internal or external, both on the single MMCX jack; sensor `ref_locked` | [AntsdrE200_UHD.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD.md), [ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp) |

What the vendor documentation shows `uhd_usrp_probe` printing (a UHD 3.15-era output; the
documentation does not say which SD image produced it)
([AntsdrE200_UHD.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD.md),
Chinese mirror [AntsdrE200_UHD_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD_cn.md)):
`[E200] _Product B205MINI(COMPATIBLE)`, master clock "automatic" defaulting to 16 MHz,
mboard `ANTSDR-EXXX`, "No mboard EEPROM found", FPGA Version 7.0, RX DSP frequency range
-8.000 to 8.000 MHz, RX frontend antennas `TX/RX, RX2`, RX frequency range
**50.000 to 6000.000 MHz**, RX gain range PGA 0.0 to 76.0 dB in 1.0 dB steps, bandwidth
200 kHz to 56 MHz, sensors `temp`, `rssi`, `lo_locked`; TX gain 0.0 to 89.8 dB in 0.2 dB
steps. Note the FPGA/host coupling: current `master` expects
`B200_FPGA_COMPAT_NUM = 16` (the B210 flow with source flow control) while the documented
probe output reports FPGA Version 7.0 (the B205 compat-7 flow), so host and firmware must
be built from matching revisions or probing throws "Expected FPGA compatibility number".
Which SD image that probe output came from is **not stated in any source**, so this is a
reason to check `FPGA Version` on the unit before assuming a mismatch, not a statement
that the shipping v1.0 image is on compat 7
([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)).
Also note the probe's 50 MHz lower edge against the datasheet 70 MHz; the evidence does
not explain the difference.

---

## 9. IIO path: pyadi-iio attribute cheat sheet

The E200's IIO firmware exposes exactly the device names pyadi-iio's `adi.ad9361` class
expects: control device `ad9361-phy`, RX data device `cf-ad9361-lpc`, TX data device
`cf-ad9361-dds-core-lpc`
([adi/ad936x.py](https://github.com/analogdevicesinc/pyadi-iio/blob/main/adi/ad936x.py);
the E200 `iio_attr -d` listing on firmware v0.34 is `ad9361-phy`, `mp-gpio`, `xadc`,
`ref-pll`, `cf-ad9361-dds-core-lpc`, `cf-ad9361-lpc`, per
[set_gpio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_gpio.md)).
Use `adi.ad9364('ip:192.168.1.10')` for 1R1T and `adi.ad9361(...)` once 2r2t is enabled;
`adi.Pluto` also works with an explicit `uri`.

| Attribute | Backing IIO attribute | Notes |
|---|---|---|
| `uri` | context | `ip:192.168.1.10` (or `ip:ant.local`) |
| `rx_enabled_channels` | scan channels | `[0]` = RX1 (SMA), `[0, 1]` = RX1 + RX2 (IPEX); validated against 4 channels / 2 |
| `sample_rate` | `voltage0` `sampling_frequency` | setter refuses below 521 kSPS and pushes a FIR: decimation 4 at or below 20 MSPS, otherwise 2; pyadi's own tests sweep 2.084 to 61.44 MSPS |
| `rx_rf_bandwidth` | `voltage0` `rf_bandwidth` | analog filter; set roughly equal to `sample_rate` |
| `rx_lo` | `altvoltage0` `frequency` | 70 MHz to 6 GHz in the pyadi test sweep, 1 Hz steps per the GNU Radio block |
| `gain_control_mode_chan0` / `_chan1` | `gain_control_mode` | `manual`, `slow_attack`, `hybrid`, `fast_attack`. **Must be set to `manual` before any gain write**: the `rx_hardwaregain_chanX` setter is silently skipped otherwise |
| `rx_hardwaregain_chan0` / `_chan1` | `hardwaregain` | 0 to 76 dB in 1 dB steps **as quoted from the UHD probe output** for FE-RX1; that range is a UHD-personality figure and is **not confirmed on the IIO personality**, where the only sourced numbers are the -3 to 70 dB used by ADI's own scripts. Read the attribute's `_available` range on the board (section 15) |
| `tx_hardwaregain_chan0` / `_chan1` | `hardwaregain` | an **attenuation on the IIO path, expressed as a negative number**: set `-89` for passive operation and never call `tx()` (section 2). Do not confuse this with the UHD TX *gain* range of 0.0 to 89.8 dB, where maximum attenuation is 0.0 |
| `rx_buffer_size` | n/a | only read when the buffer is created on the first `rx()`; call `rx_destroy_buffer()` before changing it |
| `rx()` | | returns a list of two complex arrays with two channels enabled, a single array with one; raw int16 counts unless `rx_output_type='SI'` |
| `_rxadc.set_kernel_buffers_count(1)` | libiio v0 API | avoids stale buffers; with libiio v1 bindings set `_rx_buffer_num_blocks` (default 4) before the first `rx()` |

Sources: [adi/ad936x.py](https://github.com/analogdevicesinc/pyadi-iio/blob/main/adi/ad936x.py),
`adi/rx_tx.py` and `adi/compat.py` in [pyadi-iio](https://github.com/analogdevicesinc/pyadi-iio),
[AntsdrE310_gnurdio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/AntsdrE310_gnurdio.md)
for the gain-mode list, and [AntsdrE200_UHD.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD.md)
for the gain range. The 12-bit scaling constant used by ADI's own examples is 2**11
("Pluto is a signed 12 bit ADC", [Pluto_Beamformer](https://github.com/jonkraft/Pluto_Beamformer)).

Trap carried over from ADI's demo scripts: `sdr.gain_control_mode = 'manual'` without the
`_chanX` suffix is **not** a pyadi-iio property on `adi.ad9361`; only
`gain_control_mode_chan0` and `gain_control_mode_chan1` exist. Writing the unsuffixed name
is a silent no-op, after which the gain writes are also silently skipped and the two
channels can end up on divergent AGC gains
([adi/ad936x.py](https://github.com/analogdevicesinc/pyadi-iio/blob/main/adi/ad936x.py),
[Pluto_Beamformer](https://github.com/jonkraft/Pluto_Beamformer)).

GNU Radio 3.10 and later ships `gr-iio` in the core distribution; the PlutoSDR Source
block exposes RF bandwidth, sample rate in MSPS, LO with 1 Hz steps, per-loop tracking
switches for quadrature, RF DC and BB DC, the four gain modes and an FIR filter file, and
"Filter auto" is what enables the very low rates
([AntsdrE310_gnurdio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/AntsdrE310_gnurdio.md)).

---

## 10. AD936x caveats that bite

**Initialisation calibrations re-run on retune.** Writing the LO or the sample rate, even
with the same value, makes the driver re-run the init calibrations, named in ADI's own
answer as RX QEC, RF DC and BBF tune. That is the mechanism behind the phase instability
in section 11 and it is also why a retune must be followed by discarded buffers
(ADI EngineerZone thread
[601154](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/f/q-a/601154/adalm-pluto-revc-phase-between-rx1-rx2-is-not-stable),
reachable only as a search snippet because the domain is blocked in the research sandbox;
verified: `rf-ports`). ADI's own example code discards buffers with the comment "let Pluto
run for a bit, to do all its calibrations, then get a buffer"
([Pluto_Beamformer](https://github.com/jonkraft/Pluto_Beamformer)), and
RF-Vision-UAV-Tracker sleeps 40-50 ms after each `rx_lo` write and discards one to two
buffers per retune
([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)).

**Quadrature tracking perturbs phase.** ADI's FMComms5 phase-sync routine explicitly
writes `quadrature_tracking_en = 0` on `in voltage0` of both PHYs before it measures
anything
([ad9361_fmcomms5_phase_sync.c](https://github.com/analogdevicesinc/libad9361-iio/blob/main/ad9361_fmcomms5_phase_sync.c)),
and ADI's DoA whitepaper lists the phase relationship as changing "when LO is changed,
sample rate is changed, gain (in some cases) is changed, and even during quadrature
tracking"
([doa_whitepaper.pdf](https://wiki.analog.com/_media/resources/tools-software/linux-software/doa_whitepaper.pdf), snippet only).
For phase-sensitive work, disable quadrature tracking during calibration and verify first
that the attribute exists on the E200 driver.

**DC offset and LO leakage:** the IIO firmware exposes RF DC and BB DC tracking loops
through the GNU Radio PlutoSDR Source block
([AntsdrE310_gnurdio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/AntsdrE310_gnurdio.md)),
and one third-party FPV pipeline inserts a `dc_blocker_cc(32, True)` for non-UHD radios
while sending the UHD path straight through
([fpv-sdr](https://github.com/lukeswitz/fpv-sdr)). No source in this research record
measures the residual DC or LO-leakage level on an E200, so the magnitude is unknown; see
Gaps.

**Close-in phase noise** may be worse than a Pluto's; see section 1.2.

**AGC choice.** The device tree default is slow-attack AGC on both RX chains, while
MicroPhase's own DroneID firmware is configured with `gain_mode fast_attack` for burst
detection ([linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch),
[alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid)). Any
phase-coherent work needs AGC off and identical manual gains on both channels
(verified: `rf-ports`).

---

## 11. Coherence facts for direction finding

The physics is favourable and the calibration discipline is the hard part.

- **Both RX chains sit behind one AD9361 RX RFPLL**, so they are coherent and sampled on
  the same clock. ADI confirms it directly for the Pluto rev C, the same single-chip 2RX
  topology: "when asked about coherence of the two receive channels, the answer is yes,
  they are coherent" (EngineerZone
  [566569](https://ez.analog.com/adieducation/university-program/f/q-a/566569/pluto-rev-c-coherent-reception-using-2-rx-channels),
  snippet only) (verified: `rf-ports`).
- **The offset is fixed but unknown at a given tune, and it moves when you retune.** ADI's
  answer on thread [601154](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/f/q-a/601154/adalm-pluto-revc-phase-between-rx1-rx2-is-not-stable)
  states that the relative phase stays constant as long as the LO and sample rate are not
  touched, and that writing either, even with the same value, can change it. The header of
  `libad9361` says the same for its own sync: "Phase synchronization is valid until the
  LOs are retuned or sample rates change or gains are modified"
  ([ad9361.h](https://github.com/analogdevicesinc/libad9361-iio/blob/main/ad9361.h)).
  ADI's DoA whitepaper adds gain and quadrature tracking to the list
  ([whitepaper](https://wiki.analog.com/_media/resources/tools-software/linux-software/doa_whitepaper.pdf), snippet).
  Jon Kraft's 2.3 GHz time-delay script hard-codes `invert_Rx = -1` "to compensate for a
  180 deg phase shift on the LO divider" and his MVDR script hard-codes a
  `phase_offset = -0.3` rad, both signs of a repeatable offset at a fixed state
  ([Pluto_Beamformer](https://github.com/jonkraft/Pluto_Beamformer)).
- **Magnitude is unmeasured.** No source in this record quantifies the per-retune jump on
  an E200, and the gain dependence is asserted from first principles only
  (verified: `rf-ports`). ADI's FMComms5 code rotates RX1 and RX2 of one chip by a single
  value and measures only one channel per chip, implying the intra-chip pair is treated as
  a unit at a given tune, that is, not the 0-360 degree random LO-divider effect seen
  between chips
  ([ad9361_fmcomms5_phase_sync.c](https://github.com/analogdevicesinc/libad9361-iio/blob/main/ad9361_fmcomms5_phase_sync.c)).
- **`libad9361`'s phase sync cannot be used here.** `ad9361_fmcomms5_phase_sync()`
  hard-codes six FMCOMMS5 device names (`cf-ad9361-A`, `cf-ad9361-B`, `ad9361-phy-B` and
  so on) and returns `-ENODEV` on a single-AD9361 board; it also relies on ADG918 RF
  switches and FPGA loopback registers that the E200 does not have
  ([ad9361_fmcomms5_phase_sync.c](https://github.com/analogdevicesinc/libad9361-iio/blob/main/ad9361_fmcomms5_phase_sync.c)).
  The calibration has to be re-implemented as a cross-spectrum phase measurement.
- **Calibration must use an external source**, because the toolkit is passive and may not
  transmit a loopback tone ([ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md)):
  a splitter with matched-length cables into the SMA and the U.FL pigtail, which is what
  ADI's own test rig does, or a cooperative beacon at a known bearing
  (verified: `rf-ports`).
- **Array geometry.** Half-wavelength spacing is 62.5 mm at 2.4 GHz and 25.8 mm at 5.8 GHz
  (`d = c / (2 f)`, the formula used in
  [Pluto_MVDR_DOA.py](https://github.com/jonkraft/Pluto_Beamformer/blob/main/Pluto_MVDR_DOA.py)),
  so one spacing cannot serve both bands unambiguously. KrakenSDR's array guidance applies
  directly: "the spacing multiplier must be kept under 0.5 to avoid ambiguities", keep it
  "above around 0.2 and closer to 0.5", a linear array is "only valid for 180 degrees, and
  there is no way of knowing if the signal is coming from in front, or behind", cables must
  be length-matched "to a tolerance within a centimeter" up to about 900 MHz, and
  "bearings will always have inaccuracies of several degrees"
  ([KrakenSDR antenna wiki](https://github.com/krakenrf/krakensdr_docs/wiki/04.-Antenna-Array-Setup)).
- **Rate budget for two channels**: 30.72 MHz master clock maximum, and against the
  20 MSPS host figure roughly 10 MSPS per channel. That is below the 15.36 MSPS a DroneID
  OcuSync 2 burst needs, so two-channel DroneID direction finding requires on-board
  preprocessing or burst capture rather than continuous streaming
  (verified: `host-streaming-tiers`, `rf-ports`; see
  [ADR-0009](../docs/decisions/ADR-0009-localisation-deferred.md)).
- For TDOA across several E200s, `dronelocate`'s UHD source is written for "B210-class
  hardware" with `channels=[0, 1]` for the coherent pair and warns that without a
  `gps_locked` sensor "TDOA will need an external PPS on the PPS input, or reference-emitter
  calibration" ([dronelocate](https://github.com/cherubimro/dronelocate)) - which is exactly
  the E200's situation, since it has no GPSDO (section 1.2).

---

## 12. GPIO and other on-board resources

On the IIO firmware v0.39 the header GPIOs are exposed as EMIO pins 35-40, that is Linux
GPIO numbers 995-1000, either through `/sys/class/gpio` or through the IIO device
registered by `mpiio_io.c` under the name `ant-gpio` (compatible `microphase,mpiio`), with
`in_voltage0_raw` as the value bitmask and `in_voltage1_raw` as the direction bitmask
(1 = output). Only six of the eight header pins remain usable: GPIO_06 and GPIO_07
(package pins Y6 and Y9) are reassigned to EMIO UART1 RX/TX in the v0.39 HDL. On the
older v0.34 firmware the documentation describes eight GPIOs at 995-1002 and an IIO device
named `mp-gpio`
([set_gpio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_gpio.md),
[linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch),
[HDL patch](https://github.com/MicroPhase/antsdr-fw-patch) `projects/e200/system_constr.xdc`).
The UHD FPGA declares `fp_gpio[9:0]` internally but the top-level port list has no GPIO
header pins, so **the UHD personality exposes no physical GPIO**
([antsdr_e200.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/antsdr_e200.v)).

Other IIO devices on the board: `ad9361-phy`, `xadc`, `ref-pll`, `cf-ad9361-lpc`,
`cf-ad9361-dds-core-lpc`, plus `ad5660mp` and `ant-gpio`/`mp-gpio`
([set_gpio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_gpio.md),
[Antsdr-Clock-calibration_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration_cn.md)).
An I2C EEPROM (24c256 at address 0x50 on i2c0) is declared in the IIO device tree and used
by the UHD firmware's `ip_set` tool to persist the address
([linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch),
[firmware README](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/README.md)).

---

## 13. Toolchains, if firmware ever has to be rebuilt

| Target | Toolchain | Command | Source |
|---|---|---|---|
| IIO firmware (antsdr-fw-patch v0.39) | Vivado **2023.2** plus Linaro GCC 7.3-2018.05 as a Buildroot external toolchain (the AMD/Xilinx GCC is incompatible with Buildroot) | `export TARGET=e200; sh patch.sh e200; cd plutosdr-fw; make; make sdimg` | [antsdr-fw-patch README](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md) |
| UHD firmware | Vivado and SDK **2019.1**, part `xc7z020clg400-2`, Buildroot rootfs (no PetaLinux) | `firmware/scripts/build_image.sh e200` or `make TARGET=e200 image` | [firmware README](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/README.md) |
| openwifi | Vivado **2021.1** for v1.4.0, **2022.2** for v1.5.0; no Vivado licence needed for the xc7z020 | per openwifi build docs | [openwifi releases](https://github.com/open-sdr/openwifi/releases), [openwifi](https://github.com/open-sdr/openwifi) |
| Standalone / no-OS | Vivado and Vitis **2021.1** | `source ../scripts/adi_make.tcl`, `adi_make::lib all`, `source ./system_project.tcl` in `hdl/project/antsdre200` | [antsdr_standalone](https://github.com/MicroPhase/antsdr_standalone) |

Pinned submodule state of antsdr-fw-patch v0.39: plutosdr-fw v0.39 (commit 9e90bce), hdl
065c8f1, linux f3da30d, u-boot 90401ce, buildroot e783aad
([antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch)). The UHD firmware's
`VERSIONS` file records device-fw v0.34-dirty, hdl 2019_r2, linux adi-xilinx-2020.1,
u-boot v0.20-PlutoSDR
([antsdr_uhd](https://github.com/MicroPhase/antsdr_uhd) buildroot board files).

Licence position, which decides what may be vendored: `antsdr_doc_en` and `antsdr_uhd` are
GPL-3.0 (parts of the UHD FPGA are LGPL-3.0-or-later), `antsdr-fw-patch` has no LICENSE
file and patches GPL-2 kernel and U-Boot trees, `libiio` is LGPL-2.1, `pyadi-iio` is the
non-OSI "ADI BSD" with an "must be connected to, run on or loaded to an Analog Devices
Inc. component" clause, and `Pluto_Beamformer` has no LICENSE file at all. So: UHD only as
an optional separate process, libiio dynamically linked, pyadi-iio as a pip dependency,
and ADI's beamformer scripts re-implemented rather than copied. See
[ADR-0003](../docs/decisions/ADR-0003-third-party-code-and-licences.md).

---

## 14. Setup checklist for day one

1. **Inventory.** Read the marking on U11 (AD9361 or AD9363, section 1.1). Check whether
   a U.FL-to-SMA pigtail is in the box (section 2). Note whether a 10 MHz or GPSDO
   reference is available.
2. **Serial console first.** Type-C to the host, 115200 8N1, CH340 driver. Leave the DIP
   switch on QSPI. Power up: the green LED should blink
   ([unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md)).
3. **Log in** as root / `analog` and record the firmware state: `fw_printenv` (whole
   environment), `cat /proc/version`, `ls /sys/bus/iio/devices/`.
4. **Network.** Set the host NIC to 192.168.1.100/24 with gateway 192.168.1.1, the host
   example given by the vendor
   ([unboxing page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md));
   the board is 192.168.1.10. Confirm the link negotiates **1000 Mbit/s**; the UHD firmware refuses
   anything slower ([antsdr_uhd README](https://github.com/MicroPhase/antsdr_uhd)).
   Change the board address, if needed, with `fw_setenv ipaddr_eth <ip>` and reboot, not
   with `ifconfig`.
5. **Discover over IIO.** `iio_info -S` should show
   `[ip:ant.local] 192.168.1.10 (Analog Devices ANTSDR Rev.C (Z7020-AD9361))`; then
   `iio_info -u ip:192.168.1.10` and check for `ad9361-phy`, `cf-ad9361-lpc`,
   `cf-ad9361-dds-core-lpc`, `ad5660mp`, `xadc`, `ant-gpio`
   ([issue #1478](https://github.com/AlexandreRouma/SDRPlusPlus/issues/1478),
   [set_gpio.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_gpio.md)).
6. **First capture, single channel, safe rate.** `adi.ad9364('ip:192.168.1.10')`,
   `sample_rate = 5e6`, `rx_rf_bandwidth = 5e6`, `rx_lo = 2.437e9`,
   `gain_control_mode_chan0 = 'manual'` **before** `rx_hardwaregain_chan0 = 40`,
   `tx_hardwaregain_chan0 = -89` (maximum attenuation, section 2),
   `rx_buffer_size = 2**18`, discard 20 buffers, then read.
   Verify the samples look like 12-bit counts, within roughly +/-2048.
7. **Throughput baseline on the stock IIO firmware.** 60 s of continuous RX at 5, 7.68,
   10, 15.36 and 20 MSPS with `iio_readdev -b 1048576`, recording where overruns start.
   Expect trouble somewhere above 11-13 MSPS
   ([libiio #875](https://github.com/analogdevicesinc/libiio/discussions/875)).
8. **Enable the second receiver** with the QSPI `fw_setenv` sequence in section 5.1,
   reboot, and confirm `voltage2` and `voltage3` appear. Fit the pigtail on J6 (RX2).
9. **Reference clock**, if one is available. SMA-to-MMCX into the "10/PPS" jack, then the
   `ad5660mp` procedure in section 1.2; require `in_voltage_dac_locked == 1`. Record which
   reference is connected, because PPS and 10 MHz share the jack.
10. **Optional UHD personality.** Build the fork into `/opt/antsdr-uhd` (section 8), write
    the v1.0 `build_sdimg.zip` files to a FAT32 SD, move the DIP switch to SD, boot, log in
    as root / `microphase`, then `uhd_find_devices --args=addr=192.168.1.10` and
    `uhd_usrp_probe --args=addr=192.168.1.10,product=E200`. Open UDP 49100 and 49200-49210
    on the host firewall and raise `net.core.rmem_max`.
11. **Record everything into SigMF from the first capture**
    ([ADR-0002](../docs/decisions/ADR-0002-sigmf-recordings.md)): personality and version,
    `mode` (1r1t / 2r2t), which physical port each channel is on (`SMA` or `IPEX`), sample
    rate, RF bandwidth, gain mode and gain per channel, reference source and DAC code,
    capture mode (continuous or snapshot) and duty cycle, and the wire format.

---

## 15. Numbers to measure on the real unit

Nothing below exists in any source found. Each is a first-run characterisation script. The
test parameters in the method column (buffer sizes, dwell times, frequency points) are
proposals for the measurement, not figures taken from a source; the "why" column names the
sourced claim each measurement settles.

| # | Measurement | Method | Why |
|---|---|---|---|
| 1 | Transceiver identity | read the U11 marking; compare with `iio_attr` on `ad9361-phy` | decides whether 5.8 GHz and >20 MHz bandwidth are in-datasheet (section 1.1) |
| 2 | Maximum sustained sc16 rate, stock IIO firmware, 1 channel | `iio_readdev -b 1048576` for 60 s at 5 / 7.68 / 10 / 12 / 15.36 / 20 MSPS, count overruns | vendor says 20 MSPS, community measurements say 11-13 (section 7) |
| 3 | Same, 2 channels | 2 x 5 / 2 x 7.68 / 2 x 10 MSPS | the per-channel halving is arithmetic, not measured |
| 4 | UHD `benchmark_rate` sweep | sc16 at 7.68 / 10 / 15.36 / 20 / 23.04 / 30.72 MSPS, sc8 at 30.72 / 40 / 56 MSPS, log `O` counts | sc8 and sc12 are implemented in driver and FPGA but unmeasured anywhere |
| 5 | Snapshot duty cycle | `rx_buffer_size` bursts at 30.72, 40, 56 and 61.44 MSPS; time capture versus transfer | sets the scheduler's coverage model (section 7) |
| 6 | RX1/RX2 phase offset, stability at a fixed state | splitter with matched cables into SMA and the U.FL pigtail; 100 buffers; circular mean and standard deviation | the baseline DF calibration; target under 1 degree standard deviation |
| 7 | RX1/RX2 phase jump per retune | 10 repeats of writing the same `rx_lo`, then 10 different LOs; log jumps, flag 180 degree flips | ADI says it changes, nobody has published how much for the E200 (section 11) |
| 8 | Same across sample-rate and gain changes | fs 2 / 5 / 10 MSPS, gain 0-60 dB in steps | gain dependence is first-principles only |
| 9 | Residual DC offset and LO leakage | terminated input, per-bin power at DC with the RF DC and BB DC tracking loops on and off, on the IIO firmware where the TX PA enable is tied high | not quantified in any source (sections 2 and 10) |
| 10 | Close-in phase noise | CW at 1 GHz and 5.8 GHz, spectrum against a known-good reference receiver | the RadioReference report is unresolved (section 1.2) |
| 11 | Free-running LO error and its drift | count a known reference, disciplined and undisciplined | 0.5 ppm nominal is about 2.9 kHz at 5.8 GHz |
| 12 | `ad5660mp` lock time and residual error | time to `in_voltage_dac_locked == 1`, then LO error; target under 0.1 ppm | the vendor claims 10 ppb with a GPSDO |
| 13 | Port map proof | inject on the SMA only, then on the pigtail only | confirms channel 0 (`voltage0`/`voltage1`) = SMA and channel 1 (`voltage2`/`voltage3`) = IPEX, and that the UHD antenna names do nothing |
| 14 | Front-end sensitivity and 1 dB compression per band | noise-floor and step-attenuator sweep at 433 / 868 / 915 / 2400 / 5800 MHz | sets the detector thresholds in [signal-reference.md](signal-reference.md) |
| 15 | Board temperature and thermal drift | `xadc` and the UHD `temp` sensor over a long capture | drift is a phase-calibration invalidation source |
| 16 | Second Cortex-A9 | `fw_setenv maxcpus 2`, reboot, `nproc` | inference only today; matters for [ADR-0005](../docs/decisions/ADR-0005-processing-location.md) |
| 17 | openwifi personality, if used | boot the image, `sdrctl dev sdr0 get reg rx 20`, time to the Viterbi halt; capture a known Remote ID beacon and read its radiotap data rate | confirms whether 1 Mbps DSSS beacons are invisible on this board |
| 18 | RX and TX gain ranges on the IIO personality | read `in_voltage0_hardwaregain_available` and `out_voltage0_hardwaregain_available` with `iio_attr`, then step through them | the 0 to 76 dB RX range and the 0.0 to 89.8 dB TX range are UHD-probe figures; the IIO-side ranges and the sign convention of `tx_hardwaregain_chanX` are unconfirmed (sections 2 and 9) |

---

## Gaps

What the evidence could not establish, drawn from the research lenses' open questions and
from the adversarial verdicts.

1. **Which transceiver is actually fitted.** The schematic says AD9363, the firmware says
   AD9364/AD9361, and Crowd Supply sells both variants. Performance above 3.8 GHz and
   above 20 MHz of bandwidth is outside the AD9363 datasheet and untested by the vendor
   documentation.
2. **Whether a U.FL-to-SMA pigtail ships.** Crowd Supply (snippet) says yes, MicroPhase's
   unboxing page lists none. Without one there is no second antenna.
3. **The magnitude of the RX1/RX2 phase jump per retune, per sample-rate change and per
   gain change on an E200.** ADI says it changes; nobody has published numbers, and the
   gain dependence is first-principles only (verified: `rf-ports`).
4. **Whether `calibscale` / `calibphase` exist on the E200's `cf-ad9361-lpc` core.** That
   depends on the `axi_ad9361` HDL build and was not verified.
5. **Real sustained throughput on this unit**, on either personality. Every IIO figure in
   section 7 comes from a Zynq-7000 board that the poster did not always identify as an
   E200, or from LibreSDR. Every UHD figure is a vendor table entry or a stress-test
   default, never a maximum.
6. **sc8 and sc12 throughput under UHD.** The packers exist in the driver and in the FPGA
   manifest, but no measurement of them exists in any source found.
7. **The 20 MSPS versus 15 MSPS PL-Ethernet figure.** openwifi's board README says
   "above 20MSPS ... 80MB/s"; the openwifi-hw copy of the same paragraph says 15 MSPS and
   60 MB/s. Unresolved.
8. **Three different default DAC codes for the reference loop**: 23000 in the documented
   manual procedure
   ([Antsdr-Clock-calibration.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration.md)),
   42580 as the `axi_vcxo_ctrl` HDL default
   ([HDL patch](https://github.com/MicroPhase/antsdr-fw-patch)), and `0xB7D0` as the
   `b205_ref_pll` DAC default in the UHD FPGA
   ([antsdr_e200.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/antsdr_e200.v)).
   Unresolved, and none is stated as the as-shipped value of a particular E200.
9. **Close-in phase noise.** One unresolved user report says it is visibly worse than a
   Pluto's; no measurement, and the domain is blocked in the research sandbox.
10. **Residual DC offset and LO leakage levels**, and how much the RF DC / BB DC tracking
    loops actually remove on this board. No source measures them.
11. **The E200 UHD probe's 50 MHz lower tuning edge** versus the 70 MHz datasheet figure.
    Unexplained.
12. **Whether `fw_setenv maxcpus 2` actually brings up the second Cortex-A9.** Inferred
    from the bootargs, not documented.
13. **Whether the E310's "RF switch fixed to the >3 GHz path" openwifi quirk affects the
    E200.** The E200 has no RF switching, so it should not, but this has not been tested.
14. **The E200 O4 DroneID firmware's channel list and clocking** (2434.5 / 5756.5 / 5776.5
    / 5816.5 MHz, 1R1T, 61.44 MSPS path clock, legacy FPGA correlator at
    `/dev/my-axi-droneid-filter0`) is **(unverified, round 1)**: it was scheduled for
    adversarial verification and the budget ran out.
15. **OcuSync PHY parameters** used elsewhere in this record (OcuSync 2 at 15 kHz
    subcarrier spacing with FFT 2048/1024 and CP 144/72 in roughly 1 ms frames; O3 and O4
    near 30 kHz spacing with about 9 MHz of 99 % bandwidth and 5 ms periodicity on the
    Mini 5 Pro; cyclic-prefix autocorrelation separating OcuSync from Wi-Fi's 312.5 kHz)
    are **(unverified, round 1)** for the same reason. They matter here only because they
    set the capture bandwidth the E200 must sustain; see
    [signal-reference.md](signal-reference.md).
16. **No E200-specific measurement of anything in section 15 exists in public.** That is
    the point of the list.
