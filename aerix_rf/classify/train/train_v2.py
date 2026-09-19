"""Stage-2 ``features_v2`` trainer -- produces a drop-in model bundle.

This is the F5 counterpart of ``bench/benchmark_features_v2.py`` (F3): where
the benchmark measures cross-tier recall/PFA on ``features_v2`` without
saving anything, this module actually fits and saves a bundle that
``aerix_rf.classify.model.classify_window`` can load under
``AERIX_RF_FEATURES=v2`` (docs/design/features-and-benchmark.md S4 F4/F5).

Row loading and the sample-rate-deficit exclusion rule are **reused, not
duplicated**, from ``bench/benchmark_features_v2.py`` (``load_rows``,
``_common_columns``, ``_matrix``, ``_assert_disjoint_groups``,
``SplitLeakError``, ``FRAMING_PARAGRAPH``) -- see that module's docstring for
why each dataset's rows are excluded (session-median ``stream_rate_ratio`` /
typed sample-count deficits) and why a ``transition``-flagged window with
existing annotations must be dropped.

Group-level split (never per-window, section 4 of the dataset-normalization
memo): every window sharing a ``(dataset_id, device_id, run_id)`` group gets
the same split, via ``aerix_rf.datasets.index.assign_splits`` at 70/15/15.
Labels are the binary ``drone_link`` / ``background`` collapse of each row's
*actual* scene ``emitter_class`` (not which ``--positives``/``--negatives``
list its dataset was passed under -- a "positive" dataset could in principle
contribute a non-``drone_link`` row); the finer per-row scene label is kept
in the bundle's ``train_manifest`` for later multi-class work.

Column mask: ``features_v2`` columns invalid for *any* loaded row (G3 is
always invalid in this corpus -- no stored detector frames; G5 also drops
out whenever a short window, e.g. RUB fragments, is present) are recorded in
the bundle (``feature_columns``) and are also genuinely excluded from what
the fitted estimator looks at, via a ``ColumnMaskSelector`` pipeline step.
That step -- not the caller -- applies the mask, because
``classify.model.classify_window``'s ``features_v2`` live path always feeds
the *full* ``FEATURES_V2_DIM``-wide vector to ``bundle["model"].predict``;
a bundle whose masked-out columns were simply dropped before fitting would
crash (shape mismatch) the first time the live loop calls it.

CLI::

    uv run python -m aerix_rf.classify.train.train_v2 \\
        --positives zenodo_drone_rf_video_2020 rub_dronesecurity \\
        --negatives aerix_antsdr_ambient_2026_09_18 \\
        --out models/signature_v2.joblib --seed 0
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter, defaultdict
from collections import namedtuple as _namedtuple
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# bench/ is a script directory, not an installed package -- import it the
# same way tests/test_benchmark_features_v2.py does.
_PKG_ROOT = Path(__file__).resolve().parents[3]      # .../aerix-rf
_BENCH_DIR = _PKG_ROOT / "bench"
if str(_BENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCH_DIR))

import benchmark_features_v2 as bfv  # noqa: E402

from ...datasets import index as index_mod  # noqa: E402
from ...datasets.spec import Split  # noqa: E402
from .. import features_v2 as fv2  # noqa: E402

VERSION = "v2-1"
DEFAULT_MODEL_PATH = _PKG_ROOT / "models" / "signature_v2.joblib"
DEFAULT_FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}

GroupKey = bfv.GroupKey
Row = bfv.Row

_FakeIdentity = _namedtuple("_FakeIdentity", "dataset_id device_id run_id")
_FakeSidecar = _namedtuple("_FakeSidecar", "identity")


class SplitLeakError(bfv.SplitLeakError):
    """Re-exported so callers of this module need not import the bench script."""


# --------------------------------------------------------------------------
# sklearn pipeline step: selects the bundle's fixed column mask from the
# *full* FEATURES_V2_DIM vector. Kept as a pipeline step (not applied by the
# caller) so classify.model's features_v2 live path -- which always feeds a
# full-width vector -- can call this bundle's model directly.
# --------------------------------------------------------------------------

class ColumnMaskSelector:
    """A minimal, joblib-picklable sklearn-style transformer: ``X[:, mask]``."""

    def __init__(self, mask: np.ndarray):
        self.mask = np.asarray(mask, dtype=bool)

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return np.asarray(X)[:, self.mask]

    def fit_transform(self, X, y=None):
        return self.transform(X)

    def get_params(self, deep=True):
        return {"mask": self.mask}

    def set_params(self, **params):
        for k, v in params.items():
            setattr(self, k, v)
        return self


# When this module is executed as a script (``python -m
# aerix_rf.classify.train.train_v2``), Python imports it as ``__main__``:
# pickle's save_global would record ``ColumnMaskSelector.__module__`` as
# ``"__main__"`` (unloadable from any other process, e.g. the live box's
# ``aerix_rf.classify.model._load_bundle``, which imports this module by its
# real dotted path). Registering this already-executing module object under
# its real dotted name too -- not re-importing it, which would create a
# second, distinct class object and fail pickle's identity check -- lets
# ``ColumnMaskSelector.__module__`` point at the real path while
# ``sys.modules[real_path] is sys.modules["__main__"]`` still holds, so
# ``pickle.save_global``'s ``sys.modules[module_name].name is obj`` check
# passes. A bundle trained this way is then loadable via a normal
# ``import aerix_rf.classify.train.train_v2``, which defines its own,
# structurally-identical ``ColumnMaskSelector`` (pickle only needs the class
# to exist at that path, not object identity across processes).
_REAL_MODULE_NAME = "aerix_rf.classify.train.train_v2"
if __name__ != _REAL_MODULE_NAME:
    sys.modules.setdefault(_REAL_MODULE_NAME, sys.modules[__name__])
    ColumnMaskSelector.__module__ = _REAL_MODULE_NAME


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_PKG_ROOT,
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 -- provenance only, never fatal
        return "unknown"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

@dataclass
class LoadSummary:
    rows: list  # list[Row]
    meta_by_dataset: dict
    skipped: dict


def load_datasets(dataset_ids: list[str], root: Path | None) -> LoadSummary:
    all_rows: list = []
    meta_by_dataset: dict = {}
    skipped_all: dict = defaultdict(int)
    for dsid in dataset_ids:
        rows, skipped, meta = bfv.load_rows(dsid, root=root)
        all_rows.extend(rows)
        meta_by_dataset[dsid] = meta
        for k, v in skipped.items():
            skipped_all[k] += v
    return LoadSummary(rows=all_rows, meta_by_dataset=meta_by_dataset, skipped=dict(skipped_all))


def binary_label(row) -> str:
    """The row's actual scene ``emitter_class`` collapsed to the binary target."""
    return "drone_link" if row.emitter_class == "drone_link" else "background"


# --------------------------------------------------------------------------
# Group-level split (section 4): (dataset_id, device_id, run_id).
# --------------------------------------------------------------------------

def _assign_row_splits(rows: list, seed: int, fractions: dict | None = None) -> dict[int, str]:
    """index-in-``rows`` -> split name, group-consistent via
    ``aerix_rf.datasets.index.assign_splits`` (every window sharing a group
    gets the same split; never assigned per window)."""
    fake = [_FakeSidecar(_FakeIdentity(*r.group)) for r in rows]
    group_to_split = index_mod.assign_splits(fake, seed=seed, fractions=fractions or DEFAULT_FRACTIONS)
    return {i: group_to_split[rows[i].group].value for i in range(len(rows))}


def _assert_group_splits_disjoint(rows: list, row_split: dict[int, str]) -> None:
    """Refuse (raise ``SplitLeakError``) if any ``(dataset_id, device_id,
    run_id)`` group is present in more than one split partition."""
    partitions: dict[str, set] = defaultdict(set)
    for i, row in enumerate(rows):
        partitions[row_split[i]].add(row.group)
    try:
        bfv._assert_disjoint_groups(partitions, tier="train_v2")
    except bfv.SplitLeakError as exc:
        raise SplitLeakError(str(exc)) from exc


# --------------------------------------------------------------------------
# Model fitting
# --------------------------------------------------------------------------

def _pipelines(mask: np.ndarray, seed: int) -> dict:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    logreg = Pipeline([
        ("select", ColumnMaskSelector(mask)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=seed)),
    ])
    gboost = Pipeline([
        ("select", ColumnMaskSelector(mask)),
        ("clf", GradientBoostingClassifier(random_state=seed)),
    ])
    return {"logreg": logreg, "gboost": gboost}


def _fit(pipe, X, y, seed: int):
    from sklearn.utils.class_weight import compute_sample_weight

    clf = pipe.named_steps["clf"]
    if clf.__class__.__name__ == "GradientBoostingClassifier":
        sw = compute_sample_weight("balanced", y)
        pipe.fit(X, y, clf__sample_weight=sw)
    else:
        pipe.fit(X, y)
    return pipe


def _proba_drone_link(pipe, X: np.ndarray) -> np.ndarray:
    if X.shape[0] == 0:
        return np.zeros(0, dtype=np.float64)
    proba = pipe.predict_proba(X)
    classes = list(pipe.classes_)
    idx = classes.index("drone_link")
    return proba[:, idx]


def _val_score(pipe, Xval: np.ndarray, yval: np.ndarray) -> float:
    """Validation PR-AUC (positive class ``drone_link``); falls back to
    accuracy if only one class is present in ``yval`` (small synthetic
    corpora), so the comparison never raises."""
    from sklearn.metrics import accuracy_score, average_precision_score

    if Xval.shape[0] == 0:
        return float("nan")
    if len(set(yval.tolist())) < 2:
        return float(accuracy_score(yval, pipe.predict(Xval)))
    y_true = (yval == "drone_link").astype(int)
    return float(average_precision_score(y_true, _proba_drone_link(pipe, Xval)))


# --------------------------------------------------------------------------
# End-to-end
# --------------------------------------------------------------------------

@dataclass
class TrainV2Result:
    bundle: dict
    report_md: str
    n_train: int
    n_val: int
    n_test: int
    chosen_model: str
    val_scores: dict
    test_recall: float
    test_pfa: float
    per_group_table: list = field(default_factory=list)


def train_v2(
    positives: list[str], negatives: list[str], *,
    out_path: str | Path = DEFAULT_MODEL_PATH,
    seed: int = 0, root: Path | None = None,
    fractions: dict | None = None,
) -> TrainV2Result | None:
    """Load, split, fit and package a ``features_v2`` bundle. Returns
    ``None`` if no rows were loaded for either side (caller should treat
    that as exit code 2). Raises :class:`SplitLeakError` on a split-spanning
    group (caller should treat that as exit code 4)."""
    root = root if root is not None else index_mod.dataset_root()
    pos = load_datasets(list(dict.fromkeys(positives)), root)
    neg = load_datasets(list(dict.fromkeys(negatives)), root)
    all_rows = pos.rows + neg.rows
    if not all_rows:
        return None

    y_all = np.array([binary_label(r) for r in all_rows])
    row_split = _assign_row_splits(all_rows, seed, fractions)
    _assert_group_splits_disjoint(all_rows, row_split)

    mask = bfv._common_columns(all_rows)
    full_mask = np.ones(fv2.FEATURES_V2_DIM, dtype=bool)
    X_all = bfv._matrix(all_rows, full_mask)

    idx_train = [i for i in range(len(all_rows)) if row_split[i] == "train"]
    idx_val = [i for i in range(len(all_rows)) if row_split[i] == "val"]
    idx_test = [i for i in range(len(all_rows)) if row_split[i] == "test"]

    Xtr, ytr = X_all[idx_train], y_all[idx_train]
    Xval, yval = X_all[idx_val], y_all[idx_val]
    Xtest, ytest = X_all[idx_test], y_all[idx_test]

    pipes = _pipelines(mask, seed)
    for name, pipe in pipes.items():
        _fit(pipe, Xtr, ytr, seed)

    val_scores = {name: _val_score(pipe, Xval, yval) for name, pipe in pipes.items()}
    chosen_name = max(val_scores, key=lambda n: (val_scores[n] if val_scores[n] == val_scores[n] else -1.0))
    chosen = pipes[chosen_name]

    test_rows = [all_rows[i] for i in idx_test]
    pred_test = chosen.predict(Xtest) if Xtest.shape[0] else np.array([])
    pos_mask = ytest == "drone_link"
    neg_mask = ~pos_mask
    test_recall = float(np.mean(pred_test[pos_mask] == "drone_link")) if pos_mask.any() else float("nan")
    test_pfa = float(np.mean(pred_test[neg_mask] == "drone_link")) if neg_mask.any() else float("nan")

    by_group: dict = defaultdict(list)
    for i, r in enumerate(test_rows):
        by_group[r.group].append(i)
    per_group_table = []
    for grp in sorted(by_group):
        idxs = by_group[grp]
        yt = ytest[idxs]
        pt = pred_test[idxs]
        gpos = yt == "drone_link"
        gneg = ~gpos
        states = np.array([test_rows[i].receiver_state for i in idxs], dtype=np.float64)
        per_group_table.append({
            "group": "/".join(grp),
            "n": len(idxs),
            "n_pos": int(gpos.sum()),
            "n_neg": int(gneg.sum()),
            "recall": float(np.mean(pt[gpos] == "drone_link")) if gpos.any() else float("nan"),
            "pfa": float(np.mean(pt[gneg] == "drone_link")) if gneg.any() else float("nan"),
            "median_dbfs": float(np.mean(states[:, 0])),
            "time_p99_dbfs": float(np.mean(states[:, 1])),
            "edge_minus_centre_db": float(np.mean(states[:, 2])),
        })

    feature_names = np.array(fv2.feature_names_v2())
    scene_counts = {
        split_name: dict(Counter(binary_label_scene(all_rows[i]) for i in idx))
        for split_name, idx in (("train", idx_train), ("val", idx_val), ("test", idx_test))
    }

    train_manifest = {
        "positives": positives,
        "negatives": negatives,
        "seed": seed,
        "git_sha": _git_sha(),
        "row_counts": {"train": len(idx_train), "val": len(idx_val), "test": len(idx_test)},
        "exclusion_counts": {**pos.skipped, **{f"neg:{k}": v for k, v in neg.skipped.items()}},
        "preproc_versions": {
            dsid: sorted(m.preproc_versions) for dsid, m in {**pos.meta_by_dataset, **neg.meta_by_dataset}.items()
        },
        "code_versions": {
            dsid: sorted(m.code_versions) for dsid, m in {**pos.meta_by_dataset, **neg.meta_by_dataset}.items()
        },
        "chosen_model": chosen_name,
        "val_scores": val_scores,
        "feature_columns_kept": int(mask.sum()),
        "feature_columns_total": fv2.FEATURES_V2_DIM,
        "scene_label_counts": scene_counts,
    }

    bundle = {
        "model": chosen,
        "kind": "sklearn",
        "features_version": fv2.FEATURES_VERSION,
        "feature_columns": feature_names[mask].tolist(),
        "feature_mask": mask,
        "classes": ["background", "drone_link"],
        "version": VERSION,
        "train_manifest": train_manifest,
        "claims": bfv.FRAMING_PARAGRAPH,
    }

    report_md = _format_report(
        positives=positives, negatives=negatives, seed=seed,
        pos=pos, neg=neg, row_split_counts=train_manifest["row_counts"],
        mask=mask, chosen_name=chosen_name, val_scores=val_scores,
        test_recall=test_recall, test_pfa=test_pfa,
        per_group_table=per_group_table, train_manifest=train_manifest,
    )

    return TrainV2Result(
        bundle=bundle, report_md=report_md,
        n_train=len(idx_train), n_val=len(idx_val), n_test=len(idx_test),
        chosen_model=chosen_name, val_scores=val_scores,
        test_recall=test_recall, test_pfa=test_pfa, per_group_table=per_group_table,
    )


def binary_label_scene(row) -> str:
    """The row's raw scene ``emitter_class`` (finer than the binary target,
    kept in the bundle's ``train_manifest`` for later multi-class work)."""
    return row.emitter_class


def _format_report(*, positives, negatives, seed, pos: LoadSummary, neg: LoadSummary,
                   row_split_counts: dict, mask: np.ndarray, chosen_name: str,
                   val_scores: dict, test_recall: float, test_pfa: float,
                   per_group_table: list, train_manifest: dict) -> str:
    lines = []
    lines.append("# features_v2 training report (signature_v2)\n")
    lines.append(f"positives: {positives}  negatives: {negatives}  seed: {seed}\n")
    lines.append(f"git sha: {train_manifest['git_sha']}\n")
    lines.append("")
    lines.append(bfv.FRAMING_PARAGRAPH)
    lines.append("")
    lines.append("## Row counts")
    lines.append("")
    lines.append(f"positives loaded: {len(pos.rows)} (skipped: {pos.skipped})")
    lines.append(f"negatives loaded: {len(neg.rows)} (skipped: {neg.skipped})")
    lines.append(f"split (group-level, 70/15/15): {row_split_counts}")
    lines.append(f"feature columns kept: {int(mask.sum())}/{fv2.FEATURES_V2_DIM} "
                 f"(G3 always masked -- no stored detector frames; G5 masked if any short window present)")
    lines.append("")
    lines.append("## Model selection")
    lines.append("")
    lines.append(f"validation scores (PR-AUC, or accuracy if val has one class): {val_scores}")
    lines.append(f"chosen model: **{chosen_name}**")
    lines.append("")
    lines.append("## Test set (held-out groups)")
    lines.append("")
    lines.append(f"overall recall (drone_link): {test_recall:.3f}")
    lines.append(f"overall PFA (background): {test_pfa:.3f}")
    lines.append("")
    lines.append("Per-group test recall/PFA, with the S5.1 receiver-state diagnostic "
                 "(median_dbfs / time_p99_dbfs / edge_minus_centre_db) alongside each group "
                 "-- diagnostic only, never a feature; an outlier here flags a receiver-state "
                 "change, not necessarily a scene change:")
    lines.append("")
    lines.append("| group | n | n_pos | n_neg | recall | pfa | median_dbfs | time_p99_dbfs | edge-centre_db |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in per_group_table:
        def fmt(v):
            return "n/a" if v != v else f"{v:.3f}"
        lines.append(
            f"| {row['group']} | {row['n']} | {row['n_pos']} | {row['n_neg']} | "
            f"{fmt(row['recall'])} | {fmt(row['pfa'])} | {fmt(row['median_dbfs'])} | "
            f"{fmt(row['time_p99_dbfs'])} | {fmt(row['edge_minus_centre_db'])} |"
        )
    lines.append("")
    lines.append("No PD/cross-receiver claim is made for this bundle -- see the framing "
                 "paragraph above; the per-group table is evidence-level 2 (probabilistic "
                 "classification) against evidence-level 5 scene truth, same as the F3 benchmark.")
    return "\n".join(lines) + "\n"


def save_bundle(bundle: dict, out_path: str | Path) -> Path:
    import joblib
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out)
    return out


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train a features_v2 stage-2 bundle")
    ap.add_argument("--positives", nargs="+", required=True, help="dataset_id(s) with drone_link rows")
    ap.add_argument("--negatives", nargs="+", required=True, help="dataset_id(s) with background rows")
    ap.add_argument("--out", default=str(DEFAULT_MODEL_PATH))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--root", default=None, help="dataset root override ($AERIX_RF_DATASET_ROOT default)")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else None
    try:
        result = train_v2(args.positives, args.negatives, out_path=args.out, seed=args.seed, root=root)
    except SplitLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    if result is None:
        print("error: no rows loaded for --positives/--negatives", file=sys.stderr)
        return 2

    out = save_bundle(result.bundle, args.out)
    report_path = Path(str(out) + ".md")
    report_path.write_text(result.report_md, encoding="utf-8")

    print(f"rows: train={result.n_train} val={result.n_val} test={result.n_test}")
    print(f"chosen model: {result.chosen_model}  val_scores={result.val_scores}")
    print(f"test recall={result.test_recall:.3f}  test pfa={result.test_pfa:.3f}")
    print(f"bundle: {out}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
