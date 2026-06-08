# EPG 2.0 — Attention Portfolio Manager: System Overview

## Что это

EPG 2.0 заменяет логику выбора тредов в старом EPG на многоступенчатый инвестиционный движок. Reddit рассматривается как рынок внимания, каждый аватар — как инвестиционный фонд, каждая публикация — как инвестиционное решение.

Система управляет полным pipeline: **Discovery → Scoring → Risk → Return → Allocation → Execution → Measurement → Correction**.

Генерация текста остаётся **последним** шагом, а не первым.

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                  Existing Pipeline (unchanged)                    │
│  Scrape Subreddits → Score Threads (Gemini Flash) → ThreadScore │
└─────────────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│              EPG 2.0 — Attention Portfolio Manager                │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Opportunity  │→│  Risk Engine  │→│ Return Engine │          │
│  │    Engine     │  │              │  │              │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│          ↓                                    ↓                   │
│  ┌──────────────┐                    ┌──────────────┐           │
│  │  Allocation  │←───────────────────│   Portfolio   │          │
│  │    Engine    │                    │   Manager    │           │
│  └──────────────┘                    └──────────────┘           │
└─────────────────────────────────────┬───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│              Existing Execution (unchanged)                       │
│  EPGSlot (planned) → Generate Comment → Post via PRAW + Proxy   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Файловая структура

```
app/services/
├── portfolio_manager.py     # Orchestrator + dataclasses (AttentionBudget, ReturnWeights, PortfolioAllocation)
├── opportunity_engine.py    # Market scanner + 5 scoring functions + scan_opportunities()
├── risk_engine.py           # Risk assessment + filtering + removal feedback
├── return_engine.py         # Expected return estimation + karma multiplier
└── allocation_engine.py     # Portfolio optimization + diversification + timing

app/models/
├── opportunity.py           # Opportunity (scored engagement possibility)
├── decision_record.py       # DecisionRecord (immutable audit log per day)
├── zero_day_report.py       # ZeroDayReport (explanation when 0 actions)
└── performance_metric.py    # PerformanceMetric (daily per-avatar metrics)

app/tasks/
├── epg.py                   # build_and_generate_epg_all_avatars (checks epg2_enabled flag)
├── karma_outcomes.py        # check_karma_outcomes (4h/24h/48h outcome tracking)
└── performance_metrics.py   # compute_daily_performance_metrics + archive_old_decision_records

app/templates/partials/
├── portfolio_summary.html   # Today's portfolio overview
├── portfolio_decision.html  # Full decision record drill-down
├── portfolio_zero_day.html  # Zero-day report with recommendations
├── portfolio_health.html    # System-wide health panel
├── portfolio_metrics.html   # Performance trends (7/14/30d)
├── portfolio_override.html  # Manual opportunity exclusion form
└── client_return_weights.html # Return weights config form

alembic/versions/
└── epg2_01_attention_portfolio_tables.py  # Migration for 4 new tables + 3 client columns
```

---

## Pipeline: Как работает build_portfolio()

При каждом запуске EPG (08:15 и 14:15, Asia/Jerusalem) для каждого аватара:

### 1. Attention Budget
- Определяется дневной бюджет из фазы аватара:
  - Phase 1: 3 comments, 0 posts, risk ≤ 40
  - Phase 2: 7 comments, 2 posts, risk ≤ 60
  - Phase 3: 12 comments, 3 posts, risk ≤ 75
- Если у клиента есть `max_comments_per_month` — применяется monthly cap

### 2. Opportunity Engine (scan_opportunities)
- Сканирует ThreadScore записи с тегами "engage" / "monitor"
- Для Phase 1 — также HobbySubreddit посты
- Дедупликация: исключает треды где аватар уже имеет draft/posted коммент
- Scoring (5 детерминистических функций, без LLM):
  - **Visibility** (0-100): свежесть, умеренные ups, мало комментов, размер саба
  - **Competition** (0-100): мало комментов = выше, нет доминирующего топ-коммента
  - **Trust Potential** (0-100): тема аватара, help-seeking intent, глубина дискуссии
  - **Karma Potential** (0-100): исторический avg, velocity, first-mover advantage
  - **Strategic Alignment** (0-100): ThreadScore.strategic, keyword match, phase fit
- Composite = weighted average (20% каждая dimension)
- Сортировка по composite desc, cap 10-50 результатов
- Логирует `market_scarcity` если < 10 тредов

### 3. State-Based Context
- **Phase 1 restriction**: фильтрует к hobby subreddits only
- **Brand budget exhaustion**: исключает brand content (strategic > 70) когда cap достигнут
- **Topic saturation**: -30 visibility если 5+ тредов на ту же тему за 24ч
- **Timing enforcement**: defer если last_posted_at < 45 минут назад

### 4. Risk Engine (assess_risk + filter_by_risk)
- 5 факторов риска:
  - account_age_factor (0-25): <30d→25, 30-90d→15, 90-180d→8, >180d→3
  - karma_factor (0-20): <100→20, 100-500→12, 500-2000→6, >2000→2
  - frequency_factor (0-20): 0→0, 1-3→5, 4-7→12, >7→20
  - moderation_factor (0-30): 3+ removals in 30d → 30, else 10 per removal
  - content_type_factor (0-15): brand→15, professional→8, hobby→3
- Modifiers:
  - health_modifier: +20 для warned/suspicious
  - phase_multiplier: ×2.0 на frequency + moderation для Phase 1
  - removal_feedback: +5 per historical removal (capped 30)
- Flags: "high_risk" > 70, "critical_risk" > 90
- Filter: risk_score > threshold → rejected с reason

### 5. Return Engine (estimate_returns)
- 5 dimensions expected return:
  - **Karma** (int ≥ 0): regression model (subreddit avg × multiplier × position bonus × velocity bonus × phase bonus)
  - **Trust** (0-100): trust_potential × 0.75 + dialogue bonus + phase bonus
  - **Visibility** (0-100): visibility_score × 0.70 + position bonus + cross-post bonus
  - **Influence** (0-100): trust × 0.40 + strategic × 0.35 + competition × 0.25
  - **Strategic Value** (0-100): phase-adjusted strategic_alignment
- **Composite** = normalized weighted sum (клиентские веса из return_weights)
- **Karma multiplier**: starts at 1.0, +10% after 5+ over-performances, -10% after 5+ under-performances. Clamped [0.5, 2.0]

### 6. Allocation Engine (allocate_portfolio)
- Assign opportunities to categories (primary/secondary/experimental/community)
- Greedy selection по risk-adjusted return (composite / max(1, risk_score))
- Category budget: `floor(total × category% / 100)`
- **Diversification**: no single subreddit > 40% of actions
- **Reallocation**: empty categories redistribute proportionally
- **Timing**: deterministic spacing across 08:00-23:00 with min 45 min intervals
- **Shannon entropy**: diversification metric
- Returns: AllocationResult (selected actions, rejected + reasons, budget info, diversification score)

### 7. Persist & Output
- Opportunity records updated (status: selected/rejected, rejection_reason)
- EPGSlot записи для каждого selected action
- Decision Record (immutable): avatar state, community states, market state, client state, allocation, budget, metrics
- Если 0 selected → Zero-Day Report с reason code + 2-5 рекомендаций
- Return EPGResult (backward-compatible с existing consumers)

### 8. Error Handling
- Полный pipeline обёрнут в try/except
- При failure → rollback + fallback на legacy `build_daily_epg()`
- Performance warning если > 60 секунд

---

## Feedback Loop (Post-Execution)

### Karma Outcome Tracking (`check_karma_outcomes`)
- Runs: каждые 4 часа (12:15, 18:15, 00:15, 06:15)
- Находит opportunities с EPGSlots в status "posted"
- Проверяет outcome на 4h, 24h, 48h после posting
- Обновляет: `actual_karma`, `actual_removal`, `outcome_checked_at`
- Deviation > 50% → logs `model_correction_event`

### Removal Feedback
- Каждый removal (actual_removal=True) → +5 risk points для avatar-subreddit pair
- Накапливается, cap at 30 points
- Автоматически применяется через `community_state.risk_adjustment` в следующих оценках

### Karma Multiplier Correction
- 5+ over-performances (actual > 150% predicted) → multiplier ×1.1
- 5+ under-performances (actual < 50% predicted) → multiplier ×0.9
- Clamped [0.5, 2.0]

---

## Daily Performance Metrics (`compute_daily_performance_metrics`)

Runs: 01:00 daily. Computes per avatar:

| Metric | Formula |
|--------|---------|
| Return_On_Attention | karma_gained / actions_taken |
| Risk_Adjusted_Return | ROA / avg_risk_score |
| Portfolio_Diversification | Shannon entropy of subreddit distribution |
| Decision_Accuracy | % actions with positive karma |
| Opportunity_Cost | max(0, highest_rejected - avg_selected composite) |
| Zero_Day_Rate | % zero-day days in last 30 days |

### Alerts (14-day window):
- Zero_Day_Rate > 50% → ActivityEvent alert "strategy reconfiguration needed"
- Decision_Accuracy < 50% → ActivityEvent alert "model review recommended"

### Archival (`archive_old_decision_records`)
- Runs: 01:30 daily
- Deletes Opportunity records > 90 days old
- Decision Record metadata retained indefinitely

---

## Zero-Day Reports

Генерируются когда allocation даёт 0 selected actions.

### Reason Codes:
| Code | Meaning |
|------|---------|
| `market_scarcity` | < 10 scoreable threads found |
| `market_cold` | No opportunities at all |
| `risk_too_high` | >70% rejections by risk |
| `return_too_low` | Average return < 20 |
| `avatar_state_unfavorable` | Avatar health/state issues |

### Recommendations (2-5 per report):
- `add_new_subreddits`
- `adjust_risk_threshold` (с suggested value)
- `change_strategy_focus`
- `wait_for_better_timing`
- `review_avatar_health`

---

## Admin UI

### Portfolio Tab (per avatar)
- `/admin/avatars/{id}/portfolio` — Summary: allocation bars, budget utilization, top 3 opportunities, metrics
- `/admin/avatars/{id}/portfolio/decision/{date}` — Full decision drill-down
- `/admin/avatars/{id}/portfolio/zero-day` — Zero-day report
- `/admin/avatars/{id}/portfolio/metrics` — Trends (7/14/30 days)
- `/admin/avatars/{id}/portfolio/override` — Manual exclusion + re-allocation

### Dashboard Panel
- `/admin/dashboard/portfolio-health` — System-wide: total actions today, zero-day avatars, avg ROA, alerts

### Client Configuration
- `/admin/clients/{id}/return-weights` — Custom weights (karma/trust/visibility/influence/strategic_value)

---

## System Settings (группа "epg")

| Setting | Default | Description |
|---------|---------|-------------|
| `epg2_enabled` | `true` | Master feature flag — instant rollback to legacy |
| `epg2_min_opportunities` | `10` | Minimum before market_scarcity |
| `epg2_max_opportunities` | `50` | Max evaluated per avatar |
| `epg2_min_return_threshold` | `20` | Minimum composite return |
| `epg2_subreddit_max_share` | `40` | Diversification cap (%) |
| `epg2_zero_day_alert_threshold` | `50` | Alert trigger (%) |
| `epg2_decision_retention_days` | `90` | Days before archival |

---

## Database: Новые таблицы

### `opportunities`
- 7 CHECK constraints (все scores 0-100)
- Indexes: (avatar_id, decision_date), status, (avatar_id, decision_date, status)
- Lifecycle: evaluated → selected/rejected → executed
- Outcome tracking: actual_karma, actual_removal, outcome_checked_at

### `decision_records`
- UNIQUE(avatar_id, decision_date) — prevents duplicate daily runs
- JSONB: avatar_state, community_states, market_state, client_state, portfolio_allocation, budget_available, budget_consumed, metrics
- Immutable audit trail

### `zero_day_reports`
- reason_code, report_content (JSONB), recommendations (JSONB)
- Index: (avatar_id, report_date)

### `performance_metrics`
- UNIQUE(avatar_id, metric_date)
- 6 float metrics + 2 integer counts
- Index: (avatar_id, metric_date)

### Client extensions
- `return_weights` JSONB (default: {"karma":20, "trust":25, "visibility":20, "influence":15, "strategic_value":20})
- `brand_mention_cap` INTEGER (nullable)
- `max_comments_per_month` INTEGER (nullable)

---

## Celery Beat Schedule (новые задачи)

| Time | Task | Purpose |
|------|------|---------|
| 08:15, 14:15 | `build_and_generate_epg_all_avatars` | Calls `build_portfolio()` when epg2_enabled |
| 12:15, 18:15 | `check_karma_outcomes` | 4h after EPG runs |
| 00:15, 06:15 | `check_karma_outcomes` | 24-28h checks |
| 01:00 | `compute_daily_performance_metrics` | Aggregate yesterday's metrics + alerts |
| 01:30 | `archive_old_decision_records` | Prune opportunities > 90 days |

---

## Integration с existing системой

| Что | Как |
|-----|-----|
| ThreadScore | Input: pre-scored threads from Gemini Flash |
| EPGSlot | Output: same format, same downstream processing |
| timing_engine | Used: jitter ±30%, min 45 min, active hours |
| posting_safety.py | Respected: all 9 safety gates unchanged |
| execute_pending_posts | Picks up EPGSlots from EPG 2.0 identically |
| Activity Events | Portfolio alerts via ActivityEvent model |
| Audit Trail | Decision records + PostingEvent + audit log |

---

## Feature Flag: Instant Rollback

```python
# In Celery task:
if epg2_enabled:
    epg = build_portfolio(db, avatar, client)  # EPG 2.0
else:
    epg = build_daily_epg(db, avatar, client)  # Legacy
```

Toggle `epg2_enabled` to "false" in admin settings → immediate revert to legacy without deployment.

---

## Ключевые свойства

1. **Детерминистический scoring** — никаких LLM-вызовов в pipeline (LLM scoring уже сделан upstream)
2. **Бюджет как hard ceiling** — никогда не превышает max_actions
3. **Diversification enforced** — no subreddit > 40%
4. **Zero-day = first-class output** — не ошибка, а осознанное решение с обоснованием
5. **Self-correcting** — karma feedback loop adjusts predictions over time
6. **Full audit trail** — каждое решение traced и explainable
7. **Backward-compatible** — same EPGResult, same EPGSlot, same downstream processing
8. **< 60 seconds per avatar** — performance target for allocation pipeline
