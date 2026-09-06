# ADR-0008: Relation to the AERIX observation contract

- **Status:** Proposed (needs Q7 in `../../QUESTIONS.md`)
- **Date:** 2026-09-06
- **Sources:** `../../../contracts/observation-envelope.v1.schema.json`, `../../../docs/02-observation-contract.md`, `../../research/landscape.md`

## Context

The frozen AERIX envelope describes one reception of one Open Drone ID
transmission; `odid_raw` is mandatory and `source` already allows
`future_sdr`. Most of what the E200 produces is not an ODID reception: a
DroneID payload (a DJI-proprietary message with a different field set), an
O4 presence detection, an ELRS or analog-video classification, or a bearing.
Forcing these into the ODID envelope would violate its own rule that
everything derives from `odid_raw`.

## Decision

1. ODID received through the SDR (Wi-Fi Beacon via openwifi or gr-ieee802-11,
   BLE if ever decoded from IQ) uses the existing envelope unchanged with
   `source: future_sdr`, and the SDR's RF context goes into the existing
   `rf` block.
2. Everything else is a separate, provisional **RF detection event**
   (`toolkit/antsdr_toolkit/scan/events.py`, schema version 0.1): centre
   frequency, bandwidth, time, duration, peak and SNR, family and confidence,
   evidence, capture tier, personality, RF port, and a reference to the SigMF
   file and sample range that holds the raw IQ. Raw IQ is referenced, not
   embedded.
3. DJI DroneID payloads are carried inside that event as a typed `dji_droneid`
   evidence block with the raw 91 bytes, mirroring the envelope's
   raw-plus-decoded principle.
4. Promotion of the event schema into `contracts/` is a separate decision
   once the fields have survived a field test.

## Consequences

- The cloud contract stays frozen; nothing in AERIX changes until there is
  field data.
- Correlating an RF detection with an ODID track (same time window, RSSI
  trend, frequency plan) is a fusion-layer job, consistent with the
  architecture's rule that fusion sits above the immutable layer.

## Alternatives considered

- Extend the envelope now with optional RF-only fields: tempting, but it
  weakens `odid_raw NOT NULL`, the contract's core guarantee; rejected.
