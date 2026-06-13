"""Outcome Analysis Service — aggregates karma outcomes into actionable signals.

This is the brain of the Feedback Layer. It reads KarmaSnapshot data and produces:
1. Subreddit effectiveness scores (karma/comment by subreddit)
2. Approach effectiveness (which comment_approach yields best karma)
3. Avatar performance trends (karma trajectory over time)
4. Removal rate by subreddit (moderator pattern detection)
5. Signals for EPG re-evaluation (which subreddits to prioritize/deprioritize)
6. Signals for Discovery hypothesis validation (did confirmed hypotheses produce results?)

Key principle: this service ONLY reads and aggregates. It does not modify EPG/Discovery/Strategy
directly — it produces signals that other services consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func as sa_func, case, and_
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.comment_draft import CommentDraft
from app.models.karma_snapshot import KarmaSnapshot

logger = get_logger(__name__)


@dataclass
class SubredditSignal:
    """Effectiveness signal for a single subreddit."""
    subreddit: str
    total_comments: int = 0
    avg_karma: float = 0.0
    median_karma: float = 0.0
    removal_rate: float = 0.0  # 0.0-1.0
    avg_reply_count: float = 0.0
    karma_trend: float = 0.0  # positive = improving, negative = declining
    # Recommendation: "prioritize" | "maintain" | "reduce" | "exit"
    recommendation: str = "maintain"
    confidence: float = 0.0  # 0.0-1.0 based on sample size


@dataclass
class ApproachSignal:
    """Effectiveness signal for a comment approach."""
    approach: str
    total_comments: int = 0
    avg_karma: float = 0.0
    removal_rate: float = 0.0
    avg_reply_count: float = 0.0


@dataclass
class AvatarOutcomeProfile:
    """Aggregated outcome profile for an avatar."""
    avatar_id: UUID
    total_posted: int = 0
    total_karma: int = 0
    avg_karma: float = 0.0
    removal_rate: float = 0.0
    avg_reply_count: float = 0.0
    karma_velocity: float = 0.0  # karma per day
    subreddit_signals: list[SubredditSignal] = field(default_factory=list)
    approach_signals: list[ApproachSignal] = field(default_factory=list)
    top_performing_subreddits: list[str] = field(default_factory=list)
    underperforming_subreddits: list[str] = field(default_factory=list)


@dataclass
class OutcomeFeedbackPacket:
    """Complete feedback packet for consumption by EPG, Discovery, and Strategy.

    This is what gets passed to:
    - EPG: subreddit_priority_adjustments (boost/reduce subreddits)
    - Discovery: hypothesis_confidence_updates (validate/invalidate based on outcomes)
    - Strategy: performance_summary (for next strategy generation)
    """
    avatar_id: UUID
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    profile: AvatarOutcomeProfile | None = None
    subreddit_priority_adjustments: dict = field(default_factory=dict)  # {subreddit: delta (-1.0 to +1.0)}
    hypothesis_confidence_updates: list[dict] = field(default_factory=list)  # [{hypothesis_id, delta, reason}]
    performance_summary: dict = field(default_factory=dict)  # for strategy prompt injection


# --- Minimum thresholds for statistical confidence ---
MIN_COMMENTS_FOR_SIGNAL = 3
MIN_COMMENTS_FOR_TREND = 5
LOOKBACK_DAYS = 30
TREND_COMPARISON_DAYS = 14  # Compare last 14d vs previous 14d


def compute_avatar_outcome_profile(
    db: Session,
    avatar_id: UUID,
    lookback_days: int = LOOKBACK_DAYS,
) -> AvatarOutcomeProfile:
    """Compute full outcome profile for an avatar over the lookback window.

    Aggregates KarmaSnapshot data into subreddit signals and approach signals.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    profile = AvatarOutcomeProfile(avatar_id=avatar_id)

    # Get all posted comments with their latest karma snapshot
    posted_comments = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= cutoff,
        )
        .all()
    )

    if not posted_comments:
        return profile

    profile.total_posted = len(posted_comments)

    # Get latest snapshot per comment for current state
    comment_ids = [c.id for c in posted_comments]
    latest_snapshots = _get_latest_snapshots(db, comment_ids)

    # Aggregate overall metrics
    karma_values = []
    reply_values = []
    deletions = 0

    for draft in posted_comments:
        snapshot = latest_snapshots.get(draft.id)
        karma = snapshot.karma_value if snapshot else (draft.reddit_score or 0)
        replies = snapshot.reply_count if snapshot else 0
        is_del = snapshot.is_deleted if snapshot else draft.is_deleted

        karma_values.append(karma)
        reply_values.append(replies)
        if is_del:
            deletions += 1

    profile.total_karma = sum(karma_values)
    profile.avg_karma = sum(karma_values) / len(karma_values) if karma_values else 0
    profile.removal_rate = deletions / len(posted_comments) if posted_comments else 0
    profile.avg_reply_count = sum(reply_values) / len(reply_values) if reply_values else 0

    # Karma velocity: total karma / days active
    days_active = lookback_days
    if posted_comments:
        first_post = min(c.posted_at for c in posted_comments if c.posted_at)
        if first_post:
            days_active = max(1, (datetime.now(timezone.utc) - first_post).days)
    profile.karma_velocity = profile.total_karma / days_active

    # Subreddit breakdown
    profile.subreddit_signals = _compute_subreddit_signals(
        db, posted_comments, latest_snapshots, avatar_id
    )

    # Approach breakdown
    profile.approach_signals = _compute_approach_signals(posted_comments, latest_snapshots)

    # Top/underperforming
    sorted_subs = sorted(profile.subreddit_signals, key=lambda s: s.avg_karma, reverse=True)
    profile.top_performing_subreddits = [
        s.subreddit for s in sorted_subs[:3] if s.avg_karma > 0 and s.confidence >= 0.5
    ]
    profile.underperforming_subreddits = [
        s.subreddit for s in sorted_subs if s.recommendation == "exit"
    ]

    return profile


def generate_feedback_packet(
    db: Session,
    avatar_id: UUID,
    lookback_days: int = LOOKBACK_DAYS,
) -> OutcomeFeedbackPacket:
    """Generate a complete feedback packet for EPG/Discovery/Strategy consumption.

    This is the main entry point for the feedback loop.
    """
    profile = compute_avatar_outcome_profile(db, avatar_id, lookback_days)

    packet = OutcomeFeedbackPacket(
        avatar_id=avatar_id,
        profile=profile,
    )

    # Compute EPG subreddit priority adjustments
    packet.subreddit_priority_adjustments = _compute_subreddit_adjustments(profile)

    # Compute Discovery hypothesis confidence updates
    packet.hypothesis_confidence_updates = _compute_hypothesis_updates(db, avatar_id, profile)

    # Build performance summary for strategy injection
    packet.performance_summary = _build_performance_summary(profile)

    return packet


def _get_latest_snapshots(db: Session, comment_ids: list[UUID]) -> dict[UUID, KarmaSnapshot]:
    """Get the most recent KarmaSnapshot for each comment_draft_id."""
    if not comment_ids:
        return {}

    from sqlalchemy import distinct

    # Subquery for max checked_at per comment
    subq = (
        db.query(
            KarmaSnapshot.comment_draft_id,
            sa_func.max(KarmaSnapshot.checked_at).label("max_checked"),
        )
        .filter(KarmaSnapshot.comment_draft_id.in_(comment_ids))
        .group_by(KarmaSnapshot.comment_draft_id)
        .subquery()
    )

    snapshots = (
        db.query(KarmaSnapshot)
        .join(
            subq,
            and_(
                KarmaSnapshot.comment_draft_id == subq.c.comment_draft_id,
                KarmaSnapshot.checked_at == subq.c.max_checked,
            ),
        )
        .all()
    )

    return {s.comment_draft_id: s for s in snapshots}


def _compute_subreddit_signals(
    db: Session,
    posted_comments: list,
    latest_snapshots: dict,
    avatar_id: UUID,
) -> list[SubredditSignal]:
    """Compute per-subreddit effectiveness signals."""
    from collections import defaultdict

    # Group comments by subreddit
    sub_groups: dict[str, list] = defaultdict(list)
    for draft in posted_comments:
        sub = None
        if draft.thread:
            sub = getattr(draft.thread, "subreddit", None)
        if not sub:
            snapshot = latest_snapshots.get(draft.id)
            sub = snapshot.subreddit if snapshot else None
        if sub:
            sub_groups[sub].append(draft)

    signals = []
    for subreddit, drafts in sub_groups.items():
        signal = SubredditSignal(subreddit=subreddit, total_comments=len(drafts))

        karma_vals = []
        reply_vals = []
        deletions = 0

        for d in drafts:
            snap = latest_snapshots.get(d.id)
            k = snap.karma_value if snap else (d.reddit_score or 0)
            r = snap.reply_count if snap else 0
            is_del = snap.is_deleted if snap else d.is_deleted

            karma_vals.append(k)
            reply_vals.append(r)
            if is_del:
                deletions += 1

        signal.avg_karma = sum(karma_vals) / len(karma_vals) if karma_vals else 0
        signal.removal_rate = deletions / len(drafts) if drafts else 0
        signal.avg_reply_count = sum(reply_vals) / len(reply_vals) if reply_vals else 0

        # Confidence based on sample size
        signal.confidence = min(1.0, len(drafts) / 10.0)

        # Trend (compare recent vs older if enough data)
        signal.karma_trend = _compute_karma_trend(db, avatar_id, subreddit)

        # Recommendation logic
        signal.recommendation = _determine_recommendation(signal)

        signals.append(signal)

    return signals


def _compute_karma_trend(db: Session, avatar_id: UUID, subreddit: str) -> float:
    """Compare average karma in last 14d vs previous 14d for trend signal."""
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=TREND_COMPARISON_DAYS)
    older_start = now - timedelta(days=TREND_COMPARISON_DAYS * 2)

    recent_avg = (
        db.query(sa_func.avg(KarmaSnapshot.karma_value))
        .filter(
            KarmaSnapshot.avatar_id == avatar_id,
            KarmaSnapshot.subreddit == subreddit,
            KarmaSnapshot.checked_at >= recent_start,
        )
        .scalar()
    )

    older_avg = (
        db.query(sa_func.avg(KarmaSnapshot.karma_value))
        .filter(
            KarmaSnapshot.avatar_id == avatar_id,
            KarmaSnapshot.subreddit == subreddit,
            KarmaSnapshot.checked_at >= older_start,
            KarmaSnapshot.checked_at < recent_start,
        )
        .scalar()
    )

    if recent_avg is None or older_avg is None:
        return 0.0

    recent_avg = float(recent_avg)
    older_avg = float(older_avg)

    if older_avg == 0:
        return 1.0 if recent_avg > 0 else 0.0

    return (recent_avg - older_avg) / abs(older_avg)


def _determine_recommendation(signal: SubredditSignal) -> str:
    """Determine subreddit recommendation based on signals."""
    # Not enough data
    if signal.total_comments < MIN_COMMENTS_FOR_SIGNAL:
        return "maintain"  # Insufficient data to decide

    # High removal rate — likely moderation issue
    if signal.removal_rate > 0.3:
        return "exit"

    # Negative karma — community doesn't welcome us
    if signal.avg_karma < 0:
        return "reduce"

    # Good karma + positive trend
    if signal.avg_karma >= 5 and signal.karma_trend >= 0:
        return "prioritize"

    # Declining engagement
    if signal.karma_trend < -0.3 and signal.confidence >= 0.5:
        return "reduce"

    return "maintain"


def _compute_approach_signals(posted_comments: list, latest_snapshots: dict) -> list[ApproachSignal]:
    """Compute per-approach effectiveness signals."""
    from collections import defaultdict

    approach_groups: dict[str, list] = defaultdict(list)
    for draft in posted_comments:
        approach = draft.comment_approach or "unknown"
        approach_groups[approach].append(draft)

    signals = []
    for approach, drafts in approach_groups.items():
        signal = ApproachSignal(approach=approach, total_comments=len(drafts))

        karma_vals = []
        reply_vals = []
        deletions = 0

        for d in drafts:
            snap = latest_snapshots.get(d.id)
            k = snap.karma_value if snap else (d.reddit_score or 0)
            r = snap.reply_count if snap else 0
            is_del = snap.is_deleted if snap else d.is_deleted

            karma_vals.append(k)
            reply_vals.append(r)
            if is_del:
                deletions += 1

        signal.avg_karma = sum(karma_vals) / len(karma_vals) if karma_vals else 0
        signal.removal_rate = deletions / len(drafts) if drafts else 0
        signal.avg_reply_count = sum(reply_vals) / len(reply_vals) if reply_vals else 0

        signals.append(signal)

    return sorted(signals, key=lambda s: s.avg_karma, reverse=True)


def _compute_subreddit_adjustments(profile: AvatarOutcomeProfile) -> dict[str, float]:
    """Translate subreddit signals into priority adjustments for EPG.

    Returns dict: {subreddit_name: delta} where delta is -1.0 to +1.0.
    Positive = increase priority, negative = decrease.
    """
    adjustments = {}

    for signal in profile.subreddit_signals:
        if signal.confidence < 0.3:
            continue  # Not enough data to adjust

        if signal.recommendation == "prioritize":
            adjustments[signal.subreddit] = 0.3
        elif signal.recommendation == "reduce":
            adjustments[signal.subreddit] = -0.3
        elif signal.recommendation == "exit":
            adjustments[signal.subreddit] = -0.8

    return adjustments


def _compute_hypothesis_updates(
    db: Session,
    avatar_id: UUID,
    profile: AvatarOutcomeProfile,
) -> list[dict]:
    """Check if Discovery hypotheses are validated/invalidated by outcomes.

    For each confirmed hypothesis that mentions a subreddit we have outcome data for,
    adjust confidence based on actual karma results.
    """
    from app.models.discovery_hypothesis import DiscoveryHypothesis
    from app.models.avatar import Avatar

    updates = []

    # Get the avatar's client to find associated Discovery sessions
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar or not avatar.client_ids:
        return updates

    # For each client the avatar serves, find confirmed hypotheses
    for client_id in avatar.client_ids:
        hypotheses = (
            db.query(DiscoveryHypothesis)
            .join(
                DiscoveryHypothesis.session
            )
            .filter(
                DiscoveryHypothesis.status == "confirmed",
                DiscoveryHypothesis.session.has(client_id=client_id),
            )
            .all()
        )

        for hyp in hypotheses:
            # Check if hypothesis references any subreddit we have data for
            reddit_signals = hyp.reddit_signals or {}
            signal_subreddits = [
                s.get("name", "").replace("r/", "")
                for s in reddit_signals.get("subreddits", [])
            ]

            for sub_signal in profile.subreddit_signals:
                if sub_signal.subreddit in signal_subreddits and sub_signal.confidence >= 0.5:
                    # We have outcome data for a subreddit this hypothesis predicted
                    delta = 0
                    reason = ""

                    if sub_signal.avg_karma >= 5:
                        delta = 10  # Hypothesis validated: good engagement
                        reason = f"Avg karma {sub_signal.avg_karma:.1f} in r/{sub_signal.subreddit}"
                    elif sub_signal.avg_karma < 0:
                        delta = -15  # Hypothesis weakened: negative reception
                        reason = f"Negative karma ({sub_signal.avg_karma:.1f}) in r/{sub_signal.subreddit}"
                    elif sub_signal.removal_rate > 0.2:
                        delta = -20  # Hypothesis weakened: high removals
                        reason = f"High removal rate ({sub_signal.removal_rate:.0%}) in r/{sub_signal.subreddit}"

                    if delta != 0:
                        updates.append({
                            "hypothesis_id": str(hyp.id),
                            "delta": delta,
                            "reason": reason,
                            "subreddit": sub_signal.subreddit,
                            "data_points": sub_signal.total_comments,
                        })

    return updates


def _build_performance_summary(profile: AvatarOutcomeProfile) -> dict:
    """Build a performance summary dict for injection into strategy generation prompts.

    This is what the Strategy Engine sees when generating the next strategy version.
    """
    return {
        "total_posted_30d": profile.total_posted,
        "total_karma_30d": profile.total_karma,
        "avg_karma_per_comment": round(profile.avg_karma, 1),
        "removal_rate": round(profile.removal_rate, 3),
        "avg_reply_count": round(profile.avg_reply_count, 1),
        "karma_velocity_per_day": round(profile.karma_velocity, 1),
        "top_subreddits": profile.top_performing_subreddits,
        "underperforming_subreddits": profile.underperforming_subreddits,
        "best_approaches": [
            {"approach": s.approach, "avg_karma": round(s.avg_karma, 1)}
            for s in (profile.approach_signals[:3] if profile.approach_signals else [])
        ],
        "worst_approaches": [
            {"approach": s.approach, "avg_karma": round(s.avg_karma, 1)}
            for s in (profile.approach_signals[-2:] if len(profile.approach_signals) > 3 else [])
        ],
    }
