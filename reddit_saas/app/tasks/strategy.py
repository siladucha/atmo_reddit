"""Celery task for async strategy generation.

Runs in background so the user can navigate away without losing the result.
Falls back to rule-based strategy if LLM fails.
Audit events:
  - strategy_generation_started (task picked up by worker)
  - strategy_generated (success — LLM or fallback)
  - strategy_generation_failed (unrecoverable error)
"""

import logging
import time
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
    task_start = time.time()
    try:
        from app.models.avatar import Avatar
        from app.models.client import Client
        from app.services.strategy_engine import StrategyEngine
        from app.services import audit as audit_service

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            logger.error("generate_strategy_async: avatar %s not found", avatar_id)
            return {"status": "error", "reason": "avatar_not_found"}

        client = None
        if client_id:
            client = db.query(Client).filter(Client.id == client_id).first()

        # --- Audit: task started (worker picked it up) ---
        try:
            _audit_log(
                db, user_id,
                action="strategy_generation_started",
                entity_type="avatar",
                entity_id=uuid.UUID(avatar_id),
                client_id=uuid.UUID(client_id) if client_id else None,
                details={
                    "avatar_username": avatar.reddit_username,
                    "celery_task_id": self.request.id,
                },
            )
        except Exception as e:
            logger.warning("Failed to audit strategy_generation_started: %s", e)

        engine = StrategyEngine()

        # Try LLM generation first
        try:
            strategy_doc = engine.generate_strategy(db, avatar, client)
            elapsed_ms = int((time.time() - task_start) * 1000)

            logger.info(
                "generate_strategy_async: LLM success for %s (v%d, %dms)",
                avatar.reddit_username, strategy_doc.version, elapsed_ms,
            )

            # --- Audit: success ---
            try:
                _audit_log(
                    db, user_id,
                    action="strategy_generated",
                    entity_type="strategy_document",
                    entity_id=strategy_doc.id,
                    client_id=uuid.UUID(client_id) if client_id else None,
                    details={
                        "avatar_username": avatar.reddit_username,
                        "version": strategy_doc.version,
                        "cost_usd": float(strategy_doc.cost_usd) if strategy_doc.cost_usd else None,
                        "model": strategy_doc.model_used,
                        "duration_ms": elapsed_ms,
                        "mode": "llm",
                    },
                )
            except Exception as e:
                logger.error("Failed to audit strategy_generated: %s", e, exc_info=True)

            return {
                "status": "success",
                "mode": "llm",
                "strategy_id": str(strategy_doc.id),
                "version": strategy_doc.version,
            }

        except RuntimeError as e:
            # LLM failed — fall back to rule-based strategy
            elapsed_ms = int((time.time() - task_start) * 1000)
            logger.warning(
                "generate_strategy_async: LLM failed for %s, using fallback: %s",
                avatar.reddit_username, str(e)[:200],
            )

            strategy_doc = engine.generate_fallback_strategy(db, avatar, client)

            # --- Audit: fallback success ---
            try:
                _audit_log(
                    db, user_id,
                    action="strategy_generated",
                    entity_type="strategy_document",
                    entity_id=strategy_doc.id,
                    client_id=uuid.UUID(client_id) if client_id else None,
                    details={
                        "avatar_username": avatar.reddit_username,
                        "version": strategy_doc.version,
                        "duration_ms": elapsed_ms,
                        "mode": "fallback",
                        "llm_error": str(e)[:200],
                    },
                )
            except Exception as audit_err:
                logger.error("Failed to audit strategy_generated (fallback): %s", audit_err)

            return {
                "status": "success",
                "mode": "fallback",
                "strategy_id": str(strategy_doc.id),
                "version": strategy_doc.version,
                "llm_error": str(e)[:200],
            }

    except Exception as e:
        elapsed_ms = int((time.time() - task_start) * 1000)
        logger.error("generate_strategy_async failed for avatar %s: %s", avatar_id, e, exc_info=True)

        # --- Audit: failure ---
        try:
            from app.services import audit as audit_service
            _audit_log(
                db, user_id,
                action="strategy_generation_failed",
                entity_type="avatar",
                entity_id=uuid.UUID(avatar_id),
                client_id=uuid.UUID(client_id) if client_id else None,
                details={
                    "error": str(e)[:300],
                    "duration_ms": elapsed_ms,
                },
            )
        except Exception:
            pass

        return {"status": "error", "reason": str(e)[:300]}
    finally:
        db.close()


def _audit_log(
    db,
    user_id: str | None,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    """Helper: write audit log with user_id or as system action."""
    from app.services import audit as audit_service

    if user_id:
        audit_service.log_action(
            db=db,
            user_id=uuid.UUID(user_id),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            client_id=client_id,
            details=details,
        )
    else:
        audit_service.log_system_action(
            db=db,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            client_id=client_id,
            details=details,
        )
