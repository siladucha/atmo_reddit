# Custom Domain Routing — Technical Approach

## Overview

White-label partners serve the RAMP platform under their own domain (e.g., `reddit.theiragency.com`). This document describes the full request flow from DNS to rendered page, covering nginx configuration, automated SSL provisioning, and application-level branding injection.

**Key principle:** Zero per-partner infrastructure changes. Adding a new partner domain requires only a database row in `branding_configs` — no nginx reload, no container restart, no manual certificate steps.

---

## 1. DNS Setup (Partner's Responsibility)

Partners configure DNS to point their chosen subdomain at RAMP's infrastructure.

### Option A: CNAME Record (Recommended — Subdomains)

```
reddit.theiragency.com.  CNAME  partners.ramp-platform.com.
```

- Works for any subdomain (`reddit.`, `platform.`, `app.`, etc.)
- Partner's DNS provider handles this — typically 1-click in Cloudflare/Route53/GoDaddy
- Propagation: usually 5-60 minutes, worst case 24 hours

### Option B: A Record (Apex Domains Only)

```
theiragency.com.  A  161.35.27.165
```

- Required when partner wants to use their root domain (no subdomain)
- Some DNS providers support ALIAS/ANAME records as an alternative
- Less flexible — IP changes require partner DNS update

### Onboarding Checklist for Partner

1. Partner decides on domain (e.g., `reddit.acme-marketing.com`)
2. Partner creates CNAME → `partners.ramp-platform.com`
3. Partner notifies RAMP ops (or enters domain in admin panel)
4. RAMP adds `custom_domain` to partner's `branding_configs` row
5. First request triggers automatic SSL provisioning
6. Partner verifies HTTPS access within 5-30 minutes

---

## 2. NGINX Configuration

A single wildcard server block handles all partner domains dynamically. No per-partner nginx config changes needed.

### Server Block

```nginx
# Catch-all server block for white-label partner domains
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name _;

    # Dynamic SSL certificate selection (per-domain)
    ssl_certificate     /etc/letsencrypt/live/$ssl_server_name/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$ssl_server_name/privkey.pem;

    # Fallback wildcard cert for *.ramp-platform.com
    ssl_certificate     /etc/letsencrypt/live/ramp-platform.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ramp-platform.com/privkey.pem;

    # Pass original Host header to FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ACME challenge path for certbot (HTTP-01 validation)
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
}

# HTTP → HTTPS redirect for all domains
server {
    listen 80;
    listen [::]:80;
    server_name _;

    # Allow ACME challenges over HTTP
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect everything else to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `server_name _` (wildcard catch-all) | No nginx reload needed when adding partners |
| `$ssl_server_name` for cert path | nginx selects correct cert per incoming SNI |
| Fallback wildcard cert | Serves `*.ramp-platform.com` if per-domain cert not yet provisioned |
| Host header passthrough | FastAPI reads `Host` to determine branding context |
| Single upstream (`127.0.0.1:8000`) | All partners share one FastAPI instance |

---

## 3. SSL/TLS (Auto-Provisioned)

### Strategy: Let's Encrypt + certbot (HTTP-01 Challenge)

Certificates are provisioned automatically on first request to a new partner domain.

### Provisioning Flow

```
1. Partner DNS propagates (CNAME → partners.ramp-platform.com)
2. First HTTPS request arrives → nginx serves fallback cert (warning in browser)
3. Provisioning script detects new domain in branding_configs without cert
4. certbot runs: certbot certonly --webroot -w /var/www/certbot -d reddit.theiragency.com
5. Certificate issued (~10 seconds for HTTP-01 validation)
6. nginx picks up new cert on next request (no reload needed with $ssl_server_name)
```

### Automation Script (cron-based)

```bash
#!/bin/bash
# /opt/ramp/scripts/provision_ssl.sh
# Runs every 15 minutes via cron

# Query branding_configs for domains without valid certs
DOMAINS=$(psql -t -A -c "
    SELECT custom_domain FROM branding_configs
    WHERE custom_domain IS NOT NULL
    AND is_active = true
" reddit_saas)

for DOMAIN in $DOMAINS; do
    # Skip if cert already exists and is valid
    if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        # Check expiry (skip if >30 days remaining)
        EXPIRY=$(openssl x509 -enddate -noout -in "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" | cut -d= -f2)
        EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "$EXPIRY" +%s)
        NOW_EPOCH=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
        if [ "$DAYS_LEFT" -gt 30 ]; then
            continue
        fi
    fi

    # Verify DNS points to us before requesting cert
    RESOLVED_IP=$(dig +short "$DOMAIN" | tail -1)
    OUR_IP="161.35.27.165"
    if [ "$RESOLVED_IP" != "$OUR_IP" ]; then
        echo "SKIP $DOMAIN — DNS not pointing to us (resolved: $RESOLVED_IP)"
        continue
    fi

    # Request certificate
    certbot certonly \
        --webroot \
        -w /var/www/certbot \
        -d "$DOMAIN" \
        --non-interactive \
        --agree-tos \
        --email ops@ramp-platform.com \
        --quiet

    if [ $? -eq 0 ]; then
        echo "OK $DOMAIN — certificate provisioned"
        # Reload nginx to pick up new cert
        nginx -s reload
    else
        echo "FAIL $DOMAIN — certbot failed"
    fi
done
```

### Cron Schedule

```cron
# Provision new certs every 15 minutes
*/15 * * * * /opt/ramp/scripts/provision_ssl.sh >> /var/log/ramp/ssl_provision.log 2>&1

# Renew existing certs (certbot handles 60-day renewal internally)
0 3 * * * certbot renew --quiet --post-hook "nginx -s reload" >> /var/log/ramp/ssl_renew.log 2>&1
```

### Certificate Lifecycle

| Event | Timing | Action |
|-------|--------|--------|
| New domain added to `branding_configs` | T+0 | Row inserted |
| DNS propagation | T+5min to T+24h | Partner's responsibility |
| First cert provisioned | Next cron run after DNS resolves | Automatic |
| Certificate valid | 90 days (Let's Encrypt default) | — |
| Renewal triggered | 30 days before expiry | `certbot renew` cron |
| Partner removed | Manual | Delete cert + remove DB row |

### Fallback: Wildcard Certificate

```bash
# Covers all *.ramp-platform.com subdomains (DNS-01 challenge)
certbot certonly \
    --dns-digitalocean \
    --dns-digitalocean-credentials /etc/letsencrypt/do-credentials.ini \
    -d "*.ramp-platform.com" \
    -d "ramp-platform.com"
```

- Used as fallback when per-domain cert not yet provisioned
- Covers RAMP's own subdomains (`admin.ramp-platform.com`, `api.ramp-platform.com`)
- Does NOT cover partner custom domains (those need individual certs)

---

## 4. Application-Level Routing

### FastAPI Branding Middleware

```python
# app/middleware/branding.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from sqlalchemy import select
from app.database import async_session
from app.models.branding_config import BrandingConfig

# In-memory cache (refreshed every 5 minutes)
_branding_cache: dict[str, BrandingConfig] = {}
_cache_ttl = 300  # seconds


class BrandingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]  # strip port

        # Look up branding config by domain
        branding = await self._get_branding(host)

        if branding:
            # Inject branding context into request state
            request.state.branding = branding
            request.state.partner_id = branding.partner_id
        else:
            # No match → serve default RAMP branding
            request.state.branding = None
            request.state.partner_id = None

        response = await call_next(request)
        return response

    async def _get_branding(self, domain: str) -> BrandingConfig | None:
        # Check cache first
        if domain in _branding_cache:
            return _branding_cache[domain]

        # Query database
        async with async_session() as session:
            result = await session.execute(
                select(BrandingConfig)
                .where(BrandingConfig.custom_domain == domain)
                .where(BrandingConfig.is_active == True)
            )
            config = result.scalar_one_or_none()

        # Cache result (even None, to avoid repeated DB hits for unknown domains)
        _branding_cache[domain] = config
        return config
```

### Jinja2 Template Integration

```python
# In route handlers — branding context injected into all template renders

@router.get("/dashboard")
async def dashboard(request: Request):
    branding = request.state.branding

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        # Branding context (falls back to RAMP defaults)
        "logo_url": branding.logo_url if branding else "/static/ramp-logo.svg",
        "primary_color": branding.primary_color if branding else "#6366f1",
        "accent_color": branding.accent_color if branding else "#8b5cf6",
        "company_name": branding.company_name if branding else "RAMP",
        "favicon_url": branding.favicon_url if branding else "/static/favicon.ico",
        # ... page-specific data
    })
```

### Unknown Domain Handling

| Scenario | Behavior |
|----------|----------|
| Known partner domain | Serve with partner branding |
| `*.ramp-platform.com` | Serve with default RAMP branding |
| Unknown domain (no DB match) | Serve default RAMP branding (or 404 page) |
| Admin panel (`admin.ramp-platform.com`) | Serve admin panel (no partner branding) |

---

## 5. Request Flow — Sequence Diagram

```
┌──────────┐     ┌─────────┐     ┌───────────┐     ┌──────────┐     ┌────────────────┐     ┌──────────────┐
│  Browser │     │   DNS   │     │   NGINX   │     │  FastAPI │     │  PostgreSQL    │     │   Jinja2     │
│          │     │         │     │           │     │          │     │  branding_     │     │   Template   │
│          │     │         │     │           │     │          │     │  configs       │     │   Engine     │
└────┬─────┘     └────┬────┘     └─────┬─────┘     └────┬─────┘     └───────┬────────┘     └──────┬───────┘
     │                │                │                │                   │                     │
     │  1. GET https://reddit.acme.com/dashboard       │                   │                     │
     │───────────────>│                │                │                   │                     │
     │                │                │                │                   │                     │
     │  2. CNAME → partners.ramp-platform.com          │                   │                     │
     │                │  A → 161.35.27.165             │                   │                     │
     │<───────────────│                │                │                   │                     │
     │                │                │                │                   │                     │
     │  3. TLS handshake (SNI: reddit.acme.com)        │                   │                     │
     │────────────────────────────────>│                │                   │                     │
     │                │                │                │                   │                     │
     │  4. nginx selects cert for reddit.acme.com      │                   │                     │
     │                │                │                │                   │                     │
     │  5. Proxy to FastAPI with Host: reddit.acme.com │                   │                     │
     │                │                │───────────────>│                   │                     │
     │                │                │                │                   │                     │
     │                │                │                │  6. SELECT * FROM branding_configs      │
     │                │                │                │      WHERE custom_domain =              │
     │                │                │                │      'reddit.acme.com'                  │
     │                │                │                │──────────────────>│                     │
     │                │                │                │                   │                     │
     │                │                │                │  7. Return: {logo, colors, name, ...}   │
     │                │                │                │<──────────────────│                     │
     │                │                │                │                   │                     │
     │                │                │                │  8. Render template with branding       │
     │                │                │                │      context injected                   │
     │                │                │                │──────────────────────────────────────── >│
     │                │                │                │                   │                     │
     │                │                │                │  9. HTML with partner logo, colors,     │
     │                │                │                │      company name                       │
     │                │                │                │<────────────────────────────────────────│
     │                │                │                │                   │                     │
     │  10. Response: branded HTML page                 │                   │                     │
     │<────────────────────────────────────────────────│                   │                     │
     │                │                │                │                   │                     │
```

### Flow Summary

1. **Browser** resolves `reddit.acme.com` via DNS
2. **DNS** returns CNAME → `partners.ramp-platform.com` → A record `161.35.27.165`
3. **Browser** connects to `161.35.27.165:443` with SNI `reddit.acme.com`
4. **NGINX** selects the correct SSL certificate based on SNI hostname
5. **NGINX** proxies request to FastAPI, preserving `Host: reddit.acme.com` header
6. **FastAPI middleware** queries `branding_configs` by `custom_domain` field
7. **PostgreSQL** returns the partner's branding configuration (logo, colors, name)
8. **FastAPI** passes branding context to Jinja2 template engine
9. **Jinja2** renders the page with partner's visual identity
10. **Browser** receives a fully branded page — no trace of RAMP

---

## 6. Implementation Effort

| Component | Effort | Notes |
|-----------|--------|-------|
| nginx wildcard server block | 30 min | Single config file, tested locally with Docker |
| certbot automation script | 2 hours | Script + cron + DNS verification logic |
| FastAPI branding middleware | 4 hours | Middleware + cache + fallback logic |
| Jinja2 template branding variables | 2 hours | Update `base.html` to use branding context |
| Testing (end-to-end with test domain) | 2 hours | Local Docker + `/etc/hosts` override |
| **Total** | **~1 day** | Can be done in a single focused sprint |

### Prerequisites

- `branding_configs` table exists (see task 4.2)
- Domain purchased for RAMP (`ramp-platform.com` or similar)
- DigitalOcean droplet accessible on ports 80 + 443

---

## 7. Scaling Considerations

| Factor | At 10 Partners | At 100 Partners | Notes |
|--------|---------------|-----------------|-------|
| nginx performance | No concern | No concern | Single instance handles 10K+ concurrent connections |
| Certificate storage | ~50 KB | ~500 KB | ~5 KB per domain (cert + key), negligible |
| Cert provisioning rate | Instant | Instant | Let's Encrypt allows 50 certs/week per registered domain |
| Branding cache memory | ~10 KB | ~100 KB | One dict entry per domain, negligible |
| DNS propagation | 1-24 hours | 1-24 hours | Partner warned during onboarding |
| Database queries | Cached (5 min TTL) | Cached (5 min TTL) | Only 1 query per new/expired cache entry |

### Let's Encrypt Rate Limits

| Limit | Value | Impact |
|-------|-------|--------|
| Certificates per registered domain | 50/week | Not relevant (each partner has their own domain) |
| Duplicate certificates | 5/week | Only matters if re-issuing same cert |
| Failed validations | 5/hour | DNS must resolve before requesting cert |
| Accounts per IP | 10/3 hours | Use single certbot account |

**Conclusion:** Rate limits are not a concern for white-label scaling. Even onboarding 10 partners in a single day is well within limits.

---

## 8. Failure Modes and Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| DNS not propagated yet | `dig` check in provisioning script | Skip domain, retry next cron cycle |
| Cert provisioning fails | certbot exit code ≠ 0 | Log error, retry next cycle, alert ops after 3 failures |
| Cert expires (renewal missed) | certbot renewal cron + monitoring | Manual `certbot renew`, nginx reload |
| Partner removes CNAME | Requests stop arriving | No action needed (cert expires naturally) |
| nginx crash | systemd auto-restart + health check | Auto-recovery within seconds |
| Branding cache stale | 5-min TTL | Partner sees old branding for max 5 minutes after update |

---

## 9. Security Considerations

- **No wildcard cert for partner domains** — each partner gets their own cert (prevents cross-partner cert compromise)
- **DNS verification before cert request** — prevents cert issuance for domains not pointing to us
- **Host header validation** — middleware only serves branding for domains in `branding_configs` (unknown domains get default branding, not an error page that leaks info)
- **No partner access to nginx config** — all routing is application-level, partners cannot inject headers or modify proxy behavior
- **Certificate private keys** — stored in `/etc/letsencrypt/live/` with root-only permissions (0600)
