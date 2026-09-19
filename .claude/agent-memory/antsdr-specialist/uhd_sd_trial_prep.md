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

**2026-09-19 (later same day): fork host build (source-built ANT-transport UHD) — done, no device access.** Cloned `MicroPhase/antsdr_uhd` `master` @ `b5ebd04a` (host/ tree, matches image UHD_VERSION 4.1.0.0) to `~/rf-tools/antsdr_uhd_src`. Separate micromamba env `antsdr-uhd-fork` (distinct from the stock-UHD `antsdr-uhd` env above — do not mix; fork speaks ABI 4.1.0.0, stock is 4.11) with `cmake ninja boost-cpp libusb python numpy`.

Two build blockers hit and fixed, both are environment/toolchain issues, not code bugs in the fork:
1. **CMake≥3.5 policy error** (`CMakeRC.cmake:63 cmake_minimum_required`) — this 2021-era fork's CMake files predate CMake's removal of compatibility with `<3.5` (conda-forge's cmake was 4.4.3). Fix: add `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` to the configure command. No source patch needed.
2. **`boost/filesystem/convenience.hpp: No such file`** building `mpmd_image_loader.cpp` — conda-forge's `boost-cpp` 1.85.0 removed the deprecated `filesystem/convenience.hpp` header that this fork's mpmd code still includes. Fix: pin `boost-cpp`/`libboost`/`libboost-devel`/`libboost-headers` to **1.84.0** in the `antsdr-uhd-fork` env (`micromamba install -y -p <env> -c conda-forge "boost-cpp=1.84.0" "libboost=1.84.0" "libboost-devel=1.84.0" "libboost-headers=1.84.0"`) — 1.84 still ships the header. **If a future rebuild starts with a fresh env, pin boost to 1.84.0 (or lower) from the start** rather than hitting this again; conda-forge does not carry an obviously-labeled "last version with convenience.hpp" so 1.84.0 is the known-good pin.

Full working configure line (from `~/rf-tools/antsdr_uhd_src/host`, prefix `~/rf-tools/uhd-antsdr`):
```
cmake -S host -B host/build -G Ninja \
  -DCMAKE_INSTALL_PREFIX=$HOME/rf-tools/uhd-antsdr -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_PYTHON_API=ON -DENABLE_EXAMPLES=ON -DENABLE_TESTS=OFF \
  -DENABLE_DOXYGEN=OFF -DENABLE_MANUAL=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5
```
Enabled components with this config: LibUHD, C API, Python API, Examples, Utils, USB, B100, B200, ANT, USRP1, USRP2, X300, MPMD, SIM, N300, N320, E320, E300, X400, OctoClock, Man Pages (494 ninja targets). `ANT` (the E200-specific transport) is present, confirming the source tree matches the image.

**Build launched detached** (`setsid nohup ... ninja -j 20 && ninja install`) — check completion via `tail -f ~/rf-tools/antsdr_uhd_src/build.log` (look for line `BUILD_INSTALL_EXIT=0`) and confirm `~/rf-tools/uhd-antsdr/lib/libuhd.so*` + `~/rf-tools/uhd-antsdr/bin/uhd_find_devices` exist. `~/rf-tools/uhd-antsdr/ENV.sh` sources PATH/LD_LIBRARY_PATH/PYTHONPATH/UHD_IMAGES_DIR for this prefix (also adds the fork env's lib dir to LD_LIBRARY_PATH since libuhd links against that env's boost/libusb .so, and exports `UHD_ANTSDR_PYTHON` pointing at that env's python3.11). `~/rf-tools/uhd-antsdr/accept.sh` runs `uhd_find_devices`/`uhd_usrp_probe`, then a `rx_samples_to_file` sweep (12.288/13.44/15.36/20/30.72 MS/s x sc16/sc8, 60s each, overflow-'O'-count parsed from stats), then an optional 600s soak gated on `SOAK_RATE`/`SOAK_TYPE` env vars (deliberately not auto-selected — a human should pick the soak rate from the sweep summary first), then a Python `uhd.usrp.MultiUSRP` timestamp-continuity check (only runs if `import uhd` succeeds). **None of this has been run against real hardware yet** — build-only session, no E200 attached/network-reachable in UHD mode. Do not treat build success as evidence of the ≥20 MS/s decision-rule outcome; that still requires the actual hardware trial via `accept.sh`.
