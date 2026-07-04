/**
 * Retry Engine — per-error-type retry strategy for task execution.
 *
 * Retry Strategy Table:
 * | Error Type         | Max Retries | Delay              | After exhaustion          |
 * |--------------------|-------------|--------------------|-----------------------------|
 * | DOM_CHANGED        | 2           | 5000ms             | mark dom_health: broken     |
 * | EDITOR_NOT_FOUND   | 2           | 5000ms             | mark dom_health: broken     |
 * | SUBMIT_FAILED      | 1           | 10000ms            | mark task failed            |
 * | TIMEOUT            | 1           | 5000ms             | mark task failed            |
 * | NETWORK_ERROR      | 3           | exponential backoff | mark task failed            |
 *
 * Storage format in chrome.storage.local:
 * {
 *   "ramp_retry_state": {
 *     "tasks": {
 *       "<task_id>": { attempts: number, lastError: string }
 *     },
 *     "consecutive_failures": {
 *       "DOM_CHANGED": 0,
 *       "EDITOR_NOT_FOUND": 0,
 *       "SUBMIT_FAILED": 0,
 *       "TIMEOUT": 0,
 *       "NETWORK_ERROR": 0
 *     }
 *   }
 * }
 */

export const STORAGE_KEY = 'ramp_retry_state';

/**
 * Retry strategies keyed by error type.
 */
export const RETRY_STRATEGIES = {
  DOM_CHANGED: { maxRetries: 2, delayMs: 5000, markBrokenOnExhaust: true },
  EDITOR_NOT_FOUND: { maxRetries: 2, delayMs: 5000, markBrokenOnExhaust: true },
  SUBMIT_FAILED: { maxRetries: 1, delayMs: 10000, markBrokenOnExhaust: false },
  TIMEOUT: { maxRetries: 1, delayMs: 5000, markBrokenOnExhaust: false },
  NETWORK_ERROR: { maxRetries: 3, delayMs: null, markBrokenOnExhaust: false }, // exponential
};

/**
 * Calculate exponential backoff delay for NETWORK_ERROR.
 * Formula: 2000 * 2^(attempt - 1) → 2000, 4000, 8000ms
 * @param {number} attemptNumber - 1-indexed attempt number
 * @returns {number} delay in milliseconds
 */
export function getExponentialDelay(attemptNumber) {
  return 2000 * Math.pow(2, attemptNumber - 1);
}

/**
 * @typedef {Object} RetryDecision
 * @property {boolean} shouldRetry - Whether to retry the task
 * @property {number} delayMs - How long to wait before retrying
 * @property {boolean} markBroken - Whether to set dom_health to "broken"
 * @property {boolean} markFailed - Whether to mark the task as permanently failed
 */

/**
 * Get the retry decision for a given error type and attempt count.
 * Pure function — no side effects, no storage access.
 *
 * @param {string} errorType - One of: DOM_CHANGED, EDITOR_NOT_FOUND, SUBMIT_FAILED, TIMEOUT, NETWORK_ERROR
 * @param {number} attemptNumber - Current attempt (1-indexed: first failure = attempt 1)
 * @returns {RetryDecision}
 */
export function getRetryDecision(errorType, attemptNumber) {
  const strategy = RETRY_STRATEGIES[errorType];

  if (!strategy) {
    // Unknown error type — do not retry, mark failed
    return { shouldRetry: false, delayMs: 0, markBroken: false, markFailed: true };
  }

  if (attemptNumber <= strategy.maxRetries) {
    // Still have retries left
    const delayMs = errorType === 'NETWORK_ERROR'
      ? getExponentialDelay(attemptNumber)
      : strategy.delayMs;

    return { shouldRetry: true, delayMs, markBroken: false, markFailed: false };
  }

  // Retries exhausted
  return {
    shouldRetry: false,
    delayMs: 0,
    markBroken: strategy.markBrokenOnExhaust,
    markFailed: true,
  };
}

/**
 * Get stored retry state from chrome.storage.local.
 * @returns {Promise<Object>}
 */
async function getRetryState() {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  return result[STORAGE_KEY] || {
    tasks: {},
    consecutive_failures: {
      DOM_CHANGED: 0,
      EDITOR_NOT_FOUND: 0,
      SUBMIT_FAILED: 0,
      TIMEOUT: 0,
      NETWORK_ERROR: 0,
    },
  };
}

/**
 * Persist retry state to chrome.storage.local.
 * @param {Object} state
 */
async function saveRetryState(state) {
  await chrome.storage.local.set({ [STORAGE_KEY]: state });
}

/**
 * Track a failure and get the retry decision.
 * Updates failure counters in chrome.storage.local.
 *
 * @param {string} taskId
 * @param {string} errorType
 * @returns {Promise<RetryDecision>}
 */
export async function recordFailureAndDecide(taskId, errorType) {
  const state = await getRetryState();

  // Initialize task state if not present
  if (!state.tasks[taskId]) {
    state.tasks[taskId] = { attempts: 0, lastError: null };
  }

  // Increment per-task attempt counter
  state.tasks[taskId].attempts += 1;
  state.tasks[taskId].lastError = errorType;

  // Increment global consecutive failure counter for this error type
  if (state.consecutive_failures[errorType] !== undefined) {
    state.consecutive_failures[errorType] += 1;
  }

  await saveRetryState(state);

  // Get decision based on current attempt count for this task
  const decision = getRetryDecision(errorType, state.tasks[taskId].attempts);

  return decision;
}

/**
 * Reset failure counters for a task (called on success).
 * @param {string} taskId
 */
export async function resetRetryState(taskId) {
  const state = await getRetryState();

  delete state.tasks[taskId];

  await saveRetryState(state);
}

/**
 * Get current consecutive failure counts by error type.
 * Used by health monitoring to determine dom_health.
 * @returns {Promise<Object>} Map of errorType → consecutive count
 */
export async function getConsecutiveFailures() {
  const state = await getRetryState();
  return { ...state.consecutive_failures };
}

/**
 * Reset ALL consecutive failure counters (called on successful execution).
 */
export async function resetAllConsecutiveFailures() {
  const state = await getRetryState();

  state.consecutive_failures = {
    DOM_CHANGED: 0,
    EDITOR_NOT_FOUND: 0,
    SUBMIT_FAILED: 0,
    TIMEOUT: 0,
    NETWORK_ERROR: 0,
  };

  await saveRetryState(state);
}
