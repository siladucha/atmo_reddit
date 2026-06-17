"""Patch portal.py to add karma growth + enhanced metrics endpoints."""
import re

filepath = "/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/routes/portal.py"

with open(filepath, "r") as f:
    content = f.read()

# Find the section to replace (lines ~1497-1510)
old_block = '''    metrics = {
        "comments_posted": comments_posted,
        "total_upvotes": int(total_upvotes),
        "active_subreddits": active_subreddits,
    }

    return templates.TemplateResponse(
        name="partials/client/metric_card.html",
        context={"request": request, "metrics": metrics},
        request=request,
    )


@router.get("/clients/{client_id}/partials/drafts", response_class=HTMLResponse)
def portal_drafts_partial(
    request: Request,
    client_id: UUID,
    status: str = "pending",
    avatar_id: str = "",'''

new_block = '''    # Avg upvote rate per comment
    avg_upvote = 0.0
    if comments_posted > 0:
        avg_upvote = round(int(total_upvotes) / comments_posted, 1)

    # Distinct subreddits with posted comments
    subreddits_penetrated = (
        db.query(func.count(func.distinct(RedditThread.subreddit)))
        .join(CommentDraft, CommentDraft.thread_id == RedditThread.id)
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            CommentDraft.status == "posted",
            Avatar.client_ids.any(str(client_id)),
        )
        .scalar()
    ) or 0

    metrics = {
        "comments_posted": comments_posted,
        "total_upvotes": int(total_upvotes),
        "active_subreddits": active_subreddits,
        "avg_upvote": avg_upvote,
        "subreddits_penetrated": subreddits_penetrated,
    }

    return templates.TemplateResponse(
        name="partials/client/metric_card.html",
        context={"request": request, "metrics": metrics},
        request=request,
    )


@router.get("/clients/{client_id}/partials/karma-growth", response_class=HTMLResponse)
def portal_karma_growth_partial(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return karma growth sparkline partial — daily posted comments + upvotes over 30 days."""
    from sqlalchemy import cast, Date as SQLDate

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)

    # Daily aggregates: posted count + sum of upvotes
    daily_rows = (
        db.query(
            cast(CommentDraft.posted_at, SQLDate).label("day"),
            func.count(CommentDraft.id).label("posted"),
            func.coalesce(func.sum(CommentDraft.reddit_score), 0).label("upvotes"),
        )
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.posted_at.isnot(None),
            CommentDraft.posted_at >= start,
        )
        .group_by(cast(CommentDraft.posted_at, SQLDate))
        .order_by(cast(CommentDraft.posted_at, SQLDate))
        .all()
    )

    # Build a 30-day array (fill empty days with 0)
    day_map = {r.day: {"posted": r.posted, "upvotes": int(r.upvotes)} for r in daily_rows}
    days = []
    for i in range(30):
        d = (now - timedelta(days=29 - i)).date()
        entry = day_map.get(d, {"posted": 0, "upvotes": 0})
        days.append({"date": d.strftime("%m/%d"), "posted": entry["posted"], "upvotes": entry["upvotes"]})

    # Cumulative karma growth
    cumulative = 0
    for d in days:
        cumulative += d["upvotes"]
        d["cumulative"] = cumulative

    # Period comparison (this 30d vs previous 30d)
    prev_start = start - timedelta(days=30)
    prev_upvotes = (
        db.query(func.coalesce(func.sum(CommentDraft.reddit_score), 0))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "posted",
            CommentDraft.posted_at.isnot(None),
            CommentDraft.posted_at >= prev_start,
            CommentDraft.posted_at < start,
        )
        .scalar()
    ) or 0

    curr_upvotes = sum(d["upvotes"] for d in days)
    delta = curr_upvotes - int(prev_upvotes)
    delta_pct = round(delta / int(prev_upvotes) * 100) if int(prev_upvotes) > 0 else (100 if curr_upvotes > 0 else 0)

    return templates.TemplateResponse(
        name="partials/client/karma_growth.html",
        context={
            "request": request,
            "days": days,
            "total_upvotes_period": curr_upvotes,
            "delta": delta,
            "delta_pct": delta_pct,
        },
        request=request,
    )


@router.get("/clients/{client_id}/partials/drafts", response_class=HTMLResponse)
def portal_drafts_partial(
    request: Request,
    client_id: UUID,
    status: str = "pending",
    avatar_id: str = "",'''

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    with open(filepath, "w") as f:
        f.write(content)
    print("SUCCESS: portal.py patched with karma-growth endpoint + enhanced metrics")
else:
    print("ERROR: Could not find the old_block in portal.py")
    # Debug: show what's around line 1497
    lines = content.split('\n')
    for i in range(1495, min(1515, len(lines))):
        print(f"{i+1}: {repr(lines[i])}")
