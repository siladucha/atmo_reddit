/**
 * Tests for scheduler.js
 *
 * Validates:
 * - schedulerTick returns immediately when pause_all is true
 * - schedulerTick returns immediately when dom_health is "broken"
 * - schedulerTick returns immediately outside active hours (08:00–22:00)
 * - schedulerTick returns immediately when 3-minute interval not elapsed
 * - schedulerTick finds and executes due approved tasks
 * - schedulerTick prevents double-dispatch (marks task 'executing')
 * - schedulerTick handles execution success correctly
 * - schedulerTick handles execution failure with retry
 * - schedulerTick handles execution failure with permanent fail
 * - schedulerTick respects retry_after on tasks
 * - generateJitterOffset produces values within expected range
 * - startScheduler/stopScheduler manage the alarm
 * - setPauseAll updates storage
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// ─── Chrome API Mocks ────────────────────────────────────────────────────────

let storageData = {};
let alarms = {};

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

const chromeAlarmsMock = {
  create: vi.fn(async (name, opts) => {
    alarms[name] = opts;
  }),
  clear: vi.fn(async (name) => {
    delete alarms[name];
    return true;
  }),
};

const chromeTabsMock = {
  query: vi.fn(async () => [{ id: 42, lastAccessed: Date.now() }]),
  create: vi.fn(async (opts) => ({ id: 99, ...opts })),
  update: vi.fn(async () => {}),
  sendMessage: vi.fn(async () => null),
  onUpdated: {
    addListener: vi.fn(),
    removeListener: vi.fn(),
  },
};

const chromeActionMock = {
  setBadgeText: vi.fn(async () => {}),
  setBadgeBackgroundColor: vi.fn(async () => {}),
};

globalThis.chrome = {
  storage: chromeStorageMock,
  alarms: chromeAlarmsMock,
  tabs: chromeTabsMock,
  action: chromeActionMock,
};

// ─── Mock dependencies ───────────────────────────────────────────────────────

// Mock executeTask
const mockExecuteTask = vi.fn(async () => ({
  success: true,
  permalink: 'https://reddit.com/r/test/comments/abc/comment/xyz',
  comment_id: 'xyz',
  events: [],
  duration_ms: 5000,
}));

vi.mock('./executor.js', () => ({
  executeTask: (...args) => mockExecuteTask(...args),
}));

// Mock executeTaskOldReddit
const mockExecuteTaskOldReddit = vi.fn(async () => ({
  success: true,
  permalink: 'https://old.reddit.com/r/test/comments/abc/comment/old123',
  comment_id: 'old123',
  events: [],
  duration_ms: 4000,
}));

vi.mock('./executor-old-reddit.js', () => ({
  executeTaskOldReddit: (...args) => mockExecuteTaskOldReddit(...args),
}));

// Mock retry-engine
const mockRecordFailureAndDecide = vi.fn(async () => ({
  shouldRetry: false,
  delayMs: 0,
  markBroken: false,
  markFailed: true,
}));
const mockResetRetryState = vi.fn(async () => {});

vi.mock('./retry-engine.js', () => ({
  recordFailureAndDecide: (...args) => mockRecordFailureAndDecide(...args),
  resetRetryState: (...args) => mockResetRetryState(...args),
  resetAllConsecutiveFailures: vi.fn(async () => {}),
  getConsecutiveFailures: vi.fn(async () => ({
    DOM_CHANGED: 0,
    EDITOR_NOT_FOUND: 0,
    SUBMIT_FAILED: 0,
    TIMEOUT: 0,
    NETWORK_ERROR: 0,
  })),
}));

// Mock health-monitor (partially — we need getHealthState to read from storage)
vi.mock('./health-monitor.js', () => ({
  recordSuccess: vi.fn(async () => {}),
  recordFailure: vi.fn(async () => {}),
  getHealthState: vi.fn(async () => {
    const healthData = storageData['ramp_health'];
    return healthData || { dom_health: 'ok', reddit_session_valid: true, last_task_executed_at: null };
  }),
  evaluateDomHealth: vi.fn(async () => 'ok'),
}));

// Mock auth
vi.mock('../shared/auth.js', () => ({
  getAuth: vi.fn(async () => ({
    token: 'test-token',
    nodeId: 'node-1',
    rampUrl: 'https://gorampit.com',
  })),
}));

// ─── Import after mocks ──────────────────────────────────────────────────────

const {
  schedulerTick,
  startScheduler,
  stopScheduler,
  setPauseAll,
  generateJitterOffset,
  SCHEDULER_ALARM_NAME,
} = await import('./scheduler.js');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeTask(overrides = {}) {
  return {
    task_id: 'task-001',
    task_type: 'epg',
    thread_url: 'https://www.reddit.com/r/test/comments/abc/test_post/',
    comment_text: 'This is a test comment for the scheduler.',
    scheduled_at: new Date(Date.now() - 60000).toISOString(), // 1 min ago (due)
    status: 'approved',
    ...overrides,
  };
}

// Set active hours by mocking Date
function mockHour(hour) {
  vi.useFakeTimers();
  const date = new Date();
  date.setHours(hour, 30, 0, 0);
  vi.setSystemTime(date);
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('scheduler', () => {
  beforeEach(() => {
    storageData = {};
    alarms = {};
    vi.clearAllMocks();
    vi.useRealTimers();

    // Default: no fetch calls
    globalThis.fetch = vi.fn(async () => ({ ok: true }));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('startScheduler()', () => {
    it('creates a chrome alarm with correct name and period', async () => {
      await startScheduler();

      expect(chromeAlarmsMock.create).toHaveBeenCalledWith(
        SCHEDULER_ALARM_NAME,
        { delayInMinutes: 0.25, periodInMinutes: 0.25 },
      );
    });
  });

  describe('stopScheduler()', () => {
    it('clears the scheduler alarm', async () => {
      await stopScheduler();

      expect(chromeAlarmsMock.clear).toHaveBeenCalledWith(SCHEDULER_ALARM_NAME);
    });
  });

  describe('schedulerTick() — guard checks', () => {
    it('returns immediately when pause_all is true', async () => {
      mockHour(12);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: true,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('returns immediately when dom_health is "broken"', async () => {
      mockHour(12);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_health'] = {
        dom_health: 'broken',
        reddit_session_valid: true,
        last_task_executed_at: null,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('returns immediately outside active hours (before 08:00)', async () => {
      mockHour(7);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('returns immediately outside active hours (at/after 22:00)', async () => {
      mockHour(22);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('returns immediately when 3-minute interval not elapsed', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: new Date().toISOString(), // just now
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('proceeds when 3-minute interval has elapsed', async () => {
      mockHour(14);
      const threeMinAgo = new Date(Date.now() - 200000).toISOString();
      storageData['ramp_scheduler_state'] = {
        last_execution_time: threeMinAgo,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      await schedulerTick();

      expect(mockExecuteTask).toHaveBeenCalled();
    });
  });

  describe('schedulerTick() — task selection', () => {
    it('skips tasks that are not approved', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ status: 'pending' }),
        makeTask({ task_id: 'task-002', status: 'completed' }),
      ];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('skips tasks with retry_after in the future', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ retry_after: new Date(Date.now() + 60000).toISOString() }),
      ];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('executes tasks with expired retry_after', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ retry_after: new Date(Date.now() - 1000).toISOString() }),
      ];

      await schedulerTick();

      expect(mockExecuteTask).toHaveBeenCalled();
    });

    it('skips tasks with scheduled_at in the future', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ scheduled_at: new Date(Date.now() + 600000).toISOString() }), // 10 min future
      ];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('returns immediately when queue is empty', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [];

      await schedulerTick();

      expect(mockExecuteTask).not.toHaveBeenCalled();
    });
  });

  describe('schedulerTick() — execution', () => {
    it('marks task as "executing" before dispatch (double-dispatch prevention)', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      const task = makeTask();
      storageData['ramp_task_queue'] = [task];

      // Track the status when saveQueue is called with 'executing'
      let statusWhenExecutorCalled = null;
      mockExecuteTask.mockImplementation(async () => {
        // At this point, the queue should have been saved with 'executing' status
        // Read the raw storage to verify (storageData is the mock source of truth)
        const queueSnapshot = storageData['ramp_task_queue'];
        const execTask = queueSnapshot.find(t => t.task_id === 'task-001');
        statusWhenExecutorCalled = execTask?.status;
        return { success: true, permalink: '/r/test/xyz', comment_id: 'xyz', events: [], duration_ms: 100 };
      });

      await schedulerTick();

      // During execution, task should have been marked 'executing'
      expect(statusWhenExecutorCalled).toBe('executing');
    });

    it('marks task as "completed" on success', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      mockExecuteTask.mockResolvedValue({
        success: true,
        permalink: 'https://reddit.com/r/test/comments/abc/comment/xyz123',
        comment_id: 'xyz123',
        events: [],
        duration_ms: 3000,
      });

      await schedulerTick();

      const queue = storageData['ramp_task_queue'];
      const completed = queue.find(t => t.task_id === 'task-001');
      expect(completed.status).toBe('completed');
      expect(completed.permalink).toBe('https://reddit.com/r/test/comments/abc/comment/xyz123');
      expect(completed.comment_id).toBe('xyz123');
      expect(completed.completed_at).toBeDefined();
    });

    it('updates last_execution_time on success', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      mockExecuteTask.mockResolvedValue({
        success: true,
        permalink: '/r/test/xyz',
        comment_id: 'xyz',
        events: [],
        duration_ms: 100,
      });

      await schedulerTick();

      const state = storageData['ramp_scheduler_state'];
      expect(state.last_execution_time).not.toBeNull();
      expect(new Date(state.last_execution_time).getTime()).toBeGreaterThan(0);
    });

    it('sets task to "approved" with retry_after on retriable failure', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      mockExecuteTask.mockResolvedValue({
        success: false,
        error_code: 'DOM_CHANGED',
        error_details: 'Selector not found',
        events: [],
        duration_ms: 2000,
      });

      mockRecordFailureAndDecide.mockResolvedValue({
        shouldRetry: true,
        delayMs: 5000,
        markBroken: false,
        markFailed: false,
      });

      await schedulerTick();

      const queue = storageData['ramp_task_queue'];
      const task = queue.find(t => t.task_id === 'task-001');
      expect(task.status).toBe('approved');
      expect(task.retry_after).toBeDefined();
      expect(task.last_error).toBe('DOM_CHANGED');
    });

    it('marks task as "failed" on non-retriable failure', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      mockExecuteTask.mockResolvedValue({
        success: false,
        error_code: 'AUTH_FAILED',
        error_details: 'Session expired',
        events: [],
        duration_ms: 500,
      });

      mockRecordFailureAndDecide.mockResolvedValue({
        shouldRetry: false,
        delayMs: 0,
        markBroken: false,
        markFailed: true,
      });

      await schedulerTick();

      const queue = storageData['ramp_task_queue'];
      const task = queue.find(t => t.task_id === 'task-001');
      expect(task.status).toBe('failed');
      expect(task.error_code).toBe('AUTH_FAILED');
      expect(task.failed_at).toBeDefined();
    });

    it('only executes ONE task per tick', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ task_id: 'task-001' }),
        makeTask({ task_id: 'task-002' }),
        makeTask({ task_id: 'task-003' }),
      ];

      await schedulerTick();

      // Should only execute once
      expect(mockExecuteTask).toHaveBeenCalledTimes(1);
    });
  });

  describe('setPauseAll()', () => {
    it('sets pause_all to true in storage', async () => {
      await setPauseAll(true);

      const state = storageData['ramp_scheduler_state'];
      expect(state.pause_all).toBe(true);
    });

    it('sets pause_all to false in storage', async () => {
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: true,
      };

      await setPauseAll(false);

      const state = storageData['ramp_scheduler_state'];
      expect(state.pause_all).toBe(false);
    });
  });

  describe('generateJitterOffset()', () => {
    it('returns a number within ±300000ms range', () => {
      for (let i = 0; i < 100; i++) {
        const offset = generateJitterOffset();
        expect(offset).toBeGreaterThanOrEqual(-300000);
        expect(offset).toBeLessThanOrEqual(300000);
      }
    });

    it('returns different values (not constant)', () => {
      const offsets = new Set();
      for (let i = 0; i < 20; i++) {
        offsets.add(generateJitterOffset());
      }
      // With 20 random samples, we should have at least 2 distinct values
      expect(offsets.size).toBeGreaterThan(1);
    });
  });

  describe('schedulerTick() — tab handling', () => {
    it('uses existing Reddit tab when available', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()];

      // Return existing Reddit tab
      chromeTabsMock.query.mockResolvedValue([{ id: 42, lastAccessed: Date.now() }]);

      await schedulerTick();

      // Should have used the existing tab (not create a new one)
      expect(chromeTabsMock.create).not.toHaveBeenCalled();
      expect(mockExecuteTask).toHaveBeenCalledWith(
        expect.objectContaining({ task_id: 'task-001' }),
        42,
      );
    });
  });

  describe('schedulerTick() — posting strategy routing', () => {
    it('routes tasks with posting_strategy=old_reddit to executeTaskOldReddit()', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ posting_strategy: 'old_reddit' }),
      ];

      mockExecuteTaskOldReddit.mockResolvedValue({
        success: true,
        permalink: 'https://old.reddit.com/r/test/comments/abc/comment/old123',
        comment_id: 'old123',
        events: [],
        duration_ms: 4000,
      });

      await schedulerTick();

      expect(mockExecuteTaskOldReddit).toHaveBeenCalledWith(
        expect.objectContaining({ task_id: 'task-001', posting_strategy: 'old_reddit' }),
        42,
      );
      expect(mockExecuteTask).not.toHaveBeenCalled();
    });

    it('routes tasks with posting_strategy=new_reddit_debugger to executeTask()', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ posting_strategy: 'new_reddit_debugger' }),
      ];

      mockExecuteTask.mockResolvedValue({
        success: true,
        permalink: 'https://reddit.com/r/test/comments/abc/comment/new456',
        comment_id: 'new456',
        events: [],
        duration_ms: 5000,
      });

      await schedulerTick();

      expect(mockExecuteTask).toHaveBeenCalledWith(
        expect.objectContaining({ task_id: 'task-001', posting_strategy: 'new_reddit_debugger' }),
        42,
      );
      expect(mockExecuteTaskOldReddit).not.toHaveBeenCalled();
    });

    it('routes tasks without posting_strategy (null/undefined) to executeTask() for backward compatibility', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      // No posting_strategy field at all — backward compat case
      storageData['ramp_task_queue'] = [
        makeTask(), // no posting_strategy set
      ];

      mockExecuteTask.mockResolvedValue({
        success: true,
        permalink: 'https://reddit.com/r/test/comments/abc/comment/default789',
        comment_id: 'default789',
        events: [],
        duration_ms: 3000,
      });

      await schedulerTick();

      expect(mockExecuteTask).toHaveBeenCalled();
      expect(mockExecuteTaskOldReddit).not.toHaveBeenCalled();
    });

    it('includes posting_strategy in completed task record on success', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ posting_strategy: 'old_reddit' }),
      ];

      mockExecuteTaskOldReddit.mockResolvedValue({
        success: true,
        permalink: 'https://old.reddit.com/r/test/comments/abc/comment/old999',
        comment_id: 'old999',
        events: [],
        duration_ms: 3500,
      });

      await schedulerTick();

      const queue = storageData['ramp_task_queue'];
      const completed = queue.find(t => t.task_id === 'task-001');
      expect(completed.status).toBe('completed');
      expect(completed.posting_strategy_used).toBe('old_reddit');
    });

    it('defaults posting_strategy_used to new_reddit_debugger when task has no posting_strategy', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [makeTask()]; // no posting_strategy

      mockExecuteTask.mockResolvedValue({
        success: true,
        permalink: '/r/test/xyz',
        comment_id: 'xyz',
        events: [],
        duration_ms: 100,
      });

      await schedulerTick();

      const queue = storageData['ramp_task_queue'];
      const completed = queue.find(t => t.task_id === 'task-001');
      expect(completed.posting_strategy_used).toBe('new_reddit_debugger');
    });

    it('includes posting_strategy in failure report to backend', async () => {
      mockHour(14);
      storageData['ramp_scheduler_state'] = {
        last_execution_time: null,
        pause_all: false,
      };
      storageData['ramp_task_queue'] = [
        makeTask({ posting_strategy: 'old_reddit' }),
      ];

      mockExecuteTaskOldReddit.mockResolvedValue({
        success: false,
        error_code: 'TEXTAREA_NOT_FOUND',
        error_details: 'Comment textarea not found',
        events: [],
        duration_ms: 2000,
      });

      mockRecordFailureAndDecide.mockResolvedValue({
        shouldRetry: false,
        delayMs: 0,
        markBroken: false,
        markFailed: true,
      });

      await schedulerTick();

      // Verify the failure report includes posting_strategy
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/extension/report'),
        expect.objectContaining({
          body: expect.stringContaining('"posting_strategy":"old_reddit"'),
        }),
      );
    });
  });
});
