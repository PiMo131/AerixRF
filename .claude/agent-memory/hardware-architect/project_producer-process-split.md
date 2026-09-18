---
name: producer-process-split
description: The ANTSDR silent-loss risk is GIL/same-process contention, not host load — acquisition producer moves to its own OS process with a shared-memory ring (T7)
metadata:
  type: project
---

The ANTSDR libiio acquisition producer runs (from design T7, 2026-09-18) as a **separate OS
process** from the DSP consumer, handing samples over a `multiprocessing.shared_memory` ring
(32 slots x 4 MiB = 128 MiB, ~2.7 s span at 12.288 MS/s) with a per-slot 64 B header and a JSON
socketpair control channel. Design lives in `docs/design/antsdr-backend.md` §T7.

**Why:** measurement, not preference. Brief §14 showed an expensive consumer *inside the producer's
own Python process* collapses the stream (throughput ratio 0.41, catastrophic interior phase jumps
under BIST). §14.1 then showed 12 saturating *separate OS processes* cost exactly nothing
(ratio 0.9998, zero jumps). So the failure mechanism is the GIL/same-process CPU share, which is
structurally fixable, not "the machine", which would only be a deployment rule. The libiio path has
no overflow counter, so this loss is otherwise silent.

**How to apply:**
- Never propose "keep the DSP light" or "field box runs nothing else heavy" as the primary defence
  for ANTSDR streaming again — that was the pre-§14.1 answer. The process split is the real fix;
  host-wide load is a secondary risk only near total CPU saturation (untested above 12/24 cores).
- Keep the two loss vocabularies separate: `loss_detection` stays the **device→host** link
  (`"inferred_rate_only"` on libiio, no hardware counter) and `host_loss_detection="exact_ring"`
  with an integer `host_dropped_samples` covers the **host transport**. Merging them would launder
  an inferred number into a counted one — same principle as [[antsdr-backend-interface-decisions]]'
  honest `None`.
- The ring + headers + control op set are backend-neutral by construction; HackRF can adopt them
  later (cs8, `raw_full_scale=128`, device-side `loss_detection="exact"`). Do not let libiio refill
  semantics leak into the ring contract — see [[hackrf-couplings-in-abstraction]].
- The producer process does refill/read + `raw_clip_stats` + memcpy only. cs16→complex64 conversion
  stays in the consumer; anything expensive added to the producer re-creates the original bug.
