"""Live IQ from the ANTSDR E200 over Ethernet through pyadi-iio (passive receive only).

The E200 boots a PlutoSDR-compatible IIO firmware, so the stock pyadi-iio
classes drive it unchanged: ``adi.ad9364`` for one receive chain and
``adi.ad9361`` when the IPEX RX2 chain is wanted (which exists only after the
``2r2t`` boot-mode change, see :data:`antsdr_toolkit.hardware.FW_SETENV_2R2T`).
:class:`E200Source` wraps such an object behind the toolkit's
:class:`~antsdr_toolkit.device.base.SampleSource` contract.

Signal path and units
---------------------
* ``rx()`` in pyadi-iio returns the 12-bit ADC words of the ``cf-ad9361-lpc``
  core sign-extended to int16 and combined as ``I + 1j*Q`` (a ``complex128``
  array of integer counts, or a list of them with several channels).  Full
  scale is ``2**11 = 2048`` counts, so samples are converted to ``complex64``
  by multiplying with ``1/2048``: ``|x| == 1.0`` is 0 dBFS everywhere in the
  toolkit (same scaling as the Pluto beamformer scripts' ``dbfs()``).
* ``sample_rate_hz`` is the complex baseband rate written to
  ``sampling_frequency``; pyadi loads its 128-tap FIR (decimation 4 up to
  20 MSPS, 2 above) as part of the setter.  ``rf_bandwidth_hz`` programs the
  analog filter and defaults to the sample rate.
* Gain: ``gain_control_mode_chanX`` is written *before*
  ``rx_hardwaregain_chanX`` because pyadi silently drops the gain write unless
  the chain is already in ``'manual'`` mode (``adi/ad936x.py``).
  ``tx_hardwaregain_chanX`` is always set to -89 dB: this toolkit never
  transmits.
* Buffers: ``rx_buffer_size`` samples per ``rx()`` call; the buffer is created
  lazily on the first call and destroyed in :meth:`E200Source.close`.  A few
  buffers are discarded after configuration and after every retune because
  the DMA ring still holds samples captured before the LO settled.

Sources
-------
* pyadi-iio (ADI BSD): https://github.com/analogdevicesinc/pyadi-iio -
  ``adi/ad936x.py`` (attribute names, gain-mode gate, sample-rate floor),
  ``adi/rx_tx.py`` (``rx()`` return types, lazy buffer creation,
  ``rx_destroy_buffer``), ``adi/compat.py`` (missing-channel error text
  ``"Channel voltageN not found"`` at buffer creation).
* Pluto beamformer configuration sequence and 12-bit scaling (re-implemented,
  no code copied; the repo carries no licence):
  https://github.com/jonkraft/Pluto_Beamformer
* E200 facts (ports, rates, firmware, 2r2t): :mod:`antsdr_toolkit.hardware`
  and the MicroPhase repos cited there.

Verified vs inferred: attribute names, the gain-mode gate, the int16-count
``rx()`` output and the ``voltage2`` failure on 1r1t firmware are verified
in the pyadi sources; the number of buffers to discard (2 by default) is a
choice - the beamformer scripts discard 20 at 4096 samples, this driver
defaults to 2 x 262144.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any

import numpy as np

from .. import hardware as hw
from .base import IQ_DTYPE, SampleSource, StreamInfo

__all__ = ["ADI_IMPORT_HELP", "E200Source", "import_adi", "open_source", "probe",
           "two_channel_help"]

log = logging.getLogger(__name__)

#: Counts-to-full-scale factor for the 12-bit AD9363 (exact power of two).
_COUNTS_TO_FS = np.float32(1.0 / hw.E200.full_scale_counts)

ADI_IMPORT_HELP = (
    "pyadi-iio could not be imported ({exc}). The E200 driver needs the optional "
    "hardware extra and the native libiio library: "
    "pip install 'antsdr-toolkit[e200]'  (pyadi-iio + pylibiio bindings) and install "
    "libiio itself (Debian/Ubuntu: apt install libiio-dev or libiio0/libiio1; "
    "https://github.com/analogdevicesinc/libiio). Offline work (SigMF replay, "
    "synthetic scenes, DSP) does not need it."
)


def import_adi() -> ModuleType:
    """Import ``adi`` (pyadi-iio) lazily with an actionable error when it fails.

    ``import adi`` raises ``ImportError`` when the package is missing, but an
    ``AttributeError``/``OSError`` when ``pylibiio`` is installed without the
    native ``libiio`` shared library (undefined symbol at binding load); all
    three are reported as :class:`ImportError` carrying install instructions.
    """
    try:
        import adi  # deliberately lazy: hardware-only dependency
    except (ImportError, AttributeError, OSError) as exc:
        raise ImportError(ADI_IMPORT_HELP.format(exc=exc)) from exc
    return adi


def two_channel_help(uri: str, original: BaseException | None = None) -> str:
    """Explain why RX channel 1 (IPEX RX2) is missing and how to enable it."""
    detail = "" if original is None else f"\n(driver error: {original!r})"
    return (
        f"the E200 at {uri!r} exposes only RX channel 0 ({hw.E200.rf_port_name(0)}): the "
        "Pluto-compatible firmware boots in 1r1t mode by default, so the cf-ad9361-lpc "
        "scan channels voltage2/voltage3 (channel 1 = IPEX RX2) do not exist. Enable the "
        "second chain once on the device and reboot:\n"
        f"{hw.FW_SETENV_2R2T}{detail}"
    )


def _mentions_channel(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "voltage" in text or "channel" in text


class E200Source(SampleSource):
    """Pull IQ from an ANTSDR E200 over libiio; see the module docstring for the units.

    Args:
        uri: libiio context URI; the factory firmware answers on
            ``ip:192.168.1.10`` (``usb:`` is not available on the E200).
        sample_rate_hz: Complex sample rate (521 kSPS .. 61.44 MSPS single
            channel, 30.72 MSPS per channel with two). Rates above the 1 GbE
            host ceiling (20 / 10 MSPS) only log a warning.
        center_freq_hz: RX LO in Hz (70 MHz .. 6 GHz as the firmware allows).
        rf_bandwidth_hz: Analog filter bandwidth; ``None`` uses the sample rate.
        gain_mode: ``'manual'``, ``'slow_attack'``, ``'fast_attack'`` or ``'hybrid'``.
        gain_db: Manual RX gain in dB (ignored by the AGC modes).
        channels: Hardware chains to stream: ``(0,)`` SMA RX1, ``(1,)`` IPEX RX2
            or ``(0, 1)``. Anything but ``(0,)`` uses ``adi.ad9361`` and needs
            the 2r2t firmware mode.
        buffer_size: Samples per ``rx()`` buffer (per channel).
        discard_buffers: Buffers dropped after configuration and every retune.
        adi_module: Dependency injection of the ``adi`` package (tests pass a
            fake); ``None`` imports pyadi-iio lazily.
        firmware: Personality tag for ``core:hw`` (``hw_string(fw=...)``);
            ``None`` reads the context's ``fw_version`` and reports
            ``"pluto-iio <version>"``.

    Raises:
        ValueError: configuration outside the E200 limits, or two channels
            requested on a 1r1t firmware (message carries the fix).
        ImportError: pyadi-iio / libiio missing (message carries the fix).
        OSError: the device cannot be opened at ``uri``.
    """

    def __init__(
        self,
        uri: str = hw.E200.default_uri,
        *,
        sample_rate_hz: float,
        center_freq_hz: float,
        rf_bandwidth_hz: float | None = None,
        gain_mode: str = "manual",
        gain_db: float = 40.0,
        channels: Sequence[int] = (0,),
        buffer_size: int = 1 << 18,
        discard_buffers: int = 2,
        adi_module: ModuleType | None = None,
        firmware: str | None = None,
    ) -> None:
        chans = tuple(int(c) for c in channels)
        rate = float(sample_rate_hz)
        fc = float(center_freq_hz)
        bw = rate if rf_bandwidth_hz is None else float(rf_bandwidth_hz)
        # Validates every limit and raises ValueError before any hardware access.
        self.warnings: list[str] = hw.check_stream_config(
            rate, fc, channels=chans, rf_bandwidth_hz=bw, gain_mode=gain_mode, gain_db=gain_db
        )
        if int(buffer_size) <= 0:
            raise ValueError(f"buffer_size must be positive, got {buffer_size}")
        if int(discard_buffers) < 0:
            raise ValueError(f"discard_buffers must be >= 0, got {discard_buffers}")
        for message in self.warnings:
            log.warning("%s: %s", uri, message)

        adi = adi_module if adi_module is not None else import_adi()
        self._uri = str(uri)
        self._channels = chans
        self._two_chain = chans != (0,)
        self._gain_mode = str(gain_mode)
        self._gain_db = float(gain_db)
        self._buffer_size = int(buffer_size)
        self._discard = int(discard_buffers)
        self._remainder: np.ndarray | None = None
        self._closed = False
        self._sdr: Any = None

        driver = adi.ad9361 if self._two_chain else adi.ad9364
        try:
            self._sdr = driver(uri=self._uri)
        except Exception as exc:
            raise OSError(
                f"cannot open the E200 at {self._uri!r}: {exc}. Check the 1000BASE-T link, "
                f"the address (factory default {hw.E200.default_uri}) and that the "
                "Pluto-compatible (QSPI) firmware is booted"
            ) from exc
        try:
            self._configure(rate, fc, bw)
            self._flush(self._discard)
        except BaseException:
            self.close()
            raise

        fw = firmware if firmware else self._detect_firmware()
        ports = ", ".join(f"{c}={hw.E200.rf_port_name(c)}" for c in chans)
        gain_note = f"{self._gain_db:.1f} dB manual" if self._gain_mode == "manual" else (
            f"AGC {self._gain_mode}"
        )
        self._info = StreamInfo(
            sample_rate_hz=rate,
            center_freq_hz=fc,
            rx_channels=chans,
            gain_db=self._gain_db if self._gain_mode == "manual" else None,
            hardware=hw.hw_string(fw),
            description=f"{self._uri}; rx ports {ports}; gain {gain_note}; "
                        f"rx_buffer_size {self._buffer_size}",
            rf_bandwidth_hz=bw if bw < rate else None,
        )

    # -- configuration ------------------------------------------------------
    def _write(self, name: str, value: Any) -> None:
        """``setattr`` on the pyadi object, translating chain-1 failures into 2r2t advice."""
        try:
            setattr(self._sdr, name, value)
        except Exception as exc:
            if self._two_chain and (name.endswith("chan1") or _mentions_channel(exc)):
                raise ValueError(two_channel_help(self._uri, exc)) from exc
            raise

    def _require_second_chain(self) -> None:
        """Fail early when the RX data core lacks the channel-1 scan elements."""
        rxadc = getattr(self._sdr, "_rxadc", None)
        find = getattr(rxadc, "find_channel", None)
        if not callable(find):
            return  # unknown driver object: let buffer creation decide
        try:
            present = find(hw.RX_DATA_CHANNELS[1][0]) is not None
        except Exception:  # noqa: BLE001 - a probing failure must not mask the real error
            return
        if not present:
            raise ValueError(two_channel_help(self._uri))

    def _configure(self, rate: float, fc: float, bw: float) -> None:
        if self._two_chain:
            self._require_second_chain()
            self._write("rx_enabled_channels", list(self._channels))
        self._write("sample_rate", round(rate))
        self._write("rx_rf_bandwidth", round(bw))
        self._write("rx_lo", round(fc))
        for c in self._channels:
            # Mode first: pyadi ignores rx_hardwaregain_chanX unless already 'manual'.
            self._write(f"gain_control_mode_chan{c}", self._gain_mode)
            if self._gain_mode == "manual":
                self._write(f"rx_hardwaregain_chan{c}", self._gain_db)
        for c in (0, 1) if self._two_chain else (0,):
            self._write(f"tx_hardwaregain_chan{c}", hw.TX_GAIN_OFF_DB)  # never transmit
        self._write("rx_buffer_size", self._buffer_size)

    def _detect_firmware(self) -> str:
        attrs = getattr(getattr(self._sdr, "ctx", None), "attrs", None)
        version = None
        if isinstance(attrs, Mapping):
            raw = attrs.get("fw_version")
            if raw is not None:
                version = str(getattr(raw, "value", raw)).strip()
        return f"pluto-iio {version}" if version else "pluto-iio"

    # -- streaming ----------------------------------------------------------
    def _rx_buffer(self) -> np.ndarray:
        """One ``rx()`` buffer as complex64 at full scale 1.0, ``(n,)`` or ``(channels, n)``."""
        try:
            data = self._sdr.rx()
        except Exception as exc:
            if self._two_chain and _mentions_channel(exc):
                raise ValueError(two_channel_help(self._uri, exc)) from exc
            raise
        if isinstance(data, (list, tuple)):
            arr = np.stack([np.asarray(d) for d in data])
        else:
            arr = np.asarray(data)
        n_chan = len(self._channels)
        if arr.ndim == 2 and n_chan == 1:
            arr = arr[0]
        elif arr.ndim == 1 and n_chan > 1:
            raise RuntimeError(
                f"driver returned one channel but {n_chan} are enabled: {self._channels}"
            )
        elif arr.ndim == 2 and arr.shape[0] != n_chan:
            raise RuntimeError(f"driver returned {arr.shape[0]} channels, expected {n_chan}")
        return arr.astype(IQ_DTYPE) * _COUNTS_TO_FS

    def _flush(self, n_buffers: int) -> None:
        for _ in range(n_buffers):
            self._rx_buffer()

    def _check_open(self) -> None:
        if self._closed or self._sdr is None:
            raise ValueError("E200Source is closed")

    @property
    def info(self) -> StreamInfo:
        return self._info

    def read(self, n_samples: int) -> np.ndarray:
        """Return exactly ``n_samples`` per channel, spanning ``rx()`` buffers as needed."""
        n = int(n_samples)
        if n <= 0:
            raise ValueError(f"n_samples must be positive, got {n}")
        self._check_open()
        pieces: list[np.ndarray] = [] if self._remainder is None else [self._remainder]
        have = 0 if self._remainder is None else int(self._remainder.shape[-1])
        while have < n:
            buf = self._rx_buffer()
            pieces.append(buf)
            have += int(buf.shape[-1])
        data = pieces[0] if len(pieces) == 1 else np.concatenate(pieces, axis=-1)
        out = np.ascontiguousarray(data[..., :n])
        rest = data[..., n:]
        self._remainder = np.ascontiguousarray(rest) if rest.shape[-1] else None
        return out

    def retune(self, center_freq_hz: float) -> None:
        """Move the RX LO, drop the buffers captured during settling, update ``info``."""
        self._check_open()
        fc = float(center_freq_hz)
        hw.check_stream_config(
            self._info.sample_rate_hz, fc, channels=self._channels, host_ceiling=False
        )
        self._write("rx_lo", round(fc))
        self._remainder = None
        self._flush(self._discard)
        self._info = self._info.replace(center_freq_hz=fc)

    def close(self) -> None:
        """Destroy the RX buffer and the IIO context; idempotent."""
        if self._closed:
            return
        self._closed = True
        sdr, self._sdr = self._sdr, None
        self._remainder = None
        if sdr is None:
            return
        for method in ("rx_destroy_buffer", "close"):
            fn = getattr(sdr, method, None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001 - best effort teardown
                    log.debug("%s.%s() failed during close: %s", type(sdr).__name__, method, exc)

    # -- introspection ------------------------------------------------------
    @property
    def uri(self) -> str:
        return self._uri

    @property
    def sdr(self) -> Any:
        """The underlying pyadi-iio object (``None`` once closed)."""
        return self._sdr

    @property
    def channels(self) -> tuple[int, ...]:
        return self._channels

    @property
    def rf_ports(self) -> tuple[str, ...]:
        """Connector names of the streamed channels, in axis-0 order."""
        return tuple(hw.E200.rf_port_name(c) for c in self._channels)

    @property
    def gain_mode(self) -> str:
        return self._gain_mode

    def hardware_gain_db(self) -> tuple[float, ...]:
        """Current ``rx_hardwaregain_chanX`` per channel (the AGC's choice in AGC modes)."""
        self._check_open()
        out = []
        for c in self._channels:
            value = getattr(self._sdr, f"rx_hardwaregain_chan{c}")
            out.append(float(getattr(value, "value", value)))
        return tuple(out)

    def sigmf_extra_global(self) -> dict[str, Any]:
        """``antsdr:`` namespaced global fields describing this receiver for SigMF."""
        return {
            "antsdr:uri": self._uri,
            "antsdr:rf_ports": list(self.rf_ports),
            "antsdr:gain_mode": self._gain_mode,
            "antsdr:rx_buffer_size": self._buffer_size,
            "antsdr:adc_bits": hw.E200.adc_bits,
            "antsdr:transceiver": hw.E200.transceiver,
        }

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"E200Source({self._uri!r}, {state}, {self._info})"


def open_source(uri: str = hw.E200.default_uri, **kwargs: Any) -> E200Source:
    """Factory hook used by the sweep CLI: ``open_source(uri, sample_rate_hz=..., ...)``.

    Same keyword arguments as :class:`E200Source`; exists so callers that
    resolve the driver lazily by name find one stable entry point.
    """
    return E200Source(uri, **kwargs)


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------
def _attr_value(attrs: Any, name: str) -> str | None:
    """Read a libiio attribute value from a ``dict``-like ``attrs`` (v0 str or v1 Attr)."""
    if attrs is None:
        return None
    try:
        raw = attrs[name]
    except (KeyError, TypeError):
        return None
    return str(getattr(raw, "value", raw))


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


def _probe_iio(iio: ModuleType, uri: str) -> dict[str, Any]:
    ctx = iio.Context(uri)
    out: dict[str, Any] = {"uri": uri, "backend": "libiio"}
    attrs = getattr(ctx, "attrs", {}) or {}
    out["context_attrs"] = {str(k): str(getattr(v, "value", v)) for k, v in dict(attrs).items()}
    out["devices"] = [str(d.name) for d in getattr(ctx, "devices", [])]
    rx_names: list[str] = []
    rxadc = ctx.find_device(hw.IIO_DEVICE_NAMES["rx_data"])
    if rxadc is not None:
        rx_names = [
            str(getattr(c, "id", "")) for c in getattr(rxadc, "channels", [])
            if getattr(c, "scan_element", True)
        ]
    out["rx_data_channels"] = rx_names
    out["two_channel_capable"] = hw.RX_DATA_CHANNELS[1][0] in rx_names
    out["rx_lo_hz"] = out["sample_rate_hz"] = out["rf_bandwidth_hz"] = None
    out["gain_control_mode"] = {}
    out["rx_hardwaregain_db"] = {}
    phy = ctx.find_device(hw.IIO_DEVICE_NAMES["control"])
    if phy is not None:
        lo = phy.find_channel("altvoltage0", True)
        out["rx_lo_hz"] = _number(_attr_value(getattr(lo, "attrs", None), "frequency"))
        for c, name in hw.PHY_RX_CHANNELS.items():
            chan = phy.find_channel(name, False)
            if chan is None:
                continue
            attrs = getattr(chan, "attrs", None)
            if c == 0:
                out["sample_rate_hz"] = _number(_attr_value(attrs, "sampling_frequency"))
                out["rf_bandwidth_hz"] = _number(_attr_value(attrs, "rf_bandwidth"))
            out["gain_control_mode"][c] = _attr_value(attrs, "gain_control_mode")
            out["rx_hardwaregain_db"][c] = _number(_attr_value(attrs, "hardwaregain"))
    return out


def _probe_adi(adi: ModuleType, uri: str) -> dict[str, Any]:
    sdr = adi.ad9361(uri=uri)
    out: dict[str, Any] = {"uri": uri, "backend": "pyadi-iio"}
    try:
        ctx = getattr(sdr, "ctx", None)
        attrs = getattr(ctx, "attrs", {}) or {}
        out["context_attrs"] = {
            str(k): str(getattr(v, "value", v)) for k, v in dict(attrs).items()
        }
        out["devices"] = [str(d.name) for d in getattr(ctx, "devices", [])]
        rxadc = getattr(sdr, "_rxadc", None)
        find = getattr(rxadc, "find_channel", None)
        rx_names = [
            str(getattr(c, "id", "")) for c in getattr(rxadc, "channels", [])
            if getattr(c, "scan_element", True)
        ]
        out["rx_data_channels"] = rx_names
        if callable(find):
            out["two_channel_capable"] = find(hw.RX_DATA_CHANNELS[1][0]) is not None
        else:
            out["two_channel_capable"] = hw.RX_DATA_CHANNELS[1][0] in rx_names or None
        out["rx_lo_hz"] = _number(str(sdr.rx_lo))
        out["sample_rate_hz"] = _number(str(sdr.sample_rate))
        out["rf_bandwidth_hz"] = _number(str(sdr.rx_rf_bandwidth))
        out["gain_control_mode"] = {}
        out["rx_hardwaregain_db"] = {}
        for c in hw.PHY_RX_CHANNELS:
            try:
                out["gain_control_mode"][c] = str(getattr(sdr, f"gain_control_mode_chan{c}"))
                out["rx_hardwaregain_db"][c] = _number(
                    str(getattr(sdr, f"rx_hardwaregain_chan{c}"))
                )
            except Exception:  # noqa: BLE001 - chain 1 is absent on 1r1t firmware
                break
    finally:
        for method in ("rx_destroy_buffer", "close"):
            fn = getattr(sdr, method, None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001 - best effort teardown
                    log.debug("probe teardown %s() failed: %s", method, exc)
    return out


def probe(
    uri: str = hw.E200.default_uri,
    *,
    adi_module: ModuleType | None = None,
    iio_module: ModuleType | None = None,
) -> dict[str, Any]:
    """Describe the device at ``uri`` without streaming.

    Uses the ``iio`` (libiio) bindings when importable, else pyadi-iio. Keys:
    ``backend``, ``context_attrs`` (``fw_version``, ``hw_model``, ...),
    ``devices``, ``rx_data_channels`` (``cf-ad9361-lpc`` scan elements),
    ``two_channel_capable`` (``voltage2`` present = 2r2t firmware),
    ``rx_lo_hz``, ``sample_rate_hz``, ``rf_bandwidth_hz`` and per-chain
    ``gain_control_mode`` / ``rx_hardwaregain_db`` dictionaries; ``rf_ports``
    names the connector of each data channel found.
    """
    iio = iio_module
    if iio is None and adi_module is None:
        try:
            import iio as _iio  # optional native dependency, imported lazily
        except (ImportError, AttributeError, OSError):
            _iio = None
        iio = _iio
    if iio is not None:
        out = _probe_iio(iio, uri)
    else:
        out = _probe_adi(adi_module if adi_module is not None else import_adi(), uri)
    out["rf_ports"] = {
        c: hw.E200.rf_port_name(c)
        for c, names in hw.RX_DATA_CHANNELS.items()
        if names[0] in out.get("rx_data_channels", [])
    }
    out["hardware"] = hw.hw_string(
        "pluto-iio " + out["context_attrs"]["fw_version"]
        if out.get("context_attrs", {}).get("fw_version") else "pluto-iio"
    )
    return out
