/**
 * Tests for the local task queue module.
 *
 * Mocks chrome.storage.local to test queue logic in isolation.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  MAX_QUEUE_SIZE,
  STORAGE_KEY,
  getQueue,
  enqueueTask,
  dequeueTask,
  clearQueue,
  getQueueSize,
} from './queue.js';

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

// Inject mock before module uses chrome
globalThis.chrome = { storage: chromeStorageMock };

// Reset storage between tests
beforeEach(() => {
  storage = {};
  vi.clearAllMocks();
});

// --- Helpers ---

function makeTask(overrides = {}) {
  return {
    task_id: `task-${Math.random().toString(36).slice(2, 10)}`,
    task_type: 'post_comment',
    priority: 'content',
    scheduled_at: new Date().toISOString(),
    avatar_username: 'TestUser',
    ...overrides,
  };
}

// --- Tests ---

describe('constants', () => {
  it('MAX_QUEUE_SIZE is 20', () => {
    expect(MAX_QUEUE_SIZE).toBe(20);
  });

  it('STORAGE_KEY is ramp_task_queue', () => {
    expect(STORAGE_KEY).toBe('ramp_task_queue');
  });
});

describe('getQueue', () => {
  it('returns empty array when storage is empty', async () => {
    const queue = await getQueue();
    expect(queue).toEqual([]);
  });

  it('returns tasks sorted by priority (diagnostic first)', async () => {
    const contentTask = makeTask({ task_id: 'c1', priority: 'content', scheduled_at: '2026-06-28T08:00:00Z' });
    const diagTask = makeTask({ task_id: 'd1', priority: 'diagnostic', scheduled_at: '2026-06-28T09:00:00Z' });

    storage[STORAGE_KEY] = [contentTask, diagTask];

    const queue = await getQueue();
    expect(queue[0].task_id).toBe('d1');
    expect(queue[1].task_id).toBe('c1');
  });

  it('sorts by scheduled_at within same priority', async () => {
    const early = makeTask({ task_id: 'early', priority: 'content', scheduled_at: '2026-06-28T08:00:00Z' });
    const late = makeTask({ task_id: 'late', priority: 'content', scheduled_at: '2026-06-28T10:00:00Z' });

    storage[STORAGE_KEY] = [late, early];

    const queue = await getQueue();
    expect(queue[0].task_id).toBe('early');
    expect(queue[1].task_id).toBe('late');
  });

  it('handles tasks with null scheduled_at (treated as earliest)', async () => {
    const withTime = makeTask({ task_id: 'timed', priority: 'content', scheduled_at: '2026-06-28T08:00:00Z' });
    const noTime = makeTask({ task_id: 'notime', priority: 'content', scheduled_at: null });

    storage[STORAGE_KEY] = [withTime, noTime];

    const queue = await getQueue();
    expect(queue[0].task_id).toBe('notime');
    expect(queue[1].task_id).toBe('timed');
  });
});

describe('enqueueTask', () => {
  it('adds a task to an empty queue', async () => {
    const task = makeTask({ task_id: 'new-1' });
    const result = await enqueueTask(task);

    expect(result).toEqual({ accepted: true });
    expect(storage[STORAGE_KEY]).toHaveLength(1);
    expect(storage[STORAGE_KEY][0].task_id).toBe('new-1');
  });

  it('maintains priority order after enqueue', async () => {
    const content1 = makeTask({ task_id: 'c1', priority: 'content', scheduled_at: '2026-06-28T09:00:00Z' });
    storage[STORAGE_KEY] = [content1];

    const diag = makeTask({ task_id: 'd1', priority: 'diagnostic', scheduled_at: '2026-06-28T10:00:00Z' });
    await enqueueTask(diag);

    expect(storage[STORAGE_KEY][0].task_id).toBe('d1');
    expect(storage[STORAGE_KEY][1].task_id).toBe('c1');
  });

  it('rejects duplicate task_id', async () => {
    const task = makeTask({ task_id: 'dup-1' });
    storage[STORAGE_KEY] = [task];

    const duplicate = makeTask({ task_id: 'dup-1', priority: 'diagnostic' });
    const result = await enqueueTask(duplicate);

    expect(result).toEqual({ accepted: false, reason: 'duplicate' });
    expect(storage[STORAGE_KEY]).toHaveLength(1);
  });

  it('rejects when queue is full (20 items)', async () => {
    // Fill queue to max
    const tasks = Array.from({ length: MAX_QUEUE_SIZE }, (_, i) =>
      makeTask({ task_id: `task-${i}` })
    );
    storage[STORAGE_KEY] = tasks;

    const overflow = makeTask({ task_id: 'overflow' });
    const result = await enqueueTask(overflow);

    expect(result).toEqual({ accepted: false, reason: 'overflow' });
    expect(storage[STORAGE_KEY]).toHaveLength(MAX_QUEUE_SIZE);
  });

  it('accepts task when queue has 19 items (one below max)', async () => {
    const tasks = Array.from({ length: 19 }, (_, i) =>
      makeTask({ task_id: `task-${i}` })
    );
    storage[STORAGE_KEY] = tasks;

    const result = await enqueueTask(makeTask({ task_id: 'last-one' }));
    expect(result).toEqual({ accepted: true });
    expect(storage[STORAGE_KEY]).toHaveLength(20);
  });
});

describe('dequeueTask', () => {
  it('removes and returns the task by task_id', async () => {
    const task1 = makeTask({ task_id: 'remove-me' });
    const task2 = makeTask({ task_id: 'keep-me' });
    storage[STORAGE_KEY] = [task1, task2];

    const removed = await dequeueTask('remove-me');

    expect(removed.task_id).toBe('remove-me');
    expect(storage[STORAGE_KEY]).toHaveLength(1);
    expect(storage[STORAGE_KEY][0].task_id).toBe('keep-me');
  });

  it('returns null when task_id not found', async () => {
    storage[STORAGE_KEY] = [makeTask({ task_id: 'exists' })];

    const removed = await dequeueTask('nonexistent');
    expect(removed).toBeNull();
    expect(storage[STORAGE_KEY]).toHaveLength(1);
  });

  it('returns null on empty queue', async () => {
    const removed = await dequeueTask('any-id');
    expect(removed).toBeNull();
  });
});

describe('clearQueue', () => {
  it('removes all tasks from queue', async () => {
    storage[STORAGE_KEY] = [
      makeTask({ task_id: 'a' }),
      makeTask({ task_id: 'b' }),
      makeTask({ task_id: 'c' }),
    ];

    await clearQueue();
    expect(storage[STORAGE_KEY]).toEqual([]);
  });

  it('works on already empty queue', async () => {
    await clearQueue();
    expect(storage[STORAGE_KEY]).toEqual([]);
  });
});

describe('getQueueSize', () => {
  it('returns 0 for empty queue', async () => {
    const size = await getQueueSize();
    expect(size).toBe(0);
  });

  it('returns correct count', async () => {
    storage[STORAGE_KEY] = [
      makeTask({ task_id: 'a' }),
      makeTask({ task_id: 'b' }),
      makeTask({ task_id: 'c' }),
    ];

    const size = await getQueueSize();
    expect(size).toBe(3);
  });
});

describe('priority ordering (full integration)', () => {
  it('diagnostics always come before content regardless of scheduled_at', async () => {
    // Enqueue in "wrong" order to verify sorting
    await enqueueTask(makeTask({ task_id: 'c1', priority: 'content', scheduled_at: '2026-06-28T07:00:00Z' }));
    await enqueueTask(makeTask({ task_id: 'c2', priority: 'content', scheduled_at: '2026-06-28T08:00:00Z' }));
    await enqueueTask(makeTask({ task_id: 'd1', priority: 'diagnostic', scheduled_at: '2026-06-28T12:00:00Z' }));
    await enqueueTask(makeTask({ task_id: 'd2', priority: 'diagnostic', scheduled_at: '2026-06-28T11:00:00Z' }));

    const queue = await getQueue();
    expect(queue.map((t) => t.task_id)).toEqual(['d2', 'd1', 'c1', 'c2']);
  });
});
