"""Fixture, result accounting, permissions and optional PGN replay regression tests."""
from datetime import datetime, timezone
import sqlite3

import pytest
from test_league import client, seed_admin, login_admin, post, new_team, logout, token
import database as store


def players():
    return (store.create_player('Ada White'), store.create_player('Ben Black'))


def test_game_schema_upgrade_retains_existing_data(client):
    store.create_team('Longstanding Knights')
    store.init_db()
    store.init_db()
    with store.read_db() as db:
        assert db.execute("SELECT count(*) FROM teams WHERE name='Longstanding Knights'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='games'").fetchone()[0] == 1
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_admin_only_create_game_and_fantasy_awards_are_correctable(client):
    white, black = players()
    assert client.post('/admin/games', data={}).status_code == 401
    seed_admin()
    login_admin(client)
    assert 'Games' in client.get('/').text
    assert 'Schedule a match' in client.get('/admin').text
    result = post(client, '/admin/games', white_player_id=str(white), black_player_id=str(black), scheduled_at='2026-04-18T15:00', event_name='Club open', round_label='R1')
    assert result.status_code == 200
    assert 'Ada White' in result.text and 'Ben Black' in result.text
    with store.read_db() as db:
        gid = db.execute('SELECT id FROM games').fetchone()[0]
    assert 'Club open' in client.get('/games').text
    post(client,f'/admin/games/{gid}/result',result='1-0')
    post(client,f'/admin/games/{gid}/result',result='1-0')
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?',(white,)).fetchone()[0] == 3
        assert db.execute('SELECT white_award,black_award FROM games WHERE id=?',(gid,)).fetchone()[:] == (3,0)
    post(client,f'/admin/games/{gid}/result',result='1/2-1/2')
    with store.read_db() as db:
        assert [db.execute('SELECT points FROM players WHERE id=?',(i,)).fetchone()[0] for i in (white,black)] == [1,1]
    post(client,f'/admin/games/{gid}/result',result='*')
    with store.read_db() as db:
        assert [db.execute('SELECT points FROM players WHERE id=?',(i,)).fetchone()[0] for i in (white,black)] == [0,0]
    assert 'Not played' in client.get('/games').text
    logout(client)
    assert client.post(f'/admin/games/{gid}/result',data={}).status_code == 401


def test_invalid_match_creation_does_not_write(client):
    a,b=players()
    seed_admin(); login_admin(client)
    assert 'cannot play themselves' in post(client,'/admin/games',white_player_id=str(a),black_player_id=str(a),scheduled_at='2026-01-12T10:00').text
    assert 'valid match date' in post(client,'/admin/games',white_player_id=str(a),black_player_id=str(b),scheduled_at='bad-date').text
    assert 'Both players' in post(client,'/admin/games',white_player_id='9999',black_player_id=str(b),scheduled_at='2026-01-12T10:00').text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM games').fetchone()[0] == 0


def test_fixtures_show_on_player_profiles_and_team_season(client):
    user_id, team = new_team('captain', 'Knights')
    with store.read_db() as db:
        pid = db.execute('SELECT id FROM players WHERE user_id=?',(user_id,)).fetchone()[0]
    # This fixture represents a manager who joined before the July match.
    with store.transaction() as db:
        db.execute('UPDATE player_team_terms SET started_at=? WHERE player_id=?',
                   ('2026-01-01T00:00:00+00:00', pid))
    opponent = store.create_player('Opponent')
    gid = store.create_game(pid, opponent, '2026-07-10T15:45:00+00:00', 'Tournament', '5')
    store.update_game_result(gid, '1-0')
    assert 'Tournament' in client.get('/games').text
    assert '/games/' in client.get(f'/users/{user_id}').text
    assert f'/games/{gid}' in client.get(f'/teams/{team}?season=2026').text
    with store.read_db() as db:
        record=db.execute('SELECT white_team_id,black_team_id FROM games WHERE id=?',(gid,)).fetchone()
        assert record['white_team_id'] == team
        assert record['black_team_id'] is None


def test_pgn_upload_rejected_when_not_admin_or_invalid_file(client):
    a,b=players()
    gid=store.create_game(a,b,'2026-03-15T12:00')
    before=token(client,'/register')
    assert client.post(f'/admin/games/{gid}/pgn',data={'csrf':before},files={'pgn':('x.pgn',b'[Result "1-0"]\n\n1. e4 e5 1-0')}).status_code==401
    seed_admin(); login_admin(client)
    response=client.post(f'/admin/games/{gid}/pgn',data={'csrf':token(client,'/')},files={'pgn':('attack.exe',b'nothing')},follow_redirects=True)
    assert 'Choose a .pgn file.' in response.text
    response=client.post(f'/admin/games/{gid}/pgn',data={'csrf':token(client,'/')},files={'pgn':('huge.pgn',b'a'*(256*1024+5))},follow_redirects=True)
    assert '256 KB' in response.text
    with store.read_db() as db:
        assert db.execute('SELECT pgn_text FROM games WHERE id=?',(gid,)).fetchone()[0] is None
    assert client.get(f'/games/{gid}/pgn').status_code == 404


def test_genuine_pgn_validation_and_replay_if_dependency_available(client):
    pytest.importorskip('chess.pgn')
    a,b=players()
    gid=store.create_game(a,b,'2026-03-15T12:00')
    seed_admin(); login_admin(client)
    sample=b'''[Event "Test"]\n[Site "Local"]\n[White "Ada White"]\n[Black "Ben Black"]\n[Result "1-0"]\n\n1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0\n'''
    resp=client.post(f'/admin/games/{gid}/pgn',data={'csrf':token(client,'/')},files={'pgn':('mate.pgn',sample)},follow_redirects=True)
    assert 'PGN attached' in resp.text
    assert 'Replay the game' in resp.text
    assert 'chess-replay.js' in resp.text
    assert 'Qxf7#' in resp.text
    assert client.get(f'/games/{gid}/pgn').content == sample
    with store.read_db() as db:
        assert db.execute('SELECT result FROM games WHERE id=?',(gid,)).fetchone()[0] == '1-0'
        assert db.execute('SELECT points FROM players WHERE id=?',(a,)).fetchone()[0] == 3
    # Re-upload does not award the win twice.
    client.post(f'/admin/games/{gid}/pgn',data={'csrf':token(client,'/')},files={'pgn':('mate.pgn',sample)})
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?',(a,)).fetchone()[0] == 3
    # Reject inconsistent game result; keep PGN and points unchanged.
    resp=post(client,f'/admin/games/{gid}/result',result='0-1')
    assert 'declares 1-0' in resp.text
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?',(a,)).fetchone()[0] == 3
    invalid=b'[Result "1-0"]\n\n1. e4 e5 2. Qh5 Qh3 1-0'
    resp=client.post(f'/admin/games/{gid}/pgn',data={'csrf':token(client,'/')},files={'pgn':('broken.pgn',invalid)},follow_redirects=True)
    assert 'Invalid chess moves' in resp.text
    with store.read_db() as db:
        assert db.execute('SELECT points FROM players WHERE id=?',(a,)).fetchone()[0] == 3


def test_offline_replay_template_and_download_route_without_external_scripts(client, monkeypatch):
    from unittest.mock import patch
    a,b=players()
    gid=store.create_game(a,b,'2026-02-15T12:00')
    sample='[Event "Test"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'
    with store.transaction() as db:
        db.execute('UPDATE games SET result=?,pgn_text=?,white_award=3 WHERE id=?',('1-0',sample,gid))
    seed_admin(); login_admin(client)
    start='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    e4='rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
    e5='rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2'
    parsed={'positions':[start,e4,e5], 'moves':[{'san':'e4','uci':'e2e4','ply':1,'move_number':1,'color':'white'}, {'san':'e5','uci':'e7e5','ply':2,'move_number':1,'color':'black'}], 'result':'1-0', 'headers':{}}
    with patch('game_logic.parse_pgn', return_value=parsed):
        r=client.get(f'/games/{gid}')
    assert r.status_code==200
    assert 'data-chess-replay' in r.text
    assert 'chess-replay.js' in r.text
    assert '"e2e4"' in r.text
    assert 'cdn.' not in r.text
    assert client.get(f'/games/{gid}/pgn').text==sample


def test_upgrade_real_v8_database_preserves_teams_accounts_and_auctions(client, tmp_path, monkeypatch, legacy_database_factory):
    import shutil
    original=legacy_database_factory(8)
    db_path=tmp_path/'v8-copy.sqlite3'
    shutil.copyfile(original,db_path)
    monkeypatch.setattr(store,'DB_PATH',db_path)
    with store.read_db() as db:
        counts=[db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('users','teams','players','auctions','bids','player_team_terms')]
    store.init_db()
    assert db_path.with_name('v8-copy.sqlite3.pre-v9.bak').exists()
    with store.read_db() as db:
        after=[db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('users','teams','players','auctions','bids','player_team_terms')]
        assert counts==after
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT COUNT(*) FROM games').fetchone()[0]==0
