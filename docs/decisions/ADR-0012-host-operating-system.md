# ADR-0012: Host operating system: Windows for capture and analysis, Linux for firmware work

- **Status:** Accepted (answers the maintainer's question of 2026-09-06,
  "should we move this project to a Windows machine?")
- **Date:** 2026-09-06
- **Sources:** `analogdevicesinc/libiio` (Azure pipeline and v0.26 release
  assets, read), `analogdevicesinc/pyadi-iio` (`.github/workflows/win-test.yml`,
  read), `MicroPhase/antsdr_uhd` (`host/README.md`, read),
  `open-sdr/openwifi` (`README.md`, read), `../../research/hardware-e200.md`

## Context

The maintainer has a Windows machine available and asked whether the project
should move to it. The answer divides cleanly along one line: what talks to
the board over Ethernet, and what builds or boots firmware.

**The toolkit itself is not the question.** `antsdr_toolkit` is Python with
numpy and scipy, and `remoteid` is pure standard library. It runs anywhere.

**Nor is throughput.** The E200 is CPU-bound in `iiod` on its own Cortex-A9 at
11 to 13 MSPS *(verified: verdict 2, `host-streaming-tiers`)*, so any modern
host has orders of magnitude of headroom. The host is not the bottleneck and
choosing an operating system for speed would be solving the wrong problem.

**What settles it is the connection.** The E200 is reached over Ethernet at a
network URI, never over USB. That matters more than it sounds: the notorious
PlutoSDR-on-Windows driver misery is entirely a `usb:` problem, and the E200
does not go near it.

The evidence on Windows support:

- Analog Devices builds libiio for Windows on VS2022 and VS2026, plus MinGW,
  and the v0.26 release carries a `Windows.zip` containing
  `Windows-VS-2022-x64` and siblings.
- pyadi-iio runs a Windows CI job (`win-test.yml`, `os: ["windows-latest"]`),
  so it is tested there and not merely assumed to work.
- MicroPhase's UHD fork documents an Ubuntu build with `apt-get`
  dependencies, and mentions no other platform.
- openwifi's development workflow is Linux throughout: `dd`, `fdisk`, `scp`,
  shell scripts. Windows appears only as a community tips thread.

## Decision

**Run day-to-day capture and analysis on Windows. Keep a Linux path for
firmware work, and do not build it until something needs it.**

| Task | Windows | Notes |
|---|---|---|
| The whole `antsdr_toolkit`, its tests and its CLI | yes | Python only |
| Capture over Ethernet with pyadi-iio, stock IIO firmware | yes | tested in pyadi-iio's own CI |
| Snapshot capture up to 61.44 MSPS | yes | which is what analog video at 20 MSPS needs (ADR-0004) |
| Remote ID from a monitor-mode adapter | no, in practice | monitor mode on Windows needs specific hardware and drivers; use Linux or a separate node |
| UHD personality for continuous 20 MSPS | no | Ubuntu build only |
| openwifi | no | Linux host, kernel modules, SD-card image build |
| Rebuilding firmware or FPGA images | partly | Vivado runs on Windows; petalinux and buildroot do not |

WSL2 is deliberately **not** the recommendation, and the reason is sharper
than "it adds a layer". It buys nothing for the capture path, which is an
outbound TCP connection the host makes to the board and works either way. What
its default NAT breaks is exactly one existing feature: the new-firmware
DroneID bridge, where the *board* dials in to the host on TCP 52002. An
inbound connection from the LAN cannot cross that NAT at all. Windows 11
22H2's `networkingMode=mirrored` restores it, at the cost of a newer network
path with live defects. Taking on that trade to reach a Linux userspace that
still cannot build the UHD fork or run openwifi is a poor bargain.

## Consequences

- Four Windows-specific traps are known in advance and are worth writing down
  because each costs an afternoon:
  1. **The installer is not where the documentation says it is.** ADI's own
     docs point at the GitHub release for `libiio-setup.exe`, and it is not
     published there; the release carries `Windows.zip` instead. Unpack it and
     put `Windows-VS-2022-x64/libiio.dll` on the PATH, or fetch the installer
     from ADI's SWDownloads site.
  2. **`pip install pylibiio` ships no DLL.** It looks for `libiio.dll` by
     name, so the native runtime has to be installed first.
  3. **Do not install the PlutoSDR USB drivers.** They serve `usb:` URIs only
     and are the source of the classic Windows driver trouble. The E200 needs
     none of it.
  4. **The DroneID firmware bridge needs an inbound firewall rule.** The two
     wire formats in `bridges/dji_droneid.py` run in opposite directions, and
     only one of them is a problem. The legacy binary path is fine: the host
     connects out to the board on TCP 41030. The new firmware path is the
     reverse, with the board connecting *in* to the host on TCP 52002, or
     pushing UDP there. Windows Defender Firewall blocks that by default and
     the symptom is silence, not an error. Open TCP and UDP 52002 inbound
     before concluding the firmware is not reporting.
- Address the board by explicit URI (`ip:192.168.1.10`), not by discovery.
  mDNS binds UDP 5353 as a listener, which Windows Defender Firewall gates,
  and an explicit URI sidesteps the whole question.
- Choosing Windows now **defers** a Linux requirement rather than removing it.
  The moment continuous 20 MSPS or openwifi is wanted, a Linux host is needed.
  The cheap answer at that point is a small Linux machine next to the board,
  not a conversion of the desktop.
- The analog video work is unaffected: 20 MSPS as a snapshot on the stock
  firmware is enough for whole NTSC or PAL fields, and that path is available
  on Windows today.

## Alternatives considered

- **Move everything to Linux now.** Correct in the long run and wrong for the
  maintainer's stated constraint, which is that there is no time. It converts
  a machine before anything has been captured.
- **WSL2 as a middle path.** Rejected above: cost without benefit for the
  path actually being used first.
- **Dual boot.** Keeps both options at the price of rebooting to change task,
  which is exactly the friction that stops short sessions from happening.
