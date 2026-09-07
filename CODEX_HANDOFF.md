# ANTSDR handoff to Claude

Date: 2026-09-07. DSP baseline: `a764553b5a918499f70a1cbfb69168e975cfeac2`.
Preserve the subsequent capture-continuity findings in `8c4dc993`.

## Scope agreed with Pike

1. Detect drone-related RF with ANTSDR.
2. Decode proprietary telemetry, including drone/operator GPS where transmitted
   and supported. DJI DroneID here is distinct from standard Open Drone ID.
3. Recover FPV pictures, distinguishing analog and digital implementations.

ODID reception/decoding is already handled by ESP32 C5/S3 hardware. Do not
expand the ANTSDR ODID work or count it as progress against these objectives.
Existing modules were left intact. No RF transmission or server changes.

## Delivered in this pass

- Added `toolkit/examples/validate_real_droneid.py`. It takes a local checkout's
  samples, verifies exact sizes/hashes, wraps IQ with the RF centre explicitly
  unknown, runs the real CLI and checks expected CRC-valid output and published
  positions. It fails with a nonzero exit on mismatch. No IQ is added to git.
- Independently reproduced **10 CRC-valid Mini 2 bursts and two Mavic Air 2
  frames**. See `research/validation/reports/codex-real-droneid.json` for input
  hashes, versions, sequence values and results. Default `both` gate exercised.
  `--methods zc cp both` is supported but was not used for this recorded run.
- Corrected the CLI's decode-failure interpretation: failure remains an
  unidentified RF candidate, not evidence of O4, encryption or even a drone.
  Invalid payloads no longer export plausible coordinates/serials in `frame`.
  The JSON has `decode_status` and `crc_checks`; accepted frames retain both
  CRC checks. Consumers must tolerate `frame: null` for failed decodes.
- Preserved `zc_root` and `root_agnostic` in detection JSON. Added the processing
  sample rate and sample-index domain so resampled indices are not interpreted
  using the original capture rate.
- Live sweep now defaults to **10 MSPS** and refuses rates above the stock IIO
  budget. File replay is unaffected; no UHD backend was implemented.
- Above that budget, `capture` only allows a snapshot fitting one RX buffer.
  Its default duration is now **10 ms**. It records the selected tier,
  unverified continuity and host timestamp source. This avoids joining buffers
  with unknown gaps into a supposedly continuous high-rate timeline.
- Applied the same rejection to `firstrun`'s long high-rate steps. Failed steps
  now produce a nonzero exit. Its board-identification path used to construct
  `E200Source` without mandatory rate/frequency arguments, which failed before
  testing the board; it now uses the existing read-only `probe()` function.
  Printing a decoded frame with absent GPS no longer raises a formatting error.

## What the evidence does and does not establish

The public inputs are **extracted bursts**, not continuous timelines. The
upstream README explicitly says the live receiver dumped candidate frames.
Do not calculate transmitter hop periods or detection probability from their
file spacing. The ten Mini 2 bursts have eight distinct sequence values;
repeated sequence values are not automatically duplicate detector outputs.

Reference counts 7/1 come from the upstream README. Counts 10/2 are this
branch's regression targets, independently reproduced here. GPS comparison
allows the upstream rounded conversion constant; it does not establish GPS
accuracy. The reference receiver itself was not rerun in this pass.

Final verification: **581 passed, 1 skipped** in 52.18 seconds on Python
3.12.13, NumPy 2.5.3 and SciPy 1.17.0. The skipped test requires the package's
installed console entry point; tests here used the source package on PYTHONPATH.
The actual CLI Python entry was exercised by the passing real-IQ runner.
Both sample validations passed; the committed JSON contains the recorded results.

No physical ANTSDR was attached. Mock-driver tests establish software behavior,
not gapless capture, a supported DMA buffer size, throughput or RF performance.
The rate budget is conservative and comes from existing project data; it is
not a newly measured universal hardware limit. `--fw` remains a metadata label.

## Next work, in order

1. **Finish real acquisition before claiming live readiness.** Design segmented
   snapshots with separate time domains or implement a verified continuous
   backend with overflow accounting. Keep source/ADC timestamps distinct from
   host receive times. Test after tuning and under CPU/network load. The
   existing first-run plan's 1–2 second high-rate captures now fail explicitly;
   this guard is not a replacement capture scheduler. `--seconds 0.01` is only
   a board probe and will frequently miss DroneID and complete video fields.
2. **Measure retune handling.** The driver flushes buffers and the sweeper also
   waits/discards. Quantify stale samples, settling and revisit latency before
   removing either mechanism. This pass did not guess a new discard count.
3. **Independent analog video validation.** Feed a known real PAL/NTSC IQ file
   into the decoder; compare recovered image content to an independent receiver.
   The current grayscale decoder still relies on synthetic round trips for its
   image-quality tests. A 50 ms / 20 MSPS single-buffer example is in the toolkit
   README; validate board capacity and field lock before relying on it.
4. **Detection specificity.** Test Wi-Fi and other non-drone emitters alongside
   drone recordings. Measure false alarms, missed detections and observation
   coverage. A similarity score is not a calibrated probability, and an unknown
   OFDM burst is not automatically DJI. Review sweep-to-event label association
   before using multi-emitter output downstream.
5. **Modern proprietary telemetry and digital FPV.** O2 results do not validate
   O3/O4. Keep firmware-output parsing distinct from our own IQ decoding.
   Digital FPV video recovery is not implemented; choose one supported protocol
   and independent test capture before promising that capability.
6. **CI and remaining documentation.** The runner is ready for a dedicated
   regression job with pinned inputs. No workflow was added in this pass.
   Older README/research claims and the first-run summary still need a scoped
   consistency pass (especially universal O4 and Remote ID claims). Do not
   convert synthetic SNR improvements directly into field range claims.

## Reproduce

From `antsdr/toolkit` in an environment with the package and dev extra installed:

```sh
python -m pytest -q -rs
git clone https://github.com/RUB-SysSec/DroneSecurity.git /tmp/DroneSecurity
git -C /tmp/DroneSecurity checkout 9ff819843bee48fb140a0704ec78aff757896dea
python examples/validate_real_droneid.py --samples /tmp/DroneSecurity/samples --output validation.json
```

Review these conclusions independently. If you disagree, record the specific
counterexample, capture or test in the existing validation/disputes workflow.
Do not preserve a limitation merely because Codex wrote it.
