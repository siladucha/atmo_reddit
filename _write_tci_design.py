#!/usr/bin/env python3
"""Write the trial-conversion-intelligence design.md file."""
import pathlib

TARGET = pathlib.Path("/Volumes/2SSD/Projects/ReddirSaaS/.kiro/specs/trial-conversion-intelligence/design.md")

CONTENT = r"""# Design Document: Trial Conversion Intelligence

## Overview

Trial Conversion Intelligence is an internal sales operations layer that treats every trial account as a sales opportunity. The system continuously collects engagement signals, computes deterministic conversion scores, manages trial lifecycle states, and provides AI-powered sales briefings — all behind a unified dashboard accessible only to Owner/Partner roles.

### Architecture Philosophy

The core architectural principle is **separation of deterministic scoring from LLM interpretation**:

```
Signals → Deterministic Scoring Engine → Score Snapshot → LLM Interpretation (cached)
```

- **Scoring path**: Pure Python computation. No network calls, no LLM. Fast (<100ms), reproducible, auditable.
- **Interpretation path**: LLM-based (Claude Sonnet). Operates only on score snapshots. Cached per score_id.

This ensures scores are reproducible from any snapshot, LLM costs are bounded, and the system degrades gracefully if LLM providers are unavailable.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Deterministic scoring (no LLM) | Reproducibility, speed, auditability, cost control |
| Score snapshot as LLM input | Decouples interpretation from signal collection |
| Cache summary per score_id | Avoid redundant LLM calls (~$0.04 each) |
| 60s debounce on recomputation | Prevent burst-scoring during rapid user activity |
| Celery for background scoring | Consistent with existing task architecture |
| Redis for debounce + dashboard presence | Already available, sub-millisecond latency |
| HTMX partials for dashboard | Consistent with admin panel patterns |

"""

TARGET.write_text(CONTENT)
print(f"Part 1 written: {len(CONTENT)} bytes")
