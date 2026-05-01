"""Pipeline trigger routes — for manual testing and admin control."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.tasks.scraping import scrape_professional_subreddits, scrape_hobby_subreddits
from app.tasks.ai_pipeline import score_threads, generate_comments, generate_hobby_comments

router = APIRouter()


@router.post("/scrape/{client_id}")
def trigger_scrape(client_id: UUID):
    """Trigger professional subreddit scraping for a client."""
    task = scrape_professional_subreddits.delay(str(client_id))
    return {"task_id": task.id, "status": "queued", "action": "scrape_professional"}


@router.post("/score/{client_id}")
def trigger_scoring(client_id: UUID):
    """Trigger thread scoring for a client."""
    task = score_threads.delay(str(client_id))
    return {"task_id": task.id, "status": "queued", "action": "score_threads"}


@router.post("/generate/{client_id}")
def trigger_generation(client_id: UUID):
    """Trigger comment generation for a client."""
    task = generate_comments.delay(str(client_id))
    return {"task_id": task.id, "status": "queued", "action": "generate_comments"}


@router.post("/full-pipeline/{client_id}")
def trigger_full_pipeline(client_id: UUID):
    """Trigger the full pipeline: scrape → score → generate."""
    # Chain tasks: scrape first, then score, then generate
    chain = (
        scrape_professional_subreddits.si(str(client_id))
        | score_threads.si(str(client_id))
        | generate_comments.si(str(client_id))
    )
    result = chain.apply_async()
    return {"task_id": result.id, "status": "queued", "action": "full_pipeline"}


@router.post("/hobby/{avatar_id}")
def trigger_hobby_pipeline(avatar_id: UUID):
    """Trigger hobby scraping + comment generation for an avatar."""
    scrape_task = scrape_hobby_subreddits.delay(str(avatar_id))
    return {"task_id": scrape_task.id, "status": "queued", "action": "hobby_pipeline"}
