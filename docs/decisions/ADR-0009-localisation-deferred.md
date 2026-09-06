# ADR-0009: Localisation (direction finding, TDOA, passive radar) is deferred

- **Status:** Proposed (needs Q9 in `../../QUESTIONS.md`)
- **Date:** 2026-09-06
- **Sources:** `../../research/landscape.md` section 6, `../../research/verification-log.md` (claim `rf-ports`)

## Context

The E200's two receive chains share one LO and are phase-coherent, so a
two-antenna interferometer is possible, but: the second chain sits on an
internal u.FL connector and needs a length-matched pigtail; the relative phase
changes on every LO, sample-rate or gain write and must be recalibrated from
an external common source because the toolkit never transmits; two elements
give a single ambiguous bearing with errors of several degrees; and the
2-channel host rate is about 5-10 MSPS per channel. TDOA needs a PPS or
10 MHz reference at each node (the E200 has one MMCX input and no GPS).
Passive radar with broadcast illuminators is original work, not a reuse.

## Decision

Localisation is out of scope for the first toolkit release. The device layer
supports two channels and records the RF port in SigMF so that a later
`doa` module (phase calibration table per tuning state, per-burst bearing,
optional MVDR spectrum) can be added without changing captures. Pilot
position from DroneID (tier A in ADR-0006) and Remote ID remains the only
localisation the toolkit reports.

## Consequences

- No pigtail, no calibration rig and no second antenna are needed for the
  first field tests.
- A first-run characterisation script for RX1-RX2 phase drift is worth
  writing early, because nobody has published those numbers for the E200.

## Alternatives considered

- Two-element DoA in release one: the algorithm is small, the calibration
  workflow is not; deferred until the base detections are trusted.
