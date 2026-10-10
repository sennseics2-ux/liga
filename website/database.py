"""SQLite persistence, account/team management and auction accounting."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import secrets
import re
import sqlite3
from pathlib import Path

from league_migrations import apply as apply_migrations, SCHEMA_VERSION


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('CHESS_DB_PATH', str(BASE_DIR / 'league.sqlite3')))
STARTING_BUDGET = 1000


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


def connect():
    # Normal traffic must never silently create a new, empty database after a
    # deleted file or incorrectly mounted volume. Only init_db creates files.
    db = sqlite3.connect(DB_PATH.resolve().as_uri() + '?mode=rw', uri=True,
                         timeout=20, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=20000')
    return db


@contextmanager
def transaction():
    db = connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def read_db():
    db = connect()
    try:
        yield db
    finally:
        db.close()


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
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
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    manager_id INTEGER UNIQUE REFERENCES users(id),
    budget INTEGER NOT NULL DEFAULT 1000 CHECK (budget >= 0),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
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
CREATE TABLE IF NOT EXISTS auctions (
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
CREATE UNIQUE INDEX IF NOT EXISTS one_open_auction_per_player
    ON auctions(player_id) WHERE status='open';
CREATE TABLE IF NOT EXISTS bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER NOT NULL REFERENCES auctions(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    amount INTEGER NOT NULL CHECK(amount > 0),
    placed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bids_by_auction ON bids(auction_id, amount DESC, id ASC);
CREATE TABLE IF NOT EXISTS manager_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    final_fantasy_points INTEGER,
    final_budget INTEGER
);
CREATE INDEX IF NOT EXISTS manager_terms_by_user ON manager_terms(manager_id, started_at DESC);
CREATE TABLE IF NOT EXISTS manager_invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    status TEXT NOT NULL CHECK(status IN ('pending','accepted','declined','cancelled')),
    created_at TEXT NOT NULL,
    responded_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS pending_invitation_per_team ON manager_invitations(team_id) WHERE status='pending';
CREATE TABLE IF NOT EXISTS role_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK(role IN ('manager','player')),
    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled')),
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS pending_role_request ON role_requests(user_id,role) WHERE status='pending';
CREATE TABLE IF NOT EXISTS player_team_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    source TEXT NOT NULL DEFAULT 'recorded',
    manager_player INTEGER NOT NULL DEFAULT 0 CHECK(manager_player IN (0,1))
);
CREATE INDEX IF NOT EXISTS player_team_terms_team_dates
    ON player_team_terms(team_id,started_at,ended_at);
CREATE UNIQUE INDEX IF NOT EXISTS active_player_team_term
    ON player_team_terms(player_id) WHERE ended_at IS NULL;
CREATE TABLE IF NOT EXISTS games (
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
CREATE INDEX IF NOT EXISTS games_by_date ON games(scheduled_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS games_by_white ON games(white_player_id,scheduled_at);
CREATE INDEX IF NOT EXISTS games_by_black ON games(black_player_id,scheduled_at);
CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
'''


def init_db():
    """Create or upgrade an existing database without losing its data.

    SQLite doesn't support altering CHECK constraints or NOT NULL columns directly;
    preserve IDs and dependent auction/bid rows while rebuilding those two tables.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        DB_PATH.chmod(0o600)
        db.execute('PRAGMA busy_timeout=20000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=OFF')
        # On the first upgrade, make a consistent backup of the legacy database.
        # Use SQLite's backup API rather than copying an actively opened database.
        legacy = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if legacy and "'player'" not in legacy['sql']:
            backup_file = DB_PATH.with_name(DB_PATH.name + '.pre-v2.bak')
            if not backup_file.exists():
                with sqlite3.connect(backup_file) as backup_db:
                    db.backup(backup_db)
        # A snapshot of existing data is kept before automatically adding manager
        # player profiles. A consistent SQLite backup includes any WAL contents.
        if legacy:
            backup_file = DB_PATH.with_name(DB_PATH.name + '.pre-v3.bak')
            if not backup_file.exists():
                with sqlite3.connect(backup_file) as backup_db:
                    db.backup(backup_db)
        if legacy and 'manager_active' not in legacy['sql']:
            backup_file = DB_PATH.with_name(DB_PATH.name + '.pre-v4.bak')
            if not backup_file.exists():
                with sqlite3.connect(backup_file) as backup_db:
                    db.backup(backup_db)
        # New games and PGN feature: keep a consistent snapshot before upgrading V8.
        if legacy and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='games'").fetchone():
            backup_file = DB_PATH.with_name(DB_PATH.name + '.pre-v9.bak')
            if not backup_file.exists():
                with sqlite3.connect(backup_file) as backup_db:
                    db.backup(backup_db)
        if legacy:
            migration_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
            upgraded = migration_table and db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (SCHEMA_VERSION,)).fetchone()
            backup_file = DB_PATH.with_name(DB_PATH.name + '.pre-v25.bak')
            if not upgraded and not backup_file.exists():
                with sqlite3.connect(backup_file) as backup_db:
                    db.backup(backup_db)
        for suffix in ('.pre-v2.bak', '.pre-v3.bak', '.pre-v4.bak', '.pre-v9.bak', '.pre-v25.bak'):
            backup_file = DB_PATH.with_name(DB_PATH.name + suffix)
            if backup_file.exists():
                backup_file.chmod(0o600)
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        user_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()['sql']
        if "'player'" not in user_sql:
            db.execute('''CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin','manager','player')),
                created_at TEXT NOT NULL)''')
            db.execute('INSERT INTO users_new(id,username,password_hash,role,created_at) SELECT id,username,password_hash,role,created_at FROM users')
            db.execute('DROP TABLE users')
            db.execute('ALTER TABLE users_new RENAME TO users')
        team_info = {c['name']: c for c in db.execute('PRAGMA table_info(teams)')}
        if team_info['manager_id']['notnull']:
            db.execute('''CREATE TABLE teams_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                manager_id INTEGER UNIQUE REFERENCES users(id),
                budget INTEGER NOT NULL DEFAULT 1000 CHECK(budget >= 0),
                created_at TEXT NOT NULL)''')
            db.execute('INSERT INTO teams_new(id,name,manager_id,budget,created_at) SELECT id,name,manager_id,budget,created_at FROM teams')
            db.execute('DROP TABLE teams')
            db.execute('ALTER TABLE teams_new RENAME TO teams')
        player_fields = {c['name'] for c in db.execute('PRAGMA table_info(players)')}
        if 'user_id' not in player_fields:
            db.execute('ALTER TABLE players ADD COLUMN user_id INTEGER REFERENCES users(id)')
        if 'is_manager_player' not in player_fields:
            db.execute('ALTER TABLE players ADD COLUMN is_manager_player INTEGER NOT NULL DEFAULT 0 CHECK(is_manager_player IN (0,1))')
        user_fields = {c['name'] for c in db.execute('PRAGMA table_info(users)')}
        new_flags = 'manager_active' not in user_fields
        for field in ('manager_active','player_active','manager_available'):
            if field not in user_fields:
                db.execute(f'ALTER TABLE users ADD COLUMN {field} INTEGER NOT NULL DEFAULT 0')
        # V7: photos are stored in SQLite so ordinary database backups include them.
        for field, sqltype in [('photo_data', 'BLOB'), ('photo_updated_at', 'TEXT')]:
            if field not in user_fields:
                db.execute(f'ALTER TABLE users ADD COLUMN {field} {sqltype}')
        if 'auth_version' not in user_fields:
            db.execute('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')
        if new_flags:
            # Existing manager accounts were eligible to play under v3, so give them
            # both roles. Existing player accounts keep only the player role.
            db.execute("UPDATE users SET manager_active=1,player_active=1,manager_available=1 WHERE role='manager'")
            db.execute("UPDATE users SET manager_active=0,player_active=1 WHERE role='player'")
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS unique_player_account ON players(user_id) WHERE user_id IS NOT NULL')
        apply_migrations(db, iso(now_utc()))
        # Existing releases allowed assignments to conflict with open auctions.
        # Preserve their bids for review, release reservations, and continue the
        # upgrade rather than preventing the entire application from starting.
        conflicts = db.execute('''SELECT a.id FROM auctions a JOIN players p ON p.id=a.player_id
            LEFT JOIN users u ON u.id=p.user_id LEFT JOIN teams t ON t.manager_id=u.id
            WHERE a.status='open' AND (p.is_manager_player=1 OR
                (t.id IS NOT NULL AND u.manager_active=1 AND u.player_active=1))''').fetchall()
        for conflict in conflicts:
            _fail_auction(db, conflict['id'], 'Manager assignment conflicts with this legacy auction.')
        # Earlier versions made manager-player profiles optional. Every manager
        # with a team is now automatically eligible to play for their own squad.
        # Existing profiles are reused; calling init_db repeatedly is safe.
        assignments = db.execute('''SELECT t.id AS team_id, t.manager_id FROM teams t
            JOIN users u ON u.id=t.manager_id WHERE u.manager_active=1 AND u.player_active=1 ''').fetchall()
        for assignment in assignments:
            _activate_manager_player(db, assignment['team_id'], assignment['manager_id'])
        # Reconstruct active historic terms when upgrading v3. Earlier versions
        # did not record start dates, so use the team creation date as an
        # explicitly approximate starting point for migrated assignments.
        for a in db.execute('SELECT id,manager_id,created_at FROM teams WHERE manager_id IS NOT NULL').fetchall():
            if not db.execute('SELECT 1 FROM manager_terms WHERE team_id=? AND manager_id=? AND ended_at IS NULL',
                              (a['id'], a['manager_id'])).fetchone():
                db.execute('INSERT INTO manager_terms(manager_id,team_id,started_at) VALUES(?,?,?)',
                           (a['manager_id'], a['id'], a['created_at']))
        _backfill_player_team_terms(db)
        problems = db.execute('PRAGMA foreign_key_check').fetchall()
        if problems:
            raise RuntimeError(f'Database migration failed foreign key check: {problems}')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def readiness():
    """Check the mounted database, required schema and settlement alerts."""
    with read_db() as db:
        required = {'users', 'teams', 'players', 'auctions', 'games', 'points_ledger', 'audit_log', 'seasons', 'team_matches', 'password_resets'}
        actual = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= actual:
            raise sqlite3.DatabaseError('Required league tables are missing.')
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (SCHEMA_VERSION,)).fetchone():
            raise sqlite3.DatabaseError('The league database needs migration.')
        # Query the columns that current code needs, not just SELECT 1.
        db.execute('SELECT auth_version,account_active,email,name,fide_id,fide_id_locked,manager_active,player_active FROM users LIMIT 1').fetchone()
        db.execute('SELECT status,failure_reason FROM auctions LIMIT 1').fetchone()
        db.execute('SELECT white_award,black_award,white_team_id,black_team_id,attribution_confirmed FROM games LIMIT 1').fetchone()
        failed = db.execute("SELECT COUNT(*) FROM auctions WHERE status='failed'").fetchone()[0]
        overdue = db.execute("SELECT COUNT(*) FROM auctions WHERE status='open' AND ends_at<=?", (iso(now_utc()),)).fetchone()[0]
        last_settlement = db.execute("SELECT MAX(created_at) FROM audit_log WHERE event='auction_settled'").fetchone()[0]
    return {'database': 'ready', 'schema': SCHEMA_VERSION, 'failed_auctions': failed,
            'overdue_auctions': overdue, 'last_settlement_at': last_settlement}


def _reason(value):
    value = str(value or '').strip()
    if not 3 <= len(value) <= 500:
        raise ValueError('Provide a reason of 3–500 characters.')
    return value


def _admin_actor(db, actor_id):
    actor = db.execute('SELECT role,account_active FROM users WHERE id=?', (actor_id,)).fetchone()
    if not actor or (actor['role'] != 'admin' or not actor['account_active']):
        raise ValueError('Only administrators can make this change.')


def _audit(db, event, entity_type, entity_id, actor_id=None, reason='Automatic league operation', before=None, after=None):
    db.execute('''INSERT INTO audit_log(event,entity_type,entity_id,actor_id,reason,before_json,after_json,created_at)
        VALUES(?,?,?,?,?,?,?,?)''',
        (event, entity_type, entity_id, actor_id, _reason(reason),
         json.dumps(before, sort_keys=True) if before is not None else None,
         json.dumps(after, sort_keys=True) if after is not None else None, iso(now_utc())))


def save_profile_photo(user_id, jpeg_bytes):
    """Persist a validated, compressed JPEG on the user's account."""
    if not jpeg_bytes or len(jpeg_bytes) > 600_000:
        raise ValueError('Photo could not be saved.')
    with transaction() as db:
        result = db.execute("""UPDATE users SET photo_data=?, photo_updated_at=?
            WHERE id=? AND role!='admin' AND player_active=1""",
            (jpeg_bytes, iso(now_utc()), user_id))
        if result.rowcount != 1:
            raise ValueError('Your player role must be active to upload a photo.')


def remove_profile_photo(user_id):
    with transaction() as db:
        result = db.execute("""UPDATE users SET photo_data=NULL, photo_updated_at=NULL
            WHERE id=? AND role!='admin'""", (user_id,))
        if result.rowcount != 1:
            raise ValueError('Member account not found.')


def _roster_tracking_ready(db):
    return db.execute("SELECT 1 FROM schema_migrations WHERE version='v6_roster_history'").fetchone() is not None


def _start_player_term(db, player_id, team_id, started_at=None, source='recorded', manager_player=False):
    """Write one current ownership period. All callers must hold an IMMEDIATE transaction."""
    started_at = started_at or iso(now_utc())
    active = db.execute('SELECT * FROM player_team_terms WHERE player_id=? AND ended_at IS NULL',
                        (player_id,)).fetchone()
    if active:
        if active['team_id'] == team_id:
            return active['id']
        raise ValueError('Historical roster data shows an existing team; ownership must be ended first.')
    return db.execute("""INSERT INTO player_team_terms
        (player_id,team_id,started_at,source,manager_player) VALUES (?,?,?,?,?)""",
        (player_id,team_id,started_at,source,int(bool(manager_player)))).lastrowid


def _stop_player_term(db, player_id, when=None, reason='left team'):
    when = when or iso(now_utc())
    db.execute("""UPDATE player_team_terms SET ended_at=?,end_reason=?
        WHERE player_id=? AND ended_at IS NULL""", (when,reason,player_id))


def _backfill_player_team_terms(db):
    """One-time, conservative V5 conversion from known transfer and manager records.

    Never backdate an untraced current owner to player/team creation. Past memberships
    require dated auction evidence or a historical manager appointment. Running init
    repeatedly leaves the history unchanged.
    """
    if db.execute("SELECT 1 FROM schema_migrations WHERE version='v6_roster_history'").fetchone():
        return
    players = db.execute('SELECT id,user_id,owner_team_id,is_manager_player FROM players ORDER BY id').fetchall()
    for p in players:
        pid=p['id']
        events=db.execute("""SELECT seller_team_id,winner_team_id,created_at,closed_at,ends_at
            FROM auctions WHERE player_id=? AND status='closed'
            ORDER BY COALESCE(closed_at,ends_at),id""",(pid,)).fetchall()
        for a in events:
            closed=a['closed_at'] or a['ends_at']
            current=db.execute('SELECT * FROM player_team_terms WHERE player_id=? AND ended_at IS NULL',(pid,)).fetchone()
            seller=a['seller_team_id']
            winner=a['winner_team_id']
            if seller is not None and (current is None or current['team_id'] != seller):
                if current:
                    _stop_player_term(db,pid,a['created_at'],'older records incomplete')
                _start_player_term(db,pid,seller,a['created_at'],'legacy auction listing')
            if winner is not None and winner != seller:
                _stop_player_term(db,pid,closed,'transferred')
                _start_player_term(db,pid,winner,closed,'legacy auction win')
        # Managers have trustworthy appointment dates; include their eligible
        # playing periods even if they no longer manage or play for a team.
        if p['user_id'] is not None:
            terms=db.execute("""SELECT team_id,started_at,ended_at,end_reason
                FROM manager_terms WHERE manager_id=? ORDER BY started_at,id""",(p['user_id'],)).fetchall()
            for mt in terms:
                current=db.execute('SELECT * FROM player_team_terms WHERE player_id=? AND ended_at IS NULL',(pid,)).fetchone()
                if current and current['team_id']!=mt['team_id']:
                    _stop_player_term(db,pid,mt['started_at'],'older records incomplete')
                    current=None
                if not current:
                    _start_player_term(db,pid,mt['team_id'],mt['started_at'],'manager appointment',True)
                if mt['ended_at']:
                    _stop_player_term(db,pid,mt['ended_at'],mt['end_reason'] or 'appointment ended')
        # If historical records do not establish today's owner, start a term
        # at the migration snapshot (never claim membership in past years).
        current=db.execute('SELECT * FROM player_team_terms WHERE player_id=? AND ended_at IS NULL',(pid,)).fetchone()
        if current and current['team_id']!=p['owner_team_id']:
            _stop_player_term(db,pid,current['started_at'],'unrecorded legacy change; end date unknown')
            current=None
        if p['owner_team_id'] is not None and current is None:
            _start_player_term(db,pid,p['owner_team_id'],iso(now_utc()),'imported current snapshot',p['is_manager_player'])
    db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES('v6_roster_history',?)", (iso(now_utc()),))


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 390000)
    return f'pbkdf2_sha256$390000${salt.hex()}${digest.hex()}'


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, target = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        calculated = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(calculated, bytes.fromhex(target))
    except (ValueError, TypeError):
        return False


def change_account_password(user_id, current_password, new_password):
    """Replace a password atomically and revoke all other signed-in sessions."""
    if not isinstance(current_password, str) or not isinstance(new_password, str):
        raise ValueError('Invalid password input.')
    if not 12 <= len(new_password) <= 256:
        raise ValueError('The new password must contain 12–256 characters.')
    # Password hashing is deliberately expensive. Do it before taking SQLite's
    # writer lock, then verify the version has not changed when committing.
    with read_db() as db:
        row = db.execute('SELECT password_hash,auth_version FROM users WHERE id=?', (user_id,)).fetchone()
    if row is None or not verify_password(current_password, row['password_hash']):
        raise ValueError('Current password is incorrect.')
    if verify_password(new_password, row['password_hash']):
        raise ValueError('Choose a password different from the current one.')
    replacement = hash_password(new_password)
    with transaction() as db:
        current = db.execute('SELECT password_hash,auth_version FROM users WHERE id=?', (user_id,)).fetchone()
        if current is None or current['password_hash'] != row['password_hash'] or current['auth_version'] != row['auth_version']:
            raise ValueError('Your password changed in another session. Please sign in again.')
        db.execute('UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?',
                   (replacement, user_id))
        return row['auth_version'] + 1


def validate_username(username):
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,32}', username):
        raise ValueError('Username must be 3–32 ASCII characters (letters, numbers, - or _).')
    if username.isdecimal():
        raise ValueError('Username cannot contain only numbers.')


def create_account(username, password, role, email=None):
    validate_username(username)
    from account_service import validate_email
    email = validate_email(email) if email is not None else None
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('Password must contain 12–256 characters.')
    if role not in ('manager', 'player'):
        raise ValueError('Choose either manager or player.')
    encoded_password = hash_password(password)
    with transaction() as db:
        try:
            uid = db.execute('''INSERT INTO users(username,password_hash,role,created_at,
                    manager_active,player_active,manager_available,email,name) VALUES (?,?,?,?,?,?,?,?,?)''',
                              (username, encoded_password, role, iso(now_utc()),
                               int(role=='manager'), 1, int(role=='manager'), email, username)).lastrowid
            if role=='manager':
                db.execute('INSERT INTO players(name,user_id,is_manager_player,created_at) VALUES(?,?,1,?)',
                           (username,uid,iso(now_utc())))
            return uid
        except sqlite3.IntegrityError:
            raise ValueError('That username or email address is already taken.') from None


def create_team(name):
    name = name.strip()
    if not 3 <= len(name) <= 45:
        raise ValueError('Team name must be 3–45 characters.')
    with transaction() as db:
        try:
            return db.execute('INSERT INTO teams(name,budget,created_at) VALUES (?,?,?)',
                              (name, STARTING_BUDGET, iso(now_utc()))).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('That team name is already taken.') from None


def _score_team(db, team_id):
    return db.execute('SELECT COALESCE(SUM(points),0) FROM players WHERE owner_team_id=?', (team_id,)).fetchone()[0]


def _end_manager_term(db, team_id, manager_id, reason):
    team = db.execute('SELECT budget FROM teams WHERE id=?', (team_id,)).fetchone()
    db.execute('''UPDATE manager_terms SET ended_at=?, end_reason=?,final_fantasy_points=?,final_budget=?
        WHERE team_id=? AND manager_id=? AND ended_at IS NULL''',
        (iso(now_utc()), reason, _score_team(db, team_id), team['budget'], team_id, manager_id))


def _unassign_manager(db, team_id, reason):
    team = db.execute('SELECT * FROM teams WHERE id=?', (team_id,)).fetchone()
    if not team or team['manager_id'] is None:
        return
    manager_id = team['manager_id']
    _end_manager_term(db, team_id, manager_id, reason)
    db.execute('UPDATE teams SET manager_id=NULL WHERE id=?', (team_id,))
    profile = db.execute('SELECT id FROM players WHERE user_id=? AND is_manager_player=1', (manager_id,)).fetchone()
    if profile and _roster_tracking_ready(db):
        _stop_player_term(db, profile['id'], reason=reason)
    db.execute('UPDATE players SET owner_team_id=NULL WHERE user_id=? AND is_manager_player=1', (manager_id,))


def _accept_manager(db, team_id, manager_id):
    team = db.execute('SELECT * FROM teams WHERE id=?', (team_id,)).fetchone()
    user = db.execute('SELECT * FROM users WHERE id=?', (manager_id,)).fetchone()
    if not team:
        raise ValueError('Team not found.')
    if not user or not user['account_active'] or not user['manager_active'] or user['role']=='admin':
        raise ValueError('Choose a manager with an active manager role.')
    if db.execute('SELECT 1 FROM teams WHERE manager_id=? AND id!=?', (manager_id,team_id)).fetchone():
        raise ValueError('This manager already runs another team.')
    if team['manager_id'] is not None and team['manager_id'] != manager_id:
        raise ValueError('Team already has a manager. Vacate it first.')
    if team['manager_id'] == manager_id:
        return
    db.execute('UPDATE teams SET manager_id=? WHERE id=?', (manager_id,team_id))
    db.execute('INSERT INTO manager_terms(manager_id,team_id,started_at) VALUES (?,?,?)',
               (manager_id,team_id,iso(now_utc())))
    if user['player_active']:
        _activate_manager_player(db,team_id,manager_id)
    db.execute('UPDATE users SET manager_available=0 WHERE id=?', (manager_id,))
    db.execute("UPDATE manager_invitations SET status='cancelled',responded_at=? WHERE status='pending' AND manager_id=?",
               (iso(now_utc()), manager_id))


def assign_manager(team_id, manager_id):
    # Legacy administrative operation; new web assignments require consent.
    with transaction() as db:
        team=db.execute('SELECT * FROM teams WHERE id=?', (team_id,)).fetchone()
        if not team:
            raise ValueError('Team not found.')
        if manager_id is None:
            _unassign_manager(db,team_id,'admin removed manager')
            return
        if team['manager_id'] is not None and team['manager_id']!=manager_id:
            _unassign_manager(db,team_id,'admin reassignment')
        _accept_manager(db,team_id,manager_id)


def invite_manager(team_id, manager_id):
    with transaction() as db:
        team=db.execute('SELECT * FROM teams WHERE id=?',(team_id,)).fetchone()
        manager=db.execute('SELECT * FROM users WHERE id=?',(manager_id,)).fetchone()
        if not team or team['manager_id'] is not None:
            raise ValueError('The team must be vacant before sending an invitation.')
        if not manager or not manager['account_active'] or not manager['manager_active'] or not manager['manager_available'] or manager['role']=='admin':
            raise ValueError('Choose an available manager with an active manager role.')
        if db.execute('SELECT 1 FROM teams WHERE manager_id=?',(manager_id,)).fetchone():
            raise ValueError('This manager already manages another team.')
        existing=db.execute('SELECT owner_team_id FROM players WHERE user_id=?',(manager_id,)).fetchone()
        if manager['player_active'] and existing and existing['owner_team_id'] not in (None,team_id):
            raise ValueError('This manager is currently a chess player for another team. Their player must first be released.')
        if db.execute("SELECT 1 FROM manager_invitations WHERE team_id=? AND status='pending'",(team_id,)).fetchone():
            raise ValueError('This team already has a pending invitation.')
        return db.execute('INSERT INTO manager_invitations(manager_id,team_id,status,created_at) VALUES(?,?,?,?)',
                    (manager_id,team_id,'pending',iso(now_utc()))).lastrowid


def cancel_invitation(invitation_id):
    with transaction() as db:
        updated=db.execute("UPDATE manager_invitations SET status='cancelled',responded_at=? WHERE id=? AND status='pending'",
                           (iso(now_utc()),invitation_id))
        if updated.rowcount!=1:
            raise ValueError('This invitation is no longer pending.')


def respond_invitation(user_id, invitation_id, accept):
    with transaction() as db:
        invite=db.execute("SELECT * FROM manager_invitations WHERE id=? AND manager_id=? AND status='pending'",
                          (invitation_id,user_id)).fetchone()
        if not invite:
            raise ValueError('This invitation is no longer available.')
        if accept:
            _accept_manager(db,invite['team_id'],user_id)
            status='accepted'
        else:
            status='declined'
        db.execute('UPDATE manager_invitations SET status=?,responded_at=? WHERE id=?',
                   (status,iso(now_utc()),invitation_id))


def set_availability(user_id, available):
    with transaction() as db:
        user=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not user or not user['manager_active']:
            raise ValueError('Your manager role is not active.')
        if db.execute('SELECT 1 FROM teams WHERE manager_id=?',(user_id,)).fetchone():
            raise ValueError('You must resign from your team before updating availability.')
        db.execute('UPDATE users SET manager_available=? WHERE id=?',(int(available),user_id))


def resign_team(user_id):
    with transaction() as db:
        team=db.execute('SELECT id FROM teams WHERE manager_id=?',(user_id,)).fetchone()
        if not team:
            raise ValueError('You are not managing a team.')
        _unassign_manager(db,team['id'],'resigned')
        db.execute('UPDATE users SET manager_available=0 WHERE id=?',(user_id,))
        return team['id']


def quit_role(user_id, role):
    if role not in ('manager','player'):
        raise ValueError('Unknown role.')
    with transaction() as db:
        u=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not u or not u['account_active'] or u['role']=='admin' or not u[f'{role}_active']:
            raise ValueError('This role is not active.')
        if role=='manager':
            team=db.execute('SELECT id FROM teams WHERE manager_id=?',(user_id,)).fetchone()
            if team:
                _unassign_manager(db,team['id'],'left manager role')
            db.execute("UPDATE users SET manager_active=0,manager_available=0,role='player' WHERE id=?", (user_id,))
            # Former manager is now an ordinary transferable free agent.
            db.execute('UPDATE players SET is_manager_player=0,owner_team_id=NULL WHERE user_id=? AND is_manager_player=1',(user_id,))
        else:
            profile=db.execute('SELECT id FROM players WHERE user_id=?',(user_id,)).fetchone()
            if profile and db.execute("SELECT 1 FROM auctions WHERE player_id=? AND status='open'",(profile['id'],)).fetchone():
                raise ValueError('You cannot leave the player role while your player is in an open auction.')
            # Ordinary chess players cannot resign from their owned squad by
            # disguising that action as a role change. Their manager must release
            # them first. A manager may stop playing for their own team.
            ownership=db.execute('SELECT owner_team_id,is_manager_player FROM players WHERE user_id=?',(user_id,)).fetchone()
            if ownership and ownership['owner_team_id'] is not None and not ownership['is_manager_player']:
                raise ValueError('Your team manager must remove you from your team before you can quit the player role.')
            db.execute("UPDATE users SET player_active=0,role=CASE WHEN manager_active=1 THEN 'manager' ELSE 'player' END WHERE id=?",(user_id,))
            # A manager-only account never appears as a chess-player roster member.
            if profile and _roster_tracking_ready(db):
                _stop_player_term(db,profile['id'],reason='left player role')
            db.execute('UPDATE players SET owner_team_id=NULL WHERE user_id=?',(user_id,))
            if not u['manager_active']:
                db.execute('UPDATE users SET manager_available=0 WHERE id=?', (user_id,))
        db.execute("UPDATE role_requests SET status='cancelled',reviewed_at=? WHERE user_id=? AND status='pending'",
                   (iso(now_utc()),user_id))
        if role=='manager':
            db.execute("UPDATE manager_invitations SET status='cancelled',responded_at=? WHERE manager_id=? AND status='pending'",
                       (iso(now_utc()),user_id))
        _audit(db, 'role_deactivated', 'user', user_id, user_id, f'Member left the {role} role',
               before={'manager_active': u['manager_active'], 'player_active': u['player_active']},
               after=dict(db.execute('SELECT manager_active,player_active FROM users WHERE id=?', (user_id,)).fetchone()))


def request_role(user_id, role):
    if role not in ('manager','player'):
        raise ValueError('Unknown role.')
    with transaction() as db:
        user=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not user or not user['account_active'] or user['role']=='admin':
            raise ValueError('Account not found.')
        if user[f'{role}_active']:
            raise ValueError(f'Your {role} role is already active.')
        if db.execute("SELECT 1 FROM role_requests WHERE user_id=? AND role=? AND status='pending'",(user_id,role)).fetchone():
            raise ValueError('You already have a pending request for that role.')
        db.execute("INSERT INTO role_requests(user_id,role,status,created_at) VALUES(?,?,'pending',?)",
                   (user_id,role,iso(now_utc())))


def review_role_request(admin_id,request_id,approve):
    with transaction() as db:
        admin=db.execute('SELECT role,account_active FROM users WHERE id=?',(admin_id,)).fetchone()
        if not admin or admin['role']!='admin':
            raise ValueError('Only administrators can review requests.')
        request=db.execute("SELECT * FROM role_requests WHERE id=? AND status='pending'",(request_id,)).fetchone()
        if not request:
            raise ValueError('This request is no longer pending.')
        user=db.execute('SELECT * FROM users WHERE id=?',(request['user_id'],)).fetchone()
        if not user['account_active']:
            raise ValueError('Reactivate the account before approving a role.')
        if approve and user[f"{request['role']}_active"]:
            raise ValueError('That role is already active.')
        if approve:
            column='manager_active' if request['role']=='manager' else 'player_active'
            db.execute(f'UPDATE users SET {column}=1 WHERE id=?',(request['user_id'],))
            db.execute("UPDATE users SET role=CASE WHEN manager_active=1 THEN 'manager' ELSE 'player' END WHERE id=?", (request['user_id'],))
            # If this newly approved user already manages a team, player
            # eligibility is restored and the same locked profile is reused.
            if request['role']=='player':
                team=db.execute('SELECT id FROM teams WHERE manager_id=?',(request['user_id'],)).fetchone()
                if team:
                    _activate_manager_player(db,team['id'],request['user_id'])
        db.execute('UPDATE role_requests SET status=?,reviewed_at=?,reviewed_by=? WHERE id=?',
                   ('approved' if approve else 'rejected',iso(now_utc()),admin_id,request_id))
        _audit(db, 'role_request_approved' if approve else 'role_request_rejected', 'user', request['user_id'],
               admin_id, f"Administrator reviewed {request['role']} activation request")


def kick_player(manager_id, player_id):
    with transaction() as db:
        team=db.execute('SELECT id FROM teams WHERE manager_id=?',(manager_id,)).fetchone()
        if not team:
            raise ValueError('You must manage a team to remove a player.')
        player=db.execute('SELECT * FROM players WHERE id=?',(player_id,)).fetchone()
        if not player or player['owner_team_id']!=team['id']:
            raise ValueError('That player is not on your team.')
        if player['is_manager_player']:
            raise ValueError('Managers cannot be kicked from the player roster.')
        if db.execute("SELECT 1 FROM auctions WHERE player_id=? AND status='open'",(player_id,)).fetchone():
            raise ValueError('Cannot kick a player while they are in an active auction.')
        if _roster_tracking_ready(db):
            _stop_player_term(db,player_id,reason='removed by manager')
        db.execute('UPDATE players SET owner_team_id=NULL WHERE id=?',(player_id,))


def _activate_manager_player(db, team_id, manager_id):
    user = db.execute('SELECT * FROM users WHERE id=? AND manager_active=1 AND account_active=1', (manager_id,)).fetchone()
    if not user:
        raise ValueError('Manager not found.')
    existing = db.execute('SELECT * FROM players WHERE user_id=?', (manager_id,)).fetchone()
    if existing:
        if db.execute("SELECT 1 FROM auctions WHERE player_id=? AND status='open'", (existing['id'],)).fetchone():
            raise ValueError('Your player profile is in an open auction. Resolve the auction before accepting a manager assignment.')
        if existing['owner_team_id'] is not None and existing['owner_team_id'] != team_id:
            raise ValueError('Your player profile belongs to another team; resolve this before managing a team.')
        db.execute('UPDATE players SET owner_team_id=?,is_manager_player=1 WHERE id=?', (team_id, existing['id']))
        if _roster_tracking_ready(db):
            _start_player_term(db,existing['id'],team_id,manager_player=True)
    else:
        player_id=db.execute('''INSERT INTO players(name,owner_team_id,user_id,is_manager_player,created_at)
            VALUES (?,?,?,1,?)''', (user['name'] or user['username'], team_id, manager_id, iso(now_utc()))).lastrowid
        if _roster_tracking_ready(db):
            _start_player_term(db,player_id,team_id,manager_player=True)


def create_player(name, club='', rating=None, user_id=None):
    name = name.strip()
    club = club.strip()
    if not 2 <= len(name) <= 80:
        raise ValueError('Player name must be 2–80 characters.')
    if len(club) > 80:
        raise ValueError('Club name is too long.')
    if rating is not None and not 0 <= rating <= 3500:
        raise ValueError('Rating must be between 0 and 3500.')
    with transaction() as db:
        if user_id is not None:
            account = db.execute('SELECT role,player_active,account_active,name,fide_rating FROM users WHERE id=?', (user_id,)).fetchone()
            if not account or not account['account_active'] or not account['player_active'] or account['role']=='admin':
                raise ValueError('Only a registered player account can be linked to this player.')
            if db.execute('SELECT id FROM players WHERE user_id=?', (user_id,)).fetchone():
                raise ValueError('This player account already has a chess profile.')
        if user_id is not None:
            db.execute('UPDATE users SET name=? WHERE id=?',(name,user_id))
            rating = account['fide_rating'] if account['fide_rating'] is not None else rating
        try:
            return db.execute('INSERT INTO players(name,club,rating,user_id,created_at) VALUES (?,?,?,?,?)',
                              (name, club, rating, user_id, iso(now_utc()))).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('Could not create player; account may already be linked.') from None


# Compatibility facade: web routes, offline tools and older integrations keep
# the established database API while the business rules live in focused modules.
from league_auctions import (
    highest_bid,
    reserved_credits,
    settle_auction,
    _fail_auction,
    _settle_isolated,
    _settle_expired,
    settle_expired,
    close_auction,
    cancel_auction,
    retry_auction,
    place_bid,
    create_auction,
)
from league_scoring import (
    create_game,
    _team_at,
    _ensure_points_baseline,
    _refresh_points,
    adjust_player_points,
    update_game_result,
    attach_pgn,
    remove_game_pgn,
)
