"""Abstract sample-source interface shared by hardware, file and synthetic sources.

Conventions used throughout ``antsdr_toolkit``:

* IQ samples are ``np.complex64``. One channel is shape ``(n,)``; several
  channels are shape ``(channels, n)`` with axis 0 ordered like
  :attr:`StreamInfo.rx_channels`.
* Full scale is ``|x| == 1.0`` (0 dBFS). Fixed-point device formats are scaled
  into this range by the I/O layer, never by DSP code.
* ``sample_rate_hz`` and ``center_freq_hz`` are floats in Hz; complex baseband
  therefore spans ``center_freq_hz +/- sample_rate_hz / 2`` (or less when an
  explicit RF bandwidth is narrower).

Nothing in this module imports a hardware library.
"""

from __future__ import annotations

import abc
import dataclasses
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np

IQ_DTYPE = np.dtype(np.complex64)


def empty_iq(n_channels: int = 1) -> np.ndarray:
    """Return the canonical empty chunk a finite source yields once exhausted.

    Shape is ``(0,)`` for a single channel and ``(n_channels, 0)`` otherwise so
    ``chunk.shape[-1] == 0`` is the exhaustion test in both layouts.
    """
    if n_channels <= 1:
        return np.empty((0,), dtype=IQ_DTYPE)
    return np.empty((n_channels, 0), dtype=IQ_DTYPE)


@dataclass(frozen=True)
class StreamInfo:
    """Static description of an IQ sample stream.

    Attributes:
        sample_rate_hz: Complex sample rate in Hz. This is also the usable
            baseband span unless ``rf_bandwidth_hz`` narrows it.
        center_freq_hz: RF centre frequency in Hz that baseband 0 Hz maps to.
        rx_channels: Hardware receive channels present in the stream, in the
            order they appear along axis 0 of a ``(channels, n)`` array.
        gain_db: Receiver gain in dB when known; ``None`` for synthetic or
            file data without a recorded gain.
        hardware: Origin of the samples, e.g. ``"antsdr-e200"``,
            ``"synthetic"`` or ``"file"``.
        description: Free-form human readable note.
        rf_bandwidth_hz: Analogue/RF filter bandwidth in Hz when it is
            narrower than the sample rate; ``None`` means "as wide as the
            sample rate".
    """

    sample_rate_hz: float
    center_freq_hz: float
    rx_channels: tuple[int, ...] = (0,)
    gain_db: float | None = None
    hardware: str = "unknown"
    description: str = ""
    rf_bandwidth_hz: float | None = None

    def __post_init__(self) -> None:
        # Normalise types so instances built from JSON metadata compare equal to
        # hand-written ones (lists -> tuples, ints -> floats).
        object.__setattr__(self, "sample_rate_hz", float(self.sample_rate_hz))
        object.__setattr__(self, "center_freq_hz", float(self.center_freq_hz))
        object.__setattr__(self, "rx_channels", tuple(int(c) for c in self.rx_channels))
        if self.gain_db is not None:
            object.__setattr__(self, "gain_db", float(self.gain_db))
        if self.rf_bandwidth_hz is not None:
            object.__setattr__(self, "rf_bandwidth_hz", float(self.rf_bandwidth_hz))
        if not self.sample_rate_hz > 0.0:
            raise ValueError(f"sample_rate_hz must be positive, got {self.sample_rate_hz}")
        if not self.rx_channels:
            raise ValueError("rx_channels must name at least one channel")
        if self.rf_bandwidth_hz is not None and not self.rf_bandwidth_hz > 0.0:
            raise ValueError(f"rf_bandwidth_hz must be positive, got {self.rf_bandwidth_hz}")

    @property
    def bandwidth_hz(self) -> float:
        """Usable RF span in Hz: ``rf_bandwidth_hz`` if set, else the sample rate."""
        if self.rf_bandwidth_hz is None:
            return self.sample_rate_hz
        return self.rf_bandwidth_hz

    @property
    def n_channels(self) -> int:
        """Number of channels along axis 0 of a multi-channel chunk."""
        return len(self.rx_channels)

    @property
    def freq_lower_hz(self) -> float:
        """Absolute lower edge of the usable span in Hz."""
        return self.center_freq_hz - self.bandwidth_hz / 2.0

    @property
    def freq_upper_hz(self) -> float:
        """Absolute upper edge of the usable span in Hz."""
        return self.center_freq_hz + self.bandwidth_hz / 2.0

    def replace(self, **changes: Any) -> StreamInfo:
        """Return a copy with the given fields replaced (frozen-dataclass friendly)."""
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-serialisable dict including the derived ``bandwidth_hz``."""
        out = dataclasses.asdict(self)
        out["rx_channels"] = list(self.rx_channels)
        out["bandwidth_hz"] = self.bandwidth_hz
        return out

    def __str__(self) -> str:
        gain = "n/a" if self.gain_db is None else f"{self.gain_db:.1f} dB"
        return (
            f"{self.hardware}: {self.sample_rate_hz / 1e6:.3f} MS/s @ "
            f"{self.center_freq_hz / 1e6:.3f} MHz, bw {self.bandwidth_hz / 1e6:.3f} MHz, "
            f"ch {list(self.rx_channels)}, gain {gain}"
        )


class SampleSource(abc.ABC):
    """Pull-based IQ source: hardware receiver, file replay or synthetic scene.

    Contract for :meth:`read`:

    * returns ``np.complex64`` shaped ``(n,)`` or ``(channels, n)`` according to
      ``info.rx_channels``;
    * a finite source may return fewer than ``n`` samples only at its end and
      returns an empty array (``shape[-1] == 0``) once exhausted; live or
      looping sources always return exactly ``n`` samples.

    Sources are context managers and :meth:`close` must be idempotent.
    """

    @property
    @abc.abstractmethod
    def info(self) -> StreamInfo:
        """Static stream description (rate, centre frequency, channels...)."""

    @abc.abstractmethod
    def read(self, n_samples: int) -> np.ndarray:
        """Return up to ``n_samples`` complex64 samples per channel."""

    def retune(self, center_freq_hz: float) -> None:
        """Move the RF centre frequency; only tunable hardware overrides this."""
        raise NotImplementedError(f"{type(self).__name__} does not support retuning")

    def close(self) -> None:
        """Release resources; safe to call more than once."""
        return

    def iter_chunks(self, n_samples: int) -> Iterator[np.ndarray]:
        """Yield successive :meth:`read` results until an empty chunk is returned."""
        if n_samples <= 0:
            raise ValueError(f"n_samples must be positive, got {n_samples}")
        while True:
            chunk = self.read(n_samples)
            if chunk.shape[-1] == 0:
                return
            yield chunk

    def __enter__(self) -> SampleSource:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False
