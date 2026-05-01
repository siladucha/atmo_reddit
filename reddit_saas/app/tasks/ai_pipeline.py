from app.tasks.worker import celery_app


@celery_app.task(name="score_threads")
def score_threads(client_id: str):
    """Score unscored threads with AI. Runs after scraping."""
    # TODO: implement with LiteLLM/Bedrock
    pass


@celery_app.task(name="generate_comments")
def generate_comments(client_id: str):
    """Generate comments for 'engage' threads. Runs after scoring."""
    # TODO: implement with LiteLLM/Bedrock
    pass


@celery_app.task(name="generate_hobby_comments")
def generate_hobby_comments(avatar_id: str):
    """Generate hobby comments for karma building."""
    # TODO: implement with LiteLLM/Bedrock
    pass


@celery_app.task(name="generate_posts")
def generate_posts(client_id: str):
    """Generate post drafts. Runs on schedule."""
    # TODO: implement with LiteLLM/Bedrock
    pass
