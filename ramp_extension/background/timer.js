/**
 * RAMP Extension — Timer / Dispatch Module
 *
 * Holds tasks in the local queue until their `scheduled_at` time arrives,
 * then dispatches them to the content script for execution.
 *
 * Dispatch rules:
 *   - Diagnostic tasks (priority === "diagnostic") are auto-approved — dispatch immediately when due
 *   - Content tasks require executor approval (handled via popup approve flow)
 *   - Only ONE task dispatched per tick (sequential execution per spec)
 *
 * Exports:
 *   TIMER_ALARM_NAME          — alarm name constant
 *   startTimer()              — start the 15s check alarm
 *   stopTimer()               — clear the alarm
 *   checkAndDispatch()        — main tick: check due tasks, dispatch one
 */

import { getQueue, dequeueTask } from './queue.js';

/** Alarm name used for the task dispatch timer. */
export const TIMER_ALARM_NAME = 'ramp-task-timer';

/** Timer period in minutes (chrome.alarms minimum is ~0.5 for unpacked, we use 0.25 = 15s). */
const TIMER_PERIOD_MINUTES = 0.25;

/**
 * Start the dispatch timer alarm.
 * Fires every 15 seconds to check for due tasks.
 */
export function startTimer() {
  chrome.alarms.create(TIMER_ALARM_NAME, {
    delayInMinutes: TIMER_PERIOD_MINUTES,
    periodInMinutes: TIMER_PERIOD_MINUTES,
  });
  console.log('[RAMP] Timer started — checking tasks every 15s');
}

/**
 * Stop the dispatch timer alarm.
 */
export function stopTimer() {
  chrome.alarms.clear(TIMER_ALARM_NAME);
  console.log('[RAMP] Timer stopped');
}

/**
 * Determine if a task is due for dispatch.
 * A task is due if:
 *   - scheduled_at is null/empty/undefined → immediate
 *   - scheduled_at <= now
 *
 * @param {object} task
 * @returns {boolean}
 */
function isTaskDue(task) {
  if (!task.scheduled_at) {
    return true;
  }

  const scheduledTime = new Date(task.scheduled_at).getTime();
  if (isNaN(scheduledTime)) {
    // Invalid date — treat as immediate
    return true;
  }

  return scheduledTime <= Date.now();
}

/**
 * Determine if a task is ready to be dispatched.
 * - Diagnostic tasks are auto-approved (always ready when due)
 * - Content tasks from EPG (with HMAC signature) are pre-approved — auto-execute
 * - All extension tasks are pre-approved by backend (backend only sends approved content)
 *
 * @param {object} task
 * @returns {boolean}
 */
function isTaskReady(task) {
  // All tasks from backend are pre-approved (EPG approved slots only create tasks)
  // Extension is execution-only — if backend sent it, it's approved.
  return true;
}

/**
 * Dispatch a task to the content script on the active Reddit tab.
 * Sends message: { type: 'EXECUTE_TASK', task: taskObject }
 *
 * @param {object} task — The task to dispatch
 * @returns {Promise<boolean>} — true if dispatched successfully
 */
async function dispatchToContentScript(task) {
  try {
    // Find the active Reddit tab
    const tabs = await chrome.tabs.query({
      active: true,
      url: ['*://*.reddit.com/*'],
    });

    if (tabs.length === 0) {
      // Try any Reddit tab (not necessarily active)
      const allRedditTabs = await chrome.tabs.query({
        url: ['*://*.reddit.com/*'],
      });

      if (allRedditTabs.length === 0) {
        console.warn('[RAMP] No Reddit tab found — cannot dispatch task', task.task_id);
        return false;
      }

      // Use the most recently accessed Reddit tab
      const targetTab = allRedditTabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
      await chrome.tabs.sendMessage(targetTab.id, {
        type: 'EXECUTE_TASK',
        task,
      });
      console.log(`[RAMP] Task ${task.task_id} dispatched to Reddit tab (id: ${targetTab.id})`);
      return true;
    }

    // Dispatch to the active Reddit tab
    const targetTab = tabs[0];
    await chrome.tabs.sendMessage(targetTab.id, {
      type: 'EXECUTE_TASK',
      task,
    });
    console.log(`[RAMP] Task ${task.task_id} dispatched to active Reddit tab (id: ${targetTab.id})`);
    return true;
  } catch (err) {
    console.error(`[RAMP] Failed to dispatch task ${task.task_id}:`, err.message || err);
    return false;
  }
}

/**
 * Main timer tick — check queue for due tasks and dispatch one.
 *
 * Process:
 *   1. Get the queue (already priority-sorted: diagnostics first)
 *   2. Find the first task that is both due AND ready
 *   3. Dequeue it and dispatch to content script
 *   4. Process only ONE task per tick (sequential execution)
 */
export async function checkAndDispatch() {
  // Disabled — auto-dispatch handled by onTasksReceived -> autoDispatchDueTasks in service-worker.js
  // Timer only needed for future scheduled tasks (Phase 2)
  return;
}
