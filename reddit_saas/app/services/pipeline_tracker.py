"""Pipeline Run Tracker — lightweight helper for pipeline observability.

Usage in any Celery task:

    from app.services.pipeline_tracker import track_pipeline

    with track_pipeline(db, "epg_build", avatar_id=avatar.id) as run:
        # ... do work ...
        run.items_processed = 5
        run.items_succeeded = 3
        run.items_failed = 1
        run.items_skipped = 1
        # On exit: auto-completes or auto-fails based on exception

Or manual:

    run = start_pipeline_run(db, "scoring", client_id=client.id)
    try:
        ... work ...
        complete_pipeline_run(db, run, succeeded=10)
    except Exception as e:
        fail_pipeline_run(db, run, str(e))
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.pipeline_run import PipelineRun

logger = get_logger(__name__)


def start_pipeline_run(
    db: Session,
    pipeline_type: str,
    *,
    avatar_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    trigger_source: str = "scheduler",
    meta: dict | None = None,
) -> PipelineRun:
    """Create and persist a new pipeline run record."""
    run = PipelineRun(
        pipeline_type=pipeline_type,
        trigger_source=trigger_source,
        avatar_id=avatar_id,
        client_id=client_id,
        status="running",
        started_at=datetime.now(timezone.utc),
        meta=meta,
    )
    db.add(run)
    db.flush()  # Get ID without committing
    return run


def complete_pipeline_run(
    db: Session,
    run: PipelineRun,
    succeeded: int = 0,
    failed: int = 0,
    skipped: int = 0,
) -> None:
    """Mark a pipeline run as completed."""
    run.complete(items_succeeded=succeeded, items_failed=failed, items_skipped=skipped)
    run.items_processed = succeeded + failed + skipped
    db.flush()


def fail_pipeline_run(
    db: Session,
    run: PipelineRun,
    error_message: str,
    error_type: str = "exception",
) -> None:
    """Mark a pipeline run as failed."""
    run.fail(error_message=error_message, error_type=error_type)
    db.flush()


@contextmanager
def track_pipeline(
    db: Session,
    pipeline_type: str,
    *,
    avatar_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    trigger_source: str = "scheduler",
    meta: dict | None = None,
):
    """Context manager for tracking pipeline runs with auto-complete/fail.

    Usage:
        with track_pipeline(db, "epg_build", avatar_id=a.id) as run:
            # do work
            run.items_succeeded = 3
    """
    run = start_pipeline_run(
        db, pipeline_type,
        avatar_id=avatar_id,
        client_id=client_id,
        trigger_source=trigger_source,
        meta=meta,
    )
    try:
        yield run
        # If user didn't set status manually, auto-complete
        if run.status == "running":
            run.complete(
                items_succeeded=run.items_succeeded,
                items_failed=run.items_failed,
                items_skipped=run.items_skipped,
            )
            run.items_processed = run.items_succeeded + run.items_failed + run.items_skipped
        db.flush()
    except Exception as e:
        run.fail(error_message=str(e)[:2000], error_type=type(e).__name__)
        db.flush()
        raise
