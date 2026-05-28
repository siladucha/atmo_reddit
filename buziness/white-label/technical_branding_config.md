# BrandingConfig — Data Model Specification

## Overview

The `branding_configs` table stores all visual and identity customizations for each white-label partner. A single row defines how the platform renders for a partner's end-clients — logo, colors, domain, email sender, and mobile app identity. This is the core mechanism that makes RAMP invisible.

**Implementation effort:** 0.5 days (model + migration + seed)
**Dependencies:** `partners` table must exist first

---

## Schema Definition

```sql
CREATE TABLE branding_configs (
    id UUID PRIMARY KEY,
    partner_id UUID REFERENCES partners(id),
    logo_url VARCHAR(500),
    primary_color VARCHAR(7),       -- hex color (#RRGGBB)
    accent_color VARCHAR(7),        -- hex color (#RRGGBB)
    company_name VARCHAR(255),
    custom_domain VARCHAR(255),
    favicon_url VARCHAR(500),
    email_from_name VARCHAR(255),
    email_from_address VARCHAR(255),
    app_name VARCHAR(255),          -- for mobile app flavor
    app_bundle_id VARCHAR(255),
    is_active BOOLEAN DEFAULT true
);
```

---

## Field Descriptions & Validation Rules

| Field | Type | Required | Validation | Description |
|-------|------|----------|------------|-------------|
| `id` | UUID | Yes | Auto-generated (uuid4) | Primary key |
| `partner_id` | UUID (FK) | Yes | Must reference existing `partners.id` | Links branding to a partner entity |
| `logo_url` | VARCHAR(500) | Yes | Valid URL, must end in `.svg` or `.png`; asset must be ≥200×200px | Partner's logo displayed in header, reports, emails |
| `primary_color` | VARCHAR(7) | Yes | Regex: `^#[0-9A-Fa-f]{6}$` | Main brand color (nav bar, buttons, headings) |
| `accent_color` | VARCHAR(7) | Yes | Regex: `^#[0-9A-Fa-f]{6}$` | Secondary color (links, highlights, hover states) |
| `company_name` | VARCHAR(255) | Yes | Non-empty, 2-255 chars | Displayed in page titles, reports, footer |
| `custom_domain` | VARCHAR(255) | No | Valid FQDN, no protocol prefix, no trailing slash | e.g. `app.agencyname.com` |
| `favicon_url` | VARCHAR(500) | No | Valid URL, must end in `.ico` or `.png`; 32×32px | Browser tab icon |
| `email_from_name` | VARCHAR(255) | No | 2-255 chars | Sender name for transactional emails |
| `email_from_address` | VARCHAR(255) | No | Valid email format, domain must match `custom_domain` or be verified | Reply-to address on notifications |
| `app_name` | VARCHAR(255) | No | 2-30 chars (App Store limit) | Display name in mobile app |
| `app_bundle_id` | VARCHAR(255) | No | Reverse-domain format: `com.agency.poster` | iOS Bundle ID / Android applicationId |
| `is_active` | BOOLEAN | Yes | Default: `true` | Soft-delete / disable branding |

**Constraints:**
- One active `branding_configs` row per `partner_id` (enforced at application layer)
- If `custom_domain` is set, it must be unique across all active configs
- If `email_from_address` is set, `email_from_name` must also be set

---

## Asset Requirements

### Logo
- **Formats:** SVG (preferred) or PNG
- **Minimum size:** 200×200px
- **Maximum file size:** 2 MB
- **Background:** Transparent (renders on both light and dark backgrounds)
- **Storage:** S3 bucket (`ramp-partner-assets/{partner_id}/logo.*`)
- **Usage:** Header nav, PDF reports, email header, mobile app splash

### Favicon
- **Formats:** ICO (preferred) or PNG
- **Size:** 32×32px (standard browser favicon)
- **Maximum file size:** 100 KB
- **Storage:** S3 bucket (`ramp-partner-assets/{partner_id}/favicon.*`)
- **Usage:** Browser tab, bookmarks

### Colors
- **Format:** 6-digit hex with `#` prefix (e.g. `#1A73E8`)
- **Contrast requirement:** Primary color must have ≥4.5:1 contrast ratio against white (WCAG AA)
- **Validation:** Checked at submission time, warning if contrast fails

---

## Branding Injection — Jinja2 Context

The branding middleware injects a `branding` context variable into every Jinja2 template render. Templates reference branding values without knowing which partner they serve.

### Middleware Flow

```python
# app/middleware/branding.py

class BrandingMiddleware:
    """Resolves domain → BrandingConfig on every request."""

    async def __call__(self, request, call_next):
        domain = request.headers.get("host", "").split(":")[0]
        branding = await self.resolve_branding(domain)
        request.state.branding = branding
        response = await call_next(request)
        return response

    async def resolve_branding(self, domain: str) -> BrandingContext:
        # 1. Check cache (Valkey/Redis, TTL 5 min)
        cached = await cache.get(f"branding:{domain}")
        if cached:
            return BrandingContext.from_cache(cached)

        # 2. DB lookup: custom_domain match
        config = await db.query(BrandingConfig).filter(
            BrandingConfig.custom_domain == domain,
            BrandingConfig.is_active == True
        ).first()

        # 3. Fallback: RAMP default branding
        if not config:
            config = RAMP_DEFAULT_BRANDING

        # 4. Cache result
        context = BrandingContext.from_config(config)
        await cache.set(f"branding:{domain}", context.to_cache(), ttl=300)
        return context
```

### Template Usage

```html
<!-- templates/base.html -->
<head>
    <title>{{ branding.company_name }} — Dashboard</title>
    <link rel="icon" href="{{ branding.favicon_url }}">
    <style>
        :root {
            --color-primary: {{ branding.primary_color }};
            --color-accent: {{ branding.accent_color }};
        }
    </style>
</head>
<body>
    <nav style="background: var(--color-primary)">
        <img src="{{ branding.logo_url }}" alt="{{ branding.company_name }}" />
    </nav>
    <!-- All UI elements use CSS variables — zero hardcoded RAMP colors -->
</body>
```

### BrandingContext Object

```python
@dataclass
class BrandingContext:
    company_name: str
    logo_url: str
    favicon_url: str
    primary_color: str      # "#1A73E8"
    accent_color: str       # "#FF6B35"
    email_from_name: str
    email_from_address: str
    app_name: str
    is_default: bool        # True if RAMP fallback

    @classmethod
    def from_config(cls, config: BrandingConfig) -> "BrandingContext":
        return cls(
            company_name=config.company_name,
            logo_url=config.logo_url or RAMP_DEFAULTS["logo_url"],
            favicon_url=config.favicon_url or RAMP_DEFAULTS["favicon_url"],
            primary_color=config.primary_color or RAMP_DEFAULTS["primary_color"],
            accent_color=config.accent_color or RAMP_DEFAULTS["accent_color"],
            email_from_name=config.email_from_name or "RAMP",
            email_from_address=config.email_from_address or "noreply@ramp.com",
            app_name=config.app_name or "RAMP Poster",
            is_default=False,
        )
```

---

## Domain → BrandingConfig Lookup Flow

```
┌──────────────────────────────────────────────────────────────────┐
│  INCOMING REQUEST: https://app.agencyname.com/dashboard          │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  NGINX: Routes all *.agencyname.com → FastAPI app (port 8000)    │
│  (wildcard SSL via Let's Encrypt + certbot auto-renewal)         │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  BRANDING MIDDLEWARE: Extract Host header → "app.agencyname.com" │
│                                                                   │
│  Step 1: Check Redis/Valkey cache → key: "branding:app.agency…"  │
│          HIT → return cached BrandingContext (skip DB)            │
│          MISS → continue to Step 2                                │
│                                                                   │
│  Step 2: Query branding_configs WHERE custom_domain = host       │
│          AND is_active = true                                     │
│          FOUND → build BrandingContext, cache it (TTL 5 min)     │
│          NOT FOUND → continue to Step 3                           │
│                                                                   │
│  Step 3: Return RAMP_DEFAULT_BRANDING (fallback)                 │
│          Cache the fallback too (prevents repeated DB misses)     │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  FASTAPI ROUTE HANDLER: request.state.branding available         │
│  → Passes branding to Jinja2 template context                    │
│  → All templates render with partner's identity                  │
└──────────────────────────────────────────────────────────────────┘
```

**Performance:** Cache hit path adds <1ms latency. Cache miss (DB lookup) adds ~5ms. Acceptable for first request after cache expiry.

---

## Default Fallback Behavior

When no branding config matches the incoming domain (or partner has no custom domain configured):

```python
RAMP_DEFAULT_BRANDING = BrandingContext(
    company_name="RAMP",
    logo_url="/static/img/ramp_logo.svg",
    favicon_url="/static/img/ramp_favicon.ico",
    primary_color="#1E293B",       # Slate-800
    accent_color="#3B82F6",        # Blue-500
    email_from_name="RAMP",
    email_from_address="noreply@ramp.com",
    app_name="RAMP Poster",
    is_default=True,
)
```

**Fallback triggers:**
1. Request comes from IP address (no domain) → RAMP default
2. Request comes from unknown domain → RAMP default
3. Partner's `is_active = false` → RAMP default
4. Partner has no `branding_configs` row → RAMP default
5. Cache miss + DB miss → RAMP default (cached to prevent repeated lookups)

**Admin panel exception:** Requests to `admin.ramp.com` always use RAMP branding regardless of any partner config. Admin panel is internal-only.

---

## Update Workflow

Partner branding updates follow a controlled flow to prevent broken UI states:

```
┌─────────────────────────────────────────────────────────────────┐
│  1. PARTNER SUBMITS NEW ASSETS                                   │
│     → Upload form: logo, favicon, colors, company name           │
│     → Assets uploaded to S3 staging path                         │
│     → Status: "pending_review"                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. RAMP ADMIN REVIEWS                                           │
│     → Verify logo dimensions (≥200×200), format (SVG/PNG)        │
│     → Verify favicon dimensions (32×32), format (ICO/PNG)        │
│     → Verify color contrast (WCAG AA against white)              │
│     → Preview: render sample page with new branding              │
│     → Approve or reject with feedback                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. CONFIG UPDATED                                               │
│     → Assets moved from S3 staging → production path             │
│     → branding_configs row updated with new URLs/values           │
│     → Audit log entry: "branding_updated" with before/after      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. CACHE INVALIDATED                                            │
│     → Redis DEL "branding:{partner_domain}"                      │
│     → Next request triggers fresh DB lookup → new branding       │
│     → Propagation time: ≤5 minutes (cache TTL)                   │
│     → Immediate if admin triggers manual cache flush             │
└─────────────────────────────────────────────────────────────────┘
```

**Rollback:** If new branding causes issues, admin can revert `branding_configs` row to previous values + flush cache. Previous assets remain in S3 (versioned bucket).

---

## Mobile App Fields

The `app_name` and `app_bundle_id` fields feed directly into Flutter build flavors. They don't affect the web platform — they're consumed only during mobile app builds.

### How Fields Map to Flutter Build Flavors

```yaml
# flutter/flavors/{partner_slug}.yaml (generated from branding_configs)

flavor:
  name: "agencyname"
  app_name: "AgencyName Poster"          # ← branding_configs.app_name
  bundle_id: "com.agencyname.poster"     # ← branding_configs.app_bundle_id
  primary_color: "#1A73E8"               # ← branding_configs.primary_color
  accent_color: "#FF6B35"                # ← branding_configs.accent_color
  api_base_url: "https://app.agencyname.com/api/mobile"
  logo_path: "assets/partners/agencyname/logo.png"
  splash_path: "assets/partners/agencyname/splash.png"
  icon_path: "assets/partners/agencyname/icon.png"
```

### Build Command

```bash
# Generate partner-specific APK/IPA
flutter build apk --flavor=agencyname \
  --dart-define=APP_NAME="AgencyName Poster" \
  --dart-define=API_BASE_URL="https://app.agencyname.com/api/mobile"

flutter build ios --flavor=agencyname \
  --dart-define=APP_NAME="AgencyName Poster" \
  --dart-define=API_BASE_URL="https://app.agencyname.com/api/mobile"
```

### What Each Field Controls

| BrandingConfig Field | Mobile App Effect |
|---------------------|-------------------|
| `app_name` | App display name on home screen, App Store listing title |
| `app_bundle_id` | iOS Bundle Identifier + Android applicationId (unique per store listing) |
| `primary_color` | App bar, navigation, primary buttons |
| `accent_color` | FAB, links, selection highlights |
| `logo_url` | Splash screen center image, login screen header |
| `company_name` | In-app "Powered by" footer (hidden), push notification sender name |

### Build Flavor File Structure

```
ramp_poster/
├── android/
│   └── app/
│       └── src/
│           ├── main/          # Shared code
│           ├── agencyname/    # Partner-specific resources
│           │   ├── res/values/strings.xml    (app_name override)
│           │   └── res/mipmap-*/ic_launcher  (partner icon)
│           └── rampDefault/   # RAMP's own branding
├── ios/
│   └── Runner/
│       └── Flavors/
│           ├── AgencyName.xcconfig   (bundle ID, display name)
│           └── RampDefault.xcconfig
└── lib/
    └── config/
        └── flavor_config.dart  # Runtime flavor detection
```

### App Store Publishing

- Partner owns their Apple Developer / Google Play Console account
- RAMP provides the signed binary (IPA/AAB) + store listing metadata
- Partner submits to their own store listing
- Updates: RAMP builds new version → sends binary → partner submits update
- OTA updates (CodePush/Shorebird) for non-native changes (no re-submission needed)

---

## SQLAlchemy Model (Implementation Reference)

```python
# app/models/branding_config.py

from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.database import Base


class BrandingConfig(Base):
    __tablename__ = "branding_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id = Column(UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    logo_url = Column(String(500))
    primary_color = Column(String(7))
    accent_color = Column(String(7))
    company_name = Column(String(255))
    custom_domain = Column(String(255), unique=True)
    favicon_url = Column(String(500))
    email_from_name = Column(String(255))
    email_from_address = Column(String(255))
    app_name = Column(String(255))
    app_bundle_id = Column(String(255))
    is_active = Column(Boolean, default=True)

    # Relationships
    partner = relationship("Partner", back_populates="branding_config")
```

---

## Investor Takeaway

**Why this matters for the pitch:**

1. **Zero marginal cost** — Adding a new partner is a single DB row. No new servers, no new deployments, no DevOps work.
2. **5-minute branding** — Partner provides logo + colors + domain → config row created → platform renders their brand immediately.
3. **Complete invisibility** — End-clients interact with the partner's domain, see the partner's logo, receive emails from the partner's address. RAMP doesn't exist in their world.
4. **Mobile included** — Same config row drives both web branding AND mobile app builds. One source of truth.
5. **Already architected** — The multi-tenant RBAC system (6 roles, query scoping, data isolation) is built. BrandingConfig is a 0.5-day addition on top of existing infrastructure.

This is not a "we'll figure it out later" feature. The data model is defined, the middleware pattern is standard FastAPI, and the template system (Jinja2 + CSS variables) already supports dynamic theming. Implementation is straightforward.
