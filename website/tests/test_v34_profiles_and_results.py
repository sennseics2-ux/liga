"""Current affiliations and final match/round outcomes use recorded league data."""
import re
import database as store
import league_seasons as seasons
from test_league import client
from test_v31_manager_and_lineup_privacy import arranged_match


def test_current_affiliation_uses_correct_role_and_lisbon_join_date(client):
    _,_,_,_,teams,managers,rosters=arranged_match()
    with store.transaction() as db:
        db.execute("UPDATE manager_terms SET started_at='2026-01-07T12:00:00+00:00' WHERE manager_id=? AND ended_at IS NULL",(managers[0],))
        db.execute("UPDATE player_team_terms SET started_at='2026-06-30T23:30:00+00:00' WHERE player_id=? AND ended_at IS NULL",(rosters[0][0],))
    player=client.get('/users/manager_home').text
    captain=client.get('/users/manager_home/manager').text
    player_line=re.search(r'<p class="profile-affiliation">(.*?)</p>',player,re.S)[1]
    captain_line=re.search(r'<p class="profile-affiliation">(.*?)</p>',captain,re.S)[1]
    assert 'Player for' in player_line and '01.07.2026' in player_line
    assert 'Captain for' in captain_line and '07.01.2026' in captain_line
    assert f'href="/teams/{teams[0]}"' in captain_line and 'Team home' in captain_line
    store.assign_manager(teams[0],None)
    assert 'class="profile-affiliation"' not in client.get('/users/manager_home/manager').text
    assert 'class="profile-affiliation"' not in client.get('/users/manager_home').text


def test_only_final_match_results_get_winner_or_draw_and_completed_round(client):
    admin,season,_,match,_,_,_=arranged_match()
    with store.transaction() as db:
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-01T12:00:00+00:00' WHERE id=?",(match,))
        games=[row[0] for row in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(match,))]
    def calendar():
        with store.read_db() as db:return seasons.calendar_view(db,str(season))
    assert calendar()['matches'][0]['outcome'] is None
    store.update_game_result(games[0],'1-0',actor_id=admin,reason='Partial result')
    assert calendar()['matches'][0]['outcome'] is None
    assert not calendar()['schedule_rounds'][0]['completed']
    for game,result in zip(games[1:],['0-1','1/2-1/2','1-0']):
        store.update_game_result(game,result,actor_id=admin,reason='Completed match')
    result=calendar()
    assert result['matches'][0]['outcome']=='home'
    assert result['schedule_rounds'][0]['completed']
    assert not result['schedule_rounds'][1]['completed']
    page=client.get('/seasons',params={'season':season}).text
    assert page.count('fixture-team-winner')==1 and 'season-metrics' not in page
    assert 'data-i18n="View season"' not in page
    assert 'schedule-round-complete' in page and f'href="/matches/{match}"' in page
    # Alternating board colours: two white wins and two black wins score 4–0.
    store.update_game_result(games[2],'1-0',actor_id=admin,reason='Correct board result')
    store.update_game_result(games[3],'0-1',actor_id=admin,reason='Correct board result')
    assert calendar()['matches'][0]['outcome']=='home'
    for game in games:store.update_game_result(game,'1/2-1/2',actor_id=admin,reason='Drawn match')
    assert calendar()['matches'][0]['outcome']=='draw'
    page=client.get('/seasons',params={'season':season}).text
    assert page.count('fixture-team-draw')==2 and 'fixture-team-winner' not in page


def test_unpublished_schedule_does_not_expose_fixture_dates(client):
    _,season,_,_,_,_,_=arranged_match()
    with store.transaction() as db:db.execute("UPDATE seasons SET status='draft' WHERE id=?",(season,))
    with store.read_db() as db:
        public=seasons.calendar_view(db,str(season))
        admin=seasons.calendar_view(db,str(season),True)
    assert public['matches']==[] and all(r['first_date'] is None for r in public['schedule_rounds'])
    assert admin['schedule_rounds'][0]['first_date']
