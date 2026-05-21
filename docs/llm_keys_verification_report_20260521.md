# LLM API Keys — Verification Report

**Date:** May 21, 2026  
**Performed by:** Max  
**Triggered by:** Tzvi sent new API keys (email May 20, 2026)

---

## Summary

| Check | Status |
|-------|--------|
| Backup old keys | ✅ Done |
| DEV keys → local `.env` | ✅ Configured |
| PROD keys → server `/app/.env` | ✅ Configured |
| Gemini (scoring) — local | ✅ PASS |
| Claude (generation) — local | ✅ PASS |
| Gemini (scoring) — production | ✅ PASS |
| Claude (generation) — production | ✅ PASS |
| Graceful error handling (502→maintenance page) | ✅ Deployed |

---

## Keys Installed

| Environment | Anthropic Key | Gemini Key |
|-------------|---------------|------------|
| DEV (local) | `sk-ant-api03-4chb...` | `AIzaSyBws0hi...` |
| PROD (server) | `sk-ant-api03-qS4y...` | `AIzaSyD6dxZ3...` |

Both keys have spending limits set by Tzvi in provider consoles.

---

## Model Update

Old models were deprecated/unavailable on new keys:

| Role | Old Model | New Model |
|------|-----------|-----------|
| Scoring | `gemini/gemini-2.0-flash` | `gemini/gemini-2.5-flash` |
| Generation | `anthropic/claude-sonnet-4-20250514` | `anthropic/claude-sonnet-4-6` |

---

## Test Results — Local (DEV keys)

```
Gemini 2.5 Flash (scoring):
  Status: PASS
  Response: "OK"
  Latency: 961ms
  Tokens: 8 in / 6 out

Claude Sonnet 4.6 (generation):
  Status: PASS
  Response: "OK"
  Latency: 5,592ms
  Tokens: 14 in / 4 out
```

---

## Test Results — Production (PROD keys, 161.35.27.165)

```
Gemini 2.5 Flash (scoring):
  Status: PASS
  Response: "OK"
  Latency: 894ms

Claude Sonnet 4.6 (generation):
  Status: PASS
  Response: "OK"
  Latency: 2,012ms
```

Health check: `{"version":"0.1.0","database":"ok","redis":"ok","status":"ok"}`

---

## Infrastructure Fix: Graceful Error Handling

**Problem:** When app container restarts, nginx returned raw `502 Bad Gateway` — unprofessional, confusing for users.

**Fix applied:**
- Added `proxy_intercept_errors on` to nginx config
- Custom `error_page 502 503 504 /maintenance.html`
- Maintenance page: dark theme, "System Update in Progress", auto-refresh every 10 seconds
- Mounted `nginx/maintenance.html` as volume in docker-compose

**Result:** During restarts, users see a branded maintenance page that auto-refreshes when app comes back. No more raw 502.

**Deployed to:** both local and production.

---

## Backups

- `.env.backup.20260521_122735` (local, old empty keys)
- `.env.production.backup.20260521_122735` (production template)

---

## Action Items

- [x] Replace keys locally (DEV)
- [x] Replace keys on server (PROD)
- [x] Update model names (deprecated → current)
- [x] Verify both models respond on both environments
- [x] Fix 502 error handling (maintenance page)
- [ ] Research budget key (OpenRouter) — pending Tzvi's approval
