# Implementation Plan: Post Generation Engine

## Overview

This plan implements a 10-step AI pipeline for generating Reddit self-posts. The engine uses a `ClientPostConfig` model for per-client configuration, 10 pipeline step modules, an orchestrator service, and integration with existing Celery tasks and EPG scheduling.

## Tasks

- [ ] 1. Create ClientPostConfig model and Alembic migration with all fields (allowed_themes, forbidden_terms, content_mix_ratios, allowed_post_types, worldview_concepts, anti_pattern_words, worthiness_weights, top_n_situations, target_length_min/max, writing_rules, authenticity_threshold, persona_theme_mapping, post_generation_active, brand_mention_cap). Add unique constraint on client_id. Import in models/__init__.py.
  - Requirements: 11, 14
  - Dependencies: None

- [ ] 2. Create Pydantic schemas in `app/schemas/post_gen_outputs.py`: ExperienceSituation, ExperienceGeneratorOutput, WorthinessScores, WorthinessScorerOutput, FrictionOutput, PostOutput, AuthenticityOutput — with all field constraints (ranges, lengths).
  - Requirements: 2, 3, 5, 7, 10
  - Dependencies: None

- [ ] 3. Add `post_generation_enabled` system setting to DEFAULTS in settings.py (value "true", group "scheduler"). Add `is_post_generation_enabled(db)` helper that reads fresh from DB.
  - Requirements: 14
  - Dependencies: None

- [ ] 4. Implement Theme Selector step in `app/services/post_gen_steps/theme_selector.py`. Deterministic weighted selection from allowed_themes using content_mix_ratios. Query PostDraft history (14 days) to avoid repetition. Exclude themes with forbidden_terms. Track rolling 30-day distribution. Return theme + category or None.
  - Requirements: 1
  - Dependencies: 1

- [ ] 5. Implement Experience Generator step in `app/services/post_gen_steps/experience_generator.py`. LLM call (Gemini Flash) generating 20 practitioner situations. Validate against ExperienceGeneratorOutput schema. Retry once if <5 valid. Log AIUsageLog.
  - Requirements: 2
  - Dependencies: 1, 2

- [ ] 6. Implement Worthiness Scorer step in `app/services/post_gen_steps/worthiness_scorer.py`. LLM call (Gemini Flash) scoring 5 dimensions. Compute weighted composite using config weights. Select top N. Discard batch if all below 5.0. Retry once on LLM failure.
  - Requirements: 3
  - Dependencies: 2, 5

- [ ] 7. Implement Persona Matcher step in `app/services/post_gen_steps/persona_matcher.py`. Use persona_theme_mapping if available, else LLM-based. Exclude Phase 0/1, frozen, unhealthy avatars. Distribute across avatars. Fallback to highest karma. Emit event if no eligible avatar.
  - Requirements: 4
  - Dependencies: 1

- [ ] 8. Implement Friction Generator step in `app/services/post_gen_steps/friction_generator.py`. LLM call (Gemini Flash) identifying emotional center from 6 options. Produce 40-200 char statement. Fallback to "curiosity" with low-confidence flag.
  - Requirements: 5
  - Dependencies: 2

- [ ] 9. Implement Post Type Selector step in `app/services/post_gen_steps/post_type_selector.py`. Deterministic selection using friction-to-type affinity. Enforce 40% cap over 30-day window. Fallback to lowest-usage allowed type.
  - Requirements: 6
  - Dependencies: 1

- [ ] 10. Implement Post Writer step in `app/services/post_gen_steps/post_writer.py`. LLM call (Claude Sonnet) generating title + body. Inject voice profile, writing_rules, learning context. Validate word count. Regenerate once if over max. Reject if no voice profile.
  - Requirements: 7, 16
  - Dependencies: 1, 2

- [ ] 11. Implement Worldview Injector step in `app/services/post_gen_steps/worldview_injector.py`. Optional LLM call (Gemini Flash). Skip for Phase 1. Evaluate semantic overlap. Max 1 concept. Track 30-day count vs brand_mention_cap. Skip if empty/null.
  - Requirements: 8
  - Dependencies: 1

- [ ] 12. Implement Anti-Pattern Filter step in `app/services/post_gen_steps/anti_pattern_filter.py`. Deterministic check — case-insensitive word/substring matching against anti_pattern_words + forbidden_terms. Check generic patterns. Return passed/warning/violations.
  - Requirements: 9
  - Dependencies: 1

- [ ] 13. Implement Authenticity Tester step in `app/services/post_gen_steps/authenticity_tester.py`. LLM call (Gemini Flash) with test question from config. Return pass/fail + confidence + markers. Threshold from config (default 0.6).
  - Requirements: 10
  - Dependencies: 2

- [ ] 14. Implement PostGenerationPipeline orchestrator in `app/services/post_generation_pipeline.py`. Load config, execute 10 steps per situation, handle retries (rewrite on auth fail, regenerate on anti-pattern), enforce 5-min timeout, create PostDraft with provenance, emit audit/activity events, assign run_id UUID. Enforce daily cap and 2-pending limit.
  - Requirements: 12, 13, 14, 15, 17
  - Dependencies: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13

- [ ] 15. Integrate pipeline with `generate_posts` Celery task. Check for ClientPostConfig; if active, delegate to PostGenerationPipeline. If no config, use legacy pipeline. Check `post_generation_enabled` kill switch. Preserve retry logic.
  - Requirements: 14, 12
  - Dependencies: 1, 3, 14

- [ ] 16. Add safety and phase gate enforcement in orchestrator. Phase 1: community_value only, zero brand. Phase 2: worldview seeding, no explicit brand. Enforce brand_mention_cap as hard limit. All drafts status="pending". Verify kill switches at entry.
  - Requirements: 13
  - Dependencies: 14

- [ ] 17. Implement audit logging. AuditLog at start/complete/fail. ActivityEvent per draft. AIUsageLog per LLM call. Step failure logging with name + error + completed steps. Run_id in all entries. Structured JSON logger at INFO/ERROR.
  - Requirements: 15
  - Dependencies: 14

- [ ] 18. Implement self-learning integration. Call LearningService for few-shot examples and correction patterns before Post Writer. Inject into prompt. Handle failures gracefully. Capture EditRecord on post review (adapt comment review hook).
  - Requirements: 16
  - Dependencies: 10, 14

- [ ] 19. Create admin UI for ClientPostConfig. Add "Post Generation" tab to client detail page. Display/edit all config fields. Toggle post_generation_active. Validate content_mix_ratios sum, allowed_post_types validity. Add GET/POST routes.
  - Requirements: 11
  - Dependencies: 1

## Task Dependency Graph

```json
{
  "waves": [
    [1, 2, 3],
    [4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
    [14],
    [15, 16, 17, 18, 19]
  ]
}
```

## Notes

- Tasks 1, 2, 3 have no dependencies and can be done in parallel
- Tasks 4-13 (pipeline steps) depend on the model (1) and schemas (2) but are independent of each other
- Task 14 (orchestrator) depends on all pipeline steps
- Tasks 15-19 depend on the orchestrator
- The existing `generate_posts` task continues working for clients without ClientPostConfig (backward compatible)
