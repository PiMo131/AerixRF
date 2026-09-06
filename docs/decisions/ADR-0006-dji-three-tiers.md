# ADR-0006: DJI links are handled in three tiers

- **Status:** Proposed (needs Q5 and Q6 in `../../QUESTIONS.md`)
- **Date:** 2026-09-06
- **Sources:** `../../research/verification-log.md` (verdicts 4 `dji-generation-coverage` and 7 `dji-eu-rid`), `../../research/landscape.md`, `../../research/regulatory.md`

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
| C: identity, where the law compels it | any DJI carrying an EU class label of **C1 or above** | standard Remote ID via a monitor-mode Wi-Fi receiver (Beacon), parsed by `remoteid/` | the normal ODID observation; correlated with tier B detections by time and RSSI |
| D: nothing but energy | **C0, under 250 g**, and unmarked legacy airframes | detection and classification only | "a DJI-class airlink is here"; no identity exists to be had |

Paid decryption services are **not** used unless the maintainer decides
otherwise; if ever enabled they must be labelled as third-party provenance in
the observation.

## Consequences

- **Tier C does not cover everything, and the gap is the whole point of tier
  D.** The EU Remote ID obligation attaches to the class label, not to the
  aircraft: C1 and above must broadcast, C0 under 250 g is exempt. An earlier
  version of this record said "any DJI with EU firmware", which is wrong and
  would have built a detection network around an identity source that is
  silent for a large part of the consumer fleet. A DJI Neo (135 g) and a
  Mini 4 Pro on its standard battery (249 g) broadcast no standard Remote ID
  at all, while the *same* Mini 4 Pro on the Intelligent Flight Battery Plus
  crosses 250 g and starts broadcasting. The battery decides whether the
  aircraft is identifiable. `remoteid.SystemMessage.exempt_from_remote_id`
  carries this into the code, and an empty Remote ID scan must never be
  reported as an empty sky.
- **The maintainer's own fleet lands almost entirely outside tier A.** Avata
  (O3) is tier A only through the closed firmware; Avata 2, Mini 4 Pro and
  Neo are tier B, and of those only the Avata 2 (C1, 377 g) reaches tier C.
  Open code decodes exactly two airframes end to end, the Mini 2 and the
  Mavic Air 2, and the fleet contains neither. Validating the open decoder
  therefore needs a borrowed or second-hand Mini 2, which is also what
  proto17 issue 58 has been blocked on.
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
