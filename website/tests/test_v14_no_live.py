"""Regression tests: removing online games must retain normal league games/data."""
from pathlib import Path

import database as store
from test_league import client

ROOT = Path(__file__).resolve().parents[1]


def test_online_chess_routes_and_assets_are_removed(client):
    for url in ('/live', '/live/1', '/live/1/state', '/live/invitations/count'):
        assert client.get(url).status_code == 404, url
    assert client.post('/live/challenge', data={}).status_code == 404
    assert client.post('/live/1/move', data={}).status_code == 404
    assert client.post('/live/1/action', data={}).status_code == 404
    for url in ('/static/live-chess.js', '/static/live-invitations.js'):
        assert client.get(url).status_code == 404
    for url in ('/', '/games', '/players', '/teams'):
        response = client.get(url)
        assert response.status_code == 200
        assert 'href="/live"' not in response.text
        assert 'live-invite-badge' not in response.text
        assert 'live-invitations.js' not in response.text


def test_new_database_has_fixtures_but_no_online_tables(client):
    with store.read_db() as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'games' in names
    assert 'live_games' not in names
    assert 'live_moves' not in names


def test_retains_dormant_legacy_online_records_with_regular_games(client):
    a = store.create_player('Historic White')
    b = store.create_player('Historic Black')
    gid = store.create_game(a, b, '2025-03-09T12:00:00+00:00')
    store.update_game_result(gid, '1-0')
    with store.transaction() as db:
        db.executescript('''
        CREATE TABLE live_games (id INTEGER PRIMARY KEY, game_id INTEGER NOT NULL,
                                 status TEXT NOT NULL);
        CREATE TABLE live_moves (id INTEGER PRIMARY KEY, live_id INTEGER NOT NULL,
                                 ply INTEGER NOT NULL, san TEXT NOT NULL);
        INSERT INTO live_games(id,game_id,status) VALUES(9, %d, 'finished');
        INSERT INTO live_moves(id,live_id,ply,san) VALUES(10,9,1,'e4');
        ''' % gid)
    store.init_db()
    with store.read_db() as db:
        assert db.execute('SELECT san FROM live_moves WHERE live_id=9').fetchone()[0] == 'e4'
        assert db.execute('SELECT status FROM live_games WHERE id=9').fetchone()[0] == 'finished'
        assert db.execute('SELECT result FROM games WHERE id=?', (gid,)).fetchone()[0] == '1-0'
        assert db.execute('SELECT points FROM players WHERE id=?', (a,)).fetchone()[0] == 3
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert client.get(f'/games/{gid}').status_code == 200
    store.update_game_result(gid, '1/2-1/2')
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?', (a,)).fetchone()[0] == 1
        assert db.execute('SELECT points FROM players WHERE id=?', (b,)).fetchone()[0] == 1


def test_live_engine_is_not_distributed_and_pgn_replay_is_kept():
    for file in ('live_engine.py', 'static/live-chess.js', 'static/live-invitations.js',
                 'templates/live_detail.html', 'templates/live_directory.html'):
        assert not (ROOT / file).exists(), file
    assert (ROOT / 'game_logic.py').exists()
    assert (ROOT / 'static/chess-replay.js').exists()
    assert '/games/{game_id}/pgn' in (ROOT / 'main.py').read_text()
