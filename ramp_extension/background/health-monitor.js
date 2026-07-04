/**
 * RAMP Extension — Health Monitor Module
 *
 * Evaluates dom_health based on consecutive failure counts from retry-engine.
 * Checks Reddit session validity by querying content script.
 * Stores health state in chrome.storage.local for heartbeat + popup consumption.
 *
 * Storage format in chrome.storage.local:
 * {
 *   "ramp_health": {
 *     "dom_health": "ok",           // "ok" | "broken"
 *     "reddit_session_valid": true,
 *     "last_task_executed_at": null  // ISO string or null
 *   }
 * }
 *
 * Exports:
 *   evaluateDomHealth()    — returns "ok" | "broken" based on consecutive failures
 *   getHealthState()       — returns full health state for heartbeat payload
 *   recordSuccess()        — resets failure counters, updates last_task_executed_at
 *   recordFailure(type)    — delegates to retry-engine, re-evaluates dom_health
 *   checkRedditSession()   — queries Reddit tab for session validity
 */

import { getConsecutiveFailures, resetAllConsecutiveFailures } from './retry-engine.js';

export const HEALTH_STORAGE_KEY = 'ramp_health';

/** Threshold: 3+ consecutive DOM_CHANGED or EDITOR_NOT_FOUND → "broken" */
const DOM_BROKEN_THRESHOLD = 3;

/**
 * Evaluate dom_health based on consecutive failure counts.
 * Rule: 3+ consecutive DOM_CHANGED or EDITOR_NOT_FOUND → "broken"
 * @returns {Promise<string>} "ok" | "broken"
 */
export async function evaluateDomHealth() {
  const failures = await getConsecutiveFailures();

  const domChangedCount = failures.DOM_CHANGED || 0;
  const editorNotFoundCount = failures.EDITOR_NOT_FOUND || 0;

  if (domChangedCount >= DOM_BROKEN_THRESHOLD || editorNotFoundCount >= DOM_BROKEN_THRESHOLD) {
    return 'broken';
  }

  return 'ok';
}

/**
 * Get current health state for heartbeat payload.
 * Reads from chrome.storage.local (last persisted state).
 * @returns {Promise<{dom_health: string, reddit_session_valid: boolean, last_task_executed_at: string|null}>}
 */
export async function getHealthState() {
  const result = await chrome.storage.local.get(HEALTH_STORAGE_KEY);
  const state = result[HEALTH_STORAGE_KEY] || {
    dom_health: 'ok',
    reddit_session_valid: true,
    last_task_executed_at: null,
  };

  // Always re-evaluate dom_health from live failure counts
  state.dom_health = await evaluateDomHealth();

  return state;
}

/**
 * Record a successful execution — resets failure counters, updates last_task_executed_at.
 */
export async function recordSuccess() {
  // Reset all consecutive failure counters in retry-engine
  await resetAllConsecutiveFailures();

  // Update stored health state
  const result = await chrome.storage.local.get(HEALTH_STORAGE_KEY);
  const state = result[HEALTH_STORAGE_KEY] || {
    dom_health: 'ok',
    reddit_session_valid: true,
    last_task_executed_at: null,
  };

  state.dom_health = 'ok';
  state.dom_health_since = null;
  state.last_task_executed_at = new Date().toISOString();

  await chrome.storage.local.set({ [HEALTH_STORAGE_KEY]: state });

  console.log('[RAMP Health] Success recorded, counters reset');
}

/**
 * Record a failure — re-evaluates dom_health and stores in chrome.storage.local.
 * Note: The actual retry-engine tracking (incrementing consecutive_failures)
 * is done by retry-engine.js recordFailureAndDecide(). This function
 * re-evaluates and persists the resulting health state.
 *
 * @param {string} errorType - One of: DOM_CHANGED, EDITOR_NOT_FOUND, SUBMIT_FAILED, TIMEOUT, NETWORK_ERROR
 */
export async function recordFailure(errorType) {
  // Re-evaluate dom_health after the failure was recorded by retry-engine
  const domHealth = await evaluateDomHealth();

  // Update stored health state
  const result = await chrome.storage.local.get(HEALTH_STORAGE_KEY);
  const state = result[HEALTH_STORAGE_KEY] || {
    dom_health: 'ok',
    reddit_session_valid: true,
    last_task_executed_at: null,
  };

  state.dom_health = domHealth;

  // Track when dom_health first became broken
  if (domHealth === 'broken' && !state.dom_health_since) {
    state.dom_health_since = new Date().toISOString();
  } else if (domHealth === 'ok') {
    state.dom_health_since = null;
  }

  await chrome.storage.local.set({ [HEALTH_STORAGE_KEY]: state });

  if (domHealth === 'broken') {
    console.warn(`[RAMP Health] DOM health BROKEN after ${errorType} failures`);
  } else {
    console.log(`[RAMP Health] Failure recorded (${errorType}), dom_health still ok`);
  }
}

/**
 * Check Reddit session validity by querying a Reddit tab.
 * Sends CHECK_AUTH message to content script on any active Reddit tab.
 * Updates stored reddit_session_valid state.
 *
 * Behavior:
 * - If expired: true → set reddit_session_valid = false
 * - If expired: false → set reddit_session_valid = true
 * - If no Reddit tab found → keep previous state (don't change)
 *
 * @returns {Promise<boolean>} true if session is valid
 */
export async function checkRedditSession() {
  const result = await chrome.storage.local.get(HEALTH_STORAGE_KEY);
  const state = result[HEALTH_STORAGE_KEY] || {
    dom_health: 'ok',
    reddit_session_valid: true,
    last_task_executed_at: null,
  };

  try {
    // Find any Reddit tab to query
    const tabs = await chrome.tabs.query({
      url: ['*://*.reddit.com/*'],
    });

    if (!tabs || tabs.length === 0) {
      // No Reddit tab found — keep previous state
      console.log('[RAMP Health] No Reddit tab found, keeping previous session state');
      return state.reddit_session_valid;
    }

    // Try each tab until one responds
    for (const tab of tabs) {
      try {
        const response = await chrome.tabs.sendMessage(tab.id, { type: 'CHECK_AUTH' });
        if (response && typeof response.expired === 'boolean') {
          const valid = !response.expired;
          state.reddit_session_valid = valid;
          await chrome.storage.local.set({ [HEALTH_STORAGE_KEY]: state });

          if (!valid) {
            console.warn('[RAMP Health] Reddit session EXPIRED');
          } else {
            console.log('[RAMP Health] Reddit session valid');
          }

          return valid;
        }
      } catch {
        // Content script not injected on this tab, try next
        continue;
      }
    }

    // No tab responded — keep previous state
    console.log('[RAMP Health] No Reddit tab responded to CHECK_AUTH, keeping previous state');
    return state.reddit_session_valid;
  } catch (error) {
    console.warn('[RAMP Health] Session check error:', error.message || error);
    return state.reddit_session_valid;
  }
}
