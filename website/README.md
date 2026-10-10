# Liga SX-AAC — Chess Fantasy League V26

FastAPI, Jinja templates, SQLite, and an offline PGN replay viewer for a club fantasy chess league. This release adds account recovery and editable identities, season scheduling, and four-player team matches while preserving existing accounts and league data.

## New in v26

- Recovery requires the matching username and email, with a redesigned page and integrated return link. Correct credentials for a deactivated account show administrator reactivation instructions. The registration submit button renders Criar conta by default and assets use v=26.
- `demo/generate_past_seasons.py` privately copies the existing database and adds generated 2024-2025 and 2025-2026 double round-robin seasons. `deploy/install_past_seasons.sh` stops database users, backs up, generates, validates and restores the copy. See HOSTING.md before running it.

## New in v25

- Registration requires a unique, valid email address; no verification code is sent. Existing members add their recovery email in Account Settings. Recovery requires both the username and matching email. SMTP sends one-hour, single-use reset links. Recovery responses do not disclose account existence; tokens are stored hashed and travel in URL fragments to keep them out of access logs.
- Account Settings edits Name, Country, and a 6–8 digit ASCII FIDE ID. Administrators can edit identities and lock/unlock FIDE IDs. Account edits keep linked player names consistent. FIDE IDs are unique per account.
- The FIDE Rating worker fetches only the configured standard-rating field, retries failures with persisted backoff, checks the first and second of each month in Europe/Lisbon, and retries stale publication months. Without publication metadata it checks through day seven. The documented public `/api/player/{fide_id}/current` endpoint and standard-rating/publication-month fields are built in; documentation and a live response were verified. No API key is required for this endpoint.
- Active managers appear in the player directory before team appointment. Administration calls profile creation **Activate a player** and offers a dropdown for teams, role requests, players/transfers, games/results, seasons, and accounts.
- Seasons are named YYYY–YYYY+1. Administrators edit dates and round count, choose all team pairings, and set match date/time/location. A complete schedule must have the same participating teams playing once per round before publication. Edits return it to draft for review; used rounds cannot be silently deleted.
- Managers submit exactly four distinct active team players in board order before the match starts. Both submissions generate four chess games with alternating colors. Managers can revise unplayed lineups before the deadline; recorded results/PGNs lock them. A match with recorded games cannot be rescheduled.
- Members can deactivate their account with their password; administrators can deactivate/reactivate members. Only administrators reactivate accounts, and the last active administrator is protected. Deactivation revokes sessions, cancels pending invitations/role requests, quarantines open player auctions, and ends manager appointments while retaining history. Reactivation does not silently restore an old team appointment.
- Registration now says **Criar conta** in Portuguese. New account and season workflows are translated.
- New usernames use ASCII `[A-Za-z0-9_-]` in both registration and administrator CLI. Existing usernames are preserved for a safe migration. SQLite uses WAL; pages and polling skip the writer transaction when no auctions are due. Only the configured proxy IP is trusted for forwarded headers. Logout increments the authentication version and revokes all sessions, including copied cookies.

## What changed

- **Replay requires login.** Fixtures and results remain public. Signed-in members can view a PGN replay and download its PGN. Anonymous responses contain no PGN text, move data, or FEN positions; the login link returns to the selected match. Uploading/removing PGNs and recording results remain administrator actions. Session-dependent responses are private and not cached.
- **Recoverable auctions.** Manager appointments cannot conflict with active player auctions. Broken legacy auctions are isolated with a failure reason, allowing other auctions, bids, pages, and startup to continue. Administrators can cancel or retry with an audited reason. Recovery preserves bids and checks outstanding credit reservations.
- **Audited scoring.** Administrators enter signed point adjustments rather than overwrite totals. An adjustment ledger and reversible game awards determine the total. Existing totals are preserved during migration. Result, PGN, adjustment, and auction-recovery changes record their actor and reason.
- **Historical attribution.** Dated membership determines the team represented at a match. Future fixture attribution is confirmed when the first final result is recorded, then retained through corrections. Missing legacy history never substitutes today's owner.
- **Safer requests and responsive bidding.** Actual received bodies are limited to 8 MiB, including streamed requests without Content-Length, before multipart parsing. Upload fields are restricted and closed. Blocking transactions, password hashing, and photo normalization run in a bounded thread pool.
- **Clear member actions.** Manager pages provide Recruit players and available/committed credits. Home links to all auctions. Auction state refreshes every 30 seconds and when returning to the app, preserving unfinished bids.
- **Complete game browsing.** Pagination includes matching counts, preserved filters, and upcoming/newest ordering. Times display in Europe/Lisbon with a zone; storage stays UTC. Scheduling fields explicitly accept UTC.
- **Portuguese and accessibility.** Sentence keys preserve member/team/event identities. Improved contrast, keyboard menus, mobile table cards, touch targets, and session recovery retain the visual identity. Replay adds a semantic board, position description, flipping, coordinates, speeds, keyboard controls, and correct custom-FEN move numbering.
- **Independent roles.** Quitting a role never activates another role. Members with neither role can sign in and request administrator approval to reactivate one.
- **Operations.** Readiness validates the real database and migration version; missing databases are never recreated during ordinary traffic. `/health/live` checks liveness. Failed/overdue auctions are reported separately. Daily online backups include integrity checks, status monitoring, safe restore, and optional encrypted off-server copies.
- **Reproducible releases.** Runtime, development, and build dependencies are hash-locked; images are digest-pinned. CI runs regression, historical-migration, and Chromium tests and verifies generated translations.

## Local development

Use Python 3.12. From this directory:

```bash
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-build.txt
.venv/bin/python -m pip install --require-hashes --no-build-isolation -r requirements-dev.txt
.venv/bin/python manage.py init
.venv/bin/python manage.py create-admin --username liga_admin
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Administrator creation prompts privately for a 12–256 character password. Existing passwords remain usable. Set a permanent random CHESS_SESSION_SECRET for persistent login sessions. On Windows use `.venv\Scripts\python.exe` instead of `.venv/bin/python`.

CHESS_DB_PATH can point to a development database outside the source tree. Demo generators create fictional data only; they are not production imports.

## Tests

```bash
.venv/bin/python -m playwright install chromium
.venv/bin/python tools/build_i18n.py --check
RUN_BROWSER_TESTS=1 PYTHONPATH=. .venv/bin/python -m pytest -q
```

On Linux CI, `python -m playwright install --with-deps chromium` also installs system dependencies. Browser tests use Playwright Chromium or installed Chromium; LIGA_CHROMIUM_PATH can select an executable. With RUN_BROWSER_TESTS=1, missing Chromium fails rather than silently skipping. On Windows set these environment variables before running pytest.

Historical schemas are generated from sanitized frozen fixtures, so migration tests need no external databases. The invalid-PGN fixture now uses an actually illegal move.

## Production and upgrading

See [HOSTING.md](HOSTING.md) for installation, safe upgrades, backup monitoring, encrypted off-server configuration, restoration drills, and dependency updates.

**V24 includes database migrations.** It extends auction states, creates scoring/audit ledgers, and records confirmed historical attribution. Initialization takes a private consistent pre-upgrade snapshot and checks foreign keys before committing. Verify an off-server backup before deployment; preserve `.env`, `data/`, `backups/`, ignored secret files, and Caddy volumes. Deploy source files, not demonstration databases. New steps are versioned in league_migrations.py.

Default Compose schedules daily local snapshots. Encrypted off-server copies require your own repository and credentials configured with the optional profile in HOSTING.md. Credentials are not included; monitor backup health externally.

## Source organization

- main.py: routes, session/permission checks, template contexts.
- web_security.py: received-body limits, bounded forms, safe return URLs, browser recovery.
- web_queries.py: synchronous account/query operations dispatched as whole thread-pool jobs.
- database.py: persistence, account/team/profile management, compatible domain facade.
- league_auctions.py: reservations, atomic settlement, recovery.
- league_scoring.py: games, dated attribution, scoring ledger, corrections.
- league_migrations.py: incremental versioned migrations.
- static/pt-PT.json: editable catalogue; tools/build_i18n.py generates JS/TSV and detects drift.
- deploy/: HTTPS proxy, health checks, startup, backups, restore, encrypted backup support.

The integrated Liga repository runs .github/workflows/website.yml with website/ as its working directory. The standalone source ZIP includes the corresponding root-level workflow.
