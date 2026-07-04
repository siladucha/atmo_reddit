/**
 * Tests for popup/edit-task.js — Edit Before Approve module
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock chrome.runtime.sendMessage
const mockSendMessage = vi.fn();
const mockStorageGet = vi.fn();
const mockStorageSet = vi.fn();

globalThis.chrome = {
  runtime: { sendMessage: mockSendMessage },
  storage: {
    local: {
      get: mockStorageGet,
      set: mockStorageSet,
      remove: vi.fn(),
    },
  },
};

// Mock fetch for PATCH calls
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

// Mock getAuth — import after chrome mock is set up
vi.mock('../shared/auth.js', () => ({
  getAuth: vi.fn().mockResolvedValue({
    token: 'test-jwt-token',
    rampUrl: 'https://gorampit.com',
    nodeId: 'node-123',
  }),
}));

import { initEditForTask } from './edit-task.js';

describe('edit-task', () => {
  let taskCard;
  let task;
  let onSaved;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendMessage.mockResolvedValue({ ok: true });

    task = {
      task_id: 'task-abc-123',
      comment_text: 'Original comment text here',
      subreddit: 'sysadmin',
      thread_title: 'Test thread',
    };

    onSaved = vi.fn();

    // Build a minimal task card DOM
    taskCard = document.createElement('div');
    taskCard.className = 'task-card';
    taskCard.innerHTML = `
      <div class="task-card__preview">Original comment text here</div>
      <div class="task-card__actions">
        <button class="edit-btn">Edit</button>
        <button class="task-card__btn task-card__btn--prepare">Prepare</button>
      </div>
    `;
    document.body.appendChild(taskCard);
  });

  it('should add click listener to .edit-btn', () => {
    initEditForTask(taskCard, task, onSaved);
    const editBtn = taskCard.querySelector('.edit-btn');
    expect(editBtn).not.toBeNull();
  });

  it('should open textarea when edit button is clicked', () => {
    initEditForTask(taskCard, task, onSaved);
    const editBtn = taskCard.querySelector('.edit-btn');
    editBtn.click();

    const textarea = taskCard.querySelector('.edit-area__textarea');
    expect(textarea).not.toBeNull();
    expect(textarea.value).toBe('Original comment text here');
  });

  it('should hide preview when editing', () => {
    initEditForTask(taskCard, task, onSaved);
    taskCard.querySelector('.edit-btn').click();

    const preview = taskCard.querySelector('.task-card__preview');
    expect(preview.style.display).toBe('none');
  });

  it('should show Save and Cancel buttons', () => {
    initEditForTask(taskCard, task, onSaved);
    taskCard.querySelector('.edit-btn').click();

    const saveBtn = taskCard.querySelector('.edit-area__btn--save');
    const cancelBtn = taskCard.querySelector('.edit-area__btn--cancel');
    expect(saveBtn).not.toBeNull();
    expect(cancelBtn).not.toBeNull();
    expect(saveBtn.textContent).toBe('Save');
    expect(cancelBtn.textContent).toBe('Cancel');
  });

  it('should not open multiple editors', () => {
    initEditForTask(taskCard, task, onSaved);
    taskCard.querySelector('.edit-btn').click();
    taskCard.querySelector('.edit-btn').click(); // second click

    const textareas = taskCard.querySelectorAll('.edit-area__textarea');
    expect(textareas.length).toBe(1);
  });

  it('should collapse editor on cancel without saving', () => {
    initEditForTask(taskCard, task, onSaved);
    taskCard.querySelector('.edit-btn').click();

    const textarea = taskCard.querySelector('.edit-area__textarea');
    textarea.value = 'Modified text';

    const cancelBtn = taskCard.querySelector('.edit-area__btn--cancel');
    cancelBtn.click();

    // Editor should be gone
    expect(taskCard.querySelector('.edit-area')).toBeNull();
    // Preview should be visible again with original text
    const preview = taskCard.querySelector('.task-card__preview');
    expect(preview.style.display).toBe('');
    // onSaved should NOT have been called
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('should call PATCH and update on save success', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        id: 'task-abc-123',
        text: 'Edited comment text',
        version: 1,
        updated_at: '2026-07-02T10:00:00Z',
      }),
    });

    initEditForTask(taskCard, task, onSaved);
    taskCard.querySelector('.edit-btn').click();

    const textarea = taskCard.querySelector('.edit-area__textarea');
    textarea.value = 'Edited comment text';

    const saveBtn = taskCard.querySelector('.edit-area__btn--save');
    saveBtn.click();

    // Wait for async operations
    await vi.waitFor(() => {
      expect(onSaved).toHaveBeenCalledTimes(1);
    });

    // Verify PATCH was called correctly
    expect(mockFetch).toHaveBeenCalledWith(
      'https://gorampit.com/api/extension/tasks/task-abc-123',
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({
          'Authorization': 'Bearer test-jwt-token',
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ text: 'Edited comment text' }),
      })
    );

    // Verify service worker message was sent
    expect(mockSendMessage).toHaveBeenCalledWith({
      type: 'UPDATE_TASK_TEXT',
      taskId: 'task-abc-123',
      newText: 'Edited comment text',
    });

    // Verify local task was updated
    expect(task.comment_text).toBe('Edited comment text');

    // Editor should be collapsed
    expect(taskCard.querySelector('.edit-area')).toBeNull();
  });

  it('should show error on save failure', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ detail: 'Cannot edit finalized task' }),
    });

    initEditForTask(taskCard, task, onSaved);
    taskCard.querySelector('.edit-btn').click();

    const textarea = taskCard.querySelector('.edit-area__textarea');
    textarea.value = 'Some edit';

    const saveBtn = taskCard.querySelector('.edit-area__btn--save');
    saveBtn.click();

    // Wait for async operations
    await vi.waitFor(() => {
      const errorEl = taskCard.querySelector('.edit-area__error');
      expect(errorEl.style.display).toBe('block');
    });

    const errorEl = taskCard.querySelector('.edit-area__error');
    expect(errorEl.textContent).toBe('Cannot edit finalized task');

    // Save button should be re-enabled
    expect(saveBtn.disabled).toBe(false);
    expect(saveBtn.textContent).toBe('Save');

    // onSaved should NOT have been called
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('should show error when text is empty', () => {
    initEditForTask(taskCard, task, onSaved);
    taskCard.querySelector('.edit-btn').click();

    const textarea = taskCard.querySelector('.edit-area__textarea');
    textarea.value = '   '; // whitespace only

    const saveBtn = taskCard.querySelector('.edit-area__btn--save');
    saveBtn.click();

    const errorEl = taskCard.querySelector('.edit-area__error');
    expect(errorEl.style.display).toBe('block');
    expect(errorEl.textContent).toBe('Comment text cannot be empty');

    // Should not have made a fetch call
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('should do nothing if no .edit-btn exists', () => {
    const cardWithoutBtn = document.createElement('div');
    cardWithoutBtn.innerHTML = '<div class="task-card__preview">text</div>';

    // Should not throw
    initEditForTask(cardWithoutBtn, task, onSaved);
  });
});
