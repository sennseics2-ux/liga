"""End-to-end regression tests for manager/player accounts and the transfer market."""
import os
import re
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('CHESS_SESSION_SECRET', 'test-session-secret-for-unit-tests-123')
import database as store
from main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    with TestClient(app) as c:
        yield c


def token(client, page='/register'):
    match = re.search(r'name="csrf" value="([^"]+)"', client.get(page).text)
    assert match is not None, page
    return match.group(1)


def post(client, endpoint, **kwargs):
    csrf = token(client, endpoint if endpoint in ('/register', '/login') else '/')
    return client.post(endpoint, data={'csrf': csrf, **kwargs}, follow_redirects=True)


def register(client, name, role='manager'):
    result = post(client, '/register', username=name, password='p4ssword!AB12', role=role)
    assert result.status_code == 200
    assert 'Account created' in result.text or 'Player account created' in result.text
    return result


def logout(client):
    return post(client, '/logout')


def seed_admin():
    with store.transaction() as db:
        db.execute('INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)',
                   ('commissioner', store.hash_password('adminpass123!'), 'admin', store.iso(store.now_utc())))


def login_admin(client):
    result = post(client, '/login', username='commissioner', password='adminpass123!')
    assert result.status_code == 200
    assert 'Commissioner' in result.text


def new_team(manager, team):
    uid = store.create_account(manager, 'password123!', 'manager')
    tid = store.create_team(team)
    store.assign_manager(tid, uid)
    return uid, tid


def expire(auction):
    with store.transaction() as db:
        db.execute('UPDATE auctions SET ends_at=? WHERE id=?',
                   (store.iso(store.now_utc()-timedelta(seconds=1)), auction))
    store.settle_expired()


def test_signup_roles_and_no_auto_team(client):
    register(client, 'alice')
    assert 'Awaiting administrator assignment' in client.get('/dashboard').text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM teams').fetchone()[0] == 0
        assert db.execute("SELECT role FROM users WHERE username='alice'").fetchone()[0] == 'manager'
    logout(client)
    register(client, 'lisa', 'player')
    assert 'Waiting for your chess profile' in client.get('/dashboard').text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM players').fetchone()[0] == 0
        assert db.execute("SELECT role FROM users WHERE username='lisa'").fetchone()[0] == 'player'
    assert client.get('/auctions').status_code == 200


def test_public_cannot_create_teams_or_players(client):
    register(client, 'alice')
    assert post(client, '/admin/teams', name='Bad Team').status_code == 403
    assert post(client, '/admin/players', name='Bad Player').status_code == 403
    assert post(client, '/admin/teams/1/manager', manager_id='').status_code == 403


def test_admin_team_creation_assignment_and_manager_player(client):
    seed_admin()
    register(client, 'knight')
    with store.read_db() as db:
        manager_id = db.execute("SELECT id FROM users WHERE username='knight'").fetchone()[0]
    logout(client)
    login_admin(client)
    assert 'Team created' in post(client, '/admin/teams', name='King’s Guard').text
    with store.read_db() as db:
        team = db.execute('SELECT * FROM teams').fetchone()
        assert team['manager_id'] is None
        team_id = team['id']
    assert 'make_player' not in client.get('/admin').text
    assert '/manager-player' not in client.get('/admin').text
    response = post(client, f'/admin/teams/{team_id}/manager', manager_id=str(manager_id))
    assert 'Manager invitation sent' in response.text
    with store.read_db() as db:
        assert db.execute('SELECT manager_id FROM teams WHERE id=?', (team_id,)).fetchone()[0] is None
        invitation_id = db.execute('SELECT id FROM manager_invitations WHERE team_id=?', (team_id,)).fetchone()[0]
    logout(client)
    post(client, '/login', username='knight', password='p4ssword!AB12')
    assert 'Accept invitation' in client.get('/my/manager').text
    assert 'Invitation accepted.' in post(client, f'/my/manager/invitations/{invitation_id}/respond', decision='accept').text
    with store.read_db() as db:
        team = db.execute('SELECT * FROM teams WHERE id=?', (team_id,)).fetchone()
        profile = db.execute('SELECT * FROM players WHERE user_id=?', (manager_id,)).fetchone()
        assert team['manager_id'] == manager_id
        assert profile['owner_team_id'] == team_id
        assert profile['is_manager_player'] == 1
        assert db.execute('SELECT COUNT(*) FROM users WHERE username=\'knight\'').fetchone()[0] == 1
    assert 'Not transferable' in client.get('/players').text
    with pytest.raises(ValueError, match='cannot be listed'):
        store.create_auction(profile['id'], 20, 24)
    logout(client)
    post(client, '/login', username='knight', password='p4ssword!AB12')
    assert 'King’s Guard' in client.get('/dashboard').text
    assert 'Manager · Active' in re.sub(r'<[^>]+>', '', client.get('/dashboard').text)


def test_manager_automatically_plays_and_follows_reassignment(client):
    m1 = store.create_account('alice', 'password123!', 'manager')
    m2 = store.create_account('bob', 'password123!', 'manager')
    a, b = store.create_team('Alpha Team'), store.create_team('Bravo Team')
    store.assign_manager(a, m1)
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM players WHERE user_id=? AND is_manager_player=1', (m1,)).fetchone()[0] == 1
    store.assign_manager(a, m1)  # Saving the same assignment doesn't duplicate the player
    with pytest.raises(ValueError, match='already runs another team'):
        store.assign_manager(b, m1)
    store.assign_manager(a, None)
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE user_id=?', (m1,)).fetchone()[0] is None
    store.assign_manager(b, m1)
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE user_id=?', (m1,)).fetchone()[0] == b
        assert db.execute('SELECT COUNT(*) FROM players WHERE user_id=?', (m1,)).fetchone()[0] == 1
    store.assign_manager(b, m2)
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE user_id=?', (m1,)).fetchone()[0] is None
        new_profile = db.execute('SELECT owner_team_id,is_manager_player FROM players WHERE user_id=?', (m2,)).fetchone()
        assert new_profile['owner_team_id'] == b
        assert new_profile['is_manager_player'] == 1
    # Unassigned managers remain non-transferable, even if they change teams.
    with store.read_db() as db:
        previous_profile_id = db.execute('SELECT id FROM players WHERE user_id=?', (m1,)).fetchone()[0]
    with pytest.raises(ValueError, match='cannot be listed'):
        store.create_auction(previous_profile_id, 30, 12)


def test_admin_links_player_registration_to_profile(client):
    seed_admin()
    register(client, 'alice', 'player')
    with store.read_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
    logout(client)
    login_admin(client)
    assert 'alice' in client.get('/admin').text
    r = post(client, '/admin/players', name='Alice Silva', club='Chess Club', rating='1800', user_id=str(uid))
    assert 'Added Alice Silva' in r.text
    assert 'Alice Silva' in client.get('/players').text
    assert 'already has a chess profile' in post(client, '/admin/players', name='Alice Double', user_id=str(uid)).text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM players WHERE user_id=?', (uid,)).fetchone()[0] == 1
    logout(client)
    post(client, '/login', username='alice', password='p4ssword!AB12')
    assert 'Alice Silva' in client.get('/dashboard').text
    assert post(client, '/auctions/1/bid', amount='10').status_code == 403


def test_unassigned_manager_cannot_bid(client):
    seed_admin()
    pid = store.create_player('Bishop Player')
    auction = store.create_auction(pid, 40, 24)
    register(client, 'alice')
    assert 'administrator must assign' in post(client, f'/auctions/{auction}/bid', amount='50').text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM bids').fetchone()[0] == 0


def test_auctions_budget_and_seller_payment(client):
    alice, at = new_team('alice', 'Team Alpha')
    bob, bt = new_team('bob', 'Team Beta')
    p1 = store.create_player('Chess Player One')
    p2 = store.create_player('Chess Player Two')
    a1 = store.create_auction(p1, 10, 24)
    a2 = store.create_auction(p2, 10, 24)
    store.place_bid(a1, at, 700)
    with pytest.raises(ValueError, match='300 credits'):
        store.place_bid(a2, at, 400)
    store.place_bid(a1, bt, 750)
    store.place_bid(a2, at, 400)
    expire(a2)
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?', (p2,)).fetchone()[0] == at
        assert db.execute('SELECT budget FROM teams WHERE id=?', (at,)).fetchone()[0] == 600
    a3 = store.create_auction(p2, 10, 24)
    store.place_bid(a3, bt, 200)
    expire(a3)
    with store.read_db() as db:
        assert db.execute('SELECT budget FROM teams WHERE id=?', (at,)).fetchone()[0] == 800
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?', (p2,)).fetchone()[0] == bt


def test_duplicate_names_unsold_and_csrf(client):
    assert client.post('/register', data={'username':'x','role':'manager'}).status_code == 403
    register(client, 'alice')
    assert client.post('/logout', data={'csrf':'not-real'}).status_code == 403
    with pytest.raises(ValueError, match='already taken'):
        store.create_account('ALICE', 'password123!', 'player')
    store.create_team('Team Knights')
    with pytest.raises(ValueError, match='already taken'):
        store.create_team('TEAM KNIGHTS')
    player = store.create_player('Independent Player')
    auction = store.create_auction(player, 10, 24)
    with pytest.raises(ValueError, match='already listed'):
        store.create_auction(player, 15, 12)
    expire(auction)
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?', (player,)).fetchone()[0] is None


def test_old_database_auto_migration(monkeypatch, tmp_path):
    """Real v1 schema with users, teams, players, bids and auctions retains all IDs."""
    filename = tmp_path / 'existing.sqlite3'
    db = sqlite3.connect(filename)
    db.executescript('''
      CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','manager')), created_at TEXT NOT NULL);
      CREATE TABLE teams (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        manager_id INTEGER NOT NULL UNIQUE REFERENCES users(id), budget INTEGER NOT NULL DEFAULT 1000 CHECK(budget>=0),
        created_at TEXT NOT NULL);
      CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,club TEXT NOT NULL DEFAULT '',
        rating INTEGER,points INTEGER NOT NULL DEFAULT 0,owner_team_id INTEGER REFERENCES teams(id),created_at TEXT NOT NULL);
      CREATE TABLE auctions (id INTEGER PRIMARY KEY AUTOINCREMENT,player_id INTEGER NOT NULL REFERENCES players(id),
        seller_team_id INTEGER REFERENCES teams(id),starting_price INTEGER NOT NULL CHECK(starting_price>0),
        ends_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
        winner_team_id INTEGER REFERENCES teams(id),final_price INTEGER,created_at TEXT NOT NULL,closed_at TEXT);
      CREATE TABLE bids (id INTEGER PRIMARY KEY AUTOINCREMENT,auction_id INTEGER NOT NULL REFERENCES auctions(id),
        team_id INTEGER NOT NULL REFERENCES teams(id),amount INTEGER NOT NULL CHECK(amount>0),placed_at TEXT NOT NULL);
      INSERT INTO users VALUES(1,'oldmanager','x','manager','2026-01-01');
      INSERT INTO teams VALUES(1,'Legacy Squad',1,960,'2026-01-01');
      INSERT INTO players VALUES(1,'Legacy Chess Player','',NULL,3,1,'2026-01-01');
      INSERT INTO auctions VALUES(1,1,1,50,'2028-01-01','open',NULL,NULL,'2026-01-01',NULL);
      INSERT INTO bids VALUES(1,1,1,51,'2026-01-01');
    ''')
    db.close()
    monkeypatch.setattr(store, 'DB_PATH', filename)
    store.init_db()
    store.init_db()  # idempotent
    with store.read_db() as migrated:
        assert migrated.execute('PRAGMA foreign_key_check').fetchall() == []
        assert migrated.execute('SELECT name,budget,manager_id FROM teams').fetchone()[:] == ('Legacy Squad',960,1)
        assert migrated.execute('SELECT player_id FROM auctions WHERE id=1').fetchone()[0] == 1
        assert migrated.execute('SELECT amount FROM bids WHERE id=1').fetchone()[0] == 51
        assert migrated.execute('SELECT COUNT(*) FROM players WHERE user_id=1 AND is_manager_player=1').fetchone()[0] == 1
        assert migrated.execute('SELECT owner_team_id FROM players WHERE user_id=1').fetchone()[0] == 1
        assert migrated.execute('SELECT COUNT(*) FROM players').fetchone()[0] == 2
    assert filename.with_name(filename.name + '.pre-v3.bak').exists()
    new_player = store.create_account('newplayer', 'password123!', 'player')
    new_team = store.create_team('New Empty Team')
    assert new_player != 1 and new_team != 1
    assert store.create_player('New Chess Member', user_id=new_player)


def test_existing_v2_manager_assignment_gains_playing_eligibility_on_upgrade(monkeypatch, tmp_path):
    """A manager previously assigned without checking 'make player' is now eligible."""
    filename = tmp_path / 'existing_v2.sqlite3'
    monkeypatch.setattr(store, 'DB_PATH', filename)
    store.init_db()
    m1 = store.create_account('oldmanager', 'password123!', 'manager')
    m2 = store.create_account('othermanager', 'password123!', 'manager')
    t1 = store.create_team('Already Assigned')
    t2 = store.create_team('Unassigned Team')
    # Simulate the old v2 assignment, with no corresponding chess profile.
    with store.transaction() as db:
        db.execute('UPDATE teams SET manager_id=? WHERE id=?', (m1, t1))
    store.init_db()
    store.init_db()
    with store.read_db() as db:
        profile = db.execute('SELECT * FROM players WHERE user_id=?', (m1,)).fetchone()
        assert profile['owner_team_id'] == t1
        assert profile['is_manager_player'] == 1
        assert db.execute('SELECT COUNT(*) FROM players WHERE user_id=?', (m1,)).fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM players WHERE user_id=?', (m2,)).fetchone()[0] == 0
        assert db.execute('SELECT manager_id FROM teams WHERE id=?', (t2,)).fetchone()[0] is None
    with pytest.raises(ValueError, match='cannot be listed'):
        store.create_auction(profile['id'], 20, 24)
    assert filename.with_name(filename.name + '.pre-v3.bak').exists()
