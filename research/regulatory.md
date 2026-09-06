# Regulation and Remote ID for a Dutch/EU deployment

This is the legal and regulatory half of the research record: what passive reception, decoding and
storage of drone-link signals looks like under Dutch and EU rules as far as the evidence reaches,
why anything active (jamming, spoofing, take-over) is out of scope, what EU Remote ID actually
obliges a drone to broadcast, how DJI implements it, what China and Russia mandate instead, and
which receiver hardware is the right tool per transport.

**This is not legal advice.** Every Dutch legal source below was reachable only as a search-engine
snippet: the development sandbox could not fetch `itenrecht.nl`, `wetten.overheid.nl`,
`veiligesmartcities.nl` or the ASD-STAN standard text. The primary texts are on the wish list in
[sources.md](sources.md) (Wanted downloads, items 3, 4 and the `wetten.overheid.nl` entry), and
[ADR-0011](../docs/decisions/ADR-0011-legal-posture.md) makes a legal review a gate before
multi-node recording (question Q10 in [QUESTIONS.md](../QUESTIONS.md)).

Conventions, as in the other research documents:

* **verified** means an agent fetched the page or cloned the repository and read it; **snippet**
  means only a search-engine snippet was reachable. Per-source flags are in [sources.md](sources.md).
* Eight design-critical claims went through an adversarial verification pass and are cited as
  *(verified: verdict N, key)*, mirrored in [verification-log.md](verification-log.md). The one that
  matters most here is verdict 7, `dji-eu-rid`.
* Two claims were queued for that pass but the agent budget ran out (`o4-firmware-channels` and
  `ocusync-phy`). Neither is load-bearing in this document; where OcuSync PHY detail is needed it is
  taken from the verified decoder repositories instead, and the full treatment is in
  [landscape.md](landscape.md) and [signal-reference.md](signal-reference.md).

---

## 1. Dutch law: the radio-receiver exemption is the whole game

### 1.1 Article 139c Sr

The provision that governs listening to somebody else's radio link in the Netherlands is article
139c of the Wetboek van Strafrecht. Lid 1 criminalises intentionally and unlawfully tapping or
recording, with a technical aid, data not intended for you that is transmitted via
telecommunications or an automated work, with up to two years imprisonment or a fine
([maxius.nl art. 139c](https://maxius.nl/wetboek-van-strafrecht/artikel139c), snippet). Lid 2 sub 1
disapplies lid 1 to data received with a **radio-ontvangapparaat** (radio receiving device), unless
a **bijzondere inspanning** (special effort) was made to enable reception, or a **niet toegestane
ontvanginrichting** (not-permitted receiving installation) was used
([maxius.nl art. 139c](https://maxius.nl/wetboek-van-strafrecht/artikel139c), snippet).

For a passive SDR observation network that exemption is the entire legal basis. An ANTSDR E200 with
an antenna is a radio receiving device; nothing in the toolkit transmits
([ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md)). The two carve-outs in lid 2 are
therefore the only things that can move AERIX out of the exemption, and both are under-specified in
the sources that were reachable.

### 1.2 What counts as a "bijzondere inspanning"

Two readings were found, and they do not agree on scope.

| Source | Reading of "bijzondere inspanning" | Confidence |
|---|---|---|
| [ITenRecht ECLI document](https://www.itenrecht.nl/documents/ecli/56e8eb1b-5a94-40f9-9451-3e83c35ff8c2.pdf) | Ether signals are in principle free and receiving or recording them is in principle permitted, but not once a special effort is made, "which is the case if the tapping or recording occurs systematically and the receiving device consists of more than one apparatus" | snippet only; domain blocked, so the case facts, court level and which signals were at issue are **unknown** |
| [Ius Mentis, Aftappen van gegevens](https://www.iusmentis.com/beveiliging/hacken/computercriminaliteit/aftappengegevens/) | Data received by radio is exempt unless special effort or an unauthorised receiver is used; intercepting encryption keys and spoofing a MAC address are given as examples of special effort | snippet only; the same page cites ECLI:NL:RBROT:2016:5814 (TorRAT) and ECLI:NL:RBROT:2011:BU6142 as 139c case law, neither drone-specific |

The ITenRecht reading is the uncomfortable one for AERIX, because "systematic" plus "more than one
apparatus" is a literal description of a multi-node observation network with an SDR and a Wi-Fi
dongle per node. No drone-specific case law was found, and the snippet cannot be checked against the
judgment, so the honest position is: single-receiver research and development sits inside the
exemption on any reading; a permanent multi-node network that records link content does not
obviously sit inside it on the ITenRecht reading. That is precisely the split
[ADR-0011](../docs/decisions/ADR-0011-legal-posture.md) encodes.

A third, informal position exists in the Dutch scanner-hobby community: that receiving and listening
to everything over the air is permitted including decoding encoded data traffic, but that the
information may not be passed to third parties and that recording or saving is not permitted
([evel.nl, Nieuwe wetgeving op gebied van afluisteren](https://www.evel.nl/aflwet.htm), snippet).
The same search surfaced community disagreement about the decoding half. This page is undated and
possibly obsolete; it is quoted here only because its "no recording, no sharing" claim, if it did
reflect current law, would collide head-on with an observation network that stores and republishes
detections. It does not collide with storing Remote ID, which the research characterises as a
legally mandated one-way public broadcast that any third party may receive
([EASA Remote ID primer](https://www.elsight.com/blog/primer-on-easa-remote-id-regulations/),
snippet, cited only as a research key finding), and which is therefore the legally safest data class
for AERIX (section 3).

### 1.3 What could not be established

* No Telecommunicatiewet article on confidentiality of communications or on receive-only equipment
  could be verified. The hypothesis that an "artikel 18.x" applies remains unconfirmed, and the
  authoritative statutory text (<https://wetten.overheid.nl/BWBR0001854/>) is on the download wish
  list in [sources.md](sources.md).
* No statement by the Rijksinspectie Digitale Infrastructuur on passive SDR monitoring was located.
  What the RDI pages do establish is that the RDI regulates and supervises Dutch frequency use and
  that **active** drone detection needs a permit, with X-band radar given as the example
  ([RDI, onbemande luchtvaartuigen en drones](https://www.rdi.nl/onderwerpen/vergunningen-en-registraties/luchtvaart/onbemande-luchtvaartuigen-en-drones),
  snippet). Passive reception with the E200 appears to need no frequency licence, but this rests on
  the absence of a rule rather than on a positive statement, which is a weak form of evidence.
* No Dutch Autoriteit Persoonsgegevens or EASA guidance was found on the GDPR treatment of stored
  Remote ID operator registration numbers and operator positions by a private observation network.
  This is a real gap, because the EU rule makes operator registration ID and operator dynamic
  position mandatory broadcast content (section 3.3), i.e. the mandated payload is personal data by
  construction.

### 1.4 Data classes, ranked by how comfortably they sit inside the exemption

The practical output of section 1 is a ranking. Nothing here is a legal conclusion; it is a
risk ordering to drive the toolkit's defaults.

| Data class | What it is | Broadcast intended for anyone? | Encrypted? | Position under the lid-2 exemption as read here |
|---|---|---|---|---|
| Standard Remote ID (EN 4709-002 / ASTM F3411) | Legally mandated identification broadcast | Yes, by regulation | No, and unauthenticated ([droneRemoteIDSpoofer](https://github.com/cyber-defence-campus/droneRemoteIDSpoofer)) | Safest class. Receiving what the law compels a drone to shout is the paradigm case of a free ether signal |
| Chinese broadcast RID (GB 42590-2023, GB 46750-2025) | Same idea, different wire format ([luolitao/remoteid](https://github.com/luolitao/remoteid)) | Yes, by regulation | No | Same as above |
| DJI DroneID over OcuSync, clear (O2/O3) | Proprietary identification broadcast carrying serial, drone, pilot and home position ([proto17 create_frame_bytes.m](https://github.com/proto17/dji_droneid)) | Broadcast, but proprietary and not legally mandated | No | Received in the clear with an ordinary receiver, so on the exemption's face it qualifies; but the payload includes the pilot's phone position, so treat as personal data |
| DJI legacy Wi-Fi DroneID IE (OUI `26:37:12`) | Same field set inside 802.11 beacons ([Kismet dot11_ie_221_dji_droneid.h](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h)) | Broadcast in a management frame | No | As above |
| RC and video link **metadata** (centre frequency, bandwidth, hop timing, RSSI, burst shape) | Physical-layer observables, no payload | Not applicable | Not applicable, no content is recovered | Lowest-risk non-RID class: nothing "transmitted data" is recorded, only measurements of the channel |
| Analog FPV video | Unencrypted wideband FM composite video, demodulable to a picture *(verified: verdict 5)*, see [landscape.md](landscape.md) section 4.1 | No, it is a point-to-point link | No | Content of somebody else's link. Received by radio, so arguably exempt, but this is where "systematic recording with more than one apparatus" bites hardest |
| RC link payload (for example decoded ELRS channels) | Content of a control link | No | Not encrypted; the CRC seed, the FLRC sync word and the IQ inversion are all derived from the binding UID ([ExpressLRS OTA.h and SX1280.cpp](https://github.com/ExpressLRS/ExpressLRS)) | As above |
| Digital video payload (OcuSync, WPA2 Wi-Fi links) | Content, encrypted | No | Yes | Out of scope: recovering it needs key material, and intercepting encryption keys is named as a "special effort" ([Ius Mentis](https://www.iusmentis.com/beveiliging/hacken/computercriminaliteit/aftappengegevens/)) |
| DJI O4 encrypted DroneID | Encrypted proprietary broadcast *(verified: verdict 4)* | Broadcast | Yes | Detect-only. Decryption, including via a paid third-party service, is a different legal question and is declined by default ([ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md), Q6) |
| Raw IQ recordings | Everything above, undifferentiated, replayable | Mixed | Mixed | Highest risk, because a recording preserves content the toolkit never decoded. proto17 declines to publish his DroneID recordings precisely because they "likely contain GPS information" ([proto17/dji_droneid](https://github.com/proto17/dji_droneid)) |

The toolkit default that follows: metadata and classifications by default, raw IQ as an explicit
per-capture opt-in, decoded DroneID payloads treated as personal data in the same way AERIX already
treats ODID operator fields ([ADR-0011](../docs/decisions/ADR-0011-legal-posture.md), and the SigMF
recording policy in [ADR-0002](../docs/decisions/ADR-0002-sigmf-recordings.md)).

### 1.5 Personal data actually present in the payloads

Worth stating explicitly, because it is easy to think of RF detection as anonymous:

* The EU rule makes the **operator registration ID** and the **operator dynamic position**
  mandatory broadcast content ([opendroneid-core-c README comparison
  table](https://github.com/opendroneid/opendroneid-core-c)).
* The DJI DroneID frame carries a 16-byte serial, the drone position, the **app (pilot phone) GPS
  position**, the home position, and a 19-byte UUID
  ([proto17 create_frame_bytes.m](https://github.com/proto17/dji_droneid)).
* The DJI protocol even has a "user privacy enabled" state flag, alongside motors-on, in-air and
  gps-valid ([Kismet DJI DroneID IE
  parser](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h)),
  and DroneSecurity's decoder reports the serial as `SecureStorage?` when the drone withholds it
  ([RUB-SysSec/DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity)).
* GB 46750-2025 makes the operator/GCS position mandatory and requires both a 20-character serial
  and the 8-character real-name registration ID
  ([libopendroneidcn README](https://github.com/opendroneid/opendroneid-core-c)).

So a "detection" record can contain a natural person's live position. That is a GDPR question the
evidence could not answer (section 1.3) and it is why [ADR-0011](../docs/decisions/ADR-0011-legal-posture.md)
puts a review gate in front of deployment rather than in front of research.

---

## 2. Why jamming, spoofing and take-over are out of scope

[ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md) fixes the whole `antsdr/` directory as
receive-only: no module configures the TX path, no code generates over-the-air waveforms, and TX
attenuation stays at maximum. The research supports that boundary on three independent grounds.

1. **Active counter-drone measures are a state monopoly in the Netherlands.** The Minister of
   Justice and Security's temporary policy framework (Staatscourant 2026 nr. 2035, reported
   17 March 2026) enumerates the means police and Defence may use against unwanted drones: forcing a
   landing, disrupting signals, taking over the aircraft, and use of a firearm. It applies
   retroactively from 19 December 2025 until 1 July 2026 while permanent legislation is prepared
   ([Dronewatch](https://www.dronewatch.nl/2026/03/17/nieuwe-richtlijn-politie-mag-drones-verstoren-overnemen-en-zelfs-neerschieten/),
   snippet; the Staatscourant PDF itself is at
   <https://veiligesmartcities.nl/wp-content/uploads/2026/03/stcrt-2026-2035.pdf> and is on the
   download wish list). A private observation network is on the detection side of that line, and its
   output can at most be a feed for the authorities.
2. **Spoofing Remote ID is trivial and therefore tempting, which is exactly why it must be ruled
   out by architecture rather than by discipline.** The Swiss armasuisse Cyber-Defence Campus
   demonstrated forging ASD-STAN/ASTM broadcasts with a monitor-mode Wi-Fi adapter and a standard
   BLE HCI adapter, with the spoofed aircraft appearing in commercial receivers including DJI
   AeroScope and the OpenDroneID apps, because "the protocol itself does not provide authentication
   or cryptographic integrity"
   ([droneRemoteIDSpoofer](https://github.com/cyber-defence-campus/droneRemoteIDSpoofer)). Several
   otherwise useful projects ship a transmitter next to the receiver:
   [bkerler/DroneID](https://github.com/bkerler/DroneID) includes a spoofer,
   [luolitao/remoteid](https://github.com/luolitao/remoteid) ships `tools/spoofer`,
   [esp32-crid](https://github.com/luolitao/esp32-crid) has a `main_tx` beacon simulator and
   [DroneRX](https://github.com/ficusdeltoidearobertbarany663/DroneRX) also transmits beacons. Only
   the receive halves are in scope, and simulators are usable only into a cable or a shielded box.
3. **Decryption is a legal step change, not a technical one.** Intercepting encryption keys is
   named as an example of the "special effort" that removes the art. 139c exemption
   ([Ius Mentis](https://www.iusmentis.com/beveiliging/hacken/computercriminaliteit/aftappengegevens/)),
   and DJI began encrypting DroneID in January 2024 on newer models
   ([Aerial Defence](https://www.aerial-defence.com/the-process-of-encrypting-dji-droneid-has-commenced/),
   snippet). The paid routes that exist, MicroPhase's `o4online` endpoint inside the E200 firmware
   and cemaxecuter's [DragonScope](https://cemaxecuter.com/?product=dragonscope-drone-id-service)
   service, forward the intercepted encrypted payload to a third party that returns serial and
   position *(verified: verdict 4)*. That combines an interception question, a third-party data
   transfer question and an internet dependency, so the default is no
   ([ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md), Q6 in [QUESTIONS.md](../QUESTIONS.md)).

One more transmit-adjacent finding, recorded because it affects trust rather than scope: Russian and
Ukrainian DJI re-flash guides document firmware commands `aeroscope_off`, `aeroscope_random`,
`aeroscope_z` and `aeroscope_heart` that silence DroneID or broadcast pseudo-random positions,
alongside builds with "DRONE ID, OpenDroneId, NFZ" disabled
([techuav registry](https://github.com/techuav/techuav.github.io)) *(verified: verdict 4)*, and
MavicPilots users publish tricks to disable Remote ID on the Mavic 3
([thread 148094](https://mavicpilots.com/threads/how-to-disable-remote_id-on-dh-mavic-3-works.148094/),
snippet) *(verified: verdict 7, `dji-eu-rid`)*. See [foreign-perspective.md](foreign-perspective.md).
Absence of a Remote ID broadcast is therefore evidence of nothing, and the presence of one is an
unauthenticated claim.

---

## 3. EU Remote ID: what must be broadcast, by whom, since when

### 3.1 The regulatory chain

| Instrument | What it does | Source |
|---|---|---|
| Delegated Regulation (EU) 2019/945 | Product rules and the C0-C6 class marks | [eur-lex 2019/945](https://eur-lex.europa.eu/eli/reg_del/2019/945/2020-08-09) via [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c) |
| Implementing Regulation (EU) 2019/947 | Operational rules (Open, Specific, Certified categories) | [eur-lex 2019/947](https://eur-lex.europa.eu/eli/reg_impl/2019/947/2021-08-05) via [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c) |
| ASD-STAN prEN 4709-002 P1 | The Direct Remote Identification specification developed to meet 2019/945 and 2019/947, published 31 October 2021, broadcast-compatible with ASTM F3411 v1.1 | [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c); [ASD-STAN whitepaper](https://cms.stan-shop.org/uploads/2024/01/ASD-STAN_DRI_Introduction_to_the_European_digital_RID_UAS_Standard.pdf) (snippet, blocked domain) |
| Commission Implementing Decision (EU) 2024/2103 of 30 July 2024 | Publishes the harmonised DRI standard reference in the Official Journal **with restriction**, giving presumption of conformity | [eur-lex 2024/2103](https://eur-lex.europa.eu/eli/dec_impl/2024/2103/oj) (snippet; the restriction text could not be retrieved) |
| Implementing Regulation (EU) 2022/425 | Cited by the OpenDroneID project as the EU timeline reference | link listed in [opendroneid-core-c README](https://github.com/opendroneid/opendroneid-core-c) (the regulation text itself was not read) |

### 3.2 Who has to broadcast, and since when

| Aircraft | DRI obligation | Source and confidence |
|---|---|---|
| C1, C2, C3 class marks in the Open category | Active, updated Remote ID since 1 January 2024 | [skyzr](https://www.skyzr.com/en/drone-laws/remote-id-for-drones-mandatory-in-eu-since-2024/) (blog, snippet), [Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/) (vendor, snippet) |
| C5 and C6 | Included in the same obligation | [skyzr](https://www.skyzr.com/en/drone-laws/remote-id-for-drones-mandatory-in-eu-since-2024/) (snippet). Dronavia words it as "all class-marked C1-C6", so the two secondary sources differ on whether C4 is in scope; neither was checkable against the regulation |
| Any drone in the Specific category (below 120 m) | DRI required | [skyzr](https://www.skyzr.com/en/drone-laws/remote-id-for-drones-mandatory-in-eu-since-2024/), [Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/) (both snippet) |
| C0 and drones under 250 g without a camera, and toys | Exempt | [skyzr](https://www.skyzr.com/en/drone-laws/remote-id-for-drones-mandatory-in-eu-since-2024/) (snippet) |
| Legacy drones with no class mark flown in the Open category | May legally emit nothing | Research key finding built on [eur-lex 2024/2103](https://eur-lex.europa.eu/eli/dec_impl/2024/2103/oj), [skyzr](https://www.skyzr.com/en/drone-laws/remote-id-for-drones-mandatory-in-eu-since-2024/) and [Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/); secondary sourcing only |
| Compliance route | Native (DJI, Parrot) or an add-on broadcast module | [Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/) (snippet) |

One claim is flagged as **probably wrong**: skyzr also states that from 1 January 2026 Remote ID
becomes mandatory for all drones over 250 g regardless of class mark
([skyzr](https://www.skyzr.com/en/drone-laws/remote-id-for-drones-mandatory-in-eu-since-2024/)).
No EU instrument matching that could be found, and it may be a confusion with UK CAA plans. Do not
build a coverage assumption on it.

The consequence for AERIX is the one that matters most in this whole document: **a large part of the
Dutch drone population is legally silent.** C0 sub-250 g aircraft, legacy unmarked aircraft and toys
broadcast nothing, so RF-link detection (DroneID bursts, OcuSync/ELRS/analog-video signatures,
classifier output) is not an optional extra next to a Remote ID receiver, it is the only way to see
them. That is the argument for the E200 in one sentence, and it is developed in
[landscape.md](landscape.md).

### 3.3 What the messages contain, and which fields each rule mandates

The message set is Basic ID, Location, Self ID, System, Operator ID, Authentication and a Message
Pack ([ASD-STAN whitepaper](https://cms.stan-shop.org/uploads/2024/01/ASD-STAN_DRI_Introduction_to_the_European_digital_RID_UAS_Standard.pdf),
snippet; [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c), verified). Each
message is 25 bytes and up to 9 can be packed together
([opendroneid-core-c wifi.c](https://github.com/opendroneid/opendroneid-core-c)). Protocol version
numbers travel in every message header: 0 = ASTM F3411-19 (published 14 February 2020), 1 = ASD-STAN
prEN 4709-002 P1 (31 October 2021), 2 = ASTM F3411-22a (25 May 2022), where the delta from 1 to 2 is
only three new enum values and a Timestamp field in the System message
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)).

Condensed from the comparison table in the
[opendroneid-core-c README](https://github.com/opendroneid/opendroneid-core-c) (verified, M =
mandatory, O = optional, R = recommended, blank = not addressed):

| Field | FAA rule | EU rule | ASD-STAN DRI | Japan rule |
|---|---|---|---|---|
| Serial number (ANSI/CTA-2063-A) | M (or Session ID) | M | M | M |
| CAA registration ID | | | O | M |
| Session ID | M (or serial) | | O | O |
| UA dynamic position | M | M | M | M |
| UA altitude, barometric | | O | | M |
| UA altitude, WGS-84 | M | | O | M |
| UA altitude AGL / take-off | | M | M | O |
| Timestamp (Location message) | M | M | M | M |
| Operational / emergency status | M | M | M | O |
| Track direction, horizontal speed | M | M | M | M |
| Vertical speed | M | | O | M |
| Authentication signature | | | | M |
| Operator registration ID | | M | M | O |
| EU category and class | | | R | |
| Operator dynamic position | M | M | M | O |
| Transmission interval (Basic ID, Location, System) | 1 s | | 1 s or 3 s | 1 s |
| Transmission time | take-off to shutdown | | when airborne | when airborne |

Two qualifications carried by the README's own footnotes: the operational/emergency status is not
required for add-on modules, and under the EU rule an add-on may broadcast the take-off location
instead of the operator's dynamic position (under the FAA rule the take-off location is required
instead) ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)). So an add-on
equipped legacy drone yields a static operator position, not a moving one.

Two further footnotes matter to a receiver design. Location is always at 1 s intervals; and
if any channel other than 2.4 GHz channel 6 or 5 GHz channel 149 is used, the transmission rate must
rise to 5 Hz ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)). That is why
channel 6 and channel 149 are the two channels a scanner must cover first.

### 3.4 Transports: mandatory-one-of, and what that means for a receiver

Under ASD-STAN DRI the mandatory-one-of set is BT5 Long Range (Coded PHY with extended advertising),
Wi-Fi NAN on 2.4 and 5 GHz, and Wi-Fi Beacon on 2.4 and 5 GHz; BT4 legacy advertising is **optional**
([opendroneid-core-c README](https://github.com/opendroneid/opendroneid-core-c)). Under the ASTM
Means of Compliance for the FAA, the allowed sets are different again: either Bluetooth with BT4 and
BT5 transmitted simultaneously, or Wi-Fi Beacon on 2.4 or 5 GHz
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)).

On-air markers a receiver must match:

| Marker | Value | Source |
|---|---|---|
| Wi-Fi Beacon vendor IE (element 221) | ASD-STAN OUI `FA:0B:BC`, OUI type `0x0D` | [opendroneid-core-c wifi.c](https://github.com/opendroneid/opendroneid-core-c), [wireshark-dissector](https://github.com/opendroneid/wireshark-dissector) |
| Wi-Fi NAN service | Wi-Fi Alliance OUI `50:6F:9A`, type `0x13`, cluster ID `50:6F:9A:01:00:FF`, carried in Action frames (subtype 13) | [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c), [luolitao/remoteid](https://github.com/luolitao/remoteid) |
| BLE service data | UUID `0xFFFA`, application code `0x0D` | [wireshark-dissector](https://github.com/opendroneid/wireshark-dissector) |
| BT5 long range framing | Field offsets shift by 5 bytes; HCI extended advertising adds 17 (`BT5_OFF_ADDER = 17`) | [wireshark-dissector](https://github.com/opendroneid/wireshark-dissector) |
| Parrot Wi-Fi OUI | `90:3A:E6` | [wireshark-dissector](https://github.com/opendroneid/wireshark-dissector), [DroneRX](https://github.com/ficusdeltoidearobertbarany663/DroneRX) |
| French e-ID OUI | `6A:5C:35` (France runs a separate national "double identification" regime) | [opendroneid-core-c wifi.c](https://github.com/opendroneid/opendroneid-core-c), [DroneRX](https://github.com/ficusdeltoidearobertbarany663/DroneRX), [Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/) |
| DJI legacy Wi-Fi DroneID IE | OUI `26:37:12`, subcommand `0x10` telemetry, `0x11` flight purpose | [Kismet dot11_ie_221_dji_droneid.h](https://github.com/kismetwireless/kismet/blob/master/dot11_parsers/dot11_ie_221_dji_droneid.h) |

Ground-truth test vectors exist and should be used before trusting any parser: the OpenDroneID
Wireshark dissector ships `odid_wifi_sample.pcap`, `odid_wifi_bcn_sample.pcap` and
`odid_bt5_lr_sample.pcapng` ([wireshark-dissector](https://github.com/opendroneid/wireshark-dissector)).

---

## 4. DJI in the EU: Remote ID behaviour and DroneID coexistence

This section states the corrected version of the claim that went through adversarial verification
*(verified: verdict 7, `dji-eu-rid`)*.

**Transport.** DJI's standard Remote ID is an 802.11 **Beacon-only** implementation using the
ASD-STAN vendor IE (`FA:0B:BC`, type `0x0D`), typically advertising an SSID of the form `RID-<id>`.
No DJI model is documented anywhere in the evidence as using Bluetooth 4, Bluetooth 5 or Wi-Fi NAN.
Verified for the Mavic 3 and Mini 3 Pro from
[opendroneid's transmitter-devices.md](https://github.com/opendroneid/receiver-android/blob/master/transmitter-devices.md)
("Wi-Fi Beacon only", "Range < 500 meters via smartphone"), for the Air 2S from
[receiver-android issue 93](https://github.com/opendroneid/receiver-android/issues/93) ("added RID
support through WiFi Beacon") and for the Mavic 3 Enterprise from
[issue 99](https://github.com/opendroneid/receiver-android/issues/99) ("Transport type: Beacon
(Wi-Fi)"). For post-2022 models it rests on forum snippets, not on a maintained list. Beacon-only is
DJI's own choice, not a standard requirement: EN 4709-002 would equally allow BT5 Long Range or NAN
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)).

**Band and channel are not established.** Whether DJI beacons on 2.4 GHz channel 6 or 5 GHz channel
149 could not be determined *(verified: verdict 7)*. A scanner must cover both.

**EU availability is narrower than "model and firmware dependent".** DRI is mandated for C1 and
above and for specific-category operations, so C0 sub-250 g DJI aircraft are exempt and are reported
to broadcast nothing in Europe *(verified: verdict 7)*.

| Model | Reported EU / general behaviour | Source, confidence |
|---|---|---|
| Mavic 3 | Broadcasts; appeared in the OpenDroneID app from firmware 01.00.0800 regardless of FCC/CE region; a firmware trick to disable it circulates | [MavicPilots 132574](https://mavicpilots.com/threads/bad-news-to-everyone-rid-was-already-active-in-01-00-0800-firmware-and-the-drone-appears-in-opendroneid-app.132574/page-5), [MavicPilots 148094](https://mavicpilots.com/threads/how-to-disable-remote_id-on-dh-mavic-3-works.148094/), snippet |
| Mavic 3 Enterprise | Beacon (Wi-Fi) confirmed in a receiver log | [receiver-android 99](https://github.com/opendroneid/receiver-android/issues/99), verified |
| Mini 3 (C0) | "Remote ID on Mini 3 is turned OFF in Europe. It was ON with early firmwares, but DJI disconnected this" | [MavicPilots 151947](https://mavicpilots.com/threads/does-the-dji-mini-3-pro-have-remoteid-in-the-eu-that-broadcasts-the-location-and-altitude.151947/), snippet |
| Mini 3 Pro | Broadcasts only after firmware update; one user received EASA-format RID over Wi-Fi NAN which appears disabled in later firmware | [MavicPilots 151947](https://mavicpilots.com/threads/does-the-dji-mini-3-pro-have-remoteid-in-the-eu-that-broadcasts-the-location-and-altitude.151947/), [forum.dji.com 279235](https://forum.dji.com/thread-279235-1-1.html), snippet |
| Air 2S | Gained RID by firmware, and a C1 label later | [receiver-android 93](https://github.com/opendroneid/receiver-android/issues/93) verified, [DroneDJ](https://dronedj.com/2024/04/18/dji-air-2s-c1-label/) snippet |
| Mini 4 Pro | Reported upgradeable to C1 with a pilot-ID menu in DJI Fly; in the US it broadcasts only with the heavier (over 249 g) battery. The verification pass instead groups the Mini 4 Pro with the C0-exempt models *(verified: verdict 7)*, so these reports conflict | [MavicPilots 151947](https://mavicpilots.com/threads/does-the-dji-mini-3-pro-have-remoteid-in-the-eu-that-broadcasts-the-location-and-altitude.151947/), [dronexl](https://dronexl.co/2024/02/09/remote-id-update-dji-mini-4-pro/), snippet |
| Mini 5 Pro | Reported to broadcast RID | [MavicPilots 155240](https://mavicpilots.com/threads/question-about-rid-on-my-mini-5-pro.155240/), snippet |
| Neo, Flip (C0 class) | No evidence of RID in the EU; assumed silent by extension from the C0 exemption | inference recorded in *(verified: verdict 7)* |

**iOS cannot see DJI at all.** Apple exposes no Wi-Fi beacon API, so a BLE-only or iOS-based
receiver misses every DJI aircraft ([Dronetag Drone Scanner help](https://help.dronetag.com/drone-scanner/),
[MavicPilots 143189](https://mavicpilots.com/threads/remote-id-via-wifi-vs-bluetooth.143189/),
snippet), and iOS up to 15 only exposes BT4 legacy advertising to apps
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)). Android is not much
better as an infrastructure sensor: Wi-Fi beacon scanning is throttled by default from Android 8 and
must be disabled in developer options, and BT5 Long Range reception works reliably only on some
chipsets ([receiver-android README](https://github.com/opendroneid/receiver-android)); a user
measured roughly 600 m line of sight but 30 to 60 s to first catch a drone
([MavicPilots 151947](https://mavicpilots.com/threads/does-the-dji-mini-3-pro-have-remoteid-in-the-eu-that-broadcasts-the-location-and-altitude.151947/),
snippet). That is the argument for a dedicated always-on receiver rather than a phone app.

**Coexistence with DroneID.** DJI aircraft have broadcast a proprietary beacon receivable by
AeroScope since 2017 ([MavicPilots 143189](https://mavicpilots.com/threads/remote-id-via-wifi-vs-bluetooth.143189/),
snippet), and that side channel continues alongside standard Remote ID. Three disjoint lenses result,
and the AERIX observation contract must not merge them
([ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md),
[ADR-0008](../docs/decisions/ADR-0008-relation-to-aerix-observation-contract.md)):

| Lens | Content | Receiver | Legal/observation note |
|---|---|---|---|
| Standard RID (Wi-Fi Beacon) | Serial or session ID, positions, operator ID and operator position | Monitor-mode Wi-Fi NIC (section 6) | Mandated broadcast, present only for C1 and above |
| DJI DroneID in the clear (O2/O3) | Serial, model, drone/pilot/home GPS, altitude, speed, RSSI | E200 with MicroPhase's DroneID firmware, or open decoders for OcuSync 2 *(verified: verdict 4)* | Proprietary, unauthenticated, contains the pilot's position |
| DJI DroneID encrypted (O4 and later: Air 3, Mini 4 Pro, Avata 2, Neo, Flip, Mini 5 Pro, Mavic 4 Pro, Avata 360) | A per-session hash, frequency and RSSI only | E200 firmware, detection tier | Never label it an identity; the hash is a transient track key *(verified: verdict 4)* |

DJI began encrypting DroneID from January 2024 on newer models (Mavic 3 series, Mini 4 Pro, Avata)
once on current firmware, and offered AeroScope owners a firmware update plus an "AeroScope Upgrade
Module" (EA500) that decrypts the new signal
([Aerial Defence](https://www.aerial-defence.com/the-process-of-encrypting-dji-droneid-has-commenced/),
snippet; [AeroDefense](https://aerodefense.tech/djis-drone-encryption-move-how-it-affects-aeroscopes-many-drone-detection-systems-and-national-security/),
snippet). The adversarial pass sharpened the generation boundary: O3+/O3 Pro (Mavic 3 series,
Inspire 3) are on the unencrypted side and the encryption boundary is the O4 generation (Air 3,
August 2023 onward) *(verified: verdict 4)*, which is a different grouping from the vendor blog's
model list. Note also that DroneID reporting is model-dependent in time: one source states DJI
aircraft broadcast DroneID only while motors are spinning
([WarDragon detection-capabilities](https://github.com/alphafox02/WarDragon/blob/main/docs/software/detection-capabilities.md)),
but this is contested for O2-era drones and must be measured rather than assumed
*(verified: verdict 4)*.

**Net effect for the Netherlands.** For the sub-250 g O4 fleet (Mini 4 Pro, Neo, Flip and similar)
there is neither decodable Remote ID nor decodable DroneID. Those aircraft are visible only as RF
energy with an OFDM signature. Everything the toolkit does in that direction is described in
[landscape.md](landscape.md) sections 1 and 5.

---

## 5. Other jurisdictions

### 5.1 United States: FAA rule and ASTM F3411

The US means of compliance is ASTM F3411-22a overlaid by the ASTM Means of Compliance F3586-22,
published 26 July 2022 and accepted by the FAA through a Notification of Availability on
11 August 2022 as an acceptable, but not the only, means of compliance
([opendroneid-core-c README](https://github.com/opendroneid/opendroneid-core-c)). FAA enforcement of
the operator Remote ID requirement began 16 March 2024 after a grace period, and drones upgraded by
firmware must carry the label `ASTM F3411-22a-RID-B`
([DJI FAQ on FAA Remote ID compliance](https://support.dji.com/help/content?customId=en-us03400007747&spaceId=34&re=US&lang=en),
snippet). Because ASD-STAN prEN 4709-002 was written against the ASTM F3411 v1.1 draft and the
delta between protocol versions 1 and 2 is only three enum values plus a System-message timestamp
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)), **one decoder covers
FAA- and EU-configured aircraft**; what differs is the mandated field set (section 3.3). The FAA
allows a rotating Session ID instead of a serial number, and add-ons are not allowed to use it,
while the EU column of the comparison table is blank for Session ID (blank meaning the document
says nothing specific about it)
([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)); a receiver must
therefore treat the Basic ID type as significant rather than assuming a serial.

### 5.2 Japan

Broadcast Remote ID has been required since 20 June 2022. Compared with the EU: BT5 Long Range and
Wi-Fi Beacon are among the mandatory-one-of methods, BT4 legacy advertising is optional, **two**
Basic ID messages must be sent (serial number and a CAA-provisioned registration ID), an
Authentication signature over the message set is mandatory, and because the System message is
optional so is the operator location
([opendroneid-core-c README](https://github.com/opendroneid/opendroneid-core-c)). The README itself
warns that this reading is based on auto-translated Japanese documents and may contain errors.
Japan is not operationally relevant to a Dutch deployment; it is recorded because it is the only
rule in the set that mandates an authentication signature, which is what a spoof-resistant network
would want (section 2, point 2).

### 5.3 China: GB 42590-2023 and GB 46750-2025

| | GB 42590-2023 | GB 46750-2025 |
|---|---|---|
| Title | 民用无人驾驶航空器系统安全要求 (Civil UAS safety requirements) | 民用无人驾驶航空器系统运营识别规范 (Civil UAS operational identification specification) |
| Dates | Published 2023-05-23, effective 2024-06-01 ([openstd.samr.gov.cn](https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=0DC41035BA23EF2C5B94E6482492AF1E), snippet) | Published 2025-10-31, effective 2026-05-01 ([XC-RemoteID](https://github.com/luolitao/XC-RemoteID), [libopendroneidcn README](https://github.com/opendroneid/opendroneid-core-c)) |
| Obligation | Light and small UAS report identification to the state supervision platform over the network **and** automatically broadcast identification over Wi-Fi or Bluetooth in flight ([NetEase explainer](https://www.163.com/dy/article/KCLCCD000552L9R6.html), snippet) | Both broadcast mode (§5.2) and network mode (§5.3) mandatory for full compliance ([libopendroneidcn README](https://github.com/opendroneid/opendroneid-core-c)) |
| Wire format | Same vendor IE as ASTM (`FA:0B:BC` / `0x0D`) but protocol-version nibble `0x1`, 25-byte messages, a 3-byte pack header `[0xF1][25][count]` against ASTM's 2-byte header, and a 12-bit direction field ([luolitao/remoteid](https://github.com/luolitao/remoteid), [esp32-crid](https://github.com/luolitao/esp32-crid)) | Independent, not wire-compatible: single variable-length packet starting `0xFF` with a flag-bitmask chain, 21 defined fields, data region up to 200 bytes ([libopendroneidcn README](https://github.com/opendroneid/opendroneid-core-c), [luolitao/remoteid](https://github.com/luolitao/remoteid)) |
| Identity | Manufacturers may fill the payload with OpenDroneID message types ([CSDN parsing guide](https://blog.csdn.net/qq_41126242/article/details/143920008), snippet) | Serial (GB/T 41300, 20 characters) **and** the last 8 digits of the CAAC real-name registration number, both mandatory ([XC-RemoteID](https://github.com/luolitao/XC-RemoteID), [libopendroneidcn](https://github.com/opendroneid/opendroneid-core-c)) |
| Transports | Wi-Fi beacon vendor IE 221 on 2400-2476 MHz or 5725-5829 MHz, or Bluetooth ([CSDN](https://blog.csdn.net/qq_41126242/article/details/143920008), snippet) | At least Bluetooth 5.0 broadcast mode or Wi-Fi broadcast mode; reference firmware uses BLE 5.0 extended advertising plus Wi-Fi Beacon, and BT4.2 chips cannot carry a full packet within the 31-byte limit ([XC-RemoteID](https://github.com/luolitao/XC-RemoteID)); 2.4 GHz / 5.8 GHz ([libopendroneidcn](https://github.com/opendroneid/opendroneid-core-c)) |
| Product-level obligations | Geofencing among 17 requirement areas ([NetEase](https://www.163.com/dy/article/KCLCCD000552L9R6.html), snippet) | Continuous broadcast that cannot be switched off, interval <= 1 s, 10 s shutdown grace period, take-off interlock, 120 h rolling log, **ADS-B prohibited**, operator/GCS position mandatory, WGS-84 or CGCS2000 ([XC-RemoteID](https://github.com/luolitao/XC-RemoteID), [libopendroneidcn](https://github.com/opendroneid/opendroneid-core-c)) |
| Transition | Newly manufactured micro/light/small drones needed RID from 1 January 2024 per secondary summaries ([openstd entry](https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=0DC41035BA23EF2C5B94E6482492AF1E), snippet) | Manufacturers must retrofit sold drones with a module within 12 months of publication; 36-month transition for retrofitted systems ([XC-RemoteID](https://github.com/luolitao/XC-RemoteID)) |

Why a Dutch receiver should care: an ASTM-only parser silently drops both Chinese formats, and
grey-import or China-firmware aircraft may use them. The parsing order that works is the one
[esp32-crid](https://github.com/luolitao/esp32-crid) uses: try GB 46750 (`0xFF`), then GB 42590
(3-byte `0xF1` pack header), then ASTM (2-byte `0xF1` header).
[opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c) now ships `libopendroneidcn`
for the GB 46750 format, and [luolitao/remoteid](https://github.com/luolitao/remoteid) parses all
three from one pcap stream. Two cautions: the two open GB 46750 implementations disagree on the
timestamp encoding (6-byte Unix milliseconds against 4-byte seconds since 2019-01-01), so the
standard text is needed before shipping a decoder ([XC-RemoteID](https://github.com/luolitao/XC-RemoteID)),
and whether any China-market DJI aircraft actually emits these frames in Europe is unknown. The
5.8 GHz Wi-Fi option is a blind spot in every open receiver surveyed, which listens on 2.4 GHz
channel 6 only ([CSDN parsing guide](https://blog.csdn.net/qq_41126242/article/details/143920008),
snippet; [esp32-crid](https://github.com/luolitao/esp32-crid) defaults to channel 6 at 1 Hz).
A known-good Chinese test emitter is available as an ESP32 build
([esp32-crid-sim](https://github.com/luolitao/esp32-crid-sim), MIT) or as a commercial "C-RID"
module ([bilibili tutorial](https://www.bilibili.com/video/BV1RRtEzvEZS/), snippet), usable into a
cable only, per section 2.

### 5.4 Russia: network identification, nothing to receive

Government Decree No. 83 of 2 February 2026 makes connection to the state ERA-GLONASS system
mandatory from 1 March 2026 for civil UAVs over 250 g; the equipment forms and transmits an
identification index, aircraft category, flight altitude and coordinates to the ERA-GLONASS operator
([Interfax](https://www.interfax.ru/russia/1071959), snippet). ERA-GLONASS ingests cellular,
satellite and hybrid trackers as well as ADS-B, and AO GLONASS is reported to be testing a hybrid
"analogue of DroneID" for areas without cellular coverage
([ComNews](https://www.comnews.ru/content/244060/2026-03-04/2026-w10/1008/grazhdanskie-bespilotniki-vselilas-era-glonass),
snippet). No public Bluetooth or Wi-Fi broadcast standard and no GOST for broadcast RID was found.

Consequence: Russian-registered aircraft are **not** expected to be receivable by an Open Drone ID
receiver at all, because their identification path is a network report rather than a local
broadcast. The only speculative local hook is ADS-B on 1090 MHz if a hybrid tracker uses it, which
is unverified. Note the contrast with China, which explicitly prohibits using ADS-B for this purpose
([libopendroneidcn](https://github.com/opendroneid/opendroneid-core-c)). The wider Russian and
Ukrainian picture is in [foreign-perspective.md](foreign-perspective.md).

---

## 6. Receiving Remote ID: SDR versus commodity dongles

### 6.1 Transport -> best receiver for AERIX

The required table. "E200" means the ANTSDR E200 in some firmware personality; see
[hardware-e200.md](hardware-e200.md) and
[ADR-0004](../docs/decisions/ADR-0004-firmware-personality-and-capture-tiers.md).

| Transport | Where it is mandated | E200 capability | Best receiver for AERIX | Why |
|---|---|---|---|---|
| **Wi-Fi Beacon 2.4 GHz (ch 6)** | Mandatory-one-of under ASD-STAN DRI, ASTM MoC and GB 42590 ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)) | Poor. openwifi supports `antsdr_e200` but is OFDM-only and cannot demodulate 802.11b DSSS/CCK, which is what reference RID transmitters use for beacons *(verified: verdict 6)* | **Commodity monitor-mode Wi-Fi NIC** (for example the rtl8812au tested by [unix_rid_capture](https://github.com/sxjack/unix_rid_capture)) | An openwifi E200 will most likely miss mainstream 2.4 GHz Beacon RID; an ordinary USB NIC that speaks 802.11b does not |
| **Wi-Fi Beacon 5 GHz (ch 149)** | Same | Possible in principle: 5 GHz beacons are OFDM at 6 Mbps or above *(verified: verdict 6)* | Same commodity NIC (dual-band) | The NIC covers both channels and hops; openwifi watches only one 20 MHz channel at a time *(verified: verdict 6)* |
| **Wi-Fi NAN 2.4 / 5 GHz** | Mandatory-one-of under ASD-STAN DRI ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)) | Unverified. NAN service discovery rides Action frames (subtype 13) ([luolitao/remoteid](https://github.com/luolitao/remoteid)); whether openwifi passes them in monitor mode and at what PHY rate was not tested *(verified: verdict 6)* | Commodity NIC with NAN-capable capture, or a phone for spot checks | Android NAN reception is documented as working only on some devices ([receiver-android](https://github.com/opendroneid/receiver-android)) |
| **Bluetooth 4 legacy advertising** | Optional under DRI, mandatory (with BT5) under the ASTM MoC ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)) | Marginal. [ice9-bluetooth-sniffer](https://github.com/mikeryan/ice9-bluetooth-sniffer) channelises 4-60 MHz into 2 MHz channels and links against libuhd, so it might run through MicroPhase's `antsdr_uhd` fork, untested; [BTLE](https://github.com/JiaoXianjun/BTLE) is HackRF/bladeRF and 1M PHY only | **CC2652P dongle running [Sniffle](https://github.com/nccgroup/Sniffle)**, or a bluez HCI adapter ([unix_rid_capture](https://github.com/sxjack/unix_rid_capture)) | Cheap, reliable, captures all three primary advertising channels with one sniffer |
| **Bluetooth 5 Long Range (Coded PHY, extended advertising)** | Mandatory-one-of under DRI, and the transport add-on modules such as Dronetag use ([Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/), [Dronetag](https://help.dronetag.com/drone-scanner/)) | **None.** No surveyed open SDR tool decodes Coded PHY: ice9 documents BR and BLE 1M only, BTLE is 1M only | **[Sniffle](https://github.com/nccgroup/Sniffle) on TI CC26x2R / CC2652RB / CC1352 / SONOFF CC2652P / Catsniffer**, or an nRF52840 dongle with sniffer firmware | Sniffle supports "all BT5 PHY modes (regular 1M, 2M, and coded modes)", follows extended-advertising auxiliary pointers (`-e`) and exports PCAP; the OpenDroneID project recommends it and validated BT5 capture with the nRF52840 ([wireshark-dissector](https://github.com/opendroneid/wireshark-dissector)) |
| **GB 46750-2025 broadcast (BLE 5.0+ extended advertising or Wi-Fi 2.4/5.8 GHz)** | China, effective 2026-05-01 ([libopendroneidcn](https://github.com/opendroneid/opendroneid-core-c)) | Wi-Fi side only, and nothing the commodity radios cannot also hear | Same NIC plus Sniffle pair, with a `0xFF`-first parser ([esp32-crid](https://github.com/luolitao/esp32-crid), [luolitao/remoteid](https://github.com/luolitao/remoteid)) | Same radios, different parser. Note that the surveyed open receivers only listen on 2.4 GHz channel 6, so the 5.8 GHz option has to be covered deliberately ([CSDN parsing guide](https://blog.csdn.net/qq_41126242/article/details/143920008), snippet) |
| **GB 42590-2023 broadcast (Wi-Fi IE 221 or Bluetooth)** | China, effective 2024-06-01 | As above | As above | Shares the ASTM OUI, so it costs only a header check ([luolitao/remoteid](https://github.com/luolitao/remoteid)) |
| **French e-ID beacon (OUI `6A:5C:35`)** | France national regime ([Dronavia](https://www.dronavia.com/2024/04/04/drone-remote-identification-european-union/)) | Same as Wi-Fi Beacon | Commodity NIC | Parser addition only ([opendroneid-core-c wifi.c](https://github.com/opendroneid/opendroneid-core-c)) |
| **DJI legacy Wi-Fi DroneID IE (OUI `26:37:12`)** | Not mandated; DJI Wi-Fi-link aircraft (Spark, Mavic Air, Tello class) | Same as Wi-Fi Beacon | Commodity NIC with [Kismet](https://github.com/kismetwireless/kismet) or the [DeFliTeam](https://github.com/DeFliTeam/DroneDetection) approach | It is an 802.11 beacon IE, so an SDR adds nothing |
| **DJI DroneID over OcuSync (2.4 / 5.8 GHz OFDM burst)** | Not a Remote ID transport at all | **This is what the E200 is for.** ~10 MHz burst (15.36 MHz with guards) every ~600 ms ([proto17](https://github.com/proto17/dji_droneid)) | **ANTSDR E200** with the MicroPhase DroneID firmware or a host decoder *(verified: verdict 4)* | No commodity dongle demodulates an LTE-flavoured OFDM burst; see [landscape.md](landscape.md) section 1 |
| **Network RID (Russia ERA-GLONASS; China network mode)** | Russia from 2026-03-01 ([Interfax](https://www.interfax.ru/russia/1071959)); China §5.3 ([libopendroneidcn](https://github.com/opendroneid/opendroneid-core-c)) | None, and none for any receiver | **Not receivable.** Record as a known blind spot | The identification path is a network report to a state platform, not a local broadcast |

Note on price: the research lens describes the Sniffle-compatible dongle as a roughly EUR 15 part;
the Sniffle README lists the supported boards (CC26x2R, CC2652RB, CC1352R/P Launchpads, SONOFF
CC2652P USB Dongle Plus, Catsniffer V3) but no price
([nccgroup/Sniffle](https://github.com/nccgroup/Sniffle)), so treat the figure as an order of
magnitude rather than a quote.

### 6.2 Why openwifi on the E200 is not the Remote ID path

The project's initial hypothesis was that the E200 could be the Remote ID sensor. The evidence says
otherwise *(verified: verdict 6)*, and this is the single most useful negative result of the sweep.

What works: `antsdr_e200` is a supported openwifi board with devicetree, u-boot, an FPGA design, a
prebuilt bitstream and, since August 2026, a compact Buildroot image stated to have been booted with
AP/client plus iperf3 on real hardware; monitor mode delivers every received frame including
bad-CRC frames to mac80211 with radiotap signal in dBm; injection, CSI and IQ capture (`iq_len` under
4096 on the Z7020) all work ([open-sdr/openwifi](https://github.com/open-sdr/openwifi))
*(verified: verdict 6)*.

What breaks it:

| Blocker | Detail | Source |
|---|---|---|
| 802.11b blindness | openwifi is OFDM-only and cannot demodulate DSSS/CCK; its README notes this "is usually the case during beacon transmission". Reference RID transmitters beacon at the 11b lowest basic rate: [transmitter-linux beacon.conf](https://github.com/opendroneid/transmitter-linux) uses `hw_mode=g`, `channel=6` with no `basic_rates` override, and ESP32 modules ([ArduRemoteID](https://github.com/ArduPilot/ArduRemoteID), [esp32-crid](https://github.com/luolitao/esp32-crid)) never override the ESP-IDF default 11B/11G/11N protocol | *(verified: verdict 6)*; the 1 Mbps DSSS conclusion is inferred from defaults, not measured |
| Viterbi halt | The free FPGA image's Xilinx Viterbi decoder runs under an evaluation licence and halts after about two hours; recovery needs an FPGA reload or power cycle, detectable via `sdrctl dev sdr0 get reg rx 20` | [openwifi README](https://github.com/open-sdr/openwifi) *(verified: verdict 6)* |
| One channel at a time | 20 MHz at a time, so channel 6 and channel 149 cannot be covered simultaneously | *(verified: verdict 6)* |
| No Bluetooth | Bluetooth Remote ID is out of reach entirely in openwifi mode | *(verified: verdict 6)* |
| Personality exclusivity | openwifi boots from SD only and is mutually exclusive with both the IIO (QSPI) and UHD streaming personalities; inside the openwifi image the cf-ad9361 IQ DMA is disabled, so no wideband IQ | *(verified: verdict 6)*, [ADR-0004](../docs/decisions/ADR-0004-firmware-personality-and-capture-tiers.md) |
| Auto-ACK | Even in monitor mode the FPGA auto-ACKs matching frames unless `sdrctl dev sdr0 set reg xpu 11 16` is set, which is a transmission and therefore contradicts [ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md) | [openwifi](https://github.com/open-sdr/openwifi) |

The host-side alternative has the same shape of problem:
[gr-ieee802-11](https://github.com/bastibl/gr-ieee802-11) decodes 802.11a/g/p legacy OFDM only, at
5, 10 or 20 MSPS from a UHD source into a Wireshark pcap, so covering a 20 MHz Wi-Fi channel
consumes the E200's entire practical Ethernet budget of about 20 MSPS *(verified: verdict 2)* and
still cannot see 11b beacons. And the three BLE primary advertising channels (2402, 2426 and
2480 MHz) plus Wi-Fi channel 6 (2437 MHz) span 78 MHz, more than the E200's 56 MHz analog bandwidth,
so no single tuning covers Wi-Fi and BLE Remote ID together
([gr-ieee802-11](https://github.com/bastibl/gr-ieee802-11), [openwifi](https://github.com/open-sdr/openwifi)).

If openwifi is used at all, it should be an optional research personality (CSI, IQ trigger capture,
5 GHz OFDM beacon and NAN sniffing) with a Viterbi watchdog, channel hopping between ch 6 and ch 149,
the auto-ACK register set, and one explicit validation step: capture the target aircraft's RID
beacons with a commodity card first and read the radiotap data-rate field to see whether they are
1 Mbps DSSS (openwifi blind) or OFDM *(verified: verdict 6)*.

### 6.3 Software that already does this on commodity hardware

| Project | Inputs | Output | Licence / status |
|---|---|---|---|
| [opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c) | Library, plus `libopendroneidcn` for GB 46750 | Parsed ODID structures | The reference encoder/decoder; use it behind whatever capture path is chosen |
| [sxjack/unix_rid_capture](https://github.com/sxjack/unix_rid_capture) | libpcap monitor-mode Wi-Fi (rtl8812au tested), bluez >= 5.10, nRF52840 sniffer dongle | JSON (MAC, operator ID, position, heading, speed, timestamps) and GPX | Tested on a Raspberry Pi 3B, a comparable ARM class to the E200's PS; needs root or `cap_net_raw`; "probably won't receive Bluetooth 5 advertising without external hardware" |
| [luolitao/remoteid](https://github.com/luolitao/remoteid) | Go + gopacket/libpcap Wi-Fi Beacon and NAN | Web UI, offline pcap parsing (`ridparse -file`) | Parses ASTM, GB 42590 and GB 46750 in one pass |
| [luolitao/esp32-crid](https://github.com/luolitao/esp32-crid) | ESP32-S3 promiscuous sniffer | Single-line JSON (`uav_discovery`, `uav_update`, `uav_timeout`) with mac, rssi, channel, transport, protocol | A useful JSON event schema template as well as a cheap sensor |
| [cyber-defence-campus/RemoteIDReceiver](https://github.com/cyber-defence-campus/RemoteIDReceiver) | Monitor-mode Wi-Fi beacons only | Python REST/WebSocket backend plus Vue/MapLibre map | Full ASD-STAN message-type support; explicitly "a proof of concept and is not intended for production use" |
| [opendroneid/wireshark-dissector](https://github.com/opendroneid/wireshark-dissector) | pcap/pcapng | Wireshark decode | Ships sample captures usable as unit-test vectors |
| [alphafox02/droneid-go](https://github.com/alphafox02/droneid-go) | Monitor-mode Wi-Fi, Sniffle BLE, plus DJI DroneID over ZMQ | Unified JSON on ZMQ 4224 | "not open source at this time", so an integration-pattern reference only |
| [bkerler/DroneID](https://github.com/bkerler/DroneID) | Sonoff/Sniffle BLE, monitor-mode Wi-Fi or pcap replay, DJI receiver module | Merged ZMQ decoder output | Receive side only; it also contains a spoofer, which is out of scope |

The architectural point for AERIX: all of these are pcap-plus-parser pipelines on commodity radios.
The E200 earns its place on the signals nothing else can touch, which is where
[landscape.md](landscape.md) and [ADR-0010](../docs/decisions/ADR-0010-band-coverage.md) put it, not
on Remote ID.

### 6.4 Trust: an RID observation is a claim, not a fact

Remote ID has no authentication or cryptographic integrity, and spoofed aircraft appear in
compliant receivers including AeroScope and the OpenDroneID apps
([droneRemoteIDSpoofer](https://github.com/cyber-defence-campus/droneRemoteIDSpoofer)). Under the
EU rule no Authentication message is even required (section 3.3, only Japan mandates a signature).
DJI DroneID can likewise be silenced or falsified with modified firmware
([techuav registry](https://github.com/techuav/techuav.github.io)) *(verified: verdict 4)*.

So every ingested Remote ID observation should carry a provenance field and a plausibility score,
and should be corroborated against an independent physical-layer detection (an OcuSync or ELRS or
video-link signature at a consistent time, frequency and RSSI trend) before it is treated as ground
truth *(verified: verdict 7)*. The source taxonomy the verification pass recommends is
`standard_rid_wifi_beacon`, `dji_droneid_clear`, `dji_droneid_encrypted_hash` and `rf_classifier`,
never merging DroneID hashes with RID serials
([ADR-0008](../docs/decisions/ADR-0008-relation-to-aerix-observation-contract.md)).

---

## 7. What this means for the AERIX build

1. **Receive only, permanently.** No TX configuration, no waveform generation on air, no
   decryption, no use of paid decrypt services
   ([ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md),
   [ADR-0011](../docs/decisions/ADR-0011-legal-posture.md), Q6).
2. **Remote ID is the safe data class; treat it as personal data anyway**, because the EU rule
   mandates operator registration ID and operator position
   ([opendroneid-core-c](https://github.com/opendroneid/opendroneid-core-c)).
3. **Metadata by default, raw IQ on explicit opt-in.** A recording preserves content that the
   pipeline never decoded, and the reference project in this field withholds its own recordings for
   exactly that reason ([proto17/dji_droneid](https://github.com/proto17/dji_droneid),
   [ADR-0002](../docs/decisions/ADR-0002-sigmf-recordings.md)).
4. **A legal review is a gate before multi-node recording of anything beyond Remote ID**, because of
   the "systematic, more than one apparatus" reading
   ([ITenRecht](https://www.itenrecht.nl/documents/ecli/56e8eb1b-5a94-40f9-9451-3e83c35ff8c2.pdf),
   snippet; [ADR-0011](../docs/decisions/ADR-0011-legal-posture.md), Q10).
5. **Buy the dongles, keep the SDR for the SDR job.** A dual-band monitor-mode Wi-Fi NIC plus a
   Sniffle-capable BLE dongle cover every mandated Remote ID transport; the E200 covers DroneID,
   OcuSync, RC links, video links and future direction finding
   ([ADR-0010](../docs/decisions/ADR-0010-band-coverage.md)).
6. **Parse three Remote ID dialects, not one**: ASTM/ASD-STAN, GB 42590-2023 and GB 46750-2025, plus
   the DJI legacy `26:37:12` IE and the French `6A:5C:35` OUI.
7. **Expect silence from a large minority of aircraft**: C0 and legacy in the EU, everything Russian
   (network-only identification), and every drone whose operator has disabled the broadcast.

---

## Gaps

Drawn from `gaps_or_open_questions` in the research lenses and from the verification pass. These are
the things the evidence could not establish, in rough order of how much they would change the design.

1. **The "bijzondere inspanning" interpretation rests on one search snippet.** The ITenRecht ECLI
   PDF could not be fetched, so the case facts, the court level and whether it concerned radio
   scanners at all are unverified, and no case law specific to drone RF monitoring was found.
2. **No Telecommunicatiewet provision on confidentiality of communications or receive-only equipment
   could be verified**; the "artikel 18.x" hypothesis is unconfirmed, and no RDI statement on
   passive SDR monitoring exists in the evidence.
3. **GDPR handling of stored Remote ID operator registration numbers and operator positions by a
   private observation network is unaddressed**: no Autoriteit Persoonsgegevens or EASA guidance was
   found.
4. **The restriction attached to the harmonised EN 4709-002 reference in Decision (EU) 2024/2103 was
   not retrieved**, so it is unknown which parts of the standard carry presumption of conformity.
5. **The ASD-STAN prEN 4709-002 text itself was never read.** Everything about the EU message set
   here comes from the opendroneid-core-c README and the ASD-STAN whitepaper snippet.
6. **The skyzr claim that Remote ID becomes mandatory from 1 January 2026 for all drones over 250 g
   regardless of class mark could not be matched to any EU instrument** and is probably wrong.
7. **The two secondary sources disagree on whether C4 is in the class-mark scope** (skyzr lists
   C1/C2/C3 plus C5/C6, Dronavia says C1-C6).
8. **Which Wi-Fi band and channel DJI uses for Remote ID (2.4 GHz ch 6 or 5 GHz ch 149) is not
   established** *(verified: verdict 7)*, so a receiver must scan both.
9. **Per-model EU Remote ID behaviour of 2024-2026 DJI aircraft (Mini 4 Pro, Air 3, Avata 2, Neo,
   Flip, Mini 5 Pro) rests on forum reports.** No authoritative DJI statement was reachable
   (support.dji.com and enterprise-insights.dji.com are blocked from the sandbox). Validate
   empirically with one C1 and one C0 aircraft before freezing assumptions *(verified: verdict 7)*.
10. **The exact DJI model and firmware list that encrypts DroneID is known only from vendor blogs**
    ([Aerial Defence](https://www.aerial-defence.com/the-process-of-encrypting-dji-droneid-has-commenced/),
    [AeroDefense](https://aerodefense.tech/djis-drone-encryption-move-how-it-affects-aeroscopes-many-drone-detection-systems-and-national-security/)),
    and whether older EU-firmware models still transmit in the clear after 2024 is unverified.
11. **No open-source SDR decoder for BLE 5 Coded PHY exists in the surveyed set**, and the
    feasibility of implementing S=8 decoding on E200 IQ or in its FPGA is unknown. Whether
    ice9-bluetooth-sniffer's libuhd backend works against MicroPhase's `antsdr_uhd` fork is untested.
12. **openwifi on the E200 is untested here for the things that matter**: channel-6 beacon
    sensitivity, whether NAN action frames survive monitor mode, the PHY rate real drones use for
    RID beacons, and an operational watchdog for the two-hour Viterbi halt *(verified: verdict 6)*.
13. **Whether China-market DJI firmware actually broadcasts GB 42590 or GB 46750 frames, and whether
    such aircraft appear in the Netherlands, is unknown**; the two open GB 46750 implementations also
    disagree on the timestamp encoding, and the official standard texts are not openly hosted.
14. **The physical layer of Russia's ERA-GLONASS hybrid "DroneID analogue" is unknown**, and no GOST
    for a broadcast Remote ID was found; the ADS-B hook is speculative.
15. **Whether Dutch listening rules differ by band** (for example the 433 MHz, 700-1000 MHz and
    1.2 GHz allocations used by frontline-driven ELRS and video forks) was not assessed at all.
