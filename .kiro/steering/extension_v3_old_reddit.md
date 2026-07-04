---
inclusion: manual
---

# Extension v3 — Old Reddit Strategy

## Problem

New Reddit (Shreddit) uses:
- Shadow DOM web components (`faceplate-textarea-input`)
- Lexical rich-text editor (Facebook)
- `isTrusted` event checks that reject programmatic clicks
- reCAPTCHA Enterprise on comment submission (blocks API-based posting)
- Lazy-loaded composer (not in DOM until scroll + click)

These make reliable automated posting nearly impossible. Any Reddit deploy can break selectors.

## Solution: Old Reddit

`old.reddit.com` has:
- Plain HTML forms (no Shadow DOM, no web components)
- Simple `<textarea>` for comments (no Lexical, no contenteditable)
- Standard `<form>` submit (no reCAPTCHA Enterprise on most subreddits)
- DOM that hasn't changed significantly in 10+ years
- Same session cookies (switching between old/new doesn't require re-login)

## Architecture Change

```
BEFORE (v2):
  Navigate to www.reddit.com/r/sub/comments/id/...
  → scroll to comments
  → chrome.debugger click on shadow DOM
  → wait for Lexical composer
  → insertText into contenteditable
  → chrome.debugger click submit
  → pray it works

AFTER (v3):
  Navigate to old.reddit.com/r/sub/comments/id/...
  → find textarea.commentarea (always present, no lazy load)
  → set value + dispatch input event
  → click .save button
  → verify comment appeared
  → done
```

## Key Selectors (Old Reddit — stable 10+ years)

| Element | Selector | Notes |
|---------|----------|-------|
| Comment textarea | `#comment_reply_form textarea` or `.usertext-edit textarea` | Always present on page load |
| Submit button | `.usertext-buttons .save` or `button.save` | Standard HTML button |
| Logged-in user | `#header-bottom-right .user a` | Username in header |
| Comment text | `.usertext-body p` | Posted comment content |
| Thread locked | `.locked-comment-form` | If present, can't comment |

## URL Transformation

```
www.reddit.com/r/test/comments/18da1zl/some_test_commands/
→
old.reddit.com/r/test/comments/18da1zl/some_test_commands/
```

Simple string replace: `www.reddit.com` → `old.reddit.com`

## Execution Flow (Simplified)

1. **Navigate:** `chrome.tabs.update(tabId, { url: oldRedditUrl })`
2. **Wait:** `waitForTabLoad()` — old reddit is server-rendered, no SPA delays
3. **Verify:** Check `#header-bottom-right .user a` contains expected username
4. **Find textarea:** `document.querySelector('#comment_reply_form textarea')` — always exists
5. **Set value:** `textarea.value = text; textarea.dispatchEvent(new Event('input', {bubbles: true}))`
6. **Submit:** `document.querySelector('#comment_reply_form .save').click()`
7. **Verify:** Wait for `.usertext-body` to appear with matching text
8. **Extract permalink:** From new comment's permalink link

## Advantages Over v2

| Aspect | v2 (new Reddit) | v3 (old Reddit) |
|--------|-----------------|-----------------|
| Composer availability | Lazy-loaded, needs scroll+click | Always in DOM on page load |
| Text insertion | execCommand/InputEvent into Lexical | `textarea.value = text` |
| Submit | Debugger trusted click on shadow DOM button | `.save.click()` (plain HTML) |
| isTrusted checks | Yes (blocks programmatic clicks) | No (plain HTML form) |
| reCAPTCHA | Enterprise (invisible, blocks API) | None or basic (old reddit rarely shows) |
| DOM stability | Changes every Reddit deploy | Stable 10+ years |
| chrome.debugger needed | Yes | No |
| Debugger banner shown | Yes (yellow bar during execution) | No |

## Risks

1. **Reddit might disable old.reddit.com** — Unlikely short-term (millions of users), but possible long-term. If it happens, we still have v2 as fallback.
2. **Some threads might not have textarea** — If user is banned from sub, or thread is locked. Handle gracefully.
3. **Session must be valid for old reddit too** — Same cookies, should work. Verify.
4. **Subreddit custom CSS on old reddit** — Some subs hide comment form via CSS. Use `old.reddit.com` URL which ignores sub CSS by default.

## Migration Plan

1. Change executor.js to transform URL to old.reddit.com
2. Replace all Shreddit-specific selectors with old reddit selectors
3. Remove chrome.debugger dependency (no longer needed!)
4. Remove `debugger` permission from manifest (cleaner, no yellow banner)
5. Simplify content script (80% of DOM-interaction code becomes unnecessary)
6. Test on r/test
7. Deploy

## Fallback Strategy

If old.reddit.com fails for a specific thread:
- Fall back to email delivery for that task
- Report `OLD_REDDIT_UNAVAILABLE` error
- Don't attempt new reddit (too unreliable)
