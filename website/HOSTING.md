# Liga SX-AAC — deployment and recovery

The web application, HTTPS proxy and scheduled SQLite snapshots run with Docker
Compose. The existing domain, accounts and data remain compatible. PGN replay
and downloads require a signed-in account; fixture and result pages stay public.

## Upgrade an existing server

Run these commands on the server after reviewing the release. They are deployment
instructions, not evidence that this workspace has changed the live website.

1. Create a consistent backup and copy it off the VM before installing the release:

   ```sh
   cd /opt/clubdraft
   sudo docker compose exec -T web python -m deploy.backup_sqlite
   ```

   Preserve this snapshot separately. Never copy a running SQLite database with
   cp; committed changes may still be in its WAL file.

2. Unpack the release in your SSH home directory, stop database users and copy
   application files while preserving the existing secret and persistent data:

   ```sh
   cd /opt/clubdraft
   sudo docker compose down
   sudo rsync -a --exclude='/.env' --exclude='/data/' --exclude='/backups/' \
     --exclude='/secrets/' --exclude='/.venv/' --exclude='/__pycache__/' \
     ~/chess-fantasy-league-v24/ /opt/clubdraft/
   sudo docker compose config -q
   sudo docker compose up -d --build
   sudo docker compose ps
   sudo docker compose logs --tail=80 web backups proxy
   ```

   Keep CHESS_SESSION_SECRET, CHESS_DOMAIN, DNS and the Caddy volumes. Do not
   overwrite data/league.sqlite3, copy sample databases, or change ownership of
   existing data by copying the entire extracted directory over the deployment.
   The service takes a snapshot before migrating an existing database. If an
   upgrade fails, preserve that database and restore a verified earlier snapshot
   with the service stopped rather than assuming old code understands new data.

3. Verify /health, public teams/results, manager recruiting, and account login.
   Open a PGN game while signed out: it should invite sign-in without providing
   replay data. Sign in and verify replay and PGN download. Confirm Portuguese
   labels and unchanged team/player names. Monitor backups health separately.

## First installation

Copy .env.example to .env, set the domain, and generate a permanent random session
secret of at least 32 characters. Keep the real .env out of Git. DNS must point at
this VM and the firewall must permit public TCP 80/443 and UDP 443. Only Caddy
publishes public ports; never publish the web service's port 8000.

The web and backup processes run as UID 10001. Prepare private writable volumes:

```sh
cd /opt/clubdraft
sudo mkdir -p data backups
sudo chown 10001:10001 data backups
sudo chmod 700 data backups
sudo docker compose config -q
sudo docker compose up -d --build
sudo docker compose exec web python manage.py create-admin --username liga_admin
```

The administrator command prompts for a password without echoing it. Both the
proxy and application count streamed request bytes and cap requests at 8 MiB.
The application additionally enforces photo and PGN limits. A single web worker
continues to use SQLite transactions; do not add workers without coordinating
the settlement scheduler and rate limits.

## Scheduled backups and monitoring

The backups service creates a validated SQLite online snapshot at startup and
every CHESS_BACKUP_INTERVAL seconds (default 86400, one day), keeping 30 local
snapshots. This includes profile photos, PGNs and all committed WAL changes.
Snapshots and backup status have mode 0600. Local snapshots survive an application
rebuild, but not loss of the VM: configure the off-server option below.

A backup error writes backups/status.json with status: error, logs a generic
failure, makes the backup container unhealthy, and retries after five minutes.
Stale success also makes the container unhealthy. Set up external monitoring for
both web readiness and Docker backup health; Docker does not send alerts itself.
Logs and status avoid repository URLs and credentials.

Manual snapshot:

```sh
sudo docker compose exec -T web python -m deploy.backup_sqlite
sudo docker compose exec -T backups python -m deploy.backup_service --healthcheck
```

## Encrypted off-server snapshots (optional setup)

The compose.offsite.yaml override installs a pinned restic binary and uploads
each successful local snapshot to an encrypted remote repository. This is ready
to configure, but it cannot copy off-server until the operator supplies a real
repository and credentials. No repository or credentials are bundled with the
release. Use an S3-compatible bucket outside this VM, preferably with independent
credentials and a bucket lifecycle/immutability policy protecting older snapshots.

1. Set RESTIC_REPOSITORY in .env, for example
   s3:https://s3.example.org/club-backups/liga.
2. Create ignored secrets/restic-password containing a long random repository
   password. Keep an independent password backup: losing it prevents recovery.
   Create secrets/offsite-credentials with AWS_ACCESS_KEY_ID=... and
   AWS_SECRET_ACCESS_KEY=... lines (optional AWS_SESSION_TOKEN and
   AWS_DEFAULT_REGION are supported). Values are read as data, never as a shell
   script. Give only backup credentials the necessary bucket access.
3. Set ownership to UID 10001 and permissions 0400 on both secret files. Compose
   secrets backed by local files keep host file ownership, so this is required
   even when the operator has a different UID. Keep the directory private.
4. Build and initialize the remote repository once, then start the service:

   ```sh
   sudo docker compose -f compose.yaml -f compose.offsite.yaml build backups
   sudo docker compose -f compose.yaml -f compose.offsite.yaml run --rm --no-deps \
     backups python -m deploy.backup_service --initialize-offsite
   sudo docker compose -f compose.yaml -f compose.offsite.yaml up -d --build
   ```

Use both compose files for subsequent deployment commands. An off-server upload
failure retains the validated local snapshot and marks backup health as failed.
Remote snapshots are not automatically deleted; choose a retention policy after
verifying recovery. Periodically check the repository and test actual recovery:

```sh
sudo docker compose -f compose.yaml -f compose.offsite.yaml run --rm --no-deps \
  backups python -m deploy.backup_service --check-offsite
```

This reads a random 10% data subset. For a full repository check, use restic's
check --read-data in an operator-controlled environment with the same credential
files. Recover a remote snapshot with restic in that environment, then restore
the resulting SQLite file using the validated procedure below.

## Restore drills and disaster recovery

Monthly, copy a snapshot into an isolated environment, restore to a fresh path,
and check integrity, counts, login, a historical result and a PGN replay. Keep the
record of the snapshot and checks. A fresh-path drill leaves the live league alone:

```sh
python -m deploy.backup_sqlite --restore /path/to/league-snapshot.sqlite3 \
  --target /path/to/drill/restored.sqlite3
```

The restore command checks SQLite integrity and foreign keys, uses SQLite's backup
API, writes atomically, and refuses an existing target by default. It never opens
a missing source in a mode that silently creates a database.

For production recovery, stop all database users (web and backups), preserve the
current database and any sidecars outside the data folder, and restore:

```sh
sudo docker compose down
# Preserve the old data and resolve any -wal/-shm/-journal files before proceeding.
sudo docker compose run --rm --no-deps web python -m deploy.backup_sqlite \
  --restore /backups/league-VERIFIED-SNAPSHOT.sqlite3 \
  --target /data/league.sqlite3 --overwrite
sudo docker compose up -d
sudo docker compose ps
```

Use both compose files if the off-server profile is enabled. The overwrite flag
is explicit and refuses SQLite sidecars; it cannot prove no other process holds
the database open, so stopping every database user is essential. Validate the
recovered application before resuming writes.

## Reproducible releases and checks

Runtime, development and build requirements have exact transitive pins and
SHA-256 hashes. The Python, Caddy and optional restic images use verified OCI index
digests. To update dependencies, edit the .in inputs, compile all three locks with
uv for Python 3.12, and review the complete change:

```sh
uv pip compile requirements.in --python-version 3.12 --universal --generate-hashes -o requirements.txt --no-header
uv pip compile requirements-dev.in --python-version 3.12 --universal --generate-hashes -o requirements-dev.txt --no-header
uv pip compile requirements-build.in --python-version 3.12 --universal --generate-hashes -o requirements-build.txt --no-header
```

Install build requirements with --require-hashes first, then runtime or dev
requirements with both --require-hashes --no-build-isolation. This prevents
unlocked build dependencies being fetched for the chess source distribution.
Verify replacement image digests against the registry instead of inventing pins.

GitHub Actions runs translation generation checks, the Python suite, browser
checks and a container build. Historical migration and three-season demo fixtures
are generated locally from sanitized data; external databases are not required.
Browser checks are required in CI (RUN_BROWSER_TESTS=1) and fail if Chromium or
Playwright is unavailable.
