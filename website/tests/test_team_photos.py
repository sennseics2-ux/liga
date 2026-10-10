"""Team pictures follow current appointments, survive upgrades and stay public."""
import io
import pytest
from PIL import Image
import database as store
from main import normalize_photo
from test_league import client, post, token
from test_v25_seasons import setup, PASSWORD


def picture(colour='blue'):
    data=io.BytesIO()
    Image.new('RGB',(640,320),colour).save(data,format='PNG')
    return data.getvalue()


def upload(client, team, contents=None, csrf=True):
    return client.post(f'/teams/{team}/photo',data={'csrf':token(client)} if csrf else {},
                       files={'photo':('team.png',contents if contents is not None else picture(),'image/png')})


def test_upload_replace_public_display_and_remove(client):
    _,_,_,match,teams,managers,_=setup();team=teams[0]
    assert client.get(f'/teams/{team}/photo').status_code==404
    assert 'id="team-photo"' not in client.get(f'/teams/{team}').text
    post(client,'/login',username='manager_home',password=PASSWORD)
    assert 'id="team-photo"' in client.get(f'/teams/{team}').text
    assert upload(client,team,csrf=False).status_code==403
    assert upload(client,team).status_code==200
    response=client.get(f'/teams/{team}/photo')
    assert response.headers['content-type']=='image/jpeg'
    assert response.headers['x-content-type-options']=='nosniff'
    image=Image.open(io.BytesIO(response.content));assert image.size==(512,512)
    old=response.content
    for path in ['/teams','/standings',f'/teams/{team}',f'/matches/{match}']:
        assert f'src="/teams/{team}/photo"' in client.get(path).text
    # Replacements use the same URL, with no stale browser/shared-cache images.
    assert response.headers['cache-control']=='no-store'
    assert upload(client,team,picture('red')).status_code==200
    assert client.get(f'/teams/{team}/photo').content!=old
    store.init_db()
    assert client.get(f'/teams/{team}/photo').status_code==200
    assert post(client,f'/teams/{team}/photo/remove').status_code==200
    assert client.get(f'/teams/{team}/photo').status_code==404
    assert f'src="/teams/{team}/photo"' not in client.get('/teams').text


def test_current_appointment_required_and_retains_picture_after_reassignment(client):
    _,_,_,_,teams,managers,_=setup();team=teams[0]
    assert upload(client,team).status_code==401
    post(client,'/login',username='manager_away',password=PASSWORD)
    assert upload(client,team).status_code==403
    assert post(client,f'/teams/{team}/photo/remove').status_code==403
    post(client,'/login',username='manager_home',password=PASSWORD)
    assert upload(client,team).status_code==200
    with store.transaction() as db:
        db.execute('UPDATE teams SET manager_id=NULL WHERE id=?',(team,))
    assert upload(client,team).status_code==403
    assert client.get(f'/teams/{team}/photo').status_code==200
    # Persistence guard also blocks appointment/account changes during decoding.
    with pytest.raises(PermissionError):
        store.save_team_photo(team,managers[0],normalize_photo(picture()))
    with pytest.raises(PermissionError):
        store.remove_team_photo(team,managers[0])
    with store.transaction() as db:
        db.execute('UPDATE teams SET manager_id=? WHERE id=?',(managers[0],team))
        db.execute('UPDATE users SET account_active=0 WHERE id=?',(managers[0],))
    with pytest.raises(PermissionError):
        store.save_team_photo(team,managers[0],normalize_photo(picture()))


def test_invalid_and_oversize_uploads_preserve_existing_picture(client):
    _,_,_,_,teams,_,_=setup();team=teams[0]
    post(client,'/login',username='manager_home',password=PASSWORD)
    upload(client,team);original=client.get(f'/teams/{team}/photo').content
    assert 'Invalid image' in upload(client,team,b'<svg onload="alert(1)"></svg>').text
    assert 'smaller than 5 MB' in upload(client,team,b'x'*(5*1024*1024+1)).text
    assert upload(client,team,b'x'*(6*1024*1024+1)).status_code==413
    assert client.get(f'/teams/{team}/photo').content==original


def test_upgrade_v29_adds_picture_storage_without_changing_league(client):
    _,_,_,_,teams,managers,_=setup()
    with store.transaction() as db:
        before=[tuple(r) for r in db.execute('SELECT id,name,manager_id,budget FROM teams ORDER BY id')]
        db.execute('DROP TABLE team_photos')
        db.execute("DELETE FROM schema_migrations WHERE version IN ('v30_team_photos','v32_shared_fide_ids')")
    # V29 may already have a pre-V25 backup: V30 must still snapshot its data.
    live=store.DB_PATH
    live.with_name(live.name+'.pre-v25.bak').write_bytes(b'old backup')
    store.init_db()
    assert live.with_name(live.name+'.pre-v30.bak').exists()
    with store.read_db() as db:
        assert [tuple(r) for r in db.execute('SELECT id,name,manager_id,budget FROM teams ORDER BY id')]==before
        assert db.execute("SELECT 1 FROM schema_migrations WHERE version='v25_accounts_seasons'").fetchone()
        assert db.execute("SELECT 1 FROM schema_migrations WHERE version='v30_team_photos'").fetchone()
        assert db.execute('SELECT COUNT(*) FROM team_photos').fetchone()[0]==0
