"""Shared external identities never combine account or historical game records."""
from datetime import timedelta
import re
import subprocess
import sys
from pathlib import Path
import pytest
import database as store
import account_service as accounts
import league_seasons as seasons
from main import public_game_visibility,season_bounds
from player_statistics import player_totals,team_season_scores
from test_league import client,seed_admin
from test_v29_admin_and_results import seed_player_results
from test_v31_manager_and_lineup_privacy import arranged_match


def test_shared_fide_ids_survive_restart_and_email_and_lock_rules_remain(client):
    a=store.create_account('SharedOne','SharedPassword123!','player',email='one@example.com')
    b=store.create_account('SharedTwo','SharedPassword123!','player',email='two@example.com')
    accounts.update_profile(a,'First','','123456')
    accounts.update_profile(b,'Second','','123456')
    store.init_db();store.init_db()
    with store.read_db() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE fide_id='123456'").fetchone()[0]==2
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='users_fide_unique'").fetchone()
    with pytest.raises(ValueError,match='6 to 8'):
        accounts.update_profile(b,'Second','','12345')
    with pytest.raises(ValueError,match='email address is already'):
        accounts.update_profile(b,'Second','','123456',email='one@example.com',current_password='SharedPassword123!')
    seed_admin()
    with store.read_db() as db:admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    accounts.update_profile(a,'First','','123456',actor_id=admin,fide_id_locked=True)
    with pytest.raises(ValueError,match='locked'):
        accounts.update_profile(a,'First','','234567')
    accounts.update_profile(b,'Second','','234567')
    assert accounts.account(a)['fide_id']=='123456'


def test_v31_migration_drops_unique_index_without_changing_profiles_or_photos(client):
    a=store.create_account('LegacyFide','SharedPassword123!','player',email='legacy@example.com')
    accounts.update_profile(a,'Existing Name','Portugal','123456')
    with store.transaction() as db:
        db.execute("DELETE FROM schema_migrations WHERE version IN ('v32_shared_fide_ids','v103_player_countries','v108_unregistered_player_fide')")
        db.execute('DROP INDEX users_fide_lookup')
        db.execute('CREATE UNIQUE INDEX users_fide_unique ON users(fide_id) WHERE fide_id IS NOT NULL')
        before=tuple(db.execute('SELECT username,email,name,country,fide_id,auth_version FROM users WHERE id=?',(a,)).fetchone())
    store.init_db()
    assert store.DB_PATH.with_name(store.DB_PATH.name+'.pre-v32.bak').exists()
    with store.read_db() as db:
        assert tuple(db.execute('SELECT username,email,name,country,fide_id,auth_version FROM users WHERE id=?',(a,)).fetchone())==before
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='team_photos'").fetchone()


def test_career_totals_use_all_completed_games_both_colours_and_all_years(client):
    seed_admin();white,black,games=seed_player_results()
    with store.read_db() as db:admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    # Add records beyond the eight-game profile preview and a previous season.
    for year,result in [(2024,'1-0'),(2025,'1/2-1/2'),(2026,'0-1')]:
        game=store.create_game(white,black,f'{year}-06-01T18:00:00+00:00')
        store.update_game_result(game,result,actor_id=admin,reason='Cross-season result')
    with store.read_db() as db:
        total=player_totals(db,white,*public_game_visibility())
        assert total=={'played':9,'wins':3,'draws':3,'losses':3,'score':'4.5'}
    page=client.get('/users/WhiteResults').text
    assert 'career-record' in page
    assert re.search(r'career-wins.*?<dd data-no-i18n>3</dd>',page,re.S)
    assert re.search(r'career-losses.*?<dd data-no-i18n>3</dd>',page,re.S)


def test_season_score_one_win_one_draw_is_1_5_over_2_and_not_fantasy_points(client):
    admin,season,rounds,match,teams,managers,rosters=arranged_match()
    second=seasons.save_match(rounds[1],*reversed(teams),store.iso(store.now_utc()+timedelta(days=15)),'Second match',admin)
    seasons.submit_lineup(second,managers[0],rosters[0])
    seasons.submit_lineup(second,managers[1],rosters[1])
    with store.transaction() as db:
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-01T18:00:00+00:00' WHERE id=?",(match,))
        games=[r[0] for r in db.execute('SELECT game_id FROM match_games WHERE match_id=? ORDER BY board',(match,))]
        admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    store.update_game_result(games[0],'1-0',actor_id=admin,reason='Season win')
    # The return match has reversed colours and immutable team attribution.
    with store.transaction() as db:
        db.execute("UPDATE team_matches SET scheduled_at='2026-06-02T18:00:00+00:00' WHERE id=?",(second,))
        drawn=db.execute('SELECT game_id FROM match_games WHERE match_id=? AND board=1',(second,)).fetchone()[0]
    store.update_game_result(drawn,'1/2-1/2',actor_id=admin,reason='Season draw')
    with store.read_db() as db:
        start,end,_=season_bounds(db,f's{season}')
        totals=team_season_scores(db,teams[0],start,end,season,*public_game_visibility())
        assert totals[rosters[0][0]]['summary']=='1.5/2'
    page=client.get(f'/teams/{teams[0]}?season=s{season}').text
    assert 'class="season-player-score" data-no-i18n>1.5/2</strong>' in page
    # A later transfer must not reattribute earlier games to the new team.
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(teams[1],rosters[0][0]))
    with store.read_db() as db:
        totals=team_season_scores(db,teams[0],start,end,season,*public_game_visibility())
        assert totals[rosters[0][0]]['summary']=='1.5/2'


def test_private_future_results_do_not_leak_through_statistics(client):
    admin,season,_,match,teams,_,rosters=arranged_match()
    with store.read_db() as db:game=db.execute('SELECT game_id FROM match_games WHERE match_id=? AND board=1',(match,)).fetchone()[0]
    store.update_game_result(game,'1-0',actor_id=admin,reason='Premature result is embargoed')
    with store.read_db() as db:
        assert player_totals(db,rosters[0][0],*public_game_visibility())['played']==0
        assert team_season_scores(db,teams[0],'2026-01-01','2028-01-01',season,*public_game_visibility())=={}


def test_generated_dark_styles_remain_complete():
    subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'tools/build_dark_theme.py'),'--check'],check=True)
