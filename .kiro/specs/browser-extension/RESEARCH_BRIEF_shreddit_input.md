# Research Brief: Shreddit Comment Composer — Text Input Problem

## Status: BLOCKED — needs deep DOM/framework analysis

## Problem Statement

RAMP browser extension cannot programmatically insert text into Reddit's comment composer on the new "shreddit" UI (Lit-based Web Components). All standard DOM manipulation methods fail silently — text doesn't appear in the field, and submit sends empty content.

The state machine reports "COMPLETED" (false positive) because `execCommand('insertText')` returns `true` but the framework's internal state is NOT updated.

---

## What We Know

### Reddit's Comment Composer Architecture (from live DOM inspection, June 29 2026)

```
<comment-composer-host>
  └── <faceplate-form action="/svc/shreddit/t3_XXX/create-comment" method="post">
      └── <shreddit-composer name="content" mode="richText" required>
          ├── <div slot="rte" class="cursor-text"> ← contenteditable appears HERE after expand
          ├── <button id="comment-composer-submit-button" type="submit" slot="submit-button">
          └── <button id="comment-composer-cancel-button" type="reset" slot="cancel-button">
```

### Two-Phase Lazy Loading

1. **Collapsed state**: `<faceplate-textarea-input data-testid="trigger-button" placeholder="Вступить в беседу">` — a fake input
2. **After click**: `<shreddit-composer>` activates, `<div contenteditable="true">` appears inside the `slot="rte"` div

### What's Been Tried (ALL FAILED)

| Method | Result | Why it fails |
|--------|--------|-------------|
| `element.value = text` | N/A | It's a div, not textarea |
| `element.textContent = text` | DOM changes, framework ignores | Lit doesn't detect external DOM mutation |
| `element.innerHTML = '<p>text</p>'` | DOM changes, framework ignores | Same — bypasses reactive system |
| `document.execCommand('insertText', false, text)` | Returns `true` but text doesn't persist | Likely: Lit observes only its own model, not DOM |
| `InputEvent('beforeinput', {inputType: 'insertText', data: text})` | Framework ignores | Not a real browser-dispatched event (isTrusted=false) |
| `ClipboardEvent('paste', {clipboardData: dt})` | Framework ignores | isTrusted=false |
| `Selection API + execCommand` | Returns true, 0 chars visible | Same as plain execCommand |
| Direct `dispatchEvent(new Event('input'))` | No effect | Framework doesn't listen on generic input |

### Key Insight: `isTrusted` Property

All programmatically-created events have `isTrusted: false`. Reddit's Lit framework (or the RTE library inside `shreddit-composer`) likely checks `event.isTrusted` and ignores synthetic events.

**Only real user actions produce `isTrusted: true` events.** This cannot be faked from content script JavaScript.

---

## Possible Solutions to Investigate

### 1. `chrome.debugger` API (Input.dispatchKeyEvent)

Chrome DevTools Protocol allows dispatching "trusted" keyboard events via `Input.dispatchKeyEvent`. These events have `isTrusted: true` because they come from the browser engine, not JavaScript.

```javascript
chrome.debugger.attach({tabId}, "1.3");
chrome.debugger.sendCommand({tabId}, "Input.dispatchKeyEvent", {
  type: "keyDown", key: "H", code: "KeyH", text: "H"
});
// ... for each character
chrome.debugger.sendCommand({tabId}, "Input.dispatchKeyEvent", {
  type: "char", text: "H"
});
chrome.debugger.sendCommand({tabId}, "Input.dispatchKeyEvent", {
  type: "keyUp", key: "H", code: "KeyH"
});
```

**Pros:** Produces real trusted events. Works with any framework.
**Cons:** Requires `debugger` permission. Chrome shows a yellow "debugger attached" bar to user. Slow (per-character). Need to focus element first.

### 2. `Input.insertText` via CDP (simpler than keyDown)

```javascript
chrome.debugger.sendCommand({tabId}, "Input.insertText", {
  text: "Full comment text here"
});
```

**Pros:** Inserts full text at once (fast). Trusted. Works in any focused contenteditable.
**Cons:** Same debugger bar issue. Need element focused first.

### 3. `chrome.scripting.executeScript` with `world: "MAIN"`

Run script in the page's JS context (not isolated world). This gives access to the Lit component's internal API:

```javascript
// In MAIN world, we can access the component's internal state
const composer = document.querySelector('shreddit-composer');
// Access Lit internals — component._value or similar
// Depends on reverse-engineering the component
```

**Pros:** No debugger bar. Can manipulate framework state directly.
**Cons:** Fragile (internal APIs change). Needs reverse engineering of `shreddit-composer` component.

### 4. Clipboard API (real paste via `navigator.clipboard`)

```javascript
await navigator.clipboard.writeText(comment_text);
// Then simulate Ctrl+V via chrome.debugger
chrome.debugger.sendCommand({tabId}, "Input.dispatchKeyEvent", {
  type: "keyDown", modifiers: 2, key: "v", code: "KeyV"
});
```

**Pros:** Fast (full text at once). Real paste event (isTrusted).
**Cons:** Requires clipboard permission + debugger. Overwrites user's clipboard.

### 5. `document.execCommand('insertText')` from MAIN world

Current attempts run in content script isolated world. Try running `execCommand` from the **MAIN world** (page context):

```javascript
chrome.scripting.executeScript({
  target: {tabId},
  world: "MAIN",
  func: (text) => {
    const box = document.querySelector('shreddit-composer div[contenteditable]');
    box.focus();
    document.execCommand('insertText', false, text);
  },
  args: [comment_text]
});
```

**Pros:** Simple. No debugger bar. execCommand in MAIN world might work differently.
**Cons:** May still fail if framework checks aren't event-based but mutation-observer-based.

### 6. Native Messaging Host + AutoHotkey/xdotool

External process that physically types via OS-level input. Extension sends text to native host, host simulates keyboard.

**Pros:** 100% real input. Undetectable.
**Cons:** Heavy. Requires installation of native host binary. Platform-specific.

---

## Recommended Investigation Order

1. **`chrome.scripting.executeScript` with `world: "MAIN"` + execCommand** — easiest test, 5 min
2. **`chrome.debugger` + `Input.insertText`** — most likely to work, 30 min to implement
3. **Reverse-engineer `shreddit-composer` Lit internals via MAIN world** — definitive solution, 1-2h
4. **Clipboard paste via debugger** — fallback if #2 has issues

---

## What the Analyst Should Do

1. **Open Reddit thread in Chrome** (logged in, r/test)
2. **Click on comment box** to expand composer
3. **In DevTools Console**, test these one by one:

```javascript
// Test A: execCommand from page context (should already be MAIN world in console)
const box = document.querySelector('shreddit-composer div[contenteditable]');
box.focus();
const sel = window.getSelection();
const range = document.createRange();
range.selectNodeContents(box);
range.collapse(false);
sel.removeAllRanges();
sel.addRange(range);
const result = document.execCommand('insertText', false, 'TEST TEXT HERE');
console.log('execCommand result:', result, 'text:', box.textContent);
```

```javascript
// Test B: check shreddit-composer API
const composer = document.querySelector('shreddit-composer');
console.log(Object.keys(composer));
console.log(composer.value); // does it have a value getter?
// Try setting:
composer.value = 'TEST';
// or
composer.setAttribute('value', 'TEST');
```

```javascript
// Test C: check what events the RTE actually listens to
const box = document.querySelector('shreddit-composer div[contenteditable]');
// Monkeypatch addEventListener to see what's being listened for
const orig = box.addEventListener;
box.addEventListener = function(type, fn, opts) {
  console.log('RTE listens:', type);
  return orig.call(this, type, fn, opts);
};
```

4. **Report**: which test produces visible text in the composer + enables submit button

---

## Key Question

**Does `document.execCommand('insertText')` work when executed from the DevTools Console (which runs in MAIN world)?**

If YES → solution is `chrome.scripting.executeScript` with `world: "MAIN"`.
If NO → need `chrome.debugger` CDP approach.

---

## Current Extension Status (June 29, 2026)

- ✅ Backend: all endpoints deployed and working
- ✅ Polling, heartbeat, auth: working
- ✅ State machine: full cycle runs
- ✅ Navigation: extension opens correct thread
- ✅ Trigger click: composer expands
- ✅ Element found: contenteditable div located
- ❌ **Text insertion: FAILS** — all methods produce 0 visible chars
- ❌ Submit: clicks button but sends empty (no text = Reddit rejects silently)
- ❌ False positive: state machine reports COMPLETED because execCommand returns true

## Files Involved

- `ramp_extension/content/reddit-actions.js` → `postComment()` function
- `ramp_extension/content/bundle.js` → compiled version loaded by Chrome
- `ramp_extension/background/state-machine.js` → execution state machine
- `ramp_extension/background/service-worker.js` → dispatches tasks

## Reproduction

1. Load extension from `/Volumes/2SSD/Projects/ReddirSaaS/ramp_extension/`
2. Open `https://www.reddit.com/r/test/comments/1uilh33/day_560/`
3. Create task: `ssh ramp 'docker exec app-celery-1 python3 -c "..."'`
4. Wait 30 sec for auto-dispatch
5. Observe: page navigates to thread, composer expands, but text field stays EMPTY
