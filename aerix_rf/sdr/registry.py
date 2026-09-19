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

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from typing import Callable

from ..config import Config
from .antsdr_iio import antsdr_iio_capabilities
from .antsdr_iio_device import BUFFER_SAMPLES, IQ_FULL_SCALE, resolve_profile
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
from .uhd_device import DEFAULT_SAMPLE_RATE as UHD_DEFAULT_SAMPLE_RATE, antsdr_uhd_capabilities


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


# T8: ANTSDR/UHD (MicroPhase ``uhd-antsdr`` fork). Env vars a user sets by
# running ``source ~/rf-tools/uhd-antsdr/ENV.sh`` before starting this
# process -- forwarded EXPLICITLY (not just inherited via ``os.environ``) to
# whatever child interpreter actually opens the device, because that
# interpreter is normally NOT ``sys.executable`` (see ``_resolve_uhd_python``)
# and this makes exactly what crosses the process boundary reviewable/testable
# instead of "whatever happened to be in this process's env".
_UHD_ENV_PASSTHROUGH = ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "UHD_IMAGES_DIR")


def _resolve_uhd_python() -> str:
    """The python interpreter that can ``import uhd``: ``$AERIX_RF_UHD_PYTHON``
    if set, else ``$UHD_ANTSDR_PYTHON`` (the var ``uhd-antsdr/ENV.sh`` itself
    exports), else this process's own interpreter (will fail the probe/import
    on a host that never installed the fork's bindings into it)."""
    return (
        os.environ.get("AERIX_RF_UHD_PYTHON")
        or os.environ.get("UHD_ANTSDR_PYTHON")
        or sys.executable
    )


def _uhd_child_env() -> dict:
    env = dict(os.environ)
    for key in _UHD_ENV_PASSTHROUGH:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _probe_antsdr_uhd_proc() -> tuple[bool, str]:
    """Availability = the CONFIGURED CHILD interpreter can ``import uhd``,
    checked in a real subprocess (never this process's own interpreter,
    which is ordinarily a plain venv without the ``uhd-antsdr`` fork's
    bindings) -- unlike ``_probe_antsdr_iio``, an in-process ``import`` here
    would test the wrong python and give a false negative on an otherwise
    healthy setup."""
    python = _resolve_uhd_python()
    try:
        result = subprocess.run(
            [python, "-c", "import uhd"], env=_uhd_child_env(),
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run {python!r} to probe `import uhd`: {exc}"
    if result.returncode == 0:
        return True, f"`import uhd` OK in {python!r}"
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"exit code {result.returncode}"
    return False, (
        f"`import uhd` failed in {python!r} ({reason}); set $AERIX_RF_UHD_PYTHON to the "
        "uhd-antsdr fork's interpreter (see ~/rf-tools/uhd-antsdr/ENV.sh, $UHD_ANTSDR_PYTHON)"
    )


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


def _make_antsdr_proc(cfg: Config) -> IQSource:
    from .process_source import ProcessIQSource

    # Same URI/profile resolution _make_antsdr_iio uses (Config already falls
    # back to $AERIX_RF_ANTSDR_URI / $AERIX_RF_ANTSDR_PROFILE in from_env());
    # re-exported into the environment so the producer SUBPROCESS -- which
    # reads those two env vars itself, inside AntsdrIioDevice.__init__ (see
    # antsdr_iio_device.py) -- also sees an explicit --antsdr-uri/--antsdr-profile
    # CLI flag, not only whatever the env var already was when this process
    # started.
    if cfg.antsdr_uri:
        os.environ["AERIX_RF_ANTSDR_URI"] = cfg.antsdr_uri
    if cfg.antsdr_profile:
        os.environ["AERIX_RF_ANTSDR_PROFILE"] = cfg.antsdr_profile

    # producer_main's antsdr_iio source does not (yet) support an "unset ->
    # let the device pick its own profile rate" sentinel over argv: whatever
    # --rate value ``ProcessIQSource`` passes is treated by
    # ``AntsdrIioDevice`` as an explicit override (see its docstring). Resolve
    # the same value ``_make_antsdr_iio`` would let the backend pick for
    # itself (the profile's own rate) up front here instead, so the ring/
    # window sizing this consumer needs before spawning the producer matches
    # what the device will actually run at.
    profile = resolve_profile(cfg.antsdr_profile or None)
    sample_rate = cfg.sample_rate if cfg.sample_rate_requested else float(profile["sample_rate"])

    return ProcessIQSource(
        source_type="antsdr_iio",
        sample_rate=sample_rate,
        center_freq_hz=cfg.center_freq_mhz * 1e6,
        chunk_samples=BUFFER_SAMPLES,
        full_scale=IQ_FULL_SCALE,
        window_seconds=cfg.window_s,
    )


def _make_antsdr_uhd_proc(cfg: Config) -> IQSource:
    from .process_source import ProcessIQSource
    from .uhd_device import IQ_FULL_SCALE as UHD_IQ_FULL_SCALE

    # Same "explicit request wins, otherwise the backend's own fixed default"
    # rule _make_antsdr_proc applies to antsdr_iio's profile rate: this fork's
    # canonical rate (uhd_device.DEFAULT_SAMPLE_RATE) needs no resampling, so
    # only override it when the caller actually asked (--sample-rate /
    # $AERIX_RF_SAMPLE_RATE), never with Config's HackRF-ish 20e6 dataclass
    # default.
    sample_rate = cfg.sample_rate if cfg.sample_rate_requested else UHD_DEFAULT_SAMPLE_RATE

    return ProcessIQSource(
        source_type="uhd",
        sample_rate=sample_rate,
        center_freq_hz=cfg.center_freq_mhz * 1e6,
        full_scale=UHD_IQ_FULL_SCALE,
        window_seconds=cfg.window_s,
        python_executable=_resolve_uhd_python(),
        env=_uhd_child_env(),
        extra_args=["--uhd-gain-db", repr(cfg.gain_db)],
    )


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
    # T7c: the same ANTSDR/AD9361 device as "antsdr_iio", but read through the
    # acquisition-producer OS process + shared-memory ring (process_source.py)
    # instead of an in-process thread. ``_probe_antsdr_proc`` is deliberately
    # the exact same probe as "antsdr_iio" (python-iio import only, no network
    # context): both backends need the same library, and this one's factory
    # only imports/opens the device inside the spawned subprocess, so probing
    # it here must not block on an unreachable box either.
    #
    # Device-side loss stays exactly as honest as "antsdr_iio"
    # (``loss_counter_available=False`` below -- the AD9361 firmware itself
    # has no overflow/sequence counter, see antsdr_iio.py). What's new here is
    # the HOST side: this backend's ring (``ShmRing``) makes every host-side
    # loss -- an overrun or a producer-declared chunk drop -- an EXACT count
    # (see process_source.py's module docstring, "host_loss_detection").
    # ``ReceiverCapabilities`` has no separate field for that (it is reported
    # per-window in ``IQWindow.health()``'s ``host_loss_detection``/
    # ``host_dropped_samples``/``host_overrun_events``, not as a static
    # capability), so this comment is the documentation of that fact.
    "antsdr_proc": BackendEntry("antsdr_proc", _make_antsdr_proc, _probe_antsdr_iio,
                                replace(antsdr_iio_capabilities(), backend="antsdr_proc")),
    # T8: the same physical ANTSDR E200/AD9361 box, read through the
    # MicroPhase ``uhd-antsdr`` fork's UHD python bindings instead of libiio
    # (``uhd_device.UhdDevice`` / ``producer_main.UhdProducerSource``), over
    # the same OS-process-producer plumbing as "antsdr_proc". Unlike the
    # libiio path, this fork's RX metadata carries a real device time_spec
    # AND an explicit overflow error code (see ``uhd_device.py``'s module
    # docstring), so ``antsdr_uhd_capabilities()`` reports
    # ``timestamp_quality="device_counter"``/``loss_counter_available=True``
    # where "antsdr_proc" (honestly) cannot. Its own probe -- NOT
    # ``_probe_antsdr_iio`` -- runs `import uhd` in the CONFIGURED CHILD
    # interpreter (see ``_probe_antsdr_uhd_proc``), since the bindings live in
    # a separate fork-specific venv, not this process's own interpreter.
    "antsdr_uhd_proc": BackendEntry("antsdr_uhd_proc", _make_antsdr_uhd_proc,
                                    _probe_antsdr_uhd_proc, antsdr_uhd_capabilities()),
}

# Documented order ``make_source(cfg)`` tries with no explicit --backend / cfg.sim /
# cfg.iq_file: continuous gap-free libhackrf first, then SoapySDR (also a
# continuous stream, if the bindings happen to be present), then the
# one-process-per-window, gapped hackrf_transfer fallback last. ANTSDR is
# deliberately NOT in this auto chain: it is a separate physical box on its own
# network URI, not something to silently fall back to when a HackRF is absent.
# It is still listed in ``REGISTRY`` (with a real availability probe) so
# `aerix-rf info` can show it and ``--backend antsdr_iio`` / ``AERIX_RF_BACKEND``
# can select it explicitly. Same for "antsdr_proc" (T7c, the OS-process
# producer path to the same physical box) and "antsdr_uhd_proc" (T8, the UHD
# fork path to that same box): also excluded here on purpose -- explicit
# --backend/$AERIX_RF_BACKEND selection only.
AUTO_ORDER: tuple[str, ...] = ("libhackrf", "soapy", "hackrf_transfer")
