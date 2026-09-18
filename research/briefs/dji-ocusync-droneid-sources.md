# DJI OcuSync / DroneID — what the local corpus actually establishes

## Question
What does the local research corpus (17-article leegang12 CSDN series + mirrored code repos) establish about DJI O1-O4 physical-layer parameters and DroneID, with evidence grade per claim, and where does it conflict?

## Short answer
The corpus gives a dense, internally-cross-checked parameter set for **O1-O3 DroneID** (9-symbol OFDM burst, ZC synchronization at symbols 4/6 with roots 600/147, 601 subcarriers at 15 kHz SCS, 1024-pt FFT, QPSK, Gold scrambling, LTE Turbo coding, no pilots) that plaintext-decodes to full telemetry. For **O4**, the corpus is explicit and consistent: only the CRC verifies — **no telemetry payload has been demonstrated decoded from O4 anywhere in this archive**; the payload is stated to be encrypted. This matches AERIX's own stated blind spot. All of this is **secondary-source evidence** (one Chinese-language blog author's reverse-engineering claims, "秋风战士"/leegang12, CSDN 通信算法 series, 17 articles 2025-05 to 2025-10) — internally consistent across articles but not independently reproduced inside this corpus except by cross-referencing two mirrored open-source repos (`proto17/dji_droneid`, `RUB-SysSec/DroneSecurity`) that were not re-verified line-by-line this pass.

## Strongest evidence (by claim)

| Claim | Value | Source article(s) | Grade |
|---|---|---|---|
| DroneID burst structure | 9 OFDM symbols/frame, ZC sequences at symbol positions 4 and 6 | 264, 288, 305 (independently repeats the "图1 云哨帧结构" figure) | Medium — same author, but repeated across 3 separately-dated articles without contradiction |
| ZC roots | 600 and 147, brute-forced over 601 samples with middle element zeroed | 264, 281 | Medium — consistent across 2 articles |
| Subcarriers / SCS / FFT (O2, and by extension O1-O3) | 601 subcarriers (600 + DC), 15 kHz SCS, 1024-pt FFT, ~15.36 MHz BW | 264, 276 | Medium-High — 276 independently states measured Fs=15.36 MHz for a Phantom 4 Pro v2.0 (OcuSync 1), matching 264's O2 numbers |
| CP length | 72 samples, extended to 80 on symbols 1 and 9 | 264, 276 | Medium |
| Short-frame variant | Symbol 1 omitted on Mavic 2 and earlier → 576 µs frame | 264, 281 | Low-Medium — stated, not shown with a capture |
| Modulation / pilots | QPSK; **no pilots** — channel phase derived from the two ZC symbols, with a walking-phase correction (halve the phase difference between the two ZC channel estimates) | 281 | Medium — detailed method description, single source |
| Coding | LTE Turbo with the LTE sub-block interleaver permutation table; de-rate-matching with K/N/D/E parameters | 264, 283, 325 | Medium for "it's LTE Turbo" (325 shows the Tx chain diagram unredacted); **Low for actual K/N/D/E values — article 283 is a stub with every value left blank** |
| Scrambling | Gold sequence, LFSR seed recoverable from S1 (Sparrow S1) firmware; descrambler zeroes symbol 1 and restarts over the remaining 8 | 264, 281 | Medium |
| CRC | 16-bit at message-parser level (`8ffa`, `f557`, `5c39` observed); separately a 24-bit CRC scheme shown via calculator screenshot (WIDTH=24, XOROUT=0, no reflection) with **POLY/INIT deliberately blurred but brute-forceable from the shown input/output pair** | 288, 292, 326 | Medium — real observed values, but POLY/INIT for the 24-bit scheme are not disclosed in-corpus |
| PlaneInfo telemetry struct | Full struct incl. drone/pilot/home lat-lon, product type, uuid, license, serial, altitude | 264, 288, 292 | Medium-High — live decoded examples shown (Mini 2, Mavic 3, Mini 3 Pro), with real (but partly redacted) field values |
| O1/O2/O3 vs O4 | O1/O2/O3 decode to full plaintext telemetry (worked example: Mini 3 Pro, pkt_len 88, version 2, CRC match). **For O4, only `crc_byte`/`crc_calc` match — no telemetry field is ever shown decoded.** | 292 | **This is the load-bearing claim for AERIX's O4 assumption.** Medium confidence: single author, but stated plainly and re-checked by the archive's own audit pass; matches the general industry understanding that OcuSync 4 (O4) added payload encryption |
| Demod threshold | −5 dB acquisition threshold claimed in 4 separate articles (305, 316, 334, 335); only quantitative support is a MATLAB comment reporting CRC success 4996/5000 at −5 dB, 5000/5000 at −4 dB, **in AWGN simulation only** | 305, 316, 334, 335 | **Low** — the number is asserted repeatedly but the only evidence is a simulated AWGN result in a code skeleton, not a real-capture measurement. Treat as a design target, not a validated receiver spec. |
| Carrier frequencies | 2.3995-2.4595 GHz (5 channels) and 5.7565-5.7965 GHz (3 channels) | 281 | Medium |
| SDR front end used by the reference receiver | AD9361 | 288, 305, 325 | Low-Medium — stated, not otherwise corroborated in-corpus (relevant context for ANTSDR/AD9361 integration, but no register-level detail given) |

## Independent code cross-checks available locally
- `proto17/dji_droneid` — mirrored at `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/281/external_repos/proto17_dji_droneid_main.zip`. This is the repo AERIX already references (per prior `research/index.md`); now available locally for direct diffing against the article-derived parameters above. **Not re-read line-by-line this pass** — recommend `python-builder`/`rf-protocol-analyst` diff it against the table above if a discrepancy matters.
- `RUB-SysSec/DroneSecurity` (public_squash branch) — mirrored at the same `external_repos/` path, 5.0 MB. Contains a full Python DroneID receiver (`zcsequence.py`, `goldgen.py`, `qpsk.py`, `droneid_packet.py`) **plus two real IQ captures**: `samples/mavic_air_2`, `samples/mini2_sm`. This is the single best asset in the corpus for validating the ZC/Gold/QPSK claims above against real signals without needing a live drone. Not yet executed or hashed against the article claims.
- `leegang12/335/code/DJI_yunshao_rx_sim.m` — the only MATLAB in the corpus; a **skeleton** (CP_LENGTHS, NFFT, ncarriers, channelH left blank), useful mainly as confirmation of function decomposition (`ofdm_time_to_freq`, `che_equ`, `f_qamDemod`, `generate_scrambler_seq`, `Rate_Recover`, `Turbo_Decode`, `calc_crc`, `uav_message_pack`) rather than as runnable code.

## Competing / contradictory evidence inside the corpus
1. **Article 249's OcuSync CP numbers** (CP 1/32 ≈ 2.85 µs, symbol ≈ 94.25 µs) contradict 264 and 276 (CP 72/80 samples at 15.36 MHz = 4.69/5.21 µs, symbol 1096/1104 samples). 249's figures are screenshots of an AI-assistant conversation and are not internally self-consistent. **Prefer 264/276.**
2. **Burst repetition interval**: 640 ms (264) vs "~600 ms" (281). Unresolved.
3. **Guard bandwidth**: 15.36 MHz (264) vs 15.56 MHz (281). Unresolved, likely a units/rounding slip in one article.
4. **Pilots**: article 281 states there are no pilots and phase comes entirely from the ZC symbols; articles 296/305/325 reference a private specification document's table of contents that includes a section titled "导频数据组帧" (pilot data framing). **This is the most consequential unresolved contradiction** for a receiver design — it bears directly on channel estimation strategy. None of 296/305/325 actually publish the pilot-framing section content; they only show the document's navigation pane. Resolve by testing against the RUB-SysSec real IQ captures rather than trusting either claim.
5. **Threshold**: −5 dB acquisition (305/316/334) vs −4 dB full-decode threshold (334/335). The archive's own read is that these are acquisition-vs-full-decode thresholds rather than a real contradiction, but neither number has real-capture support (see table above).

## Confidence
**Medium overall.** Single-author reverse-engineering series, internally cross-checked across 17 articles with contradictions explicitly flagged above, corroborated only partially by two independently-authored open-source repos (not re-verified this pass). No primary DJI documentation, no standards document, and no independently-published academic paper is present in this corpus for O1-O4 (the project's existing `arXiv:2207.10795` reference is **not** present in `research/library/` and was not fetched this pass).

## Technical implications for AERIX RF
- The O1-O3 parameter table above is detailed enough to be a starting implementation target for a receiver, **provided** the pilot-vs-no-pilot contradiction (item 4 above) is resolved against real IQ before committing to a channel-estimation design — recommend testing directly against `RUB-SysSec/DroneSecurity`'s `samples/mavic_air_2` and `samples/mini2_sm` captures.
- Do not present the −5 dB / −4 dB thresholds as validated receiver sensitivity — they are simulation-only claims in this corpus. If AERIX needs a real sensitivity figure, it must be measured, not cited from this corpus.
- **O4 remains the correct blind spot to design around.** Nothing in this corpus, nor any corroborating source found, demonstrates O4 payload decode. AERIX's DOA/TDOA and RF-fingerprinting/classification tracks (see `NON_DJI_POSITION_MATRIX.md` and `GENERIC_HOPPING_FEATURES.md` in the local corpus, not yet briefed separately) are the corpus's own recommended fallback for O4 and for encrypted/closed competitor links.
- CRC/rate-matching parameters (POLY/INIT for the 24-bit CRC, K/N/D/E for de-rate-matching) are **not** available in this corpus. If needed, they are brute-forceable from article 326's shown input/output pair (24-bit CRC) — flagged as a bounded, well-defined task if a builder ever needs it, not "read more of the corpus."

## Open questions
- Does `proto17/dji_droneid` (already referenced by the project) already resolve the pilot-vs-no-pilot contradiction? Not checked this pass.
- Is the "云哨协议和接收算法 V1.0.0" 25-page spec (referenced but never obtained, author-contact-only per articles 296/305/325) obtainable through any other channel? No new lead found.
- Would decrypting/analyzing O4's CRC-only transport (channel coding + framing, independent of payload decryption) be a useful intermediate AERIX capability? Not addressed in this corpus — escalate to `rf-protocol-analyst` if the architect wants to scope it.

## Sources
- `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/{249,264,269,270,276,281,283,288,292,296,305,316,320,325,326,334,335}/` (article text/PDF/HTML/images, captured 2026-09-08 from CSDN, author 秋风战士/leegang12)
- `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/281/external_repos/{proto17_dji_droneid_main.zip, RUB-SysSec_DroneSecurity_public_squash.zip}`
- `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/335/code/DJI_yunshao_rx_sim.m`
- `research/library/csdn_enriched/AERIX_RF_CSDN/INDEX.md` (consolidated parameter table, Part 1) and `CSDN_RF_GAP_REPORT.md` — synthesis documents produced during the original capture pass, used here as a secondary cross-check, not as independent evidence.

## Decode thresholds and interference — literature (2026-09-18 addendum)

**Question:** does any published DroneID/OcuSync receiver report a decode threshold or performance under a co-channel/adjacent strong emitter (Wi-Fi, other drone)? AERIX's own synthetic pipeline measured an ~8-9 dB in-band SNR knee under clean AWGN and 0% decode under a +20 dB adjacent continuous emitter (pre-fix).

**Short answer:** No source found in this pass publishes a decode-vs-interference number comparable to AERIX's own +20 dB adjacent-emitter test. This appears to be a genuine literature gap, not a search failure — multiple independent 2023-2025 sources were checked and none report it.

**Findings (graded):**
1. **RUB-SysSec NDSS'23** ("Drone Security and the Mysterious Case of DJI's DroneID", ndss-symposium.org/wp-content/uploads/2023-217-paper.pdf) — describes the receiver/demod/decoder architecture (ZC detection, CFO/TO correction, QPSK subcarrier demod) but a direct read of quantitative SNR-threshold or interference-performance numbers was **not done this pass** (only searched, not fetched). Confidence: Unknown for this specific claim — do not cite a number from this paper without reading it directly.
2. **RUB-SysSec DroneSecurity GitHub issues** (e.g. "Ocusync 3.0 Drone Id demodulation" #46) — a WebSearch-synthesized summary suggested "DroneID frame detection may be quite slow where there is co-channel interference with non-DroneID transmitters," but this sentence was not verified against the primary issue text this pass. Confidence: **Low** — unverified paraphrase, treat as a lead not a fact.
3. **TranSIC-Net** (Rostami et al. 2025, MDPI Sensors 25(20):6488, PMC12567810 — directly read via PMC this pass) — a transformer-based OFDM symbol demodulator validated on real DroneID captures. Reports BER vs SNR over 0-20 dB (approx. 20-35% lower BER than LS+ZF baseline, biggest advantage below 15 dB) and real-world CRC frame-pass-rate: 100.0% (409/409) at <10 m range vs LS 99.3% (406/409); 91.8% (382/416) at ~100 m vs LS 88.5% (368/416). Explicitly addresses multipath, CFO, and additive noise. **Does not evaluate co-channel/adjacent-channel interference from a competing emitter (Wi-Fi or another drone) at all** — confirmed by direct reading, not inference. Confidence: **High** that this specific gap exists in this paper (primary source read); the BER/FPR numbers themselves are High confidence (directly quoted from the paper).
4. **"Drone Detection and Identification Using SDR: Analysis of DJI Mini 2 Drone ID Signals"** (ResearchGate 391371984, 2025) — WebFetch blocked (403 Forbidden), only a search-snippet claim seen: "tested under varying SNR conditions, demonstrating high detection accuracy and robustness against interference." No numbers obtained. Confidence: **Low/Unknown** — unverified, could not access primary text this pass.
5. **arXiv:2207.10795** ("DJI drone IDs are not encrypted") — located but not fetched/read this pass; earlier project references (see corpus item 4 above) already flag it as absent from the local library. No claim extracted.

**Competing evidence:** none found — the absence is consistent across all sources checked, not contradicted by any source claiming a specific interference-robustness number.

**Technical implications for AERIX RF:** AERIX's own +20 dB adjacent-emitter, 0%-decode measurement and the 8-9 dB clean-AWGN knee appear to be the **only quantified interference-robustness numbers currently available to this project** for DroneID/OcuSync decode — no published paper supplies a comparable co-channel/adjacent-emitter benchmark to validate against. Treat these as AERIX-internal engineering measurements (evidence level: operator-provided test truth / stage-4+ per the project's evidence-level scale), not as literature-confirmed figures. If a defensible external benchmark is needed, the two next-best candidates to pursue are (a) directly reading the RUB-SysSec NDSS'23 PDF's evaluation section (not yet done — bounded, single-document task) and (b) the RUB-SysSec GitHub issue #46 thread directly (to confirm or refute finding #2 above).

**Open questions:** has anyone published a DroneID BER/FPR curve under a *controlled, swept* interferer power (not just ambient/urban noise)? Not found. Would TranSIC-Net's authors' other work or dataset release include an interference sweep? Not checked this pass.
