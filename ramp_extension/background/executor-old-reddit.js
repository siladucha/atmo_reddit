/**
 * RAMP Extension v3 — Old Reddit Executor
 *
 * Posts comments via old.reddit.com which has:
 * - Plain HTML textarea (no Shadow DOM, no Lexical)
 * - Standard form submit (no reCAPTCHA Enterprise)
 * - Stable DOM (unchanged for 10+ years)
 * - No chrome.debugger needed (no isTrusted checks)
 *
 * HUMAN-LIKE FLOW (v3.1):
 *   1. Navigate to subreddit (old.reddit.com/r/xxx)
 *   2. Scroll down slowly (simulate browsing)
 *   3. Find the target thread link and click it
 *   4. Wait for thread page to load
 *   5. Scroll to comment area
 *   6. Insert text into textarea
 *   7. Click save
 *   8. Verify comment posted
 *
 * This mimics natural user behavior: open subreddit → browse → click thread → comment.
 * NOT a direct URL navigation to thread (which looks programmatic).
 *
 * @module background/executor-old-reddit
 */

import { getAuth } from '../shared/auth.js';

// ─── Constants ─────────────────────────────────────────────────────────────

export const ERROR_CODES = {
  AUTH_FAILED: 'AUTH_FAILED',
  NAVIGATE_FAILED: 'NAVIGATE_FAILED',
  THREAD_NOT_FOUND: 'THREAD_NOT_FOUND',
  THREAD_LOCKED: 'THREAD_LOCKED',
  TEXTAREA_NOT_FOUND: 'TEXTAREA_NOT_FOUND',
  TEXT_INSERT_FAILED: 'TEXT_INSERT_FAILED',
  SUBMIT_FAILED: 'SUBMIT_FAILED',
  VERIFY_FAILED: 'VERIFY_FAILED',
  TIMEOUT: 'TIMEOUT',
  NETWORK_ERROR: 'NETWORK_ERROR',
};

/** Convert any reddit URL to old reddit */
function toOldRedditUrl(url) {
  if (!url) return url;
  return url
    .replace('https://www.reddit.com', 'https://old.reddit.com')
    .replace('https://reddit.com', 'https://old.reddit.com')
    .replace('http://www.reddit.com', 'https://old.reddit.com')
    .replace('http://reddit.com', 'https://old.reddit.com');
}

/** Extract subreddit name from a reddit URL */
function extractSubreddit(url) {
  const match = url.match(/\/r\/([^/?#]+)/i);
  return match ? match[1] : null;
}

/** Extract thread ID from a reddit comments URL */
function extractThreadId(url) {
  // old.reddit.com/r/sysadmin/comments/1abc123/title_here/
  const match = url.match(/\/comments\/([a-z0-9]+)/i);
  return match ? match[1] : null;
}

// ─── Main Entry Point ──────────────────────────────────────────────────────

/**
 * Execute a comment posting task via old.reddit.com with human-like navigation.
 *
 * Flow:
 *   1. Navigate to subreddit page (old.reddit.com/r/xxx)
 *   2. Wait + simulate scrolling (browse behavior)
 *   3. Find target thread in feed and click it (or fallback to direct nav)
 *   4. Wait for thread page load
 *   5. Verify logged in as correct user
 *   6. Check thread not locked
 *   7. Scroll to comment area
 *   8. Insert text into textarea
 *   9. Click save button
 *  10. Verify comment posted
 *  11. Report success
 *
 * @param {Object} task - Task from backend (must have thread_url, comment_text, subreddit)
 * @param {number} tabId - Chrome tab ID
 * @returns {Promise<ExecutionResult>}
 */
export async function executeTaskOldReddit(task, tabId) {
  const events = [];
  const startedAt = Date.now();

  const emitEvent = (type, data = {}) => {
    events.push({ task_id: task.task_id, event_type: type, timestamp: new Date().toISOString(), ...data });
  };

  const fail = (errorCode, errorDetails, step) => {
    emitEvent('task_failed', { error_code: errorCode, error_details: errorDetails, step });
    return { success: false, error_code: errorCode, error_details: errorDetails, step, events, duration_ms: Date.now() - startedAt };
  };

  emitEvent('task_execution_started', { task_type: task.task_type, thread_url: task.thread_url, strategy: 'old_reddit' });

  const threadUrl = toOldRedditUrl(task.thread_url);
  const subreddit = task.subreddit || extractSubreddit(threadUrl);
  const threadId = extractThreadId(threadUrl);

  if (!subreddit) {
    return fail(ERROR_CODES.NAVIGATE_FAILED, 'Cannot extract subreddit from thread URL', 'parse');
  }

  try {
    // ── Step 1: Navigate to subreddit ────────────────────────────────────────
    const subredditUrl = `https://old.reddit.com/r/${subreddit}`;
    emitEvent('step_started', { step: 'navigate_subreddit', url: subredditUrl });

    try {
      await chrome.tabs.update(tabId, { url: subredditUrl });
      await waitForTabLoad(tabId, 30000);
      await sleep(1500 + Math.random() * 1500); // 1.5-3s human pause
    } catch (err) {
      return fail(ERROR_CODES.NAVIGATE_FAILED, err.message || 'Subreddit navigation failed', 'navigate_subreddit');
    }

    emitEvent('step_completed', { step: 'navigate_subreddit' });

    // ── Step 2: Verify Auth on subreddit page ────────────────────────────────
    emitEvent('step_started', { step: 'verify_auth' });

    const authResult = await sendMsg(tabId, { type: 'OLD_REDDIT_CHECK_AUTH' });
    if (!authResult || !authResult.logged_in) {
      return fail(ERROR_CODES.AUTH_FAILED, 'Not logged in on old.reddit.com', 'verify_auth');
    }

    emitEvent('step_completed', { step: 'verify_auth', username: authResult.username });

    // ── Step 3: Scroll through subreddit feed (simulate browsing) ────────────
    emitEvent('step_started', { step: 'browse_subreddit' });

    // Scroll down 2-4 times with random delays (like human scanning titles)
    const scrollCount = 2 + Math.floor(Math.random() * 3); // 2-4 scrolls
    await sendMsg(tabId, { type: 'OLD_REDDIT_SCROLL', count: scrollCount, delay_ms: 800 });
    await sleep(1000 + Math.random() * 1000); // pause after scrolling

    emitEvent('step_completed', { step: 'browse_subreddit', scrolls: scrollCount });

    // ── Step 4: Find and click the target thread ─────────────────────────────
    emitEvent('step_started', { step: 'find_thread' });

    let threadFound = false;
    if (threadId) {
      // Try to find the thread link in the current feed
      const clickResult = await sendMsg(tabId, { type: 'OLD_REDDIT_CLICK_THREAD', thread_id: threadId });
      if (clickResult && clickResult.found) {
        threadFound = true;
        await waitForTabLoad(tabId, 30000);
        await sleep(1500 + Math.random() * 1000); // human pause after clicking
      }
    }

    // Fallback: if thread not found in feed (different page, already scrolled past),
    // navigate directly to thread URL (still on old.reddit.com)
    if (!threadFound) {
      emitEvent('thread_not_in_feed', { fallback: 'direct_navigation' });
      try {
        await chrome.tabs.update(tabId, { url: threadUrl });
        await waitForTabLoad(tabId, 30000);
        await sleep(2000 + Math.random() * 1000);
      } catch (err) {
        return fail(ERROR_CODES.NAVIGATE_FAILED, err.message || 'Thread navigation failed', 'find_thread');
      }
    }

    emitEvent('step_completed', { step: 'find_thread', found_in_feed: threadFound });

    // ── Step 5: Check thread not locked ──────────────────────────────────────
    emitEvent('step_started', { step: 'check_locked' });

    const threadStatus = await sendMsg(tabId, { type: 'OLD_REDDIT_CHECK_THREAD' });
    if (threadStatus?.locked) {
      return fail(ERROR_CODES.THREAD_LOCKED, 'Thread is locked or archived', 'check_locked');
    }

    emitEvent('step_completed', { step: 'check_locked' });

    // ── Step 6: Scroll to comment area (simulate reading the post) ───────────
    emitEvent('step_started', { step: 'scroll_to_comments' });

    await sendMsg(tabId, { type: 'OLD_REDDIT_SCROLL_TO_COMMENTS' });
    await sleep(1500 + Math.random() * 1500); // pause like reading

    emitEvent('step_completed', { step: 'scroll_to_comments' });

    // ── Step 7: Insert text into textarea ────────────────────────────────────
    emitEvent('step_started', { step: 'insert_text' });

    const insertResult = await sendMsg(tabId, { type: 'OLD_REDDIT_INSERT_TEXT', text: task.comment_text });
    if (!insertResult || !insertResult.ok) {
      return fail(
        ERROR_CODES.TEXTAREA_NOT_FOUND,
        insertResult?.error || 'Comment textarea not found',
        'insert_text'
      );
    }

    // Small pause after typing (human doesn't click submit instantly)
    await sleep(800 + Math.random() * 1200);

    emitEvent('step_completed', { step: 'insert_text', char_count: insertResult.char_count });

    // ── Step 8: Click submit ─────────────────────────────────────────────────
    emitEvent('step_started', { step: 'submit' });

    const submitResult = await sendMsg(tabId, { type: 'OLD_REDDIT_SUBMIT' });
    if (!submitResult || !submitResult.ok) {
      return fail(ERROR_CODES.SUBMIT_FAILED, submitResult?.error || 'Submit button not found or click failed', 'submit');
    }

    emitEvent('step_completed', { step: 'submit' });

    // ── Step 9: Wait and verify ──────────────────────────────────────────────
    emitEvent('step_started', { step: 'verify' });

    // Wait for page to reload/update after submit (old reddit does full reload)
    await sleep(5000);

    const verifyResult = await sendMsg(tabId, { type: 'OLD_REDDIT_VERIFY_POSTED', expected_text: task.comment_text });
    if (!verifyResult || !verifyResult.found) {
      emitEvent('verify_uncertain', { error: verifyResult?.error });
    }

    emitEvent('step_completed', { step: 'verify', permalink: verifyResult?.permalink });

    // ── Step 10: Report to backend ───────────────────────────────────────────
    emitEvent('step_started', { step: 'report' });

    let reportSuccess = false;
    try {
      reportSuccess = await reportToBackend(task, verifyResult?.permalink, verifyResult?.comment_id);
    } catch (err) {
      emitEvent('report_error', { error: err.message });
    }

    emitEvent('step_completed', { step: 'report', reported: reportSuccess });

    // ── SUCCESS ──────────────────────────────────────────────────────────────
    emitEvent('task_execution_completed', {
      permalink: verifyResult?.permalink,
      comment_id: verifyResult?.comment_id,
      duration_ms: Date.now() - startedAt,
      strategy: 'old_reddit',
      found_in_feed: threadFound,
    });

    return {
      success: true,
      permalink: verifyResult?.permalink || null,
      comment_id: verifyResult?.comment_id || null,
      events,
      duration_ms: Date.now() - startedAt,
    };

  } catch (err) {
    return fail(ERROR_CODES.NETWORK_ERROR, `Unexpected: ${err.message}`, 'unknown');
  }
}

// ─── Helpers ───────────────────────────────────────────────────────────────

async function sendMsg(tabId, message) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (err) {
    console.warn('[RAMP OldReddit] sendMessage failed:', message.type, err.message);
    return null;
  }
}

function waitForTabLoad(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    let settled = false;
    const listener = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === 'complete') {
        if (!settled) {
          settled = true;
          chrome.tabs.onUpdated.removeListener(listener);
          setTimeout(resolve, 1000);
        }
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => {
      if (!settled) {
        settled = true;
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }, timeoutMs);
  });
}

async function reportToBackend(task, permalink, commentId) {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return false;

  const response = await fetch(`${auth.rampUrl}/api/extension/report`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${auth.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      task_id: task.task_id,
      idempotency_key: task.idempotency_key,
      result_type: 'task_completed',
      permalink,
      comment_id: commentId,
      posted_at: new Date().toISOString(),
    }),
  });

  return response.ok;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
