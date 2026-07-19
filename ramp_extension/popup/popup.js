/**
 * RAMP Extension — Popup v3 (Action Center)
 *
 * Design principle: Approval inbox, not dashboard.
 * Executor answers one question: "Do I need to do anything right now?"
 *
 * Sections (priority order):
 * 1. Needs Approval — pending tasks requiring action
 * 2. Failed — problems requiring attention
 * 3. Today — schedule + minimal stats
 * 4. Done — collapsed history
 */

import { isAuthenticated, getAuth } from '../shared/auth.js';

const REFRESH_INTERVAL = 30_000;

async function init() {
  if (!(await isAuthenticated())) {
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
  await checkAlerts();
  await fetchPendingDrafts();
  await fetchQueueAndRender();
  updateTimestamp();
}

// ─── Account & Status ───────────────────────────────────────────────────────

async function detectAccount() {
  const el = document.getElementById('account-name');
  const dot = document.getElementById('status-dot');
  const stText = document.getElementById('status-text');

  const auth = await getAuth();
  const hasAuth = auth?.token && auth?.rampUrl;

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

  const tabs = await chrome.tabs.query({ url: ['*://*.reddit.com/*'] }).catch(() => []);
  if (!tabs || tabs.length === 0) {
    dot.className = 'popup__status-dot popup__status-dot--warning';
    stText.textContent = 'Open Reddit';
    return;
  }

  const result = await chrome.storage.local.get('ramp_health');
  if (result?.ramp_health?.reddit_session_valid === false) {
    dot.className = 'popup__status-dot popup__status-dot--warning';
    stText.textContent = 'Session expired';
  } else {
    dot.className = 'popup__status-dot popup__status-dot--connected';
    stText.textContent = 'Connected';
  }
}

async function checkAlerts() {
  const result = await chrome.storage.local.get([
    'ramp_health', 'ramp_server_status',
    'ramp_update_available', 'ramp_latest_version', 'ramp_download_url'
  ]);

  const healthBanner = document.getElementById('health-warning');
  const maintBanner = document.getElementById('maintenance-warning');
  const updateBanner = document.getElementById('update-banner');

  healthBanner.style.display = result?.ramp_health?.dom_health === 'broken' ? 'block' : 'none';
  maintBanner.style.display = result?.ramp_server_status === 'maintenance' ? 'block' : 'none';

  if (result?.ramp_update_available) {
    updateBanner.style.display = 'flex';
    document.getElementById('update-version').textContent = result.ramp_latest_version || '';
    document.getElementById('update-link').href = result.ramp_download_url || '#';
  } else {
    updateBanner.style.display = 'none';
  }
}

// ─── Draft Review ───────────────────────────────────────────────────────────

async function fetchPendingDrafts() {
  const auth = await getAuth();
  if (!auth?.token || !auth?.rampUrl) return;

  const username = await getActiveUsername(auth);
  if (!username) return;

  const reviewSection = document.getElementById('review-section');
  const reviewList = document.getElementById('review-list');
  const reviewCount = document.getElementById('review-count');

  try {
    const resp = await fetch(
      `${auth.rampUrl}/api/extension/dashboard?avatar_username=${encodeURIComponent(username)}`,
      { headers: { 'Authorization': `Bearer ${auth.token}` } }
    );
    if (!resp.ok) { reviewSection.style.display = 'none'; return; }

    const data = await resp.json();
    const drafts = data.pending_drafts || [];

    if (drafts.length === 0) { reviewSection.style.display = 'none'; return; }

    reviewSection.style.display = '';
    reviewCount.textContent = drafts.length;
    reviewList.innerHTML = drafts.map(renderDraftCard).join('');
    bindDraftActions(reviewList);
  } catch { reviewSection.style.display = 'none'; }
}

function renderDraftCard(draft) {
  const sub = draft.subreddit || '';
  const title = truncate(draft.thread_title || '', 40);
  const text = truncate(draft.text_preview || '', 100);
  const threadUrl = draft.thread_url || '';
  const typeIcon = '💬'; // Drafts are always comments

  const titleHtml = title
    ? (threadUrl
      ? `<a href="${esc(threadUrl)}" target="_blank" class="task-card__title">${esc(title)}</a>`
      : `<span class="task-card__title">${esc(title)}</span>`)
    : '';

  return `
    <div class="task-card task-card--draft" data-draft-id="${draft.id}">
      <div class="task-card__row">
        <div class="task-card__info">
          <div class="task-card__top">
            <span class="task-card__type">${typeIcon}</span>
            <span class="task-card__sub">r/${esc(sub)}</span>
          </div>
          ${titleHtml}
          <div class="task-card__preview">${esc(text)}</div>
        </div>
        <div class="task-card__actions">
          <button class="btn-sm btn-sm--approve" data-action="approve-draft" data-id="${draft.id}">✓</button>
          <button class="btn-sm btn-sm--skip" data-action="reject-draft" data-id="${draft.id}">✗</button>
        </div>
      </div>
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
      const act = action === 'approve-draft' ? 'approve' : 'reject';
      await fetch(`${auth.rampUrl}/api/extension/drafts/${id}/review`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${auth.token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: act }),
      });
    } catch {}
    await refreshAll();
  });
}

async function handleApproveAllDrafts() {
  const btn = document.getElementById('btn-approve-all-drafts');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  const auth = await getAuth();
  const username = await getActiveUsername(auth);
  if (auth?.token && auth?.rampUrl && username) {
    try {
      await fetch(
        `${auth.rampUrl}/api/extension/drafts/approve-all?avatar_username=${encodeURIComponent(username)}`,
        { method: 'POST', headers: { 'Authorization': `Bearer ${auth.token}` } }
      );
    } catch {}
  }

  if (btn) { btn.disabled = false; btn.textContent = 'Approve All'; }
  await refreshAll();
}

// ─── Task Queue ─────────────────────────────────────────────────────────────

async function fetchQueueAndRender() {
  let localTasks = [];
  try {
    const resp = await chrome.runtime.sendMessage({ type: 'GET_QUEUE' });
    localTasks = resp?.tasks || [];
  } catch {}

  // Fetch today_history directly from server (don't rely on stale cache)
  let todayHistory = [];
  try {
    const auth = await getAuth();
    if (auth?.token && auth?.rampUrl && auth?.nodeId) {
      const resp = await fetch(
        `${auth.rampUrl}/api/extension/tasks?execution_node_id=${encodeURIComponent(auth.nodeId)}`,
        { headers: { 'Authorization': `Bearer ${auth.token}` } }
      );
      if (resp.ok) {
        const data = await resp.json();
        todayHistory = data.today_history || [];
        console.log('[RAMP] today_history:', todayHistory.length, 'active tasks:', (data.tasks||[]).length);
        await chrome.storage.local.set({ ramp_today_history: todayHistory });
        if (data.tasks?.length > 0) {
          chrome.runtime.sendMessage({ type: 'TASKS_FROM_POPUP', tasks: data.tasks }).catch(() => {});
        }
      } else {
        console.warn('[RAMP] /tasks failed:', resp.status);
      }
    } else {
      console.warn('[RAMP] no auth/nodeId', !!auth?.token, !!auth?.rampUrl, !!auth?.nodeId);
    }
  } catch (err) {
    console.warn('[RAMP] fetch error:', err.message);
  }

  // Fallback to cached history if direct fetch failed
  if (todayHistory.length === 0) {
    try {
      const stored = await chrome.storage.local.get('ramp_today_history');
      todayHistory = stored?.ramp_today_history || [];
    } catch {}
  }

  // Merge: local queue overrides server history for active tasks
  const localMap = new Map(localTasks.map(t => [t.task_id, t]));
  const allTasks = todayHistory.map(h => {
    const local = localMap.get(h.task_id);
    return local ? { ...h, ...local } : h;
  });
  for (const t of localTasks) {
    if (!todayHistory.find(h => h.task_id === t.task_id)) allTasks.push(t);
  }

  // Filter out cancelled/skipped tasks — they should not appear in any category
  const activeTasks = allTasks.filter(t =>
    t.status !== 'cancelled' && t.status !== 'skipped'
  );

  // Categorize
  const pending = activeTasks.filter(t =>
    t.status === 'pending' ||
    (!t.status && t.lifecycle === 'CREATED') ||
    (t.status === 'generated' && !t.has_epg_slot && !t.scheduled_at)
  );
  const scheduled = activeTasks.filter(t =>
    t.status === 'approved' || t.status === 'executing' ||
    (t.status === 'generated' && (t.has_epg_slot || t.scheduled_at))
  );
  const completed = activeTasks.filter(t =>
    t.status === 'completed' || t.lifecycle === 'REPORTED' || t.lifecycle === 'FINALIZED'
  );
  const failed = activeTasks.filter(t =>
    (t.status === 'failed' || (t.lifecycle === 'EXPIRED' && t.status !== 'cancelled')) &&
    t.status !== 'completed'
  );

  // ─── Approval Section ───
  const approvalSection = document.getElementById('approval-section');
  const pendingList = document.getElementById('pending-list');
  const pendingCount = document.getElementById('pending-count');
  const approveBtn = document.getElementById('btn-approve-all');

  if (pending.length > 0) {
    approvalSection.style.display = '';
    pendingCount.textContent = pending.length;
    approveBtn.style.display = pending.length > 1 ? '' : 'none';
    pendingList.innerHTML = pending.map(renderPendingCard).join('');
    bindPendingActions(pendingList);
  } else {
    approvalSection.style.display = 'none';
  }

  // ─── Failed Section ───
  const failedSection = document.getElementById('failed-section');
  const failedList = document.getElementById('failed-list');
  if (failed.length > 0) {
    failedSection.style.display = '';
    failedList.innerHTML = failed.map(renderFailedCard).join('');
    bindFailedActions(failedList);
  } else {
    failedSection.style.display = 'none';
  }

  // ─── Today Section — unified timeline (all statuses in one list) ───
  const statDone = document.getElementById('stat-done');
  const statRemaining = document.getElementById('stat-remaining');
  statDone.textContent = `${completed.length} done`;
  statRemaining.textContent = `${scheduled.length + pending.length} left`;

  // Merge all into timeline sorted by scheduled_at
  const timeline = [...scheduled, ...completed, ...pending].sort((a, b) => {
    const ta = a.scheduled_at || a.completed_at || '9999';
    const tb = b.scheduled_at || b.completed_at || '9999';
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });

  const timelineList = document.getElementById('timeline-list');
  const emptyState = document.getElementById('empty-state');

  if (timeline.length > 0) {
    if (emptyState) emptyState.style.display = 'none';
    timelineList.innerHTML = timeline.map(renderTimelineCard).join('');
  } else {
    if (emptyState) {
      emptyState.style.display = '';
      emptyState.textContent = 'Nothing scheduled today.';
    }
    timelineList.innerHTML = '';
    if (emptyState) timelineList.appendChild(emptyState);
  }

  // Badge: pending count only
  const badgeCount = pending.length;
  chrome.action.setBadgeText({ text: badgeCount > 0 ? String(badgeCount) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#f59e0b' });
}

// ─── Card Renderers ─────────────────────────────────────────────────────────

function renderPendingCard(task) {
  const sub = task.subreddit || '';
  const threadUrl = task.thread_url || '';
  const threadTitle = truncate(task.thread_title || '', 40);
  const text = truncate(task.comment_text || '', 100);
  const deadlineStr = task.deadline ? `by ${formatTime(task.deadline)}` : '';
  const typeIcon = task.task_type === 'post' ? '📝' : '💬';

  const titleHtml = threadTitle
    ? (threadUrl
      ? `<a href="${esc(threadUrl)}" target="_blank" class="task-card__title">${esc(threadTitle)}</a>`
      : `<span class="task-card__title">${esc(threadTitle)}</span>`)
    : '';

  return `
    <div class="task-card" data-id="${task.task_id}">
      <div class="task-card__row">
        <div class="task-card__info">
          <div class="task-card__top">
            <span class="task-card__type">${typeIcon}</span>
            <span class="task-card__sub">r/${esc(sub)}</span>
            ${deadlineStr ? `<span class="task-card__deadline">${deadlineStr}</span>` : ''}
          </div>
          ${titleHtml}
          <div class="task-card__preview">${esc(text)}</div>
        </div>
        <div class="task-card__actions">
          <button class="btn-sm btn-sm--approve" data-action="approve" data-id="${task.task_id}" title="Approve">✓</button>
          <button class="btn-sm" data-action="edit" data-id="${task.task_id}" title="Edit">✎</button>
          <button class="btn-sm btn-sm--skip" data-action="skip" data-id="${task.task_id}" title="Skip">✗</button>
        </div>
      </div>
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

function renderTimelineCard(task) {
  const sub = task.subreddit || '';
  const threadUrl = task.thread_url || '';
  const threadTitle = truncate(task.thread_title || '', 50);
  const text = truncate(task.comment_text || '', 80);
  const time = formatTime(task.scheduled_at || task.completed_at);
  const typeIcon = task.task_type === 'post' ? '📝' : '💬';

  // Status badge
  let statusBadge = '';
  let cardClass = 'task-card--timeline';
  if (task.status === 'completed' || task.lifecycle === 'REPORTED' || task.lifecycle === 'FINALIZED') {
    statusBadge = '<span class="timeline-badge timeline-badge--done">✓ posted</span>';
    cardClass += ' task-card--timeline-done';
  } else if (task.status === 'executing') {
    statusBadge = '<span class="timeline-badge timeline-badge--active">⏳ posting...</span>';
    cardClass += ' task-card--timeline-active';
  } else if (task.status === 'approved') {
    statusBadge = '<span class="timeline-badge timeline-badge--planned">✓ planned</span>';
  } else if (task.status === 'generated' && (task.has_epg_slot || task.scheduled_at)) {
    statusBadge = '<span class="timeline-badge timeline-badge--planned">✓ planned</span>';
  } else if (task.status === 'generated') {
    statusBadge = '<span class="timeline-badge timeline-badge--waiting">⏱ queued</span>';
  } else if (task.status === 'pending') {
    statusBadge = '<span class="timeline-badge timeline-badge--pending">● pending</span>';
  }

  const permalink = task.permalink
    ? `<a href="${esc(task.permalink)}" target="_blank" class="timeline-link">view ↗</a>`
    : '';

  const titleHtml = threadTitle
    ? (threadUrl
      ? `<a href="${esc(threadUrl)}" target="_blank" class="task-card__title">${esc(threadTitle)}</a>`
      : `<span class="task-card__title">${esc(threadTitle)}</span>`)
    : '';

  return `
    <div class="task-card ${cardClass}">
      <div class="task-card__row">
        <span class="timeline-time">${time}</span>
        <div class="task-card__info">
          <div class="task-card__top">
            <span class="task-card__type">${typeIcon}</span>
            <span class="task-card__sub">r/${esc(sub)}</span>
            ${statusBadge}
          </div>
          ${titleHtml}
          ${text ? `<div class="task-card__preview">${esc(text)}</div>` : ''}
        </div>
        ${permalink}
      </div>
    </div>
  `;
}

function renderFailedCard(task) {
  const sub = task.subreddit || '';
  const error = task.status === 'cancelled'
    ? (task.lifecycle === 'EXPIRED' ? 'Expired' : 'Cancelled')
    : truncate(task.error_details || task.error_code || 'Failed', 50);

  return `
    <div class="task-card task-card--failed" data-id="${task.task_id}">
      <div class="task-card__row">
        <div class="task-card__info">
          <div class="task-card__top">
            <span class="task-card__sub">r/${esc(sub)}</span>
          </div>
          <div class="task-card__error">${esc(error)}</div>
        </div>
        <div class="task-card__actions">
          ${task.status !== 'cancelled' ? `<button class="btn-sm btn-sm--retry" data-action="retry" data-id="${task.task_id}">Retry</button>` : ''}
          <button class="btn-sm btn-sm--skip" data-action="dismiss" data-id="${task.task_id}">✗</button>
        </div>
      </div>
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
        break;
      case 'skip':
        await chrome.runtime.sendMessage({ type: 'SKIP_TASK', taskId: id });
        break;
      case 'edit': {
        const panel = document.getElementById(`edit-${id}`);
        if (panel) panel.classList.toggle('open');
        return; // Don't refresh
      }
      case 'cancel-edit': {
        const panel = document.getElementById(`edit-${id}`);
        if (panel) panel.classList.remove('open');
        return;
      }
      case 'save-edit': {
        const panel = document.getElementById(`edit-${id}`);
        const textarea = panel?.querySelector('textarea');
        if (textarea && textarea.value.trim()) {
          const newText = textarea.value.trim();
          const auth = await getAuth();
          if (auth?.token && auth?.rampUrl) {
            try {
              await fetch(`${auth.rampUrl}/api/extension/tasks/${id}`, {
                method: 'PATCH',
                headers: { 'Authorization': `Bearer ${auth.token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: newText }),
              });
            } catch {}
          }
          await chrome.runtime.sendMessage({ type: 'UPDATE_TASK_TEXT', taskId: id, newText });
          await chrome.runtime.sendMessage({ type: 'APPROVE_TASK_V2', taskId: id });
        }
        break;
      }
    }
    await fetchQueueAndRender();
  });
}

function bindFailedActions(container) {
  container.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    if (btn.dataset.action === 'retry') {
      await chrome.runtime.sendMessage({ type: 'RETRY_TASK', taskId: btn.dataset.id });
    } else if (btn.dataset.action === 'dismiss') {
      await chrome.runtime.sendMessage({ type: 'SKIP_TASK', taskId: btn.dataset.id });
    }
    await fetchQueueAndRender();
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

async function getActiveUsername(auth) {
  if (auth?.avatarUsername) return auth.avatarUsername;
  const stored = await chrome.storage.local.get('activeRedditUsername');
  return stored?.activeRedditUsername || '';
}

function formatTime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function truncate(str, max) {
  return str.length <= max ? str : str.slice(0, max).trimEnd() + '…';
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

function updateTimestamp() {
  const el = document.getElementById('last-updated');
  if (el) el.textContent = `Updated ${formatTime(new Date().toISOString())}`;
}

// Chrome extension popup blocks target="_blank" — intercept and open via chrome.tabs.create
document.addEventListener('click', (e) => {
  const link = e.target.closest('a[href]');
  if (!link) return;
  const href = link.getAttribute('href');
  if (href && href.startsWith('http')) {
    e.preventDefault();
    chrome.tabs.create({ url: href });
  }
});

document.addEventListener('DOMContentLoaded', init);
