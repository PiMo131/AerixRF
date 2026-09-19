# Same-receiver positives campaign — operator protocol (v1, 2026-09-19)

Purpose: capture DJI aircraft (O2 if available; O3/O4 for detection/classification) with the ANTSDR E200 in
ONE continuous session per band so positives and negatives share room, antenna, front-end state and time.
Labels come ONLY from the operator timeline (evidence level 5). Never from detections.

## Priority measurements (from `research/briefs/dji-generations-and-o3o4-identification.md`)
1. O3 plaintext test with the Avata: dwell at 2400–2412 MHz (never captured before) and the raster centres
   2414.5/2429.5/2444.5/2459.5 MHz, then 5.8 GHz; accept = ≥1 CRC-valid frame with a plausible device_type.
2. O4 transport-to-CRC on any O4 airframe: ZC hit rate vs O2 reference, ≥20 frames with crc_byte==crc_calc,
   payload failing a plaintext check (entropy > 7.5 bits/byte, no ASCII serial).
3. Per-generation link morphology (occupied BW, burst duration/period, hop raster, band; idle/video/flight).

## Before
- Backend: `--backend antsdr_proc` (producer process), profile default (12.288 MS/s, 10 MHz, cs16, manual 40 dB).
- Session root on NVMe, e.g. `~/rf-sessions/positives_<date>/`. IQ ON (`--max-gb 200`).
- Note: aircraft model, firmware, link generation (O2/O3/O4), controller model, phone, antenna, room, distances.
- Watch the status line for `clip=`; if clipping appears at the closest distance, reduce `--gain-db` and LOG it.

## Timeline (per band; 2.4 GHz first, then 5.8 GHz)
| # | Interval | Duration | Aircraft | Controller/phone | Wi-Fi confuser | Purpose |
|---|---|---|---|---|---|---|
| 1 | OFF-baseline | 5 min | off | off | ambient | background |
| 2 | RC-only | 3 min | off | on (linked? no) | ambient | confuser negative |
| 3a | ON near | 3 min | on, motors off, ~2 m | on | ambient | positive, high SNR |
| — | gap | 1 min | off | off | ambient | separation |
| 3b | ON mid | 3 min | on, motors on/hover if safe, ~10 m | on | ambient | positive |
| — | gap | 1 min | off | off | ambient | separation |
| 3c | ON far | 3 min | on, ~30 m / max available | on | ambient | positive, low SNR |
| — | gap | 1 min | off | off | ambient | separation |
| 4 | ON + Wi-Fi | 3 min | on, ~10 m | on | phone streaming video on the same channel | anti-"quiet band" control |
| 5 | OFF-final | 5 min | off | off | ambient | background |

Log each transition as `HH:MM:SS <interval-id> <note>` (UTC or local — say which) in a text file
`timeline.txt` next to the session; `aerix-rf annotate <session> timeline.txt` applies it to the windows
(labels + evidence_level 5 + interval_id as run_id group). Windows inside a ±5 s guard band around each
transition are labelled `transition` and excluded from training.

## Safety / scope
Receive-only. No transmit, no link interference. Fly only where legal; hover/motors-on is optional.

## Addendum 2026-09-19 — RC-transmitter capture (Stage-1 validation)

Paired RC-on / RC-off windows in the same session and room; keep the in-room Wi-Fi AP ON so the fragment rule is
exercised. Record the transmitter model and protocol mode. Metrics to extract afterwards: measured −6 dB bandwidth vs
the link's known modulation width; hop grid spacing and burst duration vs known values; fraction of hops tagged
fragment when they fall inside the active Wi-Fi channel; detection rate vs SNR (vary distance); RC-off hopping rate as
the honest in-session false-alarm rate. Ask before the session: which RC link first, and can the AP stay on?
