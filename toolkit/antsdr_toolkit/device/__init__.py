"""Sample sources: the abstract interface plus file-replay and synthetic sources.

The hardware driver for the E200 (``pyadi-iio``) is deliberately *not*
imported here; ``SyntheticSource``/``Scene`` are resolved lazily so importing
this package never pulls in more than numpy.
"""

from __future__ import annotations

from .base import IQ_DTYPE, SampleSource, StreamInfo, empty_iq
from .file_source import SigmfFileSource

__all__ = [
    "IQ_DTYPE",
    "SampleSource",
    "SigmfFileSource",
    "StreamInfo",
    "empty_iq",
]

_LAZY = {"SyntheticSource", "Scene", "Emission"}


def __getattr__(name: str):
    """Lazily expose the synthetic-scene objects without importing scipy eagerly."""
    if name in _LAZY:
        from . import synthetic

        return getattr(synthetic, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
