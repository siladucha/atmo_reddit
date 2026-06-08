"""Safety Blocks — Brand Mention Protection.

Prevents approval of drafts that contain brand mentions when the avatar
is still in Phase 1 or Phase 2 (credibility building).
"""

from app.logging_config import get_logger

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft

logger = get_logger(__name__)


def check_safety_blocks(
    draft: CommentDraft, avatar: Avatar, client: Client
) -> dict | None:
    """Return safety block info dict or None if safe to approve.

    Checks:
    1. Brand mention in Phase 1/2 → hard block.
    """
    # Hard block: brand mention in Phase 1 or Phase 2
    if avatar.warming_phase < 3 and client.brand_name:
        brand_terms = [client.brand_name.lower()]
        # Also check common variations
        if client.client_name and client.client_name.lower() != client.brand_name.lower():
            brand_terms.append(client.client_name.lower())

        comment_lower = (draft.edited_draft or draft.ai_draft or "").lower()
        for term in brand_terms:
            if term and term in comment_lower:
                logger.info(
                    "Safety block: brand mention '%s' in Phase %d draft | "
                    "draft_id=%s | avatar=%s",
                    term,
                    avatar.warming_phase,
                    draft.id,
                    avatar.reddit_username,
                )
                return {
                    "rule": "brand_mention_phase_block",
                    "avatar_phase": avatar.warming_phase,
                    "brand_detected": term,
                    "message": (
                        f"Brand mention blocked — {avatar.reddit_username} is still building "
                        f"credibility. Brand mentions unlock at Phase 3."
                    ),
                }

    return None  # Safe to approve
