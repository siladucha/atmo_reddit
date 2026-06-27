"""Admin routes for per-subreddit ban management.

Provides:
- GET /admin/avatars/{id}/subreddit-bans — list bans (HTMX partial)
- POST /admin/avatars/{id}/subreddit-bans/add — manual ban
- POST /admin/avatars/{id}/subreddit-bans/{ban_id}/unban — manual unban
- POST /admin/avatars/{id}/subreddit-bans/{ban_id}/probe — force re-probe
"""

import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.avatar_subreddit_ban import AvatarSubredditBan
from app.services.subreddit_ban import (
    ban_avatar_from_subreddit,
    get_banned_subreddits,
    probe_single_ban,
    unban_avatar_from_subreddit,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/avatars", tags=["admin-subreddit-bans"])


@router.get("/{avatar_id}/subreddit-bans", response_class=HTMLResponse)
async def get_subreddit_bans(
    avatar_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_superuser),
):
    """Return HTMX partial listing subreddit bans for an avatar."""
    try:
        aid = uuid.UUID(avatar_id)
    except ValueError:
        return HTMLResponse('<div class="text-red-400">Invalid avatar ID</div>')

    avatar = db.query(Avatar).filter(Avatar.id == aid).first()
    if not avatar:
        return HTMLResponse('<div class="text-red-400">Avatar not found</div>')

    bans = (
        db.query(AvatarSubredditBan)
        .filter(AvatarSubredditBan.avatar_id == aid)
        .order_by(AvatarSubredditBan.is_active.desc(), AvatarSubredditBan.banned_at.desc())
        .all()
    )

    # Build HTML partial
    if not bans:
        html = """
        <div class="text-slate-400 text-sm italic py-2">
            No subreddit bans detected for this avatar.
        </div>
        """
    else:
        rows = []
        for ban in bans:
            status_badge = (
                '<span class="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400">Active</span>'
                if ban.is_active
                else '<span class="px-2 py-0.5 text-xs rounded bg-green-500/20 text-green-400">Lifted</span>'
            )
            source_badge = (
                '<span class="text-xs text-yellow-400">auto</span>'
                if ban.ban_source == "auto_detected"
                else '<span class="text-xs text-blue-400">manual</span>'
            )
            probe_info = ""
            if ban.last_probe_at:
                probe_info = f'<span class="text-xs text-slate-500">Last probe: {ban.last_probe_at.strftime("%Y-%m-%d")} → {ban.last_probe_result}</span>'

            actions = ""
            if ban.is_active:
                actions = f"""
                <form hx-post="/admin/avatars/{avatar_id}/subreddit-bans/{ban.id}/unban"
                      hx-target="#subreddit-bans-panel" hx-swap="innerHTML" class="inline">
                    <button type="submit" class="text-xs text-green-400 hover:text-green-300 underline">Unban</button>
                </form>
                <form hx-post="/admin/avatars/{avatar_id}/subreddit-bans/{ban.id}/probe"
                      hx-target="#subreddit-bans-panel" hx-swap="innerHTML" class="inline ml-2">
                    <button type="submit" class="text-xs text-blue-400 hover:text-blue-300 underline">Re-check</button>
                </form>
                """

            rows.append(f"""
            <tr class="border-b border-slate-700/50">
                <td class="py-2 px-3 text-sm text-slate-200">r/{ban.subreddit}</td>
                <td class="py-2 px-3">{status_badge} {source_badge}</td>
                <td class="py-2 px-3 text-xs text-slate-400">{ban.banned_at.strftime("%Y-%m-%d %H:%M") if ban.banned_at else '-'}</td>
                <td class="py-2 px-3 text-xs text-slate-400">{ban.consecutive_deletions}</td>
                <td class="py-2 px-3">{probe_info}</td>
                <td class="py-2 px-3">{actions}</td>
            </tr>
            """)

        html = f"""
        <table class="w-full text-sm">
            <thead>
                <tr class="text-slate-400 text-xs uppercase border-b border-slate-700">
                    <th class="py-2 px-3 text-left">Subreddit</th>
                    <th class="py-2 px-3 text-left">Status</th>
                    <th class="py-2 px-3 text-left">Banned At</th>
                    <th class="py-2 px-3 text-left">Deletions</th>
                    <th class="py-2 px-3 text-left">Probe</th>
                    <th class="py-2 px-3 text-left">Actions</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """

    # Add manual ban form
    html += f"""
    <div class="mt-4 pt-3 border-t border-slate-700">
        <form hx-post="/admin/avatars/{avatar_id}/subreddit-bans/add"
              hx-target="#subreddit-bans-panel" hx-swap="innerHTML"
              class="flex items-center gap-2">
            <input type="text" name="subreddit" placeholder="subreddit name (e.g. Juve)"
                   class="bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200
                          placeholder-slate-500 focus:border-blue-500 focus:outline-none w-48" required>
            <button type="submit"
                    class="px-3 py-1.5 text-xs bg-red-600 hover:bg-red-700 text-white rounded">
                Add Ban
            </button>
        </form>
    </div>
    """

    return HTMLResponse(html)


@router.post("/{avatar_id}/subreddit-bans/add", response_class=HTMLResponse)
async def add_subreddit_ban(
    avatar_id: str,
    subreddit: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_superuser),
):
    """Manually ban an avatar from a subreddit."""
    try:
        aid = uuid.UUID(avatar_id)
    except ValueError:
        return HTMLResponse('<div class="text-red-400">Invalid avatar ID</div>')

    ban_avatar_from_subreddit(db, aid, subreddit, source="manual")

    # Return updated list
    return await get_subreddit_bans(avatar_id, db, current_user)


@router.post("/{avatar_id}/subreddit-bans/{ban_id}/unban", response_class=HTMLResponse)
async def unban_subreddit(
    avatar_id: str,
    ban_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_superuser),
):
    """Manually unban an avatar from a subreddit."""
    try:
        aid = uuid.UUID(avatar_id)
        bid = uuid.UUID(ban_id)
    except ValueError:
        return HTMLResponse('<div class="text-red-400">Invalid ID</div>')

    ban = db.query(AvatarSubredditBan).filter(AvatarSubredditBan.id == bid).first()
    if ban:
        unban_avatar_from_subreddit(db, aid, ban.subreddit, source="manual")

    return await get_subreddit_bans(avatar_id, db, current_user)


@router.post("/{avatar_id}/subreddit-bans/{ban_id}/probe", response_class=HTMLResponse)
async def probe_subreddit_ban(
    avatar_id: str,
    ban_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_superuser),
):
    """Force re-probe a specific ban."""
    try:
        bid = uuid.UUID(ban_id)
    except ValueError:
        return HTMLResponse('<div class="text-red-400">Invalid ID</div>')

    ban = db.query(AvatarSubredditBan).filter(AvatarSubredditBan.id == bid).first()
    if ban:
        probe_single_ban(db, ban)

    return await get_subreddit_bans(avatar_id, db, current_user)
