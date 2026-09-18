"""Smoke test for bench/canonical_rate_sweep.py: keeps the script importable
and its sweep loop correct without paying for a real sweep. Must run < 60 s.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))

import canonical_rate_sweep as crs  # noqa: E402


def test_sweep_smoke_runs_and_has_expected_shape():
    labels = ["A_legacy_20msps", "B_canonical_15p36msps", "C_fallback_11p52msps"]
    snr_values = [-2.0, 5.0, 15.0]
    summary = crs.run_sweep(trials=2, snr_values=snr_values, labels=labels,
                            max_workers=None)

    assert set(summary.keys()) == set(labels)
    for label in labels:
        curve = summary[label]["curve"]
        assert len(curve) == len(snr_values)
        for point in curve:
            assert point["n"] == 2
            assert 0.0 <= point["crc_frac"] <= 1.0
            assert 0.0 <= point["serial_frac"] <= 1.0
            assert point["mean_decode_s"] >= 0.0
        # crc_frac can never be lower than serial_frac (serial requires crc_ok).
        assert all(c["serial_frac"] <= c["crc_frac"] for c in curve)

    # High-SNR clean-ish trials should decode far more often than -2 dB ones,
    # at least for the canonical arm (sanity check the pipeline is wired up).
    b_curve = {p["snr_db"]: p for p in summary["B_canonical_15p36msps"]["curve"]}
    assert b_curve[15.0]["serial_frac"] >= b_curve[-2.0]["serial_frac"]


def test_snr50_interpolation():
    assert crs._interp_snr50([]) is None
    assert crs._interp_snr50([(0.0, 1.0)]) == 0.0
    assert crs._interp_snr50([(0.0, 0.0), (10.0, 1.0)]) == 5.0
    assert crs._interp_snr50([(0.0, 0.0), (10.0, 0.4)]) is None


def test_markdown_table_and_quant_profile_smoke():
    summary = crs.run_sweep(trials=2, snr_values=[5.0], labels=["B_cs8", "B_cs12"],
                            max_workers=None)
    table = crs._markdown_table(summary)
    assert "B_cs8" in table and "B_cs12" in table
