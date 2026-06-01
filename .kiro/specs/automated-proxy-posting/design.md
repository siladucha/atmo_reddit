# Design Document: Automated Proxy Posting

## Overview

This document describes the technical design for the automated proxy posting system — a feature that takes human-approved comment drafts from the EPG pipeline and posts them to Reddit automatically via PRAW with per-avatar OAuth credentials, proxy routing, and timing jitter.

## Architecture

The automated proxy posting system extends the existing EPG pipeline to execute approved comment posts to Reddit without manual intervention. It introduces per-avatar OAuth credentials, dedicated residential proxy routing, timing jitter, and comprehensive safety gates.

**Data flow:**
```
EPG Slot (approved) → Celery Beat (every 5 min) → execute_pending_posts
  → per-slot post_comment task → safety gates → timing check
  → PRAW client (proxy + OAuth) → Reddit API → audit log
```

The system integrates with existing infrastructure:
- **Celery Beat** dispatches the `execute_pending_posts` periodic task
- **Redis distributed locks** prevent concurrent posting for the same avatar
- **SystemSetting** provides the global kill switch (`auto_posting_enabled`)
- **EPG slots** drive the posting schedule (status: `approved` → `posted`)
- **Activity events** provide transparency/audit trail

---

## Components and Interfaces

### 1. Reddit App Registry (`models/reddit_app.py`)

Stores registered Reddit OAuth applications, scoped to a specific client or to the shared pool.

```python
class RedditApp(Base):
    __tablename__ = "reddit_apps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)  # NULL = shared pool
    client_id_reddit: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # Reddit's OAuth client_id
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    app_name: Mapped[str] = mapped_column(String(255), nullable=False)
    registered_under_username: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")  # healthy | suspect | revoked | unknown
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**Client scoping rules:**
- `client_id IS NOT NULL` → app belongs to that client. Only that client's avatars may use it.
- `client_id IS NULL` → shared pool app. Only farm/unassigned avatars may use it.
- Constraint enforced at service layer (assignment validation) and documented in admin UI.

### 2. Avatar Model Extensions

New fields on the existing `Avatar` model:

```python
# Proxy & fingerprint
proxy_url_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
user_agent_string: Mapped[str | None] = mapped_column(String(500), nullable=True)
declared_timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")

# Posting control
posting_mode: Mapped[str] = mapped_column(String(20), default="disabled")  # auto | disabled
reddit_app_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reddit_apps.id"), nullable=True)
refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
reddit_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # MVP: password auth

# Posting state
last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
last_posted_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
consecutive_post_failures: Mapped[int] = mapped_column(Integer, default=0)
```

### 3. Posting Events Audit Table (`models/posting_event.py`)

```python
class PostingEvent(Base):
    __tablename__ = "posting_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("comment_drafts.id"), nullable=True)
    epg_slot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("epg_slots.id"), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip_used: Mapped[str | None] = mapped_column(String(45), nullable=True)
    proxy_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256
    user_agent_used: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reddit_comment_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reddit_comment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failure | skipped
```

### 4. Encryption Service (`services/encryption.py`)

Encrypts sensitive fields (refresh tokens, proxy credentials) at rest using Fernet symmetric encryption.

```python
from cryptography.fernet import Fernet

class FieldEncryptor:
    """Encrypts/decrypts sensitive model fields using Fernet (AES-128-CBC)."""

    def __init__(self, key: str):
        """Key sourced from FIELD_ENCRYPTION_KEY env var."""
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string, return base64 ciphertext."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext string, return plaintext."""
        return self._fernet.decrypt(ciphertext.encode()).decode()
```

Key management: `FIELD_ENCRYPTION_KEY` stored in `.env`, generated via `Fernet.generate_key()`. Added to `Settings` as a bootstrap key.

### 5. Posting Service (`services/posting.py`)

Core orchestration service for executing a single post.

```python
def execute_post(db: Session, epg_slot_id: uuid.UUID) -> PostingEvent:
    """Execute a single automated post for an EPG slot.

    Steps:
    1. Load slot + avatar + draft + reddit_app
    2. Run safety gates (kill switch, mode, frozen, health, phase, daily limit)
    3. Verify fingerprint consistency (IP, user-agent)
    4. Build authenticated PRAW client with proxy
    5. Submit comment via PRAW
    6. Update state (draft, slot, avatar)
    7. Record PostingEvent audit record

    Returns PostingEvent with outcome.
    Raises PostingRefused if safety gates fail.
    """
```

### 6. PRAW Client Factory (`services/praw_factory.py`)

Constructs per-avatar authenticated PRAW clients with proxy routing. Supports both auth modes.

```python
import praw
import requests

def create_avatar_reddit_client(
    avatar: Avatar,
    reddit_app: RedditApp,
    encryptor: FieldEncryptor,
) -> praw.Reddit:
    """Create an authenticated PRAW client routed through the avatar's proxy.

    Supports two auth modes:
    - Password auth (MVP): uses avatar.reddit_username + avatar.reddit_password_encrypted
    - OAuth auth (upgrade): uses avatar.refresh_token_encrypted

    Uses requestor_kwargs to inject a custom requests.Session with:
    - Proxy configuration (SOCKS5 or HTTP)
    - Custom User-Agent header
    - Connection timeouts (30s connect, 60s read)
    """
    proxy_url = encryptor.decrypt(avatar.proxy_url_encrypted)
    client_secret = encryptor.decrypt(reddit_app.client_secret_encrypted)

    session = requests.Session()
    session.proxies = {"https": proxy_url, "http": proxy_url}
    session.headers["User-Agent"] = avatar.user_agent_string

    # OAuth mode (per-avatar refresh_token)
    if avatar.refresh_token_encrypted:
        refresh_token = encryptor.decrypt(avatar.refresh_token_encrypted)
        reddit = praw.Reddit(
            client_id=reddit_app.client_id_reddit,
            client_secret=client_secret,
            refresh_token=refresh_token,
            user_agent=avatar.user_agent_string,
            requestor_kwargs={"session": session},
        )
    # Password auth mode (MVP — uses existing script app)
    elif avatar.reddit_password_encrypted:
        password = encryptor.decrypt(avatar.reddit_password_encrypted)
        reddit = praw.Reddit(
            client_id=reddit_app.client_id_reddit,
            client_secret=client_secret,
            username=avatar.reddit_username,
            password=password,
            user_agent=avatar.user_agent_string,
            requestor_kwargs={"session": session},
        )
    else:
        raise PostingConfigError(f"Avatar {avatar.reddit_username} has no auth credentials (no refresh_token, no password)")

    return reddit
```

### 7. Timing Engine (`services/timing_engine.py`)

Calculates jittered posting times respecting all constraints.

```python
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ACTIVE_HOURS_START = 8   # 08:00 local
ACTIVE_HOURS_END = 23    # 23:00 local
SLEEP_HOURS_START = 0    # 00:00 local
SLEEP_HOURS_END = 7      # 07:00 local
MIN_INTERVAL_MINUTES = 45
MAX_INTERVAL_MINUTES = 90
JITTER_FACTOR = 0.30
PEAK_HOURS = [(12, 14), (18, 22)]

# Phase-based daily limits (from PhasePolicy)
PHASE_DAILY_LIMITS = {
    0: 0,   # Mentor — excluded from pipeline
    1: 3,   # Hobby only (CQS "lowest": 1)
    2: 7,   # Hobby + professional
    3: 18,  # Full brand integration
}

def get_effective_daily_cap(
    avatar: Avatar,
    auto_posting_daily_cap: int = 8,
) -> int:
    """Calculate effective daily posting cap for an avatar.

    Returns min(phase_daily_limit, auto_posting_daily_cap).
    The auto_posting_daily_cap is a system setting (default 8) that acts
    as a safety ceiling regardless of phase.
    """
    phase_limit = PHASE_DAILY_LIMITS.get(avatar.warming_phase, 0)
    if avatar.warming_phase == 1 and avatar.cqs_level == "lowest":
        phase_limit = 1
    return min(phase_limit, auto_posting_daily_cap)

def calculate_jittered_time(
    scheduled_at: datetime,
    interval_minutes: float,
    avatar_timezone: str,
) -> datetime:
    """Apply ±30% jitter to scheduled time, clamped to active hours.

    Uses secrets.randbelow() for cryptographically secure randomness.
    """

def get_next_valid_posting_time(
    avatar_id: uuid.UUID,
    scheduled_at: datetime,
    avatar_timezone: str,
    last_posted_at: datetime | None,
    db: Session,
) -> datetime | None:
    """Calculate next valid posting time respecting all constraints.

    Returns None if effective daily cap reached or no valid window today.
    """
```

### 8. Safety Gates (`services/posting_safety.py`)

Pre-posting validation checks consolidated into a single gate function.

```python
@dataclass
class SafetyResult:
    allowed: bool
    reason: str = ""

def check_posting_safety(
    db: Session,
    avatar: Avatar,
    epg_slot: EPGSlot,
) -> SafetyResult:
    """Run all pre-posting safety checks.

    Checks (in order):
    1. Global kill switch (auto_posting_enabled)
    2. Avatar posting_mode == 'auto'
    3. Avatar not frozen
    4. Avatar health_status not in (shadowbanned, suspended)
    5. Phase policy (phase 0 excluded, phase 1 hobby-only, phase 2 no brand, phase 3 with ratio)
    6. Daily post count < effective cap (min(phase_limit, auto_posting_daily_cap))
    7. Proxy URL configured and non-empty
    8. User-agent string configured and non-empty
    9. IP subnet consistency (resolved IP in same /24 as last_posted_ip)
    """
```

### 9. Celery Tasks (`tasks/posting.py`)

```python
from app.tasks.worker import celery_app

@celery_app.task(name="execute_pending_posts")
def execute_pending_posts():
    """Periodic task (every 5 min): find approved slots due for posting, dispatch tasks."""

@celery_app.task(name="post_comment", bind=True, max_retries=3, default_retry_delay=60)
def post_comment(self, epg_slot_id: str):
    """Execute a single comment post with retry on transient errors.

    Acquires Redis distributed lock per avatar before posting.
    Exponential backoff: 60s × 2^attempt.
    """
```

## Data Models

### New Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `reddit_apps` | OAuth app registry | client_id, client_secret_encrypted, app_name, is_active |
| `posting_events` | Audit trail | avatar_id, draft_id, ip_used, proxy_url_hash, outcome, duration_ms |

### Modified Tables

| Table | New Fields | Purpose |
|-------|-----------|---------|
| `avatars` | proxy_url_encrypted, user_agent_string, declared_timezone, posting_mode, reddit_app_id, refresh_token_encrypted, last_posted_at, last_posted_ip, consecutive_post_failures | Per-avatar posting config & state |
| `epg_slots` | (no schema change — uses existing status lifecycle) | Status transitions: approved → posted |
| `comment_drafts` | (no schema change — uses existing posted_at, reddit_comment_url) | Updated on successful post |

### Encryption Strategy

| Field | Storage | Encryption |
|-------|---------|-----------|
| `reddit_apps.client_secret_encrypted` | Text (base64 Fernet ciphertext) | Fernet AES-128-CBC |
| `avatars.proxy_url_encrypted` | Text (base64 Fernet ciphertext) | Fernet AES-128-CBC |
| `avatars.refresh_token_encrypted` | Text (base64 Fernet ciphertext) | Fernet AES-128-CBC |
| `avatars.reddit_password_encrypted` | Text (base64 Fernet ciphertext) | Fernet AES-128-CBC |
| `posting_events.proxy_url_hash` | String(64) — SHA-256 hex | One-way hash (correlation only) |

Key: `FIELD_ENCRYPTION_KEY` in `.env`, generated via `cryptography.fernet.Fernet.generate_key()`.

---

## Error Handling

### Error Classification

| Error Type | Action | Retry? |
|-----------|--------|--------|
| 401 Unauthorized | Freeze avatar (`auth_error: 401`) | No |
| 403 Forbidden | Freeze avatar (`auth_error: 403`) | No |
| Account suspended/banned | Freeze avatar (`account_suspended`) | No |
| Network timeout | Retry with backoff | Yes (3x) |
| 500/502/503 | Retry with backoff | Yes (3x) |
| Proxy connection refused | Log + retry | Yes (3x) |
| Rate limited (429) | Retry after `Retry-After` header | Yes (3x) |
| All retries exhausted | Skip slot (`posting_failed_after_retries`) | No |
| 3 consecutive failures (24h) | Freeze avatar (`consecutive_failures`) | No |

### Retry Strategy

```python
# Exponential backoff: 60s × 2^attempt
# Attempt 1: retry after 60s
# Attempt 2: retry after 120s
# Attempt 3: retry after 240s
# After attempt 3: mark slot as skipped, increment consecutive_post_failures
```

### Credential Redaction

All logging of proxy URLs redacts credentials:
- `socks5://user:pass@1.2.3.4:1080` → `socks5://***:***@1.2.3.4:1080`
- Used in error messages, PostingEvent.error_message, and application logs

---

## Celery Integration

### Beat Schedule Addition

```python
"execute-pending-posts": {
    "task": "execute_pending_posts",
    "schedule": 300.0,  # Every 5 minutes
},
```

### Task Flow

```
execute_pending_posts (periodic, every 5 min)
  │
  ├─ Query: EPG slots WHERE status='approved' AND scheduled_at <= now()
  │
  ├─ For each slot:
  │   └─ Dispatch: post_comment.delay(epg_slot_id=str(slot.id))
  │
  └─ (exits — individual tasks handle execution)

post_comment (per-slot task, bind=True, max_retries=3)
  │
  ├─ Acquire Redis lock: posting_lock:{avatar_id} (TTL=300s)
  │   └─ If locked: retry after 60s (another post in progress)
  │
  ├─ Safety gates → refuse if any fail
  │
  ├─ Build PRAW client (proxy + OAuth)
  │
  ├─ Resolve proxy IP → verify subnet consistency (/24)
  │
  ├─ Submit comment (submission.reply or comment.reply)
  │
  ├─ On success:
  │   ├─ Update draft (status=posted, posted_at, reddit_comment_url)
  │   ├─ Update slot (status=posted, posted_at)
  │   ├─ Update avatar (last_posted_at, last_posted_ip, consecutive_post_failures=0)
  │   └─ Create PostingEvent (outcome=success)
  │
  ├─ On auth error (401/403/suspended):
  │   ├─ Freeze avatar
  │   ├─ Create PostingEvent (outcome=failure)
  │   └─ Do NOT retry
  │
  ├─ On transient error:
  │   ├─ Create PostingEvent (outcome=failure, attempt_number)
  │   ├─ Increment consecutive_post_failures
  │   └─ self.retry(countdown=60 * 2**self.request.retries)
  │
  └─ Release Redis lock
```

### Distributed Lock

Uses the same pattern as `ScrapeDistributedLock` but with a different key prefix:

```python
KEY_PREFIX = "posting_lock:"
DEFAULT_TTL = 300  # 5 minutes — enough for one post + retries
```

---

## Proxy IP Resolution

To verify IP subnet consistency, the system resolves the proxy's exit IP before posting:

```python
import ipaddress

def resolve_proxy_ip(proxy_url: str, timeout: int = 10) -> str | None:
    """Resolve the exit IP of a proxy by making a request to an IP echo service.

    Uses httpbin.org/ip or ipify.org as the echo endpoint.
    Returns the IP string or None on failure.
    """
    session = requests.Session()
    session.proxies = {"https": proxy_url, "http": proxy_url}
    response = session.get("https://api.ipify.org", timeout=timeout)
    return response.text.strip()

def is_same_subnet(ip1: str, ip2: str, prefix_length: int = 24) -> bool:
    """Check if two IPs are in the same /24 subnet.

    Allows normal residential proxy IP rotation within the same provider block.
    Returns True if both IPs share the same /24 prefix.
    """
    net1 = ipaddress.ip_network(f"{ip1}/{prefix_length}", strict=False)
    net2 = ipaddress.ip_network(f"{ip2}/{prefix_length}", strict=False)
    return net1 == net2
```

This is called before the first post (to establish `last_posted_ip`) and on subsequent posts to verify subnet consistency. The /24 subnet check allows for normal IP rotation within the same residential proxy provider while detecting suspicious changes (different ISP, different country).

---

## Timing Engine Details

### Jitter Calculation

```python
def calculate_jittered_time(scheduled_at, interval_minutes, avatar_timezone):
    # 1. Calculate jitter range: ±30% of interval
    max_jitter = interval_minutes * JITTER_FACTOR
    # 2. Generate cryptographically secure random offset
    jitter_seconds = secrets.randbelow(int(max_jitter * 60 * 2)) - int(max_jitter * 60)
    # 3. Apply jitter
    jittered = scheduled_at + timedelta(seconds=jitter_seconds)
    # 4. Clamp to active hours (08:00-23:00 local)
    jittered = clamp_to_active_hours(jittered, avatar_timezone)
    return jittered
```

### Peak Hour Bias

When distributing posts across the day, the timing engine weights peak hours:
- **Peak hours** (12:00–14:00, 18:00–22:00): 2x weight
- **Off-peak hours** (08:00–12:00, 14:00–18:00, 22:00–23:00): 1x weight
- **Sleep hours** (00:00–07:00): 0 weight (never scheduled)

### Minimum Interval Enforcement

When `execute_pending_posts` dispatches tasks, it checks `avatar.last_posted_at`:
- If `now - last_posted_at < 45 minutes`: defer the slot (don't dispatch yet)
- The slot will be picked up on the next 5-minute tick

---

## Admin UI Integration

### Avatar Detail Page — Proxy Section

Added to existing `/admin/avatars/{id}` page as a new tab/section:
- Proxy URL (masked: `socks5://***:***@1.2.3.4:1080`)
- User-Agent string
- Posting mode toggle (auto/manual/disabled)
- Last posted at + IP
- Reddit OAuth status (connected/disconnected) + connect button
- Consecutive failures count

### Global Posting Dashboard (`/admin/posting`)

- Total posts today (all avatars)
- Success rate (last 24h)
- Active auto-posting avatars count
- Global kill switch toggle
- Recent posting events table (last 50)
- Per-avatar posting summary (posts today, last post time, status)

---

## Testing Strategy

### OAuth Scaling Architecture

The system uses per-avatar OAuth tokens with client-scoped Reddit apps for blast radius isolation:

**Architecture:**
```
Client A (ATMO):
  Reddit App "ATMO-1" (client_id_reddit=abc123)
    ├─ Avatar 1: refresh_token_1 → 60 req/min (independent)
    ├─ Avatar 2: refresh_token_2 → 60 req/min (independent)
    └─ Avatar 3: refresh_token_3 → 60 req/min (independent)

Client B (XM Cyber):
  Reddit App "XMC-1" (client_id_reddit=def456)
    ├─ Avatar 4: refresh_token_4 → 60 req/min (independent)
    └─ Avatar 5: refresh_token_5 → 60 req/min (independent)

Shared Pool (farm/warming):
  Reddit App "Farm-1" (client_id=NULL)
    ├─ Avatar 6: refresh_token_6 → 60 req/min
    ├─ Avatar 7: refresh_token_7 → 60 req/min
    └─ ... (up to 50+ avatars, soft warning at 15)
```

**Key principles:**
- Each client gets 1+ dedicated Reddit apps → full blast radius isolation between clients
- Each avatar has its own refresh_token → own 60 req/min rate limit (independent of app)
- Farm/warming avatars use shared pool apps (no client assignment)
- When farm avatar is rented to a client → reassign to client's app (re-OAuth required)
- No hard limit on avatars per app (soft warning at 15 per client app, 50 per shared pool app)
- If App "ATMO-1" is revoked → only ATMO's avatars affected, XM Cyber continues normally

**Capacity at scale:**
| Clients | Avatars/client | Farm | Total Apps | Total Capacity |
|---------|---------------|------|-----------|---------------|
| 3 | 5 | 20 | 3 client + 2 shared = 5 | 35 × 60 = 2,100 req/min |
| 10 | 10 | 50 | 10 client + 3 shared = 13 | 150 × 60 = 9,000 req/min |
| 50 | 10 | 100 | 50 client + 3 shared = 53 | 600 × 60 = 36,000 req/min |

**Key insight:** Reddit rate limits are per-token, not per-app. Multiple apps exist solely for client isolation and blast radius control, not for capacity.

---

## App Health Check Service (`services/app_health_check.py`)

Periodic verification that Reddit apps are still valid.

```python
from datetime import datetime, timedelta

async def check_app_health(db: Session, reddit_app: RedditApp, encryptor: FieldEncryptor) -> str:
    """Verify a Reddit app's credentials are still valid.

    Makes a lightweight API call (GET /api/v1/me) using any avatar's token
    that is assigned to this app. If no avatars have tokens, marks as 'unknown'.

    Returns: 'healthy' | 'suspect' | 'revoked' | 'unknown'
    """

async def run_all_app_health_checks(db: Session) -> dict:
    """Celery Beat task (every 60 min): check all active apps.

    For each active app:
    1. Pick one avatar with a valid refresh_token
    2. Attempt GET /api/v1/me through that avatar's token
    3. On success: mark app as 'healthy'
    4. On 401/403: mark app as 'revoked', freeze all avatars on that app
    5. On network error: mark as 'suspect' (will retry next cycle)

    Returns summary: {checked: N, healthy: N, suspect: N, revoked: N}
    """

def detect_app_failure_pattern(db: Session, app_id: uuid.UUID, window_hours: int = 1) -> bool:
    """Detect if 2+ avatars on the same app got auth errors within a time window.

    Called from error handling in posting service. If pattern detected,
    proactively marks app as 'suspect' without waiting for scheduled health check.
    """
```

### Celery Beat Schedule Addition

```python
"check-reddit-app-health": {
    "task": "check_reddit_app_health",
    "schedule": 3600.0,  # Every 60 minutes
},
```

---

## Client-App Assignment Validation (`services/app_assignment.py`)

```python
def validate_avatar_app_assignment(
    db: Session,
    avatar: Avatar,
    reddit_app: RedditApp,
) -> tuple[bool, str]:
    """Validate that an avatar can be assigned to a Reddit app.

    Rules:
    1. If avatar has client_ids → app must belong to one of those clients (or shared pool during transition)
    2. If avatar is farm (no client) → app must be shared pool (client_id IS NULL)
    3. App must be active and health_status != 'revoked'

    Returns: (allowed: bool, reason: str)
    """

def get_available_apps_for_avatar(db: Session, avatar: Avatar) -> list[RedditApp]:
    """Get list of Reddit apps this avatar is eligible to use.

    For client avatars: returns apps belonging to their client
    For farm avatars: returns shared pool apps
    Excludes revoked and inactive apps.
    """
```

---

## Testing Strategy

### Property-Based Tests (Hypothesis)
- **Timing engine**: Generate random schedules, verify all invariants (min/max interval, active hours, daily cap, jitter bounds)
- **Encryption round-trip**: Generate random strings, verify encrypt→decrypt identity
- **Proxy URL validation**: Generate random strings, verify accept/reject correctness
- **Safety gates**: Generate random avatar states, verify correct allow/refuse decisions
- **Audit credential safety**: Generate random proxy URLs, verify no credentials leak into PostingEvent fields

### Unit Tests (pytest)
- PRAW client factory: mock requests.Session, verify proxy and user-agent configuration
- Post execution flow: mock PRAW, verify state transitions on success/failure
- Error classification: mock Reddit API responses, verify correct freeze/retry behavior
- Kill switch enforcement: verify posting skipped when disabled
- Consecutive failure tracking: verify freeze after 3 failures in 24h

### Integration Tests
- Full posting flow with mocked Reddit API (end-to-end Celery task execution)
- Redis distributed lock prevents concurrent posting for same avatar
- OAuth flow (mock Reddit OAuth endpoints)

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: PRAW Client Construction Correctness

For any avatar with a valid proxy_url and user_agent_string, the constructed PRAW client SHALL route all HTTP traffic through the specified proxy and use the specified user-agent header.

**Validates: Requirements 2.3, 2.4**

### Property 2: Missing Configuration Refuses Posting

For any avatar where proxy_url is empty/null OR user_agent_string is empty/null, the posting service SHALL refuse to post and return a configuration error.

**Validates: Requirements 2.6, 2.7**

### Property 3: Proxy URL Uniqueness Among Active Avatars

For any set of active avatars with posting_mode='auto', no two avatars SHALL share the same decrypted proxy_url value.

**Validates: Requirements 2.5**

### Property 4: Successful Post State Transitions

For any successful posting attempt, the system SHALL atomically update: CommentDraft.status='posted' with posted_at and reddit_comment_url set, EPGSlot.status='posted' with posted_at set, and Avatar.last_posted_at updated to the current timestamp.

**Validates: Requirements 3.3, 3.4, 3.5**

### Property 5: Reply Method Selection by Depth

For any comment draft, the posting service SHALL use submission.reply() when location_depth is 0 or null, and comment.reply() when location_depth > 0.

**Validates: Requirements 3.2**

### Property 6: Timing Engine Output Invariants

For any set of posting times generated by the timing engine for a single avatar: (a) all consecutive pairs are separated by at least 45 minutes and at most 90 minutes, (b) no time falls outside 08:00–23:00 in the avatar's declared timezone, and (c) no more than `min(phase_daily_limit, auto_posting_daily_cap)` posts are scheduled per day.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7**

### Property 7: Jitter Bounds

For any scheduled time and interval, the jittered time SHALL fall within ±30% of the interval from the original scheduled time (before active-hours clamping is applied).

**Validates: Requirements 4.1**

### Property 8: Kill Switch and Mode Enforcement

For any posting attempt where auto_posting_enabled is false OR the avatar's posting_mode is not 'auto', the posting service SHALL skip the post without executing any Reddit API call.

**Validates: Requirements 6.2, 6.4**

### Property 9: Safety Gates Refuse Unhealthy Avatars

For any avatar that is frozen OR has health_status in ('shadowbanned', 'suspended'), the posting service SHALL refuse to post regardless of slot status.

**Validates: Requirements 5.6, 5.7**

### Property 10: IP Subnet Consistency Enforcement

For any avatar where last_posted_ip is not null and the resolved proxy IP is in a different /24 subnet from last_posted_ip, the posting service SHALL freeze the avatar with a security alert and refuse to post. IPs within the same /24 subnet are considered consistent (normal residential proxy rotation).

**Validates: Requirements 5.1, 5.2**

### Property 11: Auth Error Freezes Avatar

For any posting attempt that receives a 401, 403, or account-suspended response from Reddit, the posting service SHALL freeze the avatar with the appropriate reason and NOT retry.

**Validates: Requirements 8.1, 8.2**

### Property 12: Audit Event Completeness and Credential Safety

For any posting attempt (success or failure), a PostingEvent record SHALL be created where: ip_used contains only an IP address (no credentials), proxy_url_hash equals SHA-256 of the full proxy URL, and all context fields are populated.

**Validates: Requirements 9.2, 9.3, 9.4**

### Property 13: Encryption Round-Trip

For any plaintext string, encrypting then decrypting with the same FieldEncryptor key SHALL produce the original plaintext.

**Validates: Requirements 2.1, 1.1**

### Property 14: Proxy URL Validation

For any string, the proxy URL validator SHALL accept it only if it starts with 'socks5://' or 'http://' and contains a valid host:port structure.

**Validates: Requirements 10.2**

### Property 15: Consecutive Failure Freeze

For any avatar that accumulates 3 consecutive posting failures within a 24-hour window, the posting service SHALL freeze the avatar with reason 'consecutive_failures'.

**Validates: Requirements 8.5**

### Property 16: Client-Scoped App Isolation

For any avatar assigned to client C, the avatar's reddit_app_id SHALL reference a RedditApp where reddit_app.client_id equals C (or reddit_app.client_id IS NULL only if the avatar is a farm avatar with no client assignment). An avatar of client A SHALL never be assigned to an app belonging to client B.

**Validates: Requirements 1.5, 13.2**

### Property 17: No Posting During Sleep Hours

For any generated posting time, the time SHALL never fall between 00:00–07:00 in the avatar's declared timezone.

**Validates: Requirements 7.4**

### Property 18: App Health Check Freezes on Revocation

For any Reddit app that receives a 401/403 response during health check, ALL avatars assigned to that app SHALL be frozen with reason containing the app name, and the app's health_status SHALL be set to 'revoked'.

**Validates: Requirements 13.5**
