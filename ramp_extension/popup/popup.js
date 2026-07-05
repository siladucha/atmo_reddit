/**
 * RAMP Extension — Popup v2 (Clean Executor UI)
 *
 * Three things the executor cares about:
 * 1. Is everything OK? (status)
 * 2. What do I need to do? (pending tasks)
 * 3. What happened? (done/failed)
 *
 * Auto-refreshes every 30s.
 */

import { isAuthenticated, getAuth } from '../shared/auth.js';

const REFRESH_INTERVAL = 30_000;

async function init() {
  const authenticated = await isAuthenticated();
  if (!authenticated) {
    window.location.href = 'onboarding.html';
    return;
  }

  document.getElementById('btn-approve-all')?.addEventListener('click', handleApproveAll);

  await refreshAll();
  setInterval(refreshAll, REFRESH_INTERVAL);
}

async function refreshAll() {
  await detectAccount();
  await checkHealth();
  await fetchQueueAndRender();
  await fetchDashboardStats();
  updateTimestamp();
}

// ─── Account & Status ───────────────────────────────────────────────────────

async function detectAccount() {
  const el = document.getElementById('account-name');
  const dot = document.getElementById('status-dot');
  const stText = document.getElementById('status-text');

  const auth = await getAuth();
  const hasAuth = auth?.token && auth?.rampUrl;

  // Try stored username
  let username = auth?.avatarUsername || null;
  if (!username) {
    const stored = await chrome.storage.local.get('activeRedditUsername');
    username = stored?.activeRedditUsername || null;
  }

  el.textContent = username ? `u/${username}` : 'Not connected';

  if (!hasAuth) {
    dot.className = 'popup__status-dot popup__status-dot--disconnected';
    stText.textContent = 'Offline';
  } else {
    dot.className = 'popup__status-dot popup__status-dot--connected';
    stText.textContent = 'Connected';
  }
}

async function checkHealth() {
  const banner = document.getElementById('health-warning');
  const maintenanceBanner = document.getElementById('maintenance-warning');
  try {
    const result = await chrome.storage.local.get(['ramp_health', 'ramp_server_status']);
    const health = result?.ramp_health;
    const serverStatus = result?.ramp_server_status;

    banner.style.display = health?.dom_health === 'broken' ? 'block' : 'none';
    maintenanceBanner.style.display = serverStatus === 'maintenance' ? 'block' : 'none';

    // Update connection status dot
    const dot = document.getElementById('status-dot');
    const stText = document.getElementById('status-text');
    if (serverStatus === 'maintenance') {
      dot.className = 'popup__status-dot popup__status-dot--warning';
      stText.textContent = 'Updating...';
    }
  } catch {
    banner.style.display = 'none';
    maintenanceBanner.style.display = 'none';
  }
}

// ─── Task Queue ─────────────────────────────────────────────────────────────

async function fetchQueueAndRender() {
  let tasks = [];
  try {
    const response = await chrome.runtime.sendMessage({ type: 'GET_QUEUE' });
    tasks = response?.tasks || [];
  } catch {}

  const pending = tasks.filter(t => !t.status || t.status === 'pending');
  const approved = tasks.filter(t => t.status === 'approved' || t.status === 'executing');
  const completed = tasks.filter(t => t.status === 'completed');
  const failed = tasks.filter(t => t.status === 'failed');

  // Stats
  document.getElementById('stat-posted').textContent = completed.length;
  document.getElementById('stat-queued').textContent = approved.length;
  document.getElementById('stat-failed').textContent = failed.length;
  const failedValue = document.getElementById('stat-failed');
  failedValue.className = failed.length > 0
    ? 'today-stat__value today-stat__value--warn'
    : 'today-stat__value';

  // Pending section
  const pendingList = document.getElementById('pending-list');
  const pendingCount = document.getElementById('pending-count');
  const approveBtn = document.getElementById('btn-approve-all');

  pendingCount.textContent = pending.length;
  pendingCount.style.display = pending.length > 0 ? '' : 'none';
  approveBtn.style.display = pending.length > 1 ? '' : 'none';

  if (pending.length === 0) {
    pendingList.innerHTML = '<p class="empty-text">Nothing to approve — you\'re all set 👍</p>';
  } else {
    pendingList.innerHTML = pending.map(t => renderPendingCard(t)).join('');
    bindPendingActions(pendingList);
  }

  // Done section
  const doneSection = document.getElementById('done-section');
  const doneList = document.getElementById('done-list');
  if (completed.length > 0) {
    doneSection.style.display = '';
    doneList.innerHTML = completed.map(t => renderDoneCard(t)).join('');
  } else {
    doneSection.style.display = 'none';
  }

  // Failed section
  const failedSection = document.getElementById('failed-section');
  const failedList = document.getElementById('failed-list');
  if (failed.length > 0) {
    failedSection.style.display = '';
    failedList.innerHTML = failed.map(t => renderFailedCard(t)).join('');
    bindFailedActions(failedList);
  } else {
    failedSection.style.display = 'none';
  }

  // Badge
  chrome.action.setBadgeText({ text: pending.length > 0 ? String(pending.length) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#7c3aed' });
}

// ─── Dashboard stats (karma etc from backend) ───────────────────────────────

async function fetchDashboardStats() {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  let username = auth.avatarUsername || '';
  if (!username) {
    const stored = await chrome.storage.local.get('activeRedditUsername');
    username = stored?.activeRedditUsername || '';
  }
  if (!username) return;

  try {
    const resp = await fetch(
      `${auth.rampUrl}/api/extension/dashboard?avatar_username=${encodeURIComponent(username)}`,
      { headers: { 'Authorization': `Bearer ${auth.token}` } }
    );
    if (!resp.ok) return;
    const data = await resp.json();

    // Override posted count with backend data (more accurate — includes email-posted)
    const postsToday = data.stats?.posts_today || 0;
    const el = document.getElementById('stat-posted');
    if (el && postsToday > parseInt(el.textContent || '0')) {
      el.textContent = postsToday;
    }
  } catch {}
}

// ─── Card Renderers ─────────────────────────────────────────────────────────

function renderPendingCard(task) {
  const time = formatTime(task.scheduled_at);
  const sub = task.subreddit || '';
  const text = truncate(task.comment_text || '', 100);

  return `
    <div class="task-card" data-id="${task.task_id}">
      <div class="task-card__row">
        <div class="task-card__meta">
          <span class="task-card__time">${time}</span>
          <span class="task-card__sub">r/${esc(sub)}</span>
        </div>
        <div class="task-card__actions">
          <button class="btn-sm btn-sm--approve" data-action="approve" data-id="${task.task_id}">✓</button>
          <button class="btn-sm" data-action="edit" data-id="${task.task_id}">✎</button>
          <button class="btn-sm btn-sm--skip" data-action="skip" data-id="${task.task_id}">✗</button>
        </div>
      </div>
      <div class="task-card__text">"${esc(text)}"</div>
      <div class="task-card__edit" id="edit-${task.task_id}">
        <textarea class="task-card__textarea">${esc(task.comment_text || '')}</textarea>
        <div class="task-card__edit-actions">
          <button class="btn-sm" data-action="cancel-edit" data-id="${task.task_id}">Cancel</button>
          <button class="btn-sm btn-sm--approve" data-action="save-edit" data-id="${task.task_id}">Save & Approve</button>
        </div>
      </div>
    </div>
  `;
}

function renderDoneCard(task) {
  const time = formatTime(task.completed_at || task.scheduled_at);
  const sub = task.subreddit || '';
  const link = task.permalink
    ? `<a href="${esc(task.permalink)}" target="_blank" style="color: var(--green); font-size: 11px; text-decoration: none;">view →</a>`
    : '';

  return `
    <div class="task-card task-card--done">
      <div class="task-card__row">
        <div class="task-card__meta">
          <span class="task-card__time">✅ ${time}</span>
          <span class="task-card__sub">r/${esc(sub)}</span>
        </div>
        ${link}
      </div>
    </div>
  `;
}

function renderFailedCard(task) {
  const time = formatTime(task.failed_at || task.scheduled_at);
  const sub = task.subreddit || '';
  const error = task.error_details || task.error_code || 'Unknown error';

  return `
    <div class="task-card task-card--failed" data-id="${task.task_id}">
      <div class="task-card__row">
        <div class="task-card__meta">
          <span class="task-card__time">❌ ${time}</span>
          <span class="task-card__sub">r/${esc(sub)}</span>
        </div>
        <div class="task-card__actions">
          <button class="btn-sm btn-sm--retry" data-action="retry" data-id="${task.task_id}">Retry</button>
          <button class="btn-sm btn-sm--skip" data-action="dismiss" data-id="${task.task_id}">✗</button>
        </div>
      </div>
      <div class="task-card__error">${esc(truncate(error, 60))}</div>
    </div>
  `;
}

// ─── Action Handlers ────────────────────────────────────────────────────────

function bindPendingActions(container) {
  container.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const id = btn.dataset.id;

    switch (action) {
      case 'approve':
        await chrome.runtime.sendMessage({ type: 'APPROVE_TASK_V2', taskId: id });
        await fetchQueueAndRender();
        break;

      case 'skip':
        await chrome.runtime.sendMessage({ type: 'SKIP_TASK', taskId: id });
        await fetchQueueAndRender();
        break;

      case 'edit': {
        const editPanel = document.getElementById(`edit-${id}`);
        if (editPanel) editPanel.classList.toggle('open');
        break;
      }

      case 'cancel-edit': {
        const editPanel = document.getElementById(`edit-${id}`);
        if (editPanel) editPanel.classList.remove('open');
        break;
      }

      case 'save-edit': {
        const editPanel = document.getElementById(`edit-${id}`);
        const textarea = editPanel?.querySelector('textarea');
        if (textarea && textarea.value.trim()) {
          const newText = textarea.value.trim();
          // Save to backend
          const auth = await getAuth();
          if (auth?.token && auth?.rampUrl) {
            try {
              await fetch(`${auth.rampUrl}/api/extension/tasks/${id}`, {
                method: 'PATCH',
                headers: {
                  'Authorization': `Bearer ${auth.token}`,
                  'Content-Type': 'application/json',
                },
                body: JSON.stringify({ text: newText }),
              });
            } catch {}
          }
          // Update local queue
          await chrome.runtime.sendMessage({ type: 'UPDATE_TASK_TEXT', taskId: id, newText });
          // Approve
          await chrome.runtime.sendMessage({ type: 'APPROVE_TASK_V2', taskId: id });
          await fetchQueueAndRender();
        }
        break;
      }
    }
  });
}

function bindFailedActions(container) {
  container.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const id = btn.dataset.id;

    if (action === 'retry') {
      await chrome.runtime.sendMessage({ type: 'RETRY_TASK', taskId: id });
      await fetchQueueAndRender();
    } else if (action === 'dismiss') {
      await chrome.runtime.sendMessage({ type: 'SKIP_TASK', taskId: id });
      await fetchQueueAndRender();
    }
  });
}

async function handleApproveAll() {
  const btn = document.getElementById('btn-approve-all');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  await chrome.runtime.sendMessage({ type: 'APPROVE_ALL' });

  if (btn) { btn.disabled = false; btn.textContent = 'Approve All'; }
  await fetchQueueAndRender();
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatTime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function truncate(str, max) {
  return str.length <= max ? str : str.slice(0, max).trimEnd() + '…';
}

function esc(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

function updateTimestamp() {
  const el = document.getElementById('last-updated');
  if (el) el.textContent = `Updated ${formatTime(new Date().toISOString())}`;
}

document.addEventListener('DOMContentLoaded', init);
