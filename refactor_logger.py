"""
Refactor script: Replace `import logging` + `logger = logging.getLogger(__name__)`
with `from app.logging_config import get_logger` + `logger = get_logger(__name__)`

Only modifies files where `logging` is used ONLY for `getLogger(__name__)`.
"""
import re
import os

ROOT = "/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas"

# Files that use logging for more than getLogger(__name__) - skip these for `import logging` removal
KEEP_IMPORT_LOGGING = {
    "app/services/metrics_collector.py",
    "app/routes/admin.py",
    "app/logging_config.py",
    "app/main.py",  # uses setup_logging from logging_config already, also has logging import
}

def find_python_files(root):
    """Find all .py files under root (excluding tests, __pycache__, .venv)."""
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip directories
        dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.venv', '.hypothesis', 'alembic')]
        for f in filenames:
            if f.endswith('.py'):
                results.append(os.path.join(dirpath, f))
    return results

def process_file(filepath):
    """Process a single file. Returns True if modified."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Must have the target pattern
    if 'logger = logging.getLogger(__name__)' not in content:
        return False
    
    relative = os.path.relpath(filepath, ROOT)
    
    # Check if file uses logging for other purposes
    uses_logging_elsewhere = bool(re.search(
        r'logging\.(WARNING|DEBUG|INFO|ERROR|CRITICAL|disable|basicConfig|StreamHandler|'
        r'FileHandler|Handler|LogRecord|getLogger\([^_])',
        content
    ))
    
    # Also check if logging_config is already imported
    already_has_get_logger = 'from app.logging_config import' in content
    
    new_content = content
    
    # Replace the logger line
    new_content = new_content.replace(
        'logger = logging.getLogger(__name__)',
        'logger = get_logger(__name__)'
    )
    
    if not already_has_get_logger:
        if uses_logging_elsewhere or relative in KEEP_IMPORT_LOGGING:
            # Keep `import logging`, just add get_logger import
            # Add after the last `from app...` import or after `import logging`
            new_content = new_content.replace(
                'import logging\n',
                'import logging\n\nfrom app.logging_config import get_logger\n',
                1
            )
        else:
            # Replace `import logging` with `from app.logging_config import get_logger`
            new_content = new_content.replace(
                'import logging\n',
                'from app.logging_config import get_logger\n',
                1
            )
    
    if new_content == content:
        return False
    
    with open(filepath, 'w') as f:
        f.write(new_content)
    
    print(f"  Modified: {relative}")
    return True

def main():
    files = find_python_files(ROOT)
    modified = 0
    for f in sorted(files):
        if process_file(f):
            modified += 1
    print(f"\nDone. Modified {modified} files.")

if __name__ == '__main__':
    main()
