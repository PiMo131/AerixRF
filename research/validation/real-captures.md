# Phase 5: real DJI captures

`VALIDATION_PLAN.md` Phase 5, "Real DJI DroneID golden validation first". This
is the run that decided which of the toolkit's beliefs about DroneID were
true. Four were not, and none of them could have been caught by any amount of
work on synthetic bursts.

## The captures

[RUB-SysSec/DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity), the
NDSS 2023 reference receiver, ships two recordings with published decodes.
They are IQ, so they are not in this repository; the manifest is
[`datasets/rub-syssec.md`](datasets/rub-syssec.md).

| File | Bytes | Samples | Duration | Rate | SHA-256 |
|---|---|---|---|---|---|
| `samples/mini2_sm` | 5 820 000 | 727 500 | 14.55 ms | 50 MSPS | `5a17913cb11cde2919347054700345c9e5595eaff7818980d332b8ac8910bc55` |
| `samples/mavic_air_2` | 1 802 240 | 225 280 | 4.51 ms | 50 MSPS | `623fa40f190d3fd859ec2fd62b379ad9a01a0485db3179ae29ac2e3c7a070450` |

Format is interleaved little-endian float32. Published results, from the
project's own README:

- `mini2_sm`: 10 candidates, 9 decoded, **7 CRC OK**. No drone position (no GPS
  lock). Operator at 51.447176178716916, 7.266528392911369.
- `mavic_air_2`: 1 decoded, 1 CRC OK. Drone at 51.44633393111904,
  7.26721594197086, height 12.8 m. Operator at 51.44620788045814,
  7.267101350460944.

The reference was run first, unmodified apart from two compatibility shims
(`np.complex` is gone in numpy 2, and its `bitarray`/`crcmod` dependencies were
installed), and reproduced its published numbers exactly. That is the baseline
everything below is measured against.

## Result

| | reference | this toolkit, before | this toolkit, after |
|---|---|---|---|
| `mini2_sm` bursts found | 10 | 10 | 10 |
| `mini2_sm` decoded, both CRCs | 7 | **0** | **10** |
| `mavic_air_2` frames decoded | 1 | 0 | 2 |

End to end from the 50 MSPS files, through `antsdr-tk droneid`, with all three
detection gates (`zc`, `cp`, `both`) agreeing.

The two `mavic_air_2` frames are sequence numbers 589 and 591 on two different
hop channels, 14.5 MHz apart, with heights of 11.28 m and 12.80 m: one
aircraft descending, seen twice. The reference's band search returns a single
band and sees one of them.

## What was wrong

### 1. A timing error read as a frequency, twice

Detection was never the problem. Ten bursts, the reference's exact count,
start times within two samples of the reference's, cyclic-prefix confidence
above 0.98, root 600 confirmed. Every payload destroyed.

The reported offset was −50 788 Hz where the reference measured −5 792 Hz.
The difference is 45 000 Hz on all ten bursts, which is exactly three
subcarriers: an integer subcarrier offset rotates every carrier onto its
neighbour, which leaves detection untouched and makes the payload noise.

The cyclic prefixes give the offset exactly but wrap every 15 kHz, so
something has to supply the whole number of subcarriers. Both gates got that
number from a Zadoff-Chu correlation, and both were wrong in the same way:

- `find_bursts_cp` de-rotated by each candidate wrap and kept whichever scored
  best against a known root. **A chirp under a frequency offset keeps almost
  all of its correlation and slides in time.** That is the property that makes
  Zadoff-Chu a good detector - it is why the burst is found at all through a
  megahertz of offset - and it is precisely what disqualifies it from telling
  one wrap from another. The wrap it selected was the one whose slide
  cancelled the receiver's own three-sample alignment error.
- `find_bursts` measured that slide directly, via `estimate_cfo`. One sample
  of slide is 8.8 kHz at 15.36 MSPS, so timing error and frequency offset are
  confounded one for one. Its docstring already noted the sensitivity and drew
  the wrong conclusion from it: it declined to snap to the subcarrier grid,
  when the finding is that the mechanism cannot be trusted for the integer at
  all.

The fix is to measure the two parts with two different instruments.
`resolve_cfo` takes the fraction from the prefix phase and the integer from
where the occupied band sits: a DroneID burst fills 601 of 1024 bins with hard
edges, so sliding that window across the spectrum and reading off the
brightest position answers *where the band is* rather than *what it
correlates with*. Verified to recover a deliberate offset within 200 Hz from
0 to 300 kHz.

A knock-on: with the offset finally correct, `estimate_zc_root` reported *no*
root, having reported 600 while the offset was wrong. Same cause, other
direction — the time-domain matched filter needs the timing right to about a
sample, and cyclic-prefix alignment is routinely three or four samples early.
It now matches on subcarriers instead: dividing the received pilot by a
candidate root turns a timing error into a pure tone, and one inverse
transform turns that into a peak wherever it lands. Root 600 on all ten.

### 2. The channel estimate was extrapolated

The pilots sit at symbols 3 and 5 of nine, and the equaliser interpolated
between them and extrapolated out to symbols 1 and 8 with weights of −1 and
+2. The stated reason was to track the phase ramp a residual frequency offset
leaves. There is no such ramp: the prefix estimator leaves well under a
hundred hertz, which is a couple of degrees across a 643 µs burst. What the
extrapolation actually tracked was the difference in *noise* between two
estimates, amplified.

Measured on the ten `mini2_sm` bursts with noise added, raw bit error rate
before FEC, 20 trials each:

| in-band SNR | extrapolate | hold endpoints | average |
|---|---|---|---|
| 30 dB | 0.00055 | 0.00001 | 0.00000 |
| 24 dB | 0.00064 | 0.00002 | 0.00000 |
| 20 dB | 0.00079 | 0.00002 | 0.00001 |
| 17 dB | 0.00121 | 0.00004 | 0.00001 |
| 14 dB | 0.00426 | 0.00008 | 0.00002 |
| 11 dB | 0.01943 | 0.00064 | 0.00017 |
| 8 dB | 0.06096 | 0.00802 | 0.00335 |

The extrapolation has an **error floor**: 5.5 × 10⁻⁴ at 30 dB, where there is
no noise left to blame. It cost one of the ten frames. Averaging the two pilot
estimates is best everywhere, by two to four times over holding the endpoints.

This assumes the frequency offset has already been removed, which
`decode_burst` does by default; `correct_cfo=False` on a burst genuinely off
frequency now averages over a rotation, and the docstring says so.

### 3. Altitude and height, swapped and in feet

The frame carries altitude at bytes 31–32 and height at 33–34, both in whole
feet. This toolkit had the order reversed and reported the raw integer as
metres, so a Mavic Air 2 at 12.8 m printed as 141 m.

The `mavic_air_2` frame holds 141 and 42 in those two fields. RUB-SysSec
publish 12.8 m for that flight, and 42 / 3.28084 = 12.80. The other reading
puts the aircraft at 43 m.

The unit is not in any specification this project could find; it is inferred
from a number that can be checked, and any other scaling makes one of the two
fields absurd. `constants.FEET_PER_METRE` carries that reasoning.

The synthesiser had the same error in the same direction, so the round trip
passed. `tests/test_droneid_offsets.py` now pins both fields by byte offset.

### 4. There was no way to read a real capture at all

The receiver wants a burst centred at zero at a multiple of 15 kHz with a
power-of-two FFT. Both captures are 50 MSPS with the burst 9.6 and −12.5 MHz
off centre. Nothing in the toolkit could get from one to the other; the first
run of this phase was done with a hand-written mixer and resampler in a
scratch directory, which is not a capability.

`droneid/tune.py` is that step, and `antsdr-tk droneid` engages it by itself
when the recording's rate cannot work — which is what finally makes 20 MSPS
usable, the rate the E200's host link prefers and the receiver cannot take.

## Where this toolkit deliberately differs from the reference

**Coordinates, by 2.46 m.** Every decoded position differs from the published
one by 2.464 m, identically, on both captures. The whole difference is the
scale constant: the reference divides by 174533.0, with the comment "i don't
know why -> found this in: White Paper: Anatomy of DJI's Drone ID
Implementation". The encoding is radians × 10⁷, so the exact divisor is
10⁷ × π/180 = 174532.9252, which is what `constants.COORD_SCALE` uses. The
ratio 174533 / 174532.9252 is 1 + 4.286 × 10⁻⁷, and 4.286 × 10⁻⁷ of the
distance from the equator to Bochum is 2.46 m — the discrepancy exactly.

This is well inside GPS error either way, and it is recorded rather than
matched: the reference's number is a rounding of the toolkit's, not the other
way round. If a future capture ever shows the encoding is not radians × 10⁷,
this is the paragraph to revisit.

## A fifth defect, in the analysis rather than the code

After the four above were fixed, the same captures were used to ask a different
question: what is the *second* emission in `mini2_sm`, the one the toolkit
detects and cannot decode? Two claims came out of that, and one of them was
wrong in exactly the way this document is about.

**The wrong one.** Burst start times in `mini2_sm` are spaced 14 837 to 14 980
samples apart at 15.36 MSPS, and every larger gap is a whole multiple of that
to within 1.3 %: 1, 1, 3, 4, 1, 1, 1, 1, 1 slots. That is a clean, regular
grid of 970 us, and it looked like a real and useful finding - a detector that
knows the grid can predict where the next burst will be.

It is the recorder's chunk size. `mini2_sm` is 727 500 samples, exactly 15 x
48 500, and 48 500 samples at 50 MSPS is 970.0 us. Every burst starts between
8002 and 8333 samples into its own chunk, a spread of 6.6 us in a 970 us
window. The file is triggered extractions concatenated, and the "grid" is the
trigger, not the drone.

What caught it was an inconsistency that had nothing to do with timing: the ten
frames carry four distinct `gps_time` values spanning 19 990 ms, in a file
14.55 ms long. Twenty seconds of aircraft time cannot fit in fifteen
milliseconds of samples. The reference implementation parses that field the
same way and gets the same values, so it was not a decode error, and once the
file could not be contiguous the grid had an obvious other owner.

This is the same error as the frequency offset, one level up: a periodicity was
measured correctly and attributed to the wrong system. There it was timing read
as frequency; here it was the capture apparatus read as the transmitter.

**The one that survived, on better evidence.** The second emission is a
genuinely separate transmission rather than the DroneID burst's spectral
splatter. The first argument for that was a time-overlap test - only 7.1 % of
its activity coincided with a DroneID burst - which, given the above, was
measuring the extractor's trigger and was worthless. The chunk structure
settles it properly: chunks 0, 1, 2, 5 and 9-14 hold the DroneID band at +27 dB
with the second band at -1.5 dB; chunks 3, 4, 6, 7 and 8 hold the second band
at +18.5 dB with the DroneID band at -3.6 dB. Perfect anti-correlation. The
recorder triggered on two different signals and gave each its own chunks.

Its numerology is **not** established, and the negative control is why. A
cyclic-prefix lag sweep says 15 kHz subcarrier spacing - but the same sweep
says 15 kHz for a band of the same capture that is empty, at 4.66x lift against
the emission's 5.09x. A method that gives nearly the same answer for a real
signal and for nothing has not measured anything. The positive control (the
DroneID band, truth 15 kHz) scores 7.50x, so the method works; it simply has no
resolving power on a signal this weak over a record this short.

Recorded here rather than quietly dropped, because the near-miss is the useful
part: the grid was measured, believed, and written up before the timestamps
contradicted it.

## The blind spot, stated plainly

Every one of the four defects above survived a 554-test suite, and they
survived it for one reason. A synthetic burst starts exactly where the
synthesiser put it, at exactly zero frequency offset, and is read back by the
code that wrote it. Such a capture cannot exhibit a timing error, so it cannot
expose an estimator that confuses timing with frequency; and it cannot expose
two fields swapped, or a unit dropped, as long as both ends agree.

The back end was never at fault, and that was worth establishing separately:
handed the reference's own demodulated symbols, this toolkit's slicer,
descrambler and de-rate-matcher reproduce the reference's payloads byte for
byte on all seven frames it decodes, and fail identically on the two it does
not. In particular the reference's magic `offset = 4148` into a doubled buffer
and this toolkit's `_k0`-derived start are the same position arrived at two
ways — checked, rather than assumed, before anything was changed.

The lesson for the rest of the toolkit: the analog video decoder, the
classifier and the sweep planner have all been validated the same way the
DroneID receiver was, and are owed the same scepticism until real signals have
been through them.

## Reproducing

The scripts are in the session scratchpad rather than the repository, since
they depend on a checkout of the reference and on IQ that is not in git. The
sequence is:

1. `git clone https://github.com/RUB-SysSec/DroneSecurity` and check the two
   sample files against the hashes above.
2. Run the reference's `droneid_receiver_offline.py` to confirm 7 of 10.
3. Wrap either sample as SigMF (`cf32_le`, `core:sample_rate` 50e6) and run
   `antsdr-tk droneid <stem> --quiet`.
