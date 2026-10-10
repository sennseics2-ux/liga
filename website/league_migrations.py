"""Versioned, transactional upgrades after the historical v1–v23 conversion.

The caller holds an IMMEDIATE transaction with foreign keys disabled, checks all
foreign keys before committing, and creates a consistent pre-upgrade backup.
"""
LEDGER_VERSION = 'v24_reliability_ledger'
SCHEMA_VERSION = 'v24_historical_attribution'


def apply(db, applied_at):
    _apply_ledger(db, applied_at)
    _apply_attribution(db, applied_at)


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
    if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (SCHEMA_VERSION,)).fetchone():
        return
    columns = {column['name'] for column in db.execute('PRAGMA table_info(games)')}
    if 'attribution_confirmed' not in columns:
        db.execute('''ALTER TABLE games ADD COLUMN attribution_confirmed
            INTEGER NOT NULL DEFAULT 0 CHECK(attribution_confirmed IN (0,1))''')
    # Preserve completed legacy game attribution. Unplayed fixtures are only a
    # prediction until their first result is recorded after any intervening move.
    db.execute("""UPDATE games SET attribution_confirmed=1
        WHERE result!='*' OR recorded_at IS NOT NULL OR white_award!=0 OR black_award!=0""")
    db.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)', (SCHEMA_VERSION, applied_at))
