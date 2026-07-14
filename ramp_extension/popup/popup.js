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
  document.getElementById('btn-approve-all-drafts')?.addEventListener('click', handleApproveAllDrafts);

  await refreshAll();
  setInterval(refreshAll, REFRESH_INTERVAL);
}

async function refreshAll() {
  await detectAccount();
  await checkHealth();
  await fetchPendingDrafts();
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
    return;
  }

  // Check if Reddit tab is available (query active Reddit tabs)
  let hasRedditTab = false;
  try {
    const tabs = await chrome.tabs.query({ url: ['*://*.reddit.com/*'] });
    hasRedditTab = tabs && tabs.length > 0;
  } catch {}

  if (!hasRedditTab) {
    dot.className = 'popup__status-dot popup__status-dot--warning';
    stText.textContent = 'Open Reddit';
  } else {
    // Check session validity from health monitor
    const result = await chrome.storage.local.get('ramp_health');
    const health = result?.ramp_health;
    if (health && health.reddit_session_valid === false) {
      dot.className = 'popup__status-dot popup__status-dot--warning';
      stText.textContent = 'Session expired';
    } else {
      dot.className = 'popup__status-dot popup__status-dot--connected';
      stText.textContent = 'Connected';
    }
  }
}

async function checkHealth() {
  const banner = document.getElementById('health-warning');
  const maintenanceBanner = document.getElementById('maintenance-warning');
  const updateBanner = document.getElementById('update-banner');
  try {
    const result = await chrome.storage.local.get(['ramp_health', 'ramp_server_status', 'ramp_update_available', 'ramp_latest_version', 'ramp_download_url']);
    const health = result?.ramp_health;
    const serverStatus = result?.ramp_server_status;

    banner.style.display = health?.dom_health === 'broken' ? 'block' : 'none';
    maintenanceBanner.style.display = serverStatus === 'maintenance' ? 'block' : 'none';

    // Update available banner
    if (result?.ramp_update_available) {
      updateBanner.style.display = 'block';
      document.getElementById('update-version').textContent = result.ramp_latest_version || '';
      const link = document.getElementById('update-link');
      link.href = result.ramp_download_url || 'https://gorampit.com/static/extension/index.html';
    } else {
      updateBanner.style.display = 'none';
    }

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
    updateBanner.style.display = 'none';
  }
}

// ─── Pending Drafts (Review before they become tasks) ───────────────────────

async function fetchPendingDrafts() {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  let username = auth.avatarUsername || '';
  if (!username) {
    const stored = await chrome.storage.local.get('activeRedditUsername');
    username = stored?.activeRedditUsername || '';
  }
  if (!username) return;

  const reviewSection = document.getElementById('review-section');
  const reviewList = document.getElementById('review-list');
  const reviewCount = document.getElementById('review-count');

  try {
    const resp = await fetch(
      `${auth.rampUrl}/api/extension/dashboard?avatar_username=${encodeURIComponent(username)}`,
      { headers: { 'Authorization': `Bearer ${auth.token}` } }
    );
    if (!resp.ok) {
      reviewSection.style.display = 'none';
      return;
    }
    const data = await resp.json();
    const drafts = data.pending_drafts || [];

    if (drafts.length === 0) {
      reviewSection.style.display = 'none';
      return;
    }

    reviewSection.style.display = '';
    reviewCount.textContent = drafts.length;
    reviewList.innerHTML = drafts.map(d => renderDraftCard(d)).join('');
    bindDraftActions(reviewList);

    // Update badge: drafts + pending tasks
    const currentBadge = parseInt(document.getElementById('pending-count')?.textContent || '0');
    const total = drafts.length + currentBadge;
    chrome.action.setBadgeText({ text: total > 0 ? String(total) : '' });
    chrome.action.setBadgeBackgroundColor({ color: '#f59e0b' });

  } catch {
    reviewSection.style.display = 'none';
  }
}

function renderDraftCard(draft) {
  const sub = draft.subreddit || '';
  const title = truncate(draft.thread_title || '', 50);
  const text = truncate(draft.text_preview || '', 120);
  const time = draft.created_at ? formatTime(draft.created_at) : '';
  const threadUrl = draft.thread_url || '';

  // Build clickable link for subreddit + title
  const subHtml = threadUrl
    ? `<a href="${esc(threadUrl)}" target="_blank" class="task-card__sub task-card__link">r/${esc(sub)}</a>`
    : `<span class="task-card__sub">r/${esc(sub)}</span>`;
  const titleHtml = title
    ? (threadUrl
      ? `<a href="${esc(threadUrl)}" target="_blank" class="task-card__title task-card__link">${esc(title)}</a>`
      : `<span class="task-card__title">${esc(title)}</span>`)
    : '';

  return `
    <div class="task-card task-card--draft" data-draft-id="${draft.id}">
      <div class="task-card__row">
        <div class="task-card__meta">
          ${subHtml}
          ${titleHtml}
          ${time ? `<span class="task-card__time">${time}</span>` : ''}
        </div>
        <div class="task-card__actions">
          <button class="btn-sm btn-sm--approve" data-action="approve-draft" data-id="${draft.id}" title="Approve">✓</button>
          <button class="btn-sm btn-sm--skip" data-action="reject-draft" data-id="${draft.id}" title="Reject">✗</button>
        </div>
      </div>
      <div class="task-card__text">"${esc(text)}"</div>
    </div>
  `;
}

function bindDraftActions(container) {
  container.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const id = btn.dataset.id;
    const auth = await getAuth();
    if (!auth?.token || !auth?.rampUrl) return;

    btn.disabled = true;

    try {
      if (action === 'approve-draft') {
        await fetch(`${auth.rampUrl}/api/extension/drafts/${id}/review`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${auth.token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ action: 'approve' }),
        });
      } else if (action === 'reject-draft') {
        await fetch(`${auth.rampUrl}/api/extension/drafts/${id}/review`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${auth.token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ action: 'reject' }),
        });
      }
    } catch {}

    await refreshAll();
  });
}

async function handleApproveAllDrafts() {
  const btn = document.getElementById('btn-approve-all-drafts');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  const auth = await getAuth();
  if (auth?.token && auth?.rampUrl) {
    let username = auth.avatarUsername || '';
    if (!username) {
      const stored = await chrome.storage.local.get('activeRedditUsername');
      username = stored?.activeRedditUsername || '';
    }
    if (username) {
      try {
        await fetch(
          `${auth.rampUrl}/api/extension/drafts/approve-all?avatar_username=${encodeURIComponent(username)}`,
          {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${auth.token}` },
          }
        );
      } catch {}
    }
  }

  if (btn) { btn.disabled = false; btn.textContent = 'Approve All'; }
  await refreshAll();
}

// ─── Task Queue ─────────────────────────────────────────────────────────────

async function fetchQueueAndRender() {
  let tasks = [];
  try {
    const response = await chrome.runtime.sendMessage({ type: 'GET_QUEUE' });
    tasks = response?.tasks || [];
  } catch {}

  // Also load today_history from storage (server-side full picture)
  let todayHistory = [];
  try {
    const stored = await chrome.storage.local.get('ramp_today_history');
    todayHistory = stored?.ramp_today_history || [];
  } catch {}

  // Merge: use today_history as primary source, overlay local queue status for active tasks
  const localMap = new Map(tasks.map(t => [t.task_id, t]));
  const allTasks = todayHistory.map(h => {
    const local = localMap.get(h.task_id);
    if (local) {
      // Local queue has more current status (approved, executing, completed, failed)
      return { ...h, ...local, _source: 'local' };
    }
    return { ...h, _source: 'server' };
  });
  // Add any local-only tasks not in server history
  for (const t of tasks) {
    if (!todayHistory.find(h => h.task_id === t.task_id)) {
      allTasks.push({ ...t, _source: 'local_only' });
    }
  }

  // Categorize
  // EPG tasks (has_epg_slot=true OR has scheduled_at) that are generated = already approved via draft review
  // Immediate tasks (no epg slot, no scheduled_at) = need human approval in extension
  const pending = allTasks.filter(t =>
    t.status === 'pending' ||
    (!t.status && t.lifecycle === 'CREATED') ||
    // Immediate tasks (no EPG slot, no schedule) need human approval
    (t.status === 'generated' && !t.has_epg_slot && !t.scheduled_at && (t.lifecycle === 'ASSIGNED' || t.lifecycle === 'CREATED'))
  );
  const approved = allTasks.filter(t =>
    t.status === 'approved' || t.status === 'executing' ||
    // EPG tasks already approved via draft review — waiting for execution time
    (t.status === 'generated' && (t.has_epg_slot || t.scheduled_at) && (t.lifecycle === 'ASSIGNED' || t.lifecycle === 'CREATED'))
  );
  const completed = allTasks.filter(t =>
    t.status === 'completed' || t.lifecycle === 'REPORTED' || t.lifecycle === 'FINALIZED'
  );
  const failed = allTasks.filter(t => t.status === 'failed' || (t.lifecycle === 'EXPIRED' && t.status !== 'cancelled'));
  const cancelled = allTasks.filter(t => t.status === 'cancelled');

  // Stats — Waiting and Missed computed from allTasks (consistent with rendered list)
  // Posted is overridden by fetchDashboardStats (more accurate — includes email-posted)
  document.getElementById('stat-posted').textContent = completed.length;
  document.getElementById('stat-queued').textContent = pending.length + approved.length;
  document.getElementById('stat-failed').textContent = failed.length + cancelled.length;
  const failedValue = document.getElementById('stat-failed');
  failedValue.className = (failed.length + cancelled.length) > 0
    ? 'today-stat__value today-stat__value--warn'
    : 'today-stat__value';

  // Scheduled list (approved tasks — executing soon)
  const scheduledList = document.getElementById('scheduled-list');
  if (approved.length === 0) {
    scheduledList.innerHTML = '<p class="empty-text">No tasks scheduled yet</p>';
  } else {
    scheduledList.innerHTML = approved.map(t => renderScheduledCard(t)).join('');
    bindScheduledActions(scheduledList);
  }

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
  const allFailed = [...failed, ...cancelled];
  if (allFailed.length > 0) {
    failedSection.style.display = '';
    failedList.innerHTML = allFailed.map(t => renderFailedCard(t)).join('');
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

    // Plan = EPG slots today — show only active (not skipped)
    const planEl = document.getElementById('stat-plan');
    if (planEl) {
      const summary = data.epg_summary;
      if (summary) {
        planEl.textContent = summary.active + summary.posted;
      } else {
        planEl.textContent = data.total_planned || 0;
      }
    }

    // Posted = from dashboard (includes email-posted + extension-posted)
    document.getElementById('stat-posted').textContent = data.stats?.posts_today || 0;

    // Render EPG slots in scheduled-list if no execution tasks shown there
    const scheduledList = document.getElementById('scheduled-list');
    const epgSlots = data.epg || [];
    const activeSlots = epgSlots.filter(s => s.status !== 'skipped' && s.status !== 'posted');
    if (scheduledList && activeSlots.length > 0 && scheduledList.querySelector('.empty-text')) {
      scheduledList.innerHTML = activeSlots.map(s => {
        const time = s.scheduled_at ? formatTime(s.scheduled_at) : '';
        const sub = s.subreddit || '';
        const statusLabel = s.status === 'planned' ? '⏳ generating'
          : s.status === 'generated' ? '📝 needs review'
          : s.status === 'approved' ? '✓ ready'
          : s.status;
        return `<div class="task-card task-card--epg">
          <div class="task-card__row">
            <div class="task-card__meta">
              ${time ? `<span class="task-card__time">${time}</span>` : ''}
              <span class="task-card__sub">r/${esc(sub)}</span>
            </div>
            <span class="task-card__status">${statusLabel}</span>
          </div>
        </div>`;
      }).join('');
    }
  } catch {}
}

// ─── Card Renderers ─────────────────────────────────────────────────────────

function renderPendingCard(task) {
  const time = formatTime(task.scheduled_at);
  const sub = task.subreddit || '';
  const text = truncate(task.comment_text || '', 100);
  const avatar = task.avatar_username ? `u/${task.avatar_username}` : '';
  const threadUrl = task.thread_url || '';

  // Check if task is overdue (scheduled_at in the past)
  let overdue = false;
  if (task.scheduled_at) {
    const scheduledTime = new Date(task.scheduled_at).getTime();
    overdue = scheduledTime < Date.now();
  }

  const timeClass = overdue ? 'task-card__time task-card__time--overdue' : 'task-card__time';
  const overdueLabel = overdue ? ' ⚠️' : '';

  // Build clickable subreddit link
  const subHtml = threadUrl
    ? `<a href="${esc(threadUrl)}" target="_blank" class="task-card__sub task-card__link">r/${esc(sub)}</a>`
    : `<span class="task-card__sub">r/${esc(sub)}</span>`;

  return `
    <div class="task-card" data-id="${task.task_id}">
      <div class="task-card__row">
        <div class="task-card__meta">
          <span class="${timeClass}">${time}${overdueLabel}</span>
          ${subHtml}
          ${avatar ? `<span class="task-card__avatar">${esc(avatar)}</span>` : ''}
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

function renderScheduledCard(task) {
  const time = formatTime(task.scheduled_at);
  const sub = task.subreddit || '';
  const text = truncate(task.comment_text || '', 80);
  const status = task.status === 'executing' ? '⏳' : '🕐';
  const threadUrl = task.thread_url || '';

  const subHtml = threadUrl
    ? `<a href="${esc(threadUrl)}" target="_blank" class="task-card__sub task-card__link">r/${esc(sub)}</a>`
    : `<span class="task-card__sub">r/${esc(sub)}</span>`;

  return `
    <div class="task-card task-card--scheduled" data-id="${task.task_id}">
      <div class="task-card__row">
        <div class="task-card__meta">
          <span class="task-card__time">${status} ${time}</span>
          ${subHtml}
        </div>
        <div class="task-card__actions">
          <button class="btn-sm btn-sm--skip" data-action="cancel-scheduled" data-id="${task.task_id}" title="Cancel this task">✗</button>
        </div>
      </div>
      <div class="task-card__text">"${esc(text)}"</div>
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

  // Determine error message based on status
  let error;
  let icon;
  if (task.status === 'cancelled') {
    error = task.lifecycle === 'EXPIRED' ? 'Expired (overdue)' : 'Cancelled';
    icon = '⊘';
  } else {
    error = task.error_details || task.error_code || 'Failed';
    icon = '❌';
  }

  return `
    <div class="task-card task-card--failed" data-id="${task.task_id}">
      <div class="task-card__row">
        <div class="task-card__meta">
          <span class="task-card__time">${icon} ${time}</span>
          <span class="task-card__sub">r/${esc(sub)}</span>
        </div>
        <div class="task-card__actions">
          ${task.status !== 'cancelled' ? `<button class="btn-sm btn-sm--retry" data-action="retry" data-id="${task.task_id}">Retry</button>` : ''}
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

function bindScheduledActions(container) {
  container.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const id = btn.dataset.id;

    if (action === 'cancel-scheduled') {
      if (!confirm('Cancel this scheduled task?')) return;
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
