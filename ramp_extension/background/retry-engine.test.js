/**
 * Tests for the retry engine module.
 *
 * Covers:
 * - Each error type returns correct decisions at each attempt number
 * - Exponential backoff calculation for NETWORK_ERROR
 * - Consecutive failure tracking (increment and reset)
 * - Per-task state management
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  STORAGE_KEY,
  RETRY_STRATEGIES,
  getExponentialDelay,
  getRetryDecision,
  recordFailureAndDecide,
  resetRetryState,
  getConsecutiveFailures,
  resetAllConsecutiveFailures,
} from './retry-engine.js';

// --- chrome.storage.local mock ---
let storage = {};

const chromeStorageMock = {
  local: {
    get: vi.fn(async (key) => {
      if (typeof key === 'string') {
        return { [key]: storage[key] };
      }
      return storage;
    }),
    set: vi.fn(async (items) => {
      Object.assign(storage, items);
    }),
  },
};

globalThis.chrome = { storage: chromeStorageMock };

beforeEach(() => {
  storage = {};
  vi.clearAllMocks();
});

// --- Strategy constants ---

describe('RETRY_STRATEGIES', () => {
  it('DOM_CHANGED has 2 max retries with 5000ms delay', () => {
    expect(RETRY_STRATEGIES.DOM_CHANGED).toEqual({
      maxRetries: 2, delayMs: 5000, markBrokenOnExhaust: true,
    });
  });

  it('EDITOR_NOT_FOUND has 2 max retries with 5000ms delay', () => {
    expect(RETRY_STRATEGIES.EDITOR_NOT_FOUND).toEqual({
      maxRetries: 2, delayMs: 5000, markBrokenOnExhaust: true,
    });
  });

  it('SUBMIT_FAILED has 1 max retry with 10000ms delay', () => {
    expect(RETRY_STRATEGIES.SUBMIT_FAILED).toEqual({
      maxRetries: 1, delayMs: 10000, markBrokenOnExhaust: false,
    });
  });

  it('TIMEOUT has 1 max retry with 5000ms delay', () => {
    expect(RETRY_STRATEGIES.TIMEOUT).toEqual({
      maxRetries: 1, delayMs: 5000, markBrokenOnExhaust: false,
    });
  });

  it('NETWORK_ERROR has 3 max retries with exponential backoff', () => {
    expect(RETRY_STRATEGIES.NETWORK_ERROR).toEqual({
      maxRetries: 3, delayMs: null, markBrokenOnExhaust: false,
    });
  });
});

// --- Exponential delay ---

describe('getExponentialDelay', () => {
  it('attempt 1 → 2000ms', () => {
    expect(getExponentialDelay(1)).toBe(2000);
  });

  it('attempt 2 → 4000ms', () => {
    expect(getExponentialDelay(2)).toBe(4000);
  });

  it('attempt 3 → 8000ms', () => {
    expect(getExponentialDelay(3)).toBe(8000);
  });
});

// --- getRetryDecision (pure function) ---

describe('getRetryDecision', () => {
  describe('DOM_CHANGED', () => {
    it('attempt 1 → shouldRetry true, 5000ms delay (retry 1 of 2)', () => {
      const d = getRetryDecision('DOM_CHANGED', 1);
      expect(d).toEqual({ shouldRetry: true, delayMs: 5000, markBroken: false, markFailed: false });
    });

    it('attempt 2 → shouldRetry true, 5000ms delay (retry 2 of 2)', () => {
      const d = getRetryDecision('DOM_CHANGED', 2);
      expect(d).toEqual({ shouldRetry: true, delayMs: 5000, markBroken: false, markFailed: false });
    });

    it('attempt 3 (exhausted) → shouldRetry false, markBroken true', () => {
      const d = getRetryDecision('DOM_CHANGED', 3);
      expect(d).toEqual({ shouldRetry: false, delayMs: 0, markBroken: true, markFailed: true });
    });
  });

  describe('EDITOR_NOT_FOUND', () => {
    it('attempt 1 → shouldRetry true, 5000ms delay (retry 1 of 2)', () => {
      const d = getRetryDecision('EDITOR_NOT_FOUND', 1);
      expect(d).toEqual({ shouldRetry: true, delayMs: 5000, markBroken: false, markFailed: false });
    });

    it('attempt 2 → shouldRetry true, 5000ms delay (retry 2 of 2)', () => {
      const d = getRetryDecision('EDITOR_NOT_FOUND', 2);
      expect(d).toEqual({ shouldRetry: true, delayMs: 5000, markBroken: false, markFailed: false });
    });

    it('attempt 3 (exhausted) → shouldRetry false, markBroken true', () => {
      const d = getRetryDecision('EDITOR_NOT_FOUND', 3);
      expect(d).toEqual({ shouldRetry: false, delayMs: 0, markBroken: true, markFailed: true });
    });
  });

  describe('SUBMIT_FAILED', () => {
    it('attempt 1 → shouldRetry true, 10000ms delay (retry 1 of 1)', () => {
      const d = getRetryDecision('SUBMIT_FAILED', 1);
      expect(d).toEqual({ shouldRetry: true, delayMs: 10000, markBroken: false, markFailed: false });
    });

    it('attempt 2 (exhausted) → shouldRetry false, markFailed true', () => {
      const d = getRetryDecision('SUBMIT_FAILED', 2);
      expect(d).toEqual({ shouldRetry: false, delayMs: 0, markBroken: false, markFailed: true });
    });
  });

  describe('TIMEOUT', () => {
    it('attempt 1 → shouldRetry true, 5000ms delay (retry 1 of 1)', () => {
      const d = getRetryDecision('TIMEOUT', 1);
      expect(d).toEqual({ shouldRetry: true, delayMs: 5000, markBroken: false, markFailed: false });
    });

    it('attempt 2 (exhausted) → shouldRetry false, markFailed true', () => {
      const d = getRetryDecision('TIMEOUT', 2);
      expect(d).toEqual({ shouldRetry: false, delayMs: 0, markBroken: false, markFailed: true });
    });
  });

  describe('NETWORK_ERROR', () => {
    it('attempt 1 → shouldRetry true, 2000ms delay', () => {
      const d = getRetryDecision('NETWORK_ERROR', 1);
      expect(d).toEqual({ shouldRetry: true, delayMs: 2000, markBroken: false, markFailed: false });
    });

    it('attempt 2 → shouldRetry true, 4000ms delay', () => {
      const d = getRetryDecision('NETWORK_ERROR', 2);
      expect(d).toEqual({ shouldRetry: true, delayMs: 4000, markBroken: false, markFailed: false });
    });

    it('attempt 3 → shouldRetry true, 8000ms delay (retry 3 of 3)', () => {
      const d = getRetryDecision('NETWORK_ERROR', 3);
      expect(d).toEqual({ shouldRetry: true, delayMs: 8000, markBroken: false, markFailed: false });
    });

    it('attempt 4 (exhausted) → shouldRetry false, markFailed true', () => {
      const d = getRetryDecision('NETWORK_ERROR', 4);
      expect(d).toEqual({ shouldRetry: false, delayMs: 0, markBroken: false, markFailed: true });
    });
  });

  describe('unknown error type', () => {
    it('returns markFailed true, no retry', () => {
      const d = getRetryDecision('SOME_RANDOM_ERROR', 1);
      expect(d).toEqual({ shouldRetry: false, delayMs: 0, markBroken: false, markFailed: true });
    });
  });
});

// --- recordFailureAndDecide (stateful) ---

describe('recordFailureAndDecide', () => {
  it('first failure for a task increments attempts to 1', async () => {
    const decision = await recordFailureAndDecide('task-1', 'DOM_CHANGED');

    expect(decision.shouldRetry).toBe(true);
    expect(decision.delayMs).toBe(5000);

    const state = storage[STORAGE_KEY];
    expect(state.tasks['task-1']).toEqual({ attempts: 1, lastError: 'DOM_CHANGED' });
  });

  it('second failure for a task increments attempts to 2', async () => {
    await recordFailureAndDecide('task-1', 'DOM_CHANGED');
    const decision = await recordFailureAndDecide('task-1', 'DOM_CHANGED');

    // 2 retries allowed, so attempt 2 still retries
    expect(decision.shouldRetry).toBe(true);
    expect(decision.delayMs).toBe(5000);

    const state = storage[STORAGE_KEY];
    expect(state.tasks['task-1'].attempts).toBe(2);
  });

  it('increments global consecutive failure counter', async () => {
    await recordFailureAndDecide('task-1', 'DOM_CHANGED');
    await recordFailureAndDecide('task-2', 'DOM_CHANGED');

    const state = storage[STORAGE_KEY];
    expect(state.consecutive_failures.DOM_CHANGED).toBe(2);
  });

  it('tracks multiple error types independently', async () => {
    await recordFailureAndDecide('task-1', 'DOM_CHANGED');
    await recordFailureAndDecide('task-2', 'NETWORK_ERROR');
    await recordFailureAndDecide('task-3', 'NETWORK_ERROR');

    const state = storage[STORAGE_KEY];
    expect(state.consecutive_failures.DOM_CHANGED).toBe(1);
    expect(state.consecutive_failures.NETWORK_ERROR).toBe(2);
  });

  it('NETWORK_ERROR attempt 1 gives 2000ms delay', async () => {
    const decision = await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    expect(decision.shouldRetry).toBe(true);
    expect(decision.delayMs).toBe(2000);
  });

  it('NETWORK_ERROR attempt 2 gives 4000ms delay', async () => {
    await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    const decision = await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    expect(decision.shouldRetry).toBe(true);
    expect(decision.delayMs).toBe(4000);
  });

  it('NETWORK_ERROR attempt 3 gives 8000ms delay', async () => {
    await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    const decision = await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    expect(decision.shouldRetry).toBe(true);
    expect(decision.delayMs).toBe(8000);
  });

  it('NETWORK_ERROR attempt 4 exhausts retries', async () => {
    await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    const decision = await recordFailureAndDecide('task-net', 'NETWORK_ERROR');
    expect(decision.shouldRetry).toBe(false);
    expect(decision.markFailed).toBe(true);
  });

  it('SUBMIT_FAILED retries once then exhausts', async () => {
    const decision1 = await recordFailureAndDecide('task-submit', 'SUBMIT_FAILED');
    expect(decision1.shouldRetry).toBe(true);
    expect(decision1.delayMs).toBe(10000);

    const decision2 = await recordFailureAndDecide('task-submit', 'SUBMIT_FAILED');
    expect(decision2.shouldRetry).toBe(false);
    expect(decision2.markFailed).toBe(true);
  });
});

// --- resetRetryState ---

describe('resetRetryState', () => {
  it('removes task from retry state', async () => {
    await recordFailureAndDecide('task-1', 'DOM_CHANGED');
    await recordFailureAndDecide('task-2', 'TIMEOUT');

    await resetRetryState('task-1');

    const state = storage[STORAGE_KEY];
    expect(state.tasks['task-1']).toBeUndefined();
    expect(state.tasks['task-2']).toBeDefined();
  });

  it('does not crash on non-existent task', async () => {
    await resetRetryState('non-existent');
    // Should not throw
  });
});

// --- getConsecutiveFailures ---

describe('getConsecutiveFailures', () => {
  it('returns all zeros on fresh state', async () => {
    const failures = await getConsecutiveFailures();
    expect(failures).toEqual({
      DOM_CHANGED: 0,
      EDITOR_NOT_FOUND: 0,
      SUBMIT_FAILED: 0,
      TIMEOUT: 0,
      NETWORK_ERROR: 0,
    });
  });

  it('returns incremented counts after failures', async () => {
    await recordFailureAndDecide('t1', 'DOM_CHANGED');
    await recordFailureAndDecide('t2', 'DOM_CHANGED');
    await recordFailureAndDecide('t3', 'NETWORK_ERROR');

    const failures = await getConsecutiveFailures();
    expect(failures.DOM_CHANGED).toBe(2);
    expect(failures.NETWORK_ERROR).toBe(1);
    expect(failures.SUBMIT_FAILED).toBe(0);
  });

  it('returns a copy (not a reference to internal state)', async () => {
    const failures = await getConsecutiveFailures();
    failures.DOM_CHANGED = 999;

    const failures2 = await getConsecutiveFailures();
    expect(failures2.DOM_CHANGED).toBe(0);
  });
});

// --- resetAllConsecutiveFailures ---

describe('resetAllConsecutiveFailures', () => {
  it('resets all counters to 0', async () => {
    await recordFailureAndDecide('t1', 'DOM_CHANGED');
    await recordFailureAndDecide('t2', 'EDITOR_NOT_FOUND');
    await recordFailureAndDecide('t3', 'NETWORK_ERROR');

    await resetAllConsecutiveFailures();

    const failures = await getConsecutiveFailures();
    expect(failures).toEqual({
      DOM_CHANGED: 0,
      EDITOR_NOT_FOUND: 0,
      SUBMIT_FAILED: 0,
      TIMEOUT: 0,
      NETWORK_ERROR: 0,
    });
  });

  it('does not affect per-task state', async () => {
    await recordFailureAndDecide('task-x', 'DOM_CHANGED');

    await resetAllConsecutiveFailures();

    const state = storage[STORAGE_KEY];
    expect(state.tasks['task-x']).toEqual({ attempts: 1, lastError: 'DOM_CHANGED' });
  });
});
