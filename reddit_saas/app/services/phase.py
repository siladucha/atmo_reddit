"""Phase policy service for avatar warming phase content restrictions.

Determines what content is allowed for an avatar based on its current
warming phase (1, 2, or 3). Enforces brand mention limits, subreddit
restrictions, comment type rules, and daily rate limits per phase.

Also contains PhaseEvaluator for eligibility gate checks (promotion/demotion).
"""

from __future__ import annotations

from app.logging_config import get_logger
import re
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.settings import SystemSetting
from app.services.phase_lock import PhaseTransitionLock
from app.services.phase_types import (
    BrandMentionLevel,
    EvaluationResult,
    PolicyResult,
    PolicyStatus,
    RampUpStage,
)
from app.services.sanitize import clean_subreddit_list, get_avatar_hobby_subreddits

logger = get_logger(__name__)

# --- Phase Policy Constants ---
MAX_COMMENTS_PER_DAY_PHASE1 = 3
MAX_COMMENTS_PER_DAY_PHASE2 = 7   # Was 10; reduced per R12.3 for safety margin
MAX_COMMENTS_PER_DAY_PHASE3 = 18  # TODO(pipeline-v2): replace with BudgetEngine.calculate_daily_limit()
MAX_BRAND_RATIO = 0.30             # TODO(pipeline-v2): move to system_settings "max_brand_ratio_percent"
BRAND_RAMP_UP_EARLY_MAX = 1
BRAND_RAMP_UP_MID_RATIO = 0.10


class PhasePolicy:
    """Content restriction rules per warming phase.

    Enforces phase-specific rules for comment type, subreddit targeting,
    brand mention levels, daily limits, and ramp-up constraints.
    """

    def classify_brand_mention(
        self,
        comment_text: str,
        client: Client,
    ) -> BrandMentionLevel | None:
        """Classify the highest-severity brand mention in comment text.

        Checks for:
        1. explicit_brand_link — URL containing client's brand_domain
        2. explicit_brand_name — case-insensitive match of client's brand_name

        Priority: explicit_brand_link > explicit_brand_name > inferred_brand > None

        Note: inferred_brand detection is not implemented (would require AI).
        """
        if not comment_text:
            return None

        # Check for explicit brand link (URL containing brand_domain)
        if client.brand_domain:
            # Match URLs containing the brand domain
            domain = client.brand_domain.lower()
            # Look for the domain in URLs or as a standalone reference
            url_pattern = re.compile(
                r'https?://[^\s]*' + re.escape(domain) + r'[^\s]*',
                re.IGNORECASE,
            )
            if url_pattern.search(comment_text):
                return BrandMentionLevel.explicit_brand_link

            # Also check for bare domain references (without protocol)
            bare_domain_pattern = re.compile(
                r'(?<![a-zA-Z0-9\-\.])' + re.escape(domain) + r'(?![a-zA-Z0-9\-\.])',
                re.IGNORECASE,
            )
            if bare_domain_pattern.search(comment_text):
                return BrandMentionLevel.explicit_brand_link

        # Check for explicit brand name (case-insensitive word match)
        if client.brand_name:
            brand_name = client.brand_name
            # Use word boundary matching for the brand name
            pattern = re.compile(
                r'\b' + re.escape(brand_name) + r'\b',
                re.IGNORECASE,
            )
            if pattern.search(comment_text):
                return BrandMentionLevel.explicit_brand_name

        # inferred_brand detection not implemented (requires AI)
        return None

    def get_daily_comment_count(
        self,
        db: Session,
        avatar: Avatar,
    ) -> int:
        """Count today's approved/posted comments for rate limiting.

        Uses UTC date boundaries (midnight to midnight).
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        count = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= today_start,
            )
            .scalar()
        )
        return count or 0

    def get_brand_ratio(
        self,
        db: Session,
        avatar: Avatar,
        window_days: int = 7,
    ) -> float:
        """Calculate brand comment ratio over the given window.

        Scans comment texts in the window and classifies brand mentions
        using classify_brand_mention. Returns ratio of brand-containing
        comments to total comments.

        Returns 0.0 if no comments exist in the window.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)

        # Get all comments in the window
        comments = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= window_start,
            )
            .all()
        )

        if not comments:
            return 0.0

        # We need the client to classify brand mentions
        # Get client from avatar's client_ids
        if not avatar.client_ids:
            return 0.0

        from app.models.client import Client as ClientModel
        client = (
            db.query(ClientModel)
            .filter(ClientModel.id == avatar.client_ids[0])
            .first()
        )
        if not client:
            return 0.0

        brand_count = 0
        for comment in comments:
            text = comment.ai_draft or comment.edited_draft or ""
            if self.classify_brand_mention(text, client) is not None:
                brand_count += 1

        return brand_count / len(comments)

    def get_ramp_up_stage(
        self,
        avatar: Avatar,
    ) -> RampUpStage:
        """Determine ramp-up stage based on time since phase_changed_at.

        Returns:
            EARLY: 0-72 hours since phase change
            MID: 72 hours to 7 days
            COMPLETE: more than 7 days
        """
        now = datetime.now(timezone.utc)
        hours_since = (now - avatar.phase_changed_at).total_seconds() / 3600

        if hours_since < 72:
            return RampUpStage.early
        elif hours_since < 168:  # 7 days = 168 hours
            return RampUpStage.mid
        else:
            return RampUpStage.complete

    def check_comment_allowed(
        self,
        db: Session,
        avatar: Avatar,
        comment_type: str,
        target_subreddit: str,
        comment_text: str,
        client: Client,
        thread_tag: str | None = None,
    ) -> PolicyResult:
        """Determine if a comment is allowed under phase restrictions.

        Enforces phase-specific rules for content type, subreddit targeting,
        brand mentions, and daily limits.

        Args:
            db: Database session
            avatar: The avatar attempting to post
            comment_type: "professional" or "hobby"
            target_subreddit: Target subreddit name
            comment_text: The comment text to check
            client: The client associated with this avatar
            thread_tag: Thread tag ("engage", "monitor", "skip") or None

        Returns:
            PolicyResult with status (allowed/blocked/requires_review),
            reason string, and detected brand_mention_level.
        """
        phase = avatar.warming_phase

        # Mentor phase — not subject to pipeline content restrictions
        if phase == 0:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason="Phase 0 (Mentor): avatar excluded from automated pipelines",
            )

        if phase == 1:
            return self._check_phase1(db, avatar, comment_type, target_subreddit, comment_text, client)
        elif phase == 2:
            return self._check_phase2(db, avatar, comment_type, target_subreddit, comment_text, client)
        elif phase == 3:
            return self._check_phase3(db, avatar, comment_type, target_subreddit, comment_text, client, thread_tag)
        else:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Unknown warming phase: {phase}",
            )

    def _check_phase1(
        self,
        db: Session,
        avatar: Avatar,
        comment_type: str,
        target_subreddit: str,
        comment_text: str,
        client: Client,
    ) -> PolicyResult:
        """Phase 1 rules: hobby only, hobby subreddits only, no brand mentions, max 3/day.

        CQS "lowest" avatars get a reduced daily limit (1/day) to warm up cautiously.
        """
        # Rule: Only "hobby" type allowed
        if comment_type != "hobby":
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 1: only hobby comments allowed, got '{comment_type}'",
            )

        # Rule: Only subreddits in avatar.hobby_subreddits allowed.
        # hobby_subreddits is JSONB and may contain either bare strings or
        # dicts of the form {"subreddit": "name"} / {"name": "name"} (legacy
        # Ori format). Normalize via get_avatar_hobby_subreddits which also
        # provides Phase 1 fallback defaults (NewToReddit, AskReddit, etc.)
        hobby_subs = {s.lower() for s in get_avatar_hobby_subreddits(avatar)}
        if (target_subreddit or "").lower() not in hobby_subs:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 1: subreddit '{target_subreddit}' not in hobby_subreddits",
            )

        # Rule: No brand mentions at all
        brand_level = self.classify_brand_mention(comment_text, client)
        if brand_level is not None:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 1: brand mentions not allowed ({brand_level.value})",
                brand_mention_level=brand_level,
            )

        # Rule: Daily limit — reduced for CQS "lowest" (cautious warming)
        daily_limit = MAX_COMMENTS_PER_DAY_PHASE1
        if avatar.cqs_level == "lowest":
            daily_limit = 1  # Ultra-cautious: 1 hobby comment/day until CQS improves

        daily_count = self.get_daily_comment_count(db, avatar)
        if daily_count >= daily_limit:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 1: daily limit reached ({daily_count}/{daily_limit})",
            )

        return PolicyResult(
            status=PolicyStatus.allowed,
            reason="Phase 1: comment allowed",
        )

    def _check_phase2(
        self,
        db: Session,
        avatar: Avatar,
        comment_type: str,
        target_subreddit: str,
        comment_text: str,
        client: Client,
    ) -> PolicyResult:
        """Phase 2 rules: hobby + professional, hobby + business subs, block explicit brand."""
        # Rule: "hobby" and "professional" types allowed
        if comment_type not in ("hobby", "professional"):
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 2: comment type '{comment_type}' not allowed",
            )

        # Rule: Subreddits in hobby_subreddits OR business_subreddits allowed.
        # Both fields are JSONB; normalize for the dict-vs-string shape (see Phase 1).
        hobby_subs = {s.lower() for s in clean_subreddit_list(avatar.hobby_subreddits)}
        business_subs = {s.lower() for s in clean_subreddit_list(avatar.business_subreddits)}
        allowed_subs = hobby_subs | business_subs
        if (target_subreddit or "").lower() not in allowed_subs:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 2: subreddit '{target_subreddit}' not in allowed subreddits",
            )

        # Rule: Check brand mentions
        brand_level = self.classify_brand_mention(comment_text, client)
        if brand_level == BrandMentionLevel.explicit_brand_link:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason="Phase 2: explicit brand links not allowed",
                brand_mention_level=brand_level,
            )
        if brand_level == BrandMentionLevel.explicit_brand_name:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason="Phase 2: explicit brand name mentions not allowed",
                brand_mention_level=brand_level,
            )
        if brand_level == BrandMentionLevel.inferred_brand:
            return PolicyResult(
                status=PolicyStatus.requires_review,
                reason="Phase 2: inferred brand mention requires human review",
                brand_mention_level=brand_level,
            )

        # Rule: Standard daily limit
        daily_count = self.get_daily_comment_count(db, avatar)
        if daily_count >= MAX_COMMENTS_PER_DAY_PHASE2:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 2: daily limit reached ({daily_count}/{MAX_COMMENTS_PER_DAY_PHASE2})",
            )

        return PolicyResult(
            status=PolicyStatus.allowed,
            reason="Phase 2: comment allowed",
        )

    def _check_phase3(
        self,
        db: Session,
        avatar: Avatar,
        comment_type: str,
        target_subreddit: str,
        comment_text: str,
        client: Client,
        thread_tag: str | None = None,
    ) -> PolicyResult:
        """Phase 3 rules: all types, ramp-up constraints, brand ratio, engage-only links."""
        # Rule: All types allowed (no type restriction)

        # Rule: All subreddits allowed (no subreddit restriction)

        # Rule: Standard daily limit
        daily_count = self.get_daily_comment_count(db, avatar)
        if daily_count >= MAX_COMMENTS_PER_DAY_PHASE3:
            return PolicyResult(
                status=PolicyStatus.blocked,
                reason=f"Phase 3: daily limit reached ({daily_count}/{MAX_COMMENTS_PER_DAY_PHASE3})",
            )

        # Check brand mention level
        brand_level = self.classify_brand_mention(comment_text, client)

        # Rule: Brand links only allowed when thread_tag == "engage"
        if brand_level == BrandMentionLevel.explicit_brand_link:
            if thread_tag != "engage":
                return PolicyResult(
                    status=PolicyStatus.blocked,
                    reason="Phase 3: brand links only allowed in 'engage' tagged threads",
                    brand_mention_level=brand_level,
                )

        # Rule: Enforce ramp-up constraints for brand mentions
        if brand_level is not None:
            ramp_stage = self.get_ramp_up_stage(avatar)

            if ramp_stage == RampUpStage.early:
                # EARLY stage: max 1 brand comment total since phase_changed_at
                brand_count_since_phase = self._count_brand_comments_since_phase_change(
                    db, avatar, client
                )
                if brand_count_since_phase >= BRAND_RAMP_UP_EARLY_MAX:
                    return PolicyResult(
                        status=PolicyStatus.blocked,
                        reason=f"Phase 3 (early ramp-up): max {BRAND_RAMP_UP_EARLY_MAX} brand comment(s) allowed",
                        brand_mention_level=brand_level,
                    )

            elif ramp_stage == RampUpStage.mid:
                # MID stage: brand ratio must be <= 10%
                brand_ratio = self.get_brand_ratio(db, avatar, window_days=7)
                if brand_ratio > BRAND_RAMP_UP_MID_RATIO:
                    return PolicyResult(
                        status=PolicyStatus.blocked,
                        reason=f"Phase 3 (mid ramp-up): brand ratio {brand_ratio:.0%} exceeds {BRAND_RAMP_UP_MID_RATIO:.0%} limit",
                        brand_mention_level=brand_level,
                    )

            else:  # COMPLETE stage
                # COMPLETE stage: brand ratio must be <= 30%
                brand_ratio = self.get_brand_ratio(db, avatar, window_days=7)
                if brand_ratio > MAX_BRAND_RATIO:
                    return PolicyResult(
                        status=PolicyStatus.blocked,
                        reason=f"Phase 3 (complete): brand ratio {brand_ratio:.0%} exceeds {MAX_BRAND_RATIO:.0%} limit",
                        brand_mention_level=brand_level,
                    )

        return PolicyResult(
            status=PolicyStatus.allowed,
            reason="Phase 3: comment allowed",
            brand_mention_level=brand_level,
        )

    def _count_brand_comments_since_phase_change(
        self,
        db: Session,
        avatar: Avatar,
        client: Client,
    ) -> int:
        """Count brand-containing comments since the avatar's last phase change."""
        comments = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= avatar.phase_changed_at,
            )
            .all()
        )

        brand_count = 0
        for comment in comments:
            text = comment.ai_draft or comment.edited_draft or ""
            if self.classify_brand_mention(text, client) is not None:
                brand_count += 1

        return brand_count


# --- Phase Evaluator Constants (defaults) ---
_P1_DEFAULTS = {
    "min_age_days": 60,
    "min_karma": 100,
    "min_activity": 20,
    "min_survival_rate": 80,
}

_P2_DEFAULTS = {
    "min_age_days": 150,
    "min_karma": 500,
    "min_activity": 50,
    "min_survival_rate": 85,
    "min_avg_score": 2.0,
}

# Window sizes for eligibility checks (in days)
_P1_WINDOW_DAYS = 60
_P2_WINDOW_DAYS = 90
_DEMOTION_WINDOW_DAYS = 7
_DEMOTION_MIN_SURVIVAL_RATE = 70


class PhaseEvaluator:
    """Eligibility gate checks for phase transitions.

    Evaluates whether an avatar meets criteria for promotion to the next phase,
    and checks demotion triggers (shadowban, low survival rate).
    """

    def get_thresholds(self, db: Session, current_phase: int) -> dict:
        """Load eligibility thresholds from SystemSettings with fallback to defaults.

        Args:
            db: Database session.
            current_phase: The avatar's current phase (1 or 2).

        Returns:
            Dictionary of threshold names to numeric values.
        """
        if current_phase == 1:
            prefix = "phase_gate_p1_"
            defaults = _P1_DEFAULTS
        elif current_phase == 2:
            prefix = "phase_gate_p2_"
            defaults = _P2_DEFAULTS
        else:
            # Phase 3 is max — no thresholds for next phase
            return {}

        # Load all settings with the prefix in one query
        settings = (
            db.query(SystemSetting)
            .filter(SystemSetting.key.like(f"{prefix}%"))
            .all()
        )
        settings_map = {s.key: s.value for s in settings}

        thresholds = {}
        for key, default_value in defaults.items():
            setting_key = f"{prefix}{key}"
            raw_value = settings_map.get(setting_key)
            if raw_value is not None:
                # Parse as float to handle both int and float thresholds
                try:
                    thresholds[key] = float(raw_value)
                except (ValueError, TypeError):
                    thresholds[key] = float(default_value)
            else:
                thresholds[key] = float(default_value)

        return thresholds

    def compute_comment_survival_rate(
        self, db: Session, avatar: Avatar, window_days: int
    ) -> float:
        """Calculate comment survival rate over the given window.

        Survival rate = (total_posted - deleted) / total_posted.
        Returns 1.0 if no posted comments (no evidence of deletion).

        Args:
            db: Database session.
            avatar: The avatar to evaluate.
            window_days: Number of days to look back.

        Returns:
            Float between 0.0 and 1.0 representing survival rate.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)

        total_posted = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= window_start,
            )
            .scalar()
        ) or 0

        if total_posted == 0:
            return 1.0

        deleted_count = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status == "posted",
                CommentDraft.is_deleted == True,  # noqa: E712
                CommentDraft.posted_at >= window_start,
            )
            .scalar()
        ) or 0

        return (total_posted - deleted_count) / total_posted

    def compute_avg_comment_score(
        self, db: Session, avatar: Avatar, window_days: int
    ) -> float:
        """Calculate mean reddit_score over the given window.

        Only considers comments with status="posted" and reddit_score IS NOT NULL.
        Returns 0.0 if no scored comments exist.

        Args:
            db: Database session.
            avatar: The avatar to evaluate.
            window_days: Number of days to look back.

        Returns:
            Float representing the average comment score.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)

        avg_score = (
            db.query(sa_func.avg(CommentDraft.reddit_score))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status == "posted",
                CommentDraft.reddit_score.isnot(None),
                CommentDraft.posted_at >= window_start,
            )
            .scalar()
        )

        if avg_score is None:
            return 0.0

        return float(avg_score)

    def should_piggyback(self, avatar: Avatar) -> bool:
        """Return True if last_phase_evaluated_at is None or > 4 hours ago.

        Used to determine whether a piggyback eligibility check should run
        during a PhasePolicy content restriction check.
        """
        if avatar.last_phase_evaluated_at is None:
            return True

        now = datetime.now(timezone.utc)
        hours_since = (now - avatar.last_phase_evaluated_at).total_seconds() / 3600
        return hours_since > 4

    def check_promotion_eligibility(
        self, db: Session, avatar: Avatar
    ) -> tuple[bool, dict]:
        """Check if avatar meets all criteria for the next phase.

        Phase 0 (Mentor): not subject to promotion — return (False, {})
        Phase 1→2: age≥60, karma≥100, activity≥20, survival≥80%,
                   karma in ≥2 distinct subreddits.
        Phase 2→3: age≥150, karma≥500, activity≥50, survival≥85%, avg_score≥2.0,
                   karma in ≥3 distinct subreddits incl. ≥1 professional.
        Phase 3: already max, return (False, {})

        Returns:
            (eligible: bool, criteria_values: dict with current vs required for each criterion)
        """
        from app.services import karma_tracker

        current_phase = avatar.warming_phase

        # Mentor (phase 0) — not subject to warming evaluation
        if current_phase == 0:
            return (False, {})

        if current_phase >= 3:
            return (False, {})

        thresholds = self.get_thresholds(db, current_phase)

        # Calculate account age
        if avatar.reddit_account_created:
            account_created = avatar.reddit_account_created
        else:
            account_created = avatar.created_at

        now = datetime.now(timezone.utc)
        age_days = (now - account_created).days

        # Calculate combined karma
        karma = (avatar.reddit_karma_comment or 0) + (avatar.reddit_karma_post or 0)

        # Determine window for activity/survival/score
        if current_phase == 1:
            window_days = _P1_WINDOW_DAYS
        else:
            window_days = _P2_WINDOW_DAYS

        # Calculate activity count (comments with status approved or posted in window)
        window_start = now - timedelta(days=window_days)
        activity_count = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= window_start,
            )
            .scalar()
        ) or 0

        # Pre-warmed avatar bypass: if karma significantly exceeds threshold
        # AND account is old enough, waive the activity requirement.
        # These avatars already proved credibility on Reddit externally.
        min_activity_effective = thresholds["min_activity"]
        karma_threshold = thresholds["min_karma"]
        age_threshold = thresholds["min_age_days"]
        if karma >= karma_threshold * 3 and age_days >= age_threshold * 2:
            min_activity_effective = 0

        # Calculate survival rate
        survival_rate = self.compute_comment_survival_rate(db, avatar, window_days)
        survival_pct = survival_rate * 100

        # Subreddit karma distribution (Req 7)
        diversity = karma_tracker.diversity_count(db, avatar.id)
        professional_diversity = karma_tracker.professional_diversity_count(
            db, avatar.id
        )

        if current_phase == 1:
            required_diversity = 2
        else:  # Phase 2 → 3
            required_diversity = 3

        # Build criteria values dict
        criteria_values = {
            "age_days": {"current": age_days, "required": thresholds["min_age_days"]},
            "karma": {"current": karma, "required": thresholds["min_karma"]},
            "activity": {"current": activity_count, "required": min_activity_effective},
            "survival_rate": {"current": survival_pct, "required": thresholds["min_survival_rate"]},
            "subreddit_diversity": {
                "current": diversity,
                "required": required_diversity,
                "shortfall": (
                    f"karma in {diversity}/{required_diversity} required subreddits"
                    if diversity < required_diversity
                    else None
                ),
            },
        }

        # Check all criteria
        diversity_ok = diversity >= required_diversity
        eligible = (
            age_days >= thresholds["min_age_days"]
            and karma >= thresholds["min_karma"]
            and activity_count >= min_activity_effective
            and survival_pct >= thresholds["min_survival_rate"]
            and diversity_ok
        )

        # Phase 2→3 also requires avg_score and at least one professional sub
        if current_phase == 2:
            avg_score = self.compute_avg_comment_score(db, avatar, window_days)
            criteria_values["avg_score"] = {
                "current": avg_score,
                "required": thresholds["min_avg_score"],
            }
            criteria_values["professional_diversity"] = {
                "current": professional_diversity,
                "required": 1,
                "shortfall": (
                    "needs karma in at least 1 professional subreddit"
                    if professional_diversity < 1
                    else None
                ),
            }
            eligible = (
                eligible
                and avg_score >= thresholds["min_avg_score"]
                and professional_diversity >= 1
            )

        return (eligible, criteria_values)

    def check_demotion_triggers(
        self, db: Session, avatar: Avatar
    ) -> tuple[bool, int, str | None]:
        """Check if any demotion trigger is active.

        Triggers checked:
        - Shadowban detected → demote to Phase 1, reason "shadowban_detected"
        - Survival rate < 70% (7-day window) → demote by 1 phase, reason "low_survival_rate"
        - Karma drop (avg reddit_score < -2 over 14-day window) → demote by 1, reason "karma_drop"

        Returns:
            (should_demote: bool, target_phase: int, trigger_reason: str | None)
        """
        current_phase = avatar.warming_phase

        # Can't demote below Phase 1; Mentors (phase 0) are not subject to demotion
        if current_phase <= 1:
            return (False, current_phase or 1, None)

        # Check shadowban — demote to Phase 1
        if avatar.is_shadowbanned:
            return (True, 1, "shadowban_detected")

        # Check survival rate < 70% over 7-day window — demote by 1
        survival_rate = self.compute_comment_survival_rate(
            db, avatar, _DEMOTION_WINDOW_DAYS
        )
        survival_pct = survival_rate * 100

        if survival_pct < _DEMOTION_MIN_SURVIVAL_RATE:
            target_phase = max(1, current_phase - 1)
            return (True, target_phase, "low_survival_rate")

        # Check karma drop — avg reddit_score below threshold over 14-day window
        from app.services.karma_feedback import check_karma_drop_demotion
        should_demote_karma, avg_score = check_karma_drop_demotion(db, avatar)
        if should_demote_karma:
            target_phase = max(1, current_phase - 1)
            return (True, target_phase, f"karma_drop (avg_score={avg_score:.2f})")

        return (False, current_phase, None)

    def evaluate(self, db: Session, avatar: Avatar) -> EvaluationResult:
        """Evaluate promotion eligibility and demotion triggers for an avatar.

        Orchestrates the full evaluation:
        1. Skip if avatar is inactive (but still check demotion for shadowban)
        2. Check demotion triggers first (demotion takes priority)
        3. If no demotion, check promotion eligibility
        4. Update last_phase_evaluated_at timestamp

        Args:
            db: Database session.
            avatar: The avatar to evaluate.

        Returns:
            EvaluationResult with action (promote/demote/none),
            target_phase, criteria_values dict, and trigger_reason.
        """
        now = datetime.now(timezone.utc)

        # Check demotion triggers first (even for shadowbanned avatars)
        should_demote, target_phase, trigger_reason = self.check_demotion_triggers(
            db, avatar
        )

        if should_demote:
            # Update evaluation timestamp
            avatar.last_phase_evaluated_at = now
            db.commit()
            return EvaluationResult(
                action="demote",
                target_phase=target_phase,
                trigger_reason=trigger_reason,
            )

        # Skip promotion check if avatar is inactive or shadowbanned
        if not avatar.active or avatar.is_shadowbanned:
            avatar.last_phase_evaluated_at = now
            db.commit()
            return EvaluationResult(action="none")

        # Check promotion eligibility
        eligible, criteria_values = self.check_promotion_eligibility(db, avatar)

        # Update evaluation timestamp
        avatar.last_phase_evaluated_at = now
        db.commit()

        if eligible:
            return EvaluationResult(
                action="promote",
                target_phase=avatar.warming_phase + 1,
                criteria_values=criteria_values,
            )

        return EvaluationResult(
            action="none",
            criteria_values=criteria_values,
        )


class PhaseTransitionManager:
    """Executes phase transitions (promotions, demotions, overrides).

    Acquires a per-avatar distributed lock before mutating phase state,
    records ActivityEvent entries for audit trail, and commits changes.
    """

    def __init__(self, lock: PhaseTransitionLock) -> None:
        self.lock = lock

    def promote(self, db: Session, avatar: Avatar, criteria_values: dict) -> bool:
        """Promote avatar to next phase.

        Acquires transition lock, updates warming_phase and phase_changed_at,
        records phase_promotion ActivityEvent.

        Args:
            db: Database session.
            avatar: The avatar to promote.
            criteria_values: Dictionary of criteria that qualified the promotion.

        Returns:
            True if promotion succeeded, False if lock not acquired.
        """
        avatar_id_str = str(avatar.id)
        if not self.lock.acquire(avatar_id_str):
            logger.warning(
                "Could not acquire phase lock for avatar %s — skipping promotion",
                avatar_id_str,
            )
            return False

        try:
            previous_phase = avatar.warming_phase
            new_phase = previous_phase + 1

            avatar.warming_phase = new_phase
            avatar.phase_changed_at = datetime.now(timezone.utc)

            self._record_event(
                db=db,
                avatar=avatar,
                event_type="phase_promotion",
                previous_phase=previous_phase,
                new_phase=new_phase,
                metadata={"criteria_values": criteria_values},
            )

            db.commit()
            logger.info(
                "Avatar %s promoted from Phase %d to Phase %d",
                avatar.reddit_username,
                previous_phase,
                new_phase,
            )
            return True
        finally:
            self.lock.release(avatar_id_str)

    def demote(
        self, db: Session, avatar: Avatar, target_phase: int, trigger_reason: str
    ) -> bool:
        """Demote avatar to target phase.

        If avatar is already in Phase 1, logs but does not demote.
        Acquires transition lock, updates fields, records auto_downgrade event.

        Args:
            db: Database session.
            avatar: The avatar to demote.
            target_phase: The phase to demote to.
            trigger_reason: Explanation of why demotion was triggered.

        Returns:
            True if demotion succeeded, False if lock not acquired or already Phase 1.
        """
        if avatar.warming_phase <= 1:
            logger.info(
                "Avatar %s at Phase %d — skipping demotion",
                avatar.reddit_username,
                avatar.warming_phase,
            )
            return False

        avatar_id_str = str(avatar.id)
        if not self.lock.acquire(avatar_id_str):
            logger.warning(
                "Could not acquire phase lock for avatar %s — skipping demotion",
                avatar_id_str,
            )
            return False

        try:
            previous_phase = avatar.warming_phase

            avatar.warming_phase = target_phase
            avatar.phase_changed_at = datetime.now(timezone.utc)

            self._record_event(
                db=db,
                avatar=avatar,
                event_type="auto_downgrade",
                previous_phase=previous_phase,
                new_phase=target_phase,
                metadata={"trigger_reason": trigger_reason},
            )

            db.commit()
            logger.info(
                "Avatar %s demoted from Phase %d to Phase %d (reason: %s)",
                avatar.reddit_username,
                previous_phase,
                target_phase,
                trigger_reason,
            )
            return True
        finally:
            self.lock.release(avatar_id_str)

    def admin_override(
        self,
        db: Session,
        avatar: Avatar,
        target_phase: int,
        admin_user_id: str,
        reason: str,
    ) -> bool:
        """Admin override to set avatar to a specific phase.

        Validates target_phase is 0, 1, 2, or 3. Acquires lock, updates fields,
        records phase_override ActivityEvent.

        Phase 0 = Mentor (excluded from all pipelines, no warming needed).

        Args:
            db: Database session.
            avatar: The avatar to override.
            target_phase: The phase to set (must be 0, 1, 2, or 3).
            admin_user_id: ID of the admin performing the override.
            reason: Explanation for the override.

        Returns:
            True if override succeeded, False if lock not acquired.

        Raises:
            ValueError: If target_phase is not in {0, 1, 2, 3}.
        """
        if target_phase not in {0, 1, 2, 3}:
            raise ValueError(
                f"target_phase must be 0, 1, 2, or 3, got {target_phase}"
            )

        avatar_id_str = str(avatar.id)
        if not self.lock.acquire(avatar_id_str):
            logger.warning(
                "Could not acquire phase lock for avatar %s — skipping admin override",
                avatar_id_str,
            )
            return False

        try:
            previous_phase = avatar.warming_phase

            avatar.warming_phase = target_phase
            avatar.phase_changed_at = datetime.now(timezone.utc)

            self._record_event(
                db=db,
                avatar=avatar,
                event_type="phase_override",
                previous_phase=previous_phase,
                new_phase=target_phase,
                metadata={
                    "admin_user_id": admin_user_id,
                    "reason": reason,
                },
            )

            db.commit()
            logger.info(
                "Avatar %s phase overridden from %d to %d by admin %s (reason: %s)",
                avatar.reddit_username,
                previous_phase,
                target_phase,
                admin_user_id,
                reason,
            )
            return True
        finally:
            self.lock.release(avatar_id_str)

    def _record_event(
        self,
        db: Session,
        avatar: Avatar,
        event_type: str,
        previous_phase: int,
        new_phase: int,
        metadata: dict,
    ) -> None:
        """Record a phase transition as an ActivityEvent.

        Args:
            db: Database session.
            avatar: The avatar involved in the transition.
            event_type: Type of event (phase_promotion, auto_downgrade, phase_override).
            previous_phase: The phase before transition.
            new_phase: The phase after transition.
            metadata: Additional context to store as JSONB.
        """
        client_id = None
        if avatar.client_ids:
            try:
                client_id = uuid.UUID(str(avatar.client_ids[0]))
            except (TypeError, ValueError):
                client_id = None

        event_metadata = {
            "avatar_id": str(avatar.id),
            "reddit_username": avatar.reddit_username,
            "previous_phase": previous_phase,
            "new_phase": new_phase,
            **metadata,
        }

        message = (
            f"Avatar {avatar.reddit_username} "
            f"{event_type.replace('_', ' ')} "
            f"from Phase {previous_phase} to Phase {new_phase}"
        )

        event = ActivityEvent(
            event_type=event_type,
            client_id=client_id,
            message=message,
            event_metadata=event_metadata,
        )
        db.add(event)
