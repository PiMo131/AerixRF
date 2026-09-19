"""Stage-1 energy/spectral detector (unsupervised) = RF *morphology*.

Keys on signal *shape*, not content, so it catches even encrypted O4 / analog FPV.
Produces a bounded detection_probability ("how strong / interesting is this RF")
plus the RF context the server path wants, and a ``morphology`` label that
describes the measured shape only:

    noise                          nothing above the floor
    narrowband_candidate           < 2 MHz occupied
    wideband_candidate             2-6 MHz occupied (bursty or continuous)
    burst_wideband_candidate       >= 6 MHz, bursty, not flat-topped
    ofdm_candidate                 >= 6 MHz, bursty, flat-topped (OFDM-like)
    continuous_wideband_candidate  >= 6 MHz, on for most of the window
    analog_candidate               >= 18 MHz continuous (weak guess: analog FPV)
    unknown                        above the floor but no usable shape

    -- stage-1 link-signature vocabulary (docs/design/stage1-link-signatures.md;
       see aerix_rf.detect.{bursts,raster} T1/T2), overlaid ahead of the shape
       buckets above when the burst-event evidence supports it:
    fhss_1mhz_grid_candidate       Rayleigh-tested 1.000 MHz channel raster
    fhss_2mhz_grid_candidate       Rayleigh-tested 2.000 MHz channel raster (collides
                                    with BLE data channels by frequency alone)
    rc_link_family_candidate       hopping + ELRS-rate period + <=2 MHz hops + short bursts
    droneid_cadence_candidate      session-level 640 ms crystal-locked cadence (see
                                    aerix_rf.pipeline.SessionCadenceStore; never fires
                                    from one 1 s window alone)
    hopping_candidate              >=3 reused channel clusters, near-white centre sequence
                                    (replaces the old power-centroid ``fhss_candidate``)
    fixed_channel_burst_candidate  one channel cluster, tight centre spread

Stage 1 makes NO identity claim: a 10-20 MHz OFDM blob is just as likely
ambient Wi-Fi as a drone link. Identity (``dji_ocusync`` / ``wifi_uas`` / ...)
is stage 2 (``aerix_rf.classify.model``); deterministic confirmation is stage 3
(protocol decode). ``Detection.signature_class`` is kept for backward
compatibility but is only ever ``"noise"`` or ``"unknown"`` here.

Thresholds are tuned/validated against the public datasets (see plan); nothing
here needs training. Runs at 1 Hz on a 20 Msps window: everything added beyond
the STFT is O(T*F) vectorised numpy at most, ~50 ms on the reference box.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

import numpy as np
from scipy.ndimage import uniform_filter1d

from ..dsp.spectrogram import Spectrogram
from . import bursts as bursts_mod
from . import raster as raster_mod
from .bursts import BurstEvent

MORPHOLOGIES = (
    "noise", "narrowband_candidate", "wideband_candidate", "burst_wideband_candidate",
    "ofdm_candidate", "continuous_wideband_candidate", "analog_candidate", "unknown",
    # stage-1 link-signature vocabulary (docs/design/stage1-link-signatures.md S6);
    # replaces the old power-centroid "fhss_candidate".
    "fhss_1mhz_grid_candidate", "fhss_2mhz_grid_candidate", "rc_link_family_candidate",
    "droneid_cadence_candidate", "hopping_candidate", "fixed_channel_burst_candidate",
)

# Priority order in which a T2 link-signature label overrides the plain
# bandwidth/duty-cycle shape bucket below (most specific/rare first). This is
# the position the old centroid-spread ``fhss_candidate`` heuristic used to
# sit at (ahead of the narrowband/wideband/ofdm bucketing).
_T2_LABEL_PRIORITY = (
    "droneid_cadence_candidate",
    "fhss_2mhz_grid_candidate",
    "fhss_1mhz_grid_candidate",
    "rc_link_family_candidate",
    "hopping_candidate",
)

# Shape thresholds (MHz / ratios). Kept as module constants so tests and the
# stage-2 rules can reference the same numbers.
NOISE_SNR_DB = 6.0            # below this the window is "noise"
NARROWBAND_MAX_MHZ = 2.0      # < this  -> narrowband_candidate
WIDEBAND_MIN_MHZ = 6.0        # >= this -> *_wideband / ofdm candidates
ANALOG_MIN_MHZ = 18.0         # >= this and continuous -> analog_candidate
CONTINUOUS_DUTY = 0.8         # duty cycle above which the emitter is "continuous"
FLAT_TOP_SPREAD_DB = 6.0      # p90-p10 of the in-band PSD below this = flat-topped
_MAX_BURST_RUNS = 64          # cap per-burst work (bounded cost per window)
MIN_CLUSTER_EVENTS_FOR_CADENCE = 4   # >= 3 intervals (design S4/T3)

# T1 input conditioning (T3's own adapter, does not touch bursts.py). One raw
# STFT frame is a single periodogram realisation of the underlying process --
# a stationary random signal (an OFDM-like blob, or any bandlimited noise-like
# burst) has ~5.6 dB of *irreducible per-bin fading* on a lone frame, same as
# any single-look spectral estimate. bursts.py's own docstring assumes a "D8
# detector frame" (already a lower-variance estimate, not one FFT snapshot);
# feeding it a raw single-shot STFT frame instead fragments one genuine wide
# burst into dozens of spurious sub-clusters at the 6/3 dB gate/hysteresis
# margins (bridging in bursts.py is time-only, by design, so a 1-bin fade dip
# permanently splits the frequency footprint). A modest frequency-domain
# boxcar smooth over this many Hz -- applied ONLY to the copy handed to
# detect_bursts, never to snr_db/occupied_bw_mhz/duty_cycle/burst_count/
# peak_freq_mhz/score, which stay on the original array -- restores enough
# independent samples (bandwidth / this width bins) to make the burst's own
# footprint contiguous without smearing a genuine 1 MHz hop or a 0.5 MHz
# narrowband burst into its neighbours.
_T1_FREQ_SMOOTH_HZ = 300e3


@dataclass
class Detection:
    score: float                 # detection_probability, 0..1 -- RF strength/interest, NOT "is a drone"
    snr_db: float
    rssi_dbm: float              # approximate; HackRF power is uncalibrated (dBFS + offset)
    peak_freq_mhz: float
    occupied_bw_mhz: float
    burst_count: int
    cadence_ms: float | None     # inter-burst period, if periodic (per-cluster; window-level only)
    signature_class: str         # backward-compat only: "noise" | "unknown" (identity is stage 2)
    morphology: str = "unknown"  # one of MORPHOLOGIES (stage-1 shape vocabulary)
    duty_cycle: float = 0.0      # fraction of STFT slices with the occupied band active
    stage1: dict[str, Any] = field(default_factory=dict)   # additive T2 evidence, see analyze()
    events: list[BurstEvent] = field(default_factory=list)  # this window's T1 burst events, for
                                                              # session-level (cross-window) R3/R1(e)
                                                              # accumulation -- see aerix_rf.pipeline.
                                                              # Not part of the persisted record schema.
    frame_dt_s: float | None = None  # this window's T1 frame pitch (slice_dt_s), forwarded to
                                      # SessionCadenceStore so session-level period_test() gets a
                                      # correct C1 dt-filter floor too (independent review 2026-09-19
                                      # #2). Not part of the persisted record schema.

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _burst_runs(bursts: np.ndarray) -> list[tuple[int, int]]:
    """(start, stop) slice indices of each contiguous burst run, capped."""
    d = np.diff(bursts.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(d == 1)
    stops = np.flatnonzero(d == -1)
    return list(zip(starts[:_MAX_BURST_RUNS].tolist(), stops[:_MAX_BURST_RUNS].tolist()))


def _cluster_cadence_ms(clusters: list, wifi_beacon_cluster_idx: set[int] | None = None) -> float | None:
    """Window-level cadence (design T3): only reported from a single channel
    cluster's OWN burst stream when it holds >= 3 intervals -- never from the
    whole-band envelope (that was the old ``_estimate_cadence_ms`` bug: ambient
    Wi-Fi sets a "cadence" on every candidate). A 1 s window at DroneID's
    640 ms period gives <= 1 interval by construction (design S1/S4), so this
    is expected to be ``None`` for that case at window level; DroneID cadence
    recognition happens at the session level (``aerix_rf.pipeline``).

    Returns ``None`` (never ``0.0``) whenever no cadence is established:
    that includes a degenerate median inter-event gap of 0 s (e.g. two
    fragments of the same physical burst landing in the same cluster at
    (near-)identical timestamps -- a T1 artefact, not a real sub-millisecond
    "cadence"), and a dominant cluster R3 has already tagged
    ``wifi_beacon_like`` (design S3: a cadence better explained by a known
    non-UAS beacon schedule is discounted here the same way raster.py
    discounts it from the level-2 label set, rather than reported as a
    generic "periodic burst" cadence)."""
    if not clusters:
        return None
    dominant_idx = max(range(len(clusters)), key=lambda i: clusters[i].n)
    dominant = clusters[dominant_idx]
    if dominant.n < MIN_CLUSTER_EVENTS_FOR_CADENCE:
        return None
    if wifi_beacon_cluster_idx and dominant_idx in wifi_beacon_cluster_idx:
        return None
    t = np.array(sorted(e.t_start for e in dominant.events))
    dt = np.diff(t)
    if dt.size < 3:
        return None
    median_dt_ms = float(np.median(dt) * 1000.0)
    if not np.isfinite(median_dt_ms) or median_dt_ms <= 0.0:
        return None
    return median_dt_ms


def _morphology(*, snr_db: float, occupied_bw_mhz: float, n_occupied: int,
                burst_count: int, duty_cycle: float, flat_top: bool,
                t2_labels: list[str]) -> str:
    """Shape -> stage-1 vocabulary. No identity claim is made here."""
    if snr_db < NOISE_SNR_DB:
        return "noise"
    if n_occupied == 0:
        return "unknown"
    for lbl in _T2_LABEL_PRIORITY:
        if lbl in t2_labels:
            return lbl
    continuous = duty_cycle > CONTINUOUS_DUTY
    if occupied_bw_mhz < NARROWBAND_MAX_MHZ:
        return "narrowband_candidate"
    if occupied_bw_mhz < WIDEBAND_MIN_MHZ:
        return "wideband_candidate"
    if continuous:
        return "analog_candidate" if occupied_bw_mhz >= ANALOG_MIN_MHZ \
            else "continuous_wideband_candidate"
    if burst_count >= 1:
        return "ofdm_candidate" if flat_top else "burst_wideband_candidate"
    # Wideband, above the floor, but neither continuous nor resolvable bursts.
    if "fixed_channel_burst_candidate" in t2_labels:
        return "fixed_channel_burst_candidate"
    return "wideband_candidate"


def detect(spec: Spectrogram, center_freq_mhz: float,
           snr_threshold_db: float = 8.0, occupied_bw_ref_mhz: float = 10.0,
           gain_db: float = 40.0) -> Detection:
    power_db = spec.power_db                      # [T, F]
    n_time, n_freq = power_db.shape
    bin_hz = spec.sample_rate / n_freq

    # Time envelope: total linear power per STFT slice -> find burst slices first,
    # so a short burst is measured on the slices where it actually occurs rather
    # than averaged into silence across the whole window.
    lin = np.power(10.0, power_db / 10.0)
    p_t = lin.sum(axis=1)                          # [T]
    base = float(np.median(p_t))
    bursts = p_t > (base * 2.5)
    rising = np.count_nonzero(np.diff(bursts.astype(np.int8)) == 1)
    burst_count = int(rising + (1 if bursts[:1].any() else 0))

    # Signal PSD over burst slices vs noise PSD over the rest. For a continuous
    # emitter (or pure noise) there are no "burst" slices, so the floor is taken
    # as a low percentile of the time-averaged PSD: the median would sit ON a
    # wideband emitter's plateau and hide it entirely.
    bursty = bool(bursts.any() and not bursts.all())
    if bursty:
        # Average *linear* power over the burst slices, then dB: a hopper that
        # lights each bin only 1/N of the time still shows up (a mean of dB
        # values would bury it at the noise level).
        sig_psd = 10.0 * np.log10(lin[bursts].mean(axis=0) + 1e-12)      # [F]
        noise_floor = float(np.median(power_db[~bursts]))
        quiet = ~bursts                               # per-bin linear noise level, from p_t (no copy)
        noise_lin = float(p_t[quiet].sum() / (np.count_nonzero(quiet) * n_freq))
    else:
        sig_psd = power_db.mean(axis=0)
        noise_floor = float(np.percentile(sig_psd, 5.0))
        noise_lin = float(np.power(10.0, noise_floor / 10.0)) * 1.78   # mean-of-dB -> linear mean

    peak_db = float(sig_psd.max())
    snr_db = peak_db - noise_floor
    peak_bin = int(np.argmax(sig_psd))
    peak_freq_mhz = center_freq_mhz + spec.freqs_hz[peak_bin] / 1e6

    occupied = sig_psd > (noise_floor + 6.0)
    n_occupied = int(np.count_nonzero(occupied))
    occupied_bw_mhz = float(n_occupied * bin_hz / 1e6)

    # Duty cycle: fraction of slices where the occupied band carries > 2x (3 dB)
    # its expected noise power. Distinguishes a 3 ms/600 ms burst train (~0.005)
    # from a continuous emitter (~1.0). Pure noise has no occupied band -> 0.
    if n_occupied > 0 and snr_db >= NOISE_SNR_DB:
        p_occ_t = lin @ occupied.astype(lin.dtype)  # [T]; mat-vec beats a column gather ~20x
        duty_cycle = float(np.count_nonzero(p_occ_t > 2.0 * noise_lin * n_occupied) / n_time)
    else:
        duty_cycle = 0.0

    # Flat-topped in-band PSD (OFDM-like) vs peaky (carrier + sidebands, analog).
    if n_occupied >= 4:
        band = sig_psd[occupied]
        flat_top = bool(np.percentile(band, 90.0) - np.percentile(band, 10.0) < FLAT_TOP_SPREAD_DB)
    else:
        flat_top = False

    # Time step between STFT frames. Honour the actual hop the spectrogram was
    # computed with (it may be time-decimated for speed); fall back to the old
    # 50 %-overlap assumption for a Spectrogram built without one.
    hop = getattr(spec, "hop", None) or spec.freqs_hz.size // 2
    slice_dt_s = hop / spec.sample_rate

    # -- T1/T2 (docs/design/stage1-link-signatures.md): burst-event extraction
    # and hop-raster/period/cadence-discount evidence, replacing the old
    # power-centroid "hop spread" heuristic. Absolute Hz so cluster centres
    # are meaningful across windows/dwells (session accumulation, R1(e)).
    freqs_hz_abs = center_freq_mhz * 1e6 + spec.freqs_hz
    smooth_bins = max(1, int(round(_T1_FREQ_SMOOTH_HZ / bin_hz)))
    lin_for_bursts = uniform_filter1d(lin, size=smooth_bins, axis=1, mode="nearest") \
        if smooth_bins > 1 else lin
    events = bursts_mod.detect_bursts(
        lin_for_bursts, fs=spec.sample_rate, frame_dt_s=slice_dt_s, freqs_hz=freqs_hz_abs,
        noise_floor_lin=noise_lin, t0_s=0.0,
    )
    clusters = raster_mod.cluster_centres(events)
    raster_result = raster_mod.analyze_raster(events, frame_dt_s=slice_dt_s)
    wifi_beacon_idx = {t.cluster_index for t in raster_result.cadence_tags
                       if t.tag == "wifi_beacon_like"}
    cadence_ms = _cluster_cadence_ms(clusters, wifi_beacon_idx)

    stage1 = {
        "labels": list(raster_result.labels),
        "tags": list(raster_result.tags),
        "consistent_with": list(raster_result.consistent_with),
        "raster_delta_hz": raster_result.raster.delta_hz,
        "raster_p": raster_result.raster.p_false,
        "n_clusters": raster_result.raster.n_channels,
        "period_s": raster_result.period.t_hat_s if raster_result.period.passed else None,
    }

    # Approximate RSSI: peak power is dB relative to full scale; offset by gain to
    # a rough dBm. Not calibrated -- good for relative comparison, flagged as such.
    rssi_dbm = peak_db - gain_db

    # Bounded score: signal strength + bandwidth interest. The old +0.15
    # "cadence_bonus" for a 300-1000 ms whole-band autocorrelation peak is
    # removed (docs/design/stage1-link-signatures.md S4: that estimator fires
    # on ambient Wi-Fi/BLE noise, not just DroneID); cadence is now evidence
    # (``stage1``/``cadence_ms``), not a score input.
    snr_c = float(np.clip((snr_db - snr_threshold_db) / 20.0, 0.0, 1.0))
    bw_c = float(np.clip(occupied_bw_mhz / occupied_bw_ref_mhz, 0.0, 1.0))
    score = float(np.clip(0.5 * snr_c + 0.5 * bw_c, 0.0, 1.0))

    morphology = _morphology(snr_db=snr_db, occupied_bw_mhz=occupied_bw_mhz,
                             n_occupied=n_occupied, burst_count=burst_count,
                             duty_cycle=duty_cycle, flat_top=flat_top,
                             t2_labels=raster_result.labels)

    return Detection(
        score=score,
        snr_db=snr_db,
        rssi_dbm=rssi_dbm,
        peak_freq_mhz=peak_freq_mhz,
        occupied_bw_mhz=occupied_bw_mhz,
        burst_count=burst_count,
        cadence_ms=cadence_ms,
        # Stage 1 makes no identity claim; stage 2 (classify.model) does.
        signature_class="noise" if morphology == "noise" else "unknown",
        morphology=morphology,
        duty_cycle=duty_cycle,
        stage1=stage1,
        events=events,
        frame_dt_s=slice_dt_s,
    )
