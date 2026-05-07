# Ori Project vs ThreddOps Architecture Audit + Persona/Avatar Matching Layer Spec

Date: 2026-05-07
Scope: reverse-engineering audit of Ori n8n/Airtable/Supabase workflows against current ThreddOps SaaS codebase, plus backend design for a scalable persona/avatar matching layer.

## Executive Summary

Ori is a strong single-client Reddit operations PoC. Its durable value is not its infrastructure, but its product logic: subreddit-first discovery, rich qualification, persona-aware response strategy, anti-sales voice rules, and behavior sampling that makes engagement less repetitive.

ThreddOps is already architecturally stronger for SaaS. The current codebase has FastAPI, Celery, PostgreSQL, shared subreddit registry, per-client `ThreadScore`, audit/activity events, scrape queue freshness, Redis rate limiting, distributed locks, avatar safety checks, health/status tracking, and human review. The main gap is that persona/avatar routing is still too fused and LLM-driven, while risk, reputation, subreddit affinity, sanctions, and diversity entropy are not yet first-class matching primitives.

Recommended direction: keep ThreddOps backend-first and subreddit-centric. Adapt Ori's strategic and naturalism layers into typed backend services with explicit evidence, scoring, audit logs, and human approval. Reject Ori's n8n/Airtable operational shape as a long-term SaaS architecture.

## Source Inventory Reviewed

- Ori workflows: `Scrape subreddit copy.json`, `Run subreddits - Cyber copy.json`, `XM Cyber _ Write comments copy.json`, `Hobby Comment Writing copy.json`, related Airtable CSV exports.
- Current ThreddOps docs: `docs/architecture.md`, `docs/database_schema.md`, `docs/reddit_tos_compliance.md`, `docs/architectural_gap_analysis_ori_vs_backend.md`.
- Current ThreddOps code: `reddit_saas/app/tasks/*`, `reddit_saas/app/services/scoring.py`, `reddit_saas/app/services/generation.py`, `reddit_saas/app/services/safety.py`, `reddit_saas/app/models/*`.

## A. Gap Matrix

| Capability | Ori | ThreddOps Current | Recommended Target |
|---|---|---|---|
| Primary ingestion model | Subreddit batch workflows, hardcoded lists | Shared `subreddits` registry, queue tick, stale-first scrape | Keep subreddit-centric ingestion as canonical |
| Duplicate prevention | In-memory permalink/post text Sets in n8n | Global `reddit_native_id` uniqueness, DB dedup | Keep DB uniqueness; add source/content hash for edited/deleted edge cases |
| Multi-client isolation | None, XM Cyber-specific | Per-client assignments and `ThreadScore`; avatars use `client_ids` array | Normalize avatar-client/persona-client relationships; remove array as routing core |
| Scrape scheduling | n8n cron and fixed waits | Celery beat `queue_tick`, freshness window, Redis limiter | Keep; add priority lanes and adaptive freshness per subreddit |
| Scraper isolation | n8n workflow-level sequential isolation | Distributed lock per subreddit | Keep; add worker pool separation for scrape/AI/health |
| Rate-limit handling | Fixed 15s waits | Redis sliding window, rate-limit metrics | Keep; add jitter/backoff and per-token budget when multiple OAuth tokens exist |
| Proxy/OAuth model | Assumes simple/shared access | Single Reddit app/read-only PRAW | OK for read-only MVP; future per-token read pools only after real scale signal |
| Ingestion normalization | n8n Set nodes and image extraction code | `RedditThread` normalized record, simple media handling | Improve media/comment normalization, but keep backend model |
| Qualification/scoring | Rich structured schema with triggers | Pydantic output, but fewer persisted trigger fields | Add trigger fields and rationale JSON to `ThreadScore` |
| Strategic filtering | Strong prompt framework | Basic relevance/quality/strategic scores | Convert strategy to typed `OpportunityAnalysis` service |
| Persona selection | LLM selects from named avatars/personas | `select_persona()` chooses avatar from active client avatars | Replace with deterministic candidate generation + weighted matcher + optional LLM tie-breaker |
| Persona/avatar separation | Conceptually present, operationally blurred | `personas` doc exists; `avatars` hold voice/worldview fields | Make Persona strategic, Avatar operational; map many-to-many |
| Worldview injection | Prompt-heavy and client-specific | Client worldview fields passed into prompts | Keep as strategy config, not hidden prompt magic |
| Engagement modes | `bullseye`, `helpful_peer`, `karma_only` | Same three modes on drafts | Add `monitor_only`, `escalation_required`, and pre-generation no-engage gates |
| Diversity | Ori has explicit previous-comment and opener/style checks | Previous comments passed to LLM; no persisted entropy | Build diversity engine from engagement history |
| Safety/governance | Mostly prompt/ops convention | Safety service, phase policy, limits, freeze, shadowban | Expand to sanctions, cooldowns, trust decay, quarantine, readiness gates |
| Auditability | Airtable history + ad hoc logs | `AuditLog`, `ActivityEvent`, `ai_usage_log`, `ScrapeLog` | Add `opportunity_matches` with full scoring breakdown/rejected alternatives |
| Review/publishing | Airtable review | HTMX review; no API posting | Keep human-in-the-loop; publishing disabled until checklist passes |
| Operational UI | Airtable flexible ops UI | Admin dashboard/templates | Keep SaaS UI; optionally use workflow tool only for non-critical ops experiments |
| Long-term scaling | Fragile at 100+ clients | Good base, but matching/risk schema incomplete | Backend services + queues + normalized governance tables |

## 1. Scraping Architecture Audit

### Comparison Diagram

```text
Ori
n8n cron/manual
  -> hardcoded subreddit list
  -> Reddit node per subreddit
  -> fixed wait nodes
  -> comment sub-workflow
  -> normalize/dedup in JS
  -> Supabase/Airtable rows
  -> LLM filter/generate workflow

ThreddOps current
Celery beat queue_tick
  -> DB shared subreddit registry
  -> stale-first selection
  -> Redis rate limiter
  -> distributed subreddit lock
  -> scrape_subreddit_shared
  -> global RedditThread insert
  -> per-client ThreadScore
  -> generation/review pipeline

Recommended target
Subreddit scheduler
  -> priority/freshness policy
  -> scrape worker pool
  -> normalized thread/comment/media store
  -> per-client opportunity analysis
  -> matching/risk governance
  -> human approval queue
```

### What Scales Well

- Shared subreddit registry is the right SaaS primitive. One scrape of `r/cybersecurity` can serve many clients.
- `ThreadScore` per client is the right split: shared ingestion, client-specific interpretation.
- Redis locks and sliding-window scrape limits are much better than n8n fixed waits.
- `ScrapeLog` and `ActivityEvent` give operational visibility that Ori lacked.

### What Breaks Under 100+ Clients

- Any remaining legacy client-centric scrape path duplicates work and should be retired.
- Global dedup loads all `reddit_native_id` values into memory in some paths; this becomes expensive with millions of threads.
- Freshness is currently mostly uniform; high-value subreddits need tighter windows, low-value subs need slower cadence.
- Hobby pipeline remains avatar-centric and can reintroduce duplicate scraping.
- Comment context is flattened text; long threads need structured, budgeted context selection.

### What Should Remain Subreddit-Centric

- Reddit read ingestion.
- Thread/comment/media normalization.
- Freshness/rate-limit scheduling.
- Duplicate prevention.
- Subreddit intelligence: rules, tone, sensitivity, common topics, ban patterns.

### What Should Move to Client-Specific Pipelines

- Opportunity scoring.
- ICP relevance.
- Strategic tiering.
- Persona/avatar matching.
- Draft generation and review queues.
- Client-specific forbidden topics and risk tolerance.

### Recommended Target Architecture

- `SubredditScheduler`: computes due subreddits using freshness, demand count, priority, error backoff, and rate budget.
- `ScrapeWorker`: read-only Reddit fetch, normalized posts/comments/media, idempotent inserts.
- `OpportunityAnalyzer`: per-client analysis on shared threads.
- `MatchingService`: ranks persona/avatar candidates and returns explainable assignment.
- `GovernanceService`: hard blocks risk, cooldown, sanctions, sensitivity, velocity, phase policy.
- `DraftService`: generates only after matching and governance pass.

## 2. AI Pipeline Architecture Audit

### Ori Pipeline Stages

Ori's effective chain is:

```text
qualification
  -> strategic filtering
  -> persona selection
  -> worldview/voice injection
  -> response generation
  -> refinement/naturalism checks
  -> Airtable review
```

The valuable product idea is the "Paradigm Shift -> Helpful -> Karma Play" ladder:

- `bullseye` / paradigm shift: engage when the thread naturally supports a strong strategic belief.
- `helpful_peer`: add practical value while softly carrying the worldview.
- `karma_only`: participate for account credibility, no client positioning.

### Layers That Improve Output Quality

- Explicit engagement mode before generation.
- Audience/thread-angle/pov-opportunity prep step.
- Anti-sales and anti-vendor language rules.
- Previous-comment diversity checks.
- Location selection: decide whether to reply to post or a specific comment.
- Naturalism refinement pass.

### Layers That Are Prompt Complexity Without Durable SaaS Value

- Hardcoded client/company context embedded inside workflow prompts.
- Hardcoded avatar username enum.
- Very long prompts as the only enforcement mechanism.
- Multiple LLM calls for choices that should be deterministic risk gates.
- Airtable-specific state transitions.

### Backend vs Workflow Ownership

| Stage | Owner | Reason |
|---|---|---|
| Ingestion normalization | Backend service | Idempotency, scale, testing |
| Qualification schema | Backend + LLM | Needs structured persistence |
| Strategic tiering | Backend service | Auditable and measurable |
| Persona/avatar matching | Backend service | Must enforce risk/cooldown/sanctions |
| Voice generation | LLM service | Creative language generation belongs here |
| Naturalism/refinement | LLM service + safety filters | Hybrid: generation plus deterministic blockers |
| Human approval | SaaS UI | Operational control and audit |

### Proposed Layered AI Pipeline for ThreddOps

```text
ThreadContextBuilder
  -> OpportunityAnalysis
  -> StrategyClassifier
  -> CandidateGeneration
  -> MatchScoring
  -> GovernanceGate
  -> DraftGeneration
  -> ContentSafety
  -> HumanReview
  -> ManualPublishTracking
```

Service boundaries:

- `opportunity_service.py`: intent, sentiment, technical depth, controversy, ICP fit.
- `strategy_service.py`: engagement mode, strategic theme, no-engage rationale.
- `matching_service.py`: persona/avatar ranking, confidence, rejected alternatives.
- `risk_service.py`: sanctions, cooldowns, trust, velocity, subreddit sensitivity.
- `diversity_service.py`: entropy penalties from recent history.
- `explainability_service.py`: persisted reasoning/audit payloads.

## 3. Persona & Avatar System Audit

### Recommended Entity Separation

Persona and avatar should be separate entities.

Persona represents strategic identity:

- worldview
- expertise
- tone
- communication style
- strategic beliefs
- claim boundaries
- subreddit affinity
- audience compatibility
- engagement mode fit

Avatar represents Reddit account state:

- username/account identity
- karma and account age
- subreddit history
- sanctions/cooldowns
- trust/risk score
- velocity
- health/shadowban/suspension state
- publishing readiness

### Normalized Entity Model

```text
clients
  1 -> many personas
  1 -> many strategic_themes
  1 -> many forbidden_topics

personas
  many -> many avatars via avatar_persona_map
  many -> many subreddits via persona_subreddit_affinity

avatars
  many -> many clients via avatar_client_map
  many -> many subreddits via avatar_subreddit_history
  1 -> many avatar_health_snapshots
  1 -> many sanctions
  1 -> many cooldowns
  1 -> many trust_score_events

reddit_threads
  1 -> many thread_scores
  1 -> many opportunity_matches

opportunity_matches
  belongs to client, thread, persona, avatar
  stores ranked candidates and scoring breakdown
```

### Recommended DB Relationships

- `personas.client_id -> clients.id`
- `avatar_client_map.avatar_id -> avatars.id`, `client_id -> clients.id`
- `avatar_persona_map.avatar_id -> avatars.id`, `persona_id -> personas.id`, with `fit_score`, `allowed_modes`, `is_active`
- `persona_subreddit_affinity.persona_id -> personas.id`, `subreddit_id -> subreddits.id`
- `avatar_subreddit_history.avatar_id -> avatars.id`, `subreddit_id -> subreddits.id`
- `opportunity_matches.thread_id/client_id/persona_id/avatar_id`

### Migration Proposal

1. Keep existing `avatars` rows as operational account records.
2. Create one initial persona per existing avatar using `voice_profile_md`, `hill_i_die_on`, `helpful_mode_topics`, `constraints`.
3. Populate `avatar_persona_map` 1:1 initially.
4. Move `business_subreddits` and `hobby_subreddits` into explicit affinity/history tables.
5. Replace `avatars.client_ids` array with `avatar_client_map`.
6. Update generation to consume `(persona, avatar)` rather than avatar-only voice blobs.

## 4. Strategic Layer

### SaaS-Level Strategic Abstractions

- `strategic_theme`: reusable belief or market-education point.
- `engagement_mode`: `bullseye`, `helpful_peer`, `karma_only`, `monitor_only`, `escalation_required`.
- `claim_boundary`: what persona may/may not claim.
- `forbidden_topic`: client-level and persona-level no-go areas.
- `positioning_risk`: how salesy/vendor-like the response would appear.
- `subreddit_sensitivity`: how risky a subreddit is for commercial-adjacent engagement.

### Client Configuration

- ICP profiles.
- Brand worldview.
- Competitors.
- Product/market positioning.
- Forbidden topics.
- Risk tolerance.
- Approval policy.

### Preventing AI Marketing Spam Patterns

- Default to `monitor_only` when relevance is weak, controversy is high, or subreddit sensitivity is high.
- Separate "strategic relevance" from "permission to engage".
- Enforce no brand mentions in early phases and sensitive subreddits.
- Penalize repeated strategic framing.
- Store explanations for why engagement is natural; if no natural anchor exists, do not draft.
- Require human approval for `bullseye` and all high-risk contexts.

## 5. Operational Architecture

### n8n vs Celery

n8n is useful for prototypes and non-critical operational automations. It should not own core SaaS workflows because it weakens version control, testing, observability, idempotency, and multi-client isolation.

Celery/backend services should own:

- scraping
- scoring
- matching
- risk gates
- generation
- audit/event persistence
- scheduled health checks

LLM workflow orchestration can exist as service-level code, not as visual workflow state.

### Workflow Ownership Matrix

| Workflow | Owner | Notes |
|---|---|---|
| Subreddit scrape scheduling | Celery + DB | Shared SaaS primitive |
| Reddit read ingestion | Scrape workers | Read-only, idempotent |
| Opportunity analysis | AI worker | Per-client |
| Matching | Backend service | Deterministic scoring first |
| Governance gates | Backend service | Hard-blocking |
| Draft generation | AI worker | Only after match/governance |
| Review and override | SaaS UI | Human-in-the-loop |
| Audit trail | Backend | Append-only event model |
| Experimental prompt testing | Optional workflow/notebook | Non-production only |

### Auditability Evolution

Add append-only events for:

- `opportunity_analyzed`
- `match_previewed`
- `match_assigned`
- `candidate_rejected`
- `risk_blocked`
- `cooldown_applied`
- `sanction_created`
- `manual_override_applied`
- `draft_generated`
- `draft_rejected_by_policy`

## 6. Reddit Survival / Anti-Detection Risk Review

This section is framed as platform-risk reduction for a human-reviewed content suggestion system. The safest current architectural fact is that ThreddOps does not auto-post to Reddit.

### Likely Causes of Ori Avatar Bans

- Repetitive AI writing patterns despite strong prompts.
- Too much professional/strategic engagement relative to ordinary participation.
- Avatar/account behavior not matching account age, karma, or subreddit history.
- Fixed or clustered timing.
- Weak subreddit-native fit.
- Overuse of the same worldview angle.
- Multiple personas/accounts operating around similar topics without enough entropy.

### Dangerous Operational Patterns

- Avatar-centric scraping and engagement loops.
- Publishing on high-sensitivity subreddits before account trust exists.
- Reusing the same opener, tone, structure, or strategic frame.
- Bullseye comments in hostile or high-controversy threads.
- New/low-karma accounts commenting on vendor-adjacent topics.
- Treating "LLM says engage" as sufficient permission to publish.

### Risk Matrix

| Risk | Probability | Impact | Required Control |
|---|---:|---:|---|
| New/weak avatar used in sensitive subreddit | High | High | Trust threshold + subreddit affinity gate |
| Repetitive tone/framing | High | High | Diversity entropy engine |
| Overposting in same subreddit | Medium | High | Subreddit cooldown + velocity throttle |
| Shadowban/suspension ignored | Medium | Critical | Health checks + quarantine |
| Strategic comment reads like vendor marketing | High | High | Anti-sales classifier + human approval |
| Same client over-targets same community | Medium | High | Client/subreddit exposure budget |
| Manual override bypasses risk | Medium | High | Override requires reason and audit |
| Auto-publishing introduced too early | Low now | Critical | Publishing readiness checklist |

### Mandatory Safeguards Before Publishing Is Enabled

- No automatic publishing by default.
- Match record must exist for every draft.
- Risk gate must pass before generation and again before approval.
- Active cooldowns and sanctions must hard-block.
- High-sensitivity subreddits require manual approval by a privileged operator.
- Shadowban/suspension suspicion quarantines avatar.
- Every override persists operator, reason, risk diff, and timestamp.
- Diversity entropy below threshold blocks or downgrades to `monitor_only`.

### Publishing Readiness Checklist

- `opportunity_matches` implemented with full explainability.
- Sanctions/cooldowns/trust tables implemented.
- Manual review UI shows risk factors and rejected candidates.
- Emergency global pause exists and is tested.
- Per-avatar and per-subreddit limits include jitter and cooldowns.
- Health checks run reliably and quarantine on status risk.
- Audit events are append-only and searchable.
- Human approval remains mandatory for professional comments.

## B. Critical Missing Systems

### P0

- Normalized persona/avatar separation with `avatar_persona_map`.
- Matching service with ranked candidates, confidence, rejected alternatives, and persisted explanations.
- Governance hard gates: sanctions, cooldowns, shadowban/suspension, risk threshold, subreddit sensitivity.
- `opportunity_matches` audit table.
- Engagement modes expanded to include `monitor_only` and `escalation_required`.

### P1

- Diversity entropy engine using engagement history.
- Explicit subreddit affinity/history tables.
- Trust score and trust decay.
- Client/subreddit exposure budgets.
- Trigger persistence in `ThreadScore`: competitor mentioned, company mentioned, buying signal, override applied.
- Admin UI for manual override with reason capture.

### P2

- Adaptive subreddit freshness.
- Comment context summarization/tree selection.
- Prompt/version experiment framework.
- Subreddit intelligence from rules/wiki/sidebar.
- Future real-time recommendation stream.

## C. Architecture Decision Recommendations

| Area | Decision | Rationale |
|---|---|---|
| Subreddit-centric scraping | KEEP | Correct scalable primitive; avoids duplicate ingestion |
| Avatar-centric ingestion | REJECT | Creates duplicate scraping and detectable behavior loops |
| n8n as core orchestration | REPLACE | Not durable for tested multi-client SaaS |
| n8n as ops/prototype tool | ADAPT | Useful for experiments outside core path |
| Airtable operational UI | REPLACE | Current SaaS UI and DB should own state |
| Ori strategic prep step | ADAPT | Keep mode/audience/thread-angle/pov, but persist typed results |
| Ori prompt naturalism rules | ADAPT | Useful, but enforce with services and audit rather than prompt only |
| Persona/avatar distinction | KEEP/ADAPT | Must become explicit relational model |
| Random avatar selection | REJECT | Too risky; use scored matching with entropy |
| LLM-only persona selection | REPLACE | Use deterministic scoring plus optional LLM tie-breaker |
| Current safety service | KEEP/ADAPT | Good base; needs sanctions/cooldowns/trust |
| Human review | KEEP | Essential for Reddit safety and compliance posture |
| Automatic publishing | REJECT for now | Platform risk too high without mature governance |

## D. Final Recommendation

### 1. What ThreddOps Should Borrow From Ori

- The strategic engagement ladder: `bullseye -> helpful_peer -> karma_only`.
- The prep-step idea: audience, thread angle, POV opportunity, natural reply location.
- Anti-sales/anti-vendor naturalism rules.
- Diversity checks against previous comments.
- Session sampling concept for organic cadence.
- Rich qualification triggers and override reasons.

### 2. What ThreddOps Should Avoid

- n8n as the production orchestration layer.
- Airtable/Supabase split-brain state.
- Hardcoded client, subreddit, and avatar lists.
- Prompt-only governance.
- Avatar-centric scraping.
- Publishing before governance/audit/matching are complete.

### 3. Strategic Moat

The moat is not clever prompts. The moat is reputation orchestration:

- subreddit-native opportunity intelligence
- explainable persona/avatar routing
- account health and trust governance
- diversity entropy and behavior pacing
- human-in-the-loop auditability
- multi-client isolation on shared ingestion

### 4. Long-Term SaaS Scaling Architecture

Backend-first, event-driven, subreddit-centric:

```text
shared subreddit ingestion
  -> per-client opportunity analysis
  -> explainable persona/avatar matching
  -> governance/risk gate
  -> draft generation
  -> human review
  -> audit/event feedback loop
```

### 5. Architecture That Minimizes Reddit Platform Risk

- Read-only Reddit API usage for ingestion.
- Human approval for publishing.
- No avatar-centric scraping.
- Explicit cooldowns, sanctions, trust thresholds, and subreddit sensitivity.
- Persona/avatar separation so a strategic identity never overrides account health.
- Append-only evidence for every engagement decision.

# Task 2: Backend Matching Layer Specification

## Objective

Build a scalable matching system that selects the most appropriate `(persona, avatar)` pair for Reddit engagement opportunities. The matching layer should act as a reputation orchestration engine, subreddit-native persona router, and survivability layer.

Canonical flow:

```text
subreddit -> threads/comments -> opportunity analysis -> persona/avatar matching -> governance gate -> draft generation
```

## 1. Services and Ownership Boundaries

### Proposed Services

- `OpportunityAnalysisService`
  - Inputs: thread, client, thread score, subreddit metadata.
  - Outputs: topic, intent, sentiment, technical depth, controversy, strategic relevance, recommended mode.

- `CandidateGenerationService`
  - Inputs: client, subreddit, opportunity.
  - Outputs: eligible personas and avatars before scoring.
  - Hard filters: active client mapping, active persona, non-frozen avatar, not shadowbanned, not quarantined.

- `MatchingService`
  - Inputs: opportunity, client context, persona candidates, avatar candidates.
  - Outputs: ranked candidates, confidence, selected assignment, scoring breakdown.

- `RiskGovernanceService`
  - Inputs: selected candidate and opportunity.
  - Outputs: allow/block/requires approval, risk factors, cooldowns.

- `DiversityService`
  - Inputs: recent engagement history for avatar/persona/client/subreddit.
  - Outputs: entropy penalties and repeated-pattern warnings.

- `ExplainabilityService`
  - Persists selection rationale, rejected candidates, risk factors, and score breakdown into `opportunity_matches` and events.

### Queues

- `scrape`: shared subreddit ingestion.
- `analysis`: per-client scoring/opportunity analysis.
- `matching`: candidate ranking and preview creation.
- `generation`: draft generation after governance pass.
- `health`: avatar health, trust decay, sanctions.
- `audit`: async event enrichment/export.

## 2. Database Design

### ERD

```text
clients
  |-- personas
  |-- avatar_client_map -- avatars
  |-- client_subreddit_assignments -- subreddits

personas
  |-- avatar_persona_map -- avatars
  |-- persona_subreddit_affinity -- subreddits

avatars
  |-- avatar_health_snapshots
  |-- avatar_subreddit_history -- subreddits
  |-- avatar_sanctions
  |-- avatar_cooldowns
  |-- avatar_trust_scores
  |-- engagement_history

reddit_threads
  |-- thread_scores
  |-- opportunity_matches

opportunity_matches
  |-- selected persona
  |-- selected avatar
  |-- scoring JSON
  |-- rejected candidates JSON
  |-- governance JSON
```

### Tables

#### `personas`

Existing table should be expanded:

- `id`
- `client_id`
- `persona_name`
- `archetype`
- `worldview`
- `expertise_tags jsonb`
- `tone_profile jsonb`
- `claim_boundaries text`
- `allowed_modes text[]`
- `risk_tolerance`
- `is_active`
- `created_at`, `updated_at`

#### `avatar_client_map`

- `id`
- `avatar_id`
- `client_id`
- `is_active`
- `assignment_notes`
- unique `(avatar_id, client_id)`

#### `avatar_persona_map`

- `id`
- `avatar_id`
- `persona_id`
- `fit_score numeric`
- `allowed_modes text[]`
- `is_default bool`
- `is_active bool`
- `created_at`
- unique `(avatar_id, persona_id)`

#### `persona_subreddit_affinity`

- `id`
- `persona_id`
- `subreddit_id`
- `affinity_score numeric`
- `expertise_fit numeric`
- `tone_fit numeric`
- `allowed_modes text[]`
- `notes text`
- unique `(persona_id, subreddit_id)`

#### `avatar_subreddit_history`

- `id`
- `avatar_id`
- `subreddit_id`
- `comment_karma`
- `post_karma`
- `comments_count_30d`
- `last_engaged_at`
- `last_positive_engagement_at`
- `ban_state`
- `native_fit_score`
- unique `(avatar_id, subreddit_id)`

#### `avatar_health_snapshots`

- `id`
- `avatar_id`
- `reddit_status`
- `karma_comment`
- `karma_post`
- `account_age_days`
- `shadowban_suspected`
- `trust_score`
- `risk_score`
- `checked_at`

#### `avatar_sanctions`

- `id`
- `avatar_id`
- `subreddit_id nullable`
- `client_id nullable`
- `severity`
- `type`
- `reason`
- `starts_at`
- `ends_at nullable`
- `is_active`
- `created_by`
- `created_at`

#### `avatar_cooldowns`

- `id`
- `avatar_id`
- `subreddit_id nullable`
- `client_id nullable`
- `cooldown_type`
- `reason`
- `starts_at`
- `ends_at`
- `created_at`

#### `avatar_trust_scores`

- `id`
- `avatar_id`
- `subreddit_id nullable`
- `score`
- `delta`
- `reason`
- `source_event_id nullable`
- `created_at`

#### `engagement_history`

- `id`
- `client_id`
- `thread_id`
- `subreddit_id`
- `avatar_id`
- `persona_id`
- `engagement_mode`
- `tone_signature`
- `strategy_theme_id nullable`
- `status`
- `created_at`
- `approved_at nullable`
- `posted_at nullable`

#### `opportunity_matches`

- `id`
- `client_id`
- `thread_id`
- `thread_score_id nullable`
- `selected_persona_id nullable`
- `selected_avatar_id nullable`
- `engagement_mode`
- `decision_status`: `selected | blocked | monitor_only | escalation_required | overridden`
- `confidence numeric`
- `total_score numeric`
- `score_breakdown jsonb`
- `candidate_rankings jsonb`
- `rejected_candidates jsonb`
- `risk_factors jsonb`
- `governance_decision jsonb`
- `strategic_rationale text`
- `created_by nullable`
- `created_at`

### Indexing Strategy

- `avatar_persona_map(persona_id, is_active)`
- `avatar_persona_map(avatar_id, is_active)`
- `avatar_client_map(client_id, is_active)`
- `persona_subreddit_affinity(subreddit_id, affinity_score desc)`
- `avatar_subreddit_history(avatar_id, subreddit_id)`
- `avatar_sanctions(avatar_id, is_active, ends_at)`
- `avatar_cooldowns(avatar_id, ends_at)`
- `engagement_history(avatar_id, created_at desc)`
- `engagement_history(subreddit_id, created_at desc)`
- `opportunity_matches(client_id, created_at desc)`
- `opportunity_matches(thread_id, client_id)`

## 3. Match Algorithm

### Weighted Scoring Model

Default weights:

| Factor | Weight | Meaning |
|---|---:|---|
| Persona expertise fit | 0.18 | Persona knows the topic |
| Persona subreddit affinity | 0.14 | Persona fits community norms |
| Persona worldview compatibility | 0.12 | Strategic theme fits naturally |
| Persona tone compatibility | 0.08 | Tone fits emotional/technical context |
| Avatar subreddit history | 0.14 | Account has credible local history |
| Avatar trust score | 0.12 | Account health and reputation |
| Avatar risk inverse | 0.12 | Lower risk is better |
| Cooldown/velocity penalty | -0.10 | Prevent overuse |
| Diversity entropy penalty | -0.10 | Avoid repeated patterns |
| Client risk tolerance fit | 0.08 | Candidate fits allowed risk |

Hard blockers are applied before scoring:

- avatar inactive/frozen
- shadowban/suspension suspected
- active sanction
- active cooldown
- account trust below threshold
- subreddit sensitivity above allowed threshold
- persona claim boundary conflict
- client forbidden topic conflict

### Pseudocode

```python
def match_opportunity(db, client_id, thread_id, preview=True):
    opportunity = analyze_opportunity(db, client_id, thread_id)

    if opportunity.recommended_mode in ["monitor_only", "escalation_required"]:
        return persist_match(status=opportunity.recommended_mode, confidence=1.0)

    personas = candidate_personas(db, client_id, opportunity)
    avatars = candidate_avatars(db, client_id, opportunity.subreddit_id)

    candidates = []
    rejected = []

    for persona in personas:
        for avatar in avatars_for_persona(avatars, persona):
            hard_block = governance_hard_block(db, avatar, persona, opportunity)
            if hard_block:
                rejected.append(rejection(avatar, persona, hard_block))
                continue

            factors = {
                "expertise_fit": score_expertise(persona, opportunity),
                "persona_subreddit_affinity": score_persona_subreddit(persona, opportunity),
                "worldview_fit": score_worldview(persona, client_id, opportunity),
                "tone_fit": score_tone(persona, opportunity),
                "avatar_subreddit_history": score_avatar_history(avatar, opportunity),
                "trust_score": normalized_trust(avatar),
                "risk_inverse": 1 - normalized_risk(avatar, opportunity),
                "cooldown_penalty": cooldown_penalty(db, avatar, opportunity),
                "diversity_penalty": diversity_penalty(db, avatar, persona, opportunity),
                "client_risk_fit": score_client_risk(client_id, opportunity),
            }

            total = weighted_sum(factors)
            candidates.append(candidate(avatar, persona, total, factors))

    ranked = sorted(candidates, key=lambda c: c.total, reverse=True)

    if not ranked:
        return persist_match(
            status="blocked",
            rejected_candidates=rejected,
            governance_decision={"reason": "no_eligible_candidates"},
        )

    winner = ranked[0]
    confidence = compute_confidence(winner, ranked[1:] if len(ranked) > 1 else [])

    if winner.total < MIN_MATCH_SCORE:
        return persist_match(status="monitor_only", ranked=ranked, rejected=rejected)

    if opportunity.risk_level >= HIGH_RISK_THRESHOLD:
        status = "escalation_required"
    else:
        status = "selected"

    return persist_match(
        status=status,
        selected_avatar=winner.avatar,
        selected_persona=winner.persona,
        confidence=confidence,
        score_breakdown=winner.factors,
        candidate_rankings=ranked,
        rejected_candidates=rejected,
    )
```

### Extensibility Plan

- MVP: deterministic weighted scoring from relational fields.
- Production-safe: add diversity entropy, sanctions, trust decay, manual override learning.
- Advanced: train/reweight factors using approval, rejection, engagement, and health outcomes.

## 4. Engagement Modes

Supported modes:

- `bullseye`: high strategic fit, high confidence, low/moderate subreddit risk, strong persona credibility.
- `helpful_peer`: practical answer with light worldview; default professional mode.
- `karma_only`: non-client, reputation-building engagement.
- `monitor_only`: relevant but not safe or not worth engagement.
- `escalation_required`: needs senior human review before drafting.

Mode decision rules:

- High controversy + low trust = `monitor_only`.
- Direct competitor/company mention + high risk = `escalation_required`.
- Weak strategic anchor = `helpful_peer` or `karma_only`, not `bullseye`.
- Any active hard block = no draft.

## 5. Governance Layer

### Sanctions

Sanctions can apply to avatar globally, avatar in subreddit, avatar for client, or persona/avatar pairing.

Types:

- `manual_freeze`
- `shadowban_suspicion`
- `subreddit_warning`
- `velocity_violation`
- `content_policy_violation`
- `operator_review_required`

### Throttling

Throttle dimensions:

- avatar/day
- avatar/subreddit/day
- client/subreddit/day
- persona/day
- engagement mode/day
- strategic theme/week

### Trust Decay

Trust should decay when:

- health checks are stale
- engagement is rejected repeatedly
- cooldowns are triggered
- subreddit sensitivity increases
- avatar has no recent native activity

Trust should recover slowly from:

- healthy status checks
- approved karma-only/helpful peer engagement
- long quiet periods after sanction

### Quarantine

Quarantine should hard-block matching and generation. Triggers:

- shadowban/suspension suspicion
- active severe sanction
- repeated policy violations
- manual operator action
- anomalous karma/status mismatch

## 6. API Design

### Candidate Generation

`POST /api/matching/candidates`

Request:

```json
{
  "client_id": "uuid",
  "thread_id": "uuid",
  "engagement_mode": "helpful_peer"
}
```

Response:

```json
{
  "personas": [],
  "avatars": [],
  "hard_blocks": []
}
```

### Match Scoring

`POST /api/matching/score`

Request:

```json
{
  "client_id": "uuid",
  "thread_id": "uuid",
  "preview": true
}
```

Response:

```json
{
  "match_id": "uuid",
  "decision_status": "selected",
  "selected": {
    "persona_id": "uuid",
    "avatar_id": "uuid"
  },
  "confidence": 0.82,
  "ranked_candidates": [],
  "rejected_candidates": [],
  "risk_factors": [],
  "score_breakdown": {}
}
```

### Assignment Preview

`GET /api/matching/{match_id}`

Returns persisted explanation, rankings, risk factors, and governance result.

### Manual Override

`POST /api/matching/{match_id}/override`

Request:

```json
{
  "persona_id": "uuid",
  "avatar_id": "uuid",
  "reason": "Operator knows this avatar has authentic history in r/devops."
}
```

Rules:

- Cannot override severe sanctions, quarantine, or shadowban suspicion.
- Must persist override reason and operator id.

### Sanctions

- `POST /api/avatars/{avatar_id}/sanctions`
- `GET /api/avatars/{avatar_id}/sanctions`
- `POST /api/sanctions/{sanction_id}/resolve`

### Avatar Health

- `GET /api/avatars/{avatar_id}/health`
- `POST /api/avatars/{avatar_id}/health/check`
- `GET /api/avatars/health/at-risk`

## 7. Event Flows

### Normal Flow

```text
thread scored engage
  -> opportunity_analyzed
  -> match_previewed
  -> governance_passed
  -> match_assigned
  -> draft_generated
  -> human_review_pending
```

### Blocked Flow

```text
thread scored engage
  -> opportunity_analyzed
  -> candidate_rejected events
  -> risk_blocked
  -> match status blocked/monitor_only
  -> no draft generated
```

### Override Flow

```text
match_previewed
  -> operator_override_requested
  -> governance_recheck
  -> override_applied or override_denied
  -> audit log persisted
```

## 8. Rollout Plan

### Phase 1: MVP

- Add normalized tables: `avatar_client_map`, `avatar_persona_map`, `persona_subreddit_affinity`, `avatar_subreddit_history`, `opportunity_matches`.
- Implement deterministic matching service.
- Persist ranked candidates, selected candidate, rejected alternatives, and score breakdown.
- Add `monitor_only` and `escalation_required`.
- Integrate matching before `generate_comment()`.

### Phase 2: Production-Safe

- Add sanctions, cooldowns, trust score, and health snapshots.
- Add diversity entropy from `engagement_history`.
- Add admin preview/override UI.
- Add audit events for all matching/risk decisions.
- Add hard blocks before both draft generation and approval.

### Phase 3: Advanced Intelligence

- Adaptive weights per client/subreddit.
- Subreddit rules/sensitivity intelligence.
- Feedback loop from approval/rejection/post status.
- Real-time recommendation queue.
- Experiment framework for strategy and prompt variants.

## Implementation Notes for Backend Developer

- Do not add any avatar-centric scraping path.
- Matching should consume already-ingested shared subreddit/thread data.
- LLMs may assist opportunity analysis, but risk gates and eligibility must be deterministic.
- Every match decision must be explainable from persisted data.
- No publishing automation should be introduced as part of this work.
- Start with simple SQLAlchemy services and Pydantic contracts; avoid complex ML infrastructure until enough outcomes exist.
