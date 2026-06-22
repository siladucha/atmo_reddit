"""Trial guard — utility to check if a trial client has expired.

Used by pipeline tasks to skip expired trials (prevents AI resource consumption
for unpaying users).
"""

from datetime import datetime, timezone

from app.models.client import Client

TRIAL_DURATION_DAYS = 14


def is_trial_expired(client: Client) -> bool:
    """Check if a trial client's 14-day window has elapsed.

    Returns False for non-trial clients (they always pass).
    """
    if client.plan_type != "trial":
        return False

    if not client.created_at:
        return False

    days_elapsed = (datetime.now(timezone.utc) - client.created_at).days
    return days_elapsed > TRIAL_DURATION_DAYS
