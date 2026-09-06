# ADR-0006: DJI links are handled in three tiers

- **Status:** Proposed (needs Q5 and Q6 in `../../QUESTIONS.md`)
- **Date:** 2026-09-06
- **Sources:** `../../research/verification-log.md` (claim `droneid-decodability`), `../../research/landscape.md`

## Context

DJI DroneID (the OcuSync side channel with drone, pilot and home position) is
unencrypted on OcuSync 2 and 3 but encrypted since the O4 generation (Air 3,
August 2023 onward). Open decoders (proto17, RUB-SysSec) are verified only on
OcuSync-2-era drones (Mini 2, Mavic Air 2); the only thing that decodes
OcuSync 3 today is MicroPhase's closed firmware binary redistributed in
alphafox02/antsdr_dji_droneid, which reports O4 drones as a per-session hash
plus frequency and RSSI. O4 decryption exists only as paid cloud services
(DragonScope, MicroPhase's `o4online` endpoint). Meanwhile DJI drones sold in
the EU broadcast standard Remote ID over Wi-Fi Beacon, which AERIX already
ingests. Whether DroneID is sent from power-on or only with motors running is
contested and model-dependent.

## Decision

| Tier | Drones | What the toolkit does | Observation semantics |
|---|---|---|---|
| A: identity and position | OcuSync 2 and 3 (Mini 2, Air 2S, Mini 3, Mavic 3 family, Avata) | run the MicroPhase DroneID firmware on the E200 and parse its reports with `bridges/dji_droneid.py`; keep the open numpy decoder (`droneid/`) as the inspectable fallback and regression bench, verified only for OcuSync 2 | serial, model, drone, pilot and home position; source flag `dji_droneid_firmware` or `dji_droneid_open` |
| B: presence | O4 and later (Air 3, Mini 4 Pro, Avata 2, Neo, Mini 5 Pro) | PHY-level detection: Zadoff-Chu correlation, ~10 MHz burst, hop pattern, hash from the firmware if running | "DJI O4 airlink detected", hash as a transient track key, never an identity |
| C: identity for everything | any DJI with EU firmware | standard Remote ID via the existing AERIX receivers (Wi-Fi Beacon), optionally via openwifi on the E200 | the normal ODID observation; correlated with tier B detections by time and RSSI |

Paid decryption services are **not** used unless the maintainer decides
otherwise; if ever enabled they must be labelled as third-party provenance in
the observation.

## Consequences

- The closed firmware is a dependency for tier A on OcuSync 3; its licence is
  unstated and its protocol is documented only by third parties (ADR-0003).
- The toolkit does not claim O3 decoding from open code until someone
  reverse-engineers the 10-symbol, four-ZC burst (proto17 issue 58).
- DroneID start conditions are logged (motor_on, in_air, gps_valid bits), not
  assumed.

## Alternatives considered

- Open decoder only: honest but blind to O3 and O4 today; rejected as the
  sole path.
- Vendor decrypt API: internet dependency, unknown legal standing in the EU,
  recurring cost; rejected by default.
