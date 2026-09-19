# Same-receiver positives campaign — operator protocol (v1, 2026-09-19)

Purpose: capture DJI aircraft (O2 if available; O3/O4 for detection/classification) with the ANTSDR E200 in
ONE continuous session per band so positives and negatives share room, antenna, front-end state and time.
Labels come ONLY from the operator timeline (evidence level 5). Never from detections.

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
