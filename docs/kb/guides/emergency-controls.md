# Guide — Emergency Controls

> **Audience:** Owner, Partner  
> **Last updated:** 2026-05-28

---

## Quick Reference — Emergency Actions

| Situation | Immediate Action | Where |
|-----------|-----------------|-------|
| Avatar shadowbanned | Freeze avatar | Avatar detail → Freeze |
| Avatar suspended | Freeze avatar | Avatar detail → Freeze |
| Multiple avatars compromised | Kill pipeline | Settings → `pipeline_enabled` = OFF |
| Bad content generated | Kill generation | Settings → `generation_enabled` = OFF |
| Reddit API issues | Kill scraping | Settings → `scrape_enabled` = OFF |
| Client requests immediate stop | Deactivate client | Client detail → Deactivate |
| Cost spike detected | Kill generation | Settings → `generation_enabled` = OFF |

---

## Kill Switches

### Where to Find
`/admin/settings` → Pipeline Controls section

### Available Switches

| Switch | Default | Effect When OFF |
|--------|---------|----------------|
| `pipeline_enabled` | ON | **Stops everything.** No scraping, scoring, or generation. |
| `generation_enabled` | ON | Stops AI generation. Scraping and scoring continue. |
| `scrape_enabled` | ON | Stops subreddit scraping. Existing data still processed. |

### When to Use Each

**`pipeline_enabled` = OFF** (nuclear option)
- Multiple avatars banned simultaneously
- Suspected platform-wide detection
- Major system malfunction
- During maintenance windows

**`generation_enabled` = OFF**
- AI producing harmful/incorrect content
- LLM API cost spike (runaway loop)
- Need to pause while adjusting prompts/strategy
- Scraping continues so you don't lose data freshness

**`scrape_enabled` = OFF**
- Reddit API returning errors
- Rate limiting detected
- Subreddit configuration changes in progress

### Recovery After Kill Switch

1. Identify and fix the root cause
2. Toggle switch back ON
3. Pipeline resumes on next scheduled run (or trigger manually)
4. Check activity feed to confirm normal operation

---

## Avatar Freeze

### What It Does

Frozen avatar is immediately excluded from:
- Scoring pipeline (won't select threads for this avatar)
- Generation pipeline (won't generate comments)
- Hobby pipeline (won't generate hobby comments)
- EPG generation (no daily plan created)
- Phase evaluation (won't be promoted/demoted)

Frozen avatar retains:
- All existing data (drafts, history, karma records)
- Pending drafts (not auto-rejected)
- Configuration (voice profile, subreddits)

### How to Freeze

1. Go to avatar detail page
2. Click **"Freeze"** button
3. Enter reason (required):
   - "Shadowban detected"
   - "CQS dropped to lowest"
   - "Client requested pause"
   - "Suspicious activity"
   - "Removal rate too high"
4. Confirm

### How to Unfreeze

1. Verify the issue is resolved
2. Go to avatar detail page
3. Click **"Unfreeze"** button
4. Avatar returns to pipeline on next run

### Auto-Freeze Triggers

The system automatically freezes avatars when:
- Shadowban detected (health check at 07:30, 13:30)
- Account suspended by Reddit
- CQS drops to "lowest" (Phase 2+ only)
- 3 consecutive posting failures (automated posting)

---

## Client Deactivation

### What It Does

Deactivating a client cascades:
1. `client.is_active = false`
2. All subreddit assignments deactivated
3. All avatar assignments removed
4. All pipeline tasks skip this client
5. Client users can still login but see "inactive" state

### When to Use

- Client requests pause
- Payment issues
- Contract ended
- Suspected misuse

### How to Deactivate

1. Go to `/admin/clients/{id}`
2. Click **"Deactivate"**
3. Confirm (shows cascade warning)

### How to Reactivate

1. Go to client detail
2. Click **"Activate"**
3. Reassign avatars and subreddits
4. Pipeline resumes on next run

---

## Incident Response Playbook

### Scenario: Single Avatar Shadowbanned

**Severity:** Low (contained to one avatar)

1. System auto-freezes the avatar ✅
2. Verify: check avatar's profile in incognito browser
3. If confirmed shadowbanned:
   - Leave frozen
   - Assign replacement avatar to client (if available)
   - Notify client (if they're aware of specific avatars)
   - Log incident
4. If false positive:
   - Unfreeze
   - Monitor for 24h

### Scenario: Multiple Avatars Banned

**Severity:** High (possible pattern detection)

1. **Immediately:** Toggle `pipeline_enabled` = OFF
2. Freeze all affected avatars
3. Investigate:
   - Same subreddit? (subreddit-level ban)
   - Same IP? (IP-level detection)
   - Same time? (coordinated action by Reddit)
   - Same content pattern? (content-level detection)
4. Based on findings:
   - If subreddit ban: remove that subreddit from all avatars
   - If IP issue: rotate proxies
   - If content pattern: adjust voice profiles and generation strategy
5. Resume cautiously (one avatar at a time)
6. Notify affected clients

### Scenario: Reddit API Down

**Severity:** Medium (no data loss, just delays)

1. Toggle `scrape_enabled` = OFF (prevent error spam)
2. Check Reddit status: https://www.redditstatus.com/
3. Wait for recovery
4. Toggle `scrape_enabled` = ON
5. System auto-catches up (scrapes stale subreddits first)

### Scenario: LLM API Errors

**Severity:** Medium (generation stops, no content risk)

1. Check LLM provider status (Anthropic, Google)
2. If provider down:
   - Toggle `generation_enabled` = OFF
   - Wait for recovery
   - Toggle back ON
3. If our API key issue:
   - Check key validity
   - Check billing/quota
   - Rotate key if needed
4. System has retry logic (3 retries with exponential backoff)

### Scenario: Cost Spike

**Severity:** Medium (financial, not operational)

1. Toggle `generation_enabled` = OFF (stops the expensive part)
2. Check AI Costs page — identify the source
3. Common causes:
   - Scoring running on wrong model (should be Gemini Flash)
   - Generation loop (same thread being re-generated)
   - Too many clients activated simultaneously
4. Fix the root cause
5. Resume generation

### Scenario: Bad Content Posted

**Severity:** High (reputation risk)

1. If still on Reddit: manually delete the comment (login as avatar)
2. Freeze the avatar
3. Investigate:
   - Was it approved by a human? (review process failure)
   - Was it auto-posted without approval? (system bug)
   - Was the voice profile wrong? (configuration issue)
4. Fix root cause
5. Review all pending drafts for similar issues
6. Notify client if they're aware

---

## Monitoring Checklist (Daily)

```
□ All topology nodes green
□ No frozen avatars (unless intentional)
□ Pipeline ran at 08:00 and 14:00
□ No errors in activity feed
□ Review queue not overflowing (< 50 pending)
□ No cost anomalies
□ All clients active (unless intentionally paused)
```

---

## Contacts for Escalation

| Issue | Primary | Backup |
|-------|---------|--------|
| System/infrastructure | Max | — |
| Client communication | Tzvi | Jenny |
| Legal/compliance | Tzvi | — |
| Reddit account issues | Max | — |
| Billing/payment | Tzvi | — |
