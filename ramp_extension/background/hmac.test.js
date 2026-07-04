/**
 * Tests for HMAC verifier module.
 *
 * Uses Node.js crypto to generate reference HMAC values that match
 * what the Python backend produces (hmac.new(secret, msg, sha256).hexdigest()).
 */

import { describe, it, expect } from 'vitest';
import { createHmac } from 'node:crypto';
import { verifyTaskHmac, computeHmacSha256, arrayBufferToHex } from './hmac.js';

// Helper: compute expected HMAC using Node.js crypto (matches Python backend)
function pythonHmac(secret, message) {
  return createHmac('sha256', secret).update(message).digest('hex');
}

describe('arrayBufferToHex', () => {
  it('converts empty buffer to empty string', () => {
    const buf = new ArrayBuffer(0);
    expect(arrayBufferToHex(buf)).toBe('');
  });

  it('converts known bytes to hex', () => {
    const arr = new Uint8Array([0x00, 0x0f, 0xff, 0xab]);
    expect(arrayBufferToHex(arr.buffer)).toBe('000fffab');
  });

  it('produces lowercase hex', () => {
    const arr = new Uint8Array([0xDE, 0xAD, 0xBE, 0xEF]);
    expect(arrayBufferToHex(arr.buffer)).toBe('deadbeef');
  });
});

describe('computeHmacSha256', () => {
  it('produces correct HMAC-SHA256 for simple input', async () => {
    const secret = 'test-secret';
    const message = 'hello:world';
    const expected = pythonHmac(secret, message);

    const result = await computeHmacSha256(secret, message);
    expect(result).toBe(expected);
  });

  it('matches Python backend format for task message', async () => {
    const secret = 'my-extension-hmac-secret';
    const message = 'abc-123:post_comment:Flaky_Finder_13:https://reddit.com/r/test/comments/xyz';
    const expected = pythonHmac(secret, message);

    const result = await computeHmacSha256(secret, message);
    expect(result).toBe(expected);
  });

  it('matches Python backend format for diagnostic probe', async () => {
    const secret = 'secret-key-456';
    const message = 'uuid-key:diagnostic_probe:TestUser:reddit_cqs';
    const expected = pythonHmac(secret, message);

    const result = await computeHmacSha256(secret, message);
    expect(result).toBe(expected);
  });

  it('handles empty message', async () => {
    const secret = 'key';
    const message = '';
    const expected = pythonHmac(secret, message);

    const result = await computeHmacSha256(secret, message);
    expect(result).toBe(expected);
  });

  it('handles unicode characters', async () => {
    const secret = 'key';
    const message = 'héllo:wörld:ñ:日本語';
    const expected = pythonHmac(secret, message);

    const result = await computeHmacSha256(secret, message);
    expect(result).toBe(expected);
  });
});

describe('verifyTaskHmac', () => {
  const secret = 'test-hmac-secret-key';

  function makeTask(overrides = {}) {
    const base = {
      idempotency_key: 'task-uuid-001',
      task_type: 'post_comment',
      avatar_username: 'CoolUser42',
      thread_url: 'https://reddit.com/r/sysadmin/comments/abc123/thread_title/',
      probe_type: null,
      task_hash: '', // will be computed below
    };
    const task = { ...base, ...overrides };

    // Compute correct hash if not explicitly set
    if (!overrides.task_hash) {
      const target = task.task_type === 'post_comment' ? task.thread_url : task.probe_type;
      const message = `${task.idempotency_key}:${task.task_type}:${task.avatar_username}:${target}`;
      task.task_hash = pythonHmac(secret, message);
    }

    return task;
  }

  it('accepts a valid post_comment task', async () => {
    const task = makeTask();
    const result = await verifyTaskHmac(task, secret);
    expect(result).toEqual({ valid: true });
  });

  it('accepts a valid diagnostic_probe task', async () => {
    const task = makeTask({
      task_type: 'diagnostic_probe',
      probe_type: 'reddit_cqs',
      thread_url: null,
    });
    const result = await verifyTaskHmac(task, secret);
    expect(result).toEqual({ valid: true });
  });

  it('rejects a task with tampered thread_url', async () => {
    const task = makeTask();
    task.thread_url = 'https://reddit.com/r/hacking/comments/evil/';
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('mismatch');
  });

  it('rejects a task with tampered comment_text (hash stays same, no data change matters)', async () => {
    // comment_text is NOT part of the HMAC message, so changing it doesn't affect hash
    // This test confirms HMAC only covers the specified fields
    const task = makeTask();
    task.comment_text = 'totally different comment';
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(true); // comment_text is not in HMAC
  });

  it('rejects a task with wrong secret', async () => {
    const task = makeTask();
    const result = await verifyTaskHmac(task, 'wrong-secret');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('mismatch');
  });

  it('rejects a task with tampered idempotency_key', async () => {
    const task = makeTask();
    task.idempotency_key = 'modified-key';
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(false);
  });

  it('rejects a task with tampered avatar_username', async () => {
    const task = makeTask();
    task.avatar_username = 'EvilUser';
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(false);
  });

  // Edge cases: missing fields
  it('returns error for null task', async () => {
    const result = await verifyTaskHmac(null, secret);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('not a valid object');
  });

  it('returns error for missing secret', async () => {
    const task = makeTask();
    const result = await verifyTaskHmac(task, '');
    expect(result.valid).toBe(false);
    expect(result.error).toContain('secret');
  });

  it('returns error for missing task_hash', async () => {
    const task = makeTask();
    task.task_hash = ''; // Override after makeTask computes the real hash
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('task_hash');
  });

  it('returns error for missing idempotency_key', async () => {
    const task = makeTask();
    task.idempotency_key = '';
    // Recompute hash with empty key to isolate the validation
    const result = await verifyTaskHmac({ ...task, idempotency_key: '' }, secret);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('idempotency_key');
  });

  it('returns error for missing task_type', async () => {
    const task = makeTask();
    task.task_type = '';
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('task_type');
  });

  it('returns error for missing avatar_username', async () => {
    const task = makeTask();
    task.avatar_username = '';
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('avatar_username');
  });

  it('returns error for unknown task_type', async () => {
    const task = makeTask({ task_hash: 'abc123' });
    task.task_type = 'unknown_action';
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(false);
    expect(result.error).toContain('unknown task_type');
  });

  it('handles post_comment with empty thread_url (uses empty string as target)', async () => {
    const task = makeTask({ thread_url: '' });
    // Recompute hash with empty target
    const message = `${task.idempotency_key}:post_comment:${task.avatar_username}:`;
    task.task_hash = pythonHmac(secret, message);
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(true);
  });

  it('handles diagnostic_probe with empty probe_type (uses empty string as target)', async () => {
    const task = makeTask({
      task_type: 'diagnostic_probe',
      probe_type: '',
      thread_url: null,
    });
    const message = `${task.idempotency_key}:diagnostic_probe:${task.avatar_username}:`;
    task.task_hash = pythonHmac(secret, message);
    const result = await verifyTaskHmac(task, secret);
    expect(result.valid).toBe(true);
  });
});
