# Auto Competitor Discovery — Design

## Architecture Overview

```
Onboarding Complete (onboarding_completed_at set)
         │
         ▼
┌─────────────────────────┐
│ Celery Task:            │
│ auto_discover_competitors│  ← triggered by step6_activate
│ (Gemini Flash, 3-5 calls)│
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ DiscoveredCompetitor    │  ← new model
│ records (confirmed=null) │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ Client Notification:    │
│ "Review competitors"    │  ← SSE + portal badge
└─────────┬───────────────┘
          │ (client confirms)
          ▼
┌─────────────────────────┐     ┌──────────────────────┐
│ Auto-create:            │     │ Auto-create:         │
│ - GeoCompetitor records │     │ - DiscoverySession   │
│ - GeoPrompt records     │     │ - Auto-run research  │
│ - First GEO batch       │     │ - Generate report    │
└─────────────────────────┘     └──────────────────────┘
```

## New Model: DiscoveredCompetitor

```python
class DiscoveredCompetitor(Base):
    __tablename__ = "discovered_competitors"

    id: UUID (pk)
    client_id: UUID (FK → clients)
    name: str  # competitor name
    source_query: str  # what prompt found it
    source_platform: str  # "gemini_flash" | "manual"
    confidence: float  # 0.0 - 1.0
    status: str  # "pending" | "confirmed" | "rejected" | "not_competitor"
    confirmed_at: datetime | None
    created_at: datetime
```

## AI Discovery Prompts

### Query 1: Category discovery
```
"List the top 10 {product_category} tools or platforms in the {industry} space. 
Include both well-known and emerging solutions. Return JSON: {\"competitors\": [{\"name\": \"...\", \"reason\": \"...\"}]}"
```

Product category inferred from `company_profile` (e.g. "exposure management platform" → "exposure management")

### Query 2: Alternative discovery  
```
"What are the main alternatives to {brand_name} for {problem_statement}? 
Return JSON: {\"competitors\": [{\"name\": \"...\", \"reason\": \"...\"}]}"
```

### Query 3: Problem-space discovery
```
"A {icp_job_title} looking to solve {customer_pain} — what tools/solutions would they evaluate?
Return JSON: {\"competitors\": [{\"name\": \"...\", \"reason\": \"...\"}]}"
```

## Deduplication Logic

After all queries return:
1. Normalize names (lowercase, strip Inc/Ltd/Corp/etc)
2. Merge duplicates (same name from multiple queries = higher confidence)
3. Exclude the client's own brand name
4. Exclude known false positives (generic terms: "open source", "in-house", etc.)
5. Cross-reference with `client.competitive_landscape` (mark those as pre-confirmed)
6. Sort by confidence (# of queries that mentioned them)

## GEO Prompt Auto-Generation

Template prompts created per confirmed competitor:

| Template | Example |
|----------|---------|
| `best {category} tools` | "best exposure management tools" |
| `{brand} vs {competitor}` | "XM Cyber vs Tenable" |
| `alternatives to {competitor}` | "alternatives to Wiz" |
| `{problem} solutions` | "attack path analysis solutions" |

## Trigger Mechanism

In `onboarding.py` → `step6_activate()`:
```python
# After quality gate passes and client activated:
from app.tasks.competitor_discovery import auto_discover_competitors
auto_discover_competitors.delay(str(client.id))
```

## Client Portal UI

New section in portal home (trial clients):
```
┌─────────────────────────────────────┐
│ 🔍 Competitor Intelligence          │
│                                      │
│ We discovered 7 potential competitors│
│ in AI search results.                │
│                                      │
│ ☑ Tenable (from: "best exposure...")│
│ ☑ Wiz (from: "alternatives to...")  │
│ ☑ CrowdStrike (from: category)     │
│ ☐ Qualys (from: category)          │
│ ☐ Rapid7 (from: "attack path...")  │
│                                      │
│ [Confirm Selected] [Skip for now]   │
└─────────────────────────────────────┘
```

## Timeout / Fallback

- If client doesn't review within 48h → `operator_notification` event
- Operator can confirm on behalf (admin action)
- If client clicks "Skip for now" → uses only `competitive_landscape` from onboarding
- Discovery Engine starts with whatever is available (confirmed or onboarding-provided)

## Cost Estimate

| Operation | Model | Calls | Cost |
|-----------|-------|-------|------|
| Category discovery | Gemini Flash | 1 | $0.0003 |
| Alternative discovery | Gemini Flash | 1 | $0.0003 |
| Problem-space discovery | Gemini Flash | 1 | $0.0003 |
| Parse + dedup | Code only | 0 | $0 |
| **Total per client** | | **3** | **$0.001** |

## Dependencies

- Existing: `GeoCompetitor` model, `GeoPrompt` model, `DiscoverySession` model
- Existing: `notify_client()` (SSE notifications)
- Existing: `run_continuous_discovery()` (can be triggered per-client)
- New: `DiscoveredCompetitor` model (1 migration)
- New: `auto_discover_competitors` Celery task
- New: Portal partial for competitor review
