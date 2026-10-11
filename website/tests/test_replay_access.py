"""Public PGN access, custom starting-position metadata and replay regression tests."""

import pytest

import database as store
from test_league import client, post


SAMPLE = '[Event "Replay"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'
START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'


def recorded_game():
    white = store.create_player('Players')
    black = store.create_player('Teams')
    game_id = store.create_game(white, black, '2026-06-15T12:00:00+00:00', 'League replay')
    with store.transaction() as db:
        db.execute('UPDATE games SET pgn_text=? WHERE id=?', (SAMPLE, game_id))
    return game_id


def test_anonymous_visitors_can_replay_and_download_pgn(client):
    game_id = recorded_game()
    response = client.get(f'/games/{game_id}')
    assert response.status_code == 200
    assert 'replay-data' in response.text and 'data-chess-replay' in response.text
    assert '"e2e4"' in response.text and START in response.text
    assert 'Log in to replay' not in response.text
    assert 'Download PGN' in response.text
    assert 'data-piece-style' in response.text
    download = client.get(f'/games/{game_id}/pgn')
    assert download.status_code == 200 and download.text == SAMPLE
    assert 'Replay' in client.get('/games').text


def test_regular_authenticated_member_can_replay_and_download_pgn(client):
    pytest.importorskip('chess.pgn')
    game_id = recorded_game()
    store.create_account('viewer', 'password123!', 'player')
    post(client, '/login', username='viewer', password='password123!')
    response = client.get(f'/games/{game_id}')
    assert response.status_code == 200
    assert 'replay-data' in response.text and 'chess-replay.js' in response.text
    assert '"e2e4"' in response.text
    assert 'role="grid"' in response.text
    assert 'aria-describedby="replay-position-description"' in response.text
    assert 'data-speed' in response.text and 'data-action="flip"' in response.text
    assert 'Log in to replay this game' not in response.text
    download = client.get(f'/games/{game_id}/pgn')
    assert download.status_code == 200
    assert download.text == SAMPLE
    assert download.headers['cache-control'].startswith('private')


def test_no_pgn_summary_explains_absence_without_login_requirement(client):
    white = store.create_player('Ada')
    black = store.create_player('Ben')
    game_id = store.create_game(white, black, '2026-06-15T12:00')
    response = client.get(f'/games/{game_id}')
    assert 'No PGN attached yet' in response.text
    assert 'Log in to replay this game' not in response.text


def test_black_fen_start_uses_position_color_and_fullmove_number():
    pytest.importorskip('chess.pgn')
    from game_logic import parse_pgn
    pgn = f'[SetUp "1"]\n[FEN "{START} b KQkq - 0 10"]\n[Result "*"]\n\n10... e5 11. e4 *\n'
    replay = parse_pgn(pgn)
    assert [(move['san'], move['color'], move['move_number'], move['ply']) for move in replay['moves']] == [
        ('e5', 'black', 10, 1), ('e4', 'white', 11, 2)]
    assert replay['positions'][0].split()[1:] == ['b', 'KQkq', '-', '0', '10']
    assert replay['positions'][-1].split()[1] == 'b'


def test_white_fen_start_preserves_noninitial_fullmove_number():
    pytest.importorskip('chess.pgn')
    from game_logic import parse_pgn
    pgn = f'[SetUp "1"]\n[FEN "{START} w KQkq - 0 23"]\n[Result "*"]\n\n23. e4 e5 *\n'
    replay = parse_pgn(pgn)
    assert [(move['color'], move['move_number']) for move in replay['moves']] == [('white', 23), ('black', 23)]
    assert replay['positions'][-1].split()[-1] == '24'
