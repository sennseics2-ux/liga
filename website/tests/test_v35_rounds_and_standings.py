"""League points come exclusively from selected-season four-board match results."""
import re
from datetime import timedelta
import database as store
from league_standings import season_table
from test_league import client
from test_team_honours import seed_podium


def test_season_table_uses_3_1_0_and_ignores_player_points_budgets_and_transfers(client):
    season,teams,matches,_=seed_podium()
    with store.transaction() as db:
        db.execute('UPDATE players SET points=999999,owner_team_id=?',(teams[3],))
        db.execute('UPDATE teams SET budget=900000 WHERE id=?',(teams[3],))
    with store.read_db() as db:rows=season_table(db,season)
    assert [(r['id'],r['points'],r['played'],r['wins'],r['losses']) for r in rows]==[(teams[i],9-3*i,3,3-i,i) for i in range(4)]
    with store.transaction() as db:
        db.execute("UPDATE games SET result='1/2-1/2' WHERE id IN (SELECT game_id FROM match_games WHERE match_id=?)",(matches[0],))
    with store.read_db() as db:rows={r['id']:r for r in season_table(db,season)}
    assert rows[teams[0]]['points']==7 and rows[teams[3]]['points']==1
    assert rows[teams[0]]['draws']==rows[teams[3]]['draws']==1
    assert client.get(f'/standings?season={season}').status_code==200
    assert client.get('/standings?season=999999').status_code==404
    # Current table must not include points earned in 2024–2025.
    assert '>999999<' not in client.get('/standings').text
    assert 'Most league points' in client.get('/teams').text


def test_incomplete_unpublished_and_future_matches_do_not_earn_league_points(client):
    season,teams,matches,_=seed_podium()
    with store.transaction() as db:
        db.execute("UPDATE games SET result='*' WHERE id=(SELECT game_id FROM match_games WHERE match_id=? LIMIT 1)",(matches[0],))
        db.execute('UPDATE team_matches SET scheduled_at=? WHERE id=?',(store.iso(store.now_utc()+timedelta(days=10)),matches[1]))
    with store.read_db() as db:rows={r['id']:r for r in season_table(db,season)}
    assert rows[teams[0]]['played']==2 and rows[teams[0]]['points']==6
    assert rows[teams[1]]['played']==2 and rows[teams[1]]['points']==3
    with store.transaction() as db:db.execute("UPDATE seasons SET status='draft' WHERE id=?",(season,))
    with store.read_db() as db:assert season_table(db,season)==[]


def test_round_filter_and_home_away_heading(client):
    season,_,_,_=seed_podium()
    page=client.get(f'/seasons?season={season}&round=2')
    assert page.status_code==200
    assert 'id="round-2"' in page.text and 'id="round-1"' not in page.text
    assert page.text.count('class="fixture-card"')==2
    label=re.findall(r'class="fixture-match-label">(.*?)</strong>',page.text,re.S)[0]
    assert label.index('Podium Team 1') < label.index('vs') < label.index('Podium Team 3')
    assert client.get(f'/seasons?season={season}&round=all').text.count('class="fixture-card"')==6
    for invalid in ('0','4','abc','-1'):assert client.get(f'/seasons?season={season}&round={invalid}').status_code==400
    for path in ('/players','/teams','/users/unknown','/admin'):
        assert 'FANTASY POINTS' not in client.get(path).text
