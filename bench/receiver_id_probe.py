"""F2 -- receiver-ID probe (mandatory control), ``docs/design/features-and-benchmark.md`` S2.

Trains a small grouped-CV classifier on ``features_v2`` to predict
``dataset_id`` (used here as a proxy for "which receiver produced this
window" -- see the caveat below) and reports balanced accuracy against
chance. Two variants:

1. UNRESTRICTED (all windows, upper bound only): ``dataset_id`` is
   confounded with emitter content (Zenodo = drones in an anechoic
   chamber, ANTSDR = Wi-Fi ambient), so high accuracy here may be real
   signal difference, not device leakage. Always runs if >=2 datasets/groups
   are present.
2. LABEL-MATCHED (isolates device confound): restricted to windows sharing
   one ``emitter_class`` label across >=2 datasets. As of this pass only
   ``background`` exists, and only from one receiver (ANTSDR) -- the probe
   detects this and refuses to run with a clear message and exit code 3,
   per the design doc: "no cross-receiver claim may be made while the probe
   fails" applies equally to "cannot be run".

Caveat printed in every report: this probe uses ``dataset_id`` as the
receiver-ID label because every window in the local corpus with 1.0 s
windows carries at most one receiver per dataset (Zenodo: unknown 3rd-party
SDR; ANTSDR: our E200 sessions; RUB: unknown 3rd-party SDR) -- it is not a
receiver_id field distinct from dataset_id in the current sidecar schema.

Detector frames are not stored in the prepared corpus (only the 30-average
``<uid>.tensor.npy``), so every window is scored with
``detector_frames_lin=None``; G3 (occupancy/cadence) is therefore always
``valid_mask=False`` in this probe and is excluded from the leak-importance
listing (it is already excluded from the classifier by construction, since
its feature values are simply zero for every row -- see ``_load_features``).

**2026-09-18 revision, design doc S5.4/S5.5: previous PASS withdrawn (fold
artefact).** The prior report (``GroupKFold``, pooled balanced accuracy,
``margin <= +0.10 -> PASS``) reported the unrestricted probe as PASS at BA
0.4342 (margin -0.0658 vs chance). That evaluation was broken:
``GroupKFold`` balances folds by *row count*, not by class, so one fold held
100% of one class (the single dominant ANTSDR session, 298/338 ambient
rows) and contributed nothing to the other class's recall term; a BA below
chance measured session-level domain shift, not the absence of a device
fingerprint, and the pass/conditional/fail thresholds were never designed to
treat "below chance" as informative. This revision replaces ``GroupKFold``
with ``StratifiedGroupKFold``, adds a per-fold class-count guard (dropping
and reporting under-powered folds instead of silently pooling them),
subsamples the dominant class within each fold's training data, and adds an
**INCONCLUSIVE** verdict for BA below chance, fewer than 2 valid folds, or
any dropped fold -- INCONCLUSIVE is not on the exit-code-0 (pass) path.

Windows whose sidecar session shows a real sample-rate deficit are excluded
before feature extraction (design doc S5.5): the old ``rate_warning=True``
string-match in ``notes`` is a *trailing-window* rate estimate that
false-positives on loss-free sessions (median ratio 0.96-1.01 across most
sessions despite the flag firing on individual windows). The rule here
instead prefers a typed ``receiver.window_deficit_frac`` /
``receiver.samples_deficit`` field if the sidecar has one (window > 1e-3 or
session > 1e-2 excludes), and otherwise falls back to the **session-level**
(``run_id``) median ``stream_rate_ratio=`` parsed from ``notes`` (< 0.95
excludes) -- this keeps loss-free sessions whose per-window metric fired
spuriously and drops only the session with a real deficit.

Usage::

    uv run python3 bench/receiver_id_probe.py \\
        --dataset zenodo_drone_rf_video_2020 --dataset aerix_antsdr_ambient_2026_09_18 \\
        --dataset rub_dronesecurity \\
        --report bench/out/receiver_id_probe.md

Exit codes: 0 pass/conditional (or a variant simply not runnable, exit 3,
see above), 1 fail or INCONCLUSIVE (label-matched probe balanced accuracy >
chance + 0.25, or the probe could not produce an informative result -- see
the INCONCLUSIVE conditions above), 2 unexpected error, 3 label-matched
probe not runnable.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aerix_rf.classify.features_v2 import (  # noqa: E402
    FEATURE_NAMES,
    FEATURES_V2_DIM,
    G3_SLICE,
    extract_features_v2,
)
from aerix_rf.datasets.index import dataset_root, iter_dataset  # noqa: E402
from aerix_rf.datasets.spec import WindowSidecar  # noqa: E402

PASS_MARGIN = 0.10
CONDITIONAL_MARGIN = 0.25
RANDOM_STATE = 0

# S5.4 fold guard: a fold is dropped (and the whole probe verdict becomes
# INCONCLUSIVE, S5.4) unless it has at least this many distinct groups on
# the train side and at least this many rows of *every* class on both the
# train and test side.
MIN_GROUPS_PER_FOLD = 2
MIN_ROWS_PER_CLASS = 5
# Majority-class subsampling within each fold's training data, S5.4: cap the
# largest class at this multiple of the smallest class's row count.
MAJORITY_SUBSAMPLE_RATIO = 4.0
# S5.5 session-level sample-rate-deficit exclusion (notes fallback path).
SESSION_RATE_RATIO_MIN = 0.95

# G3 is never valid in this probe (no stored detector frames) -- excluded
# from the feature matrix and from permutation-importance reporting.
_USABLE_MASK = np.array(
    [not (G3_SLICE.start <= i < G3_SLICE.stop) for i in range(FEATURES_V2_DIM)]
)
USABLE_FEATURE_NAMES = tuple(n for n, keep in zip(FEATURE_NAMES, _USABLE_MASK) if keep)

_RATE_RATIO_RE = re.compile(r"stream_rate_ratio=([0-9.]+)")


@dataclass
class Row:
    dataset_id: str
    device_id: str
    run_id: str
    emitter_class: str
    vector: np.ndarray  # usable features only, float32 [len(USABLE_FEATURE_NAMES)]


def _rate_ratio_from_notes(sc: WindowSidecar) -> float | None:
    if not sc.notes:
        return None
    m = _RATE_RATIO_RE.search(sc.notes)
    return float(m.group(1)) if m else None


def _typed_deficits(sc: WindowSidecar) -> tuple[float | None, float | None]:
    """``(window_deficit_frac, session samples_deficit)`` from typed sidecar
    fields if present -- forward-compat with a builder adding
    ``receiver.window_deficit_frac`` / ``receiver.samples_deficit``. Returns
    ``(None, None)`` if neither typed field exists on this sidecar, in which
    case callers fall back to the ``notes`` ``stream_rate_ratio=`` rule."""
    recv = getattr(sc, "receiver", None)
    if recv is None:
        return None, None
    return getattr(recv, "window_deficit_frac", None), getattr(recv, "samples_deficit", None)


def _session_rate_ratio_medians(dataset_id: str, root: Path) -> dict[str, float]:
    """Pre-scan pass (no tensor load): per-``run_id`` (session) median
    ``stream_rate_ratio`` parsed from ``notes``. Replaces the old
    ``rate_warning=True`` string-match, which fired on a *trailing-window*
    rate estimate that dips transiently on otherwise loss-free sessions
    (design doc S5.5)."""
    ratios: dict[str, list[float]] = defaultdict(list)
    for sc in iter_dataset(dataset_id, root=root):
        r = _rate_ratio_from_notes(sc)
        if r is not None:
            ratios[sc.identity.run_id].append(r)
    return {run_id: float(np.median(vals)) for run_id, vals in ratios.items() if vals}


def _rate_deficit_reason(sc: WindowSidecar, session_ratio_medians: dict[str, float]) -> str | None:
    """Exclusion reason string, or ``None`` to keep the row. Prefers typed
    ``receiver.window_deficit_frac`` / ``receiver.samples_deficit`` if
    present (window > 1e-3 or session > 1e-2 excludes); else falls back to
    the session-level (``run_id``) median ``stream_rate_ratio`` from
    ``notes`` (< 0.95 excludes -- a real session-wide deficit, not a
    spurious per-window rate estimate)."""
    window_d, session_d = _typed_deficits(sc)
    if window_d is not None or session_d is not None:
        if window_d is not None and window_d > 1e-3:
            return "window_samples_deficit"
        if session_d is not None and session_d > 1e-2:
            return "session_samples_deficit"
        return None
    median = session_ratio_medians.get(sc.identity.run_id)
    if median is not None and median < SESSION_RATE_RATIO_MIN:
        return "session_rate_ratio_lt_0.95"
    return None


def _emitter_class(sc: WindowSidecar) -> str:
    return sc.labels.window.emitter_class.value


def load_rows(dataset_ids: list[str], root: Path | None = None, limit_per_dataset: int | None = None) -> tuple[list[Row], dict]:
    """Load prepared index rows for ``dataset_ids``, compute ``features_v2``
    per row (``detector_frames_lin=None`` -- see module docstring), and skip
    windows with a real sample-rate deficit (S5.5; see
    ``_rate_deficit_reason``). Returns ``(rows, skip_counts)``."""
    root = root if root is not None else dataset_root()
    rows: list[Row] = []
    skipped = Counter()
    for dsid in dataset_ids:
        session_ratio_medians = _session_rate_ratio_medians(dsid, root)
        n_loaded = 0
        for sc in iter_dataset(dsid, root=root):
            if limit_per_dataset is not None and n_loaded >= limit_per_dataset:
                break
            reason = _rate_deficit_reason(sc, session_ratio_medians)
            if reason is not None:
                skipped[f"{dsid}:{reason}"] += 1
                continue
            tensor_path = root / dsid / "prepared" / f"{sc.identity.uid}.tensor.npy"
            if not tensor_path.exists():
                skipped[f"{dsid}:missing_tensor"] += 1
                continue
            tensor = np.load(tensor_path)
            try:
                feats = extract_features_v2(tensor, None, fs_hz=sc.signal.sample_rate_hz)
            except ValueError:
                skipped[f"{dsid}:extract_error"] += 1
                continue
            vec = feats.vector[_USABLE_MASK]
            rows.append(
                Row(
                    dataset_id=dsid,
                    device_id=sc.identity.device_id,
                    run_id=sc.identity.run_id,
                    emitter_class=_emitter_class(sc),
                    vector=vec,
                )
            )
            n_loaded += 1
    return rows, dict(skipped)


@dataclass
class FoldSummary:
    fold: int
    dropped: bool
    reasons: list[str] = field(default_factory=list)
    n_train: int = 0
    n_test: int = 0
    train_groups: int = 0
    test_groups: int = 0
    confusion_lr: list[list[int]] = field(default_factory=list)
    confusion_gb: list[list[int]] = field(default_factory=list)
    recall_lr: dict = field(default_factory=dict)
    recall_gb: dict = field(default_factory=dict)


@dataclass
class ProbeResult:
    variant: str
    runnable: bool
    reason: str = ""
    n_rows: int = 0
    n_groups: int = 0
    n_classes: int = 0
    classes: list = field(default_factory=list)
    chance: float = 0.0
    balanced_accuracy_logreg: float = 0.0
    balanced_accuracy_gboost: float = 0.0
    balanced_accuracy_best: float = 0.0
    verdict: str = ""
    verdict_detail: str = ""
    n_folds_total: int = 0
    n_folds_valid: int = 0
    n_folds_dropped: int = 0
    dropped_fold_reasons: list[str] = field(default_factory=list)
    fold_summaries: list[FoldSummary] = field(default_factory=list)
    top_importance: list[tuple[str, float]] = field(default_factory=list)
    class_counts: dict = field(default_factory=dict)


def _verdict(best_ba: float, chance: float) -> str:
    margin = best_ba - chance
    if margin <= PASS_MARGIN:
        return "pass"
    if margin <= CONDITIONAL_MARGIN:
        return "conditional"
    return "fail"


def run_probe(rows: list[Row], variant: str) -> ProbeResult:
    """Grouped-CV classifier predicting ``dataset_id`` from usable
    ``features_v2``. Group key = ``(dataset_id, device_id, run_id)`` (same
    leakage-safe group as the rest of the pipeline, ``datasets/index.py:
    group_key``).

    S5.4 revision: ``StratifiedGroupKFold`` (not ``GroupKFold``), a per-fold
    guard that drops under-powered folds (and forces verdict
    ``INCONCLUSIVE`` when it does), ``class_weight="balanced"`` /
    class-balanced ``sample_weight``, majority-class train subsampling
    capped at ``MAJORITY_SUBSAMPLE_RATIO``x the minority class, and
    per-fold confusion matrices / per-class recall in addition to pooled
    balanced accuracy."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score, confusion_matrix, recall_score
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.utils.class_weight import compute_sample_weight

    labels = [r.dataset_id for r in rows]
    classes = sorted(set(labels))
    n_classes = len(classes)
    class_counts = dict(Counter(labels))

    if n_classes < 2:
        return ProbeResult(
            variant=variant, runnable=False,
            reason=f"only {n_classes} distinct dataset_id(s) present: {classes}",
            class_counts=class_counts,
        )

    X = np.stack([r.vector for r in rows]).astype(np.float64)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    y = np.array(labels)
    groups = np.array([f"{r.dataset_id}\x1f{r.device_id}\x1f{r.run_id}" for r in rows])
    n_groups = len(set(groups.tolist()))
    chance = 1.0 / n_classes

    if n_groups < 2:
        return ProbeResult(
            variant=variant, runnable=False,
            reason=f"only {n_groups} distinct group(s) present, need >=2 for grouped CV",
            n_rows=len(rows), n_groups=n_groups, n_classes=n_classes, classes=classes, chance=chance,
            class_counts=class_counts,
        )

    n_splits = min(5, n_groups)
    if n_splits < 2:
        return ProbeResult(
            variant=variant, runnable=False,
            reason=f"only {n_groups} distinct group(s) present, need >=2 for StratifiedGroupKFold",
            n_rows=len(rows), n_groups=n_groups, n_classes=n_classes, classes=classes, chance=chance,
            class_counts=class_counts,
        )

    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)

    fold_summaries: list[FoldSummary] = []
    oof_true: list = []
    oof_pred_lr: list = []
    oof_pred_gb: list = []

    for fold_idx, (train_idx, test_idx) in enumerate(sgkf.split(X, y, groups)):
        fs = FoldSummary(
            fold=fold_idx, dropped=False, n_train=len(train_idx), n_test=len(test_idx),
            train_groups=len(set(groups[train_idx].tolist())),
            test_groups=len(set(groups[test_idx].tolist())),
        )
        reasons: list[str] = []
        if fs.train_groups < MIN_GROUPS_PER_FOLD:
            reasons.append(f"train groups={fs.train_groups} < {MIN_GROUPS_PER_FOLD}")
        train_counts = Counter(y[train_idx].tolist())
        test_counts = Counter(y[test_idx].tolist())
        for c in classes:
            if train_counts.get(c, 0) < MIN_ROWS_PER_CLASS:
                reasons.append(f"train class={c!r} rows={train_counts.get(c, 0)} < {MIN_ROWS_PER_CLASS}")
            if test_counts.get(c, 0) < MIN_ROWS_PER_CLASS:
                reasons.append(f"test class={c!r} rows={test_counts.get(c, 0)} < {MIN_ROWS_PER_CLASS}")
        if reasons:
            fs.dropped = True
            fs.reasons = reasons
            fold_summaries.append(fs)
            continue

        # Majority-class subsampling within this fold's training data only
        # (test is untouched): cap each class at MAJORITY_SUBSAMPLE_RATIO x
        # the smallest class's row count in this fold's training split.
        min_count = min(train_counts.values())
        cap = int(round(min_count * MAJORITY_SUBSAMPLE_RATIO))
        rng = np.random.default_rng(RANDOM_STATE + fold_idx)
        keep_parts = []
        for c in classes:
            idx_c = train_idx[y[train_idx] == c]
            if len(idx_c) > cap:
                idx_c = rng.choice(idx_c, size=cap, replace=False)
            keep_parts.append(idx_c)
        train_idx_sub = np.concatenate(keep_parts)

        Xtr, ytr = X[train_idx_sub], y[train_idx_sub]
        Xte, yte = X[test_idx], y[test_idx]

        logreg = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE),
        )
        logreg.fit(Xtr, ytr)
        pred_lr = logreg.predict(Xte)

        sw = compute_sample_weight("balanced", ytr)
        gboost = GradientBoostingClassifier(random_state=RANDOM_STATE)
        gboost.fit(Xtr, ytr, sample_weight=sw)
        pred_gb = gboost.predict(Xte)

        fs.confusion_lr = confusion_matrix(yte, pred_lr, labels=classes).tolist()
        fs.confusion_gb = confusion_matrix(yte, pred_gb, labels=classes).tolist()
        rec_lr = recall_score(yte, pred_lr, labels=classes, average=None, zero_division=0)
        rec_gb = recall_score(yte, pred_gb, labels=classes, average=None, zero_division=0)
        fs.recall_lr = {c: float(r) for c, r in zip(classes, rec_lr)}
        fs.recall_gb = {c: float(r) for c, r in zip(classes, rec_gb)}
        fold_summaries.append(fs)

        oof_true.extend(yte.tolist())
        oof_pred_lr.extend(pred_lr.tolist())
        oof_pred_gb.extend(pred_gb.tolist())

    n_dropped = sum(1 for fs in fold_summaries if fs.dropped)
    n_valid = len(fold_summaries) - n_dropped
    dropped_reasons = [f"fold {fs.fold}: {'; '.join(fs.reasons)}" for fs in fold_summaries if fs.dropped]

    if n_valid == 0 or not oof_true:
        return ProbeResult(
            variant=variant, runnable=True, n_rows=len(rows), n_groups=n_groups,
            n_classes=n_classes, classes=classes, chance=chance,
            verdict="inconclusive", verdict_detail="no valid folds after per-fold guards",
            n_folds_total=len(fold_summaries), n_folds_valid=n_valid, n_folds_dropped=n_dropped,
            dropped_fold_reasons=dropped_reasons, fold_summaries=fold_summaries, class_counts=class_counts,
        )

    ba_lr = float(balanced_accuracy_score(oof_true, oof_pred_lr))
    ba_gb = float(balanced_accuracy_score(oof_true, oof_pred_gb))
    ba_best = max(ba_lr, ba_gb)

    if n_dropped > 0:
        verdict = "inconclusive"
        verdict_detail = f"{n_dropped} fold(s) dropped by the per-fold guard (see dropped folds above)"
    elif n_valid < 2:
        verdict = "inconclusive"
        verdict_detail = f"only {n_valid} valid fold(s) remain, need >=2"
    elif ba_best < chance:
        verdict = "inconclusive"
        verdict_detail = f"balanced accuracy {ba_best:.4f} < chance {chance:.4f} (anti-correlated boundary, not evidence of fairness)"
    else:
        verdict = _verdict(ba_best, chance)
        verdict_detail = f"margin {ba_best - chance:+.4f} over chance"

    # Permutation importance: diagnostic full-data fit (not a held-out
    # estimate), class-balanced, no per-fold subsampling.
    if ba_gb >= ba_lr:
        sw_full = compute_sample_weight("balanced", y)
        best_model = GradientBoostingClassifier(random_state=RANDOM_STATE)
        best_model.fit(X, y, sample_weight=sw_full)
    else:
        best_model = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE),
        )
        best_model.fit(X, y)
    try:
        pi = permutation_importance(
            best_model, X, y, n_repeats=8, random_state=RANDOM_STATE, scoring="balanced_accuracy"
        )
        order = np.argsort(pi.importances_mean)[::-1][:15]
        top = [(USABLE_FEATURE_NAMES[i], float(pi.importances_mean[i])) for i in order]
    except Exception:
        top = []

    return ProbeResult(
        variant=variant, runnable=True,
        n_rows=len(rows), n_groups=n_groups, n_classes=n_classes, classes=classes, chance=chance,
        balanced_accuracy_logreg=ba_lr, balanced_accuracy_gboost=ba_gb,
        balanced_accuracy_best=ba_best, verdict=verdict, verdict_detail=verdict_detail,
        n_folds_total=len(fold_summaries), n_folds_valid=n_valid, n_folds_dropped=n_dropped,
        dropped_fold_reasons=dropped_reasons, fold_summaries=fold_summaries,
        top_importance=top, class_counts=class_counts,
    )


def label_matched_subset(rows: list[Row]) -> tuple[list[Row], str | None]:
    """Find an ``emitter_class`` present in >=2 distinct ``dataset_id``
    values, restrict to it. Returns ``(subset, label)``; ``label`` is
    ``None`` if no such class exists."""
    by_class: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        by_class[r.emitter_class].add(r.dataset_id)
    matched = {c: ds for c, ds in by_class.items() if len(ds) >= 2}
    if not matched:
        return [], None
    # Prefer the class with the most distinct datasets, then most rows.
    label = max(matched, key=lambda c: (len(matched[c]), sum(1 for r in rows if r.emitter_class == c)))
    subset = [r for r in rows if r.emitter_class == label]
    return subset, label


def _single_receiver_classes(rows: list[Row]) -> dict[str, list[str]]:
    by_class: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        by_class[r.emitter_class].add(r.dataset_id)
    return {c: sorted(ds) for c, ds in by_class.items() if len(ds) == 1}


def render_report(
    dataset_ids: list[str],
    rows: list[Row],
    skip_counts: dict,
    unrestricted: ProbeResult,
    label_matched: ProbeResult | None,
    label_matched_reason: str,
    elapsed_s: float,
) -> str:
    lines = []
    lines.append("# F2 receiver-ID probe report")
    lines.append("")
    lines.append(
        "**Previous PASS withdrawn: fold artefact (S5.4).** An earlier run of this report used "
        "`GroupKFold` and reported the unrestricted probe as PASS (BA 0.4342, margin -0.0658). "
        "`GroupKFold` balances folds by row count, not by class, so one fold held ~100% of the "
        "dominant ANTSDR session and contributed nothing to the other class's recall; a "
        "below-chance BA measured session-level domain shift, not an absence of device leakage. "
        "This report now uses `StratifiedGroupKFold` with a per-fold class-count guard, "
        "class-balanced weighting, majority-class subsampling and an INCONCLUSIVE verdict -- see "
        "the per-fold detail and verdict below for the current (re-evaluated) result."
    )
    lines.append("")
    lines.append(f"Datasets: {', '.join(dataset_ids)}")
    lines.append(f"Total usable rows loaded: {len(rows)}; wall time: {elapsed_s:.1f} s")
    if skip_counts:
        lines.append(f"Skipped: {skip_counts}")
    lines.append("")
    lines.append(
        "**Caveat.** This probe uses `dataset_id` as the receiver-ID label -- the prepared "
        "corpus has at most one receiver per dataset (Zenodo: third-party SDR, unknown; "
        "ANTSDR ambient: our E200; RUB: third-party SDR, unknown), so `dataset_id` and "
        "`receiver_id` are equivalent here but this is not a distinct `receiver_id` field."
    )
    lines.append("")
    lines.append(
        "**G3 caveat.** Detector frames are not stored in the prepared corpus (only the "
        "30-average `<uid>.tensor.npy`), so every window here is scored with "
        "`detector_frames_lin=None`. G3 (occupancy/cadence, 12 dims) is therefore always "
        "invalid and is excluded from the feature matrix and from permutation importance "
        "in this probe -- **G3 is not evaluated here**."
    )
    lines.append("")

    def _section(title: str, res: ProbeResult | None, extra_note: str = "") -> None:
        lines.append(f"## {title}")
        lines.append("")
        if extra_note:
            lines.append(extra_note)
            lines.append("")
        if res is None or not res.runnable:
            reason = res.reason if res is not None else "not run"
            lines.append(f"**Not runnable.** {reason}")
            lines.append("")
            return
        lines.append(f"- rows: {res.n_rows}, groups: {res.n_groups}, classes: {res.n_classes} ({res.class_counts})")
        lines.append(f"- chance (1/K): {res.chance:.4f}")
        lines.append(
            f"- folds: {res.n_folds_total} total, {res.n_folds_valid} valid, {res.n_folds_dropped} dropped"
        )
        if res.dropped_fold_reasons:
            lines.append("- dropped fold detail:")
            for r in res.dropped_fold_reasons:
                lines.append(f"  - {r}")
        lines.append(f"- balanced accuracy, logistic regression (pooled valid folds): {res.balanced_accuracy_logreg:.4f}")
        lines.append(f"- balanced accuracy, gradient boosting (pooled valid folds): {res.balanced_accuracy_gboost:.4f}")
        lines.append(f"- balanced accuracy, best of the two: {res.balanced_accuracy_best:.4f}")
        verdict_label = res.verdict.upper() if res.verdict else "N/A"
        lines.append(
            f"- **{verdict_label}** -- {res.verdict_detail} "
            f"(pass <= chance+0.10, conditional <= chance+0.25, fail otherwise; INCONCLUSIVE overrides "
            f"all thresholds when BA < chance, <2 valid folds remain, or any fold was dropped by the guard)"
        )
        lines.append("")
        if res.fold_summaries:
            kept = [fs for fs in res.fold_summaries if not fs.dropped]
            if kept:
                lines.append(f"Per-fold detail (kept folds only; class order {res.classes}):")
                lines.append("")
                lines.append("| fold | n_train | n_test | train groups | test groups | confusion (logreg) | recall (logreg) | confusion (gboost) | recall (gboost) |")
                lines.append("|---|---|---|---|---|---|---|---|---|")
                for fs in kept:
                    lines.append(
                        f"| {fs.fold} | {fs.n_train} | {fs.n_test} | {fs.train_groups} | {fs.test_groups} | "
                        f"{fs.confusion_lr} | {fs.recall_lr} | {fs.confusion_gb} | {fs.recall_gb} |"
                    )
                lines.append("")
        if res.top_importance:
            lines.append("Permutation importance, top 15 (best model, full-data fit, diagnostic only):")
            lines.append("")
            lines.append("| rank | feature | importance |")
            lines.append("|---|---|---|")
            for i, (name, imp) in enumerate(res.top_importance, 1):
                lines.append(f"| {i} | `{name}` | {imp:.5f} |")
            lines.append("")

    _section(
        "Unrestricted probe (upper bound only, confounded with content)",
        unrestricted,
        "`dataset_id` is confounded with emitter content (Zenodo = drones in an anechoic "
        "chamber, ANTSDR = Wi-Fi ambient): a high number here may be real signal difference, "
        "not device leakage. This variant does not by itself support or refute a cross-receiver "
        "claim.",
    )
    _section(
        "Label-matched probe (isolates device confound -- the one that matters)",
        label_matched,
        label_matched_reason,
    )

    lines.append(
        "No cross-receiver claim may be made from the label-matched probe while it is not "
        "runnable, while it fails, or while it is INCONCLUSIVE (S2/S5.4 of the design doc)."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", dest="datasets", required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--limit-per-dataset", type=int, default=None)
    parser.add_argument("--report", type=Path, default=Path("bench/out/receiver_id_probe.md"))
    args = parser.parse_args(argv)

    t0 = time.monotonic()
    rows, skip_counts = load_rows(args.datasets, root=args.root, limit_per_dataset=args.limit_per_dataset)
    if not rows:
        print("receiver_id_probe: no rows loaded, nothing to do", file=sys.stderr)
        return 2

    unrestricted = run_probe(rows, "unrestricted")

    subset, matched_label = label_matched_subset(rows)
    single_receiver = _single_receiver_classes(rows)
    if matched_label is None:
        reason_bits = ", ".join(f"{c} exists for receivers {ds} only" for c, ds in sorted(single_receiver.items()))
        reason = f"label-matched probe not runnable: {reason_bits}" if reason_bits else \
            "label-matched probe not runnable: no emitter_class shared by >=2 datasets"
        print(reason, file=sys.stderr)
        print(reason)
        label_matched_result = None
        exit_code = 3
    else:
        label_matched_result = run_probe(subset, "label_matched")
        reason = f"restricted to emitter_class={matched_label!r} ({label_matched_result.n_rows} rows)"
        exit_code = 0 if (not label_matched_result.runnable or label_matched_result.verdict in ("pass", "conditional")) else 1

    elapsed = time.monotonic() - t0
    report_md = render_report(
        args.datasets, rows, skip_counts, unrestricted, label_matched_result, reason, elapsed,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_md, encoding="utf-8")
    print(report_md)
    print(f"\nReport written to {args.report}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
