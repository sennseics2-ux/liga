"""Season selection, unpublished schedule privacy, and board-point scoreboards."""
from datetime import datetime, timezone
import database as store
import league_seasons as seasons
from test_league import client, post
from test_v25_seasons import setup, PASSWORD


def test_current_placeholder_is_read_only_and_not_replaced_by_past_seasons(client, monkeypatch):
    monkeypatch.setattr(store,'now_utc',lambda:datetime(2026,10,10,tzinfo=timezone.utc))
    admin, current, rounds, match, teams, managers, rosters=setup()
    with store.transaction() as db:
        db.execute("UPDATE seasons SET name='2025-2026',start_year=2025,status='published' WHERE id=?",(current,))
    page=client.get('/seasons')
    assert page.status_code==200
    assert '<h1 data-no-i18n>2026-2027</h1>' in page.text
    assert 'Schedule coming soon' in page.text
    assert 'class="fixture-card"' not in page.text
    assert '2025-2026</option>' in page.text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM seasons').fetchone()[0]==1
    past=client.get(f'/seasons?season={current}')
    assert '<h1 data-no-i18n>2025-2026</h1>' in past.text
    assert f'href="/matches/{match}"' in past.text
    assert client.get('/seasons?season=999999').status_code==404


def test_current_future_start_selected_and_draft_fixture_hidden(client,monkeypatch):
    monkeypatch.setattr(store,'now_utc',lambda:datetime(2026,10,10,tzinfo=timezone.utc))
    admin, season, rounds, match, teams, managers, rosters=setup()
    with store.transaction() as db:
        db.execute("UPDATE seasons SET start_date='2026-11-01' WHERE id=?",(season,))
    response=client.get('/seasons')
    assert '<h1 data-no-i18n>2026-2027</h1>' in response.text
    assert 'Not started' in response.text
    assert 'Club hall' not in response.text
    assert client.get(f'/matches/{match}').status_code==404
    post(client,'/login',username='commissioner',password='adminpass123!')
    assert 'Draft preview.' in client.get('/seasons').text
    assert 'Club hall' in client.get('/seasons').text
    monkeypatch.setattr(store,'now_utc',lambda:datetime(2027,2,10,tzinfo=timezone.utc))
    assert '<h1 data-no-i18n>2026-2027</h1>' in client.get('/seasons').text


def test_match_scores_follow_teams_across_alternating_colours_and_draws(client):
    admin, season, rounds, match, teams, managers, rosters=setup()
    seasons.submit_lineup(match,managers[0],rosters[0])
    seasons.submit_lineup(match,managers[1],rosters[1])
    with store.transaction() as db:
        db.execute("UPDATE seasons SET status='published' WHERE id=?",(season,))
        games=[r[0] for r in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(match,))]
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-01T18:00:00+00:00' WHERE id=?",(match,))
        db.execute("UPDATE games SET scheduled_at='2026-06-01T18:00:00+00:00' WHERE id IN (SELECT game_id FROM match_games WHERE match_id=?)",(match,))
    with store.read_db() as db:
        empty=seasons.match_rows(db,season)[0]
        assert (empty['home_score'],empty['away_score'],empty['finished_boards'])==('—','—',0)
    for game,result in zip(games[:3],['1-0','0-1','1/2-1/2']):
        store.update_game_result(game,result,actor_id=admin,reason='Test official result')
    with store.read_db() as db:
        partial=seasons.match_rows(db,season)[0]
        assert (partial['home_score'],partial['away_score'],partial['result_status'])==('2½','½','Partial results')
    store.update_game_result(games[3],'1-0',actor_id=admin,reason='Final board result')
    page=client.get(f'/matches/{match}')
    assert page.status_code==200
    assert 'scoreboard-numbers' in page.text
    assert '<span>2½</span>' in page.text and '<span>1½</span>' in page.text
    assert page.text.count('class="match-board-row board-result-card"')==4
    assert page.text.count('class="match-board-row board-result-card"')==4
    assert 'Lineups &amp; results' in page.text
    assert 'Submitted lineups' not in page.text
    assert 'View game' not in page.text
    assert 'match-board-game-link' not in page.text
    # Scores follow home/away teams, even when colours alternate by board.
    import re
    rows=re.findall(r'<a class="match-board-row board-result-card"[^>]*>(.*?)</a>',page.text,re.S)
    scores=[re.search(r'<strong class="match-board-score" data-no-i18n>(.*?)</strong>',row,re.S).group(1) for row in rows]
    assert [re.sub(r'<[^>]+>','',score).strip() for score in scores]==['1 : 0','1 : 0','½ : ½','0 : 1']
    assert all(row.count('class="match-lineup-player"')==2 for row in rows)
    assert f'/seasons?season={season}' in page.text
    assert 'Completed' in page.text
    post(client,'/login',username='manager_home',password=PASSWORD)
    locked=client.get(f'/matches/{match}')
    assert 'Lineups are locked once' in locked.text
    assert 'name="player_1"' not in locked.text
