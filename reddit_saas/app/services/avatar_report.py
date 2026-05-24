"""Avatar client report generator — produces Markdown reports for client delivery.

Generates a structured quality assessment with scores, strategy evaluation,
and actionable recommendations. Uses automatic metrics + optional AI analysis.
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, case, desc
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.avatar_subreddit_presence import AvatarSubredditPresence
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.models.subreddit_karma import SubredditKarma
from app.models.thread import RedditThread


def _profile_completeness(avatar: Avatar) -> tuple[int, int, list[str]]:
    """Return (filled_count, total_count, missing_fields)."""
    fields = [
        ("voice_profile_md", "Voice Profile"),
        ("tone_principles", "Tone Principles"),
        ("speech_patterns", "Speech Patterns"),
        ("vocabulary_lean", "Vocabulary Lean"),
        ("hill_i_die_on", "Hill I Die On"),
        ("helpful_mode_topics", "Helpful Mode Topics"),
        ("constraints", "Constraints"),
    ]
    filled = 0
    missing = []
    for attr, label in fields:
        if getattr(avatar, attr, None):
            filled += 1
        else:
            missing.append(label)
    return filled, len(fields), missing


def _score_profile_quality(avatar: Avatar) -> dict:
    """Score avatar profile quality (1-5) with comments."""
    filled, total, missing = _profile_completeness(avatar)

    # Profile completeness score
    completeness_score = min(5, max(1, round(filled / total * 5)))
    completeness_comment = f"{filled}/{total} fields filled"
    if missing:
        completeness_comment += f". Missing: {', '.join(missing)}"

    # Voice profile length assessment
    voice_len = len(avatar.voice_profile_md or "")
    if voice_len == 0:
        voice_score = 1
        voice_comment = "Not filled"
    elif voice_len < 500:
        voice_score = 3
        voice_comment = f"{voice_len} chars — too short, needs more detail"
    elif voice_len <= 2000:
        voice_score = 5
        voice_comment = f"{voice_len} chars — optimal length"
    elif voice_len <= 4000:
        voice_score = 4
        voice_comment = f"{voice_len} chars — good, could be condensed"
    else:
        voice_score = 3
        voice_comment = f"{voice_len} chars — too long, recommend condensing to 2000"

    # Constraints assessment
    constraints_len = len(avatar.constraints or "")
    if constraints_len == 0:
        constraints_score = 1
        constraints_comment = "Not filled — risk of unwanted content"
    elif constraints_len < 50:
        constraints_score = 3
        constraints_comment = "Too short, needs more specifics"
    else:
        constraints_score = 5
        constraints_comment = "Clear constraints defined"

    # Hill I Die On assessment
    hill = avatar.hill_i_die_on or ""
    if not hill:
        hill_score = 1
        hill_comment = "Not filled — avatar will lack personality"
    elif len(hill) < 30:
        hill_score = 3
        hill_comment = "Too short, needs a concrete stance"
    else:
        hill_score = 5
        hill_comment = f'"{hill[:60]}..." — strong hook'

    return {
        "completeness": {"score": completeness_score, "comment": completeness_comment},
        "voice_profile_md": {"score": voice_score, "comment": voice_comment},
        "constraints": {"score": constraints_score, "comment": constraints_comment},
        "hill_i_die_on": {"score": hill_score, "comment": hill_comment},
    }


def _get_activity_stats(db: Session, avatar_id: uuid.UUID, days: int = 30) -> dict:
    """Get comment/post activity stats for the last N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Comments by status
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
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.created_at >= since,
        )
        .first()
    )

    # Subreddit breakdown
    subreddit_stats = (
        db.query(
            RedditThread.subreddit,
            func.count(CommentDraft.id).label("count"),
            func.avg(CommentDraft.reddit_score).label("avg_score"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.created_at >= since,
        )
        .group_by(RedditThread.subreddit)
        .order_by(desc(func.count(CommentDraft.id)))
        .all()
    )

    return {
        "period_days": days,
        "total_drafts": stats.total if stats else 0,
        "posted": stats.posted if stats else 0,
        "approved": stats.approved if stats else 0,
        "rejected": stats.rejected if stats else 0,
        "pending": stats.pending if stats else 0,
        "hobby_comments": stats.hobby if stats else 0,
        "professional_comments": stats.professional if stats else 0,
        "avg_score": round(float(stats.avg_score), 1) if stats and stats.avg_score else 0,
        "max_score": stats.max_score if stats else 0,
        "subreddit_breakdown": [
            {"subreddit": r.subreddit, "count": r.count, "avg_score": round(float(r.avg_score), 1) if r.avg_score else 0}
            for r in subreddit_stats
        ],
    }


def _score_activity(stats: dict) -> dict:
    """Score activity level (1-5)."""
    posted = stats["posted"]
    if posted == 0:
        return {"score": 1, "comment": "0 comments in period — avatar inactive"}
    elif posted < 10:
        return {"score": 2, "comment": f"{posted} comments — too few for warming"}
    elif posted < 25:
        return {"score": 3, "comment": f"{posted} comments — okay, could be more"}
    elif posted < 50:
        return {"score": 4, "comment": f"{posted} comments/month — good activity"}
    else:
        return {"score": 5, "comment": f"{posted} comments — excellent activity"}


def _get_karma_breakdown(db: Session, avatar_id: uuid.UUID) -> list[dict]:
    """Get per-subreddit karma breakdown with deltas."""
    rows = (
        db.query(SubredditKarma)
        .filter(SubredditKarma.avatar_id == avatar_id)
        .order_by(desc(SubredditKarma.comment_karma))
        .all()
    )
    return [
        {
            "subreddit": r.subreddit_name,
            "type": r.subreddit_type,
            "comment_karma": r.comment_karma,
            "post_karma": r.post_karma,
            "total": r.total_karma,
            "delta": r.total_delta,
            "comment_count": r.comment_count,
            "last_updated": r.last_updated_at,
        }
        for r in rows
    ]


def _get_presence_data(db: Session, avatar_id: uuid.UUID) -> list[dict]:
    """Get Reddit presence scan data (actual Reddit history)."""
    rows = (
        db.query(AvatarSubredditPresence)
        .filter(AvatarSubredditPresence.avatar_id == avatar_id)
        .order_by(desc(AvatarSubredditPresence.total_karma))
        .all()
    )
    return [
        {
            "subreddit": r.subreddit_name,
            "comment_count": r.comment_count,
            "total_karma": r.total_karma,
            "last_activity": r.last_activity_at,
        }
        for r in rows
    ]


def _get_correction_patterns(db: Session, avatar_id: uuid.UUID) -> list[dict]:
    """Get active learned correction patterns."""
    rows = (
        db.query(CorrectionPattern)
        .filter(CorrectionPattern.avatar_id == avatar_id)
        .order_by(desc(CorrectionPattern.frequency))
        .all()
    )
    return [
        {
            "type": r.pattern_type,
            "rule": r.rule_text,
            "frequency": r.frequency,
            "last_seen": r.last_seen_at,
        }
        for r in rows
    ]


def _get_learning_stats(db: Session, avatar_id: uuid.UUID, days: int = 30) -> dict:
    """Get self-learning loop stats (edit records)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stats = (
        db.query(
            func.count(EditRecord.id).label("total"),
            func.count(case((EditRecord.final_status == "approved", 1))).label("approved_edited"),
            func.count(case((EditRecord.final_status == "approved_unchanged", 1))).label("approved_unchanged"),
            func.count(case((EditRecord.final_status == "rejected", 1))).label("rejected"),
        )
        .filter(
            EditRecord.avatar_id == avatar_id,
            EditRecord.created_at >= since,
        )
        .first()
    )

    return {
        "total_edits": stats.total if stats else 0,
        "approved_edited": stats.approved_edited if stats else 0,
        "approved_unchanged": stats.approved_unchanged if stats else 0,
        "rejected": stats.rejected if stats else 0,
    }


def _get_removal_stats(db: Session, avatar_id: uuid.UUID) -> dict:
    """Get comment removal/deletion stats."""
    posted_total = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
        )
        .scalar()
    ) or 0

    deleted_count = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar_id,
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
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
        )
        .group_by(RedditThread.subreddit)
        .having(func.count(CommentDraft.id) >= 2)
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
            if r.deleted > 0
        ],
    }


def _get_approach_performance(db: Session, avatar_id: uuid.UUID) -> list[dict]:
    """Get performance breakdown by comment_approach."""
    rows = (
        db.query(
            CommentDraft.comment_approach,
            func.count(CommentDraft.id).label("total"),
            func.avg(CommentDraft.reddit_score).label("avg_score"),
            func.count(case((CommentDraft.is_deleted.is_(True), 1))).label("deleted"),
        )
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.comment_approach.isnot(None),
        )
        .group_by(CommentDraft.comment_approach)
        .order_by(desc(func.avg(CommentDraft.reddit_score)))
        .all()
    )
    return [
        {
            "approach": r.comment_approach,
            "count": r.total,
            "avg_score": round(float(r.avg_score), 1) if r.avg_score else 0,
            "deleted": r.deleted,
        }
        for r in rows
    ]


def _generate_recommendations(avatar: Avatar, profile_scores: dict, activity: dict) -> list[str]:
    """Generate actionable recommendations based on scores."""
    recs = []

    # Profile recommendations
    if profile_scores["voice_profile_md"]["score"] <= 3 and len(avatar.voice_profile_md or "") > 3000:
        recs.append(f"Condense voice_profile to 1500-2000 chars (currently {len(avatar.voice_profile_md or '')})")
    if profile_scores["voice_profile_md"]["score"] <= 2:
        recs.append("Fill Voice Profile — without it AI generates generic comments")
    if profile_scores["constraints"]["score"] <= 2:
        recs.append("Add Constraints — without them avatar may generate unwanted content")
    if profile_scores["hill_i_die_on"]["score"] <= 2:
        recs.append("Add Hill I Die On — makes the avatar recognizable and authentic")

    # Activity recommendations
    if activity["posted"] == 0:
        recs.append("Start comment generation — avatar is inactive")
    elif activity["posted"] < 15:
        recs.append(f"Increase activity (currently {activity['posted']} comments/month, recommend 25+)")

    # Subreddit recommendations
    if activity["subreddit_breakdown"]:
        top_sub = activity["subreddit_breakdown"][0]
        if top_sub["avg_score"] > 3:
            recs.append(f"Increase comments in r/{top_sub['subreddit']} (higher upvotes there, avg {top_sub['avg_score']})")

    # Hobby vs professional balance
    if activity["hobby_comments"] == 0 and activity["posted"] > 0:
        recs.append("Add hobby comments for natural profile appearance")

    # Karma
    if avatar.reddit_karma_comment < 50:
        recs.append("Karma below 50 — needs active warming in hobby subs")

    # Phase
    if avatar.warming_phase == 1 and activity["posted"] > 30:
        recs.append("Avatar ready for Phase 2 — sufficient activity for transition")

    # Frozen
    if avatar.is_frozen:
        recs.append(f"⚠️ Avatar is frozen: {avatar.freeze_reason or 'no reason specified'}")

    return recs if recs else ["Avatar in good shape, continue current strategy"]


def generate_avatar_report_md(db: Session, avatar_id: uuid.UUID) -> str | None:
    """Generate a full Markdown report for client delivery."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return None

    # Gather data
    profile_scores = _score_profile_quality(avatar)
    activity = _get_activity_stats(db, avatar_id, days=30)
    activity_score = _score_activity(activity)
    karma_breakdown = _get_karma_breakdown(db, avatar_id)
    presence_data = _get_presence_data(db, avatar_id)
    correction_patterns = _get_correction_patterns(db, avatar_id)
    learning_stats = _get_learning_stats(db, avatar_id, days=30)
    removal_stats = _get_removal_stats(db, avatar_id)
    approach_perf = _get_approach_performance(db, avatar_id)
    recommendations = _generate_recommendations(avatar, profile_scores, activity)

    # Assigned clients
    client_names = []
    if avatar.client_ids:
        for cid in avatar.client_ids:
            try:
                c = db.query(Client).filter(Client.id == uuid.UUID(cid)).first()
                if c:
                    client_names.append(c.client_name or c.brand_name or str(c.id)[:8])
            except (ValueError, AttributeError):
                pass

    # Calculate overall score
    all_scores = [
        profile_scores["completeness"]["score"],
        profile_scores["voice_profile_md"]["score"],
        profile_scores["constraints"]["score"],
        profile_scores["hill_i_die_on"]["score"],
        activity_score["score"],
    ]
    overall = round(sum(all_scores) / len(all_scores), 1)

    # Build Markdown
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []

    lines.append(f"# Avatar Report: @{avatar.reddit_username}")
    lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Phase:** {avatar.warming_phase} | **Status:** {avatar.reddit_status} | **Karma:** {avatar.reddit_karma_comment} comment / {avatar.reddit_karma_post} post")
    if avatar.cqs_level:
        lines.append(f"**CQS (Contributor Quality Score):** {avatar.cqs_level}")
    if client_names:
        lines.append(f"**Clients:** {', '.join(client_names)}")
    if avatar.is_frozen:
        lines.append(f"**⚠️ FROZEN:** {avatar.freeze_reason or 'no reason'}")
    lines.append("")

    # --- Profile Quality ---
    lines.append("## Profile Quality")
    lines.append("")
    lines.append("| Parameter | Score (1-5) | Comment |")
    lines.append("|-----------|:-----------:|---------|")
    lines.append(f"| Profile Completeness | {profile_scores['completeness']['score']} | {profile_scores['completeness']['comment']} |")
    lines.append(f"| Voice Profile | {profile_scores['voice_profile_md']['score']} | {profile_scores['voice_profile_md']['comment']} |")
    lines.append(f"| Constraints | {profile_scores['constraints']['score']} | {profile_scores['constraints']['comment']} |")
    lines.append(f"| Hill I Die On | {profile_scores['hill_i_die_on']['score']} | {profile_scores['hill_i_die_on']['comment']} |")
    lines.append(f"| Activity (30 days) | {activity_score['score']} | {activity_score['comment']} |")
    lines.append("")
    lines.append(f"**Overall:** {overall} / 5")
    lines.append("")

    # --- Profile Completeness Detail ---
    filled, total_fields, missing_fields = _profile_completeness(avatar)
    pct = int(round(filled / total_fields * 100)) if total_fields > 0 else 0
    if missing_fields:
        lines.append("### ⚠️ Unfilled Profile Fields")
        lines.append("")
        lines.append(f"**{filled}/{total_fields} fields filled ({pct}%)** — missing fields reduce generation quality:")
        lines.append("")
        field_impacts = {
            "Voice Profile": "Core personality — without it, comments sound generic",
            "Tone Principles": "Defines emotional register and communication style",
            "Speech Patterns": "Unique phrasing that makes avatar recognizable",
            "Vocabulary Lean": "Word choice preferences (technical vs casual)",
            "Hill I Die On": "Strong opinion that gives avatar personality depth",
            "Helpful Mode Topics": "Expertise areas for authoritative answers",
            "Constraints": "Safety guardrails — without them, off-brand content risk",
        }
        for field_name in missing_fields:
            impact = field_impacts.get(field_name, "")
            lines.append(f"- ❌ **{field_name}** — {impact}")
        lines.append("")
    else:
        lines.append("### ✅ Profile Complete")
        lines.append("")
        lines.append(f"All {total_fields} profile fields are filled. Generation quality is maximized.")
        lines.append("")

    # --- Activity Stats ---
    lines.append("## Activity (Last 30 Days)")
    lines.append("")
    lines.append(f"- **Total drafts:** {activity['total_drafts']}")
    lines.append(f"- **Posted:** {activity['posted']}")
    lines.append(f"- **Approved (awaiting posting):** {activity['approved']}")
    lines.append(f"- **Rejected:** {activity['rejected']}")
    lines.append(f"- **Pending review:** {activity['pending']}")
    lines.append(f"- **Hobby / Professional:** {activity['hobby_comments']} / {activity['professional_comments']}")
    lines.append(f"- **Avg Reddit score:** {activity['avg_score']}")
    lines.append(f"- **Max Reddit score:** {activity['max_score']}")
    lines.append("")

    # --- Subreddit Breakdown ---
    if activity["subreddit_breakdown"]:
        lines.append("## Subreddit Activity")
        lines.append("")
        lines.append("| Subreddit | Comments | Avg Score |")
        lines.append("|-----------|:--------:|:---------:|")
        for sub in activity["subreddit_breakdown"]:
            lines.append(f"| r/{sub['subreddit']} | {sub['count']} | {sub['avg_score']} |")
        lines.append("")

    # --- Karma Breakdown (per-subreddit) ---
    if karma_breakdown:
        lines.append("## Karma Breakdown (Per Subreddit)")
        lines.append("")
        lines.append("| Subreddit | Type | Comment Karma | Post Karma | Total | Δ Delta | Comments |")
        lines.append("|-----------|------|:------------:|:---------:|:-----:|:-------:|:--------:|")
        for k in karma_breakdown:
            delta_str = f"+{k['delta']}" if k['delta'] > 0 else str(k['delta'])
            lines.append(
                f"| r/{k['subreddit']} | {k['type']} | {k['comment_karma']} | "
                f"{k['post_karma']} | {k['total']} | {delta_str} | {k['comment_count']} |"
            )
        lines.append("")

    # --- Reddit Presence (actual Reddit history scan) ---
    if presence_data:
        lines.append("## Reddit Presence (History Scan)")
        lines.append("")
        if avatar.presence_last_scanned_at:
            lines.append(f"*Last scanned: {avatar.presence_last_scanned_at.strftime('%Y-%m-%d %H:%M UTC')}*")
            lines.append("")
        lines.append("| Subreddit | Comments | Total Karma | Last Activity |")
        lines.append("|-----------|:--------:|:-----------:|:-------------:|")
        for p in presence_data[:20]:  # Top 20
            last_act = p['last_activity'].strftime('%Y-%m-%d') if p['last_activity'] else "—"
            lines.append(f"| r/{p['subreddit']} | {p['comment_count']} | {p['total_karma']} | {last_act} |")
        if len(presence_data) > 20:
            lines.append(f"| *...and {len(presence_data) - 20} more* | | | |")
        lines.append("")

    # --- Comment Approach Performance ---
    if approach_perf:
        lines.append("## Comment Approach Performance")
        lines.append("")
        lines.append("| Approach | Count | Avg Score | Removed |")
        lines.append("|----------|:-----:|:---------:|:-------:|")
        for ap in approach_perf:
            lines.append(f"| {ap['approach']} | {ap['count']} | {ap['avg_score']} | {ap['deleted']} |")
        lines.append("")

    # --- Removal Stats ---
    if removal_stats["posted_total"] > 0:
        lines.append("## Comment Removals")
        lines.append("")
        rate = removal_stats["removal_rate"]
        status_icon = "🟢" if rate <= 10 else ("🟡" if rate <= 20 else "🔴")
        lines.append(f"- **Total posted:** {removal_stats['posted_total']}")
        lines.append(f"- **Removed/deleted:** {removal_stats['deleted_count']}")
        lines.append(f"- **Removal rate:** {status_icon} {rate}%")
        lines.append("")
        if removal_stats["by_subreddit"]:
            lines.append("**Removals by subreddit:**")
            lines.append("")
            lines.append("| Subreddit | Posted | Removed | Rate |")
            lines.append("|-----------|:------:|:-------:|:----:|")
            for s in removal_stats["by_subreddit"]:
                lines.append(f"| r/{s['subreddit']} | {s['total']} | {s['deleted']} | {s['rate']}% |")
            lines.append("")

    # --- Self-Learning Loop ---
    lines.append("## Self-Learning Loop")
    lines.append("")
    if learning_stats["total_edits"] > 0:
        lines.append(f"- **Total edit records (30 days):** {learning_stats['total_edits']}")
        lines.append(f"- **Approved with edits:** {learning_stats['approved_edited']}")
        lines.append(f"- **Approved unchanged:** {learning_stats['approved_unchanged']}")
        lines.append(f"- **Rejected:** {learning_stats['rejected']}")
        if learning_stats["total_edits"] > 0:
            edit_rate = round(
                learning_stats["approved_edited"] / learning_stats["total_edits"] * 100, 1
            )
            lines.append(f"- **Edit rate:** {edit_rate}% (lower = AI improving)")
        lines.append("")
    else:
        lines.append("*No edit records in the last 30 days.*")
        lines.append("")

    # Correction patterns
    if correction_patterns:
        lines.append("### Learned Correction Patterns")
        lines.append("")
        lines.append("| Type | Rule | Frequency | Last Seen |")
        lines.append("|------|------|:---------:|:---------:|")
        for cp in correction_patterns:
            last_seen = cp['last_seen'].strftime('%Y-%m-%d') if cp['last_seen'] else "—"
            lines.append(f"| {cp['type']} | {cp['rule']} | {cp['frequency']}× | {last_seen} |")
        lines.append("")

    # --- Health ---
    lines.append("## Avatar Health")
    lines.append("")
    lines.append(f"- **Reddit Status:** {avatar.reddit_status}")
    lines.append(f"- **Shadowban:** {'⚠️ YES' if avatar.is_shadowbanned else '✅ No'}")
    lines.append(f"- **Health Check:** {avatar.health_status}")
    if avatar.last_health_check:
        lines.append(f"- **Last health check:** {avatar.last_health_check.strftime('%Y-%m-%d %H:%M UTC')}")
    if avatar.consecutive_check_failures > 0:
        lines.append(f"- **Consecutive check failures:** {avatar.consecutive_check_failures}")
    lines.append(f"- **Warming Phase:** {avatar.warming_phase}")
    if avatar.phase_changed_at:
        lines.append(f"- **Phase since:** {avatar.phase_changed_at.strftime('%Y-%m-%d')}")
    if avatar.cqs_level:
        lines.append(f"- **CQS Level:** {avatar.cqs_level}")
        if avatar.cqs_notes:
            lines.append(f"- **CQS Notes:** {avatar.cqs_notes}")
    if avatar.reddit_account_created:
        age_days = (datetime.now(timezone.utc) - avatar.reddit_account_created).days
        lines.append(f"- **Account age:** {age_days} days")
    lines.append("")

    # --- Recommendations ---
    lines.append("## Recommendations")
    lines.append("")
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

    # --- Voice Profile Summary ---
    if avatar.voice_profile_md:
        preview = avatar.voice_profile_md[:500]
        if len(avatar.voice_profile_md) > 500:
            preview += "..."
        lines.append("## Voice Profile (preview)")
        lines.append("")
        lines.append("```")
        lines.append(preview)
        lines.append("```")
        lines.append("")

    # --- Strategy Document ---
    try:
        from app.models.strategy_document import StrategyDocument
        strategy = (
            db.query(StrategyDocument)
            .filter(
                StrategyDocument.avatar_id == avatar_id,
                StrategyDocument.is_current.is_(True),
            )
            .first()
        )
        if strategy:
            lines.append("## Active Strategy")
            lines.append("")
            lines.append(f"**Version:** {strategy.version} | **Generated:** {strategy.generated_at.strftime('%Y-%m-%d %H:%M UTC')} | **Model:** {strategy.model_used or 'unknown'}")
            if strategy.cost_usd:
                lines.append(f"**Generation cost:** ${strategy.cost_usd:.4f}")
            lines.append("")

            # Goals
            if strategy.goals:
                lines.append("### Goals")
                lines.append("")
                for goal in strategy.goals:
                    if isinstance(goal, dict):
                        lines.append(f"- {goal.get('objective', str(goal))} → {goal.get('target', '')}")
                    else:
                        lines.append(f"- {goal}")
                lines.append("")

            # Subreddit Priorities
            if strategy.subreddit_priorities:
                lines.append("### Subreddit Priorities")
                lines.append("")
                lines.append("| Subreddit | Frequency | Type |")
                lines.append("|-----------|-----------|------|")
                for sub in strategy.subreddit_priorities:
                    if isinstance(sub, dict):
                        lines.append(f"| r/{sub.get('subreddit', '?')} | {sub.get('frequency', '?')} | {sub.get('type', '?')} |")
                    else:
                        lines.append(f"| {sub} | — | — |")
                lines.append("")

            # Tone
            if strategy.tone_guidelines and isinstance(strategy.tone_guidelines, dict):
                lines.append("### Tone Guidelines")
                lines.append("")
                tg = strategy.tone_guidelines
                lines.append(f"- **Formality:** {tg.get('formality', '?')}")
                lines.append(f"- **Humor:** {tg.get('humor', '?')}")
                lines.append(f"- **Expertise:** {tg.get('expertise_level', '?')}")
                if tg.get('avoid'):
                    lines.append(f"- **Avoid:** {', '.join(tg['avoid'])}")
                lines.append("")

            # Hook
            if strategy.hook_inventory and isinstance(strategy.hook_inventory, dict):
                lines.append("### Hook (Hill I Die On)")
                lines.append("")
                hi = strategy.hook_inventory
                lines.append(f"- **Primary:** \"{hi.get('primary_hook', avatar.hill_i_die_on or '?')}\"")
                lines.append(f"- **Target usage:** {hi.get('usage_target_percent', 30)}%")
                if hi.get('natural_angles'):
                    lines.append(f"- **Angles:** {', '.join(hi['natural_angles'])}")
                lines.append("")

            # Full document (collapsible in markdown)
            if strategy.document_md:
                lines.append("### Full Strategy Document")
                lines.append("")
                lines.append(strategy.document_md)
                lines.append("")

            # Pipeline impact note
            lines.append("> **Note:** This strategy actively influences scoring (+20% hill alignment, -30% repeat penalty) and generation (tone, cadence, hooks injected into prompts). Auto-correction triggers on 3 consecutive negative scores.")
            lines.append("")
        else:
            lines.append("## Strategy")
            lines.append("")
            lines.append("*No strategy document generated yet. Generate one from the admin panel → Avatar → Strategy tab.*")
            lines.append("")
    except Exception:
        lines.append("## Strategy")
        lines.append("")
        lines.append("*Strategy data unavailable.*")
        lines.append("")

    lines.append("---")
    lines.append("*Report generated automatically by RAMP Platform*")

    return "\n".join(lines)
