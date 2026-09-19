# ANTSDR E200 UHD-image SD-card trial (non-persistent)

Status: PREPARATION ONLY as of 2026-09-19. No SD card has been flashed. The E200's QSPI IIO image (`ip:192.168.1.10`, stock Pluto-compatible, `ad9364`, single RX) has NOT been touched by this prep. Approved: a second, spare microSD card booted in UHD mode for an acceptance trial. NOT approved: any persistent U-Boot env / 2R2T device-tree change (that remains a separate, unapproved decision — see `research/briefs/antsdr-e200.md` §9 and agent-memory `firmware_strategy.md`).

Downloaded image files + checksums: `~/rf-tools/antsdr_uhd_image/SOURCE.md`.

## Why this is expected to be non-destructive

The E200 has a physical DIP switch below the Ethernet port labeled `BOOT`, `QSPI`, `SD` (DOCUMENTED, antsdr-doc-en Getting Started Guide). Per that same guide: the stock/Pluto IIO firmware boots from onboard QSPI flash; **"UHD firmware can only be started under the SD card"** — i.e., UHD mode is defined as booting from a removable SD card, never from QSPI. Flipping the switch to SD and inserting a card that does not contain the current QSPI image cannot overwrite QSPI; reverting is flipping the switch back to QSPI (the spare SD card does not even need to be removed first, though removing it is an extra precaution). This is a stronger, more direct citation than the community-inference note already in the brief.

## What the user must physically do

1. **Get a spare microSD card**, ≥8 GB, class 10 (or better; sequential write speed matters less than the network path, but avoid unbranded/no-name cards — corruption on cheap cards is the most common cause of "UHD image doesn't boot" reports in the wider USRP-embedded community).
2. **Do NOT reuse the E200's own original SD card** if one shipped with the unit and already has vendor UHD firmware on it — check first; if MicroPhase shipped a card with UHD content pre-loaded, that may already be the fastest path and needs no flashing at all. Confirm this before buying/flashing a new card.
3. **Flash the card from this host.** microSD writing needs raw block-device access, which is not available to an unprivileged user by default:
   - If the reader/card shows up as a **removable** block device the login session owns (check `udisksctl status` / `lsblk` — some desktop environments grant polkit rules for user-owned removable media), `dd` or `udisksctl` may work without `sudo`. Check first with `lsblk -o NAME,RM,SIZE,TYPE,MOUNTPOINT` — the target device's `RM` column should read `1`.
   - Otherwise this step **requires `sudo`** (writing a raw block device is a privileged operation on this host regardless of the "no sudo for the host env" constraint that applies to the UHD *software* setup — those are different scopes). Exact command, after confirming `/dev/sdX` is the card and NOT any internal disk:
     ```bash
     lsblk   # identify the card, e.g. /dev/sdX — TRIPLE-CHECK, this is destructive to the card
     sudo dd if=/dev/zero of=/dev/sdX bs=1M count=16 status=progress   # wipe old partition table
     sudo mkfs.vfat -F 32 /dev/sdX1   # after partitioning FAT32 (see step 4)
     ```
   - The user should run this personally or with the architect's explicit go-ahead per session — this task does not execute it.
4. **Partition and copy files** (v1.0 `e200.zip`, RECOMMENDED first attempt):
   - Create a single FAT32 partition spanning the card (v1.0's rootfs is an initramfs bundled into `uramdisk.image.gz`, so no second ext4 partition is needed — simpler than the v0.1 fallback).
   - Copy all 5 boot-relevant files from the unzipped `uhd/` directory onto that FAT32 partition root: `BOOT.bin`, `uImage`, `devicetree.dtb`, `uEnv.txt`, `uramdisk.image.gz`. (`antsdr.bit` is the bitstream — confirm whether `BOOT.bin` already embeds it or it must also be copied loose; MicroPhase's own instructions say copy "all of these files," so include it too, doesn't hurt.)
   - If v1.0 fails to boot cleanly, fall back to v0.1 `build_sdimg.zip`, which needs a second **ext4** partition with `e200_rootfs.tar.gz` extracted onto it (classic two-partition Zynq SD layout: `BOOT.bin uImage devicetree.dtb uEnv.txt antsdr_e200.bit` on FAT32 partition 1, rootfs tarball contents on ext4 partition 2).
5. **Set the boot-mode DIP switch to `SD`.** Insert the card. Power-cycle the E200 (full power cycle, not just an IIO-side reboot).
6. **Wait for boot** — LED should flash once Linux is running (DOCUMENTED behavior per the getting-started guide). Give it ~30-60 s.
7. **Set host NIC** to the same subnet the E200 already uses in UHD mode: static IP `192.168.1.10` is the E200's documented UHD-mode default — this happens to be the **exact same address** our unit already uses in IIO mode (`nmcli` profile `antsdr-e200-static`, host `192.168.1.20/24`, interface `enp0s31f6` — see agent-memory `device_facts_e200.md`). No host network reconfiguration should be needed; verify with `ping 192.168.1.10`.
8. **Confirm Gigabit link speed.** MicroPhase's docs are explicit: "The ethernet of ANTSDR-E200 ... can only work at 1000M speed, make sure the connection speed of your computer to the device is 1000M." Check with `ethtool enp0s31f6 | grep Speed` on the host before running any rate test — a 100M negotiated link would look like a firmware throughput failure but actually be a cabling/NIC/switch problem.
9. **To revert:** power off, flip the DIP switch back to `QSPI`, power on. The original IIO image at `ip:192.168.1.10` (Pluto-compatible, single RX) should come back untouched, since it was never written to. Re-run `iio_info -u ip:192.168.1.10` afterward as a sanity check that the QSPI image is intact and unchanged.

## Host software (prepared this session, no sudo)

- micromamba env `antsdr-uhd` created with `uhd` from **conda-forge** (version **4.11.0.0**, mainline/stock UHD — NOT the MicroPhase fork). `uhd_find_devices` runs and correctly reports "No UHD Devices Found" with nothing connected — confirms the binary and Boost/libusb runtime are healthy.
- **Important documented caveat, found in `host/README.md` of the `antsdr_uhd` repo itself:** the E200 needs a custom "ANT" UHD transport/motherboard plugin (`-DENABLE_ANT=ON` at UHD build time) that does not exist in mainline UHD. This means stock conda-forge UHD 4.11 is very likely to still report "No UHD Devices Found" even with a live, correctly-booted E200 in UHD mode on the wire — the gap is almost certainly a missing device plugin, not a network/boot problem. **Do not conclude "UHD firmware doesn't work" from a stock-UHD `uhd_find_devices` failure alone; that is an expected/documented limitation, not new evidence.**
- **Fallback (not built this session, budget-limited):** if stock UHD fails to enumerate the device after boot is otherwise confirmed healthy (ping works, correct link speed), build the MicroPhase fork from source, no sudo required for the parts that matter:
  ```bash
  micromamba create -n antsdr-uhd-fork -c conda-forge cmake ninja boost-cpp libusb pkg-config python numpy mako ruamel.yaml
  git clone --depth 1 https://github.com/MicroPhase/antsdr_uhd.git
  cd antsdr_uhd/host
  micromamba run -n antsdr-uhd-fork cmake -S . -B build-antsdr \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$HOME/.local/antsdr-uhd-fork" \
    -DENABLE_ANT=ON -DENABLE_USB=ON -DENABLE_X400=OFF -DENABLE_N320=OFF -DENABLE_N300=OFF -DENABLE_E320=OFF -DENABLE_E300=OFF -DENABLE_B200=OFF -DENABLE_USRP1=OFF -DENABLE_USRP2=OFF
  micromamba run -n antsdr-uhd-fork cmake --build build-antsdr --parallel
  cmake --install build-antsdr    # writes only under $HOME/.local/antsdr-uhd-fork — no sudo needed with this prefix
  ```
  The upstream README uses `sudo cmake --install` with `/opt/...` — substitute a user-writable `CMAKE_INSTALL_PREFIX` as above to avoid sudo entirely. Untested this session; flag to the architect if this branch is needed.

## Acceptance experiment

Once `uhd_find_devices` / `uhd_usrp_probe` see the device (with whichever UHD build works — stock or fork), run, for each rate in **{12.288, 13.44, 15.36, 20, 30.72} MS/s**, for **both sc16 and sc8**, for **60 s each**:

```bash
uhd_rx_samples_to_file --args "addr=192.168.1.10" --rate <RATE> --freq 2440e6 \
  --duration 60 --file /dev/null --type <sc16|sc8> --channels 0
```

Record for each run:
- **Overflow (`O`) count** printed by the UHD console during streaming — must be **zero**.
- **Achieved vs requested rate** (compare bytes-written / duration against expected).
- **Timestamp continuity**: use the Python `uhd` API (`multi_usrp.recv()` loop) instead of the CLI tool for at least one rate, and check `rx_metadata.time_spec` advances by exactly `nsamps / rate` between successive `recv()` calls with no gaps — this is the property IIO mode on this unit does NOT give us (`samples_pps` → ENODEV on the stock image; see agent-memory `device_facts_e200.md`), so it is the main reason UHD mode would be worth adopting at all.
- **2R2T availability**: run `uhd_usrp_probe` and check whether both RX channels (`channels 0,1`) are enumerated and independently streamable at the target rate, or whether the UHD-mode firmware also ships as a 1R1T image (unconfirmed — the release notes don't say either way; the antsdr_uhd repo's `firmware/` FPGA source would need inspection to be sure, out of scope for this trial).

Also re-run the **10-minute soak** (not just 60 s) at whichever rate looks best, mirroring the same BIST-style long-run methodology already used for the IIO ceiling measurement (agent-memory `silent_loss_bist_measurement.md`), before trusting a "clean" short run.

## Decision rule

**Adopt the UHD image as our working firmware only if, at the SAME rate:**
1. ≥ 20 MS/s sustained (sc16) for the full 10-minute soak, **and**
2. **zero** overflow (`O`) events over that 10 minutes, **and**
3. `rx_metadata.time_spec` is verified continuous (no unexplained jumps) across the run.

If all three hold, this beats the current IIO ceiling (~15 MS/s, no overflow signal at all, no timestamp) enough to justify the added integration cost of a `uhd` backend. If any fail — report the actual achieved ceiling, overflow behavior, and timestamp behavior, and **stay on IIO** as the default backend; UHD-mode findings still get recorded as useful ceiling/timestamp data even if not adopted.

This trial does not touch or replace the current QSPI IIO deployment regardless of outcome; it is purely comparative, on a second card.

## What an AERIX `uhd` backend would need (design note only — no implementation here)

A `ProcessIQSource`-shaped producer variant, analogous to the existing `antsdr_proc` libiio producer:
- Use the Python `uhd` API (`uhd.usrp.MultiUSRP`, `recv_streamer` + `recv()` loop) instead of `iio.Context`/`iio.Buffer`.
- Map `rx_metadata.time_spec` into whatever timestamp field the common IQ abstraction/event schema exposes — this device would be the first backend able to populate it meaningfully.
- Map `rx_metadata.error_code` (esp. `ERROR_CODE_OVERFLOW`) into the existing `stream_end_reason` / dropped-sample accounting already built for `antsdr_proc`, rather than inventing a new field.
- Decide gain/AGC mapping (`multi_usrp.set_rx_gain` / `set_rx_agc`) against the existing common-abstraction gain controls.
- If 2R2T is confirmed available in UHD mode, decide whether the common abstraction should grow a 2-channel concept now or whether AERIX still only consumes channel 0 for the near term (matches the existing 1R1T IIO posture — see `firmware_strategy.md`).
- Process boundary should mirror `antsdr_proc`: keep the UHD/Boost C++ runtime in a separate OS process from the Python analysis pipeline, communicating over the same shared-memory/queue mechanism already validated for gap-free delivery (see `T7 accepted` commit, gap-free BIST-verified) — do not assume that guarantee transfers to a new producer without re-running the same BIST methodology.

This is a design note for the architect/`sdr-backend-builder`, not an implementation instruction.
