"""Replay a SigMF recording through the :class:`SampleSource` interface.

The dataset is memory-mapped, so opening a multi-gigabyte capture is instant
and :meth:`SigmfFileSource.read` only touches the pages it returns. Samples are
converted to ``complex64`` at full scale ``|x| == 1.0`` whatever the on-disk
datatype is (``cf32_le`` written by this toolkit, ``ci16_le``/``ci8`` produced
natively by the E200/AD9361 firmware).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import numpy as np

from .base import SampleSource, StreamInfo

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps the runtime import lazy
    from ..io.sigmf_io import SigmfReader


class SigmfFileSource(SampleSource):
    """Sequential (optionally looping) reader over a SigMF dataset.

    Args:
        path: ``.sigmf-meta``, ``.sigmf-data`` or the common stem.
        loop: When ``True`` the recording wraps around forever and ``read``
            always returns exactly ``n_samples`` (useful to feed live-style
            pipelines from a capture). When ``False`` the source is finite.
        channel: Index into the recording's channels (0-based position along
            axis 0, not the hardware channel number). Selecting one channel
            makes ``read`` return ``(n,)`` arrays and narrows ``info.rx_channels``
            to that single hardware channel. ``None`` returns every channel.

    ``info.hardware`` is taken from the recording's ``core:hw`` so a replayed
    E200 capture still identifies as ``"antsdr-e200"``; recordings without it
    report ``"file"``.
    """

    def __init__(
        self,
        path: str | os.PathLike,
        *,
        loop: bool = False,
        channel: int | None = None,
    ) -> None:
        from ..io.sigmf_io import SigmfReader  # lazy: keeps ``antsdr_toolkit.device`` light

        self._reader: SigmfReader = SigmfReader(path, mmap=True)
        self._loop = bool(loop)
        n_channels = self._reader.n_channels
        if channel is not None:
            channel = int(channel)
            if not 0 <= channel < n_channels:
                raise ValueError(
                    f"channel {channel} out of range for a {n_channels}-channel recording"
                )
        self._channel = channel

        info = self._reader.info
        if "core:hw" not in self._reader.metadata.get("global", {}):
            info = info.replace(hardware="file")
        if channel is not None:
            info = info.replace(rx_channels=(info.rx_channels[channel],))
        self._info = info
        self._pos = 0
        self._closed = False

    # -- metadata -----------------------------------------------------------
    @property
    def info(self) -> StreamInfo:
        return self._info

    @property
    def metadata(self) -> dict[str, Any]:
        """Full SigMF metadata document (annotations carry ground-truth labels)."""
        return self._reader.metadata

    @property
    def path(self) -> os.PathLike:
        return self._reader.data_path

    @property
    def loop(self) -> bool:
        return self._loop

    @property
    def n_samples(self) -> int:
        """Samples per channel in the recording."""
        return self._reader.n_samples

    @property
    def duration_s(self) -> float:
        return self.n_samples / self._info.sample_rate_hz

    @property
    def position(self) -> int:
        """Index of the next sample :meth:`read` will return."""
        return self._pos

    @property
    def remaining(self) -> int:
        """Samples left before the end of the recording (ignores looping)."""
        return max(self.n_samples - self._pos, 0)

    def seek(self, sample_index: int) -> None:
        """Move the read position; wraps modulo the length when looping."""
        n = self.n_samples
        if self._loop and n > 0:
            sample_index %= n
        if not 0 <= sample_index <= n:
            raise ValueError(f"sample_index {sample_index} outside [0, {n}]")
        self._pos = int(sample_index)

    # -- streaming ----------------------------------------------------------
    def read(self, n_samples: int) -> np.ndarray:
        if self._closed:
            raise ValueError("source is closed")
        if n_samples <= 0:
            raise ValueError(f"n_samples must be positive, got {n_samples}")
        n_total = self.n_samples
        if not self._loop or n_total == 0:
            chunk = self._reader.read(self._pos, n_samples)
            self._pos += chunk.shape[-1]
            return self._select(chunk)

        pieces: list[np.ndarray] = []
        remaining = n_samples
        while remaining > 0:
            if self._pos >= n_total:
                self._pos = 0
            chunk = self._reader.read(self._pos, remaining)
            got = chunk.shape[-1]
            self._pos += got
            remaining -= got
            pieces.append(chunk)
        out = pieces[0] if len(pieces) == 1 else np.concatenate(pieces, axis=-1)
        return self._select(out)

    def _select(self, chunk: np.ndarray) -> np.ndarray:
        if self._channel is None or chunk.ndim == 1:
            return chunk
        return np.ascontiguousarray(chunk[self._channel])

    def close(self) -> None:
        if not self._closed:
            self._reader.close()
            self._closed = True

    def __repr__(self) -> str:
        return (
            f"SigmfFileSource({os.fspath(self.path)!r}, loop={self._loop}, "
            f"channel={self._channel}, n_samples={self.n_samples})"
        )
