"""Analog FPV: channel table, gates, envelope and line-rate lock."""

from __future__ import annotations

import numpy as np
import pytest

from antsdr_toolkit.analog import fpv
from antsdr_toolkit.analog import video_synth as vs
from antsdr_toolkit.dsp.spectrum import welch_psd_db

FS = 20e6
FC = 5800e6


def _noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return ((rng.standard_normal(n) + 1j * rng.standard_normal(n))
            / np.sqrt(2)).astype(np.complex64)


def _video(standard: str = "ntsc", snr_db: float | None = None, seconds: float = 20e-3,
           seed: int = 0) -> np.ndarray:
    x = vs.video_carrier(FS, seconds, standard=standard, rng=np.random.default_rng(seed))
    if snr_db is None:
        return x
    noise = _noise(x.size, np.random.default_rng(seed + 100))
    return (x * np.sqrt(10 ** (snr_db / 10.0)) + noise).astype(np.complex64)


# ------------------------------------------------------------------ the table


def test_channel_table_matches_the_published_plan():
    assert set(fpv.CHANNELS) == {"R", "A", "B", "E", "F", "D", "L"}
    assert all(len(v) == 8 for v in fpv.CHANNELS.values())
    assert len(fpv.channel_frequencies_hz()) == 53  # 56 entries, three duplicated
    assert fpv.CHANNELS["R"][0] == 5658.0 and fpv.CHANNELS["A"][7] == 5725.0
    assert min(fpv.channel_frequencies_hz()) == 5362e6
    assert max(fpv.channel_frequencies_hz()) == 5945e6


def test_shared_frequencies_resolve_by_band_priority():
    # 5880 MHz is both R7 and F8; 5695 is R2 and D2. Raceband wins.
    assert fpv.nearest_channel(5880e6) == "R7"
    assert fpv.nearest_channel(5695e6) == "R2"
    assert fpv.nearest_channel(5658.4e6) == "R1"  # nearest, not exact
    assert fpv.nearest_channel(5100e6) is None
    assert fpv.nearest_channel(5100e6, tolerance_hz=400e6) is not None


# ------------------------------------------------------------------ the gates


def test_a_video_carrier_passes_both_gates_and_noise_does_not():
    detection = fpv.detect_fpv(_video(), FS, FC)
    assert detection.verdict == "analog_fpv"
    assert detection.snr_db > fpv.MIN_SNR_DB
    assert detection.peak_db > fpv.MIN_PEAK_DB
    assert detection.channel == "F4"  # 5800 MHz

    noise = fpv.detect_fpv(_noise(400_000, np.random.default_rng(2)), FS, FC)
    assert noise.verdict == "none"


def test_the_width_gate_separates_ten_megahertz_from_twenty():
    # What the in-band-against-shoulder test is really measuring, on synthetic
    # spectra so the answer is exact. It needs a spectrum wider than the
    # carrier: at 20 MSPS a 20 MHz signal leaves the noise floor nowhere to
    # sit, which is why the reference scanner sweeps 32 MHz at a time.
    freqs = np.linspace(FC - 30e6, FC + 30e6, 8192)
    for width, expect_pass in ((9e6, True), (14e6, True), (20e6, False), (36e6, False)):
        psd = np.full(freqs.size, -100.0)
        psd[np.abs(freqs - FC) <= width / 2] = -60.0
        _snr, peak = fpv.channel_metrics(freqs, psd, FC)
        assert (peak >= fpv.MIN_PEAK_DB) is expect_pass, f"{width / 1e6:g} MHz gave {peak:.1f} dB"


def test_a_continuous_wide_carrier_has_the_same_envelope_as_noise():
    # The limitation worth knowing: a continuous orthogonal-frequency-division
    # carrier has a Rayleigh envelope, so its coefficient of variation is 0.52,
    # exactly like noise and well inside the analog gate. The envelope test
    # cannot separate continuous OFDM from frequency modulation; only the
    # width test and the line-rate lock can.
    from antsdr_toolkit.device.synthetic import bandlimited_noise_burst

    rng = np.random.default_rng(3)
    wide = bandlimited_noise_burst(FS, 14e6, 20e-3, rng)
    noise = _noise(wide.size, np.random.default_rng(31))
    mixed = (wide * np.sqrt(10 ** 2.0) + noise).astype(np.complex64)
    detection = fpv.detect_fpv(mixed, FS, FC)
    assert detection.envelope_cv == pytest.approx(0.52, abs=0.06)
    assert detection.envelope_cv < fpv.MAX_ENVELOPE_CV  # it passes the envelope gate
    assert detection.lock_ntsc < 0.1 and detection.lock_pal < 0.1  # but never locks


def test_bursty_traffic_is_what_the_envelope_gate_catches():
    # Gated energy, like Wi-Fi frames with gaps: the envelope swings between
    # on and off, which is the 1.2 to 3.2 the reference scanner measured.
    from antsdr_toolkit.device.synthetic import bandlimited_noise_burst

    rng = np.random.default_rng(33)
    x = _noise(400_000, rng) * 0.05
    burst = bandlimited_noise_burst(FS, 8e6, 1e-3, rng) * 6.0
    for start in range(0, 300_000, 40_000):
        x[start:start + burst.size] += burst
    detection = fpv.detect_fpv(x.astype(np.complex64), FS, FC)
    assert detection.envelope_cv > fpv.MAX_ENVELOPE_CV
    assert detection.verdict != "analog_fpv"


def test_the_occupied_bandwidth_is_about_ten_megahertz():
    # The research settled a contested number: analog FPV occupies about
    # 9-11 MHz, not the 19-20 MHz channel spacing or the 23-27 MHz Carson
    # estimate (verified: analog-fpv-bw).
    freqs, psd = welch_psd_db(_video(), FS, 0.0, nfft=4096)
    linear = 10 ** (psd / 10.0)
    cumulative = np.cumsum(linear) / linear.sum()
    lo = freqs[np.searchsorted(cumulative, 0.005)]
    hi = freqs[np.searchsorted(cumulative, 0.995)]
    assert 8e6 < hi - lo < 13e6


def test_envelope_of_frequency_modulation_is_constant():
    assert fpv.envelope_cv(_video()) < 0.05
    # Rayleigh noise reads about 0.52, which is why this gate cannot reject
    # noise on its own.
    assert fpv.envelope_cv(_noise(100_000, np.random.default_rng(4))) == pytest.approx(
        0.523, abs=0.02)
    assert np.isnan(fpv.envelope_cv(np.zeros(0, np.complex64)))


# ------------------------------------------------------------------- the lock


@pytest.mark.parametrize("standard", ["ntsc", "pal"])
def test_the_line_rate_identifies_the_standard(standard):
    demod = fpv.fm_demod(_video(standard), FS)
    same = fpv.sync_lock(demod, FS, standard)
    other = fpv.sync_lock(demod, FS, "pal" if standard == "ntsc" else "ntsc")
    assert same > 0.5, f"{standard} did not lock"
    assert other < 0.1, "the two standards are only 0.8 % apart and must not both lock"
    assert fpv.detect_fpv(_video(standard), FS, FC).standard == standard


@pytest.mark.parametrize("snr_db", [20.0, 10.0])
def test_the_lock_survives_noise(snr_db):
    detection = fpv.detect_fpv(_video("ntsc", snr_db=snr_db), FS, FC)
    assert detection.verdict == "analog_fpv"
    assert detection.standard == "ntsc"
    assert detection.lock_ntsc > 0.5


def test_noise_does_not_lock():
    demod = fpv.fm_demod(_noise(400_000, np.random.default_rng(5)), FS)
    assert fpv.sync_lock(demod, FS, "ntsc") < 0.1
    assert fpv.sync_lock(demod, FS, "pal") < 0.1


def test_sync_lock_validates_its_arguments():
    with pytest.raises(ValueError, match="standard must be"):
        fpv.sync_lock(np.zeros(100), FS, "secam")
    assert fpv.sync_lock(np.zeros(4), FS) == 0.0
    assert fpv.sync_lock(np.zeros(1000), FS) == 0.0  # never crosses the threshold


# ------------------------------------------------------------------ the sweep


def test_scanning_a_wide_spectrum_ranks_the_occupied_channels():
    # Two carriers 40 MHz apart inside one 100 MHz-wide spectrum.
    freqs = np.linspace(5750e6, 5850e6, 4096)
    psd = np.full(freqs.size, -100.0)
    for centre, level in ((5800e6, -60.0), (5765e6, -70.0)):
        inside = np.abs(freqs - centre) <= 4.5e6
        psd[inside] = level
    hits = fpv.scan_channels(freqs, psd)
    assert [h[0] for h in hits][:2] == ["F4", "A6"]
    assert hits[0][2] > hits[1][2]  # ranked by signal-to-noise ratio
    assert fpv.scan_channels(np.zeros(0), np.zeros(0)) == []


def test_channel_metrics_validates_shapes():
    with pytest.raises(ValueError, match="same length"):
        fpv.channel_metrics(np.zeros(10), np.zeros(11), FC)
    snr, peak = fpv.channel_metrics(np.zeros(0), np.zeros(0), FC)
    assert np.isnan(snr) and np.isnan(peak)


def test_detection_serialises():
    import json

    doc = json.loads(json.dumps(fpv.detect_fpv(_video(), FS, FC).to_dict()))
    assert doc["channel"] == "F4" and doc["verdict"] == "analog_fpv"
    assert doc["standard"] == "ntsc"


def test_video_synth_produces_the_documented_levels():
    baseband = vs.composite_video(FS, 5e-3, standard="ntsc", rng=np.random.default_rng(0))
    assert baseband.min() == pytest.approx(fpv.SYNC_LEVEL, abs=0.01)
    assert baseband.max() == pytest.approx(fpv.WHITE_LEVEL, abs=0.01)
    with pytest.raises(ValueError, match="standard must be"):
        vs.composite_video(FS, 1e-3, standard="secam")
    # the modulator and the demodulator are inverses at the same scaling
    demod = fpv.fm_demod(vs.fm_modulate(baseband, FS), FS)
    assert demod.min() == pytest.approx(fpv.SYNC_LEVEL, abs=0.01)
