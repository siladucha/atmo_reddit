/**
 * RAMP Client Portal — Toast Notification System
 * Listens for HTMX showToast trigger events.
 * Positions: fixed bottom-right, max 3 stacked, auto-dismiss 4s.
 */

(function () {
  'use strict';

  const MAX_TOASTS = 3;
  const DISMISS_MS = 4000;

  // Container (created once, appended to body)
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText =
      'position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
    document.body.appendChild(container);
  }

  function getColor(type) {
    switch (type) {
      case 'success': return 'var(--color-green)';
      case 'warning': return 'var(--color-amber)';
      case 'error':   return 'var(--color-red)';
      default:        return 'var(--color-surface-alt)';
    }
  }

  function createToast(type, message) {
    // Enforce max 3
    while (container.children.length >= MAX_TOASTS) {
      container.removeChild(container.firstChild);
    }

    const el = document.createElement('div');
    el.className = 'toast-enter';
    el.style.cssText =
      'pointer-events:auto;padding:12px 20px;border-radius:8px;color:#fff;font-size:14px;' +
      'font-weight:500;box-shadow:0 4px 16px rgba(0,0,0,0.5);max-width:360px;' +
      'background:' + getColor(type) + ';';
    el.textContent = message;
    container.appendChild(el);

    // Auto-dismiss
    setTimeout(function () {
      el.className = 'toast-exit';
      el.addEventListener('animationend', function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      });
    }, DISMISS_MS);
  }

  // Listen for HTMX trigger: HX-Trigger: {"showToast": {"type":"success","message":"..."}}
  document.body.addEventListener('showToast', function (evt) {
    var detail = evt.detail || {};
    createToast(detail.type || 'success', detail.message || 'Done');
  });

  // Also expose globally for manual use
  window.showToast = createToast;
})();
