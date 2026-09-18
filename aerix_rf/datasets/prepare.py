"""S1->S4 "prepare" pipeline + tiny CLI (Workstream D, T4).

For each recording an :class:`~aerix_rf.datasets.adapters.Adapter` reports,
runs the full pipeline described in ``docs/design/dataset-normalization.md``:

    S0 sha256 original -> S1 adapter.load_iq -> S2 plan_chain/apply_chain to
    15.36 MS/s -> S3 iter_windows -> per window: optional <uid>.c64.npy,
    always <uid>.tensor.npy (ml_tensor) + <uid>.json sidecar -> append to
    prepared/index.jsonl.

Deterministic: given the same original files, adapter and config, a rerun
produces byte-identical ``.npy`` artefacts and identical sidecars except
``bookkeeping.created_at``. Output lives under
``<root>/<dataset_id>/prepared/`` -- ``original/`` is never written to.

Note: this task's pipeline applies a single :func:`~aerix_rf.datasets.resample.plan_chain`
decimate to the canonical rate with no S2 frequency re-centring/tiling
(``mix_and_slice`` exists but is not invoked here). For a source recorded far
wider than the canonical 15.36 MS/s span with its emitter of interest away
from DC (e.g. Zenodo's 120/200 MS/s files), this keeps only the band nearest
DC after resampling, which will not always be the drone signal. That is a
known limitation of this task's scope, not of ``resample.py`` -- flagged in
the handback report as an item for a follow-up S2-tiling task, per the
normalisation memo's S2 "source wider than 12 MHz: tile" rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from .adapters import ADAPTERS, Adapter, source_file_field, source_sha256
from .index import append, dataset_root
from .resample import CANONICAL_RATE_HZ, apply_chain, plan_chain, usable_bandwidth
from .spec import (
    BookkeepingGroup,
    ClockInfo,
    GainInfo,
    GainMode,
    Identity,
    LevelsGroup,
    ReceiverDevice,
    ReceiverGroup,
    SignalInfo,
    Split,
    SourceInfo,
    StageEntry,
    WindowSidecar,
)
from .tensor import ml_tensor
from .window import iter_windows

PREPROC_VERSION = "v1"

_PREPROC_CONFIG_V1 = {
    "preproc_version": PREPROC_VERSION,
    "canonical_rate_hz": CANONICAL_RATE_HZ,
    "window_s": 1.0,
    "grid_ms": 1,
    "tensor_fft": 1024,
    "tensor_hop": 512,
}

_CONFIG_SHA256 = hashlib.sha256(
    json.dumps(_PREPROC_CONFIG_V1, sort_keys=True).encode("utf-8")
).hexdigest()


def _git_sha() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


_CODE_VERSION = _git_sha()

_IO_SOURCES = {
    "int16_interleaved": ("int16_full_scale_32768", "interleaved_i2"),
    "float32_interleaved": ("native_unit_scale_assumed", "interleaved_f4"),
    # AerixSessionAdapter's own session.json-recorded formats (Workstream D,
    # T5): the full scale is never assumed -- it is whatever session.json's
    # per-file/session `iq_full_scale` says (128.0 for cs8, 2048.0 for
    # ANTSDR/AD9361 cs16) -- hence "session_metadata", not a fixed constant
    # like the two entries above.
    "cs8": ("session_metadata", "interleaved_i1"),
    "cs16": ("session_metadata", "interleaved_i2"),
}


@dataclass
class PrepareStats:
    dataset_id: str
    recordings: int = 0
    windows: int = 0
    short_windows: int = 0
    bytes_written: int = 0
    wall_time_s: float = 0.0
    example_sidecar: Optional[dict] = None
    tensor_shape_example: Optional[tuple] = None


def _uid(source_sha256_: str, source_file: str, slice_spec: str, window_index: int) -> str:
    key = "|".join([source_sha256_, source_file, slice_spec, str(window_index), _CONFIG_SHA256])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _write_npy(path_stem: Path, arr: np.ndarray) -> Path:
    """``np.save`` appends ``.npy`` to a filename that doesn't already end
    with it -- so ``path_stem`` here is e.g. ``<dir>/<uid>.tensor``, and the
    file actually written is ``<dir>/<uid>.tensor.npy``."""

    np.save(str(path_stem), arr, allow_pickle=False)
    return Path(str(path_stem) + ".npy")


def prepare_dataset(
    dataset_id: str,
    adapter: Adapter,
    root: Path | None = None,
    limit: int | None = None,
    write_iq: bool = False,
    write_tensor: bool = True,
) -> PrepareStats:
    """Run S1->S4 for up to ``limit`` recordings of ``dataset_id`` using
    ``adapter``. Writes artefacts + sidecars under
    ``<root>/<dataset_id>/prepared/`` and appends every sidecar to
    ``prepared/index.jsonl``. Returns summary :class:`PrepareStats`."""

    import time

    root = root if root is not None else dataset_root()
    dataset_dir = root / dataset_id
    prepared_dir = dataset_dir / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)

    stats = PrepareStats(dataset_id=dataset_id)
    t0 = time.monotonic()

    recordings = list(adapter.iter_recordings(root))
    if limit is not None:
        recordings = recordings[:limit]

    for rec in recordings:
        stats.recordings += 1
        src_sha256 = source_sha256(rec)
        src_file = source_file_field(rec)

        raw_iq, in_rate_hz, centre_hz, bw_hz = adapter.load_iq(rec)
        centre_hz = centre_hz if centre_hz is not None else rec.original_center_freq_hz
        bw_hz = bw_hz if bw_hz is not None else rec.original_bw_hz

        chain = plan_chain(in_rate_hz, CANONICAL_RATE_HZ, in_bw_hz=bw_hz)
        canonical_iq = apply_chain(raw_iq, chain, in_rate_hz)
        usable_bw_hz, band_deficit = usable_bandwidth(in_rate_hz, bw_hz)

        iq_full_scale_source, iq_format_source = _IO_SOURCES.get(
            rec.original_dtype, ("unknown", "unknown")
        )

        labels = adapter.labels(rec)

        for window_index, (start, iq_window, short) in enumerate(
            iter_windows(canonical_iq, CANONICAL_RATE_HZ, window_s=1.0, grid_ms=1)
        ):
            slice_spec = f"{rec.recording_id}|{rec.channel_id or ''}"
            uid = _uid(src_sha256, src_file, slice_spec, window_index)

            tensor = ml_tensor(iq_window, CANONICAL_RATE_HZ)
            noise_floor_dbfs = float(np.median(tensor)) if tensor.size else None

            artifact_sha256: Optional[str] = None
            if write_iq:
                iq_path = _write_npy(prepared_dir / f"{uid}.c64", iq_window.astype(np.complex64))
                stats.bytes_written += iq_path.stat().st_size
            if write_tensor:
                tensor_path = _write_npy(prepared_dir / f"{uid}.tensor", tensor)
                stats.bytes_written += tensor_path.stat().st_size
                artifact_sha256 = hashlib.sha256(tensor_path.read_bytes()).hexdigest()
                if stats.tensor_shape_example is None:
                    stats.tensor_shape_example = tuple(tensor.shape)

            n_samples = int(iq_window.shape[-1])
            duration_s = n_samples / CANONICAL_RATE_HZ

            sidecar = WindowSidecar(
                identity=Identity(
                    uid=uid,
                    dataset_id=dataset_id,
                    recording_id=rec.recording_id,
                    source_file=src_file,
                    source_sha256=src_sha256,
                    device_id=rec.device_id,
                    run_id=rec.run_id,
                    capture_group=rec.capture_group,
                    channel_id=rec.channel_id,
                    slice_index=window_index,
                    slice_reason=None,
                ),
                signal=SignalInfo(
                    sample_rate_hz=CANONICAL_RATE_HZ,
                    duration_s=duration_s,
                    n_samples=n_samples,
                    center_freq_hz=centre_hz,
                    bandwidth_hz=CANONICAL_RATE_HZ,
                    usable_bw_hz=usable_bw_hz,
                    band_deficit=band_deficit,
                    short_window=short,
                ),
                source=SourceInfo(
                    original_rate_hz=in_rate_hz,
                    original_dtype=rec.original_dtype,
                    original_center_freq_hz=centre_hz,
                    original_bw_hz=bw_hz,
                    iq_full_scale_source=iq_full_scale_source,
                    iq_format_source=iq_format_source,
                    resample_chain=chain,
                ),
                receiver=ReceiverGroup(
                    receiver=ReceiverDevice(
                        type="third_party_dataset",
                        backend=dataset_id,
                        firmware=None,
                        driver=None,
                        antenna=None,
                    ),
                    gain=GainInfo(mode=GainMode.UNKNOWN, changed_within_window=False),
                    dc_offset_corrected=None,
                    quadrature_corrected=None,
                    clock=ClockInfo(source=None, pps_locked=None),
                ),
                levels=LevelsGroup(
                    noise_floor_dbfs=noise_floor_dbfs,
                    rssi_dbfs=None,
                    occupied_bw_hz=None,
                    bw_saturated=False,
                    calibrated=False,
                ),
                labels=labels,
                notes=rec.notes,
                bookkeeping=BookkeepingGroup(
                    stage_entry=StageEntry.S1,
                    preproc_version=PREPROC_VERSION,
                    config_sha256=_CONFIG_SHA256,
                    code_version=_CODE_VERSION,
                    artifact_sha256=artifact_sha256,
                    split=Split.UNASSIGNED,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ),
            )

            append(sidecar, root=root)
            sidecar_path = prepared_dir / f"{uid}.json"
            sidecar_path.write_text(sidecar.model_dump_json(indent=2), encoding="utf-8")
            stats.bytes_written += sidecar_path.stat().st_size

            if stats.example_sidecar is None:
                stats.example_sidecar = json.loads(sidecar.model_dump_json())

            stats.windows += 1
            if short:
                stats.short_windows += 1

    stats.wall_time_s = time.monotonic() - t0
    return stats


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aerix_rf.datasets.prepare")
    parser.add_argument("--dataset", required=True, choices=sorted(ADAPTERS))
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--write-iq", action="store_true")
    parser.add_argument("--no-tensor", action="store_true")
    args = parser.parse_args(argv)

    adapter = ADAPTERS[args.dataset]
    stats = prepare_dataset(
        dataset_id=args.dataset,
        adapter=adapter,
        root=args.root,
        limit=args.limit,
        write_iq=args.write_iq,
        write_tensor=not args.no_tensor,
    )
    print(
        json.dumps(
            {
                "dataset_id": stats.dataset_id,
                "recordings": stats.recordings,
                "windows": stats.windows,
                "short_windows": stats.short_windows,
                "bytes_written": stats.bytes_written,
                "wall_time_s": round(stats.wall_time_s, 3),
                "tensor_shape_example": stats.tensor_shape_example,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
