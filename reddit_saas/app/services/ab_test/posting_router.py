"""Posting Method Router — delivery channel override for A/B test participants.

Routes tasks to the correct posting method based on the avatar's treatment
group assignment. Integrates with task creation flow to override the avatar's
configured delivery_channel during active experiments.

Usage:
    from app.services.ab_test.posting_router import get_posting_method

    config = get_posting_method(db, avatar_id)
    if config:
        # Avatar is in active experiment — use experiment posting method
        task.delivery_channel = config.delivery_channel
        task.posting_strategy = config.posting_strategy
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.ab_test import (
    AvatarAssignment,
    ExperimentRun,
    TreatmentGroup,
)
from app.services.ab_test import experiment_manager

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PostingMethodConfig:
    """Configuration for experiment-controlled posting method."""

    delivery_channel: str  # "email" | "extension"
    posting_strategy: str  # "old_reddit" | "manual_email" | "new_reddit_debugger"
    experiment_id: uuid.UUID
    group_id: uuid.UUID


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


METHOD_TO_CHANNEL: dict[str, str] = {
    "old_reddit": "extension",           # extension with old_reddit mode
    "manual_email": "email",             # standard email delivery
    "new_reddit_debugger": "extension",  # extension with debugger mode (default)
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_posting_method(
    db: Session,
    avatar_id: uuid.UUID,
) -> PostingMethodConfig | None:
    """Get posting method override for an experiment participant.

    Returns None if avatar is not in an active experiment (early return
    for performance). Otherwise queries the avatar's assignment and
    treatment group to determine the correct delivery channel and
    posting strategy.

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar to check.

    Returns:
        PostingMethodConfig with delivery_channel, posting_strategy,
        experiment_id, and group_id — or None if avatar is not
        participating in any active experiment.
    """
    # Fast check: is avatar in an active experiment?
    active_experiment = experiment_manager.get_active_experiment_for_avatar(
        db, avatar_id
    )
    if not active_experiment:
        return None

    # Get the avatar's assignment (non-excluded, in this active experiment)
    assignment = (
        db.query(AvatarAssignment)
        .filter(
            AvatarAssignment.experiment_id == active_experiment.id,
            AvatarAssignment.avatar_id == avatar_id,
            AvatarAssignment.is_excluded == False,  # noqa: E712
        )
        .first()
    )
    if not assignment:
        return None

    # Get the treatment group to determine posting_method
    group = (
        db.query(TreatmentGroup)
        .filter(TreatmentGroup.id == assignment.group_id)
        .first()
    )
    if not group:
        logger.warning(
            "TreatmentGroup %s not found for assignment %s",
            assignment.group_id,
            assignment.id,
        )
        return None

    # Map posting_method to delivery_channel
    posting_method = group.posting_method
    delivery_channel = METHOD_TO_CHANNEL.get(posting_method)

    if not delivery_channel:
        logger.warning(
            "Unknown posting_method '%s' for group %s — no channel mapping.",
            posting_method,
            group.id,
        )
        return None

    return PostingMethodConfig(
        delivery_channel=delivery_channel,
        posting_strategy=posting_method,
        experiment_id=active_experiment.id,
        group_id=group.id,
    )
