"""Rating freshness and the reported SQLite/proxy/session security regressions."""
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import json
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import account_service as accounts
import database as store
import fide_ratings
from deploy.proxy_trust import trusted_proxies
from test_league import client


def test_monthly_refresh_first_second_day_stale_data_and_year_rollover():
    first=datetime(2026,10,1,9,tzinfo=timezone.utc)
    assert fide_ratings.next_success(first,'2026-10').day==2
    assert fide_ratings.next_success(first,'2026-09')==first+timedelta(hours=6)
    second=datetime(2026,10,2,9,tzinfo=timezone.utc)
    assert fide_ratings.next_success(second,'2026-10').month==11
    assert fide_ratings.next_success(second,None).day==3
    december=datetime(2026,12,5,9,tzinfo=timezone.utc)
    assert fide_ratings.next_success(december,'2026-12').year==2027


def test_rating_success_retry_stale_id_guard_and_no_loss_on_failure(client,monkeypatch):
    uid=store.create_account('fide_member','PasswordLong123!','manager')
    accounts.update_profile(uid,'Fide Player','Portugal','123456')
    now=datetime(2026,10,1,9,tzinfo=timezone.utc)
    monkeypatch.setattr(store,'now_utc',lambda:now)
    assert fide_ratings.sync_ratings(fetcher=lambda _: (2110,'2026-10'))==1
    with store.read_db() as db:
        assert db.execute('SELECT rating FROM players WHERE user_id=?',(uid,)).fetchone()[0]==2110
    with store.transaction() as db:
        db.execute('UPDATE users SET fide_next_attempt=NULL WHERE id=?',(uid,))
    def failure(_):raise TimeoutError()
    assert fide_ratings.sync_ratings(fetcher=failure)==0
    profile=accounts.account(uid)
    assert profile['fide_rating']==2110 and profile['fide_error']
    assert fide_ratings.sync_ratings(fetcher=lambda _: (2999,'2026-10'))==0 # not due yet
    with store.transaction() as db:
        db.execute('UPDATE users SET fide_next_attempt=NULL WHERE id=?',(uid,))
    def changed(_):
        accounts.update_profile(uid,'Fide Player','Portugal','234567')
        return 2900,'2026-10'
    assert fide_ratings.sync_ratings(fetcher=changed)==0
    assert accounts.account(uid)['fide_rating'] is None


def test_rating_parser_selects_standard_field_not_rapid_or_blitz(monkeypatch):
    monkeypatch.setenv('CHESS_FIDE_API_URL_TEMPLATE','https://fideratings.com/api/player/{fide_id}')
    monkeypatch.setenv('CHESS_FIDE_RATING_FIELD','ratings.standard')
    monkeypatch.setenv('CHESS_FIDE_MONTH_FIELD','month')
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def geturl(self):return 'https://fideratings.com/api/player/123456'
        def read(self,n):return json.dumps({'ratings':{'standard':2120,'rapid':2300,'blitz':2400},'month':'2026-10'}).encode()
    with patch('fide_ratings.urlopen',return_value=Response()) as lookup:
        assert fide_ratings.fetch_standard_rating('123456')==(2120,'2026-10')
        assert lookup.call_args.args[0].full_url.endswith('/123456')
    monkeypatch.setenv('CHESS_FIDE_API_URL_TEMPLATE','http://127.0.0.1/{fide_id}')
    with pytest.raises(ValueError,match='HTTPS provider'):
        fide_ratings.fetch_standard_rating('123456')


@pytest.mark.parametrize('source,standard,expected',[
    ('latest_list',{'date':'2026-10','rating':'2823'},(2823,'2026-10')),
    ('last_known_profile',{'date':'2024-03','rating':'2100'},(2100,None)),
    ('latest_list',None,(None,None)),
    ('latest_list',{'date':'2026-10','rating':'N/A'},(None,'2026-10')),
])
def test_documented_current_endpoint_defaults_and_unrated(monkeypatch,source,standard,expected):
    for name in ('CHESS_FIDE_API_URL_TEMPLATE','CHESS_FIDE_RATING_FIELD','CHESS_FIDE_MONTH_FIELD','CHESS_FIDE_API_KEY'):
        monkeypatch.delenv(name,raising=False)
    payload={'fideid':'1503014','current_source':source,'current':{
        'standard':standard,'rapid':{'date':'2026-10','rating':'2801'},
        'blitz':{'date':'2026-10','rating':'2860'}}}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def geturl(self):return 'https://fideratings.com/api/player/1503014/current'
        def read(self,n):return json.dumps(payload).encode()
    with patch('fide_ratings.urlopen',return_value=Response()) as lookup:
        assert fide_ratings.fetch_standard_rating('1503014')==expected
        assert lookup.call_args.args[0].full_url==Response().geturl()
        payload['fideid']='123456'
        with pytest.raises(ValueError,match='unexpected player'):
            fide_ratings.fetch_standard_rating('1503014')


def test_pages_and_auction_poll_do_not_take_writer_lock_when_nothing_is_due(client):
    with patch('database.transaction',side_effect=AssertionError('No page-level writer lock')):
        assert store.settle_expired()==0
        assert client.get('/').status_code==200
        assert client.get('/auctions').status_code==200
        assert client.get('/api/auctions/snapshot').status_code==200
    with store.read_db() as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
    writer=store.connect()
    try:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("INSERT INTO teams(name,created_at) VALUES('Uncommitted','2026-01-01')")
        # WAL readers see the previously committed state while a writer is held.
        assert client.get('/').status_code==200
        assert client.get('/health').status_code==200
    finally:
        writer.rollback();writer.close()


def test_forwarded_ip_only_accepted_from_configured_proxy(monkeypatch):
    captured=[]
    async def target(scope,receive,send):captured.append(scope['client'][0])
    proxy=ProxyHeadersMiddleware(target,trusted_hosts='172.30.0.10')
    for remote in ['198.51.100.20','172.30.0.10']:
        scope={'type':'http','client':(remote,1234),'headers':[(b'x-forwarded-for',b'203.0.113.8')],'scheme':'http'}
        asyncio.run(proxy(scope,None,None))
    assert captured==['198.51.100.20','203.0.113.8']
    monkeypatch.setenv('CHESS_TRUSTED_PROXY_IPS','*')
    with pytest.raises(ValueError):trusted_proxies()
    monkeypatch.setenv('CHESS_TRUSTED_PROXY_IPS','0.0.0.0/0')
    with pytest.raises(ValueError):trusted_proxies()


def test_v24_migration_preserves_old_identity_results_and_roles(tmp_path,monkeypatch):
    import sqlite3
    live=tmp_path/'v24.sqlite3'
    fixture=Path(__file__).parent/'fixtures/v24-account-migration.sql'
    with sqlite3.connect(live) as db:
        db.executescript(fixture.read_text())
    monkeypatch.setattr(store,'DB_PATH',live)
    store.init_db();store.init_db()
    with store.read_db() as db:
        row=db.execute('SELECT u.*,p.points FROM users u JOIN players p ON p.user_id=u.id').fetchone()
        assert row['username']=='аlice' and row['name']=='Existing Name' and row['points']==7
        assert row['account_active']==1 and row['email'] is None
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert live.with_name(live.name+'.pre-v25.bak').exists()
