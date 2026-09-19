---
name: droneid-channel-raster
description: DJI DroneID 2.4/5.8 GHz candidate-centre lists, dwell/hop behavior, and why the two known source lists disagree — feeds ANTSDR 15.36 MS/s dwell planning
metadata:
  type: project
---

Answered a 3-question brief for the DSP/protocol specialists 2026-09-18, written to
`research/briefs/droneid-channel-raster.md`. Full detail there; key facts worth keeping
in memory so I don't have to re-derive them:

## The two empirical frequency lists (both PRIMARY CODE, both self-declared non-exhaustive)
- **proto17/dji_droneid README** (`Known Values → Frequencies`): 2.4 GHz = 2399.5,
  2414.5, 2429.5, 2444.5, 2459.5 MHz (uniform 15 MHz spacing, 5 pts). 5.8 GHz = 5756.5,
  5776.5, 5796.5 MHz (uniform 20 MHz spacing, 3 pts). Author explicitly says "there
  might be others" and "I've heard there's a pattern [to which freq is used when] but
  cannot validate with my SDR as the bandwidth isn't high enough" — hop pattern is
  **unknown**, not just undocumented.
- **RUB-SysSec/DroneSecurity `src/droneid_receiver_live.py`** hardcoded scan list
  (variable `frequencies`, function `receive_thread`): 2.4 GHz = 2414.5, 2429.502441,
  2434.5, 2444.5, 2459.5, 2474.5 MHz (6 pts, irregular spacing). 5.8 GHz = 5721.5,
  5731.5, 5741.5, 5756.5, 5761.5, 5771.5, 5786.5, 5801.5, 5816.5, 5831.5 MHz (10 pts,
  irregular, spans 110 MHz). This is a **scan-then-lock** receiver (iterate list, lock
  onto whichever centre decodes a frame, fall back to scanning after 10 consecutive
  misses) — the list is an engineering scan list, not a decoded protocol hop table.
- Only 2414.5/2429.5/2444.5/2459.5 MHz (2.4 GHz) and 5756.5 MHz (5.8 GHz) are shared
  between the two lists. **5.8 GHz raster is the more contested one** (3 vs 10 points,
  110 MHz vs 40 MHz span) — flag this specifically if anyone asks about 5.8 GHz dwell
  planning again.
- AERIX's own observed point (2429.5 MHz, Mini 3, 2026-09-04) matches RUB's
  2429.502441 MHz to <2 kHz — good single-point cross-validation, not raster proof.
- CSDN leegang12 article 281 (previously graded Medium in
  `briefs/dji-ocusync-droneid-sources.md`) is confirmed this pass to be a **direct
  Chinese translation of the proto17 README**, not an independent source — its
  frequency claims should not be counted as a second, independent corroboration of
  proto17's list. Update this understanding if the older brief is revisited.

## NDSS'23 paper (Schiller et al.) — now actually fetched and read, not just referenced
- Full text extractable via `curl` + `pdftotext -layout` (WebFetch's own PDF handling
  failed/returned encoded garbage for this file both directly and via a mirror at
  `mschloegel.me/paper/schiller23dronesecurity.pdf` — always fall back to
  `curl -o x.pdf <url> && pdftotext -layout x.pdf -` for PDFs WebFetch chokes on).
- No DroneID hop list published in the paper. States drones "dynamically switch between
  the 2.4 GHz and 5.7 GHz band" (inter-band only) and separately cites the FCC ID
  database for OcuSync video/control channelization (20 MHz downlink OFDM, narrower
  frequency-hopped uplink control) — this is about the video/control link, not
  necessarily the DroneID broadcast itself; don't conflate the two when citing this
  paper.
- Burst interval **640 ms, measured** (not proto17's "~600 ms" guess) — prefer this
  number going forward.
- Their receiver dwells 1.3 s per 50 MHz band (broadband scan, not a fixed list) —
  deliberately avoids needing a channel list at all.
- Confirmed **~37% successful-decode rate even while locked on frequency** — relevant
  context if anyone asks for a dwell-time recommendation: implies dwell should budget
  for multiple burst intervals per candidate, not one.
- `mini2_sm` / `mavic_air_2` samples in `RUB-SysSec/DroneSecurity/samples/` are real
  captures used for both paper demo and repo's offline/live receiver.
- `spoofed`/`SysSecWasHere` test serials: confirmed **firmware-level bug (#15
  "Arbitrary Serial Number"), found via DUML fuzzing of the Mini 2 flight controller**,
  not a crafted/spoofed RF transmission. DroneID just broadcasts whatever serial is
  persisted in firmware storage — the RF frame itself is a normal unmodified DroneID
  transmission. Cite NDSS'23 Section IV, vulnerability #15, and Fig. 8 caption.

## DJI serial-number prefix→model mapping (Q2)
No official DJI documentation found. Only COMMUNITY-grade sources exist:
serial-number-decoder.com, dankdronedownloader.com/DDD2, MavicPilots forum threads.
Example prefixes surfaced by web search (Mavic 3 = `1581F4`, Mavic 3 Classic =
`1581F67P`, Mavic 3 Pro = `1581F67Q`) were **not independently verified** this pass —
treat as unverified lore if anyone wants to hardcode prefix→model logic in AERIX.

## Escalation note left in the brief
Dwell-time math for ANTSDR's 15.36 MS/s window (occupied BW ~15.36 MHz fits with zero
margin, unlike HackRF's 20 MS/s) is flagged as **INFERRED, not evidence** — recommended
`rf-dsp-specialist`/`hardware-architect` own the actual dwell-schedule decision using the
640 ms interval + ~37% decode-rate numbers above as inputs.
