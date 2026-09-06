# Questions after the research phase

The research is in `research/`, the recommendations are the *Proposed* records
in `docs/decisions/`, and a first toolkit lives in `toolkit/`. The questions
below are what I could not decide for you. Each one names the ADR it unlocks.
Where I have a recommendation it is marked **(rec.)**.

## Answered

| Date | Question | Answer | Effect |
|---|---|---|---|
| 2026-09-06 | Q2 scope | DJI and FPV first, wide sweep as an option | [ADR-0010](docs/decisions/ADR-0010-band-coverage.md) **Accepted** |
| 2026-09-06 | Q8 recordings, in part | No time for field captures now. Available airframes: DJI Avata, Avata 2, Mini 4 Pro, Neo, possibly a Matrice, not all at once | Build order reordered; see Q13 |
| 2026-09-06 | Q13 build order | Field captures deferred; prepare what needs no hardware | Reordered below |

Questions still open are numbered as before. The numbering never changes,
because the decision records cite these by number.

## A. Facts only you can check on the unit

**Q1. What exactly is on your board and in the box?**
- Chip marking on the transceiver (U11): AD9361 or AD9363? The public
  schematic shows an AD9363 that the firmware declares as an AD9361 to unlock
  70 MHz-6 GHz and 56 MHz. Performance above 3.8 GHz and above 20 MHz
  bandwidth is then outside the datasheet, which matters for 5.8 GHz work.
- Is there a U.FL-to-SMA pigtail in the kit? The Crowd Supply campaign says
  one ships, MicroPhase's Chinese unboxing page lists none. Without it the
  second receive chain (IPEX RX2) is unreachable.
- Firmware in QSPI: the output of `iio_info -u ip:192.168.1.10 | head` and
  `fw_printenv` over the serial console (root / analog). I assume
  antsdr-fw-patch v0.39, 1r1t mode.
- Host: which machine and OS will sit next to the E200 (a laptop with a
  dedicated 1 GbE port is enough), and do you have a 10 MHz reference or GPS
  disciplined oscillator anywhere?

## B. Scope

**Q2. Which links matter first?** (ADR-0010) — **answered 2026-09-06:**
(a) and (b), with (c) as an option. ADR-0010 is Accepted.

- (a) Consumer DJI: DroneID for OcuSync 2/3, presence for O4, Remote ID.
- (b) FPV and hobby: ExpressLRS 2.4 GHz and 868 MHz, Crossfire, FrSky, analog
  5.8 GHz video, HDZero/Walksnail, OpenIPC.
- (c) Security-style wide sweep, 150 MHz-6 GHz, for links that have left the
  hobby bands (the Russian and Ukrainian sources describe ELRS forks at
  360-1020 MHz and video from 460 MHz to above 6 GHz).
- **(rec.)** (a) and (b) in the default profile, (c) as an optional profile.

## C. Platform choices

**Q3. Firmware personality.** (ADR-0004) Start on the stock IIO firmware with
pyadi-iio, using snapshot captures for anything above 10 MSPS? Are you
willing to boot SD-card images later (the MicroPhase UHD fork for 20 MSPS
continuous streams, the DroneID firmware, openwifi)? **(rec.)** yes to both,
stock IIO first.

**Q4. Time coverage.** Snapshot mode means 25-40 % of the time is observed at
high sample rates. Acceptable for the first tests, or do you want the UHD
path built out immediately for continuous 20 MSPS? **(rec.)** snapshots
first.

**Q5. Closed DroneID firmware.** (ADR-0006) The only thing that decodes
OcuSync 3 DroneID today is MicroPhase's binary, redistributed without a
licence file by a third party. Fine for research and benches; is it
acceptable in an Ecotax product path, or must product decoding be open code
only? **(rec.)** research yes, product decision later, and ask MicroPhase
directly for terms and source.

**Q6. Paid O4 decryption services.** (ADR-0006, ADR-0011) DragonScope and
MicroPhase's online endpoint return serial and position for O4 drones for a
fee, over the internet, with unclear legal standing in the EU. **(rec.)** no.

**Q7. Contract.** (ADR-0008) Keep the AERIX envelope frozen and carry SDR
results as a separate RF detection event (schema 0.1 in
`toolkit/antsdr_toolkit/scan/events.py`) until a field test settles the
fields? **(rec.)** yes.

## D. Ambition

**Q8. Machine learning and recordings.** (ADR-0007) — **partly answered
2026-09-06:** no time for captures now; the fleet is DJI Avata, Avata 2,
Mini 4 Pro, Neo and possibly a Matrice, not all available at once. The
remaining half of this question is below.
 Do you want to invest in
own SigMF recordings and training, or stay rule-based for now? Which drones
and transmitters can you borrow for recordings (DJI Mini 2 or Air 2S for
OcuSync 2/3, a Mini 4 Pro or Air 3 for O4, an ExpressLRS handset, an analog
VTX)? Without owned transmitters no decoder claim can be validated.

**Q9. Localisation.** (ADR-0009) Interest in two-antenna direction finding
later? It needs the pigtail, a length-matched second antenna, a splitter-fed
signal source for calibration, and accepts bearings with errors of several
degrees. TDOA needs a PPS or 10 MHz reference at every node. **(rec.)** defer.

**Q10. Legal.** (ADR-0011) Will Ecotax get a legal review of Dutch art. 139c
Sr and the Telecommunicatiewet before a multi-node deployment records
anything beyond Remote ID? Default for now: store metadata, raw IQ only on
explicit opt-in. **(rec.)** yes, and metadata-first.

## E. Shape and order of the build

**Q12. What should "the toolkit" be for you?**
- A Python package and CLI for experiments (what exists now), a headless
  daemon that feeds RF detection events into the AERIX ingest service, or an
  operator screen? **(rec.)** CLI now, daemon next, no GUI until events are
  trusted.

**Q13. Which build step next?** — **answered 2026-09-06:** no field
captures for now, so item 1 is deferred and the no-hardware work comes
first. Revised order:
1. Field capture kit: capture, sweep, classify on real signals, plus the
   RX1/RX2 phase characterisation script (numbers nobody has published).
2. Finish the open DroneID decoder (turbo decoder, OcuSync 2 golden test,
   then attempt OcuSync 3's four-Zadoff-Chu burst from your own captures).
3. Sub-GHz ExpressLRS decoding through a channeliser and gr-lora_sdr in a
   separate GPL process, validated with an owned transmitter.
4. openwifi on the E200 as a Wi-Fi Remote ID sniffer feeding the existing
   AERIX envelope with `source: future_sdr`.
5. A sweep daemon emitting RF detection events to AERIX ingest.
6. Moving the cheap stages onto the E200's ARM.

## F. Things I need from you

**Q11. Downloads.** The sandbox reaches only github.com and pypi.org. The
full wish list with priorities is the last section of `research/sources.md`
(**Wanted downloads**). The ten that change decisions:
1. MicroPhase's readthedocs site for the E200 (`antsdr-docs.microphase.cn`,
   English and Chinese) as PDF or HTML, plus the CrowdSupply E200 pages.
2. The rtl-sdr.com article on DroneID on the E200 and MicroPhase's DroneID
   firmware release notes, if you can get them from MicroPhase.
3. ASD-STAN prEN 4709-002 text and the ASD-STAN DRI whitepaper.
4. The ITenRecht PDF on "bijzondere inspanning" (art. 139c Sr) and
   Staatscourant 2026 nr. 2035.
5. The Aerial Defence and AeroDefense posts on DJI DroneID encryption
   (which models and firmware since January 2024).
6. FCC test reports: DJI O3 air unit (SS3-OAS11709), Autel SkyLink 2.0
   (2AGNTMDC240958A), Walksnail Avatar (2A78Z-AVATAR), Herelink
   (2A6CG-HX406210).
7. g3gg0's Crossfire reverse-engineering write-up.
8. The CSDN posts by `futon` (B200 DroneID decode) and `leegang12`
   (DroneID physical layer, O1-O4 CRC claim).
9. arXiv PDFs 2406.18624, 2503.09033, 2601.03302, 2504.11967, 2607.01025.
10. GB 46750-2025 full text (Chinese Remote ID format from May 2026).

Drop files in `research/inbox/` with a line in its README, or push them to
any GitHub repository I can read.

**Q14. Branch.** Keep pushing to `claude/antsdr-drone-rf-detection-ac0uxs`,
or open a pull request now for review?
