#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head 2>&1 || {
    echo "Alembic migration failed, checking if tables exist..."
    
    # Check if base tables already exist (data was restored from dump)
    TABLE_EXISTS=$(python -c "
from app.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
tables = insp.get_table_names()
print('yes' if 'clients' in tables and 'system_settings' in tables else 'no')
")
    
    if [ "$TABLE_EXISTS" = "yes" ]; then
        echo "Tables already exist (restored from dump). Stamping alembic to head..."
        alembic stamp head
    else
        echo "No tables found. Creating via create_all..."
        python -c "
from app.database import engine, Base
from app.models import *
Base.metadata.create_all(bind=engine)
print('Tables created via create_all')
"
        alembic stamp head
        echo "Stamped alembic to head"
    fi
}

echo "Running seed data..."
python -m app.seed || echo "Seed already applied or skipped"

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
