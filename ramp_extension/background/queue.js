/**
 * RAMP Extension — Local Task Queue
 *
 * Manages the local task queue in chrome.storage.local.
 * Tasks are priority-ordered: diagnostic tasks first, then by scheduled_at ascending.
 * Max queue size: 20 items (backpressure mechanism — rejects new tasks on overflow).
 *
 * Exports:
 *   MAX_QUEUE_SIZE            — constant (20)
 *   STORAGE_KEY               — storage key identifier
 *   getQueue()                — returns sorted task queue
 *   enqueueTask(task)         — adds task (returns {accepted, reason?})
 *   dequeueTask(taskId)       — removes task by task_id, returns removed task or null
 *   clearQueue()              — removes all tasks
 *   getQueueSize()            — returns count of tasks in queue
 */

/** Maximum number of tasks allowed in the local queue. */
export const MAX_QUEUE_SIZE = 20;

/** Chrome storage key for the task queue. */
export const STORAGE_KEY = 'ramp_task_queue';

/**
 * Sort tasks by priority: diagnostic first, then by scheduled_at ascending.
 * @param {Array} tasks
 * @returns {Array} Sorted copy
 */
function sortByPriority(tasks) {
  return [...tasks].sort((a, b) => {
    // Diagnostic tasks come before content tasks
    const aPriority = a.priority === 'diagnostic' ? 0 : 1;
    const bPriority = b.priority === 'diagnostic' ? 0 : 1;

    if (aPriority !== bPriority) {
      return aPriority - bPriority;
    }

    // Within same priority tier, sort by scheduled_at ascending
    const aTime = a.scheduled_at ? new Date(a.scheduled_at).getTime() : 0;
    const bTime = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
    return aTime - bTime;
  });
}

/**
 * Get the current task queue from chrome.storage.local, sorted by priority.
 * @returns {Promise<Array>} Sorted task queue
 */
export async function getQueue() {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  const queue = result[STORAGE_KEY] || [];
  return sortByPriority(queue);
}

/**
 * Add a task to the queue.
 *
 * Rejects if:
 *   - Queue already has MAX_QUEUE_SIZE items → {accepted: false, reason: "overflow"}
 *   - Task with same task_id already exists → {accepted: false, reason: "duplicate"}
 *
 * On success, inserts maintaining priority order.
 *
 * @param {object} task — Task object (must have at least task_id, task_type, priority, scheduled_at)
 * @returns {Promise<{accepted: boolean, reason?: string}>}
 */
export async function enqueueTask(task) {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  const queue = result[STORAGE_KEY] || [];

  // Check overflow
  if (queue.length >= MAX_QUEUE_SIZE) {
    return { accepted: false, reason: 'overflow' };
  }

  // Check duplicate
  if (queue.some((t) => t.task_id === task.task_id)) {
    return { accepted: false, reason: 'duplicate' };
  }

  // Add task and re-sort
  queue.push(task);
  const sorted = sortByPriority(queue);

  await chrome.storage.local.set({ [STORAGE_KEY]: sorted });
  return { accepted: true };
}

/**
 * Remove a task from the queue by task_id.
 * @param {string} taskId — The task_id to remove
 * @returns {Promise<object|null>} The removed task, or null if not found
 */
export async function dequeueTask(taskId) {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  const queue = result[STORAGE_KEY] || [];

  const index = queue.findIndex((t) => t.task_id === taskId);
  if (index === -1) {
    return null;
  }

  const [removed] = queue.splice(index, 1);
  await chrome.storage.local.set({ [STORAGE_KEY]: queue });
  return removed;
}

/**
 * Save an entire task queue array to storage (overwrites existing).
 * Used by batch operations (approve all, status updates).
 * @param {Array} tasks — Full task queue to persist
 * @returns {Promise<void>}
 */
export async function saveQueue(tasks) {
  const sorted = sortByPriority(tasks);
  await chrome.storage.local.set({ [STORAGE_KEY]: sorted });
}

/**
 * Remove all tasks from the queue.
 * @returns {Promise<void>}
 */
export async function clearQueue() {
  await chrome.storage.local.set({ [STORAGE_KEY]: [] });
}

/**
 * Get the number of tasks currently in the queue.
 * @returns {Promise<number>}
 */
export async function getQueueSize() {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  const queue = result[STORAGE_KEY] || [];
  return queue.length;
}
