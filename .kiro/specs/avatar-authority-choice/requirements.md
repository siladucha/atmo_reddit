# Avatar Authority Choice in BYOA (Bring Your Own Avatar)

## Problem Statement

When a client connects their own Reddit avatar during onboarding (Step 5 — BYOA flow), the system automatically classifies it via AI (Claude) as a "community voice" based on Reddit history. However, the client should choose what kind of authority this avatar represents for their brand.

Tzvi's feedback (June 26): "When inserting a client-owned avatar as part of the onboarding flow, the system treats it as a community voice — we should allow the client to choose his desired authority, tone, etc. For example: For Ono International School, the client should choose whether this avatar should be a CEO, a lecturer, a student, etc."

## Requirements

### FR-1: Authority Role Selection

1. AFTER AI classification completes (avatar_onboard_analysis), THE system SHALL present the client with an authority selection step:
   - **Role/Expertise** dropdown or free-text: CEO, Engineer, Student, Researcher, Practitioner, Consultant, etc.
   - **Industry Authority** free-text: "Cybersecurity veteran", "Yoga instructor", "SaaS founder"
   - **Tone preference** radio: Technical Expert | Friendly Practitioner | Thought Leader | Community Member
2. THE AI classification SHALL be shown as a "suggestion" that the client can override
3. THE client's authority choice SHALL override AI-generated `persona_bio` and `voice_profile_md`

### FR-2: Authority Influences Generation

1. THE `voice_profile_md` stored on avatar SHALL incorporate the authority choice:
   - Role → appears in voice profile opening (e.g., "A senior DevOps engineer who...")
   - Tone preference → adjusts formality level and vocabulary
   - Industry Authority → defines the domain of expertise for content
2. WHEN generating comments, THE prompt SHALL use the authority-enhanced voice profile
3. THE authority choice SHALL NOT change which subreddits the avatar posts in (that's configured separately)

### FR-3: UI in Onboarding Flow (Step 5)

1. THE BYOA flow SHALL be: Enter username → AI analyzes → Show classification card → **Authority selection** → Confirm & create
2. THE authority selection SHALL appear as an expandable section on the analysis card:
   - "How should this avatar represent your brand?"
   - Pre-filled with AI suggestion (editable)
   - Quick-select buttons for common roles + free-text option
3. THE selection SHALL be optional — if skipped, AI classification is used as-is

### FR-4: Editable Post-Creation

1. AFTER avatar is created, THE authority settings SHALL be editable from:
   - Admin panel: Avatar detail page → Authority section
   - Client portal: Avatar detail page → "Edit Role" button
2. CHANGES to authority SHALL trigger voice_profile_md regeneration (LLM call to rebuild profile)

## Data Model Changes

1. **Avatar model**: add fields:
   - `authority_role`: String(100), nullable — "CEO", "Engineer", "Student", etc.
   - `authority_description`: Text, nullable — "Cybersecurity veteran with 15 years in enterprise"
   - `authority_tone`: String(30), nullable — "technical_expert" | "friendly_practitioner" | "thought_leader" | "community_member"
   - `authority_source`: String(20), default "ai" — "ai" | "client" | "operator"
2. These fields feed into voice_profile_md generation but don't replace it

## Non-Functional Requirements

### NFR-1: Non-Blocking
- Authority selection is optional — skipping it uses AI default
- Voice profile regeneration (if authority changed) runs async
- Onboarding completion not blocked by authority choice

### NFR-2: Backward Compatible
- Existing avatars without authority fields continue working (null = use existing voice_profile_md)
- No migration needed for existing voice profiles

## Out of Scope

- Multiple authority roles per avatar (one role per avatar)
- Authority-based subreddit recommendation (separate feature)
- Authority scoring/verification

## Dependencies

- Avatar onboarding flow (exists: `app/routes/avatar_onboard.py`)
- Avatar analysis service (exists: `app/services/avatar_onboard_analysis.py`)
- Voice profile field on Avatar model (exists: `voice_profile_md`)
- Alembic migration for new fields

## Success Criteria

1. Client can choose "CEO" instead of AI-suggested "community member" during BYOA
2. Generated comments reflect the chosen authority (tone, vocabulary, self-reference)
3. Existing avatars unaffected (null authority = AI default behavior)
