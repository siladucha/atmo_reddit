/**
 * RAMP Extension — Heartbeat Module
 *
 * POSTs /api/extension/heartbeat every 60 seconds to keep the backend
 * informed of node liveness, active Reddit account, and local queue depth.
 *
 * Uses chrome.alarms for reliable timing in MV3 service workers
 * (setInterval is not available in ephemeral service workers).
 *
 * Exports:
 *   startHeartbeat()       — starts the heartbeat alarm (every 60s)
 *   stopHeartbeat()        — clears the heartbeat alarm
 *   sendHeartbeat()        — performs a single heartbeat POST
 *   HEARTBEAT_ALARM_NAME   — alarm identifier constant
 */

import { getAuth, getHeaders } from '../shared/auth.js';
import { getQueueSize } from './queue.js';
import { getHealthState, checkRedditSession } from './health-monitor.js';

/** Alarm name for the heartbeat schedule. */
export const HEARTBEAT_ALARM_NAME = 'ramp-heartbeat';

/** Heartbeat interval in minutes (1 minute = 60 seconds). */
const HEARTBEAT_PERIOD_MINUTES = 1;

/**
 * Start the heartbeat alarm. Fires every 60 seconds.
 * Clears any existing heartbeat alarm before creating a new one.
 */
export async function startHeartbeat() {
  await chrome.alarms.clear(HEARTBEAT_ALARM_NAME);

  chrome.alarms.create(HEARTBEAT_ALARM_NAME, {
    delayInMinutes: HEARTBEAT_PERIOD_MINUTES,
    periodInMinutes: HEARTBEAT_PERIOD_MINUTES,
  });

  console.log('[RAMP Heartbeat] Started (every 60s)');
}

/**
 * Stop the heartbeat alarm.
 */
export async function stopHeartbeat() {
  await chrome.alarms.clear(HEARTBEAT_ALARM_NAME);
  console.log('[RAMP Heartbeat] Stopped');
}

/**
 * Perform a single heartbeat POST to the backend.
 *
 * Payload:
 *   {
 *     execution_node_id: <nodeId from auth>,
 *     active_reddit_username: <from active tab content script, or "">
 *     extension_version: <from manifest>,
 *     tasks_in_local_queue: <queue size>
 *   }
 *
 * On success: logs.
 * On failure: logs warning — does NOT crash or throw.
 */
export async function sendHeartbeat() {
  try {
    const auth = await getAuth();
    if (!auth || !auth.rampUrl || !auth.token || !auth.nodeId) {
      console.log('[RAMP Heartbeat] Not authenticated or missing nodeId, skipping');
      return;
    }

    const headers = await getHeaders();
    if (!headers) {
      console.log('[RAMP Heartbeat] No auth headers, skipping');
      return;
    }

    // Get current queue size
    const queueSize = await getQueueSize();

    // Get active reddit username from content script (best-effort)
    const activeUsername = await _getActiveRedditUsername();

    // Get extension version from manifest
    const extensionVersion = chrome.runtime.getManifest().version;

    // Check Reddit session validity (reports to health-monitor storage)
    await checkRedditSession();

    // Get health state (dom_health, reddit_session_valid, last_task_executed_at)
    const healthState = await getHealthState();

    const body = {
      execution_node_id: auth.nodeId,
      active_reddit_username: activeUsername,
      extension_version: extensionVersion,
      tasks_in_local_queue: queueSize,
      // Health monitoring fields (FR-6)
      reddit_session_valid: healthState.reddit_session_valid,
      dom_health: healthState.dom_health,
      last_task_executed_at: healthState.last_task_executed_at,
    };

    const url = `${auth.rampUrl}/api/extension/heartbeat`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (response.ok) {
      const data = await response.json();
      console.log('[RAMP Heartbeat] Sent successfully');

      // Store server commands (pause_all, daily_cap)
      await chrome.storage.local.set({
        ramp_pause_all: data.pause_all || false,
        ramp_daily_cap_remaining: data.daily_cap_remaining ?? null,
      });

      // Version check: server tells us if update is available
      if (data.update_available) {
        await chrome.storage.local.set({
          ramp_update_available: true,
          ramp_latest_version: data.latest_version || '',
          ramp_download_url: data.download_url || '',
        });
      } else {
        await chrome.storage.local.remove(['ramp_update_available', 'ramp_latest_version', 'ramp_download_url']);
      }

      // Server maintenance detection
      await chrome.storage.local.set({ ramp_server_status: 'ok' });
    } else if (response.status >= 500) {
      await chrome.storage.local.set({ ramp_server_status: 'maintenance' });
      console.warn(
        `[RAMP Heartbeat] Server error: ${response.status} ${response.statusText}`
      );
    } else {
      console.warn(
        `[RAMP Heartbeat] Failed: ${response.status} ${response.statusText}`
      );
    }
  } catch (error) {
    // Network error — log but don't crash. Will retry on next alarm.
    console.warn('[RAMP Heartbeat] Error (will retry):', error.message || error);
  }
}

/**
 * Attempt to get the active Reddit username from the currently active tab.
 * Sends a message to the content script on reddit.com tabs.
 *
 * Returns empty string if:
 *   - No active reddit.com tab
 *   - Content script not injected
 *   - Content script can't determine username
 *   - Any error occurs
 *
 * @returns {Promise<string>} Reddit username or empty string
 */
async function _getActiveRedditUsername() {
  try {
    // First try: ask content script on active reddit tab
    const tabs = await chrome.tabs.query({
      active: true,
      currentWindow: true,
      url: '*://*.reddit.com/*',
    });

    if (tabs && tabs.length > 0) {
      try {
        const response = await chrome.tabs.sendMessage(tabs[0].id, {
          type: 'GET_USERNAME',
        });
        if (response && response.username) {
          // Cache it
          await chrome.storage.local.set({ activeRedditUsername: response.username });
          return response.username;
        }
      } catch { /* content script not loaded */ }
    }

    // Fallback: use cached username from storage
    const stored = await chrome.storage.local.get('activeRedditUsername');
    if (stored?.activeRedditUsername) {
      return stored.activeRedditUsername;
    }

    // Last fallback: check auth data
    const auth = await getAuth();
    return auth?.avatarUsername || '';
  } catch {
    return '';
  }
}
