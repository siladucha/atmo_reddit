# RAMP Browser Extension

Chrome Manifest V3 extension for RAMP — Execution Node for Reddit tasks.

## What it does

- **CQS Probes**: Posts "What is my CQS?" in r/WhatIsMyCQS, reads bot reply, reports to backend
- **Comment Posting**: Receives signed tasks from RAMP, posts comments in Reddit threads
- **Health Monitoring**: Passively detects ban indicators, reports signals
- **Submission Visibility**: Checks if a post is visible in subreddit /new feed

## Installation

See [INSTALL.md](./INSTALL.md) for executor setup and admin distribution guide.

## Architecture

```
Extension (untrusted execution)     RAMP Backend (sole authority)
├── Service Worker (background)     ├── /api/extension/policy
│   ├── Poller (GET /tasks)         ├── /api/extension/tasks
│   ├── Heartbeat (POST /hb)       ├── /api/extension/report
│   ├── Queue (chrome.storage)      ├── /api/extension/heartbeat
│   └── Timer (scheduled_at)        └── /api/extension/register
├── Content Script (reddit.com)
│   ├── Reddit variant detection
│   ├── postComment()
│   ├── postCQSCheck()
│   └── checkSubmissionVisibility()
└── Popup (task queue UI)
    ├── Approve/Reject tasks
    ├── Connection status
    └── Activity history
```

## Development

```bash
# Install dependencies (minimal — no build needed for MV3)
npm install

# Load in Chrome:
# 1. chrome://extensions
# 2. Enable "Developer mode"
# 3. "Load unpacked" → select this directory
```

## Modes

- **REQUIRED_UI** (MVP): Popup shows tasks, executor must approve each one
- **OPTIONAL** (Phase 2): Auto-execute, popup shows activity
- **DISABLED** (Phase 2): Invisible runtime, diagnostics only

## Security

- Extension NEVER sends cookies/passwords/tokens to RAMP
- All tasks signed with HMAC (verified via HTTPS + JWT)
- Extension cannot generate or modify tasks
- Reports are untrusted — backend validates all state transitions
- Minimal permissions: reddit.com + gorampit.com API only
