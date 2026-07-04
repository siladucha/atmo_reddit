/**
 * Tests for the service worker message handlers (GET_QUEUE, GET_STATUS, APPROVE_TASK, REJECT_TASK).
 *
 * These test the message handling logic by importing the service worker module
 * with all Chrome APIs and dependencies mocked.
 */

import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest';

// --- Chrome API mocks (set up BEFORE any imports that use chrome) ---
let storage = {};
let messageListeners = [];

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
    remove: vi.fn(async (key) => {
      delete storage[key];
    }),
  },
};

globalThis.chrome = {
  storage: chromeStorageMock,
  runtime: {
    onMessage: {
      addListener: vi.fn((fn) => {
        messageListeners.push(fn);
      }),
    },
    getManifest: vi.fn(() => ({ version: '1.0.0' })),
    sendMessage: vi.fn(),
  },
  alarms: {
    create: vi.fn(),
    clear: vi.fn(async () => true),
    onAlarm: {
      addListener: vi.fn(),
    },
  },
  tabs: {
    query: vi.fn(async () => []),
    sendMessage: vi.fn(),
  },
  action: {
    setBadgeText: vi.fn(),
    setBadgeBackgroundColor: vi.fn(),
  },
};

// Mock fetch for rejection reports
globalThis.fetch = vi.fn(async () => ({
  ok: true,
  status: 200,
  statusText: 'OK',
  json: async () => ({ tasks: [] }),
}));

// Now import the modules AFTER chrome mocks are in place
import { getQueue, enqueueTask, dequeueTask } from './queue.js';

// Import the service worker to trigger listener registration
await import('./service-worker.js');

// Get the message listener that was registered
const listener = messageListeners[0];

/**
 * Helper: simulate sending a message and getting the async response.
 */
function sendMessage(message) {
  return new Promise((resolve) => {
    const sendResponse = (response) => resolve(response);
    const result = listener(message, {}, sendResponse);
    // If synchronous (returns false), resolve immediately
    if (result !== true) {
      resolve(undefined);
    }
  });
}

beforeEach(() => {
  storage = {};
  globalThis.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => ({ tasks: [] }),
  }));
});

describe('Service Worker Message Handlers', () => {
  it('listener is registered', () => {
    expect(listener).toBeDefined();
    expect(typeof listener).toBe('function');
  });

  describe('GET_QUEUE', () => {
    it('returns empty tasks array when queue is empty', async () => {
      const response = await sendMessage({ type: 'GET_QUEUE' });
      expect(response).toEqual({ tasks: [] });
    });

    it('returns tasks from the queue', async () => {
      const task = {
        task_id: 'test-123',
        task_type: 'post_comment',
        priority: 'content',
        scheduled_at: '2026-06-28T08:00:00Z',
        subreddit: 'biohackers',
        comment_text: 'hello world',
      };
      await enqueueTask(task);

      const response = await sendMessage({ type: 'GET_QUEUE' });
      expect(response.tasks).toHaveLength(1);
      expect(response.tasks[0].task_id).toBe('test-123');
    });
  });

  describe('GET_STATUS', () => {
    it('returns disconnected when not authenticated', async () => {
      const response = await sendMessage({ type: 'GET_STATUS' });
      expect(response.status).toBe('disconnected');
      expect(response.statusText).toBe('Not authenticated');
    });

    it('returns degraded when authenticated but no successful poll yet', async () => {
      storage['ramp_auth'] = {
        token: 'test-token',
        nodeId: 'node-123',
        rampUrl: 'https://gorampit.com',
      };

      const response = await sendMessage({ type: 'GET_STATUS' });
      // Polling is active but _lastPollSuccess starts as false
      expect(response.status).toBe('degraded');
      expect(response.statusText).toBe('Connection issues');
    });
  });

  describe('APPROVE_TASK', () => {
    it('dequeues the task and returns ok', async () => {
      const task = {
        task_id: 'approve-me',
        task_type: 'post_comment',
        priority: 'content',
        scheduled_at: '2026-06-28T09:00:00Z',
      };
      await enqueueTask(task);

      const response = await sendMessage({
        type: 'APPROVE_TASK',
        taskId: 'approve-me',
      });
      expect(response.ok).toBe(true);

      // Verify task was removed from queue
      const queue = await getQueue();
      expect(queue).toHaveLength(0);
    });

    it('returns ok even if task not found', async () => {
      const response = await sendMessage({
        type: 'APPROVE_TASK',
        taskId: 'nonexistent',
      });
      expect(response.ok).toBe(true);
    });
  });

  describe('REJECT_TASK', () => {
    it('dequeues the task and reports rejection to backend', async () => {
      storage['ramp_auth'] = {
        token: 'test-token',
        nodeId: 'node-123',
        rampUrl: 'https://gorampit.com',
      };

      const task = {
        task_id: 'reject-me',
        idempotency_key: 'idem-123',
        task_type: 'post_comment',
        priority: 'content',
        scheduled_at: '2026-06-28T09:00:00Z',
      };
      await enqueueTask(task);

      const response = await sendMessage({
        type: 'REJECT_TASK',
        taskId: 'reject-me',
      });
      expect(response.ok).toBe(true);

      // Verify task was removed from queue
      const queue = await getQueue();
      expect(queue).toHaveLength(0);

      // Wait for async report to fire
      await new Promise((r) => setTimeout(r, 50));

      // Verify fetch was called with rejection report
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'https://gorampit.com/api/extension/report',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('rejected_by_executor'),
        })
      );
    });

    it('returns ok even if task not found (no fetch called)', async () => {
      const response = await sendMessage({
        type: 'REJECT_TASK',
        taskId: 'nonexistent',
      });
      expect(response.ok).toBe(true);

      // No fetch should be made for a nonexistent task
      await new Promise((r) => setTimeout(r, 50));
      expect(globalThis.fetch).not.toHaveBeenCalled();
    });

    it('report body includes correct fields per design spec', async () => {
      storage['ramp_auth'] = {
        token: 'test-token',
        nodeId: 'node-123',
        rampUrl: 'https://gorampit.com',
      };

      const task = {
        task_id: 'reject-spec',
        idempotency_key: 'idem-spec',
        task_type: 'post_comment',
        priority: 'content',
        scheduled_at: '2026-06-28T09:00:00Z',
      };
      await enqueueTask(task);

      await sendMessage({
        type: 'REJECT_TASK',
        taskId: 'reject-spec',
      });

      await new Promise((r) => setTimeout(r, 50));

      const [url, options] = globalThis.fetch.mock.calls[0];
      const body = JSON.parse(options.body);

      expect(url).toBe('https://gorampit.com/api/extension/report');
      expect(body.task_id).toBe('reject-spec');
      expect(body.idempotency_key).toBe('idem-spec');
      expect(body.result_type).toBe('task_failed');
      expect(body.error_code).toBe('rejected_by_executor');
      expect(body.error_details).toContain('rejected');
    });
  });

  describe('Unknown message type', () => {
    it('returns false for unrecognized messages', () => {
      const sendResponse = vi.fn();
      const result = listener({ type: 'UNKNOWN' }, {}, sendResponse);
      expect(result).toBe(false);
      expect(sendResponse).not.toHaveBeenCalled();
    });

    it('returns false for null message', () => {
      const sendResponse = vi.fn();
      const result = listener(null, {}, sendResponse);
      expect(result).toBe(false);
    });

    it('returns false for message without type', () => {
      const sendResponse = vi.fn();
      const result = listener({ foo: 'bar' }, {}, sendResponse);
      expect(result).toBe(false);
    });
  });
});
