"""Country-only updates preserve filled fields, ratings, and concurrent edits."""
import account_service as accounts
import database as store
import fide_ratings
from deploy.fill_missing_countries import fill_missing
from test_league import client


def test_country_only_fetch_uses_only_profile_endpoint(monkeypatch):
    calls=[]
    def payload(fid,template):
        calls.append((fid,template))
        return {'fideid':'1959506','federation_code':'POR'}
    monkeypatch.setattr(fide_ratings,'_fetch_payload',payload)
    assert fide_ratings.fetch_federation_country('1959506')=='Portugal'
    assert calls==[('1959506',fide_ratings.PROFILE_URL)]


def test_fill_only_blanks_in_both_registered_and_standalone_records(client):
    uid=store.create_account('blank_country','PasswordLong123!','manager')
    accounts.update_profile(uid,'Blank Player','','1959506')
    known=store.create_player('Existing country',country='Spain',rating=1700,fide_id='94761418')
    blank=store.create_player('Blank country',rating=1800,fide_id='1959506')
    no_id=store.create_player('No ID',rating=1500)
    with store.transaction() as db:
        db.execute('UPDATE players SET country=?,rating=1600 WHERE user_id=?',('France',uid))
        db.execute('UPDATE users SET fide_rating=1600,account_active=0 WHERE id=?',(uid,))
        db.execute('UPDATE players SET country=? WHERE id=?',('\u2003\t ',blank))
    with store.read_db() as db:
        ratings=[tuple(row) for row in db.execute('SELECT id,rating,fide_checked_at,fide_next_attempt FROM players')]
    calls=[]
    assert fill_missing(fetcher=lambda fid:(calls.append(fid) or 'Portugal'),output=lambda _:None)['updated']==2
    assert calls==['1959506']
    with store.read_db() as db:
        assert db.execute('SELECT country,fide_rating FROM users WHERE id=?',(uid,)).fetchone()[:]==('Portugal',1600)
        assert db.execute('SELECT country FROM players WHERE user_id=?',(uid,)).fetchone()[0]=='France'
        assert db.execute('SELECT country FROM players WHERE id=?',(known,)).fetchone()[0]=='Spain'
        assert db.execute('SELECT country FROM players WHERE id=?',(blank,)).fetchone()[0]=='Portugal'
        assert db.execute('SELECT country FROM players WHERE id=?',(no_id,)).fetchone()[0]==''
        assert ratings==[tuple(row) for row in db.execute('SELECT id,rating,fide_checked_at,fide_next_attempt FROM players')]
    calls.clear()
    assert fill_missing(fetcher=lambda fid:(calls.append(fid) or 'Portugal'),output=lambda _:None)['updated']==0
    assert calls==[]


def test_blank_linked_player_uses_account_id_preserving_account_country(client):
    uid=store.create_account('existing_country','PasswordLong123!','manager')
    accounts.update_profile(uid,'Linked Player','Spain','1959506')
    calls=[]
    assert fill_missing(fetcher=lambda fid:(calls.append(fid) or 'Portugal'),output=lambda _:None)['updated']==1
    assert calls==['1959506']
    with store.read_db() as db:
        assert db.execute('SELECT country FROM users WHERE id=?',(uid,)).fetchone()[0]=='Spain'
        assert db.execute('SELECT country FROM players WHERE user_id=?',(uid,)).fetchone()[0]=='Portugal'


def test_unknown_failed_and_shared_ids_do_not_invent_countries(client):
    for name,fid in [('First','1959506'),('Second','1959506'),('Unknown','94761418')]:
        store.create_player(name,fide_id=fid)
    calls=[]
    def fetch(fid):
        calls.append(fid)
        if fid=='1959506':raise TimeoutError()
        return None
    assert fill_missing(fetcher=fetch,output=lambda _:None)=={'updated':0,'unknown':1,'failed':2,'skipped':0}
    assert calls==['1959506','94761418']
    with store.read_db() as db:
        assert db.execute("SELECT count(*) FROM players WHERE country!=''").fetchone()[0]==0


def test_country_entered_or_fide_id_changed_during_lookup_is_preserved(client):
    first=store.create_player('Country edit',fide_id='1959506')
    second=store.create_player('ID edit',fide_id='94761418')
    def changed(fid):
        with store.transaction() as db:
            if fid=='1959506':db.execute("UPDATE players SET country='Spain' WHERE id=?",(first,))
            else:db.execute("UPDATE players SET fide_id='555014356' WHERE id=?",(second,))
        return 'Portugal'
    assert fill_missing(fetcher=changed,output=lambda _:None)['skipped']==2
    with store.read_db() as db:
        assert db.execute('SELECT country FROM players WHERE id=?',(first,)).fetchone()[0]=='Spain'
        assert db.execute('SELECT country FROM players WHERE id=?',(second,)).fetchone()[0]==''
