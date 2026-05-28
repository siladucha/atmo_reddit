# Requirements Document

## Introduction

Evolution of avatar warming from karma farming to building AI-Native Experts — topical authorities whose content maximizes probability of being indexed and cited by external LLMs (OpenAI, Gemini, Perplexity) as grounding sources.

Current system (Phase 1-3) focuses on karma accumulation and brand safety. This spec augments existing phases with quality dimensions: topic coherence, content structure, engagement quality, and entity linking.

Builds on: self-learning loop, approach diversity, presence tracking, karma tracking, strategy documents, EPG.

## Measurement Constraint

Direct "AI citation" measurement is NOT possible — no public API exists to check whether ChatGPT/Perplexity cited a specific Reddit comment.

**What we CAN measure (proxy signals):**
- Topic coherence — embedding similarity within semantic cluster (local computation)
- Citability score — content structure quality (local computation)
- Engagement quality — upvote-to-char ratio, thread depth, saves (Reddit API)
- Posting consistency — regular niche output over months (our DB)
- Removal rate — content stays indexed (Reddit API)
- Cross-references — other users quoting the avatar (Reddit API, partial)

**What we CANNOT measure:**
- Actual citation by external LLMs
- Embedding weight in external systems
- Citation count in AI-generated answers

**Validation:** Periodic manual spot-checks (query Perplexity/ChatGPT with niche questions, log results). Qualitative, not automated.

## Glossary

| Term | Definition |
|------|-----------|
| AI-Native Expert | Avatar with coherent topical authority optimized for external LLM citation |
| Semantic Cluster | Narrow topic niche (e.g. "Kubernetes security in fintech") with LSI keywords, entities, jargon |
| Niche Profile | Per-avatar config: semantic cluster, LSI keywords, named entities, content archetypes |
| Authority Score | Composite metric (0-100) from topic coherence + citability + engagement quality + consistency |
| Citability Score | Per-comment metric: structure quality, data density, experience markers, absence of AI-tells |
| Content Archetype | Structured format optimized for citation: case study, comparison, framework, troubleshooting, benchmark |
| Tier-2 Trust Signal | Quality engagement: upvote-to-char ratio, thread depth provoked, saves, cross-references |
| Entity Linking | Naturally associating client brand with problem-solution patterns in content |
| Topic Coherence Score | How tightly avatar's content clusters in embedding space (cosine similarity to centroid) |
| LSI Keywords | Semantically related terms signaling topical depth to embedding models |
| Named Entities | Specific proper nouns (tools, frameworks, standards) anchoring content in knowledge graphs |

## Requirements

### Requirement 1: Niche Profile Configuration

**User Story:** As a platform operator, I want to define a precise semantic cluster for each avatar, so that all generated content builds coherent topical authority.

#### Acceptance Criteria

1. THE system SHALL store a `NicheProfile` per avatar: `avatar_id`, `niche_label`, `semantic_cluster` (text description), `lsi_keywords` (JSONB, 20-50 terms), `named_entities` (JSONB, 10-30 entities), `forbidden_topics` (JSONB), `content_archetypes` (JSONB, enabled types), `phase_strategy` (JSONB, per-phase content constraints), `authority_target_score` (int 0-100), `created_at`, `updated_at`.
2. WHEN creating/editing a NicheProfile, THE system SHALL validate: min 15 LSI keywords, min 8 named entities.
3. THE system SHALL provide LLM-assisted niche profile generation: given client brand + product + audience → generate recommended NicheProfile.
4. WHEN saved, THE system SHALL compute `topic_coherence_baseline` by embedding LSI keywords and measuring cluster tightness.
5. Each avatar has exactly one active NicheProfile. Changing niche resets Authority Score to 0.
6. `phase_strategy` maps phases to content constraints: Phase 1 = hobby-adjacent niche only, Phase 2 = professional niche + external citations, Phase 3 = niche + entity linking.

---

### Requirement 2: Topic Coherence Enforcement

**User Story:** As a platform operator, I want generated content to stay within the avatar's semantic cluster, building focused authority rather than diluting the profile.

#### Acceptance Criteria

1. Generation pipeline SHALL inject NicheProfile (LSI keywords, named entities, forbidden topics) into LLM prompt as mandatory constraint.
2. Prompt SHALL instruct LLM to incorporate 2-4 LSI keywords and 1-2 named entities per comment naturally.
3. After generation, system SHALL compute `topic_coherence_score` (0-100) via embedding cosine similarity to cluster centroid.
4. IF `topic_coherence_score` < configurable threshold (default 60), flag for review as "off-topic for niche", optionally regenerate.
5. Scoring pipeline SHALL include `niche_relevance` factor (0-1) based on keyword/entity overlap with NicheProfile.
6. `topic_coherence_score` stored on CommentDraft, visible in review UI.
7. Avatar SHALL NOT be assigned to threads outside its semantic cluster, even if thread scores high on client keywords.

---

### Requirement 3: Citable Content Generation

**User Story:** As a platform operator, I want generated content to follow patterns that AI search engines prefer to index, maximizing citation probability.

#### Acceptance Criteria

1. System SHALL define 5 content archetypes:
   - `micro_case_study` — "In my experience deploying X for Y users..." + metrics + outcome
   - `comparison_matrix` — structured A vs B with criteria and verdict
   - `decision_framework` — "When choosing between X and Y, consider 3 factors..."
   - `troubleshooting_guide` — problem → diagnosis → solution → verification
   - `benchmark_report` — "We tested X under Y conditions, results: ..." + data
2. Generation SHALL select archetype from avatar's enabled set and follow its structure.
3. Prompt SHALL enforce first-hand data patterns: "In my tests...", "We deployed...", "After 6 months of using...", "Our team switched from X to Y because...".
4. Prompt SHALL enforce structured formatting: numbered lists, comparisons, specific numbers. Forbid wall-of-text.
5. Prompt SHALL include anti-AI-detection blocklist: "In conclusion", "It's worth noting", "Delve", "Crucial", "Landscape", "Leverage", "Robust", "Seamless", "Cutting-edge", "Game-changer".
6. System SHALL compute `citability_score` (0-100): structured data presence + experience markers + no AI-tells + information density.
7. `citability_score` stored on CommentDraft, visible in review UI.
8. System SHALL track archetype → engagement correlation per avatar and auto-adjust selection weights.

---

### Requirement 4: Tier-2 Trust Signal Optimization

**User Story:** As a platform operator, I want the system to optimize for quality engagement signals, not just raw karma.

#### Acceptance Criteria

1. Track per-comment: `upvote_to_char_ratio` (upvotes / chars × 1000), `thread_depth_provoked` (direct replies count), `is_saved` (if detectable), `is_crossreferenced` (if quoted/linked by others).
2. Compute per-avatar `authority_score` (0-100): topic_coherence 30% + avg citability 20% + avg upvote_ratio 20% + avg thread_depth 15% + posting_consistency 10% + niche_tenure 5%.
3. Update `authority_score` daily (06:00 phase evaluation window), store on Avatar model.
4. Expose in admin: breakdown, 30-day trend, contributing factors.
5. Generation SHALL include "engagement hooks" — open questions, contrarian takes, "what's your experience?" to provoke thread depth.
6. Track which hooks produce most thread depth per subreddit, feed back into generation (self-learning loop extension).
7. WHEN `authority_score` > 75 → mark `authority_status = "expert"`, notify admin. Used for premium pricing.

---

### Requirement 5: Entity Linking (Brand Integration)

**User Story:** As a platform operator, I want the system to naturally associate the client's brand with problem-solution patterns, building persistent associations for LLM training data.

#### Acceptance Criteria

1. NicheProfile SHALL include `entity_linking_config`: `brand_entity`, `problem_patterns` (array), `solution_framing`, `linking_frequency` (1 per N comments), `linking_phase_gate` (default Phase 3).
2. Phase gates: Phase 1 = zero brand mentions, Phase 2 = indirect only (problem category, external sources, no brand name), Phase 3 = natural integration (1 per 5-8 comments, in problem-solving context).
3. Entity linking prompt: (a) identify problem, (b) provide genuine insight first, (c) mention brand as one option among others, (d) frame as personal experience.
4. Track `entity_link_events`: thread_id, comment_id, problem_pattern matched, community_response (upvotes).
5. Compute `entity_linking_effectiveness`: ratio of brand-mentioning comments with positive engagement (>3 upvotes, no removal) vs total mentions.
6. IF effectiveness < 50% → auto-reduce frequency by 50%, alert admin.
7. Enforce existing `brand_ratio` safety: max 1 brand mention per 5 comments per avatar per subreddit per 7 days.

---

### Requirement 6: Authority Dashboard & Reporting

**User Story:** As a platform operator, I want to monitor authority progression and demonstrate value to clients.

#### Acceptance Criteria

1. Avatar detail page: "Authority Progress" tab — score breakdown, 30-day trend, coherence history, citability distribution, top content, entity linking stats.
2. Avatars list: "Authority" column with color coding — <30 red, 30-60 amber, 60-75 green, 75+ gold.
3. Weekly "Authority Progress Report" per client (markdown): scores, best content, coherence trends, entity linking, qualitative AI visibility assessment.
4. "Grounding Source Check" tool: generates suggested queries for manual Perplexity/Google testing. Admin logs results (appeared/not, date, query). Qualitative validation only.
5. Emit ActivityEvents on authority milestones (30, 50, 75, 90).
6. Authority Score clearly documented as proxy metric — measures optimization for citation probability, NOT confirmed citation.

---

### Requirement 7: Content Anti-Detection & Naturalness

**User Story:** As a platform operator, I want content to pass Reddit spam filters and AI-detection algorithms, keeping it indexed and trusted.

#### Acceptance Criteria

1. Enforce natural patterns: varied sentence length (5-25 words mix), informal contractions, domain abbreviations. Optional typos (default: off).
2. Per-avatar voice consistency profile: avg sentence length, vocabulary complexity, punctuation patterns. Content stays within ±15% of established metrics.
3. Forbid: "Great question!" openers, bullet points in >40% of comments, repeating opening patterns in consecutive comments.
4. Content density rotation: 60% concise (50-150 words), 30% medium (150-300 words), 10% long-form (300-500 words).
5. Track removal rate per archetype, auto-deprioritize archetypes with >15% removal rate.

---

### Requirement 8: Niche-Aware Thread Selection

**User Story:** As a platform operator, I want scoring to prioritize threads aligned with the avatar's semantic cluster.

#### Acceptance Criteria

1. Compute `niche_relevance_score` (0-1): overlap between thread content (title + body + top comments) and NicheProfile (LSI keywords + entities).
2. Final score formula: `final_score = base_score × (0.5 + 0.5 × niche_relevance_score)`. Zero relevance = halved score.
3. Skip threads with `niche_relevance_score < 0.2` entirely for that avatar.
4. Track which subreddits produce high niche-relevance threads, recommend additions/removals.
5. When multiple avatars compete for same thread, prefer highest `niche_relevance_score` (enhance existing persona routing).

---

### Requirement 9: Authority Progression Phases

**User Story:** As a platform operator, I want warming phases to incorporate authority-building milestones for systematic progression toward Expert status.

#### Acceptance Criteria

1. Authority sub-phases within existing warming:
   - **1A** (months 1-2): Niche presence. Hobby + niche-adjacent. Target: coherence > 40, 10+ niche comments.
   - **1B** (months 2-3): Niche depth. Professional content, structured formats. Target: coherence > 55, citability_avg > 40.
   - **2A** (months 3-4): Authority building. High-value content, engagement optimization. Target: authority > 30, thread_depth > 1.5.
   - **2B** (months 4-5): Expert recognition. Consistent quality. Target: authority > 50, upvote_ratio > 0.5.
   - **3** (month 5+): Brand integration. Entity linking active. Target: authority > 60, linking_effectiveness > 60%.
   - **Expert** (authority > 75): AI-Native Expert. Premium status, quality over quantity.
2. Phase evaluation (daily 06:00) checks sub-phase criteria alongside existing karma/age checks.
3. Auto-promote on meeting all criteria, log ActivityEvent.
4. NO auto-demotion from Expert. Manual admin action only.
5. Admin UI: sub-phase display with progress indicator to next milestone.

---

### Requirement 10: Multi-Tenant Niche Management

**User Story:** As a platform operator managing multiple clients, I want efficient niche management across the avatar inventory.

#### Acceptance Criteria

1. Support "Niche Templates" — reusable NicheProfile configs applicable to multiple avatars.
2. When assigning avatar to client, suggest applicable templates based on client industry/keywords.
3. Prevent niche conflicts: two avatars from same client SHALL NOT have identical NicheProfiles (different sub-niches/angles required).
4. Niche overlap detection: >80% LSI keyword overlap between any two avatars → warn admin about cannibalization.
5. "Niche Health" dashboard: total active niches, authority distribution, underperforming niches, coverage gaps per client.
