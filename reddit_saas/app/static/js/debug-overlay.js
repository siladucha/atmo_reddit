/**
 * RAMP Debug Overlay Engine — UI Observability System
 * 
 * Activates when:
 *   1. <body data-debug-ui="true"> (backend injection, dev only)
 *   2. localStorage.getItem('debug_ui_active') === 'true'
 * 
 * Provides three overlay layers: borders, labels, grid
 * Handles HTMX dynamic DOM updates via afterSwap/beforeSwap events.
 * 
 * Toggle: Click the floating panel button (bottom-right corner)
 * Activate: localStorage.setItem('debug_ui_active', 'true'); location.reload();
 */
(function() {
  'use strict';

  // --- Constants ---
  var PREFS_KEY = 'debug_ui_prefs';
  var ACTIVE_KEY = 'debug_ui_active';
  var OVERLAY_CLASS = 'ramp-debug-overlay';
  var COLORS = ['#FF6B35', '#22C55E', '#60A5FA', '#F59E0B', '#A855F7', '#EC4899', '#14B8A6', '#EF4444'];
  var VIEWPORT_THRESHOLD = 200;

  // --- State ---
  var state = {
    active: false,
    layers: { borders: true, labels: true, grid: false },
    overlays: [],       // {el, border, label} tracking
    observer: null,     // IntersectionObserver
    panelEl: null,
    headerEl: null,
    colorIdx: 0,
    useViewportMode: false
  };

  // --- Check Activation ---
  function shouldActivate() {
    if (document.body.dataset.debugUi !== 'true') return false;
    return localStorage.getItem(ACTIVE_KEY) === 'true';
  }

  // --- Preferences ---
  function loadPrefs() {
    try {
      var saved = JSON.parse(localStorage.getItem(PREFS_KEY));
      if (saved) {
        state.layers.borders = saved.borders !== false;
        state.layers.labels = saved.labels !== false;
        state.layers.grid = saved.grid === true;
      }
    } catch(e) {}
  }

  function savePrefs() {
    localStorage.setItem(PREFS_KEY, JSON.stringify(state.layers));
  }

  // --- Color Assignment ---
  function nextColor() {
    var c = COLORS[state.colorIdx % COLORS.length];
    state.colorIdx++;
    return c;
  }

  // --- Overlay Creation ---
  function createBorderOverlay(el, color) {
    var rect = el.getBoundingClientRect();
    var div = document.createElement('div');
    div.className = OVERLAY_CLASS + ' ramp-debug-border';
    div.style.cssText = 'position:fixed;pointer-events:none;z-index:99990;' +
      'border:2px solid ' + color + ';' +
      'top:' + rect.top + 'px;left:' + rect.left + 'px;' +
      'width:' + rect.width + 'px;height:' + rect.height + 'px;' +
      'box-sizing:border-box;transition:none;';
    document.body.appendChild(div);
    return div;
  }

  function createLabelOverlay(el, color) {
    var name = el.getAttribute('data-component') || '?';
    var owner = el.getAttribute('data-owner') || '';
    var variant = el.getAttribute('data-variant');
    var text = name;
    if (owner) text += ' — ' + owner;
    if (variant) text += ' [' + variant + ']';

    var rect = el.getBoundingClientRect();
    var label = document.createElement('div');
    label.className = OVERLAY_CLASS + ' ramp-debug-label';
    label.style.cssText = 'position:fixed;pointer-events:none;z-index:99991;' +
      'background:' + color + ';color:#fff;font-size:10px;font-family:monospace;' +
      'padding:1px 4px;border-radius:2px;white-space:nowrap;opacity:0.9;' +
      'top:' + Math.max(0, rect.top - 14) + 'px;left:' + rect.left + 'px;' +
      'max-width:300px;overflow:hidden;text-overflow:ellipsis;';
    label.textContent = text;
    document.body.appendChild(label);
    return label;
  }

  // --- Scan DOM ---
  function scanElements(root) {
    var elements = (root || document).querySelectorAll('[data-component]');
    state.useViewportMode = elements.length > VIEWPORT_THRESHOLD;
    return Array.prototype.slice.call(elements);
  }

  function renderOverlays(elements) {
    elements.forEach(function(el) {
      // Skip if already tracked
      if (el._rampDebugTracked) return;
      el._rampDebugTracked = true;

      var color = nextColor();
      var entry = { el: el, border: null, label: null, color: color, visible: true };

      if (state.layers.borders) {
        entry.border = createBorderOverlay(el, color);
      }
      if (state.layers.labels) {
        entry.label = createLabelOverlay(el, color);
      }

      state.overlays.push(entry);
    });
  }

  function removeOverlaysForContainer(container) {
    state.overlays = state.overlays.filter(function(entry) {
      if (container.contains(entry.el)) {
        if (entry.border) entry.border.remove();
        if (entry.label) entry.label.remove();
        entry.el._rampDebugTracked = false;
        return false;
      }
      return true;
    });
  }

  function removeAllOverlays() {
    state.overlays.forEach(function(entry) {
      if (entry.border) entry.border.remove();
      if (entry.label) entry.label.remove();
      entry.el._rampDebugTracked = false;
    });
    state.overlays = [];
    state.colorIdx = 0;
  }

  function repositionAll() {
    state.overlays.forEach(function(entry) {
      var rect = entry.el.getBoundingClientRect();
      if (entry.border) {
        entry.border.style.top = rect.top + 'px';
        entry.border.style.left = rect.left + 'px';
        entry.border.style.width = rect.width + 'px';
        entry.border.style.height = rect.height + 'px';
      }
      if (entry.label) {
        entry.label.style.top = Math.max(0, rect.top - 14) + 'px';
        entry.label.style.left = rect.left + 'px';
      }
    });
  }

  // --- Header Bar ---
  function createHeaderBar() {
    var header = document.createElement('div');
    header.className = OVERLAY_CLASS + ' ramp-debug-header';
    header.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99992;' +
      'background:#1E293B;color:#94A3B8;font-size:11px;font-family:monospace;' +
      'padding:3px 12px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #475569;';
    
    var templateName = document.querySelector('meta[name="template"]');
    var tmplText = templateName ? templateName.content : '(unknown template)';
    header.innerHTML = '<span style="color:#818CF8;">DEBUG</span> ' +
      '<span>Template: <b style="color:#F1F5F9;">' + tmplText + '</b></span>' +
      '<span style="margin-left:auto;color:#64748B;">' + state.overlays.length + ' components</span>';
    
    document.body.appendChild(header);
    state.headerEl = header;
  }

  function updateHeader() {
    if (!state.headerEl) return;
    var countSpan = state.headerEl.querySelector('span:last-child');
    if (countSpan) countSpan.textContent = state.overlays.length + ' components';
  }

  // --- Floating Panel ---
  function createPanel() {
    var panel = document.createElement('div');
    panel.className = OVERLAY_CLASS + ' ramp-debug-panel';
    panel.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:99993;' +
      'background:#1E293B;border:1px solid #475569;border-radius:8px;' +
      'padding:8px;font-family:system-ui,sans-serif;font-size:12px;color:#F1F5F9;' +
      'box-shadow:0 4px 16px rgba(0,0,0,0.5);display:flex;flex-direction:column;gap:4px;min-width:140px;';

    var title = document.createElement('div');
    title.style.cssText = 'font-weight:600;font-size:11px;color:#818CF8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:4px;';
    title.textContent = 'Debug Overlay';
    panel.appendChild(title);

    ['borders', 'labels', 'grid'].forEach(function(layer) {
      var row = document.createElement('label');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;cursor:pointer;padding:2px 0;';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = state.layers[layer];
      cb.style.cssText = 'accent-color:#818CF8;';
      cb.addEventListener('change', function() {
        state.layers[layer] = cb.checked;
        savePrefs();
        refresh();
      });
      row.appendChild(cb);
      row.appendChild(document.createTextNode(layer.charAt(0).toUpperCase() + layer.slice(1)));
      panel.appendChild(row);
    });

    // Deactivate button
    var deact = document.createElement('button');
    deact.style.cssText = 'margin-top:6px;padding:4px 8px;border-radius:4px;border:1px solid #475569;' +
      'background:transparent;color:#94A3B8;font-size:11px;cursor:pointer;';
    deact.textContent = 'Deactivate';
    deact.addEventListener('click', function() {
      localStorage.removeItem(ACTIVE_KEY);
      deactivate();
    });
    panel.appendChild(deact);

    document.body.appendChild(panel);
    state.panelEl = panel;
  }

  // --- Refresh ---
  function refresh() {
    removeAllOverlays();
    if (state.headerEl) { state.headerEl.remove(); state.headerEl = null; }
    
    var elements = scanElements();
    renderOverlays(elements);
    
    if (state.layers.labels) {
      createHeaderBar();
    }
    updateHeader();
  }

  // --- HTMX Integration ---
  function setupHTMXListeners() {
    document.body.addEventListener('htmx:beforeSwap', function(evt) {
      var target = evt.detail.target;
      if (target) removeOverlaysForContainer(target);
    });

    document.body.addEventListener('htmx:afterSwap', function(evt) {
      var target = evt.detail.target;
      if (target) {
        setTimeout(function() {
          var newElements = scanElements(target);
          renderOverlays(newElements);
          updateHeader();
        }, 50);
      }
    });
  }

  // --- Scroll/Resize ---
  var rafId = null;
  function onScrollResize() {
    if (rafId) return;
    rafId = requestAnimationFrame(function() {
      rafId = null;
      repositionAll();
    });
  }

  // --- Public API ---
  function activate() {
    if (state.active) return;
    state.active = true;
    loadPrefs();
    refresh();
    createPanel();
    setupHTMXListeners();
    window.addEventListener('scroll', onScrollResize, { passive: true });
    window.addEventListener('resize', onScrollResize, { passive: true });
  }

  function deactivate() {
    state.active = false;
    removeAllOverlays();
    if (state.panelEl) { state.panelEl.remove(); state.panelEl = null; }
    if (state.headerEl) { state.headerEl.remove(); state.headerEl = null; }
    window.removeEventListener('scroll', onScrollResize);
    window.removeEventListener('resize', onScrollResize);
    // Remove all debug overlay elements
    document.querySelectorAll('.' + OVERLAY_CLASS).forEach(function(el) { el.remove(); });
  }

  // --- Expose Global API ---
  window.RampDebug = {
    activate: function() { localStorage.setItem(ACTIVE_KEY, 'true'); activate(); },
    deactivate: function() { localStorage.removeItem(ACTIVE_KEY); deactivate(); },
    toggle: function(layer) {
      if (state.layers.hasOwnProperty(layer)) {
        state.layers[layer] = !state.layers[layer];
        savePrefs();
        refresh();
      }
    },
    rescan: refresh,
    rescanSubtree: function(el) {
      var newElements = scanElements(el);
      renderOverlays(newElements);
      updateHeader();
    }
  };

  // --- Auto-activate ---
  if (shouldActivate()) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', activate);
    } else {
      activate();
    }
  }

})();
