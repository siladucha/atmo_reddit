/**
 * RAMP Client Portal — Real-time Notification System
 * Connects to SSE stream, manages bell badge, and shows notification feed panel.
 *
 * Requires: toast.js (for showToast), portal-actions.js
 * Expects data attribute on body: data-client-id="..."
 */

(function() {
  'use strict';

  var clientId = document.body.getAttribute('data-client-id');
  if (!clientId) return; // Not on a client-scoped page

  var badge = document.getElementById('notif-badge');
  var bellBtn = document.getElementById('notif-bell');
  var panel = document.getElementById('notif-panel');
  var listEl = document.getElementById('notif-list');
  var unreadCount = 0;
  var panelOpen = false;
  var eventSource = null;

  // --- SSE Connection ---

  function connectSSE() {
    if (eventSource) { eventSource.close(); }
    eventSource = new EventSource('/api/sse/notifications');

    eventSource.onmessage = function(evt) {
      try {
        var data = JSON.parse(evt.data);
        if (data.type === 'connected') return;
        if (data.type === 'error') return;

        // New notification arrived
        unreadCount++;
        updateBadge();
        
        // Show toast for real-time notification
        window.showToast(data.type || 'info', data.title || 'New notification');
        
        // Add to panel if open
        if (panelOpen && listEl) {
          var item = buildNotifItem(data);
          listEl.insertBefore(item, listEl.firstChild);
        }

        // Dispatch custom event for page-specific handlers (e.g., refresh review queue)
        document.dispatchEvent(new CustomEvent('ramp:notification', { detail: data }));
      } catch(e) {
        // keepalive or parse error, ignore
      }
    };

    eventSource.onerror = function() {
      // Auto-reconnect is built into EventSource (browser handles it)
      console.debug('SSE connection lost, browser will auto-reconnect');
    };
  }

  // --- Badge ---

  function updateBadge() {
    if (!badge) return;
    if (unreadCount > 0) {
      badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
      badge.style.display = 'flex';
    } else {
      badge.style.display = 'none';
    }
  }

  function fetchUnreadCount() {
    fetch('/clients/' + clientId + '/notifications/count', {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      unreadCount = data.unread || 0;
      updateBadge();
    })
    .catch(function() {});
  }

  // --- Panel ---

  function togglePanel() {
    panelOpen = !panelOpen;
    if (!panel) return;
    
    if (panelOpen) {
      panel.style.display = 'block';
      loadNotifications();
    } else {
      panel.style.display = 'none';
    }
  }

  function loadNotifications() {
    if (!listEl) return;
    listEl.innerHTML = '<div style="padding:16px;text-align:center;color:var(--color-muted);font-size:13px;">Loading...</div>';

    fetch('/clients/' + clientId + '/notifications', {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      listEl.innerHTML = '';
      var notifs = data.notifications || [];
      if (notifs.length === 0) {
        listEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--color-muted);font-size:13px;">No notifications yet</div>';
        return;
      }
      notifs.forEach(function(n) {
        listEl.appendChild(buildNotifItem(n));
      });
    })
    .catch(function() {
      listEl.innerHTML = '<div style="padding:16px;text-align:center;color:var(--color-red);font-size:13px;">Failed to load</div>';
    });
  }

  function buildNotifItem(n) {
    var el = document.createElement('div');
    el.style.cssText = 'padding:10px 16px;border-bottom:1px solid var(--color-border);display:flex;align-items:flex-start;gap:10px;';
    if (!n.is_read) {
      el.style.background = 'rgba(99,102,241,0.05)';
    }
    
    var iconColor = n.type === 'success' ? 'var(--color-green)' :
                    n.type === 'error' ? 'var(--color-red)' :
                    n.type === 'warning' ? 'var(--color-amber)' : '#60a5fa';
    
    var dot = '<span style="width:8px;height:8px;border-radius:50%;background:' + iconColor + ';flex-shrink:0;margin-top:5px;"></span>';
    var content = '<div style="flex:1;min-width:0;">';
    content += '<div style="font-size:13px;color:var(--color-white);font-weight:500;">' + escapeHtml(n.title) + '</div>';
    if (n.body) {
      content += '<div style="font-size:12px;color:var(--color-muted);margin-top:2px;">' + escapeHtml(n.body) + '</div>';
    }
    content += '<div style="font-size:11px;color:var(--color-muted);margin-top:4px;">' + timeAgo(n.created_at) + '</div>';
    content += '</div>';
    
    if (n.link) {
      el.innerHTML = '<a href="' + n.link + '" style="display:flex;align-items:flex-start;gap:10px;text-decoration:none;flex:1;">' + dot + content + '</a>';
    } else {
      el.innerHTML = dot + content;
    }
    return el;
  }

  function markAllRead() {
    fetch('/clients/' + clientId + '/notifications/read', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    })
    .then(function() {
      unreadCount = 0;
      updateBadge();
      // Remove highlights
      if (listEl) {
        var items = listEl.querySelectorAll('[style*="rgba(99,102,241"]');
        items.forEach(function(item) { item.style.background = 'transparent'; });
      }
    })
    .catch(function() {});
  }

  // --- Helpers ---

  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function timeAgo(isoStr) {
    if (!isoStr) return '';
    var d = new Date(isoStr);
    var now = new Date();
    var diff = Math.floor((now - d) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  // --- Init ---

  // Wire up bell button
  if (bellBtn) {
    bellBtn.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();
      togglePanel();
    });
  }

  // Close panel on outside click
  document.addEventListener('click', function(e) {
    if (panelOpen && panel && !panel.contains(e.target) && bellBtn && !bellBtn.contains(e.target)) {
      panelOpen = false;
      panel.style.display = 'none';
    }
  });

  // Wire up mark-all-read button
  var markReadBtn = document.getElementById('notif-mark-read');
  if (markReadBtn) {
    markReadBtn.addEventListener('click', markAllRead);
  }

  // Initial load
  fetchUnreadCount();
  connectSSE();

  // Expose for external use
  window.rampNotifications = {
    refresh: fetchUnreadCount,
    markAllRead: markAllRead
  };

})();
