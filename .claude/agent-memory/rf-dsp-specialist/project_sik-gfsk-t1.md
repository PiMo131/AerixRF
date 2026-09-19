---
name: sik-gfsk-t1
description: SiK 2-GFSK T1 demod — why 12 dB in-band SNR is easy (post-detection matched filter), the OBW98/rate calibration, and the preamble-gated 2-bit sync arithmetic.
metadata:
  type: project
---

T1 (`aerix_rf/decode/sik/gfsk.py`) meets the full design acceptance on the
synthetic model (level 1): BER <= 4.8e-5 at **12 dB** in-band SNR for all 13
air rates (>=20 880 bits each), 200/200 sync at 64 kbps with CFO +/-20 kHz and
random sub-symbol timing, exact rate ID for all 13 rates at 20 dB, 0 false
syncs, 12.6 ms for a 252-byte 64 kbps burst at 15.36 MS/s.

**Why:** an earlier implementation missed by 3-8 dB and the shortfall was
attributed to the "FM threshold effect" and blanket-xfailed. That rationale was
wrong and the arithmetic says so: synth.py references noise to a 2*R_b
bandwidth, so 12 dB in-band == Eb/N0 = 15 dB, where the noncoherent 2-FSK bound
is ~1e-7. Any BER above ~1e-5 there is implementation loss. The actual loss was
**no post-detection matched filter**: slicing one discriminator sample per
symbol keeps the whole pre-detection noise bandwidth in each decision. A
one-symbol boxcar average on the discriminator output took BER from ~2 % to 0
at 12 dB. A two-tone noncoherent correlator was prototyped and is unnecessary
once the post-detection filter exists.

**How to apply:** durable decisions worth reusing for any FSK/GFSK demod here —
1. Always state the noise-bandwidth convention before judging an SNR target; convert to Eb/N0 and compare against the noncoherent bound before accepting an xfail.
2. Post-detection (symbol-rate) matched filtering is mandatory, not optional.
3. Residual carrier: use the **midpoint of the 10th/90th percentiles of the eye**, not the mean or median of the discriminator — for a bimodal density the median swings across the sparse middle with mark/space imbalance (measured 8.6 % of deviation on 592-bit bursts).
4. Rate ID from occupied bandwidth: Carson `(2+h)*R` over-states BT=0.5 GFSK OBW98 by ~1.6x. Measured OBW98/R of the model: 2.25 (h=1.875), 2.49 (h=2.0), 2.01 (h=1.65), 1.78 (h=1.27); match in log-bandwidth against the 13 legal rates. Calibrated to the model, NOT to hardware — worst adjacent-rate margin ~15 % (128k vs 192k).
5. Sync tolerance and preamble gating are one decision: +/-2 bit errors on a 16-bit sync = 137/65536 per position per hypothesis, so a 32-bit alternating-preamble gate (<=3 errors, 2.6e-6) is what buys back the zero-false-sync requirement. A 24-bit gate measurably leaks (1 false sync per 200x2000-bit noise streams).
6. Runtime: polyphase decimation cost is linear in tap count — design the decimation filter from the transition width actually needed (>=3x the keep band here) instead of `resample_poly`'s default 10*decim+1 taps (35 ms -> 10 ms). One FFT then serves both the coarse-CFO centroid and the channel slice.

Still open: everything above is calibrated against `synth.py`, which shares the
decoder's model. Real Si4432 spectra, LO phase noise and sample-clock error are
unvalidated, and there is no timing-tracking loop (single best-phase search).
See [[decode-snr-bench]] for the analogous non-monotonic-decode trap.
