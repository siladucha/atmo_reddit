/**
 * Tests for health-monitor.js
 *
 * Validates:
 * - evaluateDomHealth returns "broken" after 3+ consecutive DOM_CHANGED or EDITOR_NOT_FOUND
 * - evaluateDomHealth returns "ok" when below threshold
 * - getHealthState re-evaluates dom_health from live failure counts
 * - recordSuccess resets counters and updates last_task_executed_at
 * - recordFailure re-evaluates and persists dom_health
 * - checkRedditSession queries Reddit tab and stores result
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

// ─── Chrome API Mocks ────────────────────────────────────────────────────────

let storageData = {};

const chromeStorageMock = {
  local: {
    get: vi.fn(async (key) => {
      if (typeof key === 'string') {
        return { [key]: storageData[key] };
      }
      return storageData;
    }),
    set: vi.fn(async (obj) => {
      Object.assign(storageData, obj);
    }),
  },
};

const chromeTabsMock = {
  query: vi.fn(async () => []),
  sendMessage: vi.fn(async () => null),
};

globalThis.chrome = {
  storage: chromeStorageMock,
  tabs: chromeTabsMock,
};

// ─── Import after mocks ──────────────────────────────────────────────────────

const {
  evaluateDomHealth,
  getHealthState,
  recordSuccess,
  recordFailure,
  checkRedditSession,
  HEALTH_STORAGE_KEY,
} = await import('./health-monitor.js');

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('health-monitor', () => {
  beforeEach(() => {
    storageData = {};
    vi.clearAllMocks();
  });

  describe('evaluateDomHealth()', () => {
    it('returns "ok" when no failures exist', async () => {
      // Default state from retry-engine has all zeros
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: {
          DOM_CHANGED: 0,
          EDITOR_NOT_FOUND: 0,
          SUBMIT_FAILED: 0,
          TIMEOUT: 0,
          NETWORK_ERROR: 0,
        },
      };

      const result = await evaluateDomHealth();
      expect(result).toBe('ok');
    });

    it('returns "ok" when failures below threshold (2 DOM_CHANGED)', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: {
          DOM_CHANGED: 2,
          EDITOR_NOT_FOUND: 0,
          SUBMIT_FAILED: 0,
          TIMEOUT: 0,
          NETWORK_ERROR: 0,
        },
      };

      const result = await evaluateDomHealth();
      expect(result).toBe('ok');
    });

    it('returns "broken" when DOM_CHANGED reaches threshold (3)', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: {
          DOM_CHANGED: 3,
          EDITOR_NOT_FOUND: 0,
          SUBMIT_FAILED: 0,
          TIMEOUT: 0,
          NETWORK_ERROR: 0,
        },
      };

      const result = await evaluateDomHealth();
      expect(result).toBe('broken');
    });

    it('returns "broken" when EDITOR_NOT_FOUND reaches threshold (3)', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: {
          DOM_CHANGED: 0,
          EDITOR_NOT_FOUND: 3,
          SUBMIT_FAILED: 0,
          TIMEOUT: 0,
          NETWORK_ERROR: 0,
        },
      };

      const result = await evaluateDomHealth();
      expect(result).toBe('broken');
    });

    it('returns "broken" when DOM_CHANGED exceeds threshold (5)', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: {
          DOM_CHANGED: 5,
          EDITOR_NOT_FOUND: 0,
          SUBMIT_FAILED: 0,
          TIMEOUT: 0,
          NETWORK_ERROR: 0,
        },
      };

      const result = await evaluateDomHealth();
      expect(result).toBe('broken');
    });

    it('returns "ok" when other failure types are high but DOM types are low', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: {
          DOM_CHANGED: 1,
          EDITOR_NOT_FOUND: 1,
          SUBMIT_FAILED: 10,
          TIMEOUT: 10,
          NETWORK_ERROR: 10,
        },
      };

      const result = await evaluateDomHealth();
      expect(result).toBe('ok');
    });

    it('returns "ok" when retry state is missing (fresh install)', async () => {
      // No ramp_retry_state in storage
      const result = await evaluateDomHealth();
      expect(result).toBe('ok');
    });
  });

  describe('getHealthState()', () => {
    it('returns default state when nothing stored', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: { DOM_CHANGED: 0, EDITOR_NOT_FOUND: 0, SUBMIT_FAILED: 0, TIMEOUT: 0, NETWORK_ERROR: 0 },
      };

      const state = await getHealthState();
      expect(state.dom_health).toBe('ok');
      expect(state.reddit_session_valid).toBe(true);
      expect(state.last_task_executed_at).toBeNull();
    });

    it('re-evaluates dom_health from live failure counts', async () => {
      // Store says "ok" but failures say "broken"
      storageData[HEALTH_STORAGE_KEY] = {
        dom_health: 'ok',
        reddit_session_valid: true,
        last_task_executed_at: '2026-07-01T10:00:00Z',
      };
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: { DOM_CHANGED: 4, EDITOR_NOT_FOUND: 0, SUBMIT_FAILED: 0, TIMEOUT: 0, NETWORK_ERROR: 0 },
      };

      const state = await getHealthState();
      expect(state.dom_health).toBe('broken');
      expect(state.last_task_executed_at).toBe('2026-07-01T10:00:00Z');
    });

    it('preserves reddit_session_valid from storage', async () => {
      storageData[HEALTH_STORAGE_KEY] = {
        dom_health: 'ok',
        reddit_session_valid: false,
        last_task_executed_at: null,
      };
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: { DOM_CHANGED: 0, EDITOR_NOT_FOUND: 0, SUBMIT_FAILED: 0, TIMEOUT: 0, NETWORK_ERROR: 0 },
      };

      const state = await getHealthState();
      expect(state.reddit_session_valid).toBe(false);
    });
  });

  describe('recordSuccess()', () => {
    it('sets dom_health to "ok" and updates last_task_executed_at', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: { DOM_CHANGED: 2, EDITOR_NOT_FOUND: 1, SUBMIT_FAILED: 0, TIMEOUT: 0, NETWORK_ERROR: 0 },
      };
      storageData[HEALTH_STORAGE_KEY] = {
        dom_health: 'broken',
        reddit_session_valid: true,
        last_task_executed_at: null,
      };

      await recordSuccess();

      // Check that health state was updated
      const stored = storageData[HEALTH_STORAGE_KEY];
      expect(stored.dom_health).toBe('ok');
      expect(stored.last_task_executed_at).not.toBeNull();
      expect(new Date(stored.last_task_executed_at).getTime()).toBeGreaterThan(0);
    });

    it('resets consecutive failure counters', async () => {
      storageData['ramp_retry_state'] = {
        tasks: { 'task-1': { attempts: 2, lastError: 'DOM_CHANGED' } },
        consecutive_failures: { DOM_CHANGED: 5, EDITOR_NOT_FOUND: 3, SUBMIT_FAILED: 1, TIMEOUT: 0, NETWORK_ERROR: 2 },
      };

      await recordSuccess();

      // Verify consecutive_failures reset to zeros
      const retryState = storageData['ramp_retry_state'];
      expect(retryState.consecutive_failures.DOM_CHANGED).toBe(0);
      expect(retryState.consecutive_failures.EDITOR_NOT_FOUND).toBe(0);
      expect(retryState.consecutive_failures.SUBMIT_FAILED).toBe(0);
      expect(retryState.consecutive_failures.NETWORK_ERROR).toBe(0);
    });
  });

  describe('recordFailure()', () => {
    it('sets dom_health to "broken" when threshold is reached', async () => {
      // Already at 3 DOM_CHANGED (threshold)
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: { DOM_CHANGED: 3, EDITOR_NOT_FOUND: 0, SUBMIT_FAILED: 0, TIMEOUT: 0, NETWORK_ERROR: 0 },
      };

      await recordFailure('DOM_CHANGED');

      const stored = storageData[HEALTH_STORAGE_KEY];
      expect(stored.dom_health).toBe('broken');
    });

    it('keeps dom_health as "ok" when below threshold', async () => {
      storageData['ramp_retry_state'] = {
        tasks: {},
        consecutive_failures: { DOM_CHANGED: 1, EDITOR_NOT_FOUND: 0, SUBMIT_FAILED: 0, TIMEOUT: 0, NETWORK_ERROR: 0 },
      };

      await recordFailure('SUBMIT_FAILED');

      const stored = storageData[HEALTH_STORAGE_KEY];
      expect(stored.dom_health).toBe('ok');
    });
  });

  describe('checkRedditSession()', () => {
    it('returns true and stores valid when session is active', async () => {
      chromeTabsMock.query.mockResolvedValue([{ id: 1 }]);
      chromeTabsMock.sendMessage.mockResolvedValue({ expired: false });

      const result = await checkRedditSession();

      expect(result).toBe(true);
      const stored = storageData[HEALTH_STORAGE_KEY];
      expect(stored.reddit_session_valid).toBe(true);
    });

    it('returns false and stores invalid when session is expired', async () => {
      chromeTabsMock.query.mockResolvedValue([{ id: 1 }]);
      chromeTabsMock.sendMessage.mockResolvedValue({ expired: true });

      const result = await checkRedditSession();

      expect(result).toBe(false);
      const stored = storageData[HEALTH_STORAGE_KEY];
      expect(stored.reddit_session_valid).toBe(false);
    });

    it('keeps previous state when no Reddit tab found', async () => {
      storageData[HEALTH_STORAGE_KEY] = {
        dom_health: 'ok',
        reddit_session_valid: false,
        last_task_executed_at: null,
      };
      chromeTabsMock.query.mockResolvedValue([]);

      const result = await checkRedditSession();

      // Previous state was false, should stay false
      expect(result).toBe(false);
    });

    it('keeps previous state when content script does not respond', async () => {
      storageData[HEALTH_STORAGE_KEY] = {
        dom_health: 'ok',
        reddit_session_valid: true,
        last_task_executed_at: null,
      };
      chromeTabsMock.query.mockResolvedValue([{ id: 1 }]);
      chromeTabsMock.sendMessage.mockRejectedValue(new Error('No content script'));

      const result = await checkRedditSession();

      // Should keep previous state (true)
      expect(result).toBe(true);
    });

    it('tries multiple tabs if first does not respond', async () => {
      storageData[HEALTH_STORAGE_KEY] = {
        dom_health: 'ok',
        reddit_session_valid: true,
        last_task_executed_at: null,
      };
      chromeTabsMock.query.mockResolvedValue([{ id: 1 }, { id: 2 }]);
      chromeTabsMock.sendMessage
        .mockRejectedValueOnce(new Error('Tab 1 no script'))
        .mockResolvedValueOnce({ expired: true });

      const result = await checkRedditSession();

      expect(result).toBe(false);
      expect(chromeTabsMock.sendMessage).toHaveBeenCalledTimes(2);
    });
  });
});
