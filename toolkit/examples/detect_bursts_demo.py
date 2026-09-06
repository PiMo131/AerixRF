#!/usr/bin/env python
"""Detect bursts in a SigMF capture and print the burst table and per-emitter features.

Pipeline (the same one a live E200 dwell will go through):

1. read the capture (memory-mapped) and its metadata,
2. STFT power map in dBFS on an absolute, ascending frequency axis,
3. 2-D energy burst detection: robust per-bin noise floor + threshold,
   binary closing to bridge chirp wraps / short dropouts, connected
   components -> time-frequency boxes,
4. if the file carries truth annotations (``core:freq_lower_edge`` etc., as
   written by ``make_synthetic_capture.py``), match detections to them by
   IoU so each row gets a label,
5. print the burst table and a :class:`BurstFeatures` table for all bursts
   and for each label - this is the raw material for the classifier.

Usage::

    python examples/detect_bursts_demo.py STEM [--fft-size 1024] [--threshold-db 10]
                                               [--max-rows 40] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence

import numpy as np

from antsdr_toolkit.dsp.bursts import Burst, detect_bursts, match_bursts
from antsdr_toolkit.dsp.features import BurstFeatures, burst_features, bursts_to_table
from antsdr_toolkit.dsp.spectrum import stft_power_db
from antsdr_toolkit.io.sigmf_io import SigmfReader

UNMATCHED = "unmatched"


def truth_from_annotations(annotations: Sequence[Mapping], sample_rate_hz: float) -> list[dict]:
    """SigMF annotations with frequency edges -> truth boxes for :func:`match_bursts`."""
    rows = []
    for ann in annotations:
        if "core:freq_lower_edge" not in ann or "core:freq_upper_edge" not in ann:
            continue
        start = int(ann["core:sample_start"])
        count = int(ann.get("core:sample_count", 0))
        rows.append(
            {
                "t_start_s": start / sample_rate_hz,
                "t_end_s": (start + count) / sample_rate_hz,
                "f_low_hz": float(ann["core:freq_lower_edge"]),
                "f_high_hz": float(ann["core:freq_upper_edge"]),
                "label": str(ann.get("core:label", "unlabelled")),
            }
        )
    return rows


def label_detections(
    bursts: Sequence[Burst], truth: Sequence[dict], *, min_iou: float
) -> tuple[list[str], list[int]]:
    """Label each detection with its matched truth label; also return missed truth indices."""
    labels = [UNMATCHED] * len(bursts)
    pairs, _unmatched_detected, missed = match_bursts(bursts, truth, min_iou=min_iou)
    for det_index, truth_index in pairs:
        labels[det_index] = truth[truth_index]["label"]
    return labels, missed


def format_feature(name: str, value: float) -> str:
    """Human units for a BurstFeatures field: Hz -> MHz, s -> ms, dB as is."""
    if name in ("n_bursts", "n_distinct_centers"):
        return f"{int(value)}"
    if name == "hop_rate_hz":
        return f"{value:.1f} Hz"
    if name.endswith("_hz"):
        return f"{value / 1e6:.3f} MHz"
    if name.endswith("_s"):
        return f"{value * 1e3:.3f} ms"
    if name.endswith("_db"):
        return f"{value:.1f} dB"
    return f"{value:.3f}"


def print_burst_table(bursts: Sequence[Burst], labels: Sequence[str], max_rows: int) -> None:
    print(
        f"{'#':>4} {'t_start ms':>11} {'dur us':>9} {'f_low MHz':>11} {'f_high MHz':>11} "
        f"{'bw MHz':>8} {'peak dB':>8} {'snr dB':>7}  label"
    )
    for index, (burst, label) in enumerate(zip(bursts, labels)):
        if index >= max_rows:
            print(f"  ... {len(bursts) - max_rows} more rows (raise --max-rows)")
            break
        print(
            f"{index:>4} {burst.t_start_s * 1e3:>11.3f} {burst.duration_s * 1e6:>9.1f} "
            f"{burst.f_low_hz / 1e6:>11.3f} {burst.f_high_hz / 1e6:>11.3f} "
            f"{burst.bandwidth_hz / 1e6:>8.3f} {burst.peak_db:>8.1f} {burst.snr_db:>7.1f}  {label}"
        )


def print_feature_table(groups: Mapping[str, BurstFeatures]) -> None:
    names = list(next(iter(groups.values())).to_dict())
    columns = list(groups)
    cells = {name: [format_feature(name, groups[c].to_dict()[name]) for c in columns] for name in names}
    widths = [max(len(c), *(len(cells[n][i]) for n in names)) for i, c in enumerate(columns)]
    print(f"{'feature':<26} " + " ".join(f"{c:>{w}}" for c, w in zip(columns, widths)))
    for name in names:
        print(f"{name:<26} " + " ".join(f"{v:>{w}}" for v, w in zip(cells[name], widths)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", help="SigMF stem, .sigmf-meta or .sigmf-data")
    parser.add_argument("--fft-size", type=int, default=1024, help="STFT size (hop = half)")
    parser.add_argument("--threshold-db", type=float, default=10.0,
                        help="detection threshold above the mean noise power")
    parser.add_argument("--close-time-us", type=float, default=100.0,
                        help="bridge time gaps up to this many microseconds")
    parser.add_argument("--close-freq-khz", type=float, default=500.0,
                        help="bridge frequency gaps up to this many kHz (LoRa chirp wraps)")
    parser.add_argument("--min-iou", type=float, default=0.3,
                        help="IoU needed to match a detection to a truth annotation")
    parser.add_argument("--max-rows", type=int, default=40, help="burst rows to print")
    parser.add_argument("--json", action="store_true", help="print bursts and features as JSON")
    args = parser.parse_args(argv)

    with SigmfReader(args.path, mmap=True) as reader:
        info = reader.info
        samples = reader.samples
        iq = samples if samples.ndim == 1 else samples[0]  # first channel of a 2x2 capture
        window_s = reader.duration_s
        truth = truth_from_annotations(reader.annotations, info.sample_rate_hz)
        fs, fc = info.sample_rate_hz, info.center_freq_hz
        power_db, freqs_hz, times_s = stft_power_db(iq, fs, fc, fft_size=args.fft_size)

    frame_s = (args.fft_size // 2) / fs
    bin_hz = fs / args.fft_size
    bursts = detect_bursts(
        power_db,
        freqs_hz,
        times_s,
        threshold_db=args.threshold_db,
        min_duration_s=3 * frame_s,  # drop isolated false-alarm cells: >= 3 frames ...
        min_bandwidth_hz=3 * bin_hz,  # ... and >= 3 bins
        close_time_s=args.close_time_us * 1e-6,
        close_freq_hz=args.close_freq_khz * 1e3,
    )
    labels, missed = label_detections(bursts, truth, min_iou=args.min_iou)

    groups: dict[str, BurstFeatures] = {"all": burst_features(bursts, window_s=window_s)}
    for label in sorted(set(labels)):
        subset = [b for b, lab in zip(bursts, labels) if lab == label]
        groups[label] = burst_features(subset, window_s=window_s)

    if args.json:
        rows = [dict(row, label=label) for row, label in zip(bursts_to_table(bursts), labels)]
        print(json.dumps({"bursts": rows, "features": {k: v.to_dict() for k, v in groups.items()}},
                         indent=2))
        return 0

    print(f"# {info}")
    print(f"# {power_db.shape[0]} frames x {power_db.shape[1]} bins "
          f"({frame_s * 1e6:.1f} us x {bin_hz / 1e3:.1f} kHz), {window_s * 1e3:.1f} ms")
    print(f"# floor {np.percentile(power_db, 20):.1f} dBFS (20th pct), "
          f"threshold +{args.threshold_db:.1f} dB, {len(bursts)} bursts detected")
    if truth:
        n_matched = sum(lab != UNMATCHED for lab in labels)
        print(f"# truth: {len(truth)} annotations, {n_matched} matched, "
              f"{len(bursts) - n_matched} unmatched detections, {len(missed)} missed")
    print()
    print_burst_table(bursts, labels, args.max_rows)
    print()
    print_feature_table(groups)
    return 0


if __name__ == "__main__":
    sys.exit(main())
