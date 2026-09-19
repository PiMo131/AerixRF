---
name: uhd-sd-trial-prep
description: 2026-09-19 prep for a non-persistent second-SD-card UHD firmware trial on the E200 — image identity, checksums, host env, decision rule
metadata:
  type: project
---

2026-09-19: user approved a **non-persistent** second-microSD-card trial of MicroPhase's UHD-compatible firmware for the E200 (NOT the persistent 2R2T U-Boot change discussed in [[antsdr-firmware-strategy]] — that remains unapproved and separate). Prep-only session; the E200 itself was not touched.

**Image identified:** `MicroPhase/antsdr_uhd` release `v1.0`, asset `e200.zip` (https://github.com/MicroPhase/antsdr_uhd/releases/download/v1.0/e200.zip, sha256 `d8605c5f851ab38856dd222c55b31b25c9cb7b153174b0908d493f167c835caf`), UHD firmware version 4.1.0.0 (MicroPhase's fork, not upstream). Single-FAT32-partition layout (BOOT.bin/uImage/devicetree.dtb/uEnv.txt/uramdisk.image.gz/antsdr.bit) — simpler than the older `v0.1`/`build_sdimg.zip` fallback (UHD 3.15.0.0, needs a second ext4 rootfs partition). Both downloaded to `~/rf-tools/antsdr_uhd_image/` with a `SOURCE.md` recording provenance; no vendor-published checksums exist to cross-check against.

**Why:** the IIO/libiio path on this unit is ceiling-capped at ~15 MS/s with no overflow counter and no working timestamp (see [[firmware-streaming-ceiling]]). UHD mode is the only realistic path to a higher sustained rate and to real per-sample timing on this specific board — worth trialing on a spare card before ruling it in or out.

**Stronger citation found this session:** antsdr-doc-en's E200 Getting Started Guide explicitly states the boot-mode DIP switch (labeled BOOT/QSPI/SD, below the Ethernet port) determines QSPI-vs-SD boot, and "UHD firmware can only be started under the SD card" — i.e. UHD mode is *defined* as SD-card boot, which structurally cannot overwrite QSPI. This upgrades the §9 INFERRED non-destructiveness claim in `research/briefs/antsdr-e200.md` closer to DOCUMENTED (still not a literal vendor sentence "QSPI is untouched," but the mode definition itself makes overwrite impossible via this switch).

**Host env prepared (no sudo):** micromamba env `antsdr-uhd` with stock `uhd` 4.11.0.0 from conda-forge; `uhd_find_devices` runs cleanly (binary/Boost/libusb healthy), correctly finds nothing with no device attached. **Important:** `antsdr_uhd`'s own `host/README.md` states the E200 needs a custom "ANT" UHD transport plugin (`-DENABLE_ANT=ON`) not present in mainline UHD — so a stock-UHD failure to enumerate the E200 later is expected/documented, not new evidence against the firmware. A no-sudo source-build recipe for the fork (using a user-writable `CMAKE_INSTALL_PREFIX`, conda-forge-provided boost-cpp/libusb/cmake instead of apt) is written into `docs/field/antsdr-uhd-sd-trial.md` but NOT executed this session (tool-budget tradeoff) — do this first if the stock-UHD path fails to see the device once the card actually boots.

**Decision rule** (already written into the field doc, repeating here so it survives independently): adopt UHD firmware only if ≥20 MS/s sc16 sustained with zero overflow over a 10-minute soak AND `rx_metadata.time_spec` verified continuous. Otherwise stay on IIO — this is a comparative trial on a second card, not a commitment to switch.

**How to apply:** read `docs/field/antsdr-uhd-sd-trial.md` for the full physical procedure (flashing needs sudo for the raw block device — different scope than the no-sudo host-software constraint), acceptance test matrix, and the `uhd`-backend design note. Do not re-derive the image URL/checksum/layout facts above; they're already verified.
