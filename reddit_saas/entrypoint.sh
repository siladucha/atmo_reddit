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
alembic upgrade heads 2>&1 || {
    echo "Alembic migration failed, checking if tables exist..."
    
    # Check if base tables already exist (data was restored from dump)
    TABLE_EXISTS=$(python3 -c "
from app.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
tables = insp.get_table_names()
print('yes' if 'clients' in tables and 'system_settings' in tables else 'no')
")
    
    if [ "$TABLE_EXISTS" = "yes" ]; then
        echo "Tables already exist (restored from dump). Skipping alembic."
    else
        echo "No tables found. Creating via create_all..."
        python3 -c "
from app.database import engine, Base
from app.models import *
Base.metadata.create_all(bind=engine)
print('Tables created via create_all')
"
        echo "Tables created"
    fi
}

echo "Running seed data..."
python3 -m app.seed || echo "Seed already applied or skipped"

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
