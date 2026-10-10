"""V8 public directory filtering, search and self-consistent demo data."""
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from test_league import client, new_team
import database as store
from main import app


def test_player_search_filters_and_safe_sort(client):
    _,knights = new_team('knightmgr','Knight Searchers')
    _,bishops = new_team('bishopmgr','Bishop Searchers')
    p1=store.create_player('Ana Example','Club A',1880)
    p2=store.create_player('Bea Example','Club B',1710)
    p3=store.create_player('Zoe Example','Club B',1940)
    with store.transaction() as db:
        for pid,team,pts in [(p1,knights,30),(p2,bishops,80),(p3,None,5)]:
            db.execute('UPDATE players SET owner_team_id=?,points=? WHERE id=?',(team,pts,pid))
            if team:
                store._start_player_term(db,pid,team)
    directory=client.get('/players')
    assert directory.status_code==200 and 'Search players' in directory.text
    assert 'Minimum rating' in directory.text
    assert 'Ana Example' in directory.text
    assert 'Bea Example' in directory.text
    page=client.get('/players',params={'q':'ana','team':str(knights)})
    assert 'Ana Example' in page.text and 'Bea Example' not in page.text
    page=client.get('/players',params={'status':'free','club':'Club B','min_rating':1900})
    assert 'Zoe Example' in page.text and 'Bea Example' not in page.text
    page=client.get('/players',params={'sort':'name_desc'})
    assert page.text.index('Zoe Example') < page.text.index('Bea Example') < page.text.index('Ana Example')
    # No arbitrary SQL expressions are accepted as an order clause.
    assert client.get('/players',params={'sort':'p.id;DROP TABLE users'}).status_code==200
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]>0


def test_team_directory_search_sort_filter_and_member_redirect(client):
    _,t1=new_team('manageraa','Alpha Knights')
    t2=store.create_team('Vacant Bishops')
    p=store.create_player('Team Player',rating=1700)
    with store.transaction() as db:
        db.execute('UPDATE players SET owner_team_id=?,points=19 WHERE id=?',(t1,p))
        store._start_player_term(db,p,t1)
    page=client.get('/teams',params={'q':'manageraa','manager':'assigned','min_players':2})
    assert 'Alpha Knights' in page.text and 'Vacant Bishops' not in page.text
    page=client.get('/teams',params={'manager':'vacant'})
    assert 'Vacant Bishops' in page.text and 'Alpha Knights' not in page.text
    assert client.get('/teams',params={'sort':'points_desc'}).status_code==200
    assert client.get('/members',follow_redirects=False).headers['location']=='/players'
    assert 'Members</a>' not in client.get('/').text
    assert 'Transfers in ' in client.get(f'/teams/{t1}').text


def test_three_season_demonstration_database(tmp_path,monkeypatch,three_season_database):
    from demo.generate_three_seasons import validate
    source=three_season_database
    dbpath=tmp_path/'three-seasons.sqlite3'
    shutil.copy2(source,dbpath)
    report=validate(dbpath)
    assert report['transfer_count']==40 and report['open_auctions']==3
    monkeypatch.setattr(store,'DB_PATH',dbpath)
    with TestClient(app) as c:
        for season in (2024,2025,2026):
            for team_id in range(1,9):
                page=c.get(f'/teams/{team_id}',params={'season':season})
                assert page.status_code==200
                assert f'{season} season' in page.text
                assert 'Historical coverage is partial' not in page.text
                assert 'Squad by season' in page.text
                assert 'Transfers in ' in page.text
        assert 'Ana ' in c.get('/players',params={'q':'Ana'}).text
        assert 'No matching players' in c.get('/players',params={'q':'does-not-exist-123'}).text
        assert 'Coimbra Knights' in c.get('/teams',params={'q':'Coimbra'}).text
        assert 'Coimbra Knights' not in c.get('/teams',params={'q':'Viseu'}).text
        page=c.get('/teams/1',params={'season':2024})
        assert '2024 season' in page.text
        assert c.get('/login').status_code==200
