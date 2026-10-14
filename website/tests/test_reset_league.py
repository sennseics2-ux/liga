"""Admin-only reset prepares a separate validated database without data loss."""
from contextlib import closing
import sqlite3
import pytest
import database as store
import league_seasons as seasons
from deploy.reset_league import prepare
from deploy.backup_sqlite import backup,readonly,validate
from test_league import client
from test_v25_seasons import setup


def test_reset_preserves_admin_credentials_only_and_does_not_change_source(client,tmp_path,monkeypatch):
    admin,_,_,match,teams,managers,rosters=setup()
    for manager,roster in zip(managers,rosters):seasons.submit_lineup(match,manager,roster)
    auction=store.create_auction(rosters[0][1],10,24)
    store.place_bid(auction,teams[1],10)
    with store.read_db() as db:
        original=dict(db.execute('SELECT * FROM users WHERE id=?',(admin,)).fetchone())
        before='\n'.join(db.iterdump())
        allocated=db.execute("SELECT seq FROM sqlite_sequence WHERE name='users'").fetchone()[0]
    source=store.DB_PATH
    snapshot=backup(source,tmp_path/'backup',keep=0)
    output=tmp_path/'fresh.sqlite3'
    assert prepare(source,output)=='commissioner'
    assert store.DB_PATH==source
    with store.read_db() as db:assert '\n'.join(db.iterdump())==before
    with closing(readonly(output)) as db:
        db.row_factory=sqlite3.Row
        validate(db)
        rows=db.execute('SELECT * FROM users').fetchall()
        assert len(rows)==1
        kept=dict(rows[0])
        for field in ('id','username','email','password_hash','created_at'):
            assert kept[field]==original[field]
        assert kept['auth_version']==original['auth_version']+1
        assert store.verify_password('adminpass123!',kept['password_hash'])
        for table in ('teams','players','seasons','season_rounds','team_matches','games','match_lineups','lineup_players','auctions','bids','audit_log','password_resets'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0,table
    with closing(readonly(snapshot)) as db:assert db.execute('SELECT count(*) FROM players').fetchone()[0]>0
    monkeypatch.setattr(store,'DB_PATH',output)
    store.init_db()
    assert store.create_account('FreshPlayer','FreshPlayerPassword123!','player')>allocated


def test_reset_refuses_ambiguous_admin_and_existing_or_live_output(client,tmp_path):
    admin,*_=setup()
    source=store.DB_PATH
    with pytest.raises(ValueError,match='differ'):prepare(source,source)
    with store.transaction() as db:
        db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,'admin',?)",('second-admin',store.hash_password('SecondAdminPassword123!'),store.iso(store.now_utc())))
    output=tmp_path/'fresh.sqlite3'
    with pytest.raises(ValueError,match='one admin'):prepare(source,output)
    assert not output.exists()
    assert prepare(source,output,'commissioner')=='commissioner'
    with pytest.raises(FileExistsError):prepare(source,output,'commissioner')
