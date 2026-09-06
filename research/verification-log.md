# Verification log

This is the audit trail of the research phase. Ten claims that would have driven a design
decision in the AERIX ANTSDR toolkit were pulled out of the first research round and sent
back for adversarial verification: an agent had to try to break each one against primary
sources (cloned code, vendor documentation, datasheets, issue trackers) rather than confirm
it. Eight completed. Two ran out of budget and are recorded here as unverified round-1
findings, because they are used elsewhere in the record and the reader has to know their
status.

Companion documents: [landscape.md](landscape.md) for what the signals are,
[hardware-e200.md](hardware-e200.md) for the platform, [signal-reference.md](signal-reference.md)
for waveform parameters, [datasets.md](datasets.md), [regulatory.md](regulatory.md),
[foreign-perspective.md](foreign-perspective.md) and [sources.md](sources.md) for the full
bibliography with per-source verified/snippet flags. The decisions that lean on these verdicts
are in [../docs/decisions/](../docs/decisions/), by topic:
[ADR-0004](../docs/decisions/ADR-0004-firmware-personality-and-capture-tiers.md) (verdicts 1, 2
and 6), [ADR-0005](../docs/decisions/ADR-0005-processing-location.md) (verdict 2),
[ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md) (verdicts 4 and 7),
[ADR-0007](../docs/decisions/ADR-0007-detection-pipeline-heuristics-before-ml.md) (verdict 8),
[ADR-0009](../docs/decisions/ADR-0009-localisation-deferred.md) (verdict 1) and
[ADR-0010](../docs/decisions/ADR-0010-band-coverage.md) (verdicts 3 and 5).

## How to read this log

* Verdict numbering is 1-based and matches the citation style used in the rest of the
  record: *(verified: verdict N, name)*, where N is the position in `verdicts.json`.
* Each verified subsection reproduces, from `verdicts.json`, the original round-1 claim,
  the verdict, the corrected claim, the evidence, a summary of the reasoning and the design
  consequence. The corrected claim is the version the other documents use. Where the
  original claim survives only in part, the surviving part is stated explicitly.
* Each verification agent had a hard budget of six web searches. All eight used all six.
  That budget, plus a sandbox that could not reach `ez.analog.com`, `wiki.analog.com`,
  `arxiv.org`, `fccid.io`, `crowdsupply.com`, CSDN, IEEE DataPort, Zenodo, Hugging Face or
  SciDB, is why several conclusions below stop at "snippet-level" or "not established".
* **verified** = an agent cloned the repository or fetched the page and read it.
  **snippet** = only a search-engine snippet was reachable. **inference** = arithmetic or
  first-principles reasoning on verified constants, labelled as such by the verifying agent.

The single most important result of the pass: **all eight verdicts came back `partly`.**
Not one round-1 claim was wholly right and not one was wholly wrong. Every one of them was
either over-generalised, mis-scoped to the wrong hardware generation, or resting on a number
that turned out to be a default rather than a limit. Treat any remaining unverified claim in
this record the same way.

| # | Key | Claim in one line | Verdict | Where used |
|---|---|---|---|---|
| 1 | `rf-ports` | E200 has 1 SMA RX + 1 IPEX RX, coherent, needs `2r2t` on Pluto firmware | partly | [hardware-e200.md](hardware-e200.md), DF planning |
| 2 | `host-streaming-tiers` | ~20 MSPS is the E200's host ceiling; RF-Vision's 40 MSPS contradicts it | partly | [hardware-e200.md](hardware-e200.md), all capture budgets |
| 3 | `elrs-decodability` | 2.4 GHz ELRS is detect-only, sub-GHz ELRS is decodable | partly | [landscape.md](landscape.md), [signal-reference.md](signal-reference.md) |
| 4 | `dji-generation-coverage` | Open DroneID decode covers O2/O3; O4 is encrypted; DroneID needs motors spinning | partly | [landscape.md](landscape.md), DJI tiering |
| 5 | `analog-fpv-bandwidth` | Analog FPV is ~5 MHz deviation, >99 % inside +/-4.5 MHz, 10 MSPS is enough | partly | [signal-reference.md](signal-reference.md), FPV capture defaults |
| 6 | `openwifi-personality` | openwifi supports the E200 and can be the Remote ID sniffer | partly | [regulatory.md](regulatory.md), RID receiver choice |
| 7 | `dji-eu-rid` | DJI standard RID is Wi-Fi Beacon only; DroneID continues alongside | partly | [regulatory.md](regulatory.md), [landscape.md](landscape.md) |
| 8 | `rf-ml-inputs-and-leakage` | Spectrograms beat raw IQ at low SNR; depth does not matter; benchmarks leak | partly | [datasets.md](datasets.md), ML protocol |
| 9 | `o4-firmware-channels` | E200 O4 firmware auto mode watches four channels, 1R1T, 61.44 MSPS | **not run** | [hardware-e200.md](hardware-e200.md), [landscape.md](landscape.md) |
| 10 | `ocusync-phy` | OcuSync 2 = 15 kHz/FFT 2048/CP 144; O3/O4 ~30 kHz; CP autocorrelation vs Wi-Fi | **not run** | [signal-reference.md](signal-reference.md), detector design |

---

## 1. `rf-ports` - RF ports, RX phase coherence and the 2r2t firmware mode

**Original claim.** The E200 has one RX/TX pair on SMA and the second RX/TX pair only on
internal IPEX (u.FL) connectors; both RX chains share the AD9361 RX LO and are
phase-coherent, but the RX1/RX2 phase offset is arbitrary after every LO retune, sample-rate
or gain change, so two-antenna direction finding needs re-calibration per tune. Also:
enabling the second channel on the Pluto-compatible firmware requires the `fw_setenv mode
2r2t` change.

**Verdict: partly.**

**Corrected claim.**

*Ports (verified).* MicroPhase's own selection table lists the E200 RF channels as
"SMA:1T1R IPEX:1T1R" while the E310/E316 are "2T2R MIMO"
([AntsdrE200_RF_parameters.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md),
[Chinese original](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters_cn.md)),
and the board photo shows exactly two SMA jacks, RX1 and TX1, on the RF edge
([e200.png](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/ANTSDR_E200_Reference_Manual.assets/e200.png)).
The second pair, RX2/TX2, is on u.FL/IPEX pads on the PCB. The pair is not unreachable: the
Crowd Supply campaign states the kit ships with a Hirose U.FL-to-SMA bulkhead pigtail of
less than 2 dB loss to 6 GHz
([crowdsupply.com](https://www.crowdsupply.com/microphase-technology/antsdr-e200), snippet
only), so RX2 can be brought out with a pigtail.

*No antenna switching (verified).* There is no TX/RX antenna switching on the E200 at all.
The UHD FPGA top drives only `tx_amp_en1`; the whole B200 front-end GPIO vector with its
SFDX/SRX switch lines is commented out
([antsdr_e200.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/antsdr_e200.v)
lines 505-508). The "TX/RX" and "RX2" antenna names that `uhd_usrp_probe` prints are B210
driver leftovers and are no-ops
([ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)).
RX1 is hard-wired to its SMA, TX1 to its SMA, and only TX1 has a PA-enable line.

*Coherence (verified/snippet).* The AD9361 has one RX RFPLL shared by both RX mixers, so
RX1 and RX2 are coherent and sampled on the same clock
([AD9361 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/AD9361.pdf)).

*Stability (snippet plus first principles).* ADI's own EngineerZone answer on the Pluto
rev C, which is the same single-chip 2RX topology, states that the RX1/RX2 relative phase
stays constant as long as the LO and sample rate are not touched, and that rewriting the LO
or the sample rate, even with the same value, can change it, because the driver re-runs the
init calibrations (RX QEC, RF DC, BBF tune)
([EZ thread 601154](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/f/q-a/601154/adalm-pluto-revc-phase-between-rx1-rx2-is-not-stable),
reachable only as a search snippet; the domain is egress-blocked). The magnitude of the
per-retune change is not established by any source that could be read. ADI's own FMComms5
phase-sync code rotates RX1 and RX2 of one chip together and measures only one channel per
chip
([ad9361_fmcomms5_phase_sync.c](https://github.com/analogdevicesinc/libad9361-iio/blob/main/ad9361_fmcomms5_phase_sync.c)),
which implies the intra-chip pair is treated as a fixed unit at a given tune - that is, the
intra-chip jump is not the 0-360 degree random LO-divider effect seen between chips or
between the TX and RX PLLs. Gain-induced phase change is not confirmed by any source; it is
expected from first principles, and per-channel AGC would make the two channels' gains
diverge, so run fixed, equal manual gains and treat any gain change as a recalibration event
until it is measured on the actual unit. Nobody has published measurements on the E200
specifically.

*Firmware (verified, current as of the August 2026 `antsdr-fw-patch` and `antsdr_uhd`
trees).* The stock Pluto-compatible firmware in QSPI declares the E200's chip as
`compatible = "adi,ad9364"` (1R1T, but the full 70 MHz-6 GHz / 56 MHz range), upstream Pluto
u-boot defaults to `mode=1r1t`, and u-boot strips `adi,2rx-2tx-mode-enable` from the device
tree when `mode=1r1t`
([linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch),
[u-boot patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-uboot.patch),
[zynq-common.h](https://raw.githubusercontent.com/analogdevicesinc/u-boot-xlnx/pluto/include/configs/zynq-common.h)).
So with Pluto/libiio firmware only RX1/TX1 exist until you run `fw_setenv attr_name
compatible; fw_setenv attr_val ad9361; fw_setenv compatible ad9361; fw_setenv mode 2r2t;
reboot` for QSPI boot, or edit `uEnv.txt` for SD boot
([antsdr-fw-patch README](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md)).
This env change is **not** needed for the UHD firmware - the E200 bitstream is built with
`TARGET_B210`, reports two radio chains and the driver allows up to 2 RX
([antsdr_e200.tcl](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/antsdr_e200.tcl),
[b200_core.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/b200_core.v)) -
nor for openwifi, whose E200 device tree already carries `adi,2rx-2tx-mode-enable`
([devicetree.dts](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/devicetree.dts)).
In two-channel mode the UHD driver halves the permissible master clock to 30.72 MHz
(`AD9361_MAX_CLOCK_RATE` 61.44e6 divided by the channel count, in
`enforce_tick_rate_limits` and `set_auto_tick_rate` -
[ant_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp)),
the Pluto scripts note the same 30.72 MHz cap with both channels enabled
([Pluto_MVDR_DOA.py](https://github.com/jonkraft/Pluto_Beamformer/blob/main/Pluto_MVDR_DOA.py)),
and MicroPhase rates the E200 host link at 20 MSPS total
([AntsdrE200_RF_parameters.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md)),
so realistic dual-channel DF is about 2 x 10 MSPS. UHD also inherits the B210 rule that 2RX+1TX is impossible, which is
irrelevant for passive use.

**Reasoning summary.** Ports confirmed but softened: the pigtail is supplied and there are
no RF switches to worry about. Coherence confirmed at chip level. "Arbitrary after every
retune or sample-rate change" is supported only at snippet level and with no magnitude. The
gain part is unverified and asserted from first principles. The `2r2t` requirement is
confirmed and scoped: it applies to the Pluto/libiio firmware only, and it also flips the
chip identity from `ad9364` to `ad9361`. A side observation that explains a persistent piece
of folklore: the E200 UHD documentation page shows an older single-frontend
`B205MINI(COMPATIBLE)` probe output, which is why some users believe the E200 is
single-channel under UHD; the current driver is B210-compatible with two chains
([AntsdrE200_UHD.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD.md)).
`ez.analog.com` was attempted once and returned EGRESS_BLOCKED.

**Design consequence.**

1. Document the E200 as "2RX coherent, 1 SMA + 1 u.FL". Hardware setup must include fitting
   the supplied U.FL-to-SMA bulkhead pigtail for RX2, define a fixed channel map RX1 = SMA
   jack / RX2 = pigtail, and ignore the UHD `antenna` parameter because it does nothing.
2. Provide a firmware-mode matrix with explicit commands: UHD image as the toolkit default
   (two RX chains natively, no env change); Pluto/libiio image (ships 1R1T as `adi,ad9364`,
   so the toolkit must run or verify the `fw_setenv` sequence and check that `iio_info` shows
   `voltage2`/`voltage3` before any DF code runs); openwifi image (already 2rx2tx).
3. Rate budget: in 2-channel mode plan for a master clock of at most 30.72 MHz and, given
   the 20 MSPS GbE ceiling, roughly 10 MSPS per channel. DF works on narrow band-slices, one
   10 MHz DroneID/OcuSync channel at a time, not the full 56 MHz.
4. DF calibration policy: treat every LO write, sample-rate write and gain write as a
   calibration-invalidating event; run with AGC off and identical manual gains; consider
   disabling RX quadrature tracking; design the tuning plan as a small set of fixed
   (LO, fs, gain) states with a cached calibration table per state. Because the toolkit is
   passive, calibration needs an external common reference (splitter-fed noise source, or an
   over-the-air beacon at a known bearing).
5. Add a first-run characterisation script that records RX1-RX2 phase over repeated retunes,
   rate changes and gain steps, and publish the numbers, since none exist for the E200.
6. Keep two-antenna DF out of the frozen AERIX observation contract until that
   characterisation exists.

---

## 2. `host-streaming-tiers` - what the 1 GbE link actually sustains

**Original claim.** The ANTSDR E200 can sustain only about 20 MSPS single-channel sc16 IQ
streaming to a host over its 1 GbE link (IIO/Pluto firmware ~11 MSPS with libiio 0.x,
~20 MSPS with libiio 1.0; UHD firmware vendor-tested at 7.68 MSPS per device), whereas the
RF-Vision-UAV-Tracker project claims 40 MSPS from a Zynq-7020 + AD9364 board via pyadi-iio.

**Verdict: partly.**

**Corrected claim.** The E200's host link is a single 1 GbE port with a standard 1500-byte
MTU, so continuous single-channel streaming is capped by arithmetic at about **29.6 MSPS in
sc16** (39 MSPS sc12, 59 MSPS sc8); 40 MSPS sc16 is 1.28 Gbit/s and is impossible on any
firmware. The computation is the ANT driver's own packet geometry: 1500-byte frames, a
16-byte CHDR header, a 1472-byte UDP payload, no jumbo frames, giving 81,274 packets/s x 364
sc16 samples
([ant_io_impl.cpp](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_io_impl.cpp)).
The realistic sustained rate then depends on the firmware personality.

*Tier 1, IIO/PlutoSDR-compatible firmware* (`antsdr-fw-patch` v0.39 = `plutosdr-fw` v0.39,
libiio v0.26 `iiod`, Linux 6.1 -
[plutosdr-fw v0.39](https://github.com/analogdevicesinc/plutosdr-fw/releases/tag/v0.39)):
the AD936x DMA path is fixed at 4 bytes per sample and all packets go through the Zynq PS
GEM (Cadence `macb`, whose `zynq_config` has no `MACB_CAPS_JUMBO` -
[macb_main.c](https://github.com/torvalds/linux/blob/master/drivers/net/ethernet/cadence/macb_main.c))
and `iiod` TCP on the ~700 MHz Cortex-A9. That is CPU-bound at roughly 47-52 MiB/s = 11-13
MSPS sc16 with stock firmware; about 20-22 MSPS (82-84 MiB/s) has been reached on the same
SoC class only with a speed-optimised kernel, larger IIO blocks and `iiod` pinned to core 1,
and 27.5 MSPS only with a 1100 MHz CPU / 750 MHz DDR overclock
([libiio discussion #875](https://github.com/analogdevicesinc/libiio/discussions/875),
[hz12opensource/libresdr](https://github.com/hz12opensource/libresdr)). MicroPhase's own
table rates the IIO-only E310 at 10 MSPS to host
([AntsdrE200_RF_parameters.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md)).

*Tier 2, UHD firmware*: the sample path uses a PL-side Ettus-derived 1 GbE MAC and
CHDR-over-UDP engine that bypasses the ARM entirely
([e200_eth_if_core.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/antsdr_e200/top/e200_eth_if_core.v),
[openwifi antsdr_e200 README](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md)).
MicroPhase rates the E200 and E316 at 20 MSPS "transmission bandwidth to host", and the
7.68 MSPS figure is merely the default of a two-device, four-hour concurrent stress test
producing about 492 Mbit/s aggregate - explicitly not a maximum
([antsdr_dual_e200_stress.sh](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/utils/antsdr_dual_e200_stress.sh),
[host README](https://github.com/MicroPhase/antsdr_uhd/blob/master/host/README.md)). The
driver and FPGA implement `otw_format` sc12 and sc8 (`SR_RX_FMT` plus
`chdr_16sc_to_xxxx_chain` in
[radio_legacy.v](https://github.com/MicroPhase/antsdr_uhd/blob/master/firmware/fpga/lib/radio_200/radio_legacy.v)),
which in principle allows 30-50 MSPS continuous single-channel, but no published measurement
exists. Two channels halve the per-channel rate (14.8 MSPS sc16 maximum).

*Tier 3, the RF-Vision contradiction dissolves.* RF-Vision-UAV-Tracker does not claim
continuous 40 MSPS. It programs the AD9364 to 40 MSPS and pulls 2,621,440-sample (65.5 ms)
snapshot buffers via `adi.Pluto` over the libiio network backend on a generic Zynq-7020 +
AD9364 board; each 10.5 MB snapshot takes 100-200 ms to transfer, giving at most a 25-40 %
duty cycle
([README_zh.md](https://github.com/ALPssdz/RF-Vision-UAV-Tracker/blob/main/README_zh.md),
[main_rf_pipeline.py](https://github.com/ALPssdz/RF-Vision-UAV-Tracker/blob/main/backend_rk3588/main_rf_pipeline.py)).
Snapshot capture at any AD9361 rate up to 61.44 MSPS is possible on both firmwares because
the DMA lands in DDR first; sustained streaming is not.

**Reasoning summary.** The headline (~20 MSPS sc16 sustained) is confirmed and sharpened.
The "libiio 1.0 gives ~20 MSPS" sub-claim is **refuted as stated**: there is no v1.x release
(newest tag v0.26, 25 Sep 2024 - [libiio tags](https://github.com/analogdevicesinc/libiio/tags))
and the 1.0-dev `iiod` alone moved the ANTSDR figure only from 48 to 52 MiB/s; the ~20 MSPS
gain came from kernel flags, block size and core pinning. The "UHD 7.68 MSPS" sub-claim is
true but was misread: it is a stress-test default. `antsdr-fw-patch`
[issue #29](https://github.com/MicroPhase/antsdr-fw-patch/issues/29) (Oct 2025, open, no
maintainer reply) asks MicroPhase for exactly the 1100/750 overclock, so the tuned-IIO path
is not something the vendor ships. Confidence: the vendor table, firmware architecture, RTL
and driver format support, the 1 GbE arithmetic, the libiio tag status and the tracker code
are verified; discussion #875 and the LibreSDR rates are verified quotes but on
ANTSDR-unspecified or LibreSDR hardware; the UHD sc8 practical rate and the stock-IIO
E200-specific rate are not directly measured.

**Design consequence.** Design the toolkit around three explicit capture tiers instead of one
"20 MSPS" number.

1. **IIO/Pluto, stock firmware**: budget at most 10 MSPS continuous sc16 (7.68-10 MSPS
   safe). The 15.36 MSPS DroneID rate and 20 MSPS OcuSync bandwidths are not reliable here;
   offer them only behind a documented "tuned IIO firmware" path and never depend on
   overclocking. No 8-bit option exists on this path and no jumbo frames.
2. **UHD**: the default for continuous host streaming. 20 MSPS sc16 is the vendor figure,
   29.6 MSPS is the hard 1500-MTU wire limit. Ship a `benchmark_rate` acceptance script that
   sweeps sc16 at 7.68/10/15.36/20/23.04/30.72 MSPS and sc8 at 30.72/40/56 MSPS and records
   overflow counts. Treat 2-channel use as halving per-channel rate (14.8 MSPS sc16).
3. **Snapshot/dwell mode**: for 40 MHz OcuSync video, wideband classifiers and DF
   experiments, use `rx_buffer_size` bursts at up to 56-61.44 MSPS with a scheduler that
   accepts a 25-40 % duty cycle - the RF-Vision pattern - not a continuous 40 MSPS pipeline.

Consequently DroneID/OcuSync decoding at 15.36 MSPS should run either via UHD sc16 on the
host or on the E200 itself emitting decoded JSON, the latter being the natural fit for the
AERIX `future_sdr` receiver class. Anything above 30 MSPS continuous requires custom PL
firmware and must be labelled experimental. The observation contract should carry effective
sample rate, wire format and capture mode (continuous vs snapshot, with duty cycle) as
metadata. Finally, retire the "libiio 1.0 gives ~20 MSPS" statement from the toolkit docs.

---

## 3. `elrs-decodability` - ExpressLRS 2.4 GHz versus sub-GHz

**Original claim.** ExpressLRS 2.4 GHz LoRa modes use 812.5 kHz bandwidth with SF5-SF8 and
the SX1280 long-interleaver coding, which no open SDR LoRa decoder (gr-lora_sdr, gr-lora,
SDRangel) implements, so 2.4 GHz ELRS is detect/classify-only; whereas 868/915 MHz ELRS uses
SX127x-format LoRa (500 kHz, SF6-9) that gr-lora_sdr can demodulate, making sub-GHz ELRS
decodable given the CRC/UID handling.

**Verdict: partly.**

**Corrected claim.** The 2.4 GHz LoRa rates (500 / 333Full / 250 / 150 / 100Full / 50 Hz)
all use SX1280 bandwidth code `0x18` - nominal 812.5 kHz, called "800" in ELRS - with SF5 to
SF8, long-interleaver coding rates LI 4/6 (500 Hz) or LI 4/8 (all others), implicit header,
hardware CRC off, and IQ inverted whenever `UID[5]` is odd
([common.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/src/common.cpp),
[SX1280_Regs.h](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/SX1280Driver/SX1280_Regs.h),
[SX1280.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/SX1280Driver/SX1280.cpp),
[rx_main.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/src/rx_main.cpp)).
No public SDR decoder implements the SX1280 PHY, let alone the undocumented long
interleaver: gr-lora_sdr is documented and tested for RFM95/SX1276/SX1262 only and its
deinterleaver implements only the classic diagonal interleaver
([gr-lora_sdr](https://github.com/tapparelj/gr-lora_sdr),
[deinterleaver_impl.cc](https://github.com/tapparelj/gr-lora_sdr/blob/master/lib/deinterleaver_impl.cc)),
[issue #143](https://github.com/tapparelj/gr-lora_sdr/issues/143) (open since 2025-07-04)
shows that even plain-CR SX1280 frames fail; rpp0/gr-lora rejects SF < 6
([decoder_impl.cc](https://github.com/rpp0/gr-lora/blob/master/lib/decoder_impl.cc)) and
SDRangel ChirpChat tops out at 500 kHz
([readme](https://github.com/f4exb/sdrangel/blob/master/plugins/channelrx/demodchirpchat/readme.md)).
The claim also misses that the SX1280 FLRC rates (F500/F1000, D250/D500) and the LR1121
GFSK-2G4 rates (300 kbps, BW 467 kHz, fdev 100 kHz) are not LoRa at all. So every 2.4 GHz
ELRS mode is detect/classify-only today, and because the 2.4 GHz FHSS table spans
2400.4-2479.4 MHz in 80 channels - 79 MHz
([FHSS.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/FHSS/FHSS.cpp)) -
it also exceeds the E200's 56 MHz instantaneous bandwidth.

Sub-GHz ELRS on SX127x hardware is 500 kHz, SF6-SF9, CR 4/7-4/8, implicit header, hardware
CRC off, LoRa sync word `0x12`, IQ possibly inverted per `UID[5]`
([SX127x.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/SX127xDriver/SX127x.cpp),
[SX127xRegs.h](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/SX127xDriver/SX127xRegs.h)) -
parameters gr-lora_sdr supports, so demodulation is plausible but **has not been demonstrated
end-to-end by any public project**. The only GNU Radio ELRS work re-implements the OTA/FHSS/CRC
layer SDR-to-SDR with non-ELRS LoRa parameters (SF7, BW 125 kHz) and validates only packet
counts between two SDRs
([Diamond-D0gs/GNU_Radio_ExpressLRS](https://github.com/Diamond-D0gs/GNU_Radio_ExpressLRS)).
Two caveats narrow "sub-GHz decodable" further: current LR1121/LR2021 hardware adds sub-GHz
rates outside gr-lora_sdr's tested space - SF5 in the SX126x style, which gr-lora_sdr's own
README says is incompatible, a 300 kbps GFSK 1000 Hz mode, and dual-band modes - while
LR1121 SF6 is forced into SX127x-compatible mode via an undocumented register supplied by
Semtech in an email
([LR1121.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/LR1121Driver/LR1121.cpp)).
SF6, the most-used sub-GHz rate, therefore needs measurement against real hardware.

The "CRC/UID handling" is easier than the original claim implied: every SYNC packet carries
`UID4` and `UID5` in the clear (with `UID5`'s low 6 bits XORed with `~modelId` when
ModelMatch is on), which is exactly the CRC initialiser - CRC14 poly `0x2E57` on the 8-byte
OTA4 frame, CRC16 poly `0x3D65` on the 13-byte OTA8 frame
([OTA.h](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/OTA/OTA.h),
[OTA.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/OTA/OTA.cpp),
[tx_main.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/src/tx_main.cpp)).
Since ELRS V4.0 ([PR #3294](https://github.com/ExpressLRS/ExpressLRS/pull/3294), merged
2025-10-08) non-sync packets XOR the per-packet nonce into the initialiser, so a sniffer must
track the nonce from sync packets. There is no encryption anywhere in the OTA layer.
Capturing the whole sub-GHz hop band removes any need to know the FHSS seed: EU868 is 13
channels over 6.3 MHz, AU915 20 channels over 11.4 MHz, FCC915 40 channels over 23.4 MHz
([FHSS.cpp](https://github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/FHSS/FHSS.cpp)).

**Reasoning summary.** Both headline statements are true, but the claim is outdated on
hardware generation (LR1121/LR2021), silent on UID-driven IQ inversion and on the non-LoRa
2.4 GHz modes, overstates "decodable" into plausible-but-undemonstrated, and understates how
little UID knowledge is actually needed. An NCC Group advisory confirms that sync packets
leak most of the FHSS seed
([NCC Group, 2022](https://research.nccgroup.com/2022/06/30/technical-advisory-expresslrs-vulnerabilities-allow-for-hijack-of-control-link/)).

**Design consequence.**

1. Treat ELRS 2.4 GHz (LoRa LI, FLRC, LR1121 GFSK) as detect/classify-only. Because the hop
   set spans 79 MHz, implement 2.4 GHz detection as a swept or windowed energy/chirp-signature
   detector (812.5 kHz LoRa chirps, 0.6 MHz FLRC bursts, 2-20 ms packet intervals) and label
   it "ELRS-2G4 (LoRa/FLRC)" without attempting payload decode.
2. Build the sub-GHz decoder as: whole-band capture of the local regulatory domain (EU868
   needs about 7-8 MSPS; FCC915 needs about 25 MSPS or on-Zynq channelisation), a polyphase
   channeliser to the 13/20/40 ELRS channels at 1 MSPS each, and per-channel gr-lora_sdr
   chains (BW 500 kHz, implicit header, CRC off, sync word `0x12`, preamble 8-10) for SF6-SF9
   with CR 4/7 and 4/8, run on both IQ polarities.
3. Implement the OTA layer from the ExpressLRS source: parse SYNC for `UID4`/`UID5` (plus up
   to 64 ModelMatch XOR candidates), nonce, rate index, telemetry ratio and `otaProtocol`;
   validate CRC14/CRC16 with the nonce term for V4.0+ and without it for earlier; decode RC
   channels, link stats and CRSF telemetry, which can carry aircraft GPS. No binding phrase is
   needed and no encryption exists.
4. Mark the LR1121/LR2021 SF5 rates and the GFSK 1000 Hz rate as "needs new demod", and flag
   SF6 as "verify against real SX127x and LR1121 hardware".
5. Because no public project has shown end-to-end decode of real ELRS radios, plan a
   validation step with an owned ELRS TX/RX pair and a known binding phrase before the
   `future_sdr` receiver class advertises ELRS decoding. Until then: sub-GHz is a
   "decodable-candidate", 2.4 GHz is "detect-only".

---

## 4. `dji-generation-coverage` - what open DroneID tooling really decodes

**Original claim.** DJI DroneID is decodable with open-source tools only for OcuSync 2 and
standard OcuSync 3 drones; O3 Pro / O4 / O4+ drones (Air 3, Mini 4 Pro, Avata 2, Neo, Mini 5)
transmit encrypted DroneID payloads so only a per-session hash, frequency and RSSI can be
obtained; and DJI drones transmit DroneID only while the motors are spinning.

**Verdict: partly.**

**Corrected claim.**

*(1) Open-source coverage is narrower than "O2 plus standard O3".* The open decoders
([proto17/dji_droneid](https://github.com/proto17/dji_droneid/blob/main/Test.md),
[RUB-SysSec/DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity/blob/public_squash/README.md),
[anarkiwi/samples2djidroneid](https://github.com/anarkiwi/samples2djidroneid/blob/main/README.md))
are verified only on DJI Mini 2 and Mavic Air 2. They do not decode the OcuSync-2.0 Mavic 2
Pro - "existing decoders don't support Mavic 2 parameters"
([DroneSecurity #49](https://github.com/RUB-SysSec/DroneSecurity/issues/49), Jun 2026) - and
O3-generation decoding (Air 2S, Mini 3/3 Pro, the Mavic 3 family) is unfinished in public
code: proto17's Mavic 3 analysis stopped at Zadoff-Chu identification (roots 600 and 385,
each twice, six data symbols in a 10-symbol/4-ZC burst -
[wiki](https://github.com/proto17/dji_droneid/wiki/DJI-Mavic-3-DroneID-Analysis)) and every
O3 decode issue is open or unresolved
([#43](https://github.com/proto17/dji_droneid/issues/43),
[#51](https://github.com/proto17/dji_droneid/issues/51),
[#58](https://github.com/proto17/dji_droneid/issues/58),
[DroneSecurity #46](https://github.com/RUB-SysSec/DroneSecurity/issues/46)). O3 payloads are
**not** encrypted, and full offline O2+O3 decode - serial, model, drone/pilot/home GPS,
altitude, speed, RSSI - exists, but only in MicroPhase's closed-source E200 firmware binaries
(`done_dji_release`, files dated 2024-03-06, and `drone_dji_rid_decode`, build 2026-01-14)
redistributed in
[alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/README.md).
The claim's "O3 Pro" grouping is a generation mix-up: O3+/O3 Pro (Mavic 3 series, Inspire 3)
sit on the unencrypted O3 side. The encryption boundary is the **O4** generation, from the
Air 3 (Aug 2023) onward.

*(2) O4/O4+ payloads are encrypted but not un-recoverable.* The burst is still demodulable -
a clean QPSK constellation was obtained in
[proto17 #50](https://github.com/proto17/dji_droneid/issues/50) (May 2024), a ~500 us burst
with four ZC sequences on the Air 3S in
[DroneSecurity #50](https://github.com/RUB-SysSec/DroneSecurity/issues/50), and O4+ ZC root
indices that change from frame to frame in
[proto17 #65](https://github.com/proto17/dji_droneid/issues/65) - but the payload is
encrypted. With the public E200 O4 firmware you get `dji(<hash>)`, described as a per-session
hash, plus detection frequency and RSSI
([dji_receiver.py](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/dji_receiver.py)).
The firmware binary contains an online decrypt call
`/api/o4online/decrypt?hex=...` with `Authorization`, `auth_secret` and `token_secret`, and
the WarDragon DragonScope proxy forwards the encrypted hex to a licensed remote endpoint that
returns serial, latitude and longitude
([dragonscope.py](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/dragonscope.py)).
O4 decryption is therefore a paid cloud service held by vendors with keys, not an open-source
capability; [proto17 #63](https://github.com/proto17/dji_droneid/issues/63) ("does anyone have
the O4 decryption key... looking to purchase it") is unanswered. A Chinese researcher reports
O1/O2/O3 unencrypted versus O4 encrypted and four DroneID packet types - full, serial-only,
fully encrypted and key packets
([CSDN leegang12](https://blog.csdn.net/leegang12/article/details/149397403)) - unverified
detail, snippet only.

*(3) "Only while motors are spinning" is contested.* The sole source is alphafox02's 2026
README, in its O4 section
([README](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/README.md)). For O2-era
drones it is contradicted by proto17's own recording instructions, "Power on the drone
(shouldn't need the controller to be on)"
([wiki](https://github.com/proto17/dji_droneid/wiki/Using-the-MATLAB-Code)) - a Mini 2 cannot
arm its motors without a controller - by DroneSecurity's `mini2_sm` capture taken before GPS
lock with only the phone position present, and by the protocol itself carrying separate
`motor_on` and `in_air` flags
([droneid_packet.py](https://github.com/RUB-SysSec/DroneSecurity/blob/public_squash/src/droneid_packet.py),
[Kismet's DJI IE parser](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h)).
Treat the DroneID start condition as unknown per model and verify empirically.

*(4) Caveats the claim omitted.* LightBridge/OcuSync-1 drones such as the Phantom 4 Pro V2
have no such burst, or a different 14-symbol signal that only the E200 firmware handles
([DroneSecurity #43](https://github.com/RUB-SysSec/DroneSecurity/issues/43)). Wi-Fi-link DJI
drones send DroneID as an 802.11 vendor IE with OUI `26:37:12`, decoded by Kismet and not by
SDR OFDM decoders. DroneID is unauthenticated, and modified DJI firmware documented in
Russian/Ukrainian re-flash guides can switch it off (`aeroscope_off`) or broadcast
pseudo-random or fake positions (`aeroscope_random`, `aeroscope_z`, `aeroscope_heart`) and
also disable OpenDroneID
([techuav firmware registry](https://github.com/techuav/techuav.github.io/blob/main/docs/ПЛАТФОРМА_FPV/Прошивка/РЕЕСТР_ПРОШИВОК_ДЛЯ_КВАДРОКОПТЕРОВ_DJI.html)).
And DJI drones sold since roughly 2022-23 in the EU and US, including all O4 models,
additionally broadcast standard ASTM F3411 / EN 4709 Remote ID over Wi-Fi/BT, which is
open-source decodable
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c/blob/master/README.md))
and is the practical way to obtain O4 identity and position.

**Reasoning summary.** Verified from cloned code, extracted firmware strings and issue
trackers. The strings in `build_sdimg_drone_o4.zip` include the CSV formats `dji_O,2/3,...`
and `dji_O,4,...hash`, `O4 packet`, `Enable o4`/`Disable o4`, `/api/o4online/decrypt?hex=`,
and a model table running up to Mavic 4 Pro, Neo, Air 3S, Flip, Mini 4 Pro, Avata 2 and
Matrice 4E/4T, with the Mini 5 Pro absent; the 2024-03 net firmware has no `o4online`
strings. First-principles check: the DroneID burst is about 10 MHz wide (FFT 1024 at 15.36
MSPS), so the E200's ~20 MSPS Ethernet budget suffices for host decoding, and the MicroPhase
firmware decodes on the Zynq itself. The 640 ms cadence and fixed ZC roots hold for O2
(600/147) and O3 (600/385) but not for O4+, so ZC-template detection must be generalised.
Vendor READMEs that say "detect O4 drones" mean airlink presence plus a hash, not identity.

**Design consequence.** Design the DJI branch as three tiers with different observation
semantics rather than one "DroneID decoder".

* **Tier A - identity plus position, offline**: OcuSync 2/3 drones. Run MicroPhase's E200
  DroneID firmware on the Zynq (CSV over TCP 52002/41030, then `dji_receiver.py`, then ZMQ
  4221 into AERIX), because it is the only thing that decodes O3 today. Keep
  proto17/DroneSecurity as the inspectable open fallback and regression bench, but do not
  promise O3 or Mavic 2 decoding from them.
* **Tier B - presence only**: O4/O4+. Emit a "DJI OcuSync-4 airlink detected" observation
  carrying hash, frequency, RSSI and time, never a serial or position. The per-session hash
  must be modelled as a transient track key, not a stable aircraft ID. Put licensed decrypt
  services behind an optional, clearly labelled provenance flag; the contract must record that
  a position came from a third-party decrypt API and requires internet.
* **Tier C - identity and position for O4 and everything else**: standard Wi-Fi/BT Remote ID,
  which AERIX already ingests. The toolkit's value for O4 drones is correlating an RID track
  with a Tier-B RF detection, so the `future_sdr` class needs fields for airlink generation
  (O2/O3/O4), a detection-only flag, hash, frequency plan and RSSI, plus a correlation hint to
  an RID track.

Do not encode "no DroneID until motors spin" as an assumption: log the `motor_on`, `in_air`
and `gps_valid` state bits and measure per model. Treat all DroneID and RID content as
unauthenticated, and keep the physical-layer detector (ZC correlation on 600/147 and 600/385,
plus a root-agnostic ZC or periodicity detector for O4+) as an independent evidence channel.
Note the coverage holes explicitly: LightBridge/OcuSync-1 and Wi-Fi-link DJI drones need
Kismet's 802.11 parser or the closed firmware.

---

## 5. `analog-fpv-bandwidth` - what 5.8 GHz analog FPV actually occupies

**Original claim.** Analog 5.8 GHz FPV video is FM with about 5 MHz peak deviation and keeps
more than 99 % of its energy within +/-4.5 MHz, so a 10 MSPS capture decodes it fully and the
commonly quoted "20-27 MHz" figure describes channel spacing or a 6 MHz-deviation worst case
rather than the occupied bandwidth.

**Verdict: partly.**

**Corrected claim.** Analog 5.8 GHz FPV is wideband FM of a 1 Vpp composite video signal
(NTSC 4.2 MHz, PAL about 5-5.5 MHz including chroma) plus, on RTC6705-class VTX - the dominant
chipset - two FM audio subcarriers at 6.0 and 6.5 MHz sitting 25-30 dB below the video
carrier. The RTC6705 datasheet specifies **no** main-carrier video deviation: it gives the
video input as 1 Vpp / 75 ohm, the video-to-audio carrier ratio as -30/-25 dBc, an audio
subcarrier deviation of +/-25 kHz and 12 kHz pre-emphasis, and registers `0x00`-`0x07` that
contain synthesiser, VCO, audio and PA control and nothing for video deviation
([RTC6705 datasheet, RichWave, Sep 2007 V0.2](https://github.com/OpenVTx/OpenVTx/blob/master/docs/RTC6705-RichWave.pdf)).
So "5 MHz peak deviation" is a decoder scale constant - the `fpvdec --dev` default - that
varies per VTX and video gain, not a specification
([config.hpp](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder/blob/main/src/config.hpp)).

Because the luma-driven instantaneous frequency carries nearly all the power, a 10 MSPS
capture (+/-4.9 MHz) yields a usable NTSC colour picture. That was demonstrated on one 25 mW
whoop VTX with a HackRF, where the author measured less than 0.3 % of energy outside
+/-4.5 MHz
([config.hpp](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder/blob/main/src/config.hpp)).
It does **not** decode the signal "fully": the 6.0/6.5 MHz audio subcarriers are beyond
Nyquist, PAL chroma up to about 5.5 MHz is beyond Nyquist, sync tip and peak white sit right
at the filter edge - `fpvdec` has to open the HackRF analog filter to 0.9x the rate "or color
washes out"
([hackrf_source.cpp](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder/blob/main/src/source/hackrf_source.cpp)) -
and 1-3 MHz VTX drift eats the margin without AFC
([README](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder/blob/main/README.md)). The
E200-native scanner defaults ANTSDR/USRP to 20 MSPS for viewing and 40 MSPS for detection,
with HackRF 12, bladeRF 18, Pluto 8 and CaribouLite 4 MSPS, and treats 10 MSPS as the "PC
can't keep up" fallback and 16 MSPS as "more detail"
([fpv-sdr README](https://github.com/lukeswitz/fpv-sdr/blob/main/README.md),
[fpv_sdr.py](https://github.com/lukeswitz/fpv-sdr/blob/main/fpv_sdr.py)).

Note the internal inconsistency in the original claim: a true +/-5 MHz swing would park about
7 % of line time (the sync tips) outside +/-4.5 MHz, so the >99 % figure implies the tested
VTX swung less than the assumed 5 MHz. The two numbers cannot both be exact.

The "20-27 MHz" community figure is neither pure channel spacing nor a 6 MHz-deviation case.
19-20 MHz is the A/B/E/F channel spacing while Raceband is 37 MHz (channel tables verified in
both decoders, [fpv_scanner.sh](https://github.com/lukeswitz/fpv-sdr/blob/main/fpv_scanner.sh)),
and 23-27 MHz is a Carson-rule occupied-bandwidth estimate 2 x (deviation + f_max) with the
6.5 MHz audio subcarrier or an 8 MHz "video bandwidth" as f_max
([TS5828-class VTX spec sheet](https://www.foxtechfpv.com/58g-600mw-48channel-vtx.html),
snippet; [Oscar Liang](https://oscarliang.com/fpv-channels/), snippet). 27 MHz also happens
to be HDZero's digital channel width. Carson's 98 % bound is conservative here because the
high-frequency modulating components are 25-30 dB weak, so the real 99 % bandwidth lies
between about 9 MHz (video-only, low index) and about 20 MHz (Carson, video-only), with faint
subcarrier lines out to +/-11.5 MHz.

**Reasoning summary.** The decoder facts are verified from cloned code. The GNU Radio
lineage's "10 MSPS" traces back to a student flowgraph whose variables are `bandwidth = 5e6`
and `samp_rate = 2*bandwidth`
([gr-ntsc-rc](https://github.com/lscardoso/gr-ntsc-rc/blob/master/examples/NTSC_Video_5GHz_RX.grc)),
not a measurement. `fpvdec`'s own `--spectrum` help expects energy "spread over
+/-(dev+4.2) MHz" = +/-9.2 MHz, the author's own Carson estimate for video only
([main.cpp](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder/blob/main/src/main.cpp)).
The deviation and energy-fraction numbers rest on a single unreproduced hobbyist measurement
taken with an 8-bit HackRF at presumably 20 MSPS, so energy beyond +/-10 MHz was invisible and
audio-equipped or high-power VTX were not tested. The "6 MHz deviation worst case" part of the
original claim has no source in any repo or datasheet found.

**Design consequence.**

1. Make 20 MSPS (RF bandwidth about 20 MHz) the E200 default for analog FPV viewing and
   recording - `fpv-sdr`'s own E200 default and within the ~20 MSPS 1 GbE budget - and treat
   10-12 MSPS as a throughput fallback (10 MSPS gives NTSC colour, 12 MSPS or more is needed
   for PAL chroma, 6-8 MSPS is grayscale only). Always run an AFC and set the AD9361 analog
   filter to at least 0.9x the rate at low rates.
2. Model analog FPV for detection as a noise-like FM hump about 9-10 MHz wide with no discrete
   carrier, with optional weak lines at +/-6.0 and +/-6.5 MHz that fingerprint RTC6705-class
   audio-equipped VTX. Integrate channel power over +/-5 MHz with a +/-9 MHz shoulder
   ([fpv_detect.py](https://github.com/lukeswitz/fpv-sdr/blob/main/fpv_detect.py) uses an
   in-band 10 MHz and an 18 MHz shoulder ring), expect adjacent-channel overlap on the
   19-20 MHz-spaced bands, and identify channels by spectral centroid plus AFC rather than by
   nearest-table lookup.
3. Port `fpvdec`'s DSP (NTSC colour, currently HackRF-only input) to a UHD/IIO source, and note
   that `fpv-sdr`'s 2 MHz post-demod low-pass makes it luma-only. Flag PAL colour, common in EU
   cameras, as an unsupported gap in all open decoders and record 20 MSPS IQ for offline work.
4. Do not quote "27 MHz" as analog occupied bandwidth without qualification. State channel
   spacing (20/19/37 MHz), the Carson estimate (18-27 MHz depending on whether the audio
   subcarriers count) and the 9-10 MHz 99 %-power core separately, and do not present "5 MHz
   deviation" as a chipset specification.

---

## 6. `openwifi-personality` - openwifi on the E200 as a Remote ID sniffer

**Original claim.** openwifi officially supports the ANTSDR E200 (monitor mode, packet
injection, CSI, IQ capture) as a separate SD-card image that cannot run concurrently with the
IIO or UHD streaming personalities, so the E200 can serve as an 802.11 Remote ID (Wi-Fi
Beacon / NAN) sniffer in that mode.

**Verdict: partly.**

**Corrected claim.** openwifi does officially list the E200 as board `antsdr_e200`: it appears
in the README board table, in `kernel_boot/boards/antsdr_e200` with device tree and u-boot, in
`openwifi-hw/boards/antsdr_e200` as an FPGA design, in `openwifi-hw-img` as a prebuilt
bitstream, and since Aug 2026 as a compact Buildroot SD image stated to have been booted with
AP/client operation and iperf3 on real E200 hardware
([openwifi README](https://github.com/open-sdr/openwifi/blob/master/README.md),
[board README](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md),
[buildroot README](https://github.com/open-sdr/openwifi/blob/master/doc/img_build_instruction/buildroot/README.md)).
MicroPhase's E200 openwifi page just defers to the E310 procedure with E200-specific boot files
([AntsdrE200_openwifi.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_openwifi.md)).

It boots only from SD. The E200's DIP switch selects BOOT/QSPI/SD, the stock Pluto/IIO
firmware lives in QSPI and the UHD firmware is SD-only
([unpacking page](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination.md),
[set_the_iio_firmware_ip.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/set_the_iio_firmware_ip.md)),
so openwifi is mutually exclusive at boot time with both streaming personalities - the claim's
exclusivity statement is confirmed. Inside the openwifi image the AD9361 IIO control driver
exists but the `cf-ad9361` IQ DMA nodes have their `dmas` lines commented out, so there is no
wideband IQ stream
([devicetree.dts](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/devicetree.dts)).
Monitor mode delivers all frames including bad-CRC ones to mac80211 with radiotap dBm signal
and FCS, and packet injection, CSI and IQ capture (with `iq_len` under 4096 on the Z7020) are
available
([doc/README.md](https://github.com/open-sdr/openwifi/blob/master/doc/README.md),
[sdr.c](https://github.com/open-sdr/openwifi/blob/master/driver/sdr.c),
[iq.md](https://github.com/open-sdr/openwifi/blob/master/doc/app_notes/iq.md)).

**However** - and this is what breaks the Remote ID use case - openwifi is OFDM-only
(802.11a/g/n) and cannot demodulate 802.11b DSSS/CCK at 1/2/5.5/11 Mbps. Its own README says
this incompatibility "is usually the case during beacon transmission", and its bundled hostapd
configuration has to force OFDM basic rates to work
([README](https://github.com/open-sdr/openwifi/blob/master/README.md),
[hostapd-openwifi.conf](https://github.com/open-sdr/openwifi/blob/master/user_space/hostapd-openwifi.conf),
[issue #454](https://github.com/open-sdr/openwifi/issues/454), Apr 2025, no fix). Reference
Remote ID Wi-Fi Beacon transmitters send 2.4 GHz beacons at the 802.11b lowest basic rate:
opendroneid's `transmitter-linux` uses `hw_mode=g`, channel 6 and no `basic_rates` override
([beacon.conf](https://github.com/opendroneid/transmitter-linux/blob/master/beacon.conf)), and
ESP32-based modules never call `esp_wifi_set_protocol` or `esp_wifi_config_80211_tx_rate`, so
the ESP-IDF default 11B|11G|11N protocol applies and beacons go out at 1 Mbps DSSS
([ArduRemoteID WiFi_TX.cpp](https://github.com/ArduPilot/ArduRemoteID/blob/master/RemoteIDModule/WiFi_TX.cpp),
[esp_wifi.h](https://github.com/espressif/esp-idf/blob/master/components/esp_wifi/include/esp_wifi.h),
[esp32-crid](https://github.com/luolitao/esp32-crid)) - **inferred from defaults, not
measured**. An openwifi-mode E200 will therefore most likely miss the common 2.4 GHz Wi-Fi
Beacon Remote ID broadcasts. It can in principle capture 5 GHz Beacon RID on channel 149 at
OFDM rates of 6 Mbps or more, and NAN frames if they are sent at OFDM rates (the NAN PHY rate
is not verified), and it can never receive Bluetooth 4/5 Remote ID.

Further sniffer caveats: the free FPGA image's Xilinx Viterbi decoder runs under an evaluation
licence and halts after about two hours, needing an FPGA reload or power cycle, detectable via
`sdrctl dev sdr0 get reg rx 20`
([README](https://github.com/open-sdr/openwifi/blob/master/README.md)); only one 20 MHz channel
can be watched at a time, so channel 6 and channel 149 cannot be covered simultaneously; the
classic image is a multi-gigabyte Kuiper SD image needing a 16 GB card on a 512 MB-RAM board;
and the Aug-2026 Buildroot path carries an E200 SPL/MMC diagnostics patch written because "the
ANTSDR E200 currently resets while entering the SPL MMC loader"
([patch](https://github.com/open-sdr/openwifi/blob/master/buildroot-external/patches/uboot/antsdr_e200/0002-antsdr-e200-spl-mmc-diagnostics.patch),
11 Aug 2026). The PHY rate of commercial drones' Wi-Fi Beacon RID frames is unverified.

**Reasoning summary.** Confirmed from the cloned upstream tree at commit `bf8790e` (25 Aug
2026) and MicroPhase's docs at `ea2cd8d`. The E310's "RF switch fixed to the >3 GHz path"
openwifi quirk does not appear for the E200 and the E200 IIO device tree has no `adi,band-ctl`
GPIO nodes, so nothing blocks 2.4 GHz on the E200
([E310 notes.md](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr/notes.md)).
`opendroneid-core-c`'s `wifi.c` writes a supported-rates IE of `0x8C` (6 Mbps) into the beacon
body, but that is IE content, not the PHY rate
([wifi.c](https://github.com/opendroneid/opendroneid-core-c/blob/master/libopendroneid/wifi.c)).
All six web searches were used and returned nothing authoritative on NAN or DJI beacon PHY
rates.

**Design consequence.** Do not make openwifi-on-E200 the toolkit's Remote ID path. Keep the
E200 in its IIO (QSPI) or UHD (SD) personality for what only a wideband SDR can do - DJI
DroneID/OcuSync, RC and video-link detection, RF-ML classification, later DF - and cover ASTM
F3411 / EN 4709 Remote ID with a dedicated cheap receiver that handles all mandatory
transports: a Linux mac80211 adapter in monitor mode with 802.11b/g/n/a support (1 Mbps DSSS
beacons on channel 6, OFDM beacons on channel 149, NAN action frames) plus a BLE 4/5 Coded PHY
radio, or an ESP32-S3-class RID receiver. If openwifi mode is offered at all, document it as an
optional research personality (CSI, IQ trigger capture, 5 GHz OFDM beacon/NAN sniffing) with a
boot-switch/SD-swap procedure, a watchdog that polls `sdrctl dev sdr0 get reg rx 20` and
reloads the FPGA when the two-hour Viterbi halt hits, channel hopping between 6 and 149, and an
explicit validation step: capture the target drones' RID beacons with a COTS card and read the
radiotap data-rate field to confirm whether they are 1 Mbps DSSS (openwifi blind) or OFDM.
Record that Bluetooth RID is out of reach for openwifi entirely.

---

## 7. `dji-eu-rid` - DJI standard Remote ID in the EU

**Original claim.** In the EU, DJI drones that broadcast standard Remote ID (ASD-STAN
EN 4709-002) do so over Wi-Fi Beacon only (not BLE, not NAN), availability depends on model,
class mark and firmware, and DJI DroneID over OcuSync continues to be transmitted alongside it.

**Verdict: partly.**

**Corrected claim.** DJI's standard Remote ID is an 802.11 Beacon-only implementation, using
the ASD-STAN/ASTM vendor IE with OUI `FA:0B:BC` and type `0x0D`, and an SSID typically of the
form `RID-<id>`
([wifi.c](https://github.com/opendroneid/opendroneid-core-c/blob/master/libopendroneid/wifi.c)).
No DJI model is documented as using Bluetooth 4/5 or Wi-Fi NAN. This is verified for the Mavic
3 and Mini 3 Pro
([transmitter-devices.md](https://github.com/opendroneid/receiver-android/blob/master/transmitter-devices.md)),
for the Air 2S, where firmware "added RID support through WiFi Beacon"
([receiver-android #93](https://github.com/opendroneid/receiver-android/issues/93)), and for
the Mavic 3 Enterprise, whose log shows "Transport type: Beacon (Wi-Fi)"
([receiver-android #99](https://github.com/opendroneid/receiver-android/issues/99)); it is
snippet-level for the Mini 4 Pro and Mini 5 Pro
([mavicpilots](https://mavicpilots.com/threads/question-about-rid-on-my-mini-5-pro.155240/)).
The standard itself would allow BT5 Long Range or NAN - the ASD-STAN DRI table makes BT5 LR,
NAN 2.4/5 GHz and Beacon 2.4/5 GHz alternative mandatory options of which only one is required,
with BT4 optional
([opendroneid-core-c README](https://github.com/opendroneid/opendroneid-core-c/blob/master/README.md)) -
so Beacon-only is DJI's choice, not an EN 4709-002 requirement. **Which band and channel DJI
uses (2.4 GHz channel 6 versus 5 GHz channel 149) is not established.**

EU availability is narrower than "depends on model, class mark and firmware". DRI is mandated
only for C1 and above class marks and for specific-category operations
([Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/),
snippet). C0 sub-250 g DJI drones - Mini 3, Mini 4 Pro, and by extension Neo and Flip - are
exempt and are reported to broadcast no RID in Europe, while in the US the same models
broadcast only with the heavier, over-249 g battery
([mavicpilots](https://mavicpilots.com/threads/does-the-dji-mini-3-pro-have-remoteid-in-the-eu-that-broadcasts-the-location-and-altitude.151947/),
[dronexl](https://dronexl.co/2024/02/09/remote-id-update-dji-mini-4-pro/), both snippet), and
users have published firmware tricks to disable RID on the Mavic 3
([mavicpilots](https://mavicpilots.com/threads/how-to-disable-remote_id-on-dh-mavic-3-works.148094/)).
So in the Netherlands the sub-250 g DJI fleet is largely invisible to standard RID.

DJI DroneID over OcuSync is still transmitted by all generations but (a) only while motors are
spinning, per the single source that states it, and (b) only O2/O3 models are decodable in the
clear; O3+/O3 Pro/O4/O4+ models transmit encrypted DroneID that open decoders can only detect
as a burst plus a per-session hash plus RSSI, with position and serial available only via a paid
proprietary service
([alphafox02 README](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/README.md),
[DragonScope product page](https://cemaxecuter.com/?product=dragonscope-drone-id-service),
snippet). Additionally, older Wi-Fi-link DJI drones carry DJI DroneID as an 802.11 vendor IE
with OUI `26:37:12` inside their own beacons - a third format distinct from standard RID
([Kismet parser](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h)).

Note the internal tension between this verdict and verdict 4: verdict 4 refutes the
motors-spinning condition for O2-era firmware while this verdict repeats it as reported. Take
verdict 4's reading - it examined the counter-evidence - and treat the condition as unknown per
model.

**Reasoning summary.** Transport is verified from the OpenDroneID device list and two issue
logs; for post-2022 models it rests on forum snippets rather than a maintained list. No source
anywhere shows a DJI model on BLE or NAN, so "Wi-Fi Beacon only" stands. The class-mark and EU
behaviour is snippet-level throughout. Unresolved: which Wi-Fi band and channel DJI beacons
use, whether any 2024-2026 DJI model added BLE, and the exact EU firmware behaviour per model.
All six searches used.

**Design consequence.** Treat DJI coverage as three disjoint lenses and make the observation
contract distinguish them.

1. **Standard RID** needs a monitor-mode Wi-Fi NIC, not the E200, parsing the beacon vendor IE
   `FA:0B:BC`/`0x0D` on at least 2.4 GHz channel 6 and 5 GHz channel 149 - scan both, because
   the band is unverified - plus a BLE4/BLE5-LR listener for non-DJI drones and add-on modules.
   A BLE-only or iOS-based receiver will miss every DJI drone. Also parse the DJI legacy IE
   `26:37:12` and optionally the French `6A:5C:35`. Expect standard RID only from C1 and above
   DJI aircraft in NL; assume C0 sub-250 g DJI emit none.
2. **E200 DroneID path**: full serial and position decode only for O2/O3; for O3+/O4 design the
   pipeline as detection plus per-session hash plus RSSI/DF only, and label the output
   `dji_droneid_encrypted` rather than promising identity.
3. Because sub-250 g O4 DJI drones broadcast neither decodable RID nor decodable DroneID in the
   EU, the RF-ML/energy classifier is the only detection route for the most common consumer
   models and should be prioritised for DJI O4 OFDM signatures. Add a source/provenance field
   (`standard_rid_wifi_beacon` | `dji_droneid_clear` | `dji_droneid_encrypted_hash` |
   `rf_classifier`) and a confidence, never merging DroneID hashes with RID serials. Validate
   empirically in NL with one C1 DJI and one C0 DJI before freezing assumptions.

---

## 8. `rf-ml-inputs-and-leakage` - spectrogram versus IQ, depth, and benchmark leakage

**Original claim.** For low-SNR drone RF classification, spectrogram (STFT) inputs clearly
beat raw IQ inputs (balanced accuracy 0.842 vs 0.413 at -12 dB SNR in Glüge et al.), model
depth barely matters (VGG11-VGG19 all ~0.90), and published accuracies on DroneRF-type
datasets are inflated by window-level random splits (data leakage).

**Verdict: partly.** The numbers are correct but over-generalised and mis-attributed.

**Corrected claim.**

*(1) The headline comparison.* 0.842 versus 0.413 balanced accuracy at -12 dB (VGG11) comes
from Glüge et al., NCTA 2023, "Robust Drone Detection and Classification from Radio Frequency
Signals using CNNs" - dataset v1, 7 classes, 16,384-sample (1.2 ms) windows at 14 MSps,
128x128 complex STFT - not from the 2024 JRFID/arXiv 2406.18624 paper, whose code contains only
2D VGG models and no IQ comparison
([NCTA_2023_37_CR.pdf](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification/blob/main/NCTA_2023_37_CR.pdf),
[2024 repo](https://github.com/sgluege/Robust-Drone-Detection-and-Classification/blob/main/lib/model_VGG2D.py)).
The comparison is a naive 1D VGG (3-tap `Conv1d`, 25 epochs, from scratch) against the same VGG
in 2D on a linear-scale complex STFT with real and imaginary channels - an **invertible
transform of the same IQ samples** - so it demonstrates an inductive-bias and optimisation
effect, not that time-frequency inputs carry more information. The authors themselves state
that an IQ model with comparable performance may exist. Across all SNRs the gap is about 10
points (0.79 vs 0.90 balanced accuracy, Table 3) and zero at SNR at or above 0 dB; at -12 dB
the other depths scored 0.34-0.35 (IQ) against 0.81-0.83 (SPEC), so 0.413 is the best IQ case,
not a typical one. The SNR is defined as burst carrier power over full 14 MHz-band noise power
with synthetic AWGN or recorded lab-noise mixing, so with 1-3 MHz-wide RC links "-12 dB" is
roughly -1 to -5 dB in band; the figures do not transfer to datasets with other sample rates or
SNR conventions (RFUAV at 100 MSps, DroneRF at 40 MSps real-valued). Third-party evidence shows
architecture matters more than input domain: on DroneRFa with synthetic channels, an IQ-only
CNN-LSTM matched an STFT-EfficientNet at -10 dB AWGN (about 69 % vs 68 %) while an STFT-ResNet
got 47 % and a plain IQ-CNN 33 %
([SE-DCNet](https://github.com/maojinxiang/SE-DCNet/blob/main/results/robustness_comparison_three_channels.png)),
although STFT models are more consistently robust under Rayleigh/Rician fading and dual-branch
fusion is best; another survey reports a raw-IQ model at 94.1 % against a spectrogram model at
97.8 % on RFUAV at high SNR with no low-SNR test
([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub/blob/main/EXPERIMENTS.md)).

*(2) Depth.* "Depth barely matters" is confirmed only within the VGG family on this dataset
(SPEC balanced accuracy 0.900 / 0.897 / 0.899 / 0.898 for VGG11/13/16/19); deeper nets converge
faster, not better. It reflects that low-SNR performance is information-limited by integration
time times bandwidth, so window length matters more than capacity - the 2024 paper moved from
16,384-sample windows to 1,048,576-sample (about 75 ms) windows
([2024 repo README](https://github.com/sgluege/Robust-Drone-Detection-and-Classification/blob/main/README.md)).

*(3) Leakage.* Confirmed and quantified for DroneRF: leave-one-recording-out evaluation drops
AR-versus-Bebop type identification from macro-F1 0.742 to 0.455, which is chance, with only
four independent recordings per drone, and essentially all of the inflation is within-recording
segment leakage
([Shulman 2026, arXiv 2607.01025](https://arxiv.org/abs/2607.01025),
[spectrahawk](https://github.com/shulm/spectrahawk)). The original DroneRF code uses
`StratifiedKFold(shuffle=True)` over segments
([Classification.py](https://github.com/Al-Sad/DroneRF/blob/master/Python/Classification.py)).
But the inflation is task- and capacity-dependent: binary drone-versus-background detection
stays strong under grouped evaluation (ROC-AUC 0.978), and a grouped-versus-window benchmark
with weak 2048-sample models on DroneRF changed accuracy by only 0-3 points (binary RF
0.871 -> 0.857, Spec-CNN 0.863 -> 0.856, type 0.55 -> 0.54, mode 0.43 -> 0.41)
([grouped_benchmark.json](https://github.com/greenbeanss/dronerf-emi-robustness/blob/main/experiments/results/grouped_benchmark.json),
[benchmark_v2_revised.json](https://github.com/greenbeanss/dronerf-emi-robustness/blob/main/experiments/results/benchmark_v2_revised.json)),
because those small models were already near the honest level. Note that Glüge's own protocol
is also a random stratified split over windows from single anechoic-chamber recordings per
class - `train_test_split` with `stratify`, repeated five times, so the folds are not even
disjoint
([train_model_cv5.py](https://github.com/sgluege/Robust-Drone-Detection-and-Classification/blob/main/train_model_cv5.py)) -
and SE-DCNet's split puts every source `.mat` file in train, validation and test
([prepare_labels.py](https://github.com/maojinxiang/SE-DCNet/blob/main/prepare_labels.py)). The
low-SNR spectrogram numbers are themselves within-recording, synthetic-noise results.

**Reasoning summary.** Verified from the PDF shipped inside the cloned repository (Tables 3 and
5, Sections 2.2 and 3.1) and from the training code of both Glüge repositories. A second
leakage pathway - receiver CFO, DC offset and noise-floor fingerprints when classes correlate
with capture hardware - is documented in
[2_Stage_Drone_Detection_Model](https://github.com/TungAnhNguyen5/2_Stage_Drone_Detection_Model/blob/main/rf_pipeline/README.md)
and is directly relevant to training on USRP datasets and deploying on the E200. The
attribution of the -12 dB figures to arXiv 2406.18624 in a third-party survey is a
misattribution
([rfml-moe-hub survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md)).
First-principles check: the complex STFT is invertible, so IQ and STFT inputs carry identical
information; the STFT concentrates a 1-3 MHz burst into a few bins, about 6.5-11.5 dB of
processing gain over the full-band SNR, which a 3-tap 1D VGG must learn implicitly. Six web
searches used; `arxiv.org` fetch blocked once as expected.

**Design consequence.**

1. Make a time-frequency representation the default classifier input on the E200 host: an STFT
   with an FFT size giving roughly 10-100 kHz bins at the E200's ~20 MSPS rate, complex Re/Im
   for classification and log-power for detection gating. Treat "raw IQ versus spectrogram" as
   an architecture choice, not an information choice, and do not budget effort for end-to-end
   raw-IQ nets.
2. Use small backbones (VGG11-BN, MobileNetV3, ConvNeXt-Tiny class) and spend the budget on
   window length (tens of ms to cover burst repetition periods), SNR-aware training (mix
   -20 to +30 dB with recorded 2.4/5.8 GHz background and E200 receiver noise at several gain
   settings), and a burst/energy detector in front of the CNN.
3. State the SNR convention explicitly (in-band versus full-band at the configured sample rate)
   and report per-SNR balanced accuracy. Do not compare numbers across datasets with different
   sample rates.
4. Adopt a leakage-proof evaluation protocol as a hard rule: split by recording, session,
   device unit, day or location (GroupKFold or leave-one-recording-out); train on public
   USRP/bladeRF datasets but test on E200 captures; apply DC/CFO/power normalisation to strip
   receiver fingerprints; report detection metrics (AUC, Pd at fixed false-alarm rate)
   separately from type-ID accuracy; and treat published DroneRF-family type and mode
   accuracies as non-reproducible upper bounds.
5. Use the protocol decoders as the ground-truth labeller for E200 captures, so the classifier
   trains on many independent real recordings instead of the few-recording regime. In the
   `future_sdr` observation contract, emit detection with confidence and SNR as the primary
   field and drone-type classification as a lower-confidence secondary field.

---

## 9. `o4-firmware-channels` - NOT VERIFIED (round-1 finding)

**Status: the adversarial pass was planned for this claim and never ran, because the agent
budget was exhausted.** Everything below is a round-1 finding from the `github-dji` lens. It is
labelled **(unverified, round 1)** everywhere it is used in this record.

**Round-1 claim.** The E200 O4 DroneID firmware in `auto` mode hops only four channels -
2434.5, 5756.5, 5776.5 and 5816.5 MHz - runs the AD9361 single-channel (`uEnv.txt` sets
`mode=1r1t` and `maxcpus=1`) with a 61.44 MSPS path clock, and reports frequency and RSSI per
detection, so 2.4 GHz coverage of the DroneID hop set is incomplete out of the box. The legacy
firmware additionally opens an FPGA correlator device node `/dev/my-axi-droneid-filter0`.

**What it rests on.** String extraction from the two firmware ramdisks redistributed in
[alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid): the new
binary's channel list "2434.5M, 5756.5M, 5776.5M, 5816.5M" alongside "AUTO MODE" and "Predict
switch: freq {} MHz ({} ms before target)"; the AD9361 path clocks `RRX 983040000 245760000
122880000 61440000 61440000 61440000`; `libiio` and `libfftw3f` linkage with no GNU Radio;
functions `set_zc600`/`set_zc147`, `lte_rate_match_rv`, `lte_turbo_decode`,
`get_long_cp_len`/`get_short_cp_len`, `cfo_correct` and `cross_correlation_find_peak_by_fft`;
`uEnv.txt` in both images setting `mode=1r1t` and `maxcpus=1`; and the legacy binary's
`/dev/my-axi-droneid-filter0` open, which the O4 binary does not have. The README says
`device_mode auto` "hops 5.8 GHz channels".

**Why it was queued for verification.** It is a strings-in-a-binary finding about closed
firmware whose source is not published - the build path `/home/jcc/work/Git/mp/antsdr-fw-patch-drone/`
shows a private tree, not anything on MicroPhase's GitHub. Three things need checking on real
hardware before the toolkit depends on them:

* whether the four-channel auto list is the whole scan set or only a default that
  `device_mode` and `fw_setenv` can widen;
* whether the 61.44 MSPS figure is the AD9361 path clock or the rate the decoder actually
  processes - the DroneID numerology accepts any sample rate that is an integer multiple of
  15 kHz giving a power-of-two FFT, so 15.36 MSPS (FFT 1024, CP 80/72), 30.72 (2048, 160/144)
  and 61.44 (4096, 320/288) are all valid
  ([proto17 MATLAB `get_fft_size.m` / `get_cyclic_prefix_lengths.m`](https://github.com/proto17/dji_droneid),
  [DroneSecurity `helpers.py`](https://github.com/RUB-SysSec/DroneSecurity));
* whether `/dev/my-axi-droneid-filter0` means the legacy image does its correlation in the PL,
  which would determine how much Zynq-7020 headroom a co-resident AERIX process has.

**Provisional design consequence, to be re-checked.** Assume the stock O4 image gives partial
2.4 GHz coverage and plan a separate 2.4 GHz scan strategy. Do not assume spare FPGA or CPU
capacity on the board while the DroneID firmware is running. Do not publish the channel list as
a fact about DJI - it is a fact about one vendor's scanner default, if it is a fact at all. The
verified DroneID centre frequencies to compare it against are the 16 in DroneSecurity's live
hop list and the 8 in proto17's README (see the contradiction table below).

---

## 10. `ocusync-phy` - NOT VERIFIED (round-1 finding)

**Status: the adversarial pass was planned for this claim and never ran, because the agent
budget was exhausted.** Everything below is a round-1 finding, mainly from the
`github-video-links`, `academic-en-detection` and `signal-reference-tables` lenses. It is
labelled **(unverified, round 1)** everywhere it is used, notably in
[signal-reference.md](signal-reference.md).

**Round-1 claim.** OcuSync 2 uses 15 kHz subcarriers with FFT 2048 (20 MHz) or 1024 (10 MHz),
cyclic prefixes of 144/72 samples and roughly 1 ms frames; OcuSync 3 and 4 use about 30 kHz
spacing, about 9 MHz of 99 % bandwidth and 5 ms periodicity on the Mini 5 Pro; and cyclic-prefix
autocorrelation separates OcuSync from Wi-Fi, whose subcarrier spacing is 312.5 kHz.

**What it rests on.**

* *OcuSync 2*: Felix Domke's reverse-engineering notes - bandwidths 20/10/3/1.4 MHz plus a
  1.4 MHz-CA mode, FFT 2048 at 20 MHz with 1201 active subcarriers (601 at 10 MHz), CP 144
  (20 MHz) / 72 (10 MHz) with extended 144+16 / 72+8 on selected symbols, packets about 1 ms,
  a downlink layout of RS0 | D x6 | RS1 | D x6 | RS0 with Zadoff-Chu reference symbols, first
  data symbol always QPSK, unused DC subcarrier, implemented on DJI's "Sparrow" ASIC
  ([tmbinc/random dji/ocusync2](https://github.com/tmbinc/random/tree/master/dji/ocusync2),
  verified). This is the only public numeric OcuSync numerology.
* *O3/O4 at 30 kHz*: a single hobby project's cyclostationary detector, which tests two
  hypotheses at 40 MSps - 30 kHz spacing giving lag tau = 1333 samples and a cyclic-frequency
  window of 22-30 kHz, and 15 kHz giving tau = 2667 and 10.5-14.5 kHz - and repeatedly measured
  a stable peak at about 27.99 kHz
  ([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker), verified code,
  unverified physical interpretation).
* *O4 bandwidth and periodicity*: one measurement session on a Mini 5 Pro reporting a 99 %
  bandwidth of 8.921-8.926 MHz spanning about 2403.071-2411.992 MHz, and a 5 ms period with
  strong activity 0-3.27 ms, a gap 3.27-4.47 ms and activity again 4.47-5.00 ms - while also
  reporting FFT 1024, 15 kHz spacing and 600 active carriers for the DroneID burst, and stating
  that 5 ms periodicity alone cannot separate video, C2, RID and DroneID
  ([luyii-code-1/dji-ocusync-droneid-research](https://github.com/luyii-code-1/dji-ocusync-droneid-research),
  verified 2026-08-27).
* *Wi-Fi at 312.5 kHz*: the same cyclostationary work uses a 250 kHz cyclic-frequency probe as
  an orthogonal Wi-Fi discriminator and reports Wi-Fi leakage into the OcuSync test of about
  0.028 % of the Wi-Fi power.

**Why it was queued for verification.** The 30 kHz figure for O3/O4 comes from **one** hobby
repository and is inferred from a measured cyclic peak, not from a DJI document or an FCC
filing. It is in direct tension with the same generation's DroneID burst, which the luyii work
measures at 15 kHz spacing with a 1024-point FFT. The two are reconcilable if the DroneID
broadcast keeps LTE numerology while the video/C2 main link moved to 30 kHz, but no source
states that, and 27.99 kHz is not 30 kHz. The `signal-reference-tables` lens flags exactly this
as unresolved and names the FCC test reports as the route to settle it (see the snippet section
below).

**Provisional design consequence, to be re-checked.** A cyclic-prefix / cyclostationary
front end is still the right OcuSync-versus-Wi-Fi discriminator, but implement it with the
subcarrier spacing as a **parameter** and test both hypotheses per detection rather than
hard-coding 30 kHz, exactly as the source project does. Report the measured cyclic frequency in
the observation record so the question can be settled from the toolkit's own data. Do not
publish "OcuSync 3/4 uses 30 kHz subcarriers" as a fact in any AERIX-facing document.

---

## Contradictions between lenses

Independent research lenses reached the same subjects from different directions and sometimes
disagreed. These are the disagreements that mattered, and what happened to each.

| # | Subject | The two positions | Status |
|---|---|---|---|
| C1 | E200 RF channel count | "2x2 MIMO" vs "SMA:1T1R IPEX:1T1R" | **Resolved** |
| C2 | Analog FPV occupied bandwidth | ">99 % inside +/-4.5 MHz" vs "20-27 MHz" | **Resolved with bounds** |
| C3 | OcuSync 3/4 subcarrier spacing | 30 kHz (one repo) vs 15 kHz (DroneID measurement) | **Open** |
| C4 | RF-Vision 40 MSPS vs the 20 MSPS ceiling | Both true, different meanings | **Resolved** |
| C5 | AD9361 vs AD9363 on the E200 | Schematic vs docs vs device tree | **Resolved, with a risk** |
| C6 | PL-Ethernet throughput | 20 MSPS / 80 MB/s vs 15 MSPS / 60 MB/s | **Open** |
| C7 | DroneID only with motors spinning | One README vs three counter-sources | **Resolved against the claim** |
| C8 | DroneID channel set | 4 vs 8 vs 16 centre frequencies | **Open, and probably not a real conflict** |
| C9 | libiio "1.0" gives 20 MSPS | Version claim vs tag list | **Refuted** |
| C10 | Origin of the -12 dB IQ/STFT numbers | Survey attribution vs the actual paper | **Resolved** |
| C11 | DJI C0 Remote ID in the EU | "no RID in Europe" vs "Mini 4 Pro includes RID" | **Open** |
| C12 | GB 46750-2025 timestamp field | 6-byte Unix ms vs 4-byte seconds since 2019 | **Open** |

**C1 - E200 RF channel count.** The Crowd Supply campaign describes "2x2 MIMO with two SMA
antenna connectors and two U.FL connectors"
([crowdsupply.com](https://www.crowdsupply.com/microphase-technology/antsdr-e200), snippet), a
technology-press article repeats "2x2 MIMO"
([CNX Software](https://www.cnx-software.com/2023/07/03/antsdr-e200-gigabit-ethernet-connected-sdr-with-xilinx-zynq-soc-fpga-supports-70-mhz-6-ghz-range/),
snippet), and MicroPhase's own hardware manual says "2 transmit channels and 2 receive
channels"
([AntsdrE200_Reference_Manual.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Reference_Manual.md)),
while the vendor's own selection table says "SMA:1T1R IPEX:1T1R" and reserves "2T2R MIMO" for
the E310/E316
([AntsdrE200_RF_parameters.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md)).
**Resolved by verdict 1** (`rf-ports`): all of these are true about different things. The
AD9361 die is 2x2; the board exposes one RX and one TX on SMA and the second pair on u.FL; and
the two SMA jacks that Crowd Supply counts are RX1 and TX1, not two RX. The practical answer is
"2RX coherent, one on SMA and one on a supplied u.FL pigtail". The manual's "2 transmit and 2
receive channels" is correct at chip level and misleading at connector level, which is exactly
the kind of statement this log exists to flag.

**C2 - Analog FPV occupied bandwidth.** The `github-video-links` lens recorded the conflict
itself as an open question: one decoder's author measured more than 99.7 % of energy within
+/-4.5 MHz on a 25 mW whoop VTX
([config.hpp](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder/blob/main/src/config.hpp))
while the project brief and the community quote 20-27 MHz.
**Resolved with bounds by verdict 5** (`analog-fpv-bandwidth`): the two numbers describe
different quantities. 19-20 MHz is A/B/E/F channel spacing and 37 MHz is Raceband spacing;
23-27 MHz is a Carson estimate that counts the 6.0/6.5 MHz audio subcarriers or an 8 MHz video
bandwidth as f_max; the 99 %-power core of a low-index, audio-free VTX is 9-10 MHz wide. The
residual disagreement is that the +/-4.5 MHz measurement and the assumed +/-5 MHz deviation are
mutually inconsistent, which the verdict resolves by concluding the measured VTX swung less
than 5 MHz. It is one hobbyist measurement on one VTX with an 8-bit receiver, and no
independent spectrum measurement exists in any open source found. The toolkit therefore
captures at 20 MSPS by default rather than betting on 10.

**C3 - OcuSync 3/4 subcarrier spacing. Open.** One project's cyclostationary detector infers
30 kHz spacing for O3/O4 from a repeatedly measured 27.99 kHz cyclic peak at 5.8 GHz
([RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)), while a separate
Mini 5 Pro (O4) measurement reports 15 kHz spacing with a 1024-point FFT and 600 active
carriers for the DroneID burst and a 99 % bandwidth of about 8.92 MHz at 2.4 GHz
([luyii-code-1](https://github.com/luyii-code-1/dji-ocusync-droneid-research)), and the only
verified OcuSync numerology in existence is OcuSync 2 at 15 kHz
([tmbinc](https://github.com/tmbinc/random/tree/master/dji/ocusync2)). The most likely
reconciliation - the DroneID broadcast keeps LTE numerology while the main link changed - is
not stated by any source, and 27.99 kHz is not 30 kHz either. Both lenses independently flagged
it: `academic-en-detection` records that "OcuSync 3/O4 waveform parameters (30 kHz subcarrier
spacing, 35 kHz with CP=1/4 in one field measurement) come from a single hobby repo and need
confirmation against FCC filings or papers", and `signal-reference-tables` records the same.
**Left open**, and this is precisely why claim 10 (`ocusync-phy`) is marked unverified. The
route to settling it is the DJI OcuSync Air System FCC test report (see the snippet section).

**C4 - RF-Vision's 40 MSPS versus the E200's ~20 MSPS ceiling.** The `academic-en-detection`
lens found a Zynq-7020 + AD9364 node running at 40 MSps over libiio while the
`github-antsdr-platform` lens established a 20 MSPS host figure.
**Resolved by verdict 2** (`host-streaming-tiers`): both are right because they measure
different modes. 40 MSPS is the ADC and DMA rate of a 2,621,440-sample (65.5 ms) snapshot that
then takes 100-200 ms to transfer, a 25-40 % duty cycle; 20 MSPS is a sustained-streaming
figure. Neither is a continuous 40 MSPS pipeline, which 1 GbE cannot carry in sc16 at all
(29.6 MSPS is the arithmetic ceiling). The toolkit adopts this as a design pattern rather than
a contradiction: a third "snapshot/dwell" capture tier.

**C5 - AD9361 versus AD9363.** The vendor documentation says "AD9361/9363" and the public
development schematic draws U11 as an **AD9363**
([ANT-E200_Public.pdf](https://github.com/MicroPhase/antsdr_doc_en/blob/master/schematic/ANT-E200_Public.pdf),
sheets 1 and 11), while the firmware declares the chip as `adi,ad9364` (or `adi,ad9361` after
the `2r2t` change) to unlock 70 MHz-6 GHz and 56 MHz
([linux patch](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/patch/e200/0001-add-support-linux.patch)).
The Crowd Supply listing sells them as two SKUs: an AD9363 variant at $299 covering
325-3800 MHz with 20 MHz bandwidth, and an AD9361 variant at $499 covering 70 MHz-6 GHz with
56 MHz, both 12-bit and 200 kS/s to 61.44 MS/s
([crowdsupply.com](https://www.crowdsupply.com/microphase-technology/antsdr-e200), snippet).
**Resolved as a variant question with a standing risk**: which die is fitted depends on the SKU,
and on an AD9363 board the firmware is operating the part outside its datasheet above 3.8 GHz
and above 20 MHz bandwidth. That directly affects 5.8 GHz FPV and OcuSync work. The unit in
hand must be identified before any 5.8 GHz performance claim is made.

**C6 - PL-Ethernet throughput figure. Open.** openwifi's `antsdr_e200` board README, authored
by MicroPhase, says the network port was moved to the PL because "above 20MSPS sample rate ...
bandwidth of the Ethernet will reach 80MB/s"
([board README](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md)),
while the `openwifi-hw` copy of the same paragraph says 15 MSPS and 60 MB/s
([openwifi](https://github.com/open-sdr/openwifi)). Nobody has measured either on an E200.
**Left open**; verdict 2 works around it by deriving the hard ceiling from packet arithmetic
(29.6 MSPS sc16) rather than from either prose figure.

**C7 - "DJI drones only broadcast DroneID when motors are spinning."** Asserted once, in the
O4 section of one README
([alphafox02](https://github.com/alphafox02/antsdr_dji_droneid/blob/main/README.md)), and
repeated into claim 7 (`dji-eu-rid`). Contradicted by proto17's recording instructions ("Power
on the drone (shouldn't need the controller to be on)"), by DroneSecurity's `mini2_sm` capture
recorded before GPS lock, and by the protocol carrying separate `motor_on` and `in_air` flags.
**Resolved against the claim for O2-era firmware by verdict 4**, and left explicitly unknown for
O4. Two web searches in English and Russian found no independent statement either way. The
toolkit logs the state bits rather than assuming the condition - and note that verdicts 4 and 7
disagree on this point between themselves, with verdict 4 being the one that examined the
evidence.

**C8 - The DroneID channel set. Open, and probably not a real conflict.** Three different
channel lists are in play: the four channels in the E200 O4 firmware's auto mode
(2434.5 / 5756.5 / 5776.5 / 5816.5 MHz, **unverified round 1**, claim 9); the eight observed
centre frequencies in proto17's README (2399.5, 2414.5, 2429.5, 2444.5, 2459.5 MHz and 5756.5,
5776.5, 5796.5 MHz - [proto17/dji_droneid](https://github.com/proto17/dji_droneid)); and the
sixteen in DroneSecurity's live receiver (2414.5, 2429.502441, 2434.5, 2444.5, 2459.5, 2474.5,
5721.5, 5731.5, 5741.5, 5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5 MHz, dwelling
1.3 s per frequency at 50 MSPS -
[DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity)). The two open lists overlap but
neither contains the other: proto17 has 2399.5 and 5796.5 MHz, which DroneSecurity lacks;
DroneSecurity has 2474.5 and the whole 5721.5-5741.5 group, which proto17 lacks. These are
observational unions of different measurement campaigns, not published schedules, and the
`github-dji` lens records that "the exact DroneID hop sequence and timing is not documented
anywhere open" - the 13-point set and the 12-20 bursts-per-channel dwell come from paywalled or
blocked papers. **Left open.** The design response is to scan the union of all three and to
treat any firmware's channel list as a vendor default rather than a property of DJI.

**C9 - "libiio 1.0 gives about 20 MSPS." Refuted** by verdict 2. There is no libiio v1.x
release; the newest tag is v0.26 of 25 September 2024
([tags](https://github.com/analogdevicesinc/libiio/tags)) and the main branch has carried the
"eventually 1.0" API since August 2023. The 1.0-dev `iiod` alone moved a measured ANTSDR figure
from 48 to 52 MiB/s, about 8 %; the roughly 20 MSPS results came from kernel build flags, larger
IIO blocks and pinning `iiod` to core 1
([discussion #875](https://github.com/analogdevicesinc/libiio/discussions/875)). The statement
is to be removed from the toolkit documentation.

**C10 - Where the -12 dB IQ-versus-spectrogram numbers come from.** A third-party survey
attributes 0.842 / 0.413 to the 2024 JRFID paper (arXiv 2406.18624)
([rfml-moe-hub survey](https://github.com/r4d10n/rfml-moe-hub/blob/main/docs/RF_ML_Practitioners_Survey.md)),
but the 2024 repository contains only 2D VGG models and no IQ comparison at all; the figures are
Tables 3 and 5 of the NCTA 2023 paper shipped inside the earlier repository.
**Resolved by verdict 8**: cite NCTA 2023, on the v1 dataset, with 16,384-sample windows at
14 MSps - not the 2024 paper with its 1,048,576-sample windows.

**C11 - DJI C0 Remote ID in the EU. Open.** Forum reports say Remote ID is off in Europe for the
Mini 3 because C0 is exempt
([mavicpilots](https://mavicpilots.com/threads/does-the-dji-mini-3-pro-have-remoteid-in-the-eu-that-broadcasts-the-location-and-altitude.151947/)),
while press coverage says the Mini 4 Pro includes Remote ID
([dronexl](https://dronexl.co/2024/02/09/remote-id-update-dji-mini-4-pro/)), with the US
behaviour reportedly depending on which battery is fitted. Both are snippets, no DJI source was
reachable (`support.dji.com` and `enterprise-insights.dji.com` are egress-blocked), and the
OpenDroneID device list has not been updated for 2024-2026 models. **Left open**; verdict 7
records the sub-250 g fleet as a coverage hole to be validated in the Netherlands with one C1
and one C0 aircraft.

**C12 - GB 46750-2025 timestamp encoding. Open.** The two open implementations of the Chinese
broadcast Remote ID format disagree on the timestamp field: six-byte Unix milliseconds versus
four-byte seconds since 2019-01-01. Neither GB text is openly hosted. **Left open**; it only
matters if Chinese-market firmware turns up in NL, which is itself unverified.

---

## Facts that rest on snippets only

The research sandbox could not reach `ez.analog.com`, `wiki.analog.com`, `arxiv.org`,
`fccid.io`, `crowdsupply.com`, `hackaday.io`, CSDN, Zhihu, bilibili, Habr, cyberleninka, IEEE
DataPort, Zenodo, Kaggle, Hugging Face, SciDB, `jeit.ac.cn`, `sciengine.com` or several Dutch
and Ukrainian hosts. Where a conclusion below still depends on such a host, it is snippet-grade:
a search-engine extract, not a read page. The list is ordered by how much a design decision
leans on it. The "download" column is drawn from the `wanted_downloads` entries the lenses
recorded.

| Fact resting on a snippet | Why it matters | Download to confirm |
|---|---|---|
| The E200 kit ships a Hirose U.FL-to-SMA bulkhead pigtail with under 2 dB loss to 6 GHz | The entire "RX2 is usable" position in verdict 1, and therefore all two-channel DF planning | [crowdsupply.com/microphase-technology/antsdr-e200](https://www.crowdsupply.com/microphase-technology/antsdr-e200); also the [Taobao listing](https://item.taobao.com/item.htm?id=691394502321) for accessory SKUs |
| ADI's statement that RX1/RX2 relative phase holds while LO and sample rate are untouched, and can change on any rewrite of either | The DF calibration policy (per-state calibration tables, AGC off) rests on this one thread | [EngineerZone 601154](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/f/q-a/601154/adalm-pluto-revc-phase-between-rx1-rx2-is-not-stable) and [EngineerZone 554210](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/f/q-a/554210/ad9361-2r2t-operation-for-digital-phase-correction-of-rx-and-tx-pll-s) |
| ADI's DoA whitepaper: phase relationship changes when LO, sample rate or gain change, and during quadrature tracking | The only source that names **gain** as a phase-disturbing event; verdict 1 otherwise has to assert it from first principles | [doa_whitepaper.pdf](https://wiki.analog.com/_media/resources/tools-software/linux-software/doa_whitepaper.pdf) |
| ESP32 and hostapd Remote ID beacons go out at 1 Mbps DSSS | Decides whether an openwifi E200 can see mainstream 2.4 GHz Beacon RID at all. Verdict 6 calls this an inference from defaults, not a measurement | No download will settle it: capture a real RID beacon with a COTS card and read the radiotap rate field |
| Which Wi-Fi band and channel DJI uses for standard RID beacons (2.4 GHz ch 6 vs 5 GHz ch 149) | Sets the Wi-Fi sniffer's channel plan; unverified in verdict 7, so both must be scanned | No reachable DJI source; measure with a C1 DJI aircraft |
| DJI began encrypting DroneID from January 2024 on Mavic 3 Series, Mini 4 Pro and Avata with current firmware, and sells an AeroScope EA500 dongle that decrypts it | Would move specific models across the Tier A / Tier B boundary of verdict 4 | [aerial-defence.com](https://www.aerial-defence.com/the-process-of-encrypting-dji-droneid-has-commenced/) |
| A Chinese series claiming CRC-correct DroneID decoding for O1, O2, O3 **and O4**, with a ~5 dB demodulation threshold and four packet types | Directly contradicts "O4 payloads are encrypted" in verdict 4. If true it changes the whole DJI tiering | [CSDN leegang12 #292](https://blog.csdn.net/leegang12/article/details/149397403) plus the sibling posts [#283](https://blog.csdn.net/leegang12/article/details/148471288), [#305](https://blog.csdn.net/leegang12/article/details/149977416), [#320](https://blog.csdn.net/leegang12/article/details/150761143), [#267](https://blog.csdn.net/leegang12/article/details/147321812) |
| DJI OcuSync Air System measured occupied bandwidth for the 10/20/40 MHz modes, and the hop channel list | The only route to settling contradiction C3 (O3/O4 subcarrier spacing and channel widths) | [FCC SS3-OAS11709 test report](https://fccid.io/SS3-OAS11709/Test-Report/Test-Report-3634081) |
| Autel SkyLink 2.0 and Walksnail Avatar occupied bandwidths | Whole rows of [signal-reference.md](signal-reference.md) are empty without them | [FCC 2AGNTMDC240958A](https://fccid.io/2AGNTMDC240958A/Test-Report/Test-report-part-3-6031063), [FCC 2A78Z-AVATAR](https://fccid.io/2A78Z-AVATAR) |
| TBS Crossfire per-mode parameters: 150 Hz FSK at 42.48 kHz shift and 85.1 kBaud, 50 Hz LoRa, TX channels 0-49 and RX 50-99, no eavesdropping protection | Crossfire is the main sub-GHz alternative to ELRS and has no verified PHY row | [g3gg0.de Crossfire analysis](https://www.g3gg0.de/default/fpv-analysis-of-tbs-crossfire/) |
| Analog VTX "video bandwidth 0-8.0 MHz, audio carrier 6.5 MHz" and the "30 MHz analog channel width" community figure | Both feed the Carson estimate in verdict 5; neither is a measurement | [foxtechfpv TS5828 page](https://www.foxtechfpv.com/58g-600mw-48channel-vtx.html), [oscarliang.com](https://oscarliang.com/fpv-channels/), [RTC6715 receiver datasheet](https://assets.flitetest.com/article_files/RTC6715_1420104047.pdf) |
| The Dutch reading of "bijzondere inspanning" in art. 139c lid 2 sub 1 Sr as systematic recording with more than one apparatus | The legal posture of a multi-node passive network in [regulatory.md](regulatory.md) turns on this single snippet, whose case facts are unknown | [ITenRecht ECLI document](https://www.itenrecht.nl/documents/ecli/56e8eb1b-5a94-40f9-9451-3e83c35ff8c2.pdf), plus [wetten.overheid.nl art. 139c](https://wetten.overheid.nl/BWBR0001854/) |
| The exact transport, timing and message requirements of ASD-STAN prEN 4709-002, and the "restriction" attached to its harmonised reference | The RID receiver's mandatory-transport matrix is built from a whitepaper summary, not the standard | [ASD-STAN prEN 4709-002 P1](http://asd-stan.org/downloads/asd-stan-pren-4709-002-p1/), [ASD-STAN DRI whitepaper](https://cms.stan-shop.org/uploads/2024/01/ASD-STAN_DRI_Introduction_to_the_European_digital_RID_UAS_Standard.pdf), [Decision (EU) 2024/2103](https://eur-lex.europa.eu/eli/dec_impl/2024/2103/oj) |
| Bender's observation that a DJI drone emits 12-20 DroneIDs on one frequency before hopping | Sets the dwell time of any DroneID scan scheduler | [arXiv 2207.10795](https://arxiv.org/abs/2207.10795) |
| The NDSS 2023 paper's detection range, receiver sensitivity and DroneID hopping schedule | Link-budget and coverage planning; only the repository README was readable | [NDSS 2023 paper](https://www.ndss-symposium.org/ndss-paper/drone-security-and-the-mysterious-case-of-djis-droneid/) |
| RFUAV's composition (about 102 GB compressed, 37 classes, USRP X310, 100 MSps, 5.765 GHz centre) and its licence | The largest candidate training corpus; every parameter comes from a third party's notes | [huggingface.co/datasets/kitofrank/RFUAV](https://huggingface.co/datasets/kitofrank/RFUAV) |
| DroneDetect's 60 MHz sample rate and bladeRF capture chain, and the ZHAW v2 class list and size | Decides whether either can be re-rendered to E200 bandwidth | [IEEE DataPort DroneDetect](https://ieee-dataport.org/open-access/dronedetect-dataset-radio-frequency-dataset-unmanned-aerial-system-uas-signals-machine), [Kaggle ZHAW v2](https://www.kaggle.com/datasets/sgluege/noisy-drone-rf-signal-classification-v2) |
| Shulman's leakage study beyond its README abstract, and Glüge's 2024 field-test numbers | The evaluation protocol in verdict 8 leans on both | [arXiv 2607.01025](https://arxiv.org/abs/2607.01025), [arXiv 2406.18624](https://arxiv.org/abs/2406.18624) |
| The full text of GB 42590-2023 and GB 46750-2025 | Settles contradiction C12 and whether Chinese broadcast RID follows ASTM F3411 message formats | [GB 46750-2025 PDF](https://img.antpedia.com/standard/files/pdfs_ora/GB2025/20251130/GB+46750-2025.pdf), [CAAC publication page](https://www.caac.gov.cn/XXGK/XXGK/BZGF/BZGF_GJBZ/202601/t20260120_229783.html) |
| The "UOE (UDP Data Offload Engine)" description of the E200's UHD Ethernet path | Explains why the UHD personality is faster than the IIO one; the RTL was read, the explanation was not | [hackaday.io/project/188635](https://hackaday.io/project/188635-antsdr-e200) |
| The claim that the E200's close-in phase noise is worse than a Pluto's | Would affect every narrowband decode; a single unresolved user complaint on a blocked forum | No download settles it; bench-measure the unit |

---

## Gaps

What this verification pass could **not** establish, drawn from the verdicts themselves and
from the lens-level open questions. Each item is a candidate for round two or for bench work on
the actual hardware.

**Platform.**

1. No measured sustained sample rate for **this** unit on **any** personality. Every IIO number
   comes from a Zynq-7000 board the poster did not always identify as an E200, or from a
   LibreSDR; every UHD number is a vendor table entry or a stress-test default.
2. Whether `otw_format` sc8 and sc12 actually work end to end on the E200 FPGA, and at what
   rate. The packers exist in the driver and the FPGA manifest; nobody has measured them.
3. The magnitude of the RX1-RX2 phase jump per LO retune, per sample-rate write and per gain
   change, on the E200 or on any AD9361 board. Gain dependence is asserted from first
   principles only.
4. Whether the E200's single 10 MHz/PPS MMCX input can take both signals simultaneously, and
   whether the UHD "external" clock source actually locks the AD9361 reference or only
   timestamps PPS.
5. Whether `2r2t` on the Pluto firmware uses the CMOS or LVDS AD9361 interface, which bounds
   the two-channel rate.
6. Which AD936x die is actually fitted to a given E200 (contradiction C5), and how the board
   behaves above 3.8 GHz and above 20 MHz bandwidth if it is an AD9363.
7. Whether the E200 case exposes the RX2 u.FL without opening it.
8. Close-in phase noise, residual DC offset and LO leakage on this board. Nothing measures them.

**DJI.**

9. Claim 9 (`o4-firmware-channels`) was never verified: the four-channel auto list, the 1R1T /
   61.44 MSPS clocking and the `/dev/my-axi-droneid-filter0` FPGA correlator are all
   strings-in-a-binary findings.
10. The DroneID hop sequence and dwell schedule are not documented anywhere open
    (contradiction C8).
11. O4/O3-Pro DroneID encryption is entirely opaque: no public information on algorithm or key
    handling, and the per-session hash's derivation is unconfirmed. The one source claiming
    O1-O4 CRC-correct decode is a blocked Chinese blog series.
12. Open-source OcuSync 3 decoding remains unproven; the closed E200 firmware claims it, and the
    O3 burst variant would have to be reverse-engineered from E200 captures.
13. The licence of `alphafox02/antsdr_dji_droneid` is ambiguous (no root LICENSE, one MIT header)
    and the redistributed firmware binaries carry no stated licence.
14. Whether DroneID transmission really requires spinning motors, per model and per firmware
    (contradiction C7).

**Waveforms.**

15. Claim 10 (`ocusync-phy`) was never verified, and the O3/O4 subcarrier spacing remains open
    (contradiction C3). DJI O3/O4 video-link bandwidths for the 10/20/40 MHz modes could not be
    verified from any fetched source.
16. The DJI C2 uplink's hop rate, dwell and packet period are undocumented anywhere found.
17. HDZero and Walksnail Avatar on-air modulation, symbol rate and occupied bandwidth are not in
    any open repository; only channel plans and chip names were verified.
18. Analog FPV occupied bandwidth rests on a single hobbyist measurement of one VTX; no
    audio-subcarrier handling exists in any open decoder, and PAL chroma is unsupported
    everywhere.
19. Herelink versus OcuSync discrimination: both use LTE numerology and no source gives
    Herelink's CP or reference-symbol structure.
20. Exact TBS Crossfire per-mode LoRa parameters, and the chipset and modulation of TBS Tracer.
21. No open SDR demodulator exists for Semtech FLRC, so the ELRS F- and D-rates would have to be
    written from the SX1280 datasheet.
22. Whether gr-lora_sdr's SF6 really matches SX127x and LR1121-in-compatibility-mode hardware
    has not been tested; ELRS sub-GHz decoding has never been demonstrated end to end against
    real radios.
23. FrSky ACCESS, Futaba FASST, Flysky AFHDS3, Yuneec and Skydroid links have no public
    reverse engineering; Autel SkyLink and Skydio Connect SL are unpublished.

**Remote ID and regulation.**

24. The PHY rate of real Remote ID beacons, from both reference transmitters and commercial
    drones, is inferred from library defaults and never measured (verdict 6). This decides
    whether openwifi can see them.
25. Which band and channel DJI uses for standard RID beacons (verdict 7).
26. Per-model EU RID behaviour for 2024-2026 DJI aircraft, especially the C0 sub-250 g fleet
    (contradiction C11).
27. No open-source SDR receiver for BLE 5 Coded PHY exists in the surveyed set, so Bluetooth
    Long Range RID is out of reach for the E200 and for openwifi entirely.
28. Whether `ice9-bluetooth-sniffer`'s libuhd backend works against MicroPhase's `antsdr_uhd`
    fork is untested.
29. The "restriction" attached to the harmonised EN 4709-002 reference in Decision (EU) 2024/2103
    was not retrieved, and the Dutch legal reading of art. 139c rests on one snippet.
30. Whether Chinese-market firmware broadcasts GB 42590 / GB 46750 frames, and the timestamp
    encoding disagreement between the two open implementations (contradiction C12).

**Machine learning and datasets.**

31. No public pretrained model exists for DJI OcuSync 3/4, ELRS, Crossfire or Remote-ID-era
    links at E200 sample rates. The only released weights cover one DJI class plus five legacy
    RC transmitters.
32. No SigMF-formatted public drone dataset was found, and no dataset contains ELRS, Crossfire,
    SiK or AFHDS-2A signals. Own E200 captures will be required.
33. The accuracy cost of re-rendering 80-100 MSps datasets down to E200 bandwidth has not been
    quantified by any source.
34. CPU inference latency of the complex-STFT VGG on a host at 14-20 MSps was measured nowhere;
    only a Jetson TensorRT figure exists.
35. Exact capture hardware and sample rates remain unverified for DroneRF, DroneDetect, RFUAV and
    CageDroneRF, as do several dataset licences.
36. The generality of the leakage result is unresolved: it is severe for high-capacity models on
    few-recording corpora and nearly absent for small models, so "how much do benchmarks
    overstate" has no single answer.

**Process.**

37. Two of the ten claims never went through the pass at all. Both are used elsewhere in this
    record and both are marked. A round two should start with them, and with contradiction C3,
    which claim 10 would have settled.
38. Every verification agent was limited to six web searches and a sandbox with a large blocked
    host list. Several "not established" results above are budget artefacts rather than evidence
    of absence, and should be re-attempted from a machine with unrestricted egress.
