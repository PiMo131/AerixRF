"""Band presets for the scan workflow.

These are *scan presets for the test tool*, NOT regulatory truth. They are the
ranges the HackRF is told to sweep when the operator types ``--band 2.4``;
they deliberately overshoot the ISM/U-NII edges a little so channel skirts and
off-nominal drone links are still visible. Any preset can be overridden by
passing an explicit ``lo:hi`` (or ``lo-hi``) range in MHz, and callers may add
or replace entries in :data:`BANDS` at runtime (it is a plain dict).

Do not bake one regulatory region into the detector (project spec 2.3).
"""

from __future__ import annotations

import re

# name -> (lo_mhz, hi_mhz). Presets, not regulatory truth; see module docstring.
BANDS: dict[str, tuple[float, float]] = {
    "2.4": (2400.0, 2500.0),   # 2.4 GHz ISM: Wi-Fi, DJI O2/O3/O4, most hobby links
    "5.8": (5725.0, 5875.0),   # 5.8 GHz ISM: DJI O3/O4, analog FPV video
    "5.2": (5150.0, 5350.0),   # U-NII-1/2A: DJI O4 5.1 GHz mode (region dependent)
    "900": (900.0, 930.0),     # 915 MHz ISM: long-range control links (crossfire, ELRS)
}

_RANGE_RE = re.compile(
    r"^\s*(?P<lo>\d+(?:\.\d+)?)\s*[:\-]\s*(?P<hi>\d+(?:\.\d+)?)\s*$"
)


def resolve_band(spec: str) -> tuple[float, float]:
    """Turn a band spec into ``(lo_mhz, hi_mhz)``.

    ``spec`` is either a preset name from :data:`BANDS` (``"2.4"``, ``"5.8"``,
    ...) or an explicit MHz range ``"lo:hi"`` / ``"lo-hi"`` such as
    ``"2400:2483.5"``. Raises ``ValueError`` for anything else or when
    ``lo >= hi``.
    """
    if spec is None:
        raise ValueError("band spec is required")
    key = spec.strip()
    if key in BANDS:
        return BANDS[key]
    # tolerate "2.4GHz", "band-2.4" style sloppiness only for exact presets
    lowered = key.lower().removesuffix("ghz").removesuffix("mhz").strip()
    if lowered in BANDS:
        return BANDS[lowered]
    m = _RANGE_RE.match(key)
    if not m:
        raise ValueError(
            f"unknown band {spec!r}: use a preset {sorted(BANDS)} or 'lo:hi' in MHz"
        )
    lo, hi = float(m.group("lo")), float(m.group("hi"))
    if lo >= hi:
        raise ValueError(f"band {spec!r}: lo must be below hi")
    return lo, hi
