"""The requested FPX range imports as independent players, never accounts."""
from contextlib import closing
import sqlite3
import pytest
import database as store
import fide_ratings
from deploy.import_fpx_players import import_entries,load_entries,SOURCE
from test_league import client,seed_admin


def test_import_exact_range_without_accounts_and_zero_ids_stay_blank(client):
    seed_admin()
    with store.read_db() as db:users=[tuple(r) for r in db.execute('SELECT * FROM users')]
    assert import_entries()==(128,0)
    with store.read_db() as db:
        players=db.execute('SELECT * FROM players ORDER BY id').fetchall()
        assert len(players)==128
        assert all(p['user_id'] is None and p['owner_team_id'] is None and not p['is_manager_player'] for p in players)
        assert [tuple(r) for r in db.execute('SELECT * FROM users')]==users
        assert sum(p['fide_id'] is None for p in players)==41
        assert sum(p['fide_id'] is not None for p in players)==87
        assert players[0]['name']=='MORAIS, MÁRIO MARTINS FREITAS' and players[0]['fide_id']=='1959506'
        assert players[-1]['name']=='SERRADELL VILLA, ANDREA' and players[-1]['fide_id']=='94761418'
        nine=next(p for p in players if p['name']=='AHMED MOHAMED AHMED REZK, AHMED')
        assert nine['fide_id']=='555014356'
        missing=next(p for p in players if p['fide_id'] is None)
        assert len(db.execute('SELECT * FROM player_import_records').fetchall())==128
    assert '555014356' in client.get(f'/players/{nine["id"]}').text
    assert '<span data-i18n="FIDE ID">FIDE ID</span>:' not in client.get(f'/players/{missing["id"]}').text
    assert import_entries()==(0,128)
    with store.read_db() as db:
        assert db.execute('SELECT count(*) FROM players').fetchone()[0]==128
        assert db.execute('SELECT count(*) FROM users').fetchone()[0]==1


def test_import_uses_fpx_keys_and_never_merges_by_name(client):
    entries=load_entries()
    old=store.create_player(entries[0]['name'],fide_id=entries[0]['fide_id'])
    assert import_entries()==(128,0)
    with store.read_db() as db:
        new=db.execute('SELECT player_id FROM player_import_records WHERE source=? AND record_key=?',(SOURCE,entries[0]['fpx_id'])).fetchone()[0]
        assert new!=old
        assert db.execute('SELECT count(*) FROM players WHERE name=?',(entries[0]['name'],)).fetchone()[0]==2


def test_import_is_atomic_on_failure(client):
    with store.transaction() as db:
        db.execute("""CREATE TRIGGER reject_second_player BEFORE INSERT ON players
            WHEN NEW.name='AZUL, ARTUR AUGUSTO' BEGIN SELECT RAISE(ABORT,'test failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):import_entries()
    with store.read_db() as db:
        assert db.execute('SELECT count(*) FROM players').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM player_import_records').fetchone()[0]==0


def test_unregistered_ratings_include_nine_digit_ids_and_skip_blank_ids(client):
    nine=store.create_player('Nine digit player',fide_id='555014356')
    unknown=store.create_player('No FIDE player',fide_id='0')
    calls=[]
    assert fide_ratings.sync_ratings(fetcher=lambda value:(calls.append(value) or (1800,'2026-10')))==1
    assert calls==['555014356']
    with store.read_db() as db:
        row=db.execute('SELECT * FROM players WHERE id=?',(nine,)).fetchone()
        assert row['rating']==1800 and row['fide_rating_month']=='2026-10' and row['fide_next_attempt']
        assert db.execute('SELECT fide_id,rating FROM players WHERE id=?',(unknown,)).fetchone()[0] is None
    assert fide_ratings.sync_ratings(fetcher=lambda _:(9999,'2026-10'))==0


def test_unregistered_rating_failure_preserves_rating_and_schedules_retry(client):
    player=store.create_player('Failed lookup',rating=1600,fide_id='1959506')
    def fail(_):raise OSError('Unavailable')
    assert fide_ratings.sync_ratings(fetcher=fail)==0
    with store.read_db() as db:
        row=db.execute('SELECT rating,fide_error,fide_attempts,fide_next_attempt FROM players WHERE id=?',(player,)).fetchone()
        assert row['rating']==1600 and row['fide_error'] and row['fide_attempts']==1 and row['fide_next_attempt']


def test_upgrade_preserves_existing_player_data_and_is_repeatable(client):
    player=store.create_player('Existing Player',rating=1750,country='Portugal')
    with store.transaction() as db:
        db.execute('DROP TABLE player_import_records')
        db.execute('DROP INDEX players_fide_lookup')
        for field in ('fide_id','fide_rating_month','fide_checked_at','fide_next_attempt','fide_error','fide_attempts'):
            db.execute(f'ALTER TABLE players DROP COLUMN {field}')
        db.execute("DELETE FROM schema_migrations WHERE version='v108_unregistered_player_fide'")
    store.init_db()
    assert store.DB_PATH.with_name(store.DB_PATH.name+'.pre-v108.bak').exists()
    with store.read_db() as db:
        row=db.execute('SELECT name,rating,country,fide_id FROM players WHERE id=?',(player,)).fetchone()
        assert tuple(row)==('Existing Player',1750,'Portugal',None)
    assert import_entries()==(128,0)
    store.init_db()
    assert import_entries()==(0,128)
