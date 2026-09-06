# ADR-0011: Legal posture: receive-only, metadata first, review before multi-node recording

- **Status:** Proposed (needs Q10 in `../../QUESTIONS.md`)
- **Date:** 2026-09-06
- **Sources:** `../../research/regulatory.md`

## Context

The research (not legal advice) found: Dutch criminal law exempts data
received with a radio receiver from the interception offence unless a
"bijzondere inspanning" or a non-permitted receiver is used, and one legal
interpretation treats systematic recording with more than one receiver as
such an effort; Remote ID is a mandated public broadcast and the safest data
class; active counter-drone measures are reserved to police and Defence;
DroneID and Remote ID contents include personal data (operator position,
serial numbers); DJI's O4 encryption makes any decryption attempt a different
legal question altogether.

## Decision

1. Receive-only (ADR-0001), no decryption attempts, no use of decrypt
   services.
2. The toolkit stores signal metadata and classifications by default; raw IQ
   recordings are an explicit opt-in per capture, and decoded DroneID
   payloads are treated as personal data in the same way AERIX treats ODID
   operator fields.
3. Before a multi-node deployment records anything beyond Remote ID, Ecotax
   obtains a legal review of art. 139c Sr and the Telecommunicatiewet for the
   specific configuration.

## Consequences

- Single-receiver research and development can proceed now.
- Product deployment has a legal gate that must be planned.

## Alternatives considered

- Treat everything as free to receive: contradicted by the "bijzondere
  inspanning" interpretation; rejected.
