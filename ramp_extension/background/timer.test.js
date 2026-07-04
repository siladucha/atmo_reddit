/**
 * Tests for the timer/dispatch module.
 *
 * Mocks chrome.alarms, chrome.tabs, and chrome.storage.local
 * to test timer logic in isolation.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  TIMER_ALARM_NAME,
  startTimer,
  stopTimer,
  checkAndDispatch,
} from './timer.js';

// --- Chrome API mocks ---

let storage = {};
const STORAGE_KEY = 'ramp_task_queue';

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

const chromeAlarmsMock = {
  create: vi.fn(),
  clear: vi.fn(),
};

const chromeTabsMock = {
  query: vi.fn(async () => []),
  sendMessage: vi.fn(async () => undefined),
};

globalThis.chrome = {
  storage: chromeStorageMock,
  alarms: chromeAlarmsMock,
  tabs: chromeTabsMock,
};

// Reset between tests
beforeEach(() => {
  storage = {};
  vi.clearAllMocks();
});

// --- Helpers ---

function makeTask(overrides = {}) {
  return {
    task_id: `task-${Math.random().toString(36).slice(2, 10)}`,
    task_type: 'cqs_check',
    priority: 'diagnostic',
    scheduled_at: null,
    avatar_username: 'TestUser',
    ...overrides,
  };
}

// --- Tests ---

describe('TIMER_ALARM_NAME', () => {
  it('is "ramp-task-timer"', () => {
    expect(TIMER_ALARM_NAME).toBe('ramp-task-timer');
  });
});

describe('startTimer', () => {
  it('creates a chrome alarm with correct name and period', () => {
    startTimer();

    expect(chromeAlarmsMock.create).toHaveBeenCalledOnce();
    expect(chromeAlarmsMock.create).toHaveBeenCalledWith('ramp-task-timer', {
      delayInMinutes: 0.25,
      periodInMinutes: 0.25,
    });
  });
});

describe('stopTimer', () => {
  it('clears the timer alarm', () => {
    stopTimer();

    expect(chromeAlarmsMock.clear).toHaveBeenCalledOnce();
    expect(chromeAlarmsMock.clear).toHaveBeenCalledWith('ramp-task-timer');
  });
});

describe('checkAndDispatch', () => {
  it('does nothing when queue is empty', async () => {
    storage[STORAGE_KEY] = [];

    await checkAndDispatch();

    expect(chromeTabsMock.query).not.toHaveBeenCalled();
    expect(chromeTabsMock.sendMessage).not.toHaveBeenCalled();
  });

  it('dispatches a due diagnostic task with null scheduled_at', async () => {
    const task = makeTask({ task_id: 'diag-1', priority: 'diagnostic', scheduled_at: null });
    storage[STORAGE_KEY] = [task];

    // Mock: a Reddit tab exists
    chromeTabsMock.query.mockResolvedValueOnce([{ id: 42, lastAccessed: Date.now() }]);

    await checkAndDispatch();

    expect(chromeTabsMock.sendMessage).toHaveBeenCalledWith(42, {
      type: 'EXECUTE_TASK',
      task: expect.objectContaining({ task_id: 'diag-1' }),
    });

    // Task should be removed from queue
    expect(storage[STORAGE_KEY]).toHaveLength(0);
  });

  it('dispatches a due diagnostic task when scheduled_at is in the past', async () => {
    const pastTime = new Date(Date.now() - 60000).toISOString();
    const task = makeTask({ task_id: 'diag-past', priority: 'diagnostic', scheduled_at: pastTime });
    storage[STORAGE_KEY] = [task];

    chromeTabsMock.query.mockResolvedValueOnce([{ id: 10, lastAccessed: Date.now() }]);

    await checkAndDispatch();

    expect(chromeTabsMock.sendMessage).toHaveBeenCalledOnce();
    expect(storage[STORAGE_KEY]).toHaveLength(0);
  });

  it('does NOT dispatch a diagnostic task when scheduled_at is in the future', async () => {
    const futureTime = new Date(Date.now() + 60000).toISOString();
    const task = makeTask({ task_id: 'diag-future', priority: 'diagnostic', scheduled_at: futureTime });
    storage[STORAGE_KEY] = [task];

    await checkAndDispatch();

    expect(chromeTabsMock.sendMessage).not.toHaveBeenCalled();
    // Task should remain in queue
    expect(storage[STORAGE_KEY]).toHaveLength(1);
  });

  it('does NOT dispatch content tasks (they require manual approval)', async () => {
    const task = makeTask({ task_id: 'content-1', priority: 'content', scheduled_at: null });
    storage[STORAGE_KEY] = [task];

    await checkAndDispatch();

    expect(chromeTabsMock.sendMessage).not.toHaveBeenCalled();
    expect(storage[STORAGE_KEY]).toHaveLength(1);
  });

  it('processes only ONE task per tick', async () => {
    const task1 = makeTask({ task_id: 'diag-a', priority: 'diagnostic', scheduled_at: null });
    const task2 = makeTask({ task_id: 'diag-b', priority: 'diagnostic', scheduled_at: null });
    storage[STORAGE_KEY] = [task1, task2];

    chromeTabsMock.query.mockResolvedValueOnce([{ id: 5, lastAccessed: Date.now() }]);

    await checkAndDispatch();

    // Only one message sent
    expect(chromeTabsMock.sendMessage).toHaveBeenCalledOnce();
    // One task remains
    expect(storage[STORAGE_KEY]).toHaveLength(1);
  });

  it('skips content task and dispatches the first due diagnostic', async () => {
    const contentTask = makeTask({ task_id: 'content-x', priority: 'content', scheduled_at: null });
    const diagTask = makeTask({ task_id: 'diag-x', priority: 'diagnostic', scheduled_at: null });
    // Queue is priority-sorted: diagnostic first
    storage[STORAGE_KEY] = [diagTask, contentTask];

    chromeTabsMock.query.mockResolvedValueOnce([{ id: 7, lastAccessed: Date.now() }]);

    await checkAndDispatch();

    expect(chromeTabsMock.sendMessage).toHaveBeenCalledWith(7, {
      type: 'EXECUTE_TASK',
      task: expect.objectContaining({ task_id: 'diag-x' }),
    });
    // Content task remains
    expect(storage[STORAGE_KEY]).toHaveLength(1);
    expect(storage[STORAGE_KEY][0].task_id).toBe('content-x');
  });

  it('does not dispatch if no Reddit tab is available', async () => {
    const task = makeTask({ task_id: 'diag-no-tab', priority: 'diagnostic', scheduled_at: null });
    storage[STORAGE_KEY] = [task];

    // First query (active reddit tabs): empty
    chromeTabsMock.query.mockResolvedValueOnce([]);
    // Second query (any reddit tabs): also empty
    chromeTabsMock.query.mockResolvedValueOnce([]);

    await checkAndDispatch();

    expect(chromeTabsMock.sendMessage).not.toHaveBeenCalled();
    // Task is dequeued even though dispatch failed (lease expiry handles retry)
    expect(storage[STORAGE_KEY]).toHaveLength(0);
  });

  it('uses a non-active Reddit tab if no active Reddit tab exists', async () => {
    const task = makeTask({ task_id: 'diag-fallback', priority: 'diagnostic', scheduled_at: null });
    storage[STORAGE_KEY] = [task];

    // First query (active reddit tabs): empty
    chromeTabsMock.query.mockResolvedValueOnce([]);
    // Second query (any reddit tabs): one available
    chromeTabsMock.query.mockResolvedValueOnce([
      { id: 99, lastAccessed: Date.now() - 5000 },
      { id: 100, lastAccessed: Date.now() },
    ]);

    await checkAndDispatch();

    // Should use the most recently accessed tab (id: 100)
    expect(chromeTabsMock.sendMessage).toHaveBeenCalledWith(100, {
      type: 'EXECUTE_TASK',
      task: expect.objectContaining({ task_id: 'diag-fallback' }),
    });
  });
});
