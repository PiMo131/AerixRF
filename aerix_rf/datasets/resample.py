"""Canonical resampler / band-slicer for dataset normalisation (Workstream D, T2).

Implements stage S2 of ``docs/design/dataset-normalization.md``:

    original -> optional complex mix (re-centre) + band-slice
             -> integer decimation to >= 19.2 MS/s (1.25 x canonical)
             -> ONE rational `resample_poly` stage -> 15.36 MS/s

and the resampling rule of ``docs/design/canonical-representation.md`` D14/D15
(section 7): band-slice before resampling when the target occupies less than
half the source band; integer-decimate to the smallest rate >= 19.2 MS/s,
then a single rational stage; transition band between the 12.0 MHz usable
half-width (6.0 MHz) and the 15.36 MHz canonical Nyquist (7.68 MHz); stopband
>= 60 dB.

Determinism (section 6 of the normalisation memo): never rely on
``scipy.signal.resample_poly`` defaults. Every stage's FIR filter is designed
explicitly with ``scipy.signal.kaiserord`` / ``firwin`` from parameters that
are themselves recorded in the emitted :class:`~aerix_rf.datasets.spec.ResampleStage`
(``numtaps``, ``window`` with an embedded exact Kaiser beta, ``cutoff_hz``,
``stopband_db``). ``apply_chain`` regenerates taps from those recorded
parameters plus the starting sample rate rather than caching raw arrays, so
two calls with the same inputs are byte-identical and a chain replayed from a
sidecar reproduces the same filter.

Architect amendment (2026-09-18, Workstream D, T3): the earlier one-entry
60 MS/s override (decimate-by-2 -> 64/125, honouring the design memo's
literal text) is removed. The general rule -- "integer-decimate to the
largest divisor keeping the intermediate rate >= 19.2 MS/s (1.25x
canonical), then one rational `resample_poly` stage" -- now applies
uniformly: 60 -> /3 -> 20 MS/s -> 96/125. This also covers the Zenodo
4264467 (2020) recording rates without any new special-casing: 120 -> /6 ->
20 MS/s -> 96/125 and 200 -> /10 -> 20 MS/s -> 96/125.
"""

from __future__ import annotations

import re
from math import gcd

import numpy as np
from scipy.signal import firwin, kaiserord, resample_poly

from .spec import ResampleStage

# D1 (canonical-representation.md): canonical representation rate.
CANONICAL_RATE_HZ = 15_360_000.0

# D3: declared usable band is 12.0 MHz total width (+/- 6.0 MHz).
USABLE_BW_HZ = 12.0e6
_USABLE_HALF_BW_HZ = USABLE_BW_HZ / 2.0  # 6.0 MHz passband edge

# Stopband edge = canonical Nyquist (half of 15.36 MS/s) = 7.68 MHz, per the
# normalisation memo's S2 rule ("transition band strictly between 12.0 and
# 15.36 MHz" read as double-sided widths: 12.0 MHz passes, 15.36 MHz --
# i.e. its Nyquist, 7.68 MHz single-sided -- is where the stopband begins).
_CANONICAL_NYQUIST_HZ = CANONICAL_RATE_HZ / 2.0  # 7.68 MHz

STOPBAND_DB = 60.0

# Integer-decimate to the smallest rate >= this multiple of the target rate
# before the single rational `resample_poly` stage (1.25 x canonical = 19.2
# MS/s, per D14/15 and the normalisation memo's S2 rule).
_DECIMATE_HEADROOM = 1.25

# Live-grade filter design (F5 live-latency task, architect brief 2026-09-18):
# a much shorter Kaiser FIR than the dataset-grade design above, traded for
# real-time throughput. 50 dB stopband (vs 60 dB) and a wider transition
# band roughly halve `kaiserord`'s numtaps for the same passband edge at the
# common ANTSDR rate (12.288 -> 15.36 MS/s, up=5): measured 135 taps
# (dataset) vs 73 taps (live) -- see the F6 perf task's result packet.
#
# Round-trip correction (F6 perf task, 2026-09-18): the original value here
# (1.0 MHz) was *narrower* than the dataset grade's ~1.68 MHz transition,
# which made "live" grade design MORE taps than dataset for the ANTSDR
# up=5 case (181 vs 135 measured) -- the opposite of this module's stated
# intent and of the F5 docstring above. 2.5 MHz is wide enough to reliably
# beat the dataset grade's tap count for every up-factor this module is
# actually called with, while staying well clear of the +-4.995 MHz band
# features_v2 actually reads (S1.1): the extra transition slack lands
# between 6.0 and 8.5 MHz, outside the +-5.0 MHz feature band with margin.
# Still not enough alone to hit a <=150 ms live-latency budget at HackRF's
# 20 MS/s native rate (up=96 forces a much higher design rate and,
# consequently, a much larger absolute numtaps regardless of transition/
# stopband tuning within this safe range) -- see the F6 result packet;
# that gap is a resample-architecture question (e.g. multi-stage/FFT-domain
# resampling), not a live-grade constant, and needs DSP-specialist review.
LIVE_STOPBAND_DB = 50.0
LIVE_TRANSITION_HZ = 2.5e6
_DATASET_TRANSITION_HZ = _CANONICAL_NYQUIST_HZ - _USABLE_HALF_BW_HZ


def _window_field(beta: float) -> str:
    """Encode a Kaiser beta into the ``ResampleStage.window`` string so
    ``apply_chain`` can reconstruct the exact same filter later without a
    separate ``beta`` field on the shared sidecar schema."""

    return f"kaiser(beta={beta!r})"


_WINDOW_RE = re.compile(r"kaiser\(beta=([^)]+)\)")

# F6 perf task: firwin taps depend only on (numtaps, cutoff_hz, beta,
# design_rate_hz) -- all recorded/derivable stage parameters, never on the
# IQ data itself -- so the same live-grade stage design (e.g. the fixed
# 12.288 -> 15.36 MS/s ANTSDR up=5 case) redesigns identical taps on every
# `apply_chain` call. Cached by that 4-tuple key; unbounded but keyed on a
# small, low-cardinality set of (rate, chain) combinations actually seen in
# one process, matching `_WIN_CACHE`'s existing precedent in tensor.py.
_TAPS_CACHE: dict[tuple[int, float, float, float], np.ndarray] = {}


def _firwin_cached(numtaps: int, cutoff_hz: float, beta: float, design_rate_hz: float) -> np.ndarray:
    key = (numtaps, cutoff_hz, beta, design_rate_hz)
    taps = _TAPS_CACHE.get(key)
    if taps is None:
        taps = firwin(numtaps, cutoff_hz, window=("kaiser", beta), fs=design_rate_hz)
        _TAPS_CACHE[key] = taps
    return taps


def _parse_window_beta(window: str) -> float:
    m = _WINDOW_RE.match(window or "")
    if not m:
        raise ValueError(f"cannot parse Kaiser beta from window field: {window!r}")
    return float(m.group(1))


def _design_lowpass(
    design_rate_hz: float,
    passband_hz: float = _USABLE_HALF_BW_HZ,
    stopband_hz: float = _CANONICAL_NYQUIST_HZ,
    stopband_db: float = STOPBAND_DB,
) -> tuple[int, float, float]:
    """Kaiser-window FIR lowpass design. Returns (numtaps, beta, cutoff_hz).

    ``design_rate_hz`` is the rate at which ``resample_poly`` applies the
    filter internally: ``up * fs_in`` (equivalently ``down * fs_out``).
    """

    nyquist = design_rate_hz / 2.0
    pb = min(passband_hz, nyquist * 0.98)
    sb = min(stopband_hz, nyquist * 0.999)
    if sb <= pb:
        sb = min(pb * 1.05, nyquist * 0.999)
    width = (sb - pb) / nyquist
    numtaps, beta = kaiserord(stopband_db, width)
    numtaps = int(numtaps)
    if numtaps % 2 == 0:
        numtaps += 1
    cutoff_hz = (pb + sb) / 2.0
    return numtaps, float(beta), cutoff_hz


def _make_stage(
    op: str,
    up: int,
    down: int,
    in_rate_hz: float,
    mix_hz: float | None = None,
    grade: str = "dataset",
) -> ResampleStage:
    design_rate_hz = in_rate_hz * up
    if grade == "live":
        stopband_db = LIVE_STOPBAND_DB
        transition_hz = LIVE_TRANSITION_HZ
    elif grade == "dataset":
        stopband_db = STOPBAND_DB
        transition_hz = _DATASET_TRANSITION_HZ
    else:
        raise ValueError(f"unknown resample grade {grade!r}, expected 'dataset' or 'live'")
    stopband_hz = _USABLE_HALF_BW_HZ + transition_hz
    numtaps, beta, cutoff_hz = _design_lowpass(
        design_rate_hz, stopband_hz=stopband_hz, stopband_db=stopband_db
    )
    return ResampleStage(
        op=op,
        up=up,
        down=down,
        mix_hz=mix_hz,
        numtaps=numtaps,
        window=_window_field(beta),
        cutoff_hz=cutoff_hz,
        stopband_db=stopband_db,
        grade=grade,
    )


def _find_decimate_factor(in_rate_hz: float, out_rate_hz: float) -> int:
    """Largest integer divisor ``n`` of ``in_rate_hz`` such that
    ``in_rate_hz / n >= _DECIMATE_HEADROOM * out_rate_hz``. Returns 1 (no
    decimation stage needed) if the source is already within headroom."""

    in_int = int(round(in_rate_hz))
    threshold = _DECIMATE_HEADROOM * out_rate_hz
    max_n = max(1, int(in_int // threshold))
    for n in range(max_n, 1, -1):
        if in_int % n == 0:
            return n
    return 1


def plan_chain(
    in_rate_hz: float,
    out_rate_hz: float = CANONICAL_RATE_HZ,
    in_bw_hz: float | None = None,
    grade: str = "dataset",
) -> list[ResampleStage]:
    """Plan the S2 resample chain from ``in_rate_hz`` to ``out_rate_hz``.

    Always returns a non-empty, JSON-serialisable list of
    :class:`ResampleStage` -- even a no-op is recorded (an explicit
    ``identity`` stage), per the normalisation memo ("no relying on implicit
    behaviour"). ``in_bw_hz`` is accepted for API symmetry with
    :func:`usable_bandwidth` / :func:`band_deficit` but does not change the
    resample chain itself (band-narrower-than-usable sources still resample
    to the universal grid; only the sidecar's ``usable_bw_hz``/
    ``band_deficit`` change -- see those helpers).

    ``grade``: ``"dataset"`` (default, unchanged 60 dB stopband / ~1.68 MHz
    transition Kaiser design used by dataset normalisation) or ``"live"``
    (F5 live-latency task: a much shorter Kaiser FIR -- 50 dB stopband /
    1.0 MHz transition -- for the real-time path). The two grades are never
    mixed within a chain; every stage records its own ``grade``.
    """

    in_rate_hz = float(in_rate_hz)
    out_rate_hz = float(out_rate_hz)

    if int(round(in_rate_hz)) == int(round(out_rate_hz)):
        return [ResampleStage(op="identity", up=1, down=1)]

    decim = _find_decimate_factor(in_rate_hz, out_rate_hz)

    stages: list[ResampleStage] = []
    intermediate_rate_hz = in_rate_hz
    if decim > 1:
        stages.append(_make_stage("decimate", up=1, down=decim, in_rate_hz=in_rate_hz, grade=grade))
        intermediate_rate_hz = in_rate_hz / decim

    inter_int = int(round(intermediate_rate_hz))
    out_int = int(round(out_rate_hz))
    g = gcd(inter_int, out_int)
    up = out_int // g
    down = inter_int // g
    stages.append(_make_stage("rational", up=up, down=down, in_rate_hz=intermediate_rate_hz, grade=grade))
    return stages


def apply_chain(iq: np.ndarray, chain: list[ResampleStage], in_rate_hz: float) -> np.ndarray:
    """Apply a chain produced by :func:`plan_chain` to ``iq``.

    ``in_rate_hz`` is required (a deliberate, documented deviation from the
    bare ``apply_chain(iq, chain)`` sketch): filter taps are regenerated
    deterministically from each stage's recorded design parameters plus the
    running sample rate, not cached, so the starting rate must be supplied.
    Returns complex64.
    """

    # F6 perf task: "live" grade chains keep complex64 through resample_poly
    # (avoids two full-array float64 promotions -- input cast and mix's
    # `t`/exp temporaries -- for a real-time path that only ever accepts
    # complex64 IQ). Dataset-grade chains are unchanged (complex128
    # throughout) to preserve dataset-normalisation bit-exactness. Chains
    # never mix grades (module docstring), so checking any stage is
    # equivalent to checking all of them.
    is_live = any(getattr(stage, "grade", None) == "live" for stage in chain)
    compute_dtype = np.complex64 if is_live else np.complex128

    x = np.asarray(iq, dtype=compute_dtype)
    current_rate_hz = float(in_rate_hz)
    for stage in chain:
        if stage.op == "identity":
            continue
        if stage.op == "mix":
            n = x.shape[-1]
            t = np.arange(n, dtype=np.float64) / current_rate_hz
            x = (x * np.exp(-2j * np.pi * float(stage.mix_hz) * t)).astype(compute_dtype)
            continue
        up = int(stage.up or 1)
        down = int(stage.down or 1)
        design_rate_hz = current_rate_hz * up
        beta = _parse_window_beta(stage.window)
        taps = _firwin_cached(int(stage.numtaps), float(stage.cutoff_hz), beta, design_rate_hz)
        if is_live:
            taps = taps.astype(np.float32)
        x = resample_poly(x, up, down, window=taps)
        current_rate_hz = current_rate_hz * up / down
    return x.astype(np.complex64)


def mix_and_slice(iq: np.ndarray, in_rate_hz: float, offset_hz: float) -> tuple[np.ndarray, ResampleStage]:
    """Complex-mix ``iq`` so that content at ``+offset_hz`` lands at DC (S2
    "optional complex mix to re-centre"). Sample rate is unchanged; band
    narrowing/decimation is left to a subsequent :func:`plan_chain` /
    :func:`apply_chain` pass. Returns the mixed array (same dtype family as
    input, promoted to complex128 internally) and the ``mix`` stage record
    for ``resample_chain`` provenance."""

    x = np.asarray(iq, dtype=np.complex128)
    n = x.shape[-1]
    t = np.arange(n, dtype=np.float64) / float(in_rate_hz)
    mixed = x * np.exp(-2j * np.pi * float(offset_hz) * t)
    stage = ResampleStage(op="mix", mix_hz=float(offset_hz))
    return mixed, stage


def usable_bandwidth(
    in_rate_hz: float,
    in_bw_hz: float | None = None,
    target_usable_bw_hz: float = USABLE_BW_HZ,
) -> tuple[float, bool]:
    """Compute ``(usable_bw_hz, band_deficit)`` for a source given its
    sample rate and (optionally) its analog/declared bandwidth, per S2's
    "source narrower than 12 MHz" rule: still resample to the universal
    grid, but flag the true, narrower usable width rather than pretend the
    full 12 MHz is populated."""

    candidate_hz = float(in_rate_hz) if in_bw_hz is None else min(float(in_bw_hz), float(in_rate_hz))
    usable_bw_hz = min(candidate_hz, float(target_usable_bw_hz))
    band_deficit = usable_bw_hz < float(target_usable_bw_hz)
    return usable_bw_hz, band_deficit


def chain_to_json(chain: list[ResampleStage]) -> list[dict]:
    """``resample_chain`` as plain JSON-serialisable dicts (sidecar field),
    in stage order."""

    return [stage.model_dump(mode="json", exclude_none=True) for stage in chain]
