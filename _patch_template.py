import pathlib

p = pathlib.Path('/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/templates/executor_task_view.html')
content = p.read_text()

# Find the section to replace - use a unique anchor
old_section = """        {% if task.status in ('accepted', 'submitted', 'url_verified', 'emailed') %}
        <!-- Submit URL form -->
        <form method="POST" action="/tasks/{{ task.task_code }}/{{ token }}/submit">
            <label class="block text-sm font-medium text-gray-700 mb-1">Reddit Permalink</label>
            <input type="url" name="reddit_url" required placeholder="https://www.reddit.com/r/.../comments/..."
                   value="{{ task.submitted_url or '' }}"
                   class="w-full px-4 py-3 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mb-3">
            <button type="submit" class="w-full bg-green-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-green-700 transition-colors">
                Submit & Verify
            </button>
        </form>
        {% endif %}
    </div>
    {% endif %}"""

new_section = """        {% if task.status in ('accepted', 'submitted', 'url_verified', 'emailed') %}
        <!-- Submit URL form -->
        <form method="POST" action="/tasks/{{ task.task_code }}/{{ token }}/submit">
            <label class="block text-sm font-medium text-gray-700 mb-1">Reddit Permalink</label>
            <input type="url" name="reddit_url" required placeholder="https://www.reddit.com/r/.../comments/..."
                   value="{{ task.submitted_url or '' }}"
                   class="w-full px-4 py-3 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mb-3">
            <button type="submit" class="w-full bg-green-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-green-700 transition-colors">
                Submit & Verify
            </button>
        </form>

        <!-- Can't Post section -->
        <details class="mt-4 border-t pt-3">
            <summary class="text-sm text-gray-500 cursor-pointer hover:text-gray-700">Can't post this comment?</summary>
            <form method="POST" action="/tasks/{{ task.task_code }}/{{ token }}/report-blocked" class="mt-3">
                <label class="block text-sm font-medium text-gray-700 mb-1">Reason</label>
                <select name="reason" class="w-full px-3 py-2 border rounded-lg text-sm mb-3">
                    <option value="thread_locked">Thread is locked</option>
                    <option value="thread_removed">Thread was removed/deleted</option>
                    <option value="thread_archived">Thread is archived</option>
                    <option value="account_issue">Account issue (banned/suspended)</option>
                    <option value="other">Other reason</option>
                </select>
                <button type="submit" class="w-full bg-gray-500 text-white py-2 px-4 rounded-lg text-sm font-medium hover:bg-gray-600 transition-colors">
                    Report as Blocked
                </button>
            </form>
        </details>
        {% endif %}
    </div>
    {% endif %}"""

if old_section in content:
    content = content.replace(old_section, new_section, 1)
    p.write_text(content)
    print('OK: template patched with Can\'t Post button')
else:
    print('ERROR: old section not found in template')
