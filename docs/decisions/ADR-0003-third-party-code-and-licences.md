# ADR-0003: Third-party code: reuse by licence, otherwise re-implement the wire format

- **Status:** Accepted
- **Date:** 2026-09-05

## Context

The research phase (`../../research/sources.md`) found valuable open projects
with very different licences: GNU Radio blocks and academic decoders under
GPL, host tooling around the ANTSDR DroneID firmware published on GitHub
without any licence file (which legally means all rights reserved), and
vendor firmware images distributed as binaries. AERIX is a commercial product
line, so what gets copied into this repository matters.

## Decision

1. Code with a permissive licence (MIT, BSD, Apache-2.0) may be vendored or
   depended on; the licence text travels with it and the origin is recorded in
   `sources.md`.
2. GPL code is used as a separate process or an optional dependency (for
   example a GNU Radio flowgraph launched from the toolkit), never linked into
   the toolkit package.
3. Where a project has no licence, we do not copy its code. We may document and
   re-implement the *wire format* or the *algorithm* it reveals, citing it as
   the source of the format description. The DJI DroneID firmware bridge in
   `toolkit/antsdr_toolkit/bridges/dji_droneid.py` is such an independent
   re-implementation.
4. Vendor firmware binaries are never committed here; the ADR for the firmware
   personality records where to fetch them and which checksum was used.

## Consequences

- Every reused project appears in `sources.md` with its licence.
- Some convenient code (unlicensed scripts) must be rewritten instead of
  copied. This is a one-time cost.

## Alternatives considered

- Fork and copy freely because it is "just research": rejected, this
  directory is inside a product repository.
