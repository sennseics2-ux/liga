"""V15 public URL, flag asset, and password security regression coverage."""
import re
from pathlib import Path
from fastapi.testclient import TestClient
from test_league import client, post, register, logout, seed_admin
import database as store
from main import app


def test_usernames_are_canonical_and_old_ids_redirect(client):
    register(client, 'ChessCaptain', 'manager')
    with store.read_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username='ChessCaptain'").fetchone()[0]
    assert client.get('/dashboard', follow_redirects=False).headers['location'] == '/users/ChessCaptain/manager'
    assert client.get('/users/ChessCaptain').status_code == 200
    assert client.get('/users/ChessCaptain/manager').status_code == 200
    assert client.get('/users/chesscaptain', follow_redirects=False).headers['location'] == '/users/ChessCaptain'
    assert client.get(f'/users/{uid}', follow_redirects=False).status_code == 308
    assert client.get(f'/users/{uid}', follow_redirects=False).headers['location'] == '/users/ChessCaptain'
    assert client.get(f'/users/{uid}/manager', follow_redirects=False).headers['location'] == '/users/ChessCaptain/manager'
    assert client.get(f'/users/{uid}/player', follow_redirects=False).headers['location'] == '/users/ChessCaptain'
    assert client.get('/users/unknown-name').status_code == 404
    assert client.get('/users/123456').status_code == 404
    with store.read_db() as db:
        assert db.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()[0] == 'ChessCaptain'


def test_names_used_in_links_with_existing_player_and_team(client):
    register(client, 'name_for_urls', 'manager')
    with store.read_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username='name_for_urls'").fetchone()[0]
    team = store.create_team('International Rooks')
    store.assign_manager(team, uid)
    assert 'href="/users/name_for_urls/manager"' in client.get('/standings').text
    assert 'href="/users/name_for_urls"' in client.get('/teams/'+str(team)).text
    assert 'href="/account/profile"' in client.get('/').text
    assert client.get('/account/profile', follow_redirects=False).headers['location'] == '/users/name_for_urls'


def test_flag_images_are_real_self_hosted_svg_assets(client):
    html = client.get('/').text
    assert '<img id="language-flag"' in html
    for flag in ('pt','gb'):
        response = client.get(f'/static/flags/{flag}.svg')
        assert response.status_code == 200
        assert '<svg' in response.text
        assert response.headers['content-type'].startswith('image/svg+xml')
    script = client.get('/static/i18n.js').text
    assert 'flag.src=' in script
    assert 'flag.textContent=' not in script


def test_change_password_requires_login_current_secret_and_csrf(client):
    assert client.get('/account/security').status_code == 401
    assert client.post('/account/security', data={'new_password':'NewPass!strong123'}).status_code == 401
    register(client, 'password_owner', 'player')
    page = client.get('/account/security')
    assert page.status_code == 200
    assert 'Current password' in page.text and 'Update password' in page.text
    assert 'Change password' in client.get('/my/player').text
    assert client.post('/account/security', data={'current_password':'x','new_password':'NewPass!strong123'}).status_code == 403
    wrong = post(client, '/account/security', current_password='wrong', new_password='NewPass!strong123', confirm_password='NewPass!strong123')
    assert 'Current password is incorrect.' in wrong.text
    mismatch = post(client, '/account/security', current_password='p4ssword!AB12',new_password='NewPass!strong123',confirm_password='different')
    assert 'New passwords do not match.' in mismatch.text
    short = post(client, '/account/security', current_password='p4ssword!AB12',new_password='short',confirm_password='short')
    assert '12–256' in short.text
    assert post(client, '/account/security',current_password='p4ssword!AB12',new_password='NewPass!strong123',confirm_password='NewPass!strong123').status_code == 200
    with store.read_db() as db:
        user = db.execute("SELECT * FROM users WHERE username='password_owner'").fetchone()
        assert user['auth_version'] == 1
        assert store.verify_password('NewPass!strong123',user['password_hash'])
        assert not store.verify_password('p4ssword!AB12',user['password_hash'])
    assert client.get('/account/security').status_code == 200
    logout(client)
    assert 'Incorrect username or password' in post(client,'/login',username='password_owner',password='p4ssword!AB12').text
    assert 'Password & security' in post(client,'/login',username='password_owner',password='NewPass!strong123').text or client.get('/account/security').status_code == 200


def test_password_change_revokes_another_browser_session(client):
    register(client,'two_browsers','player')
    with TestClient(app) as other:
        assert post(other,'/login',username='two_browsers',password='p4ssword!AB12').status_code == 200
        assert other.get('/account/security').status_code == 200
        changed=post(client,'/account/security',current_password='p4ssword!AB12',new_password='BetterPass!123456',confirm_password='BetterPass!123456')
        assert changed.status_code == 200
        assert client.get('/account/security').status_code == 200
        assert other.get('/account/security').status_code == 401


def test_admin_can_change_password_and_has_no_member_page(client):
    seed_admin()
    post(client,'/login',username='commissioner',password='adminpass123!')
    assert client.get('/account/security').status_code == 200
    assert 'Account Settings' in client.get('/admin').text
    assert client.get('/users/commissioner').status_code == 404
    post(client,'/account/security',current_password='adminpass123!',new_password='MyNewSuperStrongPass!123',confirm_password='MyNewSuperStrongPass!123')
    logout(client)
    assert 'Incorrect username or password' in post(client,'/login',username='commissioner',password='adminpass123!').text
    assert post(client,'/login',username='commissioner',password='MyNewSuperStrongPass!123').status_code == 200


def test_schema_upgrade_adds_auth_version_without_loss(client):
    register(client,'keep_user','player')
    with store.read_db() as db:
        account_before=db.execute("SELECT id,password_hash FROM users WHERE username='keep_user'").fetchone()
    store.init_db()
    with store.read_db() as db:
        account_after=db.execute("SELECT id,password_hash,auth_version FROM users WHERE username='keep_user'").fetchone()
    assert list(account_before)==list(account_after)[:2]
    assert account_after['auth_version']==0
