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
| H6 | Classifier integration from the sweep CLI | **CONFIRMED**, and the design question answered against the placeholder | sweep now classifies per emitter; "unknown" no longer travels as a family name |
| H7 | DroneID FEC and turbo capability claims | in progress | |
| H8 | Synthetic tests versus real compatibility | in progress | |
| H9 | AERIX observation and event contract | in progress | |
| H10 | CRC failure and OcuSync 4 inference | in progress | |
| H11 | CI and reproducibility | **CONFIRMED** | none yet; recorded as a gap |
| H12 | Documentation contradictions | **CONFIRMED**, both named cases | README and three research documents corrected |
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

---

## H12 — Documentation contradictions

**Verdict: CONFIRMED**, on both of the cases the plan named, and the second
one caught this audit making the opposite error.

### 1. openwifi as a Remote ID identity path

The top-level `README.md` said DJI's EU Remote ID "goes out over Wi-Fi Beacon,
so AERIX's existing receivers, or openwifi on the E200, are the identity path
for O4 drones". Two things wrong with one sentence.

openwifi cannot receive it: it is OFDM-only and cannot demodulate the 802.11b
rates that 2.4 GHz Remote ID beacons use *(verified: verdict 6,
`openwifi-personality`)*, which `regulatory.md` already stated. The E200 is
the wrong radio and a commodity monitor-mode adapter is the right one.

And it is not the identity path for O4 drones as a class. The obligation
attaches to the class label: C0 aircraft under 250 g broadcast nothing
*(verified: verdict 7, `dji-eu-rid`)*. An encrypted O4 airframe under 250 g,
which is a common configuration, has no identity available by any published
means. Corrected in `README.md`.

### 2. The analog sample rate, where this audit over-corrected first

The plan asked that older "10 MSPS" analog claims not survive unnoticed after
the decoder work found that low-rate captures can appear to lock while
producing a wrong image. Correct as far as it goes, and the first pass of this
audit duly rewrote three documents to say 12.75 MSPS is a hard floor.

That was an overreach, and re-reading `landscape.md` caught it. The two claims
are about different things:

* **verdict 5, about a real transmitter:** a 25 mW whoop VTX captured with a
  HackRF at 10 MSPS gave a usable NTSC colour picture, with under 0.3 % of its
  energy outside +/-4.5 MHz. That is a measurement, and it stands.
* **this project's decoder, about its own signal model:** the toolkit's
  demodulator scaling puts peak white at +6.4 MHz, so a signal generated at
  that depth aliases below 12.75 MSPS.

Those do not contradict each other. They say the real VTX swung less than the
model does, which `landscape.md` had already noticed from a different
direction: "a true +/-5 MHz swing would park roughly 7 % of line time outside
+/-4.5 MHz, so the tested VTX must have swung less". The RTC6705 datasheet
specifies no video deviation at all, so what a given transmitter swings is
unestablished until measured.

Replacing a measurement of real hardware with a measurement of our own
synthetic signal would have been the H8 error in reverse. Both are now stated
with their scope attached, in the code and in the documents, and the
recommendation that survives either reading is 20 MSPS: it clears the model,
it clears a +/-5 MHz real swing, and it is the only rate at which the audio
subcarriers and PAL chroma are inside Nyquist at all.

### Changes made

`README.md` (both items), `research/README.md`, `research/sources.md`, and the
scope wording in `analog/video_decode.py` and `cli_video.py`. `landscape.md`
was left alone: it was right.

---

## H6 — Classifier integration from the sweep CLI

**Reviewer claim.** `cli_sweep` may look up a function that
`antsdr_toolkit.classify` does not export.

**Verdict: CONFIRMED.** `cli_sweep.py` called

```python
getattr(importlib.import_module("antsdr_toolkit.classify"), "classify_dwell", None)
```

and `classify/__init__.py` exports `classify`, `classify_clusters`, `margin`,
`membership`, `SIGNATURES`, `Signature`, `by_family`, `families` and
`signatures_for_band`. It has never exported `classify_dwell`. The lookup
returned `None` on every run and the families column was always `-`.

No test caught it because every sweep test supplied its own `classifier`
override, so the real import path was never exercised. That is the shape of
the problem rather than an accident: a hook that only tests reach is a hook
that is not integrated.

### The design question, which matters more than the missing symbol

The plan asked whether classification belongs at dwell level or emitter level,
and told this audit not to preserve the flat interface merely to keep a
placeholder working. The answer is emitter level, and the evidence is in the
toolkit's own end-to-end demo: a single 15.36 MHz dwell there contains three
distinct emitters, and the earlier analog and DroneID work showed the same
thing in every realistic scene. In the 2.4 GHz band a dwell routinely holds
Wi-Fi, a control link and a video downlink at once.

`classify_dwell(result) -> [(family, confidence), ...]` cannot express that. A
flat list per dwell mixes the burst statistics of unrelated transmitters, and
the result is a confident average of nothing. So the interface was replaced
rather than repaired: `_families` now clusters bursts by centre frequency and
bandwidth and scores each cluster on its own timing and shape, returning the
best candidate **per emitter**. More than one entry now means more than one
transmitter, not more than one guess about the same signal.

`classifier` survives as the override, which is how a trained model gets
dropped in later (`ADR-0007`).

### A second defect, found by turning the hook on

With the hook finally firing, an existing test failed because it asserted
`family is None` in every emitted event. That assertion had been encoding the
bug. Fixing the test would have been the wrong move: the new value was the
string `"unknown"`, which is the scorer's pseudo-family for "nothing cleared
the threshold", and `scan/events.py` documents `family` as `None` when
unclassified. Letting the string travel would have contradicted the event
schema's own contract, and a downstream consumer reading `"unknown"` would
take it for a claim about the waveform.

`_families` now drops the `unknown` candidate. The burst is still emitted; only
the label is withheld, which is the difference between "we saw something we
cannot name" and "we saw an unknown".

### Tests added

Five, none using the override: the hook produces names through the real import
path; two separated emitters produce two clusters and are never collapsed into
one averaged claim; noise produces nothing; an explicit `classifier` still
overrides; and the band hint matches the dwell centre.

### Question raised

None.

---

## Additional findings, not from the hypothesis list

The fleet and host-platform audit that ran alongside this one produced two
defects in the same code, and they are recorded here because they came out of
the same discipline even though the plan did not predict them.

### The detector could not see any of the maintainer's aircraft

`find_bursts` gates on a matched filter for Zadoff-Chu root 600, which is the
OcuSync 2 pilot. OcuSync 3 is reported to use a different pair, and an
OcuSync 4 variant to vary its roots frame to frame (proto17 issue 65). Every
airframe in the maintainer's fleet is O3 or O4, so the gate was plausibly
blind to all of them, and it fails in the worst possible way: no detection is
indistinguishable from no drone.

`find_bursts_cp` gates on structure instead. Every OFDM symbol repeats its own
tail one FFT length earlier, so correlating the two peaks wherever this
numerology is present whatever the symbols carry. The roots become generation
*labels*, and the measured root is recorded per burst, which turns every
future capture of a real aircraft into a data point on roots nobody has
published.

Three bugs surfaced while building it, all found by measuring:

1. **A fixed stride where the schedule is not uniform.** The back-search
   stepped 1104 samples per symbol, but the prefixes run 80, then seven of 72,
   then 80. That accumulates 8 samples per symbol and lands 2192 samples out,
   which is exactly the gap between the two pilots, so the second was read as
   the first and the root came back 147 instead of 600. It looked like a
   successful decode.
2. **A sign error in the prefix frequency estimator.** `numpy.vdot` conjugates
   its *first* argument, so the recovered offset is positive. The error is
   invisible whenever the true offset is near a multiple of the 15 kHz
   subcarrier spacing, which is where a test written to be convenient would
   look; it only appeared because 5 and 9 kHz behaved differently from 30 and
   120.
3. **A root claimed on a coin toss.** Different roots cross-correlate at about
   `1 / sqrt(601)` = 0.04, so a real match wins twentyfold. Two scores within a
   thousandth of each other mean neither matched, and the honest answer is
   none.

### The product-type table stops at "Mini SE"

`PRODUCT_TYPES` ends at 70. Every DJI airframe released since carries a higher
number, so a successful decode of a recent aircraft rendered `unknown (73)`,
which reads like a failed decode when in fact everything except the model name
resolved. That includes the Mini 3 Pro, which the closed E200 firmware
explicitly claims to decode in full.

The audit proposed adding 73, 75, 77, 82, 83, 86, 87, 88 and 90. **They were
not added, and a test asserts they are still absent.** No primary source
reachable from this project confirms any of them: neither reference decoder
ships a lookup table, Kismet's parser reads `product_type` and never maps it,
and the numbers in circulation trace to forum posts. A wrong model name on a
detection is a confident false identification, which is worse than a missing
one. `product_name()` describes the gap instead, distinguishing a number above
the table's ceiling from one inside it.
