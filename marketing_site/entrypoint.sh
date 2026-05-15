#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until nc -z db 5432; do
    echo "PostgreSQL not ready, waiting..."
    sleep 2
done
echo "PostgreSQL is ready."

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting marketing site..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
