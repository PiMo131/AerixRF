"""Analog 5.8 GHz FPV video-carrier detector (T1, ``analog-fpv-detector.md``).

Two independent stages, matching the design doc:

* :func:`sweep_candidates` (S3-S4): sweep-level persistence + published
  channel-grid matching. Level 1 (``analog_video_carrier_candidate``) needs
  only morphology (occupied bandwidth, seam-masked baseline-differenced
  peak) and persistence; level 2 (``analog_fpv_grid_candidate``) additionally
  needs on-grid membership AND (>=2 co-band carriers OR an external dwell
  confirmation) -- grid position alone is never sufficient (S1: Band A
  collides with 802.11 U-NII-3 centres; the ANTSDR sweep step-seam comb also
  lands on the Band A lattice).
* :func:`dwell_confirm` (S5): a 1 s offset-tuned dwell capture's continuity
  (duty ~= 1.0 via an EXPLICIT noise floor -- the default percentile floor is
  invalid for a duty-1 emitter), FM shape ratio and audio-subcarrier check.

Every record carries ``grid_false_match_p`` (S4): 40 published channels at
+-1.0 MHz tolerance (S11: measured VTX centre scatter, see GRID_TOL_MHZ_DEFAULT)
cover ~27% of 5645-5945 MHz, so grid membership is weak
evidence on its own and must always be reported as a number, not implied by
the label. Evidence-level wording: never emit ``analog_fpv_detected`` or any
aircraft-present/brand claim -- "consistent with the Raceband lattice" is the
strongest wording this detector can justify (S6).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks

from .bursts import detect_bursts
from .raster import _rayleigh_stat  # reuse the lattice-concentration statistic (S4)

__all__ = [
    "GRID_CHANNELS_MHZ",
    "AnalogFpvCandidate",
    "match_grid",
    "grid_false_match_p",
    "lattice_check",
    "sweep_candidates",
    "dwell_confirm",
]

# --------------------------------------------------------------------------- #
# Published analog FPV channel grids, 5.8 GHz.
# Source: research/library/fpv/AERIX_FPV/analog_video/channel_plans/
# CHANNEL_DATABASE.md S1 (Oscar Liang, "5.8GHz FPV Channels & Frequency
# Chart", https://oscarliang.com/fpv-channels/). Evidence class SUPPORTED:
# de-facto community standard reproduced across vendor docs/goggle firmware,
# NOT independently measured by this project. Values MHz, channel index 1-8
# as published. Band A descends with index; B/F/R ascend; E is discontinuous
# (E1-E4 descend from 5705, E5-E8 jump above 5885) -- a monotonic-grid
# assumption mis-labels A and E.
# --------------------------------------------------------------------------- #
GRID_CHANNELS_MHZ: dict[str, tuple[float, ...]] = {
    "A": (5865.0, 5845.0, 5825.0, 5805.0, 5785.0, 5765.0, 5745.0, 5725.0),
    "B": (5733.0, 5752.0, 5771.0, 5790.0, 5809.0, 5828.0, 5847.0, 5866.0),
    "E": (5705.0, 5685.0, 5665.0, 5645.0, 5885.0, 5905.0, 5925.0, 5945.0),
    "F": (5740.0, 5760.0, 5780.0, 5800.0, 5820.0, 5840.0, 5860.0, 5880.0),
    "R": (5658.0, 5695.0, 5732.0, 5769.0, 5806.0, 5843.0, 5880.0, 5917.0),
}
# Uniform-lattice spacing per band, used by lattice_check (S4: "prefer the
# lattice test over absolute positions"). E is discontinuous and has no
# single uniform spacing, so it is excluded here.
GRID_DELTAS_HZ: dict[str, float] = {"A": 20e6, "B": 19e6, "F": 20e6, "R": 37e6}

_CHANNELS_PER_BAND = 8
_BAND_SPAN_MHZ = 300.0          # 5645-5945 MHz
GRID_TOL_MHZ_DEFAULT = 1.0      # tau: MEASURED 2026-09-19 on Zenodo 19870020 chunk10 -- real 1240 MHz
                                 # analog VTX carrier estimates scattered 1.14 MHz across 3 rows (see
                                 # DEFAULT_PERSIST_TOL_MHZ). 1.0 MHz covers that scatter with margin;
                                 # adjacent published channels within a band are >=19 MHz apart (see
                                 # GRID_DELTAS_HZ), so this cannot create cross-channel ambiguity.
                                 # Supersedes the previous 0.5 MHz placeholder budget
BAND_A_REQUIRES_DWELL_DEFAULT = True   # S4/S7: Band A == U-NII-3 Wi-Fi centres

DEFAULT_PEAK_DELTA_DB = 8.0
DEFAULT_PROMINENCE_DB = 4.0
DEFAULT_SEAM_GUARD_MHZ = 0.75    # mandatory guard around RetuneWelchSweep step seams (S3.2, S7)
DEFAULT_MIN_SWEEPS = 3
DEFAULT_PERSIST_TOL_MHZ = 1.5    # MEASURED 2026-09-19 on Zenodo 19870020 chunk10 (real 1240 MHz analog
                                 # VTX, 3 sweeps): the per-row -12 dB edge-midpoint carrier estimate
                                 # scattered 1239.18 / 1239.18 / 1240.32 MHz -- 1.14 MHz between rows --
                                 # because picture content moves the FM dwell structure and the 500 kHz
                                 # sweep grid quantises which local max is picked. At the previous 0.25
                                 # (code) / 0.75 (design doc S3.6) the three rows never clustered and a
                                 # strong (17-20 dB over baseline), continuously present real carrier was
                                 # MISSED entirely. 1.5 MHz still cannot merge adjacent published channels
                                 # (19-37 MHz apart). Supersedes both placeholders.
DEFAULT_BW20_RANGE_MHZ = (5.0, 9.0)
DEFAULT_BW10_RANGE_MHZ = (3.0, 7.0)
DEFAULT_PEAK_OVER_FLOOR_FOR_BW20_DB = 25.0
DEFAULT_CARRIER_EDGE_DROP_DB = 12.0  # contour used for the carrier estimate (T1 correction); see
                                     # _row_peaks -- NOT -20 dB (asymmetric shoulder) and not
                                     # -6/-10 dB (inside the FM dwell structure)
DEFAULT_EDGE_MARGIN_DB = 4.0     # a -20 dB contour is only trusted if it still sits this far
                                 # above the baseline-differenced zero level (T1 correction)


def _p_band(tol_mhz: float) -> float:
    """Per-band chance-coincidence probability at tolerance ``tol_mhz``
    (S4): ``channels_per_band * 2*tau / band_span``."""
    return _CHANNELS_PER_BAND * 2.0 * tol_mhz / _BAND_SPAN_MHZ


def grid_false_match_p(k: int = 1, tol_mhz: float = GRID_TOL_MHZ_DEFAULT,
                        n_bands: int = len(GRID_CHANNELS_MHZ)) -> float:
    """Bonferroni false-match probability (S4) for ``k`` carriers claimed to
    sit on the SAME lattice: ``p = min(1, n_bands * p_band**k)``. ``k=1`` is
    the single-carrier, any-of-5-bands union bound (~27% at tau=1.0 MHz)."""
    p_band = _p_band(tol_mhz)
    return float(min(1.0, n_bands * (p_band ** max(1, int(k)))))


def match_grid(centre_hz: float, tol_mhz: float = GRID_TOL_MHZ_DEFAULT) -> list[tuple[str, int, float]]:
    """All ``(band, channel_index, channel_mhz)`` published channels within
    ``tol_mhz`` of ``centre_hz`` -- may return >1 hit (S1: 5880 = F8 = R7)."""
    centre_mhz = centre_hz / 1e6
    hits: list[tuple[str, int, float]] = []
    for band, chans in GRID_CHANNELS_MHZ.items():
        for idx, f in enumerate(chans, start=1):
            if abs(centre_mhz - f) <= tol_mhz:
                hits.append((band, idx, f))
    return hits


def lattice_check(centres_hz: list[float], deltas_hz: dict[str, float] = GRID_DELTAS_HZ
                   ) -> dict[str, tuple[float, float]]:
    """Rayleigh concentration ``(r, offset_hz)`` of ``centres_hz`` against
    each named lattice spacing (S4 bonus check for >=2 carriers; not required
    for a single-carrier level-2 promotion). Reuses
    :func:`aerix_rf.detect.raster._rayleigh_stat`."""
    values = np.asarray(centres_hz, dtype=np.float64)
    return {name: _rayleigh_stat(values, delta) for name, delta in deltas_hz.items()}


# --------------------------------------------------------------------------- #
# Stage A: sweep-level candidates
# --------------------------------------------------------------------------- #

@dataclass
class AnalogFpvCandidate:
    label: str                              # "analog_video_carrier_candidate" | "analog_fpv_grid_candidate"
    centre_hz: float
    bw_20db_hz: float | None
    bw_10db_hz: float | None
    delta_db: float
    n_sweeps_present: int
    seam_masked: bool
    grid: str | None = None
    grid_channel: int | None = None
    grid_residual_hz: float | None = None
    grid_false_match_p: float = 1.0
    consistent_with: list[str] = field(default_factory=list)
    band_a: bool = False
    carrier_estimator: str = "edge_mid_20db"
    r_shape: float | None = None
    frac_time_occupied: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _smooth_db(power_db: np.ndarray, window: int = 3) -> np.ndarray:
    """3-bin smoothing in LINEAR power (S3.1), returned back in dB."""
    lin = np.power(10.0, power_db / 10.0)
    smoothed = uniform_filter1d(lin, size=window, mode="nearest")
    return 10.0 * np.log10(np.maximum(smoothed, 1e-30))


def _reference_db(freqs_mhz: np.ndarray, smoothed_rows: list[np.ndarray], baseline_db) -> np.ndarray:
    if baseline_db is not None:
        if hasattr(baseline_db, "interp"):
            # Smooth the same way as the per-row power (S3.1) before
            # differencing: a raw (unsmoothed) baseline differenced against a
            # 3-bin-smoothed row leaves an uncancelled residual right where
            # the real baseline has a sharp step (e.g. a sweep-step seam
            # edge) -- measured to bias the parabolic carrier-centre estimate
            # by several hundred kHz when a carrier sits within a couple of
            # bins of such a step (see the real-ambient-baseline T1
            # acceptance test).
            return _smooth_db(baseline_db.interp(freqs_mhz))
        ref = np.asarray(baseline_db, dtype=np.float64)
        if ref.shape != freqs_mhz.shape:
            raise ValueError("baseline_db array must match freqs_mhz shape, or pass a Baseline")
        return ref
    # Self-baseline (no recorded Baseline): per-bin median across the
    # provided sweeps, in dB -- only finds carriers hot in < 50% of rows
    # (same convention as scan/candidates.py).
    stacked = np.stack(smoothed_rows, axis=0)
    return np.median(stacked, axis=0)


def _band_edges_mhz(power_db: np.ndarray, freqs_mhz: np.ndarray, peak_idx: int, drop_db: float,
                     margin_db: float = DEFAULT_EDGE_MARGIN_DB) -> tuple[float, float] | None:
    """Sub-bin ``-drop_db`` band edges around ``peak_idx``, or ``None`` when
    they are not resolvable.

    The threshold crossing is refined by LINEAR interpolation in dB between
    the last in-band bin and the first out-of-band bin (S3.1, T1 correction):
    a skirt falls roughly linearly in dB per bin, so a linear crossing is the
    right sub-bin model there -- parabolic interpolation belongs on a peak,
    not on an edge.

    Returns ``None`` if the threshold is not at least ``margin_db`` above the
    row's own zero level (i.e. the peak is too weak for a -20 dB contour to
    be distinguishable from noise) or if the contour runs off either end of
    the array (truncated band: an unmeasurable width, not a narrow one).
    """
    n = power_db.size
    thresh = float(power_db[peak_idx]) - drop_db
    if thresh < margin_db:
        return None
    lo = hi = peak_idx
    while lo > 0 and power_db[lo - 1] >= thresh:
        lo -= 1
    while hi < n - 1 and power_db[hi + 1] >= thresh:
        hi += 1
    if lo == 0 or hi == n - 1:
        return None

    def _cross(i_in: int, i_out: int) -> float:
        y_in, y_out = float(power_db[i_in]), float(power_db[i_out])
        if y_in == y_out:
            return float(freqs_mhz[i_in])
        frac = (y_in - thresh) / (y_in - y_out)
        return float(freqs_mhz[i_in] + frac * (freqs_mhz[i_out] - freqs_mhz[i_in]))

    return _cross(lo, lo - 1), _cross(hi, hi + 1)


def _row_peaks(freqs_mhz: np.ndarray, power_db: np.ndarray, delta_db_row: np.ndarray,
               seam_mhz: list[float], seam_guard_mhz: float, peak_delta_db: float,
               prominence_db: float, bw20_range_mhz: tuple[float, float],
               bw10_range_mhz: tuple[float, float], peak_over_floor_gate: float,
               edge_margin_db: float = DEFAULT_EDGE_MARGIN_DB,
               carrier_edge_drop_db: float = DEFAULT_CARRIER_EDGE_DROP_DB) -> list[dict]:
    n = freqs_mhz.size
    if n == 0:
        return []
    bin_mhz = float(np.median(np.diff(freqs_mhz))) if n > 1 else 0.5

    masked = np.zeros(n, dtype=bool)
    for s in seam_mhz:
        masked |= np.abs(freqs_mhz - s) <= seam_guard_mhz
    search = np.where(masked, -np.inf, delta_db_row)

    peak_idx, _ = find_peaks(search, height=peak_delta_db, prominence=prominence_db)
    row_floor_db = float(np.median(power_db))
    out = []
    for i in peak_idx:
        peak_db = float(power_db[i])
        peak_over_floor = peak_db - row_floor_db

        # Edges are measured on the baseline-differenced row (zero == ambient
        # floor), so a -20 dB contour is only claimed when the peak actually
        # stands that far above the floor.
        e20 = _band_edges_mhz(delta_db_row, freqs_mhz, i, 20.0, edge_margin_db)
        e10 = _band_edges_mhz(delta_db_row, freqs_mhz, i, 10.0, edge_margin_db)
        e_c = _band_edges_mhz(delta_db_row, freqs_mhz, i, carrier_edge_drop_db, edge_margin_db)
        bw20 = (e20[1] - e20[0]) if e20 else None
        bw10 = (e10[1] - e10[0]) if e10 else None

        # --- carrier estimate (T1 correction 2026-09-19) ---------------- #
        # NOT the argmax bin (+ parabolic refinement): wideband FM video is
        # not a peaked spectrum. Its strongest bins are wherever the
        # instantaneous frequency dwells (blanking/sync-tip lines and the
        # luma-ramp plateau), which is several bins off the channel centre
        # and moves with picture content -- measured 0.59-0.84 MHz of centre
        # error against a planted carrier on a 500 kHz grid. The channel
        # frequency is instead the MIDPOINT of the occupied band's -20 dB
        # edges (the same edge-midpoint principle used for the DroneID
        # centroid in detect/bursts.py); linear refinement is applied to the
        # EDGES, not to the peak.
        #
        # WHICH contour matters, measured on fmvideo_sim (midband, 500 kHz
        # bins, 3-bin smoothing, flat floor + the real base_58 ambient):
        #   -6/-10 dB: still inside the FM dwell structure (blanking line,
        #              sync-tip line, luma plateau) -- error up to +0.76 MHz,
        #              and +0.58 MHz on the real-ambient row;
        #   -20 dB:    runs out into the asymmetric shoulder (colour-subcarrier
        #              and ramp-harmonic products, one-sided) -- error +0.5 to
        #              +0.86 MHz;
        #   -12/-15 dB: |error| <= 0.09 MHz on all four fixtures.
        # So the default carrier contour is -12 dB, while the REPORTED
        # bandwidths stay at the design doc's -10/-20 dB definitions.
        if e_c is not None:
            centre_mhz = 0.5 * (e_c[0] + e_c[1])
            estimator = f"edge_mid_{carrier_edge_drop_db:g}db"
        elif e10 is not None:
            centre_mhz = 0.5 * (e10[0] + e10[1])
            estimator = "edge_mid_10db"
        else:
            centre_mhz = float(freqs_mhz[i])
            estimator = "peak_bin"

        bw20_hz = bw10_hz = None
        bw_ok = False
        if (peak_over_floor >= peak_over_floor_gate and bw20 is not None
                and bw20_range_mhz[0] <= bw20 <= bw20_range_mhz[1]):
            bw_ok = True
            bw20_hz = bw20 * 1e6
            bw10_hz = bw10 * 1e6 if bw10 is not None else None
        elif bw10 is not None and bw10_range_mhz[0] <= bw10 <= bw10_range_mhz[1]:
            bw_ok = True
            bw10_hz = bw10 * 1e6
            if bw20 is not None and bw20_range_mhz[0] <= bw20 <= bw20_range_mhz[1]:
                bw20_hz = bw20 * 1e6
        if not bw_ok:
            continue

        near_seam = any(abs(freqs_mhz[i] - s) <= seam_guard_mhz * 2.0 for s in seam_mhz)
        out.append({"centre_mhz": centre_mhz, "delta_db": float(delta_db_row[i]),
                    "bw_20db_hz": bw20_hz, "bw_10db_hz": bw10_hz, "near_seam": near_seam,
                    "carrier_estimator": estimator})

    # One occupied band can contain several local maxima (blanking line, luma
    # plateau ripple); they all resolve to the SAME edge midpoint, so collapse
    # peaks whose centres agree to within one bin and keep the strongest.
    out.sort(key=lambda pk: (pk["centre_mhz"], -pk["delta_db"]))
    deduped: list[dict] = []
    for pk in out:
        if deduped and abs(pk["centre_mhz"] - deduped[-1]["centre_mhz"]) <= bin_mhz:
            if pk["delta_db"] > deduped[-1]["delta_db"]:
                deduped[-1] = pk
            continue
        deduped.append(pk)
    return deduped


def _cluster_across_rows(per_row: list[list[dict]], tol_mhz: float) -> list[dict]:
    flat = [(ridx, pk) for ridx, peaks in enumerate(per_row) for pk in peaks]
    flat.sort(key=lambda item: item[1]["centre_mhz"])
    clusters: list[list[tuple[int, dict]]] = []
    for item in flat:
        if clusters and item[1]["centre_mhz"] - clusters[-1][-1][1]["centre_mhz"] <= tol_mhz:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    out = []
    for cl in clusters:
        rows = {ridx for ridx, _ in cl}
        centre_hz = float(np.mean([pk["centre_mhz"] for _, pk in cl])) * 1e6
        delta_db = float(np.mean([pk["delta_db"] for _, pk in cl]))
        bw20_vals = [pk["bw_20db_hz"] for _, pk in cl if pk["bw_20db_hz"] is not None]
        bw10_vals = [pk["bw_10db_hz"] for _, pk in cl if pk["bw_10db_hz"] is not None]
        out.append({
            "centre_hz": centre_hz,
            "delta_db": delta_db,
            "bw_20db_hz": float(np.median(bw20_vals)) if bw20_vals else None,
            "bw_10db_hz": float(np.median(bw10_vals)) if bw10_vals else None,
            "n_sweeps_present": len(rows),
            "seam_masked": any(pk["near_seam"] for _, pk in cl),
            "carrier_estimator": min(pk["carrier_estimator"] for _, pk in cl),
        })
    return out


def sweep_candidates(sweeps, baseline_db=None, seam_mhz: list[float] | None = None, *,
                      peak_delta_db: float = DEFAULT_PEAK_DELTA_DB,
                      prominence_db: float = DEFAULT_PROMINENCE_DB,
                      seam_guard_mhz: float = DEFAULT_SEAM_GUARD_MHZ,
                      min_sweeps: int = DEFAULT_MIN_SWEEPS,
                      persist_tol_mhz: float = DEFAULT_PERSIST_TOL_MHZ,
                      grid_tol_mhz: float = GRID_TOL_MHZ_DEFAULT,
                      bw20_range_mhz: tuple[float, float] = DEFAULT_BW20_RANGE_MHZ,
                      bw10_range_mhz: tuple[float, float] = DEFAULT_BW10_RANGE_MHZ,
                      edge_margin_db: float = DEFAULT_EDGE_MARGIN_DB,
                      carrier_edge_drop_db: float = DEFAULT_CARRIER_EDGE_DROP_DB,
                      band_a_requires_dwell: bool = BAND_A_REQUIRES_DWELL_DEFAULT,
                      dwell_confirmed_centres_hz: list[float] | None = None) -> list[dict]:
    """Stage A (S3-S4): sweep-level candidates from ``sweeps``, a list of
    ``(freqs_mhz, power_db)`` rows (same frequency grid assumed across rows,
    as any single :class:`~aerix_rf.scan.sweep.Baseline`-covered band sweep
    naturally has). Returns a list of dicts (``AnalogFpvCandidate.as_dict()``)
    -- every record carries ``grid_false_match_p`` regardless of label.

    ``seam_mhz`` is an explicit list of sweep-step seam centre frequencies
    (MHz) to mask +-``seam_guard_mhz`` around (S3.2/S7); pass the seams
    derived from a :class:`~aerix_rf.sdr.sweep.RetuneWelchSweep`'s
    ``step_hz``/band start -- this module does not import that source
    (kept read-only per task scope) so the caller computes them.

    Level-2 promotion (``analog_fpv_grid_candidate``) requires on-grid
    membership AND (>=2 candidates sharing a band OR the candidate's centre
    is within ``grid_tol_mhz`` of one of ``dwell_confirmed_centres_hz``);
    Band A additionally always requires the dwell confirmation
    (``band_a_requires_dwell``), since it collides with 802.11 U-NII-3.
    """
    sweeps = [(np.asarray(f, dtype=np.float64), np.asarray(p, dtype=np.float64)) for f, p in sweeps]
    if not sweeps:
        return []
    freqs_mhz = sweeps[0][0]
    seam_list = list(seam_mhz) if seam_mhz else []

    smoothed_rows = [_smooth_db(p) for _, p in sweeps]
    ref_db = _reference_db(freqs_mhz, smoothed_rows, baseline_db)

    per_row = []
    for (f, p), smoothed in zip(sweeps, smoothed_rows):
        delta_row = smoothed - ref_db
        per_row.append(_row_peaks(f, p, delta_row, seam_list, seam_guard_mhz, peak_delta_db,
                                   prominence_db, bw20_range_mhz, bw10_range_mhz,
                                   DEFAULT_PEAK_OVER_FLOOR_FOR_BW20_DB, edge_margin_db,
                                   carrier_edge_drop_db))

    clusters = [c for c in _cluster_across_rows(per_row, persist_tol_mhz)
                if c["n_sweeps_present"] >= min_sweeps]

    # Co-band counts across all surviving clusters (S4: ">=2 co-band carriers").
    hits_per_cluster = [match_grid(c["centre_hz"], grid_tol_mhz) for c in clusters]
    band_counts: dict[str, int] = {}
    for hits in hits_per_cluster:
        for b in {h[0] for h in hits}:
            band_counts[b] = band_counts.get(b, 0) + 1

    dwell_centres = list(dwell_confirmed_centres_hz) if dwell_confirmed_centres_hz else []

    out = []
    for c, hits in zip(clusters, hits_per_cluster):
        label = "analog_video_carrier_candidate"
        grid = grid_channel = grid_residual_hz = None
        consistent_with: list[str] = []
        band_a = False
        p_match = grid_false_match_p(k=1, tol_mhz=grid_tol_mhz)

        if hits:
            best = min(hits, key=lambda h: abs(c["centre_hz"] / 1e6 - h[2]))
            grid, grid_channel, best_freq_mhz = best
            grid_residual_hz = c["centre_hz"] - best_freq_mhz * 1e6
            consistent_with = [f"{b}{idx} {int(round(f))}" for b, idx, f in hits]
            band_a = any(b == "A" for b, _, _ in hits)
            k = max(band_counts.get(b, 1) for b, _, _ in hits)
            p_match = grid_false_match_p(k=k, tol_mhz=grid_tol_mhz)

            dwell_ok = any(abs(c["centre_hz"] - dc) <= grid_tol_mhz * 1e6 for dc in dwell_centres)
            band_a_blocks = band_a and band_a_requires_dwell and not dwell_ok
            if (k >= 2 or dwell_ok) and not band_a_blocks:
                label = "analog_fpv_grid_candidate"

        out.append(AnalogFpvCandidate(
            label=label, centre_hz=c["centre_hz"], bw_20db_hz=c["bw_20db_hz"],
            bw_10db_hz=c["bw_10db_hz"], delta_db=c["delta_db"],
            n_sweeps_present=c["n_sweeps_present"], seam_masked=c["seam_masked"],
            grid=grid, grid_channel=grid_channel, grid_residual_hz=grid_residual_hz,
            grid_false_match_p=p_match, consistent_with=consistent_with, band_a=band_a,
            carrier_estimator=c["carrier_estimator"],
        ).as_dict())
    return out


# --------------------------------------------------------------------------- #
# Stage B: dwell confirmation
# --------------------------------------------------------------------------- #

def dwell_confirm(iq: np.ndarray, fs: float, lo_offset_hz: float = 3.0e6, *,
                   fft_size: int = 1024,
                   min_duration_s: float = 0.5,
                   noise_floor_db: float | None = None,
                   off_carrier_guard_hz: float = 6.0e6,
                   shape_narrow_hz: float = 1.0e6,
                   shape_wide_hz: float = 4.0e6,
                   r_shape_threshold: float = 0.35,
                   frac_time_threshold: float = 0.98,
                   duty_gate_db: float = 6.0,
                   audio_subcarriers_hz: tuple[float, ...] = (6.0e6, 6.5e6),
                   audio_tol_hz: float = 300e3) -> dict:
    """Stage B (S5): 1 s dwell offset-tuned to ``f_c + lo_offset_hz`` (the
    caller does the actual retune/capture; ``iq``/``fs`` is that capture).
    Baseband 0 Hz is the TUNED centre, so the video carrier itself sits at
    baseband ``-lo_offset_hz`` and frequencies are reported/gated relative to
    the carrier via ``freq_rel_carrier = baseband_freq + lo_offset_hz``.

    Returns a dict: ``confirmed`` (bool), ``continuous``, ``frac_time_occupied``,
    ``r_shape``, ``noise_floor_db`` (the EXPLICIT floor actually used --
    S5.1: the default 5th-percentile-over-time floor is invalid for a
    duty~1.0 emitter and must never silently gate this test),
    ``audio_subcarriers_detected_hz``, ``n_events``.
    """
    from ..dsp import spectrogram  # local import: keep this module's import graph light

    iq = np.asarray(iq, dtype=np.complex64)
    if iq.size < fft_size:
        return {"confirmed": False, "continuous": False, "frac_time_occupied": 0.0,
                "r_shape": 0.0, "noise_floor_db": float("nan"),
                "audio_subcarriers_detected_hz": [], "n_events": 0}

    spec = spectrogram.compute(iq, fs, fft_size=fft_size)
    lin = np.power(10.0, spec.power_db.astype(np.float64) / 10.0)
    freq_rel_carrier = spec.freqs_hz + lo_offset_hz

    off_carrier = np.abs(freq_rel_carrier) > off_carrier_guard_hz
    if noise_floor_db is None:
        # S5.1: explicit floor from off-carrier bins (never the default
        # per-bin 5th-percentile-over-time floor -- a duty~1.0 emitter
        # defines its own floor and nothing would gate).
        if off_carrier.any():
            noise_floor_db = float(np.median(spec.power_db[:, off_carrier]))
        else:
            noise_floor_db = float(np.percentile(spec.power_db, 5.0))
    noise_floor_lin = float(10.0 ** (noise_floor_db / 10.0))

    frame_dt_s = (spec.hop or fft_size // 2) / fs
    events = detect_bursts(lin, fs=fs, frame_dt_s=frame_dt_s, freqs_hz=freq_rel_carrier,
                            noise_floor_lin=noise_floor_lin)
    long_events = [e for e in events
                   if e.duration_s >= min_duration_s and abs(e.centre_hz) <= 2.0e6]
    continuous = bool(long_events)

    within_2mhz = np.abs(freq_rel_carrier) <= 2.0e6
    if within_2mhz.any():
        occ = spec.power_db[:, within_2mhz] > (noise_floor_db + duty_gate_db)
        frac_time_occupied = float(np.mean(occ.any(axis=1)))
    else:
        frac_time_occupied = 0.0

    mean_lin_spectrum = lin.mean(axis=0)
    narrow = np.abs(freq_rel_carrier) <= shape_narrow_hz
    wide = np.abs(freq_rel_carrier) <= shape_wide_hz
    p_wide = float(mean_lin_spectrum[wide].sum())
    r_shape = float(mean_lin_spectrum[narrow].sum() / p_wide) if p_wide > 0 else 0.0

    audio_hits = []
    for f_audio in audio_subcarriers_hz:
        near = np.abs(freq_rel_carrier - f_audio) <= audio_tol_hz
        if near.any() and float(spec.power_db[:, near].max()) - noise_floor_db >= duty_gate_db:
            audio_hits.append(float(f_audio))

    confirmed = bool(continuous and frac_time_occupied >= frac_time_threshold
                      and r_shape >= r_shape_threshold)

    return {
        "confirmed": confirmed,
        "continuous": continuous,
        "frac_time_occupied": frac_time_occupied,
        "r_shape": r_shape,
        "noise_floor_db": noise_floor_db,
        "audio_subcarriers_detected_hz": audio_hits,
        "n_events": len(events),
    }
