---
name: canonical-representation
description: Canonical live/ML representation decided 2026-09-18 (15.36 MS/s, cs16 on ANTSDR, 12 MHz usable band) and the non-obvious reasoning behind it
metadata:
  type: project
---

Workstream A3 decision memo lives at `docs/design/canonical-representation.md` (200 lines, decision table
up top). Headline: canonical rate **15.36 MS/s** for both receivers; ANTSDR session storage **cs16**
(challenging the hardware-architect's cs8-for-both default in `docs/design/antsdr-backend.md` §6.5);
declared **usable band 12.0 MHz**; STFT FFT 1024 / Hann / hop 512.

**Why:** the reasoning that is easy to lose and hard to re-derive —
- 15.36e6 / 512 = 30 000 STFT frames/s *exactly*, so 30 frames = 1.000 ms and 6 = 200 µs. Canonical tensor
  shapes are exact only at this rate. Bin grid 15.0 kHz also equals the DroneID/LTE carrier spacing.
- Width loss vs 20 MS/s is 19 % → 25 % of the ISM band. FHSS observation is a dwell-scheduling problem,
  not a window-width problem, so the wide-slice argument for 20 MS/s does not survive contact.
- At 15.36 MS/s a 2437 MHz tune clips ~half of a DroneID burst centred at 2429.5 MHz. Dwells must tune on
  the *emitter* raster. Bonus: DroneID's DC subcarrier is unused, so LO leak lands on a null carrier.
- `classify/train/features.py` uses a *fraction-of-band* frequency axis — that, not the sample rate itself,
  is why the DroneRF (40 MS/s) bundle is invalid at 20 MS/s. Fix = absolute Hz axis over the usable band.
- Comparing decode SNR across sample rates must fix SNR in the 9 MHz occupied band, else the 20 MS/s arm
  eats a spurious 1.14 dB penalty and "proves" whatever you wanted.
- Fallback ladder under a hard Ethernet ceiling is 15.36 → **11.52 MS/s** (fft 768, CP 60/54 integer).
  Never 7.68: DroneID occupies 9 MHz.
- **2026-09-18 revision:** 15.36 MS/s loses samples *silently* on the ANTSDR-IIO path (ratio 0.94–0.98,
  no error counter). ANTSDR-IIO **live capture rate = 12.288 MS/s** (4/5 of canonical, exact 5/4
  polyphase back to canonical, 24 000 STFT frames/s at hop 512 = exactly 24/ms), `rf_bandwidth` 10.0 MHz,
  declared `usable_bw_hz` 10.0 MHz. 13.44 also sustains (53.8 MB/s) but sits at ~0.9 of the ~57–60 MB/s
  ceiling with no overflow counter. 15.36 stays the canonical *representation* rate for storage/ML.
  Decode sensitivity does not drive this choice — see [[decode-snr-bench]].

**How to apply:** treat the memo as the reference for any rate/format/spectrogram question; re-check the
`[MEASURE]` items (GbE ceiling, `iq_full_scale` = 2048?, hop-512 window timing) before relying on them —
they were unmeasured on 2026-09-18. Related: [[evidence-levels-practice]].
