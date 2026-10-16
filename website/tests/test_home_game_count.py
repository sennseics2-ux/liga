"""The home game count measures completed games and respects match privacy."""
import re
from datetime import timedelta
import database as store
from test_league import client
from test_v31_manager_and_lineup_privacy import arranged_match


def game_count(client):
    html=client.get('/').text
    strip=html.split('class="stats-strip"',1)[1].split('</section>',1)[0]
    assert 'GAMES PLAYED' in strip and 'ACTIVE TRANSFERS' not in strip
    return int(re.findall(r'<strong>(.*?)</strong>',strip)[2])


def test_count_completed_games_across_seasons_and_exclude_unplayed(client):
    assert game_count(client)==0
    white=store.create_player('White Count')
    black=store.create_player('Black Count')
    for year,result in [(2024,'1-0'),(2025,'0-1'),(2026,'1/2-1/2'),(2025,'*'),(2030,'*')]:
        game=store.create_game(white,black,f'{year}-01-10T12:00:00+00:00')
        if result!='*':store.update_game_result(game,result)
    assert game_count(client)==3


def test_completed_private_match_boards_wait_until_kickoff(client):
    _,_,_,match,_,_,_=arranged_match()
    with store.transaction() as db:
        db.execute('UPDATE team_matches SET scheduled_at=? WHERE id=?',(store.iso(store.now_utc()+timedelta(days=1)),match))
        db.execute("UPDATE games SET result='1-0' WHERE id IN (SELECT game_id FROM match_games WHERE match_id=?)",(match,))
    assert game_count(client)==0
    with store.transaction() as db:
        db.execute('UPDATE team_matches SET scheduled_at=? WHERE id=?',(store.iso(store.now_utc()-timedelta(days=1)),match))
    assert game_count(client)==4
