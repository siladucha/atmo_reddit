# Next Session — Extension v3 (Old Reddit)

## Context

Extension v2 (chrome.debugger) failed because:
- `faceplate-textarea-input` exists on page but GET_ELEMENT_COORDS returns null from content script after auto-navigation
- Shadow DOM + isTrusted checks make new Reddit unreliable
- reCAPTCHA Enterprise blocks API-based posting

Solution: Switch to old.reddit.com (stable DOM, plain textarea, no captcha).

## Files Created

- `background/executor-old-reddit.js` — new executor (replaces executor.js for posting)
- `content/old-reddit-actions.js` — content script for old.reddit.com
- `.kiro/steering/extension_v3_old_reddit.md` — architecture doc

## TODO (next session)

### 1. Wire up the new executor

In `scheduler.js`, replace:
```js
import { executeTask } from './executor.js';
```
with:
```js
import { executeTaskOldReddit } from './executor-old-reddit.js';
```

And in `_doTick()` change `executeTask(dueTask, tab.id)` → `executeTaskOldReddit(dueTask, tab.id)`.

### 2. Update manifest.json

Add old.reddit.com to content scripts:
```json
"content_scripts": [
  {
    "matches": ["https://www.reddit.com/*", "https://old.reddit.com/*"],
    "js": ["content/bundle.js"]
  },
  {
    "matches": ["https://old.reddit.com/*"],
    "js": ["content/old-reddit-actions.js"]
  }
]
```

Remove `"debugger"` permission (no longer needed!):
```json
"permissions": ["storage", "alarms", "notifications", "tabs", "scripting"]
```

### 3. Update host_permissions

```json
"host_permissions": [
  "https://www.reddit.com/*",
  "https://old.reddit.com/*",
  "https://gorampit.com/api/extension/*",
  "http://localhost:8000/*"
]
```

### 4. Popup: timeline UI

Replace current popup with unified day timeline:
- All tasks chronologically
- Status badge per task (pending/approved/queued/executing/posted/failed)
- Action buttons only where needed
- EPG data from /dashboard endpoint

### 5. Chrome notification on AUTH_FAILED

```js
chrome.notifications.create('auth-expired', {
  type: 'basic',
  title: 'RAMP: Reddit session expired',
  message: 'Please log in to Reddit to continue automated posting.',
  iconUrl: 'assets/icon-48.png',
});
```

### 6. Auto-reset dom_health on extension reload

In service-worker.js startup:
```js
chrome.storage.local.set({ ramp_health: { dom_health: 'ok', reddit_session_valid: true, last_task_executed_at: null, dom_health_since: null } });
```

### 7. Test

1. Reload extension
2. Open old.reddit.com (verify logged in)
3. Force a task to execute now
4. Watch service worker logs for success
5. Check r/test for posted comment

### 8. After success — remove debugger code

- Remove `background/debugger-engine.js` (no longer needed)
- Remove `background/executor.js` (replaced by executor-old-reddit.js)
- Remove `"debugger"` permission
- Simplify content/bundle.js (remove Shreddit-specific code)

## Key Insight

Old Reddit posting is literally:
```js
textarea.value = "comment text";
document.querySelector('.save').click();
// Done. That's it.
```

No Shadow DOM. No Lexical. No debugger. No isTrusted. No reCAPTCHA.


## 9. Chrome Notifications for Executor

Extension must notify executor when something requires attention:

### When to notify:

1. **Reddit session expired** — `CHECK_AUTH` returns `expired: true`
   - Notification: "RAMP: Reddit session expired. Please log in to Reddit."
   - Trigger: health monitor detects expired + was previously valid

2. **No Reddit tab available** — scheduler can't find a Reddit tab to execute
   - Notification: "RAMP: Please open Reddit in a tab for auto-posting."
   - Trigger: 3 consecutive scheduler ticks without available Reddit tab

3. **dom_health broken** — 3+ consecutive DOM failures
   - Notification: "RAMP: Reddit changed something. Auto-posting paused, tasks go via email."
   - Trigger: health monitor transitions to "broken"

### Implementation:

```js
// In health-monitor.js or scheduler.js:
chrome.notifications.create('reddit-session-expired', {
  type: 'basic',
  title: 'RAMP: Reddit session expired',
  message: 'Please log in to Reddit to continue automated posting.',
  iconUrl: 'assets/icon-48.png',
  priority: 2,
});
```

### Rules:
- Max 1 notification per type per hour (debounce)
- Clear notification when issue resolves (session restored, tab opened)
- RAMP backend gets health status via heartbeat regardless (dom_health, reddit_session_valid)
- Backend can fall back to email delivery when extension reports problems

### Popup UI changes:
- If `reddit_session_valid: false` → show red badge "Reddit: ✗" + message "Please log in"
- If no Reddit tab → show "Open Reddit tab" hint
- These are already partially in place, just need notification trigger
