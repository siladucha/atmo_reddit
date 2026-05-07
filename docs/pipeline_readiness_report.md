# Pipeline Readiness Report — May 7, 2026

## Executive Summary

The comment pipeline (professional + hobby) is **100% implemented** and mirrors Ori's n8n workflows. The post creation pipeline (`generate_posts`) is a **stub** — it requires a separate 3-step LLM chain and a news source integration that doesn't exist yet. Post creation is not needed for the first pilot (comments are the core product).

---

## What's Fully Implemented (Comment Pipeline)

| Ori's n8n Workflow | Our Implementation | Status |
|---|---|---|
| Scrape subreddit (professional) | `scrape_professional_subreddits`, `scrape_subreddit_shared` | ✅ Complete |
| Scrape hobby subreddits | `scrape_hobby_subreddits` | ✅ Complete |
| Thread scoring (tag/relevance/quality/strategic/composite) | `score_unscored_threads_for_client` + `ScoringOutput` Pydantic schema | ✅ Complete |
| Persona selection (mode, audience, thread_angle, pov_opportunity) | `select_persona()` in `generation.py` | ✅ Complete |
| Professional comment writing (strategic angles, location, depth) | `generate_comment()` + `CommentOutput` Pydantic schema | ✅ Complete |
| Comment editing (tone cleanup, human-like polish) | `edit_comment()` in `generation.py` | ✅ Complete |
| Hobby comment writing (karma building, voice profile, diversity) | `generate_hobby_comments()` in `ai_pipeline.py` | ✅ Complete |
| Previous comments diversity enforcement (last 20 fed to prompt) | Both professional and hobby pipelines | ✅ Complete |
| Safety checks (daily limits, phase policy, brand ratio, subreddit limits) | `safety.py` — full implementation | ✅ Complete |
| Avatar phase enforcement (Phase 1/2/3 restrictions) | `phase.py` + `PhaseEvaluator` + `PhaseTransitionManager` | ✅ Complete |
| Human review queue | `CommentDraft` model + admin review UI | ✅ Complete |

### Pipeline Flow (End-to-End)

```
queue_tick (every 60s) → scrape subreddits → save RedditThread records
                                    ↓
run_full_pipeline (08:00, 14:00 UTC) → score_threads (Gemini Flash)
                                    ↓
                              generate_comments (Claude Sonnet)
                              ├─ select_persona → pick best avatar
                              ├─ generate_comment → write draft
                              └─ edit_comment → polish tone
                                    ↓
                              Human review queue (approve/reject/edit)
                                    ↓
                              Manual posting to Reddit
```

---

## What's NOT Implemented — Post Creation Pipeline

### Why It's a Stub

Ori's post creation workflow (`XM Cyber — Reddit Post Creation`) is a fundamentally different pipeline with **3 sequential LLM stages**:

1. **Brief Generator** (Claude Sonnet) — Analyzes source material (news articles, reports), classifies input treatment mode, assigns strategic tier (worldview push / problem awareness / community value), selects post type and body architecture
2. **Persona Selector** (Gemini Flash) — Chooses the best avatar for the post based on subreddit fit and topic alignment
3. **Post Writer** (Claude Sonnet) — Writes the full post following the brief's strategic directions

### Dependencies That Don't Exist Yet

| Dependency | Description | Effort |
|---|---|---|
| `news_scrape` table | Source material for posts (news articles, reports, competitor mentions) | 1 day |
| News ingestion | RSS feeds, Google News API, or manual URL submission | 1 day |
| 3-step LLM chain | Brief → Persona → Write with intermediate validation | 1.5 days |
| Post-specific prompts | Brief Generator prompt, Post Writer prompt (from Ori's workflow) | 0.5 day |
| `PostDraft` review flow | Separate review queue for posts (model exists, UI partially done) | 0.5 day |

**Total estimated effort: ~4-5 days**

### Why It's Not Blocking the Pilot

1. **Comments = 90% of activity.** The core value proposition is comment engagement, not post creation.
2. **Pricing tiers:** Seed ($149) and Starter ($399) plans include 0 posts. Posts only appear in Growth ($799+) at 10/month.
3. **Phase restrictions:** Most avatars start in Phase 1-2 where post creation isn't allowed anyway (only comments for credibility building).
4. **Manual workaround:** For the pilot, Tzvi can manually create posts if needed — the review queue and posting workflow already exist.

---

## Differences from Ori's Workflows

### Implemented Differently (Functional Equivalent)

| Ori's Approach | Our Approach | Notes |
|---|---|---|
| Separate `.md` files per avatar (voice profile) | `avatar.voice_profile_md` field in database | Same content, different storage |
| Company Profile as `.md` file | `client.company_profile`, `company_worldview`, `company_problem` DB fields | Same data, queryable |
| n8n structured output parser | Pydantic `ScoringOutput` / `CommentOutput` schemas | Stronger validation |
| Supabase for storage | PostgreSQL + SQLAlchemy | Same schema, better ORM |
| n8n scheduler | Celery Beat (08:00, 14:00 UTC + continuous scraping) | Same schedule |

### Not Yet Implemented (Quality Improvements for Later)

| Feature | Description | Priority | Effort |
|---|---|---|---|
| `forbidden_patterns.md` | Dedicated file with banned language patterns, loaded into every prompt | Medium — improves comment quality | 0.5 day |
| Subreddit intelligence | Per-subreddit rules/wiki parsing, culture guide | Medium — reduces mod removals | 2-3 days |
| ICP Personas document | Formal target audience personas per client | Low — company_profile covers basics | 1 day |
| `Reddit_Guide.md` | General Reddit mechanics guide loaded into prompts | Low — basics are in prompts already | 0.5 day |

---

## What's Needed to Run a Live Demo

### Infrastructure Checklist (No Code Changes Required)

```
[ ] 1. Set Reddit API credentials in .env (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET)
[ ] 2. Set LLM API key in .env (LITELLM_API_KEY)
[ ] 3. Start PostgreSQL + Redis (docker compose up -d db redis)
[ ] 4. Run database migrations (python -m alembic upgrade head) — DONE
[ ] 5. Run seed script (python -m app.seed) — creates admin user, XM Cyber client, 5 avatars, 33 subreddits
[ ] 6. Start FastAPI app (uvicorn app.main:app --port 8000)
[ ] 7. Start Celery worker (celery -A app.tasks.worker worker --loglevel=info)
[ ] 8. Start Celery Beat scheduler (celery -A app.tasks.worker beat --loglevel=info)
```

### Demo Script

1. Login to admin panel: `http://localhost:8000/admin/`
2. Click "Scrape All" → watch activity feed (5-15 seconds)
3. Click "Score All" → threads get tagged (engage/monitor/skip)
4. Click "Generate All" → comment drafts appear in review queue
5. Open review queue → approve/reject/edit drafts
6. Show pipeline controls → toggle kill switches
7. Show avatar detail → freeze/unfreeze controls

---

## MVP Hardening Sprint 1 — Completed

All required tasks from the hardening sprint are done:

- ✅ Avatar Freeze (model + migration + pipeline guards + admin UI)
- ✅ Global Kill Switches (pipeline_enabled, generation_enabled, scrape_enabled)
- ✅ Admin Emergency Controls (freeze/unfreeze endpoints, pipeline toggle UI)
- ✅ Retry with Exponential Backoff (3 retries, 60s/120s/240s, AI tasks only)
- ✅ Structured LLM Output Validation (Pydantic schemas for scoring + generation)
- ✅ Context Isolation Assertions (runtime checks in select_persona + generate_comment)
- ✅ E2E Onboarding Test (full pipeline test with mocked LLM)
- ✅ Migration chain fixed (duplicate revision ID, detached migration, missing subreddit_id)

**Test suite: 177 tests passing.**

---

## Recommendation

**For the first paid pilot:** Ship as-is. The comment pipeline is complete and production-ready. Post creation can be added in Sprint 3 when Growth-tier clients need it.

**Next priorities (in order):**
1. Configure environment and run live demo with real Reddit data
2. Add `forbidden_patterns.md` to improve comment quality
3. Implement timing jitter (Sprint 2 — behavioral randomization)
4. Implement `generate_posts` when a Growth-tier client signs up
