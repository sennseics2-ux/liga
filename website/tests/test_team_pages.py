"""V6 teams directory, ownership history, archived seasons and migrations."""
import shutil
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest

from test_league import client, new_team
import database as store


def test_public_team_directory_and_detail(client):
    manager,team=new_team('watchman','Rose Knights')
    another=store.create_team('Desert Bishops')
    p=store.create_player('Laura Tester','Coimbra Chess',1920)
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(team,p))
        store._start_player_term(db,p,team)
    directory=client.get('/teams')
    assert directory.status_code==200
    assert f'href="/teams/{team}"' in directory.text
    assert 'Rose Knights' in directory.text
    assert 'Desert Bishops' in directory.text
    assert 'Teams</a>' in client.get('/').text
    page=client.get(f'/teams/{team}')
    assert page.status_code==200
    for value in ('Rose Knights','Laura Tester','watchman','Current squad','Squad by season'):
        assert value in page.text
    assert client.get(f'/teams/{another}').status_code==200
    assert 'No players are currently' in client.get(f'/teams/{another}').text
    assert client.get('/teams/123456').status_code==404
    assert client.get(f'/teams/{team}?season=1900').status_code==404
    assert f'href="/teams/{team}"' in client.get('/standings').text
    assert f'href="/teams/{team}"' in client.get('/players').text


def test_auction_and_kick_preserve_membership_history(client):
    _manager,old_team=new_team('seller1','Golden Queens')
    manager2,new_team_id=new_team('buyer2','Bronze Knights')
    p=store.create_player('Dated Chess Player',rating=1700)
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=? WHERE id=?',(old_team,p))
        store._start_player_term(db,p,old_team,'2025-01-01T00:00:00+00:00')
    auction=store.create_auction(p,10,1)
    store.place_bid(auction,new_team_id,33)
    with store.transaction() as db:
        assert store.settle_auction(db,auction)
        actual=db.execute('SELECT owner_team_id FROM players WHERE id=?',(p,)).fetchone()[0]
        assert actual==new_team_id
        old=db.execute('SELECT ended_at,end_reason FROM player_team_terms WHERE player_id=? AND team_id=?',(p,old_team)).fetchone()
        new=db.execute('SELECT started_at,ended_at FROM player_team_terms WHERE player_id=? AND team_id=?',(p,new_team_id)).fetchone()
        assert old['ended_at'] and old['end_reason']=='transferred'
        assert new['started_at'] and new['ended_at'] is None
    assert 'Dated Chess Player' in client.get(f'/teams/{old_team}?season=2025').text
    assert 'Dated Chess Player' in client.get(f'/teams/{new_team_id}').text
    store.kick_player(manager2,p)
    with store.read_db() as db:
        assert db.execute('SELECT owner_team_id FROM players WHERE id=?',(p,)).fetchone()[0] is None
        row=db.execute('SELECT ended_at,end_reason FROM player_team_terms WHERE player_id=? AND team_id=?',(p,new_team_id)).fetchone()
        assert row['ended_at'] and row['end_reason']=='removed by manager'
    assert 'Dated Chess Player' not in client.get(f'/teams/{new_team_id}').text.split('Squad by season')[0]
    assert 'Dated Chess Player' in client.get(f'/teams/{new_team_id}').text.split('Squad by season')[1]


def test_manager_history_and_current_status(client):
    mid,tid=new_team('captain1','Kings of 2026')
    with store.read_db() as db:
        player=db.execute('SELECT id FROM players WHERE user_id=?',(mid,)).fetchone()[0]
        assert db.execute('SELECT COUNT(*) FROM player_team_terms WHERE player_id=? AND ended_at IS NULL',(player,)).fetchone()[0]==1
    store.resign_team(mid)
    with store.read_db() as db:
        assert db.execute('SELECT ended_at FROM player_team_terms WHERE player_id=?',(player,)).fetchone()[0]
    page=client.get(f'/teams/{tid}')
    assert 'captain1' in page.text  # historical manager remains visible
    assert 'Awaiting appointment' in page.text
    assert 'Kings of 2026' in page.text


def test_v5_demo_database_migration(tmp_path, monkeypatch, legacy_database_factory):
    source=legacy_database_factory(5)
    target=tmp_path/'v5_demo.sqlite3'
    shutil.copy2(source,target)
    monkeypatch.setattr(store,'DB_PATH',target)
    with store.read_db() as db:
        counts={t:db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                for t in ('users','teams','players','auctions','bids','manager_terms')}
    store.init_db()
    with store.read_db() as db:
        for table,before in counts.items():
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==before
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM player_team_terms').fetchone()[0]>20
        assert db.execute("SELECT COUNT(*) FROM player_team_terms WHERE substr(started_at,1,4)='2024'").fetchone()[0]>0
        first_count=db.execute('SELECT COUNT(*) FROM player_team_terms').fetchone()[0]
        current=db.execute('''SELECT COUNT(*) FROM players p JOIN player_team_terms r
            ON p.id=r.player_id WHERE p.owner_team_id=r.team_id AND r.ended_at IS NULL''').fetchone()[0]
        assert current==db.execute('SELECT COUNT(*) FROM players WHERE owner_team_id IS NOT NULL').fetchone()[0]
    store.init_db() # repeat migration should not duplicate any records
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM player_team_terms').fetchone()[0]==first_count
