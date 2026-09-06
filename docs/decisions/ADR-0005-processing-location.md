# ADR-0005: Processing location: host first, board later

- **Status:** Proposed
- **Date:** 2026-09-06
- **Sources:** `../../research/landscape.md` (edge inference budgets), `../../research/hardware-e200.md`

## Context

The E200's dual Cortex-A9 with 512 MB RAM already runs MicroPhase's DroneID
decoder, so on-board DSP is possible. The research found that spectrogram
CNNs cost roughly 30-300 GFLOP per decision window (Glüge VGG11: about 312
GFLOP per 75 ms window), which is out of reach for the ARM cores, while
energy gating, kurtosis, decimation and DroneID Zadoff-Chu correlation are
cheap. AERIX's architecture wants receivers that emit normalised observations
without a host, which argues for on-board processing eventually.

## Decision

Phase 1 runs everything on the Ethernet-attached Linux host: capture,
sweep, burst detection, features, heuristic classification, DroneID
detection and decoding. The package keeps every DSP stage in numpy with no
GUI or GNU Radio dependency, so the cheap stages (energy gate, kurtosis,
decimation, DroneID detector) can later be moved to the E200's ARM as a
Python or C daemon that speaks the same event schema (ADR-0008).

## Consequences

- Fast iteration and full inspectability during the research phase.
- A laptop is part of the sensor until phase 2.
- Module boundaries must stay clean: no stage may depend on matplotlib or on
  the CLI.

## Alternatives considered

- On-board from day one: blocks on a PetaLinux/Buildroot toolchain and on
  unmeasured CPU headroom; rejected for now.
