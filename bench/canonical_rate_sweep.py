"""Synthetic validation bench for the canonical sample-rate decision.

Answers the question posed in docs/design/canonical-representation.md #10:
does moving the live/dataset canonical rate from the legacy 20 MS/s HackRF
window to 15.36 MS/s (or the 11.52 MS/s ANTSDR fallback) raise the SNR
required for a valid DroneID decode? Also quantifies the cs8-vs-cs12(-in-cs16)
storage-format dynamic-range loss called out in memo #4.

Usage:
    uv run python bench/canonical_rate_sweep.py --trials 20 --snr-min -2 \
        --snr-max 12 --step 1 --out bench/out/canonical_rate_sweep.json

Method (memo #10):
  * Bursts are synthesized at MASTER_RATE (an exact 4x multiple of the 15.36
    MHz canonical rate, so `decode._synth.make_encoded_burst`'s internal
    FFT/CP-schedule math stays exact) via `make_encoded_burst`, then AWGN is
    added at MASTER_RATE with a variance chosen so the noise power landing
    inside the OCCUPIED_BW_HZ occupied band gives the requested **in-band**
    SNR -- not a naive per-sample SNR, which would bias the 20 MS/s arm by
    10*log10(20/15.36) = 1.14 dB versus 15.36 MS/s (memo #10.1).
  * Each arm's IQ is produced by resampling that single noisy master-rate
    record down to the arm's own rate (scipy `resample_poly`, which supplies
    the anti-aliasing filter), then fed to `decode.droneid.decode_all(iq, fs)`
    unchanged -- the decoder resamples internally to its own working rate.
  * Random per-trial CFO (+-CFO_MAX_HZ) and a random pad_start/pad_end split
    at MASTER_RATE give both a random sub-sample timing offset (MASTER_RATE
    is far finer-grained than any arm's sample grid) and a random burst
    centre offset within the padded window.
  * A trial is a decode "success" if any decode_all() attempt is CRC-valid
    (level "C") *and* recovers the injected serial.

This script does not touch aerix_rf/sdr/ or aerix_rf/session/; quantisation
here is a local float round-trip through the same clip/round convention as
`aerix_rf.sdr.capture.to_cs8`/`to_cs16`, not a rewrite of those helpers.
"""

from __future__ import annotations

import argparse
import json
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from aerix_rf.decode import ofdm
from aerix_rf.decode._synth import make_encoded_burst
from aerix_rf.decode.droneid import decode_all

# --- physical constants ------------------------------------------------------

MASTER_RATE = 4.0 * ofdm.NOMINAL_SAMPLE_RATE  # 61.44 MS/s: exact 4x canonical.
OCCUPIED_BW_HZ = 9.015e6   # 601 x 15 kHz carrier grid; SNR is defined over this
                           # band (memo #10.1), not per input sample.
FIELDS = {"serial": "BENCHSERIAL0123"}

CFO_MAX_HZ = 3000.0        # random CFO, "a few kHz" per the task packet
STO_MARGIN_FRAC = 0.35     # random burst-centre / sub-sample offset, as a
                           # fraction of one burst length, applied at MASTER_RATE
BACKOFF_DB = 10.0          # manual-gain peak backoff before quantisation (memo #4)
# Out-of-band blocker: beyond the ±4.51 MHz DroneID occupied band but inside the
# 15.36 MS/s window (±7.68 MHz), so it stresses ADC/quantiser dynamic range rather
# than jamming subcarriers directly (architect decision 2026-09-18; was 3.0e6 in-band).
BLOCKER_OFFSET_HZ = 6.0e6
BLOCKER_DB_ABOVE_BURST = 30.0
# Realistic adjacent-channel blocker (rf-dsp 2026-09-18): a wideband OFDM-like
# emitter (Wi-Fi / another OcuSync channel) whose lower edge sits just outside the
# +-4.51 MHz DroneID band and whose upper part is clipped by the 15.36 MS/s window
# edge. Unlike the +30 dB CW this stresses spectral *selectivity* the way a real
# crowded 2.4 GHz window does, without being a single PSD-argmax-capturing tone.
WB_BLOCKER_OFFSET_HZ = 6.5e6
WB_BLOCKER_BW_HZ = 4.0e6
WB_BLOCKER_DB_ABOVE_BURST = 20.0

ARM_RATES = {
    "A_legacy_20msps": 20.0e6,
    "B_canonical_15p36msps": 15.36e6,
    "C_fallback_11p52msps": 11.52e6,
}

# label -> (arm_rate, quant "cs8"/"cs12"/None, blocker bool)
PROFILES: dict[str, tuple[float, str | None, str | bool]] = {
    "A_legacy_20msps": (20.0e6, None, False),
    "B_canonical_15p36msps": (15.36e6, None, False),
    "C_fallback_11p52msps": (11.52e6, None, False),
    # ANTSDR-IIO measured-sustainable candidates (2026-09-18 E200 runs, 25 s, kbufs 8,
    # zero errors): 12.288 MS/s ratio 1.0007; 13.44 MS/s ratio 1.0001 @ 53.8 MB/s.
    "C2_12p288msps": (12.288e6, None, False),
    "C3_13p44msps": (13.44e6, None, False),
    "B_cs8": (15.36e6, "cs8", False),
    "B_cs12": (15.36e6, "cs12", False),
    "B_cs8_blocker": (15.36e6, "cs8", "cw"),
    "B_cs12_blocker": (15.36e6, "cs12", "cw"),
    "B_wb_blocker": (15.36e6, None, "wb"),
    "B_cs12_wb_blocker": (15.36e6, "cs12", "wb"),
}


@dataclass
class TrialResult:
    label: str
    snr_db: float
    crc_ok: bool
    serial_ok: bool
    decode_s: float


def _band_limited_noise_sigma2(snr_db: float, master_rate: float,
                                occupied_bw_hz: float = OCCUPIED_BW_HZ) -> float:
    """Variance of full-band white AWGN at `master_rate` giving `snr_db` of
    in-band SNR against a unit-power burst whose entire energy already sits
    inside `occupied_bw_hz` (see module docstring / memo #10.1)."""
    snr_lin = 10.0 ** (snr_db / 10.0)
    return master_rate / (occupied_bw_hz * snr_lin)


def _make_master_burst(snr_db: float, seed: int):
    rng = np.random.default_rng(seed)
    cfo_hz = float(rng.uniform(-CFO_MAX_HZ, CFO_MAX_HZ))

    burst_len = ofdm.burst_length(MASTER_RATE)
    margin = max(1, int(round(STO_MARGIN_FRAC * burst_len)))
    pad_start = int(rng.integers(0, 2 * margin + 1))
    pad_end = 2 * margin - pad_start

    b = make_encoded_burst(FIELDS, sample_rate=MASTER_RATE, snr_db=None,
                            cfo_hz=cfo_hz, pad_start=pad_start, pad_end=pad_end,
                            seed=seed)
    sigma2 = _band_limited_noise_sigma2(snr_db, MASTER_RATE)
    noise_rng = np.random.default_rng([seed, 999])
    noise = (noise_rng.standard_normal(b.iq.size)
             + 1j * noise_rng.standard_normal(b.iq.size))
    noise *= np.sqrt(sigma2 / 2.0)
    iq = (b.iq.astype(np.complex128) + noise)
    return iq


def _resample_arm(master_iq: np.ndarray, arm_rate: float) -> np.ndarray:
    """Anti-alias-filtered resample from MASTER_RATE down to `arm_rate`.

    Relies on scipy `resample_poly`'s own polyphase anti-imaging/anti-aliasing
    filter as the front-end band-limiting step. NOTE: this is a proxy for the
    memo's 0.9xFs analog `rf_bandwidth` corner (D2), not a distinct explicit
    filter at that exact cutoff -- see hand-back note.
    """
    return ofdm.resample_to(master_iq, MASTER_RATE, arm_rate)


def _add_blocker(iq: np.ndarray, fs: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng([seed, 777])
    n = np.arange(iq.size)
    phase0 = rng.uniform(0, 2 * np.pi)
    amp = 10.0 ** (BLOCKER_DB_ABOVE_BURST / 20.0)  # burst is unit power (RMS 1)
    tone = amp * np.exp(1j * (2 * np.pi * BLOCKER_OFFSET_HZ / fs * n + phase0))
    return iq + tone


def _add_wb_blocker(iq: np.ndarray, fs: float, seed: int) -> np.ndarray:
    """Band-limited Gaussian (OFDM-like) adjacent-channel blocker, +20 dB."""
    rng = np.random.default_rng([seed, 778])
    n = iq.size
    x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)
    f = np.fft.fftfreq(n, d=1.0 / fs)
    lo = WB_BLOCKER_OFFSET_HZ - WB_BLOCKER_BW_HZ / 2.0
    hi = WB_BLOCKER_OFFSET_HZ + WB_BLOCKER_BW_HZ / 2.0
    mask = (f >= lo) & (f <= hi)
    x = np.fft.ifft(np.fft.fft(x) * mask)
    p = float(np.mean(np.abs(x) ** 2))
    if p <= 0:
        return iq
    amp = 10.0 ** (WB_BLOCKER_DB_ABOVE_BURST / 20.0)  # burst is unit power (RMS 1)
    return iq + x * (amp / np.sqrt(p))


def _apply_receiver_backoff(iq: np.ndarray, backoff_db: float = BACKOFF_DB) -> np.ndarray:
    """Emulate a manual-gain peak backoff before a fixed-full-scale ADC (memo
    #4/#D12): scale so the composite's peak sample sits `backoff_db` below
    full scale (1.0)."""
    peak = float(np.max(np.abs(iq))) if iq.size else 1.0
    if peak <= 0:
        return iq
    target_peak = 10.0 ** (-backoff_db / 20.0)
    return iq * (target_peak / peak)


def _quantize(iq: np.ndarray, full_scale: float) -> np.ndarray:
    """Round-trip through an integer ADC code of the given full scale (128 for
    cs8, 2048 for cs12-in-cs16 per memo D4/5), matching the clip/round
    convention of aerix_rf.sdr.capture.to_cs8/to_cs16 without importing the
    sdr module."""
    i = np.clip(np.round(iq.real * full_scale), -full_scale, full_scale - 1)
    q = np.clip(np.round(iq.imag * full_scale), -full_scale, full_scale - 1)
    return (i + 1j * q) / full_scale


def _run_trial(label: str, snr_db: float, trial_idx: int) -> TrialResult:
    arm_rate, quant, blocker = PROFILES[label]
    # A stable hash (not the salted builtin hash()) so seeds -- and therefore
    # results -- are reproducible across separate processes/runs regardless of
    # PYTHONHASHSEED or ProcessPoolExecutor worker startup.
    seed = zlib.crc32(f"{label}|{snr_db}|{trial_idx}".encode())

    master_iq = _make_master_burst(snr_db, seed)
    iq = _resample_arm(master_iq, arm_rate)
    if blocker == "wb":
        iq = _add_wb_blocker(iq, arm_rate, seed)
    elif blocker:
        iq = _add_blocker(iq, arm_rate, seed)
    if quant is not None:
        iq = _apply_receiver_backoff(iq)
        full_scale = 128.0 if quant == "cs8" else 2048.0
        iq = _quantize(iq, full_scale)
    iq = iq.astype(np.complex64)

    t0 = time.perf_counter()
    attempts = decode_all(iq, arm_rate)
    dt = time.perf_counter() - t0

    crc_ok = any(a.crc_ok for a in attempts)
    serial_ok = any(a.crc_ok and a.result is not None
                     and a.result.serial == FIELDS["serial"] for a in attempts)
    return TrialResult(label=label, snr_db=snr_db, crc_ok=crc_ok,
                        serial_ok=serial_ok, decode_s=dt)


def _interp_snr50(points: list[tuple[float, float]]) -> float | None:
    """Linear-interpolated SNR at which success fraction first reaches 0.5.
    `points` = sorted [(snr_db, success_frac), ...]."""
    if not points:
        return None
    if points[0][1] >= 0.5:
        return points[0][0]
    for (s0, f0), (s1, f1) in zip(points, points[1:]):
        if f0 < 0.5 <= f1:
            if f1 == f0:
                return s1
            return s0 + (0.5 - f0) * (s1 - s0) / (f1 - f0)
    return None  # never reached 0.5 in the swept range


def _interp_snr50_final(points: list[tuple[float, float]]) -> float | None:
    """SNR above which the success fraction *stays* >= 0.5 for the rest of the
    sweep. The plain first-crossing `_interp_snr50` is unsafe here: the measured
    serial-decode curve is non-monotonic (a ~0.5 plateau near 2-6 dB, a dip to
    ~0.2 near 7 dB, then the true knee at ~9-10 dB), so first-crossing reports
    the plateau, not the operating threshold (rf-dsp 2026-09-18)."""
    if not points:
        return None
    last_bad = None
    for i, (s_db, f) in enumerate(points):
        if f < 0.5:
            last_bad = i
    if last_bad is None:
        return points[0][0]
    if last_bad == len(points) - 1:
        return None  # never stays above 0.5 in the swept range
    s0, f0 = points[last_bad]
    s1, f1 = points[last_bad + 1]
    if f1 == f0:
        return s1
    return s0 + (0.5 - f0) * (s1 - s0) / (f1 - f0)


def run_sweep(trials: int, snr_values: list[float], labels: list[str] | None = None,
              max_workers: int | None = None) -> dict:
    labels = labels or list(PROFILES.keys())
    tasks = [(label, snr, t) for label in labels for snr in snr_values for t in range(trials)]

    results: list[TrialResult] = []
    if max_workers and max_workers > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            for r in ex.map(_run_trial, *zip(*tasks), chunksize=4):
                results.append(r)
    else:
        for args in tasks:
            results.append(_run_trial(*args))

    by_label: dict[str, dict[float, list[TrialResult]]] = {}
    for r in results:
        by_label.setdefault(r.label, {}).setdefault(r.snr_db, []).append(r)

    summary: dict[str, dict] = {}
    for label, by_snr in by_label.items():
        curve = []
        for snr in sorted(by_snr):
            trs = by_snr[snr]
            n = len(trs)
            crc_frac = sum(t.crc_ok for t in trs) / n
            serial_frac = sum(t.serial_ok for t in trs) / n
            mean_dt = sum(t.decode_s for t in trs) / n
            curve.append({"snr_db": snr, "n": n, "crc_frac": crc_frac,
                          "serial_frac": serial_frac, "mean_decode_s": mean_dt})
        pts = [(c["snr_db"], c["serial_frac"]) for c in curve]
        snr50 = _interp_snr50(pts)
        summary[label] = {"curve": curve, "snr50_db": snr50,
                          "snr50_final_db": _interp_snr50_final(pts),
                          "arm_rate_hz": PROFILES[label][0],
                          "quant": PROFILES[label][1], "blocker": PROFILES[label][2]}
    return summary


def _markdown_table(summary: dict) -> str:
    lines = ["| arm | rate (MS/s) | quant | blocker | SNR50 first (dB) | SNR50 final (dB) | mean decode (ms) |",
             "|---|---|---|---|---|---|---|"]
    for label, s in summary.items():
        snr50 = f"{s['snr50_db']:.2f}" if s["snr50_db"] is not None else "n/a"
        snr50f = (f"{s['snr50_final_db']:.2f}" if s.get("snr50_final_db") is not None
                  else "n/a")
        mean_dt = (sum(c["mean_decode_s"] for c in s["curve"]) / len(s["curve"]) * 1e3
                   if s["curve"] else float("nan"))
        lines.append(f"| {label} | {s['arm_rate_hz'] / 1e6:g} | {s['quant'] or '-'} | "
                     f"{s['blocker'] or '-'} | {snr50} | {snr50f} | {mean_dt:.1f} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--snr-min", type=float, default=-2.0)
    ap.add_argument("--snr-max", type=float, default=12.0)
    ap.add_argument("--step", type=float, default=1.0)
    ap.add_argument("--out", type=str, default="bench/out/canonical_rate_sweep.json")
    ap.add_argument("--workers", type=int, default=None,
                    help="process-pool workers (default: os.cpu_count())")
    ap.add_argument("--labels", type=str, default=None,
                    help="comma-separated subset of profile labels (default: all)")
    args = ap.parse_args()

    n_steps = int(round((args.snr_max - args.snr_min) / args.step)) + 1
    snr_values = [round(args.snr_min + i * args.step, 6) for i in range(n_steps)]
    labels = args.labels.split(",") if args.labels else None

    t0 = time.perf_counter()
    summary = run_sweep(args.trials, snr_values, labels=labels, max_workers=args.workers)
    wall_s = time.perf_counter() - t0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "trials": args.trials, "snr_values": snr_values, "wall_s": wall_s,
        "master_rate_hz": MASTER_RATE, "occupied_bw_hz": OCCUPIED_BW_HZ,
        "summary": summary,
    }, indent=2))

    print(f"trials={args.trials} snr={snr_values[0]}..{snr_values[-1]} "
          f"step={args.step} wall={wall_s:.1f}s -> {out_path}")
    print()
    print(_markdown_table(summary))

    a_snr50 = summary.get("A_legacy_20msps", {}).get("snr50_db")
    b_snr50 = summary.get("B_canonical_15p36msps", {}).get("snr50_db")
    if a_snr50 is not None and b_snr50 is not None:
        delta = b_snr50 - a_snr50
        verdict = "ACCEPT" if delta <= 0.5 else "REJECT"
        print(f"\nB - A SNR50 delta = {delta:+.2f} dB "
              f"(accept threshold: <= 0.5 dB) -> {verdict}")


if __name__ == "__main__":
    main()
