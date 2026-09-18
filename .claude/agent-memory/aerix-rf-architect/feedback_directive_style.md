---
name: user-directive-style
description: User issues long, structured directives with explicit "proceed" — skip the questionnaire ceremony, launch parallel workstreams, report at milestones with the requested numbered report.
metadata:
  type: feedback
---

When the user hands over a detailed structured directive (workstreams, deliverables, constraints) ending with "proceed unless a decision genuinely requires user input", do NOT run the 10–20 question planning questionnaire. Bootstrap parallel agents immediately and report using the numbered report format the user asked for.

**Why:** On 2026-09-18 the user rejected an AskUserQuestion prompt and instead supplied a full multi-workstream directive with explicit instructions to proceed and to keep downloads from blocking engineering. The user thinks in workstreams and wants execution + concise status, not clarification rounds.

**How to apply:** Reserve questions for genuine blockers (credentials, sudo actions, destructive choices, gated-dataset access). Still keep evidence grading and receive-only safety explicit. The user is fine with agents inspecting hardware/network and doing receive-only tests.
