import pathlib

content = '''# Design Document: Trial Conversion Intelligence

## Overview

Trial Conversion Intelligence is an internal sales-ops layer that transforms every 14-day trial account into a prioritized sales opportunity. The system collects behavioral signals, computes deterministic scores, and provides LLM-powered interpretation — all accessible through a unified dashboard restricted to Owner/Partner roles.

### Architecture Principle: Deterministic Scoring + LLM Interpretation

The core architectural decision separates computation from interpretation:

```mermaid
flowchart TD
    subgraph Collection["SIGNAL COLLECTION LAYER"]
        OE[Onboarding Events]
        PA[Portal Actions]
        PE[Pipeline Events]
        CJ[Celery Jobs - Negative Signal Detection]
    end

    subgraph Scoring["DETERMINISTIC SCORING ENGINE"]
        WA[Weighted Signal Aggregation]
        CS[Conversion_Score + Priority_Score + Opportunity_Value]
        SE[Score_Explanation + Recommended_Action]
        LS[Lifecycle State Machine]
    end

    subgraph LLM["LLM INTERPRETATION LAYER - cached per score_id"]
        SS[Sales_Summary - Claude Sonnet]
        SO[Suggested_Outreach - 4 drafts]
        FA[Failure Analysis + Reactivation Intel]
    end

    Collection -->|trial_signals table| Scoring
    Scoring -->|trial_scores snapshot| LLM
```

**Why this separation matters:**
1. Scores are reproducible - same snapshot always produces same score
2. LLM costs are minimized - interpretation runs only on-demand, cached per snapshot
3. Auditability - every score change can be traced to specific signals
4. Speed - dashboard loads use precomputed scores (no LLM latency)

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scoring approach | Deterministic weighted aggregation | Reproducible, auditable, fast, no LLM cost |
| LLM for summaries | Claude Sonnet via LiteLLM | Matches existing ai.py infrastructure |
| Caching strategy | Per-score_id snapshot cache | Regenerate only when score changes |
| Debounce window | 60 seconds | Prevents scoring thrash during rapid actions |
| Negative signals | Celery Beat periodic checks | 72h inactivity needs async detection |
| Dashboard access | Owner + Partner only | Internal sales tool, not client-facing |
| Score storage | Append-only trail | Full history for trend analysis |
| Timezone | Asia/Jerusalem (system-wide) | Matches existing infra |
'''

p = pathlib.Path('/Volumes/2SSD/Projects/ReddirSaaS/.kiro/specs/trial-conversion-intelligence/design.md')
p.write_text(content, encoding='utf-8')
print(f"Part 1 written: {p.stat().st_size} bytes")
