"""Complete season schedules, team pairings, and deadline-enforced lineups."""
from datetime import timedelta

import pytest
import database as store
import league_seasons as seasons
from test_league import client,seed_admin,post

PASSWORD='PlayerPassword123!'


def setup():
    seed_admin()
    with store.read_db() as db:
        admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    teams=[];managers=[];rosters=[]
    for suffix in ['home','away']:
        manager=store.create_account('manager_'+suffix,PASSWORD,'manager')
        team=store.create_team('Team '+suffix);store.assign_manager(team,manager)
        with store.read_db() as db:
            roster=[db.execute('SELECT id FROM players WHERE user_id=?',(manager,)).fetchone()[0]]
        for n in range(1,4):
            user=store.create_account(f'{suffix}_player_{n}',PASSWORD,'player')
            player=store.create_player(f'{suffix} Player {n}',user_id=user)
            with store.transaction() as db:
                db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team,player))
                store._start_player_term(db,player,team)
            roster.append(player)
        teams.append(team);managers.append(manager);rosters.append(roster)
    year=store.now_utc().year
    season=seasons.save_season(year,f'{year}-01-01',f'{year+1}-12-31',2,admin)
    with store.read_db() as db:
        rounds=[r[0] for r in db.execute('SELECT id FROM season_rounds WHERE season_id=? ORDER BY number',(season,))]
    when=store.iso(store.now_utc()+timedelta(days=10))
    match=seasons.save_match(rounds[0],*teams,when,'Club hall',admin)
    return admin,season,rounds,match,teams,managers,rosters


def test_schedule_requires_all_rounds_and_unique_pairings(client):
    admin,season,rounds,match,teams,managers,rosters=setup()
    with pytest.raises(ValueError,match='all rounds'):
        seasons.publish_season(season,admin)
    with pytest.raises(ValueError,match='one match'):
        seasons.save_match(rounds[0],*teams,store.iso(store.now_utc()+timedelta(days=10)),'Another hall',admin)
    with pytest.raises(ValueError,match='different teams'):
        seasons.save_match(rounds[1],teams[0],teams[0],store.iso(store.now_utc()),'Hall',admin)
    seasons.save_match(rounds[1],*reversed(teams),store.iso(store.now_utc()+timedelta(days=20)),'Club hall',admin)
    seasons.publish_season(season,admin)
    assert f'{store.now_utc().year}-{store.now_utc().year+1}' in client.get('/seasons').text
    seasons.save_season(store.now_utc().year,f'{store.now_utc().year}-02-01',f'{store.now_utc().year+1}-11-30',3,admin,season)
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM season_rounds WHERE season_id=?',(season,)).fetchone()[0]==3
    with pytest.raises(ValueError,match='extra rounds'):
        seasons.save_season(store.now_utc().year,f'{store.now_utc().year}-02-01',f'{store.now_utc().year+1}-11-30',1,admin,season)


def test_four_players_per_team_creates_four_games_and_updates_before_deadline(client):
    admin,season,rounds,match,teams,managers,rosters=setup()
    seasons.submit_lineup(match,managers[0],rosters[0])
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM match_games').fetchone()[0]==0
    seasons.submit_lineup(match,managers[1],rosters[1])
    with store.read_db() as db:
        games=db.execute('SELECT g.* FROM games g JOIN match_games mg ON mg.game_id=g.id ORDER BY board').fetchall()
        assert len(games)==4
        assert [g['white_team_id'] for g in games]==[teams[0],teams[1],teams[0],teams[1]]
        assert all(g['attribution_confirmed']==1 for g in games)
    seasons.submit_lineup(match,managers[0],list(reversed(rosters[0])))
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM games').fetchone()[0]==4
    store.update_game_result(games[0]['id'],'1-0',actor_id=admin,reason='Official match result')
    with pytest.raises(ValueError,match='locked'):
        seasons.submit_lineup(match,managers[0],rosters[0])
    with pytest.raises(ValueError,match='recorded games'):
        seasons.save_match(rounds[0],*teams,store.iso(store.now_utc()+timedelta(days=15)),'Updated hall',admin,match)


def test_lineup_rejects_duplicates_opponent_players_inactive_members_and_deadline(client,monkeypatch):
    admin,season,rounds,match,teams,managers,rosters=setup()
    with pytest.raises(ValueError,match='four different'):
        seasons.submit_lineup(match,managers[0],[rosters[0][0]]*4)
    with pytest.raises(ValueError,match='active member'):
        seasons.submit_lineup(match,managers[0],rosters[1])
    outsider=store.create_account('outside_manager',PASSWORD,'manager')
    with pytest.raises(ValueError,match='assigned team manager'):
        seasons.submit_lineup(match,outsider,rosters[0])
    with store.transaction() as db:
        db.execute('UPDATE users SET account_active=0 WHERE id=(SELECT user_id FROM players WHERE id=?)',(rosters[0][1],))
    with pytest.raises(ValueError,match='active member'):
        seasons.submit_lineup(match,managers[0],rosters[0])
    later=store.now_utc()+timedelta(days=11)
    monkeypatch.setattr(store,'now_utc',lambda:later)
    with pytest.raises(ValueError,match='deadline'):
        seasons.submit_lineup(match,managers[1],rosters[1])


def test_manager_lineup_http_and_admin_navigation(client):
    admin,season,rounds,match,teams,managers,rosters=setup()
    post(client,'/login',username='manager_home',password=PASSWORD)
    page=client.get(f'/matches/{match}')
    assert 'Your four-player lineup' in page.text
    response=post(client,f'/matches/{match}/lineup',**{f'player_{i}':str(pid) for i,pid in enumerate(rosters[0],1)})
    assert 'Four-player lineup submitted.' in response.text
    assert 'Team home' in client.get('/players?q=manager_home').text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM lineup_players WHERE match_id=?',(match,)).fetchone()[0]==4
