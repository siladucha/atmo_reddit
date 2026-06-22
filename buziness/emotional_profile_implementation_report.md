# Subreddit Emotional Profile — Implementation Report

**Date:** 2026-06-17  
**Status:** Ready for deployment  
**Spec:** `.kiro/specs/subreddit-emotional-profile/requirements.md` (P0 + P1)

---

## What Was Implemented

### P0 — Core Analysis + Schema + UI + On-Demand Trigger

| Req | What | Status |
|-----|------|--------|
| Req 1 | Subreddit Emotional Profile Analysis | ✅ Done |
| Req 10 | Profile Data Schema (Pydantic validation) | ✅ Done |
| Req 8 | On-Demand Profile Analysis (admin button) | ✅ Done |
| Req 4 | Admin Panel — Profile Display (HTMX partial) | ✅ Done |

### P1 — Compatibility Scoring + Pipeline Injection + Auto-Refresh

| Req | What | Status |
|-----|------|--------|
| Req 3 | Avatar-Subreddit Compatibility Scoring | ✅ Done |
| Req 7 | Pipeline Integration — Tone Context in Generation | ✅ Done |
| Req 2 | Periodic Profile Refresh (weekly) | ✅ Done |
| Req 5 | Compatibility Warnings (admin display) | Partial (data ready, needs template tab) |

---

## Files Created (7 new)

| File | Purpose |
|------|---------|
| `app/schemas/emotional_profile.py` | Pydantic: EmotionalProfileSchema, CompatibilityResult |
| `app/models/avatar_subreddit_compatibility.py` | SQLAlchemy model for compatibility scores |
| `app/services/emotional_profile.py` | Core service: analyze, score, pipeline helper |
| `app/tasks/emotional_profile.py` | Celery: on-demand + weekly refresh + recompute |
| `alembic/versions/ep01_subreddit_emotional_profile.py` | Migration: columns + table |
| `docs/kb/guides/discovery-engine.md` | Discovery Engine documentation |
| `buziness/emotional_profile_implementation_report.md` | This report |

## Files Modified (4)

| File | Change |
|------|--------|
| `app/models/subreddit.py` | Added JSONB import + 4 emotional_profile columns |
| `app/services/generation.py` | Injected tone context section (non-blocking) |
| `app/tasks/worker.py` | Added task include + Celery Beat schedule entry |
| `app/routes/admin.py` | Added 2 routes (analyze trigger + HTMX partial) |

---

## How It Works

### Flow: Profile Analysis
```
Admin clicks "Run Analysis" on subreddit detail page
→ Celery task dispatched
→ PRAW fetches hot threads (10) + top comments (30, score ≥ 2)
→ Gemini Flash analyzes tone patterns
→ Pydantic validates output (retry once on failure)
→ Stores in subreddits.emotional_profile JSONB
→ Admin sees: rewarded tones (green), punished tones (red), temperament, formality/humor/vulnerability
```

### Flow: Compatibility Scoring
```
After profile exists + avatar has voice_profile_md
→ Gemini Flash Lite compares avatar voice vs subreddit profile
→ Returns score 0-100 + mismatch_reasons
→ Stored in avatar_subreddit_compatibility table
→ Score < 40 = tone mismatch warning
```

### Flow: Pipeline Injection (during comment generation)
```
generate_comment() called for avatar + thread
→ get_subreddit_tone_context(db, thread.subreddit)
→ If profile exists: returns formatted "SUBREDDIT TONE CONTEXT" section
→ Injected into system prompt (after strategy, before approach constraint)
→ LLM sees: "WORKS WELL: [tones]" and "AVOID: [tones]"
→ Non-blocking: if no profile, generation proceeds normally
```

### Schedule (Celery Beat)
```
Sunday 04:30 — refresh_subreddit_emotional_profiles (weekly)
  → Sequential, 5s delay between subs
  → After refresh → recompute_all_compatibility
```

---

## Cost

| Operation | Model | Cost per call |
|-----------|-------|---------------|
| Profile analysis (1 sub) | Gemini Flash | ~$0.0006 |
| Compatibility scoring (1 pair) | Gemini Flash Lite | ~$0.0002 |

**Monthly at 10 clients (50 subs, 50 avatars):**
- Profile refresh: 50 × $0.0006 = $0.03/month
- Compatibility: 150 pairs × $0.0002 = $0.03/month
- **Total: ~$0.06/month** (negligible)

---

## Deployment Steps

```bash
# 1. Push code to server
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./reddit_saas/ root@161.35.27.165:/app/

# 2. Run migration
ssh root@161.35.27.165 "cd /app && docker compose exec -T app alembic upgrade head"

# 3. Rebuild and restart
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# 4. Verify
ssh root@161.35.27.165 "curl -s http://localhost/health | python3 -m json.tool"
```

---

## What This Solves (Quality Risk)

**Before:** Discovery recommends a subreddit → avatar goes there → comments get removed or downvoted → we learn AFTER the damage.

**After:** 
1. Profile analysis checks subreddit vibe BEFORE avatar enters
2. Compatibility scoring checks if THIS avatar fits THIS sub
3. Generation prompt includes tone guidance (avoid/use patterns)
4. Weekly refresh catches subreddit culture drift

**Net effect:** Fewer removed comments, less karma loss, better avatar-subreddit matching.

---

## Not Implemented (deferred to P2)

- Req 6: Subreddit list colored dots (trivial UI, low value)
- Req 9: Karma correlation display
- Req 11: Thread emotional classification (piggybacked on scoring)
- Req 12: Avatar emotional range inference

These require no architecture changes — just additional UI and minor prompt tweaks.
