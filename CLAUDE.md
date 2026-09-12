# AERIX RF — Claude Code operating guide

This directory uses a project-local multi-agent workflow. The preferred main session is:

```bash
cd aerix-rf
claude --agent aerix-rf-architect
```

The main architect is Opus. Do not bypass the architect for substantial project work unless explicitly requested.

## Project purpose

AERIX RF adds passive RF/SDR-based drone detection and protocol analysis to AERIX for signals that are not covered by Open Drone ID reception.

Current source-of-truth project documents:
- `README.md`
- `AERIX_RF_ANTSDR_PROJECT.md`

Build on the existing implementation. Do not restart the project from scratch.

## Safety and scope

This is a passive receive-only project. Work may include receiving, measuring, detecting, classifying, storing, replaying, demodulating, and decoding signals where technically and legally appropriate.

Do not add transmit, interference, jamming, spoofing, takeover, deauthentication, or active interrogation functionality.

## Agent architecture

The architect may delegate to:

| Agent | Role | Model |
|---|---|---|
| `research-librarian` | Owns papers, web research, local research library and source index | Sonnet |
| `hackrf-specialist` | HackRF hardware/software knowledge | Sonnet |
| `antsdr-specialist` | ANTSDR E200 / AD9361 hardware/software knowledge | Sonnet |
| `rf-dsp-specialist` | RF/DSP algorithm design and validation | Opus |
| `rf-protocol-analyst` | Protocol evidence and decode-feasibility reasoning | Opus |
| `hardware-architect` | Cross-hardware receiver/system architecture | Opus |
| `python-builder` | Bounded Python/application/DSP implementation | Sonnet |
| `sdr-backend-builder` | Bounded SDR backend/driver implementation | Sonnet |
| `test-reviewer` | Independent test and evidence review | Sonnet |
| `fable-reviewer` | Major planning-gate and difficult-decision review | Fable |

## Knowledge routing rule

The research corpus belongs to `research-librarian`.

Other agents should NOT independently reread broad papers/manual collections. They should receive a focused brief from the architect. This includes builders and Opus specialists.

Detailed research-librarian agent memory is treated as that agent's working knowledge base. Other agents should not inspect it directly unless the architect explicitly decides that a specific note is needed.

Device manuals and broad device research belong to the corresponding device specialist.

## Major planning workflow

For a new phase, major capability, new protocol target, or new hardware integration:

```text
USER
  ↓
OPUS ARCHITECT
  ↓
focused research + device specialist bootstrap
  ↓
DSP / protocol / hardware specialist interpretation as needed
  ↓
architect draft mini-plan + 10-20 meaningful questions
  ↓
FABLE REVIEW of compact decision packet
  ↓
architect improves plan/questions
  ↓
USER answers / chooses
  ↓
architecture + acceptance criteria frozen
  ↓
builder(s)
  ↓
independent test-reviewer
  ↓
architect reports results and next decision
```

Do not make the user coordinate subagents manually.

For small tasks inside an already-approved phase, shorten this process. Do not manufacture 20 questions when the decision is already made.

## Progress reporting

The architect should report during substantial work at natural milestones, not only at the end. Updates should summarize findings and decisions, not paste raw worker transcripts.

## Fable cost discipline

Fable is not a general-purpose worker.

Use it:
- once at major planning gates;
- for important unresolved architecture disputes;
- for difficult escalations after focused specialist work.

Do not use it for:
- repository search;
- routine coding;
- test execution;
- documentation;
- ordinary debugging;
- reading large research corpora.

Give Fable a compact decision packet.

## Research library

Local papers/manuals can be dropped into:

```text
research/library/
```

The raw library is intentionally ignored by git. The research librarian should index sources in `research/index.md`, keep detailed reusable knowledge in agent memory, and create focused durable summaries under `research/briefs/` when useful.

## Evidence levels

Always distinguish:
1. RF candidate / morphology;
2. probabilistic classification;
3. protocol-specific evidence;
4. validated deterministic decode;
5. operator-provided test truth.

Do not present a stage-1 RF candidate as a confirmed drone merely because its bandwidth, cadence, or spectrogram resembles a known system.

## Hardware strategy

HackRF is the first field-test platform. ANTSDR E200 / AD9361 is the next target. Keep the shared receiver abstraction extensible without prematurely implementing ANTSDR-specific acceleration.

Device-specific limitations must not silently become universal assumptions.

## Completion criteria

Meaningful changes require:
- an approved scope;
- implementation;
- targeted tests;
- independent review for consequential changes;
- correct evidence wording;
- documentation/memory update;
- explicit remaining unknowns.
