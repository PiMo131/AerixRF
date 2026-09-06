# Phase 2: verdicts on the peer-review hypotheses

One record per hypothesis from `../../VALIDATION_PLAN.md`. The plan's rule is
that these are hypotheses to test, not conclusions to satisfy, so a finding is
recorded whether it survives or not, and the evidence on both sides is kept.

Verdicts: **CONFIRMED**, **PARTLY**, **REJECTED**, **UNRESOLVED**.

| ID | Subject | Verdict | Change made |
|---|---|---|---|
| H1 | DroneID frame layout and field semantics | in progress | |
| H2 | Coordinate validation | **CONFIRMED**, and worse than claimed | fixed in two modules, plus a shared scale constant |
| H3 | Snapshot capture and SigMF time semantics | in progress | |
| H4 | Retune settling and double discard | in progress | |
| H5 | Live sweep default rate versus firmware | in progress | |
| H6 | Classifier integration from the sweep CLI | in progress | |
| H7 | DroneID FEC and turbo capability claims | in progress | |
| H8 | Synthetic tests versus real compatibility | in progress | |
| H9 | AERIX observation and event contract | in progress | |
| H10 | CRC failure and OcuSync 4 inference | in progress | |
| H11 | CI and reproducibility | **CONFIRMED** | none yet; recorded as a gap |
| H12 | Documentation contradictions | in progress | |
| H13 | New work added after the previous review | in progress | |

---

## H2 — Coordinate validation

**Reviewer claim.** Latitude and longitude may not be validated against their
own physical ranges.

**Verdict: CONFIRMED**, in two separate modules, and the audit turned up a
third defect in the same area that the hypothesis did not predict.

### What was found

**1. One range used for two different coordinates.**

`droneid/receiver.py` validated every coordinate with:

```python
return deg if -90.0 <= abs(deg) <= 180.0 else None
```

and `remoteid/odid.py`, written later in the same session, independently made
a similar mistake:

```python
if value == 0 or not -90.0 <= degrees <= 180.0:
```

Latitude runs to ±90 and longitude to ±180. One range cannot be right about
both: it accepts a latitude of 150 degrees, which does not exist, and the
Remote ID version rejects a longitude of -150 degrees, which is the middle of
the Pacific. The DroneID version additionally takes `abs(deg)` before
comparing against a lower bound of -90, so the lower half of the test is
vacuous: `-90.0 <= abs(deg)` is true for every real number.

Primary source for the correct limits: `opendroneid/opendroneid-core-c`,
`libopendroneid/opendroneid.h`, which states them separately as `MIN_LAT`
-90, `MAX_LAT` 90, `MIN_LON` -180, `MAX_LON` 180. For DroneID no reference is
needed; the limits are geodesy.

**2. "No fix" was decided per coordinate rather than per pair.**

Both modules returned `None` for any coordinate that was exactly zero. The
zeros are indeed how an absent fix is signalled, but implementations send
*both* as zero. Rejecting each on its own discards a real position anywhere on
the equator or the Greenwich meridian, and there is airspace over both. The
pair is now rejected only when both halves are zero, and a valid latitude
beside an impossible longitude is dropped as a pair, because half a position
is not a position.

**3. The encoder and decoder used different scale constants.** Not predicted
by the hypothesis, and found by the four-pass check on units at module
boundaries.

DJI encodes coordinates as radians scaled by 1e7, so degrees multiply by
`1e7 * pi / 180` = 174532.925199. The receiver used `174533.0`; the burst
synthesiser used `1e7 / 57.2957795785523` = 174532.925. The difference is 4.3
parts in ten million, which is about **2.5 m of position at Dutch latitudes**.

The round-trip test did not catch it because its tolerance was wider than the
error, which is exactly the failure mode H8 is about: a synthetic generator
and the parser under test are not independent evidence. There is now one
`constants.COORD_SCALE`, defined exactly, used by both.

### Changes made

- `remoteid/odid.py`: `LATITUDE_RANGE` and `LONGITUDE_RANGE` declared
  separately; `_position()` validates the pair.
- `droneid/receiver.py`: `_pair()` replaces `_deg()`, with the same semantics.
- `droneid/constants.py`: `COORD_SCALE` added, exact, shared by the receiver
  and the synthesiser.

### Tests added

Boundary cases at ±90 and ±180; the equator and the Greenwich meridian
asserted to be *places* rather than missing fixes; the 150-degree case
asserted in both directions, so a future shared-range regression fails; and a
test that the two scale constants are the same object, with the size of the
old disagreement recorded in it.

### Question raised

None. The physical ranges are not a judgement call.

---

## H11 — CI and reproducibility

**Verdict: CONFIRMED.** No `.github/workflows` exists at the repository root
or under `antsdr/`. Every test count in this project, including the 457 in
`baseline.md`, comes from a manual run on one machine against one set of
dependency versions. Nothing re-checks a push, and nothing exercises the
minimum dependency versions `pyproject.toml` claims to support. No coverage
measurement exists either, so the test count says nothing about which lines
are reached.

Recorded rather than fixed, because adding CI to this repository is a change
to the repository's own configuration rather than to the toolkit, and belongs
to the maintainer. See `baseline.md`.
