# 5-Day Implementation Timeline — White-Label Layer

## Executive Summary

The white-label layer is a thin extension on top of existing RAMP infrastructure. **80%+ of the multi-tenant architecture is already built and tested.** This timeline covers the remaining 20% — from database migration to live partner portal.

**Total effort:** 5 working days (40 hours)
**Team:** 1 senior full-stack developer (Max)
**Output:** Fully functional white-label system ready for first partner onboarding

---

## Prerequisites (Must Exist Before Starting)

| Component | Status | Notes |
|-----------|--------|-------|
| RBAC system (6 roles, permission guards) | ✅ DONE | Production, 40+ tests |
| Query scoping (automatic client_id filtering) | ✅ DONE | Production |
| Client management (7-step onboarding, CRUD) | ✅ DONE | Production |
| Admin panel (dark theme, HTMX partials) | ✅ DONE | Production |
| LLM context isolation (runtime assertions) | ✅ DONE | Production |
| JWT auth + role-based middleware | ✅ DONE | Production |
| ramp_poster Flutter app (for mobile flavor) | 🟡 PLANNED | Can defer Day 4 afternoon if not ready |

---

## Gantt-Style Timeline

```
         ┃ MORNING (4h)                    ┃ AFTERNOON (4h)                  ┃
━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋
         ┃                                 ┃                                 ┃
 DAY 1   ┃ ██████████████████████████████  ┃ ██████████████████████████████  ┃
         ┃ Data Model + Migration          ┃ SQLAlchemy Models + Schemas     ┃
         ┃ • partners table                ┃ • BrandingConfig model          ┃
         ┃ • branding_configs table        ┃ • Pydantic schemas              ┃
         ┃ • partner_id FK on clients      ┃ • Seed data (test partner)      ┃
         ┃                                 ┃                                 ┃
━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋
         ┃                                 ┃                                 ┃
 DAY 2   ┃ ██████████████████████████████  ┃ ██████████████████████████████  ┃
         ┃ Domain Routing (nginx + SSL)    ┃ Branding Middleware + Templates ┃
         ┃ • Wildcard server block         ┃ • FastAPI BrandingMiddleware    ┃
         ┃ • certbot automation script     ┃ • base.html CSS variables       ┃
         ┃ • DNS verification logic        ┃ • Cache layer (Redis, 5m TTL)  ┃
         ┃                                 ┃                                 ┃
━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋
         ┃                                 ┃                                 ┃
 DAY 3   ┃ ██████████████████████████████  ┃ ██████████████████████████████  ┃
         ┃ Partner Portal + Query Scoping  ┃ Partner User Management         ┃
         ┃ • QueryScope partner_id filter  ┃ • Create/invite partner users   ┃
         ┃ • Partner master dashboard view ┃ • Client creation scoped to     ┃
         ┃   (filtered admin dashboard)    ┃   partner                       ┃
         ┃                                 ┃                                 ┃
━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋
         ┃                                 ┃                                 ┃
 DAY 4   ┃ ██████████████████████████████  ┃ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ┃
         ┃ Email + Reports Branding        ┃ Mobile App Build Flavor         ┃
         ┃ • Email sender customization    ┃ • Flutter flavor config         ┃
         ┃ • PDF report branding injection ┃ • First partner test build      ┃
         ┃   (logo, colors, company name)  ┃ (can defer if ramp_poster       ┃
         ┃                                 ┃  not ready)                     ┃
         ┃                                 ┃                                 ┃
━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋
         ┃                                 ┃                                 ┃
 DAY 5   ┃ ██████████████████████████████  ┃ ██████████████████████████████  ┃
         ┃ Admin UI + Onboarding Workflow  ┃ E2E Testing + Documentation     ┃
         ┃ • Partner/branding CRUD panel   ┃ • Full flow test (domain →      ┃
         ┃ • Partner onboarding workflow   ┃   branding → portal → client)   ┃
         ┃   (create → configure → first  ┃ • Documentation + handoff       ┃
         ┃    client)                      ┃ • Runbook for partner ops       ┃
         ┃                                 ┃                                 ┃
━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋

LEGEND:  ██ = Critical path    ░░ = Deferrable (parallel track)
```

---

## Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│   DAY 1                    DAY 2                    DAY 3                │
│   ┌──────────────┐        ┌──────────────┐        ┌──────────────┐     │
│   │ Data Model   │───────>│ Domain       │───────>│ Partner      │     │
│   │ + Migration  │        │ Routing +    │        │ Portal +     │     │
│   │              │        │ Middleware   │        │ Query Scope  │     │
│   └──────────────┘        └──────────────┘        └──────┬───────┘     │
│          │                                               │              │
│          │                                               │              │
│          │                 DAY 4                    DAY 5 │              │
│          │                 ┌──────────────┐        ┌─────▼────────┐    │
│          │                 │ Email +      │───────>│ Admin UI +   │    │
│          └────────────────>│ Reports +    │        │ Testing +    │    │
│                            │ Mobile       │───────>│ Docs         │    │
│                            └──────────────┘        └──────────────┘    │
│                                                                          │
│   DEPENDENCY RULES:                                                      │
│   • Day 1 → Day 2 (models needed for middleware DB lookup)              │
│   • Day 2 → Day 3 (middleware needed for portal branding)               │
│   • Day 4 can run partially in parallel with Day 3                      │
│   • Day 5 depends on all previous days                                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Day 1: Data Model + Migration (Full Day)

### Morning (4 hours) — Database Schema

**Deliverables:**
- Alembic migration creating `partners` table
- Alembic migration creating `branding_configs` table
- Alembic migration adding `partner_id` FK to `clients` table
- Index on `clients.partner_id`

**Implementation:**

```sql
-- Migration 1: partners table
CREATE TABLE partners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    tier VARCHAR(50) NOT NULL DEFAULT 'starter',
    pricing_model VARCHAR(50) DEFAULT 'flat_fee',
    max_client_slots INTEGER NOT NULL DEFAULT 3,
    contract_start DATE,
    contract_end DATE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Migration 2: branding_configs table
CREATE TABLE branding_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id UUID REFERENCES partners(id) NOT NULL,
    logo_url VARCHAR(500),
    primary_color VARCHAR(7) NOT NULL DEFAULT '#1E293B',
    accent_color VARCHAR(7) NOT NULL DEFAULT '#3B82F6',
    company_name VARCHAR(255) NOT NULL,
    custom_domain VARCHAR(255) UNIQUE,
    favicon_url VARCHAR(500),
    email_from_name VARCHAR(255),
    email_from_address VARCHAR(255),
    app_name VARCHAR(255),
    app_bundle_id VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_branding_configs_custom_domain ON branding_configs(custom_domain);
CREATE INDEX ix_branding_configs_partner_id ON branding_configs(partner_id);

-- Migration 3: partner_id on clients
ALTER TABLE clients ADD COLUMN partner_id UUID REFERENCES partners(id);
CREATE INDEX ix_clients_partner_id ON clients(partner_id);
```

**Validation:** Run `alembic upgrade head`, verify tables exist, verify FK constraints.

### Afternoon (4 hours) — SQLAlchemy Models + Schemas + Seed

**Deliverables:**
- `app/models/partner.py` — Partner SQLAlchemy model
- `app/models/branding_config.py` — BrandingConfig SQLAlchemy model
- `app/schemas/partner.py` — Pydantic schemas (create, update, response)
- Updated `app/models/client.py` — add `partner_id` column + relationship
- Seed data: test partner "Demo Agency" with branding config

**Implementation:**

```python
# app/models/partner.py
class Partner(Base):
    __tablename__ = "partners"
    id = mapped_column(UUID, primary_key=True, default=uuid4)
    name = mapped_column(String(255), nullable=False)
    tier = mapped_column(String(50), nullable=False, default="starter")
    pricing_model = mapped_column(String(50), default="flat_fee")
    max_client_slots = mapped_column(Integer, nullable=False, default=3)
    contract_start = mapped_column(Date, nullable=True)
    contract_end = mapped_column(Date, nullable=True)
    is_active = mapped_column(Boolean, default=True)
    created_at = mapped_column(DateTime, default=func.now())
    # Relationships
    branding_config = relationship("BrandingConfig", back_populates="partner", uselist=False)
    clients = relationship("Client", back_populates="partner")
```

**Seed data:**
```python
# Test partner for development
demo_partner = Partner(
    name="Demo Agency",
    tier="growth",
    max_client_slots=8,
    is_active=True
)
demo_branding = BrandingConfig(
    partner=demo_partner,
    company_name="Demo Agency",
    primary_color="#1A73E8",
    accent_color="#FF6B35",
    custom_domain="demo.localhost",
    email_from_name="Demo Agency",
    app_name="Demo Poster"
)
```

**End of Day 1 Checkpoint:** ✅ All tables created, models defined, seed data loads, existing tests still pass.

---

## Day 2: Domain Routing + Branding Middleware (Full Day)

### Morning (4 hours) — nginx + SSL Automation

**Deliverables:**
- nginx wildcard server block configuration file
- certbot automation script (`/opt/ramp/scripts/provision_ssl.sh`)
- Cron job configuration (every 15 min cert check)
- Local testing with `/etc/hosts` override

**Implementation:**

```nginx
# /etc/nginx/sites-available/ramp-partners
server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate     /etc/letsencrypt/live/$ssl_server_name/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$ssl_server_name/privkey.pem;

    # Fallback wildcard cert
    ssl_certificate     /etc/letsencrypt/live/ramp-platform.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ramp-platform.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
}
```

**certbot automation script:**
- Queries `branding_configs` for domains without valid certs
- Verifies DNS resolution (dig check) before requesting cert
- Requests cert via HTTP-01 challenge
- Reloads nginx on success
- Logs all operations

**Validation:** Test with `/etc/hosts` pointing `demo.localhost` → `127.0.0.1`, verify SSL handshake.

### Afternoon (4 hours) — FastAPI Middleware + Template Updates

**Deliverables:**
- `app/middleware/branding.py` — BrandingMiddleware class
- Updated `app/main.py` — middleware registration
- Updated `app/templates/base.html` — CSS variables from branding context
- Redis/Valkey cache integration (5-minute TTL)
- Fallback to RAMP default branding for unknown domains

**Implementation:**

```python
# app/middleware/branding.py
class BrandingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        branding = await self._resolve_branding(host)
        request.state.branding = branding
        request.state.partner_id = branding.partner_id if branding else None
        response = await call_next(request)
        return response
```

**Template update (base.html):**
```html
<style>
    :root {
        --color-primary: {{ branding.primary_color | default('#1E293B') }};
        --color-accent: {{ branding.accent_color | default('#3B82F6') }};
    }
</style>
<nav>
    <img src="{{ branding.logo_url | default('/static/img/ramp_logo.svg') }}" />
    <span>{{ branding.company_name | default('RAMP') }}</span>
</nav>
```

**End of Day 2 Checkpoint:** ✅ Visiting `demo.localhost` shows Demo Agency branding. Visiting default domain shows RAMP branding. Cache works (second request skips DB).

---

## Day 3: Partner Portal + Query Scoping (Full Day)

### Morning (4 hours) — QueryScope Extension + Master Dashboard

**Deliverables:**
- Updated `app/services/query_scope.py` — partner_id filter (~5 lines)
- Partner master dashboard view (filtered version of admin dashboard)
- Partner-scoped client list (sees only their own clients)
- Partner-scoped activity feed

**Implementation (QueryScope extension):**

```python
# In QueryScope.scope_query():
if self.user.role == UserRole.partner and self.user.partner_id:
    # Partner sees only their own clients
    if hasattr(model, 'partner_id'):
        return query.filter(model.partner_id == self.user.partner_id)
    elif hasattr(model, 'client_id'):
        # For models scoped to client, filter via client's partner_id
        partner_client_ids = self.get_partner_client_ids()
        return query.filter(model.client_id.in_(partner_client_ids))
```

**Partner dashboard:**
- Reuses existing admin dashboard templates
- Filters data through QueryScope (partner sees only their clients)
- Shows: client count, total avatars, pipeline health, recent activity
- Route: `GET /partner/dashboard`

**Validation:** Log in as partner user → see only Demo Agency's clients. Log in as owner → see all clients.

### Afternoon (4 hours) — Partner User Management

**Deliverables:**
- Partner user creation endpoint (invite by email)
- Partner user roles: `partner_admin`, `partner_viewer`
- Client creation scoped to partner (new client auto-assigned `partner_id`)
- Partner team management page (list/invite/deactivate users)

**Implementation:**
- `POST /partner/users/invite` — creates user with `partner_id` set
- `POST /partner/clients/create` — creates client with `partner_id = current_user.partner_id`
- `GET /partner/team` — lists all users belonging to this partner
- Permission guard: `require_partner_access` (verifies user.partner_id matches)

**End of Day 3 Checkpoint:** ✅ Partner user can log in, see their dashboard, create clients (auto-scoped), invite team members. Data isolation verified — partner cannot see other partners' data.

---

## Day 4: Email + Reports + Mobile (Full Day)

### Morning (4 hours) — Email + PDF Branding

**Deliverables:**
- Email sender customization (from_name, from_address per partner)
- PDF report template with branding injection (logo, colors, company name)
- Email template using partner branding (header logo, footer company name)

**Implementation (email):**

```python
# In email sending service:
def send_notification(recipient, subject, body, partner_id=None):
    branding = get_branding_for_partner(partner_id)
    from_name = branding.email_from_name or "RAMP"
    from_address = branding.email_from_address or "noreply@ramp.com"
    # Send with partner's identity
    send_email(from_=f"{from_name} <{from_address}>", to=recipient, ...)
```

**Implementation (PDF reports):**

```python
# In report generation service:
def generate_monthly_report(client_id):
    client = get_client(client_id)
    branding = get_branding_for_partner(client.partner_id)
    # Inject into PDF template:
    # - Header: partner logo + company name
    # - Colors: primary/accent for charts and headings
    # - Footer: partner company name + contact
    return render_pdf("report_template.html", branding=branding, data=report_data)
```

**Validation:** Generate test PDF → verify partner logo appears, RAMP branding absent.

### Afternoon (4 hours) — Mobile App Build Flavor (Deferrable)

> ⚠️ **This half-day can be deferred** if `ramp_poster` Flutter app is not yet ready. Move to Day 5 afternoon or schedule separately.

**Deliverables:**
- Flutter build flavor configuration (Gradle + Xcode schemes)
- `flavors/demo_agency.json` config file
- First test build: `flutter build apk --flavor=demoAgency`
- Verification: app launches with Demo Agency branding

**Implementation:**
- Create `android/app/src/demoAgency/` resource directory
- Create `ios/Runner/DemoAgency/` configuration
- Add `--dart-define` parameters for API URL + flavor name
- Build and verify on emulator

**End of Day 4 Checkpoint:** ✅ Emails send with partner identity. PDF reports show partner branding. (If mobile ready: test APK builds with partner branding.)

---

## Day 5: Admin UI + Testing (Full Day)

### Morning (4 hours) — Admin Panel + Onboarding Workflow

**Deliverables:**
- Admin CRUD for partners (`/admin/partners` — list, create, edit, deactivate)
- Admin CRUD for branding configs (`/admin/partners/{id}/branding` — upload logo, set colors)
- Partner onboarding workflow (guided flow: create partner → configure branding → provision first client)
- Domain status indicator (DNS resolved? SSL provisioned?)

**Implementation:**
- `GET /admin/partners` — list all partners with status badges
- `POST /admin/partners` — create new partner (name, tier, slots)
- `GET /admin/partners/{id}/branding` — branding config form
- `POST /admin/partners/{id}/branding` — save branding (logo upload, colors, domain)
- `POST /admin/partners/{id}/provision-client` — create first client for partner
- HTMX partials for inline editing (same pattern as existing admin pages)

**Onboarding workflow (3 steps):**
```
Step 1: Create Partner → name, tier, contract dates
Step 2: Configure Branding → logo, colors, domain, email settings
Step 3: Provision First Client → client name, subreddits, keywords
        → Auto-assigns partner_id
        → Auto-creates partner admin user
        → Sends welcome email with login credentials
```

### Afternoon (4 hours) — End-to-End Testing + Documentation

**Deliverables:**
- E2E test: new domain → branding renders → partner portal works → client workspace isolated
- Integration test: partner user CRUD + query scoping verification
- Operations runbook: "How to onboard a new white-label partner"
- Handoff documentation for Tzvi (what to tell partners about setup)

**Test scenarios:**
1. Visit `demo.localhost` → see Demo Agency branding (not RAMP)
2. Log in as partner user → see only partner's clients
3. Create client as partner → client has `partner_id` set
4. Log in as owner → see ALL partners and clients
5. Partner user tries to access another partner's client → 403
6. Deactivate partner → all partner users lose access immediately

**Documentation:**
- `docs/partner_onboarding_runbook.md` — step-by-step ops guide
- `docs/white_label_architecture.md` — technical overview for future developers

**End of Day 5 Checkpoint:** ✅ Full white-label system functional. First partner can be onboarded. All tests pass. Documentation complete.

---

## Deliverables Summary

| Day | Deliverables | Files Created/Modified |
|-----|-------------|----------------------|
| 1 | DB schema, models, schemas, seed | 3 migrations, 2 models, 1 schema, seed update |
| 2 | nginx config, SSL script, middleware, templates | 2 config files, 1 middleware, 1 template update |
| 3 | QueryScope extension, partner portal, user mgmt | 1 service update, 3 route files, 4 templates |
| 4 | Email branding, PDF branding, mobile flavor | 2 service updates, 1 template, flavor config |
| 5 | Admin CRUD, onboarding flow, tests, docs | 2 route files, 5 templates, 2 test files, 2 docs |

**Total new files:** ~25
**Total modified files:** ~10
**Lines of code (estimated):** ~1,500 (excluding templates)

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Day 1 migration conflicts with existing schema | Low | Medium | Run on fresh DB first, test against production dump |
| DNS propagation delays (Day 2 testing) | Medium | Low | Use `/etc/hosts` for local testing, real DNS for staging |
| Flutter app not ready for Day 4 | Medium | Low | Defer mobile to separate sprint, web-only MVP is complete |
| QueryScope edge cases (Day 3) | Low | High | Property-based tests cover all scoping scenarios |
| Template branding breaks existing admin panel | Low | Medium | Admin panel uses `admin_base.html` (separate from partner `base.html`) |

---

## Post-Implementation: First Partner Onboarding (Day 6+)

Once the 5-day implementation is complete, onboarding the first real partner takes ~2 hours:

```
1. Admin creates partner in panel (5 min)
2. Partner provides: logo SVG, hex colors, domain choice (async, 1-2 days)
3. Admin configures branding (10 min)
4. Partner sets DNS CNAME (5 min, their side)
5. SSL auto-provisions (5-30 min, automatic)
6. Admin creates first client workspace (10 min)
7. Admin creates partner admin user + sends credentials (5 min)
8. Partner logs in, verifies branding (5 min)
9. ✅ LIVE — partner portal operational
```

**Time from "partner says yes" to "portal live":** 1-2 business days (limited by DNS propagation and asset delivery, not engineering work).

---

## Cost Impact

| Item | One-Time | Recurring |
|------|----------|-----------|
| Engineering (5 days × $0 marginal) | $0 | — |
| SSL certificates (Let's Encrypt) | $0 | $0/partner |
| Additional server resources | $0 | $0/partner |
| Additional database | $0 | $0/partner |
| S3 for partner assets | — | ~$0.10/partner/mo |
| **Total per partner** | **$0** | **~$0.10/mo** |

The white-label layer adds zero infrastructure cost. Every partner shares the same server, database, and codebase. The only per-partner cost is asset storage (logos, favicons) — negligible.

---

*Document prepared for investor/partner technical due diligence. Demonstrates that white-label is a 5-day engineering sprint, not a multi-month rebuild.*
