"""Administrator team renames preserve IDs, ownership and captain assignments."""
import json
import pytest
import database as store
from test_league import client,post,seed_admin,login_admin,new_team


def test_admin_renames_team_without_changing_other_team_or_player_data(client):
    seed_admin();login_admin(client)
    _,team=new_team('RenameCaptain','Original Team')
    with store.read_db() as db:
        before=dict(db.execute('SELECT * FROM teams WHERE id=?',(team,)).fetchone())
        players=[tuple(row) for row in db.execute('SELECT * FROM players')]
    page=client.get('/admin/teams').text
    assert f'action="/admin/teams/{team}/name"' in page and 'data-team-name-editor' in page
    assert f'href="/teams/{team}"' in page
    assert post(client,f'/admin/teams/{team}/name',name='  Equipa de Coimbra  ',original_name='Original Team').status_code==200
    with store.read_db() as db:
        after=dict(db.execute('SELECT * FROM teams WHERE id=?',(team,)).fetchone())
        assert after=={**before,'name':'Equipa de Coimbra'}
        assert [tuple(row) for row in db.execute('SELECT * FROM players')]==players
        event=db.execute("SELECT * FROM audit_log WHERE event='team_name_updated'").fetchone()
        assert event['entity_id']==team and json.loads(event['after_json'])['name']=='Equipa de Coimbra'
    assert 'Equipa de Coimbra' in client.get(f'/teams/{team}').text
    assert 'Equipa de Coimbra' in client.get('/teams').text


def test_duplicate_team_names_are_rejected_but_case_only_rename_is_allowed(client):
    seed_admin();login_admin(client)
    team=store.create_team('Original Team');store.create_team('Existing Team')
    assert 'That team name is already taken.' in post(client,f'/admin/teams/{team}/name',name='EXISTING TEAM',original_name='Original Team').text
    with store.read_db() as db:
        assert db.execute('SELECT name FROM teams WHERE id=?',(team,)).fetchone()[0]=='Original Team'
        assert db.execute("SELECT count(*) FROM audit_log WHERE event='team_name_updated'").fetchone()[0]==0
    post(client,f'/admin/teams/{team}/name',name='ORIGINAL TEAM',original_name='Original Team')
    with store.read_db() as db:
        assert db.execute('SELECT name FROM teams WHERE id=?',(team,)).fetchone()[0]=='ORIGINAL TEAM'


@pytest.mark.parametrize('name',['',' ','AB','A'*46,'Bad\nName','Bad\x7fName'])
def test_invalid_team_names_leave_the_name_unchanged(client,name):
    seed_admin();login_admin(client)
    team=store.create_team('Original Team')
    assert 'Team name must be 3–45 characters.' in post(client,f'/admin/teams/{team}/name',name=name,original_name='Original Team').text
    with store.read_db() as db:
        assert db.execute('SELECT name FROM teams WHERE id=?',(team,)).fetchone()[0]=='Original Team'


def test_team_rename_requires_admin_csrf_and_current_name(client):
    team=store.create_team('Original Team')
    viewer=store.create_account('TeamNameViewer','PasswordLong123!','player')
    post(client,'/login',username='TeamNameViewer',password='PasswordLong123!')
    assert post(client,f'/admin/teams/{team}/name',name='Changed Team',original_name='Original Team').status_code==403
    with pytest.raises(ValueError,match='administrators'):store.update_team_name(team,'Changed Team',viewer,'Original Team')
    seed_admin();login_admin(client)
    assert client.post(f'/admin/teams/{team}/name',data={'name':'Changed Team','original_name':'Original Team'}).status_code==403
    with store.transaction() as db:db.execute('UPDATE teams SET name=? WHERE id=?',('Concurrent Team',team))
    assert 'Team name changed.' in post(client,f'/admin/teams/{team}/name',name='Stale Team',original_name='Original Team').text
    with store.read_db() as db:
        assert db.execute('SELECT name FROM teams WHERE id=?',(team,)).fetchone()[0]=='Concurrent Team'
    assert post(client,f'/admin/teams/{2**63}/name',name='Changed Team',original_name='Original Team').status_code==404
