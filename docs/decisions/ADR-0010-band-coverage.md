# ADR-0010: Band coverage: consumer and hobby links first, optional wide sweep

- **Status:** Accepted (Q2 answered 2026-09-06: DJI and FPV first, wide sweep optional)
- **Date:** 2026-09-06
- **Sources:** `../../research/signal-reference.md`, `../../research/foreign-perspective.md`

## Context

Consumer and hobby drones in the EU live in 2.4 GHz, 5.8 GHz, 868 MHz and,
for DJI O4 and Autel SkyLink 3, the 5.2 GHz DFS block. The Russian and
Ukrainian sources document links that have drifted far outside those bands
(ELRS forks at 360-560 and 720-1020 MHz, analog video from 460 MHz to above
6 GHz, OpenIPC at 3.6 and 5.9-7.1 GHz). The E200 tunes 70 MHz to 6 GHz and
sweeps 56 MHz at a time, so wide coverage is a scheduling and revisit-time
question, not a hardware one, except above 6 GHz.

The maintainer answered Q2 on 2026-09-06: consumer DJI and the FPV/hobby
families come first, and the security-style wide sweep is an option rather
than a default. That is the split this record already proposed, so it is
adopted unchanged.

## Decision

The default scan profile covers, in priority order: 2400-2483.5 MHz,
5725-5875 MHz, 5150-5250 MHz, 863-870 MHz, then the full 5.3-5.95 GHz analog
video table and 1080-1360 MHz. A second profile, off by default, sweeps
150 MHz to 6 GHz in 50 MHz steps with energy and chirp detection only, for
security deployments that must flag unusual links. Band plans are data
(`scan/bands.py`), not code.

## Consequences

- Sub-second revisit of the 5.8 GHz video band is feasible in the default
  profile; the wide profile trades revisit time for coverage.
- Legality of listening in non-hobby bands is covered by ADR-0011.

## Alternatives considered

- 2.4 and 5.8 GHz only: misses DJI O4 at 5.2 GHz and every sub-GHz control
  link; rejected.
