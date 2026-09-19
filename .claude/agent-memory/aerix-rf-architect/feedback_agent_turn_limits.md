---
name: agent-turn-limits
description: Subagents stop at ~28 (specialists) / ~40 (librarian) tool-call turns and SendMessage may be disabled — scope tasks so deliverables are written early; relaunch with a continuation brief.
metadata:
  type: feedback
---

Delegated agents hit hard turn limits (observed: antsdr-specialist 28, research-librarian 40) and are then unrecoverable when SendMessage is disabled — their unsent report is lost, though files they wrote survive.

**Why:** 2026-09-18 two of the first four agents timed out with zero report; recovery cost a relaunch each.

Also: never `git add -A` while a builder is mid-flight — it sweeps half-finished files into the commit (happened 2026-09-19 with the annotate tool). Stage explicit paths, or exclude the builder's files with `git reset -q -- <paths>` before committing.

**How to apply:** In every brief: state the call budget, order the work so the durable file deliverable is written by ~40% of budget, and demand hand-back even if partial. Before relaunching, check scratchpad/target paths for partial outputs and pass them to the continuation agent. Keep discovery tasks and writing tasks separate when a task is broad.
