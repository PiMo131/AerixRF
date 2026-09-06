"""Signal-family classification: the signature table and the heuristic scorer.

``signatures`` holds the on-air parameters the research phase established,
one row per link family with its sources; ``heuristic`` scores measured
burst statistics against them without any training.  See
``antsdr/docs/decisions/ADR-0007`` for why the first classifier is rule-based.
"""

from .heuristic import Candidate, classify, classify_clusters, margin, membership
from .signatures import SIGNATURES, Signature, by_family, families, signatures_for_band

__all__ = [
    "SIGNATURES",
    "Candidate",
    "Signature",
    "by_family",
    "classify",
    "classify_clusters",
    "families",
    "margin",
    "membership",
    "signatures_for_band",
]
