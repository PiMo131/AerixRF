"""Verified MicroPhase ANTSDR E200 hardware facts, rate planning and operator notes.

This module is pure data plus a few helpers; it imports nothing beyond the
standard library and is safe to import anywhere (CLI ``--help``, docs, tests).
Everything else in the toolkit that needs a number about the E200 should read
it from :data:`E200` instead of hard-coding it.

Sources (all read in the research clones, file references in the notes below)
-----------------------------------------------------------------------------
* https://github.com/MicroPhase/antsdr_doc_en - ``AntsdrE200_RF_parameters.md``
  (selection table: ``SMA:1T1R IPEX:1T1R``, instantaneous bandwidth ``56M
  (9361) / 20M (9363)``, ``Transmission bandwidth to host 20MSPS``, 1G ETH,
  10M/PPS), ``AntsdrE200_Reference_Manual.md`` (Zynq-7020, AD9361/9363, 12-bit
  ADC, LO 70 MHz-6 GHz for AD9361 / 325 MHz-3.8 GHz for AD9363),
  ``AntsdrE200_Unpacking_examination.md`` (Pluto firmware in QSPI, DIP switch
  BOOT/QSPI/SD, ``192.168.1.10``, ``root``/``analog``),
  ``set_the_iio_firmware_ip.md`` (UHD firmware ``root``/``microphase``,
  ``ip_set``), ``AntsdrE200_UHD.md`` (UHD probe: PGA gain 0-76 dB, BW 200 kHz-56
  MHz), ``Antsdr-Clock-calibration.md`` (E200 page defers to the E310 page:
  ``ad5660mp`` sysfs procedure), ``schematic/ANT-E200_Public.pdf`` (sheet 11:
  transceiver U11 is an AD9363; sheet 12: J3 SMA = RX1A, J6 u.FL = RX2A; sheet
  13: 40 MHz TCXO +/-0.5 ppm tuned by DAC U60).
* https://github.com/MicroPhase/antsdr-fw-patch - ``README.md`` "Support 2r2t
  mode" (the ``fw_setenv`` sequence and the SD ``uEnv.txt`` edits);
  ``patch/e200/0001-add-support-linux.patch`` (``zynq-e200.dtsi``: default
  30.72 MSPS, 18 MHz RF bandwidth, RX LO 2.4 GHz, slow-attack AGC; U-Boot
  ``mode=1r1t`` strips ``adi,2rx-2tx-mode-enable``); HDL patch
  (``axi_ad9361`` CMOS single port, ``rx_clk`` period 16.27 ns = 61.44 MHz,
  FIR decimator wired only to channel 0).
* https://github.com/MicroPhase/antsdr_uhd - ``host/lib/usrp/ant/ant_impl.cpp``
  (max tick rate ``61.44e6 / num_chans``, ``AD9361_MIN_CLOCK_RATE`` 220 kHz).
* https://github.com/analogdevicesinc/pyadi-iio - ``adi/ad936x.py`` (device
  names ``ad9361-phy`` / ``cf-ad9361-lpc`` / ``cf-ad9361-dds-core-lpc``;
  ``sample_rate`` setter refuses ``< 521e3``; ``rx_hardwaregain_chanX`` is
  silently skipped unless ``gain_control_mode_chanX == 'manual'``);
  ``test/test_ad9361_p.py`` (rate sweep 2.084-61.44 MSPS).
* https://github.com/alphafox02/antsdr_dji_droneid - ``README.md`` (DroneID
  firmware boots from SD, ``root``/``1``, TCP 52002 / legacy 41030,
  ``fw_setenv gain_mode fast_attack``).

Verified vs inferred
--------------------
Verified (read in the files above): port mapping, 12-bit ADC, 61.44 MSPS
single-channel interface limit, 30.72 MSPS per channel with two channels,
521 kSPS pyadi setter floor, LO 70 MHz-6 GHz as configured by the firmware,
56 MHz RF bandwidth in AD9361 mode, default URI/credentials, the 2r2t and
clock-calibration procedures, the vendor's 20 MSPS host figure.
Inferred: the 10 MSPS per-channel host ceiling with two channels (half of the
vendor figure, libiio streams 32 bit per complex sample), the 40 MSPS UHD
``sc8`` figure (16 bit per sample on the wire; never measured), the
2.083 MSPS "no FIR" floor (pyadi's own sweep starts at 2.084 MSPS), and the
1.5x oversampling headroom used by :func:`recommend_sample_rate` (the LTE
convention 10 MHz -> 15.36 MSPS that DJI DroneID inherits).

Units: rates and frequencies are floats in Hz; gains in dB.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

__all__ = [
    "CLEAN_RATES",
    "CLOCK_CALIBRATION_SYSFS",
    "DRONEID_RATES",
    "E200",
    "FW_SETENV_2R2T",
    "GAIN_DB_RANGE",
    "GAIN_MODES",
    "IIO_DEVICE_NAMES",
    "OVERSAMPLING_DEFAULT",
    "PHY_RX_CHANNELS",
    "RX_DATA_CHANNELS",
    "TX_GAIN_OFF_DB",
    "UENV_2R2T_SD",
    "FirmwarePersonality",
    "HardwareProfile",
    "check_stream_config",
    "hw_string",
    "recommend_sample_rate",
]

#: pyadi-iio gain modes accepted by ``gain_control_mode_chanX`` (adi/ad936x.py,
#: also the GNU Radio PlutoSDR source options in ``AntsdrE310_gnurdio.md``).
GAIN_MODES: tuple[str, ...] = ("manual", "slow_attack", "fast_attack", "hybrid")

#: Manual RX gain limits accepted by :func:`check_stream_config`. UHD probe on the
#: E200 reports PGA 0-76 dB (verified, ``AntsdrE200_UHD.md``); the AD9361 manual
#: gain table also allows a few negative dB in the low bands (inferred).
GAIN_DB_RANGE: tuple[float, float] = (-10.0, 76.0)

#: ``tx_hardwaregain_chanX`` written by every receiver in this toolkit: the
#: AD9361 attenuation floor (-89.75 dB, ``ad9361_device.cpp`` MAX_GAIN 89.75) so
#: the transmitter never radiates. Passive receive only.
TX_GAIN_OFF_DB: float = -89.0

#: Sample rates that the AD9361 clock tree produces without odd BBPLL settings
#: and that the pyadi ``sample_rate`` setter accepts (>= 521 kSPS, FIR DEC 4 up
#: to 20 MSPS, DEC 2 above). 15.36 / 30.72 / 61.44 MSPS are the LTE-family
#: rates DJI DroneID work uses; 56 / 61.44 MSPS only make sense on-board.
CLEAN_RATES: tuple[float, ...] = (
    2.5e6, 4e6, 5e6, 8e6, 10e6, 14e6, 15.36e6, 20e6, 30.72e6, 40e6, 56e6, 61.44e6,
)

#: Rates used by the DroneID decoders (proto17/dji_droneid takes 15.36 MSPS
#: minimum for the 10 MHz OcuSync carrier; 30.72 / 61.44 MSPS are the LTE-style
#: multiples). Only 15.36 MSPS fits under the libiio host ceiling.
DRONEID_RATES: tuple[float, ...] = (15.36e6, 30.72e6, 61.44e6)

#: Complex sample rate / target bandwidth headroom (LTE convention: 10 MHz ->
#: 15.36 MSPS, 20 MHz -> 30.72 MSPS). Keeps the band inside the flat part of
#: the AD9361 analog filter + FIR response (inferred, not measured on the E200).
OVERSAMPLING_DEFAULT: float = 1.5

#: IIO device names exposed by the Pluto-compatible firmware (``set_gpio.md``
#: ``iio_attr -d`` listing, fw v0.34; identical to pyadi ``adi/ad936x.py``).
IIO_DEVICE_NAMES: Mapping[str, str] = MappingProxyType({
    "control": "ad9361-phy",
    "rx_data": "cf-ad9361-lpc",
    "tx_data": "cf-ad9361-dds-core-lpc",
    "clock_dac": "ad5660mp",
})

#: ``ad9361-phy`` input channel that carries gain/AGC attributes per RX chain.
PHY_RX_CHANNELS: Mapping[int, str] = MappingProxyType({0: "voltage0", 1: "voltage1"})

#: ``cf-ad9361-lpc`` (I, Q) scan channels per complex RX chain; channel 1 only
#: exists after the 2r2t boot-mode change (pyadi ``_rx_channel_names``).
RX_DATA_CHANNELS: Mapping[int, tuple[str, str]] = MappingProxyType({
    0: ("voltage0", "voltage1"),
    1: ("voltage2", "voltage3"),
})

FW_SETENV_2R2T: str = """\
# Enable the second RX/TX chain (IPEX RX2 = IIO voltage1 / channel 1) on the
# QSPI Pluto-compatible firmware. Run on the E200 (ssh root@192.168.1.10,
# password 'analog'), then reboot. Source: antsdr-fw-patch/README.md
# "Support 2r2t mode" (E200 doc Antsdr-fw-patch.md defers to it).
fw_setenv attr_name compatible
fw_setenv attr_val ad9361
fw_setenv compatible ad9361
fw_setenv mode 2r2t
reboot
# Same from the U-Boot prompt ('ANTSDR> '): setenv ... ; saveenv ; reset
# Check after reboot: fw_printenv mode   -> mode=2r2t
"""

UENV_2R2T_SD: str = """\
# SD-card boot of the Pluto-compatible firmware: edit uEnv.txt on the FAT
# partition instead of fw_setenv (antsdr-fw-patch/README.md "SD mode").
#  1. adi_loadvals=fdt addr ${devicetree_load_address} ...   (was ${fit_load_address})
#  2. mode=2r2t                                                (was mode=1r1t)
#  3. sdboot=... load mmc 0 ${ramdisk_load_address} ${ramdisk_image} && run adi_loadvals;
#     bootm ${fit_load_address} ${ramdisk_load_address} ${devicetree_load_address}#{fit_config}; fi
#  4. append:  attr_name=compatible
#              attr_val=ad9361
#              compatible=ad9361
"""

CLOCK_CALIBRATION_SYSFS: str = """\
# Discipline the 40 MHz TCXO (+/-0.5 ppm: ~1.2 kHz at 2.4 GHz, ~2.9 kHz at 5.8 GHz)
# against a 10 MHz reference or PPS on the single '10/PPS' MMCX (J18).
# IIO device 'ad5660mp' (driver ad5660_mp.c in antsdr-fw-patch). Source:
# antsdr_doc_en .../ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration.md
# (the E200 page states the procedure applies unchanged).
ssh root@192.168.1.10                     # password: analog
iio_attr -d                               # find the iio:deviceN named ad5660mp
cd /sys/bus/iio/devices/iio:device0       # N as listed above
# automatic lock (mode 0) to the selected reference:
echo 0 > in_voltage_dac_mode
echo 0 > in_voltage_dac_ref_sel           # 0: 10 MHz, 1: PPS, 2: GPS (no GPS input on E200)
sleep 30; cat in_voltage_dac_locked       # 1 = locked
cat in_voltage_dac_read_value             # calibrated DAC word to keep
# manual (mode 1, the power-on default with DAC word 23000):
echo 1 > in_voltage_dac_mode
echo 23000 > in_voltage_dac_value         # 0..65535
# Record the DAC word and the reference in the SigMF metadata of captures.
"""


@dataclass(frozen=True)
class FirmwarePersonality:
    """One of the mutually exclusive firmware images the E200 can boot.

    Attributes:
        name: Short tag used in ``core:hw`` strings (``hw_string(fw=...)``).
        boot: Where it boots from (``"QSPI"`` factory flash or ``"SD"``).
        ip: Default IPv4 address on the 1 GbE port.
        username / password: Default shell credentials.
        api: Host API this personality serves.
        notes: Boot / usage notes with the documenting file.
    """

    name: str
    boot: str
    ip: str
    username: str
    password: str
    api: str
    notes: str


@dataclass(frozen=True)
class HardwareProfile:
    """Numeric truth about one SDR board; see :data:`E200` for the values.

    All rates are complex samples per second (Hz). ``rf_ports`` maps the IIO /
    UHD channel index to the physical connector. ``host_stream_ceiling_sps``
    holds sustained host-link figures per transport, per channel.
    """

    name: str
    transceiver: str
    rf_ports: Mapping[int, str]
    adc_bits: int
    sample_rate_min: float
    sample_rate_max_1ch: float
    sample_rate_max_2ch: float
    host_stream_ceiling_sps: Mapping[str, float]
    rf_bandwidth_max: float
    lo_min: float
    lo_max: float
    default_uri: str
    firmware: tuple[FirmwarePersonality, ...] = ()
    rf_bandwidth_min: float = 200e3
    rf_bandwidth_default: float = 18e6
    sample_rate_no_fir_min: float = 2.083e6
    sample_rate_default: float = 30.72e6
    lo_default: float = 2.4e9
    tcxo_ppm: float = 0.5
    notes: Mapping[str, str] = field(default_factory=dict)

    @property
    def full_scale_counts(self) -> float:
        """Integer count that maps to ``|x| == 1.0`` (12-bit signed: 2048)."""
        return float(2 ** (self.adc_bits - 1))

    @property
    def n_rx_channels(self) -> int:
        return len(self.rf_ports)

    def rf_port_name(self, channel: int) -> str:
        """Connector name for an IIO/UHD channel index (``0 -> 'SMA RX1'``)."""
        try:
            return self.rf_ports[int(channel)]
        except KeyError:
            raise ValueError(
                f"{self.name} has RX channels {sorted(self.rf_ports)}, not {channel}"
            ) from None

    def interface_max_rate(self, channels: int = 1) -> float:
        """Digital-interface limit per channel for ``channels`` simultaneous chains."""
        if channels <= 0:
            raise ValueError("channels must be >= 1")
        if channels > self.n_rx_channels:
            raise ValueError(f"{self.name} has at most {self.n_rx_channels} RX channels")
        return self.sample_rate_max_1ch if channels == 1 else self.sample_rate_max_2ch

    def host_ceiling(self, channels: int = 1, transport: str = "iio_sc16") -> float | None:
        """Sustained per-channel host-link rate for ``transport``; ``None`` if unknown."""
        key = f"{transport}_1ch" if channels == 1 else f"{transport}_2ch_per_ch"
        value = self.host_stream_ceiling_sps.get(key)
        return None if value is None else float(value)

    def firmware_by_name(self, name: str) -> FirmwarePersonality | None:
        for fw in self.firmware:
            if fw.name == name:
                return fw
        return None


E200 = HardwareProfile(
    name="MicroPhase ANTSDR E200",
    transceiver="AD9363 (firmware declares ad9361)",
    rf_ports=MappingProxyType({0: "SMA RX1", 1: "IPEX RX2"}),
    adc_bits=12,
    sample_rate_min=521e3,
    sample_rate_max_1ch=61.44e6,
    sample_rate_max_2ch=30.72e6,
    host_stream_ceiling_sps=MappingProxyType({
        "iio_sc16_1ch": 20e6,
        "iio_sc16_2ch_per_ch": 10e6,
        "uhd_sc8_1ch": 40e6,
    }),
    rf_bandwidth_max=56e6,
    lo_min=70e6,
    lo_max=6e9,
    default_uri="ip:192.168.1.10",
    firmware=(
        FirmwarePersonality(
            name="pluto-iio",
            boot="QSPI",
            ip="192.168.1.10",
            username="root",
            password="analog",
            api="libiio / iiod (pyadi-iio adi.ad9364 / adi.ad9361), GNU Radio gr-iio, SDR++",
            notes=(
                "Factory image (antsdr-fw-patch, PlutoSDR-compatible). DIP switch under "
                "the Ethernet jack to QSPI; green LED blinks when booted; hostname 'ant'; "
                "1000BASE-T link required. Second RX chain needs the 2r2t change "
                "(FW_SETENV_2R2T). DFU reflash is not supported on the E200. Sources: "
                "AntsdrE200_Unpacking_examination.md, antsdr-fw-patch/README.md."
            ),
        ),
        FirmwarePersonality(
            name="uhd",
            boot="SD",
            ip="192.168.1.10",
            username="root",
            password="microphase",
            api="MicroPhase antsdr_uhd (UHD 4.1 fork, GPL-3): addr=192.168.1.10,product=E200",
            notes=(
                "Boots only from the SD card (BOOT.bin, antsdr.bit, uImage, uEnv.txt, ...). "
                "Persistent IP with 'ip_set <ip>' then reboot. UDP ports 49100 / 49200 / "
                "49202-49204 must be open on the host. OTW sc16/sc12/sc8. Sources: "
                "set_the_iio_firmware_ip.md, AntsdrE200_UHD.md, antsdr_uhd/host/README.md."
            ),
        ),
        FirmwarePersonality(
            name="dji-droneid",
            boot="SD",
            ip="192.168.1.10",
            username="root",
            password="1",
            api="text CSV over TCP to the host (E200 connects to host:52002); legacy server 41030",
            notes=(
                "Third-party binary-only decoder image (alphafox02/antsdr_dji_droneid). "
                "Configure from the QSPI firmware first: fw_setenv tcp_serverip <host>; "
                "fw_setenv tcp_serverport 52002; fw_setenv gain_mode fast_attack; then boot "
                "from SD. See antsdr_toolkit.bridges.dji_droneid for the wire formats."
            ),
        ),
    ),
    rf_bandwidth_min=200e3,
    rf_bandwidth_default=18e6,
    sample_rate_no_fir_min=2.083e6,
    sample_rate_default=30.72e6,
    lo_default=2.4e9,
    tcxo_ppm=0.5,
    notes=MappingProxyType({
        "silicon": (
            "Schematic sheet 11 shows an AD9363 (datasheet 325 MHz-3.8 GHz, 20 MHz BW); the "
            "firmware declares it ad9361/ad9364 so the driver allows 70 MHz-6 GHz and 56 MHz. "
            "Above 3.8 GHz / 20 MHz the part is outside its datasheet (untested by the vendor)."
        ),
        "interface": (
            "12-bit CMOS DDR single port at up to 61.44 MHz DATA_CLK: 61.44 MSPS in 1R1T, "
            "30.72 MSPS per channel in 2R2T (time-multiplexed); UHD enforces 61.44e6/2."
        ),
        "host_link": (
            "1 GbE only; vendor table says 20 MSPS to host. libiio moves 32 bit per complex "
            "sample (640 Mbit/s at 20 MSPS). Two channels: plan on ~10 MSPS per channel."
        ),
        "rates_below_2.083_msps": (
            "Need the FIR / FPGA decimator; the HDL wires the rx FIR decimator to channel 0 "
            "only, so keep sample_rate >= 2.5 MSPS in 2R2T and decimate on the host."
        ),
        "sample_rate_min": (
            "521 kSPS is the pyadi-iio setter floor (adi/ad936x.py); UHD allows 220 kSPS."
        ),
        "gain": (
            "pyadi writes rx_hardwaregain_chanX only while gain_control_mode_chanX is "
            "'manual': set the mode first. Firmware default is slow_attack AGC (dtsi)."
        ),
        "uhd_sc8_1ch": "unverified inference (16 bit/sample OTW); never benchmarked.",
        "iio_sc16_2ch_per_ch": "inferred: half of the vendor 20 MSPS figure.",
    }),
)


def hw_string(fw: str = "pluto-iio") -> str:
    """``core:hw`` string for SigMF: ``MicroPhase ANTSDR E200 (Zynq-7020, AD9363, fw=...)``."""
    return f"MicroPhase ANTSDR E200 (Zynq-7020, AD9363, fw={fw})"


def recommend_sample_rate(
    target_bw_hz: float,
    channels: int = 1,
    host_ceiling: bool = True,
    *,
    oversampling: float = OVERSAMPLING_DEFAULT,
    rates: Sequence[float] = CLEAN_RATES,
    profile: HardwareProfile = E200,
) -> float:
    """Pick a clean AD9361 sample rate for a signal of ``target_bw_hz``.

    The smallest rate in ``rates`` that is at least ``oversampling *
    target_bw_hz`` (1.5x by default, the LTE/DroneID convention: 10 MHz ->
    15.36 MSPS) and does not exceed the ceiling is returned. The ceiling is the
    digital-interface limit for ``channels`` (61.44 / 30.72 MSPS) and, when
    ``host_ceiling`` is true, the libiio host-link figure (20 MSPS single
    channel, 10 MSPS per channel with two). A target that cannot be covered
    under the ceiling returns the largest allowed rate, so the caller still
    gets the widest usable span (and can warn that the band is clipped).
    """
    if not target_bw_hz > 0.0:
        raise ValueError(f"target_bw_hz must be positive, got {target_bw_hz}")
    if not oversampling >= 1.0:
        raise ValueError("oversampling must be >= 1.0")
    ceiling = profile.interface_max_rate(channels)
    if host_ceiling:
        host = profile.host_ceiling(channels)
        if host is not None:
            ceiling = min(ceiling, host)
    allowed = sorted(r for r in rates if profile.sample_rate_min <= r <= ceiling)
    if not allowed:
        raise ValueError(f"no rate in {list(rates)} lies within the {ceiling / 1e6:.3f} MSPS ceiling")
    wanted = float(target_bw_hz) * float(oversampling)
    for rate in allowed:
        if rate >= wanted:
            return float(rate)
    return float(allowed[-1])


def check_stream_config(
    sample_rate_hz: float,
    center_freq_hz: float,
    *,
    channels: Sequence[int] = (0,),
    rf_bandwidth_hz: float | None = None,
    gain_mode: str = "manual",
    gain_db: float | None = None,
    host_ceiling: bool = True,
    profile: HardwareProfile = E200,
) -> list[str]:
    """Validate a receive configuration against ``profile``.

    Hard limits (interface rate, LO range, RF filter range, channel indices,
    gain mode / manual gain range) raise ``ValueError`` with the offending
    value and the limit. Soft limits return warnings: the host-link ceiling
    (when ``host_ceiling``), the AD9363 datasheet envelope (LO > 3.8 GHz or
    RF bandwidth > 20 MHz) and rates that need the channel-0-only decimator.
    """
    chans = tuple(int(c) for c in channels)
    if not chans:
        raise ValueError("channels must name at least one RX channel")
    if len(set(chans)) != len(chans):
        raise ValueError(f"channels must be unique, got {chans}")
    for c in chans:
        profile.rf_port_name(c)  # raises on unknown channel
    n_chan = len(chans)
    rate = float(sample_rate_hz)
    max_rate = profile.interface_max_rate(n_chan)
    if not profile.sample_rate_min <= rate <= max_rate:
        raise ValueError(
            f"sample_rate_hz {rate / 1e6:.4f} MSPS outside "
            f"[{profile.sample_rate_min / 1e6:.3f}, {max_rate / 1e6:.2f}] MSPS "
            f"for {n_chan} channel(s) on the {profile.name}"
        )
    fc = float(center_freq_hz)
    if not profile.lo_min <= fc <= profile.lo_max:
        raise ValueError(
            f"center_freq_hz {fc / 1e6:.3f} MHz outside the RX LO range "
            f"[{profile.lo_min / 1e6:.0f}, {profile.lo_max / 1e6:.0f}] MHz"
        )
    if rf_bandwidth_hz is not None:
        bw = float(rf_bandwidth_hz)
        if not profile.rf_bandwidth_min <= bw <= profile.rf_bandwidth_max:
            raise ValueError(
                f"rf_bandwidth_hz {bw / 1e6:.3f} MHz outside "
                f"[{profile.rf_bandwidth_min / 1e6:.1f}, {profile.rf_bandwidth_max / 1e6:.0f}] MHz"
            )
    if gain_mode not in GAIN_MODES:
        raise ValueError(f"gain_mode must be one of {GAIN_MODES}, got {gain_mode!r}")
    if gain_mode == "manual" and gain_db is not None:
        lo_g, hi_g = GAIN_DB_RANGE
        if not lo_g <= float(gain_db) <= hi_g:
            raise ValueError(f"gain_db {gain_db} outside [{lo_g}, {hi_g}] dB")

    warnings: list[str] = []
    host = profile.host_ceiling(n_chan) if host_ceiling else None
    if host is not None and rate > host:
        warnings.append(
            f"{rate / 1e6:.3f} MSPS x {n_chan} channel(s) exceeds the libiio host-link "
            f"ceiling of {host / 1e6:.0f} MSPS per channel over 1 GbE: expect dropped buffers"
        )
    if rate < profile.sample_rate_no_fir_min:
        warnings.append(
            f"{rate / 1e6:.3f} MSPS needs the FIR/FPGA decimator (below "
            f"{profile.sample_rate_no_fir_min / 1e6:.3f} MSPS); the E200 HDL decimates "
            "channel 0 only, so decimate on the host instead"
        )
    if fc > 3.8e9:
        warnings.append(
            f"LO {fc / 1e9:.3f} GHz is above the AD9363 datasheet range (3.8 GHz); "
            "the firmware allows it but sensitivity is unspecified"
        )
    bw_eff = rate if rf_bandwidth_hz is None else float(rf_bandwidth_hz)
    if bw_eff > 20e6:
        warnings.append(
            f"RF bandwidth {bw_eff / 1e6:.2f} MHz exceeds the AD9363 datasheet 20 MHz"
        )
    return warnings
