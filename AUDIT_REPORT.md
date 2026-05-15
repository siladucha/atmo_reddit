# Audit Report — Reddit SaaS Backend

Scope: `reddit_saas/app/` — models, services, tasks, routes, dependencies, schemas, config.
Method: read all models to build attribute map, then cross-reference every attribute access in services/tasks/routes, plus business-logic checks (phase rules, learning loop, kill switches, isolation).

---

## CRITICAL (will crash in production or completely break a feature)

### 1. `services/phase.py:322` — `set()` on list of dicts raises TypeError, breaks Phase 2 generation
```python
# _check_phase2
hobby_subs = avatar.hobby_subreddits or []
business_subs = avatar.business_subreddits or []
allowed_subs = set(hobby_subs) | set(business_subs)
```
`avatar.hobby_subreddits` / `business_subreddits` are JSONB and the system stores them as a list of dicts (e.g. `{"subreddit": "name"}`) — every other consumer (`routes/avatar_pipeline.py` line 92‑115, `services/smart_scoring.py` line 154‑175, `tasks/scraping.py` line 204‑213, `services/strategy_engine.py` line 177‑187) explicitly normalises dict→string before use. Here it does not.

When called with a dict-based `hobby_subreddits`, `set(hobby_subs)` raises `TypeError: unhashable type: 'dict'`, which propagates out of `PhasePolicy.check_comment_allowed`, gets caught by the `try/except` in `services/safety.py:117`, and returns a `SafetyCheckResult(False, "Phase policy check error: ...")`. **Every Phase 2 comment is blocked** with a "Phase policy check error" message.

**Fix:** normalise items before set/contains, e.g.:
```python
def _names(raw):
    out = []
    for it in raw or []:
        n = it.get("subreddit") or it.get("name") if isinstance(it, dict) else str(it)
        if n: out.append(n.strip().replace("r/", "").lower())
    return out
allowed_subs = set(_names(avatar.hobby_subreddits)) | set(_names(avatar.business_subreddits))
```

### 2. `services/phase.py:271-272` — `target_subreddit not in hobby_subs` always True when items are dicts, breaks Phase 1
```python
# _check_phase1
hobby_subs = avatar.hobby_subreddits or []
if target_subreddit not in hobby_subs:
    return PolicyResult(blocked, "Phase 1: subreddit '...' not in hobby_subreddits")
```
Same root cause as #1, different symptom. `"reddit_username" in [{"subreddit": "reddit_username"}]` is `False` (string vs dict). Result: every Phase 1 hobby comment is rejected with "subreddit not in hobby_subreddits" — Phase 1 avatars (i.e. all new/CQS-lowest avatars) cannot generate ANY comments.

**Fix:** same normalisation as #1; do `target_subreddit.lower() in normalised_names`.

### 3. `services/karma_tracker.py:39-61` `_classify_subreddit` — `.lower()` on dict, TypeError
```python
business = avatar.business_subreddits or []
if isinstance(business, dict):
    business = list(business.keys())
if any((s or "").lower() == sub_lower for s in business):
    ...
```
The check `isinstance(business, dict)` handles the case where the JSONB *root* is an object, not where items inside the list are dicts. When `business_subreddits = [{"subreddit": "..."}]`, the iteration calls `.lower()` on a dict → `AttributeError`. This is called from `record_comment_score`, `sync_avatar_from_comment_history`, `sync_avatar_from_reddit` — i.e. every karma update path. Karma tracking on `posted` transitions (`routes/review.py:110`) and Reddit-status sync will throw, the caller's `try/except` swallows it, and per-subreddit karma silently never updates.

**Fix:** add the same dict-item normalisation as #1.

### 4. `services/safety.py:82-83` — phase content restrictions silently bypassed when called without all 3 args
```python
if target_subreddit is not None and comment_text is not None and client is not None:
    # PhasePolicy.check_comment_allowed(...)
```
Callers that don't pass `comment_text` AND `client` skip the entire phase-policy gate — including subreddit allow-listing for phase 1/2:

- `tasks/ai_pipeline.py:321`: `check_avatar_can_post(db, avatar, "professional")` — only 3 args. Auto-pipeline never enforces subreddit phase restrictions before paying for LLM generation.
- `routes/avatar_pipeline.py:750` and `:866`: `check_avatar_can_post(db, avatar, comment_type, thread.subreddit)` — missing `comment_text` + `client`. Manual pipeline-tab generation can be triggered for Phase 1 avatars on professional subreddits, etc.
- `routes/avatar_pipeline.py:1291`: same pattern in `pipeline_regenerate`.

Result: Phase 1/2 avatars can have comments generated against subreddits they should be blocked from. The CQS "lowest" reduced-daily-limit branch in `_check_phase1` (line 289‑296) is also skipped.

**Fix:** either (a) make the gate fire on `target_subreddit` alone with a separate "no client / no text" fallback, or (b) pass `client` + `comment_text=""` from every caller. Document that the caller MUST pass them when professional.

### 5. `models/__init__.py` missing `StrategyDocument` export
`StrategyDocument` (referenced by `services/strategy_engine.py`, `routes/admin.py` 1004/3140/3171/3224/3276/3340, `tasks/strategy.py`) is never imported by `app/models/__init__.py`. Currently every consumer uses `from app.models.strategy_document import StrategyDocument` directly so this won't crash today — but Alembic's `target_metadata = Base.metadata` only sees models that have been imported. If `app.models` is imported (e.g., for autogenerate) before the first `strategy_engine` import, Alembic generates a DROP for `strategy_documents`. Same risk applies to any code that does `from app.models import StrategyDocument` (none today, but the asymmetry is a foot-gun).

**Fix:** add `from app.models.strategy_document import StrategyDocument` and `"StrategyDocument"` to `__all__`.

---

## HIGH (incorrect behaviour, broken metrics, data leaks)

### 6. `routes/pages.py` Client Hub uses legacy `RedditThread.tag` / `.composite` / `.alert`
`thread.py:39-41` marks `tag`, `alert`, `composite` as *legacy* — "canonical scores in ThreadScore". The Client Hub reads them directly:

- `_tab_overview` line 95-99: `engage_count` filters `RedditThread.tag == "engage"` — always 0 for the new pipeline.
- `_tab_threads` line 162-187: `query.filter(RedditThread.tag == tag)` and emits `t.tag`, `t.composite` in the row dict — both stale/None.
- `_tab_reports` line 240-246: groups by `RedditThread.tag` for the "threads by tag" widget.
- `threads_list` line 1147-1175: same legacy tag filter on the non-admin threads page.
- `_tab_review` line 211-212: `thread.composite`, `thread.alert` in the review row enrichment — always None for new threads.

All canonical scoring now lives in `ThreadScore` per-client. Every client-hub stat in this file is wrong for threads scored by the active pipeline.

**Fix:** join `RedditThread` to `ThreadScore` (filtered to the user's `client_id`) wherever `tag`/`composite`/`alert` is read, mirroring `services/scoring.get_client_threads_with_scores`.

### 7. `services/transparency.py:135-148` `get_pipeline_stats` — same legacy `tag` bug
```python
db.query(RedditThread.tag, sa_func.count(RedditThread.id))
  .filter(RedditThread.client_id == client_id)
  .group_by(RedditThread.tag)
```
Returns all threads as `unscored: tag_counts.get(None, 0)` because the new pipeline doesn't write to `RedditThread.tag`. Admin dashboard "tag distribution" widget will read engage=0 / monitor=0 / skip=0 / unscored=ALL.

**Fix:** same as #6 — join through `ThreadScore` and group by `ThreadScore.tag`.

### 8. `routes/pages.py` Client Hub uses legacy `ClientSubreddit` for subreddit list & counts
- `_tab_overview` line 77-79: subreddits count filters `ClientSubreddit` (legacy, comment in `subreddit.py:12` says "Legacy model — kept for migration compatibility. Use Subreddit + ClientSubredditAssignment instead.").
- `_tab_subreddits` line 119-138: returns the row list from `ClientSubreddit`.

So newly-added subreddits (which write to `ClientSubredditAssignment` per `services/admin.add_subreddit`) **never appear** in the Client Hub UI and the count is wrong.

**Fix:** query `ClientSubredditAssignment` joined to `Subreddit`.

### 9. `routes/pages.py:_tab_overview:90-93` — `threads_count` filters by `RedditThread.client_id` but shared-scrape threads have no `client_id`
`tasks/scraping.scrape_subreddit_shared:373-391` inserts `RedditThread` rows with `subreddit_id` and **no `client_id`** (subreddit-centric model). The overview counter `db.query(RedditThread).filter(RedditThread.client_id == client_id)` therefore counts zero for the entire shared-scrape pipeline (which is what `queue_tick` uses in production).

**Fix:** join through `ClientSubredditAssignment` (or `ThreadScore.client_id`) instead of relying on the denormalised `client_id` on RedditThread.

### 10. `services/strategy_engine.py:407, 423, 428` — wrong key reads from LLM result, persisted cost is always `None`
```python
strategy_doc = StrategyDocument(
    ...
    cost_usd=result.get("cost"),   # call_llm returns "cost_usd", not "cost"
)
record_activity_event(... f"... ${result.get('cost') or 0:.4f})",
                       metadata={"cost_usd": result.get("cost"), ...})
logger.info("...%.4f", result.get("cost") or 0, ...)
```
`services/ai.call_llm` returns `{content, input_tokens, output_tokens, cost_usd, duration_ms, model}` — there is no `cost` key. Every `StrategyDocument.cost_usd` is persisted as NULL; every strategy `record_activity_event` records `cost_usd=None`; every log line shows `$0.0000`.

**Fix:** `result.get("cost_usd")` everywhere.

### 11. `tasks/ai_pipeline.py:209-224` — duplicate filter loop iterates wrong set
The second pass for "log avatars excluded due to health_status" iterates `for a in avatars:` (the *unfiltered* set) and re-applies the same filters. Functionally OK, but the `cqs_level == "lowest"` warning branch (line 218) misses any avatar that was already excluded by `is_shadowbanned`/`health_status`. Minor.

### 12. `routes/pages.py:268, 292` — `User.id == user_id` where `user_id` is a raw string from `request.state`
```python
user = db.query(User).filter(User.id == user_id).first()
```
`User.id` is `UUID(as_uuid=True)`. With psycopg2 this works (the DB engine coerces), but it bypasses Python-side validation: a bogus header value lands in the WHERE clause and produces a DB error rather than the 303 redirect the dependencies in `permissions.py:56-59` are designed to give. The shared dep already does `uuid.UUID(user_id)`; these route-local helpers do not.

**Fix:** parse `uuid.UUID(user_id)` and bail on `ValueError`, mirroring `dependencies/permissions.get_current_user`.

### 13. `routes/review.py:645` (and similar) — string `client_id` filter against UUID column
`list_pending_comments(client_id: UUID | None ...)` is correct, but `pages.review_comments(client_id: str | None ...)` then does `query.filter(CommentDraft.client_id == client_id)`. The path tolerates strings via psycopg2 but a malformed value yields a DB error to the user. Consistency fix: type-annotate as `UUID | None` and let FastAPI 422 invalid input.

### 14. Phase policy uses raw subreddit name without case-normalisation, but the rest of the code lowercases
Almost every other path lowercases subreddit names before comparison (`scoring._get_all_subreddit_ids_for_scoring` line 577, `smart_scoring.get_avatar_available_subreddit_names` line 162, `avatars_query`, etc.). `services/phase._check_phase1:272` does `if target_subreddit not in hobby_subs` with no `.lower()`. Even after fixing #2, a subreddit configured as `"Python"` will not match a Reddit `display_name` of `"python"`.

**Fix:** lowercase both sides when comparing.

### 15. `services/karma_tracker.top_subreddits:409` — manufactured object passed to `get_breakdown`
```python
rows = get_breakdown(db, type("_A", (), {"id": avatar_id})())  # noqa
```
Creates a throw-away class instance with only `.id` to satisfy `get_breakdown(db, avatar)`. It works because `get_breakdown` only accesses `avatar.id`. Brittle: any future change to `get_breakdown` that touches other Avatar attrs will explode at runtime. Use `db.query(SubredditKarma).filter(SubredditKarma.avatar_id == avatar_id)...` directly.

---

## MEDIUM (logic errors, edge cases that will manifest under specific conditions)

### 16. `services/strategy_engine.generate_fallback_strategy:577` — wrong shape for affinity entries
```python
affinity = self._get_subreddit_affinity(db, avatar)  # returns {"r/foo": 12.3, ...}
good_subs = [a for a in affinity if not a.get("banned", False)]
```
`affinity` is a `dict[str, float]`; iterating it yields the keys (strings). Calling `.get("banned", False)` on a string raises `AttributeError`. The fallback strategy is therefore broken — but since it's the "API failed" branch, the main path masks it until something actually triggers it. Same loop then does `sub["subreddit"]`, `sub["karma"]`, `sub["comments"]` on strings — completely wrong type assumptions.

**Fix:** rewrite to use the affinity dict directly (`for name, score in affinity.items()`) or change `_get_subreddit_affinity` to return a list of dicts as the fallback expects.

### 17. `routes/avatar_pipeline.py:50` — `uuid.UUID(avatar.client_ids[0])` doesn't validate
`client_ids` is `ARRAY(String)`. If a stale/malformed entry is in the array, this raises `ValueError` and `_get_avatar_and_client` propagates it through every pipeline endpoint. Wrap in `try/except`.

### 18. `routes/pages.py:643-645` — `CommentDraft.client_id == client_id` where `client_id` is `str`
Same as #13 in admin review path. Compounded with: a non-admin client-scoped user gets their filter overridden if they pass a `client_id` query param (line 642-645's `elif`). Today the `not current_user.is_superuser and current_user.client_id` branch fires first so the override path is dead for client users. Still ambiguous code, easy to break in a refactor.

### 19. `services/learning.compute_edit_summary:44` — `edited_draft.split()` crashes if caller bypasses status check
The function itself returns `None` only when `ai_draft == edited_draft`. If a caller passes `edited_draft=None`, the first `if` is False (`"foo" == None`) and the next line `edited_words = edited_draft.split()` is `AttributeError`. All current callers gate by status, but the function should defend against `None` explicitly.

### 20. `services/phase.py:289-296` — CQS-lowest daily limit is `1`, but per-type limit in `services/safety.MAX_HOBBY_PER_DAY` is `5`
The two safety layers don't agree. `PhasePolicy._check_phase1` enforces the cap of 1 hobby/day for CQS-lowest, but `services/safety.check_avatar_can_post`'s Check 4 (type-specific limit) lets 5 through. As long as the phase gate runs first this is fine — but when the phase gate is skipped (#4), the more-permissive limit is the only line of defense.

### 21. `services/scoring.score_unscored_threads_for_client:644-654` returns full dict; `score_unscored_threads` legacy returns int — but if `result` is somehow not a dict, the legacy path returns the result itself (line 822-823). Defensive-but-misleading: callers (e.g. `ai_pipeline.score_threads` — wait, this one calls `smart_score_for_avatar` so unused) shouldn't fail silently. Low impact.

### 22. `services/safety.check_avatar_can_post:174` — `last_comment.created_at` may be timezone-naive in tests
`CommentDraft.created_at` is `DateTime(timezone=True)` so production rows are aware. Tests that bypass server defaults (e.g. `CommentDraft(created_at=datetime.utcnow())`) would produce naive datetimes and `(now - last_comment.created_at)` would raise `TypeError: can't subtract offset-naive...`. Not a prod bug, but a test smell.

### 23. `tasks/ai_pipeline.generate_comments:321` calls `check_avatar_can_post(db, avatar, "professional")` — see #4. In addition: brand-ratio check (Check 6) compares against `MAX_BRAND_RATIO = 0.30`, but the system_setting `max_brand_ratio_percent` (settings.py:298) is `"30"`. The constant is never overridden by the setting, so the admin UI for brand ratio is decorative.

### 24. `services/phase.PhaseEvaluator.compute_avg_comment_score:606` — uses `func.avg(reddit_score)` — returns Decimal which is fine, but `compute_comment_survival_rate` then uses `posted_at` to filter (line 565, 579). Posted drafts marked `is_deleted=True` still have non-null `posted_at`, so they're included in `total_posted` and excluded from `total_posted - deleted_count`. Algebraically correct (`(total - deleted) / total`), but if a draft is marked deleted but its `posted_at` is null, both queries miss it — survival under-reports deletion. Edge case; minor.

### 25. `models/audit.py:24` — `Index("ix_audit_log_action_created", "action", created_at.desc())` mixes string column name and column expression. Works in SQLAlchemy 2.x but inconsistent style — and the same pattern in `scrape_log.py:27` and `subreddit_karma.py:59`, `edit_record.py:67`, `analysis_edit.py:22`. Fine. Not a bug.

### 26. `services/strategy_engine.generate_strategy:341-342` — `for/else` on `range(max_retries + 1)` with `break` and a trailing `else: raise RuntimeError(...)` will never execute the else block because the loop either breaks (success) or raises inside (failure). The `else` is dead code. Minor — but the `last_error` variable then leaks.

---

## LOW (style or future-risk; no immediate impact)

### 27. `services/ai._calculate_cost:267-283` — partial match logic compares `key in model or model in key`. With long model strings that happen to contain another model's substring (e.g. an OpenRouter alias), cost is mis-attributed. Add an exact-match-first pass (already done) then a stricter prefix match.

### 28. `services/phase._record_event:1080-1084` — wraps `uuid.UUID(str(avatar.client_ids[0]))` in `try/except (TypeError, ValueError)`. Fine, but every other place treats `client_ids[0]` as a usable string directly (`services/safety.py:224`, `tasks/orchestrator.py`, etc.). Inconsistent.

### 29. `routes/pages.py:1217` `_is_htmx` is defined AFTER it's used (line 523, 1264). Python lookups at call-time so it works, but order is confusing.

### 30. `services/karma_tracker.top_subreddits` — see #15. Bad pattern, code smell.

### 31. `routes/avatar_pipeline.py:736` imports `from app.services.generation import select_persona, generate_comment, edit_comment` — `edit_comment` is imported but never called inside `pipeline_regenerate`. Wait — line 1343 *does* call it. OK, used.

### 32. `tasks/scraping.scrape_professional_subreddits:38-46` filters `ClientSubreddit` (legacy table). New onboarding writes only to `ClientSubredditAssignment`. This task is dead for new clients. If still scheduled it just no-ops; remove from Beat schedule or rewrite.

### 33. `routes/pages.py:1395` — global side effect at import time: `from starlette.requests import Request as StarletteRequest`. Trivial but unusual placement.

### 34. `services/access_control.py:14-17` — `TYPE_CHECKING` guards the `Session` import but then `check_avatar_limit(db: Session, ...)` uses `Session` as a runtime annotation. Under `from __future__ import annotations` (which is set at top) annotations are lazy strings, so this works. Fragile if anyone removes the future import.

### 35. `models/audit.AuditLog.action` length is `String(100)` — `services/safety.log_safety_event:301` writes `f"safety_{action}"` which can exceed 100 chars if `action` is long. Edge.

### 36. `services/transparency.get_pipeline_stats` uses `Decimal("0")` default, but template/JSON serialisation downstream may need `float`. Not a bug, but a footgun for the dashboard JSON encoder.

### 37. `routes/review.update_comment:150` — references local `old_status` outside the `if data.status:` block (line 85). When `data.status` is None and only `edited_draft` is changed, `old_status` is unbound and the trailing audit-log section (line 142-157) is also skipped (it's nested inside `if data.status:`), so OK in practice. Not a bug, but tightly coupled.

---

## Notes on the calibration bug

`routes/avatar_pipeline.py:779` `avatar.voice_profile_md` is correct in the current tree (matches the model). The patch is in place. Findings #1, #2, #3 are the same class of bug (JSONB-shape mismatch) and would have been caught by the same review.

---

## Suggested fix order

1. #1, #2, #3 — single shared normaliser for `hobby_subreddits` / `business_subreddits`. Add a `_normalize_sub_list(raw) -> list[str]` helper in `app/services/sanitize.py` and call it from `phase.py`, `karma_tracker.py`, and any other site that consumes the raw JSONB.
2. #4 — decide whether `check_avatar_can_post` should require all 4 args (rename + add a typed wrapper) or fall back gracefully. Today the silent skip is the worst of both worlds.
3. #6, #7, #8, #9 — Client Hub and dashboard read from legacy columns / legacy tables. One sweep through `routes/pages.py` + `services/transparency.py` to migrate every read to `ThreadScore` / `ClientSubredditAssignment`.
4. #10 — one-line key rename in `strategy_engine.py`.
5. #5 — add `StrategyDocument` to `models/__init__.py`.
6. The rest can ship in a follow-up.
