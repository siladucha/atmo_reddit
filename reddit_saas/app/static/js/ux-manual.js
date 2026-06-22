/**
 * UX Manual Overlay — open/close logic
 * Vanilla JS, no dependencies.
 */
(function() {
    "use strict";

    var overlay = document.getElementById("ux-manual-overlay");
    var btn = document.getElementById("ux-manual-btn");
    var closeBtn = document.getElementById("ux-manual-close-btn");
    var backdrop = document.getElementById("ux-manual-backdrop");

    if (!overlay || !btn) return;

    function openManual() {
        overlay.classList.remove("ux-manual-hidden");
        document.body.style.overflow = "hidden";
        // Focus the close button for accessibility
        if (closeBtn) closeBtn.focus();
    }

    function closeManual() {
        overlay.classList.add("ux-manual-hidden");
        document.body.style.overflow = "";
        btn.focus();
    }

    // Button click opens overlay (HTMX handles content loading via hx-trigger="click once")
    btn.addEventListener("click", openManual);

    // Close handlers
    if (closeBtn) closeBtn.addEventListener("click", closeManual);
    if (backdrop) backdrop.addEventListener("click", closeManual);

    // Escape key
    document.addEventListener("keydown", function(e) {
        if (e.key === "Escape" && !overlay.classList.contains("ux-manual-hidden")) {
            closeManual();
        }
    });
})();
