"""Band plans, dwell planning, stepped sweeps and detection events.

``bands`` and ``planner`` are numpy-only and imported eagerly; ``sweep``
(scipy through the DSP layer) and ``events`` are resolved lazily so
``import antsdr_toolkit.scan`` stays cheap for callers that only need the
frequency tables.
"""

from __future__ import annotations

from .bands import (
    BAND_PLANS,
    DRONEID_CENTRES_MHZ,
    FPV_5G8_CHANNELS,
    Band,
    FpvChannel,
    fpv_channel_freqs_hz,
    get_band,
    list_bands,
)
from .planner import Dwell, plan_dwells, usable_span_hz

__all__ = [
    "BAND_PLANS",
    "DRONEID_CENTRES_MHZ",
    "FPV_5G8_CHANNELS",
    "Band",
    "DetectionEvent",
    "Dwell",
    "DwellResult",
    "FpvChannel",
    "JsonlEventWriter",
    "OccupancyMap",
    "OccupiedSegment",
    "Sweeper",
    "analyse_dwell",
    "events_from_dwell",
    "fpv_channel_freqs_hz",
    "get_band",
    "list_bands",
    "plan_dwells",
    "usable_span_hz",
]

_LAZY = {
    "Sweeper": "sweep",
    "DwellResult": "sweep",
    "OccupancyMap": "sweep",
    "OccupiedSegment": "sweep",
    "analyse_dwell": "sweep",
    "DetectionEvent": "events",
    "JsonlEventWriter": "events",
    "events_from_dwell": "events",
}


def __getattr__(name: str):
    """Lazily expose the sweep and event objects without importing scipy eagerly."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
