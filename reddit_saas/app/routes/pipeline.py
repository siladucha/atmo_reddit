"""Pipeline trigger routes — for manual testing and admin control."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.user import User
from app.tasks.scraping import scrape_subreddit_shared, scrape_hobby_subreddits
from app.tasks.ai_pipeline import score_threads, generate_comments, generate_hobby_comments

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/scrape/{client_id}")
def trigger_scrape(
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Trigger subreddit scraping for a client.

    Dispatches shared scrape tasks for all subreddits assigned to this client.
    """
    from app.models.client import Client
    from app.models.subreddit import Subreddit, ClientSubredditAssignment

    client = db.query(Client).filter(Client.id == client_id, Client.is_active.is_(True)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found or inactive")

    # Get all active subreddit assignments for this client
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, Subreddit.id == ClientSubredditAssignment.subreddit_id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
            Subreddit.is_active.is_(True),
        )
        .all()
    )

    if not assignments:
        raise HTTPException(status_code=404, detail="No active subreddits for this client")

    task_ids = []
    for assignment in assignments:
        try:
            task = scrape_subreddit_shared.delay(str(assignment.subreddit_id))
            task_ids.append(task.id)
        except Exception as e:
            logger.error(f"Failed to dispatch scrape for subreddit {assignment.subreddit_id}: {e}")

    if not task_ids:
        raise HTTPException(status_code=503, detail="Task queue unavailable")

    return {"task_ids": task_ids, "status": "queued", "action": "scrape_shared", "count": len(task_ids)}


@router.post("/score/{client_id}")
def trigger_scoring(
    client_id: UUID,
    current_user: User = Depends(require_superuser),
):
    """Trigger thread scoring for a client."""
    try:
        task = score_threads.delay(str(client_id))
    except Exception as e:
        logger.error(f"Failed to dispatch scoring task for client {client_id}: {e}")
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e
    return {"task_id": task.id, "status": "queued", "action": "score_threads"}


@router.post("/generate/{client_id}")
def trigger_generation(
    client_id: UUID,
    current_user: User = Depends(require_superuser),
):
    """Trigger comment generation for a client."""
    try:
        task = generate_comments.delay(str(client_id))
    except Exception as e:
        logger.error(f"Failed to dispatch generation task for client {client_id}: {e}")
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e
    return {"task_id": task.id, "status": "queued", "action": "generate_comments"}


@router.post("/full-pipeline/{client_id}")
def trigger_full_pipeline(
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Trigger the full pipeline: scrape → score → generate.

    Dispatches shared scrape tasks for all client subreddits, then chains
    score and generate tasks.
    """
    from app.models.client import Client
    from app.models.subreddit import Subreddit, ClientSubredditAssignment

    client = db.query(Client).filter(Client.id == client_id, Client.is_active.is_(True)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found or inactive")

    # Get all active subreddit assignments for this client
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, Subreddit.id == ClientSubredditAssignment.subreddit_id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
            Subreddit.is_active.is_(True),
        )
        .all()
    )

    try:
        # Dispatch scrape tasks for all subreddits
        for assignment in assignments:
            scrape_subreddit_shared.delay(str(assignment.subreddit_id))

        # Chain score → generate (runs after scrapes complete independently)
        chain = (
            score_threads.si(str(client_id))
            | generate_comments.si(str(client_id))
        )
        result = chain.apply_async(countdown=30)  # 30s delay to let scrapes finish
    except Exception as e:
        logger.error(f"Failed to dispatch full pipeline for client {client_id}: {e}")
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e
    return {"task_id": result.id, "status": "queued", "action": "full_pipeline"}


@router.post("/hobby/{avatar_id}")
def trigger_hobby_pipeline(
    avatar_id: UUID,
    current_user: User = Depends(require_superuser),
):
    """Trigger hobby scraping + comment generation for an avatar."""
    try:
        scrape_task = scrape_hobby_subreddits.delay(str(avatar_id))
    except Exception as e:
        logger.error(f"Failed to dispatch hobby pipeline for avatar {avatar_id}: {e}")
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e
    return {"task_id": scrape_task.id, "status": "queued", "action": "hobby_pipeline"}


@router.post("/karma-track/{avatar_id}")
def trigger_karma_tracking(
    avatar_id: UUID,
    current_user: User = Depends(require_superuser),
):
    """Trigger karma tracking for a single avatar."""
    from app.tasks.karma_tracking import track_karma_single_avatar
    try:
        task = track_karma_single_avatar.delay(str(avatar_id))
    except Exception as e:
        logger.error(f"Failed to dispatch karma tracking for avatar {avatar_id}: {e}")
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e
    return {"task_id": task.id, "status": "queued", "action": "karma_track_avatar"}


@router.post("/karma-track-all")
def trigger_karma_tracking_all(
    current_user: User = Depends(require_superuser),
):
    """Trigger karma tracking for all active avatars."""
    from app.tasks.karma_tracking import track_karma_all_avatars
    try:
        task = track_karma_all_avatars.delay()
    except Exception as e:
        logger.error(f"Failed to dispatch karma tracking for all avatars: {e}")
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e
    return {"task_id": task.id, "status": "queued", "action": "karma_track_all"}
