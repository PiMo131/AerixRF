#!/usr/bin/env python
"""Run the whole toolkit over one synthetic 2.4 GHz scene, with no hardware.

Renders a scene containing four emitters whose parameters come from the
signature table, writes it as a SigMF recording with ground-truth
annotations, and then puts it through every stage in turn:

1. sweep the band and rank the dwells by activity
2. detect bursts and name each emitter with the heuristic classifier
3. test the cyclic prefixes to separate the OFDM numerologies
4. find and decode the DJI DroneID burst
5. check the analog FPV channel with its own metrics

The point is to show what each stage contributes and where each one stops.
The classifier cannot tell an OcuSync 2 downlink from an O4 one on burst
statistics alone, the cyclostationary test says "LTE numerology" rather than
"drone", and only the DroneID decoder produces a serial number and a
position. That is the honest division of labour, and it is visible in the
output.

Usage::

    python examples/end_to_end_demo.py [OUT_STEM]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np

from antsdr_toolkit.analog import fpv
from antsdr_toolkit.classify.heuristic import classify_clusters, margin
from antsdr_toolkit.device import synthetic as syn
from antsdr_toolkit.droneid import receiver as droneid_rx
from antsdr_toolkit.droneid import synth as droneid_synth
from antsdr_toolkit.dsp import cyclo
from antsdr_toolkit.dsp.bursts import detect_bursts_from_iq
from antsdr_toolkit.io.sigmf_io import write_sigmf
from antsdr_toolkit.scan.planner import plan_dwells
from antsdr_toolkit.scan.sweep import Sweeper

# 15.36 MSPS: the DroneID rate, and one of the few the burst tolerates. On the
# stock E200 firmware this is a snapshot capture, not a continuous stream.
SAMPLE_RATE_HZ = 15.36e6
CENTER_FREQ_HZ = 2429.5e6  # a documented DroneID channel
DURATION_S = 0.12


def build_scene(rng: np.random.Generator) -> syn.Scene:
    """Four emitters, each built from a row of the signature table."""
    scene = syn.Scene(SAMPLE_RATE_HZ, CENTER_FREQ_HZ, DURATION_S, rng, noise_power_db=-60.0)

    # 1. A DJI DroneID burst on the tuned channel: 9 MHz, 643 us, and in a
    #    real capture one every 600 ms. The scene is short, so one burst.
    droneid = droneid_synth.make_burst(SAMPLE_RATE_HZ, rng=np.random.default_rng(11))
    scene.add(droneid, t_start_s=0.02, freq_offset_hz=0.0, snr_db=25.0,
              label="dji_droneid", bandwidth_hz=9e6)

    # 2. An ExpressLRS-like control link: 812 kHz chirps hopping on a 1 MHz
    #    grid every 4 ms, which is the published 250 Hz packet rate.
    hop_rng = np.random.default_rng(12)
    n_symbols = max(1, round(3.3e-3 / (2 ** 7 / 812.5e3)))
    t, index = 0.002, 0
    while t < DURATION_S - 0.005:
        packet = syn.lora_chirps(SAMPLE_RATE_HZ, 812.5e3, 7, n_symbols, hop_rng)
        # +5, +6 and +7 MHz: the three channels of the 1 MHz-spaced,
        # 80-channel 2.4 GHz hop set that fit in the top of this 15.36 MHz
        # window while staying clear of both the Nyquist edge and the DroneID
        # burst's own 9 MHz. ExpressLRS holds a channel for four packets
        # before hopping, which is what the //4 is.
        #
        # A real capture has no such courtesy: when a hopper lands inside the
        # DroneID band the two overlap in time and frequency, no 2-D detector
        # can separate them, and that is the usual reason a burst is found
        # but does not decode.
        offset = (5.0 + 1.0 * ((index // 4) % 3)) * 1e6
        scene.add(packet, t_start_s=t, freq_offset_hz=offset, snr_db=22.0,
                  label="elrs_2g4", bandwidth_hz=812.5e3)
        t += 4e-3
        index += 1

    # 3. A narrow telemetry link on a fixed frequency: 200 kHz of GFSK at
    #    2422.9 MHz, every 10 ms, never hopping. Stage 2 gets this one wrong
    #    too, and for a reason worth reading in the output.
    tel_rng = np.random.default_rng(13)
    t = 0.003
    while t < DURATION_S - 0.005:
        scene.add(syn.gfsk_burst(SAMPLE_RATE_HZ, 64e3, 300, tel_rng),
                  t_start_s=t, freq_offset_hz=-6.6e6, snr_db=20.0,
                  label="telemetry", bandwidth_hz=200e3)
        t += 10e-3
    return scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stem", nargs="?", default="end_to_end_scene",
                        help="output SigMF stem (default end_to_end_scene)")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    scene = build_scene(rng)
    source = syn.SyntheticSource.from_scene(scene)
    samples = source.read(source.n_samples)

    stem = pathlib.Path(args.stem)
    annotations = [
        {"sample_start": int(e["t_start_s"] * SAMPLE_RATE_HZ),
         "sample_count": int((e["t_end_s"] - e["t_start_s"]) * SAMPLE_RATE_HZ),
         "freq_lower_hz": e["f_low_hz"], "freq_upper_hz": e["f_high_hz"],
         "label": e["label"]}
        for e in scene.truth_bursts()
    ]
    data_path, meta_path = write_sigmf(stem, samples, source.info, annotations=annotations)
    print(f"# wrote {data_path.name} and {meta_path.name}: "
          f"{samples.size} samples, {samples.size / SAMPLE_RATE_HZ * 1e3:.0f} ms, "
          f"{len(annotations)} truth annotations")

    _section("1. sweep: where is the energy")
    plan = plan_dwells([CENTER_FREQ_HZ], SAMPLE_RATE_HZ)
    sweeper = Sweeper(syn.SyntheticSource.from_scene(scene, loop=True), plan,
                      dwell_s=DURATION_S / 2, settle_s=0.0, discard_buffers=0,
                      fft_size=1024)
    for result in sweeper.run_once():
        print(f"  {result.center_freq_hz / 1e6:9.3f} MHz  floor {result.noise_floor_db:6.1f} dB  "
              f"{len(result.occupancy)} occupied segment(s)  {len(result.bursts)} burst(s)  "
              f"kurtosis {result.kurtosis:5.2f}  activity {result.activity_score:6.2f}")
        for segment in result.occupancy[:4]:
            print(f"      {segment.f_low_hz / 1e6:9.3f} to {segment.f_high_hz / 1e6:9.3f} MHz  "
                  f"snr {segment.snr_db:5.1f} dB")

    _section("2. classify: what does each emitter look like")
    # close_time_s matters here: a LoRa chirp sweeps its bandwidth once per
    # symbol, so a spectrogram detector sees a packet as a train of separate
    # diagonal streaks. Closing gaps shorter than a symbol glues them back
    # into one burst, which is what the timing features need.
    bursts = detect_bursts_from_iq(samples, SAMPLE_RATE_HZ, CENTER_FREQ_HZ,
                                   fft_size=512, threshold_db=10.0,
                                   min_duration_s=200e-6, min_bandwidth_hz=300e3,
                                   close_time_s=250e-6, close_freq_hz=1e6)
    groups = classify_clusters(bursts, window_s=samples.size / SAMPLE_RATE_HZ,
                               band_hint="ism-2g4", cluster_gap_hz=3e6, top_k=2)
    print(f"  {len(bursts)} burst(s) in {len(groups)} emitter group(s)")
    for index, (features, candidates) in enumerate(groups, start=1):
        print(f"\n  emitter {index}: {features.n_bursts} burst(s), "
              f"{features.bandwidth_median_hz / 1e6:.2f} MHz, "
              f"{features.duration_median_s * 1e3:.2f} ms long, "
              f"every {features.interval_median_s * 1e3:.2f} ms, "
              f"{features.n_distinct_centers} centre(s)")
        for candidate in candidates:
            print(f"    {candidate.score:5.2f}  {candidate.display} ({candidate.decodability})")
            print(f"           {candidate.explanation}")
        if len(candidates) > 1:
            print(f"    margin {margin(candidates):.2f}")
    print("\n  All three groups are mismeasured, each in its own way, and the\n"
          "  reasons are worth more than the labels:\n"
          "\n"
          "  Emitter 1 is the ExpressLRS link, correctly named. Its channels are\n"
          "  a real 1 MHz apart, but they read as half that: burst centres wander\n"
          "  by a couple of hundred kilohertz and the 250 kHz centre tolerance\n"
          "  splits each true channel into two. The tolerance has to sit between\n"
          "  the centre jitter and the channel spacing, and for an 812 kHz chirp\n"
          "  on a 1 MHz grid that gap is narrow.\n"
          "\n"
          "  Emitter 2 is the telemetry link, which never hops, yet it is named\n"
          "  FrSky and HoTT on four distinct centres. The 1 MHz frequency closing\n"
          "  pulls neighbouring noise cells into each 200 kHz burst, so the\n"
          "  measured width swings between 450 and 1500 kHz and the centre swings\n"
          "  with it. Invented hopping is what a closing wider than the signal\n"
          "  looks like. The margin of 0.00 is the one honest number here: the\n"
          "  classifier is saying it cannot separate its own top two.\n"
          "\n"
          "  Emitter 3 is the DroneID burst, named Wi-Fi. The 250 us time closing\n"
          "  that glues LoRa symbols back into packets also glues this 643 us\n"
          "  burst to the hop that follows it, so it measures 3.3 ms and 11 MHz.\n"
          "\n"
          "  One detector setting cannot serve every waveform. That is why stage 4\n"
          "  runs a matched detector instead, and why a field deployment sweeps\n"
          "  the same dwell more than once with different settings.")

    _section("3. cyclic prefixes: which OFDM numerology, if any")
    profile = cyclo.cyclic_profile(samples, SAMPLE_RATE_HZ, chunk_s=4e-3)
    for name, result in profile.items():
        verdict = "line found" if result.contrast > 3.0 else "nothing"
        flag = "" if result.verified_numerology else "  (numerology unverified)"
        print(f"  {name:<12} alpha {result.alpha_hz / 1e3:7.2f} kHz  "
              f"contrast {result.contrast:5.2f}  {verdict}{flag}")
    print("  note: this says 'LTE-family OFDM', not 'drone'. Cellular uses the "
          "same numerology.")

    _section("4. DroneID: the only stage that yields an identity")
    for detection, frame in droneid_rx.process(samples, SAMPLE_RATE_HZ):
        print(f"  burst at {detection.t_start_s * 1e3:.2f} ms  score {detection.score:.3f}  "
              f"prefix coherence {detection.confirm_score:.3f}  "
              f"offset {detection.cfo_hz:+.0f} Hz")
        if frame and frame.crc24_ok and frame.crc16_ok:
            print(f"    {frame.product_name}, serial {frame.serial!r}")
            print(f"    drone {frame.drone_lat:.5f}, {frame.drone_lon:.5f}  "
                  f"height {frame.height_m:.0f} m")
            print(f"    pilot {frame.pilot_lat:.5f}, {frame.pilot_lon:.5f}")
        else:
            print("    CRC failed: too weak, or an encrypted OcuSync 4 payload")

    _section("5. analog FPV: nothing here, and the metrics say so")
    detection = fpv.detect_fpv(samples, SAMPLE_RATE_HZ, CENTER_FREQ_HZ)
    print(f"  verdict {detection.verdict}  snr {detection.snr_db:.1f} dB  "
          f"width margin {detection.peak_db:.1f} dB  envelope {detection.envelope_cv:.2f}  "
          f"standard {detection.standard}")

    print(f"\n# try the same recording through the command line:\n"
          f"#   antsdr-tk classify {stem} --band ism-2g4 --fft 512 "
          f"--min-duration 200e-6 --min-bandwidth 300e3\n"
          f"#   antsdr-tk droneid {stem}")
    return 0


def _section(title: str) -> None:
    print(f"\n{'-' * 72}\n{title}\n")


if __name__ == "__main__":
    sys.exit(main())
