#!/bin/sh
set -e

# Try to wait for DB using a short Python snippet (psycopg2 must be installed)
if [ -n "$DATABASE_URL" ]; then
  echo "Waiting for database..."
  python - <<'PY'
import os, time, sys
import psycopg2
dsn = os.environ.get("DATABASE_URL")
if not dsn:
    print("DATABASE_URL not set, skipping DB wait")
    sys.exit(0)
for i in range(60):
    try:
        conn = psycopg2.connect(dsn, connect_timeout=2)
        conn.close()
        print("Database ready")
        break
    except Exception as e:
        print("DB not ready yet:", e)
        time.sleep(1)
else:
    print("Database did not become ready in time")
    sys.exit(1)
PY
fi

# Run alembic migrations if alembic.ini exists
if [ -f "./alembic.ini" ]; then
  echo "Running alembic migrations..."
  alembic upgrade head
fi

# Start uvicorn; allow PORT from environment (Render sets $PORT)
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers
