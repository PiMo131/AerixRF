# Phase 0 baseline: what is being audited

The frozen state the validation in `../../VALIDATION_PLAN.md` is measured
against. Nothing was repaired while taking these readings, which is the point
of the phase: a second developer should be able to check out the commit below
and reproduce exactly this.

## Commit and environment

| | |
|---|---|
| Branch | `claude/antsdr-drone-rf-detection-ac0uxs` |
| Head at freeze | `5eee5c76d8fb5e4aeedfc72403912e3d34af11be` |
| Plan's stated baseline | `a7d8cf62ea8b3123a320b71c88b1917d93819eb7` (ADR-0012) |
| Python | 3.11.15 |
| Platform | Linux 6.18.44 x86-64, glibc 2.39 |
| numpy | 2.4.6 |
| scipy | 1.17.1 |
| pytest | 9.1.1 |
| ruff | 0.16.6 |

The head is ahead of the plan's stated baseline by the merge of the plan
itself plus one commit (`38ad028`, the fourth Windows trap). Nothing in that
commit touches code under audit; it edits `ADR-0012` and one docstring in
`bridges/dji_droneid.py`.

## Test suite, before any change

**457 passed, 0 failed, 0 skipped, 0 xfail**, in 32 seconds.

| Test file | Tests |
|---|---|
| `test_remoteid.py` | 69 |
| `test_video_decode.py` | 35 |
| `test_droneid.py` | 34 |
| `test_hardware.py` | 31 |
| `test_dji_droneid.py` | 31 |
| `test_sigmf_io.py` | 29 |
| `test_fleet.py` | 21 |
| `test_fpv.py` | 18 |
| `test_firstrun.py` | 17 |
| `test_file_source.py` | 16 |
| `test_heuristic.py` | 15 |
| `test_sweep.py` | 14 |
| `test_synthetic.py` | 11 |
| `test_spectrum.py`, `test_scan_planner.py`, `test_cyclo.py` | 10 each |
| `test_cli_capture.py` | 9 |
| `test_signatures.py`, `test_features.py`, `test_bursts.py` | 8 each |
| `test_cli.py` | 7 |
| `test_cli_classify.py` | 6 |
| `test_events.py`, `test_cli_droneid.py` | 5 each |

Lint: `ruff check` passes with no findings.

Size: 12,842 lines of package code, 6,290 lines of tests, across 47 modules.

## Clean-environment smoke test

A fresh virtualenv, `pip install -e .`, then importing every module:

**37 of 37 modules import**, and the `antsdr-tk` entry point runs and reports
version 0.1.0. Notably `device.e200` imports without `pyadi-iio` present,
because the driver import is deferred into the constructor; that is deliberate
and is what lets the test suite and the CLI run on a machine with no radio
stack installed.

## Validation gaps found in this phase

**There is no continuous integration.** No `.github/workflows` exists at the
repository root or under `antsdr/`. Every test result recorded anywhere in
this project, including the 457 above, comes from a manual run on one machine
with one set of dependency versions. Nothing prevents a commit that breaks the
suite from being pushed, and nothing checks the package against a Python or
numpy version other than the two pinned here. This is the finding of Phase 0
and it is a precondition for trusting anything in Phase 1: an audit of code
that no machine re-checks is a snapshot, not a guarantee.

**The dependency floor is untested.** `pyproject.toml` declares minimum
versions; only the installed versions above have ever been exercised. numpy
2.4 and scipy 1.17 are both recent, and the code has never run against the
older versions it claims to support.

**No coverage measurement exists**, so "457 tests" says nothing about which
lines or branches are reached.

## What this phase deliberately did not do

No test was fixed, no lint rule silenced, no version pinned. The next phase
audits this exact state.
