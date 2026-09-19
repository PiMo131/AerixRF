"""Synthetic analog (FM composite-video) FPV downlink generator.

Ground-truth generator for validating `aerix_rf.detect.analog_fpv` against a
known carrier/shape, per ``docs/design/analog-fpv-detector.md`` S8. This is
**level-1 realism**: line/field sync timing and the colour-subcarrier
frequency follow the PAL/NTSC numbers in the design doc, and the luminance
content is a simple in-line ramp (broadband edge/ramp content rather than a
flat tone, so the modulated spectrum is not a pure comb) -- not a real
picture, and not accurate enough to validate a demodulator. Good enough to
exercise carrier estimation, occupied-bandwidth measurement, duty/FM-shape
morphology and the audio-subcarrier check.

Carrier convention (``carrier_convention``, T1 correction 2026-09-19). A
composite-video waveform is NOT symmetric about its blanking level (sync
tip -0.43, white +1.0), so where ``carrier_offset_hz`` is placed inside the
modulated spectrum is a modelling choice with a real evidence gap:

* ``"midband"`` (default) -- the sync-tip..white swing is centred on
  ``carrier_offset_hz`` (+-``deviation_hz``), i.e. the published channel
  frequency is the MID-BAND of the occupied spectrum. This matches how an
  analog receiver uses the channel table (it centres a symmetric IF filter
  there) and is the convention the sweep detector's edge-midpoint carrier
  estimator assumes.
* ``"blanking"`` -- the previous convention: blanking level (baseband 0,
  the dominant held level by line-time fraction) sits exactly at
  ``carrier_offset_hz`` as an FM residual-carrier line. Measured
  consequence: the occupied band then runs about -1.9..+4.0 MHz, so its
  -20 dB midpoint is **+0.90 MHz** away from ``carrier_offset_hz`` and any
  spectrum-shape carrier estimator is biased by that amount.

NOT project-measured: no real VTX spectrum has been captured to decide which
convention a real transmitter follows (see the design doc's open-evidence
list).

Occupied-bandwidth note (measured with a 4096-point Welch PSD binned to
500 kHz, ``audio_subcarriers=()``, PAL, ``deviation_hz=4e6``, see
``tests/test_analog_fpv.py``): ``deviation_hz`` is the ONE-SIDED peak FM
deviation, so the sync-tip..white swing is ``2*deviation_hz`` peak-to-peak;
the default 2.5 MHz (5 MHz p-p) sits mid-range in the design doc's own
"~4-8 MHz p-p" figure. Under ``"midband"`` that measures, on the DETECTOR's
representation (500 kHz bins, 3-bin smoothing, interpolated edges), to
occupied bandwidth **-20 dB: 5.6-6.0 MHz, -10 dB: 3.7-5.1 MHz** -- inside
the design doc's accepted windows (5-9 MHz / 3-7 MHz). Reading the doc's
4-8 MHz as ONE-SIDED instead (``deviation_hz=4e6``) gives 11.8 MHz at -20 dB
and falls outside those windows, so the two readings are not
interchangeable. A real camera measured ~9 MHz occupied in
``CHANNEL_DATABASE.md`` S4 (dB level unstated), i.e. between these two
readings -- an open evidence gap. Callers validating occupied bandwidth
should re-measure at their chosen ``deviation_hz``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["make_fm_video", "STANDARDS"]


@dataclass(frozen=True)
class _Standard:
    line_rate_hz: float
    field_rate_hz: float
    colour_subcarrier_hz: float


# Line/field rates and colour-subcarrier frequencies are standard broadcast
# constants (not project-measured); see docs/design/analog-fpv-detector.md S2.
STANDARDS = {
    "PAL": _Standard(line_rate_hz=15625.0, field_rate_hz=50.0,
                      colour_subcarrier_hz=4_433_618.75),
    "NTSC": _Standard(line_rate_hz=15734.264, field_rate_hz=59.94,
                       colour_subcarrier_hz=3_579_545.0),
}

_SYNC_FRAC = 0.08            # fraction of a line spent on the sync tip
_BACK_PORCH_FRAC = 0.12      # fraction of a line spent on the back porch (blanking)
_SYNC_LEVEL = -0.43          # IRE-like scale: 0 = blank, 1 = white, -0.43 = sync tip
_FIELD_SYNC_LINES = 3.0      # broadened sync tip for ~3 line-times once per field


def make_fm_video(fs: float, duration_s: float, *,
                   carrier_offset_hz: float = 0.0,
                   deviation_hz: float = 2.7e6,
                   standard: str = "PAL",
                   carrier_convention: str = "midband",
                   audio_subcarriers: tuple[float, ...] = (6.0e6, 6.5e6),
                   audio_level: float = 0.06,
                   snr_db: float | None = None,
                   seed: int | None = 0) -> np.ndarray:
    """Complex64 baseband IQ of a synthetic analog FM-video downlink.

    ``carrier_offset_hz`` places the (already FM-modulated) carrier at that
    baseband offset within the returned IQ -- use a negative value to
    simulate an offset-tuned dwell capture (see
    :func:`aerix_rf.detect.analog_fpv.dwell_confirm`). ``deviation_hz`` is
    the one-sided peak FM deviation (see module docstring). ``audio_subcarriers``
    are modelled as small fixed-amplitude tones riding on the carrier at
    ``carrier_offset_hz + f_audio`` -- enough to exercise a spectral
    audio-subcarrier check, not a real FM-subcarrier-of-audio chain.
    ``snr_db`` adds complex Gaussian noise referenced to the *signal's own*
    power (video + audio tones) if given; ``None`` returns a noise-free
    signal.
    """
    if standard not in STANDARDS:
        raise ValueError(f"unknown standard {standard!r}; expected one of {sorted(STANDARDS)}")
    std = STANDARDS[standard]
    n = int(round(fs * duration_s))
    if n <= 0:
        return np.zeros(0, dtype=np.complex64)
    t = np.arange(n, dtype=np.float64) / fs
    rng = np.random.default_rng(seed)

    # --- composite baseband (level-1 CVBS-like waveform) ---
    line_phase = (t * std.line_rate_hz) % 1.0
    field_phase = (t * std.field_rate_hz) % 1.0

    active = line_phase > (_SYNC_FRAC + _BACK_PORCH_FRAC)
    sync = np.where(line_phase <= _SYNC_FRAC, _SYNC_LEVEL, 0.0)

    # Luminance: a ramp 0..1 across the active portion of each line -- gives
    # the spectrum broadband ramp/edge content rather than a single tone.
    active_span = max(1e-9, 1.0 - _SYNC_FRAC - _BACK_PORCH_FRAC)
    active_phase = np.clip((line_phase - _SYNC_FRAC - _BACK_PORCH_FRAC) / active_span, 0.0, 1.0)
    luma = np.where(active, active_phase, 0.0)

    # Field sync: broaden/deepen the tip for a few line-times once per field.
    lines_per_field = std.line_rate_hz / std.field_rate_hz
    field_sync_frac = _FIELD_SYNC_LINES / lines_per_field
    sync = np.where(field_phase < field_sync_frac, _SYNC_LEVEL, sync)

    colour = 0.20 * np.sin(2 * np.pi * std.colour_subcarrier_hz * t) * np.where(active, 1.0, 0.0)

    baseband = sync + luma + colour
    # Never MEAN-subtracted (that would make the modulated spectrum's shape
    # depend on picture content). Two range normalisations, see the module
    # docstring: "midband" maps [min, max] -> [-1, +1] so the sync-tip..white
    # swing is symmetric about carrier_offset_hz; "blanking" divides by the
    # peak magnitude so baseband 0 (blanking) stays exactly on
    # carrier_offset_hz as a residual-carrier line, leaving the occupied band
    # asymmetric (-1.9..+4.0 MHz at the default deviation).
    if carrier_convention == "midband":
        b_lo, b_hi = float(np.min(baseband)), float(np.max(baseband))
        half = max(1e-9, 0.5 * (b_hi - b_lo))
        baseband = (baseband - 0.5 * (b_hi + b_lo)) / half
    elif carrier_convention == "blanking":
        peak = float(np.max(np.abs(baseband))) or 1.0
        baseband = baseband / peak
    else:
        raise ValueError(f"unknown carrier_convention {carrier_convention!r}; "
                         "expected 'midband' or 'blanking'")

    inst_freq = carrier_offset_hz + deviation_hz * baseband
    phase = 2.0 * np.pi * np.cumsum(inst_freq) / fs
    iq = np.exp(1j * phase).astype(np.complex128)

    for f_audio in audio_subcarriers:
        iq = iq + audio_level * np.exp(1j * 2.0 * np.pi * (carrier_offset_hz + f_audio) * t)

    if snr_db is not None:
        sig_power = float(np.mean(np.abs(iq) ** 2))
        noise_power = sig_power / (10.0 ** (snr_db / 10.0))
        noise = np.sqrt(noise_power / 2.0) * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        iq = iq + noise

    return iq.astype(np.complex64)
