"""Stage 1: the detector fires on a drone-like signal, stays quiet on noise, and
describes RF *shape* (morphology) without claiming identity."""

import numpy as np

from aerix_rf.dsp import spectrogram
from aerix_rf.detect import energy
from aerix_rf.sdr.sim import synth_iq

SAMPLE_RATE = 10e6      # smaller than the 20e6 field rate keeps the test fast
CENTER_MHZ = 2431.5


def _detect(iq, sample_rate=SAMPLE_RATE):
    spec = spectrogram.compute(iq, sample_rate, fft_size=1024)
    return energy.detect(spec, CENTER_MHZ)


def _packets(sample_rate, duration_s, *, bw_hz, amp, hop_hz=None, seed=7):
    """Wi-Fi-like random packets (fixed centre) or an FHSS-like hopper."""
    rng = np.random.default_rng(seed)
    n = int(sample_rate * duration_s)
    iq = ((rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)).astype(np.complex64)
    t0 = 0
    while t0 < n:
        seg = min(int(rng.uniform(0.2e-3, 2e-3) * sample_rate), n - t0)
        fc = rng.uniform(-hop_hz / 2, hop_hz / 2) if hop_hz else 0.0
        s = rng.standard_normal(seg) + 1j * rng.standard_normal(seg)
        f = np.fft.fftshift(np.fft.fftfreq(seg, 1 / sample_rate))
        S = np.fft.fftshift(np.fft.fft(s))
        S[np.abs(f - fc) > bw_hz / 2] = 0
        iq[t0:t0 + seg] += (amp * np.fft.ifft(np.fft.ifftshift(S))).astype(np.complex64)
        t0 += seg + int(rng.uniform(0.1e-3, 3e-3) * sample_rate)
    return iq


def test_drone_signal_scores_high():
    iq = synth_iq(SAMPLE_RATE, 0.3, drone=True, snr_db=15.0,
                  burst_bw_hz=8e6, cadence_s=0.06, seed=1)
    det = _detect(iq)
    assert det.score > 0.60, det
    assert det.snr_db > 8.0
    assert det.occupied_bw_mhz > 4.0
    assert det.morphology in ("ofdm_candidate", "burst_wideband_candidate")
    assert det.duty_cycle < 0.3            # 3 ms bursts every 60 ms
    assert det.burst_count >= 3


def test_noise_scores_low():
    iq = synth_iq(SAMPLE_RATE, 0.3, drone=False, seed=2)
    det = _detect(iq)
    assert det.score < 0.30, det
    assert det.morphology == "noise"
    assert det.signature_class == "noise"
    assert det.duty_cycle == 0.0


def test_stage1_never_claims_identity():
    """Stage 1 describes shape only: signature_class is 'noise' or 'unknown'."""
    for seed, drone in ((1, True), (2, False)):
        det = _detect(synth_iq(SAMPLE_RATE, 0.3, drone=drone, snr_db=15.0,
                               burst_bw_hz=8e6, cadence_s=0.06, seed=seed))
        assert det.signature_class in ("noise", "unknown")
        assert det.morphology in energy.MORPHOLOGIES
        d = det.as_dict()
        assert {"morphology", "duty_cycle", "signature_class"} <= set(d)


def test_continuous_wideband_is_continuous_not_bursty():
    """A ~16 MHz emitter that is on for the whole window (Wi-Fi-like / video
    downlink) must be seen as continuous wideband -- and it must be *seen* at
    all, even though it covers most of the captured band."""
    sr = 20e6
    iq = synth_iq(sr, 0.25, drone=True, snr_db=12.0, burst_bw_hz=16e6,
                  burst_ms=1000.0, cadence_s=10.0, seed=4)
    det = _detect(iq, sr)
    assert det.snr_db > 8.0, det
    assert det.occupied_bw_mhz > 12.0
    assert det.duty_cycle > 0.8
    assert det.cadence_ms is None
    assert det.morphology == "continuous_wideband_candidate"


def test_very_wide_continuous_is_analog_candidate():
    sr = 20e6
    iq = synth_iq(sr, 0.25, drone=True, snr_db=12.0, burst_bw_hz=18.5e6,
                  burst_ms=1000.0, cadence_s=10.0, seed=4)
    det = _detect(iq, sr)
    assert det.occupied_bw_mhz >= 18.0
    assert det.morphology == "analog_candidate"


def test_cadenced_burst_train_is_ofdm_candidate_with_cadence():
    """The DroneID-like case: 10 MHz bursts every 600 ms over a >= 1.5 s window."""
    sr = 20e6
    iq = synth_iq(sr, 1.6, drone=True, snr_db=15.0, burst_bw_hz=10e6,
                  cadence_s=0.6, seed=3)
    det = _detect(iq, sr)
    assert det.morphology == "ofdm_candidate"
    assert det.cadence_ms is not None and 500 <= det.cadence_ms <= 700
    assert det.burst_count >= 2
    assert 8.0 <= det.occupied_bw_mhz <= 12.0
    assert det.duty_cycle < 0.1


def test_wifi_like_packets_have_no_cadence():
    """Random 16 MHz packets: wideband, bursty, but not periodic."""
    det = _detect(_packets(20e6, 0.5, bw_hz=16e6, amp=4.0), 20e6)
    assert det.snr_db > 8.0
    assert det.occupied_bw_mhz > 12.0
    assert det.morphology in ("ofdm_candidate", "burst_wideband_candidate")
    assert not (det.cadence_ms is not None and 300 <= det.cadence_ms <= 1000)


def test_hopper_is_fhss_candidate():
    det = _detect(_packets(20e6, 0.5, bw_hz=1e6, amp=8.0, hop_hz=16e6), 20e6)
    assert det.morphology == "fhss_candidate", det


def test_narrowband_burst_is_narrowband_candidate():
    iq = synth_iq(SAMPLE_RATE, 0.3, drone=True, snr_db=20.0, burst_bw_hz=0.5e6,
                  burst_ms=5.0, cadence_s=0.1, seed=5)
    det = _detect(iq)
    assert det.morphology == "narrowband_candidate"
    assert det.occupied_bw_mhz < 2.0


def test_spectrogram_png_roundtrips():
    iq = synth_iq(SAMPLE_RATE, 0.2, drone=True, seed=3)
    spec = spectrogram.compute(iq, SAMPLE_RATE, fft_size=512)
    png = spectrogram.to_png(spec)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 100
