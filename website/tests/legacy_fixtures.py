"""Sanitized, representative old SQLite schemas, generated without external files.

These are migration fixtures, not copies of member data or old Python code. Their
schemas are intentionally frozen so a change to today's schema cannot update the
old side of the migration test by accident.
"""
import sqlite3
from pathlib import Path


CORE = '''
CREATE TABLE users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','manager','player')),
 created_at TEXT NOT NULL {flags}
);
CREATE TABLE teams (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 manager_id INTEGER UNIQUE REFERENCES users(id), budget INTEGER NOT NULL DEFAULT 1000 CHECK(budget>=0),
 created_at TEXT NOT NULL
);
CREATE TABLE players (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, club TEXT NOT NULL DEFAULT '',
 rating INTEGER, points INTEGER NOT NULL DEFAULT 0, owner_team_id INTEGER REFERENCES teams(id),
 user_id INTEGER UNIQUE REFERENCES users(id), is_manager_player INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
CREATE TABLE auctions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL REFERENCES players(id),
 seller_team_id INTEGER REFERENCES teams(id), starting_price INTEGER NOT NULL CHECK(starting_price>0),
 ends_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
 winner_team_id INTEGER REFERENCES teams(id), final_price INTEGER, created_at TEXT NOT NULL, closed_at TEXT
);
CREATE TABLE bids (
 id INTEGER PRIMARY KEY AUTOINCREMENT, auction_id INTEGER NOT NULL REFERENCES auctions(id),
 team_id INTEGER NOT NULL REFERENCES teams(id), amount INTEGER NOT NULL CHECK(amount>0), placed_at TEXT NOT NULL
);
CREATE TABLE manager_terms (
 id INTEGER PRIMARY KEY AUTOINCREMENT, manager_id INTEGER NOT NULL REFERENCES users(id),
 team_id INTEGER NOT NULL REFERENCES teams(id), started_at TEXT NOT NULL, ended_at TEXT,
 end_reason TEXT, final_fantasy_points INTEGER, final_budget INTEGER
);
'''
HISTORY = '''
CREATE TABLE player_team_terms (
 id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL REFERENCES players(id),
 team_id INTEGER NOT NULL REFERENCES teams(id), started_at TEXT NOT NULL, ended_at TEXT,
 end_reason TEXT, source TEXT NOT NULL DEFAULT 'recorded', manager_player INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
INSERT INTO schema_migrations VALUES ('v6_roster_history','2024-01-01T12:00:00+00:00');
'''
STAMP = '2024-01-01T12:00:00+00:00'


def create_legacy_database(path: Path, version: int):
    if version not in (3, 5, 6, 8):
        raise ValueError('Supported legacy fixtures: 3, 5, 6, 8')
    flags = '' if version == 3 else ', manager_active INTEGER NOT NULL DEFAULT 0, player_active INTEGER NOT NULL DEFAULT 0, manager_available INTEGER NOT NULL DEFAULT 0'
    photos = ', photo_data BLOB, photo_updated_at TEXT' if version == 8 else ''
    with sqlite3.connect(path) as db:
        db.executescript(CORE.format(flags=flags + photos))
        if version >= 6:
            db.executescript(HISTORY)
        username = 'pastmanager' if version == 3 else 'fixture_manager'
        team_name = 'Historical Team' if version == 3 else 'Sanitized Legacy Knights'
        # No usable credentials or real user records are included in these fixtures.
        db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,?,'invalid-fixture-hash','manager',?)", (username, STAMP))
        if version >= 5:
            db.execute('UPDATE users SET manager_active=1,player_active=1,manager_available=1 WHERE id=1')
        db.execute('INSERT INTO teams(id,name,manager_id,budget,created_at) VALUES(1,?,1,900,?)', (team_name, STAMP))
        db.execute('INSERT INTO manager_terms(manager_id,team_id,started_at) VALUES(1,1,?)', (STAMP,))
        if version != 3:
            db.execute("INSERT INTO players(id,name,owner_team_id,user_id,is_manager_player,created_at) VALUES(1,'Fixture Captain',1,1,1,?)", (STAMP,))
            if version >= 6:
                db.execute("INSERT INTO player_team_terms(player_id,team_id,started_at,source,manager_player) VALUES(1,1,?,'manager appointment',1)", (STAMP,))
        count = 1 if version == 3 else 30
        for index in range(count):
            player_id = index + 2
            owner = None if version == 3 else 1
            db.execute('INSERT INTO players(id,name,owner_team_id,created_at) VALUES(?,?,?,?)',
                       (player_id, f'Fictional Chess Player {index:02d}', owner, STAMP))
            status = 'open' if version == 3 else 'closed'
            end = '2099-01-01T12:00:00+00:00' if version == 3 else STAMP
            auction_id = db.execute('''INSERT INTO auctions(player_id,starting_price,ends_at,status,winner_team_id,final_price,created_at,closed_at)
                VALUES(?,20,?,?,?,25,?,?)''', (player_id, end, status, owner, STAMP, None if version == 3 else STAMP)).lastrowid
            db.execute('INSERT INTO bids(auction_id,team_id,amount,placed_at) VALUES(?,1,25,?)', (auction_id, STAMP))
            if version >= 6:
                db.execute("INSERT INTO player_team_terms(player_id,team_id,started_at,source) VALUES(?,1,?,'recorded')", (player_id, STAMP))
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    return path
