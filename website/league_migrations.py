"""Versioned, transactional upgrades after the historical v1–v23 conversion.

The caller holds an IMMEDIATE transaction with foreign keys disabled, checks all
foreign keys before committing, and creates a consistent pre-upgrade backup.
"""
LEDGER_VERSION = 'v24_reliability_ledger'
ATTRIBUTION_VERSION = 'v24_historical_attribution'
ACCOUNTS_VERSION = 'v25_accounts_seasons'
TEAM_PHOTOS_VERSION = 'v30_team_photos'
SHARED_FIDE_VERSION = 'v32_shared_fide_ids'
SCHEMA_VERSION = 'v103_player_countries'


def apply(db, applied_at):
    _apply_ledger(db, applied_at)
    _apply_attribution(db, applied_at)
    _apply_v25(db, applied_at)
    _apply_team_photos(db, applied_at)
    _apply_shared_fide_ids(db, applied_at)
    _apply_player_countries(db, applied_at)


def _apply_ledger(db, applied_at):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (LEDGER_VERSION,)).fetchone():
        return
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='auctions'").fetchone()[0]
    if "'failed'" not in sql:
        db.execute('''CREATE TABLE auctions_v24 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL REFERENCES players(id),
            seller_team_id INTEGER REFERENCES teams(id),
            starting_price INTEGER NOT NULL CHECK(starting_price > 0),
            ends_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open','closed','failed','cancelled')),
            winner_team_id INTEGER REFERENCES teams(id),
            final_price INTEGER,
            created_at TEXT NOT NULL,
            closed_at TEXT,
            failure_reason TEXT
        )''')
        db.execute('''INSERT INTO auctions_v24
            (id,player_id,seller_team_id,starting_price,ends_at,status,
             winner_team_id,final_price,created_at,closed_at)
            SELECT id,player_id,seller_team_id,starting_price,ends_at,status,
                   winner_team_id,final_price,created_at,closed_at FROM auctions''')
        db.execute('DROP TABLE auctions')
        db.execute('ALTER TABLE auctions_v24 RENAME TO auctions')
        db.execute("CREATE UNIQUE INDEX one_open_auction_per_player ON auctions(player_id) WHERE status='open'")
    db.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        actor_id INTEGER REFERENCES users(id),
        reason TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT,
        created_at TEXT NOT NULL
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS audit_by_entity ON audit_log(entity_type,entity_id,id)')
    db.execute('''CREATE TABLE IF NOT EXISTS points_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL REFERENCES players(id),
        game_id INTEGER REFERENCES games(id),
        source TEXT NOT NULL CHECK(source IN ('legacy_adjustment','manual_adjustment','game_award')),
        amount INTEGER NOT NULL,
        actor_id INTEGER REFERENCES users(id),
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CHECK((source='game_award' AND game_id IS NOT NULL) OR
              (source!='game_award' AND game_id IS NULL))
    )''')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ledger_game_award ON points_ledger(game_id,player_id) WHERE source='game_award'")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ledger_legacy_baseline ON points_ledger(player_id) WHERE source='legacy_adjustment'")
    db.execute('CREATE INDEX IF NOT EXISTS ledger_by_player ON points_ledger(player_id,id)')
    # Separate known game awards from the previous total without changing it.
    for game in db.execute('SELECT id,white_player_id,black_player_id,white_award,black_award FROM games').fetchall():
        for player_id, amount in ((game['white_player_id'], game['white_award']),
                                 (game['black_player_id'], game['black_award'])):
            db.execute('''INSERT INTO points_ledger(player_id,game_id,source,amount,reason,created_at)
                VALUES(?,?,'game_award',?,'Imported recorded game award',?)''',
                (player_id, game['id'], amount, applied_at))
    for player in db.execute('SELECT id,points FROM players').fetchall():
        awards = db.execute('SELECT COALESCE(SUM(amount),0) FROM points_ledger WHERE player_id=?', (player['id'],)).fetchone()[0]
        db.execute('''INSERT INTO points_ledger(player_id,source,amount,reason,created_at)
            VALUES(?,'legacy_adjustment',?,'Preserved pre-upgrade points balance',?)''',
            (player['id'], player['points'] - awards, applied_at))
    db.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)', (LEDGER_VERSION, applied_at))


def _apply_attribution(db, applied_at):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (ATTRIBUTION_VERSION,)).fetchone():
        return
    columns = {column['name'] for column in db.execute('PRAGMA table_info(games)')}
    if 'attribution_confirmed' not in columns:
        db.execute('''ALTER TABLE games ADD COLUMN attribution_confirmed
            INTEGER NOT NULL DEFAULT 0 CHECK(attribution_confirmed IN (0,1))''')
    # Preserve completed legacy game attribution. Unplayed fixtures are only a
    # prediction until their first result is recorded after any intervening move.
    db.execute("""UPDATE games SET attribution_confirmed=1
        WHERE result!='*' OR recorded_at IS NOT NULL OR white_award!=0 OR black_award!=0""")
    db.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)', (ATTRIBUTION_VERSION, applied_at))


def _apply_v25(db, applied_at):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (ACCOUNTS_VERSION,)).fetchone():
        return
    columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
    additions = {'email': 'TEXT', 'name': "TEXT NOT NULL DEFAULT ''", 'country': "TEXT NOT NULL DEFAULT ''",
        'fide_id': 'TEXT', 'fide_id_locked': 'INTEGER NOT NULL DEFAULT 0',
        'account_active': 'INTEGER NOT NULL DEFAULT 1', 'fide_rating': 'INTEGER',
        'fide_rating_month': 'TEXT', 'fide_checked_at': 'TEXT', 'fide_next_attempt': 'TEXT',
        'fide_error': 'TEXT', 'fide_attempts': 'INTEGER NOT NULL DEFAULT 0'}
    for name, declaration in additions.items():
        if name not in columns:
            db.execute(f'ALTER TABLE users ADD COLUMN {name} {declaration}')
    db.execute("UPDATE users SET name=COALESCE((SELECT name FROM players WHERE user_id=users.id),username) WHERE name=''")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email COLLATE NOCASE) WHERE email IS NOT NULL")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_fide_unique ON users(fide_id) WHERE fide_id IS NOT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS auctions_due ON auctions(ends_at) WHERE status='open'")
    statements = [
        """CREATE TABLE IF NOT EXISTS password_resets (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            auth_version INTEGER NOT NULL, email TEXT NOT NULL, expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL, used_at TEXT)""",
        "CREATE INDEX IF NOT EXISTS resets_by_user ON password_resets(user_id)",
        """CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, start_year INTEGER NOT NULL UNIQUE,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, round_count INTEGER NOT NULL CHECK(round_count BETWEEN 1 AND 100),
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')), created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS season_rounds (
            id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(id),
            number INTEGER NOT NULL CHECK(number>0), UNIQUE(season_id,number))""",
        """CREATE TABLE IF NOT EXISTS team_matches (
            id INTEGER PRIMARY KEY, round_id INTEGER NOT NULL REFERENCES season_rounds(id),
            home_team_id INTEGER NOT NULL REFERENCES teams(id), away_team_id INTEGER NOT NULL REFERENCES teams(id),
            scheduled_at TEXT NOT NULL, location TEXT NOT NULL, created_at TEXT NOT NULL,
            CHECK(home_team_id<>away_team_id))""",
        "CREATE INDEX IF NOT EXISTS matches_by_round ON team_matches(round_id)",
        """CREATE TABLE IF NOT EXISTS match_lineups (
            match_id INTEGER NOT NULL REFERENCES team_matches(id), team_id INTEGER NOT NULL REFERENCES teams(id),
            manager_id INTEGER NOT NULL REFERENCES users(id), submitted_at TEXT NOT NULL,
            PRIMARY KEY(match_id,team_id))""",
        """CREATE TABLE IF NOT EXISTS lineup_players (
            match_id INTEGER NOT NULL, team_id INTEGER NOT NULL, board INTEGER NOT NULL CHECK(board BETWEEN 1 AND 4),
            player_id INTEGER NOT NULL REFERENCES players(id),
            PRIMARY KEY(match_id,team_id,board), UNIQUE(match_id,player_id),
            FOREIGN KEY(match_id,team_id) REFERENCES match_lineups(match_id,team_id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS match_games (
            match_id INTEGER NOT NULL REFERENCES team_matches(id), board INTEGER NOT NULL CHECK(board BETWEEN 1 AND 4),
            game_id INTEGER NOT NULL UNIQUE REFERENCES games(id), PRIMARY KEY(match_id,board))""",
    ]
    for statement in statements:
        db.execute(statement)
    # Managers eligible to play are discoverable even before a team appointment.
    for user in db.execute("SELECT * FROM users WHERE manager_active=1 AND player_active=1 AND role!='admin'").fetchall():
        if not db.execute('SELECT 1 FROM players WHERE user_id=?', (user['id'],)).fetchone():
            db.execute("INSERT INTO players(name,user_id,is_manager_player,created_at) VALUES(?,?,1,?)",
                       (user['name'],user['id'],applied_at))
    db.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)', (ACCOUNTS_VERSION,applied_at))


def _apply_team_photos(db, applied_at):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (TEAM_PHOTOS_VERSION,)).fetchone():
        return
    db.execute('''CREATE TABLE team_photos (
        team_id INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
        photo_data BLOB NOT NULL, updated_at TEXT NOT NULL)''')
    db.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)', (TEAM_PHOTOS_VERSION,applied_at))


def _apply_shared_fide_ids(db, applied_at):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (SHARED_FIDE_VERSION,)).fetchone():
        return
    db.execute('DROP INDEX IF EXISTS users_fide_unique')
    db.execute('CREATE INDEX IF NOT EXISTS users_fide_lookup ON users(fide_id) WHERE fide_id IS NOT NULL')
    db.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)', (SHARED_FIDE_VERSION,applied_at))


def _apply_player_countries(db, applied_at):
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (SCHEMA_VERSION,)).fetchone():
        return
    fields = {row[1] for row in db.execute('PRAGMA table_info(players)')}
    if 'country' not in fields:
        db.execute("ALTER TABLE players ADD COLUMN country TEXT NOT NULL DEFAULT ''")
    db.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)', (SCHEMA_VERSION,applied_at))
