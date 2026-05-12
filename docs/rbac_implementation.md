# RBAC Implementation — May 12, 2026

## Summary

Role-based access control implemented. Replaces binary `is_superuser` with 6 granular roles.

## Roles

| Role | Who | Access |
|------|-----|--------|
| `owner` | Max | Everything. Kill switches, system settings, infrastructure. |
| `partner` | Tzvi | All clients, onboarding, reports, user management. No system settings. |
| `qa` | Jenny | Cross-client reviewer. Can approve/reject all clients. Can warm own avatars (farm). |
| `client_manager` | B2B client contact | Own client only. Review, add subreddits/keywords. |
| `client_viewer` | B2B read-only | Own client only. Dashboard + reports. No approve/reject. |
| `b2c_user` | Self-service | 1 avatar, simplified UI. If wants more → becomes client. |

## Key Design Decisions

1. **Backward compatible** — `is_superuser` field kept. `user_role` property falls back to legacy logic if `role` column is empty.
2. **Partner = admin panel access** — Tzvi sees admin panel but cannot touch kill switches or system settings.
3. **QA = cross-client reviewer** — Jenny can review all clients' drafts. Can also warm personal avatars (farm for future client assignment).
4. **B2C = 1 avatar cap** — if they want more, they upgrade to client_manager tier.
5. **Registration closed** — `/register` now redirects to `/login`. Users created only via admin panel.
6. **Avatar farm** — owner, partner, qa can all warm personal avatars that can later be assigned to clients.

## Files Changed

| File | Change |
|------|--------|
| `app/models/user_role.py` | **NEW** — UserRole enum with permission properties |
| `app/models/user.py` | Added `role` column + `user_role` property |
| `app/models/__init__.py` | Export UserRole |
| `app/dependencies/admin.py` | Updated to accept partner role |
| `app/dependencies/roles.py` | **NEW** — `require_role()`, `require_admin`, `require_internal`, `require_reviewer`, `require_owner` |
| `app/routes/pages.py` | Role-based routing, closed registration, role-aware access checks |
| `app/routes/admin.py` | User creation with role dropdown, avatar strategy enrichment on client detail |
| `app/templates/base.html` | Role-specific nav + badges (👑 Owner, 🤝 Partner, 🔍 QA, 👤 Client) |
| `app/templates/admin_users.html` | Role dropdown in create form, updated guide |
| `app/templates/partials/admin_user_row.html` | Role badge display |
| `app/templates/admin_client_detail.html` | Enriched avatar section (phase, health, CQS, strategy status) |
| `alembic/versions/z6a7b8c9d0e1_add_user_role_field.py` | Migration: adds `role` column, migrates existing users |

## Migration

```sql
-- Adds role column, migrates existing data:
-- is_superuser=True → 'owner'
-- is_superuser=False + client_id → 'client_manager'  
-- is_superuser=False + no client → 'qa'
```

Run: `alembic upgrade head`

## Avatar Strategy on Client Detail Page

Each avatar now shows:
- **Phase** (Mentor/1/2/3) with color coding
- **Active/Frozen/Inactive** status
- **Health** (healthy/shadowbanned/suspended)
- **CQS level** (if checked)
- **Strategy status** (✅ Approved v{N} / ⚠️ Draft v{N} / ❌ No Strategy)
- Clickable → links to avatar detail page

## How to Create a Client Login

1. Go to `/admin/users`
2. Fill: email, password, full name
3. Select role: "👤 Client Manager" (or "👁️ Client Viewer" for read-only)
4. Select client from dropdown
5. Click "Create User"
6. Share credentials with client

Client logs in → lands on their Client Hub → sees only their data.
