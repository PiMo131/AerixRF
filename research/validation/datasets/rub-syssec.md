# RUB-SysSec DroneSecurity samples

Two DJI DroneID recordings published with the NDSS 2023 reference receiver.
The IQ is not in this repository. Fetch it from the upstream project and check
the hashes.

- Upstream: <https://github.com/RUB-SysSec/DroneSecurity>, `samples/`
- Licence: the upstream repository's. Check it before redistributing.

| File | Bytes | Complex samples | Duration | Rate | Format | SHA-256 |
|---|---|---|---|---|---|---|
| `mini2_sm` | 5 820 000 | 727 500 | 14.55 ms | 50 MSPS | interleaved `<f4` | `5a17913cb11cde2919347054700345c9e5595eaff7818980d332b8ac8910bc55` |
| `mavic_air_2` | 1 802 240 | 225 280 | 4.51 ms | 50 MSPS | interleaved `<f4` | `623fa40f190d3fd859ec2fd62b379ad9a01a0485db3179ae29ac2e3c7a070450` |

Neither file carries a centre frequency. `mini2_sm` is consistent with a
2414.5 MHz tune: its DroneID band sits 9.63 MHz above the capture centre,
which lands on a documented hop centre. Treat that as an inference, not
metadata.

Ground truth published upstream, and what this toolkit gets, is in
[../real-captures.md](../real-captures.md).

## Reading them

```python
import numpy as np
raw = np.memmap(path, mode="r", dtype="<f").astype(np.float32).view(np.complex64)
```

Then wrap as SigMF (`core:datatype` `cf32_le`, `core:sample_rate` `50e6`) and
run `antsdr-tk droneid <stem>`; the band search and resampling engage by
themselves at that rate.

## These files are NOT contiguous recordings

**Do not measure timing from them.** `mini2_sm` is 727 500 samples, which is
exactly 15 chunks of 48 500 samples, and 48 500 samples at 50 MSPS is 970.0 us.
Every DroneID burst in the file starts between 8002 and 8333 samples into its
own chunk - a spread of 331 samples, 6.6 us, out of a 48 500-sample chunk.
Bursts belonging to the drone rather than to the recorder would be scattered
across the whole chunk. These are triggered extractions with a fixed
pre-trigger window, concatenated.

The frames confirm it from the other side: their `gps_time` field takes four
distinct values spanning 19 990 ms, in a file 14.55 ms long. The reference
implementation parses that field identically and gets the same values, so it is
not a decode error. The chunks were captured seconds apart.

What this costs you: any burst interval, duty cycle, hop dwell or slot
structure measured from these files is a property of RUB-SysSec's extractor.
Measuring one and attributing it to DJI is an easy mistake to make - this
project made it, found a "970 us slot grid with unused slots", and only caught
it because the GPS timestamps could not be reconciled with the file length.
See [../real-captures.md](../real-captures.md).

The files remain excellent for what they are for: burst detection,
synchronisation, demodulation and decoding, all of which are properties of a
single burst.

## What else is in them

`mini2_sm` holds a second emission from about +21 MHz to past the capture edge,
roughly 8 dB below the DroneID band. It is a genuinely separate transmission,
not splatter, and the chunk structure proves it cleanly: chunks 0, 1, 2, 5 and
9 to 14 carry the DroneID band at +27 dB with the second band at -1.5 dB, while
chunks 3, 4, 6, 7 and 8 carry the second band at +18.5 dB with the DroneID band
at -3.6 dB. Perfect anti-correlation - the recorder triggered on two different
signals and gave each its own chunks.

Its OFDM numerology is **not** established. A cyclic-prefix lag sweep reports
15 kHz subcarrier spacing for it, but the same sweep reports 15 kHz for a band
of the capture that is empty (0.0 % active, 6.4 dB peak-to-floor), at nearly
the same confidence: 4.66x lift against 5.09x. That is not a measurement. It is
most likely the aircraft's video or control link, and it is truncated by the
50 MSPS window, so nothing beyond its presence and bandwidth is usable here.
