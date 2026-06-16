# Design Document

## Overview

The XM Cyber Post Strategy is a client-specific configuration record (`ClientPostConfig`) that plugs into the Post Generation Engine. It implements Tzvi's "XM Reddit Engine V2 Build Specification" — configuring the generic 10-step pipeline to generate authentic cybersecurity practitioner posts seeded with XM Cyber's worldview concepts. No custom code paths are needed — the engine reads this config and adapts behavior.

## Architecture

The XM Cyber strategy is a pure configuration record — no custom code paths or XM-specific services. The generic Post Generation Engine reads the `ClientPostConfig` row for XM Cyber and adapts its 10-step pipeline behavior based on the stored configuration values.

## Components and Interfaces

### Seed Script

Location: `app/seeds/xm_cyber_post_config.py`

```python
def seed_xm_cyber_post_config(db: Session, client_id: uuid.UUID) -> ClientPostConfig:
    """Create or update XM Cyber post generation config. Idempotent."""
    ...
```

### Admin Integration

- "Seed XM Cyber Config" button on client detail page
- "Post Generation" tab shows all fields (read from ClientPostConfig)
- Toggle `post_generation_active` to enable/disable

### Prompt Parameterization

The Post Generation Engine injects `writing_rules` from config into prompts:
- Post Writer receives: opening_rule, structure, tone, anti_tone, global_rule
- Authenticity Tester receives: authenticity_test, pass_signals, fail_signals
- Experience Generator receives: icp_segments, content_category_definitions

## Data Models

### ClientPostConfig Record (XM Cyber Instance)

The following values are stored in the `client_post_configs` table row for XM Cyber:

```json
{
    "client_id": "<xm_cyber_uuid>",
    "allowed_themes": ["Identity Risk", "Exposure Prioritization", "Remediation Efficiency", "Cloud Drift", "Hybrid Infrastructure", "Security Operations", "Continuous Validation", "Attack Paths", "Exposure Validation"],
    "forbidden_terms": ["CTEM", "Exposure Management", "Digital Twin", "Risk Reduction Platform", "Cyber Resilience Framework", "holistic", "strategic", "visibility", "ecosystem", "transformation", "framework", "maturity", "journey", "operating model"],
    "content_mix_ratios": {"community_value": 60, "problem_awareness": 25, "worldview": 10, "brand_narrative": 5},
    "allowed_post_types": ["War_Story", "Observation", "Frustration", "Discussion_Question", "Contrarian_Insight"],
    "worldview_concepts": ["attack path", "lateral movement", "blast radius", "ownership", "prioritization", "remediation"],
    "anti_pattern_words": ["holistic", "strategic", "framework", "transformation", "maturity", "visibility", "ecosystem", "journey", "operating model"],
    "worthiness_weights": {"curiosity": 0.15, "relatability": 0.30, "frustration": 0.20, "authenticity": 0.20, "discussion_potential": 0.15},
    "top_n_situations": 5,
    "target_length_min": 150,
    "target_length_max": 350,
    "authenticity_threshold": 0.6,
    "persona_theme_mapping": {
        "Lucas Parker": {"primary": ["Security Operations", "Continuous Validation"], "secondary": ["Attack Paths", "Exposure Prioritization"]},
        "Connor": {"primary": ["Cloud Drift", "Hybrid Infrastructure", "Exposure Validation"], "secondary": ["Attack Paths", "Exposure Prioritization"]},
        "Leon": {"primary": ["Identity Risk", "Remediation Efficiency"], "secondary": ["Attack Paths", "Exposure Prioritization"]}
    },
    "writing_rules": {
        "opening_rule": "Must start with something happened or something was observed. Never start with opinion, lesson, trend, or strategic statement.",
        "structure": ["what happened", "why it mattered", "what surprised me", "question or open observation"],
        "tone": ["practitioner", "human", "slightly frustrated", "curious"],
        "anti_tone": ["vendor", "consultant", "executive", "marketer"],
        "global_rule": "Do not write about cybersecurity concepts. Write about PEOPLE DEALING WITH cybersecurity problems.",
        "authenticity_test": "Would a tired engineer write this at 10PM?",
        "anti_linkedin_patterns": ["keynote speaker tone", "consultant framing", "vendor blog style", "LinkedIn post patterns"],
        "authenticity_pass_signals": ["conversational flow", "emotional specificity", "incomplete resolution", "detail asymmetry"],
        "authenticity_fail_signals": ["polished paragraph structure", "balanced arguments", "clean conclusions", "professional detachment"],
        "icp_segments": {
            "Security Operations": ["alert fatigue", "tool sprawl", "ownership ambiguity", "after-hours incidents"],
            "Identity & Access Management": ["orphaned accounts", "privilege creep", "access review fatigue", "identity lifecycle gaps"],
            "Cloud Security": ["configuration drift", "multi-cloud inconsistency", "shared responsibility confusion", "runtime vs posture disconnect"],
            "Infrastructure Security": ["patch prioritization paralysis", "legacy system exposure", "network segmentation debt", "hybrid environment blind spots"]
        },
        "content_category_definitions": {
            "community_value": ["sysadmin frustrations with tooling", "Azure/cloud platform ops issues", "AWS ownership and billing", "K8s deployment and scaling", "vuln mgmt scan noise"],
            "problem_awareness": ["ticket ownership disputes", "patch deployment delays", "identity cleanup backlogs", "cloud drift"],
            "worldview": ["prioritization by impact not severity", "attack path thinking", "security control validation", "remediation bottleneck analysis"],
            "brand_narrative": ["continuous validation concept", "exposure-centric thinking", "choke point analysis", "identity-centric risk in hybrid"]
        }
    },
    "post_generation_active": false,
    "brand_mention_cap": null
}
```

## Error Handling

- Seed script validates all fields before saving (sums, ranges, allowed values)
- Raises ValueError with specific message on any validation failure
- If XM Cyber client doesn't exist, seed script logs error and returns None
- Admin UI shows validation errors inline on save

## Correctness Properties

### Property 1: Generic Config
XM Cyber config uses the same ClientPostConfig model as any other client with no special code paths.

### Property 2: Ratio Sum
content_mix_ratios always sum to exactly 100 (60+25+10+5=100).

### Property 3: Weight Sum
worthiness_weights always sum to 1.0 (0.15+0.30+0.20+0.20+0.15=1.0).

### Property 4: Valid Post Types
All allowed_post_types are valid members of the 5 supported types.

### Property 5: Safe Default
post_generation_active defaults to false requiring explicit admin activation.

### Property 6: Idempotent Seed
Seed script updates existing record if present without creating duplicates.

## Testing Strategy

- Seed script unit test: verify all fields populated correctly
- Validation test: tamper with ratios, verify rejection
- Integration test: run PostGenerationPipeline with XM Cyber config, verify:
  - Theme comes from 9 allowed clusters
  - No forbidden terms in output
  - Persona routing matches mapping
  - Writing rules appear in LLM prompt
  - Anti-pattern words trigger rejection
