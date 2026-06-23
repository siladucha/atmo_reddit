"""Insert executor email section into the admin_avatar_detail.html posting tab."""
import pathlib

template_path = pathlib.Path('/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/templates/admin_avatar_detail.html')
content = template_path.read_text()

# The marker before which we insert
marker = '        <!-- Posting Configuration Form -->'
idx = content.find(marker)
if idx == -1:
    print("ERROR: Marker not found!")
    exit(1)

print(f"Found marker at position: {idx}")

# The new section to insert BEFORE the posting config form
new_section = '''        <!-- Email Task Routing -->
        <div class="bg-dark-steel rounded-lg border border-slate-700 p-6">
            <h3 class="text-lg font-semibold text-white mb-4">Email Task Routing{% set tooltip_text = "When a draft is approved, the system emails posting instructions to the avatar's executor. Configure the executor email here. Email must be verified before tasks are sent." %}{% include "partials/block_tooltip.html" %}</h3>

            <div class="flex items-center gap-3 mb-4">
                {% if avatar.executor_email %}
                <div class="flex items-center gap-2">
                    <span class="text-sm text-gray-200 font-mono">{{ avatar.executor_email }}</span>
                    {% if avatar.executor_email_verified %}
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-900/50 text-green-400 border border-green-700">
                        &#10003; Verified
                    </span>
                    {% else %}
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-900/50 text-amber-300 border border-amber-700">
                        &#9888; Not verified
                    </span>
                    {% endif %}
                </div>
                {% else %}
                <span class="text-sm text-gray-500 italic">No executor email configured &mdash; email tasks will not be sent for this avatar</span>
                {% endif %}
            </div>

            <form method="post" action="/admin/avatars/{{ avatar.id }}/executor-email" class="space-y-3">
                <div class="flex items-end gap-3">
                    <div class="flex-1">
                        <label class="block text-sm font-medium text-gray-300 mb-1">Executor Email</label>
                        <input type="email" name="executor_email" value="{{ avatar.executor_email or '' }}"
                               placeholder="worker@example.com"
                               class="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500">
                    </div>
                    <button type="submit" class="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-500 transition-colors">
                        Save
                    </button>
                </div>
                <p class="text-[11px] text-gray-500">The person who manually posts content from this Reddit account. Changing the email resets verification status.</p>
            </form>

            {% if avatar.executor_email and not avatar.executor_email_verified %}
            <div class="mt-4 flex items-center gap-3">
                <form method="post" action="/admin/avatars/{{ avatar.id }}/executor-email/verify" class="inline">
                    <button type="submit" class="px-3 py-2 rounded-lg text-sm font-medium bg-green-900/50 text-green-300 border border-green-700 hover:bg-green-800/50 transition-colors">
                        &#10003; Mark as Verified
                    </button>
                </form>
                <span class="text-[11px] text-gray-500">Confirm this email belongs to the avatar owner</span>
            </div>
            {% elif avatar.executor_email and avatar.executor_email_verified %}
            <div class="mt-4">
                <form method="post" action="/admin/avatars/{{ avatar.id }}/executor-email/unverify" class="inline">
                    <button type="submit" class="px-3 py-1.5 rounded text-xs font-medium text-gray-400 hover:text-red-300 border border-slate-700 hover:border-red-700 transition-colors">
                        Revoke Verification
                    </button>
                </form>
            </div>
            {% endif %}
        </div>

'''

content = content[:idx] + new_section + content[idx:]
template_path.write_text(content)
print("SUCCESS: Executor email section inserted.")
