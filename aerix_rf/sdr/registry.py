"""Backend name -> factory + availability probe.

``make_source()`` (in ``capture.py``) and ``aerix-rf info`` both go through this
table instead of hardcoding a HackRF-only backend chain, so a new SDR (ANTSDR's
iio path, T4; bladeRF; USRP; ...) is one new entry here plus a new adapter in
``capture.py`` -- no branching added to ``make_source``.

Import discipline: importing this module must NOT require any optional hardware
library (ctypes libhackrf, SoapySDR, python-iio, ...) to be installed. Every
probe/factory does its own import lazily, inside the function body.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable

from ..config import Config
from .antsdr_iio import antsdr_iio_capabilities
from .capture import (
    IQSource,
    ReceiverCapabilities,
    FileIQSource,
    SimSource,
    LibHackRFSource,
    HackrfTransferSource,
    HackRFSource,
    hackrf_capabilities,
    sim_capabilities,
)


@dataclass(frozen=True)
class BackendEntry:
    name: str
    factory: Callable[[Config], IQSource]
    probe: Callable[[], tuple[bool, str]]
    # Static capabilities, known without opening hardware (None: unknown/depends
    # on the live device or on session metadata, e.g. "file").
    capabilities: ReceiverCapabilities | None = None


# --- probes ----------------------------------------------------------------

def _probe_libhackrf() -> tuple[bool, str]:
    import ctypes
    import ctypes.util
    path = ctypes.util.find_library("hackrf")
    if not path:
        return False, "libhackrf.so not found (install the `hackrf` package)"
    try:
        ctypes.CDLL(path)
    except OSError as exc:  # noqa: BLE001
        return False, f"libhackrf.so found but failed to load: {exc}"
    return True, "libhackrf.so loadable"


def _probe_hackrf_transfer() -> tuple[bool, str]:
    if shutil.which("hackrf_transfer"):
        return True, "hackrf_transfer on PATH"
    return False, "hackrf_transfer not on PATH (install the `hackrf` package)"


def _probe_soapy() -> tuple[bool, str]:
    try:
        import SoapySDR  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"SoapySDR python bindings not importable: {exc}"
    return True, "SoapySDR python bindings importable"


def _probe_file() -> tuple[bool, str]:
    return True, "no hardware required; needs --iq-file / cfg.iq_file to point at a recording"


def _probe_sim() -> tuple[bool, str]:
    return True, "no hardware required"


def _probe_antsdr_iio() -> tuple[bool, str]:
    # Only checks the python-iio import; deliberately does NOT open the network
    # context (that happens lazily in AntsdrIIOSource.__init__ / the factory
    # below), so `aerix-rf info` / auto-probing never blocks on an unreachable
    # ANTSDR box.
    try:
        import iio  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, (
            "python-iio (pylibiio) not importable (install with "
            f"`uv sync --extra antsdr` plus the libiio runtime): {exc}"
        )
    return True, "python-iio (pylibiio) importable"


# --- factories ---------------------------------------------------------------

def _make_libhackrf(cfg: Config) -> IQSource:
    return LibHackRFSource(cfg)


def _make_hackrf_transfer(cfg: Config) -> IQSource:
    return HackrfTransferSource(cfg)


def _make_soapy(cfg: Config) -> IQSource:
    return HackRFSource(cfg)


def _make_file(cfg: Config) -> IQSource:
    return FileIQSource(cfg)


def _make_sim(cfg: Config) -> IQSource:
    return SimSource(cfg)


def _make_antsdr_iio(cfg: Config) -> IQSource:
    from .antsdr_iio import AntsdrIIOSource

    # URI / profile / gain-mode go through Config now (CLI --antsdr-uri /
    # --antsdr-profile / --gain-mode, env AERIX_RF_ANTSDR_* as fallback --
    # see Config.from_env()); "" means "let the backend use its own default".
    # sample_rate is only passed through when the caller explicitly asked for
    # one (cfg.sample_rate_requested) -- otherwise this fixed-rate-profile
    # backend picks its own rate from the profile, never Config's HackRF-ish
    # 20e6 dataclass default.
    return AntsdrIIOSource(
        uri=cfg.antsdr_uri or None,
        profile=cfg.antsdr_profile or None,
        sample_rate=cfg.sample_rate if cfg.sample_rate_requested else None,
        center_freq_hz=cfg.center_freq_mhz * 1e6,
        gain_mode=cfg.gain_mode,
        gain_db=cfg.gain_db,
        window_seconds=cfg.window_s,
    )


# --- the table -----------------------------------------------------------------

REGISTRY: dict[str, BackendEntry] = {
    "libhackrf": BackendEntry("libhackrf", _make_libhackrf, _probe_libhackrf,
                              hackrf_capabilities("libhackrf")),
    "hackrf_transfer": BackendEntry("hackrf_transfer", _make_hackrf_transfer, _probe_hackrf_transfer,
                                    hackrf_capabilities("hackrf_transfer")),
    "soapy": BackendEntry("soapy", _make_soapy, _probe_soapy,
                          hackrf_capabilities("soapy")),
    "file": BackendEntry("file", _make_file, _probe_file, None),
    "sim": BackendEntry("sim", _make_sim, _probe_sim, sim_capabilities()),
    "antsdr_iio": BackendEntry("antsdr_iio", _make_antsdr_iio, _probe_antsdr_iio,
                              antsdr_iio_capabilities()),
}

# Documented order ``make_source(cfg)`` tries with no explicit --backend / cfg.sim /
# cfg.iq_file: continuous gap-free libhackrf first, then SoapySDR (also a
# continuous stream, if the bindings happen to be present), then the
# one-process-per-window, gapped hackrf_transfer fallback last. ANTSDR is
# deliberately NOT in this auto chain: it is a separate physical box on its own
# network URI, not something to silently fall back to when a HackRF is absent.
# It is still listed in ``REGISTRY`` (with a real availability probe) so
# `aerix-rf info` can show it and ``--backend antsdr_iio`` / ``AERIX_RF_BACKEND``
# can select it explicitly.
AUTO_ORDER: tuple[str, ...] = ("libhackrf", "soapy", "hackrf_transfer")
