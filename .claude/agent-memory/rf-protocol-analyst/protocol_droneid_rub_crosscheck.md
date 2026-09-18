---
name: protocol-droneid-rub-crosscheck
description: Durable facts from cross-checking AERIX's DroneID decoder against RUB-SysSec/DroneSecurity real IQ samples (field offsets, coord constant, RUB has no turbo decoder, sample files are pre-segmented)
metadata:
  type: project
---

Cross-check of `aerix_rf/decode/droneid.py` + `decode/frame.py` against RUB-SysSec/DroneSecurity
(NDSS'23) on its two real 50 MS/s IQ captures. Verified 2026-09-18.

**Deterministic facts (re-derivable, but expensive to re-derive):**
- Frame field offsets agree exactly with RUB's `struct.unpack("<BBBHH16siihhhhhhQiiiiBB20sH", raw[0:91])`:
  len@0, msg_type/"unk"@1 (=16), version@2 (=2), seq@3 u16, state@5 u16, **serial@7 16 bytes**,
  drone_lon@23, drone_lat@27, @31/@33 (RUB calls them altitude/height, proto17 calls them
  height/altitude — offsets identical, *names swapped*), vN@35 vE@37 vU@39 yaw@41, gps_time@43 u64,
  app_lat@51, app_lon@55, home_lon@59, home_lat@63, product_type@67, uuid_len@68, uuid@69,
  CRC16@89. Our 19-byte uuid + trailing-zero @88 vs RUB's 20-byte uuid is the only difference and
  is cosmetic.
- Coordinate scaling: RUB divides by the rounded `174533.0`; we use `1e7/57.2957795785523 =
  174532.9252`. Ratio 1.00000043 → ~2.4 m apparent offset at 51.4 deg. **Both receivers recover the
  identical int32** (e.g. 8979083). Any coord comparison against RUB README values must allow this,
  or compare raw int32.
- **RUB's receiver has no turbo decoder.** `src/qpsk.py:magic()` de-rate-matches and keeps only the
  *systematic* bit stream, discarding both parity streams; their "CRC OK" is the inner DJI CRC16
  (crcmod poly 0x11021, init 0x3692, rev=True) over bytes[0:89]. AERIX runs a real LTE turbo decoder
  and checks CRC24A over 173 bytes. So AERIX decoding *more* frames than RUB on the same file is the
  expected outcome, not a red flag.
- RUB drops candidates two ways we do not: `estimate_offset()` CFO/10-MHz-shape gate in
  `packetizer.py`, and `Packet.__init__` raising unless the symbol-6 ZC root == 147.
- **The `samples/` files are NOT continuous spectrum captures.** README: they are dumps from the live
  receiver's first detection stage. mini2_sm = 727,500 complex samples = 14.55 ms holding 10 frames
  (~1.455 ms per pre-segmented slice); mavic_air_2 = 225,280 samples = 4.51 ms. They therefore
  validate sync/demod/turbo/CRC/parse only — **not** our envelope + PSD candidate screening under
  real clutter.
- Serial field content: mini2_sm decodes to `"SysSecWasHere "` (13 chars + space = 14) on all frames;
  RUB's own README example output shows `"SecureStorage?"` (also 14). Both are researcher-chosen
  strings padded to DJI's conventional 14-char serial length — treat RUB captures as
  modified/instrumented serials, never as examples of genuine DJI SN format.
- Licence: RUB repo is **AGPL-3.0** (whole repo, samples included). AERIX RF has no LICENSE file.
  Do not vendor the sample files; reference them through `$AERIX_RF_DATASET_ROOT` (existing
  convention, see `research/datasets/README.md`) with sha256 pinning:
  mavic_air_2 `623fa40f190d3fd859ec2fd62b379ad9a01a0485db3179ae29ac2e3c7a070450`,
  mini2_sm `5a17913cb11cde2919347054700345c9e5595eaff7818980d332b8ac8910bc55`.

See [[protocol-droneid-evidence-gating]].
