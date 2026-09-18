# Blind OFDM detection / sync methods in the local corpus

## Question
Does the local research corpus have substantive material on OFDM synchronization (blind parameter estimation, CFO/STO, cyclostationary detection) applicable to AERIX's decoder, beyond the DJI-specific ZC-based approach already briefed in `dji-ocusync-droneid-sources.md`?

## Short answer
Yes, but it is thin and entirely secondary-source. The corpus's best material is two CSDN articles (269, 270) by the same DJI-DroneID author, describing **cyclic-autocorrelation-based blind OFDM parameter estimation** (recovering FFT length, symbol duration, and subcarrier spacing from cyclostationarity alone, with no synchronization or demodulation). This is a genuinely different technique from the DJI-specific ZC-correlation sync already used for DroneID, and is the corpus's proposed front end for detecting **unknown** OFDM video links (non-DJI FPV, unidentified emitters) before any protocol-specific receiver runs. Supporting material (FPV archive) adds MATLAB/Pluto-SDR/XSRP walkthroughs of generic OFDM CFO estimation and channel estimation, but these are lower-grade, mostly-unverified single-source blog posts with no code released.

## Strongest evidence

**Cyclostationary/cyclic-autocorrelation detection (`leegang12/269`, `270`)** — Medium confidence.
- Full closed-form theory given: the α=0 slice of the cyclic autocorrelation has a secondary peak whose spacing from the origin gives **Tu (useful/FFT-length symbol duration)**; **Ts = Tu + Tcp** is recovered from peak spacing in a different slice; peaks recur at **α = 1/Ts**; subcarrier spacing **Δf = 1/Tu**.
- Practical simplification stated: compute only two cyclic-autocorrelation slices rather than the full cyclic autocorrelation function (CAF) — a meaningful compute-cost reduction for an edge/embedded front end.
- Article 270 restates this as a pipeline: blind detection/parameter estimation feeds a protocol-specific receiver, naming a reference project `OFDMSignalDetection-master/OFDM_Signal_Detection` — **named only, no URL, not located or mirrored in this corpus.**
- Gap: the author's own simulation code for this method is stated as "available only by contacting the author" — no code accompanies either article.

**Generic hopping/OFDM feature synthesis (`generic_RF_detection/GENERIC_HOPPING_FEATURES.md`)** — Medium confidence (synthesis document, not primary data).
- Explicitly re-uses the 269/270 cyclostationary method as feature "D" in a proposed vendor-independent detector: "cyclic autocorrelation at the hop period... a hopping link is cyclostationary at its hop rate, detectable below the noise floor without demodulation."
- Cross-references DroneRFa's and RFUAV's dataset-derived features (hop bandwidth, hop dwell time, spectral centroid/shape, chirp-rate test for LoRa vs GFSK) as complementary, decode-free signal-family classifiers — useful for triaging a capture into "OFDM video" vs "FHSS control" vs "LoRa" before choosing a decoder path.
- This is a **research note, not validated code**; the document says so explicitly and defers validation to the (not-yet-downloaded) DroneRFa/RFUAV datasets.

**FPV-archive generic OFDM articles (`fpv/AERIX_FPV/digital_video/generic_OFDM/*`)** — Low confidence, use only as leads.
- `matlab_ofdm_blind_estimation` (UNVERIFIED, per the archive's own grading): claims blind OFDM parameter estimation via cyclic spectrum, higher-order cumulants, bandwidth and carrier-count estimation — but the article body is a paid-package advertisement; only the *method list* has value, no numbers or code shown.
- `spread_spectrum_cyclic_detection` (PLAUSIBLE): MATLAB energy detection + cyclic-spectrum analysis + false-alarm-rate verification — a plausible, moderately detailed (12.9k chars) worked toolkit, single source, not independently corroborated.
- `pluto_ofdm_chain`, `XSRP_ofdm_link` (PLAUSIBLE): end-to-end OFDM link build-outs on real SDR hardware (ADALM-Pluto, XSRP), covering symbol-start detection, CFO estimation/correction, and channel estimation/equalization at a tutorial level. Useful as worked examples of the *standard* Schmidl-Cox-family sync steps, not as novel technique.
- `IF_IQ_OFDM_detection` (UNVERIFIED — 469-character stub): titled exactly on-topic ("how IF IQ data detects/identifies OFDM signals") but contains nothing usable.

**OpenWIFI (`fpv/AERIX_FPV/digital_video/wifibroadcast/OpenWIFI_sdr_fpga/`)** — SUPPORTED grade in source archive (repo exists).
- Points to an open-source SDR+FPGA 802.11 OFDM implementation (`openwifi` project) as "the deepest available PHY reference for wifibroadcast-class links" in this corpus. Not DJI/DroneID-relevant, but directly relevant if AERIX ever needs a full reference 802.11-OFDM PHY (e.g., for OpenHD/wifibroadcast-class digital FPV, which uses 802.11 as its physical layer). Not mirrored locally this pass — repo only referenced, not fetched.

## Competing / contradictory evidence
None found — the corpus does not contain enough independent material on generic OFDM sync to cross-check itself; the only genuinely primary/technical items (269/270's theory) are not contradicted elsewhere in-corpus, but they are also not independently reproduced.

## Confidence
**Medium for the cyclostationary method's theoretical correctness** (it is standard, textbook cyclostationary-signal-processing reasoning, correctly stated, and consistent with well-known literature on blind OFDM parameter recovery — this is a case where the technique itself is well-established outside this corpus even though the specific write-up is a single secondary source). **Low for everything else in this brief** — no code, no numeric validation, several UNVERIFIED-graded stub articles.

## Technical implications for AERIX RF
- The two-slice cyclic-autocorrelation shortcut (269) is a reasonable **first building block** for a vendor-agnostic "is this an OFDM emission, and what is its likely Tu/Ts/Δf" front end — cheaper than a full CAF and decode-free, which matters for O4 and for unknown FPV emitters. This is a technique recommendation for `rf-dsp-specialist` to evaluate, not a ready implementation (no code in corpus).
- Do not adopt any numeric claim from the UNVERIFIED-graded FPV-archive articles (`matlab_ofdm_blind_estimation`, `IF_IQ_OFDM_detection`) without independent derivation — they are advertisement-length or stub-length.
- If AERIX needs a reference implementation of standard OFDM sync steps (Schmidl-Cox-style symbol-start + CFO estimation, channel estimation/equalization) to compare against a from-scratch build, `pluto_ofdm_chain` and `XSRP_ofdm_link` are tutorial-level worked examples worth a closer read by a builder — but they teach standard technique, they do not contain anything DJI- or FHSS-specific.
- `GENERIC_HOPPING_FEATURES.md`'s broader feature list (hop bandwidth, dwell time, spectral shape, chirp-rate test, sync-channel histogram spike) is a reasonable checklist for a **signal-family triage stage** ahead of any decoder, complementary to (not a replacement for) the cyclostationary OFDM-specific method.

## Open questions
- Is `OFDMSignalDetection-master/OFDM_Signal_Detection` (named in article 270, no URL given) locatable on GitHub? Not searched this pass — a bounded follow-up if the architect wants the cyclostationary method as runnable code rather than theory.
- Has AERIX's existing decoder work already implemented Schmidl-Cox-style sync for DJI DroneID (per the ZC-based approach in the DJI brief)? If so, the generic cyclostationary method here would only be needed for the *pre-decode triage* stage (detecting an unknown OFDM emission before knowing it's DJI), not for the DJI receiver itself — worth the architect confirming scope before commissioning implementation work.

## Sources
- `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/{269,270}/`
- `research/library/csdn_enriched/AERIX_RF_CSDN/generic_RF_detection/GENERIC_HOPPING_FEATURES.md`
- `research/library/fpv/AERIX_FPV/digital_video/generic_OFDM/{matlab_ofdm_blind_estimation,spread_spectrum_cyclic_detection,pluto_ofdm_chain,XSRP_ofdm_link,IF_IQ_OFDM_detection,COFDM_video_link,spread_turbo_ofdm_image}/`
- `research/library/fpv/AERIX_FPV/digital_video/wifibroadcast/OpenWIFI_sdr_fpga/` (pointer only, repo not mirrored)
- `research/library/fpv/AERIX_FPV/INDEX.md` (evidence-grade table used for cross-checking article quality)
