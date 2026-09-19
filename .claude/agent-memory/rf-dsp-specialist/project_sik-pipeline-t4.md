---
name: sik-pipeline-t4
description: SiK T4 dwell pipeline - the wideband-capture AWGN fixture trap, the -6 dB centre bias on bimodal 2-FSK, single-look STFT gating, and per-burst DDC cost
metadata:
  type: project
---

Durable findings from making `aerix_rf/decode/sik/pipeline.py` (T4, one sub-GHz
dwell -> bursts -> GFSK -> frames -> raster/NETID -> MAVLink) actually work.
Related: [[sik-gfsk-t1]], [[stage1-link-signatures]].

**1. Embedding `make_sik_burst(snr_db=...)` in a wideband capture is a trap.**
The generator adds AWGN over the *whole* `fs` of its own buffer, sized for a
`2*rate_bps` reference bandwidth. At 15.36 MS/s and 64 kbps that is
`fs/(2*rate) = 21 dB` more total noise power than the in-band figure, so each
embedded burst raised the entire 15.36 MHz dwell floor by ~24 dB for its own
duration. With a 54 % burst duty cycle the per-bin *median* floor then became
the burst-time floor, the detector saw band-wide "signal" at every hop, hit its
64-event cap on splatter, and only 7 of 40 bursts were ever reached.
**Why:** one narrowband transmitter does not raise a whole band's floor - it is
a fixture artefact, not receiver physics.
**How to apply:** when a synthetic burst is embedded in a wider capture, always
generate it noiseless and add one stationary dwell-wide AWGN process sized from
the target in-band SNR. Suspect this first whenever a detector "floods" only
during signal-present frames.

**2. `detect_bursts`' -6 dB edge-midpoint centre is biased on wide-deviation 2-FSK.**
A SiK burst at h~2 has a bimodal spectrum (tones at +/-h*rate/2). The stronger
tone wins the peak search and the -6 dB walk terminates in the inter-tone dip,
so the reported centre collapses onto one tone: measured **-54 kHz +/- 2 kHz**
systematic at 64 kbps (0.2 of the 250 kHz channel spacing). An iterated
noise-subtracted power centroid over the burst's own samples reduces this to
~-24 kHz.
**Why:** the -6 dB midpoint is the right estimator for a single-lobe burst only.
**How to apply:** never feed raw `event.centre_hz` to anything that needs true
carrier frequency for an FSK/FHSS emitter. Note the Rayleigh lattice test
absorbs a *constant* centre bias into its offset term, so spacing/N recovery
survives it - but the reported `offset_hz` does not, and a data-dependent bias
would break the lattice.

**3. Single-look periodograms must not inherit `detect_bursts`' dB gates.**
GATE_DB/HYST_DB (6/3 dB) are calibrated for D8's factor-6 block-averaged
frames. On a single-look FFT the arm false-alarm rate is ~1.9 %/pixel. Raising
the gates to 13/9 dB to compensate throws away burst margin and still leaked
false events. Correct fix: average 6 FFT frames into one detector frame (same
Erlang-6 statistics as D8) and gate 9/6 dB -> ~2e-14 arm false-alarm per pixel,
0 events on a 0.2 s noise-only capture, ~15 dB margin on a 20 dB-SNR burst.

**4. Per-burst cost.** Bandpass-decimation DDC (mixing folded into the
anti-alias taps, one residual exponential at the decimated rate) to a 2 MHz
channel, plus `scipy.fft` on complex64 (numpy always promotes to complex128 and
doubles FFT cost), took the 40-burst 0.32 s window from 0.94 s to 0.25 s.

**5. Air-rate hypothesis retry.** `estimate_rate`'s OBW match put 1 burst in 40
(20 dB in-band SNR) one legal step off (96 instead of 64 kbps) -> no sync. The
pipeline retries the estimated rate's two legal neighbours; a CRC-valid frame at
a neighbouring rate is self-validating, and 40/40 then decode.
