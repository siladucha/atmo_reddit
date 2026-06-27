/**
 * Idle Logout — auto-logout after 1 hour of inactivity.
 * Tracks: mousemove, keydown, scroll, click, touchstart.
 * Shows a warning toast 60s before logout.
 */
(function () {
  "use strict";

  var IDLE_TIMEOUT_MS = 60 * 60 * 1000; // 1 hour
  var WARNING_BEFORE_MS = 60 * 1000; // warn 60s before logout
  var LOGOUT_URL = "/logout";

  var idleTimer = null;
  var warningTimer = null;
  var warningShown = false;

  function resetTimers() {
    if (warningShown) {
      hideWarning();
    }
    clearTimeout(idleTimer);
    clearTimeout(warningTimer);

    warningTimer = setTimeout(showWarning, IDLE_TIMEOUT_MS - WARNING_BEFORE_MS);
    idleTimer = setTimeout(doLogout, IDLE_TIMEOUT_MS);
  }

  function doLogout() {
    window.location.href = LOGOUT_URL;
  }

  function showWarning() {
    warningShown = true;
    var el = document.getElementById("idle-logout-warning");
    if (!el) {
      el = document.createElement("div");
      el.id = "idle-logout-warning";
      el.style.cssText =
        "position:fixed;top:20px;left:50%;transform:translateX(-50%);" +
        "background:#1e293b;color:#fbbf24;padding:12px 24px;border-radius:8px;" +
        "font-size:14px;z-index:99999;box-shadow:0 4px 12px rgba(0,0,0,0.3);" +
        "display:flex;align-items:center;gap:8px;";
      el.innerHTML =
        '<span style="font-size:18px;">⚠️</span>' +
        '<span>Session expires in 60 seconds due to inactivity</span>';
      document.body.appendChild(el);
    }
    el.style.display = "flex";
  }

  function hideWarning() {
    warningShown = false;
    var el = document.getElementById("idle-logout-warning");
    if (el) {
      el.style.display = "none";
    }
  }

  // Listen for user activity
  var events = ["mousemove", "keydown", "scroll", "click", "touchstart"];
  events.forEach(function (evt) {
    document.addEventListener(evt, resetTimers, { passive: true });
  });

  // Also reset on HTMX requests (counts as activity)
  document.addEventListener("htmx:afterRequest", resetTimers);

  // Start timers
  resetTimers();
})();
