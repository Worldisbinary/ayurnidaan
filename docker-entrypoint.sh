#!/bin/sh
# Apply schema migrations, then serve. Migrations are idempotent (alembic tracks the
# applied revision), so every deploy and restart can safely run them first.
set -e
alembic upgrade head
exec uvicorn ayurnidaan.app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" --proxy-headers --forwarded-allow-ips="*"
