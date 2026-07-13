"""Plan Enforcer — runtime plan limit checking and counter management.

Called by:
- portfolio_manager.py (EPG build) — get_remaining_budget() as budget ceiling
- posting.py / draft_reconciliation.py — increment_counter() on draft→posted
- plan_enforcement.py (existing) — delegates here when billing_enabled=true
- admin routes — check_avatar_limit() on avatar assignment

All enforcement gated by `billing_enabled` system setting. When false,
all methods return permissive defaults (generation_allowed=True, counters are no-op).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.client_subscription import ClientSubscription
from app.models.comment_draft import CommentDraft
from app.models.plan_definition import PlanDefinition

logger = get_logger(__name__)


@dataclass
class BudgetStatus:
    """Result of get_remaining_budget() — tells pipeline what's allowed."""

    actions_remaining: int
    posts_remaining: int
    generation_allowed: bool
    days_remaining: int
    reason: str | None = None  # only set when generation_allowed=False


class PlanEnforcer:
    """Runtime plan limit checks. Fast, stateless per-call."""

    def is_billing_enabled(self, db: Session) -> bool:
        """Check if billing enforcement is active."""
        from app.services.settings import get_setting
        return get_setting(db, "billing_enabled") == "true"

    def get_remaining_budget(self, db: Session, client_id: UUID) -> BudgetStatus:
        """Returns remaining actions, posts, and whether generation is allowed.

        If billing_enabled=false, returns unlimited budget.
        Agency tier: always allowed (soft enforcement only).
        """
        if not self.is_billing_enabled(db):
            return BudgetStatus(
                actions_remaining=9999,
                posts_remaining=999,
                generation_allowed=True,
                days_remaining=30,
            )

        subscription = (
            db.query(ClientSubscription)
            .filter(ClientSubscription.client_id == client_id)
            .first()
        )
        if not subscription:
            # No subscription record — allow (fail-open)
            return BudgetStatus(
                actions_remaining=9999,
                posts_remaining=999,
                generation_allowed=True,
                days_remaining=30,
            )

        # Check subscription status — suspended/canceled/archived = blocked
        if subscription.status in ("suspended", "canceled", "archived", "trial_expired"):
            return BudgetStatus(
                actions_remaining=0,
                posts_remaining=0,
                generation_allowed=False,
                days_remaining=0,
                reason=f"subscription_{subscription.status}",
            )

        # Get effective limits
        max_actions = self.get_effective_limit(db, client_id, "max_actions_per_month")
        max_posts = self.get_effective_limit(db, client_id, "max_posts_per_month")

        actions_remaining = max(0, max_actions - subscription.monthly_action_counter)
        posts_remaining = max(0, max_posts - subscription.monthly_post_counter)

        # Agency tier: soft enforcement (never block)
        client = db.query(Client).filter(Client.id == client_id).first()
        is_agency = client and client.plan_type == "agency"

        if actions_remaining <= 0 and not is_agency:
            return BudgetStatus(
                actions_remaining=0,
                posts_remaining=0,
                generation_allowed=False,
                days_remaining=self._compute_days_remaining(subscription),
                reason="plan_limit_reached",
            )

        return BudgetStatus(
            actions_remaining=actions_remaining if not is_agency else 9999,
            posts_remaining=posts_remaining if not is_agency else 999,
            generation_allowed=True,
            days_remaining=self._compute_days_remaining(subscription),
        )

    def increment_counter(self, db: Session, client_id: UUID, is_post: bool = False) -> None:
        """Increment monthly counter. Called when draft→posted.

        Atomic SQL UPDATE prevents race conditions.
        Emits notifications at 80%, 90%, 100% thresholds.
        """
        if not self.is_billing_enabled(db):
            return

        # Atomic increment
        stmt = (
            db.query(ClientSubscription)
            .filter(ClientSubscription.client_id == client_id)
        )
        subscription = stmt.first()
        if not subscription:
            return

        subscription.monthly_action_counter += 1
        if is_post:
            subscription.monthly_post_counter += 1

        # Check threshold notifications
        max_actions = self.get_effective_limit(db, client_id, "max_actions_per_month")
        if max_actions > 0:
            percentage = (subscription.monthly_action_counter / max_actions) * 100
            self._check_threshold_notification(
                db, client_id, subscription, percentage, max_actions
            )

        db.flush()

    def check_avatar_limit(self, db: Session, client_id: UUID) -> tuple[bool, str]:
        """Check if client can add another avatar.

        Returns (is_allowed, message).
        """
        if not self.is_billing_enabled(db):
            return True, ""

        max_avatars = self.get_effective_limit(db, client_id, "max_avatars")

        # Count current active avatars for this client
        active_count = (
            db.query(func.count(Avatar.id))
            .filter(
                Avatar.client_ids.any(str(client_id)),
                Avatar.is_frozen == False,
            )
            .scalar() or 0
        )

        if active_count >= max_avatars:
            return False, f"Avatar limit reached ({active_count}/{max_avatars}). Upgrade plan for more."

        return True, ""

    def get_effective_limit(self, db: Session, client_id: UUID, limit_key: str) -> int:
        """Get effective limit: Per_Client_Override > plan_definitions.

        Per_Client_Override = explicit value on client record (custom deals).
        """
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return 0

        # Check per-client override first
        override_value = self._get_client_override(client, limit_key)
        if override_value is not None:
            return override_value

        # Fall back to plan_definitions
        plan_def = (
            db.query(PlanDefinition)
            .filter(PlanDefinition.plan_type == client.plan_type)
            .first()
        )
        if not plan_def:
            logger.warning("PLAN_ENFORCER_NO_PLAN_DEF | client_id=%s | plan=%s", client_id, client.plan_type)
            return 0

        return getattr(plan_def, limit_key, 0)

    def reconcile_counter(self, db: Session, client_id: UUID) -> None:
        """Daily reconciliation: recompute counter from posted drafts.

        Compares stored counter vs actual posted drafts in billing period.
        If drift > 5%, corrects and logs.
        """
        if not self.is_billing_enabled(db):
            return

        subscription = (
            db.query(ClientSubscription)
            .filter(ClientSubscription.client_id == client_id)
            .first()
        )
        if not subscription or not subscription.billing_period_start:
            return

        # Count actual posted drafts in billing period
        avatar_ids = (
            db.query(Avatar.id)
            .filter(Avatar.client_ids.any(str(client_id)))
            .all()
        )
        avatar_id_list = [a.id for a in avatar_ids]
        if not avatar_id_list:
            return

        actual_count = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id.in_(avatar_id_list),
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= subscription.billing_period_start,
                CommentDraft.posted_at <= (subscription.billing_period_end or datetime.now(timezone.utc)),
            )
            .scalar() or 0
        )

        stored = subscription.monthly_action_counter
        if stored == 0 and actual_count == 0:
            return

        # Check drift
        drift_pct = abs(stored - actual_count) / max(stored, actual_count, 1) * 100
        if drift_pct > 5:
            logger.warning(
                "BILLING_COUNTER_DRIFT | client_id=%s | stored=%d | actual=%d | drift=%.1f%%",
                client_id, stored, actual_count, drift_pct,
            )
            subscription.monthly_action_counter = actual_count
            db.flush()

            # Emit activity event
            from app.models.activity_event import ActivityEvent
            activity = ActivityEvent(
                client_id=client_id,
                event_type="billing_counter_drift",
                details={
                    "stored": stored,
                    "actual": actual_count,
                    "drift_pct": round(drift_pct, 1),
                    "corrected_to": actual_count,
                },
            )
            db.add(activity)

    def _compute_days_remaining(self, subscription: ClientSubscription) -> int:
        """Compute days remaining in billing period."""
        if not subscription.billing_period_end:
            return 30  # default for trial/unconfigured

        now = datetime.now(timezone.utc)
        delta = subscription.billing_period_end - now
        return max(1, delta.days)

    def _get_client_override(self, client: Client, limit_key: str) -> int | None:
        """Check if client has a per-client override for this limit.

        Existing override fields on Client model:
        - max_comments_per_month → maps to max_actions_per_month
        - max_avatars → maps to max_avatars
        """
        if limit_key == "max_actions_per_month" and client.max_comments_per_month is not None:
            return client.max_comments_per_month
        if limit_key == "max_avatars" and client.max_avatars is not None:
            # max_avatars always has a value (default 3) — only treat as override
            # if it differs from what plan_definitions would give
            return client.max_avatars
        return None

    def _check_threshold_notification(
        self,
        db: Session,
        client_id: UUID,
        subscription: ClientSubscription,
        percentage: float,
        max_actions: int,
    ) -> None:
        """Emit notification at 80%, 90%, 100% thresholds."""
        current_threshold = subscription.last_notified_threshold

        new_threshold = 0
        if percentage >= 100:
            new_threshold = 100
        elif percentage >= 90:
            new_threshold = 90
        elif percentage >= 80:
            new_threshold = 80

        if new_threshold > current_threshold:
            subscription.last_notified_threshold = new_threshold

            # Emit notification
            from app.services.notifications import notify_client
            if new_threshold == 100:
                title = f"Monthly limit reached ({subscription.monthly_action_counter}/{max_actions})"
                notify_type = "warning"
            elif new_threshold == 90:
                title = f"90% of monthly limit used ({subscription.monthly_action_counter}/{max_actions})"
                notify_type = "warning"
            else:
                title = f"80% of monthly limit used ({subscription.monthly_action_counter}/{max_actions})"
                notify_type = "info"

            notify_client(
                db, client_id, notify_type, title,
                body="Consider upgrading your plan for more capacity.",
                link=f"/clients/{client_id}/billing",
            )

            logger.info(
                "BILLING_THRESHOLD_NOTIFICATION | client_id=%s | threshold=%d%% | counter=%d/%d",
                client_id, new_threshold, subscription.monthly_action_counter, max_actions,
            )
