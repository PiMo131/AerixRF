"""Real-IQ DroneID decoder regression fixture (RUB-SysSec DroneSecurity captures).

Frozen against two real DJI OcuSync<=2.0 DroneID captures from the RUB-SysSec
DroneSecurity repo (AGPL-3.0): a Mavic Air 2 burst and a Mini 2 SE burst with a
custom "SysSecWasHere" serial. These are pre-segmented candidate slices, not
continuous spectrum captures.

Samples are NOT distributed with this repo (AGPL-3.0 license forbids bundling
them here). The test locates them via AERIX_RF_DATASET_ROOT (default
~/rf-datasets) and skips entirely if the dataset directory is absent, so CI/dev
environments without the dataset are unaffected. See
~/rf-datasets/RUB-DroneSecurity/original/SOURCE.md for provenance and sha256
pins.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from aerix_rf.decode.droneid import decode_all

SAMPLE_RATE = 50e6

DATASET_ROOT = Path(os.environ.get("AERIX_RF_DATASET_ROOT", "~/rf-datasets")).expanduser()
SAMPLES_DIR = DATASET_ROOT / "RUB-DroneSecurity" / "original" / "samples"

SHA256 = {
    "mavic_air_2": "623fa40f190d3fd859ec2fd62b379ad9a01a0485db3179ae29ac2e3c7a070450",
    "mini2_sm": "5a17913cb11cde2919347054700345c9e5595eaff7818980d332b8ac8910bc55",
}

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rub_droneid_expected.json"

# Fields carried on aerix_rf.decode.droneid.DroneIdResult. parse_frame's fuller
# DroneIdFrame also has velocity/yaw and state0/state1, which are not threaded
# through DroneIdResult/decode_all (frame.py's DroneIdFrame/parse_frame were not
# extended to carry state bits in this change; see the handback for that gap).
STABLE_FIELDS = (
    "serial", "drone_lat", "drone_lon", "operator_lat", "operator_lon",
    "protocol", "drone_height", "drone_altitude", "home_lat", "home_lon",
    "sequence", "product_type", "uuid", "gps_time_ms", "semantic_flags",
    "evidence_quality",
)

pytestmark = pytest.mark.skipif(
    not SAMPLES_DIR.is_dir(),
    reason=f"RUB-SysSec DroneSecurity dataset not found at {SAMPLES_DIR} "
           "(set AERIX_RF_DATASET_ROOT or fetch the dataset)",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_iq(name: str) -> np.ndarray:
    path = SAMPLES_DIR / name
    assert _sha256(path) == SHA256[name], f"{name}: sha256 mismatch, dataset changed?"
    return np.memmap(path, dtype="<f").astype(np.float32).view(np.complex64)


def _result_dict(result) -> dict:
    return {field: getattr(result, field) for field in STABLE_FIELDS}


def _good_attempts(iq: np.ndarray) -> list:
    attempts = decode_all(iq, SAMPLE_RATE, budget_s=None, max_bursts=32)
    return [a for a in attempts if a.level == "C" and a.crc_ok]


def test_mavic_air_2_single_frame():
    iq = _load_iq("mavic_air_2")
    good = _good_attempts(iq)
    assert len(good) == 1, f"expected exactly 1 CRC-valid frame, got {len(good)}"
    r = good[0].result
    assert r.serial == "1WNBH3900201N1"
    assert r.sequence == 591
    assert round(r.drone_lat, 5) == round(51.446356, 5)
    assert round(r.drone_lon, 5) == round(7.267219, 5)
    # Real GPS-locked frame: no semantic flags at all (evidence-quality label,
    # never a filter -- the frame is kept either way; see
    # protocol_droneid_evidence_gating.md).
    assert r.product_type == 58
    assert r.semantic_flags == []
    assert r.evidence_quality == "clean"


def test_mini2_sm_ten_frames():
    iq = _load_iq("mini2_sm")
    good = _good_attempts(iq)
    assert len(good) == 10, f"expected exactly 10 CRC-valid frames, got {len(good)}"

    sequences = [a.result.sequence for a in good]
    # Exact sequence list as observed from a real decode_all run (duplicates and
    # gaps are real: the capture is a pre-segmented candidate slice, not a clean
    # continuous burst train).
    assert sequences == [786, 787, 788, 788, 789, 800, 804, 804, 805, 806]

    op_lats = {round(a.result.operator_lat, 5) for a in good}
    op_lons = {round(a.result.operator_lon, 5) for a in good}
    assert op_lats == {round(51.447198, 5)}
    assert op_lons == {round(7.266532, 5)}

    # duplicates/gaps -> sequence_non_monotonic on the later of the pair (indices
    # 3, 5, 6, 7 of the list above: 788 dup, 800 gap, 804 gap, 804 dup); never on
    # the first frame in the window.
    seq_flagged = ["sequence_non_monotonic" in a.result.semantic_flags for a in good]
    assert seq_flagged == [False, False, False, True, False, True, True, True, False, False]

    for a in good:
        r = a.result
        assert r.serial == "SysSecWasHere "
        assert r.drone_lat == 0.0
        assert r.drone_lon == 0.0
        # RUB README: this capture has no GPS lock -- drone (and the
        # GPS-fix-derived home point) position is exact-zero and flagged as
        # such, but the operator/app position (phone GPS) is real and clean.
        assert r.product_type == 63
        assert "drone_coords_zero" in r.semantic_flags
        assert "home_coords_zero" in r.semantic_flags
        assert "operator_coords_zero" not in r.semantic_flags
        assert r.evidence_quality == "flagged"


def test_frame_fields_match_frozen_fixture():
    """Guard the full decoded field set against silent decoder drift."""
    with open(FIXTURE_PATH) as f:
        expected = json.load(f)

    for name in ("mavic_air_2", "mini2_sm"):
        iq = _load_iq(name)
        good = _good_attempts(iq)
        actual = [_result_dict(a.result) for a in good]
        exp = expected[name]
        assert len(actual) == len(exp), f"{name}: frame count drifted"
        for got, want in zip(actual, exp):
            for field in STABLE_FIELDS:
                got_v, want_v = got[field], want[field]
                if isinstance(want_v, float):
                    assert got_v == pytest.approx(want_v, abs=1e-6), (
                        f"{name}.{field}: {got_v} != {want_v}"
                    )
                else:
                    assert got_v == want_v, f"{name}.{field}: {got_v!r} != {want_v!r}"
