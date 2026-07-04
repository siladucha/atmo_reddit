/**
 * RAMP Extension — Execution State Machine v2
 *
 * Deterministic runtime: each task goes through a strict state sequence.
 * Every transition emits an event to the backend event stream.
 *
 * CORE PRINCIPLE:
 *   approve = permission to PREPARE execution only
 *   approve ≠ permission to POST
 *
 * Execution modes:
 *   prepare_only (default) — navigate + insert text + verify + STOP. Never submit.
 *   execute_manual (Phase 2) — prepare + wait for explicit user Publish click.
 *
 * States (prepare_only):
 *   INIT → PRECHECK → NAVIGATING → CONTEXT_VERIFIED → EDITOR_OPENED →
 *   TEXT_INSERTED → READY_TO_SUBMIT (terminal for prepare_only)
 *
 * States (execute_manual, Phase 2):
 *   ... → READY_TO_SUBMIT → WAITING_USER_ACTION → SUBMITTED → COMPLETED
 *
 * SAFETY INVARIANT:
 *   Transition READY_TO_SUBMIT → SUBMITTED is IMPOSSIBLE without a user event.
 *   No code path exists that auto-submits.
 *
 * Extension NEVER decides truth. It observes and reports.
 * Backend reconciles event stream with intent (EPG) to derive truth.
 */

import { getAuth } from '../shared/auth.js';

// ─── State Definitions ─────────────────────────────────────────────────────

export const STATES = {
  INIT: 'INIT',
  PRECHECK: 'PRECHECK',
  NAVIGATING: 'NAVIGATING',
  CONTEXT_VERIFIED: 'CONTEXT_VERIFIED',
  EDITOR_OPENED: 'EDITOR_OPENED',
  TEXT_INSERTED: 'TEXT_INSERTED',
  READY_TO_SUBMIT: 'READY_TO_SUBMIT',
  // Phase 2 only:
  WAITING_USER_ACTION: 'WAITING_USER_ACTION',
  SUBMITTED: 'SUBMITTED',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED',
};

export const EXECUTION_MODES = {
  PREPARE_ONLY: 'prepare_only',
  EXECUTE_MANUAL: 'execute_manual',
};

export const FAILURE_REASONS = {
  DOM_CHANGED: 'DOM_CHANGED',
  THREAD_DELETED: 'THREAD_DELETED',
  THREAD_LOCKED: 'THREAD_LOCKED',
  AUTH_FAILED: 'AUTH_FAILED',
  RATE_LIMITED: 'RATE_LIMITED',
  SESSION_LOST: 'SESSION_LOST',
  CAPABILITY_MISSING: 'CAPABILITY_MISSING',
  WRONG_PAGE: 'WRONG_PAGE',
  EDITOR_NOT_FOUND: 'EDITOR_NOT_FOUND',
  TEXT_INSERT_FAILED: 'TEXT_INSERT_FAILED',
  TEXT_MISMATCH: 'TEXT_MISMATCH',
  SUBMIT_BUTTON_MISSING: 'SUBMIT_BUTTON_MISSING',
  SUBMIT_FAILED: 'SUBMIT_FAILED',
  PROOF_MISSING: 'PROOF_MISSING',
  UNKNOWN: 'UNKNOWN',
};

// ─── Allowed Transitions ───────────────────────────────────────────────────

const TRANSITIONS = {
  INIT: ['PRECHECK', 'FAILED'],
  PRECHECK: ['NAVIGATING', 'FAILED'],
  NAVIGATING: ['CONTEXT_VERIFIED', 'FAILED'],
  CONTEXT_VERIFIED: ['EDITOR_OPENED', 'FAILED'],
  EDITOR_OPENED: ['TEXT_INSERTED', 'FAILED'],
  TEXT_INSERTED: ['READY_TO_SUBMIT', 'FAILED'],
  READY_TO_SUBMIT: ['WAITING_USER_ACTION', 'FAILED'],  // Phase 2 only
  WAITING_USER_ACTION: ['SUBMITTED', 'FAILED'],         // Phase 2 only
  SUBMITTED: ['COMPLETED', 'FAILED'],                   // Phase 2 only
  COMPLETED: [],
  FAILED: [],
};

// ─── Event Emitter ─────────────────────────────────────────────────────────

const eventQueue = [];

/**
 * Emit an execution event. Queued locally, flushed to backend periodically.
 */
function emit(taskId, eventType, data = {}) {
  const event = {
    task_id: taskId,
    event: eventType,
    timestamp: new Date().toISOString(),
    ...data,
  };
  eventQueue.push(event);
  console.log(`[RAMP SM] ${eventType}`, data);
}

/**
 * Flush queued events to backend. Non-blocking — failures retry next flush.
 */
export async function flushEvents() {
  if (eventQueue.length === 0) return;

  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  const batch = eventQueue.splice(0, eventQueue.length);

  try {
    await fetch(`${auth.rampUrl}/api/extension/events`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${auth.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ events: batch }),
    });
  } catch {
    // Put back for retry
    eventQueue.unshift(...batch);
  }
}

// ─── Proof Object ──────────────────────────────────────────────────────────

/**
 * Proof collected during prepare execution.
 * This is the observable output — what happened at each step.
 */
function createProof() {
  return {
    thread_opened: false,
    editor_found: false,
    text_inserted: false,
    char_count: 0,
    text_matches: false,
    submit_available: false,
    reddit_variant: null,
    reddit_tab_id: null,
    thread_url: null,
    not_published: true,  // ALWAYS true in prepare_only mode
  };
}

// ─── Task Execution Engine ─────────────────────────────────────────────────

/**
 * Execute a task through the state machine in prepare_only mode.
 *
 * STOPS at READY_TO_SUBMIT. Never clicks submit.
 * Returns proof of what was prepared.
 *
 * @param {object} task - Task from backend (task_id, thread_url, comment_text, etc.)
 * @param {number} tabId - Chrome tab ID to execute in
 * @param {string} [mode='prepare_only'] - Execution mode
 * @returns {Promise<{state: string, proof: object, result: object}>}
 */
export async function executeTaskStateMachine(task, tabId, mode = EXECUTION_MODES.PREPARE_ONLY) {
  let currentState = STATES.INIT;
  const proof = createProof();
  proof.reddit_tab_id = String(tabId);
  proof.thread_url = task.thread_url;

  const transition = (newState, data = {}) => {
    if (!TRANSITIONS[currentState]?.includes(newState)) {
      console.error(`[RAMP SM] Invalid transition: ${currentState} → ${newState}`);
      return false;
    }
    const from = currentState;
    currentState = newState;
    emit(task.task_id, `state_${newState.toLowerCase()}`, { from, ...data });
    return true;
  };

  const fail = (reason, details = '') => {
    currentState = STATES.FAILED;
    emit(task.task_id, 'task_failed', { failure_reason: reason, details, proof });
    return {
      state: STATES.FAILED,
      proof,
      result: { result_type: 'task_failed', error_code: reason, error_details: details },
    };
  };

  try {
    // ── INIT ──
    emit(task.task_id, 'task_started', {
      task_type: task.task_type,
      thread_url: task.thread_url,
      execution_mode: mode,
    });

    // ── PRECHECK ──
    if (!transition(STATES.PRECHECK)) return fail(FAILURE_REASONS.UNKNOWN);

    // Check Reddit session is alive
    const authCheck = await chrome.tabs.sendMessage(tabId, { type: 'CHECK_AUTH' }).catch(() => null);
    if (authCheck?.expired) return fail(FAILURE_REASONS.AUTH_FAILED, 'Reddit session expired');

    // Check tab is on reddit
    const tab = await chrome.tabs.get(tabId);
    if (!tab.url?.includes('reddit.com')) return fail(FAILURE_REASONS.WRONG_PAGE, tab.url);

    emit(task.task_id, 'precheck_passed', {});

    // ── NAVIGATING ──
    if (!transition(STATES.NAVIGATING)) return fail(FAILURE_REASONS.UNKNOWN);

    // Always navigate to the target thread URL (even if already on a /comments/ page)
    // This ensures we're on the CORRECT thread, not just any thread
    if (task.thread_url) {
      const currentTab = await chrome.tabs.get(tabId);
      const currentUrl = currentTab.url || '';
      const targetPath = task.thread_url.replace('https://www.reddit.com', '');
      
      // Navigate if not already on the exact target thread
      if (!currentUrl.includes(targetPath.split('?')[0].replace(/\/$/, ''))) {
        await chrome.tabs.update(tabId, { url: task.thread_url });
        await waitForTabLoad(tabId, 30000);
        // Extra delay for content script injection after navigation
        await new Promise(r => setTimeout(r, 3000));
      }
    }

    proof.thread_opened = true;
    emit(task.task_id, 'navigation_completed', { url: task.thread_url });

    // ── CONTEXT_VERIFIED ──
    if (!transition(STATES.CONTEXT_VERIFIED)) return fail(FAILURE_REASONS.UNKNOWN);

    // Verify page context (not locked, correct thread, etc.)
    // Retry up to 5 times — content script may not be ready immediately after navigation
    let context = null;
    for (let attempt = 0; attempt < 5; attempt++) {
      context = await chrome.tabs.sendMessage(tabId, { type: 'VERIFY_CONTEXT', task }).catch(() => null);
      if (context && (context.ok || context.error)) break;
      // Content script not ready — wait and retry
      await new Promise(r => setTimeout(r, 1500));
    }
    
    if (!context || context.error) {
      const reason = context?.error === 'thread_locked'
        ? FAILURE_REASONS.THREAD_LOCKED
        : FAILURE_REASONS.DOM_CHANGED;
      return fail(reason, context?.details || 'Context verification failed');
    }

    proof.reddit_variant = context.variant;
    emit(task.task_id, 'context_verified', { variant: context.variant });

    // ── EDITOR_OPENED ──
    if (!transition(STATES.EDITOR_OPENED)) return fail(FAILURE_REASONS.UNKNOWN);

    // Ask content script to expand the comment editor (but NOT insert text yet)
    // Retry if content script not responding
    let editorResult = null;
    for (let attempt = 0; attempt < 3; attempt++) {
      editorResult = await chrome.tabs.sendMessage(tabId, {
        type: 'EXPAND_EDITOR',
        task,
      }).catch(err => ({ error: err.message || 'Editor expand failed' }));
      if (editorResult && !editorResult.error?.includes('Could not establish connection')) break;
      await new Promise(r => setTimeout(r, 2000));
    }

    if (editorResult.error) {
      return fail(FAILURE_REASONS.EDITOR_NOT_FOUND, editorResult.error);
    }

    proof.editor_found = true;
    emit(task.task_id, 'editor_opened', { variant: proof.reddit_variant });

    // ── TEXT_INSERTED ──
    if (!transition(STATES.TEXT_INSERTED)) return fail(FAILURE_REASONS.UNKNOWN);

    // Ask content script to insert text into the editor
    // Wait extra time for Shreddit's restoreDraft to finish (fires on composer updated() lifecycle)
    await new Promise(r => setTimeout(r, 3000));

    const insertResult = await chrome.tabs.sendMessage(tabId, {
      type: 'INSERT_TEXT',
      task,
      text: task.comment_text,
    }).catch(err => ({ error: err.message || 'Text insert failed' }));

    if (insertResult.error) {
      return fail(FAILURE_REASONS.TEXT_INSERT_FAILED, insertResult.error);
    }

    proof.text_inserted = insertResult.text_inserted || false;
    proof.char_count = insertResult.char_count || 0;
    proof.text_matches = insertResult.text_matches || false;

    if (!proof.text_inserted || proof.char_count < 5) {
      return fail(FAILURE_REASONS.TEXT_INSERT_FAILED, `Inserted ${proof.char_count} chars, expected ${(task.comment_text || '').length}`);
    }

    if (!proof.text_matches) {
      return fail(FAILURE_REASONS.TEXT_MISMATCH, 'Inserted text does not match expected content');
    }

    emit(task.task_id, 'text_inserted', {
      char_count: proof.char_count,
      text_matches: proof.text_matches,
    });

    // ── READY_TO_SUBMIT ──
    if (!transition(STATES.READY_TO_SUBMIT)) return fail(FAILURE_REASONS.UNKNOWN);

    // Verify submit button exists (but DO NOT click it)
    const submitCheck = await chrome.tabs.sendMessage(tabId, {
      type: 'CHECK_SUBMIT_BUTTON',
    }).catch(() => ({ available: false }));

    proof.submit_available = submitCheck.available || false;

    if (!proof.submit_available) {
      // Non-fatal: text is inserted, but submit button not found (maybe disabled state)
      emit(task.task_id, 'submit_button_missing', {});
    }

    emit(task.task_id, 'ready_to_submit', {
      proof,
      execution_mode: mode,
    });

    // ═══════════════════════════════════════════════════════════════════════
    // STOP HERE in prepare_only mode.
    // The text is inserted. The editor is open. Submit was NOT clicked.
    // User can visually verify in the Reddit tab.
    // ═══════════════════════════════════════════════════════════════════════

    if (mode === EXECUTION_MODES.PREPARE_ONLY) {
      proof.not_published = true;

      emit(task.task_id, 'task_prepared', {
        proof,
        message: 'Text inserted and verified. Not published. Awaiting user decision.',
      });

      return {
        state: STATES.READY_TO_SUBMIT,
        proof,
        result: {
          result_type: 'task_prepared',
          status: 'prepared',
          proof,
        },
      };
    }

    // Phase 2: execute_manual mode would continue here with WAITING_USER_ACTION
    // For now, this code path is unreachable (mode is always prepare_only)
    return fail(FAILURE_REASONS.UNKNOWN, `Unsupported execution mode: ${mode}`);

  } catch (err) {
    return fail(FAILURE_REASONS.UNKNOWN, err.message || 'Unexpected error');
  }
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function waitForTabLoad(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    const listener = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        setTimeout(resolve, 2000); // Give Reddit JS time to render
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, timeoutMs);
  });
}

// ─── Periodic Event Flush ──────────────────────────────────────────────────

// Flush events every 10 seconds
setInterval(flushEvents, 10000);
