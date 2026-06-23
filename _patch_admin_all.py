"""Patch admin_subreddits_all.html to add risk score badge."""

path = '/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/templates/admin_subreddits_all.html'
with open(path, 'r') as f:
    content = f.read()

old = '''                    <!-- Subreddit Name -->
                    <td class="px-4 py-3">
                        <a href="/admin/subreddits/detail/{{ item.subreddit_name }}" class="text-white font-medium hover:text-indigo-400 transition-colors">r/{{ item.subreddit_name }}</a>
                    </td>'''

new = '''                    <!-- Subreddit Name -->
                    <td class="px-4 py-3">
                        <div class="flex items-center gap-2">
                            <a href="/admin/subreddits/detail/{{ item.subreddit_name }}" class="text-white font-medium hover:text-indigo-400 transition-colors">r/{{ item.subreddit_name }}</a>
                            {% if item.risk_score is not none %}
                            <a href="/admin/subreddits/{{ item.subreddit_id }}/risk-profile" title="Risk Score: {{ item.risk_score }}"
                               class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold
                                      {% if item.risk_score <= 30 %}bg-green-900/50 text-green-400 border border-green-700/50
                                      {% elif item.risk_score <= 60 %}bg-yellow-900/50 text-yellow-400 border border-yellow-700/50
                                      {% elif item.risk_score <= 80 %}bg-orange-900/50 text-orange-400 border border-orange-700/50
                                      {% else %}bg-red-900/50 text-red-400 border border-red-700/50{% endif %}">
                                {{ item.risk_score }}
                            </a>
                            {% endif %}
                        </div>
                    </td>'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)
    print('OK - replaced')
else:
    print('NOT FOUND')
