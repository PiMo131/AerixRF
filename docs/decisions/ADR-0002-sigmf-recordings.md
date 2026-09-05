# ADR-0002: Every IQ recording is SigMF with metadata and truth annotations

- **Status:** Accepted
- **Date:** 2026-09-05

## Context

Detection and classification work lives or dies on recordings: field captures
of real drones, synthetic scenes for tests, and public datasets. A raw `.iq`
file without sample rate, centre frequency, gain and time is worthless a week
later. The open datasets that matter for this work (DroneRF, DroneDetect,
RFUAV, CageDroneRF, see `../../research/datasets.md`) are increasingly
published with SigMF or SigMF-convertible metadata, and GNU Radio, Inspectrum
and most SDR tooling read it.

## Decision

All captures written by the toolkit are SigMF (`.sigmf-data` in `cf32_le`
plus `.sigmf-meta`). The metadata carries sample rate, centre frequency,
hardware description, gain, UTC time and the toolkit version. Detected bursts
and synthetic ground truth are stored as SigMF annotations
(`core:sample_start`, `core:sample_count`, `core:freq_lower_edge`,
`core:freq_upper_edge`, `core:label`). Readers also accept `ci16_le` and `ci8`
because that is what the AD9361 delivers natively, so recordings made with
other tools (iio_readdev, GNU Radio, UHD) load unchanged.

## Consequences

- Tests and demos use exactly the same file format as field captures; a
  detector can be run on a synthetic scene, a field recording or a public
  dataset with the same command.
- Annotations make every recording a labelled dataset item, which is what a
  later classifier needs.
- Files are large (8 bytes per sample in cf32). Long-duration captures should
  use `ci16_le` through the E200 firmware's native path; a writer for that is a
  small follow-up.

## Alternatives considered

- Raw interleaved float or int files: no metadata, rejected.
- HDF5 or NumPy `.npz`: fine for Python, invisible to SDR tools, rejected.
