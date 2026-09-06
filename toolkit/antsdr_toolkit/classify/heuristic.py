"""Score measured burst statistics against the signature table.

This is the first-stage classifier: no training, no model file, and every
decision traceable to a number in :mod:`antsdr_toolkit.classify.signatures`
and from there to a source.  It answers "what does this look like, and why"
rather than "what is this".

Method
------
Each signature constrains a handful of features (bandwidth, burst duration,
repetition interval, duty cycle, hop rate, number of distinct centres,
channel spacing).  A measured feature is compared with the signature's range
by a soft membership function that is 1.0 inside the range and falls off
*geometrically* outside it, because RF quantities span decades: being a
factor of two outside a range is the same kind of error at 500 kHz as at
20 MHz.  With ``tolerance`` = 3 (the default), a value a factor of three
beyond an edge scores 0.

The family score is the weighted mean of the memberships of the features
that are both constrained by the signature and available in the measurement.
Features the signature does not constrain are ignored, not treated as
matches, so a signature that constrains one feature cannot win on that alone:
:data:`MIN_FEATURES` sets how many must overlap before a family is scored at
all.

Band membership is a multiplier, never a veto (:data:`OUT_OF_BAND_FACTOR`).
Frontline-modified control links deliberately leave the ISM bands, and a
receiver that refuses to name a waveform because it appeared 40 MHz outside
its expected plan is worse than one that names it and says the band is
wrong.

Confidence is not probability
-----------------------------
The returned score is a similarity in ``[0, 1]``.  Several families overlap
heavily by construction (ExpressLRS packet rates differ only in timing;
Herelink and OcuSync differ only in the channel plan), so the top two scores
being close is information, not a defect - it is reported in ``margin``.
Anything below :data:`UNKNOWN_BELOW` returns the ``unknown`` candidate with
the near misses attached, which is what an open-set model would later be
trained to do properly.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ..dsp.bursts import Burst
from ..dsp.features import BurstFeatures, burst_features
from .signatures import SIGNATURES, Signature, signatures_for_band

__all__ = [
    "CONTRADICTION_CAP",
    "MIN_FEATURES",
    "OUT_OF_BAND_FACTOR",
    "UNKNOWN_BELOW",
    "Candidate",
    "classify",
    "classify_clusters",
    "membership",
]

#: A value this many times beyond a range edge scores zero.
DEFAULT_TOLERANCE = 3.0
#: Below this score the answer is "unknown", with the near misses attached.
UNKNOWN_BELOW = 0.35
#: Score multiplier when the measurement is outside the signature's bands.
OUT_OF_BAND_FACTOR = 0.6
#: Fewest overlapping *structural* features before a family may be scored.
MIN_FEATURES = 2

#: A feature that scores exactly zero is a contradiction, not a bad fit: the
#: measurement is more than ``tolerance`` times outside the range, or it is
#: zero where the family needs a positive value (a fixed-frequency emitter
#: against an FHSS family).  One contradiction caps the family's score below
#: :data:`UNKNOWN_BELOW`, so it stays visible as a near miss but can never be
#: the answer.  Without this a family can win on three matching features while
#: being definitionally impossible.
CONTRADICTION_CAP = 0.9 * UNKNOWN_BELOW

#: Features that carry identity on their own. The other two (duty cycle, hop
#: rate) are legitimately 0.0 for a fixed-frequency or sparse emitter, so a
#: family must never be selected on those alone: a "0 % duty cycle, 0 hops per
#: second" measurement matches half the table.
STRUCTURAL = ("bandwidth_hz", "duration_s", "interval_s",
              "center_spacing_hz", "n_distinct_centers")

#: Which :class:`~antsdr_toolkit.dsp.features.BurstFeatures` field feeds which
#: signature range.
FEATURE_FIELDS: Mapping[str, str] = {
    "bandwidth_hz": "bandwidth_median_hz",
    "duration_s": "duration_median_s",
    "interval_s": "interval_median_s",
    "duty_cycle": "duty_cycle",
    "hop_rate_hz": "hop_rate_hz",
    "n_distinct_centers": "n_distinct_centers",
    "center_spacing_hz": "center_spacing_median_hz",
}

#: Features that are meaningless when the measurement did not produce them.
#: ``burst_features`` reports 0.0 for undefined statistics, and 0.0 is a
#: legitimate value only for the duty cycle and the hop rate.
_ZERO_IS_MISSING = frozenset({
    "bandwidth_hz", "duration_s", "interval_s", "center_spacing_hz", "n_distinct_centers",
})


@dataclass(frozen=True)
class Candidate:
    """One family's score with the evidence that produced it."""

    family: str
    display: str
    score: float
    decodability: str
    confidence: str
    matched: tuple[str, ...]
    """Features that fell inside the signature's range."""
    mismatched: tuple[str, ...]
    """Features that fell outside it, worst first."""
    in_band: bool
    explanation: str
    per_feature: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "display": self.display,
            "score": round(float(self.score), 4),
            "decodability": self.decodability,
            "confidence": self.confidence,
            "matched": list(self.matched),
            "mismatched": list(self.mismatched),
            "in_band": bool(self.in_band),
            "explanation": self.explanation,
            "per_feature": {k: round(float(v), 4) for k, v in self.per_feature.items()},
        }


UNKNOWN = Candidate(
    family="unknown", display="unknown", score=0.0, decodability="detect_only",
    confidence="verified", matched=(), mismatched=(), in_band=True,
    explanation="no signature scored above the threshold",
)


def membership(value: float, low: float, high: float, *,
               tolerance: float = DEFAULT_TOLERANCE) -> float:
    """Soft membership of ``value`` in ``[low, high]``, geometric outside it.

    Returns 1.0 inside the range and decays to 0.0 a factor of ``tolerance``
    beyond either edge.  A measurement of exactly zero against a strictly
    positive lower bound scores 0.0: an emitter that did not hop at all is not
    "nearly" a family that hops eighty times a second, it is a different
    thing.  Where the *range* touches zero (a duty cycle, the hop rate of a
    fixed-frequency family) the decay is linear over ``tolerance`` times the
    range width instead, because a ratio to zero is undefined.
    """
    v, lo, hi = float(value), float(low), float(high)
    if not math.isfinite(v):
        return 0.0
    if lo <= v <= hi:
        return 1.0
    tol = max(float(tolerance), 1.0 + 1e-9)
    if v > hi:
        if hi > 0.0:
            return max(0.0, 1.0 - math.log10(v / hi) / math.log10(tol))
        width = max(hi - lo, 1e-12)
        return max(0.0, 1.0 - (v - hi) / (tol * width))
    if v < lo:
        if lo > 0.0:
            if v <= 0.0:
                return 0.0
            return max(0.0, 1.0 - math.log10(lo / v) / math.log10(tol))
        width = max(hi - lo, 1e-12)
        return max(0.0, 1.0 - (lo - v) / (tol * width))
    return 0.0


def _measured(features: BurstFeatures, extra: Mapping[str, float] | None) -> dict[str, float]:
    """Feature values keyed by signature-range name, missing ones left out."""
    out: dict[str, float] = {}
    undefined: set[str] = set()
    if features.n_bursts < 2:  # an interval and a hop rate need two bursts
        undefined |= {"interval_s", "hop_rate_hz", "center_spacing_hz"}
    if features.n_bursts < 1:
        undefined |= {"duty_cycle", "bandwidth_hz", "duration_s", "n_distinct_centers"}
    for range_name, field_name in FEATURE_FIELDS.items():
        if range_name in undefined:
            continue
        value = float(getattr(features, field_name))
        if range_name in _ZERO_IS_MISSING and value <= 0.0:
            continue
        out[range_name] = value
    if extra:
        for key, value in extra.items():
            if key in FEATURE_FIELDS and value is not None:
                out[key] = float(value)
    return out


def _explain(sig: Signature, measured: Mapping[str, float],
             per_feature: Mapping[str, float], in_band: bool) -> str:
    """One sentence naming the two strongest and the worst feature."""
    if not per_feature:
        return "no comparable features"
    ordered = sorted(per_feature.items(), key=lambda kv: -kv[1])
    good = [k for k, v in ordered if v >= 0.8][:2]
    worst = ordered[-1]
    parts: list[str] = []
    for name in good:
        parts.append(f"{_pretty(name, measured[name])} fits")
    if worst[1] <= 0.0:
        parts.append(f"ruled out by {_pretty(worst[0], measured[worst[0]])} "
                     f"({_range_text(sig, worst[0])} expected)")
    elif worst[1] < 0.8:
        parts.append(f"{_pretty(worst[0], measured[worst[0]])} does not "
                     f"({_range_text(sig, worst[0])} expected)")
    if not in_band:
        parts.append("outside the expected band")
    return "; ".join(parts) if parts else "all features fit"


def _pretty(name: str, value: float) -> str:
    if name.endswith("_hz") and name != "hop_rate_hz":
        return f"{name[:-3].replace('_', ' ')} {value / 1e6:.3g} MHz"
    if name == "hop_rate_hz":
        return f"hop rate {value:.4g} Hz"
    if name.endswith("_s"):
        return f"{name[:-2].replace('_', ' ')} {value * 1e3:.3g} ms"
    if name == "n_distinct_centers":
        return f"{value:.0f} distinct centres"
    return f"{name.replace('_', ' ')} {value:.3g}"


def _range_text(sig: Signature, name: str) -> str:
    rng = getattr(sig, name)
    if rng is None:
        return "no constraint"
    lo, hi = rng
    if name.endswith("_hz") and name != "hop_rate_hz":
        return f"{lo / 1e6:.3g}-{hi / 1e6:.3g} MHz"
    if name.endswith("_s"):
        return f"{lo * 1e3:.3g}-{hi * 1e3:.3g} ms"
    return f"{lo:.3g}-{hi:.3g}"


def _score_one(sig: Signature, measured: Mapping[str, float], band_hint: str | None,
               tolerance: float) -> Candidate | None:
    ranges = sig.constrained()
    per_feature: dict[str, float] = {}
    weights: dict[str, float] = {}
    for name, (lo, hi) in ranges.items():
        if name not in measured:
            continue
        per_feature[name] = membership(measured[name], lo, hi, tolerance=tolerance)
        weights[name] = sig.weight(name)
    structural_seen = sum(1 for name in per_feature if name in STRUCTURAL)
    if structural_seen < MIN_FEATURES:
        return None
    total_w = sum(weights.values())
    score = sum(per_feature[k] * weights[k] for k in per_feature) / total_w if total_w else 0.0
    in_band = band_hint is None or band_hint in sig.bands
    if not in_band:
        score *= OUT_OF_BAND_FACTOR
    contradictions = tuple(k for k, v in per_feature.items() if v <= 0.0)
    if contradictions:
        score = min(score, CONTRADICTION_CAP)
    matched = tuple(k for k, v in sorted(per_feature.items(), key=lambda kv: -kv[1]) if v >= 0.8)
    mismatched = tuple(k for k, v in sorted(per_feature.items(), key=lambda kv: kv[1]) if v < 0.8)
    return Candidate(
        family=sig.family, display=sig.display, score=float(score),
        decodability=sig.decodability, confidence=sig.confidence,
        matched=matched, mismatched=mismatched, in_band=in_band,
        explanation=_explain(sig, measured, per_feature, in_band),
        per_feature=per_feature,
    )


def classify(
    features: BurstFeatures,
    *,
    band_hint: str | None = None,
    extra: Mapping[str, float] | None = None,
    top_k: int = 5,
    tolerance: float = DEFAULT_TOLERANCE,
    signatures: Iterable[Signature] = SIGNATURES,
    restrict_to_band: bool = False,
) -> list[Candidate]:
    """Rank the signature table against one burst-set measurement.

    Parameters
    ----------
    features
        Output of :func:`antsdr_toolkit.dsp.features.burst_features`.
    band_hint
        Band id the measurement came from.  Signatures that do not list it
        are scored down by :data:`OUT_OF_BAND_FACTOR`, and dropped entirely
        only when ``restrict_to_band`` is set.
    extra
        Measurements the burst statistics do not carry, keyed like the
        signature ranges (for example ``{"duty_cycle": 1.0}`` from a
        continuous-carrier test).  These override the computed values.
    top_k
        How many candidates to return.

    Returns the candidates best first.  When the best score is below
    :data:`UNKNOWN_BELOW` the list starts with the ``unknown`` candidate and
    the near misses follow, so the caller always sees what it nearly was.
    """
    if top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {top_k}")
    measured = _measured(features, extra)
    pool = signatures_for_band(band_hint) if (restrict_to_band and band_hint) else signatures
    scored = [c for c in (_score_one(s, measured, band_hint, tolerance) for s in pool) if c]
    scored.sort(key=lambda c: (-c.score, c.family))
    best = scored[:top_k]
    if not best or best[0].score < UNKNOWN_BELOW:
        near = ", ".join(f"{c.display} {c.score:.2f}" for c in best[:3])
        unknown = Candidate(
            family="unknown", display="unknown", score=0.0,
            decodability="detect_only", confidence="verified",
            matched=(), mismatched=(), in_band=True,
            explanation=(f"no signature above {UNKNOWN_BELOW:.2f}"
                         + (f"; nearest: {near}" if near else "")),
        )
        return [unknown, *best]
    return best


def margin(candidates: Sequence[Candidate]) -> float:
    """Score gap between the top two candidates (0.0 when there is only one)."""
    real = [c for c in candidates if c.family != "unknown"]
    if len(real) < 2:
        return 0.0
    return float(real[0].score - real[1].score)


def classify_clusters(
    bursts: Sequence[Burst],
    *,
    window_s: float,
    center_tolerance_hz: float = 250e3,
    cluster_gap_hz: float = 5e6,
    bandwidth_ratio: float = 4.0,
    band_hint: str | None = None,
    extra: Mapping[str, float] | None = None,
    top_k: int = 3,
) -> list[tuple[BurstFeatures, list[Candidate]]]:
    """Split bursts into emitters, then classify each one separately.

    Two emitters in one dwell (a video downlink and a hopping control link,
    say) would otherwise be averaged into one meaningless feature vector.

    Grouping uses two properties, because centre frequency alone is not
    enough: a 9 MHz burst and a 0.8 MHz burst can share a centre and still be
    different emitters, and a wideband signal sitting across a hop set would
    chain every narrowband burst into one group.  A burst therefore joins a
    group only when its centre is within ``cluster_gap_hz`` of the group's
    nearest member *and* its bandwidth is within a factor of
    ``bandwidth_ratio`` of the group's median.  Hopping links stay together
    because their hops are much closer than the gap and their bursts are all
    the same width.

    Returns one ``(features, candidates)`` pair per group, most bursts first.
    """
    if not bursts:
        return []
    ordered = sorted(bursts, key=lambda b: b.center_freq_hz)
    groups: list[list[Burst]] = []
    for burst in ordered:
        placed = False
        for group in groups:
            near = min(abs(burst.center_freq_hz - other.center_freq_hz) for other in group)
            if near > float(cluster_gap_hz):
                continue
            widths = sorted(other.bandwidth_hz for other in group)
            median = widths[len(widths) // 2]
            ratio = max(burst.bandwidth_hz, median) / max(min(burst.bandwidth_hz, median), 1e-9)
            if ratio <= float(bandwidth_ratio):
                group.append(burst)
                placed = True
                break
        if not placed:
            groups.append([burst])
    out: list[tuple[BurstFeatures, list[Candidate]]] = []
    for group in sorted(groups, key=len, reverse=True):
        feats = burst_features(group, window_s=window_s,
                               center_tolerance_hz=center_tolerance_hz)
        out.append((feats, classify(feats, band_hint=band_hint, extra=extra, top_k=top_k)))
    return out
