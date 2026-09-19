# RC/control-link raster facts for Stage-1 signature vocabulary

**Question:** five discriminator facts requested by `docs/design/stage1-link-signatures.md` §11 (items 1-5): DJI RC
2.4 GHz uplink raster, ExpressLRS air-time-per-rate, FlySky AFHDS2A channel plan, BLE hop-increment behaviour, and
real-world Wi-Fi beacon-interval spread.

## 1. DJI RC 2.4 GHz uplink hop-set span / channel count / raster offset — **UNKNOWN (BLOCKING, unresolved)**
No primary numeric source found this pass. NDSS'23 (Schiller et al.) states only that "the control uplink uses
frequency hopping with narrower [channels than the 20 MHz OFDM downlink]," sourced generically to "the FCC ID
database" with **no channel count, spacing, span, or offset given** in the paper text (checked full body, not just
abstract). Their citation [15] (`FCC ID SS3-MT2WD2007`, DJI Mini 2) is cited elsewhere in the paper for RC hardware,
not for this sentence. I attempted to pull that filing's test-report exhibits directly (`fccid.io`, `fcc.report`,
and `apps.fcc.gov/oetcf/eas` — the FCC's own OET database) — **all three returned HTTP 403 (Akamai/anti-bot block)**
from this sandbox; this is a network-access limitation, not evidence that the data doesn't exist. A DJI/Qualcomm
patent that looked promising (`EP3659264A1`, "Frequency hopping in an uplink control channel") is an **unrelated
Qualcomm LTE/NR PUCCH patent**, not DJI RF — false lead, discard. The local 17-article leegang12 DJI corpus (our
densest DJI source) covers DroneID-broadcast and OFDM/ZC physical layer only — zero hits for "跳频"/"hopping" — it
does not cover the RC→aircraft control uplink at all.
**How Stage-1 should use it:** §2(e)'s BLE-vs-DJI-RC raster separation **cannot be evidence-based today**. Do not
hardcode a DJI-RC raster/offset value. Two paths forward: (a) architect routes a live HackRF/ANTSDR capture of an
actual DJI RC transmitting (RC powered, no aircraft link needed) to `hardware-architect`/device specialists —
this is now the only way to close the gap short of buying FCC exhibit access from a non-blocked network; (b) accept
the rule stays gated behind "co-located 20 MHz OFDM downlink present" (already true per §2(e)) rather than raster
alone, and treat this as a permanent design constraint, not a temporary unknown.

## 2. ExpressLRS air-time per packet, 50 Hz–1000 Hz — **PRIMARY for period, UNKNOWN for on-air duration**
`src/include/common.h` (`ExpressLRS/ExpressLRS`, fetched from GitHub `master` this pass) defines
`expresslrs_mod_settings_s.interval`, commented **"interval in us [that] corresponds to that frequency"** — i.e.
the packet *repetition period*, not the transmitted symbol duration:
50 Hz → 20000 µs, 150 Hz → 6667 µs, 250 Hz → 4000 µs, 500 Hz (LoRa) → 2000 µs, 1000 Hz (`RATE_FLRC_2G4_1000HZ`) →
1000 µs. These period values are PRIMARY (shipping firmware header, directly quoted) and match `FHSS.cpp`'s 80×1 MHz
channel table (`FREQ_HZ_TO_REG_VAL(2400400000)`…`2479400000`, sync channel = count/2+1) already in the corpus. The
*actual on-air transmission duration* (SF/BW/CR-dependent for LoRa, bitrate-dependent for FLRC — always shorter
than `interval`) lives in a rate-config array we did not locate in `src/lib/{SX1280Driver,OTA}` this pass (not a
negative result — likely in a target-specific `tx_main.cpp`/`rx_main.cpp` not checked; budget-limited). Secondary
sources (blog posts) conflate "20 ms airtime at 50 Hz" with the period above — **do not cite that as on-air
duration**.
**How Stage-1 should use it:** the `interval` values above are safe, primary-grade edges for the *hop-cadence*
(packets-per-second / re-hop timing) part of the duration histogram; do **not** use them as the occupied-burst-width
edge — that still needs either a firmware follow-up read of the target-specific rate table or a bench measurement
(route to `sdr-backend-builder`/`hackrf-specialist` if precision on the burst-width edge specifically is needed).

## 3. FlySky AFHDS2A channel spacing/count/hop rate — **COMMUNITY/UNKNOWN, do not admit to Δ dictionary**
No primary source (firmware, decompiled binary, or FCC filing) found in the local corpus or via web this pass. The
corpus's own `non_dji_telemetry/RC_telemetry/FlySky/NOTES.md` states explicitly: "No RF air-interface RE" — only
iBUS/PPM *serial*-layer parsing has been reverse-engineered locally, not the 2.4 GHz FHSS air interface. Public web
search this pass surfaced no FCC-grade or firmware-grade AFHDS2A channel table either (multiprotocol-TX-module
implementations exist per the corpus but were not verified as primary this pass).
**How Stage-1 should use it:** confirms the design doc's own caution — leave AFHDS2A out of the Δ dictionary until
someone reads the actual multiprotocol-module AFHDS2A source (a bounded follow-up request, not done here) or an FCC
filing is reachable.

## 4. BLE channel-selection Algorithm #1/#2 hop-increment + connection-interval lattice — **PRIMARY (well-established spec facts)**
- **Algorithm #1** (mandatory, BT4.0+): `hopIncrement` is drawn from the integer range **[5, 16]** (11 possible
  values) — Bluetooth Core Specification Vol 6, Part B, §4.5.8 (cross-confirmed via MathWorks' Bluetooth Toolbox
  reference page, which quotes the spec range directly). Successive selected channels differ by this fixed
  increment (mod 37, with the "remap" table skipping bad channels) — a **regular, small-increment lattice**.
- **Algorithm #2** (BT5.0+, used whenever both sides support it): channel is a PRNG function of the event counter +
  access address, not a fixed increment — **effectively pseudorandom** across the used-channel set, no fixed-delta
  discriminator available.
- **Connection interval**: 7.5 ms – 4.0 s in 1.25 ms steps — standard Core-spec Vol 6 Part B §4.5.1 parameter
  (high-confidence, textbook fact, not separately re-verified against spec PDF this pass but not disputed anywhere).
**How Stage-1 should use it:** hop-increment is **not usable as a blind RF (undecoded) discriminator** — you cannot
observe `hopIncrement` without demodulating the access address and payload, so it does nothing for a spectrogram/
burst-only detector. What *is* passively observable is the **connection-interval periodicity itself**: a BLE
connection's burst cadence is quantised to 1.25 ms steps inside [7.5 ms, 4 s] — already captured by §5's
`ble_connection_like` cadence check; this item doesn't add a new blind feature, it only explains *why* Algorithm #2
links look more random than #1 ones if anyone ever gets far enough to decode channel maps. Recommend not spending
further budget trying to make hop-increment a Stage-1 feature.

## 5. Real-world Wi-Fi beacon-interval spread around 102.4 ms — **COMMUNITY (credible practitioner sources), Medium confidence**
Nominal is exact: 100 TU × 1.024 ms/TU = 102.4 ms (802.11 standard, high confidence). TBTT is a *target*, not a
guarantee: per CWNP and Intuitibits (established Wi-Fi practitioner technical sites, not peer-reviewed, but
consistent with 802.11 medium-access rules) actual beacons are delayed — never early — by CSMA/CA contention when
the medium is busy at TBTT; under load this produces a **one-sided, right-skewed jitter** (some intervals well over
102.4 ms, essentially none under). No specific quantitative jitter-distribution paper was found this pass (searched
directly; none returned). Clock-drift-induced jitter (oscillator ppm error) is a separate, much smaller effect than
contention-induced delay in busy environments.
**How Stage-1 should use it:** §9's ±2% beacon-interval discount tolerance should probably be **asymmetric**
(tighter early-side, looser late-side) rather than symmetric, since real deviation is contention-driven and
one-directional — flag this as a design suggestion to `rf-dsp-specialist`, not a hard number (no measured percentile
table exists to set the late-side bound precisely).

## Sources
- NDSS'23 Schiller et al. (`research/library/.../ndss2023_f217_paper.pdf` reference; re-fetched+`pdftotext`'d this
  pass from `ndss-symposium.org`), full text scanned for FCC/hop/channel mentions.
- `fccid.io`, `fcc.report`, `apps.fcc.gov/oetcf/eas` — attempted, all HTTP 403 this pass (network-blocked, not
  evidence-negative).
- `patents.google.com/patent/EP3659264A1` — checked and discarded (unrelated Qualcomm LTE patent).
- GitHub `ExpressLRS/ExpressLRS` `master` branch: `src/include/common.h` (rate enum + `interval` field, fetched
  raw), `src/lib/FHSS/FHSS.cpp`/`FHSS.h` (already in local corpus, channel table cross-checked).
- `research/library/csdn_enriched/AERIX_RF_CSDN/non_dji_telemetry/RC_telemetry/FlySky/NOTES.md` (local, read).
- Bluetooth Core Specification Vol 6 Part B §4.5.8 (hop increment) / §4.5.1 (connection interval) — via
  `mathworks.com/help/bluetooth/...` secondary confirmation, spec itself not directly fetched this pass.
- CWNP (`cwnp.com/cwnp-wifi-blog/80211-beacon-intervals`), Intuitibits (`intuitibits.com/2017/08/28/...`) —
  practitioner technical write-ups on TBTT/beacon jitter.

## Open follow-ups (not done this pass, name if reopened)
- DJI RC uplink raster: needs either a non-sandboxed FCC exhibit fetch or a live capture — architect decision.
- ExpressLRS true on-air duration table: needs a deeper firmware read (`tx_main.cpp`/rate-config array) or bench
  measurement.
- FlySky AFHDS2A: needs a multiprotocol-TX-module firmware source read (not attempted this pass).
