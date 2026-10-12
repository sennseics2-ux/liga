"""Cumulative round snapshots use only results and tie-breaks up to the cutoff."""
import re
import pytest
import database as store
from league_standings import season_table
from test_league import client
from test_team_honours import seed_podium


@pytest.mark.parametrize('round_number,points,played',[(1,[3,3,0,0],1),(2,[6,6,0,0],2),(3,[9,6,3,0],3)])
def test_cumulative_round_points_and_rankings(client,round_number,points,played):
    season,teams,_,_=seed_podium()
    with store.read_db() as db:
        rows=season_table(db,season,through_round=round_number)
    assert [r['points'] for r in rows]==points
    assert all(r['played']==played for r in rows)
    assert [r['board_points'] for r in rows]==[str(n//3*4) for n in points]
    assert [r['rank'] for r in rows]==([1,1,3,3] if round_number<3 else [1,2,3,4])
    page=client.get(f'/standings?season={season}&round={round_number}')
    assert page.status_code==200
    assert re.findall(r'class="score" data-no-i18n>(\d+)</span>',page.text)==list(map(str,points))
    assert f'Includes results from rounds 1–{round_number}.' in page.text
    assert f'value="{round_number}" selected' in page.text
    assert client.get(f'/standings?season={season}').text==client.get(f'/standings?season={season}&round=all').text


def test_later_results_do_not_change_earlier_points_or_tie_breaks(client):
    season,_,_,_=seed_podium()
    with store.read_db() as db:
        before=season_table(db,season,through_round=1)
        all_before=season_table(db,season)
    with store.transaction() as db:
        db.execute("""UPDATE games SET result='1/2-1/2' WHERE id IN (
            SELECT mg.game_id FROM match_games mg JOIN team_matches m ON m.id=mg.match_id
            JOIN season_rounds r ON r.id=m.round_id WHERE r.season_id=? AND r.number>1)""",(season,))
    with store.read_db() as db:
        assert season_table(db,season,through_round=1)==before
        assert season_table(db,season)!=all_before


def test_later_round_participants_and_invalid_filters(client):
    season,teams,_,_=seed_podium()
    new_team=store.create_team('Later debut')
    with store.transaction() as db:
        db.execute('UPDATE seasons SET round_count=4 WHERE id=?',(season,))
        rnd=db.execute('INSERT INTO season_rounds(season_id,number) VALUES(?,4)',(season,)).lastrowid
        db.execute("INSERT INTO team_matches(round_id,home_team_id,away_team_id,scheduled_at,location,created_at) VALUES(?,?,?,'2025-05-01T12:00:00+00:00','Club hall','2025-01-01')",(rnd,new_team,teams[0]))
    with store.read_db() as db:
        row=next(r for r in season_table(db,season,through_round=1) if r['id']==new_team)
        assert (row['points'],row['played'],row['board_points'])==(0,0,'0')
    for invalid in ('0','5','abc','-1','01','١','9'*5000):
        assert client.get(f'/standings?season={season}&round={invalid}').status_code==400
    assert client.get('/standings?season=999999&round=1').status_code==404


def test_board_points_include_partial_matches_and_half_point_draws(client):
    season,teams,matches,_=seed_podium()
    with store.transaction() as db:
        games=[r[0] for r in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(matches[0],))]
        for game,result in zip(games,['1-0','1/2-1/2','0-1','*']):
            db.execute('UPDATE games SET result=? WHERE id=?',(result,game))
    with store.read_db() as db:
        rows={r['id']:r for r in season_table(db,season,through_round=1)}
    assert (rows[teams[0]]['board_points'],rows[teams[3]]['board_points'])==('1.5','1.5')
    assert rows[teams[0]]['played']==rows[teams[3]]['played']==0
    assert rows[teams[0]]['points']==rows[teams[3]]['points']==0
    page=client.get(f'/standings?season={season}&round=1').text
    headers=re.findall(r'<th\b[^>]*>(.*?)</th>',page)
    assert headers==['RANK','TEAM','GAMES','WINS','DRAWS','LOSSES','POINTS','BOARD POINTS']
    assert 'data-label="CAPTAIN"' not in page
    assert 'data-label="GAMES"' in page
    assert page.index('data-label="POINTS"')<page.index('data-label="BOARD POINTS"')
    # Later rounds contribute only when they fall within the selected cutoff.
    with store.read_db() as db:
        through_two={r['id']:r for r in season_table(db,season,through_round=2)}
    assert through_two[teams[0]]['board_points']=='5.5'
