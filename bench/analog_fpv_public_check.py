"""Real-data check of the analog-FPV detector against the public Zenodo
19870020 analog-FPV IQ set (chunk10: 3 wideband sweeps, VTX at 1240 MHz,
25 mW, indoors, 3 m).

Answers four questions that synthetic `fmvideo_sim` fixtures cannot:

1. CARRIER CONVENTION -- where does the published channel frequency sit
   inside the real occupied band (mid-band vs blanking/residual-carrier
   line)?  Decides whether the sweep detector's edge-midpoint carrier
   estimator + tau = 0.5 MHz grid tolerance survive.
2. SHAPE -- real occupied bandwidth at -10/-20 dB, FM-video profile
   (dwell lines, colour-subcarrier shoulder, +6.0/+6.5 MHz audio
   subcarriers) and whether `dwell_confirm` passes on real IQ.
3. NEGATIVE CONTROL -- chunk10 has no no-TX sweep, so the controls are
   (a) every dwell tuned away from 1240 MHz and (b) the 5645-5945 MHz
   sub-band, where the 5.8 GHz grid detector must produce 0 candidates.
4. SIM COMPARISON -- the same measurements on `fmvideo_sim` defaults.

Run:  python bench/analog_fpv_public_check.py [--root ~/rf-datasets]
Read-only with respect to detector code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.signal import welch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aerix_rf.datasets.adapters import AnalogFpvZenodoAdapter  # noqa: E402
from aerix_rf.detect import analog_fpv as afpv  # noqa: E402

TX_MHZ = 1240.0
DC_NOTCH_HZ = 40e3          # HackRF LO/DC leakage guard (tuned centre == TX centre here)
OFF_CARRIER_HZ = 8e6        # noise-floor reference region within the 20 MHz span


# ----------------------------------------------------------------- helpers --
def psd_db(iq: np.ndarray, fs: float, nperseg: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    f, p = welch(iq, fs=fs, nperseg=nperseg, noverlap=nperseg // 2,
                 return_onesided=False, detrend=False, scaling="density")
    order = np.argsort(f)
    return f[order], 10.0 * np.log10(np.maximum(p[order], 1e-30))


def notch_dc(f: np.ndarray, p_db: np.ndarray, half_hz: float = DC_NOTCH_HZ) -> np.ndarray:
    out = p_db.copy()
    m = np.abs(f) <= half_hz
    if m.any() and (~m).any():
        out[m] = np.interp(f[m], f[~m], p_db[~m])
    return out


def outer_edges(f: np.ndarray, p_db: np.ndarray, thresh_db: float):
    """OUTERMOST threshold crossings (never a contiguous walk from the peak --
    an FM-video spectrum has internal notches), linear-in-dB sub-bin refine."""
    above = np.where(p_db >= thresh_db)[0]
    if above.size == 0 or above[0] == 0 or above[-1] == p_db.size - 1:
        return None
    lo, hi = int(above[0]), int(above[-1])

    def cross(i_in, i_out):
        y_in, y_out = float(p_db[i_in]), float(p_db[i_out])
        if y_in == y_out:
            return float(f[i_in])
        frac = (y_in - thresh_db) / (y_in - y_out)
        return float(f[i_in] + frac * (f[i_out] - f[i_in]))

    return cross(lo, lo - 1), cross(hi, hi + 1)


def profile(f: np.ndarray, p_db: np.ndarray, floor_db: float) -> dict:
    """Carrier-position / occupied-bandwidth measurements of one dwell PSD."""
    rel = p_db - floor_db
    pk = int(np.argmax(rel))
    peak_db = float(rel[pk])
    out = {"peak_hz": float(f[pk]), "peak_over_floor_db": peak_db}
    for drop in (6.0, 10.0, 12.0, 15.0, 20.0):
        e = outer_edges(f, rel, peak_db - drop)
        if e is None:
            out[f"edges_{drop:g}"] = None
            continue
        out[f"edges_{drop:g}"] = e
        out[f"bw_{drop:g}_mhz"] = (e[1] - e[0]) / 1e6
        out[f"mid_{drop:g}_khz"] = 0.5 * (e[0] + e[1]) / 1e3
    return out


def smooth_db(p_db: np.ndarray, win: int) -> np.ndarray:
    lin = np.power(10.0, p_db / 10.0)
    k = np.ones(win) / win
    return 10.0 * np.log10(np.maximum(np.convolve(lin, k, mode="same"), 1e-30))


def rebin(f: np.ndarray, p_db: np.ndarray, bin_hz: float):
    """Average in LINEAR power into `bin_hz` bins (sweep representation)."""
    lin = np.power(10.0, p_db / 10.0)
    edges = np.arange(f[0], f[-1] + bin_hz, bin_hz)
    idx = np.clip(np.digitize(f, edges) - 1, 0, len(edges) - 2)
    s = np.bincount(idx, weights=lin, minlength=len(edges) - 1)
    n = np.bincount(idx, minlength=len(edges) - 1)
    ok = n > 0
    centres = 0.5 * (edges[:-1] + edges[1:])
    return centres[ok], 10.0 * np.log10(np.maximum(s[ok] / n[ok], 1e-30))


# ------------------------------------------------------------------- main --
def load_dwells(root: Path):
    ad = AnalogFpvZenodoAdapter()
    recs = list(ad.iter_recordings(root))
    return ad, recs


def neighbour_baseline(ad, recs, run_id, tx_mhz=TX_MHZ,
                        offsets=(-60, -40, -20, 20, 40, 60), nperseg=8192):
    """Per-bin baseline from dwells tuned +-20..60 MHz away in the SAME sweep.

    A single-dwell noise floor taken from |f| > 8 MHz lands in the HackRF's
    baseband-filter STOPBAND (measured: the passband edge is +-6.89 MHz), which
    inflates peak-over-floor by ~15 dB and makes the occupied band run to the
    filter corner.  Differencing against neighbouring dwells removes the filter
    shape, the fs/4 spur at +5 MHz and the DC region in one step -- the same
    trick as the detector's recorded `Baseline`.
    """
    by = {round(r.original_center_freq_hz / 1e6): r for r in recs if r.run_id == run_id}
    rows, f = [], None
    for off in offsets:
        rec = by.get(round(tx_mhz + off))
        if rec is None:
            continue
        iq, fs, _, _ = ad.load_iq(rec)
        f, p = psd_db(iq, fs, nperseg)
        rows.append(notch_dc(f, p, 150e3))
    return f, np.median(np.stack(rows), axis=0)


def fm_probe(iq: np.ndarray, fs: float, video_lp_hz: float = 5.5e6) -> dict:
    """FM-demodulate and characterise the modulating waveform: the mean/median
    instantaneous frequency (where an AC-coupled modulator puts the published
    channel), the sync-tip/white extremes, and the line rate (PAL vs NTSC)."""
    from scipy.signal import firwin, lfilter
    h = firwin(255, video_lp_hz, fs=fs)
    x = lfilter(h, 1, iq)[300:]
    inst = np.diff(np.unwrap(np.angle(x))) * fs / (2 * np.pi)
    tip = (inst < np.percentile(inst, 6)).astype(np.float64)
    tip -= tip.mean()
    n = 1 << 18
    S = np.fft.rfft(tip[:n], 2 * n)
    ac = np.fft.irfft(S * np.conj(S))[:4000]
    lag = int(np.argmax(ac[600:2500])) + 600
    q = {f"p{v}": float(np.percentile(inst, v)) for v in (0.5, 1, 5, 50, 95, 99, 99.5)}
    return {"mean_inst_hz": float(inst.mean()), **q,
            "line_rate_hz": fs / lag, "line_lag_samples": lag}


def q1_q2_carrier_and_shape(ad, recs, tx_recs) -> list[dict]:
    rows = []
    for rec in tx_recs:
        iq, fs, fc, _ = ad.load_iq(rec)
        f, p = psd_db(iq, fs, nperseg=8192)
        p = notch_dc(f, p)
        fb, base = neighbour_baseline(ad, recs, rec.run_id)
        rel = smooth_db(p - base, 9)
        # +-6.9 MHz: narrow non-video spurs at the filter corner (see doc note)
        m = np.abs(f) <= 6.0e6
        fm_, rm = f[m], rel[m]
        i = int(np.argmax(rm))
        r = {"rec": rec.recording_id, "fc_mhz": fc / 1e6, "dur_ms": 1e3 * iq.size / fs,
             "peak_over_baseline_db": float(rm[i]), "peak_hz": float(fm_[i])}
        for drop in (6.0, 10.0, 12.0, 15.0, 20.0):
            e = outer_edges(fm_, rm, rm[i] - drop)
            r[f"bw_{drop:g}_mhz"] = None if e is None else (e[1] - e[0]) / 1e6
            r[f"mid_{drop:g}_khz"] = None if e is None else 0.5 * (e[0] + e[1]) / 1e3
        def band(lo, hi):
            k = (fm_ >= lo) & (fm_ <= hi)
            return float(np.max(rm[k])) if k.any() else float("nan")
        r["probes_db"] = {"pal_sc_+4.43": band(4.20e6, 4.65e6),
                          "ntsc_sc_+3.58": band(3.40e6, 3.78e6),
                          "audio_+6.0": band(5.85e6, 6.00e6),
                          "ref_+5.5": band(5.40e6, 5.60e6)}
        r["fm"] = fm_probe(iq, fs)
        rows.append(r)
    return rows


def q2_dwell_confirm(ad, tx_recs) -> list[dict]:
    out = []
    for rec in tx_recs:
        iq, fs, _, _ = ad.load_iq(rec)
        dur = iq.size / fs
        # The capture is tuned ON the carrier (sweep centre == drone_freq), so
        # lo_offset_hz = 0 -- the offset-tuned dwell the design doc specifies
        # is NOT what this dataset provides.
        r = afpv.dwell_confirm(iq, fs, lo_offset_hz=0.0,
                               min_duration_s=min(0.5, 0.8 * dur))
        r["rec"] = rec.recording_id
        r["dur_s"] = dur
        out.append(r)
    return out


def build_sweep_rows(ad, recs, blocks_per_dwell=2):
    """One stitched 500 kHz-bin sweep row per sweep file, from the first
    `blocks_per_dwell` blocks of every dwell (100-5980 MHz, 20 MHz steps)."""
    by_run: dict[str, list] = {}
    for rec in recs:
        by_run.setdefault(rec.run_id, []).append(rec)
    rows, seams = [], set()
    for run_id in sorted(by_run):
        fs_all, ps_all = [], []
        for rec in sorted(by_run[run_id], key=lambda r: r.original_center_freq_hz):
            fc = rec.original_center_freq_hz
            rec2 = rec.__class__(**{**rec.__dict__,
                                    "extra": {**rec.extra,
                                              "n_samples": min(int(rec.extra["n_samples"]),
                                                               65536 * blocks_per_dwell)}})
            iq, fs, _, _ = ad.load_iq(rec2)
            f, p = psd_db(iq, fs, nperseg=4096)
            p = notch_dc(f, p, 150e3)   # per-tile LO/DC leakage spur
            fb, pb = rebin(f, p, 500e3)
            keep = np.abs(fb) <= 9.75e6
            fs_all.append((fc + fb[keep]) / 1e6)
            ps_all.append(pb[keep])
            seams.add(round((fc + 10e6) / 1e6, 3))
        rows.append((np.concatenate(fs_all), np.concatenate(ps_all), run_id))
    return rows, sorted(seams)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / "rf-datasets"))
    ap.add_argument("--skip-sweep", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).expanduser()

    ad, recs = load_dwells(root)
    tx = [r for r in recs if r.extra["is_tx_freq"]]
    print(f"# recordings={len(recs)} tx_dwells={len(tx)} "
          f"no_tx_sweeps={sum(1 for r in recs if r.extra['no_tx_sweep'])}")

    print("\n== Q1/Q2 carrier position + shape (fine PSD, DC-notched) ==")
    rows = q1_q2_carrier_and_shape(ad, recs, tx)
    for r in rows:
        print(json.dumps(r, default=float))

    print("\n== Q2 dwell_confirm on real IQ ==")
    for r in q2_dwell_confirm(ad, tx):
        print(json.dumps(r, default=float))

    if not args.skip_sweep:
        print("\n== Q3 full-sweep candidates (stitched real sweep rows) ==")
        sweep_rows, seams = build_sweep_rows(ad, recs)
        sweeps = [(f, p) for f, p, _ in sweep_rows]
        from scipy.ndimage import median_filter
        for tag, base in (("self", None),
                          ("medfilt41", "medfilt")):
            if base is None:
                cands = afpv.sweep_candidates(sweeps, seam_mhz=seams)
            else:
                # Pseudo-ambient baseline: 41-bin (20.5 MHz) running median of
                # row 0.  NOT a recorded Baseline -- but the self-baseline
                # (per-bin median of the rows) CANCELS a continuously-on
                # emitter present in every row, which is exactly an analog VTX.
                ref = median_filter(np.stack([p for _, p in sweeps]).mean(axis=0), size=41)
                cands = afpv.sweep_candidates(sweeps, baseline_db=ref, seam_mhz=seams)
            in58 = [c for c in cands if 5645e6 <= c["centre_hz"] <= 5945e6]
            near = [c for c in cands if abs(c["centre_hz"] - TX_MHZ * 1e6) <= 3e6]
            print(f"[{tag}] n={len(cands)} in_5645_5945={len(in58)} near_1240={len(near)}")
            for c in cands:
                print("   ", json.dumps(c, default=float))
        cands = []
        print(f"n_candidates={len(cands)} (self-baseline = per-bin median of {len(sweeps)} rows)")
        for c in cands:
            print(json.dumps(c, default=float))
        in58 = [c for c in cands if 5645e6 <= c["centre_hz"] <= 5945e6]
        print(f"candidates_in_5645_5945={len(in58)}  (negative control: expect 0)")
        near_tx = [c for c in cands if abs(c["centre_hz"] - TX_MHZ * 1e6) <= 2e6]
        print(f"candidates_near_1240={len(near_tx)}")


if __name__ == "__main__":
    main()
