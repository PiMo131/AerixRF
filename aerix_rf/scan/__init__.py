"""Scan-and-lock workflow library (spec 2.3 / milestone 1.3).

Typical use::

    from aerix_rf.scan import resolve_band, record_baseline, save_baseline, \\
        load_baseline, sweep_once, rank_candidates, summarize

    lo, hi = resolve_band("2.4")
    b = record_baseline(lo, hi, seconds=30)      # drones OFF
    save_baseline(b, "sessions/site-baseline")   # -> .npz
    ...
    freqs, matrix, n = sweep_once(lo, hi, seconds=2)
    cands = rank_candidates(freqs, matrix, load_baseline("sessions/site-baseline"))
    print(summarize(cands))

No CLI here; see the ``aerix-rf`` entry point for the operator commands.
"""

from aerix_rf.scan.bands import BANDS, resolve_band
from aerix_rf.scan.candidates import (
    DEFAULT_WEIGHTS,
    Candidate,
    rank_candidates,
    summarize,
    to_dict,
)
from aerix_rf.scan.sweep import (
    Baseline,
    average_db,
    load_baseline,
    parse_sweep_csv_multi,
    record_baseline,
    run_hackrf_sweep,
    save_baseline,
    sweep_once,
)

__all__ = [
    "BANDS", "resolve_band",
    "Baseline", "average_db", "parse_sweep_csv_multi", "run_hackrf_sweep",
    "sweep_once", "record_baseline", "save_baseline", "load_baseline",
    "Candidate", "DEFAULT_WEIGHTS", "rank_candidates", "summarize", "to_dict",
]
