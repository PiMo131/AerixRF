"""Minimal fake ``uhd`` module, importable by a real subprocess (T8).

Used ONLY by ``producer_main.py``'s ``--fake-uhd`` flag so the whole ``uhd``
producer path (device open/configure/readback/tune/recv, ring write, control
channel) can be exercised end to end -- via a real
``python -m aerix_rf.sdr.producer_main`` subprocess -- with no ANTSDR/UHD
hardware. Separate, smaller copy of any fake used from pytest directly (none
yet): this one must be importable from a real subprocess by module path.

Mimics only the uhd python API shapes ``uhd_device.UhdDevice`` calls:
``usrp.MultiUSRP(addr)``, ``set_rx_rate/freq/gain/antenna/bandwidth``,
``get_rx_rate/freq/gain/antenna/bandwidth``, ``get_mboard_name``,
``get_usrp_rx_info``, ``get_time_source``/``get_clock_source``,
``usrp.StreamArgs(cpu, otw)``, ``usrp.get_rx_stream(args)``,
``rx.get_max_num_samps()``, ``rx.issue_stream_cmd(cmd)``,
``rx.recv(buf, md, timeout)``, ``types.RXMetadata``,
``types.RXMetadataErrorCode``, ``types.StreamCMD``/``StreamMode``,
``libpyuhd.types.tune_request``.

Emits deterministic sc16 packets (I ramps, Q constant, same convention as
``_fake_iio.py``'s ramp chunk) packed two-int16-per-int32 the way this fork's
"sc16" cpu format buffer is laid out (see ``uhd_device.py``'s ``.view(np.int16)``
read). ``overflow_after``: the Nth good packet (0-indexed) is preceded by one
injected ``ERROR_CODE_OVERFLOW`` recv() result, then the next good packet's
``time_spec`` is advanced by ``gap_samples`` worth of time so the device-side
gap is independently derivable exactly as real UHD overflow accounting would
produce.
"""

from __future__ import annotations

import types
from typing import Optional

import numpy as np

PKT_SAMPLES = 32  # small, deliberately far smaller than any realistic chunk_samples


def build_fake_uhd(*, overflow_after: Optional[int] = None, gap_samples: int = 100,
                    sample_rate: float = 200_000.0) -> types.ModuleType:
    state = {"pkt_index": 0, "overflow_fired": False, "t": 0.0}

    class ErrCode:
        none = "none"
        overflow = "overflow"
        timeout = "timeout"

    class RXMetadataErrorCode:
        none = ErrCode.none
        overflow = ErrCode.overflow
        timeout = ErrCode.timeout

    class TimeSpec:
        def __init__(self, t: float):
            self._t = t

        def get_real_secs(self) -> float:
            return self._t

    class RXMetadata:
        def __init__(self):
            self.error_code = ErrCode.none
            self.has_time_spec = True
            self.time_spec = TimeSpec(0.0)

    class TuneRequest:
        def __init__(self, freq_hz: float):
            self.target_freq = freq_hz

    class StreamCMD:
        def __init__(self, mode):
            self.stream_mode = mode
            self.stream_now = False

    class StreamMode:
        start_cont = "start_cont"
        stop_cont = "stop_cont"

    class StreamArgs:
        def __init__(self, cpu_format: str, otw_format: str):
            self.cpu_format = cpu_format
            self.otw_format = otw_format
            self.channels: list[int] = []

    class RxStreamer:
        def __init__(self):
            self._started = False

        def get_max_num_samps(self) -> int:
            return PKT_SAMPLES

        def issue_stream_cmd(self, cmd: StreamCMD) -> None:
            self._started = cmd.stream_mode == StreamMode.start_cont

        def recv(self, buf, md: RXMetadata, timeout: float) -> int:
            idx = state["pkt_index"]
            if overflow_after is not None and idx == overflow_after and not state["overflow_fired"]:
                state["overflow_fired"] = True
                md.error_code = ErrCode.overflow
                md.has_time_spec = False
                # The gap itself: advance the device clock without emitting
                # any samples for it, so the NEXT good packet's time_spec
                # shows exactly `gap_samples` worth of missing time.
                state["t"] += gap_samples / sample_rate
                return 0

            md.error_code = ErrCode.none
            md.has_time_spec = True
            md.time_spec = TimeSpec(state["t"])
            n = PKT_SAMPLES
            k = np.arange(n, dtype=np.int64) + idx * n
            i_vals = ((k % 2048) - 1024).astype(np.int16)
            q_vals = np.full(n, 7, dtype=np.int16)
            packed = np.empty(n, dtype=np.int32)
            iq16 = np.empty(n * 2, dtype=np.int16)
            iq16[0::2] = i_vals
            iq16[1::2] = q_vals
            packed[:] = iq16.view(np.int32)
            buf[0, :n] = packed
            state["t"] += n / sample_rate
            state["pkt_index"] += 1
            return n

    class MultiUSRP:
        def __init__(self, addr: str):
            self.addr = addr
            self._rate = 0.0
            self._freq = 0.0
            self._gain = 0.0
            self._antenna = ""
            self._bandwidth = None

        def set_rx_rate(self, rate, chan=0):
            self._rate = float(rate)

        def get_rx_rate(self, chan=0):
            return self._rate

        def set_rx_freq(self, tune_req, chan=0):
            self._freq = float(tune_req.target_freq)

        def get_rx_freq(self, chan=0):
            return self._freq

        def set_rx_gain(self, gain, chan=0):
            self._gain = float(gain)

        def get_rx_gain(self, chan=0):
            return self._gain

        def set_rx_antenna(self, antenna, chan=0):
            self._antenna = antenna

        def get_rx_antenna(self, chan=0):
            return self._antenna

        def set_rx_bandwidth(self, bw, chan=0):
            self._bandwidth = float(bw)

        def get_rx_bandwidth(self, chan=0):
            return self._bandwidth

        def get_mboard_name(self, chan=0):
            return "FAKE-B210"

        def get_usrp_rx_info(self, chan=0):
            return {"mboard_serial": "FAKE0000"}

        def get_time_source(self, chan=0):
            return "internal"

        def get_clock_source(self, chan=0):
            return "internal"

        def get_rx_stream(self, stream_args: StreamArgs):
            return RxStreamer()

    usrp_mod = types.ModuleType("uhd.usrp")
    usrp_mod.MultiUSRP = MultiUSRP
    usrp_mod.StreamArgs = StreamArgs

    types_mod = types.ModuleType("uhd.types")
    types_mod.RXMetadata = RXMetadata
    types_mod.RXMetadataErrorCode = RXMetadataErrorCode
    types_mod.StreamCMD = StreamCMD
    types_mod.StreamMode = StreamMode

    libpyuhd_types_mod = types.ModuleType("uhd.libpyuhd.types")
    libpyuhd_types_mod.tune_request = TuneRequest
    libpyuhd_mod = types.ModuleType("uhd.libpyuhd")
    libpyuhd_mod.types = libpyuhd_types_mod

    mod = types.ModuleType("uhd")
    mod.usrp = usrp_mod
    mod.types = types_mod
    mod.libpyuhd = libpyuhd_mod
    return mod
