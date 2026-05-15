# Full Technical & Logic Audit — Reddit SaaS Backend

## Objective

Perform a comprehensive code audit of the `reddit_saas/app/` directory. Find ALL technical bugs, logic errors, attribute mismatches, broken references, dead code paths, and runtime failures. This is a production system about to go live — every bug matters.

## Scope

Audit the following directories exhaustively:
- `reddit_saas/app/models/` — all 25 model files
- `reddit_saas/app/services/` — all 53 service files
- `reddit_saas/app/tasks/` — all 12 task files
- `reddit_saas/app/routes/` — all 13 route files
- `reddit_saas/app/dependencies/` — permission guards
- `reddit_saas/app/schemas/` — Pydantic validation schemas
- `reddit_saas/app/config.py`, `database.py`, `main.py`, `seed.py`

## What to Check (Exhaustive Checklist)

### 1. Attribute & Column Mismatches (CRITICAL — we already found one)

We found `avatar.voice_profile` used in `routes/avatar_pipeline.py` but the model has `voice_profile_md`. This class of bug is the #1 priority.

For EVERY model access in services, routes, and tasks:
- Verify the attribute name exists on the SQLAlchemy model
- Check for typos, old names, renamed columns that weren't updated everywhere
- Check `.client_id` vs `.client_ids` (Avatar uses `client_ids` as ARRAY)
- Check `.is_active` vs `.active` (Avatar uses `active`, Client uses `is_active`)
- Check `.id` types (UUID vs string) — ensure no string comparison against UUID
- Check JSONB field access (e.g., `client.keywords["high"]` — is it accessed correctly?)

### 2. Import Errors & Missing References

- Circular imports (especially between models, services, and tasks)
- Imports inside functions (lazy imports) — verify the imported module/class actually exists
- `from app.models.X import Y` — verify Y is defined in X
- Services importing other services — check for missing functions

### 3. SQLAlchemy Query Bugs

- `.filter(Model.column == value)` where column doesn't exist
- Missing `await` on async session operations (if any async code exists)
- `.first()` vs `.scalar()` vs `.one()` misuse
- Queries that don't handle `None` results before accessing attributes
- Missing `.all()` or `.scalars().all()` on queries that expect lists
- `session.execute(select(...))` without proper result extraction
- Incorrect join conditions (wrong FK references)

### 4. Celery Task Issues

- Tasks referencing models/services that don't exist
- Missing `bind=True` on tasks that use `self.retry()`
- Incorrect `countdown` calculations
- Tasks that open DB sessions but don't close them on exception
- Race conditions between tasks (e.g., two tasks modifying same avatar)
- Kill switch checks — verify the setting name matches what's in the DB

### 5. Route/Endpoint Bugs

- Template names that don't exist in `templates/` directory
- Context variables passed to templates that aren't used or are misspelled
- Missing `Depends()` for auth/permission guards
- HTMX endpoints returning wrong content type
- Path parameters not matching function signatures
- Missing error handling (bare `.first()` followed by attribute access without None check)

### 6. Business Logic Errors

- Phase checks: verify `warming_phase == 0` (Mentor) is excluded from ALL automated pipelines
- Frozen avatar checks: verify `is_frozen == True` skips ALL generation/scoring/posting
- Client `is_active == False` checks: verify inactive clients are skipped everywhere
- Kill switch logic: `pipeline_enabled`, `generation_enabled`, `scrape_enabled` — are they checked consistently?
- RBAC: verify permission guards match the documented permission matrix
- Learning loop: verify `capture_edit_record` is called on ALL review actions (approve/reject/edit) in BOTH `routes/review.py` AND `routes/pages.py`
- Thread liveness: verify locked threads are skipped at scraping, scoring, AND generation stages
- Avatar health exclusion: verify shadowbanned/suspended avatars are filtered BEFORE LLM calls

### 7. Data Type Mismatches

- UUID vs string comparisons (SQLAlchemy UUID columns compared with string literals)
- Integer vs string for `warming_phase` (model is Integer, check if any code compares with string "0")
- Boolean vs truthy checks (e.g., `if avatar.is_frozen` vs `if avatar.is_frozen == True`)
- JSONB fields: are they accessed as dict or do they need `.get()` safety?
- ARRAY fields: `client_ids` is `ARRAY(String)` — check if code does `avatar.client_ids == client_id` instead of `client_id in avatar.client_ids` or `.contains()`

### 8. Error Handling Gaps

- Bare `except:` or `except Exception:` that swallow important errors
- Missing try/except around external API calls (Reddit, LLM)
- Functions that return `None` on error but callers don't check
- Database operations without rollback on failure

### 9. Configuration & Settings

- `config.py` settings referenced in code but not defined in config
- Environment variables used but not in `.env.example`
- Default values that are clearly wrong (e.g., `default=0` for something that should be `1`)
- Settings accessed via `get_config()` — verify attribute names match

### 10. Concurrency & Race Conditions

- Distributed locks: verify lock key naming is consistent
- Rate limiter: verify it actually blocks when limit is reached
- Multiple Celery workers: can two workers process the same subreddit/avatar simultaneously?
- DB session sharing between threads (should NOT happen)

## Output Format

Produce a structured report with:

```markdown
## CRITICAL (will crash in production)
1. **File:** `path/to/file.py`, **Line:** N
   **Bug:** Description
   **Fix:** What to change

## HIGH (incorrect behavior, data corruption risk)
1. ...

## MEDIUM (logic errors, edge cases)
1. ...

## LOW (code quality, potential future issues)
1. ...
```

## Methodology

1. Start by reading ALL model files to build a complete attribute map
2. Then systematically read each service file and cross-reference every model attribute access
3. Then read each task file and verify service function calls match actual signatures
4. Then read each route file and verify template names, context vars, and service calls
5. Check `config.py` for all settings and verify they're used correctly
6. Check `seed.py` for model instantiation correctness

## Known Bug (already fixed, use as calibration)

- `routes/avatar_pipeline.py` line 779: `avatar.voice_profile` → should be `avatar.voice_profile_md`
- This was caught because it crashed on the production server. Find ALL similar bugs.

## Important Context

- Avatar model: `active` (not `is_active`), `client_ids` (ARRAY, not `client_id`), `voice_profile_md` (not `voice_profile`)
- Client model: `is_active`, `keywords` (JSONB with high/medium/low keys)
- User model: has `role` field (UserRole enum), `client_id` (nullable, for client-scoped users)
- CommentDraft: `status` field with workflow `pending → approved/rejected → posted`
- Thread: `is_locked`, `locked_detected_at`
- All IDs are UUID (PostgreSQL UUID type)
- Timezone: Asia/Jerusalem everywhere

## Execution Rules

- Do NOT ask for permission to read files, run grep, or any other read-only operation. Just do it.
- Do NOT ask "should I continue?" — continue until the full audit is complete.
- Do NOT pause between steps. Read all files, cross-reference, and produce the final report in one go.
- You have full permission to read any file in this repository. No confirmation needed.
- If you need to run `grep`, `find`, or `cat` to verify something — just run it.

## Do NOT

- Do not suggest style improvements or refactoring
- Do not suggest adding tests
- Do not suggest documentation changes
- Focus ONLY on bugs that will cause runtime errors, incorrect behavior, or data corruption
- Do not fix anything — only report findings
