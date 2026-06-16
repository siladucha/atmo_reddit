# Implementation Plan: XM Cyber Post Strategy

## Overview

This plan creates the XM Cyber client-specific post generation configuration as a `ClientPostConfig` record. It depends on the Post Generation Engine being implemented first (model + orchestrator). The work is primarily data/seed setup and verification.

## Tasks

- [ ] 1. Verify or create XM Cyber client record in clients table with: client_name="XM Cyber", brand_name="XM Cyber", company_worldview (exposure management philosophy), company_problem (finding and fixing exposures that actually matter), competitive_landscape (Tenable, Qualys, Rapid7, CrowdStrike), industry="cybersecurity".
  - Requirements: 12
  - Dependencies: None

- [ ] 2. Create seed script at `app/seeds/xm_cyber_post_config.py` with `seed_xm_cyber_post_config(db, client_id)`. Populate all 9 allowed_themes, 14 forbidden_terms, content_mix_ratios (60/25/10/5), 5 allowed_post_types, 6 worldview_concepts, 9 anti_pattern_words, custom worthiness_weights (relatability=0.30), target lengths 150-350, top_n=5. Make idempotent.
  - Requirements: 1, 2, 3, 4, 5, 6, 12
  - Dependencies: 1, post-generation-engine Task 1

- [ ] 3. Add writing_rules JSONB to the seed: opening_rule, structure array, tone/anti_tone arrays, global_rule, authenticity_test, anti_linkedin_patterns, authenticity_pass/fail_signals, icp_segments (4 segments with pain points), content_category_definitions (4 categories with topics).
  - Requirements: 7, 9, 10, 11
  - Dependencies: 2

- [ ] 4. Add persona_theme_mapping to the seed: Lucas Parker (Security Operations, Continuous Validation), Connor (Cloud Drift, Hybrid Infrastructure, Exposure Validation), Leon (Identity Risk, Remediation Efficiency). Verify avatar records exist with voice profiles and correct client_ids.
  - Requirements: 8
  - Dependencies: 2

- [ ] 5. Add content_category_definitions to writing_rules with detailed topic lists per category (community_value, problem_awareness, worldview, brand_narrative). These guide the Experience Generator's situation generation.
  - Requirements: 11
  - Dependencies: 3

- [ ] 6. Add admin route `POST /admin/clients/{id}/seed-post-config` to trigger seed. Add button to XM Cyber client detail page. Alternatively integrate into `app/seed.py` as conditional block.
  - Requirements: 12
  - Dependencies: 2

- [ ] 7. Add validation in seed script: verify content_mix_ratios sum=100, worthiness_weights sum=1.0, allowed_post_types valid, length range valid, worldview_concepts<=20, forbidden_terms<=500. Raise ValueError on failure.
  - Requirements: 12
  - Dependencies: 2

- [ ] 8. Run end-to-end test: execute PostGenerationPipeline for XM Cyber, verify theme from 9 clusters, no forbidden terms in output, persona routing correct, writing_rules in prompt, anti-pattern words trigger rejection, PostDraft created with status="pending" and full provenance.
  - Requirements: All (1-12)
  - Dependencies: 2, 3, 4, 5, 7, post-generation-engine Task 14

- [ ] 9. Activate XM Cyber: set post_generation_active=true, verify next generate_posts run includes XM Cyber, monitor via Activity Feed, verify posts in review queue, disable if issues.
  - Requirements: 12
  - Dependencies: 8

## Task Dependency Graph

```json
{
  "waves": [
    [1],
    [2],
    [3, 4, 5, 6, 7],
    [8],
    [9]
  ]
}
```

## Notes

- This spec depends on Post Generation Engine (Tasks 1 and 14 at minimum) being complete
- Tasks 1-7 are pure data/config work — no new service logic needed
- Task 8 is the acceptance test verifying the full pipeline works with XM Cyber config
- Task 9 is the final activation step (done manually by admin after verification)
- Avatar records for Lucas Parker, Connor, and Leon must exist before Task 4
