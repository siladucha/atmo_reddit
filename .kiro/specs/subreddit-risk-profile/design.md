# Design Document: Subreddit Risk Profile

## Overview

The Subreddit Risk Profile system adds a data-driven safety layer between Smart Scoring and Comment Generation. It extracts subreddit rules via PRAW + LLM, learns moderation patterns from KarmaSnapshot deletion data, computes a dynamic risk score per subreddit, and gates unsafe avatar-subreddit pairings before wasting LLM tokens. A dedicated UI page shows the full profile with daily history for all roles.

## Architecture

### System Context

```
Sunday Weekly Batch (Celery Beat)
  05:00 --- Rule Extraction -----> SubredditRiskProfile.extracted_rules
  05:15 --- Moderation Profile --> SubredditRiskProfile.moderation_profile
  05:30 --- Risk Score ----------> SubredditRiskProfile.risk_score

Pipeline (08:00 / 14:00 daily)
  Smart Scoring --> [Fitness Gate] --> Generate Comments
                      | block |
                      v       |
               ActivityEvent   |
               "fitness_block" |

UI (admin + portal)
  /admin/subreddits/<id>/risk-profile --- Risk Profile Page (admin)
  /portal/subreddits/<id>/risk-profile -- Risk Profile Page (client)
```

### Component Diagram

```
+------------------------+     +------------------------+
| rule_extractor.py      |     | moderation_profiler.py |
| (PRAW + Gemini Flash)  |     | (KarmaSnapshot agg)   |
+----------+-------------+     +-----------+------------+
           |                               |
           v                               v
+------------------------------------------------------+
|         SubredditRiskProfile (model)                  |
| + SubredditDailyStats (model)                        |
+-------------------------+----------------------------+
                          |
          +---------------+---------------+
          v               v               v
+---------------+ +---------------+ +-------------------+
| risk_scorer   | | fitness_gate  | | risk_profile      |
| .py           | | .py           | | _routes.py        |
| (compute)     | | (pipeline)    | | (UI endpoints)    |
+---------------+ +---------------+ +-------------------+
```

---

## Data Models

### SubredditRiskProfile (new model)

```python
class SubredditRiskProfile(Base):
    __tablename__ = "subreddit_risk_profiles"

    id: UUID PK
    subreddit_id: UUID FK(subreddits.id, CASCADE) UNIQUE NOT NULL

    # Risk score
    risk_score: Integer(0-100), CHECK, default=50
    risk_score_history: JSONB  # [{"week": "2026-W25", "score": 42}, ...]
    is_high_risk: Boolean, default=False

    # Extracted rules
    extracted_rules: JSONB  # [{"category": "min_karma", "description": "...", "threshold_value": "500"}, ...]
    extraction_status: String  # pending | success | no_content | extraction_failed
    last_rule_extraction_at: DateTime(tz), nullable

    # Moderation profile
    moderation_profile: JSONB  # {"removal_rate": 0.15, "aggressiveness": "medium", "patterns": [...]}
    dangerous_hours: JSONB  # [14, 15, 22]  (hours in dominant timezone)
    confidence_level: String  # insufficient_data | low | medium | high
    last_profile_computed_at: DateTime(tz), nullable

    # Recommendations
    recommendations: JSONB  # ["Avoid posting before 10am", ...]
    dominant_timezone: String, default="UTC"

    # Timestamps
    created_at: DateTime(tz), server_default=now()
    updated_at: DateTime(tz), onupdate=now()
```

**Indexes:**
- `ix_srp_subreddit_id` UNIQUE on subreddit_id
- `ix_srp_risk_score` on risk_score
- `ix_srp_extraction_status` on extraction_status

### SubredditDailyStats (new model)

```python
class SubredditDailyStats(Base):
    __tablename__ = "subreddit_daily_stats"

    id: UUID PK
    subreddit_id: UUID FK(subreddits.id, CASCADE) NOT NULL
    date: Date NOT NULL
    comments_posted: Integer, default=0
    comments_survived: Integer, default=0
    removal_rate: Float  # computed: 1 - survived/posted (0 if posted=0)
    computed_at: DateTime(tz)
```

**Constraints:**
- UNIQUE(subreddit_id, date)
- Index on (subreddit_id, date)

### AvatarSubredditCompatibility - add field

```python
# Add to existing model:
fitness_score: Integer(0-100), nullable  # Subreddit risk fitness gate score
fitness_computed_at: DateTime(tz), nullable
```

---

## Components and Interfaces

### Internal Interfaces

| Component | Interface | Consumers |
|-----------|-----------|-----------|
| `rule_extractor.py` | `extract_subreddit_rules(subreddit_name: str) -> ExtractionResult | None` | `risk_profile.py` task |
| `rule_extractor.py` | `refresh_all_subreddit_rules(db: Session) -> dict` | `risk_profile.py` task |
| `moderation_profiler.py` | `compute_moderation_profile(db: Session, subreddit_name: str) -> ModerationProfile` | `risk_profile.py` task |
| `moderation_profiler.py` | `compute_daily_stats(db: Session, subreddit_name: str) -> None` | `risk_profile.py` task |
| `risk_scorer.py` | `compute_risk_score(profile: SubredditRiskProfile) -> int` | `risk_profile.py` task |
| `risk_scorer.py` | `refresh_all_risk_scores(db: Session) -> dict` | `risk_profile.py` task |
| `fitness_gate.py` | `evaluate_fitness(db, avatar, subreddit_name, current_hour=None) -> FitnessResult` | `ai_pipeline.py` task |
| `fitness_gate.py` | `batch_evaluate_fitness(db, avatar, thread_subreddit_pairs) -> list[FitnessResult]` | `ai_pipeline.py` task |

### External Dependencies

| Dependency | Usage | Rate Limit |
|-----------|-------|-----------|
| PRAW (Reddit API) | Fetch subreddit sidebar + wiki | 60 req/min per token |
| Gemini Flash (LiteLLM) | Rule extraction from sidebar text | No hard limit (cost: ~$0.0003/call) |

### Database Interfaces

| Model | Relationship | Access Pattern |
|-------|-------------|----------------|
| SubredditRiskProfile | 1:1 with Subreddit | Read by fitness_gate (per pipeline run), Write by weekly batch |
| SubredditDailyStats | N:1 with Subreddit | Read by UI (last 30 days), Write by weekly batch |
| AvatarSubredditCompatibility | Extended with fitness_score | Read by UI, Write by fitness_gate |
| Subreddit | Extended with is_high_risk | Read/Write by risk_scorer |

---

## Service Layer

### 1. `app/services/rule_extractor.py`

```python
class ExtractedRule(BaseModel):
    category: Literal["min_karma", "min_account_age", "no_self_promo",
                      "required_flair", "posting_frequency_limit",
                      "content_restriction", "other"]
    description: str  # max 200 chars
    threshold_value: str | None  # e.g. "500", "30 days", None

class ExtractionResult(BaseModel):
    rules: list[ExtractedRule]  # max 20

def extract_subreddit_rules(subreddit_name: str) -> ExtractionResult | None:
    """Fetch sidebar/wiki via PRAW, send to Gemini Flash for structured extraction."""
    # 1. PRAW: subreddit.description_html + subreddit.wiki["rules"]
    # 2. Concatenate, truncate to 4000 chars
    # 3. LLM prompt -> ExtractionResult (Pydantic validation)
    # 4. Retry once on validation failure
    # 5. Return None on permanent failure

def refresh_all_subreddit_rules(db: Session) -> dict:
    """Batch: iterate active subreddits, extract rules, update profiles."""
    # Sequential with 3s delay, circuit breaker at 50% failure
```

### 2. `app/services/moderation_profiler.py`

```python
@dataclass
class ModerationProfile:
    removal_rate: float  # 0.0 - 1.0
    aggressiveness: str  # low | medium | high | extreme
    dangerous_hours: list[int]  # hours (0-23) in dominant timezone
    patterns: list[dict]  # [{"type": "time_of_day", "detail": "14-16", "pct": 0.35}]
    confidence_level: str  # insufficient_data | low | medium | high
    total_posted: int
    total_deleted: int

def compute_moderation_profile(db: Session, subreddit_name: str) -> ModerationProfile:
    """Aggregate KarmaSnapshot + CommentDraft deletion data for 30-day window."""
    # 1. Query comment_drafts WHERE subreddit=X AND status="posted" AND posted_at >= 30d ago
    # 2. Left join karma_snapshots for is_deleted
    # 3. Compute removal_rate = deleted / total
    # 4. If total >= 10: compute hourly distribution, find dangerous hours (>2x avg)
    # 5. Classify aggressiveness by thresholds
    # 6. Identify patterns (>30% of removals from same cause)

def compute_daily_stats(db: Session, subreddit_name: str) -> None:
    """Upsert SubredditDailyStats for last 30 days."""
    # GROUP BY date(posted_at), count posted vs survived
```

### 3. `app/services/risk_scorer.py`

```python
def compute_risk_score(profile: SubredditRiskProfile) -> int:
    """Weighted risk score computation.

    Weights:
    - Removal Rate (40%): linear 0-100 from removal_rate
    - Aggressiveness (25%): low=10, medium=40, high=70, extreme=100
    - Rule Strictness (20%): min(rule_count * 12, 100)
    - Trend Direction (15%): slope of last 4 weeks, mapped to 0-100
    """

def refresh_all_risk_scores(db: Session) -> dict:
    """Batch: compute risk scores for all profiles."""
```

### 4. `app/services/fitness_gate.py`

```python
@dataclass
class FitnessResult:
    passed: bool
    score: int  # 0-100
    blocked_by: str | None  # rule name that blocked
    reason: str | None  # human-readable explanation

def evaluate_fitness(
    db: Session,
    avatar: Avatar,
    subreddit_name: str,
    *,
    current_hour: int | None = None,
) -> FitnessResult:
    """Evaluate avatar-subreddit fitness. Returns pass/block decision.

    Checks (in order):
    1. Profile exists? (fail-open if not)
    2. min_karma rule vs SubredditKarma.comment_karma
    3. min_account_age rule vs avatar.reddit_account_created
    4. posting_frequency_limit vs recent post count
    5. Extreme aggressiveness + <50 karma -> block
    6. Dangerous hours + <200 karma -> block

    Returns FitnessResult with score (0-100) and block reason if any.
    """

def batch_evaluate_fitness(
    db: Session,
    avatar: Avatar,
    thread_subreddit_pairs: list[tuple],
) -> list[FitnessResult]:
    """Evaluate multiple threads for a single avatar in one pass.

    Preloads SubredditKarma and SubredditRiskProfile in bulk
    to avoid N+1 queries. Max 50ms per thread.
    """
```

---

## Celery Tasks

### `app/tasks/risk_profile.py`

```python
@celery_app.task(name="extract_subreddit_rules_batch")
def extract_subreddit_rules_batch():
    """Sunday 05:00 - Extract rules for all active subreddits."""
    # Acquire distributed lock "risk_profile_batch" TTL=1800s
    # Sequential processing with 3s delay
    # Circuit breaker: >50% failures -> 120s pause
    # Log ActivityEvent on completion

@celery_app.task(name="compute_moderation_profiles_batch")
def compute_moderation_profiles_batch():
    """Sunday 05:15 - Compute moderation profiles from deletion data."""
    # Also computes daily stats

@celery_app.task(name="compute_risk_scores_batch")
def compute_risk_scores_batch():
    """Sunday 05:30 - Compute risk scores and update high_risk flags."""
    # Emit risk_score_spike events when delta > 15
```

### Celery Beat additions (worker.py)

```python
"risk-profile-rules-weekly": {
    "task": "extract_subreddit_rules_batch",
    "schedule": crontab(hour=5, minute=0, day_of_week="sunday"),
},
"risk-profile-moderation-weekly": {
    "task": "compute_moderation_profiles_batch",
    "schedule": crontab(hour=5, minute=15, day_of_week="sunday"),
},
"risk-profile-scores-weekly": {
    "task": "compute_risk_scores_batch",
    "schedule": crontab(hour=5, minute=30, day_of_week="sunday"),
},
```

---

## Pipeline Integration

### Where Fitness Gate Hooks In

In `app/tasks/ai_pipeline.py :: generate_comments()`:

```python
# After getting engage_threads list, before generation loop:
if is_fitness_gate_enabled(db):
    from app.services.fitness_gate import evaluate_fitness
    filtered_threads = []
    blocked_count = 0
    for thread in engage_threads:
        result = evaluate_fitness(db, avatar, thread.subreddit)
        if result.passed:
            filtered_threads.append(thread)
        else:
            blocked_count += 1
            record_activity_event(db, "fitness_block", ...)
    engage_threads = filtered_threads
```

**Key design decision:** Fitness Gate operates per-avatar during generation (not during scoring). This is because:
1. Smart Scoring already runs per-avatar
2. The same thread might be safe for one avatar (high karma) but not another (low karma)
3. Gate checks are DB-only (no API calls), under 50ms per thread

---

## Routes and UI

### Admin Route: `app/routes/admin_risk_profile.py`

```python
router = APIRouter(prefix="/admin/subreddits")

@router.get("/{subreddit_id}/risk-profile")
def admin_subreddit_risk_profile(subreddit_id, db, user):
    """Full risk profile page (admin roles)."""

@router.get("/{subreddit_id}/risk-profile/daily-history")
def admin_risk_profile_daily_history(subreddit_id, db, user):
    """HTMX partial: daily stats table (lazy-loaded)."""

@router.get("/{subreddit_id}/risk-profile/trend-chart")
def admin_risk_profile_trend_chart(subreddit_id, db, user):
    """HTMX partial: 12-week risk score trend (lazy-loaded)."""
```

### Portal Route: `app/routes/portal_risk_profile.py`

```python
router = APIRouter(prefix="/portal/subreddits")

@router.get("/{subreddit_id}/risk-profile")
def portal_subreddit_risk_profile(subreddit_id, db, user):
    """Client-scoped risk profile page."""
    # Scopes avatars/stats to user's client only
```

### Templates

```
templates/
  admin_subreddit_risk_profile.html     # Full page (extends admin_base.html)
  client/subreddit_risk_profile.html    # Portal page (extends client_base.html)
  partials/
    risk_profile_header.html            # Score badge + trend sparkline
    risk_profile_rules.html             # Extracted rules list
    risk_profile_daily_history.html     # Daily stats table (HTMX partial)
    risk_profile_trend_chart.html       # 12-week trend (HTMX partial)
    risk_profile_avatars.html           # Avatar fitness scores
    risk_profile_insights.html          # Dangerous hours + patterns
    risk_profile_recommendations.html   # AI recommendations
```

### UI Layout

```
+--------------------------------------------------------------+
| r/sysadmin - Risk Profile                        [Risk: 67]  |
+--------------------------------------------------------------+
| Risk Score Trend (12 weeks)              [chart/sparkline]    |
+--------------------------------------------------------------+
| Rules (extracted from sidebar)                                |
| +-----------------------------------------------------------+|
| | lock min_karma: 500 comment karma required                 ||
| | lock min_account_age: 30 days minimum                      ||
| | warn no_self_promo: No promotional content                 ||
| | note required_flair: Post must have flair                   ||
| +-----------------------------------------------------------+|
+--------------------------------------------------------------+
| Moderation Insights                                           |
| +-----------------------------------------------------------+|
| | Aggressiveness: HIGH (removal rate 32%)                    ||
| | Dangerous Hours: 14:00-16:00, 22:00-23:00 UTC             ||
| | Patterns: 45% removals from accounts < 100 karma          ||
| +-----------------------------------------------------------+|
+--------------------------------------------------------------+
| Recommendations                                               |
| - Avoid posting between 14:00-16:00 (peak mod activity)       |
| - Build 100+ karma before commenting on popular posts         |
| - No promotional language or brand mentions                   |
+--------------------------------------------------------------+
| Avatar Fitness                                                |
| +------------------+---------+--------------------------+    |
| | Avatar           | Score   | Issues                   |    |
| +------------------+---------+--------------------------+    |
| | Hot-Thought2408  | 82 OK   | -                        |    |
| | CyberGuy_99      | 35 BAD  | karma < 500, age < 30d  |    |
| +------------------+---------+--------------------------+    |
+--------------------------------------------------------------+
| Daily History (30 days)                    [lazy-loaded]       |
| +----------+--------+----------+-----------------------+     |
| | Date     | Posted | Survived | Removal Rate          |     |
| +----------+--------+----------+-----------------------+     |
| | Jun 22   | 4      | 3        | 25%                   |     |
| | Jun 21   | 6      | 6        | 0%                    |     |
| | Jun 20   | 3      | 2        | 33%                   |     |
| +----------+--------+----------+-----------------------+     |
+--------------------------------------------------------------+
```

---

## Database Migration

### Alembic migration `xxx_add_subreddit_risk_profile.py`

1. Create `subreddit_risk_profiles` table
2. Create `subreddit_daily_stats` table
3. Add `fitness_score` + `fitness_computed_at` columns to `avatar_subreddit_compatibility`
4. Add `is_high_risk` column to `subreddits` table
5. Create indexes

---

## LLM Prompt (Rule Extraction)

```
Model: Gemini Flash (cheap, fast)
Temperature: 0.1

System: You are a Reddit moderation rule parser. Extract formal rules from subreddit sidebar/wiki text.

User: Extract all posting rules from this subreddit sidebar. Return a JSON array of rules.

Each rule must have:
- category: one of min_karma, min_account_age, no_self_promo, required_flair,
            posting_frequency_limit, content_restriction, other
- description: concise rule description (max 200 chars)
- threshold_value: numeric or duration value if applicable (e.g. "500", "30 days"),
                   null if not applicable

Return max 20 rules. If no rules found, return empty array.

Sidebar text:
---
{sidebar_text}
---

Return ONLY valid JSON array, no markdown.
```

---

## Configuration

### System Settings (DB)

| Key | Default | Description |
|-----|---------|-------------|
| `fitness_gate_enabled` | `true` | Enable/disable fitness gate in pipeline |

### Constants (code)

| Constant | Value | Location |
|----------|-------|----------|
| `RULE_EXTRACTION_DELAY_SECONDS` | 3 | rule_extractor.py |
| `CIRCUIT_BREAKER_THRESHOLD` | 0.5 | risk_profile task |
| `CIRCUIT_BREAKER_PAUSE_SECONDS` | 120 | risk_profile task |
| `LOCK_KEY` | "risk_profile_batch" | risk_profile task |
| `LOCK_TTL_SECONDS` | 1800 | risk_profile task |
| `DANGEROUS_HOUR_MULTIPLIER` | 2.0 | moderation_profiler |
| `PATTERN_THRESHOLD_PCT` | 0.30 | moderation_profiler |
| `FITNESS_KARMA_HEADROOM_MAX` | 1000 | fitness_gate |
| `FITNESS_AGE_HEADROOM_MAX_DAYS` | 365 | fitness_gate |
| `RISK_SCORE_HISTORY_WEEKS` | 12 | risk_scorer |
| `MODERATION_WINDOW_DAYS` | 30 | moderation_profiler |
| `MIN_POSTS_FOR_DANGEROUS_HOURS` | 10 | moderation_profiler |
| `MIN_POSTS_FOR_CONFIDENCE` | 5 | moderation_profiler |

---

## File Structure (new files)

```
reddit_saas/app/
  models/
    subreddit_risk_profile.py    # SubredditRiskProfile model
    subreddit_daily_stats.py     # SubredditDailyStats model
  services/
    rule_extractor.py            # PRAW + Gemini Flash rule extraction
    moderation_profiler.py       # KarmaSnapshot aggregation + patterns
    risk_scorer.py               # Weighted risk score computation
    fitness_gate.py              # Pre-generation safety gate
  tasks/
    risk_profile.py              # Weekly batch Celery tasks
  routes/
    admin_risk_profile.py        # Admin risk profile pages
    portal_risk_profile.py       # Client portal risk profile
  templates/
    admin_subreddit_risk_profile.html
    client/subreddit_risk_profile.html
    partials/
      risk_profile_header.html
      risk_profile_rules.html
      risk_profile_daily_history.html
      risk_profile_trend_chart.html
      risk_profile_avatars.html
      risk_profile_insights.html
      risk_profile_recommendations.html
```

---

## Performance Considerations

1. **Fitness Gate under 50ms**: Preload SubredditRiskProfile + SubredditKarma for all candidate subreddits in a single query before iterating threads. No per-thread DB calls.

2. **Weekly batch timing**: 50 subreddits x 3s delay = 2.5 min for rule extraction. PRAW + LLM = ~5s per subreddit total. Full batch: ~5 min (well within 1800s lock TTL).

3. **Daily stats computation**: Single SQL GROUP BY query, no iteration. Indexed on (subreddit_id, date).

4. **UI lazy loading**: Daily history + trend chart loaded via HTMX partials to keep initial page load fast.

---

## Security and RBAC

- Admin routes: `require_superuser` or `require_avatar_admin`
- Portal routes: `require_client_access` - scopes all data to user's client
- Client roles see only their avatars' data in daily stats and fitness scores
- No sensitive data exposed (no passwords, tokens, or proxy URLs in risk profiles)

---

## Correctness Properties

### Property 1: Fail-Open Guarantee
If SubredditRiskProfile is missing or unreadable, Fitness Gate MUST allow generation (never block pipeline due to missing data).

### Property 2: Idempotent Batch
Running the weekly batch twice in succession produces the same SubredditRiskProfile state (last-write-wins on all fields).

### Property 3: Risk Score Bounded
risk_score is always in [0, 100] range, enforced by CHECK constraint at the database level.

### Property 4: Score History Append-Only
risk_score_history only appends new entries (never removes), capped at 12 weeks using FIFO eviction of oldest entry.

### Property 5: Daily Stats Unique
SubredditDailyStats has UNIQUE(subreddit_id, date) constraint. Upsert pattern prevents duplicates on recomputation.

### Property 6: Budget Consumption
A fitness-blocked thread counts as consumed (budget decremented by 1) and is never re-evaluated on the same calendar day.

### Property 7: Lock Safety
Distributed lock TTL (1800s) exceeds maximum batch duration (~5 min for 50 subs) with large margin, preventing stale locks from blocking subsequent runs.

---

## Testing Strategy

1. **Unit tests**: `test_fitness_gate.py` - parametrized tests for each rule check
2. **Unit tests**: `test_risk_scorer.py` - weight calculations, edge cases
3. **Unit tests**: `test_moderation_profiler.py` - aggregation, threshold classification
4. **Integration test**: `test_pipeline_with_fitness_gate.py` - verify gate blocks correctly in pipeline
5. **LLM mock**: Rule extraction tests mock the LLM response to verify Pydantic validation + retry

---

## Error Handling

| Scenario | Handler | Recovery |
|----------|---------|----------|
| PRAW 403/404 on sidebar fetch | Log activity event, mark extraction_status="no_content" | Skip subreddit, continue batch |
| PRAW rate limit (429) | 3s delay between subs; circuit breaker at 50% failure | Pause 120s, resume |
| LLM validation failure (Pydantic) | Retry once after 5s | Mark extraction_status="extraction_failed", continue |
| LLM timeout | Catch as validation failure | Same retry/fail path |
| No KarmaSnapshot data (<5 posts) | Set confidence_level="insufficient_data" | Assign default risk_score=50 |
| Distributed lock not acquired | Log warning, abort batch | Next weekly run will retry |
| Fitness gate DB query failure | Fail-open (allow generation) | Log fitness_gate_warning event |
| Risk score spike (delta > 15) | Emit risk_score_spike activity event | Operator reviews in Decision Center |

---

## Migration Path

1. Deploy models + migration (no runtime impact)
2. Deploy services + tasks (inactive until first Sunday run)
3. First Sunday: batch runs, populates profiles
4. Next business day: fitness gate active (gated by system setting)
5. Monitor ActivityEvents for fitness_block frequency - tune thresholds if too aggressive
