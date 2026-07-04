"""Fix the false 'Leave page?' popup on admin pages."""
import pathlib

file = pathlib.Path("/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/templates/admin_base.html")
content = file.read_text()

OLD = """    <!-- Unsaved changes detection -->
    <script>
    (function() {
        var dirty = false;

        function markDirty() { dirty = true; }
        function markClean() { dirty = false; }

        // Track changes on forms with data-track-changes attribute
        document.addEventListener('input', function(e) {
            if (e.target.closest('form[data-track-changes]')) markDirty();
        });
        document.addEventListener('change', function(e) {
            if (e.target.closest('form[data-track-changes]')) markDirty();
        });

        // Reset dirty flag on successful form submission
        document.addEventListener('submit', function(e) {
            if (e.target.matches('form[data-track-changes]')) markClean();
        });

        // Skip beforeunload for HTMX requests
        document.body.addEventListener('htmx:beforeRequest', function() {
            markClean();
        });

        // Warn on page navigation when form is dirty
        window.addEventListener('beforeunload', function(e) {
            if (dirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
    })();
    </script>"""

NEW = """    <!-- Unsaved changes detection -->
    <script>
    (function() {
        var dirty = false;
        var tracking = false;

        function markDirty() { if (tracking) dirty = true; }
        function markClean() { dirty = false; }

        // Track changes on forms with data-track-changes attribute
        // Only count events triggered by real user interaction (isTrusted)
        document.addEventListener('input', function(e) {
            if (e.isTrusted && e.target.closest('form[data-track-changes]')) markDirty();
        });
        document.addEventListener('change', function(e) {
            if (e.isTrusted && e.target.closest('form[data-track-changes]')) markDirty();
        });

        // Reset dirty flag on successful form submission
        document.addEventListener('submit', function(e) {
            if (e.target.matches('form[data-track-changes]')) markClean();
        });

        // Skip beforeunload for HTMX requests
        document.body.addEventListener('htmx:beforeRequest', function() {
            markClean();
        });

        // Also reset on successful HTMX swap (form submitted via HTMX)
        document.body.addEventListener('htmx:afterSwap', function() {
            markClean();
        });

        // Warn on page navigation when form is dirty
        window.addEventListener('beforeunload', function(e) {
            if (dirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });

        // Delay tracking activation to avoid false positives from
        // browser autofill, HTMX initial loads, and DOM hydration
        setTimeout(function() { tracking = true; }, 1500);
    })();
    </script>"""

if OLD in content:
    content = content.replace(OLD, NEW)
    file.write_text(content)
    print("✅ Fixed! Unsaved changes detection now uses isTrusted + delayed activation.")
else:
    print("❌ Old pattern not found — file may have already been modified or has different whitespace.")
    # Debug: show what's around line 666
    lines = file.read_text().splitlines()
    for i, line in enumerate(lines[665:700], start=666):
        print(f"{i}: {repr(line)}")
