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
| [0004](ADR-0004-firmware-personality-and-capture-tiers.md) | Firmware personality and capture tiers | Proposed |
| [0005](ADR-0005-processing-location.md) | Processing location: host first, board later | Proposed |
| [0006](ADR-0006-dji-three-tiers.md) | DJI links are handled in three tiers | Proposed |
| [0007](ADR-0007-detection-pipeline-heuristics-before-ml.md) | Burst features and heuristics before machine learning | Proposed |
| [0008](ADR-0008-relation-to-aerix-observation-contract.md) | Relation to the AERIX observation contract | Proposed |
| [0009](ADR-0009-localisation-deferred.md) | Localisation is deferred | Proposed |
| [0010](ADR-0010-band-coverage.md) | Band coverage | Accepted |
| [0011](ADR-0011-legal-posture.md) | Legal posture | Proposed |

The proposed records are the research phase's recommendations. Each names the
question in `../../QUESTIONS.md` whose answer turns it into Accepted or sends
it back for rework.

Template: `ADR-0000-template.md`.
