# GPT DJI telemetry audit — H1 / H7 / H10

Date: 2026-09-06

Branch: `gpt/antsdr-live-capture-integrity`

This audit is about **DJI's proprietary DroneID/OcuSync telemetry**, not ASTM/Open Drone ID. The latter is handled by the AERIX ESP32-C5/S3 path and is not a priority for ANTSDR.

## Why this path matters to AERIX

For compatible DJI generations, a CRC-valid proprietary DroneID frame can expose more than simple RF presence. The current 91-byte v2 parser contains fields for:

- aircraft latitude / longitude;
- altitude and height;
- app/controller latitude / longitude;
- home latitude / longitude;
- serial number / product type;
- velocity-like N/E/up fields;
- yaw-like angle and GPS time.

RUB-SysSec's published Mavic Air 2 sample is the important reality check: it contains both aircraft and operator/app coordinates. That makes this decoder directly relevant to AERIX's `drone position` and potentially `pilot/controller position` goals.

## H1 — frame layout and field semantics

**Status: core location layout validated; some non-location units remain evidence-limited.**

### Strong evidence

The current parser layout is 91 bytes:

```text
<BBBHH16siihhhhhhQiiiiBB19sBH
```

This is consistent with the independent references in all high-value areas:

- sequence/state + 16-byte serial;
- drone longitude / latitude;
- two 16-bit vertical fields;
- three 16-bit velocity-like fields;
- one 16-bit angle-like field in v2;
- 64-bit phone/app GPS time;
- app latitude / longitude;
- home longitude / latitude;
- product type;
- UUID length;
- 19 UUID bytes plus one terminating/padding byte;
- trailing CRC-16.

RUB-SysSec parses the final UUID area as a 20-byte string, while `samples2djidroneid` and proto17's transmitter code separate a 19-byte UUID from one zero byte. The current toolkit's `19s + B` representation is therefore a useful semantic refinement without changing the 20-byte wire area.

### Altitude / height order

There is a source conflict if only synthetic/reference code is considered:

- Department 13's reverse-engineered `Flight_Reg_Info` structure and RUB-SysSec place **altitude before height**.
- proto17's synthetic `create_frame_bytes.m` labels its emitted order **height before altitude**.

The real IQ capture resolves the conflict. In RUB-SysSec's `mavic_air_2` frame, the two fields contain 141 and 42. The published flight height is 12.8 m, and `42 / 3.28084 = 12.80 m`. The current parser's **altitude first, height second, both whole feet** therefore matches ground truth. Do not swap these fields to match proto17's transmitter helper.

### Coordinates

The wire value is consistent with radians x 10^7, which is equivalent to dividing degree values by approximately 174532.925. RUB-SysSec uses rounded 174533.0. The toolkit deliberately uses the exact `1e7*pi/180` scale; `real-captures.md` records the resulting ~2.46 m difference from the rounded reference at Bochum latitude.

Only an all-zero coordinate **pair** is treated as missing. A single zero component can be a valid location on the equator or Greenwich meridian.

### Velocity fields

Do **not** change these from the current raw-to-float behavior yet.

Primary/older sources (Department 13, Kismet, RUB-SysSec) expose signed 16-bit `v_north`, `v_east`, `v_up` values directly and do not establish a scale factor. A newer secondary implementation describes them as cm/s, but that conflicts with plausible real values in the published Mavic/Mini captures and is not enough evidence for a parser migration.

The current API names them `v_north_m_s`, `v_east_m_s`, `v_up_m_s`. That unit suffix is stronger than the available primary evidence. Follow-up should compare consecutive CRC-valid real frames against GPS displacement/time to determine the scale empirically before changing either the values or API names.

### Angle field

RUB-SysSec labels the v2 field `d_1_angle` and publishes raw values such as -14958. Interpreting `/100` as degrees gives -149.58 degrees, a plausible yaw-like angle. Older Kismet/Department 13 v1 code expresses its angle conversion in radians. Treat `yaw_deg` as supported but still worth checking against a flight where heading is independently known.

## H7 — soft/turbo sensitivity claim

**Status: decoder implementation validated; range claim NOT validated.**

The LTE turbo implementation is real and useful. Tests cover:

- LTE QPP interleaver entries;
- encoder/decoder round trips;
- rate matching / de-rate matching;
- correction of heavily corrupted synthetic code blocks;
- CRC-aided early exit;
- full synthetic RF-chain decoding at 6 dB where the old hard-decision chain used to fail.

What those tests do **not** establish is a measured 10 dB field sensitivity improvement or a threefold real-world range increase.

`tests/test_turbo.py` uses a synthetic antipodal AWGN channel. `tests/test_droneid.py` contains synthetic RF loopbacks. `real-captures.md` proves that the receiver decodes real RUB-SysSec IQ and contains an added-noise BER study for channel-estimation choices, but it does not present a controlled hard-vs-soft real-capture packet success curve that establishes a 10 dB receiver threshold shift.

Therefore the sentence currently in `droneid/receiver.py` — "worth a measured 10 dB over hard decisions - a factor of three in range" — is an **overclaim**. The correct statement is closer to:

> Soft LTE turbo decoding materially improves synthetic low-SNR decoding and is enabled by default. Field sensitivity/range gain has not yet been measured on controlled over-the-air captures.

Even if a future controlled test established 10 dB of receiver-threshold improvement, converting it to a distance multiplier requires a propagation/link-budget model; it is not itself a measured range result.

## H10 — CRC failure must not identify O4

**Status: confirmed and fixed in the user-facing CLI on this branch.**

Before this audit, `antsdr-tk droneid` told the user that a failed CRC was either a weak signal or an encrypted OcuSync 4 payload. It also wrote `frame.to_dict()` to JSON even when both CRCs failed, which could put garbage serial numbers and coordinates into the same field used for trusted telemetry.

That is unsafe for an AERIX server feed.

A 2026 proto17 issue about an O4+ Avata-family signal is useful RF evidence: a 9 MHz / 15.36 MSPS / 1024-FFT OFDM signal was observed with Zadoff-Chu root indices changing between frames. It does **not** prove that every detected-but-CRC-failed burst is O4, nor does it establish payload encryption as the cause of a particular failure.

The CLI now uses three evidence states:

- `decoded`: frame exists and **CRC-24 + CRC-16 both pass**;
- `decode_failed`: a frame-shaped parse exists but one or both CRCs fail;
- `geometry_failed`: the burst was detected but frame geometry did not resolve.

Only `decoded` records populate JSON `frame`. Failed attempts keep detection metadata and CRC flags, but their untrusted coordinates/serial/model fields are not published as telemetry. Console output says `generation/cause unknown`, not O4.

This does not prevent future O3/O4 classification. It forces that classification to come from independent RF evidence (burst geometry, root behavior, bandwidth/numerology, validated generation-specific signatures), not from the fact that an O2 decoder failed.

## Code changed in this audit

- `antsdr_toolkit/cli_droneid.py`
  - clarified proprietary DJI vs standards-based ODID scope;
  - removed stale "receiver without error correction" wording;
  - removed CRC-fail -> O4/encryption inference;
  - added explicit decode evidence state;
  - only exposes a telemetry frame when both CRCs pass.
- `tests/test_cli_droneid.py`
  - CRC-valid frame contract;
  - CRC-failed parse cannot leak telemetry;
  - failure output contains no O4/encryption claim;
  - geometry failure is distinct from CRC failure.

## Tests to run before merge

The environment used for this review cannot execute a full repository checkout, and the repo currently has no GitHub Actions workflow. Run at least:

```bash
cd antsdr/toolkit
python -m pytest \
  tests/test_cli_droneid.py \
  tests/test_droneid.py \
  tests/test_turbo.py \
  tests/test_droneid_offsets.py -q
```

Then:

```bash
python -m pytest -q
```

## Next experiment that would actually improve AERIX

Use a controlled real DJI flight/capture where receiver location is fixed and record, for every CRC-valid frame:

1. RF centre/channel, SNR estimate and detection score;
2. sequence number and GPS time;
3. aircraft GPS, app/controller GPS and home GPS;
4. raw `v_north/east/up` and angle fields;
5. ground-truth aircraft/controller position from a second source if available.

That single experiment can answer three open questions with real evidence:

- actual velocity scaling;
- yaw/angle semantics;
- packet decode probability versus received signal level/SNR.

It also gives the first defensible path from decoder performance to **estimated detection/telemetry range**, instead of turning synthetic dB improvements directly into range claims.
