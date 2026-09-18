# Memory index — hardware-architect

- [ANTSDR is now the primary receiver](project_antsdr-primary-receiver.md) — 2026-09-18 reversal of the project doc's Phase-3 sequencing; HackRF demoted to reference.
- [ANTSDR backend interface decisions](project_antsdr-backend-interface-decisions.md) — why ±1.0 normalization, sample-rate default (now 12.288), iq_format defaults, shared assembler, honest `None`.
- [HackRF couplings hiding outside IQSource](project_hackrf-couplings-in-abstraction.md) — sweep/gain/bandwidth/format/timing assumptions the "already neutral" abstraction misses.
- [Producer runs as its own OS process](project_producer-process-split.md) — measured: GIL contention (not host load) causes silent loss; shared-memory ring design T7.
