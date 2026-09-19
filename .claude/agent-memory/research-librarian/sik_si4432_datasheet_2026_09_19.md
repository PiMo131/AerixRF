---
name: sik-si4432-datasheet-2026-09-19
description: Confirmed Si4432/AN440 register facts (sync word, CRC, freq deviation, data rate) that docs/design/sik-mavlink-passive-decode.md flagged RESEARCH NEEDED, plus a negative result on public SiK/RFD900 IQ
metadata:
  type: project
---

Answered the two `RESEARCH NEEDED` items in `docs/design/sik-mavlink-passive-decode.md` (lines ~127-139).
Full writeup appended to `research/briefs/rc-link-raster-facts.md` under "SiK datasheet confirmation & public
IQ (2026-09-19)" — read that section, this memory is the short version + gotchas.

## Datasheet source
Silicon Labs **AN440 Rev 0.9** ("Si4430/31/32 Register Descriptions"), fetched via WebFetch from
`silabs.com/documents/public/application-notes/AN440.pdf` and mirrored to
`research/library/datasheets/Silabs_AN440_Si4430-31-32_Register_Descriptions.pdf` (gitignored — do not
attempt to commit it). WebFetch's own text extraction failed on this PDF ("corrupted binary data" — it's a
scanned/complex-layout appnote); the fix that worked was pulling the raw PDF WebFetch had already saved under
the tool-results scratch path and running `pdftotext -layout` on it locally. If a similar PDF fails WebFetch's
built-in extraction again, check the tool-results path first before assuming the source is unreachable.

## Confirmed facts (High confidence, primary source)
- Sync word regs 0x36-0x39 POR default = `2D D4 00 00`. SiK's `radio_443x.c` never writes these registers
  (only configures sync **length** via `HEADER_CONTROL_2`/0x33 = 2-byte), so the on-air sync word is the POR
  default's top two bytes = **`0x2D 0xD4`**, matching the design doc's "0x2DD4" expectation exactly.
- Register 0x30 (Data Access Control) POR default = `0x8D` = `encrc=1, crc[1:0]=01`. AN440's polynomial table:
  `00=CCITT, 01=CRC-16(IBM), 10=IEC-16, 11=Biacheva`. So **CRC-16(IBM) with hardware CRC on is the Si4432's own
  power-on default**, not something SiK actively had to pick — SiK's explicit `ENCRC|CRC_16` write in
  `radio_443x.c` (~line 840) just reasserts it. In the Golay/FEC path SiK instead uses its own **software**
  CRC-16 (`crc.c`, ArduPilot's table-driven implementation, NOT the hardware CRC engine) computed before Golay
  encoding, because bit errors must be corrected before the CRC check (code comment ~line 825-827) — don't
  conflate the hardware-CRC path with the Golay path, they use different CRC implementations even though both
  are "CRC-16".
- Frequency deviation reg 0x72, formula `Fd = 625 Hz × fd[8:0]` (AN440 explicit statement) — confirms the
  design doc's 625 Hz LSB.
- TX data rate regs 0x6E/0x6F, POR default `0x0A3D` = 40 kbps; formula `TX_DR = 10^6 × txdr[15:0] / 2^16 bps`
  (or `/2^21` if Modulation-Mode-Control-1 bit 5 = 1, low-rate mode). SiK doesn't compute this at runtime — it
  writes precomputed per-airrate register bytes from its own constant tables in `radio_443x.c` (~line 668+).
  I spot-checked consistency for one row only, not exhaustively — treat per-row byte values as Medium, the
  formula/POR-default itself as High.

## Public IQ search — negative result
Searched GitHub ("gr-sik", "3DR radio" sigmf, RFD900 iq), Zenodo/IEEE DataPort/Kaggle (general web search
only, no native API access from this sandbox), GNU Radio's SigMF-recordings wiki. **No labeled SiK/3DR/RFD900
IQ dataset found.** One unverified lead: GitHub `SAMS0N1TE/LakeShark-Signal-Corpus` claims "reviewed SigMF IQ
recordings for open radio decoder testing" — did NOT open/vet its manifest, don't assume it contains SiK
signals until someone actually checks it. `danidask/SiKset` is a config CLI tool, not captures — false lead,
don't recheck. Conclusion unchanged from the design doc: opportunistic field recording is still the only known
route to real SiK ground truth.

## Process note
Budget was ~12 tool calls; used exactly that (2 grep/find, unzip+grep firmware source ×3, 2 web searches, 1
WebFetch, pdftotext + greps ×3, then writes). This is a good template for future single-datasheet-confirmation
requests: local firmware grep first (cheap, often has register-name constants that make the datasheet search
targeted), then one WebFetch of the specific appnote PDF, then pdftotext locally rather than re-fetching.
