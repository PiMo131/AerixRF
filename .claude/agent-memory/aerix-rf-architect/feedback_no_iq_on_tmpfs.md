---
name: no-iq-on-tmpfs
description: Never write capture sessions/IQ into the Claude scratchpad or /tmp — it is a 32 GB RAM tmpfs; filling it kills agent outputs and running captures. Use an NVMe path.
metadata:
  type: feedback
---

Put live-capture session roots on the NVMe (e.g. `~/rf-sessions/` or directly under `~/rf-datasets/<dataset_id>/original/`), never under the session scratchpad or `/tmp`.

**Why:** 2026-09-18 I wrote ~40 GB of cs16 IQ into the scratchpad (a 32 GB tmpfs); ENOSPC destroyed a 300 s measurement, lost several agent reports, and required emergency cleanup. cs16 at 12.288 MS/s is 49 MB/s ≈ 3 GB/min.

**How to apply:** Any `aerix-rf capture/lock` command I or an agent runs must use `--session-root` on NVMe; preserve valuable sessions into `~/rf-datasets/aerix_antsdr_ambient_<date>/original/` with sha256 verification. Also: don't run measurement captures while builders run test suites — CPU contention causes silent sample loss on the libiio path.
