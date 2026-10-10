#!/bin/sh
set -eu
umask 077
: "${CHESS_DB_PATH:=/data/league.sqlite3}"
# Always capture a consistent backup BEFORE any automatic schema migration.
if [ -f "$CHESS_DB_PATH" ]; then
    python -m deploy.backup_sqlite --quiet
fi
python manage.py init
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000 \
    --workers 1 --proxy-headers --forwarded-allow-ips '*'
