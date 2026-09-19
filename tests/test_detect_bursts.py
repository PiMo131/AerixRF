"""T1 acceptance tests for aerix_rf.detect.bursts (stage1-link-signatures.md).

All frames are synthetic linear-power tensors built directly (no IQ/STFT),
matching the D8 detector-frame contract: [n_frames, n_bins] linear power,
200 us/frame. Seeded wherever randomness is used.
"""

from __future__ import annotations

import time

import numpy as np

from aerix_rf.detect.bursts import detect_bursts

FRAME_DT_S = 200e-6
N_BINS = 1024
FS = 15.36e6
FREQS_HZ = np.fft.fftshift(np.fft.fftfreq(N_BINS, d=1.0 / FS))
BIN_HZ = float(FREQS_HZ[1] - FREQS_HZ[0])
FLOOR_LIN = 1.0


def _band_mask(centre_hz: float, width_hz: float) -> np.ndarray:
    return np.abs(FREQS_HZ - centre_hz) <= (width_hz / 2.0)


def _power_centroid(profile_lin: np.ndarray, floor_lin: float) -> float:
    """The OLD estimator (power centroid) -- used only to prove it fails
    where the new -6 dB edge-midpoint estimator passes."""
    p = np.clip(profile_lin - floor_lin, 0.0, None)
    tot = p.sum()
    if tot <= 0:
        return 0.0
    return float((p * FREQS_HZ).sum() / tot)


def test_hop_raster_centre_and_bw():
    rng = np.random.default_rng(1)
    grid = [k * 1.0e6 for k in range(-5, 5)]        # exact 1.000 MHz grid
    on_frames, gap_frames = 5, 5
    n_hops = 20
    centres = [rng.choice(grid) for _ in range(n_hops)]

    frames = np.full((n_hops * (on_frames + gap_frames), N_BINS), FLOOR_LIN)
    for i, fc in enumerate(centres):
        a = i * (on_frames + gap_frames)
        frames[a:a + on_frames, _band_mask(fc, 2.0e6)] = FLOOR_LIN * 10 ** (20.0 / 10.0)

    events = detect_bursts(frames, fs=FS, frame_dt_s=FRAME_DT_S, freqs_hz=FREQS_HZ,
                            noise_floor_lin=FLOOR_LIN)
    assert len(events) == n_hops
    errs = np.array([ev.centre_hz - fc for ev, fc in zip(events, centres)])
    bws = np.array([ev.bw_6db_hz for ev in events])
    assert errs.std() <= 60e3, f"sigma_f={errs.std()} Hz"
    assert np.all(np.abs(bws - 2.0e6) <= 0.3e6), bws


def test_edge_midpoint_beats_centroid_on_varying_shape():
    fc = 0.0
    main_bw = 2.0e6
    n_bursts = 10
    on_frames, gap_frames = 4, 4
    frames = np.full((n_bursts * (on_frames + gap_frames), N_BINS), FLOOR_LIN)
    peak = FLOOR_LIN * 10 ** (20.0 / 10.0)
    shoulder = FLOOR_LIN * 10 ** (13.0 / 10.0)   # peak - 7 dB: below the -6 dB gate

    for i in range(n_bursts):
        a = i * (on_frames + gap_frames)
        frames[a:a + on_frames, _band_mask(fc, main_bw)] = peak
        side = 1.0 if i % 2 == 0 else -1.0
        shoulder_centre = fc + side * (main_bw / 2.0 + 2.0e6)
        frames[a:a + on_frames, _band_mask(shoulder_centre, 4.0e6)] = shoulder

    events = detect_bursts(frames, fs=FS, frame_dt_s=FRAME_DT_S, freqs_hz=FREQS_HZ,
                            noise_floor_lin=FLOOR_LIN)
    assert len(events) == n_bursts

    edge_centres = np.array([ev.centre_hz for ev in events])
    profiles = frames.reshape(n_bursts, on_frames + gap_frames, N_BINS)[:, :on_frames, :].mean(axis=1)
    centroids = np.array([_power_centroid(p, FLOOR_LIN) for p in profiles])

    bw_bound = 0.25 * main_bw
    assert edge_centres.std() < bw_bound, f"edge std={edge_centres.std()}"
    assert centroids.std() >= bw_bound, f"centroid std={centroids.std()} (expected to fail)"


def test_overlapping_time_different_centres_separated():
    n_frames = 20
    frames = np.full((n_frames, N_BINS), FLOOR_LIN)
    peak = FLOOR_LIN * 10 ** (20.0 / 10.0)
    active = slice(5, 15)
    frames[active, _band_mask(-3.0e6, 1.0e6)] = peak
    frames[active, _band_mask(3.0e6, 1.0e6)] = peak

    events = detect_bursts(frames, fs=FS, frame_dt_s=FRAME_DT_S, freqs_hz=FREQS_HZ,
                            noise_floor_lin=FLOOR_LIN)
    assert len(events) == 2
    centres = sorted(ev.centre_hz for ev in events)
    assert abs(centres[0] - (-3.0e6)) < 60e3
    assert abs(centres[1] - 3.0e6) < 60e3
    # both events occupy (overlapping) the same active time range
    for ev in events:
        assert abs(ev.t_start - 5 * FRAME_DT_S) < 1e-9
        assert ev.n_frames == 10


def test_edge_clipped_at_time_edge():
    n_frames = 20
    frames = np.full((n_frames, N_BINS), FLOOR_LIN)
    peak = FLOOR_LIN * 10 ** (20.0 / 10.0)
    frames[0:5, _band_mask(0.0, 2.0e6)] = peak   # touches t=0

    events = detect_bursts(frames, fs=FS, frame_dt_s=FRAME_DT_S, freqs_hz=FREQS_HZ,
                            noise_floor_lin=FLOOR_LIN)
    assert len(events) == 1
    assert events[0].edge_clipped is True
    assert events[0].t_start == 0.0


def test_wifi_like_wider_than_dwell_clips_both_freq_edges():
    n_frames = 20
    frames = np.full((n_frames, N_BINS), FLOOR_LIN)
    peak = FLOOR_LIN * 10 ** (20.0 / 10.0)
    frames[5:15, :] = peak   # occupies the entire visible band, interior in time

    events = detect_bursts(frames, fs=FS, frame_dt_s=FRAME_DT_S, freqs_hz=FREQS_HZ,
                            noise_floor_lin=FLOOR_LIN)
    assert len(events) == 1
    ev = events[0]
    assert ev.edge_clipped is True
    assert abs(ev.centre_hz) < BIN_HZ   # centre lands on the dwell (band) centre
    assert ev.bw_6db_hz >= FS - 1.0      # occupies (at least) the whole visible band


def test_noise_only_yields_zero_events():
    n_frames = 200
    frames = np.full((n_frames, N_BINS), FLOOR_LIN)
    events = detect_bursts(frames, fs=FS, frame_dt_s=FRAME_DT_S, freqs_hz=FREQS_HZ,
                            noise_floor_lin=FLOOR_LIN)
    assert events == []


def test_timing_bound_1s_window_at_12_288_msps():
    fs = 12.288e6
    n_frames = int(round(1.0 / FRAME_DT_S))   # 5000
    rng = np.random.default_rng(3)
    freqs = np.fft.fftshift(np.fft.fftfreq(N_BINS, d=1.0 / fs))
    frames = np.full((n_frames, N_BINS), FLOOR_LIN) * (1.0 + 0.01 * rng.standard_normal((n_frames, N_BINS)))
    # a handful of bursts so the channelisation path actually does work
    peak = FLOOR_LIN * 10 ** (20.0 / 10.0)
    for i, fc in enumerate([-2e6, -1e6, 0.0, 1e6, 2e6] * 8):
        a = i * 90
        frames[a:a + 5, np.abs(freqs - fc) <= 1.0e6] = peak

    # Median-of-repeats: the budget is about the algorithm's cost, not about
    # one-off OS-scheduling/GC jitter on a shared CI box.
    kwargs = dict(fs=fs, frame_dt_s=FRAME_DT_S, freqs_hz=freqs, noise_floor_lin=FLOOR_LIN)
    detect_bursts(frames, **kwargs)  # warm up (first-call numpy/scipy overhead)
    timings = []
    events = None
    for _ in range(7):
        t0 = time.perf_counter()
        events = detect_bursts(frames, **kwargs)
        timings.append(time.perf_counter() - t0)
    timings.sort()
    median_s = timings[len(timings) // 2]

    assert median_s <= 0.05, f"detect_bursts median {median_s * 1000:.2f} ms (budget 50 ms)"
    assert len(events) >= 1
