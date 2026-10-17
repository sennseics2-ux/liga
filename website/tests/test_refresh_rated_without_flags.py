"""Target only rated records without flags; preserve other records and edits."""
import sqlite3
import sys
import pytest
import account_service as accounts
import database as store
import fide_ratings
from deploy import refresh_fide_ratings as command
from test_league import client


@pytest.fixture(autouse=True)
def pause_background_worker(monkeypatch):
    # These tests invoke refresh explicitly; do not race the startup worker.
    import asyncio
    import main
    async def idle():
        await asyncio.Event().wait()
    monkeypatch.setattr(main,'rating_loop',idle)


def test_target_blank_unknown_and_whitespace_countries_only(client):
    uid=store.create_account('target_rating','PasswordLong123!','manager')
    accounts.update_profile(uid,'Target account','','1959506')
    targets=[store.create_player(f'Target {i}',rating=1800,fide_id='1959506') for i in range(3)]
    known=store.create_player('Known country',rating=1700,country='Portugal',fide_id='1959506')
    alias=store.create_player('Country alias',rating=1650,fide_id='1959506')
    unrated=store.create_player('Unrated no flag',fide_id='555014240')
    no_id=store.create_player('Rated without ID',rating=1600)
    with store.transaction() as db:
        db.execute('UPDATE users SET fide_rating=1800,account_active=0 WHERE id=?',(uid,))
        db.execute('UPDATE players SET rating=1800 WHERE user_id=?',(uid,))
        db.execute("UPDATE players SET country='Unknown federation' WHERE id=?",(targets[1],))
        db.execute("UPDATE players SET country=? WHERE id=?",('\u2003\t ',targets[2]))
        db.execute("UPDATE players SET country='PT' WHERE id=?",(alias,))
        before={pid:tuple(db.execute('SELECT * FROM players WHERE id=?',(pid,)).fetchone()) for pid in [known,alias,unrated,no_id]}
    calls=[];output=[]
    totals=command.refresh_all(fetcher=lambda fid:(calls.append(fid) or (1900,'2026-10','Portugal')),
                               rated_without_flag=True,output=output.append)
    assert calls==['1959506']
    assert totals=={'updated':4,'failed':0,'skipped':0,'unrated':0,'without_flag':1}
    with store.read_db() as db:
        assert db.execute('SELECT fide_rating,country,account_active FROM users WHERE id=?',(uid,)).fetchone()[:]==(1900,'Portugal',0)
        for pid in targets:
            assert db.execute('SELECT rating,country FROM players WHERE id=?',(pid,)).fetchone()[:]==(1900,'Portugal')
        assert db.execute('SELECT rating,country FROM players WHERE user_id=?',(uid,)).fetchone()[:]==(1900,'Portugal')
        for pid in before:assert tuple(db.execute('SELECT * FROM players WHERE id=?',(pid,)).fetchone())==before[pid]
    assert 'without a FIDE ID: 1' in output[-1]


@pytest.mark.parametrize('change',["country='Spain'",'rating=NULL',"fide_id='555014240'"])
def test_record_no_longer_eligible_is_not_overwritten(client,change):
    player=store.create_player('Edited during lookup',rating=1800,fide_id='1959506')
    def fetch(_):
        with store.transaction() as db:
            db.execute(f'UPDATE players SET {change} WHERE id=?',(player,))
        return 1900,'2026-10','Portugal'
    totals=command.refresh_all(fetcher=fetch,rated_without_flag=True,output=lambda _:None)
    assert totals['skipped']==1 and totals['updated']==0
    with store.read_db() as db:
        row=db.execute('SELECT rating,country,fide_checked_at FROM players WHERE id=?',(player,)).fetchone()
        assert row['rating']==(None if change=='rating=NULL' else 1800)
        assert row['country']==('Spain' if change=="country='Spain'" else '')
        assert row['fide_checked_at'] is None


def test_failure_or_unknown_country_is_reported_and_rating_is_preserved_on_failure(client):
    player=store.create_player('Provider failure',rating=1800,fide_id='1959506')
    def fail(_):raise TimeoutError('Provider unavailable')
    totals=command.refresh_all(fetcher=fail,rated_without_flag=True,output=lambda _:None)
    assert totals['failed']==1 and totals['without_flag']==1
    with store.read_db() as db:
        assert db.execute('SELECT rating,country FROM players WHERE id=?',(player,)).fetchone()[:]==(1800,'')
    totals=command.refresh_all(fetcher=lambda _:(1850,'2026-10',None),rated_without_flag=True,output=lambda _:None)
    assert totals['updated']==1 and totals['without_flag']==1


def test_target_filter_is_applied_before_batch_limit(client):
    store.create_player('Known first',rating=1800,country='Portugal',fide_id='1959506')
    target=store.create_player('Missing later',rating=1800,fide_id='555014240')
    calls=[]
    assert fide_ratings.sync_ratings(fetcher=lambda fid:(calls.append(fid) or (1900,'2026-10','Portugal')),
                                    limit=1,force=True,rated_without_flag=True)==1
    assert calls==['555014240']
    with store.read_db() as db:
        assert db.execute('SELECT country FROM players WHERE id=?',(target,)).fetchone()[0]=='Portugal'


def test_cli_dry_run_does_not_fetch_back_up_or_change_data(client,monkeypatch):
    player=store.create_player('Dry run player',rating=1800,fide_id='1959506')
    monkeypatch.setattr(sys,'argv',['refresh_fide_ratings','--rated-without-flag','--dry-run'])
    monkeypatch.setattr(command,'backup',lambda *a,**k:pytest.fail('Dry run must not back up/write'))
    monkeypatch.setattr(fide_ratings,'fetch_player_details',lambda _:pytest.fail('Dry run must not fetch'))
    assert command.main()==0
    with store.read_db() as db:
        assert db.execute('SELECT rating,country,fide_checked_at FROM players WHERE id=?',(player,)).fetchone()[:]==(1800,'',None)


def test_cli_creates_original_backup_before_targeted_updates(client,monkeypatch,tmp_path):
    player=store.create_player('Backup player',rating=1800,fide_id='1959506')
    monkeypatch.setattr(sys,'argv',['refresh_fide_ratings','--rated-without-flag','--backup-dir',str(tmp_path/'backups')])
    monkeypatch.setattr(fide_ratings,'fetch_player_details',lambda _:(1900,'2026-10','Portugal'))
    assert command.main()==0
    snapshots=list((tmp_path/'backups').glob('fide-refresh-*/*.sqlite3'))
    assert len(snapshots)==1
    with sqlite3.connect(snapshots[0]) as db:
        assert db.execute('SELECT rating,country FROM players WHERE id=?',(player,)).fetchone()==(1800,'')
    with store.read_db() as db:
        assert db.execute('SELECT rating,country FROM players WHERE id=?',(player,)).fetchone()[:]==(1900,'Portugal')


def test_cli_reports_unresolvable_missing_fide_id(client,monkeypatch):
    store.create_player('No FIDE ID',rating=1800)
    monkeypatch.setattr(sys,'argv',['refresh_fide_ratings','--rated-without-flag'])
    monkeypatch.setattr(command,'backup',lambda *a,**k:'test backup')
    assert command.main()==1
