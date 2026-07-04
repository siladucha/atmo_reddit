# Multiple ICPs (Ideal Customer Profiles)

## Problem Statement

Currently the onboarding wizard collects ONE ICP (Step 3). Many B2B clients have multiple audience segments. Tzvi's feedback (June 26): "Some clients have more than 1 ICP. I suggest adding a button ('Add ICP') which leads to the same questions for another audience segment + define if it's a primary or adjacent ICP."

## Requirements

### FR-1: Multiple ICP Collection in Onboarding

1. THE Step 3 (ICP/Buyer) of onboarding SHALL support 1-5 ICPs
2. EACH ICP SHALL have:
   - `role_title`: String — "CISO", "DevOps Lead", "VP Engineering"
   - `seniority`: String — "C-level", "Director", "Manager", "IC", "Student"
   - `pain_points`: Text — what keeps them up at night
   - `where_they_hang_out`: Text — subreddits, communities, publications
   - `priority`: Enum — "primary" | "adjacent"
3. THE first ICP SHALL be required. Additional ICPs optional.
4. UI: "Add Another ICP" button below the first ICP form. Each additional ICP = collapsible card.
5. THE primary ICP SHALL influence subreddit/keyword suggestions more heavily than adjacent ICPs.

### FR-2: ICP Data Model

1. A new model `ClientICP` SHALL be created:
   - `id`: UUID PK
   - `client_id`: FK to clients
   - `role_title`: String(200)
   - `seniority`: String(50)
   - `pain_points`: Text
   - `communities`: Text (free-form, will be parsed for subreddit suggestions)
   - `priority`: String(20) — "primary" | "adjacent"
   - `order`: Integer (display order)
   - `created_at`: DateTime
2. THE existing `client.strategy_context` JSONB SHALL reference ICP IDs (not duplicate text)
3. MIGRATION: existing onboarding data (single ICP in strategy_context) → migrate to ClientICP record

### FR-3: ICP Influences Pipeline

1. WHEN generating subreddit suggestions (Step 4), THE system SHALL consider ALL ICPs:
   - Primary ICP → direct subreddit matches (high priority)
   - Adjacent ICPs → complementary subreddits (medium priority)
2. WHEN generating strategy documents, ALL ICPs SHALL be included in the strategy prompt
3. WHEN scoring threads, THE scoring prompt SHALL reference the primary ICP's pain points
4. THE EPG opportunity scoring `strategic_alignment` dimension SHALL factor in ICP relevance

### FR-4: ICP Management Post-Onboarding

1. THE Client Portal Settings SHALL include an "Audience" or "ICPs" section
2. CLIENTS with role `client_admin` or `client_manager` SHALL be able to:
   - Add new ICPs
   - Edit existing ICPs
   - Reorder ICPs
   - Change primary/adjacent designation
   - Delete ICPs (minimum 1 must remain)
3. THE Admin panel SHALL show ICPs on client detail page

## Non-Functional Requirements

### NFR-1: Backward Compatible
- Clients with existing single-ICP data continue working
- Migration creates one ClientICP record from existing strategy_context ICP data
- Null/empty ICPs = system works as before (uses keywords + subreddits without ICP context)

### NFR-2: Prompt Size
- ICP descriptions feed into LLM prompts — max 500 chars per ICP in prompt context
- With 5 ICPs → 2500 chars additional context (acceptable for Claude/Gemini)

## Out of Scope

- ICP-based avatar assignment (which avatar speaks to which ICP)
- ICP-based draft routing (showing drafts grouped by target ICP)
- ICP analytics (which ICP gets most engagement)

## Dependencies

- Onboarding wizard Step 3 (exists)
- Strategy generation service (exists, needs prompt update)
- Scoring prompts (exist, need ICP injection)
- Alembic migration for new `client_icps` table

## Success Criteria

1. Client can add 3 ICPs during onboarding (primary + 2 adjacent)
2. Subreddit suggestions reflect all ICPs (not just first one)
3. Strategy document mentions all audience segments
4. Existing single-ICP clients unaffected
