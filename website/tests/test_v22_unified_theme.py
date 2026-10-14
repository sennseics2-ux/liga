"""Homepage navigation and shared monochrome visual rules, V22."""
from pathlib import Path
from test_league import client

ROOT = Path(__file__).resolve().parents[1]

def test_home_link_swap_market_button_removal_without_market_removal(client):
    html = client.get('/').text
    player = html.split('<article class="role-card role-card-player">', 1)[1].split('</article>', 1)[0]
    manager = html.split('<article class="role-card role-card-manager">', 1)[1].split('</article>', 1)[0]
    assert 'href="/teams">Explore teams' in player
    assert 'href="/players">Explore players' in manager
    assert 'href="/players">Explore players' not in player
    assert 'href="/teams">Explore teams' not in manager
    assert 'View transfer market' not in html
    assert 'TRANSFER WINDOW' in html and 'On the auction block' in html
    assert '<a href="/auctions"' not in html  # hidden from top navigation
    assert client.get('/auctions').status_code == 200

def test_shared_monochrome_rules_on_other_pages(client):
    for route in ('/players', '/teams', '/auctions', '/games', '/standings', '/login'):
        assert client.get(route).status_code == 200
    css = (ROOT / 'static/style.css').read_text()
    assert '--pine:#171819' in css
    assert '.page-banner,.auth-pitch{background:#1a1b1c' in css
    assert '.btn-primary{background:#1d1e1f' in css
    assert '.replay-square.light{background:#efefef' in css
    assert '.replay-square.dark{background:#949494' in css
    assert 'style.css?v=91' in client.get('/players').text
