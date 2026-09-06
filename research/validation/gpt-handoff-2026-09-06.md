# GPT takeover checkpoint — live capture integrity

Date: 2026-09-06

Baseline reviewed: `claude/antsdr-drone-rf-detection-ac0uxs` at `8c4dc993a75ec71d57870da5f1e8e827bf19d904`.

Work branch: `gpt/antsdr-live-capture-integrity`.

## Scope reminder

The ANTSDR work is for:

1. RF drone detection / classification.
2. Drone-link decoding where the RF protocol permits it: telemetry, drone position and potentially controller/operator position.
3. FPV/video-link analysis and, where technically possible, recovery of video frames/content.

Open Drone ID is **not** an ANTSDR requirement for AERIX. The ESP32-C5/S3 receiver path handles ODID. SDR-side ODID code can remain as research/reference, but it must not drive priorities or acceptance criteria for the ANTSDR detector.

## What changed since the previous review

Claude's latest two commits were both good corrections:

- FEC documentation now matches the implementation: the turbo decoder exists, rather than being described as missing.
- RUB-SysSec IQ files were correctly reclassified as concatenated triggered extractions rather than continuous recordings. The earlier ~970 us timing-grid / duty-cycle inference from those file seams is therefore invalid and must not be used as RF evidence.

That correction is important: it is exactly the same class of error that H3 exposed in our own snapshot writer.

## H3 — snapshot SigMF continuity

**Status: CONFIRMED, fixed on this branch.**

### Problem

`cli_capture` explicitly described the `snapshot` tier as having gaps between host buffers, but `SigmfRecorder.write()` appended every buffer to one apparent continuous sample timeline. Any timing feature computed later could therefore interpret the end of buffer N and the start of buffer N+1 as adjacent RF samples.

That can corrupt:

- inter-burst intervals;
- duty cycle;
- periodicity;
- cyclostationary features;
- any decoder that assumes sample-time continuity across the seam.

### Fix

Added `antsdr_toolkit.io.segmented_sigmf.SegmentedSigmfRecorder`.

For `--tier snapshot`:

- each transferred host RX buffer after the first starts a new SigMF capture segment;
- `core:sample_start` remains the packed dataset index;
- the segment carries `antsdr:continuity = "unknown-gap-before"`;
- global metadata carries `antsdr:capture_tier = "snapshot"` and `antsdr:timing_contiguous = false`;
- no fake `core:global_index` is written because pyadi/libiio does not currently provide us a hardware sample counter;
- no per-segment `core:datetime` is invented because a host-side `rx()` call time is not the RF acquisition timestamp of a DMA buffer that may already be queued.

For `--tier continuous`, the original single-timeline writer remains in use and global metadata says timing is contiguous.

### Downstream fix

`SigmfFileSource` now detects `antsdr:continuity = "unknown-gap-before"` boundaries and will return a short read ending at the boundary instead of concatenating the next segment into the same DSP window. Calling `read()` again enters the next segment.

`loop=True` is rejected for a discontinuous snapshot because looping/filling across unknown gaps would fabricate timing again.

This is what makes the H3 fix end-to-end rather than metadata-only.

### SigMF compatibility

This representation uses standard Capture Segment `core:sample_start` semantics plus the already-declared optional `antsdr` extension namespace. SigMF permits extension fields in capture objects. The gap duration remains unknown until a real hardware/global sample counter is available.

## H4 — retune blind time / double discard

**Status: CONFIRMED for the live CLI path, fixed on this branch.**

### Old path

At the old CLI defaults:

- sample rate: 20 MSPS;
- E200 driver retune flush: 2 x 262,144-sample physical RX buffers;
- extra sweep settle sleep: 80 ms;
- extra sweep discard: 2 x full 60 ms dwell-length reads;
- retained observation: 60 ms.

Minimum RF/sample-time budget per dwell, ignoring Python/DSP/network slowdown:

- driver flush: `524288 / 20e6 = 26.2144 ms`;
- sleep: `80 ms`;
- sweep-level discard: `120 ms`;
- retained dwell: `60 ms`;
- total: `286.2144 ms`;
- retained observation fraction: `60 / 286.2144 = 20.96%`.

So almost 80% of the nominal dwell cycle was deliberately blind before processing overhead, and this calculation is optimistic because 20 MSPS is itself above the stock-IIO continuous ceiling.

### New live CLI defaults

- sample rate: 10 MSPS;
- extra settle: 0;
- extra dwell-length discard: 0;
- E200 driver's existing 2-buffer retune flush remains;
- retained dwell remains 60 ms.

Minimum budget:

- driver flush: `524288 / 10e6 = 52.4288 ms`;
- retained dwell: `60 ms`;
- total: `112.4288 ms`;
- retained observation fraction: `53.37%`.

This removes exactly 200 ms of additive blind time from every default live dwell. It does **not** claim the remaining two-buffer E200 flush is optimal; that still needs hardware measurement. The driver currently documents two buffers as a conservative choice, not a measured minimum.

### Residual H4 item

The low-level `scan.sweep.Sweeper` constructor still defaults to `settle_s=0.08` and `discard_buffers=2`. `cli_sweep` now passes explicit zeros, so the normal E200 command is corrected, but direct library callers can still recreate the old behavior unless they pass explicit timing. Refactor the generic class defaults to neutral values after checking any non-E200 callers.

## H5 — 20 MSPS live sweep default

**Status: CONFIRMED, fixed on this branch.**

The branch's own `hardware.py` says stock IIO is CPU-bound around 11-13 MSPS and explicitly says to plan continuous work at **10 MSPS**. Nevertheless `cli_sweep` defaulted to **20 MSPS** and described that as the E200 1 GbE host ceiling.

That was internally inconsistent and unsafe for a detector whose job is not to miss short bursts.

`cli_sweep` now defaults to 10 MSPS. Higher rates remain user-selectable, but the E200 driver's host-link warning is printed by the CLI so an explicit 15.36/20 MSPS sweep cannot silently pretend to be continuous.

Trade-off: the default usable instantaneous span falls from roughly 16 MHz (`0.8 * 20`) to 8 MHz (`0.8 * 10`), so a full-band sweep needs more retunes. That is preferable to planning with sample bandwidth the host cannot continuously deliver. Actual whole-band revisit time must be measured on the E200 once connected; do not infer it from sample rate alone.

## Tests added

- `test_live_sweep_defaults.py`
  - locks 10 MSPS / 0 settle / 0 extra discard defaults;
  - checks explicit high-rate host warnings are visible.
- `test_segmented_sigmf.py`
  - verifies segment metadata;
  - verifies no invented global sample index or timestamp;
  - verifies replay stops at an unknown gap;
  - rejects discontinuous looping.

There is currently no `.github/workflows` Actions configuration in this repository, and this review environment could not execute a full local checkout. These tests therefore need to be run before merge:

```bash
cd antsdr/toolkit
python -m pytest tests/test_live_sweep_defaults.py tests/test_segmented_sigmf.py tests/test_cli_capture.py tests/test_file_source.py tests/test_sweep.py -q
```

Then run the whole suite:

```bash
python -m pytest -q
```

## Next engineering order

1. Run the focused + full Python tests and fix any regression before merge.
2. With E200 hardware connected, instrument retune timing and determine whether two 262,144-sample driver flushes are really necessary. Measure one vs two buffers and no-flush contamination rather than inheriting a magic number.
3. Measure real 10 MSPS full-band sweep cycle/revisit time and packet/burst hit rate. Keep explicit 15.36/20 MSPS modes for targeted snapshots, not the default continuous detector.
4. Re-run public IQ validation with segment boundaries respected. Never derive timing features across known dataset seams (including RUB-SysSec triggered concatenations).
5. Return to RF-family work: distinguish OcuSync/O3/O4-like wideband burst structure from Wi-Fi and other ISM traffic using real captures. Detection confidence must be based on RF evidence, not ODID.
6. Only after stable detection, proceed into link-content work: telemetry/location candidates first, then video/FPV content recovery. O4 encryption/proprietary framing should be treated as an evidence question, not an assumed decoder milestone.

## Merge recommendation

Do **not** merge this branch only on source review. First execute the tests above. If green, H3/H5 can be considered resolved for the current architecture and H4 can be considered resolved for the CLI path, with the generic `Sweeper` defaults and E200 two-buffer flush left as explicit follow-up items.
