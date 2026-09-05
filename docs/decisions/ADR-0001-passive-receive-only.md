# ADR-0001: Passive receive only

- **Status:** Accepted
- **Date:** 2026-09-05

## Context

The ANTSDR E200 is a full-duplex 2x2 transceiver: the same board that receives
a drone link can transmit on it. Drone RF work attracts three activities that
are illegal for a private operator in the Netherlands and the EU: jamming,
spoofing (including fake Remote ID broadcasts) and taking over a control link.
Receiving and analysing signals for detection is the activity the surrounding
AERIX project exists for, and is the only one this directory needs.

## Decision

Everything under `antsdr/` is receive-only. No module configures the E200 TX
path, no code generates over-the-air waveforms, and synthetic signals exist
only as in-memory or on-disk test data. The device layer never enables TX and
leaves the TX attenuation at maximum. Any future transmit use (for example a
calibration tone into a cable) gets its own ADR and its own package.

## Consequences

- Legal review stays simple: passive reception and local analysis.
- Direction-finding calibration must use received signals of opportunity or a
  cabled external generator, not the E200's own TX.
- The toolkit can be shared and reviewed without export or misuse concerns.

## Alternatives considered

- Include a TX calibration helper behind a flag: rejected, a flag is not a
  boundary and the feature is not needed for detection.
