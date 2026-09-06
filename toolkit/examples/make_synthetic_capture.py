#!/usr/bin/env python
"""Render a synthetic 2.4 GHz drone scene into a SigMF capture with truth annotations.

The scene mimics what an ANTSDR E200 dwell on the 2.4 GHz ISM band would see
with three very different emitters on the air at once:

* ``dji_ofdm``  - a DJI OcuSync-like video downlink: 10 MHz wide OFDM-shaped
  bursts (flat spectrum, steep roll-off) of 600 us every 5 ms, at a fixed
  carrier offset.
* ``elrs_fhss`` - an ExpressLRS-like control link: LoRa chirp packets
  (SF7, 500 kHz) hopping pseudo-randomly over 8 channels at 250 hops/s.
* ``analog_fm`` - an analog FPV-video-like carrier: continuous wideband FM
  of a low-passed noise "picture", parked at the low edge of the band.

Every emission is written as one SigMF annotation (``core:sample_start``,
``core:sample_count``, ``core:freq_lower_edge``/``upper_edge`` in absolute Hz,
``core:label``, plus ``antsdr:snr_db``), so the capture doubles as labelled
ground truth for ``detect_bursts_demo.py`` and for scoring a detector.

Usage::

    python examples/make_synthetic_capture.py [OUT_STEM] [--seed N] [--duration-s S]

Rendering is deterministic for a given ``--seed``; only ``core:datetime``
changes between runs.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import sys

import numpy as np

from antsdr_toolkit.device.synthetic import (
    Scene,
    SyntheticSource,
    bandlimited_noise_burst,
    fm_video_like,
    lora_chirps,
)
from antsdr_toolkit.io.sigmf_io import write_sigmf

# A common AD9361 rate; the scene spans +-15.36 MHz around the 2.4 GHz band centre.
SAMPLE_RATE_HZ = 30.72e6
CENTER_FREQ_HZ = 2.4415e9
NOISE_POWER_DB = -60.0  # total noise power over the sample rate (dBFS)

# DJI-like OFDM video downlink (offsets are relative to the scene centre).
DJI_OFFSET_HZ = 10.0e6
DJI_BANDWIDTH_HZ = 10.0e6
DJI_BURST_S = 600e-6
DJI_PERIOD_S = 5e-3
DJI_SNR_DB = 20.0

# ELRS-like LoRa FHSS control link.
ELRS_BANDWIDTH_HZ = 500e3
ELRS_SPREADING_FACTOR = 7
ELRS_CHANNELS_HZ = tuple(-6.0e6 + 1.25e6 * k for k in range(8))  # -6.0 ... +2.75 MHz
ELRS_HOP_RATE_HZ = 250.0
ELRS_PACKET_S = 1.5e-3
ELRS_SNR_DB = 15.0

# Analog-video-like FM carrier (Carson bandwidth 2 * (1.5 + 1.0) = 5 MHz).
FM_OFFSET_HZ = -10.0e6
FM_DEVIATION_HZ = 1.5e6
FM_BASEBAND_BW_HZ = 1.0e6
FM_SNR_DB = 25.0


def build_scene(rng: np.random.Generator, duration_s: float) -> Scene:
    """Compose the three emitters on white noise; returns the populated :class:`Scene`."""
    fs = SAMPLE_RATE_HZ
    scene = Scene(fs, CENTER_FREQ_HZ, duration_s, rng, noise_power_db=NOISE_POWER_DB)

    # 1. DJI-like OFDM burst train: fixed carrier, periodic bursts.
    n_bursts = math.floor((duration_s - 1e-3) / DJI_PERIOD_S) + 1
    for k in range(max(n_bursts, 0)):
        t_start_s = 1e-3 + k * DJI_PERIOD_S
        if t_start_s >= duration_s:
            break
        burst = bandlimited_noise_burst(fs, DJI_BANDWIDTH_HZ, DJI_BURST_S, rng)
        scene.add(
            burst,
            t_start_s=t_start_s,
            freq_offset_hz=DJI_OFFSET_HZ,
            snr_db=DJI_SNR_DB,
            label="dji_ofdm",
            bandwidth_hz=DJI_BANDWIDTH_HZ,  # nominal box rather than the 99 % estimate
        )

    # 2. ELRS-like FHSS: one LoRa packet per hop, random channel order.
    symbol_s = 2**ELRS_SPREADING_FACTOR / ELRS_BANDWIDTH_HZ  # 256 us per SF7 symbol

    def lora_packet(burst_duration_s: float) -> np.ndarray:
        n_symbols = max(1, math.ceil(burst_duration_s / symbol_s))
        return lora_chirps(fs, ELRS_BANDWIDTH_HZ, ELRS_SPREADING_FACTOR, n_symbols, rng)

    scene.fhss(
        lora_packet,
        channels_hz=ELRS_CHANNELS_HZ,
        hop_rate_hz=ELRS_HOP_RATE_HZ,
        burst_duration_s=ELRS_PACKET_S,
        t_start_s=0.5e-3,
        t_end_s=duration_s,
        snr_db=ELRS_SNR_DB,
        label="elrs_fhss",
        order="random",
    )

    # 3. Analog-video-like FM carrier, on for the whole scene.
    carrier = fm_video_like(
        fs, duration_s, rng, deviation_hz=FM_DEVIATION_HZ, baseband_bw_hz=FM_BASEBAND_BW_HZ
    )
    scene.add(
        carrier,
        t_start_s=0.0,
        freq_offset_hz=FM_OFFSET_HZ,
        snr_db=FM_SNR_DB,
        label="analog_fm",
    )
    return scene


def truth_annotations(scene: Scene) -> list[dict]:
    """Turn the scene's ground truth into SigMF annotations (friendly alias keys)."""
    fs = scene.sample_rate_hz
    rows = []
    for truth, emission in zip(scene.truth_bursts(), scene.emissions):
        start = round(truth["t_start_s"] * fs)
        stop = round(truth["t_end_s"] * fs)
        rows.append(
            {
                "sample_start": start,
                "sample_count": max(stop - start, 0),
                "freq_lower_hz": truth["f_low_hz"],
                "freq_upper_hz": truth["f_high_hz"],
                "label": truth["label"],
                "snr_db": emission.snr_db,  # stored as antsdr:snr_db
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "stem",
        nargs="?",
        default="synthetic_2g4_scene",
        help="output stem; writes <stem>.sigmf-data and <stem>.sigmf-meta",
    )
    parser.add_argument("--seed", type=int, default=2024, help="numpy Generator seed")
    parser.add_argument("--duration-s", type=float, default=60e-3, help="scene length in seconds")
    args = parser.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    scene = build_scene(rng, args.duration_s)

    # SyntheticSource is the same SampleSource interface a live E200 driver will offer.
    with SyntheticSource.from_scene(
        scene, description=f"synthetic 2.4 GHz scene (seed {args.seed}): DJI OFDM, ELRS FHSS, FM"
    ) as source:
        samples = source.read(source.n_samples)
        info = source.info

    data_path, meta_path = write_sigmf(
        args.stem,
        samples,
        info,
        annotations=truth_annotations(scene),
        extra_global={"antsdr:scene_seed": args.seed, "antsdr:noise_power_db": NOISE_POWER_DB},
    )

    counts: dict[str, int] = {}
    for emission in scene.emissions:
        counts[emission.label] = counts.get(emission.label, 0) + 1
    print(f"wrote {data_path} ({data_path.stat().st_size / 1e6:.1f} MB) and {meta_path}")
    print(f"{info}")
    print(f"{len(samples)} samples, {scene.duration_s * 1e3:.1f} ms, {len(scene.emissions)} truth annotations:")
    for label, count in counts.items():
        print(f"  {label:<10} {count:3d} emission(s)")
    print(f"next: python {pathlib.Path(__file__).with_name('detect_bursts_demo.py')} {args.stem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
