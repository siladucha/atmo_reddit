"""Celery task for async strategy generation.

Runs in background so the user can navigate away without losing the result.
Falls back to rule-based strategy if LLM fails.
"""

import logging
import uuid

from app.tasks.worker import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="generate_strategy_async", bind=True, max_retries=1)
def generate_strategy_async(self, avatar_id: str, client_id: str | None = None, user_id: str | None = None):
    """Generate strategy in background. Falls back to rule-based on LLM failure.

    Args:
        avatar_id: UUID string of the avatar.
        client_id: UUID string of the client (optional).
        user_id: UUID string of the user who triggered (for audit).

    Returns:
        Dict with status and strategy_document_id.
    """
    db = SessionLocal()
    try:
        from app.models.avatar import Avatar
        from app.models.client import Client
        from app.services.strategy_engine import StrategyEngine

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            logger.error("generate_strategy_async: avatar %s not found", avatar_id)
            return {"status": "error", "reason": "avatar_not_found"}

        client = None
        if client_id:
            client = db.query(Client).filter(Client.id == client_id).first()

        engine = StrategyEngine()

        # Try LLM generation first
        try:
            strategy_doc = engine.generate_strategy(db, avatar, client)
            logger.info(
                "generate_strategy_async: LLM success for %s (v%d)",
                avatar.reddit_username, strategy_doc.version,
            )

            # Audit log
            if user_id:
                try:
                    from app.services import audit as audit_service
                    audit_service.log_action(
                        db=db,
                        user_id=uuid.UUID(user_id),
                        action="strategy_generated",
                        entity_type="strategy_document",
                        entity_id=strategy_doc.id,
                        client_id=uuid.UUID(client_id) if client_id else None,
                        details={
                            "avatar_username": avatar.reddit_username,
                            "version": strategy_doc.version,
                            "cost_usd": strategy_doc.cost_usd,
                            "model": strategy_doc.model_used,
                            "mode": "llm",
                        },
                    )
                except Exception:
                    logger.warning("Failed to audit log strategy generation")

            return {
                "status": "success",
                "mode": "llm",
                "strategy_id": str(strategy_doc.id),
                "version": strategy_doc.version,
            }

        except RuntimeError as e:
            # LLM failed — fall back to rule-based strategy
            logger.warning(
                "generate_strategy_async: LLM failed for %s, using fallback: %s",
                avatar.reddit_username, str(e)[:200],
            )

            strategy_doc = engine.generate_fallback_strategy(db, avatar, client)

            return {
                "status": "success",
                "mode": "fallback",
                "strategy_id": str(strategy_doc.id),
                "version": strategy_doc.version,
                "llm_error": str(e)[:200],
            }

    except Exception as e:
        logger.error("generate_strategy_async failed for avatar %s: %s", avatar_id, e, exc_info=True)
        return {"status": "error", "reason": str(e)[:300]}
    finally:
        db.close()
