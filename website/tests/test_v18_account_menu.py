"""V18 consolidated user dropdown and profile entry-point regression tests."""
import json
from pathlib import Path

from test_league import client, post, register, logout, seed_admin


def test_signed_out_navigation_does_not_show_account_menu(client):
    page = client.get('/')
    assert page.status_code == 200
    assert 'id="account-toggle"' not in page.text
    assert 'id="account-menu"' not in page.text
    assert client.get('/account/profile').status_code == 401


def test_member_menu_links_and_profile_redirect(client):
    register(client, 'user_menu_example', 'player')
    html = client.get('/').text
    assert '<button type="button" id="account-toggle"' in html
    assert '<div id="account-menu" class="account-menu" hidden>' in html
    assert html.count('href="/account/profile"') == 1
    assert html.count('href="/account/security"') == 1
    assert html.count('action="/logout"') == 1
    assert 'Sign out</button>' in html
    assert 'id="account-toggle"' in html and 'user_menu_example' in html
    # The old separate links and logout buttons were removed.
    assert 'class="account-settings-link"' not in html
    assert 'class="logged-in account-link"' not in html
    assert 'Log out</button>' not in html
    profile = client.get('/account/profile', follow_redirects=False)
    assert profile.status_code == 303
    assert profile.headers['location'] == '/users/user_menu_example'
    assert client.get('/users/user_menu_example').status_code == 200
    assert client.get('/account/security').status_code == 200
    # Logout remains a CSRF-protected POST, not a GET.
    assert client.get('/logout').status_code == 405
    assert client.post('/logout').status_code == 403
    assert post(client, '/logout').status_code == 200
    assert client.get('/account/profile').status_code == 401


def test_administrator_profile_stays_private(client):
    seed_admin()
    post(client, '/login', username='commissioner', password='adminpass123!')
    html = client.get('/admin').text
    assert 'id="account-toggle"' in html
    assert 'commissioner' in html
    assert 'href="/account/profile"' in html
    resp = client.get('/account/profile')
    assert resp.status_code == 200
    assert 'Administrator profile' in resp.text
    assert 'commissioner' in resp.text
    assert 'href="/admin"' in resp.text
    assert client.get('/account/security').status_code == 200
    logout(client)
    assert client.get('/account/profile').status_code == 401


def test_account_menu_translations_exist_and_client_script_wired(client):
    catalogue = json.loads((Path(__file__).parents[1]/'static'/'pt-PT.json').read_text())
    for english, portuguese in {'Profile':'Perfil','Account Settings':'Definições da conta',
                                 'Sign out':'Terminar sessão'}.items():
        assert catalogue[english] == portuguese
    script = client.get('/static/app.js').text
    assert "getElementById('account-toggle')" in script
    assert "getElementById('account-menu')" in script
    assert "event.key === 'Escape'" in script
