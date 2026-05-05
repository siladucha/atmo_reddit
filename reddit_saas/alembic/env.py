from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, create_engine
from alembic import context

from app.config import get_settings
from app.database import Base
from app.models import *  # noqa: F401,F403 — import all models so Alembic sees them

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Use DATABASE_URL from .env instead of alembic.ini
app_settings = get_settings()


def run_migrations_offline() -> None:
    context.configure(
        url=app_settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(app_settings.database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
