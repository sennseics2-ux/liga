# Liga SX-AAC — deployment and recovery

The web application, HTTPS proxy and scheduled SQLite snapshots run with Docker
Compose. The existing domain, accounts and data remain compatible. PGN replay
and downloads are public for visible games.

## Club landing page at www.sx-aac.com

The v122 release includes a static Portuguese landing page in `landing/`. Its
League button opens `https://liga.sx-aac.com/`. Caddy serves the landing page at
`www.sx-aac.com` and redirects `sx-aac.com` to the www address, while retaining
the existing League configuration.

Before deploying, set the A records for `www.sx-aac.com` and `sx-aac.com` to the
VM's public IPv4 address in your DNS provider. Set AAAA records only if the VM
also has working public IPv6; remove any stale records pointing elsewhere.
Ports 80 and 443 must be reachable, as they already are for the League.
If these domains currently serve a different site, this changes their destination.

Deploy the release using the upgrade commands below. The proxy needs
`docker compose up -d --build --force-recreate` so it receives the new read-only
landing directory mount. Caddy obtains and renews HTTPS certificates automatically
once DNS resolves to this VM. No additional `.env` settings are required.

Verify after deployment:

```sh
curl -I https://www.sx-aac.com/
curl -I https://sx-aac.com/
curl -I https://liga.sx-aac.com/
sudo docker compose logs --tail=80 proxy
```

The www page should return 200; the bare domain should redirect to www; the
League should retain its existing behavior. Allow time for DNS changes to
propagate. If HTTPS is not ready, inspect the proxy logs for DNS or certificate
errors. The static files can also be uploaded unchanged to another static host
instead of using the shared VM.

For later changes affecting only the landing page, copy just the release's
`landing/` directory into `/opt/clubdraft/landing/`. The existing Caddy directory
mount serves the changed files immediately; the League does not need to stop or
rebuild. The v122 landing page is centered, monochrome and has no chessboard.

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
     ~/chess-fantasy-league-v122/ /opt/clubdraft/
   sudo mkdir -p data backups
   sudo chown -R 10001:10001 data backups
   sudo chmod 700 data backups
   sudo docker compose config -q
   sudo docker compose up -d --build --force-recreate
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
   Open a PGN game while signed out and verify replay and PGN download. Confirm Portuguese
   labels and unchanged team/player names. Monitor backups health separately.

## V35 release extraction and configuration

The standalone release ZIP has `chess-fantasy-league-v122/` at its root. GitHub's
Download ZIP instead contains `liga-main/website/` (or `liga-COMMIT/website/`
for a commit archive). Copy the directory containing
`main.py`, `compose.yaml`, and `league_migrations.py`; copying `liga-main/` directly
will put the application at the wrong nesting level and leave the old site running.

Use a fresh extraction directory, validate it before downtime, and stop on errors:

```bash
(
  set -e
  ZIP="$HOME/chess-fantasy-league-v122.zip"
  RELEASE_DIR="$(mktemp -d "$HOME/liga-v122-release.XXXXXX")"
  unzip -q "$ZIP" -d "$RELEASE_DIR"
  SOURCE_DIR="$RELEASE_DIR/chess-fantasy-league-v122"
  if [ ! -f "$SOURCE_DIR/main.py" ]; then
    for CANDIDATE in "$RELEASE_DIR"/liga-*/website; do
      if [ -f "$CANDIDATE/main.py" ]; then
        SOURCE_DIR="$CANDIDATE"
      fi
    done
  fi
  test -f "$SOURCE_DIR/main.py"
  test -f "$SOURCE_DIR/compose.yaml"
  test -f "$SOURCE_DIR/deploy/install_past_seasons.sh"
  grep -q 'v108_unregistered_player_fide' "$SOURCE_DIR/league_migrations.py"

  cd /opt/clubdraft
  sudo docker compose exec -T web python -m deploy.backup_sqlite
  sudo docker compose down
  sudo rsync -a \
    --exclude='/.env' --exclude='/data/' --exclude='/backups/' \
    --exclude='/secrets/' --exclude='/.venv/' --exclude='/__pycache__/' \
    "$SOURCE_DIR/" /opt/clubdraft/
  sudo mkdir -p data backups
  sudo chown -R 10001:10001 data backups
  sudo chmod 700 data backups
  sudo docker compose config -q
  sudo docker compose up -d --build --force-recreate
  sudo docker compose ps
  sudo docker compose logs --tail=80 web backups proxy
)
```

If encrypted offsite backups are enabled, use both compose files in every compose
command as described below. Preserve `.env` and `secrets/`. Application startup
creates a consistent snapshot before migrating. The additional `.pre-v108.bak`
snapshot preserves the pre-migration database; keep a copy off the VM.

After web is healthy, `/health` must report `"schema":"v108_unregistered_player_fide"`, and
the homepage assets must use `v=108`. A browser hard refresh may be necessary.
Open `/seasons`: it defaults to the current July–June season (2026-2027 in October
2026), including before its schedule is published. Use the season dropdown to
view 2024-2025 and 2025-2026; their results no longer appear on the initial page.
Check a completed match for its team score and four board results. Open a team
profile and check its season medals. These use team-match league points (3/1/0),
the same scoring and tiebreaks as the season Standings page. Concluded, fully recorded published seasons
qualify automatically. Sign in as an administrator and open `/admin` for the new
management dashboard; its cards link to dedicated workspaces. Confirm transfer
amounts use ♔ and player-profile results are green for wins, red for losses, and
grey for draws/upcoming fixtures. Toggle the header moon/sun button and navigate
between public and account pages: the theme choice should persist. Confirm the
Results label, all-season player win/draw/loss totals, and the selected team's
seasonal score/games-played column (a win and draw show `1.5/2`). Accounts can
now share a FIDE ID; existing per-account FIDE locks and email uniqueness remain.
This upgrade does not regenerate or replace the database; do not rerun the historical installer
if those seasons are already present.

### SMTP password recovery

Edit the existing private configuration with `sudoedit /opt/clubdraft/.env`.
Keep existing CHESS_DOMAIN and CHESS_SESSION_SECRET. Add your provider's settings:

```dotenv
CHESS_SMTP_HOST=smtp.YOUR-PROVIDER.example
CHESS_SMTP_PORT=587
CHESS_SMTP_SECURITY=starttls
CHESS_SMTP_USER=YOUR-SMTP-USERNAME
CHESS_SMTP_PASSWORD=YOUR-PRIVATE-SMTP-PASSWORD
CHESS_SMTP_FROM=liga@YOUR-DOMAIN.example
```

Use the provider's verified sender address. For implicit TLS use security `ssl`
and port 465. Set credentials privately on the VM, never in GitHub or chat. Compose
sets CHESS_PUBLIC_URL from the existing domain. New registrations do not send a
verification code. Existing accounts without emails must add one in Account
Settings, confirming their current password. Recovery is intentionally generic;
a deactivated account cannot recover access without administrator reactivation.

After updating `.env`, run `sudo docker compose up -d --force-recreate web` to apply
it (use both compose files if offsite backups are enabled). Test recovery using the username and an
email you control. Check SMTP delivery and reset the password through the received
link. The link expires after one hour; using it or changing the password revokes
all sessions. Logout also revokes every session for that account.

### FIDE standard ratings

The default lookup uses the documented public endpoint
`https://fideratings.com/api/player/{fide_id}/current`. The standard rating is
`current.standard.rating`; its publication month is `current.standard.date`.
Rapid and blitz ratings are ignored. Documentation and a live player response
were verified during this release. No API key is required for this endpoint.
Existing installations get these defaults automatically without adding variables.

Optional overrides in `.env` (normally unnecessary):

```dotenv
CHESS_FIDE_API_URL_TEMPLATE=https://fideratings.com/api/player/{fide_id}/current
CHESS_FIDE_RATING_FIELD=current.standard.rating
CHESS_FIDE_MONTH_FIELD=current.standard.date
CHESS_FIDE_API_KEY=
CHESS_FIDE_API_KEY_HEADER=X-Fideratings-Key
```

Only the requested fideratings.com HTTPS host is accepted. JSON paths use dot
notation. Historical players with `current_source=last_known_profile` retain their
last-known standard rating and follow the normal monthly schedule. Players with
no standard rating display no FIDE Rating. The regular worker checks up to ten due users
per minute; edited IDs also wake it, and results are saved locally. Large integrations should arrange a
trusted batch API key with the provider before increasing this rate. Private
keys must stay out of source control.

New/edited IDs trigger the worker; due work is also checked every minute. Failed
lookups retain the previous rating and retry after 5 minutes, with backoff capped
at 6 hours. The next-month lookup runs on the first day, with another check on the
second. Stale publication months retry every 6 hours. Without publication metadata
the worker checks daily through day seven. Scheduling uses Europe/Lisbon and
persists in SQLite, so a restart catches up missed work. Changing a FIDE ID clears
its old rating; an outstanding response for the previous ID is discarded. A locked
ID may still receive automatic rating updates.

### Season and account administration

Use the admin dropdown to open Season setup. Create YYYY–YYYY+1, choose dates and
round count, and schedule every round's team pairings with location and UTC input
time (public times display in Europe/Lisbon). Publication checks that every
participating team plays once per round. Season/date edits return the schedule to
draft; republish it after checking. Used rounds cannot be silently removed.

Managers open Results and select their match. Each submits exactly four
active roster players in board order before kickoff. Both lineups create four
board games; colors alternate with the home team white on boards 1 and 3. Managers
can revise before kickoff until a result or PGN is recorded. Administrators enter
results/PGNs on the generated games. Missing lineups are shown explicitly and do
not invent forfeits or results.

Member accounts lets administrators edit Name/Country/FIDE ID, lock IDs, deactivate
accounts, and reactivate them. Deactivation retains historical records and player
ownership, revokes sessions, ends manager appointments, cancels pending role
requests/invitations, and quarantines that player's active auctions. Reactivation
does not restore a previous manager appointment automatically. The last active
administrator cannot deactivate; create another administrator through the CLI
first if an administrator account must be retired.

### Trusted proxy network

V25 assigns Caddy the private IP 172.30.0.10 in subnet 172.30.0.0/24 and trusts only
that address for forwarded client headers. Standalone startup trusts loopback
only. If the subnet conflicts with another Docker network, choose an unused
private subnet and an address within it through CHESS_NETWORK_SUBNET and
CHESS_PROXY_IP in `.env`, then recreate the compose network. Never publish port
8000 or configure a wildcard trusted-proxy address. `docker compose config -q`
checks syntax without displaying your SMTP credentials.

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

## Generate and install the two past seasons

Install V35 application files first using the upgrade commands above. Keep the
existing `.env`, accounts, and data. Startup applies the additive
`v32_shared_fide_ids` migration and assets use `v=35`. Team pictures live in SQLite,
so existing database backups include them. Do not run this generator as part
of an ordinary application upgrade.

The generator uses your **private current VM database**, not a downloadable
fictional replacement. It preserves account IDs, password hashes, recovery emails,
profile settings, current ownership, current manager appointments, budgets,
auctions and existing scoring adjustments. Generated results add their normal
awards to cumulative fantasy points. Historical lineups use existing players
regardless of current team assignment. Current ownership remains unchanged.
The installer adds explicitly named historical guests only if fewer than sixteen
chess profiles exist; guests have no login accounts or current team assignments.

It adds 2024-2025 and 2025-2026, each September 1–June 30, with six completed rounds.
Every team meets each other team twice, once home and once away. There are 12 team
matches and 48 board games per season (96 games altogether), submitted four-player
lineups, managers playing, historical roster/manager terms, scored results and
legal sample PGNs. All selected players rotate through games in both past seasons.
No current-season matches, games or lineups are generated. Existing current/future
games or matches cause a safe failure rather than being silently deleted. Games, PGNs and audit records explicitly identify the history as
**generated demonstration data, not actual past results or actual game moves**.

Requirements: exactly four teams and at least four existing manager accounts.
Historical managers are selected independently from those accounts; current
manager assignment, activation, invitation and acceptance are not prerequisites.
Missing manager chess profiles are added only in the copied database, without
current ownership. Historical manager appointments are closed at season end. Current teams may have empty player rosters; they do not need 4–24 current
players. Separate historical assignments fill the past-season lineups. More than
96 existing players cannot all play across six rounds per season. Existing past
seasons/games or conflicting dated appointments cause a safe failure. A repeat
attempt refuses duplicate seasons. The installer rebuilds the web image before
stopping services so it uses the updated Python generator. It opts into
`--allow-historical-guests`; omit this flag when running the generator directly
if you want existing players only.

Copy a consistent recent backup off the VM before starting. Then run:

```bash
cd /opt/clubdraft
bash deploy/install_past_seasons.sh
```

For an existing offsite-backup deployment, use:

```bash
cd /opt/clubdraft
CHESS_USE_OFFSITE_COMPOSE=1 bash deploy/install_past_seasons.sh
```

The script stops all Compose services, creates an offline consistent original
snapshot, generates a separate copy, checks its integrity and foreign keys,
checkpoints any remaining WAL, and atomically restores the prepared database.
It restarts services on success or failure. The original backup and prepared copy
are retained in `backups/past-seasons-TIMESTAMP/`; the exact location is printed.
The generated database contains private account data. Keep it on the VM and
never add it to GitHub or send it publicly.

Verify the homepage, login and recovery, `/seasons`, both past-season filters on
`/games`, and each team's seasonal roster, manager and game archives. Signed-out
visitors can replay and download PGNs for visible games. Check:

```bash
sudo docker compose ps
sudo docker compose logs --tail=80 web backups
curl -fsS https://liga.sx-aac.com/health
```

To generate a copy without installing it (no application data is changed):

```bash
sudo docker compose exec -T web python demo/generate_past_seasons.py \
  --source /data/league.sqlite3 \
  --output /backups/review-past-seasons.sqlite3
```

This is an online consistent snapshot, useful for reviewing the report. Do not
later deploy an old review copy after new sign-ups or other database changes;
the installer generates a fresh copy while all writers are stopped.

### Roll back the generated history

Use the original snapshot from the directory printed by the installer. Replace
`PASTE-TIMESTAMP` and `PASTE-ORIGINAL-FILENAME` with those actual values:

```bash
cd /opt/clubdraft
sudo docker compose down
sudo docker compose run --rm --no-deps -T --entrypoint python web \
  -m deploy.backup_sqlite \
  --restore /backups/past-seasons-PASTE-TIMESTAMP/original/PASTE-ORIGINAL-FILENAME.sqlite3 \
  --target /data/league.sqlite3 --overwrite
sudo docker compose up -d
```

Restore only with all database users stopped. A restore refuses SQLite sidecars;
if reported, checkpoint the stopped database using the command in
`deploy/install_past_seasons.sh` before retrying. A full rollback also removes
any sign-ups or edits made after the original snapshot. Use both Compose files
in each command when offsite backups are enabled.

## Reset the live league, keeping the existing admin

After installing this release, run on the hosting VM:

```bash
cd /opt/clubdraft
sudo bash deploy/reset_database.sh --keep-admin-only
```

This removes every non-admin account and all teams, players, seasons, matches,
games, transfers and other league records. It preserves the selected admin's
username, password hash, email and profile details, plus the installed `.env`,
SMTP settings and backups. Log in again afterward. The user-ID sequence is kept
above old account IDs so old session cookies cannot belong to new accounts.

The script builds the new image, stops database users, backs up the original to
`backups/reset-<timestamp>-<pid>/original/`, prepares and validates a fresh database,
checkpoints SQLite and installs the prepared copy atomically before restarting.
A preparation failure leaves the original database in place and restarts services.
The prepared copy is retained beside the backup. No sample data is generated.

If there is more than one admin, the script stops without replacing the database.
Choose the single admin to retain explicitly:

```bash
sudo bash deploy/reset_database.sh --keep-admin-only ADMIN_USERNAME
```

For installations using encrypted offsite backups, preserve the compose profile:

```bash
sudo env CHESS_USE_OFFSITE_COMPOSE=1 bash deploy/reset_database.sh --keep-admin-only
```

## Import the requested AA Coimbra players

After installing and rebuilding v122, run inside the live web container:

```bash
cd /opt/clubdraft
sudo docker compose exec -T web python -m deploy.import_fpx_players
```

The importer backs up the current database, then atomically adds the 128 entries
from pages 40–43 of the FPX Filiados 2025–2026 list, from MORAIS, MÁRIO MARTINS
FREITAS to SERRADELL VILLA, ANDREA inclusive. It creates no user accounts or team
assignments. Club is AA Coimbra; country remains unknown until entered by an
administrator. FIDE 0 becomes SQL NULL; all other IDs retain their full digits,
including nine-digit IDs. The source CSV and provenance are in `data_imports/`.

Expect `Players added: 128. Already imported: 0. Login accounts created: 0.` on
the first run. Reruns use FPX record identifiers and skip previous imports; they
never merge unrelated players by name or FIDE ID. Existing accounts and league
records remain intact. Do not run the database reset after importing players.

The standard-rating worker also processes unregistered players with FIDE IDs,
using the existing retry and monthly refresh schedule. Newly imported ratings
start blank and fill asynchronously when the configured provider responds. No
rating or nationality is inferred from the PDF.

## Refresh all FIDE ratings immediately

After deploying and rebuilding v122, run:

```bash
cd /opt/clubdraft
sudo docker compose exec -T web python -m deploy.refresh_fide_ratings
```

The command creates a consistent backup under `/backups/fide-refresh-<timestamp>/`
before changing ratings. It looks up every distinct FIDE ID using the configured
FIDE API and applies the standard rating and federation country to every matching record, including
unregistered players and inactive accounts. Registered profiles use the account's
FIDE ID and update the linked player rating as well. Players with no FIDE ID are
skipped. Existing accounts, teams, games and scores are preserved.

This explicitly refreshes the entire roster even if its next monthly refresh or
retry is not yet due. Each lookup is outside the SQLite write transaction and
shared IDs are fetched once per run. Public API calls are spaced at least one
second apart, retrying short HTTP 429 rate limits up to twice. Allow a few minutes
for a full roster. The command prints individual outcomes and an
`Updated / Failed / Changed/skipped` summary. Updated includes confirmed
unrated players, shown separately as `unrated`; their rating is cleared rather
than invented. A failed lookup preserves its previous rating and country and schedules a
retry. A profile changed during lookup is skipped. Failures or changed/skipped
records cause a nonzero exit status; rerun the command after resolving the issue.
The background monthly refresh continues normally afterward.

As of v110, each distinct FIDE ID uses the `/current` rating endpoint and the
`/profile` federation endpoint. No `.env` changes are required. `federation_code`
(or the provider's country/federation code field) is converted from FIDE's
three-letter codes to the site's country names, so existing profile flags work:
for example POR → Portugal and GER → Germany. FIDE/IOC codes are mapped explicitly
where they differ from ISO codes, including NGR → Nigeria and NIG → Niger.
England, Scotland and Wales use the United Kingdom country choice. Kosovo is
included as a country choice with its flag.

The refresh replaces manually entered countries when the provider supplies a
recognized federation; this field therefore follows FIDE representation.
Unknown/missing codes or a provider profile returning 404 now trigger an official
FIDE profile lookup. Recognized official federation countries are used; genuinely
unresolved or neutral affiliations preserve the existing country. Other profile lookup failures preserve both fields
and schedule a retry. Country updates apply to registered accounts and their
linked player records, unregistered players, and forced inactive-account refreshes.
The monthly worker repeats the same country lookup automatically. Shared IDs use
one pair of lookups per run, and every HTTP request is paced. Allow a few minutes
for the full roster; per-record output includes the country or `country unchanged`.

## Fill only missing countries

After deploying v122, run this country-only command:

```bash
cd /opt/clubdraft
sudo docker compose exec -T web python -m deploy.fill_missing_countries
```

A consistent backup is created under `/backups/missing-countries-<timestamp>/`
before the first update. Only blank, NULL or whitespace-only country fields with
a FIDE ID are candidates. Registered accounts (including inactive accounts) and
player records are checked independently. Linked player records use the account's
FIDE ID. Existing countries on either record are preserved; an already-filled
account country does not prevent filling its blank player record, and vice versa.

The script requests only the federation profile, caches shared FIDE IDs, and uses
the same federation mapping, pacing and short HTTP 429 retries as the combined
refresh. It updates only `country`: ratings, publication months, rating-check
and retry schedules, accounts, teams and match results remain unchanged. Unknown
or neutral codes and missing provider profiles trigger the official FIDE fallback. Network/provider
failures are reported without changing data; rerun this command to retry.
Concurrent country, FIDE ID or account-link changes are skipped. A summary reports
countries filled, unknown federations, failures and changed/skipped records.
The country-only command is safe to rerun and does not change the normal combined
refresh command or monthly worker's behavior.

### Official FIDE fallback in v112

Missing secondary-provider profiles (HTTP 404) and unrecognized federation codes
are looked up at `https://ratings.fide.com/profile/<FIDE-ID>`. This recovers
countries for unrated players missing from the provider registry: for example,
555014356 is officially registered with Egypt. The displayed FIDE ID must match
the requested ID before the federation is accepted. Only country data is saved;
the country-only command still leaves existing countries and all ratings intact.
No API key is sent to the official website, and both sources use HTTPS with
provider-specific redirect checks and request pacing. Allow `ratings.fide.com`
in any VM outbound firewall that restricts destinations.

If the official profile itself has no recognized country, the script reports
that the record needs review and exits with a nonzero status, so it cannot be
mistaken for a completed update. Network failures are also reported. Players
without a FIDE ID need an ID or a country entered before their country can be
resolved; the script does not guess from names or team membership.

## Administrator inline player names in v113

Deploy using the normal source upgrade and rebuild. No database migration or
additional database command is needed. On `/admin/players`, click the pencil next
to a player's name, enter the name, and click the floppy disk to save. Enter also
saves; Escape restores the original name without saving. Names link to their
profiles when the editor is closed. Editing a linked player updates the account's
display name as well, keeping its username, login credentials, profile URL, FIDE
ID, country and ratings intact. Server-side validation requires 2–80 characters
and an administrator session with CSRF. Concurrent name changes are rejected
rather than overwritten. Player-name updates are recorded in the audit log.

## Administrator inline team names in v114

Deploy with the normal source upgrade and rebuild; no migration or separate
database command is required. On `/admin/teams`, click the pencil next to a team,
edit its name and click the floppy disk. Enter saves; Escape cancels the draft.
Names continue linking to team profiles when closed. Team names require 3–45
characters and must remain unique, ignoring ASCII case as in team creation.
The save updates only the name, preserving team IDs, profile URLs, captains,
rosters, budgets, photos and results. Admin authorization, CSRF and stale-name
checks protect the update, which is recorded in the audit log.
