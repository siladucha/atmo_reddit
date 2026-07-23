#!/bin/bash
set -e

echo "Ensuring pgvector extension..."
python3 -c "
from app.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
try:
    db.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
    db.commit()
    print('pgvector extension OK')
except Exception as e:
    db.rollback()
    print(f'pgvector extension warning: {e}')
finally:
    db.close()
" || echo "pgvector extension check skipped"

echo "Running database migrations..."
if alembic upgrade head 2>&1; then
    echo "Alembic migrations applied successfully."
else
    ALEMBIC_EXIT=$?
    echo "ALEMBIC MIGRATION FAILED (exit code: $ALEMBIC_EXIT)"

    # Check if this is a fresh DB restore (no alembic_version row = pg_restore scenario)
    HAS_ALEMBIC_VERSION=$(python3 -c "
from app.database import engine
from sqlalchemy import inspect, text
insp = inspect(engine)
tables = insp.get_table_names()
if 'alembic_version' not in tables:
    print('no_table')
else:
    from app.database import SessionLocal
    db = SessionLocal()
    row = db.execute(text('SELECT version_num FROM alembic_version LIMIT 1')).fetchone()
    db.close()
    print('has_version' if row else 'empty_table')
" 2>/dev/null || echo "error")

    if [ "$HAS_ALEMBIC_VERSION" = "no_table" ] || [ "$HAS_ALEMBIC_VERSION" = "empty_table" ]; then
        # Fresh pg_restore scenario — tables exist but no Alembic tracking
        TABLE_EXISTS=$(python3 -c "
from app.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
tables = insp.get_table_names()
print('yes' if 'clients' in tables and 'system_settings' in tables else 'no')
")
        if [ "$TABLE_EXISTS" = "yes" ]; then
            echo "NOTICE: pg_restore detected (tables exist, no alembic tracking). Stamping head..."
            alembic stamp head 2>&1 || echo "ERROR: Stamp failed -- manual intervention needed"
        else
            echo "CRITICAL: No tables found and migrations failed. Creating via create_all..."
            python3 -c "
from app.database import engine, Base
from app.models import *
Base.metadata.create_all(bind=engine)
print('Tables created via create_all')
"
            alembic stamp head 2>&1 || echo "ERROR: Stamp after create_all failed"
            echo "Tables created"
        fi
    else
        # Alembic tracking EXISTS but migration failed — this is a REAL error.
        # Do NOT stamp head. Fail loudly so CI catches it.
        echo "❌ CRITICAL: Migration failed on a tracked database. NOT stamping head."
        echo "❌ This means new code requires schema changes that could not be applied."
        echo "❌ Container will start but app may be broken. Check alembic logs above."
        # Exit with error so Docker marks container as failed and CI catches it
        exit 1
    fi
fi

echo "Running seed data..."
python3 -m app.seed || echo "Seed already applied or skipped"

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
