# SiK frequency hopping — firmware-sourced facts (PRIMARY)

**Date:** 2026-09-19 · **Analyst:** rf-protocol-analyst · **Evidence level: primary source (vendor/upstream firmware C source).**

Source: `ArduPilot/SiK` master, local copy
`research/library/csdn_enriched/AERIX_RF_CSDN/non_dji_telemetry/MAVLink/SiK_3DR_Holybro/source/ArduPilot_SiK_master.zip`
→ `SiK-master/Firmware/radio/{freq_hopping.c,freq_hopping.h,main.c,tdm.c,radio_443x.c,parameters.c}`.
Line numbers below are for the files inside that archive.

**Verdict: `aerix_rf/decode/sik/raster.py`'s `hop_map()` does NOT match the firmware.** The PRNG constants
are right; the shuffle is a different algorithm and the draw width is different. Hop maps agree with the
firmware only at chance level (1–3 of N positions for NETID 25/1/4242 at N=10 and N=50).

---

## 1. The actual hop-map algorithm

### 1.1 PRNG — `freq_hopping.c:65-78`

```c
static unsigned long int r_next;

int
r_rand(void)
{
    r_next = r_next * 1103515245UL + 12345;
    return (unsigned int)(r_next/65536) % (RAND_MAX + 1U);
}

void
r_srand(unsigned int seed)
{
    r_next = seed;
}
```

Comment at `freq_hopping.c:61-64`: *"replacement for rand() and srand() from sdcc 3.0. This is needed to
keep compatibility with original frequency hopping order"* — i.e. this LCG is frozen by compatibility and
is the same across SiK builds. `r_next` is `unsigned long` (32-bit on SDCC/8051), so the recursion is
mod 2^32. `RAND_MAX` comes from SDCC `<stdlib.h>` (`radio/radio.h:48`), value 32767 → the return is
`(r_next >> 16) & 0x7FFF`. Constants `1103515245`/`12345` in raster.py are CORRECT.

### 1.2 Shuffle — `freq_hopping.c:81-93` (benpfaff "naive" shuffle, **not** Fisher–Yates/Durstenfeld)

```c
// a very simple array shuffle
// based on shuffle from
// http://benpfaff.org/writings/clc/shuffle.html
static inline void shuffle(__xdata uint8_t *array, uint8_t n)
{
	uint8_t i;
	for (i = 0; i < n - 1; i++) {
                uint8_t j = ((uint8_t)r_rand()) % n;
		uint8_t t = array[j];
		array[j] = array[i];
		array[i] = t;
	}
}
```

Three load-bearing details: the loop runs **ascending** `i = 0 … n-2`; `j` is drawn modulo **n** (the whole
array), not `i+1`; and the draw is **truncated to `uint8_t`** — `(uint8_t)r_rand()` keeps only the low 8
bits, i.e. `(r_next >> 16) & 0xFF`, not the 15-bit value. The result is not a uniform permutation; that is
irrelevant for decoding but means no "standard shuffle" shortcut is valid.

### 1.3 Seeding — `freq_hopping.c:95-118`

```c
void
shuffleRand(void)
{
  r_srand(param_get(PARAM_NETID));
#ifdef INCLUDE_AES
  if (param_get(PARAM_ENCRYPTION)) {
    r_srand(crc16(32, param_get_encryption_key()));
  }
#endif // INCLUDE_AES
}

void 
fhop_init(void)
{
	uint8_t i;
	for (i = 0; i < num_fh_channels; i++) {
		channel_map[i] = i;
	}
	shuffleRand();
	shuffle(channel_map, num_fh_channels);
}
```

The seed is NETID **only on unencrypted links**. With `ENCRYPTION` enabled the seed is
`crc16(32, encryption_key)` — the hop map then carries no NETID information and NETID brute force over
0…65535 is invalid by construction. `r_srand` takes `unsigned int` (16-bit on SDCC), matching NETID's
16-bit range; `param_get` returns a 16-bit param. Note `main.c:427` calls `r_srand(NETID)` earlier for the
base-frequency offset, but `shuffleRand()` re-seeds, so no PRNG state carries into the shuffle.

### 1.4 Window advance / TX-RX relationship — `freq_hopping.c:120-170`, `tdm.c:309`

```c
uint8_t fhop_transmit_channel(void) { return channel_map[transmit_channel]; }
uint8_t fhop_receive_channel(void)  { return channel_map[receive_channel];  }

void fhop_window_change(void)
{
	transmit_channel = (transmit_channel + 1) % num_fh_channels;
	if (have_radio_lock) {
		receive_channel = transmit_channel;
	} else if (transmit_channel == 0) {
		receive_channel = (receive_channel + 1) % num_fh_channels;
	}
}
```

`fhop_window_change()` is called once per TDM window-owner change (`tdm.c:309`), and when locked
`receive_channel == transmit_channel`. **Observer consequence (deterministic):** on a locked link both
ends transmit on the *same* physical channel within a window pair, and the physical channel advances by
exactly one virtual index per TDM window:
`phys(t) = channel_map[(c0 + t) mod N]`. raster.py's constant-offset model in
`netid_candidates_from_sequence` is therefore structurally correct; only the map is wrong.
(`main.c:439`: `radio_set_channel(NETID % num_fh_channels)` is the pre-TDM initial register value;
`transmit_channel` itself starts at 0. The unknown start phase is absorbed by the constant offset `c0`.)
Unlocked radios slow-hop their *receive* channel only — it does not perturb the observed TX sequence.

### 1.5 Python transcription for the builder (drop-in replacement for `hop_map`)

```python
_LCG_A = 1103515245
_LCG_C = 12345
_LCG_MASK = 0xFFFFFFFF

def hop_map(seed: int, n_channels: int) -> list[int]:
    """Firmware fhop_init(): channel_map[i]=i, then shuffle() from
    Firmware/radio/freq_hopping.c:84-93 seeded by r_srand(seed)."""
    state = int(seed) & 0xFFFF          # r_srand takes unsigned int (16-bit)
    m = list(range(n_channels))
    for i in range(n_channels - 1):     # ascending, n-1 draws
        state = (state * _LCG_A + _LCG_C) & _LCG_MASK
        draw = (state >> 16) & 0xFF     # (uint8_t)r_rand(); &0x7FFF then &0xFF == &0xFF
        j = draw % n_channels           # modulo n, NOT i+1
        m[i], m[j] = m[j], m[i]
    return m
```

Reference vector for a unit test: `hop_map(25, 10) == [0, 9, 5, 2, 6, 7, 4, 3, 8, 1]` (NETID default is 25,
`parameters.c:60`). This vector is derived from the C by transcription, not from a running radio — it
validates "the Python matches the C", not "the C matches the air". See §6.

---

## 2. How raster.py differs (what is wrong today)

| Aspect | raster.py `hop_map()` | Firmware | Impact |
|---|---|---|---|
| Algorithm | Durstenfeld Fisher–Yates, `i = n-1 … 1` | naive benpfaff swap, `i = 0 … n-2` | different permutation |
| Swap index | `j = draw % (i+1)` | `j = draw % n` | different permutation |
| Draw width | `(state >> 16) & 0x7FFF` (15 bit) | `(uint8_t)r_rand()` = `(state >> 16) & 0xFF` | different `j` even for identical loop |
| Draw count | n-1 | n-1 | same |
| LCG | `*1103515245 + 12345`, mod 2^32 | identical | correct |
| Seed | `netid & 0xFFFFFFFF`, always NETID | `netid & 0xFFFF`; **`crc16(32, key)` if ENCRYPTION** | encrypted links break the NETID assumption |
| Window model | `pos - window_index` const mod N | matches `(c0+t) mod N` | correct |

Measured agreement between the two maps (transcribed C vs current raster.py), positions equal:
NETID 25 → 2/10 and 3/50; NETID 1 → 2/10 and 1/50; NETID 4242 → 1/10 and 1/50. That is chance level
(expected ≈1 for a random permutation). **Any NETID recovered by the current code is meaningless**, and
synthetic hop sequences generated by the current `hop_map` are not SiK-like sequences.

---

## 3. Channel → frequency, from firmware

`main.c:399-441` (band defaults `main.c:322-346`, overrides `main.c:353-362`, clamps `main.c:371-394`):

```c
	channel_spacing = (freq_max - freq_min) / (num_fh_channels+2);
	// add half of the channel spacing, to ensure that we are well
	// away from the edges of the allowed range
	freq_min += channel_spacing/2;
	// add another offset based on network ID. ...
        r_srand(param_get(PARAM_NETID));
	if (num_fh_channels > 5) {
                freq_min += ((unsigned long)(r_rand()*625)) % channel_spacing;
	}
	radio_set_frequency(freq_min, channel_spacing);
	radio_set_channel(param_get(PARAM_NETID) % num_fh_channels);
```

`radio_443x.c:614-630`: `spacing = scale_uint32(spacing, 10000)` written to the 8-bit
`FREQUENCY_HOPPING_STEP_SIZE` register (`scale_uint32(v,s) = (v + s/2)/s`, `radio_443x.c:1097-1100`), and
`radio_set_channel()` writes the channel index to `FREQUENCY_HOPPING_CHANNEL_SELECT`. Base carrier is
quantised by `set_frequency_registers()` (`radio_443x.c:1147-1175`) to 625 Hz steps below 480 MHz and
1250 Hz steps above (`HBSEL` doubling).

So, deterministically:

```
spacing_hz = round_half_up( floor((freq_max - freq_min) / (N + 2)) / 10_000 ) * 10_000
base_hz    ≈ freq_min + floor(raw_spacing/2) + netid_offset        (quantised to 625/1250 Hz)
f(k)       = base_hz + k * spacing_hz,   k = physical channel index 0..N-1
```

Board defaults (`main.c:322-346`, PRIMARY — confirms the S1 table used by raster.py):
433 → 433.050–434.790 MHz, N=10; 470 → 470–471 MHz, N=10; 868 → 868–870 MHz, N=10;
915 → 915–928 MHz, N=MAX_FREQ_CHANNELS=50 (`freq_hopping.h:37`). `MIN_FREQ`/`MAX_FREQ`/`NUM_CHANNELS`
overrides exist and are clamped to the board's legal range; `N` is clamped to 1…50 (`main.c:371`).
**Note the 470 MHz board is missing from raster.py's `BAND_LIMITS_HZ`.**

vs raster.py:
* 10 kHz quantisation of spacing — **CONFIRMED PRIMARY** (was marked INFERRED at `raster.py:51`). Register
  is 8-bit in units of 10 kHz, hence also the `spacing ≤ 2.55 MHz` guard (`radio_443x.c:618`).
* `(freq_max-freq_min)/(N+2)` — **CONFIRMED PRIMARY**, but firmware **floors to integer Hz first** and then
  rounds half-**up**; `_nominal_spacing_hz` uses float division + Python `round()` (banker's rounding).
  Divergence is rare but real on exact `.5`-register ties.
* **raster.py has no model of the base-frequency offset.** Firmware places channel 0 at
  `freq_min + spacing/2 + netid_offset`, where `netid_offset ∈ [0, spacing)` whenever `N > 5`. The lattice
  *spacing* estimate is unaffected, but the recovered *phase* (`offset_hz`) is NETID-dependent and must not
  be compared against a fixed band-edge-derived phase. Conversely, once spacing and phase are estimated,
  the phase is an additional NETID-consistency observable — worth exploring after the map is fixed.
* `netid_offset` arithmetic is **not fully resolved**: `r_rand()*625` is `int * int`, and SDCC `int` is
  16 bits, so the product overflows/wraps before the `(unsigned long)` cast. The offset therefore is not
  simply `(draw*625) mod spacing` under 32-bit math. Do not implement an exact phase predictor until this
  is settled on a real build (see §6).

---

## 4. What must change in the code (builder task)

1. Replace `hop_map()` with the §1.5 transcription; keep the LCG constants, change loop direction, the
   `% n` modulus, the `& 0xFF` draw truncation, and mask the seed to 16 bits.
2. Update the vectorised `_hop_maps_all_netids()` the same way (the ascending naive shuffle is still
   independent across NETIDs, so the per-step numpy update pattern still works; `j` is now
   `draw % n_channels`, a full-range index, so the scatter/gather is over all columns — verify the
   `maps[rows, i] / maps[rows, j]` read-modify-write still handles `i == j` correctly).
3. Rename the parameter `netid` → `seed` and document that on `ENCRYPTION`-enabled links the seed is
   `crc16(32, key)`, so `netid_candidates_from_sequence` returns nothing meaningful there. The result type
   should carry that caveat; a "no candidate reached threshold" outcome is *not* evidence of a non-SiK link.
4. `netid_candidates_from_sequence`'s window model (`pos - window_index` constant mod N) is **correct** and
   does not need to change — but candidate uniqueness must be re-measured after the map is fixed
   (collision statistics of the naive shuffle differ from Fisher–Yates; with 65536 seeds and a
   non-uniform permutation generator, distinct NETIDs can share a hop map — test for it explicitly).
5. Regenerate every synthetic hop sequence used in tests: fixtures built with the old map are invalid.
6. `_nominal_spacing_hz`: use `floor` then round-half-up to match the firmware exactly.
7. Add the 470 MHz board to `BAND_LIMITS_HZ` (470–471 MHz, N=10) or document the omission.
8. Update the module docstring's provenance: the band table, `(max-min)/(N+2)`, 10 kHz quantisation,
   `MAX_FREQ_CHANNELS=50`, and the +1-per-window advance are all now **PRIMARY (firmware)**.

## 5. Evidence grading

| Claim | Level |
|---|---|
| LCG, shuffle, seeding, window advance, band defaults, spacing formula, 10 kHz register quantisation, 625/1250 Hz carrier quantisation | **Primary — upstream firmware C source**, quoted above |
| `RAND_MAX = 32767` (so `r_rand()` is 15-bit) | High: SDCC `<stdlib.h>` convention; not in the archive. Irrelevant to the hop map (the `uint8_t` cast discards it) but relevant to `tdm.c:653` LBT jitter and the `main.c:427` offset |
| Exact value of the NETID base-frequency offset | **Unresolved** — depends on SDCC 16-bit `int` overflow in `r_rand()*625` |
| `hop_map(25,10) == [0,9,5,2,6,7,4,3,8,1]` | Transcription-level: validates Python↔C, not C↔air |
| Anything about hop behaviour on non-`SiK-master` forks (RFD900x, Holybro/3DR factory builds, `SiK` 2.x) | **Not established** — version-scoped to this tree |

## 6. Validation experiments (machine-testable)

1. **C-vs-Python oracle (cheap, do first):** compile `shuffle()`/`r_rand()` standalone with `uint8_t`/
   `uint32_t`/16-bit-`int` semantics forced, dump `channel_map` for seeds {0,1,25,4242,65535} × N ∈ {5,10,50},
   and assert byte-equality against the Python. Acceptance: 100% match on all 15 vectors. This also settles
   the `r_rand()*625` overflow question if the harness mimics SDCC's 16-bit `int`.
2. **Passive air check (authoritative):** record a real SiK link (known NETID, known band, known N), extract
   the burst-centre sequence over ≥ 2N consecutive TDM windows, and require (a) the recovered channel index
   sequence equals `channel_map[(c0+t) mod N]` for the true NETID for ≥ N-1 of N hops, and (b)
   `netid_candidates_from_sequence` returns the true NETID uniquely. Acceptance: both, on ≥ 2 captures with
   different NETIDs.
3. **Cross-check against the cleartext header:** NETID appears in the frame header once a CRC validates —
   require the brute-forced NETID to equal the header NETID on the same capture. This is the only
   independent ground truth that does not assume our own decoder is right.
4. **Phase check:** compare the estimated raster phase against `freq_min + spacing/2 + offset(NETID)` once
   §3's overflow question is resolved. Until then, do not fail a detection on phase.

## 7. Claims that must NOT be made yet

* Do not claim NETID recovery works — it has never been tested against a correct hop map, and has never
  been tested against real air data at all.
* Do not claim the hop map is NETID-derived on encrypted SiK links (it is key-derived).
* Do not claim these findings cover RFD900x/other forks; version-scope every statement to `ArduPilot/SiK`
  master as archived here.
* Do not claim an absolute-frequency prediction for channel 0 (NETID base offset unresolved).
