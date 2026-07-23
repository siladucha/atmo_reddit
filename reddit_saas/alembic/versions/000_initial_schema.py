"""Initial schema — create all base tables for fresh database.

This migration creates all tables defined in the SQLAlchemy models using
metadata.create_all(checkfirst=True). This means:
- On a FRESH database (CI): creates all tables from scratch
- On an EXISTING database (prod/staging): skips tables that already exist

This is necessary because the project was originally bootstrapped via pg_restore
(not via migrations), so there was no initial migration creating core tables like
clients, users, avatars, subreddits, etc. Without this, alembic upgrade head on
an empty DB fails because later migrations reference tables that don't exist.

Revision ID: 000_initial
Revises:
Create Date: 2026-07-23 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "000_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables from SQLAlchemy models (checkfirst=True).

    Uses the ORM metadata to create tables in dependency order.
    checkfirst=True ensures existing tables (prod/staging) are not touched.

    On a fresh database, this creates the FULL current schema — all 87+ tables
    with all columns as they exist in the current model definitions. This means
    subsequent migrations that create these same tables or add columns will
    encounter "already exists" errors.

    To handle this, subsequent migrations should be written with idempotency checks.
    For existing migrations that don't have checks, the CI workflow stamps to head
    after this migration creates the schema.
    """
    import app.models  # noqa: F401 — registers all models with Base
    from app.database import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop all tables (DANGEROUS — only for CI teardown)."""
    import app.models  # noqa: F401
    from app.database import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
