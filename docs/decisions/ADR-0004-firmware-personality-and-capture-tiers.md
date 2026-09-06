# ADR-0004: Firmware personality and capture tiers

- **Status:** Proposed (needs the maintainer's answer to Q3 and Q4 in `../../QUESTIONS.md`)
- **Date:** 2026-09-06
- **Sources:** `../../research/hardware-e200.md`, `../../research/verification-log.md` (claims `stream-rate`, `rf-ports`)

## Context

The E200 ships with three mutually exclusive personalities. The factory
PlutoSDR-compatible IIO firmware lives in QSPI and is reachable with
pyadi-iio at `ip:192.168.1.10`. The UHD (B210-compatible) firmware and the
MicroPhase DJI DroneID firmware boot only from the SD card. The personalities
differ in what they can stream to the host over the single 1 GbE port:

| Personality | Continuous host stream (verified or vendor figure) | Snapshot capture | Notes |
|---|---|---|---|
| IIO (stock v0.39) | about 11-13 MSPS sc16, CPU-bound in iiod on the Cortex-A9 | any AD9361 rate up to 61.44 MSPS into `rx_buffer_size` bursts | pyadi-iio, ADI-BSD, no extra install beyond libiio |
| UHD (MicroPhase fork, GPL-3) | 20 MSPS sc16 vendor figure; 29.6 MSPS is the 1500-byte-MTU wire limit; sc8/sc12 formats exist but are unmeasured | same | PL-side Ethernet bypasses the ARM; needs a private UHD 4.1 build and SD boot |
| DroneID firmware (closed binary) | decoded CSV/binary reports only, no IQ | none | decodes OcuSync 2/3 DroneID on the ARM; O4 gives a hash only |
| openwifi | 802.11 frames via mac80211, no IQ | none | Wi-Fi Remote ID beacons on channel 6; Viterbi core halts after about 2 h |

Everything in the toolkit that is bandwidth-hungry (DroneID at 15.36 MSPS,
OcuSync video at 20 MHz, 5.8 GHz FPV sweeps at 20 MSPS) exceeds the stock IIO
continuous rate but fits the snapshot mode.

## Decision

1. The toolkit's default device path is the **stock IIO firmware with
   pyadi-iio**, in two capture tiers that the code names explicitly:
   `continuous` (sample rate at or below 10 MSPS single channel, 5 MSPS per
   channel with two) and `snapshot` (any rate up to 61.44 MSPS, buffers of
   50-200 ms, a scheduler that accepts a 25-40 % duty cycle).
2. The **UHD personality is optional** and only used through a separate
   process (GPL-3), for users who need 15-20 MSPS continuous streams. It is
   not required for the first field tests.
3. The **DroneID firmware is a third personality the toolkit only talks to**
   over its TCP/UDP report protocol (see ADR-0006); switching personalities is
   a manual SD-card and DIP-switch action documented in
   `../../research/hardware-e200.md`.
4. Every SigMF capture records the personality, the tier, the wire format and
   the duty cycle, so later analysis knows what time coverage a capture had.

## Consequences

- No firmware build is needed to start. The first day is: plug in, `iio_info`,
  `antsdr-tk capture`.
- Continuous wideband monitoring is limited to 10 MSPS until either the UHD
  path or on-board processing exists.
- DroneID decoding on the host runs on snapshots, so a burst that repeats every
  ~600 ms is caught with a probability equal to the duty cycle unless the
  scheduler dwells long enough on one channel.

## Alternatives considered

- UHD as the default: better rates, but a GPL UHD fork in a private prefix, SD
  boot, and no pyadi-iio; rejected as the *first* step, kept as an option.
- Custom PL firmware (channeliser or sc8 packing): the only way above 30 MSPS
  continuous; deferred, experimental.
