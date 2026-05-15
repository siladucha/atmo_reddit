# Permission Matrix — RBAC & Client Data Isolation

## Deny-by-Default Principle

**Any role-resource-action combination not explicitly listed as "allowed" in this matrix is DENIED by default.**

If a role is not listed for a resource, or an action is not marked as allowed, the system will return HTTP 403 "Access Denied". This applies to all API endpoints, UI pages, query scoping, and LLM context assembly.

---

## Roles

| Role | Scope | Description |
|------|-------|-------------|
| `owner` | All resources | Full system access. Platform owner (Max). |
| `partner` | All clients | Business admin (Tzvi, Jenny). All clients, user management, analytics, audit logs. NO system settings or kill switches. |
| `client_admin` | Own company only | B2B company administrator. Manages team, avatars, approves drafts, configures client settings. |
| `client_manager` | Own company only | B2B client contact. Approves/rejects drafts, manages subreddits/keywords. Cannot manage users or delete avatars. |
| `client_viewer` | Own company only | B2B read-only. Dashboard + reports. Can approve drafts only if `draft_approval_enabled=True` on client record. |
| `b2c_user` | Own avatar only | Self-service individual. Single avatar limit enforced. |

---

## Permission Matrix

### 1. Client Data (read/write)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company) | denied |
| Write | allowed | allowed | scoped (own company) | denied | denied | denied |

### 2. Avatars — Owned (read/create/delete)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company) | scoped (own avatar only) |
| Create | allowed | allowed | scoped (own company, max_avatars limit) | denied | denied | denied (single avatar limit) |
| Delete | allowed | allowed | scoped (own company) | denied | denied | denied |

### 3. Avatars — Rented (read/use)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company, active rentals only) | scoped (own company, active rentals only) | scoped (own company, active rentals only) | denied |
| Use (select for generation) | allowed | allowed | scoped (own company, active rentals only) | scoped (own company, active rentals only) | denied | denied |

### 4. Avatar Farm / Rentals (manage)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| View farm inventory | allowed | allowed | denied | denied | denied | denied |
| Create rental | allowed | allowed | denied | denied | denied | denied |
| Deactivate rental | allowed | allowed | denied | denied | denied | denied |
| Set rent price | allowed | denied | denied | denied | denied | denied |

### 5. Subreddits (read/create/delete)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company) | scoped (own avatar only) |
| Create / assign | allowed | allowed | scoped (own company) | scoped (own company) | denied | denied |
| Delete / unassign | allowed | allowed | scoped (own company) | denied | denied | denied |

### 6. Threads (read)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company) | scoped (own avatar only) |

### 7. Comment Drafts (read/approve/reject/edit)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company) | scoped (own avatar only) |
| Approve | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company, if `draft_approval_enabled`) | scoped (own avatar only) |
| Reject | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company, if `draft_approval_enabled`) | scoped (own avatar only) |
| Edit | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company, if `draft_approval_enabled`) | scoped (own avatar only) |

### 8. Post Drafts (read/approve/reject)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company) | scoped (own avatar only) |
| Approve | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company, if `draft_approval_enabled`) | scoped (own avatar only) |
| Reject | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company, if `draft_approval_enabled`) | scoped (own avatar only) |

### 9. Activity Events (read)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | allowed | scoped (own company) | scoped (own company) | scoped (own company) | scoped (own avatar only) |

### 10. System Settings (read/write)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read | allowed | denied | denied | denied | denied | denied |
| Write | allowed | denied | denied | denied | denied | denied |

### 11. Kill Switches (toggle)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Toggle | allowed | denied | denied | denied | denied | denied |

### 12. User Management (create/edit/deactivate)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Create any role | allowed | allowed | denied | denied | denied | denied |
| Create client_manager/client_viewer | allowed | allowed | scoped (own company) | denied | denied | denied |
| Edit | allowed | allowed | scoped (own company, client_manager/client_viewer only) | denied | denied | denied |
| Deactivate | allowed | allowed | scoped (own company, client_manager/client_viewer only) | denied | denied | denied |

### 13. AI Cost Analytics (read)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read (all clients) | allowed | allowed | denied | denied | denied | denied |

### 14. Audit Logs (read)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Read (all clients) | allowed | allowed | denied | denied | denied | denied |

### 15. Pipeline Triggers (manual trigger)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` |
|--------|---------|-----------|----------------|------------------|-----------------|------------|
| Trigger (all clients) | allowed | allowed | denied | denied | denied | denied |
| Trigger (own company) | allowed | allowed | scoped (own company) | denied | denied | denied |

---

## Scope Definitions

| Scope | Meaning |
|-------|---------|
| **allowed** | Full access, no restrictions |
| **denied** | Access blocked, returns HTTP 403 |
| **scoped (own company)** | Access limited to records belonging to the user's assigned `client_id` |
| **scoped (own avatar only)** | Access limited to the user's single personal avatar and its associated data |
| **scoped (own company, active rentals only)** | Access limited to avatars rented by the user's company with `is_active=true` and `expires_at > now` (or null) |
| **scoped (own company, if `draft_approval_enabled`)** | Access granted only if the client record has `draft_approval_enabled=True`; otherwise denied |
| **scoped (own company, max_avatars limit)** | Access granted but enforces `client.max_avatars` cap on creation |

---

## Additional Rules

1. **Inactive users** (`is_active=False`) are redirected to `/login` regardless of role.
2. **Inactive clients** (`is_active=False`) cause all scoped users to receive HTTP 403 on any request.
3. **Expired avatar rentals** (`expires_at < now` or `is_active=False`) are hidden from the client's avatar list automatically.
4. **Background tasks** (Celery workers) use `system_context()` which bypasses user-based scoping and logs the caller in the audit trail.
5. **LLM context assembly** enforces client isolation at runtime — any cross-client data detected triggers an abort and security error log.
6. **`client_admin` cannot create another `client_admin`** — only `owner` or `partner` can assign the `client_admin` role.
7. **`b2c_user` single avatar limit** — attempting to create a second avatar returns HTTP 403 with "B2C users can have only one avatar".
8. **Mobile app avatar ownership** — all `/api/mobile/*` endpoints validate that the draft/avatar belongs to the authenticated user via `avatar_assignments` table. Unauthorized access returns HTTP 403.
9. **Mobile posting audit** — all confirm-posted and skip actions from mobile are logged in `audit_log` with `details.source = 'mobile_app'` and in `posting_events` table with device/IP info.

---

## 16. Mobile Posting (queue/confirm/skip)

| Action | `owner` | `partner` | `client_admin` | `client_manager` | `client_viewer` | `b2c_user` | `avatar_owner` (via assignment) |
|--------|---------|-----------|----------------|------------------|-----------------|------------|-------------------------------|
| View posting queue | allowed | allowed | denied | denied | denied | denied | scoped (assigned avatars only) |
| Confirm posted | allowed | allowed | denied | denied | denied | denied | scoped (assigned avatars only) |
| Skip draft | allowed | allowed | denied | denied | denied | denied | scoped (assigned avatars only) |
| View own stats | allowed | allowed | denied | denied | denied | denied | scoped (own stats only) |
| Register device | allowed | allowed | denied | denied | denied | denied | allowed |
| View all owners' stats | allowed | allowed | denied | denied | denied | denied | denied |
| Assign avatars to owners | allowed | allowed | denied | denied | denied | denied | denied |

**Note:** "avatar_owner" is not a separate role — it's any user with active records in `avatar_assignments`. The mobile API checks assignment, not role. An `owner` or `partner` can also use the mobile app if they have avatar assignments.

---

## Revision History

| Date | Change Summary |
|------|---------------|
| 2025-06-06 | Initial creation. Full permission matrix covering 6 roles × 15 resource categories. Implements Requirements 11.1–11.7 from RBAC & Client Data Isolation spec. |
| 2026-05-13 | Added Mobile Posting App permissions (Section 16). Avatar owners can view queue, confirm posted, skip drafts for their assigned avatars only. |
