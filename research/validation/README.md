# Validation record

The output of `../../VALIDATION_PLAN.md`: an independent re-audit of the
implementation before any time is spent flying drones, then validation against
public real recordings.

| File | What it holds |
|---|---|
| [baseline.md](baseline.md) | Phase 0. The exact commit, environment and test state being audited, taken before anything was changed. |
| [review-findings.md](review-findings.md) | Phase 2. One verdict per peer-review hypothesis H1 to H13, with the evidence on both sides. |
| [disputes.md](disputes.md) | Where this audit disagrees with the review, and why. A hypothesis that is wrong is as useful a finding as one that is right. |
| `datasets/` | Phase 3 and 4. Manifests for public datasets. No IQ in git. |
| `reports/` | Per-run outputs. |

The plan's rule, which this record follows: the hypotheses are things to test,
not conclusions to satisfy. Where the implementation is right and the review
is wrong, that is recorded and the implementation is left alone.
