/**
 * RAMP Client Portal — Unified Action Handler
 * Handles all button actions with consistent loading states, toasts, and error handling.
 * 
 * Usage:
 *   portalAction(button, '/clients/xxx/drafts/yyy/approve', {
 *     method: 'POST',
 *     onSuccess: (data) => removeCard(draftId),
 *     successMessage: 'Approved',
 *     errorMessage: 'Could not approve',
 *   });
 */

(function() {
  'use strict';

  // --- Button State Management ---
  
  function setButtonLoading(btn) {
    if (!btn) return;
    btn.disabled = true;
    btn._originalContent = btn.innerHTML;
    btn._originalWidth = btn.offsetWidth;
    btn.style.minWidth = btn._originalWidth + 'px';
    btn.innerHTML = '<span class="portal-spinner"></span>';
  }

  function resetButton(btn) {
    if (!btn || !btn._originalContent) return;
    btn.disabled = false;
    btn.innerHTML = btn._originalContent;
    btn.style.minWidth = '';
  }

  function setButtonSuccess(btn, text) {
    if (!btn) return;
    btn.innerHTML = '<span style="color:#22c55e;">\u2713</span> ' + (text || 'Done');
    setTimeout(function() { resetButton(btn); }, 2000);
  }

  function setButtonError(btn) {
    if (!btn) return;
    resetButton(btn);
    btn.style.animation = 'portal-shake 0.4s ease';
    setTimeout(function() { btn.style.animation = ''; }, 500);
  }

  // --- Core Action Function ---

  window.portalAction = function(btn, url, opts) {
    opts = opts || {};
    var method = opts.method || 'POST';
    var body = opts.body || null;
    var headers = { 'Accept': 'application/json' };
    
    if (opts.contentType) {
      headers['Content-Type'] = opts.contentType;
    } else if (method === 'POST' && !body) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
      body = '';
    }

    setButtonLoading(btn);

    fetch(url, {
      method: method,
      headers: headers,
      credentials: 'same-origin',
      body: body
    })
    .then(function(r) {
      if (r.ok) {
        return r.text().then(function(text) {
          var data = {};
          try { data = JSON.parse(text); } catch(e) {}
          
          if (opts.onSuccess) {
            opts.onSuccess(data, r);
          } else {
            setButtonSuccess(btn, opts.successMessage || 'Done');
          }
          window.showToast('success', data.message || opts.successMessage || 'Done');
        });
      } else if (r.status === 303 || r.redirected) {
        window.location.href = '/login';
      } else {
        return r.text().then(function(text) {
          var msg = opts.errorMessage || 'Action failed';
          try {
            var data = JSON.parse(text);
            msg = data.message || data.detail || msg;
          } catch(e) {
            console.error('portalAction error response:', r.status, text.substring(0, 200));
          }
          setButtonError(btn);
          window.showToast('error', msg);
          if (opts.onError) opts.onError(msg, r);
        });
      }
    })
    .catch(function(err) {
      console.error('portalAction network error:', err);
      setButtonError(btn);
      window.showToast('error', 'Connection lost. Check your internet.');
      if (opts.onError) opts.onError('Network error', null);
    });
  };

  // --- Card Animation Helper ---

  window.portalRemoveCard = function(cardId) {
    var card = document.getElementById(cardId);
    if (!card) return;
    card.style.transition = 'all 300ms ease';
    card.style.maxHeight = '0';
    card.style.overflow = 'hidden';
    card.style.padding = '0';
    card.style.margin = '0';
    card.style.opacity = '0';
    setTimeout(function() { card.remove(); }, 350);
  };

  // --- Inject CSS for spinner and shake ---

  var style = document.createElement('style');
  style.textContent = [
    '@keyframes portal-spin { to { transform: rotate(360deg); } }',
    '@keyframes portal-shake { 0%,100% { transform:translateX(0); } 25% { transform:translateX(-4px); } 75% { transform:translateX(4px); } }',
    '.portal-spinner {',
    '  display:inline-block; width:16px; height:16px;',
    '  border:2px solid rgba(255,255,255,0.3);',
    '  border-top-color:#fff; border-radius:50%;',
    '  animation: portal-spin 0.6s linear infinite;',
    '}'
  ].join('\n');
  document.head.appendChild(style);

})();
