/**
 * RAMP Extension — Task Poller
 *
 * Polls GET {rampUrl}/api/extension/tasks at a configurable interval
 * using chrome.alarms for reliable timing in MV3 service workers.
 *
 * Exports:
 *   startPolling(intervalSeconds) — starts the polling alarm
 *   stopPolling()                 — clears the polling alarm
 *   pollOnce()                    — performs a single poll (immediate check)
 *   setTaskCallback(fn)           — register handler for received tasks
 *   ALARM_NAME                    — alarm identifier constant
 */

import { getAuth, getHeaders } from '../shared/auth.js';

/** Alarm name used for the polling schedule. */
export const ALARM_NAME = 'ramp-task-poll';

/** Default poll interval in seconds (from policy, overridable). */
const DEFAULT_INTERVAL_SECONDS = 30;

/** Registered callback for received tasks. */
let _onTasksReceived = null;

/**
 * Register a callback invoked when tasks are successfully fetched.
 * @param {(tasks: Array) => void} fn
 */
export function setTaskCallback(fn) {
  _onTasksReceived = fn;
}

/**
 * Start polling GET /api/extension/tasks at the given interval.
 * Uses chrome.alarms API for reliable timing (service workers don't support setInterval).
 *
 * @param {number} [intervalSeconds] — poll interval; defaults to 30s
 */
export async function startPolling(intervalSeconds = DEFAULT_INTERVAL_SECONDS) {
  // Clear any existing alarm before creating a new one
  await chrome.alarms.clear(ALARM_NAME);

  // chrome.alarms.create periodInMinutes minimum is 0.5 (30s) in production,
  // but we set it as close as allowed. For intervals < 30s in dev, Chrome
  // will clamp to its minimum.
  const periodInMinutes = intervalSeconds / 60;

  chrome.alarms.create(ALARM_NAME, {
    delayInMinutes: 0.1, // fire first poll quickly (~6s)
    periodInMinutes,
  });

  console.log(`[RAMP Poller] Started polling every ${intervalSeconds}s`);
}

/**
 * Stop the polling alarm.
 */
export async function stopPolling() {
  await chrome.alarms.clear(ALARM_NAME);
  console.log('[RAMP Poller] Polling stopped');
}

/**
 * Perform a single poll — useful for immediate checks (e.g., on install or wake).
 * Fetches GET {rampUrl}/api/extension/tasks.
 *
 * On success: passes tasks array to registered callback.
 * On auth failure: logs and skips (will retry on next alarm).
 * On network error: logs and skips (will retry on next alarm).
 */
export async function pollOnce() {
  try {
    const auth = await getAuth();
    if (!auth || !auth.rampUrl || !auth.token || !auth.nodeId) {
      console.log('[RAMP Poller] Not authenticated or missing nodeId, skipping poll');
      return;
    }

    const headers = await getHeaders();
    if (!headers) {
      console.log('[RAMP Poller] No auth headers available, skipping poll');
      return;
    }

    const url = `${auth.rampUrl}/api/extension/tasks?execution_node_id=${encodeURIComponent(auth.nodeId)}`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      console.warn(`[RAMP Poller] Poll failed with status ${response.status}`);
      return;
    }

    const data = await response.json();
    const tasks = data.tasks || [];

    if (_onTasksReceived && tasks.length > 0) {
      _onTasksReceived(tasks);
    }

    // Handle commands from backend (e.g., pause_all)
    if (data.commands && data.commands.length > 0) {
      _handleCommands(data.commands);
    }
  } catch (error) {
    // Network error — log but don't crash. Will retry on next alarm.
    console.warn('[RAMP Poller] Poll error (will retry):', error.message);
  }
}

/**
 * Handle backend commands delivered alongside tasks.
 * @param {Array} commands
 */
function _handleCommands(commands) {
  for (const cmd of commands) {
    console.log(`[RAMP Poller] Received command: ${cmd.type || cmd}`);
    // Command handling will be implemented in Task 8.7 (kill switch)
  }
}
