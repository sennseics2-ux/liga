"""The language picker must stay at the far right of the account controls."""
from pathlib import Path
from test_league import client, register, logout, seed_admin, post


def test_signed_in_member_header_order(client):
    register(client, 'navigationcheck', 'player')
    html = client.get('/').text
    assert html.index('class="account-dropdown"') < html.index('class="language-picker"')
    assert html.count('id="language-toggle"') == 1
    css = (Path(__file__).parents[1] / 'static' / 'style.css').read_text()
    assert '.account-dropdown{position:relative;flex:0 1 auto;min-width:0;order:0}' in css
    assert '.language-picker{position:relative;order:9;' in css


def test_signed_in_admin_header_order(client):
    seed_admin()
    post(client, '/login', username='commissioner', password='adminpass123!')
    html = client.get('/admin').text
    assert html.index('class="account-dropdown"') < html.index('class="language-picker"')


def test_signed_out_header_has_language_picker(client):
    html = client.get('/').text
    assert 'class="account-dropdown"' not in html
    assert html.index('href="/register"') < html.index('class="language-picker"')
