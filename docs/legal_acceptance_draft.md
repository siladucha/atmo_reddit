# Legal Acceptance Flow — Draft for Tzvi

## When It Appears
- First login after client account creation (onboarding step 1)
- Cannot proceed without accepting
- Acceptance logged in `audit_log` with timestamp + user_id + IP

## UI: Modal Dialog (blocking)

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  ⚠️  Platform Terms & Risk Acknowledgment              │
│                                                         │
│  Before using [PLATFORM NAME], please review and        │
│  accept the following terms:                            │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │                                                   │  │
│  │  1. SERVICE DESCRIPTION                           │  │
│  │  This platform provides community engagement      │  │
│  │  management tools. Content is generated with AI   │  │
│  │  assistance and published by human operators      │  │
│  │  ("Digital Asset Owners") on your behalf.         │  │
│  │                                                   │  │
│  │  2. PLATFORM RISK ACKNOWLEDGMENT                  │  │
│  │  You acknowledge that social media platforms may  │  │
│  │  restrict or suspend accounts used in connection  │  │
│  │  with this service ("Platform Enforcement         │  │
│  │  Events"). Such events are not compensable and    │  │
│  │  do not constitute service failure.               │  │
│  │                                                   │  │
│  │  3. CONTENT APPROVAL LIABILITY                    │  │
│  │  All content requires your explicit approval      │  │
│  │  before publication. Once you approve content,    │  │
│  │  responsibility for that content transfers to     │  │
│  │  you. You are responsible for FTC/advertising     │  │
│  │  compliance in your jurisdiction.                 │  │
│  │                                                   │  │
│  │  4. DIGITAL ASSETS                                │  │
│  │  Avatars ("Digital Assets") are service access    │  │
│  │  tools, not your property. No refund is issued    │  │
│  │  if a Digital Asset becomes unavailable due to    │  │
│  │  Platform Enforcement Events.                     │  │
│  │                                                   │  │
│  │  5. CONFIDENTIALITY                               │  │
│  │  You agree not to disclose the operational        │  │
│  │  methods of this platform to third parties.       │  │
│  │  All engagement activities should be described    │  │
│  │  externally as "managed brand presence" or        │  │
│  │  "community engagement management."              │  │
│  │                                                   │  │
│  │  6. LIABILITY CAP                                 │  │
│  │  Total liability is limited to 3 months of       │  │
│  │  fees paid. No consequential damages.            │  │
│  │                                                   │  │
│  │  7. IMMEDIATE SUSPENSION                          │  │
│  │  We reserve the right to suspend service          │  │
│  │  immediately if elevated platform risk is         │  │
│  │  detected, without prior notice.                  │  │
│  │                                                   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ☐ I have read and accept these terms                   │
│  ☐ I understand that Platform Enforcement Events are    │
│    not compensable                                      │
│                                                         │
│  [Cancel]                        [Accept & Continue]    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Database

Add to `clients` table:
- `terms_accepted_at: DateTime | None`
- `terms_accepted_by: UUID | None` (user who accepted)
- `terms_version: String | None` (e.g. "1.0")

## Backend Logic

```python
# In auth middleware or client access check:
if user.role in ("client_admin", "client_manager", "client_viewer"):
    if not client.terms_accepted_at:
        # Redirect to acceptance page
        return RedirectResponse("/accept-terms")
```

## Audit Trail

Every acceptance creates an `AuditLog` entry:
```json
{
  "action": "terms_accepted",
  "user_id": "...",
  "client_id": "...",
  "metadata": {
    "version": "1.0",
    "ip_address": "...",
    "user_agent": "...",
    "checkboxes_checked": ["terms", "enforcement_events"]
  }
}
```

## Notes for Tzvi
- [ ] Review legal text with lawyer
- [ ] Decide on platform name (placeholder: [PLATFORM NAME])
- [ ] Confirm liability cap period (currently 3 months)
- [ ] Add any jurisdiction-specific clauses (Cyprus/Israel/US)
- [ ] Decide if separate NDA document needed or this covers it
