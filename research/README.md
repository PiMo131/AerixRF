# AERIX RF research library

This directory is the handoff point between raw research and the AERIX RF engineering team.

## Layout

```text
research/
├── README.md
├── index.md          # compact source catalog maintained by research-librarian
├── briefs/           # focused reusable decision briefs
└── library/          # local raw papers/manuals/datasets; ignored by git
```

Place PDFs, manuals, downloaded papers, technical notes, or other local source material in `research/library/` on the Linux machine running Claude Code.

The `research-librarian` agent owns broad reading and indexing. Other agents should normally ask the architect for a focused research brief instead of reading the raw library themselves.

## Brief naming

Prefer descriptive filenames such as:

```text
briefs/dji-droneid-frame-evidence.md
briefs/ocusync-o3-o4-observability.md
briefs/hackrf.md
briefs/antsdr-e200.md
briefs/rf-datasets.md
```

Each brief should answer a specific reusable question and include sources, confidence, contradictions, implications for AERIX RF, and unresolved questions.

## Raw data

Do not commit large papers, proprietary manuals, copied web archives, raw IQ recordings, or datasets merely so an agent can read them. Keep raw material local and version only the index/briefs that are useful to the engineering project.
