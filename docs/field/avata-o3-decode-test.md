# Avata (OcuSync 3) DroneID decode test — checklist (v1, 2026-09-19)

Why: the research corpus documents plaintext DroneID decodes on O3 aircraft (Mini 3 Pro, Mavic 3); our
decoder is proven on O2 real IQ. If the Avata decodes, acceptance A4 ("CRC-valid DJI frame captured by the
E200") is met without borrowing an O2 aircraft. Receive-only; the aircraft may stay on the ground.

## Setup
- E200 on `enp0s31f6` (192.168.1.10), stock antenna on the exposed RX port (A_BALANCED).
- Env: `export LD_LIBRARY_PATH=/home/jarvis/aerix-rf/.antsdr-tools/mamba/envs/antsdr/lib AERIX_RF_ANTSDR_URI=ip:192.168.1.10`
- Session root on NVMe: `R=~/rf-sessions/avata_o3_<date>`; IQ ON (`--max-gb 60`).
- Power the Avata + goggles/controller, wait for link; aircraft on the ground, 2–5 m from the antenna.

## Dwell plan (12.288 MS/s ⇒ ~10 MHz usable per dwell; DroneID burst ≈9 MHz, 640 ms cadence ⇒ ≥60 s per centre)
```
for C in 2406 2414.5 2429.5 2444.5 2459.5 2474.5; do
  uv run aerix-rf lock --backend antsdr_proc --center-mhz $C --seconds 90 --record-all \
      --label "avata_o3 2.4G c$C ground" --drone-manufacturer DJI --drone-model Avata \
      --drone-state ground --controller-state on --motors-state off --distance-m 3 --session-root $R
done
for C in 5721.5 5756.5 5776.5 5796.5 5831.5; do
  uv run aerix-rf lock --backend antsdr_proc --center-mhz $C --seconds 90 --record-all \
      --label "avata_o3 5.8G c$C ground" --drone-manufacturer DJI --drone-model Avata \
      --drone-state ground --controller-state on --motors-state off --distance-m 3 --session-root $R
done
```
Watch the status line: `dec=C` = CRC-valid frame (prints serial/position). `clip=` warning ⇒ lower `--gain-db`.

## Accept / reject
- ACCEPT: ≥1 window with `dec=C` in any dwell; `aerix-rf replay` of that session reproduces it; serial is a
  14-char DJI-style string and `product_type` is plausible; record centre frequency and band.
- If only `dec=A/B` (ZC sync but CRC fails): O3 transport differs — capture 5 min at the best centre for
  offline analysis (do NOT tune the decoder live).
- If no ZC hits at all: check the link is up (goggles video), try the other band, then the far raster edges.

## Afterwards
`aerix-rf report <session> --print`; preserve the session under `~/rf-datasets/aerix_antsdr_positives_<date>/original/`.
