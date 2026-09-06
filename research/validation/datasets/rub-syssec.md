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

## What else is in them

`mini2_sm` holds a second, wider OFDM emission from about +21 MHz to past the
capture edge, roughly 2 dB below the DroneID band. The toolkit reports it as
detected and not decoded, which is correct: it has cyclic-prefix structure but
it is not a DroneID frame. It is most likely the same aircraft's video or
control link, and it is truncated by the 50 MSPS window, so it is not usable
for anything beyond presence.
