# AERIX RF — Canonical live representation & dataset preprocessing target

Status: decision memo (rf-dsp-specialist, 2026-09-18), Workstream A3. Scope: the one representation every
backend converges to, live and for ML training. `[MEASURE]` = depends on an unmeasured number;
`[SPEC]` = device-specialist confirmation.

## 1. Decision table

| # | Item | Decision | Ceiling ≥20 MS/s | Ceiling ~15 MS/s |
|---|---|---|---|---|
| D1 | Canonical sample rate | **15.36 MS/s complex, both receivers** (representation/ML rate) | same (headroom → 16-bit wire + optional 20 MS/s A/B profile) | **live capture 12.288 MS/s** (4/5 of canonical; exact 5/4 polyphase up to canonical). 15.36 loses samples *silently* on the IIO path (measured ratio 0.94–0.98, no error counter); 13.44 sustains but at ~0.9 of the measured ~57–60 MB/s ceiling. 11.52 remains the hard-floor fallback; never below (DroneID occupies 9 MHz) |
| D2 | `rf_bandwidth` | **≈0.8–0.9 × Fs**, recorded per window; must exceed the 9.0 MHz DroneID occupancy plus tuning slack | HackRF BB filter 12 MHz at 15.36 MS/s | **10.0 MHz at 12.288 MS/s** (11.0 MHz at 13.44, 10.0 MHz at 11.52). Narrower than 0.9·Fs on purpose: less out-of-band blocker energy into the ADC/AGC. Declared `usable_bw_hz` drops to **10.0 MHz** on ANTSDR-IIO — features must use the HackRF∩ANTSDR usable band, not the per-device one (D11) |
| D3 | Declared **usable** band | **12.0 MHz** (±6.0 MHz); outer bins kept but masked for band-relative features | same | same |
| D4/5 | Wire + storage format | ANTSDR wire 16-bit (`le:S12/16`); session **default `cs16`, full scale 2048**; HackRF stays `cs8` (native); never float on disk | same | same; `sc8` wire only as a flagged escape [SPEC]; event-gated retention |
| D6 | Window duration | **keep 1.000 s** | same | same |
| D7 | Canonical STFT | FFT **1024**, **Hann**, hop **512**, complex64, coherent-gain normalised | `time_decim` 1 | `time_decim` 1 |
| D8 | Detector spectrogram | linear-power block-average to **200 µs** frames → [5000 × 1024] | same | same |
| D9 | ML tensor | block-average to **1.000 ms** frames → **[1000 T × 1024 F]** float32 | same | same |
| D10 | Normalisation | store **absolute dBFS** (referenced to declared `iq_full_scale`); relative (dB-above-floor) applied **inside feature extraction**, never at storage | same | same |
| D11 | Classifier freq axis | **absolute Hz/bin over the 12 MHz usable band**, not fraction-of-band | same | same |
| D12 | Gain | **manual**, changed only between windows, recorded per window. AGC ⇒ no absolute RSSI, excluded from ML | same | same |
| D13 | HackRF live default | move new captures to **15.36 MS/s, BB filter 12 MHz** [SPEC]; 20 MS/s retained as a profile | same | same |
| D14/15 | Legacy + dataset resampling | 20 MS/s sessions **never rewritten**, canonical derived by 96/125 `resample_poly`; datasets integer-decimate to ≥ 19.2 MS/s, then one rational stage | same | same |

## 2. Why 15.36 MS/s is the canonical rate

1. It is `ofdm.NOMINAL_SAMPLE_RATE`: FFT 1024 at exactly 15 kHz/bin, CP 80/72 integer, burst 9880 samples.
   Live windows need no resampling before the highest-evidence path we own (`resampled=False`).
2. Integer STFT arithmetic falls out: 15.36e6 / 512 = **30 000 frames/s exactly** → 30 frames = 1.000 ms,
   6 = 200 µs. Canonical tensor shapes are exact, not rounded; no other candidate rate does this. The bin
   grid (15.0 kHz) also coincides with the DroneID/LTE carrier raster.
3. Ethernet: 61.4 MB/s at 16-bit — inside the plausible band in every throughput scenario considered.
4. The width we give up is not decisive. 15.36 → 20 MS/s is +30 % of an ~80 MHz ISM band (19 % → 25 %).
   FHSS RC observation is a **scan/dwell-scheduling** problem at any reachable rate, not a window-width one.
   OcuSync video at 10 MHz fits with 2.7 MHz guard; a 13 MHz mode exceeds D3's flat 12 MHz — record
   `occupied_bw_mhz ≥ usable_bw` as **saturated**, never as a measured width.

**Load-bearing consequence — tuning raster.** At 15.36 MS/s the tuned centre must sit on the *emitter's*
centre, not a Wi-Fi channel centre. The 2026-09-04 golden capture tuned 2437 MHz and found DroneID at
2429.5 MHz; a 2437 MHz tune at 15.36 MS/s covers 2429.3–2444.7 MHz and would clip roughly half of that
9 MHz burst. Live DroneID dwells must tune **on the DroneID raster** (2429.5 MHz observed; the rest of the
raster is an evidence gap, §12). Tuning on the burst centre is also optimal for LO leakage: DroneID's DC
subcarrier is unused (`ofdm.data_carrier_indices` excludes DC), so the leak lands on a null carrier.
Residual CFO (±10 ppm ≈ ±24 kHz) moves it onto ~1 of 600 carriers after correction — negligible under turbo.

## 3. Bandwidth, and why "usable" is a first-class field

AD9361 `rf_bandwidth` is a settable analog corner; HackRF's baseband filter has discrete steps
(…, 12, 14, 15, 20 MHz). A corner at Fs leaves blockers in the ADC; a corner at 0.8 Fs puts the rolloff
inside the analysed band and silently biases `occupied_bw_mhz` and the flat-top test. Decision: corner at
0.9 Fs (13.8 MHz ANTSDR; 14 MHz HackRF), **declared flat band 12.0 MHz**, which both receivers meet. `IQWindow` / `session.json` carry `bandwidth_hz` *and* `usable_bw_hz`; all
band-relative statistics (occupied bandwidth, flat-top spread, noise floor, hop spread) are computed on the
usable mask. This is what makes ANTSDR and HackRF numbers comparable at all.

## 4. Storage format — challenge to the ANTSDR backend memo (§6.5)

"cs8 default for both receivers, cs16 opt-in" is rejected for ANTSDR. Dynamic range is the *entire* reason
to prefer ANTSDR over HackRF; defaulting to cs8 discards it silently and irreversibly, and sessions are the
future training corpus. With a Wi-Fi blocker 30 dB above a drone burst and 10 dB of peak backoff, the burst
sits ~45 dBFS down — ~3 effective bits at cs8 versus ~7 at cs12. Per-carrier processing gain
(10·log10(15.36e6/15e3) ≈ 30 dB) rescues the average case, which is exactly why the failure would be silent
and confined to the crowded-band cases we care about.

Decision: ANTSDR default `cs16`, `iq_full_scale = 2048.0` `[MEASURE]`; HackRF stays `cs8`/128.0 (cs16 for an
8-bit ADC is waste). Disk pressure is a **retention** problem, not a quantisation one: pre-trigger ring
buffer + event-gated writes + periodic background sampling. `--iq-format cs8` stays available for long soaks
and must be recorded, not inferred. Float on disk is never correct; complex64 is in-memory/export only.

RSSI: every dBFS number must reference the declared `iq_full_scale`. cs8-vs-cs16 is a 24 dB offset
(20·log10(2048/128)) waiting to be applied to the wrong session. Additionally `dsp/spectrogram.compute`
scales by 1/fft_size² with an unnormalised Hann window: a full-scale tone reads ≈ −6 dB, and the noise floor
is not a PSD. Canonical fix: scale the STFT by 1/Σw (coherent gain) so a full-scale tone reads 0 dBFS, and
report the floor as dBFS/Hz using the Hann ENBW (1.5 bins). SNR-based thresholds in `detect/energy.py` are
differences and survive unchanged; absolute `rssi_dbm` values shift and must be versioned in reports
(`rssi_dbfs`, `gain_db`, `receiver_offset_db`, `calibrated: false`).

## 5. Window and STFT

1 s stays: one DroneID cadence period (~600 ms) plus margin, and 15.36e6 complex64 = 123 MB is already the
memory-dominant object. Lengthening it doubles latency and RAM to buy one more cadence period; instead make
cadence estimation **multi-window** (a ring of per-window envelopes feeding `_estimate_cadence_ms`), since a
600 ms cadence inside 1 s often yields only two bursts and an autocorrelation peak near the noise.

Canonical STFT = FFT 1024 / Hann / hop 512 (50 % overlap, COLA-satisfying, 33.33 µs frames). The current
auto-hop cap (`_TARGET_FRAMES = 4000`) gives 250 µs frames at 15.36 MS/s, resolving a 643 µs DroneID burst
into ~2.6 frames — too coarse for burst morphology. The cost of hop 512 is not the FFTs (~30 k × 1024-pt
≈ 50 ms multithreaded) but `np.log10` over 30 M elements. Therefore **the detector must run in linear
power**, taking dB only on reduced quantities (per-slice sums, per-bin averages, the 200 µs product). That
removes ~1000× of log work and makes hop 512 affordable at 1 Hz `[MEASURE: window time on the reference
box]`. `time_decim` stays an explicit, recorded parameter.

Derived products (all integer ratios at 15.36 MS/s):
* **Detector**: linear block-mean ×6 → 200 µs frames, [5000 × 1024], 20 MB.
* **ML tensor**: block-mean ×30 → 1.000 ms frames, [1000 × 1024] float32, 4 MB.
* **Burst timing** below 200 µs: from the existing 20 µs |x|² envelope in
  `decode/droneid.find_burst_candidates`, not from the STFT.

## 6. Normalisation — detection vs ML

Store absolute dBFS: absolute → relative is a subtraction, the reverse is unrecoverable. The classifier
consumes `tensor_dB − noise_floor_dbfs(window)` plus a scalar side-channel (`noise_floor_dbfs`, `gain_db`,
`usable_bw_hz`, `rssi_dbfs`), so it can use absolute-level cues without being hostage to calibration.
Per-window *power* normalisation is rejected: it destroys duty cycle and SNR, the discriminative features.

`classify/train/features.py` builds the PSD feature on a **fraction of the captured band** — that, not the
sample rate per se, is why the DroneRF-trained bundle (40 MS/s) is invalid at 20 MS/s. Fixing the axis to
absolute Hz over the 12 MHz usable band makes a bundle portable across rates and receivers; the canonical
rate then merely makes it cheap. This is the single highest-value change for Workstream D.

## 7. Resampling strategy

* **Band-slice before resampling.** If the target occupies < half the source band: mix to DC → FIR
  low-pass → integer decimate → one small rational stage. `ofdm.resample_to` should split into (integer
  decimate, rational finish) so a 100 MS/s record avoids a ~12 500-tap polyphase filter end to end.
* Exact factors to 15.36 MS/s: 20 → **96/125**; 40 → ÷2 then 96/125; 56 → ÷2 then 96/175; 60 → ÷2 then
  64/125; 100 → ÷5 then 96/125. Rule: integer-decimate to the smallest rate ≥ 19.2 MS/s (1.25 × canonical,
  keeping the transition band out of the usable 12 MHz), then one `resample_poly`.
* Anti-alias: transition band must live between 12.0 MHz (usable) and 15.36 MHz; stopband ≥ 60 dB —
  otherwise a decimated Wi-Fi blocker folds into the usable band and becomes a phantom emitter.
* When the source rate exceeds ~2× canonical (most 100 MS/s public captures), emit **several** canonical
  windows at different centres from one wide record rather than centre-cropping blindly; record each
  `center_freq_hz` and the slice offset in `resample_chain`.
* Legacy HackRF: 20 MS/s files stay byte-identical on disk; canonical products are derived. HackRF's live
  default moves to 15.36 MS/s for *new* captures, so both backends are natively canonical.

## 8. Dataset preprocessing target

One canonical window = `<id>.npy` (complex64, ±1.0 full scale, 15 360 000 samples for 1.000 s) + `<id>.json`
sidecar mirroring `session.json`, so live and dataset paths share readers. Sidecar fields:
`schema_version`, `sample_rate_hz` (15.36e6), `duration_s`, `center_freq_hz`, `bandwidth_hz`,
`usable_bw_hz`, `captured_at`, `receiver {type, backend, firmware, driver}`,
`gain {mode, stages, db, changed_within_window: false}`, `iq_format_source`, `iq_full_scale_source`,
`resample_chain` (ordered list of {op, factor|up/down, taps, stopband_db, mix_hz}),
`noise_floor_dbfs`, `rssi_dbfs`, `dc_offset_corrected`, `quadrature_corrected`, `channel_id`,
`capture_group`, `clock {source, pps_locked}`, `sha256`, `source_dataset`, `source_file`, and
`label {class, protocol, airframe, evidence_level (1–5), provenance}`.
Labels carry their evidence level explicitly; a dataset's own label is at best level 5 and often level 2.
Training corpus = the [1000 × 1024] tensors (4 MB each); canonical IQ is kept only for a curated
decode-oriented subset (123 MB each).

## 9. ANTSDR-vs-HackRF DSP consequences

* **12-bit vs 8-bit.** ~24 dB more raw range; ANTSDR windows become thermal-noise-limited rather than
  quantisation-limited, so noise-floor estimates stabilise and HackRF-tuned `detect/energy.py` thresholds
  will be *conservative* on ANTSDR — re-validate, do not port blindly.
* **Manual gain: agreed.** AGC moves the dBFS reference inside a window: it destroys absolute RSSI,
  manufactures amplitude steps that read as bursts, and corrupts duty cycle, cadence and hop-spread. AD9361
  fast-attack AGC targets TDD comms, not spectral monitoring. Gain may be re-planned *between* windows by a
  slow scheduler and must be recorded per window; if AGC is enabled, mark the window ineligible for absolute
  RSSI and for ML ingestion.
* **DC offset / quadrature.** AD9361 provides BB/RF DC-offset and quadrature (QEC) tracking [SPEC: IIO
  attribute names]. Enable BB DC + quadrature tracking and record their state; expect image rejection to go
  from ~25 dBc to ~50–70 dBc. **False-positive rule:** a candidate mirrored about the tuned LO with the same
  time envelope as a stronger candidate is a suspected image — not an independent emitter or hop partner.
* **LO leakage.** Keep centre-bin blanking, widen to ±2 bins (±30 kHz), fix the stale comment in
  `dsp/spectrogram.py` (it cites 58 kHz of 20 MHz). Tuning on the emitter centre puts the leak on DroneID's
  unused DC carrier (§2).
* **Single RX channel today.** Nothing here assumes two channels; `channel_id`/`capture_group` exist so
  adding RX2 is additive. No coherence is claimed.

## 10. Synthetic validation plan (must run before the rate is frozen)

Goal: prove 15.36 MS/s does not raise the DroneID decode SNR threshold versus today's 20 MS/s path.
Method (as run, `bench/canonical_rate_sweep.py`): bursts synthesised at 61.44 MS/s, AWGN scaled so SNR is
fixed **in the 9.0 MHz occupied band, not per sample** — a per-sample definition hands the 20 MS/s arm a
spurious 10·log10(20/15.36) = 1.14 dB penalty and would "prove" whatever you wanted; each arm resamples
that one noisy master record to its own rate and calls `decode_all` unchanged; random CFO ±3 kHz and
random STO/burst placement per trial; success = CRC-valid **and** injected serial recovered. Arms: legacy
20, canonical 15.36, 13.44 / 12.288 / 11.52 fallbacks, cs8 and cs12(±2048) quantisation after a 10 dB peak
back-off, and two blockers (+30 dB CW at +6 MHz; +20 dB band-limited OFDM-like at +4.5…+8.5 MHz).
**Still owed (level-5 binding):** replay the 2026-09-04 golden session natively at 20 MS/s and after 96/125
resampling to canonical — identical CRC-valid frame contents and non-inferior `zc_score`. Synthetic
results alone say nothing about the air. Seeded; belongs in the suite as a slow-marked regression.

### 10.1 Results (2026-09-18, `bench/canonical_rate_sweep.py`, n=200/point, 0.5 dB steps)

The measured P(serial-correct decode) curve is **not monotonic**: a ~0.5 plateau at 2–6 dB, a dip to ~0.2
at 7–7.5 dB, then the real knee at 8–10 dB. `snr50_db` (first crossing of 0.5) therefore measures the
plateau, scatters ≥0.5 dB run-to-run (A: 2.79 vs 2.94; C: 4.44 vs 3.92) and even ranked 13.44 worse than
11.52, which is not physical. **Use `snr50_final_db`** — the SNR above which success stays ≥0.5;
it reproduces to ~0.05 dB. SNR50-final: 20 MS/s **9.28/9.32** · 15.36 **8.59** · 13.44 **8.21** ·
12.288 **8.02** · 11.52 **7.64/7.50** · cs8 **8.57** · cs12 **8.60** (n=100 recheck over 7–16 dB:
no-quant 8.56, cs8 8.50, cs12 8.48).

* D1 **accepted, and the sub-canonical rates carry no decode penalty**: required SNR *falls* with window
  width (less out-of-band noise reaches the envelope/PSD/correlator front end; the decoder resamples to
  15.36 regardless). Rate choice is a throughput/coverage decision, not a sensitivity one — but this holds
  in a noise-only environment; a wider window only pays when the extra *coverage* is needed.
* **cs8 vs cs12 is a non-difference** (≤0.1 dB). The earlier "cs12 0.73 dB worse" was the first-crossing
  estimator on the plateau, not physics: at 10 dB peak back-off both formats' quantisation noise sits
  ≳30 dB below a 3 dB-SNR signal. §4's cs16 case must rest on headroom/blocker dynamic range, not on this.
* **Both blocker arms decode 0 % at every SNR, bailing out in ~9 ms.** Root cause is candidate screening,
  not the mixer/CFO stage: `burst_spectrum` anchors its occupied-band search at `argmax(psd)`, so the
  blocker owns the peak, the band grows only over it (`droneid_shaped=False`), the reported centre is
  +6 MHz, and `decode_all` mixes the *burst* to −6 MHz before the front end. A realistic arm (+20 dB
  band-limited OFDM-like emitter at +4.5…+8.5 MHz, adjacent channel) fails the same way up to +16 dB, so
  this is a **field weakness, not a CW pathology**: any stronger emitter in the window blinds screening.
  Decoder-side fix (not done here): screen several spectral peaks and/or excise narrowband spurs first.

## 11. Files likely affected

`config.py` (rate/window/bandwidth/iq_format defaults) · `dsp/spectrogram.py` (coherent-gain
normalisation, hop policy, usable-band mask, linear-domain output, stale DC comment) · `detect/energy.py`
(usable-band mask, PSD floor, RSSI definition, saturated-bandwidth flag, image rejection) ·
`decode/ofdm.py` (two-stage `resample_to`) · `decode/droneid.py` (band-slice, raster-aware dwell) ·
`classify/train/features.py` + `data.py` (absolute-Hz axis, canonical rate, loader resampling) ·
`sdr/capture.py` (cs16 read/write, per-window gain/bandwidth metadata) ·
`docs/design/antsdr-backend.md` §6.5 · new `dsp/canonical.py` (builder's call). All under `aerix_rf/`.

## 12. Open items

* `[MEASURE]` Sustained ANTSDR GbE rate at 15.36 MS/s, 16-bit, 10+ min (`stream_rate_ratio ≥ 0.99`);
  `iq_full_scale` for `le:S12/16>>0` (2048 assumed — confirm against a known level); end-to-end 1 s window
  time with hop 512 + linear-domain detector; AD9361 passband flatness at `rf_bandwidth` 13.8 MHz (this
  validates the 12.0 MHz usable-band claim).
* `[SPEC]` HackRF exact 15.36 MS/s support and BB-filter step (hackrf-specialist); AD9361 DC/QEC tracking
  attribute names and defaults (antsdr-specialist).
* **RESEARCH NEEDED (architect → research-librarian):** the DJI DroneID 2.4 GHz burst-centre raster — is
  the observed 2429.5 MHz one of a fixed set (spacing, band edges, 5.8 GHz equivalent), and does it differ
  across OcuSync 2/3? The 15.36 MS/s dwell plan depends on it; one observed centre is not a raster.
