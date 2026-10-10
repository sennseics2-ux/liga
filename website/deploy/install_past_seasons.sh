#!/usr/bin/env bash
# Run on the hosting VM after installing this release. Never run against a
# different league directory. All database users are stopped until installation.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# The deployment's data directory is mode 700 and owned by container UID 10001.
# Check with the same privileges used by Docker, not the SSH account's access.
if ! sudo test -f .env; then
  echo "Missing .env in $(pwd). Run this script from the installed website on the VM." >&2
  exit 1
fi
if ! sudo test -f data/league.sqlite3; then
  echo "Missing database at $(pwd)/data/league.sqlite3. Installation has not started." >&2
  exit 1
fi
STAMP="past-seasons-$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="/backups/$STAMP/original"
PREPARED="/backups/$STAMP/prepared.sqlite3"
# Optional extra compose file for existing encrypted offsite backup installations.
COMPOSE=(sudo docker compose)
if [[ "${CHESS_USE_OFFSITE_COMPOSE:-0}" == 1 ]]; then
  COMPOSE+=(-f compose.yaml -f compose.offsite.yaml)
fi
"${COMPOSE[@]}" config -q
# Restart the existing deployment on failure; the generator never changes source.
trap '"${COMPOSE[@]}" up -d' EXIT
"${COMPOSE[@]}" down
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web \
  -m deploy.backup_sqlite --output-dir "$BACKUP_DIR" --keep 0
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web \
  demo/generate_past_seasons.py --source /data/league.sqlite3 --output "$PREPARED"
# Checkpoint any preserved WAL only after every database service is stopped.
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web -c \
  'import sqlite3; from contextlib import closing; from pathlib import Path
with closing(sqlite3.connect(Path("/data/league.sqlite3").as_uri()+"?mode=rw",uri=True)) as db:
    result=db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    assert result[0]==0, "Database still has active users; installation stopped"'
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web \
  -m deploy.backup_sqlite --restore "$PREPARED" --target /data/league.sqlite3 --overwrite
"${COMPOSE[@]}" up -d
trap - EXIT
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=60 web
printf 'Original database retained in /opt/clubdraft/backups/%s/original/\n' "$STAMP"
printf 'Prepared database retained in /opt/clubdraft/backups/%s/prepared.sqlite3\n' "$STAMP"
