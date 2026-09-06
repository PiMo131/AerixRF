# ADR-0007: Detection pipeline: burst features and heuristics before machine learning

- **Status:** Proposed (needs Q8 in `../../QUESTIONS.md`)
- **Date:** 2026-09-06
- **Sources:** `../../research/landscape.md`, `../../research/datasets.md`, `../../research/signal-reference.md`, `../../research/verification-log.md` (claim `spectrogram-vs-iq`)

## Context

Published RF drone classifiers reach 94-98 % on their own datasets but the
research found three systematic problems: window-level random splits inflate
results (data leakage), models trained in the lab lose most of their
confidence on live SDR data (domain shift; RF-Vision-UAV-Tracker reports
0.2-0.7 confidence versus 0.995 mAP in training), and every large dataset was
recorded at 60-100 MSPS on USRP-class hardware, far above the E200's practical
rates. At the same time, the on-air parameters of the common links (hop
period, dwell, occupied bandwidth, burst length, subcarrier spacing) are
well documented and separate most families without any training.

## Decision

The first classifier is rule-based: an STFT burst detector with a per-bin
adaptive noise floor, burst-set features (bandwidth, duration, repetition,
hop set, duty cycle, kurtosis), two protocol-specific confirmers
(Zadoff-Chu correlation for DroneID, cyclic-prefix autocorrelation for
OcuSync versus Wi-Fi) and an analog-video confirmer (envelope constancy and
line-sync periodicity). Families are scored against the signature table in
`classify/signatures.py`, every number of which cites its source.

Machine learning enters only after the toolkit has produced its own SigMF
recordings on the E200, with session- and unit-level splits and per-SNR
evaluation; public datasets are used for pre-training and sanity checks, not
as the field model.

## Consequences

- Explainable detections from day one ("812 kHz LoRa chirps every 4 ms on a
  1 MHz grid" reads as ELRS 250 Hz).
- Unknown or new links land in an explicit `unknown` class with their
  features preserved, which is what a later open-set model needs.
- Accuracy on close families (Herelink versus OcuSync, FrSky R9 versus
  sub-GHz ELRS) will be limited until decoders or ML exist.

## Alternatives considered

- Port a published CNN first (Glüge VGG11, RFUAV YOLO): weights exist, but
  the class lists do not match modern links, inference costs 312 GFLOP per
  window, and domain shift is unmeasured on the E200; deferred.
