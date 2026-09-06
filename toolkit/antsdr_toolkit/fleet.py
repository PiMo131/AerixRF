"""What each DJI airframe actually yields to a receiver.

The question this answers is the one a maintainer asks before spending a
weekend: *if I point an E200 at this drone, what do I get?*  The honest answer
varies from a serial number and two positions down to "some energy was here",
and it depends on the link generation, on the EU class label, and on which
firmware the E200 is booted into.

The three things that decide it
-------------------------------
**Link generation.**  DJI's proprietary DroneID is plaintext on OcuSync 2 and
3 and encrypted from OcuSync 4 (Air 3, August 2023) onward
*(verified: verdict 4, ``dji-generation-coverage``)*.

**What can read it.**  Open code decodes exactly two airframes end to end, the
Mini 2 and the Mavic Air 2.  OcuSync 3 is plaintext but unfinished in public
code, so the only thing that decodes it is MicroPhase's closed firmware on the
E200.  OcuSync 4 needs a key nobody has published, and the only route to its
payload is a paid cloud service that ``ADR-0006`` declines.

**The EU class label.**  Standard Remote ID is mandated from C1 upward and
**C0, under 250 g, is exempt** *(verified: verdict 7, ``dji-eu-rid``)*.  This
is the trap in the whole subject: an OcuSync 4 airframe that is also C0 has an
encrypted proprietary identity *and* no obligation to broadcast a standard
one, so it is detectable and not identifiable by any means at all.  A Mini 4
Pro sits at 249 g on its standard battery and at about 290 g on the
Intelligent Flight Battery Plus, which puts it either side of the line: the
battery decides whether the aircraft can be identified.

Confidence
----------
Every row carries its own ``confidence``.  ``verified`` means the claim traces
to a primary source that was read, usually a firmware model table or a decoder
repository.  ``snippet`` means it rests on search-result text from a host the
research sandbox could not fetch, which covers most manufacturer specification
pages.  Nothing here is written from memory; the per-airframe evidence is in
``antsdr/research/landscape.md`` and ``antsdr/research/verification-log.md``.

This table will go out of date.  DJI ships firmware that changes DroneID
behaviour, and the encryption boundary moved once already.  Treat a row as a
prior to be checked, not as a fact about the aircraft in front of you.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = [
    "AIRFRAMES",
    "OPEN_DECODABLE",
    "TIERS",
    "Airframe",
    "identity_sources",
    "lookup",
    "observation_tier",
]

#: What ``ADR-0006`` calls each level of observation.
TIERS: Mapping[str, str] = MappingProxyType({
    "A": "identity and position from DroneID",
    "B": "presence only: an encrypted DroneID burst, a hash, frequency and RSSI",
    "C": "identity from standard Remote ID, because the class label compels it",
    "D": "energy only: no identity exists to be had",
})


@dataclass(frozen=True)
class Airframe:
    """One aircraft, and what a receiver can get from it."""

    name: str
    link: str
    """OcuSync generation, or the Wi-Fi mode for the models that have one."""
    droneid_encrypted: bool | None
    """``None`` where the evidence does not settle it."""
    open_decodable: bool
    """Decodable end to end by public open-source code today."""
    firmware_decodable: bool
    """Decodable by MicroPhase's closed DroneID firmware on the E200."""
    eu_class: str | None
    """``None`` for legacy airframes that carry no class mark."""
    takeoff_weight_g: float | None
    broadcasts_remote_id: bool | None
    product_type: int | None = None
    """The integer DJI's own frame carries, where an open decoder maps one."""
    note: str = ""
    confidence: str = "snippet"

    @property
    def remote_id_exempt(self) -> bool:
        """C0 and unmarked legacy airframes carry no broadcast obligation."""
        return self.eu_class in (None, "C0")

    @property
    def tier(self) -> str:
        """Which row of ``ADR-0006`` this airframe falls into."""
        if self.open_decodable or self.firmware_decodable:
            return "A"
        if self.broadcasts_remote_id:
            return "C"
        if self.droneid_encrypted:
            return "B"
        return "D"

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "link": self.link, "tier": self.tier,
                "eu_class": self.eu_class, "takeoff_weight_g": self.takeoff_weight_g,
                "droneid_encrypted": self.droneid_encrypted,
                "open_decodable": self.open_decodable,
                "firmware_decodable": self.firmware_decodable,
                "broadcasts_remote_id": self.broadcasts_remote_id,
                "product_type": self.product_type,
                "confidence": self.confidence, "note": self.note}


#: The two airframes public open-source code decodes end to end. Everything
#: else is either plaintext but unfinished in open code, or encrypted.
OPEN_DECODABLE = ("mini_2", "mavic_air_2")


AIRFRAMES: Mapping[str, Airframe] = MappingProxyType({
    # ---------------------------------------------------------- decodable
    "mini_2": Airframe(
        "DJI Mini 2", "OcuSync 2", droneid_encrypted=False, open_decodable=True,
        firmware_decodable=True, eu_class=None, takeoff_weight_g=249.0,
        broadcasts_remote_id=False, product_type=63,
        note="The reference airframe: proto17 was developed against one and "
             "RUB-SysSec ships Mini 2 samples. Predates the class-mark scheme "
             "and is sub-250 g, so it broadcasts no standard Remote ID, which "
             "for validation is a feature: a decode cannot be accidentally "
             "satisfied by an Open Drone ID beacon.",
        confidence="verified"),
    "mavic_air_2": Airframe(
        "DJI Mavic Air 2", "OcuSync 2", droneid_encrypted=False, open_decodable=True,
        firmware_decodable=True, eu_class=None, takeoff_weight_g=570.0,
        broadcasts_remote_id=None, product_type=58,
        note="The second and last airframe open code is demonstrated on.",
        confidence="verified"),

    # ------------------------------------------- plaintext but only closed
    "avata": Airframe(
        "DJI Avata", "OcuSync 3+", droneid_encrypted=None, open_decodable=False,
        firmware_decodable=True, eu_class=None, takeoff_weight_g=410.0,
        broadcasts_remote_id=False,
        note="O3 DroneID is plaintext but no open decoder finishes it, so the "
             "closed E200 firmware is the only route. Carries no C-class mark, "
             "and its Remote ID support was added for the United States only, "
             "so expect nothing on the EU Remote ID path. Whether DJI's 2024 "
             "encryption rollout reached this model is not established."),
    "mini_3_pro": Airframe(
        "DJI Mini 3 Pro", "OcuSync 3", droneid_encrypted=False, open_decodable=False,
        firmware_decodable=True, eu_class="C0", takeoff_weight_g=249.0,
        broadcasts_remote_id=False,
        note="Named in the closed firmware's own coverage list."),
    "air_2s": Airframe(
        "DJI Air 2S", "OcuSync 3", droneid_encrypted=False, open_decodable=False,
        firmware_decodable=True, eu_class="C1", takeoff_weight_g=595.0,
        broadcasts_remote_id=True,
        note="Named in the closed firmware's coverage list; C1, so it also "
             "broadcasts standard Remote ID."),
    "mavic_3": Airframe(
        "DJI Mavic 3", "OcuSync 3", droneid_encrypted=False, open_decodable=False,
        firmware_decodable=True, eu_class="C1", takeoff_weight_g=895.0,
        broadcasts_remote_id=True, note="Confirmed on Wi-Fi Beacon in a receiver log.",
        confidence="verified"),

    # ------------------------------------------------------ encrypted (O4)
    "mini_4_pro": Airframe(
        "DJI Mini 4 Pro", "OcuSync 4", droneid_encrypted=True, open_decodable=False,
        firmware_decodable=False, eu_class="C0", takeoff_weight_g=249.0,
        broadcasts_remote_id=False,
        note="The battery decides. At 249 g on the standard Intelligent Flight "
             "Battery it is C0, exempt, and broadcasts nothing; on the "
             "Intelligent Flight Battery Plus it passes 250 g and standard "
             "Remote ID activates. A C1 label upgrade is offered through DJI "
             "Fly, which would oblige it to broadcast. Ask which battery was "
             "flown before concluding anything from a silent scan."),
    "avata_2": Airframe(
        "DJI Avata 2", "OcuSync 4", droneid_encrypted=True, open_decodable=False,
        firmware_decodable=False, eu_class="C1", takeoff_weight_g=377.0,
        broadcasts_remote_id=True,
        note="The one O4 airframe in a typical hobby fleet that is still "
             "identifiable: at 377 g it is C1, so standard Remote ID is "
             "mandatory and carries the serial and both positions. Its "
             "proprietary DroneID stays encrypted."),
    "neo": Airframe(
        "DJI Neo", "OcuSync 4, or plain Wi-Fi in phone mode",
        droneid_encrypted=True, open_decodable=False, firmware_decodable=False,
        eu_class="C0", takeoff_weight_g=135.0, broadcasts_remote_id=False,
        note="The hardest of the fleet. Encrypted O4 with an RC, C0 so exempt "
             "from Remote ID, and absent from every open receiver's device "
             "list. Its phone-Wi-Fi mode is the one opening worth testing, "
             "since ordinary 802.11 frames carry a MAC address."),
    "air_3": Airframe(
        "DJI Air 3", "OcuSync 4", droneid_encrypted=True, open_decodable=False,
        firmware_decodable=False, eu_class="C1", takeoff_weight_g=720.0,
        broadcasts_remote_id=True,
        note="The airframe that marks the encryption boundary, August 2023.",
        confidence="verified"),

    # -------------------------------------------------------- enterprise
    "matrice_30": Airframe(
        "DJI Matrice 30 / 30T", "OcuSync 3 Enterprise", droneid_encrypted=False,
        open_decodable=False, firmware_decodable=False, eu_class="C2",
        takeoff_weight_g=3770.0, broadcasts_remote_id=True,
        note="Plaintext O3 in principle, but the closed firmware's coverage "
             "list names no Matrice, so treat identity as unproven until "
             "tested. No Matrice appears in OpenDroneID's transmitter list "
             "either, so even the Remote ID path is inference."),
    "matrice_4": Airframe(
        "DJI Matrice 4E / 4T", "OcuSync 4 Enterprise", droneid_encrypted=True,
        open_decodable=False, firmware_decodable=False, eu_class="C2",
        takeoff_weight_g=1233.0, broadcasts_remote_id=True,
        note="Named in the E200 O4 firmware's own model table, so it is at "
             "least classifiable as O4. Remote ID is interlocked with flight "
             "on the Matrice 4 series, which makes it the most reliable "
             "identity source in this table. Watch the band: this family uses "
             "5.150-5.250 GHz, outside a 5.725-5.875 GHz sweep."),
})


def lookup(name: str) -> Airframe | None:
    """Find an airframe by key or by a loose match on its name.

    ``lookup("Mini 4 Pro")``, ``lookup("mini_4_pro")`` and ``lookup("MINI4PRO")``
    all reach the same row.
    """
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key in AIRFRAMES:
        return AIRFRAMES[key]
    squashed = key.replace("_", "")
    for candidate_key, airframe in AIRFRAMES.items():
        if squashed in (candidate_key.replace("_", ""),
                        airframe.name.lower().replace(" ", "").replace("/", "")):
            return airframe
    for candidate_key, airframe in AIRFRAMES.items():
        if squashed and squashed in candidate_key.replace("_", ""):
            return airframe
    return None


def observation_tier(name: str) -> tuple[str, str] | None:
    """``(tier, what it means)`` for one airframe, or ``None`` if unknown."""
    airframe = lookup(name)
    if airframe is None:
        return None
    return airframe.tier, TIERS[airframe.tier]


def identity_sources(name: str) -> list[str]:
    """Every route to this airframe's identity, best first; empty if none.

    An empty list is a real answer and the most important one this module
    gives: it means the aircraft can be detected and tracked but not named,
    by anyone, without a key that has not been published.
    """
    airframe = lookup(name)
    if airframe is None:
        return []
    out: list[str] = []
    if airframe.open_decodable:
        out.append("DroneID, open decoder (antsdr_toolkit.droneid)")
    if airframe.firmware_decodable:
        out.append("DroneID, closed MicroPhase E200 firmware "
                   "(antsdr_toolkit.bridges.dji_droneid)")
    if airframe.broadcasts_remote_id:
        out.append("standard Remote ID over Wi-Fi Beacon "
                   "(antsdr_toolkit.remoteid), needs a monitor-mode adapter")
    return out
