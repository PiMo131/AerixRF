---
name: hackrf-couplings-in-abstraction
description: The non-obvious HackRF assumptions baked into the supposedly hardware-neutral IQSource/session layer, and which one is worst
metadata:
  type: project
---

The `IQSource`/`IQWindow`/`ReceiverCapabilities` contract is genuinely hardware-neutral in
shape, but several HackRF assumptions live *outside* it and are easy to miss when someone
says "the abstraction already exists" (assessed 2026-09-18):

- **The scan path is not part of the abstraction at all.** `aerix-rf scan` / `baseline`
  shell out to the `hackrf_sweep` binary. There is no ANTSDR equivalent, so those
  commands simply cannot run on any other receiver. This is the largest hidden coupling
  and the one most likely to be overlooked, because `IQSource` looks clean.
- `to_cs8`/`_read_cs8` hardcode int8 ±128 as *the* on-disk IQ format.
- There is no analog-bandwidth field anywhere (`Config`, `IQWindow`, `session.json`) —
  HackRF has no settable RX filter, AD9361 does.
- Gain is modelled as `lna`/`vga`/`amp`; there is nowhere to record an AGC *mode*, whose
  absence silently invalidates RSSI comparison between captures.
- `captured_at` is host wall clock only, with no field that says so — so nothing warns a
  future reader that the record cannot support TDOA.
- `make_source()` ends in `RuntimeError("no usable HackRF backend")`; `cmd_info` opens a
  HackRF directly with hardcoded 20e6/2440e6.

Reassuring counterpoints: all five `IQWindow(...)` construction sites use keyword args
(appending defaulted fields is safe), `capabilities` has only two consumers
(`cli.py`, `main.py`, both reading only `receiver_type`), and `Session.open()` does no
`schema_version` validation (additive schema changes load in old readers).

**Why:** a previous framing treated "the hardware abstraction is built" as done; it is
built for the *stream*, not for sweep, gain, bandwidth, format, or timing.

**How to apply:** when scoping any cross-receiver work, check the sweep path and the
session on-disk format explicitly — reading `sdr/capture.py` alone will make the job look
smaller than it is. Related: [[antsdr-backend-interface-decisions]].
