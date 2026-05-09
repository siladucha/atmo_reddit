"""Reddit Profile Analytics service.

Fetches comprehensive profile analytics for an avatar from Reddit:
- Account metadata (karma, age, verification)
- Recent comments with subreddit breakdown
- Recent posts with engagement metrics
- Karma distribution by subreddit
- Activity patterns (posting frequency, peak hours)
- Content style analysis (avg length, tone indicators)

Used by the admin avatar detail page "Profile Analytics" button.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.services.reddit import get_reddit_client

logger = logging.getLogger(__name__)


@dataclass
class SubredditPresence:
    """Karma and activity stats for one subreddit."""
    name: str
    comment_count: int = 0
    comment_karma: int = 0
    post_count: int = 0
    post_karma: int = 0
    last_activity: datetime | None = None

    @property
    def total_karma(self) -> int:
        return self.comment_karma + self.post_karma

    @property
    def total_activity(self) -> int:
        return self.comment_count + self.post_count


@dataclass
class RecentComment:
    """A single recent comment."""
    subreddit: str
    body: str
    score: int
    created_at: datetime
    permalink: str
    is_submitter: bool = False


@dataclass
class RecentPost:
    """A single recent post."""
    subreddit: str
    title: str
    score: int
    num_comments: int
    created_at: datetime
    permalink: str
    selftext_preview: str = ""


@dataclass
class ActivityPattern:
    """Posting frequency and timing analysis."""
    total_comments: int = 0
    total_posts: int = 0
    avg_comments_per_week: float = 0.0
    avg_posts_per_week: float = 0.0
    most_active_hour_utc: int | None = None
    most_active_day: str | None = None  # e.g. "Monday"
    days_since_last_comment: int | None = None
    days_since_last_post: int | None = None
    account_age_days: int = 0


@dataclass
class ContentStyle:
    """Content style indicators."""
    avg_comment_length: int = 0
    avg_post_length: int = 0
    uses_emoji: bool = False
    uses_links: bool = False
    avg_comment_score: float = 0.0
    avg_post_score: float = 0.0
    top_comment_score: int = 0
    top_post_score: int = 0


@dataclass
class ProfileAnalytics:
    """Full profile analytics result."""
    username: str
    fetched_at: datetime
    fetch_duration_ms: int

    # Account info
    comment_karma: int = 0
    post_karma: int = 0
    total_karma: int = 0
    account_created: datetime | None = None
    account_age_days: int = 0
    has_verified_email: bool = False
    is_gold: bool = False
    is_mod: bool = False
    icon_url: str | None = None

    # Subreddit presence
    subreddits: list[SubredditPresence] = field(default_factory=list)

    # Recent activity
    recent_comments: list[RecentComment] = field(default_factory=list)
    recent_posts: list[RecentPost] = field(default_factory=list)

    # Patterns
    activity: ActivityPattern = field(default_factory=ActivityPattern)
    style: ContentStyle = field(default_factory=ContentStyle)

    # Errors
    error: str | None = None


def fetch_profile_analytics(username: str, comment_limit: int = 100, post_limit: int = 50) -> ProfileAnalytics:
    """Fetch comprehensive Reddit profile analytics.

    Makes multiple Reddit API calls — use sparingly (rate limiting applies).
    Typical execution: 3-8 seconds depending on activity volume.
    """
    start_time = time.time()
    logger.info("PROFILE_ANALYTICS | action=start | username=u/%s", username)

    try:
        reddit = get_reddit_client()
        redditor = reddit.redditor(username)

        # Basic profile info
        if getattr(redditor, "is_suspended", False):
            duration_ms = int((time.time() - start_time) * 1000)
            return ProfileAnalytics(
                username=username,
                fetched_at=datetime.now(timezone.utc),
                fetch_duration_ms=duration_ms,
                error="Account is suspended",
            )

        comment_karma = int(getattr(redditor, "comment_karma", 0) or 0)
        post_karma = int(getattr(redditor, "link_karma", 0) or 0)
        created_utc = getattr(redditor, "created_utc", None)
        account_created = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc) if created_utc else None
        )
        account_age_days = (
            (datetime.now(timezone.utc) - account_created).days if account_created else 0
        )

        analytics = ProfileAnalytics(
            username=username,
            fetched_at=datetime.now(timezone.utc),
            fetch_duration_ms=0,  # will be set at the end
            comment_karma=comment_karma,
            post_karma=post_karma,
            total_karma=comment_karma + post_karma,
            account_created=account_created,
            account_age_days=account_age_days,
            has_verified_email=bool(getattr(redditor, "has_verified_email", False)),
            is_gold=bool(getattr(redditor, "is_gold", False)),
            is_mod=bool(getattr(redditor, "is_mod", False)),
            icon_url=getattr(redditor, "icon_img", None) or None,
        )

        # --- Fetch comments ---
        sub_data: dict[str, SubredditPresence] = defaultdict(lambda: SubredditPresence(name=""))
        comments_list: list[RecentComment] = []
        hour_counts: dict[int, int] = defaultdict(int)
        day_counts: dict[int, int] = defaultdict(int)  # 0=Monday
        total_comment_len = 0
        emoji_found = False
        links_found = False
        top_comment_score = 0

        for comment in redditor.comments.new(limit=comment_limit):
            sub_name = comment.subreddit.display_name
            score = comment.score
            body = comment.body
            created = datetime.fromtimestamp(comment.created_utc, tz=timezone.utc)
            permalink = f"https://reddit.com{comment.permalink}"

            # Subreddit stats
            if sub_data[sub_name].name == "":
                sub_data[sub_name].name = sub_name
            sub_data[sub_name].comment_count += 1
            sub_data[sub_name].comment_karma += score
            if sub_data[sub_name].last_activity is None or created > sub_data[sub_name].last_activity:
                sub_data[sub_name].last_activity = created

            # Recent comments (keep first 20 for display)
            if len(comments_list) < 20:
                comments_list.append(RecentComment(
                    subreddit=sub_name,
                    body=body[:300],
                    score=score,
                    created_at=created,
                    permalink=permalink,
                    is_submitter=getattr(comment, "is_submitter", False),
                ))

            # Activity patterns
            hour_counts[created.hour] += 1
            day_counts[created.weekday()] += 1

            # Style analysis
            total_comment_len += len(body)
            if not emoji_found and any(ord(c) > 0x1F600 for c in body):
                emoji_found = True
            if not links_found and ("http://" in body or "https://" in body or "[" in body):
                links_found = True
            if score > top_comment_score:
                top_comment_score = score

        # --- Fetch posts ---
        posts_list: list[RecentPost] = []
        total_post_len = 0
        top_post_score = 0

        for post in redditor.submissions.new(limit=post_limit):
            sub_name = post.subreddit.display_name
            score = post.score
            created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
            permalink = f"https://reddit.com{post.permalink}"
            selftext = getattr(post, "selftext", "") or ""

            # Subreddit stats
            if sub_data[sub_name].name == "":
                sub_data[sub_name].name = sub_name
            sub_data[sub_name].post_count += 1
            sub_data[sub_name].post_karma += score
            if sub_data[sub_name].last_activity is None or created > sub_data[sub_name].last_activity:
                sub_data[sub_name].last_activity = created

            # Recent posts (keep first 15 for display)
            if len(posts_list) < 15:
                posts_list.append(RecentPost(
                    subreddit=sub_name,
                    title=post.title[:150],
                    score=score,
                    num_comments=post.num_comments,
                    created_at=created,
                    permalink=permalink,
                    selftext_preview=selftext[:200],
                ))

            # Activity patterns
            hour_counts[created.hour] += 1
            day_counts[created.weekday()] += 1

            # Style
            total_post_len += len(post.title) + len(selftext)
            if score > top_post_score:
                top_post_score = score

        # --- Compile subreddit presence ---
        subreddits_sorted = sorted(
            sub_data.values(),
            key=lambda s: s.total_karma,
            reverse=True,
        )
        analytics.subreddits = subreddits_sorted
        analytics.recent_comments = comments_list
        analytics.recent_posts = posts_list

        # --- Activity patterns ---
        total_comments = sum(s.comment_count for s in subreddits_sorted)
        total_posts = sum(s.post_count for s in subreddits_sorted)
        weeks = max(1, account_age_days / 7) if account_age_days > 0 else 1

        # But use actual activity window, not full account age
        if comments_list:
            oldest_comment = min(c.created_at for c in comments_list)
            activity_weeks = max(1, (datetime.now(timezone.utc) - oldest_comment).days / 7)
        else:
            activity_weeks = weeks

        most_active_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None
        most_active_day_num = max(day_counts, key=day_counts.get) if day_counts else None
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        most_active_day = day_names[most_active_day_num] if most_active_day_num is not None else None

        days_since_last_comment = None
        if comments_list:
            days_since_last_comment = (datetime.now(timezone.utc) - comments_list[0].created_at).days

        days_since_last_post = None
        if posts_list:
            days_since_last_post = (datetime.now(timezone.utc) - posts_list[0].created_at).days

        analytics.activity = ActivityPattern(
            total_comments=total_comments,
            total_posts=total_posts,
            avg_comments_per_week=round(total_comments / activity_weeks, 1),
            avg_posts_per_week=round(total_posts / activity_weeks, 1),
            most_active_hour_utc=most_active_hour,
            most_active_day=most_active_day,
            days_since_last_comment=days_since_last_comment,
            days_since_last_post=days_since_last_post,
            account_age_days=account_age_days,
        )

        # --- Content style ---
        avg_comment_len = total_comment_len // total_comments if total_comments > 0 else 0
        avg_post_len = total_post_len // total_posts if total_posts > 0 else 0
        avg_comment_score = round(
            sum(c.score for c in comments_list) / len(comments_list), 1
        ) if comments_list else 0.0
        avg_post_score = round(
            sum(p.score for p in posts_list) / len(posts_list), 1
        ) if posts_list else 0.0

        analytics.style = ContentStyle(
            avg_comment_length=avg_comment_len,
            avg_post_length=avg_post_len,
            uses_emoji=emoji_found,
            uses_links=links_found,
            avg_comment_score=avg_comment_score,
            avg_post_score=avg_post_score,
            top_comment_score=top_comment_score,
            top_post_score=top_post_score,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        analytics.fetch_duration_ms = duration_ms

        logger.info(
            "PROFILE_ANALYTICS | action=done | username=u/%s | "
            "comments=%d | posts=%d | subreddits=%d | duration_ms=%d",
            username, total_comments, total_posts, len(subreddits_sorted), duration_ms,
        )

        return analytics

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.exception(
            "PROFILE_ANALYTICS | action=error | username=u/%s | duration_ms=%d",
            username, duration_ms,
        )
        return ProfileAnalytics(
            username=username,
            fetched_at=datetime.now(timezone.utc),
            fetch_duration_ms=duration_ms,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Persistence — save/load snapshots to database
# ---------------------------------------------------------------------------


def _analytics_to_json_subreddits(analytics: ProfileAnalytics) -> list[dict]:
    """Serialize subreddit presence list to JSON-safe dicts."""
    return [
        {
            "name": s.name,
            "comment_count": s.comment_count,
            "comment_karma": s.comment_karma,
            "post_count": s.post_count,
            "post_karma": s.post_karma,
            "last_activity": s.last_activity.isoformat() if s.last_activity else None,
        }
        for s in analytics.subreddits
    ]


def _analytics_to_json_comments(analytics: ProfileAnalytics) -> list[dict]:
    """Serialize recent comments to JSON-safe dicts."""
    return [
        {
            "subreddit": c.subreddit,
            "body": c.body,
            "score": c.score,
            "created_at": c.created_at.isoformat(),
            "permalink": c.permalink,
            "is_submitter": c.is_submitter,
        }
        for c in analytics.recent_comments
    ]


def _analytics_to_json_posts(analytics: ProfileAnalytics) -> list[dict]:
    """Serialize recent posts to JSON-safe dicts."""
    return [
        {
            "subreddit": p.subreddit,
            "title": p.title,
            "score": p.score,
            "num_comments": p.num_comments,
            "created_at": p.created_at.isoformat(),
            "permalink": p.permalink,
            "selftext_preview": p.selftext_preview,
        }
        for p in analytics.recent_posts
    ]


def save_profile_snapshot(db: Session, avatar_id, analytics: ProfileAnalytics) -> None:
    """Save a ProfileAnalytics result to the database.

    Creates a new snapshot row each time (history is preserved).
    """
    from app.models.avatar_profile_snapshot import AvatarProfileSnapshot

    snapshot = AvatarProfileSnapshot(
        avatar_id=avatar_id,
        reddit_username=analytics.username,
        comment_karma=analytics.comment_karma,
        post_karma=analytics.post_karma,
        total_karma=analytics.total_karma,
        account_age_days=analytics.account_age_days,
        account_created=analytics.account_created,
        has_verified_email=analytics.has_verified_email,
        is_gold=analytics.is_gold,
        is_mod=analytics.is_mod,
        icon_url=analytics.icon_url,
        # Activity
        total_comments=analytics.activity.total_comments,
        total_posts=analytics.activity.total_posts,
        avg_comments_per_week=analytics.activity.avg_comments_per_week,
        avg_posts_per_week=analytics.activity.avg_posts_per_week,
        most_active_hour_utc=analytics.activity.most_active_hour_utc,
        most_active_day=analytics.activity.most_active_day,
        days_since_last_comment=analytics.activity.days_since_last_comment,
        days_since_last_post=analytics.activity.days_since_last_post,
        # Style
        avg_comment_length=analytics.style.avg_comment_length,
        avg_post_length=analytics.style.avg_post_length,
        uses_emoji=analytics.style.uses_emoji,
        uses_links=analytics.style.uses_links,
        avg_comment_score=analytics.style.avg_comment_score,
        avg_post_score=analytics.style.avg_post_score,
        top_comment_score=analytics.style.top_comment_score,
        top_post_score=analytics.style.top_post_score,
        # JSON data
        subreddits_data=_analytics_to_json_subreddits(analytics),
        recent_comments_data=_analytics_to_json_comments(analytics),
        recent_posts_data=_analytics_to_json_posts(analytics),
        # Meta
        fetch_duration_ms=analytics.fetch_duration_ms,
        error=analytics.error,
        fetched_at=analytics.fetched_at,
    )
    db.add(snapshot)
    db.commit()
    logger.info(
        "PROFILE_ANALYTICS | action=saved | username=u/%s | snapshot_id=%s",
        analytics.username, snapshot.id,
    )


def load_latest_snapshot(db: Session, avatar_id) -> "AvatarProfileSnapshot | None":
    """Load the most recent profile snapshot for an avatar."""
    from app.models.avatar_profile_snapshot import AvatarProfileSnapshot

    return (
        db.query(AvatarProfileSnapshot)
        .filter(AvatarProfileSnapshot.avatar_id == avatar_id)
        .order_by(AvatarProfileSnapshot.fetched_at.desc())
        .first()
    )


def snapshot_to_analytics(snapshot) -> ProfileAnalytics:
    """Convert a DB snapshot back to a ProfileAnalytics dataclass for template rendering."""
    # Rebuild subreddits
    subreddits = []
    for s in (snapshot.subreddits_data or []):
        last_activity = None
        if s.get("last_activity"):
            try:
                last_activity = datetime.fromisoformat(s["last_activity"])
            except (ValueError, TypeError):
                pass
        subreddits.append(SubredditPresence(
            name=s["name"],
            comment_count=s.get("comment_count", 0),
            comment_karma=s.get("comment_karma", 0),
            post_count=s.get("post_count", 0),
            post_karma=s.get("post_karma", 0),
            last_activity=last_activity,
        ))

    # Rebuild recent comments
    recent_comments = []
    for c in (snapshot.recent_comments_data or []):
        try:
            created_at = datetime.fromisoformat(c["created_at"])
        except (ValueError, TypeError):
            created_at = snapshot.fetched_at
        recent_comments.append(RecentComment(
            subreddit=c["subreddit"],
            body=c.get("body", ""),
            score=c.get("score", 0),
            created_at=created_at,
            permalink=c.get("permalink", ""),
            is_submitter=c.get("is_submitter", False),
        ))

    # Rebuild recent posts
    recent_posts = []
    for p in (snapshot.recent_posts_data or []):
        try:
            created_at = datetime.fromisoformat(p["created_at"])
        except (ValueError, TypeError):
            created_at = snapshot.fetched_at
        recent_posts.append(RecentPost(
            subreddit=p["subreddit"],
            title=p.get("title", ""),
            score=p.get("score", 0),
            num_comments=p.get("num_comments", 0),
            created_at=created_at,
            permalink=p.get("permalink", ""),
            selftext_preview=p.get("selftext_preview", ""),
        ))

    return ProfileAnalytics(
        username=snapshot.reddit_username,
        fetched_at=snapshot.fetched_at,
        fetch_duration_ms=snapshot.fetch_duration_ms,
        comment_karma=snapshot.comment_karma,
        post_karma=snapshot.post_karma,
        total_karma=snapshot.total_karma,
        account_created=snapshot.account_created,
        account_age_days=snapshot.account_age_days,
        has_verified_email=snapshot.has_verified_email,
        is_gold=snapshot.is_gold,
        is_mod=snapshot.is_mod,
        icon_url=snapshot.icon_url,
        subreddits=subreddits,
        recent_comments=recent_comments,
        recent_posts=recent_posts,
        activity=ActivityPattern(
            total_comments=snapshot.total_comments,
            total_posts=snapshot.total_posts,
            avg_comments_per_week=snapshot.avg_comments_per_week,
            avg_posts_per_week=snapshot.avg_posts_per_week,
            most_active_hour_utc=snapshot.most_active_hour_utc,
            most_active_day=snapshot.most_active_day,
            days_since_last_comment=snapshot.days_since_last_comment,
            days_since_last_post=snapshot.days_since_last_post,
            account_age_days=snapshot.account_age_days,
        ),
        style=ContentStyle(
            avg_comment_length=snapshot.avg_comment_length,
            avg_post_length=snapshot.avg_post_length,
            uses_emoji=snapshot.uses_emoji,
            uses_links=snapshot.uses_links,
            avg_comment_score=snapshot.avg_comment_score,
            avg_post_score=snapshot.avg_post_score,
            top_comment_score=snapshot.top_comment_score,
            top_post_score=snapshot.top_post_score,
        ),
        error=snapshot.error,
    )


def fetch_and_save(db: Session, avatar_id, username: str) -> ProfileAnalytics:
    """Fetch fresh analytics from Reddit and save to database. Returns the analytics."""
    analytics = fetch_profile_analytics(username)
    if not analytics.error:
        save_profile_snapshot(db, avatar_id, analytics)
    return analytics
