# Extension v2 — Technical Design

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Popup (Day Schedule UI)                                      │
│  - Mini dashboard (karma, CQS, phase)                       │
│  - Timeline: pending → [Edit/Approve/Skip] → approved       │
│  - Approve All button                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │ chrome.runtime.sendMessage
┌──────────────────────────▼──────────────────────────────────┐
│ Service Worker (Orchestrator)                                │
│  - Task queue (chrome.storage.local)                        │
│  - Scheduler: checks every 15s for due approved tasks       │
│  - Dispatches execution via Debugger Engine                 │
│  - Reports results to backend                               │
└──────────┬───────────────────────────────┬──────────────────┘
           │                               │
┌──────────▼──────────┐    ┌──────────────▼───────────────────┐
│ Debugger Engine      │    │ Content Script                    │
│ (NEW component)      │    │ (reddit-actions.js)               │
│                      │    │                                   │
│ - attach(tabId)      │    │ - VERIFY_CONTEXT                  │
│ - getElementCoords() │    │ - INSERT_TEXT (InputEvent)         │
│ - trustedClick(x,y)  │    │ - CHECK_SUBMIT_BUTTON             │
│ - detach(tabId)      │    │ - WAIT_FOR_COMPOSER (MutObserver) │
│                      │    │ - VERIFY_POSTED (find new comment)│
└──────────────────────┘    └───────────────────────────────────┘
```

## Execution Flow (per task)

```
1. Scheduler finds approved task with scheduled_at ≤ now
2. Navigate to thread URL (chrome.tabs.update)
3. Wait for page load + content script ready
4. VERIFY_CONTEXT → ok
5. Clear localStorage drafts
6. Attach debugger to tab
7. Get coordinates of trigger-button[last] via content script
8. Debugger: trustedClick at coordinates → composer opens
9. Detach debugger
10. Wait 3s for Lexical init
11. INSERT_TEXT via content script (InputEvent strategy)
12. Verify text inserted (char_count ≥ 5, text_matches)
13. Attach debugger
14. Get coordinates of submit button
15. Debugger: trustedClick at coordinates → comment submitted
16. Detach debugger
17. VERIFY_POSTED: wait for new comment in DOM (30s)
18. Extract permalink + comment_id
19. Report task_completed to backend
20. Update local state → mark task as "posted"
```

## Debugger Engine (NEW: `background/debugger-engine.js`)

```javascript
export async function trustedClick(tabId, selector, shadowSelector = null) {
  // 1. Get element coordinates via content script
  const coords = await chrome.tabs.sendMessage(tabId, {
    type: 'GET_ELEMENT_COORDS',
    selector,
    shadowSelector,  // e.g. '#innerTextArea' inside shadow root
  });

  if (!coords) throw new Error('Element not found for click');

  // 2. Attach debugger
  await chrome.debugger.attach({tabId}, '1.3');

  // 3. Dispatch trusted mouse events at element center
  const x = coords.x + coords.width / 2;
  const y = coords.y + coords.height / 2;

  await chrome.debugger.sendCommand({tabId}, 'Input.dispatchMouseEvent', {
    type: 'mousePressed', x, y, button: 'left', clickCount: 1
  });
  await chrome.debugger.sendCommand({tabId}, 'Input.dispatchMouseEvent', {
    type: 'mouseReleased', x, y, button: 'left', clickCount: 1
  });

  // 4. Detach
  await chrome.debugger.detach({tabId});
}
```

## Content Script: GET_ELEMENT_COORDS handler

```javascript
case 'GET_ELEMENT_COORDS': {
  const { selector, shadowSelector } = message;
  let el = document.querySelector(selector);
  if (el && shadowSelector && el.shadowRoot) {
    el = el.shadowRoot.querySelector(shadowSelector);
  }
  if (!el) { sendResponse(null); return; }
  const rect = el.getBoundingClientRect();
  sendResponse({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });
  return false;
}
```

## Popup v3 Design

```
┌─────────────────────────────────────┐
│ RAMP v3        ● Connected          │
│ u/Hot-Thought2408   Reddit✓ RAMP✓   │
├─────────────────────────────────────┤
│ +2 karma │ HIGH cqs │ Phase 1       │
│ 0 posted │ 3 pending│ 0 failed      │
├─────────────────────────────────────┤
│ [✓ Approve All]                     │
├─────────────────────────────────────┤
│ TODAY Jul 2                         │
│                                     │
│ ⏰ 14:30 r/Austin                   │
│ "The trick is meal prep on Sun..."  │
│ [Edit✏️] [✓] [✗]                    │
│                                     │
│ 📋 17:45 r/whoop                    │
│ "Heart rate zones tell more..."     │
│ [Edit✏️] [✓] [✗]                    │
│                                     │
│ 🔧 -- CQS Check                    │
│ Auto                                │
│                                     │
│ ── completed ──────────────────     │
│ ✅ 09:15 r/sysadmin   Posted        │
├─────────────────────────────────────┤
│ Dashboard ↗            Updated 12:01│
└─────────────────────────────────────┘
```

## Manifest Changes

```json
{
  "permissions": [
    "storage",
    "alarms",
    "notifications",
    "tabs",
    "scripting",
    "debugger"   // ← NEW
  ]
}
```

## Backend Changes

### Heartbeat extended:
```json
{
  "execution_node_id": "...",
  "active_reddit_username": "Hot-Thought2408",
  "reddit_session_valid": true,
  "dom_health": "healthy|degraded|broken",
  "last_task_executed_at": "2026-07-02T09:15:00Z",
  "consecutive_failures": 0,
  "extension_version": "2.0.0"
}
```

### New endpoint: PATCH /api/extension/tasks/{task_id}/edit
```json
{
  "edited_text": "Modified comment text by executor"
}
```

### Task delivery extended:
```json
{
  "task_id": "...",
  "status": "pending_approval",  // NEW status for extension
  "scheduled_at": "2026-07-02T14:30:00+03:00",
  "task_type": "epg|manual|diagnostic",
  ...
}
```

## Migration from v1

- v1 popup.html/js/css → replaced entirely
- v1 state-machine.js EXPAND_EDITOR via shadow click → replaced by debugger-engine.js
- v1 INSERT_TEXT → kept (InputEvent strategy works)
- v1 CHECK_SUBMIT_BUTTON → replaced by debugger trustedClick on submit
- v1 poller/heartbeat/queue → kept, extended
- New file: background/debugger-engine.js
- New file: background/scheduler.js (replaces timer.js for auto-execution)
