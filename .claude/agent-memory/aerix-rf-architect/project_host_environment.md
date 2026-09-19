---
name: host-environment-2026-09
description: Dev machine constraints observed 2026-09-18 — no passwordless sudo, user not in dialout, no SDR tools installed, 1.7TB NVMe free, E200 likely on enp0s31f6 + CH340 UART.
metadata:
  type: project
---

Dev host (Debian 13, 24 cores, 62 GB, 1.8 TB NVMe at `/`, ~1.7 TB free on 2026-09-18) is NOT the field box — nothing SDR-related was installed (no libiio/UHD/Soapy/hackrf/aria2c). `sudo` needs a password so agents cannot apt-install; user-space installs (micromamba, `~/.local`, uv) are the workaround. User `jarvis` is in `netdev` and `sudo` groups but NOT `dialout`, so `/dev/ttyUSB0` (CH340, probably E200 UART console) is inaccessible until `usermod -aG dialout`. Ethernet `enp0s31f6` had a 1 GbE link with no IPv4 — the E200 is presumably on it.

**Why:** These blocked/shaped the ANTSDR discovery in the first session.

Tooling pitfall: `pgrep -f <pattern>` from the Bash tool matches the tool's own `bash -c` wrapper (its command line contains the pattern) — count processes with `ps -eo args | grep -E '^[^ ]*python'` style anchors instead, or you will "find" orphans that are your own shell.

**How to apply:** Re-verify before relying on it (user may have granted sudo/dialout since). When a task needs root, produce an exact command list for the user instead of retrying. Dataset root is `~/rf-datasets/` (see [[antsdr-primary-pivot]]).

Update 2026-09-19: user set `net.core.rmem_max/wmem_max=50000000` (persistent in /etc/sysctl.d/90-aerix-uhd.conf) —
UHD-mode soaks are no longer blocked on host buffers. User added himself to `dialout` (effective after re-login).
`sysctl` binary is not on PATH for the non-root user — read /proc/sys/net/core/* instead. E200 (UHD SD image) is at
192.168.1.10.
