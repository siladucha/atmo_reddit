"""Discovery Artifact Store — persists all prompts, responses, and intermediate AI outputs.

Requirement: "For every significant operation the system must preserve:
inputs, prompts, intermediate results, decisions, actions, outcomes, costs, timestamps."

Each AI call in Discovery is stored as an artifact in session_metadata["artifacts"].
Structure:
{
    "artifacts": [
        {
            "id": "uuid",
            "operation": "entity_extraction|hypothesis_formation|report_generation|research",
            "timestamp": "ISO8601",
            "inputs": {"client_brief": "...", ...},
            "prompt": "full system+user prompt text",
            "response": "full LLM response text",
            "model": "gemini/gemini-2.5-flash-lite",
            "cost_usd": 0.0003,
            "tokens": {"input": 480, "output": 284},
            "outcome": "success|error|timeout",
            "result_summary": "extracted 8 entities" | "formed 5 hypotheses" | etc.
        }
    ]
}

This enables:
- Full prompt/response replay at any time
- Debugging why AI made specific decisions
- Audit trail compliance
- A/B testing of prompts (compare outputs from different prompts)
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.discovery_session import DiscoverySession

logger = get_logger(__name__)


def store_artifact(
    db: Session,
    session_id: uuid.UUID,
    operation: str,
    inputs: dict,
    prompt: str,
    response: str,
    model: str,
    cost_usd: float = 0.0,
    tokens: dict | None = None,
    outcome: str = "success",
    result_summary: str = "",
) -> dict:
    """Store a complete AI artifact in the Discovery session.

    Appends to session_metadata["artifacts"] array.
    Returns the stored artifact dict.
    """
    artifact = {
        "id": str(uuid.uuid4()),
        "operation": operation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
        "prompt": prompt[:10000],  # Cap at 10K chars to avoid bloat
        "response": response[:10000],
        "model": model,
        "cost_usd": cost_usd,
        "tokens": tokens or {},
        "outcome": outcome,
        "result_summary": result_summary,
    }

    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        logger.warning(f"Cannot store artifact — session {session_id} not found")
        return artifact

    # Initialize artifacts array if not exists
    metadata = session.session_metadata or {}
    if "artifacts" not in metadata:
        metadata["artifacts"] = []

    metadata["artifacts"].append(artifact)
    session.session_metadata = metadata

    # Force SQLAlchemy to detect JSONB mutation
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(session, "session_metadata")

    db.flush()

    logger.debug(
        "Artifact stored: session=%s op=%s model=%s cost=$%.4f",
        session_id, operation, model, cost_usd,
    )

    return artifact


def get_artifacts(db: Session, session_id: uuid.UUID) -> list[dict]:
    """Get all artifacts for a session."""
    session = db.query(DiscoverySession).filter(DiscoverySession.id == session_id).first()
    if not session:
        return []
    return (session.session_metadata or {}).get("artifacts", [])


def get_artifacts_by_operation(db: Session, session_id: uuid.UUID, operation: str) -> list[dict]:
    """Get artifacts filtered by operation type."""
    all_artifacts = get_artifacts(db, session_id)
    return [a for a in all_artifacts if a.get("operation") == operation]
