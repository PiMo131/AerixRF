# antsdr_toolkit

RF-based drone detection with an **ANTSDR E200** (AD9361, 2x2, up to 56 MHz,
Ethernet). This package holds the research-independent core:

- `antsdr_toolkit.device` - the `SampleSource` interface, SigMF file replay and
  synthetic scenes (OFDM-like bursts, LoRa chirps, FM video, GFSK, FHSS).
- `antsdr_toolkit.io` - SigMF recording/playback (`cf32_le` written; `ci16_le`
  and `ci8` from the E200 firmware read and scaled to full scale 1.0).
- `antsdr_toolkit.dsp` - STFT power, Welch PSD, noise floor, 2-D burst
  detection and burst-set features.
- `antsdr_toolkit.bridges` - parser and transports for the E200 DJI DroneID
  firmware output.
- `antsdr-tk` - command line (`info` and `replay` for SigMF files).

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
