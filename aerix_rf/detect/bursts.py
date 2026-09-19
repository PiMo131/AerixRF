"""Stage-1 burst extraction from D8 detector frames (200 us, linear power).

Implements T1 of ``docs/design/stage1-link-signatures.md``: turn a
``[n_frames x n_bins]`` linear-power tensor (``aerix_rf.datasets.tensor.
detector_frames``, or the live detector's equivalent) into a bounded list of
:class:`BurstEvent` objects with a **-6 dB edge-midpoint** centre/bandwidth
estimate -- not a power centroid. The centroid moves with the emitter's
spectral shape (MCS, aggregation, skirt asymmetry) even when the true centre
frequency is fixed; that drift is the root cause of the current
``fhss_candidate`` mislabel in ``aerix_rf/detect/energy.py`` (see the design
doc S0/S2). This module does not touch that file (T3's job).

Pure function, no I/O, deterministic, vectorised. Cost budget: <=50 ms for a
1 s / 12.288 MS/s dwell (measured in tests/test_detect_bursts.py).

Gating (design doc S "Burst gating"): a pixel is a *candidate* burst pixel if
its power exceeds its own bin's noise floor by >= ``GATE_DB`` (arm) or
>= ``HYST_DB`` (hold); a component of hold-pixels is promoted to a burst only
if it contains at least one arm pixel (2-D hysteresis). Gaps of <=1 frame
within one frequency bin are bridged (time-only morphological closing) before
connected-component labelling. Grouping bursts by (time x frequency)
connected components is the vectorised, non-quantised equivalent of the
doc's "per-sub-band greatest-of" test: instead of pre-tiling the band into a
fixed sub-band grid, each burst's own frequency footprint IS its sub-band,
which avoids splitting one hop's passband across an arbitrary grid boundary
and avoids a sub-band-width tuning parameter. Two bursts that are
simultaneously active but at different, non-adjacent centre frequencies are
therefore always separated (different connected components), which is what
the design doc's per-sub-band requirement is for (S "acceptance (c)").

Centre/bandwidth: per component, take the time-integrated (mean) linear-power
spectrum over the component's active frame range, over the FULL bin axis (not
just the component's own bins) so the true -6 dB skirt is captured even where
it dips outside the >=GATE_DB region; the walk that finds the -6 dB crossing
starts at the component's OWN peak bin (not the global argmax), so a second,
stronger, simultaneous emitter elsewhere in the window cannot bias this
component's edges. If the walk reaches the array's frequency edge before
crossing -6 dB, that edge is reported at the true band edge and the event is
flagged ``edge_clipped`` (this is what makes the "Wi-Fi burst wider than the
dwell" case in the acceptance tests report ``centre_hz`` at the dwell centre).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from typing import Any

import numpy as np
import scipy.fft as sfft
from scipy import stats
from scipy.ndimage import find_objects, label

GATE_DB = 6.0            # arm threshold: floor + this many dB (fixed-dB fallback /
                          # explicit-override path -- see ``threshold_db_for_pfa``)
HYST_DB = 3.0            # hold threshold: floor + this many dB (hysteresis; ditto)
EDGE_DB = 6.0            # the "-6 dB" in "-6 dB edge midpoint"
_EPS = 1e-12

# C4 (docs/design/stage1-c4-c5-spec.md S(b)): the gate/hold operating point is
# specified as a false-arm-pixel PROBABILITY, not a fixed dB margin, because a
# fixed dB gate is mode-dependent (the number of independent looks entering
# ``detect_bursts`` varies with the receiver's frequency-smoothing width and
# any detector-local time averaging -- see ``energy.py``'s ``_T1_FREQ_SMOOTH_HZ``
# and ``looks``). ``threshold_db_for_pfa`` converts a target P_fa + the
# effective look count into the dB-over-mean-floor margin that achieves it.
ARM_PFA = 1e-6            # ~0.3 false arm pixels per 2000x1024 window
HOLD_PFA = 2e-3           # ~4000 hold pixels; only those 4-connected to an arm
                           # pixel survive to become an event
DEFAULT_L_EFF = 1.0        # single-look fallback when the caller does not know
                           # its own effective look count

# C4(a): per-bin noise floor estimator constants.
FLOOR_CLAMP_DB = 10.0      # +/- this many dB around the band-wide (median-over-
                           # -bins) reference; measured per-bin p10-p90 floor
                           # spread over a 100 MHz span is 6-7 dB, so this
                           # covers real analog tilt/roll-off but not a
                           # 20-30 dB occupied (e.g. Wi-Fi) channel, which is
                           # the point: such a bin stays armed and surfaces as
                           # its own (wide, edge-clipped) event instead of
                           # self-blinding.
FLOOR_QUANTILE = 0.25      # 25th percentile: tolerates up to 75% occupancy
                           # (a busy Wi-Fi channel or continuous downlink),
                           # vs 50% for the median -- see the design doc.
FLOOR_STRIDE = 4           # decimate frames before the percentile to hold the
                           # estimator inside the ~4-8 ms cost budget.
FLOOR_MIN_FRAMES = 256     # do not decimate below this many frames.
# C2 fix (docs/design/stage1-rc-positives-2026-09-19.md S3/S4): the old
# ``_MAX_EVENTS = 64`` was a TIME cut, not a strength cut -- scipy.ndimage.label
# numbers connected components in raster (time-major) scan order, so "first 64"
# meant "components found in the first ~0.5% of the window" for any dense
# capture (3-20 k bursts/s measured on real RC-transmitter IQ). Raised to 256
# (the empirically working point in the design-doc cap sweep) and the
# selection is now STRONGEST-256-BY-PEAK-POWER, not first-256-by-label-id, so
# the retained events are no longer concentrated in a few milliseconds of the
# window (see ``_channelise``). Still configurable per call site.
_MAX_EVENTS = 256
_MAX_REFINE = 16         # 33.3 us refinement is gated to this many bursts

# 4-connectivity (no diagonal): a component can only grow along one axis at a
# time, so a burst that changes centre by one hop is still not accidentally
# fused to a diagonal-adjacent, unrelated burst.
_LABEL_STRUCT = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)


def _bridge_1frame_gaps(low: np.ndarray) -> np.ndarray:
    """Morphological closing with a 3-tall, 1-wide (time-only) structuring
    element, i.e. bridges a single-frame gap in one frequency bin without
    ever spreading a component sideways in frequency -- equivalent to
    ``scipy.ndimage.binary_closing(low, structure=[[1],[1],[1]],
    border_value=1)`` but an order of magnitude cheaper as plain shift/OR/AND
    numpy ops (no generic per-pixel structuring-element machinery). Dilation
    treats "past either time edge" as False (nothing to bridge into); erosion
    treats it as True (``border_value=1``: a true edge pixel must not be
    eroded away just because it has no time-neighbour on one side)."""
    up = np.zeros_like(low)
    up[1:] = low[:-1]
    down = np.zeros_like(low)
    down[:-1] = low[1:]
    dilated = low | up | down

    dil_up = np.ones_like(dilated)
    dil_up[1:] = dilated[:-1]
    dil_down = np.ones_like(dilated)
    dil_down[:-1] = dilated[1:]
    return dilated & dil_up & dil_down


@dataclass
class BurstEvent:
    t_start: float                # s, absolute (t0_s + frame index * frame_dt_s)
    t_end: float                  # s, absolute, exclusive
    duration_s: float
    centre_hz: float              # -6 dB edge midpoint (NOT the power centroid)
    bw_6db_hz: float
    peak_db_over_floor: float
    mean_db_over_floor: float
    n_frames: int
    edge_clipped: bool            # touches the time edge of the input or a
                                   # frequency edge of the bin axis
    bw_noise_limited: bool = False  # the -6 dB level lies BELOW this component's
                                     # own hold threshold on at least one side, so
                                     # the -6 dB edge walk stopped on the noise
                                     # limit: ``bw_6db_hz``/``centre_hz`` are then
                                     # detector artefacts (a lower bound and a
                                     # midpoint of that lower bound), not a
                                     # measured channel. See ``_edge_cross``.

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _floor_lin(power_lin: np.ndarray, noise_floor_lin: np.ndarray | float | None) -> np.ndarray:
    """Per-bin noise floor, linear power, broadcastable against ``power_lin``'s
    columns. Kept in linear units so the hot gating path (run over every
    frame x bin pixel) never needs a full-array ``log10`` -- dB is only taken
    later, on the much smaller per-event slices."""
    if noise_floor_lin is None:
        # Fallback estimator only -- callers that already know the floor
        # (the live detector, or a test) should pass it explicitly. Estimated
        # in dB (5th percentile is a robust "below almost everything" floor
        # for a mixture of noise + sparse bursts) then converted back.
        power_db = 10.0 * np.log10(np.maximum(power_lin, _EPS))
        floor_db = np.percentile(power_db, 5.0, axis=0)
        return np.power(10.0, floor_db / 10.0)
    arr = np.asarray(noise_floor_lin, dtype=np.float64)
    return np.broadcast_to(arr, (power_lin.shape[1],)).astype(np.float64)


def _q25_bias(l_eff: float) -> float:
    """``Q25(L) = gamma.ppf(0.25, a=L) / L``: the ratio of the 25th-percentile
    of an ``L``-look-averaged exponential (Gamma(L, 1/L)-mean-normalised)
    power estimate to its true mean. Dividing a measured 25th percentile by
    this constant debiases it back to the mean noise power. ``L=1`` gives
    ``-ln(0.75) = 0.2877`` (the single-look, no-averaging case); ``L=4``
    gives ``0.6339``. Non-integer ``l_eff`` (a smoothing-bin or looks count
    that is not an exact integer) is handled by the continuous Gamma
    distribution, which coincides with the Erlang sum-of-exponentials CDF at
    integer ``L``."""
    l_eff = max(float(l_eff), _EPS)
    return float(stats.gamma.ppf(FLOOR_QUANTILE, a=l_eff) / l_eff)


def threshold_db_for_pfa(pfa: float, l_eff: float) -> float:
    """dB-over-mean-floor margin ``T`` such that
    ``P(pixel power >= floor * 10**(T/10)) == pfa`` for an ``l_eff``-look
    power estimate (Gamma(l_eff, 1/l_eff)-mean-normalised). Inverts the Gamma
    survival function: ``x = gamma.isf(pfa, a=l_eff) / l_eff``,
    ``T_db = 10*log10(x)``. At ``l_eff=1`` this reduces to the familiar
    single-look exponential tail ``P_fa = exp(-x)``.

    Replaces a hard-coded dB gate (design doc C4(b)): a fixed dB margin is
    mode-dependent -- the number of independent looks entering
    ``detect_bursts`` varies with frequency smoothing / detector-local time
    averaging -- so the operating point is specified as a P_fa target and the
    dB margin solved for at runtime instead.
    """
    l_eff = max(float(l_eff), _EPS)
    pfa = float(np.clip(pfa, 1e-300, 1.0 - 1e-15))
    x = stats.gamma.isf(pfa, a=l_eff) / l_eff
    return float(10.0 * np.log10(max(x, _EPS)))


def perbin_noise_floor_lin(power_lin: np.ndarray, *, l_eff: float = DEFAULT_L_EFF,
                            stride: int = FLOOR_STRIDE,
                            min_floor_frames: int = FLOOR_MIN_FRAMES,
                            clamp_db: float = FLOOR_CLAMP_DB,
                            ref_lin: float | None = None) -> np.ndarray:
    """Per-bin noise floor, linear MEAN power, ``[n_bins]`` (design doc
    C4(a)).

    Estimator: the 25th percentile of each bin's power over a
    stride-decimated frame subset (``np.partition``, not a full sort, to
    stay inside the cost budget), debiased to the mean via ``_q25_bias``,
    then clamped to +/- ``clamp_db`` of the band-wide (median-over-bins)
    reference ``F_ref``. The clamp is mandatory, not optional: a bin occupied
    more than 75% of the window (continuous Wi-Fi/video downlink) has its own
    25th percentile sitting ON the signal, so it is pulled back to
    ``F_ref +/- clamp_db`` instead of being trusted -- this keeps the bin
    armed so the occupant still surfaces as its own (wide, edge-clipped)
    event rather than self-blinding the detector.

    ``ref_lin`` overrides the band-wide clamp reference ``F_ref``. The
    default (``None``) uses the median over bins, which is only valid while
    LESS THAN HALF the band is occupied. A single wideband occupant (analog
    FPV video, a 16-20 MHz downlink in a 20 MHz capture) puts the median ON
    the signal: every idle bin is then clamped UP to ``F_ref - clamp_db``
    (detector goes noise-blind) and the occupant's own bins sit ~0 dB over
    their floor, so the emitter fragments into speckle instead of one
    continuous wideband event. Callers that already hold a band-wide noise
    estimate immune to frequency occupancy -- ``energy.detect``'s
    ``noise_lin``, taken either from non-burst TIME slices or from the 5th
    percentile over bins -- must pass it here. This is a reference for the
    CLAMP only; the per-bin Q25 estimate is unchanged, so real analog
    tilt/roll-off is still tracked per bin.
    """
    power_lin = np.asarray(power_lin, dtype=np.float64)
    n_frames, n_bins = power_lin.shape
    if n_frames == 0 or n_bins == 0:
        return np.zeros(n_bins, dtype=np.float64)

    step = max(1, int(stride))
    sub = power_lin[::step]
    if sub.shape[0] < min(min_floor_frames, n_frames):
        sub = power_lin  # too few decimated frames: use the full (bounded) set

    k = int(np.clip(round(FLOOR_QUANTILE * (sub.shape[0] - 1)), 0, sub.shape[0] - 1))
    part = np.partition(sub, k, axis=0)
    q25 = part[k]

    bias = _q25_bias(l_eff)
    floor = q25 / max(bias, _EPS)

    f_ref = float(ref_lin) if ref_lin is not None else float(np.median(floor))
    if not np.isfinite(f_ref) or f_ref <= 0.0:
        return np.maximum(floor, _EPS)
    # Outside +/- ``clamp_db`` of the reference the per-bin estimate is
    # REJECTED, and the fallback is the reference itself -- not the rejection
    # boundary. Clipping to the boundary (the first implementation) leaves a
    # bin whose Q25 sat on a continuous occupant with a floor exactly
    # ``clamp_db`` above the true noise, so the occupant's detection margin
    # is (its SNR - clamp_db): a 15 dB continuous wideband emitter was left
    # ~5 dB over its own floor, i.e. right at the arm threshold, and
    # fragmented into 1-frame speckle across the whole window (spurious
    # "hopping"/cadence from ONE continuous emitter). Once the clamp binds we
    # have positive evidence the bin's own estimate is contaminated, and the
    # best remaining estimate of its noise power is the band-wide reference;
    # real analog tilt/roll-off (6-7 dB p10-p90) never reaches the rejection
    # radius, so tilt tracking is unaffected. The low side is treated the
    # same way (a bin >clamp_db BELOW the reference is a notch/dead bin;
    # using the higher F_ref there is the conservative, fewer-false-alarm
    # choice).
    lo = f_ref * 10.0 ** (-clamp_db / 10.0)
    hi = f_ref * 10.0 ** (clamp_db / 10.0)
    return np.where((floor < lo) | (floor > hi), f_ref, floor)


def _edge_cross(profile_db: np.ndarray, freqs_hz: np.ndarray, peak_idx: int,
                 thresh_db: float, direction: int,
                 stop_db: np.ndarray | None = None) -> tuple[float, bool]:
    """Walk from ``peak_idx`` in ``direction`` (+1/-1) until ``profile_db``
    drops below ``thresh_db``; return the interpolated crossing frequency and
    whether the walk instead ran off the array (a frequency-edge clip), and
    whether the walk was stopped by ``stop_db`` (the noise limit) rather than
    by the -6 dB level itself -- in which case the returned edge is a
    NOISE-LIMITED bound, not a measured -6 dB edge (see ``bw_noise_limited``).

    ``stop_db`` (``[n_bins]``, optional) is a per-bin NOISE-LIMIT profile
    (the caller passes ``floor_db + hysteresis_db``): the walk also stops
    where the profile falls below it. Rationale -- a -6 dB edge cannot be
    measured below the noise. When a component's peak is less than
    ``EDGE_DB`` above its own hold threshold (a weak or single-frame
    component), the -6 dB level lies UNDER the noise floor, the walk never
    crosses it, and the unbounded version ran to the band edge and reported
    ``bw_6db_hz`` = the whole captured band. That is how a handful of
    marginal components ended up dominating the median measured bandwidth of
    a window containing only 300 kHz bursts. Stopping at the noise limit
    reports the width down to the noise instead, which is the widest claim
    the data supports. For any component whose peak clears its hold
    threshold by >= ``EDGE_DB`` the -6 dB crossing is reached first and this
    bound never binds."""
    n = profile_db.shape[0]
    i = peak_idx
    bin_hz = float(freqs_hz[1] - freqs_hz[0]) if n > 1 else 0.0
    while 0 <= i + direction < n:
        j = i + direction
        limit = thresh_db if stop_db is None else max(thresh_db, float(stop_db[j]))
        if profile_db[j] < limit:
            # Linear interpolation between i (>= thresh) and j (< thresh).
            span = profile_db[i] - profile_db[j]
            frac = 0.0 if span <= 0 else (profile_db[i] - limit) / span
            frac = min(max(frac, 0.0), 1.0)
            f = freqs_hz[i] + direction * frac * bin_hz
            return float(f), False, bool(limit > thresh_db)
        i = j
    # Ran off the edge without crossing: report the true band edge, clipped.
    edge = freqs_hz[0] - 0.5 * bin_hz if direction < 0 else freqs_hz[-1] + 0.5 * bin_hz
    return float(edge), True, False


def _channelise(power_lin: np.ndarray, floor_lin: np.ndarray,
                 freqs_hz: np.ndarray, t0_s: float, frame_dt_s: float,
                 gate_db: float, hyst_db: float, max_events: int) -> list[BurstEvent]:
    n_total_frames, n_bins = power_lin.shape
    gate_ratio = 10.0 ** (gate_db / 10.0)
    hyst_ratio = 10.0 ** (hyst_db / 10.0)
    floor_row = floor_lin[None, :]
    high = power_lin >= (floor_row * gate_ratio)
    low = power_lin >= (floor_row * hyst_ratio)
    if not high.any():
        return []
    low_closed = _bridge_1frame_gaps(low)
    labelled, n_labels = label(low_closed, structure=_LABEL_STRUCT)
    if n_labels == 0:
        return []
    objects = find_objects(labelled)
    floor_db = 10.0 * np.log10(np.maximum(floor_lin, _EPS))   # [n_bins], cheap
    # Noise limit for the -6 dB edge walk: below this a bin is not part of
    # any burst by the detector's own hold criterion, so the walk must not
    # continue through it (see ``_edge_cross``'s ``stop_db``).
    noise_limit_db = floor_db + hyst_db

    # C2 fix (perf revision): the arm-pixel confirmation ("is this component
    # ever actually armed, not just held?") and the strength ranking used
    # for the cap are computed for every label in one vectorised pass, so
    # the per-event Python loop below never repeats a per-component boolean
    # slice+``.any()`` (``labelled[t_slice, f_slice] == idx`` +
    # ``high[...][region_mask].any()``). The retained set is the STRONGEST
    # ``max_events`` (by peak power) of the arm-confirmed components, not
    # the first ``max_events`` in label-id (time-major) order, so raising
    # the cap does not concentrate events in a few ms of the window. The
    # output loop still walks components in their original (time-major) id
    # order, so the *order* of returned events is unchanged by this
    # selection -- only which components survive the cap changes, and only
    # the retained components pay for the (more expensive) per-event
    # profile/edge-walk below.
    #
    # This gather is done via a single ``np.nonzero(low_closed)`` over the
    # FOREGROUND pixels only, rather than ``scipy.ndimage.sum_labels``/
    # ``maximum`` over the whole ``[n_frames, n_bins]`` image: those two
    # ndimage calls each do a full-array pass regardless of how few labels
    # exist, which costs ~40 ms on a 5000x1024 frame even when the
    # foreground is a sparse handful of short bursts (<1% of pixels). Cost
    # here scales with the number of foreground (labelled) pixels instead
    # of the window size.
    idx_t, idx_f = np.nonzero(low_closed)
    labels_flat = labelled[idx_t, idx_f]
    high_flat = high[idx_t, idx_f]
    power_flat = power_lin[idx_t, idx_f]

    arm_counts = np.bincount(labels_flat, weights=high_flat.astype(np.float64),
                              minlength=n_labels + 1)[1:]
    label_ids = np.arange(1, n_labels + 1)
    confirmed_ids = label_ids[arm_counts > 0]
    if confirmed_ids.size == 0:
        return []
    if confirmed_ids.size > max_events:
        peak_all = np.full(n_labels + 1, -np.inf)
        np.maximum.at(peak_all, labels_flat, power_flat)
        peak_vals = peak_all[confirmed_ids]
        top = np.argpartition(-peak_vals, max_events - 1)[:max_events]
        selected_ids = set(int(i) for i in confirmed_ids[top])
    else:
        selected_ids = set(int(i) for i in confirmed_ids)

    events: list[BurstEvent] = []
    for idx, obj in enumerate(objects, start=1):
        if obj is None or idx not in selected_ids:
            continue  # obj is None: not a labelled pixel; not selected:
                       # either never arm-confirmed, or cut by the cap above

        t_slice, f_slice = obj
        t_start_i, t_stop_i = t_slice.start, t_slice.stop
        f_start_i, f_stop_i = f_slice.start, f_slice.stop
        n_frames = t_stop_i - t_start_i

        # Time-integrated (mean) linear-power spectrum over the FULL bin axis
        # for this component's active frame range (small: n_frames x n_bins).
        profile_lin = power_lin[t_start_i:t_stop_i, :].mean(axis=0)
        profile_db = 10.0 * np.log10(np.maximum(profile_lin, _EPS))

        # Peak within the component's OWN frequency footprint only, so a
        # stronger simultaneous emitter elsewhere cannot steal the peak.
        local_peak = f_start_i + int(np.argmax(profile_db[f_start_i:f_stop_i]))
        peak_db = profile_db[local_peak]
        thresh_db = peak_db - EDGE_DB

        left_hz, left_clip, left_nl = _edge_cross(profile_db, freqs_hz, local_peak, thresh_db, -1,
                                                   stop_db=noise_limit_db)
        right_hz, right_clip, right_nl = _edge_cross(profile_db, freqs_hz, local_peak, thresh_db, +1,
                                                      stop_db=noise_limit_db)
        # FA fix 2026-09-19 (docs/design/stage1-c4-c5-spec.md "S FA regression
        # 2026-09-19"): a component whose peak is less than ``EDGE_DB`` above
        # its own hold threshold has no measurable -6 dB width -- the walk
        # stops on ``noise_limit_db`` within a bin or two of the peak and
        # reports a bandwidth far below the detector's own frequency
        # resolution (the T1 boxcar in ``energy.detect`` is 300 kHz wide, so
        # NO real component can measure 6-60 kHz here). Both its bandwidth
        # and its -6 dB-midpoint centre are then artefacts of where the
        # threshold happened to cut the noise, so downstream channel/raster
        # reasoning must not treat it as a resolved channel.
        bw_noise_limited = bool(left_nl or right_nl)
        centre_hz = 0.5 * (left_hz + right_hz)
        bw_hz = right_hz - left_hz

        time_clip = (t_start_i == 0) or (t_stop_i == n_total_frames)
        edge_clipped = bool(time_clip or left_clip or right_clip)

        region_db = 10.0 * np.log10(np.maximum(
            power_lin[t_start_i:t_stop_i, f_start_i:f_stop_i], _EPS))
        region_db_over_floor = region_db - floor_db[None, f_start_i:f_stop_i]

        events.append(BurstEvent(
            t_start=t0_s + t_start_i * frame_dt_s,
            t_end=t0_s + t_stop_i * frame_dt_s,
            duration_s=n_frames * frame_dt_s,
            centre_hz=centre_hz,
            bw_6db_hz=bw_hz,
            peak_db_over_floor=float(peak_db - floor_db[local_peak]),
            mean_db_over_floor=float(region_db_over_floor.mean()),
            n_frames=int(n_frames),
            edge_clipped=edge_clipped,
            bw_noise_limited=bw_noise_limited,
        ))
    return events


def _refine_duration(event: BurstEvent, iq: np.ndarray, iq_fs: float, floor_lin: float,
                      fft_size: int, hop: int, guard_s: float) -> BurstEvent:
    """Re-estimate ``t_start``/``t_end``/``duration_s`` at native (hop/iq_fs)
    resolution from a raw-IQ slice around the burst, restricted to the
    burst's own [centre-bw/2, centre+bw/2] band. Best-effort: if the slice is
    too short to form even one analysis frame, the 200 us estimate is kept
    unchanged."""
    lo_hz = event.centre_hz - 0.5 * event.bw_6db_hz
    hi_hz = event.centre_hz + 0.5 * event.bw_6db_hz
    s0 = max(0, int(round((event.t_start - guard_s) * iq_fs)))
    s1 = min(iq.shape[-1], int(round((event.t_end + guard_s) * iq_fs)))
    seg = iq[s0:s1]
    if seg.shape[-1] < fft_size:
        return event

    n_frames = (seg.shape[-1] - fft_size) // hop + 1
    win = np.hanning(fft_size).astype(np.float64)
    frames = np.lib.stride_tricks.sliding_window_view(seg, fft_size)[::hop][:n_frames]
    spec = sfft.fftshift(sfft.fft(frames * win, axis=1), axes=1)
    power = (np.abs(spec) ** 2).astype(np.float64)
    freqs = sfft.fftshift(sfft.fftfreq(fft_size, d=1.0 / iq_fs))

    band = (freqs >= lo_hz) & (freqs <= hi_hz)
    if not band.any():
        return event
    env = power[:, band].sum(axis=1)
    on = env > (2.0 * floor_lin * np.count_nonzero(band))
    if not on.any():
        return event
    active = np.flatnonzero(on)
    frame_dt = hop / iq_fs
    t_start = (s0 / iq_fs) + active[0] * frame_dt
    t_end = (s0 / iq_fs) + (active[-1] + 1) * frame_dt
    return replace(event, t_start=t_start, t_end=t_end, duration_s=t_end - t_start)


def detect_bursts(
    power_lin: np.ndarray,
    *,
    fs: float,
    frame_dt_s: float,
    freqs_hz: np.ndarray | None = None,
    noise_floor_lin: np.ndarray | float | None = None,
    t0_s: float = 0.0,
    gate_db: float | None = None,
    hysteresis_db: float | None = None,
    arm_pfa: float = ARM_PFA,
    hold_pfa: float = HOLD_PFA,
    l_eff: float = DEFAULT_L_EFF,
    max_events: int = _MAX_EVENTS,
    iq: np.ndarray | None = None,
    iq_fs: float | None = None,
    refine_fft: int = 1024,
    refine_hop: int = 512,
    refine_guard_s: float = 200e-6,
    max_refine: int = _MAX_REFINE,
) -> list[BurstEvent]:
    """Gate and channelise D8 detector frames into :class:`BurstEvent`\\ s.

    ``power_lin`` is ``[n_frames, n_bins]`` linear power (D8: 200 us frames).
    ``freqs_hz`` are the bin-centre frequencies matching the column axis
    (defaults to an fftshifted baseband axis ``fs*k/n_bins``); pass absolute
    Hz (tuned_centre + bin_offset - lo_offset) to get absolute ``centre_hz``.
    ``noise_floor_lin`` is the per-bin (or scalar) linear noise floor; if
    omitted it is estimated as the 5th percentile of each bin's power over
    time (a fallback only -- callers that already track a floor should pass
    it). If ``iq``/``iq_fs`` are given, up to ``max_refine`` bursts (by order
    of detection) get a 33.3 us-native duration refinement from a re-STFT of
    their own raw-IQ slice.

    ``gate_db``/``hysteresis_db`` are the explicit-override path (design doc
    C4(b)): pass them (e.g. the module constants ``GATE_DB``/``HYST_DB``) to
    force a fixed dB margin as before. Left at their default (``None``), the
    margin is instead solved from a target false-arm/false-hold pixel
    probability (``arm_pfa``/``hold_pfa``) and the caller's effective look
    count ``l_eff`` via ``threshold_db_for_pfa`` -- a fixed dB gate is
    mode-dependent (the number of independent looks varies with frequency
    smoothing / detector-local time averaging), so the operating point is a
    P_fa target, not a hard-coded margin.
    """
    power_lin = np.asarray(power_lin, dtype=np.float64)
    if power_lin.ndim != 2:
        raise ValueError("power_lin must be [n_frames, n_bins]")
    n_frames, n_bins = power_lin.shape
    if n_frames == 0 or n_bins == 0:
        return []
    if freqs_hz is None:
        freqs_hz = np.fft.fftshift(np.fft.fftfreq(n_bins, d=1.0 / fs))
    freqs_hz = np.asarray(freqs_hz, dtype=np.float64)

    if gate_db is None:
        gate_db = threshold_db_for_pfa(arm_pfa, l_eff)
    if hysteresis_db is None:
        hysteresis_db = threshold_db_for_pfa(hold_pfa, l_eff)

    floor_lin_arr = _floor_lin(power_lin, noise_floor_lin)

    events = _channelise(power_lin, floor_lin_arr, freqs_hz, t0_s, frame_dt_s,
                          gate_db, hysteresis_db, max_events)

    if iq is not None and events:
        floor_lin_scalar = float(floor_lin_arr.mean())
        for k in range(min(max_refine, len(events))):
            events[k] = _refine_duration(events[k], iq, iq_fs or fs, floor_lin_scalar,
                                          refine_fft, refine_hop, refine_guard_s)
    return events
