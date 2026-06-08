"""Logging configuration with daily rotation, 7 days history.

Full observability: all Reddit API calls, LLM calls, user actions,
and system events are logged for complete audit trail.

Usage in any module:
    from app.logging_config import get_logger
    logger = get_logger(__name__)
"""

import os
import logging
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = "logs"
LOG_FORMAT = "%(asctime)s | %(process)d | %(thread)d | %(funcName)s | %(filename)s:%(lineno)d | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """Configure logging with console + daily rotating file."""
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler — rotate at midnight, keep 7 days
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, "app.log"),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"
    root.addHandler(file_handler)

    # --- Library log levels ---
    # Reddit API: log all HTTP requests to Reddit (INFO level shows requests)
    logging.getLogger("prawcore").setLevel(logging.DEBUG)
    logging.getLogger("praw").setLevel(logging.DEBUG)

    # HTTP access logs: see all incoming requests
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    # LiteLLM: keep at WARNING (our ai.py handles detailed logging)
    logging.getLogger("litellm").setLevel(logging.WARNING)

    # Quiet truly noisy libraries that add no value
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.INFO)  # Shows Reddit HTTP connections


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Use as: logger = get_logger(__name__)"""
    return logging.getLogger(name)
