# antsdr

Everything about using a MicroPhase **ANTSDR E200** (Zynq-7020 + AD936x SDR,
70 MHz-6 GHz, Ethernet) for RF-based drone detection, classification and
decoding inside AERIX. Passive receive only.

| Directory | What it holds |
|---|---|
| `research/` | The research record: annotated sources in three languages, the state of the art per signal family, the hardware truth for the E200, dataset catalogue, signal parameter tables, regulation, what the Chinese and Russian/Ukrainian scenes add, and a verification log. Start at `research/README.md`. |
| `docs/decisions/` | Architecture Decision Records. Accepted ones are in force; Proposed ones are the research phase's recommendations waiting for answers. |
| `toolkit/` | `antsdr_toolkit`, a Python package and the `antsdr-tk` CLI: E200 capture, SigMF recording and replay, synthetic drone-like scenes, band sweeps, burst detection and features, a heuristic signal-family classifier, a numpy DJI DroneID detector and decoder, analog FPV metrics, the DJI DroneID firmware bridge. Tests run without hardware. |
| `QUESTIONS.md` | The questions the maintainer must answer before the next phase, each tied to an ADR. |
| `research/inbox/` | Drop point for pages and papers the development sandbox cannot reach. |

## Ten things the research established

1. The E200 has one RX/TX pair on SMA and the second on an internal u.FL; both
   receive chains are phase-coherent but need a pigtail and a per-tuning-state
   phase calibration to be used together.
2. Continuous host streaming is about 11-13 MSPS on the stock IIO firmware and
   20 MSPS (29.6 MSPS wire limit) on the UHD firmware; snapshot captures work
   at any rate up to 61.44 MSPS on both.
3. DJI DroneID is unencrypted on OcuSync 2 and 3 and encrypted from O4 (Air 3,
   2023) onward; open decoders handle OcuSync 2 only, the closed MicroPhase
   firmware also handles OcuSync 3, and O4 yields a hash, frequency and RSSI.
4. DJI's EU Remote ID goes out over Wi-Fi Beacon, so AERIX's existing
   receivers, or openwifi on the E200, are the identity path for O4 drones.
5. ExpressLRS 2.4 GHz is detect-only (SX1280 long-interleaver LoRa and FLRC,
   80 channels over 79 MHz); sub-GHz ExpressLRS and Crossfire are decodable in
   principle with existing LoRa/FSK tooling, unproven end to end.
6. Analog 5.8 GHz FPV keeps its energy within about +/-4.5 MHz and decodes at
   10 MSPS; the useful detector metrics are in-band versus shoulder power,
   envelope constancy and line-sync periodicity.
7. Hop period and hop-set size separate the 2.4 GHz RC families (FrSky 9 ms,
   Flysky 3.85 ms, Futaba 6.8 ms, HoTT 10 ms, DSMX 11/22 ms) without decoding.
8. Spectrogram inputs beat raw IQ at low SNR, model depth barely matters, and
   published accuracies are inflated by window-level splits and collapse on
   live SDR data; own E200 recordings are a precondition for any field model.
9. The Chinese contribution is datasets (DroneRFa, DroneRFb-DIR), per-model
   hop tables and GB 42590/46750 Remote ID tooling; the Russian and Ukrainian
   scene documents links far outside hobby bands and RSSI-only detectors.
10. Dutch law exempts single-receiver listening but a multi-node recording
    network may count as a "bijzondere inspanning"; Remote ID is the safest
    data class and jamming is reserved to police and Defence.

Sources for each are in `research/`.
