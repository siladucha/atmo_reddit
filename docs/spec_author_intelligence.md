# Spec: Author Intelligence

## Summary

Enrich Reddit thread authors with profile data (karma, active subreddits, account age) to help operators assess engagement quality and identify high-value conversation partners.

## Problem

Currently `author` is a plain string from scraping. The operator has no way to know:
- Is this a real active user or a throwaway?
- Does this person have authority in the subreddit (high karma)?
- What other communities are they active in (potential cross-posting opportunity)?
- Is it worth engaging with this author or will the comment be buried?

## User Stories

1. As an operator, I want to see author karma next to their name in the threads table so I can prioritize engaging with high-karma authors (more visibility for our comment).
2. As an operator, I want to click an author and see their top subreddits so I can understand if they're a good fit for our client's niche.
3. As an operator, I want to see account age so I can avoid engaging with brand-new throwaway accounts.

## Data Model

### New table: `reddit_authors`

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | PK |
| username | VARCHAR(255) | Reddit username (unique, indexed) |
| karma_comment | INTEGER | Comment karma |
| karma_post | INTEGER | Post karma |
| account_created_at | TIMESTAMP | Reddit account creation date |
| top_subreddits | JSONB | Top 10 subreddits by activity `[{"name": "cybersecurity", "karma": 450}, ...]` |
| is_suspended | BOOLEAN | Account suspended by Reddit |
| is_deleted | BOOLEAN | Account deleted |
| fetched_at | TIMESTAMP | When we last fetched this data |
| created_at | TIMESTAMP | Row creation time |

### Indexes
- `UNIQUE(username)`
- `ix_reddit_authors_fetched_at` — for staleness queries

### Staleness policy
- Re-fetch if `fetched_at` > 7 days ago
- Never fetch for `[deleted]` or `AutoModerator`

## API / Service Layer

### `app/services/author_intel.py`

```python
def get_author_profile(db, username: str) -> dict | None:
    """Return cached author profile or None if not yet fetched."""

def fetch_author_profile(db, username: str) -> dict:
    """Fetch from Reddit API (PRAW), cache in DB, return profile dict."""

def bulk_enrich_authors(db, usernames: list[str]) -> dict[str, dict]:
    """Batch-fetch profiles for multiple authors. Rate-limited (2s between calls)."""
```

### Reddit API calls (PRAW)
```python
redditor = reddit.redditor(username)
# Fields: redditor.link_karma, redditor.comment_karma, redditor.created_utc
# Top subreddits: redditor.top_subreddits() — may not be available for all users
# Fallback: parse from redditor.comments.new(limit=100) → count by subreddit
```

### Rate limiting
- Max 1 author fetch per 2 seconds (Reddit API courtesy)
- Batch enrichment runs as background task, not blocking UI
- Budget: ~30 authors/minute

## UI Changes

### Threads table (`/admin/threads`)
- Author column shows: `username` + small karma badge `↑1.2k`
- If author not yet enriched: show username only (no badge)
- Tooltip on hover: account age, top 3 subreddits

### Author detail popover (click on author name)
- Small modal/popover with:
  - Username, karma (comment + post), account age
  - Top 10 subreddits with karma per sub
  - Link to Reddit profile (external)
  - "Last fetched: X days ago" + "Refresh" button

### Admin route
- `GET /admin/authors/{username}` — detail page or JSON
- `POST /admin/authors/{username}/refresh` — force re-fetch

## Background Task

### `enrich_thread_authors` (Celery task)
- Triggered after scraping completes
- Takes all unique authors from new threads
- Skips already-enriched (fetched < 7 days ago)
- Fetches remaining, rate-limited
- Runs in background, doesn't block pipeline

### Scheduler addition
```python
"author-enrichment": {
    "task": "enrich_new_authors",
    "schedule": crontab(hour="*/6", minute=45),  # Every 6h
}
```

## Scoring Integration (Future)

Once author data is available, scoring can use it:
- Prefer threads by high-karma authors (comment gets more visibility)
- Avoid threads by suspended/deleted accounts
- Boost threads where author is active in client's target subreddits

This is a scoring model change — separate from this spec.

## Migration

```
alembic revision --autogenerate -m "add_reddit_authors_table"
```

## Effort Estimate

| Component | Effort |
|-----------|--------|
| Model + migration | 30 min |
| Service (fetch + cache) | 1h |
| Background task | 30 min |
| UI (badge + popover) | 1.5h |
| Tests | 1h |
| **Total** | **~4.5h** |

## Dependencies

- PRAW (already installed)
- Reddit API credentials (already configured)
- No new external services needed

## Priority

Medium. Not blocking for pilot, but valuable for:
- Better engagement targeting (comment on posts by influential users)
- Avoiding wasted effort (skip throwaway accounts)
- Client reporting ("we engaged with users totaling X karma")

## Out of Scope

- Author sentiment analysis
- Author relationship mapping (who replies to whom)
- Cross-client author deduplication
- Author blocklist/allowlist (future feature)
