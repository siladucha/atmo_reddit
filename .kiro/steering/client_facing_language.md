# Client-Facing Language Rules

## Purpose

Single source of truth for all compliance terminology rules applied to ANY client-facing surface: marketing site, portal UI, emails, PDFs, sales materials, FAQ, blog posts, onboarding wizard, extension popup.

## Prohibited Terms (NEVER use)

These terms MUST NOT appear in any client-facing text (case-insensitive, whole-word match):

### Category: Platform Mechanics
- "fake accounts", "fake account"
- "bot", "bots" (allowed as substring: "robot", "chatbot")
- "automated posting", "auto-posting"
- "evading detection", "bypassing"
- "violating ToS", "against Reddit rules"
- "terms of service", "ToS", "Reddit rules", "platform rules"
- "rule violation", "policy violation", "against the rules"

### Category: Operational Details
- "VPN", "multi-IP", "proxy", "residential IP", "rotating IP"
- "karma farming", "karma farm"
- "account warming", "account warm-up"
- "warming phase", "warming mechanics"
- "karma levels", "karma threshold" (as requirements)
- "account age requirements"

### Category: Identity
- "avatar", "avatars" → use "voice" or "voices"
- "subreddit", "subreddits" → use "community" or "communities" in marketing/sales (OK in portal/admin)
- "ban", "shadowban", "suspended" (as standalone) → use "restricted" or "limited"

## Required Terms (ALWAYS use instead)

| Instead of | Use |
|-----------|-----|
| avatar | voice / voices |
| fake account | community voice |
| bot / automated tool | human-in-the-loop platform |
| automated posting | community engagement management |
| karma farming | credibility building |
| subreddit (marketing) | community |
| banned/shadowbanned | restricted / limited |
| Reddit rules violation | community guidelines |

## Approved Descriptor Phrases

Every answer/paragraph that explains what RAMP does must include at least one:
- "community engagement management"
- "persona-driven content strategy"
- "human-in-the-loop"

## Context-Specific Rules

### Marketing Site & Sales Materials
- Full prohibition applies
- "subreddit" → "community"
- No operational mechanics of any kind

### Client Portal UI
- "avatar" → "voice" (all visible text)
- "subreddit" is acceptable (technical context, clients understand)
- No operational mechanics exposed to clients

### Admin Panel (owner/partner only)
- Internal terminology acceptable
- "avatar" in code/admin is fine
- "subreddit" acceptable

### Emails (client-facing)
- Full prohibition applies
- Use "voice" not "avatar"

### Code / Internal Docs
- Any terminology acceptable
- "avatar" is the model name — don't rename in code

## Validation

When writing any client-facing text:
1. Scan for prohibited terms (whole-word, case-insensitive)
2. Verify at least one approved phrase present per explanatory paragraph
3. Verify "voice" used instead of "avatar"
4. Verify no operational mechanics exposed
