"""Patch approve_comment in pages.py:
1. Add sync_slot_status call after draft.status = approved
2. Fix HTML response to work with DC queue outerHTML swap
"""
import pathlib

p = pathlib.Path('/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/routes/pages.py')
content = p.read_text()

# Part 1: Add sync_slot_status after db.commit() following draft.status = "approved"
old_1 = '''    draft.status = "approved"
    db.commit()
    audit_service.log_action('''

new_1 = '''    draft.status = "approved"
    db.commit()

    # Sync EPG slot status (so automated posting picks it up)
    try:
        from app.services.epg_executor import sync_slot_status
        sync_slot_status(db, draft.id, "approved")
        db.commit()
    except Exception:
        logger.warning("Failed to sync EPG slot for draft %s", comment_id, exc_info=True)

    audit_service.log_action('''

assert old_1 in content, "Part 1 old string not found"
content = content.replace(old_1, new_1, 1)

# Part 2: Replace the HTML response
old_2 = '''    # Return inline "posting mode" panel so user can mark as posted without switching tabs
    thread_url = ""
    if draft.thread and draft.thread.url:
        thread_url = draft.thread.url
    return HTMLResponse(f\'\'\'
    <div id="action-panel-{comment_id}" class="px-4 py-3 border-t border-green-700/50 bg-green-900/10">
        <div class="flex items-center gap-2 mb-2">
            <span class="text-green-400 text-xs font-medium">✓ Approved</span>
            <span class="text-gray-500 text-xs">— post to Reddit, then mark as posted:</span>
        </div>
        <form hx-post="/review/{comment_id}/posted" hx-target="#action-panel-{comment_id}" hx-swap="outerHTML"
              class="flex flex-wrap gap-2 items-center">
            <input type="url" name="reddit_comment_url" placeholder="Paste Reddit comment URL (optional)"
                   class="flex-1 min-w-[200px] px-3 py-1.5 bg-slate-night border border-slate-600 text-gray-200 rounded text-sm focus:outline-none focus:border-indigo-500">
            <button type="submit"
                    class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded text-sm font-medium">
                📤 Mark as Posted
            </button>
            {"<a href=\\\'" + thread_url + "\\' target=\\'_blank\\' rel=\\'noopener\\' class=\\'text-xs text-indigo-400 hover:text-indigo-300\\'>Open thread ↗</a>" if thread_url else ""}
        </form>
    </div>
    \\\'\\\'\\\')'''

new_2 = '''    # Build approved card response — compatible with DC queue outerHTML swap
    import html as html_module
    thread_url = ""
    thread_title = ""
    subreddit = ""
    avatar_username = ""
    comment_text = draft.edited_draft or draft.ai_draft or ""
    if draft.thread and draft.thread.url:
        thread_url = draft.thread.url
    if draft.thread:
        thread_title = (draft.thread.post_title or "")[:60]
        subreddit = draft.thread.subreddit or "?"
    if draft.avatar:
        avatar_username = draft.avatar.reddit_username or ""

    comment_text_escaped = html_module.escape(comment_text)
    thread_title_escaped = html_module.escape(thread_title)

    return HTMLResponse(f\\\'\\\'\\\'
    <div data-dc-card data-draft-id="{comment_id}"
         class="bg-dark-steel rounded-lg border border-green-700/50 overflow-hidden">
        <div class="px-4 py-3 flex items-center justify-between gap-3">
            <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 mb-1">
                    <span class="px-2 py-0.5 rounded text-[10px] font-medium bg-green-900/50 text-green-300 border border-green-700">✓ Approved</span>
                    <span class="text-[11px] text-gray-500">r/{subreddit} · u/{avatar_username}</span>
                </div>
                <div class="text-sm text-gray-300 truncate">{thread_title_escaped}</div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                {"<a href=\\\'" + thread_url + "\\' target=\\'_blank\\' rel=\\'noopener\\' class=\\'text-xs text-indigo-400 hover:text-indigo-300\\'>Reddit ↗</a>" if thread_url else ""}
                <form hx-post="/review/{comment_id}/posted" hx-target="closest [data-dc-card]" hx-swap="outerHTML"
                      class="inline-flex items-center gap-1.5">
                    <input type="url" name="reddit_comment_url" placeholder="URL"
                           class="px-2 py-1 bg-slate-900 border border-slate-600 text-gray-200 rounded text-[11px] w-28 focus:outline-none focus:border-indigo-500">
                    <button type="submit"
                            class="px-2.5 py-1 rounded text-xs font-medium bg-purple-600 hover:bg-purple-500 text-white">
                        📤 Posted
                    </button>
                </form>
            </div>
        </div>
        <details class="px-4 pb-3">
            <summary class="text-[11px] text-indigo-400 hover:text-indigo-300 cursor-pointer select-none mb-1">Show comment</summary>
            <div class="text-sm text-gray-100 leading-relaxed whitespace-pre-wrap bg-slate-900/60 border border-slate-700/50 rounded-lg px-3 py-2 select-all max-h-24 overflow-y-auto">{comment_text_escaped}</div>
        </details>
    </div>
    \\\'\\\'\\\')'''

assert old_2 in content, "Part 2 old string not found"
content = content.replace(old_2, new_2, 1)

p.write_text(content)
print("DONE - patched successfully")
'''
