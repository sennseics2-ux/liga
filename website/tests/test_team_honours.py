"""Podium medals follow concluded season match results, not current squads."""
from datetime import datetime,timezone
import pytest
import database as store
from league_honours import season_honours
from test_league import client


def seed_podium():
    teams=[store.create_team(f'Podium Team {n+1}') for n in range(4)]
    players={team:[store.create_player(f'Team {team} Player {n}') for n in range(4)] for team in teams}
    with store.transaction() as db:
        season=db.execute("INSERT INTO seasons(name,start_year,start_date,end_date,round_count,status,created_at) VALUES('2024-2025',2024,'2024-09-01','2025-06-30',3,'published',?)",(store.iso(store.now_utc()),)).lastrowid
        fixtures=[]
        for number,pairs in enumerate([[(0,3),(1,2)],[(0,2),(3,1)],[(0,1),(2,3)]],1):
            rnd=db.execute('INSERT INTO season_rounds(season_id,number) VALUES(?,?)',(season,number)).lastrowid
            for home_index,away_index in pairs:
                home,away=teams[home_index],teams[away_index]
                when=f'2025-0{number}-10T14:00:00+00:00'
                match=db.execute('INSERT INTO team_matches(round_id,home_team_id,away_team_id,scheduled_at,location,created_at) VALUES(?,?,?,?,?,?)',(rnd,home,away,when,'Club hall',when)).lastrowid
                fixtures.append(match)
                winner=teams[min(home_index,away_index)]
                for board in range(1,5):
                    white,black=(home,away) if board%2 else (away,home)
                    game=db.execute('''INSERT INTO games(white_player_id,black_player_id,scheduled_at,result,white_team_id,black_team_id,attribution_confirmed,created_at)
                        VALUES(?,?,?,?,?,?,1,?)''',(players[white][board-1],players[black][board-1],when,'1-0' if white==winner else '0-1',white,black,when)).lastrowid
                    db.execute('INSERT INTO match_games(match_id,board,game_id) VALUES(?,?,?)',(match,board,game))
    return season,teams,fixtures,players


def test_three_medals_engrave_season_and_ignore_current_squads(client,monkeypatch):
    monkeypatch.setattr(store,'now_utc',lambda:datetime(2026,10,10,tzinfo=timezone.utc))
    season,teams,fixtures,players=seed_podium()
    with store.transaction() as db:
        db.execute('UPDATE players SET points=9999,owner_team_id=?',(teams[3],))
        db.execute('UPDATE teams SET budget=50000 WHERE id=?',(teams[3],))
    for team,rank,medal,points in zip(teams,[1,2,3,None],['gold','silver','bronze',None],[9,6,3,None]):
        with store.read_db() as db:
            honours=season_honours(db,team)
        page=client.get(f'/teams/{team}')
        assert page.status_code==200
        if rank:
            assert honours[0]['rank']==rank and honours[0]['points']==points
            assert f'medal-{medal}' in page.text
            assert '<span class="medal-season" data-no-i18n>2024-2025</span>' in page.text
            assert f'/seasons?season={season}' in page.text
        else:
            assert honours==[] and 'class="team-honours"' not in page.text


@pytest.mark.parametrize('fault',['draft','ongoing','missing_round','missing_board','unfinished','unconfirmed','wrong_team'])
def test_no_medals_until_season_and_every_match_are_complete(client,monkeypatch,fault):
    monkeypatch.setattr(store,'now_utc',lambda:datetime(2026,10,10,tzinfo=timezone.utc))
    season,teams,fixtures,players=seed_podium()
    with store.transaction() as db:
        game=db.execute('SELECT game_id FROM match_games LIMIT 1').fetchone()[0]
        if fault=='draft':db.execute("UPDATE seasons SET status='draft'")
        elif fault=='ongoing':db.execute("UPDATE seasons SET end_date='2026-10-10'")
        elif fault=='missing_round':db.execute('UPDATE seasons SET round_count=4')
        elif fault=='missing_board':db.execute('DELETE FROM match_games WHERE game_id=?',(game,))
        elif fault=='unfinished':db.execute("UPDATE games SET result='*' WHERE id=?",(game,))
        elif fault=='unconfirmed':db.execute('UPDATE games SET attribution_confirmed=0 WHERE id=?',(game,))
        elif fault=='wrong_team':db.execute('UPDATE games SET white_team_id=NULL WHERE id=?',(game,))
    with store.read_db() as db:
        assert all(season_honours(db,team)==[] for team in teams)


def test_two_two_match_earns_one_league_point_each(client):
    season,teams,fixtures,players=seed_podium()
    with store.transaction() as db:
        games=list(db.execute('SELECT g.id,g.white_team_id,mg.board FROM games g JOIN match_games mg ON mg.game_id=g.id WHERE mg.match_id=?',(fixtures[0],)))
        for game in games:
            winner=teams[0] if game['board']<=2 else teams[3]
            db.execute('UPDATE games SET result=? WHERE id=?',('1-0' if game['white_team_id']==winner else '0-1',game['id']))
    with store.read_db() as db:
        assert season_honours(db,teams[0])[0]['points']==7 # two wins and one draw
        assert season_honours(db,teams[1])[0]['points']==6


def test_equal_match_and_board_points_share_place(client):
    season,teams,fixtures,players=seed_podium()
    with store.transaction() as db:db.execute("UPDATE games SET result='1/2-1/2'")
    with store.read_db() as db:
        assert all(season_honours(db,team)[0]['rank']==1 for team in teams)
        assert all(season_honours(db,team)[0]['points']==3 for team in teams)


def test_two_wins_draw_and_loss_win_match_and_head_to_head_breaks_league_tie(client):
    season,teams,fixtures,players=seed_podium()
    with store.transaction() as db:
        # Team 1 now loses its first match; teams 1 and 2 both finish on six league points.
        for game in db.execute('SELECT g.id,g.white_team_id FROM games g JOIN match_games mg ON mg.game_id=g.id WHERE mg.match_id=?',(fixtures[0],)).fetchall():
            db.execute('UPDATE games SET result=? WHERE id=?',('1-0' if game['white_team_id']==teams[3] else '0-1',game['id']))
        # Team 2 wins 2.5-1.5 instead of 4-0: still three league points, fewer board points.
        for game in db.execute('SELECT g.id,g.white_team_id,mg.board FROM games g JOIN match_games mg ON mg.game_id=g.id WHERE mg.match_id=?',(fixtures[1],)).fetchall():
            if game['board']==3:result='1/2-1/2'
            else:
                winner=teams[1] if game['board']<=2 else teams[2]
                result='1-0' if game['white_team_id']==winner else '0-1'
            db.execute('UPDATE games SET result=? WHERE id=?',(result,game['id']))
    with store.read_db() as db:
        gold=season_honours(db,teams[0])[0];silver=season_honours(db,teams[1])[0]
        assert gold['points']==silver['points']==6
        assert gold['rank']==1 and silver['rank']==2


def test_tiebreak_order_uses_head_to_head_before_overall_boards():
    from league_honours import _standing_keys
    points={1:12,2:12,3:6,4:3}
    # Team 1 won both direct encounters; team 2's bigger overall board score cannot override them.
    keys=_standing_keys(points,{1:24,2:40,3:12,4:8},[(1,2,5,3),(2,1,2,6)])
    assert keys[1]>keys[2]
    # One win each: 8 games across two matches, team 1 ahead 5.5-2.5 overall.
    keys=_standing_keys(points,{1:24,2:40,3:12,4:8},[(1,2,8,0),(2,1,5,3)])
    assert keys[1]>keys[2]
    # Head-to-head match wins and board points equal: overall board score decides.
    keys=_standing_keys(points,{1:24,2:40,3:12,4:8},[(1,2,6,2),(2,1,6,2)])
    assert keys[2]>keys[1]
    keys=_standing_keys(points,{1:24,2:24,3:12,4:8},[(1,2,6,2),(2,1,6,2)])
    assert keys[1]==keys[2]


def test_three_way_tie_uses_all_tied_teams_and_is_independent_of_match_order():
    from league_honours import _standing_keys
    points={1:9,2:9,3:9,4:0}
    records=[(1,2,8,0),(2,3,6,2),(3,1,5,3)]
    keys=_standing_keys(points,{1:30,2:30,3:30,4:0},records)
    # One direct win each; their mini-table board totals are 11, 6, 7 half-points.
    assert keys[1]>keys[3]>keys[2]
    assert keys==_standing_keys(points,{1:30,2:30,3:30,4:0},list(reversed(records)))
