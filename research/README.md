# Research record: RF drone detection with an ANTSDR E200

This directory is the output of the research phase: what is publicly known about detecting, classifying and decoding drone RF links, what a MicroPhase ANTSDR E200 can actually do with
each of them, and where the evidence stops. It is a record, not a tutorial. Passive receive only ([ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md)). Every number, band,
rate, licence, date and model name here and in the other documents carries the source it came from; nothing is written from memory, and where the evidence is snippet-only or
contradictory the text says so.

## The documents

| File | What it is for |
|---|---|
| [sources.md](sources.md) | Annotated bibliography of all 296 unique sources: language, kind, year, relevance 1-5, verified/snippet flag, extracted facts and an E200 note per entry; ends with the **Wanted downloads** wish list. |
| [landscape.md](landscape.md) | State of the art per signal family (DJI DroneID/OcuSync, Wi-Fi drones and Remote ID, RC and telemetry, video links, detection and classification methods, localisation), judged against what the E200 can do. |
| [hardware-e200.md](hardware-e200.md) | Board-level truth: parts, clocks, RF ports, the three firmware personalities, host streaming tiers, and where the vendor prose disagrees with the vendor's own code. |
| [datasets.md](datasets.md) | Every public drone-RF corpus the sweep could reach, with capture hardware, rate, contents and flaws, the cost of using it at E200 rates, and how to record our own so it is comparable. |
| [signal-reference.md](signal-reference.md) | Parameter tables (centre frequencies, bandwidths, hop periods, hop-set sizes, modulation) laid out so a heuristic classifier can be written straight off the page. |
| [regulatory.md](regulatory.md) | Dutch and EU legal frame for passive reception and storage, EU Remote ID obligations and transports, DJI's implementation, the Chinese and Russian equivalents, receiver choice per transport. |
| [foreign-perspective.md](foreign-perspective.md) | What the Chinese, Russian and Ukrainian material adds: datasets, hop-feature tables, GB Remote ID tooling, frontline band drift, the DIY detector scene. |
| [verification-log.md](verification-log.md) | The audit trail: the ten design-critical claims sent for adversarial verification, their verdicts and corrected claims, cross-lens contradictions, and the snippet-only facts still to confirm. |
| [inbox/](inbox/) | Drop point for pages, papers and datasets the sandbox could not reach; its README carries the required provenance table. |

Decisions that came out of this are in [../docs/decisions/](../docs/decisions/); the open questions for the maintainer are in [../QUESTIONS.md](../QUESTIONS.md).

## Ten headline findings

1. **The host link, not the AD9361, is the binding constraint.** 1 GbE with a 1500-byte MTU caps continuous single-channel sc16 streaming at about 29.6 MSPS by arithmetic; the stock
   PlutoSDR-compatible IIO firmware is CPU-bound in `iiod` at roughly 11-13 MSPS, MicroPhase rates the UHD personality at 20 MSPS "transmission bandwidth to host", and snapshots up to
   61.44 MSPS work on both because the DMA lands in DDR first, so DroneID's 15.36 MSPS is no continuous stock-firmware stream *(verified: verdict 2, `host-streaming-tiers`;
   [vendor table](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters.md),
   [libiio #875](https://github.com/analogdevicesinc/libiio/discussions/875))*. See [hardware-e200.md](hardware-e200.md).
2. **The board does one job at a time.** QSPI holds the factory Pluto/IIO firmware; the UHD firmware, the closed DJI DroneID firmware and openwifi each boot only from SD, selected by the
   BOOT switch, and none of them coexist *(verified: verdict 6, `openwifi-personality`; [antsdr-fw-patch](https://github.com/MicroPhase/antsdr-fw-patch),
   [antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid), [openwifi E200 notes](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md))*.
3. **Two coherent receivers, one on an internal u.FL.** MicroPhase's table reads `SMA:1T1R IPEX:1T1R`; both RX chains hang off one AD9361 RX PLL so they are coherent, but rewriting the LO
   or the sample rate re-runs the init calibrations and can move the RX1/RX2 phase offset, and on the Pluto firmware the second chain does not exist until `mode=2r2t` is set in the U-Boot
   environment. No measured E200 phase figure exists anywhere *(verified: verdict 1, `rf-ports`)*. See [hardware-e200.md](hardware-e200.md).
4. **DJI DroneID: the PHY is settled, the decode coverage is not.** Two independent implementations agree on 15 kHz subcarriers, 600 data carriers plus a nulled DC, 9 OFDM symbols (8 on
   Mavic Pro and Mavic 2), Zadoff-Chu pilots with roots 600 and 147, QPSK and LTE turbo coding, in a ~640 us burst about every 600 ms ([proto17](https://github.com/proto17/dji_droneid),
   [DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity)). Open decode is verified only on OcuSync-2-era airframes (Mini 2, Mavic Air 2); O3 decoding is unfinished in public code
   and O4 payloads are encrypted, yielding a per-session hash, frequency and RSSI only *(verified: verdict 4, `dji-generation-coverage`)*. See [landscape.md](landscape.md).
5. **For encrypted-DroneID drones, identity comes from standard Remote ID over Wi-Fi.** DJI implements ASTM F3411 / EN 4709 as an 802.11 Beacon vendor IE (OUI FA:0B:BC, type 0x0D) only,
   no Bluetooth and no Wi-Fi NAN, and EU C0 sub-250 g models are exempt and reported to broadcast nothing *(verified: verdict 7, `dji-eu-rid`)*. openwifi on the E200 is the wrong receiver
   for it: it is OFDM-only and cannot demodulate the 802.11b rates reference RID transmitters use on 2.4 GHz, inferred from their defaults rather than measured *(verified: verdict 6)*.
   See [regulatory.md](regulatory.md).
6. **RC links: the modern ones are detect-only, the legacy ones separate on timing.** Every 2.4 GHz ExpressLRS mode uses SX1280 bandwidth code 0x18 (812.5 kHz nominal) with SF5-SF8 and an
   undocumented long interleaver, or FLRC, or LR1121 GFSK, and no public SDR decoder implements any of them; the 80-channel hop table spans 2400.4-2479.4 MHz, wider than the E200's 56 MHz
   *(verified: verdict 3, `elrs-decodability`)*. Legacy families still fall out of hop period and hop-set size alone: FrSky D8/D16 9 ms over 47 channels, Flysky AFHDS-2A 3.85 ms over 16,
   Futaba S-FHSS 6.8 ms over 30, Graupner HoTT 10 ms over 75, Spektrum DSM2/DSMX 11 or 22 ms over 23
   ([DIY-Multiprotocol-TX-Module](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module)). See [signal-reference.md](signal-reference.md).
7. **Analog 5.8 GHz FPV decodes, but 10 MSPS does not capture all of it.** It is wideband FM of composite video; one HackRF measurement on a 25 mW whoop VTX found under 0.3 % of the energy
   outside +/-4.5 MHz, yet the 6.0 and 6.5 MHz audio subcarriers and PAL chroma sit beyond a 10 MSPS Nyquist, so 20 MSPS (fpv-sdr's own E200 default) is the capture default and 10-12 MSPS
   the fallback *(verified: verdict 5, `analog-fpv-bandwidth`; [5G8atv](https://github.com/zubon2003/5G8atv-rf-hackrf-decoder), [fpv-sdr](https://github.com/lukeswitz/fpv-sdr))*.
8. **Use a time-frequency front end, and distrust published accuracies.** VGG11 scored 0.842 balanced accuracy on a complex STFT against 0.413 on raw IQ at -12 dB SNR (Glüge et al., NCTA
   2023), the gap closing to zero at 0 dB and above; grouped evaluation collapses DroneRF type identification from macro-F1 0.742 to 0.455, which is chance *(verified: verdict 8,
   `rf-ml-inputs-and-leakage`; [Noisy-Drone-RF](https://github.com/sgluege/Noisy-Drone-RF-Signal-Classification), [spectrahawk](https://github.com/shulm/spectrahawk))*. Domain shift bites
   harder than SNR: statistical features fall from 100 % to 42.3 % on an unseen individual airframe while ConvNeXt keeps 92.0 % ([rfml-moe-hub](https://github.com/r4d10n/rfml-moe-hub)).
   See [datasets.md](datasets.md).
9. **The foreign-language material contributes data and bands, not code.** The Chinese value is datasets, per-model hop tables and Remote ID tooling: DroneRFa was recorded with a USRP-2955
   at 100 MS/s ([JEIT 10.11999/JEIT230570](https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570)), GB 42590-2023 has been in force since 2024-06-01 and GB 46750-2025 takes effect
   2026-05-01 in a format an ODID-only parser silently drops ([XC-RemoteID](https://github.com/luolitao/XC-RemoteID), [remoteid](https://github.com/luolitao/remoteid)). Russian and
   Ukrainian sources put control links at 415-640 MHz and analog video anywhere from 460 to 6184 MHz, far outside the hobby bands, and the open code found there is RSSI-level only
   ([techuav mirror](https://github.com/techuav/techuav.github.io), [SkySweep32](https://github.com/bobberdolle1/SkySweep32)). See [foreign-perspective.md](foreign-perspective.md).
10. **Dutch law permits listening but not obviously a recording network.** Art. 139c lid 2 sub 1 Sr exempts what a radio receiver picks up unless a "bijzondere inspanning" or a
    not-permitted receiver is used, and a cited interpretation treats systematic recording with more than one receiving apparatus as exactly such an effort
    ([art. 139c](https://maxius.nl/wetboek-van-strafrecht/artikel139c)); Remote ID, a mandated one-way public broadcast, is the safest data class, and disruption, take-over and shooting
    down are reserved to police and Defence ([Staatscourant 2026 nr. 2035](https://veiligesmartcities.nl/wp-content/uploads/2026/03/stcrt-2026-2035.pdf)). Every Dutch legal source was
    snippet-only. See [regulatory.md](regulatory.md).

## How the research was done

**Thirteen lenses.** Each lens was one agent with its own question, source language and search budget: `github-antsdr-platform`, `github-dji`,
`github-rf-ml`, `github-rc-links`, `github-video-links`, `github-df-tdoa`, `academic-en-detection`, `academic-en-datasets`, `web-zh-community`,
`academic-zh`, `web-ru-community`, `regulatory-rid`, `signal-reference-tables`. Together they logged 368 queries and returned 385 annotated source entries
(counted from `finders_all.json`), 296 unique after deduplication: English 208, Chinese 50, Russian 24, Ukrainian 8, Dutch 6 ([sources.md](sources.md)).

**Seven deep code reads.** These were cloned and read file by file rather than summarised, because the toolkit will either reuse or re-implement them:
`RUB-SysSec/DroneSecurity` (AGPL-3.0) with `proto17/dji_droneid` (MIT); `MicroPhase/antsdr_doc_en`, `antsdr_uhd` and `antsdr-fw-patch` (GPL-3.0);
`sandialabs/gr-fhss_utils` (GPL-3.0-or-later); `lukeswitz/fpv-sdr` (conflicting MIT and GPL-3.0 notices in one tree);
`sgluege/Robust-Drone-Detection-and-Classification` (GPL-3.0); `jonkraft/Pluto_Beamformer` (no LICENSE file, ADI BSD headers);
`ALPssdz/RF-Vision-UAV-Tracker` (MIT, with AGPL and proprietary dependencies). Licence detail per repo is in [sources.md](sources.md) and drives
[ADR-0003](../docs/decisions/ADR-0003-third-party-code-and-licences.md).

**Adversarial verification and a critic pass.** Ten claims that would drive a design decision were pulled out of the first round and sent back with
instructions to break them against primary sources, not to confirm them. Each verifier had six web searches and every one used all six. Eight completed, and
all eight came back `partly`: not one round-1 claim was wholly right or wholly wrong, and the corrected versions are what the other documents use
([verification-log.md](verification-log.md)). Each finished document was then read by a critic agent whose only task was to check every number, name, licence
and date against the evidence JSON and flag unsourced facts, overreach, snippet-only claims presented as verified, and broken links.

**Sandbox constraints.** The research ran in a sandbox that could reach only `github.com` and `pypi.org` over HTTP. Everything else was available as
search-engine snippets only: arXiv, IEEE, MDPI, CSDN, Zhihu, bilibili, habr, cyberleninka, SciDB, Zenodo, Kaggle, Hugging Face, IEEE DataPort, fccid.io,
crowdsupply.com, ez.analog.com, wiki.analog.com and the Dutch legal sites. The whole session shared a 200-search budget which ran out during the fourth lens,
so `github-video-links`, `github-df-tdoa`, `academic-en-detection` and `academic-en-datasets` logged 11-14 queries against 45-51 for the first four and rest
almost entirely on GitHub-hosted material; GitHub search itself rate-limited (HTTP 429) in two lenses. A session limit then killed the first run of the
remaining five lenses (`web-zh-community`, `academic-zh`, `web-ru-community`, `regulatory-rid`, `signal-reference-tables`); they were re-run in a second round
with 22-26 queries each.

## How confidence is marked

* **verified** - an agent cloned the repository or fetched the page and read it. **snippet** - only a search-engine snippet was reachable, so re-check it
  against the original before it drives a design decision; the flag is per source in [sources.md](sources.md) and repeated inline wherever such a fact carries
  weight. **inference** - arithmetic or first-principles reasoning on verified constants, labelled where it appears (for example the 29.6 MSPS wire limit).
* *(verified: verdict N, `key`)* - the claim went through the adversarial pass and this is the corrected version; N is the 1-based position in `verdicts.json`,
  mirrored in [verification-log.md](verification-log.md).
* **unverified round 1** - a first-round finding queued for verification that was never checked. Two are used in the record and labelled at every use.

## What was lost to usage limits and is still open

The verification pass was budgeted for ten claims and completed eight. The two that never ran are recorded in [verification-log.md](verification-log.md) as
unverified round-1 findings and carry that label wherever they are used:

* `o4-firmware-channels` - the E200 O4 DroneID firmware in auto mode hopping only 2434.5, 5756.5, 5776.5 and 5816.5 MHz, running 1R1T at a 61.44 MSPS path
  clock, the legacy firmware using an FPGA correlator at `/dev/my-axi-droneid-filter0`. Used in [hardware-e200.md](hardware-e200.md) and [landscape.md](landscape.md).
* `ocusync-phy` - OcuSync 2 as 15 kHz subcarriers with FFT 2048/1024, CP 144/72 and ~1 ms frames; O3/O4 at roughly 30 kHz spacing with ~9 MHz 99 % bandwidth and 5 ms periodicity on the
  Mini 5 Pro; cyclic-prefix autocorrelation separating OcuSync from Wi-Fi's 312.5 kHz. Used in [landscape.md](landscape.md) and [signal-reference.md](signal-reference.md).

Several second-pass reviews of the written documents were also cut short by agent usage limits. Treat any statement here that is not marked **verified** or
backed by a verdict the way the verification pass treated its own inputs.

## How to add a source

1. If neither the sandbox nor your browser can reach it from here, download it by hand into [inbox/](inbox/) and add a row to the table in `inbox/README.md`
   (file, origin URL, why it is here, date). Large binaries stay out of git: record a link and a checksum instead.
2. Add the entry to the matching section of [sources.md](sources.md) in the existing format: a heading with a one-line description, then relevance `n/5`, language, kind, year and the
   verified/snippet flag, the URL, a short summary, a bullet list of extracted facts, and an `*E200:*` line saying what it means for this board.
3. Put the facts where they belong (parameters in [signal-reference.md](signal-reference.md), platform facts in [hardware-e200.md](hardware-e200.md)), each with its URL next to it. If a
   new source contradicts the record, do not overwrite: add it to the contradictions section of [verification-log.md](verification-log.md) with which way the evidence leans and why.
4. If it settles a gap below or an item on the **Wanted downloads** list at the end of [sources.md](sources.md), strike that item and name the source that closed it.

## Gaps

The limits of the record as a whole; each document carries its own longer list.

* **No E200 measurements exist anywhere.** Sustained MSPS on stock v0.39 IIO firmware, whether sc8/sc12 over-the-wire works on its FPGA, RX1/RX2 phase coherence and drift, close-in
  phase noise (one unresolved user complaint of worse-than-Pluto at 1 GHz), and whether the case exposes the RX2 u.FL without opening it: all bench work.
* **OcuSync 3 and O4.** No open decoder finishes O3; O4 encryption has no published algorithm or key handling and the only route to its payload is a paid
  closed service; the E200 O4 firmware's channel set and its per-session hash are unverified (`o4-firmware-channels`).
* **The closed links have no published waveform parameters.** Autel SkyLink, Skydio Connect SL, Walksnail Avatar, Herelink framing, HDZero's PHY and DJI
  O3/O4 video bandwidths beyond one Mini 5 Pro measurement sit behind blocked FCC test reports or are unpublished.
* **Remote ID reception details.** Which band and channel DJI beacons on (2.4 GHz ch 6 vs 5 GHz ch 149) is not established, the PHY rate of commercial RID
  beacons is unmeasured, no surveyed open SDR tool decodes BLE 5 Coded PHY, and the two open GB 46750 implementations disagree on the timestamp encoding.
* **Datasets.** No public drone-RF corpus is in SigMF; none contains ELRS, Crossfire, SiK or O3/O4 recordings; the primary pages, licences and sizes of DroneDetect, CardRF, UAVSig,
  DroneRFb-DIR and CageDroneRF were unreachable; and the accuracy cost of re-cutting 80-100 MS/s corpora to E200 bandwidth has never been quantified.
* **Dutch and EU legal detail.** Every Dutch source is snippet-only, including the case the "bijzondere inspanning" reading rests on; no Telecommunicatiewet
  article on receive-only equipment was confirmed; and no guidance was found on storing Remote ID operator identifiers under the GDPR.
* **The foreign-language scenes were only half sampled.** CSDN, Zhihu, bilibili, CNKI, habr and cyberleninka were unreachable, so Chinese and Russian evidence is limited to what GitHub
  mirrors; no Chinese-language work using any MicroPhase board for drone detection was found, and no Russian or Ukrainian open IQ-level classifier surfaced at all.
* **Localisation.** No quantitative DoA accuracy for a two-element AD9361 interferometer, no reported E200 TDOA, no open passive-radar project with drone
  micro-Doppler detections, and the E200's simultaneous 10 MHz plus PPS capability is unconfirmed.
