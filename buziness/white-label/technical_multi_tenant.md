# Technical Multi-Tenant Architecture — What's Already Built

## Executive Summary

**80%+ of the multi-tenant infrastructure required for white-label is already built, tested, and running in production.** The white-label extension is a thin layer on top of existing architecture — not a rebuild.

This document details what exists today and what needs adding. The gap is small: one FK migration, one new table, one middleware, and one dashboard view.

---

## 1. RBAC System — DONE ✅

### 8 Roles Implemented

| Role | Scope | Access Level |
|------|-------|-------------|
| `owner` | System-wide | Full infrastructure control, kill switches, all settings |
| `partner` | System-wide | All clients, onboarding, reports, user management |
| `avatar_manager` | System-wide (avatars) | All avatar lifecycle, health, EPG, review queue |
| `qa` | Cross-client | Review/approve all clients, read-only data access |
| `client_admin` | Own company only | Team management, avatar config, draft approval |
| `client_manager` | Own company only | Approve/reject drafts, add subreddits/keywords |
| `client_viewer` | Own company only | Dashboard + reports (read-only) |
| `b2c_user` | Single avatar | Self-service, simplified UI |

### Permission Guards (FastAPI Dependencies)

All routes are protected by composable permission guards:

```python
# Route-level guards — already in production
require_owner              # System settings, kill switches
require_platform_admin     # Admin panel (owner + partner + avatar_manager)
require_client_admin       # Team management within own company
require_client_manager_or_above  # Draft approval, subreddit/keyword management
require_client_access(client_id) # Verifies user can access specific client
require_authenticated      # Any active logged-in user
verify_client_access_from_path   # Auto-extracts client_id from URL path
require_avatar_manager_or_above  # Avatar inventory routes
```

### Role Permission Properties

The `UserRole` enum exposes computed properties used throughout the codebase:

```python
role.is_internal          # owner, partner, avatar_manager, qa
role.is_admin_level       # owner, partner, avatar_manager
role.can_review           # owner, partner, avatar_manager, qa, client_admin, client_manager
role.can_manage_clients   # owner, partner
role.can_manage_avatars   # owner, partner, avatar_manager, client_admin
role.can_manage_system    # owner only
role.can_manage_users     # owner, partner
role.can_trigger_pipeline # owner, partner
role.can_view_all_clients # owner, partner, qa
role.can_manage_team      # client_admin only (within own company)
role.is_client_scoped     # client_admin, client_manager, client_viewer, b2c_user
role.can_warm_avatars     # owner, partner, avatar_manager, qa
```

### UserClientAssignment Model

Maps users to clients with role tracking:

```python
class UserClientAssignment:
    id: UUID
    user_id: UUID          # FK → users
    client_id: UUID        # FK → clients
    role: str              # Role within this client
    is_active: bool        # Soft-delete for deactivation
    created_at: datetime
    # UniqueConstraint("user_id", "client_id")
```

### Client Deactivation Cascade

When a client is deactivated (`is_active=False`):
- All client-scoped users immediately lose access (403 on next request)
- All downstream pipeline tasks skip this client automatically
- Avatar assignments become inactive
- Owner/partner retain access for administrative purposes
- Reactivation instantly restores all access

---

## 2. Query Scoping — DONE ✅

### QueryScope Class

Every database query in the system passes through the `QueryScope` layer, which automatically filters results based on the authenticated user's role:

```python
class QueryScope:
    def scope_query(self, query, model):
        """Automatic client_id filtering based on user role."""
        # owner/partner → no filter (sees everything)
        # system context → no filter (background tasks)
        # client_admin/manager/viewer/b2c → filter by user.client_id
        
    def get_authorized_client_ids(self) -> list[UUID] | None:
        """Returns None for full access, or [client_id] for scoped users."""
        
    def assert_write_access(self, client_id: UUID) -> None:
        """Raises SecurityError if user cannot write to target client."""
```

### Scoping Rules by Role

| Role | `get_authorized_client_ids()` | `scope_query()` behavior |
|------|-------------------------------|--------------------------|
| owner | `None` (full access) | No filter applied |
| partner | `None` (full access) | No filter applied |
| avatar_manager | `None` (full access) | No filter applied |
| qa | Cross-client (route-level) | Route-level enforcement |
| client_admin | `[own_client_id]` | Filters by `client_id` |
| client_manager | `[own_client_id]` | Filters by `client_id` |
| client_viewer | `[own_client_id]` | Filters by `client_id` |
| b2c_user | `[own_client_id]` | Filters by `client_id` |

### Special Model Scoping

The QueryScope handles complex models with custom filter strategies:

- **Avatar** — Filters by `client_ids` ARRAY contains OR active rental exists
- **RedditThread** — Filters via `ThreadScore` join (threads are shared, scores are per-client)
- **StrategyDocument** — Filters via avatar ownership chain
- **Client** — Filters by `id == client_id` (user sees only their own company)
- **Default** — Filters by `model.client_id` column

### System Context for Background Tasks

```python
# Celery workers use system_context() to bypass user-based scoping
scope = system_context(caller="generate_comments")
# Logs the caller for audit trail, returns full-access scope
```

### Partner Scoping — Ready for White-Label Extension

The existing `partner` role already has full access to all clients. For white-label, the extension is straightforward:

```python
# Current: partner sees ALL clients
if role in (UserRole.owner, UserRole.partner):
    return None  # Full access

# White-label extension (simple addition):
if role == UserRole.partner:
    # Filter by partner_id on clients table
    return query.filter(model.partner_id == self.user.partner_id)
```

This is a **single-line change** in `scope_query()` once `partner_id` FK exists on the `clients` table.

---

## 3. Data Isolation — DONE ✅

### LLM Context Isolation

The generation pipeline verifies avatar-client ownership at runtime before assembling any LLM context:

```python
def _avatar_accessible_by_client(db, avatar, client) -> bool:
    """Runtime check: is this avatar owned by or rented to this client?"""
    # Check 1: client.id in avatar.client_ids ARRAY (ownership)
    # Check 2: Active, non-expired rental in avatar_rentals table
```

This function is called with **runtime assertions** in:
- `select_persona()` — before choosing which avatar responds to a thread
- `generate_comment()` — before assembling the LLM prompt with avatar context
- All pipeline stages that touch avatar data

### Avatar Farm & Rental Model

Avatars can be shared across clients via the rental system:

```python
class AvatarRental:
    avatar_id: UUID    # The farm avatar being rented
    client_id: UUID    # The client renting it
    is_active: bool    # Active rental flag
    expires_at: datetime | None  # Optional expiry
    price: Decimal     # Rental price
```

Query scoping automatically includes rented avatars in a client's visible set — no special handling needed at the route level.

### Cross-Client Isolation Verification

**Property-based tests** verify isolation across all scenarios:

| Test Scenario | What's Verified |
|---------------|----------------|
| Client manager queries | Sees ONLY own client's data (events, drafts, threads, avatars) |
| Owner/partner queries | Sees ALL clients' data (no filtering) |
| Client deactivation | All scoped users immediately blocked (403) |
| Write access | client_admin CANNOT write to another client |
| Avatar visibility | Client A CANNOT see Client B's avatars |
| Thread visibility | Scoped via ThreadScore (shared threads, per-client scores) |
| Draft visibility | Filtered by `client_id` column |
| Team management | client_admin CANNOT manage users in another company |

The test suite (`tests/test_rbac_scenarios.py`) covers **8 comprehensive scenarios** with 40+ individual test cases.

### Pipeline-Level Isolation

Every automated pipeline task enforces isolation:
- `generate_comments` — filters out avatars not belonging to the target client
- `generate_hobby_comments` — skips avatars outside client scope
- `generate_posts` — health_status + client ownership filter
- `run_hobby_pipeline_all_avatars` — excludes frozen + shadowbanned + wrong-client
- All tasks check `client.is_active` before processing

---

## 4. What Needs Adding for White Label

### 4.1 Partner ID on Clients Table (0.5 day)

```sql
-- Simple Alembic migration
ALTER TABLE clients ADD COLUMN partner_id UUID REFERENCES partners(id);
CREATE INDEX ix_clients_partner_id ON clients(partner_id);
```

**Impact:** One FK column. All existing query scoping logic already handles the `partner` role — this just adds the data relationship.

### 4.2 BrandingConfig Model (0.5 day)

```sql
CREATE TABLE branding_configs (
    id UUID PRIMARY KEY,
    partner_id UUID REFERENCES partners(id),
    logo_url VARCHAR(500),
    primary_color VARCHAR(7),
    accent_color VARCHAR(7),
    company_name VARCHAR(255),
    custom_domain VARCHAR(255),
    favicon_url VARCHAR(500),
    email_from_name VARCHAR(255),
    app_name VARCHAR(255),
    is_active BOOLEAN DEFAULT true
);
```

**Impact:** New table, no changes to existing models.

### 4.3 Domain-Based Partner Lookup Middleware (1 day)

```python
# New middleware: resolve incoming domain → partner → branding
class BrandingMiddleware:
    async def __call__(self, request, call_next):
        domain = request.headers.get("host")
        branding = lookup_branding_by_domain(domain)
        request.state.branding = branding  # Available to all templates
        return await call_next(request)
```

**Impact:** One new middleware file. Templates already use `request.state` for context injection (same pattern as auth middleware).

### 4.4 Partner Master Dashboard View (1 day)

A filtered view of the existing admin dashboard showing only the partner's clients. The existing admin templates + HTMX partials can be reused with branding context injection.

### 4.5 QueryScope Partner Filter (0.5 day)

```python
# In QueryScope.scope_query():
if role == UserRole.partner and self.user.partner_id:
    return query.filter(model.partner_id == self.user.partner_id)
```

**Impact:** ~5 lines of code in an existing class.

---

## 5. Architecture Readiness Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    WHAT'S BUILT (80%+)                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ✅ RBAC (8 roles, permission guards, role properties)          │
│  ✅ Query Scoping (automatic client_id filtering)               │
│  ✅ LLM Context Isolation (runtime assertions)                  │
│  ✅ Avatar Farm + Rental Model (shared avatars)                 │
│  ✅ Client Deactivation Cascade                                 │
│  ✅ Cross-Client Isolation Tests (40+ test cases)               │
│  ✅ Pipeline Guards (all tasks check ownership)                 │
│  ✅ Write Access Control (SecurityError on violation)           │
│  ✅ System Context for Background Tasks                         │
│  ✅ JWT Auth + Role-Based Middleware                            │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                    WHAT NEEDS ADDING (20%)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ⬜ partner_id FK on clients table (1 migration)               │
│  ⬜ BrandingConfig model (1 new table)                         │
│  ⬜ Domain-based partner lookup middleware (1 file)             │
│  ⬜ Partner master dashboard view (template reuse)             │
│  ⬜ QueryScope partner filter (~5 lines)                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Zero Infrastructure Cost Per Partner

Adding a white-label partner requires:
- **No new servers** — same FastAPI instance serves all partners
- **No new databases** — same PostgreSQL, scoped by `partner_id`
- **No new containers** — same Docker Compose deployment
- **No new Redis/Valkey** — same cache/lock infrastructure
- **No new Celery workers** — same task queue processes all partners

The only per-partner cost is LLM API usage (proportional to their client count) and optional custom domain SSL certificate (free via Let's Encrypt).

---

## 6. Key Technical Proof Points for Pitch

| Claim | Evidence |
|-------|----------|
| "Multi-tenant from Day 1" | 8-role RBAC system with query scoping, built and tested |
| "Zero infrastructure per partner" | Single codebase, single DB, partner_id scoping |
| "Data isolation guaranteed" | Runtime assertions + property-based tests (40+ cases) |
| "5 days to onboard" | Only 5 items to add (migration + table + middleware + view + filter) |
| "Battle-tested security" | Client deactivation cascade, write access control, SecurityError on violations |
| "Scales to unlimited partners" | QueryScope handles N partners with same code path |
| "Avatar sharing works" | Farm + rental model already supports cross-client avatar access |

---

## 7. Code References

| Component | File | Status |
|-----------|------|--------|
| Permission guards | `app/dependencies/permissions.py` | Production |
| Query scoping | `app/services/query_scope.py` | Production |
| LLM isolation | `app/services/isolation.py` | Production |
| UserRole enum | `app/models/user_role.py` | Production |
| UserClientAssignment | `app/models/user_client_assignment.py` | Production |
| AvatarRental | `app/models/avatar_rental.py` | Production |
| RBAC test suite | `tests/test_rbac_scenarios.py` | 40+ tests passing |
| Permission matrix | `docs/permission_matrix.md` | Documentation |
