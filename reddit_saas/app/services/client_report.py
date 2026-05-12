"""Client report generator — produces Markdown reports for client delivery.

Generates a structured assessment with pipeline stats, avatar performance,
subreddit coverage, AI costs, and actionable recommendations.
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, case, desc
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.models.scrape_log import ScrapeLog
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.ai_usage import AIUsageLog
from app.models.subreddit import ClientSubredditAssignment, Subreddit


def _profile_completeness(client: Client) -> tuple[int, int, list[str]]:
    """Return (filled_count, total_count, missing_fields)."""
    fields = [
        ("company_profile", "Company Profile"),
        ("company_worldview", "Company Worldview"),
        ("company_problem", "Company Problem"),
        ("competitive_landscape", "Competitive Landscape"),
        ("brand_voice", "Brand Voice"),
        ("icp_profiles", "ICP Profiles"),
        ("keywords", "Keywords"),
    ]
    filled = 0
    missing = []
    for attr, label in fields:
        val = getattr(client, attr, None)
        if val:
            filled += 1
        else:
            missing.append(label)
    return filled, len(fields), missing


def _score_client_profile(client: Client) -> dict:
    """Score client profile quality (1-5) with comments."""
    filled, total, missing = _profile_completeness(client)

    # Profile completeness
    completeness_score = min(5, max(1, round(filled / total * 5)))
    completeness_comment = f"{filled}/{total} fields filled"
    if missing:
        completeness_comment += f". Missing: {', '.join(missing)}"

    # Company profile depth
    profile_len = len(client.company_profile or "")
    if profile_len == 0:
        profile_score = 1
        profile_comment = "Not filled — AI cannot understand the brand"
    elif profile_len < 200:
        profile_score = 3
        profile_comment = f"{profile_len} chars — too short, needs more context"
    elif profile_len <= 1500:
        profile_score = 5
        profile_comment = f"{profile_len} chars — good depth"
    else:
        profile_score = 4
        profile_comment = f"{profile_len} chars — could be condensed"

    # Keywords assessment
    keywords = client.keywords or {}
    total_kw = sum(len(v) for v in keywords.values()) if isinstance(keywords, dict) else 0
    if total_kw == 0:
        kw_score = 1
        kw_comment = "No keywords — scoring pipeline cannot function"
    elif total_kw < 5:
        kw_score = 3
        kw_comment = f"{total_kw} keywords — too few for good coverage"
    elif total_kw <= 30:
        kw_score = 5
        kw_comment = f"{total_kw} keywords — good coverage"
    else:
        kw_score = 4
        kw_comment = f"{total_kw} keywords — consider pruning low-performers"

    # ICP assessment
    icp_len = len(client.icp_profiles or "")
    if icp_len == 0:
        icp_score = 1
        icp_comment = "Not filled — AI cannot target the right audience"
    elif icp_len < 100:
        icp_score = 3
        icp_comment = "Too short, needs more detail on target personas"
    else:
        icp_score = 5
        icp_comment = "ICP defined"

    return {
        "completeness": {"score": completeness_score, "comment": completeness_comment},
        "company_profile": {"score": profile_score, "comment": profile_comment},
        "keywords": {"score": kw_score, "comment": kw_comment},
        "icp_profiles": {"score": icp_score, "comment": icp_comment},
    }


def _get_pipeline_stats(db: Session, client_id: uuid.UUID, days: int = 30) -> dict:
    """Get pipeline stats for the last N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Comment drafts by status
    stats = (
        db.query(
            func.count(CommentDraft.id).label("total"),
            func.count(case((CommentDraft.status == "posted", 1))).label("posted"),
            func.count(case((CommentDraft.status == "approved", 1))).label("approved"),
            func.count(case((CommentDraft.status == "rejected", 1))).label("rejected"),
            func.count(case((CommentDraft.status == "pending", 1))).label("pending"),
            func.count(case((CommentDraft.type == "hobby", 1))).label("hobby"),
            func.count(case((CommentDraft.type == "professional", 1))).label("professional"),
            func.avg(CommentDraft.reddit_score).label("avg_score"),
            func.max(CommentDraft.reddit_score).label("max_score"),
        )
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.created_at >= since,
        )
        .first()
    )

    # Threads scraped
    threads_count = (
        db.query(func.count(RedditThread.id))
        .filter(
            RedditThread.client_id == client_id,
            RedditThread.scraped_at >= since,
        )
        .scalar()
    ) or 0

    # Threads tagged "engage"
    engage_count = (
        db.query(func.count(RedditThread.id))
        .filter(
            RedditThread.client_id == client_id,
            RedditThread.tag == "engage",
            RedditThread.scraped_at >= since,
        )
        .scalar()
    ) or 0

    return {
        "period_days": days,
        "threads_scraped": threads_count,
        "threads_engage": engage_count,
        "total_drafts": stats.total if stats else 0,
        "posted": stats.posted if stats else 0,
        "approved": stats.approved if stats else 0,
        "rejected": stats.rejected if stats else 0,
        "pending": stats.pending if stats else 0,
        "hobby_comments": stats.hobby if stats else 0,
        "professional_comments": stats.professional if stats else 0,
        "avg_score": round(float(stats.avg_score), 1) if stats and stats.avg_score else 0,
        "max_score": stats.max_score if stats and stats.max_score else 0,
    }


def _get_avatar_summary(db: Session, client_id: uuid.UUID, days: int = 30) -> list[dict]:
    """Get per-avatar performance summary."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)))
        .all()
    )

    result = []
    for avatar in avatars:
        stats = (
            db.query(
                func.count(CommentDraft.id).label("total"),
                func.count(case((CommentDraft.status == "posted", 1))).label("posted"),
                func.count(case((CommentDraft.status == "rejected", 1))).label("rejected"),
                func.avg(CommentDraft.reddit_score).label("avg_score"),
            )
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.client_id == client_id,
                CommentDraft.created_at >= since,
            )
            .first()
        )

        result.append({
            "username": avatar.reddit_username,
            "phase": avatar.warming_phase,
            "karma": avatar.reddit_karma_comment,
            "is_frozen": avatar.is_frozen,
            "freeze_reason": avatar.freeze_reason,
            "health_status": avatar.health_status,
            "total_drafts": stats.total if stats else 0,
            "posted": stats.posted if stats else 0,
            "rejected": stats.rejected if stats else 0,
            "avg_score": round(float(stats.avg_score), 1) if stats and stats.avg_score else 0,
        })

    return sorted(result, key=lambda x: x["posted"], reverse=True)


def _get_subreddit_performance(db: Session, client_id: uuid.UUID, days: int = 30) -> list[dict]:
    """Get per-subreddit performance from posted comments."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            RedditThread.subreddit,
            func.count(CommentDraft.id).label("comments"),
            func.avg(CommentDraft.reddit_score).label("avg_score"),
            func.max(CommentDraft.reddit_score).label("max_score"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status == "posted",
            CommentDraft.created_at >= since,
        )
        .group_by(RedditThread.subreddit)
        .order_by(desc(func.count(CommentDraft.id)))
        .all()
    )

    return [
        {
            "subreddit": r.subreddit,
            "comments": r.comments,
            "avg_score": round(float(r.avg_score), 1) if r.avg_score else 0,
            "max_score": r.max_score or 0,
        }
        for r in rows
    ]


def _get_ai_cost_summary(db: Session, client_id: uuid.UUID, days: int = 30) -> dict:
    """Get AI cost summary for the client."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stats = (
        db.query(
            func.count(AIUsageLog.id).label("total_calls"),
            func.sum(AIUsageLog.cost_usd).label("total_cost"),
            func.sum(AIUsageLog.input_tokens).label("total_input_tokens"),
            func.sum(AIUsageLog.output_tokens).label("total_output_tokens"),
        )
        .filter(
            AIUsageLog.client_id == client_id,
            AIUsageLog.created_at >= since,
        )
        .first()
    )

    # By operation
    by_operation = (
        db.query(
            AIUsageLog.operation,
            func.count(AIUsageLog.id).label("calls"),
            func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .filter(
            AIUsageLog.client_id == client_id,
            AIUsageLog.created_at >= since,
        )
        .group_by(AIUsageLog.operation)
        .order_by(desc(func.sum(AIUsageLog.cost_usd)))
        .all()
    )

    return {
        "period_days": days,
        "total_calls": stats.total_calls if stats else 0,
        "total_cost_usd": round(float(stats.total_cost), 4) if stats and stats.total_cost else 0,
        "total_input_tokens": stats.total_input_tokens if stats else 0,
        "total_output_tokens": stats.total_output_tokens if stats else 0,
        "by_operation": [
            {
                "operation": r.operation,
                "calls": r.calls,
                "cost_usd": round(float(r.cost), 4) if r.cost else 0,
            }
            for r in by_operation
        ],
    }


def _get_top_comments(db: Session, client_id: uuid.UUID, limit: int = 10) -> list[dict]:
    """Get top-performing posted comments by Reddit score."""
    rows = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status == "posted",
            CommentDraft.reddit_score.isnot(None),
        )
        .order_by(desc(CommentDraft.reddit_score))
        .limit(limit)
        .all()
    )

    return [
        {
            "subreddit": draft.thread.subreddit if draft.thread else "?",
            "thread_title": (draft.thread.post_title[:80] + "...") if draft.thread and len(draft.thread.post_title or "") > 80 else (draft.thread.post_title if draft.thread else "?"),
            "comment_text": (draft.edited_draft or draft.ai_draft or "")[:200],
            "reddit_score": draft.reddit_score,
            "approach": draft.comment_approach,
            "posted_at": draft.posted_at,
        }
        for draft in rows
    ]


def _get_scoring_summary(db: Session, client_id: uuid.UUID, days: int = 30) -> dict:
    """Get scoring pipeline summary — how threads are being evaluated."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stats = (
        db.query(
            func.count(ThreadScore.id).label("total"),
            func.count(case((ThreadScore.tag == "engage", 1))).label("engage"),
            func.count(case((ThreadScore.tag == "monitor", 1))).label("monitor"),
            func.count(case((ThreadScore.tag == "skip", 1))).label("skip"),
            func.avg(ThreadScore.relevance).label("avg_relevance"),
            func.avg(ThreadScore.quality).label("avg_quality"),
            func.avg(ThreadScore.strategic).label("avg_strategic"),
            func.avg(ThreadScore.composite).label("avg_composite"),
        )
        .filter(
            ThreadScore.client_id == client_id,
            ThreadScore.scored_at >= since,
        )
        .first()
    )

    # Top intents
    intents = (
        db.query(
            ThreadScore.intent,
            func.count(ThreadScore.id).label("count"),
        )
        .filter(
            ThreadScore.client_id == client_id,
            ThreadScore.scored_at >= since,
            ThreadScore.intent.isnot(None),
        )
        .group_by(ThreadScore.intent)
        .order_by(desc(func.count(ThreadScore.id)))
        .limit(10)
        .all()
    )

    return {
        "total_scored": stats.total if stats else 0,
        "engage": stats.engage if stats else 0,
        "monitor": stats.monitor if stats else 0,
        "skip": stats.skip if stats else 0,
        "avg_relevance": round(float(stats.avg_relevance), 1) if stats and stats.avg_relevance else 0,
        "avg_quality": round(float(stats.avg_quality), 1) if stats and stats.avg_quality else 0,
        "avg_strategic": round(float(stats.avg_strategic), 1) if stats and stats.avg_strategic else 0,
        "avg_composite": round(float(stats.avg_composite), 1) if stats and stats.avg_composite else 0,
        "top_intents": [{"intent": r.intent, "count": r.count} for r in intents],
    }


def _get_scraping_health(db: Session, client_id: uuid.UUID, days: int = 30) -> dict:
    """Get scraping pipeline health metrics."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stats = (
        db.query(
            func.count(ScrapeLog.id).label("total_scrapes"),
            func.sum(ScrapeLog.posts_found).label("total_found"),
            func.sum(ScrapeLog.posts_new).label("total_new"),
            func.avg(ScrapeLog.duration_ms).label("avg_duration_ms"),
            func.count(case((ScrapeLog.errors.isnot(None), 1))).label("error_count"),
        )
        .filter(
            ScrapeLog.client_id == client_id,
            ScrapeLog.scraped_at >= since,
        )
        .first()
    )

    # Per-subreddit scraping
    sub_stats = (
        db.query(
            ScrapeLog.subreddit_name,
            func.count(ScrapeLog.id).label("scrapes"),
            func.sum(ScrapeLog.posts_new).label("new_posts"),
            func.max(ScrapeLog.scraped_at).label("last_scraped"),
        )
        .filter(
            ScrapeLog.client_id == client_id,
            ScrapeLog.scraped_at >= since,
        )
        .group_by(ScrapeLog.subreddit_name)
        .order_by(desc(func.sum(ScrapeLog.posts_new)))
        .all()
    )

    return {
        "total_scrapes": stats.total_scrapes if stats else 0,
        "total_posts_found": int(stats.total_found) if stats and stats.total_found else 0,
        "total_posts_new": int(stats.total_new) if stats and stats.total_new else 0,
        "avg_duration_ms": round(float(stats.avg_duration_ms)) if stats and stats.avg_duration_ms else 0,
        "error_count": stats.error_count if stats else 0,
        "by_subreddit": [
            {
                "subreddit": r.subreddit_name,
                "scrapes": r.scrapes,
                "new_posts": int(r.new_posts) if r.new_posts else 0,
                "last_scraped": r.last_scraped,
            }
            for r in sub_stats
        ],
    }


def _get_removal_stats(db: Session, client_id: uuid.UUID) -> dict:
    """Get comment removal/deletion stats for the client."""
    posted_total = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status == "posted",
        )
        .scalar()
    ) or 0

    deleted_count = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status == "posted",
            CommentDraft.is_deleted.is_(True),
        )
        .scalar()
    ) or 0

    # Per-subreddit removal breakdown
    sub_removals = (
        db.query(
            RedditThread.subreddit,
            func.count(CommentDraft.id).label("total"),
            func.count(case((CommentDraft.is_deleted.is_(True), 1))).label("deleted"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status == "posted",
        )
        .group_by(RedditThread.subreddit)
        .having(func.count(case((CommentDraft.is_deleted.is_(True), 1))) > 0)
        .order_by(desc(func.count(case((CommentDraft.is_deleted.is_(True), 1)))))
        .all()
    )

    return {
        "posted_total": posted_total,
        "deleted_count": deleted_count,
        "removal_rate": round(deleted_count / posted_total * 100, 1) if posted_total > 0 else 0,
        "by_subreddit": [
            {
                "subreddit": r.subreddit,
                "total": r.total,
                "deleted": r.deleted,
                "rate": round(r.deleted / r.total * 100, 1) if r.total > 0 else 0,
            }
            for r in sub_removals
        ],
    }


def _get_learning_stats(db: Session, client_id: uuid.UUID, days: int = 30) -> dict:
    """Get self-learning loop stats for the client."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stats = (
        db.query(
            func.count(EditRecord.id).label("total"),
            func.count(case((EditRecord.final_status == "approved", 1))).label("approved_edited"),
            func.count(case((EditRecord.final_status == "approved_unchanged", 1))).label("approved_unchanged"),
            func.count(case((EditRecord.final_status == "rejected", 1))).label("rejected"),
        )
        .filter(
            EditRecord.client_id == client_id,
            EditRecord.created_at >= since,
        )
        .first()
    )

    # Correction patterns count
    patterns_count = (
        db.query(func.count(CorrectionPattern.id))
        .filter(CorrectionPattern.client_id == client_id)
        .scalar()
    ) or 0

    return {
        "total_edits": stats.total if stats else 0,
        "approved_edited": stats.approved_edited if stats else 0,
        "approved_unchanged": stats.approved_unchanged if stats else 0,
        "rejected": stats.rejected if stats else 0,
        "active_patterns": patterns_count,
    }


def _get_approach_performance(db: Session, client_id: uuid.UUID, days: int = 30) -> list[dict]:
    """Get performance breakdown by comment_approach for the client."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            CommentDraft.comment_approach,
            func.count(CommentDraft.id).label("total"),
            func.avg(CommentDraft.reddit_score).label("avg_score"),
            func.count(case((CommentDraft.is_deleted.is_(True), 1))).label("deleted"),
            func.count(case((CommentDraft.status == "rejected", 1))).label("rejected"),
        )
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.comment_approach.isnot(None),
            CommentDraft.created_at >= since,
        )
        .group_by(CommentDraft.comment_approach)
        .order_by(desc(func.count(CommentDraft.id)))
        .all()
    )
    return [
        {
            "approach": r.comment_approach,
            "count": r.total,
            "avg_score": round(float(r.avg_score), 1) if r.avg_score else 0,
            "deleted": r.deleted,
            "rejected": r.rejected,
        }
        for r in rows
    ]


def _generate_recommendations(
    client: Client,
    profile_scores: dict,
    pipeline: dict,
    avatars: list[dict],
    subreddits: list[dict],
) -> list[str]:
    """Generate actionable recommendations."""
    recs = []

    # Profile recommendations
    if profile_scores["company_profile"]["score"] <= 2:
        recs.append("Fill Company Profile — AI needs context to generate relevant comments")
    if profile_scores["keywords"]["score"] <= 2:
        recs.append("Add keywords — scoring pipeline cannot identify relevant threads without them")
    if profile_scores["icp_profiles"]["score"] <= 2:
        recs.append("Define ICP Profiles — helps AI target the right audience")

    # Pipeline recommendations
    if pipeline["threads_scraped"] == 0:
        recs.append("No threads scraped — check subreddit assignments and scraping schedule")
    elif pipeline["threads_engage"] == 0:
        recs.append("No threads tagged 'engage' — review scoring thresholds or keyword relevance")

    if pipeline["total_drafts"] == 0:
        recs.append("No comment drafts generated — pipeline may be paused or misconfigured")
    elif pipeline["posted"] == 0 and pipeline["approved"] > 0:
        recs.append(f"{pipeline['approved']} approved comments awaiting posting — post them to Reddit")
    elif pipeline["pending"] > 20:
        recs.append(f"{pipeline['pending']} comments pending review — review queue needs attention")

    # Rejection rate
    if pipeline["total_drafts"] > 10:
        reject_rate = pipeline["rejected"] / pipeline["total_drafts"]
        if reject_rate > 0.5:
            recs.append(f"High rejection rate ({reject_rate:.0%}) — review avatar voice profiles or keyword targeting")

    # Avatar recommendations
    frozen_avatars = [a for a in avatars if a["is_frozen"]]
    if frozen_avatars:
        names = ", ".join(f"@{a['username']}" for a in frozen_avatars)
        recs.append(f"⚠️ Frozen avatars: {names} — investigate and unfreeze if safe")

    inactive_avatars = [a for a in avatars if a["posted"] == 0 and not a["is_frozen"]]
    if inactive_avatars:
        names = ", ".join(f"@{a['username']}" for a in inactive_avatars)
        recs.append(f"Inactive avatars (0 posts): {names}")

    if not avatars:
        recs.append("No avatars assigned — assign at least one avatar to start the pipeline")

    # Subreddit recommendations
    if not subreddits:
        recs.append("No subreddit activity — check subreddit assignments")
    elif len(subreddits) == 1:
        recs.append("Activity in only 1 subreddit — diversify for natural appearance")

    # Score recommendations
    if pipeline["avg_score"] and pipeline["avg_score"] < 2:
        recs.append("Low average Reddit score — review comment quality and targeting")

    return recs if recs else ["Client pipeline in good shape, continue current strategy"]


def generate_client_report_md(db: Session, client_id: uuid.UUID) -> str | None:
    """Generate a full Markdown report for client delivery."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return None

    # Gather data
    profile_scores = _score_client_profile(client)
    pipeline = _get_pipeline_stats(db, client_id, days=30)
    avatars = _get_avatar_summary(db, client_id, days=30)
    subreddits = _get_subreddit_performance(db, client_id, days=30)
    ai_costs = _get_ai_cost_summary(db, client_id, days=30)
    top_comments = _get_top_comments(db, client_id, limit=10)
    scoring = _get_scoring_summary(db, client_id, days=30)
    scraping = _get_scraping_health(db, client_id, days=30)
    removals = _get_removal_stats(db, client_id)
    learning = _get_learning_stats(db, client_id, days=30)
    approach_perf = _get_approach_performance(db, client_id, days=30)
    recommendations = _generate_recommendations(client, profile_scores, pipeline, avatars, subreddits)

    # Subreddit assignments
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    professional_subs = [a.subreddit.subreddit_name for a in assignments if a.type == "professional"]
    hobby_subs = [a.subreddit.subreddit_name for a in assignments if a.type == "hobby"]

    # Calculate overall score
    all_scores = [
        profile_scores["completeness"]["score"],
        profile_scores["company_profile"]["score"],
        profile_scores["keywords"]["score"],
        profile_scores["icp_profiles"]["score"],
    ]
    overall_profile = round(sum(all_scores) / len(all_scores), 1)

    # Build Markdown
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []

    lines.append(f"# Client Report: {client.client_name}")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Brand:** {client.brand_name}")
    lines.append(f"**Status:** {'✅ Active' if client.is_active else '❌ Inactive'}")
    if client.brand_domain:
        lines.append(f"**Domain:** {client.brand_domain}")
    lines.append(f"**Avatars:** {len(avatars)} | **Subreddits:** {len(professional_subs)} professional + {len(hobby_subs)} hobby")
    lines.append("")

    # --- Profile Quality ---
    lines.append("## Profile Quality")
    lines.append("")
    lines.append("| Parameter | Score (1-5) | Comment |")
    lines.append("|-----------|:-----------:|---------|")
    lines.append(f"| Profile Completeness | {profile_scores['completeness']['score']} | {profile_scores['completeness']['comment']} |")
    lines.append(f"| Company Profile | {profile_scores['company_profile']['score']} | {profile_scores['company_profile']['comment']} |")
    lines.append(f"| Keywords | {profile_scores['keywords']['score']} | {profile_scores['keywords']['comment']} |")
    lines.append(f"| ICP Profiles | {profile_scores['icp_profiles']['score']} | {profile_scores['icp_profiles']['comment']} |")
    lines.append("")
    lines.append(f"**Overall Profile Score:** {overall_profile} / 5")
    lines.append("")

    # --- Pipeline Stats ---
    lines.append("## Pipeline Activity (Last 30 Days)")
    lines.append("")
    lines.append(f"- **Threads scraped:** {pipeline['threads_scraped']}")
    lines.append(f"- **Threads tagged 'engage':** {pipeline['threads_engage']}")
    lines.append(f"- **Total comment drafts:** {pipeline['total_drafts']}")
    lines.append(f"- **Posted:** {pipeline['posted']}")
    lines.append(f"- **Approved (awaiting posting):** {pipeline['approved']}")
    lines.append(f"- **Rejected:** {pipeline['rejected']}")
    lines.append(f"- **Pending review:** {pipeline['pending']}")
    lines.append(f"- **Hobby / Professional:** {pipeline['hobby_comments']} / {pipeline['professional_comments']}")
    lines.append(f"- **Avg Reddit score:** {pipeline['avg_score']}")
    lines.append(f"- **Max Reddit score:** {pipeline['max_score']}")
    lines.append("")

    # Conversion funnel
    if pipeline["threads_scraped"] > 0:
        engage_rate = pipeline["threads_engage"] / pipeline["threads_scraped"] * 100
        lines.append("### Conversion Funnel")
        lines.append("")
        lines.append(f"- Scraped → Engage: {engage_rate:.1f}%")
        if pipeline["total_drafts"] > 0:
            approval_rate = (pipeline["posted"] + pipeline["approved"]) / pipeline["total_drafts"] * 100
            lines.append(f"- Drafts → Approved/Posted: {approval_rate:.1f}%")
        lines.append("")

    # --- Scoring Intelligence ---
    if scoring["total_scored"] > 0:
        lines.append("## Scoring Intelligence")
        lines.append("")
        lines.append(f"- **Total threads scored:** {scoring['total_scored']}")
        lines.append(f"- **Tagged engage / monitor / skip:** {scoring['engage']} / {scoring['monitor']} / {scoring['skip']}")
        lines.append(f"- **Avg scores — Relevance:** {scoring['avg_relevance']} | **Quality:** {scoring['avg_quality']} | **Strategic:** {scoring['avg_strategic']} | **Composite:** {scoring['avg_composite']}")
        lines.append("")

        if scoring["top_intents"]:
            lines.append("### Thread Intents Detected")
            lines.append("")
            lines.append("| Intent | Count |")
            lines.append("|--------|:-----:|")
            for intent in scoring["top_intents"]:
                lines.append(f"| {intent['intent']} | {intent['count']} |")
            lines.append("")

    # --- Scraping Health ---
    if scraping["total_scrapes"] > 0:
        lines.append("## Scraping Health")
        lines.append("")
        lines.append(f"- **Total scrapes:** {scraping['total_scrapes']}")
        lines.append(f"- **Posts found / new:** {scraping['total_posts_found']} / {scraping['total_posts_new']}")
        lines.append(f"- **Avg scrape duration:** {scraping['avg_duration_ms']}ms")
        if scraping["error_count"] > 0:
            error_rate = round(scraping["error_count"] / scraping["total_scrapes"] * 100, 1)
            lines.append(f"- **Errors:** {scraping['error_count']} ({error_rate}%)")
        lines.append("")

        if scraping["by_subreddit"]:
            lines.append("### Scraping by Subreddit")
            lines.append("")
            lines.append("| Subreddit | Scrapes | New Posts | Last Scraped |")
            lines.append("|-----------|:-------:|:--------:|:------------:|")
            for s in scraping["by_subreddit"]:
                last = s["last_scraped"].strftime("%Y-%m-%d %H:%M") if s["last_scraped"] else "—"
                lines.append(f"| r/{s['subreddit']} | {s['scrapes']} | {s['new_posts']} | {last} |")
            lines.append("")

    # --- Comment Approach Performance ---
    if approach_perf:
        lines.append("## Comment Approach Performance")
        lines.append("")
        lines.append("| Approach | Count | Avg Score | Removed | Rejected |")
        lines.append("|----------|:-----:|:---------:|:-------:|:--------:|")
        for ap in approach_perf:
            lines.append(f"| {ap['approach']} | {ap['count']} | {ap['avg_score']} | {ap['deleted']} | {ap['rejected']} |")
        lines.append("")

    # --- Comment Removals ---
    if removals["posted_total"] > 0:
        lines.append("## Comment Removals")
        lines.append("")
        rate = removals["removal_rate"]
        status_icon = "🟢" if rate <= 10 else ("🟡" if rate <= 20 else "🔴")
        lines.append(f"- **Total posted:** {removals['posted_total']}")
        lines.append(f"- **Removed/deleted:** {removals['deleted_count']}")
        lines.append(f"- **Removal rate:** {status_icon} {rate}%")
        lines.append("")
        if removals["by_subreddit"]:
            lines.append("**Removals by subreddit:**")
            lines.append("")
            lines.append("| Subreddit | Posted | Removed | Rate |")
            lines.append("|-----------|:------:|:-------:|:----:|")
            for s in removals["by_subreddit"]:
                lines.append(f"| r/{s['subreddit']} | {s['total']} | {s['deleted']} | {s['rate']}% |")
            lines.append("")

    # --- Self-Learning Loop ---
    lines.append("## Self-Learning Loop")
    lines.append("")
    if learning["total_edits"] > 0:
        lines.append(f"- **Total edit records (30 days):** {learning['total_edits']}")
        lines.append(f"- **Approved with edits:** {learning['approved_edited']}")
        lines.append(f"- **Approved unchanged:** {learning['approved_unchanged']}")
        lines.append(f"- **Rejected:** {learning['rejected']}")
        lines.append(f"- **Active correction patterns:** {learning['active_patterns']}")
        if learning["total_edits"] > 0:
            edit_rate = round(
                learning["approved_edited"] / learning["total_edits"] * 100, 1
            )
            lines.append(f"- **Edit rate:** {edit_rate}% (lower = AI improving)")
        lines.append("")
    else:
        lines.append("*No edit records in the last 30 days.*")
        lines.append("")

    # --- Avatar Performance ---
    if avatars:
        lines.append("## Avatar Performance")
        lines.append("")
        lines.append("| Avatar | Phase | Karma | Posted | Rejected | Avg Score | Health |")
        lines.append("|--------|:-----:|:-----:|:------:|:--------:|:---------:|--------|")
        for a in avatars:
            frozen_badge = " 🧊" if a["is_frozen"] else ""
            lines.append(
                f"| @{a['username']}{frozen_badge} | {a['phase']} | {a['karma']} | "
                f"{a['posted']} | {a['rejected']} | {a['avg_score']} | {a['health_status']} |"
            )
        lines.append("")

        # Frozen avatars detail
        frozen = [a for a in avatars if a["is_frozen"]]
        if frozen:
            lines.append("### ⚠️ Frozen Avatars")
            lines.append("")
            for a in frozen:
                lines.append(f"- **@{a['username']}**: {a['freeze_reason'] or 'no reason specified'}")
            lines.append("")

    # --- Subreddit Performance ---
    if subreddits:
        lines.append("## Subreddit Performance (Posted Comments)")
        lines.append("")
        lines.append("| Subreddit | Comments | Avg Score | Max Score |")
        lines.append("|-----------|:--------:|:---------:|:---------:|")
        for s in subreddits:
            lines.append(f"| r/{s['subreddit']} | {s['comments']} | {s['avg_score']} | {s['max_score']} |")
        lines.append("")

    # --- Subreddit Coverage ---
    lines.append("## Subreddit Coverage")
    lines.append("")
    if professional_subs:
        lines.append(f"**Professional ({len(professional_subs)}):** {', '.join('r/' + s for s in professional_subs)}")
    else:
        lines.append("**Professional:** None assigned")
    lines.append("")
    if hobby_subs:
        lines.append(f"**Hobby ({len(hobby_subs)}):** {', '.join('r/' + s for s in hobby_subs)}")
    else:
        lines.append("**Hobby:** None assigned")
    lines.append("")

    # --- Top Comments ---
    if top_comments:
        lines.append("## Top Performing Comments")
        lines.append("")
        for i, c in enumerate(top_comments, 1):
            score_str = f"+{c['reddit_score']}" if c['reddit_score'] and c['reddit_score'] > 0 else str(c['reddit_score'] or 0)
            lines.append(f"### {i}. r/{c['subreddit']} — {score_str} points")
            lines.append(f"*Thread: {c['thread_title']}*")
            lines.append(f"*Approach: {c['approach'] or '—'}*")
            lines.append("")
            lines.append(f"> {c['comment_text']}")
            lines.append("")

    # --- AI Costs ---
    lines.append("## AI Costs (Last 30 Days)")
    lines.append("")
    lines.append(f"- **Total API calls:** {ai_costs['total_calls']}")
    lines.append(f"- **Total cost:** ${ai_costs['total_cost_usd']:.4f}")
    lines.append(f"- **Input tokens:** {ai_costs['total_input_tokens']:,}")
    lines.append(f"- **Output tokens:** {ai_costs['total_output_tokens']:,}")
    lines.append("")

    if ai_costs["by_operation"]:
        lines.append("| Operation | Calls | Cost |")
        lines.append("|-----------|:-----:|-----:|")
        for op in ai_costs["by_operation"]:
            lines.append(f"| {op['operation']} | {op['calls']} | ${op['cost_usd']:.4f} |")
        lines.append("")

    # --- Keywords ---
    keywords = client.keywords or {}
    if isinstance(keywords, dict) and any(keywords.values()):
        lines.append("## Keywords")
        lines.append("")
        for priority in ["high", "medium", "low"]:
            kws = keywords.get(priority, [])
            if kws:
                lines.append(f"**{priority.capitalize()}:** {', '.join(kws)}")
        lines.append("")

    # --- Recommendations ---
    lines.append("## Recommendations")
    lines.append("")
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

    lines.append("---")
    lines.append("*Report generated automatically by ThredOps Platform*")

    return "\n".join(lines)
