---
name: antsdr-e200-bootstrap
description: How to reach and query the ANTSDR E200 from this host — network config, tooling env, no-sudo constraints
metadata:
  type: project
---

Access setup for AERIX RF's ANTSDR E200 unit (established 2026-09-18, confirmed working this session):
- Device at `ip:192.168.1.10` (Xilinx MAC OUI `00:0a:35`), host at `192.168.1.20/24` on `enp0s31f6`, nmcli connection profile `antsdr-e200-static`.
- libiio 0.26 + python `iio` bindings live in a micromamba env at `/home/jarvis/aerix-rf/.antsdr-tools/mamba/envs/antsdr`. Run scripts via `~/.local/bin/micromamba run -p /home/jarvis/aerix-rf/.antsdr-tools/mamba/envs/antsdr python <script>.py`. There is no system-wide `iio_info`/python-iio install — always go through that env.
- No sudo available in this environment. `/dev/ttyUSB0` (UART console) exists but is inaccessible because the user isn't in the `dialout` group — this blocks serial-console-based recovery or U-Boot env inspection until a human runs `sudo usermod -aG dialout $USER` and re-logs-in. Recorded as an open TODO, not resolved.

**Why:** re-establishing this took real setup work (network profile, micromamba env bootstrap) in a prior session; rediscovering it wastes turns.

**How to apply:** any future ANTSDR session should start by confirming `ip:192.168.1.10` still responds (`micromamba run -p .../antsdr python -c "import iio; print(iio.Context('ip:192.168.1.10').attrs)"` or plain `iio_info -u ip:192.168.1.10` inside the env) rather than re-deriving network/tooling setup from scratch. Full device capability facts are in [[device-facts-e200]] and `research/briefs/antsdr-e200.md`, not here.
