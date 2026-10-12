## v72 Seasons navigation and banner

The /seasons navigation item, banner label and browser title now use Seasons. Portuguese navigation and banner labels use Épocas. Assets use v72; database schema remains v32.

## v71 neutral game-list results

Player names, scores and outcome captions in the Games list no longer receive result-based highlighting. Match-board and banner score highlights remain. Assets use v71; database schema remains v32.

## v70 match scores only

Match-board player names use the same neutral styling regardless of result. Only winning/drawing board scores retain their highlights; the winning total in the banner stays highlighted. Assets use v70; database schema remains v32.

## v69 mobile replay header and five move rows

Mobile replay titles and date/round metadata wrap without clipping. The scrolling notation panel reserves five full move rows (White and Black together). Short screens can scroll the page while keeping the board large; desktop keeps its existing layout. Assets use v69; database schema remains v32.

## v68 match banner winner

Completed matches highlight the winning team’s total score in the banner using the neutral grey palette. Home and away wins are supported; draws and unfinished matches have no winner highlight. Assets use v68; database schema remains v32.

## v67 neutral game and match accents

The Games directory and match-board content use black and grey accents for counters, controls, round links, pagination, hover/focus states and result emphasis. Wins remain stronger than draws using different grey backgrounds. Both themes retain readable contrast. Header and banner layouts stay unchanged. Assets use v67; database schema remains v32.

## v66 match history and clean review timestamps

The Games heading is Match history / Histórico de partidas, and only the completed counter remains. Review timestamps omit the city in visible text, hover text and accessibility labels, while retaining the existing local date/time conversion. Assets use v66; database schema remains v32.

## v65 match board result highlights

Winning board scores and their players have green highlights. Drawn scores and both players have a lighter green tint. Highlights follow home/away results even on boards with reversed piece colours; unplayed boards stay neutral. Light and dark modes are supported. Assets use v65; database schema remains v32.

## v64 full English game dates and review timestamps

English list dates include the day (6 September 2026). Review headers display dd-mm-yyyy and local time followed by Lisbon/Lisboa, including localized accessibility labels and hover text. UTC storage and Lisbon daylight-saving conversion are preserved. Assets use v64; database schema remains v32.

## v63 localized game dates and simpler filters

The Games list shows English month/year dates (September, 2026) or Portuguese full dates (6 de setembro de 2026), updating immediately when switching languages. Dates still use the Lisbon calendar day, with full dates available on hover. The Status selector is removed and the remaining filters use the available space. Assets use v63; database schema remains v32.

## v62 game team venues and Portuguese outcomes

Game cards label teams (home)/(away) using the linked team match, including boards with reversed colours. Portuguese uses (casa)/(fora) and Brancas vencem/Pretas vencem. Standalone games show no invented venue designation. Assets use v62; database schema remains v32.

## v61 approved game directory design

The header and page banner retain their existing design. Below them, compact counters and filters precede game cards with date/round, White, centered score and Black columns. Winning names and scores are green with explicit outcome labels. Mobile stacks the players and collapses filters. Cards open games; season/round links open matches. Numbered pagination preserves filters and sorting. Light/dark themes and Portuguese translations are supported. Assets use v61; database schema remains v32.

## v60 streamlined game cards

Game cards open replay across their full area, except the independent season/round link to the league match. Player and team identities align in two columns; separate Replay and View match buttons and displayed timezone text are removed. Times remain converted to Lisbon. Assets use v60; database schema remains v32.

## v59 game teams and match navigation

Game cards show each player’s team at the match and a View match button for linked league games. Replay round labels link to that same match. Standalone games retain their details/replay links without an unrelated match button. Assets use v59; database schema remains v32.

## v58 player search

The Players search matches only names and usernames, with the placeholder “Name or username” and its Portuguese translation. Assets use v58; database schema remains v32.

## v57 standings columns and board scores

Standings omit Captain and label completed team matches Games. League Points precede Board Points. Board Points sum every valid completed individual board result through the selected round, including partial team matches, using 1/½/0. Total-board tie-breaks use that same sum. Assets use v57; database schema remains v32.

## v56 desktop board resize

Drag the bottom-right board handle to resize the desktop replay board. It stays square, annotations remain aligned, and the notation panel stays beside it. Size is saved in this browser and clamped to available width; mobile retains its responsive layout. The handle also supports arrow keys and Home/End. Assets use v56; database schema remains v32.

## v55 cumulative standings by round

Standings default to All rounds. Selecting round N includes completed team matches from rounds 1 through N, including cumulative board points and tie-break results. Teams scheduled for later rounds remain visible with zero points before playing. Season changes reset the round filter; native form submission works without JavaScript. Assets use v55; database schema remains v32.

## v54 clear current replay annotations

A left-click anywhere on the board clears all circles and arrows for the current position, preserving marks on other positions. Assets use v54; database schema remains v32.

## v53 annotation refinements

Replay circles are thinner and sit near the square edges. Arrow shafts end inside their arrowheads, with the tip aligned to the destination square for straight and curved arrows. Assets use v53; database schema remains v32.

## v52 move-specific replay annotations

Desktop mouse users can right-click to toggle green circles and right-drag to toggle directed green arrows. Rank, file and diagonal arrows are straight; other directions curve towards the board centre. Marks are associated with individual replay positions, follow board flips and survive move navigation, piece changes and language changes. They are held only in page memory and cleared on leaving, including browser back/forward-cache restoration. Assets use v52; database schema remains v32.

## v51 home and footer cleanup

Removed the home-page How it works section and the fantasy-league tagline from the shared footer. Assets use v51; database schema remains v32.

## v50 transfer window outline

The home-page Transfer Window has a rounded outline in dark mode, using the same border colour as the other panels and responsive padding. Assets use v50; database schema remains v32.

## v49 appearance previews

Piece choices show the actual king, queen, rook, bishop, knight and pawn alongside every set name, including the selected set. Board palette swatches appear alongside every colour name. Accessible selectors support arrow keys, Home/End, first-letter navigation and native selects when JavaScript is unavailable. Saved preferences and all 43 piece sets remain supported. Assets use v49; database schema remains v32.

## v48 settings button and team labels

The appearance button uses a crisp SVG settings icon with coordinated light/dark colours, green hover/open states and a visible keyboard-focus ring. The signed-in account button has a matching SVG chevron. The Players table, mobile cards and team filter use Team/Equipa. Assets use v48; database schema remains v32.

## v47 focused match and replay layouts

Entire board rows open their game reviews with native keyboard-accessible links. Compact match scoreboards and captain forms fit desktop workspaces; long content scrolls within its panel. Replay tools sit beneath the board, with PGN download beside Replay options. Mobile replays have a single-row header and a full-width board; notation remains independently scrollable. Assets use v47; database schema remains v32.

## v46 match boards and immediate replay controls

Arrow keys navigate a replay immediately when a game opens, while menus and form fields retain their normal keyboard controls. Match pages combine both lineups, player ratings, piece colours and game results in one board-by-board section. Pre-match lineup privacy and captain submissions remain enforced. Assets use v46; database schema remains v32.

## v45 compact replay and appearance

Game pages place player identities and score next to a viewport-sized board, with an independently scrolling notation panel. Piece Set and eight Board palettes are available from the top-right account/appearance menu and persist in this browser. Profile links highlight green; sign out highlights red. Assets use v45; database schema remains v32.

## v44 replay progress

Progress beneath playback controls counts numbered moves and uses moves/lances rather than half-moves. Assets use v44; database schema remains v32.

## v43 replay controls

An accessible flip-board icon sits on the same row as playback controls. Assets use v43; database schema remains v32.

## v42 replay layout

Replay counts numbered moves rather than individual half-moves, including custom starting positions. Flip sits directly below the board; playback controls appear above the notation. Assets use v42; database schema remains v32.

## v41 replay control

The play/pause button shows only its icon, keeping translated accessible labels. Assets use v41; database schema remains v32.

## v40 public replay

Visitors can replay and download PGNs for visible games without signing in. Unpublished matches and pre-match pairings retain their existing visibility restrictions. Assets use v40; database schema remains v32.

## v39 replay piece styles

Login no longer displays a welcome flash. Replay uses all 43 locally bundled piece sets from Lichess lila, with Cardinal as the default. Style selection persists in this browser. Original artwork credits and licensing are retained in static/pieces/ATTRIBUTION.txt and LICENSE, linked from replay. Assets use v39; database schema remains v32.

## v38 compact headers and colour-specific game filters

Menu-page banners reduce blank space while retaining type sizes. The home page removes two feature bullets. Games offers white-player and black-player selectors, applied together and preserved through pagination; options include players in visible games. Assets use v38; database schema remains v32.

## v37 navigation and replay appearance

Menu pages share consistent banner heights, with Results selectors below its banner. Teams no longer shows Captain status; Players no longer shows the club/rating filters or club column. Games removes its fantasy scoring card. White replay pieces use solid silhouettes filled white with black outlines. Assets use v37; database schema remains v32.

## v36 appearance updates

The team directory is titled League teams. Dark headers on Results, the admin dashboard and match pages share the site header palette. Player profile games played appears above wins, draws and losses. Assets use v36; database schema remains v32.

# Liga SX-AAC — Chess Fantasy League V35

FastAPI, Jinja templates, SQLite, and an offline PGN replay viewer for a club fantasy chess league. This release adds account recovery and editable identities, season scheduling, and four-player team matches while preserving existing accounts and league data.

## New in v35

- Results offers **All rounds / a specific round** below the season selector. Changing seasons resets the round filter, and round tiles link directly to filtered fixtures. Fixture headers show **home team vs away team** beside the date/time.
- Standings uses **3 points for a team-match win, 1 for a draw, 0 for a loss** for the selected season, with played/won/drawn/lost and board points. Only published, completed four-board matches with valid historical team attribution and a past kickoff count. Ties use the same head-to-head wins, head-to-head board points, and total board points as season medals; exact ties share a rank. A season dropdown selects past tables. Current teams appear with zero points before play starts.
- Fantasy-point counters, sorting, game-award labels and manual adjustment controls are removed from the interface. Current team/captain totals and team-directory point sorting use current-season league points. Player profiles keep chess records and FIDE ratings. Legacy point columns and accounting history remain in the database for migration compatibility and do not contribute to standings.
- Assets use `v=35`; the database schema remains `v32_shared_fide_ids`.

## New in v34

- The player/captain identity card links to the current team and shows the recorded join date in `DD.MM.YYYY` (Europe/Lisbon). Each tab uses its own current roster/appointment record; unassigned members do not display a previous team as current, and missing historical dates are not invented.
- Results highlights the winning team and score once all four boards are complete. Final draws highlight both teams with a lighter colour; partial results have no winner styling.
- A season schedule replaces the teams/rounds/matches metric strip. Round tiles show dates and link to their fixtures. Completed rounds have lighter backgrounds and explicit status labels. Completion requires every match's four boards to be recorded; unpublished fixture details remain private.
- Season selection navigates immediately without a redundant submit button. Browsers with JavaScript disabled get direct season links.
- The dark stylesheet generator now preserves media-query scope. This fixes mobile menu backgrounds leaking into desktop navigation and mobile table colours leaking into desktop tables. Desktop menu links share the header background; expanded mobile navigation remains opaque.
- Assets use `v=34`; the database schema remains `v32_shared_fide_ids`.

## New in v33

- Public role labels use **Captain / Capitão**, including registration, invitations, role requests and error messages. Stored role identifiers and existing `/manager` links remain compatible; account names and historical records are never rewritten.
- All-season wins, draws, losses and played totals sit compactly inside the member identity card.
- The team directory offers name, fantasy-point and budget sorting; removed sort values fall back to name order.
- Seasonal squads have a season header, avatars, captain badges, score chips and alternating rows, with cards on phones. **Join date / Leave date** replace known-from/until. Leave date is `-` when a term remains open or ends at/after the selected season boundary; departures within the season retain their dates and unknown legacy end dates remain marked unknown.
- Dark mode separates the page canvas, banners, cards and inset controls with stronger surface contrast and visible borders. Text contrast is checked across public, member and admin pages at 320, 390 and 1440 pixels.
- Assets use `v=33`. No new database migration is required; health continues reporting `v32_shared_fide_ids`.

## New in v32

- Multiple accounts may use the same numeric 6–8 digit FIDE ID. Accounts, ratings, game statistics and lock settings stay independent. Recovery email uniqueness remains enforced. Startup applies `v32_shared_fide_ids`, removing only the FIDE uniqueness index while retaining existing profiles and team pictures; a private `.pre-v32.bak` snapshot is created before migration.
- Player profiles display wins, draws, losses and completed games across all seasons, including both piece colours and records beyond the recent eight-game preview. Scheduled games do not count; the pre-match privacy embargo also applies to statistics.
- **Results** replaces **Seasons & rounds** in navigation, titles and manager links. Existing `/seasons` URLs and the season dropdown remain compatible.
- **Squad by season** shows each member's chess score/games played (for example **1.5/2** for a win and a draw). Scores use the team attribution recorded on each game, not current ownership or fantasy points. Season-match IDs remain authoritative if an admin edits season dates; standalone games use season date boundaries.
- A header moon/sun button toggles dark mode across every page, including administration, recovery, profiles, auctions, results and replay controls. It follows the device preference initially and saves an explicit choice locally. The preference loads before styles paint; storage-disabled browsers can still toggle. Text, surfaces, controls, borders, focus rings and result colours receive dark styling; uploaded photos and chess pieces retain their original appearance.
- `static/dark.css` is generated from colour declarations in the main stylesheet by `python tools/build_dark_theme.py`; maintain theme-specific controls and semantic colours in `static/theme.css`. Run the generator after changing main CSS and use `--check` in validation. Assets use `v=32`.

## New in v31

- Team management uses a red person-with-X icon to remove a manager, with a translated accessible label and confirmation. Pending invitations show the invited manager and a **Cancel invitation** action directly in the team table; cancelled invitations cannot be accepted and can be replaced.
- Admin removal ends the appointment and player membership while retaining the active manager role. The removed manager becomes available immediately and can accept a new invitation to the same team. Existing appointment history is retained; voluntary resignation still leaves availability off until the manager enables it.
- Before kickoff, only active players on the current team and its assigned manager can see that team's selected lineup. Opponents, outsiders, anonymous visitors and administrators see a privacy notice and reveal time. Both lineups become public at the scheduled match time.
- Associated board pairings are embargoed until kickoff across match pages, game listings/search/pagination, player profiles, team archives, admin recent games, direct game URLs and PGN downloads. Rescheduling uses the live match time. Standalone scheduled games remain available as before.
- Portuguese/English labels and phone layouts are supported. Assets use `v=31`; no new database migration or past-season regeneration is needed (schema remains `v30_team_photos`).

## New in v30

- Teams have a profile picture. The currently assigned, active manager can upload, replace or remove it on the team's profile. Former managers, other users and administrators cannot override the current manager's picture permissions.
- JPG, PNG and WebP uploads up to 5 MB are validated, cropped to a 512-pixel square and re-encoded as JPEG without metadata. SVG and oversized uploads are rejected. CSRF protection and transactional appointment checks protect changes.
- Pictures appear on team profiles, the team directory, standings, season fixtures and match scoreboards. Teams without pictures retain their existing emblem.
- Images live in SQLite and are covered by existing backups. Startup automatically applies the additive `v30_team_photos` migration; existing accounts, teams, appointments and seasons are preserved. Assets use `v=30`.

## New in v29

- `/admin` is now an overview dashboard with summary cards, six management workspaces, an actionable attention panel, recent games/activity and manager availability. Existing tools live on the dedicated team, role, player/transfer, game, season and account pages. Actions return to their relevant workspace.
- Transfer amounts display **♔** throughout auctions, bids, budgets, standings and historical manager/transfer records. The symbol has an accessible credits label. Amounts and bidding rules remain unchanged; live auction refresh preserves the symbol.
- Player-profile results show **green wins**, **red losses**, and **grey draws/upcoming fixtures**, with explicit labels as well as colour. Outcomes follow the profile's player, including when they played Black, while retaining the recorded game score.
- Portuguese/English translations and mobile layouts cover the new dashboard and result badges. Assets use `v=29`; existing databases remain compatible and require no regeneration.

## New in v28

- Team profiles display gold, silver and bronze podium badges, each engraved with its season year and linked to that season's results. Badges from every qualifying past season remain visible together.
- Placements use **team-match league points**: win 3, draw 1, loss 0. Four board scores determine the match result: 2½–1½ is a win, 2–2 is a draw. These medals are independent of the existing fantasy-point standings.
- Equal league points are resolved by head-to-head match wins, then head-to-head board points, then total season board points. Multi-team ties use a mini-table of all teams tied on league points. Exact remaining ties share their competition rank (1, 1, 3).
- Only published seasons whose end date has passed and whose complete round schedule has all four board results per match qualify. Historical teams come from the recorded games, not current rosters or budgets. Corrections recalculate honours automatically; incomplete or unconfirmed records receive no provisional medals.
- This feature is read-only and requires no database migration or regeneration. Assets use `v=28`; Portuguese/English labels and phone layouts are supported.

## New in v27

- Seasons opens on the current July–June season, even if no schedule has been configured or published. A dropdown selects other seasons without mixing their fixtures; the native submit button works without JavaScript.
- Results are grouped into round cards with team scores, match status, date/time, location and board completion counts. Scores use standard chess board points, not fantasy points.
- Match pages show a team scoreboard, individual white/black board results and submitted lineups. Managers have a dedicated four-player selection panel; recorded games and expired deadlines prevent editing.
- Both layouts support Portuguese and English, keyboard navigation and narrow phones. Assets use `v=27`; the existing database and schema remain compatible.

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

- **Public replay (v40).** Visitors can view and download PGNs for visible games without signing in. Uploading/removing PGNs and recording results remain administrator actions. Pre-match game visibility restrictions remain in effect.
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
