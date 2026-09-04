"""Stage-1 energy/spectral detector (unsupervised).

Keys on signal *shape*, not content, so it catches even encrypted O4 / analog FPV.
Produces a bounded detection_probability plus the RF context the server path wants.
Thresholds are tuned/validated against the public datasets (see plan); nothing here
needs training. Stage-2 classification and stage-3 DroneID decode build on this.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

from ..dsp.spectrogram import Spectrogram


@dataclass
class Detection:
    score: float                 # detection_probability, 0..1
    snr_db: float
    rssi_dbm: float              # approximate; HackRF power is uncalibrated (dBFS + offset)
    peak_freq_mhz: float
    occupied_bw_mhz: float
    burst_count: int
    cadence_ms: float | None     # inter-burst period, if periodic
    signature_class: str         # dji_ocusync | wifi_drone | fpv_analog | noise

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _estimate_cadence_ms(power_per_slice: np.ndarray, slice_dt_s: float) -> float | None:
    """Dominant inter-burst period via autocorrelation of the time envelope."""
    x = power_per_slice - power_per_slice.mean()
    if np.allclose(x, 0):
        return None
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    # Ignore the zero-lag peak; look for the first strong secondary peak.
    lo = max(1, int(0.05 / slice_dt_s))     # >= 50 ms apart
    if lo >= len(ac):
        return None
    seg = ac[lo:]
    k = int(np.argmax(seg))
    if seg[k] < 0.3:                          # not convincingly periodic
        return None
    return (lo + k) * slice_dt_s * 1000.0


def _classify(occupied_bw_mhz: float, snr_db: float, cadence_ms: float | None) -> str:
    if snr_db < 6.0:
        return "noise"
    droneid_cadence = cadence_ms is not None and 300.0 <= cadence_ms <= 1000.0
    if occupied_bw_mhz >= 6.0 and droneid_cadence:
        return "dji_ocusync"
    if occupied_bw_mhz >= 6.0:
        return "fpv_analog" if occupied_bw_mhz >= 18.0 else "dji_ocusync"
    if 0.5 <= occupied_bw_mhz < 6.0:
        return "wifi_drone"
    return "noise"


def detect(spec: Spectrogram, center_freq_mhz: float,
           snr_threshold_db: float = 8.0, occupied_bw_ref_mhz: float = 10.0,
           gain_db: float = 40.0) -> Detection:
    power_db = spec.power_db                      # [T, F]
    n_time, n_freq = power_db.shape
    bin_hz = spec.sample_rate / n_freq

    # Time envelope: total linear power per STFT slice -> find burst slices first,
    # so a short burst is measured on the slices where it actually occurs rather
    # than averaged into silence across the whole window.
    lin = np.power(10.0, power_db / 10.0)
    p_t = lin.sum(axis=1)                          # [T]
    base = float(np.median(p_t))
    bursts = p_t > (base * 2.5)
    rising = np.count_nonzero(np.diff(bursts.astype(np.int8)) == 1)
    burst_count = int(rising + (1 if bursts[:1].any() else 0))

    # Signal PSD over burst slices vs noise PSD over the rest. Falls back to a
    # flat mean for a continuous (non-bursty) signal or pure noise.
    if bursts.any() and not bursts.all():
        sig_psd = power_db[bursts].mean(axis=0)       # [F]
        noise_floor = float(np.median(power_db[~bursts]))
    else:
        sig_psd = power_db.mean(axis=0)
        noise_floor = float(np.median(power_db))

    peak_db = float(sig_psd.max())
    snr_db = peak_db - noise_floor
    peak_bin = int(np.argmax(sig_psd))
    peak_freq_mhz = center_freq_mhz + spec.freqs_hz[peak_bin] / 1e6

    occupied = sig_psd > (noise_floor + 6.0)
    occupied_bw_mhz = float(np.count_nonzero(occupied) * bin_hz / 1e6)

    # Time step between STFT frames. Honour the actual hop the spectrogram was
    # computed with (it may be time-decimated for speed); fall back to the old
    # 50 %-overlap assumption for a Spectrogram built without one.
    hop = getattr(spec, "hop", None) or spec.freqs_hz.size // 2
    slice_dt_s = hop / spec.sample_rate
    cadence_ms = _estimate_cadence_ms(p_t, slice_dt_s)

    # Approximate RSSI: peak power is dB relative to full scale; offset by gain to
    # a rough dBm. Not calibrated -- good for relative comparison, flagged as such.
    rssi_dbm = peak_db - gain_db

    # Bounded score: signal strength + how drone-like the bandwidth is + cadence bonus.
    snr_c = float(np.clip((snr_db - snr_threshold_db) / 20.0, 0.0, 1.0))
    bw_c = float(np.clip(occupied_bw_mhz / occupied_bw_ref_mhz, 0.0, 1.0))
    cadence_bonus = 0.15 if (cadence_ms is not None and 300.0 <= cadence_ms <= 1000.0) else 0.0
    score = float(np.clip(0.5 * snr_c + 0.5 * bw_c + cadence_bonus, 0.0, 1.0))

    return Detection(
        score=score,
        snr_db=snr_db,
        rssi_dbm=rssi_dbm,
        peak_freq_mhz=peak_freq_mhz,
        occupied_bw_mhz=occupied_bw_mhz,
        burst_count=burst_count,
        cadence_ms=cadence_ms,
        signature_class=_classify(occupied_bw_mhz, snr_db, cadence_ms),
    )
