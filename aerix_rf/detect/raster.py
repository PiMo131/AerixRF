"""Stage-1 hop-raster / hop-period / cadence-discount evidence (T2).

Implements T2 of ``docs/design/stage1-link-signatures.md`` (rules R1-R5) over
the ``list[BurstEvent]`` produced by ``aerix_rf.detect.bursts`` (T1). Pure
functions, no I/O, deterministic. This module does not touch ``energy.py`` or
``classify`` (T3's job) and never emits a manufacturer/vendor label -- vendor
tokens only ever appear inside ``consistent_with``, which is an informational
consistency list, never a detection.

Evidence-level discipline (see ``research/briefs/rc-link-raster-facts.md`` and
CLAUDE.md "Evidence levels"):
  * Level 1 (RF candidate / morphology): ``hopping_candidate``,
    ``fixed_channel_burst_candidate`` -- says only "channel-use pattern looks
    like X", no probabilistic family claim.
  * Level 2 (probabilistic classification, still not identity):
    ``fhss_1mhz_grid_candidate``, ``fhss_2mhz_grid_candidate``,
    ``rc_link_family_candidate``, ``droneid_cadence_candidate`` -- a
    structured statistical test (explicit false-match probability) says the
    burst set is consistent with a *family* of emitters, never a specific
    manufacturer. ``consistent_with`` entries (e.g. ``"expresslrs_2g4"``) are
    informational cross-references only and MUST NOT be read as identity;
    identity requires a CRC-valid protocol decode (level 4), which this
    module never attempts.
  * Discount tags (``wifi_beacon_like``, ``ble_connection_like``) suppress a
    level-2 label when the cadence is better explained by a known non-UAS
    system; ``INSUFFICIENT_CHANNELS`` means the grid test was not attempted
    because there is not enough distinct-channel evidence to run it (an
    "unknown", not a "no").

The DJI RC 2.4 GHz uplink raster/offset is UNKNOWN (see the facts brief) and
is never hardcoded here; the only 2 MHz grid label this module can emit
(``fhss_2mhz_grid_candidate``) is deliberately generic and always carries a
BLE-collision note (R1(e)).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from aerix_rf.detect.bursts import BurstEvent

# --------------------------------------------------------------------------
# Configurable parameters (design doc S7). Kept as module-level constants so
# a future config surface can override them without touching the algorithm.
# --------------------------------------------------------------------------

DEFAULT_CLUSTER_TOL_HZ = 100e3          # design S2(a): "cluster centres at 100 kHz"
CLUSTER_BW_SEPARATION_FRAC = 0.75       # min separation floor: 0.75 * max(BW_i, BW_j)

# C3 fix (docs/design/stage1-rc-positives-2026-09-19.md S3/S4): the single-
# linkage merge below had no maximum cluster width and no cap on its
# bandwidth-scaled threshold, so it chains without bound at high event
# density -- a 20 143-event real capture collapsed into ONE 99.4 MHz-wide
# cluster. Two independent bounds fix this:
CLUSTER_MAX_MERGE_HZ = 1.0e6      # absolute cap on the per-pair merge
                                    # threshold (design doc S4: "~1 MHz"), so
                                    # one wide/mis-measured occupant's BW can
                                    # no longer make the bw-scaled threshold
                                    # (0.75 * BW) arbitrarily large.
CLUSTER_GRID_MERGE_CAP_HZ = 333e3  # C3b fix (docs/design/stage1-c4-c5-spec.md
                                    # C4(d)): with true (post-C4) burst
                                    # bandwidths of a few hundred kHz, a fixed
                                    # 1 MHz merge radius merges adjacent
                                    # channels of the very 1 MHz grid this
                                    # module tests for. Capped at
                                    # min(DEFAULT_DELTAS_HZ)/3 = 200 kHz's
                                    # sibling for the 1 MHz grid specifically
                                    # (1.0 MHz / 3): a merge radius under 1/3
                                    # of the smallest grid step under test
                                    # cannot, by construction, bridge one grid
                                    # step even in the worst case (two bursts
                                    # sitting right at the inner edges of
                                    # adjacent channels).
CLUSTER_MAX_SPAN_HZ = 5.0e6       # a cluster may not grow past this centre-
                                    # to-centre span regardless of how many
                                    # consecutive pairwise gaps stay under
                                    # threshold (= 2 * HOP_MAX_CLUSTER_BW_HZ,
                                    # defined below in the R4 section) -- this
                                    # is what stops the chain from running
                                    # across the whole band.

DEFAULT_DELTAS_HZ: tuple[float, ...] = (
    0.6e6, 1.0e6, 1.5e6, 2.0e6, 2.5e6, 5.0e6,
)
FREE_DELTA_RANGE_HZ = (0.3e6, 6.0e6)
FREE_DELTA_STEP_HZ = 10e3
# Number of independent Delta hypotheses scanned by the free-spacing coarse
# grid (design S2(b) fixes the family-wise threshold for the 6-entry
# dictionary only; the free search is an ADDITIONAL family of hypotheses and
# must carry its own Bonferroni/Sidak accounting -- see `_p_false_corrected`).
N_FREE_DELTA_TRIALS = int(round((FREE_DELTA_RANGE_HZ[1] - FREE_DELTA_RANGE_HZ[0]) / FREE_DELTA_STEP_HZ))

M_MIN_RASTER = 10          # design S2(b) operating point
R_MIN_RASTER = 0.93
SIGMA_F_DEBIAS_CAP = 1.15

ELRS_OFFSET_MOD_HZ = 0.4e6              # ELRS 2.4 centres == 0.400 MHz (mod 1.000 MHz)
ELRS_OFFSET_TOL_HZ = 100e3

# ExpressLRS firmware `interval` values (packet repetition period), PRIMARY
# per research/briefs/rc-link-raster-facts.md item 2 (src/include/common.h):
# 50/150/250/500/1000 Hz -> 20000/6667/4000/2000/1000 us.
ELRS_PERIODS_S: tuple[float, ...] = (0.020, 0.006667, 0.004, 0.002, 0.001)
FREE_PERIOD_RANGE_S = (0.5e-3, 1.0)
FREE_PERIOD_STEPS = 400          # log-spaced

N_MIN_PERIOD = 10
R_MIN_PERIOD = 0.93

# Independent review fix (2026-09-19, finding #3): a live detector's frame
# pitch (``frame_dt_s``, forwarded to ``period_test`` for the C1 sub-frame
# dt-filter) can itself be coarser than the fastest period this module
# models. If it exceeds half of ``min(periods_s)``, the filter can erase a
# genuinely fast, regular train wholesale (every true inter-arrival falls
# below ``min_dt``) rather than only removing degenerate co-temporal
# artefacts -- see ``period_test``'s docstring.
FRAME_PITCH_MAX_FRAC_OF_MIN_PERIOD = 0.5

# C1 fix (docs/design/stage1-rc-positives-2026-09-19.md S3/S4): a candidate
# period landing at/near the TOP of the free-search range cannot be told
# apart from "no bound on the period" -- for any bounded set of inter-burst
# intervals, the Rayleigh statistic trivially rises as the trial period grows
# towards the top of the search range (all phases 2*pi*dt/T -> 0), independent
# of whether real periodicity is present. Reject any winning candidate within
# one coarse free-search grid step of ``FREE_PERIOD_RANGE_S[1]`` as
# unidentifiable rather than reporting the range top as a period.
_FREE_PERIOD_GRID_STEP_RATIO = (
    (FREE_PERIOD_RANGE_S[1] / FREE_PERIOD_RANGE_S[0]) ** (1.0 / (FREE_PERIOD_STEPS - 1))
)
PERIOD_RANGE_TOP_REJECT_S = FREE_PERIOD_RANGE_S[1] / _FREE_PERIOD_GRID_STEP_RATIO

DURATION_BIN_EDGES_S = (0.4e-3, 1e-3, 3e-3, 10e-3)   # 5 bins: <0.4,0.4-1,1-3,3-10,>10 ms
DURATION_BIN_LABELS = ("lt_0.4ms", "0.4_1ms", "1_3ms", "3_10ms", "gt_10ms")

# R3 -- Wi-Fi beacon discount (asymmetric: contention only delays a beacon,
# never advances it -- research/briefs/rc-link-raster-facts.md item 5).
WIFI_BEACON_PERIOD_S = 0.1024
WIFI_BEACON_MAX_N = 5
WIFI_BEACON_MIN_R = 0.85                # absolute-phase Rayleigh concentration
WIFI_BEACON_MIN_BW_HZ = 16e6            # design S "R3": fixed >=16 MHz flat-top channel
WIFI_BEACON_MIN_N = 3

# R3 revision -- wideband (Wi-Fi-like) occupancy. In a 10 MHz usable dwell a
# 20 MHz Wi-Fi burst is ALWAYS frequency-edge-clipped, so it never reaches
# ``cluster_centres`` (which drops edge-clipped events) and the original
# ``WIFI_BEACON_MIN_BW_HZ = 16 MHz`` per-cluster beacon test could not fire by
# construction. The wideband stream is therefore analysed separately, on the
# RAW event list, where only timing (not centre) is trusted.
WIFI_WIDEBAND_MIN_BW_HZ = 8e6      # "wider than any RC/BLE channel we model"
WIFI_WIDEBAND_MIN_EVENTS = 3       # informational wifi_like_wideband tag floor
WIFI_WIDEBAND_GROUP_TOL_HZ = 3e6   # coarse grouping of clipped centres (their
                                    # centre estimate is dwell-edge-biased)
WIFI_BEACON_LATE_TOL_S = 8e-3      # asymmetric: CSMA/CA contention + TBTT
                                    # deferral only DELAYS a beacon
WIFI_BEACON_EARLY_TOL_S = 0.5e-3   # small symmetric allowance for timestamp
                                    # quantisation (200 us detector frames)
WIFI_BEACON_MIN_INTERVALS = 3      # >=3 qualifying intervals (task spec)
WIFI_BEACON_LATE_FRAC = 0.6        # ... and they must be the MAJORITY of the
                                    # group's intervals, else dense data
                                    # traffic trivially supplies 3 by chance

# R3 -- BLE connection discount (facts brief item 4: 7.5 ms-4 s, 1.25 ms steps).
BLE_CONN_MIN_S = 7.5e-3
BLE_CONN_MAX_S = 4.0
BLE_CONN_QUANT_S = 1.25e-3
BLE_CONN_QUANT_TOL_S = 0.15e-3
BLE_CONN_MAX_HOP_BW_HZ = 2.0e6
BLE_CONN_MIN_R = 0.9
BLE_CONN_MIN_N_CHANNELS = 20    # distinct-channel-count proxy for the 37-ch BLE
                                 # data-channel map (design S1's own channel-count
                                 # table caps any 0.6-5 MHz RC raster at <=17
                                 # channels per dwell); a per-channel MEDIAN-visit
                                 # count is NOT a valid BLE/RC discriminator -- it
                                 # scales with (events observed)/(channel count)
                                 # regardless of which system is transmitting, so a
                                 # long, busy BLE capture can legitimately revisit
                                 # every one of its 37 channels several times.

# R3 -- DroneID cadence candidate (design S4: session-level, 640 ms, 7-11 MHz flat-top).
DRONEID_PERIOD_S = 0.640
DRONEID_MIN_BW_HZ = 7e6
DRONEID_MAX_BW_HZ = 11e6
DRONEID_MIN_EVENTS = 5
DRONEID_MIN_SPAN_S = 3.0
DRONEID_MIN_R = 0.9

# R4 -- fixed vs hopping.
FIXED_STD_FRAC_OF_BW = 0.25
HOPPING_MIN_M_REPEAT = 5   # R4 revision 2026-09-19 (was 3). Ambient-corpus
                            # evidence: in a 10 MHz usable dwell, 3-4 reused
                            # narrow clusters is the SATURATED ambient state of
                            # a busy 2.4 GHz room (BLE data/advert traffic and
                            # LO-adjacent narrow blips at +/-1/+/-3 MHz), not
                            # evidence of a hop set. Raising the floor to 5
                            # asks the hop set to be wider than "a handful of
                            # adjacent channels", which is the same
                            # decidability argument design S1 makes for the
                            # raster test. A genuine narrow hopper that shows
                            # only 3-4 channels per dwell is recovered by
                            # multi-dwell accumulation (R1(e)), not by lowering
                            # this floor.
HOPPING_MIN_EVENTS = 6          # sample-size floor for a meaningful lag-1 autocorr
HOPPING_WHITENESS_MAX_ABS_AUTOCORR = 0.3
HOP_MAX_CLUSTER_BW_HZ = 2.5e6   # R4 revision: a hop channel must be NARROW
                                 # relative to the dwell. A cluster whose
                                 # median 6 dB bandwidth exceeds this is a
                                 # wideband occupant (Wi-Fi/OFDM), and its
                                 # -6 dB "centre" is a shape estimate, not a
                                 # channel; such clusters are excluded from
                                 # the hop-set count entirely (they can still
                                 # carry fixed_channel_burst_candidate).
HOPPING_MIN_REUSE_RATIO = 2.0   # events/cluster: guards against coincidental noise
                                # clusters (birthday-paradox collisions) satisfying
                                # M_repeat>=3 with no real channel reuse structure.
                                # Empirically (module test fixtures): genuine hoppers
                                # measure 2.3-5.0 events/cluster (ELRS 250 Hz/1 s 3.2,
                                # ELRS 50 Hz/3 s 2.3, DJI-like 2 MHz single dwell 5.0);
                                # 80 fully-random (uniform centre+time) bursts across an
                                # 80 MHz band -- pure noise, no channel structure at all
                                # -- land at ~1.5-2.05 purely from the bandwidth-scaled
                                # cluster-separation floor coincidentally merging nearby
                                # random points (not genuine reuse). 1.5 sat inside that
                                # noise band and let a random draw through; 2.0 sits
                                # below every measured genuine-hopper ratio while
                                # rejecting the noise fixture. This is a level-1
                                # morphology gate, not a formal p-value -- design S9
                                # explicitly budgets `hopping_candidate` an allowed
                                # <=5% false-alarm rate at level 1, so this threshold is
                                # a pragmatic separator, not a guarantee against every
                                # possible random draw.

# R5 controlled label/tag vocabulary (no vendor tokens; see module docstring).
LABEL_VOCAB = frozenset({
    "fhss_1mhz_grid_candidate",
    "fhss_2mhz_grid_candidate",
    "rc_link_family_candidate",
    "hopping_candidate",
    "fixed_channel_burst_candidate",
    "droneid_cadence_candidate",
})
TAG_VOCAB = frozenset({"wifi_beacon_like", "ble_connection_like", "wifi_like_wideband",
                       "INSUFFICIENT_CHANNELS"})


# --------------------------------------------------------------------------
# Shared statistics
# --------------------------------------------------------------------------

def _rayleigh_stat(values: np.ndarray, period: float) -> tuple[float, float]:
    """Rayleigh concentration ``R = |mean(exp(j*2*pi*v/period))|`` and the
    circular-mean offset (mod ``period``). Level 1 statistic only -- ``R``
    close to 1 says "these values sit on a period/period-multiple lattice",
    nothing about what emits it."""
    theta = 2.0 * np.pi * np.asarray(values, dtype=np.float64) / period
    z = np.mean(np.exp(1j * theta))
    r = float(np.abs(z))
    offset = float((np.angle(z) * period / (2.0 * np.pi)) % period)
    return r, offset


def _p_false(n: int, r: float) -> float:
    """Uniform-null false-match probability approximation (design S2(b))."""
    return float(np.exp(-n * r * r))


def _p_false_corrected(n: int, r: float, n_trials: int) -> float:
    """Bonferroni-corrected false-match probability: the winning R was
    selected as the best of ``n_trials`` scanned Delta hypotheses (the fixed
    dictionary AND the free-spacing grid both contribute candidates to
    ``results`` in ``raster_test`` before a winner is picked), so the
    single-hypothesis formula in ``_p_false`` understates the true false-
    alarm rate of "the best of many" by roughly a factor of ``n_trials``
    (design S0: "false-match probability is an explicit number" -- that
    number must reflect the actual search, not one hypothesis in isolation).
    """
    return float(min(1.0, n_trials * _p_false(n, r)))


def _scan(values: np.ndarray, lo: float, hi: float, n_steps: int, log_spaced: bool) -> tuple[float, float]:
    if hi <= lo:
        r, _ = _rayleigh_stat(values, lo)
        return lo, r
    grid = np.geomspace(lo, hi, n_steps) if log_spaced else np.linspace(lo, hi, n_steps)
    best_r, best_p = -1.0, float(grid[0])
    for p in grid:
        r, _ = _rayleigh_stat(values, float(p))
        if r > best_r:
            best_r, best_p = r, float(p)
    return best_p, best_r


def _free_search(values: np.ndarray, lo: float, hi: float, n_steps: int,
                  log_spaced: bool) -> float:
    """Coarse grid search over a candidate period/spacing, then two rounds
    of local zoom (+/-5% of the running best, 200-point linear grid) so a
    period that does not land on the coarse grid (e.g. a 30 ms BLE
    connection interval against a log-spaced 0.5 ms-1 s search) is still
    resolved to enough precision for the Rayleigh statistic to concentrate."""
    p, r = _scan(values, lo, hi, n_steps, log_spaced)
    for _ in range(3):
        span = max(p * 0.05, 1e-9)
        p2, r2 = _scan(values, max(lo, p - span), min(hi, p + span), 200, False)
        if r2 >= r:
            p, r = p2, r2
        else:
            break
    return p


# --------------------------------------------------------------------------
# (1) Clustering
# --------------------------------------------------------------------------

@dataclass
class Cluster:
    """One frequency-channel cluster (level 1: a set of bursts whose -6 dB
    edge-midpoint centres sit close together in absolute Hz)."""
    centre_hz: float
    std_hz: float
    bw_hz: float                  # median 6 dB bandwidth of member events
    events: list[BurstEvent] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.events)


def cluster_centres(events: list[BurstEvent], tol_hz: float = DEFAULT_CLUSTER_TOL_HZ,
                     bw_separation_frac: float = CLUSTER_BW_SEPARATION_FRAC,
                     max_merge_hz: float | None = None,
                     max_cluster_span_hz: float = CLUSTER_MAX_SPAN_HZ) -> list[Cluster]:
    """Level 1. Group non-``edge_clipped`` bursts into frequency clusters.

    Sequential (sorted-by-centre) agglomeration: consecutive events merge
    into the same cluster while the gap to the running cluster is below
    ``max(tol_hz, bw_separation_frac * max(BW_i, BW_j))`` (design S2(a)) --
    the bandwidth-scaled floor stops one wide, shape-varying emitter's -6 dB
    edge jitter from being split into a fake multi-channel hop set. Events
    with ``edge_clipped`` set are excluded (their centre estimate is
    dwell-edge-biased, not a real channel estimate).

    C3 fix (docs/design/stage1-rc-positives-2026-09-19.md S3/S4): unbounded
    single-linkage chaining. Two independent bounds are applied on top of the
    original merge rule, without changing it otherwise:
      * the per-pair merge threshold is capped at ``max_merge_hz`` (a single
        wide/mis-measured occupant's bandwidth can no longer make
        ``bw_separation_frac * BW`` arbitrarily large);
      * a cluster may not grow past ``max_cluster_span_hz`` measured from its
        first (lowest-centre) member to the candidate next event, regardless
        of how many consecutive pairwise gaps stay under threshold -- this is
        what stops a dense event stream from chaining across the whole band.

    Independent review fix (2026-09-19, finding #1): a FIXED
    ``max_merge_hz = CLUSTER_MAX_MERGE_HZ`` (1 MHz) overrode the
    bandwidth-scaled floor (``bw_separation_frac * BW``) for any occupant
    wider than ~1.33 MHz, so a genuine wideband burst (e.g. 2.4 MHz) sampled
    by only 2-3 -6 dB centre estimates near its edges (gap ~2.2 MHz) was
    split into separate clusters -- a spurious multi-cluster "hop set" from
    ONE emitter. The cap is now scaled up to (at most) the widest occupant
    this module still treats as a single hop channel
    (``HOP_MAX_CLUSTER_BW_HZ``), so a real single-emitter's -6 dB edge
    jitter no longer exceeds the merge threshold; ``max_cluster_span_hz`` is
    unchanged and remains the only thing that stops unbounded chaining
    (C3, above).
    """
    if max_merge_hz is None:
        # Equivalent to ``max(CLUSTER_MAX_MERGE_HZ, bw_separation_frac *
        # min(BW, HOP_MAX_CLUSTER_BW_HZ))``: for BW < HOP_MAX_CLUSTER_BW_HZ
        # the outer ``min(max_merge_hz, bw_separation_frac * BW)`` below
        # already yields the smaller, per-pair-scaled value, so a constant
        # ceiling computed once here (rather than re-derived per pair) gives
        # the same result.
        max_merge_hz = max(CLUSTER_MAX_MERGE_HZ, bw_separation_frac * HOP_MAX_CLUSTER_BW_HZ)
    usable = sorted((e for e in events if not e.edge_clipped), key=lambda e: e.centre_hz)
    clusters: list[Cluster] = []
    current: list[BurstEvent] = []
    for e in usable:
        if current:
            gap = e.centre_hz - current[-1].centre_hz
            pair_bw = max(current[-1].bw_6db_hz, e.bw_6db_hz)
            # C3b (docs/design/stage1-c4-c5-spec.md C4(d)): a NARROW pair
            # (candidate hop-channel bursts, the case the grid test actually
            # runs on) additionally never merges past 1/3 of the smallest
            # channel grid under test (``CLUSTER_GRID_MERGE_CAP_HZ``) -- with
            # true (post-C4) burst bandwidths of a few hundred kHz, the old
            # fixed 1 MHz cap merged adjacent channels of the very 1 MHz grid
            # being tested for.
            #
            # "Narrow" here means ``pair_bw <= min(DEFAULT_DELTAS_HZ)``, NOT
            # ``<= HOP_MAX_CLUSTER_BW_HZ`` (2.5 MHz). A burst WIDER than the
            # smallest grid step under test cannot be a channel on that grid
            # at all, so the anti-grid-bridging cap has no purpose for it,
            # while applying it anyway re-broke the independent-review fix
            # below: one 2.4 MHz emitter sampled by 2-3 -6 dB centre
            # estimates ~1.1 MHz apart was split into a spurious
            # multi-cluster "hop set". With this split point both
            # requirements hold simultaneously, and no time-overlap test is
            # needed (the sparse samples of one emitter are NOT co-temporal,
            # so a co-temporality rule would not have separated the cases):
            #   * 2.4 MHz pair, 1.1 MHz gap -> cap 1.875 MHz, thresh
            #     0.75*2.4 = 1.8 MHz > 1.1 MHz  -> merges (one emitter);
            #   * 0.3 MHz pair, 1.0 MHz gap  -> cap 333 kHz, thresh
            #     max(tol, 0.225) = 0.1-0.225 MHz < 1.0 MHz -> stays split
            #     (two channels of the 1 MHz grid).
            grid_relevant = pair_bw <= min(DEFAULT_DELTAS_HZ)
            pair_cap = CLUSTER_GRID_MERGE_CAP_HZ if grid_relevant else max_merge_hz
            thresh = min(pair_cap, max(tol_hz, bw_separation_frac * pair_bw))
            span = e.centre_hz - current[0].centre_hz
            if gap > thresh or span > max_cluster_span_hz:
                clusters.append(_make_cluster(current))
                current = []
        current.append(e)
    if current:
        clusters.append(_make_cluster(current))
    return clusters


def _make_cluster(evs: list[BurstEvent]) -> Cluster:
    centres = np.array([e.centre_hz for e in evs], dtype=np.float64)
    bws = np.array([e.bw_6db_hz for e in evs], dtype=np.float64)
    return Cluster(
        centre_hz=float(centres.mean()),
        std_hz=float(centres.std()),
        bw_hz=float(np.median(bws)),
        events=list(evs),
    )


def _repeat_clusters(clusters: list[Cluster]) -> list[Cluster]:
    """Clusters attested by >=2 bursts (design S2(a): "M = clusters holding
    >=2 bursts"). A single-visit centre is not distinguishable from a
    one-off, uncorrelated emission and must not inflate M for any lattice
    or hopping test."""
    return [c for c in clusters if c.n >= 2]


# --------------------------------------------------------------------------
# (2) R1 -- hop-raster (frequency lattice) test
# --------------------------------------------------------------------------

@dataclass
class RasterEvidence:
    """Level 1-2 structured evidence for the frequency-lattice test (R1).
    A populated ``delta_hz`` with ``rayleigh_r >= R_MIN_RASTER`` and
    ``n_channels >= M_MIN_RASTER`` is the only basis for a level-2 grid
    label; anything else is morphology only."""
    delta_hz: float | None
    offset_hz: float | None
    n_channels: int
    rayleigh_r: float
    rayleigh_r_debiased: float
    p_false: float
    sigma_f_hz: float
    aliases_hz: list[float]
    insufficient: bool
    source: str            # "fixed_grid" | "free_search" | "none"


def raster_test(clusters: list[Cluster], deltas_hz: tuple[float, ...] = DEFAULT_DELTAS_HZ,
                 m_min: int = M_MIN_RASTER, r_min: float = R_MIN_RASTER) -> RasterEvidence:
    """R1(b)-(d): Rayleigh lattice test over cluster centres at each
    candidate spacing plus one free-spacing search; largest PASSING spacing
    is reported, smaller passing integer submultiples go in ``aliases_hz``
    (R1(c)) rather than as separate detections. Level 1-2: only a pass
    (``n_channels >= m_min`` and ``rayleigh_r >= r_min``) supports a level-2
    grid label; a fail or ``insufficient`` result is not evidence of absence
    (few in-band hops observed is the common cause -- see design S1).

    ``n_channels`` (M) is the number of DISTINCT channel clusters observed
    (>=1 burst each), not clusters revisited >=2 times: design S1's own
    coupon-collector decidability numbers ("2.3 s at 50 Hz ... for 8 distinct
    of 10 channels") are about distinct-channel coverage, and a channel
    visited exactly once still sits on the true grid and is valid lattice
    evidence -- requiring a revisit here would make slow links permanently
    undecidable rather than decidable-with-more-dwell-time. The >=2-visit
    "repeat" cluster set is reserved for R4's hopping-vs-noise gate, which
    specifically needs genuine channel reuse to rule out coincidental
    one-off centres (see ``fixed_vs_hopping``)."""
    m = len(clusters)
    repeat = _repeat_clusters(clusters)
    sigma_f = float(np.sqrt(np.mean([c.std_hz ** 2 for c in repeat]))) if repeat else 0.0

    if m < m_min:
        return RasterEvidence(None, None, m, 0.0, 0.0, 1.0, sigma_f, [], True, "none")

    centres = np.array([c.centre_hz for c in clusters], dtype=np.float64)
    results: dict[float, tuple[float, float]] = {}
    for d in deltas_hz:
        results[d] = _rayleigh_stat(centres, d)
    free_d = _free_search(centres, FREE_DELTA_RANGE_HZ[0], FREE_DELTA_RANGE_HZ[1],
                           int((FREE_DELTA_RANGE_HZ[1] - FREE_DELTA_RANGE_HZ[0]) / FREE_DELTA_STEP_HZ),
                           log_spaced=False)
    if free_d not in results:
        results[free_d] = _rayleigh_stat(centres, free_d)

    n_trials = len(deltas_hz) + N_FREE_DELTA_TRIALS

    passing = [(d, r, off) for d, (r, off) in results.items() if r >= r_min]
    if not passing:
        best_d = max(results, key=lambda d: results[d][0])
        r_best, off_best = results[best_d]
        return RasterEvidence(None, None, m, r_best, r_best,
                               _p_false_corrected(m, r_best, n_trials), sigma_f,
                               [], False, "none")

    passing.sort(key=lambda t: t[0], reverse=True)
    d_hat, r, off = passing[0]
    aliases = [d for d, _, _ in passing[1:]
               if abs(round(d_hat / d) - d_hat / d) < 1e-6 and round(d_hat / d) >= 2]

    debias_raw = np.exp(-2.0 * np.pi ** 2 * sigma_f ** 2 / d_hat ** 2)
    debias_factor = min(SIGMA_F_DEBIAS_CAP, 1.0 / debias_raw) if debias_raw > 0 else SIGMA_F_DEBIAS_CAP
    r_debiased = min(1.0, r * debias_factor)
    source = "fixed_grid" if d_hat in deltas_hz else "free_search"

    return RasterEvidence(d_hat, off, m, r, r_debiased,
                           _p_false_corrected(m, r, n_trials), sigma_f,
                           aliases, False, source)


def _elrs_offset_consistent(offset_hz: float, delta_hz: float) -> bool:
    diff = abs(offset_hz - ELRS_OFFSET_MOD_HZ)
    diff = min(diff, abs(delta_hz - diff))
    return diff <= ELRS_OFFSET_TOL_HZ


# --------------------------------------------------------------------------
# (3) R2 -- hop-period (time lattice) test + duration histogram
# --------------------------------------------------------------------------

@dataclass
class PeriodEvidence:
    """Level 1-2 structured evidence for the inter-burst period test (R2).
    ``t_hat_s``/``rayleigh_r`` are always reported (best candidate found);
    only ``passed`` gates any label/tag use of them."""
    t_hat_s: float | None
    rayleigh_r: float
    p_false: float
    n_intervals: int
    passed: bool
    duration_hist: dict[str, int]
    duration_mode: str | None
    source: str            # "elrs_set" | "free_search" | "none" | "range_top_rejected"
                            # | "frame_pitch_too_coarse"


def _duration_histogram(durations_s: list[float]) -> dict[str, int]:
    hist = {label: 0 for label in DURATION_BIN_LABELS}
    for d in durations_s:
        idx = int(np.searchsorted(DURATION_BIN_EDGES_S, d, side="right"))
        hist[DURATION_BIN_LABELS[idx]] += 1
    return hist


def period_test(clusters: list[Cluster], periods_s: tuple[float, ...] = ELRS_PERIODS_S,
                 n_min: int = N_MIN_PERIOD, r_min: float = R_MIN_PERIOD,
                 frame_dt_s: float | None = None) -> PeriodEvidence:
    """R2: inter-burst intervals of the pooled channel-cluster set (every
    non-edge-clipped burst across all clusters, time-sorted -- deliberately
    NOT filtered to >=2-visit clusters, so a periodic link that revisits
    almost no individual channel, e.g. BLE, is still testable) are
    near-integer multiples of a packet period T -- span-free, works even
    though most hops land out of band (design S3).

    ``frame_dt_s``, when known (the live detector's frame pitch), is used to
    drop degenerate near-zero intervals before the Rayleigh scan (C1 fix,
    docs/design/stage1-rc-positives-2026-09-19.md S3/S4): bursts that are
    co-temporal but at different centre frequencies are adjacent in this
    pooled, time-sorted list and produce ``dt`` at or near 0. If
    ``frame_dt_s`` is not given, the minimum observed positive event
    duration is used instead (a burst cannot be shorter than one frame by
    construction of ``bursts.py``).

    Estimator (rewritten 2026-09-19, see the same design-doc addendum): the
    previous version scanned a dictionary of candidate periods (the
    ExpressLRS firmware set, the empirical median, and a log-spaced free
    search) and reported the LARGEST candidate whose Rayleigh statistic
    cleared ``r_min``. That alias rule is unsound for ANY sufficiently
    regular ``dt`` set, not just the degenerate dt~=0 case the dt-filter
    above targets: identical (or near-identical, low-jitter) intervals give
    Rayleigh R ~= 1 at EVERY trial period T, because the phase
    ``2*pi*dt/T`` is the same for every interval regardless of T (a single
    repeated complex unit vector has magnitude 1 irrespective of the
    divisor tested). "Largest passing" therefore silently picked the
    largest set member (or free-search point) that happened to clear
    ``r_min``, e.g. reporting 20 ms for a genuinely period-8-ms train just
    because 20 ms was also a "passing" alias and is bigger.

    The fix is to estimate the fundamental FIRST, directly from the data --
    ``t_hat_0 = median(dt)`` -- and gate pass/fail on the Rayleigh
    statistic AT THAT ESTIMATE, not on whichever dictionary entry has the
    numerically largest period. A declared ExpressLRS period is reported
    (``source="elrs_set"``) only when a member of ``periods_s`` actually
    lies within 5% of ``t_hat_0``; otherwise the data-anchored estimate
    itself is reported (``source="free_search"``). An estimate at/near the
    top of ``FREE_PERIOD_RANGE_S`` is not identifiable from an observation
    this short and is rejected (``source="range_top_rejected"``) rather than
    reported as a period.

    Independent review fix (2026-09-19, finding #3): ``frame_dt_s`` gates the
    sub-frame dt-filter above, but if it is itself coarser than
    ``FRAME_PITCH_MAX_FRAC_OF_MIN_PERIOD`` (0.5) of the smallest modelled
    period (``min(periods_s)``), the filter's own quantisation is no longer
    fine enough to trust: it can as easily erase a genuinely fast, regular
    train (e.g. a 4 ms cadence sampled at a 5 ms frame pitch has NO surviving
    ``dt``, since every true inter-arrival is below ``min_dt``) as clean up a
    real degenerate-zero artefact. The filter is still applied (removing it
    would reopen the dt~=0 co-temporal-train failure C1 fixed), but any
    result computed under this condition is marked ``source=
    "frame_pitch_too_coarse"`` with ``passed=False`` rather than reported at
    face value, on every return path below."""
    # Pooled across ALL clusters (not filtered to >=2-visit "repeat" clusters):
    # unlike the frequency-lattice test (R1, which needs revisited channels to
    # even define a cluster centre distribution), the *time* periodicity of a
    # link can be genuine even when almost every hop lands on a channel it
    # never revisits (e.g. BLE connection events, each on a fresh 2 MHz data
    # channel) -- filtering those out here would blind the BLE discriminator.
    frame_pitch_too_coarse = bool(
        frame_dt_s is not None and frame_dt_s > 0.0 and len(periods_s) > 0
        and frame_dt_s > FRAME_PITCH_MAX_FRAC_OF_MIN_PERIOD * min(periods_s)
    )

    def _coarse_source(default: str) -> str:
        return "frame_pitch_too_coarse" if frame_pitch_too_coarse else default

    events = sorted((e for c in clusters for e in c.events), key=lambda e: e.t_start)
    hist = _duration_histogram([e.duration_s for e in events])
    mode = max(hist, key=lambda k: hist[k]) if events else None

    if len(events) < 2:
        return PeriodEvidence(None, 0.0, 1.0, 0, False, hist, mode, _coarse_source("none"))

    t = np.array([e.t_start for e in events], dtype=np.float64)
    dt_all = np.diff(t)

    # C1 fix (a)/(d): drop degenerate near-zero intervals below one frame
    # period before doing any Rayleigh scan -- see the docstring above.
    if frame_dt_s is not None and frame_dt_s > 0.0:
        min_dt = float(frame_dt_s)
    else:
        durations = np.array([e.duration_s for e in events], dtype=np.float64)
        positive_durations = durations[durations > 0.0]
        min_dt = float(positive_durations.min()) if positive_durations.size else 1e-9
    dt = dt_all[dt_all >= min_dt]
    n = int(len(dt))

    # The minimum-interval-count gate applies AFTER the dt filter --
    # surviving (non-degenerate) intervals are what the Rayleigh statistic
    # is actually computed over.
    if n < n_min:
        return PeriodEvidence(None, 0.0, 1.0, n, False, hist, mode, _coarse_source("none"))

    # (a) Estimate the fundamental FIRST, directly from the (frame-filtered)
    # data -- the data-anchored median inter-arrival, not a dictionary/grid
    # search. All surviving dt are > 0 (filtered by min_dt > 0 above), so
    # the median is always a strictly positive, well-defined period
    # candidate.
    t_hat_0 = float(np.median(dt))

    # C1 fix (d): a candidate at/near the top of the free-search range
    # cannot be told apart from "no bound on the period" from an
    # observation this short -- reject rather than report it.
    if t_hat_0 >= PERIOD_RANGE_TOP_REJECT_S:
        r0, _ = _rayleigh_stat(dt, t_hat_0)
        return PeriodEvidence(None, r0, _p_false(n, r0), n, False, hist, mode,
                               _coarse_source("range_top_rejected"))

    # (b) Compute R AT t_hat_0 and require IT (not some other dictionary
    # entry) to pass.
    r0, _ = _rayleigh_stat(dt, t_hat_0)
    passed = r0 >= r_min

    # (c) Only label the estimate as a declared ExpressLRS period if a set
    # member actually lies within 5% of t_hat_0 (report that member's exact
    # value as t_hat_s); otherwise report the data-anchored estimate itself.
    # (Cosmetic fix, independent review 2026-09-19 #4: a separate
    # ``p <= 1.5 * t_hat_0`` bound was previously ANDed in here but is
    # unreachable -- the 5% tolerance above already forces
    # ``p <= 1.05 * t_hat_0``, strictly inside 1.5x, so the extra guard
    # could never reject anything. Removed rather than kept as dead code.)
    best_t = t_hat_0
    best_r = r0
    source = "free_search"
    candidates = [p for p in periods_s if abs(p - t_hat_0) <= 0.05 * t_hat_0]
    if candidates:
        best_t = min(candidates, key=lambda p: abs(p - t_hat_0))
        best_r, _ = _rayleigh_stat(dt, best_t)
        source = "elrs_set"

    if frame_pitch_too_coarse:
        # See the docstring note above: the dt-filter itself is untrustworthy
        # at this frame pitch, so the estimate is reported as unidentifiable
        # (same treatment as "range_top_rejected") rather than at face value.
        return PeriodEvidence(None, best_r, _p_false(n, best_r), n, False, hist, mode,
                               "frame_pitch_too_coarse")

    return PeriodEvidence(best_t, best_r, _p_false(n, best_r), n, passed, hist, mode, source)


# --------------------------------------------------------------------------
# (4) R3 -- non-UAS cadence discount / DroneID cadence recognition
# --------------------------------------------------------------------------

@dataclass
class CadenceTag:
    cluster_index: int
    tag: str
    t_hat_s: float
    rayleigh_r: float
    n: int


def _wifi_beacon_like(cluster: Cluster) -> CadenceTag | None:
    """Tested on ABSOLUTE burst timestamps (mod period), not consecutive
    intervals: independent per-beacon contention delay (facts brief #5)
    makes consecutive *intervals* noisier than the underlying schedule
    (two independent delays combine per interval), while each timestamp's
    phase relative to the 102.4 ms x n lattice stays tightly, one-sidedly
    concentrated. No quantitative late-side jitter percentile table exists
    yet (facts brief open follow-up), so the tolerance is the same
    concentration threshold as the other cadence tests rather than a
    direction-aware band; this is flagged as a design simplification."""
    if cluster.bw_hz < WIFI_BEACON_MIN_BW_HZ:
        return None
    t = np.array(sorted(e.t_start for e in cluster.events))
    if len(t) < WIFI_BEACON_MIN_N:
        return None
    for n_mult in range(1, WIFI_BEACON_MAX_N + 1):
        period = WIFI_BEACON_PERIOD_S * n_mult
        r, _ = _rayleigh_stat(t, period)
        if r >= WIFI_BEACON_MIN_R:
            return CadenceTag(-1, "wifi_beacon_like", period, r, len(t))
    return None


def _wideband_events(events: list[BurstEvent]) -> list[BurstEvent]:
    """Events too wide to be any channel this module models (Wi-Fi/OFDM
    occupants). Includes frequency-edge-clipped events: in a 10 MHz usable
    dwell a 20 MHz Wi-Fi burst is clipped by construction, and its measured
    ``bw_6db_hz`` is a lower bound (the dwell width), not the true bandwidth."""
    return [e for e in events
            if e.bw_6db_hz >= WIFI_WIDEBAND_MIN_BW_HZ or e.edge_clipped]


def _wideband_groups(events: list[BurstEvent]) -> list[list[BurstEvent]]:
    """Coarse centre grouping of the wideband stream. Clipped centres are
    dwell-edge-biased, so the tolerance is deliberately wide (a single AP's
    bursts in one dwell all land in one group); this is a timing-analysis
    grouping, NOT a channel estimate."""
    out: list[list[BurstEvent]] = []
    cur: list[BurstEvent] = []
    for e in sorted(events, key=lambda e: e.centre_hz):
        if cur and e.centre_hz - cur[-1].centre_hz > WIFI_WIDEBAND_GROUP_TOL_HZ:
            out.append(cur)
            cur = []
        cur.append(e)
    if cur:
        out.append(cur)
    return out


def _wifi_beacon_like_wideband(events: list[BurstEvent]) -> CadenceTag | None:
    """R3 revision: per-group INTERVAL analysis with a one-sided (late-only)
    tolerance, on the wideband stream.

    A beacon-only AP emits a ~1 ms burst every 102.4 ms (or a small integer
    multiple, when TBTTs are missed); CSMA/CA contention and TBTT deferral can
    only push a beacon LATE, never early (research/briefs/
    rc-link-raster-facts.md item 5). So an interval between two consecutive
    bursts of the same AP is ``n * 102.4 ms + delay``, ``delay >= 0``. Testing
    the intervals directly (rather than the Rayleigh phase of absolute
    timestamps) is what makes the asymmetry expressible.

    Requires ``WIFI_BEACON_MIN_INTERVALS`` qualifying intervals AND that they
    are the majority (``WIFI_BEACON_LATE_FRAC``) of the group's intervals:
    in a busy room an AP's beacons are interleaved with data/ACK traffic, so
    three qualifying intervals alone are easy to obtain by chance. This tag is
    a DISCOUNT (level: non-UAS cadence explanation), never a detection, and a
    busy-room miss is expected and acceptable."""
    for group in _wideband_groups(events):
        t = np.array(sorted(e.t_start for e in group), dtype=np.float64)
        if len(t) < WIFI_BEACON_MIN_INTERVALS + 1:
            continue
        dt = np.diff(t)
        n_mult = np.round(dt / WIFI_BEACON_PERIOD_S)
        resid = dt - n_mult * WIFI_BEACON_PERIOD_S
        ok = ((n_mult >= 1) & (n_mult <= WIFI_BEACON_MAX_N)
              & (resid >= -WIFI_BEACON_EARLY_TOL_S) & (resid <= WIFI_BEACON_LATE_TOL_S))
        n_ok = int(np.count_nonzero(ok))
        if n_ok >= WIFI_BEACON_MIN_INTERVALS and n_ok >= WIFI_BEACON_LATE_FRAC * len(dt):
            return CadenceTag(-1, "wifi_beacon_like", WIFI_BEACON_PERIOD_S,
                              float(n_ok) / len(dt), len(t))
    return None


def _ble_connection_like(clusters: list[Cluster], period_ev: PeriodEvidence) -> CadenceTag | None:
    """Global test (design S3 "BLE discriminator"): the connection-interval
    periodicity survives even though each connection event lands on a
    different 2 MHz data channel, so this is evaluated on R2's pooled
    period estimate, not a single cluster. The "one burst per period" cadence
    itself is already enforced by requiring a high-R (``BLE_CONN_MIN_R``)
    concentration of R2's pooled inter-burst intervals -- if more than one
    burst occurred per connection event, the pooled dt sequence would mix a
    short intra-event gap with the full-period gap and could not concentrate
    this tightly. Channel breadth uses the DISTINCT-cluster count
    (``BLE_CONN_MIN_N_CHANNELS``), not a per-channel revisit statistic: the
    37-channel BLE data-channel map is far wider than any RC raster's
    per-dwell channel count in design S1's table (<=17 for the narrowest,
    0.6 MHz grid). A per-channel MEDIAN visit count is not usable here -- it
    scales with (events observed)/(channels used) for ANY hopper, BLE
    included, so a long capture legitimately revisits every BLE channel
    several times. Per-hop bandwidth uses the same all-clusters view."""
    if not clusters or period_ev.t_hat_s is None:
        return None
    if period_ev.source == "elrs_set":
        # The winning period is an exact match to a declared ExpressLRS
        # firmware rate; some of those (e.g. 20 ms = 16 x 1.25 ms) are
        # numerically also on the BLE 1.25 ms lattice by coincidence. A
        # known, declared RC period explanation takes priority over an
        # incidental BLE alias.
        return None
    t_hat = period_ev.t_hat_s
    if not (BLE_CONN_MIN_S <= t_hat <= BLE_CONN_MAX_S):
        return None
    quant_residual = abs(t_hat - BLE_CONN_QUANT_S * round(t_hat / BLE_CONN_QUANT_S))
    if quant_residual > BLE_CONN_QUANT_TOL_S:
        return None
    if any(c.bw_hz > BLE_CONN_MAX_HOP_BW_HZ for c in clusters):
        return None
    if len(clusters) < BLE_CONN_MIN_N_CHANNELS:
        return None
    if period_ev.rayleigh_r < BLE_CONN_MIN_R:
        return None
    return CadenceTag(-1, "ble_connection_like", t_hat, period_ev.rayleigh_r, period_ev.n_intervals)


def _droneid_cadence_candidate(cluster: Cluster, idx: int) -> CadenceTag | None:
    """Session-level (design S4): >=5 bursts spanning >=3 s on a 7-11 MHz
    flat-top channel, crystal-locked 640 ms cadence. Tested on absolute
    timestamps (same rationale as ``_wifi_beacon_like``): a high-Q
    (``DRONEID_MIN_R``) concentration is what separates a crystal-locked
    link from jittery non-UAS cadences."""
    if not (DRONEID_MIN_BW_HZ <= cluster.bw_hz <= DRONEID_MAX_BW_HZ):
        return None
    t = sorted(e.t_start for e in cluster.events)
    if len(t) < DRONEID_MIN_EVENTS or (t[-1] - t[0]) < DRONEID_MIN_SPAN_S:
        return None
    r, _ = _rayleigh_stat(np.array(t), DRONEID_PERIOD_S)
    if r < DRONEID_MIN_R:
        return None
    return CadenceTag(idx, "droneid_cadence_candidate", DRONEID_PERIOD_S, r, len(t))


def cadence_discount(clusters: list[Cluster], period_ev: PeriodEvidence,
                     events: list[BurstEvent] | None = None) -> list[CadenceTag]:
    """R3: per-cluster Wi-Fi-beacon / DroneID cadence checks, the wideband
    (clipped-inclusive) Wi-Fi beacon check, plus the global BLE-connection
    check. ``events`` is the RAW event list (pre-clustering); pass it so the
    wideband stream -- which ``cluster_centres`` deliberately drops -- is still
    analysable. Returns every tag that fired."""
    tags: list[CadenceTag] = []
    for i, c in enumerate(clusters):
        wifi = _wifi_beacon_like(c)
        if wifi is not None:
            wifi.cluster_index = i
            tags.append(wifi)
        drone = _droneid_cadence_candidate(c, i)
        if drone is not None:
            tags.append(drone)
    if events and not any(t.tag == "wifi_beacon_like" for t in tags):
        wb = _wifi_beacon_like_wideband(events)
        if wb is not None:
            tags.append(wb)
    ble = _ble_connection_like(clusters, period_ev)
    if ble is not None:
        tags.append(ble)
    return tags


# --------------------------------------------------------------------------
# (5) R4 -- fixed-channel vs hopping
# --------------------------------------------------------------------------

def fixed_vs_hopping(clusters: list[Cluster]) -> str | None:
    """R4 (level 1 only): replaces the old max-min "hop spread" heuristic.
    ``fixed_channel_burst_candidate`` requires exactly one cluster with a
    centre spread well inside its own bandwidth; ``hopping_candidate``
    requires >= ``HOPPING_MIN_M_REPEAT`` well-attested (>=2-burst) NARROW
    (<= ``HOP_MAX_CLUSTER_BW_HZ``) channel clusters, a minimum
    events/cluster reuse ratio (rules out coincidental one-off centres that
    happen to collide within the cluster tolerance -- see
    ``HOPPING_MIN_REUSE_RATIO``), AND a near-white (non-drifting) lag-1
    autocorrelation of the time-ordered centre sequence -- a monotone/
    drifting centre is AGC/AFC/thermal drift on ONE emitter, not
    multi-channel use. Returns ``None`` (no label) if no condition is met
    (``unknown_channel_structure`` is not in the T2 controlled vocabulary)."""
    if len(clusters) == 1:
        c = clusters[0]
        if c.bw_hz > 0 and c.std_hz < FIXED_STD_FRAC_OF_BW * c.bw_hz:
            return "fixed_channel_burst_candidate"
        return None

    # R4 revision 2026-09-19: the hop set is counted over NARROW clusters only
    # (``HOP_MAX_CLUSTER_BW_HZ``). A wideband occupant's -6 dB edge midpoint
    # moves with its modulation/shape, so several such "centres" are one
    # emitter's shape jitter, not several channels; and in a dwell narrower
    # than the occupant the centre is dwell-edge-biased anyway (those events
    # are already dropped as ``edge_clipped`` in ``cluster_centres``).
    narrow = [c for c in clusters if c.bw_hz <= HOP_MAX_CLUSTER_BW_HZ]
    repeat = _repeat_clusters(narrow)
    all_events = sorted((e for c in narrow for e in c.events), key=lambda e: e.t_start)
    reuse_ratio = len(all_events) / len(narrow) if narrow else 0.0
    if (len(repeat) >= HOPPING_MIN_M_REPEAT and len(all_events) >= HOPPING_MIN_EVENTS
            and reuse_ratio >= HOPPING_MIN_REUSE_RATIO):
        centres = np.array([e.centre_hz for e in all_events], dtype=np.float64)
        centres = centres - centres.mean()
        denom = float(np.sum(centres ** 2))
        if denom > 0:
            lag1 = float(np.sum(centres[:-1] * centres[1:]) / denom)
            if abs(lag1) < HOPPING_WHITENESS_MAX_ABS_AUTOCORR:
                return "hopping_candidate"
    return None


# --------------------------------------------------------------------------
# (6) R5 -- combined output
# --------------------------------------------------------------------------

@dataclass
class RasterResult:
    """R5 combined Stage-1 link-signature evidence. ``labels`` and ``tags``
    are drawn only from ``LABEL_VOCAB``/``TAG_VOCAB``; ``consistent_with`` is
    informational only and MUST NOT be treated as a label or as identity
    (identity requires a level-4 CRC-valid decode, never produced here)."""
    labels: list[str]
    tags: list[str]
    consistent_with: list[str]
    raster: RasterEvidence
    period: PeriodEvidence
    cadence_tags: list[CadenceTag]
    fixed_or_hopping: str | None
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "labels": list(self.labels),
            "tags": list(self.tags),
            "consistent_with": list(self.consistent_with),
            "raster": {
                "spacing_hz": self.raster.delta_hz,
                "offset_hz": self.raster.offset_hz,
                "n_channels": self.raster.n_channels,
                "rayleigh_r": self.raster.rayleigh_r,
                "rayleigh_r_debiased": self.raster.rayleigh_r_debiased,
                "p_false": self.raster.p_false,
                "aliases_hz": list(self.raster.aliases_hz),
            },
            "period": {
                "t_hat_s": self.period.t_hat_s,
                "n_intervals": self.period.n_intervals,
                "rayleigh_r": self.period.rayleigh_r,
                "p_false": self.period.p_false,
                "duration_mode": self.period.duration_mode,
            },
            "notes": list(self.notes),
        }


def analyze_raster(
    events: list[BurstEvent],
    *,
    cluster_tol_hz: float = DEFAULT_CLUSTER_TOL_HZ,
    deltas_hz: tuple[float, ...] = DEFAULT_DELTAS_HZ,
    periods_s: tuple[float, ...] = ELRS_PERIODS_S,
    frame_dt_s: float | None = None,
) -> RasterResult:
    """Run R1-R5 over one window's (or one accumulated multi-dwell)
    ``BurstEvent`` list and assemble the controlled-vocabulary result.

    Evidence level: level 1 morphology (`hopping_candidate`,
    `fixed_channel_burst_candidate`) and level 2 probabilistic family
    candidates (`fhss_1mhz_grid_candidate`, `fhss_2mhz_grid_candidate`,
    `rc_link_family_candidate`, `droneid_cadence_candidate`) ONLY -- never a
    manufacturer identity. Multi-dwell accumulation (R1(e), needed for any
    2 MHz-grid claim) is the caller's responsibility: pass in a ``events``
    list already pooled (in absolute Hz) across dithered dwell centres.

    ``frame_dt_s``, when known, is forwarded to ``period_test`` so it can
    drop degenerate co-temporal (dt ~= 0) intervals before the R2 Rayleigh
    scan (C1 fix); see ``period_test``'s docstring.
    """
    clusters = cluster_centres(events, tol_hz=cluster_tol_hz)
    raster_ev = raster_test(clusters, deltas_hz=deltas_hz)
    period_ev = period_test(clusters, periods_s=periods_s, frame_dt_s=frame_dt_s)
    cadence_tags = cadence_discount(clusters, period_ev, events)
    fixhop = fixed_vs_hopping(clusters)

    labels: list[str] = []
    tags: list[str] = []
    consistent: list[str] = []
    notes: list[str] = []

    if raster_ev.insufficient:
        tags.append("INSUFFICIENT_CHANNELS")
        notes.append(
            f"Only {raster_ev.n_channels} channel clusters attested by >=2 bursts "
            f"(need >= {M_MIN_RASTER}) -- grid lattice test not attempted; this is "
            f"'insufficient evidence', not a negative result (design S1)."
        )
    elif raster_ev.delta_hz is not None:
        d = raster_ev.delta_hz
        if abs(d - 1.0e6) <= 0.1e6:
            labels.append("fhss_1mhz_grid_candidate")
            if raster_ev.offset_hz is not None and _elrs_offset_consistent(raster_ev.offset_hz, d):
                consistent.append("expresslrs_2g4")
        elif abs(d - 2.0e6) <= 0.2e6:
            labels.append("fhss_2mhz_grid_candidate")
            notes.append(
                "2 MHz raster spacing/offset is indistinguishable from BLE data-channel "
                "spacing by frequency alone (design S2(e)); see the ble_connection_like "
                "tag for the time-domain discriminator. DJI RC uplink raster is not "
                "evidenced (research/briefs/rc-link-raster-facts.md item 1) and is not "
                "asserted here."
            )
        else:
            notes.append(
                f"Frequency lattice detected at Delta={d/1e6:.3f} MHz "
                f"(R={raster_ev.rayleigh_r:.3f}, M={raster_ev.n_channels}) -- not in the "
                f"controlled level-2 label vocabulary (only 1.0/2.0 MHz grids are)."
            )
        if raster_ev.aliases_hz:
            notes.append(f"Submultiple alias spacing(s) also concentrate: {raster_ev.aliases_hz} Hz "
                          f"(reported as aliases of {d} Hz, not separate detections; design S2(c)).")

    tag_by_name = {t.tag for t in cadence_tags}
    if "wifi_beacon_like" in tag_by_name:
        tags.append("wifi_beacon_like")
    if "ble_connection_like" in tag_by_name:
        tags.append("ble_connection_like")
    # Informational only (never suppresses, never a detection): says "this
    # window is dominated by occupants wider than any channel this module
    # models", i.e. WHY a narrow hop set was not found. Level 1 morphology
    # about the CHANNEL OCCUPANCY, not an identity claim -- a >=8 MHz burst in
    # 2.4 GHz is most often Wi-Fi, but DroneID/OcuSync downlink and microwave
    # leakage are also wideband, so the token deliberately says "wifi_like",
    # not "wifi".
    n_wide = len(_wideband_events(events))
    if n_wide >= WIFI_WIDEBAND_MIN_EVENTS:
        tags.append("wifi_like_wideband")
        notes.append(
            f"{n_wide} burst(s) at/above {WIFI_WIDEBAND_MIN_BW_HZ/1e6:.0f} MHz (or "
            f"frequency-edge-clipped by the dwell) -- wideband occupancy; these are "
            f"excluded from the hop-set count (R4 revision), so an absent hopping "
            f"label here is 'masked/insufficient', not 'no hopper'."
        )
    if any(t.tag == "droneid_cadence_candidate" for t in cadence_tags):
        labels.append("droneid_cadence_candidate")

    if ("ble_connection_like" in tags or "wifi_beacon_like" in tags):
        suppress = {"fhss_1mhz_grid_candidate", "fhss_2mhz_grid_candidate", "rc_link_family_candidate"}
        removed = [l for l in labels if l in suppress]
        if removed:
            labels = [l for l in labels if l not in suppress]
            notes.append(
                f"Suppressed level-2 label(s) {removed}: cadence is a better match to a "
                f"known non-UAS discount ({[t for t in tags if t != 'INSUFFICIENT_CHANNELS']}) "
                f"than to an RC/UAS family (design S3 BLE discriminator / R3)."
            )

    if fixhop is not None:
        labels.append(fixhop)

    if (
        fixhop == "hopping_candidate"
        and period_ev.passed
        and period_ev.t_hat_s is not None
        and 1e-3 <= period_ev.t_hat_s <= 20e-3
        and all(c.bw_hz <= 2.0e6 for c in _repeat_clusters(clusters))
        and period_ev.duration_mode in ("lt_0.4ms", "0.4_1ms", "1_3ms")
        and "ble_connection_like" not in tags
        and "wifi_beacon_like" not in tags
    ):
        labels.append("rc_link_family_candidate")

    assert all(l in LABEL_VOCAB for l in labels), labels
    assert all(t in TAG_VOCAB for t in tags), tags

    return RasterResult(
        labels=labels,
        tags=tags,
        consistent_with=consistent,
        raster=raster_ev,
        period=period_ev,
        cadence_tags=cadence_tags,
        fixed_or_hopping=fixhop,
        notes=notes,
    )
