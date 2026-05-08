#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head 2>&1 || {
    echo "Alembic migration failed, falling back to create_all + stamp head..."
    python -c "
from app.database import engine, Base
from app.models import *
Base.metadata.create_all(bind=engine)
print('Tables created via create_all')
"
    alembic stamp head
    echo "Stamped alembic to head"
}

echo "Running seed data..."
python -m app.seed || echo "Seed already applied or skipped"

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
