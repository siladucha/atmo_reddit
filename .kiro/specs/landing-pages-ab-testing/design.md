# Design Document: Landing Pages A/B Testing

## Overview

This design describes a **standalone marketing website** deployed as a separate Docker container, completely independent from the main Reddit SaaS application (`reddit_saas/`). The marketing site lives in its own directory (`marketing_site/`) at the project root, has its own FastAPI app, Dockerfile, and dependencies -- but connects to the **same shared PostgreSQL database** via Docker networking.

The marketing site serves four public pages (/, /mobile, /proxy, /thank-you) with A/B testing on pricing and business model variants, waitlist signup collection, and client-side analytics tracking. It is intentionally lightweight: no admin panel, no Celery, no PRAW, no LLM dependencies.

### Key Design Decisions

1. **Separate Docker container** -- complete isolation from the main app. Marketing site can be deployed, scaled, and updated independently. No risk of marketing code affecting the production pipeline.
2. **Shared PostgreSQL database** -- both containers connect to the same `db` service via Docker network. Marketing tables (`waitlist_signups`, `ab_test_assignments`, `analytics_events`) are owned by the marketing site Alembic migrations.
3. **Own Alembic setup** -- the marketing site manages its own migrations for marketing-specific tables only. This avoids coupling migration histories and allows independent schema evolution.
4. **Server-side variant assignment with client-side cookie management** -- the AB test engine runs in JavaScript for instant assignment, but records assignments to PostgreSQL via API for durability.
5. **Custom lightweight JS (no external analytics tools)** -- keeps the page fast, avoids third-party dependencies, and gives full control over data.
6. **Jinja2 + Tailwind CDN** -- consistent with the existing stack. Marketing pages use a dedicated `marketing_base.html` template (light premium theme).
7. **Batch analytics API** -- reduces network requests; client queues events and sends in batches.
8. **Reverse proxy ready** -- in production, both containers sit behind nginx/traefik that routes by domain or path prefix.

## Architecture

### High-Level System Diagram

```mermaid
graph TB
    subgraph Internet
        V[Visitor Browser]
    end

    subgraph "Reverse Proxy - nginx/traefik"
        RP[Routes by domain/path]
    end

    subgraph "Docker Network: reddit_saas_default"
        subgraph "marketing_site container - port 8001 external"
            MS[FastAPI Marketing App<br/>uvicorn on :8000 internal]
            MR[Marketing Routes<br/>/ /mobile /proxy /thank-you]
            MAPI[Marketing APIs<br/>POST /waitlist/signup<br/>POST /api/analytics/events<br/>POST /api/ab/record]
        end

        subgraph "reddit_saas container - port 8000 external"
            APP[FastAPI Main App]
            CW[Celery Workers]
            CB[Celery Beat]
        end

        subgraph "Shared Services"
            DB[(PostgreSQL 16<br/>reddit_saas DB)]
            RD[(Redis 7)]
        end
    end

    V -->|marketing.example.com| RP
    V -->|app.example.com| RP
    RP -->|marketing traffic| MS
    RP -->|admin/app traffic| APP
    MS -->|SQLAlchemy| DB
    APP -->|SQLAlchemy| DB
    APP -->|Celery| RD
    CW -->|Tasks| RD
    CB -->|Schedule| RD
```

### Request Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant RP as Reverse Proxy
    participant M as Marketing Site Container
    participant DB as PostgreSQL (shared)

    B->>RP: GET marketing.example.com/mobile
    RP->>M: GET /mobile (port 8000 internal)
    M->>B: HTML (Jinja2 template, default variant pricing)
    Note over B: JS loads, checks cookies
    alt No visitor_id cookie
        B->>B: Generate UUID v4, set cookie (30d)
    end
    alt No variant cookies
        B->>B: Assign variants (uniform random)
        B->>B: Set variant cookies (30d)
        B->>RP: POST /api/ab/record
        RP->>M: POST /api/ab/record
        M->>DB: INSERT ab_test_assignments
        M->>B: 200 OK
    end
    B->>B: Update DOM with assigned variant pricing
    B->>B: Queue page_view event
    Note over B: After 5s or 20 events
    B->>RP: POST /api/analytics/events [batch]
    RP->>M: POST /api/analytics/events
    M->>DB: INSERT analytics_events
    M->>B: 200 OK
```

### Docker Network Topology

```mermaid
graph LR
    subgraph "docker-compose network"
        A[app:8000] --- DB[db:5432]
        M[marketing:8000] --- DB
        A --- RD[redis:6379]
        CW[celery] --- DB
        CW --- RD
    end
    
    subgraph "Host Ports"
        H1[localhost:8000] -.->|maps to| A
        H2[localhost:8001] -.->|maps to| M
    end
```

## Project Structure

```
marketing_site/
+-- app/
|   +-- __init__.py
|   +-- main.py                    # FastAPI app creation + route registration
|   +-- config.py                  # Settings (pydantic-settings, DATABASE_URL only)
|   +-- database.py                # SQLAlchemy engine + session (connects to shared DB)
|   +-- models/
|   |   +-- __init__.py
|   |   +-- base.py                # SQLAlchemy Base
|   |   +-- waitlist_signup.py     # WaitlistSignup model
|   |   +-- ab_test_assignment.py  # ABTestAssignment model
|   |   +-- analytics_event.py    # AnalyticsEvent model
|   +-- schemas/
|   |   +-- __init__.py
|   |   +-- marketing.py          # Pydantic request/response schemas
|   +-- services/
|   |   +-- __init__.py
|   |   +-- waitlist.py           # Waitlist signup business logic
|   |   +-- ab_tests.py           # AB test configuration + validation
|   |   +-- analytics.py          # Analytics event processing
|   +-- routes/
|   |   +-- __init__.py
|   |   +-- pages.py              # GET /, /mobile, /proxy, /thank-you
|   |   +-- api.py                # POST /waitlist/signup, /api/analytics/events, /api/ab/record
|   +-- templates/
|   |   +-- marketing_base.html   # Premium light theme base
|   |   +-- marketing_home.html   # Homepage (hero + product cards)
|   |   +-- marketing_mobile.html # Mobile landing page
|   |   +-- marketing_proxy.html  # Proxy landing page
|   |   +-- marketing_thank_you.html # Thank-you confirmation
|   |   +-- marketing_404.html    # 404 page
|   |   +-- partials/
|   |       +-- marketing_waitlist_form.html  # Reusable form partial
|   +-- static/
|       +-- js/
|       |   +-- marketing.js      # AB engine + analytics + visitor identity
|       +-- css/
|       |   +-- marketing.css     # Custom styles (minimal, Tailwind CDN handles most)
|       +-- images/
|           +-- logo.svg          # Brand logo
+-- alembic/
|   +-- env.py                    # Alembic environment (points to shared DB)
|   +-- versions/                 # Marketing-only migrations
|       +-- 001_create_marketing_tables.py
+-- alembic.ini                   # Alembic config for marketing_site
+-- tests/
|   +-- __init__.py
|   +-- conftest.py               # Test fixtures (test DB, client)
|   +-- test_marketing_properties.py  # Property-based tests (Hypothesis)
|   +-- test_marketing_unit.py    # Unit tests
|   +-- test_marketing_integration.py # Integration tests
+-- Dockerfile                    # Lightweight Python image
+-- entrypoint.sh                 # Run migrations + start uvicorn
+-- pyproject.toml                # Minimal dependencies
+-- .env.example                  # Environment variable template
+-- README.md                     # Setup and development docs
```

## Docker Configuration

### Dockerfile (`marketing_site/Dockerfile`)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install only what we need (no gcc needed if using binary wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev curl netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENV PYTHONPATH=/app

CMD ["/app/entrypoint.sh"]
```

### Entrypoint (`marketing_site/entrypoint.sh`)

```bash
#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until nc -z db 5432; do
    echo "PostgreSQL not ready, waiting..."
    sleep 2
done
echo "PostgreSQL is ready."

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting marketing site..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### Docker Compose Service (added to `reddit_saas/docker-compose.yml`)

```yaml
  marketing:
    build:
      context: ../marketing_site
      dockerfile: Dockerfile
    ports:
      - "8001:8000"
    environment:
      - DATABASE_URL=postgresql://reddit_saas_user:${POSTGRES_PASSWORD:-change-me-in-production}@db:5432/reddit_saas
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.5'
```

### Dependencies (`marketing_site/pyproject.toml`)

```toml
[project]
name = "marketing-site"
version = "0.1.0"
description = "RAMP Marketing Website with A/B Testing"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "psycopg2-binary>=2.9.0",
    "alembic>=1.12.0",
    "jinja2>=3.1.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "python-multipart>=0.0.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "httpx>=0.25.0",
    "hypothesis>=6.90.0",
]
```

### Configuration (`marketing_site/app/config.py`)

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://reddit_saas_user:change-me@db:5432/reddit_saas"
    app_name: str = "RAMP Marketing"
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

## Components and Interfaces

### Backend Components

#### 1. FastAPI Application (`marketing_site/app/main.py`)

```python
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.routes import pages, api
from app.config import settings

app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register route modules
app.include_router(pages.router)
app.include_router(api.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "marketing"}
```

#### 2. Marketing Page Routes (`marketing_site/app/routes/pages.py`)

Public routes with no authentication required.

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request) -> HTMLResponse:
    """Render the homepage with hero section and product cards."""
    return templates.TemplateResponse("marketing_home.html", {"request": request})


@router.get("/mobile", response_class=HTMLResponse)
async def mobile_page(request: Request) -> HTMLResponse:
    """Render the Mobile landing page with default variant pricing."""
    return templates.TemplateResponse("marketing_mobile.html", {"request": request})


@router.get("/proxy", response_class=HTMLResponse)
async def proxy_page(request: Request) -> HTMLResponse:
    """Render the Proxy landing page with default variant pricing."""
    return templates.TemplateResponse("marketing_proxy.html", {"request": request})


@router.get("/thank-you", response_class=HTMLResponse)
async def thank_you_page(request: Request) -> HTMLResponse:
    """Render the thank-you confirmation page."""
    return templates.TemplateResponse("marketing_thank_you.html", {"request": request})
```

#### 3. Marketing API Routes (`marketing_site/app/routes/api.py`)

```python
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.marketing import (
    WaitlistSignupRequest,
    RecordAssignmentsRequest,
    AnalyticsBatchRequest,
)
from app.services.waitlist import process_signup, mark_conversions
from app.services.analytics import store_events, validate_event
from app.services.ab_tests import is_valid_variant

router = APIRouter(tags=["api"])


@router.post("/waitlist/signup")
async def waitlist_signup(request: Request, db: Session = Depends(get_db)):
    """Process waitlist form submission.

    On success: redirect to /thank-you
    On validation error: re-render page with errors
    On DB error: re-render page with error message
    """
    ...


@router.post("/api/analytics/events")
async def record_analytics(request: Request, db: Session = Depends(get_db)):
    """Accept a batch of analytics events.

    Validates each event, stores valid ones, returns count.
    """
    ...


@router.post("/api/ab/record")
async def record_ab_assignment(request: Request, db: Session = Depends(get_db)):
    """Record A/B test variant assignments to the database.

    Accepts: {visitor_id, assignments: [{test_name, variant_name}]}
    Idempotent: skips if assignment already exists for visitor+test.
    """
    ...
```

#### 4. Waitlist Service (`marketing_site/app/services/waitlist.py`)

Business logic for waitlist signup processing.

```python
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.waitlist_signup import WaitlistSignup
from app.models.ab_test_assignment import ABTestAssignment


async def process_signup(
    db: Session,
    email: str,
    company: str | None,
    role: str | None,
    accounts_count: int | None,
    price_tier: str | None,
    feedback: str | None,
    variant_shown: dict,
    source_page: str,
    visitor_id: UUID | None,
) -> WaitlistSignup:
    """Create or update a waitlist signup record.

    If email already exists, updates the existing record.
    If visitor_id is present, marks matching ab_test_assignments as converted.

    Returns the created/updated WaitlistSignup.
    Raises ValueError on validation failure.
    """
    ...


def mark_conversions(db: Session, visitor_id: UUID) -> int:
    """Set converted=True on all ab_test_assignments for this visitor.

    Returns the number of records updated.
    """
    ...
```

#### 5. AB Test Configuration (`marketing_site/app/services/ab_tests.py`)

Static configuration of active A/B tests and variant assignment logic.

```python
from dataclasses import dataclass


@dataclass
class Variant:
    name: str
    display_value: str  # What the visitor sees (e.g., "$99/month")


@dataclass
class ABTest:
    test_name: str
    page: str  # "mobile" or "proxy"
    variants: list[Variant]


# Active test configuration
ACTIVE_TESTS: list[ABTest] = [
    ABTest(
        test_name="mobile_pricing",
        page="mobile",
        variants=[
            Variant(name="price_99", display_value="$99/month"),
            Variant(name="price_149", display_value="$149/month"),
            Variant(name="price_199", display_value="$199/month"),
        ],
    ),
    ABTest(
        test_name="mobile_model",
        page="mobile",
        variants=[
            Variant(name="subscription", display_value="Monthly subscription"),
            Variant(name="pay_per_comment", display_value="Pay per comment"),
            Variant(name="hybrid", display_value="Hybrid model"),
        ],
    ),
    ABTest(
        test_name="proxy_pricing",
        page="proxy",
        variants=[
            Variant(name="price_999", display_value="$999/month"),
            Variant(name="price_1999", display_value="$1,999/month"),
            Variant(name="contact_sales", display_value="Contact sales"),
        ],
    ),
    ABTest(
        test_name="proxy_guarantee",
        page="proxy",
        variants=[
            Variant(name="no_guarantee", display_value="Standard (lower price)"),
            Variant(name="free_replacement", display_value="Free replacement guarantee"),
        ],
    ),
]


def get_tests_for_page(page: str) -> list[ABTest]:
    """Return active tests applicable to a given page."""
    return [t for t in ACTIVE_TESTS if t.page == page]


def get_default_variants() -> dict[str, str]:
    """Return the first variant of each test (used for no-JS fallback)."""
    return {t.test_name: t.variants[0].name for t in ACTIVE_TESTS}


def is_valid_variant(test_name: str, variant_name: str) -> bool:
    """Check if a variant name is valid for a given test."""
    for test in ACTIVE_TESTS:
        if test.test_name == test_name:
            return any(v.name == variant_name for v in test.variants)
    return False
```

#### 6. Analytics Service (`marketing_site/app/services/analytics.py`)

Processes and stores analytics events.

```python
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.analytics_event import AnalyticsEvent


@dataclass
class EventPayload:
    visitor_id: UUID
    event_type: str  # "page_view" | "click" | "signup"
    event_data: dict | None
    page_path: str
    timestamp: datetime


def validate_event(payload: dict) -> EventPayload | None:
    """Validate an event payload. Returns None if invalid."""
    ...


def store_events(db: Session, events: list[EventPayload]) -> int:
    """Bulk insert validated events. Returns count of stored events."""
    ...
```

### Frontend Components

#### 7. Marketing JavaScript (`marketing_site/app/static/js/marketing.js`)

Single JS file handling visitor identity, A/B assignment, DOM updates, and analytics.

```javascript
// Module structure (IIFE, no external dependencies)
const MarketingEngine = (function() {
    // --- Visitor Identity ---
    function getOrCreateVisitorId() { /* UUID v4 generation + cookie */ }
    function isValidUUID(value) { /* 8-4-4-4-12 hex pattern */ }

    // --- A/B Test Engine ---
    function getAssignments() { /* Read from cookies */ }
    function assignVariant(testName, variants) { /* Uniform random */ }
    function applyVariants(assignments) { /* Update DOM */ }
    function recordAssignments(visitorId, assignments) { /* POST to API */ }

    // --- Analytics Tracker ---
    const eventQueue = [];
    function trackEvent(type, data) { /* Add to queue */ }
    function flushQueue() { /* POST batch to API */ }
    function setupAutoFlush() { /* 5s interval + 20-event threshold */ }

    // --- Offline Queue (localStorage) ---
    function getOfflineQueue() { /* Read from localStorage */ }
    function retryOfflineEvents() { /* Send stored events on page load */ }

    return { init };
})();
```

### Templates

#### 8. Template Hierarchy

```
marketing_site/app/templates/
+-- marketing_base.html          # Premium light theme, no auth nav
+-- marketing_home.html          # Homepage (hero + product cards)
+-- marketing_mobile.html        # Mobile landing page
+-- marketing_proxy.html         # Proxy landing page
+-- marketing_thank_you.html     # Thank-you confirmation
+-- marketing_404.html           # 404 page with link to homepage
+-- partials/
    +-- marketing_waitlist_form.html  # Reusable waitlist form partial
```

`marketing_base.html` includes:
- Tailwind CSS CDN
- Shared header (logo + nav links to / and product pages)
- Shared footer (copyright, links)
- Block for page-specific content
- `marketing.js` script tag (deferred)
- Meta tags for SEO and social sharing
- No HTMX (not needed for marketing pages)

## Data Models

### Entity Relationship Diagram

```mermaid
erDiagram
    waitlist_signups {
        uuid id PK
        varchar email UK "NOT NULL, max 320"
        varchar company "max 200"
        varchar role "max 100"
        integer accounts_count "1-10000"
        varchar price_tier "max 50"
        text feedback "max 2000"
        jsonb variant_shown
        varchar source_page "max 500"
        timestamptz created_at "NOT NULL, DEFAULT now"
        timestamptz updated_at "NOT NULL, DEFAULT now"
    }

    ab_test_assignments {
        uuid id PK
        uuid visitor_id "NOT NULL"
        varchar test_name "NOT NULL, max 100"
        varchar variant_name "NOT NULL, max 100"
        timestamptz assigned_at "NOT NULL, DEFAULT now"
        boolean converted "NOT NULL, DEFAULT false"
        timestamptz converted_at "nullable"
    }

    analytics_events {
        uuid id PK
        uuid visitor_id "NOT NULL"
        varchar event_type "NOT NULL, max 100"
        jsonb event_data
        varchar page_path "max 500"
        timestamptz timestamp "NOT NULL, DEFAULT now"
    }

    ab_test_assignments }o--|| waitlist_signups : "visitor converts"
    analytics_events }o--|| ab_test_assignments : "same visitor_id"
```

### SQLAlchemy Models

#### `marketing_site/app/models/waitlist_signup.py`

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class WaitlistSignup(Base):
    __tablename__ = "waitlist_signups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    accounts_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    variant_shown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_page: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_waitlist_signups_created_at", "created_at"),
    )
```

#### `marketing_site/app/models/ab_test_assignment.py`

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class ABTestAssignment(Base):
    __tablename__ = "ab_test_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    visitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    test_name: Mapped[str] = mapped_column(String(100), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    converted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    converted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_ab_test_assignments_test_variant", "test_name", "variant_name"),
    )
```

#### `marketing_site/app/models/analytics_event.py`

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    visitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    page_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_analytics_events_type_timestamp", "event_type", "timestamp"),
    )
```

### Pydantic Schemas (`marketing_site/app/schemas/marketing.py`)

```python
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
import re


class WaitlistSignupRequest(BaseModel):
    email: str = Field(..., max_length=254)
    company: str | None = Field(None, max_length=100)
    role: str | None = Field(None, max_length=100)
    accounts_count: int | None = Field(None, ge=1, le=10000)
    price_tier: str | None = Field(None, max_length=50)
    feedback: str | None = Field(None, max_length=1000)
    variant_shown: dict | None = None
    source_page: str | None = Field(None, max_length=500)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(pattern, v.strip()):
            raise ValueError("Invalid email format")
        return v.strip().lower()


class ABAssignmentRecord(BaseModel):
    test_name: str = Field(..., max_length=100)
    variant_name: str = Field(..., max_length=100)


class RecordAssignmentsRequest(BaseModel):
    visitor_id: UUID
    assignments: list[ABAssignmentRecord]


class AnalyticsEventPayload(BaseModel):
    visitor_id: UUID
    event_type: str = Field(..., max_length=100)
    event_data: dict | None = None
    page_path: str | None = Field(None, max_length=500)
    timestamp: datetime


class AnalyticsBatchRequest(BaseModel):
    events: list[AnalyticsEventPayload] = Field(..., max_length=100)
```

## Database Migration Strategy

### Decision: Marketing Site Owns Its Own Migrations

The marketing site has its own Alembic setup (`marketing_site/alembic/`) pointing to the same shared PostgreSQL database. This is the recommended approach because:

1. **Independent deployment** -- marketing site can be deployed without touching the main app's migration history
2. **No coupling** -- adding/modifying marketing tables doesn't require changes to `reddit_saas/alembic/`
3. **Clean separation** -- marketing tables are clearly owned by the marketing codebase
4. **No conflicts** -- separate `alembic_version` tracking (uses a different version table name)

### Alembic Configuration (`marketing_site/alembic.ini`)

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql://reddit_saas_user:password@db:5432/reddit_saas
version_table = alembic_version_marketing

[loggers]
keys = root,sqlalchemy,alembic
```

Key: `version_table = alembic_version_marketing` ensures the marketing migrations track separately from the main app's `alembic_version` table.

### Initial Migration (`marketing_site/alembic/versions/001_create_marketing_tables.py`)

Creates all three marketing tables with indexes in a single migration:
- `waitlist_signups` (with unique email index, created_at index)
- `ab_test_assignments` (with visitor_id index, test_name+variant_name composite index)
- `analytics_events` (with visitor_id index, event_type+timestamp composite index)

### Migration Workflow

```bash
# Development: create new migration
cd marketing_site
alembic revision --autogenerate -m "description"

# Apply migrations (also runs automatically in entrypoint.sh)
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Deployment Strategy

### Development (Local Docker Compose)

Both services run via the same `docker-compose.yml` in `reddit_saas/`:

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    # ... existing config ...

  marketing:
    build:
      context: ../marketing_site
      dockerfile: Dockerfile
    ports:
      - "8001:8000"
    environment:
      - DATABASE_URL=postgresql://reddit_saas_user:${POSTGRES_PASSWORD}@db:5432/reddit_saas
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  db:
    # ... existing config (shared) ...

  redis:
    # ... existing config (main app only) ...
```

Access:
- Main app: `http://localhost:8000`
- Marketing site: `http://localhost:8001`

### Production (DigitalOcean Droplet)

Both containers run on the same droplet with nginx as reverse proxy:

```mermaid
graph TB
    subgraph "DigitalOcean Droplet (161.35.27.165)"
        subgraph "nginx (port 80/443)"
            N[Reverse Proxy]
        end
        subgraph "Docker Compose"
            A[app:8000]
            M[marketing:8000]
            DB[(PostgreSQL)]
            RD[(Redis)]
        end
    end

    Internet -->|marketing.ramp.com| N
    Internet -->|app.ramp.com| N
    N -->|proxy_pass :8000| A
    N -->|proxy_pass :8001| M
    A --- DB
    M --- DB
    A --- RD
```

### Nginx Configuration (Production)

```nginx
# Marketing site
server {
    listen 80;
    server_name marketing.ramp.com;  # or ramp.com for the public site

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Main app (admin + API)
server {
    listen 80;
    server_name app.ramp.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Deployment Commands

```bash
# Deploy marketing site only (no main app restart needed)
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.git/' \
  --exclude='*.pyc' --exclude='.DS_Store' --exclude='tests/' \
  --exclude='.env' --delete \
  marketing_site/ root@161.35.27.165:/app/marketing_site/

ssh root@161.35.27.165 "cd /app && docker compose build marketing && docker compose up -d marketing"

# Deploy both
ssh root@161.35.27.165 "cd /app && docker compose build && docker compose up -d"

# Check marketing health
curl -s http://161.35.27.165:8001/health
```

### Resource Allocation

| Container | CPU | Memory | Justification |
|-----------|-----|--------|---------------|
| app (main) | 1.5 CPU | 2 GB | Celery workers, LLM calls, admin UI |
| marketing | 0.5 CPU | 256 MB | Static pages, minimal DB writes |
| db | shared | 1 GB | PostgreSQL (shared) |
| redis | shared | 256 MB | Main app only |

The marketing container is extremely lightweight -- it only serves Jinja2 templates and handles simple DB inserts. 256 MB is more than sufficient.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system -- essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Variant configuration lookup is consistent

*For any* valid test_name and variant_name pair in the ACTIVE_TESTS configuration, looking up the display value should return a non-empty string that matches the configured display_value for that variant.

**Validates: Requirements 2.5, 3.5**

### Property 2: Assignment always produces valid output

*For any* set of active tests (including empty sets), calling the assignment function should return exactly one variant per test, and each returned variant_name must be a member of that test's configured variants list.

**Validates: Requirements 4.1, 4.6**

### Property 3: Existing valid assignments are idempotent

*For any* valid assignment state (a mapping of test_name to variant_name where all values are valid), reading and re-applying the assignment logic should return the identical mapping without modification.

**Validates: Requirements 4.3**

### Property 4: New test assignment preserves existing

*For any* existing valid assignment set and any new test added to the configuration, the merge operation should preserve all existing test->variant mappings unchanged and add exactly one valid variant for the new test only.

**Validates: Requirements 4.9**

### Property 5: Email validation rejects invalid formats

*For any* string that is empty, consists only of whitespace, exceeds 254 characters, lacks an "@" character, or has a domain part without at least one dot, the email validator should reject it (raise ValueError or return invalid).

**Validates: Requirements 5.4**

### Property 6: Waitlist signup upsert produces exactly one record per email

*For any* valid email and any sequence of N submissions (N >= 1) with that same email, the waitlist_signups table should contain exactly one record for that email, and its field values should match the most recent submission.

**Validates: Requirements 5.2, 5.5**

### Property 7: Conversion marking updates all visitor assignment records

*For any* visitor_id with K associated ab_test_assignment records (K >= 0), calling mark_conversions should set converted=True and converted_at to a non-null timestamp on all K records.

**Validates: Requirements 7.5**

### Property 8: Analytics event validation accepts iff required fields present

*For any* event payload dictionary, the validation function should accept it if and only if it contains non-null values for visitor_id (valid UUID), event_type (non-empty string), and timestamp (valid datetime). Missing or null required fields should cause rejection.

**Validates: Requirements 6.1, 6.2, 6.5, 6.6**

### Property 9: Analytics client queue never exceeds 100 events

*For any* sequence of N events added to the client-side queue without flushing, the queue length should never exceed 100. Events beyond the limit are dropped or trigger a flush.

**Validates: Requirements 6.4**

### Property 10: Generated visitor_id conforms to UUID v4 format

*For any* invocation of the visitor ID generation function, the output should match the UUID v4 pattern: 8-4-4-4-12 hexadecimal characters with the version nibble set to 4 and the variant bits set correctly.

**Validates: Requirements 9.1**

### Property 11: Invalid UUID strings are correctly detected

*For any* string that does not match the UUID v4 format (wrong length, non-hex characters, incorrect version nibble, missing hyphens), the UUID validation function should return false.

**Validates: Requirements 9.4**

### Property 12: Offline event queue is bounded at 50 events

*For any* number of events N queued while the analytics API is unreachable, the localStorage queue should contain at most 50 events (oldest events are discarded when the cap is reached).

**Validates: Requirements 10.3**

### Property 13: Stale event cleanup removes events older than 72 hours

*For any* set of queued events with mixed timestamps, after running the cleanup function, the queue should contain only events whose timestamp is within 72 hours of the current time. All older events should be discarded.

**Validates: Requirements 10.5**

## Error Handling

### Server-Side Errors

| Error Scenario | Handling Strategy | User Experience |
|---|---|---|
| Database unreachable on signup | Catch `SQLAlchemyError`, return form with error message | "We couldn't process your signup. Please try again." + form data retained |
| Invalid email format | Pydantic validation in `WaitlistSignupRequest` | Inline error below email field, no page reload |
| Analytics event missing fields | Return 422 with field-level errors | Silent (client-side, no user impact) |
| AB assignment recording fails | Retry 3x with exponential backoff (1s, 2s, 4s) | Variant still displayed; failure logged |
| Invalid variant in cookie | Overwrite with fresh valid assignment | Seamless -- visitor sees new variant |
| 404 page | Custom `marketing_404.html` template | Friendly page with link to homepage |
| Marketing container crashes | Docker restart policy `unless-stopped` | Brief downtime, auto-recovery |

### Client-Side Errors

| Error Scenario | Handling Strategy | User Experience |
|---|---|---|
| Analytics API unreachable | Queue events in localStorage (max 50) | Silent -- no user impact |
| localStorage full | Discard oldest events, continue tracking | Silent |
| Cookie blocked by browser | Generate visitor_id per session (in-memory) | Tracking works for session only |
| JS disabled | Server renders default variant (first in list) | Full content visible, no A/B testing |
| Stale offline events (>72h) | Discard on next page load | Silent cleanup |

### Retry Strategy

```python
# AB assignment recording retry (client-side JS)
MAX_RETRIES = 3
RETRY_DELAYS = [1000, 2000, 4000]  # ms, exponential backoff

# Analytics batch retry (client-side JS)
# On failure: store in localStorage, retry on next page load
# On second failure: discard events older than 72h
```

### Validation Rules

| Field | Rule | Error Message |
|---|---|---|
| email | Required, <=254 chars, matches `^[^@\s]+@[^@\s]+\.[^@\s]+$` | "Please enter a valid email address" |
| company | Optional, <=100 chars | "Company name must be 100 characters or less" |
| role | Optional, <=100 chars | "Role must be 100 characters or less" |
| accounts_count | Optional, integer 1-10,000 | "Please enter a number between 1 and 10,000" |
| feedback | Optional, <=1,000 chars | "Feedback must be 1,000 characters or less" |

## Testing Strategy

### Property-Based Tests (Hypothesis)

The marketing site includes its own test suite using Hypothesis for property-based testing. Each property test runs a minimum of 100 iterations.

**Library:** `hypothesis` (Python, in dev dependencies)

**Test file:** `marketing_site/tests/test_marketing_properties.py`

| Property | Test Function | Generators |
|---|---|---|
| P1: Variant lookup | `test_variant_lookup_consistency` | `st.sampled_from(all_test_variant_pairs)` |
| P2: Assignment validity | `test_assignment_always_valid` | `st.lists(st.sampled_from(ACTIVE_TESTS))` |
| P3: Assignment idempotence | `test_assignment_idempotent` | `st.fixed_dictionaries(valid_assignments)` |
| P4: New test preserves existing | `test_new_test_preserves_existing` | `st.dictionaries(test_names, variant_names)` |
| P5: Email validation rejects invalid | `test_invalid_email_rejected` | `st.text()` filtered to invalid patterns |
| P6: Signup upsert idempotence | `test_signup_upsert_one_record` | `st.emails()`, `st.lists(signup_data)` |
| P7: Conversion marking | `test_conversion_marks_all` | `st.uuids()`, `st.integers(min_value=0, max_value=10)` |
| P8: Event validation | `test_event_validation_iff_fields` | `st.fixed_dictionaries(...)` with optional None fields |
| P10: UUID v4 generation | `test_generated_uuid_valid` | No input needed (test output format) |
| P11: Invalid UUID detection | `test_invalid_uuid_detected` | `st.text()` filtered to non-UUID strings |
| P13: Stale event cleanup | `test_stale_cleanup_72h` | `st.lists(st.tuples(event, st.datetimes()))` |

**Note:** Properties 9 and 12 (queue size bounds) are client-side JavaScript. These will be tested with example-based JS tests rather than Hypothesis.

**Tag format:** Each test is annotated with:
```python
# Feature: landing-pages-ab-testing, Property 1: Variant configuration lookup is consistent
```

### Unit Tests (pytest)

**Test file:** `marketing_site/tests/test_marketing_unit.py`

- Homepage renders with hero, headline, subheadline, two product cards
- Mobile page renders with correct headline and section order
- Proxy page renders with correct headline and section order
- Thank-you page displays "You're on the list"
- 404 page includes homepage link
- Waitlist form contains all required fields
- Successful signup redirects to /thank-you
- DB failure shows error message and retains form data
- Default pricing visible in server-rendered HTML (no-JS fallback)
- Health endpoint returns 200

### Integration Tests (pytest + httpx)

**Test file:** `marketing_site/tests/test_marketing_integration.py`

- Full signup flow: GET /mobile -> POST /waitlist/signup -> redirect /thank-you
- Analytics batch API: POST valid events -> verify DB records
- AB assignment recording: POST assignments -> verify DB records
- Conversion marking: signup with visitor_id -> verify ab_test_assignments updated
- Cookie restoration: clear cookie, verify assignment restored from DB
- Container health check: GET /health returns 200

### Test Configuration

```python
# marketing_site/tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient
from app.main import app
from app.database import get_db
from app.models.base import Base

TEST_DATABASE_URL = "postgresql://test_user:test_pass@localhost:5432/test_marketing"


@pytest.fixture
def test_db():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def marketing_client(test_db):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(app=app, base_url="http://test")
```

### Running Tests

```bash
# From marketing_site directory
cd marketing_site

# Run all tests
pytest tests/ -v

# Run property tests only
pytest tests/test_marketing_properties.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing
```

## Performance Considerations

### Container Footprint

The marketing site is designed to be extremely lightweight:
- **Image size:** ~150 MB (python:3.11-slim + minimal deps)
- **Memory usage:** ~50-100 MB at runtime (2 uvicorn workers)
- **CPU:** Negligible (template rendering + simple DB inserts)
- **Startup time:** <5 seconds (migrations + uvicorn boot)

### Caching Strategy

- **Static assets:** Served with `Cache-Control: max-age=604800` (7 days) via FastAPI StaticFiles
- **Templates:** Jinja2 template caching enabled (auto_reload=False in production)
- **Tailwind CDN:** Browser-cached by CDN provider
- **No server-side page caching needed** -- pages are simple template renders with no DB reads on GET

### Database Impact

The marketing site adds minimal load to the shared PostgreSQL:
- **Page views:** 0 DB queries (pure template render)
- **Signup:** 1-2 queries (INSERT or UPDATE + optional conversion marking)
- **Analytics batch:** 1 bulk INSERT per batch (up to 100 events)
- **AB recording:** 1-4 INSERTs per new visitor (one per active test)

Estimated at peak traffic (1000 visitors/day):
- ~1000 analytics batches/day = ~1000 bulk INSERTs
- ~50 signups/day = ~50 queries
- ~300 new visitors/day = ~1200 AB assignment INSERTs

This is negligible compared to the main app's pipeline load (~9,350 queries/day).

## Security Considerations

### No Authentication Required

Marketing pages are fully public. No JWT, no session management, no auth middleware.

### Input Validation

- All form inputs validated via Pydantic schemas before DB insertion
- Email format validation prevents injection
- Field length limits prevent oversized payloads
- JSONB fields (variant_shown, event_data) accept arbitrary dicts but are stored as-is (no execution)

### Rate Limiting (Future)

For MVP, no rate limiting on marketing APIs. If abuse is detected:
- Add IP-based rate limiting via nginx (`limit_req_zone`)
- Or add a simple in-memory rate limiter in FastAPI

### CORS

Marketing site serves its own pages and APIs from the same origin -- no CORS configuration needed.

### Container Isolation

- Marketing container runs as non-root user (`appuser`)
- No access to Redis (no Celery, no cache)
- No access to main app's filesystem or environment variables
- Only network access: PostgreSQL on port 5432 (via Docker network)

## Dependencies

### Runtime Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.104.0 | Web framework |
| uvicorn[standard] | >=0.24.0 | ASGI server |
| sqlalchemy | >=2.0.0 | ORM + database access |
| psycopg2-binary | >=2.9.0 | PostgreSQL driver |
| alembic | >=1.12.0 | Database migrations |
| jinja2 | >=3.1.0 | Template engine |
| pydantic | >=2.5.0 | Data validation |
| pydantic-settings | >=2.1.0 | Environment config |
| python-multipart | >=0.0.6 | Form data parsing |

### Development Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | >=7.4.0 | Test runner |
| pytest-asyncio | >=0.21.0 | Async test support |
| httpx | >=0.25.0 | Test HTTP client |
| hypothesis | >=6.90.0 | Property-based testing |

### What is NOT included (by design)

- No Celery / Redis (no background tasks needed)
- No PRAW (no Reddit API access)
- No LiteLLM / AI libraries (no LLM calls)
- No HTMX (simple static pages)
- No python-jose / passlib (no authentication)
- No external analytics (custom JS only)

Total dependency count: 9 runtime packages (vs ~40+ in the main app).
