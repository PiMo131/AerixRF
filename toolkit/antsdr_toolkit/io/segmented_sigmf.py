"""SigMF recorder support for discontinuous host-side snapshot captures.

SigMF's data file is necessarily packed: sample indices describe positions in
the file, not elapsed RF time.  A high-rate E200 snapshot therefore cannot be
made truthful by inserting guessed zero samples for time the host did not
receive.  Instead this module starts a new SigMF capture segment at every
known host-buffer boundary and marks the continuity before that segment as
unknown.

The first segment is created by :class:`~antsdr_toolkit.io.sigmf_io.SigmfRecorder`.
Subsequent segments use ``core:sample_start`` to point at the packed file index
and ``antsdr:continuity = 'unknown-gap-before'`` to state explicitly that no
RF timing relationship may be inferred across the boundary.  A hardware
sample counter can later replace that statement with ``core:global_index``;
the current pyadi/libiio path does not expose such a counter.
"""

from __future__ import annotations

from typing import Any

from .sigmf_io import NAMESPACE, SigmfRecorder

__all__ = ["SegmentedSigmfRecorder"]


class SegmentedSigmfRecorder(SigmfRecorder):
    """A :class:`SigmfRecorder` that can mark discontinuous capture segments."""

    def start_segment(
        self,
        *,
        frequency_hz: float | None = None,
        continuity: str = "unknown-gap-before",
        datetime_utc: str | None = None,
        **extra: Any,
    ) -> None:
        """Start a new capture segment at the current packed sample index.

        ``datetime_utc`` is deliberately optional.  A host timestamp taken
        before ``rx()`` is not the same thing as the RF timestamp of a DMA
        buffer already waiting in the device, so callers should omit it unless
        they have a defensible time reference.
        """
        if self.closed:
            raise ValueError("recorder is closed")
        if self.samples_written <= 0:
            raise ValueError("write at least one sample before starting a new segment")

        capture: dict[str, Any] = {
            "core:sample_start": int(self.samples_written),
            "core:frequency": float(
                self.info.center_freq_hz if frequency_hz is None else frequency_hz
            ),
            f"{NAMESPACE}:continuity": str(continuity),
        }
        if datetime_utc is not None:
            capture["core:datetime"] = str(datetime_utc)
        for key, value in extra.items():
            capture[key if ":" in key else f"{NAMESPACE}:{key}"] = value
        self._captures.append(capture)
