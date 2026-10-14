"""A whole-roster refresh ignores deadlines without losing data on failure."""
from datetime import timedelta
import pytest
from urllib.error import HTTPError
import account_service as accounts
import database as store
import fide_ratings
from deploy.refresh_fide_ratings import refresh_all,paced_fetcher
from test_league import client


def test_force_refresh_covers_all_players_shared_ids_and_inactive_accounts(client):
    uid=store.create_account('rating_member','PasswordLong123!','manager')
    accounts.update_profile(uid,'Registered Player','Spain','1959506')
    shared=store.create_player('Shared FIDE player',fide_id='1959506')
    others=[store.create_player(f'Player {i}',fide_id=str(555014240+i)) for i in range(12)]
    blank=store.create_player('No FIDE ID',rating=1500)
    future=store.iso(store.now_utc()+timedelta(days=60))
    with store.transaction() as db:
        db.execute('UPDATE users SET account_active=0,fide_next_attempt=? WHERE id=?',(future,uid))
        db.execute('UPDATE players SET fide_next_attempt=?',(future,))
    calls=[];output=[]
    totals=refresh_all(fetcher=lambda fid:(calls.append(fid) or (1870,'2026-10','Portugal')),output=output.append)
    assert totals=={'updated':14,'failed':0,'skipped':0,'unrated':0}
    assert len(calls)==13 and calls.count('1959506')==1
    with store.read_db() as db:
        assert db.execute('SELECT fide_rating,account_active FROM users WHERE id=?',(uid,)).fetchone()[:]==(1870,0)
        assert db.execute('SELECT count(*) FROM players WHERE rating=1870').fetchone()[0]==14
        assert db.execute('SELECT country FROM users WHERE id=?',(uid,)).fetchone()[0]=='Portugal'
        assert db.execute("SELECT count(*) FROM players WHERE country='Portugal'").fetchone()[0]==14
        assert db.execute('SELECT rating,fide_checked_at FROM players WHERE id=?',(blank,)).fetchone()[:]==(1500,None)
    assert 'Updated: 14' in output[-1]


def test_failed_lookups_keep_ratings_and_unrated_response_is_not_a_failure(client):
    first=store.create_player('Failed player',rating=1700,fide_id='1959506')
    second=store.create_player('Same failed ID',rating=1800,fide_id='1959506')
    unrated=store.create_player('Unrated player',rating=1500,fide_id='555014240')
    calls=[]
    def fetch(fid):
        calls.append(fid)
        if fid=='1959506':raise TimeoutError('Example failure')
        return None,'2026-10'
    totals=refresh_all(fetcher=fetch,output=lambda _:None)
    assert totals=={'updated':1,'failed':2,'skipped':0,'unrated':1}
    assert calls.count('1959506')==1
    with store.read_db() as db:
        assert db.execute('SELECT rating FROM players WHERE id=?',(first,)).fetchone()[0]==1700
        assert db.execute('SELECT rating FROM players WHERE id=?',(second,)).fetchone()[0]==1800
        assert db.execute('SELECT fide_attempts,fide_error FROM players WHERE id=?',(first,)).fetchone()[0]==1
        assert db.execute('SELECT rating FROM players WHERE id=?',(unrated,)).fetchone()[0] is None
    assert fide_ratings.sync_ratings(fetcher=fetch,limit=None)==0


def test_force_refresh_skips_a_fide_id_changed_during_lookup(client):
    player=store.create_player('Changed ID',rating=1700,fide_id='1959506',country='Spain')
    def changed(_):
        with store.transaction() as db:
            db.execute('UPDATE players SET fide_id=? WHERE id=?',('555014240',player))
        return 1900,'2026-10','Portugal'
    assert refresh_all(fetcher=changed,output=lambda _:None)['skipped']==1
    with store.read_db() as db:
        assert db.execute('SELECT rating FROM players WHERE id=?',(player,)).fetchone()[0]==1700
        assert db.execute('SELECT country FROM players WHERE id=?',(player,)).fetchone()[0]=='Spain'


def test_normal_worker_still_respects_batch_limit(client):
    for i in range(12):store.create_player(f'Player {i}',fide_id=str(555014240+i))
    assert fide_ratings.sync_ratings(fetcher=lambda _:(1800,'2026-10'))==10
    assert fide_ratings.sync_ratings(fetcher=lambda _:(1800,'2026-10'))==2
    with pytest.raises(ValueError):fide_ratings.sync_ratings(limit=-1)


def test_public_api_pacing_and_retry_after():
    now=[0.0];sleeps=[];calls=[]
    def sleep(delay):
        sleeps.append(delay)
        now[0]+=delay
    def fetch(fid):
        calls.append((fid,now[0]))
        if len(calls)==2:
            raise HTTPError('https://fideratings.com/',429,'Too many requests',{'Retry-After':'7'},None)
        return 1800,'2026-10'
    polite=paced_fetcher(fetch,sleep=sleep,clock=lambda:now[0])
    assert polite('1959506')==(1800,'2026-10')
    assert polite('555014240')==(1800,'2026-10')
    assert calls==[('1959506',0.0),('555014240',1.0),('555014240',8.0)]


def test_long_rate_limit_is_not_retried_or_hidden():
    calls=[]
    def fail(fid):
        calls.append(fid)
        raise HTTPError('https://fideratings.com/',429,'Too many requests',{'Retry-After':'120'},None)
    polite=paced_fetcher(fail,sleep=lambda _:pytest.fail('Long wait should not run'))
    with pytest.raises(HTTPError):polite('1959506')
    assert calls==['1959506']
