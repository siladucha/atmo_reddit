from app.tasks.worker import celery_app


@celery_app.task(name="scrape_professional_subreddits")
def scrape_professional_subreddits(client_id: str):
    """Scrape professional subreddits for a client. Runs on schedule."""
    # TODO: implement with PRAW
    pass


@celery_app.task(name="scrape_hobby_subreddits")
def scrape_hobby_subreddits(avatar_id: str):
    """Scrape hobby subreddits for an avatar. Runs on schedule."""
    # TODO: implement with PRAW
    pass
