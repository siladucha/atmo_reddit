from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://reddit_saas_user:change-me@db:5432/reddit_saas"
    app_name: str = "RAMP Marketing"
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
