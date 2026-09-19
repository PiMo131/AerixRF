---
name: dji-generations-q1-verification-2026-09
description: Primary-source (dji.com) verification of the DJI aircraft-to-link-generation table in briefs/dji-generations-and-o3o4-identification.md, done 2026-09-19.
metadata:
  type: project
---

Verified 19 DJI aircraft against dji.com spec/FAQ/announcement pages (web search snippets + one direct
fetch of dji.com/mini-3/specs) for the Q1 table in
`research/briefs/dji-generations-and-o3o4-identification.md`. Result appended as a
"Q1 verification (2026-09-19)" section in that brief, with `research/index.md` updated to reflect the
now-primary-confirmed status.

**Confirmed exact DJI-stated transmission-system names (all agree with the brief's prior analyst claim
except Avata):**
- OcuSync 2.0: Mavic 2 Pro/Zoom, Mavic Air 2, Mini 2.
- Enhanced Wi-Fi (no OcuSync): Mavic Mini, Mini SE.
- DJI O2: Mini 2 SE, Mini 3 (non-Pro, dji.com/mini-3/specs literally says "Video Transmission System:
  DJI O2" — directly fetched), Mini 4K.
- O3: Air 2S, Mini 3 Pro, DJI FPV.
- O3+: Mavic 3 (/Classic/Pro), **Avata** (correction — brief had said "OcuSync 3.0" for Avata; DJI's own
  name is O3+, same family as Mavic 3, no decode-relevance change).
- O4: Mini 4 Pro, Air 3, Air 3S, Avata 2, Neo (this resolves the brief's "uncertain" flag on Neo — DJI
  confirms O4 is used with controller/goggles; phone-only control uses separate Wi-Fi), Flip.

**Still unresolved (no dji.com page found in this search pass) — do NOT upgrade from D-UNVERIFIED:**
Mavic 4 Pro (claimed "O4+" — not found on any dji.com page; DJI's O4 Air Unit/O4 Ground Station pages are
about the FPV/enterprise ecosystem, not the Mavic 4 Pro specifically), Mini 5 Pro (launched 2025-09-17,
no transmission-system spec surfaced), Neo 2 (only a secondary source, dronexl.co, claims the onboard O4
module was removed in favor of an external O4 transponder — not confirmed against a primary dji.com page).

**Net effect on the brief's conclusions:** no change to any decode-feasibility claim, the O2 shortlist, or
the campaign measurement plan. This was purely upgrading evidence grade (B-VENDOR → primary-confirmed) for
rows already believed correct, plus catching one naming nuance (Avata = O3+) and resolving one uncertainty
(Neo = O4, confirmed).

**Method note for future verification passes:** WebSearch against `site:dji.com` queries reliably surfaces
DJI's own spec/FAQ/announcement page snippets with the exact transmission-system field wording (e.g.
"Video Transmission System: DJI O2"). One direct WebFetch of a `dji.com/<model>/specs` page confirmed the
snippet-quoted wording is accurate (Mini 3 non-Pro case) — worth spot-checking at least one row per batch
this way before trusting search-snippet paraphrase for the rest, since the search tool's summarized text is
itself an LLM paraphrase and could invert "O2"/"O3" if not careful.
