-- Fictional v24 account and league schema for migration regression.
BEGIN TRANSACTION;
CREATE TABLE auctions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    seller_team_id INTEGER REFERENCES teams(id),
    starting_price INTEGER NOT NULL CHECK(starting_price > 0),
    ends_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed','failed','cancelled')),
    winner_team_id INTEGER REFERENCES teams(id),
    final_price INTEGER,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    failure_reason TEXT
);
CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        actor_id INTEGER REFERENCES users(id),
        reason TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT,
        created_at TEXT NOT NULL
    );
CREATE TABLE bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER NOT NULL REFERENCES auctions(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    amount INTEGER NOT NULL CHECK(amount > 0),
    placed_at TEXT NOT NULL
);
CREATE TABLE games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    white_player_id INTEGER NOT NULL REFERENCES players(id),
    black_player_id INTEGER NOT NULL REFERENCES players(id),
    scheduled_at TEXT NOT NULL,
    event_name TEXT NOT NULL DEFAULT '',
    round_label TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '*' CHECK(result IN ('*','1-0','0-1','1/2-1/2')),
    pgn_text TEXT,
    recorded_at TEXT,
    white_award INTEGER NOT NULL DEFAULT 0,
    black_award INTEGER NOT NULL DEFAULT 0,
    white_team_id INTEGER REFERENCES teams(id),
    black_team_id INTEGER REFERENCES teams(id),
    attribution_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(attribution_confirmed IN (0,1)),
    created_at TEXT NOT NULL,
    CHECK(white_player_id <> black_player_id)
);
CREATE TABLE manager_invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    status TEXT NOT NULL CHECK(status IN ('pending','accepted','declined','cancelled')),
    created_at TEXT NOT NULL,
    responded_at TEXT
);
CREATE TABLE manager_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    final_fantasy_points INTEGER,
    final_budget INTEGER
);
CREATE TABLE player_team_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    source TEXT NOT NULL DEFAULT 'recorded',
    manager_player INTEGER NOT NULL DEFAULT 0 CHECK(manager_player IN (0,1))
);
CREATE TABLE players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    club TEXT NOT NULL DEFAULT '',
    rating INTEGER,
    points INTEGER NOT NULL DEFAULT 0,
    owner_team_id INTEGER REFERENCES teams(id),
    user_id INTEGER UNIQUE REFERENCES users(id),
    is_manager_player INTEGER NOT NULL DEFAULT 0 CHECK(is_manager_player IN (0, 1)),
    created_at TEXT NOT NULL
);
INSERT INTO "players" VALUES(1,'Existing Name','',1800,7,NULL,1,0,'2026-10-10T08:43:35+00:00');
CREATE TABLE points_ledger (
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
    );
CREATE TABLE role_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK(role IN ('manager','player')),
    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled')),
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by INTEGER REFERENCES users(id)
);
CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
INSERT INTO "schema_migrations" VALUES('v24_reliability_ledger','2026-10-10T08:43:35+00:00');
INSERT INTO "schema_migrations" VALUES('v24_historical_attribution','2026-10-10T08:43:35+00:00');
INSERT INTO "schema_migrations" VALUES('v6_roster_history','2026-10-10T08:43:35+00:00');
CREATE TABLE teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    manager_id INTEGER UNIQUE REFERENCES users(id),
    budget INTEGER NOT NULL DEFAULT 1000 CHECK (budget >= 0),
    created_at TEXT NOT NULL
);
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','manager','player')),
    created_at TEXT NOT NULL,
    manager_active INTEGER NOT NULL DEFAULT 0,
    player_active INTEGER NOT NULL DEFAULT 0,
    manager_available INTEGER NOT NULL DEFAULT 0,
    photo_data BLOB,
    photo_updated_at TEXT,
    auth_version INTEGER NOT NULL DEFAULT 0
);
INSERT INTO "users" VALUES(1,'аlice','pbkdf2_sha256$390000$8a9c1d1a322f59b880c12198a05a06c3$44d656e01c08ed1726a9515586cc163cea6677199de39d9614e5c40aae4b748a','player','2026-10-10T08:43:35+00:00',0,1,0,NULL,NULL,0);
CREATE UNIQUE INDEX one_open_auction_per_player
    ON auctions(player_id) WHERE status='open';
CREATE INDEX bids_by_auction ON bids(auction_id, amount DESC, id ASC);
CREATE INDEX manager_terms_by_user ON manager_terms(manager_id, started_at DESC);
CREATE UNIQUE INDEX pending_invitation_per_team ON manager_invitations(team_id) WHERE status='pending';
CREATE UNIQUE INDEX pending_role_request ON role_requests(user_id,role) WHERE status='pending';
CREATE INDEX player_team_terms_team_dates
    ON player_team_terms(team_id,started_at,ended_at);
CREATE UNIQUE INDEX active_player_team_term
    ON player_team_terms(player_id) WHERE ended_at IS NULL;
CREATE INDEX games_by_date ON games(scheduled_at DESC,id DESC);
CREATE INDEX games_by_white ON games(white_player_id,scheduled_at);
CREATE INDEX games_by_black ON games(black_player_id,scheduled_at);
CREATE UNIQUE INDEX unique_player_account ON players(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX audit_by_entity ON audit_log(entity_type,entity_id,id);
CREATE UNIQUE INDEX ledger_game_award ON points_ledger(game_id,player_id) WHERE source='game_award';
CREATE UNIQUE INDEX ledger_legacy_baseline ON points_ledger(player_id) WHERE source='legacy_adjustment';
CREATE INDEX ledger_by_player ON points_ledger(player_id,id);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('users',1);
INSERT INTO "sqlite_sequence" VALUES('players',1);
COMMIT;
