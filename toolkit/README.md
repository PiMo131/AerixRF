# antsdr_toolkit

RF-based drone detection with an **ANTSDR E200** (AD936x, 70 MHz to 6 GHz,
Ethernet). Passive receive only.

Docstrings and comments here cite their evidence. A marker like
*(verified: `host-streaming-tiers`)* names a claim that went through the
adversarial verification pass; the corrected wording, the primary sources and
what was found to be wrong about the original are under that key in
[`../research/verification-log.md`](../research/verification-log.md). Anything
marked *inferred* or *unverified* is arithmetic or a single unconfirmed
report, and is worth re-checking before you rely on it.

| Module | What it does |
|---|---|
| `antsdr_toolkit.hardware` | The verified E200 facts as data: RF ports, sample-rate limits, host-link ceilings per firmware personality, capture tiers, the 2r2t and clock-calibration procedures |
| `antsdr_toolkit.device` | `SampleSource` interface, the E200 itself over pyadi-iio, SigMF replay, and synthetic scenes (OFDM bursts, LoRa chirps, FM video, GFSK, hopping) |
| `antsdr_toolkit.io` | SigMF recording and playback (`cf32_le` written; `ci16_le` and `ci8` from the E200 read and scaled) |
| `antsdr_toolkit.dsp` | STFT power, Welch PSD, noise floor, 2-D burst detection, burst-set features, cyclostationary numerology tests |
| `antsdr_toolkit.scan` | Band plans, dwell planner, sweeper, and the provisional RF detection event schema |
| `antsdr_toolkit.classify` | The signature table (26 link families with their sources) and the heuristic scorer |
| `antsdr_toolkit.droneid` | DJI DroneID: constants, Zadoff-Chu pilots, coding, a burst synthesiser and a receiver that decodes |
| `antsdr_toolkit.analog` | Analog 5.8 GHz FPV: the channel plan, the width and envelope gates, a line-rate lock that names the video standard, and a decoder that turns the carrier into pictures |
| `antsdr_toolkit.fleet` | What each DJI airframe actually yields: link generation, EU class label, and every route to its identity, with the confidence of each claim |
| `antsdr_toolkit.remoteid` | Two payloads that ride in 802.11 beacons: standard Remote ID (ASTM F3411 / EN 4709) under the ASD-STAN OUI, and DJI's own proprietary DroneID under OUI 26:37:12 |
| `antsdr_toolkit.bridges` | Parser and transports for the E200 DroneID firmware's own output |

### Commands

```sh
antsdr-tk info capture.sigmf-meta        # what is in a recording
antsdr-tk replay capture --chunk 65536   # stream it in chunks
antsdr-tk capture --freq 2.4295e9 --rate 15.36e6 --seconds 2 --dry-run out
antsdr-tk sweep --band ism-2g4 --file capture --runs 2
antsdr-tk classify capture --band ism-2g4
antsdr-tk droneid capture --json result.json
antsdr-tk video capture -o frames/ --frames  # analog FPV to PNG
antsdr-tk remoteid rid.pcap --unique         # Remote ID from a Wi-Fi capture
antsdr-tk fleet "Mini 4 Pro"                 # what can I get from this drone?
antsdr-tk firstrun --dry-run                 # plan the first session with the board
antsdr-tk firstrun -o firstrun               # then run the whole thing
```

### The hardware facts that shape everything

- **RX1 is the SMA connector, RX2 the internal u.FL.** Both come from one
  AD936x and share its receive oscillator, so they are phase-coherent, but the
  second one needs a pigtail and the firmware's `2r2t` mode
  (`antsdr-tk capture --help` prints the `fw_setenv` sequence).
- **Continuous streaming is about 11 to 13 MSPS on the factory IIO firmware**
  (CPU-bound in `iiod`), about 20 MSPS on the UHD personality, with 29.6 MSPS
  the hard wire limit of 1 GbE. Snapshot capture reaches 61.44 MSPS on both.
  The toolkit calls these the `continuous` and `snapshot` capture tiers and
  records which one a capture used.
- **DroneID needs 15.36, 30.72 or 61.44 MSPS**, never 20 MSPS: the rate must
  be a multiple of the 15 kHz subcarrier spacing.

Licence policy for reused work is `../docs/decisions/ADR-0003`; the research
behind these numbers is in `../research/`.

Conventions: IQ is `np.complex64`, shape `(n,)` or `(channels, n)`; rates and
frequencies are floats in Hz; frequency axes are absolute Hz; powers are dB
relative to full scale (`|x| == 1.0`). No hardware library is imported at
module import time.

## Install

```sh
python -m pip install -e .            # core: numpy, scipy, sigmf
python -m pip install -e ".[dev]"     # + pytest, ruff
```

Hardware and optional extras:

| extra   | pulls in                    | purpose                                  |
|---------|-----------------------------|------------------------------------------|
| `e200`  | `pyadi-iio`, `pylibiio`     | talk to the E200 over Ethernet (libiio)  |
| `zmq`   | `pyzmq`                     | stream samples/reports between processes |
| `viz`   | `matplotlib`                | spectrogram and burst plots              |

`pylibiio` needs the native `libiio` shared library on the host.

## Use

```sh
antsdr-tk info capture.sigmf-meta
antsdr-tk replay capture --chunk 65536 --max-chunks 10
```

```python
from antsdr_toolkit.device import SigmfFileSource

with SigmfFileSource("capture", loop=False) as src:
    print(src.info)
    for chunk in src.iter_chunks(1 << 16):
        ...
```

## Tests

```sh
python -m pytest -q
```

Tests are deterministic (seeded `numpy.random.Generator`) and need no hardware.
