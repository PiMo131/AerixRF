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

from ..dsp import spectrogram as spectrogram_mod
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

# C4(a)/(b) (docs/design/stage1-c4-c5-spec.md): the T1 frequency-smoothing
# boxcar above restores independent samples under a Hann window. The design
# doc's estimate was ``L_freq_eff = W / 1.5``; that is measurably wrong.
# Adjacent Hann bins are power-correlated, so for a W-bin boxcar
#   L_freq_eff(W) = W**2 / (W + 2*rho2*(W-1)),  rho2 = |rho(1)|**2,
# with rho(k>=2) negligible. Measured on 3905 x 1024 white-noise STFT frames
# (Hann, hop >= fft): W = 3/5/9/15/20/25/31 -> L_hat = 1.85/2.85/4.86/7.91/
# 10.46/13.02/16.11, which the model above reproduces to <2% at rho2 = 0.48.
# The old W/1.5 gave 16.7 where the truth is 13.0 at W = 25 (the 15.36 MS/s
# dwell), i.e. an arm threshold ~0.45 dB low and ~17x the target arm-pixel
# P_fa; at W = 3 (the 100 MS/s bench column) it gave 2.0 vs a true 1.85. This, together with any detector-local time-domain
# ``looks`` averaging (see ``_detector_local_looks`` below), gives the
# effective look count ``l_eff`` that ``threshold_db_for_pfa`` and
# ``perbin_noise_floor_lin`` need to stay P_fa-correct across receiver
# modes (a fixed dB gate is 6+ dB wrong between a 20-bin-smoothed 15.36 MS/s
# dwell and a 3-bin-smoothed 100 MS/s bench capture). Not independently
# calibrated against real data yet (open evidence gap, design doc "Open
# evidence gaps"); flagged as an estimate, not a measured constant.
_L_FREQ_ADJ_BIN_RHO2 = 0.48

# C4(c): detector-local L-look averaging of contiguous, non-overlapping FFTs
# within one detector frame (design doc C4(c)). NOT free at the canonical
# rate: it recomputes a second STFT from the raw ``iq`` (the canonical
# ``Spectrogram`` only stored one look per hop, since ``hop`` is widened well
# past ``fft_size`` to cap frame count -- see ``dsp.spectrogram``'s
# ``_TARGET_FRAMES``), so the other ``looks - 1`` frames per hop are not
# otherwise available and there is no way to average them out of the existing
# ``spec`` object. Measured cost (see docs/design/stage1-c4-c5-spec.md "CPU
# decision (2026-09-19)"): the recompute adds ~200-300 ms per 1 s window at
# 12.288 MS/s/1024 REGARDLESS of ``looks`` being 2, 3, 4 or 8 (dominated by
# the fancy-index gather + second FFT/fftshift over the whole window, not by
# the look count itself, and ``looks`` is silently clamped to
# ``hop // fft_size`` = 3 at this rate/fft_size anyway) -- there is no
# ``looks >= 2`` setting that fits the ~220 ms detector budget, so this
# constant / ``Config.detector_looks`` (env ``AERIX_RF_DETECTOR_LOOKS``)
# default to 1 (recompute disabled; ``iq`` is not passed to ``detect()`` at
# all in that case -- see ``pipeline.process_window``). Used ONLY here, from
# a caller-supplied ``iq``; the canonical ``Spectrogram`` passed into
# ``detect()`` (PNG / ML tensor / snr_db / occupied_bw_mhz / duty_cycle /
# peak_freq_mhz / score) is never touched.
MAX_DETECTOR_LOOKS = 1


def _l_freq_eff(smooth_bins: int) -> float:
    """Effective independent-look count contributed by the T1 frequency
    boxcar of ``smooth_bins`` bins over a Hann-windowed STFT. See
    ``_L_FREQ_ADJ_BIN_RHO2``."""
    w = max(1, int(smooth_bins))
    if w == 1:
        return 1.0
    return float(w * w / (w + 2.0 * _L_FREQ_ADJ_BIN_RHO2 * (w - 1)))


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


# A narrow cluster that is concurrent with, and sits inside/at the skirt of,
# a MUCH wider simultaneously-active event is a fragment set of that one
# occupant, not an independent burst train (design evidence discipline: a
# cadence claim requires resolved, separated bursts). A continuous wideband
# emitter's spectral skirt always contains a few bins where the per-bin floor
# is partly biased onto the emitter itself, so the emitter is only marginally
# armed there and breaks into short fragments whose inter-fragment spacing is
# a detector artefact. See docs/design/stage1-c4-c5-spec.md
# "S Implementation reconciliation 2026-09-19".
CADENCE_FRAGMENT_BW_RATIO = 4.0      # "much wider" = this many x the cluster BW
CADENCE_FRAGMENT_PROXIMITY = 0.75    # x the wide event's BW, centre-to-centre


def _is_fragment_of_wideband(cluster, events: list) -> bool:
    """True if ``cluster`` looks like fragments of a concurrent, much wider
    occupant (see ``CADENCE_FRAGMENT_BW_RATIO``)."""
    if not events or cluster.n == 0:
        return False
    min_bw = CADENCE_FRAGMENT_BW_RATIO * max(cluster.bw_hz, 1.0)
    times = [(e.t_start, e.t_end) for e in cluster.events]
    need = 0.5 * len(times)
    for w in events:
        if w.bw_6db_hz < min_bw:
            continue
        if abs(cluster.centre_hz - w.centre_hz) > CADENCE_FRAGMENT_PROXIMITY * w.bw_6db_hz:
            continue
        n_overlap = sum(1 for t0, t1 in times if t0 < w.t_end and t1 > w.t_start)
        if n_overlap >= need:
            return True
    return False


def _cluster_cadence_ms(clusters: list, wifi_beacon_cluster_idx: set[int] | None = None,
                         events: list | None = None) -> float | None:
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
    if events is not None and _is_fragment_of_wideband(dominant, events):
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
           gain_db: float = 40.0, *, iq: np.ndarray | None = None,
           max_looks: int = MAX_DETECTOR_LOOKS) -> Detection:
    """``iq`` (optional, keyword-only): the same raw IQ ``spec`` was computed
    from. When given, the T1/T2 burst/raster pipeline below additionally
    averages up to ``max_looks`` contiguous FFTs per detector frame
    (design doc C4(c)) -- a detector-local product that never changes
    ``spec``/the canonical representation itself. Omit it (the default) to
    keep today's single-look behaviour exactly."""
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

    # C4(d) (docs/design/stage1-c4-c5-spec.md): deliberately left on the
    # scalar ``noise_floor``/``noise_lin`` estimated above, NOT the per-bin
    # C4(a) floor used for the T1/T2 burst pipeline below -- these three
    # fields feed the stage-2 classifier's existing feature contract, and
    # changing their estimator is out of this change's scope.
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
    #
    # C4(c): detector-local L-look averaging, ONLY for this pipeline -- see
    # ``MAX_DETECTOR_LOOKS``'s docstring. ``n_looks`` stays 1 (no-op) unless
    # the caller passed ``iq`` and the canonical ``hop`` actually has room for
    # more than one contiguous fft_size-length look.
    n_looks = 1
    lin_local = lin
    if iq is not None and hop:
        n_looks = max(1, min(max_looks, int(hop) // n_freq))
        if n_looks > 1:
            local_spec = spectrogram_mod.compute(
                iq, spec.sample_rate, fft_size=n_freq, hop=hop,
                remove_dc=True, looks=n_looks,
            )
            lin_local = np.power(10.0, local_spec.power_db.astype(np.float64) / 10.0)

    freqs_hz_abs = center_freq_mhz * 1e6 + spec.freqs_hz
    smooth_bins = max(1, int(round(_T1_FREQ_SMOOTH_HZ / bin_hz)))
    lin_for_bursts = uniform_filter1d(lin_local, size=smooth_bins, axis=1, mode="nearest") \
        if smooth_bins > 1 else lin_local

    # C4(a)/(b): per-bin (not scalar) noise floor and the matching P_fa-
    # targeted gate/hold margins. ``l_eff`` = (detector-local time looks) x
    # (frequency-smoothing looks) -- see ``_L_FREQ_EFF_HANN_DIVISOR``'s
    # docstring for the caveat that the frequency term is an estimate.
    l_freq_eff = _l_freq_eff(smooth_bins)
    l_eff = float(n_looks) * l_freq_eff
    # ``ref_lin``: the band-wide clamp reference must NOT be the median over
    # bins when one emitter can occupy most of the band. ``noise_lin`` above
    # is estimated either from non-burst TIME slices or (continuous case)
    # from the 5th percentile over bins, so it survives up to ~95%
    # frequency occupancy -- see ``perbin_noise_floor_lin``'s ``ref_lin``.
    # It is the mean noise power per bin of the UNSMOOTHED array; the boxcar
    # preserves the mean, so it is the right scale for ``lin_for_bursts``.
    floor_perbin, floor_excess_db = bursts_mod.perbin_noise_floor_lin(
        lin_for_bursts, l_eff=l_eff, ref_lin=noise_lin, return_excess=True)

    events = bursts_mod.detect_bursts(
        lin_for_bursts, fs=spec.sample_rate, frame_dt_s=slice_dt_s, freqs_hz=freqs_hz_abs,
        noise_floor_lin=floor_perbin, floor_excess_db=floor_excess_db,
        l_eff=l_eff, t0_s=0.0,
    )
    clusters = raster_mod.cluster_centres(events)
    raster_result = raster_mod.analyze_raster(events, frame_dt_s=slice_dt_s, bin_hz=bin_hz)
    wifi_beacon_idx = {t.cluster_index for t in raster_result.cadence_tags
                       if t.tag == "wifi_beacon_like"}
    cadence_ms = _cluster_cadence_ms(clusters, wifi_beacon_idx, events=events)

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
