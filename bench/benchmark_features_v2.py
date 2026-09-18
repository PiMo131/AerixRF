"""F3 -- cross-receiver / cross-dataset benchmark runner for ``features_v2``,
``docs/design/features-and-benchmark.md`` S3 (tiers) and S4 (F3).

Runs tiers A, B and D over the prepared window store (see the design doc for
why: Zenodo has no in-dataset negative class, RUB has no negatives at all,
and we have zero ANTSDR-captured drone positives, so no tier here is a field
PD number). Tier C (cross-receiver on our own HackRF captures) is reported as
explicitly BLOCKED -- never silently omitted -- because no local HackRF
sessions exist on this host (S3.1).

* **Tier A** -- in-dataset Zenodo group hold-out (group = model, i.e.
  ``device_id``). Zenodo has only ``drone_link`` positives, so each fold
  trains on (other Zenodo models' positives + ANTSDR-ambient negatives) and
  reports **recall only** on the held-out model. One ANTSDR session group is
  reserved, deterministically, purely as a PR-AUC negative pool -- it is
  never trained on in any Tier-A fold -- so a (diagnostic) PR-AUC can also be
  reported per fold.
* **Tier B** -- leave-one-dataset-out: train on Zenodo(+ANTSDR negatives),
  test recall on RUB DroneID fragments (short windows: G3/G5 are masked
  invalid on RUB, so the common feature-column set for this tier drops to
  G1/G2/G4). RUB has no negatives, so no PFA/PR-AUC here.
* **Tier D** -- ANTSDR ambient hold-out, leave-one-session-out (session =
  ``run_id`` group): train on (other ANTSDR sessions + all public positives),
  report PFA and false-alarms/hour on the held-out session. No PD/recall is
  reported for tier D: there are no ANTSDR drone positives. This is a
  documented simplification of S3.2's dev/test ANTSDR split (a separate
  threshold-selection dev split is not implemented in this pass).

Every tier fold is checked with ``_assert_disjoint_groups`` before fitting:
if any ``(dataset_id, device_id, run_id)`` group would appear in more than
one partition of the same fold, the run refuses (raises ``SplitLeakError``,
non-zero exit from ``main``) rather than silently leaking.

Usage::

    uv run python3 bench/benchmark_features_v2.py \\
        --report bench/out/benchmark_features_v2.md

Exit codes: 0 report written (tiers may individually be "not run" with a
reason -- that is not a failure), 2 no rows loaded for any dataset, 4 a
split-spanning group was detected and the run refused.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aerix_rf.classify.features_v2 import (  # noqa: E402
    FEATURES_V2_DIM,
    FEATURES_VERSION,
    extract_features_v2,
)
from aerix_rf.datasets.index import dataset_root, iter_dataset  # noqa: E402
from aerix_rf.datasets.spec import EmitterClass, WindowSidecar  # noqa: E402

RANDOM_STATE = 0
WINDOW_SECONDS = 1.0  # S3.3: "windows are 1 s" -- FA/hour = PFA * 3600
N_BOOTSTRAP = 200
CI_LEVEL = 0.90
WIDE_CI_GROUP_THRESHOLD = 10

ZENODO_DATASET_ID = "zenodo_drone_rf_video_2020"
ANTSDR_DATASET_ID = "aerix_antsdr_ambient_2026_09_18"
RUB_DATASET_ID = "rub_dronesecurity"

# S3.4, must appear verbatim in the generated report.
FRAMING_PARAGRAPH = (
    "We have no ANTSDR-captured drone positives. This benchmark measures (a) false-positive "
    "behaviour of the Stage-2 classifier on real ANTSDR ambient RF and (b) recall on public "
    "positives captured by other receivers, mostly in an anechoic chamber. It is not a field "
    "detection-performance measurement, and no number in it is a PD claim for the deployed "
    "system. All positives are evidence level 5 *scene* truth from the source dataset, not "
    "per-window truth; Stage-2 output remains evidence level 2."
)

GroupKey = tuple[str, str, str]


class SplitLeakError(RuntimeError):
    """A ``(dataset_id, device_id, run_id)`` group was assigned to more than
    one partition of the same tier fold -- refuse to run (S3 tiers)."""


def _group_key(sc: WindowSidecar) -> GroupKey:
    return (sc.identity.dataset_id, sc.identity.device_id, sc.identity.run_id)


def _has_rate_warning(sc: WindowSidecar) -> bool:
    return bool(sc.notes) and "rate_warning=True" in sc.notes


@dataclass
class Row:
    dataset_id: str
    device_id: str
    run_id: str
    group: GroupKey
    emitter_class: str
    n_ms: int
    vector: np.ndarray       # full FEATURES_V2_DIM, zero-filled where invalid
    valid_mask: np.ndarray   # bool [FEATURES_V2_DIM]
    valid_fraction: float


@dataclass
class DatasetMeta:
    n_seen: int = 0
    n_used: int = 0
    preproc_versions: set = field(default_factory=set)
    code_versions: set = field(default_factory=set)
    valid_fractions: list = field(default_factory=list)


def load_rows(
    dataset_id: str, root: Path | None = None, limit: int | None = None
) -> tuple[list[Row], dict, DatasetMeta]:
    """Load one dataset's prepared index rows, compute ``features_v2`` per
    row (``detector_frames_lin=None`` -- not stored in the prepared corpus,
    so G3 is always invalid, matching ``bench/receiver_id_probe.py``), and
    skip rate_warning windows / missing tensors."""
    root = root if root is not None else dataset_root()
    rows: list[Row] = []
    skipped: dict = defaultdict(int)
    meta = DatasetMeta()
    for sc in iter_dataset(dataset_id, root=root):
        meta.n_seen += 1
        if limit is not None and meta.n_used >= limit:
            break
        meta.preproc_versions.add(sc.bookkeeping.preproc_version)
        meta.code_versions.add(sc.bookkeeping.code_version)
        if _has_rate_warning(sc):
            skipped[f"{dataset_id}:rate_warning"] += 1
            continue
        tensor_path = root / dataset_id / "prepared" / f"{sc.identity.uid}.tensor.npy"
        if not tensor_path.exists():
            skipped[f"{dataset_id}:missing_tensor"] += 1
            continue
        tensor = np.load(tensor_path)
        try:
            feats = extract_features_v2(tensor, None, fs_hz=sc.signal.sample_rate_hz)
        except ValueError:
            skipped[f"{dataset_id}:extract_error"] += 1
            continue
        rows.append(
            Row(
                dataset_id=dataset_id,
                device_id=sc.identity.device_id,
                run_id=sc.identity.run_id,
                group=_group_key(sc),
                emitter_class=sc.labels.scene.emitter_class.value,
                n_ms=int(tensor.shape[0]),
                vector=feats.vector,
                valid_mask=feats.valid_mask,
                valid_fraction=float(np.mean(feats.valid_mask)),
            )
        )
        meta.n_used += 1
        meta.valid_fractions.append(rows[-1].valid_fraction)
    return rows, dict(skipped), meta


def _common_columns(rows: list[Row]) -> np.ndarray:
    """Columns valid across every row in ``rows`` (AND of ``valid_mask``):
    the classifier's fixed column set for one tier/fold. G3 is always
    invalid in this corpus (no stored detector frames); G5 additionally
    drops out whenever short (RUB) windows are present."""
    if not rows:
        return np.ones(FEATURES_V2_DIM, dtype=bool)
    mask = np.ones(FEATURES_V2_DIM, dtype=bool)
    for r in rows:
        mask &= r.valid_mask
    return mask


def _matrix(rows: list[Row], columns: np.ndarray) -> np.ndarray:
    if not rows:
        return np.zeros((0, int(columns.sum())), dtype=np.float64)
    X = np.stack([r.vector for r in rows]).astype(np.float64)[:, columns]
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)


def _assert_disjoint_groups(partitions: dict[str, set], tier: str, fold: str = "") -> None:
    names = list(partitions)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            overlap = partitions[names[i]] & partitions[names[j]]
            if overlap:
                where = f" fold={fold!r}" if fold else ""
                raise SplitLeakError(
                    f"tier {tier}{where}: group(s) {sorted(overlap)} present in both "
                    f"{names[i]!r} and {names[j]!r} -- refusing to run"
                )


def _reserve_one_group(rows: list[Row]) -> tuple[list[Row], list[Row], GroupKey | None]:
    """Deterministically reserve one group (sorted first) as a held-out
    validation pool that is never trained on. Returns
    ``(remaining_rows, reserved_rows, reserved_group)``."""
    groups = sorted({r.group for r in rows})
    if not groups:
        return rows, [], None
    reserved = groups[0]
    remaining = [r for r in rows if r.group != reserved]
    reserved_rows = [r for r in rows if r.group == reserved]
    return remaining, reserved_rows, reserved


def _fit_models(Xtr: np.ndarray, ytr: np.ndarray) -> dict:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.utils.class_weight import compute_sample_weight

    logreg = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE),
    )
    logreg.fit(Xtr, ytr)

    sw = compute_sample_weight("balanced", ytr)
    gboost = GradientBoostingClassifier(random_state=RANDOM_STATE)
    gboost.fit(Xtr, ytr, sample_weight=sw)
    return {"logreg": logreg, "gboost": gboost}


def _predict_proba_pos(model, X: np.ndarray, pos_label: int = 1) -> np.ndarray:
    if X.shape[0] == 0:
        return np.zeros(0, dtype=np.float64)
    proba = model.predict_proba(X)
    classes = list(model.classes_)
    idx = classes.index(pos_label)
    return proba[:, idx]


def _bootstrap_ci(
    values: list[float], n_boot: int = N_BOOTSTRAP, level: float = CI_LEVEL, seed: int = RANDOM_STATE
) -> tuple[float, float]:
    """Group bootstrap (S3.3): resample the per-group point estimates, not
    windows."""
    if not values:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boots[i] = float(np.median(arr[idx]))
    alpha = (1.0 - level) / 2.0
    lo, hi = np.quantile(boots, [alpha, 1.0 - alpha])
    return float(lo), float(hi)


def _summary_stats(values: list[float]) -> dict:
    vals = [v for v in values if v == v]  # drop NaN
    if not vals:
        return {"min": float("nan"), "median": float("nan"), "max": float("nan"),
                "ci_lo": float("nan"), "ci_hi": float("nan")}
    lo, hi = _bootstrap_ci(vals)
    return {"min": float(np.min(vals)), "median": float(np.median(vals)), "max": float(np.max(vals)),
            "ci_lo": lo, "ci_hi": hi}


@dataclass
class TierResult:
    name: str
    ran: bool
    reason: str = ""
    columns_used: int = 0
    table: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Tier A -- in-dataset Zenodo model hold-out, recall (+ diagnostic PR-AUC).
# --------------------------------------------------------------------------

def run_tier_a(zenodo_rows: list[Row], antsdr_rows: list[Row]) -> TierResult:
    from sklearn.metrics import average_precision_score

    name = "A"
    pos_rows = [r for r in zenodo_rows if r.emitter_class == EmitterClass.DRONE_LINK.value]
    if not pos_rows:
        return TierResult(name=name, ran=False, reason="no zenodo drone_link rows loaded")
    if not antsdr_rows:
        return TierResult(name=name, ran=False, reason="no ANTSDR ambient rows loaded for negatives")

    antsdr_train_pool, antsdr_reserved, reserved_group = _reserve_one_group(antsdr_rows)
    if not antsdr_train_pool:
        return TierResult(
            name=name, ran=False,
            reason="only one ANTSDR session group available; cannot reserve a PR-AUC "
                   "negative holdout without starving negative training data",
        )

    model_groups = sorted({r.device_id for r in pos_rows})
    if len(model_groups) < 2:
        return TierResult(
            name=name, ran=False,
            reason=f"only {len(model_groups)} zenodo model group(s); need >=2 for group hold-out",
        )

    columns = _common_columns(pos_rows + antsdr_train_pool + antsdr_reserved)
    table: list[dict] = []
    recalls_lr, recalls_gb, prauc_lr, prauc_gb = [], [], [], []

    for m in model_groups:
        train_pos = [r for r in pos_rows if r.device_id != m]
        test_pos = [r for r in pos_rows if r.device_id == m]
        train_groups = {r.group for r in train_pos} | {r.group for r in antsdr_train_pool}
        test_groups = {r.group for r in test_pos}
        reserved_set = {reserved_group} if reserved_group else set()
        _assert_disjoint_groups(
            {"train": train_groups, "test": test_groups, "reserved_neg": reserved_set},
            tier=name, fold=m,
        )

        Xtr = _matrix(train_pos + antsdr_train_pool, columns)
        ytr = np.array([1] * len(train_pos) + [0] * len(antsdr_train_pool))
        models = _fit_models(Xtr, ytr)

        Xte_pos = _matrix(test_pos, columns)
        Xte_neg = _matrix(antsdr_reserved, columns)

        row_metrics: dict = {"group": m, "n_pos": len(test_pos)}
        for mname, model in models.items():
            pred_pos = model.predict(Xte_pos)
            recall = float(np.mean(pred_pos == 1)) if len(test_pos) else float("nan")
            y_true = np.array([1] * len(test_pos) + [0] * len(antsdr_reserved))
            y_score = np.concatenate([_predict_proba_pos(model, Xte_pos), _predict_proba_pos(model, Xte_neg)])
            pr_auc = float(average_precision_score(y_true, y_score)) if len(set(y_true.tolist())) > 1 else float("nan")
            row_metrics[f"recall_{mname}"] = recall
            row_metrics[f"pr_auc_{mname}"] = pr_auc
            (recalls_lr if mname == "logreg" else recalls_gb).append(recall)
            (prauc_lr if mname == "logreg" else prauc_gb).append(pr_auc)
        table.append(row_metrics)

    summary = {
        "n_groups": len(model_groups),
        "recall_logreg": _summary_stats(recalls_lr),
        "recall_gboost": _summary_stats(recalls_gb),
        "pr_auc_logreg": _summary_stats(prauc_lr),
        "pr_auc_gboost": _summary_stats(prauc_gb),
        "wide_ci": len(model_groups) < WIDE_CI_GROUP_THRESHOLD,
    }
    notes = [
        f"negative training pool: {len(antsdr_train_pool)} ANTSDR ambient windows across "
        f"{len({r.group for r in antsdr_train_pool})} session group(s); ANTSDR session "
        f"{reserved_group} reserved solely as the PR-AUC negative pool, never trained on in "
        f"any fold.",
        "recall only is the tier-A claim per S3.2; PR-AUC here is a diagnostic against the "
        "reserved ANTSDR negative pool, not a field number.",
    ]
    return TierResult(name=name, ran=True, columns_used=int(columns.sum()), table=table, summary=summary, notes=notes)


# --------------------------------------------------------------------------
# Tier B -- leave-one-dataset-out, RUB recall only (short windows).
# --------------------------------------------------------------------------

def run_tier_b(zenodo_rows: list[Row], antsdr_rows: list[Row], rub_rows: list[Row]) -> TierResult:
    name = "B"
    train_pos = [r for r in zenodo_rows if r.emitter_class == EmitterClass.DRONE_LINK.value]
    train_neg = antsdr_rows
    test_rows = [r for r in rub_rows if r.emitter_class == EmitterClass.DRONE_LINK.value]
    if not train_pos or not train_neg:
        return TierResult(name=name, ran=False, reason="need zenodo positives and ANTSDR negatives for training")
    if not test_rows:
        return TierResult(name=name, ran=False, reason="no RUB drone_link rows loaded")

    train_groups = {r.group for r in train_pos} | {r.group for r in train_neg}
    test_groups = {r.group for r in test_rows}
    _assert_disjoint_groups({"train": train_groups, "test": test_groups}, tier=name)

    columns = _common_columns(train_pos + train_neg + test_rows)
    Xtr = _matrix(train_pos + train_neg, columns)
    ytr = np.array([1] * len(train_pos) + [0] * len(train_neg))
    models = _fit_models(Xtr, ytr)

    by_group: dict[GroupKey, list[Row]] = defaultdict(list)
    for r in test_rows:
        by_group[r.group].append(r)

    table: list[dict] = []
    recalls_lr, recalls_gb = [], []
    for grp, grows in sorted(by_group.items()):
        Xte = _matrix(grows, columns)
        row_metrics: dict = {"group": "/".join(grp), "n": len(grows)}
        for mname, model in models.items():
            pred = model.predict(Xte)
            recall = float(np.mean(pred == 1))
            row_metrics[f"recall_{mname}"] = recall
            (recalls_lr if mname == "logreg" else recalls_gb).append(recall)
        table.append(row_metrics)

    summary = {
        "n_groups": len(by_group),
        "recall_logreg": _summary_stats(recalls_lr),
        "recall_gboost": _summary_stats(recalls_gb),
        "wide_ci": len(by_group) < WIDE_CI_GROUP_THRESHOLD,
    }
    notes = [
        "RUB has no negatives: PFA/PR-AUC not computed for tier B, recall only.",
        f"feature columns used: {int(columns.sum())}/{FEATURES_V2_DIM} -- RUB fragments are "
        "short windows, so G3 and (if <100 ms) G5 are masked invalid and excluded from the "
        "common column set for this tier.",
        "RUB fragments are pre-segmented: someone already did the detection step.",
    ]
    return TierResult(name=name, ran=True, columns_used=int(columns.sum()), table=table, summary=summary, notes=notes)


# --------------------------------------------------------------------------
# Tier D -- ANTSDR ambient hold-out, leave-one-session-out, PFA/FA-per-hour.
# --------------------------------------------------------------------------

def run_tier_d(antsdr_rows: list[Row], public_pos_rows: list[Row]) -> TierResult:
    name = "D"
    if not antsdr_rows:
        return TierResult(name=name, ran=False, reason="no ANTSDR ambient rows loaded")
    sessions = sorted({r.group for r in antsdr_rows})
    if len(sessions) < 2:
        return TierResult(
            name=name, ran=False,
            reason=f"only {len(sessions)} ANTSDR session group(s); need >=2 for leave-one-session-out",
        )
    if not public_pos_rows:
        return TierResult(name=name, ran=False, reason="no public positive rows (zenodo/rub) available for training")

    columns = _common_columns(antsdr_rows + public_pos_rows)
    table: list[dict] = []
    pfa_lr, pfa_gb, fah_lr, fah_gb = [], [], [], []

    for s in sessions:
        train_neg = [r for r in antsdr_rows if r.group != s]
        test_neg = [r for r in antsdr_rows if r.group == s]
        train_groups = {r.group for r in train_neg} | {r.group for r in public_pos_rows}
        test_groups = {r.group for r in test_neg}
        _assert_disjoint_groups({"train": train_groups, "test": test_groups}, tier=name, fold="/".join(s))

        Xtr = _matrix(train_neg + public_pos_rows, columns)
        ytr = np.array([0] * len(train_neg) + [1] * len(public_pos_rows))
        models = _fit_models(Xtr, ytr)

        Xte = _matrix(test_neg, columns)
        row_metrics: dict = {"group": "/".join(s), "n": len(test_neg)}
        for mname, model in models.items():
            pred = model.predict(Xte)
            pfa = float(np.mean(pred == 1)) if len(test_neg) else float("nan")
            fah = pfa * (3600.0 / WINDOW_SECONDS)
            row_metrics[f"pfa_{mname}"] = pfa
            row_metrics[f"fa_per_hour_{mname}"] = fah
            (pfa_lr if mname == "logreg" else pfa_gb).append(pfa)
            (fah_lr if mname == "logreg" else fah_gb).append(fah)
        table.append(row_metrics)

    summary = {
        "n_groups": len(sessions),
        "pfa_logreg": _summary_stats(pfa_lr),
        "pfa_gboost": _summary_stats(pfa_gb),
        "fa_per_hour_logreg": _summary_stats(fah_lr),
        "fa_per_hour_gboost": _summary_stats(fah_gb),
        "wide_ci": len(sessions) < WIDE_CI_GROUP_THRESHOLD,
    }
    notes = [
        "PD is not reported for tier D: there are no ANTSDR-captured drone positives.",
        "Simplification vs S3.2's dev/test ANTSDR split: this run uses leave-one-session-out "
        "(each ANTSDR session held out in turn, all other sessions + public positives train, "
        "default classifier decision threshold) rather than a separate dev split for operating"
        "-threshold selection -- documented deviation, time-boxed for this pass.",
    ]
    return TierResult(name=name, ran=True, columns_used=int(columns.sum()), table=table, summary=summary, notes=notes)


# --------------------------------------------------------------------------
# Report rendering.
# --------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _load_probe_summary(path: Path) -> str:
    if not path.exists():
        return f"receiver-ID probe report not found at `{path}` -- run `bench/receiver_id_probe.py` first."
    text = path.read_text(encoding="utf-8")
    lines: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## Label-matched probe"):
            in_section = True
            lines.append(line)
            continue
        if line.startswith("## ") and in_section:
            break
        if in_section and line.strip():
            lines.append(line)
    if len(lines) <= 1:
        return f"receiver-ID probe report at `{path}` had no parseable label-matched section."
    return "\n".join(lines)


def _fmt_stats(s: dict) -> str:
    return (f"min {s['min']:.3f} / median {s['median']:.3f} / max {s['max']:.3f}, "
            f"90% group-bootstrap CI [{s['ci_lo']:.3f}, {s['ci_hi']:.3f}]")


def render_tier_a(res: TierResult) -> list[str]:
    lines = ["## Tier A -- in-dataset Zenodo model hold-out (recall)", ""]
    if not res.ran:
        lines += [f"**Not run.** {res.reason}", ""]
        return lines
    lines.append(f"Feature columns used: {res.columns_used}/{FEATURES_V2_DIM}. Groups (models): {res.summary['n_groups']}.")
    if res.summary["wide_ci"]:
        lines.append("**Fewer than 10 groups: confidence intervals below are wide -- reported as-is, not hidden.**")
    lines.append("")
    lines.append("| model group | n_pos | recall (logreg) | recall (gboost) | PR-AUC (logreg, vs reserved neg) | PR-AUC (gboost, vs reserved neg) |")
    lines.append("|---|---|---|---|---|---|")
    for row in res.table:
        lines.append(
            f"| {row['group']} | {row['n_pos']} | {row['recall_logreg']:.3f} | {row['recall_gboost']:.3f} | "
            f"{row['pr_auc_logreg']:.3f} | {row['pr_auc_gboost']:.3f} |"
        )
    lines.append("")
    lines.append(f"- recall (logreg): {_fmt_stats(res.summary['recall_logreg'])}")
    lines.append(f"- recall (gboost): {_fmt_stats(res.summary['recall_gboost'])}")
    lines.append(f"- PR-AUC (logreg): {_fmt_stats(res.summary['pr_auc_logreg'])}")
    lines.append(f"- PR-AUC (gboost): {_fmt_stats(res.summary['pr_auc_gboost'])}")
    lines.append("")
    for n in res.notes:
        lines.append(f"Note: {n}")
    lines.append("")
    return lines


def render_tier_b(res: TierResult) -> list[str]:
    lines = ["## Tier B -- leave-one-dataset-out (Zenodo+ANTSDR train -> RUB recall)", ""]
    if not res.ran:
        lines += [f"**Not run.** {res.reason}", ""]
        return lines
    lines.append(f"Feature columns used: {res.columns_used}/{FEATURES_V2_DIM}. RUB groups: {res.summary['n_groups']}.")
    if res.summary["wide_ci"]:
        lines.append("**Fewer than 10 groups: confidence intervals below are wide -- reported as-is, not hidden.**")
    lines.append("")
    lines.append("| RUB group | n | recall (logreg) | recall (gboost) |")
    lines.append("|---|---|---|---|")
    for row in res.table:
        lines.append(f"| {row['group']} | {row['n']} | {row['recall_logreg']:.3f} | {row['recall_gboost']:.3f} |")
    lines.append("")
    lines.append(f"- recall (logreg): {_fmt_stats(res.summary['recall_logreg'])}")
    lines.append(f"- recall (gboost): {_fmt_stats(res.summary['recall_gboost'])}")
    lines.append("")
    for n in res.notes:
        lines.append(f"Note: {n}")
    lines.append("")
    return lines


def render_tier_d(res: TierResult) -> list[str]:
    lines = ["## Tier D -- ANTSDR ambient hold-out, leave-one-session-out (PFA / FA per hour)", ""]
    if not res.ran:
        lines += [f"**Not run.** {res.reason}", ""]
        return lines
    lines.append(f"Feature columns used: {res.columns_used}/{FEATURES_V2_DIM}. ANTSDR session groups: {res.summary['n_groups']}.")
    if res.summary["wide_ci"]:
        lines.append("**Fewer than 10 groups: confidence intervals below are wide -- reported as-is, not hidden.**")
    lines.append("")
    lines.append("| held-out session | n windows | PFA (logreg) | FA/hour (logreg) | PFA (gboost) | FA/hour (gboost) |")
    lines.append("|---|---|---|---|---|---|")
    for row in res.table:
        lines.append(
            f"| {row['group']} | {row['n']} | {row['pfa_logreg']:.4f} | {row['fa_per_hour_logreg']:.1f} | "
            f"{row['pfa_gboost']:.4f} | {row['fa_per_hour_gboost']:.1f} |"
        )
    lines.append("")
    lines.append(f"- PFA (logreg): {_fmt_stats(res.summary['pfa_logreg'])}")
    lines.append(f"- PFA (gboost): {_fmt_stats(res.summary['pfa_gboost'])}")
    lines.append(f"- FA/hour (logreg): {_fmt_stats(res.summary['fa_per_hour_logreg'])}")
    lines.append(f"- FA/hour (gboost): {_fmt_stats(res.summary['fa_per_hour_gboost'])}")
    lines.append("")
    for n in res.notes:
        lines.append(f"Note: {n}")
    lines.append("")
    return lines


def render_report(
    tier_a: TierResult, tier_b: TierResult, tier_d: TierResult,
    dataset_meta: dict[str, DatasetMeta], skip_counts: dict,
    probe_summary: str, elapsed_s: float,
) -> str:
    lines = ["# F3 benchmark report -- features_v2 (tiers A/B/D)", ""]
    lines.append(FRAMING_PARAGRAPH)
    lines.append("")
    lines.append(f"Generated in {elapsed_s:.1f} s. `features_version` = `{FEATURES_VERSION}`, code git sha = `{_git_sha()}`.")
    lines.append("")

    lines.append("## Dataset row counts and versions")
    lines.append("")
    lines.append("| dataset_id | rows seen | rows used | mean features_valid_fraction | preproc_version(s) | code_version(s) |")
    lines.append("|---|---|---|---|---|---|")
    for dsid, meta in dataset_meta.items():
        mvf = float(np.mean(meta.valid_fractions)) if meta.valid_fractions else float("nan")
        lines.append(
            f"| {dsid} | {meta.n_seen} | {meta.n_used} | {mvf:.3f} | "
            f"{', '.join(sorted(meta.preproc_versions)) or '-'} | {', '.join(sorted(meta.code_versions)) or '-'} |"
        )
    lines.append("")
    if skip_counts:
        lines.append(f"Skipped: {dict(skip_counts)}")
        lines.append("")

    lines.append("## Receiver-ID probe (F2)")
    lines.append("")
    lines.append(probe_summary)
    lines.append("")

    lines += render_tier_a(tier_a)
    lines += render_tier_b(tier_b)
    lines += render_tier_d(tier_d)

    lines.append("## Tier C -- cross-receiver on our own HackRF captures")
    lines.append("")
    lines.append(
        "**BLOCKED.** No local HackRF 2026-09-04 (or later) sessions are present on this host "
        "(S3.1). Tier C is reported here explicitly rather than silently omitted; it cannot be "
        "run until HackRF captures are copied onto this machine or re-captured."
    )
    lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Top-level run + CLI.
# --------------------------------------------------------------------------

def run_benchmark(
    zenodo_id: str = ZENODO_DATASET_ID,
    antsdr_id: str = ANTSDR_DATASET_ID,
    rub_id: str = RUB_DATASET_ID,
    root: Path | None = None,
    limit_per_dataset: int | None = None,
) -> tuple[TierResult, TierResult, TierResult, dict[str, DatasetMeta], dict]:
    zenodo_rows, skip_z, meta_z = load_rows(zenodo_id, root=root, limit=limit_per_dataset)
    antsdr_rows, skip_a, meta_a = load_rows(antsdr_id, root=root, limit=limit_per_dataset)
    rub_rows, skip_r, meta_r = load_rows(rub_id, root=root, limit=limit_per_dataset)

    skip_counts: dict = {}
    for d in (skip_z, skip_a, skip_r):
        skip_counts.update(d)
    dataset_meta = {zenodo_id: meta_z, antsdr_id: meta_a, rub_id: meta_r}

    tier_a = run_tier_a(zenodo_rows, antsdr_rows)
    tier_b = run_tier_b(zenodo_rows, antsdr_rows, rub_rows)
    public_pos = [r for r in zenodo_rows + rub_rows if r.emitter_class == EmitterClass.DRONE_LINK.value]
    tier_d = run_tier_d(antsdr_rows, public_pos)

    return tier_a, tier_b, tier_d, dataset_meta, skip_counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--limit-per-dataset", type=int, default=None)
    parser.add_argument("--report", type=Path, default=Path("bench/out/benchmark_features_v2.md"))
    parser.add_argument("--probe-report", type=Path, default=Path("bench/out/receiver_id_probe.md"))
    parser.add_argument("--zenodo-dataset", default=ZENODO_DATASET_ID)
    parser.add_argument("--antsdr-dataset", default=ANTSDR_DATASET_ID)
    parser.add_argument("--rub-dataset", default=RUB_DATASET_ID)
    args = parser.parse_args(argv)

    t0 = time.monotonic()
    try:
        tier_a, tier_b, tier_d, dataset_meta, skip_counts = run_benchmark(
            zenodo_id=args.zenodo_dataset, antsdr_id=args.antsdr_dataset, rub_id=args.rub_dataset,
            root=args.root, limit_per_dataset=args.limit_per_dataset,
        )
    except SplitLeakError as exc:
        print(f"benchmark_features_v2: refusing to run -- {exc}", file=sys.stderr)
        return 4

    total_used = sum(m.n_used for m in dataset_meta.values())
    if total_used == 0:
        print("benchmark_features_v2: no rows loaded for any dataset, nothing to do", file=sys.stderr)
        return 2

    probe_summary = _load_probe_summary(args.probe_report)
    elapsed = time.monotonic() - t0
    report_md = render_report(tier_a, tier_b, tier_d, dataset_meta, skip_counts, probe_summary, elapsed)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_md, encoding="utf-8")
    print(report_md)
    print(f"\nReport written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
