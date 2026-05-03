from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/reddit_saas"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 1440
    algorithm: str = "HS256"

    # Admin
    admin_email: str = "max@admin.com"
    admin_password: str = ""
    admin_name: str = "Admin"

    # Reddit API
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "reddit-saas:v0.1.0"

    # LLM
    litellm_api_key: str = ""
    litellm_scoring_model: str = "gemini/gemini-2.0-flash"
    litellm_generation_model: str = "anthropic/claude-sonnet-4-20250514"

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
