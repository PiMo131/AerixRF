# Design decisions (ADRs)

Every non-obvious choice in `antsdr/` is recorded here as a short Architecture
Decision Record so that later work can see *why* something is the way it is,
and can reverse it deliberately instead of by accident.

| Status | Meaning |
|---|---|
| **Accepted** | In force. Change it with a new ADR that supersedes this one. |
| **Proposed** | Recommended by the research phase, waiting for the maintainer's answer (see `../../QUESTIONS.md`). |
| **Superseded** | Replaced; the record stays for history. |

| ADR | Title | Status |
|---|---|---|
| [0001](ADR-0001-passive-receive-only.md) | Passive receive only | Accepted |
| [0002](ADR-0002-sigmf-recordings.md) | Every IQ recording is SigMF with metadata and truth annotations | Accepted |
| [0003](ADR-0003-third-party-code-and-licences.md) | Third-party code: reuse by licence, otherwise re-implement the wire format | Accepted |

Further ADRs (processing location, firmware personality, relation to the AERIX
observation contract, classifier strategy, direction finding) are written once
the research findings in `../../research/` are in and the open questions are
answered.

Template: `ADR-0000-template.md`.
