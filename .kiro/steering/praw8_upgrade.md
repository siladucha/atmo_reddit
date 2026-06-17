---
inclusion: fileMatch
fileMatchPattern: "**/services/reddit.py,**/services/praw_factory.py,**/tasks/scraping.py,**/tasks/posting.py,**/services/posting.py,**/services/health_checker.py,*pyproject.toml"
---

# PRAW 8 Upgrade — Available When Ready

## Current State
- Installed: PRAW 7.8.1
- Pinned: `praw>=7.7.0` in pyproject.toml
- No asyncpraw installed

## PRAW 8 Release Notes (relevant to RAMP)

### Useful improvements
1. **Timezone-aware datetime attrs** — `created_datetime`, `edited_datetime` on Comment/Submission. Eliminates manual `datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)` calls.
2. **`.stream` exception_handler** — streams resume gracefully on errors instead of terminating. Useful for scraping resilience.
3. **Redditor.overview** — combined comments + submissions listing. Useful for avatar profile analytics.
4. **In-memory file uploads** — bytes/file pointers for images. Useful if we add image post support.

### Breaking changes to check before upgrade
1. `reddit.user.me()` raises `ReadOnlyException` in read-only mode — verify scraping client doesn't call this.
2. `subreddit.random` removed — check we don't use it.
3. `APIException` class removed — check we don't catch it.
4. `subreddit.py` split into package — imports should be backwards-compatible but verify.

### Migration docs
- https://praw.readthedocs.io/en/stable/package_info/praw8_migration.html
- https://asyncpraw.readthedocs.io/en/stable/package_info/asyncpraw8_migration.html

## When to upgrade
- When touching reddit.py or praw_factory.py for other reasons (piggyback)
- When implementing async scraping
- When adding stream-based monitoring
- Before scaling to 50+ subreddits (exception_handler improves reliability)

## Estimated effort
1-2 hours. PRAW usage is compact (reddit.py + praw_factory.py + health_checker.py).
