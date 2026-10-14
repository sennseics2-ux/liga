"""Member avatar upload/security and V6 -> V7 migrations."""
import io
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from test_league import client, post, register, logout, seed_admin
import database as store


def make_image(size=(720, 540), kind='PNG', color=(90, 115, 155)):
    img = Image.new('RGB', size, color)
    buffer = io.BytesIO()
    img.save(buffer, format=kind)
    return buffer.getvalue()


def upload(client, token, contents, name='picture.png', target='/my/player/photo'):
    return client.post(target, data={'csrf': token}, files={'photo': (name, contents, 'image/png')}, follow_redirects=True)


def test_photo_upload_public_display_and_replace(client):
    register(client, 'rookie', 'player')
    with store.read_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username='rookie'").fetchone()[0]
    profile_page = f'/users/{uid}'
    assert 'Upload photo' in client.get('/account/settings').text
    assert 'My player photo' not in client.get(profile_page).text
    assert 'Registered identity' not in client.get(profile_page).text
    assert 'Standard FIDE rating' not in client.get(profile_page).text
    assert client.get(f'{profile_page}/photo').status_code == 404
    csrf = client.get('/account/settings').text.split('name="csrf" value="')[1].split('"')[0]
    response = upload(client, csrf, make_image())
    assert response.status_code == 200
    assert response.url.path == '/account/settings'
    assert 'Your profile photo has been updated' in response.text
    assert 'Replace photo' in response.text
    assert '/users/rookie/photo' in response.text
    portrait = client.get(f'{profile_page}/photo')
    assert portrait.status_code == 200
    assert portrait.headers['content-type'] == 'image/jpeg'
    assert portrait.headers['cache-control'] == 'no-store'
    with Image.open(io.BytesIO(portrait.content)) as img:
        assert img.size == (512, 512)
        assert img.format == 'JPEG'
        assert img.getexif() == {}  # metadata is stripped
    # The Players directory shows administrator-added chess profiles, not every registered account.
    store.create_player('Rookie Chess Player',user_id=uid)
    assert '/users/rookie/photo' in client.get('/players').text
    old_content = portrait.content
    response = upload(client, csrf, make_image(color=(180, 80, 100)))
    assert response.status_code == 200
    assert client.get(f'{profile_page}/photo').content != old_content
    # User can remove the photo using CSRF, and it disappears publicly.
    result = post(client, '/my/player/photo/remove')
    assert 'Your profile photo was removed' in result.text
    assert result.url.path == '/account/settings'
    assert client.get(f'{profile_page}/photo').status_code == 404


def test_photo_validation_and_old_image_untouched(client):
    register(client, 'photographer', 'player')
    with store.read_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username='photographer'").fetchone()[0]
    csrf = client.get('/account/settings').text.split('name="csrf" value="')[1].split('"')[0]
    upload(client, csrf, make_image())
    before = client.get(f'/users/{uid}/photo').content
    for name, body in [
        ('evil.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
        ('invalid.png', b'not an image'),
        ('huge.png', b'x'*(5*1024*1024+1)),
        ('animation.gif', make_image(kind='GIF')),
    ]:
        res = upload(client, csrf, body, name=name)
        assert res.status_code == 200
        assert 'notice-error' in res.text
        assert client.get(f'/users/{uid}/photo').content == before
    assert client.post('/my/player/photo', data={'csrf': 'bad'}, files={'photo': ('x.jpg', make_image(), 'image/jpeg')}).status_code == 403


def test_not_logged_in_and_manager_only_cannot_upload(client):
    assert client.post('/my/player/photo', data={'csrf': 'x'}, files={'photo': ('x.png', make_image(), 'image/png')}).status_code == 401
    register(client, 'chief', 'manager')
    result = client.get('/dashboard')
    csrf = result.text.split('name="csrf" value="')[1].split('"')[0]
    # Managers register with both roles active under V6; the same account uploads a photo.
    assert upload(client, csrf, make_image()).status_code == 200
    # Managers keep the same photo when appointed to a team.
    with store.read_db() as db:
        uid = db.execute("SELECT id FROM users WHERE username='chief'").fetchone()[0]
    tid = store.create_team('Photo Knights')
    store.assign_manager(tid, uid)
    assert upload(client, csrf, make_image()).status_code == 200
    logout(client)
    register(client, 'reader', 'player')
    with store.read_db() as db:
        mid = db.execute("SELECT id FROM users WHERE username='chief'").fetchone()[0]
    # Visitor can see the photo but not an upload form for someone else's page.
    other = client.get(f'/users/{mid}')
    assert '/users/chief/photo' in other.text
    assert '/my/player/photo"' not in other.text
    assert client.get(f'/users/{mid}/photo').status_code == 200


def test_admin_and_inactive_role_cannot_upload(client):
    register(client, 'sometimes', 'player')
    post(client, '/my/roles/player/quit')
    csrf = client.get('/').text.split('name="csrf" value="')[1].split('"')[0]
    assert client.post('/my/player/photo', data={'csrf': csrf}, files={'photo': ('x.png', make_image(), 'image/png')}).status_code == 403
    logout(client)
    seed_admin()
    post(client, '/login', username='commissioner', password='adminpass123!')
    csrf = client.get('/').text.split('name="csrf" value="')[1].split('"')[0]
    assert client.post('/my/player/photo', data={'csrf': csrf}, files={'photo': ('x.png', make_image(), 'image/png')}).status_code == 403


def test_existing_v6_database_migrates_photos_without_losing_existing_data(tmp_path, monkeypatch, legacy_database_factory):
    original = legacy_database_factory(6)
    target = tmp_path / 'v6data.sqlite3'
    target.write_bytes(original.read_bytes())
    monkeypatch.setattr(store, 'DB_PATH', target)
    with sqlite3.connect(target) as db:
        before_users = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        before_teams = db.execute('SELECT COUNT(*) FROM teams').fetchone()[0]
        before_bids = db.execute('SELECT COUNT(*) FROM bids').fetchone()[0]
    store.init_db()
    store.init_db()
    with store.read_db() as db:
        fields = {r['name'] for r in db.execute('PRAGMA table_info(users)')}
        assert {'photo_data', 'photo_updated_at'} <= fields
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == before_users
        assert db.execute('SELECT COUNT(*) FROM teams').fetchone()[0] == before_teams
        assert db.execute('SELECT COUNT(*) FROM bids').fetchone()[0] == before_bids
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
