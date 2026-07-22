"""Access Gate — subscription-aware platform access control.

Gates platform features (pipeline execution, portal access, read-only mode)
based on the client's subscription_status field.

Supersedes trial_guard.py for all subscription-aware gating logic.
"""

from datetime import datetime, timezone

from app.models.client import Client

TRIAL_DURATION_DAYS = 14


class AccessGate:
    """Gates platform features based on subscription status.

    Replaces trial_guard.py with full subscription-aware gating.
    """

    # Statuses that block pipeline execution (scoring, generation, EPG)
    PIPELINE_BLOCKED = {"past_due", "canceled", "trial_expired"}

    # Statuses that allow full access (pipeline + portal + actions)
    FULL_ACCESS = {"active", "trialing"}

    # Statuses that allow read-only portal access within grace period
    READ_ONLY_GRACE = {"past_due", "canceled"}
    GRACE_PERIOD_DAYS = 30

    @staticmethod
    def can_execute_pipeline(client: Client) -> bool:
        """Check if client's subscription allows pipeline execution.

        Used by EPG, scoring, generation tasks to gate AI resource usage.

        Returns True for:
          - active (paying subscriber)
          - trialing (Stripe trial with payment method)
          - trial (legacy trial, not yet expired — treated same as trialing)

        Returns False for:
          - past_due (payment failed)
          - canceled (subscription ended)
          - trial_expired (legacy trial past 14 days)
        """
        status = client.subscription_status or "trial"

        # Legacy "trial" (no Stripe checkout) treated same as "trialing"
        # for pipeline access — full access until expiry
        if status == "trial":
            return not AccessGate._is_legacy_trial_expired(client)

        return status not in AccessGate.PIPELINE_BLOCKED

    @staticmethod
    def can_access_portal(client: Client) -> bool:
        """Check if client can access the portal.

        Returns True for all statuses EXCEPT trial_expired past 30 days.
        Clients in past_due/canceled get read-only access for 30 days.
        """
        status = client.subscription_status or "trial"

        if status == "trial_expired":
            # Allow portal access for 30 days after expiry
            return AccessGate._within_grace_period(client)

        # All other statuses can access portal
        # (active, trialing, trial, past_due, canceled — all get portal)
        return True

    @staticmethod
    def is_read_only(client: Client) -> bool:
        """Check if client is in read-only grace period.

        Returns True when status is past_due or canceled AND within
        30 days of subscription_canceled_at.

        Read-only means: can view data, reports, drafts but cannot
        trigger pipeline actions or create new content.
        """
        status = client.subscription_status or "trial"

        if status not in AccessGate.READ_ONLY_GRACE:
            return False

        return AccessGate._within_grace_period(client)

    @staticmethod
    def check_trial_expiry(client: Client) -> bool:
        """For legacy trials (no Stripe checkout), check 14-day expiry.

        Only applies to subscription_status == "trial" (legacy trials
        without Stripe). If 14 days have passed since created_at, sets
        subscription_status to "trial_expired".

        Returns True if the trial is expired (status was set or was already expired).
        Returns False if not a legacy trial or not yet expired.

        Note: Does NOT call db.commit() — caller must commit the session.
        """
        status = client.subscription_status or "trial"

        if status != "trial":
            return status == "trial_expired"

        if AccessGate._is_legacy_trial_expired(client):
            client.subscription_status = "trial_expired"
            return True

        return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_legacy_trial_expired(client: Client) -> bool:
        """Check if a legacy trial (subscription_status='trial') has passed 14 days."""
        if not client.created_at:
            return False

        now = datetime.now(timezone.utc)
        created = client.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        days_elapsed = (now - created).days
        return days_elapsed > TRIAL_DURATION_DAYS

    @staticmethod
    def _within_grace_period(client: Client) -> bool:
        """Check if within 30-day grace period from cancellation/expiry.

        Uses subscription_canceled_at if available. If None but status is
        canceled/past_due, allows access (safety — shouldn't happen in
        production but we don't want to lock out clients due to missing data).
        """
        if client.subscription_canceled_at is None:
            # Safety: if no cancellation date recorded, allow access
            # (shouldn't happen for properly-managed subscriptions)
            return True

        now = datetime.now(timezone.utc)
        canceled_at = client.subscription_canceled_at
        if canceled_at.tzinfo is None:
            canceled_at = canceled_at.replace(tzinfo=timezone.utc)

        days_since = (now - canceled_at).days
        return days_since <= AccessGate.GRACE_PERIOD_DAYS
