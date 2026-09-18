"""Append-only JSONL index of prepared-window sidecars (section 6 of the memo:

    "A flat index.jsonl (one row per window, all scalar sidecar fields) is
    the only thing trainers and splitters read -- never a directory walk."

Layout: ``<dataset_root>/<dataset_id>/prepared/index.jsonl``, one
``WindowSidecar`` JSON object per line, appended in write order.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .spec import Split, WindowSidecar

DATASET_ROOT_ENV = "AERIX_RF_DATASET_ROOT"
DATASET_ROOT_DEFAULT = "~/rf-datasets"

GroupKey = tuple[str, str, str]


def dataset_root() -> Path:
    """Resolve the dataset root: ``$AERIX_RF_DATASET_ROOT`` or ``~/rf-datasets``."""
    raw = os.environ.get(DATASET_ROOT_ENV) or DATASET_ROOT_DEFAULT
    return Path(raw).expanduser()


def _index_path(dataset_id: str, root: Path | None = None) -> Path:
    base = root if root is not None else dataset_root()
    return base / dataset_id / "prepared" / "index.jsonl"


def append(sidecar: WindowSidecar, root: Path | None = None) -> Path:
    """Append one sidecar as a JSONL row to its dataset's index. Returns the
    index file path."""
    path = _index_path(sidecar.identity.dataset_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(sidecar.model_dump_json())
        fh.write("\n")
    return path


def iter_dataset(dataset_id: str, root: Path | None = None) -> Iterator[WindowSidecar]:
    """Iterate the sidecars of a single dataset's index, in write order."""
    path = _index_path(dataset_id, root)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield WindowSidecar.model_validate_json(line)


def iter_all(root: Path | None = None) -> Iterator[WindowSidecar]:
    """Iterate every dataset's index under the dataset root."""
    base = root if root is not None else dataset_root()
    if not base.exists():
        return
    for dataset_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        yield from iter_dataset(dataset_dir.name, root=base)


def filter_index(
    sidecars: Iterable[WindowSidecar],
    dataset_id: str | None = None,
    device_id: str | None = None,
    split: Split | None = None,
) -> list[WindowSidecar]:
    """Filter an in-memory (or streamed) sequence of sidecars by dataset,
    device and/or split."""
    out = []
    for sc in sidecars:
        if dataset_id is not None and sc.identity.dataset_id != dataset_id:
            continue
        if device_id is not None and sc.identity.device_id != device_id:
            continue
        if split is not None and sc.bookkeeping.split != split:
            continue
        out.append(sc)
    return out


def group_key(sidecar: WindowSidecar) -> GroupKey:
    """Leakage-safe split group (section 4): (dataset_id, device_id, run_id)."""
    return (sidecar.identity.dataset_id, sidecar.identity.device_id, sidecar.identity.run_id)


def assign_splits(
    sidecars: Sequence[WindowSidecar],
    seed: int = 0,
    fractions: dict[str, float] | None = None,
) -> dict[GroupKey, Split]:
    """Deterministically assign every group in `sidecars` to a Split.

    Assignment is by GROUP, never by window: every window sharing a
    ``(dataset_id, device_id, run_id)`` group key gets the same split. The
    result depends only on the seed and the set of group keys present, not on
    input order or on per-window fields, so it is stable under reordering and
    repeatable given the same groups and seed.
    """
    fractions = fractions or {"train": 0.8, "val": 0.1, "test": 0.1}
    total = sum(fractions.values())
    if total <= 0:
        raise ValueError("fractions must sum to a positive number")

    # Cumulative boundaries in a fixed, deterministic key order (not the
    # dict's insertion order, so callers passing the same fractions in a
    # different order still get the same partition).
    names = sorted(fractions)
    cum = []
    acc = 0.0
    for name in names:
        acc += fractions[name] / total
        cum.append((name, acc))

    groups = sorted({group_key(sc) for sc in sidecars})
    result: dict[GroupKey, Split] = {}
    for grp in groups:
        key = f"{seed}:{grp[0]}\x1f{grp[1]}\x1f{grp[2]}".encode("utf-8")
        digest = hashlib.sha256(key).digest()
        position = int.from_bytes(digest, "big") / (2 ** (8 * len(digest)))
        for name, boundary in cum:
            if position < boundary:
                result[grp] = Split(name)
                break
        else:
            result[grp] = Split(names[-1])
    return result
