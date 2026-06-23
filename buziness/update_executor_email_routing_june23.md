# Update: Per-Avatar Task Email Routing (June 23, 2026)

## What Changed

Previously, ALL posting tasks were emailed to one global address (max.breger@gmail.com).
Now each avatar has its own executor email configured in the admin panel.

## How It Works Now

1. Each avatar has a dedicated "Executor Email" in its Posting tab
2. Email must be marked as "Verified" by admin before tasks are sent
3. If no verified email — tasks are NOT sent (system logs the reason)
4. No global fallback — forces explicit assignment

## What This Means for Operations

- When we hire a new avatar owner, we set their email on their avatars
- One person can own multiple avatars (they get separate emails per task)
- Changing the email resets verification (prevents accidental routing)
- All changes are audit-logged

## Where to Configure

Admin Panel > Avatars > [avatar name] > Posting tab > "Email Task Routing" section

## Action Needed

After deployment, set executor_email on each active avatar that should receive tasks.
Currently no avatars have this field set (new feature).

## Technical

- New fields: `avatar.executor_email`, `avatar.executor_email_verified`
- Migration: `exec01_add_avatar_executor_email`
- Routes: POST `/admin/avatars/{id}/executor-email`, `/verify`, `/unverify`
- Delivery: Brevo HTTP API (unchanged)
