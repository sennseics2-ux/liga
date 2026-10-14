#!/usr/bin/env bash
# Explicitly reset the installed league, retaining one existing admin and backups.
set -euo pipefail
if [[ "${1:-}" != '--keep-admin-only' || $# -gt 2 ]]; then
  echo 'Usage: sudo bash deploy/reset_database.sh --keep-admin-only [admin-username]' >&2
  exit 2
fi
shift
ADMIN_ARGS=()
if [[ $# == 1 ]]; then ADMIN_ARGS=(--admin-username "$1"); fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."
sudo test -f .env || { echo 'Missing installed .env; reset has not started.' >&2; exit 1; }
sudo test -f data/league.sqlite3 || { echo 'Missing installed database; reset has not started.' >&2; exit 1; }
COMPOSE=(sudo docker compose)
if [[ "${CHESS_USE_OFFSITE_COMPOSE:-0}" == 1 ]]; then
  COMPOSE+=(-f compose.yaml -f compose.offsite.yaml)
fi
STAMP="reset-$(date -u +%Y%m%dT%H%M%S)-$$"
BACKUP_DIR="/backups/$STAMP/original"
PREPARED="/backups/$STAMP/prepared.sqlite3"
"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" build web
trap '"${COMPOSE[@]}" up -d' EXIT
"${COMPOSE[@]}" down
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web \
  -m deploy.backup_sqlite --output-dir "$BACKUP_DIR" --keep 0
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web \
  -m deploy.reset_league --source /data/league.sqlite3 --output "$PREPARED" "${ADMIN_ARGS[@]}"
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web -c \
  'import sqlite3; from contextlib import closing
with closing(sqlite3.connect("file:/data/league.sqlite3?mode=rw",uri=True)) as db:
    result=db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    assert result[0]==0, "Database still has active users; reset stopped"'
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python web \
  -m deploy.backup_sqlite --restore "$PREPARED" --target /data/league.sqlite3 --overwrite
"${COMPOSE[@]}" up -d
trap - EXIT
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=60 web
printf 'Reset complete. Log in again with the existing admin credentials.\n'
printf 'Original database backup: /opt/clubdraft/backups/%s/original/\n' "$STAMP"
