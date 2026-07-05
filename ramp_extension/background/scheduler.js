/**
 * RAMP Extension v2 — Scheduler Module
 *
 * Replaces the old timer.js for automated task execution.
 * Checks every ~15s for approved tasks that are due (scheduled_at ≤ now with jitter),
 * then dispatches them one at a time through the executor module.
 *
 * Safety constraints:
 *   - 3-minute minimum interval between executions
 *   - Active hours only: 08:00–22:00 executor local time
 *   - pause_all flag from heartbeat response stops all execution
 *   - dom_health "broken" stops execution (avoids cascading failures)
 *   - One task per tick (no parallel execution)
 *   - Double-dispatch prevention (task marked 'executing' before dispatch)
 *
 * Storage keys:
 *   ramp_scheduler_state: { last_execution_time, pause_all }
 *
 * @module background/scheduler
 */

import { executeTask } from './executor.js';
import { executeTaskOldReddit } from './executor-old-reddit.js';
import { getQueue, saveQueue } from './queue.js';
import { recordFailureAndDecide, resetRetryState } from './retry-engine.js';
import { recordSuccess, recordFailure, getHealthState } from './health-monitor.js';
import { getAuth } from '../shared/auth.js';

// ─── Constants ─────────────────────────────────────────────────────────────

/** Chrome alarm name for the scheduler. */
export const SCHEDULER_ALARM_NAME = 'ramp-scheduler';

/** Scheduler check period in minutes (0.25 = 15 seconds). */
const SCHEDULER_PERIOD_MINUTES = 0.25;

/** Minimum interval between executions in milliseconds (3 minutes). */
const MIN_EXECUTION_INTERVAL_MS = 180000;

/** Active hours start (inclusive) — executor local time. */
const ACTIVE_HOURS_START = 8;

/** Active hours end (exclusive) — executor local time. */
const ACTIVE_HOURS_END = 22;

/** Default jitter range in milliseconds (±5 minutes). */
const JITTER_RANGE_MS = 300000;

/** Storage key for scheduler state. */
const SCHEDULER_STATE_KEY = 'ramp_scheduler_state';

/** Tab load timeout in milliseconds. */
const TAB_LOAD_TIMEOUT_MS = 15000;

// ─── Lock to prevent concurrent ticks ──────────────────────────────────────

let _tickInProgress = false;

// ─── Public API ────────────────────────────────────────────────────────────

/**
 * Start the scheduler alarm (fires every ~15 seconds).
 * Chrome may clamp this to ~30s minimum in production, which is acceptable.
 */
export async function startScheduler() {
  await chrome.alarms.create(SCHEDULER_ALARM_NAME, {
    delayInMinutes: SCHEDULER_PERIOD_MINUTES,
    periodInMinutes: SCHEDULER_PERIOD_MINUTES,
  });
  console.log('[RAMP Scheduler] Started — checking every ~15s for due approved tasks');
}

/**
 * Stop the scheduler alarm.
 */
export async function stopScheduler() {
  await chrome.alarms.clear(SCHEDULER_ALARM_NAME);
  console.log('[RAMP Scheduler] Stopped');
}

/**
 * Main scheduler tick — called every ~15s by the alarm listener.
 *
 * Logic:
 *   1. Check pause_all flag → return if paused
 *   2. Check dom_health → return if broken
 *   3. Check active hours (08:00–22:00 local) → return if outside
 *   4. Check 3-minute minimum interval since last execution → return if too soon
 *   5. Find approved tasks that are due (scheduled_at + jitter ≤ now)
 *   6. Execute the first due task found
 *   7. Handle success/failure outcomes
 */
export async function schedulerTick() {
  // Prevent concurrent ticks (service worker can wake and fire multiple)
  if (_tickInProgress) {
    return;
  }
  _tickInProgress = true;

  try {
    await _doTick();
  } catch (err) {
    console.error('[RAMP Scheduler] Tick error:', err.message || err);
  } finally {
    _tickInProgress = false;
  }
}

// ─── Internal Tick Logic ───────────────────────────────────────────────────

async function _doTick() {
  // 1. Check pause_all flag
  const state = await getSchedulerState();
  if (state.pause_all) {
    return;
  }

  // 2. Check dom_health from health monitor
  const healthState = await getHealthState();
  if (healthState.dom_health === 'broken') {
    // Auto-recovery: if broken for >30 min, reset and retry once
    const brokenSince = healthState.dom_health_since
      ? new Date(healthState.dom_health_since).getTime()
      : Date.now();
    const brokenDuration = Date.now() - brokenSince;
    if (brokenDuration > 30 * 60 * 1000) {
      // Reset health and allow one more attempt
      await recordSuccess(); // clears broken state
      console.log('[RAMP Scheduler] Auto-recovered dom_health after 30 min cooldown');
    } else {
      return;
    }
  }

  // 3. Check active hours: 08:00–22:00 executor local time
  if (!isWithinActiveHours()) {
    return;
  }

  // 4. Check 3-minute minimum interval
  if (state.last_execution_time) {
    const elapsed = Date.now() - new Date(state.last_execution_time).getTime();
    if (elapsed < MIN_EXECUTION_INTERVAL_MS) {
      return;
    }
  }

  // 5. Get queue and find due approved tasks
  const queue = await getQueue();
  const now = Date.now();
  const MAX_TASK_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours

  // Filter approved tasks, auto-expire ones older than 24h
  const approvedTasks = [];
  let expiredCount = 0;

  for (const task of queue) {
    if (task.status !== 'approved') continue;

    // Auto-expire tasks older than 24h
    const createdAt = task.created_at ? new Date(task.created_at).getTime() : 0;
    if (createdAt > 0 && (now - createdAt) > MAX_TASK_AGE_MS) {
      task.status = 'failed';
      task.error_code = 'EXPIRED';
      task.error_details = 'Task expired (older than 24h)';
      task.failed_at = new Date().toISOString();
      expiredCount++;
      continue;
    }

    approvedTasks.push(task);
  }

  if (expiredCount > 0) {
    await saveQueue(queue);
    console.log(`[RAMP Scheduler] Auto-expired ${expiredCount} stale task(s) older than 24h`);
  }

  if (approvedTasks.length === 0) {
    return;
  }
  let dueTask = null;

  for (const task of approvedTasks) {
    // Skip tasks that are already executing (double-dispatch prevention)
    if (task.status === 'executing') {
      continue;
    }

    // Skip tasks that have a retry_after in the future
    if (task.retry_after && new Date(task.retry_after).getTime() > now) {
      continue;
    }

    // Apply jitter to scheduled_at
    const jitteredTime = applyJitter(task.scheduled_at, task._jitter_offset);

    if (jitteredTime <= now) {
      dueTask = task;
      break;
    }
  }

  if (!dueTask) {
    return;
  }

  // 6. Mark task as 'executing' to prevent double-dispatch
  dueTask.status = 'executing';
  dueTask.execution_started_at = new Date().toISOString();
  await saveQueue(queue);

  // 7. Find or create a Reddit tab
  let tab;
  try {
    tab = await findOrCreateRedditTab();
  } catch (err) {
    console.error('[RAMP Scheduler] Failed to get Reddit tab:', err.message);
    // Revert task status
    dueTask.status = 'approved';
    delete dueTask.execution_started_at;
    await saveQueue(queue);
    return;
  }

  if (!tab) {
    console.warn('[RAMP Scheduler] No Reddit tab available');
    dueTask.status = 'approved';
    delete dueTask.execution_started_at;
    await saveQueue(queue);
    return;
  }

  // 8. Execute the task (route based on posting_strategy)
  console.log(`[RAMP Scheduler] Executing task ${dueTask.task_id} on tab ${tab.id} (strategy: ${dueTask.posting_strategy || 'new_reddit_debugger'})`);
  const result = await _executeDueTask(dueTask, tab.id);

  // 9. Handle outcome
  if (result.success) {
    await handleSuccess(dueTask, result, queue);
  } else {
    await handleFailure(dueTask, result, queue);
  }

  // 10. Flush events to backend (non-critical)
  if (result.events && result.events.length > 0) {
    await flushEvents(result.events);
  }

  // 11. Update badge
  await updateBadge(queue);
}

// ─── Strategy-Based Task Execution Router ──────────────────────────────────

/**
 * Route a task to the correct executor module based on its posting_strategy field.
 *
 * DEFAULT: old_reddit (most reliable — plain textarea, no Shadow DOM, no reCAPTCHA).
 *
 * - 'old_reddit' or null/undefined → executeTaskOldReddit() (textarea + .save button via old.reddit.com)
 * - 'new_reddit_debugger' → executeTask() (chrome.debugger trusted clicks — only for A/B test)
 *
 * The posting_strategy used is included in the result for backend reporting.
 *
 * @param {Object} task - The task object from the queue
 * @param {number} tabId - Chrome tab ID to execute in
 * @returns {Promise<ExecutionResult>}
 */
async function _executeDueTask(task, tabId) {
  const strategy = task.posting_strategy || 'old_reddit';

  let result;
  if (strategy === 'new_reddit_debugger') {
    result = await executeTask(task, tabId);
  } else {
    // Default: old_reddit (most reliable path)
    result = await executeTaskOldReddit(task, tabId);
  }

  // Include posting_strategy in result for backend reporting
  result.posting_strategy = strategy;

  return result;
}

// ─── Success Handler ───────────────────────────────────────────────────────

async function handleSuccess(task, result, queue) {
  // Mark task as completed in queue
  task.status = 'completed';
  task.completed_at = new Date().toISOString();
  task.permalink = result.permalink || null;
  task.comment_id = result.comment_id || null;
  task.posting_strategy_used = result.posting_strategy || task.posting_strategy || 'new_reddit_debugger';
  await saveQueue(queue);

  // Record success in health monitor (resets failure counters)
  await recordSuccess();

  // Reset retry state for this task
  await resetRetryState(task.task_id);

  // Update last_execution_time
  await updateLastExecutionTime();

  console.log(`[RAMP Scheduler] Task ${task.task_id} completed successfully`);
}

// ─── Failure Handler ───────────────────────────────────────────────────────

async function handleFailure(task, result, queue) {
  const errorCode = result.error_code || 'UNKNOWN';

  // Get retry decision from retry engine
  const decision = await recordFailureAndDecide(task.task_id, errorCode);

  if (decision.shouldRetry) {
    // Set task back to approved with a retry_after delay
    task.status = 'approved';
    task.retry_after = new Date(Date.now() + decision.delayMs).toISOString();
    task.last_error = errorCode;
    delete task.execution_started_at;
    console.log(`[RAMP Scheduler] Task ${task.task_id} will retry after ${decision.delayMs}ms (${errorCode})`);
  } else if (decision.markFailed) {
    // Mark task as permanently failed
    task.status = 'failed';
    task.failed_at = new Date().toISOString();
    task.error_code = errorCode;
    task.error_details = result.error_details || null;
    delete task.execution_started_at;

    // Record failure in health monitor
    await recordFailure(errorCode);

    console.warn(`[RAMP Scheduler] Task ${task.task_id} permanently failed: ${errorCode}`);
  }

  if (decision.markBroken) {
    // Record failure to potentially set dom_health to broken
    await recordFailure(errorCode);
    console.warn(`[RAMP Scheduler] DOM marked broken after ${errorCode}`);
  }

  await saveQueue(queue);

  // Report failure to backend
  await reportFailureToBackend(task, result);
}

// ─── Helper Functions ──────────────────────────────────────────────────────

/**
 * Check if current time is within active hours (08:00–22:00 local time).
 * @returns {boolean}
 */
function isWithinActiveHours() {
  const hour = new Date().getHours();
  return hour >= ACTIVE_HOURS_START && hour < ACTIVE_HOURS_END;
}

/**
 * Apply jitter to a scheduled time.
 * Uses a stable per-task jitter offset to avoid re-rolling on each tick.
 * If no _jitter_offset stored, treats scheduled_at directly.
 *
 * @param {string|null} scheduledAt - ISO string of scheduled time
 * @param {number|undefined} storedOffset - Pre-computed jitter offset in ms
 * @returns {number} Jittered timestamp in milliseconds
 */
function applyJitter(scheduledAt, storedOffset) {
  if (!scheduledAt) {
    // No scheduled time = immediate
    return 0;
  }

  const baseTime = new Date(scheduledAt).getTime();
  if (isNaN(baseTime)) {
    return 0;
  }

  // Use stored offset if available, otherwise apply no jitter
  // (jitter offset is assigned when task enters 'approved' state)
  const offset = typeof storedOffset === 'number' ? storedOffset : 0;
  return baseTime + offset;
}

/**
 * Generate a random jitter offset in the range [-JITTER_RANGE_MS, +JITTER_RANGE_MS].
 * Stored on the task so the same jitter applies across ticks.
 * @returns {number} Jitter offset in milliseconds
 */
export function generateJitterOffset() {
  return Math.floor((Math.random() * 2 - 1) * JITTER_RANGE_MS);
}

/**
 * Find an existing Reddit tab or create a new one.
 * Preference: existing Reddit tab → create new background tab.
 * @returns {Promise<chrome.tabs.Tab|null>}
 */
async function findOrCreateRedditTab() {
  // Try to find existing Reddit tab (prefer old.reddit.com)
  const tabs = await chrome.tabs.query({ url: ['*://old.reddit.com/*', '*://*.reddit.com/*'] });
  if (tabs.length > 0) {
    // Prefer old.reddit.com tabs over www.reddit.com
    const oldRedditTab = tabs.find(t => t.url && t.url.includes('old.reddit.com'));
    if (oldRedditTab) return oldRedditTab;
    // Return the most recently accessed one
    return tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
  }

  // Create a new tab (inactive/background) on old.reddit.com
  const newTab = await chrome.tabs.create({
    url: 'https://old.reddit.com',
    active: false,
  });

  // Wait for tab to load
  await waitForTabLoad(newTab.id, TAB_LOAD_TIMEOUT_MS);
  return newTab;
}

/**
 * Wait for a tab to reach 'complete' status.
 * @param {number} tabId
 * @param {number} timeoutMs
 * @returns {Promise<void>}
 */
function waitForTabLoad(tabId, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;

    const listener = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === 'complete') {
        if (!settled) {
          settled = true;
          chrome.tabs.onUpdated.removeListener(listener);
          // Extra delay for Reddit SPA render
          setTimeout(resolve, 2000);
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

/**
 * Get scheduler state from chrome.storage.local.
 * @returns {Promise<{last_execution_time: string|null, pause_all: boolean}>}
 */
async function getSchedulerState() {
  const result = await chrome.storage.local.get(SCHEDULER_STATE_KEY);
  return result[SCHEDULER_STATE_KEY] || {
    last_execution_time: null,
    pause_all: false,
  };
}

/**
 * Update the last_execution_time in scheduler state.
 */
async function updateLastExecutionTime() {
  const state = await getSchedulerState();
  state.last_execution_time = new Date().toISOString();
  await chrome.storage.local.set({ [SCHEDULER_STATE_KEY]: state });
}

/**
 * Set the pause_all flag (called when heartbeat response contains pause_all: true).
 * @param {boolean} paused
 */
export async function setPauseAll(paused) {
  const state = await getSchedulerState();
  state.pause_all = paused;
  await chrome.storage.local.set({ [SCHEDULER_STATE_KEY]: state });
  if (paused) {
    console.log('[RAMP Scheduler] pause_all = true — execution paused');
  } else {
    console.log('[RAMP Scheduler] pause_all = false — execution resumed');
  }
}

/**
 * Flush execution events to the backend.
 * Non-critical — failures are logged but don't affect task outcome.
 *
 * @param {Array} events - Array of event objects from executor
 */
async function flushEvents(events) {
  if (!events || events.length === 0) return;

  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  try {
    await fetch(`${auth.rampUrl}/api/extension/events`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${auth.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ events }),
    });
  } catch (err) {
    console.warn('[RAMP Scheduler] Event flush failed:', err.message);
  }
}

/**
 * Report a failed task to the backend.
 * Non-critical — logged but doesn't affect local state.
 *
 * @param {Object} task - The failed task
 * @param {Object} result - The execution result with error info
 */
async function reportFailureToBackend(task, result) {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  try {
    await fetch(`${auth.rampUrl}/api/extension/report`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${auth.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        task_id: task.task_id,
        result_type: 'task_failed',
        error_code: result.error_code || 'UNKNOWN',
        error_details: result.error_details || null,
        step: result.step || null,
        duration_ms: result.duration_ms || null,
        posting_strategy: result.posting_strategy || task.posting_strategy || 'new_reddit_debugger',
      }),
    });
  } catch (err) {
    console.warn('[RAMP Scheduler] Failure report failed:', err.message);
  }
}

/**
 * Update the extension badge with count of pending/approved tasks.
 * @param {Array} [queue] - Optional pre-loaded queue array
 */
async function updateBadge(queue) {
  try {
    const tasks = queue || await getQueue();
    const pendingCount = tasks.filter(
      t => t.status === 'pending' || t.status === 'approved'
    ).length;
    await chrome.action.setBadgeText({ text: pendingCount > 0 ? String(pendingCount) : '' });
    await chrome.action.setBadgeBackgroundColor({ color: '#7c3aed' });
  } catch {
    // Non-critical
  }
}
