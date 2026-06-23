# Security Update — Auto-Logout on Inactivity

**For:** Tzvi
**From:** Max
**Date:** June 23, 2026
**Status:** Deployed

---

## What's New

The platform now automatically logs out any user after **10 minutes of inactivity**.

### How It Works

1. If a user is logged in but doesn't interact with the page (no mouse movement, clicks, scrolling, or typing) for 9 minutes — a **yellow warning banner** appears at the top of the screen:

   > ⚠️ Session expires in 60 seconds due to inactivity

2. If the user still does nothing for 60 more seconds — they are **automatically logged out** and redirected to the login page.

3. **Any activity resets the timer** — just moving the mouse is enough.

### Who Is Affected

Everyone — owners, partners, client admins, client managers, client viewers, avatar managers.

---

## Why This Matters

| Concern | How Auto-Logout Helps |
|---------|----------------------|
| **Security** | Prevents someone from accessing the system on an unattended laptop/browser |
| **Client trust** | Shows we take access control seriously (enterprise clients expect this) |
| **Compliance** | Standard security practice for SaaS platforms handling client data |

---

## What Users Should Know

- If they're actively working, nothing changes — the timer resets on any interaction
- If they step away for coffee (>10 min), they'll need to log back in
- The warning gives 60 seconds to come back and prevent logout
- HTMX actions (clicking buttons, loading data) also count as activity

---

## No Action Needed From You

This is a security improvement that works automatically. No configuration required.
