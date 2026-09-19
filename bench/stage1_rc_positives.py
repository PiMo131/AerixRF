"""Stage-1 raster/period rule validation against REAL RC-transmitter IQ
(RFUAV corpus) plus an ANTSDR-ambient control.

Runs the SAME live Stage-1 entry point (``aerix_rf.detect.energy.detect``,
which internally does STFT -> ``bursts.detect_bursts`` -> ``raster.
analyze_raster``) over real RC-transmitter captures from the RFUAV dataset
(``~/rf-datasets/rfuav/original/extracted/<MODEL>/``), for every
RC-transmitter model (DJI/Autel airframes excluded -- those are drone
downlinks, not the RC uplink families this task is about).

Per window this script reports BOTH:
  * "full_band": ``detect()`` run at the recording's NATIVE rate (up to
    100 MS/s per the RFUAV XML) and native centre frequency, i.e. the full
    IFBandwidth the capture device recorded -- shows the true hop-set width
    a wideband capture can see.
  * "dwell": the recording re-centred (``resample.mix_and_slice``) on its
    OWN strongest-activity bin, then resampled (``resample.plan_chain`` /
    ``apply_chain``, canonical/live grade) down to the 15.36 MS/s canonical
    rate -- i.e. what a live 12 MHz-usable AERIX RF dwell would have seen if
    it happened to be tuned there. This is expected to see FEWER distinct
    channels than full_band for any hop set wider than ~12 MHz (e.g. FrSky's
    47-channel, ~94 MHz-wide hop set) -- reported as ``INSUFFICIENT_CHANNELS``
    dominance, not a rule failure.

``aerix_rf/detect/*`` is NOT modified by this script or as a result of
running it: this is read-only validation. Where a rule's real-data behaviour
looks wrong, the numbers are reported in
``docs/design/stage1-rc-positives-2026-09-19.md`` for a DSP-specialist
decision, never silently patched here.

Evidence level: RFUAV is a lab/anechoic-style capture with dataset-supplied
metadata, not an AERIX-operated live receiver -- level 2 (probabilistic
morphology/classification) at best; see the report's caveat paragraph.

Usage:
    uv run python bench/stage1_rc_positives.py [--workers N] [--out FILE] [--json-out FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

RFUAV_ROOT = Path.home() / "rf-datasets" / "rfuav" / "original" / "extracted"
ANTSDR_ROOT = Path.home() / "rf-datasets" / "aerix_antsdr_ambient_2026_09_18" / "original"
ANTSDR_SESSION_SUBSTR = ("soak10min_b", "probe_default", "probe_k32_4m", "a_iq_default")
ANTSDR_CONTROL_TARGET_WINDOWS = 100

MAX_RECORDINGS_PER_MODEL = 3
MAX_SLICES_PER_RECORDING = 10

# Dwell re-centre selection (fix for the C6 bench-only defect, docs/design/
# stage1-rc-positives-2026-09-19.md sec 3/4 item 6): raw argmax(mean PSD)
# landed on the extreme band edge (2390.0 MHz, a roll-off artefact) for
# FLYSKY/FRSKY, so the `dwell` column mostly measured a band edge, not the
# link. See ``_dwell_center_by_occupancy``.
_DWELL_WINDOW_HZ = 10.0e6      # width of the emulated dwell window
_DWELL_EDGE_GUARD_HZ = 5.0e6   # exclude >= this much at both band edges
_DWELL_DC_GUARD_HZ = 200.0e3   # exclude the DC-bin region from the score
_DWELL_OCCUPANCY_DB = 6.0      # "above floor" threshold for the occupancy metric

_IQ_STEM_RE = re.compile(r"^pack(\d+)_(\d+)-(\d+)s$")

LEVEL1_LEVEL2_LABELS = (
    "fhss_1mhz_grid_candidate",
    "fhss_2mhz_grid_candidate",
    "rc_link_family_candidate",
    "hopping_candidate",
    "fixed_channel_burst_candidate",
    "droneid_cadence_candidate",
)
TAGS = ("wifi_beacon_like", "ble_connection_like", "wifi_like_wideband", "INSUFFICIENT_CHANNELS")

# Per-model expected raster/period facts (research/briefs/rc-link-raster-facts.md
# "DIY-Multiprotocol primary tables" + task packet). None means "no primary
# table -- report observed only", never a guessed number.
_MODEL_EXPECT: dict[str, dict[str, Any]] = {
    "FLYSKY_FS_I6X": {"protocol": "FlySky AFHDS2A", "period_s": 3.85e-3,
                       "note": "confirmed AFHDS2A (MODELS.md); PRIMARY period per facts brief"},
    "FLYSKY_EL_18": {"protocol": "FlySky AFHDS3", "period_s": None,
                      "note": "AFHDS3, not AFHDS2A -- no primary timing table, do not apply 3.85ms"},
    "FLYSKY_NV_14": {"protocol": "FlySky AFHDS3", "period_s": None,
                      "note": "AFHDS3, not AFHDS2A -- no primary timing table, do not apply 3.85ms"},
    "FRSKY_X14": {"protocol": "FrSky ACCESS", "period_s": 9.0e-3, "n_channels": 47,
                  "note": "ACCESS, not legacy D/X -- 9ms/47ch is the D/X PRIMARY figure, applied here only as a loose reference"},
    "FRSKY_X20R": {"protocol": "FrSky ACCESS", "period_s": 9.0e-3, "n_channels": 47,
                   "note": "ACCESS, not legacy D/X -- 9ms/47ch is the D/X PRIMARY figure, applied here only as a loose reference"},
    "FRSKY_X9DP2019": {"protocol": "FrSky ACCESS (D16-capable)", "period_s": 9.0e-3, "n_channels": 47,
                        "note": "ACCESS/legacy D16 firmware-switchable -- 9ms/47ch is the D/X PRIMARY figure"},
    "FUTABA_T10J": {"protocol": "Futaba FASST/FASSTest", "period_s": None, "note": "no primary table"},
    "FUTABA_T14SG": {"protocol": "Futaba FASSTest/T-FHSS", "period_s": None, "note": "no primary table"},
    "FUTABA_T16IZ": {"protocol": "Futaba T-FHSS", "period_s": None, "note": "no primary table"},
    "FUTABA_T18SZ": {"protocol": "Futaba FASSTest/T-FHSS", "period_s": None, "note": "no primary table"},
}
_DEFAULT_EXPECT = {"protocol": "unconfirmed/other", "period_s": None, "note": "no primary table (MODELS.md Low evidence)"}


def _model_expect(model_dir_name: str) -> dict[str, Any]:
    return _MODEL_EXPECT.get(model_dir_name.upper(), _DEFAULT_EXPECT)


def _skip_model(model_dir_name: str) -> bool:
    up = model_dir_name.upper()
    return "DJI" in up or "DAUTEL" in up  # DJI/Autel airframes are out of scope (RC-uplink task)


def _find_packs(model_dir: Path) -> list[Path]:
    """Up to MAX_RECORDINGS_PER_MODEL distinct pack<K>.xml paths under a
    model dir, at ANY depth -- non-DJI archives nest one extra directory
    level (``<MODEL>/<Drone Name>/pack1.xml``, no ``VTSBW=`` folder) that
    ``RfuavAdapter.iter_recordings`` does not handle (see handback report)."""
    xmls = sorted(p for p in model_dir.rglob("pack*.xml")
                  if not p.with_name(p.name + ".aria2").exists())
    return xmls[:MAX_RECORDINGS_PER_MODEL]


def _find_slices(xml_path: Path, pack_num: int) -> list[Path]:
    out = []
    for p in sorted(xml_path.parent.glob(f"pack{pack_num}_*-*s.iq")):
        if p.with_name(p.name + ".aria2").exists():
            continue
        m = _IQ_STEM_RE.match(p.stem)
        if not m or int(m.group(1)) != pack_num:
            continue
        out.append(p)
    return out[:MAX_SLICES_PER_RECORDING]


def _load_slice(iq_path: Path, expected_samples: int) -> np.ndarray:
    raw = np.memmap(iq_path, dtype="<f4", mode="r")
    if raw.size != expected_samples * 2:
        raise ValueError(f"{iq_path.name}: {raw.size} f32 values, expected {expected_samples * 2}")
    return np.asarray(raw).view(np.complex64)


def _dwell_center_by_occupancy(spec, fs_hz: float) -> tuple[float, dict[str, Any]]:
    """Choose the dwell re-centre offset (baseband Hz) from ``spec``'s own PSD.

    Replaces raw ``argmax(mean PSD)`` (which picked the band edge for two of
    three inspected RFUAV models -- a roll-off artefact, not the link):

      * a >= ``_DWELL_EDGE_GUARD_HZ`` guard band at both ends of the capture,
        plus a small guard around the DC bin, is excluded from the score;
      * every ``_DWELL_WINDOW_HZ``-wide candidate window is scored by
        OCCUPANCY -- the fraction of (frame, bin) cells above a per-bin
        robust floor (its own time-median) + ``_DWELL_OCCUPANCY_DB`` -- not
        raw mean power, so a persistent narrow spur (constant power, zero
        variance -> zero occupancy against its own median) or a broad but
        low-duty-cycle roll-off cannot outscore a real hopping cluster once
        the edge guard also keeps it out of the candidate set.

    Returns ``(chosen baseband offset_hz, selection metadata)``; the metadata
    is recorded on the bench record for provenance (task item (c)).
    """
    freqs = np.asarray(spec.freqs_hz, dtype=np.float64)
    power_db = spec.power_db
    n_bins = freqs.size
    meta_base = {"window_hz": _DWELL_WINDOW_HZ, "edge_guard_hz": _DWELL_EDGE_GUARD_HZ,
                 "dc_guard_hz": _DWELL_DC_GUARD_HZ}
    if n_bins < 2 or power_db.shape[0] < 1:
        return 0.0, {**meta_base, "method": "fallback_degenerate_spectrogram", "occupancy": None}

    bin_hz = float(freqs[1] - freqs[0])
    floor_db = np.median(power_db, axis=0)
    occ = (power_db > (floor_db + _DWELL_OCCUPANCY_DB)).mean(axis=0).astype(np.float64)
    # A spur sitting exactly on the DC bin (LO-leak residual) cannot itself
    # justify a window's score.
    occ_scored = np.where(np.abs(freqs) <= _DWELL_DC_GUARD_HZ, 0.0, occ)

    window_bins = max(1, min(n_bins, int(round(_DWELL_WINDOW_HZ / bin_hz))))
    starts = np.arange(0, n_bins - window_bins + 1)
    win_lo = freqs[starts]
    win_hi = freqs[starts + window_bins - 1]
    lo_edge = freqs.min() + _DWELL_EDGE_GUARD_HZ
    hi_edge = freqs.max() - _DWELL_EDGE_GUARD_HZ
    valid = (win_lo >= lo_edge) & (win_hi <= hi_edge)

    csum = np.concatenate(([0.0], np.cumsum(occ_scored)))
    win_mean_occ = (csum[starts + window_bins] - csum[starts]) / window_bins

    method = "occupancy_grid"
    if not np.any(valid):
        # Band too narrow for guard + window (e.g. a short/narrowband dev
        # capture): fall back to the unguarded candidate set rather than
        # raising, but flag it so it is visible in the record.
        valid = np.ones_like(valid, dtype=bool)
        method = "fallback_guard_too_wide_for_band"

    scored = np.where(valid, win_mean_occ, -np.inf)
    best = int(np.argmax(scored))
    center_bin = min(best + window_bins // 2, n_bins - 1)
    offset_hz = float(freqs[center_bin])
    return offset_hz, {**meta_base, "method": method, "occupancy": float(win_mean_occ[best]),
                        "window_bins": window_bins}


def _window_record(det, model: str, pack_id: str, slice_name: str, mode: str,
                    fs_hz: float, center_freq_hz: float,
                    dwell_select: dict[str, Any] | None = None) -> dict[str, Any]:
    from aerix_rf.detect import raster as raster_mod

    rr = raster_mod.analyze_raster(det.events)
    return {
        "model": model,
        "pack": pack_id,
        "slice": slice_name,
        "mode": mode,
        "fs_hz": fs_hz,
        "center_freq_hz": center_freq_hz,
        "dwell_select": dwell_select,
        "morphology": det.morphology,
        "n_events": len(det.events),
        "burst_count": det.burst_count,
        "labels": list(rr.labels),
        "tags": list(rr.tags),
        "consistent_with": list(rr.consistent_with),
        "raster": {
            "delta_hz": rr.raster.delta_hz,
            "offset_hz": rr.raster.offset_hz,
            "n_channels": rr.raster.n_channels,
            "rayleigh_r": rr.raster.rayleigh_r,
            "rayleigh_r_debiased": rr.raster.rayleigh_r_debiased,
            "p_false": rr.raster.p_false,
            "insufficient": rr.raster.insufficient,
            "source": rr.raster.source,
        },
        "period": {
            "t_hat_s": rr.period.t_hat_s,
            "rayleigh_r": rr.period.rayleigh_r,
            "p_false": rr.period.p_false,
            "n_intervals": rr.period.n_intervals,
            "passed": rr.period.passed,
            "duration_hist": dict(rr.period.duration_hist),
            "duration_mode": rr.period.duration_mode,
            "source": rr.period.source,
        },
    }


def _process_one_iq(iq: np.ndarray, fs_hz: float, center_freq_hz: float,
                     model: str, pack_id: str, slice_name: str) -> list[dict[str, Any]]:
    from aerix_rf.detect import energy
    from aerix_rf.datasets import resample
    from aerix_rf.dsp import spectrogram

    out = []
    spec_full = spectrogram.compute(iq, sample_rate=fs_hz, fft_size=1024)
    det_full = energy.detect(spec_full, center_freq_mhz=center_freq_hz / 1e6)
    out.append(_window_record(det_full, model, pack_id, slice_name, "full_band", fs_hz, center_freq_hz))

    # Dwell emulation: re-centre on this window's OWN highest-occupancy 10 MHz
    # band (a live 12 MHz dwell tuned anywhere in the recording's band would
    # be centred by its own scan logic, not necessarily at the RFUAV
    # capture's native centre), then resample down to the 15.36 MS/s
    # canonical rate. See ``_dwell_center_by_occupancy`` for why this is not
    # a raw argmax(mean PSD) (that lands on band-edge roll-off artefacts).
    peak_offset_hz, dwell_select = _dwell_center_by_occupancy(spec_full, fs_hz)
    mixed, _ = resample.mix_and_slice(iq, in_rate_hz=fs_hz, offset_hz=peak_offset_hz)
    chain = resample.plan_chain(fs_hz, out_rate_hz=resample.CANONICAL_RATE_HZ, grade="live")
    dwell_iq = resample.apply_chain(mixed, chain, in_rate_hz=fs_hz)
    dwell_center_hz = center_freq_hz + peak_offset_hz
    spec_dwell = spectrogram.compute(dwell_iq, sample_rate=resample.CANONICAL_RATE_HZ, fft_size=1024)
    det_dwell = energy.detect(spec_dwell, center_freq_mhz=dwell_center_hz / 1e6)
    out.append(_window_record(det_dwell, model, pack_id, slice_name, "dwell",
                               resample.CANONICAL_RATE_HZ, dwell_center_hz,
                               dwell_select=dwell_select))
    return out


def _run_one_model(model_dir_str: str) -> dict[str, Any]:
    from aerix_rf.datasets.adapters import parse_rfuav_pack_xml

    model_dir = Path(model_dir_str)
    model = model_dir.name
    t0 = time.perf_counter()
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    for xml_path in _find_packs(model_dir):
        try:
            meta = parse_rfuav_pack_xml(xml_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{xml_path}: xml parse failed: {exc!r}")
            continue
        pack_num = int(xml_path.stem.removeprefix("pack"))
        pack_id = f"{model}/{xml_path.parent.name}/{xml_path.stem}"
        for iq_path in _find_slices(xml_path, pack_num):
            try:
                iq = _load_slice(iq_path, meta.sample_count)
                records.extend(_process_one_iq(
                    iq, meta.sample_rate_hz, meta.center_freq_hz,
                    model, pack_id, iq_path.name,
                ))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{iq_path.name}: {exc!r}\n{traceback.format_exc(limit=3)}")

    return {
        "model": model,
        "n_windows_raw": len(records) // 2,  # full+dwell per window
        "records": records,
        "errors": errors,
        "elapsed_s": time.perf_counter() - t0,
    }


def _run_control(root: Path) -> dict[str, Any]:
    """Same live pipeline path, over real ANTSDR ambient RF (no RC TX
    present) -- the false-alarm-budget-style control (docs/design/
    stage1-fa-budget-2026-09-19*.md), capped at ~100 windows total."""
    from aerix_rf.config import Config
    from aerix_rf.pipeline import process_window, SessionCadenceStore
    from aerix_rf.session.store import Session

    sessions = [
        p for p in sorted(root.iterdir())
        if p.is_dir() and (p / "session.json").exists()
        and any(s in p.name for s in ANTSDR_SESSION_SUBSTR)
    ]
    counts = {k: 0 for k in LEVEL1_LEVEL2_LABELS + TAGS}
    n_windows = 0
    cfg = Config.from_env()
    for sess_path in sessions:
        if n_windows >= ANTSDR_CONTROL_TARGET_WINDOWS:
            break
        src = Session.open(sess_path)
        session_cadence = SessionCadenceStore()
        for win in src.iq_windows(cfg):
            if n_windows >= ANTSDR_CONTROL_TARGET_WINDOWS:
                break
            fr = process_window(win, cfg, decode=False, session_cadence=session_cadence)
            n_windows += 1
            stage1 = getattr(fr.det, "stage1", {}) or {}
            labels = set(stage1.get("labels", []))
            tags = set(stage1.get("tags", []))
            for k in LEVEL1_LEVEL2_LABELS:
                if k in labels:
                    counts[k] += 1
            for k in TAGS:
                if k in tags:
                    counts[k] += 1
    return {"n_windows": n_windows, "counts": counts, "sessions": [s.name for s in sessions]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rfuav-root", default=str(RFUAV_ROOT))
    ap.add_argument("--antsdr-root", default=str(ANTSDR_ROOT))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=str(Path(__file__).parent / "out" / "stage1_rc_positives.md"))
    ap.add_argument("--json-out", default=str(Path(__file__).parent / "out" / "stage1_rc_positives.json"))
    ap.add_argument("--skip-control", action="store_true")
    args = ap.parse_args()

    rfuav_root = Path(args.rfuav_root)
    model_dirs = [p for p in sorted(rfuav_root.iterdir())
                  if p.is_dir() and not _skip_model(p.name)]
    print(f"{len(model_dirs)} RC-transmitter models: {[p.name for p in model_dirs]}", flush=True)

    results: list[dict[str, Any]] = []
    workers = max(1, min(args.workers, len(model_dirs), 8))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_one_model, str(p)): p for p in model_dirs}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED: {p.name}: {exc!r}")
                results.append({"model": p.name, "n_windows_raw": 0, "records": [],
                                 "errors": [repr(exc)], "elapsed_s": 0.0})
                continue
            results.append(r)
            print(f"done: {r['model']} ({r['n_windows_raw']} windows, "
                  f"{len(r['errors'])} errors, {r['elapsed_s']:.1f}s)", flush=True)

    results.sort(key=lambda r: r["model"])

    control = None
    if not args.skip_control:
        print("running ANTSDR ambient control...", flush=True)
        control = _run_control(Path(args.antsdr_root))
        print(f"control: {control['n_windows']} windows, counts={control['counts']}", flush=True)

    out = {"results": results, "control": control}
    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
