"""Stage-1 energy/spectral detector (unsupervised) = RF *morphology*.

Keys on signal *shape*, not content, so it catches even encrypted O4 / analog FPV.
Produces a bounded detection_probability ("how strong / interesting is this RF")
plus the RF context the server path wants, and a ``morphology`` label that
describes the measured shape only:

    noise                          nothing above the floor
    narrowband_candidate           < 2 MHz occupied
    wideband_candidate             2-6 MHz occupied (bursty or continuous)
    burst_wideband_candidate       >= 6 MHz, bursty, not flat-topped
    ofdm_candidate                 >= 6 MHz, bursty, flat-topped (OFDM-like)
    fhss_candidate                 burst centroid hops around the band
    continuous_wideband_candidate  >= 6 MHz, on for most of the window
    analog_candidate               >= 18 MHz continuous (weak guess: analog FPV)
    unknown                        above the floor but no usable shape

Stage 1 makes NO identity claim: a 10-20 MHz OFDM blob is just as likely
ambient Wi-Fi as a drone link. Identity (``dji_ocusync`` / ``wifi_uas`` / ...)
is stage 2 (``aerix_rf.classify.model``); deterministic confirmation is stage 3
(protocol decode). ``Detection.signature_class`` is kept for backward
compatibility but is only ever ``"noise"`` or ``"unknown"`` here.

Thresholds are tuned/validated against the public datasets (see plan); nothing
here needs training. Runs at 1 Hz on a 20 Msps window: everything added beyond
the STFT is O(T*F) vectorised numpy at most, ~50 ms on the reference box.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

from ..dsp.spectrogram import Spectrogram

MORPHOLOGIES = (
    "noise", "narrowband_candidate", "wideband_candidate", "burst_wideband_candidate",
    "ofdm_candidate", "fhss_candidate", "continuous_wideband_candidate",
    "analog_candidate", "unknown",
)

# Shape thresholds (MHz / ratios). Kept as module constants so tests and the
# stage-2 rules can reference the same numbers.
NOISE_SNR_DB = 6.0            # below this the window is "noise"
NARROWBAND_MAX_MHZ = 2.0      # < this  -> narrowband_candidate
WIDEBAND_MIN_MHZ = 6.0        # >= this -> *_wideband / ofdm candidates
ANALOG_MIN_MHZ = 18.0         # >= this and continuous -> analog_candidate
CONTINUOUS_DUTY = 0.8         # duty cycle above which the emitter is "continuous"
FLAT_TOP_SPREAD_DB = 6.0      # p90-p10 of the in-band PSD below this = flat-topped
FHSS_MIN_BURSTS = 4           # need this many bursts to call a hop pattern
FHSS_MIN_SPREAD_MHZ = 1.0     # centroid spread must exceed this ...
FHSS_SPREAD_VS_BW = 0.5       # ... and this fraction of the union occupied bw
_MAX_BURST_RUNS = 64          # cap per-burst work (bounded cost per window)


@dataclass
class Detection:
    score: float                 # detection_probability, 0..1 -- RF strength/interest, NOT "is a drone"
    snr_db: float
    rssi_dbm: float              # approximate; HackRF power is uncalibrated (dBFS + offset)
    peak_freq_mhz: float
    occupied_bw_mhz: float
    burst_count: int
    cadence_ms: float | None     # inter-burst period, if periodic
    signature_class: str         # backward-compat only: "noise" | "unknown" (identity is stage 2)
    morphology: str = "unknown"  # one of MORPHOLOGIES (stage-1 shape vocabulary)
    duty_cycle: float = 0.0      # fraction of STFT slices with the occupied band active

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


def _burst_runs(bursts: np.ndarray) -> list[tuple[int, int]]:
    """(start, stop) slice indices of each contiguous burst run, capped."""
    d = np.diff(bursts.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(d == 1)
    stops = np.flatnonzero(d == -1)
    return list(zip(starts[:_MAX_BURST_RUNS].tolist(), stops[:_MAX_BURST_RUNS].tolist()))


def _hop_spread_mhz(lin: np.ndarray, bursts: np.ndarray, freqs_hz: np.ndarray,
                    noise_lin: float) -> float | None:
    """Spread (max-min) of the power centroid across bursts, in MHz.

    A fixed-frequency burst train (OcuSync, Wi-Fi) keeps its centroid put; an
    FHSS link (Bluetooth, many RC links) moves it by several MHz per burst.
    Only touches the burst slices, so cost is bounded by the burst duty cycle.
    """
    runs = _burst_runs(bursts)
    if len(runs) < FHSS_MIN_BURSTS:
        return None
    f_mhz = freqs_hz / 1e6
    cents = []
    for a, b in runs:
        p = lin[a:b].mean(axis=0) - noise_lin
        np.clip(p, 0.0, None, out=p)
        tot = float(p.sum())
        if tot <= 0.0:
            continue
        cents.append(float((p * f_mhz).sum() / tot))
    if len(cents) < FHSS_MIN_BURSTS:
        return None
    return float(max(cents) - min(cents))


def _morphology(*, snr_db: float, occupied_bw_mhz: float, n_occupied: int,
                burst_count: int, duty_cycle: float, flat_top: bool,
                hop_spread_mhz: float | None) -> str:
    """Shape -> stage-1 vocabulary. No identity claim is made here."""
    if snr_db < NOISE_SNR_DB:
        return "noise"
    if n_occupied == 0:
        return "unknown"
    if (hop_spread_mhz is not None and burst_count >= FHSS_MIN_BURSTS
            and hop_spread_mhz >= FHSS_MIN_SPREAD_MHZ
            and hop_spread_mhz >= FHSS_SPREAD_VS_BW * occupied_bw_mhz):
        return "fhss_candidate"
    continuous = duty_cycle > CONTINUOUS_DUTY
    if occupied_bw_mhz < NARROWBAND_MAX_MHZ:
        return "narrowband_candidate"
    if occupied_bw_mhz < WIDEBAND_MIN_MHZ:
        return "wideband_candidate"
    if continuous:
        return "analog_candidate" if occupied_bw_mhz >= ANALOG_MIN_MHZ \
            else "continuous_wideband_candidate"
    if burst_count >= 1:
        return "ofdm_candidate" if flat_top else "burst_wideband_candidate"
    # Wideband, above the floor, but neither continuous nor resolvable bursts.
    return "wideband_candidate"


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

    # Signal PSD over burst slices vs noise PSD over the rest. For a continuous
    # emitter (or pure noise) there are no "burst" slices, so the floor is taken
    # as a low percentile of the time-averaged PSD: the median would sit ON a
    # wideband emitter's plateau and hide it entirely.
    bursty = bool(bursts.any() and not bursts.all())
    if bursty:
        # Average *linear* power over the burst slices, then dB: a hopper that
        # lights each bin only 1/N of the time still shows up (a mean of dB
        # values would bury it at the noise level).
        sig_psd = 10.0 * np.log10(lin[bursts].mean(axis=0) + 1e-12)      # [F]
        noise_floor = float(np.median(power_db[~bursts]))
        quiet = ~bursts                               # per-bin linear noise level, from p_t (no copy)
        noise_lin = float(p_t[quiet].sum() / (np.count_nonzero(quiet) * n_freq))
    else:
        sig_psd = power_db.mean(axis=0)
        noise_floor = float(np.percentile(sig_psd, 5.0))
        noise_lin = float(np.power(10.0, noise_floor / 10.0)) * 1.78   # mean-of-dB -> linear mean

    peak_db = float(sig_psd.max())
    snr_db = peak_db - noise_floor
    peak_bin = int(np.argmax(sig_psd))
    peak_freq_mhz = center_freq_mhz + spec.freqs_hz[peak_bin] / 1e6

    occupied = sig_psd > (noise_floor + 6.0)
    n_occupied = int(np.count_nonzero(occupied))
    occupied_bw_mhz = float(n_occupied * bin_hz / 1e6)

    # Duty cycle: fraction of slices where the occupied band carries > 2x (3 dB)
    # its expected noise power. Distinguishes a 3 ms/600 ms burst train (~0.005)
    # from a continuous emitter (~1.0). Pure noise has no occupied band -> 0.
    if n_occupied > 0 and snr_db >= NOISE_SNR_DB:
        p_occ_t = lin @ occupied.astype(lin.dtype)  # [T]; mat-vec beats a column gather ~20x
        duty_cycle = float(np.count_nonzero(p_occ_t > 2.0 * noise_lin * n_occupied) / n_time)
    else:
        duty_cycle = 0.0

    # Flat-topped in-band PSD (OFDM-like) vs peaky (carrier + sidebands, analog).
    if n_occupied >= 4:
        band = sig_psd[occupied]
        flat_top = bool(np.percentile(band, 90.0) - np.percentile(band, 10.0) < FLAT_TOP_SPREAD_DB)
    else:
        flat_top = False

    # Frequency hopping: centroid movement between bursts (bounded cost).
    hop_spread = _hop_spread_mhz(lin, bursts, spec.freqs_hz, noise_lin) if bursty else None

    # Time step between STFT frames. Honour the actual hop the spectrogram was
    # computed with (it may be time-decimated for speed); fall back to the old
    # 50 %-overlap assumption for a Spectrogram built without one.
    hop = getattr(spec, "hop", None) or spec.freqs_hz.size // 2
    slice_dt_s = hop / spec.sample_rate
    cadence_ms = _estimate_cadence_ms(p_t, slice_dt_s)

    # Approximate RSSI: peak power is dB relative to full scale; offset by gain to
    # a rough dBm. Not calibrated -- good for relative comparison, flagged as such.
    rssi_dbm = peak_db - gain_db

    # Bounded score: signal strength + bandwidth interest + cadence bonus. This is
    # "how strong/interesting is this RF", not "is it a drone".
    snr_c = float(np.clip((snr_db - snr_threshold_db) / 20.0, 0.0, 1.0))
    bw_c = float(np.clip(occupied_bw_mhz / occupied_bw_ref_mhz, 0.0, 1.0))
    cadence_bonus = 0.15 if (cadence_ms is not None and 300.0 <= cadence_ms <= 1000.0) else 0.0
    score = float(np.clip(0.5 * snr_c + 0.5 * bw_c + cadence_bonus, 0.0, 1.0))

    morphology = _morphology(snr_db=snr_db, occupied_bw_mhz=occupied_bw_mhz,
                             n_occupied=n_occupied, burst_count=burst_count,
                             duty_cycle=duty_cycle, flat_top=flat_top,
                             hop_spread_mhz=hop_spread)

    return Detection(
        score=score,
        snr_db=snr_db,
        rssi_dbm=rssi_dbm,
        peak_freq_mhz=peak_freq_mhz,
        occupied_bw_mhz=occupied_bw_mhz,
        burst_count=burst_count,
        cadence_ms=cadence_ms,
        # Stage 1 makes no identity claim; stage 2 (classify.model) does.
        signature_class="noise" if morphology == "noise" else "unknown",
        morphology=morphology,
        duty_cycle=duty_cycle,
    )
