/**
 * RAMP Extension v3 — Old Reddit Executor (Stabilized)
 *
 * Posts comments via old.reddit.com which has:
 * - Plain HTML textarea (no Shadow DOM, no Lexical)
 * - Standard form submit (no reCAPTCHA Enterprise)
 * - Stable DOM (unchanged for 10+ years)
 * - No chrome.debugger needed (no isTrusted checks)
 *
 * FLOW:
 *   1. Navigate to subreddit (old.reddit.com/r/xxx)
 *   2. Verify auth on subreddit page
 *   3. Scroll subreddit feed (simulate browsing)
 *   4. Find target thread in feed → click it (or fallback to direct nav)
 *   5. Wait for thread page load + verify content script ready
 *   6. Verify auth on thread page
 *   7. Check thread not locked (with retry)
 *   8. Scroll to comment area
 *   9. Insert text into textarea
 *  10. Click save
 *  11. Verify comment posted
 *  12. Report to backend
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
  CONTENT_SCRIPT_NOT_READY: 'CONTENT_SCRIPT_NOT_READY',
  NETWORK_ERROR: 'NETWORK_ERROR',
};

const LOG_PREFIX = '[RAMP OldReddit]';

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
  const match = url.match(/\/comments\/([a-z0-9]+)/i);
  return match ? match[1] : null;
}

// ─── Main Entry Point ──────────────────────────────────────────────────────

/**
 * Execute a comment posting task via old.reddit.com.
 *
 * @param {Object} task - Task from backend (must have thread_url, comment_text, subreddit)
 * @param {number} tabId - Chrome tab ID
 * @returns {Promise<ExecutionResult>}
 */
export async function executeTaskOldReddit(task, tabId) {
  const events = [];
  const startedAt = Date.now();

  const log = (msg, data) => {
    const ts = ((Date.now() - startedAt) / 1000).toFixed(1);
    if (data) {
      console.log(`${LOG_PREFIX} [${ts}s] ${msg}`, data);
    } else {
      console.log(`${LOG_PREFIX} [${ts}s] ${msg}`);
    }
  };

  const emitEvent = (type, data = {}) => {
    events.push({ task_id: task.task_id, event_type: type, timestamp: new Date().toISOString(), ...data });
  };

  const fail = (errorCode, errorDetails, step) => {
    log(`❌ FAILED at step "${step}": ${errorCode} — ${errorDetails}`);
    emitEvent('task_failed', { error_code: errorCode, error_details: errorDetails, step });
    return { success: false, error_code: errorCode, error_details: errorDetails, step, events, duration_ms: Date.now() - startedAt };
  };

  const threadUrl = toOldRedditUrl(task.thread_url);
  const subreddit = task.subreddit || extractSubreddit(threadUrl);
  const threadId = extractThreadId(threadUrl);

  log(`▶ Starting task: thread=${threadUrl}, sub=r/${subreddit}, threadId=${threadId}`);
  emitEvent('task_execution_started', { task_type: task.task_type, thread_url: threadUrl, strategy: 'old_reddit' });

  if (!subreddit) {
    return fail(ERROR_CODES.NAVIGATE_FAILED, 'Cannot extract subreddit from thread URL', 'parse');
  }

  try {
    // ════════════════════════════════════════════════════════════════════════
    // STEP 1: Navigate to subreddit
    // ════════════════════════════════════════════════════════════════════════
    const subredditUrl = `https://old.reddit.com/r/${subreddit}/new/`;
    log(`→ Step 1: Navigating to subreddit: ${subredditUrl}`);
    emitEvent('step_started', { step: 'navigate_subreddit', url: subredditUrl });

    try {
      await chrome.tabs.update(tabId, { url: subredditUrl });
      await waitForTabComplete(tabId, 30000);
    } catch (err) {
      return fail(ERROR_CODES.NAVIGATE_FAILED, `Subreddit nav failed: ${err.message}`, 'navigate_subreddit');
    }

    // Wait for DOM to settle
    await sleep(2000 + Math.random() * 1000);
    log('✓ Step 1: Subreddit page loaded');
    emitEvent('step_completed', { step: 'navigate_subreddit' });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 2: Verify auth on subreddit page
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 2: Verifying auth on subreddit page');
    emitEvent('step_started', { step: 'verify_auth_subreddit' });

    const authResult = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_CHECK_AUTH' }, 3, 2000);
    if (!authResult) {
      return fail(ERROR_CODES.CONTENT_SCRIPT_NOT_READY, 'Content script not responding on subreddit page', 'verify_auth_subreddit');
    }
    if (!authResult.logged_in) {
      return fail(ERROR_CODES.AUTH_FAILED, `Not logged in on old.reddit.com (username: ${authResult.username})`, 'verify_auth_subreddit');
    }

    log(`✓ Step 2: Logged in as "${authResult.username}"`);
    emitEvent('step_completed', { step: 'verify_auth_subreddit', username: authResult.username });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 3: Browse subreddit (simulate human behavior)
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 3: Scrolling subreddit feed');
    emitEvent('step_started', { step: 'browse_subreddit' });

    const scrollCount = 2 + Math.floor(Math.random() * 2);
    await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_SCROLL', count: scrollCount, delay_ms: 800 }, 1, 1000);
    await sleep(800 + Math.random() * 800);

    log(`✓ Step 3: Scrolled ${scrollCount} times`);
    emitEvent('step_completed', { step: 'browse_subreddit', scrolls: scrollCount });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 4: Find and navigate to thread
    // ════════════════════════════════════════════════════════════════════════
    log(`→ Step 4: Looking for thread ${threadId} in feed`);
    emitEvent('step_started', { step: 'navigate_thread' });

    let threadFoundInFeed = false;

    if (threadId) {
      const clickResult = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_CLICK_THREAD', thread_id: threadId }, 1, 1000);
      if (clickResult && clickResult.found) {
        threadFoundInFeed = true;
        log('  Thread found in feed, clicked — waiting for load');
        await waitForTabComplete(tabId, 30000);
        await sleep(2000 + Math.random() * 1000);
      }
    }

    if (!threadFoundInFeed) {
      log(`  Thread not in feed (normal for older posts). Direct navigation to: ${threadUrl}`);
      try {
        await chrome.tabs.update(tabId, { url: threadUrl });
        await waitForTabComplete(tabId, 30000);
      } catch (err) {
        return fail(ERROR_CODES.NAVIGATE_FAILED, `Thread nav failed: ${err.message}`, 'navigate_thread');
      }
      // Extra wait for old reddit server-render + cookie application
      await sleep(3000 + Math.random() * 1500);
    }

    log(`✓ Step 4: On thread page (found_in_feed: ${threadFoundInFeed})`);
    emitEvent('step_completed', { step: 'navigate_thread', found_in_feed: threadFoundInFeed });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 5: Ensure content script is ready on thread page
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 5: Waiting for content script on thread page');
    emitEvent('step_started', { step: 'ensure_content_script' });

    const pingResult = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_CHECK_AUTH' }, 5, 2000);
    if (!pingResult) {
      return fail(ERROR_CODES.CONTENT_SCRIPT_NOT_READY, 'Content script never responded on thread page after 10s', 'ensure_content_script');
    }

    log(`✓ Step 5: Content script ready (logged_in: ${pingResult.logged_in}, user: ${pingResult.username})`);
    emitEvent('step_completed', { step: 'ensure_content_script' });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 6: Verify auth on thread page
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 6: Verifying auth on thread page');
    emitEvent('step_started', { step: 'verify_auth_thread' });

    if (!pingResult.logged_in) {
      return fail(ERROR_CODES.AUTH_FAILED, 'Not logged in on thread page — session may not apply to old.reddit.com', 'verify_auth_thread');
    }

    log(`✓ Step 6: Auth confirmed on thread (user: ${pingResult.username})`);
    emitEvent('step_completed', { step: 'verify_auth_thread', username: pingResult.username });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 7: Check thread not locked (with retry)
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 7: Checking if thread is locked');
    emitEvent('step_started', { step: 'check_locked' });

    let threadStatus = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_CHECK_THREAD' }, 2, 1500);

    if (!threadStatus) {
      return fail(ERROR_CODES.CONTENT_SCRIPT_NOT_READY, 'CHECK_THREAD got no response', 'check_locked');
    }

    // If locked but no form — might be timing, retry after extra wait
    if (threadStatus.locked && !threadStatus.has_form) {
      log(`  ⚠ First check: locked=${threadStatus.locked}, has_form=${threadStatus.has_form}, reason=${threadStatus.reason}. Retrying after 3s...`);
      await sleep(3000);
      threadStatus = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_CHECK_THREAD' }, 2, 1500);
      if (!threadStatus) {
        return fail(ERROR_CODES.CONTENT_SCRIPT_NOT_READY, 'CHECK_THREAD retry got no response', 'check_locked');
      }
      log(`  Retry result: locked=${threadStatus.locked}, has_form=${threadStatus.has_form}, reason=${threadStatus.reason}`);
    }

    if (threadStatus.locked) {
      return fail(ERROR_CODES.THREAD_LOCKED, `Thread is locked (has_form=${threadStatus.has_form}, reason=${threadStatus.reason || 'explicit_lock'})`, 'check_locked');
    }

    log(`✓ Step 7: Thread is open (has_form: ${threadStatus.has_form})`);
    emitEvent('step_completed', { step: 'check_locked', has_form: threadStatus.has_form });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 8: Scroll to comment area
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 8: Scrolling to comment area');
    emitEvent('step_started', { step: 'scroll_to_comments' });

    await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_SCROLL_TO_COMMENTS' }, 1, 1000);
    await sleep(1000 + Math.random() * 1000);

    log('✓ Step 8: Scrolled to comments');
    emitEvent('step_completed', { step: 'scroll_to_comments' });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 9: Insert text into textarea
    // ════════════════════════════════════════════════════════════════════════
    log(`→ Step 9: Inserting text (${task.comment_text.length} chars)`);
    emitEvent('step_started', { step: 'insert_text' });

    const insertResult = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_INSERT_TEXT', text: task.comment_text }, 2, 2000);

    if (!insertResult || !insertResult.ok) {
      return fail(ERROR_CODES.TEXTAREA_NOT_FOUND, insertResult?.error || 'Comment textarea not found', 'insert_text');
    }

    if (insertResult.char_count !== task.comment_text.length) {
      log(`  ⚠ Char count mismatch: inserted=${insertResult.char_count}, expected=${task.comment_text.length}`);
    }

    // Human pause after typing
    await sleep(1000 + Math.random() * 1500);

    log(`✓ Step 9: Text inserted (${insertResult.char_count} chars)`);
    emitEvent('step_completed', { step: 'insert_text', char_count: insertResult.char_count });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 10: Click submit
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 10: Clicking submit button');
    emitEvent('step_started', { step: 'submit' });

    const submitResult = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_SUBMIT' }, 2, 2000);
    if (!submitResult || !submitResult.ok) {
      return fail(ERROR_CODES.SUBMIT_FAILED, submitResult?.error || 'Submit button not found or click failed', 'submit');
    }

    log('✓ Step 10: Submit clicked');
    emitEvent('step_completed', { step: 'submit' });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 11: Wait and verify posted
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 11: Waiting for page reload and verifying');
    emitEvent('step_started', { step: 'verify' });

    // Old reddit does full page reload after submit
    await sleep(5000);

    // Re-ensure content script after reload
    const postReloadPing = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_CHECK_AUTH' }, 5, 2000);
    if (!postReloadPing) {
      log('  ⚠ Content script not responding after submit — page may still be loading');
      await sleep(3000);
    }

    const verifyResult = await sendMsgWithRetry(tabId, { type: 'OLD_REDDIT_VERIFY_POSTED', expected_text: task.comment_text }, 2, 2000);

    if (!verifyResult || !verifyResult.found) {
      log(`  ⚠ Verification uncertain: ${verifyResult?.error || 'comment not found in page'}`);
      emitEvent('verify_uncertain', { error: verifyResult?.error });
    } else {
      log(`✓ Step 11: Comment verified! permalink=${verifyResult.permalink}`);
    }

    emitEvent('step_completed', { step: 'verify', found: !!verifyResult?.found, permalink: verifyResult?.permalink });

    // ════════════════════════════════════════════════════════════════════════
    // STEP 12: Report to backend
    // ════════════════════════════════════════════════════════════════════════
    log('→ Step 12: Reporting to backend');
    emitEvent('step_started', { step: 'report' });

    let reportSuccess = false;
    try {
      reportSuccess = await reportToBackend(task, verifyResult?.permalink, verifyResult?.comment_id);
    } catch (err) {
      log(`  ⚠ Report failed: ${err.message}`);
      emitEvent('report_error', { error: err.message });
    }

    log(`✓ Step 12: Report sent (success: ${reportSuccess})`);
    emitEvent('step_completed', { step: 'report', reported: reportSuccess });

    // ════════════════════════════════════════════════════════════════════════
    // SUCCESS
    // ════════════════════════════════════════════════════════════════════════
    const duration = Date.now() - startedAt;
    log(`🎉 Task completed successfully in ${(duration / 1000).toFixed(1)}s`);
    emitEvent('task_execution_completed', {
      permalink: verifyResult?.permalink,
      comment_id: verifyResult?.comment_id,
      duration_ms: duration,
      strategy: 'old_reddit',
      found_in_feed: threadFoundInFeed,
    });

    return {
      success: true,
      permalink: verifyResult?.permalink || null,
      comment_id: verifyResult?.comment_id || null,
      events,
      duration_ms: duration,
    };

  } catch (err) {
    return fail(ERROR_CODES.NETWORK_ERROR, `Unexpected error: ${err.message}`, 'unknown');
  }
}

// ─── Helpers ───────────────────────────────────────────────────────────────

/**
 * Send a message to content script with retries.
 * Handles the case where content script is not yet injected after navigation.
 *
 * @param {number} tabId
 * @param {Object} message
 * @param {number} maxAttempts - Total attempts (including first)
 * @param {number} retryDelay - Delay between retries in ms
 * @returns {Promise<any|null>}
 */
async function sendMsgWithRetry(tabId, message, maxAttempts = 3, retryDelay = 1500) {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const result = await chrome.tabs.sendMessage(tabId, message);
      return result;
    } catch (err) {
      if (attempt < maxAttempts) {
        console.log(`${LOG_PREFIX} sendMsg(${message.type}) attempt ${attempt}/${maxAttempts} failed: ${err.message}. Retrying in ${retryDelay}ms...`);
        await sleep(retryDelay);
      } else {
        console.warn(`${LOG_PREFIX} sendMsg(${message.type}) failed after ${maxAttempts} attempts: ${err.message}`);
        return null;
      }
    }
  }
  return null;
}

/**
 * Wait for tab to reach 'complete' load status.
 * @param {number} tabId
 * @param {number} timeoutMs
 */
function waitForTabComplete(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    let settled = false;

    const listener = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === 'complete') {
        if (!settled) {
          settled = true;
          chrome.tabs.onUpdated.removeListener(listener);
          // Give DOM a moment to finalize after status=complete
          setTimeout(resolve, 500);
        }
      }
    };

    chrome.tabs.onUpdated.addListener(listener);

    setTimeout(() => {
      if (!settled) {
        settled = true;
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(); // resolve anyway — page might be usable even if slow
      }
    }, timeoutMs);
  });
}

/**
 * Report successful execution to RAMP backend.
 */
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
