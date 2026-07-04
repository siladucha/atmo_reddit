/**
 * RAMP Extension — Service Worker (Background)
 *
 * Responsibilities:
 * - Poll backend for tasks (GET /api/extension/tasks)
 * - HMAC verify incoming tasks
 * - Manage local task queue (chrome.storage.local)
 * - Timer: hold tasks until scheduled_at
 * - Heartbeat: POST /heartbeat every 60s
 * - Kill switch: pause_all command handling
 * - Account monitor: detect username changes
 * - Network retry with exponential backoff
 */

import {
  startPolling,
  stopPolling,
  pollOnce,
  setTaskCallback,
  ALARM_NAME,
} from './poller.js';

// HMAC verification planned for Phase 2 (not enforced in prepare_only mode)
// import { verifyTaskHmac } from './hmac.js';

import { enqueueTask, getQueue, dequeueTask, saveQueue } from './queue.js';

import { getAuth } from '../shared/auth.js';

import {
  startTimer,
  stopTimer,
  checkAndDispatch,
  TIMER_ALARM_NAME,
} from './timer.js';

import {
  startScheduler,
  schedulerTick,
  SCHEDULER_ALARM_NAME,
} from './scheduler.js';

import {
  startHeartbeat,
  stopHeartbeat,
  sendHeartbeat,
  HEARTBEAT_ALARM_NAME,
} from './heartbeat.js';

import { executeTaskStateMachine, flushEvents, EXECUTION_MODES, STATES } from './state-machine.js';

// --------------------------------------------------------------------------
// Task callback — receives tasks from poller
// --------------------------------------------------------------------------

function onTasksReceived(tasks) {
  console.log(`[RAMP] Received ${tasks.length} task(s) from backend`);
  for (const task of tasks) {
    if (task && task.task_id) {
      enqueueTask(task);
    }
  }
  // Update badge to show pending task count
  updateBadge();
}

/**
 * Update extension badge with count of pending (unapproved) tasks.
 * Tasks with status 'approved', 'executing', 'completed', or 'failed' are not counted.
 */
async function updateBadge() {
  try {
    const queue = await getQueue();
    const pendingCount = queue.filter(t => !t.status || t.status === 'pending').length;
    chrome.action.setBadgeText({ text: pendingCount > 0 ? String(pendingCount) : '' });
    chrome.action.setBadgeBackgroundColor({ color: '#7c3aed' }); // purple
  } catch {}
}

/**
 * Auto-dispatch is DISABLED. Extension operates in prepare_only mode.
 * Tasks are only executed when user clicks Prepare in popup.
 */

setTaskCallback(onTasksReceived);

// --------------------------------------------------------------------------
// Polling status tracking — used by GET_STATUS handler
// --------------------------------------------------------------------------

let _isPollingActive = true;
let _lastPollSuccess = false;

// Wrap pollOnce to track success/failure for status reporting
const _originalPollOnce = pollOnce;
async function trackedPollOnce() {
  try {
    await _originalPollOnce();
    _lastPollSuccess = true;
  } catch (err) {
    _lastPollSuccess = false;
  }
}

// --------------------------------------------------------------------------
// Message listener — handles popup.js communication
// --------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !message.type) return false;

  switch (message.type) {
    case 'GET_QUEUE':
      handleGetQueue(sendResponse);
      return true; // async response

    case 'GET_STATUS':
      handleGetStatus(sendResponse);
      return true; // async response

    case 'PREPARE_TASK':
      handlePrepareTask(message.taskId, sendResponse);
      return true; // async response

    case 'APPROVE_TASK':
      // Legacy: redirects to prepare mode (safe default)
      handlePrepareTask(message.taskId, sendResponse);
      return true; // async response

    case 'REJECT_TASK':
      handleRejectTask(message.taskId, sendResponse);
      return true; // async response

    case 'OPEN_TASK_TAB':
      handleOpenTaskTab(message.taskId, sendResponse);
      return true; // async response

    case 'CANCEL_PREPARED_TASK':
      handleCancelPreparedTask(message.taskId, sendResponse);
      return true; // async response

    case 'GET_EXECUTION_STATE':
      handleGetExecutionState(sendResponse);
      return true; // async response

    case 'TOGGLE_PAUSE':
      handleTogglePause(sendResponse);
      return true;

    case 'UPDATE_TASK_TEXT':
      handleUpdateTaskText(message.taskId, message.newText, sendResponse);
      return true;

    case 'APPROVE_ALL': {
      handleApproveAll(sendResponse);
      return true; // async
    }

    case 'APPROVE_TASK_V2': {
      handleApproveTaskV2(message.taskId, sendResponse);
      return true; // async
    }

    case 'SKIP_TASK': {
      handleSkipTask(message.taskId, sendResponse);
      return true; // async
    }

    case 'RETRY_TASK': {
      handleRetryTask(message.taskId, sendResponse);
      return true; // async
    }

    default:
      return false;
  }
});

/**
 * Handle GET_QUEUE: return the current task queue.
 */
async function handleGetQueue(sendResponse) {
  try {
    const tasks = await getQueue();
    sendResponse({ tasks });
  } catch (err) {
    console.error('[RAMP] GET_QUEUE error:', err);
    sendResponse({ tasks: [] });
  }
}

/**
 * Handle GET_STATUS: return connection status based on polling state.
 */
async function handleGetStatus(sendResponse) {
  try {
    const auth = await getAuth();
    const hasAuth = auth && auth.token && auth.rampUrl;

    let status = 'disconnected';
    let statusText = 'Disconnected';

    if (!hasAuth) {
      status = 'disconnected';
      statusText = 'Not authenticated';
    } else if (_isPollingActive && _lastPollSuccess) {
      status = 'connected';
      statusText = 'Connected';
    } else if (_isPollingActive && !_lastPollSuccess) {
      status = 'degraded';
      statusText = 'Connection issues';
    } else {
      status = 'disconnected';
      statusText = 'Polling stopped';
    }

    sendResponse({ status, statusText });
  } catch (err) {
    console.error('[RAMP] GET_STATUS error:', err);
    sendResponse({ status: 'disconnected', statusText: 'Error' });
  }
}

/**
 * Handle PREPARE_TASK: dequeue task and run prepare-only execution.
 * Navigates to thread, inserts text, verifies — but does NOT submit.
 * Stores proof in executionState for popup display.
 */
async function handlePrepareTask(taskId, sendResponse) {
  try {
    const task = await dequeueTask(taskId);
    if (!task) {
      console.warn(`[RAMP] Prepare: task ${taskId} not found in queue`);
      sendResponse({ ok: false, error: 'Task not found' });
      return;
    }

    console.log(`[RAMP] Task prepare started: ${taskId}`, task.task_type);
    sendResponse({ ok: true, status: 'preparing' });

    // Run prepare pipeline in background
    dispatchPrepareTask(task);
  } catch (err) {
    console.error('[RAMP] PREPARE_TASK error:', err);
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Dispatch a task through prepare_only execution pipeline.
 * Does NOT submit. Stores result in chrome.storage for popup to read.
 */
async function dispatchPrepareTask(task) {
  // Update execution state: "preparing..."
  await setExecutionState({
    task_id: task.task_id,
    status: 'preparing',
    task,
    proof: null,
    error: null,
    started_at: new Date().toISOString(),
  });

  try {
    // Find or create a Reddit tab
    let targetTab = await findOrCreateRedditTab(task);
    if (!targetTab) {
      await setExecutionState({
        task_id: task.task_id,
        status: 'failed',
        task,
        proof: null,
        error: 'No Reddit tab available and no thread_url',
        finished_at: new Date().toISOString(),
      });
      reportToBackend(task, 'task_failed', { error_code: 'no_reddit_tab' });
      return;
    }

    // Execute state machine in prepare_only mode
    const result = await executeTaskStateMachine(task, targetTab.id, EXECUTION_MODES.PREPARE_ONLY);

    // Flush events immediately
    await flushEvents();

    // Store result for popup
    await setExecutionState({
      task_id: task.task_id,
      status: result.state === STATES.READY_TO_SUBMIT ? 'prepared' : 'failed',
      task,
      proof: result.proof || null,
      error: result.state === STATES.FAILED ? (result.result?.error_details || result.result?.error_code) : null,
      tab_id: targetTab.id,
      finished_at: new Date().toISOString(),
    });

    // Report to backend
    const reportBody = {
      task_id: task.task_id,
      idempotency_key: task.idempotency_key,
      result_type: result.state === STATES.READY_TO_SUBMIT ? 'task_prepared' : 'task_failed',
      status: result.state === STATES.READY_TO_SUBMIT ? 'prepared' : 'failed',
      error_code: result.result?.error_code || null,
      error_details: result.result?.error_details || null,
      execution_metadata: { proof: result.proof, execution_mode: 'prepare_only' },
    };

    await reportToBackend(task, reportBody.result_type, reportBody);

    console.log(`[RAMP] Task ${task.task_id} prepare finished: ${result.state}`);
  } catch (err) {
    console.error(`[RAMP] Task prepare error ${task.task_id}:`, err.message || err);
    await setExecutionState({
      task_id: task.task_id,
      status: 'failed',
      task,
      proof: null,
      error: err.message || 'Unexpected error',
      finished_at: new Date().toISOString(),
    });
  }
}

/**
 * Handle OPEN_TASK_TAB: focus the Reddit tab where the task was prepared.
 */
async function handleOpenTaskTab(taskId, sendResponse) {
  try {
    const state = await getExecutionState();
    if (state?.task_id === taskId && state?.tab_id) {
      await chrome.tabs.update(state.tab_id, { active: true });
      await chrome.windows.update((await chrome.tabs.get(state.tab_id)).windowId, { focused: true });
      sendResponse({ ok: true });
    } else {
      sendResponse({ ok: false, error: 'No tab found for this task' });
    }
  } catch (err) {
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Handle CANCEL_PREPARED_TASK: clear execution state, report cancellation.
 */
async function handleCancelPreparedTask(taskId, sendResponse) {
  try {
    const state = await getExecutionState();
    if (state?.task_id === taskId) {
      await clearExecutionState();
      // Report cancellation to backend
      const task = state.task;
      if (task) {
        await reportToBackend(task, 'task_failed', {
          task_id: task.task_id,
          idempotency_key: task.idempotency_key,
          result_type: 'task_failed',
          error_code: 'cancelled_by_executor',
          error_details: 'Executor cancelled prepared task',
        });
      }
    }
    sendResponse({ ok: true });
  } catch (err) {
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Handle GET_EXECUTION_STATE: return current execution state for popup.
 */
async function handleGetExecutionState(sendResponse) {
  try {
    const state = await getExecutionState();
    sendResponse({ state: state || null });
  } catch (err) {
    sendResponse({ state: null });
  }
}

// ─── Execution State Storage ─────────────────────────────────────────────────

const EXEC_STATE_KEY = 'ramp_execution_state';

async function setExecutionState(state) {
  await chrome.storage.local.set({ [EXEC_STATE_KEY]: state });
}

async function getExecutionState() {
  const result = await chrome.storage.local.get(EXEC_STATE_KEY);
  return result[EXEC_STATE_KEY] || null;
}

async function clearExecutionState() {
  await chrome.storage.local.remove(EXEC_STATE_KEY);
}

// ─── Tab Management ──────────────────────────────────────────────────────────

async function findOrCreateRedditTab(task) {
  // Try active Reddit tab first
  const activeTabs = await chrome.tabs.query({
    active: true,
    url: ['*://*.reddit.com/*'],
  });
  if (activeTabs.length > 0) return activeTabs[0];

  // Try any Reddit tab
  const allRedditTabs = await chrome.tabs.query({ url: ['*://*.reddit.com/*'] });
  if (allRedditTabs.length > 0) {
    return allRedditTabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
  }

  // Create new tab with thread_url
  if (task.thread_url) {
    const newTab = await chrome.tabs.create({ url: task.thread_url, active: true });
    await new Promise(resolve => {
      const listener = (id, info) => {
        if (id === newTab.id && info.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener);
          setTimeout(resolve, 2000);
        }
      };
      chrome.tabs.onUpdated.addListener(listener);
      setTimeout(() => { chrome.tabs.onUpdated.removeListener(listener); resolve(); }, 30000);
    });
    return newTab;
  }

  return null;
}

// ─── Backend Reporting ────────────────────────────────────────────────────────

async function reportToBackend(task, resultType, body) {
  try {
    const auth = await getAuth();
    if (!auth?.token || !auth?.rampUrl) return;

    const reportBody = {
      task_id: task.task_id,
      idempotency_key: task.idempotency_key,
      result_type: resultType,
      ...body,
    };

    await fetch(`${auth.rampUrl}/api/extension/report`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${auth.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(reportBody),
    });
  } catch (err) {
    console.warn('[RAMP] Report failed:', err);
  }
}

/**
 * Handle REJECT_TASK: dequeue task and report rejection to backend.
 */
async function handleRejectTask(taskId, sendResponse) {
  try {
    const task = await dequeueTask(taskId);
    if (task) {
      console.log(`[RAMP] Task rejected: ${taskId}`, task.task_type);
      await reportToBackend(task, 'task_failed', {
        task_id: task.task_id,
        idempotency_key: task.idempotency_key,
        result_type: 'task_failed',
        error_code: 'rejected_by_executor',
        error_details: 'Task rejected by executor via popup UI',
      });
    } else {
      console.warn(`[RAMP] Reject: task ${taskId} not found in queue`);
    }
    sendResponse({ ok: true });
  } catch (err) {
    console.error('[RAMP] REJECT_TASK error:', err);
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Handle TOGGLE_PAUSE: pause/resume content task execution.
 * Paused = diagnostics still run, content tasks held.
 */
async function handleTogglePause(sendResponse) {
  try {
    const { rampPaused } = await chrome.storage.local.get('rampPaused');
    const newState = !rampPaused;
    await chrome.storage.local.set({ rampPaused: newState });
    console.log(`[RAMP] Pause toggled: ${newState}`);
    sendResponse({ paused: newState });
  } catch (err) {
    console.error('[RAMP] TOGGLE_PAUSE error:', err);
    sendResponse({ paused: false });
  }
}

/**
 * Handle UPDATE_TASK_TEXT: update a task's comment_text in the local queue.
 * Called after a successful PATCH to the backend from the edit-task module.
 */
async function handleUpdateTaskText(taskId, newText, sendResponse) {
  try {
    const queue = await getQueue();
    const taskIndex = queue.findIndex(t => t.task_id === taskId);
    if (taskIndex !== -1) {
      queue[taskIndex].comment_text = newText;
      await chrome.storage.local.set({ ramp_task_queue: queue });
    }
    sendResponse({ ok: true });
  } catch (err) {
    console.error('[RAMP] UPDATE_TASK_TEXT error:', err);
    sendResponse({ ok: false, error: err.message });
  }
}

// ─── Batch Approval Handlers (v2) ───────────────────────────────────────────

/**
 * Handle APPROVE_ALL: mark all pending tasks in the queue as 'approved'.
 * Reports batch approval to the backend and clears the badge.
 */
async function handleApproveAll(sendResponse) {
  try {
    const queue = await getQueue();
    const pendingTasks = queue.filter(t => !t.status || t.status === 'pending');

    if (pendingTasks.length === 0) {
      sendResponse({ ok: true, approved_count: 0 });
      return;
    }

    // Mark all pending as approved locally
    for (const task of pendingTasks) {
      task.status = 'approved';
      task.approved_at = new Date().toISOString();
    }

    // Save updated queue (includes non-pending tasks too)
    await saveQueue(queue);

    // Report batch approval to backend
    await reportBatchApproval(pendingTasks.map(t => t.task_id));

    // Clear badge (no more pending tasks)
    chrome.action.setBadgeText({ text: '' });

    console.log(`[RAMP] APPROVE_ALL: ${pendingTasks.length} tasks approved`);
    sendResponse({ ok: true, approved_count: pendingTasks.length });
  } catch (err) {
    console.error('[RAMP] APPROVE_ALL error:', err);
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Handle APPROVE_TASK_V2: mark a single task as 'approved' in the local queue.
 * Reports individual approval to the backend.
 */
async function handleApproveTaskV2(taskId, sendResponse) {
  try {
    const queue = await getQueue();
    const task = queue.find(t => t.task_id === taskId);
    if (!task) {
      sendResponse({ ok: false, error: 'Task not found' });
      return;
    }

    task.status = 'approved';
    task.approved_at = new Date().toISOString();
    await saveQueue(queue);

    // Report individual approval to backend
    await reportTaskApproval(taskId);

    // Update badge (only pending tasks count)
    await updateBadge();

    console.log(`[RAMP] APPROVE_TASK_V2: ${taskId} approved`);
    sendResponse({ ok: true });
  } catch (err) {
    console.error('[RAMP] APPROVE_TASK_V2 error:', err);
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Handle SKIP_TASK: remove a task from the queue and report skip to backend.
 * Different from REJECT_TASK in that it uses the v2 status reporting pattern.
 */
async function handleSkipTask(taskId, sendResponse) {
  try {
    const queue = await getQueue();
    const taskIndex = queue.findIndex(t => t.task_id === taskId);
    if (taskIndex === -1) {
      sendResponse({ ok: false, error: 'Task not found' });
      return;
    }

    // Remove from queue
    const [task] = queue.splice(taskIndex, 1);
    await saveQueue(queue);

    // Report skip to backend (same as reject with specific error code)
    await reportToBackend(task, 'task_failed', {
      task_id: task.task_id,
      idempotency_key: task.idempotency_key,
      result_type: 'task_failed',
      error_code: 'skipped_by_executor',
      error_details: 'Task skipped via popup UI',
    });

    await updateBadge();

    console.log(`[RAMP] SKIP_TASK: ${taskId} skipped`);
    sendResponse({ ok: true });
  } catch (err) {
    console.error('[RAMP] SKIP_TASK error:', err);
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Handle RETRY_TASK: move a failed task back to 'approved' status.
 * Clears error fields (retry_after, error_code, error_details, failed_at)
 * and saves the queue. Reports retry to backend.
 */
async function handleRetryTask(taskId, sendResponse) {
  try {
    const queue = await getQueue();
    const task = queue.find(t => t.task_id === taskId);
    if (!task) {
      sendResponse({ ok: false, error: 'Task not found' });
      return;
    }

    // Move task back to approved status
    task.status = 'approved';
    task.approved_at = new Date().toISOString();

    // Clear error-related fields
    delete task.retry_after;
    delete task.error_code;
    delete task.error_details;
    delete task.failed_at;

    await saveQueue(queue);

    // Report retry to backend
    await reportTaskRetry(taskId);

    await updateBadge();

    console.log(`[RAMP] RETRY_TASK: ${taskId} moved back to approved`);
    sendResponse({ ok: true });
  } catch (err) {
    console.error('[RAMP] RETRY_TASK error:', err);
    sendResponse({ ok: false, error: err.message });
  }
}

/**
 * Report task retry to backend — notifies that executor wants to retry a failed task.
 * @param {string} taskId — The task_id being retried
 */
async function reportTaskRetry(taskId) {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  try {
    await fetch(`${auth.rampUrl}/api/extension/tasks/${taskId}/retry`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${auth.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ status: 'approved' }),
    });
  } catch (err) {
    console.warn(`[RAMP] Failed to report retry for ${taskId}:`, err.message);
  }
}

// ─── Backend Approval Reporting ──────────────────────────────────────────────

/**
 * Report batch approval to backend — notifies for each approved task.
 * Uses the existing tasks status endpoint if available, falls back to report endpoint.
 * @param {string[]} taskIds — Array of task_id values that were approved
 */
async function reportBatchApproval(taskIds) {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  for (const taskId of taskIds) {
    try {
      await fetch(`${auth.rampUrl}/api/extension/tasks/${taskId}/approve`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${auth.token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ status: 'approved' }),
      });
    } catch (err) {
      console.warn(`[RAMP] Failed to report approval for ${taskId}:`, err.message);
    }
  }
}

/**
 * Report individual task approval to backend.
 * @param {string} taskId — The task_id approved
 */
async function reportTaskApproval(taskId) {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  try {
    await fetch(`${auth.rampUrl}/api/extension/tasks/${taskId}/approve`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${auth.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ status: 'approved' }),
    });
  } catch (err) {
    console.warn(`[RAMP] Failed to report approval for ${taskId}:`, err.message);
  }
}

// reportRejection removed — using reportToBackend() utility instead

// --------------------------------------------------------------------------
// Alarm listener — routes alarm events to the appropriate handler
// --------------------------------------------------------------------------

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    pollOnce();
  }
  if (alarm.name === HEARTBEAT_ALARM_NAME) {
    sendHeartbeat();
  }
  if (alarm.name === TIMER_ALARM_NAME) {
    checkAndDispatch();
  }
  if (alarm.name === SCHEDULER_ALARM_NAME) {
    schedulerTick();
  }
});

// --------------------------------------------------------------------------
// Service Worker activation — start polling with default 30s interval
// --------------------------------------------------------------------------

const DEFAULT_POLL_INTERVAL_SECONDS = 30;

// Start polling when the service worker activates
startPolling(DEFAULT_POLL_INTERVAL_SECONDS);

// Start heartbeat (every 60s)
startHeartbeat();

// Start task dispatch timer (every 15s) — legacy, kept for backward compat
startTimer();

// Start scheduler (every ~15s) — v2 automated execution
startScheduler();

// Also perform an immediate poll on fresh activation
pollOnce();

// Send an immediate heartbeat on fresh activation
sendHeartbeat();

console.log('[RAMP] Service worker loaded and polling started');
