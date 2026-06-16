# Client Manager Portal Actions — Requirements

## Introduction

Extend the Client Portal to give `client_manager` role the ability to trigger pipeline operations (discovery, strategy generation, EPG rebuild, full pipeline, draft regeneration) with rate limiting. Currently these operations are admin-only. This unlocks self-service for managed clients paying $2K+/mo.

## Requirements

### Requirement 1: Rate-Limited Pipeline Trigger

**User Story:** As a client_manager, I want to manually trigger a full pipeline run (scrape → score → generate) for my company, so I can get fresh content without waiting for the scheduled run.

**Acceptance Criteria:**
1. Client_manager can trigger full pipeline from the portal (button on Home or EPG page)
2. Rate limited to max 2 manual runs per day per client (cooldown enforced server-side)
3. UI shows next available run time when limit is reached
4. Audit log captures who triggered and when
5. Returns task status (queued/rejected with reason)

### Requirement 2: EPG Rebuild Trigger

**User Story:** As a client_manager, I want to rebuild today's EPG for my avatars, so I can refresh the publishing schedule after changes.

**Acceptance Criteria:**
1. Client_manager can trigger EPG rebuild from the EPG page
2. Rate limited to 1 rebuild per day per client
3. Only rebuilds EPG for avatars belonging to that client
4. Shows progress/status feedback via toast notification

### Requirement 3: Discovery Session Management

**User Story:** As a client_manager, I want to create and manage discovery sessions for my company, so I can research new subreddits and topics.

**Acceptance Criteria:**
1. Client_manager can create new discovery sessions from portal
2. Can confirm entities, trigger research, decide hypotheses, generate report
3. Sessions are scoped to own client only
4. Rate limited to 1 active session at a time, max 2 new sessions per week

### Requirement 4: Strategy Generation Trigger

**User Story:** As a client_manager, I want to regenerate strategy documents for my avatars, so I can update the AI approach based on new insights.

**Acceptance Criteria:**
1. Client_manager can trigger strategy generation per avatar from Strategy page
2. Rate limited to 1 strategy generation per avatar per week
3. Shows current vs. previous strategy version

### Requirement 5: Individual Draft Regeneration

**User Story:** As a client_manager, I want to regenerate a single comment draft, so I can get a fresh AI attempt without running the full pipeline.

**Acceptance Criteria:**
1. Client_manager can click "Regenerate" on any pending draft in review queue
2. No daily limit (single LLM call, ~$0.04)
3. Old draft is marked "regenerated", new draft created
4. Learning context (edit patterns) injected into regeneration

### Requirement 6: Rate Limit Tracking Model

**User Story:** As a platform operator, I want all client-triggered actions rate-limited and audited, so I can control LLM costs.

**Acceptance Criteria:**
1. `ClientActionLog` model tracks: client_id, action_type, triggered_by, triggered_at
2. Rate limits enforced server-side before task dispatch
3. Limits configurable via system settings (default: pipeline=2/day, epg=1/day, strategy=1/week/avatar, discovery=2/week)
4. HTTP 429 returned with retry_after when limit exceeded
