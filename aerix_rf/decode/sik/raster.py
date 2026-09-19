"""SiK sub-GHz hop-raster / NETID estimator (T4).

Implements the raster half of ``docs/design/sik-mavlink-passive-decode.md``
S2 ("Hop-set / NETID handling") over a set of observed burst centre
frequencies: spacing/offset/channel-count estimation via the same Rayleigh
lattice statistic used by the 2.4 GHz RC-link raster module
(:mod:`aerix_rf.detect.raster`, reused directly -- see the imports below),
plus consistency-checking against the finite (spacing, N) grid that the SiK
firmware can actually produce for a given band (S1's ``freq_min``/``freq_max``
table and the ``(max-min)/(N+2)`` formula, 10 kHz hop-step register
quantisation).

**Evidence level 1-2 (synthetic).** A passing raster test here is
``sik_like_hopper_candidate`` (level 2: probabilistic "this looks like a
SiK-class 250/145/167 kHz-family hopper"), never identity. NETID recovery via
:func:`netid_candidates_from_sequence` is an auxiliary *consistency check*
(design S2: "Do not brute-force NETID ... it is in the header in clear" --
the header already gives NETID directly once a frame's CRC validates; this
brute force is only useful when the *physical channel sequence* is known but
no CRC-valid frame has been recovered yet, or as a cross-check).

Band tables (S1, PRIMARY unless noted): board default ``freq_min``/
``freq_max``/``num_channels``. ``NUM_CHANNELS``/``MIN_FREQ``/``MAX_FREQ`` are
all operator-overridable in the firmware; this module estimates spacing from
the data (a free search) and only uses the band table to (a) bound the search
range and (b) report which (spacing, N) legal pairs are consistent with the
result -- it never assumes the default edges are in force (S2 caveat).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from aerix_rf.detect.raster import _free_search, _rayleigh_stat  # reuse (T2)

# Board default (freq_min_hz, freq_max_hz, default_num_channels).
# PRIMARY (firmware main.c:322-346, verified 2026-09-19). NOTE: the firmware
# also has a FREQ_470 board (470-471 MHz, N=10) that is missing here.
# Also unmodelled: the firmware places channel 0 at
# freq_min + spacing/2 + netid_offset, netid_offset in [0, spacing) when N > 5
# (main.c:420-428) -- so the recovered raster PHASE is NETID-dependent and must
# not be compared against a band-edge-derived phase. See the brief.
# Keyed by the CLI/pipeline band token (aerix_rf.scan.bands presets
# "sik915"/"sik868"/"sik433"); bare region digits are accepted as aliases.
BAND_LIMITS_HZ: Dict[str, Tuple[float, float, int]] = {
    "sik915": (915.0e6, 928.0e6, 50),
    "sik868": (868.0e6, 870.0e6, 10),
    "sik433": (433.05e6, 434.79e6, 10),
}
_BAND_ALIASES: Dict[str, str] = {"915": "sik915", "868": "sik868", "433": "sik433"}

MAX_FREQ_CHANNELS = 50           # PRIMARY: freq_hopping.h:37 (and main.c:371 clamps N to 1..50)
HOP_STEP_QUANT_HZ = 10e3         # scale_uint32(spacing, 10000) register unit -- PRIMARY (firmware):
                                 # radio_443x.c:614-626 writes spacing/10 kHz to the 8-bit
                                 # FREQUENCY_HOPPING_STEP_SIZE register (hence the 2.55 MHz guard).
                                 # Firmware floors (fmax-fmin)/(N+2) to integer Hz FIRST, then rounds
                                 # half-UP; _nominal_spacing_hz() below uses float + banker's round(),
                                 # which differs on exact .5-register ties. See the brief.

# Free-spacing search range: below the narrowest board's floor (N=50 on the
# 433 band would be an absurdly dense hop set, but keep headroom) and above
# the widest single-channel case (N=1 on any board).
_FREE_SPACING_RANGE_HZ = (10e3, 3.0e6)
_FREE_SPACING_STEPS = 600  # ~5 kHz coarse resolution over the range above

M_MIN_CHANNELS = 3          # minimum distinct-frequency clusters to attempt the lattice test
R_MIN_RASTER = 0.9
SPACING_CONSISTENCY_TOL_HZ = 5e3  # T4 acceptance: spacing recovered within +/-5 kHz
ON_LATTICE_TOL_HZ = 40e3          # cluster-vs-recovered-grid phase tolerance for the N
                                    # tie-break below: comfortably above the burst
                                    # detector's -6 dB edge-midpoint centre bias/jitter on a
                                    # GFSK burst (empirically a few-kHz spread, occasionally a
                                    # systematic tens-of-kHz offset -- unbiased-for-flat-top-
                                    # bursts detector, see aerix_rf/detect/bursts.py, is not
                                    # exactly unbiased for a Gaussian-shaped GFSK spectrum),
                                    # comfortably below half the narrowest legal spacing.


def _band_limits(band: str) -> Tuple[float, float, int]:
    key = _BAND_ALIASES.get(band, band)
    if key not in BAND_LIMITS_HZ:
        raise ValueError(f"unknown SiK band {band!r}: use one of {sorted(BAND_LIMITS_HZ)}")
    return BAND_LIMITS_HZ[key]


def _nominal_spacing_hz(freq_min_hz: float, freq_max_hz: float, n_channels: int) -> float:
    """``(freq_max-freq_min)/(N+2)``, rounded to the 10 kHz hop-step register
    unit. PRIMARY (firmware main.c:417, radio_443x.c:624). Caveat: the
    firmware floors the division to integer Hz and then rounds half-up; this
    uses float division + banker's ``round()``."""
    raw = (freq_max_hz - freq_min_hz) / (n_channels + 2)
    return round(raw / HOP_STEP_QUANT_HZ) * HOP_STEP_QUANT_HZ


def legal_raster_pairs(band: str) -> List[Tuple[float, int]]:
    """All ``(spacing_hz, n_channels)`` pairs the firmware can produce on
    ``band`` for ``n_channels`` in ``[1, MAX_FREQ_CHANNELS]``, at the board's
    *default* ``freq_min``/``freq_max`` (S1 table). Does not cover a custom
    ``MIN_FREQ``/``MAX_FREQ`` override (S2 caveat) -- see module docstring."""
    lo, hi, _default_n = _band_limits(band)
    return [(_nominal_spacing_hz(lo, hi, n), n) for n in range(1, MAX_FREQ_CHANNELS + 1)]


# ---------------------------------------------------------------------------
# (1) Raster (spacing/offset/N) estimate
# ---------------------------------------------------------------------------

@dataclass
class SikRasterEvidence:
    """Level 1-2 raster evidence for a SiK-class hop set. ``consistent`` is
    True only when the free-search spacing lands within
    ``SPACING_CONSISTENCY_TOL_HZ`` of a legal (band, N) pair AND the lattice
    test passed (``rayleigh_r >= R_MIN_RASTER``, ``n_channel_clusters >= M_MIN_CHANNELS``).
    """

    band: str
    spacing_hz: Optional[float]
    offset_hz: Optional[float]
    n_channels: Optional[int]           # legal N implied by spacing_hz, if consistent
    n_channel_clusters: int             # distinct-frequency clusters actually observed
    rayleigh_r: float
    p_false: float
    consistent: bool
    insufficient: bool
    notes: List[str] = field(default_factory=list)


def _cluster_raw_centres(centres_hz: Sequence[float], tol_hz: float) -> List[Tuple[float, int]]:
    """Sequential agglomeration of raw (repeated-visit) burst centres into
    per-channel ``(mean_centre_hz, n_visits)`` -- a minimal local version of
    :func:`aerix_rf.detect.raster.cluster_centres` for plain floats (no
    :class:`BurstEvent` bandwidth field available here)."""
    xs = sorted(float(c) for c in centres_hz)
    if not xs:
        return []
    clusters: List[List[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] <= tol_hz:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [(float(np.mean(c)), len(c)) for c in clusters]


def estimate_sik_raster(
    burst_centres_hz: Sequence[float],
    band: str,
    *,
    cluster_tol_hz: float = 20e3,
    r_min: float = R_MIN_RASTER,
    m_min: int = M_MIN_CHANNELS,
) -> SikRasterEvidence:
    """Estimate hop-raster spacing/offset/channel-count from observed burst
    centre frequencies (absolute Hz) and check consistency against ``band``'s
    legal (spacing, N) pairs (S1).

    ``burst_centres_hz`` may contain repeated visits to the same physical
    channel (the common case for a real hop set observed over several TDM
    windows); they are first agglomerated into per-channel clusters
    (``cluster_tol_hz``, well under the narrowest legal spacing so adjacent
    channels are never merged) before the Rayleigh lattice test runs on the
    per-channel mean frequencies -- reusing
    :func:`aerix_rf.detect.raster._rayleigh_stat`/``_free_search`` (T2).
    """
    lo, hi, _default_n = _band_limits(band)
    clusters = _cluster_raw_centres(burst_centres_hz, cluster_tol_hz)
    m = len(clusters)
    if m < m_min:
        return SikRasterEvidence(
            band=band, spacing_hz=None, offset_hz=None, n_channels=None,
            n_channel_clusters=m, rayleigh_r=0.0, p_false=1.0,
            consistent=False, insufficient=True,
            notes=[f"only {m} distinct-frequency clusters (need >= {m_min})"],
        )

    centres = np.array([c for c, _n in clusters], dtype=np.float64)
    lo_search = max(_FREE_SPACING_RANGE_HZ[0], (hi - lo) / (MAX_FREQ_CHANNELS + 2) * 0.5)
    hi_search = min(_FREE_SPACING_RANGE_HZ[1], (hi - lo) / 3.0 * 1.5)
    if hi_search <= lo_search:
        lo_search, hi_search = _FREE_SPACING_RANGE_HZ
    free_d = _free_search(centres, lo_search, hi_search, _FREE_SPACING_STEPS, log_spaced=False)

    # Candidate spacings = the band's finite legal set (S1) plus the free
    # search result, so a true grid spacing is tested exactly (not just
    # wherever the coarse/zoom search happened to land) while a non-default
    # MIN_FREQ/MAX_FREQ/NUM_CHANNELS link is still reachable via free_d.
    legal_all = legal_raster_pairs(band)
    candidates = sorted({s for s, _n in legal_all} | {free_d})
    results = {d: _rayleigh_stat(centres, d) for d in candidates}

    # Prefer the LARGEST candidate that passes the lattice test (a true
    # spacing S also concentrates at every submultiple S/2, S/3, ... -- the
    # same aliasing r1 R1(c) handles in aerix_rf.detect.raster.raster_test;
    # picking the largest passing candidate rather than whatever the search
    # converged to avoids reporting a submultiple alias as "the" spacing).
    passing = [(d, r, off) for d, (r, off) in results.items() if r >= r_min]
    if passing:
        passing.sort(key=lambda t: t[0], reverse=True)
        spacing_hat, r, offset = passing[0]
    else:
        spacing_hat = max(results, key=lambda d: results[d][0])
        r, offset = results[spacing_hat]
    p_false = float(np.exp(-m * r * r))

    if r < r_min:
        return SikRasterEvidence(
            band=band, spacing_hz=spacing_hat, offset_hz=offset, n_channels=None,
            n_channel_clusters=m, rayleigh_r=r, p_false=p_false,
            consistent=False, insufficient=False,
            notes=[f"lattice test failed (R={r:.3f} < {r_min})"],
        )

    # Which legal N (if any) is consistent with the recovered spacing? The
    # 10 kHz register quantisation can make two adjacent N (e.g. 49 and 50
    # on the 915 board) round to the identical spacing -- break that tie
    # with the hard constraint that N must be able to hold every DISTINCT
    # channel actually observed, preferring the smallest such N (Occam)
    # among ties. Use the ON-LATTICE cluster count (phase within
    # ON_LATTICE_TOL_HZ of the recovered grid), not the raw cluster count:
    # a single off-grid noise/outlier cluster must not inflate the apparent
    # channel-count floor and push the N estimate to the wrong tie member.
    m_on_lattice = 0
    for c, _n in clusters:
        resid = (c - offset) % spacing_hat
        if resid > spacing_hat / 2.0:
            resid -= spacing_hat
        if abs(resid) <= ON_LATTICE_TOL_HZ:
            m_on_lattice += 1
    legal = [(s, n) for s, n in legal_all if n >= m_on_lattice] or legal_all
    best_delta = min(abs(s - spacing_hat) for s, n in legal)
    tied_ns = sorted(n for s, n in legal if abs(s - spacing_hat) == best_delta)
    # The 10 kHz register quantisation routinely makes several adjacent N
    # (e.g. 49/50/51 on the 915 board) round to the identical legal spacing,
    # so an observed-channel-count floor alone cannot break the tie once the
    # true N wasn't fully visited (S2 caveat). Prefer the board's own
    # default_num_channels (S1) when it is one of the tied candidates -- a
    # deviation from default is the less common case -- else fall back to
    # the smallest tied N (Occam).
    best_n = _default_n if _default_n in tied_ns else tied_ns[0]
    consistent = best_delta <= SPACING_CONSISTENCY_TOL_HZ
    notes = []
    if m_on_lattice < m:
        notes.append(
            f"{m - m_on_lattice} of {m} clusters sit off the recovered "
            f"{spacing_hat/1e3:.1f} kHz grid (> {ON_LATTICE_TOL_HZ/1e3:.0f} kHz phase "
            f"error) and were excluded from the channel-count floor used to pick N."
        )
    if not consistent:
        notes.append(
            f"spacing {spacing_hat/1e3:.1f} kHz does not match any legal {band} "
            f"(spacing, N) pair within {SPACING_CONSISTENCY_TOL_HZ/1e3:.0f} kHz "
            f"(closest: N={best_n}, {best_delta/1e3:.1f} kHz off) -- non-default "
            f"MIN_FREQ/MAX_FREQ/NUM_CHANNELS is possible (S2 caveat), or this is "
            f"not a SiK-class hopper."
        )

    return SikRasterEvidence(
        band=band, spacing_hz=spacing_hat, offset_hz=offset,
        n_channels=best_n if consistent else None,
        n_channel_clusters=m, rayleigh_r=r, p_false=p_false,
        consistent=consistent, insufficient=False, notes=notes,
    )


# ---------------------------------------------------------------------------
# (2) NETID recovery from an observed physical-channel sequence
# ---------------------------------------------------------------------------

_LCG_A = 1103515245
_LCG_C = 12345
_LCG_MASK = 0xFFFFFFFF


def hop_map(netid: int, n_channels: int) -> List[int]:
    """SiK's ``fhop_init()`` hop map: ``channel_map[i] = i`` then a
    Durstenfeld Fisher-Yates shuffle driven by the LCG
    ``r_next = r_next*1103515245 + 12345`` (32-bit wraparound), draw
    ``(r_next >> 16) & 0x7FFF`` per step, seeded ``r_next = netid``
    (``r_srand(netid)``). Used both to generate synthetic test hop sequences
    and by :func:`netid_candidates_from_sequence`'s brute force.

    .. warning::
       **PROVENANCE: WRONG (task-spec formula, contradicted by the firmware).**
       Verified 2026-09-19 against the upstream ``ArduPilot/SiK`` master C
       source -- see ``research/briefs/sik-freq-hopping-firmware.md``.
       ``Firmware/radio/freq_hopping.c:84-93`` uses the *naive* benpfaff
       shuffle, not Durstenfeld Fisher-Yates:

       * loop is ASCENDING ``i = 0 .. n-2`` (here: descending ``n-1 .. 1``);
       * ``j = ((uint8_t)r_rand()) % n`` -- modulo ``n``, the whole array
         (here: ``% (i+1)``);
       * the draw is TRUNCATED TO 8 BITS by the ``(uint8_t)`` cast, i.e.
         ``(r_next >> 16) & 0xFF`` (here: 15-bit ``& 0x7FFF``);
       * the seed is NETID only on unencrypted links -- with ``ENCRYPTION``
         set, ``shuffleRand()`` (``freq_hopping.c:95-104``) seeds with
         ``crc16(32, encryption_key)`` instead, so NETID brute force is
         invalid there by construction.

       The LCG constants below ARE correct. The resulting permutations agree
       with the firmware only at chance level (1-3 of N positions for NETID
       25/1/4242 at N=10/50), so any NETID reported today is meaningless and
       every synthetic hop fixture built from this function is not SiK-like.
       Fixing this (and the vectorised twin below) is a builder task; the
       brief carries a drop-in Python transcription and a reference vector
       (``hop_map(25, 10) == [0, 9, 5, 2, 6, 7, 4, 3, 8, 1]``). Do not treat
       this function as decode evidence until then."""
    state = int(netid) & _LCG_MASK
    m = list(range(n_channels))
    for i in range(n_channels - 1, 0, -1):
        state = (state * _LCG_A + _LCG_C) & _LCG_MASK
        draw = (state >> 16) & 0x7FFF
        j = draw % (i + 1)
        m[i], m[j] = m[j], m[i]
    return m


@lru_cache(maxsize=8)
def _hop_maps_all_netids(n_channels: int) -> np.ndarray:
    """Vectorised :func:`hop_map` for all 65536 NETIDs at once: shape
    ``[65536, n_channels]``. **Inherits :func:`hop_map`'s WRONG provenance**
    (task-spec Fisher-Yates, contradicted by ``Firmware/radio/freq_hopping.c``
    -- see the warning on :func:`hop_map` and
    ``research/briefs/sik-freq-hopping-firmware.md``); must be re-derived with
    the firmware's ascending ``j = draw % n`` / 8-bit-draw shuffle. The Fisher-Yates recursion is inherently
    sequential in ``i``, but independent *across* NETIDs, so each of the
    (at most 49) steps is one O(65536) numpy update rather than a Python
    loop -- this is what makes the brute force "cheap" (module docstring)."""
    n_netids = 1 << 16
    state = np.arange(n_netids, dtype=np.uint64)
    maps = np.tile(np.arange(n_channels, dtype=np.int64), (n_netids, 1))
    rows = np.arange(n_netids)
    for i in range(n_channels - 1, 0, -1):
        state = (state * np.uint64(_LCG_A) + np.uint64(_LCG_C)) & np.uint64(_LCG_MASK)
        draw = (state >> np.uint64(16)) & np.uint64(0x7FFF)
        j = (draw.astype(np.int64) % (i + 1))
        vi = maps[rows, i].copy()
        vj = maps[rows, j]
        maps[rows, i] = vj
        maps[rows, j] = vi
    return maps


@dataclass
class NetidCandidateResult:
    """Brute-force NETID-vs-observed-hop-sequence consistency check (S2:
    an auxiliary cross-check, NOT how NETID is normally recovered -- the
    header carries it in clear once any frame's CRC validates)."""

    n_channels: int
    n_observed: int
    threshold_k: int
    best_match_count: int
    candidates: List[int]     # NETIDs reaching >= threshold_k consecutive-hop matches
    unique: bool               # True iff exactly one candidate reached threshold_k


def netid_candidates_from_sequence(
    observed_channel_indices: Sequence[int],
    n_channels: int,
    *,
    k: Optional[int] = None,
) -> NetidCandidateResult:
    """Brute-force NETID 0-65535 against an observed sequence of physical
    channel indices (0..``n_channels``-1, ``TX advances +1 (mod N) every TDM
    window`` -- S1), assumed to be one entry per *consecutive* TDM window
    (gaps are not modelled here). For each candidate NETID, the hop map's
    inverse gives each observed channel's position in the cyclic schedule;
    a genuine match has ``position - window_index`` constant (mod N) for
    (close to) every observed hop. Returns every NETID whose best constant-
    offset run reaches ``k`` (default: all but 2 of the observed hops, floor
    5) matches.
    """
    obs = np.asarray(list(observed_channel_indices), dtype=np.int64)
    n_obs = len(obs)
    if k is None:
        k = max(5, n_obs - 2)
    if n_obs == 0 or n_channels < 2:
        return NetidCandidateResult(n_channels, n_obs, k, 0, [], False)

    maps = _hop_maps_all_netids(n_channels)  # [65536, n_channels]
    n_netids = maps.shape[0]
    inv = np.empty_like(maps)
    rows = np.arange(n_netids)[:, None]
    inv[rows, maps] = np.arange(n_channels)[None, :]

    pos = inv[:, obs]                                    # [65536, n_obs]
    window_idx = np.arange(n_obs, dtype=np.int64)[None, :]
    diffs = (pos - window_idx) % n_channels              # [65536, n_obs]

    best = np.zeros(n_netids, dtype=np.int64)
    for r in range(n_channels):
        cnt = np.count_nonzero(diffs == r, axis=1)
        np.maximum(best, cnt, out=best)

    hit = np.nonzero(best >= k)[0]
    order = hit[np.argsort(-best[hit])]
    candidates = [int(x) for x in order]
    best_match_count = int(best.max()) if n_netids else 0
    return NetidCandidateResult(
        n_channels=n_channels, n_observed=n_obs, threshold_k=k,
        best_match_count=best_match_count, candidates=candidates,
        unique=(len(candidates) == 1),
    )
