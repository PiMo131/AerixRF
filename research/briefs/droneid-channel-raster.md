# DJI DroneID channel raster, SN prefixes, and NDSS'23 serial-modification method

## Q1 — DroneID burst-centre raster (2.4 GHz / 5.8 GHz)

No source in or out of corpus publishes an official DJI-disclosed raster. All three
independent sources are **empirical "frequencies I've seen" lists**, not a decoded
protocol spec, and the two code-derived lists disagree in channel count and spacing.
AERIX's single observed point (2429.5 MHz, Mini 3, 2026-09-04) lands almost exactly on
both lists' shared point (RUB: 2429.502441 MHz) — good cross-validation of *that one
point*, not evidence of a full raster.

### 2.4 GHz candidates

| Centre MHz | proto17 README | RUB-SysSec scan list | Grade |
|---|---|---|---|
| 2399.5 | ✓ | — | PRIMARY CODE (proto17 `README.md` "Known Values → Frequencies", author-observed, explicitly non-exhaustive: *"There might be others, but that's just what I've seen"*) |
| 2414.5 | ✓ | ✓ | PRIMARY CODE, agreement |
| 2429.5 | ✓ | ✓ (2429.502441) | PRIMARY CODE, agreement; **matches AERIX's observed 2429.5 MHz to <2 kHz** |
| 2434.5 | — | ✓ | PRIMARY CODE (RUB only; breaks the 15 MHz pattern — 5 MHz above 2429.5, 10 MHz below 2444.5) |
| 2444.5 | ✓ | ✓ | agreement |
| 2459.5 | ✓ | ✓ | agreement |
| 2474.5 | — | ✓ | RUB only |

proto17's 5 points are uniform 15 MHz spacing (2399.5→2459.5). RUB's 6 points are
irregular (15/5/10/15/15 MHz steps) and shift the window up by one 15 MHz slot
(includes 2474.5, excludes 2399.5). Union = 7 unique centres spanning 2399.5–2474.5 MHz
(75 MHz).

### 5.8 GHz candidates

| Centre MHz | proto17 README | RUB-SysSec scan list |
|---|---|---|
| 5721.5 / 5731.5 / 5741.5 | — | ✓ / ✓ / ✓ |
| 5756.5 | ✓ | ✓ (only shared point) |
| 5761.5 / 5771.5 | — | ✓ / ✓ |
| 5776.5 | ✓ | — |
| 5786.5 / 5801.5 / 5816.5 / 5831.5 | — | ✓ ✓ ✓ ✓ |
| 5796.5 | ✓ | — |

proto17: 3 points, uniform 20 MHz spacing (5756.5, 5776.5, 5796.5). RUB: 10 points
spanning 5721.5–5831.5 (110 MHz), irregular 5/10/15 MHz steps. Only 5756.5 is common to
both — the two lists disagree far more in the 5.8 GHz band than in 2.4 GHz. **Unresolved
conflict**, not just rounding.

### Channel width, hop behaviour, dwell — NDSS'23 paper (Schiller et al. 2023, PRIMARY PAPER)
- DroneID OFDM occupied BW: 1024 subcarriers @ 15 kHz SCS = **15.36 MHz including guard**
  (matches leegang12 article 264/276, Medium→High agreement).
- Burst interval measured **640 ms** (vs. proto17's unverified "~600 ms" estimate — prefer
  the paper's measured value).
- Paper states drones **"dynamically switch between the 2.4 GHz and 5.7 GHz band"**
  (inter-band) and separately cites the FCC ID database for OcuSync video: **20 MHz wide
  OFDM downlink channels**, with the **uplink control channel using frequency hopping on
  narrower channels** — this describes the video/control link channelization, not
  necessarily the DroneID broadcast raster itself; the paper does not publish a DroneID
  hop list. Their own receiver avoids needing one: it **broadband-scans 50 MHz windows,
  1.3 s dwell per band**, then locks onto whichever centre produced a valid frame.
- RUB-SysSec's shipped code (`droneid_receiver_live.py`) is a **scan-then-lock** receiver:
  it iterates its 16-entry list one center at a time (dwell = one `num_samps` capture at
  the configured sample rate/duration, CLI-configurable, not a fixed protocol dwell), and
  latches onto a frequency once a valid frame decodes, falling back to scanning after 10
  consecutive misses. This confirms the frequency list is an **engineering scan list**,
  not a decoded hop schedule.
- No source (paper, either repo, or CSDN corpus) discloses a deterministic hop *pattern*
  (sequence/PRNG) — proto17 explicitly: *"The frequency varies and I've heard that there
  is a pattern to it, but cannot validate with my SDR as the bandwidth isn't high
  enough."* Treat hop pattern as **unknown**, not modeled.

### Implication for ANTSDR 15.36 MS/s dwell planning (INFERRED, escalate to rf-dsp-specialist)
- Burst occupied BW (~15.36 MHz) fits inside a 15.36 MS/s window with zero margin — no
  guard band for CFO/placement error, unlike HackRF's 20 MS/s window. A single ANTSDR
  window cannot cover two candidate centres 15 MHz apart simultaneously.
- With burst interval 640 ms and the NDSS paper's own ~37% successful-decode rate per
  expected packet even *while locked on frequency*, dwell per untried candidate centre
  should be planned for **≥2 burst intervals (≥1.3 s)** before moving on, not a single
  640 ms window — this is an inference from the paper's numbers, not a stated
  recommendation.
- 7 candidate 2.4 GHz centres × ≥1.3 s ≈ 9+ s to sweep the band once; the 5.8 GHz band
  (12 unique centres) is worse and its raster is the less-agreed one. Recommend
  `rf-dsp-specialist`/`hardware-architect` decide whether ANTSDR should prioritize 2.4 GHz
  sweep + opportunistic 5.8 GHz, given the corpus's disagreement on the 5.8 GHz raster.

## Q2 — DJI serial-number prefix → model mapping

**No documented/official DJI mapping found.** DJI's own support page only explains
*where* to find the SN on the device/app, not how to decode it. All prefix-mapping
claims found are **COMMUNITY** grade: third-party lookup tools (serial-number-decoder.com,
"Dank Drone Downloader" DDD2 decoder) and MavicPilots forum threads ("DJI Mavic model
based on serial number check", "DJI Serial Decoder") assert that the first 3–4
characters of the 14-character SN are model-specific (example prefixes surfaced by
search: Mavic 3 = `1581F4`, Mavic 3 Classic = `1581F67P`, Mavic 3 Pro = `1581F67Q`), but
none of these were verified against an authoritative DJI source this pass and no prefix
table was directly read (tool-gated lookups, not published tables). Treat as **community
lore**, not proven — do not hardcode prefix→model logic in AERIX without independent
corroboration from multiple confirmed-model serials.

## Q3 — NDSS'23 / RUB-SysSec: `mini2_sm` sample and the `SysSecWasHere`/spoofed serial

Confirmed by direct read of `ndss2023_f217_paper.pdf` (Schiller et al., NDSS 2023) text:
- `mini2_sm` is one of two real IQ captures shipped in the repo's `samples/`
  (the other is `mavic_air_2`), used to demo both the offline and live receiver.
- The paper's Fig. 8 caption: *"A decoded DroneID packet with the manipulated serial
  number `spoofed` and a spoofed operator location."* — confirms the receiver can display
  an attacker-altered serial number field as transmitted.
- **Mechanism is firmware modification, not a crafted RF transmission.** Section IV
  ("Security Analysis with Physical Access"), vulnerability **"(2) Arbitrary Serial
  Number (#15)"**: *"While fuzzing the DJI Mini 2 drone, the UI oracle discovered that
  the fuzzer managed to change the serial number of the flight controller... An attacker
  can abuse this to spoof their identity, as this serial number is also the one that is
  transmitted in DroneID."* The bug was found via their custom DUML black-box fuzzer
  against the flight controller, changing the **persisted** serial number in firmware
  storage; DroneID then broadcasts whatever value is stored — the over-the-air frame
  itself is a normal, unmodified DroneID transmission carrying an attacker-altered
  stored field, not a hand-crafted/spoofed RF packet. `SysSecWasHere` (seen in the
  CSDN-mirrored decode dumps, leegang12 articles 281/288) is consistent with this same
  test-marker convention.
- Grade: **PAPER, high confidence** (primary text, directly quoted, not paraphrased from
  a secondary summary).

## Sources
- `proto17/dji_droneid` README (mirrored locally: `research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/281/external_repos/proto17_dji_droneid_main.zip`, extracted and read directly, "Known Values → Frequencies/Burst Duration" section) — PRIMARY CODE
- `RUB-SysSec/DroneSecurity` `src/droneid_receiver_live.py` (mirrored at same path; also extracted to session scratchpad) — read directly, lines defining `frequencies` list and scan-then-lock loop — PRIMARY CODE
- `RUB-SysSec/DroneSecurity` `README.md` (same mirror) — PRIMARY (repo docs; confirms NDSS'23 citation, `mini2_sm` sample provenance, USRP B205-mini/Mini2/Mavic Air 2 test environment)
- Schiller et al., "Drone Security and the Mysterious Case of DJI's DroneID," NDSS 2023, `https://www.ndss-symposium.org/wp-content/uploads/2023/02/ndss2023_f217_paper.pdf` — fetched and `pdftotext`-extracted this pass (Sections III.D "Wireless Physical Layer", IV "Security Analysis with Physical Access" incl. bug #15) — PRIMARY PAPER
- CSDN leegang12 article 281 (`research/library/csdn_enriched/AERIX_RF_CSDN/leegang12/281/article.pdf`) — confirmed via direct text comparison to be a Chinese translation of the proto17 README, not an independent source
- Community serial-number sources (not independently verified): `https://serial-number-decoder.com/dji/dji.php`, `https://www.dankdronedownloader.com/DDD2/app/decoder`, MavicPilots forum threads — COMMUNITY

## Open questions
- No source resolves the 5.8 GHz raster conflict (3 vs 10 points, only 1 shared) or
  confirms/denies a deterministic hop pattern — flag as unresolved for any future field
  capture that could add data points.
- Whether the RUB-SysSec 16-frequency list was itself empirically derived from bulk
  captures (like leegang12's claimed "bulk capture" articles 296/305) or copied/extended
  from proto17 is not stated in either repo — not resolved this pass.
