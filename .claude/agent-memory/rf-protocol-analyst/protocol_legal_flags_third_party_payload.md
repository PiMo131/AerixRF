---
name: protocol-legal-flags-third-party-payload
description: Three recurring legal/ethics flags (third-party MAVLink telemetry, third-party video, Wi-Fi beyond management frames) plus the no-transmit consequence for bench validation
metadata:
  type: project
---

Three flags recur on every non-DJI decode question and each needs an explicit user ruling **before** a builder is tasked, not after:
- **FLAG-A — RULED 2026-09-19: passive decode of third-party MAVLink over SiK/mLRS is APPROVED for research** (receive-only). Retention still binds: aircraft/home position and NETID/sysid are personal data with the DroneID 7-day expiry, and the parser stays behind a default-off config flag. FLAG-A remains open for any *other* MAVLink-carrying link. Original framing: third-party MAVLink telemetry decode (SiK, mLRS, Paparazzi, and Herelink/SIYI/Skydroid/Yuneec H520 if their PHY is ever solved). Payload is cleartext and passive receive is trivial, but it recovers another operator's position, home location and airframe telemetry. Recommended default: build the detector, gate the payload parser behind an explicit config flag + documented authorisation basis.
- **FLAG-B — third-party video content** (analog 5.8 GHz, HDZero, Walksnail, OpenHD). Carrier detection/characterisation is in scope; demodulating content is not. The corpus already draws this line in `digital_video/proprietary_detection_only/NOTES.md`.
- **FLAG-C — Wi-Fi-based aircraft** (Parrot, Wi-Fi toy drones, OpenHD). Observing 802.11 management frames (SSID/OUI/beacons) is ordinary passive spectrum use; associating, decrypting or capturing data frames is not.

**Why:** AERIX is passive-receive-only by charter, but "passive" does not automatically settle whether reading a third party's cleartext position is appropriate. Raised 2026-09-19 in `research/briefs/non-dji-targets.md`.

**No-transmit consequence (easy to miss):** bench-validating ELRS/SiK requires *someone* to key a transmitter. AERIX must not. Compliant routes are (a) recorded third-party IQ, (b) capture where operators are already transmitting for their own purposes (an FPV field), or (c) the user personally operating a radio they are authorised to operate — which is the user's decision and must never be assumed by an agent or written into a build task ("borrow an ELRS TX and key it" is not an acceptable task line).

**How to apply:** attach the relevant flag to any decode recommendation and state it is blocking; never present a flagged capability as available. Related: [[protocol-non-dji-decodability]], [[protocol-sik-phy-facts]].
