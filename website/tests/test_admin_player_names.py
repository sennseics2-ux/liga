"""Only administrators can rename players while stable identities are preserved."""
import json
import pytest
import database as store
from test_league import client,post,seed_admin,login_admin,new_team


def test_admin_renames_unregistered_namesake_only_and_records_audit(client):
    seed_admin();login_admin(client)
    first=store.create_player('Same Name',rating=1700,country='Portugal',fide_id='1959506')
    second=store.create_player('Same Name',rating=1800,country='Spain',fide_id='94761418')
    with store.read_db() as db:
        before=dict(db.execute('SELECT * FROM players WHERE id=?',(first,)).fetchone())
    page=client.get('/admin/players').text
    assert 'Edit country' not in page and 'data-player-name-editor' in page
    assert f'action="/admin/players/{first}/name"' in page
    assert f'href="/players/{first}"' in page
    assert post(client,f'/admin/players/{first}/name',name='  Mário Morais  ',original_name='Same Name').status_code==200
    with store.read_db() as db:
        after=dict(db.execute('SELECT * FROM players WHERE id=?',(first,)).fetchone())
        assert after=={**before,'name':'Mário Morais'}
        assert db.execute('SELECT name FROM players WHERE id=?',(second,)).fetchone()[0]=='Same Name'
        event=db.execute("SELECT * FROM audit_log WHERE event='player_name_updated'").fetchone()
        assert event['entity_id']==first and json.loads(event['after_json'])['name']=='Mário Morais'
    assert 'Mário Morais' in client.get(f'/players/{first}').text


def test_linked_account_name_changes_but_username_and_account_data_do_not(client):
    seed_admin();login_admin(client)
    uid,_=new_team('NameCaptain','Name Team')
    with store.read_db() as db:
        before=dict(db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())
        player=db.execute('SELECT id,name FROM players WHERE user_id=?',(uid,)).fetchone()
    post(client,f'/admin/players/{player["id"]}/name',name='New Captain Name',original_name=player['name'])
    with store.read_db() as db:
        after=dict(db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())
        assert after=={**before,'name':'New Captain Name'}
        assert db.execute('SELECT name FROM players WHERE id=?',(player['id'],)).fetchone()[0]=='New Captain Name'
    assert client.get(f'/players/{player["id"]}',follow_redirects=False).headers['location']=='/users/NameCaptain'
    assert 'New Captain Name' in client.get('/users/NameCaptain').text


@pytest.mark.parametrize('name',['',' ','A','A'*81,'Bad\nName','Bad\x7fName'])
def test_invalid_names_cannot_change_data(client,name):
    seed_admin();login_admin(client)
    player=store.create_player('Original Name')
    response=post(client,f'/admin/players/{player}/name',name=name,original_name='Original Name')
    assert 'Player name must be 2–80 characters.' in response.text
    with store.read_db() as db:
        assert db.execute('SELECT name FROM players WHERE id=?',(player,)).fetchone()[0]=='Original Name'
        assert db.execute("SELECT count(*) FROM audit_log WHERE event='player_name_updated'").fetchone()[0]==0


def test_rename_requires_admin_and_csrf_and_rejects_stale_edits(client):
    player=store.create_player('Original Name')
    member=store.create_account('NameViewer','PasswordLong123!','player')
    post(client,'/login',username='NameViewer',password='PasswordLong123!')
    assert post(client,f'/admin/players/{player}/name',name='Changed Name',original_name='Original Name').status_code==403
    with pytest.raises(ValueError,match='administrators'):store.update_player_name(player,'Changed Name',member,'Original Name')
    seed_admin();login_admin(client)
    assert client.post(f'/admin/players/{player}/name',data={'name':'Changed Name','original_name':'Original Name'}).status_code==403
    with store.transaction() as db:db.execute('UPDATE players SET name=? WHERE id=?',('Concurrent Name',player))
    assert 'Player name changed.' in post(client,f'/admin/players/{player}/name',name='Stale Name',original_name='Original Name').text
    with store.read_db() as db:
        assert db.execute('SELECT name FROM players WHERE id=?',(player,)).fetchone()[0]=='Concurrent Name'
    assert post(client,f'/admin/players/{2**63}/name',name='Changed Name',original_name='Original Name').status_code==404
