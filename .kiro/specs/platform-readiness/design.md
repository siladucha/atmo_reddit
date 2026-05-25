# Design Document — Platform Readiness MVP

## Overview

MVP scope of Platform Readiness — focused on what's needed to safely run the first paid pilot without getting detected by Reddit anti-spam systems. The full spec has 12 requirements across 3 subsystems (jitter, subreddit intelligence, context assembly). For MVP, we implement **only timing jitter** (Requirements 1-3) and defer subreddit intelligence + context assembly to Phase 2.

**Rationale:** Context isolation is already done (runtime assertions exist). Subreddit intelligence is nice-to-have for first 3 clients. But timing jitter is a **detection risk** — fixed intervals create patterns that Reddit's anti-spam can flag. This is the only P0 blocker.

## MVP Scope

| Requirement | Status | MVP? |
|-------------|--------|------|
| Req 1: Comment Timing Jitter | **This sprint** | ✅ |
| Req 2: Scraping Interval Jitter | **This sprint** | ✅ |
| Req 3: Per-Avatar Daily Activity Jitter | **This sprint** | ✅ |
| Req 4-7: Subreddit Intelligence | Deferred | ❌ Phase 2 |
| Req 8-9: Context Assembly | Deferred (already have runtime assertions) | ❌ Phase 2 |
| Req 10: Conversation Memory | Deferred | ❌ Phase 2 |
| Req 11: Subreddit Knowledge Store | Deferred | ❌ Phase 2 |
| Req 12: Backward Compatibility | Applies to jitter only | ✅ |

## Architecture

### Jitter Service

```python
# app/services/jitter.py

import secrets
import hashlib
from dataclasses import dataclass

@dataclass
class TimingWindow:
    """Bounded range for randomized delay sampling."""
    min_minutes: float
    max_minutes: float

    def sample(self, seed: bytes | None = None) -> float:
        """Sample a random delay within the window.
        
        Uses secrets.randbelow (CSPRNG) for production.
        Uses seeded PRNG for testing when seed is provided.
        """
        if seed is not None:
            # Deterministic for testing
            h = int(hashlib.sha256(seed).hexdigest(), 16)
            ratio = (h % 10000) / 10000.0
        else:
            # Cryptographically secure for production
            range_ms = int((self.max_minutes - self.min_minutes) * 1000)
            if range_ms <= 0:
                return self.min_minutes
            ratio = secrets.randbelow(range_ms) / range_ms
        
        return self.min_minutes + ratio * (self.max_minutes - self.min_minutes)


# Pre-configured windows (overridable via SystemSettings)
COMMENT_GAP_WINDOW = TimingWindow(min_minutes=12, max_minutes=45)
SCRAPE_INTERVAL_WINDOW = TimingWindow(min_minutes=55, max_minutes=90)
COLD_START_WINDOW = TimingWindow(min_minutes=0, max_minutes=5)
ACTIVITY_START_WINDOW = TimingWindow(min_minutes=7*60, max_minutes=11*60)  # 07:00-11:00 in minutes
ACTIVITY_END_WINDOW = TimingWindow(min_minutes=20*60, max_minutes=23*60+59)  # 20:00-23:59


def get_comment_delay(avatar_id: UUID | None = None, seed: bytes | None = None) -> float:
    """Get randomized delay between comments for an avatar.
    
    Returns minutes. Each call produces an independent sample.
    Drop-in replacement for MIN_MINUTES_BETWEEN_COMMENTS constant.
    """
    window = _load_comment_window()  # from SystemSettings or default
    return window.sample(seed)


def get_next_scrape_offset(subreddit_id: UUID | None = None, seed: bytes | None = None) -> float:
    """Get randomized offset for next scrape time.
    
    Returns minutes to add to last_scraped_at.
    """
    window = _load_scrape_window()
    return window.sample(seed)


def get_cold_start_offset(seed: bytes | None = None) -> float:
    """Get staggered offset for first-ever scrape (0-5 minutes)."""
    return COLD_START_WINDOW.sample(seed)


def compute_daily_activity_window(avatar_id: UUID, date: date, seed: bytes | None = None) -> tuple[int, int]:
    """Compute randomized daily activity window for an avatar.
    
    Returns (start_hour, end_hour) in UTC.
    Guarantees window is at least 8 hours wide.
    Uses avatar_id + date as implicit seed for day-to-day variation.
    """
    if seed is None:
        # Derive seed from avatar_id + date for reproducible daily windows
        seed = f"{avatar_id}:{date.isoformat()}".encode()
    
    start_minutes = ACTIVITY_START_WINDOW.sample(seed + b":start")
    end_minutes = ACTIVITY_END_WINDOW.sample(seed + b":end")
    
    start_hour = int(start_minutes // 60)
    end_hour = int(end_minutes // 60)
    
    # Guarantee minimum 8-hour window
    if end_hour - start_hour < 8:
        end_hour = start_hour + 8
        if end_hour > 23:
            start_hour = max(7, end_hour - 16)  # shift start earlier
    
    return (start_hour, min(end_hour, 23))


def is_within_activity_window(avatar_id: UUID, current_hour: int, date: date) -> tuple[bool, str]:
    """Check if current hour is within avatar's daily activity window.
    
    Returns (is_active, reason).
    """
    start, end = compute_daily_activity_window(avatar_id, date)
    if start <= current_hour <= end:
        return (True, "")
    return (False, f"Outside activity window ({start}:00-{end}:00 UTC). Resumes at {start}:00.")
```

### Integration Points

#### 1. Comment Gap (replaces fixed constant)

**Current code** (`services/safety.py` or `services/rate_limiter.py`):
```python
MIN_MINUTES_BETWEEN_COMMENTS = 15  # fixed
```

**After:**
```python
from app.services.jitter import get_comment_delay

# In the rate check function:
min_gap = get_comment_delay(avatar_id=avatar.id)
# Use min_gap instead of fixed constant
```

#### 2. Scraping Interval (replaces fixed interval)

**Current code** (`tasks/queue_ticker.py`):
```python
# Checks if subreddit is due based on fixed scrape_freshness_window_hours
```

**After:**
```python
from app.services.jitter import get_next_scrape_offset

# When determining if subreddit is due:
next_scrape_offset = get_next_scrape_offset(subreddit_id=sub.id)
# Compare last_scraped_at + offset vs now
```

#### 3. Daily Activity Window (new gate in pipeline)

**Integration in** `tasks/ai_pipeline.py` or `services/pre_filter.py`:
```python
from app.services.jitter import is_within_activity_window
from datetime import datetime, timezone, date

# Before generating for an avatar:
now = datetime.now(timezone.utc)
is_active, reason = is_within_activity_window(avatar.id, now.hour, now.date())
if not is_active:
    logger.info(f"Avatar {avatar.name} skipped: {reason}")
    continue  # Skip this avatar for now
```

### SystemSettings Configuration

| Setting | Group | Default | Description |
|---------|-------|---------|-------------|
| `jitter_comment_min_minutes` | jitter | 12 | Minimum gap between comments (minutes) |
| `jitter_comment_max_minutes` | jitter | 45 | Maximum gap between comments (minutes) |
| `jitter_scrape_min_minutes` | jitter | 55 | Minimum scrape interval (minutes) |
| `jitter_scrape_max_minutes` | jitter | 90 | Maximum scrape interval (minutes) |
| `jitter_activity_start_min_hour` | jitter | 7 | Earliest activity start (UTC hour) |
| `jitter_activity_start_max_hour` | jitter | 11 | Latest activity start (UTC hour) |
| `jitter_activity_end_min_hour` | jitter | 20 | Earliest activity end (UTC hour) |
| `jitter_activity_end_max_hour` | jitter | 23 | Latest activity end (UTC hour) |

### Logging

All jitter decisions logged at DEBUG level for operational visibility:
```
[DEBUG] jitter: avatar=DrCyberNinja comment_delay=23.4min (window 12-45)
[DEBUG] jitter: subreddit=r/netsec next_scrape_offset=67.2min (window 55-90)
[DEBUG] jitter: avatar=DrCyberNinja activity_window=08:00-21:00 UTC (date=2026-05-22)
[INFO]  jitter: avatar=DrCyberNinja BLOCKED outside activity window (resumes 08:00 UTC)
```

## Security Considerations

- CSPRNG (`secrets` module) for production randomness — not predictable
- Deterministic mode (seed parameter) only for testing — never exposed in production
- Activity windows derived from avatar_id + date — same avatar gets same window on same day (consistent behavior, but varies day-to-day)
- No external dependencies — pure Python implementation

## Backward Compatibility

- `get_comment_delay()` returns a float (minutes) — drop-in replacement for the constant
- If SystemSettings keys don't exist, defaults are used (no migration required for existing deployments)
- Existing pipeline logic unchanged — jitter is additive (wraps existing checks)
- No model changes, no migrations needed
- Feature can be disabled by setting min=max in SystemSettings (effectively fixed interval)

## Testing Strategy

- Unit tests with explicit seeds → deterministic, reproducible
- Property: sampled value always within [min, max]
- Property: independent samples (no correlation between consecutive calls)
- Property: activity window always ≥ 8 hours
- Property: deterministic with same seed
- Integration: verify pipeline skips avatars outside activity window
