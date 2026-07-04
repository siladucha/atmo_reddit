# Health Check Rewrite — Multi-Signal Consensus

## Problem Statement

The current shadowban detection system uses single-probe decision making. One positive signal from `check_submission_visibility()` immediately marks an avatar as shadowbanned and freezes it. This has caused:

1. **False positive for connor_lloyd** (June 2026): submission probe checked a post >24h old, naturally absent from top-100 new → "shadowban" → frozen
2. **False positive cascade during outage** (June 2026): workers died → no new content → all submissions age → probe finds only old posts → false shadowban for healthy avatars
3. **System punishing avatars for its own failures**: worker death → stale posts → false detection → freeze → compounding the outage

The fundamental flaw: **a single unreliable signal triggers an irreversible state change** (freeze). No confirmation, no quorum, no cooldown.

## Requirements

### FR-1: Multi-Signal Decision Model

1. WHEN performing a health check, THE system SHALL collect multiple independent signals before changing health_status
2. THE system SHALL require at least 2 out of 3 signals to agree before marking an avatar as shadowbanned
3. THE available signals SHALL be:
   - **Signal A: Comment Visibility** — ratio of visible comments (existing check, reliable when sample ≥ 5)
   - **Signal B: Submission Visibility** — post visible in subreddit feed (only valid for posts < 24h old)
   - **Signal C: Karma Accumulation** — whether posted comments are receiving any karma (new signal)
4. IF fewer than 2 signals are available (e.g., no recent submission, insufficient comments), THE system SHALL return `inconclusive` and retain previous status
5. THE system SHALL NOT change health_status based on a single signal alone, except for SUSPENDED (404/403 = definitive)

### FR-2: Signal Confidence Scoring

1. EACH signal SHALL have a confidence score (0.0 - 1.0) based on data quality:
   - Comment visibility: confidence = min(1.0, comments_sampled / 10). Below 5 samples = low confidence.
   - Submission visibility: confidence = 1.0 if post < 6h old, 0.7 if < 12h, 0.3 if < 24h, 0.0 if > 24h
   - Karma accumulation: confidence = min(1.0, posts_with_karma_data / 5)
2. THE consensus decision SHALL weight signals by confidence:
   - `weighted_shadowban_score = sum(signal_positive × confidence) / sum(confidence)`
   - If weighted_score > 0.6 → shadowbanned
   - If weighted_score < 0.3 → active
   - Otherwise → retain previous status (inconclusive)

### FR-3: State Transition Cooldown

1. WHEN health_status changes from `active` to `shadowbanned`, THE system SHALL require the new status to persist across 2 consecutive health checks (minimum 4h apart) before triggering freeze
2. THE system SHALL introduce a `shadowban_candidate` intermediate state:
   - First detection → `shadowban_candidate` (no freeze, continue monitoring at 4h interval)
   - Second consecutive detection (≥4h later) → `shadowbanned` (freeze + notify)
   - If second check returns `active` or `inconclusive` → revert to `active`
3. THIS cooldown SHALL NOT apply to SUSPENDED (immediate — account is definitely dead)

### FR-4: Self-Healing Awareness

1. WHEN the system detects that no scraping has occurred in >12h (pipeline dead), THE health check SHALL annotate results with `pipeline_context: degraded`
2. WHEN `pipeline_context: degraded`, THE system SHALL:
   - Increase submission age tolerance to 72h (posts may be old because pipeline stopped, not because shadowban)
   - Reduce confidence of submission probe to 0.1 (unreliable during outage)
   - Log: "Health check running in degraded pipeline context — reduced confidence"
3. THIS prevents the "system punishes avatars for its own failure" cascade

### FR-5: Existing Behavior Preserved

1. THE `check_profile_accessibility()` check SHALL remain unchanged (404/403 = SUSPENDED, immediate)
2. THE `external_shadowban_checker` integration SHALL remain unchanged (if configured, overrides)
3. THE `zero_content_with_history` detection SHALL be deprecated in favor of multi-signal consensus
4. THE auto-freeze on shadowban SHALL be gated by the cooldown (FR-3), not immediate
5. ALL existing activity events (global_shadowban_detected, etc.) SHALL continue to be emitted

### FR-6: Observability

1. EACH health check SHALL log the individual signal results, confidence scores, and consensus decision
2. THE admin avatar detail page SHALL show the last 5 health check results with signal breakdown
3. THE health_check_details JSONB field SHALL store: signals array (name, result, confidence), consensus_score, decision, pipeline_context

## Non-Functional Requirements

### NFR-1: Performance
- Multi-signal check must complete within 60s per avatar (current timeout)
- No additional Reddit API calls beyond what's already made (reuse existing data)
- Karma accumulation signal uses data already in karma_snapshots table (no API call)

### NFR-2: Backward Compatibility
- Existing health_status values unchanged (unknown, active, limited, shadowbanned, suspended)
- New `shadowban_candidate` state is internal (not exposed to UI as separate status)
- Avatars currently marked as shadowbanned should be re-evaluated on next health check

### NFR-3: Testing
- Unit tests for consensus logic with various signal combinations
- Integration test: simulate "all probes old" → must return inconclusive, not shadowban
- Regression test: simulate connor_lloyd case (old submission + 0 comments sampled)

## Out of Scope

- Browser extension health signals (separate spec)
- Per-subreddit ban detection (Layer 2 — unchanged)
- CQS integration with health (separate concern)
- External shadowban checker API changes

## Dependencies

- `karma_snapshots` table (already exists) — for Signal C
- `health_check_details` JSONB field on Avatar (already exists)
- No new migrations required (uses existing fields)

## Success Criteria

1. connor_lloyd scenario (old submission, 0 comments sampled) → returns `inconclusive`, NOT `shadowbanned`
2. Actual shadowban (0/10 comments visible + invisible submission < 6h) → detected within 2 checks (8h)
3. During pipeline outage (no scrapes 12h+) → no false positives triggered
4. False positive rate drops from ~20% (estimated) to <2%
