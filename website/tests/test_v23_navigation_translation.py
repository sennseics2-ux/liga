"""V23 removes top-navigation market link without disabling auctions."""
import json
from pathlib import Path
from test_league import client

ROOT = Path(__file__).resolve().parents[1]


def test_market_absent_from_top_nav_but_route_works(client):
    home = client.get('/')
    assert home.status_code == 200
    nav = home.text.split('<div class="nav-links"', 1)[1].split('</div>', 1)[0]
    assert 'href="/auctions"' not in nav
    assert 'Transfer market</a>' not in nav
    assert client.get('/auctions').status_code == 200
    assert 'On the auction block' in home.text


def test_informal_portuguese_is_built_into_browser_bundle(client):
    catalogue = json.loads((ROOT/'static/pt-PT.json').read_text())
    assert catalogue['Join your club'] == 'Junta-te ao clube'
    assert '"Join your club":"Junta-te ao clube"' in client.get('/static/i18n.js').text
    assert 'i18n.js?v=78' in client.get('/').text
