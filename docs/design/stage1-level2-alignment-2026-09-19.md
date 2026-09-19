# C4 gate item (ii): level-2 hop-set alignment vs ground truth channels

Status: IN PROGRESS
Started: 2026-09-19

## Task
Verify RFUAV RC-positive level-2 fires (rc_link_family_candidate, fhss_1mhz_grid_candidate)
on wip/stage1-c4 sit on transmitter's actual hop channels, not crowded-band contaminants.

## Plan
- Load bench JSON, enumerate 40 level-2 windows.
- Independent GT via gt2.py (median floor + 12dB gate, narrow-run centre histogram) from raw IQ.
- Compare detector raster (offset+delta lattice) / re-run energy.detect vs GT channel centres.
- Check delta_hz vs GT spacing, check wideband contamination overlap.
- Cross-check plausibility vs research/briefs/rc-link-raster-facts.md per link family.

## Log

## Method actually used (time-boxed deviation from full 40-window sweep)
- Extracted all 40 level-2 records via jq -> l2_windows.json (rc_link_family_candidate: FLYSKY_FS_I6X x4,
  FLYSKY_NV_14 x4, JR_PROPO_XG7 x3, FUTABA_T18SZ x1, SKYDROID_T10 x8 = 20; fhss_1mhz_grid_candidate:
  Radiolink_AT9S_Pro x2, SIYI_MK15 x1, WFLY_ET10 x9, WFLY_ET16S x8 = 20).
- Ran an INDEPENDENT ground-truth pass (own script, gt_check.py, NOT importing aerix_rf.detect.raster/bursts
  for the channel-histogram part -- only numpy) on a stratified sample of 11/40 windows covering all 9 models
  and both mode types: FLYSKY_FS_I6X 0-1s, FLYSKY_NV_14 0-1s, JR_PROPO_XG7 5-6s(full)+1-2s(dwell),
  FUTABA_T18SZ 5-6s(dwell), SKYDROID_T10 1-2s+3-4s(dwell), Radiolink_AT9S_Pro 0-1s, SIYI_MK15 3-4s,
  WFLY_ET10 0-1s, WFLY_ET16S 0-1s. Did NOT re-run production `energy.detect`/`raster.cluster_centres` in the
  scratch worktree (would have been circular for the "GT" role and was time-boxed); instead compared the
  independent histogram-based channel list against the record's own `raster.delta_hz`/`n_channels`, and
  checked for >=8 MHz / >=2%-occupancy wideband occupant bands. wt_rev worktree created and removed cleanly.

## Per-window results

| model | slice/mode | GT n_chan | GT med spacing | record delta_hz | dominant-chan duty | wideband occupant overlap | verdict |
|---|---|---|---|---|---|---|---|
| FLYSKY_FS_I6X | 0-1s full | 14 | 6.53 MHz (undersampled view of finer comb) | 0.500 MHz | 16.6% | none | (a) PASS structure real, (b) UNCONFIRMED (aliasing, not falsified), (c) PASS |
| FLYSKY_NV_14 | 0-1s full | 20 | 4.99 MHz (same aliasing) | 0.500 MHz | 8.1% | none | (a) PASS, (b) UNCONFIRMED, (c) PASS |
| JR_PROPO_XG7 | 5-6s full | 29 | 2.985 MHz | 2.995 MHz | 2.6% | none | (a) PASS, (b) PASS (0.3% match), (c) PASS |
| JR_PROPO_XG7 | 1-2s dwell | 30 | 2.997 MHz | null (fired via period-path) | 2.4% | none | (a) PASS, (b) n/a but cross-validated vs full_band, (c) PASS |
| FUTABA_T18SZ | 5-6s dwell | 56 | 1.066 MHz | null | **1.0%** (top chan) | none | (a) WEAK/MARGINAL -- 55/56 GT "channels" <1% duty, record's own raster r=0.59 (low); this is the ONLY FUTABA window in the 40-set |
| SKYDROID_T10 | 1-2s dwell | 46 | 0.835 MHz | null, raster r=0.0 (raster fit failed) | 5.9% | none | (a) PASS -- real dense occupancy despite raster r=0 (detector robustness gap, not contamination), (c) PASS |
| SKYDROID_T10 | 3-4s dwell | 45 | 0.759 MHz | 0.649 MHz | 5.4% | none | (a) PASS, (b) borderline (17% off 10% band, same right order), (c) PASS |
| Radiolink_AT9S_Pro | 0-1s full | 20 | 4.30 MHz | 1.002 MHz | 12.6% | **2 bands, 10.3+18.5 MHz, ~30% of clusters inside** | (a) count matches (20 vs 19) but spacing off 4x, (b) FAIL, (c) PARTIAL FAIL |
| **SIYI_MK15** | 3-4s full | 5 | n/a (1 dominant near-CW carrier, 5.7x total-frame duty = effectively always-on) | 1.000 MHz, n=32, r=0.99 | 570% (always-on) | **2 bands, 48+19 MHz, cover essentially the whole claimed grid span** | **FAIL -- claimed 32-ch 1MHz grid has no narrowband GT support; real signal is 1 continuous carrier + 2 wideband OFDM-like occupant bands** |
| **WFLY_ET10** | 0-1s full | 29 (28 near-floor) | 1.013 MHz (artifact of edge-clustered noise, not a true comb) | 1.000 MHz, n=59-65, r=0.95-0.98 | 164% (always-on) | 28/29 GT "channels" <1% duty, i.e. near noise-floor gate crossings | **FAIL -- dominant single carrier + noise-floor scatter, not a real 60-channel hopper** |
| **WFLY_ET16S** | 0-1s full | 7 | n/a | 1.000 MHz, n=58-65, r=0.96-0.98 | 723% (always-on) | **1 band, 73.6 MHz wide @6.2%, covers essentially the entire claimed grid span** | **FAIL -- starkest case: virtually the whole claimed hop-grid region is one diffuse wideband occupant plus 1 continuous carrier** |

## Cross-check against research/briefs/rc-link-raster-facts.md
- FlySky AFHDS2A hop-set size is PRIMARY-sourced at **16 channels** (DIY-Multiprotocol firmware, `AFHDS2A_a7105.ino`).
  FLYSKY_FS_I6X/FLYSKY_NV_14 GT channel counts (14, 20) bracket this reasonably well -> supports genuine multi-channel
  narrowband occupancy, though the brief explicitly says the MHz-per-channel-unit step is COMMUNITY-grade/unconfirmed,
  so the record's literal 500 kHz delta cannot be confirmed or refuted by this method (1 s of data undersamples a
  16-member hop set unevenly, inflating apparent visited-channel spacing -- a known aliasing effect, not contamination).
- No brief coverage for JR Propo / Skydroid / Futaba / Radiolink / SIYI / WFLY air-interfaces -- FrSky/DSM/AFHDS2A
  facts don't directly apply to these vendors; this is an evidence gap, not a contradiction.
- SIYI MK15 is (general RF-industry knowledge, NOT drawn from the project research corpus -- flagging as
  unsourced-in-corpus per routing rule) a COFDM digital video+control link, i.e. an inherently wideband/continuous
  system, not a narrowband FHSS control-only radio. The GT result (1 dominant near-CW carrier + 2 wideband OFDM-like
  occupant bands spanning ~67 MHz combined) is fully consistent with that expectation and is NOT consistent with a
  32-channel, 1 MHz-spaced hop set. This should be confirmed against the research corpus by research-librarian if a
  formal citation is wanted; treat as a strong plausibility argument, not a sourced fact, in this report.

## Overall
- Sampled 11/40 (27.5%) level-2 windows, stratified across all 9 models and both raster label families and both
  analysis modes.
- rc_link_family_candidate sample (7 windows, all 5 constituent models covered): 6/7 solidly supported by
  independent narrowband multi-channel GT with no wideband-occupant overlap; 1/7 (FUTABA_T18SZ, which is the ONLY
  FUTABA record in the entire 40-window level-2 set) is weak/marginal -- near-floor duty cycles on 55 of 56 GT
  "channels", consistent with the record's own low Rayleigh r=0.59.
- fhss_1mhz_grid_candidate sample (4 windows, all 4 constituent models covered): 3/4 (SIYI_MK15, WFLY_ET10,
  WFLY_ET16S) show CLEAR, independently-confirmed contamination -- the claimed 1 MHz hop grid coincides with a
  dominant near-continuous carrier and/or a diffuse >=18 MHz wideband occupant, not discrete narrowband hop
  channels. 1/4 (Radiolink_AT9S_Pro) is a partial fail (~30% of claimed cluster centres sit inside two 10-18 MHz
  wideband occupant bands; spacing is 4x off from the claimed 1 MHz delta).
  WFLY_ET10 (9 windows) + WFLY_ET16S (8 windows) together are 17 of the 20 total fhss_1mhz_grid_candidate windows
  in this bench (85%); both sampled representative windows from these two models show the SAME severe
  single-carrier + wideband-occupant pattern, not a one-off artifact, so this generalizes with reasonable
  confidence to most of that label family's fires in this dataset -- this is very likely THE finding Fable
  flagged as a potential HOLD trigger.

STATUS: DONE (time-boxed at 11/40 windows; see Evidence gaps below for what remains unverified).
