/**
 * RAMP Extension — Edit Before Approve
 *
 * Handles inline editing of task comment text before approval.
 * When executor clicks Edit, an inline textarea expands pre-filled
 * with the current task text. Save sends PATCH to backend,
 * updates local state, and collapses back to preview.
 */

import { getAuth } from '../shared/auth.js';

/**
 * Send PATCH to backend to update task text.
 * @param {string} taskId - UUID of the task
 * @param {string} newText - The edited comment text
 * @returns {Promise<{id: string, text: string, version: number, updated_at: string}>}
 */
async function patchTaskText(taskId, newText) {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) throw new Error('Not authenticated');

  const resp = await fetch(`${auth.rampUrl}/api/extension/tasks/${taskId}`, {
    method: 'PATCH',
    headers: {
      'Authorization': `Bearer ${auth.token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ text: newText }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }

  return resp.json();
}

/**
 * Initialize edit functionality for a task card.
 * Inserts inline textarea when Edit is clicked, handles save.
 *
 * @param {HTMLElement} taskCard - The task card DOM element
 * @param {Object} task - Task data from chrome.storage.local
 * @param {Function} onSaved - Callback when text is successfully saved (receives updated task)
 */
export function initEditForTask(taskCard, task, onSaved) {
  const editBtn = taskCard.querySelector('.edit-btn');
  if (!editBtn) return;

  editBtn.addEventListener('click', () => {
    // Prevent opening multiple editors
    if (taskCard.querySelector('.edit-area')) return;
    openEditor(taskCard, task, onSaved);
  });
}

/**
 * Open the inline editor for a task card.
 * @param {HTMLElement} taskCard
 * @param {Object} task
 * @param {Function} onSaved
 */
function openEditor(taskCard, task, onSaved) {
  // Find the text preview element to hide
  const previewEl = taskCard.querySelector('.task-card__preview');
  if (previewEl) previewEl.style.display = 'none';

  // Create the edit area container
  const editArea = document.createElement('div');
  editArea.className = 'edit-area';

  // Create textarea pre-filled with current text
  const textarea = document.createElement('textarea');
  textarea.className = 'edit-area__textarea';
  textarea.value = task.comment_text || '';
  textarea.rows = 4;
  // Auto-size to fit content
  textarea.style.height = 'auto';
  textarea.style.height = Math.max(60, textarea.scrollHeight) + 'px';

  // Resize on input
  textarea.addEventListener('input', () => {
    textarea.style.height = 'auto';
    textarea.style.height = Math.max(60, textarea.scrollHeight) + 'px';
  });

  // Create button row
  const btnRow = document.createElement('div');
  btnRow.className = 'edit-area__buttons';

  const saveBtn = document.createElement('button');
  saveBtn.className = 'edit-area__btn edit-area__btn--save';
  saveBtn.textContent = 'Save';

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'edit-area__btn edit-area__btn--cancel';
  cancelBtn.textContent = 'Cancel';

  // Error message element (hidden by default)
  const errorEl = document.createElement('div');
  errorEl.className = 'edit-area__error';
  errorEl.style.display = 'none';

  btnRow.appendChild(saveBtn);
  btnRow.appendChild(cancelBtn);

  editArea.appendChild(textarea);
  editArea.appendChild(btnRow);
  editArea.appendChild(errorEl);

  // Insert after the preview element (or at end of card content area)
  if (previewEl) {
    previewEl.parentNode.insertBefore(editArea, previewEl.nextSibling);
  } else {
    taskCard.appendChild(editArea);
  }

  // Auto-focus the textarea
  textarea.focus();

  // Handle Save
  saveBtn.addEventListener('click', async () => {
    const newText = textarea.value.trim();
    if (!newText) {
      errorEl.textContent = 'Comment text cannot be empty';
      errorEl.style.display = 'block';
      return;
    }

    // Disable save button and show loading state
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    cancelBtn.disabled = true;
    errorEl.style.display = 'none';

    try {
      const updated = await patchTaskText(task.task_id, newText);

      // Update local task data
      task.comment_text = updated.text;

      // Notify service worker to update task in local queue
      chrome.runtime.sendMessage({
        type: 'UPDATE_TASK_TEXT',
        taskId: task.task_id,
        newText: updated.text,
      });

      // Call the onSaved callback with updated task
      if (onSaved) onSaved(task);

      // Collapse editor back to text preview
      closeEditor(taskCard, editArea, task);
    } catch (err) {
      // Show error, re-enable save
      errorEl.textContent = err.message || 'Failed to save';
      errorEl.style.display = 'block';
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      cancelBtn.disabled = false;
    }
  });

  // Handle Cancel
  cancelBtn.addEventListener('click', () => {
    closeEditor(taskCard, editArea, task);
  });
}

/**
 * Close the editor and restore the text preview.
 * @param {HTMLElement} taskCard
 * @param {HTMLElement} editArea
 * @param {Object} task
 */
function closeEditor(taskCard, editArea, task) {
  // Remove the edit area
  editArea.remove();

  // Show the preview element again with updated text
  const previewEl = taskCard.querySelector('.task-card__preview');
  if (previewEl) {
    previewEl.textContent = truncate(task.comment_text || '', 80);
    previewEl.style.display = '';
  }
}

/**
 * Truncate text to max length with ellipsis.
 * @param {string} str
 * @param {number} max
 * @returns {string}
 */
function truncate(str, max) {
  return str.length <= max ? str : str.slice(0, max).trimEnd() + '…';
}
