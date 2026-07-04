/**
 * RAMP Extension v2 — Executor Module
 *
 * Full automated execution flow for comment posting tasks.
 * Replaces the old state-machine.js prepare_only mode with a complete
 * cycle: navigate → dismiss banners → debugger click composer →
 * wait for composer → insert text → debugger click submit →
 * verify posted → extract permalink → report to backend.
 *
 * The CALLER (scheduler) handles retry logic via retry-engine.js.
 * This module only reports success or failure with error codes.
 *
 * @module background/executor
 */

import { trustedClick } from './debugger-engine.js';
import { getAuth } from '../shared/auth.js';

// ─── Constants ─────────────────────────────────────────────────────────────

/** Error codes returned on failure */
export const ERROR_CODES = {
  AUTH_FAILED: 'AUTH_FAILED',
  NAVIGATE_FAILED: 'NAVIGATE_FAILED',
  DOM_CHANGED: 'DOM_CHANGED',
  THREAD_LOCKED: 'THREAD_LOCKED',
  EDITOR_NOT_FOUND: 'EDITOR_NOT_FOUND',
  TEXT_INSERT_FAILED: 'TEXT_INSERT_FAILED',
  SUBMIT_FAILED: 'SUBMIT_FAILED',
  TIMEOUT: 'TIMEOUT',
  NETWORK_ERROR: 'NETWORK_ERROR',
  VERIFY_FAILED: 'VERIFY_FAILED',
  REPORT_FAILED: 'REPORT_FAILED',
};

/** Execution step identifiers for traceability */
const STEPS = {
  PRECHECK: 'precheck',
  NAVIGATE: 'navigate',
  VERIFY_CONTEXT: 'verify_context',
  DISMISS_BANNERS: 'dismiss_banners',
  CLEAR_DRAFTS: 'clear_drafts',
  CLICK_COMPOSER: 'click_composer',
  WAIT_COMPOSER: 'wait_composer',
  INSERT_TEXT: 'insert_text',
  VERIFY_TEXT: 'verify_text',
  CLICK_SUBMIT: 'click_submit',
  VERIFY_POSTED: 'verify_posted',
  REPORT: 'report',
};

/** Selectors for the composer trigger (tried in order) */
const COMPOSER_SELECTORS = [
  // Shreddit (new Reddit): textarea input trigger (the collapsed "Join" area)
  { selector: 'faceplate-textarea-input:last-of-type', shadow: '#innerTextArea' },
  { selector: 'faceplate-textarea-input', shadow: '#innerTextArea' },
  // Shreddit: sometimes appears as a button or div with specific test ID
  { selector: '[data-testid="trigger-button"]', shadow: null },
  // Shreddit composer might already be expanded (contenteditable visible)
  { selector: 'shreddit-composer div[contenteditable="true"]', shadow: null },
  // Generic contenteditable (Lexical editor already open)
  { selector: 'div[contenteditable="true"][role="textbox"]', shadow: null },
  // Old Reddit fallback
  { selector: '.usertext-edit textarea', shadow: null },
];

/** Selectors for the submit button (tried in order) */
const SUBMIT_SELECTORS = [
  { selector: '#comment-composer-submit-button', shadow: null },
  { selector: 'faceplate-form[action*="create-comment"] button[type="submit"]', shadow: null },
  { selector: 'shreddit-composer button[type="submit"]', shadow: null },
  { selector: 'button[type="submit"][slot="submit-button"]', shadow: null },
];

// ─── Main Entry Point ──────────────────────────────────────────────────────

/**
 * Execute a comment posting task through the full automated flow.
 *
 * @param {Object} task - Task from backend
 * @param {string} task.task_id - Unique task identifier
 * @param {string} task.thread_url - Reddit thread URL to navigate to
 * @param {string} task.comment_text - Comment text to post
 * @param {string} [task.task_type] - Task type (epg, manual, diagnostic)
 * @param {number} tabId - Chrome tab ID to execute in
 * @returns {Promise<ExecutionResult>}
 */
export async function executeTask(task, tabId) {
  const events = [];
  const startedAt = Date.now();

  const emitEvent = (eventType, data = {}) => {
    events.push({
      task_id: task.task_id,
      event_type: eventType,
      timestamp: new Date().toISOString(),
      ...data,
    });
  };

  const fail = (errorCode, errorDetails, step) => {
    emitEvent('task_failed', { error_code: errorCode, error_details: errorDetails, step });
    return {
      success: false,
      error_code: errorCode,
      error_details: errorDetails,
      step,
      events,
      duration_ms: Date.now() - startedAt,
    };
  };

  emitEvent('task_execution_started', {
    task_type: task.task_type,
    thread_url: task.thread_url,
  });

  try {
    // ── Step 1: PRECHECK — Verify Reddit session ─────────────────────────────
    emitEvent('step_started', { step: STEPS.PRECHECK });

    const authCheck = await sendMessageSafe(tabId, { type: 'CHECK_AUTH' });
    if (!authCheck || authCheck.expired) {
      return fail(ERROR_CODES.AUTH_FAILED, 'Reddit session expired or not logged in', STEPS.PRECHECK);
    }

    emitEvent('step_completed', { step: STEPS.PRECHECK });

    // ── Step 2: NAVIGATE — Go to thread URL ──────────────────────────────────
    emitEvent('step_started', { step: STEPS.NAVIGATE });

    try {
      await chrome.tabs.update(tabId, { url: task.thread_url });
      await waitForTabLoad(tabId, 30000);
      // Extra delay for Reddit SPA to fully render + content script to inject
      await sleep(5000);
    } catch (navErr) {
      return fail(ERROR_CODES.NAVIGATE_FAILED, navErr.message || 'Navigation failed', STEPS.NAVIGATE);
    }

    emitEvent('step_completed', { step: STEPS.NAVIGATE, url: task.thread_url });

    // ── Step 3: VERIFY_CONTEXT — Ensure correct thread, not locked ───────────
    emitEvent('step_started', { step: STEPS.VERIFY_CONTEXT });

    let context = null;
    for (let attempt = 0; attempt < 5; attempt++) {
      context = await sendMessageSafe(tabId, { type: 'VERIFY_CONTEXT', task });
      if (context && (context.ok || context.error)) break;
      await sleep(1500);
    }

    if (!context || context.error) {
      const errorCode = context?.error === 'thread_locked'
        ? ERROR_CODES.THREAD_LOCKED
        : ERROR_CODES.DOM_CHANGED;
      return fail(errorCode, context?.details || 'Context verification failed', STEPS.VERIFY_CONTEXT);
    }

    emitEvent('step_completed', { step: STEPS.VERIFY_CONTEXT, variant: context.variant });

    // ── Step 4: DISMISS_BANNERS — Remove app promo overlays ──────────────────
    emitEvent('step_started', { step: STEPS.DISMISS_BANNERS });

    const bannerResult = await sendMessageSafe(tabId, { type: 'DISMISS_BANNERS' });
    if (bannerResult?.dismissed) {
      emitEvent('banner_dismissed', { banner_type: bannerResult.banner_type });
    }

    emitEvent('step_completed', { step: STEPS.DISMISS_BANNERS });

    // ── Step 5: CLEAR_DRAFTS — Remove localStorage drafts ────────────────────
    emitEvent('step_started', { step: STEPS.CLEAR_DRAFTS });

    const draftResult = await sendMessageSafe(tabId, { type: 'CLEAR_DRAFTS' });
    emitEvent('step_completed', {
      step: STEPS.CLEAR_DRAFTS,
      drafts_cleared: draftResult?.cleared || 0,
    });

    // ── Step 5.5: SCROLL_TO_COMMENTS — Ensure composer area is in viewport ───
    await sendMessageSafe(tabId, { type: 'SCROLL_TO_COMMENTS' });
    await sleep(2000); // Wait for lazy-loaded composer to render

    // ── Step 6: DEBUGGER_CLICK_COMPOSER — Trusted click on textarea trigger ──
    emitEvent('step_started', { step: STEPS.CLICK_COMPOSER });

    // First check if composer is already open (contenteditable visible)
    const alreadyOpen = await sendMessageSafe(tabId, {
      type: 'WAIT_FOR_COMPOSER',
      timeout_ms: 1000, // Quick check — don't wait long
    });

    let composerClicked = false;
    let composerError = null;

    if (alreadyOpen && alreadyOpen.found) {
      // Composer already visible — no click needed
      composerClicked = true;
      emitEvent('composer_already_open', { selector: alreadyOpen.selector });
    } else {
      // Debug: ask content script what composer elements exist
      const debugInfo = await sendMessageSafe(tabId, { type: 'DEBUG_COMPOSER_STATE' });
      emitEvent('debug_composer_state', debugInfo || {});

      // Need to click to open composer
      for (const { selector, shadow } of COMPOSER_SELECTORS) {
        try {
          await trustedClick(tabId, selector, shadow);
          composerClicked = true;
          emitEvent('composer_click_success', { selector, shadow });
          break;
        } catch (err) {
          composerError = err.message;
          // Try next selector
        }
      }

      if (!composerClicked) {
        // Retry: scroll further down and try again after 3s
        await sendMessageSafe(tabId, { type: 'SCROLL_TO_COMMENTS', force: true });
        await sleep(3000);

        for (const { selector, shadow } of COMPOSER_SELECTORS) {
          try {
            await trustedClick(tabId, selector, shadow);
            composerClicked = true;
            emitEvent('composer_click_success', { selector, shadow, retry: true });
            break;
          } catch (err) {
            composerError = err.message;
          }
        }
      }
    }

    if (!composerClicked) {
      return fail(
        ERROR_CODES.EDITOR_NOT_FOUND,
        `All composer selectors failed. Last error: ${composerError}`,
        STEPS.CLICK_COMPOSER,
      );
    }

    emitEvent('step_completed', { step: STEPS.CLICK_COMPOSER });

    // ── Step 7: WAIT_FOR_COMPOSER — MutationObserver wait (15s timeout) ──────
    emitEvent('step_started', { step: STEPS.WAIT_COMPOSER });

    const composerWait = await sendMessageSafe(tabId, {
      type: 'WAIT_FOR_COMPOSER',
      timeout_ms: 15000,
    });

    if (!composerWait || !composerWait.found) {
      return fail(
        ERROR_CODES.EDITOR_NOT_FOUND,
        composerWait?.error || 'Composer did not appear within 15s',
        STEPS.WAIT_COMPOSER,
      );
    }

    emitEvent('step_completed', { step: STEPS.WAIT_COMPOSER, selector: composerWait.selector });

    // ── Step 8: Wait for Lexical editor initialization ───────────────────────
    await sleep(3000);

    // ── Step 9: INSERT_TEXT — Send text via InputEvent strategy ───────────────
    emitEvent('step_started', { step: STEPS.INSERT_TEXT });

    const insertResult = await sendMessageSafe(tabId, {
      type: 'INSERT_TEXT',
      text: task.comment_text,
      task,
    });

    if (!insertResult || insertResult.error) {
      return fail(
        ERROR_CODES.TEXT_INSERT_FAILED,
        insertResult?.error || 'Text insertion failed',
        STEPS.INSERT_TEXT,
      );
    }

    emitEvent('step_completed', {
      step: STEPS.INSERT_TEXT,
      char_count: insertResult.char_count,
      text_matches: insertResult.text_matches,
    });

    // ── Step 10: VERIFY_TEXT — Check char_count and text match ────────────────
    emitEvent('step_started', { step: STEPS.VERIFY_TEXT });

    if (!insertResult.char_count || insertResult.char_count < 5) {
      return fail(
        ERROR_CODES.TEXT_INSERT_FAILED,
        `Only ${insertResult.char_count || 0} chars inserted, expected ${(task.comment_text || '').length}`,
        STEPS.VERIFY_TEXT,
      );
    }

    if (!insertResult.text_matches) {
      return fail(
        ERROR_CODES.TEXT_INSERT_FAILED,
        'Inserted text does not match expected content',
        STEPS.VERIFY_TEXT,
      );
    }

    emitEvent('step_completed', { step: STEPS.VERIFY_TEXT });

    // ── Step 11: Wait for text to settle in Lexical ──────────────────────────
    await sleep(1500);

    // ── Step 12: DEBUGGER_CLICK_SUBMIT — Trusted click on submit button ──────
    emitEvent('step_started', { step: STEPS.CLICK_SUBMIT });

    let submitClicked = false;
    let submitError = null;

    for (const { selector, shadow } of SUBMIT_SELECTORS) {
      try {
        await trustedClick(tabId, selector, shadow);
        submitClicked = true;
        emitEvent('submit_click_success', { selector });
        break;
      } catch (err) {
        submitError = err.message;
        // Try next selector
      }
    }

    if (!submitClicked) {
      return fail(
        ERROR_CODES.SUBMIT_FAILED,
        `All submit selectors failed. Last error: ${submitError}`,
        STEPS.CLICK_SUBMIT,
      );
    }

    emitEvent('step_completed', { step: STEPS.CLICK_SUBMIT });

    // ── Step 13: VERIFY_POSTED — Wait for comment to appear (30s) ────────────
    emitEvent('step_started', { step: STEPS.VERIFY_POSTED });

    const verifyResult = await sendMessageSafe(tabId, {
      type: 'VERIFY_POSTED',
      expected_text: task.comment_text,
      timeout_ms: 30000,
    });

    if (!verifyResult || !verifyResult.found) {
      return fail(
        ERROR_CODES.TIMEOUT,
        verifyResult?.error || 'Comment did not appear within 30s after submit',
        STEPS.VERIFY_POSTED,
      );
    }

    const { permalink, comment_id } = verifyResult;

    emitEvent('step_completed', {
      step: STEPS.VERIFY_POSTED,
      permalink,
      comment_id,
    });

    // ── Step 14: REPORT — POST result to backend ─────────────────────────────
    emitEvent('step_started', { step: STEPS.REPORT });

    let reportSuccess = false;
    try {
      reportSuccess = await reportToBackend(task, permalink, comment_id);
    } catch (reportErr) {
      // Non-fatal: task was posted successfully even if report fails
      emitEvent('report_error', { error: reportErr.message });
    }

    emitEvent('step_completed', { step: STEPS.REPORT, reported: reportSuccess });

    // ── SUCCESS ──────────────────────────────────────────────────────────────
    emitEvent('task_execution_completed', {
      permalink,
      comment_id,
      duration_ms: Date.now() - startedAt,
    });

    return {
      success: true,
      permalink,
      comment_id,
      events,
      duration_ms: Date.now() - startedAt,
    };

  } catch (err) {
    // Unexpected error — catch-all
    return fail(
      ERROR_CODES.DOM_CHANGED,
      `Unexpected error: ${err.message || 'Unknown'}`,
      'unknown',
    );
  }
}

// ─── Helper Functions ──────────────────────────────────────────────────────

/**
 * Send a message to the content script with error handling.
 * Returns null if the content script is not reachable.
 *
 * @param {number} tabId
 * @param {Object} message
 * @returns {Promise<Object|null>}
 */
async function sendMessageSafe(tabId, message) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (err) {
    console.warn('[RAMP Executor] sendMessage failed:', message.type, err.message);
    return null;
  }
}

/**
 * Wait for a tab to finish loading (status === 'complete').
 *
 * @param {number} tabId
 * @param {number} timeoutMs - Maximum time to wait
 * @returns {Promise<void>}
 */
function waitForTabLoad(tabId, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    let settled = false;

    const listener = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === 'complete') {
        if (!settled) {
          settled = true;
          chrome.tabs.onUpdated.removeListener(listener);
          // Give Reddit JS additional time to render DOM
          setTimeout(resolve, 2000);
        }
      }
    };

    chrome.tabs.onUpdated.addListener(listener);

    setTimeout(() => {
      if (!settled) {
        settled = true;
        chrome.tabs.onUpdated.removeListener(listener);
        // Resolve anyway after timeout (page may be usable)
        resolve();
      }
    }, timeoutMs);
  });
}

/**
 * Report task completion to RAMP backend.
 *
 * @param {Object} task - The executed task
 * @param {string|null} permalink - Reddit comment permalink
 * @param {string|null} commentId - Reddit comment ID
 * @returns {Promise<boolean>} - true if report succeeded
 */
async function reportToBackend(task, permalink, commentId) {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) {
    console.warn('[RAMP Executor] Cannot report: no auth');
    return false;
  }

  const payload = {
    task_id: task.task_id,
    result_type: 'task_completed',
    permalink,
    comment_id: commentId,
    posted_at: new Date().toISOString(),
  };

  const response = await fetch(`${auth.rampUrl}/api/extension/report`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${auth.token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`Report failed: ${response.status} ${text.substring(0, 100)}`);
  }

  return true;
}

/**
 * Sleep utility.
 * @param {number} ms
 * @returns {Promise<void>}
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
