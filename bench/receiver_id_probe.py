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

Windows whose sidecar ``notes`` records ``rate_warning=True`` (S1.6 Q4:
"Dropped samples also spike flux, so the sidecar must carry a per-window
drop count and such windows must be excluded from the probe") are excluded
before feature extraction.

Usage::

    uv run python3 bench/receiver_id_probe.py \\
        --dataset zenodo_drone_rf_video_2020 --dataset aerix_antsdr_ambient_2026_09_18 \\
        --dataset rub_dronesecurity \\
        --report bench/out/receiver_id_probe.md

Exit codes: 0 pass/conditional (or a variant simply not runnable, exit 3,
see above), 1 fail (label-matched probe balanced accuracy > chance + 0.25),
2 unexpected error, 3 label-matched probe not runnable.
"""

from __future__ import annotations

import argparse
import json
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

# G3 is never valid in this probe (no stored detector frames) -- excluded
# from the feature matrix and from permutation-importance reporting.
_USABLE_MASK = np.array(
    [not (G3_SLICE.start <= i < G3_SLICE.stop) for i in range(FEATURES_V2_DIM)]
)
USABLE_FEATURE_NAMES = tuple(n for n, keep in zip(FEATURE_NAMES, _USABLE_MASK) if keep)


@dataclass
class Row:
    dataset_id: str
    device_id: str
    run_id: str
    emitter_class: str
    vector: np.ndarray  # usable features only, float32 [len(USABLE_FEATURE_NAMES)]


def _has_rate_warning(sc: WindowSidecar) -> bool:
    return bool(sc.notes) and "rate_warning=True" in sc.notes


def _emitter_class(sc: WindowSidecar) -> str:
    return sc.labels.window.emitter_class.value


def load_rows(dataset_ids: list[str], root: Path | None = None, limit_per_dataset: int | None = None) -> tuple[list[Row], dict]:
    """Load prepared index rows for ``dataset_ids``, compute ``features_v2``
    per row (``detector_frames_lin=None`` -- see module docstring), and skip
    rate_warning windows. Returns ``(rows, skip_counts)``."""
    root = root if root is not None else dataset_root()
    rows: list[Row] = []
    skipped = Counter()
    for dsid in dataset_ids:
        n_loaded = 0
        for sc in iter_dataset(dsid, root=root):
            if limit_per_dataset is not None and n_loaded >= limit_per_dataset:
                break
            if _has_rate_warning(sc):
                skipped[f"{dsid}:rate_warning"] += 1
                continue
            tensor_path = root / dsid / "prepared" / f"{sc.identity.uid}.tensor.npy"
            if not tensor_path.exists():
                skipped[f"{dsid}:missing_tensor"] += 1
                continue
            tensor = np.load(tensor_path)
            try:
                feats = extract_features_v2(tensor, None, fs_hz=sc.signal.sample_rate_hz)
            except ValueError as exc:
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
class ProbeResult:
    variant: str
    runnable: bool
    reason: str = ""
    n_rows: int = 0
    n_groups: int = 0
    n_classes: int = 0
    chance: float = 0.0
    balanced_accuracy_logreg: float = 0.0
    balanced_accuracy_gboost: float = 0.0
    balanced_accuracy_best: float = 0.0
    verdict: str = ""
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
    group_key``)."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.model_selection import GroupKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

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

    n_splits = min(5, n_groups)
    if n_splits < 2:
        return ProbeResult(
            variant=variant, runnable=False,
            reason=f"only {n_groups} distinct group(s) present, need >=2 for GroupKFold",
            n_rows=len(rows), n_groups=n_groups, n_classes=n_classes, chance=chance,
            class_counts=class_counts,
        )

    gkf = GroupKFold(n_splits=n_splits)

    logreg = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, random_state=RANDOM_STATE),
    )
    gboost = GradientBoostingClassifier(random_state=RANDOM_STATE)

    pred_lr = cross_val_predict(logreg, X, y, cv=gkf, groups=groups)
    pred_gb = cross_val_predict(gboost, X, y, cv=gkf, groups=groups)

    ba_lr = float(balanced_accuracy_score(y, pred_lr))
    ba_gb = float(balanced_accuracy_score(y, pred_gb))
    ba_best = max(ba_lr, ba_gb)

    # Permutation importance from a single fit of the best-performing model
    # on the full data (diagnostic only, not a held-out estimate).
    best_model = gboost if ba_gb >= ba_lr else logreg
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
        n_rows=len(rows), n_groups=n_groups, n_classes=n_classes, chance=chance,
        balanced_accuracy_logreg=ba_lr, balanced_accuracy_gboost=ba_gb,
        balanced_accuracy_best=ba_best, verdict=_verdict(ba_best, chance),
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
        lines.append(f"- balanced accuracy, logistic regression: {res.balanced_accuracy_logreg:.4f}")
        lines.append(f"- balanced accuracy, gradient boosting: {res.balanced_accuracy_gboost:.4f}")
        lines.append(f"- balanced accuracy, best of the two: {res.balanced_accuracy_best:.4f}")
        lines.append(
            f"- margin over chance: {res.balanced_accuracy_best - res.chance:+.4f} "
            f"-> **{res.verdict.upper()}** (pass <= +0.10, conditional <= +0.25, else fail)"
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
        "runnable or while it fails (S2 of the design doc)."
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
